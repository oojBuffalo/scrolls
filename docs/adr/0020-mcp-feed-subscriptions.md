# ADR 0020: The MCP server exposes feed subscriptions

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

ADR 0014 launched the MCP server with read tools plus `ingest_url`, and
ADR 0017 noted that follow/sync were not exposed yet. With feed sync
proven and HTTP-cached (ADR 0019), the gap was the only asymmetry left
between the interfaces: an MCP-connected agent could save a single URL
(`ingest_url`) but could not act on "follow this blog for me" or "check
my feeds" without shelling out.

## Decision

1. **Four tools, mirroring the CLI verbs:** `follow_feed(url)`,
   `unfollow_feed(ref)`, `list_feed_subscriptions()`, and
   `sync_feeds(subscription_id=None)`. Same engines, same payload
   shapes the CLI prints.
2. **Batch semantics are shared code, not parallel code.** The CLI's
   sync loop moved into `feeds.sync_many`, and both `scrolls sync` and
   `sync_feeds` call it: per-feed failures become `failed` results in
   the payload (one dead feed never kills the batch), unchanged feeds
   count as `unchanged`, and totals aggregate identically. The
   interfaces cannot drift.
3. **Error semantics follow the existing MCP conventions.** Reference
   errors raise — unknown `subscription_id` in `sync_feeds`, unknown
   ref in `unfollow_feed`, invalid/unfetchable feed in `follow_feed` —
   exactly like `get_scroll` on an unknown id; FastMCP turns them into
   tool errors. Batch-internal failures stay data, like `ingest_url`'s
   `error` key.
4. **Unfollow is included.** It is reversible (re-follow is one call;
   items the feed registered always stay), and subscription management
   is one capability — exposing follow without unfollow would strand
   agents with half of it.

## Consequences

- An MCP client can now run the full live-delta loop: follow → sync →
  (ingest/fetch via existing tools). The shell remains primary
  (ADR 0014); nothing moved, the surface grew.
- `_cmd_sync` shrank to resolve-subscriptions + print, and any future
  change to batch semantics lands in one place (`feeds.sync_many`).
- The tool count grows to eleven; the server instructions steer agents
  to the read tools first, so the addition does not dilute the
  retrieval-first design.

## Proof

`feeds.sync_many` + four tool functions in `src/scrolls/mcp_server.py`,
locked by `tests/test_mcp.py` (tool surface, follow/sync/unfollow round
trip, 304 `unchanged` through MCP, error cases) and the unchanged CLI
sync tests now running through `sync_many`; 420 passing.
