"""Tests for SQLite FTS5 search (IDEAS.md §14 Pass 3)."""

import dataclasses
import sqlite3

import pytest

from scrolls.db import MIGRATIONS, init_db
from scrolls.items import ScrollItem, insert_item, update_item
from scrolls.search import search_items


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "db.sqlite"
    init_db(path)
    return path


def make_item(item_id, title, extracted_text, **overrides):
    base = dict(
        id=item_id,
        source="wikipedia",
        url=f"https://example.org/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00",
        title=title,
        extracted_text=extracted_text,
        summary=extracted_text.split(".")[0],
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def test_search_finds_items_by_content(db_path):
    insert_item(db_path, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine with full-text search support.",
    ))
    insert_item(db_path, make_item(
        "wikipedia:en:Pelican", "Pelican",
        "Pelicans are large water birds with throat pouches.",
    ))

    hits = search_items(db_path, "database engine")
    assert [hit.id for hit in hits] == ["wikipedia:en:SQLite"]
    assert hits[0].title == "SQLite"
    assert hits[0].source == "wikipedia"
    assert hits[0].url == "https://example.org/wikipedia:en:SQLite"
    assert hits[0].stage == "fetched"
    assert isinstance(hits[0].score, float)
    assert "database" in hits[0].snippet


def test_search_ranks_title_matches_for_relevance(db_path):
    insert_item(db_path, make_item(
        "wikipedia:en:BM25", "Okapi BM25",
        "BM25 is a ranking function used by search engines.",
    ))
    insert_item(db_path, make_item(
        "wikipedia:en:Search", "Search engine",
        "A search engine may use ranking functions such as BM25 internally "
        "but this page is mostly about crawling.",
    ))

    hits = search_items(db_path, "BM25 ranking")
    assert hits[0].id == "wikipedia:en:BM25"
    assert len(hits) == 2


def test_search_reflects_updates(db_path):
    item = make_item("wikipedia:en:SQLite", "SQLite", "Original text about databases.")
    insert_item(db_path, item)
    update_item(db_path, dataclasses.replace(
        item,
        extracted_text="Now this page discusses pelicans instead.",
        summary="Now this page discusses pelicans instead",
    ))

    assert search_items(db_path, "pelicans") != []
    assert search_items(db_path, "databases") == []


def test_search_survives_fts_special_syntax(db_path):
    insert_item(db_path, make_item(
        "wikipedia:en:Cpp", "C++",
        "C++ is a programming language.",
    ))
    # none of these may raise an FTS5 syntax error
    assert search_items(db_path, 'C++') != []
    assert search_items(db_path, 'C++ language') != []
    assert search_items(db_path, 'language AND "unbalanced') == []  # no 'unbalanced' token
    assert search_items(db_path, "NEAR(") == []


def test_search_rejects_blank_query(db_path):
    with pytest.raises(ValueError):
        search_items(db_path, '   "" ')


def test_search_missing_db_finds_nothing_but_still_validates(tmp_path):
    missing = tmp_path / "absent.sqlite"
    assert search_items(missing, "anything") == []
    with pytest.raises(ValueError):
        search_items(missing, "   ")
    assert not missing.exists()  # searching never creates a library


def test_search_respects_limit(db_path):
    for index in range(5):
        insert_item(db_path, make_item(
            f"wikipedia:en:Page_{index}", f"Page {index}",
            "Every page mentions databases.",
        ))
    assert len(search_items(db_path, "databases", limit=3)) == 3


def test_migration_backfills_fts_for_existing_rows(tmp_path):
    """A v2 library (items, no FTS) gains a searchable index on upgrade."""
    db_file = tmp_path / "db.sqlite"
    conn = sqlite3.connect(db_file)
    with conn:
        conn.execute(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        for statement in MIGRATIONS[2]:
            conn.execute(statement)
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '2')")
    conn.close()
    insert_item(db_file, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))

    init_db(db_file)  # migrate v2 -> current

    assert [hit.id for hit in search_items(db_file, "database")] == ["wikipedia:en:SQLite"]
