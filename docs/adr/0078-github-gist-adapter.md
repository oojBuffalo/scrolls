# ADR 0078: GitHub Gist adapter — the developer code-snippet content type

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

The github repo adapter (ADR 0007) covers `github.com/<owner>/<repo>` — a
project's *metadata and README*. It does not cover gists: the standalone files
GitHub hosts at `gist.github.com` (a config, a script, a bug repro, a notebook,
a paste). A gist is a distinct content type — the **developer code snippet** —
and a common save target (IDEAS.md §6 names GitHub as an initial platform).

Until now `gist.github.com` fell through to the generic `web` adapter
(ADR 0001), which `test_detect.py` pinned with a note: *"gist.github.com falls
back to `web` until a gist adapter exists."* A `web` scrape of a gist page is
poor — the page is JS-rendered, the file contents arrive as DOM noise, and the
result has no `concepts`, no author, no clean title. This ADR makes good on that
pinned invitation.

A gist has its own keyless REST endpoint, distinct from the repo endpoint:
`GET https://api.github.com/gists/<id>` returns the *whole* gist in one
request — the description, owner, dates, and **each file's full `content`
inlined** — so the searchable scroll needs no second call (the Lobsters
one-request economy, ADR 0046). The adapter contract (ADR 0002) makes this a
near-template build; the design lives in four platform facts.

## Decision

Add `gist` as its own source and keyless fetch adapter (`sources/gist.py`),
distinct from `github` because the host, the API endpoint, the content, and the
category posture all differ — zero risk to the existing repo detection.

1. **Identity is the gist id alone, lowercased.** A gist URL is
   `gist.github.com/<owner>/<id>`, `gist.github.com/<id>` (anonymous), or a
   revision permalink `…/<owner>/<id>/<sha>`. The owner login is *decorative*:
   the API is keyed by the gist id alone (`GET /gists/<id>`), which resolves the
   owner itself — so identity drops the login and every URL form for one gist
   dedupes (`gist:<id>`), the slug-dropped Discourse pattern (ADR 0054). The id
   is a hexadecimal hash folded lowercase to canonical (the crates/Open Library
   fold, ADR 0036/0073). `_gist_id` claims any hex id from the *second* segment
   (the owner disambiguates), but a *bare* one-segment id only at full
   modern-id length (≥20) — a hex-looking username would otherwise be confused
   with that owner's gist-*list* page (`gist.github.com/octocat`), which must
   stay a bare `gist` source with no fetchable item (github's profile-page
   pattern); the rare bare short legacy id is left to the owner-qualified form.
   Reserved routes (`/discover`, `/starred`, …) carry no gist.

2. **One request: files inlined.** `GET /gists/<id>` returns each file with its
   `content` inline, so the entire scroll comes from one keyless GET — no
   per-file fetch (Lobsters' economy). Truncated very-large files (the API caps
   inline `content` and sets `truncated`) keep their partial body; refetching the
   full text via `raw_url` is deferred (the partial still indexes).

3. **Files → `extracted_text`; languages → `tags`; `concepts` empty.** Each
   file becomes a `### <filename>` heading and a language-hinted fenced code
   block, emitted in *sorted-filename* order so the body and its `content_hash`
   are deterministic; blank files are skipped. The distinct file `language`s
   (`Python`, `Shell`, `Markdown`) become `tags` — the one structured facet a
   gist offers, the **bitbucket `language`→tag mapping** (ADR 0057). `concepts`
   stay empty *by design*: a gist has no topic/keyword facet (the bitbucket/go
   posture, ADR 0057/0042), so it does not join the concept graph — honest, not a
   gap. The `title` is the gist `description` else the first filename else
   `Gist <id>`; the `summary` is a file *manifest* (`"2 files: a.py, b.md"`) —
   informative at a glance and searchable whether or not the gist has a
   description; `author` is `owner.login` (anonymous gists → None);
   `published_at` is `created_at`; `canonical_url` is the gist `html_url`. The
   raw gist JSON stays in `raw_text` for rebuilds; `provenance.extraction_method`
   is `github-api:gist`.

