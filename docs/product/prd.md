# Scrolls PRD — inspiration-backed product direction

**Status:** Living product doc for the `work/scrolls-dev` agent trunk.
**Authority:** Subordinate to the vision. `docs/custody-vision.md` is the
operative north star; `docs/vision.md` and `docs/agents/vision.md` are the
earlier syntheses it sharpens. This PRD does not redefine the vision — it states
*what we are building next and why*, with the obsidian-second-brain inspiration
(`docs/agents/obsidian-second-brain-inspiration.md`) folded in.

## Problem

People save internet artifacts — papers, repos, videos, threads, PDFs,
bookmarks — across dozens of tools, then lose them: the link rots, the content
drifts, the tool dies, or the artifact is simply un-findable six months later.
Existing "second brain" tools optimize for *capture and re-synthesis* and mutate
their own store as they go, so the user can no longer prove what they originally
saved. Agents, meanwhile, have no trustworthy local corpus to reason over.

## What Scrolls is

A **local-first custody system** for saved artifacts. It holds a faithful copy
of what you saved, proves what it was at capture time, detects when the live
source rots or drifts, degrades honestly when full fidelity is impossible, and
lets you walk away with everything losslessly at any time. The library is a
custody ledger; agents are its primary readers, trusting it because nothing in
it is a black box.

This is deliberately **not** a planner, a discovery engine, or a self-rewriting
notebook (see the Non-goals).

## Who it is for

1. **Agents** (Claude Code, Codex, Hermes, MCP clients) — the primary users.
   They ingest, search, cluster, audit, export, and repair without a human in
   the loop.
2. **A single owner or small team** who deliberately keeps artifacts and wants
   durable, portable, provable custody of them.

## Product principles (from the vision, restated as build rules)

1. **Custody over capture.** Stewardship over time is the product; ingestion is
   the cheap part.
2. **Raw is sacred; views are regenerable.** Every derived surface
   (`library/`, facets, concept pages, bundles, `agents/` files) must rebuild
   from raw + index. *New from obsidian:* regeneration is sentinel-fenced so it
   never destroys human annotations (ADR 0102).
3. **Fidelity and provenance travel with every result.** Search ≡ list ≡ MCP ≡
   facets. An agent always sees how much of an item we hold and where it came
   from (ADR 0100, ADR 0101).
4. **Drift is a recorded event, never an overwrite.** *Reinforced by obsidian's
   bi-temporal facts:* captured-at vs source-changed-at.
5. **The library is a way-station, not a sink.** Lossless export/import is
   load-bearing infrastructure (ADR 0082).
6. **Agents must be able to trust completeness.** *New from obsidian:*
   anti-fabrication + search-completeness are a tested contract invariant — a
   result states its scope, and "nothing found" is distinguishable from "not
   checked."
7. **Adapters are commodity; custody guarantees are the moat.** No new adapter
   unless it introduces a new custody shape.

## Capabilities (priority order)

These extend the prioritized list in `docs/custody-vision.md` §3 with the two
obsidian-derived additions marked **[OSB]**.

1. **Custody integrity audit** — `scrolls doctor` as a full custody report with
   a per-library custody score (network-free, deterministic).
2. **Explicit fidelity tiers** — full / partial / reference, surfaced on every
   browse surface.
3. **Drift / rot detection on re-fetch** — custody events, never overwrites.
4. **Lossless round-trip as a tested invariant** — export→import→export stable.
5. **Canonical works as custody consolidation** — many representations held as
   one work.
6. **[OSB] Refresh-safe generated artifacts** — sentinel-fenced regeneration of
   `library/` and `agents/` files so hand annotations survive re-compile.
7. **[OSB] Anti-fabrication / search-completeness invariant** — scope-honest,
   completeness-honest results across `search` / `context` / `related` /
   `works` / `doctor`.
8. **Provenance-complete, re-derivable enrichment** — classification and
   summaries record inputs + method and regenerate deterministically.
9. **Shareable, self-contained custody bundles** — portable Markdown/HTML
   briefings carrying provenance + fidelity, re-importable losslessly.
10. **Progressive context budgets** — `scrolls context` as a budgeted boot
    sequence (identity/index first, deep bodies on demand).
11. **Dogfood workflows as the success metric** — every capability has an
    agent-runnable end-to-end flow.

## Non-goals (explicit)

- A self-mutating store that overwrites what you saved.
- Calendar / tasks / people / meetings / kanban — Scrolls is not a planner.
- A paid live-research / discovery toolkit (X, Perplexity, Grok, NotebookLM).
- Default cloud sync, real-time streaming ingestion, a visual editor.
- New one-off registry adapters that add breadth without a new custody shape.

## Success metrics

- **Custody score** trends up and is defensible from `scrolls doctor --json`.
- **Round-trip invariant** holds in CI (export→import→export byte-stable for
  model-complete fields).
- **Surface parity**: search, list, MCP, and facets return identical
  fidelity + works membership for the same item (no drift).
- **Regeneration safety**: re-compiling `library/` preserves any `@user` block.
- **Completeness honesty**: browse/audit results never imply unverified
  completeness (covered by tests).
- **Dogfood**: an agent runs *hold a topic → prove custody → detect loss → take
  it with me* unattended.

## Risks and how we handle them

- **Vision-doc sprawl** (now several vision-ish docs). Mitigation: this PRD and
  the MVP cite the existing custody vision as authority and do not fork it.
- **Adopting obsidian's framing by accident.** Mitigation: the inspiration doc
  pins the one rejected idea (self-mutation) up front; every adoption is the
  *mechanism*, not the philosophy.
- **Live-source flakiness** for drift detection. Mitigation: the deterministic
  custody audit lands first and is the home drift reports write into.

See `docs/product/mvp.md` for the near-term coherent scope and
`docs/agents/autonomous-roadmap.md` for the scheduled sequencing.
