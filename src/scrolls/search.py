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

Finally, a hit carries the derived `classification` view (roadmap H26): how its
category was produced — the engine, the rules precedence tier, the ruleset
fingerprint, the LLM model — the same view `scrolls list`/`show` surface, so an
agent reads a category's provenance identically whether it browsed to the item
or searched for it. Built per-hit from the row's own `provenance` column
(`classification_view`), so it costs no extra query and stays scope-honest;
omitted entirely when no engine stamped the category (the honest-absence shape
`list` keeps), via the shared `hit_payload` serializer.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from scrolls.custody import FIDELITY_TIERS, drift_posture, last_checked, latest_events
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
SELECT items.id, items.source, items.title, items.url, items.stage,
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


def _search_filters(
    source: str | None,
    category: str | None,
    stage: str | None,
    tag: str | None,
    concept: str | None,
    fidelity: str | None,
) -> tuple[list[str], list[str]]:
    """The shared facet clauses for the ranked query and its count.

    `item_filters` covers the stored-column facets (source/category/stage/tag/
    concept) the ranked query and `facets` share. `fidelity` is the one facet
    that is *derived* (ADR 0097), not a stored column, so it rides the
    `scrolls_fidelity` UDF as a WHERE clause over the content-presence booleans.
    Because it ANDs into the SQL *before* the LIMIT, it scopes the top-k ranked
    selection (the top full-fidelity matches), never a post-cap sieve of them;
    `count_matches` appends the identical clause, so the G2 truncation marker
    counts only the kept tier. An unknown tier is a `ValueError` (a closed
    vocabulary, like `list_items`), raised before any DB access so it never
    depends on library state.
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

    A missing database means an empty library: no hits, and the query is
    still validated so callers surface bad input consistently.
    """
    match = _escape_query(query)
    clauses, params = _search_filters(source, category, stage, tag, concept, fidelity)
    if not db_path.exists():
        return []
    sql = _QUERY.format(filters="".join(f"\n  AND {clause}" for clause in clauses))
    conn = sqlite3.connect(db_path)
    register_facet_functions(conn)
    try:
        rows = conn.execute(sql, (match, *params, limit)).fetchall()
    finally:
        conn.close()
    hits = [_hit(row) for row in rows]
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
        )
        for hit in hits
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
    library (0 matches).
    """
    match = _escape_query(query)
    clauses, params = _search_filters(source, category, stage, tag, concept, fidelity)
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


def _escape_query(query: str) -> str:
    """Quote each token so user input is never parsed as FTS5 syntax."""
    tokens = [token.replace('"', "") for token in query.split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        raise ValueError("search query has no searchable tokens")
    return " ".join(f'"{token}"' for token in tokens)
