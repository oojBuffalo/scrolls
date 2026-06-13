# Scrolls Architecture

How the implemented system works today, with pointers into the code and
tests that prove each claim. For the product vision and design brainstorm
see `IDEAS.md`; for the rationale behind individual decisions see the
ADRs indexed at `docs/adr/README.md`.

Everything below describes code on this branch, verified by
`uv run pytest` (1498 tests at the time of writing). The docs themselves
are guarded by `tests/test_docs.py`: cited test names, relative links,
and `IDEAS.md §N` references must resolve, and `docs/cli.md`'s captured
examples are pinned to the code's version and schema.

## The pipeline

The mental model `Sources → Items → Scrolls → Library → Agents` maps to
a small set of idempotent stages. Each item row carries a `stage` column;
each command moves items between stages or derives artifacts from them.

```text
 feed ── follow ──▶ subscription ── sync ──▶ new entry URLs join at 'detected'

 URL ── add ──▶ detected ── fetch ──▶ fetched ── md ──▶ rendered
                  │ ▲                   ▲                  │
                  │ ├ import google-takeout                │
                  │ └ import bookmarks                     │
                  │   import fieldtheory┘                  ▼
                  │            classify (stage-neutral, sets category)
                  │            media    (stage-neutral, downloads media refs)
                  │            kb       (stage-neutral, compiles library/)
                  │
                  └─ sources without a fetch adapter stay 'detected'
```

- `scrolls add <url>` detects the source, mints a stable id, and inserts
  a row at stage `detected` (`src/scrolls/cli.py`, `src/scrolls/items.py`).
- `scrolls fetch [id]` runs the source adapter, filling title, extracted
  text, summary, links, media, content hash, and provenance, and moves
  the item to `fetched` (`src/scrolls/sources/`). `--limit N` paces a
  batch run — at most N attempts, oldest saved first, resuming next
  run — so a bulk-imported spine enriches incrementally.
- `scrolls md [id]` renders each fetched item to a Markdown scroll at
  `scrolls/<source>/<slug>.md` and moves it to `rendered`
  (`src/scrolls/render.py`).
- `scrolls classify [id]`, `scrolls media [id]`, and `scrolls kb` are
  stage-neutral engines: classification assigns `category` without
  advancing the stage, media capture downloads items' media refs into
  `media/<source>/`, and the KB compiler rebuilds `library/` from
  whatever is rendered (`src/scrolls/classify.py`,
  `src/scrolls/media.py`, `src/scrolls/kb.py`).
- `scrolls ingest <url>` chains add → fetch → classify → md for one URL.
- `scrolls import fieldtheory` bulk-inserts X bookmarks directly at stage
  `fetched`, since the archive already contains the content
  (`src/scrolls/fieldtheory.py`, ADR 0009).
- `scrolls import google-takeout` bulk-inserts YouTube watch history at
  stage `detected` — Takeout is a spine with no content, so the export's
  title/channel/watch-time seed items the way feed entries do and
  `scrolls fetch` enriches them (`src/scrolls/takeout.py`, ADR 0029).
- `scrolls import bookmarks` bulk-inserts a browser bookmarks HTML
  export at stage `detected` — another bare spine, but heterogeneous:
  each URL routes through the same detection as `add`, and folder
  ancestry becomes `tags` (`src/scrolls/bookmarks.py`, ADR 0030).
- `scrolls follow <url>` / `scrolls sync [id]` subscribe to RSS/Atom
  feeds and register their new entry URLs at stage `detected` through
  the same detection/dedupe as `add` — sync discovers URLs, adapters
  still fetch (`src/scrolls/feeds.py`, ADR 0017).

Per-item failures never abort a batch: `fetch`, `md`, `media`,
`sync` (per subscription), and `kb --engine llm` (per concept) report
each failure in their JSON output and continue (`tests/test_cli.py`).

## Storage: SQLite is the index, Markdown is the artifact

Two stores, by design (IDEAS.md §3):

- **`db.sqlite`** — the canonical index. One `items` table whose columns
  mirror the `ScrollItem` dataclass one-to-one (`src/scrolls/items.py`,
  `src/scrolls/db.py`). List-valued fields (`tags`, `concepts`, `links`,
  `media`) and `provenance` round-trip through JSON text columns. An
  external-content FTS5 table (`items_fts`) over title/summary/extracted
  text is kept in sync by SQL triggers so no Python write path can forget
  it. A `subscriptions` table holds followed feeds and their sync
  state, including each feed's HTTP cache validators (ADR 0017,
  ADR 0019) — sync state belongs to the index, not config (IDEAS.md
  §3). A `concept_summaries` table holds the LLM concept engine's
  synthesized concept-page summaries with the members fingerprint that
  makes regeneration incremental (ADR 0025). `meta` carries the schema
  version (`SCHEMA_VERSION = 6`);
  `MIGRATIONS[n]` walks any version gap in one transaction, and opening a
  newer-versioned library raises instead of corrupting it
  (`tests/test_db.py`).
- **`scrolls/<source>/<slug>.md`** — the durable, human- and
  agent-readable artifact. Frontmatter lines are `key: <JSON value>`
  (YAML 1.2 is a JSON superset, so standard parsers read them with zero
  dependencies). Scrolls can always be rebuilt from the index;
  `markdown_path` is recorded so re-renders keep a stable path
  (`src/scrolls/render.py`, `tests/test_render.py`). The full file
  format — frontmatter keys, body sections, KB page formats, and the
  stability guarantees consumers may rely on — is specified in
  `docs/library-format.md`.

The library root is `~/.scrolls`, overridden by `$SCROLLS_HOME` — every
path derives from the root so tests and portable installs can relocate
the whole tree (`src/scrolls/paths.py`):

```text
$SCROLLS_HOME (default ~/.scrolls)
  db.sqlite      # items + subscriptions + concept_summaries tables + FTS5 index + schema meta
  scrolls/       # one Markdown scroll per rendered item, per source
  library/       # compiled KB: index.md, graph.md, sources/, categories/, concepts/
  agents/        # generated agent instruction files (claude/, codex/, hermes/)
  items/         # reserved (raw record exports; currently unused)
  media/         # captured media files (PDFs, thumbnails, photos), per source
  config.toml    # settings; today: [classify] default_engine + llm_model
```

## The data model

`ScrollItem` (`src/scrolls/items.py`) is the single normalized record
every source becomes — the IDEAS.md §12 model, frozen as a dataclass:
identity (`id`, `source`, `source_id`, `url`, `canonical_url`), content
(`title`, `author`, `published_at`, `raw_text`, `extracted_text`,
`summary`), classification (`category`, `domain`, `tags`, `concepts`),
graph edges (`links`, `media`), and bookkeeping (`content_hash`,
`markdown_path`, `provenance`, `stage`, `saved_at`).

Item ids are stable and deduplicating: `source:source_id` when the URL
carries a source-local id (`wikipedia:en:SQLite`, `arxiv:1706.03762`,
`x:1234567890`), else `source:` plus a 12-hex-char SHA-256 of the URL
(`make_item_id`). `scrolls add` of a tweet URL and a Field Theory import
of the same tweet therefore collide on purpose — `INSERT OR IGNORE`
keeps the existing row (`tests/test_items.py`, `tests/test_fieldtheory.py`).

