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
    get_fidelity,
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
    report_at_risk_works,
    report_by_source,
    report_enrichment_by_source,
    report_summary_by_source,
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
                   coverage=None, at_risk=0):
    """A minimal doctor report shaped like `run_doctor`'s custody block.

    `coverage` mirrors the drift block's `{verified, total}` recheck-coverage
    member (roadmap H113); defaults to the honest zero when not specified.
    `at_risk` mirrors the `custody.works.at_risk` consolidation-alarm count
    (roadmap H263/H267); defaults to zero (no work at risk).
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
            "works": {"status": "ok", "total": at_risk, "at_risk": at_risk,
                      "most_at_risk": None},
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
        at_risk=2,
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
        # the consolidation-loss scalar (H267): the at-risk-works count, not the
        # whole `at_risk_works` block — a comparable scalar the delta subtracts
        "at_risk": 2,
    }


def test_custody_snapshot_coverage_defaults_to_zero_on_a_pre_h113_drift_block():
    # A doctor report whose drift block predates the H113 coverage member reads
    # the honest zeroed coverage, never a KeyError — the degrade-safely posture.
    report = _doctor_report(100, {"full": 1}, {"checked": 1, "unchanged": 1})
    del report["custody"]["drift"]["coverage"]
    assert custody_snapshot(report)["coverage"] == {"verified": 0, "total": 0}


def test_custody_snapshot_records_the_at_risk_works_count():
    # H267: the snapshot carries the at-risk-works count (the consolidation-loss
    # scalar) read off `custody.works.at_risk`, so `--history`/`--trend` can show
    # whether consolidation health is degrading without re-auditing each run.
    report = _doctor_report(80, {"full": 2, "partial": 0, "reference": 1}, {},
                            at_risk=1)
    assert custody_snapshot(report)["at_risk"] == 1


def test_custody_snapshot_at_risk_defaults_to_zero_without_a_works_block():
    # A report without a `works` block (an older schema) or one a --source pass left
    # `status: skipped` (a scoped item set fragments works → at_risk 0) reads the
    # honest 0, never a KeyError — the module's degrade-safely posture (ADR 0082).
    report = _doctor_report(100, {"full": 1}, {"checked": 1, "unchanged": 1})
    del report["custody"]["works"]
    assert custody_snapshot(report)["at_risk"] == 0
    # a skipped works block (the --source default) reads its honest 0 too
    skipped = _doctor_report(100, {"full": 1}, {"checked": 1})
    skipped["custody"]["works"] = {
        "status": "skipped", "total": 0, "at_risk": 0, "most_at_risk": None,
    }
    assert custody_snapshot(skipped)["at_risk"] == 0


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


def test_delta_reports_at_risk_change_against_a_baseline():
    """The at-risk-works count is a scalar the delta subtracts (H267), so a worker
    reads whether consolidation health moved since last run."""
    previous = {
        "recorded_at": "2026-06-20T09:00:00+00:00",
        "score": 90, "tiers": {"full": 2}, "drift": {"checked": 0}, "at_risk": 1,
    }
    current = custody_snapshot(_doctor_report(80, {"full": 2}, {}, at_risk=3))
    delta = compute_delta(previous, current)
    # two more works lost their last safe representation since last run
    assert delta["at_risk"] == {"before": 1, "after": 3, "change": 2}


def test_delta_at_risk_on_first_run_is_null():
    # no baseline → the at-risk before/change is null, never a fabricated zero
    current = custody_snapshot(_doctor_report(100, {"full": 2}, {}, at_risk=2))
    delta = compute_delta(None, current)
    assert delta["at_risk"] == {"before": None, "after": 2, "change": None}


def test_delta_tolerates_a_baseline_lacking_at_risk():
    """A pre-H267 baseline (no `at_risk` axis) reads as zero for that axis, never
    null — the run happened, consolidation was simply not yet tracked (ADR 0082)."""
    previous = {"recorded_at": "t", "score": 100, "tiers": {"full": 2},
                "drift": {"checked": 2}}  # no `at_risk` key
    current = custody_snapshot(_doctor_report(100, {"full": 2}, {"checked": 2},
                                              at_risk=1))
    delta = compute_delta(previous, current)
    assert delta["at_risk"] == {"before": 0, "after": 1, "change": 1}


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
    at_risk=0,
):
    return {
        "recorded_at": recorded_at,
        "snapshot": {
            "score": score,
            "drift": {"drifted": drifted, "rotted": rotted},
            "coverage": {"verified": verified, "total": total},
            "enrichment_stale": enrichment_stale,
            "summaries_stale": summaries_stale,
            "at_risk": at_risk,
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
        assert trend["at_risk_change"] is None  # nor a consolidation-loss direction
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


def test_trend_reports_at_risk_works_movement_first_to_last():
    """The consolidation-loss trajectory (H267): the net first→last change in the
    count of works no representation safely holds, so a worker reading `--trend`
    sees whether consolidation health is degrading ("2 → 4 works at risk")."""
    trend = compute_trend([_run("t1", 100, at_risk=2), _run("t3", 90, at_risk=4)])
    # two more works lost their last safe representation across the span
    assert trend["at_risk_change"] == 2


def test_trend_at_risk_movement_is_independent_of_the_posture():
    """A rising at-risk-works count re-views the fidelity/drift the score/drift
    already move on, so folding it into `posture` would double-count: a steady
    score with no drift movement is still `holding` even as works go at risk
    (the H115 coverage rule, on the consolidation axis) — `at_risk_change` is
    reported, never a `posture` trigger."""
    trend = compute_trend([_run("t1", 100, at_risk=0), _run("t2", 100, at_risk=3)])
    assert trend["at_risk_change"] == 3
    assert trend["posture"] == "holding"


def test_trend_at_risk_can_clear_across_the_window():
    """A recapture between runs restores a work's safe copy: a negative
    `at_risk_change` is the honest 'fewer works at risk' direction."""
    trend = compute_trend([_run("t1", 100, at_risk=3), _run("t2", 100, at_risk=1)])
    assert trend["at_risk_change"] == -2
    assert trend["posture"] == "holding"


def test_trend_at_risk_reads_zero_for_a_pre_h267_endpoint():
    """A window endpoint recorded before the snapshot tracked `at_risk` (a pre-H267
    schema) reads 0 for the missing axis, so the movement is still computed, never a
    crash (the missing-axis-zero posture, ADR 0082)."""
    pre = {"recorded_at": "t1", "snapshot": {"score": 100, "drift": {}}, "delta": {}}
    trend = compute_trend([pre, _run("t2", 100, at_risk=2)])
    assert trend["at_risk_change"] == 2


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
    held_sources=(),
    enrichment_by_source=None,
    summary_by_source=None,
):
    """A doctor report shaped like `run_doctor`'s — the full surface
    `suggest_repairs` reads, not just the distilled custody scalars.

    `held_sources` seeds `custody.by_source` (the per-source universe H104 the
    scoped-suggestion strict-subset check reads); `enrichment_by_source` /
    `summary_by_source` seed the offenders maps (`custody.enrichment.by_source`
    H135 / `custody.summaries.by_source` H171). Omitting them models a pre-H104
    report with no per-source breakdown (scoping degrades to whole-library)."""

    def _found(n):
        return [{"status": "found"} for _ in range(n)]

    custody = {
        "enrichment": {"stale": enrichment_stale},
        "summaries": {"stale": summaries_stale},
    }
    if held_sources:
        # `custody.by_source` carries every held source (clean or not, H104) — the
        # universe; the per-source tally's shape is irrelevant to scoping, only its keys.
        custody["by_source"] = {s: {"tiers": {}, "drift": {}} for s in held_sources}
    if enrichment_by_source is not None:
        custody["enrichment"]["by_source"] = enrichment_by_source
    if summary_by_source is not None:
        custody["summaries"]["by_source"] = summary_by_source

    return {
        "issues": duplicates + missing_scrolls + missing_media + orphan_scrolls
        + (0 if fts_in_sync else 1),
        "duplicates": _found(duplicates),
        "missing_scrolls": _found(missing_scrolls),
        "missing_media": _found(missing_media),
        "orphan_scrolls": _found(orphan_scrolls),
        "fts": {"in_sync": True if fts_in_sync else False, "status": "ok"},
        "custody": custody,
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


# --- source-scoped refresh suggestions (roadmap H181) ----------------------
#
# When the stale-enrichment / stale-summary debt is confined to a *strict subset*
# of the library's held sources, `suggest_repairs` names the minimal scoped act per
# offending source (`classify --stale --source <S>` H154 / `kb --stale --source <S>`
# H172) instead of the whole-library sweep. The held-source universe is `doctor`'s
# `custody.by_source` (H104, every held source); the offenders are
# `custody.enrichment.by_source` (H135) / `custody.summaries.by_source` (H171).


def test_suggest_repairs_scopes_a_refresh_confined_to_one_source():
    # web carries the only stale classifications in a 2-source library → the
    # suggestion names the minimal act, not the whole-library sweep that would also
    # re-run the clean arxiv source.
    suggested = suggest_repairs(
        _full_doctor_report(
            enrichment_stale=2,
            held_sources=("arxiv", "web"),
            enrichment_by_source={"web": 2},
        )
    )
    assert suggested == [
        {
            "command": "scrolls classify --stale --source web",
            "addresses": ["enrichment_stale"],
        }
    ]


def test_suggest_repairs_scopes_each_offending_source_in_sorted_order():
    # 3 held sources, 2 stale → one scoped command per offending source, in sorted
    # source order, the clean third source (wikipedia) left untouched.
    suggested = suggest_repairs(
        _full_doctor_report(
            enrichment_stale=3,
            held_sources=("arxiv", "web", "wikipedia"),
            enrichment_by_source={"web": 2, "arxiv": 1},
        )
    )
    assert suggested == [
        {
            "command": "scrolls classify --stale --source arxiv",
            "addresses": ["enrichment_stale"],
        },
        {
            "command": "scrolls classify --stale --source web",
            "addresses": ["enrichment_stale"],
        },
    ]


def test_suggest_repairs_stays_whole_library_when_every_held_source_is_stale():
    # Offenders == the universe → scoping buys nothing (it would just enumerate them
    # all), so the whole-library command is already the minimal act.
    suggested = suggest_repairs(
        _full_doctor_report(
            enrichment_stale=3,
            held_sources=("arxiv", "web"),
            enrichment_by_source={"arxiv": 1, "web": 2},
        )
    )
    assert suggested == [
        {"command": "scrolls classify --stale", "addresses": ["enrichment_stale"]}
    ]


def test_suggest_repairs_stays_whole_library_for_a_single_source_library():
    # One held source → the whole-library command IS that source's command;
    # `--source web` would buy nothing (offenders == held, not a strict subset).
    suggested = suggest_repairs(
        _full_doctor_report(
            enrichment_stale=1,
            held_sources=("web",),
            enrichment_by_source={"web": 1},
        )
    )
    assert suggested == [
        {"command": "scrolls classify --stale", "addresses": ["enrichment_stale"]}
    ]


def test_suggest_repairs_falls_back_to_whole_library_without_a_source_universe():
    # A report whose audit predates the per-source breakdown (no `custody.by_source`)
    # cannot prove the debt is *confined* — without the held-source universe the
    # honest, degrade-safe choice is the whole-library command, never a scoped one
    # over a universe it cannot see.
    suggested = suggest_repairs(
        _full_doctor_report(
            enrichment_stale=2,
            enrichment_by_source={"web": 2},  # offenders known, universe unknown
        )
    )
    assert suggested == [
        {"command": "scrolls classify --stale", "addresses": ["enrichment_stale"]}
    ]


def test_suggest_repairs_scopes_the_summary_axis_per_offending_source():
    # The summary-axis sibling: stale summaries confined to web → `kb --stale
    # --source web`, the minimal summary refresh.
    suggested = suggest_repairs(
        _full_doctor_report(
            summaries_stale=1,
            held_sources=("arxiv", "web"),
            summary_by_source={"web": 1},
        )
    )
    assert suggested == [
        {"command": "scrolls kb --stale --source web", "addresses": ["summaries_stale"]}
    ]


def test_suggest_repairs_scopes_a_multi_source_stale_cluster_under_each_member():
    # The H171/H172 attribution carried through: a stale concept spanning arxiv+web
    # is "stale for" both, so `summary_by_source` names both and each earns its own
    # scoped `kb --stale --source <S>`. Refreshing under either regenerates the whole
    # cluster (H172), so the two commands double-cover it — a known, harmless
    # redundancy. wikipedia (clean) is the strict-subset gap that makes scoping
    # worthwhile; the union of the two commands still refreshes exactly the offenders.
    suggested = suggest_repairs(
        _full_doctor_report(
            summaries_stale=1,  # one cluster, attributed to both members (sum > stale)
            held_sources=("arxiv", "web", "wikipedia"),
            summary_by_source={"arxiv": 1, "web": 1},
        )
    )
    assert suggested == [
        {
            "command": "scrolls kb --stale --source arxiv",
            "addresses": ["summaries_stale"],
        },
        {
            "command": "scrolls kb --stale --source web",
            "addresses": ["summaries_stale"],
        },
    ]


def test_suggest_repairs_scopes_the_two_axes_independently():
    # enrichment confined to web, summaries confined to arxiv → each axis scopes to
    # its own offender, the classify suggestion still ordered before the kb one.
    suggested = suggest_repairs(
        _full_doctor_report(
            enrichment_stale=1,
            summaries_stale=1,
            held_sources=("arxiv", "web"),
            enrichment_by_source={"web": 1},
            summary_by_source={"arxiv": 1},
        )
    )
    assert suggested == [
        {
            "command": "scrolls classify --stale --source web",
            "addresses": ["enrichment_stale"],
        },
        {
            "command": "scrolls kb --stale --source arxiv",
            "addresses": ["summaries_stale"],
        },
    ]


def test_suggest_repairs_scoping_leaves_the_structural_groups_unchanged():
    # Scoping touches only the two refresh axes — the grouped `doctor --fix` and the
    # `media` suggestions keep their whole-library shape beside the scoped refresh.
    suggested = suggest_repairs(
        _full_doctor_report(
            duplicates=1,
            missing_media=1,
            enrichment_stale=1,
            held_sources=("arxiv", "web"),
            enrichment_by_source={"web": 1},
        )
    )
    assert suggested == [
        {"command": "scrolls doctor --fix", "addresses": ["duplicates"]},
        {"command": "scrolls media", "addresses": ["missing_media"]},
        {
            "command": "scrolls classify --stale --source web",
            "addresses": ["enrichment_stale"],
        },
    ]


# --- a scoped pass suggests the scoped refresh (roadmap H182) ---------------
#
# A `maintain --source <S>` pass pre-filters the audit (`run_doctor(source=S)`), so
# the held-source universe (`custody.by_source`) collapses to `{S}` and the offenders
# are `{S}` too — making offenders == universe, so H181's strict-subset rule emits the
# *whole-library* sweep even though the operator scoped the pass to S. Threading the
# pass's `--source` scope into `suggest_repairs(report, source=S)` honors that scope:
# the refresh suggestion always carries `--source S` when the finding is present.


def test_suggest_repairs_scopes_to_the_pass_source_on_the_collapsed_universe():
    # The H182 case: a scoped audit's universe is the singleton {web} and the
    # offenders are {web} too (offenders == held, NOT a strict subset), so H181 alone
    # would emit the whole-library `classify --stale`. The pass's `source=web` makes
    # the suggestion the scoped `--source web` the operator declared.
    suggested = suggest_repairs(
        _full_doctor_report(
            enrichment_stale=2,
            held_sources=("web",),
            enrichment_by_source={"web": 2},
        ),
        source="web",
    )
    assert suggested == [
        {
            "command": "scrolls classify --stale --source web",
            "addresses": ["enrichment_stale"],
        }
    ]


def test_suggest_repairs_scopes_the_summary_axis_to_the_pass_source():
    # The summary-axis sibling: `maintain --source web` with stale summaries → the
    # scoped `kb --stale --source web`, not the whole-library sweep.
    suggested = suggest_repairs(
        _full_doctor_report(
            summaries_stale=1,
            held_sources=("web",),
            summary_by_source={"web": 1},
        ),
        source="web",
    )
    assert suggested == [
        {"command": "scrolls kb --stale --source web", "addresses": ["summaries_stale"]}
    ]


def test_suggest_repairs_scopes_to_source_even_without_a_known_universe():
    # A scoped pass honors its declared scope even when the report carries no
    # `by_source` universe (a degraded/pre-H104 audit): the operator scoped to web,
    # so the refresh is `--source web`, never the whole-library command H181 would
    # fall back to when the universe is unknown.
    suggested = suggest_repairs(
        _full_doctor_report(enrichment_stale=1), source="web"
    )
    assert suggested == [
        {
            "command": "scrolls classify --stale --source web",
            "addresses": ["enrichment_stale"],
        }
    ]


def test_suggest_repairs_with_a_source_but_no_debt_suggests_nothing():
    # G1 honest absence under a scope: a scoped pass over a source with no stale
    # debt yields no refresh suggestion — `source` never fabricates a command for a
    # finding that is absent.
    assert suggest_repairs(_full_doctor_report(), source="web") == []


def test_suggest_repairs_scoped_pass_leaves_structural_groups_whole_library():
    # H182 touches only the two refresh axes, exactly like H181: a scoped pass still
    # names the whole-library `doctor --fix` / `media` (those commands take no
    # `--source`), with only the refresh scoped to the pass source.
    suggested = suggest_repairs(
        _full_doctor_report(
            duplicates=1,
            missing_media=1,
            enrichment_stale=1,
            held_sources=("web",),
            enrichment_by_source={"web": 1},
        ),
        source="web",
    )
    assert suggested == [
        {"command": "scrolls doctor --fix", "addresses": ["duplicates"]},
        {"command": "scrolls media", "addresses": ["missing_media"]},
        {
            "command": "scrolls classify --stale --source web",
            "addresses": ["enrichment_stale"],
        },
    ]


def test_suggest_repairs_without_a_source_keeps_the_h181_strict_subset_rule():
    # The default `source=None` is the whole-library pass: the strict-subset rule
    # still governs, so a confined debt scopes per offender and an all-stale universe
    # stays whole-library — H182 changes nothing when no scope is declared.
    confined = suggest_repairs(
        _full_doctor_report(
            enrichment_stale=2,
            held_sources=("arxiv", "web"),
            enrichment_by_source={"web": 2},
        )
    )
    assert confined == [
        {
            "command": "scrolls classify --stale --source web",
            "addresses": ["enrichment_stale"],
        }
    ]
    all_stale = suggest_repairs(
        _full_doctor_report(
            enrichment_stale=3,
            held_sources=("arxiv", "web"),
            enrichment_by_source={"arxiv": 1, "web": 2},
        )
    )
    assert all_stale == [
        {"command": "scrolls classify --stale", "addresses": ["enrichment_stale"]}
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
    doctor custody block. The single stale item is `web`, and `arxiv` is clean, so
    the suggestion is **source-scoped** to web (roadmap H181) — the minimal act."""
    items = _held_topic()  # 1 arxiv + 2 web
    _build(items)
    persisted = get_item(home.db_path, items[1].id)  # web
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
    assert report["enrichment_by_source"] == {"web": 1}  # arxiv clean → strict subset
    assert report["suggested"] == [
        {
            "command": "scrolls classify --stale --source web",
            "addresses": ["enrichment_stale"],
        }
    ]


