"""Tests for the ScrollItem model and SQLite persistence (IDEAS.md §12, §14 Pass 2)."""

import dataclasses

import pytest

from scrolls.db import init_db
from scrolls.items import (
    ArchiveRecord,
    ScrollItem,
    adopt_incoming,
    archive_export_dict,
    archive_from_dict,
    archived_records,
    delete_item,
    get_item,
    import_archive,
    insert_item,
    item_from_dict,
    item_to_dict,
    latest_archived,
    library_counts,
    list_archived,
    list_items,
    make_item_id,
    preview_import_archive,
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


# --- prior-content archive + accept-incoming adoption (ADR 0106) -------------


def test_adopt_incoming_replaces_the_held_copy_and_archives_the_prior(db_path):
    # the one custody-safe overwrite (H278): the held body becomes the incoming
    # one, while the prior capture is archived (recoverable), not destroyed.
    prior = make_item(id="web:a", source="web", source_id=None,
                      url="https://a.example", raw_text="OLD body",
                      content_hash="sha256:old", stage="rendered")
    insert_item(db_path, prior)
    incoming = dataclasses.replace(prior, raw_text="NEW body", content_hash="sha256:new")

    returned = adopt_incoming(db_path, incoming, archived_at="2026-06-22T00:00:00+00:00")

    # the held row now carries the incoming content
    held = get_item(db_path, "web:a")
    assert held.raw_text == "NEW body" and held.content_hash == "sha256:new"
    # the prior is returned (so the caller can record the supersession event)
    assert returned.content_hash == "sha256:old"
    # …and archived, recoverable byte-for-byte
    recovered = latest_archived(db_path, "web:a")
    assert recovered == prior


def test_adopt_incoming_records_an_archive_index_entry(db_path):
    prior = make_item(id="web:a", source="web", source_id=None,
                      url="https://a.example", content_hash="sha256:old",
                      raw_text="x", stage="rendered")
    insert_item(db_path, prior)
    incoming = dataclasses.replace(prior, content_hash="sha256:new", raw_text="y")
    adopt_incoming(db_path, incoming, archived_at="2026-06-22T00:00:00+00:00")

    entries = list_archived(db_path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.item_id == "web:a"
    assert entry.prior_hash == "sha256:old"
    assert entry.superseded_by == "sha256:new"
    assert entry.archived_at == "2026-06-22T00:00:00+00:00"


def test_adopt_incoming_is_a_no_op_for_an_absent_id(db_path):
    # defensive: nothing held to supersede → no archive row, no write, returns None
    incoming = make_item(id="web:ghost", source="web", source_id=None,
                         url="https://ghost.example", content_hash="sha256:x")
    assert adopt_incoming(db_path, incoming,
                          archived_at="2026-06-22T00:00:00+00:00") is None
    assert get_item(db_path, "web:ghost") is None
    assert list_archived(db_path) == []


def test_archive_round_trip_restores_the_prior_capture(db_path):
    # the symmetric recovery the whole design rests on: adopt B over A (A archived),
    # then adopt the archived A back over B — the held copy is A again, B archived.
    a = make_item(id="web:a", source="web", source_id=None, url="https://a.example",
                  raw_text="A body", content_hash="sha256:a", stage="rendered")
    b = dataclasses.replace(a, raw_text="B body", content_hash="sha256:b")
    insert_item(db_path, a)
    adopt_incoming(db_path, b, archived_at="2026-06-22T00:00:00+00:00")
    assert get_item(db_path, "web:a").content_hash == "sha256:b"

    recovered_a = latest_archived(db_path, "web:a")  # the archived prior == A
    adopt_incoming(db_path, recovered_a, archived_at="2026-06-22T01:00:00+00:00")
    assert get_item(db_path, "web:a") == a  # held copy is A again, byte-for-byte
    # both directions retained: two archive rows now (A, then B)
    assert [e.prior_hash for e in list_archived(db_path)] == ["sha256:b", "sha256:a"]


def test_list_archived_filters_by_item_id(db_path):
    for ident in ("web:a", "web:b"):
        prior = make_item(id=ident, source="web", source_id=None,
                          url=f"https://{ident}.example", content_hash="sha256:old",
                          raw_text="x", stage="rendered")
        insert_item(db_path, prior)
        adopt_incoming(db_path, dataclasses.replace(prior, content_hash="sha256:new",
                                                    raw_text="y"),
                       archived_at="2026-06-22T00:00:00+00:00")
    assert {e.item_id for e in list_archived(db_path)} == {"web:a", "web:b"}
    assert [e.item_id for e in list_archived(db_path, item_id="web:a")] == ["web:a"]


def test_latest_archived_returns_none_for_a_never_superseded_id(db_path):
    insert_item(db_path, make_item(id="web:a", source="web", source_id=None,
                                   url="https://a.example", content_hash="sha256:x"))
    assert latest_archived(db_path, "web:a") is None


# --- portable prior-content archive (the recovery store travels, H280) -------


def _archive_a_prior(db_path, item_id, *, old_hash, new_hash, archived_at):
    """Adopt a divergent capture of `item_id`, archiving its prior — test helper."""
    prior = make_item(id=item_id, source="web", source_id=None,
                      url=f"https://{item_id}.example", raw_text="OLD",
                      content_hash=old_hash, stage="rendered")
    insert_item(db_path, prior)
    incoming = dataclasses.replace(prior, raw_text="NEW", content_hash=new_hash)
    adopt_incoming(db_path, incoming, archived_at=archived_at)
    return prior


def test_archived_records_carries_the_model_complete_prior_snapshot(db_path):
    prior = _archive_a_prior(db_path, "web:a", old_hash="sha256:old",
                             new_hash="sha256:new", archived_at="2026-06-22T00:00:00+00:00")
    records = archived_records(db_path)
    assert len(records) == 1
    rec = records[0]
    assert rec.item_id == "web:a"
    assert rec.prior_hash == "sha256:old"
    assert rec.superseded_by == "sha256:new"
    assert rec.archived_at == "2026-06-22T00:00:00+00:00"
    # the snapshot is the model-complete prior, recoverable byte-for-byte
    assert item_from_dict(rec.snapshot) == prior


def test_archived_records_filters_by_item_id_set(db_path):
    _archive_a_prior(db_path, "web:a", old_hash="sha256:oa", new_hash="sha256:na",
                     archived_at="2026-06-22T00:00:00+00:00")
    _archive_a_prior(db_path, "web:b", old_hash="sha256:ob", new_hash="sha256:nb",
                     archived_at="2026-06-22T01:00:00+00:00")
    assert {r.item_id for r in archived_records(db_path)} == {"web:a", "web:b"}
    assert [r.item_id for r in archived_records(db_path, ["web:a"])] == ["web:a"]
    # an empty id set selects nothing (the bundle-empty-scope case)
    assert archived_records(db_path, []) == []


def test_archived_records_orders_content_deterministically(db_path):
    # ordered by (archived_at, item_id, prior_hash), independent of insert/local id —
    # so a re-export after import reproduces the stream regardless of restored ids
    _archive_a_prior(db_path, "web:b", old_hash="sha256:2", new_hash="sha256:n2",
                     archived_at="2026-06-22T02:00:00+00:00")
    _archive_a_prior(db_path, "web:a", old_hash="sha256:1", new_hash="sha256:n1",
                     archived_at="2026-06-22T01:00:00+00:00")
    assert [(r.item_id, r.archived_at) for r in archived_records(db_path)] == [
        ("web:a", "2026-06-22T01:00:00+00:00"),
        ("web:b", "2026-06-22T02:00:00+00:00"),
    ]


def test_archived_records_empty_on_pre_v8_library(tmp_path):
    # tolerates a library with no archive table (the list_archived precedent)
    legacy = tmp_path / "legacy.sqlite"
    import sqlite3
    sqlite3.connect(legacy).close()  # an empty db, no item_archive table
    assert archived_records(legacy) == []


def test_archive_export_round_trips_through_dict(db_path):
    _archive_a_prior(db_path, "web:a", old_hash="sha256:old", new_hash="sha256:new",
                     archived_at="2026-06-22T00:00:00+00:00")
    [rec] = archived_records(db_path)
    assert archive_from_dict(archive_export_dict(rec)) == rec


def test_import_archive_restores_into_a_fresh_library(db_path, tmp_path):
    _archive_a_prior(db_path, "web:a", old_hash="sha256:old", new_hash="sha256:new",
                     archived_at="2026-06-22T00:00:00+00:00")
    records = archived_records(db_path)

    fresh = tmp_path / "fresh.sqlite"
    init_db(fresh)
    imported, skipped = import_archive(fresh, records)
    assert (imported, skipped) == (1, 0)
    # the prior is recoverable on the fresh library, byte-for-byte
    assert archived_records(fresh) == records
    assert latest_archived(fresh, "web:a") == item_from_dict(records[0].snapshot)


def test_import_archive_is_idempotent_deduping_by_item_id_and_prior_hash(db_path, tmp_path):
    _archive_a_prior(db_path, "web:a", old_hash="sha256:old", new_hash="sha256:new",
                     archived_at="2026-06-22T00:00:00+00:00")
    records = archived_records(db_path)
    fresh = tmp_path / "fresh.sqlite"
    init_db(fresh)
    assert import_archive(fresh, records) == (1, 0)
    # a second import of the same recovery store is a no-op (dedup, no second row)
    assert import_archive(fresh, records) == (0, 1)
    assert len(archived_records(fresh)) == 1


def test_import_archive_dedups_within_a_batch_and_null_safe(db_path, tmp_path):
    # two records with a NULL prior_hash for the same item are the same prior —
    # the within-batch dedup uses a NULL-safe identity, not blind append
    rec = ArchiveRecord(item_id="web:a", archived_at="2026-06-22T00:00:00+00:00",
                        prior_hash=None, superseded_by="sha256:new",
                        snapshot=item_to_dict(make_item(id="web:a", source="web",
                                                        source_id=None,
                                                        url="https://a.example")))
    fresh = tmp_path / "fresh.sqlite"
    init_db(fresh)
    imported, skipped = import_archive(fresh, [rec, rec])
    assert (imported, skipped) == (1, 1)


def test_preview_import_archive_matches_a_real_import(db_path, tmp_path):
    # the dry-run twin never drifts from the live restore (the preview_import_events
    # discipline on the archive axis): same (imported, skipped), and it writes nothing
    _archive_a_prior(db_path, "web:a", old_hash="sha256:oa", new_hash="sha256:na",
                     archived_at="2026-06-22T00:00:00+00:00")
    records = archived_records(db_path)
    fresh = tmp_path / "fresh.sqlite"
    init_db(fresh)
    import_archive(fresh, records[:0])  # ensure table exists, nothing in it

    predicted = preview_import_archive(fresh, records)
    assert archived_records(fresh) == []  # preview wrote nothing
    actual = import_archive(fresh, records)
    assert predicted == actual == (1, 0)
    # with the row now present, the preview predicts the skip too
    assert preview_import_archive(fresh, records) == (0, 1)
