# 0096: `scrolls related` scores a same-work edge

Date: 2026-06-15

Status: accepted

## Context

`scrolls related <id>` ranks the library
by explainable signals — link edges (5 points per direction), shared concepts
(3 each), shared tags (2 each), same category/domain (1 each) — each carrying a
human-readable reason. Its link edges resolve through the same primitives
`scrolls graph` uses, so the two views agree on what a link points at.

But both views inherit the same blind spot, the one `works.py`
(ADR [0069](0069-works-by-doi.md)) was built to name: two representations of the
*same scholarly work* — an arXiv preprint and its published article, an indexing
record — that both carry `doi.org/D` but with **no Crossref hub item present**
share no realized link edge. Neither item's identity *is* the DOI, so each
link resolves to a URL token no item owns, and `related` returned nothing for a
pair that is literally the same work. When the hub *is* present `related`
already binds them (the preprint's link resolves to the Crossref item's URL),
so the gap was exactly the hub-absent case — the case `works` clustering exists
to catch.

The vision lists same-work edges and evidence clustering as priorities, and
ADR [0095](0095-canonical-representation.md) had just made the work model's
DOI-identity a first-class, reusable notion.

## Decision

Add a **same-work** signal to `find_related`, worth `_WORK_POINTS = 6` per
shared DOI — one notch above a single link direction.

- Two items are siblings of one work when they share a DOI, computed with the
  same rule the clustering uses: `works.item_dois` (promoted from a private
  helper to public so the one DOI-extraction definition is reused, not copied).
- The reason reads `same work: https://doi.org/<doi>` for each shared DOI.
- 6 > 5 (a one-way link), so a same-work sibling outranks a mere citation:
  identity is a stronger signal than "one points at the other".
- When the binding hub *is* present, a genuine pair scores **both** the
  same-work edge and the link edge. These are complementary facts — *these are
  the same work* and *one points at the other* — not double counting.

## Consequences

- `related` now catches same-work siblings the link graph cannot, closing the
  gap between the per-item `related` view and the `works` lens — the
  `related`↔`works_for_item` symmetry (ADR [0072](0072-works-per-item-lens.md))
  made concrete in ranking.
- The MCP `get_related_scrolls` tool surfaces the new signal for free (same
  engine); its docstring names same-work as the strongest signal.
- `related.py` now imports `works.py` (`item_dois`, `DOI_RESOLVER`). No cycle:
  `works` imports neither `related` nor `graph`.
- Ranking can reorder for DOI-sharing items; no test pinned exact scores, and
  the hub-present case keeps its existing link reason, so existing behavior is
  preserved where it existed and only extended where it was blank.
- Deterministic and offline; no schema, DB, or payload-shape change (the hit
  shape already carried `reasons`).
