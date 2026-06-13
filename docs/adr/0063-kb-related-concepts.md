# 0063: Related Concepts on KB concept pages — the concept-graph complement to the link graph

Date: 2026-06-13

Status: accepted

## Context

The compiled library (`kb.py`, ADR 0005) gives every concept its own page:
the scrolls that carry it, optionally led by an LLM-synthesized summary
(ADR 0025). IDEAS.md §9's sketch of that page has a second section the
compiler never built — **Related Concepts**:

```md
## Related Concepts

- [[Full-text search]]
- [[SQLite]]
- [[Ranking]]
```

That gap left the library with a *link* graph but no browsable *concept*
graph. The adapters' cross-source links cluster into "islands of meaning"
(`scrolls graph`, ADR 0044; `library/graph.md`, ADR 0062), but the other
structure the library holds — which ideas recur *together* across saved
items — was visible only one page at a time (this concept's members) with
no edges between concepts. An agent browsing `concepts/bm25.md` could read
which scrolls mention BM25 but not that BM25 keeps company with full-text
search and ranking across the library.

The link graph already declined this signal on purpose. ADR 0044 and
ADR 0047 both deferred "shared-concept/shared-tag" edges in the *link*
graph, and ADR 0062 restated it. The reason is density: concepts form
cliques — every pair of concepts on one scroll is an edge — so folding them
into `scrolls graph` would bury the sparse, high-signal link edges (a model
to its paper, a package to its repo) under a fog of co-occurrence edges. The
concept page, not the link graph, is the right home for the concept signal:
it is already scoped to one concept, so its neighbours are a short ranked
list, not a global clique.

## Decision

Add a deterministic **Related Concepts** section to each concept page,
computed by concept co-occurrence over the rendered scrolls.

- **`kb.related_concepts(by_concept, limit=10)`** is a pure function over the
  same `group_concepts` grouping the compiler already builds. Two concepts
  are *related* when at least one rendered scroll carries both; the strength
  is how many scrolls carry both (an item-id set intersection per concept
  pair). It returns, per slug, a list of
  `(other_slug, other_display, shared_count)` ordered by shared count
  descending, then the other concept's case-folded display, then its slug —
  stable run to run — capped at `limit` (10, matching the index's recent
  cap). A concept whose members carry no other concept maps to an empty list
  (`tests/test_kb.py::test_related_concepts_merges_spellings_and_caps`).

- **The page.** `compile_kb` computes the map once and passes each concept's
  related list to `_write_page` as a `trailer` — a generic "lines appended
  after the members" hook that leaves source and category pages untouched.
  The trailer renders `## Related Concepts` followed by one bullet per
  neighbour: the concept's display spelling linking its sibling page (a bare
  `<slug>.md`, since concept pages share the `concepts/` directory) with a
  `— N shared scroll(s)` note carrying the strength. A concept with no
  co-occurrence gets no section, mirroring the index's omit-empty-sections
  rule (`tests/test_kb.py::test_kb_concept_page_lists_related_concepts`,
  `test_kb_concept_page_without_co_occurrence_omits_related_section`).

- **Merge-by-slug throughout.** Neighbours are deduped and displayed by the
  same slug merge `group_concepts` uses, so `RAG` and `rag` are one concept
  on both sides of an edge and a concept never relates to itself across a
  spelling variant.

## Consequences

- The library now has a browsable concept graph beside its link graph: the
  co-occurrence structure of ideas, surfaced where an agent already reads a
  concept. The MCP `get_concept_page` tool returns the rendered file, so the
  section reaches agents with no new tool or schema (`tests/test_mcp.py`).

- It is deterministic and offline — a rollup of the `concepts` the pipeline
  already stored, like every other plain `scrolls kb` page; the compiler
  still never calls a model. The LLM concept summary (ADR 0025) and this
  deterministic co-occurrence list coexist on the page (summary leads, member
  list, then Related Concepts).

- The concept edges live on the concept pages, **not** in `scrolls graph`,
  so ADR 0044/0047/0062's deliberate "link graph stays sparse and link-only"
  posture is preserved. This resolves the *concept* half of those ADRs'
  shared-concept/shared-tag deferral by giving it the right home; the link
  graph's relation-label deferral and a possible shared-*tag* page section
  remain open.

- The cap is a silent top-N: a hub concept's weakest co-occurrences (all tied
  at one shared scroll) drop alphabetically past the tenth. The strongest —
  the ones an agent wants — are kept, and a future LLM pass or a richer
  concept-graph view could lift the cap; documented in `docs/library-format.md`.
