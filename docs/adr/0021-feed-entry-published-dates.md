# ADR 0021: Feed entry published dates seed detected items

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

Sync registers feed entries as detected items, and since the previous
slice the entry's feed title seeds the item. Entry dates were still
dropped: RSS 2.0 `<pubDate>` and Atom `<published>`/`<updated>` were not
parsed, so synced items had no `published_at` until fetch — and for
YouTube the fetch adapter (keyless oEmbed, ADR 0003) carries no publish
date at all, so synced videos would *never* get one. Worse, four fetch
adapters wrote `published_at=<source date> or None`, which would have
erased a seeded date even where the source had nothing better.

## Decision

1. **Parse entry dates and seed `published_at`.** `parse_feed` reads
   RSS 2.0 `<pubDate>` and Atom `<published>` (falling back to
   `<updated>`, the only date Atom requires), and `sync_subscription`
   stores the result on the new item exactly like the entry title:
   `INSERT OR IGNORE` keeps known items untouched, and re-syncs never
   backfill.
2. **Normalize to UTC ISO 8601 at the parser.** RFC 822 pubDates
   (`Tue, 02 Jun 2026 10:00:00 GMT`) and RFC 3339 timestamps both
   become `isoformat(timespec="seconds")` in UTC, the same shape as
   `saved_at`/`added_at` — one feed format must not leak its date
   syntax into the schema. Naive datetimes are assumed UTC; an
   unparseable date becomes an honest `None`, never stored garbage.
   `dc:date` and other extension elements stay out of scope until a
   real feed needs them.
3. **Fetch follows the title precedent: the source's own date wins,
   the seeded date is the fallback.** The web, arxiv, github, and pdf
   adapters now write `published_at=<source date> or
   item.published_at`; wikipedia and youtube never touch the field, so
   `dataclasses.replace` preserves the seed automatically. A feed's
   date is honest provenance, but the source knows itself best.

## Consequences

- Synced YouTube videos finally carry a publish date — the channel
  feed is the only keyless place one exists.
- A rendered scroll's frontmatter `published_at` (always optional per
  `docs/library-format.md`) is now populated for feed-discovered items
  whose adapters find no better date.
- `published_at` values written by sync are uniformly UTC ISO 8601;
  adapter-written values still vary with what each source emits
  (e.g. trafilatura's `YYYY-MM-DD`, GitHub's `Z` suffix) — normalizing
  those is a separate decision if sorting ever needs it.
- `scrolls add` still seeds nothing: a bare URL has no date to offer.

## Proof

`_parse_date` + `FeedEntry.published` in `src/scrolls/feeds.py`, the
fallback edit in the four adapters, all offline-tested
(`tests/test_feeds.py` date tests, seeded-`published_at` preservation
tests in `tests/test_web.py`, `tests/test_github.py`,
`tests/test_arxiv.py`, `tests/test_pdf.py`, `tests/test_youtube.py`;
432 passing).
