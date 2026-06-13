# 0070: `library/works.md` — scholarly works as a compiled KB page

Date: 2026-06-13

Status: accepted

## Context

`scrolls works` (ADR [0069](0069-works-by-doi.md)) clusters the library's
items into *works* keyed by the DOI that names them: one scholarly work now
sits in the library as several near-duplicate `paper` entries — an arXiv
preprint (ADR 0038), its published Crossref article (ADR 0037), a PubMed
record (ADR 0065), a bioRxiv/medRxiv preprint (ADR 0068) — and the command
consolidates those representations into the work they all manifest. It
emits a `{works, stats}` JSON object, and the MCP `get_works` tool hands
agents the same.

ADR 0069 factored `works_over(items)` out of `find_works` for exactly one
named reason: "a future KB `library/works.md` page ... can pass only its
rendered items". That page is this ADR — the works analog of the link-graph
page ADR [0062](0062-kb-link-graph-page.md) added, and the same gap it
closed. The compiled library (`kb.py`, ADR 0005) is the Karpathy-wiki shelf
an agent or human *browses* as Markdown. After ADR 0062 it rolls up sources,
categories, concepts, tags, and the link graph — but the DOI-clustered works,
the semantically-correct "same scholarly work" lens (the FRBR sense Crossref
and OpenAlex use), were queryable (`scrolls works`, `get_works`) yet had no
browsable page. An agent reading `library/` could see "which scrolls carry
the BM25 concept" and "which scrolls link to one another" but not "which of
my papers are the same work held twice".

Two facts shaped the design, mirroring ADR 0062:

1. **The interesting structure is the work, not a flat item list.** A
   whole-library dump is what the JSON already is. The value a *page* adds
   is the grouping: the preprint-and-published pairs, the
   preprint/published/indexed triples — the DOI hubs the four paper sources
   feed. `works_over` already computes them.

2. **A KB page links to scroll files, and those links must resolve.** The
   library's stability guarantee (docs/library-format.md) is that every link
   in the generated tree resolves. `find_works` clusters over *all* items,
   including unrendered ones with no scroll file. The page must be built
   over the rendered items only — the same rule the rest of the KB follows,
   and exactly why `works_over` takes an item set.

## Decision

Compile a `library/works.md` page, reusing `works.works_over` over the
compiler's rendered items.

- **The page.** `kb.compile_kb` calls `works_over(rendered_items)` and writes
  `library/works.md`: an H1, a summary line (`N works held as M
  representations.`), then one `## <doi>` section per work — the `doi.org`
  resolver link with a representation count, then every representation as a
  bullet linking to its scroll (the shared `_item_line`, relative to
  `library/`, looked up by id in the same `items_by_id` map the graph page
  uses). Works keep `works_over`'s order (representation count descending,
  then DOI) and representations sort by id. The page is always written, like
  the index and the graph page; a library with no DOI held in two-plus
  rendered representations gets a single `No works held in multiple
  representations yet.` line, so it is a stable entry point
  (`tests/test_kb.py`, the pinned example in `tests/test_docs.py::`
  `test_library_format_works_page_example_matches_compiler_output`).

- **The index links to it.** `index.md` carries a one-line `Works` link to
  `works.md` under the graph line, summarising how many works are held, so the
  page is reachable by browsing from the entry point.

- **The compile summary gains `works`** (the multi-representation work count)
  and `pages` counts the always-written `works.md`, flowing through
  `scrolls kb` and the MCP `compile_library` tool unchanged otherwise
  (`tests/test_kb.py`, `tests/test_mcp.py`, docs/cli.md).

## Consequences

- The DOI-clustered works `scrolls works` reports are now a durable,
  browsable artifact, not only a query result: an agent walking `library/`
  reads "these two scrolls are the same paper" the way it reads the library's
  clusters, concepts, and categories. This closes ADR 0069's deferred KB page.

- The page is deterministic and offline — a rollup of DOIs the pipeline
  already stored (`source_id` DOIs and `doi.org` links resolved through the
  same `detect_source`+`normalize_url` path the graph uses), like every other
  KB page; the compiler still never calls a model or the network.

- Clustering lives in `works.py`, so `scrolls works`, `get_works`, and the
  compiled page all agree on what a work is. `works_over` is the seam that
  let the page reuse all of it while scoping to rendered items — the
  `graph_over` pattern ADR 0062 established, applied a second time.

- Because the page scopes to rendered items while `scrolls works` clusters
  over the whole library, the page's work count can be smaller than the
  CLI's — the same rendered-only divergence the graph page has from `scrolls
  graph`, documented in docs/library-format.md.

- The page inherits ADR 0069's open deferrals: title-fuzzy matching for
  DOI-less duplicates, and the heavier "merge the near-duplicate `paper`
  entries into one" step. This page *surfaces* the duplication browsably; it
  does not yet consolidate the scrolls themselves.
