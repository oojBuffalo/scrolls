"""Tests for facet-vocabulary enumeration (ADR 0080)."""

import pytest

from scrolls.custody import CustodyEvent, record_events
from scrolls.db import init_db
from scrolls.facets import FIELDS, compute_facets
from scrolls.items import ScrollItem, insert_item


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "db.sqlite"
    init_db(path)
    return path


def make_item(item_id, **overrides):
    base = dict(
        id=item_id,
        source="web",
        url=f"https://example.com/{item_id}",
        saved_at="2026-06-11T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def seed(db_path, items):
    for item in items:
        assert insert_item(db_path, item) is True


def test_missing_db_yields_empty_dimensions(tmp_path):
    payload = compute_facets(tmp_path / "absent.sqlite")
    assert payload == {"facets": {name: [] for name in FIELDS}}


def test_empty_library_yields_empty_dimensions(db_path):
    payload = compute_facets(db_path)
    assert payload == {"facets": {name: [] for name in FIELDS}}


def test_sources_counted_and_ranked_by_count_then_value(db_path):
    seed(
        db_path,
        [
            make_item("arxiv:1", source="arxiv"),
            make_item("arxiv:2", source="arxiv"),
            make_item("web:1", source="web"),
            make_item("github:1", source="github"),
        ],
    )
    sources = compute_facets(db_path, field="sources")["facets"]["sources"]
    assert sources == [
        {"value": "arxiv", "count": 2},
        {"value": "github", "count": 1},
        {"value": "web", "count": 1},
    ]


def test_categories_report_unclassified_pool_as_empty_string(db_path):
    seed(
        db_path,
        [
            make_item("a", category="paper"),
            make_item("b", category="paper"),
            make_item("c", category="tool"),
            make_item("d"),  # category is None -> unclassified
        ],
    )
    categories = compute_facets(db_path, field="categories")["facets"]["categories"]
    assert categories == [
        {"value": "paper", "count": 2},
        {"value": "", "count": 1},
        {"value": "tool", "count": 1},
    ]


def test_tags_merge_case_insensitively_with_smallest_spelling(db_path):
    seed(
        db_path,
        [
            make_item("a", tags=("Rust", "MIT")),
            make_item("b", tags=("rust",)),
            make_item("c", tags=("mit",)),
        ],
    )
    tags = compute_facets(db_path, field="tags")["facets"]["tags"]
    # "Rust"/"rust" merge to one group (smallest spelling "Rust" wins), count 2;
    # "MIT"/"mit" likewise -> "MIT", count 2. Ranked by count then display.
    assert tags == [
        {"value": "MIT", "count": 2},
        {"value": "Rust", "count": 2},
    ]


def test_concepts_merge_by_slug_and_expose_the_slug(db_path):
    seed(
        db_path,
        [
            make_item("a", concepts=("Full Text Search", "SQLite")),
            make_item("b", concepts=("full text search",)),
        ],
    )
    concepts = compute_facets(db_path, field="concepts")["facets"]["concepts"]
    assert concepts == [
        {"value": "Full Text Search", "slug": "full-text-search", "count": 2},
        {"value": "SQLite", "slug": "sqlite", "count": 1},
    ]


def test_repeated_spellings_on_one_item_count_it_once(db_path):
    # "Full Text Search" and "full text search" share a slug; one item carrying
    # both must contribute a single distinct-item count, not two.
    seed(db_path, [make_item("a", concepts=("Full Text Search", "full text search"))])
    concepts = compute_facets(db_path, field="concepts")["facets"]["concepts"]
    assert concepts == [
        {"value": "Full Text Search", "slug": "full-text-search", "count": 1},
    ]


def test_all_dimensions_returned_by_default(db_path):
    seed(db_path, [make_item("a", source="web", category="tool", tags=("x",), concepts=("Y",))])
    payload = compute_facets(db_path)
    assert list(payload["facets"].keys()) == list(FIELDS)
    assert payload["facets"]["sources"] == [{"value": "web", "count": 1}]
    assert payload["facets"]["tags"] == [{"value": "x", "count": 1}]


# --- drift (custody posture from the verify ledger, roadmap H48) -----------


def _event(item_id, status, observed=None):
    return CustodyEvent(
        item_id=item_id, checked_at="2026-06-14T00:00:00+00:00", status=status,
        prior_hash="deadbeef", observed_hash=observed,
    )


def test_drift_counts_by_posture(db_path):
    # the browse aggregate of the verify ledger: each held item by drift posture,
    # with the never-checked ones counted as `unverified`, never silently dropped
    seed(db_path, [make_item(f"web:{index}") for index in range(5)])
    record_events(db_path, [
        _event("web:0", "unchanged", observed="deadbeef"),  # → verified
        _event("web:1", "unchanged", observed="deadbeef"),  # → verified
        _event("web:2", "drifted", observed="cafe1234"),
        _event("web:3", "rotted"),
        # web:4 left unverified
    ])
    drift = compute_facets(db_path, field="drift")["facets"]["drift"]
    assert {entry["value"]: entry["count"] for entry in drift} == {
        "verified": 2, "drifted": 1, "rotted": 1, "unverified": 1,
    }
    # ranked by count desc then value asc, like every other dimension
    assert drift[0] == {"value": "verified", "count": 2}


def test_drift_facet_respects_the_scoping_filters(db_path):
    # the same facets that scope the other dimensions scope `drift` too
    seed(db_path, [
        make_item("arxiv:1", source="arxiv"),
        make_item("web:1", source="web"),
    ])
    record_events(db_path, [_event("arxiv:1", "drifted", observed="cafe1234")])
    scoped = compute_facets(db_path, field="drift", source="arxiv")["facets"]["drift"]
    assert scoped == [{"value": "drifted", "count": 1}]


def test_drift_facet_empty_library_is_well_shaped(db_path):
    assert compute_facets(db_path, field="drift") == {"facets": {"drift": []}}


def test_drift_facet_converges_with_doctor_custody_drift(db_path, tmp_path):
    # `facets drift` and `doctor`'s `custody.drift` read the same ledger via the
    # same primitives, so they agree for the same scope (verified ≡ unchanged)
    from scrolls.doctor import run_doctor
    from scrolls.paths import get_paths

    seed(db_path, [make_item(f"web:{index}") for index in range(4)])
    record_events(db_path, [
        _event("web:0", "unchanged", observed="deadbeef"),
        _event("web:1", "drifted", observed="cafe1234"),
        _event("web:2", "rotted"),
        # web:3 left unverified
    ])
    drift = {
        entry["value"]: entry["count"]
        for entry in compute_facets(db_path, field="drift")["facets"]["drift"]
    }
    doctor = run_doctor(get_paths(tmp_path))["custody"]["drift"]
    assert drift.get("verified", 0) == doctor["unchanged"] == 1
    assert drift.get("drifted", 0) == doctor["drifted"] == 1
    assert drift.get("rotted", 0) == doctor["rotted"] == 1
    assert drift.get("unverified", 0) == doctor["unverified"] == 1


# --- method (how each held category was produced, roadmap H28) -------------


def test_method_counts_by_how_the_category_was_produced(db_path):
    # the aggregate counterpart of the per-item `classification` view (H20/H26):
    # buckets the library by the engine that produced each category, with the
    # honest "user-set" / "unclassified" buckets the per-item view's None covers.
    from scrolls.classify import classify_item

    seed(
        db_path,
        [
            # two rules-classified items (wikipedia → reference, curated-source)
            classify_item(make_item("wiki:1", source="wikipedia", category=None,
                                    title="SQLite")),
            classify_item(make_item("wiki:2", source="wikipedia", category=None,
                                    title="Postgres")),
            # an LLM-classified item carries classified_by=llm-v1
            make_item("web:llm", category="tutorial",
                      provenance={"classified_by": "llm-v1", "classified_model": "claude-x"}),
            # a hand-set category, no engine stamp
            make_item("web:user", category="opinion"),
            # nothing classified it: no category at all
            make_item("web:bare"),
        ],
    )
    method = compute_facets(db_path, field="method")["facets"]["method"]
    assert method == [
        {"value": "rules-v1", "count": 2},
        {"value": "llm-v1", "count": 1},
        {"value": "unclassified", "count": 1},
        {"value": "user-set", "count": 1},
    ]


def test_method_facet_respects_the_scoping_filters(db_path):
    # the same facets that scope the other dimensions scope `method` too
    from scrolls.classify import classify_item

    seed(
        db_path,
        [
            classify_item(make_item("wiki:1", source="wikipedia", category=None,
                                    title="SQLite")),
            make_item("web:user", source="web", category="opinion"),
        ],
    )
    scoped = compute_facets(db_path, field="method", source="wikipedia")["facets"]["method"]
    assert scoped == [{"value": "rules-v1", "count": 1}]


def test_method_facet_empty_library_is_well_shaped(db_path):
    assert compute_facets(db_path, field="method") == {"facets": {"method": []}}


def test_method_facet_is_the_aggregate_of_the_per_item_confidence_level(db_path):
    # H21 carries no new `confidence` facet on purpose: the level axis aggregate
    # *is* `facets method` (and the freshness aggregate is doctor's
    # custody.enrichment). This pins that they agree — both derive from
    # `classification_view`, so the facet's engine buckets are exactly the rollup
    # of each held item's per-item `confidence.level` (rules-v1↔deterministic,
    # llm-v1↔inferred), with user-set/unclassified the view's honest-absence None.
    from collections import Counter

    from scrolls.classify import classify_item
    from scrolls.items import classification_provenance, list_items

    seed(
        db_path,
        [
            classify_item(make_item("wiki:1", source="wikipedia", category=None,
                                    title="SQLite")),
            classify_item(make_item("wiki:2", source="wikipedia", category=None,
                                    title="Postgres")),
            make_item("web:llm", category="tutorial",
                      provenance={"classified_by": "llm-v1", "classified_model": "x"}),
            make_item("web:user", category="opinion"),
            make_item("web:bare"),
        ],
    )
    level_for_engine = {"rules-v1": "deterministic", "llm-v1": "inferred"}

    # roll up each held item's own per-item confidence level (or absence)
    rolled = Counter()
    for item in list_items(db_path):
        view = classification_provenance(item)
        if view is None:
            rolled["user-set" if item.category is not None else "unclassified"] += 1
        else:
            rolled[view["by"]] += 1
            # the level the per-item marker reports matches the engine bucket
            assert view["confidence"]["level"] == level_for_engine[view["by"]]

    method = compute_facets(db_path, field="method")["facets"]["method"]
    assert {entry["value"]: entry["count"] for entry in method} == dict(rolled)


def test_scoping_filter_restricts_the_vocabulary(db_path):
    seed(
        db_path,
        [
            make_item("arxiv:1", source="arxiv", concepts=("Machine Learning",)),
            make_item("web:1", source="web", concepts=("Cooking",)),
        ],
    )
    concepts = compute_facets(db_path, field="concepts", source="arxiv")["facets"][
        "concepts"
    ]
    assert concepts == [
        {"value": "Machine Learning", "slug": "machine-learning", "count": 1},
    ]


def test_scoping_by_unclassified_category(db_path):
    seed(
        db_path,
        [
            make_item("a", category="tool", tags=("classified",)),
            make_item("b", tags=("loose",)),
        ],
    )
    tags = compute_facets(db_path, field="tags", category="")["facets"]["tags"]
    assert tags == [{"value": "loose", "count": 1}]


def test_limit_caps_each_dimension(db_path):
    seed(
        db_path,
        [make_item(f"t{i}", tags=(f"tag{i}",)) for i in range(5)],
    )
    tags = compute_facets(db_path, field="tags", limit=2)["facets"]["tags"]
    assert len(tags) == 2


def test_unknown_field_is_rejected(db_path):
    with pytest.raises(ValueError):
        compute_facets(db_path, field="bogus")
