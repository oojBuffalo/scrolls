"""Wikipedia fetch adapter (IDEAS.md §6, ADR 0002).

One GET against the MediaWiki action API (`prop=extracts|info`,
`explaintext`, `redirects`) returns the full plain-text page plus its
canonical URL — no auth, no runtime dependencies. The raw page object is
kept in `raw_text` so scrolls and indexes can be rebuilt without refetching.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlencode

from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

_API_PARAMS = {
    "action": "query",
    "format": "json",
    "formatversion": "2",
    "redirects": "1",
    "prop": "extracts|info",
    "explaintext": "1",
    "inprop": "url",
}

GetJson = Callable[[str], dict[str, Any]]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected Wikipedia item's page text; return the item at stage 'fetched'.

    Raises FetchError when the page identity is missing, the request fails,
    or the page does not exist. The input item is never mutated.
    """
    get_json = get_json or _get_json
    lang, _, title = (item.source_id or "").partition(":")
    if not lang or not title:
        raise FetchError(f"cannot determine wikipedia page for item {item.id!r}")

    url = _api_url(lang, title)
    try:
        payload = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"wikipedia API request failed: {exc}") from exc

    page = _single_page(payload)
    extract = page.get("extract") or ""
    if page.get("missing") or not extract:
        raise FetchError(f"wikipedia page not found: {lang}:{title}")

    return replace(
        item,
        title=page.get("title") or item.title,
        canonical_url=page.get("canonicalurl") or page.get("fullurl"),
        raw_text=json.dumps(page, ensure_ascii=False),
        extracted_text=extract,
        summary=_lead_section(extract),
        content_hash="sha256:" + hashlib.sha256(extract.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "wikipedia",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "mediawiki-api:extracts",
        },
        stage="fetched",
    )


def _api_url(lang: str, title: str) -> str:
    query = urlencode({**_API_PARAMS, "titles": title})
    return f"https://{lang}.wikipedia.org/w/api.php?{query}"


def _single_page(payload: dict[str, Any]) -> dict[str, Any]:
    pages = payload.get("query", {}).get("pages") or []
    if not pages:
        raise FetchError("wikipedia API returned no pages")
    return pages[0]


def _lead_section(extract: str) -> str:
    """Plain-text extract before the first '== Heading ==' marker."""
    return extract.split("\n==", 1)[0].strip()


_get_json = http.get_json
