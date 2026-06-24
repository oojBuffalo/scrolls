"""Full-text search over the items index (IDEAS.md §14 Pass 3).

FTS5 BM25 ranking with the title weighted above the summary, and the
summary above the body, so items *about* a topic beat items that merely
mention it. User queries are quoted token-by-token (implicit AND) instead
of being passed as raw FTS5 syntax: agents send arbitrary strings, and
robustness beats phrase/NEAR operators for now.

Optional `source`/`category`/`stage` facets narrow the ranked match the way
`scrolls list` filters the full item set (ADR 0058): with 30+ heterogeneous
sources in one library, "what *papers* does my library know about X" needs
to scope a search, not just a flat listing. Filters AND with the FTS match
and never reorder it; the empty-string `category` selects the unclassified
pool, mirroring `list_items`/`scrolls set`.

Each hit also carries the per-item custody axes: its `fidelity` tier
(full/partial/reference, ADR 0097) — derived from content *presence* read in
SQL, never by hauling each match's body text — its `drift` posture
(verified/unverified/drifted/rotted/error, roadmap H58) read from the verify
ledger, and `last_checked` (when that posture was taken, or null when never
re-checked, roadmap H84). So a search result tells an agent not just *what*
matched but at what fidelity the library still holds it, whether that source has
drifted out from under the capture, *and* as of when — the same custody picture
`scrolls list` rows, `scrolls related` hits, and the `scrolls graph` node shape
report.

A hit also carries the scholarly work(s) it represents (ADR 0101): when two
ranked hits are the same work — an arXiv preprint and its published Crossref
record — each names the work's DOI and points at its canonical representation,
so an agent searching "attention is all you need" sees the two top hits *are*
one work and which form to prefer, rather than treating them as unrelated
results. Computed by the same DOI clustering `scrolls works` reports.

A hit also carries the derived `classification` view (roadmap H26): how its
category was produced — the engine, the rules precedence tier, the ruleset
fingerprint, the LLM model — the same view `scrolls list`/`show` surface, so an
agent reads a category's provenance identically whether it browsed to the item
or searched for it. Built per-hit from the row's own `provenance` column
(`classification_view`), so it costs no extra query and stays scope-honest;
omitted entirely when no engine stamped the category (the honest-absence shape
`list` keeps), via the shared `hit_payload` serializer.

Finally, a hit *explains its own rank*: the raw BM25 `score` is opaque (a
negative float whose magnitude depends on the query and corpus), so each hit
also carries `matched_fields` — the indexed fields the query terms landed in, in
BM25-weight order (title/summary/extracted_text) — and `match_strength`, the
qualitative confidence those weights imply (`strong` title hit / `moderate`
summary hit / `weak` body-only hit). Computed by column-restricted FTS matches
over the already-ranked hit rowids (never hauling a match's body text), with an
any-token (OR) test per field so a hit whose terms split across columns names
*both* fields it landed in. Grounded in the very column weights that produced
the order, it is custody's ranking signal — provenance and holdings, not
engagement (custody-vision §3.5) — not an invented relevance score.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from scrolls.custody import (
    DRIFT_POSTURES,
    FIDELITY_TIERS,
    drift_posture,
    last_checked,
    latest_events,
)
from scrolls.items import (
    classification_view,
    fidelity_tier,
    item_filters,
    list_items,
    register_facet_functions,
)
from scrolls.works import WorkRef, work_membership

_BM25_WEIGHTS = "5.0, 2.0, 1.0"  # title, summary, extracted_text
_SNIPPET_TOKENS = 12

# The indexed FTS columns in BM25-weight order (highest first), the same order
# `_BM25_WEIGHTS` weights them. A hit's `matched_fields` lists the subset of these
# its query terms actually landed in, and `match_strength` names the strength of
# the highest-weighted one — so the explanation is grounded in the very weights
# that produced the rank, never an invented relevance score (custody-vision §3.5:
# provenance and fidelity, not engagement, rank a custody library).
_FTS_FIELDS = ("title", "summary", "extracted_text")
_STRENGTH_BY_FIELD = {
    "title": "strong",
    "summary": "moderate",
    "extracted_text": "weak",
}

# The strength bands in descending field-weight order (strongest first), 1:1 with
# `_FTS_FIELDS` so band index `i` names the same field as `_FTS_FIELDS[i]`. The
# closed vocabulary `tally_strength` partitions over and `--strength` filters by;
# derived from `_STRENGTH_BY_FIELD` so the order can never drift from the weights.
STRENGTH_BANDS = tuple(_STRENGTH_BY_FIELD[field] for field in _FTS_FIELDS)

# Presence, not content: the fidelity tier (ADR 0097) needs to know only
# *whether* each body column is populated, so the query asks SQLite for the
# booleans and never moves a match's (potentially multi-kilobyte) body text.
_PRESENCE = (
    "(items.raw_text IS NOT NULL AND items.raw_text != '') AS has_raw",
    "(items.extracted_text IS NOT NULL AND items.extracted_text != '') AS has_extracted",
    "(items.summary IS NOT NULL AND items.summary != '') AS has_summary",
    "(items.content_hash IS NOT NULL AND items.content_hash != '') AS has_hash",
)

_QUERY = f"""\
SELECT items_fts.rowid AS rowid,
       items.id, items.source, items.title, items.url, items.stage,
       bm25(items_fts, {_BM25_WEIGHTS}) AS score,
       snippet(items_fts, -1, '[', ']', '…', {_SNIPPET_TOKENS}) AS snippet,
       items.provenance,
       {", ".join(_PRESENCE)}
