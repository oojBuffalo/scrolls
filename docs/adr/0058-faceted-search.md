# ADR 0058: `scrolls search` gains source/category/stage facets

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

The library now spans 30+ heterogeneous sources — papers (`arxiv`,
`crossref`), code hosts (`github`, `gitlab`, `gitea`, `bitbucket`),
package registries (`pypi`, `npm`, `crates`, …), forums and social posts
(`hackernews`, `lobsters`, `mastodon`, `bluesky`, `lemmy`, `discourse`,
…). The adapters made the library *heterogeneous*; the consumption side
never caught up. `scrolls search` ran a flat FTS5/BM25 match with no way
to scope it, so "what *papers* does my library know about transformers"
or "which *unclassified* items mention SQLite" was unanswerable — an
agent got every source mixed together and had to post-filter the JSON
itself.

`scrolls list` already filters the full item set by `--source`,
`--stage`, and `--category` (with the empty-string-selects-unclassified
convention shared with `scrolls set`). The asymmetry was the gap: `list`
filters but doesn't rank, `search` ranks but doesn't filter. Neither
alone answers a scoped relevance question over a large multi-source
library.

## Decision

1. **`search_items` takes optional `source`/`category`/`stage` facets.**
   They AND with the FTS match and leave the BM25 ordering untouched —
   filters narrow the candidate set, they never reorder it. `None` (the
   default for all three) never filters, so every existing caller is
   unchanged.
2. **Mirror `list_items`' semantics exactly.** `source` and `stage`
   match the indexed column exactly; `category` matches exactly except
   the empty string, which selects `category IS NULL` — the
   batch-classifiable pool, the same convention `list` and `set` use. No
   new vocabulary, no second mental model.
3. **Filter on the joined `items` columns, not the FTS table.** The
   search query already joins `items` on `items_fts.rowid`, so
   `items.source`/`items.category`/`items.stage` are in scope; the facet
   clauses append to the existing `WHERE items_fts MATCH ?` with their
   params ordered between the match and the `LIMIT`. The FTS index stays
   text-only — facets are structured metadata, not tokens.
4. **Wire the facets through every search surface.** The CLI `search`
   command gains `--source`/`--category`/`--stage` (stage with the same
   `detected`/`fetched`/`rendered` choices `list` offers), and the MCP
   `search_scrolls` tool gains the three optional parameters so a
   protocol agent can scope a search the same way — the primary payoff,
   since agents are the intended consumer of a scoped ranked match. The
   context bundle (`scrolls context`/`get_context_bundle`) builds on the
   same `search_items`, so it takes the identical facets and threads them
   straight through: scoping the bundle's ranked match also scopes the
   connected-scrolls graph that hangs off it. A scoped bundle names its
   active facets in the title (`category=unclassified` for the empty-string
   pool) so it stays self-documenting once dropped into model context —
   the one piece of presentation the bundle adds over the JSON `search`.
5. **No `tags`/`concepts` facets yet.** Those are JSON multi-value
   columns, a different (membership) query than the single-column
   equality the three facets share; deferred until a concrete need,
   to keep this slice to the columns `list` already exposes.

## Consequences

- The agent-facing question "papers about X", "this source's take on Y",
  "unclassified items mentioning Z" is now one call on either surface —
  the heterogeneity the adapters built becomes navigable, not just
  searchable.
- A facet that excludes every hit returns `[]`, never an error — the same
  empty-result posture as a query with no matches; an invalid `--stage`
  is rejected by argparse choices at the CLI, while `search_items`/MCP
  stay permissive (an unknown stage simply matches nothing, like
  `list_items`).
- The empty-string `--category` overloads "no value" to mean
  "unclassified", inherited from `list`/`set`; it is the one non-obvious
  spelling, documented on the flag and in `docs/cli.md`.
- Ranking is unchanged: facets are a pre-filter, so relevance within a
  scope is identical to relevance in the whole library.

## Proof

`tests/test_search.py` (`test_search_filters_by_source`,
`test_search_filters_by_category`,
`test_search_empty_category_selects_unclassified`,
`test_search_filters_by_stage`, `test_search_filters_combine_with_and`,
`test_search_filters_can_exclude_every_hit`,
`test_search_filters_compose_with_limit`,
`test_search_blank_query_still_rejected_with_filters`), the CLI path in
`tests/test_cli.py` (`test_search_filters_by_source_and_category`), and
the MCP tool in `tests/test_mcp.py`
(`test_search_scrolls_honors_facets`). The context bundle inherits the
facets in `tests/test_context.py`
(`test_context_facets_scope_the_bundle`,
`test_context_unclassified_facet_uses_a_clear_scope_note`,
`test_context_facet_with_no_matches_keeps_the_scope_note`) and over MCP in
`tests/test_mcp.py` (`test_get_context_bundle_honors_facets`). 1388
passing.
