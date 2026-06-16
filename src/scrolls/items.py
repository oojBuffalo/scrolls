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


# The stages at which a held body counts as full custody: the pipeline has
# finished capturing the item, so the body it holds is the one it stands behind.
_CAPTURED_STAGES = ("fetched", "rendered")


def fidelity_tier(
    *,
    has_raw: bool,
    has_extracted: bool,
    has_summary: bool,
    has_hash: bool,
    stage: str,
) -> str:
    """The custody-fidelity tier from content-presence flags alone (ADR 0097).

    The decision `get_fidelity` makes, expressed over booleans instead of a
    whole `ScrollItem`, so a caller that knows only *whether* each content
    column is populated — a search row that selects presence rather than
    hauling a multi-kilobyte body — derives the identical tier. `get_fidelity`
    is the convenience wrapper for callers that already hold the item.

    - ``full``: a re-derivable body is held (`has_raw`, or `has_extracted`
      paired with a `has_hash` fingerprint) and the item reached a captured
      stage (`fetched`/`rendered`).
    - ``partial``: some content survives (`has_raw`, `has_extracted`, or
      `has_summary`) but not enough to qualify as full.
    - ``reference``: only the pointer and provenance are held, no content.
    """
    has_body = has_raw or (has_extracted and has_hash)
    if has_body and stage in _CAPTURED_STAGES:
        return "full"
    if has_raw or has_extracted or has_summary:
        return "partial"
    return "reference"


def get_fidelity(item: ScrollItem) -> str:
    """Derive the explicit custody-fidelity tier for an item (ADR 0097).

    The tier answers "at what fidelity do we still hold this?" purely from
    stored fields — no network, fully deterministic:

    - ``full``: a re-derivable body is held — ``raw_text`` is present, or
      ``extracted_text`` paired with a ``content_hash`` that fingerprints it
      — and the item reached ``fetched``/``rendered``. The body can be
      regenerated and the hash gives a future re-fetch something to diff.
    - ``partial``: some content survives (``raw_text``, ``extracted_text``, or
      ``summary``) but not enough to qualify as full — a degraded-but-honest
      capture.
    - ``reference``: only the pointer and provenance are held, no content.

    Degradation is honest, not a failure: a reference-only item is a complete
    custody record of a thing we deliberately hold by reference. Lives with the
    item model so every surface (doctor, facets, list, search, related) derives
    it identically — delegating to `fidelity_tier` so the rule has one home.
    """
    return fidelity_tier(
        has_raw=bool(item.raw_text),
        has_extracted=bool(item.extracted_text),
        has_summary=bool(item.summary),
        has_hash=bool(item.content_hash),
        stage=item.stage,
    )


def classification_view(provenance: dict[str, Any] | None) -> dict[str, Any] | None:
    """The recorded *how* of a category from a raw `provenance` dict, or None.

    The shared core behind `classification_provenance`: a derived, read-only view
    every surface builds the same way, whether it holds a full `ScrollItem`
    (`show`/`list`) or only the FTS row's `provenance` column (`search`, H26). It
    names the engine that classified the item (`by`), and — for the rules engine —
    which precedence tier fired (`basis`) and the ruleset fingerprint it ran under
    (`ruleset`); for the LLM engine, the `model`. A user override or an
    unclassified item carries no engine stamp, so this is None — honest absence
    (no method is claimed for a category no engine produced).

    Every present view also carries a derived `confidence` marker (roadmap H21,
    the obsidian "confidence levels" adaptation) so an agent reading the category
    knows *how much to trust it* without consulting doctor or knowing the live
    ruleset — see `classification_confidence`.
    """
    provenance = provenance or {}
    engine = provenance.get("classified_by")
    if not engine:
        return None
    view: dict[str, Any] = {"by": engine}
    for source_key, view_key in (
        ("classified_basis", "basis"),
        ("classified_ruleset", "ruleset"),
        ("classified_model", "model"),
    ):
        value = provenance.get(source_key)
        if value is not None:
            view[view_key] = value
    view["confidence"] = classification_confidence(engine, provenance)
    return view


