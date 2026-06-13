"""Normalized item model and persistence (IDEAS.md §12, §14 Pass 2).

`ScrollItem` mirrors the IDEAS.md §12 record one-to-one with the `items`
table; columns share field names so rows map by name. Items enter at stage
'detected' — registered from a URL but not yet fetched — and move to
'fetched' once a source adapter fills in content (ADR 0002 revises the
IDEAS.md §4 stage names for the add-one-URL path). List-valued fields and
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


def update_item(db_path: Path, item: ScrollItem) -> bool:
    """Replace the stored row for `item.id`; return False if no such row (no upsert)."""
    row = _to_row(item)
    value_names = tuple(name for name in _FIELD_NAMES if name != "id")
    assignments = ", ".join(f"{name} = ?" for name in value_names)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            cursor = conn.execute(
                f"UPDATE items SET {assignments} WHERE id = ?",
                tuple(row[name] for name in value_names) + (item.id,),
            )
        return cursor.rowcount == 1
    finally:
        conn.close()


def replace_items(db_path: Path, remove_ids: list[str], item: ScrollItem) -> None:
    """Atomically delete `remove_ids` and insert `item` in their place.

    The doctor's duplicate merge (ADR 0026): one transaction, so an
    interruption can never lose the group's rows without storing the
    merged survivor. `item.id` may be one of the removed ids.
    """
    row = _to_row(item)
    columns = ", ".join(_FIELD_NAMES)
    placeholders = ", ".join("?" for _ in _FIELD_NAMES)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.executemany(
                "DELETE FROM items WHERE id = ?", [(item_id,) for item_id in remove_ids]
            )
            conn.execute(
                f"INSERT INTO items ({columns}) VALUES ({placeholders})",
                tuple(row[name] for name in _FIELD_NAMES),
            )
    finally:
        conn.close()


def delete_item(db_path: Path, item_id: str) -> bool:
    """Delete one item row; return False if no such row.

    The FTS delete trigger keeps the search index in sync (ADR 0027).
    """
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            cursor = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
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


def count_by_source(db_path: Path) -> dict[str, int]:
    """Item counts keyed by source, alphabetical."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT source, COUNT(*) FROM items GROUP BY source ORDER BY source"
        ).fetchall()
    finally:
        conn.close()
    return dict(rows)


def library_counts(db_path: Path) -> dict[str, Any]:
    """Item counts for `scrolls status`: total, by stage, by source, unclassified.

    `by_stage` always carries all three stages (zero-filled) so agents
    can read pending work — detected items await `fetch`, fetched ones
    await `md` — without key-existence checks; `by_source` lists only
    sources present. `unclassified` is the pool a batch `classify`
    would pick up (`category IS NULL`, any stage).
    """
    conn = sqlite3.connect(db_path)
    try:
        by_stage = {"detected": 0, "fetched": 0, "rendered": 0}
        by_stage.update(
            conn.execute("SELECT stage, COUNT(*) FROM items GROUP BY stage").fetchall()
        )
        by_source = dict(
            conn.execute(
                "SELECT source, COUNT(*) FROM items GROUP BY source ORDER BY source"
            ).fetchall()
        )
        total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        unclassified = conn.execute(
            "SELECT COUNT(*) FROM items WHERE category IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "total": total,
        "by_stage": by_stage,
        "by_source": by_source,
        "unclassified": unclassified,
    }


def register_facet_functions(conn: sqlite3.Connection) -> None:
    """Register the SQL helpers the tag/concept membership facets need (ADR 0059).

    Concepts merge by slug and tags match case-insensitively, exactly as
    `scrolls related` and the KB concept pages treat them. The built-in SQL
    `lower()` is ASCII-only, so a Unicode-aware `str.lower` is registered
    alongside `slugify`, keeping the indexed column value and the
    Python-normalized parameter in agreement for non-ASCII tags. Both
    `list_items` and the joined `search_items` query call this on their
    connection before running a `tag_concept_filters` clause.
    """
    from scrolls.render import slugify  # lazy: render imports items at module load

    conn.create_function("scrolls_slug", 1, slugify, deterministic=True)
    conn.create_function("scrolls_lower", 1, str.lower, deterministic=True)


def tag_concept_filters(
    tag: str | None, concept: str | None
) -> tuple[list[str], list[str]]:
    """SQL membership clauses and params for the optional tag/concept facets.

    Each facet is a single value AND-ed with the others: an item matches
    when the value is a member of its `tags` (case-insensitive) or
    `concepts` (by slug) JSON-array column. The clauses reference
    `items.tags`/`items.concepts`, so they correlate equally in
    `list_items`' `SELECT * FROM items` and `search_items`' join; the
    connection must have run `register_facet_functions`. `None` never
    filters.
    """
    from scrolls.render import slugify  # lazy: render imports items at module load

    clauses: list[str] = []
    params: list[str] = []
    if tag is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(items.tags) "
            "WHERE scrolls_lower(json_each.value) = ?)"
        )
        params.append(tag.lower())
    if concept is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(items.concepts) "
            "WHERE scrolls_slug(json_each.value) = ?)"
        )
        params.append(slugify(concept))
    return clauses, params


def item_filters(
    source: str | None,
    category: str | None,
    stage: str | None,
    tag: str | None,
    concept: str | None,
) -> tuple[list[str], list[str]]:
    """SQL clauses and their params for the optional facets, in column order.

    The clauses are `items.`-qualified so they correlate equally in a bare
    `SELECT ... FROM items` query and in `search_items`' FTS join — shared by
    `search` (the ranked match) and `facets` (the vocabulary enumeration).
    `category == ""` selects the unclassified pool (`category IS NULL`), the
    `scrolls set` empty-clears convention; `tag`/`concept` are the membership
    facets (`tag_concept_filters`), so the connection must have run
    `register_facet_functions`. `None` never filters.
    """
    clauses: list[str] = []
    params: list[str] = []
    if source is not None:
        clauses.append("items.source = ?")
        params.append(source)
    if category == "":
        clauses.append("items.category IS NULL")
    elif category is not None:
        clauses.append("items.category = ?")
        params.append(category)
    if stage is not None:
        clauses.append("items.stage = ?")
        params.append(stage)
    membership_clauses, membership_params = tag_concept_filters(tag, concept)
    clauses += membership_clauses
    params += membership_params
    return clauses, params


def list_items(
    db_path: Path,
    stage: str | None = None,
    source: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
) -> list[ScrollItem]:
    """All items, oldest saved first; filters combine with AND.

    `stage` and `source` match exactly. `category` matches exactly too,
    except the empty string, which selects items *without* a category —
    the batch-classifiable pool, mirroring `scrolls set`'s empty-clears
    convention. `tag` and `concept` are membership facets over the JSON
    array columns (ADR 0059): `tag` matches case-insensitively, `concept`
    by slug, each the way `scrolls related` compares them. `None` never
    filters. Shares the one clause builder (`item_filters`) with `search`
    and `facets`; its `items.`-qualified clauses run unchanged against this
    single-table `SELECT`.
    """
    clauses, params = item_filters(source, category, stage, tag, concept)
    query = "SELECT * FROM items"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    conn = sqlite3.connect(db_path)
    register_facet_functions(conn)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query + " ORDER BY saved_at, id", tuple(params)).fetchall()
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