def test_maintain_suggests_whole_library_classify_stale_when_all_sources_stale(
    home, monkeypatch, capsys
):
    """When *every* held source carries stale classifications, scoping buys nothing
    (it would just enumerate every source), so the suggestion stays the whole-library
    `classify --stale` — the H181 strict-subset rule, through the real audit."""
    items = _held_topic()  # 1 arxiv + 2 web
    _build(items)
    for item in items:  # arxiv + both web → every source stale
        _mark_stale_classified(item.id)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["enrichment_by_source"] == {"arxiv": 1, "web": 2}
    assert report["suggested"] == [
        {"command": "scrolls classify --stale", "addresses": ["enrichment_stale"]}
    ]


def test_maintain_source_pass_suggests_the_scoped_refresh(
    home, monkeypatch, capsys
):
    """The gap H181 surfaced (roadmap H182): a `maintain --source web` pass pre-filters
    the audit, so its held-source universe collapses to `{web}` and the offenders are
    `{web}` too — defeating H181's strict-subset rule, which would emit the whole-library
    `classify --stale`. The pass's `--source web` scope is threaded through, so the
    suggestion is the scoped `classify --stale --source web` the operator declared."""
    items = _held_topic()  # 1 arxiv + 2 web
    _build(items)
    _mark_stale_classified(items[1].id)  # web
    _mark_stale_classified(items[2].id)  # web
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain", "--source", "web"]) == 0
    report = json.loads(capsys.readouterr().out)
    # the scoped audit sees only web — offenders == held == {web} (the collapse)
    assert report["source"] == "web"
    assert report["enrichment_by_source"] == {"web": 2}
    assert report["suggested"] == [
        {
            "command": "scrolls classify --stale --source web",
            "addresses": ["enrichment_stale"],
        }
    ]


