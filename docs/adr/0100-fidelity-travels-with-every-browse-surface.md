# 0100: Custody fidelity travels with every browse surface

Date: 2026-06-15

Status: accepted

## Context

The custody integrity audit (ADR 0097) made **fidelity** — `full` / `partial` /
`reference`, the tier at which the library still holds an item — a first-class,
network-free, derived property. It surfaced in three places: `scrolls doctor`'s
custody report, the `fidelity` facet, and the browse summary shared by
`scrolls list` and the MCP `list_scrolls` (commit 38abf1b, "custody fidelity
travels with browse results").

But an agent rarely *lists* its way to an item. It **searches** ("what does my
library know about X?") or **follows a related edge** ("what else belongs next
to this?"). Those two surfaces — `scrolls search` / MCP `search_scrolls` and
`scrolls related` / MCP `get_related_scrolls` — returned a hit with no fidelity
tier at all. So the same item read as `reference` when browsed by facet or list,
and as an unlabeled hit when reached by search or related discovery. That is the
exact drift the vision forbids (capability 4, *MCP + Search + List Consistency*:
"MCP tools, CLI search/list, and library pages all use the same filters, facets,
ranking, and pagination semantics. No drift."), and it undercuts capability 2
(*Explainable Ranking & Confidence*): a search result that says *what* matched
but not *at what fidelity the library holds it* hides the one custody fact an
agent needs before trusting the hit.

The blocker was cost, not concept. `get_fidelity` takes a whole `ScrollItem`;
deriving it for search hits naively means hauling each match's `raw_text` /
`extracted_text` (a paper or article body is multi-kilobyte) out of SQLite only
to test whether it is non-empty. `related` already loads full items, so it pays
nothing extra; `search` selects a deliberately thin row.

## Decision

**Express the tier rule over presence flags, not the whole item.** A new
`items.fidelity_tier(*, has_raw, has_extracted, has_summary, has_hash, stage)`
is the decision `get_fidelity` makes, lifted to four booleans plus the stage.
`get_fidelity(item)` becomes the convenience wrapper that reads those booleans
off the item — the rule now has exactly one home, callable either way.

**Fidelity travels with search and related, derived the cheap way each surface
affords:**

- `SearchHit` gains a `fidelity` field. The FTS query selects four `has_*`
  presence booleans (`raw_text IS NOT NULL AND raw_text != ''`, …) alongside the
  ranked columns — never the body text itself — and folds them through
  `fidelity_tier`. A search row moves no body bytes it does not already need for
  the snippet.
- `RelatedHit` gains a `fidelity` field, derived with `get_fidelity(other)`
  directly, because `find_related` already holds the full neighbour item.

Both fields propagate to the CLI (`dataclasses.asdict`) and MCP outputs for free.

**Fold the facet onto the same primitive.** `facets._fidelity_counts` no longer
reconstructs a lightweight `ScrollItem` per row (the `_load_fidelity_columns`
helper ADR 0097 introduced); it selects the same four presence booleans and
counts `fidelity_tier` directly. This deletes the text-hauling reconstruction
*and* the footgun ADR 0097 warned about — loading the wrong columns is what once
made every item read `reference`; presence flags computed in SQL cannot repeat
it. Behavior is byte-for-byte unchanged (the existing facet tests pin it).

## Consequences

- `scrolls search` / `search_scrolls` and `scrolls related` /
  `get_related_scrolls` each carry a `fidelity` tier on every hit, identical to
  the tier `scrolls list`, the facet, and `doctor` report. Fidelity now travels
  with **every** way an agent reaches an item — list, search, related — closing
  the search/list/MCP consistency gap for this dimension.
- The tier rule lives in one function (`fidelity_tier`); `get_fidelity`, search,
  and the facet all delegate to it, so the three surfaces cannot drift in how
  they classify a tier.
- Search derives the tier without moving body text: the query asks SQLite for
  presence booleans, so a 20-hit search over a library of multi-kilobyte
  articles reads four ints per row, not four bodies.
- ADR 0097's `_load_fidelity_columns` is removed; its job is now done by presence
  flags in `_fidelity_counts`. The fidelity facet's observable output is
  unchanged.
- Verified offline: `tests/test_search.py` (each tier on a ranked hit, and that
  a hit's tier equals `get_fidelity` of the same stored item),
  `tests/test_related.py` (the neighbour's tier on the hit + the CLI surface),
  `tests/test_fidelity.py` (`fidelity_tier` agrees with `get_fidelity` across
  every presence/stage combination), and the existing facet/list shape tests in
  `tests/test_facets.py` / `tests/test_cli.py` / `tests/test_mcp.py`.
