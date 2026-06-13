# 0050: GoToSocial and Pleroma/Akkoma join the Mastodon adapter by URL shape

Date: 2026-06-13

Status: accepted

## Context

The Mastodon adapter (ADR 0049) was the first source detected by URL *shape*
rather than host, because the Fediverse has no shared host to claim. It
closed by naming its own sequel:

> Pleroma/Akkoma and GoToSocial expose the same `/api/v1/statuses` surface
> but mint non-numeric ids on different URL routes, so each is a future shape
> branch, not a rewrite.

This is that branch. GoToSocial and Pleroma/Akkoma are the most common
Mastodon-API-compatible server implementations after Mastodon itself. Both
serve the *identical* keyless read endpoints the adapter already speaks:

- `GET https://<instance>/api/v1/statuses/<id>` — the status.
- `GET https://<instance>/api/v1/statuses/<id>/context` — its thread.

and return Mastodon-shaped status JSON (`content` HTML, `account`,
`media_attachments`, `tags`, `card`, `spoiler_text`, `reblog`, the
`favourites_count`/`reblogs_count`/`replies_count` trio). So the *fetch* path
needs nothing new — `src/scrolls/sources/mastodon.py` reads only standard
fields and treats the status id as an opaque token. What differs is two
things detection must learn:

1. **The URL routes.** A public status's canonical web URL is not
   `/@<user>/<id>` on these forks:
   - **GoToSocial** — `/@<user>/statuses/<ULID>` (web), and the shared
     ActivityPub form `/users/<user>/statuses/<ULID>`.
   - **Pleroma/Akkoma** — `/notice/<FlakeId>` (web), and the shared AP form
     `/users/<nick>/statuses/<FlakeId>`.
2. **The id is not numeric.** GoToSocial mints a **ULID** (26 uppercase
   Crockford base32 chars); Pleroma/Akkoma a **FlakeId** (a base62 run, ~18
   chars). Mastodon's all-digits constraint — ADR 0049's safety lever — would
   reject both.

The tension: ADR 0049's numeric-id rule is exactly what keeps the
host-agnostic heuristic from stealing a Medium `/@author/<slug>` or a
Threads/TikTok `/@user/<kind>/<id>`. Relaxing it to admit non-numeric ids
must not reopen that door.

## Decision

Extend the existing `mastodon` source — no new source name, no new fetch
adapter. The source name already means "a status on a Mastodon-API-compatible
instance"; GoToSocial and Pleroma are exactly that. Only `detect.py`'s
`_mastodon_id` grows, splitting into a small `_fediverse_status_id` that
recognizes four URL shapes and pairs each with the id constraint that keeps
it safe:

| Shape | Server | Id constraint | What anchors safety |
| --- | --- | --- | --- |
| `/@<user>/<id>` | Mastodon | all digits | the strict numeric rule (unchanged) |
| `/@<user>/statuses/<id>` | GoToSocial | base62 run | the literal `statuses` segment |
| `/users/<user>/statuses/<id>` | all (AP form) | base62 run | the `users`+`statuses` literals |
| `/notice/<id>` | Pleroma/Akkoma | base62 run, **16+ chars** | the `notice` literal + length floor |

The reasoning behind the constraints (`tests/test_detect.py`):

- **The Mastodon `/@<user>/<id>` form keeps all-digits.** GoToSocial and
  Pleroma do not use a bare two-segment `/@user/<id>` permalink, so nothing
  is lost by leaving this rule strict — and it is what continues to keep
  Medium's `/@author/<slug>` (non-numeric) a web page.
- **The two `statuses`-bearing forms admit any base62 id.** No mainstream
  non-Fediverse platform routes a content URL through `/@user/statuses/<id>`
  or `/users/<user>/statuses/<id>`; the literal `statuses` segment is a
  strong, Fediverse-specific anchor, so the id only needs to be a single
  base62 token (which a ULID, a FlakeId, and a snowflake all are, and a
  hyphenated slug is not).
- **The bare `/notice/<id>` form needs a length floor.** It is the weak one:
  `/notice/<id>` could appear on any site (a `/notice/privacy` legal page).
  Its id therefore carries a 16-character minimum that a real FlakeId (~18
  chars) clears but `/notice/privacy` (7) and a hyphenated `/notice/cookie-policy`
  do not — the latter also failing the base62 charset. A residual false
  positive degrades to a benign failed fetch (the `/api/v1/statuses` call
  404s), never a wrong scroll — exactly ADR 0049's reversible tradeoff.
- **Pleroma's AP *Object* URL (`/objects/<uuid>`) is deliberately not
  matched.** That uuid identifies the ActivityPub object, not the
  `/api/v1/statuses/<id>` the adapter fetches, so it would 404; it is left to
  the `web` adapter.

Identity is unchanged: every shape collapses to `<host>/<status_id>`, so a
status saved via its web permalink and via its AP form dedupe to one item
(`tests/test_detect.py`). The non-numeric ids are kept verbatim — ULIDs are
uppercase and FlakeIds case-sensitive, and the API resolves them as-is — while
the host is still lowercased.

The fetch adapter is untouched, but two tests pin that a fork status flows
through it correctly: a GoToSocial ULID status
(`test_gotosocial_ulid_status_fetches_through_the_same_adapter`) and a
Pleroma FlakeId status carrying Pleroma's `pleroma` extension keys and a
content warning (`test_pleroma_flakeid_status_with_extension_keys_and_cw`),
both in `tests/test_mastodon.py`. They assert the non-numeric id is used
verbatim in the API URL (case preserved), the extension keys are inert, and
`provenance.adapter` stays `mastodon`.

## Consequences

- A saved GoToSocial or Pleroma/Akkoma post — from any instance — becomes the
  same clean scroll a Mastodon post does, with no new fetch adapter, no new
  source, and no schema change. The Fediverse coverage roughly matches where
  Fediverse users actually are.
- `provenance.adapter` records `mastodon` for a fork status, because the
  Mastodon-API adapter is genuinely what served it and the specific server
  software is not reliably knowable from the URL (and no behavior depends on
  it). This is the honest call here, unlike DataCite-via-Crossref (ADR 0045),
  where the *adapter* really differs and provenance says so.
- Detection's safety model generalizes from "the id is numeric" to "a
  distinctive literal anchors the shape, and the id constraint is as strict
  as that anchor is weak." The `notice` length floor is the worked example;
  the next Fediverse server (Misskey's `/notes/<id>`, say) slots in as another
  row with its own anchor-and-id pairing.
- Deferred, as in ADR 0049: home-instance-canonical identity (a status reached
  through a remote instance, or by a different canonical URL, is still a
  separate item). That needs a fetch-time rewrite of the item id no adapter
  does today — the same deferral DID-canonical Bluesky carries (ADR 0048).
