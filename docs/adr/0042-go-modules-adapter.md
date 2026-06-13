# 0042: Go modules via the keyless proxy; the last registry on the JSON-metadata pattern

Date: 2026-06-13

Status: accepted

## Context

A developer's saved internet — Scrolls' core audience (IDEAS.md §11) — is
full of package pages, and the Go module page (`pkg.go.dev/<module>`) is
the Go sibling of the PyPI, npm, crates.io, Packagist, and RubyGems pages
the previous five registry adapters claimed (ADR 0034, 0035, 0036, 0039,
0040). Every one of those ADRs named Go modules as the last obvious
adapter on the JSON-metadata pattern (the `proxy.golang.org`
`@latest`/`.info` endpoints). Until now a `pkg.go.dev/...` URL fell
through to the generic `web` adapter (ADR 0001), which runs `trafilatura`
over a JS-rendered docs page: it captures whatever HTML survives but
discards the structured metadata the Go module proxy already holds — the
latest version, the publish time, the dependency graph, the source repo.

Go is different from the other five registries in one decisive way, which
shaped the design — confirmed by smoke-testing the live proxy before
committing, the discipline the prior registry ADRs used.

1. **The proxy is the sparsest metadata source of the family.** A GET of
   `proxy.golang.org/<module>/@latest` returns only
   `{"Version", "Time", "Origin"}` — no description, no keywords, no
   license, no classifiers. There is genuinely nothing to put in `summary`
   (so it stays None — honest, not a synthesized placeholder), nothing for
   `concepts` (empty by design, RubyGems' situation — ADR 0040), and
   nothing for `tags` (Go has no license/classifier facet at all, so even
   the structured-facet slot the other five fill stays empty). The only
   content the proxy carries is the `go.mod` manifest
   (`/@v/<version>.mod`): it declares the module path, the `go` directive,
   and the dependency graph, so it becomes the searchable `extracted_text`
   — the closest honest analog to crates' README (ADR 0036). A `.mod` that
   fails to fetch degrades to a metadata-only scroll (ADR 0002).

2. **Module paths are case-sensitive, and the proxy *case-encodes* the
   request.** A Go module path is `<host>/<owner>/<repo>[/...]` (or a
   vanity path like `golang.org/x/tools`, `rsc.io/quote`). The proxy
   protocol escapes every uppercase letter as `!`+lowercase
   (`github.com/Masterminds/squirrel` →
   `github.com/!masterminds/squirrel`), and an unescaped mixed-case path
   is a 400 ("invalid escaped module path", verified live). So the
   identity is preserved verbatim (npm/RubyGems' rule, ADR 0035/0040 —
   *not* the case-folding PyPI/crates/Packagist apply) and only the proxy
   *request* URL is escaped at fetch time. Folding would corrupt a
   mixed-case module's identity.

3. **The repo link comes from `Origin`, with a path fallback.** `/@latest`
   often carries `Origin.URL` — the actual VCS repository. For a vanity
   path this is the *only* way to learn the repo (`golang.org/x/tools` →
   `go.googlesource.com/tools`, verified live). Older modules omit
   `Origin` (`rsc.io/quote` does), so when it is absent the repo is
   derived from the module path for the well-known VCS hosts
   (`github.com`/`gitlab.com`/`bitbucket.org`); a vanity path with no
   `Origin` honestly yields no link.

## Decision

`scrolls add`/`fetch` of a Go module page runs a new keyless adapter
(`src/scrolls/sources/go.py`):

- **Identity is the module path, verbatim.** `detect_source` claims
  `pkg.go.dev`/`www.pkg.go.dev` (`src/scrolls/sources/detect.py`,
  `tests/test_detect.py`). A pkg.go.dev URL is
  `<module>[@<version>][/<package-in-module>]`; when a version is present
  the module path is unambiguously everything before the `@` (pkg.go.dev
  attaches the version to the module, then any in-module package follows),
  so `gin@v1.12.0` and `gin@v1.12.0/binding` both yield
  `go:github.com/gin-gonic/gin`. Without a version the whole path is the
  module candidate. A real module path's first segment is a domain (it
  contains a `.`), so the standard library (`net/http`, `fmt`) and site
  routes (`about`, `search`, `std`) — first segment with no dot — resolve
  to the source with no fetchable item, the family's pattern
  (ADR 0034–0036, 0039, 0040). The id is kept verbatim because module
  paths are case-sensitive and the proxy escapes the request, not the
  identity.
