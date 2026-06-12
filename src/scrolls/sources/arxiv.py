"""arXiv fetch adapter (IDEAS.md §6, ADR 0008).

One GET against the keyless arXiv export API returns an Atom feed parsed
with stdlib ElementTree — no auth, no runtime dependencies. The abstract
is the paper's summary by definition, so it maps to `summary` and is
indexed for search; `extracted_text` stays empty until a PDF-extraction
slice can supply full text, and the PDF link is kept as a `media` entry
for it. Taxonomy category codes (`cs.CL`) go to `tags`, not `concepts` —
they are curated but not readable concept names. The raw feed is kept in
`raw_text` so scrolls and indexes can be rebuilt without refetching.
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

API_ROOT = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"

GetText = Callable[[str], str]


def fetch_item(item: ScrollItem, *, get_text: GetText | None = None) -> ScrollItem:
    """Fetch a detected arXiv paper's metadata and abstract; return it at stage 'fetched'.

    Raises FetchError when the paper identity is missing, the request
    fails, or the API reports an unknown/malformed id. The input item is
    never mutated.
    """
    get_text = get_text or _get_text
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
    hashed = abstract or feed_text
    return replace(
        item,
        title=_text(entry, "title") or item.title,
        author=", ".join(authors) or None,
        published_at=_text(entry, "published") or None,
        canonical_url=_link_href(entry, rel="alternate") or entry_id or None,
        raw_text=feed_text,
        summary=abstract,
        tags=tuple(dict.fromkeys(
            category.get("term")
            for category in entry.findall(f"{_ATOM}category")
            if category.get("term")
        )),
        media=({"type": "pdf", "url": pdf_url},) if pdf_url else (),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "arxiv",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "arxiv-api:atom",
        },
        stage="fetched",
    )


def _text(entry: ElementTree.Element, name: str) -> str:
    """Element text with the Atom feed's line-wrapping whitespace collapsed."""
    return " ".join((entry.findtext(f"{_ATOM}{name}") or "").split())


def _link_href(entry: ElementTree.Element, **attrs: str) -> str | None:
    for link in entry.findall(f"{_ATOM}link"):
        if all(link.get(key) == value for key, value in attrs.items()):
            return link.get("href")
    return None


_get_text = http.get_text