def test_maintain_source_pass_with_no_debt_suggests_nothing(
    home, monkeypatch, capsys
):
    """A scoped pass over a source with no stale debt names no refresh — `--source`
    never fabricates a scoped command for an absent finding (the G1 honest-absence
    posture under a scope)."""
    _build(_held_topic())  # nothing marked stale → clean
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain", "--source", "web"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["source"] == "web"
    assert report["enrichment_by_source"] == {}
    assert report["suggested"] == []


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


# --- per-source enrichment staleness in the report (roadmap H147) ----------


def _enrichment_by_source_report(by_source):
    """A doctor report carrying just the per-source stale-classification map."""
    return {"custody": {"enrichment": {"by_source": by_source}}}


def test_report_enrichment_by_source_threads_the_doctor_audits_map():
    # The pure layer is a faithful read of the offenders-only `{source: stale_count}`
    # map the audit produces (`doctor`'s `custody.enrichment.by_source`, H135).
    by_source = {"arxiv": 1, "web": 2}
    assert report_enrichment_by_source(_enrichment_by_source_report(by_source)) == by_source


def test_report_enrichment_by_source_without_a_map_is_the_empty_map():
    # Forward-compat / empty library / clean library: an absent block reads as the
    # honest empty map, never a KeyError (the degrade-safely posture, this axis).
    assert report_enrichment_by_source({"custody": {"enrichment": {}}}) == {}
    assert report_enrichment_by_source({"custody": {}}) == {}
    assert report_enrichment_by_source({}) == {}


def _mark_stale_classified(item_id):
    """Stamp a persisted item rules-classified under a *superseded* ruleset, so the
    live ruleset reads it stale (the H40 stale-classification fixture)."""
    persisted = get_item(get_paths().db_path, item_id)
    update_item(
        get_paths().db_path,
        replace(
            persisted,
            provenance={
                **persisted.provenance,
                "classified_by": "rules-v1",
                "classified_basis": "title-pattern",
                "classified_ruleset": "deadbeef0000",  # superseded by the live ruleset
            },
        ),
    )


