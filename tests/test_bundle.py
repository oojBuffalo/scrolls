"""Tests for shareable custody bundles (ADR 0103, MVP M4)."""

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
    assert (
        "- `arxiv` — 1 scroll(s) · fidelity full 1 · drift unverified 1" in bundle
    )
    assert (
        "- `web` — 2 scroll(s) · fidelity full 2 · drift verified 1, drifted 1"
        in bundle
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
        "drift verified 1, drifted 1" in doc
    )
    assert (
        "<code>arxiv</code> — 1 scroll(s) · fidelity full 1 · drift unverified 1"
        in doc
    )


def test_bundle_html_per_source_breakdown_omitted_for_a_single_source(scrolls_home):
    # parity with the Markdown form: one source → no split
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "web:a", "A database", "A database.", source="web", url="https://web/a"))
    doc = build_bundle_html(db, "database")
    assert "By source:" not in doc


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
    assert report["events"] == {"imported": 2, "skipped": 0}
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
    assert report["events"] == {"imported": 0, "skipped": 1}
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
    assert report["events"] == {"imported": 0, "skipped": 0}


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
