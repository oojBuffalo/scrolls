# ADR 0017: Sync is feed subscriptions, not per-platform sync commands

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

IDEAS.md §13 distinguishes `import` (bulk local archive), `add` (one-off
URL), and `sync` (live platform delta updates); only the first two
existed. The §5 sketch imagined per-platform sync commands
(`scrolls sync x --bookmarks`, `scrolls sync youtube --playlist <url>`),
but each implies platform-specific listing code, and the most-wanted
platform (X) needs authenticated sessions the project has deliberately
avoided (ADR 0009).

Meanwhile every keyless delta source the library already handles is
reachable as an RSS 2.0/Atom feed: YouTube channels and playlists have
public Atom feeds, blogs and news sites publish RSS/Atom, arXiv exposes
per-category feeds, GitHub serves Atom for releases/commits/tags.

## Decision

1. **One sync mechanism: followed feeds.** `scrolls follow <url>`
   registers a feed subscription; `scrolls sync [id]` polls each feed
   and registers new entry URLs as items at stage `detected`, through
   exactly the `detect_source` + `make_item_id` + `INSERT OR IGNORE`
   path `scrolls add` uses. Sync only *discovers URLs* — the existing
   fetch adapters do all enrichment, so a YouTube feed entry becomes a
   `youtube` item and a blog entry a `web` item. No per-platform sync
   code exists or is planned; a platform that needs more than a feed
   (native X bookmark sync) would join as a new subscription kind, not
   a new mechanism.
2. **Sync registers; it does not fetch.** New entries land at
   `detected`, composing with the idempotent pipeline:
   `scrolls sync && scrolls fetch && scrolls classify && scrolls md`.
   Feeds can surface many items at once; fetching inline would make
   sync slow and failure-prone for no benefit the pipeline doesn't
   already provide.
3. **Subscriptions live in SQLite** (`subscriptions` table, schema v4):
   IDEAS.md §3 explicitly assigns sync state to the index, and
   subscriptions are command-managed state, not hand-edited settings —
   `config.toml` stays for settings (ADR 0016). Subscription ids are 12
   hex chars of the feed URL's SHA-256, mirroring item URL-hash ids.
4. **stdlib parsing, no feedparser.** RSS 2.0 + Atom cover the real
   feeds above and ElementTree parses both (the arxiv adapter's
   precedent); a lenient kitchen-sink dependency doesn't pay its way
   (ADR 0001). Anything else is an honest `FeedError`.
5. **`follow` validates by fetching once.** Unlike `add`, there is no
   later adapter step that would surface a typo'd feed URL — it would
   just fail every future sync. One GET at follow time rejects bad
   URLs immediately, captures the feed's title, and stores nothing on
   failure. YouTube playlist/channel-id page URLs map to their public
   feeds purely syntactically (`@handle` URLs cannot be resolved
   keylessly and fail follow's validation honestly).
6. **Batch semantics match the rest of the CLI.** Known entries count
   as `known` (the id dedupe working), non-http entry links are
   `skipped`, one dead feed fails its subscription but never the
   batch, and `sync` exits 1 if any subscription failed.

## Consequences

- Live deltas now work for YouTube channels/playlists, blogs, arXiv
  categories, and GitHub release feeds with zero new dependencies and
  no credentials.
- Items registered by sync are indistinguishable from `scrolls add`
  output (by design); removing a subscription keeps the items it
  registered — the feed is a discovery channel, not an owner.
- Known identity quirks, accepted: GitHub release-feed entries all
  detect as the same `github:owner/repo` item, so such a feed
  effectively registers the repo once rather than one item per
  release; `web` feed entries whose links carry volatile tracking
  params would hash to different ids and re-register.
- `scrolls sync` makes one uncached GET per feed per run; HTTP
  caching (ETag/Last-Modified columns) can join the subscriptions
  table if polling ever gets frequent enough to matter.
- The MCP server does not expose follow/sync yet; the shell interface
  remains primary (ADR 0014).

## Proof

`src/scrolls/feeds.py` + schema v4 in `src/scrolls/db.py` + CLI wiring,
all offline-tested (`tests/test_feeds.py`, feed CLI tests in
`tests/test_cli.py`, migration tests in `tests/test_db.py`; 383
passing), plus a live localhost capture in `docs/cli.md`'s reproduction
appendix: follow → sync → sync-again shows 2 new, then 2 known, and a
404 feed is rejected at follow time.
