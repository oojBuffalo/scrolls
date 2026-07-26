# Obsidian Second Brain inspiration for Scrolls

*Amended: 2026-07-26 — moved here from
`docs/agents/obsidian-second-brain-inspiration.md` as part of consolidating all
inspiration material under `docs/inspiration/`; shipped-status notes added and
one mis-attributed quotation paraphrased.*

The Scrolls agent trunk takes a third explicit inspiration source, alongside
[Field Theory CLI](fieldtheory-cli-inspiration.md) and
[`mvanhorn/last30days-skill`](last30days-inspiration.md):
[`eugeniughelbur/obsidian-second-brain`](https://github.com/eugeniughelbur/obsidian-second-brain)
(reference checkout: `/Users/claw/.hermes/gh-repos/obsidian-second-brain`).

It is used as inspiration only. We adopt **mechanisms and disciplines**, never
vendored code, secrets, or its product framing wholesale.

## The one decision that frames everything else

obsidian-second-brain's headline is *"a vault that rewrites itself"*: each
ingested source **mutates existing pages** in place, and `/obsidian-reconcile`
**auto-resolves contradictions by overwriting** the losing claim. That is the
exact inverse of Scrolls' custody contract (`docs/custody-vision.md`):

> Raw is sacred; everything else is derivable. … No view may hold information
> that cannot be regenerated. (§2)
>
> Drift and rot are surfaced, never hidden. A re-fetch that disagrees with the
> stored content hash is a *custody event* … not an overwrite. (§4)

So we **reject the self-mutating-vault philosophy** and instead adopt the
*mechanism underneath it* — sentinel-fenced regeneration applied only to views
that are already derivable from raw + index. obsidian mutates the record;
Scrolls regenerates the view and records the change as a custody event. Every
mapping below is filtered through that distinction.

## Adopt — strong, maps to an existing Scrolls capability

| obsidian-second-brain pattern | Scrolls mapping | Why it fits custody |
| --- | --- | --- |
| **Sentinel-safe generated blocks** (`/obsidian-architect`: `<!-- @generated -->` / `<!-- @user -->`; refresh replaces only generated content) | Make compiled `library/` pages and generated `agents/` instruction files carry a generated/user boundary, so a human/agent can hand-annotate without the next `kb`/`agent install` clobbering it | Directly enacts "raw is sacred, views regenerable" (custody-vision §2). Today a re-compile silently overwrites the whole file; this makes regeneration *non-destructive of annotations* while keeping the generated region authoritative. ADR 0102. |
| **Anti-fabrication + search-completeness hard rules** (never assert absence without exhaustive search; enumerate, don't sample; mark unknowns `TBD`) | Promote to an explicit **agent-contract invariant** for `search`, `context`, `related`, `works`, and `doctor`: results state their scope, never imply completeness they didn't verify, and "nothing found" is distinguishable from "not checked" | Custody-vision §6: "an agent that cannot trust a result's provenance and fidelity cannot use it." False absence silently corrupts a memory the same way for a vault and a library. |
| **Progressive context levels** (`/obsidian-world` L0–L3 token budgets) | An explicit budget tier on `scrolls context` (the agent-native bundle, IDEAS.md §11): identity/index first, deep bodies on demand | Builds on the just-shipped "collapse same-work context bundle hits"; turns the bundle into a budgeted boot sequence instead of a flat dump. |
| **AI-first preamble** ("For future Claude": what/why/when in 2-3 lines before the body) | A short agent-first preamble on generated `library/` index/section pages and bundles, stating scope + recency anchor | Cheap, and it makes a generated view self-describing for the agent that pulls it in isolation. Adopt the *discipline*, not a new note type. |
| **Vendor-neutral export bundle** (`/obsidian-export` → OKF "folders of markdown") | Strengthen scoped, self-contained custody bundles (custody-vision §3.7): a portable Markdown/HTML slice carrying provenance + fidelity, re-importable losslessly | We already have lossless `export items` (ADR 0082); a portable *briefing* bundle is the shareable complement. |
| **Scheduled maintenance agents** (nightly/weekly/health) | Frame the existing hourly autonomous worker as scheduled **custody maintenance** (audit → drift recheck → regenerate views → report), driven by `docs/agents/autonomous-roadmap.md` | The worker already exists; this gives its runs a custody-shaped default queue instead of ad-hoc adapter work. |

## Adapt — conceptual, defer the storage/implementation

| Pattern | Scrolls adaptation | Status |
| --- | --- | --- |
| **Bi-temporal facts** (`from`/`until` event-time vs `learned` transaction-time; never overwrite, append) | The same shape Scrolls' **custody ledger** wants for drift: *captured-at* (when we held this content) vs *source-changed-at* (when the live source diverged), recorded as events, never as an overwrite (ADR 0098 drift detection) | Adopt the concept; defer a dedicated timeline store until drift events need more than the current event record. |
| **`/obsidian-reconcile`** (find + resolve contradictions) | Scrolls already owns this as `docs/reconciliation.md` + the works model (ADR 0069/0095). Keep the *detection*; replace *auto-overwrite* with surfacing a conflict/drift custody event for review | Detection adopted; resolution stays custody-safe (surface, don't silently rewrite). |
| **`/obsidian-health` severity grouping** (🔴/🟡/⚪ critical/warning/info) | `scrolls doctor` custody report could group findings by severity for a faster agent read | Minor enhancement; defer behind the custody-score work already prioritized. |
| **Confidence levels per claim** (`stated`/`high`/`medium`/`speculation`) | Surface a confidence/recency marker on enrichment that infers (classification, LLM concept summaries) so an agent knows what to trust | Adopt as a surfacing gap; ties to fidelity tiers. |

## Reject — out of scope for a custody library

These are good for a personal-knowledge/productivity app but conflict with the
custody vision's de-emphasis of any note-app surface (Scrolls is a library, not
a note app) and its reframing of retrieval as *what you hold*, not discovery
(`docs/custody-vision.md` §4):

- **Self-mutating pages / auto-overwriting reconciliation** — violates raw-is-sacred and drift-surfaced (the framing decision above).
- **Productivity surfaces** — calendar, tasks, people, meetings, daily notes, kanban. Scrolls custodies artifacts; it is not a planner.
- **Paid live-research toolkit** — X/Grok, Perplexity, NotebookLM. Scrolls is keyless-first and local-first; discovery is explicitly downstream, not the product.
- **Presets/roles and the four-CLI build system** — Scrolls already serves agents via the CLI, MCP, and generated `agents/` targets (claude/codex/hermes); a second build matrix adds surface without custody value.
- **Thinking tools** (`/panel`, `/connect`, `/emerge`, `/challenge`, `/visualize`) — interesting, but discovery/ideation, not custody. Indefinitely deferred.

## Net effect on the roadmap

*Amended 2026-07-26: everything below has since shipped — M1 refresh-safe
regeneration (ADR 0102) and M2 the anti-fabrication/completeness invariant are
done, as are the reinforced capabilities (context budgets M3, the portable
custody bundle M4 / ADR 0103, and scheduled custody maintenance via
`scrolls maintain`). See `docs/product/mvp.md` and the roadmap's shipped
ledger; the text below is kept as the original decision framing.*

Two adoptions are new and decision-grade enough to drive near-term autonomous
work, and both deepen custody rather than widen adapters:

1. **Refresh-safe generated artifacts** (sentinel-fenced `library/` + `agents/` regeneration) — ADR 0102.
2. **Anti-fabrication / search-completeness as a tested agent-contract invariant** across the browse + audit surfaces.

The rest (progressive context budgets, portable briefing bundles, bi-temporal
drift framing, scheduled custody maintenance) reinforce capabilities Scrolls had
already prioritized. None of it introduces a new adapter. See
`docs/product/prd.md`, `docs/product/mvp.md`, and
`docs/agents/autonomous-roadmap.md` for how these sequence.
