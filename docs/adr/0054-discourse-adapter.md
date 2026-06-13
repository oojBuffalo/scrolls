# 0054: Discourse via the keyless `.json` view — a host-less forum source, and why Mbin is not the next aggregator

Date: 2026-06-13

Status: accepted

## Context

ADR 0052 (Lemmy) and ADR 0053 (PieFed) both named **Mbin** as the next link
aggregator:

> a third Lemmy-shaped aggregator (Mbin's `/m/<magazine>/t/<id>` thread URLs are a
> *different* shape, so it would detect separately; …).

Confirming Mbin surfaced a fact those ADRs did not have, which disqualifies it
under the project's keyless principle:

- **Mbin's read API requires OAuth2.** Its `config/packages/security.yaml` grants
  anonymous `PUBLIC_ACCESS` to only a handful of endpoints (`/api/doc`,
  `/api/client`, `/api/info`, `/api/instance`, `/api/federated`, …) — *not*
  `/api/entry/{id}` or `/api/entry/{id}/comments`. A read needs a registered
  OAuth2 client and a token. Two live instances confirmed it: `fedia.io/api/entry/1`
  returns **401**, `kbin.earth/api/entry/1` returns **403**.

Every Scrolls adapter to date is keyless — no login, cookie, or token (the
adapter table in `docs/architecture.md` is literally headed "all keyless"). An
Mbin adapter would be the first to need a client-registration + token-grant
dance, breaking that invariant for one more aggregator. So Mbin is **deferred,
not the next adapter** — its ActivityPub `apId` (an unauthenticated object fetch)
is the only keyless path, and that is a different, heavier design (HTTP
signatures, AP object shape) than "its own clean `/api`."

That left the next-source question open. The strongest *keyless* candidate in the
same discussion family is **Discourse** — the open-source forum software behind a
large share of developer and project communities (`discuss.python.org`,
`meta.discourse.org`, `users.rust-lang.org`, `discourse.llvm.org`,
`forum.obsidian.md`, and thousands more). Discourse is the **centralized-forum
sibling** of the federated aggregators (Lemmy/PieFed) and the discussion
aggregators (Hacker News, ADR 0031; Lobsters, ADR 0046), and it is genuinely
keyless: appending `.json` to a topic URL returns the topic and its posts with no
auth (confirmed live: `discuss.python.org/t/welcome-to-discourse/8.json` → **200**,
no token).

Three facts shape the design:

1. **There is no shared host** — Discourse runs on thousands of independent
   instances, the same problem the Fediverse adapters solved (ADR 0049–0052). So
   a topic is detected by its `/t/<slug>/<topic_id>` URL *shape* on whatever host
   the saved URL names, the host folded into the id (`discourse:<host>/<topic_id>`,
   instance-local). This is the **first non-Fediverse host-less source** — the
   shape-detection technique generalizes beyond ActivityPub software to any
   self-hostable platform with a recognizable URL.

2. **The topic and its replies come in one request** — `GET /t/<id>.json` returns
   the topic *and* the first page of `post_stream.posts` (the opening post plus
   leading replies). This is Lobsters' one-request economy (ADR 0046), not the
   two-request shape of Lemmy/Mastodon/Stack Exchange. A very long thread is
   bounded to the first page; the full ordering (`post_stream.stream`, every post
   id) survives in `raw_text` for a future paged render (Bluesky's depth cap,
   ADR 0048).

3. **A Discourse topic is a forum thread, so it has a real title** — like a Lemmy
   aggregator entry (ADR 0052), not a synthesized social-post title. The opening
   post is the body; later posts are bylined replies. The post `cooked` field is
   HTML, so it is reduced to plain text by a stdlib parser (Mastodon's rule,
   ADR 0049 — no `trafilatura` dependency).

## Decision

`scrolls add`/`fetch` of a Discourse topic runs a new keyless adapter
(`src/scrolls/sources/discourse.py`), the **twenty-third**.

- **Detection is shape-only on any unclaimed host** (`detect.py`'s `_discourse_id`,
  after the Fediverse branches — its `/t/` literal never collides with theirs,
  `tests/test_detect.py`). `/t/<slug>/<topic_id>` → `discourse:<host>/<topic_id>`,
  the topic id the third path segment (an autoincrement integer), the host
  lowercased, the slug dropped from identity (Discourse treats it as display-only
  and redirects a wrong slug; the adapter fetches the slug-free `/t/<id>.json`).
  A trailing `/<post_number>` jump target dedupes to the topic (a row in the
  `test_detect_source` parametrized table). The weak `t`
  literal makes the **id carry the weight** (the Pleroma/Misskey/Lemmy rule,
  ADR 0050–0052): an all-digits third segment with a `slug` between, so a
  two-segment `/t/<tag>` tag page or a `/t/<slug>/<non-numeric>` stays `web`. The
  residual risk — a non-Discourse `/t/<slug>/<digits>` URL the user wanted as
  `web` — degrades to a benign failed fetch (the `.json` 404s or lacks
  `post_stream`), never a wrong scroll: the conservative, reversible tradeoff a
  host-less shape forces (ADR 0049).

