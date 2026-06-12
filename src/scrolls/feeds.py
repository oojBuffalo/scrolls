"""Feed subscriptions and sync (IDEAS.md §13: sync = live platform deltas; ADR 0017).

`scrolls follow` registers an RSS 2.0/Atom feed; `scrolls sync` polls
each followed feed and registers new entry URLs as items at stage
'detected', through the same detection/dedupe path as `scrolls add`.
Sync only discovers URLs — the source adapters still do all fetching
and normalization, so a YouTube feed entry becomes a youtube item and a
blog feed entry a web item. The entry's feed title and published date
(normalized to UTC ISO 8601, ADR 0021) seed the new item; fetch
replaces them only with the source's own values. Both parse with stdlib ElementTree, the
arxiv adapter's precedent; subscriptions live in the `subscriptions`
table because sync state belongs to the index, not config (IDEAS.md §3).

Sync polls with conditional GETs (ADR 0019): each successful full
response's ETag/Last-Modified are stored on the subscription, and a
later 304 reports the feed as 'unchanged' without re-downloading or
re-parsing it. Follow never stores validators — it registers no
entries, so seeding the cache would make the first sync skip them.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem, insert_item, make_item_id
from scrolls.paths import LibraryPaths, get_paths
from scrolls.pipeline import ensure_library
from scrolls.sources import http
from scrolls.sources.detect import YOUTUBE_HOSTS, detect_source
from scrolls.sources.urls import normalize_url

_ATOM = "{http://www.w3.org/2005/Atom}"

GetText = Callable[[str], str]
# (url, stored etag, stored last_modified) -> the conditional GET's outcome
FetchConditional = Callable[[str, str | None, str | None], http.ConditionalText]


class FeedError(Exception):
    """A feed could not be fetched or parsed."""


@dataclass(frozen=True)
class Subscription:
    id: str
    feed_url: str
    title: str | None
    added_at: str
    last_synced_at: str | None = None
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True)
class FeedEntry:
    url: str
    title: str | None = None
    published: str | None = None  # UTC ISO 8601, normalized by dates.to_utc_iso


@dataclass(frozen=True)
class Feed:
    title: str | None
    entries: tuple[FeedEntry, ...]


_SUB_FIELDS = tuple(f.name for f in fields(Subscription))


def make_subscription_id(feed_url: str) -> str:
    """Stable subscription id: 12 hex chars of the feed URL's SHA-256.

    Mirrors the URL-hash half of `make_item_id`, so re-following the
    same feed collides on purpose.
    """
    return hashlib.sha256(feed_url.strip().encode("utf-8")).hexdigest()[:12]


def to_feed_url(url: str) -> str:
    """Normalize a followable URL to the feed URL that will be polled.

    YouTube playlist and channel-id page URLs map to their public Atom
    feeds purely syntactically (no network, no API key); anything else
    must already be a feed URL — `follow_feed` validates it by fetching.
    Raises ValueError for non-http(s) URLs.
    """
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"not an http(s) URL: {url!r}")
    if parsed.hostname.lower() in YOUTUBE_HOSTS:
        path_parts = [p for p in parsed.path.split("/") if p]
        if path_parts[:1] == ["playlist"]:
            values = parse_qs(parsed.query).get("list")
            if values:
                return f"https://www.youtube.com/feeds/videos.xml?playlist_id={values[0]}"
        if len(path_parts) >= 2 and path_parts[0] == "channel":
            return f"https://www.youtube.com/feeds/videos.xml?channel_id={path_parts[1]}"
    return cleaned


def parse_feed(text: str) -> Feed:
    """Parse an RSS 2.0 or Atom document into a title plus entry links.

    Entries without a link are dropped — there is no URL to register.
    Raises FeedError for malformed XML or any other document shape.
    """
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise FeedError(f"not a parseable feed: {exc}") from exc
    if root.tag == f"{_ATOM}feed":
        return Feed(
            title=_clean(root.findtext(f"{_ATOM}title")),
            entries=tuple(
                FeedEntry(
                    url=href.strip(),
                    title=_clean(entry.findtext(f"{_ATOM}title")),
                    # Atom requires <updated>; <published> is optional but
                    # is the actual publication time when present
                    published=to_utc_iso(
                        entry.findtext(f"{_ATOM}published")
                        or entry.findtext(f"{_ATOM}updated")
                    ),
                )
                for entry in root.findall(f"{_ATOM}entry")
                if (href := _atom_link(entry))
            ),
        )
    if root.tag == "rss":
        channel = root.find("channel")
        if channel is None:
            raise FeedError("RSS document has no <channel>")
        return Feed(
            title=_clean(channel.findtext("title")),
            entries=tuple(
                FeedEntry(
                    url=link.strip(),
                    title=_clean(item.findtext("title")),
                    published=to_utc_iso(item.findtext("pubDate")),
                )
                for item in channel.findall("item")
                if (link := item.findtext("link")) and link.strip()
            ),
        )
    raise FeedError(
        f"unrecognized feed format (expected RSS 2.0 or Atom, got <{root.tag}>)"
    )


def follow_feed(url: str, *, get_text: GetText | None = None) -> tuple[LibraryPaths, Subscription, bool]:
    """Validate a feed by fetching it once, then register the subscription.

    Returns (paths, subscription, created); an already-followed feed
    returns the stored row with created=False. Raises ValueError for
    non-http(s) URLs and FeedError when the feed cannot be fetched or
    parsed — nothing is stored (and no library is created) in either
    case, so a typo'd URL cannot fail every future sync.
    """
    feed_url = to_feed_url(url)
    get_text = get_text or _get_text
    try:
        feed = parse_feed(get_text(feed_url))
    except OSError as exc:
        raise FeedError(f"feed request failed: {exc}") from exc
    paths = get_paths()
    ensure_library(paths)
    subscription = Subscription(
        id=make_subscription_id(feed_url),
        feed_url=feed_url,
        title=feed.title,
        added_at=_utcnow(),
    )
    created = insert_subscription(paths.db_path, subscription)
    if not created:
        subscription = get_subscription(paths.db_path, subscription.id) or subscription
    return paths, subscription, created


def sync_subscription(
    db_path: Path, subscription: Subscription, *, fetch: FetchConditional | None = None
) -> dict:
    """Poll one subscription's feed and register its new entries.

    New entry URLs become items at stage 'detected' — exactly what
    `scrolls add` would store — and existing ids count as known, so
    re-syncing is cheap. Entries whose link is not an http(s) URL are
    skipped. The poll is a conditional GET (ADR 0019): a 304 against the
    stored validators reports status 'unchanged' without parsing, and a
    full response's validators are stored for the next poll. Raises
    FeedError when the feed cannot be fetched or parsed;
    `last_synced_at` is only stamped on success.
    """
    fetch = fetch or _get_conditional
    try:
        response = fetch(
            subscription.feed_url, subscription.etag, subscription.last_modified
        )
    except OSError as exc:
        raise FeedError(f"feed request failed: {exc}") from exc

    now = _utcnow()
    if response.not_modified:
        mark_synced(db_path, subscription.id, now)
        return {
            "id": subscription.id,
            "feed_url": subscription.feed_url,
            "status": "unchanged",
            "new": 0,
            "known": 0,
            "skipped": 0,
            "new_items": [],
        }

    feed = parse_feed(response.text or "")
    new_items: list[str] = []
    known = skipped = 0
    for entry in feed.entries:
        # normalize before detect/hash (ADR 0023): feeds decorate entry
        # links with tracking junk that would mint fresh URL-hash ids
        entry_url = normalize_url(entry.url)
        try:
            detected = detect_source(entry_url)
        except ValueError:
            skipped += 1
            continue
        item = ScrollItem(
            id=make_item_id(detected.source, detected.source_id, entry_url),
            source=detected.source,
            source_id=detected.source_id,
            url=entry_url,
            # the entry's feed title and date seed the item; fetch replaces
            # them only with the source's own values, and INSERT OR IGNORE
            # keeps known items untouched
            title=entry.title,
            published_at=entry.published,
            saved_at=now,
        )
        if insert_item(db_path, item):
            new_items.append(item.id)
        else:
            known += 1
    mark_synced(db_path, subscription.id, now)
    store_validators(db_path, subscription.id, response.etag, response.last_modified)
    return {
        "id": subscription.id,
        "feed_url": subscription.feed_url,
        "status": "synced",
        "new": len(new_items),
        "known": known,
        "skipped": skipped,
        "new_items": new_items,
    }


def sync_many(
    db_path: Path,
    subscriptions: list[Subscription],
    *,
    fetch: FetchConditional | None = None,
) -> dict:
    """Sync every given subscription and aggregate the batch payload.

    The shared batch semantics behind both the CLI and the MCP server:
    one dead feed becomes a 'failed' result with its error, never an
    exception, and the totals count items (`new`/`known`/`skipped`) and
    subscriptions (`unchanged`/`failed`).
    """
    results: list[dict] = []
    counts = {"new": 0, "known": 0, "skipped": 0, "unchanged": 0, "failed": 0}
    for subscription in subscriptions:
        try:
            result = sync_subscription(db_path, subscription, fetch=fetch)
        except FeedError as exc:
            counts["failed"] += 1
            results.append(
                {
                    "id": subscription.id,
                    "feed_url": subscription.feed_url,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            continue
        if result["status"] == "unchanged":
            counts["unchanged"] += 1
        for key in ("new", "known", "skipped"):
            counts[key] += result[key]
        results.append(result)
    return {**counts, "results": results}


def insert_subscription(db_path: Path, subscription: Subscription) -> bool:
    """Insert a subscription; return False (keeping the row) if the id is taken."""
    columns = ", ".join(_SUB_FIELDS)
    placeholders = ", ".join("?" for _ in _SUB_FIELDS)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            cursor = conn.execute(
                f"INSERT OR IGNORE INTO subscriptions ({columns}) VALUES ({placeholders})",
                tuple(getattr(subscription, name) for name in _SUB_FIELDS),
            )
        return cursor.rowcount == 1
    finally:
        conn.close()


def get_subscription(db_path: Path, subscription_id: str) -> Subscription | None:
    """Fetch one subscription by id, or None if absent."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)
        ).fetchone()
    finally:
        conn.close()
    return Subscription(**{name: row[name] for name in _SUB_FIELDS}) if row else None


