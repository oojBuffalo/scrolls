# 0080: `scrolls facets` — the filterable vocabulary, the browse half of search

Date: 2026-06-13
Status: accepted

## Context

ADR 0058 gave `search`/`list`/`context` the `--source`/`--category`/`--stage`
facets and ADR 0059 added the `--tag`/`--concept` membership facets. Together
they let an agent *narrow* the library to a slice. But to narrow by
`--concept full-text-search` an agent must already know that slug exists, that
it is spelled that way, and that anything carries it. Nothing answered "what
can I filter by?".

The pieces existed, scattered and partial. `scrolls status` reports
`by_source` and `by_stage` counts but no category breakdown and no
tags/concepts. `scrolls kb` compiles per-source/category/tag/concept pages, but
those are static Markdown files an agent would have to read and parse, rebuilt
only on a `kb` run. The MCP server's `list_sources` returns source→count — the
sources dimension alone. The genuinely hard-to-discover dimensions — the
free-form **tags** and the slugged **concepts** that `--tag`/`--concept` key
on — had no live, queryable enumeration at all. A faceted search you cannot
introspect is half a feature: the filter exists, but its domain is invisible.

The values also need to be enumerated *the way the filters compare them*, or the
enumeration lies. `--concept` matches by slug (so "BM25" and "bm25" are one
filter), `--tag` matches case-insensitively. A naive `SELECT DISTINCT` over the
JSON arrays would report "BM25" and "bm25" as two separate filterable values
when they are one — the opposite of useful. The KB already groups them
correctly (`kb.group_concepts` by slug, `kb.group_tags` by case-fold, the
smallest spelling the display form); that grouping is the canonical vocabulary.

## Decision

A new `scrolls facets [field]` command (`src/scrolls/facets.py`,
`cli._cmd_facets`) enumerates the filterable vocabulary with per-value item
counts — the **browse** half of the search/browse pair. It is the live,
JSON, agent-native complement to the KB's static facet pages.

- **One command, four dimensions.** `sources`, `categories`, `tags`,
  `concepts` — exactly the filter facets minus `stage` (a fixed three-value
  enum already in `status`, not a discovery problem). With no `field`, every
  dimension is reported in that order; a `field` narrows the payload to one.
  The shape is uniform: `{"facets": {dimension: [{"value", "count", …}, …]}}`.

- **Grouped as the filters compare.** Sources and categories are the scalar
  columns, counted with `GROUP BY`. Tags and concepts reuse
  `kb.group_tags`/`group_concepts` so the enumerated vocabulary is *exactly*
  what `--tag`/`--concept` and the KB pages key on — tags case-folded,
  concepts by slug, the smallest spelling the display form. A concept also
  carries the `slug` you would pass to `--concept`. Counts are **distinct
  items** per group, so two spellings of one concept on one item count it once
  (`len({item.id …})`, not list length — the group helpers append an item once
  per spelling).

- **Unclassified surfaces as `""`.** The `category IS NULL` pool reports as the
  empty-string value, round-trippable straight to `--category ""` the way
  `list`/`search`/`set` already treat it. The data never stores an empty-string
  category, so `""` is unambiguous and directly actionable.

- **Ranked, capped, scoped.** Each dimension is ordered by count descending then
  value ascending (deterministic ties) and capped at `--limit` (default 20,
  matching `search`). The same optional `--source`/`--category`/`--stage`/
  `--tag`/`--concept` facets that scope `search` scope the counts, so
  `scrolls facets concepts --source arxiv` answers "which concepts do my arXiv
  papers carry?".

- **One filter builder.** The scalar+membership filter clause builder, formerly
  `search._filters`, is promoted to a public `items.item_filters` and shared by
  `search` and `facets` — the `items.`-qualified clauses correlate equally in a
  bare `FROM items` query and the FTS join. `list_items`' own inline copy is
  left untouched (independently tested, unqualified) and noted as a future
  consolidation rather than churned in this slice.

- **An uninitialized library is honest, not an error.** Every dimension reports
  `[]` with a stable shape (the `list`/`status` posture), exit 0.

The array dimensions load only `id`, `tags`, `concepts` for the filtered set
(not the heavy text columns `list_items` would pull) and group in Python, so the
canonical normalization is reused rather than re-implemented as SQL `json_each`
unnest with slug functions — correctness by construction at personal-KB scale.

## Consequences

The faceted search introduced by ADR 0058/0059 is now self-describing: an agent
(or a person) can discover the categories, tags, and concept slugs the library
actually holds, then filter by them, in two calls. `scrolls facets` is exposed
over MCP as `list_facets` for the same reason `list_scrolls` exists beside
`search_scrolls` (ADR 0060) — browse and search are a pair, and an agent needs
both. The category breakdown `status` lacked is now available; `list_sources`
on MCP is subsumed by the richer `list_facets` but kept for compatibility.

Deferred: a `--stage` dimension (the enum is already discoverable); per-value
example items (that is what a scoped `list` is for); and the `list_items` filter
consolidation (a mechanical refactor better done on its own).

## Alternatives considered

- **Four separate commands** (`scrolls tags`, `scrolls concepts`, …). More
  surface for the same capability, and an agent wanting the whole vocabulary
  would make four calls. One command with an optional `field` covers both the
  whole-library and single-dimension questions.
- **Reading the KB facet pages.** They already group correctly, but they are
  Markdown to parse, rebuilt only on `kb`, and carry prose an agent must strip.
  A live JSON query is the agent-native form; the KB pages remain the
  human-browsable form.
- **`SELECT DISTINCT` in SQL.** Would split slug/case-fold equivalents into
  separate filterable values, contradicting how the filters match. Reusing the
  KB grouping keeps the enumeration and the filter in agreement.
