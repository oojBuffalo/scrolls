# 0053: PieFed via its own keyless API — a fetch-time fallback behind Lemmy, not a new detected source

Date: 2026-06-13

Status: accepted

## Context

ADR 0052 added Lemmy, the federated link aggregator, and named PieFed as the next
candidate — but framed it as an open question:

> **PieFed** — another Lemmy-shaped link aggregator — is the analog of GoToSocial
> to Mastodon, *if* its API is Lemmy-compatible enough; but PieFed serves an
> `/api/alpha` namespace rather than `/api/v3`, so it is more likely a fourth
> split (its own source/adapter) than a `detect.py` route on this one — the same
> judgment ADR 0051 made for Misskey vs the mastodon forks, to be confirmed when
> PieFed is added.

Confirming it surfaced a fact ADR 0052 didn't have, which changes the answer.
PieFed is a Reddit-shaped, ActivityPub link aggregator — the same niche as Lemmy
(and the centralized Hacker News, ADR 0031, and Lobsters, ADR 0046). Two facts
about it pull against each other:

1. **Its post URL is byte-identical to Lemmy's.** A PieFed post permalink is
   `https://<instance>/post/<id>` with an autoincrement integer id — exactly the
   shape `detect.py`'s `_lemmy_id` already claims (observed live:
   `piefed.social/post/1600132`, `piefed.social/post/956553`). There is nothing
   in the URL to tell PieFed from Lemmy. So PieFed **cannot be its own detected
   source** — the ADR 0051 (Misskey) precedent does not apply, because that one
   relied on a *distinct* URL shape (`/notes/<id>`) to route to a separate source.

2. **Its API is its own.** PieFed serves `/api/alpha`, not Lemmy's `/api/v3`. It
   is deliberately Lemmy-*shaped* (a `post_view` of `post`/`creator`/`community`/
   `counts`; a flat `comments` list with a materialized-path tree), but the field
   names diverge enough that it cannot ride Lemmy's *adapter* the way GoToSocial
   rides Mastodon's (ADR 0050, which required byte-identical JSON):
   - `post.title`, not Lemmy's `post.name`;
   - `creator.user_name`, not Lemmy's `creator.name`;
   - `comment.body`, not Lemmy's `comment.content`;
   - a `post_type` enum (`Image`/`Link`/`Discussion`/`Video`/`Poll`/`Event`)
     instead of Lemmy's `url_content_type` for telling an image post apart;
   - `cross_posts` nested *on the post* as `{post_id, community_name}` (no
     `ap_id`), where Lemmy puts full post views with `ap_id` at the response top
     level.

So PieFed is a hybrid of the two precedents the project already has for a
compatible sibling: it needs its **own adapter** (like Misskey vs the mastodon
forks — different API, different normalization) but it shares Lemmy's **detected
source and identity** (like GoToSocial vs Mastodon — indistinguishable URL). The
exact mechanism for "same detected source, different fetch backend resolved at
fetch time" already exists in the codebase: the `doi.py` dispatcher for
Crossref-vs-DataCite (ADR 0045).

## Decision

`scrolls add`/`fetch` of a PieFed post runs a new keyless adapter
(`src/scrolls/sources/piefed.py`), the **twenty-second**, reached through a new
fetch-time dispatcher — *not* through a new `detect.py` branch.

- **Detection is unchanged.** A PieFed `/post/<digits>` URL already detects as the
  `lemmy` source with `source_id = <host>/<post_id>` (the `_lemmy_id` branch,
  ADR 0052). No detection code changes; a pinned test records the shared shape
  (`tests/test_detect.py`: `piefed.social/post/1600132` → `lemmy`). This keeps the
  detection surface — already carrying three host-less Fediverse heuristics —
  from growing a fourth that it could not make correct anyway.

