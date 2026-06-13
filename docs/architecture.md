# Scrolls Architecture

How the implemented system works today, with pointers into the code and
tests that prove each claim. For the product vision and design brainstorm
see `IDEAS.md`; for the rationale behind individual decisions see the
ADRs indexed at `docs/adr/README.md`.

Everything below describes code on this branch, verified by
`uv run pytest` (927 tests at the time of writing). The docs themselves
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
  library/       # compiled KB: index.md, sources/, categories/, concepts/
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
   host tables map to `youtube`, `wikipedia`, `github`, `arxiv`, `x`,
   `hackernews`, the `stackexchange` network (every site's question
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
   `crossref` (a `doi.org`/`dx.doi.org` DOI link, the DOI folded
   lowercase as `source_id` since DOIs are case-insensitive), and
   `huggingface` (model and dataset repo pages on `huggingface.co`/`hf.co`,
   the repo *kind* in the `source_id` as `model:<org>/<name>` or
   `dataset:<...>` so one adapter serves both API endpoints — the Stack
   Exchange shape — the id kept verbatim since the Hub is case-sensitive,
   subpages deduped to the two-segment repo, site routes and `spaces`
   carrying no fetchable repo); `.pdf`
   paths map to `pdf`; everything else is `web`. A
   known source with `source_id=None` means the adapter resolves
   identity at fetch time (`tests/test_detect.py`).
2. **Fetching** — a function `ScrollItem -> ScrollItem` that fills in
   content and returns the item at stage `fetched`, raising `FetchError`
   on any failure (`src/scrolls/sources/__init__.py`, ADR 0002). The
   `FETCH_ADAPTERS` dict maps source names to these functions. A source
   with no entry (today only `x`) is still registered by `scrolls add`
   but skipped by `scrolls fetch` until its adapter lands.

Implemented fetch adapters, all keyless:

| Source | Module | Method | Distinctive output | ADR |
| --- | --- | --- | --- | --- |
| wikipedia | `sources/wikipedia.py` | MediaWiki action API, stdlib only | page categories → `concepts` | 0002 |
| web | `sources/web.py` | `trafilatura` extraction | readable article text | 0001 (dep policy) |
| youtube | `sources/youtube.py` | oEmbed + optional `youtube-transcript-api` | transcript → extracted text; degrades to metadata-only | 0003 |
| github | `sources/github.py` | REST API + optional README | repo topics → `concepts`; `GITHUB_TOKEN` lifts rate limit | 0007 |
| arxiv | `sources/arxiv.py` | Atom export API + `pypdf` full text | abstract → `summary`, taxonomy codes → `tags`, their display names → `concepts`, PDF → `media`, published `arxiv:doi` → `doi.org` `link` (preprint↔published edge, ADR 0038); degrades to abstract-only | 0008, 0010, 0012, 0038 |
| pdf | `sources/pdf.py` | direct download + `pypdf` text and document metadata | `/Title`-or-filename → `title`, `/Subject` → `summary`, the document → `media`; non-PDF payload fails, textless PDF degrades to metadata-only | 0013 |
| hackernews | `sources/hackernews.py` | keyless Firebase API, one request, stdlib only | text posts → body + lead `summary`; link posts → "N points, M comments" + bare article URL in `links`; degrades to metadata-only; `kids` kept in `raw_text` | 0031 |
| stackexchange | `sources/stackexchange.py` | keyless Stack Exchange API, stdlib only; optional second GET for answers | one adapter for the whole network (site in `source_id`); question + accepted-first top answers → `extracted_text`; tags → `concepts`; degrades to question-only | 0033 |
| pypi | `sources/pypi.py` | keyless PyPI JSON API, stdlib only | latest-release metadata; description (README) → searchable text; keywords → `concepts`, classifiers → `tags`, project URLs → `links` (package↔repo edge); `pypi → tool`; degrades to metadata-only | 0034 |
| npm | `sources/npm.py` | keyless registry JSON, stdlib only; capped `dist.tarball` GET when the packument has no README | latest-release metadata; README from packument or, when empty (common for high-traffic packages), its tarball → searchable text; keywords → `concepts` (no classifier analog, `tags` empty); homepage + normalized repository → `links` (package↔repo edge); `npm → tool`; degrades to metadata-only | 0035 |
| crates | `sources/crates.py` | keyless crates.io JSON API + capped `.crate` tarball GET for the README | displayed-version metadata; raw README from the `.crate` tarball → searchable text; keywords → `concepts`, curated category taxonomy → `tags`; homepage/docs/normalized repository → `links` (crate↔repo edge); `crates → tool`; degrades to metadata-only | 0036 |
| crossref | `sources/crossref.py` | keyless Crossref DOI metadata API, stdlib only | registered work metadata for a `doi.org` DOI (folded lowercase identity); JATS abstract → plain `summary` (no full text, so no `extracted_text`); `subject` → `concepts`, `type`+venue → `tags`; publisher landing page → `links` (`reference` DOIs dropped); `crossref → paper` like arXiv; degrades to metadata-only | 0037 |
| packagist | `sources/packagist.py` | keyless Packagist JSON API, stdlib only | Composer package metadata for a `vendor/name` (folded lowercase identity); highest *stable* release picked by ranking the numeric `version_normalized` (no `default_version` pointer, no comparator dep); description → `summary` (no README in the API, so no `extracted_text`); keywords → `concepts`, `type`+SPDX licenses → `tags`; repository/homepage/git source → `links` (package↔repo edge); `packagist → tool`; honestly metadata-only | 0039 |
| rubygems | `sources/rubygems.py` | keyless RubyGems JSON API, stdlib only | gem metadata for a `name` (verbatim, case-sensitive identity like npm); `gems/<name>.json` returns the latest version inline (no version selection); `info` → `summary` (no README in the API, so no `extracted_text`); no keywords so `concepts` empty *by design*, SPDX licenses → `tags`; homepage/source/docs URIs → `links` (gem↔repo edge survives a tagged-tree source URI); `rubygems → tool`; honestly metadata-only | 0040 |
| huggingface | `sources/huggingface.py` | keyless Hub JSON API, stdlib only; second GET for the card README | one adapter for models + datasets (kind in `source_id`); card README (frontmatter stripped) → `extracted_text`, its lead paragraph → `summary` (dataset `description` the fallback); concepts from structured fields (`pipeline_tag`/`task_categories` + `cardData.tags`), *not* the flat tag soup; `library_name`+license → `tags`; `arxiv:`→arxiv.org `link` (model↔paper edge), `dataset:`→Hub `link` (model↔dataset edge), `base_model:`→Hub `link` (model↔base-model lineage edge); `model → tool`, `dataset → dataset`; degrades to metadata-only | 0041 |

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
  input never hits FTS5 syntax errors (`tests/test_search.py`).
- **Related items** (`related.py`, IDEAS.md §10) — explainable scoring,
  no LLM: link connections in either direction (resolved through source
  detection, so `arxiv.org/pdf/X` finds item `arxiv:X`, an arXiv
  preprint's published `doi.org` link finds its `crossref:<doi>` paper —
  ADR 0038 — and a Hugging Face model's `arxiv:` tag finds the
  `arxiv:<id>` paper it introduced — ADR 0041), shared concepts
  (merged by slug), shared tags, same category/domain as weak
  corroboration. Every hit carries its `reasons`
  (`tests/test_related.py`).
- **KB compiler** (`kb.py`, ADR 0005) — rebuilds `library/index.md` plus
  per-source, per-category, and per-concept pages from scratch each run
  so stale groups can't linger; other files under `library/` are left
  alone. Concept pages merge spellings by slug, and lead with a stored
  synthesized summary when the LLM concept engine has written one — the
  store (`concept_summaries`) lives on the compiler's side so a plain
  `scrolls kb` includes summaries with no model, key, or network
  (`tests/test_kb.py`).
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
  excerpt carries item id, source, and scroll path for follow-up
  (`tests/test_context.py`).
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
  functions (`get_context_bundle`, `search_scrolls`, `get_scroll`,
  `get_related_scrolls`, `get_concept_page`, `list_sources`,
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

- **A native `x` fetch adapter** — `x` items arrive only through
  `import fieldtheory` (ADR 0009); a fetch adapter would let a pasted or
  synced tweet URL enrich on its own, like every other source.
- **Two-phase batch submit/collect** — both `--batch` paths (ADR 0022,
  ADR 0032) block and poll until the batch ends. If a real batch ever
  outgrows a terminal wait, the persisted-batch-id design those ADRs
  weighed and deferred has an obvious home in the shared `llm.py`.
- **More package registries** — the PyPI adapter (ADR 0034) set the
  pattern and npm (0035), crates.io (0036), Packagist (0039), and RubyGems
  (0040) followed it; Go modules are the last obvious registry on the same
  JSON-metadata shape (the `proxy.golang.org` `@latest`/`.info`
  endpoints), a small adapter with no keywords (like RubyGems) and a
  module-path identity. Packagist's comparator-free "highest stable
  `version_normalized`" selection (ADR 0039) is the technique a registry
  with no latest-version pointer can reuse.
- **A DataCite DOI adapter** — Crossref (ADR 0037) covers the published
  literature behind a `doi.org` link, but dataset and software DOIs are
  registered with DataCite and 404 against Crossref. A DataCite adapter
  on the same `doi.org` detection, chosen by a fetch-time fallback, would
  extend DOI coverage to those without a new URL shape.
- **Cross-source `paper` enrichment** — arXiv and its published Crossref
  version now relate through the `arxiv:doi` link (ADR 0038). A natural
  next step is the reverse from richer Crossref `relation` data, or a
  concept-level merge so the preprint and published version share one KB
  concept page rather than two near-duplicate `paper` entries.
