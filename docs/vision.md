# Scrolls Architectural Vision

**Status:** Authoritative vision for the `work/scrolls-dev` agent trunk. This document takes precedence over earlier exploratory notes when making architectural decisions.

## Core Purpose

Scrolls is a **local-first Personal Knowledge Operating System** for saved and referenced internet content.

Its job is to take content the user has intentionally saved or referenced (bookmarks, papers, videos, repositories, threads, PDFs, etc.) and turn it into a durable, queryable, richly linked, agent-native library that improves over time.

It follows the Field Theory-inspired pipeline but elevates it with strong product and engineering practices drawn from both Field Theory CLI and last30days-skill, synthesized into a first-principles design.

## The Six-Stage Pipeline (Elevated)

1. **Ingest** — Detect and fetch saved/referenced content from many sources.
2. **Enrich** — Add context, transcripts, full text, metadata, links, and provenance.
3. **Classify** — Determine category, domain, concepts, usefulness, and quality signals.
4. **Reconcile** — Merge representations of the same work, deduplicate, infer relationships.
5. **Index & Compile** — Build fast search + interlinked knowledge base (Markdown + graph).
6. **Expose** — Make the library available to agents and humans via CLI, MCP, and artifacts.

## Architectural Principles (Non-Negotiable)

### 1. Saved Item is the Primary Abstraction
- The system is about **saved and referenced items**, not general web search or discovery.
- Adapters are implementation details. The core model must support multiple ingestion paths (CLI, future browser extension, RSS, manual import, etc.).
- Every item must carry strong, queryable **provenance**.

### 2. The Markdown Scroll is the Canonical Durable Artifact
- The individual `.md` file (with rich frontmatter) is the source of truth for humans and agents.
- SQLite is the fast index and relationship graph, not the source of truth.
- This gives durability, portability, git-friendliness, and excellent agent readability.

### 3. Classification and Reconciliation are First-Class Product Features
- Classification is re-runnable, auditable, and incremental.
- Reconciliation (works merge, duplicate collapse, relationship inference, concept consolidation) is one of the highest-leverage things Scrolls can do. This is a flagship capability, not a nice-to-have.

### 4. The Agent Surface is a First-Class Product Concern
- CLI commands, MCP tools, and any future skill must have crisp, documented contracts.
- Output artifacts (Markdown scrolls, JSONL exports, HTML briefs, portable library bundles) are as important as the live system.
- The system must feel deliberately designed for agents.

### 5. Graceful Degradation and Observability
- Partial failures in any stage must not destroy the library.
- Errors, degraded states, and quality signals must be visible and actionable (`doctor`, source pages, MCP, logs).

### 6. Fixtures, Tests, and Dogfooding are Product Infrastructure
- Major pipeline stages must have golden fixtures and regression tests.
- Real dogfood workflows (ingest → search → reconcile → export → repair) must be exercised regularly.

## What We Optimize For

- **Durability and portability** of the user's knowledge.
- **Reconciliation quality** — collapsing many representations into one useful canonical item.
- **Agent trust** — reliable, explainable, contract-driven interfaces.
- **Incremental improvement** — the library gets visibly better as more items are added.
- **Human + agent readability** — Markdown first, structured data second.

## What We Deliberately De-emphasize

- Adding more one-off source adapters unless they unlock a new class of saved content or exercise a new pipeline pattern.
- Treating general web search or discovery as a goal.
- Over-generalizing "everything is a source."

## Near-Term Strategic Focus Areas

1. **Reconciliation Engine** — Deep works merge, duplicate detection, relationship inference.
2. **Provenance & Quality Model** — First-class tracking of where items came from and how reliable they are.
3. **Agent Contract Hardening** — Make CLI + MCP behavior predictable and well-documented.
4. **Export / Shareable Artifacts** — JSONL, Markdown bundles, HTML briefs, portable library format.
5. **Doctor, Repair, and Audit** — Serious subsystem for maintaining library health.
6. **Pipeline Observability** — Clear visibility into every stage for every item.
7. **Fixtures + Dogfood** — Build the testing and usage foundation that makes future work reliable.

## Relationship to Inspirations

- **Field Theory CLI**: The original 6-stage pipeline and focus on saved X bookmarks is the spark. We keep the spirit while generalizing it.
- **last30days-skill**: We borrow its product discipline — agent contract first, evidence clustering, signal-aware quality, shareable artifacts, fixtures/evals, and dogfood culture — but adapt them to a local-first saved-items library instead of a research engine.

This is not a copy of either. It is a first-principles synthesis that serves Scrolls' specific purpose.

## Governance

- This document lives on `work/scrolls-dev` (the agent integration trunk).
- All autonomous work on this branch must be consistent with this vision.
- Changes to this vision require explicit human approval.
- We do not open PRs to or merge into the repository `main` branch unless explicitly requested.

---

*Last updated: 2026-06-15 on work/scrolls-dev*