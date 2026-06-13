"""Tests for facet-vocabulary enumeration (ADR 0080)."""

import pytest

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
