# ADR 0019: Feed polling uses HTTP conditional GETs

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

ADR 0017 made `scrolls sync` poll every followed feed with one full GET
per run and noted that ETag/Last-Modified columns "can join the
subscriptions table if polling ever gets frequent enough to matter."
Sync exists precisely for frequent polling — a cron'd
`scrolls sync && scrolls fetch && scrolls classify && scrolls md` is
the intended shape — and feeds change far less often than they are
polled. Conditional requests are also long-standing feed-reader
etiquette: well-behaved pollers send `If-None-Match`/`If-Modified-Since`
and publishers expect it (some throttle clients that never do).

## Decision

1. **Validators live on the subscription** (`etag`, `last_modified`
   columns; schema v5). Sync state belongs to the SQLite index
   (IDEAS.md §3), and the validators are per-feed sync state exactly
   like `last_synced_at`.
2. **Only a successful full sync stores validators.** After a 200
   response is parsed and its entries registered, the response's own
   `ETag`/`Last-Modified` replace the stored pair — including replacing
   it with nothing when the server sent none, so the stored pair always
   describes the most recent full response. A failed fetch or parse
   stores nothing.
3. **`follow` never stores validators.** Follow validates by fetching
   but deliberately registers no entries (ADR 0017); if it seeded the
   cache, the first sync would receive 304 and the feed's current
   entries would never be registered. The first sync after follow is
   always a full response.
4. **304 is a distinct, honest result.** An unchanged feed reports
   `"status": "unchanged"` with zero counts instead of pretending its
   entries were re-checked (`known` stays 0 — nothing was parsed). The
   poll still succeeded, so `last_synced_at` is stamped and the run
   exits 0. The CLI total gains an `unchanged` count next to `failed`.
5. **The conditional GET lives in the shared transport**
   (`http.get_conditional`), returning a small `ConditionalText` result
   — text plus response validators, or `not_modified`. urllib surfaces
   304 as an `HTTPError`; only the transport knows that. Feeds keep an
   injectable fetcher, so feed tests stay offline; the urllib glue
   itself is tested against a real localhost server
   (`tests/test_http.py`).

## Consequences

- A cron'd sync against N unchanged feeds now costs N empty 304s
  instead of N full downloads and parses; feeds without validators
  behave exactly as before.
- Stored validators can go stale only in the harmless direction: the
  next poll gets a full response. A server that answers 304
  incorrectly would suppress new entries until its validators change —
  that is the server lying, and `scrolls sync <id>` after `touch`-ing
  nothing can't help; `unfollow`/`follow` resets the cache by design
  (follow stores no validators).
- `scrolls follow`'s subscription listing now shows `etag` and
  `last_modified`, which doubles as a way to see whether a feed's
  server supports conditional requests at all.
- 304 handling means sync no longer proves the stored entries still
  appear in the feed on every run — it never needed to; ids are the
  dedupe, not the feed contents.

## Proof

`http.get_conditional` + schema v5 + `feeds.store_validators` and the
`unchanged` sync path, tested offline (`tests/test_feeds.py`,
`tests/test_db.py` migration v4→v5, CLI tests) plus against a real
localhost HTTP server (`tests/test_http.py`); 410 passing. A live
capture in `docs/cli.md` shows sync → 304 `unchanged` → `touch` → full
response with `known` entries, against `python3 -m http.server`, which
honors `If-Modified-Since` natively.