def test_maintain_report_carries_the_per_source_enrichment_staleness(
    home, monkeypatch, capsys
):
    """The report names each source's stale-classification debt — the per-source
    map the audit (`doctor`'s `custody.enrichment.by_source`, H135) already
    produces, surfaced so an unattended log shows *which* source's `classify
    --stale` to run without re-running doctor."""
    items = _held_topic()  # 1 arxiv + 2 web
    _build(items)
    _mark_stale_classified(items[0].id)  # arxiv
    _mark_stale_classified(items[1].id)  # web
    _mark_stale_classified(items[2].id)  # web
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0  # stale enrichment is reported, never a failure
    report = json.loads(capsys.readouterr().out)

    # offenders-only, sorted source keys; arxiv:1, web:2
    enrichment_by_source = report["enrichment_by_source"]
    assert enrichment_by_source == {"arxiv": 1, "web": 2}
    # it is exactly the map this pass's doctor audit produces (no new read)
    assert (
        enrichment_by_source
        == run_doctor(home)["custody"]["enrichment"]["by_source"]
    )


def test_maintain_enrichment_by_source_sums_to_the_whole_library_enrichment_stale(
    home, monkeypatch, capsys
):
    """The H104/H135 sum-to-whole posture on the enrichment axis: every stale item
    has exactly one source, so the per-source counts total the report's whole-library
    `custody.enrichment_stale` — the member can never disagree with the scalar."""
    items = _held_topic()
    _build(items)
    _mark_stale_classified(items[0].id)  # arxiv
    _mark_stale_classified(items[1].id)  # web
    capsys.readouterr()
    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    report = json.loads(capsys.readouterr().out)

    assert (
        sum(report["enrichment_by_source"].values())
        == report["custody"]["enrichment_stale"]
        == 2
    )


def test_maintain_per_source_enrichment_on_a_clean_library_is_empty(
    home, monkeypatch, capsys
):
    """No stale classifications → the honest empty map (offenders-only — a source
    with no stale debt is omitted, never a 0 entry)."""
    _build(_held_topic())  # categories present but no rules stamp → not stale
    capsys.readouterr()
    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["enrichment_by_source"] == {}
    assert report["custody"]["enrichment_stale"] == 0


