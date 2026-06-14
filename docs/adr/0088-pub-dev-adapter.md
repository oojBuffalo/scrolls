# 0088: Pub.dev via the keyless JSON API; the Dart/Flutter sibling of the package family

Date: 2026-06-13

Status: accepted

## Context

A developer's saved internet — Scrolls' core audience (IDEAS.md §11) — is
full of package pages, and the pub.dev package page is the Dart/Flutter
sibling of the PyPI, npm, crates.io, Packagist, RubyGems, and Go pages the
previous six registry adapters claimed (ADR 0034–0036, 0039, 0040, 0042).
The registry family was described as "complete across Python, JavaScript,
Rust, PHP, Ruby, and Go" — but Dart and Flutter are a large, growing
ecosystem with no home: until now a `pub.dev/packages/<name>` URL fell
through to the generic `web` adapter (ADR 0001), which runs `trafilatura`
over a JS-rendered page. That captures the description but discards the
structured metadata pub.dev already holds — the publish date, the
repository, and, critically, the author-curated **topics** that wire a
package into the KB concept graph. pub.dev publishes a stable, keyless
JSON API (`pub.dev/api/packages/<name>`) returning all of that, so a
dedicated adapter is both more faithful and cheaper than scraping.

Three facts shaped the design, confirmed by smoke-testing the live API
before committing — the discipline the prior registry ADRs used.

