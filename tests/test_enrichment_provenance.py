"""Cap 8 invariant: enrichment is provenance-complete and re-derivable.

The custody vision (`docs/custody-vision.md`, capability 6) and the PRD
(capability 8) require that derived enrichment — classification, concepts, and
the LLM concept summaries — *record its inputs and method and regenerate
deterministically from raw*. "Auditable enrichment stays; un-reproducible
'clever' summarization does not" (vision §3.6). Per-engine behavior is covered
in `test_classify.py`, `test_classify_llm.py`, and `test_kb_llm.py`; this module
is the **cross-engine contract** stated in one place, the way
`test_completeness.py` pins the completeness contract and `test_roundtrip.py`
pins the lossless invariant. It is the measured baseline the confidence/recency
marker (roadmap H21) and any future engine build on.

The contract, across every engine that writes an enriched field:

1. **Method is recorded.** Each engine stamps *how* the field was produced, in
   `provenance`, alongside (never replacing) the capture provenance:
   - rules → ``classified_by = "rules-v1"``
   - llm  → ``classified_by`` + ``classified_model``
   - kb_llm summaries → ``engine`` + a ``members_hash`` fingerprint of the
     scrolls synthesized from (the re-derivation key; locked in
     `test_kb_llm.py::test_members_hash_is_order_independent_but_content_sensitive`
     and the skip-when-unchanged tests — referenced here, not duplicated).

2. **Re-derivation is deterministic.** Re-running the rules engine on the same
   item reproduces the identical enriched item, field-for-field — so a
   re-classify of an unchanged library is a no-op in *result*, and enrichment
   regenerates from raw rather than accreting.

3. **The capture chain is preserved.** Enrichment merges into the existing fetch
   provenance, so ``adapter``/``fetched_at`` survive and the chain capture →
   enrichment stays auditable; the input item is never mutated.

4. **No fabrication.** An item nothing matches gets no category and no method
   stamp — "unclassified" is honest absence, never a guessed label (the
   anti-fabrication half of M2, applied to enrichment).

5. **A user override claims no method.** Setting ``category`` by hand
   (`scrolls set`, IDEAS.md §8 layer three) drops the engine's
   category-derivation stamps, so a hand-set category records no `by`/`basis`/
   `ruleset`/`model` and is never counted re-derivable — provenance never
   claims an engine produced a value the user chose. This is what keeps user
   overrides out of doctor's stale-ruleset count and `classify --stale`
   (roadmap H27): user overrides always win.

The H19-noted gap is closed by roadmap H20: the rules engine now records not
just the engine *version* (``classified_by = "rules-v1"``) but which precedence
tier fired (``classified_basis``) and a fingerprint of the rule tables it ran
under (``classified_ruleset``) — the "inputs + method" a re-classify needs to be
reproducible and auditable. Both are deterministic (per-tier assertions live in
``test_classify.py``); this module pins them as part of the cross-engine "method
is recorded" + "deterministic re-derivation" contract.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from scrolls.classify import ENGINE as RULES_ENGINE
from scrolls.classify import (
    RULESET_FINGERPRINT,
    classify_item,
    is_stale_classification,
)
from scrolls.classify_llm import ENGINE as LLM_ENGINE
from scrolls.classify_llm import classify_item_llm
from scrolls.items import ScrollItem, classification_provenance
from scrolls.overrides import apply_overrides


def make_item(**overrides) -> ScrollItem:
    """A fetched web item with capture provenance, the way an adapter leaves it
    before any enrichment runs."""
    base = dict(
        id="web:3f1a2b3c4d5e",
        source="web",
        source_id=None,
        url="https://blog.example.com/an-intro-tutorial",
        saved_at="2026-06-12T00:00:00+00:00",
        title="A Beginner's Tutorial to SQLite FTS5",
        summary="How BM25 scoring works inside SQLite FTS5.",
        extracted_text="SQLite's FTS5 extension ranks matches with BM25...",
        stage="fetched",
        provenance={"adapter": "web", "fetched_at": "2026-06-12T00:00:00+00:00"},
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_completer(payload: dict):
    """An LLM completer returning a fixed JSON payload (offline)."""

    def complete(system, user, model):
        return json.dumps(payload)

    return complete


_LLM_PAYLOAD = {
    "category": "tutorial",
    "domain": "databases",
    "concepts": ["SQLite", "BM25", "full-text search"],
}


# --- 1. method is recorded (cross-engine) ---------------------------------


def test_rules_engine_records_its_method():
    classified = classify_item(make_item())
    assert classified.category is not None  # a rule fired (title says "Tutorial")
    assert classified.provenance["classified_by"] == RULES_ENGINE


def test_rules_engine_records_the_inputs_and_method_h20():
    """H20: beyond the engine version, the rules engine records which precedence
    tier fired and the ruleset fingerprint — the inputs/method a re-classify
    needs to be reproducible and auditable."""
    classified = classify_item(make_item())  # title rule fires
    assert classified.provenance["classified_basis"] == "title-pattern"
    assert classified.provenance["classified_ruleset"] == RULESET_FINGERPRINT


def test_llm_engine_records_its_method_and_model():
    classified = classify_item_llm(
        make_item(), complete=fake_completer(_LLM_PAYLOAD), model="claude-haiku-4-5"
    )
    assert classified.provenance["classified_by"] == LLM_ENGINE
    assert classified.provenance["classified_model"] == "claude-haiku-4-5"


@pytest.mark.parametrize(
    "enrich",
    [
        lambda item: classify_item(item),
        lambda item: classify_item_llm(item, complete=fake_completer(_LLM_PAYLOAD)),
    ],
    ids=["rules", "llm"],
)
def test_every_engine_that_classifies_stamps_a_method(enrich):
    """The contract that matters for audit: if a field was enriched, the result
    names the engine that produced it. No silent, un-attributed enrichment."""
    enriched = enrich(make_item())
    assert enriched.category is not None
    assert "classified_by" in enriched.provenance


# --- 2. re-derivation is deterministic ------------------------------------


def test_rules_classification_is_deterministically_re_derivable():
    """Re-running the engine on the same input reproduces the identical item,
    field-for-field — enrichment regenerates from raw, it does not accrete. A
    re-classify of an unchanged library is therefore a no-op in result."""
    item = make_item()
    first = classify_item(item)
    second = classify_item(item)
    assert first == second

    # and stable across a round of re-feeding the engine its own output: once a
    # category is set, the same category and the same method marker come back.
    third = classify_item(first)
    assert third.category == first.category
    assert third.provenance["classified_by"] == RULES_ENGINE


def test_re_derivation_does_not_duplicate_the_method_marker():
    """Re-classifying an already-classified item keeps one ``classified_by``,
    not a growing list — the provenance stamp is idempotent."""
    once = classify_item(make_item())
    twice = classify_item(once)
    assert twice.provenance["classified_by"] == RULES_ENGINE
    assert list(twice.provenance).count("classified_by") == 1


# --- 3. the capture chain is preserved ------------------------------------


@pytest.mark.parametrize(
    "enrich",
    [
        lambda item: classify_item(item),
        lambda item: classify_item_llm(item, complete=fake_completer(_LLM_PAYLOAD)),
    ],
    ids=["rules", "llm"],
)
def test_enrichment_preserves_the_capture_provenance(enrich):
    """Enrichment merges into the fetch provenance, never replaces it: the
    capture facts (adapter, fetched_at) survive so the chain capture →
    enrichment stays auditable."""
    item = make_item()
    enriched = enrich(item)
    assert enriched.provenance["adapter"] == "web"
    assert enriched.provenance["fetched_at"] == "2026-06-12T00:00:00+00:00"
    # the input item is never mutated — raw and its provenance are untouched
    assert "classified_by" not in (item.provenance or {})


# --- 4. no fabrication ----------------------------------------------------


def test_unmatched_item_carries_no_label_and_no_method_stamp():
    """An item nothing matches stays unclassified — no guessed category, and no
    ``classified_by`` stamp claiming an engine touched it (anti-fabrication)."""
    # a bare, sourceless-shaped item the rules engine has no signal for
    item = make_item(
        title="", url="https://example.com/", summary=None, extracted_text=None
    )
    result = classify_item(item)
    assert result.category is None
    assert "classified_by" not in (result.provenance or {})
    # honest absence is identity: nothing matched, nothing changed
    assert result == item


# --- 5. a user override claims no method (cross-engine) -------------------


def test_user_override_drops_the_rules_method_stamp():
    """A hand-set category claims no method: the engine's category-derivation
    stamps are dropped, so provenance never says an engine produced the user's
    value, and the derived classification view is honest absence."""
    classified = classify_item(make_item())  # rules-classified, fully stamped
    assert classification_provenance(classified) is not None  # engine method shown
    overridden = apply_overrides(classified, {"category": "reference"})
    assert overridden.category == "reference"
    assert classification_provenance(overridden) is None  # no method is claimed
    # the capture chain still survives the override (clause 3 holds here too)
    assert overridden.provenance["adapter"] == "web"


def test_user_override_drops_the_llm_method_stamp():
    classified = classify_item_llm(
        make_item(), complete=fake_completer(_LLM_PAYLOAD), model="claude-test"
    )
    assert classification_provenance(classified)["by"] == LLM_ENGINE
    overridden = apply_overrides(classified, {"category": "paper"})
    assert classification_provenance(overridden) is None


def test_user_override_is_never_counted_re_derivable_or_stale():
    """The override stamp-drop is what keeps a hand-set category out of doctor's
    stale-ruleset count and `classify --stale` — user overrides always win."""
    # even when the rules classification it replaced was itself stale
    classified = classify_item(make_item())
    stale = replace(
        classified,
        provenance={**classified.provenance, "classified_ruleset": "deadbeef0000"},
    )
    assert is_stale_classification(stale) is True  # would be refreshed ...
    overridden = apply_overrides(stale, {"category": "reference"})
    assert is_stale_classification(overridden) is False  # ... but the override is not
