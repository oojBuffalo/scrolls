# 0089: Hex via the keyless JSON API; the Elixir/Erlang sibling of the package family

Date: 2026-06-13

Status: accepted

## Context

A developer's saved internet — Scrolls' core audience (IDEAS.md §11) — is
full of package pages, and the Hex package page is the Elixir/Erlang
sibling of the seven registry adapters the family already covers (ADR
0034–0036, 0039, 0040, 0042, 0088). ADR 0088 named Hex as pub.dev's
"closest twin in shape" and the obvious next candidate. Until now a
`hex.pm/packages/<name>` URL fell through to the generic `web` adapter
(ADR 0001), which runs `trafilatura` over a JS-rendered page: it captures
the description but discards the structured metadata Hex already holds — the
publish date, the license, the repository link. Hex publishes a stable,
keyless JSON API (`hex.pm/api/packages/<name>`) returning all of that, so a
dedicated adapter is both more faithful and cheaper than scraping.

Three facts shaped the design, confirmed by smoke-testing the live API
before committing — the discipline the prior registry ADRs used.

1. **Identity is the package name, folded lowercase.** Hex package names
   are lowercase (the registry enforces it), and the API is case-sensitive:
   live, `GET /api/packages/Ecto` returns 404 while `…/ecto` returns 200.
   So `/packages/<name>` and the version page `/packages/<name>/<v>` are
   the same package (the family's version-page rule), and the name is
   folded lowercase — the PyPI/crates/Packagist/pub fold (ADR
   0034/0036/0039/0088), *not* the verbatim npm/RubyGems rule (ADR
   0035/0040). Folding is the forgiving choice here, as it is for pub: the
   canonical form is always lowercase, so a mistyped `Ecto` still resolves
   and dedupes rather than missing at fetch time.

2. **`meta` carries description, licenses, and a links map.** The endpoint
   returns the whole package; `meta.description`, `meta.licenses`, and the
   `meta.links` map (`{"GitHub": "…", "Changelog": "…"}`) are the fields a
   scroll needs — pub.dev's exact field layout, a `meta`/`pubspec` object
   holding description + licenses + outbound URLs. `releases` is a
   newest-first list of `{version, inserted_at}`, so the release matching
   `latest_stable_version` (else `latest_version`) dates the scroll without
   relying on list order.

3. **No keywords, and no README in the API.** Hex has no keywords field, so
   a Hex scroll contributes nothing to the KB concept graph — empty
   `concepts` *by design*, RubyGems' and Go's structural gap (ADR
   0040/0042), the opposite of pub.dev, whose `topics` make it a concept
   producer (ADR 0088). And the README lives only inside the package
   tarball (a separate download), with no inline copy in the JSON, so the
   package description is the searchable content the API holds, and the
   scroll is honestly metadata-only (ADR 0002) — RubyGems' situation.

## Decision

`scrolls add`/`fetch` of a Hex package runs a new keyless adapter
(`src/scrolls/sources/hex.py`):

- **Identity is the package name, folded lowercase.** `detect_source`
  claims `hex.pm`/`www.hex.pm`, and a `/packages/<name>[/<version>]` URL
  yields `hex:<name>` with the name lowercased and validated as a Hex name
  (`[a-z0-9_]+`) — `packages/Ecto` folds to `hex:ecto`
  (`src/scrolls/sources/detect.py`, `tests/test_detect.py`). The deliberate
  match to the folding registries (ADR 0034/0036/0039/0088): Hex's
  canonical form is lowercase, so folding is the forgiving choice, not a
  risk. The docs host `hexdocs.pm` is left to `web` (it serves rendered
  docs, not package metadata); the package list and search pages carry no
  package name and become the source with no fetchable item — the family's
  pattern.
- **Fetch reads the package document.** The adapter GETs
  `hex.pm/api/packages/<name>` and maps `meta` directly; there is no
  `versions` collection to rank — `releases` is read only to date the
  scroll.
- **The description is the content; the scroll is metadata-only.** The
  `meta.description` is the `summary`; there is no `extracted_text` and no
  secondary download — the honest reflection of an API that exposes no
  README (it ships only in the tarball). The `web`-scrape baseline captured
  no structured metadata, so nothing is lost.
- **Concepts are empty by design.** Hex declares no keywords, so `concepts`
  is always `()` — not an absent field that might be populated elsewhere,
  but a structural gap (RubyGems'/Go's posture, ADR 0040/0042). This is the
  axis on which Hex and pub.dev — twins in field layout — diverge: pub's
  `topics` feed the concept graph, Hex's metadata cannot.
- **Licenses become `tags`.** The `meta.licenses` array is SPDX
  identifiers — a structured facet, the slot PyPI's classifiers, crates'
  categories, and RubyGems' licenses fill (ADR 0034/0036/0040). Hex has no
  `type` or classifier analog, so `tags` is the license set alone.
- **The links map's values become `links`.** `meta.links` is a
  `{label: url}` map; every http(s) value becomes a `link` in the map's
  order — `Changelog`, `Docs`, `Website`, and crucially `GitHub`, whose
  clean repo URL (its `git+`/`.git` defensively folded, the crates/RubyGems
  rule) resolves to the package's github repo through `scrolls related`
  (the package↔repo edge, verified live with `ecto` →
  `github.com/elixir-ecto/ecto`). The Hex page itself (the canonical URL)
  is dropped and trailing-slash variants collapse.
- **`published_at` is the latest stable release's publish time.** The
  release whose `version` equals `latest_stable_version` (else
  `latest_version`) supplies `inserted_at` — an ISO 8601 timestamp with
  microseconds and a `Z` suffix, normalized through the shared `to_utc_iso`
  (ADR 0024) — with the newest release as the order-independent fallback
  and the feed/import seed (ADR 0021) as the last resort. Matching the
  version rather than trusting list position is the robust choice (a
  pre-release could top the list).
- **Author is left unset.** Hex exposes `owners` (a maintainer list with
  emails) but no clean author/byline field, so `author` is left `None`
  rather than synthesized from owner data — the honest gap, and a reason
  not to store the PII-bearing `owners` list verbatim either.
- **Hex packages classify as `tool`.** A published package is something you
  install and use, so `hex` joins `pypi`, `npm`, `crates`, `packagist`,
  `rubygems`, `go`, and `pub` as a curated-source `tool` in the rules
  engine (`src/scrolls/classify.py`, ADR 0004) — distinct from github's
  `project` (a repo to read).

Per the no-network rule (ADR 0001), the JSON GET is injected; tests run
against a recorded package document (`tests/test_hex.py`), and the decision
was smoke-tested end to end against the live API (`ecto`, `phoenix`, the
case-folded `Ecto`).

## Consequences

- A saved Hex package becomes a clean scroll — name, publish date,
  description, license-as-tags, and the links-map links — instead of a
  `trafilatura` scrape. The eighteenth keyless fetch adapter; `x` (Field
  Theory import only, ADR 0009) remains the sole detected source without
  one.
- The package family now spans **eight** registries across Python,
  JavaScript, Rust, PHP, Ruby, Go, Dart/Flutter, and Elixir/Erlang. Hex
  and pub.dev are the family's pair of twins-in-layout that diverge on the
  concept signal: identical `meta`/`pubspec` field shapes, but pub's
  `topics` feed the KB concept graph where Hex's metadata carries no
  keywords — the clean illustration that the registry's *data*, not the
  adapter, decides whether a package can join the concept graph.
- The links-map extraction is a small new shape for the family: where
  RubyGems/pub read named scalar fields (`homepage_uri`, `repository`),
  Hex stores its outbound URLs in a `{label: url}` map, so the adapter
  iterates the values — and the `GitHub` entry still wires the package↔repo
  edge the family shares.
- The full package document (minus the bulky `releases` list) is kept
  verbatim in `raw_text`, so a future enrichment — the README from the
  tarball, the dependency requirements, the download counts, the build
  configs — can expand a package without a refetch, the raw-record-spine
  discipline every API adapter follows.
- Other JSON-metadata registries remain reachable on the same pattern when
  a developer's saved set calls for them — NuGet (.NET), Hackage (Haskell),
  CPAN (Perl), pub's and Hex's remaining cousins — none claimed until a
  saved URL needs one.
