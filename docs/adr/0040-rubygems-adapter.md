# 0040: RubyGems via the keyless JSON API; the Ruby sibling of pypi/npm/crates/packagist

Date: 2026-06-13

Status: accepted

## Context

A developer's saved internet — Scrolls' core audience (IDEAS.md §11) — is
full of package pages, and the RubyGems gem page is the Ruby sibling of
the PyPI, npm, crates.io, and Packagist pages the previous four registry
adapters claimed (ADR 0034, ADR 0035, ADR 0036, ADR 0039). ADR 0039
named RubyGems as one of the two remaining obvious adapters on the
JSON-metadata pattern. Until now a `rubygems.org/gems/<name>` URL fell
through to the generic `web` adapter (ADR 0001), which runs `trafilatura`
over the rendered HTML: it captures the description but discards the
structured metadata RubyGems already holds — the authors, the publish
date, the license, the project URLs. RubyGems publishes a stable, keyless
JSON API (`rubygems.org/api/v1/gems/<name>.json`) returning all of that,
so a dedicated adapter is both more faithful and cheaper than scraping.

Three facts shaped the design, confirmed by smoke-testing the live API
before committing — the discipline the prior registry ADRs used.

1. **Identity is the gem name, case-sensitive.** RubyGems gem names are
   case-sensitive: live, `GET /api/v1/gems/Ascii85.json` returns 200 while
   `…/ascii85.json` returns 404. So `/gems/<name>` and the version page
   `/gems/<name>/versions/<v>` are the same gem (the version-page rule the
   whole family shares), but the name must be preserved *verbatim* — npm's
   rule (ADR 0035), not the case-folding PyPI (PEP 503, ADR 0034),
   crates.io (ADR 0036), and Packagist (ADR 0039) apply. Folding would
   turn a `RedCloth` or `Ascii85` URL into a fetch-time miss.

2. **The endpoint returns the latest version inline.** Unlike Packagist's
   `versions` map (ADR 0039) or the crates `versions` array (ADR 0036),
   `gems/<name>.json` *is* the gem's most-recent release — name, version,
   authors, description, licenses, and the project URLs in one document.
   There is no version to select and no comparator to write: the API has
   already chosen "latest" the way the registry's own page does.

3. **No keywords, and no README in the API.** A gemspec has no keywords
   field, so a RubyGems scroll contributes nothing to the KB concept
   graph — the first registry adapter for which empty `concepts` is
   *structural* rather than an incidentally-absent value. And the README
   lives only inside the `.gem` (a tar containing a gzipped `data.tar.gz`,
   a nested-archive unpack with no inline copy in the JSON), so the gem's
   `info` description is the searchable content the API holds, and the
   scroll is honestly metadata-only (ADR 0002) — Packagist's situation.

## Decision

`scrolls add`/`fetch` of a RubyGems gem runs a new keyless adapter
(`src/scrolls/sources/rubygems.py`):

- **Identity is the gem name, verbatim.** `detect_source` claims
  `rubygems.org`/`www.rubygems.org`, and a `/gems/<name>[/versions/<v>]`
  URL yields `rubygems:<name>` with the name preserved as-is —
  `gems/Ascii85` stays `rubygems:Ascii85`
  (`src/scrolls/sources/detect.py`, `tests/test_detect.py`). The
  deliberate match to npm's verbatim id (ADR 0035) and departure from the
  three folding registries: RubyGems is case-sensitive, so the id can't
  fold without risking a fetch-time miss. The gems list and search pages
  carry no gem name and become the source with no fetchable item —
  the family's pattern (ADR 0034–0036, 0039).
- **Fetch reads the latest version inline.** The adapter GETs
  `rubygems.org/api/v1/gems/<name>.json` and maps the document directly;
  there is no `versions` collection to rank. Re-fetching refreshes the
  scroll to the current latest release — the family's "track the package,
  not a pin" choice.
- **The description is the content; the scroll is metadata-only.** The
  gem's `info` is the `summary`; there is no `extracted_text` and no
  secondary download — the honest reflection of an API that exposes no
  README (it ships only in the nested `.gem` archive). The `web`-scrape
  baseline captured no structured metadata, so nothing is lost.
