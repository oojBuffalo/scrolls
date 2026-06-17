"""Scheduled custody maintenance — `scrolls maintain` (roadmap H22/H23/H34).

Two layers, tested separately:

- The **delta layer** (`scrolls.maintain`): distilling a doctor report into a
  comparable custody snapshot and computing the cross-run delta. This is the one
  genuinely new piece — everything `maintain` composes (audit/recheck/regenerate)
  already ships and is tested elsewhere.
- The **command** (`scrolls maintain`): the offline composition, scripted the way
  `test_dogfood.py` scripts the live `verify` edge — through the one
  `cli.live_recapture` seam — so the whole pass runs network-free.

The sharp custody point the command makes visible, like the dogfood proof:
detecting source drift moves the *drift posture* without lowering the integrity
*score* (raw is sacred; drift is a recorded event, never an overwrite).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

import pytest

import scrolls.cli as cli
from scrolls.cli import main
from scrolls.custody import (
    CustodyEvent,
    custody_counts_by_source,
    custody_headline,
    latest_events,
    record_events,
)
from scrolls.db import init_db
from scrolls.doctor import run_doctor
from scrolls.items import (
    ScrollItem,
    get_item,
    insert_item,
    item_to_dict,
    list_items,
    make_item_id,
    update_item,
)
from scrolls.maintain import (
    append_log_entry,
    compute_delta,
    compute_trend,
    custody_snapshot,
    last_run_boundary,
    load_snapshot,
    log_path,
    read_log,
    report_by_source,
    save_snapshot,
    snapshot_headline,
    snapshot_path,
    suggest_repairs,
    weakest_source,
)
from scrolls.paths import get_paths
from scrolls.render import write_scroll

# --- the delta layer (pure) -----------------------------------------------


def _doctor_report(score, tiers, drift, enrichment_stale=0, summaries_stale=0,
                   coverage=None):
    """A minimal doctor report shaped like `run_doctor`'s custody block.

    `coverage` mirrors the drift block's `{verified, total}` recheck-coverage
    member (roadmap H113); defaults to the honest zero when not specified.
    """
    full_drift = {
        "checked": 0, "unverified": 0, "unchanged": 0,
        "drifted": 0, "rotted": 0, "error": 0,
        "coverage": coverage or {"verified": 0, "total": 0},
    }
    full_drift.update(drift)
    return {
        "custody": {
            "score": score,
            "tiers": tiers,
            "drift": full_drift,
            "enrichment": {"stale": enrichment_stale},
            "summaries": {"stale": summaries_stale},
        }
    }


def test_custody_snapshot_distils_only_the_custody_scalars():
    report = _doctor_report(
        score=90,
        tiers={"full": 3, "partial": 1, "reference": 0},
        drift={"checked": 2, "unverified": 2, "drifted": 1, "unchanged": 1},
        enrichment_stale=2,
        summaries_stale=1,
        coverage={"verified": 2, "total": 4},
    )
    snap = custody_snapshot(report)
    assert snap == {
        "score": 90,
        "tiers": {"full": 3, "partial": 1, "reference": 0},
        "drift": {
            "checked": 2, "unverified": 2, "unchanged": 1,
            "drifted": 1, "rotted": 0, "error": 0,
        },
        "coverage": {"verified": 2, "total": 4},
        "enrichment_stale": 2,
        "summaries_stale": 1,
    }


def test_custody_snapshot_coverage_defaults_to_zero_on_a_pre_h113_drift_block():
    # A doctor report whose drift block predates the H113 coverage member reads
    # the honest zeroed coverage, never a KeyError — the degrade-safely posture.
    report = _doctor_report(100, {"full": 1}, {"checked": 1, "unchanged": 1})
    del report["custody"]["drift"]["coverage"]
    assert custody_snapshot(report)["coverage"] == {"verified": 0, "total": 0}


# --- snapshot_headline (the one-line custody picture, roadmap H103) --------


def test_snapshot_headline_renders_the_one_line_picture_mapping_unchanged_to_verified():
    # the snapshot's drift uses doctor's vocabulary (checked/unchanged/…); the
    # headline shows postures (verified/…) via the documented `verified ≡
    # unchanged` mapping, and `checked` (the verdict total) is not a posture.
    snapshot = custody_snapshot(
        _doctor_report(
            score=90,
            tiers={"full": 2, "partial": 1, "reference": 1},
            drift={"checked": 3, "unverified": 1, "unchanged": 2, "drifted": 1},
        )
    )
    assert snapshot_headline(snapshot) == (
        "_Custody: 4 scroll(s) · fidelity full 2, partial 1, reference 1 "
        "· drift verified 2, unverified 1, drifted 1._"
    )


def test_snapshot_headline_on_an_empty_or_uninitialized_snapshot_is_zero_scrolls():
    # an empty library's snapshot (doctor's all-zero tiers, score None) is the
    # honest `0 scroll(s)`, never a fabricated count.
    empty = custody_snapshot(
        _doctor_report(score=None, tiers={"full": 0, "partial": 0, "reference": 0},
                       drift={})
    )
    assert snapshot_headline(empty) == "_Custody: 0 scroll(s)._"
    # a totally absent snapshot (no axes at all) degrades to the same, never a crash
    assert snapshot_headline({}) == "_Custody: 0 scroll(s)._"


def test_snapshot_headline_tolerates_a_snapshot_missing_an_axis():
    # an older snapshot schema (drift without `error`, a tier absent) reads the
    # missing axes as zero — the module's forward-compatible posture (ADR 0082).
    line = snapshot_headline({"tiers": {"full": 2}, "drift": {"unchanged": 2}})
    assert line == "_Custody: 2 scroll(s) · fidelity full 2 · drift verified 2._"


def test_delta_on_first_run_has_null_befores_and_changes():
    current = custody_snapshot(
        _doctor_report(100, {"full": 3, "partial": 0, "reference": 0}, {"unverified": 3})
    )
    delta = compute_delta(None, current)
    assert delta["first_run"] is True
    assert delta["since"] is None
    assert delta["score"] == {"before": None, "after": 100, "change": None}
    assert delta["drift"]["unverified"] == {"before": None, "after": 3, "change": None}
    assert delta["enrichment_stale"]["change"] is None


def test_delta_reports_per_axis_change_against_a_baseline():
    previous = {
        "recorded_at": "2026-06-15T09:00:00+00:00",
        "score": 100,
        "tiers": {"full": 3, "partial": 0, "reference": 0},
        "drift": {"checked": 0, "unverified": 3, "unchanged": 0,
                  "drifted": 0, "rotted": 0, "error": 0},
        "enrichment_stale": 0,
        "summaries_stale": 0,
    }
    current = custody_snapshot(
        _doctor_report(
            100,
            {"full": 3, "partial": 0, "reference": 0},
            {"checked": 3, "unverified": 0, "unchanged": 2, "drifted": 1},
            enrichment_stale=1,
        )
    )
    delta = compute_delta(previous, current)
    assert delta["first_run"] is False
    assert delta["since"] == "2026-06-15T09:00:00+00:00"
    # raw is sacred: drift moved, score did not
    assert delta["score"] == {"before": 100, "after": 100, "change": 0}
    assert delta["drift"]["drifted"] == {"before": 0, "after": 1, "change": 1}
    assert delta["drift"]["unverified"] == {"before": 3, "after": 0, "change": -3}
    assert delta["drift"]["checked"] == {"before": 0, "after": 3, "change": 3}
    assert delta["enrichment_stale"] == {"before": 0, "after": 1, "change": 1}


def test_delta_tolerates_a_baseline_missing_an_axis():
    """An older snapshot schema (no enrichment_stale, a tier that did not exist)
    reads as zero for the absent axis, never a crash."""
    previous = {"recorded_at": "t", "score": 100, "tiers": {"full": 2},
                "drift": {"checked": 0}}
    current = custody_snapshot(
        _doctor_report(100, {"full": 2, "partial": 1, "reference": 0}, {"checked": 0})
    )
    delta = compute_delta(previous, current)
    assert delta["enrichment_stale"] == {"before": 0, "after": 0, "change": 0}
    # 'partial' is new this run; the baseline had none → before 0, change +1
    assert delta["tiers"]["partial"] == {"before": 0, "after": 1, "change": 1}
    assert delta["tiers"]["full"] == {"before": 2, "after": 2, "change": 0}


def test_delta_reports_per_axis_coverage_change():
    """Coverage is a count mapping like tiers/drift: the delta diffs it per-key,
    so a worker reads how much more of the library got covered since last run."""
    previous = {
        "recorded_at": "2026-06-16T09:00:00+00:00",
        "score": 100,
        "tiers": {"full": 4},
        "drift": {"checked": 1},
        "coverage": {"verified": 1, "total": 4},
    }
    current = custody_snapshot(
        _doctor_report(100, {"full": 4}, {"checked": 3},
                       coverage={"verified": 3, "total": 4})
    )
    delta = compute_delta(previous, current)
    # two more verifiable items came to carry a verdict; the denominator held
    assert delta["coverage"]["verified"] == {"before": 1, "after": 3, "change": 2}
    assert delta["coverage"]["total"] == {"before": 4, "after": 4, "change": 0}


def test_delta_coverage_on_first_run_is_null():
    # no baseline → every coverage before/change is null, never a fabricated zero
    current = custody_snapshot(
        _doctor_report(100, {"full": 2}, {}, coverage={"verified": 0, "total": 2})
    )
    delta = compute_delta(None, current)
    assert delta["coverage"]["verified"] == {"before": None, "after": 0, "change": None}
    assert delta["coverage"]["total"] == {"before": None, "after": 2, "change": None}


def test_delta_tolerates_a_baseline_lacking_coverage():
    """A pre-H115 baseline (no `coverage` axis) reads as zero for that axis, never
    null — the run happened, coverage was simply not yet tracked (ADR 0082)."""
    previous = {"recorded_at": "t", "score": 100, "tiers": {"full": 2},
                "drift": {"checked": 2}}  # no `coverage` key
    current = custody_snapshot(
        _doctor_report(100, {"full": 2}, {"checked": 2},
                       coverage={"verified": 2, "total": 2})
    )
    delta = compute_delta(previous, current)
    assert delta["coverage"]["verified"] == {"before": 0, "after": 2, "change": 2}
    assert delta["coverage"]["total"] == {"before": 0, "after": 2, "change": 2}


def test_snapshot_round_trips_and_missing_reads_as_none(tmp_path):
    path = tmp_path / ".maintenance" / "last-run.json"
    assert load_snapshot(path) is None  # no file yet → first run
    snap = {"score": 100, "tiers": {"full": 1}, "recorded_at": "t"}
    save_snapshot(path, snap)
    assert path.exists()
    assert load_snapshot(path) == snap


def test_corrupt_snapshot_degrades_to_first_run(tmp_path):
    path = tmp_path / ".maintenance" / "last-run.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ not json", encoding="utf-8")
    assert load_snapshot(path) is None


# --- the staleness boundary (pure, roadmap H83) ---------------------------


def test_last_run_boundary_reads_and_normalizes_the_recorded_at():
    """The default recheck's staleness window is the last run's recorded_at,
    normalized to the stored `+00:00` shape so the ledger compare is exact."""
    assert (
        last_run_boundary({"score": 100, "recorded_at": "2026-06-15T09:00:00+00:00"})
        == "2026-06-15T09:00:00+00:00"
    )
    # a Z-suffixed timestamp normalizes to the same stored shape (parse_since)
    assert (
        last_run_boundary({"recorded_at": "2026-06-15T09:00:00Z"})
        == "2026-06-15T09:00:00+00:00"
    )


def test_last_run_boundary_is_none_without_a_baseline():
    """A first run (no prior snapshot) has no boundary → recheck everything."""
    assert last_run_boundary(None) is None


def test_last_run_boundary_degrades_to_none_on_a_missing_or_corrupt_timestamp():
    """A baseline with no/blank/unparseable recorded_at degrades to "recheck all"
    — the snapshot's degrade-safely posture on the boundary axis, never a crash
    or a silently-wrong lexicographic window."""
    assert last_run_boundary({"score": 100}) is None  # no recorded_at key
    assert last_run_boundary({"recorded_at": ""}) is None  # blank
    assert last_run_boundary({"recorded_at": "not-a-timestamp"}) is None  # garbage


# --- the run log (pure, append-only) --------------------------------------


def _log_entry(recorded_at, score):
    return {
        "recorded_at": recorded_at,
        "snapshot": {"score": score, "tiers": {"full": 1}},
        "delta": {"first_run": recorded_at == "t1"},
    }


def test_log_round_trips_oldest_first(tmp_path):
    path = tmp_path / ".maintenance" / "log.jsonl"
    assert read_log(path) == []  # no file yet → empty history, not an error
    a, b = _log_entry("t1", 100), _log_entry("t2", 90)
    append_log_entry(path, a)
    append_log_entry(path, b)
    assert read_log(path) == [a, b]  # appended in order, oldest first


def test_append_never_rewrites_earlier_runs(tmp_path):
    """The custody-ledger posture: a second run appends a line, the first stays."""
    path = tmp_path / ".maintenance" / "log.jsonl"
    append_log_entry(path, _log_entry("t1", 100))
    first_bytes = path.read_text(encoding="utf-8")
    append_log_entry(path, _log_entry("t2", 90))
    grown = path.read_text(encoding="utf-8")
    assert grown.startswith(first_bytes)  # the first line is byte-for-byte intact
    assert len(grown.splitlines()) == 2


def test_read_log_limit_returns_the_last_n(tmp_path):
    path = tmp_path / ".maintenance" / "log.jsonl"
    entries = [_log_entry(f"t{i}", 100 - i) for i in range(5)]
    for entry in entries:
        append_log_entry(path, entry)
    assert read_log(path, limit=2) == entries[-2:]
    assert read_log(path, limit=10) == entries  # limit past the end is the whole log
    assert read_log(path, limit=0) == []  # an empty window is honest, not "all"
    assert read_log(path, limit=None) == entries


def test_read_log_skips_a_corrupt_line_without_losing_the_good_ones(tmp_path):
    """One bad append must never hide every good run before or after it."""
    path = tmp_path / ".maintenance" / "log.jsonl"
    good_a, good_b = _log_entry("t1", 100), _log_entry("t2", 90)
    append_log_entry(path, good_a)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{ not json\n\n")  # a corrupt line and a blank line
    append_log_entry(path, good_b)
    assert read_log(path) == [good_a, good_b]


# --- the derived trend (pure, roadmap H46) --------------------------------


def _run(
    recorded_at,
    score,
    drifted=0,
    rotted=0,
    verified=0,
    total=0,
    enrichment_stale=0,
    summaries_stale=0,
):
    return {
        "recorded_at": recorded_at,
        "snapshot": {
            "score": score,
            "drift": {"drifted": drifted, "rotted": rotted},
            "coverage": {"verified": verified, "total": total},
            "enrichment_stale": enrichment_stale,
            "summaries_stale": summaries_stale,
        },
        "delta": {},
    }


def test_trend_under_two_runs_is_not_a_trajectory():
    """A single point has no direction — honest absence, not a fabricated zero."""
    for window in ([], [_run("t1", 100)]):
        trend = compute_trend(window)
        assert trend["posture"] == "insufficient-history"
        assert trend["score"] is None and trend["drift_change"] is None
        assert trend["coverage_change"] is None  # no direction from one point
        assert trend["stale_change"] is None  # nor an enrichment/summary debt direction
        assert trend["runs"] == len(window)


def test_trend_holding_when_nothing_moved():
    trend = compute_trend([_run("t1", 100), _run("t2", 100)])
    assert trend["posture"] == "holding"
    assert trend["since"] == "t1"
    assert trend["runs"] == 2
    assert trend["score"] == {"first": 100, "last": 100, "change": 0}
    assert trend["drift_change"] == 0


def test_trend_regressing_on_a_score_drop():
    trend = compute_trend([_run("t1", 100), _run("t2", 80)])
    assert trend["posture"] == "regressing"
    assert trend["score"]["change"] == -20


def test_trend_regressing_when_drift_accumulates_even_at_a_steady_score():
    """The dogfood point recurring: integrity holds, but more sources drifted —
    a recurring drift accumulation is still a regression worth surfacing."""
    trend = compute_trend([_run("t1", 100, drifted=0), _run("t2", 100, drifted=2)])
    assert trend["posture"] == "regressing"
    assert trend["score"]["change"] == 0
    assert trend["drift_change"] == 2


def test_trend_improving_when_drift_clears():
    trend = compute_trend(
        [_run("t1", 100, drifted=2, rotted=1), _run("t2", 100, drifted=0, rotted=0)]
    )
    assert trend["posture"] == "improving"
    assert trend["drift_change"] == -3


def test_trend_score_change_is_null_when_an_endpoint_has_no_library():
    """A window spanning an uninitialized run (score None) yields a null score
    change, never a fabricated number; drift movement is still computed."""
    trend = compute_trend([_run("t1", None, drifted=0), _run("t2", 100, drifted=0)])
    assert trend["score"]["change"] is None
    assert trend["drift_change"] == 0
    assert trend["posture"] == "holding"


def test_trend_spans_first_to_last_across_the_whole_window():
    trend = compute_trend([_run("t1", 100), _run("t2", 90), _run("t3", 95)])
    # first→last, not adjacent diffs: 100 → 95
    assert trend["score"] == {"first": 100, "last": 95, "change": -5}
    assert trend["posture"] == "regressing"


def test_trend_reports_coverage_movement_first_to_last():
    """The monotone-coverage progress a bounded recheck drives (H55/H83) shows in
    the trend: more verifiable items came to carry a verdict across the window."""
    trend = compute_trend(
        [_run("t1", 100, verified=1, total=4), _run("t3", 100, verified=4, total=4)]
    )
    # 1 → 4 verified, denominator steady: the library got more covered
    assert trend["coverage_change"] == {"verified": 3, "total": 0}
    # coverage rising does NOT change the integrity-first posture (no drift, no
    # score move → holding); coverage is a separate reported axis.
    assert trend["posture"] == "holding"


def test_trend_coverage_total_grows_as_verifiable_items_are_added():
    # new captures widen the verifiable denominator first→last (Δtotal > 0)
    trend = compute_trend(
        [_run("t1", 100, verified=2, total=2), _run("t2", 100, verified=2, total=5)]
    )
    assert trend["coverage_change"] == {"verified": 0, "total": 3}


def test_trend_coverage_movement_is_independent_of_the_posture():
    """Coverage falling (a re-verify is overdue) while integrity holds is still
    `holding` — coverage is reported, never an integrity-posture trigger (H46)."""
    trend = compute_trend(
        [_run("t1", 100, verified=4, total=4), _run("t2", 100, verified=2, total=4)]
    )
    assert trend["coverage_change"] == {"verified": -2, "total": 0}
    assert trend["posture"] == "holding"


def test_trend_coverage_reads_zero_for_a_pre_h115_endpoint():
    """A window endpoint recorded before H115 (no `coverage` axis) reads 0, so the
    coverage movement is still computed, never a crash."""
    pre = {"recorded_at": "t1", "snapshot": {"score": 100, "drift": {}}, "delta": {}}
    trend = compute_trend([pre, _run("t2", 100, verified=3, total=3)])
    assert trend["coverage_change"] == {"verified": 3, "total": 3}


def test_trend_reports_enrichment_and_summary_staleness_movement():
    """The re-derivability debt trajectory (H131): the net first→last movement in
    the stale-classification / stale-summary counts, so a worker reading `--trend`
    sees whether a `classify --stale` / `kb --stale` refresh is becoming overdue."""
    trend = compute_trend(
        [
            _run("t1", 100, enrichment_stale=1, summaries_stale=0),
            _run("t3", 100, enrichment_stale=3, summaries_stale=2),
        ]
    )
    # 1 → 3 stale classifications, 0 → 2 stale summaries across the span
    assert trend["stale_change"] == {"enrichment": 2, "summaries": 2}


def test_trend_staleness_movement_is_independent_of_the_posture():
    """Rising enrichment/summary staleness is a re-derivability signal, not an
    integrity loss — the category/summary is still *held*. A steady score with no
    drift is still `holding` even as the stale debt grows (the H115 coverage rule,
    on the staleness axis): `stale_change` is reported, never a `posture` trigger."""
    trend = compute_trend(
        [
            _run("t1", 100, enrichment_stale=0, summaries_stale=0),
            _run("t2", 100, enrichment_stale=5, summaries_stale=4),
        ]
    )
    assert trend["stale_change"] == {"enrichment": 5, "summaries": 4}
    assert trend["posture"] == "holding"


def test_trend_staleness_can_clear_across_the_window():
    """A refresh (`classify --stale` / `kb --stale`) between runs clears the debt:
    a negative `stale_change` is the honest 'getting less stale' direction."""
    trend = compute_trend(
        [
            _run("t1", 100, enrichment_stale=3, summaries_stale=2),
            _run("t2", 100, enrichment_stale=0, summaries_stale=0),
        ]
    )
    assert trend["stale_change"] == {"enrichment": -3, "summaries": -2}
    assert trend["posture"] == "holding"


def test_trend_staleness_reads_zero_for_a_pre_tracking_endpoint():
    """A window endpoint recorded before the snapshot tracked the stale scalars (an
    older schema) reads 0 for the missing axis, so the movement is still computed,
    never a crash (the missing-axis-zero posture, ADR 0082)."""
    pre = {"recorded_at": "t1", "snapshot": {"score": 100, "drift": {}}, "delta": {}}
    trend = compute_trend([pre, _run("t2", 100, enrichment_stale=2, summaries_stale=1)])
    assert trend["stale_change"] == {"enrichment": 2, "summaries": 1}


# --- the repair suggestions (pure mapping, roadmap H40) -------------------


def _full_doctor_report(
    *,
    duplicates=0,
    missing_scrolls=0,
    missing_media=0,
    orphan_scrolls=0,
    fts_in_sync=True,
    enrichment_stale=0,
    summaries_stale=0,
):
    """A doctor report shaped like `run_doctor`'s — the full surface
    `suggest_repairs` reads, not just the distilled custody scalars."""

    def _found(n):
        return [{"status": "found"} for _ in range(n)]

    return {
        "issues": duplicates + missing_scrolls + missing_media + orphan_scrolls
        + (0 if fts_in_sync else 1),
        "duplicates": _found(duplicates),
        "missing_scrolls": _found(missing_scrolls),
        "missing_media": _found(missing_media),
        "orphan_scrolls": _found(orphan_scrolls),
        "fts": {"in_sync": True if fts_in_sync else False, "status": "ok"},
        "custody": {
            "enrichment": {"stale": enrichment_stale},
            "summaries": {"stale": summaries_stale},
        },
    }


def test_suggest_repairs_on_a_clean_report_is_empty():
    # G1 honest absence: nothing to fix → no suggestions, never a fabricated one.
    assert suggest_repairs(_full_doctor_report()) == []


def test_suggest_repairs_groups_the_three_structural_fixes_under_doctor_fix():
    # duplicates / missing scrolls / out-of-sync FTS all close with one command —
    # so they share a single `doctor --fix` suggestion, not three identical ones.
    suggested = suggest_repairs(
        _full_doctor_report(duplicates=2, missing_scrolls=1, fts_in_sync=False)
    )
    assert suggested == [
        {
            "command": "scrolls doctor --fix",
            "addresses": ["duplicates", "missing_scrolls", "fts"],
        }
    ]


def test_suggest_repairs_lists_only_the_structural_categories_present():
    # `addresses` names exactly the findings present, not the whole repair set.
    suggested = suggest_repairs(_full_doctor_report(missing_scrolls=1))
    assert suggested == [
        {"command": "scrolls doctor --fix", "addresses": ["missing_scrolls"]}
    ]


def test_suggest_repairs_routes_missing_media_to_the_media_command():
    # missing media is doctor-detected but `scrolls media` (network) repairs it,
    # never `doctor --fix` — so it is its own suggestion.
    assert suggest_repairs(_full_doctor_report(missing_media=3)) == [
        {"command": "scrolls media", "addresses": ["missing_media"]}
    ]


def test_suggest_repairs_routes_stale_enrichment_and_summaries():
    suggested = suggest_repairs(
        _full_doctor_report(enrichment_stale=2, summaries_stale=1)
    )
    assert suggested == [
        {"command": "scrolls classify --stale", "addresses": ["enrichment_stale"]},
        {"command": "scrolls kb --stale", "addresses": ["summaries_stale"]},
    ]


def test_suggest_repairs_omits_orphan_scrolls_which_have_no_repair_command():
    # The load-bearing decision: an orphan scroll bumps `issues` (nonzero exit)
    # but doctor never deletes a file it cannot prove it wrote (custody §2.4), so
    # there is no on-request command to suggest. maintain names a command only
    # when one actually closes the gap — never `doctor --fix` for an orphan it
    # would not remove.
    report = _full_doctor_report(orphan_scrolls=1)
    assert report["issues"] == 1
    assert suggest_repairs(report) == []


def test_suggest_repairs_is_ordered_command_first_then_the_custody_refreshes():
    # A library with every kind of gap: a deterministic, fixed command order —
    # structural repair, media, then the two enrichment refreshes.
    suggested = suggest_repairs(
        _full_doctor_report(
            duplicates=1,
            missing_media=1,
            enrichment_stale=1,
            summaries_stale=1,
        )
    )
    assert [s["command"] for s in suggested] == [
        "scrolls doctor --fix",
        "scrolls media",
        "scrolls classify --stale",
        "scrolls kb --stale",
    ]


# --- the command (offline, dogfood-style) ---------------------------------

TOPIC = "transformer"


def _rendered(source, source_id, url, **fields) -> ScrollItem:
    base = dict(
        id=make_item_id(source, source_id, url),
        source=source,
        source_id=source_id,
        url=url,
        saved_at="2026-06-14T00:00:00+00:00",
        content_hash="sha256:" + (source_id or url)[-8:],
        raw_text=f"<raw capture of {url}>",
        stage="rendered",
        provenance={"adapter": source, "fetched_at": "2026-06-14T00:00:05+00:00"},
    )
    base.update(fields)
    return ScrollItem(**base)


def _held_topic() -> list[ScrollItem]:
    return [
        _rendered(
            "arxiv", "1706.03762", "https://arxiv.org/abs/1706.03762",
            title="Attention Is All You Need",
            extracted_text="The Transformer uses attention to model sequences.",
            category="paper", domain="machine learning",
            concepts=("Transformer", "Attention"), tags=("cs.CL",),
        ),
        _rendered(
            "web", None, "https://example.com/transformer-explained",
            title="The Transformer, Explained",
            extracted_text="A transformer stacks self-attention and feed-forward.",
            category="technique", domain="machine learning",
            concepts=("Transformer",), tags=("explainer",),
        ),
        _rendered(
            "web", None, "https://example.com/scaling-transformers",
            title="Scaling Transformers",
            extracted_text="Larger transformer models keep improving with scale.",
            category="opinion", domain="machine learning",
            concepts=("Transformer",), tags=("scaling",),
        ),
    ]


def _build(items: list[ScrollItem]) -> None:
    paths = get_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    init_db(paths.db_path)
    for item in items:
        rendered = write_scroll(paths, item)
        from scrolls.items import insert_item

        insert_item(paths.db_path, rendered)
    assert main(["kb"]) == 0


def _identity_recapture(item: ScrollItem) -> ScrollItem:
    """Every source comes back byte-identical → every recheck is ``unchanged``."""
    return item


def _recapture_drifting(drift_id: str):
    def recapture(item: ScrollItem) -> ScrollItem:
        if item.id == drift_id:
            return replace(item, content_hash="sha256:drifted-upstream")
        return item

    return recapture


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library"))
    return get_paths()


def test_first_maintain_run_audits_rechecks_regenerates_and_records(
    home, monkeypatch, capsys
):
    """The whole pass on a fresh held library: every scroll rechecked clean, the
    KB recompiled, a perfect custody snapshot recorded, and a first-run delta."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    report = json.loads(capsys.readouterr().out)

    # recheck: every held item with a hash re-captured, all unchanged offline
    assert report["recheck"]["checked"] == len(items)
    assert report["recheck"]["unchanged"] == len(items)
    assert report["recheck"]["drifted"] == 0
    # regenerate: the KB recompiled (every rendered item is a page member)
    assert report["compiled"]["items"] == len(items)
    # audit: the post-maintenance custody picture
    assert report["custody"]["score"] == 100
    assert report["custody"]["tiers"] == {"full": len(items), "partial": 0, "reference": 0}
    # delta: first run, no baseline
    assert report["delta"]["first_run"] is True
    assert report["delta"]["score"]["change"] is None
    # the snapshot is recorded under .maintenance/, not as a library page
    snap = load_snapshot(snapshot_path(home))
    assert snap is not None and snap["score"] == 100
    assert snap["recorded_at"] == report["recorded_at"]
    assert not (home.library_dir / ".maintenance").exists()


