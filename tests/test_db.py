"""Tests for the SQLite index bootstrap (IDEAS.md §3, §14 Pass 1).

Pass 1 only pins a `meta` table with a schema version so later passes have a
migration anchor; the items/FTS schema arrives with storage (Pass 2/3).
"""

import sqlite3

from scrolls.db import SCHEMA_VERSION, init_db, read_schema_version


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


def test_read_schema_version_missing_db_returns_none(tmp_path):
    assert read_schema_version(tmp_path / "missing.sqlite") is None


def test_read_schema_version_db_without_meta_returns_none(tmp_path):
    db_path = tmp_path / "other.sqlite"
    sqlite3.connect(db_path).close()
    assert read_schema_version(db_path) is None
