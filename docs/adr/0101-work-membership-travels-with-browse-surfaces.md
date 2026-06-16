# 0101: Work membership travels with the browse surfaces

Date: 2026-06-15

Status: accepted

## Context

`scrolls works` (ADR 0069) clusters the library's items into scholarly
**works** by shared DOI — an arXiv preprint, its published Crossref record, and
a PubMed index of the same paper are one work — and ADR 0095 picks each work's
**canonical** representation (the published record over a preprint). ADR 0072
added the per-item lens (`scrolls works --ref <id>`: "what work is this, and
what siblings are saved?"), and ADR 0096 let `scrolls related` score a same-work
edge. The works model is mature.

But it was a *destination*, not a property an agent encountered in passing. An
agent rarely runs `scrolls works`; it **searches** ("what does my library know
about attention?") or **lists** a facet. On those surfaces the two
representations of one work came back as two unrelated hits — `arxiv:1706.03762`
and `crossref:10.5555/3295222`, same title, no signal they are the same work and
no pointer to which form is canonical. The agent treats them as two findings,
double-counts the evidence, and has no basis to prefer the published record.

That is the gap the vision names three times over:

- **Capability 1 (Deep Works Merge & Canonical Items):** "Source pages and
  search results show the canonical item." Search did not.
- **Capability 3 (Evidence Clustering & Deduplication):** duplicate
  representations should collapse *at the point an agent consumes results*, not
  only in a separate command it must know to call.
- **Capability 4 (MCP + Search + List Consistency):** "No drift." The same two
  items clustered into one work under `scrolls works` but read as unrelated
  under `scrolls search` / `scrolls list`.

This is the exact shape ADR 0100 closed for custody **fidelity** ("fidelity
travels with every browse surface"): a derived, library-wide property that an
agent needs *while browsing*, not only when it asks for it directly. Work
membership is the same kind of property, so it travels the same way.

## Decision

**A browse hit carries the scholarly work(s) it represents.** A new compact
`works.WorkRef` is the single-item view of the `Work` cluster — `doi`, canonical
`url`, the `canonical` representation's id, whether *this* item `is_canonical`,
and the `representations` count — deliberately smaller than `Work` (no full
representation list): enough for an agent to collapse a duplicate and follow the
canonical, without re-deriving the clustering. An agent that wants the full set
still asks `scrolls works --ref <id>` / `get_works(item=…)`.

**One clustering, inverted to a per-item index.** `works.work_membership(items)`
runs the same `works_over` DOI clustering and inverts it to `{item_id:
(WorkRef, …)}`, so search and list share one definition rather than each
re-deriving the grouping. An item appears only when it belongs to a work with
≥2 representations (the `works_over` default); callers default a missing id to
an empty tuple — "not a known duplicate of anything saved." An item that names
two DOIs maps to two `WorkRef`s, mirroring `works_for_item`'s list.

**Membership is a whole-library property, computed over every item — not the
rows shown.** A search returns a thin ranked slice; a `list --source arxiv`
hides the Crossref sibling. Clustering over only those rows would undercount an
item's representations or miss its work entirely. So both surfaces cluster over
the full `list_items(db_path)` and then annotate the rows they display:

- `SearchHit` gains a `works: tuple[WorkRef, …]` field. `search_items` builds
  the membership index once *after* the FTS query returns hits (and only when
  there are hits to annotate), then attaches each hit's memberships. The cost
  mirrors `scrolls works` itself, which `list_items` the library the same way;
  it is paid only on a non-empty search.
- `item_summary` gains a `works` parameter (the JSON the caller builds with
  `works.membership_payload`). It is passed in, not derived inside `items.py`,
  so that low-level module stays free of the `works` clustering — which itself
  reads items — and so a `list` over the whole library clusters once, not per
  row. `scrolls list` and MCP `list_scrolls` compute the index over the full
  library and annotate the (possibly filtered) rows they print.

`membership_payload` is the one shape the `works` field takes across every
surface, the same single-definition discipline `item_summary` already keeps for
the rest of a summary row. The CLI gets it for free (`dataclasses.asdict` on
`SearchHit`, the payload builder on `list`); MCP `search_scrolls` /
`list_scrolls` emit the identical field.

## Consequences

- `scrolls search` / `search_scrolls` and `scrolls list` / `list_scrolls` each
  carry a `works` list on every hit / summary, identical in shape and source to
  the clustering `scrolls works` reports. When two hits are the same work, each
  names the work's DOI and canonical form, so an agent collapses the duplicate
  and follows the canonical instead of treating them as unrelated matches —
  closing the "search results show the canonical item" gap (capability 1) and
  the search/list/MCP drift for this dimension (capability 4).
- Membership travels with the two enumeration surfaces alongside `fidelity`
  (ADR 0100): an agent browsing or searching now sees, per item, both *how much
  of it the library holds* and *which work it is a representation of*, with no
  follow-up call.
- The clustering has one home (`work_membership` → `works_over`); search and
  list cannot drift in how they group representations or pick a canonical.
- Cost: a non-empty search now also `list_items` the library to build the index
  — the same whole-library read `scrolls works`, `scrolls graph`, and `scrolls
  related` already perform, acceptable for a local-first personal library and
  paid only when there are hits. A leaner DOI-only projection is a future option
  if a very large library makes it matter; it is deferred to avoid forking the
  clustering definition (vision rule 6, *simplicity compounds*).
- The browse contract grew by one key. `item_summary` is now nine keys
  (`…`, `fidelity`, `works`); the search hit shape gains `works`. Existing shape
  assertions in `tests/test_cli.py`, `tests/test_mcp.py`, and
  `tests/test_fidelity.py` are updated to pin the new key.
- Verified offline: `tests/test_works.py` (`work_membership` maps each
  representation to its work and canonical, omits single-representation and
  DOI-less items, indexes an item into each of its works; `membership_payload`
  shape; CLI `list`/`search` annotation incl. survival through a facet filter),
  `tests/test_search.py` (works travel with ranked hits, a lone hit carries
  none, membership spans beyond the matched rows), and `tests/test_mcp.py` (both
  MCP browse surfaces carry membership).
