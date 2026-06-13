# 0039: Packagist via the keyless JSON API; the PHP sibling of pypi/npm/crates

Date: 2026-06-13

Status: accepted

## Context

A developer's saved internet — Scrolls' core audience (IDEAS.md §11) — is
full of package pages, and the Packagist package page is the PHP/Composer
sibling of the PyPI, npm, and crates.io pages the previous three adapters
claimed (ADR 0034, ADR 0035, ADR 0036). Each of those ADRs closed by
naming the registries that share their JSON-metadata shape as the obvious
next adapters; ADR 0036 listed "RubyGems, Packagist, Go modules"
explicitly. Until now a `packagist.org/packages/<vendor>/<name>` URL fell
through to the generic `web` adapter (ADR 0001), which runs `trafilatura`
over the rendered HTML: it captures the description but discards the
structured metadata Packagist already holds — the maintainers, the
publish date, the declared keywords, the license, the repository URL.
Packagist publishes a stable, keyless JSON API
(`packagist.org/packages/<vendor>/<name>.json`) returning all of that, so
a dedicated adapter is both more faithful and cheaper than scraping.

Three facts shaped the design, confirmed by smoke-testing the live API
before committing — the discipline ADR 0034/0035/0036 used.

1. **Identity is `vendor/name`, lowercased.** Composer package names are
   `vendor/package` (two segments, unlike the single-segment PyPI/npm/
   crates names) and case-insensitive: the composer.json schema forbids
   uppercase, and Packagist redirects mixed case to the lowercase
   canonical. So `Monolog/Monolog` and `monolog/monolog` must dedupe to
   one id. This is crates.io's situation (ADR 0036) — fold the id — not
   npm's verbatim-because-case-sensitive rule (ADR 0035). The canonical
   name is read back from the response (`package.name`) for the canonical
   URL, so a folded id never breaks the fetch.

2. **The `versions` map mixes releases with dev branches, unordered by
   contract.** Live, `monolog/monolog.json` returns 93 versions keyed by
   string, interleaving real releases (`3.9.0`, `3.8.1`, `2.9.3`) with
   branch aliases (`dev-main`, `2.x-dev`). The crates.io adapter could
   read a `default_version` field; Packagist exposes no such pointer, and
   the response order is not a documented contract. The adapter must pick
   "the latest stable release" itself. Packagist normalizes every version
   to a numeric `version_normalized` (`3.8.1` → `3.8.1.0`, `3.0.0-RC1` →
   `3.0.0.0-RC1`, `dev-main` → `dev-main`), which makes a dependency-free
   ordering possible without a semver/Composer comparator: compare the
   numeric core of the normalized string.

3. **The API carries no README, only a description.** Unlike npm's
   packument `readme` (ADR 0035) or the crates `.crate` tarball
   (ADR 0036), the Packagist JSON has no inline README and no cheap path
   to one — it lives only in the per-version dist zip, behind a second
   download and an unzip. The package/version `description` is the
   searchable content the API does hold. A description-only scroll is the
   honest common case (ADR 0002), and still far better than the `web`
   scrape it replaces, which captures the same description buried in
   navigation chrome.

## Decision

`scrolls add`/`fetch` of a Packagist package runs a new keyless adapter
(`src/scrolls/sources/packagist.py`):

- **Identity is `vendor/name`, folded lowercase.** `detect_source` claims
  `packagist.org`/`www.packagist.org`, and a
  `/packages/<vendor>/<name>[/...]` URL yields `packagist:<vendor>/<name>`
  with both segments lowercased — `Monolog/Monolog` and `monolog/monolog`
  both become `packagist:monolog/monolog`
  (`src/scrolls/sources/detect.py`, `tests/test_detect.py`). A trailing
  `.json` (the API URL people paste) and any deeper subpage (`/stats`,
  `/dependents`) are dropped, so identity is the package only. Each
  segment is validated against the composer.json name grammar
  (lowercase alphanumerics with single `_.-` separators), so the packages
  list, a vendor-only page (`/packages/<vendor>/`), and search carry no
  package name and become the source with no fetchable item — github's,
  Stack Exchange's, and the other registries' pattern (ADR 0007,
  ADR 0033, ADR 0034–0036).
- **Fetch selects the highest stable release.** The adapter GETs
  `packagist.org/packages/<vendor>/<name>.json` and ranks the `versions`
  map: a *stable* release (numeric `version_normalized`, no `-dev`/`-RC`/
  `-beta` suffix) wins, chosen by comparing the numeric core as an int
  tuple (`(3, 9, 0, 0)` > `(3, 8, 1, 0)` > `(2, 9, 3, 0)`), so the latest
  stable beats both a later-*dated* `2.9.x` patch and the `dev-main`
  branch. Fallbacks walk to the newest pre-release, then the newest dev
  branch by publish time, so a package with only pre-releases or branches
  still yields *a* version (ADR 0002). Re-fetching refreshes the scroll to
  the current latest release — the PyPI/npm/crates choice: the scroll
  tracks "the package," not a pin.
