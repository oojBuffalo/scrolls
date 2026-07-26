# Scrolls Vision (Custody-First Synthesis)

**Status:** The operative north star for the `work/scrolls-dev` agent trunk.
All autonomous decisions are justified against this document.
**Original:** 2026-06-15, as the standalone custody-vision document.

*Amended: 2026-07-26 — the three vision documents were merged into this single
file. §1–§5 below are the custody-first synthesis unchanged (section numbering
preserved, so a citation like "custody-vision §2.4" resolves here as §2.4).
The unnumbered sections after §5 salvage the still-operative remainder of the
two earlier syntheses; their old paths were removed, and the ADRs that cited
them were amended in place with the updated paths.*

**Merge record — deliberately dropped from the earlier syntheses:**

- *"The Markdown scroll is the source of truth."* Contradicts §2.2: the
  captured raw record is the root of trust; scrolls and `library/` are
  re-derivable views.
- *Engagement / "signal-aware" ranking.* Reversed by §4: provenance and
  fidelity, not engagement scores, are the ranking signals for a custody
  system.
- *The "(personal) knowledge operating system" framing.* De-emphasized by §4;
  the compiled `library/` is a regenerable view, never load-bearing.
- *Both documents' self-authority claims* ("this document is the north star",
  "takes precedence over earlier notes"). This file is now the single
  authority.
