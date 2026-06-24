"""Tests for shareable custody bundles (ADR 0103, MVP M4)."""

import dataclasses
import json
import sqlite3

import pytest

from scrolls.bundle import (
    BundleError,
    build_bundle,
    build_bundle_html,
    parse_bundle,
    parse_bundle_archive,
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
from scrolls.items import (
    ScrollItem,
    adopt_incoming,
    archived_records,
    get_item,
    insert_item,
    item_to_dict,
    latest_archived,
    list_archived,
)
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


# --- readable import-conflict `_Conflicts:_` line (roadmap H277) --------------
# The readable completion of H275's JSON `custody.conflicts` aggregate (ADR 0104):
# a one-line conflict-axis counterpart of the drift `_Attention:_` line, on both
# bundle forms and the `context` briefing. A held id whose latest import-conflict's
# incoming hash still disagrees with the held copy is *unresolved* (the held copy is
# never auto-overwritten — raw is sacred); the line surfaces the count, names no
# command (the `reconcile` act is roadmap H276).


def _record_conflict(db, item_id, *, held, incoming):
    """Record an unresolved import-conflict event on a held item (H274 shape)."""
    from scrolls.custody import conflict_event

    record_events(
        db,
        [conflict_event(
            item_id, held_hash=held, incoming_hash=incoming,
            now="2026-06-22T00:00:00+00:00")],
    )


def test_bundle_carries_a_conflicts_line(scrolls_home):
    # roadmap H277: a held item carrying an unresolved import conflict surfaces one
    # `_Conflicts:_` line — the readable completion of H275's `custody.conflicts`.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database", "Body.",
                              content_hash="deadbeef"))
    _record_conflict(db, "wikipedia:en:SQLite", held="deadbeef", incoming="moved")
    bundle = build_bundle(db, "database")
    assert "_Conflicts: 1 item(s) carry an unresolved import conflict._" in bundle
    # grouped with the divergence lines, below the scope custody headline
    assert bundle.index("_Conflicts:") > bundle.index("_Custody:")


def test_conflicts_line_converges_with_doctor(scrolls_home):
    # the line's count is the *same* `unresolved_conflicts` fold `doctor`'s
    # `custody.conflicts` reads, so the readable line and the JSON aggregate can
    # never disagree for the same (whole-library) scope
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database", "B.",
                              content_hash="deadbeef"))
    insert_item(db, make_item("wikipedia:en:Postgres", "Postgres database", "B.",
                              content_hash="deadbeef"))
    _record_conflict(db, "wikipedia:en:SQLite", held="deadbeef", incoming="moved")
    _record_conflict(db, "wikipedia:en:Postgres", held="deadbeef", incoming="moved")
    bundle = build_bundle(db, "database")  # matches both held items
    items = run_doctor(get_paths())["custody"]["conflicts"]["items"]
    assert items == 2
    assert f"_Conflicts: {items} item(s) carry an unresolved import conflict._" in bundle


def test_conflicts_line_omitted_on_a_clean_library(scrolls_home):
    # honest absence: no recorded conflict → no `_Conflicts:` line (the no-op shape)
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database", "Body."))
    bundle = build_bundle(db, "database")
    assert "_Custody:" in bundle
    assert "_Conflicts:" not in bundle


def test_conflicts_line_is_resolution_aware(scrolls_home):
    # a conflict whose latest incoming hash equals the held copy's current
    # content_hash is *resolved* — the resolution-aware predicate (H275) drops it, so
    # the line is honestly absent (the future `reconcile` H276 clears it for free)
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database", "Body.",
                              content_hash="deadbeef"))
    # the recorded incoming hash now matches the held copy → no longer a divergence
    _record_conflict(db, "wikipedia:en:SQLite", held="older", incoming="deadbeef")
    bundle = build_bundle(db, "database")
    assert "_Conflicts:" not in bundle


def test_conflicts_line_preserves_the_round_trip(scrolls_home):
    # the line is a derived read view *outside* the @generated JSONL fence, so the
    # lossless round-trip is untouched (the H264/H159 derived-view invariant)
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database", "Body.",
                              content_hash="deadbeef"))
    _record_conflict(db, "wikipedia:en:SQLite", held="deadbeef", incoming="moved")
    bundle = build_bundle(db, "database")
    assert "_Conflicts:" in bundle
    assert [i.id for i in parse_bundle(bundle)] == ["wikipedia:en:SQLite"]


def test_bundle_html_carries_a_conflicts_line(scrolls_home):
    # roadmap H277: the HTML briefing carries the same conflict pointer as the
    # Markdown `_Conflicts:_` line, from the *same* `unresolved_conflicts` fold —
    # so the two readable forms (and `doctor`'s JSON) cannot desync
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database", "Body.",
                              content_hash="deadbeef"))
    _record_conflict(db, "wikipedia:en:SQLite", held="deadbeef", incoming="moved")
    doc = build_bundle_html(db, "database")
    assert (
        '<p class="custody-conflicts">Conflicts: 1 '
        "item(s) carry an unresolved import conflict.</p>" in doc
    )


