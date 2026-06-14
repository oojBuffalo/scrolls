# ADR 0085: GitLab issues and merge requests — the github thread template on a separate-iid host

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

ADR 0084 made GitHub issues and pull requests a second content kind on the
`github` source: a `/issues/<n>` or `/pull/<n>` URL detects as a discussion
thread `owner/repo#<n>` and one adapter dispatches on the `#`. The architecture
flagged the same gap on every other code host — a GitLab `/-/issues/<n>` or
`/-/merge_requests/<n>` URL still collapsed to the project (ADR 0055), so the
discussion was discarded and the README scroll produced instead. GitLab is the
second major host, so it is the first place to apply the template.

The slice is "the same shape on a different API" — but GitLab forces one genuine
divergence from the github template that makes it worth its own record:

- **GitHub unifies issue and PR numbering.** A repo has one number namespace;
  `#5` is unambiguously *the* item #5 (issue or PR), and one
  `GET /repos/<o>/<r>/issues/<n>` endpoint serves both. So `owner/repo#<n>` is a
  complete identity and the `#` is a pure dispatch sentinel.
- **GitLab keeps *separate* iid sequences for issues and merge requests.** A
  project can have both issue !5 and MR !5; they are different objects on
  different endpoints (`/projects/<id>/issues/<iid>` vs
  `/projects/<id>/merge_requests/<iid>`). A bare `group/project#5` would be
  ambiguous.

GitLab already solved this in its own UI: its cross-reference notation writes an
issue as `group/project#<iid>` and a merge request as `group/project!<iid>`. The
`#`/`!` marker is exactly the disambiguator the identity needs — and it doubles
as the endpoint selector.

The GitLab REST API serves both keyless, the github posture (ADR 0055):
`GET /projects/<url-encoded path>/issues/<iid>` (or `/merge_requests/<iid>`)
returns the thread, and `…/notes` returns the conversation.

## Decision

Extend the **`gitlab` source** to cover issues and merge requests as a second
content kind, mirroring ADR 0084. Identity is GitLab's own cross-reference
notation and the adapter dispatches on the marker.

1. **Detection — `group/project#<iid>` / `group/project!<iid>` for a thread.**
   `_gitlab_id` already split the project path off the reserved `/-/`
   sub-resource separator; it now inspects the sub-resource: `issues/<digits>`
   → `#<iid>`, `merge_requests/<digits>` → `!<iid>`. A deep link
   (`/-/issues/<n>/designs`, `/-/merge_requests/<n>/diffs`, a dropped
   `#note_…` fragment) dedupes to the thread because the number is the segment
   right after the kind; the issue/MR *list* (no number) and the `/-/merge_requests/new`
   page collapse to the project, exactly as `/-/blob`/`/-/tree` always did. The
   project path keeps its lowercase fold (ADR 0055); `#`/`!` never appear in a
   GitLab slug (ASCII `[a-z0-9._-]`), so they are safe markers and the existing
   project path is byte-unchanged.

