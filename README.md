# Scrolls

Scrolls is a local-first CLI for turning saved and referenced content from many platforms into an agent-readable personal knowledge library.

It is inspired by Field Theory CLI's flow for X/Twitter bookmarks:

1. **Sync** saved content from a platform.
2. **Enrich** each item with source metadata, media/link context, transcripts, article text, or page extracts.
3. **Classify** items by category, domain, concepts, and usefulness.
4. **Store** every item as structured data plus an individual Markdown scroll.
5. **Compile** a Karpathy-style interlinked knowledge base.
6. **Expose** the library to agents such as Claude Code, Codex, and Hermes via CLI commands and skills.

## Initial platform targets

- X/Twitter bookmarks, via Field Theory-compatible concepts
- YouTube videos/playlists, including transcripts and channel metadata
- Wikipedia pages, including summaries, page metadata, and linked concepts
- Web pages/articles, including readable text extraction
- GitHub repositories, issues, releases, and README metadata
- PDFs/arXiv papers, where extractable

## Working product shape

```bash
scrolls sync youtube <url-or-playlist>
scrolls sync wikipedia <page-or-query>
scrolls sync web <url>
scrolls classify
scrolls search "distributed systems"
scrolls show <id>
scrolls md
scrolls kb
scrolls agent install
```

## Library layout

```text
~/.scrolls/
  items/          # normalized JSON/SQLite source records
  scrolls/        # individual Markdown files
  library/        # compiled interlinked KB
  media/          # optional thumbnails, images, transcripts, attachments
  agents/         # generated agent instruction files (SKILL.md, AGENTS.md)
  config.toml
```

## Design principles

- Local-first and agent-readable
- Platform adapters over one-off scrapers
- Markdown files as durable artifacts
- SQLite FTS/BM25 for fast local search
- Classification that works with or without an LLM
- Explicit provenance for every saved item
- Useful from shell, coding agents, and Hermes skills

## Status

Early implementation. Stack: Python ≥3.11 managed with uv (see
`docs/adr/0001-implementation-stack.md`).

Working today:

```bash
uv run scrolls init           # create the library skeleton (idempotent)
uv run scrolls status         # initialized? schema version? as JSON
uv run scrolls paths          # library layout, as JSON
uv run scrolls detect <url>   # URL → source adapter + source-local ID, as JSON
uv run scrolls add <url>      # register a URL as an item (stage: detected), as JSON
uv run scrolls ingest <url>   # add + fetch + md in one step, as JSON
uv run scrolls fetch          # fetch content for detected items, as JSON
uv run scrolls fetch <id>     # (re)fetch one item by id, as JSON
uv run scrolls md             # render fetched items as Markdown scrolls, as JSON
uv run scrolls md <id>        # (re)render one item by id, as JSON
uv run scrolls classify       # categorize items with the rules engine, as JSON
uv run scrolls classify <id>  # explicitly (re)classify one item, as JSON
uv run scrolls search <query> # BM25-ranked full-text search, as JSON
uv run scrolls show <id>      # print one item in full, as JSON
uv run scrolls list           # list items, as JSON
uv run scrolls kb             # compile the interlinked library pages, as JSON
uv run scrolls context <query> # compact context bundle, as Markdown
uv run scrolls agent install  # write agent instruction files, as JSON
uv run pytest                 # test suite
```

`scrolls add` auto-initializes the library, dedupes by stable item ID
(`source:source_id`, or a URL hash when the source has no local ID), and
stores the item at stage `detected` — registered but not yet fetched.

