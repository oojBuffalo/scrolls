"""Scheduled custody maintenance — the delta layer (roadmap H22/H23/H34).

`scrolls maintain` is the dogfood flow's recurring sibling: one agent-runnable
pass that *audits*, runs a *bounded drift recheck*, *regenerates views*, and
reports a **custody delta** against the previous run. The composition of audit
(`run_doctor`), recheck (`verify`), and regenerate (`compile_kb`) already ships
and lives in `cli._cmd_maintain`; this module owns the one genuinely new piece:
distilling a doctor report into a comparable **custody snapshot** and computing
the delta between this run's snapshot and the last recorded one.

Custody posture (custody-vision §2.4). A snapshot is a *record*, like the
custody ledger — never raw data, always regenerable from a fresh `doctor` run.
It is stored at `root/.maintenance/last-run.json`, dot-prefixed so it is never a
compiled `library/` page and never created by `init`; losing or corrupting it
just means "first run" (no baseline), so the maintenance pass degrades safely.
The snapshot carries only the custody-relevant scalars the delta compares —
score, fidelity tiers, drift posture, and the stale enrichment/summary counts —
so the diff stays small and the artifact is human-readable.

The delta is **cross-run** (vs the previous recorded snapshot), not within-run:
the authoritative snapshot is the *post-maintenance* state, so the maintenance
command records fresh drift events and regenerates views first, then audits
once, and that single picture is both reported and recorded for next time. The
delta tolerates a missing baseline (`first_run`) and missing axes (a snapshot
written by an older schema), mirroring the forward-compatible item import
(ADR 0082): unknown keys are ignored, absent counts default to zero.

Alongside `last-run.json` (the single baseline for the next delta), each run
also **appends** its `{recorded_at, snapshot, delta}` record to an append-only
`<root>/.maintenance/log.jsonl` (roadmap H36). The log is the custody *trend*,
not just the last diff: a worker or agent reads the score/drift trajectory over
time from `scrolls maintain --history`. It follows the custody-ledger posture
(custody-vision §2.4) — append, never rewrite — and the same degrade-safely
read posture as the snapshot: a missing log is an empty history (never an
error), and one corrupt line is skipped rather than hiding every good run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scrolls.paths import LibraryPaths

# The axes a snapshot carries from a doctor report. `score`/`enrichment_stale`/
# `summaries_stale` are scalar; `tiers`/`drift` are count mappings.
_DRIFT_AXES = ("checked", "unverified", "unchanged", "drifted", "rotted", "error")

# Each repairable finding category maps to the one explicit, on-request command
# that closes it — maintain *names* the command, never runs it (custody §2.4:
# `doctor --fix` / `scrolls media` / `classify --stale` / `kb --stale` stay the
# explicit mutations). Ordered so the `suggested` block is deterministic, and
# grouped by command: the three structural categories `doctor --fix` repairs
# (duplicate items, missing scroll files, an out-of-sync FTS index) share one
# suggestion rather than three identical ones. `orphan_scrolls` has no entry:
# doctor never deletes a file it cannot prove it wrote, so there is no on-request
# repair to suggest — the orphan is surfaced (it still bumps `issues`/the exit
# code), never acted on, so maintain points at a command only when one actually
# closes the gap.
_REPAIR_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("scrolls doctor --fix", ("duplicates", "missing_scrolls", "fts")),
    ("scrolls media", ("missing_media",)),
    ("scrolls classify --stale", ("enrichment_stale",)),
    ("scrolls kb --stale", ("summaries_stale",)),
)

SNAPSHOT_RELPATH = Path(".maintenance") / "last-run.json"
LOG_RELPATH = Path(".maintenance") / "log.jsonl"

# `scrolls maintain --history` with no count prints this many recent runs.
DEFAULT_HISTORY_LIMIT = 10


def snapshot_path(paths: LibraryPaths) -> Path:
    """Where a library's last maintenance snapshot is recorded."""
    return paths.root / SNAPSHOT_RELPATH


def log_path(paths: LibraryPaths) -> Path:
    """Where a library's append-only maintenance run log lives."""
    return paths.root / LOG_RELPATH


