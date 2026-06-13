# 0046: Lobsters via the keyless JSON API; the whole discussion in one request

Date: 2026-06-13

Status: accepted

## Context

Lobste.rs is a small computing-focused link aggregator — the same
developer-discussion niche as Hacker News (ADR 0031) and a common save
target for Scrolls' core audience (IDEAS.md §11). Until now a
`lobste.rs/s/<id>` URL fell through to the generic `web` adapter
(ADR 0001), whose `trafilatura` pass over the HTML page captures the
submission prose but mangles the threaded discussion, where most of the
value of a Lobsters thread lives.

Lobsters exposes a stable, keyless JSON view of every page: append
`.json` to any URL. Two facts about the story endpoint
(`lobste.rs/s/<short_id>.json`) shaped the design. (1) Unlike Hacker
News, whose Firebase API returns one node per request so a comment tree
costs N fetches (deferred in ADR 0031), and unlike Stack Exchange, whose
answers are a separate paginated resource costing a second GET
(ADR 0033), a Lobsters story's `.json` returns the submission, its tags,
*and* the entire comment thread in a single response. The whole
discussion arrives for the price of one keyless request. (2) The API
ships pre-rendered plain-text fields — `description_plain` for the body,
`comment_plain` for each comment — so there is no HTML grammar to write
(contrast the `_html_to_text` helpers HN and Stack Exchange each carry).

A live check confirmed the endpoint answers `200` with plain JSON for the
project's descriptive User-Agent and no credentials, where Reddit's
analogous `.json` trick now returns `403` to unauthenticated clients — so
Lobsters is honestly keyless in a way Reddit no longer is.

## Decision

`scrolls add`/`fetch` of a Lobsters story runs a new keyless adapter
(`src/scrolls/sources/lobsters.py`):

- **Detection claims the host, fetches only stories.** `detect_source`
  maps `lobste.rs` (and `www.lobste.rs`) to the `lobsters` source, and a
  story URL `/s/<short_id>[/<title-slug>]` yields the `short_id` (a
  base-36 handle like `vg5hdf`) as the `source_id`, kept verbatim — the
  trailing slug is decoration, identity is the short id. Comment
  permalinks (`/c/<id>`), tag pages (`/t/<tag>`), user pages
  (`/u/<user>`), and the front page carry no story id and become the
  source with no fetchable item — exactly Hacker News's and Stack
  Exchange's pattern (ADR 0031, ADR 0033), where the host is claimed but
  only some paths fetch (`src/scrolls/sources/detect.py`,
  `tests/test_detect.py`).
- **The whole discussion is the scroll, in one request.** The story's
  `description_plain` body (when present) and every comment's
  `comment_plain`, joined as a `### Comments` subsection, become the
  searchable `extracted_text`. Each comment is bylined with its author
  and score the way Stack Exchange bylines an answer (ADR 0033); the
  thread is rendered in the API's display (threaded) order.
  `extraction_method` records whether comments rode along
  (`lobsters-api:story+comments` vs `lobsters-api:story`). Deleted and
  moderated comments carry no usable text and are skipped. Because the
  comments arrive free in the one request, the adapter keeps *all* of
  them rather than capping like Stack Exchange's `pagesize=5` (whose cap
  exists because answers are a separate request).
- **A link submission records its article; a text submission its body.**
  A submission with a `url` (the common case) has no body of its own, so
  the linked article rides along in `links` as a bare URL — one
  `scrolls add` away and resolvable by `scrolls related`/`graph`, exactly
  the Hacker News link-story treatment (ADR 0031). A text submission
  (`url` is the empty string) contributes its `description_plain` body. A
  submitter note on a link submission counts as a body and leads.
- **`summary` leads with the body, else the discussion status.** Like
  Wikipedia, Hacker News, and Stack Exchange (ADR 0002, 0031, 0033), the
  body's first paragraph is the summary; a body-less submission degrades
  to the honest status the API reports — `"Lobsters discussion: N points,
  M comments."` (singular units handled) — and a stub with neither gets
  no invented summary (the honestly-empty posture, ADRs 0004, 0013).
- **Tags become `concepts`.** A story's curated tags — `css`,
  `security`, `ask` — are topical labels identical in spirit to github
  repo topics (ADR 0007) and Stack Exchange tags (ADR 0033), so they feed
  the KB concept pages the same way. They are not mirrored into `tags`,
  which stays the organizational field bookmarks-import folders write
  (ADR 0030).
- **Pre-rendered plain text, only tidied.** `description_plain` and
  `comment_plain` are already Markdown-rendered to text, so the adapter
  only normalizes line endings (CRLF → LF) and collapses blank runs — no
  tag grammar, the simplification the `_plain` API fields buy over HN/SE.
- **No category default — Lobsters is unclassified like Hacker News.** A
  Lobsters story is a heterogeneous link aggregator entry (a paper, a
  tool, an opinion, a tutorial), so — unlike Stack Exchange's weak
  `reference` default (ADR 0033) — it gets *no* source default in the
  rules engine, exactly Hacker News's posture (ADR 0031, no weak default,
  only the `Show HN` title rule). A `how to`/`guide` title still resolves
  to `tutorial` via the title rules, and the LLM engine (ADR 0015) can
  refine the rest. `classify.py` needs no change; the decision is locked
  by `test_lobsters_stays_unclassified_like_hacker_news` and
  `test_lobsters_tutorial_title_still_wins`.
- **The raw story object is kept in `raw_text`.** Comments and their
  `depth` survive verbatim, so a future enrichment (a threaded render
  that indents by depth) can expand a scroll without a refetch — the
  raw-record-spine discipline HN, Stack Exchange, github, and arxiv
  already follow.

Per the no-network rule (ADR 0001), the single GET is injected and tests
run against payloads trimmed from the live API
(`tests/test_lobsters.py`); the network path was verified once by hand
(`scrolls ingest https://lobste.rs/s/vg5hdf`).

## Consequences

- A saved Lobsters story becomes a clean scroll — title, author, date,
  tags-as-concepts, the linked article, and the full comment thread —
  instead of a `trafilatura` scrape of the HTML page. The seventeenth
  keyless fetch adapter; `x` (Field Theory import only, ADR 0009) remains
  the sole detected source without one.
- This is the cheapest of the three discussion adapters: one request
  carries metadata, body, tags, *and* the whole thread, where Hacker News
  defers comments entirely and Stack Exchange spends a second GET on
  answers. The `_plain` API fields also make it the simplest — no
  HTML-to-text helper.
- Keeping every comment (no cap) means a very popular thread produces a
  large `extracted_text`. That is genuine discussion content, FTS handles
  it, and it costs no extra request; should it ever matter, a cap is a
  one-line change with the raw thread already preserved in `raw_text`.
- Lobsters joins Hacker News and Stack Exchange as the third
  discussion-aggregator adapter, all sharing the link-story-degrades and
  tags-as-concepts patterns — the same one-adapter leverage Wikipedia's
  per-language and Stack Exchange's per-site coverage get.
