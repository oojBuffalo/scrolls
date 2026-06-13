# 0076: OPML import — bulk feed subscriptions, the `follow` sibling

Date: 2026-06-13
Status: accepted

## Context

The library has two ways to acquire content. **`import`** bulk-ingests a
local archive (Field Theory ADR 0009, Google Takeout ADR 0029, browser
bookmarks ADR 0030, Pocket ADR 0074) — each a thin parser over one shared
detect → dedupe → insert spine that produces **items**. **`follow`/`sync`**
(ADR 0017) is the live-delta path: `scrolls follow <url>` subscribes to one
RSS/Atom feed and `scrolls sync` registers its new entry URLs as items.

The gap is between them. Someone arriving from another RSS reader (Feedly,
Inoreader, NetNewsWire, Reeder, The Old Reader, Newsblur, …) does not have a
pile of *saved pages* — they have a curated list of *feeds*, often hundreds,
organized into folders. Every one of those readers exports that list as
**OPML**, the one universal feed-list interchange format. Scrolls can
subscribe to feeds one `follow` at a time, but a 200-feed migration through
200 manual `follow` calls (each making a network round-trip) is exactly the
bulk problem `import` exists to solve — only the unit is a *subscription*,
not an item.

OPML is a small XML format: an `<opml>` document whose `<body>` holds nested
`<outline>` elements. A feed outline carries an `xmlUrl` attribute (the feed
URL) and a `text`/`title` display label; a folder outline carries no
`xmlUrl` and only groups its children.

## Decision

`scrolls import opml <path>` (`src/scrolls/opml.py`) imports an OPML file as
feed **subscriptions** — the first import that does not produce items —
reusing the subscription machinery `follow` already owns:

- **It produces subscriptions, and the first `sync` produces items.** An
  OPML file lists feeds, not saved pages, so each feed outline becomes a row
  in the `subscriptions` table (`feeds.Subscription`,
  `feeds.insert_subscription`) with the same `make_subscription_id(feed_url)`
  `follow` mints — so an OPML import and a manual `follow` of the same feed
  collide on purpose (`INSERT OR IGNORE`, the ADR 0009 dedupe rule). This
  keeps the `import` = resumable spine, `sync` = live deltas split of
  IDEAS.md §13 intact: `import opml` lays the feed spine, `scrolls sync`
  discovers each feed's entries at stage `detected` through the same
  detect → dedupe path as `scrolls add`, and `fetch`/`classify`/`md` bring
  them in.
- **It is network-free, unlike `follow`.** `follow` fetches a feed once to
  validate it and capture its title (a typo'd URL is rejected, not stored).
  An OPML import does **not** — an export can hold hundreds of feeds, and the
  `xmlUrl` is *declared* to be a feed by the exporting reader, so a feed is
  trusted on import the way a bookmarks export's URLs are (ADR 0030). A dead
  or wrong feed surfaces on its **first sync**, failing only its own
  subscription, never the batch (`feeds.sync_many`, ADR 0017). Trusting the
  declared feed is also what makes the import the offline, resumable spine
  the other imports are.
- **No validators are stored.** A subscription enters with
  `last_synced_at`/`etag`/`last_modified` all `None`, exactly as `follow`
  leaves a fresh subscription — `follow` deliberately stores no validators so
  the first sync sees the feed's current entries (ADR 0019), and the same
  reasoning applies here.
- **The whole outline tree is walked.** `root.iter("outline")` visits feeds
  nested in folders and top-level feeds alike; any outline with a non-empty
  `xmlUrl` is a feed, and folder outlines (no `xmlUrl`) are skipped. Folder
  grouping is display metadata in the source reader and is **dropped** —
  subscriptions carry no tags, and a feed's entries get their own tags from
  detection at sync time, so there is nowhere honest to put the folder name
  (unlike bookmarks, whose items *do* carry tags, ADR 0030).
- **The document is parsed from bytes.** Every reader writes an XML
  declaration with an encoding (`<?xml version="1.0" encoding="UTF-8"?>`),
  and `ElementTree.fromstring` *rejects* an encoding-declared `str`; bytes
  input is both the robust path and the one that honors a non-UTF-8
  declaration. (Feed parsing reads `response.text`, ADR 0017, but here the
  importer owns the read.)
- **The label is `text` then `title`.** `text` is the OPML-required outline
  display attribute; `title` is the optional legacy one, equal to `text` in
  practice. The subscription title is cosmetic — `sync` names each *entry*
  from the feed itself, not from this label — so either suffices; `text`
  first, `title` fallback. Attribute lookup is case-insensitive (the spec
  spells it `xmlUrl`, but some exporters lowercase it).
- **Only `http`/`https` feeds import; noise is counted, never fatal.** A
  non-http feed (`file:`, `feed:`) is reported in `ignored.not_http` and
  skipped, a feed URL repeated within the file collapses to one subscription
  (`repeats`), and a well-formed OPML with no feeds imports nothing without
  error — content-level emptiness is lenient, document-level breakage is
  strict (the ADR 0029/0074 posture). Only a missing/unreadable path,
  malformed XML, or a non-`<opml>` root (an RSS feed passed by mistake)
  raises `ImportSourceError`.

## Consequences

- A reader migration — the common on-ramp for someone with a real RSS habit —
  becomes one offline command: `scrolls import opml subscriptions.opml`, then
  `scrolls sync` to pull the deltas. The `import` namespace now spans both
  acquisition units: archives that become **items** (bookmarks/Pocket/Takeout
  /Field Theory) and a feed list that becomes **subscriptions** — the bridge
  between the `import` family and the `follow`/`sync` family, sharing the
  subscription id with `follow` so the two acquisition paths dedupe.
- Importing without fetching is the deliberate trade: a fast, resumable,
  offline import (hundreds of feeds in milliseconds) at the cost of not
  catching a dead feed until its first sync. This matches every other bulk
  import — none validate their spine on the way in — and `sync`'s
  per-subscription failure isolation (ADR 0017) already handles the dead-feed
  case gracefully, so the cost is paid where it belongs.
- The `feed:` pseudo-scheme some older exporters emit (`feed://host/…`,
  `feed:https://host/…`) is ambiguous between http and https for the bare
  `feed://` form, so it is counted under `ignored.not_http` rather than
  guessed at. Unwrapping the unambiguous `feed:https://…` prefix form, and
  carrying folder names as a future feed-level default tag applied to
  discovered entries, are deferred — both are additive and revisable.
- The importer is OPML-shaped, not reader-specific: any reader's export
  parses through the same `xmlUrl`-bearing-outline walk, since OPML is the
  shared format. Reader-specific extensions (Newsblur's per-feed metadata,
  category attributes) are ignored, not parsed.
- `export`'s inverse — writing the library's subscriptions back out as OPML
  so Scrolls can hand a reader its feed list — is the obvious symmetric next
  step, deferred until there is a concrete consumer.
