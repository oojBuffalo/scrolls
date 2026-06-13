# 0047: `scrolls context` surfaces connected scrolls from the link graph

Date: 2026-06-13

Status: accepted

## Context

`scrolls context <query>` is the agent-native surface (IDEAS.md §11): one
compact Markdown bundle an agent drops straight into its window — ranked
keyword matches, capped excerpts, source links. Its ranking is FTS5/BM25
(`search.py`), so the bundle is exactly *what the text says*.

Meanwhile a long run of adapters built a second, orthogonal signal: the
cross-item **link graph**. A saved Hugging Face model points at the arXiv
paper that introduced it (ADR 0041), a preprint at its published DOI
(ADR 0038), a Space at the model it serves (ADR 0043), a package at its
repository (ADRs 0034–0042), a DataCite dataset at its parent work
(ADR 0045). `scrolls graph` (ADR 0044) materializes the whole graph and
`scrolls related <id>` scores one item's neighborhood — but both are
*separate commands*. The edges the adapters invested a dozen ADRs in were
invisible in the bundle an agent actually consumes.

That is a real gap, not a cosmetic one. The two signals are
complementary precisely where it matters: the paper a match points at need
*not* share the match's keywords (a model card about "instruction tuning"
links to a paper titled "Attention Is All You Need"), so FTS can never find
it, yet the library *knows* the connection with high precision. An agent
asking `scrolls context "instruction tuning"` should be told that paper
exists. Today it would have to notice the match's id, run `scrolls related`
on it, and read a second JSON object — work an agent rarely does mid-task.

Three facts shaped the design:

1. **The connection already has one definition.** `graph.build_graph`
   resolves every item's links into directed edges with the same
   source-detecting, raw-and-normalized match `related` uses (ADR 0044).
   Reusing it means the bundle, `scrolls graph`, and `scrolls related` can
   never disagree about what a link resolves to.

2. **Links, not concepts/tags, are the signal worth adding.** `related`
   also scores shared concepts, tags, and category/domain — but those
   overlap heavily with what FTS already surfaces (shared keywords tend to
   co-occur in text) and are noisier (every `tool`-category package weakly
   relates to every other). The *link* edge is the unique, high-precision,
   author-declared connection FTS structurally cannot find. Restricting the
   new section to it keeps the bundle high-signal and compact — the whole
   point of a context bundle (IDEAS.md §11).

3. **A connected scroll is a pointer, not a payload.** A keyword match earns
   an excerpt; a connected scroll earns a one-line "here's why, go look"
   (its id, source, and the match that pulled it in). Excerpting every
   neighbor would bloat the bundle agents are trying to keep small.

## Decision

Add a **Connected scrolls** section to the bundle, between Excerpts and
Links, built from the link graph (`src/scrolls/context.py`).

- **Source.** `context._connected_lines(db_path, ranked_ids)` calls
  `graph.build_graph` once and keeps every edge with exactly one endpoint
  among the matches: the *other* endpoint is a connected neighbor. An edge
  with both ends matched (two keyword hits that link to each other) or
  neither is skipped — a match is already in Best Matches and is never
  listed as its own neighbor.

- **Direction is the evidence.** A match→neighbor edge reads "linked from
  «match»" on the neighbor (the match points at it); a neighbor→match edge
  reads "links to «match»" — the same `via`/reason role a search snippet
  plays, naming *which* saved scroll pulled the neighbor in.

- **Ranked by centrality, capped.** Neighbors sort by how many distinct
  matches they connect to (a paper two matches both cite is more central),
  then by the best match's rank, then by id for determinism. The line names
  the strongest match and appends `(+N more)` when a neighbor bridges
  several. The list is capped at the match count (`len(ranked_ids)`), so the
  section never outgrows the matches it hangs off.

- **Conditional and node-sourced.** No connections → no section, not an
  empty header (the bundle stays terse). Titles/sources come from the
  graph's own `Node`s — a connected item is by definition a graph node — so
  there is no extra `get_item` per neighbor. A neighbor still at stage
  `detected` (a linked paper saved but unfetched) shows by id, honestly
  flagging "you have this but haven't pulled it."

- **One surface, both interfaces.** The change lives entirely in
  `build_context`, which the MCP `get_context_bundle` tool already delegates
  to (ADR 0014/0020), so the MCP bundle gains the section with no new code.

## Consequences

- The link graph the adapters spent ADRs 0034–0046 building finally pays off
  in the place an agent reads: a `scrolls context` call now returns both the
  keyword matches *and* the saved scrolls they connect to, in one bundle, no
  follow-up `related` call required. The model↔paper, preprint↔published,
  package↔repo, and dataset↔parent-work edges surface where they are most
  useful.
- The section is deliberately **link-only**. Folding `related`'s
  concept/tag/category signal in (a second connection kind, the way ADR 0044
  defers concept/tag *graph* edges) is a separable, reversible next step;
  this slice keeps the bundle's signal-to-noise high by adding only the
  precise edges.
- A "Synthesized Brief" over the matches *and* their connected scrolls
  remains the honest LLM-shaped slot the bundle has always left open
  (IDEAS.md §11) — the graph gives such a brief better raw material, but the
  deterministic bundle stays keyless.
- `build_context` now scans the whole library once (the linear
  `build_graph`) in addition to the FTS query. For a local library of
  hundreds–thousands of items this is negligible, and it reuses the tested
  linear build rather than the per-pair O(n²) of scoring (ADR 0044).
