"""Web article fetch adapter (IDEAS.md §6).

Downloads the page with the shared transport and extracts readable
article text and metadata with trafilatura. The raw record kept in
`raw_text` is trafilatura's JSON output, not the page HTML — scrolls and
indexes can be rebuilt from it without storing full markup per page.
trafilatura is imported lazily so commands that never fetch don't pay
its (lxml-sized) import cost.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

GetHtml = Callable[[str], str]


def fetch_item(item: ScrollItem, *, get_html: GetHtml | None = None) -> ScrollItem:
    """Fetch a detected web item's article; return the item at stage 'fetched'.

    Raises FetchError when the download fails or the page has no
    extractable article content. The input item is never mutated.
    """
    import trafilatura

    get_html = get_html or _get_html
    try:
        html = get_html(item.url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"web request failed: {exc}") from exc

    extracted = trafilatura.extract(
        html, output_format="json", with_metadata=True, url=item.url
    )
    if not extracted:
        raise FetchError(f"could not extract article content from {item.url}")
    data = json.loads(extracted)
    text = (data.get("text") or "").strip()
    if not text:
        raise FetchError(f"could not extract article text from {item.url}")

    return replace(
        item,
        title=data.get("title") or item.title,
        author=data.get("author") or None,
        published_at=to_utc_iso(data.get("date")) or item.published_at,
        canonical_url=data.get("source") or item.url,
        raw_text=extracted,
        extracted_text=text,
        summary=data.get("excerpt") or text.split("\n", 1)[0],
        content_hash="sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "web",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": f"trafilatura-{trafilatura.__version__}",
        },
        stage="fetched",
    )


_get_html = http.get_text
