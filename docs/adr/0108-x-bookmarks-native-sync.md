# 0108: X bookmarks sync natively — browser session by default, OAuth as fallback

Date: 2026-08-13

Status: accepted

Supersedes: [0009](0009-fieldtheory-import.md)

*Amended: 2026-08-24 — the `x` fetch adapter now exists. The section below
records why it was originally left out and what changed.*

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

`scrolls sync x --bookmarks` pulls the collection directly from X, over
**either of two routes**: the browser session by default, or X's official API
under an OAuth grant with `--auth oauth`.

**The route must not change the artifact.** Both mint `x:<tweetId>`, capture
the same fields, and record the same `saved_at_source`, so the two dedupe
against each other and a library assembled by both routes is one collection.
Only `provenance.extraction_method` distinguishes them — `x:graphql-internal`
against `x:api-v2` — which is exactly the distinction custody should keep:
same artifact, different road. A test pins the two parsers to identical items
for the same bookmark.

**Verified against live X on 2026-08-18.** A full run over a Brave session
pulled 479 bookmarks across 6 pages with no failures, terminated on the
end-of-collection empty page, and re-synced to 479 skips. Every item carried an
author, posted-at, text, media list and content hash; 71 had `t.co` links
expanded to their real targets. The pinned query id and feature-flag set are
therefore known-good as of that date, which is what distinguishes a later 404
from a code defect.

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

### The official API as an opt-in fallback

- **`scrolls x login`** runs OAuth 2.0 + PKCE once (S256, never `plain`) over
  a **loopback** redirect, so the authorization code never passes through a
  clipboard or terminal scrollback. The `state` is compared in constant time,
  because it is the only thing standing between a forged callback and an
  adopted grant.
- **Scopes are `tweet.read users.read bookmark.read offline.access`.** The
  last one is load-bearing: without it X issues no refresh token and the user
  re-authorizes every two hours.
- **A refresh that does not persist is worse than no refresh.** X rotates the
  refresh token on every use, so `resolve_access_token` writes the rotated set
  back before returning. Tokens are refreshed a minute ahead of expiry so one
  cannot die mid-pagination.
- **This path is metered**, so a 402 says so in those words rather than
  reading as a bug, and it stays opt-in behind `--auth oauth`. The cookie path
  costs nothing and remains the default.
- **It is unverified against live X, and will stay unverified.** Proving it
  needs a registered developer app on a paid plan, which the maintainer has
  declined to buy to validate a fallback. The tests inject the network and the
  browser, so they prove the logic is self-consistent and prove nothing about
  whether X accepts it. This is recorded in the module docstrings, the two
  `--auth oauth` help strings, `docs/cli.md` and `docs/adapters.md`, so the
  gap is discoverable before use rather than at 3am. Anyone holding an app is
  invited to verify it and amend those notes.

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

### The `x` fetch adapter, deferred then built

0009 established the boundary that fetch adapters pull one item from the
network while importers bulk-read local archives. Bookmarks sync is a third
shape — **capture-at-pull** — and it sits on the importer side of that line:
items enter at stage `fetched` with content captured from the GraphQL
response, because entering at `detected` would strand them in every
`scrolls fetch` run.

**Originally, no `x` entry joined `FETCH_ADAPTERS`.** The stated consequence
was that `scrolls verify` could not detect drift on a bookmarked post: it
failed with the honest `no fetch adapter for source 'x'` rather than a false
clean verdict, on the reasoning that re-running the whole sync was the only
re-capture path X offered.

**That reasoning was wrong, and dogfooding is what showed it.** Pulling the
collection into the live library put 482 posts — 46% of it — permanently
beyond verification, and a sweep stamped every one of them `error`. The
premise failed on inspection: X's web client reads a single post through
`TweetResultByRestId`, the same internal GraphQL API, over the same session
cookie. There was a re-capture path all along.

`src/scrolls/sources/x.py` now registers `"x"` in `FETCH_ADAPTERS`. Three
properties keep the verdicts honest:

- **The same session, not an easier one.** X's public syndication CDN would
  have been simpler to call and needs no cookies, but it is anonymous: it
  cannot see a protected account you follow, so a re-capture would see less
  than the capture did and report drift that never happened. The adapter
  borrows the browser session, exactly as the bookmarks walk does. Stored
  credentials remain the optional path, never the default.
- **The same parser, so hashes are comparable by construction.** Both
  endpoints return the identical tweet subtree, so both route through
  `x_bookmarks.item_from_tweet_result`. Were the two extractions allowed to
  drift apart, every unchanged post would start reporting drift.
- **A deleted post is rot, not an error.** X reports deletion as a normal 200
  with an empty `data.tweetResult`, so there is no 404 for `custody._is_gone`
  to read. The adapter raises `SourceGone` — a new `FetchError` subtype that
  carries "the source says this is gone" structurally, rather than inventing an
  HTTP status that never came over the wire or letting a message string decide
  custody.

A re-capture keeps the held `saved_at`, and carries `saved_at_source` and
`sort_index` across unchanged. X still exposes no bookmark timestamp; a second
read knows no more about when you saved something than the first one did.

The pinned `TweetResultByRestId` query id carries the same rotation risk as the
bookmarks one and is dated in the source beside it. It was read out of x.com's
own JavaScript bundle rather than guessed.

## Consequences

- **Terms of service.** This uses an endpoint X does not document for third
  parties, with the user's own session, to read the user's own bookmarks. It
  is the same access the browser has. It is nonetheless outside X's developer
  terms, and that is the user's call to make knowingly — hence the honest
  naming throughout rather than a "just works" surface.
- **The maintenance bill is a rotating query id**, not a monthly invoice. When
  it rotates the on-ramp stops with an actionable message and needs a one-line
  refresh.
- **The credential store is the first *writable* secret in the library.**
  Every prior credential was a read-only environment variable. X rotates the
  refresh token on every use, so a store that cannot be updated locks the user
  out after one refresh. Hence `<root>/credentials.json` at mode 0600, written
  through a single `os.open(..., 0o600)` helper so the secret is never briefly
  world-readable, keyed by service so other credentials survive an X rewrite.
  If the #2 contract later settles on a different store, this is the shape it
  has to beat, not a blocker it has to unblock.
- **Shipped 2026-08-24: drift detection for x.** The guessed re-capture path
  here — "most likely a re-sync that compares instead of skipping" — was not
  the one that existed. `TweetResultByRestId` reads a single post over the same
  session, so the adapter is per-item like every other, and no special re-sync
  mode was needed. See *The `x` fetch adapter, deferred then built* above.
- **Not supported: Safari.** Its cookies live in a proprietary
  `binarycookies` format outside the Chromium and Firefox schemes. The env-var
  path covers it.
- **Deferred: an `--all-profiles` sweep.** Discovery stops at the first
  profile holding a session, so a user signed into several accounts gets the
  first one found; `--profile` pins a specific one.
