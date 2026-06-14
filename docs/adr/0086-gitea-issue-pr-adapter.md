# ADR 0086: Gitea/Forgejo issues and pull requests — the github thread template, keyless to the comments

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

ADR 0085 set the template for carrying discussion threads onto the remaining
code hosts and named the next two: **Gitea unifies issue/PR numbering like
github (one marker), Bitbucket splits like gitlab (two).** This is the Gitea
slice.

The Gitea/Forgejo adapter (ADR 0056) covers a repository — its metadata and
README. But `_gitea_id` collapsed *every* `<host>/<owner>/<repo>/…` URL to the
repo, so a saved **issue** (`/issues/<n>`) or **pull request** (`/pulls/<n>`)
URL silently deduped to the repo and produced its README scroll, discarding the
discussion — the same gap ADR 0084/0085 closed on github/gitlab. A thread is
often *more* valuable agent context than the README (IDEAS.md §11), and Gitea
issues/PRs are the discussion-aggregator family Scrolls already serves
(HN/Lobsters/Discourse, ADR 0031/0046/0054) on the third code host.

Three facts about Gitea/Forgejo, verified live against Codeberg, shape the
decision:

1. **Numbering is unified, like github.** A single
   `GET /api/v1/repos/<o>/<r>/issues/<index>` serves both issues and PRs — a PR
   carries a `pull_request` object — and issues and PRs share one per-repo index
   namespace. So one `#` marker disambiguates (unlike gitlab's separate iid
   sequences, which forced two markers in ADR 0085).
2. **The PR web path is plural `/pulls/<n>`** (e.g.
   `codeberg.org/forgejo/forgejo/pulls/13082`), *not* github's singular
   `/pull/<n>`. This is the one divergence detection must encode.
3. **The comments endpoint is keyless.** `/issues/<n>/comments` returned the
   conversation to an anonymous caller (verified `200`), unlike gitlab, whose
   `/notes` endpoint 401s without a token (ADR 0085). So the common keyless case
   reaches the whole conversation with no `GITEA_TOKEN`/`FORGEJO_TOKEN`.

## Decision

Extend the **`gitea` source** to cover issues and pull requests as a second
content kind, applying the github thread template (ADR 0084) — the one-source-
many-kinds shape (ADR 0041), not a new source. The identity is
`<host>/<owner>/<repo>#<n>`: the host stays in the id because the Gitea API
lives on each instance's own host (the per-instance identity, ADR 0056), and
`#<n>` is the thread marker the adapter dispatches on. Because numbering is
unified, **one** `#` marker suffices — github's rule, not gitlab's two.

1. **Detection — `<host>/<owner>/<repo>#<n>` for a thread, the repo otherwise.**
   `_gitea_id` claims `/issues/<n>` and the web PR path `/pulls/<n>` (plural,
   Gitea's UI route — the divergence from github's singular `/pull/<n>`) when
   the number is all digits. A deep link into the thread (`/pulls/<n>/files`, a
   dropped `#issuecomment-…` fragment) still dedupes to it because the number is
   the fourth path segment. The issue/PR *lists* (`/issues`, `/pulls`, no
   number) and every other sub-resource (`/src/branch/...`) collapse to the repo
   exactly as before. `#` never appears in a repo `source_id`, so it is a safe
   dispatch sentinel and the repo path is byte-unchanged.