def test_maintain_report_carries_the_one_line_custody_headline(home, monkeypatch, capsys):
    """The maintain report renders the shared one-line custody headline (H103),
    equal to `snapshot_headline` over the snapshot it records AND to
    `custody_headline` over the post-maintenance library — convergence by
    construction with the `custody` block it sits beside."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    report = json.loads(capsys.readouterr().out)

    # three full-fidelity items, all rechecked clean → verified
    assert report["headline"] == (
        "_Custody: 3 scroll(s) · fidelity full 3 · drift verified 3._"
    )
    # rendered from the recorded snapshot (no second ledger read)
    assert report["headline"] == snapshot_headline(report["custody"])
    # and equal to the shared headline over the post-maintenance held library —
    # so the maintain line can never disagree with the bundle/context/status family
    held = list_items(home.db_path)
    assert report["headline"] == custody_headline(held, latest_events(home.db_path))


def test_maintain_headline_on_an_uninitialized_library_is_zero_scrolls(home, capsys):
    """No library yet → the honest `_Custody: 0 scroll(s)._`, never a fabricated
    count (the first-run/empty honesty the rest of the report keeps)."""
    assert main(["maintain", "--no-recheck"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["headline"] == "_Custody: 0 scroll(s)._"


def test_maintain_history_runs_carry_the_custody_headline(home, monkeypatch, capsys):
    """Each `--history` run renders the same one-line headline from its recorded
    snapshot — derived at read time, so the stored log stays the bare
    `{recorded_at, snapshot, delta}` (a pre-H103 entry would render one too)."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    capsys.readouterr()
    assert main(["maintain", "--all"]) == 0
    capsys.readouterr()

    assert main(["maintain", "--history"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert len(printed) == 2
    for run in printed:
        assert run["headline"] == snapshot_headline(run["snapshot"])
    # the headline is a read-time render, not stored in the log
    assert all("headline" not in run for run in read_log(log_path(home)))


def test_maintain_trend_runs_carry_the_custody_headline(home, monkeypatch, capsys):
    """The headline rides the `--trend` envelope's `runs` too, without disturbing
    the `{trend, runs}` shape or the trend computation (which reads only the
    snapshot/recorded_at)."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    capsys.readouterr()
    assert main(["maintain", "--all"]) == 0
    capsys.readouterr()

    assert main(["maintain", "--history", "--trend"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"trend", "runs"}
    for run in payload["runs"]:
        assert run["headline"] == snapshot_headline(run["snapshot"])


def test_second_run_shows_drift_in_the_delta_without_lowering_the_score(
    home, monkeypatch, capsys
):
    """Run once clean, then again after a source drifts: the delta records the
    drift posture moving (unverified → drifted) while the score holds at 100.

    The second pass uses `--all` to force a whole-library recheck: the default
    stale-bounded recheck (H83) would skip every item just seen in the first
    run, so detecting a fresh drift means re-verifying everything explicitly."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    first = json.loads(capsys.readouterr().out)
    drifted = items[0]
    before = get_item(home.db_path, drifted.id)

    monkeypatch.setattr(cli, "live_recapture", _recapture_drifting(drifted.id))
    assert main(["maintain", "--all"]) == 0
    second = json.loads(capsys.readouterr().out)

    assert second["recheck"]["drifted"] == 1
    assert second["delta"]["first_run"] is False
    assert second["delta"]["since"] == first["recorded_at"]
    # the sharp custody point: drift moved, integrity did not
    assert second["delta"]["score"] == {"before": 100, "after": 100, "change": 0}
    assert second["delta"]["drift"]["drifted"]["change"] == 1
    assert second["custody"]["score"] == 100
    # the capture itself is never clobbered by a drift verdict (custody §2.4)
    assert get_item(home.db_path, drifted.id) == before


def test_no_recheck_skips_the_live_edge_but_still_regenerates_and_audits(
    home, capsys
):
    """`--no-recheck` is the fully offline pass: no re-capture (no network seam
    touched), but views are still regenerated and a snapshot recorded."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    # no live_recapture monkeypatch: --no-recheck must not touch the seam
    assert main(["maintain", "--no-recheck"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["recheck"]["skipped"] is True
    assert report["recheck"]["checked"] == 0
    assert report["compiled"]["items"] == len(items)
    assert report["custody"]["score"] == 100
    # nothing was verified, so the drift posture stays fully unverified
    assert report["custody"]["drift"]["unverified"] == len(items)
    assert load_snapshot(snapshot_path(home))["score"] == 100


def test_limit_bounds_the_recheck(home, monkeypatch, capsys):
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain", "--limit", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["recheck"]["checked"] == 1


def test_bounded_recheck_checks_the_never_checked_before_the_already_verified(
    home, monkeypatch, capsys
):
    """A `--limit`-bounded pass spends its budget on never-checked items, not on
    re-verifying the already-verified head (roadmap H55 coverage-first order)."""
    items = _held_topic()
    _build(items)
    # pre-seed an OLD verdict on the item that sorts *first* in list order, so the
    # old (list-order) recheck would re-verify it; coverage-first must skip it.
    ordered = list_items(home.db_path)
    head = ordered[0]
    record_events(
        home.db_path,
        [CustodyEvent(head.id, "2026-06-01T00:00:00+00:00", "unchanged",
                      head.content_hash, head.content_hash)],
    )
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain", "--limit", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["recheck"]["checked"] == 1

    verdicts = latest_events(home.db_path)
    # the already-verified head was NOT rechecked — its OLD verdict stands
    assert verdicts[head.id].checked_at == "2026-06-01T00:00:00+00:00"
    # and a never-checked item now carries a verdict (coverage advanced)
    never_checked = [i for i in ordered if i.id != head.id]
    assert sum(i.id in verdicts for i in never_checked) == 1


def test_a_bounded_pass_advances_custody_coverage_each_run(home, monkeypatch, capsys):
    """Successive `--limit 1` passes monotonically shrink the unverified set —
    every run checks something new until the whole library is covered."""
    items = _held_topic()  # three held items, none verified yet
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    coverage = []
    for _ in range(len(items)):
        assert main(["maintain", "--limit", "1"]) == 0
        report = json.loads(capsys.readouterr().out)
        coverage.append(report["custody"]["drift"]["unverified"])
    # 3 → 2 → 1 → 0 across three bounded passes (strictly decreasing, reaches 0)
    assert coverage == [len(items) - 1 - n for n in range(len(items))]
    assert coverage[-1] == 0


# --- recheck coverage in the report (roadmap H109) ------------------------


def test_recheck_report_carries_coverage_over_the_verifiable_set(
    home, monkeypatch, capsys
):
    """The recheck report's `coverage` member reports `{verified, total}` over the
    held, hash-bearing items — after one whole pass every item carries a verdict."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    report = json.loads(capsys.readouterr().out)
    # every held item here is hash-bearing, and the first pass rechecks them all
    assert report["recheck"]["coverage"] == {"verified": len(items), "total": len(items)}


def test_coverage_is_post_recheck_and_advances_within_a_bounded_pass(
    home, monkeypatch, capsys
):
    """The coverage in a pass's report reflects that pass's work (post-recheck):
    each bounded run's `verified` climbs by what it just covered, visible directly
    in the report rather than only in the *next* run's unverified count."""
    items = _held_topic()  # three held, none verified
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    verified = []
    for _ in range(len(items)):
        assert main(["maintain", "--limit", "1"]) == 0
        report = json.loads(capsys.readouterr().out)
        cov = report["recheck"]["coverage"]
        assert cov["total"] == len(items)
        verified.append(cov["verified"])
    # 1 → 2 → 3 across three bounded passes (monotone, reaches full coverage)
    assert verified == [n + 1 for n in range(len(items))]


def test_coverage_converges_with_the_doctor_audit(home, monkeypatch, capsys):
    """Coverage and the post-maintenance audit can never disagree: `verified`
    equals the drift block's `checked`, and `total − verified` equals its
    `unverified` (every held item here is hash-bearing) — both from one
    `unverified_items` predicate."""
    items = _held_topic()
    _build(items)
    # pre-verify one item so the first pass leaves a real verified/unverified mix
    # under a bound that stops short of the whole set
    head = list_items(home.db_path)[0]
    record_events(
        home.db_path,
        [CustodyEvent(head.id, "2026-06-10T00:00:00+00:00", "unchanged",
                      head.content_hash, head.content_hash)],
    )
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain", "--limit", "1"]) == 0  # checks one never-checked item
    report = json.loads(capsys.readouterr().out)

    cov = report["recheck"]["coverage"]
    drift = report["custody"]["drift"]
    assert cov["verified"] == drift["checked"]
    assert cov["total"] - cov["verified"] == drift["unverified"]


def test_no_recheck_still_reports_coverage(home, monkeypatch, capsys):
    """`--no-recheck` runs no live edge but still reads and reports coverage —
    a read, not a re-capture (H109). With nothing verified it is 0 of M."""
    items = _held_topic()
    _build(items)
    # verify one item up front, so the read shows a partial coverage, not zero
    head = list_items(home.db_path)[0]
    record_events(
        home.db_path,
        [CustodyEvent(head.id, "2026-06-10T00:00:00+00:00", "unchanged",
                      head.content_hash, head.content_hash)],
    )
    capsys.readouterr()

    # no live_recapture monkeypatch: --no-recheck must not touch the seam
    assert main(["maintain", "--no-recheck"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["recheck"]["skipped"] is True
    assert report["recheck"]["coverage"] == {"verified": 1, "total": len(items)}
    # and it agrees with the audit it did not mutate
    drift = report["custody"]["drift"]
    cov = report["recheck"]["coverage"]
    assert cov["verified"] == drift["checked"]


def test_coverage_excludes_reference_only_items_from_the_denominator(
    home, monkeypatch, capsys
):
    """A reference-only item (no content hash) is unverifiable, so it is neither
    verified nor counted in `total` — coverage measures progress over what can
    actually be covered and so can reach full coverage."""
    held = _held_topic()
    # turn one held item into a reference-only capture (no baseline hash)
    held[0] = replace(held[0], content_hash=None, raw_text=None, extracted_text=None)
    _build(held)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    report = json.loads(capsys.readouterr().out)
    verifiable = len(held) - 1  # the reference-only item is excluded
    assert report["recheck"]["coverage"] == {"verified": verifiable, "total": verifiable}


# --- recheck coverage in the snapshot / trend (roadmap H115) --------------


def test_snapshot_and_log_record_recheck_coverage(home, monkeypatch, capsys):
    """The recorded snapshot (and the appended log entry) carry the recheck
    `coverage` fraction, so `--history`/`--trend` can replay it — not just the
    point-in-time figure on one pass's report (H109). The recorded coverage is
    the post-maintenance audit's, which converges with the live recheck report's
    (H113), so the two figures the one pass prints agree."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain", "--limit", "1"]) == 0
    report = json.loads(capsys.readouterr().out)

    # one item rechecked → 1 of 3 verifiable covered, recorded in the snapshot
    assert report["custody"]["coverage"] == {"verified": 1, "total": len(items)}
    snap = load_snapshot(snapshot_path(home))
    assert snap["coverage"] == {"verified": 1, "total": len(items)}
    logged = read_log(log_path(home))
    assert logged[-1]["snapshot"]["coverage"] == {"verified": 1, "total": len(items)}
    # the snapshot coverage (the audit's) converges with the live recheck's (H113)
    assert report["recheck"]["coverage"] == report["custody"]["coverage"]


def test_history_and_trend_show_coverage_advancing_across_runs(
    home, monkeypatch, capsys
):
    """Two bounded passes verify the never-checked tail one item at a time; the
    `--history` runs replay each pass's recorded coverage and `--trend` reports
    the net coverage movement — 'is the library getting more covered?'."""
    items = _held_topic()  # three held items, none verified
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain", "--limit", "1"]) == 0  # covers 1 of 3
    capsys.readouterr()
    assert main(["maintain", "--limit", "1"]) == 0  # the stale (never-checked) tail
    capsys.readouterr()

    # --history: each recorded run carries its own coverage fraction
    assert main(["maintain", "--history"]) == 0
    runs = json.loads(capsys.readouterr().out)
    assert [r["snapshot"]["coverage"]["verified"] for r in runs] == [1, 2]
    assert all(r["snapshot"]["coverage"]["total"] == len(items) for r in runs)

    # --trend: net coverage movement first→last (1 → 2 verified, denominator held)
    assert main(["maintain", "--history", "--trend"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["trend"]["coverage_change"] == {"verified": 1, "total": 0}
    # coverage rising does not move the integrity-first posture (no drift here)
    assert payload["trend"]["posture"] == "holding"


def test_trend_reports_enrichment_staleness_accumulating_across_runs(home, capsys):
    """End-to-end (H131): an item classified under a superseded ruleset appears
    between two offline passes, so the recorded snapshots carry `enrichment_stale`
    0 → 1; `--trend` reports the net `stale_change` (the re-derivability debt is
    accumulating) while the integrity-first `posture` stays `holding` — a held
    category under an old ruleset is debt to refresh, not a custody regression."""
    from scrolls.classify import ENGINE

    items = _held_topic()
    _build(items)
    capsys.readouterr()

    # pass 1 (offline): a clean library, no stale enrichment yet
    assert main(["maintain", "--no-recheck"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["custody"]["enrichment_stale"] == 0

    # one item's category was produced under a now-superseded ruleset
    target = list_items(home.db_path)[0]
    stale = replace(
        target,
        provenance={
            **(target.provenance or {}),
            "classified_by": ENGINE,
            "classified_basis": "title-pattern",
            "classified_ruleset": "superseded-fingerprint",
        },
    )
    assert update_item(home.db_path, stale)

    # pass 2 (offline): the audit now counts one stale classification
    assert main(["maintain", "--no-recheck"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["custody"]["enrichment_stale"] == 1

    # --history replays each pass's recorded staleness scalar
    assert main(["maintain", "--history"]) == 0
    runs = json.loads(capsys.readouterr().out)
    assert [r["snapshot"]["enrichment_stale"] for r in runs] == [0, 1]

    # --trend: net first→last movement — debt accumulating, posture unchanged
    assert main(["maintain", "--history", "--trend"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["trend"]["stale_change"] == {"enrichment": 1, "summaries": 0}
    assert payload["trend"]["posture"] == "holding"  # not an integrity regression


def test_unbounded_recheck_checks_the_whole_set_regardless_of_prior_verdicts(
    home, monkeypatch, capsys
):
    """The coverage-first ordering only reorders: an *unbounded* pass still checks
    every held item, so the counts are unchanged even with a pre-existing verdict."""
    items = _held_topic()
    _build(items)
    head = list_items(home.db_path)[0]
    record_events(
        home.db_path,
        [CustodyEvent(head.id, "2026-06-01T00:00:00+00:00", "unchanged",
                      head.content_hash, head.content_hash)],
    )
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain", "--all"]) == 0  # no --limit
    report = json.loads(capsys.readouterr().out)
    # every held item rechecked (the already-verified head included), all unchanged
    assert report["recheck"]["checked"] == len(items)
    assert report["recheck"]["unchanged"] == len(items)
    assert report["custody"]["drift"]["unverified"] == 0


# --- the stale-bounded recheck (roadmap H83) ------------------------------


def test_recheck_targets_only_the_stale_set_within_a_boundary(home, monkeypatch):
    """With a boundary, `_recheck_held_items` re-verifies only the items not seen
    since it — an older verdict (stale) or no verdict (never checked) — and
    leaves a fresh, post-boundary verdict untouched."""
    _build(_held_topic())
    old, recent, never = list_items(home.db_path)
    record_events(home.db_path, [
        CustodyEvent(old.id, "2026-06-01T00:00:00+00:00", "unchanged",
                     old.content_hash, old.content_hash),
        CustodyEvent(recent.id, "2026-06-10T00:00:00+00:00", "unchanged",
                     recent.content_hash, recent.content_hash),
    ])  # `never` has no verdict at all

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    report = cli._recheck_held_items(
        home, limit=None, now="2026-06-17T00:00:00+00:00",
        boundary="2026-06-05T00:00:00+00:00",
    )
    assert report["scope"] == "stale"
    assert report["since"] == "2026-06-05T00:00:00+00:00"
    assert report["checked"] == 2  # `old` (pre-boundary) + `never`, not `recent`

    verdicts = latest_events(home.db_path)
    assert verdicts[recent.id].checked_at == "2026-06-10T00:00:00+00:00"  # untouched
    assert verdicts[old.id].checked_at == "2026-06-17T00:00:00+00:00"  # re-verified
    assert verdicts[never.id].checked_at == "2026-06-17T00:00:00+00:00"  # re-verified


def test_recheck_with_no_boundary_rechecks_everything(home, monkeypatch):
    """boundary=None is the `--all` / first-run path — every held item rechecked,
    scope `all`, since null, even past a fresh prior verdict (no behavior change
    from before H83)."""
    items = _held_topic()
    _build(items)
    head = list_items(home.db_path)[0]
    record_events(home.db_path, [
        CustodyEvent(head.id, "2026-06-10T00:00:00+00:00", "unchanged",
                     head.content_hash, head.content_hash),
    ])

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    report = cli._recheck_held_items(
        home, limit=None, now="2026-06-17T00:00:00+00:00", boundary=None,
    )
    assert report["scope"] == "all"
    assert report["since"] is None
    assert report["checked"] == len(items)


def test_first_run_rechecks_everything_then_the_default_skips_the_just_seen(
    home, monkeypatch, capsys
):
    """The headline H83 behavior end to end: the first pass (no baseline) rechecks
    every held item; a second default pass right after is stale-bounded to the
    first run's recorded_at, so nothing is stale and no item is re-verified — the
    pass does the *new* work (none here), not the whole library again."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["recheck"]["scope"] == "all"  # first run: no baseline
    assert first["recheck"]["since"] is None
    assert first["recheck"]["checked"] == len(items)

    assert main(["maintain"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["recheck"]["scope"] == "stale"
    assert second["recheck"]["since"] == first["recorded_at"]
    assert second["recheck"]["checked"] == 0  # everything was just seen
    # views still regenerated, audit still run — only the live recheck is bounded
    assert second["compiled"]["items"] == len(items)
    assert second["custody"]["score"] == 100


def test_all_flag_rechecks_everything_again_after_a_clean_default_pass(
    home, monkeypatch, capsys
):
    """`--all` recovers the pre-H83 whole-library recheck: after a default pass
    leaves nothing stale, `--all` re-verifies every held item regardless."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    capsys.readouterr()

    assert main(["maintain", "--all"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["recheck"]["scope"] == "all"
    assert report["recheck"]["since"] is None
    assert report["recheck"]["checked"] == len(items)


def test_all_composes_with_limit(home, monkeypatch, capsys):
    """`--all --limit N` is the old `--limit N`: a bounded whole-library recheck,
    coverage-first — so it reaches items the stale default would skip."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    capsys.readouterr()

    assert main(["maintain", "--all", "--limit", "2"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["recheck"]["scope"] == "all"
    assert report["recheck"]["checked"] == 2


def test_all_conflicts_with_no_recheck(home, capsys):
    """`--all` runs a recheck `--no-recheck` would skip — a usage error (exit 2),
    not a silently-ignored flag (the `--trend requires --history` precedent)."""
    assert main(["maintain", "--all", "--no-recheck"]) == 2
    error = json.loads(capsys.readouterr().err)["error"].lower()
    assert "all" in error and "no-recheck" in error


def test_all_conflicts_with_history(home, capsys):
    """`--all` runs a pass; `--history` is read-only — mutually exclusive."""
    assert main(["maintain", "--all", "--history"]) == 2
    error = json.loads(capsys.readouterr().err)["error"].lower()
    assert "all" in error and "history" in error


def test_no_recheck_and_limit_together_is_an_error(home, capsys):
    # --limit bounds a recheck that --no-recheck skips: mutually exclusive, so
    # argparse rejects the pair with a usage error (SystemExit(2)).
    with pytest.raises(SystemExit) as exc:
        main(["maintain", "--no-recheck", "--limit", "2"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "limit" in err.lower() and "recheck" in err.lower()


def test_maintain_is_idempotent_on_a_clean_library(home, monkeypatch, capsys):
    """Two clean passes in a row leave the score at 100 and the drift change at
    zero — maintain regenerates and records, it never churns custody."""
    items = _held_topic()
    _build(items)
    rows = {i.id: item_to_dict(i) for i in list_items(home.db_path)}
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    capsys.readouterr()
    assert main(["maintain"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["custody"]["score"] == 100
    assert second["delta"]["score"]["change"] == 0
    assert second["delta"]["drift"]["unchanged"]["change"] == 0
    # item rows are untouched: maintain never rewrites the capture
    assert {i.id: item_to_dict(i) for i in list_items(home.db_path)} == rows


def test_structural_drift_makes_maintain_exit_nonzero(home, monkeypatch, capsys):
    """An orphan scroll is structural drift `doctor` reports but never auto-fixes;
    maintain surfaces it with a nonzero exit (run `doctor --fix`)."""
    items = _held_topic()
    _build(items)
    (home.scrolls_dir / "orphan.md").write_text("# stray\n", encoding="utf-8")
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["issues"] >= 1
    # custody score is still 100 — an orphan file is not a custody loss
    assert report["custody"]["score"] == 100


# --- the repair suggestions, end to end (roadmap H40) ---------------------


def test_maintain_suggests_no_repairs_on_a_clean_library(home, monkeypatch, capsys):
    """A healthy pass names no command — the `suggested` block is the honest
    empty list, never a fabricated suggestion (G1)."""
    _build(_held_topic())
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["suggested"] == []


def test_maintain_suggests_doctor_fix_for_a_missing_scroll_but_never_runs_it(
    home, monkeypatch, capsys
):
    """A deleted scroll file is a structural issue `doctor --fix` rewrites. maintain
    names that command (actionable guidance) but never runs it — the missing scroll
    persists, the exit is nonzero, and the capture is untouched (custody §2.4)."""
    items = _held_topic()
    _build(items)
    gone = get_item(home.db_path, items[0].id)  # persisted: carries markdown_path
    (home.root / gone.markdown_path).unlink()
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["suggested"] == [
        {"command": "scrolls doctor --fix", "addresses": ["missing_scrolls"]}
    ]
    # maintain suggested the repair; it did not perform it — the scroll is still gone
    assert not (home.root / gone.markdown_path).exists()


def test_maintain_suggests_nothing_for_an_orphan_despite_a_nonzero_exit(
    home, monkeypatch, capsys
):
    """The honest-absence counterpart of the missing-scroll case: an orphan scroll
    exits nonzero but has no on-request repair (doctor never deletes user files),
    so maintain names no command rather than pointing at a `doctor --fix` that
    would not remove it."""
    _build(_held_topic())
    (home.scrolls_dir / "orphan.md").write_text("# stray\n", encoding="utf-8")
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["issues"] >= 1
    assert report["suggested"] == []


def test_maintain_suggests_classify_stale_for_a_stale_classification(
    home, monkeypatch, capsys
):
    """A category produced under a superseded ruleset is report-only drift (no
    `issues`, exit 0), but maintain names the explicit refresh `classify --stale`
    that re-derives it — the enrichment-axis suggestion, wired through the real
    doctor custody block."""
    items = _held_topic()
    _build(items)
    persisted = get_item(home.db_path, items[1].id)
    stale = replace(
        persisted,
        provenance={
            **persisted.provenance,
            "classified_by": "rules-v1",
            "classified_basis": "title-pattern",
            "classified_ruleset": "deadbeef0000",  # a fingerprint the live ruleset superseded
        },
    )
    update_item(home.db_path, stale)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0  # stale enrichment is reported, never a failure
    report = json.loads(capsys.readouterr().out)
    assert report["custody"]["enrichment_stale"] == 1
    assert report["suggested"] == [
        {"command": "scrolls classify --stale", "addresses": ["enrichment_stale"]}
    ]


def test_maintain_history_does_not_carry_suggestions(home, monkeypatch, capsys):
    """`suggested` rides the live pass, not the recorded snapshot: the structural
    findings it routes are point-in-time, so `--history` (which replays snapshots)
    never carries a stale suggestion."""
    _build(_held_topic())
    capsys.readouterr()
    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    capsys.readouterr()

    assert main(["maintain", "--history"]) == 0
    runs = json.loads(capsys.readouterr().out)
    assert runs and all("suggested" not in run for run in runs)
    assert all("suggested" not in run["snapshot"] for run in runs)


# --- per-source custody breakdown in the report (roadmap H123) -------------


def _by_source_report(by_source):
    """A doctor report carrying just the per-source custody breakdown."""
    return {"custody": {"by_source": by_source}}


def test_report_by_source_threads_the_doctor_audits_breakdown():
    # The pure layer is a faithful read of the per-source map the audit produces.
    by_source = {
        "arxiv": {"tiers": {"full": 1}, "drift": {"verified": 1}},
        "web": {"tiers": {"full": 2}, "drift": {"verified": 2}},
    }
    assert report_by_source(_by_source_report(by_source)) == by_source


def test_report_by_source_on_a_report_without_a_breakdown_is_the_empty_map():
    # Forward-compat / empty library: an absent block reads as the honest empty
    # map, never a KeyError (the snapshot's degrade-safely posture, this axis).
    assert report_by_source({"custody": {}}) == {}
    assert report_by_source({}) == {}


def test_maintain_report_carries_the_per_source_custody_breakdown(
    home, monkeypatch, capsys
):
    """The report names each source's own custody tally — the per-source picture
    the audit (`run_doctor`) already produces (H104), surfaced so an unattended
    log shows *which* source's custody to target without re-running doctor."""
    items = _held_topic()  # 1 arxiv + 2 web, all full-fidelity
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    report = json.loads(capsys.readouterr().out)

    by_source = report["by_source"]
    # sorted source keys, one tally each (every recheck clean → verified)
    assert list(by_source) == ["arxiv", "web"]
    assert by_source["arxiv"]["tiers"]["full"] == 1
    assert by_source["arxiv"]["drift"]["verified"] == 1
    assert by_source["web"]["tiers"]["full"] == 2
    assert by_source["web"]["drift"]["verified"] == 2
    # it is exactly the breakdown this pass's doctor audit produces (no new read)
    assert by_source == run_doctor(home)["custody"]["by_source"]


def test_maintain_per_source_breakdown_sums_to_the_whole_library_custody_block(
    home, monkeypatch, capsys
):
    """The H104 sum-to-whole posture on the maintenance surface: summing the
    per-source tiers/postures re-counts the whole library — every item lands in
    exactly one source group — so `by_source` can never disagree with the
    `custody` block it sits beside (the documented `verified ≡ unchanged`)."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()
    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    capsys.readouterr()
    # drift one web item so a source carries a non-trivial posture mix
    drifted = items[1]  # a web item
    monkeypatch.setattr(cli, "live_recapture", _recapture_drifting(drifted.id))
    assert main(["maintain", "--all"]) == 0
    report = json.loads(capsys.readouterr().out)

    by_source = report["by_source"]
    # tiers: summing the per-source tiers equals the whole-library `custody.tiers`
    summed_tiers: dict[str, int] = {}
    for tally in by_source.values():
        for tier, n in tally["tiers"].items():
            summed_tiers[tier] = summed_tiers.get(tier, 0) + n
    assert summed_tiers == report["custody"]["tiers"]
    # postures sum to the whole-library drift block (verified ≡ unchanged)
    summed_drift: dict[str, int] = {}
    for tally in by_source.values():
        for posture, n in tally["drift"].items():
            summed_drift[posture] = summed_drift.get(posture, 0) + n
    whole = report["custody"]["drift"]
    assert summed_drift["verified"] == whole["unchanged"]
    assert summed_drift["drifted"] == whole["drifted"]
    assert summed_drift["unverified"] == whole["unverified"]
    # the web source carries the drift; the map equals the canonical per-source
    # tally over the held library (so it can never desync from custody_counts)
    assert by_source["web"]["drift"]["drifted"] == 1
    held = list_items(home.db_path)
    assert by_source == custody_counts_by_source(held, latest_events(home.db_path))


def test_maintain_per_source_breakdown_on_an_uninitialized_library_is_empty(
    home, capsys
):
    """No library yet → the honest empty map (no source stands out), the
    first-run/empty honesty the rest of the report keeps."""
    assert main(["maintain", "--no-recheck"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["by_source"] == {}


def test_maintain_history_does_not_carry_the_per_source_breakdown(
    home, monkeypatch, capsys
):
    """`by_source` rides the live pass, not the recorded snapshot: it is derived
    fresh from this pass's audit (like `suggested` H40 and `scope`/`since` H83),
    so `--history` (which replays snapshots) carries none and the log stays bare."""
    _build(_held_topic())
    capsys.readouterr()
    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    capsys.readouterr()

    assert main(["maintain", "--history"]) == 0
    runs = json.loads(capsys.readouterr().out)
    assert runs and all("by_source" not in run for run in runs)
    assert all("by_source" not in run["snapshot"] for run in runs)
    # and not stored in the log either (the snapshot/log carry only the scalars)
    assert all("by_source" not in run for run in read_log(log_path(home)))


# --- the single weakest source: `attention` (roadmap H119) ------------------


def _source_tally(*, full=0, partial=0, reference=0,
                  verified=0, unverified=0, drifted=0, rotted=0, error=0):
    """One source's `{tiers, drift}` tally, shaped like `custody_counts`."""
    return {
        "tiers": {"full": full, "partial": partial, "reference": reference},
        "drift": {"verified": verified, "unverified": unverified,
                  "drifted": drifted, "rotted": rotted, "error": error},
    }


def test_weakest_source_picks_the_most_drifted_and_rotted():
    # The flagged source is the one with the most actionable loss (drifted +
    # rotted), and it carries its own tally plus a one-line reason naming the loss.
    by_source = {
        "arxiv": _source_tally(full=2, verified=1, drifted=1),  # loss 1
        "web": _source_tally(full=3, drifted=2, rotted=1),       # loss 3 — weakest
    }
    flagged = weakest_source(by_source)
    assert flagged["source"] == "web"
    assert flagged["tiers"] == by_source["web"]["tiers"]
    assert flagged["drift"] == by_source["web"]["drift"]
    assert flagged["reason"] == "2 drifted, 1 rotted"


def test_weakest_source_names_the_recheck_command():
    # roadmap H137: the flagged source carries the exact `verify --source`
    # command to re-check it — the bridge from "which source is weakest" (H119)
    # to the act (`verify --source`, H125), so an unattended worker reads the
    # command without assembling it. Names exactly the flagged source.
    by_source = {
        "arxiv": _source_tally(full=2, verified=1, drifted=1),  # loss 1
        "web": _source_tally(full=3, drifted=2, rotted=1),       # loss 3 — weakest
    }
    flagged = weakest_source(by_source)
    assert flagged["command"] == "scrolls verify --source web"
    assert flagged["command"] == f"scrolls verify --source {flagged['source']}"


def test_weakest_source_tie_broken_by_most_reference_then_name():
    # Equal loss → the lowest-fidelity source (most reference-only) is weaker.
    by_tie_on_reference = {
        "a": _source_tally(full=1, reference=1, drifted=1),  # loss 1, ref 1
        "b": _source_tally(reference=3, drifted=1),          # loss 1, ref 3 — weaker
    }
    assert weakest_source(by_tie_on_reference)["source"] == "b"
    # Equal loss *and* equal reference → deterministic by source name (ascending).
    by_tie_on_name = {
        "zzz": _source_tally(reference=1, drifted=1),
        "aaa": _source_tally(reference=1, drifted=1),
    }
    assert weakest_source(by_tie_on_name)["source"] == "aaa"


def test_weakest_source_on_a_clean_multi_source_library_is_none():
    # Honest absence: ≥2 sources but no source carries any drifted/rotted loss —
    # nothing actionable to flag (reference-only is the normal capture posture, a
    # tie-breaker, never a trigger), so `attention` is null.
    clean = {
        "arxiv": _source_tally(full=2, verified=2),
        "web": _source_tally(full=1, reference=2, verified=1, unverified=2),
    }
    assert weakest_source(clean) is None


def test_weakest_source_on_a_single_source_is_none():
    # A single source does not *stand out* — the whole-library `custody` block
    # already says everything `attention` could, so even with drift it is null.
    assert weakest_source({"web": _source_tally(full=1, drifted=3)}) is None


def test_weakest_source_on_an_empty_map_is_none():
    # No library / no sources → nothing to flag.
    assert weakest_source({}) is None


def test_maintain_report_flags_the_weakest_source(home, monkeypatch, capsys):
    """A live pass names the single source carrying the most actionable loss —
    the one to target a follow-up `verify --drift drifted` / `media` at."""
    items = _held_topic()  # 1 arxiv + 2 web, all full-fidelity
    _build(items)
    capsys.readouterr()
    # first clean pass: every recheck unchanged → no source stands out
    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    assert json.loads(capsys.readouterr().out)["attention"] is None

    # drift one web item: web now carries the only actionable loss
    drifted = items[1]  # a web item
    monkeypatch.setattr(cli, "live_recapture", _recapture_drifting(drifted.id))
    assert main(["maintain", "--all"]) == 0
    report = json.loads(capsys.readouterr().out)

    attention = report["attention"]
    assert attention["source"] == "web"
    assert attention["drift"]["drifted"] == 1
    assert attention["reason"] == "1 drifted"
    # H137: the report names the exact recheck command, not just the source.
    assert attention["command"] == "scrolls verify --source web"
    # a recheck, not a `doctor --fix` repair — it rides `attention`, never the
    # `suggested` repair block (the slice's load-bearing placement decision).
    assert all(
        s["command"] != attention["command"] for s in report["suggested"]
    )
    # it is exactly `weakest_source` over the report's own per-source breakdown
    assert attention == weakest_source(report["by_source"])


def test_maintain_attention_is_null_on_a_clean_or_empty_library(
    home, monkeypatch, capsys
):
    """No drift anywhere (or no library) → honest `attention: null`, the
    first-run/empty honesty the rest of the report keeps."""
    # uninitialized library: no sources to compare
    assert main(["maintain", "--no-recheck"]) == 0
    assert json.loads(capsys.readouterr().out)["attention"] is None

    # initialized, all recheck-clean: ≥2 sources but no actionable loss
    _build(_held_topic())
    capsys.readouterr()
    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    assert json.loads(capsys.readouterr().out)["attention"] is None


def test_maintain_history_does_not_carry_attention(home, monkeypatch, capsys):
    """`attention` rides the live pass only (like `by_source`/`suggested`): it is
    derived fresh from this pass's audit, never recorded, so `--history` carries
    none and the stored log stays bare."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()
    monkeypatch.setattr(cli, "live_recapture", _recapture_drifting(items[1].id))
    assert main(["maintain"]) == 0
    capsys.readouterr()

    assert main(["maintain", "--history"]) == 0
    runs = json.loads(capsys.readouterr().out)
    assert runs and all("attention" not in run for run in runs)
    assert all("attention" not in run["snapshot"] for run in runs)
    assert all("attention" not in run for run in read_log(log_path(home)))


# --- suggest_repairs ≡ what `doctor --fix` actually repairs (roadmap H106) ---
#
# H40 maps each repairable finding category to its on-request command in the
# hand-maintained `_REPAIR_COMMANDS` table; if `doctor`'s `fix=True` path ever
# gains or loses a repairable category, that table could silently drift from
# doctor's real capability — `maintain` would suggest a command that no longer
# closes the gap (the very honesty H40's orphan-omission protects). These pin the
# mapping against doctor's *real* `fix=True` behavior, not just the table.

# The statuses `doctor`'s `fix=True` path stamps when it actually repairs a
# finding: a duplicate group merged, a missing scroll rewritten from the index,
# the FTS index rebuilt. Missing media and orphan scrolls stay `found` — doctor
# reports them but never repairs them.
_REPAIRED_STATUSES = {"merged", "rewritten", "rebuilt"}


def _web(url, *, rendered=False, **fields) -> ScrollItem:
    """A url-hash-identity web item (the kind ADR 0023 duplicates affect)."""
    base = dict(
        id=make_item_id("web", None, url),
        source="web",
        source_id=None,
        url=url,
        saved_at="2026-06-12T08:00:00+00:00",
    )
    if rendered:
        base.update(
            title="A Post",
            extracted_text="body text",
            content_hash="sha256:" + url[-8:],
            raw_text=f"<raw capture of {url}>",
            stage="rendered",
            provenance={"adapter": "web", "fetched_at": "2026-06-12T08:00:05+00:00"},
        )
    base.update(fields)
    return ScrollItem(**base)


def _seed_all_structural_drift(paths) -> None:
    """Seed one library carrying every structural finding `doctor` distinguishes:
    a mergeable duplicate pair, a missing scroll file, an out-of-sync FTS index,
    an orphan scroll file, and a missing captured-media file. Read back via
    `run_doctor` — the point is the drift, not the items."""
    paths.root.mkdir(parents=True, exist_ok=True)
    init_db(paths.db_path)

    # duplicates: junk + clean URL normalize to one canonical id; the junk item
    # carries the content (rendered, with a scroll file) so the merge completes.
    junk = "https://example.com/dup?utm_source=news"
    clean = "https://example.com/dup"
    insert_item(paths.db_path, write_scroll(paths, _web(junk, rendered=True)))
    insert_item(paths.db_path, _web(clean))

    # missing_scrolls: a rendered item whose scroll file is then deleted.
    missing = write_scroll(paths, _web("https://example.com/missing", rendered=True))
    insert_item(paths.db_path, missing)
    (paths.root / missing.markdown_path).unlink()

    # missing_media: a captured ref whose file never landed on disk.
    insert_item(
        paths.db_path,
        _web(
            "https://example.com/with-media",
            rendered=True,
            media=(
                {"type": "photo", "url": "https://example.com/p.jpg",
                 "path": "media/web/p-1.jpg"},
            ),
        ),
    )

    # orphan_scrolls: a stray scroll file with no backing item.
    stray = paths.scrolls_dir / "web" / "stray.md"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("# leftover\n", encoding="utf-8")

    # fts: a phantom index row with no backing item (corrupt last, after inserts).
    conn = sqlite3.connect(paths.db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO items_fts(rowid, title, summary, extracted_text) "
                "VALUES (999, 'ghost', '', '')"
            )
    finally:
        conn.close()


def _categories_doctor_fix_repaired(report: dict) -> set[str]:
    """The finding categories `run_doctor(fix=True)` actually transitioned to a
    repaired status. Generic over the list categories so a future change that
    starts repairing media/orphans (or stops repairing a structural one) shows up
    here, not just in the mapping table."""
    repaired = {
        category
        for category in ("duplicates", "missing_scrolls", "missing_media", "orphan_scrolls")
        if any(entry["status"] in _REPAIRED_STATUSES for entry in report[category])
    }
    if report["fts"]["status"] == "rebuilt":
        repaired.add("fts")
    return repaired


def test_maintain_doctor_fix_suggestion_matches_what_doctor_fix_repairs(home):
    """The set `suggest_repairs` routes to `scrolls doctor --fix` is *exactly* the
    set `run_doctor(fix=True)` actually repairs — so maintain never suggests a
    command that would not close the gap, and never fails to name one that would.
    Pinned against doctor's real fix path, not the `_REPAIR_COMMANDS` table."""
    _seed_all_structural_drift(home)

    # report mode: every structural finding present, nothing mutated.
    before = run_doctor(home)
    by_command = {s["command"]: s["addresses"] for s in suggest_repairs(before)}
    assert "scrolls doctor --fix" in by_command

    # the real fix path, on the same library.
    after = run_doctor(home, fix=True)
    repaired = _categories_doctor_fix_repaired(after)

    assert repaired == {"duplicates", "missing_scrolls", "fts"}
    assert set(by_command["scrolls doctor --fix"]) == repaired


def test_maintain_never_suggests_a_command_for_the_orphan_doctor_cannot_fix(home):
    """An orphan scroll bumps `issues`/the exit code but `fix=True` leaves it
    `found` (doctor never deletes a file it cannot prove it wrote, custody §2.4) —
    so it is in neither set: not repaired, and no `suggested` command names it. The
    H40 honest-absence point, pinned against doctor's real behavior."""
    _seed_all_structural_drift(home)

    after = run_doctor(home, fix=True)
    assert "orphan_scrolls" not in _categories_doctor_fix_repaired(after)
    assert after["orphan_scrolls"], "the seed must carry an orphan to make this non-vacuous"
    assert all(entry["status"] == "found" for entry in after["orphan_scrolls"])

    by_command = {s["command"]: s["addresses"] for s in suggest_repairs(run_doctor(home))}
    assert all("orphan_scrolls" not in addresses for addresses in by_command.values())


def test_maintain_routes_missing_media_to_scrolls_media_which_doctor_fix_leaves(home):
    """The sibling: missing media is doctor-reports-never-fixes — `fix=True` leaves
    it `found`, and `suggest_repairs` routes it to `scrolls media`, never the
    grouped `doctor --fix` suggestion."""
    _seed_all_structural_drift(home)

    after = run_doctor(home, fix=True)
    assert "missing_media" not in _categories_doctor_fix_repaired(after)
    assert after["missing_media"] and all(
        entry["status"] == "found" for entry in after["missing_media"]
    )

    by_command = {s["command"]: s["addresses"] for s in suggest_repairs(run_doctor(home))}
    assert by_command["scrolls media"] == ["missing_media"]
    assert "missing_media" not in by_command.get("scrolls doctor --fix", [])


def test_maintain_on_an_uninitialized_library_is_a_clean_no_op(home, capsys):
    """No library yet: nothing to recheck or compile, and an honest empty audit
    — doctor reports score ``None`` (no library, not a perfect 100). maintain
    never creates a library; it just surfaces that, with a first-run delta."""
    assert main(["maintain", "--no-recheck"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["custody"]["score"] is None
    assert report["compiled"]["items"] == 0
    assert report["delta"]["first_run"] is True
    assert report["issues"] == 0


# --- the run log + `--history` (the custody trend, roadmap H36) ------------


def test_each_maintain_run_appends_to_the_trend_log(home, monkeypatch, capsys):
    """Two passes leave two log lines, oldest first, each carrying that run's
    score and delta — the trajectory, not just the last diff."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(["maintain"]) == 0
    second = json.loads(capsys.readouterr().out)

    runs = read_log(log_path(home))
    assert [r["recorded_at"] for r in runs] == [first["recorded_at"], second["recorded_at"]]
    assert runs[0]["snapshot"]["score"] == 100 and runs[1]["snapshot"]["score"] == 100
    # the first run is first_run, the second is a real delta vs the first
    assert runs[0]["delta"]["first_run"] is True
    assert runs[1]["delta"]["first_run"] is False
    assert runs[1]["delta"]["since"] == first["recorded_at"]
    # the log lives under .maintenance/, never as a compiled library page
    assert not (home.library_dir / ".maintenance").exists()


def test_history_prints_the_recorded_runs_oldest_first(home, monkeypatch, capsys):
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(["maintain"]) == 0
    second = json.loads(capsys.readouterr().out)

    assert main(["maintain", "--history"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert [r["recorded_at"] for r in printed] == [
        first["recorded_at"],
        second["recorded_at"],
    ]


def test_history_bounds_to_the_last_n(home, monkeypatch, capsys):
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    recorded = []
    for _ in range(3):
        assert main(["maintain"]) == 0
        recorded.append(json.loads(capsys.readouterr().out)["recorded_at"])

    assert main(["maintain", "--history", "2"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert [r["recorded_at"] for r in printed] == recorded[-2:]


def test_history_is_read_only_and_never_runs_a_pass(home, monkeypatch, capsys):
    """`--history` reads the log; it must not recheck, recompile, or append."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    capsys.readouterr()
    before = read_log(log_path(home))

    # no live_recapture call should happen; the seam is left as the identity stub
    assert main(["maintain", "--history"]) == 0
    capsys.readouterr()
    after = read_log(log_path(home))
    assert after == before  # history appended nothing — it only read the log


def test_history_on_a_library_never_maintained_is_empty(home, capsys):
    """A built library that has never run a pass → an empty history, exit 0."""
    _build(_held_topic())
    capsys.readouterr()
    assert main(["maintain", "--history"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_history_before_init_is_empty_not_an_error(home, capsys):
    assert main(["maintain", "--history"]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out) == []
    assert out.err == ""


def test_history_is_mutually_exclusive_with_the_pass_flags(home, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["maintain", "--history", "--no-recheck"])
    assert exc.value.code == 2


def test_history_trend_wraps_the_runs_in_a_trend_envelope(home, monkeypatch, capsys):
    """`--history --trend` reads the trajectory direction across the window: a
    drift the second run records makes the posture `regressing` while the bare
    `--history` array stays the default shape. The second pass uses `--all` to
    force the recheck (the default stale-bounded pass would skip the just-seen
    items, H83)."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    capsys.readouterr()
    monkeypatch.setattr(cli, "live_recapture", _recapture_drifting(items[0].id))
    assert main(["maintain", "--all"]) == 0
    capsys.readouterr()

    assert main(["maintain", "--history", "--trend"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"trend", "runs"}
    assert len(payload["runs"]) == 2
    # score held at 100 across both runs, but one source drifted → regressing
    assert payload["trend"]["score"]["change"] == 0
    assert payload["trend"]["drift_change"] == 1
    assert payload["trend"]["posture"] == "regressing"


def test_history_without_trend_stays_a_bare_array(home, monkeypatch, capsys):
    items = _held_topic()
    _build(items)
    capsys.readouterr()
    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    capsys.readouterr()

    assert main(["maintain", "--history"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)  # the completeness-contract bare array


def test_trend_on_a_single_run_window_is_insufficient_history(home, monkeypatch, capsys):
    items = _held_topic()
    _build(items)
    capsys.readouterr()
    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    capsys.readouterr()

    assert main(["maintain", "--history", "--trend"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["trend"]["posture"] == "insufficient-history"
    assert len(payload["runs"]) == 1


def test_trend_requires_history(home, capsys):
    """`--trend` only shapes a `--history` read; alone it is a usage error, not a
    silently-ignored flag that runs a full pass."""
    exit_code = main(["maintain", "--trend"])
    out = capsys.readouterr()
    assert exit_code == 2
    assert out.out == ""
    assert "history" in json.loads(out.err)["error"].lower()
