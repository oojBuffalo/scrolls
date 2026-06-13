# 0044: `scrolls graph` — the cross-item link graph as a first-class view

Date: 2026-06-13

Status: accepted

## Context

A long run of adapters has been quietly building a graph. Each one stores,
in an item's `links`, the URLs that item points at, and several do so
deliberately as *typed edges* between saved items: a model's `arxiv:` tag
becomes the model↔paper edge (ADR 0041), a preprint's published DOI the
preprint↔published edge (ADR 0038), a Space's `cardData.models` the
space↔model edge (ADR 0043), and a package's repository URL the
package↔repo edge (ADRs 0034–0040). `scrolls related <id>` resolves those
links — raw and normalized, and through source detection so
`arxiv.org/pdf/X` finds item `arxiv:X` (ADR 0023) — and scores them
alongside shared concepts and tags.

But `related` is a *per-item* lens: it answers "what is next to this one?"
There was no way to see the graph as a whole — which items are hubs, which
lineage chains exist, how connected the library is — and no way to hand an
agent the connective structure in one call. The edges the adapters invested
in were invisible above the level of a single item. The link-resolution
logic that would power a whole-library view, moreover, lived private inside
`related.py` (`_link_targets`, `_own_urls`), so any second consumer would
either duplicate it or drift from it.

Three facts shaped the design:

1. **The graph is exactly `related`'s link signal, materialized.** An edge
   `A → B` should mean precisely what "A links to B" means in `related`:
   the same two-sided, source-detecting match. Reusing one definition keeps
   the per-item and whole-library views from ever disagreeing about what a
   link resolves to.

2. **The naive build is O(n²); the right one is linear.** Scoring every
   pair (what running `related` for all items would cost) is quadratic. But
   resolving links is a lookup: index every item's identity tokens (id,
   URLs raw and normalized) once, then probe that index with each link.
   That is linear in the number of links, and the index makes the build
   trivially correct as the library grows.

3. **Agents want the structure, not a hundred `related` calls.** The
   agent-native surface (IDEAS.md §10: shell first, MCP alongside) is a
   single JSON object of nodes and edges an agent can traverse, the same
   spirit as the context bundle (IDEAS.md §11).

## Decision

Add a `graph` module (`src/scrolls/graph.py`) and a `scrolls graph`
command, and refactor `related` onto the shared primitives.

- **Shared link primitives.** `graph.link_tokens(link)` returns the
  identity tokens a raw link could resolve to — the minted
  `source:source_id` item id (most specific), the normalized URL, then the
  raw URL — and `graph.identity_tokens(item)` returns what identifies an
  item as a target (its id and URLs, raw and normalized). `related.py`'s
  `_link_targets`/`_own_urls` become thin wrappers over these, producing
  byte-identical sets, so the existing `related` behavior is unchanged
  (`tests/test_related.py` is the guard) and there is now exactly one
  definition of link resolution (`tests/test_graph.py`).

- **Linear build.** `graph.build_graph(db_path, include_isolated=False)`
  indexes every item's identity tokens once (`token → first item`,
  oldest-first so duplicate collisions are deterministic), then resolves
  each item's links by probing the index in token-priority order. Parallel
  links `A → B` collapse to one edge keeping the first as `via`; self-links
  are dropped; edges sort by `(from, to)` and nodes by `id`. Nodes are the
  *connected* items by default — `include_isolated` widens to every item.
  `item_count` is always the library total, so connectivity reads against
  the whole.

- **One JSON shape, two surfaces.** `graph.to_payload` renders the graph as
  `{nodes, edges, stats}` (edges use `from`/`to` since `from` is a
  keyword). The CLI command (`scrolls graph [--all]`) and the MCP tool
  (`get_link_graph`) both emit it, so the contract lives in one place
  (`src/scrolls/cli.py`, `src/scrolls/mcp_server.py`,
  `tests/test_graph.py`, `tests/test_mcp.py`).

- **Conventions.** Empty or uninitialized library → an empty graph, exit 0
  (the `status`/`related` tolerance for empties). No network, no model —
  a pure rollup of links the pipeline already stored, like `kb`.

## Consequences

- The edges adapters have been building for a dozen ADRs become a
  first-class, agent-readable view: one call returns the library's hubs,
  lineage chains, and clusters. `scrolls graph` is the whole-library
  complement to `related`'s per-item lens, and `get_link_graph` gives MCP
  clients the same.
- Link resolution now has a single home. A future edge type (a new adapter
  cross-reference) is reflected in both `related` and `graph` for free, and
  neither can drift from the other.
- The graph is intentionally *untyped* in this slice: an edge records
  source, target, and the matching link, not a relation label
  (`cites`/`base_model`/`serves`). Typing edges would mean adapters storing
  the relation alongside each link — a larger, separable change this build
  stays reversible for. Likewise deferred: a rendered KB `library/graph.md`
  page, and folding shared-concept/shared-tag connections (the rest of
  `related`'s signal) into the graph as a second edge kind.
- The build is linear in links, so it scales with the library; the
  per-pair O(n²) of scoring is confined to `related`'s single-item path,
  where n is the cost of one query, not the whole graph.