def classification_confidence(
    engine: str, provenance: dict[str, Any] | None
) -> dict[str, Any]:
    """The trust/recency marker for an engine-stamped category (roadmap H21).

    The obsidian "confidence levels" adaptation, custody-shaped: an honest report
    of *how* the category was derived, never a fabricated numeric score. Two
    orthogonal axes an agent weighs when deciding whether to trust a category:

    - ``level`` — the method's nature. ``deterministic`` for the rules engine (a
      category that follows mechanically from recorded signals, reproducible and
      explainable); ``inferred`` for any other engine (only the LLM today — a
      probabilistic model judgment, to be weighed more cautiously). This is the
      "rule-matched vs llm-inferred" axis H21 names.
    - ``freshness`` — present only when it can be answered: the rules engine's
      `classification_freshness` (``current``/``stale``/``unknown``) against the
      *live* ruleset, so a reader sees per-item whether a re-classify would still
      reproduce the category. Omitted for the LLM engine — there is no ruleset to
      compare and a timestamp would break the idempotence contract, so claiming a
      freshness would be fabrication (honest absence).

    Derived purely from the recorded stamps plus the live ruleset digest, so it
    costs no query and stays scope-honest (the H26 property). The freshness leg
    delegates to `classify.classification_freshness` — imported lazily to keep
    the items↔classify module cycle out of import time (the
    `register_facet_functions` pattern) — so the per-item marker, doctor's
    `custody.enrichment` aggregate, and the `classify --stale` pool can never
    disagree.
    """
    from scrolls.classify import ENGINE as RULES_ENGINE  # lazy: avoid import cycle
    from scrolls.classify import classification_freshness

    confidence: dict[str, Any] = {
        "level": "deterministic" if engine == RULES_ENGINE else "inferred"
    }
    freshness = classification_freshness(provenance)
    if freshness is not None:
        confidence["freshness"] = freshness
    return confidence


def classification_provenance(item: ScrollItem) -> dict[str, Any] | None:
    """The recorded *how* of an item's category, or None when no engine stamped it.

    The `ScrollItem` form of `classification_view`, used by the inspect/browse
    surfaces that already hold the item (`show`, `list`, MCP twins).
    """
    return classification_view(item.provenance)


def classification_phrase(view: dict[str, Any]) -> str:
    """`by \\`<engine>\\` (<basis|model>) · confidence <level>[, <freshness>]`.

    The shared readable rendering of a present `classification_view`'s method +
    confidence, behind both the shareable bundle's per-scroll briefing line
    (roadmap H35) and the `scrolls context` per-excerpt provenance tag (H44). The
    surfaces differ only in what they prefix — the bundle says `classified
    \\`<cat>\\` <phrase>`, the excerpt tag `classified <phrase>` (the category is
    already in Best Matches) — so the *method/confidence* part reads byte-identical
    wherever an agent meets it, the cross-surface provenance parity cap 8 asks for.
    Caller passes a non-None view (`classification_view`/`classification_provenance`).
    """
    detail = view.get("basis") or (
        f"model {view['model']}" if view.get("model") else None
    )
    phrase = f"by `{view['by']}`"
    if detail:
        phrase += f" ({detail})"
    confidence = view["confidence"]
    marker = confidence["level"]
    if "freshness" in confidence:
        marker += f", {confidence['freshness']}"
    return f"{phrase} · confidence {marker}"


