# 0090: NuGet via the flat container + nuspec; the .NET sibling of the package family

Date: 2026-06-13

Status: accepted

## Context

A developer's saved internet — Scrolls' core audience (IDEAS.md §11) — is
full of package pages, and the package-registry family already spans eight
ecosystems: PyPI, npm, crates.io, Packagist, RubyGems, Go, pub.dev, and Hex
(ADR 0034–0036, 0039, 0040, 0042, 0088, 0089). The conspicuous gap was
**.NET** — the one top-tier language ecosystem with no adapter — and ADR
0088/0089 both named NuGet as the next candidate. Until now a
`nuget.org/packages/<id>` URL fell through to the generic `web` adapter
(ADR 0001), which runs `trafilatura` over a JS-rendered page: it captures the
description but discards the author-curated **tags** that would wire the
package into the KB concept graph, the SPDX license, and the repository link.

NuGet's permanent, keyless host `api.nuget.org` exposes the V3 API, but it has
two surfaces and the choice between them is the central decision here. Both
were probed against the live service before committing — the registry ADRs'
discipline.

1. **The registration API is gzip-only and paginates.** The richest single
   document is the registration index
   (`/v3/registration5-gz-semver2/<id>/index.json`): one JSON blob with the
   `published` date, tags as an array, and the description. But the `-gz-`
   endpoint serves **gzip bytes even on a plain GET** (no `Accept-Encoding`
   negotiation, and `Accept-Encoding: identity` does not defeat it — the blob
   is stored compressed), which the shared UTF-8 `http.get_json` cannot decode;
   and for large packages its pages are not inlined but referenced by `@id`,
   so the latest-stable selection can cost an extra fetch. The non-gz
   `registration5-semver1` endpoint is plain JSON but omits SemVer-2.0.0
   versions.

2. **The flat container is plain JSON + a plain XML manifest.** The flat
   container gives `/v3-flatcontainer/<id>/index.json` →
   `{"versions": [...]}` (plain JSON, ascending, always one document) and
   `/v3-flatcontainer/<id>/<version>/<id>.nuspec` → the package manifest
   (plain XML). This is exactly the Go adapter's "proxy version index + a
   manifest file" shape (ADR 0042): two plain requests, stdlib JSON + stdlib
   ElementTree, **no gzip, no pagination**. The nuspec is the authoritative
   manifest and carries everything a scroll needs — `id`, `title`, `authors`,
   `description`, `tags`, `license`, `projectUrl`, `repository`.

The flat container is the robust choice, and its one cost — the nuspec has no
publish date — is an honest, bounded gap, not a correctness risk.

Three further facts shaped the mapping:

3. **Identity is the package id, folded lowercase.** NuGet package ids are
   case-insensitive (the registry routes `Newtonsoft.Json` and
   `newtonsoft.json` alike) and the flat-container path *requires* the
   lowercase form, so the source id folds lowercase — the forgiving
   PyPI/crates/pub/Hex fold (ADR 0034/0036/0088/0089), since the canonical
   form is always lowercase. The registrant's display casing
   (`Newtonsoft.Json`) is read back from the nuspec `<id>` for the title and
   canonical URL, the way crates reads its canonical name back.

4. **Latest *stable* version, then the nuspec.** The flat-container index
   lists every version, and the highest is often a pre-release (live,
   `newtonsoft.json` tops out at `13.0.5-beta1`), so the adapter selects the
   highest *stable* (`-`-free) version by Packagist's comparator-free numeric
   ranking (ADR 0039), with the pre-release pool the fallback for a package
   that has never shipped a stable release.

5. **`<tags>` feed the concept graph; the rest is metadata-only.** NuGet tags
   are author-curated keywords (whitespace-separated by convention) → `concepts`
   like PyPI keywords / github repo topics (ADR 0007/0034) — the payoff that
   makes .NET a first-class concept producer, not a `web`-scrape island. The
   README ships in the `.nupkg`, not the nuspec, so the `<description>` is the
   searchable `summary` and the scroll is honestly metadata-only (RubyGems/Hex,
   ADR 0040/0089).

## Decision

Add a host-claimed `nuget` source and a keyless two-request adapter
(`sources/nuget.py`), the ninth of the package-registry family.

- **Detection** (`detect._nuget_id`). Claim `nuget.org`/`www.nuget.org`
  `/packages/<id>[/<version>]`; identity is the id folded lowercase (validated
  as alphanumeric runs joined by single `.`/`-`/`_`), the version segment
  ignored (the PyPI/npm/crates rule). The packages list, `/profiles/<user>`,
  `/stats`, and search carry no fetchable id.
- **Fetch** (`nuget.fetch_item`). `GET /v3-flatcontainer/<id>/index.json` →
  pick the latest stable version → `GET /…/<version>/<id>.nuspec` → parse the
  `<metadata>` **namespace-agnostically** (the nuspec namespace URI varies by
  schema version — `…/2011/08/`, `…/2013/05/`, … — so children are matched by
  *local* name, the one rule that reads every generation). Map: `<title>` else
  `<id>` → title; `<authors>` → author; `<description>` else `<summary>` →
  summary (no `extracted_text`); `<tags>` split on whitespace/commas/semicolons
  → concepts; the SPDX `<license type="expression">` → the one tag (a
  `type="file"` is a filename, not an SPDX id, so it is skipped); `<projectUrl>`
  + the `<repository url>` → links (the `.git`/`git+` folded so the repository
  resolves to a saved github repo, the **package↔repo edge**); canonical URL
  `https://www.nuget.org/packages/<nuspec-id>` (display casing); `published_at`
  left as the feed seed (the nuspec has no date — Go's honest-empty posture,
  ADR 0042). The nuspec text is kept as `raw_text`.
- **Classification**: `nuget → tool` like every package (ADR 0004).
- The nuspec **is** the metadata, so its failure (a non-200, non-XML body, or a
  missing `<metadata>`) is a FetchError — there is no metadata-only scroll to
  degrade to, unlike Go's optional `go.mod`.

## Consequences

- The .NET ecosystem joins Scrolls, and its tags join the KB concept graph the
  way PyPI's and pub.dev's do. Live-verified keyless ingest: `Polly`
  (BSD-3-Clause, tags → concepts, projectUrl == repository deduped to one
  github link), `Newtonsoft.Json` (`<title>Json.NET</title>` winning over the
  id, MIT, two distinct links, the github repo edge to `JamesNK/Newtonsoft.Json`),
  and `Serilog` (Apache-2.0, structured-logging concepts).
- The flat-container + nuspec path keeps the adapter stdlib-only and free of the
  gzip/pagination complexity the registration API would impose. Should the
  publish date or richer per-version metadata ever matter, the registration
  endpoint is the obvious enrichment — but it would need a gzip-aware fetcher
  and last-page resolution, deliberately deferred.
- The ninth keyless registry; the family now spans Python, JavaScript, Rust,
  PHP, Ruby, Go, Dart/Flutter, Elixir/Erlang, and .NET. **Hackage** (Haskell)
  and **CPAN** (Perl, via the rich MetaCPAN JSON API) remain reachable on the
  same pattern, none claimed until a saved URL needs one.
- Defers: the `.nupkg` README extraction (npm/crates' tarball trick, ADR 0035),
  package-type tags (`DotnetTool` vs the default `Dependency`), the publish
  date, and self-hosted/private NuGet feeds.