- **The adapter fetches one `.json` view and validates it is a Discourse topic.**
  A response with no `post_stream.posts` raises `FetchError` — both the
  topic-not-found case and the benign-misdetect case (a non-Discourse
  `/t/x/123.json`), so a wrong detection can never produce a wrong scroll
  (`test_non_discourse_json_raises_the_misdetect_path`). Each behavior is pinned
  by a test shaped from the live topic payload (`tests/test_discourse.py`):
  - **Real `title`, author from `details.created_by`** (falling back to the
    opening post's byline), `published_at` from the topic `created_at`,
    `canonical_url` rebuilt as `/t/<slug>/<id>` from the response slug
    (`test_fetch_topic_in_one_request`, `test_canonical_url_carries_the_slug_from_the_response`).
    One GET, no second request (`test_hits_the_slug_free_json_view`).
  - **The opening post (`post_number` 1) is the body**, leading the
    `extracted_text`; the later posts are bylined `### Replies` with author and
    like count (from `actions_summary`'s like action), the `cooked` HTML reduced
    to text (`test_opening_post_is_the_body_and_leads_the_extracted_text`,
    `test_replies_are_bylined_with_like_counts`, `test_html_cooked_is_reduced_to_plain_text`).
    Moderator-action, small-action, whisper (`post_type` 2/3/4), and
    deleted/hidden posts are skipped the way Lemmy skips deleted comments
    (`test_action_deleted_and_whisper_posts_are_skipped`).
  - **Tags → `concepts`** (github-topics pattern, ADR 0007 —
    `test_tags_become_concepts`); the topic's outbound `details.links` →
    `links`, with `internal` (same-instance navigation, excluded like Mastodon's
    mentions) and `reflection` (an *incoming* link from another topic) filtered
    out (`test_outbound_link_becomes_a_link_internal_and_reflection_excluded`),
    so a thread pointing at an arXiv paper or github repo wires to it through
    `scrolls related`/`graph` (the cross-source edges, ADR 0044). The topic's
    representative `image_url` → a `thumbnail` media ref, resolved against the
    host when site-relative (`test_image_url_becomes_a_thumbnail_media_ref`,
    `test_relative_image_url_is_resolved_against_the_host`).
  - **`summary` = the opening post's lead paragraph, else the engagement status**
    (`"Discourse topic: N replies, M likes."` — `posts_count` includes the
    opening post, so replies = `posts_count − 1`), the honestly-empty posture
    when neither exists (`test_summary_is_the_opening_post_lead_paragraph`,
    `test_empty_op_summary_is_engagement_status`). The `extraction_method`
    records whether replies rendered (`discourse-api:topic+replies` vs
    `…:topic`, `test_op_only_topic_is_topic_not_replies`).
  - **No category default** — a heterogeneous forum thread is unclassified like
    Hacker News, Lobsters, Lemmy, and the social adapters until a title rule or
    the LLM engine names it; `classify.py` needs no change
    (`test_no_category_default`). The whole topic JSON, including the skipped
    posts and the full `stream` of post ids, is kept in `raw_text`
    (`test_raw_text_keeps_the_whole_topic`).

Per the no-network rule (ADR 0001), the GET transport is injected and the tests
run against a payload shaped from the live Discourse topic view; the adapter is
registered in `FETCH_ADAPTERS` (`test_registered_in_fetch_adapters`).

## Consequences

- A saved Discourse topic from *any* instance becomes a clean scroll — real
  title, author, date, tags-as-concepts, the opening post body, the bylined reply
  thread, outbound links, and a thumbnail — the **twenty-third keyless fetch
  adapter**, and the first whose host-less shape detection reaches **non-Fediverse**
  software. The technique the Fediverse adapters built (recognize a platform by
  URL shape when it has no host set, degrade a misdetect to a benign failed fetch)
  is now established as general, not ActivityPub-specific.
- **The discussion-source family is now four-wide**: the centralized aggregators
  (Hacker News, Lobsters), the federated aggregators (Lemmy, PieFed), the social
  networks (Bluesky, Mastodon, Misskey), and now the **forums** (Discourse) — all
  sharing the "real-or-synthesized title, bylined thread, tags/community →
  concepts, outbound links → edges, no category default" shape, differing only in
  the API and field names.
- **Mbin is recorded as deferred, not pending.** The README's and ADR 0052/0053's
  "Mbin next" note is corrected here: Mbin's read API is OAuth-gated, so it cannot
  join as a keyless adapter without a token dance. A future Mbin slice would have
  to either accept an OAuth client-credentials path (a new, non-keyless adapter
  posture worth its own ADR) or fetch the ActivityPub `apId` object directly.
- **Discourse-specific gaps left honest / deferred this slice:**
  - **Long threads are first-page-only.** A topic with more posts than the first
    `post_stream.posts` page renders only that page; the full `stream` of post ids
    is in `raw_text`, so a future paged-fetch enrichment (`/t/<id>/posts.json?post_ids[]=…`)
    can extend it — the same bounded-then-deepen posture Bluesky/Lemmy take.
  - **Replies render flat, not nested.** Discourse posts carry
    `reply_to_post_number`, so a threaded (indented) render is possible later; the
    flat pre-ordered byline list is shared with Lemmy/PieFed (ADR 0052/0053).
  - **Internal-link edges deferred.** A `/t/<id>` link to another topic on the
    same instance is excluded as navigation; surfacing same-instance topic↔topic
    edges (Lemmy's `cross_posts` analog) is a future tightening.
  - **The two-segment `/t/<id>` slug-free URL is not detected** (only the
    canonical `/t/<slug>/<id>`), to keep the weak `t` literal's false-positive
    surface small; a fetch-time-validated relaxation could add it.
- **A `improve-codebase-architecture` target persists.** Discourse's
  `_clean`/`_plural`/`_html_to_text` mirror Mastodon's, and its
  byline/skip/no-default posture mirrors Lemmy's — the social/aggregator/forum
  adapters now share a large body of near-identical helpers by deliberate
  duplication (ADR 0053 named this). A shared `_thread_family` module (HTML→text,
  byline, plural, link/concept helpers) is the clearest consolidation the
  duplication has yet offered.
