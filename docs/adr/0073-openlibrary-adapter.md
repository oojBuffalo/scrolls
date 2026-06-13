# 0073: Open Library adapter — books, a content type with no prior home

Date: 2026-06-13

Status: accepted

## Context

Scrolls covers a wide spread of content types — papers (arXiv, Crossref,
PubMed, bioRxiv/medRxiv — ADR 0008/0037/0065/0068), standards (RFC, ADR 0066),
code (GitHub and four siblings), packages (six registries), ML artifacts
(Hugging Face, ADR 0041), social posts, forums, encyclopedia articles
(Wikipedia), and the generic `web`/`pdf` fallbacks. **Books were missing.** A
saved `openlibrary.org` book link fell through to the `web` adapter, which
scrapes the JS-rendered page — extracting some text but none of the structured
signal the catalog publishes, and crucially no `concepts`, so the book became a
concept-less island invisible to `scrolls related`, the concept facets, and the
KB concept graph. This is the exact gap dev.to had before ADR 0061 and standards
had before ADR 0066: a real content type stuck as a `web` scrape.

[Open Library](https://openlibrary.org) is the Internet Archive's open,
keyless bibliographic catalog — it is to books what Crossref is to papers. Every
record has a stable `.json` view served with no auth, no key, and no runtime
dependency (the arXiv/Crossref discipline, ADR 0008/0037). It models books in
the same **FRBR** sense Scrolls' own `works` engine uses (ADR 0069): a *work*
(`/works/OL…W`) is the abstract book, an *edition* (`/books/OL…M`) a specific
manifestation, and an ISBN (`/isbn/<isbn>`) names an edition — the
work/manifestation distinction the `scrolls works` DOI clustering already speaks.

## Decision

Add an `openlibrary` source (host-claimed on `openlibrary.org`) and a keyless
fetch adapter (`sources/openlibrary.py`).

- **All three save shapes are claimed, the kind in the id.** `/works/OL…W` →
  `openlibrary:OL…W`, `/books/OL…M` → `openlibrary:OL…M`, `/isbn/<isbn>` →
  `openlibrary:isbn:<isbn>`. The OLID's own type letter (`W`/`M`) already encodes
  work-vs-edition, so — unlike Hugging Face's explicit `model:`/`dataset:` prefix
  (ADR 0043) — only the ISBN form needs a prefix. The OLID is uppercased to a
  canonical form (Open Library routes case-insensitively but displays uppercase,
  the crates/gitlab fold — ADR 0036/0055), a trailing title slug or `/editions`
  subpage dedupes to the OLID, and the ISBN is hyphen-stripped and uppercased
  (its check char may be `X`). Author pages (`/authors/OL…A`), subject/search/list
  routes, and the home page carry no book (the github profile-page pattern).

- **The adapter routes on the id and shares one normalizer.** A work id reads
  `/works/<OLID>.json`; an edition id reads `/books/<OLID>.json`; an `isbn:` id
  reads `/isbn/<isbn>.json`, which Open Library 302-redirects to the edition
  record (urllib follows it), so the ISBN and edition paths converge.

- **Subjects are the concepts.** Open Library's curated `subjects` become
  `concepts` (the github-topics/MeSH role, ADR 0007/0065) — the whole point of a
  dedicated adapter. Administrative/accessibility flags (`Accessible book`, `Open
  Library Staff Picks`, …) and library call numbers (`Pz7.d1515`, `Aa76.73.p98`)
  are filtered as concept-graph noise, the list deduped case-insensitively
  (first spelling wins) and capped. Subjects live on the **work**, so an
  edition/ISBN fetch follows its `works` ref with one extra GET to pull them (the
  Bluesky/Stack Exchange two-request shape), degrading to the edition's own
  (usually empty) subjects on any failure.

- **The blurb is the summary; there is no full text.** `description` (a string
  or a `{value}` text object) → `summary` with **no `extracted_text`**: the
  catalog holds metadata, not the book's body, so a book is honestly summary-only
  (the Crossref/PubMed shape, ADR 0037/0065). `tags` stay empty by design — a
  book has no clean controlled facet like an RFC's status or a package's license
  (the go/rubygems posture, ADR 0042/0040).

- **Authors are references resolved with bounded GETs.** A record names authors
  by key only; each (capped, the RFC `et al.` truncation) is resolved to its
  `.json` `name`, a failed or nameless lookup skipped so the byline degrades
  rather than failing the fetch.

- **Edges.** An edition links to its FRBR work (`/works/<OLID>`) — the
  edition↔work edge `scrolls related`/`graph` resolves to the work's scroll when
  both are saved (the RFC↔RFC intra-source edge, ADR 0066) — and a work's curated
  external `links` become outbound edges. The first present cover id (Open
  Library's `-1` "no cover" sentinel skipped) becomes a `thumbnail` media ref on
  `covers.openlibrary.org` (the youtube/Discourse convention, ADR 0011). Free-form
  publication dates (`Aug 20, 2015`, `August 2015`, `2015`, `2008-09`) parse to
  UTC ISO 8601 with missing parts padded to the start of the period (the RFC
  partial-date rule, ADR 0024).

- **No category default.** Open Library spans fiction and non-fiction, so forcing
  `reference` (right for a textbook) would be dishonest for a novel — the honesty
  value that keeps a medRxiv paper off the `biorxiv` label (ADR 0068/0045). A book
  flows through the title rules (a "How to" → tutorial) and otherwise stays
  honestly unclassified — Hacker News's posture (ADR 0031), not a guessed default.

## Consequences

- **Books join the library as first-class scrolls.** A saved book now wires into
  the concept graph through its subjects, dedupes its work/edition/ISBN URLs onto
  stable ids, and connects an edition to its work — `test_openlibrary.py` covers
  the subjects-as-concepts join, the edition→work subject follow-up and link, the
  bounded author resolution, the cover thumbnail, the date dialects, and the
  metadata-only posture, all offline against trimmed fixtures (ADR 0001). A live
  smoke test confirmed a work, an edition, and an ISBN ingest cleanly and the
  edition↔work edge resolves in `scrolls related`.

- **The FRBR symmetry with `scrolls works`.** Open Library's work/edition split
  mirrors the abstract-work/representation split the DOI `works` engine already
  models (ADR 0069). The two are not yet connected — a book carries no DOI and a
  paper no OLID — but the vocabulary is now shared, and a future enrichment
  (matching an edition's ISBN or a work's `identifiers` to a saved paper) has an
  obvious home.

- **Deferred.** Author *bio* enrichment (a work could carry its authors as their
  own scrolls), the work's `identifiers` (Wikidata/Goodreads/LibraryThing
  cross-references as links), and a true work↔edition merge (collapsing the
  manifestations into one canonical item — the same merge ADR 0069/0072 defer for
  papers) are left for later. This ADR adds the adapter, not the merge.
