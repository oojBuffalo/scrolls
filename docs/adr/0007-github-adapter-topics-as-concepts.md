# ADR 0007: GitHub adapter — keyless REST API, repo topics as concepts

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

GitHub is the first post-MVP source (README "Initial platform targets",
IDEAS.md §6 "then add: GitHub repos"). The rest of the pipeline already
anticipated it: `detect.py` maps `github.com/<owner>/<repo>/…` URLs to
source `github` with id `owner/repo`, and the rules engine (ADR 0004)
carries a curated `github → project` category. Separately, the KB
compiler (ADR 0005) builds concept pages from item `concepts`, but no
adapter had ever populated that field — the concept layer existed only
as dead code paths.

## Decision

1. **Repo-level granularity.** Any repo-shaped GitHub URL (including
   deep links like `/issues/7`) resolves to the repository item, per the
   existing detect behavior. Issues/releases as first-class items are
   future slices.
2. **Keyless GitHub REST API, optional token.** Two GETs over the shared
   stdlib transport: `GET /repos/{owner}/{repo}` for metadata and
   `GET /repos/{owner}/{repo}/readme` for content. No new dependencies.
   Unauthenticated calls are rate-limited to 60/hour — fine for one-off
   `scrolls add`; setting `GITHUB_TOKEN` (or `GH_TOKEN`, the `gh` CLI
   convention) sends a Bearer token and lifts the limit to 5000/hour.
   This added an optional `headers` parameter to `http.get_text/get_json`
   (backward compatible; header construction lives in the adapter as a
   pure, testable `_api_headers()`).
3. **README via the base64 JSON endpoint, decoded locally.** The raw
   media type (`Accept: application/vnd.github.raw+json`) would return
   plain text, but the default JSON payload carries the same bytes
   base64-encoded and works with the existing `get_json` transport
   unchanged. `b64decode` discards GitHub's newline chunking.
4. **The README is optional enrichment** (the youtube-transcript posture
   from ADR 0003): a missing/empty/oddly-encoded README degrades to a
   metadata-only scroll at stage `fetched`, with
   `provenance.extraction_method` recording `github-api:repo+readme` vs
   `github-api:repo`. `FetchError` is reserved for missing identity
   (reserved paths like `/explore` detect with no repo id) and repo
   request failures.
5. **Repo topics become `concepts`** — the headline of this slice.
   Topics are author-curated, already-slugged labels, so they meet the
   project's "honest, no guessing" classification posture (ADR 0004)
   without any extraction heuristics. This is the first producer for the
   `concepts` field, which activates the KB compiler's concept pages.
   `language`/`license` are deliberately not mapped to `tags`/`domain` —
   no rollup consumes them yet, and inventing semantics early is how
   categories rot.
6. **Field mapping:** title = `full_name` (disambiguates same-named
   repos in KB lists), author = `owner.login`, `published_at` =
   `created_at` (first adapter to set it), summary = `description`,
   canonical_url = `html_url`. `content_hash` covers the README when
   present, else the repo payload. Both raw payloads are kept in
   `raw_text` for rebuilds.

## Consequences

- A transient network failure on the README request silently yields a
  metadata-only scroll (same trade-off ADR 0003 accepted for
  transcripts); the degradation is visible in provenance and
  `scrolls fetch <id>` repairs it.
- Repos without topics produce no concepts — concept pages only ever
  reflect curated data, and most of the library stays concept-less until
  more producers (wikipedia categories, an LLM engine) land.
- The unauthenticated rate limit makes github a poor bulk-sync source
  for now; bulk import would want a token or a sync-shaped slice.
- CLI tests that needed an adapterless source for skip/failure paths now
  use arxiv instead of github.

## Proof

`src/scrolls/sources/github.py` with transport-faked tests
(`tests/test_github.py`, end-to-end CLI + KB test in `tests/test_cli.py`),
and live keyless smoke tests: `scrolls ingest
https://github.com/oojBuffalo/scrolls` produced a rendered `project`
scroll with the real README; `https://github.com/simonw/datasette`
carried 11 topics that `scrolls kb` compiled into 11 concept pages with
backlinks (`library/concepts/sqlite.md` → the datasette scroll).
