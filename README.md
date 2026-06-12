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
uv run pytest                 # test suite
```

`scrolls add` auto-initializes the library, dedupes by stable item ID
(`source:source_id`, or a URL hash when the source has no local ID), and
stores the item at stage `detected` — registered but not yet fetched.

`scrolls fetch` runs the source adapter for each detected item, filling in
title, extracted text, summary, canonical URL, content hash, and
provenance, and moving the item to stage `fetched`. Adapters so far:
**wikipedia** (MediaWiki action API, no dependencies — see
`docs/adr/0002-first-fetch-adapter-wikipedia.md`), **web** (readable
article extraction via `trafilatura`, the project's first per-adapter
dependency per ADR 0001), and **youtube** (keyless oEmbed metadata plus
optional transcript via `youtube-transcript-api`; caption-less videos and
playlists degrade to metadata-only scrolls — see
`docs/adr/0003-youtube-adapter-oembed-transcripts.md`). Items from sources
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

Item stages so far: `detected → fetched → rendered`; classification is
stage-neutral enrichment. The IDEAS.md §6 MVP source trio (wikipedia, web,
youtube) is complete and Pass 4 classification has its rules layer. Next
slices: the compiled library/KB and context bundles (Pass 5), an LLM
classification engine, or more adapters (github, arxiv).

The library root is `~/.scrolls`, overridable with `$SCROLLS_HOME`.
