# ADR 0087: Bitbucket issues and pull requests — the gitlab two-marker template, completing the code-host thread family

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

ADR 0085/0086 carried discussion threads onto GitLab and Gitea, and ADR 0085
named the last host: **Bitbucket splits issue/PR numbering like gitlab (two
markers).** This is that slice — the fourth and final web-discoverable code host
to gain threads, completing the family github (ADR 0084) / gitlab (ADR 0085) /
gitea (ADR 0086) / bitbucket.

The Bitbucket adapter (ADR 0057) covers a repository. But `_bitbucket_id`
collapsed *every* `bitbucket.org/<workspace>/<repo>/…` URL to the repo, so a
saved **issue** (`/issues/<n>`) or **pull request** (`/pull-requests/<n>`) URL
deduped to the repo and produced its README scroll, discarding the discussion —
the gap ADR 0084/0085/0086 closed on the other three hosts.

Three facts about Bitbucket Cloud, verified live, shape the decision:

1. **Numbering is split, like gitlab.** Issues and PRs have separate number
   sequences on separate endpoints
   (`GET /2.0/repositories/<ws>/<repo>/issues/<n>` vs `…/pullrequests/<n>`), so a
   bare `#<n>` is ambiguous and the kind is part of identity — the gitlab shape
   (ADR 0085), *not* github/gitea's one-endpoint-serves-both unification.
2. **The PR web path is hyphenated `/pull-requests/<n>`** (e.g.
   `bitbucket.org/atlassian/aui/pull-requests/5332`), while the API endpoint is
   the unhyphenated `/pullrequests/<n>`. Detection encodes the web form, the
   adapter the API form.
3. **The native issue tracker is deprecated.** Atlassian has removed Bitbucket
   Cloud's issue tracker from most repos; the issues API returns `410 Gone` on
   every public repo probed. So the **pull-request** path is the common, still-
   supported, live-verifiable case, and the issue path degrades honestly.

## Decision

Extend the **`bitbucket` source** to cover issues and pull requests as a second
content kind, applying the **gitlab** thread template (ADR 0085) — the
one-source-many-kinds shape (ADR 0085/0041), not a new source. The identity uses
gitlab's cross-reference markers: `workspace/repo#<n>` for an issue,
`workspace/repo!<n>` for a pull request. Bitbucket has no native PR-marker
notation of its own, so adopting gitlab's `#`/`!` keeps the cross-host thread
identity uniform (the architecture doc anticipated exactly this). Because
numbering is split, **two** markers are needed — the marker both disambiguates
identity and picks the endpoint.

1. **Detection — `workspace/repo#<n>`/`!<n>` for a thread, the repo otherwise.**
   `_bitbucket_id` claims `/issues/<n>` (→ `#<n>`) and the web PR path
   `/pull-requests/<n>` (→ `!<n>`, hyphenated — the divergence from the API's
   `/pullrequests/`) when the number is all digits. A deep link
   (`/pull-requests/<n>/diff`) dedupes to the thread; the issue/PR *lists* (no
   number) and every other sub-resource collapse to the repo. The path keeps its
   lowercase fold (ADR 0057); `#`/`!` are safe markers (a slug is lowercase
   ASCII).

