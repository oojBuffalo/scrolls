# ADR 0005: Pass 5 starts with a deterministic KB compiler

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

Passes 1–4 produced the pipeline `detected → fetched → rendered` plus
stage-neutral classification, FTS5 search, and per-item Markdown scrolls.
The `library/` directory has existed since Pass 1 but stayed empty. Pass 5
(IDEAS.md §14) is the compiled library: index/concept/category/source
pages (§9, "feel like Karpathy wiki") and agent context bundles (§11).
The open questions were what a KB can honestly contain before any concept
extraction exists, how regeneration works, and whether compiling is an
item stage.

## Decision

1. **Deterministic rollups only.** `scrolls kb` (`scrolls/kb.py`) groups
   rendered scrolls by source, category, and frontmatter concepts and
   writes `library/index.md`, `library/sources/<source>.md`,
   `library/categories/<category>.md`, and
   `library/concepts/<concept>.md`. This is IDEAS.md §9's "simple
   version": group, count, backlink. LLM-synthesized concept pages are a
   future engine, exactly like LLM classification (ADR 0004).
2. **Only rendered items appear.** KB pages link to scroll files via
   relative Markdown links, and items without a `markdown_path` have
   nothing to link to. Standard links beat `[[wikilinks]]` for
   portability: they work in any Markdown tooling and for agents reading
   raw files. The index reports unclassified items as an honest count.
3. **`library/` generated pages are compile artifacts.** Every run wipes
   and rebuilds `index.md`, `sources/`, `categories/`, and `concepts/` so
   stale group pages can't linger after reclassification. Files the user
   puts elsewhere under `library/` are untouched.
4. **Compiling is not an item stage.** Like the FTS index, the KB is a
   library-level artifact derived from items; `scrolls kb` never changes
   item rows, so the IDEAS.md §4 `compiled` stage stays unused (ADR 0002
   already revised stage names for the add-one-URL path).
5. **Concept grouping is slug-keyed.** Spellings that slug identically
   ("BM25"/"bm25") merge into one page; the lexicographically smallest
   spelling is the display form. The `concepts` model field is already
   live, so the future concept-extraction/LLM engine feeds the KB with no
   compiler changes.

## Consequences

- `scrolls kb` is idempotent and safe to run after any ingest/classify;
  it does not auto-run inside `scrolls ingest` yet. If the library turns
  out to always want recompiling, a later slice can chain it (or add
  `ingest --kb` per IDEAS.md §4).
- Concept pages are empty until an engine populates `concepts`; the
  compiler and its tests already cover them via manually-set values.
- The full rebuild is O(library) per run — fine at personal-library
  scale; revisit incremental compilation only if it ever measures slow.
- The §11 context bundle (`scrolls context <query>`) is the second half
  of Pass 5 and builds on search, not on the compiled pages, so the two
  ship as separate slices.

## Proof

`src/scrolls/kb.py` + `scrolls kb` in `cli.py`, with deterministic tests
(`tests/test_kb.py`; 176 passing) and a live smoke test: `scrolls init` →
`kb` (empty index, 1 page) → `ingest en.wikipedia.org/wiki/Okapi_BM25` →
`kb` produced `index.md`, `sources/wikipedia.md`, and
`categories/reference.md` with working relative links.
