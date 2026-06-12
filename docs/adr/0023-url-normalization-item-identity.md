# ADR 0023: URL normalization for item identity

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

Items whose source has no URL-local id — every `web` and `pdf` item —
are identified by `source:` + a hash of the URL string (IDEAS.md §12).
That makes the URL's exact spelling the identity, so volatile
decorations mint duplicate items: feed entries decorated with rotating
`utm_*` params re-register the same post on every sync (ADR 0017's
known identity quirk, the first "next candidate" named by the README),
and the same article saved from a newsletter link and a plain link
becomes two items. The junk also propagated into stored URLs, scroll
frontmatter, and KB links.

## Decision

1. **Normalize at registration, store the normalized URL.**
   `normalize_url` (`src/scrolls/sources/urls.py`) runs at the two
   places URLs become items — `pipeline.register_url` (add/ingest/MCP
   `ingest_url`) and `feeds.sync_subscription` — before detection and
   hashing, and the normalized form is what gets stored: tracking
   params are content-free by definition, and keeping them out of
   scrolls and KB links is the point. The source's own
   `canonical_url` still lands at fetch, unmodified.
2. **Drop only what provably never changes a fetch.** Lowercased
   scheme/host, dropped default ports and fragments (never sent to the
   server), dropped `utm_*` plus a curated denylist of unambiguous
   click/campaign ids (`fbclid`, `gclid`, `mc_cid`, …), empty path →
   `/`. Everything else stays byte-identical — original param order
   and percent-encoding, no decode/re-encode round-trip. Ambiguous
   names (`ref` is a GitHub branch; `si`/`source` carry state on real
   sites) are kept: a false dedupe silently merges different pages,
   which is worse than the duplicate it prevents.
3. **Normalize the comparison sides in `related`.** Stored URLs are
   clean from now on, but links inside saved content carry whatever
   the author pasted; `_link_targets` and `_own_urls` compare raw and
   normalized forms so connections aren't silently lost in either
   direction.
4. **Not normalized: feed subscription URLs.** A feed URL is a
   user-supplied endpoint where any param may matter
   (`?format=rss`, …), and rewriting them would orphan existing
   subscription ids. `detect_source` also stays pure — the dropped
   params are never identity params, so detection results are
   unchanged either way.
5. **No migration.** Item ids are stored, never re-derived, so
   existing rows keep working untouched. A pre-existing library may
   hold a junk-URL item that a future clean re-add would duplicate;
   with libraries this young that is acceptable, and a `doctor`-style
   dedupe can repair it if it ever matters.

## Consequences

- Re-syncing a feed whose entry links rotate tracking junk reports
  `known` instead of growing the library (the quirk accepted in
  ADR 0017 is closed).
- `web`/`pdf` item ids are stable across the decorated and plain
  spellings of the same URL; scrolls, KB pages, and fetches see clean
  URLs.
- A URL whose meaningful params happen to use a denylisted name would
  be over-normalized; the denylist is deliberately short and
  unambiguous to keep that risk near zero.
- Hash-routed SPA URLs (`example.com/#/page`) collapse to one item —
  consistent with fetch, which never sees the fragment and extracts
  identical content for both.

## Proof

`normalize_url` in `src/scrolls/sources/urls.py`, unit-tested in
`tests/test_urls.py`; wiring proven by
`test_add_strips_tracking_params_before_identity` and
`test_add_stores_the_normalized_url` (`tests/test_cli.py`),
`test_sync_normalizes_tracking_params_out_of_entry_links`
(`tests/test_feeds.py`), and
`test_link_with_tracking_params_matches_the_clean_stored_url`
(`tests/test_related.py`); 463 passing.
