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
from scrolls.db import init_db
from scrolls.items import ScrollItem, get_item, item_to_dict, list_items, make_item_id
from scrolls.maintain import (
    append_log_entry,
    compute_delta,
    custody_snapshot,
    load_snapshot,
    log_path,
    read_log,
    save_snapshot,
    snapshot_path,
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
    drift posture moving (unverified → drifted) while the score holds at 100."""
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _identity_recapture)
    assert main(["maintain"]) == 0
    first = json.loads(capsys.readouterr().out)
    drifted = items[0]
    before = get_item(home.db_path, drifted.id)

    monkeypatch.setattr(cli, "live_recapture", _recapture_drifting(drifted.id))
    assert main(["maintain"]) == 0
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
