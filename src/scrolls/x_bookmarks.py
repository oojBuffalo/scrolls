"""Native X bookmarks collection parsing (lineage:
`docs/inspiration/fieldtheory-cli-inspiration.md`).

Turns one page of X's internal GraphQL bookmarks response into fetched `x`
items. The transport lives in `x_graphql.py` and the browser session in
`x_session.py`; this module is pure so the response shape — the part X
changes without notice — is testable against fixtures alone.

Item ids are `x:<tweetId>`, matching what `sources/detect.py` produces for
x.com status URLs, so `scrolls add` of a post and a later bookmarks pull
converge on one item. Items enter at stage 'fetched': the GraphQL payload
already carries the body, so there is nothing left to fetch.

Two shape notes, both learned from the response rather than assumed:

- **Author** moved from `core.user_results.result.legacy` to `…result.core`.
  Both are read; whichever is present wins.
- **There is no bookmark timestamp.** X orders bookmarks by an opaque
  `sortIndex` that is, in Field Theory's own words, "useful for chronology,
  not timestamps". Rather than invent a save time by decoding it, `saved_at`
  falls back to the sync time and `provenance.saved_at_source` records that it
  did. The raw `sortIndex` is preserved for ordering.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from scrolls.items import ScrollItem, make_item_id

_POSTED_AT_FORMAT = "%a %b %d %H:%M:%S %z %Y"  # "Mon Jun 01 15:34:00 +0000 2026"
_MAX_TITLE_LENGTH = 80
_CURSOR_PREFIX = "cursor-bottom"

# X wraps some posts in a visibility envelope; the real tweet hangs off `.tweet`.
_VISIBILITY_TYPENAME = "TweetWithVisibilityResults"
# Anything else non-Tweet (TweetTombstone, TweetUnavailable) is a bookmark whose
# post was deleted or hidden. It is a fact about X, not a parse failure.
_TWEET_TYPENAMES = {"Tweet", _VISIBILITY_TYPENAME}


@dataclass(frozen=True)
class BookmarksPage:
    """One parsed page of the bookmarks timeline.

    Attributes:
        items: Fetched `x` items, in the order X returned them.
        next_cursor: Cursor for the following page, or None at the end.
        failures: Per-entry problems that did not abort the page, each a dict
            with `entry_id` and `error`.
    """

    items: tuple[ScrollItem, ...] = ()
    next_cursor: str | None = None
    failures: tuple[dict, ...] = ()


def parse_bookmarks_page(payload: dict, *, synced_at: str) -> BookmarksPage:
    """Parse one GraphQL bookmarks response into items and a cursor.

    Args:
        payload: The decoded JSON body of a Bookmarks GraphQL call.
        synced_at: UTC ISO-8601 timestamp for this sync run, used as the
            `saved_at` fallback and as `provenance.fetched_at`.

    Returns:
        A BookmarksPage. A malformed entry becomes a failure rather than
        aborting the page, mirroring `scrolls fetch` batch semantics.
    """
    items: list[ScrollItem] = []
    failures: list[dict] = []
    next_cursor: str | None = None

    for entry in _entries(payload):
        entry_id = entry.get("entryId") or ""
        if entry_id.startswith(_CURSOR_PREFIX):
            value = (entry.get("content") or {}).get("value")
            if isinstance(value, str) and value:
                next_cursor = value
            continue

        result = _tweet_result(entry)
        if result is None:
            continue
        try:
            items.append(_to_item(result, entry, synced_at))
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            failures.append({"entry_id": entry_id, "error": str(exc)})

    return BookmarksPage(tuple(items), next_cursor, tuple(failures))


def _entries(payload: dict) -> list[dict]:
    """Collect entries from every TimelineAddEntries instruction."""
    timeline = (
        ((payload or {}).get("data") or {})
        .get("bookmark_timeline_v2", {})
        .get("timeline", {})
    )
    entries: list[dict] = []
    for instruction in timeline.get("instructions") or ():
        if instruction.get("type") == "TimelineAddEntries":
            entries.extend(instruction.get("entries") or ())
    return entries


def _tweet_result(entry: dict) -> dict | None:
    """The tweet subtree for an entry, or None if it holds no live post."""
    result = (
        ((entry.get("content") or {}).get("itemContent") or {})
        .get("tweet_results", {})
        .get("result")
    )
    if not isinstance(result, dict):
        return None
    typename = result.get("__typename")
    if typename == _VISIBILITY_TYPENAME:
        result = result.get("tweet") or result
    elif typename is not None and typename not in _TWEET_TYPENAMES:
        return None
    return result


def tweet_result(payload: dict) -> dict | None:
    """The tweet subtree of a single-post response, or None if the post is gone.

    The `TweetResultByRestId` counterpart of `_tweet_result`. X answers a
    deleted or suspended post with a normal 200 whose `data.tweetResult` is
    empty, and a withheld one with a non-Tweet `__typename`; both mean the post
    is no longer readable, which is a fact about X rather than a parse failure.
    """
    result = ((payload.get("data") or {}).get("tweetResult") or {}).get("result")
    if not isinstance(result, dict):
        return None
    typename = result.get("__typename")
    if typename == _VISIBILITY_TYPENAME:
        result = result.get("tweet") or result
    elif typename is not None and typename not in _TWEET_TYPENAMES:
        return None
    return result


def item_from_tweet_result(
    result: dict, *, synced_at: str, adapter: str = "x-bookmarks"
) -> ScrollItem:
    """Build one fetched `x` item from a tweet subtree.

    The shared extraction behind both X on-ramps. The bookmarks walk and the
    single-post re-capture read the *same* subtree shape out of the *same*
    GraphQL API, so routing both through here is what makes a re-capture
    hash-comparable to the original capture by construction rather than by
    coincidence — the property `scrolls verify` rests on.

    Args:
        result: The tweet subtree, already unwrapped of any visibility envelope.
        synced_at: UTC ISO-8601 timestamp for this capture.
        adapter: Which on-ramp is calling, recorded in provenance.

    Returns:
        A fetched `x` item.

    Raises:
        ValueError: The subtree carries no usable tweet id.
    """
    return _to_item(result, {}, synced_at, adapter=adapter)


def _to_item(
    result: dict, entry: dict, synced_at: str, *, adapter: str = "x-bookmarks"
) -> ScrollItem:
    """Build one fetched `x` item from a tweet subtree.

    Raises:
        ValueError: The subtree carries no usable tweet id.
    """
    legacy = result.get("legacy") or {}
    tweet_id = str(result.get("rest_id") or legacy.get("id_str") or "")
    if not tweet_id:
        raise ValueError("entry has no tweet id")

    handle, name = _author(result)
    url = (
        f"https://x.com/{handle}/status/{tweet_id}"
        if handle
        else f"https://x.com/i/status/{tweet_id}"
    )

    extracted = _body_text(result, legacy)
    quoted_handle, quoted_text = _quoted(result)
    if quoted_text:
        extracted += f"\n\nQuoting @{quoted_handle or 'unknown'}: {quoted_text}"

    sort_index = entry.get("sortIndex")
    provenance: dict[str, Any] = {
        "adapter": adapter,
        "fetched_at": synced_at,
        "extraction_method": "x:graphql-internal",
        # X exposes no bookmark timestamp; say so rather than imply one.
        "saved_at_source": "synced_at",
    }
    if isinstance(sort_index, str) and sort_index:
        provenance["sort_index"] = sort_index

    return ScrollItem(
        id=make_item_id("x", tweet_id, url),
        source="x",
        source_id=tweet_id,
        url=url,
        saved_at=synced_at,
        title=_make_title(handle, _collapse(extracted), tweet_id),
        author=f"{name} (@{handle})" if name and handle else (name or handle or None),
        published_at=_parse_posted_at(legacy.get("created_at")),
        raw_text=json.dumps(result, ensure_ascii=False, sort_keys=True),
        extracted_text=extracted or None,
        links=_links(legacy),
        media=_media(legacy),
        content_hash="sha256:" + hashlib.sha256(extracted.encode("utf-8")).hexdigest(),
        provenance=provenance,
        stage="fetched",
    )


def _author(result: dict) -> tuple[str, str]:
    """Handle and display name, reading the newer `core` shape then `legacy`."""
    user = ((result.get("core") or {}).get("user_results") or {}).get("result") or {}
    for holder in (user.get("core") or {}, user.get("legacy") or {}):
        handle = holder.get("screen_name") or ""
        name = holder.get("name") or ""
        if handle or name:
            return handle, name
    return "", ""


def _body_text(result: dict, legacy: dict) -> str:
    """Long-form note text when present, else the legacy (truncated) text."""
    note = (
        (result.get("note_tweet") or {})
        .get("note_tweet_results", {})
        .get("result", {})
        .get("text")
    )
    return note or legacy.get("full_text") or ""


def _quoted(result: dict) -> tuple[str, str]:
    """Handle and text of the quoted post, or empty strings when absent."""
    quoted = (result.get("quoted_status_result") or {}).get("result")
    if not isinstance(quoted, dict):
        return "", ""
    if quoted.get("__typename") == _VISIBILITY_TYPENAME:
        quoted = quoted.get("tweet") or quoted
    quoted_legacy = quoted.get("legacy") or {}
    handle, _ = _author(quoted)
    return handle, _body_text(quoted, quoted_legacy)


def _links(legacy: dict) -> tuple:
    urls = (legacy.get("entities") or {}).get("urls") or ()
    return tuple(
        url["expanded_url"] for url in urls if isinstance(url, dict) and url.get("expanded_url")
    )


def _media(legacy: dict) -> tuple:
    entries = (legacy.get("extended_entities") or {}).get("media") or (
        legacy.get("entities") or {}
    ).get("media") or ()
    return tuple(
        {"type": media.get("type") or "media", "url": media["media_url_https"]}
        for media in entries
        if isinstance(media, dict) and media.get("media_url_https")
    )


def _make_title(handle: str, collapsed_text: str, tweet_id: str) -> str:
    prefix = f"@{handle}: " if handle else ""
    title = f"{prefix}{collapsed_text}" if collapsed_text else f"{prefix}status {tweet_id}"
    if len(title) > _MAX_TITLE_LENGTH:
        title = title[: _MAX_TITLE_LENGTH - 1].rstrip() + "…"
    return title


def _parse_posted_at(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, _POSTED_AT_FORMAT)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _collapse(text: str) -> str:
    return " ".join(text.split())
