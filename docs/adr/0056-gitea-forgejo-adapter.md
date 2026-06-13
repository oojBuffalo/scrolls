# ADR 0056: Gitea/Forgejo adapter — the third code host, where the API lives on each instance's host

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

GitHub (ADR 0007) and GitLab (ADR 0055) cover the two largest code hosts.
Gitea — and its API-compatible soft-fork Forgejo — is the third: the
lightweight, self-hosted git platform behind Codeberg (a prominent
nonprofit forge running Forgejo) and gitea.com (the Gitea project's own
instance). A saved `codeberg.org/<owner>/<repo>` URL detected as `web` lost
everything the same URL on github.com would have kept — description, topics,
README. ADR 0055's follow-up named Gitea/Forgejo as the next code host, and
the github adapter is a near-complete template: keyless repo metadata plus an
optional README.

One thing makes Gitea unlike both siblings, and it is the decision that
shapes the adapter.

## Decision

1. **The instance host rides in the identity (`gitea:<host>/<owner>/<repo>`).**
   github and gitlab each hardcode one API host (`api.github.com`,
   `gitlab.com/api/v4`) because each *is* a single service. Gitea is software
   deployed per-host: Codeberg's API is `codeberg.org/api/v1`, gitea.com's is
   `gitea.com/api/v1`. So the host must be known to fetch, and it is carried
   in the id the way the Fediverse sources carry theirs (`<host>/<id>`,
   ADR 0049) — the first *code* host to do so. This unifies the two patterns:
   a host-scoped code host whose identity is host-carrying is exactly what a
   self-hosted-across-many-hosts platform needs, and it future-proofs
   self-hosted instances (the moment detection learns a host, the adapter
   already works). The host is folded to its canonical form (`www.` stripped)
   so `www.gitea.com` and `gitea.com` dedupe; owner/repo are kept verbatim
   like github (Gitea routes case-insensitively but preserves display case,
   and the API resolves either).

2. **Two public instances only (host-scoped, like github/gitlab).** Detection
   keys on `codeberg.org` and `gitea.com`. Self-hosted Gitea is the platform's
   common deployment, but a bare repo root (`<instance>/<owner>/<repo>`) has no
   universal shape tell — unlike the Fediverse literals (`/@user`, `/notes/`,
   `/post/<digits>`, `/t/<slug>/<id>`) that anchor a host-less match. So
   self-hosted is deferred exactly as self-hosted GitLab is (ADR 0055): a
   future config-listed host allowlist or an explicit source hint could reach
   it. Because the identity is already host-carrying, adding a host is a
   one-line change with no adapter rework.

3. **One `gitea` source for both Gitea and Forgejo.** Forgejo is a 2022
   soft-fork of Gitea that maintains "Gitea API v1" compatibility — the same
   `/api/v1/repos/...` surface this adapter speaks. So one source/adapter
   serves both, exactly as the `mastodon` source serves GoToSocial and
   Pleroma (ADR 0050): the `source` stays `gitea`, `provenance.adapter` stays
   `gitea` (the adapter that answered), and which software a host runs is not
   read off the URL. Codeberg-on-Forgejo items reading `gitea:` is the same
   accepted naming trade-off a Pleroma post reading `mastodon:` is.

4. **Keyless `GET /api/v1/repos/<owner>/<repo>`, optional token.** Public
   repos need no auth. `topics` is inline on modern Gitea/Forgejo, so repo
   topics become `concepts` like github's (ADR 0007) with no second call —
   unlike old Gitea's separate `/topics` endpoint. Setting `GITEA_TOKEN` (or
   `FORGEJO_TOKEN`) sends Gitea's `Authorization: token <token>` header to
   lift the rate limit and reach private repos — github's optional-token
   posture (ADR 0007), Gitea's header. A single env var applies to whatever
   host the id names, with the honest caveat that a token is valid only on the
   instance that issued it (the multi-host trade-off the per-instance API
   forces).

