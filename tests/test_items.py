"""Tests for the ScrollItem model and SQLite persistence (IDEAS.md §12, §14 Pass 2)."""

import dataclasses

import pytest

from scrolls.db import init_db
from scrolls.items import (
    ScrollItem,
    delete_item,
    get_item,
    insert_item,
    library_counts,
    list_items,
    make_item_id,
    replace_items,
    update_item,
)


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


def test_update_item_replaces_stored_row(db_path):
    insert_item(db_path, make_item())
    fetched = dataclasses.replace(
        make_item(),
        title="A video",
        extracted_text="transcript text",
        content_hash="sha256:abc",
        provenance={"adapter": "youtube", "fetched_at": "2026-06-12T00:00:00+00:00"},
        stage="fetched",
    )
    assert update_item(db_path, fetched) is True
    assert get_item(db_path, fetched.id) == fetched


def test_update_item_returns_false_for_missing_id(db_path):
    assert update_item(db_path, make_item()) is False
    assert get_item(db_path, make_item().id) is None  # no upsert


def test_list_items_filters_by_stage(db_path):
    insert_item(db_path, make_item())
    insert_item(
        db_path,
        make_item(id="web:a", source="web", source_id=None,
                  url="https://a.example", stage="fetched"),
    )
    assert [item.id for item in list_items(db_path, stage="detected")] == ["youtube:abc123"]
    assert [item.id for item in list_items(db_path, stage="fetched")] == ["web:a"]
    assert len(list_items(db_path)) == 2


def test_list_items_filters_by_source_and_category(db_path):
    insert_item(db_path, make_item())  # youtube, unclassified
    insert_item(db_path, make_item(id="web:a", source="web", source_id=None,
                                   url="https://a.example", category="tool"))
    insert_item(db_path, make_item(id="web:b", source="web", source_id=None,
                                   url="https://b.example",
                                   saved_at="2026-06-11T01:00:00+00:00"))

    assert [i.id for i in list_items(db_path, source="web")] == ["web:a", "web:b"]
    assert [i.id for i in list_items(db_path, category="tool")] == ["web:a"]
    # the empty string selects the unclassified (batch-classifiable) pool
    assert [i.id for i in list_items(db_path, category="")] == ["youtube:abc123", "web:b"]
    # filters combine with AND
    assert [i.id for i in list_items(db_path, source="web", category="")] == ["web:b"]


def test_list_items_filters_by_tag(db_path):
    insert_item(db_path, make_item(id="web:a", source="web", source_id=None,
                                   url="https://a.example", tags=("Python", "SQLite")))
    insert_item(db_path, make_item(id="web:b", source="web", source_id=None,
                                   url="https://b.example", tags=("rust",)))

    # tag membership is case-insensitive, mirroring `scrolls related`
    assert [i.id for i in list_items(db_path, tag="python")] == ["web:a"]
    assert [i.id for i in list_items(db_path, tag="RUST")] == ["web:b"]
    # an item without the tag is excluded; no match returns []
    assert list_items(db_path, tag="go") == []


def test_list_items_filters_by_concept(db_path):
    insert_item(db_path, make_item(id="web:a", source="web", source_id=None,
                                   url="https://a.example",
                                   concepts=("Full-text search", "BM25")))
    insert_item(db_path, make_item(id="web:b", source="web", source_id=None,
                                   url="https://b.example", concepts=("Birds",)))

    # concept membership is by slug, so spelling/case/punctuation vary freely
    assert [i.id for i in list_items(db_path, concept="full text search")] == ["web:a"]
    assert [i.id for i in list_items(db_path, concept="bm25")] == ["web:a"]


def test_list_items_tag_and_concept_combine_with_other_filters(db_path):
    insert_item(db_path, make_item(id="web:a", source="web", source_id=None,
                                   url="https://a.example", category="tool",
                                   tags=("python",), concepts=("Search",)))
    insert_item(db_path, make_item(id="arxiv:1", source="arxiv", source_id="1",
                                   url="https://x.example",
                                   tags=("python",), concepts=("Search",)))

    assert [i.id for i in list_items(
        db_path, source="web", tag="python", concept="search"
    )] == ["web:a"]


