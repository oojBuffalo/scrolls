# ADR 0084: GitHub issues and pull requests — a discussion thread on the github source

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

The github adapter (ADR 0007) covers a repository — its metadata and README.
But `_github_id` collapsed *every* `github.com/<owner>/<repo>/…` URL to
`owner/repo`, so a saved **issue** or **pull request** URL
(`…/issues/<n>`, `…/pull/<n>`) silently deduped to the repo and produced the
repo's README scroll. The actual discussion — the bug report, the feature
debate, the PR description and its review conversation — was discarded.

GitHub issues and PRs are among the most-saved developer artifacts: a thread
explaining *why* a change was made, a long bug investigation, an RFC-style PR.
For a knowledge library built to feed coding agents (IDEAS.md §11), a thread is
often *more* valuable context than the repo's README. They are also the
discussion-aggregator family Scrolls already serves elsewhere — Hacker News
(ADR 0031), Lobsters (ADR 0046), Lemmy/PieFed (ADR 0052/0053), Discourse
(ADR 0054) — applied to the place developers actually argue about code.

The REST API serves them keyless, the github posture (ADR 0007): a single
`GET /repos/<o>/<r>/issues/<n>` returns the thread for **both** issues and PRs
(a PR carries an extra `pull_request` object), and `…/issues/<n>/comments`
returns the conversation. GitHub unifies the two: an issue and a PR share one
per-repo number namespace, and the issues endpoint serves both — so for a
knowledge library both are "a titled discussion thread with a body and
comments."

## Decision

Extend the **`github` source** to cover issues and pull requests as a second
content kind, rather than minting a new source. The identity is
`owner/repo#<number>` — GitHub's own cross-reference notation — and the github
adapter dispatches on the `#` in the source id. This is the Hugging Face
one-source-many-kinds shape (ADR 0041, where `model:`/`dataset:`/`space:`
kinds share a source and one adapter routes), not the gist split (ADR 0078,
which earned its own source because `gist.github.com`'s host, API, and id shape
all differ). An issue lives on `github.com`, is served by `api.github.com`, and
extends the repo's identity naturally — so it belongs *on* the github source.

