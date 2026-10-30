# 0118: Saves removed upstream are recorded, never acted on

Date: 2026-10-29

Status: accepted

Settles issue #24 and the deferral in [0113](0113-collection-on-ramp-contract.md) §5.

## Context

ADR 0113 kept a save the user removes upstream in the library, and deferred
recording the removal: "neither route can do it today without walking the
full collection on every sync."

That premise no longer held. Both routes already walk the whole collection on
every sync unless `--limit` is passed; the live X pull walked 482 bookmarks in
6 pages in 10s (H433). What was missing was not the walk but two facts the walk
threw away:

- **What it saw.** A bookmark whose post was deleted is a tombstone entry the
  parser skipped silently. Comparing on readable items alone would call a
  still-bookmarked deleted post "unsaved", which is rot, not removal.
- **Whether it finished.** The X walk ended on the first page with no
  *readable* items, so a page of tombstones could end it early. The reading-list
  walk stopped silently at its page cap. Neither said which.

## Decision

**A complete walk records membership on the custody ledger; anything less
records nothing.**

- **The walk reports `seen` and `complete`.** `seen` is the item id of every
  entry, readable or not. `unidentified` counts entries it could not name. A
  walk is `complete` only when it ended on the service's own end signal (an
  empty page or no cursor for X, no `rlecontinue` for MediaWiki), unlimited and
  unbroken. An empty page now means no entries at all.
- **A membership axis on the ledger.** Two statuses beside the verify verdicts
  and the conflict axis: `saved_upstream` and `unsaved_upstream`, with the
  collection key (`x/bookmarks`) as `detail`. Disjoint from the drift posture:
  an un-bookmarked post is still held and its source has not moved.
- **The comparison.** A held member the walk did not see gets
  `unsaved_upstream`. A held item the walk saw gets `saved_upstream` on its
  first sighting or its return (reported as `resaved`). A removal already
  recorded is counted (`still_unsaved`), not recorded again.
- **Who is a member.** An item whose latest membership event is
  `saved_upstream`, or, before the ledger holds any for it, an item whose
  `provenance.adapter` names the collection's on-ramp (`x-bookmarks`). So the
  live library's existing bookmarks are compared from the first walk. A
  fetched Wikipedia article's provenance cannot say it came from a list, so
  reading lists start comparing from their first complete walk.
- **Report-only.** No item, scroll or capture is touched, and an item no
  longer held gets no event. The sync report carries an always-present
  `upstream` block; `compared: false` names the reason.

## Consequences

- **"What did I stop saving?" has an answer**: `scrolls history <id> --status
  unsaved_upstream`, and the sync report's `upstream.unsaved`.
- **The ledger stays the one record.** No new table or sidecar file; the
  events travel with `export events` and bundles like every other ledger row.
- **Conservative by design.** One unnameable entry blocks a comparison
  rather than risking a false removal. A non-Wikipedia reading-list entry
  (Commons, Wiktionary) does not block it, since it can never be held.
- **Not verified live yet.** The fixtures cover tombstones, early ends,
  limits and the provenance bootstrap; a live pull on a copy of the library
  is the remaining proof.
- **Deferred:** surfacing removals in `doctor`/`status`, and an MCP read of
  them.

Tests: `tests/test_unsaved_upstream.py`.
