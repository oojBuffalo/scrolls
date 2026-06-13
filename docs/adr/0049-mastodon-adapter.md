# 0049: Mastodon via the keyless REST API; a federated source matched by URL shape

Date: 2026-06-13

Status: accepted

## Context

The Bluesky adapter (ADR 0048) reached the social-post source IDEAS.md §6
deferred X for, on the open network where it can be done keyless. Mastodon
is the other open social network — and the obvious next one — but it poses
a problem no adapter before it has: it is *federated*. There is no
`bsky.app`, no single host. A Mastodon account lives on one of thousands of
independent instances (`mastodon.social`, `hachyderm.io`,
`infosec.exchange`, `front-end.social`, …), and a post's URL carries that
instance's hostname. Every other adapter keys detection off a known host
set; Mastodon cannot be a host set, because the set is open and grows
daily.

What *is* uniform is the API and the URL shape. Every Mastodon instance (and
its API-compatible forks — Hometown, glitch-soc) serves the same keyless
read endpoints:

- `GET https://<instance>/api/v1/statuses/<id>` — the status, no auth for a
  public post.
- `GET https://<instance>/api/v1/statuses/<id>/context` — its `ancestors`
  and `descendants` (the thread), already flattened.

And a public status has two canonical URL forms on its instance:

- `/@<user>/<status_id>` — the web/UI permalink people copy.
- `/users/<user>/statuses/<status_id>` — the ActivityPub object URL.

In both, the `<status_id>` is a snowflake **integer**. That numeric
constraint is the lever that makes host-agnostic detection safe.

## Decision

`scrolls add`/`fetch` of a Mastodon status runs a new keyless adapter
(`src/scrolls/sources/mastodon.py`):

- **Detection is by URL shape, not host.** `detect_source` grows one branch
  that runs *after* every known-host branch and *before* the generic
  pdf/web fallback: on any remaining host, a path of `/@<user>/<digits>` or
  `/users/<user>/statuses/<digits>` yields the `mastodon` source with
  `source_id = <host>/<status_id>`. The host is part of identity because a
  status id is unique only within its instance; it is lowercased (DNS is
  case-insensitive), and the two URL forms collapse to the same
  `<host>/<status_id>` so a status saved either way dedupes
  (`tests/test_detect.py`).
  - **The all-digits id is the safety.** Requiring the last segment to be
    numeric is what keeps a host-agnostic heuristic from stealing
    lookalikes: a Medium `/@author/<slug>` post (the slug is non-numeric), a
    Threads or TikTok `/@user/<kind>/<id>` (three segments). Those fall
    through to `web` unchanged. The residual risk — a genuinely non-Mastodon
    `/@x/<digits>` URL the user wanted fetched as `web` — is rare, and its
    failure mode is benign: the adapter's API call 404s, the item stays at
    `detected` (a failed fetch, never a wrong scroll), and the user can
    `rm` and re-add. This is the conservative, reversible tradeoff a
    federated network with no host list forces, and it is the first adapter
    whose detection is shape-only rather than host-anchored.
- **The thread is a second request, skipped when empty.** The status fetches
  first; if its `replies_count` is zero the context call is skipped
  entirely (`test_no_replies_skips_the_context_request`) — Bluesky's
  economy of not paying for a thread that isn't there. When replies exist,
  the context call runs, and a *failed* context fetch degrades to a
  post-only scroll rather than failing the item
  (`test_context_failure_degrades_to_post_only`), the answers-are-optional
  rule Stack Exchange established (ADR 0033). `extraction_method` records
  which path ran (`mastodon-api:status+thread` vs `…:status`).
- **HTML content becomes plain text with a stdlib parser.** Mastodon's
  `content` is HTML (`<p>`, `<br>`, `<a>`); it is reduced to searchable
  text by a small `html.parser.HTMLParser` subclass — `</p>` → blank line,
  `<br>` → newline, entities unescaped — with no `trafilatura` dependency,
  the keyless/stdlib spirit of the adapter family (Crossref's JATS strip,
  ADR 0037, is the same instinct). The parser collects outbound links in
  one pass.
- **`descendants` is flat, so replies render in one pass.** Unlike Bluesky's
  nested reply tree, Mastodon's context returns descendants already
  flattened in thread order, so there is no recursive walk: each reply is
  bylined `Reply by <Display> (@acct) (N favourites)` (Bluesky's reply
  format, ADR 0048), and a reply with no text of its own is skipped. The
  whole thread (`{status, context}`) is kept in `raw_text` for a future
  rebuild — the raw-record-spine discipline (ADR 0031, 0046, 0048).
