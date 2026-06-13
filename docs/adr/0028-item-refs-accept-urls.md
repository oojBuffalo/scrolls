# ADR 0028: every item-id argument accepts the item's URL

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

For sources without a source-local id (`web`, `pdf`), item ids are
`source:` + a URL hash — opaque strings nobody remembers. An agent that
saved `https://example.com/post` had to run `list` or `detect` first
just to learn the hash before it could `show`, `set`, or re-`fetch` the
item. ADR 0027 gave `scrolls rm` URL handles ("the URL that saved an
item removes it"); the moment that shipped, `rm` being the *only*
id-taking command with URL handles was an inconsistency, not a feature.
`unfollow` had already set the same precedent for feed URLs.

## Decision

1. **`resolve_item_id` moves to `pipeline.py`** — it composes the same
   normalize → detect → mint chain as `register_url`, and the pipeline
   module is where the CLI and MCP server share item-lifecycle logic
   (ADR 0014). `remove.py` keeps only removal.
2. **One lookup helper in the CLI.** `_find_item(paths, ref)` resolves
   and fetches; `show`, `fetch`, `classify`, `md`, `media`, `set`,
   `related`, and `rm` all use it (for `related`, resolution feeds the
   engine's own existence check). Behavior for plain ids is unchanged —
   anything without `://` passes through verbatim.
3. **Misses name the resolved id.** A URL that matches nothing errors
   with `no such item: web:<hash> (from <url>)`, keeping the
   resolution visible instead of presenting a hash the user never saw.
4. **Subscriptions stay a separate namespace.** `sync <id>` and
   `unfollow <id>` take subscription ids (and `unfollow` its feed URL),
   not item refs — a feed URL is not an item.
5. **MCP keeps plain ids for now.** `get_scroll`/`get_related_scrolls`
   could accept URL refs through the same resolver; deferred until an
   MCP client actually needs it, to keep this slice CLI-scoped.

## Consequences

- The id is an implementation detail agents can ignore end-to-end:
  save by URL, inspect by URL, classify by URL, remove by URL. Hash
  ids remain canonical in stored data and outputs.
- A URL ref to a never-saved resource is indistinguishable from a typo
  of a saved one — both report the minted id. The `(from …)` suffix
  and `scrolls detect` make the resolution inspectable.
- `fetch <url>` looks up an *existing* item; it does not register a
  new one (that is `add`/`ingest`). The error message for an unsaved
  URL makes the distinction visible.

## Proof

`pipeline.resolve_item_id` (`tests/test_pipeline.py`), the shared CLI
lookup exercised per command in `tests/test_cli.py`
(`test_show_accepts_item_url`, `test_fetch_accepts_item_url`,
`test_set_accepts_item_url`, `test_related_accepts_item_url`,
`test_md_accepts_item_url`,
`test_show_unknown_url_reports_the_resolved_id`). 558 passing.