1. **Identity is the package name, folded lowercase.** Pub package names
   are lowercase Dart identifiers — the registry enforces `[a-z0-9_]`, no
   uppercase and no hyphens (hyphens are not valid Dart identifiers) — and
   the API is case-sensitive: live, `GET /api/packages/Provider` returns
   404 while `…/provider` returns 200. So `/packages/<name>` and the
   version page `/packages/<name>/versions/<v>` are the same package (the
   family's version-page rule), and the name is folded lowercase — the
   PyPI/crates/Packagist fold (ADR 0034/0036/0039), *not* the verbatim
   npm/RubyGems rule (ADR 0035/0040). Folding is strictly safe here because
   the canonical form is *always* lowercase, so a mistyped `Provider` still
   resolves and dedupes rather than missing at fetch time — the inverse of
   the case-sensitive registries, where folding would *cause* a miss.

2. **`latest.pubspec` carries the manifest.** The endpoint returns the
   whole package; `latest` is the most-recent version, and `latest.pubspec`
   is that version's `pubspec.yaml` as JSON — name, description, topics,
   repository, homepage, environment. There is no version to select (unlike
   Packagist's `versions` map, ADR 0039) and no comparator to write: the
   API has already chosen "latest" the way the registry's own page does.
   Re-fetching refreshes the scroll to the current latest release — the
   family's "track the package, not a pin" choice.

3. **`topics` are the concept signal; no README in the API.** Pub's
   `pubspec.topics` (`state-management`, `os-integration`) are the author's
   curated labels — the github-repo-topics analog (ADR 0007) — so a pub
   scroll *feeds the KB concept graph*, the trait that sets it apart from
   its siblings RubyGems and Go (ADR 0040/0042), whose registries carry no
   keywords and contribute structurally-empty `concepts`. The README lives
   only inside the package archive (`archive_url`), not the JSON, so the
   package description is the searchable content the API holds, and the
   scroll is honestly metadata-only (ADR 0002) — RubyGems' situation.

## Decision

`scrolls add`/`fetch` of a pub.dev package runs a new keyless adapter
(`src/scrolls/sources/pub.py`):

- **Identity is the package name, folded lowercase.** `detect_source`
  claims `pub.dev`/`www.pub.dev` and the legacy `pub.dartlang.org` (it 301s
  to pub.dev, but a saved old link still detects), and a
  `/packages/<name>[/versions/<v>]` URL yields `pub:<name>` with the name
  lowercased and validated as a Dart identifier (`[a-z0-9_]+`) —
  `packages/Provider` folds to `pub:provider`
  (`src/scrolls/sources/detect.py`, `tests/test_detect.py`). The deliberate
  match to the folding registries (ADR 0034/0036/0039): pub's canonical
  form is lowercase, so folding is the forgiving choice, not a risk. A
  hyphenated path (`/packages/foo-bar`) is not a valid package name and
  falls through; the package list, publisher, and search pages carry no
  package name and become the source with no fetchable item — the family's
  pattern (ADR 0034–0036, 0039, 0040).
- **Fetch reads `latest.pubspec`.** The adapter GETs
  `pub.dev/api/packages/<name>` and maps `latest.pubspec` directly; there
  is no `versions` collection to rank.
- **The description is the content; the scroll is metadata-only.** The
  pubspec `description` is the `summary`; there is no `extracted_text` and
  no secondary download — the honest reflection of an API that exposes no
  README (it ships only in the package archive). The `web`-scrape baseline
  captured no structured metadata, so nothing is lost.
- **`topics` become `concepts`.** The pubspec `topics` array is the
  author's curated labels — the github-repo-topics role (ADR 0007) — so a
  pub package joins the KB concept graph. This is the value that justifies
  a dedicated adapter over the `web` scrape, and what distinguishes pub
  from the keyword-less RubyGems/Go registries. A package with no `topics`
  (older or minimal ones) contributes empty `concepts`, an
  incidentally-absent value, not RubyGems' structural gap.
- **A Flutter dependency becomes the `flutter` tag.** Pub exposes no
  classifier or license facet in the version JSON, but it does carry the
  one structured signal that matters across the ecosystem: whether a
  package targets Flutter. A package that declares the Flutter SDK — an
  `environment.flutter` constraint, a `flutter` SDK dependency, or both (a
  real plugin like `url_launcher` carries both) — is tagged `flutter`, so
  `--tag flutter` separates Flutter plugins from pure-Dart packages
  (`riverpod`). A pure-Dart package is left *untagged* rather than given a
  synthesized `dart` label — the honest-empty `tags` posture of Go
  (ADR 0042), not a back-filled facet.
- **Repository and homepage become `links`, the repository normalized.**
  The pubspec `repository` and `homepage` become `links` — the two that
  match crates'/RubyGems' homepage/repository shape (ADR 0036/0040) — with
  the pub.dev page itself dropped and trailing-slash variants collapsed.
  The repository's `git+`/`.git` is folded to a clean URL; notably, pub
  packages in a monorepo store a *tree* repository URL
  (`github.com/flutter/packages/tree/main/packages/url_launcher`), and
  `scrolls related` still resolves it to the package's github repo because
  `detect_source` reads `owner/repo` off the path regardless of the
  trailing tree segment (the package↔repo edge, RubyGems' tagged-tree case,
  verified live with `url_launcher`). No github-specific tree-stripping is
  needed.
- **`published_at` is the version's publish time.** `latest.published` (an
  ISO 8601 timestamp with microseconds and a `Z` suffix, normalized through
  the shared `to_utc_iso`, ADR 0024) is the publish moment, with the
  feed/import seed (ADR 0021) as the fallback.
- **Author is best-effort.** The pubspec `author`/`authors` fields are
  deprecated and usually absent (pub.dev moved to verified publishers,
  which the version JSON does not carry), so `author` is read from the
  deprecated `author` string when present and left `None` otherwise — an
  honest gap, not a synthesized value.
- **Pub packages classify as `tool`.** A published package is something you
  install and use, so `pub` joins `pypi`, `npm`, `crates`, `packagist`,
  `rubygems`, and `go` as a curated-source `tool` in the rules engine
  (`src/scrolls/classify.py`, ADR 0004) — distinct from github's `project`
  (a repo to read).

Per the no-network rule (ADR 0001), the JSON GET is injected; tests run
against a recorded package document (`tests/test_pub.py`), and the decision
was smoke-tested end to end against the live API (`url_launcher`, the
Flutter plugin with a monorepo-tree repo; `riverpod`, the pure-Dart package
with topics; the case-folded `Provider`).

## Consequences

- A saved pub.dev package becomes a clean scroll — name, publish date,
  description, topics-as-concepts, the `flutter` tag, and the
  repository/homepage links — instead of a `trafilatura` scrape. The
  seventeenth keyless fetch adapter; `x` (Field Theory import only,
  ADR 0009) remains the sole detected source without one.
- The package family now spans **seven** registries across the
  case-sensitivity axis: PyPI/crates/Packagist/**pub** fold,
  npm/RubyGems preserve, Go preserves with request case-encoding — each id
  rule matching its registry's own behavior, none guessed. pub sits with
  the folding three, and is the *forgiving* end: folding can only help,
  never miss, because the canonical name is lowercase.
- Pub is the family's counter-example to RubyGems and Go on the concept
  signal: where those registries carry no keywords and feed the concept
  graph nothing, pub's `topics` make it a first-class concept producer like
  PyPI's keywords and crates' — a package's topics co-occurring with the
  same labels on a github repo, a dev.to post, or an arXiv paper in the KB
  concept pages.
- The `flutter` tag is the family's first *derived* tag — computed from the
  SDK dependency rather than read from a license/classifier field — and the
  honest model for a registry whose one structured facet is implicit in the
  manifest rather than declared.
- The package↔repo link enriches the graph for free, and the monorepo-tree
  repository URL re-proves the link resolution is robust: `detect_source`'s
  `owner/repo` extraction (ADR 0023, 0028) absorbs the `/tree/<ref>/...`
  suffix with no adapter-side special case (RubyGems' lesson, ADR 0040).
- The full latest-version object is kept verbatim in `raw_text`, so a
  future enrichment — the README from the package archive, the dependency
  graph, the SDK constraints, the example — can expand a package without a
  refetch, the raw-record-spine discipline every API adapter follows.
- Other JSON-metadata registries remain reachable on the same pattern when
  a developer's saved set calls for them — Hex (Elixir/Erlang), pub's
  closest twin in shape (`meta.description`/`meta.licenses`/`meta.links`),
  NuGet (.NET), and Hackage (Haskell) — none claimed until a saved URL
  needs one.