- **A post with no text of its own is still searchable.** An image-only
  post contributes its attachments' `description` (alt text) as the body,
  so it is findable by what the picture shows
  (`test_image_post_uses_alt_as_content_and_media`).
- **Content links, the card; not mentions or hashtags.** The link-preview
  `card.url` and any plain `<a href>` in the body become `links`, so a post
  pointing at an arXiv paper or a github repo wires to it through
  `scrolls related`/`graph` (the cross-source edges of ADR 0044). The
  `@mention` and `#hashtag` anchors Mastodon marks with a `mention`/
  `hashtag` class are navigation, not references, and are excluded
  (`test_content_and_card_urls_become_links_skipping_mentions_and_tags`).
- **Attachments become `media`; a video keeps its preview.** An image is a
  `photo` ref at its full-size `url`; a video or GIF is a `thumbnail` ref at
  its `preview_url` — the video file can be huge, so only its poster image
  is captured, the youtube-thumbnail rule (ADR 0011)
  (`test_video_post_captures_the_preview_image`). Alt text rides along.
- **`#hashtag` names become `concepts`.** Mastodon's `tags` are `{name, url}`
  objects with a bare `name`; they are curated topical labels, so they feed
  the KB concept graph the way github repo topics (ADR 0007) and Bluesky
  hashtags (ADR 0048) do.
- **A content warning leads the body, honestly.** A `spoiler_text` content
  warning is prepended as a `CW: …` line so the text it hides stays
  searchable and the scroll declares it
  (`test_content_warning_leads_the_body_and_summary`); the summary still
  leads with the actual post text, not the warning.
- **A boost unwraps to the boosted post.** If the fetched status is a reblog
  (boost), its content is an empty shell around the original in `reblog`;
  the adapter unwraps to that original for content, author, concepts, date,
  and canonical URL, keeping the saved identity
  (`test_reblog_unwraps_to_the_boosted_post`).
- **A synthesized title, an honest summary.** Social posts have no title, so
  one is synthesized — `"<byline>: <lead line>"`, or `"Post by <byline> on
  Mastodon"` for a textless post. `summary` leads with the post's first
  paragraph, falling back to image alt text, then the card title, then the
  engagement status `"Mastodon post: N favourites, M boosts, K replies."`
  with singular/plural agreement
  (`test_textless_cardless_post_summary_is_engagement_status`) — the
  metadata-only posture of Bluesky and Hacker News (ADR 0048, 0031).
- **No category default — unclassified like Bluesky, Hacker News, Lobsters.**
  A Mastodon post is a heterogeneous social entry, so it gets *no* source
  default in the rules engine; a `how to`/`guide` title still resolves via
  the title rules and the LLM engine (ADR 0015) can refine the rest, so
  `classify.py` needs no change.

Per the no-network rule (ADR 0001), both GETs are injected and tests run
against payloads shaped from the live Mastodon API (`tests/test_mastodon.py`).

## Consequences

- A saved Mastodon post from *any* instance becomes a clean scroll —
  synthesized title, author, date, hashtags-as-concepts, attached images,
  the linked article, and the reply thread — the nineteenth keyless fetch
  adapter and the second open social network after Bluesky.
- Detection is, for the first time, shape-only rather than host-anchored.
  This is the right model for a federated network (the host set is open),
  and the numeric-id constraint plus the fetch-time API validation bound the
  false-positive cost to a recoverable failed fetch. It also establishes the
  pattern the rest of the Fediverse can follow: Pleroma/Akkoma and
  GoToSocial expose the same `/api/v1/statuses` surface but mint
  non-numeric ids on different URL routes, so each is a future shape branch,
  not a rewrite.
- Identity is `<host>/<status_id>`, the instance-local id the URL carries.
  A post reached through a *different* instance (a remote-rendered copy) or
  by its canonical home URL would be a separate item — the same
  pragmatic, URL-as-registered choice Bluesky makes with handle-vs-DID
  (ADR 0048). A home-instance-canonicalizing pass is the analogous future
  tightening, deferred for the same reason: it would add a fetch-time
  rewrite of the item id no adapter does today.
- Mastodon joins Bluesky, Hacker News, Stack Exchange, and Lobsters as a
  discussion-with-a-thread adapter, sharing the link-degrades,
  tags-as-concepts, and no-category-default patterns; its distinctive trait
  is the host-agnostic, shape-only detection federation forces.