def custody_snapshot(doctor_report: dict[str, Any]) -> dict[str, Any]:
    """Distil a `run_doctor` report into the comparable custody scalars.

    Reads only the report's custody view, never the structural repair counts —
    maintain reports custody posture, and `doctor` already owns structural drift.
    """
    custody = doctor_report["custody"]
    drift = custody["drift"]
    return {
        "score": custody["score"],
        "tiers": dict(custody["tiers"]),
        "drift": {axis: drift[axis] for axis in _DRIFT_AXES},
        "enrichment_stale": custody["enrichment"]["stale"],
        "summaries_stale": custody["summaries"]["stale"],
    }


def _finding_present(report: dict[str, Any], category: str) -> bool:
    """Whether a doctor report carries this repairable finding category.

    Read directly from the *full* report `run_doctor` returns (not the distilled
    snapshot, which drops the structural findings): a non-empty findings list, an
    out-of-sync FTS index, or a non-zero stale enrichment/summary count.
    """
    if category == "fts":
        # `in_sync` is None when the check was skipped/unsupported — only a
        # definite False is the repairable "out of sync" finding `doctor --fix`
        # rebuilds, not an absent or indeterminate one.
        return report.get("fts", {}).get("in_sync") is False
    if category == "enrichment_stale":
        return report.get("custody", {}).get("enrichment", {}).get("stale", 0) > 0
    if category == "summaries_stale":
        return report.get("custody", {}).get("summaries", {}).get("stale", 0) > 0
    return bool(report.get(category))  # duplicates / missing_scrolls / missing_media