def test_bundle_html_conflicts_line_omitted_on_a_clean_library(scrolls_home):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database", "Body."))
    doc = build_bundle_html(db, "database")
    assert "Custody:" in doc  # the headline still renders
    assert '<p class="custody-conflicts">' not in doc
    # empty scope is a no-op too
    assert '<p class="custody-conflicts">' not in build_bundle_html(
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
        # the held SQLite is re-imported with the *same* content — an idempotent
        # no-op (`unchanged`), not a `conflict` (H273)
        "unchanged": 1,
        "conflict": 0,
        "adopted": [],
        "conflicts": [],
        "items": 2,
        # the reviewable id lists (H226) — dry-run-only, alongside `dry_run`
        "new": ["arxiv:1706.03762"],
        "held": ["wikipedia:en:SQLite"],
        "events": {
            "imported": 2, "skipped": 0, "orphaned": 0, "orphaned_items": [],
        },
        # a lean default bundle (no `--with-archive`) carries no archive block —
        # the honest "we checked, none travelled" (H280)
        "archive": {"imported": 0, "skipped": 0},
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
        # every skip here re-imports the *same* content (the dup'd new id and the
        # dup'd held id all share the default `content_hash`), so all three are
        # idempotent `unchanged` no-ops, none a `conflict` (H273)
        "unchanged": 3,
        "conflict": 0,
        "adopted": [],
        "conflicts": [],
        "items": 4,
        "events": {
            "imported": 2,
            "skipped": 1,
            "orphaned": 3,
            "orphaned_items": ["arxiv:2401.00001", "wikipedia:en:Ghost"],
        },
        "archive": {"imported": 0, "skipped": 0},
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


# --- import bundle conflict-on-import (roadmap H273) -----------------------
# The H272 partition (`merge_item`/`_merge_items`/`_warn_conflicts`) lifted to the
# bundle importer: a held id re-imported from a bundle with a *different*
# `content_hash` is a surfaced `conflict`, never a silent `skipped` — and the
# `--dry-run` *predicts* the conflict set the live import would surface (the
# H233/H239 "the preview never drifts from reality" discipline on the conflict
# axis). The held copy is never overwritten (raw is sacred; a conflict is a
# recorded, surfaced event — custody vision §2.4).


def test_import_bundle_surfaces_a_content_conflict(scrolls_home, tmp_path, capsys):
    # the live importer no longer lumps a divergent held id into an opaque
    # `skipped`: a bundle whose copy of a held id carries a different
    # `content_hash` (a peer's capture of a source that has since drifted) is
    # surfaced as a `conflict`, with a loud stderr warning — and the held copy is
    # kept byte-for-byte (never overwritten).
    main(["init"])
    db = get_paths().db_path
    # the library holds the original capture…
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "The original capture.",
        content_hash="sha256:held",
    ))
    # …the bundle carries a divergent capture of the *same id* (different content)
    divergent = make_item(
        "wikipedia:en:SQLite", "SQLite", "A different, later capture.",
        content_hash="sha256:moved",
    )
    bundle_path = tmp_path / "incoming.md"
    bundle_path.write_text(_items_only_bundle([divergent]), encoding="utf-8")
    capsys.readouterr()

    assert main(["import", "bundle", str(bundle_path)]) == 0
    out, err = capsys.readouterr()
    report = json.loads(out)
    # imported nothing, the lone skip partitioned into a surfaced conflict
    assert report["imported"] == 0
    assert report["skipped"] == 1
    assert report["unchanged"] == 0
    assert report["conflict"] == 1
    assert report["conflicts"] == ["wikipedia:en:SQLite"]
    # the held copy is preserved — surfaced, never overwritten (raw is sacred)
    kept = get_item(db, "wikipedia:en:SQLite")
    assert kept.content_hash == "sha256:held"
    assert kept.extracted_text == "The original capture."
    # loud, not silent: the stderr warning names the diverging id (the
    # `_warn_conflicts` idiom, the bundle twin of `import items`' H272 warning)
    warning = json.loads(err)
    assert "wikipedia:en:SQLite" in warning["warning"]
    assert "conflict" in warning["warning"].lower()


def test_import_bundle_accept_incoming_adopts_and_archives(scrolls_home, tmp_path, capsys):
    # H278: `import bundle --accept-incoming` adopts a peer's diverging capture — the
    # held copy is replaced by the bundle's, the prior archived (recoverable, never
    # destroyed), recorded as a `superseded` event that clears the conflict surfaces.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "The original capture.",
        content_hash="sha256:held",
    ))
    divergent = make_item(
        "wikipedia:en:SQLite", "SQLite", "A different, later capture.",
        content_hash="sha256:moved",
    )
    bundle_path = tmp_path / "incoming.md"
    bundle_path.write_text(_items_only_bundle([divergent]), encoding="utf-8")
    capsys.readouterr()

    assert main(["import", "bundle", str(bundle_path), "--accept-incoming"]) == 0
    out, err = capsys.readouterr()
    report = json.loads(out)
    assert report["adopted"] == ["wikipedia:en:SQLite"]
    assert report["conflict"] == 0 and report["conflicts"] == []
    # the held copy now carries the bundle's content (the adoption happened)
    adopted = get_item(db, "wikipedia:en:SQLite")
    assert adopted.content_hash == "sha256:moved"
    assert adopted.extracted_text == "A different, later capture."
    # …recorded as a `superseded` event; the prior is archived, recoverable
    assert [e.status for e in item_events(db, "wikipedia:en:SQLite")] == ["superseded"]
    recovered = latest_archived(db, "wikipedia:en:SQLite")
    assert recovered.content_hash == "sha256:held"
    assert recovered.extracted_text == "The original capture."
    # the conflict aggregate clears (both gates agree) — never on the drift axis
    report_doctor = run_doctor(get_paths(), fix=False)
    assert report_doctor["custody"]["conflicts"]["items"] == 0
    assert report_doctor["custody"]["drift"]["checked"] == 0
    # loud on stderr — a held copy was replaced
    assert "wikipedia:en:SQLite" in json.loads(err)["warning"]


