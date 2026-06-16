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
     scrolls synthesized from (the re-derivation key; the fingerprint's
     determinism is locked in
     `test_kb_llm.py::test_members_hash_is_order_independent_but_content_sensitive`,
     and section 7 below pins the summary engine into this cross-engine contract
     the way sections 1-6 pin the classification engines — recorded method,
     deterministic-in-the-fingerprint re-derivation, honest absence, and a
     freshness view convergent with doctor / `kb --stale`).

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
from scrolls.classify import classification_freshness
from scrolls.classify_llm import ENGINE as LLM_ENGINE
from scrolls.classify_llm import classify_item_llm
from scrolls.items import ScrollItem, classification_provenance
from scrolls.kb import ConceptSummary
from scrolls.kb_llm import ENGINE as KB_LLM_ENGINE
from scrolls.kb_llm import (
    is_stale_summary,
    summary_freshness,
    summary_provenance,
)
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


# --- 6. the confidence marker is honest and convergent (H21) --------------
#
# Every present classification view carries a derived `confidence` marker so an
# agent knows how much to trust a category without consulting doctor: `level`
# (the method's nature) and, where it can be answered, `freshness` (recency vs
# the live ruleset). The marker reports recorded method, never a fabricated
# score, and it reads from the *same* `classification_freshness` primitive
# doctor's aggregate and `classify --stale` use — so the marker an agent sees on
# a hit can never disagree with the count doctor reports (the H25/H27 convergence
# extended to the per-item axis).


@pytest.mark.parametrize(
    "enrich, level",
    [
        (lambda item: classify_item(item), "deterministic"),
        (
            lambda item: classify_item_llm(item, complete=fake_completer(_LLM_PAYLOAD)),
            "inferred",
        ),
    ],
    ids=["rules", "llm"],
)
def test_confidence_level_reports_the_method_nature(enrich, level):
    """A rules match is deterministic (reproducible from signals); an LLM
    category is inferred (a probabilistic judgment to weigh more cautiously)."""
    view = classification_provenance(enrich(make_item()))
    assert view["confidence"]["level"] == level


def test_confidence_freshness_is_exactly_the_doctor_primitive():
    """The marker's freshness is `classification_freshness` verbatim — the same
    derivation doctor's `custody.enrichment` and `classify --stale` read, so the
    per-item marker and the aggregate count converge by construction."""
    for prov in (
        {"classified_by": "rules-v1", "classified_ruleset": RULESET_FINGERPRINT},
        {"classified_by": "rules-v1", "classified_ruleset": "deadbeef0000"},
        {"classified_by": "rules-v1"},
        {"classified_by": "llm-v1", "classified_model": "claude-x"},
    ):
        view = classification_provenance(make_item(category="reference", provenance=prov))
        freshness = classification_freshness(prov)
        if freshness is None:  # LLM — no rules ruleset to compare against
            assert "freshness" not in view["confidence"]
        else:
            assert view["confidence"]["freshness"] == freshness


def test_llm_confidence_claims_no_fabricated_freshness():
    """The anti-fabrication clause on the recency axis: with no ruleset to
    compare and a timestamp barred by the idempotence contract, an LLM category
    claims no freshness rather than a guessed `current`."""
    classified = classify_item_llm(make_item(), complete=fake_completer(_LLM_PAYLOAD))
    confidence = classification_provenance(classified)["confidence"]
    assert confidence == {"level": "inferred"}


# --- 7. the summary axis is provenance-complete and re-derivable too (H29) -
#
# The classification axis above is mirrored on the LLM concept-summary axis: a
# stored summary records its engine + the members fingerprint it was synthesized
# from, its freshness view reads from the one primitive doctor and `kb --stale`
# share, and an unsynthesized concept claims no provenance (honest absence). The
# per-engine generation behavior (eligibility, incremental skip, pruning) is in
# `test_kb_llm.py`; this pins the summary engine into the *cross-engine* contract
# the classification engines obey, so cap 8 holds on both enrichment axes.


def _summary(members_hash, *, engine=KB_LLM_ENGINE):
    return ConceptSummary(
        slug="bm25", display="BM25", summary="How BM25 shows up across these scrolls.",
        members_hash=members_hash, engine=engine, model="claude-test",
        generated_at="2026-06-16T00:00:00+00:00")


def test_summary_records_its_method_and_members_fingerprint():
    """Clause 1 on the summary axis: a stored summary names the engine that wrote
    it and the membership fingerprint it was synthesized from — the re-derivation
    key, the kb_llm counterpart of `classified_by` + `classified_ruleset`."""
    view = summary_provenance(_summary("live-digest"), "live-digest")
    assert view["by"] == KB_LLM_ENGINE
    assert view["members_hash"] == "live-digest"


def test_summary_re_derivation_is_deterministic_in_the_members_fingerprint():
    """Clause 2 on the summary axis: recency is the members fingerprint, not a
    wall-clock timestamp, so an unchanged concept re-derives `current` (a no-op)
    while changed members read `stale` — enrichment regenerates from raw, it does
    not accrete. The fingerprint's determinism is locked in `test_kb_llm.py`."""
    assert summary_provenance(_summary("d"), "d")["freshness"] == "current"
    assert summary_provenance(_summary("old"), "d")["freshness"] == "stale"


def test_unsynthesized_concept_claims_no_summary_provenance():
    """Clause 4 on the summary axis: no stored summary → no provenance claimed
    (honest absence), never a fabricated marker for a synthesis that never ran —
    the `summary_provenance`-returns-None posture, mirroring `classification_view`
    on the classification axis."""
    assert summary_provenance(None, "live-digest") is None


def test_summary_freshness_view_is_exactly_the_doctor_primitive():
    """Clause 6 on the summary axis: the view's freshness is `summary_freshness`
    verbatim — the same derivation doctor's `custody.summaries` aggregate and
    `kb --stale` (`is_stale_summary`) read — so the per-concept marker, the
    aggregate count, and the refresh pool converge by construction, and
    `is_stale_summary` is exactly freshness == 'stale'."""
    cases = [
        (_summary("d"), "d"),                       # current
        (_summary("old"), "d"),                     # members changed → stale
        (_summary("d", engine="kb-llm-v0"), "d"),   # superseded engine → stale
        (None, "d"),                                # never synthesized
    ]
    for stored, live in cases:
        view = summary_provenance(stored, live)
        freshness = summary_freshness(stored, live)
        if view is None:
            assert freshness == "never"  # honest absence, not a present view
        else:
            assert view["freshness"] == freshness
        assert is_stale_summary(stored, live) == (freshness == "stale")