1. **Detection — `owner/repo#<n>` for a thread, `owner/repo` otherwise.**
   `_github_id` claims `/issues/<n>` and the web PR path `/pull/<n>` (singular,
   GitHub's UI route) when the number is all digits, returning
   `owner/repo#<n>`. A deep link into the thread (`/pull/<n>/files`, a dropped
   `#issuecomment-…` fragment) still dedupes to it because the number is the
   fourth path segment. Every other sub-resource (`/blob`, `/tree`,
   `/releases`, the `/issues` and `/pulls` *lists* with no number, the
   `/pull/new` page) collapses to `owner/repo` exactly as before — a saved
   code-browsing link has always pointed at the repo. `#` never appears in a
   repo `source_id` (GitHub forbids it in owner/repo names), so it is a safe
   dispatch sentinel and the existing repo path is byte-unchanged.

2. **One adapter, dispatched on `#`.** `fetch_item` routes an `owner/repo#<n>`
   id to `_fetch_issue` and leaves the repo path untouched. The issues endpoint
   serves issues and PRs alike, so one GET fetches the thread; the conversation
   comments cost a second GET (`?per_page=100`), taken only when the thread has
   any (`issue["comments"]`) and **degrading to body-only on failure** — the
   HN/Discourse two-request economy (ADR 0031/0054). The body is already
   Markdown, so there is no HTML to strip (Lobsters' economy, ADR 0046).

3. **Body + bylined comments → `extracted_text`.** The thread body leads,
   each comment follows bylined `#### Comment by <user>` the way Lobsters and
   Stack Exchange byline a reply (ADR 0046/0033). A body-less thread (a PR
   opened with no description) contributes only its comments; a thread with
   neither degrades to a metadata-only scroll. `summary` is the body's lead
   paragraph, else the engagement GitHub itself shows (`"GitHub discussion: N
   comments."`) — the honest-status fallback, not an invented summary
   (ADR 0031/0046).

4. **Labels → `concepts`; kind + state → `tags`.** Issue/PR **labels**
   (`bug`, `enhancement`, `documentation`) are the curated topical facet, so
   they become `concepts` — the github-topics rule (ADR 0007), consistent with
   how Stack Exchange / Lobsters / Discourse map a thread's tags. The **kind**
   (`issue` / `pull request`) and **lifecycle state** become `tags`, the facet
   slot (Crossref's type+venue, ADR 0037). A PR's `pull_request.merged_at`
   distinguishes a **merged** PR from a closed-unmerged one *without* the extra
   `/pulls/<n>` GET the PR-specific fields would need, so the state is
   `open` / `closed` / `merged`.

5. **The repo edge + body links.** A `github.com/<owner>/<repo>` link makes the
   **issue↔repo edge** `scrolls related`/`graph` resolves to the saved repo
   item, and http(s) URLs scanned from the body (cross-references to other
   issues, PRs, docs) become outbound edges — the social-post body scan
   (ADR 0051), deduped and never self-linking the thread.

6. **No category default — unclassified.** A thread is heterogeneous (a bug, a
   feature request, a design debate, a question), so it gets *no* curated
   source category. The `github → project` rule applies only to repos: in
   `classify.py`, a `github` item whose `source_id` carries a `#` returns
   `None` and falls through to the title rules (so a "How to rebuild the index"
   issue is still a `tutorial`) and otherwise stays honestly unclassified —
   the Hacker News / Lobsters / Discourse posture (ADR 0031/0046/0054), the
   same honesty the gist adapter took (ADR 0078). This is why github is now a
   special-cased curated source (like crossref/zenodo/huggingface) rather than
   a flat entry in `_CURATED_SOURCE_CATEGORIES`.

**Keyless, github's token posture.** `_fetch_issue` reuses `_api_headers`
(ADR 0007): keyless by default, `GITHUB_TOKEN`/`GH_TOKEN` → `Authorization:
Bearer` to lift the rate limit. `FetchError` is reserved for a missing/malformed
thread id and the issue request failing; a comments failure only degrades.

## Consequences

- A saved issue/PR URL now becomes a real discussion scroll — title, author,
  dates, searchable body and conversation, labels as concepts, the issue↔repo
  edge — instead of silently producing the repo's README. This is a deliberate
  **behavior change**: `tests/test_detect.py` previously pinned
  `…/issues/42 → owner/repo`; it now pins `owner/repo#42`. An issue URL added
  before this change resolved to the repo id, so the two never collide; the new
  thread item is simply additional.
- The github source now spans two categories — a repo is a `project`, a thread
  is unclassified — the same per-kind split huggingface (`tool`/`dataset`) and
  zenodo carry. `list_sources`/`facets` still report one `github` source; the
  `#` in the id is the only tell, mirroring huggingface's `model:`/`dataset:`
  prefixes.
- The title leads with `owner/repo#<n>:` (the RFC number-leads-title rule,
  ADR 0066) because GitHub issue titles are often terse and `owner/repo#<n>` is
  the work's canonical reference — a search hit or library listing stays
  self-identifying.
- **Deferred:** GitHub **Discussions** (`/discussions/<n>`) — a separate
  feature whose read API is GraphQL-only, so it would not slot into the keyless
  REST path; PR **review** comments on the diff (the `/pulls/<n>/comments`
  endpoint) — the conversation comments on the issues endpoint are what a reader
  wants, the diff-line review thread is a richer second slice; deep comment
  **pagination** beyond the first 100 (one GET covers essentially every real
  thread, the Discourse first-page posture, ADR 0054); inline issue **images**
  as media; and a native `x`-style fetch-time identity rewrite (not needed —
  the issue number is stable and in the URL).

## Proof

`src/scrolls/sources/github.py` `_fetch_issue` with the transport-faked tests
in `tests/test_github.py` (fixtures trimmed from the real API): the thread-field
mapping (`test_fetch_issue_maps_thread_fields`), the body+bylined-comments
`extracted_text` (`test_fetch_issue_body_and_comments_become_extracted_text`),
the repo edge plus body-URL links with no self-link
(`test_fetch_issue_links_carry_the_repo_edge_and_body_urls`), the merge-aware PR
tagging (`test_fetch_pull_request_is_tagged_and_merge_aware`), the
comments-skipped-when-none (`test_fetch_issue_skips_comment_request_when_there_are_none`)
and the requested URLs (`test_fetch_issue_requests_the_expected_api_urls`), the
comments-failure degrade (`test_fetch_issue_degrades_when_comments_fail`), the
empty-body engagement summary (`test_fetch_issue_with_empty_body_summarizes_engagement`),
the `raw_text` round-trip (`test_fetch_issue_keeps_raw_records_for_rebuilds`),
and the request-failed / malformed-id `FetchError`s — all offline. Detection is
pinned in `tests/test_detect.py` (issue and PR URLs → `owner/repo#<n>`, deep
links deduping to the thread, the `/issues`/`/pulls` lists and `/blob`/`/tree`
sub-resources collapsing to the repo, a non-numeric tail falling through). The
no-category-default and title-rule-still-fires decisions are pinned by
`test_github_issue_and_pr_are_not_projects` and
`test_github_issue_still_obeys_title_rules` in `tests/test_classify.py`.

Live keyless smoke (the ADR 0007 posture; tests stay offline) grounded the
fixtures against the real API with `GITHUB_TOKEN` unset:
`github.com/psf/requests/pull/1` (an issue-numbered thread) fetched as
`github:psf/requests#1`, title `"psf/requests#1: Cookie support?"`, author
`keul`, `tags ['issue', 'closed']`, the issue↔repo link, body+comments
extracted; `github.com/pallets/flask/pull/5004` carried label `cli` →
`concepts ['cli']`; and a genuinely merged PR `github.com/pallets/click/pull/3591`
fetched as `tags ['pull request', 'merged']` — confirming the `pull_request.merged_at`
read on real data. (The issues endpoint serves public threads keyless —
verified `200` unauthenticated.)
