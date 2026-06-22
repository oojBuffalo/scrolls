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
from collections.abc import Iterable
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
    last_checked: str | None = None,
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
    item's latest verify-ledger verdict. `last_checked` is *when* that verdict
    was taken (the verdict's `checked_at`, `custody.last_checked`), or `None`
    when the item has never been re-checked — the time axis of the same
    custody picture, so an agent reads not just whether a source moved but as of
    when (and can pick a `verify --stale-before <ISO>` boundary by inspection,
    roadmap H84). Both are passed in for the same reason as `works`: this module
    stays free of the verify ledger (which `custody` reads by importing items),
    and the caller reads `latest_events` *once* per `list`, not per row. The
    defaults (`"unverified"` = `drift_posture(None)`, `last_checked=None`) are
    the honest never-checked pair, so a caller that reads an empty ledger and one
    that omits the arguments agree, and neither silently claims "clean".
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
        "last_checked": last_checked,
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


def merge_item(db_path: Path, item: ScrollItem) -> str:
    """Insert an item custody-safely, returning *why* the row was kept or skipped.

    The conflict-aware companion of `insert_item`: it still does INSERT OR IGNORE
    (the held copy is **never** overwritten — raw is sacred), but it distinguishes
    the two reasons a row is skipped so a divergence is surfaced rather than
    silently swallowed (custody vision §2.4: drift/conflict is a recorded event,
    not an overwrite; the obsidian reconcile adoption — *detect, surface, don't
    silently rewrite*). Returns one of:

    - ``"imported"`` — the id was new; the row was inserted.
    - ``"unchanged"`` — the id was already held with the **same** ``content_hash``;
      an idempotent re-import (a true custody no-op). Two reference-only rows with
      no captured content (both ``content_hash`` ``None``) are unchanged too — there
      is nothing held either way to diverge.
    - ``"conflict"`` — the id was already held with a **different** ``content_hash``;
      the incoming copy disagrees with the held one (a different capture of the
      same id — e.g. another library's bundle of a source that has since drifted).
      The held row is kept; the caller surfaces the conflicting id.

    The comparison is on ``content_hash`` — the captured-content fingerprint the
    verify ledger itself drifts on (`custody`) — not the whole row: a difference in
    a *derived* field (title, category, an enrichment tag) is not a content-custody
    conflict, only a divergence of the same captured bytes is. A within-batch
    duplicate id resolves against the row this same batch already inserted, so a
    bundle that repeats an id with different content is itself reported conflicting.
    """
    if insert_item(db_path, item):
        return "imported"
    # the id was taken (a prior import/`add`, or an earlier row in this same
    # batch); compare the captured-content fingerprint to tell an idempotent
    # re-import from a genuine divergence. `held` is non-None here barring a
    # concurrent delete — the no-op fallback keeps the contract local.
    held = get_item(db_path, item.id)
    if held is not None and held.content_hash != item.content_hash:
        return "conflict"
    return "unchanged"


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


def library_counts(db_path: Path, source: str | None = None) -> dict[str, Any]:
    """Item counts for `scrolls status`: total, by stage, by source, unclassified.

    `by_stage` always carries all three stages (zero-filled) so agents
    can read pending work — detected items await `fetch`, fetched ones
    await `md` — without key-existence checks; `by_source` lists only
    sources present. `unclassified` is the pool a batch `classify`
    would pick up (`category IS NULL`, any stage).

    `source` scopes every count to one source's items (roadmap H166), so
    `scrolls status --source <S>` reports a payload that is genuinely
    one-source — the counts agree on scope with the source-scoped custody
    block beside them. `by_source` then carries the present-and-singleton
    ``{S: N}`` (or the empty `{}` for an unknown source that holds nothing).
    """
    where = "" if source is None else " WHERE source = ?"
    params: tuple[str, ...] = () if source is None else (source,)
    conn = sqlite3.connect(db_path)
    try:
        by_stage = {"detected": 0, "fetched": 0, "rendered": 0}
        by_stage.update(
            conn.execute(
                f"SELECT stage, COUNT(*) FROM items{where} GROUP BY stage", params
            ).fetchall()
        )
        by_source = dict(
            conn.execute(
                f"SELECT source, COUNT(*) FROM items{where} "
                "GROUP BY source ORDER BY source",
                params,
            ).fetchall()
        )
        total = conn.execute(
            f"SELECT COUNT(*) FROM items{where}", params
        ).fetchone()[0]
        unclassified = conn.execute(
            "SELECT COUNT(*) FROM items WHERE category IS NULL"
            + ("" if source is None else " AND source = ?"),
            params,
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
    # The holdings-axis tier as a SQL predicate (ADR 0097), so `search --fidelity`
    # can AND it into the *ranked* match before the LIMIT — the filter must scope
    # the top-k selection, not sieve it afterwards. It takes the four content
    # *presence* booleans + stage (never the body text, the way `search`'s
    # `_PRESENCE` and `facets`' `_fidelity_counts` read presence not content) and
    # delegates to `fidelity_tier`, so the rule keeps its one home whether folded
    # in Python (list/facets) or called from SQL (search).
    conn.create_function(
        "scrolls_fidelity",
        5,
        lambda has_raw, has_extracted, has_summary, has_hash, stage: fidelity_tier(
            has_raw=bool(has_raw),
            has_extracted=bool(has_extracted),
            has_summary=bool(has_summary),
            has_hash=bool(has_hash),
            stage=stage,
        ),
        deterministic=True,
    )
    # The ledger-claim-axis posture as a SQL predicate (H58), so `search --drift`
    # can AND it into the *ranked* match before the LIMIT — like fidelity, the
    # filter must scope the top-k selection, not sieve it afterwards. Unlike
    # fidelity (a content-column fact), a posture comes from the verify ledger, so
    # the search clause hands this UDF the item's latest `custody_events.status`
    # (NULL when never verified) and it delegates to `posture_from_status`, the one
    # home of the rule the per-hit `drift` is read off in Python.
    from scrolls.custody import posture_from_status  # lazy: custody imports items

    conn.create_function(
        "scrolls_drift", 1, posture_from_status, deterministic=True
    )


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
    fidelity: str | None = None,
    drift: str | None = None,
    stale_before: str | None = None,
    stale_classification: bool = False,
    stale_summary: bool = False,
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

    `fidelity` is the holdings-axis filter (ADR 0097): it keeps only the items
    held at one custody-fidelity tier (`full`/`partial`/`reference`), derived per
    item by `get_fidelity` — the same `fidelity_tier` primitive `facets fidelity`
    counts with, so the rows it returns total that facet's count for the tier over
    the same scope (drill-from-the-count convergence, the holdings-axis twin of
    `drift` ↔ `facets drift`). Unlike `drift` it reads no ledger — fidelity is a
    pure function of stored content columns — so it is applied post-SQL over the
    already-filtered rows (it ANDs with every other facet). An unknown tier is a
    `ValueError` (a closed vocabulary, like `--stage`), never a silent empty.

    `drift` and `stale_before` are the two filters that are *not* stored columns:
    both derive from the verify ledger and are applied after the SQL filters over
    a *single* `latest_events` read (so they compose — AND — at no extra query
    when both are given). `drift` selects a custody drift posture
    (`verified`/`unverified`/`drifted`/`rotted`/`error`) via the shared
    `custody.items_in_posture` selector (roadmap H54) — so the rows it returns are
    exactly the items `facets drift` counts under that posture for the same scope
    (drill-from-the-count convergence). An unknown posture is a `ValueError` (a
    closed vocabulary, like `--stage`), never a silent empty.

    `stale_before` is a **pre-normalized** UTC ISO boundary (the caller funnels
    the raw value through `custody.parse_since`): it selects the held items whose
    newest ledger verdict predates the boundary — the *stale* set — via the same
    `custody.items_checked_before` selector `scrolls verify --stale-before` acts
    on (roadmap H85), so the rows it returns are exactly the set that recheck
    would re-capture (drill-from-the-window convergence). A never-checked item is
    trivially stale, so it is included; the boundary itself is *fresh* (the
    `items_checked_before` `< boundary` semantics). The ledger is read only when
    `drift` or `stale_before` is requested.

    `stale_classification` is the third post-SQL filter that is not a stored
    column: when true it keeps only the held items whose rules-classified
    category the *live* ruleset would no longer reproduce — the enrichment-axis
    counterpart of `drift` (the *drift*-axis stale set). It reads each item's own
    `provenance` (no ledger), via the same `classify.stale_classifications`
    selector `scrolls classify --stale` acts on and `doctor`'s
    `custody.enrichment.stale` counts, so the rows it returns total that
    aggregate (drill-from-the-count convergence, roadmap H185). It ANDs with
    every other facet — `--source` narrows it to one source's refresh debt,
    equal to `doctor`'s `enrichment.by_source[S]` — because it filters the
    already-filtered item set. A library with nothing stale is the honest empty
    selection, never an error.

    `stale_summary` is the fourth post-SQL filter that is not a stored column:
    when true it keeps only the held items that belong to a concept whose stored
    LLM summary the *live* members would no longer reproduce — the summary-axis
    counterpart of `stale_classification` (the *enrichment*-axis stale set),
    the members a `scrolls kb --stale` refresh's clusters span (roadmap H189).
    Unlike the other three filters it is **not** item-local: summary staleness
    is a property of a *concept* over its whole membership, so the stale-member
    set is computed over the **whole library** (`kb_llm.stale_summary_members`
    over a fresh `list_items` read + the stored summaries) and then intersected
    with the already-filtered rows. The intersection is what makes it AND with
    every other facet *and* carry the H171 attribution: `--source S` returns
    S's members of the clusters S participates in (a multi-source cluster is
    eligible over its full membership, so narrowing it to S keeps S's members),
    equal to the S-members `kb --stale --source S` would refresh. Nothing
    eligible or nothing stale is the honest empty selection, never an error.
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
    if fidelity is not None:
        # The holdings axis: a pure function of stored content columns (no ledger),
        # so it filters the SQL-loaded rows directly via `get_fidelity` — the same
        # primitive `facets fidelity` folds, keeping the two convergent.
        from scrolls.custody import FIDELITY_TIERS

        if fidelity not in FIDELITY_TIERS:
            raise ValueError(
                f"unknown fidelity tier {fidelity!r}; "
                f"choose one of {', '.join(FIDELITY_TIERS)}"
            )
        items = [item for item in items if get_fidelity(item) == fidelity]
    if drift is not None or stale_before is not None:
        # lazy: custody imports items, so the reverse is import-time only here
        from scrolls.custody import (
            DRIFT_POSTURES,
            items_checked_before,
            items_in_posture,
            latest_events,
        )

        verdicts = latest_events(db_path)
        if drift is not None:
            if drift not in DRIFT_POSTURES:
                raise ValueError(
                    f"unknown drift posture {drift!r}; "
                    f"choose one of {', '.join(DRIFT_POSTURES)}"
                )
            items = items_in_posture(items, verdicts, drift)
        if stale_before is not None:
            items = items_checked_before(items, verdicts, stale_before)
    if stale_classification:
        # lazy: classify imports items, so the reverse is import-time only here.
        # Filter the already-filtered set, so it ANDs with every facet above and
        # the per-source narrowing rides the SQL `source` clause (no source arg
        # needed — `stale_classifications(items)` over the scoped rows).
        from scrolls.classify import stale_classifications

        items = stale_classifications(items)
    if stale_summary:
        # lazy: kb_llm imports items, so the reverse is import-time only here.
        # Summary staleness is a *concept* property over its whole membership,
        # so compute the stale-member set over the WHOLE library (a fresh read,
        # the way `kb --stale` resolves its targets) and intersect with the
        # already-filtered rows by id. The intersection ANDs the filter with
        # every facet above and narrows `--source S` to S's members of the
        # clusters S participates in (the H171 attribution), while the rows keep
        # this listing's `saved_at, id` ordering.
        from scrolls.kb import load_concept_summaries
        from scrolls.kb_llm import stale_summary_members

        stale_ids = {
            item.id
            for item in stale_summary_members(
                list_items(db_path), load_concept_summaries(db_path)
            )
        }
        items = [item for item in items if item.id in stale_ids]
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


# --- prior-content archive (accept-incoming recovery, ADR 0106) -------------


@dataclass(frozen=True)
class ArchiveEntry:
    """One archived prior capture an adoption superseded — a recovery-index row.

    The metadata an operator scans (`scrolls archive list`): *which* held copy was
    replaced, the hash before/after, and when. The model-complete prior snapshot
    itself is fetched on demand by `latest_archived` (so listing many entries does
    not parse every body).
    """

    archive_id: int
    item_id: str
    archived_at: str
    prior_hash: str | None
    superseded_by: str | None


def adopt_incoming(
    db_path: Path, incoming: ScrollItem, *, archived_at: str
) -> ScrollItem | None:
    """Replace the held copy of `incoming.id` with `incoming`, archiving the prior (ADR 0106).

    The one custody-safe overwrite in Scrolls — the accept-incoming reconcile
    resolution (roadmap H278). It is **not** a destructive overwrite: before the
    held row is replaced, its model-complete snapshot is appended to `item_archive`,
    so the superseded capture stays recoverable (raw is never destroyed — custody
    §2.4). The archive insert and the items UPDATE commit in **one transaction**, so
    a crash never leaves the row replaced with the prior capture unsaved.

    Reads the currently-held (prior) row; returns ``None`` without writing when the
    id is absent (a defensive no-op — nothing to supersede). Otherwise returns the
    prior `ScrollItem`, so the caller can record the `superseded` custody event with
    the archived ``prior_hash``. The held body — every column — becomes the incoming
    one; the prior is reachable only through the archive from here on.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            prior_row = conn.execute(
                "SELECT * FROM items WHERE id = ?", (incoming.id,)
            ).fetchone()
            if prior_row is None:
                return None
            prior = _from_row(prior_row)
            conn.execute(
                "INSERT INTO item_archive (item_id, archived_at, prior_hash, "
                "superseded_by, snapshot) VALUES (?, ?, ?, ?, ?)",
                (
                    prior.id,
                    archived_at,
                    prior.content_hash,
                    incoming.content_hash,
                    json.dumps(item_to_dict(prior)),
                ),
            )
            row = _to_row(incoming)
            value_names = tuple(name for name in _FIELD_NAMES if name != "id")
            assignments = ", ".join(f"{name} = ?" for name in value_names)
            conn.execute(
                f"UPDATE items SET {assignments} WHERE id = ?",
                tuple(row[name] for name in value_names) + (incoming.id,),
            )
        return prior
    finally:
        conn.close()


def list_archived(db_path: Path, item_id: str | None = None) -> list[ArchiveEntry]:
    """Archived prior captures, newest first — the recovery index (`scrolls archive list`).

    Optionally filtered to one ``item_id``. Returns lightweight `ArchiveEntry`
    metadata (no body), so an operator can see *what* an adoption replaced and
    *when* before fetching the snapshot. Tolerates a pre-v8 library (no archive
    table) by returning an empty list.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if item_id is None:
            rows = conn.execute(
                "SELECT id, item_id, archived_at, prior_hash, superseded_by "
                "FROM item_archive ORDER BY id DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, item_id, archived_at, prior_hash, superseded_by "
                "FROM item_archive WHERE item_id = ? ORDER BY id DESC",
                (item_id,),
            ).fetchall()
    except sqlite3.OperationalError:  # pre-v8 library, no archive table
        return []
    finally:
        conn.close()
    return [
        ArchiveEntry(
            archive_id=row["id"],
            item_id=row["item_id"],
            archived_at=row["archived_at"],
            prior_hash=row["prior_hash"],
            superseded_by=row["superseded_by"],
        )
        for row in rows
    ]


def latest_archived(db_path: Path, item_id: str) -> ScrollItem | None:
    """The most recently archived prior capture for `item_id`, or ``None``.

    The recovery read behind `scrolls archive show <id>`: parses the model-complete
    snapshot of the latest (highest-`id`) archived copy back into a `ScrollItem`, so
    it re-emits as a re-importable `export items` line — restoring it is then just
    `import items … --accept-incoming` of that line (the symmetric round-trip).
    Returns ``None`` when the id has no archived prior (never superseded).
    """
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT snapshot FROM item_archive WHERE item_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (item_id,),
        ).fetchone()
    except sqlite3.OperationalError:  # pre-v8 library, no archive table
        return None
    finally:
        conn.close()
    if row is None:
        return None
    return item_from_dict(json.loads(row[0]))


# --- portable prior-content archive (the recovery store travels, roadmap H280) ---
#
# ADR 0106 made adoption custody-safe *locally*: the superseded prior is archived
# and recoverable via `scrolls archive show`. But the archive is a **local** store
# — a `superseded` event travels in the lossless round-trip while the archived
# prior *bytes* stay behind, so a library rebuilt from a bundle can read *that an
# adoption happened* (the event) but cannot recover the prior copy. H280 lets the
# recovery store travel: `export bundle --with-archive` carries a third
# sentinel-fenced archive block, and `export archive` is the whole-library JSONL
# sibling of `export events`, with an idempotent `import` deduped by
# `(item_id, prior_hash)` — the H67 events-dedup precedent on the archive identity.


@dataclass(frozen=True)
class ArchiveRecord:
    """One archived prior capture as a portable, re-importable row (roadmap H280).

    The full `item_archive` row minus the per-library autoincrement `id` (never
    exported, re-numbered on restore, exactly like the custody-event `id`): the
    metadata an adoption recorded — *which* held copy was replaced, the hash
    before/after, *when* — plus the model-complete `item_to_dict` ``snapshot`` of
    the prior capture itself, so a fresh library re-emits the same prior through
    `archive show`. The export/recovery counterpart of the metadata-only
    `ArchiveEntry` (`archive list`), which carries no body.
    """

    item_id: str
    archived_at: str
    prior_hash: str | None
    superseded_by: str | None
    snapshot: dict[str, Any]


def archived_records(
    db_path: Path, item_ids: Iterable[str] | None = None
) -> list[ArchiveRecord]:
    """The archive's prior captures as portable `ArchiveRecord`s — the export read.

    Unlike `list_archived` (metadata only, newest first, for the `archive list`
    index) this carries each prior's model-complete ``snapshot``, so it is the
    read behind `export archive` and the bundle's `--with-archive` block. Filtered
    to a set of ``item_ids`` when given (the bundle scopes the archive to its
    in-scope items, the items-block symmetry); the whole archive otherwise (the
    whole-library backup).

    Ordered by ``(archived_at, item_id, prior_hash)`` — fully content-determined,
    independent of the per-library autoincrement `id` (never exported) — so a
    re-export after an `import_archive` reproduces the stream **byte-for-byte**
    regardless of the restored rows' local ids, and within an item the
    latest-``archived_at`` prior still imports to the highest local id, so
    `latest_archived`/`archive show` keeps returning the most-recently-superseded
    copy. Tolerates a pre-v8 library (no archive table) by returning ``[]``.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT item_id, archived_at, prior_hash, superseded_by, snapshot "
            "FROM item_archive"
        ).fetchall()
    except sqlite3.OperationalError:  # pre-v8 library, no archive table
        return []
    finally:
        conn.close()
    wanted = set(item_ids) if item_ids is not None else None
    records = [
        ArchiveRecord(
            item_id=row["item_id"],
            archived_at=row["archived_at"],
            prior_hash=row["prior_hash"],
            superseded_by=row["superseded_by"],
            snapshot=json.loads(row["snapshot"]),
        )
        for row in rows
        if wanted is None or row["item_id"] in wanted
    ]
    records.sort(key=lambda r: (r.archived_at, r.item_id, r.prior_hash or ""))
    return records


def archive_export_dict(record: ArchiveRecord) -> dict[str, Any]:
    """One archive row as a JSON-serializable export object (roadmap H280).

    The `snapshot` is embedded as a nested object (not a JSON string-in-string),
    so the JSONL stays clean and `jq`-friendly, the `event_export_dict` idiom. The
    inverse is `archive_from_dict`.
    """
    return {
        "item_id": record.item_id,
        "archived_at": record.archived_at,
        "prior_hash": record.prior_hash,
        "superseded_by": record.superseded_by,
        "snapshot": record.snapshot,
    }


def archive_from_dict(data: dict[str, Any]) -> ArchiveRecord:
    """Reconstruct an `ArchiveRecord` from an export object — the inverse.

    `prior_hash`/`superseded_by` are nullable (a prior with no content hash, or an
    adoption that recorded no incoming hash). Unknown keys are tolerated for
    forward compatibility. The caller validates the required identity fields
    (`item_id`/`archived_at`/`snapshot`), like `item_from_dict`/`event_from_dict`.
    """
    return ArchiveRecord(
        item_id=data["item_id"],
        archived_at=data["archived_at"],
        prior_hash=data.get("prior_hash"),
        superseded_by=data.get("superseded_by"),
        snapshot=data["snapshot"],
    )


def dump_archive_export(records: Iterable[ArchiveRecord]) -> str:
    """Serialize archive records to JSON Lines — the `export archive` / bundle block.

    One JSON object per record per line (newline-terminated), in the given order
    (`archived_records` already orders content-deterministically). Mirrors
    `dump_items_export`/`dump_events_export`: an empty iterable produces an empty
    string — a valid empty document, the shape an un-superseded library's archive
    block takes.
    """
    return "".join(json.dumps(archive_export_dict(r)) + "\n" for r in records)


# The content key that identifies an archived prior across libraries — the
# autoincrement `id` is per-library (never exported) and `superseded_by`/`snapshot`
# describe the same prior, so neither is part of the identity. Two archive rows
# with this pair equal are the same recoverable prior capture (roadmap H280's
# idempotent-restore key, the H67 events-dedup precedent on the archive axis).
_ARCHIVE_IDENTITY = ("item_id", "prior_hash")


def import_archive(
    db_path: Path, records: Iterable[ArchiveRecord]
) -> tuple[int, int]:
    """Restore archived prior captures, deduped by content; return ``(imported, skipped)``.

    The archive-axis sibling of `import_events` (roadmap H280): a record is skipped
    when the archive already holds a row with the same ``(item_id, prior_hash)`` —
    so re-importing the same recovery store twice, or the overlapping union of two
    bundles, is a no-op (the append-only archive would otherwise grow on every
    re-import). NULL hashes compare NULL-safely (SQLite ``IS``). Within-batch
    duplicates also dedup: the first insert makes the next iteration's existence
    check see it.

    Unlike the events restore, the archive is a standalone recovery store keyed by
    `item_id` with **no** held-row interaction — importing a prior for an id the
    target does not currently hold is harmless (it simply populates the recovery
    store), so there is no orphan split here. The held copy is never touched: this
    only ever appends to `item_archive`.
    """
    where = " AND ".join(f"{col} IS ?" for col in _ARCHIVE_IDENTITY)
    imported = skipped = 0
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            for r in records:
                identity = (r.item_id, r.prior_hash)
                exists = conn.execute(
                    f"SELECT 1 FROM item_archive WHERE {where} LIMIT 1", identity
                ).fetchone()
                if exists is not None:
                    skipped += 1
                    continue
                conn.execute(
                    "INSERT INTO item_archive (item_id, archived_at, prior_hash, "
                    "superseded_by, snapshot) VALUES (?, ?, ?, ?, ?)",
                    (
                        r.item_id,
                        r.archived_at,
                        r.prior_hash,
                        r.superseded_by,
                        json.dumps(r.snapshot),
                    ),
                )
                imported += 1
    finally:
        conn.close()
    return imported, skipped


def preview_import_archive(
    db_path: Path, records: Iterable[ArchiveRecord]
) -> tuple[int, int]:
    """Count how `import_archive` would split `records` *without writing* — the
    read-only sibling for `import bundle --dry-run` (the `preview_import_events` idiom).

    Mirrors `import_archive`'s dedup exactly: a record is *skipped* when the archive
    already holds its ``(item_id, prior_hash)`` or an earlier record in this same
    batch already claimed it; otherwise *imported*. The within-batch dedup the
    writer gets for free from its prior INSERT is tracked here in a local `seen` set.
    """
    where = " AND ".join(f"{col} IS ?" for col in _ARCHIVE_IDENTITY)
    imported = skipped = 0
    seen: set[tuple[object, ...]] = set()
    conn = sqlite3.connect(db_path)
    try:
        for r in records:
            identity = (r.item_id, r.prior_hash)
            if identity in seen:
                skipped += 1
                continue
            exists = conn.execute(
                f"SELECT 1 FROM item_archive WHERE {where} LIMIT 1", identity
            ).fetchone()
            if exists is not None:
                skipped += 1
                continue
            seen.add(identity)
            imported += 1
    finally:
        conn.close()
    return imported, skipped
