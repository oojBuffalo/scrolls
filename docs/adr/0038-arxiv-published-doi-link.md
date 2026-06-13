# 0038: arXiv records its published DOI as a link — the preprint↔published edge

Date: 2026-06-13

Status: accepted

## Context

ADR 0037 added the Crossref adapter, so Scrolls now holds two kinds of
the same paper: the arXiv preprint (`arxiv:<id>`, ADR 0008) and the
published version reached through its DOI (`crossref:<doi>`). They are
distinct items by design — different identifiers, different metadata, a
preprint and its journal-of-record version — but until now they were
also *disconnected*: a library could hold both and `scrolls related`
(ADR 0023's link graph, IDEAS.md §10) would not know they were the same
work. That is exactly the kind of edge the related graph exists to
surface, and the join already lives in the data: when a preprint is
published, arXiv stamps the published DOI into its Atom entry as an
`arxiv:doi` element (and the human-readable citation as
`arxiv:journal_ref`). The arXiv adapter parsed the Atom feed already but
ignored those elements, and in fact emitted no `links` at all — the PDF
went to `media`, the taxonomy to `tags`/`concepts`, nothing to `links`.

The registry adapters established the pattern this reuses: a package's
declared repository URL becomes a `link`, and because
`related._link_targets` resolves every link through `detect_source` +
`make_item_id`, a saved package and its saved github repo relate with no
new edge type (the package↔repo edge, ADR 0034–0036). The published DOI
is the same shape of free dividend — a URL already in the source data
that resolves to another item's identity.

## Decision

The arXiv adapter captures every `arxiv:doi` element as a
`https://doi.org/<doi>` link (`src/scrolls/sources/arxiv.py`,
`tests/test_arxiv.py`):

- **The DOI becomes a `doi.org` link, not a bare DOI.** A
  `https://doi.org/<doi>` URL is what `detect_source` recognizes
  (ADR 0037), so `related._link_targets` folds it to the `crossref:<doi>`
  id a saved DOI would mint — and because that resolution lowercases the
  DOI (DOIs are case-insensitive, ADR 0037), the edge holds even when
  arXiv records the DOI in a different case than the Crossref id stores
  it. The preprint then relates to its published paper "in either
  direction" through the existing scoring, with no new edge type and no
  schema change.
- **No DOI means no links.** Most preprints have no journal DOI (they
  were never formally published, or not yet), so `links` stays empty —
  honestly empty, the common case, not a guess.
- **`arxiv:journal_ref` is left in `raw_text` only.** The citation string
  (`Phys. Rev. Limuch. 12 (2024) 34`) is not a URL and not an identity, so
  it is not a link; the full Atom feed already preserves it in `raw_text`
  for a future "venue" enrichment.

Per the no-network rule (ADR 0001), this is covered by the adapter's
injected-fetcher test (an Atom entry with an `arxiv:doi`) and an
end-to-end `related` test that inserts an arXiv item linking to a saved
Crossref paper and asserts the both-way edge resolves across the DOI
case fold (`tests/test_related.py`).

## Consequences

- arXiv and Crossref are no longer parallel silos: a saved preprint and
  its saved published version surface each other in `scrolls related`
  and the future MCP `get_related_scrolls`, closing the literature loop
  ADR 0037 opened. The `paper` category groups them; this link connects
  the specific pair.
- The arXiv adapter now emits `links` (previously always empty), so a
  re-fetch of a now-published preprint gains the edge with no migration —
  the scroll re-renders with the DOI in its frontmatter.
- The edge is free of new machinery: it rides `related`'s existing
  link-resolution (ADR 0023) and Crossref's existing DOI detection
  (ADR 0037), exactly as the package↔repo edge rides the same path
  (ADR 0034–0036). No new edge type, scoring rule, or schema column.
- The reverse direction — a Crossref work pointing back at its arXiv
  preprint — is not added here: Crossref records arXiv as a `relation`
  only sporadically, so the preprint→published link carries the pair, and
  `related`'s "either direction" scoring means one link suffices.
