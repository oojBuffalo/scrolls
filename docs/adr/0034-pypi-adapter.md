# 0034: PyPI via the keyless JSON API; keywords as concepts, classifiers as tags

Date: 2026-06-13

Status: accepted

## Context

A developer's saved internet — Scrolls' core audience (IDEAS.md §11) —
is full of package pages: the PyPI project page is where you land after
"what library does X?" Until now a `pypi.org/project/<name>/` URL fell
through to the generic `web` adapter (ADR 0001), which runs `trafilatura`
over the HTML page: it captures some of the rendered README but discards
the structured metadata PyPI already holds — the one-line summary, the
author, the release date, the trove classifiers, the declared project
URLs. PyPI also publishes a stable, keyless JSON API
(`pypi.org/pypi/<name>/json`) returning all of that for the latest
release as structured data, so a dedicated adapter is both more faithful
and cheaper than scraping. It is the natural companion to the github
adapter (ADR 0007): a repo is the source, a package is the shipped thing.

Three facts about that API shaped the design. (1) A package's identity is
its name, not a version — `/project/flask/` and `/project/flask/3.0.0/`
are the same package — and PyPI normalizes names per PEP 503 (case-fold,
collapse runs of `[-_.]` to a single `-`), so `Flask`, `flask`, and
`zope.interface` must map to one canonical id. (2) The `info` block
carries everything the scroll needs in one GET; the per-file upload times
that date a release live in a sibling `urls` list. (3) Legacy metadata
writes the literal string `"UNKNOWN"` for absent fields, which must not
become a title or summary.

## Decision

`scrolls add`/`fetch` of a PyPI project runs a new keyless adapter
(`src/scrolls/sources/pypi.py`):

- **Identity is the project name, PEP 503-normalized.** `detect_source`
  claims `pypi.org`/`www.pypi.org`, and a `/project/<name>[/<version>]/`
  URL yields `pypi:<normalized-name>` — case-folded with `[-_.]` runs
  collapsed to one `-`, so `Flask`, `flask`, and the versioned page all
  dedupe to `pypi:flask` and `zope.interface` to `pypi:zope-interface`
  (`src/scrolls/sources/detect.py`, `tests/test_detect.py`). Search,
  user, and help pages carry no project name and become the source with
  no fetchable item — github's and Stack Exchange's pattern (ADR 0007,
  ADR 0033), where the host is claimed but only some paths fetch.
- **Fetch always resolves the latest release.** Because identity is the
  name only, the adapter GETs `/pypi/<name>/json` (no version) and takes
  the latest-release metadata it returns. Re-fetching a package
  *refreshes* it to its current version, whatever version page was saved
  — a deliberate, documented choice: the scroll tracks "the package," not
  a pin. A version-pinned scroll is a future option, not this slice.
- **The README is the content; the one-liner is the summary.** PyPI's
  long `description` (the rendered README) maps to `extracted_text` so it
  becomes FTS-searchable, and the one-line `summary` leads the scroll the
  way every adapter does (ADR 0002). `extraction_method` records whether
  a description was present (`pypi-api:json+description` vs `…:json`).
- **Keywords become `concepts`.** A package's author-declared keywords —
  `http`, `client`, `async` — are curated topical labels, identical in
  spirit to github repo topics, so they feed the KB concept pages the
  same way (ADR 0007, ADR 0012). The string form is comma-separated by
  convention but space-separated in the wild, so a comma-less string
  splits on whitespace; metadata 2.x's list form is taken as-is. A
  package with no keywords contributes none, honestly empty (ADRs 0004,
  0033) — verified live, current `rich` declares none.
- **Trove classifiers become `tags`.** The PyPI classifiers
  (`Programming Language :: Python :: 3.11`, `Framework :: Django`) are a
  standardized hierarchical taxonomy, the same shape as arXiv's category
  codes, so they go to `tags` verbatim the way arXiv codes do (ADR 0008,
  ADR 0012) — the organizational field, not the concept graph. Two
  packages sharing `Framework :: Django` then corroborate in `scrolls
  related` (IDEAS.md §10).
- **Declared project URLs become `links`.** `home_page` and the
  `project_urls` map (Homepage, Documentation, Source, …) become `links`,
  collapsed by trailing slash and with the PyPI page itself (the
  canonical URL) dropped. Because `scrolls related` resolves links
  through `detect_source` (ADR 0023, ADR 0028), a package's Source link
  to `github.com/owner/repo` connects it to a saved github repo — the
  package↔repo edge — verified live for `black` → `psf/black`.
- **`"UNKNOWN"` and blanks fold to absent.** A shared `_clean` maps the
  legacy sentinel and empty strings to `None`, so an old package never
  gets `"UNKNOWN"` as its author or summary; `author` falls back to
  `maintainer`.
- **`published_at` is the latest release's earliest file upload.** The
  `urls` list dates the release; the earliest `upload_time_iso_8601`
  (UTC ISO 8601, which sorts chronologically) is the publish moment,
  normalized through the shared `to_utc_iso` (ADR 0024). With no files
  it degrades to the feed/import-seeded date (ADR 0021).
- **PyPI packages classify as `tool`.** A published package is something
  you install and use, so `pypi` is a curated-source category in the
  rules engine (`src/scrolls/classify.py`, ADR 0004) — distinct from
  github's `project` (a repo to read), and the first rule to produce
  `tool` from the IDEAS.md §8 vocabulary.

Per the no-network rule (ADR 0001), the GET is injected and tests run
against a payload recorded and trimmed from the live API
(`tests/test_pypi.py`); the decision was also smoke-tested end to end
against the live API (`rich`, `black`).

## Consequences

- A saved PyPI project becomes a clean scroll — name, author, release
  date, summary, README, keywords-as-concepts, classifiers-as-tags, and
  the homepage/docs/source links — instead of a `trafilatura` scrape of
  the HTML page. The ninth keyless fetch adapter; `x` (Field Theory
  import only, ADR 0009) remains the sole detected source without one.
- The package↔repo link makes the library's graph richer for free: a
  saved package and its saved github repo (and vice versa) now relate
  through declared URLs, with no new edge type.
- `tool` enters the deterministic vocabulary. Every other curated source
  maps to a category no other source produces (reference, paper,
  project); `pypi → tool` continues that, leaving the LLM engine
  (ADR 0015) to assign `tool` to non-PyPI items by reading content.
- The raw `info` and `urls` records are kept verbatim in `raw_text`, so
  a future enrichment (dependency graph, version history, per-version
  pinning) can expand a package without a refetch — the raw-record-spine
  discipline github, arxiv, Hacker News, and Stack Exchange already
  follow.
- npm, crates.io, and other package registries are now an obvious
  pattern to follow: same JSON-metadata shape, same keywords→concepts /
  links→repo mapping, each a small adapter.
