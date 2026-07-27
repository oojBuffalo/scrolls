# Field Theory CLI inspiration for Scrolls

*Amended: 2026-07-26 — first dedicated write-up; assembled from lineage notes
previously scattered across `IDEAS.md` and the earlier vision syntheses. The
IDEAS.md lineage portions (the spark acknowledgment, the import proposal, and
the "Field Theory lessons") were moved fully into this document — nothing of
them remains there.*

Field Theory CLI is the project's origin spark: the original X-bookmarks
pipeline whose shape Scrolls generalized. Unlike the other two inspiration
sources it is also *live lineage* — Scrolls ships a first-class importer for
Field Theory archives (`scrolls import fieldtheory`, ADR 0009). There is no
reference checkout; the lineage travels through the import format and the
notes below.

## The spark

Field Theory turned one platform's saved items (X bookmarks) into a
classified, searchable, agent-readable local library. Its original 6-stage
pipeline and its focus on deliberately saved items is where Scrolls began —
"we keep the spirit while generalizing it," as the earlier vision synthesis
put it. Scrolls elevates the same flow into a source-agnostic **custody
system** (`docs/vision.md` §1): the pipeline generalized across ~57
adapters, and the library reframed from a knowledge base into a custody
ledger.

## The discipline to preserve

Field Theory's useful pattern is not the language; it is the discipline
(moved here verbatim from the IDEAS.md brainstorm, 2026-07-26):

```text
browser session/cookies → platform API/GraphQL → JSONL cache → SQLite FTS/BM25 → Markdown → agent skill
```

Borrow these regardless of stack:

- avoid literal browser driving when a session-backed API/export path works
- preserve raw records so indexes and Markdown can be rebuilt
- separate sync/import from enrichment
- run rules/regex before optional LLM classification
- expose agents through shell commands first; MCP can come later
- keep Markdown scrolls as durable, human-readable artifacts

## Patterns adopted

- **Raw-record preservation for rebuildability.** Field Theory's JSONL cache
  became Scrolls' *raw is sacred* principle (vision §2.2): every
  derived view regenerates from raw + index.
- **`import` / `sync` / `add` as distinct verbs.** Bulk local-archive
  ingestion vs live platform deltas vs one-off URL capture (IDEAS.md §13).
- **Rules-first classification.** Regex/rules before an optional LLM engine,
  with user overrides always winning (IDEAS.md §8; ADR 0004, 0015, 0018).
- **Shell-first agent access.** Reliable CLI commands with JSON output came
  first; MCP followed once the contract was stable (ADR 0014), exactly as the
  lessons list prescribed.
- **Markdown as the durable artifact.** One scroll per item (frontmatter +
  body); SQLite as the fast, rebuildable index.

## Patterns adapted

- **Category vocabulary.** Field Theory's categories
  (tool / security / technique / launch / research / opinion / commerce)
  seeded the extended classification vocabulary Scrolls uses today
  (IDEAS.md §8).
- **Stack.** A "Field Theory-style" TypeScript CLI was weighed against Python
  and rejected — the discipline transferred, the language did not
  (IDEAS.md §13; ADR 0001).

## Patterns rejected or deferred

- **Literal browser driving.** Never adopted; Scrolls uses session-backed
  APIs, feeds, or local archives instead.
- **Native X sync.** Deferred indefinitely — the X read API is paywalled, so
  X bookmarks arrive via the Field Theory archive import rather than a live
  adapter (ADR 0009; `docs/architecture.md`).

## The original import proposal

Moved here from the IDEAS.md brainstorm (2026-07-26) — the idea that became
ADR 0009:

Instead of immediately reimplementing X bookmark sync, Scrolls could
initially support:

```bash
scrolls import fieldtheory
```

It could read:

```text
~/.fieldtheory/bookmarks/
~/.fieldtheory/library/
```

Then convert Field Theory items into Scrolls' normalized format. That gives
Scrolls an immediate path to X bookmarks while letting Field Theory keep
doing what it already does well. Later, `scrolls sync x --bookmarks` could
be native — the "later" path that stayed deferred (the X read API is
paywalled).

## Concrete legacy in Scrolls

- `scrolls import fieldtheory` bulk-imports X bookmarks from a Field Theory
  archive (`~/.fieldtheory/`: raw `bookmarks.jsonl` plus classified library
  pages). The proposal is above, the decision ADR 0009, the command
  contract `docs/cli.md`.
- Field Theory remains a first-class *source* in the domain vocabulary
  (`docs/agents/domain.md`).

## Pointers

- ADR 0009 (Field Theory import), ADR 0001 (implementation stack).
- IDEAS.md §8 and §13 remain living design notes this lineage fed into (the
  layered-classification vocabulary; the import/sync/add split and the stack
  trade-off ADR 0001 resolved) — cited inline above.
