# Scrolls Implementation Ideas

*Amended: 2026-07-26 — this file is the historical brainstorm, kept in place
(its numbered sections are cited from `src/` and the ADRs; do not renumber).
The inspiration summaries that used to live in §0 and §13 moved to
`docs/inspiration/`; pointers remain.*

The clean mental model for **Scrolls** could be:

```text
Sources → Items → Scrolls → Library → Agents
```

Where:

- **Sources** = X, YouTube, Wikipedia, web pages, GitHub, PDFs, etc.
- **Items** = normalized records in SQLite/JSON.
- **Scrolls** = individual Markdown files with metadata + extracted content.
- **Library** = compiled interlinked KB / concept map.
- **Agents** = Claude Code, Codex, Hermes, shell tools, future MCP server.

**Read `docs/vision.md` for the authoritative product vision.** This IDEAS.md captures early thinking; the vision document is the current north star.

## 0. Product inspiration: Last30Days and Obsidian Second Brain

Scrolls draws on three external inspirations — the original **Field Theory
CLI** spark, [`mvanhorn/last30days-skill`](https://github.com/mvanhorn/last30days-skill),
and [`eugeniughelbur/obsidian-second-brain`](https://github.com/eugeniughelbur/obsidian-second-brain).
None is code to copy. The full record — origin, adopt/adapt/reject mappings,
and pointers per source — lives in `docs/inspiration/` (one document per
inspiration); the summaries that used to live here moved there on 2026-07-26.

## 1. Core abstraction: source adapters

Each platform should be a small adapter implementing the same interface.

```ts
interface SourceAdapter {
  name: string;

  sync(input: SyncInput): Promise<RawItem[]>;
  enrich(item: RawItem): Promise<EnrichedItem>;
  normalize(item: EnrichedItem): Promise<ScrollItem>;
}
```

Examples:

```text
sources/
  x.ts
  youtube.ts
  wikipedia.ts
  web.ts
  github.ts
  arxiv.ts
```

Each adapter answers:

1. How do I fetch this thing?
2. How do I extract useful text?
3. How do I normalize it into a Scrolls item?

Then the rest of the pipeline does not care whether the thing came from X, YouTube, or Wikipedia.

This keeps the system elegant.

## 2. Make “Scroll” the universal unit

A **scroll** should be the durable, human-readable, agent-readable artifact.

Every item becomes one Markdown file with frontmatter:

```md
---
id: youtube:abc123
source: youtube
url: https://youtube.com/watch?v=abc123
title: "How SQLite FTS Works"
author: "Some Channel"
saved_at: 2026-06-04T12:00:00Z
published_at: 2024-10-12T00:00:00Z
category: technique
domain: databases
tags:
  - sqlite
  - search
  - fts
concepts:
  - BM25
  - full text search
  - local-first software
media:
  thumbnail: media/youtube/abc123.jpg
provenance:
  fetched_by: youtube-adapter
  transcript_source: youtube-transcript
---

# How SQLite FTS Works

## Summary

...

## Extracted Content

Transcript or article text here.

## Links

- Source: ...
- Channel/Page/Author: ...

## Agent Notes

Why this item may be useful, commands/packages mentioned, APIs, etc.
```

The Markdown files become the primary “library shelf,” even if SQLite is the fast index.

## 3. SQLite as the canonical index, Markdown as the canonical artifact

Avoid choosing only one of DB vs files. Use both:

```text
~/.scrolls/
  scrolls/
    youtube/
      how-sqlite-fts-works.md
    wikipedia/
      full-text-search.md
    x/
      1234567890.md

  db.sqlite

  media/
    youtube/
    x/
    web/

  library/
    index.md
    concepts/
      bm25.md
      sqlite.md
      agents.md
    sources/
      youtube.md
      wikipedia.md
      x.md
```

SQLite stores:

- item metadata
- full-text index
- sync state
- content hash
- classification output
- backlinks/concepts
- errors/retries

Markdown stores:

- durable readable representation
- frontmatter
- summaries
- extracted content
- links
- provenance

That gives fast CLI search and agent-friendly files.

## 4. Pipeline as idempotent stages

The workflow can be modeled as stages:

```text
sync → enrich → classify → render-md → index → compile-kb → expose-agent
```

Each stage should be independently runnable:

```bash
scrolls sync youtube <url>
scrolls enrich
scrolls classify
scrolls md
scrolls index
scrolls kb
scrolls agent install
```

Or all together:

```bash
scrolls ingest youtube <url> --classify --kb
```

Internally, each item has stage state:

```text
synced
enriched
classified
rendered
indexed
compiled
```

This makes it resilient. If transcript fetching fails for one YouTube video, it should not break the whole library.

## 5. Keep the CLI small and composable

A clean initial command set:

```bash
scrolls add <url>
scrolls sync <source>
scrolls search <query>
scrolls show <id>
scrolls list
scrolls classify
scrolls md
scrolls kb
scrolls paths
scrolls status
scrolls agent install
```

Where `scrolls add` can auto-detect:

```bash
scrolls add https://youtube.com/watch?v=...
scrolls add https://en.wikipedia.org/wiki/...
scrolls add https://github.com/...
scrolls add https://example.com/article
```

Then source-specific commands exist when needed:

```bash
scrolls sync x --bookmarks
scrolls sync youtube --playlist <url>
scrolls sync wikipedia "full-text search"
```

Try to make `scrolls add <url>` delightful before making every source deep.

## 6. Start with three source types

For the MVP, avoid X first because X auth/session complexity is annoying.

Start with sources that prove the abstraction:

### YouTube

Input:

```bash
scrolls add https://youtube.com/watch?v=...
```

Extract:

- title
- channel
- description
- transcript
- thumbnail
- chapters if available
- links in description

### Wikipedia

Input:

```bash
scrolls add https://en.wikipedia.org/wiki/SQLite
```

Extract:

- title
- summary
- sections
- links
- categories
- page metadata

### Web article

Input:

```bash
scrolls add https://example.com/post
```

Extract:

- readable article text
- title
- author
- published date
- outgoing links
- Open Graph metadata

This proves the platform adapter model without starting with the hardest sync problem.

Then add:

- GitHub repos
- PDFs/arXiv
- X bookmarks / Field Theory import

## 7. Field Theory compatibility/import could be a killer feature

*(Realized as `scrolls import fieldtheory` — ADR 0009; the lineage write-up is
`docs/inspiration/fieldtheory-cli-inspiration.md`.)*

Instead of immediately reimplementing X bookmark sync, Scrolls could initially support:

```bash
scrolls import fieldtheory
```

It could read:

```text
~/.fieldtheory/bookmarks/
~/.fieldtheory/library/
```

Then convert Field Theory items into Scrolls’ normalized format.

That gives Scrolls an immediate path to X bookmarks while letting Field Theory keep doing what it already does well.

Later:

```bash
scrolls sync x --bookmarks
```

could be native.

## 8. Classification should be layered

Elegant approach:

```text
regex/rules first → optional LLM second → user overrides always win
```

Example categories from Field Theory:

- tool
- security
- technique
- launch
- research
- opinion
- commerce

Scrolls could extend them slightly:

- tool
- research
- tutorial
- reference
- opinion
- project
- product
- media
- dataset
- paper
- documentation

But avoid overdesigning categories early.

Maybe each item gets:

```yaml
category: technique
domain: databases
concepts:
  - SQLite
  - BM25
  - full-text search
usefulness: high
audience:
  - agents
  - developers
```

Classification engines:

```bash
scrolls classify --regex
scrolls classify --llm
scrolls classify --engine openai:gpt-4.1-mini
scrolls classify --engine local:ollama/qwen3
```

And a config:

```toml
[classify]
default_engine = "regex"
llm_engine = "openai:gpt-4.1-mini"
```

## 9. The KB compiler should feel like Karpathy wiki

This is probably one of the most important parts.

Input:

```text
all scroll markdown files + metadata + extracted concepts
```

Output:

```text
~/.scrolls/library/
  index.md
  concepts/
    sqlite.md
    bm25.md
    agent-tools.md
  sources/
    youtube.md
    wikipedia.md
    x.md
  categories/
    research.md
    tools.md
    techniques.md
```

Each concept page could contain:

```md
# BM25

## Summary

BM25 appears across saved items about search, SQLite FTS, information retrieval, and local-first knowledge bases.

## Key Scrolls

- [[How SQLite FTS Works]]
- [[Field Theory CLI]]
- [[Wikipedia - Okapi BM25]]

## Related Concepts

- [[Full-text search]]
- [[SQLite]]
- [[Ranking]]
- [[Local-first software]]

## Source Notes

...
```

The simple version can be deterministic:

- pull `concepts` from frontmatter
- group scrolls by concept
- create backlinks
- generate index pages

The fancy version can use LLMs to synthesize concept pages.

## 10. Agent access: start with shell commands, then add MCP

For simplicity, first expose the KB through reliable CLI commands:

```bash
scrolls search "agent memory" --json
scrolls show <id> --json
scrolls context "sqlite fts" --limit 8
scrolls related <id>
scrolls paths --json
```

Then `scrolls agent install` creates small agent instruction files.

For Claude Code:

```text
~/.scrolls/agents/claude/SKILL.md
```

For Codex:

```text
~/.scrolls/agents/codex/AGENTS.md
```

For Hermes:

```text
~/.hermes/skills/scrolls/SKILL.md
```

The agent docs would say:

```md
Use `scrolls search <query> --json` to search the user's saved knowledge.
Use `scrolls context <topic>` to retrieve a compact bundle of relevant scrolls.
Use `scrolls show <id>` to inspect one source.
```

Later, add:

```bash
scrolls mcp
```

As an MCP server exposing:

- `search_scrolls`
- `get_scroll`
- `get_related_scrolls`
- `get_concept_page`
- `list_sources`
- `ingest_url`

But do not make MCP mandatory for v1. Shell access is simpler and works everywhere.

## 11. Context bundles could be the agent-native killer feature

This feels very useful:

```bash
scrolls context "sqlite bm25 local search"
```

Output:

```md
# Scrolls Context Bundle: sqlite bm25 local search

## Best Matches

1. How SQLite FTS Works
2. Okapi BM25 - Wikipedia
3. Field Theory CLI README
4. Local-first search architecture notes

## Synthesized Brief

...

## Relevant Excerpts

...

## Commands / APIs Mentioned

...

## Source Links

...
```

Agents do not want 100 files. They want a compact, high-signal context bundle.

So the agent-facing value proposition could be:

> Scrolls turns your saved internet into searchable, cited context bundles for coding agents.

That is a strong core.

## 12. Simple internal data model

```ts
type ScrollItem = {
  id: string;              // stable: source:source_id or hash
  source: string;          // youtube, wikipedia, web, x
  sourceId?: string;
  url: string;
  canonicalUrl?: string;

  title: string;
  author?: string;
  publishedAt?: string;
  savedAt: string;

  rawText?: string;
  extractedText?: string;
  summary?: string;

  category?: string;
  domain?: string;
  tags: string[];
  concepts: string[];

  links: LinkRef[];
  media: MediaRef[];

  contentHash: string;
  markdownPath?: string;

  provenance: {
    adapter: string;
    fetchedAt: string;
    extractionMethod: string;
  };
};
```

This is enough for almost everything.

## 13. Implementation stack considerations

No stack decision yet. The important thing is to keep the pipeline boundaries clean enough that the language choice does not leak everywhere:

```text
Source adapter → normalized ScrollItem → SQLite/search index → Markdown scroll → KB/context bundle
```

### Bulk import vs live sync

A useful distinction:

```text
import = bulk local archive ingestion
sync   = live platform delta updates
add    = one-off URL ingestion
```

For example, a large YouTube history sync is probably better as:

```bash
scrolls import google-takeout takeout.zip --youtube-history
scrolls enrich youtube --transcripts --metadata
```

rather than browser-driving thousands of history entries. Google Takeout gives a fast, local, resumable spine of video IDs/timestamps; enrichment can later fetch transcripts, thumbnails, channels, descriptions, and chapters. Browser/session/API sync is more appropriate for daily deltas where the number of new items is small.

### TypeScript CLI trade-offs

TypeScript fits a Field Theory-style product well:

- CLI: `commander`, `cac`, or similar
- browser/session work: native browser cookie handling, `undici`/`fetch`, possibly Playwright/Puppeteer only when needed
- schemas: `zod`
- DB/search: `sql.js-fts5` for pure JS/WASM portability, or `better-sqlite3` for native SQLite performance
- Markdown: `gray-matter`, Markdown AST tooling
- web extraction: Readability/JSDOM/Cheerio
- install story: `npm install -g scrolls`

Strengths: polished npm CLI, good browser tooling, easy agent instruction generation, strong alignment with Field Theory patterns.

Weaknesses: heavier ML/data-analysis work is less natural; PDF extraction, embeddings, clustering, and serious analytics may end up shelling out to Python or external tools.

### Python CLI trade-offs

Python fits the broader extraction/analysis/ML direction well:

- CLI: `typer`/`click` + `rich`
- schemas: `pydantic`
- DB/search: stdlib `sqlite3`, APSW, `sqlite-utils`; optional DuckDB for analytics
- web extraction: `trafilatura`, BeautifulSoup, `readability-lxml`
- YouTube/media: `yt-dlp`, transcript libraries
- docs/PDFs: PyMuPDF, `marker`, OCR/document tooling
- ML/analysis: `sentence-transformers`, scikit-learn, pandas, NetworkX
- install story: `uv tool install scrolls`

Strengths: best ecosystem for archives, extraction, embeddings, clustering, topic analysis, PDFs, and data pipelines.

Weaknesses: packaging can get heavier, especially with ML/PDF extras; browser/session work is possible but may feel less clean than a Node CLI.

### Field Theory lessons to preserve

Moved verbatim to `docs/inspiration/fieldtheory-cli-inspiration.md`
(2026-07-26), which carries the discipline pipeline and the six
borrow-regardless-of-stack rules.


## 14. MVP in five passes

### Pass 1: Local library skeleton

- `scrolls init`
- SQLite DB
- paths/config
- `scrolls status`
- `scrolls paths --json`

### Pass 2: Add URL → Markdown

- `scrolls add <url>`
- source detection
- web/Wikipedia/YouTube adapter
- create one Markdown scroll per item

### Pass 3: Search

- SQLite FTS5
- `scrolls search`
- `scrolls show`
- JSON output for agents

### Pass 4: Classification

- regex categories
- concept extraction
- optional LLM engine
- update frontmatter

### Pass 5: KB + agents

- compile concept/category/source pages
- `scrolls kb`
- `scrolls context <query>`
- `scrolls agent install`

That would produce something real without overbuilding.

## 15. Product framing

A few possible taglines:

- **Scrolls: turn saved internet into agent-readable knowledge.**
- **Scrolls: a local-first library for your agents.**
- **Scrolls: sync, classify, and compile the web into Markdown knowledge.**
- **Scrolls: your saved internet, organized for humans and agents.**
- **Scrolls: from bookmarks to context.**

Favorite architecture phrase:

```text
Scrolls is a source-adapter pipeline that converts saved internet artifacts into Markdown scrolls, indexes them with SQLite FTS, compiles them into an interlinked library, and exposes that library as context for agents.
```

The big design principle:

> Do not build a giant scraper. Build a small, boring pipeline where every source becomes the same kind of scroll.
