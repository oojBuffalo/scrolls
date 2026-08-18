# 0109: Wikipedia reading lists sync — a collection that indexes rather than captures

Date: 2026-08-18

Status: accepted

Relates to: [0002](0002-first-fetch-adapter-wikipedia.md), [0108](0108-x-bookmarks-native-sync.md), [0030](0030-browser-bookmarks-import.md)

## Context

Wikipedia was the project's first fetch adapter (ADR 0002) and, until now, its
narrowest on-ramp: `fetch_item` took one article at a time, so bringing in a
few hundred saved articles meant running `scrolls add` a few hundred times.

**Reading lists, not the watchlist.** What the user taps "Save" on in the
Wikipedia app or while signed in on the web, synced to the account and filed
into named lists. A watchlist means "notify me when this changes" — a
different intent, and not a saved collection.

**The API was verified before anything was built**, as the issue required.
`action=paraminfo` on live en.wikipedia.org confirms both modules exist:
`meta=readinglists` and `list=readinglistentries`, from the ReadingLists
extension, each paginating on its own continue token.

## Decision

`scrolls sync wikipedia --reading-lists` pulls every article across every
reading list, authenticated by the session already in the user's browser.

**Verified against live Wikipedia on 2026-08-18.** A full run over a Brave
session read 2 lists and 586 entries across 6 pages with no failures,
producing 566 distinct articles, and re-synced to 566 skips. Every item
carried a URL, a title and a real save time.

### A collection is an index, not a capture

This is the substantive difference from ADR 0108, and it was settled by the
payload rather than by preference. A reading-list entry carries `project`,
`title`, `listId` and timestamps — **no article text at all**.

- **Items enter at stage `detected`**, and the ADR 0002 fetch adapter captures
  them on the next `scrolls fetch`. Claiming stage `fetched` for a row holding
  no prose would be exactly the fabrication custody exists to prevent.
- **So the third on-ramp shape splits in two.** X bookmarks are
  *capture-at-pull*: the enumerating response carries the artifact. Reading
  lists are *enumerate-only*, which lands on the importer side of the ADR 0009
  boundary and reuses the Pocket and browser-bookmark path unchanged.
- **The consequence is a feature, not a shortfall.** Because `wikipedia` is in
  `FETCH_ADAPTERS`, `scrolls verify` re-captures a pulled article and reports
  drift — the thing ADR 0108 had to concede X cannot do.

### Authentication is CentralAuth's, not the local wiki's

- **`centralauth_User` and `centralauth_Session` are the pair that works**, on
  the `.wikipedia.org` domain. This is not what you would guess: a valid
  per-wiki `enwikiSession` alone answers `notloggedin`, because reading lists
  are a global feature, so the global session is the one that counts. Both
  facts were established by probing live, not assumed.
- **The cookie machinery is now shared.** Finding browsers, decrypting Chrome's
  keychain-backed values and reading Firefox's plaintext ones moved out of
  `x_session.py` into `browser_cookies.py`, parameterized by a `CookieSpec` of
  hosts and cookie names. The second consumer is the right time to generalize;
  X keeps its own session type on top and its behaviour is unchanged.
- **`SCROLLS_WIKIPEDIA_USER` / `SCROLLS_WIKIPEDIA_SESSION` bypass the browser**,
  matching the X env-var escape hatch, and are the only path for a browser
  Scrolls cannot read.

### What is captured, and what is honestly missing

- **Identity is minted by URL, not re-derived.** The entry's project and title
  build the article URL, which goes through the same `detect_source` and
  `normalize_url` that `scrolls add` uses. A pulled article and an added one
  converge on `wikipedia:<lang>:<Title>` by construction rather than by two
  rules that happen to agree. This matters because the API returns display
  titles with spaces while URLs use underscores.
- **`saved_at` is Wikipedia's own `created` timestamp** — when the user saved
  the article. Unlike X, no fallback to sync time is needed, and the article's
  own dates stay with `fetch`, never here.
- **A named list becomes a tag; the default list does not.** The default list
  is Wikipedia's unnamed catch-all — where an article goes when it was filed
  nowhere — so it is the absence of curation, not a name to record.
- **An article in two lists is one article with both tags.** Wikipedia keeps a
  saved article in the default list *and* in whatever list it was filed into,
  so one article legitimately arrives as several entries. They are collapsed
  by item id before the insert, unioning tags and keeping the earliest save,
  the rule ADR 0030 already set for a URL saved twice.
- **Non-Wikipedia projects are reported, never guessed.** Reading lists span
  all of Wikimedia; a Commons or Wiktionary entry has no adapter here, so it
  is counted as a failure with its project named rather than minted into an
  item this library could not fetch.

## Consequences

- **The collapse rule is load-bearing, and the tests could not have found it.**
  The first live run imported 566 items of which exactly one carried its list
  tag: the default-list copy of each article landed first and `INSERT OR
  IGNORE` discarded the tagged one. Fixture tests passed throughout, because
  the duplicate-membership shape was not one anybody thought to write down.
  It took real data to see, which is the argument for verifying an on-ramp
  against a live account rather than against a reading of the docs.
- **The API is flagged `internal` by MediaWiki**, so it carries no stability
  promise despite being documented at Extension:ReadingLists. This on-ramp's
  volatility is that flag, the way ADR 0108's is a rotating query id. If the
  extension is withdrawn, the failure says so by name rather than reporting an
  empty collection — the one wrong answer available here.
- **A pull is an index, so the library grows before it captures.** 566 articles
  arrive as `reference`-tier items and only become `full` custody as `scrolls
  fetch` works through them. `scrolls doctor` reports this honestly rather
  than scoring an un-fetched collection as complete.
- **Deferred: other Wikimedia projects.** Wiktionary, Commons and Wikisource
  entries in a reading list are reported and skipped. Claiming them needs
  their own adapters, which is a separate decision.
- **Deferred: writing back.** The ReadingLists API can create and delete
  entries. Scrolls reads; a custody tool that edits the user's Wikipedia
  account is a much larger promise.
