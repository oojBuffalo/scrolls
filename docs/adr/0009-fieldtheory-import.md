# 0009: X bookmarks arrive via Field Theory import, not native sync

Date: 2026-06-12
Status: superseded by [0108](0108-x-bookmarks-native-sync.md)

*Amended: 2026-07-26 — the Field Theory import proposal moved from the
IDEAS.md brainstorm into `docs/inspiration/fieldtheory-cli-inspiration.md`;
the references below were updated. Decision content unchanged.*

## Context

The Field Theory import proposal
(`docs/inspiration/fieldtheory-cli-inspiration.md`) names
`scrolls import fieldtheory` as the path to X/Twitter
bookmarks: native X sync needs auth/session plumbing (the reason IDEAS.md
§6 deferred X from the MVP trio), while Field Theory already maintains a
local archive.
On this machine the archive holds 430 bookmarks; its layout:

- `bookmarks/bookmarks.jsonl` — one raw record per bookmark (id, url, text,
  author, postedAt, engagement, media, expanded links, quoted tweet).
- `library/bookmarks/*.md` — Field Theory's classified pages, whose
  frontmatter carries `tweet_id`, `category`, `domain`.
- `bookmarks.db` — Field Theory's internal SQLite cache.

IDEAS.md §13 also distinguishes `import` (bulk local archive) from `sync`
(live deltas) and `add` (one URL).

## Decision

`scrolls import fieldtheory [--root PATH]` (default `~/.fieldtheory`) bulk-
imports the JSONL cache as items with `source="x"`:

- **JSONL is the spine; the `.db` is not read.** The JSONL is Field
  Theory's own durable raw-record store and survives that tool's internal
  schema changes. Each line is preserved verbatim in `raw_text` so scrolls
  and indexes can be rebuilt without Field Theory installed.
- **Classified pages are an optional join.** Frontmatter `category`/
  `domain` are matched by `tweet_id` and carried onto the imported item —
  prior classification work is not thrown away. A missing `library/`
  directory or unparseable page just means no carried-over category, and
  `scrolls classify` can fill the gap later (batch classify never
  overwrites what the import set).
- **Imported items enter at stage `fetched`.** Content is already local
  and there is no x fetch adapter; entering at `detected` would strand
  them in every `scrolls fetch` run. `md`, `classify`, and `kb` work on
  them unchanged. This is the first non-adapter producer of fetched
  items, establishing the boundary: fetch adapters pull one item from the
  network, importers bulk-read local archives.
- **Ids align with URL detection.** `x:<tweetId>` matches what
  `detect.py` produces for x.com status URLs, so `scrolls add` of a tweet
  URL and a later import dedupe against each other.
- **Re-imports are idempotent skips.** `INSERT OR IGNORE` semantics, like
  `add`: existing items (earlier imports, manual edits) are never
  overwritten. A future `--refresh` flag can revisit this.
- **Tweets have no titles, so one is derived**: `@handle: <text…>` capped
  at 80 chars — readable slugs, and the handle adds search signal.
- Per-line parse failures are reported with line numbers and do not abort
  the batch (exit 1 signals partial failure); a missing JSONL is a hard
  error.

## Consequences

- 430/430 real bookmarks import, render, and search cleanly; the KB gains
  a `sources/x` page and 26 category pages carried over from Field Theory.
- The `import` subcommand namespace now exists for future bulk paths
  (e.g. `scrolls import google-takeout`, IDEAS.md §13).
- The minimal frontmatter parser in `fieldtheory.py` reads only simple
  `key: value` lines; if Field Theory's page format changes materially,
  the join degrades gracefully to "no carried-over classification".
- Native `scrolls sync x --bookmarks` remains open as a later, separate
  decision (the import proposal's "later" path,
  `docs/inspiration/fieldtheory-cli-inspiration.md`). **Settled by
  [ADR 0108](0108-x-bookmarks-native-sync.md)**, which supersedes this record:
  native sync ships over the browser session, and the `x:<tweetId>` identity
  rule above is the property carried across.