def test_list_items_filters_by_fidelity_tier(db_path):
    # the holdings-axis filter (ADR 0097): selects items by derived custody tier,
    # folding the same `fidelity_tier`/`get_fidelity` primitive `facets fidelity`
    # counts with. `full` (re-derivable body at a captured stage), `partial`
    # (some content, not re-derivable), `reference` (pointer only).
    insert_item(db_path, make_item(id="web:full", source="web", source_id=None,
                                   url="https://full.example",
                                   raw_text="held in full", stage="fetched"))
    insert_item(db_path, make_item(id="web:partial", source="web", source_id=None,
                                   url="https://partial.example",
                                   extracted_text="some content", stage="fetched"))
    insert_item(db_path, make_item(id="web:ref", source="web", source_id=None,
                                   url="https://ref.example", stage="detected"))

    assert [i.id for i in list_items(db_path, fidelity="full")] == ["web:full"]
    assert [i.id for i in list_items(db_path, fidelity="partial")] == ["web:partial"]
    assert [i.id for i in list_items(db_path, fidelity="reference")] == ["web:ref"]
    # composes (ANDs) with the SQL facets — same as every other filter
    assert [i.id for i in list_items(db_path, source="web", fidelity="reference")] == [
        "web:ref"
    ]


def test_list_items_rejects_an_unknown_fidelity_tier(db_path):
    # a closed vocabulary (like the drift postures), never a silent empty
    with pytest.raises(ValueError):
        list_items(db_path, fidelity="ful")


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


def test_replace_items_swaps_rows_atomically(db_path):
    insert_item(db_path, make_item(id="web:junk", source="web", source_id=None,
                                   url="https://example.com/post?utm_source=x"))
    insert_item(db_path, make_item(id="web:clean", source="web", source_id=None,
                                   url="https://example.com/post"))
    merged = make_item(id="web:clean", source="web", source_id=None,
                       url="https://example.com/post", title="Merged")

    replace_items(db_path, ["web:junk", "web:clean"], merged)

    assert [item.id for item in list_items(db_path)] == ["web:clean"]
    assert get_item(db_path, "web:clean").title == "Merged"
    assert get_item(db_path, "web:junk") is None


def test_replace_items_may_reuse_a_removed_id(db_path):
    insert_item(db_path, make_item(id="web:only", source="web", source_id=None,
                                   url="https://example.com/post"))
    merged = make_item(id="web:only", source="web", source_id=None,
                       url="https://example.com/post", title="Rewritten")
    replace_items(db_path, ["web:only"], merged)
    assert get_item(db_path, "web:only").title == "Rewritten"


def test_delete_item_removes_the_row(db_path):
    insert_item(db_path, make_item())
    assert delete_item(db_path, "youtube:abc123") is True
    assert get_item(db_path, "youtube:abc123") is None


def test_delete_item_reports_absent_id(db_path):
    assert delete_item(db_path, "youtube:nope") is False


def test_library_counts_summarizes_items(db_path):
    insert_item(db_path, make_item())  # youtube, detected, unclassified
    insert_item(db_path, make_item(id="web:a", source="web", source_id=None,
                                   url="https://a.example", stage="fetched",
                                   category="tool"))
    assert library_counts(db_path) == {
        "total": 2,
        "by_stage": {"detected": 1, "fetched": 1, "rendered": 0},
        "by_source": {"web": 1, "youtube": 1},
        "unclassified": 1,
    }


def test_library_counts_scopes_to_one_source(db_path):
    # roadmap H166: `source` narrows every count to one source's items, so
    # `scrolls status --source <S>` reports a genuinely one-source payload.
    insert_item(db_path, make_item())  # youtube, detected, unclassified
    insert_item(db_path, make_item(id="web:a", source="web", source_id=None,
                                   url="https://a.example", stage="fetched",
                                   category="tool"))
    insert_item(db_path, make_item(id="web:b", source="web", source_id=None,
                                   url="https://b.example", stage="rendered"))
    assert library_counts(db_path, source="web") == {
        "total": 2,
        "by_stage": {"detected": 0, "fetched": 1, "rendered": 1},
        "by_source": {"web": 2},  # both web items, singleton key (youtube excluded)
        "unclassified": 1,  # only web:b carries no category (web:a is "tool")
    }
    # an unknown source holds nothing → the honest empty counts, never a crash
    assert library_counts(db_path, source="ghost") == {
        "total": 0,
        "by_stage": {"detected": 0, "fetched": 0, "rendered": 0},
        "by_source": {},
        "unclassified": 0,
    }