4. **No category default — unclassified.** A gist is heterogeneous (a config, a
   script, a repro, notes), so it gets *no* curated source category. Forcing
   github's `project` would be dishonest — a gist is a snippet, not a project to
   read. An item flows through the title rules and otherwise stays honestly
   unclassified — the Hacker News / Bluesky / dev.to posture
   (ADR 0031/0048/0061), not a guessed default; the LLM engine can name it later.

**Keyless, github's token posture.** The gist API shares github's host, rate
limit, and token env vars, so `_api_headers` mirrors ADR 0007: keyless by
default, `GITHUB_TOKEN`/`GH_TOKEN` → `Authorization: Bearer` to lift the rate
limit. A gist whose files are all empty degrades to a metadata-only scroll
(`extracted_text=None`) rather than failing — the README-less-repo degrade;
`FetchError` is reserved for a missing id and the API request failing.

## Consequences

- A saved gist now becomes a clean scroll with real title, author, dates,
  searchable code, and language tags, instead of a `web` DOM scrape. Re-adding a
  previously-`web`'d gist mints a *different* id (`gist:<id>` vs `web:<hash>`),
  so the two do not auto-merge (different source, not a pre-normalization
  duplicate — ADR 0026); the `web` copy can be `scrolls rm`'d. This is the same
  acceptable seam every island-reclaiming adapter has (ADR 0061/0073/0075).
- A gist contributes no `concepts`, so it stays out of the KB concept pages and
  the concept facets — the honest consequence of GitHub not offering a gist
  topic facet (the bitbucket posture). It still participates in `search`,
  `list`, the source/tag KB pages, and tag facets.
- Identity drops the owner, so a gist saved from one owner's URL and the same
  gist viewed at a forked/anonymous URL dedupe — correct, since the API treats
  the id as the identity. The trade-off is that a bare short legacy gist id
  (`gist.github.com/12345`, no owner) is not claimed; this is rare and the
  owner-qualified form (`gist.github.com/<owner>/12345`) still works.
- The fenced code blocks use triple-backtick fences; a gist whose own content
  contains a ``` run would render an imperfect fence. This is cosmetic (the body
  is for FTS and agent reading, not re-publication) and matches the other
  adapters' plain-text economy.

## Proof

`src/scrolls/sources/gist.py` with a transport-faked test
(`tests/test_gist.py`, fixtures trimmed from the real API): the one-request
fetch, the sorted fenced-section `extracted_text`, the distinct-languages→`tags`
mapping (dedupe, null-language skip) with empty `concepts`, the manifest
`summary` (singular/plural), the description/first-filename title, the
anonymous-gist no-author case, the all-blank-files metadata-only degrade, the
`raw_text` round-trip, identity/URL preservation, the seeded-`published_at`
fallback, the requested API URL, the missing-id / request-failed `FetchError`s,
and the keyless/Bearer headers — all offline. The no-category-default decision
is pinned by `test_gist_has_no_category_default`. Detection is pinned in
`tests/test_detect.py` (the owner/id and bare-id forms deduping, the revision
deep-link dedupe, the lowercase hex fold, the user gist-list page and reserved/
home routes carrying no gist). `FETCH_ADAPTERS["gist"]` registration is covered
by `test_gist_adapter_is_registered`.

Live keyless smoke (the ADR 0007 posture, tests stay offline) grounded the
fixtures against the real API. `scrolls ingest` of
`gist.github.com/choco-bot/4d0b85a055d5d29d129ae6386ede2e3e` produced a clean
scroll: title from the gist description, `author` `choco-bot`, `summary`
`"3 files: Install.txt, InstallImage.md, _Summary.md"`, `tags`
`["Text", "Markdown"]`, empty `concepts`, no category, the gist permalink as
canonical, and each file's content as a fenced section in `extracted_text`. (The
`GET /gists/<id>` endpoint serves public gists keyless — verified `200`
unauthenticated; an *invalid* `GITHUB_TOKEN` makes it `401`, the same way it
would for the repo adapter, so the token must be valid or unset.)
