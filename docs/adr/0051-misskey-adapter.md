# 0051: Misskey via its own keyless API — a Fediverse source that is *not* Mastodon-API-compatible

Date: 2026-06-13

Status: accepted

## Context

ADR 0049 made Mastodon the first source detected by URL *shape* rather than
host, because the Fediverse is federated across thousands of instances with no
host set to claim. ADR 0050 then showed that detection-shape generalizes: the
Mastodon-API-compatible forks GoToSocial and Pleroma/Akkoma needed only new
`detect.py` routes, because they serve the *identical* keyless
`/api/v1/statuses/<id>` (+ `/context`) endpoints and return Mastodon-shaped
JSON — the fetch adapter never changed.

Both ADRs named the obvious next target: **Misskey** and its forks (Sharkey,
Firefish/Calckey, Foundkey), whose web permalink is `/notes/<id>`. The earlier
ADRs assumed it would be another shape branch on the mastodon adapter — "a new
anchor-and-id row, not a rewrite." Investigating the API shows that assumption
is wrong, and the correction is the substance of this decision.

**Misskey does not implement the Mastodon API.** It has its own, equally
keyless API, but it differs at every layer that matters to an adapter:

- The note is fetched by **`POST https://<instance>/api/notes/show`** with a
  JSON body `{"noteId": <id>}` — a POST with a request body, where every
  adapter so far used a GET (with query params at most). The reply thread is a
  second POST, `notes/children` with `{"noteId", "limit"}`, returning a *flat
  list* of child notes.
- The note shape is its own: `text` (not HTML `content`) carrying **MFM**
  (Misskey Flavored Markdown, already plain text), `cw` (not `spoiler_text`),
  `user` (not `account`) with `name`/`username`/`host`, `files` (not
  `media_attachments`) with a `comment` alt field, `tags` as **bare strings**
  (not `{name, url}` objects), `renote` (not `reblog`), and `reactions` as a
  `{":emoji:": count}` map (not a single `favourites_count`).

So Misskey cannot ride the mastodon adapter the way the forks do. It is a
genuinely separate source with a genuinely separate fetch path — while still
being detected the same host-less, shape-only way as the rest of the Fediverse.

## Decision

`scrolls add`/`fetch` of a Misskey-family note runs a new keyless adapter
(`src/scrolls/sources/misskey.py`), the twentieth, and the third open social
network after Bluesky and Mastodon:

- **Detection is shape-only, like mastodon, but its own branch.** `detect.py`
  grows a `_misskey_id` branch that runs *after* `_mastodon_id` (their literals
  — `notes` vs `@user`/`users`/`notice` — never collide) and before the
  pdf/web fallback: on any remaining host, a path of `/notes/<id>` yields the
  `misskey` source with `source_id = <host>/<note_id>`. The host is part of
  identity (a note id is unique only within its instance) and is lowercased;
  the id is kept verbatim (`aidx`/`objectid`/`ulid` formats are case-sensitive).
  - **A charset + length floor is the safety**, exactly as Pleroma's weak
    `/notice/` form carries one (ADR 0050). `notes` is a weak literal — many
    non-Fediverse sites have a `/notes/<slug>` path — so the id must be a
    base62 run (no `-`/`.`/`_`, which a slug would have) at least **10**
    characters long. Ten is Misskey's shortest id format (`aid`); a 16-char
    floor like `/notice/`'s would miss every `aid`-configured instance. A
    `/notes/getting-started` or `/notes/welcome` falls through to `web`
    (`tests/test_detect.py`). The residual risk — a non-Misskey
    `/notes/<10+ base62 chars>` URL the user wanted as `web` — degrades to a
    benign failed fetch (the POST 404s), never a wrong scroll: the
    conservative, reversible tradeoff a host-less network forces (ADR 0049).
- **A reusable JSON POST joins the shared transport.** `http.post_json(url,
  payload)` JSON-encodes a request body with `Content-Type: application/json`
  and the shared User-Agent, and parses the reply (which may be an object or an
  array). It is glue over urllib, so it is tested against a localhost server
  like `get_conditional` (`tests/test_http.py`), and it is now available to any
  future POST-bodied API.
