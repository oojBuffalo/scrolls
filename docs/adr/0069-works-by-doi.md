# 0069: `scrolls works` — scholarly works clustered by shared DOI

Date: 2026-06-13

Status: accepted

## Context

The library now reaches one scholarly work through as many as four
sources. arXiv covers preprints (ADR 0008), Crossref the published works
that carry a DOI (ADR 0037), DataCite the dataset/software DOIs (ADR 0045),
PubMed the biomedical literature (ADR 0065), bioRxiv/medRxiv the
biology/medicine preprints (ADR 0068), and RFCs the IETF standards
(ADR 0066). Each of these deliberately emits a `doi.org` link — the
preprint↔published edge (ADR 0038) and its PubMed (ADR 0065) and
bioRxiv/medRxiv (ADR 0068) analogs — so that a saved preprint resolves to
its published article through `scrolls related`/`scrolls graph`.

The consequence the architecture doc has flagged for several runs: **one
work can sit in the library as several near-duplicate `paper` entries** —
the arXiv preprint, the published Crossref article, a PubMed indexing
record, a bioRxiv version — each its own item, scroll, and search hit. An
agent asking "what does my library say about the Transformer paper" gets
the same work three times with no signal that they are one thing. The
"concept-level merge so a paper's representations share one page rather
than several near-duplicate `paper` entries" was named as the
increasingly-motivated open step now that four paper sources feed
`doi.org` edges.

`scrolls graph` (ADR 0044) already materializes the link structure, and
when the binding Crossref item is present it *does* cluster these — the
arXiv and PubMed items both link to `doi.org/D`, which resolves to the
`crossref:D` item, so all three land in one component. But the graph has a
structural blind spot: it connects two items only when a link in one
resolves to **an item already in the library**. If the user saved the
arXiv preprint and the PubMed record but *not* the published Crossref DOI,
both items link to `doi.org/D`, that link resolves to a bare URL token no
item owns, and the graph draws **no edge between them** — even though they
are unmistakably the same work. The hub has to be present for the spokes
to connect.

## Decision

Add a `works` view that clusters items by the **DOI that names the work**,
not by realized link edges — a new `works.py` engine, a `scrolls works`
CLI command, and a `get_works` MCP tool.

A *work* is the FRBR/Crossref/OpenAlex sense of the term: the abstract
creation, of which the preprint and the published article are
*manifestations*. Its identity is its DOI. An item is a **representation**
of work `D` when:

1. its `source_id` is itself a DOI (`^10\.\d{4,}/.+$`) — true for
   `crossref` items (the DOI folded lowercase, ADR 0037) and for
   `biorxiv`/`medrxiv` items (the `10.1101/<accession>` preprint DOI,
   ADR 0068), and naturally false for arXiv/PubMed/RFC integer ids; or
2. one of its `links` is a `doi.org` URL — every paper adapter emits the
   published work's DOI as exactly such a link, and `detect_source` reads
   the lowercased DOI back off it (the same normalize-then-detect
   resolution `scrolls graph` uses, ADR 0023/0037).

Items sharing a DOI form one work. Only works with **2+ representations**
are reported by default (`--min N` overrides; `--min 1` lists every
DOI-bearing item) — a single-representation work is just a paper, with
nothing to consolidate. The payload is `{works: [{doi, url,
representations}], stats: {items, works}}`, where each representation is
the `id`/`source`/`title`/`url`/`stage` node shape `graph` and `related`
already use, and `stats.items` is the library total — the same `stats`
shape `scrolls graph` reports.

## Consequences

- **`works` catches clusters the link graph structurally cannot.** Keying
  on the shared DOI *identity* rather than on a resolved edge means two
  representations bind into one work even when the Crossref item that would
  link them is absent (`test_clusters_without_the_crossref_hub_present`).
  When the hub *is* present the two views coincide; `works` is the
  semantically correct lens for "the same scholarly work", and it is
  precisely the view a deduplicating researcher's library wants. This is
  why it is a new view rather than a mode of `scrolls graph`: the graph is
  about links between present items, `works` about external work identity.
- **The `source_id`-is-a-DOI rule generalizes cleanly.** Rather than a
  per-source special case ("crossref ids are DOIs"), an item contributes
  its `source_id` as a work key whenever it matches the DOI shape. That one
  rule covers `crossref` and `biorxiv`/`medrxiv` (whose accession is a real
  `10.1101` DOI) and excludes the integer-id sources, so a directly-saved
  `doi.org/10.1101/X` and the bioRxiv preprint it names cluster
  (`test_doi_in_source_id_keys_the_work`) without any adapter knowledge.
- **Reuses the existing DOI plumbing, no new resolution path.** Links
  resolve through `detect_source` + `normalize_url` exactly as the graph
  and `related` resolve them, and the DOI shape is the one `detect.py`
  already uses — so a work key can never disagree with how the rest of the
  system reads a DOI. The engine is pure, deterministic, offline, and
  needs no schema change.
- **`works_over(items)` mirrors `graph_over(items)`.** The clustering takes
  a given item set, so a future KB `library/works.md` page (or merged
  representations on the `paper` category/source pages — the original
  motivation) can pass its rendered items and render the same clusters,
  the way `graph_over` feeds `library/graph.md` (ADR 0062). That KB merge
  is the obvious next slice this primitive unlocks and is deliberately left
  out here.
- **Deferred:** title/author fuzzy matching for representations that share
  no DOI (two preprints of an unpublished work) — DOI identity is exact and
  trustworthy, title matching is not, so it stays out; and the KB page /
  merged `paper` entries that consume this clustering.
