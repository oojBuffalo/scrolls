# Inspiration & lineage

*Amended: 2026-07-26 — created as the single home for Scrolls' inspiration
material, consolidating notes previously scattered across `IDEAS.md`,
`CLAUDE.md`, `AGENTS.md`, and the earlier vision syntheses.*

This directory is the canonical record of where Scrolls' ideas came from and
what was adopted, adapted, or rejected. Everything else in the repo should
*point* here rather than restate it. The ADRs remain the decision records;
this directory carries the narrative.

## Lineage at a glance

| Inspiration | What it is | What it contributed | Reference checkout | Key ADRs |
| --- | --- | --- | --- | --- |
| [Field Theory CLI](fieldtheory-cli-inspiration.md) | The original X-bookmarks pipeline — the project's spark | The 6-stage pipeline spirit; raw-record preservation; `import`/`sync`/`add` verbs; rules-first classification; Markdown-first durable artifacts | none — lineage travels via `scrolls import fieldtheory` | 0009, 0001 |
| [last30days-skill](last30days-inspiration.md) | `mvanhorn/last30days-skill` — an agent-facing research skill | The product bar: agent contract + engine separation; fanout with graceful degradation; clustering/dedupe; explainable ranking; shareable artifacts; fixtures/evals; dogfood workflows | `/Users/claw/.hermes/gh-repos/last30days-skill` | 0093 |
| [obsidian-second-brain](obsidian-second-brain-inspiration.md) | `eugeniughelbur/obsidian-second-brain` — a self-mutating Obsidian vault system | Mechanisms only: sentinel-fenced regeneration; anti-fabrication/completeness contract; progressive context budgets; portable bundles; bi-temporal drift framing; scheduled custody maintenance. Its self-mutating-vault philosophy is **rejected**. | `/Users/claw/.hermes/gh-repos/obsidian-second-brain` | 0102, 0103 |

## Ground rules (all inspirations)

- **Inspiration only.** Never vendored code, secrets, or implementation
  details copied blindly.
- **Mechanisms, not philosophy.** Adopt the mechanism underneath a pattern
  only when it survives Scrolls' custody contract; reject anything that
  violates *raw is sacred*, *drift is an event, never an overwrite*, or
  *views are regenerable*.
- **Adopt/adapt/reject, explicitly.** Each inspiration doc records the full
  mapping; consequential adoptions get an ADR (the ADR 0102 precedent).
- **References stay pointer-sized.** Other docs cite one of the three docs
  here instead of restating pattern lists.

## A minor stylistic influence: the Karpathy wiki

The compiled `library/` (interlinked concept/source/category pages) was
originally framed as "the KB compiler should feel like Karpathy wiki"
(IDEAS.md §9). The custody vision deliberately bounded that influence:
concept pages and the compiled `library/` are *views* — valuable, always
regenerable, never load-bearing for custody. It is a styling note, not a
peer inspiration, so it has no dedicated doc.

## Adding a new inspiration source

Give it its own `<name>-inspiration.md` here (origin, adopt/adapt/reject,
pointers), add a row to the table above, record the decision-grade parts in
an ADR, and keep every reference elsewhere a pointer.

## ADR status of this consolidation

The 2026-07-26 docs consolidation (this directory plus the single merged
`docs/vision.md`) added no new ADR. The ADRs that cited the pre-consolidation
paths (0093, 0097, 0098, 0099, 0102, 0103, and the ADR index) were instead
amended in place — dated path updates only, decision content unchanged — and
the old paths were removed rather than left as redirect stubs.
