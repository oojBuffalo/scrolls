# ADR 0113: The collection on-ramp contract

Date: 2026-10-03

Status: accepted

Settles: issue #2. Generalizes: [0108](0108-x-bookmarks-native-sync.md),
[0109](0109-wikipedia-reading-lists-collection.md).

## Context

Scrolls had three on-ramps: a URL (`add`), a file someone already exported
(`import`), and feed deltas (`follow`/`sync`). None of them could copy a
user's saved collection out of the service where it lives. Issue #2 named
the missing **fourth on-ramp** and asked for a contract *before* the second
implementation, so one adapter would not bake in a shape that does not
generalize.

The order ran the other way. X bookmarks (0108) and Wikipedia reading lists
(0109) both shipped and were verified against the live services first. The
contract was settled in practice, one source at a time, and lived only in
two near-identical CLI functions with per-source flags (`--bookmarks`,
`--reading-lists`). Nothing let a source *declare* what it offers.

That order turned out to be useful. This ADR does not guess at a contract.
It writes down what two real collections, with different custody shapes,
proved. It also adds the declaration both were missing.

## Decision

### 1. Surface: `sync`, with `--collection`

**A saved collection is pulled with
`scrolls sync <source> --collection <name>`.** `sync` already means "bring
the library up to date with a thing you follow", and a collection you keep
adding to is that. The refactor #2 warned of was smaller than feared:
dispatch on the flag, and the feed path is untouched.

- **Discovery:** `scrolls sync --list-collections` lists every declared
  collection. `scrolls sync <source> --list-collections` lists one source's.
- **Aliases:** `--bookmarks` and `--reading-lists` stay as spellings of
  `--collection bookmarks` and `--collection reading-lists`. Naming two at
  once is refused.
- **A collection source is not a feed:** `scrolls sync x` without a
  collection flag now names the command that pulls it. It used to answer
  "no such subscription: x".

### 2. Declaration: one registry, honest absence

**Every collection is a `SavedCollection` in `src/scrolls/saved_collections.py`.**
It declares the facts a reader needs before running it:

| Field | Meaning | X bookmarks | Wikipedia reading lists |
|---|---|---|---|
| `shape` | Does the listing carry the artifact? | `capture-at-pull` | `enumerate-only` |
| `entry_stage` | Stage pulled items enter at | `fetched` | `detected` |
| `saved_at` | Who says when you saved it | `sync-time` | `service` |
| `routes` | Credential routes, browser first | `browser`, `oauth` | `browser` |
| `adr` | Where its decisions live | 0108 | 0109 |

Its `pull(options, pulled_at)` returns a `CollectionPull`: items, failures,
pages, session origin, a mid-walk error, and source-specific `extra` facts
for the report. The CLI runs **one** loop over that result for every
collection.

**Having no collection is a first-class answer, not an error.**
`collections_for("youtube")` is an empty tuple, and
`--list-collections` prints an empty list and exits 0. Asking to pull one
from such a source fails, but the message names every collection that does
exist. Most sources are things you point at, not places you keep things.

### 3. Credentials: the browser session first, always

**The logged-in browser session is the default route for every collection.**
This is the repository rule in `CLAUDE.md`, and a test pins `routes[0] ==
"browser"` for every declaration.

- **Reading the session:** through `browser_cookies.py` with a per-service
  `CookieSpec`. No second cookie reader.
- **Env-var cookies** (`SCROLLS_X_AUTH_TOKEN`, `SCROLLS_WIKIPEDIA_SESSION`,
  …) are the same session, pasted, so they count as the primary route.
- **Stored credentials are opt-in** via `--auth oauth`, and only where the
  collection declares that route. Asking for a route a collection does not
  offer is refused and names the routes it does offer.
- **A start-up failure fails the whole run** with one stderr envelope that
  says what to set or do. This is the `LLMAuthError` posture #2 asked for: a
  partial import that silently dropped the unauthorized half would be worse
  than nothing. Each `pull` turns its service's errors into
  `CollectionUnavailable` so the CLI needs no per-source exception list.

This supersedes #2's starting assumption that credentials would be
per-source tokens in env or `config.toml`. Both shipped collections showed
the session route works without any stored secret.

### 4. Custody semantics

- **Stage follows shape.** A capture-at-pull listing carries the post
  itself, so its items enter at `fetched`. An enumerate-only listing names
  an article without its text, so its items enter at `detected` and the
  source's fetch adapter captures them. Claiming `fetched` for a row with no
  prose is the fabrication vision §2.8 forbids.
- **Identity converges with `add`.** A pulled item has the same id
  `scrolls add <url>` would mint, either by running the built URL through
  `detect_source` (0109) or by keeping the id scheme `add` uses (0108).
- **`saved_at` is the service's "when you saved it"** where one exists,
  never `published_at`. This matches the importer precedent (Field Theory
  `bookmarkedAt`, Pocket `time_added`, bookmarks `ADD_DATE`). Where none
  exists, the pull time stands in and `provenance.saved_at_source` says so.
- **Provenance names the route.** `provenance.extraction_method` records
  which route reached the item, so two routes to the same item still dedupe.

### 5. Re-runs and upstream removal

**Re-runs are `INSERT OR IGNORE`** (ADR 0009). A re-sync skips what is held,
never overwrites a user edit, and reports `skipped` alongside `imported`.

**A save the user removes upstream stays in the library.** Custody holds
what you deliberately saved. Un-bookmarking a post does not retract that it
was saved, and silently deleting it would be the loss this tool exists to
prevent. Recording the removal, as an "unsaved upstream" custody event from
a comparing re-sync, is **deferred**. Neither route can do it today without
walking the full collection on every sync.

### 6. Volume and rate limits

- **Serial, paged walks.** One request at a time, following the service's
  own continuation token. The walk ends on the service's own end signal (an
  empty page for X, a missing `rlecontinue` for MediaWiki), never on a guess.
- **Backoff where the service rate-limits.** X retries a 429 with capped
  exponential backoff and honors `Retry-After`. MediaWiki asks clients for
  serial requests, which the walk already does; its collections are a few
  pages, so it has no retry loop.
- **A mid-walk failure keeps what was collected.** The error rides on the
  result and the exit code is non-zero. Nothing collected plus a failure is
  a plain failure on stderr.
- **`--limit`** stops after that many saved items, for a first look at a
  large collection.

## Adding a collection

1. Write the walk in the source's own module, returning items, failures,
   pages and an optional error.
2. Read the session through `browser_cookies.py` with a `CookieSpec`.
3. Add a `SavedCollection` to `COLLECTIONS`, with a `pull` that turns the
   service's start-up errors into `CollectionUnavailable`.
4. Pick `shape`, `entry_stage` and `saved_at` from what the payload actually
   carries, not from what would be convenient.
5. Test end to end through `main(["sync", <source>, "--collection", …])`
   with only the network faked, and record the source's decisions in its
   own ADR.

## Consequences

- **Adding a collection is now a declaration**, not a new CLI branch and a
  new flag.
- **The declaration is introspectable.** An agent or a user can ask what a
  source offers before reaching for credentials.
- **The JSON report gains `source` and `collection`.** All other fields are
  unchanged, and the per-source `extra` facts (`account`, `lists`) still
  appear for Wikipedia.
- **Deferred:** the "unsaved upstream" event (§5), an MCP tool for
  collection pulls (reading a browser session is an interactive, local act),
  and the further collections #3 catalogued (GitHub stars, YouTube
  playlists, Mastodon bookmarks). Each should arrive as one more
  declaration.