`scrolls fetch` runs the source adapter for each detected item, filling in
title, extracted text, summary, canonical URL, content hash, and
provenance, and moving the item to stage `fetched`. Adapters so far:
**wikipedia** (MediaWiki action API, no dependencies — see
`docs/adr/0002-first-fetch-adapter-wikipedia.md`; visible page categories
become `concepts`), **web** (readable
article extraction via `trafilatura`, the project's first per-adapter
dependency per ADR 0001), **youtube** (keyless oEmbed metadata plus
optional transcript via `youtube-transcript-api`; caption-less videos and
playlists degrade to metadata-only scrolls — see
`docs/adr/0003-youtube-adapter-oembed-transcripts.md`), and **github**
(keyless REST API: repo metadata plus optional README; author-curated
repo topics become `concepts`, the first producer for the KB's concept
pages; set `GITHUB_TOKEN`/`GH_TOKEN` to lift the rate limit — see
`docs/adr/0007-github-adapter-topics-as-concepts.md`). Items from sources
without an adapter yet are skipped, and per-item failures don't abort the
batch.

`scrolls md` renders each fetched item to a durable Markdown scroll at
`scrolls/<source>/<slug>.md` — YAML frontmatter (emitted as JSON values,
which YAML accepts) plus summary, extracted content, and links — and moves
the item to stage `rendered`. The item's `markdown_path` is recorded so
re-renders keep a stable path.

`scrolls search` runs SQLite FTS5 over title, summary, and extracted text
(BM25-ranked, title weighted highest) and returns hits with snippets; the
index is kept in sync by SQL triggers. Query tokens are AND-ed and quoted,
so arbitrary agent input never hits FTS5 syntax errors. `scrolls show <id>`
prints the full stored item.

`scrolls ingest <url>` chains add → fetch → classify → md for one URL, so
the first render already carries the category; re-ingesting an existing
URL refreshes its content without replacing an existing category. A URL whose source has no adapter
yet is still registered, but ingest reports the failure and exits 1.

`scrolls classify` assigns a `category` with a deterministic rules engine
(`rules-v1`, layer one of IDEAS.md §8's "regex/rules first → optional LLM
second → user overrides always win" — see
`docs/adr/0004-rules-classification-engine.md`): curated platforms first
(wikipedia → reference, arxiv → paper, github → project), then title
patterns (tutorial, opinion), then URL shape (docs sites →
documentation), then youtube → media. Unmatched items honestly stay
unclassified for a future LLM engine. Batch runs never overwrite an
existing category; `scrolls classify <id>` explicitly reclassifies.
Already-rendered scrolls are re-rendered so frontmatter stays in sync.

`scrolls kb` compiles the interlinked library (IDEAS.md §9, the
deterministic version — see `docs/adr/0005-deterministic-kb-compiler.md`):
`library/index.md` plus per-source, per-category, and per-concept pages
that link back to rendered scrolls with relative Markdown links. The
generated pages are rebuilt from scratch each run so stale groups can't
linger; other files under `library/` are left alone. Concept pages merge
spellings by slug; github repo topics and wikipedia page categories
populate them today, and an LLM concept engine can join later.

`scrolls context <query>` answers "what does my library know about X?"
with one compact bundle (IDEAS.md §11): BM25-ranked best matches, capped
excerpts (stored summary, else leading extracted text), and source
links. Unlike the data commands it emits Markdown — the bundle *is* the
artifact agents drop into context — while errors stay JSON on stderr.
Each excerpt carries the item id, source, and scroll path so an agent
can follow up with `scrolls show <id>` or read the full scroll.

`scrolls agent install` writes instruction files for coding agents under
`<root>/agents/` — `claude/SKILL.md`, `codex/AGENTS.md`,
`hermes/SKILL.md` — teaching the shell-first interface (`context` first,
`search`/`show` for depth, `ingest` to save). It never writes into other
tools' config trees; copy or symlink the files where your tool expects
them (see `docs/adr/0006-agent-install-stays-in-library-root.md`).

Item stages so far: `detected → fetched → rendered`; classification and
KB compilation are stage-neutral. With the IDEAS.md §6 MVP source trio
(wikipedia, web, youtube) plus github, search, rules classification, the
compiled library, context bundles, and agent install, all five IDEAS.md
§14 MVP passes have a working first version. Next slices: an LLM
classification/concept engine, more adapters (arxiv, x via Field Theory
import), media capture, or an MCP server.

The library root is `~/.scrolls`, overridable with `$SCROLLS_HOME`.
