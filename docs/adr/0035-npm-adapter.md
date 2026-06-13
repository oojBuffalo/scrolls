# 0035: npm via the keyless registry; README from the packument or its tarball

Date: 2026-06-13

Status: accepted

## Context

A developer's saved internet — Scrolls' core audience (IDEAS.md §11) —
is full of package pages, and the npm package page is the JavaScript
sibling of the PyPI one the previous adapter claimed (ADR 0034). Until
now an `npmjs.com/package/<name>` URL fell through to the generic `web`
adapter (ADR 0001), which runs `trafilatura` over the rendered HTML: it
captures some of the README but discards the structured metadata npm
already holds — the one-line description, the author, the publish date,
the declared keywords, the repository URL. npm publishes a stable,
keyless registry API (`registry.npmjs.org/<name>`) returning all of that
as a JSON "packument," so a dedicated adapter is both more faithful and
cheaper than scraping. The architecture doc named this as the obvious
next adapter after PyPI: "same JSON-metadata shape, same
keywords→concepts / links→repo mapping."

Three facts shaped the design, two of them found by smoke-testing the
live API before committing — the discipline ADR 0034 used.

1. **Identity is the name, and npm is case-sensitive.** `/package/flask`
   and `/package/flask/v/3.0.0` are the same package, so a version page
   must dedupe to the name — the PyPI rule. But unlike PyPI's PEP 503
   fold, npm names must *not* be lowercased: the registry is
   case-sensitive and legacy mixed-case packages (`JSONStream`) 404 when
   folded, so folding would break the fetch. Names are also scoped
   (`@babel/core`), and the scope's slash must survive into the id.

2. **The packument carries the README — except when it doesn't.** npm's
   top-level `readme` field holds the rendered README, and for
   smaller/older packages (`lodash`, `commander`) it is populated, one
   GET and done. But for high-traffic packages it is empty: live, the
   top-level `readme` for `express`, `react`, `chalk`, and `@babel/core`
   is `""`. A metadata-only scroll for exactly the most-saved packages
   would be *weaker* than the `web` scrape it replaces (npmjs.com renders
   the README, so `trafilatura` would capture it). The README has to come
   from somewhere reliable.

3. **The README always lives in the published tarball.** Every version's
   `dist.tarball` is a gzipped tar with all files under `package/`,
   including the README — the canonical, keyless source npm itself
   renders from.

## Decision

`scrolls add`/`fetch` of an npm package runs a new keyless adapter
(`src/scrolls/sources/npm.py`):

- **Identity is the package name, preserved verbatim.** `detect_source`
  claims `npmjs.com`/`www.npmjs.com`, and a `/package/<name>[/v/<ver>]`
  URL yields `npm:<name>` — the name exactly as written, scope included
  (`npm:@babel/core`), the `/v/<version>` suffix ignored so a version
  page dedupes to the package (`src/scrolls/sources/detect.py`,
  `tests/test_detect.py`). The deliberate departure from PyPI's fold
  (ADR 0034): npm's registry is case-sensitive, so the id can't
  lowercase without risking a 404 at fetch time. Search, user (`~name`),
  and org pages carry no package name and become the source with no
  fetchable item — github's, Stack Exchange's, and PyPI's pattern
  (ADR 0007, ADR 0033, ADR 0034).
- **Fetch always resolves the latest release.** The adapter GETs
  `registry.npmjs.org/<name>` (scoped names percent-encode the slash,
  the documented form) and follows `dist-tags.latest` to the current
  version's metadata. Re-fetching *refreshes* the package to its current
  version, whatever version page was saved — the PyPI choice: the scroll
  tracks "the package," not a pin.
