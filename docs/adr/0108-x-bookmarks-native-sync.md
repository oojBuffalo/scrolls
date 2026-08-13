# 0108: X bookmarks sync natively over the browser session

Date: 2026-08-13

Status: accepted

Supersedes: [0009](0009-fieldtheory-import.md)

## Context

ADR 0009 routed X bookmarks through `scrolls import fieldtheory` and closed
with the follow-up: *"Native `scrolls sync x --bookmarks` remains open as a
later, separate decision."* This is that decision.

**The deferral rested on a false premise.** 0009 deferred native sync because
"native X sync needs auth/session plumbing." That reading hardened over time
into the belief that X now requires a paid developer account — X discontinued
its free tier for new signups on 2026-02-06 and bookmarks are billed as
pay-per-use "Owned Reads". All of that is true of X's *official* API, and none
of it applies here, because Field Theory never used the official API.

**Reading the source settled it.** `afar1/fieldtheory-cli` (MIT) authenticates
with the two session cookies already in the user's browser and calls X's
*internal* GraphQL endpoint — the same request x.com makes when you open your
own bookmarks page. No developer account, no cost.

**Why the gap survived a year.** `docs/inspiration/README.md` records Field
Theory's reference checkout as *"none — lineage travels via `scrolls import
fieldtheory`"*. The lineage was routed through a **data** import, so the
source was never read and its mechanism never surfaced. That is a lesson about
inspiration sourcing, not just about X: a data import carries the artifacts,
never the technique.

## Decision

`scrolls sync x --bookmarks` pulls the collection directly from X.

### Authentication: the browser's own session

- **Two cookies do the work.** `auth_token` is the session; `ct0` is the CSRF
  token, echoed back as `x-csrf-token`. X's web client sends a bearer token
  too, but it ships in x.com's JavaScript and is identical for every visitor —
  it is a client identifier, **not a secret**, and is checked in as such.
- **Every installed browser is searched.** Chrome, Brave, Arc, Edge, Vivaldi,
  Chromium and Firefox, and every profile within each. Chromium forks share
  Chrome's scheme — `PBKDF2(keychain_password, 'saltysalt', 1003, 16, sha1)`
  then AES-128-CBC under a sixteen-space IV — but each encrypts under its own
  Safe Storage keychain entry. Firefox stores cookie values in the clear, so
  that path never prompts for Keychain access.
- **Both cookies must come from the same host.** An `x.com` session paired
  with a stale `twitter.com` CSRF token is a 403, not a session.
- **Nothing is stored and nothing is written.** The session is read live on
  each run, never persisted; `XSession.__repr__` is redacted so it cannot leak
  into a traceback. Cookie databases are copied before reading, so a live
  browser profile is never locked or mutated.
- **`SCROLLS_X_AUTH_TOKEN` / `SCROLLS_X_CT0` bypass all of it**, for anyone who
  would rather paste two cookies than grant Keychain access — and the only
  path available when the session lives in a browser Scrolls cannot read.

### The volatile surface, named where it lives

- **The query id is pinned and will rotate.** The endpoint is
  `x.com/i/api/graphql/<queryId>/Bookmarks`, where the id is one of X's
  internal build hashes. X rotates them on deploy. That is the maintenance
  bill for not requiring a paid API key, and it is stated in the module
  docstring rather than discovered in production.
- **A rotated id is never reported as an empty collection.** A 404 raises
  `XQueryIdRotated`, whose message says the id needs refreshing and that this
  is *not* an empty bookmark collection. Silently answering "you have no
  bookmarks" is the one wrong answer a custody tool must not give.
- **Pagination ends on an empty page, not a missing cursor.** X keeps offering
  a cursor past the end of the collection. A repeated cursor also terminates
  the walk.
- **A partial pull is still custody.** Items already collected are kept and
  the error is reported alongside them. A failure that captured *nothing*
  is a plain error on stderr instead, because that is where an expired session
  or a rotated id is actually looked for.

### What is captured, and what is honestly missing

- **Identity stays `x:<tweetId>`.** This is the one property from 0009 that
  had to survive its supersession: it matches what `detect.py` mints for
  x.com status URLs, so a natively-pulled bookmark dedupes against a
  `scrolls add` of the same tweet, and against anything imported from Field
  Theory before that path was removed.
- **Parity with the Field Theory import**: text, author handle and name,
  posted-at, media references, expanded links, and quoted-tweet text folded
  into the body. `note_tweet` wins over a truncated `full_text`.
- **`saved_at` falls back to the sync time, and says so.** Neither X path
  exposes a bookmark timestamp. Field Theory's own `types.ts` calls
  `sortIndex` *"X's opaque bookmark ordering key. Useful for chronology, not
  timestamps."* So `provenance.saved_at_source` records `"synced_at"`. Saying
  "we do not know when you saved this" is custody; minting a plausible
  timestamp from an ordering key is fabrication (vision §2.8).
- **Re-syncing never overwrites.** `INSERT OR IGNORE`, the 0009 rule.

### There is no `x` fetch adapter, and `verify` says so

0009 established the boundary that fetch adapters pull one item from the
network while importers bulk-read local archives. Bookmarks sync is a third
shape — **capture-at-pull** — and it sits on the importer side of that line:
items enter at stage `fetched` with content captured from the GraphQL
response, because entering at `detected` would strand them in every
`scrolls fetch` run.

**No `x` entry is added to `FETCH_ADAPTERS`.** The consequence is deliberate
and must be stated rather than discovered: `scrolls verify` **cannot detect
drift on a bookmarked post**. It fails with the existing honest error, `no
fetch adapter for source 'x'`, rather than silently reporting a clean
verdict. An x item is captured once and held; Scrolls does not claim to know
whether the post has since changed or been deleted.

This is the honest position given the surface. Re-running the sync is the
only re-capture path X offers, and it currently skips held items rather than
comparing them.

## Consequences

- **Terms of service.** This uses an endpoint X does not document for third
  parties, with the user's own session, to read the user's own bookmarks. It
  is the same access the browser has. It is nonetheless outside X's developer
  terms, and that is the user's call to make knowingly — hence the honest
  naming throughout rather than a "just works" surface.
- **The maintenance bill is a rotating query id**, not a monthly invoice. When
  it rotates the on-ramp stops with an actionable message and needs a one-line
  refresh.
- **Deferred: the OAuth 2.0 + PKCE fallback.** The official path
  (`tweet.read users.read bookmark.read offline.access`, refresh-token
  rotation) needs a *writable* secret store, which the repo does not have —
  `config.py` parses one `[classify]` section and the only credential
  precedent is a read-only env var. That store is the #2 contract's business.
- **Deferred: drift detection for x**, which needs a re-capture path — most
  likely a re-sync that compares instead of skipping.
- **Not supported: Safari.** Its cookies live in a proprietary
  `binarycookies` format outside the Chromium and Firefox schemes. The env-var
  path covers it.
- **Deferred: an `--all-profiles` sweep.** Discovery stops at the first
  profile holding a session, so a user signed into several accounts gets the
  first one found; `--profile` pins a specific one.
