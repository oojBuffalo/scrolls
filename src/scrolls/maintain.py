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

import dataclasses
import json
from pathlib import Path
from typing import Any

from scrolls.custody import (
    latest_events,
    parse_since,
    recheck_coverage,
    render_custody_headline,
    weakest_source,
)
from scrolls.doctor import run_doctor
from scrolls.items import get_fidelity, list_items
from scrolls.kb import compile_kb
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

# The two refresh findings whose command takes a `--source <S>` scope
# (`classify --stale --source` H154, `kb --stale --source` H172). When such a
# finding's stale debt is confined to a *strict subset* of the library's held
# sources, `suggest_repairs` names the minimal scoped act per offending source
# instead of the whole-library sweep (roadmap H181) — consulting the same
# per-source maps the report's `enrichment_by_source`/`summary_by_source` carry.
_SCOPABLE_REFRESH = frozenset({"enrichment_stale", "summaries_stale"})

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


def suggest_repairs(
    report: dict[str, Any], source: str | None = None
) -> list[dict[str, Any]]:
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

    The two enrichment-axis refreshes (`classify --stale`, `kb --stale`) are
    further **source-scoped** when their debt is confined (roadmap H181): if the
    stale items/summaries sit in a strict subset of the library's held sources, the
    suggestion becomes one ``--source <S>`` command per offending source — the
    minimal act, never re-running the clean sources — instead of the whole-library
    sweep. See `_scoped_refresh`.

    `source` is the scope a `maintain --source <S>` pass ran under (roadmap H182):
    when set, the audit was already pre-filtered to <S> (its held-source universe
    collapsed to ``{S}``, so the H181 strict-subset rule would emit the *whole-library*
    sweep — wrong for a deliberately scoped pass). A scoped pass therefore always
    names the scoped refresh ``<command> --source <S>`` when the finding is present,
    honoring the operator's declared scope. The whole-library pass (`source` ``None``)
    is unchanged.
    """
    # The held-source universe (every held source, clean or not) — `doctor`'s
    # `custody.by_source` (H104). A refresh finding's debt is "confined" when its
    # offending sources are a strict subset of this; an absent block (an empty or
    # pre-H104 report) leaves it empty, so scoping degrades to the whole-library
    # command rather than scoping over a universe it cannot see.
    held_sources = set(report.get("custody", {}).get("by_source", {}))
    suggestions = []
    for command, categories in _REPAIR_COMMANDS:
        addresses = [c for c in categories if _finding_present(report, c)]
        if not addresses:
            continue
        # The scopable refreshes each own their command group alone (a single
        # category), so a confined one expands into per-source commands; the
        # grouped structural/media suggestions keep their whole-library shape.
        if len(addresses) == 1 and addresses[0] in _SCOPABLE_REFRESH:
            suggestions += _scoped_refresh(
                command, addresses[0], report, held_sources, source
            )
        else:
            suggestions.append({"command": command, "addresses": addresses})
    return suggestions


def _scoped_refresh(
    command: str,
    category: str,
    report: dict[str, Any],
    held_sources: set[str],
    source: str | None = None,
) -> list[dict[str, Any]]:
    """The minimal scoped act(s) for one confined refresh finding (roadmap H181/H182).

    Refines `suggest_repairs`' two `--source`-scopable refreshes (`classify --stale`
    H154, `kb --stale` H172). The offending sources are this pass's audit map
    (`custody.enrichment.by_source` H135 / `custody.summaries.by_source` H171, the
    same `enrichment_by_source`/`summary_by_source` the report carries); `held_sources`
    is the whole-library universe (`custody.by_source` H104). When the offenders are a
    **strict** subset — at least one held source is clean on this axis — a scoped
    ``--source <S>`` command per offender is more targeted than the whole-library
    sweep, which would re-run the clean sources too. When every held source is stale
    (offenders == universe) *or* the universe is unknown (a pre-H104 report with no
    `by_source`), scoping buys nothing, so the whole-library command — already the
    minimal act — stands.

    On the **summary axis** the H171 attribution carries through: a stale concept
    spanning several sources is "stale for" each, so `summary_by_source` names them
    all and each earns its own scoped `kb --stale --source <S>`. Refreshing under any
    one of them regenerates the whole cluster (H172), so the per-offender commands
    *double-cover* a shared cluster — a harmless redundancy (regeneration is
    idempotent), the price of the minimal-per-source shape; their union still
    refreshes exactly the offenders set, missing nothing.

    `source` short-circuits this for an explicitly scoped pass (roadmap H182): a
    `maintain --source <S>` pass pre-filtered the audit to <S>, so `held_sources` has
    collapsed to ``{S}`` and the offenders are ``{S}`` too — making the strict-subset
    test above False, which would emit the whole-library sweep even though the operator
    scoped to <S>. When `source` is set the finding is present *for <S>* (the scoped
    audit attributes it to no one else), so the minimal act is exactly the scoped
    ``<command> --source <S>`` — one command, named after the declared scope rather
    than re-derived from the collapsed universe.
    """
    if source is not None:
        return [{"command": f"{command} --source {source}", "addresses": [category]}]
    reader = (
        report_enrichment_by_source
        if category == "enrichment_stale"
        else report_summary_by_source
    )
    offenders = sorted(reader(report))
    if offenders and set(offenders) < held_sources:
        return [
            {"command": f"{command} --source {s}", "addresses": [category]}
            for s in offenders
        ]
    return [{"command": command, "addresses": [category]}]


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


def report_enrichment_by_source(report: dict[str, Any]) -> dict[str, int]:
    """The per-source stale-classification debt from this pass's doctor audit (roadmap H147).

    `doctor`'s `custody.enrichment` block carries a `by_source` map (roadmap H135) —
    a flat ``{source: stale_count}`` of the *offending* sources only (a source with
    no stale classifications is omitted, the ``items``-list posture), source keys in
    sorted order, summing to the whole-library ``enrichment.stale`` by construction.
    It names *which* source's `classify --stale` an operator should run — the
    re-derivability counterpart of `report_by_source`'s per-source coverage on the
    drift axis (H123). The scheduled worker's own `maintain` report distils only the
    *whole-library* `enrichment_stale` scalar (via `custody_snapshot`), so an
    unattended log could not name the source without re-running `doctor`. This threads
    the per-source map the audit already produces into the report.

    A pure read of the report `run_doctor` returns — **no new read**, the map is
    already computed in the audit (`doctor._check_enrichment_provenance`). A
    **standalone** report member, not folded into the drift `by_source` entries, so
    the H123 ``by_source`` ≡ `custody_counts_by_source` byte-identity and the H127
    convergence stay untouched (mirroring how H135 kept it under `custody.enrichment`,
    not `custody.by_source`). Surfaced **live-pass only** (like `report_by_source`
    H123, `suggest_repairs` H40, and the recheck `scope`/`since` H83): derived fresh
    from this pass's audit, never recorded in the snapshot/log, so `--history` /
    `--trend` (which replay recorded snapshots) carry none. Honest absence: a report
    without the block (an empty library, no stale items, or an older schema) reads as
    the empty map, never a `KeyError` — the module's degrade-safely posture on this axis.
    """
    return dict(report.get("custody", {}).get("enrichment", {}).get("by_source", {}))


def report_summary_by_source(report: dict[str, Any]) -> dict[str, int]:
    """The per-source stale-summary debt from this pass's doctor audit (roadmap H171/H175).

    `doctor`'s `custody.summaries` block carries a `by_source` map (roadmap H171) —
    a flat ``{source: stale_count}`` of the *offending* sources only (a source with
    no stale summaries is omitted, the ``items``-list posture), source keys in sorted
    order. It names *which* source's `kb --stale` an operator should run — the
    summary-axis sibling of `report_enrichment_by_source` (H147), which does the same
    on the classification axis. The scheduled worker's own `maintain` report distils
    only the *whole-library* `summaries_stale` scalar (via `custody_snapshot`), so an
    unattended log could not name the source without re-running `doctor`. This threads
    the per-source map the audit already produces into the report.

    A pure read of the report `run_doctor` returns — **no new read**, the map is
    already computed in the audit (`doctor._check_summary_provenance`). A **standalone**
    report member, like `report_enrichment_by_source`.

    **The load-bearing asymmetry (H171):** a concept summary spans a *cluster* whose
    live members can come from several sources, and the stored fingerprint records only
    the digest (not which member moved), so a stale summary is attributed to *every*
    source among its members. One multi-source stale concept therefore counts toward
    each contributing source, and ``sum(by_source.values()) >= summaries_stale`` —
    the map need **not** sum to the whole, unlike the drift/enrichment maps where each
    item has exactly one source. The `maintain`↔`doctor` tie is consequently
    **faithful-read equality** (``summary_by_source == doctor.custody.summaries.by_source``),
    never a sum-to-whole check.

    Surfaced **live-pass only** (like `report_enrichment_by_source` H147, `report_by_source`
    H123, `suggest_repairs` H40): derived fresh from this pass's audit, never recorded
    in the snapshot/log, so `--history` / `--trend` (which replay recorded snapshots)
    carry none. Honest absence: a report without the block (an empty library, no stale
    summaries, or an older schema) reads as the empty map, never a `KeyError` — the
    module's degrade-safely posture on this axis.
    """
    return dict(report.get("custody", {}).get("summaries", {}).get("by_source", {}))


def report_at_risk_works(report: dict[str, Any]) -> dict[str, Any]:
    """The at-risk-works consolidation alarm from this pass's doctor audit (roadmap H263).

    `doctor`'s `custody.works` block names the works no representation safely holds —
    the consolidation-level analogue of the weakest-source `attention` flag (the H261
    `safely_held == False` set: every copy of the work degraded or moved, no unmoved
    full form anywhere). The scheduled worker's own `maintain` report distils only the
    *whole-library* `custody_snapshot` (which drops `works`), so an unattended log could
    not surface the at-risk works without re-running `doctor`. This threads the block the
    audit already produces into the report — the consolidation counterpart of
    `report_by_source`'s per-item per-source picture (H123).

    A pure read of the report `run_doctor` returns — **no new ledger read**, the block is
    already folded in the audit (`doctor._check_at_risk_works`). Surfaced
    **live-pass only** (like `report_by_source` H123, the `attention` flag, and
    `suggest_repairs` H40): derived fresh from this pass's audit, never recorded in the
    snapshot/log, so `--history`/`--trend` (which replay recorded snapshots) carry none.

    A work spans sources, so the audit computes the alarm **whole-library only** (the
    `doctor` `source is None` branch): an unscoped or `--fidelity` pass carries the
    computed block (`status: "ok"`), a `--source` pass carries the skipped default
    (`status: "skipped"` — a scoped item set fragments works). Honest absence: a report
    without the block (an empty library, or an older schema) reads the skipped default,
    never a `KeyError` — the module's degrade-safely posture on this axis.
    """
    return dict(
        report.get("custody", {}).get(
            "works",
            {"status": "skipped", "total": 0, "at_risk": 0, "most_at_risk": None},
        )
    )


# `weakest_source` — the distillation of `doctor`'s per-source breakdown to the
# one source worth flagging — now lives in `custody.py` beside the
# `custody_counts_by_source` map it reads, so the readable `export bundle`/`context`
# briefings can render the same `attention` flag without reaching into `maintain`
# (roadmap H159). It is imported above and re-exported here, so `maintain`'s report
# (H123) and `scrolls status` (H139) keep importing it from `maintain` unchanged.


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

    ``coverage_change`` (``{verified, total}`` net deltas, roadmap H115) and
    ``stale_change`` (``{enrichment, summaries}`` net deltas, roadmap H131) are
    *separate* axes the worker reads alongside the posture:

    - ``coverage_change`` — "is the library getting more covered?" (Δ``verified``
      up as bounded passes verify the never-checked tail; Δ``total`` up as new
      verifiable items are added).
    - ``stale_change`` — "is re-derivable enrichment debt accumulating?" (Δ the
      stale-classification count, H25, and Δ the stale-summary count, H29 — a
      rising figure means a ``classify --stale`` / ``kb --stale`` refresh is due).

    Both are **deliberately kept out of `posture`** (the H115 precedent, on the
    staleness axis too): coverage measures *how much has been checked* and
    staleness *how much enrichment is re-derivable*, neither *how faithfully we
    hold what we have*. A held category produced under a superseded ruleset is
    still held — rising staleness means a refresh is due, not that custody
    regressed — so rising coverage is not "improving" integrity, a steady-but-
    overdue library is not "regressing", and growing stale debt does not move the
    posture. Keeping `posture` integrity-only leaves the H46 rule unchanged;
    coverage and staleness are reported, never posture triggers.

    Honest absence (the H21/H29 posture): a window of fewer than two runs is not
    a trajectory — a single point has no direction — so it carries null deltas
    (including ``coverage_change``/``stale_change``) and `posture`
    ``insufficient-history``. A `score` that is ``None`` on either end (an
    uninitialized-library run) yields a null score `change`, never a fabricated
    zero; the drift, coverage, and staleness movement are still computed (absent
    counts read 0, so a pre-H115/pre-staleness-tracking endpoint reads 0).
    """
    n = len(runs)
    if n < 2:
        return {
            "runs": n,
            "since": None,
            "score": None,
            "drift_change": None,
            "coverage_change": None,
            "stale_change": None,
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

    def _stale(snap: dict[str, Any], key: str) -> int:
        return snap.get(key, 0)

    stale_change = {
        "enrichment": _stale(last_snap, "enrichment_stale")
        - _stale(first_snap, "enrichment_stale"),
        "summaries": _stale(last_snap, "summaries_stale")
        - _stale(first_snap, "summaries_stale"),
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
        "stale_change": stale_change,
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


def maintain_coverage(
    paths: LibraryPaths, source: str | None = None, fidelity: str | None = None
) -> dict[str, int]:
    """Recheck coverage from a standalone ledger read — the ``--no-recheck`` path.

    The recheck path folds its events into its own `latest_events` read; with no
    recheck there is no recheck, so this reads the ledger once to report the same
    ``{verified, total}`` coverage of the verifiable (hash-bearing) held set
    (roadmap H109). A missing store is the honest empty ``{verified: 0, total: 0}``
    — nothing held, nothing to verify. `source` scopes the verifiable set to one
    source's held items (roadmap H165), so an offline scoped pass reports <S>'s
    coverage, agreeing with the scoped audit's `custody.drift.coverage`.

    `fidelity` is the holdings-axis scope (roadmap H255): the offline twin of the
    `verify --fidelity` recheck (H252) — the verifiable set narrows to the held,
    hash-bearing items at one custody-fidelity tier (`get_fidelity`, the same
    primitive the read surfaces fold), so an offline ``--fidelity`` pass reports
    *that tier's* coverage. A tier holding no fingerprint (typically `reference`)
    is the honest empty ``{verified: 0, total: 0}``. The two scopes never combine
    (one scope axis per pass, enforced at the CLI), so only one filter ever bites.
    """
    if not paths.db_path.exists():
        return {"verified": 0, "total": 0}
    hash_bearing = [
        item for item in list_items(paths.db_path, source=source) if item.content_hash
    ]
    if fidelity is not None:
        hash_bearing = [item for item in hash_bearing if get_fidelity(item) == fidelity]
    return recheck_coverage(hash_bearing, latest_events(paths.db_path))


def skipped_recheck_report(
    paths: LibraryPaths, source: str | None = None, fidelity: str | None = None
) -> dict[str, Any]:
    """The ``recheck`` block of a pass that skipped the live edge (``--no-recheck``).

    The recheck is the one live network edge (behind the `live_recapture` seam);
    a ``--no-recheck`` pass — and every MCP pass (roadmap H196), which must not
    trigger implicit re-captures — skips it, recording no new drift events. The
    block is the honest skipped shape: zeroed verdict counts, ``scope``/``since``
    null (no window was used), and the coverage figure still read from the current
    ledger (`maintain_coverage`) so even an offline pass reports "N of M verifiable
    items carry a verdict". `source`/`fidelity` scope that coverage read to one
    source's held items (H165) or one custody-fidelity tier (H255) respectively.
    """
    return {
        "skipped": True, "scope": None, "since": None, "checked": 0,
        "unchanged": 0, "drifted": 0, "rotted": 0, "error": 0,
        "coverage": maintain_coverage(paths, source, fidelity),
    }


def assemble_report(
    paths: LibraryPaths,
    *,
    recheck_report: dict[str, Any],
    previous: dict[str, Any] | None,
    source: str | None,
    fidelity: str | None = None,
    now: str,
) -> dict[str, Any]:
    """Build a maintenance-pass report from a recheck result (roadmap H34/H196).

    The shared composition both the CLI `scrolls maintain` command and the MCP
    `run_maintenance` act run, after the caller has performed the *recheck* step
    (the one live edge — the CLI may re-capture through the `cli.live_recapture`
    seam; an MCP pass passes a `skipped_recheck_report`). Given that recheck
    result, this performs the deterministic, network-free rest of the pass:

    1. *regenerate* views (`compile_kb` — never an LLM re-synthesis),
    2. *audit* the post-maintenance state once (`run_doctor`, read-only — maintain
       never ``--fix``es),
    3. compute the **custody delta** vs the last recorded snapshot and, for an
       *unscoped* whole-library pass, *record* this run's snapshot (the next delta
       baseline) and *append* it to the trend log,
    4. assemble the report: the recheck counts, the compiled-view counts, the
       distilled `custody` snapshot + one-line `headline`, the live-pass-only
       per-source breakdowns (`by_source`/`enrichment_by_source`/`summary_by_source`),
       the single weakest-source `attention` flag, the consolidation-level
       `at_risk_works` alarm (roadmap H263, the work-level counterpart of `attention`),
       the `delta`, the structural `issues` count, and the `suggested` on-request
       repair commands.

    **The two scope axes are non-persisting focused triage** — a pass scoped on
    *either* axis records no snapshot/log baseline, so its `delta` is the honest
    ``null`` (custody-vision §2.4 / ADR 0082); the *unscoped* whole-library pass
    owns the cross-run trend. The axes differ in *what* the scope narrows:

    - ``source`` (H165): the recheck (caller-side) *and* the audit narrow to <S>
      — `run_doctor(source=)` scopes via `list_items(source=)`, so every reported
      block is the one-source view and `by_source` collapses to ``{S: …}``. The
      snapshot it would record is a one-source slice (the stored snapshot drops
      `by_source`), so recording it would clobber the single whole-library baseline.
    - ``fidelity`` (H255): only the *recheck* narrows to the tier (caller-side, the
      `verify --fidelity` held hash-bearing subset); the **audit/regenerate stay
      whole-library** — a fidelity tier spans sources, so `run_doctor`'s source
      semantics (`by_source`-singleton collapse, orphan/FTS skip) don't apply, and
      scoping the audit is a separate, larger change deferred unless the recheck-only
      shape proves insufficient. The whole-library snapshot it *could* record is
      correct, but a partial-recheck pass is a focused triage, not a trend
      checkpoint, so it is still non-persisting (null delta) — a fidelity pass must
      not stamp the trend as if it had rechecked the whole library.

    Report-only and idempotent: it regenerates `library/` views and records the
    snapshot/log bookkeeping, but never repairs index rows, reclassifies, or
    re-summarizes — `doctor --fix` / `classify --stale` / `kb --stale` stay the
    explicit, on-request mutations.
    """
    # 1. REGENERATE views from canonical rows (views are regenerable). Whole-library
    #    even under any scope: a deterministic global recompile, not a scoped one.
    compiled = compile_kb(paths)

    # 2. AUDIT the post-maintenance state, read-only. `source` scopes the whole
    #    audit to <S> via the shipped pre-filter (roadmap H162); a `fidelity` scope
    #    leaves the audit whole-library (the recheck alone is scoped, H255).
    report = run_doctor(paths, source=source)
    current = custody_snapshot(report)

    # 3. DELTA vs the last recorded snapshot, then record this run's — but only for
    #    an *unscoped* pass. A pass scoped on either axis is a non-persisting focused
    #    triage: it keeps no baseline (a source pass's snapshot is a one-source slice;
    #    a fidelity pass rechecked only one tier), so its delta is honestly `null`.
    if source is None and fidelity is None:
        delta = compute_delta(previous, current)
        save_snapshot(snapshot_path(paths), {**current, "recorded_at": now})
        append_log_entry(
            log_path(paths),
            {"recorded_at": now, "snapshot": current, "delta": delta},
        )
    else:
        delta = None

    by_source = report_by_source(report)
    return {
        "recorded_at": now,
        "source": source,
        "fidelity": fidelity,
        "recheck": recheck_report,
        "compiled": dataclasses.asdict(compiled),
        "custody": current,
        "headline": snapshot_headline(current),
        "by_source": by_source,
        "attention": weakest_source(by_source),
        # the consolidation-level custody alarm (roadmap H263): the works no
        # representation safely holds, the work-level counterpart of `attention`.
        # Whole-library only (a work spans sources), so a `--source` pass carries
        # the skipped default; live-pass only, like `attention`/`by_source`.
        "at_risk_works": report_at_risk_works(report),
        "enrichment_by_source": report_enrichment_by_source(report),
        "summary_by_source": report_summary_by_source(report),
        "delta": delta,
        "issues": report["issues"],
        "suggested": suggest_repairs(report, source=source),
    }
