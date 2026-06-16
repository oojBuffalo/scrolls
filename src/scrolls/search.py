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

Each hit also carries its custody `fidelity` tier (full/partial/reference,
ADR 0097), so a search result tells an agent not just *what* matched but at
what fidelity the library still holds it — the same tier `scrolls list` and
the facets surface, now travelling with ranked hits too. It is derived from
content *presence* read in SQL, never by hauling each match's body text.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from scrolls.items import fidelity_tier, item_filters, register_facet_functions

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
       {", ".join(_PRESENCE)}
FROM items_fts
JOIN items ON items.rowid = items_fts.rowid
WHERE items_fts MATCH ?{{filters}}
ORDER BY bm25(items_fts, {_BM25_WEIGHTS})
LIMIT ?
"""


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


def search_items(
    db_path: Path,
    query: str,
    limit: int = DEFAULT_LIMIT,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
) -> list[SearchHit]:
    """BM25-ranked hits for a free-text query; raises ValueError if it has no tokens.

    `source` and `stage` match exactly; `category` matches exactly too,
    except the empty string, which selects items *without* a category — the
    unclassified pool, mirroring `list_items`/`scrolls set`. `tag` and
    `concept` are membership facets over the JSON array columns (ADR 0059):
    `tag` matches case-insensitively, `concept` by slug, each the way
    `scrolls related` compares them. `None` never filters. Filters AND with
    the full-text match and leave the ranking untouched.

    A missing database means an empty library: no hits, and the query is
    still validated so callers surface bad input consistently.
    """
    match = _escape_query(query)
    if not db_path.exists():
        return []
    clauses, params = item_filters(source, category, stage, tag, concept)
    sql = _QUERY.format(filters="".join(f"\n  AND {clause}" for clause in clauses))
    conn = sqlite3.connect(db_path)
    register_facet_functions(conn)
    try:
        rows = conn.execute(sql, (match, *params, limit)).fetchall()
    finally:
        conn.close()
    return [_hit(row) for row in rows]


def _hit(row: tuple) -> SearchHit:
    """Build a hit from a result row, folding the four presence flags into a tier.

    The query selects the ranked fields (`id`…`snippet`) followed by the four
    `has_*` presence booleans; this collapses those trailing flags into one
    `fidelity` string so the dataclass carries the tier, not the raw columns.
    """
    *ranked, has_raw, has_extracted, has_summary, has_hash = row
    id_, source, title, url, stage, score, snippet = ranked
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
    )


def _escape_query(query: str) -> str:
    """Quote each token so user input is never parsed as FTS5 syntax."""
    tokens = [token.replace('"', "") for token in query.split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        raise ValueError("search query has no searchable tokens")
    return " ".join(f'"{token}"' for token in tokens)
