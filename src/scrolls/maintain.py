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
score, fidelity tiers, drift posture, recheck coverage, and the stale
enrichment/summary counts — so the diff stays small and the artifact is
human-readable. Recheck coverage (the `{verified, total}` fraction of the
verifiable held set, roadmap H115) rides the snapshot so `maintain --history` /
`--trend` show the monotone-coverage progress the bounded recheck (H55/H83)
drives across runs, not just a point-in-time figure on one report.

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

from scrolls.custody import parse_since, render_custody_headline
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

    Includes the recheck `coverage` (`{verified, total}` over the verifiable
    held set, roadmap H113/H115) the audit's drift block carries, so the snapshot
    records *how much* of the library is covered — the monotone-coverage progress
    a bounded recheck (H55/H83) drives, made visible across `--history`/`--trend`,
    not just on a single pass's report (H109). Read defensively (the module's
    degrade-safely posture): a report whose drift block predates H113 reads the
    honest zeroed `{verified: 0, total: 0}`, never a `KeyError`.
    """
    custody = doctor_report["custody"]
    drift = custody["drift"]
    return {
        "score": custody["score"],
        "tiers": dict(custody["tiers"]),
        "drift": {axis: drift[axis] for axis in _DRIFT_AXES},
        "coverage": dict(drift.get("coverage", {"verified": 0, "total": 0})),
        "enrichment_stale": custody["enrichment"]["stale"],
        "summaries_stale": custody["summaries"]["stale"],
    }


# The custody snapshot's `drift` carries doctor's vocabulary
# (`checked`/`unchanged`/…); the shared headline renderer wants drift *postures*
# (`verified`/…). The one documented mapping is `verified ≡ unchanged`; the rest
# carry over by name. `checked` is the verdict *total*, not a posture, so it is
# not rendered (it is `unchanged + drifted + rotted + error`).
_SNAPSHOT_POSTURE_AXES = ("unverified", "drifted", "rotted", "error")


def snapshot_headline(snapshot: dict[str, Any]) -> str:
    """The one-line ``_Custody: …_`` headline for a recorded custody snapshot (H103).

    Every scope custody surface carries the shared `custody.custody_headline` —
    `status` (H38), the bundle briefing (H45), the `context` bundle (H47), the
    compiled `library/` pages (H95/H96) — *except* the scheduled worker's own
    primary report. `scrolls maintain` records the custody snapshot (score /
    fidelity tiers / drift posture counts) but rendered no one-line headline; this
    renders it, so the unattended worker's JSON log reads the same one-line custody
    picture the Markdown surfaces emit, without parsing the raw counts.

    Rendered from the **snapshot** the run records (not items + a fresh ledger
    read), so it converges by construction with the `custody` block it sits beside
    *and* the live pass and the `--history`/`--trend` reads share one renderer —
    a recorded snapshot has only the counts, not the items. The snapshot's `drift`
    uses doctor's vocabulary, mapped into postures by the documented
    ``verified ≡ unchanged`` rule (the rest by name; `checked` is not a posture and
    is not shown). `n` (the held total) is the tier sum — every scroll contributes
    exactly one fidelity tier — so it equals `custody_headline`'s `len(items)`. A
    snapshot missing an axis (an older schema, or no library — `score: None`,
    all-zero tiers) reads zero, the honest ``_Custody: 0 scroll(s)._``.
    """
    tiers = snapshot.get("tiers", {})
    drift = snapshot.get("drift", {})
    postures = {"verified": drift.get("unchanged", 0)}
    postures.update((axis, drift.get(axis, 0)) for axis in _SNAPSHOT_POSTURE_AXES)
    return render_custody_headline(sum(tiers.values()), tiers, postures)


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


def report_by_source(report: dict[str, Any]) -> dict[str, dict[str, dict[str, int]]]:
    """The per-source custody breakdown from this pass's doctor audit (roadmap H123).

    `doctor`'s `custody` block carries a `by_source` map — the whole-library
    fidelity-tier / drift-posture aggregate split per source (`custody.custody_counts_by_source`,
    roadmap H104) — so the audit names *which* source's custody is weakest (most
    reference-only, most drifted: the source to target a `verify --drift`/`media`/
    recapture at). The scheduled worker's own `maintain` report distils only the
    *whole-library* `custody_snapshot` (which drops `by_source`), so an unattended
    log could not show the per-source picture without re-running `doctor`. This
    threads the breakdown the audit already produces into the report.

    A pure read of the report `run_doctor` returns — **no new ledger read**, the
    map is already computed in the audit. Surfaced **live-pass only** (like
    `suggest_repairs` H40 and the recheck `scope`/`since` H83): it is derived fresh
    from this pass's audit, never recorded in the snapshot/log, so `--history` /
    `--trend` (which replay recorded snapshots) carry none. Because each per-source
    group folds through the same `custody_counts`, the breakdown sums to the
    whole-library `custody` block the report carries beside it by construction
    (the H104 sum-to-whole posture, per source — every item lands in exactly one
    source group). Each entry also carries the per-source ``coverage``
    (``{verified, total}``, roadmap H121) the audit folds into `custody_counts_by_source`,
    so the scheduled worker's per-source picture names which source is least
    *covered* too, at parity with `doctor`. Honest absence: a report without the block
    (an empty library, or an older schema) reads as the empty map, never a `KeyError`
    — the module's degrade-safely posture on this axis.
    """
    return dict(report.get("custody", {}).get("by_source", {}))


# The actionable-loss postures: the items confirmed to have moved or gone since
# capture (a follow-up `verify --drift drifted`/`media` targets exactly these).
# `unverified` (never checked) and `error` (a transient re-check failure) are not
# *confirmed* loss, so they do not flag a source — `drifted`/`rotted` do.
_LOSS_POSTURES = ("drifted", "rotted")


def _source_loss(tally: dict[str, dict[str, int]]) -> int:
    """How many of a source's held items are confirmed drifted or rotted."""
    drift = tally.get("drift", {})
    return sum(drift.get(posture, 0) for posture in _LOSS_POSTURES)


