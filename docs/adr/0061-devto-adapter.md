# ADR 0061: DEV (dev.to / Forem) adapter — turning a `web` island into a concept-graph citizen

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

dev.to is one of the largest developer-blogging communities, built on the
open-source Forem platform, and a common save target for Scrolls' audience
(IDEAS.md §6). Until now a saved `dev.to/<user>/<slug>` article fell through to
the generic `web` adapter (ADR 0001): `trafilatura` would extract the article
*text*, but everything structured the platform publishes was lost — and one loss
matters more than the rest. A `web` scroll has **no `concepts`** (the web adapter
produces none), so a saved dev.to post became a concept-less island: invisible to
`scrolls related`, the concept facets (ADR 0059), the KB concept pages (ADR
0005), and a context bundle's connected-scrolls signal. The post sat in the
library but never joined its graph.

Forem exposes a stable, keyless JSON API. A single
`GET https://dev.to/api/articles/<user>/<slug>` returns the *entire* article in
one request — title, the byline author, the author's Markdown body, the curated
tags, the canonical URL, and the cover image — with no auth and no second call
(Lobsters' one-request economy, ADR 0046). The adapter contract (ADR 0002) and
the github topics-as-concepts pattern (ADR 0007) make this a near-template build;
the novelty is entirely in three platform facts.

## Decision

Add `devto`, the twenty-seventh keyless adapter.

1. **Identity is `<user>/<slug>`, folded lowercase.** A dev.to article lives at
   `/<handle>/<slug>` — github's flat two-segment shape — so the first two path
   segments are the identity and a deeper link (`/comments`, a series page)
   dedupes to the article by taking only those two (`_devto_id`). The fetch hits
   `/api/articles/<handle>/<slug>` with exactly that pair. The id is folded
   lowercase, **the opposite of github's verbatim rule**: Forem mints lowercase
   handles and lowercase slugs, the canonical URL is lowercase, and the API is
   *case-sensitive* — a live `GET` of `/api/articles/DevTeam/...` returns **404**
   while the lowercase form returns 200 — so folding both dedupes a mixed-case
   paste *and* aims at the one form that resolves (the gitlab/bitbucket/crates
   fold, ADR 0055/0057/0036). There is no `JSONStream`-style mixed-case name to
   preserve (unlike npm/github) because Forem does not mint them.

2. **The URL handle is the author *or organization*; the byline is the person.**
   A subtlety the live API surfaced: for an organization post, the URL handle is
   the *org* (`dev.to/devteam/...`) while the byline `user` is a *person*
   (`jess` / "Jess Lee"). The fetch endpoint keys on the URL handle (the org),
   not the author — confirmed live: `/api/articles/devteam/<slug>` is 200,
   `/api/articles/jess/<slug>` is 404. So `source_id` carries the URL handle (what
   the API needs) and `author` reads `user.name` (the human), falling back to
   `user.username` then None. The org is in the payload's `organization` field,
   not the byline.

3. **Tags → `concepts` (the whole point); `tags` stays empty.** The curated
   `tags` (`python`, `api`, `webdev`) become `concepts` the way github repo
   topics do (ADR 0007) — the structured signal a `web` scrape can never
   produce, wiring the post into the concept graph. They are topical, not a
   license/classifier facet, so the `tags` field stays empty (github's posture,
   ADR 0007; not the registries' SPDX-tag slot). The API gives both a `tags` list
   and a comma-joined `tag_list`; the list is preferred, the string split as a
   fallback, results deduped order-preserving.

4. **The cross-post original is a cross-source edge, not the canonical.** dev.to
   records an author's original blog URL in `canonical_url` when the post was
   cross-posted. The scroll's own `canonical_url` is the dev.to permalink (the
   canonical location of *this* artifact); the *external* original is a different
   artifact, so it rides in `links` as the cross-source edge `scrolls
   related`/`graph` resolves (ADR 0044) — but only when `canonical_url` actually
   points elsewhere. A self-canonical article (the common case) adds no link.

5. **`body_markdown` is the searchable text; `description` is the summary.** The
   author's Markdown body is already Markdown (no HTML grammar needed — Lobsters'
   `*_plain` economy, ADR 0046), tidied only for line endings and blank runs, and
   becomes `extracted_text`. The summary prefers dev.to's own `description`
   excerpt, falling back to the body's lead paragraph (Wikipedia/HN's lead), then
   to a `"N reactions, M comments"` engagement status (HN's link-post pattern,
   ADR 0031), then None for a bare stub (the honestly-empty posture, ADR 0004).
   The `cover_image` (else `social_image`) becomes a single `thumbnail` media ref
   (the youtube/Discourse convention, ADR 0011). The raw API object stays in
   `raw_text` for rebuilds; `content_hash` covers the body when present, else the
   payload, and `provenance.extraction_method` records `devto-api:article` vs
   `devto-api:metadata`. `FetchError` is reserved for a missing/malformed id, the
   request failing (a 404 raises before the body is read), and a response with no
   title.

