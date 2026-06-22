"""Tests for shareable custody bundles (ADR 0103, MVP M4)."""

import dataclasses
import json

import pytest

from scrolls.bundle import (
    BundleError,
    build_bundle,
    build_bundle_html,
    parse_bundle,
    parse_bundle_events,
)
from scrolls.classify import ENGINE as RULES_ENGINE
from scrolls.classify import RULESET_FINGERPRINT
from scrolls.classify_llm import ENGINE as LLM_ENGINE
from scrolls.cli import main
from scrolls.custody import (
    CustodyEvent,
    custody_headline,
    item_events,
    item_history,
    record_events,
)
from scrolls.doctor import run_doctor
from scrolls.items import ScrollItem, get_item, insert_item, item_to_dict
from scrolls.kb import ConceptSummary, save_concept_summary
from scrolls.kb_llm import ENGINE as SUMMARY_ENGINE
from scrolls.kb_llm import members_hash
from scrolls.paths import get_paths


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


def make_item(item_id, title, extracted_text, **overrides):
    base = dict(
        id=item_id,
        source="wikipedia",
        url=f"https://example.org/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00",
        title=title,
        raw_text=f"<raw>{extracted_text}</raw>",
        extracted_text=extracted_text,
        summary=extracted_text.split(".")[0] + ".",
        content_hash="deadbeef",
        provenance={"fetched_at": "2026-06-12T00:00:00+00:00", "via": "test"},
        markdown_path=f"scrolls/wikipedia/{item_id}.md",
        stage="rendered",
    )
    base.update(overrides)
    return ScrollItem(**base)


# --- build / parse round-trip (in memory) ----------------------------------


def test_bundle_has_a_briefing_and_a_custody_block(scrolls_home):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine with full-text search support.",
    ))

    bundle = build_bundle(db, "database engine")
    # the readable briefing names the scroll and its custody facts
    assert bundle.startswith("# Scrolls Custody Bundle: database engine\n")
    assert "## 1. SQLite (`wikipedia:en:SQLite`)" in bundle
    assert "fidelity `full`" in bundle  # raw_text + hash + rendered → full tier
    assert "captured 2026-06-12T00:00:00+00:00" in bundle
    # the self-describing fenced custody block travels alongside
    assert "@generated scrolls" in bundle
    assert "```jsonl" in bundle
    assert "@end scrolls" in bundle


def test_parse_bundle_recovers_the_items(scrolls_home):
    main(["init"])
    db = get_paths().db_path
    original = make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine.",
    )
    insert_item(db, original)

    items = parse_bundle(build_bundle(db, "database engine"))
    assert [i.id for i in items] == ["wikipedia:en:SQLite"]
    # the recovered item is byte-for-byte the original (the lossless core)
    assert item_to_dict(items[0]) == item_to_dict(original)


def test_bundle_carries_the_raw_body_even_when_the_excerpt_is_capped(scrolls_home):
    # self-describing offline: the briefing excerpt is capped, but the custody
    # block still holds the full raw_text, so a re-import loses nothing
    main(["init"])
    db = get_paths().db_path
    long_body = "database " * 400  # ~3600 chars
    insert_item(db, make_item(
        "wikipedia:en:Long", "Long", long_body.strip(),
        raw_text=long_body.strip(), summary=None,
    ))

    bundle = build_bundle(db, "database")
    briefing, _, _block = bundle.partition("@generated scrolls")
    assert "…" in briefing  # the readable excerpt is capped
    recovered = parse_bundle(bundle)[0]
    assert recovered.raw_text == long_body.strip()  # the block is complete


# --- enrichment provenance travels in the readable briefing (roadmap H35) ---


def _rules_provenance(basis="documentation-url", ruleset=RULESET_FINGERPRINT):
    return {
        "fetched_at": "2026-06-12T00:00:00+00:00",
        "via": "test",
        "classified_by": RULES_ENGINE,
        "classified_basis": basis,
        "classified_ruleset": ruleset,
    }


def test_briefing_carries_the_classification_view_for_a_rules_category(scrolls_home):
    # how the category was derived reads in the briefing, not just the JSONL
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
        category="documentation", provenance=_rules_provenance(),
    ))

    bundle = build_bundle(db, "database engine")
    assert "classified `documentation` by `rules-v1` (documentation-url)" in bundle
    # the rules engine is reproducible from signals and current vs the live ruleset
    assert "confidence deterministic, current" in bundle


def test_briefing_classification_view_for_the_llm_engine_omits_freshness(scrolls_home):
    # the LLM engine is inferred and claims no ruleset freshness — honest absence
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "arxiv:2401.0001", "Paper", "A database paper.",
        source="arxiv", url="https://arxiv.org/abs/2401.0001", category="research",
        provenance={
            "fetched_at": "2026-06-12T00:00:00+00:00", "via": "test",
            "classified_by": LLM_ENGINE, "classified_model": "claude-test",
        },
    ))

    bundle = build_bundle(db, "database")
    assert "classified `research` by `llm-v1` (model claude-test)" in bundle
    assert "confidence inferred" in bundle
    assert "confidence inferred," not in bundle  # no freshness appended for the LLM


def test_briefing_omits_classification_when_no_engine_stamped_it(scrolls_home):
    # an unclassified item and a user-set category both carry no engine method
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))
    insert_item(db, make_item(
        "wikipedia:en:Postgres", "Postgres", "Postgres is a database.",
        category="favorites",  # user-set: no classified_by stamp
    ))

    briefing, _, _block = build_bundle(db, "database").partition("@generated scrolls")
    assert "classified" not in briefing  # honest absence, no method fabricated


def test_classification_provenance_still_round_trips_in_the_block(scrolls_home):
    # adding the readable line leaves the lossless custody block untouched
    main(["init"])
    db = get_paths().db_path
    original = make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database.",
        category="documentation", provenance=_rules_provenance(),
    )
    insert_item(db, original)

    recovered = parse_bundle(build_bundle(db, "database"))[0]
    assert item_to_dict(recovered) == item_to_dict(original)


def test_concept_scoped_bundle_carries_summary_provenance(scrolls_home):
    # a concept-scoped bundle is *about* the concept, so its synthesized summary
    # and how that summary was derived belong in the briefing
    main(["init"])
    db = get_paths().db_path
    members = [
        make_item("wikipedia:en:SQLite", "SQLite", "SQLite is a database.",
                  concepts=("Databases",)),
        make_item("wikipedia:en:Postgres", "Postgres", "Postgres is a database.",
                  concepts=("Databases",)),
    ]
    for member in members:
        insert_item(db, member)
    save_concept_summary(db, ConceptSummary(
        slug="databases", display="Databases",
        summary="Databases store and query structured data.",
        members_hash=members_hash(members), engine=SUMMARY_ENGINE,
        model="claude-test", generated_at="2026-06-12T00:00:00+00:00",
    ))

    bundle = build_bundle(db, "database", concept="Databases")
    assert "**Concept summary** — Databases store and query structured data." in bundle
    assert f"Summary by `{SUMMARY_ENGINE}`, current" in bundle


def test_concept_scoped_bundle_without_a_summary_omits_the_block(scrolls_home):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database.",
        concepts=("Databases",),
    ))

    bundle = build_bundle(db, "database", concept="Databases")
    assert "Concept summary" not in bundle  # honest absence, none synthesized


def test_concept_summary_provenance_is_stale_when_members_changed(scrolls_home):
    # the freshness is computed against the concept's live members, so a summary
    # stored under an outdated fingerprint reads stale (regenerable)
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite",
                              "SQLite is a database.", concepts=("Databases",)))
    insert_item(db, make_item("wikipedia:en:Postgres", "Postgres",
                              "Postgres is a database.", concepts=("Databases",)))
    save_concept_summary(db, ConceptSummary(
        slug="databases", display="Databases", summary="Old synthesis.",
        members_hash="stalefingerprint", engine=SUMMARY_ENGINE,
        model="claude-test", generated_at="2026-06-12T00:00:00+00:00",
    ))

    bundle = build_bundle(db, "database", concept="Databases")
    assert f"Summary by `{SUMMARY_ENGINE}`, stale" in bundle


# --- per-scroll drift posture in the briefing (roadmap H42) -----------------


def _event(item_id, status, prior="deadbeef", observed=None):
    return CustodyEvent(
        item_id=item_id, checked_at="2026-06-14T00:00:00+00:00", status=status,
        prior_hash=prior, observed_hash=observed,
    )


def test_briefing_carries_per_scroll_drift_posture(scrolls_home):
    # the verify-ledger verdict an agent reading a shared briefing most needs
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:Fresh", "Fresh", "A fresh database."))
    insert_item(db, make_item("wikipedia:en:Moved", "Moved", "A moved database."))
    insert_item(db, make_item("wikipedia:en:Never", "Never", "A never-checked database."))
    record_events(db, [
        _event("wikipedia:en:Fresh", "unchanged", observed="deadbeef"),
        _event("wikipedia:en:Moved", "drifted", observed="cafe1234"),
    ])

    bundle = build_bundle(db, "database")
    assert "custody `verified`" in bundle
    assert "as of 2026-06-14T00:00:00+00:00" in bundle
    assert "custody `drifted`" in bundle
    # the never-checked scroll is unverified, never silently "clean"
    assert "custody `unverified`" in bundle


def test_bundle_drift_posture_converges_with_the_doctor_aggregate(scrolls_home):
    # the per-scroll posture reads from the same ledger doctor aggregates, so the
    # postures in a whole-scope bundle must total doctor's custody.drift counts
    main(["init"])
    db = get_paths().db_path
    for index in range(5):
        insert_item(db, make_item(
            f"wikipedia:en:Page_{index}", f"Page {index}", "Every page is a database.",
        ))
    record_events(db, [
        _event("wikipedia:en:Page_0", "unchanged", observed="deadbeef"),
        _event("wikipedia:en:Page_1", "unchanged", observed="deadbeef"),
        _event("wikipedia:en:Page_2", "drifted", observed="cafe1234"),
        _event("wikipedia:en:Page_3", "rotted"),
        # Page_4 left unverified
    ])

    bundle = build_bundle(db, "database")
    drift = run_doctor(get_paths())["custody"]["drift"]
    assert bundle.count("custody `verified`") == drift["unchanged"] == 2
    assert bundle.count("custody `drifted`") == drift["drifted"] == 1
    assert bundle.count("custody `rotted`") == drift["rotted"] == 1
    assert bundle.count("custody `unverified`") == drift["unverified"] == 1


def test_bundle_carries_a_scope_custody_headline(scrolls_home):
    # the scope-level "how custody stands" line under the title (roadmap H45):
    # N scrolls, fidelity tier counts, drift posture counts
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:Full", "Full", "A full database."))
    insert_item(db, make_item("wikipedia:en:Moved", "Moved", "A moved database."))
    # a reference-only scroll (no body held) so a second fidelity tier appears;
    # "database" rides in the title so it is still in the query scope
    insert_item(db, make_item(
        "wikipedia:en:Ref", "Reference database pointer", "",
        raw_text=None, summary=None,
        content_hash=None, markdown_path=None, stage="detected",
    ))
    record_events(db, [_event("wikipedia:en:Moved", "drifted", observed="cafe1234")])

    bundle = build_bundle(db, "database")
    headline = next(
        line for line in bundle.splitlines() if line.startswith("_Custody:")
    )
    assert "3 scroll(s)" in headline
    # two full-fidelity bodies + one reference-only pointer
    assert "fidelity full 2, reference 1" in headline
    # one drifted, the other two never re-checked (fixed posture order)
    assert "drift unverified 2, drifted 1" in headline


def test_scope_custody_headline_totals_equal_the_entries_and_doctor(scrolls_home):
    # the headline counts converge with both the per-scroll entries and doctor's
    # custody aggregate for the same (whole-library) scope — H42 at scope level
    from scrolls.custody import custody_counts, latest_events
    from scrolls.items import get_fidelity, list_items

    main(["init"])
    db = get_paths().db_path
    for index in range(4):
        insert_item(db, make_item(
            f"wikipedia:en:Page_{index}", f"Page {index}", "Every page is a database.",
        ))
    record_events(db, [
        _event("wikipedia:en:Page_0", "unchanged", observed="deadbeef"),
        _event("wikipedia:en:Page_1", "drifted", observed="cafe1234"),
        _event("wikipedia:en:Page_2", "rotted"),
        # Page_3 left unverified
    ])

    items = list_items(db)
    counts = custody_counts(items, latest_events(db))
    # headline totals equal the entries by construction
    assert sum(counts["tiers"].values()) == len(items) == 4
    assert sum(counts["drift"].values()) == len(items) == 4
    # the fidelity-tier count equals the per-scroll `fidelity` lines in the body
    assert all(get_fidelity(item) == "full" for item in items)
    bundle = build_bundle(db, "database")
    assert counts["tiers"]["full"] == bundle.count("fidelity `full`") == 4

    # and equal doctor's custody aggregate for the whole-library scope
    custody = run_doctor(get_paths())["custody"]
    assert counts["tiers"] == custody["tiers"]
    drift = custody["drift"]
    assert counts["drift"]["verified"] == drift["unchanged"] == 1
    assert counts["drift"]["drifted"] == drift["drifted"] == 1
    assert counts["drift"]["rotted"] == drift["rotted"] == 1
    assert counts["drift"]["unverified"] == drift["unverified"] == 1


def test_empty_scope_custody_headline_is_zero_scrolls(scrolls_home):
    # honest absence: an empty bundle still states the scope custody (0 scrolls)
    main(["init"])
    bundle = build_bundle(get_paths().db_path, "nothingmatcheshere")
    assert "_Custody: 0 scroll(s)._" in bundle
    assert "No matching scrolls." in bundle