def item_summary(
    item: ScrollItem,
    works: list[dict[str, Any]] | None = None,
    drift: str = "unverified",
) -> dict[str, Any]:
    """The compact browse record shared by `scrolls list` and MCP `list_scrolls`.

    Enough to scan and pick an item — id, source, url, title, category, stage,
    saved_at — plus the two per-item custody axes: its `fidelity` tier (how much
    of the item the library still holds, ADR 0097) and its `drift` posture
    (whether the source has moved out from under the capture). So an agent
    browsing the library sees at a glance which items it holds in full, which are
    reference-only, and which have drifted — the same two-axis picture `scrolls
    related` hits and the `scrolls graph` node shape carry (roadmap H58). One
    definition keeps the CLI and MCP surfaces identical.

    `works` is the item's scholarly-work membership (ADR 0101): the JSON the
    caller builds with `works.membership_payload`, or `None`/`[]` when the item
    belongs to no multi-representation work. It is passed in rather than derived
    here so this module stays free of the `works` clustering (which itself reads
    items), and so a `list` over the whole library clusters once, not per row.

    `drift` is the item's custody drift posture (`verified`/`unverified`/
    `drifted`/`rotted`/`error`), the `custody.drift_posture` value over the
    item's latest verify-ledger verdict. It is passed in for the same reason as
    `works`: this module stays free of the verify ledger (which `custody` reads
    by importing items), and the caller reads `latest_events` *once* per `list`,
    not per row. The default `"unverified"` is `drift_posture(None)` — the honest
    never-checked posture, so a caller that reads an empty ledger and one that
    omits the argument agree, and neither silently claims "clean".
    """
    summary = {
        "id": item.id,
        "source": item.source,
        "url": item.url,
        "title": item.title,
        "category": item.category,
        "stage": item.stage,
        "saved_at": item.saved_at,
        "fidelity": get_fidelity(item),
        "drift": drift,
        "works": works or [],
    }
    # How the category was derived, when an engine recorded it — so a browse row
    # carries its own provenance (parity with `show`). Omitted entirely when no
    # method was stamped, keeping the row's shape stable for unclassified items.
    classification = classification_provenance(item)
    if classification is not None:
        summary["classification"] = classification
    return summary


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
    drift: str | None = None,
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

    `drift` is the one filter that is *not* a stored column: a custody drift
    posture (`verified`/`unverified`/`drifted`/`rotted`/`error`) derived from the
    verify ledger (roadmap H54). It is applied after the SQL filters, over a
    single `latest_events` read, by the shared `custody.items_in_posture` selector
    — so the rows it returns are exactly the items `facets drift` counts under that
    posture for the same scope (drill-from-the-count convergence). An unknown
    posture is a `ValueError` (a closed vocabulary, like `--stage`), never a
    silent empty; the ledger is read only when `drift` is requested.
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
    items = [_from_row(row) for row in rows]
    if drift is not None:
        # lazy: custody imports items, so the reverse is import-time only here
        from scrolls.custody import DRIFT_POSTURES, items_in_posture, latest_events

        if drift not in DRIFT_POSTURES:
            raise ValueError(
                f"unknown drift posture {drift!r}; "
                f"choose one of {', '.join(DRIFT_POSTURES)}"
            )
        items = items_in_posture(items, latest_events(db_path), drift)
    return items


def item_to_dict(item: ScrollItem) -> dict[str, Any]:
    """The item as a JSON-serializable dict — the lossless export shape (ADR 0082).

    `asdict` already renders the tuple fields as lists and `provenance` as a
    nested dict, so the result round-trips through `json.dumps`/`item_from_dict`
    with every field intact, in dataclass field order (a stable line for diffs).
    """
    return asdict(item)


def item_from_dict(data: dict[str, Any]) -> ScrollItem:
    """Reconstruct an item from `item_to_dict` output, ignoring unknown keys.

    The four JSON list fields come back as tuples (the dataclass shape; the
    JSON form is a list). Keys the model doesn't define are dropped, so an
    export written by a newer schema still loads under an older reader
    (forward compatibility, ADR 0082). The caller must ensure the required
    identity fields are present — `ScrollItem(**known)` raises otherwise.
    """
    known = {name: data[name] for name in _FIELD_NAMES if name in data}
    for name in _JSON_LIST_FIELDS:
        if known.get(name) is not None:
            known[name] = tuple(known[name])
    return ScrollItem(**known)


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
