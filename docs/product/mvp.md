# Scrolls MVP — near-term coherent scope

**Status:** Near-term build scope for `work/scrolls-dev`. Pairs with
`docs/product/prd.md` (direction) and `docs/agents/autonomous-roadmap.md`
(scheduling). This MVP is the smallest set of vertical slices that makes the
custody promise *real, measurable, and agent-runnable* — and that absorbs the
two obsidian-second-brain adoptions without scope creep.

## MVP thesis

An agent can, unattended, **hold a topic, prove custody of it, detect what it
has lost, and take it with it** — and every derived view it reads is
trustworthy: scope-honest, regenerable, and non-destructive of annotations.

Most of the custody spine already exists on this branch: fidelity tiers (ADR
0100), works membership on browse surfaces (ADR 0101), the custody integrity
audit (ADR 0097), drift detection (ADR 0098), and the lossless round-trip
invariant (ADR 0099). The MVP closes the remaining gaps and folds in the
obsidian adoptions.

## In scope (the coherent MVP slices)

### M1 — Refresh-safe generated artifacts (obsidian adoption #1)
- Compiled `library/` pages and generated `agents/` instruction files gain a
  generated-vs-user boundary (sentinel-fenced), so re-running the KB compiler
  (`src/scrolls/kb.py`) and `agent install` (`src/scrolls/agents.py`) replaces
  only the generated region and preserves any human/agent annotation.
- Decision-grade: this is ADR 0102.
- Done when: a `@user` block survives a re-compile; tests in `tests/test_kb.py`
  (and the agent-install tests) prove non-destructive regeneration; the
  contract is documented in `docs/library-format.md`.

### M2 — Anti-fabrication / search-completeness invariant (obsidian adoption #2)
- The browse + audit surfaces (`search`, `context`, `related`, `works`,
  `doctor`) make scope explicit and never imply unverified completeness;
  "nothing found" is distinguishable from "not checked."
- Done when: the contract is stated in `docs/cli.md` and `docs/library-format.md`
  and pinned by tests (a result over a filtered slice does not claim
  library-wide completeness; an empty result is honest about scope).

### M3 — Progressive context budgets
- `scrolls context` becomes a budgeted boot sequence: index/identity first,
  deep bodies on demand, building on the same-work collapse already shipped.
- Done when: a budget flag bounds bundle size predictably and tests pin the
  tiering.

### M4 — Shareable custody bundle (briefing)
- A scoped, self-contained Markdown/HTML bundle that carries provenance +
  fidelity per item and re-imports losslessly (complements `export items`,
  ADR 0082).
- Done when: export→import of a bundle round-trips and a fixture proves the
  bundle is self-describing offline.

### M5 — Dogfood workflow proof
- One documented, agent-runnable end-to-end flow exercising M1–M4:
  *hold a topic → prove custody (doctor score) → detect loss (recheck) → take it
  with me (bundle export → reimport)*.
- Done when: the flow runs offline against fixtures and is referenced from the
  vision's dogfood section.

## Explicitly out of MVP

- Any self-mutating ingestion or auto-overwriting reconciliation.
- Productivity surfaces (calendar/tasks/people/meetings/kanban).
- Paid live-research/discovery integrations.
- New source adapters (no new custody shape on offer right now).
- A dedicated bi-temporal timeline store — drift events (ADR 0098) cover the
  near-term need; revisit only when an agent demonstrably needs more than the
  event record.

## Sequencing and dependencies

```text
M1 (refresh-safe regen) ──┐
M2 (completeness contract)├─▶ M5 (dogfood proof)
M3 (context budgets) ─────┤
M4 (custody bundle) ──────┘
```

M1 and M2 are independent and are the two obsidian-derived, decision-grade
slices — start there. M3 and M4 build on already-shipped custody surfaces. M5
ties them into a single unattended proof. Detailed hour/day/week scheduling
lives in `docs/agents/autonomous-roadmap.md`.

## Verification bar (every slice)

- `uv run pytest` green, with new fixture-backed tests for the slice.
- Concrete command output captured where a CLI/MCP contract changed.
- The relevant contract doc updated in the same commit (`docs/architecture.md`,
  `docs/cli.md`, or `docs/library-format.md`), per `docs/agents/domain.md`.
- An ADR when the decision is consequential (M1 → ADR 0102).
