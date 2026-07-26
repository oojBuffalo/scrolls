# Progress Report — 2026-06-25

**Date:** 2026-06-25
**Branch:** `work/scrolls-dev` (agent trunk) — HEAD `a7af87e` (H343)
**Slice series:** through **H343**
**Suite:** ~4043 tests passing (per the autonomous-machine session notes)

*Reconstructed: 2026-07-26 — this check-in happened (the roadmap's
"Status snapshot — 2026-06-25" and its same-day re-compaction, commit
`34a37b1`, are its trace) but never got a durable artifact under
`docs/agents/progress/`. This directory backfills it from the roadmap
snapshot, git history, and the autonomous-machine session notes. Facts below
are as of 2026-06-25.*

## Where development stood

- **MVP M1–M5 complete** (refresh-safe regeneration, completeness invariant,
  `context --budget` tiers, the custody bundle, and the offline dogfood proof
  — `docs/dogfood.md`).
- **Post-MVP custody themes complete** through explainable ranking &
  relatedness (H312–H324): per-item/source/scope custody surfaces, work-level
  consolidation (H261–H271), conflict-on-import (ADR 0104–0106), and archive
  recovery + the un-launderable integrity alarm (H280–H321).
- **In flight: the content-identity / near-duplicate custody theme** —
  byte-identical holdings under different ids, report-only, never an
  auto-merge. H325–H343 shipped; the surface-closure tail **H344–H348** was
  the open work.
- `docs/agents/autonomous-roadmap.md` was re-compacted this day per its
  maintenance rule §6 (the file had re-accreted to ~637 KB).

## Operational state

- The hourly autonomous worker was **live**, following the roadmap queue.
- Verification was local-only (`uv run pytest`); no CI existed on GitHub.

The direction set at this check-in is `plans.md` alongside (kept as the
historical record). How development actually unfolded afterwards is recorded
in the next check-in, `../260722/`.
