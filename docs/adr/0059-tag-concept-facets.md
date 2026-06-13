# ADR 0059: `search`/`list`/`context` gain tag/concept membership facets

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

ADR 0058 gave `scrolls search` (and, through `build_context`, `scrolls
context`) the `source`/`category`/`stage` facets `scrolls list` already
had, so an agent could ask "what *papers* mention transformers" over a
30+ source library. It deliberately stopped there: §5 deferred
`tags`/`concepts` because they are JSON multi-value columns — a
*membership* query, not the single-column equality the other three share.

That deferral left a real gap. `tags` and `concepts` are the library's
finest-grained structured signal: arXiv taxonomy names, github/gitlab
repo topics, package keywords, wikipedia page categories, the LLM
classifier's concepts, and anything a user pins with `scrolls set`. The
KB compiles a page per concept, `scrolls related` scores shared
tags/concepts, and the link graph hangs off them — but a consumer could
not *filter* by them. "Papers about transformers tagged efficient" or
"everything carrying the BM25 concept" was unanswerable; an agent got
every tag mixed together and post-filtered the JSON itself, the exact
asymmetry ADR 0058 set out to close, one level deeper.

## Decision

1. **Add `tag` and `concept` membership facets to `search_items`,
   `list_items`, and `build_context`.** They AND with the existing facets
   and with the FTS match, and (in search) leave the BM25 order untouched
   — facets pre-filter, they never reorder. `None` (the default) never
   filters, so every existing caller is unchanged. Adding them to all
   three surfaces — not just the two ADR 0058 touched — keeps the
   symmetry that ADR's whole premise rested on: `list` filters, `search`
   ranks-and-filters, `context` bundles, all by the same facet set.

2. **Match exactly as the rest of the system already compares these
   fields.** `tag` is **case-insensitive** and `concept` is **by slug** —
   the precise comparisons `scrolls related` uses and the KB concept
   pages and the MCP `get_concept_page` tool use. So `--concept "full
   text search"` finds an item whose concept is `Full-text search`, and
   `--tag CS.DB` finds `cs.DB`. No new vocabulary, no second mental model:
   a facet means what a concept/tag already means everywhere else.

3. **No empty-string overload.** `category`'s `""`-means-unclassified
   convention exists because "no category" is a meaningful, queryable
   state. There is no established "untagged"/"no concept" pool, so
   `tag`/`concept` do not overload the empty string: `None` never filters,
   a value filters by membership, and a value nothing carries returns
   `[]` (the same empty-result posture as any over-narrow facet). The
   context scope note reports `tag`/`concept` verbatim, with no
   `unclassified` rewrite.

4. **Single value per facet.** Each facet takes one value, AND-ed with
   the others — the exact shape of `source`/`category`/`stage`. Combining
   facets across columns (`--source arxiv --concept transformers --tag
   efficient`) already covers the common need; repeated-flag AND *within*
   one facet ("tagged both rust and async") is a richer query deferred
   until a concrete need, keeping this slice to one `EXISTS` clause per
   facet.

5. **Filter in SQL via `json_each`, normalized by registered functions.**
   The clause is `EXISTS (SELECT 1 FROM json_each(items.tags) WHERE
   scrolls_lower(json_each.value) = ?)` for tags and the `scrolls_slug`
   analog for concepts, with the parameter normalized the same way in
   Python. SQL-side filtering (not a Python post-filter) keeps `search`'s
   `LIMIT` correct — a post-filter after the limit would drop hits and
   under-return. The two SQL functions are registered per connection
   (`items.register_facet_functions`): `scrolls_slug` wraps `render.slugify`,
   and `scrolls_lower` wraps Python's `str.lower` because SQLite's
   built-in `lower()` is ASCII-only — registering `str.lower` keeps the
   indexed column value and the Python-lowered parameter in agreement for
   a non-ASCII tag. The clause builder (`items.tag_concept_filters`)
   references `items.tags`/`items.concepts`, so it correlates equally in
   `list_items`' `SELECT * FROM items` and `search_items`' join, and is
   shared by both rather than duplicated (`slugify` is imported lazily
   inside it because `render` imports `items` at module load).

6. **Wire through every facet surface.** The CLI `search`, `list`, and
   `context` commands gain `--tag`/`--concept`, and the MCP `search_scrolls`
   and `get_context_bundle` tools gain `tag`/`concept` parameters — the
   agent payoff, since a protocol agent is the intended consumer of a
   scoped, ranked, membership-filtered match.

## Consequences

- The finest-grained structured signal the adapters and classifier
  produce is now a filter, on every consumption surface: "papers tagged
  efficient about X", "items carrying the BM25 concept", in one call.
- A facet that excludes every hit returns `[]`/`No matching scrolls.`,
  never an error — the ADR 0058 posture. An item with no tags/concepts
  (stored as `[]`) yields no `json_each` rows, so it can never match a
  membership facet — correct by construction.
- `tag`/`concept` use slug/case-insensitive matching while
  `source`/`category`/`stage` use exact equality. The difference is
  intentional and inherited (it is how `related`/KB already treat each
  field), but it is one more thing a reader must know; it is documented on
  the flags and in `docs/cli.md`.
- Two SQL functions are now registered on every `list_items`/`search_items`
  connection, even when no membership facet is active. The cost is
  negligible (two `create_function` calls) and keeps the connection
  uniform; the alternative — registering only when a facet is present —
  bought nothing.
- Repeated-flag AND within a facet and an "untagged" pool stay deferred,
  as multi-value (membership) facets are deferred no further than needed.

## Proof

`tests/test_search.py` (`test_search_filters_by_tag`,
`test_search_filters_by_concept`,
`test_search_tag_and_concept_combine_with_other_facets`,
`test_search_tag_filter_excludes_items_without_the_tag`),
`tests/test_items.py` (`test_list_items_filters_by_tag`,
`test_list_items_filters_by_concept`,
`test_list_items_tag_and_concept_combine_with_other_filters`), the CLI
path in `tests/test_cli.py`
(`test_search_and_list_filter_by_tag_and_concept`), the context bundle in
`tests/test_context.py`
(`test_context_tag_and_concept_facets_scope_the_bundle`), and both MCP
tools in `tests/test_mcp.py`
(`test_search_and_bundle_honor_tag_and_concept_facets`). 1398 passing.