def test_import_bundle_dry_run_accept_incoming_predicts_without_writing(
    scrolls_home, tmp_path, capsys
):
    # the predict-the-write discipline (H245/H273) on the adopt axis: the dry-run
    # names the held→incoming adoption set under `adopted` yet writes nothing, and
    # the live run then adopts exactly that set.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "The original capture.",
        content_hash="sha256:held",
    ))
    divergent = make_item(
        "wikipedia:en:SQLite", "SQLite", "A different, later capture.",
        content_hash="sha256:moved",
    )
    bundle_path = tmp_path / "incoming.md"
    bundle_path.write_text(_items_only_bundle([divergent]), encoding="utf-8")
    capsys.readouterr()

    assert main(
        ["import", "bundle", str(bundle_path), "--accept-incoming", "--dry-run"]
    ) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["dry_run"] is True
    assert preview["adopted"] == ["wikipedia:en:SQLite"]
    assert preview["conflict"] == 0 and preview["conflicts"] == []
    # nothing written — the held copy is byte-for-byte untouched, no archive, no event
    assert get_item(db, "wikipedia:en:SQLite").content_hash == "sha256:held"
    assert list_archived(db, "wikipedia:en:SQLite") == []
    assert item_events(db, "wikipedia:en:SQLite") == []

    # the live run adopts exactly what the preview predicted
    assert main(["import", "bundle", str(bundle_path), "--accept-incoming"]) == 0
    live = json.loads(capsys.readouterr().out)
    assert live["adopted"] == preview["adopted"]
    assert get_item(db, "wikipedia:en:SQLite").content_hash == "sha256:moved"
    assert [e.status for e in item_events(db, "wikipedia:en:SQLite")] == ["superseded"]


# --- the prior-content archive travels in the portable bundle (H280) ---------


def _seed_archived_prior(db, item_id="wikipedia:en:SQLite", *, query_token="database"):
    """Hold an item, then adopt a divergent capture so one prior is archived.

    Leaves the held copy carrying the incoming content and one recoverable prior
    in `item_archive` — the recovery store the `--with-archive` bundle carries.
    Both captures keep `query_token` in their text so the item stays in the bundle
    scope a query of that token selects.
    """
    held = make_item(item_id, "SQLite", f"The original {query_token} capture.",
                     content_hash="sha256:held")
    insert_item(db, held)
    incoming = dataclasses.replace(
        held, extracted_text=f"A later {query_token} capture.",
        raw_text=f"<raw>A later {query_token} capture.</raw>",
        content_hash="sha256:moved",
    )
    adopt_incoming(db, incoming, archived_at="2026-06-22T00:00:00+00:00")
    return held  # the archived prior, recoverable byte-for-byte


def test_default_bundle_carries_no_archive_block(scrolls_home):
    # the lean default (H280): without `--with-archive` the bundle has exactly the
    # two regions (items, events) a pre-H280 bundle had — so the byte-identity /
    # round-trip guarantees are untouched, and `parse_bundle_archive` reads []
    main(["init"])
    db = get_paths().db_path
    _seed_archived_prior(db)

    bundle = build_bundle(db, "database")
    assert bundle.count("@generated scrolls") == 2  # items + events only
    assert "prior-content archive" not in bundle
    assert parse_bundle_archive(bundle) == []  # nothing to recover


def test_with_archive_bundle_carries_the_scoped_prior_captures(scrolls_home):
    # the opt-in third region (H280): `--with-archive` appends the in-scope items'
    # recovery store, recoverable via `parse_bundle_archive` byte-for-byte
    main(["init"])
    db = get_paths().db_path
    prior = _seed_archived_prior(db)

    bundle = build_bundle(db, "database", with_archive=True)
    assert bundle.count("@generated scrolls") == 3  # items + events + archive
    assert "prior-content archive" in bundle
    recovered = parse_bundle_archive(bundle)
    assert recovered == archived_records(db)  # the same records the store holds
    assert len(recovered) == 1
    assert recovered[0].item_id == "wikipedia:en:SQLite"
    assert recovered[0].prior_hash == "sha256:held"
    # the snapshot recovers the prior capture byte-for-byte
    from scrolls.items import item_from_dict
    assert item_from_dict(recovered[0].snapshot) == prior