- **A `threadiverse.py` dispatcher resolves the backend at fetch time**, exactly
  as `doi.py` resolves the registration agency (ADR 0045). `FETCH_ADAPTERS["lemmy"]`
  now points at `threadiverse.fetch_item`, which tries `lemmy.fetch_item` first
  and falls back to `piefed.fetch_item` on its `FetchError`
  (`tests/test_threadiverse.py`):
  - **Lemmy first** because it is by far the more deployed of the two, so the
    common case pays no extra request (`test_lemmy_hit_never_touches_piefed`).
  - **PieFed on fallback** because a PieFed instance 404s the Lemmy `/api/v3` call
    (it implements only `/api/alpha`), which `lemmy.py` already turns into a
    `FetchError`; so a PieFed post spends one wasted `/api/v3` GET before its real
    `/api/alpha` fetch — DataCite's one-extra-request tax (ADR 0045)
    (`test_lemmy_miss_falls_back_to_piefed`). A `/post/<digits>` URL served by
    neither (a transient outage, or a misdetected non-aggregator URL) raises a
    `FetchError` naming both failures
    (`test_neither_backend_serves_the_post_raises_naming_both`).
  - The name follows `doi.py`'s rule — name the dispatcher after the **shared
    scheme**, not either implementation. "Threadiverse" is the established
    community term for this Reddit-like corner of the Fediverse (Lemmy, PieFed,
    Mbin), so it is the natural parallel to `doi`.

- **Identity stays `lemmy:<host>/<post_id>`, `provenance.adapter="piefed"` tells
  the truth.** The id is minted at `add` time, before the backend (Lemmy or
  PieFed) is knowable, so — exactly like a DataCite-served DOI that keeps
  `source="crossref"` with `provenance.adapter="datacite"` (ADR 0045) — a
  PieFed-served post keeps `source="lemmy"` and records the serving adapter in
  provenance (`test_fetch_post_then_comments`,
  `test_hits_the_api_alpha_namespace`). The `lemmy` source name is now a mild
  misnomer for the family ("Lemmy-API-and-friends"), the same accepted imprecision
  `crossref` carries for DataCite DOIs.

- **The adapter mirrors Lemmy's behavior, mapping PieFed's field names.** Once the
  field-name mapping is in place, everything downstream is the Lemmy adapter's
  logic (ADR 0052), each behavior pinned by a test shaped from the live
  `/api/alpha` payloads (`tests/test_piefed.py`):
  - **Title from `title`, author from `user_name`** — the two mappings that most
    distinguish the adapter (`test_title_comes_from_the_title_field`,
    `test_author_comes_from_user_name_field`); `published_at` from `post.published`,
    `canonical_url` from the federated `ap_id` so a remote post points at its
    origin instance (`test_remote_post_canonical_is_the_origin_ap_id`).
  - **Comment text from `body`**, the flat list sorted into thread pre-order by
    integer `path` and bylined with author and score, deleted/removed skipped
    (`test_comments_are_bylined_and_thread_ordered`,
    `test_deleted_and_removed_comments_are_skipped`). The thread is a second GET,
    skipped when `counts.comments == 0` and degrading to a post-only scroll on
    failure (`test_no_comments_skips_the_comment_request`,
    `test_comment_failure_degrades_to_post_only`); `extraction_method` records
    which path ran (`piefed-api:post+comments` vs `…:post`). `sort` is omitted
    from the comment request — PieFed's comment-sort vocabulary differs from
    Lemmy's and a rejected value would needlessly degrade the scroll, while the
    `path` re-sort makes server order irrelevant.
  - **Image post by `post_type`, not `url_content_type`.** A `post_type == "Image"`
    post's `url` is `photo` media; any other type's `url` (a `Link`, `Video`, …)
    is an external article/resource recorded as a `link` — so a PieFed video post
    pointing at a YouTube URL becomes a cross-source edge for free. The read falls
    back to the URL extension when the enum is absent
    (`test_image_post_url_becomes_photo_media`,
    `test_image_detected_by_post_type_even_without_extension`); an article post's
    pict-rs `thumbnail_url` is a preview `thumbnail`
    (`test_link_post_thumbnail_becomes_thumbnail_media`).
  - **Body URLs and cross-posts are the edges** (ADR 0044). Outbound URLs in the
    Markdown body are scanned (`test_body_urls_become_links`); a link post's `url`
    is the article (`test_link_post_url_becomes_a_link`); a text post contributes
    its body (`test_text_post_has_no_link_and_keeps_its_body`). PieFed's nested
    `cross_posts` carry only `post_id` (no `ap_id`), so each becomes a
    same-instance `https://<host>/post/<post_id>` link that resolves back through
    detection to the saved cross-post — a post↔post edge
    (`test_cross_post_becomes_a_same_instance_link`).
  - **Community is the one `concept`** (the subreddit-like topical home,
    github-topics pattern, ADR 0007) (`test_community_becomes_a_concept`); the
    `summary` leads with the body else the engagement status `"PieFed discussion:
    N points, M comments."` (`test_link_only_post_summary_is_engagement_status`).
  - **No category default** — a heterogeneous aggregator entry, unclassified like
    Hacker News, Lobsters, Lemmy, and the social adapters; `classify.py` needs no
    change. The whole `{post, comments}` is kept in `raw_text`
    (`test_raw_text_keeps_post_and_comments`).

