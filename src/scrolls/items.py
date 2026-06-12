"""Normalized item model and persistence (IDEAS.md §12, §14 Pass 2).

`ScrollItem` mirrors the IDEAS.md §12 record one-to-one with the `items`
table; columns share field names so rows map by name. Items enter at stage
'detected' — registered from a URL but not yet fetched — the step before
'synced' in the pipeline states of IDEAS.md §4. List-valued fields and
provenance round-trip through JSON text columns.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

_JSON_LIST_FIELDS = ("tags", "concepts", "links", "media")
_JSON_OBJECT_FIELDS = ("provenance",)


@dataclass(frozen=True)
class ScrollItem:
    id: str
    source: str
    url: str
    saved_at: str
    source_id: str | None = None
    canonical_url: str | None = None
    title: str | None = None
    author: str | None = None
    published_at: str | None = None
    raw_text: str | None = None
    extracted_text: str | None = None
    summary: str | None = None
    category: str | None = None
    domain: str | None = None
    tags: tuple = ()
    concepts: tuple = ()
    links: tuple = ()
    media: tuple = ()
    content_hash: str | None = None
    markdown_path: str | None = None
    provenance: dict[str, Any] | None = None
    stage: str = "detected"


_FIELD_NAMES = tuple(f.name for f in fields(ScrollItem))


def make_item_id(source: str, source_id: str | None, url: str) -> str:
    """Stable item id: `source:source_id`, else `source:` + URL hash (IDEAS.md §12)."""
    if source_id:
        return f"{source}:{source_id}"
    digest = hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:12]
    return f"{source}:{digest}"


def insert_item(db_path: Path, item: ScrollItem) -> bool:
    """Insert an item; return False (keeping the existing row) if the id is taken."""
    row = _to_row(item)
    columns = ", ".join(_FIELD_NAMES)
    placeholders = ", ".join("?" for _ in _FIELD_NAMES)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            cursor = conn.execute(
                f"INSERT OR IGNORE INTO items ({columns}) VALUES ({placeholders})",
                tuple(row[name] for name in _FIELD_NAMES),
            )
        return cursor.rowcount == 1
    finally:
        conn.close()


def get_item(db_path: Path, item_id: str) -> ScrollItem | None:
    """Fetch one item by id, or None if absent."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    finally:
        conn.close()
    return _from_row(row) if row else None


def list_items(db_path: Path) -> list[ScrollItem]:
    """All items, oldest saved first."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM items ORDER BY saved_at, id").fetchall()
    finally:
        conn.close()
    return [_from_row(row) for row in rows]


def _to_row(item: ScrollItem) -> dict[str, Any]:
    row = asdict(item)
    for name in _JSON_LIST_FIELDS:
        row[name] = json.dumps(row[name])
    for name in _JSON_OBJECT_FIELDS:
        if row[name] is not None:
            row[name] = json.dumps(row[name])
    return row


def _from_row(row: sqlite3.Row) -> ScrollItem:
    data = {name: row[name] for name in _FIELD_NAMES}
    for name in _JSON_LIST_FIELDS:
        data[name] = tuple(json.loads(data[name]))
    for name in _JSON_OBJECT_FIELDS:
        if data[name] is not None:
            data[name] = json.loads(data[name])
    return ScrollItem(**data)
