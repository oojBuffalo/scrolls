# Scrolls Architecture

How the implemented system works today, with pointers into the code and
tests that prove each claim. For the product vision and design brainstorm
see `IDEAS.md`; for the rationale behind individual decisions see the
ADRs indexed at `docs/adr/README.md`.

Everything below describes code on this branch, verified by
`uv run pytest` (398 tests at the time of writing). The docs themselves
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
                  │                     ▲                  │
                  │   import fieldtheory┘                  │
                  │                                        ▼
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
  the item to `fetched` (`src/scrolls/sources/`).
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
- `scrolls follow <url>` / `scrolls sync [id]` subscribe to RSS/Atom
  feeds and register their new entry URLs at stage `detected` through
  the same detection/dedupe as `add` — sync discovers URLs, adapters
  still fetch (`src/scrolls/feeds.py`, ADR 0017).

Per-item failures never abort a batch: `fetch`, `md`, `media`, and
`sync` (per subscription) report each failure in their JSON output and
continue (`tests/test_cli.py`).

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
  §3). `meta` carries the schema version (`SCHEMA_VERSION = 5`);
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
  db.sqlite      # items + subscriptions tables + FTS5 index + schema meta
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

## The source adapter model

Two small contracts make every platform the same kind of scroll
(IDEAS.md §1):

1. **Detection** — `detect_source(url) -> DetectedSource(source, source_id)`
   in `src/scrolls/sources/detect.py`. Pure URL inspection, no network:
   host tables map to `youtube`, `wikipedia`, `github`, `arxiv`, `x`;
   `.pdf` paths map to `pdf`; everything else is `web`. A known source
   with `source_id=None` means the adapter resolves identity at fetch
   time (`tests/test_detect.py`).
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
| arxiv | `sources/arxiv.py` | Atom export API + `pypdf` full text | abstract → `summary`, taxonomy codes → `tags`, their display names → `concepts`, PDF → `media`; degrades to abstract-only | 0008, 0010, 0012 |
| pdf | `sources/pdf.py` | direct download + `pypdf` text and document metadata | `/Title`-or-filename → `title`, `/Subject` → `summary`, the document → `media`; non-PDF payload fails, textless PDF degrades to metadata-only | 0013 |

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
  merged after the platform-curated ones. The completer is injectable,
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
  detection, so `arxiv.org/pdf/X` finds item `arxiv:X`), shared concepts
  (merged by slug), shared tags, same category/domain as weak
  corroboration. Every hit carries its `reasons`
  (`tests/test_related.py`).
- **KB compiler** (`kb.py`, ADR 0005) — rebuilds `library/index.md` plus
  per-source, per-category, and per-concept pages from scratch each run
  so stale groups can't linger; other files under `library/` are left
  alone. Concept pages merge spellings by slug (`tests/test_kb.py`).
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
- **MCP server** (`mcp_server.py`, ADR 0014, ADR 0020) — `scrolls mcp`
  serves the same engines to MCP clients over stdio: plain sync tool
  functions (`get_context_bundle`, `search_scrolls`, `get_scroll`,
  `get_related_scrolls`, `get_concept_page`, `list_sources`,
  `ingest_url`, plus the feed subscription tools `follow_feed`,
  `unfollow_feed`, `list_feed_subscriptions`, `sync_feeds`) registered
  on FastMCP, which derives schemas from type hints. Read tools mirror
  CLI conventions — empty library, empty results; unknown id, tool
  error — and `sync_feeds` shares the CLI's batch semantics through
  `feeds.sync_many` (`tests/test_mcp.py`).

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
- **Dependency posture** (ADR 0001): stdlib first; a third-party package
  must buy its feature something substantial. Today's full list:
  `trafilatura` (web), `youtube-transcript-api` (youtube), `pypdf`
  (arxiv and pdf), `mcp` (the protocol server, imported only by
  `scrolls mcp`), `anthropic` (LLM classification, imported only by
  `scrolls classify --engine llm`) — see `pyproject.toml`.
- **No network in tests**: every adapter takes an injectable fetcher;
  fixtures are recorded payloads. The suite runs in under a second.

## Status and known next steps

All five IDEAS.md §14 MVP passes have a working first version: library
skeleton, URL → Markdown for the §6 trio plus github/arxiv/x-via-import,
FTS5 search, two-layer classification (rules + LLM, ADRs 0004/0015), and
the compiled KB with context bundles and agent install.

Next steps already identified in decision records, in no required order:

- **Batched LLM classification** — `classify --engine llm` makes one
  API call per item; the Batches API halves the cost when libraries
  outgrow that (ADR 0015).
