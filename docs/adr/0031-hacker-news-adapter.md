# 0031: Hacker News via the keyless Firebase API; link posts degrade to metadata-only

Date: 2026-06-13

Status: accepted

## Context

Hacker News is one of the most common save targets a developer has, and
until now `news.ycombinator.com/item?id=…` fell through to the generic
`web` adapter (ADR 0001), which runs `trafilatura` over the comment
page — extracting a tangle of nested replies, not the thing the user
saved. HN also publishes a famously open, keyless, stable JSON API
(the Firebase v0 endpoints), so a dedicated adapter is both more honest
and cheaper than scraping the HTML.

An HN item is not one kind of thing. A **story** is usually a *pointer*:
a title, an author, a score, a comment count, and an external `url` —
the discussion is the artifact, the linked article lives elsewhere. An
**Ask HN** / **Show HN** / **comment** is a *text* item: its `text`
field carries the body in HN's limited HTML subset (`<p>` as an
unclosed paragraph separator, `<i>`, `<a>`, `<pre><code>`, and HTML
entities). The adapter has to serve both shapes from one `item` object.

## Decision

`scrolls add`/`fetch` of an HN item runs a new adapter
(`src/scrolls/sources/hackernews.py`), keyless, one GET against
`https://hacker-news.firebaseio.com/v0/item/<id>.json`:

- **Detection claims the host, fetches only `/item`.**
  `news.ycombinator.com` (and the `www.` variant) maps to source
  `hackernews`; the numeric `id` query param of an `/item` path is the
  `source_id`, so item ids are `hackernews:<id>` (`src/scrolls/sources/detect.py`).
  The front page, `/newest`, `/user?id=…` and the like are the source
  with no fetchable id — exactly github's pattern, where `github.com`
  is the source but only `owner/repo` paths fetch (ADR 0007). A
  non-`/item` HN URL therefore becomes an item whose fetch raises
  `FetchError` with a clear message, rather than silently becoming a
  `web` scrape.
- **Text posts carry a body; link posts degrade to metadata-only.**
  When `text` is present (Ask HN, a Show HN with a body, a comment),
  the HTML-stripped text is `extracted_text` and its lead paragraph is
  the `summary` — the way Wikipedia leads (ADR 0002). When there is no
  `text` (a link story), there is no body to extract: the item degrades
  to a metadata-only scroll, the same graceful degradation a
  caption-less YouTube video makes (ADR 0003). `extraction_method`
  records which path ran (`hn-firebase:item+text` vs `hn-firebase:item`).
- **A link post's summary is its discussion status.** With no body, the
  honest one-line summary is what HN itself adds: `"Hacker News
  discussion: N points, M comments."` (singular units handled). A bare
  metadata stub with neither score nor comment count gets no summary at
  all rather than an invented one — the project's recurring
  honestly-empty-beats-guessed posture (ADRs 0004, 0013).
- **The linked article rides along as a bare URL in `links`.** A story's
  external `url` is stored unlabelled (not `"Article: …"`) so
  `related`'s link signal can run it through `detect_source` and connect
  the saved discussion to a separately-saved copy of the article
  (`src/scrolls/related.py`, IDEAS.md §10). Fetching that article stays
  the `web` adapter's job, one `scrolls add` away — adapters don't chain.
- **`canonical_url` is the item page.** Whatever decorated HN URL the
  user pasted normalizes to `https://news.ycombinator.com/item?id=<id>`,
  so re-saves dedupe and the scroll always points at the stable
  discussion.
- **Comments synthesize a title.** A comment has no `title`, so the
  adapter writes `"Comment by <author>"` (the render fallback to the id
  would be unreadable).
- **HTML is stripped with stdlib, real markup before entities.** `<p>`
  becomes a paragraph break, remaining tags are dropped by regex, then
  `html.unescape` runs — in that order, so escaped angle brackets inside
  quoted code (`&lt;p&gt;`) survive as literal text instead of being
  mistaken for tags. No new dependency for a four-tag grammar (ADR 0001).
- **Show HN → project; Ask HN stays unclassified.** A "Show HN" post is
  someone presenting a thing they built, so a title rule classifies it
  `project` (`src/scrolls/classify.py`, ADR 0004) — the same bucket
  github repos get. "Ask HN" is a question with no honest single
  category, so the rules leave it for the LLM engine (ADR 0015). HN is
  *not* a curated-source category (ADR 0004): unlike wikipedia→reference,
  an HN link can point at anything.

Per the no-network rule (ADR 0001), the JSON fetcher is injected and
tests run against payloads recorded from the live API
(`tests/test_hackernews.py`).

## Consequences

- A saved HN discussion becomes a clean scroll — title, author, date,
  points/comments, the linked URL — instead of a scrape of its comment
  thread. The seventh keyless fetch adapter; every detected source
  except `x` (Field Theory import only, ADR 0009) now fetches.
- `kids` (the comment id tree) is preserved verbatim in `raw_text`, so a
  future comment-tree enrichment can expand a discussion into extracted
  text without a refetch — the same raw-record-spine discipline the
  github and arxiv adapters follow.
- The link-post `summary` mixes content (text leads) and metadata
  (discussion status) across item types. This is deliberate and matches
  the per-source summary semantics already in play (github=description,
  pdf=`/Subject`, arxiv=abstract); it is documented here so a reader
  isn't surprised that an HN summary sometimes describes the artifact
  rather than quoting it.
- A bookmarked or feed-synced HN URL (ADR 0030, ADR 0017) now enriches
  through this adapter automatically — bulk HN saves get first-class
  treatment with no extra command.
