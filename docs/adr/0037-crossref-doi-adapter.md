# 0037: Crossref via the keyless DOI metadata API; the published-literature sibling of arXiv

Date: 2026-06-13

Status: accepted

## Context

A researcher's or developer's saved internet (IDEAS.md §11) is full of
paper links, and a large share of them are DOIs — `doi.org/10.…` — the
durable identifier for the published literature. Scrolls already handles
the *preprint* side: arXiv (ADR 0008) turns `arxiv.org/abs/<id>` into a
clean scroll. But a published journal article, conference paper, or book
chapter is reached through its DOI, and until now a `doi.org/<doi>` link
fell through to the generic `web` adapter (ADR 0001). That is a
particularly bad fit here: the DOI resolver issues an HTTP redirect to
whatever publisher page owns the work, which is frequently a paywall or a
JavaScript landing page, so `trafilatura` captures a cookie banner and an
abstract teaser at best, and the structured metadata that actually
identifies the work — authors, venue, publication date, type — is lost.

Crossref runs the registration agency for the majority of scholarly DOIs
and publishes a stable, keyless REST API
(`api.crossref.org/works/<doi>`) returning that metadata as JSON. A
dedicated adapter is both more faithful (it reads the registered record,
not a scrape of the landing page) and cheaper (one GET, no redirect
chase) than the `web` fallback. This is the obvious literature companion
to arXiv, and a different content class from the four registry adapters
that preceded it (ADR 0034–0036): not a package you install, but a paper
you cite.

Three facts shaped the design, confirmed against the live API before
committing — the smoke-test discipline ADR 0034–0036 used.

1. **Identity is the DOI, and DOIs are case-insensitive.** The DOI
   Handbook §2.4 declares DOIs case-insensitive, and Crossref stores and
   returns them lowercased. Live, `GET /works/10.1145/2939672.2939754`
   resolves whether the saved link used `doi.org` or the legacy
   `dx.doi.org`, and whatever the case. So equivalent spellings must
   dedupe to one id — the folding situation crates.io presented
   (ADR 0036), not npm's case-sensitive registry (ADR 0035). The DOI
   suffix may itself contain slashes (`10.1000/182/sub`), so the whole
   URL path is the identifier, not just the first segment.

2. **The abstract is JATS XML, when it exists at all.** Crossref carries
   no full text — only metadata — so the abstract is the one piece of
   searchable prose, and it arrives as JATS markup
   (`<jats:p>…</jats:p>`, usually led by a `<jats:title>Abstract</jats:title>`).
   It needs reducing to plain text. And it is frequently *absent*:
   publishers are not required to deposit abstracts, and Crossref largely
   stopped collecting `subject` keywords years ago. A metadata-only scroll
   — title, authors, venue, date — is therefore the honest common case,
   not a degraded one (ADR 0002), and it is still far better than the
   `web` scrape it replaces.

