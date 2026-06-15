# 0095: A work's canonical representation is a first-class property

Date: 2026-06-15

Status: accepted

## Context

A scholarly work can sit in the library as several near-duplicate `paper`
items: an arXiv preprint, its published Crossref article, a PubMed record, a
bioRxiv/medRxiv preprint, an RFC. `works.py` (ADR [0069](0069-works-by-doi.md))
clusters those representations into a `Work` keyed by the shared DOI, and four
surfaces read that clustering — `scrolls works`, the MCP `get_works` tool, the
`library/works.md` page (ADR [0070](0070-kb-works-page.md)), and the category-page
consolidation (ADR [0071](0071-kb-category-work-consolidation.md)).

But "which of these representations *is* the work" had no answer in the model.
A `Work` carried only its `representations`, sorted by id. The one place that
needed to pick a single form — the category page, which heads a consolidated
entry with one title — derived it inline with a private `_PAPER_SOURCE_RANK`
table in `kb.py`: published record (`crossref`) over indexed record (`pubmed`)
over the preprint servers (`biorxiv`/`medrxiv`/`arxiv`) over the standards
track (`rfc`), ties broken by id. Every other surface emitted the
representations flat, so an agent reading `scrolls works` or `get_works` could
not tell which form to cite, and the vision's first-priority capability —
*canonical items*, "source pages and search results show the canonical item" —
had no datum to build on.

## Decision

Promote the canonical representation to a first-class property of `Work`.

- `Work` gains a `canonical: Representation` field, always one of its own
  `representations`. It is chosen by `CANONICAL_SOURCE_RANK` (the precedence
  moved out of `kb.py` to live with the work model) with the item id as the
  deterministic tiebreak, computed once in `works_over` so every caller agrees.
- `to_payload` emits `canonical` as the representation's **id** — a pointer
  into the work's own `representations`, not a duplicated node — so a consumer
  can highlight or cite the one form that stands for the work. `scrolls works`
  and the MCP `get_works` tool carry it for free.
- `kb.py`'s category consolidation stops re-deriving the choice and reads
  `work.canonical`; the rank table now has a single home. The `library/works.md`
  page marks the canonical bullet with `· canonical`, so the durable artifact is
  explainable at a glance.

A single-representation work (the `works_for_item` per-item lens, or `--min 1`)
is its own canonical, so the property is total.

## Consequences

- One definition of "canonical representation" instead of a `kb.py`-private
  one and an implicit none everywhere else; the same consolidation lens the
  recent refactors pursued (ADR 0093/0094).
- The payload grows one key (`canonical`); additive, no schema or DB change,
  deterministic and offline. Existing `representations` consumers are
  unaffected.
- This names the canonical item; it does **not** collapse the scrolls or DB
  rows into one (the deep merge the vision still defers). It is the datum a
  later "search/source pages surface the canonical item" step builds on.
- The exact rank order rarely changes what an agent sees, since a work's
  representations usually share a title; the value is a single, stable,
  inspectable choice.