2. **One adapter, dispatched on the marker.** `fetch_item` routes a marker-
   bearing id to `_fetch_thread`, which the marker tells which endpoint to GET
   (`!`→`/pullrequests/<n>`, `#`→`/issues/<n>`). One GET fetches the thread; its
   comments a second (`?pagelen=100`), **degrading to body-only on failure** (the
   github/HN economy, ADR 0084/0031). The comment GET is gated on the API's
   `comment_count` (PRs carry it) — skipped only when the API reports exactly
   zero; when the field is *absent* (the issue payload, unverifiable against the
   deprecated tracker) the comments are fetched anyway rather than silently
   dropped. The body is already Markdown, so there is no HTML to strip
   (Lobsters' economy, ADR 0046).

3. **Body + bylined comments → `extracted_text`.** A PR's body is its
   `description`, an issue's is `content.raw`. The body leads; each comment
   follows bylined `#### Comment by <display_name>` (the github/Lobsters byline).
   **Deleted** comments and **inline** diff-line review comments are skipped —
   the inline review thread is the deferred PR-review slice (ADR 0084/0085).
   `summary` is the body's lead paragraph, else the engagement a PR shows
   (`"Bitbucket discussion: N comments."`); a body-less *issue* (no count field)
   leaves the summary empty (the github `count is None` posture).

4. **Kind + state → `tags`; no `concepts`.** The **kind** (`issue` / `pull
   request`) and **state** → `tags`, with the state normalized to github's vocab
   so `--tag merged`/`open`/`closed` spans every code host: a PR is
   `open`/`merged` (Bitbucket's `OPEN`/`MERGED`) else `closed` (a `DECLINED` or
   `SUPERSEDED` PR is closed-unmerged, like github's closed PR); an issue is
   `open` for an active state (`new`/`open`/`on hold`) else `closed`
   (`resolved`/`wontfix`/…). **`concepts` stay empty** — Bitbucket has no
   labels/topics feature (the repo adapter's "no concepts by design" posture,
   ADR 0057); the issue `kind`/`priority` enums are kept in `raw_text`, not
   promoted to the concept graph.

5. **The repo edge + body links.** A `bitbucket.org/<workspace>/<repo>` link
   makes the **thread↔repo edge** `scrolls related`/`graph` resolves, and body
   URLs become outbound edges (the social-post body scan, ADR 0051), deduped and
   never self-linking.

6. **No category default — unclassified.** A thread is heterogeneous, so it gets
   no curated source category: in `classify.py`, a `bitbucket` item whose
   `source_id` carries a `#` or `!` returns `None` and falls through to the title
   rules, else stays unclassified — the gitlab two-marker carve-out (ADR 0085).
   bitbucket joins the special-cased curated sources.

**The title leads with the cross-reference, host-free.** `_thread_title` builds
`workspace/repo#<n>: <title>` — the source id verbatim, since Bitbucket Cloud is
a single host and (unlike gitea) no host rides in the id (the gitlab rule,
ADR 0085). Author reads a PR's `author` / an issue's `reporter`, by
`display_name` then a handle (the repo `_author` rule). **Keyless, the bitbucket
token posture** (ADR 0057): `BITBUCKET_TOKEN` → `Authorization: Bearer`.
`FetchError` is reserved for a missing/malformed id, the thread request failing
(a `410` on a disabled issue tracker degrades the *item*, but a hard request
failure raises), and a payload with no `id`.

## Consequences

- A saved Bitbucket issue/PR URL now becomes a real discussion scroll instead of
  the repo's README. This is a deliberate **behavior change**:
  `tests/test_detect.py` previously pinned `…/pull-requests/1 → workspace/repo`;
  it now pins `workspace/repo!1`. A URL added before this change resolved to the
  repo id, so the two never collide.
- **The code-host thread family is complete.** All four web-discoverable hosts
  (github/gitlab/gitea/bitbucket) carry issue/PR threads, across the two
  identity shapes the hosts forced: unified `#<n>` (github/gitea, gitea adding
  the host prefix its per-instance API needs) and split `#`/`!`
  (gitlab/bitbucket). The thread `tags` vocabulary
  (`issue`/`pull request`/`merge request`, `open`/`closed`/`merged`) is uniform,
  so cross-host `--tag` filters work; `concepts` come from labels where the host
  has them (github/gitlab/gitea) and are empty where it does not (bitbucket).
- The bitbucket source now spans two categories — a repo is a `project`, a
  thread is unclassified — the per-kind split the other three carry.
- **Deferred:** Bitbucket's native **issue threads in practice** — implemented
  to the documented API shape and offline-tested, but the tracker is deprecated
  (410 on most repos) so the fetch degrades honestly and could not be live-
  verified; PR **inline diff-line** review comments (the deferred review slice,
  ADR 0084/0085); comment **pagination** beyond the first 100; **Bitbucket
  Server/Data Center** threads (its own `/rest/api/1.0/` adapter, deferred with
  its repos, ADR 0057); and inline images as media. No more web-discoverable
  hosts remain — the family is closed pending a self-hosted-host slice.

## Proof

`src/scrolls/sources/bitbucket.py` `_fetch_thread` with the transport-faked
tests in `tests/test_bitbucket.py` (fixtures trimmed from the real API): the
PR-field mapping with the host-free title and MERGED→merged normalization
(`test_fetch_pull_request_maps_fields`), the body + bylined comments with
deleted/inline skipped (`test_fetch_pull_request_body_and_comments_become_extracted_text`),
the repo edge + body links (`test_fetch_pull_request_links_carry_the_repo_edge_and_body_urls`),
the DECLINED→closed and OPEN states
(`test_declined_pull_request_is_closed_not_merged`, `test_open_pull_request_state`),
the issue endpoint + `content.raw` + reporter author
(`test_fetch_issue_uses_the_issues_endpoint_and_content_raw`), the issue-state
normalization (`test_fetch_issue_state_normalizes_to_closed`), the
`comment_count`-gated second GET
(`test_fetch_pull_request_skips_comment_request_when_count_is_zero`), the marker→
endpoint dispatch (`test_fetch_thread_dispatches_pr_marker_to_pullrequests_endpoint`),
the comments-failure degrade (`test_fetch_thread_degrades_when_comments_fail`),
the empty-body engagement summary
(`test_fetch_pull_request_with_empty_body_summarizes_engagement`), the `raw_text`
round-trip (`test_fetch_pull_request_keeps_raw_records_for_rebuilds`), and the
request-failed (`410`) / malformed-id / no-id `FetchError`s — all offline.
Detection is pinned in `tests/test_detect.py` (issue → `#<n>`, the hyphenated
`/pull-requests/<n>` → `!<n>`, deep links deduping, the lists collapsing, the
marker on a folded path). The no-category-default and title-rule-still-fires
decisions are pinned by `test_bitbucket_issue_and_pull_request_are_not_projects`
and `test_bitbucket_thread_still_obeys_title_rules` in `tests/test_classify.py`.

Live keyless smoke (the ADR 0057 posture; tests stay offline) grounded the
PR fixtures against the real API with `BITBUCKET_TOKEN` unset:
`bitbucket.org/atlassian/aui/pull-requests/5332` fetched as `bitbucket:atlassian/aui!5332`,
title `"atlassian/aui!5332: DCA11Y-3297: Remove unused icon"`, author
`Michael Kemp`, `tags ('pull request', 'merged')`, comments fetched keyless
(`extraction_method bitbucket-api:pullrequest+comments`) and bylined, the
thread↔repo link; and the deep-linked declined PR
`bitbucket.org/atlassian/aui/pull-requests/5295/diff` deduped to `…!5295`,
`tags ('pull request', 'closed')` — confirming DECLINED→closed on real data.
The native issue tracker returned `410 Gone` on every public repo probed
(`atlassian/aui`, `bitbucketpipelines/official-pipes`), confirming the
deprecation that makes the issue path best-effort.
