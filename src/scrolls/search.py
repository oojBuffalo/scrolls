"""Full-text search over the items index (IDEAS.md §14 Pass 3).

FTS5 BM25 ranking with the title weighted above the summary, and the
summary above the body, so items *about* a topic beat items that merely
mention it. User queries are quoted token-by-token (implicit AND) instead
of being passed as raw FTS5 syntax: agents send arbitrary strings, and
robustness beats phrase/NEAR operators for now.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

_BM25_WEIGHTS = "5.0, 2.0, 1.0"  # title, summary, extracted_text
_SNIPPET_TOKENS = 12

_QUERY = f"""\
SELECT items.id, items.source, items.title, items.url, items.stage,
       bm25(items_fts, {_BM25_WEIGHTS}) AS score,
       snippet(items_fts, -1, '[', ']', '…', {_SNIPPET_TOKENS}) AS snippet
FROM items_fts
JOIN items ON items.rowid = items_fts.rowid
WHERE items_fts MATCH ?
ORDER BY bm25(items_fts, {_BM25_WEIGHTS})
LIMIT ?
"""


@dataclass(frozen=True)
class SearchHit:
    id: str
    source: str
    title: str | None
    url: str
    stage: str
    score: float
    snippet: str


def search_items(db_path: Path, query: str, limit: int = 20) -> list[SearchHit]:
    """BM25-ranked hits for a free-text query; raises ValueError if it has no tokens.

    A missing database means an empty library: no hits, and the query is
    still validated so callers surface bad input consistently.
    """
    match = _escape_query(query)
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(_QUERY, (match, limit)).fetchall()
    finally:
        conn.close()
    return [SearchHit(*row) for row in rows]


def _escape_query(query: str) -> str:
    """Quote each token so user input is never parsed as FTS5 syntax."""
    tokens = [token.replace('"', "") for token in query.split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        raise ValueError("search query has no searchable tokens")
    return " ".join(f'"{token}"' for token in tokens)