def weakest_source(
    by_source: dict[str, dict[str, dict[str, int]]]
) -> dict[str, Any] | None:
    """The single source carrying the most actionable custody loss (roadmap H119).

    H123 threads `doctor`'s *whole* per-source breakdown (`custody.by_source`,
    H104) into the `maintain` report; this distils that map to the **one** source
    worth flagging, so an unattended log reads "source `x` is weakest — N drifted"
    without scanning every source. Weakest = the most **actionable loss**: the most
    `drifted` + `rotted` items (the sources *confirmed* to have moved or gone — the
    set a follow-up `verify --drift`/`media` targets), tie-broken by the most
    `reference`-only items (lowest fidelity), then the source name (so the pick is
    deterministic). Returns ``{source, tiers, drift, reason}`` — the flagged
    source's own tally (so the per-source picture rides along) plus a one-line
    reason naming the loss that earned the flag.

    Honest absence (`None`), the report's first-run/empty posture, on three counts:

    - an **empty** map — no library / no sources, nothing to flag;
    - a **single** source — no source *stands out*; the whole-library `custody`
      block already says everything `attention` could, which only adds value by
      discriminating *across* sources, so a one-source library is null even when it
      carries drift;
    - a **fully-clean** library — no source carries any `drifted`/`rotted` loss, so
      there is nothing actionable to flag (reference-only is the normal capture
      posture, a tie-breaker, never a trigger on its own).

    Pure over the `by_source` map — **no new ledger read**; surfaced live-pass only
    (like `report_by_source`/`suggest_repairs`), so `--history`/`--trend` carry none.
    """
    if len(by_source) < 2:
        return None
    source, tally = min(
        by_source.items(),
        key=lambda kv: (-_source_loss(kv[1]), -kv[1].get("tiers", {}).get("reference", 0), kv[0]),
    )
    if _source_loss(tally) == 0:
        return None
    return {
        "source": source,
        "tiers": tally["tiers"],
        "drift": tally["drift"],
        "reason": _attention_reason(tally),
    }


