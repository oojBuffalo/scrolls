"""Google Takeout YouTube watch-history import (IDEAS.md §13, ADR 0029).

`scrolls import google-takeout <path>` turns a Takeout export's
`watch-history.json` into youtube items — the bulk-archive counterpart
to `import fieldtheory`, but for a spine with no content: Takeout
records only video URL, title, channel, and watch time, so items enter
at stage 'detected' (like feed sync, ADR 0021) and `scrolls fetch`
enriches them through the youtube adapter. The watch time becomes
`saved_at` (when the video entered the user's life, mirroring Field
Theory's `bookmarkedAt`), never `published_at` — Takeout doesn't know
when a video was published. `path` may be the Takeout .zip, an
extracted directory, or `watch-history.json` itself — the direct file
path is the escape hatch for localized exports whose directory names
("YouTube and YouTube Music") are translated. The JSON export format is
required; the default HTML export is not parseable here.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem, make_item_id
from scrolls.sources.detect import detect_source
from scrolls.sources.urls import normalize_url

_HISTORY_FILENAME = "watch-history.json"
_AD_MARKER = "From Google Ads"
_WATCHED_PREFIX = "Watched "


class ImportSourceError(Exception):
    """The Takeout export is missing, unreadable, or not the JSON format."""


def load_watch_history(path: Path) -> tuple[list[ScrollItem], dict]:
    """Parse a Takeout export into detected youtube items.

    Returns (items, stats). Per-entry oddities — ads, deleted videos
    without a URL, community posts — are counted in stats['ignored'],
    never fatal; repeat watches of one video collapse to the earliest
    watch (stats['repeats']), matching the doctor's earliest-save-date
    merge rule. Raises ImportSourceError only for document-level
    problems: missing path, no watch-history.json, non-JSON content.
    """
    entries = _read_entries(path)
    imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ignored = {"ads": 0, "no_url": 0, "not_video": 0}
    repeats = 0
    # item id -> (watched_at, entry); Takeout lists newest watches first,
    # so an earlier watch of a known video replaces the stored entry
    earliest: dict[str, tuple[str | None, ScrollItem]] = {}
    order: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("titleUrl"):
            ignored["no_url"] += 1
            continue
        if _is_ad(entry):
            ignored["ads"] += 1
            continue
        url = normalize_url(entry["titleUrl"])
        try:
            detected = detect_source(url)
        except ValueError:
            ignored["not_video"] += 1
            continue
        if detected.source != "youtube" or not detected.source_id:
            ignored["not_video"] += 1  # community posts, channel visits
            continue
        watched_at = to_utc_iso(entry.get("time"))
        item = ScrollItem(
            id=make_item_id("youtube", detected.source_id, url),
            source="youtube",
            source_id=detected.source_id,
            url=url,
            # the export's title and channel seed the item; fetch replaces
            # them with the source's own values (feed-sync semantics)
            title=_strip_watched(entry.get("title")),
            author=_channel_name(entry),
            saved_at=watched_at or imported_at,
        )
        if item.id in earliest:
            repeats += 1
            known_at, _ = earliest[item.id]
            if watched_at and (known_at is None or watched_at < known_at):
                earliest[item.id] = (watched_at, item)
        else:
            earliest[item.id] = (watched_at, item)
            order.append(item.id)

    items = [earliest[item_id][1] for item_id in order]
    stats = {"events": len(entries), "repeats": repeats, "ignored": ignored}
    return items, stats


def _read_entries(path: Path) -> list:
    if zipfile.is_zipfile(path):
        text = _read_from_zip(path)
    elif path.is_dir():
        text = _read_from_dir(path)
    elif path.is_file():
        text = path.read_text(encoding="utf-8")
    else:
        raise ImportSourceError(f"no Takeout export at {path}")

    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImportSourceError(
            f"{_HISTORY_FILENAME} is not valid JSON ({exc}); "
            "re-export from Takeout with history in JSON format"
        ) from exc
    if not isinstance(document, list):
        raise ImportSourceError(f"{_HISTORY_FILENAME} is not a list of watch events")
    return document


def _read_from_zip(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            name for name in archive.namelist()
            if Path(name).name == _HISTORY_FILENAME
        )
        if not names:
            raise ImportSourceError(
                f"no {_HISTORY_FILENAME} in {path}; "
                "re-export from Takeout with history in JSON format, "
                "or pass the history file's path directly"
            )
        return archive.read(names[0]).decode("utf-8")


def _read_from_dir(path: Path) -> str:
    matches = sorted(path.rglob(_HISTORY_FILENAME))
    if not matches:
        raise ImportSourceError(
            f"no {_HISTORY_FILENAME} under {path}; "
            "re-export from Takeout with history in JSON format, "
            "or pass the history file's path directly"
        )
    return matches[0].read_text(encoding="utf-8")


def _is_ad(entry: dict) -> bool:
    return any(
        detail.get("name") == _AD_MARKER
        for detail in entry.get("details") or ()
        if isinstance(detail, dict)
    )


def _strip_watched(title: str | None) -> str | None:
    # English exports phrase entries as "Watched <title>"; localized
    # exports keep their own phrasing, and fetch replaces the title anyway
    if title and title.startswith(_WATCHED_PREFIX):
        title = title[len(_WATCHED_PREFIX):]
    return title or None


def _channel_name(entry: dict) -> str | None:
    subtitles = entry.get("subtitles") or ()
    first = subtitles[0] if subtitles and isinstance(subtitles[0], dict) else {}
    return first.get("name") or None