- **The thread is a second POST, skipped when empty, degrading on failure.**
  `notes/show` fetches first; if `repliesCount` is zero the `notes/children`
  call is skipped (Bluesky's economy, ADR 0048), and a *failed* children fetch
  degrades to a note-only scroll (Stack Exchange's answers-are-optional rule,
  ADR 0033) (`test_no_replies_skips_the_children_request`,
  `test_children_failure_degrades_to_note_only`). `extraction_method` records
  which path ran (`misskey-api:note+thread` vs `…:note`). Children arrive flat,
  so the bylined replies render in one pass.
- **MFM `text` needs no HTML parser.** Misskey's `text` is already plain
  (Lobsters' `*_plain` economy, ADR 0046), so it is normalized the way mastodon
  normalizes *after* its HTML parse — paragraphs split on blank lines, internal
  whitespace collapsed — and the bodies read the same across the social
  adapters.
- **Links are scanned from the text; a quote links the quoted note.** Misskey
  has no Bluesky facet list and no Mastodon link card, so outbound `http(s)`
  URLs are read straight from the MFM text (trailing sentence/markdown
  punctuation trimmed), giving the cross-source edges of ADR 0044
  (`test_text_urls_become_links`). A quote-renote (a note with both its own
  text and a `renote`) keeps its text and adds the quoted note's URL as a
  post↔post link (`test_quote_note_keeps_text_and_links_the_quoted_note`).
- **A pure renote (boost) unwraps to the boosted note.** A renote with no text
  of its own is a boost; the adapter unwraps to the inner note for content,
  author, concepts, date, and canonical URL, keeping the saved identity
  (`test_renote_unwraps_to_the_boosted_note`) — Mastodon's `reblog` rule
  (ADR 0049).
- **`files` become media; a video keeps its thumbnail.** An image is a `photo`
  ref at its `url`; a video is a `thumbnail` ref at its `thumbnailUrl` — the
  video file can be huge, so only its poster is captured, the youtube/Mastodon
  rule (ADR 0011, ADR 0049) (`test_video_note_captures_the_thumbnail`). The
  `comment` alt text rides along, so an image-only note is searchable by what
  the picture shows (`test_image_note_uses_alt_as_content_and_media`).
- **`tags` (bare strings) become `concepts`**, the github-topics pattern
  (ADR 0007) (`test_hashtags_become_concepts`). A `cw` content warning leads
  the body so the hidden text stays honest and searchable, the summary still
  leading with the real text (`test_content_warning_leads_the_body`).
- **A synthesized title, an honest summary.** `"<byline>: <lead paragraph>"`,
  or `"Post by <byline> on Misskey"` for a textless note; `summary` leads with
  the note's first paragraph, falling back to image alt text, then the
  engagement status `"Misskey post: N reactions, M renotes, K replies."` with
  singular/plural agreement (`test_textless_note_summary_is_engagement_status`)
  — the metadata-only posture of Bluesky and Mastodon (ADR 0048, 0049).
- **No category default — unclassified like Bluesky, Mastodon, Hacker News,
  Lobsters.** A Misskey post is a heterogeneous social entry, so it gets no
  source default in the rules engine; a `how to`/`guide` title still resolves
  via the title rules and the LLM engine (ADR 0015) can refine the rest, so
  `classify.py` needs no change.

Per the no-network rule (ADR 0001), both POSTs are injected and tests run
against payloads shaped from the live Misskey API (`tests/test_misskey.py`).

## Consequences

- A saved Misskey/Sharkey/Firefish/Foundkey note from *any* instance becomes a
  clean scroll — synthesized title, author, date, hashtags-as-concepts,
  attached images, the linked article, and the reply thread — the twentieth
  keyless fetch adapter and the third open social network.
- The Fediverse is now covered by **two** adapters split by API, not host: the
  mastodon adapter serves the Mastodon-API family (Mastodon, GoToSocial,
  Pleroma/Akkoma — ADR 0049, 0050), and the misskey adapter serves the
  Misskey-API family. Detection routes between them by URL shape; this is the
  honest model for a federation where "same protocol (ActivityPub)" does not
  mean "same client API." A future Fediverse software with yet another API
  (e.g. a Lemmy/PieFed link-aggregator post) would be a third such split, not a
  shape on either existing adapter.
- `http.post_json` is the first reusable POST in the shared transport; the next
  JSON-body API inherits it for free.
- Identity is `<host>/<note_id>`, the instance-local id the URL carries — the
  same pragmatic, URL-as-registered choice Bluesky and Mastodon make
  (ADR 0048, 0049). A note reached through a different instance, or a
  home-instance-canonicalizing pass, is the analogous future tightening,
  deferred for the same reason: it would add a fetch-time rewrite of the item
  id no adapter does today.
- **Deferred this slice:** deeper reply descendants (only direct children are
  rendered, the rest stay in `raw_text`, Bluesky's depth cap); MFM markup is
  kept as-is rather than stripped (`$[fn …]`, custom emoji shortcodes), since
  it is lightweight and human-readable. The three social adapters (bluesky,
  mastodon, misskey) now share near-identical `_plural`/`_byline`/`_title`/
  `_image_alts` helpers by deliberate duplication; extracting a `social.py` is
  a clean future `improve-codebase-architecture` step once a fourth would copy
  them a third time.
