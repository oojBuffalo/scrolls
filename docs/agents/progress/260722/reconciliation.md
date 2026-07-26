# Reconciliation — 2026-07-22

**Question this file answers:** did development match the desired goals/plans?
Deviations and corrections, judged against `docs/vision.md`,
`docs/product/prd.md`, `docs/product/mvp.md`, and
`docs/agents/autonomous-roadmap.md`, using `report.md` alongside as the facts.

*Agent-drafted 2026-07-26 (retroactive to the 2026-07-22 report), pending
Elijah's review.*

Note: this file is a **dev check-in artifact** — distinct from
`docs/reconciliation.md`, which is the custody-conflict *design doc* for the
reconcile feature. Same word, different job.

## Verdict

Development matches the documented direction. The code did what the plans
said; the *documentation surface* is where drift accumulated.

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

1. **Doc coherence lagged code.** While the code stayed on-vision, the doc
   surface drifted: two superseded vision docs still self-declared as the
   north star, `IDEAS.md` and `CLAUDE.md` pointed readers at the wrong
   authority, inspiration material was restated across many files, and the
   priority lists copied into `CLAUDE.md`/`AGENTS.md` predated MVP
   completion. Class: documentation drift, not implementation drift.
   **Correction (applied, 2026-07-26):** the docs consolidation — inspiration
   material unified under `docs/inspiration/`, the vision docs merged into a
   single `docs/vision.md`, scattered references reduced to pointers, and
   this check-in structure created.
2. **Hardening ran long without a steering checkpoint.** H363–H425 is ~60
   slices of (valuable, on-vision) convergence guards, but no durable
   check-in artifact existed between the 2026-06-25 roadmap snapshot and this
   one, so the roadmap's own status section drifted from the shipped state.
   **Correction (proposed):** the `docs/agents/progress/<YYMMDD>/` convention
   gives human check-ins a durable home (report = facts, reconciliation =
   this judgment, plans = steering); the roadmap's snapshot should be synced
   against the latest report during its next maintenance pass.
3. **No product-direction correction needed.** Nothing shipped contradicts
   the custody vision; the non-goals (no discovery engine, no self-mutation,
   no new adapters) were respected.
