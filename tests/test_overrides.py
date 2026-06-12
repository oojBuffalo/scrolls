"""Tests for user classification overrides (IDEAS.md §8 layer three, ADR 0018).

`parse_assignments` turns `field=value` arguments into typed overrides
for exactly the fields the classification engines write; empty values
clear. `apply_overrides` is a plain replace — the CLI owns persistence
and re-rendering.
"""

import pytest

from scrolls.items import ScrollItem
from scrolls.overrides import (
    OVERRIDE_FIELDS,
    OverrideError,
    apply_overrides,
    parse_assignments,
)


def _item(**overrides):
    defaults = {
        "id": "x:1111",
        "source": "x",
        "url": "https://x.com/karpathy/status/1111",
        "saved_at": "2026-06-12T08:00:00+00:00",
    }
    return ScrollItem(**{**defaults, **overrides})


def test_override_fields_are_the_classification_fields():
    assert OVERRIDE_FIELDS == ("category", "domain", "tags", "concepts")


def test_parse_assignments_scalar_fields():
    assert parse_assignments(["category=tool", "domain=databases"]) == {
        "category": "tool",
        "domain": "databases",
    }


def test_parse_assignments_list_fields_split_on_commas():
    parsed = parse_assignments(["tags=sqlite, fts ,sqlite", "concepts=BM25"])
    assert parsed == {"tags": ("sqlite", "fts"), "concepts": ("BM25",)}


def test_parse_assignments_empty_value_clears():
    assert parse_assignments(["category=", "tags="]) == {"category": None, "tags": ()}


def test_parse_assignments_rejects_unknown_field():
    with pytest.raises(OverrideError, match="cannot set 'usefulness'"):
        parse_assignments(["usefulness=high"])


def test_parse_assignments_rejects_missing_equals():
    with pytest.raises(OverrideError, match="field=value"):
        parse_assignments(["category"])


def test_parse_assignments_value_may_contain_equals():
    assert parse_assignments(["domain=a=b"]) == {"domain": "a=b"}


def test_apply_overrides_replaces_only_named_fields():
    item = _item(category="technique", domain="databases", tags=("old",))
    updated = apply_overrides(item, {"category": "tool", "tags": ("sqlite",)})
    assert updated.category == "tool"
    assert updated.tags == ("sqlite",)
    assert updated.domain == "databases"  # untouched
    assert updated.id == item.id
