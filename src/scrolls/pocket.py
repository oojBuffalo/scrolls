"""Pocket CSV-export import (IDEAS.md §13, ADR 0074).

`scrolls import pocket <path>` turns a Pocket data export — the CSV
Mozilla mailed users when Pocket shut down in 2025 — into detected
items. Like the browser-bookmarks import (ADR 0030) this is a
heterogeneous spine-only archive: every saved URL routes through the
same source detection and URL normalization as `scrolls add`, so a
saved video becomes a `youtube` item and a repo a `github` item, all
deduping against the rest of the library, and items enter at stage
'detected' for `scrolls fetch` to enrich.

The export is a CSV with header `title,url,time_added,tags,status`:

- `time_added` is epoch seconds → `saved_at` (when the page entered the
  user's life, mirroring the bookmarks `ADD_DATE` and Field Theory's
  `bookmarkedAt`), never `published_at` — Pocket doesn't know it.
- `tags` are pipe-delimited and become `tags` — the user's own curation,
  free-form like `scrolls set` and the bookmarks-folder analog (ADR 0030).
- a missing title is stored by Pocket as the URL repeated, so a title
  equal to the URL is dropped (`scrolls fetch` fills the real one).

Large accounts export as a `.zip` of `part_*.csv` files; a single `.csv`
or a directory of parts also work (the Takeout zip/dir/file shape,
ADR 0029). Columns are read by header name (case-insensitive) via
`csv.DictReader`, so reordered or extra columns survive; only a `url`
column is required.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from scrolls.dates import epoch_to_utc_iso
from scrolls.items import ScrollItem, make_item_id
from scrolls.sources.detect import detect_source
from scrolls.sources.urls import normalize_url

_URL_COLUMN = "url"
_CSV_SUFFIX = ".csv"


class ImportSourceError(Exception):
    """The Pocket export is missing, unreadable, or not a CSV with a URL column."""


def load_pocket_export(path: Path) -> tuple[list[ScrollItem], dict]:
    """Parse a Pocket CSV export into detected items.

    Returns (items, stats). Per-row oddities — blank URLs, non-http(s)
    saves — are counted in stats['ignored'], never fatal; the same URL
    saved twice (e.g. across export parts) collapses to one item
    (earliest `time_added` wins `saved_at`, tags unioned), the
    bookmarks-import rule (ADR 0030). Raises ImportSourceError only for
    document-level problems: a missing path, a `.zip`/directory holding no
    CSV at all (or none of them Pocket-shaped), or a single `.csv` without
    a `url` column. A stray non-Pocket CSV beside the parts is skipped, not
    fatal (`_read_rows`).
    """
    rows = _read_rows(path)
    imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ignored = {"no_url": 0, "not_http": 0}
    status_counts = {"unread": 0, "archive": 0}
    repeats = 0
    # item id -> (saved_at or None, item); earliest-save-wins collapse with a
    # union of tags across occurrences — the same rule the bookmarks import uses
    earliest: dict[str, tuple[str | None, ScrollItem]] = {}
    tags_by_id: dict[str, list[str]] = {}
    order: list[str] = []
    for row in rows:
        raw_url = (row.get(_URL_COLUMN) or "").strip()
        if not raw_url:
            ignored["no_url"] += 1
            continue
        url = normalize_url(raw_url)
        try:
            detected = detect_source(url)
        except ValueError:
            ignored["not_http"] += 1  # bookmarklets, mailto:, file:, ...
            continue
        # status is tallied per detected save row (skipped rows excluded), so
        # the unread/archive split reflects the saves entering the library
        status = (row.get("status") or "").strip().lower()
        if status in status_counts:
            status_counts[status] += 1
        saved_at = epoch_to_utc_iso(row.get("time_added"))
        item = ScrollItem(
            id=make_item_id(detected.source, detected.source_id, url),
            source=detected.source,
            source_id=detected.source_id,
            url=url,
            # the export's title seeds the item; fetch replaces it with the
            # source's own value (feed-sync semantics, ADR 0021)
            title=_title(row.get("title"), raw_url),
            saved_at=saved_at or imported_at,
        )
        if item.id in earliest:
            repeats += 1
            known_at, _ = earliest[item.id]
            if saved_at and (known_at is None or saved_at < known_at):
                earliest[item.id] = (saved_at, item)
        else:
            earliest[item.id] = (saved_at, item)
            order.append(item.id)
        merged = tags_by_id.setdefault(item.id, [])
        merged.extend(tag for tag in _tags(row.get("tags")) if tag not in merged)

    items = [
        replace(earliest[item_id][1], tags=tuple(tags_by_id[item_id]))
        for item_id in order
    ]
    stats = {
        "rows": len(rows),
        "repeats": repeats,
        "ignored": ignored,
        "status": status_counts,
    }
    return items, stats


def _read_rows(path: Path) -> list[dict]:
    """Every CSV data row across the export, as header-keyed dicts.

    A plain `.csv` is read directly and must carry a `url` column. A
    `.zip` (Pocket's multi-part export) or a directory contributes all its
    `*.csv` parts: parts that *are* Pocket-shaped (carry a `url` column)
    are merged, and a stray non-Pocket CSV among them is skipped rather
    than aborting the whole import — the document is the export, a part is
    not. Raises ImportSourceError for a missing path, a zip/directory with
    no CSV at all, a bundle whose CSVs are none of them Pocket-shaped, or a
    single `.csv` with no `url` column.
    """
    if zipfile.is_zipfile(path):
        return _merge_parts(_zip_csv_texts(path), path)
    if path.is_dir():
        matches = sorted(path.rglob(f"*{_CSV_SUFFIX}"))
        if not matches:
            raise ImportSourceError(
                f"no .csv export parts under {path}; "
                "pass the Pocket export .zip, a directory of CSV parts, "
                "or a single .csv file"
            )
        return _merge_parts(
            (match.read_text(encoding="utf-8-sig") for match in matches), path
        )
    if path.is_file():
        rows = _parse_csv(path.read_text(encoding="utf-8-sig"))
        if rows is None:
            raise ImportSourceError(
                "CSV export has no 'url' column; "
                "this does not look like a Pocket data export"
            )
        return rows
    raise ImportSourceError(f"no Pocket export at {path}")


def _zip_csv_texts(path: Path):
    """The decoded text of each `*.csv` member of the zip (raises if none)."""
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if name.lower().endswith(_CSV_SUFFIX)
        )
        if not names:
            raise ImportSourceError(
                f"no .csv export parts in {path}; "
                "this does not look like a Pocket data export"
            )
        return [archive.read(name).decode("utf-8-sig") for name in names]


def _merge_parts(texts, path: Path) -> list[dict]:
    """Merge the rows of every Pocket-shaped CSV part, skipping the rest.

    A part with no `url` column isn't a Pocket part and is skipped; only
    when *no* part among the bundle is Pocket-shaped is the whole thing
    rejected as not an export.
    """
    rows: list[dict] = []
    pocket_parts = 0
    for text in texts:
        part = _parse_csv(text)
        if part is None:
            continue  # a non-Pocket CSV alongside the parts — skip, don't abort
        pocket_parts += 1
        rows.extend(part)
    if pocket_parts == 0:
        raise ImportSourceError(
            f"no CSV with a 'url' column in {path}; "
            "this does not look like a Pocket data export"
        )
    return rows


def _parse_csv(text: str) -> list[dict] | None:
    """A CSV's data rows as dicts keyed by lowercased header names.

    Returns None when the header carries no `url` column — not a Pocket
    (or Pocket-shaped) CSV. The caller decides whether that is fatal (a
    single file passed directly) or skippable (one part of a bundle).
    """
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = [(name or "").strip().lower() for name in reader.fieldnames or []]
    if _URL_COLUMN not in fieldnames:
        return None
    return [
        {(key or "").strip().lower(): value for key, value in row.items()}
        for row in reader
    ]


def _title(title: str | None, raw_url: str) -> str | None:
    """The row's title, or None when Pocket left it blank.

    A save with no title is exported with the URL repeated in the title
    field, so a title equal to the URL is treated as absent.
    """
    cleaned = (title or "").strip()
    if not cleaned or cleaned == raw_url.strip():
        return None
    return cleaned


def _tags(tags: str | None) -> list[str]:
    """The pipe-delimited tags field as a clean list (empty when blank)."""
    return [tag for tag in (part.strip() for part in (tags or "").split("|")) if tag]
