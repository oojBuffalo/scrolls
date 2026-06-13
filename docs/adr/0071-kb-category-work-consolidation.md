# 0071: Category pages consolidate a work's representations

Date: 2026-06-13

Status: accepted

## Context

The library now reaches one scholarly work through as many as four paper
sources — an arXiv preprint (ADR [0008](0008-arxiv-adapter-atom-abstracts.md)),
its published Crossref article (ADR [0037](0037-crossref-doi-adapter.md)), a
PubMed record (ADR [0065](0065-pubmed-adapter.md)), a bioRxiv/medRxiv
preprint (ADR [0068](0068-biorxiv-medrxiv-adapter.md)) — each its own item,
scroll, and search hit. `scrolls works` (ADR [0069](0069-works-by-doi.md))
clusters those representations by the DOI that names the work, and
`library/works.md` (ADR [0070](0070-kb-works-page.md)) makes the clustering
a browsable KB page. Both ADRs closed by naming the same deferred step:
the heavier **merge** — "collapsing a work's near-duplicate `paper` entries
so the category/source pages show one consolidated entry rather than
several" (architecture.md's standing next step; ADR 0070's "merge the
near-duplicate `paper` entries into one").

The duplication is *visible on the category page*. A work's representations
share a **category** (`paper`) but span **sources** (arxiv, crossref,
pubmed), so `categories/paper.md` lists the same work three times as three
flat bullets, while each `sources/<name>.md` page shows only its one
representation. An agent or human browsing `categories/paper.md` reads the
Transformer paper three times with no signal they are one work — exactly
the redundancy `scrolls works` was built to name, now bleeding into the
compiled library's most-read group page.

`works.works_over(items)` (ADR 0069) already clusters a *given* item set by
shared DOI and returns only multi-representation works — the same seam that
let `library/works.md` reuse the clustering over rendered items (ADR 0070).
A category page is just another item set.

## Decision

Consolidate each multi-representation work on **category pages** in
`kb.compile_kb`, reusing `works.works_over` over the page's own members.

- **The rendering.** A category page runs `works_over(members)` over its
  members. Each returned work (2+ representations *among these members*)
  renders as one consolidated entry: a **bold work heading** carrying the
  work's title, an `N representations` count, and the work's `doi.org`
  resolver link — then
  each representation as a **nested** bullet linking to its scroll, noted by
  source (the same `_item_line` the flat list uses, indented two spaces).
  The heading is bold text, not a link: the abstract work owns no scroll of
  its own; its manifestations do, and they are the nested bullets. The
  heading's title is the work's **canonical** representation — the
  highest-ranked paper source (`crossref` > `pubmed` > `biorxiv` >
  `medrxiv` > `arxiv` > `rfc`, ties by id), so the published record's title
  heads the entry. Items in no multi-representation work on the page render
  as ordinary bullets, exactly as before. Works and singletons interleave
  in one case-folded title order (a work by its canonical representation's
  title), preserving the page's alphabetical reading order.

- **The count line is unchanged.** It still reads `N scrolls.` — every
  representation is still a scroll on the page; consolidation groups them,
  it does not remove them. So the count can exceed the number of top-level
  bullets, and the heading's "N representations" makes the grouping legible.

- **Scope: category pages only.** Source pages are single-source, so a
  work's cross-source representations never co-occur there and there is
  nothing to consolidate; concept and tag pages keep every manifestation
  flat (a concept page is about the concept, and its co-occurrence sections
  reason over individual scrolls). The consolidation is threaded through
  `_write_page` as an optional `consolidate_works` map (the rendered
  `items_by_id`), passed only by the category loop.

## Consequences

- **The category page reads as works, not duplicates.** `categories/paper.md`
  now shows one entry per work with its representations nested, the
  long-standing "merge" step in its *presentation* form — the form the
  compiled library wants, since the KB is rebuilt from scratch each run and
  links relatively, so nothing is destroyed and a recompile reflects the
  current library exactly (`test_kb_category_page_consolidates_work_representations`).

- **One clustering definition, three views.** `scrolls works`, `get_works`,
  `library/works.md`, and now the category page all cluster through
  `works.works_over`, so they can never disagree on what a work is. Scoping
  to the page's members (not the whole-library `works` already computed)
  means a work consolidates only when 2+ of its representations are rendered
  *in that category* — a representation the user filed elsewhere by override
  stays separate, correctly (`test_kb_category_page_leaves_single_representation_uncollapsed`).

- **Deterministic, offline, no schema change.** The consolidation is a
  rollup of DOIs the pipeline already stored (`source_id` DOIs and `doi.org`
  links resolved through the same `detect_source`+`normalize_url` path the
  graph and works views use), like every other KB page; the compiler still
  never calls a model or the network. The canonical-source precedence is a
  presentation choice local to `kb.py`, not a new fact about a work.

- **Deferred.** This consolidates the *page*, not the scrolls themselves:
  the per-item scroll files and index rows stay separate, so search,
  `list`, and the source pages still see every representation. A true
  collapse of the scroll/DB rows into one canonical item — and the reverse
  enrichment from richer Crossref `relation` data that would let a single
  consolidated scroll carry all the metadata — remain the heavier open
  steps ADR 0069 named, now narrowed to exactly that. Title-fuzzy matching
  for DOI-less duplicates stays out, as in ADR 0069.
