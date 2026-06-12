"""Field Theory bookmark import (IDEAS.md §7, ADR 0009).

`scrolls import fieldtheory` reads X/Twitter bookmarks from a local Field
Theory archive instead of reimplementing X auth/sync. The JSONL cache
(`bookmarks/bookmarks.jsonl`) is the spine — Field Theory's own durable
raw-record store — and each line is kept verbatim in `raw_text` so scrolls
and indexes can be rebuilt without Field Theory installed. Classified
pages under `library/bookmarks/` are an optional join: their frontmatter
`category`/`domain` carry over prior classification work, matched by
`tweet_id`. Imported items enter at stage 'fetched' (content is already
local; there is no x fetch adapter), so `scrolls md`, `classify`, and
`kb` work on them unchanged. Item ids are `x:<tweetId>`, matching what
`detect.py` produces for x.com status URLs, so `add` and a later import
dedupe against each other.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from scrolls.items import ScrollItem, make_item_id

DEFAULT_ROOT = Path.home() / ".fieldtheory"

_BOOKMARKS_RELPATH = Path("bookmarks") / "bookmarks.jsonl"
_LIBRARY_RELPATH = Path("library") / "bookmarks"
_POSTED_AT_FORMAT = "%a %b %d %H:%M:%S %z %Y"  # "Mon Jun 01 15:34:00 +0000 2026"
_MAX_TITLE_LENGTH = 80


class ImportSourceError(Exception):
    """The Field Theory archive is missing or unreadable."""


def load_bookmarks(ft_root: Path) -> tuple[list[ScrollItem], list[dict]]:
    """Parse a Field Theory archive into fetched x items.

    Returns (items, failures) where failures are per-line problems that
    did not abort the batch, mirroring `scrolls fetch` semantics. Raises
    ImportSourceError only when the JSONL cache itself is missing.
    """
    jsonl_path = ft_root / _BOOKMARKS_RELPATH
    if not jsonl_path.is_file():
        raise ImportSourceError(f"no Field Theory bookmarks at {jsonl_path}")

    classifications = _load_classifications(ft_root / _LIBRARY_RELPATH)
    imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    items: list[ScrollItem] = []
    failures: list[dict] = []
    with jsonl_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                items.append(_to_item(record, line, classifications, imported_at))
            except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
                failures.append({"line": line_number, "error": str(exc)})
    return items, failures


def _to_item(
    record: dict, raw_line: str, classifications: dict[str, dict], imported_at: str
) -> ScrollItem:
    tweet_id = str(record.get("tweetId") or record["id"])
    url = record.get("url") or f"https://x.com/i/status/{tweet_id}"
    text = _collapse(record.get("text") or "")
    handle = record.get("authorHandle") or ""
    name = record.get("authorName") or ""

    extracted = record.get("text") or ""
    quoted = record.get("quotedTweet") or {}
    if quoted.get("text"):
        quoted_handle = quoted.get("authorHandle") or "unknown"
        extracted += f"\n\nQuoting @{quoted_handle}: {quoted['text']}"

    classified = classifications.get(tweet_id, {})
    return ScrollItem(
        id=make_item_id("x", tweet_id, url),
        source="x",
        source_id=tweet_id,
        url=url,
        saved_at=_iso(record.get("bookmarkedAt") or record.get("syncedAt")) or imported_at,
        title=_make_title(handle, text, tweet_id),
        author=f"{name} (@{handle})" if name and handle else (name or handle or None),
        published_at=_parse_posted_at(record.get("postedAt")),
        raw_text=raw_line,
        extracted_text=extracted or None,
        category=classified.get("category"),
        domain=classified.get("domain"),
        tags=tuple(record.get("tags") or ()),
        links=tuple(record.get("links") or ()),
        media=_media_refs(record),
        content_hash="sha256:" + hashlib.sha256(extracted.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "fieldtheory-import",
            "fetched_at": imported_at,
            "extraction_method": "fieldtheory:bookmarks.jsonl",
        },
        stage="fetched",
    )


def _make_title(handle: str, collapsed_text: str, tweet_id: str) -> str:
    prefix = f"@{handle}: " if handle else ""
    title = f"{prefix}{collapsed_text}" if collapsed_text else f"{prefix}status {tweet_id}"
    if len(title) > _MAX_TITLE_LENGTH:
        title = title[: _MAX_TITLE_LENGTH - 1].rstrip() + "…"
    return title


def _media_refs(record: dict) -> tuple:
    objects = record.get("mediaObjects") or ()
    if objects:
        return tuple(
            {"type": obj.get("type") or "media", "url": obj["url"]}
            for obj in objects
            if obj.get("url")
        )
    return tuple({"type": "media", "url": url} for url in record.get("media") or ())


def _parse_posted_at(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, _POSTED_AT_FORMAT)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _iso(value: str | None) -> str | None:
    """Normalize Field Theory's Z-suffixed timestamps to the library's ISO form."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _load_classifications(pages_dir: Path) -> dict[str, dict]:
    """Map tweet_id -> {category, domain} from Field Theory's classified pages.

    The frontmatter is simple `key: value` lines; a minimal parse keeps the
    join dependency-free, and any unreadable page just means no carried-over
    classification for that bookmark.
    """
    if not pages_dir.is_dir():
        return {}
    classifications: dict[str, dict] = {}
    for page in sorted(pages_dir.glob("*.md")):
        try:
            fields = _parse_frontmatter(page.read_text(encoding="utf-8"))
        except OSError:
            continue
        tweet_id = fields.get("tweet_id")
        if not tweet_id:
            continue
        entry = {
            key: fields[key] for key in ("category", "domain") if fields.get(key)
        }
        if entry:
            classifications[tweet_id] = entry
    return classifications


def _parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, separator, value = line.partition(":")
        if not separator:
            continue
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def _collapse(text: str) -> str:
    return " ".join(text.split())