- **Concepts are empty by design.** A gemspec declares no keywords, so
  `concepts` is always `()` — not an absent field that might be populated
  elsewhere, but a structural gap. Documented honestly rather than
  back-filled with guessed labels (the rules engine's posture, ADR 0004).
- **Licenses become `tags`.** The `licenses` array is SPDX identifiers — a
  structured facet, the slot PyPI's trove classifiers, crates' categories,
  and Packagist's type+license fill (ADR 0034, 0036, 0039). RubyGems has
  no `type` analog, so `tags` is the license set alone.
- **Homepage, source, and documentation URIs become `links`, the source
  normalized.** The `homepage_uri`, `source_code_uri`, and
  `documentation_uri` become `links` — the three that match crates'
  homepage/repository/docs shape (ADR 0036) — with the RubyGems page
  itself dropped and trailing-slash variants collapsed. The source URI's
  `git+`/`.git` is folded to a clean URL; notably, RubyGems often stores a
  *tagged-tree* source URI (`github.com/rails/rails/tree/v8.1.3`), and
  `scrolls related` still resolves it to the gem's github repo because
  `detect_source` reads `owner/repo` off the path regardless of the
  trailing tree segment (the package↔repo edge, verified live with
  `rails`). No github-specific tree-stripping is needed.
- **`published_at` is the version's publish time.** `version_created_at`
  (an ISO 8601 timestamp with fractional seconds and a `Z` suffix,
  normalized through the shared `to_utc_iso`, ADR 0024) is the publish
  moment, with the feed/import seed (ADR 0021) as the fallback.
- **Author is the gem's `authors` string.** RubyGems already returns
  `authors` as a single comma-joined display string ("David Heinemeier
  Hansson"), so it is used as-is — no per-author formatting like Crossref
  or Packagist need.
- **RubyGems gems classify as `tool`.** A published gem is something you
  install and use, so `rubygems` joins `pypi`, `npm`, `crates`, and
  `packagist` as a curated-source `tool` in the rules engine
  (`src/scrolls/classify.py`, ADR 0004) — distinct from github's
  `project` (a repo to read).

Per the no-network rule (ADR 0001), the JSON GET is injected; tests run
against a recorded gem document (`tests/test_rubygems.py`), and the
decision was smoke-tested end to end against the live API (`rails`, the
case-sensitive `Ascii85`).

## Consequences

- A saved RubyGems gem becomes a clean scroll — name, authors, publish
  date, description, license-as-tags, and the homepage/source/docs links —
  instead of a `trafilatura` scrape. The fourteenth keyless fetch adapter;
  `x` (Field Theory import only, ADR 0009) remains the sole detected
  source without one.
- The five package registries now span the case-sensitivity axis
  completely on purpose: PyPI/crates/Packagist fold, npm/RubyGems preserve
  (case-sensitive registries) — each id rule matching its registry's own
  behavior, none guessed. RubyGems is the simplest of the five (latest
  version inline, no `versions` collection, no comparator), the clean
  bottom of the family's complexity range.
- RubyGems is the family's honest reminder that not every registry feeds
  every field: with no keywords it contributes zero to the concept graph,
  and the adapter says so structurally (`concepts=()`) rather than
  pretending otherwise.
- The gem↔repo link enriches the graph for free, and the tagged-tree
  source URI proves the link resolution is robust: `detect_source`'s
  `owner/repo` extraction (ADR 0023, 0028) absorbs the `/tree/<ref>`
  suffix with no adapter-side special case.
- The full gem document (minus the bulky `dependencies` tree) is kept
  verbatim in `raw_text`, so a future enrichment — the README from the
  `.gem` archive, the dependency graph, the rich `metadata` URIs — can
  expand a gem without a refetch, the raw-record-spine discipline every
  API adapter follows.
- Go modules remain the last obvious registry on this JSON-metadata
  pattern (the `proxy.golang.org` `@latest`/`.info` endpoints), the
  natural next adapter.