# --- per-source custody breakdown under the scope headline (roadmap H141) ----


def _seed_multi_source(db):
    """Two `web` scrolls (one verified, one drifted) + one never-checked `arxiv`.

    Every title carries "database" so a `database` query covers the whole scope.
    web: fidelity full 2, drift verified 1 + drifted 1. arxiv: fidelity full 1,
    drift unverified 1. So the per-source split is non-trivial and the sources
    differ in custody — what a multi-source briefing must surface.
    """
    insert_item(db, make_item(
        "web:full", "Full database", "A full database.",
        source="web", url="https://web.example/full"))
    insert_item(db, make_item(
        "web:moved", "Moved database", "A moved database.",
        source="web", url="https://web.example/moved"))
    insert_item(db, make_item(
        "arxiv:1", "Arxiv database paper", "A database paper.",
        source="arxiv", url="https://arxiv.org/abs/1"))
    record_events(db, [_event("web:full", "unchanged", observed="deadbeef")])
    record_events(db, [_event("web:moved", "drifted", observed="cafe1234")])


def test_bundle_carries_a_per_source_custody_breakdown(scrolls_home):
    # roadmap H141: a multi-source briefing names which source's custody is weakest
    # within the shared scope, under the scope headline (sources sorted)
    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)
    bundle = build_bundle(db, "database")
    assert "_By source:_" in bundle
    # each bullet carries the source's recheck coverage too (roadmap H158):
    # arxiv 0 of 1 hash-bearing checked; web 2 of 2.
    assert (
        "- `arxiv` — 1 scroll(s) · fidelity full 1 · drift unverified 1"
        " · coverage 0/1" in bundle
    )
    assert (
        "- `web` — 2 scroll(s) · fidelity full 2 · drift verified 1, drifted 1"
        " · coverage 2/2" in bundle
    )


def test_per_source_breakdown_converges_with_custody_counts_by_source(scrolls_home):
    # the rendered lines come straight from the shared primitive, and the
    # per-source tallies sum to the scope headline's whole-scope counts (H45/H104)
    from scrolls.custody import (
        custody_counts,
        custody_counts_by_source,
        latest_events,
        render_custody_by_source,
    )
    from scrolls.items import list_items

    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)
    items = list_items(db)
    verdicts = latest_events(db)
    by_source = custody_counts_by_source(items, verdicts)

    bundle = build_bundle(db, "database")
    for line in render_custody_by_source(by_source):
        assert line in bundle

    whole = custody_counts(items, verdicts)
    summed_tiers = {tier: 0 for tier in ("full", "partial", "reference")}
    summed_drift = {p: 0 for p in ("verified", "unverified", "drifted", "rotted", "error")}
    for counts in by_source.values():
        for tier, n in counts["tiers"].items():
            summed_tiers[tier] += n
        for posture, n in counts["drift"].items():
            summed_drift[posture] += n
    assert summed_tiers == whole["tiers"]
    assert summed_drift == whole["drift"]


def test_per_source_breakdown_omitted_for_a_single_source(scrolls_home):
    # the whole-scope headline already says everything when there is one source
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "web:a", "A database", "A database.", source="web", url="https://web/a"))
    insert_item(db, make_item(
        "web:b", "B database", "B database.", source="web", url="https://web/b"))
    bundle = build_bundle(db, "database")
    assert "_Custody:" in bundle
    assert "_By source:_" not in bundle


def test_per_source_breakdown_empty_scope_is_a_no_op(scrolls_home):
    # an empty scope carries the scope headline but no per-source split
    main(["init"])
    bundle = build_bundle(get_paths().db_path, "nothingmatcheshere")
    assert "_Custody: 0 scroll(s)._" in bundle
    assert "_By source:_" not in bundle


def test_per_source_breakdown_preserves_the_round_trip(scrolls_home):
    # the breakdown is a derived read view *outside* the @generated JSONL fence,
    # so the lossless round-trip is untouched
    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)
    bundle = build_bundle(db, "database")
    assert "_By source:_" in bundle
    assert sorted(i.id for i in parse_bundle(bundle)) == [
        "arxiv:1", "web:full", "web:moved",
    ]


def test_bundle_html_carries_a_per_source_custody_breakdown(scrolls_home):
    # roadmap H141: the HTML briefing carries the same per-source breakdown,
    # from the shared structured primitive so the two forms cannot desync
    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)
    doc = build_bundle_html(db, "database")
    assert "By source:" in doc
    assert '<ul class="custody-by-source">' in doc
    assert (
        "<code>web</code> — 2 scroll(s) · fidelity full 2 · "
        "drift verified 1, drifted 1 · coverage 2/2" in doc
    )
    assert (
        "<code>arxiv</code> — 1 scroll(s) · fidelity full 1 · drift unverified 1"
        " · coverage 0/1" in doc
    )


def test_bundle_html_per_source_breakdown_omitted_for_a_single_source(scrolls_home):
    # parity with the Markdown form: one source → no split
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "web:a", "A database", "A database.", source="web", url="https://web/a"))
    doc = build_bundle_html(db, "database")
    assert "By source:" not in doc


# --- readable weakest-source `_Attention:_` line (roadmap H159) --------------


def _seed_clean_multi_source(db):
    """Two sources, neither carrying any drifted/rotted loss — a clean scope.

    `web` verified, `arxiv` never checked: the per-source split is non-trivial
    (two sources) but nothing is actionable, so `weakest_source`/the readable
    `_Attention:_` line are both honestly absent.
    """
    insert_item(db, make_item(
        "web:ok", "OK database", "An ok database.",
        source="web", url="https://web.example/ok"))
    insert_item(db, make_item(
        "arxiv:2", "Arxiv database note", "A database note.",
        source="arxiv", url="https://arxiv.org/abs/2"))
    record_events(db, [_event("web:ok", "unchanged", observed="deadbeef")])


def test_bundle_carries_a_weakest_source_attention_line(scrolls_home):
    # roadmap H159: one `_Attention:_` line names the single source with the most
    # actionable loss and the exact recheck command. In `_seed_multi_source`, web
    # carries the only loss (1 drifted), so it is flagged.
    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)
    bundle = build_bundle(db, "database")
    assert (
        "_Attention: source `web` carries the most drift (1 drifted) — "
        "recheck with `scrolls verify --source web`._" in bundle
    )
    # the pointer is skimmed first: it sits above the per-source map
    assert bundle.index("_Attention:") < bundle.index("_By source:_")


def test_attention_line_converges_with_weakest_source(scrolls_home):
    # the rendered line comes straight from the shared `weakest_source`/
    # `render_custody_attention` primitives over the bundle scope's own
    # `custody_counts_by_source`, so the readable line and the JSON `attention`
    # flag (status/maintain) name the same source by construction
    from scrolls.custody import (
        custody_counts_by_source,
        latest_events,
        render_custody_attention,
        weakest_source,
    )
    from scrolls.items import list_items

    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)
    items = list_items(db)
    verdicts = latest_events(db)
    by_source = custody_counts_by_source(items, verdicts)

    bundle = build_bundle(db, "database")
    for line in render_custody_attention(by_source):
        assert line in bundle
    flagged = weakest_source(by_source)
    assert flagged["source"] == "web"
    assert flagged["command"] == "scrolls verify --source web"
    assert f"`{flagged['command']}`" in bundle


def test_attention_line_omitted_for_a_single_source(scrolls_home):
    # one source never stands out — the scope headline says everything (the same
    # honest-absence count as the JSON `attention` flag)
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "web:moved", "Moved database", "A moved database.",
        source="web", url="https://web.example/moved"))
    record_events(db, [_event("web:moved", "drifted", observed="cafe1234")])
    bundle = build_bundle(db, "database")
    assert "custody `drifted`" in bundle  # the loss is still recorded per-scroll
    assert "_Attention:" not in bundle  # but no cross-source pointer
    assert "_By source:_" not in bundle


def test_attention_line_omitted_for_a_clean_multi_source_scope(scrolls_home):
    # multi-source but no source carries drifted/rotted loss → the `_By source:_`
    # split still renders, but there is nothing actionable to flag
    main(["init"])
    db = get_paths().db_path
    _seed_clean_multi_source(db)
    bundle = build_bundle(db, "database")
    assert "_By source:_" in bundle
    assert "_Attention:" not in bundle


def test_attention_line_empty_scope_is_a_no_op(scrolls_home):
    main(["init"])
    bundle = build_bundle(get_paths().db_path, "nothingmatcheshere")
    assert "_Custody: 0 scroll(s)._" in bundle
    assert "_Attention:" not in bundle


def test_attention_line_preserves_the_round_trip(scrolls_home):
    # the line is a derived read view *outside* the @generated JSONL fence, so the
    # lossless round-trip is untouched (the H35/H141 derived-view invariant)
    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)
    bundle = build_bundle(db, "database")
    assert "_Attention:" in bundle
    assert sorted(i.id for i in parse_bundle(bundle)) == [
        "arxiv:1", "web:full", "web:moved",
    ]


# --- readable work-level at-risk `_At-risk work:_` line (roadmap H264) --------


def _ref_item(item_id, title, doi, **overrides):
    """A reference-only representation (no content) of the work named by `doi`."""
    item = make_item(
        item_id, title, "ignored", links=(f"https://doi.org/{doi}",), **overrides)
    return dataclasses.replace(
        item, raw_text=None, extracted_text=None, summary=None, content_hash=None)


def _seed_at_risk_work(db):
    """One at-risk multi-rep work (Z) + one safely-held multi-rep work (Y).

    Work Z (10.3000/z): two reference-only reps (no full form anywhere), so no
    representation is both full and unmoved → at risk, the lowest custody ceiling.
    Work Y (10.2000/y): a full + never-checked preprint (unverified ∈ the safe set,
    so safely held) + a reference record. Both works' titles carry "database" so a
    `database` query covers the whole scope. 2 works, 1 at risk → Z is named.
    """
    insert_item(db, _ref_item(
        "arxiv:zref", "Zeta database preprint", "10.3000/z",
        source="arxiv", url="https://arxiv.org/abs/zref"))
    insert_item(db, _ref_item(
        "crossref:10.3000/z", "Zeta database record", "10.3000/z",
        source="crossref", url="https://doi.org/10.3000/z"))
    insert_item(db, make_item(
        "arxiv:yfull", "Ypsilon database preprint", "A full database body.",
        source="arxiv", url="https://arxiv.org/abs/yfull",
        links=("https://doi.org/10.2000/y",), content_hash="deadbeef",
        raw_text="<raw>A full database body.</raw>"))
    insert_item(db, _ref_item(
        "crossref:10.2000/y", "Ypsilon database record", "10.2000/y",
        source="crossref", url="https://doi.org/10.2000/y"))


def test_bundle_carries_an_at_risk_work_line(scrolls_home):
    # roadmap H264: one `_At-risk work:_` line names the single work no representation
    # safely holds (the consolidation counterpart of the per-source `_Attention:_`).
    # Z is all-reference (nothing re-derivable held) → the lowest-ceiling work.
    main(["init"])
    db = get_paths().db_path
    _seed_at_risk_work(db)
    bundle = build_bundle(db, "database")
    assert (
        "_At-risk work: `10.3000/z` — no representation is both full and unmoved "
        "(best held reference, safest drift unverified); 1 work(s) at risk._"
        in bundle
    )
    # the consolidation pointer is skimmed above the per-source map, like the
    # per-source `_Attention:_` line (here there is no source loss, so no source line)
    assert bundle.index("_At-risk work:") < bundle.index("_By source:_")


def test_at_risk_work_line_converges_with_at_risk_signal(scrolls_home):
    # the rendered line comes straight from the shared `render_at_risk_works`/
    # `at_risk_signal` over the bundle scope's own clustered works, so the readable
    # line and `doctor`'s `custody.works` JSON alarm name the same work by construction
    from scrolls.custody import latest_events
    from scrolls.items import list_items
    from scrolls.works import at_risk_signal, render_at_risk_works, works_over

    main(["init"])
    db = get_paths().db_path
    _seed_at_risk_work(db)
    items = list_items(db)
    verdicts = latest_events(db)

    bundle = build_bundle(db, "database")
    for line in render_at_risk_works(items, verdicts):
        assert line in bundle
    most = at_risk_signal(works_over(items), verdicts)["most_at_risk"]
    assert most["doi"] == "10.3000/z"
    assert f"`{most['doi']}`" in bundle


def test_at_risk_work_line_omitted_when_no_work_at_risk(scrolls_home):
    # a single safely-held work (full + never-checked) → honest absence, no pointer
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "arxiv:yfull", "Ypsilon database preprint", "A full database body.",
        source="arxiv", url="https://arxiv.org/abs/yfull",
        links=("https://doi.org/10.2000/y",), content_hash="deadbeef",
        raw_text="<raw>A full database body.</raw>"))
    insert_item(db, _ref_item(
        "crossref:10.2000/y", "Ypsilon database record", "10.2000/y",
        source="crossref", url="https://doi.org/10.2000/y"))
    bundle = build_bundle(db, "database")
    assert "_Custody:" in bundle
    assert "_At-risk work:" not in bundle


def test_at_risk_work_line_omitted_for_a_single_representation_scope(scrolls_home):
    # a lone representation is no work (the min_representations floor) — even an
    # all-reference single item carries no consolidation alarm
    main(["init"])
    db = get_paths().db_path
    insert_item(db, _ref_item(
        "arxiv:lone", "Lone database preprint", "10.9000/lone",
        source="arxiv", url="https://arxiv.org/abs/lone"))
    bundle = build_bundle(db, "database")
    assert "_At-risk work:" not in bundle


