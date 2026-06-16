"""User classification overrides (IDEAS.md §8 layer three, ADR 0018).

`scrolls set <id> field=value...` is the "user overrides always win"
layer: it writes exactly the fields the classification engines write —
`category`, `domain`, `tags`, `concepts` — and nothing else. Values are
free-form (engines pin vocabularies; the user's word is final), list
fields split on commas, and an empty value clears the field so an item
can return to the batch-classifiable pool. Batch classify never
overwrites an existing category, which is what makes a set value stick.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from scrolls.items import ScrollItem

OVERRIDE_FIELDS = ("category", "domain", "tags", "concepts")
_LIST_FIELDS = ("tags", "concepts")

# Provenance keys the classify engines stamp to record how a *category* was
# derived (`classify.classify_item` / `classify_llm`). A hand-set category is
# the user's, not an engine's, so setting `category` drops these — making
# `items.classification_view`'s contract ("a user override carries no engine
# stamp") true, and keeping the override out of doctor's stale-ruleset count
# and `scrolls classify --stale` (user overrides always win; custody §2.4).
_CATEGORY_STAMP_KEYS = (
    "classified_by",
    "classified_basis",
    "classified_ruleset",
    "classified_model",
)


class OverrideError(ValueError):
    """A field=value assignment cannot be applied."""


def parse_assignments(assignments: list[str]) -> dict[str, Any]:
    """Turn `field=value` arguments into typed override values.

    List fields split on commas (deduplicated, order kept); an empty
    value clears (None for scalars, empty tuple for lists). Raises
    OverrideError for a missing '=' or a field outside OVERRIDE_FIELDS,
    so a typo never half-applies.
    """
    overrides: dict[str, Any] = {}
    for assignment in assignments:
        field, sep, value = assignment.partition("=")
        if not sep:
            raise OverrideError(f"expected field=value, got {assignment!r}")
        if field not in OVERRIDE_FIELDS:
            raise OverrideError(
                f"cannot set {field!r}; settable fields: {', '.join(OVERRIDE_FIELDS)}"
            )
        if field in _LIST_FIELDS:
            overrides[field] = tuple(
                dict.fromkeys(part.strip() for part in value.split(",") if part.strip())
            )
        else:
            overrides[field] = value.strip() or None
    return overrides


def apply_overrides(item: ScrollItem, overrides: dict[str, Any]) -> ScrollItem:
    """The item with the parsed overrides applied; never mutates the input.

    Setting `category` (to a value or clearing it) also drops the
    category-derivation stamps the classify engines wrote
    (`_CATEGORY_STAMP_KEYS`): a hand-set category is the user's, so provenance
    must not keep claiming an engine produced it. Fetch/custody provenance is
    preserved. Setting only domain/tags/concepts leaves the category — and its
    stamp — the engine's.
    """
    fields = dict(overrides)
    if "category" in overrides:
        provenance = {
            key: value
            for key, value in (item.provenance or {}).items()
            if key not in _CATEGORY_STAMP_KEYS
        }
        fields["provenance"] = provenance or None
    return replace(item, **fields)