2. **One adapter, dispatched on the marker — which also picks the endpoint.**
   `fetch_item` routes a `#`/`!`-bearing id to `_fetch_thread` and leaves the
   project path untouched. Unlike github's single issues endpoint, the marker
   chooses the API route (`#` → `/issues/<iid>`, `!` → `/merge_requests/<iid>`)
   because GitLab's two object types live on two endpoints. The project path is
   URL-encoded whole like a repo fetch (nested groups). The thread costs one
   GET; its **notes** a second, taken only when it has any (`user_notes_count`)
   and **degrading to body-only on failure** — the github/HN two-request economy
   (ADR 0084/0031). The description is already Markdown, so there is no HTML to
   strip (Lobsters' economy, ADR 0046).

3. **Body + bylined comments → `extracted_text`, with system notes dropped.**
   The description leads, each note follows bylined `#### Comment by <username>`
   (ADR 0084/0046). GitLab's `/notes` endpoint returns both human comments and
   **system notes** — its automated activity events ("changed milestone to v2",
   "assigned to @alice"). System notes carry `system: true` and are *not*
   discussion, so they are dropped (the Discourse mod-action skip, ADR 0054);
   only human comments are content. `summary` is the description's lead
   paragraph, else the honest engagement GitLab shows
   (`"GitLab discussion: N comments."` from `user_notes_count`, which already
   excludes system notes) — the ADR 0084/0031 fallback.

4. **Labels → `concepts`; kind + state → `tags`.** GitLab labels become
   `concepts`, the curated topical facet (the github-topics rule, ADR 0007); the
   API returns bare strings by default and label objects under
   `?with_labels_details=true`, so both shapes are read like github's `_labels`.
   The **kind** (`issue` / `merge request`) and **lifecycle state** become
   `tags`. The state vocabulary is **normalized to github's** so a `--tag open`
   or `--tag merged` query spans both hosts: GitLab's `opened` becomes `open`,
   and a merged MR is read directly from `state == "merged"` — GitLab reports it,
   so no extra request is needed (github had to derive `merged` from
   `pull_request.merged_at`).

5. **The project edge + body links.** A `gitlab.com/<project>` link makes the
   **thread↔project edge** `scrolls related`/`graph` resolves to the saved
   project item (the github issue↔repo edge, ADR 0084), and http(s) URLs scanned
   from the description become outbound edges (the social-post body scan,
   ADR 0051), deduped and never self-linking the thread.

6. **No category default — unclassified.** A thread is heterogeneous, so it gets
   *no* curated source category. The `gitlab → project` rule now applies only to
   projects: in `classify.py`, a `gitlab` item whose `source_id` carries a `#`
   *or* `!` returns `None` and falls through to the title rules (a "How to" issue
   is still a `tutorial`) else stays unclassified — the github carve-out
   (ADR 0084), now with the two-marker check GitLab's separate iid spaces force.
   GitLab joins github as a special-cased curated source rather than a flat
   `_CURATED_SOURCE_CATEGORIES` entry.

**Keyless, GitLab's token posture — with one gate the live check surfaced.**
`_fetch_thread` reuses `_api_headers` (ADR 0055): keyless by default,
`GITLAB_TOKEN` → `PRIVATE-TOKEN`. A keyless live check found gitlab.com serves
the issue/MR **metadata** anonymously (200) but **gates the `/notes` endpoint
behind auth** — an anonymous `/notes` GET returns `401 Unauthorized` across
projects (an anti-abuse measure). So unlike github, where the token only lifts a
rate limit, here the token is what unlocks the *conversation*: the common keyless
case fetches the body and **degrades to body-only** on the notes 401 — exactly
the failure path the two-request economy already takes (a 401 is an `HTTPError`,
an `OSError`, caught like any other notes failure). `FetchError` is reserved for
a missing/malformed thread id, the *thread* request failing, and an iid-less
payload; a notes failure (the keyless norm) only degrades.

## Consequences

- A saved GitLab issue/MR URL now becomes a real discussion scroll — title,
  author, dates, searchable body and conversation, labels as concepts, the
  thread↔project edge — instead of silently producing the project's README. This
  is a deliberate **behavior change**: `tests/test_detect.py` previously pinned
  `…/-/issues/1 → gitlab-org/gitlab`; it now pins `gitlab-org/gitlab#1`. A
  GitLab issue URL added before this change resolved to the project id, so the
  two never collide; the new thread item is simply additional.
- The `#`/`!` marker is the template's first adaptation to a host whose issue
  and MR id spaces are disjoint. The pattern for the *remaining* hosts is now
  set: a host that unifies numbering (github) uses one marker, a host that
  splits it (gitlab) uses two. Gitea numbers issues and PRs together like github
  (one `/issues/<n>` endpoint serves both), and Bitbucket keeps them separate
  like gitlab (`/issues/<n>` vs `/pull-requests/<n>`) — so each future slice
  picks the github or the gitlab marker rule accordingly.
- The gitlab source now spans two categories — a project is a `project`, a
  thread is unclassified — the same per-kind split github carries (ADR 0084).
  `list_sources`/`facets` still report one `gitlab` source; the `#`/`!` in the
  id is the only tell.
- **Deferred:** GitLab's emerging `/-/work_items/<iid>` route (the live check
  found an issue's own `web_url` now uses it) — *not* claimed in detection
  because the work-items URL is the unified route for issues, **epics, tasks,
  and objectives**, so a bare `/-/work_items/<n>` can't be assumed an issue the
  `/issues/<iid>` endpoint serves; the canonical pasted form today is still
  `/-/issues/<n>`, and claiming work-items would need a type probe. MR
  **diff-line discussion** (notes positioned on the diff, a richer second slice
  like github's review comments); the MR's source/target **branch and pipeline**
  state as extra tags; deep note **pagination** beyond the first 100 (one page
  covers essentially every real thread, the github/Discourse posture);
  **self-hosted GitLab** issue/MR threads (deferred with self-hosted GitLab repos
  themselves, ADR 0055 — a host allowlist or source hint would reach both at
  once); and the Gitea and Bitbucket threads this ADR sets the template for.

## Proof

`src/scrolls/sources/gitlab.py` `_fetch_thread` with the transport-faked tests
in `tests/test_gitlab.py` (fixtures trimmed from the real API): the thread-field
mapping with `opened` → `open` normalization
(`test_fetch_issue_maps_thread_fields`), the body+bylined-notes `extracted_text`
with the **system note dropped** (`test_fetch_issue_body_and_notes_become_extracted_text`),
the project edge plus body-URL links with no self-link
(`test_fetch_thread_links_carry_the_project_edge_and_body_urls`), the
merge-aware MR tagging read from `state`
(`test_fetch_merge_request_is_tagged_and_merge_aware`), the **marker → endpoint**
dispatch (`test_fetch_thread_dispatches_to_the_right_endpoint`), the requested
URLs and nested-group encoding (`test_fetch_issue_requests_the_expected_api_urls`,
`test_fetch_thread_url_encodes_nested_group_path`), the notes-failure degrade
(`test_fetch_thread_degrades_when_notes_fail`), the notes-skipped-when-none
(`test_fetch_thread_skips_notes_when_none`), the empty-description engagement
summary (`test_fetch_thread_with_empty_description_summarizes_engagement`), the
titleless bare-reference (`test_fetch_thread_without_title_degrades_to_the_bare_reference`),
the label-object fallback (`test_fetch_thread_with_label_objects_reads_names`),
the `raw_text` round-trip keeping system notes
(`test_fetch_thread_keeps_raw_records_for_rebuilds`), and the malformed-id /
not-found `FetchError`s — all offline. Detection is pinned in
`tests/test_detect.py` (issue → `#<iid>`, MR → `!<iid>`, nested groups, deep
links deduping to the thread, the lists and `/new` page and `/-/blob` collapsing
to the project, the lowercase fold). The no-category-default and
title-rule-still-fires decisions are pinned by
`test_gitlab_issue_and_merge_request_are_not_projects` and
`test_gitlab_thread_still_obeys_title_rules` in `tests/test_classify.py`.

A keyless live check (tests stay offline) grounded the fixtures against the real
gitlab.com API with `GITLAB_TOKEN` unset:
`GET /api/v4/projects/gitlab-org%2Fgitlab/issues/1` returned `iid 1`,
`state "closed"`, `labels ['Enterprise Edition', 'backend']` (bare strings),
`user_notes_count 35`, `author.username jacobvosmaer`; the matching merge request
`/merge_requests/1` returned `state "merged"` **directly** (confirming the
no-`merged_at`-derivation read on real data). The check also surfaced the notes
gate: `…/issues/1/notes` and `…/merge_requests/1/notes` both returned
`401 Unauthorized` anonymously — so the keyless path degrades to body-only, the
behavior pinned offline by `test_fetch_thread_degrades_on_anonymous_notes_gate`
(a 401 `HTTPError`) alongside the generic `test_fetch_thread_degrades_when_notes_fail`.