def suggest_repairs(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Name the explicit on-request command that closes each finding (roadmap H40).

    maintain audits and reports but never repairs (custody §2.4); this turns the
    audit's findings into *actionable guidance* — for each repairable category in
    the report, the explicit command an operator or agent runs to close it. The
    structural fixes `doctor --fix` performs are grouped into one suggestion;
    missing media (`scrolls media`), stale classifications (`classify --stale`),
    and stale summaries (`kb --stale`) are each their own.

    Suggested **by category, never by the aggregate `issues` count**: an orphan
    scroll bumps `issues` (and the exit code) but has no on-request repair, so it
    yields no suggestion — maintain never points at a command that would not
    actually close the gap. A clean report yields the honest empty list (G1).

    Each entry is ``{command, addresses}`` where `addresses` lists exactly the
    finding categories present that the command closes, in a fixed order.
    """
    suggestions = []
    for command, categories in _REPAIR_COMMANDS:
        addresses = [c for c in categories if _finding_present(report, c)]
        if addresses:
            suggestions.append({"command": command, "addresses": addresses})
    return suggestions


def _scalar_delta(before: int | None, after: int | None) -> dict[str, Any]:
    """before/after/change for one count; change is null on the first run."""
    change = None if before is None or after is None else after - before
    return {"before": before, "after": after, "change": change}


def _mapping_delta(
    before: dict[str, int] | None, after: dict[str, int]
) -> dict[str, dict[str, Any]]:
    """Per-key scalar deltas over the union of a count mapping's keys.

    A key present in only one side defaults to zero on the other (a tier that
    appeared or emptied between runs), so the change is always meaningful.
    """
    keys = sorted(set(after) | set(before or {}))
    return {
        key: _scalar_delta(
            None if before is None else before.get(key, 0), after.get(key, 0)
        )
        for key in keys
    }


def compute_delta(
    previous: dict[str, Any] | None, current: dict[str, Any]
) -> dict[str, Any]:
    """The custody change since the last run: per-axis before/after/change.

    `previous` is ``None`` only when there is no baseline at all (the first ever
    run) — then every ``before``/``change`` is ``null`` and ``first_run`` is
    true. A *present* baseline missing an axis (an older snapshot schema) reads
    as zero for that axis, never null: the run happened, the count was simply
    not yet tracked. The two cases are kept distinct so "first run" never hides
    a real-but-incomplete prior snapshot.
    """
    first_run = previous is None

    def scalar(key: str) -> dict[str, Any]:
        before = None if first_run else previous.get(key, 0)
        return _scalar_delta(before, current[key])

    def mapping(key: str) -> dict[str, dict[str, Any]]:
        before = None if first_run else previous.get(key, {})
        return _mapping_delta(before, current[key])

    return {
        "first_run": first_run,
        "since": None if first_run else previous.get("recorded_at"),
        "score": scalar("score"),
        "tiers": mapping("tiers"),
        "drift": mapping("drift"),
        "enrichment_stale": scalar("enrichment_stale"),
        "summaries_stale": scalar("summaries_stale"),
    }


def load_snapshot(path: Path) -> dict[str, Any] | None:
    """The last recorded snapshot, or ``None`` if missing or unreadable.

    A maintenance pass must not abort because its own bookkeeping file is gone
    or corrupt: an unreadable baseline degrades to "first run", never an error.
    """
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def save_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    """Record this run's snapshot, creating `.maintenance/` if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")


def compute_trend(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Distil a window of maintenance runs into a custody *trajectory* (H46).

    Reads only the first and last run's recorded snapshot in the window — the
    net `score` change and the net drift/rot movement across the span — plus a
    one-word `posture` so an unattended worker reads the direction directly,
    without diffing entries itself. The rule, integrity-first:

    - a *drop* in `score` is `regressing` (we hold less faithfully than before);
    - else *more* drifted/rotted scrolls is `regressing` (the sources moved);
    - else a *rise* in `score` or *fewer* drifted/rotted is `improving`;
    - else `holding`.

    Honest absence (the H21/H29 posture): a window of fewer than two runs is not
    a trajectory — a single point has no direction — so it carries null deltas
    and `posture` ``insufficient-history``. A `score` that is ``None`` on either
    end (an uninitialized-library run) yields a null score `change`, never a
    fabricated zero; the drift movement is still computed (absent counts read 0).
    """
    n = len(runs)
    if n < 2:
        return {
            "runs": n,
            "since": None,
            "score": None,
            "drift_change": None,
            "posture": "insufficient-history",
        }

    first, last = runs[0], runs[-1]
    first_snap, last_snap = first.get("snapshot", {}), last.get("snapshot", {})
    first_score, last_score = first_snap.get("score"), last_snap.get("score")
    score_change = (
        None if first_score is None or last_score is None else last_score - first_score
    )

    def _drift_total(snap: dict[str, Any]) -> int:
        drift = snap.get("drift", {})
        return drift.get("drifted", 0) + drift.get("rotted", 0)

    drift_change = _drift_total(last_snap) - _drift_total(first_snap)

    if score_change is not None and score_change < 0:
        posture = "regressing"
    elif drift_change > 0:
        posture = "regressing"
    elif score_change is not None and score_change > 0:
        posture = "improving"
    elif drift_change < 0:
        posture = "improving"
    else:
        posture = "holding"

    return {
        "runs": n,
        "since": first.get("recorded_at"),
        "score": {"first": first_score, "last": last_score, "change": score_change},
        "drift_change": drift_change,
        "posture": posture,
    }


def append_log_entry(path: Path, entry: dict[str, Any]) -> None:
    """Append one run's record to the maintenance log (append-only).

    The custody-ledger posture (custody-vision §2.4): a maintenance run is an
    event, so the log grows by appending a single JSON line, never by rewriting
    earlier runs. `.maintenance/` is created on demand, mirroring `save_snapshot`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def read_log(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    """The recorded maintenance runs oldest-first; the last `limit` if given.

    Custody-safe like `load_snapshot`: a missing log is an empty history (honest
    absence, never an error), and a corrupt or blank line is skipped rather than
    aborting the whole read — one bad append never hides the good runs before it.
    A non-positive `limit` is an empty window; `None` returns the full history.
    """
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    entries: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            loaded = json.loads(line)
        except ValueError:
            continue
        if isinstance(loaded, dict):
            entries.append(loaded)
    if limit is not None:
        entries = entries[-limit:] if limit > 0 else []
    return entries
