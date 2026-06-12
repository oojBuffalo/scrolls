"""arXiv fetch adapter (IDEAS.md §6, ADR 0008, ADR 0010).

One GET against the keyless arXiv export API returns an Atom feed parsed
with stdlib ElementTree — no auth required. The abstract is the paper's
summary by definition, so it maps to `summary` and is indexed for
search. The feed's PDF link is kept as a `media` entry, and the PDF is
downloaded and its full text extracted with pypdf into `extracted_text`
(ADR 0010); any PDF failure degrades to the abstract-only scroll rather
than failing the fetch, the same contract as caption-less youtube
videos. Taxonomy category codes (`cs.CL`) go to `tags`; their display
names from the bundled taxonomy table ("Computation and Language")
become `concepts`, joining github topics and wikipedia categories in the
KB's concept graph (ADR 0012). The raw feed is kept in `raw_text` so
scrolls and indexes can be rebuilt without refetching.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlencode
from xml.etree import ElementTree

from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http
from scrolls.sources.arxiv_taxonomy import CATEGORY_NAMES

API_ROOT = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"

GetText = Callable[[str], str]
GetBytes = Callable[[str], bytes]


def fetch_item(
    item: ScrollItem,
    *,
    get_text: GetText | None = None,
    get_bytes: GetBytes | None = None,
) -> ScrollItem:
    """Fetch a detected arXiv paper's metadata, abstract, and PDF full text.

    Returns the item at stage 'fetched'. Raises FetchError when the paper
    identity is missing, the request fails, or the API reports an
    unknown/malformed id; PDF problems never raise — the scroll degrades
    to abstract-only. The input item is never mutated.
    """
    get_text = get_text or _get_text
    get_bytes = get_bytes or _get_bytes
    if not item.source_id:
        raise FetchError(f"cannot determine arxiv paper for item {item.id!r}")

    url = f"{API_ROOT}?{urlencode({'id_list': item.source_id, 'max_results': 1})}"
    try:
        feed_text = get_text(url)
        feed = ElementTree.fromstring(feed_text)
    except (OSError, ValueError, ElementTree.ParseError) as exc:
        raise FetchError(f"arxiv API request failed: {exc}") from exc

    entry = feed.find(f"{_ATOM}entry")
    if entry is None:
        raise FetchError(f"arxiv paper not found: {item.source_id}")
    entry_id = _text(entry, "id")
    if "/api/errors" in entry_id:
        raise FetchError(f"arxiv API error: {_text(entry, 'summary') or entry_id}")

    abstract = _text(entry, "summary") or None
    authors = [
        name.text.strip()
        for name in entry.findall(f"{_ATOM}author/{_ATOM}name")
        if name.text and name.text.strip()
    ]
    pdf_url = _link_href(entry, title="pdf")
    full_text = _pdf_text(pdf_url, get_bytes) if pdf_url else None
    extraction_method = "arxiv-api:atom"
    if full_text:
        import pypdf

        extraction_method = f"arxiv-api:atom+pypdf-{pypdf.__version__}"

    codes = tuple(
        dict.fromkeys(
            category.get("term")
            for category in entry.findall(f"{_ATOM}category")
            if category.get("term")
        )
    )
    hashed = full_text or abstract or feed_text
    return replace(
        item,
        title=_text(entry, "title") or item.title,
        author=", ".join(authors) or None,
        published_at=_text(entry, "published") or None,
        canonical_url=_link_href(entry, rel="alternate") or entry_id or None,
        raw_text=feed_text,
        extracted_text=full_text,
        summary=abstract,
        tags=codes,
        concepts=tuple(
            dict.fromkeys(
                CATEGORY_NAMES[code] for code in codes if code in CATEGORY_NAMES
            )
        ),
        media=({"type": "pdf", "url": pdf_url},) if pdf_url else (),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "arxiv",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": extraction_method,
        },
        stage="fetched",
    )


def _pdf_text(pdf_url: str, get_bytes: GetBytes) -> str | None:
    """The paper's PDF text, or None when anything fails (degradation contract).

    pypdf is imported lazily so commands that never fetch a paper don't
    pay for it (same pattern as trafilatura in the web adapter).
    """
    import io

    from pypdf import PdfReader

    # the feed advertises plain-http links that arxiv redirects anyway
    if pdf_url.startswith("http://"):
        pdf_url = "https://" + pdf_url.removeprefix("http://")
    try:
        reader = PdfReader(io.BytesIO(get_bytes(pdf_url)))
        pages = (page.extract_text() for page in reader.pages)
        text = "\n\n".join(part.strip() for part in pages if part.strip()).strip()
    except Exception:  # any PDF failure must keep the abstract-only scroll
        return None
    return text or None


def _text(entry: ElementTree.Element, name: str) -> str:
    """Element text with the Atom feed's line-wrapping whitespace collapsed."""
    return " ".join((entry.findtext(f"{_ATOM}{name}") or "").split())


def _link_href(entry: ElementTree.Element, **attrs: str) -> str | None:
    for link in entry.findall(f"{_ATOM}link"):
        if all(link.get(key) == value for key, value in attrs.items()):
            return link.get("href")
    return None


_get_text = http.get_text
_get_bytes = http.get_bytes