5. **README: README.md-first via the API raw route, listing fallback.** Gitea
   has no GitHub-style auto-detecting `/readme` endpoint, so the filename
   can't be assumed. Two findings from live verification shaped the fetch:
   - The contents-listing entry's `download_url` is the *web* raw route
     (`/<owner>/<repo>/raw/branch/...`), which gitea.com **303-redirects
     anonymous clients to `/user/login`** — urllib follows it and captures the
     HTML login page. The *API* raw route (`/api/v1/.../raw/<path>`) serves
     the file body keyless, so that is what the adapter uses.
   - Listing a large repo's root (`/contents`) can be slow: **forgejo/forgejo
     timed out** at 30s. So the adapter tries the dominant `README.md` via the
     fast raw route *first* (one GET, the common case) and only falls back to
     the root listing to find a differently-named README (`README.rst`,
     `readme.txt`) — which keeps the common case fast while matching the
     arbitrary-filename coverage github's `/readme` and gitlab's `readme_url`
     give in one call. The README is optional enrichment (ADR 0003/0007
     posture): a 404, a slow/failed listing, or a blank body all degrade to a
     metadata-only scroll, with `provenance.extraction_method` recording
     `gitea-api:repo+readme` vs `gitea-api:repo`. `FetchError` is reserved for
     missing identity and the repo request failing.

6. **Field mapping, faithful to github.** title = `full_name`, author =
   `owner.login`, `published_at` = `created_at`, canonical_url = `html_url`,
   summary = `description`, `concepts` = inline `topics`. Gitea repo metadata
   carries no inline license field (unlike GitLab's `?license=true`), so —
   like github — there is no license `tag`; `tags` stay empty. `content_hash`
   covers the README when present, else the repo payload; both raw payloads
   stay in `raw_text`.

7. **`gitea → project`** in the rules engine (ADR 0004), the same curated
   category github and gitlab get: a repo is a project to *read*, distinct
   from a package to *install* (the registries' `tool`).

## Consequences

- Self-hosted Gitea/Forgejo (the platform's most common deployment) is not
  reached this slice — a saved `git.example.com/<owner>/<repo>` gets a `web`
  scroll. The host-carrying identity means reaching it later is purely a
  detection change (a configured host allowlist), not an adapter rewrite.
- A repo with neither a `README.md` nor a listable root (a transient slow
  `/contents`) yields a metadata-only scroll; the degradation is visible in
  provenance and `scrolls fetch <id>` repairs it.
- A single `GITEA_TOKEN` can't authenticate to two different instances at
  once; the keyless public path (the dominant case) is unaffected.
- Gitea/Forgejo's unauthenticated rate limit makes it a poor bulk-sync source
  without a token, exactly as github/gitlab — fine for one-off
  `scrolls add`/`ingest`.

## Proof

`src/scrolls/sources/gitea.py` with transport-faked tests
(`tests/test_gitea.py`): the README.md-first fast path (one GET, no listing —
the forgejo timeout fix), the listing fallback for a non-`.md` README, the API
raw route vs the login-gated web `download_url` (a named regression), the
inline `topics`→`concepts` mapping, the per-instance API root derived from the
host in the id, the metadata-only degrades, and the keyless/`GITEA_TOKEN`/
`FORGEJO_TOKEN` headers, all offline. Detection and the `gitea → project` rule
are pinned in `tests/test_detect.py` (host-in-id, `www.` fold, deep-link
dedupe, verbatim owner/repo, reserved routes) and `tests/test_classify.py`
(`test_gitea_is_project`). `FETCH_ADAPTERS["gitea"]` registration is covered by
`test_gitea_adapter_is_registered`.

Live keyless smoke (the ADR 0007 posture, tests stay offline) validated and
corrected the fixtures against the real API. `GET
/api/v1/repos/forgejo/forgejo` and `.../gitea/tea` returned inline `topics`,
`full_name`, `owner.login`, `html_url`, and timezone-offset `created_at`
(`2022-11-06T07:24:57+01:00`, normalized by `to_utc_iso`). The contents
`download_url` was confirmed to 303-redirect to `/user/login` on gitea.com,
and the `/api/v1/.../raw/README.md` route to serve the raw README keyless on
both hosts. The first listing-based draft produced an HTML login page as
`extracted_text` and timed out on forgejo/forgejo's root listing; the
README.md-first rewrite ingests both flagship repos to clean Markdown scrolls
in under two seconds.
