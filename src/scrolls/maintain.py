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
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scrolls.paths import LibraryPaths

# The axes a snapshot carries from a doctor report. `score`/`enrichment_stale`/
# `summaries_stale` are scalar; `tiers`/`drift` are count mappings.
_DRIFT_AXES = ("checked", "unverified", "unchanged", "drifted", "rotted", "error")

SNAPSHOT_RELPATH = Path(".maintenance") / "last-run.json"


def snapshot_path(paths: LibraryPaths) -> Path:
    """Where a library's last maintenance snapshot is recorded."""
    return paths.root / SNAPSHOT_RELPATH


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