- **The description is the content; the scroll is metadata-only.** The
  chosen version's `description` (falling back to the package's) is the
  `summary`; there is no `extracted_text` and no secondary download — the
  honest reflection of an API that carries no README, and the departure
  from npm/crates, which had a cheap README path and took it. The
  `web`-scrape baseline captured no more, so nothing is lost.
- **Keywords become `concepts`.** A release's author-declared keywords —
  `log`, `logging`, `psr-3` — are curated topical labels, identical in
  spirit to github repo topics and the other registries' keywords, so
  they feed the KB concept pages the same way (ADR 0007, ADR 0034–0036).
  A package with none contributes none, honestly empty.
- **Type and licenses become `tags`.** The package `type` (`library`,
  `project`, `composer-plugin`, `metapackage`, `symfony-bundle`, …) is a
  controlled vocabulary and the release `license` is an array of SPDX
  identifiers — both structured facets, so they fill the `tags` slot
  PyPI's trove classifiers and crates' category taxonomy fill (ADR 0034,
  ADR 0036), the split that keeps free-form labels in `concepts` and a
  registry vocabulary in `tags`. This is the crossref `type`+venue
  composition (ADR 0037): KB pages are per concept, not per tag, so a
  broad `library`/`MIT` here costs nothing there while giving
  `scrolls related` same-type / same-license corroboration.
- **Homepage, repository, and git source become `links`, the source
  normalized.** The package-level `repository` (Packagist's clean repo
  URL), the release `homepage`, and the version's `source.url` (the raw
  git URL, usually `…​.git`) become `links`, with the Packagist page
  itself dropped and trailing-slash variants collapsed. The git source's
  `.git` suffix (and a leading `git+`) is folded to a clean
  `https://github.com/owner/repo`, because `scrolls related` resolves
  links through `detect_source` (ADR 0023, ADR 0028) and a trailing `.git`
  would read as a different repo. Verified live: the three URLs for
  `monolog/monolog` all collapse to `github:Seldaek/monolog`, the
  package↔repo edge.
- **`published_at` is the chosen version's publish time.** The version's
  `time` (normalized through the shared `to_utc_iso`, ADR 0024) is the
  publish moment, falling back to the package-level `time` (its
  first-published date) and finally the feed/import seed (ADR 0021).
- **Author is the release's declared authors, else the maintainers.**
  Composer authors (`{name, email?, …}`) join into a display string,
  truncated past ten names with "et al." (the Crossref author cap,
  ADR 0037); a release that declares none falls back to the package's
  Packagist maintainer accounts.
- **Packagist packages classify as `tool`.** A published Composer package
  is something you install and use, so `packagist` joins `pypi`, `npm`,
  and `crates` as a curated-source `tool` in the rules engine
  (`src/scrolls/classify.py`, ADR 0004) — distinct from github's
  `project` (a repo to read).

Per the no-network rule (ADR 0001), the JSON GET is injected; tests run
against a recorded package document (`tests/test_packagist.py`), and the
decision was smoke-tested end to end against the live API
(`monolog/monolog`, `symfony/console`, the case-folded `Monolog/Monolog`).

## Consequences

- A saved Packagist package becomes a clean scroll — name, author,
  publish date, description, keywords-as-concepts, type/license-as-tags,
  and the normalized repository link — instead of a `trafilatura` scrape.
  The thirteenth keyless fetch adapter; `x` (Field Theory import only,
  ADR 0009) remains the sole detected source without one.
- The four package registries now span both the case-sensitivity axis and
  the README-availability axis on purpose: PyPI/crates/Packagist fold,
  npm preserves (case-sensitive registry); npm/crates expose a README,
  PyPI ships one in the description, Packagist ships none — each adapter
  matching its registry's own behavior, none guessed.
- Stable-version selection without a comparator dependency: ranking by the
  numeric core of `version_normalized` is the reusable technique a future
  RubyGems or Go-modules adapter (no `default_version` pointer either) can
  borrow, keeping the stdlib-first posture (ADR 0001).
- The package↔repo link enriches the graph for free: a saved Composer
  package and its saved github repo (and vice versa) relate through the
  normalized source URL, with no new edge type — the same dividend PyPI's,
  npm's, and crates' source links paid.
- The chosen version's object is kept verbatim in `raw_text` (the bulky
  all-versions map is dropped to bound its size), so a future enrichment —
  the README from the dist zip, the dependency graph, version history —
  can expand a package without a refetch, the raw-record-spine discipline
  every API adapter follows.
- RubyGems and Go modules remain the obvious next adapters on this same
  JSON-metadata pattern.
