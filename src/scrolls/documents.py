"""Captured PDF documents as part of the scroll (ADR 0114, issue #10).

A PDF can be held as a *media file* of another item — the report attached
to a Wikipedia article, say. `scrolls media` reads such a document's text
through the same pypdf seam the `pdf` and `arxiv` adapters use
(`scrolls.sources.pdf.extract_text`) and records it on the media ref, and
the scroll renders it under `## Documents`. Pure functions only: the disk
and the download live in `scrolls.media`.

Each held document is in exactly one of three states, kept apart per the
completeness contract (ADR 0102 §3) so "nothing there" is never confused
with "never looked":

- **read** — `ref["text"]` holds the text and `ref["text_method"]` names
  the extractor that produced it;
- **read, nothing extractable** — `ref["text"]` is None (a scanned or
  encrypted PDF); the file stays held;
- **not read yet** — no `text` key at all.

The text is a derived view of the held file, like a summary: it is never
part of `content_hash`, and re-reading the file regenerates it.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

from scrolls.items import ScrollItem

_PDF_SUFFIX = ".pdf"


def is_pdf(ref: Any) -> bool:
    """True for a media ref that points at a PDF, by type or by file name."""
    if not isinstance(ref, dict):
        return False
    if ref.get("type") == "pdf":
        return True
    names = (ref.get("path") or "", urlsplit(ref.get("url") or "").path)
    return any(name.lower().endswith(_PDF_SUFFIX) for name in names)


def read_by_adapter(item: ScrollItem) -> bool:
    """True when the item's own adapter already read its PDF into the body.

    The `pdf` and `arxiv` adapters extract the document they capture into
    `extracted_text` and say so with a pypdf extraction method. Reading the
    same file again would print the text twice; an arXiv paper whose PDF
    text failed at fetch carries no pypdf method and does get a reading.
    """
    method = (item.provenance or {}).get("extraction_method") or ""
    return bool(item.extracted_text) and "pypdf" in method


def wants_text(item: ScrollItem, ref: Any) -> bool:
    """True when this ref is a document whose text belongs on the ref."""
    return is_pdf(ref) and not read_by_adapter(item)


def is_held(ref: Any) -> bool:
    """True when the ref records a captured file (not declined, not pending)."""
    return isinstance(ref, dict) and bool(ref.get("path")) and "oversize" not in ref


def frontmatter_ref(ref: Any) -> Any:
    """The ref as frontmatter shows it: everything but the document text.

    The text can run to megabytes and is rendered in the body instead;
    `text_method` stays so the frontmatter still says it was read.
    """
    if isinstance(ref, dict) and "text" in ref:
        return {key: value for key, value in ref.items() if key != "text"}
    return ref


def sections(item: ScrollItem) -> list[tuple[str, str]]:
    """`(heading, body)` for each held document, in media order.

    Documents that are not held are left to the frontmatter, which already
    records a declined or pending file.
    """
    out = []
    for ref in item.media:
        if not (wants_text(item, ref) and is_held(ref)):
            continue
        heading = _display_name(ref)
        if "text" not in ref:
            body = (
                f"_Not read yet: run `scrolls media` to read the held PDF "
                f"(`{ref['path']}`)._"
            )
        elif ref["text"] is None:
            body = (
                f"_No extractable text: the PDF is held at `{ref['path']}`, but "
                "its pages carry no text layer or it is encrypted._"
            )
        else:
            body = ref["text"]
        out.append((heading, body))
    return out


def _display_name(ref: dict[str, Any]) -> str:
    """The document's own file name from its URL, else the held file's name."""
    name = PurePosixPath(unquote(urlsplit(ref.get("url") or "").path)).name
    return name or PurePosixPath(ref["path"]).name
