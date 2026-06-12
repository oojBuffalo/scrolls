"""Tests for the ScrollItem model and SQLite persistence (IDEAS.md §12, §14 Pass 2)."""

import pytest

from scrolls.db import init_db
from scrolls.items import ScrollItem, get_item, insert_item, list_items, make_item_id


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "db.sqlite"
    init_db(path)
    return path


def make_item(**overrides):
    base = dict(
        id="youtube:abc123",
        source="youtube",
        source_id="abc123",
        url="https://youtu.be/abc123",
        saved_at="2026-06-11T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def test_make_item_id_prefers_source_local_id():
    assert make_item_id("youtube", "abc123", "https://youtu.be/abc123") == "youtube:abc123"


def test_make_item_id_hashes_url_without_source_id():
    item_id = make_item_id("web", None, "https://example.com/post")
    source, digest = item_id.split(":", 1)
    assert source == "web"
    assert len(digest) == 12
    # stable under surrounding whitespace, distinct across URLs
    assert make_item_id("web", None, " https://example.com/post ") == item_id
    assert make_item_id("web", None, "https://example.com/other") != item_id


def test_insert_and_get_round_trips_minimal_item(db_path):
    item = make_item()
    assert insert_item(db_path, item) is True
    assert get_item(db_path, item.id) == item


def test_insert_and_get_round_trips_rich_item(db_path):
    item = make_item(
        id="web:deadbeef0123",
        source="web",
        source_id=None,
        url="https://example.com/post",
        canonical_url="https://example.com/post",
        title="A post",
        author="Someone",
        published_at="2025-01-01T00:00:00+00:00",
        raw_text="raw",
        extracted_text="text",
        summary="sum",
        category="research",
        domain="databases",
        tags=("sqlite", "fts"),
        concepts=("BM25",),
        links=({"url": "https://example.com/ref", "kind": "outbound"},),
        media=({"path": "media/web/img.jpg", "kind": "image"},),
        content_hash="sha256:abc",
        markdown_path="scrolls/web/a-post.md",
        provenance={
            "adapter": "web",
            "fetched_at": "2026-06-11T00:00:00+00:00",
            "extraction_method": "trafilatura",
        },
        stage="synced",
    )
    insert_item(db_path, item)
    assert get_item(db_path, item.id) == item


def test_insert_duplicate_id_keeps_first_and_returns_false(db_path):
    assert insert_item(db_path, make_item(title="first")) is True
    assert insert_item(db_path, make_item(title="second")) is False
    assert get_item(db_path, "youtube:abc123").title == "first"


def test_get_missing_item_returns_none(db_path):
    assert get_item(db_path, "web:missing") is None


def test_list_items_orders_by_saved_at(db_path):
    insert_item(
        db_path,
        make_item(id="web:b", source="web", source_id=None,
                  url="https://b.example", saved_at="2026-06-11T02:00:00+00:00"),
    )
    insert_item(
        db_path,
        make_item(id="web:a", source="web", source_id=None,
                  url="https://a.example", saved_at="2026-06-11T01:00:00+00:00"),
    )
    assert [item.id for item in list_items(db_path)] == ["web:a", "web:b"]
