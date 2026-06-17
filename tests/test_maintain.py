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
from dataclasses import replace

import pytest

import scrolls.cli as cli
from scrolls.cli import main
from scrolls.custody import CustodyEvent, latest_events, record_events
from scrolls.db import init_db
from scrolls.items import (
    ScrollItem,
    get_item,
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
    save_snapshot,
    snapshot_path,
    suggest_repairs,
)
from scrolls.paths import get_paths
from scrolls.render import write_scroll

# --- the delta layer (pure) -----------------------------------------------


def _doctor_report(score, tiers, drift, enrichment_stale=0, summaries_stale=0):
    """A minimal doctor report shaped like `run_doctor`'s custody block."""
    full_drift = {
        "checked": 0, "unverified": 0, "unchanged": 0,
        "drifted": 0, "rotted": 0, "error": 0,
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
    )
    snap = custody_snapshot(report)
    assert snap == {
        "score": 90,
        "tiers": {"full": 3, "partial": 1, "reference": 0},
        "drift": {
            "checked": 2, "unverified": 2, "unchanged": 1,
            "drifted": 1, "rotted": 0, "error": 0,
        },
        "enrichment_stale": 2,
        "summaries_stale": 1,
    }


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


def _run(recorded_at, score, drifted=0, rotted=0):
    return {
        "recorded_at": recorded_at,
        "snapshot": {
            "score": score,
            "drift": {"drifted": drifted, "rotted": rotted},
        },
        "delta": {},
    }


def test_trend_under_two_runs_is_not_a_trajectory():
    """A single point has no direction — honest absence, not a fabricated zero."""
    for window in ([], [_run("t1", 100)]):
        trend = compute_trend(window)
        assert trend["posture"] == "insufficient-history"
        assert trend["score"] is None and trend["drift_change"] is None
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