def test_maintain_per_source_enrichment_on_an_uninitialized_library_is_empty(
    home, capsys
):
    """No library yet → the honest empty map, the first-run honesty the report keeps."""
    assert main(["maintain", "--no-recheck"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["enrichment_by_source"] == {}


def test_maintain_history_does_not_carry_the_per_source_enrichment_breakdown(
    home, monkeypatch, capsys
):
    """`enrichment_by_source` rides the live pass, not the recorded snapshot: it is
    derived fresh from this pass's audit (like `by_source` H123, `suggested` H40, and
    `scope`/`since` H83), so `--history` (which replays snapshots) carries none and
    the log stays bare."""
    items = _held_topic()
    _build(items)
    _mark_stale_classified(items[1].id)
    capsys.readouterr()
    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    capsys.readouterr()

    assert main(["maintain", "--history"]) == 0
    runs = json.loads(capsys.readouterr().out)
    assert runs and all("enrichment_by_source" not in run for run in runs)
    assert all("enrichment_by_source" not in run["snapshot"] for run in runs)
    # and not stored in the log either (the snapshot/log carry only the scalars)
    assert all("enrichment_by_source" not in run for run in read_log(log_path(home)))


# --- per-source stale-summary debt: `summary_by_source` (roadmap H175) -------
#
# The summary-axis sibling of `enrichment_by_source` (H147). H171 added doctor's
# `custody.summaries.by_source` — a flat `{source: stale_count}` of the offending
# sources only — and this surfaces it on the `maintain` report so the scheduled
# worker names *which* source's `kb --stale` to run without a second doctor pass.
# The load-bearing asymmetry (H171): a concept summary spans a *cluster* whose
# members can come from several sources, so a stale summary is attributed to every
# such source and the map need NOT sum to the whole `summaries_stale` (unlike the
# drift/enrichment maps). The `maintain`↔`doctor` tie is therefore faithful-read
# equality, never a sum-to-whole check.


def _summary_by_source_report(by_source):
    """A doctor report carrying just the per-source stale-summary map."""
    return {"custody": {"summaries": {"by_source": by_source}}}


def test_report_summary_by_source_threads_the_doctor_audits_map():
    # The pure layer is a faithful read of the offenders-only `{source: stale_count}`
    # map the audit produces (`doctor`'s `custody.summaries.by_source`, H171). A
    # multi-source stale concept counts toward each source, so the values can sum to
    # more than the whole `summaries_stale` — the read preserves that as-is.
    by_source = {"arxiv": 1, "web": 2}
    assert report_summary_by_source(_summary_by_source_report(by_source)) == by_source


def test_report_summary_by_source_without_a_map_is_the_empty_map():
    # Forward-compat / empty library / clean library: an absent block reads as the
    # honest empty map, never a KeyError (the degrade-safely posture, this axis).
    assert report_summary_by_source({"custody": {"summaries": {}}}) == {}
    assert report_summary_by_source({"custody": {}}) == {}
    assert report_summary_by_source({}) == {}


def _concept_member(source, slug, concept) -> ScrollItem:
    """A minimal rendered cluster member carrying one concept (stale-summary fixture)."""
    return _rendered(
        source, None, f"https://{source}.example.com/{slug}",
        title=slug, extracted_text="A note about the concept.",
        concepts=(concept,),
    )


def _store_stale_summary(slug, display) -> None:
    """Store a concept summary whose fingerprint no longer matches its live cluster,
    so the live ruleset reads it stale (the summary-axis counterpart of
    `_mark_stale_classified`)."""
    from scrolls.kb import ConceptSummary, save_concept_summary

    save_concept_summary(get_paths().db_path, ConceptSummary(
        slug=slug, display=display, summary="How it shows up.",
        members_hash="stale-old-digest", engine="kb-llm-v1",
        model="claude-opus-4-8", generated_at="2026-06-16T00:00:00+00:00"))


def _seed_stale_summaries() -> None:
    """A library with two stale concept summaries: Bm25 over a web+arxiv cluster
    (attributes to BOTH), Vector over a web-only cluster (attributes to web). So
    the per-source debt is {arxiv: 1, web: 2} while only 2 summaries are stale."""
    _build([
        _concept_member("web", "bm25-web", "Bm25"),
        _concept_member("arxiv", "bm25-arxiv", "Bm25"),
        _concept_member("web", "vector-1", "Vector"),
        _concept_member("web", "vector-2", "Vector"),
    ])
    _store_stale_summary("bm25", "Bm25")
    _store_stale_summary("vector", "Vector")


def test_maintain_report_carries_the_per_source_summary_staleness(home, capsys):
    """The report names each source's stale-summary debt — the per-source map the
    audit (`doctor`'s `custody.summaries.by_source`, H171) already produces, surfaced
    so an unattended log shows *which* source's `kb --stale` to run without re-running
    doctor."""
    _seed_stale_summaries()
    capsys.readouterr()

    assert main(["maintain", "--no-recheck"]) == 0  # stale summaries report, never fail
    report = json.loads(capsys.readouterr().out)

    # offenders-only, sorted source keys; web in both stale concepts, arxiv in one
    summary_by_source = report["summary_by_source"]
    assert summary_by_source == {"arxiv": 1, "web": 2}
    # it is exactly the map this pass's doctor audit produces (no new read)
    assert (
        summary_by_source
        == run_doctor(home)["custody"]["summaries"]["by_source"]
    )


def test_maintain_summary_by_source_need_not_sum_to_the_whole(home, capsys):
    """The H171 asymmetry, carried faithfully onto the report: the Bm25 summary is
    double-attributed (web + arxiv), so the per-source values sum to MORE than the
    whole-library `summaries_stale` — unlike `enrichment_by_source`, the member can
    and does exceed the scalar, and the maintain↔doctor tie is faithful-read
    equality, not a sum-to-whole check."""
    _seed_stale_summaries()
    capsys.readouterr()
    assert main(["maintain", "--no-recheck"]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["custody"]["summaries_stale"] == 2
    assert sum(report["summary_by_source"].values()) == 3 > 2


def test_maintain_per_source_summary_on_a_clean_library_is_empty(home, capsys):
    """A current summary → no stale debt, so the honest empty map (offenders-only —
    a source with no stale summaries is omitted, never a 0 entry)."""
    from scrolls.kb import ConceptSummary, save_concept_summary
    from scrolls.kb_llm import eligible_concepts, members_hash

    _build([
        _concept_member("web", "bm25-web", "Bm25"),
        _concept_member("arxiv", "bm25-arxiv", "Bm25"),
    ])
    # store a *current* summary (its fingerprint matches the live cluster digest)
    eligible = eligible_concepts(list_items(get_paths().db_path))
    save_concept_summary(get_paths().db_path, ConceptSummary(
        slug="bm25", display="Bm25", summary="How it shows up.",
        members_hash=members_hash(eligible["bm25"]["items"]), engine="kb-llm-v1",
        model="claude-opus-4-8", generated_at="2026-06-16T00:00:00+00:00"))
    capsys.readouterr()

    assert main(["maintain", "--no-recheck"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary_by_source"] == {}
    assert report["custody"]["summaries_stale"] == 0


def test_maintain_per_source_summary_on_an_uninitialized_library_is_empty(home, capsys):
    """No library yet → the honest empty map, the first-run honesty the report keeps."""
    assert main(["maintain", "--no-recheck"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary_by_source"] == {}


def test_maintain_history_does_not_carry_the_per_source_summary_breakdown(home, capsys):
    """`summary_by_source` rides the live pass, not the recorded snapshot: it is
    derived fresh from this pass's audit (like `enrichment_by_source` H147, `by_source`
    H123), so `--history` (which replays snapshots) carries none and the log stays
    bare."""
    _seed_stale_summaries()
    capsys.readouterr()
    assert main(["maintain", "--no-recheck"]) == 0
    capsys.readouterr()

    assert main(["maintain", "--history"]) == 0
    runs = json.loads(capsys.readouterr().out)
    assert runs and all("summary_by_source" not in run for run in runs)
    assert all("summary_by_source" not in run["snapshot"] for run in runs)
    # and not stored in the log either (the snapshot/log carry only the scalars)
    assert all("summary_by_source" not in run for run in read_log(log_path(home)))


# --- the single weakest source: `attention` (roadmap H119) ------------------


def _source_tally(*, full=0, partial=0, reference=0,
                  verified=0, unverified=0, drifted=0, rotted=0, error=0,
                  cov_verified=0, cov_total=0):
    """One source's `{tiers, drift, coverage}` tally, shaped like
    `custody_counts_by_source` (which carries the per-source `coverage` since H121)."""
    return {
        "tiers": {"full": full, "partial": partial, "reference": reference},
        "drift": {"verified": verified, "unverified": unverified,
                  "drifted": drifted, "rotted": rotted, "error": error},
        "coverage": {"verified": cov_verified, "total": cov_total},
    }


def test_weakest_source_picks_the_most_drifted_and_rotted():
    # The flagged source is the one with the most actionable loss (drifted +
    # rotted), and it carries its own tally plus a one-line reason naming the loss.
    by_source = {
        "arxiv": _source_tally(full=2, verified=1, drifted=1, cov_verified=1, cov_total=2),
        "web": _source_tally(full=3, drifted=2, rotted=1, cov_verified=1, cov_total=3),
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


def test_weakest_source_carries_the_flagged_sources_coverage():
    # roadmap H153: the flag carries the flagged source's own recheck `coverage`
    # (`{verified, total}`, H121) — so an unattended worker reads not just *which*
    # source is weakest (H119) and *how* to recheck it (H137), but *how much of it
    # is even checked*: whether the drift is the whole story or just the verified
    # slice of a barely-covered source. It is exactly that source's `by_source`
    # coverage (a pure read of the tally, no new ledger read).
    by_source = {
        "arxiv": _source_tally(full=2, verified=1, drifted=1, cov_verified=1, cov_total=2),
        "web": _source_tally(full=3, drifted=2, rotted=1, cov_verified=1, cov_total=3),
    }
    flagged = weakest_source(by_source)
    assert flagged["source"] == "web"  # the weakest source (loss 3)
    assert flagged["coverage"] == by_source["web"]["coverage"] == {"verified": 1, "total": 3}
    # present whenever `attention` is — the flagged source's coverage rides along,
    # not the loser's (a literal pick: arxiv's coverage is a different fraction).
    assert flagged["coverage"] != by_source["arxiv"]["coverage"]


def test_weakest_source_coverage_degrades_to_zero_fraction_without_a_tally():
    # Honest absence (the module's degrade-safe posture): a tally missing the
    # `coverage` key (an older/empty schema) reads the honest `{0, 0}` fraction,
    # never a `KeyError` — mirroring `custody_snapshot`'s coverage default.
    legacy = {
        "arxiv": {"tiers": {"full": 1, "partial": 0, "reference": 0},
                  "drift": {"verified": 1, "unverified": 0, "drifted": 0,
                            "rotted": 0, "error": 0}},
        "web": {"tiers": {"full": 1, "partial": 0, "reference": 0},
                "drift": {"verified": 0, "unverified": 0, "drifted": 1,
                          "rotted": 0, "error": 0}},
    }
    flagged = weakest_source(legacy)
    assert flagged["source"] == "web"
    assert flagged["coverage"] == {"verified": 0, "total": 0}


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
    # H153: the flag carries the flagged source's own recheck coverage — exactly
    # the `by_source` coverage the report shows beside it (a pure read, no new
    # ledger read), so the worker sees how much of the weak source is checked.
    assert attention["coverage"] == report["by_source"]["web"]["coverage"]
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


# --- the at-risk-works consolidation alarm (roadmap H263) -----------------
# `maintain` surfaces `doctor`'s `custody.works` block as `at_risk_works` — the
# work-level counterpart of the weakest-source `attention` flag, live-pass only.


def _rep(item_id, doi, tier, **fields):
    """A representation of work `doi` at the given fidelity tier (links to doi.org)."""
    base = dict(
        id=item_id, source=item_id.split(":")[0],
        source_id=item_id.split(":", 1)[1] if ":" in item_id else None,
        url=f"https://example.org/{item_id}", saved_at="2026-06-14T00:00:00+00:00",
        links=(f"https://doi.org/{doi}",), stage="rendered",
    )
    if tier == "full":
        base.update(extracted_text="body", content_hash=f"sha256:{item_id}")
    elif tier == "partial":
        base.update(summary="a summary")
    base.update(fields)
    return ScrollItem(**base)


def _build_works_mix(home):
    """Seed three 2-rep works into a real library: X at risk (full+drifted, ref), Y
    safely held (full+verified, partial), Z most at risk (all reference)."""
    home.root.mkdir(parents=True, exist_ok=True)
    init_db(home.db_path)
    for item in [
        _rep("arxiv:x", "10.1000/x", "full"),
        _rep("crossref:cx", "10.1000/x", "reference"),
        _rep("biorxiv:y", "10.2000/y", "full"),
        _rep("pubmed:y", "10.2000/y", "partial"),
        _rep("arxiv:z", "10.3000/z", "reference"),
        _rep("crossref:cz", "10.3000/z", "reference"),
    ]:
        insert_item(home.db_path, item)
    record_events(home.db_path, [
        CustodyEvent("arxiv:x", "2026-06-14T00:00:00+00:00", "drifted", "h:a", "h:b"),
        CustodyEvent("biorxiv:y", "2026-06-14T00:00:00+00:00", "unchanged", "h:c", "h:c"),
    ])


def test_maintain_reports_the_at_risk_works(home, capsys):
    """A live pass surfaces the works no representation safely holds — the
    consolidation alarm, with the single most-at-risk work named."""
    _build_works_mix(home)
    capsys.readouterr()
    assert main(["maintain", "--no-recheck"]) == 0
    report = json.loads(capsys.readouterr().out)

    works = report["at_risk_works"]
    assert works["status"] == "ok"
    assert works["total"] == 3
    assert works["at_risk"] == 2  # X (full+drifted) and Z (all reference); Y is safe
    # Z (all-reference, nothing re-derivable held) is the lowest custody ceiling
    assert works["most_at_risk"]["doi"] == "10.3000/z"
    assert works["most_at_risk"]["custody"]["safely_held"] is False
    # it is exactly `doctor`'s `custody.works` block — a faithful read, no recompute
    assert works == report_at_risk_works(run_doctor(home))


def test_maintain_at_risk_works_empty_when_every_work_safely_held(home, capsys):
    """No work at risk → the computed block names none, the honest empty alarm."""
    home.root.mkdir(parents=True, exist_ok=True)
    init_db(home.db_path)
    for item in [
        _rep("arxiv:a", "10.1000/a", "full"),  # full+unverified → safely held
        _rep("crossref:ca", "10.1000/a", "reference"),
    ]:
        insert_item(home.db_path, item)
    capsys.readouterr()
    assert main(["maintain", "--no-recheck"]) == 0
    works = json.loads(capsys.readouterr().out)["at_risk_works"]
    assert works == {"status": "ok", "total": 1, "at_risk": 0, "most_at_risk": None}


def test_maintain_at_risk_works_skipped_under_a_source_scope(home, capsys):
    """A work spans sources, so a --source pass cannot see whole works: the alarm is
    whole-library only and reports the honest skipped default under a scope."""
    _build_works_mix(home)
    capsys.readouterr()
    assert main(["maintain", "--source", "arxiv", "--no-recheck"]) == 0
    scoped = json.loads(capsys.readouterr().out)["at_risk_works"]
    assert scoped == {
        "status": "skipped", "total": 0, "at_risk": 0, "most_at_risk": None,
    }

    # but a --fidelity pass leaves the audit whole-library (H255), so it is computed
    capsys.readouterr()
    assert main(["maintain", "--fidelity", "full", "--no-recheck"]) == 0
    scoped_fid = json.loads(capsys.readouterr().out)["at_risk_works"]
    assert scoped_fid["status"] == "ok"
    assert scoped_fid["at_risk"] == 2


def test_maintain_history_does_not_carry_at_risk_works(home, capsys):
    """`at_risk_works` rides the live pass only (like `attention`/`by_source`): it is
    derived fresh from the audit, never recorded, so `--history` and the log are bare."""
    _build_works_mix(home)
    capsys.readouterr()
    assert main(["maintain", "--no-recheck"]) == 0
    capsys.readouterr()

    assert main(["maintain", "--history"]) == 0
    runs = json.loads(capsys.readouterr().out)
    assert runs and all("at_risk_works" not in run for run in runs)
    assert all("at_risk_works" not in run["snapshot"] for run in runs)
    assert all("at_risk_works" not in run for run in read_log(log_path(home)))


def test_maintain_records_the_at_risk_works_count_in_the_snapshot(home, capsys):
    """H267: the live pass surfaces the whole `at_risk_works` block, but the recorded
    snapshot keeps the scalar `at_risk` count — and the two converge by construction
    (the snapshot's scalar IS the live block's `at_risk`), so a recorded run carries
    the consolidation-loss figure `--history`/`--trend` read back."""
    _build_works_mix(home)  # X (full+drifted) and Z (all reference) at risk; Y safe
    capsys.readouterr()
    assert main(["maintain", "--no-recheck"]) == 0
    report = json.loads(capsys.readouterr().out)

    # the live block names two at-risk works (the H263 alarm) …
    assert report["at_risk_works"]["at_risk"] == 2
    # … and the recorded snapshot keeps exactly that count as its scalar `at_risk`
    snap = load_snapshot(snapshot_path(home))
    assert snap["at_risk"] == 2
    assert snap["at_risk"] == report["at_risk_works"]["at_risk"]
    # the live report's own custody snapshot carries it too (the shared primitive)
    assert report["custody"]["at_risk"] == 2
    # first run → the delta's at-risk axis is the honest null (no baseline)
    assert report["delta"]["at_risk"] == {"before": None, "after": 2, "change": None}


def test_maintain_history_carries_the_at_risk_scalar_in_each_snapshot(home, capsys):
    """The recorded `at_risk` scalar rides `--history` (unlike the live-pass-only
    `at_risk_works` block): each run's snapshot carries the count, and the delta its
    cross-run change, so a worker reads the consolidation-loss trend from the log."""
    _build_works_mix(home)
    capsys.readouterr()
    assert main(["maintain", "--no-recheck"]) == 0  # first run
    capsys.readouterr()
    assert main(["maintain", "--no-recheck"]) == 0  # second run, same fixture
    capsys.readouterr()

    assert main(["maintain", "--history"]) == 0
    runs = json.loads(capsys.readouterr().out)
    assert [run["snapshot"]["at_risk"] for run in runs] == [2, 2]
    # the second run's delta differences the scalar against the first (steady → 0)
    assert runs[1]["delta"]["at_risk"] == {"before": 2, "after": 2, "change": 0}


# --- `scrolls maintain --source <S>` — the scoped pass (roadmap H165) ----------
#
# The scheduled-maintenance counterpart of `doctor --source` (H162) and the act-
# side `verify --source` (H125): a `--source` filter narrows the recheck, audit,
# by_source, and headline to one source's held items, reusing the same shipped
# `run_doctor(source=)` pre-filter so the scoped picture converges with
# `doctor --source`/`status --source` by construction. View regeneration stays
# whole-library, and a scoped pass is non-persisting (it records per-item drift
# events but never the whole-library trend baseline — its delta is null).


def test_source_scopes_the_recheck_to_that_source(home, monkeypatch, capsys):
    """`maintain --source web --all` re-captures only web's held items, never the
    arxiv one — the same item-intrinsic filter `verify --source` applies."""
    items = _held_topic()  # 1 arxiv + 2 web, all full-fidelity with hashes
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain", "--all", "--source", "web"]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["source"] == "web"
    # only the two web items were rechecked, the arxiv one untouched
    assert report["recheck"]["checked"] == 2
    assert report["recheck"]["unchanged"] == 2
    # the audit narrows to web: two web scrolls, no arxiv tier
    assert report["custody"]["tiers"] == {"full": 2, "partial": 0, "reference": 0}
    assert set(report["by_source"]) == {"web"}


def test_source_audit_is_the_one_source_view_converging_with_doctor_source(
    home, monkeypatch, capsys
):
    """A scoped pass's `custody`/`by_source`/`headline` equal a `doctor --source S`
    audit distilled AND the whole-library audit's `by_source[S]` slice — the
    convergence the shared `run_doctor(source=)` pre-filter guarantees (H169)."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    # --no-recheck keeps the ledger pristine, so the maintain audit and a fresh
    # doctor read the identical post-maintenance state (the H127 pattern).
    assert main(["maintain", "--no-recheck", "--source", "web"]) == 0
    report = json.loads(capsys.readouterr().out)

    whole_by_source = run_doctor(home)["custody"]["by_source"]
    scoped_doctor = run_doctor(home, source="web")
    # 1. the scoped custody view == the scoped doctor audit distilled
    assert report["custody"] == custody_snapshot(scoped_doctor)
    # 2. == the whole-library by_source[web] slice (same held subset, same tally)
    assert report["custody"]["tiers"] == whole_by_source["web"]["tiers"]
    assert report["custody"]["coverage"] == whole_by_source["web"]["coverage"]
    # 3. by_source collapses to the present-and-singleton {web: that slice}
    assert report["by_source"] == {"web": whole_by_source["web"]}
    # 4. the headline is the scoped block rendered (parity with status --source)
    assert report["headline"] == snapshot_headline(report["custody"])
    # 5. attention is null under a single-source scope (nothing to flag across)
    assert report["attention"] is None
    # the offline pass reports web's coverage (agrees with the scoped audit)
    assert report["recheck"]["coverage"] == report["custody"]["coverage"]


def test_source_pass_is_non_persisting_and_leaves_the_trend_baseline(
    home, monkeypatch, capsys
):
    """A scoped pass records no snapshot/log: the single whole-library baseline is
    never clobbered with a one-source slice (no per-source storage shape), and the
    scoped `delta` is honestly null — the whole-library pass owns the trend."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()
    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)

    # one whole-library pass records the single baseline + first log entry
    assert main(["maintain"]) == 0
    capsys.readouterr()
    baseline = load_snapshot(snapshot_path(home))
    assert baseline is not None
    assert len(read_log(log_path(home))) == 1

    # a scoped pass: delta null, and the baseline/log are untouched afterwards
    assert main(["maintain", "--source", "web"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["delta"] is None
    assert load_snapshot(snapshot_path(home)) == baseline  # not clobbered
    assert len(read_log(log_path(home))) == 1  # no scoped run appended

    # --history therefore still shows only the one whole-library run
    assert main(["maintain", "--history"]) == 0
    runs = json.loads(capsys.readouterr().out)
    assert len(runs) == 1


def test_source_records_drift_events_the_next_whole_pass_folds_in(
    home, monkeypatch, capsys
):
    """The scoped recheck is real work: it appends per-item custody events (the
    next whole-library pass folds them into the trend), even though the scoped
    pass writes no snapshot. Custody-safe: events accrue, the baseline doesn't."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    drifted = items[1]  # a web item
    monkeypatch.setattr(cli, "live_recapture", _recapture_drifting(drifted.id))
    assert main(["maintain", "--all", "--source", "web"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["recheck"]["drifted"] == 1

    # the per-item ledger recorded the drift event (a real, persisted change)
    events = latest_events(home.db_path)
    assert events[drifted.id].status == "drifted"
    # but no maintenance snapshot was written (the scoped pass is non-persisting)
    assert load_snapshot(snapshot_path(home)) is None


def test_source_unknown_is_an_honest_empty_pass(home, capsys):
    """An unknown source holds nothing → the honest empty pass (empty headline,
    null attention/delta, exit 0), never an error — sources are open-ended."""
    _build(_held_topic())
    capsys.readouterr()

    assert main(["maintain", "--no-recheck", "--source", "ghost"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["source"] == "ghost"
    assert report["headline"] == "_Custody: 0 scroll(s)._"
    assert report["by_source"] == {}
    assert report["attention"] is None
    assert report["delta"] is None
    assert report["recheck"]["coverage"] == {"verified": 0, "total": 0}


def test_source_composes_with_limit(home, monkeypatch, capsys):
    """`--source web --all --limit 1` bounds the scoped recheck — one of web's two
    held items this pass (composes scope ∧ bound)."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain", "--all", "--limit", "1", "--source", "web"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["recheck"]["checked"] == 1


def test_source_conflicts_with_history(home, capsys):
    """`--source` scopes a pass; `--history` is a read of recorded passes — a
    usage error (exit 2), not a silently-ignored flag (the `--all`/history rule)."""
    assert main(["maintain", "--source", "web", "--history"]) == 2
    error = json.loads(capsys.readouterr().err)["error"].lower()
    assert "source" in error and "history" in error


# --- the fidelity-scoped maintenance pass (roadmap H255) -------------------
#
# `maintain --fidelity <tier>` is the scheduled-maintenance *act* twin of
# `verify --fidelity` (H252): the holdings-axis sibling of `--source`, but it
# narrows *less*. Only the **recheck** targets the tier (the `verify --fidelity`
# held, hash-bearing subset); the **audit and view regeneration stay whole-
# library** — a fidelity tier spans sources, so `run_doctor`'s source semantics
# (`by_source` collapse, orphan/FTS skip) don't apply, and scoping the audit is a
# separate, larger change deferred (the H255 decision). The pass is still
# non-persisting (records drift events, never the trend baseline → null delta).
# CLI-only (no MCP batch-maintain scope twin, the H252 precedent).


def _seed_mixed_fidelity() -> dict[str, ScrollItem]:
    """Insert a library spanning all three tiers *and* the holdings/verifiable gap.

    Inserted directly (no scroll files written): a `detected`-stage row carries no
    `markdown_path`, and a `rendered` row written without a scroll file is exempt
    from doctor's missing-scroll check (`_check_missing_scrolls` skips rows with no
    `markdown_path`), so the audit stays clean (exit 0) without rendering. Returns
    the items keyed by role so a test can name the exact recheck set.

    - ``full_hashed`` — full fidelity *with* a baseline hash (the `verify --fidelity
      full` set: rechecked).
    - ``full_nohash`` — full fidelity held by raw body alone, no hash to diff (in
      `list --fidelity full`, but *skipped* by the recheck — the holdings vs
      verifiable gap, ADR 0097).
    - ``partial_hashed`` — a hash-bearing partial (extracted body + hash at an
      uncaptured stage; the `verify --fidelity partial` set, a *different* source).
    - ``reference`` — only the pointer, no content/hash (rechecked by neither tier).
    """
    paths = get_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    init_db(paths.db_path)
    items = {
        "full_hashed": _rendered(
            "web", None, "https://example.com/full-hashed", title="Full Hashed"
        ),
        "full_nohash": _rendered(
            "web", None, "https://example.com/full-nohash", title="Full No Hash",
            content_hash=None,
        ),
        "partial_hashed": _rendered(
            "arxiv", "2001.00001", "https://arxiv.org/abs/2001.00001",
            title="Partial Hashed", raw_text=None, extracted_text="extracted body",
            stage="detected",
        ),
        "reference": _rendered(
            "web", None, "https://example.com/reference", title="Reference Only",
            raw_text=None, extracted_text=None, content_hash=None, stage="detected",
        ),
    }
    for item in items.values():
        insert_item(paths.db_path, item)
    return items


def test_seed_mixed_fidelity_spans_the_tiers_and_the_verifiable_gap(home):
    """Guard the fixture's own invariants: the four roles sit at the tiers and
    hash-bearing flags the recheck-scope tests rely on (so a later refactor of
    `_rendered`/`fidelity_tier` can't quietly invalidate them)."""
    items = _seed_mixed_fidelity()
    assert get_fidelity(items["full_hashed"]) == "full" and items["full_hashed"].content_hash
    assert get_fidelity(items["full_nohash"]) == "full" and not items["full_nohash"].content_hash
    assert get_fidelity(items["partial_hashed"]) == "partial" and items["partial_hashed"].content_hash
    assert get_fidelity(items["reference"]) == "reference" and not items["reference"].content_hash


def test_fidelity_scopes_the_recheck_to_that_tiers_hash_bearing_set(
    home, monkeypatch, capsys
):
    """`maintain --fidelity full --all` re-captures only the full-fidelity items
    carrying a baseline hash — the `verify --fidelity full` set — never the
    partial, reference, or hash-less full one."""
    items = _seed_mixed_fidelity()
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain", "--all", "--fidelity", "full"]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["fidelity"] == "full"
    assert report["source"] is None
    # only the one full+hash item was rechecked; full_nohash is skipped (no
    # baseline to diff), partial/reference are other tiers
    assert report["recheck"]["checked"] == 1
    assert report["recheck"]["unchanged"] == 1


def test_fidelity_recheck_set_equals_the_verify_fidelity_hash_bearing_subset(
    home, monkeypatch, capsys
):
    """The set a `maintain --fidelity T` pass rechecks equals `list --fidelity T`'s
    held, *hash-bearing* rows — the same `verify --fidelity T` selection (H252), the
    verify-axis ≡ maintain-axis drill on the holdings filter."""
    _seed_mixed_fidelity()
    capsys.readouterr()
    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)

    # the independently-computed full-tier hash-bearing subset
    held = list_items(get_paths().db_path)
    expected = {
        item.id for item in held
        if get_fidelity(item) == "full" and item.content_hash
    }

    assert main(["maintain", "--all", "--fidelity", "full"]) == 0
    report = json.loads(capsys.readouterr().out)
    # the recheck attempted exactly that set (the report carries counts, so confirm
    # via the per-item ledger the recheck just wrote)
    rechecked = {
        item_id for item_id, event in latest_events(get_paths().db_path).items()
    }
    assert rechecked == expected


def test_fidelity_audit_and_regen_stay_whole_library_unlike_source(
    home, monkeypatch, capsys
):
    """The load-bearing distinction from `--source` (the H255 decision): a fidelity
    scope narrows only the recheck — the audit stays whole-library. So with
    `--fidelity full` the `custody`/`by_source` still report *every* tier and
    *every* source (the partial arxiv item included), equal to an unscoped audit —
    never collapsed to the full tier."""
    _seed_mixed_fidelity()
    capsys.readouterr()
    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)

    assert main(["maintain", "--all", "--fidelity", "full"]) == 0
    report = json.loads(capsys.readouterr().out)

    # the audit is the whole-library picture: all three tiers, both sources
    whole = run_doctor(get_paths())
    assert report["custody"] == custody_snapshot(whole)
    assert report["custody"]["tiers"] == {"full": 2, "partial": 1, "reference": 1}
    assert set(report["by_source"]) == {"web", "arxiv"}
    # the headline is the whole-library snapshot rendered (not a one-tier slice)
    assert report["headline"] == snapshot_headline(report["custody"])


def test_fidelity_pass_is_non_persisting_and_leaves_the_trend_baseline(
    home, monkeypatch, capsys
):
    """A fidelity-scoped pass is a focused triage, not a trend checkpoint: it
    records no snapshot/log and its `delta` is null — a partial-recheck pass must
    not stamp the trend as if it had rechecked the whole library."""
    _seed_mixed_fidelity()
    capsys.readouterr()
    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)

    # one whole-library pass records the single baseline + first log entry
    assert main(["maintain", "--all"]) == 0
    capsys.readouterr()
    baseline = load_snapshot(snapshot_path(home))
    assert baseline is not None
    assert len(read_log(log_path(home))) == 1

    # a fidelity-scoped pass: delta null, baseline/log untouched afterwards
    assert main(["maintain", "--all", "--fidelity", "full"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["delta"] is None
    assert load_snapshot(snapshot_path(home)) == baseline  # not clobbered
    assert len(read_log(log_path(home))) == 1  # no scoped run appended


def test_fidelity_records_drift_events_the_next_whole_pass_folds_in(
    home, monkeypatch, capsys
):
    """The scoped recheck is real work: it appends per-item custody events (the
    next whole-library pass folds them into the trend), even though the scoped pass
    writes no snapshot. Custody-safe: events accrue, the baseline doesn't."""
    items = _seed_mixed_fidelity()
    capsys.readouterr()

    drifted = items["full_hashed"]
    monkeypatch.setattr(cli, "live_recapture", _recapture_drifting(drifted.id))
    assert main(["maintain", "--all", "--fidelity", "full"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["recheck"]["drifted"] == 1

    # the per-item ledger recorded the drift event (a real, persisted change)
    events = latest_events(home.db_path)
    assert events[drifted.id].status == "drifted"
    # but no maintenance snapshot was written (the scoped pass is non-persisting)
    assert load_snapshot(snapshot_path(home)) is None


def test_fidelity_full_skips_a_full_item_without_a_baseline_hash(
    home, monkeypatch, capsys
):
    """The holdings vs verifiable gap (ADR 0097): a full-fidelity capture held by
    raw body alone is in `list --fidelity full`, but with no hash to diff it is
    skipped by the recheck — exactly as `verify --fidelity full` skips it."""
    items = _seed_mixed_fidelity()
    capsys.readouterr()

    # both full items are listed at the full tier...
    assert main(["list", "--fidelity", "full"]) == 0
    listed = {row["id"] for row in json.loads(capsys.readouterr().out)}
    assert listed == {items["full_hashed"].id, items["full_nohash"].id}

    # ...but only the hash-bearing one is rechecked
    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain", "--all", "--fidelity", "full"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["recheck"]["checked"] == 1
    rechecked = set(latest_events(home.db_path))
    assert rechecked == {items["full_hashed"].id}


def test_fidelity_reference_is_an_honest_empty_recheck_with_a_whole_library_audit(
    home, monkeypatch, capsys
):
    """The `reference` tier holds no fingerprint, so its recheck is an empty no-op
    — but the audit stays whole-library (unlike `--source ghost`, which collapses
    everything): the report still names all three tiers, and the empty recheck
    touches no network."""
    _seed_mixed_fidelity()
    capsys.readouterr()

    def explode(_):
        raise AssertionError("a tier with no hash-bearing rows must not re-capture")

    monkeypatch.setattr(cli, "live_recapture", explode)
    assert main(["maintain", "--all", "--fidelity", "reference"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["recheck"]["checked"] == 0
    # the audit is still the whole library — reference scopes the recheck, not the audit
    assert report["custody"]["tiers"] == {"full": 2, "partial": 1, "reference": 1}
    assert report["delta"] is None


def test_fidelity_composes_with_limit(home, monkeypatch, capsys):
    """`--fidelity partial --all --limit 1` bounds the scoped recheck — the partial
    tier here holds one hash-bearing item, so the bound is moot but exercised; the
    flag is accepted alongside the scope (composes scope ∧ bound)."""
    _seed_mixed_fidelity()
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain", "--all", "--limit", "1", "--fidelity", "partial"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["recheck"]["checked"] == 1  # the one hash-bearing partial


def test_fidelity_no_recheck_reports_the_tier_scoped_coverage(home, capsys):
    """`--no-recheck --fidelity full` skips the live edge but still reports the
    full tier's coverage — `verified`/`total` over the full-fidelity hash-bearing
    held set (one item here), not the whole library (the offline `--source` shape,
    holdings axis)."""
    _seed_mixed_fidelity()
    capsys.readouterr()

    assert main(["maintain", "--no-recheck", "--fidelity", "full"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["recheck"]["skipped"] is True
    # one full+hash item, never verified yet → 0 of 1 covered (not the whole library)
    assert report["recheck"]["coverage"] == {"verified": 0, "total": 1}


def test_fidelity_conflicts_with_source(home, capsys):
    """`--source` and `--fidelity` are the two custody scope axes — one per pass
    (the source axis scopes recheck+audit, the fidelity axis only the recheck), so
    combining them is a usage error (exit 2), not a silently-honored one."""
    assert main(["maintain", "--source", "web", "--fidelity", "full"]) == 2
    error = json.loads(capsys.readouterr().err)["error"].lower()
    assert "source" in error and "fidelity" in error


def test_fidelity_conflicts_with_history(home, capsys):
    """`--fidelity` scopes a pass; `--history` is a read of recorded passes — a
    usage error (exit 2), the `--source`/history precedent on the holdings axis."""
    assert main(["maintain", "--fidelity", "full", "--history"]) == 2
    error = json.loads(capsys.readouterr().err)["error"].lower()
    assert "fidelity" in error and "history" in error


def test_fidelity_unknown_tier_is_a_closed_vocabulary_exit_2(home):
    """The fidelity vocabulary is closed (argparse choices): a typo is a loud exit
    2, never a silently empty pass that could mask the mistake (the `verify
    --fidelity` / `verify --drift` precedent)."""
    with pytest.raises(SystemExit) as excinfo:
        main(["maintain", "--fidelity", "bogus", "--no-recheck"])
    assert excinfo.value.code == 2


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
