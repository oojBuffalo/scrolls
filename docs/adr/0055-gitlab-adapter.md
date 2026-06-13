# ADR 0055: GitLab adapter — keyless REST API, the second major code host

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

GitHub got the first code-host adapter (ADR 0007), but it is not the only
major one: GitLab is the second-largest public host and by far the most
widely *self-hosted* git platform. A saved `gitlab.com/<group>/<project>`
URL detected as `web` and lost everything an agent wants — description,
topics, README, license — that the same URL on github.com would have kept.
The package-registry family (PyPI → npm → crates → Packagist → RubyGems →
Go, ADRs 0034–0042) showed the project's posture: fill out a category of
sources rather than stop at the first member. GitLab is the obvious next
code host, and the github adapter is a near-complete template — the same
"repo metadata + optional README" shape, keyless, two requests.

Two things differ enough to decide explicitly.

## Decision

1. **gitlab.com only (host-scoped, like github).** Detection keys on the
   `gitlab.com`/`www.gitlab.com` host, mirroring github's host table.
   Self-hosted GitLab is common, but a bare project URL
   (`<instance>/<group>/<project>`) carries no universal shape that says
   "this is GitLab" — unlike the Fediverse sources, whose `/@user`,
   `/notes/<id>`, `/post/<digits>`, `/t/<slug>/<id>` literals anchor a
   host-less match (ADRs 0049–0054). GitLab's distinctive `/-/` separator
   appears only on *sub-resources*, never on a repo root, so shape-detecting
   the root is unreliable. Self-hosted instances are deferred (a future
   config-listed host or an explicit `gitlab:` URL scheme could reach them),
   the same scoping github accepts for GitHub Enterprise.

2. **Nested-group paths, URL-encoded whole.** GitLab supports nested
   groups, so a project lives at a multi-segment path
   (`group/subgroup/project`), not github's flat `owner/repo`. Identity is
   the whole path before any `/-/` sub-resource separator, so a deep link
   (`/-/issues/1`, `/-/blob/main/README.md`) dedupes to its project. The API
   takes that path URL-encoded (`%2F` for the slashes), so the adapter
   `quote(...)`s `source_id` whole rather than splitting on `/`. From the URL
   alone `group/subgroup` is ambiguous (a project in `group`, or a subgroup)
   — the Go-module ambiguity (ADR 0042) — so detection mints the path as a
   candidate and the fetch resolves it: a non-project 404s to a benign failed
   fetch.

3. **Paths folded lowercase.** GitLab forces lowercase path slugs and routes
   case-insensitively, so `/Group/Project` and `/group/project` are one
   project and fold to one id — the crates/Packagist case-fold (ADR 0036,
   ADR 0039), not github's case-preserving `owner/repo`. The fold is safe
   because no GitLab slug can carry uppercase, so it can never collide two
   distinct projects.

4. **Keyless REST API, optional token.** `GET
   /api/v4/projects/<encoded path>?license=true` returns the metadata
   (including the license, which `?license=true` adds without a second
   request). Unauthenticated access works for public projects; setting
   `GITLAB_TOKEN` sends GitLab's `PRIVATE-TOKEN` header to lift the rate
   limit and reach private projects the caller can read — github's optional-
   token posture (ADR 0007), GitLab's header.

5. **README via the `/-/raw/` route, not a second API call.** The project
   payload carries `readme_url`, the README's web *blob*
   (`…/-/blob/<ref>/<file>`). Rewriting the one route segment to its raw twin
   (`…/-/raw/<ref>/<file>`) serves the file body with no HTML chrome and
   avoids a round-trip through the repository file-tree API. The rewrite is
   exact — `/-/` is GitLab's reserved separator, so it never occurs in a slug.
   The README is optional enrichment (ADR 0003/0007 posture): a null
   `readme_url`, a non-blob URL, a 404, or a blank body all degrade to a
   metadata-only scroll, with `provenance.extraction_method` recording
   `gitlab-api:project+readme` vs `gitlab-api:project`. `FetchError` is
   reserved for missing identity and the project request failing.

6. **Field mapping, faithful to github plus a license tag.** title =
   `path_with_namespace`, author = `namespace.full_path` (the owning
   group/user, nested-group-aware), `published_at` = `created_at`,
   canonical_url = `web_url`, summary = `description`, `concepts` = `topics`
   (falling back to the deprecated `tag_list`) like github repo topics
   (ADR 0007). The one enrichment beyond github's mapping: the SPDX license
   key (`gpl-3.0`, `mit`) becomes a single `tag`, the registry adapters'
   license-as-tag facet (ADR 0036, ADR 0039) — cheap here because
   `?license=true` already fetched it. `content_hash` covers the README when
   present, else the project payload; both raw payloads stay in `raw_text`.

7. **`gitlab → project`** in the rules engine (ADR 0004), the same curated
   category github gets: a repo is a project to *read*, distinct from a
   package to *install* (the registries' `tool`).

## Consequences

- Self-hosted GitLab (the platform's most common deployment) is not reached
  this slice. A user who saves a `gitlab.example.com` repo gets a `web`
  scroll. Reaching it needs either a configured host allowlist or an explicit
  source hint — a deliberate future decision, not a silent gap.
- The `group/subgroup` ambiguity means a saved *subgroup* page mints a
  candidate project id that 404s on fetch (benign, like a Go sub-package URL).
  Subgroups and user/group landing pages are not first-class items this slice.
- A transient failure on the raw README GET silently yields a metadata-only
  scroll (the ADR 0003/0007 trade-off); the degradation is visible in
  provenance and `scrolls fetch <id>` repairs it.
- GitLab's unauthenticated rate limit makes it a poor bulk-sync source
  without a token, exactly as github (ADR 0007) — fine for one-off
  `scrolls add`/`ingest`.

## Proof

`src/scrolls/sources/gitlab.py` with transport-faked tests
(`tests/test_gitlab.py`): README-optional semantics, the `topics`→`concepts`
and `license`→`tags` mappings, the nested-group `%2F` path encoding, the
`/-/blob/`→`/-/raw/` README route, and the keyless/`GITLAB_TOKEN` headers,
all offline. Detection and the `gitlab → project` rule are pinned in
`tests/test_detect.py` (nested groups, `/-/` sub-resource stripping, the
lowercase fold, reserved routes) and `tests/test_classify.py`
(`test_gitlab_is_project`). `FETCH_ADAPTERS["gitlab"]` registration is
covered by `test_gitlab_adapter_is_registered`.

Live keyless smoke (the ADR 0007 posture, tests stay offline) validated the
field assumptions the fixtures encode against the real API:
`GET /api/v4/projects/inkscape%2Finkscape?license=true` returned
`path_with_namespace`, `web_url`, `description`, a millisecond-precision
`created_at` (`2017-06-09T14:16:35.615Z`, normalized by `to_utc_iso`),
identical `topics`/`tag_list` (confirming the fallback), `namespace.full_path`,
`license.key`, and a `readme_url` of exactly the `…/-/blob/master/README.md`
shape — whose `/-/raw/master/README.md` rewrite served the raw README text
with no auth.
