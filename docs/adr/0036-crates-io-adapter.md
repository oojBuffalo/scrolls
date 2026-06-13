# 0036: crates.io via the keyless JSON API; README from the `.crate` tarball

Date: 2026-06-13

Status: accepted

## Context

A developer's saved internet — Scrolls' core audience (IDEAS.md §11) —
is full of package pages, and the crates.io crate page is the Rust
sibling of the PyPI and npm pages the previous two adapters claimed
(ADR 0034, ADR 0035). Until now a `crates.io/crates/<name>` URL fell
through to the generic `web` adapter (ADR 0001), which runs `trafilatura`
over the rendered HTML: it captures some of the README but discards the
structured metadata crates.io already holds — the one-line description,
the publisher, the publish date, the declared keywords and categories,
the repository URL. crates.io publishes a stable, keyless JSON API
(`crates.io/api/v1/crates/<name>`) returning all of that, so a dedicated
adapter is both more faithful and cheaper than scraping. ADR 0035 named
this as the obvious next adapter: "crates.io and other registries remain
the obvious next adapters on this pattern."

Two facts shaped the design, both confirmed by smoke-testing the live API
before committing — the discipline ADR 0034/0035 used.

1. **Identity is the name, and crates.io folds case and `-`/`_`.** Live,
   `GET /api/v1/crates/serde_json`, `…/serde-json`, `…/Serde-Json`, and
   `…/SERDE_JSON` all resolve to the one crate whose canonical name is
   `serde_json`. So `/crates/<name>` and `/crates/<name>/<version>` are
   the same crate (the PyPI/npm version-page rule), and equivalent
   spellings must dedupe to one id. This is PyPI's situation, not npm's:
   PyPI folds via PEP 503 (ADR 0034) while npm preserves case because its
   registry is case-sensitive (ADR 0035). crates.io is *insensitive*, so
   the id folds — and because the registry resolves the folded form, the
   fetch never breaks; the canonical published name is read back from the
   response (`crate.name`) for the canonical URL and the download path.

2. **The README lives only in the published `.crate` tarball.** Unlike
   npm's packument, the crates.io crate JSON carries no inline README —
   the version object exposes only a `readme_path` to an endpoint that
   returns the README rendered to *HTML*, not the source Markdown a scroll
   wants. The canonical raw Markdown README ships inside the version's
   `.crate` — a gzipped tar with every file under `<name>-<version>/`,
   the same artifact crates.io itself renders from. A metadata-only scroll
   would be *weaker* than the `web` scrape it replaces (crates.io renders
   the README, so `trafilatura` would capture it), so the README has to
   come from the tarball.

## Decision

`scrolls add`/`fetch` of a crates.io crate runs a new keyless adapter
(`src/scrolls/sources/crates.py`):

- **Identity is the crate name, folded.** `detect_source` claims
  `crates.io`/`www.crates.io`, and a `/crates/<name>[/<version>]` URL
  yields `crates:<name>` with the name case-folded and `[-_]` runs
  collapsed to one `-` — `serde_json`, `serde-json`, and `SERDE_JSON`
  all become `crates:serde-json` (`src/scrolls/sources/detect.py`,
  `tests/test_detect.py`). The deliberate match to PyPI's fold (ADR 0034)
  and departure from npm's verbatim id (ADR 0035): crates.io resolves the
  folded form, so the id can fold without risking a fetch-time miss. The
  crate list, search, user (`/users/<name>`), and category pages carry no
  crate name and become the source with no fetchable item — github's,
  Stack Exchange's, PyPI's, and npm's pattern (ADR 0007, ADR 0033,
  ADR 0034, ADR 0035).
- **Fetch resolves the crate's displayed version.** The adapter GETs
  `crates.io/api/v1/crates/<name>`, reads the canonical name back, and
  selects `crate.default_version` (what the crate page shows) from the
  `versions` array, falling back to `newest_version`, `max_stable_version`,
  and finally the first listed version. Re-fetching *refreshes* the crate
  to its current displayed version, whatever version page was saved — the
  PyPI/npm choice: the scroll tracks "the crate," not a pin.
