# Plans — 2026-07-22

**Question this file answers:** with the codebase and goals reconciled
(`reconciliation.md`), what are the next goals/objectives — as logical items,
detached from timelines — and what is a reasonable 1/3/7-day plan?

*Agent-drafted 2026-07-26, pending Elijah's review; derived strictly from the
`docs/agents/autonomous-roadmap.md` queue and the vision's "Open capability
notes". The roadmap remains operationally authoritative for the hourly worker
until a human edits this file.*

## Next objectives (logical items, no timelines)

1. **Finish the convergence-guard matrix** — close the remaining
   cross-surface convergence/determinism gaps in the H-series direction until
   every custody fact provably reads identically across CLI ≡ MCP ≡ compiled
   `library/` ≡ bundles ≡ context.
2. **Threaded / comment rendering as a custody shape** — code-host threads,
   discussions, and comment trees as first-class scrolls (vision "Open
   capability notes"; ADR 0093 is the groundwork).
3. **Cross-source evidence clustering beyond same-work collapse** — the
   still-open last30days pattern
   (`docs/inspiration/last30days-inspiration.md`).
4. **Typed graph edges** — `cites` / `mentions` beyond the shipped same-work
   relations.
5. **Richer enrichment** — parent-POM inheritance for Maven; full text where
   available.
6. **Roadmap snapshot sync** — refresh the roadmap's status snapshot against
   the latest check-in report (a maintenance-rule pass, not a feature).

## 1-day plan

- Land the 2026-07-26 docs-consolidation branch onto `work/scrolls-dev`
  (user-side merge; the repo hook blocks agent pushes).
- Run the roadmap maintenance rule: refresh its status snapshot from
  `report.md`, requeue ~6 concrete slices against the PRD capabilities.

## 3-day plan

- Ship the next two or three queued convergence guards (one coherent,
  test-backed slice per run), keeping the suite green.
- Write the design note (grill-checked) for threaded/comment rendering as a
  custody shape — what identity, fidelity boundary, and thread structure it
  adds; ADR if decision-grade.

## 7-day plan

- A threaded/comment-rendering vertical slice: design → fixture-backed
  implementation → contract-doc updates in the same commit.
- An evidence-clustering design spike grounded in the existing works/related
  infrastructure (report-only and custody-safe: clusters are views, never
  merges of raw).
- One full scheduled-maintenance dogfood pass (`scrolls maintain`) against a
  real library, with captured output feeding the next check-in report.
