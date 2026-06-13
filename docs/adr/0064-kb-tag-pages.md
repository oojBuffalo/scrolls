# 0064: Tag pages in the compiled library — the facet the KB could query but not browse

Date: 2026-06-13

Status: accepted

## Context

`tags` is a first-class field on every `ScrollItem` and a first-class
*query* facet: `scrolls search`/`list`/`context` all take `--tag`, matching
case-insensitively (ADR 0059), and the MCP tools expose it too. Adapters
fill it with structured metadata that is not quite a *concept* (an idea) but
is real, browsable grouping signal — arXiv taxonomy codes (`cs.CL`), SPDX
licenses (`MIT`, `Apache-2.0`), a Bitbucket repo's `language`, a Crossref
work's `type` and venue, PyPI/crates classifiers, and browser-bookmark folder
ancestry.

But the *compiled* library (`kb.py`, ADR 0005) gave tags no page. It rolled
rendered scrolls up into `index.md`, `graph.md`, and per-`source`,
per-`category`, and per-`concept` pages — every other grouping the data
carries — while tags were the one first-class facet you could filter by yet
not browse. An agent could ask `scrolls list --tag MIT` but could not open a
page listing the library's MIT-licensed items, the way it could open
`concepts/bm25.md` or `categories/paper.md`. ADR 0063 flagged this gap when it
added Related Concepts: "a possible shared-*tag* page section remains open".

## Decision

Compile a `tags/` page per tag, mirroring concept pages, plus a `## Tags`
index section and a per-page `## Related Tags` co-occurrence list.

- **`kb.group_tags(items)`** is the tag analog of `group_concepts`, but groups
  **case-insensitively** (`tag.lower()` is the key) rather than by slug —
  exactly the `--tag` facet's rule (ADR 0059), so the page set and the query
  facet agree on what one tag is. The smallest spelling is the display form, as
  with concepts. `MIT` and `mit` are therefore one page; `C++` and `C#` stay
  two, even though both slugify to `c`.

- **Filenames disambiguate slug collisions.** Concept pages key *by* slug, so
  `concepts/<slug>.md` is collision-free by construction. Tags key by case-fold,
  so distinct groups can share a slug (`C++`, `C#`, and `C` all slugify to `c`).
  `kb._tag_filenames` assigns each group a `tags/<name>.md` stem — the slug, with
  a numeric suffix (`c-2`, `c-3`) for collisions, in sorted-key order. KB pages
  are rebuilt from scratch each run and link relatively (the rest of the tree's
  rule), so a deterministic-per-run name is enough; tag-page filenames are
  addressable but not globally stable, and consumers that need a stable handle
  use the item id or URL, never a KB page path.

- **The page** reuses the shared `_write_page`: `# Tag: <display>`, the member
  count, one bullet per member (sorted by case-folded title, the item's `source`
  as the note — the concept-page convention), and a `## Related Tags` trailer.

- **Related Tags** is the tag analog of ADR 0063's Related Concepts, computed by
  the same co-occurrence core (`_co_occurring`, now shared by `related_concepts`
  and the new `related_tags`): the tags that share a scroll with this one, ranked
  by shared-scroll count, capped at 10, omitted when none. It lives on the tag
  page, **not** as edges in `scrolls graph`, for the same density reason concept
  edges do (ADR 0044/0047/0062): tag co-occurrence forms cliques that would swamp
  the sparse, high-signal link edges.

- **The index** gains a `## Tags` section after `## Concepts`, linking each tag's
  page with its scroll count, and `KbResult` gains a `tags` count that flows to
  `scrolls kb` and the MCP `compile_library` through the existing `asdict`.

## Consequences

- The library is now browsable along every grouping its data carries: source,
  category, concept, **tag**, and the link graph. The `--tag` query facet and the
  `tags/` pages share one notion of a tag (case-fold), so an agent that filters by
  a tag and one that browses to its page see the same membership. The MCP
  `get_concept_page` tool reads concept pages; a tag page is just a file under
  `library/tags/`, reachable by any consumer that walks the tree, with no new tool
  needed this slice (a `get_tag_page` tool is the obvious follow-up).

- It is deterministic and offline — a rollup of `tags` the pipeline already
  stored, like every other plain `scrolls kb` page; the compiler still never calls
  a model.

- This closes the *tag* half of ADR 0063's deferral. Tags and concepts are now
  symmetric in the compiled library (page + co-occurrence section), even though
  they merge by different rules (case-fold vs slug) because their query facets do.

- The cap is a silent top-N, like Related Concepts: a hub tag's weakest
  co-occurrences drop alphabetically past the tenth. The page filenames are not
  stable across runs when slugs collide — acceptable because the whole `library/`
  tree is regenerated each run and never a durable external handle.

- Tags can be noisy and high-cardinality (a PyPI package's trove classifiers, a
  large bookmark import's folder names), so a library may now compile many small
  tag pages. This matches concept pages' existing behaviour (one page per github
  topic, hashtag, taxonomy name) and is the honest cost of making the facet
  browsable; a future minimum-member threshold or an LLM tag-synthesis pass could
  trim it, mirroring the concept engine (ADR 0025).
