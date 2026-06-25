"""Facet-vocabulary enumeration — the discovery complement to faceted search.

`scrolls search`/`list`/`context` narrow results by `--source`, `--category`,
`--tag`, and `--concept` (ADR 0058/0059), but to *use* a facet an agent must
first know which values the library actually holds. `compute_facets` enumerates
that vocabulary with per-value item counts, so `scrolls facets concepts --source
arxiv` answers "which concepts do my arXiv papers carry?" — the browse half of
the search/browse pair.

Sources and categories are scalar columns counted with `GROUP BY`; the
unclassified pool surfaces as the empty-string category value, directly
round-trippable to `--category ""`. Tags and concepts are JSON-array membership
facets grouped exactly as the KB and the `--tag`/`--concept` filters group them
— tags case-folded, concepts by slug, the smallest spelling the display form
(`kb.group_tags`/`group_concepts`) — so the enumerated vocabulary matches what
the filters key on. Each tag/concept count is the number of *distinct* items
carrying it, so two spellings of one concept on one item count it once.

The `fidelity`, `drift`, `method`, and `content-duplicate` dimensions are
*derived* rather than stored columns. `fidelity` counts items by custody tier
(ADR 0097); `drift` counts them by custody **drift posture** read from the verify
ledger (`verified`/`unverified`/`drifted`/`rotted`/`error`, roadmap H48 — the
browse aggregate of `custody.drift_posture` over `latest_events`, so it converges
with `doctor`'s `custody.drift` and the scope custody headlines for the same
scope); `method` counts them by how each held category was produced (`rules-v1`/
`llm-v1`, or the honest `user-set`/`unclassified` buckets) — the aggregate
counterpart of the per-item `classification` view (roadmap H20/H26), built from
the same `classification_view` derivation so the two never disagree.
`content-duplicate` partitions held items into `duplicate`/`unique` by whether
each carries a byte-identical sibling (roadmap H342 — the browse aggregate of the
content-identity shape H325, folding the same `content_duplicate_index` that
`list/search --content-duplicate` selects on and `doctor`'s
`custody.content_duplicates` counts, so the `duplicate` count converges with both
over the same scope).

The same optional facets that scope search scope the enumeration too, reusing
`items.item_filters`. `None` never filters.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from scrolls.custody import drift_posture, latest_events
from scrolls.items import (
    ScrollItem,
    classification_view,
    content_duplicate_index,
    fidelity_tier,
    item_filters,
    register_facet_functions,
)
from scrolls.kb import group_concepts, group_tags

FIELDS = (
    "sources",
    "categories",
    "tags",
    "concepts",
    "fidelity",
    "drift",
    "method",
    "content-duplicate",
)

DEFAULT_LIMIT = 20


def compute_facets(
    db_path: Path,
    *,
    field: str | None = None,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
    limit: int | None = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Enumerate the filterable vocabulary with item counts.

    Returns ``{"facets": {dimension: [{"value", "count", ...}, ...]}}``. With
    no `field`, every dimension in `FIELDS` is reported, in that order; a
    `field` narrows the payload to that one dimension. Each dimension's list is
    ranked by count descending, then value ascending, and capped at `limit`
    (``None`` for no cap). The optional facets scope the counts the same way
    they scope `scrolls search`. An uninitialized library yields empty lists.
    """
    wanted = _wanted_fields(field)
    if not db_path.exists():
        return {"facets": {name: [] for name in wanted}}

    clauses, params = item_filters(source, category, stage, tag, concept)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    conn = sqlite3.connect(db_path)
    register_facet_functions(conn)
    conn.row_factory = sqlite3.Row
    try:
        facets: dict[str, list[dict[str, Any]]] = {}
        if "sources" in wanted:
            facets["sources"] = _scalar_counts(conn, "source", where, params, limit)
        if "categories" in wanted:
            facets["categories"] = _category_counts(conn, where, params, limit)
        if "tags" in wanted or "concepts" in wanted:
            items = _load_facet_columns(conn, where, params)
            if "tags" in wanted:
                facets["tags"] = _grouped_counts(group_tags(items), limit, slug=False)
            if "concepts" in wanted:
                facets["concepts"] = _grouped_counts(
                    group_concepts(items), limit, slug=True
                )
        if "fidelity" in wanted:
            facets["fidelity"] = _fidelity_counts(conn, where, params, limit)
        if "drift" in wanted:
            facets["drift"] = _drift_counts(conn, where, params, limit, db_path=db_path)
        if "method" in wanted:
            facets["method"] = _method_counts(conn, where, params, limit)
        if "content-duplicate" in wanted:
            facets["content-duplicate"] = _content_duplicate_counts(
                conn, where, params, limit
            )
    finally:
        conn.close()
    return {"facets": {name: facets[name] for name in wanted}}