2. **One adapter, dispatched on `#`.** `fetch_item` routes a `#`-bearing id to
   `_fetch_thread` and leaves the repo path untouched. The issues endpoint
   serves both kinds, so one GET fetches the thread; comments cost a second GET
   (`?per_page=100`), taken only when the thread has any (`issue["comments"]`)
   and **degrading to body-only on failure** — the github/HN economy
   (ADR 0084/0031). The body is already Markdown, so there is no HTML to strip
   (Lobsters' economy, ADR 0046).

3. **Body + bylined comments → `extracted_text`.** The thread body leads, each
   comment follows bylined `#### Comment by <user>` (the github/Lobsters byline,
   ADR 0084/0046). A body-less thread contributes only its comments; a thread
   with neither degrades to metadata-only. `summary` is the body's lead
   paragraph, else the engagement (`"Gitea discussion: N comments."`) — the
   honest-status fallback (ADR 0084/0031). "Gitea" names the source because one
   adapter serves both Gitea and Forgejo and the URL does not say which.

4. **Labels → `concepts`; kind + state → `tags`.** Issue/PR **labels** are the
   curated topical facet → `concepts` (the github-topics rule, ADR 0007). The
   **kind** (`issue` / `pull request`) and **state** → `tags`. A PR's
   `pull_request.merged_at` distinguishes a **merged** PR from a closed-unmerged
   one without a second GET (Gitea exposes the same field github reads,
   ADR 0084), and the state vocabulary (`open`/`closed`/`merged`) **matches
   github's directly** — Gitea reports `open`/`closed`, no `opened`→`open`
   normalization gitlab needed — so a `--tag merged`/`open` query spans github,
   gitlab, and gitea alike.

5. **The repo edge + body links.** A `<host>/<owner>/<repo>` link makes the
   **thread↔repo edge** `scrolls related`/`graph` resolves to the saved repo
   item, and http(s) URLs scanned from the body become outbound edges — the
   social-post body scan (ADR 0051), deduped and never self-linking the thread.

6. **No category default — unclassified.** A thread is heterogeneous, so it gets
   *no* curated source category. The `gitea → project` rule applies only to
   repos: in `classify.py`, a `gitea` item whose `source_id` carries a `#`
   returns `None` and falls through to the title rules (a "How to…" issue is
   still a `tutorial`), else stays honestly unclassified — the
   github/HN/Lobsters posture (ADR 0084/0031/0046). gitea joins
   github/gitlab/crossref/zenodo/huggingface as a special-cased curated source
   rather than a flat entry in `_CURATED_SOURCE_CATEGORIES`.

**Title leads with the host-free cross-reference.** `_thread_title` builds
`owner/repo#<n>: <title>` — *without* the host, matching the repo scroll's title
(its `full_name`, `owner/repo`) and the way Gitea references an issue
(`owner/repo#<n>`). The host stays in the id and `canonical_url` for
disambiguation across instances; titles need not be globally unique (the
github/gitlab titles aren't either). The RFC number-leads-title rule
(ADR 0066/0084) keeps a search hit self-identifying.

**Keyless, the gitea token posture.** `_fetch_thread` reuses `_api_headers`
(ADR 0056): keyless by default, `GITEA_TOKEN`/`FORGEJO_TOKEN` →
`Authorization: token …` to lift the rate limit and reach private repos.
Because the comments endpoint is keyless, the common case needs no token —
a genuine improvement over gitlab (ADR 0085). `FetchError` is reserved for a
missing/malformed thread id, the thread request failing, and a payload with no
`number`; a comments failure only degrades. Author and comment bylines read
`login` then `username` (the repo adapter's `_author` rule — Gitea carries both).

## Consequences

- A saved Gitea/Forgejo issue/PR URL now becomes a real discussion scroll —
  title, author, dates, searchable body and conversation, labels as concepts,
  the thread↔repo edge — instead of silently producing the repo's README. This
  is a deliberate **behavior change**: `tests/test_detect.py` previously pinned
  `…/issues/123 → <host>/<owner>/<repo>`; it now pins `…#123`. An issue URL
  added before this change resolved to the repo id, so the two never collide;
  the new thread item is simply additional.
- The gitea source now spans two categories — a repo is a `project`, a thread
  is unclassified — the same per-kind split github/gitlab/huggingface/zenodo
  carry. `list_sources`/`facets` still report one `gitea` source; the `#` in the
  id is the only tell.
- The three code hosts with web-discoverable thread URLs (github, gitlab, gitea)
  now all carry threads, with two identity shapes the hosts forced: github's and
  gitea's unified `#<n>` (gitea adding the host prefix its per-instance API
  needs), gitlab's split `#`/`!`. The thread `tags` vocabulary
  (`issue`/`pull request`/`merge request`, `open`/`closed`/`merged`) is now
  uniform across all three, so cross-host `--tag` filters work.
- **Deferred:** Bitbucket issues/PRs — the next slice, and the gitlab-shaped one
  (Bitbucket splits issue/PR numbering, `/issues/<n>` vs `/pull-requests/<n>`,
  so it needs two markers like gitlab); self-hosted Gitea threads (detection is
  host-scoped to Codeberg + gitea.com, as repos are, ADR 0056); PR **diff-line**
  review comments (the conversation comments are what a reader wants, the
  review thread a richer second slice — the github/gitlab deferral); comment
  **pagination** beyond the first 100 (one GET covers essentially every real
  thread); and inline issue **images** as media.

## Proof

`src/scrolls/sources/gitea.py` `_fetch_thread` with the transport-faked tests
in `tests/test_gitea.py` (fixtures trimmed from the real API): the thread-field
mapping with the host-free title (`test_fetch_thread_maps_fields`), the
body+bylined-comments `extracted_text`
(`test_fetch_thread_body_and_comments_become_extracted_text`), the repo edge
plus body-URL links with no self-link
(`test_fetch_thread_links_carry_the_repo_edge_and_body_urls`), the merge-aware
PR tagging (`test_fetch_pull_request_is_tagged_and_merge_aware`), the
comments-skipped-when-none (`test_fetch_thread_skips_comment_request_when_there_are_none`),
the per-instance API root (`test_fetch_thread_api_root_varies_by_instance_host`),
the requested URLs (`test_fetch_thread_requests_the_expected_api_urls`), the
comments-failure degrade (`test_fetch_thread_degrades_when_comments_fail`), the
empty-body engagement summary (`test_fetch_thread_with_empty_body_summarizes_engagement`),
the `raw_text` round-trip (`test_fetch_thread_keeps_raw_records_for_rebuilds`),
and the request-failed / malformed-id / no-number `FetchError`s — all offline.
Detection is pinned in `tests/test_detect.py` (issue and PR URLs → `…#<n>`, the
plural `/pulls/<n>` PR path, deep links deduping to the thread, the
`/issues`/`/pulls` lists and `/src/...` collapsing to the repo, the marker on a
verbatim-cased repo). The no-category-default and title-rule-still-fires
decisions are pinned by `test_gitea_issue_and_pull_request_are_not_projects` and
`test_gitea_thread_still_obeys_title_rules` in `tests/test_classify.py`.

Live keyless smoke (the ADR 0056 posture; tests stay offline) grounded the
fixtures against the real API with `GITEA_TOKEN`/`FORGEJO_TOKEN` unset:
`codeberg.org/forgejo/forgejo/issues/1` fetched as
`gitea:codeberg.org/forgejo/forgejo#1`, title
`"forgejo/forgejo#1: Configure Woodpecker"`, `tags ('issue', 'closed')`, the
thread↔repo link; and the deep-linked merged PR
`codeberg.org/forgejo/forgejo/pulls/13082/files` deduped to `…#13082`, fetched
via the `/issues/13082` endpoint, `tags ('pull request', 'merged')` —
confirming the `pull_request.merged_at` read on real data — with comments
fetched **keyless** (`extraction_method gitea-api:issue+comments`) and labels
`code/api`, `test/not-needed` → concepts.
