# 0062: `library/graph.md` — the link graph as a compiled KB page

Date: 2026-06-13

Status: accepted

## Context

`scrolls graph` (ADR 0044) materializes the cross-item link graph the
adapters spent a dozen ADRs building — a model wired to its paper
(ADR 0041), a preprint to its published DOI (ADR 0038), a package to its
repo (ADRs 0034–0042) — as a single `{nodes, edges, stats}` JSON object,
and `get_link_graph` hands MCP clients the same. ADR 0044 listed, among its
deferred follow-ups, "a rendered KB `library/graph.md` page".

That gap was real. The compiled library (`kb.py`, ADR 0005) is the
Karpathy-wiki shelf an agent or human *browses* as Markdown — `index.md`
plus per-source, per-category, and per-concept pages. It rolls up every
structured field the pipeline produces *except* the one the adapters most
deliberately built: the links between items. The connective tissue was
queryable (`scrolls graph`, `scrolls related`) and it surfaced in the
context bundle (ADR 0047), but it had no durable, browsable page in the
library itself. An agent reading `library/` could see "which scrolls carry
the BM25 concept" but not "which scrolls link to one another, and how they
cluster".

Two facts shaped the design:

1. **The interesting structure is the cluster, not the flat edge list.**
   A whole-library edge dump is what the JSON already is. The value a
   *page* adds is grouping: the library's connected components are its
   "islands of meaning" — a transformer-papers-and-models cluster, a
   rust-crates-and-repos cluster — exactly the hubs and lineage chains
   ADR 0044's docstring named. Connected components are a small, standard
   graph computation the `graph` module is the right home for.

2. **A KB page links to scroll files, and those links must resolve.** The
   library's stability guarantee (docs/library-format.md) is that every
   link in the generated tree resolves. But `build_graph` runs over *all*
   items, including unrendered ones with no scroll file to link. The page
   must therefore be built over the rendered items only — the same rule the
   rest of the KB already follows ("only rendered items appear").

## Decision

Compile a `library/graph.md` page, and add the clustering primitive it
needs to the `graph` module.

- **`graph.connected_components(graph)`** partitions the graph into
  clusters, treating edges as undirected for the partition (a link in
  either direction joins its endpoints) while preserving the original
  directed edges on each component. Clusters order by node count
  descending, then smallest node id; within a cluster nodes sort by id and
  edges by `(from, to)`, so the partition is stable run to run. A
  union-find with path compression keeps it linear
  (`tests/test_graph.py`).

- **`graph.graph_over(items)`**, factored out of `build_graph` (which now
  loads the items and delegates), builds the graph over a *given* item set.
  The KB compiler passes its rendered items, so a link whose target is
  unrendered never resolves — its identity isn't indexed — and the edge is
  dropped, exactly as the rest of the KB ignores unrendered items. The
  whole-library `build_graph`, `scrolls graph`, `scrolls related`, and the
  context bundle are byte-unchanged (`tests/test_graph.py`,
  `tests/test_related.py`, `tests/test_context.py`).

- **The page.** `kb.compile_kb` builds `connected_components(graph_over(
  rendered_items))` and writes `library/graph.md`: an H1, a connectivity
  line, then one `## Cluster N` section per component rendered as an
  *adjacency list* — every member a bullet linking to its scroll (the
  shared `_item_line`, relative to `library/`), with its outbound edges
  nested beneath as `→ target`. The page is always written, like the
  index; a library whose rendered scrolls don't yet link gets a single
  `No linked scrolls yet.` line, so it is a stable entry point
  (`tests/test_kb.py`, the pinned example in
  `tests/test_docs.py::test_library_format_graph_page_example_matches_compiler_output`).

- **The index links to it.** `index.md` carries a one-line link to
  `graph.md` under its count line, summarising connectivity, so the graph
  page is reachable by browsing from the entry point.

- **The compile summary gains `clusters`** (the connected-component count)
  and `pages` counts the always-written `graph.md`, flowing through
  `scrolls kb` and the MCP `compile_library` tool unchanged otherwise
  (`tests/test_kb.py`, `tests/test_mcp.py`, docs/cli.md).

## Consequences

- The cross-source edges the adapters built are now a durable, browsable
  artifact, not only a query result: an agent walking `library/` reads the
  library's clusters the way it reads its concepts and categories. This
  closes ADR 0044's deferred "rendered KB `library/graph.md` page".

- The page is deterministic and offline — a rollup of links the pipeline
  already stored, like every other KB page; the compiler still never calls
  a model or the network.

- Clustering lives in `graph.py`, the home of link resolution, so the
  per-item view (`related`), the whole-library JSON (`scrolls graph`), the
  context bundle (ADR 0047), and now the compiled page all agree on what an
  edge is. `graph_over` is the seam that let the page reuse all of it while
  scoping to rendered items.

- The page stays link-only and untyped, inheriting ADR 0044's two open
  deferrals: shared-concept/shared-tag connections are not yet a second
  edge kind, and edges carry no relation label (`cites`/`base_model`). Both
  would land in `graph.py` first and surface in every consumer at once.
