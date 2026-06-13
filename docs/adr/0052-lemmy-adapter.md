# 0052: Lemmy via its own keyless API — the federated link aggregator, a fourth Fediverse API

Date: 2026-06-13

Status: accepted

## Context

The Fediverse is now covered by two adapters split by *client API*, not host
(ADR 0051): the `mastodon` adapter serves the Mastodon-API family (Mastodon,
GoToSocial, Pleroma/Akkoma — ADR 0049, 0050), and the `misskey` adapter serves
the Misskey-API family (Misskey, Sharkey, Firefish, Foundkey). ADR 0051's
Consequences named the next target explicitly:

> A future Fediverse software with yet another API (e.g. a Lemmy/PieFed
> link-aggregator post) would be a third such split, not a shape on either
> existing adapter.

That is this decision. **Lemmy** is Fediverse software — federated over
ActivityPub like Mastodon and Misskey — but it fills a different niche: it is a
*link aggregator*, the Reddit-shaped, community-organized discussion site, the
federated cousin of the centralized aggregators Scrolls already serves (Hacker
News — ADR 0031, Lobsters — ADR 0046). And like Misskey, Lemmy speaks its own
keyless API, not Mastodon's:

- A post is fetched by **`GET https://<instance>/api/v3/post?id=<id>`** (plain
  GET with a query param — no `post_json`, unlike Misskey's JSON-body POST), and
  its comments by a second GET, `/api/v3/comment/list?post_id=<id>`.
- The shapes are its own: a `post_view` wrapping `post` (with a real `name`
  title, an optional external `url`, a Markdown `body`, a pict-rs
  `thumbnail_url`, the federated `ap_id`), `creator`, `community`, and `counts`
  (`score`, `comments`); top-level `cross_posts` (the same submission in other
  communities); and a *flat* comment list whose `path` (`"0.<id>"`,
  `"0.<parent>.<id>"`) encodes the thread tree.

So Lemmy cannot ride either existing Fediverse adapter. It is a third source
with a third fetch path — while still being detected the same host-less,
shape-only way as the rest of the Fediverse. (We target API **v3**, the
backwards-compatible surface near-universally deployed; Lemmy 1.0's v4 was still
open beta as of this writing, and v4 keeps v3 working.)

## Decision

`scrolls add`/`fetch` of a Lemmy post runs a new keyless adapter
(`src/scrolls/sources/lemmy.py`), the **twenty-first**, the fourth Fediverse
API, and the first *federated link aggregator*:

- **Detection is shape-only, its own branch after misskey.** `detect.py` grows a
  `_lemmy_id` branch that runs after `_mastodon_id` and `_misskey_id` (their
  literals — `post` vs `@user`/`users`/`notice` vs `notes` — never collide) and
  before the pdf/web fallback: on any remaining host, a path of `/post/<digits>`
  yields the `lemmy` source with `source_id = <host>/<post_id>`. The host is part
  of identity (a post id is unique only within its instance) and is lowercased;
  the numeric id is kept verbatim.
  - **The all-digits id is the safety**, exactly as Mastodon's `/@<user>/<id>`
    form keeps a strict-numeric guard (ADR 0049). `post` is a weak literal —
    countless non-Fediverse sites have a `/post/...` path — so the constraint is
    strict: an all-digits id (Lemmy's autoincrement post id) *and* exactly two
    path segments, so a blog's `/post/<slug>` (non-numeric) or a
    `/post/<id>/<extra>` URL stays a `web` page (`tests/test_detect.py`). The
    residual risk — a non-Lemmy `/post/<digits>` URL the user wanted as `web` —
    degrades to a benign failed fetch (the API 404s), never a wrong scroll: the
    conservative, reversible tradeoff a host-less network forces (ADR 0049). The
    comment (`/comment/<id>`), community (`/c/<name>`), and user (`/u/<name>`)
    routes carry no post id and resolve to the source with no fetchable item —
    Hacker News's and Lobsters' pattern.
- **The shared GET transport serves it; no new transport.** Lemmy's API is plain
  GET with query params, so `http.get_json` is enough — unlike Misskey, which
  needed `http.post_json` for its JSON request body (ADR 0051).
- **The thread is a second GET, skipped when empty, degrading on failure.** The
  post fetches first; if `counts.comments` is zero the `comment/list` call is
  skipped (Misskey's economy, ADR 0051), and a *failed* comment fetch degrades to
  a post-only scroll (Stack Exchange's answers-are-optional rule, ADR 0033)
  (`test_no_comments_skips_the_comment_request`,
  `test_comment_failure_degrades_to_post_only`). `extraction_method` records
  which path ran (`lemmy-api:post+comments` vs `…:post`). The request is bounded
  (`max_depth=8`, `limit=50`), the deeper tail surviving in `raw_text`.
- **Comments are sorted into thread pre-order, then bylined flat.** Lemmy returns
  a flat list whose `path` encodes the tree, so the comments are sorted by the
  path's integer segments — a parent immediately precedes its replies — and each
  is bylined with its author and score the way Lobsters/Stack Exchange byline a
  comment (`test_comments_are_bylined_and_thread_ordered`). Deleted and
  mod-removed comments carry no usable text and are skipped (Lobsters' rule,
  ADR 0046) (`test_deleted_and_removed_comments_are_skipped`). The `path`
  threading is not rendered into the text but survives in `raw_text` for a future
  nested render (Lobsters' `depth`).
- **A real title — no synthesis.** Unlike a Bluesky/Mastodon/Misskey social post
  (whose title is built from a byline), a Lemmy post has a real `name` title,
  like a Hacker News or Lobsters story. `author` is the creator's display name
  (falling back to the username), `published_at` is `post.published`, and
  `canonical_url` is the federated `ap_id` — so a post that originated on another
  instance points at its origin even when fetched via the saving instance
  (`test_remote_post_canonical_is_the_origin_ap_id`).
- **Link post vs text post vs image post.** A link post's external `url` is an
  article, recorded as a `link` (the Hacker News/Lobsters pattern,
  `test_link_post_url_becomes_a_link`); a text (self) post contributes its
  Markdown `body` as the searchable content (`test_text_post_has_no_link_and_keeps_its_body`).
  An *image* post's `url` is the image itself, told apart by the
  `url_content_type` the API reports (falling back to the URL extension), so it
  becomes `photo` media, never a duplicate link
  (`test_image_post_url_becomes_photo_media`). An article post's pict-rs
  `thumbnail_url` is kept as a preview `thumbnail` ref (the youtube/Mastodon
  thumbnail convention, ADR 0011), but not when the url already gave a photo
  (`test_link_post_thumbnail_becomes_thumbnail_media`).
- **Body URLs and cross-posts become links — the edges.** Outbound `http(s)`
  URLs in the Markdown body are scanned (Misskey's URL scan, ADR 0051), giving
  the cross-source edges of ADR 0044 (`test_body_urls_become_links`). The post's
  `cross_posts` — the same submission in other communities, often on other
  instances — become post↔post links by their `ap_id`
  (`test_cross_post_becomes_a_link`), kin to a Misskey quote-renote.
- **The community becomes a `concept`.** A Lemmy community (`c/rust`,
  `c/selfhosted`) is the post's topical home, like a subreddit and the one
  curated topical label a post carries, so it feeds the KB concept graph the way
  github repo topics and Lobsters tags do (ADR 0007)
  (`test_community_becomes_a_concept`). The slug `name` is used (not the human
  `title`) since KB pages merge concepts by slug.
- **An honest summary.** A text post leads its `summary` with the body's first
  paragraph (`test_summary_is_the_body_lead_paragraph`); a link or image post has
  no body of its own, so the summary is the engagement status `"Lemmy discussion:
  N points, M comments."` with singular/plural agreement
  (`test_link_only_post_summary_is_engagement_status`) — the Hacker News/Lobsters
  metadata-only posture (ADR 0031, ADR 0046).
- **No category default — unclassified like Hacker News, Lobsters, and the social
  adapters.** A Lemmy post is a heterogeneous aggregator entry, so it gets no
  source default in the rules engine; a `how to`/`guide` title still resolves via
  the title rules and the LLM engine (ADR 0015) can refine the rest, so
  `classify.py` needs no change (`tests/test_classify.py`).

Per the no-network rule (ADR 0001), the GET transport is injected and tests run
against payloads shaped from the live Lemmy v3 API (`tests/test_lemmy.py`).

## Consequences

- A saved Lemmy post from *any* instance becomes a clean scroll — real title,
  author, date, community-as-concept, the linked article or the post body, the
  comment thread in pre-order, cross-post and body links, and a thumbnail — the
  twenty-first keyless fetch adapter and the first federated link aggregator,
  completing the discussion-aggregator family alongside Hacker News and Lobsters.
- The Fediverse is now covered by **three** adapters split by client API, not
  host: `mastodon` (microblog statuses), `misskey` (Misskey notes), and `lemmy`
  (link-aggregator posts). Detection routes between them by URL shape (`@user`/
  `users`/`notice` vs `notes` vs `post`); this remains the honest model for a
  federation where "same protocol (ActivityPub)" does not mean "same client API."
- **PieFed** — another Lemmy-shaped link aggregator — is the analog of GoToSocial
  to Mastodon, *if* its API is Lemmy-compatible enough; but PieFed serves an
  `/api/alpha` namespace rather than `/api/v3`, so it is more likely a fourth
  split (its own source/adapter) than a `detect.py` route on this one — the same
  judgment ADR 0051 made for Misskey vs the mastodon forks, to be confirmed when
  PieFed is added. A Lemmy v4-only instance is the other deferred case: v3 is the
  near-universal surface today, and v4 keeps v3 working, so the upgrade is a
  future `api/v3`→`api/v4` tweak, not a redesign.
- Identity is `<host>/<post_id>`, the instance-local id the URL carries — the
  same pragmatic, URL-as-registered choice Bluesky, Mastodon, and Misskey make
  (ADR 0048–0051). A post reached through a different instance (a federated
  mirror with a different local id) does not yet dedupe against the origin; a
  home-instance-canonicalizing pass is the analogous future tightening, deferred
  for the same reason — it would add a fetch-time rewrite of the item id no
  adapter does today.
- **Deferred this slice:** deeper comment descendants beyond the depth/limit cap
  (the tail stays in `raw_text`); a threaded (indented) comment render rather
  than the flat pre-ordered byline list; the community as a richer first-class
  entity (a saved community/feed, the way `scrolls follow` handles feeds) rather
  than a single concept. The social/aggregator adapters now share near-identical
  `_plural`/`_clean`/`_dedupe`/`_text`/`_content_links` helpers by deliberate
  duplication; extracting a shared module (ADR 0051's `social.py` note) is a clean
  future `improve-codebase-architecture` step now that the duplication spans five
  adapters.
