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


def test_search_filters_by_source(db_path):
    insert_item(db_path, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine.", source="wikipedia",
    ))
    insert_item(db_path, make_item(
        "arxiv:2401.0001", "A database paper",
        "This paper studies database engines.", source="arxiv",
    ))

    hits = search_items(db_path, "database", source="arxiv")
    assert [hit.id for hit in hits] == ["arxiv:2401.0001"]
    # the unfiltered search still returns both, best-first
    assert {hit.id for hit in search_items(db_path, "database")} == {
        "wikipedia:en:SQLite", "arxiv:2401.0001"
    }


def test_search_filters_by_category(db_path):
    insert_item(db_path, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine.", category="reference",
    ))
    insert_item(db_path, make_item(
        "arxiv:2401.0001", "A database paper",
        "This paper studies database engines.", category="paper",
    ))

    hits = search_items(db_path, "database", category="paper")
    assert [hit.id for hit in hits] == ["arxiv:2401.0001"]


def test_search_empty_category_selects_unclassified(db_path):
    insert_item(db_path, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine.", category="reference",
    ))
    insert_item(db_path, make_item(
        "web:abc", "A database blog post",
        "Some database thoughts.", source="web", category=None,
    ))

    hits = search_items(db_path, "database", category="")
    assert [hit.id for hit in hits] == ["web:abc"]


def test_search_filters_by_stage(db_path):
    insert_item(db_path, make_item(
        "wikipedia:en:SQLite", "SQLite database",
        "SQLite is a database engine.", stage="rendered",
    ))
    insert_item(db_path, make_item(
        "web:abc", "Another database page",
        "More database notes.", source="web", stage="fetched",
    ))

    hits = search_items(db_path, "database", stage="rendered")
    assert [hit.id for hit in hits] == ["wikipedia:en:SQLite"]


def test_search_filters_combine_with_and(db_path):
    insert_item(db_path, make_item(
        "arxiv:2401.0001", "A database paper",
        "This paper studies database engines.",
        source="arxiv", category="paper",
    ))
    insert_item(db_path, make_item(
        "arxiv:2401.0002", "Another database paper",
        "Another database study.",
        source="arxiv", category="reference",
    ))
    insert_item(db_path, make_item(
        "web:abc", "A database blog post",
        "Some database thoughts.", source="web", category="paper",
    ))

    hits = search_items(db_path, "database", source="arxiv", category="paper")
    assert [hit.id for hit in hits] == ["arxiv:2401.0001"]


def test_search_filters_can_exclude_every_hit(db_path):
    insert_item(db_path, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine.", source="wikipedia",
    ))
    assert search_items(db_path, "database", source="arxiv") == []


def test_search_filters_compose_with_limit(db_path):
    for index in range(5):
        insert_item(db_path, make_item(
            f"arxiv:2401.000{index}", f"Paper {index}",
            "Every paper mentions databases.", source="arxiv",
        ))
    insert_item(db_path, make_item(
        "web:abc", "A database blog post",
        "Databases everywhere.", source="web",
    ))
    hits = search_items(db_path, "databases", source="arxiv", limit=3)
    assert len(hits) == 3
    assert all(hit.source == "arxiv" for hit in hits)


def test_search_filters_by_tag(db_path):
    insert_item(db_path, make_item(
        "arxiv:2401.0001", "A database paper",
        "This paper studies database engines.",
        source="arxiv", tags=("cs.DB", "cs.LG"),
    ))
    insert_item(db_path, make_item(
        "arxiv:2401.0002", "Another database paper",
        "Another database study.",
        source="arxiv", tags=("cs.CL",),
    ))
    # tag membership is case-insensitive, mirroring `scrolls related`
    hits = search_items(db_path, "database", tag="CS.db")
    assert [hit.id for hit in hits] == ["arxiv:2401.0001"]


def test_search_filters_by_concept(db_path):
    insert_item(db_path, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine.",
        concepts=("Full-text search", "Embedded databases"),
    ))
    insert_item(db_path, make_item(
        "wikipedia:en:Pelican", "Pelican database",
        "A database of birds.",
        concepts=("Birds",),
    ))
    # concept membership is by slug, so spelling/case/punctuation vary freely
    hits = search_items(db_path, "database", concept="full text search")
    assert [hit.id for hit in hits] == ["wikipedia:en:SQLite"]


def test_search_tag_and_concept_combine_with_other_facets(db_path):
    insert_item(db_path, make_item(
        "arxiv:2401.0001", "A database paper",
        "This paper studies database engines.",
        source="arxiv", category="paper",
        tags=("cs.DB",), concepts=("Full-text search",),
    ))
    insert_item(db_path, make_item(
        "arxiv:2401.0002", "Another database paper",
        "Another database study.",
        source="arxiv", category="paper",
        tags=("cs.DB",), concepts=("Birds",),
    ))
    hits = search_items(
        db_path, "database",
        source="arxiv", category="paper", tag="cs.db", concept="full-text-search",
    )
    assert [hit.id for hit in hits] == ["arxiv:2401.0001"]


def test_search_tag_filter_excludes_items_without_the_tag(db_path):
    insert_item(db_path, make_item(
        "web:abc", "A database blog post",
        "Some database thoughts.", source="web",  # no tags
    ))
    assert search_items(db_path, "database", tag="python") == []


def test_search_blank_query_still_rejected_with_filters(db_path):
    with pytest.raises(ValueError):
        search_items(db_path, "   ", source="arxiv")


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
