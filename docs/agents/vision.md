# Scrolls Vision — First-Principles Synthesis

This document defines the long-term product and engineering vision for Scrolls. It synthesizes the strongest ideas from the existing Scrolls design and the `mvanhorn/last30days-skill` project, filtered through first-principles engineering discipline. The goal is a system that is **local-first**, **agent-native**, **signal-aware**, and **dogfoodable**.

## Core Thesis

Scrolls is a **local-first knowledge operating system** for personal and small-team internet artifacts.

It turns scattered saved items (links, posts, papers, code, transcripts, discussions) into a durable, queryable, agent-readable library that compounds value over time.

The library is the product. The CLI, MCP server, and Markdown files are the interfaces. Agents are the primary users.

## First-Principles Design Rules

1. **Local ownership is non-negotiable**  
   All raw data, indexes, and rendered scrolls live on the user's machine. Exports are explicit and auditable. No cloud sync is the default.

2. **The agent contract is the product**  
   Every public surface (CLI commands, MCP tools, Markdown frontmatter, library pages) must be predictable, inspectable, and composable by agents. If an agent cannot reliably use a feature, the feature does not exist.

3. **Signal over noise**  
   Ranking, clustering, and confidence must be based on real provenance and engagement signals (when available), not just recency or keyword match. Every ranking decision should be explainable.

4. **Graceful degradation is the norm**  
   Partial source failures, missing metadata, and thin evidence are expected. The system must remain usable and clearly report what is degraded.

5. **Provenance is sacred**  
   Every scroll carries a complete, machine-readable history of how it was obtained, classified, enriched, and linked. No black-box transformations.

6. **Simplicity compounds faster than features**  
   Every new capability must justify its complexity with measurable improvement in agent or human utility. Adapter churn without new abstraction value is forbidden.

7. **Dogfood is the only valid test**  
   Major features must have an end-to-end workflow an agent can execute without human intervention (ingest → search → cluster → export → repair).

8. **Durable artifacts beat chat output**  
   The library produces shareable, self-contained Markdown/HTML bundles that survive outside the running system.

## Desired Product Shape (What Should Exist)

### Core Model
- **Sources → Items → Scrolls → Library → Agents**
- Sources are pluggable adapters with a strict contract.
- Items are normalized records.
- Scrolls are the canonical durable Markdown + frontmatter artifacts.
- Library is the compiled, interlinked KB (concepts, sources, backlinks, clusters).
- Agents consume via CLI, MCP, and direct file access.

### High-Priority Capabilities (Autonomous Focus Areas)

1. **Deep Works Merge & Canonical Items**  
   Multiple representations of the same work (preprint + published DOI + PMC full text) collapse into one canonical scroll with rich relations. Source pages and search results show the canonical item.

2. **Explainable Ranking & Confidence**  
   Search, list, facets, and MCP tools surface why an item ranks where it does (engagement, provenance, link density, concept overlap, source quality). Confidence scores and uncertainty flags are first-class.

3. **Evidence Clustering & Deduplication**  
   Cross-source stories and duplicate representations are automatically clustered. The library surface shows merged clusters with constituent evidence.

4. **MCP + Search + List Consistency**  
   MCP tools, CLI search/list, and library pages all use the same filters, facets, ranking, and pagination semantics. No drift.

5. **Doctor, Repair & Resilience**  
   `scrolls doctor` detects degraded states (missing scrolls, broken links, failed enrichments). Repair commands are safe, reversible, and logged.

6. **Lossless Export / Import & Shareable Bundles**  
   Full library or scoped slices can be exported as JSONL + Markdown bundles. Imports are idempotent. HTML briefs (inspired by last30days) are a supported output format.

7. **Threaded / Comment Rendering**  
   Code-host threads, discussions, and comment trees render as first-class scrolls with proper threading and provenance.

8. **Fixtures, Evals & Regression Harness**  
   Every adapter, MCP tool, search path, and export format has fixture-backed tests. Quality and regression suites run on every autonomous pass.

9. **Dogfood Workflows**  
   Documented, automated end-to-end flows: "research a topic", "maintain a project library", "export a briefing", "repair after source change".

### Medium-Priority (Once Core Is Solid)

- Typed graph edges (`cites`, `same-work`, `mentions`).
- Richer enrichment (parent POM inheritance, full-text where available).
- Per-source quality nudges and caps.
- Agent-facing "plan" generation for complex queries (inspired by last30days `--plan`).

### Features That Should Not Exist (or Be Deferred Indefinitely)

- Cloud sync or hosted library as default behavior.
- Real-time streaming ingestion (batch stages are sufficient and more resilient).
- Complex local UI or visual editor (this is a library, not a note app).
- Overly clever AI summarization that cannot be audited or regenerated from source.
- More one-off registry adapters unless they exercise a genuinely new abstraction or unlock a dogfood workflow.
- Anything that requires persistent remote accounts or leaks raw user data.

## Architectural Patterns to Adopt from last30days-skill

- **Contract separation**: Clear boundary between agent instructions and the executable engine (CLI/MCP).
- **Multi-source fanout with per-source error isolation**.
- **Evidence clustering + dedupe as a core library operation**.
- **Signal-weighted ranking** (engagement when present, provenance, graph signals).
- **Durable shareable artifacts** (HTML/Markdown briefs) in addition to chat/CLI output.
- **Fixtures + evals as product infrastructure**, not afterthought.
- **Dogfood as the primary success metric**.

## What Success Looks Like

An agent can:
1. Ingest a new topic or project from multiple sources.
2. Search and facet the library with explainable results.
3. Discover canonical works and related evidence.
4. Export a high-signal briefing or bundle.
5. Run doctor/repair and restore a clean state.
6. Do all of the above via MCP or CLI without human babysitting.

The library compounds: every new scroll makes future searches, clusters, and exports more valuable.

## Near-Term Autonomous Mandate

Future hourly runs on `work/scrolls-dev` must prioritize the high-priority capabilities above. New one-off adapters are only acceptable when they validate a broader pattern or unblock a dogfood workflow. Every commit should move the system measurably closer to the vision above.

This document is the north star. All ADRs, implementation choices, and review comments should reference it.