- **The README is the content, from the capped tarball.** The chosen
  version's `dl_path` is the `.crate` download; the adapter fetches it,
  finds the root `<name>-<version>/README*` (Markdown preferred), and uses
  that raw Markdown as the searchable extracted text. `extraction_method`
  records which path won (`…+tarball-readme` vs `…json`). The download is
  capped at 8 MB — the same `http.get_bytes(max_bytes=…)` npm introduced
  (ADR 0035), now reused for the first time — so a crate that vendors
  large fixtures degrades to metadata-only rather than buffering tens of
  MB; every tarball failure (no `dl_path`, oversized, unreachable, corrupt
  archive, no README) degrades the same way (ADR 0002's
  graceful-degradation rule). Verified live: `serde_json`, `tokio`, and
  `ripgrep` recover their full README from the tarball. Unlike npm, the
  tarball is *always* the README source (there is no packument fallback to
  prefer), so every crate fetch is a JSON GET plus a bounded tarball GET.
- **Keywords become `concepts`.** A crate's author-declared keywords —
  `serialization`, `async`, `cli` — are curated topical labels, identical
  in spirit to github repo topics and PyPI/npm keywords, so they feed the
  KB concept pages the same way (ADR 0007, ADR 0034, ADR 0035). A crate
  with none contributes none, honestly empty.
- **Categories become `tags`.** crates.io categories are a *controlled
  vocabulary* curated by the registry (`Encoding`, `Command line
  utilities`, `Asynchronous`), so they fill the structured-taxonomy `tags`
  slot the way PyPI's trove classifiers and arXiv's codes do (ADR 0034,
  ADR 0008) — the split that keeps free-form author labels in `concepts`
  and a registry taxonomy in `tags`. The readable display name is used
  (not the `encoding`/`no-std::no-alloc` slug), the honest analog of
  arXiv's display-name concepts; the slug stays in `raw_text`.
- **Homepage, docs, and repository become `links`, the repo normalized.**
  The declared `homepage`, `documentation` (usually a `docs.rs` page), and
  `repository` become `links`, with the crates.io page itself dropped and
  trailing-slash variants collapsed. The repository's occasional `.git`
  suffix (and a leading `git+`) is dropped to a clean
  `https://github.com/owner/repo`, because `scrolls related` resolves
  links through `detect_source` (ADR 0023, ADR 0028) and a trailing `.git`
  would read as a different repo. Verified live: `crates:ripgrep` →
  `github:BurntSushi/ripgrep`, the crate↔repo edge.
- **`published_at` is the chosen version's publish time.** The version's
  `created_at` (normalized through the shared `to_utc_iso`, ADR 0024) is
  the publish moment, with the feed/import seed (ADR 0021) as the
  fallback.
- **Author is the version's publisher.** crates.io has no crate-level
  author field; `published_by.name` (falling back to `login`) is the
  closest honest "author" — the account that published the version.
- **crates.io crates classify as `tool`.** A published crate is something
  you install and use, so `crates` joins `pypi` and `npm` as a
  curated-source `tool` in the rules engine (`src/scrolls/classify.py`,
  ADR 0004) — distinct from github's `project` (a repo to read).

Per the no-network rule (ADR 0001), both the JSON GET and the tarball GET
are injected; tests run against a recorded crate document and an in-memory
`.crate` built in the test (`tests/test_crates.py`), and the decision was
smoke-tested end to end against the live registry (`serde_json`, the
folded `serde-json`, `tokio`, `ripgrep`).

## Consequences

- A saved crates.io crate becomes a clean scroll — name, publisher,
  publish date, summary, full README, keywords-as-concepts,
  categories-as-tags, and the homepage/docs/repository links — instead of
  a `trafilatura` scrape. The eleventh keyless fetch adapter; `x` (Field
  Theory import only, ADR 0009) remains the sole detected source without
  one.
- The three package registries now span the case-sensitivity spectrum on
  purpose: PyPI folds (PEP 503), npm preserves (case-sensitive registry),
  crates.io folds (case-insensitive registry) — each id rule matching its
  registry's own behavior, none guessed.
- `http.get_bytes`'s `max_bytes` cap (added for npm's tarball fallback,
  ADR 0035) earns its keep as a reusable capability: crates.io is the
  second adapter to fetch a bounded secondary artifact, and the first to
  do so on every fetch rather than as a fallback.
- The crate↔repo link enriches the graph for free: a saved crate and its
  saved github repo (and vice versa) relate through the normalized
  repository URL, with no new edge type — the same dividend PyPI's and
  npm's source links paid.
- The chosen version's metadata is kept verbatim in `raw_text` (the bulky
  all-versions array and the README are not duplicated), so a future
  enrichment — dependency graph, version history, per-version pinning, the
  `docs.rs` API — can expand a crate without a refetch, the
  raw-record-spine discipline every API adapter follows.
- Other registries (RubyGems, Packagist, Go modules) remain the obvious
  next adapters on this same JSON-metadata pattern.
