# Field Theory CLI inspiration for Scrolls

*Amended: 2026-07-26 — first dedicated write-up; assembled from lineage notes
previously scattered across `IDEAS.md` (§0, §7, §8, §13) and the earlier
vision syntheses.*

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
system** (`docs/custody-vision.md` §1): the pipeline generalized across ~57
adapters, and the library reframed from a knowledge base into a custody
ledger.

## The discipline to preserve

Field Theory's useful pattern is not the language; it is the discipline
(moved verbatim from IDEAS.md §13, "Field Theory lessons to preserve"):

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
  became Scrolls' *raw is sacred* principle (custody vision §2.2): every
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

## Concrete legacy in Scrolls

- `scrolls import fieldtheory` bulk-imports X bookmarks from a Field Theory
  archive (`~/.fieldtheory/`: raw `bookmarks.jsonl` plus classified library
  pages). The proposal is IDEAS.md §7, the decision ADR 0009, the command
  contract `docs/cli.md`.
- Field Theory remains a first-class *source* in the domain vocabulary
  (`docs/agents/domain.md`).

## Pointers

- IDEAS.md §0 (the spark acknowledgment), §7 (the import proposal), §8 (the
  category seed), §13 (the lessons + stack trade-off) — the historical
  brainstorm, kept in place.
- ADR 0009 (Field Theory import), ADR 0001 (implementation stack).