- *The stale capability and focus lists* ("What We Optimize For", "Near-Term
  Strategic Focus Areas", "High-Priority Capabilities"). Superseded by §3;
  live scheduling is `docs/agents/autonomous-roadmap.md`; the few still-open
  ideas are salvaged under "Open capability notes" below.

## 1. Core Purpose

Scrolls is a **local-first custody system** for the internet artifacts a person or small team has deliberately saved or referenced. Its job is not to help you *find* new things (discovery) or to *rank* the open web (search) — those are downstream conveniences. Its job is to be the durable, accountable **steward** of what you already chose to keep: to hold each artifact faithfully, prove what it was at capture time, detect when the live source rots or drifts away from that capture, degrade honestly when full fidelity is impossible, and let you walk away with everything losslessly at any moment. The library is a *custody ledger* — every scroll carries a verifiable chain from raw capture through enrichment to rendered artifact — and agents are its primary readers, trusting it precisely because nothing in it is a black box.

## 2. Architectural Principles

1. **Custody, not capture-and-forget.** The system's contract is *we still hold a faithful copy of what you saved, and we can prove it.* Every feature is judged by whether it strengthens or weakens that promise. Ingestion is the cheap part; stewardship over time is the product.

2. **Raw is sacred; everything else is derivable.** The captured raw record (`raw_text`, content hash, provenance, source response) is the root of trust. Scrolls, `library/`, facets, concept pages, and bundles are all *re-derivable views* and must be rebuildable from raw + index with a single command. No view may hold information that cannot be regenerated.

3. **Fidelity is explicit and first-class.** Every scroll declares the tier at which it is held — **full-content** (raw preserved, body re-derivable), **partial/metadata-only** (spine captured, body degraded), or **reference-only** (we hold the pointer + provenance but not the content). Degradation is never silent; it is a queryable, facetable property of the library.

4. **Drift and rot are surfaced, never hidden.** A re-fetch that disagrees with the stored content hash is a *custody event* (drifted / 404-rotted / unchanged), recorded and reportable — not an overwrite. The library can always answer "what have I lost or what changed since I saved it?"

5. **The library is a way-station, not a sink.** Custody without exit is hostage-taking. Every artifact round-trips out losslessly (`export items` JSONL is the model-complete backup; `export opml`/`bookmarks` round-trip against external tools). Idempotent import/export is load-bearing infrastructure, not a feature bolt-on.

6. **The agent contract is the integrity boundary.** Every public surface — CLI JSON, MCP tools, frontmatter, `library/` pages — must be predictable, inspectable, and identical in semantics across surfaces (search ≡ list ≡ MCP ≡ facets). An agent that cannot trust a result's provenance and fidelity cannot use it; therefore those must travel *with* every result.

7. **Adapters are commodity; custody guarantees are the moat.** A source adapter is a thin capture mechanism. Breadth of adapters is not the product and must stop being the default unit of progress. A new adapter is justified only when it exercises a genuinely new *custody shape* (a new fidelity boundary, identity rule, or thread/canonical structure), never as another near-identical registry.

8. **Simplicity compounds; integrity is verified, not asserted.** Every capability must pay for its complexity in measurable custody value, and every custody claim must be backed by a fixture-driven test or concrete command output. "Self-healing" that isn't continuously proven is just hope.

## 3. Prioritized Capabilities (present and emphasized)

In rough dependency order:

1. **Custody integrity audit (hardening core).** `scrolls doctor` graduates from "find broken links/missing scrolls" to a full **custody report**: for every rendered item, verify the scroll exists, its body re-derives to the stored content hash, raw is present *or* fidelity is honestly downgraded, and provenance is complete. Output a per-library **custody score** with a categorized breakdown. Network-free, deterministic, the foundation everything else stands on.

2. **Explicit fidelity tiers.** A derived (then, if needed, persisted) `fidelity` property over existing `ScrollItem` fields, surfaced in `list`, `facets`, `show`, and MCP. Makes "you hold 1,200 scrolls: 800 full, 300 metadata-only, 100 reference-only" a one-command answer.

3. **Drift / rot detection on re-fetch.** `scrolls fetch --recheck` (or `scrolls verify`) re-captures a rendered item, compares against the stored hash, and records a custody event without clobbering the original capture. Doctor aggregates these into a rot/drift report. This is the custody *ledger* made real.

4. **Lossless round-trip as a guarantee, not a command.** Treat `export items` ↔ `import items` as a tested *invariant* (export→import→export is byte-stable for the model-complete fields), and make "rebuild every derived view from raw" (`doctor --fix` + `kb`) a dogfood-verified path.

5. **Canonical works as custody consolidation.** The recent canonical-representation work (ADR 0095/0096) is squarely custody: many representations of one work (preprint + DOI + PMC) are *held together* as one custodied work with typed relations. Continue here — it deepens an abstraction rather than widening the adapter count.

6. **Provenance-complete, re-derivable enrichment.** Classification, concept pages, and LLM summaries must record their inputs/method and regenerate deterministically from raw. Auditable enrichment stays; un-reproducible "clever" summarization does not.

7. **Shareable, self-contained custody bundles.** Scoped export to a portable Markdown/HTML bundle that carries provenance and fidelity with it — a briefing that survives outside the running system and can be re-imported losslessly.

8. **Dogfood workflows as the success metric.** End-to-end, agent-runnable flows: *hold a topic* (ingest → render → audit), *prove custody* (doctor → custody score), *detect loss* (recheck → drift report), *take it with me* (export bundle → reimport). If an agent can't run it unattended, it isn't done. **Shipped (MVP M5):** this flow runs offline against fixtures in `tests/test_dogfood.py` and is narrated, with captured before/after output, in [`docs/dogfood.md`](dogfood.md). Its sharp result: detecting source drift moves the *drift posture* (unverified → drifted, recorded) without lowering the *integrity score*, because raw is sacred and drift is an event, not an overwrite (§2.4).

## 4. What Should Be Modified or De-emphasized

- **Reframe search and ranking from "discovery engine" to "retrieval of what you hold."** Keep FTS5 search, facets, and `context` bundles — they're how agents *reach* custodied material — but drop the ambition to be signal-aware/engagement-ranked like a discovery tool. Provenance and fidelity, not engagement scores, are the ranking signals that matter for a custody system.

- **Stop the adapter sprawl, explicitly.** The recent run of near-identical package-registry adapters adds breadth without custody depth. Declare a moratorium: no new adapter unless it introduces a new custody shape. This directly enacts the autonomous mandate the codebase already states but hasn't followed.

- **De-emphasize "knowledge operating system" / Karpathy-wiki framing.** Concept pages and the compiled `library/` are *views*, valuable but secondary. They should never be load-bearing for custody and should always be regenerable; don't invest in them ahead of integrity, fidelity, and drift.

- **Demote LLM concept synthesis to an auditable view.** Keep it gated behind reproducibility (record inputs + members fingerprint); never let it become a source of truth that can't be rebuilt.

- **Drop from the roadmap (or keep indefinitely deferred):** default cloud sync, real-time streaming ingestion, any visual editor/note-app surface, persistent remote accounts, and any transformation that can't be re-derived from raw.

## 5. Recommended First Concrete Slice

**Ship the custody integrity audit as a vertical, network-free hardening slice — `scrolls doctor` custody report + a `fidelity` facet — with fixtures.**

Why this first: it's pure hardening, fully deterministic (no network, no flaky live sources), it makes the new custody framing *visible and measurable* on day one, and every later capability (drift detection, fidelity upgrades, bundles, dogfood proofs) builds directly on the model and report it establishes. It also turns the principles above from prose into a number a future run can defend.

Concrete shape (one coherent slice, top-to-bottom):

1. **Model:** a pure `fidelity(item) -> {full | partial | reference}` derivation in a small new module, computed from existing `ScrollItem` fields (presence of `extracted_text`/`raw_text`, stage, source kind). No schema migration required initially — derive, don't store, until a measured need appears.

2. **Audit:** extend `src/scrolls/doctor.py` with custody checks per rendered item — scroll file present, body re-derives to stored `content_hash`, raw present or fidelity honestly downgraded, provenance complete — emitting a categorized **custody report** and an aggregate score in the existing JSON output shape.

3. **Surface:** add `fidelity` as a facet (alongside the existing facets) and a column/field in `list`/`show`, so the custody state is queryable, not just printed by doctor.

4. **Tests:** fixture-backed cases in `tests/test_doctor.py` (and a new `test_fidelity`) covering full/partial/reference items, a deliberately drifted hash, a missing scroll, and a degraded-but-honest item — proving the audit catches each.

5. **Verify & document:** `uv run pytest`, capture `scrolls doctor --json` output, and record the custody-tier definitions and audit contract in an ADR so future drift-detection and bundle work reference a stable vocabulary.

The natural **next** slice (phase 2, network-bearing) is drift/rot detection via `fetch --recheck` recording custody events — but it should land *after* the integrity audit gives it a deterministic home to report into.

*(This slice shipped: the audit is ADR 0097, drift detection ADR 0098, and the
capability list above carries per-item shipped notes where relevant. §5 is kept
as the original sequencing rationale.)*

---

This vision deliberately focuses on custody integrity as the load-bearing wall
for Scrolls. All autonomous work on the agent trunk must align with it.

## Governance

- This document lives on `work/scrolls-dev` (the agent integration trunk).
- All autonomous work on this branch must be consistent with this vision.
- **Changes to this vision require explicit human approval.**
- We do not open PRs to or merge into the repository `main` branch unless
  explicitly requested.

## Success shape

The library compounds: every new scroll makes future searches, clusters, and
exports more valuable. The dogfood flows in §3.8 are the measure — if an agent
cannot run them unattended, they are not done.

## Open capability notes (salvaged from the earlier syntheses, 2026-07-26)

Ideas from the merged documents that remain unscheduled but worth holding:

- **Threaded / comment rendering** — code-host threads, discussions, and
  comment trees as first-class scrolls with proper threading and provenance
  (partially enacted by the shared thread-rendering work, ADR 0093).
- **Typed graph edges** — `cites` / `same-work` / `mentions` as explicit edge
  types (same-work shipped via the works model; the rest open).
- **Richer enrichment** — parent-POM inheritance for Maven; full text where
  available.

Cross-source evidence clustering, per-source quality caps, and `--plan`
generation are tracked as still-open patterns in
`docs/inspiration/last30days-inspiration.md`.

## Lineage

Scrolls synthesizes patterns from Field Theory CLI, last30days-skill, and
obsidian-second-brain into an original custody-first design. The full
adopt/adapt/reject record lives in `docs/inspiration/` — one document per
inspiration source.