Because the URL string itself is the identity of `web`/`pdf` items,
registration normalizes it first (`normalize_url` in
`src/scrolls/sources/urls.py`, ADR 0023): tracking params (`utm_*`,
`fbclid`, …), fragments, host casing, and default ports are dropped
before hashing and the normalized form is what gets stored, so the
same article saved via differently decorated links stays one item
(`tests/test_urls.py`). Everything else — param order, percent
encoding, ambiguous names like `ref` — survives byte-identical, and
feed subscription URLs are never rewritten.

## The source adapter model

Two small contracts make every platform the same kind of scroll
(IDEAS.md §1):

1. **Detection** — `detect_source(url) -> DetectedSource(source, source_id)`
   in `src/scrolls/sources/detect.py`. Pure URL inspection, no network:
   host tables map to `youtube`, `wikipedia`, `github`, `gitlab` (a
   `gitlab.com/<group>/<project>` URL — gitlab.com only, the second code
   host; the whole `group[/subgroup…]/project` path before any `/-/`
   sub-resource separator as `source_id`, nested-group-aware, folded
   lowercase since GitLab forces lowercase slugs, deep links deduping to the
   project, ADR 0055), `gitea` (a `codeberg.org`/`gitea.com`
   `/<owner>/<repo>` URL — the third code host, one source for Gitea and its
   fork Forgejo; uniquely the *instance host rides in the* `source_id`
   (`<host>/<owner>/<repo>`, `www.` folded off, owner/repo verbatim) because
   the Gitea API lives on each instance's own host, so reaching a self-hosted
   instance later is a detection-only change, ADR 0056), `bitbucket` (a
   `bitbucket.org/<workspace>/<repo>` URL — the fourth code host, host-scoped
   with a single fixed API host like github since Bitbucket Cloud is one
   service, *not* host-in-id like gitea; the flat `<workspace>/<repo>` folded
   lowercase since Bitbucket auto-lowercases slugs and routes
   case-insensitively, deep links deduping to the repo, ADR 0057), `arxiv`,
   `biorxiv` and `medrxiv` (the `/content/10.1101/<accession>` URL on each
   server's host, the `10.1101/<accession>` DOI as `source_id` with the `vN`
   version and `.full`/`.full.pdf`/early-access views stripped so every view
   dedupes; kept as *two* sources because a medRxiv paper does not live on
   bioRxiv, even though one fetch adapter serves both off the shared
   `api.biorxiv.org`, ADR 0068),
   `x`,
   `hackernews`, `lobsters` (a `/s/<short_id>` story URL, the short id
   verbatim), `bluesky` (a `bsky.app/profile/<actor>/post/<rkey>` post URL,
   `<actor>/<rkey>` as `source_id` with the actor folded lowercase — handle
   and DID are both case-insensitive — and the record key verbatim; the
   post's true AT-URI identity needs a DID resolvable only at fetch time,
   ADR 0048), the `stackexchange` network (every site's question
   URL, the per-site API slug carried in `source_id`), `pypi`
   (project pages, the PEP 503-normalized package name as `source_id` so
   a versioned page dedupes to the package), `npm` (package pages,
   the package name verbatim as `source_id` — the registry is
   case-sensitive, so unlike PyPI it is not folded — scoped names and
   version pages included), `crates` (crate pages, the name folded
   case-insensitively like a PyPI one so a version page dedupes),
   `packagist` (Composer package pages, the `vendor/name` folded
   lowercase as `source_id` since Composer names are case-insensitive, a
   trailing `.json` and deeper subpages stripped),
   `rubygems` (gem pages, the gem name verbatim as `source_id` since
   RubyGems is case-sensitive like npm, version pages included),
   `go` (`pkg.go.dev` module pages, the module path verbatim as
   `source_id` — case-sensitive, the part before any `@version`, with a
   domain first segment so stdlib and site routes carry no fetchable
   module),
   `devto` (a `dev.to/<user>/<slug>` article URL, the flat two-segment
   `<user>/<slug>` folded lowercase since Forem mints lowercase handles and
   slugs and the case-sensitive API only resolves the lowercase form — the
   gitlab/bitbucket fold — deep links deduping to the article, reserved
   `t`/site routes carrying no article, the URL handle being the author *or
   organization* the post is published under, ADR 0061),
   `crossref` (a `doi.org`/`dx.doi.org` DOI link, the DOI folded
   lowercase as `source_id` since DOIs are case-insensitive — the DOI's
   *registration agency*, Crossref or DataCite, is resolved at fetch
   time, not detection, ADR 0045), and
   `huggingface` (model, dataset, and Space repo pages on
   `huggingface.co`/`hf.co`, the repo *kind* in the `source_id` as
   `model:<org>/<name>`, `dataset:<...>`, or `space:<...>` so one adapter
   serves all three API endpoints — the Stack Exchange shape — the id kept
   verbatim since the Hub is case-sensitive, subpages deduped to the
   two-segment repo, site routes carrying no fetchable repo), and `pubmed`
   (the biomedical literature, the integer PMID as `source_id`; the
   dedicated `pubmed.ncbi.nlm.nih.gov` host is claimed wholesale with the
   PMID as the first path segment, while the legacy
   `ncbi.nlm.nih.gov/pubmed/<pmid>` form is *shape-matched* because that
   host also serves PMC/Gene/Nucleotide — those fall through to `web` —
   ADR 0065), and `rfc` (IETF technical standards via the RFC Editor's JSON
   view; **host-restricted shape matching** across `rfc-editor.org`,
   `datatracker.ietf.org`, `tools.ietf.org`, and `ietf.org` — only the
   `rfc<digits>` path shape is claimed, the integer number with leading zeros
   stripped so `rfc0020` and `rfc20` dedupe to `rfc:20`, while Internet-Drafts,
   working-group, and org pages on those shared hosts fall through to `web` —
   the legacy-NCBI-host posture, ADR 0066). Two
   *shape-only* branches then run on any host not already claimed, because
   the Fediverse is federated with no host set: `mastodon` matches a
   Mastodon-API status URL (`/@<user>/<digits>`, GoToSocial's
   `/@<user>/statuses/<id>`, Pleroma's `/notice/<id>`, the shared AP
   `/users/<user>/statuses/<id>`), `misskey` matches the Misskey-family
   `/notes/<id>`, and `lemmy` matches the link-aggregator `/post/<digits>`
   — all folding the instance host into the id (`<host>/<id>`,
   instance-local), each id constrained as strictly as its anchoring
   literal is weak (Lemmy's `post` literal needs an all-digits id and
   exactly two segments), a misdetect degrading to a benign failed
   fetch (ADRs 0049–0052). PieFed shares Lemmy's exact `/post/<digits>`
   shape, so it too detects as `lemmy` — which of the two backends actually
   serves a post (Lemmy's `/api/v3` or PieFed's `/api/alpha`) is resolved at
   *fetch* time by the `threadiverse` dispatcher, not at detection (ADR 0053,
   the DOI-dispatch pattern of ADR 0045). A fourth shape-only branch,
   `discourse`, then matches the forum software's `/t/<slug>/<id>` topic URL on
   any unclaimed host (`discourse:<host>/<topic_id>`, the slug display-only and
   dropped, the all-digits id carrying the weak `t` literal) — the **first
   non-Fediverse host-less source**, proving the shape-detection technique
   generalizes beyond ActivityPub (ADR 0054). Finally `.pdf`
   paths map to `pdf`; everything else is `web`. A
   known source with `source_id=None` means the adapter resolves
   identity at fetch time (`tests/test_detect.py`).