Per the no-network rule (ADR 0001), the GET transport is injected and tests run
against payloads shaped from the live PieFed `/api/alpha` API; the
`lemmy.fetch_item` registration test becomes
`test_registered_via_the_threadiverse_dispatcher`.

## Consequences

- A saved PieFed post from *any* instance becomes a clean scroll — real title,
  author, date, community-as-concept, the linked article or the post body, the
  comment thread in pre-order, cross-post and body links, and a thumbnail — the
  twenty-second keyless fetch adapter, with **no change to the detection surface**.
- **The `lemmy` source now spans two implementations resolved at fetch time**, the
  second detected source (after `crossref`/DOI) to do so. This is the right model
  whenever two platforms share a URL shape but not a client API — a combination
  neither the GoToSocial precedent (same API) nor the Misskey precedent (different
  URL shape) covers alone. The dispatcher generalizes: a third Lemmy-shaped
  aggregator (Mbin's `/m/<magazine>/t/<id>` thread URLs are a *different* shape, so
  it would detect separately; but a future `/post/<id>` clone would slot in as a
  third fallback).
- **PieFed-specific gaps left honest.** PieFed's `cross_posts` lack an `ap_id`, so
  a cross-post link assumes the same instance — correct for a local cross-post,
  approximate for a federated one (it degrades to an unresolvable link, never a
  wrong scroll). PieFed's `post_type` includes `Poll` and `Event`, whose
  structured payloads (`poll`, `event` objects) are kept in `raw_text` but not yet
  rendered — the same "richer payload deferred to `raw_text`" posture the social
  adapters take.
- **The doc-lineage's prediction is corrected, not just extended.** ADR 0052
  guessed PieFed would be a fourth *detected* split; the live URL shape shows it is
  a fetch-time *fallback* instead. The forward note there ("its own source/adapter
  … to be confirmed") is now resolved by this record.
- **Deferred this slice:** the `Poll`/`Event` structured render; a threaded
  (indented) comment render (the flat pre-ordered byline list is shared with
  Lemmy); home-instance-canonical identity so a post saved through two instances
  dedupes (still the cross-Fediverse gap of ADR 0048–0052, now spanning a fifth
  adapter). The six social/aggregator adapters (bluesky, mastodon, misskey, lemmy,
  piefed, plus the HN/Lobsters pair's helpers) now share near-identical
  `_plural`/`_clean`/`_dedupe`/`_text`/`_content_links`/`_path_key` helpers by
  deliberate duplication; piefed and lemmy in particular are a body-for-body
  parallel differing only in field names, so a shared `_lemmy_family` module (or a
  field-map-parameterized single adapter) is now the clearest
  `improve-codebase-architecture` target the duplication has yet offered.