def test_with_archive_bundle_round_trips_the_recovery_store_to_a_fresh_library(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    # the heart of H280: "take it with me" includes the recovery store, so a library
    # rebuilt from a `--with-archive` bundle can recover the prior bytes — not just
    # read *that* an adoption happened (the `superseded` event)
    main(["init"])
    db_a = get_paths().db_path
    prior = _seed_archived_prior(db_a)
    capsys.readouterr()

    assert main(["export", "bundle", "database", "--with-archive"]) == 0
    bundle_path = tmp_path / "briefing.md"
    bundle_path.write_text(capsys.readouterr().out, encoding="utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()

    assert main(["import", "bundle", str(bundle_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    # the import report carries the archive restore, like `events`
    assert report["archive"] == {"imported": 1, "skipped": 0}
    # the held copy (the adopted content) AND the recoverable prior both landed
    assert get_item(db_b, "wikipedia:en:SQLite").content_hash == "sha256:moved"
    recovered = latest_archived(db_b, "wikipedia:en:SQLite")
    assert recovered == prior  # the prior capture, recoverable on the rebuilt library


def test_with_archive_bundle_re_exports_byte_identically(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    # the archive block is byte-stable across the round-trip boundary (the H238/H244
    # byte-identity guarantee, on the archive axis): export → import → re-export
    # reproduces the same archive block, because the export order is content-determined
    # (archived_at, item_id, prior_hash), not the per-library autoincrement id
    main(["init"])
    db_a = get_paths().db_path
    _seed_archived_prior(db_a, "wikipedia:en:A")
    _seed_archived_prior(db_a, "wikipedia:en:B")
    capsys.readouterr()

    assert main(["export", "bundle", "database", "--with-archive"]) == 0
    first = capsys.readouterr().out
    bundle_path = tmp_path / "b.md"
    bundle_path.write_text(first, encoding="utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    capsys.readouterr()
    main(["import", "bundle", str(bundle_path)])
    capsys.readouterr()

    assert main(["export", "bundle", "database", "--with-archive"]) == 0
    second = capsys.readouterr().out
    # the archive block re-exports byte-for-byte (the lossless round-trip reach)
    from scrolls.items import dump_archive_export
    assert dump_archive_export(parse_bundle_archive(first)) == dump_archive_export(
        parse_bundle_archive(second)
    )


def test_import_bundle_archive_restore_is_idempotent(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    # re-importing the same `--with-archive` bundle dedups the archive (no second row)
    main(["init"])
    db_a = get_paths().db_path
    _seed_archived_prior(db_a)
    capsys.readouterr()
    main(["export", "bundle", "database", "--with-archive"])
    bundle_path = tmp_path / "b.md"
    bundle_path.write_text(capsys.readouterr().out, encoding="utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    capsys.readouterr()
    main(["import", "bundle", str(bundle_path)])
    first = json.loads(capsys.readouterr().out)
    assert first["archive"] == {"imported": 1, "skipped": 0}

    main(["import", "bundle", str(bundle_path)])
    second = json.loads(capsys.readouterr().out)
    assert second["archive"] == {"imported": 0, "skipped": 1}  # deduped
    assert len(archived_records(get_paths().db_path)) == 1


def test_import_bundle_dry_run_predicts_the_archive_restore(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    # the dry-run names the archive restore it would do, without writing (H280, the
    # H220/H245 predict-the-write discipline on the archive axis)
    main(["init"])
    db_a = get_paths().db_path
    _seed_archived_prior(db_a)
    capsys.readouterr()
    main(["export", "bundle", "database", "--with-archive"])
    bundle_path = tmp_path / "b.md"
    bundle_path.write_text(capsys.readouterr().out, encoding="utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()

    assert main(["import", "bundle", str(bundle_path), "--dry-run"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["dry_run"] is True
    assert preview["archive"] == {"imported": 1, "skipped": 0}
    assert archived_records(db_b) == []  # the dry-run wrote nothing

    # the live import then restores exactly what the preview predicted
    main(["import", "bundle", str(bundle_path)])
    live = json.loads(capsys.readouterr().out)
    assert live["archive"] == preview["archive"]


def _seed_archived_chain(db, item_id="wikipedia:en:SQLite", *, query_token="database"):
    """Hold an item, then adopt a *chain* of divergent captures at controlled
    `archived_at` stamps — a multi-supersession item whose archive holds several
    recoverable priors, not just one (the H280 single-prior helper's deeper cousin).

    The held copy ends as v3; the archive ends holding [v0@06-20, v1@06-21, v2@06-22]
    (newest-first v2). Strictly-increasing `archived_at` is deliberate: the export
    orders by `(archived_at, …)` and the rebuilt library inserts in that order, so
    A's adoption order and B's import order both yield the same `id DESC` newest-first
    history — `archive show --all` reads identically on either side. Every capture
    keeps `query_token` in its text so the whole item rides a query of that token's
    bundle scope. Returns the archived priors oldest-first ([v0, v1, v2])."""
    held = make_item(item_id, "SQLite", f"The original {query_token} capture.",
                     content_hash="sha256:v0")
    insert_item(db, held)
    priors = ["sha256:v0"]
    for n, at in ((1, "2026-06-20T00:00:00+00:00"),
                  (2, "2026-06-21T00:00:00+00:00"),
                  (3, "2026-06-22T00:00:00+00:00")):
        incoming = dataclasses.replace(
            held,
            extracted_text=f"A v{n} {query_token} capture.",
            raw_text=f"<raw>A v{n} {query_token} capture.</raw>",
            content_hash=f"sha256:v{n}",
        )
        adopt_incoming(db, incoming, archived_at=at)
        held = incoming
        if n < 3:
            priors.append(f"sha256:v{n}")
    return priors  # archived priors oldest-first: [v0, v1, v2]; held = v3


def test_archive_recovery_read_family_survives_the_with_archive_round_trip(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    """The whole archive-recovery *read* family reads identically on a library rebuilt
    from a `export bundle --with-archive` (H291).

    H280 makes the prior-content archive travel in the portable bundle; H285/H286/H288
    read and recover over it. The H280 round-trip pinned only that `archive show`'s
    *latest head* recovers post-rebuild — the untested integration tie is that the whole
    *family* behaves identically: the full history (`archive show --all`), the
    decide-before-you-restore delta (`archive diff`, held↔prior hashes / fidelities /
    `changed_fields` / `would_restore`), and the predicted restore (`archive restore
    --dry-run`). If they all agree field-for-field across the round-trip boundary, the
    bundle carries enough for the *entire* recovery surface, not just the newest prior.

    Adopt a multi-supersession chain in source A, round-trip a `--with-archive` bundle
    into a fresh source B, then assert every read agrees across A and B over all three
    selectors (`--hash`, `--at`, default-latest)."""
    main(["init"])
    db_a = get_paths().db_path
    _seed_archived_chain(db_a)  # archive [v0, v1, v2]; held = v3
    item_id = "wikipedia:en:SQLite"
    assert get_item(db_a, item_id).content_hash == "sha256:v3"
    assert len(list_archived(db_a, item_id)) == 3  # a genuine multi-supersession chain

    # the selectors the family reads over: the oldest prior by hash, a point-in-time
    # boundary mid-chain (picks v1@06-21, the newest at/before it), and default-latest
    selectors = (["--hash", "sha256:v0"], ["--at", "2026-06-21T12:00:00+00:00"], [])

    def read_family():
        """Run the whole recovery read-family — non-mutating (reads + a dry-run), so
        it is safe to run identically on A and on B."""
        out = {}
        capsys.readouterr()
        assert main(["archive", "show", item_id, "--all"]) == 0
        out["show_all"] = capsys.readouterr().out  # raw JSONL, compared byte-for-byte
        for sel in selectors:
            key = " ".join(sel) or "latest"
            capsys.readouterr()
            assert main(["archive", "diff", item_id, *sel]) == 0
            out[f"diff:{key}"] = json.loads(capsys.readouterr().out)
            capsys.readouterr()
            assert main(["archive", "restore", item_id, *sel, "--dry-run"]) == 0
            out[f"restore:{key}"] = json.loads(capsys.readouterr().out)
        return out

    family_a = read_family()
    # sanity: the family read something non-trivial in A — the full 3-prior chain and a
    # real would-change delta (a vacuous all-empty read would pass the A==B tie falsely)
    assert len(family_a["show_all"].splitlines()) == 3
    assert family_a["diff:--hash sha256:v0"]["would_restore"] is True
    assert family_a["restore:--at 2026-06-21T12:00:00+00:00"]["prior_hash"] == "sha256:v1"

    # round-trip a --with-archive bundle into a fresh library B
    capsys.readouterr()
    assert main(["export", "bundle", "database", "--with-archive"]) == 0
    bundle_path = tmp_path / "briefing.md"
    bundle_path.write_text(capsys.readouterr().out, encoding="utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()
    assert main(["import", "bundle", str(bundle_path)]) == 0
    capsys.readouterr()

    # the rebuilt library holds the same head and the same chain depth before reading
    assert get_item(db_b, item_id).content_hash == "sha256:v3"
    assert len(list_archived(db_b, item_id)) == 3

    # the whole recovery read-family is byte/field-identical across the round trip
    assert read_family() == family_a


# --- the archive-integrity alarm survives the --with-archive bundle (roadmap H296) ---
#
# H293 added the report-only archive-integrity check (`doctor`'s `custody.archive`
# flags any archived prior whose advertised `prior_hash` diverges from its
# snapshot's `content_hash`); H291 (above) proves the *clean* recovery read-family
# round-trips a `--with-archive` bundle; H295 (`tests/test_doctor.py`) proves the
# *alarm* survives the JSONL-backup path. The untested cell these tie together: a
# *corruption* must not be laundered by the **portable bundle** transport either —
# a tampered prior carried in the bundle's fenced archive block has to trip the
# alarm *identically* on a bundle-rebuilt library, never read clean (vision §2.4 —
# a shareable briefing may not silently repair a corruption it cannot actually
# fix). Correct-by-construction: `import bundle` restores the archive through
# `parse_bundle_archive` → `import_archive`, the *same* verbatim-snapshot restore
# behind the JSONL path, and the bundle block carries the same
# `prior_hash`/`snapshot` columns the JSONL does — so a regression guard,
# mutation-checked by *repairing* the prior on the bundle wire before import (the
# alarm then clears on the rebuild, proving the tie is load-bearing).


def _tamper_archive(db_path, item_id, **columns):
    """Out-of-band rewrite of one archive row — a corrupt/hand-edited store (the
    `tests/test_doctor.py` helper, here so the bundle path can seed a corruption)."""
    assignments = ", ".join(f"{name} = ?" for name in columns)
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            f"UPDATE item_archive SET {assignments} WHERE item_id = ?",
            tuple(columns.values()) + (item_id,),
        )
    conn.close()


def _seed_corrupt_plus_clean_archive(db):
    """Seed `db` with two archived priors — both in the `database` bundle scope —
    one clean, one whose `prior_hash` was tampered to diverge from its snapshot's
    `content_hash`. Returns the corrupt prior's item id (the row the integrity
    alarm must name). The bundle-path twin of the `tests/test_doctor.py` helper."""
    _seed_archived_prior(db, "wikipedia:en:clean")
    corrupt_id = "wikipedia:en:corrupt"
    _seed_archived_prior(db, corrupt_id)
    _tamper_archive(db, corrupt_id, prior_hash="sha256:tampered")
    return corrupt_id


def test_archive_integrity_alarm_survives_the_with_archive_bundle_round_trip(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    # A corrupt archived prior carried in a `--with-archive` bundle's fenced archive
    # block is flagged *identically* by `doctor`'s `custody.archive` on the
    # bundle-rebuilt library — the portable briefing does not launder the corruption
    # (H293 × H291/H280 tie, the bundle-path twin of H295).
    main(["init"])
    db_a = get_paths().db_path
    corrupt = _seed_corrupt_plus_clean_archive(db_a)

    archive_a = run_doctor(get_paths())["custody"]["archive"]
    # sanity: A names exactly the corrupt row, the clean prior passes — a genuine
    # mismatch travels (a vacuous all-clean read would pass the A==B tie falsely)
    assert archive_a["status"] == "ok"
    assert archive_a["checked"] == 2
    assert archive_a["mismatched"] == 1
    assert archive_a["events"] == [
        {
            "item_id": corrupt,
            "prior_hash": "sha256:tampered",
            "snapshot_hash": "sha256:held",
        }
    ]

    # round-trip a --with-archive bundle (the whole `database` scope = both items)
    capsys.readouterr()
    assert main(["export", "bundle", "database", "--with-archive"]) == 0
    bundle_path = tmp_path / "briefing.md"
    bundle_path.write_text(capsys.readouterr().out, encoding="utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()
    assert main(["import", "bundle", str(bundle_path)]) == 0

    # the rebuilt library holds the whole archive (both priors travelled) and trips
    # the alarm on the same offending event set with the same checked/mismatched —
    # byte-for-byte the report A read, never read clean
    assert len(archived_records(db_b)) == 2
    archive_b = run_doctor(get_paths())["custody"]["archive"]
    assert archive_b == archive_a


def test_repairing_the_prior_on_the_bundle_wire_clears_the_alarm_on_the_rebuild(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    # Mutation guard: the alarm-on-the-rebuild is load-bearing. If the divergence is
    # *repaired* on the bundle wire before import (the corrupt `prior_hash` rewritten
    # back to its snapshot's `content_hash`), the rebuilt library reads clean — so the
    # flag on B genuinely tracks the bundle's content, not a phantom that always fires.
    main(["init"])
    db_a = get_paths().db_path
    _seed_corrupt_plus_clean_archive(db_a)
    assert run_doctor(get_paths())["custody"]["archive"]["mismatched"] == 1  # A dirty

    capsys.readouterr()
    assert main(["export", "bundle", "database", "--with-archive"]) == 0
    bundle = capsys.readouterr().out
    # the tampered prior_hash appears exactly once on the wire (the corrupt archive
    # row's column; the snapshot keeps its honest content_hash) — repair it in place
    assert bundle.count("sha256:tampered") == 1
    bundle_path = tmp_path / "briefing.md"
    bundle_path.write_text(bundle.replace("sha256:tampered", "sha256:held"), "utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    capsys.readouterr()
    assert main(["import", "bundle", str(bundle_path)]) == 0

    archive_b = run_doctor(get_paths())["custody"]["archive"]
    assert archive_b == {"status": "ok", "checked": 2, "mismatched": 0, "events": []}


def test_html_bundle_carries_the_archive_block_only_with_the_flag(scrolls_home):
    # the HTML form embeds the archive block under `--with-archive` for parity with
    # the Markdown form (export-only — re-import via the Markdown bundle); omitted by
    # default, keeping the default HTML lean
    main(["init"])
    db = get_paths().db_path
    _seed_archived_prior(db)

    lean = build_bundle_html(db, "database")
    assert "Prior-content archive" not in lean

    full = build_bundle_html(db, "database", with_archive=True)
    assert "Prior-content archive" in full
    assert "sha256:held" in full  # the archived prior's hash travels in the block


def test_import_bundle_dry_run_predicts_the_conflict_set(scrolls_home, tmp_path, capsys):
    # the genuinely new H273 leg: the `--dry-run` preview *predicts* the conflict
    # the live merge would surface — the H245-style "predict the write effect"
    # closure on the conflict axis. It writes nothing (the held copy is untouched)
    # yet names the would-be-conflicting id under `conflicts`, and warns on stderr
    # exactly as the live import would.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "The original capture.",
        content_hash="sha256:held",
    ))
    divergent = make_item(
        "wikipedia:en:SQLite", "SQLite", "A different, later capture.",
        content_hash="sha256:moved",
    )
    bundle_path = tmp_path / "incoming.md"
    bundle_path.write_text(_items_only_bundle([divergent]), encoding="utf-8")
    capsys.readouterr()

    assert main(["import", "bundle", str(bundle_path), "--dry-run"]) == 0
    out, err = capsys.readouterr()
    preview = json.loads(out)
    assert preview["dry_run"] is True
    # the preview predicts the same conflict partition the live import surfaces
    assert preview["imported"] == 0
    assert preview["skipped"] == 1
    assert preview["unchanged"] == 0
    assert preview["conflict"] == 1
    assert preview["conflicts"] == ["wikipedia:en:SQLite"]
    # a conflicting held id is named under `held` (it is already in the library),
    # the reviewable surface an operator confirms before committing
    assert preview["held"] == ["wikipedia:en:SQLite"]
    assert preview["new"] == []
    # the conflict warning is loud in the preview too (the orphan-warning idiom)
    assert "conflict" in err.lower()
    # …but nothing was written — the held copy is byte-for-byte untouched
    kept = get_item(db, "wikipedia:en:SQLite")
    assert kept.content_hash == "sha256:held"
    assert kept.extracted_text == "The original capture."


def test_import_bundle_dry_run_conflict_partition_matches_a_real_import(
    scrolls_home, tmp_path, capsys
):
    # the live≡preview convergence the slice must hold (the conflict-axis analogue
    # of test_import_bundle_dry_run_counts_match_a_real_import): over a mixed bundle
    # — a would-be-new id, an identical re-import of a held id, and a divergent copy
    # of another held id — the dry-run's *entire* top-level summary (sans the
    # dry-run-only {dry_run, new, held}) equals what the subsequent real import
    # prints, so the preview's `unchanged`/`conflict`/`conflicts` never drift from
    # the merge's.
    new = make_item(
        "arxiv:1706.03762", "Attention", "A new attention paper.",
        source="arxiv", url="https://arxiv.org/abs/1706.03762",
        content_hash="sha256:new",
    )
    same = make_item(
        "wikipedia:en:SQLite", "SQLite", "The original capture.",
        content_hash="sha256:sqlite",
    )
    divergent = make_item(
        "wikipedia:en:Postgres", "Postgres", "A different, later capture.",
        content_hash="sha256:moved",
    )
    bundle_path = tmp_path / "incoming.md"
    bundle_path.write_text(
        _items_only_bundle([new, same, divergent]), encoding="utf-8"
    )

    main(["init"])
    db = get_paths().db_path
    # the library already holds an identical SQLite and an *older* Postgres capture
    insert_item(db, same)
    insert_item(db, make_item(
        "wikipedia:en:Postgres", "Postgres", "The original capture.",
        content_hash="sha256:held",
    ))
    capsys.readouterr()

    # dry-run first (writes nothing), then the real import into the same library
    assert main(["import", "bundle", str(bundle_path), "--dry-run"]) == 0
    preview = json.loads(capsys.readouterr().out)
    _DRY_RUN_ONLY = {"dry_run", "new", "held"}
    assert main(["import", "bundle", str(bundle_path)]) == 0
    live = json.loads(capsys.readouterr().out)
    # the whole summary converges (sans the reviewable, dry-run-only id lists)
    assert {k: v for k, v in preview.items() if k not in _DRY_RUN_ONLY} == live
    # concretely: one import, one unchanged, one surfaced conflict
    assert live["imported"] == 1
    assert live["unchanged"] == 1
    assert live["conflict"] == 1
    assert live["conflicts"] == ["wikipedia:en:Postgres"]
    assert live["skipped"] == live["unchanged"] + live["conflict"]
    # the divergent held copy was kept, the new one inserted (the merge is real on
    # disk, exactly as both summaries agreed)
    assert get_item(db, "wikipedia:en:Postgres").extracted_text == "The original capture."
    assert get_item(db, "arxiv:1706.03762") is not None


def test_import_bundle_within_bundle_dup_with_divergent_content_conflicts_on_both(
    scrolls_home, tmp_path, capsys
):
    # the within-bundle-dup parity the slice must hold: a bundle that *repeats* an
    # id with divergent content (a splice of two overlapping exports captured at
    # different times) classifies identically on both paths. The live `merge_item`
    # sees its own prior insert (the first occurrence is kept, the second compared
    # against it → conflict); the dry-run must *simulate* that within-batch view
    # without writing — so both report the same `conflict`/`conflicts`, and the
    # repeated id rides `new` (library-absent) *and* `conflicts` (the bundle
    # disagrees with itself) at once.
    first = make_item(
        "wikipedia:en:SQLite", "SQLite", "The first capture.",
        content_hash="sha256:first",
    )
    second = make_item(
        "wikipedia:en:SQLite", "SQLite", "A divergent second capture.",
        content_hash="sha256:second",
    )
    bundle_path = tmp_path / "spliced.md"
    bundle_path.write_text(_items_only_bundle([first, second]), encoding="utf-8")

    main(["init"])  # an empty library — the id is library-absent
    db = get_paths().db_path
    capsys.readouterr()

    # dry-run: the first occurrence would import, the second conflicts against it
    assert main(["import", "bundle", str(bundle_path), "--dry-run"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["imported"] == 1
    assert preview["skipped"] == 1
    assert preview["unchanged"] == 0
    assert preview["conflict"] == 1
    assert preview["conflicts"] == ["wikipedia:en:SQLite"]
    # the repeated id is library-absent → `new`, yet the bundle disagrees with
    # itself → also `conflicts` (an honest both-at-once; `new`/`held` stay
    # library-relative and disjoint, H239)
    assert preview["new"] == ["wikipedia:en:SQLite"]
    assert preview["held"] == []

    # the live import of the same spliced bundle classifies identically…
    assert main(["import", "bundle", str(bundle_path)]) == 0
    live = json.loads(capsys.readouterr().out)
    _DRY_RUN_ONLY = {"dry_run", "new", "held"}
    assert {k: v for k, v in preview.items() if k not in _DRY_RUN_ONLY} == live
    # …and the kept copy on disk is the *first* occurrence (INSERT OR IGNORE keeps
    # it; the divergent second was surfaced, never overwritten)
    assert get_item(db, "wikipedia:en:SQLite").extracted_text == "The first capture."


def test_import_bundle_records_a_conflict_as_a_custody_event(
    scrolls_home, tmp_path, capsys
):
    # H274: the conflict-event recording rides the *shared* `_merge_items`, so the
    # bundle importer gets it for free — a divergent held id surfaced as a conflict
    # also lands on the ledger (held vs incoming `content_hash`), queryable via
    # `scrolls history`. And it stays a *distinct* axis: the drift posture is
    # untouched (a peer disagreement is not evidence the live source moved).
    from scrolls.custody import drift_posture, item_events, latest_events

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "The original capture.",
        content_hash="sha256:held",
    ))
    divergent = make_item(
        "wikipedia:en:SQLite", "SQLite", "A different, later capture.",
        content_hash="sha256:moved",
    )
    bundle_path = tmp_path / "incoming.md"
    bundle_path.write_text(_items_only_bundle([divergent]), encoding="utf-8")
    capsys.readouterr()

    assert main(["import", "bundle", str(bundle_path)]) == 0
    capsys.readouterr()
    # the divergence is a recorded ledger event (the shared `_merge_items` H274 hook)
    events = item_events(db, "wikipedia:en:SQLite")
    assert [e.status for e in events] == ["conflict"]
    assert events[0].prior_hash == "sha256:held"  # the kept copy
    assert events[0].observed_hash == "sha256:moved"  # the incoming bundle row
    # distinct axis: the conflict never enters the drift posture
    assert drift_posture(latest_events(db).get("wikipedia:en:SQLite")) == "unverified"


def test_import_bundle_dry_run_records_no_conflict_event(
    scrolls_home, tmp_path, capsys
):
    # the dry-run *predicts* the conflict (H273) but writes nothing — including the
    # ledger: `_preview_merge_items` is the read-only twin, so a preview leaves no
    # conflict event behind even though it warns and names the conflicting id. Only
    # the live import (the writing `_merge_items`) records.
    from scrolls.custody import item_events

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "The original capture.",
        content_hash="sha256:held",
    ))
    divergent = make_item(
        "wikipedia:en:SQLite", "SQLite", "A different, later capture.",
        content_hash="sha256:moved",
    )
    bundle_path = tmp_path / "incoming.md"
    bundle_path.write_text(_items_only_bundle([divergent]), encoding="utf-8")
    capsys.readouterr()

    assert main(["import", "bundle", str(bundle_path), "--dry-run"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["conflict"] == 1  # the preview predicts the conflict…
    # …but the ledger is untouched — no event written by the dry-run
    assert item_events(db, "wikipedia:en:SQLite") == []


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


# --- the explainable-ranking surface on the shareable bundle (H317) ----------
#
# `scrolls export bundle <query>` is built from the *same* ranked `search_items`
# as `search`/`context`, but `_gather_scope` discarded each hit's `match_strength`
# — so the portable briefing carried the `_Custody:_` headline and per-excerpt
# drift tags but no rank explanation (a recipient saw *what* matched, not *how
# strongly*). H317 threads the per-id `match_strength` out of `_gather_scope` and
# folds it into both the Markdown and HTML forms: a bundle-level `_Strength:_`
# headline (the shared `search.render_strength_headline` over `tally_strength`,
# H315) beside the custody headline, and a per-scroll `· rank <strength>` marker
# beside the drift tag. Unlike `context`, the bundle carries no cap and does not
# collapse same-work duplicates, so the tally is over the raw matched set; the two
# forms render byte-convergent counts by construction (the shared primitive).


def _seed_strength_scope(db):
    """Three scrolls all matching "widget" at three distinct rank strengths.

    Title hit → `strong`, summary (first-sentence) hit → `moderate`, body-only
    (later-sentence) hit → `weak`, grounded in the BM25 column weights
    (title 5× > summary 2× > extracted_text 1×). `make_item`'s `summary` is the
    first sentence of `extracted_text`, so a term placed *after* the first
    sentence lands in `extracted_text` only → `weak`.
    """
    insert_item(db, make_item(
        "wikipedia:en:Strong", "The Widget Compendium",
        "An assortment of small machines. Many gears turn inside them.",
    ))
    insert_item(db, make_item(
        "wikipedia:en:Moderate", "Small Machines",
        "A widget is a small machine. People build them for fun.",
    ))
    insert_item(db, make_item(
        "wikipedia:en:Weak", "Small Machines Two",
        "A small machine made of gears. Some people call it a widget here.",
    ))


def test_bundle_carries_strength_headline_and_per_scroll_markers(scrolls_home):
    # the Markdown bundle gains a bundle-level `_Strength:_` headline summarising
    # how strongly the matches ranked, and a `· rank <strength>` marker on each
    # scroll's drift line — the H315 explainable-ranking surface lifted to the
    # portable briefing
    main(["init"])
    db = get_paths().db_path
    _seed_strength_scope(db)

    bundle = build_bundle(db, "widget")
    # the bundle-level rank-confidence headline (every band present, sums to N)
    assert "_Strength: strong 1, moderate 1, weak 1 (of 3)._" in bundle
    # the headline sits beside the scope custody headline, above the entries
    assert bundle.index("_Strength:") < bundle.index("## 1.")
    # each scroll's drift line carries its own per-match rank marker
    assert "· rank `strong`" in bundle
    assert "· rank `moderate`" in bundle
    assert "· rank `weak`" in bundle


def test_bundle_html_carries_strength_headline_and_markers(scrolls_home):
    # the HTML twin: the same headline (as a paragraph) and the same per-scroll
    # `· rank <strength>` markers — H317's two-form parity (the H271 precedent)
    main(["init"])
    db = get_paths().db_path
    _seed_strength_scope(db)

    html_bundle = build_bundle_html(db, "widget")
    assert '<p class="rank-strength">' in html_bundle
    assert "Strength: strong 1, moderate 1, weak 1 (of 3)." in html_bundle
    # the per-scroll markers ride the drift fact, escaped <code> spans
    assert "· rank <code>strong</code>" in html_bundle
    assert "· rank <code>moderate</code>" in html_bundle
    assert "· rank <code>weak</code>" in html_bundle


def test_bundle_forms_converge_on_strength_counts(scrolls_home):
    # the Markdown and HTML forms render byte-convergent strength counts — both
    # fold the same `render_strength_headline(tally_strength(...))` over the same
    # raw matched set, so the inner count string cannot disagree (H39/H271 twin)
    main(["init"])
    db = get_paths().db_path
    _seed_strength_scope(db)

    md = build_bundle(db, "widget")
    html_bundle = build_bundle_html(db, "widget")
    # the Markdown headline with its `_` emphasis stripped is the HTML content
    md_headline = "Strength: strong 1, moderate 1, weak 1 (of 3)."
    assert f"_{md_headline}_" in md
    assert md_headline in html_bundle


def test_bundle_strength_single_band(scrolls_home):
    # honest single-band scope: a lone title hit reads `_Strength: strong 1
    # (of 1)._` — only the present band, no zero-filled noise
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:Strong", "The Widget Compendium",
        "An assortment of small machines.",
    ))

    bundle = build_bundle(db, "widget")
    assert "_Strength: strong 1 (of 1)._" in bundle
    assert "moderate" not in bundle.split("## 1.")[0]  # no zero bands in the headline
    html_bundle = build_bundle_html(db, "widget")
    assert "Strength: strong 1 (of 1)." in html_bundle


def test_bundle_strength_absent_on_empty_scope(scrolls_home):
    # honest absence: an empty scope reports no rank confidence (there is nothing
    # to rank) — the headline and markers are simply omitted, both forms
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:Strong", "The Widget Compendium",
        "An assortment of small machines.",
    ))

    bundle = build_bundle(db, "nonexistentquery")
    assert "No matching scrolls." in bundle
    assert "_Strength:" not in bundle
    assert "· rank `" not in bundle
    html_bundle = build_bundle_html(db, "nonexistentquery")
    assert "<p>No matching scrolls.</p>" in html_bundle
    assert 'class="rank-strength"' not in html_bundle
