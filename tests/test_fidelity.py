"""Tests for custody-fidelity tiers (ADR 0097).

`get_fidelity` derives, from stored ScrollItem fields alone, the tier at which
the library still holds an item — ``full`` (re-derivable body), ``partial``
(degraded but honest), or ``reference`` (pointer only). The `fidelity` facet
counts the library by that tier so "how much do I hold in full?" is one query.
Both are network-free and deterministic.
"""

import pytest

from scrolls.db import init_db
from scrolls.doctor import get_fidelity
from scrolls.facets import compute_facets
from scrolls.items import ScrollItem, fidelity_tier, insert_item, item_summary

NOW = "2026-06-15T00:00:00+00:00"


def _item(item_id, **overrides):
    base = dict(id=item_id, source="web", url=f"https://ex.com/{item_id}", saved_at=NOW)
    base.update(overrides)
    return ScrollItem(**base)


# --- tier derivation ---


def test_raw_text_at_fetched_stage_is_full():
    item = _item("raw", raw_text="the whole body", stage="fetched")
    assert get_fidelity(item) == "full"


def test_extracted_plus_hash_is_full():
    # a re-derivable body with a fingerprint a future re-fetch can diff
    item = _item("hashed", extracted_text="body", content_hash="sha256:abc",
                 stage="rendered")
    assert get_fidelity(item) == "full"


def test_body_held_but_still_at_detected_stage_is_partial():
    # content is present but the pipeline hasn't promoted it past detection;
    # we won't claim full custody of an item we haven't finished capturing
    item = _item("early", raw_text="body", stage="detected")
    assert get_fidelity(item) == "partial"


def test_extracted_without_hash_is_partial():
    item = _item("nohash", extracted_text="body", stage="fetched")
    assert get_fidelity(item) == "partial"


def test_summary_only_is_partial():
    item = _item("summ", summary="a short summary", stage="fetched")
    assert get_fidelity(item) == "partial"


def test_pointer_only_is_reference():
    item = _item("ref", stage="detected")
    assert get_fidelity(item) == "reference"


def test_a_lone_hash_with_no_body_is_not_full():
    # a fingerprint without the content it fingerprints is not a held body
    item = _item("orphan", content_hash="sha256:abc", stage="fetched")
    assert get_fidelity(item) == "reference"


# --- the presence-flag primitive (what search/facets derive the tier from) ---


def test_fidelity_tier_agrees_with_get_fidelity_over_every_shape():
    # `fidelity_tier` is the rule expressed over presence booleans; deriving it
    # from an item's flags must yield exactly what `get_fidelity` reads off the
    # item, for every combination of presence and stage.
    bodies = [
        dict(),
        dict(raw_text="b"),
        dict(extracted_text="b"),
        dict(extracted_text="b", content_hash="sha256:x"),
        dict(summary="s"),
        dict(content_hash="sha256:x"),
    ]
    for stage in ("detected", "fetched", "rendered"):
        for body in bodies:
            item = _item("x", stage=stage, **body)
            assert fidelity_tier(
                has_raw=bool(item.raw_text),
                has_extracted=bool(item.extracted_text),
                has_summary=bool(item.summary),
                has_hash=bool(item.content_hash),
                stage=item.stage,
            ) == get_fidelity(item)


# --- the fidelity facet ---


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "db.sqlite"
    init_db(path)
    return path


def test_facet_counts_each_tier_from_the_right_columns(db_path):
    # the regression that mattered: the facet must read content/stage columns,
    # not the tag/concept columns, or every item collapses to `reference`
    insert_item(db_path, _item("full1", raw_text="b", stage="fetched"))
    insert_item(db_path, _item("full2", extracted_text="b", content_hash="sha256:x",
                               stage="rendered"))
    insert_item(db_path, _item("partial1", extracted_text="b", stage="fetched"))
    insert_item(db_path, _item("ref1", stage="detected"))

    facet = compute_facets(db_path, field="fidelity")["facets"]["fidelity"]
    assert facet == [
        {"value": "full", "count": 2},
        {"value": "partial", "count": 1},
        {"value": "reference", "count": 1},
    ]


def test_facet_scopes_to_the_same_filters_as_search(db_path):
    insert_item(db_path, _item("a", source="arxiv", raw_text="b", stage="fetched"))
    insert_item(db_path, ScrollItem(id="web:b", source="web",
                                    url="https://ex.com/b", saved_at=NOW))

    scoped = compute_facets(db_path, field="fidelity", source="arxiv")
    assert scoped["facets"]["fidelity"] == [{"value": "full", "count": 1}]


def test_facet_is_empty_for_an_uninitialized_library(tmp_path):
    payload = compute_facets(tmp_path / "absent.sqlite", field="fidelity")
    assert payload == {"facets": {"fidelity": []}}


# --- the browse summary (shared by `scrolls list` and MCP list_scrolls) ---


def test_summary_carries_the_browse_fields_plus_fidelity():
    item = _item("s", title="A Title", category="paper",
                 raw_text="body", stage="fetched")
    assert item_summary(item) == {
        "id": "s",
        "source": "web",
        "url": "https://ex.com/s",
        "title": "A Title",
        "category": "paper",
        "stage": "fetched",
        "saved_at": NOW,
        "fidelity": "full",
        "works": [],  # work membership defaults empty when none is passed
    }


def test_summary_reports_a_reference_only_item_honestly():
    assert item_summary(_item("ref", stage="detected"))["fidelity"] == "reference"
