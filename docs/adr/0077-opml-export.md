# 0077: `scrolls export opml` — feed subscriptions back out, the import inverse

Date: 2026-06-13
Status: accepted

## Context

ADR 0076 added `scrolls import opml`: bring a curated feed list from any RSS
reader into Scrolls as subscriptions. The import is one half of a migration.
The other half is leaving — or backing up, or syncing a phone reader from the
same list. Someone who manages their feeds in Scrolls (`follow`, `unfollow`,
the imported set) has no way to get that list *out* in the one format every
reader understands. A migration tool that only imports is a roach motel.

The library already owns everything needed: `feeds.list_subscriptions` returns
every subscription, and `src/scrolls/opml.py` already owns the OPML format in
one direction. Serializing back to OPML is the natural, symmetric other half,
and it closes the round-trip that makes the import trustworthy — you can
verify what Scrolls holds by exporting it and reading it in the reader you
came from.

Scrolls has had no `export` command until now. The closest precedents are
`scrolls context` (emits a Markdown bundle — "the artifact is the output")
and the scroll/KB files (the durable artifacts themselves).

## Decision

`scrolls export opml` writes the library's feed subscriptions as an OPML 2.0
document to **stdout** (`opml.dump_opml_export`, `cli._cmd_export_opml`):

- **A new top-level `export` command, with `opml` as its first subcommand**,
  mirroring `import`'s shape (`import opml` ↔ `export opml`). The parent
  namespace is deliberately introduced now so the obvious future exports
  (a JSON dump of items, a single Markdown bundle of scrolls, an
  agent-context pack) have a home that reads symmetrically with `import`,
  rather than bolting export onto `follow` or inventing a one-off verb. One
  subcommand today is thin, but the namespace is the honest place for it and
  is cheap to extend.
- **The OPML document is the artifact, so it prints raw on stdout** — the
  `scrolls context` exception to the JSON-on-stdout rule (ADR's interface
  conventions). `scrolls export opml > feeds.opml` is the natural use, and a
  pipe (`… | curl …`) works without a temp file. There is no path argument
  and nothing is written to the filesystem: a pure stdout emitter has no
  overwrite, permission, or path-validation surface, and the shell already
  owns redirection. Errors, were any to arise, stay JSON on stderr.
- **The export is flat.** Subscriptions carry no folder grouping — the import
  dropped it because a subscription has nowhere to store a tag (ADR 0076) — so
  the export honestly emits a flat `<body>` rather than inventing a hierarchy.
  Each subscription is one `<outline type="rss" text=… title=… xmlUrl=…>`, in
  `list_subscriptions` order (added-at, then id). `type="rss"` is the
  conventional feed-outline marker readers expect; `text` and `title` both
  carry the display label (`text` is the OPML-required one, `title` the legacy
  twin, set equal as every reader does), and a subscription with no title
  labels itself by its feed URL (OPML requires a non-empty `text`).
- **It serializes through ElementTree, so attribute values are XML-escaped.**
  A feed URL with `&` (common in `feeds/videos.xml?channel_id=…&…`) is written
  `&amp;` and re-parses intact, so an export → import cycle reproduces the
  same feeds. The document carries an explicit
  `<?xml version="1.0" encoding="UTF-8"?>` declaration (the importer reads
  bytes precisely so a declared encoding is honored, ADR 0076), is indented
  for human readability, and an empty library produces a valid empty OPML, not
  an error.
- **Round-trip is the contract.** `dump_opml_export` then `load_opml_export`
  returns the same feed URLs and titles in the same order
  (`test_export_then_import_round_trips`, `test_export_opml_round_trips_through_import`):
  the export is exactly what the import would skip as already-followed, which
  is the proof the two halves agree.

## Consequences

- The OPML round-trip is complete: a reader's feed list flows into Scrolls
  (`import opml`), is managed there (`follow`/`unfollow`/`sync`), and flows
  back out to any reader (`export opml`) — Scrolls is a way-station on a feed
  list's life, not a sink. Backup and reader-sync fall out for free.
- The `export` namespace exists, mirroring `import`. Adding `export json`
  (the library's items as a portable dump — the reserved `items/` directory's
  eventual job, see `docs/architecture.md`) or `export scrolls` (a single
  Markdown bundle) is now an additive subcommand, not a structural decision.
- Subscriptions are the only thing exported today because they are the only
  library state with a *standard* interchange format whose importer already
  exists. Items have no single universal export format (their durable form is
  the Markdown scrolls), so item export waits for a concrete need and target
  format rather than guessing one.
- The flat export loses nothing Scrolls holds (it never held folders), but it
  also will not reproduce the folder hierarchy a user had in their *original*
  reader — that information was dropped at import and is not recoverable. If
  feed-level grouping is ever added to subscriptions, both the import (folder →
  group) and the export (group → folder) gain the obvious symmetric handling.