FROM items_fts
JOIN items ON items.rowid = items_fts.rowid
WHERE items_fts MATCH ?{{filters}}
ORDER BY bm25(items_fts, {_BM25_WEIGHTS})
LIMIT ?
"""

# The same match + facets as `_QUERY`, but counting rather than ranking and
# with no LIMIT — the denominator behind G2's truncation marker (`docs/cli.md`,
# completeness contract): how many items the query matches *in scope* before
# the cap, so `scrolls search --stats` can say "top 20 of 200", not just 20.
_COUNT_QUERY = """\
SELECT COUNT(*)
FROM items_fts
JOIN items ON items.rowid = items_fts.rowid
WHERE items_fts MATCH ?{filters}
"""

# The holdings-axis filter (ADR 0097) as a WHERE clause: the `scrolls_fidelity`
# UDF (registered by `register_facet_functions`) folds the four content-presence
# booleans + stage through `fidelity_tier`, so the clause matches the tier
# `search`'s per-hit `fidelity` is read off. Passing the presence expressions —
# not the body columns — keeps the "presence, not content" discipline `_PRESENCE`
# observes: the body text never leaves SQLite for this filter either.
_FIDELITY_CLAUSE = (
    "scrolls_fidelity("
    "(items.raw_text IS NOT NULL AND items.raw_text != ''), "
    "(items.extracted_text IS NOT NULL AND items.extracted_text != ''), "
    "(items.summary IS NOT NULL AND items.summary != ''), "
    "(items.content_hash IS NOT NULL AND items.content_hash != ''), "
    "items.stage) = ?"
)

# The drift-posture filter (the ledger-claim axis, H58) as a WHERE clause. Unlike
# `_FIDELITY_CLAUSE` — a pure function of the item's own content columns — a hit's
# drift posture is read from the *verify ledger* (its latest `custody_events`
# verdict), so the clause first pulls that latest status via a correlated subquery
# (the largest `id` per item — the `latest_events` "most recent" rule, and the
# `custody_events_item` index keeps it cheap) and folds it through the
# `scrolls_drift` UDF, which delegates to the same `posture_from_status` the
# per-hit `drift` is read off. So the clause matches exactly the posture each hit
# shows, and a never-verified item (no row → the subquery yields NULL) maps to
# `unverified`. ANDed before the LIMIT, so it scopes the top-k ranked selection
# (the top hits at that posture), never a post-cap sieve of them.
_DRIFT_CLAUSE = (
    "scrolls_drift((SELECT ce.status FROM custody_events ce "
    "WHERE ce.item_id = items.id ORDER BY ce.id DESC LIMIT 1)) = ?"
)

# The match-strength filter (the rank axis, H314) as a WHERE clause. A hit's
# `match_strength` is the band of the highest-weighted indexed field its query
# terms landed in (`_match_strength` over `matched_fields`), computed *post-cap* on
# the returned rows — but a filter must scope the *ranked* selection before the
# LIMIT, exactly as `--fidelity`/`--drift` do, so the band rides a column-restricted
# FTS sub-match rather than a post-sieve. The semantics is a **threshold** (at or
# above the band): `--strength strong` keeps title hits, `--strength moderate` keeps
# title-or-summary hits, `--strength weak` keeps every match — because a hit reads
# `match_strength == band` exactly when its query lands in `band`'s column *or* a
# higher-weighted one, and the prefix `_FTS_FIELDS[:i+1]` for band index `i` names
# precisely those columns. The clause restricts a fresh `items_fts` MATCH to that
# column set with the same any-token (OR) test `_match_explanations` reads
# `matched_fields` off, and intersects the result with the outer hit rowids — so a
# row is kept by exactly the field-landing its own `match_strength` reports. The
# match string is the bound parameter (`{col …} : (t1 OR t2 …)`), built per call
# from the band's columns and the query tokens.
_STRENGTH_CLAUSE = (
    "items_fts.rowid IN (SELECT rowid FROM items_fts WHERE items_fts MATCH ?)"
)


def _strength_match(strength: str, tokens: list[str]) -> str:
    """The column-restricted FTS match string behind `--strength` (H314).

    `strength` names a band in `STRENGTH_BANDS` (strongest first, 1:1 with
    `_FTS_FIELDS`), so the columns *at or above* it are the prefix
    `_FTS_FIELDS[:i+1]` — `strong` → title, `moderate` → title+summary, `weak` →
    every field. Restricts the bound query to that column set with the same
    any-token (OR) test `_match_explanations` reads `matched_fields` off, so the
    filter keeps exactly the hits whose `match_strength` is the band or stronger.
    """
    columns = _FTS_FIELDS[: STRENGTH_BANDS.index(strength) + 1]
    any_token = " OR ".join(tokens)
    return f"{{{' '.join(columns)}}} : ({any_token})"


def _search_filters(
    source: str | None,
    category: str | None,
    stage: str | None,
    tag: str | None,
    concept: str | None,
    fidelity: str | None,
    drift: str | None,
    strength: str | None = None,
    tokens: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """The shared facet clauses for the ranked query and its count.

    `item_filters` covers the stored-column facets (source/category/stage/tag/
    concept) the ranked query and `facets` share. `fidelity`, `drift`, and
    `strength` are the facets that are *derived*, not stored columns, so each rides
    a clause: `fidelity` (ADR 0097) folds the content-presence booleans through the
    `scrolls_fidelity` UDF; `drift` (H58) folds the item's latest verify verdict
    through `scrolls_drift`; `strength` (H314) restricts a fresh `items_fts` MATCH
    to the columns at or above the band and intersects it with the hit rowids (the
    `_STRENGTH_CLAUSE`, with `_strength_match` building the bound query from
    `tokens`). Because all three AND into the SQL *before* the LIMIT, they scope the
    top-k ranked selection (the top hits at that tier/posture/strength), never a
    post-cap sieve; `count_matches` appends the identical clauses, so the G2
    truncation marker counts only the kept set. An unknown tier/posture/band is a
    `ValueError` (a closed vocabulary, like `list_items`), raised before any DB
    access so it never depends on library state.
    """
    clauses, params = item_filters(source, category, stage, tag, concept)
    if fidelity is not None:
        if fidelity not in FIDELITY_TIERS:
            raise ValueError(
                f"unknown fidelity tier {fidelity!r}; "
                f"choose one of {', '.join(FIDELITY_TIERS)}"
            )
        clauses.append(_FIDELITY_CLAUSE)
        params.append(fidelity)
    if drift is not None:
        if drift not in DRIFT_POSTURES:
            raise ValueError(
                f"unknown drift posture {drift!r}; "
                f"choose one of {', '.join(DRIFT_POSTURES)}"
            )
        clauses.append(_DRIFT_CLAUSE)
        params.append(drift)
    if strength is not None:
        if strength not in STRENGTH_BANDS:
            raise ValueError(
                f"unknown match strength {strength!r}; "
                f"choose one of {', '.join(STRENGTH_BANDS)}"
            )
        clauses.append(_STRENGTH_CLAUSE)
        params.append(_strength_match(strength, tokens or []))
    return clauses, params


DEFAULT_LIMIT = 20


@dataclass(frozen=True)
class SearchHit:
    id: str
    source: str
    title: str | None
    url: str
    stage: str
    score: float
    snippet: str
    fidelity: str
    # The hit's custody drift posture (verified/unverified/drifted/rotted/error,
    # roadmap H58) — `custody.drift_posture` over its latest verify-ledger
    # verdict. `_hit` builds the hit with the honest never-checked default; the
    # `search_items` annotation pass (which reads the ledger once) sets the real
    # posture, the same shape `related`/`graph` carry alongside `fidelity`.
    drift: str = "unverified"
    # When that latest verdict was taken (`custody.last_checked`), or None when
    # never re-checked — the time axis of the per-item custody picture (roadmap
    # H84), set in the same annotation pass from the same ledger read as `drift`.
    last_checked: str | None = None
    works: tuple[WorkRef, ...] = field(default_factory=tuple)
    # How the hit's category was produced, when an engine recorded it (H26); None
    # for a user-set or unclassified hit. `hit_payload` drops the key in that
    # case, the honest-absence shape `list`/`show` keep.
    classification: dict[str, Any] | None = None
    # Which indexed fields the query terms landed in (BM25-weight order:
    # title/summary/extracted_text), and the qualitative strength of the
    # highest-weighted one (`strong`/`moderate`/`weak`) — the explanation behind
    # the opaque `score`. Built by the `search_items` annotation pass from
    # column-restricted FTS matches over the hit rowids (never the body text);
    # `()`/`"weak"` until that pass runs, never empty for a real match.
    matched_fields: tuple[str, ...] = ()
    match_strength: str = "weak"


def search_items(
    db_path: Path,
    query: str,
    limit: int = DEFAULT_LIMIT,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
    fidelity: str | None = None,
    drift: str | None = None,
    strength: str | None = None,
) -> list[SearchHit]:
    """BM25-ranked hits for a free-text query; raises ValueError if it has no tokens.

    `source` and `stage` match exactly; `category` matches exactly too,
    except the empty string, which selects items *without* a category — the
    unclassified pool, mirroring `list_items`/`scrolls set`. `tag` and
    `concept` are membership facets over the JSON array columns (ADR 0059):
    `tag` matches case-insensitively, `concept` by slug, each the way
    `scrolls related` compares them. `None` never filters. Filters AND with
    the full-text match and leave the ranking untouched.

    `fidelity` is the holdings-axis filter (ADR 0097): it keeps only the matches
    the library holds at one custody-fidelity tier (`full`/`partial`/`reference`),
    derived from the same content-presence flags each hit's own `fidelity` is read
    off. Unlike `list_items` — which has no cap, so it sieves the loaded rows in
    Python — `search` applies a ranked `LIMIT`, so the tier must scope the *ranked*
    selection (the top-k full-fidelity matches), not sieve it afterwards; it
    therefore rides a SQL clause (`scrolls_fidelity`) ANDed before the LIMIT. An
    unknown tier is a `ValueError` (a closed vocabulary, like `list_items`).

    `drift` is the ledger-claim-axis companion (H58): it keeps only the matches
    whose latest verify verdict reads at one posture
    (`verified`/`unverified`/`drifted`/`rotted`/`error`), the same posture each
    hit's own `drift` is read off. Unlike `fidelity` (a content-column fact), a
    posture comes from the verify ledger, so it rides the `scrolls_drift` clause
    over the item's latest `custody_events` verdict — also ANDed before the LIMIT,
    so it scopes the ranked selection (the top hits at that posture). An unknown
    posture is a `ValueError` (closed vocabulary).

    `strength` is the rank-axis companion (H314): it keeps only the matches whose
    query lands at or above a field-weight band (`strong`/`moderate`/`weak`) — the
    same band each hit's own `match_strength` reports. `--strength strong` keeps
    title hits, `moderate` keeps title-or-summary hits, `weak` keeps every match.
    Like `fidelity`/`drift` it rides a SQL clause ANDed before the LIMIT (a
    column-restricted `items_fts` sub-match), so it scopes the ranked selection (the
    top hits at that strength), not a post-cap sieve. An unknown band is a
    `ValueError` (closed vocabulary).

    A missing database means an empty library: no hits, and the query is
    still validated so callers surface bad input consistently.
    """
    tokens = _escape_tokens(query)
    match = " ".join(tokens)
    clauses, params = _search_filters(
        source, category, stage, tag, concept, fidelity, drift, strength, tokens
    )
    if not db_path.exists():
        return []
    sql = _QUERY.format(filters="".join(f"\n  AND {clause}" for clause in clauses))
    conn = sqlite3.connect(db_path)
    register_facet_functions(conn)
    try:
        rows = conn.execute(sql, (match, *params, limit)).fetchall()
        rowids = [row[0] for row in rows]
        hits = [_hit(row[1:]) for row in rows]
        # The match explanation rides the *same* open connection and the already
        # ranked+capped rowids, so it adds three column-restricted FTS matches
        # over a small set, never a re-scan of the whole index nor a body haul.
        explanations = _match_explanations(conn, tokens, rowids) if rowids else {}
    finally:
        conn.close()
    if not hits:
        return hits
    # Annotate each hit with the work(s) it represents (ADR 0101). Membership
    # is a property of the *whole* library — a hit's sibling representation may
    # be filtered out of this result, or rank below the limit — so it clusters
    # over every item, not just the matched rows. The search facets are
    # deliberately NOT passed to list_items here: applying them would re-hide
    # the very siblings this annotation exists to surface, undercounting a work.
    # Only computed when there are hits to annotate; the cost mirrors `scrolls
    # works`, which list_items the library the same way.
    membership = work_membership(list_items(db_path))
    # …and with its custody drift posture + last-checked timestamp (roadmap
    # H58/H84), from one `latest_events` read for the whole result (the way
    # `related`/`graph` read the ledger once), so a search hit carries the same
    # custody axes every browse surface reports — `fidelity` (how much is held),
    # `drift` (whether the source moved), and `last_checked` (as of when).
    verdicts = latest_events(db_path)
    return [
        replace(
            hit,
            works=membership.get(hit.id, ()),
            drift=drift_posture(verdicts.get(hit.id)),
            last_checked=last_checked(verdicts.get(hit.id)),
            matched_fields=explanations.get(rowid, ()),
            match_strength=_match_strength(explanations.get(rowid, ())),
        )
        for hit, rowid in zip(hits, rowids)
    ]


def count_matches(
    db_path: Path,
    query: str,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
    fidelity: str | None = None,
    drift: str | None = None,
    strength: str | None = None,
) -> int:
    """Total items matching `query` in scope, ignoring the result cap.

    The honest denominator for `scrolls search --stats` (completeness
    contract G2): `search_items` returns at most `limit` hits, so on its own
    `len(hits)` cannot tell "those are all the matches" from "the top N of
    more". This counts every match under the *same* FTS query and facets
    (`fidelity` included, so a `--fidelity full --stats` result is never marked
    truncated by partials it never showed), with no `LIMIT`, so the caller can
    mark a result truncated exactly when `count_matches > len(hits)`. Validates
    the query the same way `search_items` does; a missing database is an empty
    library (0 matches). `drift` (the ledger-axis filter) is honored too, so a
    `--drift verified --stats` result is never marked truncated by hits at
    postures it never showed. `strength` (the rank-axis filter, H314) is honored
    too, so a `--strength strong --stats` result is never marked truncated by
    weaker-landing hits it never showed.
    """
    tokens = _escape_tokens(query)
    match = " ".join(tokens)
    clauses, params = _search_filters(
        source, category, stage, tag, concept, fidelity, drift, strength, tokens
    )
    if not db_path.exists():
        return 0
    sql = _COUNT_QUERY.format(filters="".join(f"\n  AND {clause}" for clause in clauses))
    conn = sqlite3.connect(db_path)
    register_facet_functions(conn)
    try:
        (count,) = conn.execute(sql, (match, *params)).fetchone()
    finally:
        conn.close()
    return count


def _hit(row: tuple) -> SearchHit:
    """Build a hit from a result row, folding the four presence flags into a tier.

    The query selects the ranked fields (`id`…`snippet`), then the raw
    `provenance` JSON, then the four `has_*` presence booleans; this collapses the
    trailing flags into one `fidelity` string and derives the `classification`
    view from the provenance, so the dataclass carries the tier and the recorded
    method, not the raw columns.
    """
    *ranked, has_raw, has_extracted, has_summary, has_hash = row
    id_, source, title, url, stage, score, snippet, provenance_json = ranked
    provenance = json.loads(provenance_json) if provenance_json else None
    return SearchHit(
        id=id_,
        source=source,
        title=title,
        url=url,
        stage=stage,
        score=score,
        snippet=snippet,
        fidelity=fidelity_tier(
            has_raw=bool(has_raw),
            has_extracted=bool(has_extracted),
            has_summary=bool(has_summary),
            has_hash=bool(has_hash),
            stage=stage,
        ),
        classification=classification_view(provenance),
    )


def hit_payload(hit: SearchHit) -> dict[str, Any]:
    """The JSON-ready form of a hit, shared by `scrolls search` and MCP `search_scrolls`.

    `asdict` renders the nested `works`/`classification`; the `classification`
    key is then dropped when no engine stamped the hit's category — the
    honest-absence shape `list`/`show` use (`classification_provenance`), so an
    unclassified hit keeps a stable row shape and a classified one reads
    identically across the CLI and MCP surfaces (H26 parity, one home).
    """
    data = asdict(hit)
    if data.get("classification") is None:
        data.pop("classification")
    return data


def _escape_tokens(query: str) -> list[str]:
    """The query's tokens, each quoted so user input never hits FTS5 syntax.

    Each token becomes a `"phrase"` literal, so reserved words (`AND`/`OR`/`NEAR`)
    and punctuation are matched as text, not parsed as operators. Raises
    `ValueError` when nothing searchable remains. The shared root of the
    implicit-AND match (`" ".join(tokens)`, the same string `search_items`/
    `count_matches` MATCH on), the per-field OR explanation (`_match_explanations`),
    and the `--strength` column-restricted sub-match (`_strength_match`), so they
    never tokenize a query differently.
    """
    tokens = [token.replace('"', "") for token in query.split()]
    tokens = [f'"{token}"' for token in tokens if token]
    if not tokens:
        raise ValueError("search query has no searchable tokens")
    return tokens


def _match_explanations(
    conn: sqlite3.Connection, tokens: list[str], rowids: list[int]
) -> dict[int, tuple[str, ...]]:
    """Per-hit, the indexed fields the query terms landed in (BM25-weight order).

    For each indexed column, one column-restricted FTS match — `field : (t1 OR t2
    …)` — intersected with the already ranked+capped hit `rowids`, so it asks the
    index "which of *these* hits does each field match", never re-scanning the
    library nor hauling a match's (potentially multi-kilobyte) body text. The OR
    over tokens (not AND) is deliberate: the overall hit ANDs its tokens *across*
    columns, so a hit can match because one token is in the title and another in
    the body — listing each field that holds *any* query token names exactly where
    the match landed, where an all-tokens-in-one-field test would report an empty
    set for a legitimately matched hit. Returns rowid → matched fields in
    `_FTS_FIELDS` order; a rowid absent from the map matched no single field, which
    cannot happen for a real hit (every token of a match lives in some indexed
    column).
    """
    any_token = " OR ".join(tokens)
    placeholders = ",".join("?" * len(rowids))
    per_rowid: dict[int, set[str]] = {}
    for field in _FTS_FIELDS:
        matched = conn.execute(
            f"SELECT rowid FROM items_fts "
            f"WHERE items_fts MATCH ? AND rowid IN ({placeholders})",
            (f"{field} : ({any_token})", *rowids),
        ).fetchall()
        for (rowid,) in matched:
            per_rowid.setdefault(rowid, set()).add(field)
    return {
        rowid: tuple(f for f in _FTS_FIELDS if f in fields)
        for rowid, fields in per_rowid.items()
    }


def _match_strength(matched_fields: tuple[str, ...]) -> str:
    """The qualitative match confidence: the strength of the strongest field hit.

    A fold over `matched_fields` returning the `_STRENGTH_BY_FIELD` band of the
    highest-weighted field the query landed in — `strong` for a title hit,
    `moderate` for a summary hit, `weak` for a body-only hit — so the one-word
    signal an agent reads is grounded in the BM25 column weights that produced the
    rank, not an invented probability the lexical score can't support. Defaults to
    `weak` only for the structurally-impossible empty case (a real match always
    lands in ≥1 indexed field).
    """
    for field in _FTS_FIELDS:  # BM25-weight order, strongest first
        if field in matched_fields:
            return _STRENGTH_BY_FIELD[field]
    return "weak"


def tally_strength(strengths: Iterable[str]) -> dict[str, int]:
    """Per-band match-strength counts from a stream of `match_strength` values.

    The rank-axis analogue of `custody.tally_custody` (H98): it folds each matched
    hit's own `match_strength` into the `{strong, moderate, weak}` histogram, every
    band present in `STRENGTH_BANDS` order with zeros included, so the shape is
    stable for a renderer to read. The bands partition the matched scope — each hit
    has exactly one `match_strength` — so the counts sum to `stats.matched` by
    construction, the drill-from-strength tie behind `--strength` (H314): the
    `--strength <band>` result count equals the sum of the bands at or above
    `<band>` in this tally (threshold semantics, strongest-first prefix).
    """
    counts = {band: 0 for band in STRENGTH_BANDS}
    for strength in strengths:
        counts[strength] += 1
    return counts
