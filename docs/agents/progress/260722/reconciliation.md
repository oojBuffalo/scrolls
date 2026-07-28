# Reconciliation — 2026-07-22

**Question this file answers:** did development match the desired goals/plans?
Deviations and corrections, judged against `docs/vision.md`,
`docs/product/prd.md`, `docs/product/mvp.md`, and
`docs/agents/autonomous-roadmap.md`, using `report.md` alongside as the facts.

*Agent-drafted 2026-07-26 (retroactive to the 2026-07-22 report), pending
Elijah's review; realigned the same day after the automation/ops state from
the autonomous-machine session (the 2026-07-20 reassessment) was folded in.*

Note: this file is a **dev check-in artifact** — distinct from
`docs/conflicts.md` (named reconciliation.md until 2026-07-27), which is the
custody-conflict *design doc* for the reconcile feature.

## Verdict

The *content* of development stayed on-vision — but the *process* did not.
Automated development was accidentally re-enabled after the 2026-06-25
check-in (`../260625/`) and ran 77 slices (H344–H425) with no steering
checkpoint, completing and then overshooting the June-25 plan. Since
2026-07-05 the project has been operationally stalled: crons paused, the CI
checkpoint unpushed, two idle weeks, no dogfood evidence. The documentation
surface had also drifted (corrected 2026-07-26).

## On-plan

- **MVP M1–M5 shipped as scoped** (`docs/product/mvp.md`), each with the
  required tests/docs, and tied together by the offline dogfood proof
  (`docs/dogfood.md`).
- **Post-MVP custody themes all landed on-vision**: per-item/source/scope
  custody surfaces, work-level custody consolidation, conflict-on-import
  (ADR 0104–0106), archive recovery + integrity alarm, explainable
  ranking/relatedness, content-identity custody, and the posture verdict
  (ADR 0107). Each maps to a PRD capability.
- **The forward-hardening phase (H363–H425)** — cross-surface convergence and
  determinism guards — enacts vision §2.6 (the agent contract is the
  integrity boundary) and §2.8 (integrity is verified, not asserted).
- **The adapter moratorium held** (vision §2.7): no new source adapters;
  breadth stopped being the unit of progress, exactly as directed.

## Deviations and corrections

1. **Automation ran without authorization or steering.** The 2026-06-25
   check-in expected the content-identity tail (H344–H348) and then a stop at
   the assessment/recommendation gate. Instead the worker blew through the
   tail, the posture theme, and the entire contract-consolidation queue —
   and kept going even after both crons were paused around 2026-06-27/28,
   because automated development had been **accidentally re-enabled** (the
   2026-07-01→05 tail, H420–H425, landed in that window). The output is real
   and green, but 77 slices landed with no human checkpoint, and the June-25
   direction went stale without anyone recording it.
   **Corrections:** (applied, 2026-07-26) this check-in structure plus the
   backfilled `../260625/` record; (standing) both crons stay paused — the
   hourly worker is not restarted on the guard-cell prompt (see `plans.md`).
2. **Over-proving past diminishing returns.** The June-25 direction was
   surface-closure → stewardship gate → enrichment. The overrun instead
   produced ~30 further completeness-asserted guard matrices (H397–H425).
   Valuable, on-vision — and past the knee: the roadmap itself names an
   assessment gate before any further guard-cell family, and the 2026-07-20
   reassessment calls more H426-style matrices the wrong default.
   **Correction:** the next slice must be evidence-driven (dogfood friction),
   not another invariant family — see `plans.md`.
3. **Release/ops readiness stalled.** The CI + docs pivot was committed on
   the autonomous machine 2026-07-07 (`401ad34`) but never pushed, so GitHub
   has never run the workflow — local "we have CI" is not remote
   verification — and the repo then sat idle for ~2 weeks.
   **Correction:** push + verify remote CI green is the first item on the
   1-day plan.
4. **Doc coherence lagged code.** While the code stayed on-vision, the doc
   surface drifted: two superseded vision docs still self-declared as the
   north star, `IDEAS.md` and `CLAUDE.md` pointed readers at the wrong
   authority, inspiration material was restated across many files, and the
   priority lists copied into `CLAUDE.md`/`AGENTS.md` predated MVP
   completion. Class: documentation drift, not implementation drift.
   **Correction (applied, 2026-07-26):** the docs consolidation — inspiration
   material unified under `docs/inspiration/`, the vision docs merged into a
   single `docs/vision.md`, scattered references reduced to pointers, and
   this check-in structure created.
5. **No product-direction correction needed.** Nothing shipped contradicts
   the custody vision; the non-goals (no discovery engine, no self-mutation,
   no new adapters) were respected. The correction is to *process and phase*
   (steering, ops, evidence-from-use), not to the product direction.
