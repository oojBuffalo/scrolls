# ADR 0002: First fetch adapter — Wikipedia via the MediaWiki action API

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

Pass 2's storage half is done: `scrolls add <url>` persists items at stage
`detected`. The next slice is the first adapter that actually fetches
content (IDEAS.md §6 names YouTube, Wikipedia, and web articles as the MVP
trio). Whichever lands first also fixes the adapter interface, the fetch
CLI surface, and the stage vocabulary that later adapters inherit.

## Decision

1. **Wikipedia first.** ADR 0001 commits to adding per-adapter
   dependencies only when an adapter lands; web extraction needs
   `trafilatura` and YouTube needs `yt-dlp`, while the MediaWiki API is
   plain JSON over one GET — zero new dependencies, no auth, and
   deterministic enough for unattended runs. `detect` also already
   resolves Wikipedia identity (`lang:title`) before any fetch.
2. **MediaWiki action API, not the REST summary endpoint.** One request
   (`prop=extracts|info`, `explaintext=1`, `redirects=1`,
   `formatversion=2`) returns the full plain-text page plus the canonical
   URL. The REST `page/summary` endpoint only yields the lead paragraph;
   full text is what makes search (Pass 3) and context bundles (Pass 5)
   valuable.
3. **Adapter interface: `fetch_item(item: ScrollItem) -> ScrollItem`.**
   A pure function per source module that fills content fields and returns
   the item at stage `fetched`, raising `scrolls.sources.FetchError` on
   any failure. `scrolls.sources.FETCH_ADAPTERS` maps source names to
   adapters; sources without an entry are skipped by bulk fetches.
   Function-based matches the codebase style; the richer
   `sync/enrich/normalize` split from IDEAS.md §1 can be layered on when a
   bulk-sync source (e.g. Field Theory import) needs it.
4. **CLI: `scrolls fetch [id]`.** Without arguments it processes every
   `detected` item, continuing past per-item failures (IDEAS.md §4
   resilience) and exiting 1 only if something failed. With an id it
   fetches that one item regardless of stage, which doubles as refetch.
5. **Stage vocabulary: `detected → fetched`.** IDEAS.md §4's `synced`
   describes bulk platform sync; for the add-one-URL path "fetched" is the
   honest name. Later stages keep the IDEAS.md names (`classified`,
   `rendered`, `indexed`).
6. **Raw record preservation.** The raw API page object is stored in
   `raw_text` so scrolls and indexes can be rebuilt without refetching
   (IDEAS.md §13). `content_hash` is `sha256:` + the digest of
   `extracted_text`; `summary` is the lead section (text before the first
   `== Heading ==` marker). Requests send a descriptive User-Agent per
   Wikipedia API etiquette.

## Consequences

- Item identity stays as assigned at add time even when the API resolves a
  redirect (`en:Sqlite` → page "SQLite"); two URL spellings of one page can
  therefore create two items. Canonical-URL-based dedup can be added when
  it proves to be a real problem.
- Fetching is sequential; fine at single-URL scale, revisit for bulk sync.
- The web and YouTube adapters each need a dependency decision
  (`trafilatura`, `yt-dlp`) in their own slices, but inherit the
  interface, registry, error type, and CLI surface decided here.
- No retry/backoff yet: a failed fetch leaves the item at `detected`, and
  rerunning `scrolls fetch` retries it.

## Proof

`src/scrolls/sources/wikipedia.py` + `scrolls fetch` in `cli.py`, with
transport-faked tests (`tests/test_wikipedia.py`, `tests/test_cli.py`) and
a live smoke test: `scrolls add https://en.wikipedia.org/wiki/SQLite`
then `scrolls fetch` stored 13k chars of extracted text, title, summary,
canonical URL, content hash, and provenance at stage `fetched`.
