# ADR 0024: `published_at` is one vocabulary — UTC ISO 8601 from every writer

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

ADR 0021 normalized feed-seeded dates to UTC ISO 8601 but left
adapter-written values speaking their source's dialect: trafilatura's
bare `YYYY-MM-DD` (web), RFC 3339 `Z` suffixes (github, arxiv), and
pypdf creation datetimes with arbitrary offsets (pdf). The repo also
held three copies of the same normalization logic — `feeds._parse_date`,
`fieldtheory._iso`, and nothing at all in the adapters. Any consumer
sorting or comparing `published_at` had to parse several shapes, and
the README named this the remaining "next candidate".

## Decision

1. **One shared normalizer.** `to_utc_iso` in `src/scrolls/dates.py` —
   the `feeds._parse_date` logic moved verbatim: ISO 8601/RFC 3339 via
   `fromisoformat`, RFC 822 via `parsedate_to_datetime`, naive
   datetimes assumed UTC, output `isoformat(timespec="seconds")` in
   UTC, unparseable input an honest `None`. `feeds` and the Field
   Theory import now delegate to it (`fieldtheory._iso` deleted);
   `_parse_posted_at` keeps its Twitter-specific `strptime` but the
   shared helper handles everything else.
2. **Every adapter funnels its source date through it.** web, github,
   arxiv, and pdf write `published_at=to_utc_iso(<source date>) or
   item.published_at` — so an unparseable source date now degrades to
   the feed-seeded date (ADR 0021's fallback) instead of storing the
   source's garbage. wikipedia and youtube still never touch the field.
3. **Date-only inputs become midnight UTC.** trafilatura emits bare
   `YYYY-MM-DD`; `fromisoformat` reads it as midnight, which the
   pipeline stores as `T00:00:00+00:00`. The precision is invented,
   but one shape for the whole field beats two parsers in every
   consumer — and it is exactly what the established feeds parser
   already did with date-only input.

## Consequences

- `published_at` is now uniformly UTC ISO 8601 at seconds precision
  (or absent) no matter who wrote it: sync seed, any adapter, or the
  Field Theory import. Lexicographic order is chronological order.
- `docs/library-format.md` can promise the shape to library consumers
  instead of hedging per source.
- Existing rows keep their old dialects until re-fetched; nothing
  rewrites stored data (same no-migration posture as ADR 0023).
- Sub-second precision is trimmed, matching `saved_at`/`added_at`.

## Proof

`src/scrolls/dates.py` unit-tested in `tests/test_dates.py`; adapter
normalization pinned by the updated `published_at` assertions in
`tests/test_web.py`, `tests/test_github.py`, `tests/test_arxiv.py`,
`tests/test_pdf.py`; feeds and import behavior unchanged
(`tests/test_feeds.py`, `tests/test_fieldtheory.py` untouched and
green); 471 passing.
