# 0048: Bluesky via the keyless AppView; the open social post X could never be

Date: 2026-06-13

Status: accepted

## Context

IDEAS.md §6 deliberately deferred X/Twitter — "avoid X first because X
auth/session complexity is annoying" — and to this day `x` is the only
detected source with no fetch adapter: tweets arrive solely through the
Field Theory import (ADR 0009), so a pasted tweet URL registers at
`detected` and never enriches. The architecture doc's standing first
"next step" is *a native `x` fetch adapter*. But X has only gotten
harder: its public API is now paywalled and its read endpoints demand
auth, so a keyless `x` adapter is not on the table.

Bluesky is the open social network that makes the deferred feature
reachable. The AT Protocol exposes a fully public, read-only **AppView**
(`public.api.bsky.app`) — the same backend the web app reads — that
serves posts and their threads with no login, cookie, or token. A live
check confirmed `com.atproto.identity.resolveHandle` and
`app.bsky.feed.getPostThread` both answer `200` with plain JSON for the
project's descriptive User-Agent and no credentials. So Scrolls can get
the social-post source it never could from X, honestly keyless, in the
same spirit as the Lobsters adapter that landed keyless where Reddit's
`.json` now 403s (ADR 0046).

Two facts about the API shaped the design. (1) A `bsky.app` post URL is
`/profile/<actor>/post/<rkey>`, where `<actor>` is a *handle*
(`alice.bsky.social`) or a *DID* (`did:plc:…`). The thread endpoint is
keyed by the post's AT-URI (`at://<did>/app.bsky.feed.post/<rkey>`),
which needs the DID — so a handle URL costs one extra `resolveHandle`
GET, the two-request shape Stack Exchange (ADR 0033) and Hugging Face
(ADR 0041) already use, while a DID URL skips straight to the thread.
(2) `getPostThread` returns the post *and* its nested reply tree in one
response — the whole conversation, the way a Lobsters story's `.json`
returns its comment thread (ADR 0046).

## Decision

`scrolls add`/`fetch` of a Bluesky post runs a new keyless adapter
(`src/scrolls/sources/bluesky.py`):

- **Detection claims `bsky.app`, fetches only posts.** `detect_source`
  maps `bsky.app` (and `www.bsky.app`) to the `bluesky` source, and a
  post URL `/profile/<actor>/post/<rkey>` yields `<actor>/<rkey>` as the
  `source_id`. The actor is folded lowercase — handles are DNS names and
  `did:plc` identifiers are lowercase by construction, both
  case-insensitive, so `Alice.BSKY.Social` and `alice.bsky.social` dedupe
  — while the record key is kept verbatim. Profile pages, feeds, lists,
  and the home/search routes carry no post and become the source with no
  fetchable item, the host-claimed-but-only-some-paths-fetch pattern of
  Hacker News, Stack Exchange, and Lobsters (ADR 0031, 0033, 0046)
  (`tests/test_detect.py`).
  - The truly stable identity is the AT-URI's `did/rkey`, but the DID can
    only be learned at fetch time (a network call), so the actor the URL
    carries is used as registered — the same pragmatic choice every other
    adapter makes with the handle/owner/name its URL carries. A post saved
    once via its handle and once via its DID would be two items; handles
    change rarely, and the cost is a duplicate, not a fetch failure.
- **Handle → DID, then the thread.** When the actor is a handle, a first
  keyless `resolveHandle` GET turns it into the DID; a `did:` actor skips
  it (`test_did_url_skips_handle_resolution`). The AT-URI built from the
  DID keys one `getPostThread` call (`depth=6`, `parentHeight=0` — we
  render the post and its replies, not its ancestors).
- **The post is the content; its replies are the discussion.** The post
  `text` leads `extracted_text`, followed by the reply tree as a
  `### Replies` subsection, each reply bylined `Reply by <Display>
  (@handle) (N likes)` the way Lobsters bylines a comment (ADR 0046).
  The tree is flattened depth-first; deleted, blocked, and not-found reply
  nodes carry no usable post and are skipped, as are empty-text replies
  (image-only). `extraction_method` records whether replies rode along
  (`bluesky-appview:post+thread` vs `…:post`). The whole thread is kept in
  `raw_text` so a future nested render can indent by depth without a
  refetch — the raw-record-spine discipline (ADR 0031, 0046).