def _wanted_fields(field: str | None) -> tuple[str, ...]:
    if field is None:
        return FIELDS
    if field not in FIELDS:
        raise ValueError(
            f"unknown facet field {field!r}; choose one of {', '.join(FIELDS)}"
        )
    return (field,)


def _scalar_counts(
    conn: sqlite3.Connection,
    column: str,
    where: str,
    params: list[str],
    limit: int | None,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {column} AS value, COUNT(*) AS count FROM items{where} "
        f"GROUP BY {column}",
        params,
    ).fetchall()
    return _rank([{"value": row["value"], "count": row["count"]} for row in rows], limit)


def _category_counts(
    conn: sqlite3.Connection, where: str, params: list[str], limit: int | None
) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT category AS value, COUNT(*) AS count FROM items{where} "
        f"GROUP BY category",
        params,
    ).fetchall()
    # The unclassified pool (category IS NULL) reports as "", which round-trips
    # to `--category ""` the way search/list select it.
    return _rank(
        [
            {"value": row["value"] if row["value"] is not None else "", "count": row["count"]}
            for row in rows
        ],
        limit,
    )


def _load_facet_columns(
    conn: sqlite3.Connection, where: str, params: list[str]
) -> list[ScrollItem]:
    """Filtered items carrying only the columns the array facets need.

    `group_tags`/`group_concepts` read just `id`, `tags`, and `concepts`, so we
    skip the heavy text columns `list_items` would load and hand them
    lightweight items keyed by id (id distinguishes distinct-item counts).
    """
    rows = conn.execute(f"SELECT id, tags, concepts FROM items{where}", params).fetchall()
    return [
        ScrollItem(
            id=row["id"],
            source="",
            url="",
            saved_at="",
            tags=tuple(json.loads(row["tags"])),
            concepts=tuple(json.loads(row["concepts"])),
        )
        for row in rows
    ]


def _grouped_counts(
    by_group: dict[str, dict], limit: int | None, *, slug: bool
) -> list[dict[str, Any]]:
    entries = []
    for key, entry in by_group.items():
        count = len({item.id for item in entry["items"]})
        record: dict[str, Any] = {"value": entry["display"], "count": count}
        if slug:
            record["slug"] = key
        entries.append(record)
    return _rank(entries, limit)


