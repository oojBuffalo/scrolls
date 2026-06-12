"""Tests for the SQLite index bootstrap and migrations (IDEAS.md §3).

v1 pinned the `meta` table with a schema version; v2 adds the `items`
table (Pass 2 storage); v3 the FTS index; v4 the `subscriptions` table
(feed sync, ADR 0017); v5 its HTTP cache validator columns (ADR 0019).
`init_db` must bring both fresh and older databases to SCHEMA_VERSION.
"""

import sqlite3

import pytest

from scrolls.db import MIGRATIONS, SCHEMA_VERSION, init_db, read_schema_version


def _table_columns(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_init_db_creates_file_with_schema_version(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    assert db_path.exists()
    assert read_schema_version(db_path) == SCHEMA_VERSION


def test_init_db_is_idempotent(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    init_db(db_path)
    assert read_schema_version(db_path) == SCHEMA_VERSION


def test_init_db_creates_items_table(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    assert {"id", "source", "source_id", "url", "saved_at", "stage"} <= _table_columns(
        db_path, "items"
    )


def test_init_db_creates_subscriptions_table(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    assert {
        "id",
        "feed_url",
        "title",
        "added_at",
        "last_synced_at",
        "etag",
        "last_modified",
    } <= _table_columns(db_path, "subscriptions")


def test_init_db_migrates_v4_database(tmp_path):
    """A pre-caching library's subscriptions table gains the validator columns."""
    db_path = tmp_path / "db.sqlite"
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        for version in (1, 2, 3, 4):
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
        conn.execute(
            "INSERT INTO subscriptions (id, feed_url, added_at) VALUES ('abc', 'https://e.com/f', '2026-06-12')"
        )
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '4')")
    conn.close()

    init_db(db_path)
    assert read_schema_version(db_path) == SCHEMA_VERSION
    assert {"etag", "last_modified"} <= _table_columns(db_path, "subscriptions")
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT etag, last_modified FROM subscriptions").fetchone()
    conn.close()
    assert row == (None, None)  # existing rows survive with empty validators


def test_init_db_migrates_v3_database(tmp_path):
    """A pre-subscriptions library gains the table without losing anything."""
    db_path = tmp_path / "db.sqlite"
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        for version in (1, 2, 3):
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '3')")
    conn.close()

    init_db(db_path)
    assert read_schema_version(db_path) == SCHEMA_VERSION
    assert "feed_url" in _table_columns(db_path, "subscriptions")
    assert "id" in _table_columns(db_path, "items")


def test_init_db_migrates_v1_database(tmp_path):
    db_path = tmp_path / "db.sqlite"
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '1')")
    conn.close()

    init_db(db_path)
    assert read_schema_version(db_path) == SCHEMA_VERSION
    assert "id" in _table_columns(db_path, "items")


def test_init_db_rejects_newer_schema_version(tmp_path):
    db_path = tmp_path / "db.sqlite"
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION + 1),),
        )
    conn.close()

    with pytest.raises(ValueError, match="newer"):
        init_db(db_path)
    assert read_schema_version(db_path) == SCHEMA_VERSION + 1  # no downgrade


def test_read_schema_version_missing_db_returns_none(tmp_path):
    assert read_schema_version(tmp_path / "missing.sqlite") is None


def test_read_schema_version_db_without_meta_returns_none(tmp_path):
    db_path = tmp_path / "other.sqlite"
    sqlite3.connect(db_path).close()
    assert read_schema_version(db_path) is None