def _attention_reason(tally: dict[str, dict[str, int]]) -> str:
    """A one-line reason naming the actionable loss that flagged a source.

    Lists only the non-zero loss postures (`drifted`/`rotted`) in canonical order —
    e.g. ``"2 drifted, 1 rotted"`` — never empty (a source is flagged only when its
    loss is non-zero), so the log line is always self-describing.
    """
    drift = tally.get("drift", {})
    return ", ".join(
        f"{drift[posture]} {posture}" for posture in _LOSS_POSTURES if drift.get(posture)
    )


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
        # recheck coverage `{verified, total}` (H115): a count mapping like
        # `tiers`/`drift`, so it diffs per-key. A baseline lacking it (a pre-H115
        # snapshot) reads as zero for each key, never null — the run happened, the
        # coverage was simply not yet tracked (the missing-axis posture, ADR 0082).
        "coverage": mapping("coverage"),
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


def last_run_boundary(previous: dict[str, Any] | None) -> str | None:
    """The staleness boundary the default recheck windows by — the last run's
    `recorded_at`, normalized — or ``None`` to recheck everything (roadmap H83).

    A scheduled `scrolls maintain` pass should re-verify only what has *not been
    seen since the last sweep*, not the whole library every run. That window's
    boundary is exactly the timestamp the previous run recorded: an item whose
    newest ledger verdict predates it is stale (`custody.items_checked_before`),
    one checked at/after it is fresh. This reads that boundary off the last
    recorded snapshot (`load_snapshot`), normalized through the shared
    `custody.parse_since` (so it is the same ``+00:00`` shape a stored
    `checked_at` carries — the compare is apples-to-apples).

    ``None`` means *no boundary* → recheck every held item (the coverage-first
    H55 order): on the **first run** there is no baseline, and a missing, blank,
    or corrupt `recorded_at` degrades to the same "recheck all" — the module's
    degrade-safely posture (a lost snapshot already means "first run"; a lost
    *timestamp* means "re-verify everything", never an aborted pass). The
    never-checked-is-trivially-stale property makes the first-run full recheck a
    natural special case of the windowed one (a far-past/absent boundary selects
    everything), so the two paths agree.
    """
    if previous is None:
        return None
    recorded_at = previous.get("recorded_at")
    if not recorded_at:
        return None
    try:
        return parse_since(recorded_at)
    except ValueError:
        return None


def compute_trend(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Distil a window of maintenance runs into a custody *trajectory* (H46).

    Reads only the first and last run's recorded snapshot in the window — the
    net `score` change, the net drift/rot movement, and the net recheck-coverage
    movement across the span — plus a one-word `posture` so an unattended worker
    reads the direction directly, without diffing entries itself. The posture
    rule is **integrity-first** — score, then confirmed drift:

    - a *drop* in `score` is `regressing` (we hold less faithfully than before);
    - else *more* drifted/rotted scrolls is `regressing` (the sources moved);
    - else a *rise* in `score` or *fewer* drifted/rotted is `improving`;
    - else `holding`.

    ``coverage_change`` (``{verified, total}`` net deltas, roadmap H115) is a
    *separate* axis the worker reads alongside the posture — "is the library
    getting more covered?" (Δ``verified`` up as bounded passes verify the
    never-checked tail; Δ``total`` up as new verifiable items are added). It is
    **deliberately not folded into `posture`**: coverage measures *how much has
    been checked*, not *how faithfully we hold what we have*, so rising coverage
    is not "improving" custody integrity and a steady library that simply has not
    been re-checked is not "regressing". Keeping `posture` integrity-only leaves
    the H46 rule unchanged; coverage is reported, never a posture trigger.

    Honest absence (the H21/H29 posture): a window of fewer than two runs is not
    a trajectory — a single point has no direction — so it carries null deltas
    (including ``coverage_change``) and `posture` ``insufficient-history``. A
    `score` that is ``None`` on either end (an uninitialized-library run) yields a
    null score `change`, never a fabricated zero; the drift and coverage movement
    are still computed (absent counts read 0, so a pre-H115 endpoint reads 0).
    """
    n = len(runs)
    if n < 2:
        return {
            "runs": n,
            "since": None,
            "score": None,
            "drift_change": None,
            "coverage_change": None,
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

    def _coverage(snap: dict[str, Any], axis: str) -> int:
        return snap.get("coverage", {}).get(axis, 0)

    coverage_change = {
        "verified": _coverage(last_snap, "verified") - _coverage(first_snap, "verified"),
        "total": _coverage(last_snap, "total") - _coverage(first_snap, "total"),
    }

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
        "coverage_change": coverage_change,
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