def test_at_risk_work_line_empty_scope_is_a_no_op(scrolls_home):
    main(["init"])
    bundle = build_bundle(get_paths().db_path, "nothingmatcheshere")
    assert "_Custody: 0 scroll(s)._" in bundle
    assert "_At-risk work:" not in bundle


def test_at_risk_work_line_preserves_the_round_trip(scrolls_home):
    # the line is a derived read view *outside* the @generated JSONL fence, so the
    # lossless round-trip is untouched (the H35/H141/H159 derived-view invariant)
    main(["init"])
    db = get_paths().db_path
    _seed_at_risk_work(db)
    bundle = build_bundle(db, "database")
    assert "_At-risk work:" in bundle
    assert sorted(i.id for i in parse_bundle(bundle)) == [
        "arxiv:yfull", "arxiv:zref", "crossref:10.2000/y", "crossref:10.3000/z",
    ]


def test_bundle_html_carries_an_at_risk_work_line(scrolls_home):
    # roadmap H271: the HTML briefing carries the same work-level at-risk pointer as
    # the Markdown `_At-risk work:_` line (H264), from the *same* `at_risk_signal`
    # over the same lean-scope clustered works — so the two readable forms cannot
    # desync. Z is all-reference (nothing re-derivable held) → the lowest-ceiling work.
    main(["init"])
    db = get_paths().db_path
    _seed_at_risk_work(db)
    doc = build_bundle_html(db, "database")
    assert (
        '<p class="custody-at-risk">At-risk work: <code>10.3000/z</code> — '
        "no representation is both full and unmoved "
        "(best held reference, safest drift unverified); 1 work(s) at risk.</p>"
        in doc
    )
    # grouped with the source attention pointer and above the per-source list (the
    # <p>/<ul> elements, not the always-present CSS rule of the same class name)
    assert doc.index('<p class="custody-at-risk">') < doc.index(
        '<ul class="custody-by-source">'
    )


def test_bundle_html_at_risk_line_converges_with_the_markdown_form(scrolls_home):
    # the HTML <p> and the Markdown `_At-risk work:_` line name the same work,
    # reason, and at_risk count — two renders of the one `at_risk_signal` fold, so
    # the HTML twin agrees with `doctor`'s `custody.works` by construction (H264)
    from scrolls.custody import latest_events
    from scrolls.items import list_items
    from scrolls.works import at_risk_signal, works_over

    main(["init"])
    db = get_paths().db_path
    _seed_at_risk_work(db)
    items = list_items(db)
    most = at_risk_signal(works_over(items), latest_events(db))["most_at_risk"]
    assert most["doi"] == "10.3000/z"

    doc = build_bundle_html(db, "database")
    bundle = build_bundle(db, "database")
    # both forms name the same work and reason (HTML <code> vs Markdown backticks)
    assert f"<code>{most['doi']}</code>" in doc
    assert f"`{most['doi']}`" in bundle
    assert most["reason"] in doc and most["reason"] in bundle


def test_bundle_html_at_risk_line_omitted_when_no_work_at_risk(scrolls_home):
    # a single safely-held work (full + never-checked) → honest absence, no <p>,
    # the same no-op the HTML attention line takes
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "arxiv:yfull", "Ypsilon database preprint", "A full database body.",
        source="arxiv", url="https://arxiv.org/abs/yfull",
        links=("https://doi.org/10.2000/y",), content_hash="deadbeef",
        raw_text="<raw>A full database body.</raw>"))
    insert_item(db, _ref_item(
        "crossref:10.2000/y", "Ypsilon database record", "10.2000/y",
        source="crossref", url="https://doi.org/10.2000/y"))
    doc = build_bundle_html(db, "database")
    assert "Custody:" in doc  # the headline still renders
    assert '<p class="custody-at-risk">' not in doc


def test_bundle_html_at_risk_line_omitted_for_single_rep_and_empty_scope(scrolls_home):
    # a lone representation is no work (the min_representations floor); an empty
    # scope holds nothing — both are honest no-ops, no <p>
    main(["init"])
    db = get_paths().db_path
    insert_item(db, _ref_item(
        "arxiv:lone", "Lone database preprint", "10.9000/lone",
        source="arxiv", url="https://arxiv.org/abs/lone"))
    assert '<p class="custody-at-risk">' not in build_bundle_html(db, "database")
    assert '<p class="custody-at-risk">' not in build_bundle_html(
        db, "nothingmatcheshere"
    )


def test_bundle_html_carries_a_weakest_source_attention_line(scrolls_home):
    # roadmap H159: the HTML briefing carries the same pointer, from the same
    # `weakest_source`, so the two readable forms cannot desync
    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)
    doc = build_bundle_html(db, "database")
    assert (
        '<p class="custody-attention">Attention: source <code>web</code> '
        "carries the most drift (1 drifted) — recheck with "
        "<code>scrolls verify --source web</code>.</p>" in doc
    )
    # skimmed first: above the per-source list (the <p>/<ul> elements, not the
    # always-present CSS rule of the same class name in the <style> block)
    assert doc.index('<p class="custody-attention">') < doc.index('<ul class="custody-by-source">')


def test_bundle_html_attention_line_omitted_when_clean_or_single_source(scrolls_home):
    main(["init"])
    db = get_paths().db_path
    _seed_clean_multi_source(db)
    doc = build_bundle_html(db, "database")
    assert "By source:" in doc  # multi-source split still renders
    assert '<p class="custody-attention">' not in doc  # nothing actionable to flag


# --- readable per-source `_Refresh:_` line (roadmap H178) --------------------
#
# The enrichment/summary-axis counterpart of the drift `_Attention:_` line: it
# names which source's classifications/summaries are stale and the exact
# `classify --stale`/`kb --stale --source <S>` refresh, computed over the
# bundle's own scope by the same builders doctor's `custody.enrichment.by_source`/
# `summaries.by_source` fold (convergence by construction). Honest-absent when no
# source carries refresh debt; no single-source gate (refresh debt is per-source
# work, not a cross-source comparison).


def _seed_refresh_debt(db):
    """Stale classification on `web` + a stale summary spanning `web`+`arxiv`.

    web:old-class is rules-classified under a superseded ruleset → enrichment debt
    {web}. The `Databases` concept (web:db1 + arxiv:db2) has a stored summary under
    an outdated members_hash → summary debt {arxiv, web} (the H171 multi-source
    attribution). Every title carries "database" so a `database` query is the whole
    scope.
    """
    insert_item(db, make_item(
        "web:old-class", "Old database doc", "An old database doc.",
        source="web", url="https://web.example/old", category="documentation",
        provenance=_rules_provenance(ruleset="oldfingerprint")))
    insert_item(db, make_item(
        "web:db1", "Web database", "A web database.",
        source="web", url="https://web.example/db1", concepts=("Databases",)))
    insert_item(db, make_item(
        "arxiv:db2", "Arxiv database", "An arxiv database.",
        source="arxiv", url="https://arxiv.org/abs/db2", concepts=("Databases",)))
    save_concept_summary(db, ConceptSummary(
        slug="databases", display="Databases", summary="Old synthesis.",
        members_hash="stalefingerprint", engine=SUMMARY_ENGINE,
        model="claude-test", generated_at="2026-06-12T00:00:00+00:00"))


def test_bundle_carries_a_refresh_line_for_both_axes(scrolls_home):
    main(["init"])
    db = get_paths().db_path
    _seed_refresh_debt(db)
    bundle = build_bundle(db, "database")
    assert (
        "_Refresh: classifications stale in `web` — refresh with "
        "`scrolls classify --stale --source <S>`; summaries stale in `arxiv`, "
        "`web` — refresh with `scrolls kb --stale --source <S>`._" in bundle
    )
    # an actionable pointer, sits above the per-source map like `_Attention:_`
    assert bundle.index("_Refresh:") < bundle.index("_By source:_")


def test_bundle_refresh_line_omitted_when_no_stale_debt(scrolls_home):
    # a current-ruleset classification + no stored summary → no refresh debt
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "web:fresh", "Fresh database", "A current database.",
        source="web", url="https://web.example/fresh",
        category="documentation", provenance=_rules_provenance()))
    bundle = build_bundle(db, "database")
    assert "_Refresh:" not in bundle  # honest absence, nothing to refresh


def test_bundle_refresh_line_shown_for_a_single_source(scrolls_home):
    # no single-source gate: refresh debt is per-source actionable work, so a
    # single-source bundle still names it — unlike `_Attention:_`/`_By source:_`
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "web:old-class", "Old database doc", "An old database doc.",
        source="web", url="https://web.example/old", category="documentation",
        provenance=_rules_provenance(ruleset="oldfingerprint")))
    bundle = build_bundle(db, "database")
    assert "_Refresh: classifications stale in `web`" in bundle
    assert "_Attention:" not in bundle  # single source: nothing to rank across
    assert "_By source:_" not in bundle  # single source: the headline says all


def test_refresh_line_converges_with_the_doctor_maps(scrolls_home):
    # the line names exactly the sources doctor's per-source debt maps do (same
    # builders over the same whole-library scope — convergence by construction)
    main(["init"])
    db = get_paths().db_path
    _seed_refresh_debt(db)
    report = run_doctor(get_paths())
    enr = report["custody"]["enrichment"]["by_source"]
    summ = report["custody"]["summaries"]["by_source"]
    assert enr == {"web": 1} and summ == {"arxiv": 1, "web": 1}
    bundle = build_bundle(db, "database")  # query matches all → scope == library
    assert (
        "classifications stale in "
        + ", ".join(f"`{s}`" for s in enr) in bundle
    )
    assert "summaries stale in " + ", ".join(f"`{s}`" for s in summ) in bundle


def test_refresh_line_preserves_the_round_trip(scrolls_home):
    # the readable line is outside the lossless JSONL fence — the round-trip holds
    main(["init"])
    db = get_paths().db_path
    _seed_refresh_debt(db)
    bundle = build_bundle(db, "database")
    assert "_Refresh:" in bundle
    recovered = {i.id for i in parse_bundle(bundle)}
    assert recovered == {"web:old-class", "web:db1", "arxiv:db2"}


def test_bundle_html_carries_a_refresh_line(scrolls_home):
    # the HTML briefing carries the same pointer over the same maps — no desync
    main(["init"])
    db = get_paths().db_path
    _seed_refresh_debt(db)
    doc = build_bundle_html(db, "database")
    assert (
        '<p class="custody-refresh">Refresh: classifications stale in '
        "<code>web</code> — refresh with <code>scrolls classify --stale "
        "--source &lt;S&gt;</code>; summaries stale in <code>arxiv</code>, "
        "<code>web</code> — refresh with <code>scrolls kb --stale "
        "--source &lt;S&gt;</code>.</p>" in doc
    )


def test_bundle_html_refresh_omitted_when_clean(scrolls_home):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "web:fresh", "Fresh database", "A current database.",
        source="web", url="https://web.example/fresh",
        category="documentation", provenance=_rules_provenance()))
    doc = build_bundle_html(db, "database")
    assert '<p class="custody-refresh">' not in doc


def test_a_drifted_scroll_is_still_carried_losslessly(scrolls_home):
    # raw is sacred: a drifted scroll is a recorded posture, never dropped
    main(["init"])
    db = get_paths().db_path
    original = make_item("wikipedia:en:Moved", "Moved", "A moved database.")
    insert_item(db, original)
    record_events(db, [_event("wikipedia:en:Moved", "drifted", observed="cafe1234")])

    bundle = build_bundle(db, "database")
    assert "custody `drifted`" in bundle
    recovered = parse_bundle(bundle)
    assert [i.id for i in recovered] == ["wikipedia:en:Moved"]
    assert item_to_dict(recovered[0]) == item_to_dict(original)


# --- full export → import round-trip across libraries (ADR 0099) ------------