3. **A work's references are not its links.** A Crossref record's
   `reference` array enumerates every work it cites — often hundreds of
   DOIs. Turning those into `links` would bury the one edge a reader
   wants (the publisher's own page) under a wall of citations and bloat
   both `links` and `raw_text`. The cited-work graph is a real future
   feature, but it is not what `links` is for.

## Decision

`scrolls add`/`fetch` of a `doi.org` link runs a new keyless adapter
(`src/scrolls/sources/crossref.py`):

- **Identity is the DOI, folded lowercase.** `detect_source` claims
  `doi.org`/`dx.doi.org` (and `www.` variants), and a `/<doi>` path whose
  decoded form matches `10.\d{4,}/…` yields `crossref:<doi>` with the DOI
  lowercased — `doi.org/10.1145/X`, `dx.doi.org/10.1145/X`, and case
  variants all become one id (`src/scrolls/sources/detect.py`,
  `tests/test_detect.py`). The fold matches crates.io's (ADR 0036) and
  departs from npm's verbatim id (ADR 0035) for the same reason: Crossref
  resolves the folded form, so the id can fold without risking a
  fetch-time miss; the canonical DOI is read back from the response
  (`message.DOI`) to build the canonical `https://doi.org/<doi>` URL. The
  bare resolver host and non-DOI paths (`doi.org/about`) carry no
  fetchable item — the now-standard "source known, item unknown" shape
  (ADR 0007, ADR 0033–0036).

- **Fetch reads the registered metadata.** The adapter GETs
  `api.crossref.org/works/<doi>` (the DOI path-encoded but its slashes
  kept) and maps the `message` object: `title` joined with `subtitle`
  (`Title: Subtitle`), the `author` array formatted "Given Family" (or an
  organization's `name`), and the publication date. A response without an
  `ok` status or a `message` object is a `FetchError` ("work not found"),
  which is also how a DataCite-only DOI — a dataset DOI not registered
  with Crossref — surfaces: it 404s here and the item stays `detected`.

- **The JATS abstract becomes a plain `summary`.** Tags are stripped to
  spaces (so block boundaries don't glue words), entities unescaped,
  whitespace collapsed, the space an inline tag leaves before punctuation
  removed, and a leading "Abstract"/"Summary" label dropped. No abstract →
  `summary` is None, a metadata-only scroll. There is no `extracted_text`:
  Crossref has no full text, so unlike arXiv (abstract → `summary`, PDF →
  `extracted_text`, ADR 0008/0010) the body is metadata only.

- **`subject` categories become `concepts`.** Crossref subjects are
  topical labels — the github-topics / PyPI-keywords parallel (ADR 0007,
  ADR 0034) — so they feed the KB concept pages. Most modern records
  carry none, so this is usually honestly empty.

- **The work `type` and its venue become `tags`.** `type`
  (`journal-article`, `proceedings-article`, `book-chapter`, `dataset`, …)
  is a controlled vocabulary — the structured-facet slot arXiv's taxonomy
  codes and PyPI's classifiers fill (ADR 0008, ADR 0034) — and the
  `container-title` (journal or conference proceedings) joins it so
  `scrolls related` can corroborate two works published in the same venue.
  KB pages are built per concept, not per tag (`src/scrolls/kb.py`), so a
  long venue string here adds a `related` signal without spawning a KB
  page.

- **Only the publisher landing page becomes a `link`.**
  `resource.primary.URL` (the page the DOI resolves to) is kept when it is
  an http(s) URL distinct from the canonical doi.org link; the `reference`
  array is deliberately not turned into links, and is dropped from
  `raw_text` to bound its size.

- **`published_at` follows Crossref's date precedence.** `issued` (the
  canonical publication date) wins, then `published`, `published-online`,
  `published-print`, and finally `created` (the record's registration
  date). A field may carry a full `date-time` (used verbatim through the
  shared `to_utc_iso`, ADR 0024) or only `date-parts` `[[year, month?,
  day?]]`, which pads a missing month/day to `01` — the same
  invented-but-uniform precision date-only values already get (ADR 0024).
  The feed/import seed (ADR 0021) is the fallback when no date parses.

- **A Crossref work classifies as `paper`.** A published article is a
  paper, so `crossref` joins `arxiv` as a curated-source `paper` in the
  rules engine (`src/scrolls/classify.py`, ADR 0004) — preprint and
  published literature landing in one category.

Per the no-network rule (ADR 0001), the JSON GET is injected; tests run
against a recorded, trimmed work document (`tests/test_crossref.py`), and
the decision was smoke-tested against the live API.

## Consequences

- A saved DOI becomes a clean scroll — title, authors, venue, publication
  date, a plain-text abstract when one exists, subjects-as-concepts,
  type-and-venue tags, and the publisher link — instead of a redirect into
  a paywall scrape. The twelfth keyless fetch adapter; `x` (Field Theory
  import only, ADR 0009) remains the sole detected source without one.
- Scrolls now covers both halves of the literature: arXiv for preprints
  (ADR 0008), Crossref for the published record, classified into the one
  `paper` category. A saved `arxiv.org/abs/X` and the `doi.org/10.…` of
  its published version are distinct items today; linking them by the DOI
  arXiv records is a natural follow-up.
- The cited-work graph is left on the table on purpose: `reference` DOIs
  are preserved in neither `links` nor `raw_text`, so a future
  "citations" feature would refetch (or read a stored raw record) rather
  than inherit a half-built edge set — the deliberate-scope discipline the
  registry adapters used for dependency graphs.
- DataCite DOIs (datasets, software) 404 against Crossref and stay
  `detected`; a DataCite adapter on the same `doi.org` detection, chosen
  by a fetch-time fallback, is the obvious extension if dataset DOIs prove
  common in real libraries.
- The DOI is preserved as the folded id and the metadata (minus
  references) kept in `raw_text`, so a future enrichment — citation graph,
  funder/affiliation extraction, an Unpaywall open-access link — can
  expand a work without a refetch, the raw-record-spine discipline every
  API adapter follows.
