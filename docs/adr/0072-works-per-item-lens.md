# 0072: `scrolls works <ref>` — the per-item works lens

Date: 2026-06-13

Status: accepted

## Context

`scrolls works` (ADR [0069](0069-works-by-doi.md)) clusters the whole
library's items into scholarly works keyed by the DOI that names them, and
`library/works.md` (ADR [0070](0070-kb-works-page.md)) plus the category-page
consolidation (ADR [0071](0071-kb-category-work-consolidation.md)) surface
that clustering for browsing. All three are *whole-library* views: "what
works does my library hold more than one representation of?"

The link graph has the same two-view shape, and it is filled on both sides:
`scrolls graph` (ADR [0044](0044-link-graph-command.md)) is the whole-library link
structure, and `scrolls related <id>` is the *per-item* lens — "what is
connected to **this** item?". Works had only the whole-library side. An
agent that found one representation of a work — an arXiv preprint surfaced
by `scrolls search`, a scroll it is reading — had no direct way to ask "what
work is this, and which *sibling* representations (the published article,
the PubMed record) are also saved?". It would have to run whole-library
`scrolls works` and scan every cluster for the id, or walk `scrolls related`
and infer the DOI edges. The per-item question deserved a per-item command.

`works.works_over(items)` already clusters a given item set; the per-item
view is a filter of that clustering to the works one item participates in.

## Decision

Add a per-item form, `scrolls works <ref>`, and an `item` argument to the
MCP `get_works` tool, both backed by a new `works.works_for_item(items,
item_id)`.

- **`works_for_item`** resolves the item, reads the DOIs it carries (its
  `source_id` DOI or its `doi.org` links — the same `_item_dois` the
  whole-library clustering uses), and returns the works keyed by those DOIs,
  clustered over the whole given item set, with **every** representation
  (the target included). It raises `ValueError("no such item: <id>")` for an
  absent item, mirroring `find_related`.

- **No 2+ floor in the per-item form.** Where whole-library `works`
  defaults to `min_representations=2` (a single-representation work is just
  a paper, not worth listing among thousands), the per-item form reports the
  item's work **even with one representation — just the item itself**. The
  question is "what siblings does *this* item have?", and "none saved" is a
  useful, explicit answer, not an empty result. So the item form forces
  `min 1` and `--min` is ignored with a `ref` (documented in the command
  help and `docs/cli.md`). An item that names no DOI yields no works.

- **`ref` is an id or URL.** Resolved through `pipeline.resolve_item_id`,
  the same normalize→detect→mint chain every id-taking command accepts
  (ADR [0028](0028-item-refs-accept-urls.md)), so the saved URL is a valid
  handle. The CLI emits the same `{works, stats}` payload as the
  whole-library form (`stats.items` stays the library total), and an unknown
  item is a JSON error on stderr, exit 1; the MCP tool raises (a tool
  error), as its other read tools do for an unknown id.

## Consequences

- **The works feature now has both views, like the link graph.** `scrolls
  works` / `get_works()` is the whole-library lens, `scrolls works <ref>` /
  `get_works(item=...)` the per-item one — the `scrolls graph` ↔ `scrolls
  related` symmetry, applied to the DOI clustering. An agent reading a
  scroll, or holding a search hit's id, can ask directly which other
  representations of the same work are saved.

- **One clustering, four surfaces.** `works_for_item` is a filter over
  `works_over`, so the per-item lens, the whole-library command, the
  `library/works.md` page, and the category-page consolidation all agree on
  what a work is and which representations it has. No new resolution path,
  no schema change; pure, deterministic, offline.

- **The min-semantics split is deliberate and local.** The whole-library
  form filters to multi-representation works (signal among many items); the
  per-item form does not (the one item is already the focus). This is the
  only behavioural difference between the two forms, and it falls out of the
  different questions they answer — documented where each is described.

- **Deferred (unchanged from ADR 0069/0071):** the deeper merge of the
  scrolls themselves (collapsing a work's per-representation rows into one
  canonical item) and title-fuzzy matching for DOI-less duplicates. This ADR
  adds a *lens*, not a merge.
