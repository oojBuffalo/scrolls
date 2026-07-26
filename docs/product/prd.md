# Scrolls PRD — product direction

*Amended: 2026-07-26 — vision references retargeted to the merged
`docs/vision.md`; the principles restatement compressed to a pointer plus the
two genuine deltas; inspiration references now point at `docs/inspiration/`.*

**Status:** Living product doc for the `work/scrolls-dev` agent trunk.
**Authority:** Subordinate to the vision — `docs/vision.md` is the operative
north star. This PRD does not redefine the vision — it states *what we are
building next and why*, with the obsidian-second-brain adoptions
(`docs/inspiration/obsidian-second-brain-inspiration.md`) folded in.

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

## Product principles

The build rules **are** the vision's principles — `docs/vision.md` §2; they
are not restated here. Two adopted deltas extend them (both shipped;
the mappings live in `docs/inspiration/obsidian-second-brain-inspiration.md`):

1. **Regeneration is sentinel-fenced** — rebuilding any derived surface never
   destroys human annotations (extends §2.2; ADR 0102).
2. **Agents must be able to trust completeness** — anti-fabrication +
   search-completeness are a tested contract invariant: a result states its
   scope, and "nothing found" is distinguishable from "not checked" (extends
   §2.6; MVP M2).

## Capabilities (priority order)

These extend the prioritized list in `docs/vision.md` §3 with the two adopted
additions marked **[OSB]** (adopted from obsidian-second-brain —
`docs/inspiration/obsidian-second-brain-inspiration.md`).

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

- **Vision-doc sprawl.** *Resolved 2026-07-26:* the vision docs were merged
  into the single `docs/vision.md`; this PRD and the MVP cite it as authority
  and do not fork it.
- **Adopting the self-mutating framing by accident.** Mitigation:
  `docs/inspiration/obsidian-second-brain-inspiration.md` pins the one
  rejected idea (self-mutation) up front; every adoption is the *mechanism*,
  not the philosophy.
- **Live-source flakiness** for drift detection. Mitigation: the deterministic
  custody audit lands first and is the home drift reports write into.

See `docs/product/mvp.md` for the near-term coherent scope and
`docs/agents/autonomous-roadmap.md` for the scheduled sequencing.
