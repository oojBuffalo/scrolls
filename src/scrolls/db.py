"""SQLite index bootstrap and migrations (IDEAS.md §3: SQLite as the canonical index).

The `meta` table carries the schema version. `MIGRATIONS[n]` holds the
statements that move a version n-1 database to version n; `init_db` walks
any gap in a single transaction, so fresh and existing libraries both land
on SCHEMA_VERSION. List-valued item fields are stored as JSON text.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 4

_ITEMS_TABLE = """\
CREATE TABLE items (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT,
    url TEXT NOT NULL,
    canonical_url TEXT,
    title TEXT,
    author TEXT,
    published_at TEXT,
    saved_at TEXT NOT NULL,
    raw_text TEXT,
    extracted_text TEXT,
    summary TEXT,
    category TEXT,
    domain TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    concepts TEXT NOT NULL DEFAULT '[]',
    links TEXT NOT NULL DEFAULT '[]',
    media TEXT NOT NULL DEFAULT '[]',
    content_hash TEXT,
    markdown_path TEXT,
    provenance TEXT,
    stage TEXT NOT NULL DEFAULT 'detected'
)
"""

# External-content FTS5 index over items, kept in sync by triggers so no
# Python write path can forget it (IDEAS.md §14 Pass 3). The final INSERT
# backfills rows that predate the index.
_ITEMS_FTS = (
    """\
CREATE VIRTUAL TABLE items_fts USING fts5(
    title, summary, extracted_text,
    content='items', content_rowid='rowid'
)""",
    """\
CREATE TRIGGER items_fts_insert AFTER INSERT ON items BEGIN
    INSERT INTO items_fts(rowid, title, summary, extracted_text)
    VALUES (new.rowid, new.title, new.summary, new.extracted_text);
END""",
    """\
CREATE TRIGGER items_fts_delete AFTER DELETE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, summary, extracted_text)
    VALUES ('delete', old.rowid, old.title, old.summary, old.extracted_text);
END""",
    """\
CREATE TRIGGER items_fts_update AFTER UPDATE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, summary, extracted_text)
    VALUES ('delete', old.rowid, old.title, old.summary, old.extracted_text);
    INSERT INTO items_fts(rowid, title, summary, extracted_text)
    VALUES (new.rowid, new.title, new.summary, new.extracted_text);
END""",
    """\
INSERT INTO items_fts(rowid, title, summary, extracted_text)
SELECT rowid, title, summary, extracted_text FROM items""",
)

# Feed subscriptions for `scrolls follow`/`scrolls sync` (ADR 0017).
# Sync state lives here, not in config.toml (IDEAS.md §3).
_SUBSCRIPTIONS_TABLE = """\
CREATE TABLE subscriptions (
    id TEXT PRIMARY KEY,
    feed_url TEXT NOT NULL UNIQUE,
    title TEXT,
    added_at TEXT NOT NULL,
    last_synced_at TEXT
)
"""

MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (),  # baseline: the meta table itself
    2: (_ITEMS_TABLE,),
    3: _ITEMS_FTS,
    4: (_SUBSCRIPTIONS_TABLE,),
}


def init_db(db_path: Path) -> None:
    """Create the database if needed and migrate it to SCHEMA_VERSION.

    Raises ValueError if the database was written by a newer scrolls than
    this one; refusing beats silently downgrading the stamp.
    """
    conn = sqlite3.connect(db_path)
    try:
        with conn:  # one transaction
            conn.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            current = int(row[0]) if row else 0
            if current > SCHEMA_VERSION:
                raise ValueError(
                    f"database schema version {current} is newer than supported {SCHEMA_VERSION}"
                )
            for version in range(current + 1, SCHEMA_VERSION + 1):
                for statement in MIGRATIONS[version]:
                    conn.execute(statement)
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
    finally:
        conn.close()


def read_schema_version(db_path: Path) -> int | None:
    """Return the stored schema version, or None if the db or stamp is absent."""
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.OperationalError:  # no meta table
        return None
    finally:
        conn.close()
    return int(row[0]) if row else None
