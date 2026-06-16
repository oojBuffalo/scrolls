# 0102: Obsidian Second Brain as an inspiration source; refresh-safe generated artifacts

Date: 2026-06-16

Status: accepted

## Context

Scrolls already names two inspiration sources — Field Theory CLI and
`mvanhorn/last30days-skill` (`docs/agents/last30days-inspiration.md`, IDEAS.md
§0). A third, [`eugeniughelbur/obsidian-second-brain`](https://github.com/eugeniughelbur/obsidian-second-brain),
is a mature agent-facing knowledge system worth evaluating: 45 commands, AI-first
note rules, scheduled maintenance agents, vendor-neutral export, and a
codebase-architect command that writes *maintained* docs.

But its headline philosophy is the inverse of Scrolls'. obsidian-second-brain is
*"a vault that rewrites itself"*: each ingested source **mutates existing pages**
in place, and reconciliation **auto-resolves contradictions by overwriting** the
losing claim. Scrolls' operative north star (`docs/custody-vision.md`) is the
opposite — *raw is sacred, every other surface is a regenerable view* (§2), and
*drift is a recorded custody event, never an overwrite* (§4). Adopting
obsidian's patterns naively would quietly erode the one promise that
differentiates Scrolls.

A future agent reading the repo will find three inspiration sources and needs to
know **why we took obsidian's mechanisms but rejected its central idea**, and
which concrete contract that produced. That is the surprising-without-context
part this record exists to answer.

## Decision

**Adopt obsidian-second-brain as an inspiration source under a strict
mechanism-not-philosophy posture.** The full adopt/adapt/reject mapping lives in
`docs/agents/obsidian-second-brain-inspiration.md`; the product consequences are
in `docs/product/prd.md` and `docs/product/mvp.md`; the scheduling is in
`docs/agents/autonomous-roadmap.md`. The load-bearing rules:

1. **Reject the self-mutating vault.** Scrolls never overwrites a captured
   record on ingest and never silently resolves a contradiction by rewriting the
   loser. Detection of conflict/drift is adopted; resolution stays custody-safe
   (surface an event for review).

2. **Adopt refresh-safe generated artifacts (the headline near-term contract).**
   The obsidian-architect pattern of sentinel-fenced regeneration
   (`@generated` / `@user` blocks; a refresh replaces only generated content) is
   the right *mechanism* for Scrolls' "views are regenerable" rule. The compiled
   `library/` pages (`src/scrolls/kb.py`) and generated `agents/` instruction
   files (`src/scrolls/agents.py`) will carry a generated-vs-user boundary so a
   re-compile / `agent install` replaces only the generated region and preserves
   any human or agent annotation. Today a re-compile overwrites the whole file;
   this makes regeneration non-destructive of annotations while keeping the
   generated region authoritative. This is queued as MVP slice M1.

3. **Adopt anti-fabrication / search-completeness as a tested agent-contract
   invariant.** Browse and audit surfaces must be scope-honest and
   completeness-honest; "nothing found" is distinguishable from "not checked."
   Queued as MVP slice M2.

4. **Adopt the rest as reinforcement, not new direction:** progressive context
   budgets (builds on the shipped same-work context collapse), portable custody
   bundles (complements `export items`, ADR 0082), bi-temporal framing of drift
   events (captured-at vs source-changed-at — concept only, storage deferred),
   and the AI-first preamble discipline on generated views.

5. **Reject as out of scope** (a custody library, not a planner or discovery
   engine, per `docs/vision.md`): productivity surfaces (calendar/tasks/people/
   meetings/kanban), the paid live-research toolkit, presets/roles, the
   four-CLI build matrix, and the discovery-oriented thinking tools.

## Consequences

- This commit makes the decision real in the operating docs: a new inspiration
  doc, a PRD and MVP under `docs/product/`, an autonomous roadmap, and updates
  to `CLAUDE.md`, `IDEAS.md`, `docs/agents/vision.md`, and
  `docs/agents/domain.md` so future runs see the source and its posture. No
  application code changes in this slice.
- The refresh-safe-artifacts contract (rule 2) is the committed *direction*; its
  implementation is MVP slice M1, scheduled first on the autonomous roadmap. The
  contract will be specified in `docs/library-format.md` (whose pinned examples
  are guarded by `tests/test_docs.py`) when the code lands.
- Future autonomous runs prioritize the two custody-deepening adoptions (M1, M2)
  over breadth, consistent with the existing no-new-adapters-without-a-new-
  custody-shape mandate (custody-vision §2.7).
- The development process switches from `/grill-me` to the docs-aware
  `/grill-me-docs` (installed as `grill-with-docs`), so plans are stress-tested
  against this repo's documented decisions and terminology before implementation.
- Risk acknowledged: the repo now has several vision-adjacent docs. Mitigation:
  this ADR and the PRD/MVP defer to `docs/custody-vision.md` as authority and do
  not fork the vision; the inspiration doc is explicitly subordinate.
