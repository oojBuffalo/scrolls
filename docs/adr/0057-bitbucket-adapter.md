# ADR 0057: Bitbucket Cloud adapter — the fourth code host, single-service like github

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

GitHub (ADR 0007), GitLab (ADR 0055), and Gitea/Forgejo (ADR 0056) cover three
of the four big code hosts. `docs/architecture.md`'s "More code hosts" next-step
named the fourth explicitly: **Bitbucket** — "a single API host like github" —
"the remaining big one." A saved `bitbucket.org/<workspace>/<repo>` URL detected
as `web` lost everything the same repo on github.com would have kept:
description, README, language. The github adapter is again a near-complete
template (keyless repo metadata plus an optional README), and the README-fetch
shape carries over almost verbatim from gitea (ADR 0056).

Two facts about Bitbucket shape the adapter, and one is the opposite of gitea.

## Decision

1. **Single fixed API host, flat `<workspace>/<repo>` identity (github's shape).**
   Bitbucket *Cloud* is one hosted service: every public repo's metadata comes
   from `api.bitbucket.org/2.0/repositories/<workspace>/<repo>`. So — unlike
   gitea, whose API lives on each instance's own host and which therefore carries
   the host *in* its id (ADR 0056) — Bitbucket is host-scoped like github/gitlab
   with a single hardcoded API root, and the identity is the flat two-segment
   `<workspace>/<repo>`, github's rule. Bitbucket *Server*/Data Center is the
   self-hosted product, but it is a different API (`/rest/api/1.0/`) on arbitrary
   hosts with no universal shape tell, so it is deferred exactly as self-hosted
   GitLab is (ADR 0055).

2. **Identity folded lowercase (gitlab's rule, not github's verbatim).**
   Bitbucket auto-lowercases repo slugs, mints lowercase workspace ids, and
   routes case-insensitively — a live `GET` of `Atlassian/Atlassian-Plugins`
   (mixed case) returns 200 and the canonical `full_name` comes back lowercase.
   So `<workspace>/<repo>` is folded lowercase, the crates/Packagist/gitlab
   case-fold (ADR 0036/0039/0055): `/Workspace/Repo` and `/workspace/repo` dedupe
   to one item. (github keeps `owner/repo` verbatim because its canonical form
   preserves display case; Bitbucket's canonical form is lowercase, so folding
   *is* the canonical id.) Reserved first-segment site routes (`account`,
   `dashboard`, `snippets`, `product`, …) and a bare workspace page carry no repo
   and resolve to the source with no fetchable item — github's pattern.

3. **No topics, so `concepts` empty by design; `language` is the one `tag`.**
   Bitbucket Cloud has no repository-topics feature — there is nothing
   author-curated to feed the KB's concept pages — so `concepts` are empty *by
   design*, the Go/RubyGems posture (ADR 0040/0042), not a degrade. The repo
   payload carries no inline license either, but it does carry `language`, so
   that one structured facet becomes the single `tag` (the registries'
   SPDX-license-as-tag slot, ADR 0036/0055). github ignores `language` because
   its richer `topics` already fill the facet role; Bitbucket has no topics, so
   using `language` is the "fill what the platform offers" principle (ADR 0002),
   not overdesign. An unset language yields no tag.

4. **README via the `/src/<mainbranch>` route, README.md-first then listing.**
   Bitbucket exposes no auto-detecting `/readme` endpoint (github) and no
   `/raw/` route (gitea); a file's body comes from
   `GET /2.0/repositories/<ws>/<repo>/src/<commit>/<path>`, where `<commit>`
   accepts a branch name. So the adapter reads the repo's `mainbranch.name` and
   fetches `README.md` first (one fast keyless GET, the dominant case), falling
   back to a root listing (`/src/<branch>/?pagelen=100`, whose entries are
   `{type: "commit_file"|"commit_directory", path}`) to find a differently-named
   README (`README.rst`) only when the fast path misses — the gitea README
   pattern (ADR 0056) adapted to Bitbucket's src endpoint, a `.md` preferred over
   other formats, directories named like `readme` ignored. The README is optional
   enrichment (ADR 0003/0007 posture): no main branch on an empty repo, a 404, a
   blank body, or a failed listing all degrade to a metadata-only scroll, with
   `provenance.extraction_method` recording `bitbucket-api:repo+readme` vs
   `bitbucket-api:repo`. `FetchError` is reserved for missing identity and the
   repo request failing.

5. **Field mapping, faithful to github.** title = `full_name`, author =
   `owner.display_name` (the human name, with `nickname`/`username` handle
   fallbacks — github's `owner.login` analog), `published_at` = `created_on`
   (microsecond RFC 3339, normalized by `to_utc_iso`), canonical_url =
   `links.html.href`, summary = `description`. `content_hash` covers the README
   when present, else the repo payload; both raw payloads stay in `raw_text`.

6. **Keyless, optional `BITBUCKET_TOKEN` (Bearer).** Public repos need no auth.
   A Bitbucket access token / API token authenticates with
   `Authorization: Bearer <token>` (github's Bearer posture, ADR 0007) to lift
   the unauthenticated rate limit and reach private repos. App passwords — which
   use Basic auth with a username — are deliberately not handled: the keyless
   public path is the dominant case.

7. **`bitbucket → project`** in the rules engine (ADR 0004), the same curated
   category github/gitlab/gitea get: a repo is a project to *read*, distinct from
   a package to *install* (the registries' `tool`).

## Consequences

- Bitbucket Server/Data Center (the self-hosted product) is not reached this
  slice — a saved `git.example.com/.../repos/...` gets a `web` scroll. It is a
  different API, so it would be its own adapter, not a detection-only change like
  a new gitea host.
- A repo with no README on its main branch, or a transiently slow root listing,
  yields a metadata-only scroll; the degradation is visible in provenance and
  `scrolls fetch <id>` repairs it.
- Bitbucket items contribute nothing to the concept graph (no topics) — the
  Go/RubyGems trade-off; the `language` tag is the one grouping facet.
- Bitbucket's unauthenticated rate limit makes it a poor bulk-sync source
  without a token, exactly as github/gitlab/gitea — fine for one-off
  `scrolls add`/`ingest`.

## Proof

`src/scrolls/sources/bitbucket.py` with transport-faked tests
(`tests/test_bitbucket.py`): the README.md-first fast path (one GET, no listing),
the main-branch-from-payload src route, the listing fallback for a non-`.md`
README (with the `.md` tiebreak and the directory-named-`readme` guard), the
single fixed API host regardless of workspace, the `language`→`tag` /
empty-`concepts` mapping, the metadata-only degrades (no README, failed listing,
no main branch, blank README), the `display_name`→handle author fallback, and
the keyless/`BITBUCKET_TOKEN` Bearer headers, all offline. Detection and the
`bitbucket → project` rule are pinned in `tests/test_detect.py` (single API host,
lowercase fold, deep-link dedupe, reserved routes) and `tests/test_classify.py`
(`test_bitbucket_is_project`). `FETCH_ADAPTERS["bitbucket"]` registration is
covered by `test_bitbucket_adapter_is_registered`.

Live keyless smoke (the ADR 0007 posture, tests stay offline) validated and
grounded the fixtures against the real API. `GET
/2.0/repositories/atlassian/atlassian-plugins` returned `full_name`,
`owner.display_name`, `links.html.href`, `language` (`"java"`), `mainbranch.name`
(`"master"`), and a microsecond `created_on`
(`2011-10-13T23:37:59.955067+00:00`, normalized by `to_utc_iso`); a mixed-case
request resolved 200 (confirming the lowercase fold); `GET .../src/master/`
listed the root as `commit_file`/`commit_directory` entries; and
`GET .../src/master/README.md` served the raw README keyless. `scrolls ingest`
of the repo (and a mixed-case deep link, which deduped to the same id) produced
a clean `project` scroll with the `java` tag.