def test_export_import_round_trips_across_a_fresh_library(scrolls_home, monkeypatch, tmp_path, capsys):
    # hold a topic in library A, take it with you to an empty library B
    main(["init"])
    db_a = get_paths().db_path
    insert_item(db_a, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))
    insert_item(db_a, make_item(
        "arxiv:1706.03762", "Attention", "A database-adjacent attention paper.",
        source="arxiv", url="https://arxiv.org/abs/1706.03762",
    ))
    capsys.readouterr()

    assert main(["export", "bundle", "database"]) == 0
    bundle_text = capsys.readouterr().out
    bundle_path = tmp_path / "briefing.md"
    bundle_path.write_text(bundle_text, encoding="utf-8")

    # a fresh, empty library B
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()

    assert main(["import", "bundle", str(bundle_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["imported"] == 2
    # both scrolls landed in B with their canonical custody records intact
    a = get_item(db_b, "wikipedia:en:SQLite")
    assert a is not None and a.raw_text == "<raw>SQLite is a database engine.</raw>"
    assert a.content_hash == "deadbeef"
    assert get_item(db_b, "arxiv:1706.03762") is not None


def test_import_bundle_never_overwrites_an_existing_scroll(scrolls_home, tmp_path, capsys):
    # custody-safe re-import: INSERT OR IGNORE, so an item already held is kept
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))
    capsys.readouterr()
    main(["export", "bundle", "database"])
    bundle_path = tmp_path / "b.md"
    bundle_path.write_text(capsys.readouterr().out, encoding="utf-8")

    # importing back into the same library imports nothing new
    main(["import", "bundle", str(bundle_path)])
    report = json.loads(capsys.readouterr().out)
    assert report["imported"] == 0
    assert report["skipped"] == 1


# --- mixed-fidelity round-trip: portability is *tier-lossless* (H216) --------


def _mixed_fidelity_scope():
    """Three scrolls spanning all three fidelity tiers, all in the "database"
    query scope. The reference-only pointer holds no body to index, so "database"
    rides in its title to stay in scope (the H45 reference-fixture pattern)."""
    return [
        # full: a re-derivable body (raw_text) + a content_hash at a captured stage
        make_item("wikipedia:en:Full", "Full", "A full database engine."),
        # partial: extracted text survives but no hash/raw body → a degraded-but-
        # honest capture, not re-derivable to full
        make_item(
            "wikipedia:en:Partial", "Partial", "A partial database capture.",
            raw_text=None, content_hash=None, summary=None,
        ),
        # reference: only the pointer + provenance are held, no content at all
        make_item(
            "wikipedia:en:Ref", "Reference database pointer", "",
            raw_text=None, summary=None, content_hash=None,
            markdown_path=None, stage="detected",
        ),
    ]


def test_mixed_fidelity_bundle_parse_preserves_each_tier(scrolls_home):
    # portability is *tier-lossless*, not just full-lossless: a bundle spanning
    # full/partial/reference re-parses with each item's get_fidelity tier intact
    # — the partial/reference tiers the other round-trip ties never exercise
    from scrolls.items import get_fidelity

    main(["init"])
    db = get_paths().db_path
    for item in _mixed_fidelity_scope():
        insert_item(db, item)

    expected = {
        "wikipedia:en:Full": "full",
        "wikipedia:en:Partial": "partial",
        "wikipedia:en:Ref": "reference",
    }
    # non-vacuous: the fixture really spans all three tiers
    assert set(expected.values()) == {"full", "partial", "reference"}

    recovered = {
        item.id: get_fidelity(item) for item in parse_bundle(build_bundle(db, "database"))
    }
    assert recovered == expected


def test_mixed_fidelity_bundle_round_trips_across_a_fresh_library(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    # the end-to-end "take it with me" proof for the partial/reference tiers the
    # all-full dogfood fixture never exercises: every tier survives
    # `export bundle` → `import bundle` into an empty library with no import-side
    # downgrade
    from scrolls.items import get_fidelity

    main(["init"])
    db_a = get_paths().db_path
    for item in _mixed_fidelity_scope():
        insert_item(db_a, item)
    # the tiers as the *stored* rows derive them (the path the bundle reads from)
    tiers_a = {
        item.id: get_fidelity(get_item(db_a, item.id)) for item in _mixed_fidelity_scope()
    }
    assert sorted(tiers_a.values()) == ["full", "partial", "reference"]
    capsys.readouterr()

    assert main(["export", "bundle", "database"]) == 0
    bundle_text = capsys.readouterr().out
    bundle_path = tmp_path / "briefing.md"
    bundle_path.write_text(bundle_text, encoding="utf-8")
    # fidelity travels in the readable briefing too — every tier is named in prose
    assert "fidelity `full`" in bundle_text
    assert "fidelity `partial`" in bundle_text
    assert "fidelity `reference`" in bundle_text

    # a fresh, empty library B
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()

    assert main(["import", "bundle", str(bundle_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["imported"] == 3
    # every item landed in B at the *same* fidelity tier — the round-trip never
    # downgrades a held body to a reference, nor invents fidelity it didn't carry
    tiers_b = {item_id: get_fidelity(get_item(db_b, item_id)) for item_id in tiers_a}
    assert tiers_b == tiers_a


# --- the bundle round-trip is byte-identical across mixed tiers too (H238) ---
#
# `test_mixed_fidelity_bundle_round_trips_across_a_fresh_library` (above) proves
# every fidelity *tier* survives `export bundle` → `import bundle`; H231
# (`tests/test_roundtrip.py`) proves the rebuilt scrolls + `library/` pages are
# byte-for-byte equal — but only over the *whole-library JSONL backup*
# (`export items`). The bundle item block is the *same* `export items` JSONL
# (`bundle.py` `_items_block` → `dump_items_export`) wrapped in a sentinel-fenced
# Markdown envelope — a genuinely different envelope around the same rows — and no
# test pins byte-identity through *that* envelope. This is the bundle-surface
# corner of the H216/H224/H231 round-trip matrix: the `partial` capture's
# `content_hash`-less scroll (render.py omits a None field, a strictly different
# frontmatter byte-shape than a `full` scroll) rebuilds byte-for-byte across the
# bundle boundary, and — since the scope captures every item — the compiled
# `library/` pages too.


def _read_tree(directory) -> dict[str, bytes]:
    """Every file under `directory`, keyed by path relative to it (bytes)."""
    if not directory.exists():
        return {}
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _render_mixed_library(items):
    """Render the rendered-stage items to disk and index every item at the active
    home, then compile the KB — the on-disk source library the bundle round-trip
    reads from. The reference holds no body, so it is inserted as-is rather than
    rendered (rendering would mint a scroll it has no body to fill)."""
    from scrolls.db import init_db
    from scrolls.render import write_scroll

    paths = get_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    init_db(paths.db_path)
    for item in items:
        if item.stage == "rendered":
            item = write_scroll(paths, item)
        insert_item(paths.db_path, item)
    assert main(["kb"]) == 0


def test_mixed_fidelity_bundle_rebuilds_byte_identically_across_a_fresh_library(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    # the bundle-surface byte-depth proof: a scoped `export bundle` →
    # `import bundle` round-trip rebuilds the `partial` capture's
    # `content_hash`-less scroll byte-for-byte (and, since "database" captures
    # every item, the compiled `library/` pages too) — the bundle envelope the
    # whole-library byte-identity tests (H231) never exercise
    _render_mixed_library(_mixed_fidelity_scope())
    paths_a = get_paths()
    capsys.readouterr()  # drain the kb report before capturing the source trees

    # capture the source's rendered scrolls and compiled library trees (bytes)
    src_scrolls = _read_tree(paths_a.scrolls_dir)
    src_library = _read_tree(paths_a.library_dir)

    # non-vacuous: the source tree genuinely spans both byte-shapes. A `full`
    # scroll carries a `content_hash:` frontmatter line; the `partial` capture has
    # no hash to fingerprint its body, so render.py omits the line — a strictly
    # different frontmatter byte-shape. Both shapes are present, so byte-identity
    # over this tree is a stronger claim than over an all-`full` one.
    with_hash = [p for p, body in src_scrolls.items() if b"content_hash" in body]
    without_hash = [p for p, body in src_scrolls.items() if b"content_hash" not in body]
    assert with_hash, "expected at least one full scroll (with a content_hash line)"
    assert without_hash, "expected the partial scroll (rendered with no content_hash)"

    # the bundle scope captures every item: "database" rides in the full/partial
    # bodies and the reference's title, so the bundle is the whole library
    assert main(["export", "bundle", "database"]) == 0
    bundle_text = capsys.readouterr().out
    bundle_path = tmp_path / "briefing.md"
    bundle_path.write_text(bundle_text, encoding="utf-8")

    # a fresh, empty library B
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    paths_b = get_paths()
    capsys.readouterr()

    assert main(["import", "bundle", str(bundle_path)]) == 0
    assert json.loads(capsys.readouterr().out)["imported"] == 3

    # rebuild the derived artifacts from the imported rows, the documented restore
    assert main(["doctor", "--fix"]) == 0
    assert main(["kb"]) == 0
    capsys.readouterr()  # drain the doctor/kb reports

    # the rendered scrolls — the partial's content_hash-less scroll included —
    # rebuild byte-identically across the bundle boundary
    assert _read_tree(paths_b.scrolls_dir) == src_scrolls
    # and, since the scope captured the whole library, the compiled library/
    # pages rebuild byte-identically too
    assert _read_tree(paths_b.library_dir) == src_library


# --- portable custody: the verify ledger travels in the bundle (H67) --------


def test_bundle_carries_a_custody_events_block(scrolls_home):
    # the in-scope items' verify ledger travels as a second @generated region,
    # so an item's drift *history* — not just the last-seen posture — is portable
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite", "A database engine."))
    record_events(db, [
        _event("wikipedia:en:SQLite", "unchanged", observed="deadbeef"),
        _event("wikipedia:en:SQLite", "drifted", observed="cafe1234"),
    ])

    bundle = build_bundle(db, "database")
    # a second self-describing fenced block alongside the items block
    assert "scrolls export bundle (custody events)" in bundle
    # parse_bundle_events recovers both checks, with the item id (the block
    # spans many items, so each row names its own)
    events = parse_bundle_events(bundle)
    assert [(e.item_id, e.status) for e in events] == [
        ("wikipedia:en:SQLite", "unchanged"),
        ("wikipedia:en:SQLite", "drifted"),
    ]


def test_custody_events_round_trip_into_a_fresh_library(scrolls_home, monkeypatch, tmp_path, capsys):
    # custody itself is portable: export the ledger from A, restore it in empty B
    main(["init"])
    db_a = get_paths().db_path
    insert_item(db_a, make_item("wikipedia:en:SQLite", "SQLite", "A database engine."))
    record_events(db_a, [
        _event("wikipedia:en:SQLite", "unchanged", observed="deadbeef"),
        _event("wikipedia:en:SQLite", "drifted", observed="cafe1234"),
    ])
    capsys.readouterr()
    main(["export", "bundle", "database"])
    bundle_path = tmp_path / "briefing.md"
    bundle_path.write_text(capsys.readouterr().out, encoding="utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    # before import, B has never checked the source — honest unverified
    capsys.readouterr()
    main(["import", "bundle", str(bundle_path)])
    report = json.loads(capsys.readouterr().out)
    assert report["events"] == {
        "imported": 2, "skipped": 0, "orphaned": 0, "orphaned_items": [],
    }
    # the full ledger landed in B, newest-first, and the latest posture is the
    # exporter's — drift travels, it is not frozen as prose
    assert [e["status"] for e in item_history(db_b, "wikipedia:en:SQLite")] == [
        "drifted", "unchanged"
    ]
    posture_b = next(
        line for line in build_bundle(db_b, "database").splitlines()
        if "custody `" in line
    )
    assert "custody `drifted`" in posture_b


def test_re_importing_a_bundle_dedups_the_custody_events(scrolls_home, tmp_path, capsys):
    # idempotent restore: re-importing the same bundle is a custody no-op
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite", "A database engine."))
    record_events(db, [_event("wikipedia:en:SQLite", "drifted", observed="cafe1234")])
    capsys.readouterr()
    main(["export", "bundle", "database"])
    bundle_path = tmp_path / "b.md"
    bundle_path.write_text(capsys.readouterr().out, encoding="utf-8")

    # first import is back into the same library: the event already exists → skipped
    main(["import", "bundle", str(bundle_path)])
    report = json.loads(capsys.readouterr().out)
    assert report["events"] == {
        "imported": 0, "skipped": 1, "orphaned": 0, "orphaned_items": [],
    }
    # the ledger did not grow — still exactly the one original check
    assert len(item_events(db, "wikipedia:en:SQLite")) == 1


def test_an_unverified_scope_carries_an_empty_events_block(scrolls_home):
    # a bundle whose scope has no verify history still carries the (empty) events
    # block, so the structure is stable; it parses to no events
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite", "A database engine."))

    bundle = build_bundle(db, "database")
    assert "scrolls export bundle (custody events)" in bundle
    assert parse_bundle_events(bundle) == []


def test_a_pre_h67_bundle_without_an_events_block_imports_items_only(scrolls_home, tmp_path, capsys):
    # backward compatibility: an older bundle has only the items block (one
    # @generated region). parse_bundle_events sees no second region → [], so it
    # imports items and simply carries no events — never a crash
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite", "A database engine."))
    legacy = (
        "# Scrolls Custody Bundle: database\n\n"
        "<!-- @generated scrolls — regenerated by `scrolls export bundle` -->\n"
        "```jsonl\n"
        + json.dumps(item_to_dict(get_item(db, "wikipedia:en:SQLite"))) + "\n"
        "```\n<!-- @end scrolls -->\n"
    )
    assert parse_bundle_events(legacy) == []
    legacy_path = tmp_path / "legacy.md"
    legacy_path.write_text(legacy, encoding="utf-8")
    capsys.readouterr()
    assert main(["import", "bundle", str(legacy_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["items"] == 1
    assert report["events"] == {
        "imported": 0, "skipped": 0, "orphaned": 0, "orphaned_items": [],
    }


def test_a_corrupt_custody_events_block_is_reported(scrolls_home):
    # a malformed event row fails loudly, naming the record, never silently
    # dropping a check (losing drift history would lose the proof of a verify)
    bad = (
        "# Scrolls Custody Bundle: x\n\n"
        "<!-- @generated scrolls — regenerated by `scrolls export bundle` -->\n"
        "```jsonl\n```\n<!-- @end scrolls -->\n"
        "<!-- @generated scrolls — regenerated by `scrolls export bundle (custody events)` -->\n"
        "```jsonl\n{not valid json\n```\n<!-- @end scrolls -->\n"
    )
    with pytest.raises(BundleError, match="custody-events block record 1"):
        parse_bundle_events(bad)


# --- orphan custody events (roadmap H217) ----------------------------------


def _spliced_bundle(item, *, anchored_events, orphan_events):
    """A bundle whose events block names an item the items block omits.

    A *well-formed* export never desyncs the two blocks — `events_for_items`
    scopes the events to the in-scope items, every one of which also rides the
    items block — so an orphan event only arises from corruption or a hand-edit.
    We model exactly that here, splicing real block builders so the sentinels and
    fences stay valid and only the items↔events *content* is desynced.
    """
    from scrolls.bundle import _events_block, _items_block

    return (
        "# Scrolls Custody Bundle: spliced\n\n"
        + _items_block([item])
        + "\n"
        + _events_block(list(anchored_events) + list(orphan_events))
        + "\n"
    )


def test_partition_resolvable_events_separates_held_from_orphan(scrolls_home):
    # the H217 primitive: an event resolves iff its item is in the library
    # (held-or-imported); otherwise it is an orphan — a ledger row with no item
    from scrolls.custody import partition_resolvable_events

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite", "A database engine."))
    held = _event("wikipedia:en:SQLite", "drifted", observed="cafe1234")
    orphan = _event("wikipedia:en:Ghost", "drifted", observed="beef9999")

    resolvable, orphans = partition_resolvable_events(db, [held, orphan])
    assert [e.item_id for e in resolvable] == ["wikipedia:en:SQLite"]
    assert [e.item_id for e in orphans] == ["wikipedia:en:Ghost"]


def test_import_bundle_skips_and_counts_orphan_custody_events(
    scrolls_home, tmp_path, capsys
):
    # H217: a bundle's events must resolve to a held-or-imported item. A spliced
    # bundle whose events name an item the items block omits is surfaced (counted +
    # warned) and NOT inserted — a ledger row for an item `show` 404s on would be a
    # dangling history, never silently retained nor silently dropped.
    main(["init"])
    db = get_paths().db_path
    held = make_item("wikipedia:en:SQLite", "SQLite", "A database engine.")
    bundle = _spliced_bundle(
        held,
        anchored_events=[_event("wikipedia:en:SQLite", "drifted", observed="cafe1234")],
        orphan_events=[_event("wikipedia:en:Ghost", "drifted", observed="beef9999")],
    )
    bundle_path = tmp_path / "spliced.md"
    bundle_path.write_text(bundle, encoding="utf-8")

    capsys.readouterr()
    rc = main(["import", "bundle", str(bundle_path)])
    captured = capsys.readouterr()
    assert rc == 0
    report = json.loads(captured.out)
    # the held item's event imported; the orphan one counted, not imported
    assert report["events"] == {
        "imported": 1, "skipped": 0, "orphaned": 1,
        "orphaned_items": ["wikipedia:en:Ghost"],
    }
    # the orphan left no dangling ledger row — custody stays coherent
    assert item_events(db, "wikipedia:en:Ghost") == []
    # the anchored event did land
    assert [e.status for e in item_events(db, "wikipedia:en:SQLite")] == ["drifted"]
    # the orphan is loud, not silent (a stderr warning names the orphan count)
    assert "orphan" in captured.err.lower()


def test_import_bundle_warning_names_which_items_the_orphans_dangle_on(
    scrolls_home, tmp_path, capsys
):
    # H225: the orphan warning is *diagnosable*, not just a count — it names the
    # distinct `item_id`s the orphan events point at, so "3 orphan events" becomes
    # "… not in this bundle …: `arxiv:…`, `wikipedia:en:Ghost`" and the operator
    # can see *which* rows the items block is missing, not just that it is corrupt.
    # The count stays the event count; the id list is the distinct-item count, so
    # two events naming the same missing item name it once.
    main(["init"])
    db = get_paths().db_path
    held = make_item("wikipedia:en:SQLite", "SQLite", "A database engine.")
    bundle = _spliced_bundle(
        held,
        anchored_events=[_event("wikipedia:en:SQLite", "drifted", observed="cafe1234")],
        orphan_events=[
            _event("wikipedia:en:Ghost", "drifted", observed="beef9999"),
            _event("wikipedia:en:Ghost", "rotted", observed="beef0000"),
            _event("arxiv:2401.00001", "drifted", observed="dead0001"),
        ],
    )
    bundle_path = tmp_path / "spliced.md"
    bundle_path.write_text(bundle, encoding="utf-8")

    capsys.readouterr()
    rc = main(["import", "bundle", str(bundle_path)])
    captured = capsys.readouterr()
    assert rc == 0
    report = json.loads(captured.out)
    # the summary's `orphaned` is the *event* count (3 orphan events)…
    assert report["events"]["orphaned"] == 3
    warning = json.loads(captured.err)["warning"]
    # …and the warning leads with that same event count
    assert warning.startswith("3 orphan custody event(s)")
    # both distinct missing items are named
    assert "arxiv:2401.00001" in warning
    assert "wikipedia:en:Ghost" in warning
    # the doubly-orphaned item is named exactly once — the id list is the
    # *distinct-item* count (2), not the event count (3)
    assert warning.count("wikipedia:en:Ghost") == 1
    # no dangling ledger rows for either orphaned item
    assert item_events(db, "wikipedia:en:Ghost") == []
    assert item_events(db, "arxiv:2401.00001") == []


def test_import_bundle_orphan_warning_bounds_the_id_list(scrolls_home, tmp_path, capsys):
    # H225: the named-id list is bounded with a `(+N more)` tail (the readable-surface
    # idiom) so a badly-spliced bundle naming many missing items can't blow up stderr.
    from scrolls.cli import _MAX_ORPHAN_ITEM_IDS

    main(["init"])
    held = make_item("wikipedia:en:SQLite", "SQLite", "A database engine.")
    overflow = _MAX_ORPHAN_ITEM_IDS + 2
    orphans = [
        _event(f"web:orphan-{i}", "drifted", observed=f"dead{i:04d}")
        for i in range(overflow)
    ]
    bundle = _spliced_bundle(held, anchored_events=[], orphan_events=orphans)
    bundle_path = tmp_path / "spliced.md"
    bundle_path.write_text(bundle, encoding="utf-8")

    capsys.readouterr()
    assert main(["import", "bundle", str(bundle_path)]) == 0
    warning = json.loads(capsys.readouterr().err)["warning"]
    # the leading count is the full event count, even though the list is capped
    assert warning.startswith(f"{overflow} orphan custody event(s)")
    # exactly `_MAX_ORPHAN_ITEM_IDS` ids are named, then a "(+2 more)" tail
    assert warning.count("`web:orphan-") == _MAX_ORPHAN_ITEM_IDS
    assert f"(+{overflow - _MAX_ORPHAN_ITEM_IDS} more)" in warning
    # the named ids are the lexicographically-first ones; the tail covers the rest
    assert "`web:orphan-0`" in warning
    assert f"`web:orphan-{overflow - 1}`" not in warning


def test_import_bundle_reports_zero_orphans_when_every_event_resolves(
    scrolls_home, tmp_path, capsys
):
    # the honest-zero case: a normal bundle's events all resolve, so the summary
    # affirmatively states `orphaned: 0` — absence stated, never silently omitted
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite", "A database engine."))
    record_events(db, [_event("wikipedia:en:SQLite", "drifted", observed="cafe1234")])
    capsys.readouterr()
    main(["export", "bundle", "database"])
    bundle_path = tmp_path / "clean.md"
    bundle_path.write_text(capsys.readouterr().out, encoding="utf-8")

    capsys.readouterr()
    main(["import", "bundle", str(bundle_path)])
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["events"]["orphaned"] == 0
    # the structured id list is affirmatively empty too — "we checked, none
    # dangled" stated, never silently omitted (H230, the M2 ethos)
    assert report["events"]["orphaned_items"] == []
    # no orphans → no warning noise on stderr
    assert captured.err == ""


def test_import_bundle_summary_names_which_items_orphaned(
    scrolls_home, tmp_path, capsys
):
    # H230: the machine-readable half of H225. An agent piping `import bundle`
    # *stdout* sees only the `events.orphaned` count; to learn *which* items dangle
    # it would otherwise have to scrape the human warning prose off stderr. The
    # summary now carries `events.orphaned_items` — the distinct orphan `item_id`s
    # (sorted, deduped) — beside the count, on both the live import and the
    # `--dry-run` preview, the same set the H225 warning names.
    main(["init"])
    held = make_item("wikipedia:en:SQLite", "SQLite", "A database engine.")
    bundle = _spliced_bundle(
        held,
        anchored_events=[_event("wikipedia:en:SQLite", "drifted", observed="cafe1234")],
        orphan_events=[
            _event("wikipedia:en:Ghost", "drifted", observed="beef9999"),
            _event("wikipedia:en:Ghost", "rotted", observed="beef0000"),
            _event("arxiv:2401.00001", "drifted", observed="dead0001"),
        ],
    )
    bundle_path = tmp_path / "spliced.md"
    bundle_path.write_text(bundle, encoding="utf-8")

    # the dry-run preview names the distinct orphan items first (it writes nothing)…
    capsys.readouterr()
    assert main(["import", "bundle", str(bundle_path), "--dry-run"]) == 0
    preview = json.loads(capsys.readouterr().out)
    # …the *count* stays the event count (3 events); the *items* the distinct-item
    # set (2 ids, sorted) — the doubly-orphaned `wikipedia:en:Ghost` named once
    assert preview["events"]["orphaned"] == 3
    assert preview["events"]["orphaned_items"] == [
        "arxiv:2401.00001",
        "wikipedia:en:Ghost",
    ]

    # the live import names the identical set — the structured channel never
    # diverges from the preview (byte-equal `orphaned_items`)
    assert main(["import", "bundle", str(bundle_path)]) == 0
    live = json.loads(capsys.readouterr().out)
    assert live["events"]["orphaned"] == 3
    assert live["events"]["orphaned_items"] == preview["events"]["orphaned_items"]


def test_import_bundle_orphaned_items_is_uncapped_while_the_warning_bounds(
    scrolls_home, tmp_path, capsys
):
    # H230: the structured `orphaned_items` carries the *complete* loss — every
    # distinct orphan id — even when the human stderr warning caps its named list
    # with a `(+N more)` tail. Structured completeness vs. human readability (M2):
    # a programmatic consumer gets the full diagnosable set, the operator a bounded
    # one. The cap is a stderr-prose concern, never a structured-field truncation.
    from scrolls.cli import _MAX_ORPHAN_ITEM_IDS

    main(["init"])
    held = make_item("wikipedia:en:SQLite", "SQLite", "A database engine.")
    overflow = _MAX_ORPHAN_ITEM_IDS + 2
    orphans = [
        _event(f"web:orphan-{i}", "drifted", observed=f"dead{i:04d}")
        for i in range(overflow)
    ]
    bundle = _spliced_bundle(held, anchored_events=[], orphan_events=orphans)
    bundle_path = tmp_path / "spliced.md"
    bundle_path.write_text(bundle, encoding="utf-8")

    capsys.readouterr()
    assert main(["import", "bundle", str(bundle_path)]) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    expected = sorted(f"web:orphan-{i}" for i in range(overflow))
    # the structured field lists *every* distinct orphan id, sorted — uncapped
    assert report["events"]["orphaned_items"] == expected
    assert len(report["events"]["orphaned_items"]) == overflow
    # …while the human warning bounds its named list with a `(+N more)` tail —
    # the same set, two different completeness contracts on two channels
    warning = json.loads(captured.err)["warning"]
    assert warning.count("`web:orphan-") == _MAX_ORPHAN_ITEM_IDS
    assert f"(+{overflow - _MAX_ORPHAN_ITEM_IDS} more)" in warning


def test_import_bundle_dry_run_whole_events_block_matches_a_real_import_under_orphans(
    scrolls_home, tmp_path, capsys
):
    # H237: the corrupt-bundle analogue of H220's byte-identity guarantee. H220
    # pins the preview summary byte-equal to the real import's only over a *clean*
    # held/new scope; H230 pins only `orphaned`/`orphaned_items` equal across the
    # two surfaces. The untested cell is the *whole* `events` block —
    # `{imported, skipped, orphaned, orphaned_items}`, including the resolvable-event
    # accounting — over a corrupt, orphan-bearing bundle. It matters because the two
    # surfaces run **different** functions: the dry-run counts events via
    # `preview_import_events`, the live import via `import_events`, so their agreement
    # on `{imported, skipped}` *in the presence of partitioned-out orphans* is a
    # genuine cross-implementation guarantee, not the same code twice.
    main(["init"])
    db = get_paths().db_path
    held = make_item("wikipedia:en:SQLite", "SQLite", "A database engine.")
    # anchored events on the in-scope item resolve (it rides the items block, so the
    # live import inserts it and the dry-run anchors it via `known_ids`). A
    # within-bundle *duplicate* of the first anchored event forces a non-trivial
    # resolvable split — imported 2 (the two distinct identities), skipped 1 (the
    # dup) — so the block exercises the `{imported, skipped}` accounting, not just a
    # bare `imported`. Orphan events for two missing items (one doubly-orphaned)
    # partition out: orphaned 3 (events), orphaned_items 2 (distinct ids).
    dup_anchor = _event("wikipedia:en:SQLite", "drifted", observed="cafe1234")
    bundle = _spliced_bundle(
        held,
        anchored_events=[
            dup_anchor,
            dup_anchor,  # within-bundle duplicate → skipped by the content dedup
            _event("wikipedia:en:SQLite", "rotted", observed="beef0000"),
        ],
        orphan_events=[
            _event("wikipedia:en:Ghost", "drifted", observed="beef9999"),
            _event("wikipedia:en:Ghost", "rotted", observed="beef0000"),
            _event("arxiv:2401.00001", "drifted", observed="dead0001"),
        ],
    )
    bundle_path = tmp_path / "spliced.md"
    bundle_path.write_text(bundle, encoding="utf-8")

    # dry-run first — it writes nothing, so the live import below sees the same
    # empty-ledger library and its counts are a like-for-like comparison
    capsys.readouterr()
    assert main(["import", "bundle", str(bundle_path), "--dry-run"]) == 0
    preview = json.loads(capsys.readouterr().out)
    # the preview is non-trivial in *every* field — not a vacuous all-zero block:
    # the resolvable accounting (imported 2, skipped 1) rides beside the orphan loss
    expected_events = {
        "imported": 2,
        "skipped": 1,
        "orphaned": 3,
        "orphaned_items": ["arxiv:2401.00001", "wikipedia:en:Ghost"],
    }
    assert preview["events"] == expected_events
    # the preview truly wrote nothing — neither the anchored item nor any event
    assert get_item(db, "wikipedia:en:SQLite") is None
    assert item_events(db, "wikipedia:en:SQLite") == []
    assert item_events(db, "wikipedia:en:Ghost") == []

    # now the real import into the same library: its *entire* events block equals
    # the preview's — the byte-identity H220 guarantees over a clean scope, here
    # held over a corrupt, orphan-bearing bundle. Strictly stronger than H230's
    # two-field (`orphaned`/`orphaned_items`) cross-surface tie: this also pins the
    # resolvable-event accounting (`imported`/`skipped`), the part each surface
    # computes through a *different* function.
    assert main(["import", "bundle", str(bundle_path)]) == 0
    live = json.loads(capsys.readouterr().out)
    assert live["events"] == preview["events"]
    assert live["events"] == expected_events
    # the live import did anchor the two distinct resolvable events (not the dup),
    # never the orphans — the counts the matching block reported are real on disk
    assert sorted(e.status for e in item_events(db, "wikipedia:en:SQLite")) == [
        "drifted",
        "rotted",
    ]
    assert item_events(db, "wikipedia:en:Ghost") == []
    assert item_events(db, "arxiv:2401.00001") == []


# --- import bundle --dry-run preview (roadmap H220) ------------------------


def _export_bundle_to(tmp_path, capsys, name="briefing.md"):
    """Capture `export bundle database` to a file; return its path."""
    capsys.readouterr()
    assert main(["export", "bundle", "database"]) == 0
    bundle_path = tmp_path / name
    bundle_path.write_text(capsys.readouterr().out, encoding="utf-8")
    return bundle_path


def test_import_bundle_dry_run_previews_without_writing(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    # H220: an agent handed a portable bundle can preview what a merge would add
    # before committing to it — and the preview writes *nothing*. The events of a
    # not-yet-held bundle item still resolve (the live import inserts the items
    # first), so a fresh-library preview never mis-flags them as orphans.
    main(["init"])
    db_a = get_paths().db_path
    insert_item(db_a, make_item("wikipedia:en:SQLite", "SQLite", "A database engine."))
    record_events(db_a, [_event("wikipedia:en:SQLite", "drifted", observed="cafe1234")])
    bundle_path = _export_bundle_to(tmp_path, capsys)

    # a fresh, empty library B
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()

    assert main(["import", "bundle", str(bundle_path), "--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True
    assert report["imported"] == 1 and report["skipped"] == 0
    # the event resolves to the would-be-imported item, not an orphan
    assert report["events"] == {
        "imported": 1, "skipped": 0, "orphaned": 0, "orphaned_items": [],
    }
    # nothing was written — the preview is a pure read
    assert get_item(db_b, "wikipedia:en:SQLite") is None
    assert item_events(db_b, "wikipedia:en:SQLite") == []


def test_import_bundle_dry_run_counts_match_a_real_import(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    # the strongest guarantee: the preview never lies — its summary equals what a
    # real import would print (sans the `dry_run` flag), over a non-trivial mix of
    # a freshly-imported item and an already-held one, with events for both.
    main(["init"])
    db_a = get_paths().db_path
    insert_item(db_a, make_item("wikipedia:en:SQLite", "SQLite", "A database engine."))
    insert_item(db_a, make_item(
        "arxiv:1706.03762", "Attention", "A database-adjacent attention paper.",
        source="arxiv", url="https://arxiv.org/abs/1706.03762",
    ))
    record_events(db_a, [
        _event("wikipedia:en:SQLite", "drifted", observed="cafe1234"),
        _event("arxiv:1706.03762", "unchanged", observed="deadbeef"),
    ])
    bundle_path = _export_bundle_to(tmp_path, capsys)

    # library B already holds one of the two scrolls (no events yet)
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    insert_item(db_b, make_item("wikipedia:en:SQLite", "SQLite", "A database engine."))
    capsys.readouterr()

    # dry-run first: imported 1 (arxiv), skipped 1 (the held SQLite); both events
    # resolve (SQLite is held, arxiv is a would-be import) and are new to B
    assert main(["import", "bundle", str(bundle_path), "--dry-run"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview == {
        "dry_run": True,
        "imported": 1,
        "skipped": 1,
        "items": 2,
        # the reviewable id lists (H226) — dry-run-only, alongside `dry_run`
        "new": ["arxiv:1706.03762"],
        "held": ["wikipedia:en:SQLite"],
        "events": {
            "imported": 2, "skipped": 0, "orphaned": 0, "orphaned_items": [],
        },
    }

    # the dry-run wrote nothing — B still holds only the one pre-seeded scroll
    assert get_item(db_b, "arxiv:1706.03762") is None
    assert item_events(db_b, "wikipedia:en:SQLite") == []

    # now the real import, into the same B: its counts equal the preview's. The
    # `new`/`held` review lists are dry-run-only (H226), stripped alongside
    # `dry_run` — the *counts* byte-identity guarantee (H220) is what's pinned here.
    _DRY_RUN_ONLY = {"dry_run", "new", "held"}
    assert main(["import", "bundle", str(bundle_path)]) == 0
    real = json.loads(capsys.readouterr().out)
    assert {k: v for k, v in preview.items() if k not in _DRY_RUN_ONLY} == real
    # the real import stays terse — no reviewable id lists
    assert "new" not in real and "held" not in real


def test_import_bundle_dry_run_previews_orphan_events(
    scrolls_home, tmp_path, capsys
):
    # the preview is honest about a corrupt bundle too (H217 ride-along): an orphan
    # event is counted and warned in the preview exactly as the real import would —
    # and, being a dry-run, nothing at all is written, not even the anchored item.
    main(["init"])
    db = get_paths().db_path
    held = make_item("wikipedia:en:SQLite", "SQLite", "A database engine.")
    bundle = _spliced_bundle(
        held,
        anchored_events=[_event("wikipedia:en:SQLite", "drifted", observed="cafe1234")],
        orphan_events=[_event("wikipedia:en:Ghost", "drifted", observed="beef9999")],
    )
    bundle_path = tmp_path / "spliced.md"
    bundle_path.write_text(bundle, encoding="utf-8")

    capsys.readouterr()
    assert main(["import", "bundle", str(bundle_path), "--dry-run"]) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["dry_run"] is True
    # the anchored item would import; its event resolves; the ghost event orphans
    assert report["imported"] == 1
    assert report["events"] == {
        "imported": 1, "skipped": 0, "orphaned": 1,
        "orphaned_items": ["wikipedia:en:Ghost"],
    }
    # the orphan is loud in the preview, just as in a real import
    assert "orphan" in captured.err.lower()
    # …but the preview wrote nothing — not the item, not its event
    assert get_item(db, "wikipedia:en:SQLite") is None
    assert item_events(db, "wikipedia:en:SQLite") == []
    assert item_events(db, "wikipedia:en:Ghost") == []


def test_import_bundle_dry_run_names_which_items_are_new_vs_held(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    # H226: the *reviewable* half of H220. The preview's counts say how much a merge
    # would change (`imported: 1, skipped: 1`); the operator also needs to know
    # *what* — which scrolls are new vs. already held — to confirm the bundle adds
    # what they expect before committing. The dry-run summary names the would-be-
    # imported ids under `new` and the already-held ids under `held` (each sorted +
    # deduped); the real import stays terse.
    main(["init"])
    db_a = get_paths().db_path
    insert_item(db_a, make_item("wikipedia:en:SQLite", "SQLite", "A database engine."))
    insert_item(db_a, make_item(
        "arxiv:1706.03762", "Attention", "A database-adjacent attention paper.",
        source="arxiv", url="https://arxiv.org/abs/1706.03762",
    ))
    bundle_path = _export_bundle_to(tmp_path, capsys)

    # library B already holds the SQLite scroll; the arxiv paper would be new
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    insert_item(
        get_paths().db_path,
        make_item("wikipedia:en:SQLite", "SQLite", "A database engine."),
    )
    capsys.readouterr()

    assert main(["import", "bundle", str(bundle_path), "--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out)
    # the new id is named under `new`, the already-held under `held`
    assert report["new"] == ["arxiv:1706.03762"]
    assert report["held"] == ["wikipedia:en:SQLite"]
    # each reviewable list's length equals its count (no within-bundle dups here)
    assert len(report["new"]) == report["imported"]
    assert len(report["held"]) == report["skipped"]
    # the lists are sorted (the deduped, ordered review surface)
    assert report["new"] == sorted(report["new"])
    assert report["held"] == sorted(report["held"])


def _items_only_bundle(items):
    """A bundle whose custody block is exactly `items` — within-bundle duplicate
    ids included, with an empty events block.

    A *well-formed* export never repeats an item id (`_gather_scope` returns
    distinct rows), so a repeat only arises from a concat/splice of two
    overlapping exports. We render the real block builders so the ADR 0102
    sentinels and code fences stay valid and only the items *content* carries
    the dup — exactly what `parse_bundle` appends without deduping.
    """
    from scrolls.bundle import _events_block, _items_block

    return (
        "# Scrolls Custody Bundle: spliced\n\n"
        + _items_block(items)
        + "\n"
        + _events_block([])
        + "\n"
    )


def test_import_bundle_dry_run_dedups_new_and_held_under_within_bundle_dup_ids(
    scrolls_home, tmp_path, capsys
):
    # H233: the *dedup* half of H226. H226's `new`/`held` are deduped sets and
    # `len(new) == imported` holds by construction over a well-formed bundle; this
    # pins the corrupt case a naive id-list would phantom-inflate — a spliced
    # bundle whose custody block *repeats* both a would-be-new id and an already-
    # held id (`parse_bundle` appends every record without deduping, bundle.py:667,
    # so the dups reach the preview). The reviewable surface names each distinct id
    # exactly once — never over-claiming more items than the bundle holds (the M2
    # ethos on the dedup axis) — while `imported`/`skipped` keep counting the raw
    # occurrences, exactly what a real INSERT OR IGNORE import would report.
    new = make_item(
        "arxiv:1706.03762", "Attention", "An attention paper.",
        source="arxiv", url="https://arxiv.org/abs/1706.03762",
    )
    held = make_item("wikipedia:en:SQLite", "SQLite", "A database engine.")
    # the corrupt bundle: each id appears twice in the items block
    bundle_path = tmp_path / "spliced.md"
    bundle_path.write_text(
        _items_only_bundle([new, new, held, held]), encoding="utf-8"
    )

    # the library already holds the SQLite scroll; the arxiv paper would be new
    main(["init"])
    insert_item(get_paths().db_path, held)
    capsys.readouterr()

    assert main(["import", "bundle", str(bundle_path), "--dry-run"]) == 0
    preview = json.loads(capsys.readouterr().out)

    # the reviewable lists name each distinct id exactly once — never inflated by
    # the within-bundle repeat (a naive id-list would yield two entries each)
    assert preview["new"] == ["arxiv:1706.03762"]
    assert preview["held"] == ["wikipedia:en:SQLite"]
    # the distinguishing asymmetry: `len(new) == imported` survives the duplicate
    # (the count is the distinct-new count)…
    assert len(preview["new"]) == preview["imported"] == 1
    # …while `len(held) < skipped` (the held-id repeat is skipped twice but named
    # once, and the dup-new also counts a skip): named distinct, counted raw
    assert len(preview["held"]) < preview["skipped"]
    # `items`/`imported`/`skipped` count the raw occurrences (4 items: 1 new + 3
    # skips), so the reviewable surface never claims more distinct items than held
    assert preview["items"] == 4
    assert (preview["imported"], preview["skipped"]) == (1, 3)

    # …and those raw counts are exactly what a *real* import of the same corrupt
    # bundle reports — the dry-run never drifts from reality, even under dups
    capsys.readouterr()
    assert main(["import", "bundle", str(bundle_path)]) == 0
    live = json.loads(capsys.readouterr().out)
    assert (live["imported"], live["skipped"]) == (preview["imported"], preview["skipped"])
    # the real import stays terse — no reviewable id lists
    assert "new" not in live and "held" not in live


def test_import_bundle_dry_run_new_and_held_partition_the_distinct_bundle_ids(
    scrolls_home, tmp_path, capsys
):
    # H239: the *completeness complement* of H233's dedup. H233 pins that each
    # reviewable list dedups (no list over-claims a within-bundle repeat); the
    # missing guarantee is that *together* `new`/`held` account for every distinct
    # id the bundle holds, exactly once — `set(new) ∪ set(held)` equals the bundle's
    # distinct ids and `set(new) ∩ set(held) == ∅`. Without it a preview could
    # silently drop an id from review (in neither list — invisible to the operator
    # confirming the merge) or double-count it (in both — a contradiction, since an
    # id is either already held or not). This is the M2 completeness ethos on the
    # reviewable-partition axis: nothing the merge touches is invisible to review,
    # nothing reviewed twice.
    new1 = make_item(
        "arxiv:1706.03762", "Attention", "An attention paper.",
        source="arxiv", url="https://arxiv.org/abs/1706.03762",
    )
    new2 = make_item(
        "arxiv:2401.00001", "Vectors", "A vector-index paper.",
        source="arxiv", url="https://arxiv.org/abs/2401.00001",
    )
    held = make_item("wikipedia:en:SQLite", "SQLite", "A database engine.")
    # a mixed, corrupt bundle: would-be-new ids + an already-held id, each with a
    # within-bundle repeat (parse_bundle appends every record without deduping,
    # bundle.py:667, so the dups reach the preview)
    bundle_items = [new1, new1, new2, held, held]
    bundle_path = tmp_path / "spliced.md"
    bundle_text = _items_only_bundle(bundle_items)
    bundle_path.write_text(bundle_text, encoding="utf-8")

    # the distinct ids the bundle actually holds, computed independently via the
    # same parse path the import uses (parse_bundle keeps every record, so the set
    # collapses the within-bundle dups) — the partition target, not a hardcode
    distinct_bundle_ids = {item.id for item in parse_bundle(bundle_text)}
    assert distinct_bundle_ids == {
        "arxiv:1706.03762", "arxiv:2401.00001", "wikipedia:en:SQLite",
    }

    # the library already holds the SQLite scroll; both arxiv papers would be new
    main(["init"])
    insert_item(get_paths().db_path, held)
    capsys.readouterr()

    assert main(["import", "bundle", str(bundle_path), "--dry-run"]) == 0
    preview = json.loads(capsys.readouterr().out)

    # the partition: together the two lists name every distinct id exactly once…
    assert sorted(preview["new"] + preview["held"]) == sorted(distinct_bundle_ids)
    # …and never the same id twice (an id is either already held or not — disjoint)
    assert set(preview["new"]).isdisjoint(preview["held"])
    # concretely, the new ids land under `new`, the already-held id under `held`
    assert preview["new"] == ["arxiv:1706.03762", "arxiv:2401.00001"]
    assert preview["held"] == ["wikipedia:en:SQLite"]

    # mutation: adding one more *distinct* would-be-new id extends `new` by exactly
    # that id, leaves `held` untouched, and grows the union by one — the partition
    # tracks the bundle's distinct set, never a stale snapshot
    new3 = make_item(
        "arxiv:9999.00002", "Graphs", "A graph-index paper.",
        source="arxiv", url="https://arxiv.org/abs/9999.00002",
    )
    bundle_path.write_text(
        _items_only_bundle(bundle_items + [new3]), encoding="utf-8"
    )
    capsys.readouterr()
    assert main(["import", "bundle", str(bundle_path), "--dry-run"]) == 0
    grown = json.loads(capsys.readouterr().out)

    assert set(grown["new"]) == set(preview["new"]) | {"arxiv:9999.00002"}
    assert grown["held"] == preview["held"]  # untouched by the new-id addition
    assert set(grown["new"] + grown["held"]) == distinct_bundle_ids | {"arxiv:9999.00002"}
    # still a clean, exhaustive partition after the mutation
    assert set(grown["new"]).isdisjoint(grown["held"])
    assert sorted(grown["new"] + grown["held"]) == sorted(
        distinct_bundle_ids | {"arxiv:9999.00002"}
    )


def _spliced_items_and_events_bundle(items, *, anchored_events, orphan_events):
    """A bundle corrupt on *both* axes at once (H243): a within-bundle item-dup
    items block (like `_items_only_bundle`) *and* an events block carrying orphans
    beside resolvable events (like `_spliced_bundle`).

    The union of the two single-axis splice helpers. A well-formed export desyncs
    neither block — `_gather_scope` returns distinct rows and `events_for_items`
    scopes events to those rows — so a bundle corrupt on both axes only arises from
    a concat/splice of overlapping exports plus a hand-edit. We render the real
    block builders so the ADR 0102 sentinels and code fences stay valid and only the
    *content* of each block carries its corruption.
    """
    from scrolls.bundle import _events_block, _items_block

    return (
        "# Scrolls Custody Bundle: spliced\n\n"
        + _items_block(items)
        + "\n"
        + _events_block(list(anchored_events) + list(orphan_events))
        + "\n"
    )


def test_import_bundle_dry_run_whole_summary_matches_a_real_import_under_both_corruptions(
    scrolls_home, tmp_path, capsys
):
    # H243: the *both-axes-corrupt* analogue of H220's whole-summary byte-identity.
    # H233 pins the dry-run's item-level {imported, skipped} equal to a real import's
    # under within-bundle *item* dups (empty events); H237 pins the whole `events`
    # block equal under orphan *events* (a single, distinct item). Neither exercises
    # a bundle corrupt on *both* axes simultaneously, where the item-dedup path
    # (new_ids/held_ids sets, the read-only twin of INSERT OR IGNORE) and the
    # event-accounting path (partition_resolvable_events + preview_import_events/
    # import_events) both run over the one parsed bundle. A naive implementation
    # could let one corruption axis perturb the other's count — an orphan-event
    # partition that miscounts items, or an item-dedup that drops a resolvable event.
    # This pins that they don't cross-contaminate: the dry-run's *entire* top-level
    # summary (sans the dry-run-only {dry_run, new, held}) equals the real import's,
    # over a bundle corrupt on both the item-dedup and orphan-event axes at once.
    new = make_item(
        "arxiv:1706.03762", "Attention", "An attention paper.",
        source="arxiv", url="https://arxiv.org/abs/1706.03762",
    )
    held = make_item("wikipedia:en:SQLite", "SQLite", "A database engine.")
    # axis 1 — the items block repeats *both* a would-be-new id and an already-held
    # id (parse_bundle appends every record without deduping, bundle.py:667): 4 raw
    # items → 1 new + 3 skips. axis 2 — the events block carries resolvable events on
    # the held item (with a within-bundle dup → a skipped resolvable event) *beside*
    # orphan events on two missing items (one doubly-orphaned).
    dup_anchor = _event("wikipedia:en:SQLite", "drifted", observed="cafe1234")
    bundle = _spliced_items_and_events_bundle(
        [new, new, held, held],
        anchored_events=[
            dup_anchor,
            dup_anchor,  # within-bundle duplicate → skipped by the content dedup
            _event("wikipedia:en:SQLite", "rotted", observed="beef0000"),
        ],
        orphan_events=[
            _event("wikipedia:en:Ghost", "drifted", observed="beef9999"),
            _event("wikipedia:en:Ghost", "rotted", observed="beef0000"),
            _event("arxiv:2401.00001", "drifted", observed="dead0001"),
        ],
    )
    bundle_path = tmp_path / "spliced.md"
    bundle_path.write_text(bundle, encoding="utf-8")

    # the library already holds the SQLite scroll (so its anchored events resolve on
    # both surfaces); the arxiv paper would be new
    main(["init"])
    db = get_paths().db_path
    insert_item(db, held)
    capsys.readouterr()

    # dry-run first — it writes nothing, so the live import below sees the same
    # library state and the two summaries are a like-for-like comparison
    assert main(["import", "bundle", str(bundle_path), "--dry-run"]) == 0
    preview = json.loads(capsys.readouterr().out)
    # the preview is non-trivial in *both* axes — neither block is a vacuous zero:
    # items {imported 1, skipped 3} from the dup'd items, events {imported 2,
    # skipped 1, orphaned 3} from the dup'd anchors beside the orphans
    expected = {
        "imported": 1,
        "skipped": 3,
        "items": 4,
        "events": {
            "imported": 2,
            "skipped": 1,
            "orphaned": 3,
            "orphaned_items": ["arxiv:2401.00001", "wikipedia:en:Ghost"],
        },
    }
    _DRY_RUN_ONLY = {"dry_run", "new", "held"}
    assert {k: v for k, v in preview.items() if k not in _DRY_RUN_ONLY} == expected
    # the preview truly wrote nothing — not the new item, not any resolvable event
    assert get_item(db, "arxiv:1706.03762") is None
    assert item_events(db, "wikipedia:en:SQLite") == []

    # now the real import into the same library: its *entire* top-level summary
    # equals the dry-run's (sans the dry-run-only fields) — the both-axes-corrupt
    # analogue of H220's whole-summary byte-identity. Strictly the union of H233
    # (the item counts) and H237 (the whole events block) on one bundle, proving the
    # item-dedup axis and the orphan-event axis don't distort each other's accounting.
    assert main(["import", "bundle", str(bundle_path)]) == 0
    live = json.loads(capsys.readouterr().out)
    assert {k: v for k, v in preview.items() if k not in _DRY_RUN_ONLY} == live
    assert live == expected
    # the live import moved exactly what the matching summary reported: the new item
    # inserted, the two distinct resolvable events anchored (not the dup), never the
    # orphans — the counts both surfaces agreed on are real on disk, never silently
    # dropped or phantom-retained
    assert get_item(db, "arxiv:1706.03762") is not None
    assert sorted(e.status for e in item_events(db, "wikipedia:en:SQLite")) == [
        "drifted",
        "rotted",
    ]
    assert item_events(db, "wikipedia:en:Ghost") == []
    assert item_events(db, "arxiv:2401.00001") == []


# --- scope, completeness, honesty ------------------------------------------


def test_bundle_scope_is_self_documenting_and_filters(scrolls_home):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))
    insert_item(db, make_item(
        "arxiv:2401.0001", "Paper", "This paper studies database engines.",
        source="arxiv", url="https://arxiv.org/abs/2401.0001",
    ))

    bundle = build_bundle(db, "database", source="arxiv")
    assert bundle.startswith("# Scrolls Custody Bundle: database (source=arxiv)\n")
    assert "arxiv:2401.0001" in bundle
    # the wikipedia scroll is out of scope — absent from briefing AND block
    assert "wikipedia:en:SQLite" not in bundle


def test_bundle_carries_every_match_not_a_capped_slice(scrolls_home):
    # a custody artifact is complete about its scope: no silent top-N truncation
    main(["init"])
    db = get_paths().db_path
    for index in range(12):
        insert_item(db, make_item(
            f"wikipedia:en:Page_{index}", f"Page {index}",
            "Every page mentions databases.",
        ))

    items = parse_bundle(build_bundle(db, "databases"))
    assert len(items) == 12


def test_empty_scope_yields_a_valid_importable_bundle(scrolls_home, tmp_path, capsys):
    main(["init"])
    capsys.readouterr()
    main(["export", "bundle", "nothingmatcheshere"])
    bundle_text = capsys.readouterr().out
    assert "No matching scrolls." in bundle_text
    # an empty bundle still parses and imports zero — never crashes
    assert parse_bundle(bundle_text) == []
    bundle_path = tmp_path / "empty.md"
    bundle_path.write_text(bundle_text, encoding="utf-8")
    main(["import", "bundle", str(bundle_path)])
    report = json.loads(capsys.readouterr().out)
    assert report["imported"] == 0


def test_export_bundle_before_init_is_a_valid_empty_bundle(scrolls_home, capsys):
    # like `scrolls context`, export never creates a library; the bundle is a
    # valid, importable empty one (it still carries the custody-block markers)
    capsys.readouterr()
    assert main(["export", "bundle", "anything"]) == 0
    out = capsys.readouterr().out
    assert "No matching scrolls." in out
    assert parse_bundle(out) == []
    assert not scrolls_home.exists()


def test_build_bundle_blank_query_is_an_error(scrolls_home):
    main(["init"])
    with pytest.raises(ValueError):
        build_bundle(get_paths().db_path, '""')


def test_parse_bundle_rejects_a_non_bundle(scrolls_home):
    with pytest.raises(BundleError):
        parse_bundle("# Just some markdown\n\nNo custody block here.\n")


def test_import_bundle_reports_a_corrupt_block(scrolls_home, tmp_path, capsys):
    main(["init"])
    bad = tmp_path / "bad.md"
    bad.write_text(
        "# Scrolls Custody Bundle: x\n\n"
        "<!-- @generated scrolls — regenerated by `scrolls export bundle` -->\n"
        "```jsonl\n{not valid json\n```\n"
        "<!-- @end scrolls -->\n",
        encoding="utf-8",
    )
    capsys.readouterr()
    assert main(["import", "bundle", str(bad)]) == 1
    assert "error" in json.loads(capsys.readouterr().err)


# --- HTML briefing (roadmap H39) -------------------------------------------


def test_bundle_html_is_a_self_contained_document(scrolls_home):
    # the human-facing read artifact: a single offline HTML file, no external CSS/JS
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine with full-text search support.",
    ))

    html = build_bundle_html(db, "database engine")
    assert html.startswith("<!DOCTYPE html>")
    assert "<html" in html and "</html>" in html
    # the title carries the query
    assert "<title>Scrolls Custody Bundle: database engine</title>" in html
    # self-contained: styling is inline, nothing fetched from the network
    assert "<style>" in html
    assert "<link" not in html  # no external stylesheet
    assert "<script" not in html  # no scripts at all (and no XSS surface)
    # the scroll and its custody facts render
    assert "SQLite" in html
    assert "wikipedia:en:SQLite" in html
    assert "<code>full</code>" in html  # raw_text + hash + rendered → full tier
    assert "captured 2026-06-12T00:00:00+00:00" in html


def test_bundle_html_carries_drift_posture_and_classification(scrolls_home):
    # the same two custody axes the Markdown briefing carries read in the HTML
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
        category="documentation", provenance=_rules_provenance(),
    ))

    html = build_bundle_html(db, "database engine")
    # never re-checked → the honest unverified posture, stated explicitly
    assert "<code>unverified</code>" in html
    # how the category was derived, via the shared classification phrase
    assert "classified <code>documentation</code> by <code>rules-v1</code>" in html
    assert "confidence deterministic, current" in html


def test_bundle_html_embeds_the_lossless_custody_block(scrolls_home):
    # the custody rows + events travel in the HTML (in <details>/<pre>), so the
    # data is present even though re-import consumes the Markdown form
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))

    html = build_bundle_html(db, "database engine")
    assert "<details" in html and "<pre>" in html
    # the same self-describing fenced JSONL the Markdown bundle carries
    assert "@generated scrolls" in html
    assert "wikipedia:en:SQLite" in html  # the lossless row is present
    # and it says HTML is export-only — Markdown is the canonical re-import unit
    assert "Markdown" in html


def test_bundle_html_escapes_dynamic_content(scrolls_home):
    # custody/security: a tag-bearing title or body must never inject raw HTML
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:XSS", "<script>alert(1)</script>",
        "A body with <b>markup</b> & an ampersand.",
        raw_text="<script>alert(1)</script>",
    ))

    html = build_bundle_html(db, "ampersand")
    # the raw payload is escaped wherever it appears (title, excerpt, custody block)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&amp;" in html  # the ampersand is escaped, not left bare


def test_bundle_html_scope_headline_matches_the_shared_primitive(scrolls_home):
    # the HTML headline content equals the shared custody_headline (sans markdown _)
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))

    db_items = [get_item(db, "wikipedia:en:SQLite")]
    expected = custody_headline(db_items, {}).strip("_")
    html = build_bundle_html(db, "database engine")
    assert expected in html


def test_bundle_html_concept_summary(scrolls_home):
    # a concept-scoped HTML bundle carries the synthesized summary, like Markdown
    main(["init"])
    db = get_paths().db_path
    members = [
        make_item("wikipedia:en:SQLite", "SQLite", "SQLite is a database.",
                  concepts=("Databases",)),
        make_item("wikipedia:en:Postgres", "Postgres", "Postgres is a database.",
                  concepts=("Databases",)),
    ]
    for member in members:
        insert_item(db, member)
    save_concept_summary(db, ConceptSummary(
        slug="databases", display="Databases",
        summary="Databases store and query structured data.",
        members_hash=members_hash(members), engine=SUMMARY_ENGINE,
        model="claude-test", generated_at="2026-06-12T00:00:00+00:00",
    ))

    html = build_bundle_html(db, "database", concept="Databases")
    assert "Databases store and query structured data." in html
    assert "Summary by" in html


def test_bundle_html_empty_scope_is_a_valid_document(scrolls_home):
    # no matches still yields a valid HTML doc — never a crash on an empty scope
    main(["init"])
    db = get_paths().db_path
    html = build_bundle_html(db, "nothingmatcheshere")
    assert html.startswith("<!DOCTYPE html>")
    assert "No matching scrolls." in html


def test_build_bundle_html_blank_query_is_an_error(scrolls_home):
    main(["init"])
    with pytest.raises(ValueError):
        build_bundle_html(get_paths().db_path, '""')


def test_export_bundle_format_html_emits_html(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))
    capsys.readouterr()
    assert main(["export", "bundle", "database", "--format", "html"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("<!DOCTYPE html>")
    assert "wikipedia:en:SQLite" in out


def test_export_bundle_defaults_to_markdown(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))
    capsys.readouterr()
    assert main(["export", "bundle", "database"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Scrolls Custody Bundle: database\n")
    # the Markdown form stays importable (the canonical re-import unit)
    assert [i.id for i in parse_bundle(out)] == ["wikipedia:en:SQLite"]


def test_export_bundle_format_markdown_explicit(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))
    capsys.readouterr()
    assert main(["export", "bundle", "database", "--format", "markdown"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Scrolls Custody Bundle: database\n")


def test_export_bundle_html_before_init_is_a_valid_empty_document(scrolls_home, capsys):
    # like the Markdown form, HTML export never creates a library
    capsys.readouterr()
    assert main(["export", "bundle", "anything", "--format", "html"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("<!DOCTYPE html>")
    assert "No matching scrolls." in out
    assert not scrolls_home.exists()


def test_export_bundle_html_blank_query_is_an_error(scrolls_home, capsys):
    main(["init"])
    capsys.readouterr()
    assert main(["export", "bundle", '""', "--format", "html"]) == 1
    assert "error" in json.loads(capsys.readouterr().err)


# --- the custody-filter family on the portable bundle (H258) -----------------
#
# `scrolls export bundle <query> --fidelity <tier>` / `--drift <posture>` scope
# the shareable bundle to one per-item custody value — the export twin of
# `context --fidelity`/`--drift` (H257), so a custody-scoped briefing travels.
# Both axes thread through `_gather_scope` to the `search_items`/`count_matches`
# SQL sieve (the `search --fidelity`/`--drift` primitives, H251/H253), so the
# briefing prose AND the lossless custody + events blocks describe exactly the
# kept set, and `import bundle` of it re-holds exactly the exported rows (the
# H216 mixed-fidelity round-trip under a custody scope). The bundle carries no
# cap, so the sieve simply narrows the complete set (no before-/after-cap split).


def _seed_custody_scope(db):
    """The mixed-fidelity trio at three distinct drift postures, all in "database".

    Builds on `_mixed_fidelity_scope` (full / partial / reference) and pins one
    drift posture per item so the two custody axes select genuinely different
    subsets: Full→verified, Partial→drifted, Ref→unverified (no event). So
    `--fidelity full` keeps {Full}, `--drift drifted` keeps {Partial}, and
    `--fidelity full --drift drifted` is empty (Full is verified, Partial is
    partial-fidelity) — a clean AND.
    """
    for item in _mixed_fidelity_scope():
        insert_item(db, item)
    record_events(db, [
        _event("wikipedia:en:Full", "unchanged", observed="deadbeef"),
        _event("wikipedia:en:Partial", "drifted", observed="cafe1234"),
        # wikipedia:en:Ref left unverified
    ])


def test_bundle_fidelity_keeps_only_that_tier(scrolls_home):
    # --fidelity full carries exactly the full-fidelity holding, in both the
    # lossless block (parse) and the briefing prose
    main(["init"])
    db = get_paths().db_path
    _seed_custody_scope(db)

    bundle = build_bundle(db, "database", fidelity="full")
    assert [i.id for i in parse_bundle(bundle)] == ["wikipedia:en:Full"]
    # the briefing names only the kept tier
    assert "fidelity `full`" in bundle
    assert "fidelity `partial`" not in bundle
    assert "fidelity `reference`" not in bundle


def test_bundle_drift_keeps_only_that_posture(scrolls_home):
    # --drift drifted carries exactly the moved source — the recapture-handoff
    # slice — and nothing verified or unverified
    main(["init"])
    db = get_paths().db_path
    _seed_custody_scope(db)

    bundle = build_bundle(db, "database", drift="drifted")
    assert [i.id for i in parse_bundle(bundle)] == ["wikipedia:en:Partial"]
    assert "custody `drifted`" in bundle
    assert "custody `verified`" not in bundle
    assert "custody `unverified`" not in bundle


def test_bundle_custody_axes_AND(scrolls_home):
    # the two axes intersect: full ∩ verified keeps the one item at both; full ∩
    # drifted is empty (the full item is verified, the drifted one is partial)
    main(["init"])
    db = get_paths().db_path
    _seed_custody_scope(db)

    both = build_bundle(db, "database", fidelity="full", drift="verified")
    assert [i.id for i in parse_bundle(both)] == ["wikipedia:en:Full"]

    empty = build_bundle(db, "database", fidelity="full", drift="drifted")
    assert parse_bundle(empty) == []
    assert "No matching scrolls." in empty


def test_bundle_custody_scope_is_named_in_the_title(scrolls_home):
    # provenance of *what slice* was shared: the title scope note echoes the
    # active custody value(s) beside any facet echo
    main(["init"])
    db = get_paths().db_path
    _seed_custody_scope(db)

    bundle = build_bundle(db, "database", fidelity="full", drift="verified")
    assert bundle.startswith(
        "# Scrolls Custody Bundle: database (fidelity=full, drift=verified)\n"
    )


def test_bundle_custody_headline_describes_the_kept_set(scrolls_home):
    # the scope custody headline counts only the kept slice, not the whole scope —
    # a scoped briefing must not claim library-wide custody (the M2 honesty the
    # Coverage line gives the match set, here on the custody headline)
    main(["init"])
    db = get_paths().db_path
    _seed_custody_scope(db)

    headline = next(
        line for line in build_bundle(db, "database", fidelity="full").splitlines()
        if line.startswith("_Custody:")
    )
    assert "1 scroll(s)" in headline
    assert "fidelity full 1" in headline
    assert "partial" not in headline and "reference" not in headline


def test_bundle_fidelity_count_converges_with_the_unfiltered_headline(scrolls_home):
    # the convergence invariant (the H257 shape): the --fidelity T bundle holds
    # exactly tier T's share of the *unfiltered* scope headline, because both
    # fold the one `get_fidelity` primitive — the filter selects rows by exactly
    # the value the unfiltered headline counts
    import re

    main(["init"])
    db = get_paths().db_path
    _seed_custody_scope(db)

    unfiltered = next(
        line for line in build_bundle(db, "database").splitlines()
        if line.startswith("_Custody:")
    )
    # the unfiltered headline reports one of each tier
    full_share = int(re.search(r"fidelity .*?full (\d+)", unfiltered).group(1))
    assert full_share == 1

    scoped_items = parse_bundle(build_bundle(db, "database", fidelity="full"))
    assert len(scoped_items) == full_share


def test_bundle_drift_count_converges_with_facets_drift(scrolls_home):
    # the ledger-axis convergence: the --drift P bundle holds exactly `facets
    # drift`'s P count over the same scope — both read `posture_from_status`. The
    # fixture is the whole library and every row matches "database", so the
    # whole-library facet count is the "database"-scope count.
    from scrolls.facets import compute_facets

    main(["init"])
    db = get_paths().db_path
    _seed_custody_scope(db)

    drift_counts = {
        row["value"]: row["count"]
        for row in compute_facets(db, field="drift")["facets"]["drift"]
    }
    scoped = parse_bundle(build_bundle(db, "database", drift="drifted"))
    assert len(scoped) == drift_counts.get("drifted", 0) == 1


def test_bundle_custody_scope_round_trips_losslessly(scrolls_home, monkeypatch, tmp_path, capsys):
    # the take-it-with-me proof under a custody scope: `export bundle --drift
    # drifted` → `import bundle` into a fresh library re-holds exactly the
    # exported (drifted) rows and their custody events — the H216 round-trip
    # narrowed to one posture, with no leakage of the unscoped rows
    main(["init"])
    db_a = get_paths().db_path
    _seed_custody_scope(db_a)
    capsys.readouterr()

    assert main(["export", "bundle", "database", "--drift", "drifted"]) == 0
    bundle_text = capsys.readouterr().out
    bundle_path = tmp_path / "drifted.md"
    bundle_path.write_text(bundle_text, encoding="utf-8")
    # only the drifted row's custody events travel in the scoped bundle
    assert [e.item_id for e in parse_bundle_events(bundle_text)] == ["wikipedia:en:Partial"]

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()

    assert main(["import", "bundle", str(bundle_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["imported"] == 1
    # exactly the scoped row landed; the unscoped rows never travelled
    assert get_item(db_b, "wikipedia:en:Partial") is not None
    assert get_item(db_b, "wikipedia:en:Full") is None
    assert get_item(db_b, "wikipedia:en:Ref") is None


def test_bundle_unknown_custody_value_raises_valueerror(scrolls_home):
    # closed vocabulary on the library path (the belt for the MCP-less programmatic
    # caller; the CLI also rejects via argparse choices) — ValueError, not a
    # silent empty bundle that would read as honest absence
    main(["init"])
    db = get_paths().db_path
    _seed_custody_scope(db)

    with pytest.raises(ValueError):
        build_bundle(db, "database", fidelity="bogus")
    with pytest.raises(ValueError):
        build_bundle(db, "database", drift="bogus")


def test_export_bundle_cli_rejects_unknown_custody_value(scrolls_home):
    # the CLI closed-vocab is argparse `choices` → exit 2 (SystemExit), before the
    # command body runs
    main(["init"])
    with pytest.raises(SystemExit) as exc:
        main(["export", "bundle", "database", "--fidelity", "bogus"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        main(["export", "bundle", "database", "--drift", "bogus"])
    assert exc.value.code == 2


def test_export_bundle_cli_fidelity_end_to_end(scrolls_home, capsys):
    # the CLI path carries the scope through to the rendered bundle
    main(["init"])
    db = get_paths().db_path
    _seed_custody_scope(db)
    capsys.readouterr()

    assert main(["export", "bundle", "database", "--fidelity", "full"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Scrolls Custody Bundle: database (fidelity=full)\n")
    assert [i.id for i in parse_bundle(out)] == ["wikipedia:en:Full"]


def test_bundle_html_custody_scope(scrolls_home):
    # the HTML form shares `_gather_scope`, so it scopes identically and names the
    # custody slice in its heading
    main(["init"])
    db = get_paths().db_path
    _seed_custody_scope(db)

    html_bundle = build_bundle_html(db, "database", fidelity="full")
    assert "Scrolls Custody Bundle: database (fidelity=full)" in html_bundle
    # only the kept full-fidelity row appears as a scroll section
    assert html_bundle.count('<section class="scroll">') == 1
    assert "wikipedia:en:Full" in html_bundle
    assert "wikipedia:en:Partial" not in html_bundle