- **Fetch is two keyless GETs against the proxy.** `/@latest` gives the
  latest version, publish time, and `Origin`; `/@v/<version>.mod` gives
  the `go.mod` manifest. Both the module path and the version are
  case-encoded for the request (`_escape`). The `.mod` GET is capped
  (reusing the `http.get_bytes` `max_bytes` npm introduced, ADR 0035),
  since a go.mod is a few KB. Re-fetching refreshes the scroll to the
  current latest release — the family's "track the package, not a pin"
  choice.
- **The go.mod is the content; the scroll is otherwise metadata-only.**
  The manifest is the `extracted_text` (searchable: module path +
  dependency graph), and the `go.mod` `module` line is the authoritative
  `title` (a module may be declared with different casing than the saved
  page), with the URL-derived module path as the fallback when the go.mod
  is absent. `summary` stays None — the proxy has no description, and a
  synthesized one would be dishonest.
- **`concepts` and `tags` are both empty by design.** Go's proxy carries
  no keywords (so `concepts=()`, RubyGems' structural gap — ADR 0040) and
  no license or classifier facet at all (so `tags=()` too). Go is thus the
  sparsest adapter of the family; the gaps are documented structurally
  rather than back-filled with guessed labels (the rules engine's posture,
  ADR 0004).
- **The source repo is the one `link`, from `Origin` or the path.**
  `Origin.URL` is preferred (the only source of truth for a vanity path);
  the well-known-VCS-host path derivation is the fallback. The `.git`
  suffix is folded so `detect_source` reads a clean `owner/repo` and
  `scrolls related` resolves the link to a saved github repo (the
  package↔repo edge, verified live: a saved `go:github.com/gin-gonic/gin`
  relates to `github:gin-gonic/gin` with reason "links to it"). The
  pkg.go.dev page itself is the `canonical_url`, not a link — the family's
  rule.
- **`published_at` is the version's publish time.** `/@latest` `Time`
  (RFC 3339 with a `Z` suffix, normalized through the shared `to_utc_iso`,
  ADR 0024) is the publish moment, with the feed/import seed (ADR 0021) as
  the fallback.
- **Go modules classify as `tool`.** A published module is something you
  import and use, so `go` joins `pypi`, `npm`, `crates`, `packagist`, and
  `rubygems` as a curated-source `tool` in the rules engine
  (`src/scrolls/classify.py`, ADR 0004) — distinct from github's `project`
  (a repo to read).

Per the no-network rule (ADR 0001), both GETs are injected; tests run
against recorded proxy payloads (`tests/test_go.py`), and the decision was
smoke-tested end to end against the live proxy (`github.com/gin-gonic/gin`,
the vanity `golang.org/x/tools`, the `Origin`-less `rsc.io/quote`, the
mixed-case `github.com/Masterminds/squirrel`).

## Consequences

- A saved Go module becomes a clean scroll — module path, latest version,
  publish date, the go.mod manifest as searchable content, and the source
  repo link — instead of a `trafilatura` scrape of a JS-rendered page. The
  sixteenth keyless fetch adapter; `x` (Field Theory import only, ADR 0009)
  remains the sole detected source without one.
- The package-registry family is now complete on the JSON-metadata
  pattern: PyPI, npm, crates.io, Packagist, RubyGems, and Go modules span
  Python, JavaScript, Rust, PHP, Ruby, and Go. The architecture doc's and
  every registry ADR's "Go modules remain the last obvious registry" note
  is closed.
- Go is the family's honest extreme: with no description, keywords,
  license, or classifiers in the proxy, it contributes nothing to
  `summary`, `concepts`, or `tags`, and the adapter says so structurally
  rather than pretending otherwise. The go.mod manifest carries the scroll
  — the first adapter whose searchable content is a dependency manifest
  rather than prose.
- The `Origin`-or-path repo link enriches the graph for free, and the
  vanity-path case (`golang.org/x/tools` → `go.googlesource.com/tools`)
  proves why `Origin` is preferred: the module path alone could never
  reveal a non-VCS-host repo.
- The full `/@latest` JSON is kept verbatim in `raw_text`, so a future
  enrichment — the package docs from pkg.go.dev, the version list from
  `/@v/list`, the dependency graph parsed from the go.mod — can expand a
  module without a refetch, the raw-record-spine discipline every API
  adapter follows.
