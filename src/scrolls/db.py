"""SQLite index bootstrap (IDEAS.md §3: SQLite as the canonical index).

Pass 1 pins only a `meta` table carrying the schema version, giving later
passes (items, FTS) a migration anchor without designing their schema yet.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1


def init_db(db_path: Path) -> None:
    """Create the database if needed and stamp the current schema version."""
    conn = sqlite3.connect(db_path)
    try:
        with conn:  # one transaction
            conn.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
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