2. **Fetching** — a function `ScrollItem -> ScrollItem` that fills in
   content and returns the item at stage `fetched`, raising `FetchError`
   on any failure (`src/scrolls/sources/__init__.py`, ADR 0002). The
   `FETCH_ADAPTERS` dict maps source names to these functions. A source
   with no entry (today only `x`) is still registered by `scrolls add`
   but skipped by `scrolls fetch` until its adapter lands. One source can
   map to a *dispatch* over several adapters: `crossref` points at the
   `doi.py` dispatcher, which tries the Crossref adapter and falls back to
   the DataCite one for a DOI Crossref doesn't hold (ADR 0045) — the
   registration agency can't be read off a `doi.org` URL, so it is
   resolved at fetch time, not detection.

Implemented fetch adapters, all keyless:

| Source | Module | Method | Distinctive output | ADR |
| --- | --- | --- | --- | --- |
| wikipedia | `sources/wikipedia.py` | MediaWiki action API, stdlib only | page categories → `concepts` | 0002 |
| web | `sources/web.py` | `trafilatura` extraction | readable article text | 0001 (dep policy) |
| youtube | `sources/youtube.py` | oEmbed + optional `youtube-transcript-api` | transcript → extracted text; degrades to metadata-only | 0003 |
| github | `sources/github.py` | REST API + optional README | repo topics → `concepts`; `GITHUB_TOKEN` lifts rate limit | 0007 |
| gitlab | `sources/gitlab.py` | keyless REST API + optional README via the `/-/raw/` route | the second code host (gitlab.com only); nested-group path URL-encoded whole + folded lowercase; `topics` → `concepts`, SPDX `license.key` → `tag`; `GITLAB_TOKEN` (→`PRIVATE-TOKEN`) lifts the rate limit; degrades to metadata-only | 0055 |
| gitea (incl. Forgejo) | `sources/gitea.py` | keyless `GET /api/v1/repos/<o>/<r>` + optional README via the API raw route | the third code host (codeberg.org/gitea.com), and the first to carry the instance host *in the id* (`gitea:<host>/<owner>/<repo>`) because the API is per-host not a single service — one adapter for Gitea + its API-compatible fork Forgejo (the mastodon/forks pattern); inline `topics` → `concepts` like github (no second call), no inline license so `tags` empty; README is README.md-first via the API raw route (the web `download_url` login-gates anonymous gitea.com clients; listing a big root times out) with a root-listing fallback for a non-`.md` README; `GITEA_TOKEN`/`FORGEJO_TOKEN` (→`Authorization: token`) lifts the limit; degrades to metadata-only | 0056 |
| bitbucket | `sources/bitbucket.py` | keyless `GET /2.0/repositories/<ws>/<repo>` + optional README via the `/src/<branch>` route | the fourth code host; Bitbucket *Cloud* is a single service so it is host-scoped with a fixed API host and a flat `<workspace>/<repo>` identity like github (not host-in-id like gitea; Bitbucket Server/DC deferred), folded lowercase (slugs auto-lowercase, case-insensitive routing — the gitlab fold); **no topics so `concepts` empty by design**, `language` → the one `tag`; README via the `/src/<mainbranch>/<path>` route (no `/readme` endpoint, no `/raw/` route) — README.md-first then a root-listing fallback for a non-`.md` README; `BITBUCKET_TOKEN` (→`Authorization: Bearer`) lifts the limit; degrades to metadata-only | 0057 |
| arxiv | `sources/arxiv.py` | Atom export API + `pypdf` full text | abstract → `summary`, taxonomy codes → `tags`, their display names → `concepts`, PDF → `media`, published `arxiv:doi` → `doi.org` `link` (preprint↔published edge, ADR 0038); degrades to abstract-only | 0008, 0010, 0012, 0038 |
| biorxiv, medrxiv | `sources/biorxiv.py` | keyless `api.biorxiv.org/details/<server>/<doi>`, stdlib JSON, one request | arXiv's biology/medicine preprint siblings; **two distinct sources, one shared adapter** (it reads `item.source` to pick the `<server>`) — *not* one source with a server qualifier (the huggingface unify is rejected: a medRxiv paper does not live on bioRxiv, so labeling it `biorxiv` would be dishonest — ADR 0045's honesty value), the inverse of the doi/threadiverse one-source-many-adapters shape; identity `10.1101/<accession>`, every `vN`/`.full`/`.full.pdf`/early-access view deduping to it (arXiv `abs`/`pdf` dedupe); the **highest version** in the ascending `collection` is the current preprint; abstract → `summary` with **no `extracted_text`** and **no PDF media** (the `.full.pdf` 403s anonymous clients — the deliberate divergence from arXiv whose PDF serves freely, ADR 0010); subject `category` → the one `concept` (sentence-cased so `HIV/AIDS` survives), study `type` (space-bearing only, so medRxiv's `PUBLISHAHEADOFPRINT` sentinel drops) + `server` venue + recognized CC `license` → `tags`; `published` journal DOI → `doi.org` `link` (preprint↔published edge, arXiv's `arxiv:doi` analog ADR 0038, PubMed's biomedical sibling ADR 0065), unpublished preprints edgeless; `biorxiv`/`medrxiv → paper`; degrades to metadata-only | 0068 |
| pdf | `sources/pdf.py` | direct download + `pypdf` text and document metadata | `/Title`-or-filename → `title`, `/Subject` → `summary`, the document → `media`; non-PDF payload fails, textless PDF degrades to metadata-only | 0013 |
| hackernews | `sources/hackernews.py` | keyless Firebase API, one request, stdlib only | text posts → body + lead `summary`; link posts → "N points, M comments" + bare article URL in `links`; degrades to metadata-only; `kids` kept in `raw_text` | 0031 |
| stackexchange | `sources/stackexchange.py` | keyless Stack Exchange API, stdlib only; optional second GET for answers | one adapter for the whole network (site in `source_id`); question + accepted-first top answers → `extracted_text`; tags → `concepts`; degrades to question-only | 0033 |
| pypi | `sources/pypi.py` | keyless PyPI JSON API, stdlib only | latest-release metadata; description (README) → searchable text; keywords → `concepts`, classifiers → `tags`, project URLs → `links` (package↔repo edge); `pypi → tool`; degrades to metadata-only | 0034 |
| npm | `sources/npm.py` | keyless registry JSON, stdlib only; capped `dist.tarball` GET when the packument has no README | latest-release metadata; README from packument or, when empty (common for high-traffic packages), its tarball → searchable text; keywords → `concepts` (no classifier analog, `tags` empty); homepage + normalized repository → `links` (package↔repo edge); `npm → tool`; degrades to metadata-only | 0035 |
| crates | `sources/crates.py` | keyless crates.io JSON API + capped `.crate` tarball GET for the README | displayed-version metadata; raw README from the `.crate` tarball → searchable text; keywords → `concepts`, curated category taxonomy → `tags`; homepage/docs/normalized repository → `links` (crate↔repo edge); `crates → tool`; degrades to metadata-only | 0036 |
| crossref (`doi.org`, Crossref agency) | `sources/crossref.py` via `sources/doi.py` dispatch | keyless Crossref DOI metadata API, stdlib only | registered work metadata for a `doi.org` DOI (folded lowercase identity); JATS abstract → plain `summary` (no full text, so no `extracted_text`); `subject` → `concepts`, `type`+venue → `tags`; publisher landing page → `links` (`reference` DOIs dropped); `crossref → paper` like arXiv; degrades to metadata-only | 0037 |
| crossref (`doi.org`, DataCite agency) | `sources/datacite.py` via `sources/doi.py` dispatch | keyless DataCite DOI metadata API, stdlib only | fetch-time fallback when Crossref 404s a DOI (datasets/software/etc.); JSON:API `attributes` → titles+subtitle, creators "Given Family", `Abstract` description → `summary` (no full text), `subjects` → `concepts`, DataCite date precedence, `resourceTypeGeneral`+`resourceType`+publisher → `tags`, landing + container-DOI `links` (cross-source edge); `resourceTypeGeneral` → `provenance.resource_type` drives classification (`Dataset → dataset`, `Software`/`Model` → `tool`, text types → `paper`, `Image`/`Sound` → `media`); source stays `crossref`, `provenance.adapter="datacite"` is honest; degrades to metadata-only | 0045 |
| pubmed | `sources/pubmed.py` | keyless NCBI E-utilities efetch API, stdlib ElementTree, one request | the biomedical literature, the arXiv/Crossref paper sibling (PMID identity); MeSH `DescriptorName`s → `concepts` (the curated controlled vocabulary, github-topics/arXiv-taxonomy role; qualifiers dropped), author `Keyword`s the fallback for not-yet-MEDLINE-indexed records; structured abstract → `summary` (no full text, so no `extracted_text`, the Crossref shape); publication types + journal venue → `tags`; date precedence electronic `ArticleDate` → journal `PubDate` (month-name/year-only/`MedlineDate` parsed) → history; article DOI → `doi.org` `link` (PubMed↔Crossref paper edge, ADR 0038's biomedical analog); `pubmed → paper`; degrades to metadata-only | 0065 |
| rfc | `sources/rfc.py` | keyless RFC Editor JSON view (`rfc-editor.org/rfc/rfc<N>.json`) + the `.txt` spec body, stdlib only | IETF technical standards, a content type with no prior home; host-restricted shape detection (RFC Editor + `datatracker`/`tools`/`ietf`, only `rfc<digits>` claimed, drafts/WG/org → `web`); integer-number identity, leading zeros stripped; `keywords` → `concepts` (github-topics/MeSH role; whitespace placeholder dropped), maturity `status` title-cased → the one `tag`; abstract → `summary`, the `.txt` spec body fetched + de-paginated → `extracted_text` (the arXiv abstract+PDF split, ADR 0010/0067; classic form-feed/`[Page N]`/running-header pagination stripped, modern unpaginated format passes through; degrades to abstract-only on `.txt` failure); DOI `10.17487/RFC<N>` → `doi.org` `link` (RFC↔Crossref edge), `obsoletes`/`updates` → `rfc-editor.org/rfc/rfc<M>` `link`s (RFC↔RFC lineage; inverse relations not re-emitted); number leads the title; `Month Year` dates padded to first-of-month; `rfc → reference`; degrades to metadata-only | 0066, 0067 |
| packagist | `sources/packagist.py` | keyless Packagist JSON API, stdlib only | Composer package metadata for a `vendor/name` (folded lowercase identity); highest *stable* release picked by ranking the numeric `version_normalized` (no `default_version` pointer, no comparator dep); description → `summary` (no README in the API, so no `extracted_text`); keywords → `concepts`, `type`+SPDX licenses → `tags`; repository/homepage/git source → `links` (package↔repo edge); `packagist → tool`; honestly metadata-only | 0039 |
| rubygems | `sources/rubygems.py` | keyless RubyGems JSON API, stdlib only | gem metadata for a `name` (verbatim, case-sensitive identity like npm); `gems/<name>.json` returns the latest version inline (no version selection); `info` → `summary` (no README in the API, so no `extracted_text`); no keywords so `concepts` empty *by design*, SPDX licenses → `tags`; homepage/source/docs URIs → `links` (gem↔repo edge survives a tagged-tree source URI); `rubygems → tool`; honestly metadata-only | 0040 |
| huggingface | `sources/huggingface.py` | keyless Hub JSON API, stdlib only; second GET for the card README | one adapter for models + datasets + Spaces (kind in `source_id`, a `_PATH_SEGMENT` map routes the endpoint); card README (frontmatter stripped) → `extracted_text`, its lead paragraph → `summary` (dataset `description` the fallback); concepts from structured fields (`pipeline_tag`/`task_categories` + `cardData.tags`), *not* the flat tag soup; framework facet + license → `tags` (`library_name` for a model, `sdk` for a Space); `arxiv:`→arxiv.org `link` (model↔paper edge), `dataset:`/`base_model:`→Hub `link`, a Space's `cardData.models`/`datasets`→Hub `link` (space↔model/dataset edge); `model`/`space → tool`, `dataset → dataset`; degrades to metadata-only | 0041, 0043 |
| lobsters | `sources/lobsters.py` | keyless `lobste.rs/s/<id>.json`, stdlib only, one request | story + tags + the *entire* comment thread in one GET (HN defers comments, SE spends a second GET); `description_plain`/`comment_plain` already plain, no HTML grammar; body + bylined comments (deleted/moderated skipped, all kept) → searchable `extracted_text`; link submission's article → bare `links` (HN pattern), `summary` = body lead else "N points, M comments"; tags → `concepts`; **no category default — unclassified like HN**; degrades to metadata-only | 0046 |
| go | `sources/go.py` | keyless `proxy.golang.org`, stdlib only; second GET for the go.mod | module-path identity (case-sensitive, verbatim; module = path before `@`); `/@latest` → version+time, `/@v/<v>.mod` → the go.mod manifest as searchable `extracted_text`; the sparsest adapter — no description (`summary` None), no keywords (`concepts=()`), no license/classifier facet (`tags=()`); repo `link` from `Origin.URL` else derived from the module path for known VCS hosts (package↔repo edge); request case-encoded (`X`→`!x`); `go → tool`; degrades to metadata-only | 0042 |
| bluesky | `sources/bluesky.py` | keyless AppView (`public.api.bsky.app`), stdlib only; `resolveHandle` GET for a handle URL, then one `getPostThread` | the open social-post source X couldn't be (IDEAS.md §6 deferred X; its API is now paywalled); a handle URL resolves to the DID the AT-URI needs (a `did:` URL skips it), then one call returns the post + its reply tree; post text + bylined replies (deleted/blocked/empty skipped) → `extracted_text`, image alt text the body of a textless post; external card / quoted post / inline `#link` facets → `links` (post↔post + cross-source edges), images → `photo` media, `#hashtag` facets → `concepts`; synthesized title, `summary` = lead else alt else card title else engagement status; **no category default — unclassified like HN/Lobsters**; degrades to metadata-only | 0048 |
| mastodon (incl. GoToSocial, Pleroma/Akkoma) | `sources/mastodon.py` | keyless Mastodon REST API, stdlib only; `GET /api/v1/statuses/<id>` then optional `.../context` | the Fediverse Mastodon-API family on one adapter, matched by URL *shape* not host (no shared host to key on); HTML `content` → text via stdlib `HTMLParser` (no trafilatura), flat `descendants` → bylined replies; card + body links → `links` (mentions/hashtags excluded), images → `photo`/videos → `thumbnail` media, `tags[].name` → `concepts`; `spoiler_text` content warning leads the body, a boost unwraps; synthesized title, `summary` = lead else alt else card title else engagement status; **no category default**; degrades to metadata-only | 0049, 0050 |
| misskey (incl. Sharkey, Firefish, Foundkey) | `sources/misskey.py` | keyless Misskey API, stdlib only; `POST /api/notes/show` (JSON body) then optional `notes/children` | the Fediverse Misskey-API family — *not* Mastodon-compatible, so its own source/adapter; the first POST-bodied adapter (new `http.post_json`); MFM `text` is already plain (no HTML parser, Lobsters' economy), links scanned from the text + a quote-renote's note → `links` (post↔post + cross-source edges), `files` → `photo`/video-`thumbnail` media (`comment` alt searchable), bare-string `tags` → `concepts`, `cw` content warning leads the body, a pure renote unwraps; synthesized title, `summary` = lead else alt else engagement status; **no category default**; degrades to metadata-only | 0051 |
| lemmy (Lemmy backend) | `sources/lemmy.py` via `sources/threadiverse.py` dispatch | keyless Lemmy API v3, stdlib only; `GET /api/v3/post` then optional `/comment/list` | the federated link aggregator (HN/Lobsters' cousin) — *not* Mastodon/Misskey-compatible, so its own source/adapter, the third Fediverse split by client API; plain GET so `http.get_json` serves it; a *real* `name` title (an aggregator entry, not synthesized) and `ap_id` canonical; flat comments sorted into thread pre-order by integer `path`, bylined like Lobsters (deleted/removed skipped); link post `url` → article `link`, text post `body` the content, image post `url` → `photo` media (told by `url_content_type`), `thumbnail_url` → preview; body URLs + `cross_posts` `ap_id` → `links` (cross-source + post↔post edges); community → one `concept`; `summary` = body lead else "N points, M comments"; **no category default — unclassified like HN/Lobsters/social**; degrades to post-only | 0052 |
| lemmy (PieFed backend) | `sources/piefed.py` via `sources/threadiverse.py` dispatch | keyless PieFed `/api/alpha`, stdlib only; `GET /post` then optional `/comment/list` | PieFed shares Lemmy's exact `/post/<digits>` URL, so it can't be its own *detected* source; but its API is its own (`/api/alpha`, `post.title`/`creator.user_name`/`comment.body`/`post_type` not Lemmy's `name`/`name`/`content`/`url_content_type`), so it can't ride Lemmy's *adapter* either — its own adapter on Lemmy's source, resolved at fetch time by the `threadiverse` dispatcher (Lemmy first, PieFed fallback — the `doi.py` pattern); identity stays `lemmy:<host>/<id>`, `provenance.adapter="piefed"` honest (the DataCite-vs-Crossref split); otherwise mirrors Lemmy — image by `post_type=="Image"`, cross-posts (no `ap_id`) → same-instance `/post/<id>` links, `summary` = body lead else "PieFed discussion: N points, M comments"; `Poll`/`Event` payloads kept in `raw_text`; degrades to post-only | 0053 |
| discourse | `sources/discourse.py` | keyless Discourse `.json` view, stdlib only; `GET /t/<id>.json` — topic **and** its first page of posts in *one* request | the centralized *forum* sibling of the aggregators, and the **first non-Fediverse host-less source** (matched by `/t/<slug>/<id>` shape on any unclaimed host, slug dropped from identity, the weak `t` literal making the all-digits id carry the weight); a *real* `title` (a forum thread, not a synthesized post), opening post → body, later posts → bylined `### Replies` (mod-action/whisper/deleted skipped); HTML `cooked` → text via stdlib `HTMLParser` (no trafilatura); `tags` → `concepts`, outbound `details.links` (internal/reflection filtered) → `links` (cross-source edges), `image_url` → `thumbnail` media; `summary` = OP lead else "N replies, M likes"; **no category default — unclassified like HN/Lobsters/Lemmy/social**; validates `post_stream` so a misdetect raises rather than mis-scrolls; long threads first-page-only (full `stream` in `raw_text`) | 0054 |
| devto | `sources/devto.py` | keyless `dev.to/api/articles/<user>/<slug>`, stdlib only, one request | the developer-blogging platform a `web` scrape left a concept-less island; one GET returns the whole article so `tags` → `concepts` joins it to the KB graph (github-topics pattern), `tags` field empty (no license/classifier facet); identity `<user>/<slug>` folded lowercase (Forem mints lowercase, case-sensitive API only resolves it — the gitlab/bitbucket fold); the URL handle is the author *or organization*, so `author` reads the byline `user.name` (the person); `body_markdown` already Markdown (no HTML grammar, Lobsters' economy) → `extracted_text`, `description` → `summary` (→ lead → engagement → None), cross-post `canonical_url` → `links` (cross-source edge) while the scroll's canonical stays the dev.to permalink, `cover_image`/`social_image` → `thumbnail` media; **no category default — unclassified like HN/Lobsters/Bluesky**; self-hosted Forem deferred; degrades to metadata-only | 0061 |

X items arrive through `scrolls import fieldtheory` rather than a fetch
adapter (ADR 0009): the Field Theory JSONL cache is the raw-record spine
(each line preserved verbatim in `raw_text`), and classified pages join
`category`/`domain` by tweet id.

Shared HTTP transport lives in `src/scrolls/sources/http.py` (stdlib
urllib, descriptive User-Agent). Adapters take the fetcher as an
injectable parameter, which is why no test touches the network.

### Adding a new adapter

The pattern every existing adapter followed:

1. Map the URL shape in `sources/detect.py` and cover it in
   `tests/test_detect.py`. Decide what the stable `source_id` is.
2. Write `sources/<name>.py` exposing
   `fetch_item(item, fetcher=...) -> ScrollItem`. Fill what the platform
   offers; raise `FetchError` for anything else. Degrade gracefully when
   an enrichment (transcript, README, PDF text) fails — a metadata-only
   scroll beats no scroll.
3. Register it in `FETCH_ADAPTERS` (`sources/__init__.py`).
4. Test against recorded fixture payloads with an injected fetcher
   (`tests/test_<name>.py`) — never the live API.
5. If the platform implies a category, add a platform rule to
   `classify.py` (e.g. arxiv → paper, github → project; ADR 0004).
6. Note the adapter in `README.md` and record non-obvious choices in an
   ADR (`docs/adr/`).

## Downstream engines

Each engine is deterministic today, with an explicit slot where an LLM
version can join later — deterministic-first is a deliberate, recurring
choice (ADRs 0004, 0005).

- **Classification** (`classify.py`, ADR 0004) — rules engine
  (`rules-v1`), layer one of IDEAS.md §8's "rules first → optional LLM
  second → user overrides always win". Precedence: curated platforms,
  then title patterns, then URL shape, then youtube → media. Unmatched
  items honestly stay unclassified. Batch runs never overwrite an
  existing category; `classify <id>` explicitly reclassifies
  (`tests/test_classify.py`).
- **LLM classification** (`classify_llm.py`, ADR 0015) — layer two
  (`llm-v1`), run explicitly via `classify --engine llm`: one Anthropic
  Messages call per item with structured outputs pinning `category` to
  the full IDEAS.md §8 vocabulary, plus `domain` and model `concepts`
  merged after the platform-curated ones. `--batch` (ADR 0022) sends
  the same requests as one Message Batches submission at half the
  per-token price, polled until it ends on the shared transport
  (`llm.anthropic_complete_batch`, now also the concept engine's batch
  path — ADR 0032); both per-item and batch share one validation path.
  The completers are injectable,
  so tests stay offline (`tests/test_classify_llm.py`); the SDK is
  imported lazily, and missing credentials abort the batch
  (`LLMAuthError`) while per-item API failures don't. `config.toml`'s
  `[classify]` section (`config.py`, ADR 0016) makes the engine and
  model sticky per library; the `--engine` flag and `$SCROLLS_LLM_MODEL`
  always win (`tests/test_config.py`).
- **User overrides** (`overrides.py`, ADR 0018) — `scrolls set` is
  IDEAS.md §8's third layer: it writes exactly the fields the engines
  write (`category`, `domain`, `tags`, `concepts`), free-form, with
  empty values clearing a field back to the batch-classifiable pool. A
  set category sticks because batch runs never overwrite one
  (`tests/test_overrides.py`).
- **Search** (`search.py`) — FTS5 BM25 with title weighted over summary
  over body. Query tokens are quoted and AND-ed, so arbitrary agent
  input never hits FTS5 syntax errors. Optional `source`/`category`/`stage`
  facets scope the ranked match — they AND with the FTS match and leave
  the BM25 order untouched, mirroring `scrolls list`'s filters (`""`
  category selects unclassified), so a search can ask "papers about X" over
  30+ heterogeneous sources, not just "anything mentioning X" (ADR 0058,
  `tests/test_search.py`). Two further facets, `tag` and `concept`, scope
  by *membership* in the JSON list columns rather than single-column
  equality: a `json_each` `EXISTS` subquery with `tag` lowered and
  `concept` slugified — the `scrolls related` comparisons, via two SQL
  functions registered on the connection (`items.register_facet_functions`)
  — so the filtering stays in SQL and `search`'s `LIMIT` is still correct
  (ADR 0059). The clause builder (`items.tag_concept_filters`) is shared by
  `search_items` and `list_items`.
- **Related items** (`related.py`, IDEAS.md §10) — explainable scoring,
  no LLM: link connections in either direction (resolved through source
  detection, so `arxiv.org/pdf/X` finds item `arxiv:X`, an arXiv
  preprint's published `doi.org` link finds its `crossref:<doi>` paper —
  ADR 0038 — and a Hugging Face model's `arxiv:` tag finds the
  `arxiv:<id>` paper it introduced — ADR 0041 — while a Space finds the
  model it serves and the dataset it draws on — ADR 0043, a DataCite
  dataset finds the Crossref paper it is part of through its container DOI
  — ADR 0045, and a PubMed record's article `doi.org` link finds its
  `crossref:<doi>` paper — ADR 0065, the biomedical analog of the
  arXiv preprint↔published edge — while an RFC's DOI link finds its
  `crossref:<doi>` paper and its `obsoletes`/`updates` links find the RFCs it
  supersedes — ADR 0066, the standards-lineage analog), shared concepts
  (merged by slug), shared tags, same category/domain as weak
  corroboration. Every hit carries its `reasons`
  (`tests/test_related.py`).
- **Link graph** (`graph.py`, ADR 0044) — `scrolls graph` resolves *every*
  item's links into directed edges across the whole library, the
  whole-library complement to `related`'s per-item lens. The link-resolution
  primitives (`link_tokens`, `identity_tokens`) live here and `related.py`
  imports them, so both views agree on what a link resolves to. The build
  indexes every item's identity tokens once then probes with each link
  (linear, not the per-pair O(n²)); nodes are the connected items by
  default (`--all` adds isolates), `stats.items` the library total and
  `stats.clusters` the number of 2+-member components. The
  same `{nodes, edges, stats}` payload backs the MCP `get_link_graph` tool
  (`tests/test_graph.py`). `connected_components` partitions the graph into
  clusters (edges undirected for the partition, the directed edges kept) and
  `graph_over` builds a graph over a *given* item set — both feed the KB's
  `library/graph.md` page (ADR 0062), the browsable form of the same
  structure.
- **Works** (`works.py`, ADR 0069) — `scrolls works` clusters the items
  that are *the same scholarly work* (an arXiv preprint, its published
  Crossref article, a PubMed record, a bioRxiv/medRxiv preprint) keyed by
  the **DOI that names the work**, so a library holding one work as several
  near-duplicate `paper` entries can consolidate them. A representation
  contributes a work's DOI when its `source_id` is itself a DOI
  (`crossref`, `biorxiv`/`medrxiv` — the `10.1101/<accession>` accession is
  one) or it carries a `doi.org` link (resolved through the same
  `detect_source` + `normalize_url` path the graph uses). Where the link
  graph connects two items only when one's link resolves to an item
  *already present*, `works` clusters by the shared DOI identity, so two
  representations bind even when the `crossref` item that would link them is
  absent — a cluster the graph structurally cannot form. Only 2+-member
  works are reported by default (`--min N`); the `{works, stats}` payload
  carries the same node shape and `stats.items` total as `graph`, and
  `works_over(items)` mirrors `graph_over(items)` so the KB works page
  (`library/works.md`, ADR 0070) reuses it over rendered items
  (`tests/test_works.py`).
- **KB compiler** (`kb.py`, ADR 0005) — rebuilds `library/index.md`,
  `library/graph.md`, `library/works.md`, plus per-source, per-category,
  per-concept, and per-tag pages from scratch each run so stale groups can't
  linger; other files under `library/` are left alone. Concept pages merge spellings by
  slug, and lead with a stored synthesized summary when the LLM concept
  engine has written one — the store (`concept_summaries`) lives on the
  compiler's side so a plain `scrolls kb` includes summaries with no model,
  key, or network. Tag pages (`group_tags`, ADR 0064) are the browsable
  complement to the `--tag` query facet (ADR 0059), grouping items by tag
  **case-insensitively** (the facet's rule, not concepts' slug merge — so
  `MIT`/`mit` are one page, `C++`/`C#` two despite a shared slug, the page
  filenames disambiguated by a numeric suffix); they carry a **Related
  Tags** co-occurrence section sharing the extracted `_co_occurring` core
  with Related Concepts, and a `tags` count joins the compile summary.
  `graph.md` is the browsable form of `scrolls graph`'s link structure
  (ADR 0062): the rendered scrolls that link to one another, grouped into
  clusters (`graph.connected_components(graph_over(rendered_items))`) and
  rendered as adjacency lists, with the index linking to it and the compile
  summary reporting a `clusters` count; built over rendered items only so
  every link on the page resolves to a scroll file (`tests/test_kb.py`).
  `works.md` is the parallel browsable form of `scrolls works`'s DOI
  clustering (ADR 0070): `works_over(rendered_items)` grouped under each work's
  DOI, every representation linking to its scroll, the index linking to it and
  the compile summary reporting a `works` count — the rendered-only scope
  meaning the page's work count can fall below `scrolls works`'s whole-library
  count, the same divergence `graph.md` has from `scrolls graph`.
  Each concept page also ends with a **Related Concepts** section
  (`related_concepts`, ADR 0063) — the concepts that co-occur on its member
  scrolls, ranked by shared-scroll count — the deterministic concept-graph
  complement to `graph.md`, kept on the concept pages rather than as
  `scrolls graph` edges so concept cliques don't swamp the sparse link edges
  (ADR 0044/0047/0062 deferred concept edges in the link graph for that
  reason).
- **LLM concept engine** (`kb_llm.py`, ADR 0025) — IDEAS.md §9's fancy
  version, run via `kb --engine llm`: a model synthesizes how each
  concept with 2+ member scrolls shows up across them, writing the
  store the compiler reads. Incremental by members fingerprint —
  unchanged concepts cost nothing on re-run, summaries for dissolved
  concepts are pruned. `--batch` (ADR 0032) synthesizes every concept
  needing (re)generation in one Message Batches submission at half the
  per-token price — identical eligibility, skipping, pruning, result
  shape, and per-concept failure isolation, sharing one validation
  (`_parse_summary`) and save path with the per-call transport. Failure
  semantics mirror classification: per-concept failures still compile,
  missing credentials abort but keep what's saved (`tests/test_kb_llm.py`,
  `tests/test_kb.py`). Both LLM engines share one transport (`llm.py`):
  the structured-output call (`anthropic_complete`), its Message Batches
  twin (`anthropic_complete_batch`, the shared poll loop both `--batch`
  paths bind their schema onto — ADR 0022, ADR 0032), credential
  handling, the `LLMError`/`LLMAuthError` hierarchy, and the tier's
  model choice (`$SCROLLS_LLM_MODEL` > `[classify] llm_model` >
  default).
- **Feed sync** (`feeds.py`, ADR 0017) — `follow` validates an RSS
  2.0/Atom feed by fetching it once (stdlib ElementTree, no feedparser)
  and stores the subscription; `sync` polls each feed and registers new
  entry URLs at stage `detected` through `detect_source` +
  `make_item_id`, so dedupe and adapter routing are the same as
  `scrolls add`; each entry's feed title names the new item and its
  entry date (normalized to UTC ISO 8601) seeds `published_at`, with
  fetch replacing both only by the source's own values (ADR 0021).
  Polls are conditional GETs (ADR 0019): a full
  response's `ETag`/`Last-Modified` land on the subscription and a 304
  reports the feed `unchanged` without re-parsing; follow never stores
  validators, so the first sync always sees the feed's current entries.
  YouTube playlist/channel URLs map to their public
  feeds syntactically; one dead feed fails its subscription, never the
  batch (`tests/test_feeds.py`, `tests/test_http.py`).
- **Media capture** (`media.py`, ADR 0011) — downloads items' media
  refs to `media/<source>/<id-slug>-<n><ext>`, records each file's
  root-relative `path` on the ref (reused on re-capture, so locations
  are stable), and re-renders the scroll so frontmatter points at local
  files. Batch runs capture only refs missing from disk; `media <id>`
  re-captures explicitly (`tests/test_media.py`).
- **Context bundles** (`context.py`, IDEAS.md §11) — `scrolls context`
  emits Markdown (the bundle *is* the artifact agents drop into
  context), unlike the data commands; errors stay JSON on stderr. Each
  excerpt carries item id, source, and scroll path for follow-up. Beyond
  the FTS matches, a **Connected scrolls** section pulls in items linked
  to or from those matches through the link graph (`build_graph`, the
  same edges `scrolls graph` reports) but not themselves keyword hits —
  the model↔paper, package↔repo, and dataset↔parent-work edges of
  ADRs 0034–0046 surfacing where an agent reads them, not only in
  `scrolls related`/`graph` (ADR 0047). Link-only and high-precision
  (concept/tag signal deferred), ranked by centrality, capped at the
  match count, and omitted when nothing connects; the MCP
  `get_context_bundle` inherits it through `build_context`
  (`tests/test_context.py`). The bundle takes the same
  `source`/`category`/`stage` facets as search (ADR 0058), plus the
  `tag`/`concept` membership facets (ADR 0059): they narrow the
  underlying ranked match — and so the connected-scrolls graph — so a
  bundle can cover "what the *papers* tagged efficient say about X"; a
  scoped bundle names its facets in the title (`category=unclassified` for
  the empty-string pool, `tag`/`concept` verbatim) to stay self-documenting
  once dropped into context.
- **Agent install** (`agents.py`, ADR 0006) — writes instruction files
  under `<root>/agents/` only, never into another tool's config tree
  (`tests/test_agents.py`).
- **Doctor** (`doctor.py`, ADR 0026) — `scrolls doctor` diagnoses drift
  between the index and the file tree: duplicate url-hash items left by
  pre-normalization URLs (ADR 0023's deferred debt), recorded scroll
  files missing on disk, captured media files gone, orphan scroll files,
  FTS desync. `--fix` repairs only what is safe offline — merges each
  duplicate group atomically into the id a clean re-add would mint
  (`items.replace_items`), rewrites missing scrolls from the index,
  rebuilds FTS — and exits 0 only when the library ends fully
  consistent, so it works as a cron-able health probe. Missing media
  stays `scrolls media`'s job; orphan files are never deleted
  (`tests/test_doctor.py`).
- **Removal** (`remove.py`, ADR 0027) — `scrolls rm` deletes an item's
  files (scroll, captured media) and then its row, in that order, so an
  interrupted removal leaves a re-runnable item rather than orphan
  files; the FTS delete trigger keeps search in sync. Refs are ids or
  URLs resolved through the same normalize → detect → mint chain as
  `add`, and every recorded path is validated against the library root
  before anything is deleted. No tombstone: a still-followed feed
  re-registers the entry on the next sync. Deliberately not exposed
  over MCP, like doctor (`tests/test_remove.py`).
- **MCP server** (`mcp_server.py`, ADR 0014, ADR 0020) — `scrolls mcp`
  serves the same engines to MCP clients over stdio: plain sync tool
  functions (`get_context_bundle`, `search_scrolls`, `list_scrolls`,
  `get_scroll`,
  `get_related_scrolls`, `get_link_graph`, `get_works` (ADR 0069 —
  same-work clusters by DOI), `get_concept_page`,
  `get_tag_page` (ADR 0064 — tag matched case-insensitively, slug
  collisions resolved by the page's `# Tag:` heading),
  `list_sources`,
  `ingest_url`, the feed subscription tools `follow_feed`,
  `unfollow_feed`, `list_feed_subscriptions`, `sync_feeds`, plus
  `compile_library`) registered
  on FastMCP, which derives schemas from type hints. Read tools mirror
  CLI conventions — empty library, empty results; unknown id, tool
  error — `sync_feeds` shares the CLI's batch semantics through
  `feeds.sync_many`, and `compile_library` is the deterministic
  compiler only: LLM summary generation (ADR 0025) stays a CLI step so
  no MCP tool ever makes paid API calls implicitly (`tests/test_mcp.py`).

## Interface conventions

The per-command contract — output keys, exit-code semantics, error
envelopes, with captured real output — lives in `docs/cli.md`. The
recurring rules:

- **JSON on stdout** for every data command; errors as JSON on stderr
  with exit 1. Two deliberate exceptions emit Markdown: `context` (the
  bundle is the artifact) and the scroll/KB files themselves.
- **CLI is one module** (`cli.py`): argparse subcommands, each a thin
  `cmd_*` function over the library modules. The CLI owns process
  concerns (JSON encoding, exit codes, loading `config.toml` — ADR
  0016); engines stay importable and
  testable without it (`tests/test_cli.py` covers the seams). The
  add/ingest chain lives in `src/scrolls/pipeline.py` so the CLI and
  the MCP server share one implementation (ADR 0014).
- **Item refs are ids or URLs** (ADR 0028): every command that takes an
  item id also accepts the item's URL, resolved by
  `pipeline.resolve_item_id` through the same normalize → detect → mint
  chain `add` registers with, so the saved URL is always a valid handle
  (`tests/test_pipeline.py`).
- **Dependency posture** (ADR 0001): stdlib first; a third-party package
  must buy its feature something substantial. Today's full list:
  `trafilatura` (web), `youtube-transcript-api` (youtube), `pypdf`
  (arxiv and pdf), `mcp` (the protocol server, imported only by
  `scrolls mcp`), `anthropic` (the LLM tier, imported only by
  `scrolls classify --engine llm` and `scrolls kb --engine llm`) — see
  `pyproject.toml`.
- **No network in tests**: every adapter takes an injectable fetcher;
  fixtures are recorded payloads. The suite runs in under a second.

## Status and known next steps

All five IDEAS.md §14 MVP passes have a working first version: library
skeleton, URL → Markdown for the §6 trio plus github/arxiv/x-via-import,
FTS5 search, two-layer classification (rules + LLM, ADRs 0004/0015), and
the compiled KB with context bundles and agent install.

Next steps already identified in decision records, in no required order:

- **Social posts** — the Bluesky adapter (ADR 0048) reaches the keyless
  social-post source IDEAS.md §6 deferred X for, on the open network; the
  Mastodon adapter (ADR 0049) reaches the federated Fediverse by URL
  *shape* rather than host — now serving its API-compatible forks
  GoToSocial and Pleroma/Akkoma on the same source and fetch adapter, since
  they expose the identical `/api/v1/statuses` surface and only their URL
  routes and id formats differ (ADR 0050); and the Misskey adapter
  (ADR 0051) reaches the Misskey-family software (Sharkey, Firefish,
  Foundkey) on its `/notes/<id>` shape. Misskey corrected the earlier
  assumption that it would be one more mastodon shape: it speaks its own
  `POST /api/notes/show` API, not Mastodon's, so the Fediverse is now
  covered by *two* adapters split by client API, not host — and a future
  Fediverse software with a third API (a Lemmy/PieFed post) would split off
  the same way. `x`
  itself still arrives only through `import fieldtheory` (ADR 0009): a
  native `x` fetch adapter would let a pasted or synced tweet URL enrich
  on its own, but X's read API is now paywalled, so it cannot be keyless
  like every other adapter. The remaining tightening is DID-canonical
  Bluesky / home-instance-canonical Mastodon/Misskey identity (resolve a
  post's true id at fetch time so it dedupes across the routes that reach
  it — ADRs 0048–0051 all defer it as the only fetch-time id rewrite any
  adapter would do).
- **Discussion aggregators and forums** — the federated link aggregators
  Lemmy (ADR 0052) and PieFed (ADR 0053) and the centralized forum software
  Discourse (ADR 0054) extend the discussion family beyond the centralized
  Hacker News (ADR 0031) and Lobsters (ADR 0046). Discourse is the first
  *non-Fediverse* host-less source — shape-detected by its `/t/<slug>/<id>`
  topic URL the way the Fediverse sources are — so the technique is now
  general, not ActivityPub-specific. **Mbin** (the kbin fork) was the named
  next aggregator (ADRs 0052/0053), but its read API is OAuth-gated — its
  `security.yaml` grants no anonymous `/api/entry`, and live instances 401/403
  an unauthenticated read — so it cannot join as a keyless adapter without a
  client-credentials token dance or an ActivityPub `apId` object fetch; it is
  deferred to its own ADR if that posture is ever taken (ADR 0054). A future
  Lemmy-shaped aggregator with a *distinct* URL would detect separately like
  Discourse; one sharing `/post/<digits>` would slot into the `threadiverse`
  dispatcher like PieFed.
- **More code hosts** — the GitHub adapter (ADR 0007) got siblings in
  GitLab (ADR 0055, the second major host), Gitea/Forgejo (ADR 0056, the
  third — Codeberg and gitea.com), and Bitbucket (ADR 0057, the fourth — "the
  remaining big one"), so the four big hosts are now covered. The family spans
  both identity shapes: github/gitlab/**bitbucket** are host-scoped with a
  single fixed API host (Bitbucket Cloud is one service, so it took github's
  flat `<workspace>/<repo>` — folded lowercase like gitlab — *not* gitea's
  host-in-id), while Gitea introduced the host-in-identity shape
  (`gitea:<host>/<owner>/<repo>`) a self-hosted-across-many-hosts platform
  needs: the instance host rides in the `source_id` because the API lives on
  each host, so two extensions are now cheap detection changes rather than
  adapter rewrites. *More Gitea/Forgejo hosts* (self-hosted Codeberg-likes)
  could join via a configured host allowlist, the adapter already host-carrying.
  *Gitea's cousin Gitea-API hosts* aside, *self-hosted GitLab* (deferred in
  ADR 0055 because a bare repo root carries no shape tell) would want the same
  host allowlist or an explicit source hint. *Bitbucket Server/Data Center*
  (the self-hosted product, a different `/rest/api/1.0/` API on arbitrary hosts)
  would be its own adapter, not a detection-only change like a new gitea host.
- **Two-phase batch submit/collect** — both `--batch` paths (ADR 0022,
  ADR 0032) block and poll until the batch ends. If a real batch ever
  outgrows a terminal wait, the persisted-batch-id design those ADRs
  weighed and deferred has an obvious home in the shared `llm.py`.
- **More package registries** — the PyPI adapter (ADR 0034) set the
  pattern and npm (0035), crates.io (0036), Packagist (0039), RubyGems
  (0040), and Go modules (0042) followed it, completing the family across
  Python, JavaScript, Rust, PHP, Ruby, and Go. Go was the sparsest — the
  `proxy.golang.org` `@latest` carries no description, keywords, or
  license, so `summary`/`concepts`/`tags` are all empty and the go.mod
  manifest is the searchable content. Packagist's comparator-free "highest
  stable `version_normalized`" selection (ADR 0039) and Go's request
  case-encoding (`X`→`!x`, ADR 0042) are the techniques a future
  JSON-metadata registry can reuse.
- **More DOI registration agencies** — Crossref (ADR 0037) and DataCite
  (ADR 0045) now share the `doi.org` detection through the `doi.py`
  fetch-time dispatch (Crossref first, DataCite fallback). A smaller
  agency (mEDRA, JaLC, the Korea/China RAs) that publishes keyless
  metadata could join the same dispatch without a new URL shape — and a
  DOI-RA pre-lookup (`doi.org/doiRA/<doi>`) would replace the wasted
  Crossref 404 a DataCite fetch currently pays, if that latency matters.
- **Cross-source `paper` enrichment** — arXiv and its published Crossref
  version now relate through the `arxiv:doi` link (ADR 0038); a PubMed
  record relates to its Crossref DOI the same way (ADR 0065); and a
  bioRxiv/medRxiv preprint relates to its published-journal DOI the same way
  again (ADR 0068) — so the biomedical literature and both major
  preprint servers join the paper graph too, with up to *four*
  representations of one work potentially in the library at once (an arXiv
  or bioRxiv/medRxiv preprint, a PubMed record, the published DOI).
  `scrolls works` (ADR 0069) delivers the consolidation view: it
  clusters those representations by the shared DOI that names the work —
  catching same-work groups even when the binding Crossref item is absent,
  which the link graph cannot — and `library/works.md` (ADR 0070, the
  `library/graph.md` analog, fed by the same `works_over(items)`) now makes
  that clustering a browsable KB page. The remaining step is the deeper
  KB-level *merge*: collapsing a work's near-duplicate `paper` entries so the
  category/source pages show one consolidated entry rather than several,
  alongside the reverse enrichment from richer Crossref `relation` data.
