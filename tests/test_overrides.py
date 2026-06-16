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


# --- a hand-set category carries no engine stamp (IDEAS.md §8, H27) ---------
#
# `classification_view`'s contract is "a user override carries no engine stamp."
# Setting `category` by hand makes that true: the category-derivation stamps the
# classify engines write are dropped, so the override never masquerades as an
# engine result, never shows in the H20 classification view, and never lands in
# doctor's stale-ruleset count or `scrolls classify --stale` (user overrides
# always win — they must stay out of the rules refresh pool).


def _stamped(**overrides):
    provenance = {
        "adapter": "x",
        "fetched_at": "2026-06-12T08:00:00+00:00",
        "classified_by": "rules-v1",
        "classified_basis": "weak-source",
        "classified_ruleset": "deadbeef0000",
    }
    return _item(provenance=provenance, **overrides)


def test_setting_category_drops_the_engine_stamp_but_keeps_fetch_provenance():
    updated = apply_overrides(_stamped(category="media"), {"category": "tool"})
    assert updated.category == "tool"
    # the category-derivation stamps are gone — the category is the user's now
    assert "classified_by" not in updated.provenance
    assert "classified_basis" not in updated.provenance
    assert "classified_ruleset" not in updated.provenance
    # fetch provenance (custody) is untouched
    assert updated.provenance["adapter"] == "x"
    assert updated.provenance["fetched_at"] == "2026-06-12T08:00:00+00:00"


def test_setting_llm_model_stamp_is_also_dropped_on_category_override():
    item = _item(category="paper", provenance={
        "adapter": "x", "classified_by": "llm-v1", "classified_model": "claude"})
    updated = apply_overrides(item, {"category": "tool"})
    assert "classified_model" not in updated.provenance
    assert "classified_by" not in updated.provenance
    assert updated.provenance == {"adapter": "x"}


def test_clearing_category_also_drops_the_engine_stamp():
    # an empty value returns the item to the batch-classifiable pool; the stale
    # stamp would otherwise linger and mislabel it as engine-classified
    updated = apply_overrides(_stamped(category="media"), {"category": None})
    assert updated.category is None
    assert "classified_by" not in updated.provenance
    assert "classified_ruleset" not in updated.provenance


def test_setting_only_other_fields_keeps_the_category_stamp():
    # the stamp records how the *category* was derived; setting domain/tags
    # leaves the category (and its provenance) the engine's
    updated = apply_overrides(_stamped(category="media"), {"domain": "ml"})
    assert updated.provenance["classified_by"] == "rules-v1"
    assert updated.provenance["classified_ruleset"] == "deadbeef0000"
    assert updated.domain == "ml"


def test_setting_category_on_an_unstamped_item_is_safe():
    item = _item(category=None, provenance={"adapter": "x"})
    updated = apply_overrides(item, {"category": "tool"})
    assert updated.category == "tool"
    assert updated.provenance == {"adapter": "x"}


def test_setting_category_when_provenance_was_only_the_stamp_yields_none():
    item = _item(category="media", provenance={"classified_by": "rules-v1"})
    updated = apply_overrides(item, {"category": "tool"})
    assert updated.provenance is None