def list_subscriptions(db_path: Path) -> list[Subscription]:
    """All subscriptions, oldest first."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM subscriptions ORDER BY added_at, id"
        ).fetchall()
    finally:
        conn.close()
    return [Subscription(**{name: row[name] for name in _SUB_FIELDS}) for row in rows]


def remove_subscription(db_path: Path, subscription_id: str) -> bool:
    """Delete one subscription; return False if no such id."""
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            cursor = conn.execute(
                "DELETE FROM subscriptions WHERE id = ?", (subscription_id,)
            )
        return cursor.rowcount == 1
    finally:
        conn.close()


def mark_synced(db_path: Path, subscription_id: str, when: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE subscriptions SET last_synced_at = ? WHERE id = ?",
                (when, subscription_id),
            )
    finally:
        conn.close()


def store_validators(
    db_path: Path, subscription_id: str, etag: str | None, last_modified: str | None
) -> None:
    """Record a full response's cache validators, replacing any stored pair.

    Overwriting with None is deliberate: the stored pair always
    describes the most recent full response, so a feed that stops
    sending validators stops getting conditional headers.
    """
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE subscriptions SET etag = ?, last_modified = ? WHERE id = ?",
                (etag, last_modified, subscription_id),
            )
    finally:
        conn.close()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atom_link(entry: ElementTree.Element) -> str | None:
    """The entry's alternate link href, else its first link with an href."""
    links = entry.findall(f"{_ATOM}link")
    for link in links:
        if link.get("rel") in (None, "alternate") and link.get("href"):
            return link.get("href")
    for link in links:
        if link.get("href"):
            return link.get("href")
    return None


def _clean(text: str | None) -> str | None:
    """Whitespace-collapsed text, or None when empty/absent."""
    collapsed = " ".join((text or "").split())
    return collapsed or None


_get_text = http.get_text
_get_conditional = http.get_conditional
