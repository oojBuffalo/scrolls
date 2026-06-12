"""Generic PDF fetch adapter (ADR 0013).

Downloads the document with the shared transport and extracts text and
document-information metadata with pypdf (already a dependency via the
arXiv adapter). Unlike platform adapters there is no API to lean on:
identity is the URL (hash-based item id, like `web`), the title comes
from `/Title` metadata or the URL filename, and `/Subject` is the only
honest summary candidate. The binary is the raw record — it is *not*
stored in `raw_text`; the content hash pins the exact bytes and
`scrolls media` captures the file via the item's media ref. A payload
that isn't a readable PDF (error page, paywall stub) fails the fetch,
while a real PDF with no extractable text (scanned pages, encryption)
degrades to a metadata-only scroll whose document is still captured.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

GetBytes = Callable[[str], bytes]

_SEPARATORS = re.compile(r"[-_+\s]+")


def fetch_item(item: ScrollItem, *, get_bytes: GetBytes | None = None) -> ScrollItem:
    """Fetch a detected PDF's text and metadata; return it at stage 'fetched'.

    Raises FetchError when the download fails or the payload is not a
    readable PDF. Text extraction failure degrades to a metadata-only
    scroll. The input item is never mutated.
    """
    import pypdf

    get_bytes = get_bytes or _get_bytes
    try:
        blob = get_bytes(item.url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"pdf download failed: {exc}") from exc

    try:
        reader = pypdf.PdfReader(io.BytesIO(blob))
    except Exception as exc:
        raise FetchError(f"not a readable PDF: {item.url} ({exc})") from exc

    meta = _metadata(reader)
    return replace(
        item,
        title=meta.get("title") or _filename_title(item.url) or item.title,
        author=meta.get("author"),
        published_at=to_utc_iso(meta.get("created")) or item.published_at,
        canonical_url=item.url,
        extracted_text=_pages_text(reader),
        summary=meta.get("subject"),
        media=({"type": "pdf", "url": item.url},),
        content_hash="sha256:" + hashlib.sha256(blob).hexdigest(),
        provenance={
            "adapter": "pdf",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": f"pypdf-{pypdf.__version__}",
        },
        stage="fetched",
    )


def extract_text(blob: bytes) -> str | None:
    """All page text of a PDF, or None when anything fails (degradation contract).

    Shared with the arXiv adapter, which applies the same contract to
    paper PDFs (ADR 0010). pypdf is imported lazily so commands that
    never fetch don't pay for it.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(blob))
    except Exception:
        return None
    return _pages_text(reader)


def _pages_text(reader: Any) -> str | None:
    try:
        pages = (page.extract_text() for page in reader.pages)
        text = "\n\n".join(part.strip() for part in pages if part.strip()).strip()
    except Exception:  # encrypted or broken pages keep the metadata-only scroll
        return None
    return text or None


def _metadata(reader: Any) -> dict[str, str]:
    """Document-information fields worth keeping, each independently fallible."""
    try:
        info = reader.metadata
    except Exception:
        return {}
    if info is None:
        return {}
    fields: dict[str, str] = {}
    for key in ("title", "author", "subject"):
        try:
            value = (getattr(info, key) or "").strip()
        except Exception:
            value = ""
        if value:
            fields[key] = value
    try:
        created = info.creation_date
    except Exception:
        created = None
    if created:
        fields["created"] = created.isoformat()
    return fields


def _filename_title(url: str) -> str | None:
    """The URL's filename as a readable title: 'attention-is-all-you-need' style."""
    stem = PurePosixPath(unquote(urlparse(url).path)).stem
    return _SEPARATORS.sub(" ", stem).strip() or None


_get_bytes = http.get_bytes