def _rank(entries: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    entries.sort(key=lambda record: (-record["count"], record["value"]))
    return entries[:limit] if limit is not None else entries

def _fidelity_counts(
    conn: sqlite3.Connection, where: str, params: list[str], limit: int | None
) -> list[dict[str, Any]]:
    """Count items by derived custody-fidelity tier (ADR 0097).

    The tier is derived from content *presence* and stage, not the body text
    itself, so this selects four `has_*` booleans and `stage` — never the
    bodies — and folds each row through `fidelity_tier`, the same primitive
    `scrolls search` derives its per-hit tier from. (Loading the array columns
    instead is the bug that once made every item read as `reference`; presence
    flags can't repeat it.)
    """
    rows = conn.execute(
        "SELECT "
        "(raw_text IS NOT NULL AND raw_text != '') AS has_raw, "
        "(extracted_text IS NOT NULL AND extracted_text != '') AS has_extracted, "
        "(summary IS NOT NULL AND summary != '') AS has_summary, "
        "(content_hash IS NOT NULL AND content_hash != '') AS has_hash, "
        f"stage FROM items{where}",
        params,
    ).fetchall()
    counts = Counter(
        fidelity_tier(
            has_raw=bool(row["has_raw"]),
            has_extracted=bool(row["has_extracted"]),
            has_summary=bool(row["has_summary"]),
            has_hash=bool(row["has_hash"]),
            stage=row["stage"],
        )
        for row in rows
    )
    entries = [{"value": tier, "count": count} for tier, count in counts.items()]
    return _rank(entries, limit)


def _drift_counts(
    conn: sqlite3.Connection,
    where: str,
    params: list[str],
    limit: int | None,
    *,
    db_path: Path,
) -> list[dict[str, Any]]:
    """Count held items by custody drift posture (roadmap H48).

    The browse aggregate of the verify ledger — the one custody axis that had no
    `facets` dimension (fidelity and method already do). Each scoped held item is
    bucketed by `custody.drift_posture` over its latest ledger verdict:
    `verified` (re-checked unchanged), `unverified` (never re-checked — counted,
    never silently dropped), or `drifted`/`rotted`/`error`. Because it reads the
    same `latest_events` ledger and the same `drift_posture` primitive `doctor`'s
    `custody.drift` block and the scope custody headlines (roadmap H45/H47) read,
    `facets drift` converges with them for the same scope by construction
    (`verified` ≡ doctor's `unchanged`; `unverified` = held − verdicts). Reads
    only item ids here and the ledger, never the bodies, like `_fidelity_counts`.
    """
    rows = conn.execute(f"SELECT id FROM items{where}", params).fetchall()
    verdicts = latest_events(db_path)
    counts = Counter(drift_posture(verdicts.get(row["id"])) for row in rows)
    entries = [{"value": posture, "count": count} for posture, count in counts.items()]
    return _rank(entries, limit)


def _method_counts(
    conn: sqlite3.Connection, where: str, params: list[str], limit: int | None
) -> list[dict[str, Any]]:
    """Count items by how each held category was produced (roadmap H28).

    The aggregate counterpart of the per-item `classification` view (H20/H26):
    where that view says how *one* item's category was derived, this buckets the
    whole (scoped) library by the engine that produced each category — the same
    derivation (`classification_view` over the row's own `provenance`), so the
    counts and the per-item view never disagree. Two buckets the per-item view's
    None covers are named honestly here rather than dropped: `user-set` (a
    category present with no engine stamp — a `scrolls set` value) and
    `unclassified` (no category at all). Reads only `category` + `provenance`,
    never the bodies, the way `_fidelity_counts` reads only presence flags.
    """
    rows = conn.execute(
        f"SELECT category, provenance FROM items{where}", params
    ).fetchall()
    counts = Counter(_method_bucket(row["category"], row["provenance"]) for row in rows)
    entries = [{"value": method, "count": count} for method, count in counts.items()]
    return _rank(entries, limit)


def _method_bucket(category: str | None, provenance_json: str | None) -> str:
    """The classification-method bucket for one row.

    The engine that stamped the category (`rules-v1` / `llm-v1`) when one did;
    otherwise `user-set` for a hand-set category and `unclassified` for none —
    the honest absence the per-item view returns as None, made countable.
    """
    provenance = json.loads(provenance_json) if provenance_json else None
    view = classification_view(provenance)
    if view is not None:
        return view["by"]
    return "user-set" if category is not None else "unclassified"


def _content_duplicate_counts(
    conn: sqlite3.Connection, where: str, params: list[str], limit: int | None
) -> list[dict[str, Any]]:
    """Partition held items by content-identity redundancy (roadmap H342).

    The browse aggregate of the content-identity custody shape (H325): each scoped
    held item is bucketed by whether it carries **≥1 byte-identical sibling** — the
    same bytes held under another id. `duplicate` is a member of a flagged
    `content_duplicate_groups` group; `unique` carries no byte-identical sibling
    (a genuinely lone capture *or* a NULL/empty-`content_hash` reference item, which
    holds no bytes to match — the H325 NULL-safe rule). The two buckets **partition
    the scope** (their counts sum to the held total), the `fidelity`/`drift`/`method`
    shape, and a clean library reports only `unique` (`Counter` emits no empty
    `duplicate` bucket — the omit-when-clean shape).

    The discovery counterpart `list/search --content-duplicate` (H338) drills from:
    the `duplicate` count folds the **same** `content_duplicate_index` primitive the
    filter selects on and `doctor`'s `custody.content_duplicates` counts, so over the
    whole library `duplicate` ≡ `doctor`'s `total_items` (the *M* in the `_Duplicates:_`
    headline) and, over any scope, ≡ the rows the drill returns (drill-from-the-count
    convergence, the `drift` ↔ `facets drift` twin on the content-identity axis).

    The sibling index is folded over the **whole library** — a content group spans
    sources (the H328 cross-source rule), so the fold never sees the scoped `where` —
    and only the *scoped* ids are then partitioned by membership. So
    `facets content-duplicate --source S` reports how many of S's items have a
    byte-identical sibling held *anywhere* (the sibling may live in another source),
    exactly the set `--source S --content-duplicate` would return. Reads only ids and
    hashes here, never the bodies, like `_fidelity_counts`/`_drift_counts`.
    """
    sibling_index = content_duplicate_index(_load_content_hashes(conn))
    rows = conn.execute(f"SELECT id FROM items{where}", params).fetchall()
    counts = Counter(
        "duplicate" if row["id"] in sibling_index else "unique" for row in rows
    )
    entries = [{"value": value, "count": count} for value, count in counts.items()]
    return _rank(entries, limit)


def _load_content_hashes(conn: sqlite3.Connection) -> list[ScrollItem]:
    """Whole-library lightweight items carrying only `id` + `content_hash`.

    `content_duplicate_index` reads only those two fields, and the sibling fold
    must see the **whole library** (a content group spans sources, the H328
    cross-source rule) — never the scoped `where` — so this reads every row's id and
    hash with no filter and skips the heavy body columns `list_items` would load
    (the `_load_facet_columns` lightweight-load precedent).
    """
    rows = conn.execute("SELECT id, content_hash FROM items").fetchall()
    return [
        ScrollItem(
            id=row["id"],
            source="",
            url="",
            saved_at="",
            content_hash=row["content_hash"],
        )
        for row in rows
    ]
