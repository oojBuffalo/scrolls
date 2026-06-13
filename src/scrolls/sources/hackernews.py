"""Hacker News fetch adapter (IDEAS.md §6, ADR 0031).

Item metadata comes from the keyless Firebase API
(`/v0/item/<id>.json`) in one request — no auth, no runtime dependency.
A text post (Ask HN, a Show HN with body, a comment) contributes its
HTML-stripped text as the searchable content, with the lead paragraph
as the summary the way Wikipedia leads. A link post has no body of its
own, so it degrades to a metadata-only scroll: the summary states the
discussion's points/comments, and the linked article rides along in
`links` as a bare URL — one `scrolls add` away, and resolvable by
`scrolls related`. The raw item object is kept in `raw_text` for
rebuilds, so `kids` (comment ids) survive for a future comment-tree
enrichment without a refetch.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from scrolls.dates import epoch_to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

API_ROOT = "https://hacker-news.firebaseio.com/v0"

GetJson = Callable[[str], Any]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected Hacker News item; return it at stage 'fetched'.

    Raises FetchError when the item id is missing/non-numeric, the request
    fails, or the item does not exist or was deleted/flagged. The input
    item is never mutated.
    """
    get_json = get_json or _get_json
    if not item.source_id or not item.source_id.isdigit():
        raise FetchError(f"cannot determine hacker news item for item {item.id!r}")

    url = f"{API_ROOT}/item/{item.source_id}.json"
    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"hacker news API request failed: {exc}") from exc

    if not isinstance(data, dict):  # a nonexistent id answers with JSON null
        raise FetchError(f"hacker news item not found: {item.source_id}")
    if data.get("deleted") or data.get("dead"):
        raise FetchError(f"hacker news item unavailable: {item.source_id}")

    text = _html_to_text(data.get("text") or "")
    article_url = data.get("url")
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    hashed = text or raw
    method = "hn-firebase:item+text" if text else "hn-firebase:item"
    return replace(
        item,
        title=_title(item, data),
        author=data.get("by") or None,
        published_at=epoch_to_utc_iso(str(data.get("time"))) or item.published_at,
        canonical_url=f"https://news.ycombinator.com/item?id={item.source_id}",
        raw_text=raw,
        extracted_text=text or None,
        summary=_summary(text, data),
        links=(article_url,) if article_url else (),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "hackernews",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _title(item: ScrollItem, data: dict[str, Any]) -> str | None:
    """The item's title; comments carry none, so synthesize one."""
    title = data.get("title")
    if title:
        return title
    if data.get("type") == "comment":
        by = data.get("by")
        return f"Comment by {by}" if by else "Hacker News comment"
    return item.title  # feed-seeded, else None (render falls back to the id)


def _summary(text: str, data: dict[str, Any]) -> str | None:
    """A text post's lead paragraph, else a link post's discussion status.

    A link post has no body to summarize, so its honest summary is what
    Hacker News itself adds: points and comment count. With neither (a
    bare metadata stub), there is nothing honest to say.
    """
    if text:
        return text.split("\n\n", 1)[0].strip()
    score, comments = data.get("score"), data.get("descendants")
    if score is None and comments is None:
        return None
    points = 0 if score is None else score
    replies = 0 if comments is None else comments
    return (
        f"Hacker News discussion: {points} {_plural(points, 'point')}, "
        f"{replies} {_plural(replies, 'comment')}."
    )


def _plural(count: int, noun: str) -> str:
    return noun if count == 1 else noun + "s"


def _html_to_text(html_text: str) -> str:
    """HN's limited HTML subset to plain text.

    `<p>` is a paragraph separator (HN emits no closing tag); other tags
    (`<i>`, `<a>`, `<pre><code>`) are dropped. Real markup is stripped
    before entities are unescaped, so escaped angle brackets in quoted
    code survive as literal text rather than being mistaken for tags.
    """
    text = html_text.replace("<p>", "\n\n")
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_get_json = http.get_json
