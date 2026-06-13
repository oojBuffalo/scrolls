# ADR 0060: an MCP `list_scrolls` tool — faceted enumeration for agents

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

ADRs 0058 and 0059 gave the CLI `scrolls list` five facets
(`source`/`stage`/`category`/`tag`/`concept`) and threaded the same
facets through `scrolls search` and `scrolls context`, on both the CLI
and the MCP server. But `scrolls list` itself had no MCP counterpart: the
server exposed `search_scrolls` (ranked, needs a query), `list_sources`
(per-source *counts* only), and the retrieval/connection tools — nothing
that *enumerates* items by facet.

So a protocol agent could ask "what mentions transformers" (`search_scrolls`)
but not "what arxiv papers tagged efficient are in the library" — a
question with no natural search query, only facets. The faceted-list work
of ADRs 0058/0059 was reachable from the shell but not from the surface
the facet work was explicitly built for (agents). That is the same
consumption-side asymmetry those ADRs set out to close, one tool short.

## Decision

1. **Add a `list_scrolls` MCP tool — the enumeration counterpart to
   `search_scrolls`.** It lists items with *no query*, filtered by the
   same five facets `scrolls list`/`list_items` take, AND-ed together with
   identical semantics (exact `source`/`stage`; `category` exact except
   `""` → unclassified; `tag` case-insensitive membership; `concept`
   membership by slug — ADRs 0058/0059). It wraps `items.list_items`
   directly, like every other read tool wraps its engine.

2. **Return the same summary shape `scrolls list` prints** — `id`,
   `source`, `url`, `title`, `category`, `stage`, `saved_at` — so an agent
   reads one consistent item summary across the CLI and MCP and follows up
   with `get_scroll` for the full record. Items come oldest-saved first,
   matching `list_items`' order, so CLI and MCP agree.

3. **Bound the result with a `limit` (default 50).** This is the one place
   `list_scrolls` departs from the unbounded CLI `scrolls list`: a human
   can pipe a 5000-row list through `grep`, but an agent pastes it into a
   context window. A default cap keeps the tool context-friendly while
   leaving the agent free to raise it; the cap is applied after
   `list_items` (a local-first library is small enough that loading then
   slicing is not worth a core `LIMIT` parameter that the CLI does not
   need). The default is documented in the tool's description so the model
   knows results may be truncated and how to widen them.

4. **Read-only, empty-library-safe, no new engine.** Like `list_sources`,
   an uninitialized library returns `[]`. No network, no model, no schema
   change — purely a new view over the existing index, so it carries the
   same risk as the other read tools (none).

## Consequences

- The faceted-list capability ADRs 0058/0059 built is now reachable from
  the MCP surface those ADRs named as the intended consumer: "list every
  paper", "browse this source", "items carrying the BM25 concept" are one
  tool call, no query invented.
- `search_scrolls` and `list_scrolls` now mirror the CLI's `search`/`list`
  pair: ranked-by-query versus enumerated-by-facet, the same facets on
  both. An agent picks by whether it has a query or only filters.
- A new tool joins the protocol surface, so the documented-tool set
  (`tests/test_mcp.py::test_server_exposes_exactly_the_documented_tools`)
  and the `docs/cli.md` MCP table grow by one row.
- `list_scrolls`'s `limit` makes its output bounded where `scrolls list`'s
  is not — a deliberate, documented divergence, not an inconsistency. An
  agent that needs the whole library raises `limit` explicitly.
- The summary dict is built in both `_cmd_list` and `list_scrolls`; the
  small duplication matches how the repo already inlines summary shaping
  per surface (search hits, list rows), kept over a cross-module helper.

## Proof

`tests/test_mcp.py`: `test_list_scrolls_browses_by_facet` (the summary
shape, the facet AND including tag membership, the empty-string
unclassified pool, and the limit), `test_list_scrolls_before_init_returns_empty`
(empty-library safety), and `test_server_exposes_exactly_the_documented_tools`
(the tool joins the surface). 1400 passing.
