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
uv run scrolls detect <url>   # URL → source adapter + source-local ID, as JSON
uv run pytest                 # test suite
```