- **The README is the content, two-tier and keyless.** The packument's
  `readme` is used when present (zero extra requests); when it is empty
  or npm's `ERROR: No README data found!` sentinel, the adapter
  downloads `dist.tarball`, finds the root `package/README*` (Markdown
  preferred), and uses that. `extraction_method` records which path won
  (`…+readme` vs `…+tarball-readme` vs `…json`). The download is capped
  at 8 MB (a new optional `max_bytes` on `http.get_bytes`, read in
  chunks) so a package that bundles large files degrades to
  metadata-only rather than buffering tens of MB; every tarball failure
  — no URL, oversized, unreachable, corrupt archive, no README —
  degrades the same way (ADR 0002's graceful-degradation rule). Verified
  live: `express`/`react`/`chalk`/`@babel/core` recover their full
  README from the tarball, `lodash`/`commander` from the packument.
- **Keywords become `concepts`.** A package's author-declared keywords —
  `color`, `terminal`, `cli` — are curated topical labels, identical in
  spirit to github repo topics and PyPI keywords, so they feed the KB
  concept pages the same way (ADR 0007, ADR 0034). A package with none
  contributes none, honestly empty.
- **`tags` stay empty: npm has no classifier taxonomy.** PyPI's trove
  classifiers went to `tags` as a structured taxonomy (ADR 0034); npm
  has no analog, so `tags` are honestly empty rather than padded with
  something that isn't a taxonomy — the same honesty as a keyword-less
  package.
- **Homepage and repository become `links`, the repo normalized.** The
  declared `homepage` and `repository` become `links`, with the npm page
  itself dropped and trailing-slash variants collapsed. Crucially the
  repository's VCS spelling — `git+https://github.com/owner/repo.git`,
  `git://…`, `git@github.com:owner/repo`, `github:owner/repo` — is
  normalized to a clean `https://github.com/owner/repo` with the `.git`
  dropped, because `scrolls related` resolves links through
  `detect_source` (ADR 0023, ADR 0028) and a trailing `.git` would read
  as a different repo. Verified live: `npm:chalk` → `github:chalk/chalk`
  ("links to it"), the package↔repo edge.
- **`published_at` is the latest version's publish time.** npm's `time`
  map keys each version to its publish timestamp; the latest version's
  stamp (normalized through the shared `to_utc_iso`, ADR 0024) is the
  publish moment, with `time.modified` and then the feed/import seed
  (ADR 0021) as fallbacks.
- **`"UNKNOWN"`-style blanks fold to absent; author falls back to
  maintainer.** A shared `_clean` maps empty strings to `None`; the
  author comes from npm's object (`{name, …}`) or `"Name <email> (url)"`
  string form, falling back to the first maintainer.
- **npm packages classify as `tool`.** A published package is something
  you install and use, so `npm` joins `pypi` as a curated-source `tool`
  in the rules engine (`src/scrolls/classify.py`, ADR 0004) — distinct
  from github's `project` (a repo to read).

Per the no-network rule (ADR 0001), both the JSON GET and the tarball
GET are injected; tests run against a recorded packument and an
in-memory `.tgz` built in the test (`tests/test_npm.py`), and the
decision was smoke-tested end to end against the live registry
(`express`, `react`, `chalk`, `@babel/core`, `lodash`, `commander`,
`@babel/core` scoped).

## Consequences

- A saved npm package becomes a clean scroll — name, author, publish
  date, summary, full README, keywords-as-concepts, and the
  homepage/repository links — instead of a `trafilatura` scrape, and
  *strictly* better than that scrape even for high-traffic packages,
  because the tarball fallback recovers the README the packument drops.
  The tenth keyless fetch adapter; `x` (Field Theory import only,
  ADR 0009) remains the sole detected source without one.
- `http.get_bytes` gained an optional `max_bytes` cap (chunked read,
  raises past the limit), a small general capability any future adapter
  that wants a bounded download can reuse — the first adapter to fetch a
  secondary binary artifact (a tarball) rather than a single JSON/HTML
  body.
- The package↔repo link enriches the graph for free: a saved npm package
  and its saved github repo (and vice versa) relate through the
  normalized repository URL, with no new edge type — the same dividend
  PyPI's source link paid.
- The latest version's metadata and the `time` map are kept verbatim in
  `raw_text` (the bulky all-versions blob and the README are not
  duplicated), so a future enrichment — dependency graph, version
  history, per-version pinning — can expand a package without a refetch,
  the raw-record-spine discipline every API adapter follows.
- npm preserves case where PyPI folds it: the two registries' identity
  rules now differ on purpose, each matching its registry's own
  case behavior. crates.io and other registries remain the obvious next
  adapters on this pattern.