6. **No platform category — unclassified by default.** dev.to is heterogeneous
   (tutorials, opinions, project show-and-tells), so it gets *no* curated source
   category. An item flows through the title rules (a "Getting started" →
   tutorial, "Why I" → opinion) and otherwise stays honestly unclassified —
   Hacker News's/Lobsters'/Bluesky's posture (ADR 0031/0046/0048), not a guessed
   default. The LLM engine can still assign one later.

7. **Keyless, host-scoped to dev.to.** Public articles need no auth. Self-hosted
   Forem instances are deferred: a bare article URL on an arbitrary host has no
   shape tell (it looks like any blog), exactly as self-hosted GitLab/Gitea/
   Bitbucket-Server are deferred (ADR 0055/0056/0057). No optional token is wired
   — unlike the code hosts, the public read path has no rate-limit lever worth a
   header this slice.

## Consequences

- A saved dev.to article now joins the concept graph it was excluded from as a
  `web` item — the concrete payoff. Re-adding a previously-`web`'d dev.to URL
  mints a *different* id (`devto:<user>/<slug>` vs `web:<hash>`), so the two do
  not auto-merge; `scrolls doctor` is not involved (different source, not a
  pre-normalization duplicate — ADR 0026). This is acceptable: the adapter is for
  new saves and re-adds, and the `web` copy can be `scrolls rm`'d.
- Self-hosted Forem (`forem.example.com`) still gets a `web` scroll. Reaching it
  would need a configured host allowlist or an explicit source hint, the same
  open door left for self-hosted GitLab/Gitea (ADR 0055/0056).
- The body is the author's raw Markdown including any Forem Liquid embeds (`{%
  embed %}`); they are left intact as honest source text rather than stripped —
  they carry URLs and are low-noise. A future enrichment could resolve them.
- dev.to has no rate-limit token wired, so it is fine for one-off
  `scrolls add`/`ingest`; a large bulk run would want pacing (the `--limit`
  batch flag already provides it).

## Proof

`src/scrolls/sources/devto.py` with transport-faked tests
(`tests/test_devto.py`, fixtures trimmed from the real API): the
tags-as-concepts join (and the `tag_list` string fallback, order-preserving
dedupe), the org-post byline (author = person, not the URL handle), the
cross-post `canonical_url` → `links` edge (and the self-canonical no-link case),
the `cover_image`/`social_image` thumbnail (and the non-http drop), the
`description` → lead → engagement → None summary ladder with singular units, the
metadata-only degrade (`devto-api:metadata`), identity/URL preservation, the
seeded-`published_at` fallback, the requested API URL, and the missing-id /
not-found / request-failed `FetchError`s — all offline. Detection is pinned in
`tests/test_detect.py` (lowercase fold, the org handle, deep-link dedupe,
reserved `t`/profile/site routes), and the unclassified-by-default posture in
`tests/test_classify.py` (`test_devto_stays_unclassified_like_hacker_news`,
`test_devto_tutorial_title_still_wins`).
`FETCH_ADAPTERS["devto"]` registration is covered by
`test_devto_adapter_is_registered`.

Live keyless smoke (the ADR 0007 posture, tests stay offline) grounded the
fixtures against the real API. `GET /api/articles/devteam/what-was-your-win-this-week-4k11`
returned the org/byline split (`organization.username` `devteam`, `user.name`
"Jess Lee"); a mixed-case `/api/articles/DevTeam/...` returned 404 (confirming
the lowercase fold is the only resolving form); and a cross-posted article
(`/odeeb/the-sec-edgar-api-...`) carried `canonical_url`
`https://datatooly.xyz/sec-edgar-search/` ≠ its dev.to `url`. `scrolls ingest`
of that article produced a clean scroll with `concepts`
`["api","python","finance","datascience"]`, the external blog in `links`, a
`thumbnail` media ref, and the dev.to permalink as canonical.