- **A post with no text of its own is still searchable.** An image-only
  post contributes its images' `alt` text as the body, so it is findable
  by what the picture shows (`test_image_post_uses_alt_as_content_and_media`).
- **External cards, quotes, and inline links become `links`.** An
  external link card (`app.bsky.embed.external#view`) contributes its
  `uri`; a quoted post (`app.bsky.embed.record#view`) contributes the
  quoted post's `bsky.app` URL — a post↔post edge `scrolls related`/
  `graph` resolve back to the quoted item (ADR 0044); inline `#link`
  richtext facets contribute the URLs embedded in the text. A `recordWithMedia`
  embed (quote *and* media) yields both. So a post pointing at an arXiv
  paper, a github repo, or another saved post wires to it the way every
  adapter's cross-source links do. Blocked/detached quotes have no usable
  identity and contribute nothing (`test_blocked_quote_contributes_no_link`).
- **Embedded images become `media`.** Each image's `fullsize` URL is a
  `photo` ref (alt text retained), so `scrolls media` captures it; the
  Bluesky CDN's extensionless `…@jpeg` URL resolves to `.jpg` through the
  `photo` type fallback `media.py` already has for tweet photos — verified
  live. A video embed contributes its `thumbnail` (HLS playlists are not a
  single downloadable file).
- **`#hashtag` facets become `concepts`.** Bluesky stores hashtags as
  `app.bsky.richtext.facet#tag` features; they are curated topical labels,
  so they feed the KB concept graph the way github repo topics (ADR 0007),
  Stack Exchange tags (ADR 0033), and Lobsters tags (ADR 0046) do.
- **A synthesized title, an honest summary.** Social posts have no title
  field, so one is synthesized — `"<byline>: <lead line>"`, or
  `"Post by <byline> on Bluesky"` for a textless post — which keeps the
  scroll searchable and gives it a meaningful slug. `summary` leads with
  the post's first paragraph, falling back (for a textless post) to image
  alt text, then the link card's title, then the engagement status
  `"Bluesky post: N likes, M reposts, K replies."` — the metadata-only
  posture Hacker News uses for a link story (ADR 0031), with singular/
  plural agreement including the irregular "reply"/"replies".
- **No category default — unclassified like Hacker News and Lobsters.** A
  Bluesky post is a heterogeneous social entry (an announcement, an
  opinion, a link, a thread), so it gets *no* source default in the rules
  engine, exactly the Hacker News and Lobsters posture (ADR 0031, 0046).
  A `how to`/`guide` title still resolves to `tutorial` via the title
  rules, and the LLM engine (ADR 0015) can refine the rest; `classify.py`
  needs no change.

Per the no-network rule (ADR 0001), both GETs are injected and tests run
against payloads shaped from the live API (`tests/test_bluesky.py`); the
network path was verified by hand
(`scrolls ingest https://bsky.app/profile/bsky.app/post/3mnzmprxpe22y`,
through `fetch` → `md` → `media`).

## Consequences

- A saved Bluesky post becomes a clean scroll — synthesized title,
  author, date, hashtags-as-concepts, embedded images, the linked
  article or quoted post, and the full reply thread — the eighteenth
  keyless fetch adapter.
- The deferred social-post source is finally reachable. `x` (Field Theory
  import only, ADR 0009) remains the sole detected source without a fetch
  adapter, but the *capability* IDEAS.md §6 set aside — enrich a saved
  social post from a pasted URL — now exists on the open network where it
  can be done keyless.
- Bluesky joins Hacker News, Stack Exchange, and Lobsters as a
  discussion-with-a-thread adapter, sharing the link-degrades and
  tags-as-concepts patterns; its distinctive trait is the handle→DID
  resolution the AT-URI identity scheme forces, the cleanest example yet
  of "the URL's id isn't quite the platform's id."
- Identity is handle-based where the platform's is DID-based, so a post
  saved under both spellings would duplicate. The doctor's duplicate
  merge (ADR 0026) is keyed on URL normalization, not identity
  resolution, so it would not catch this; a DID-canonicalizing pass
  (resolve every handle id to its DID at fetch time and store the DID
  form) is the obvious future tightening, deferred because it adds a
  fetch-time rewrite of the item id that no other adapter does.
