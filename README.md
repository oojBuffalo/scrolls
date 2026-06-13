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
scrolls ingest https://en.wikipedia.org/wiki/SQLite  # add + fetch + classify + md
scrolls import fieldtheory          # bulk-import X bookmarks from Field Theory
scrolls follow https://www.youtube.com/playlist?list=PL12345  # subscribe to a feed
scrolls sync                        # register new items from followed feeds
scrolls search "distributed systems"
scrolls context "sqlite fts"        # compact Markdown bundle for agents
scrolls related wikipedia:en:SQLite
scrolls kb
scrolls agent install
```

`scrolls sync` — live delta updates, as distinct from one-off `add` and
bulk `import` (IDEAS.md §13) — is feed-based: follow any RSS/Atom feed
(a blog, a YouTube channel or playlist, an arXiv category, a GitHub
releases feed) and sync registers its new entries.

## Library layout

```text
~/.scrolls/        # or $SCROLLS_HOME
  db.sqlite       # canonical index: items + subscriptions + concept_summaries tables, FTS5 search, schema meta
  scrolls/        # individual Markdown files, one per item, per source
  library/        # compiled interlinked KB (index, sources, categories, concepts)
  agents/         # generated agent instruction files (SKILL.md, AGENTS.md)
  items/          # reserved: raw record exports (currently unused)
  media/          # captured media files (PDFs, thumbnails, photos), per source
  config.toml     # settings; today: [classify] default_engine + llm_model
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
`docs/adr/0001-implementation-stack.md`). `docs/architecture.md` explains
how the implemented system fits together; `docs/adr/README.md` indexes
the decision records behind it; `docs/cli.md` documents every command's
JSON output contract, exit codes, and error envelope with captured real
output; `docs/library-format.md` specifies the on-disk artifacts —
scroll frontmatter and body, compiled `library/` pages, agent files —
and what consumers of a library may rely on.

Working today:

```bash
uv run scrolls init           # create the library skeleton (idempotent)
uv run scrolls status         # initialized? schema version? as JSON
uv run scrolls paths          # library layout, as JSON
uv run scrolls detect <url>   # URL → source adapter + source-local ID, as JSON
uv run scrolls add <url>      # register a URL as an item (stage: detected), as JSON
uv run scrolls ingest <url>   # add + fetch + md in one step, as JSON
uv run scrolls import fieldtheory [--root PATH]  # bulk-import X bookmarks from ~/.fieldtheory, as JSON
uv run scrolls follow <url>   # subscribe to an RSS/Atom feed (validated by fetching it once), as JSON
uv run scrolls follow         # list feed subscriptions, as JSON
uv run scrolls sync           # register new items from followed feeds, as JSON
uv run scrolls sync <id>      # sync one subscription by id, as JSON
uv run scrolls unfollow <id>  # remove a subscription by id or feed URL, as JSON
uv run scrolls fetch          # fetch content for detected items, as JSON
uv run scrolls fetch <id>     # (re)fetch one item by id, as JSON
uv run scrolls md             # render fetched items as Markdown scrolls, as JSON
uv run scrolls md <id>        # (re)render one item by id, as JSON
uv run scrolls media          # download uncaptured media refs into media/, as JSON
uv run scrolls media <id>     # (re)capture one item's media by id, as JSON
uv run scrolls classify       # categorize items with the rules engine, as JSON
uv run scrolls classify <id>  # explicitly (re)classify one item, as JSON
uv run scrolls classify --engine llm  # LLM pass: category + domain + concepts (needs ANTHROPIC_API_KEY)
uv run scrolls classify --engine llm --batch  # same LLM pass via the Batches API at half price
uv run scrolls set <id> category=tool tags=a,b  # set classification fields by hand; empty value clears
uv run scrolls search <query> [--limit N]  # BM25-ranked full-text search, as JSON (default 20)
uv run scrolls show <id>      # print one item in full, as JSON
uv run scrolls related <id> [--limit N]  # items connected to one item, with reasons, as JSON (default 10)
uv run scrolls list           # list items, as JSON
uv run scrolls list --source web --stage detected --category ""  # filters AND together; "" = unclassified
uv run scrolls kb             # compile the interlinked library pages, as JSON
uv run scrolls kb --engine llm  # synthesize concept-page summaries first (needs ANTHROPIC_API_KEY), then compile
uv run scrolls context <query> [--limit N]  # compact context bundle, as Markdown (default 8)
uv run scrolls agent install  # write agent instruction files, as JSON
uv run scrolls doctor         # check index/file-tree integrity, as JSON
uv run scrolls doctor --fix   # repair what is safe offline: merge dupes, rewrite scrolls, rebuild FTS
uv run scrolls mcp            # serve the library to MCP clients over stdio
uv run pytest                 # test suite
```

`scrolls add` auto-initializes the library, dedupes by stable item ID
(`source:source_id`, or a URL hash when the source has no local ID), and
stores the item at stage `detected` — registered but not yet fetched.
URLs are normalized first (ADR 0023): tracking params (`utm_*`,
`fbclid`, …), fragments, host casing, and default ports are stripped
before hashing and storing, so the same article saved via differently
decorated links — a newsletter link, a feed entry, a plain paste —
stays one item with a clean URL. Meaningful params survive untouched,
and feed subscription URLs are never rewritten.

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
`docs/adr/0003-youtube-adapter-oembed-transcripts.md`), **github**
(keyless REST API: repo metadata plus optional README; author-curated
repo topics become `concepts`, the first producer for the KB's concept
pages; set `GITHUB_TOKEN`/`GH_TOKEN` to lift the rate limit — see
`docs/adr/0007-github-adapter-topics-as-concepts.md`), and **arxiv**
(keyless Atom export API, stdlib XML: the abstract becomes the
searchable summary, taxonomy codes become `tags` and their display
names — "Computation and Language" for `cs.CL`, via a bundled taxonomy
table — become `concepts`, the PDF link is
recorded as `media`, and the paper's full text is extracted from the
PDF with `pypdf` into searchable extracted text — any PDF failure
degrades to the abstract-only scroll — see
`docs/adr/0008-arxiv-adapter-atom-abstracts.md`,
`docs/adr/0010-arxiv-pdf-full-text-pypdf.md`, and
`docs/adr/0012-arxiv-taxonomy-names-as-concepts.md`), and **pdf**
(any other `.pdf` URL: text and document metadata via `pypdf`, the
`/Title`-or-filename as title, `/Subject` as the only honest summary,
and the document itself as a media ref for `scrolls media`; a non-PDF
payload fails the fetch, while a textless-but-real PDF degrades to a
metadata-only scroll — see `docs/adr/0013-generic-pdf-adapter.md`).
Items from sources without an adapter yet (today only `x`) are skipped,
and per-item failures don't abort the batch.

`scrolls import fieldtheory [--root PATH]` bulk-imports X/Twitter
bookmarks from a local Field Theory archive (IDEAS.md §7 — see
`docs/adr/0009-fieldtheory-import.md`): the raw JSONL cache becomes
`source="x"` items at stage `fetched` (each line preserved in
`raw_text`), and Field Theory's classified pages contribute
`category`/`domain` via a frontmatter join on tweet id. Item ids
(`x:<tweetId>`) match URL detection, so imports and `scrolls add` of a
tweet URL dedupe against each other; re-imports skip existing items.

`scrolls follow <url>` subscribes the library to an RSS 2.0/Atom feed —
the URL is fetched once to validate it and capture the feed's title
(a typo'd URL is rejected, not stored), and YouTube playlist/channel
URLs map to their public feeds automatically. `scrolls sync` then polls
every followed feed (IDEAS.md §13's live-delta path — see
`docs/adr/0017-feed-subscriptions-sync.md`) and registers each new
entry URL at stage `detected` through the same detection/dedupe as
`scrolls add`, so a YouTube feed entry becomes a `youtube` item and a
blog entry a `web` item; the entry's feed title names the item (and
makes it searchable), and its published date — RSS `pubDate` or Atom
`published`, normalized to UTC ISO 8601 — fills `published_at`
(ADR 0021). Fetch replaces both only with the source's own values, so
a synced YouTube video keeps the feed's date its keyless oEmbed fetch
can't provide. `scrolls fetch` (then `classify`/`md`) brings
the new items in. Polling is HTTP-cached (see
`docs/adr/0019-feed-http-caching.md`): each full response's
`ETag`/`Last-Modified` are stored on the subscription, and an
unchanged feed answers the next poll with an empty 304 and is reported
as `unchanged` — so a cron'd sync costs almost nothing when nothing
changed. Known entries count as known on re-sync, one dead
feed never aborts the batch, and `scrolls unfollow` removes a
subscription while keeping the items it registered.

`scrolls md` renders each fetched item to a durable Markdown scroll at
`scrolls/<source>/<slug>.md` — YAML frontmatter (emitted as JSON values,
which YAML accepts) plus summary, extracted content, and links — and moves
the item to stage `rendered`. Media references (tweet photos, arXiv PDFs)
land in frontmatter, and an item's extracted links join the Links section.
The item's `markdown_path` is recorded so re-renders keep a stable path.

`scrolls media` downloads items' media references — arXiv PDFs, youtube
thumbnails, tweet photos — to `media/<source>/`, records each file's
root-relative path back on the item's media ref, and re-renders the
item's scroll so frontmatter points at the local file. Batch runs only
capture refs without a file on disk (re-downloading anything deleted);
`scrolls media <id>` explicitly re-captures one item. Failed downloads
fail the run but never abort the batch, and the recorded URL always
allows re-capture — the media tree is cache, not canon (see
`docs/adr/0011-media-capture-command.md`).

`scrolls search` runs SQLite FTS5 over title, summary, and extracted text
(BM25-ranked, title weighted highest) and returns hits with snippets; the
index is kept in sync by SQL triggers. Query tokens are AND-ed and quoted,
so arbitrary agent input never hits FTS5 syntax errors. `scrolls show <id>`
prints the full stored item.

`scrolls related <id>` finds the items connected to one item with
deterministic, explainable signals (IDEAS.md §10): link connections in
either direction (a bookmarked tweet pointing at a saved arXiv paper —
links resolve through source detection, so `arxiv.org/pdf/X` finds item
`arxiv:X`), shared concepts (merged by slug like KB pages), shared tags,
and same category/domain as weak corroboration. Every hit carries its
`reasons`, and the scoring needs no LLM.

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
unclassified. Batch runs never overwrite an
existing category; `scrolls classify <id>` explicitly reclassifies.
Already-rendered scrolls are re-rendered so frontmatter stays in sync.

`scrolls classify --engine llm` is layer two (`llm-v1` — see
`docs/adr/0015-llm-classification-engine.md`): a model reads each item's
actual content via the Anthropic API and assigns a category from the
full IDEAS.md §8 vocabulary, plus the fields no rule can honestly
invent — `domain`, and `concepts` merged after the platform-curated
ones (feeding the same KB concept pages). Structured outputs pin the
response to the category vocabulary. Needs `ANTHROPIC_API_KEY`; the
default model `claude-opus-4-8` is overridable via `SCROLLS_LLM_MODEL`.
Batch semantics are unchanged (existing categories are never
overwritten; per-item API failures don't abort the run), and missing
credentials abort with the standard error envelope. Adding `--batch`
(ADR 0022) submits the whole run as one Message Batches API request at
half the per-token price — same prompts, schema, and validation, polled
until the batch ends (typically minutes); per-request failures fail
their item, never the batch.

`scrolls set <id> field=value...` is layer three — user overrides
always win (see `docs/adr/0018-user-overrides-scrolls-set.md`). It sets
exactly the fields the engines write (`category`, `domain`, and the
comma-separated lists `tags`/`concepts`), free-form: engines pin
vocabularies, the user's word is final. An empty value clears a field
so the item is batch-classifiable again, and a set category sticks
because batch runs never overwrite one. Rendered scrolls re-render so
frontmatter stays in sync.

`config.toml`'s `[classify]` section makes both choices sticky per
library (see `docs/adr/0016-config-toml-classify-section.md`):
`default_engine = "llm"` routes a bare `scrolls classify` to the LLM
engine, and `llm_model` picks its model. Per-invocation overrides
always win — the `--engine` flag beats `default_engine`, and
`$SCROLLS_LLM_MODEL` beats `llm_model`. `scrolls ingest` always
classifies with rules, whatever the config says, so ingest stays
keyless and offline.

`scrolls kb` compiles the interlinked library (IDEAS.md §9, the
deterministic version — see `docs/adr/0005-deterministic-kb-compiler.md`):
`library/index.md` plus per-source, per-category, and per-concept pages
that link back to rendered scrolls with relative Markdown links. The
generated pages are rebuilt from scratch each run so stale groups can't
linger; other files under `library/` are left alone. Concept pages merge
spellings by slug; github repo topics, wikipedia page categories, and
arXiv taxonomy names populate them today.

`scrolls kb --engine llm` is the fancy version of IDEAS.md §9 that
ADR 0005 left room for (see `docs/adr/0025-llm-concept-summaries.md`):
a model writes the prose no rollup can — a short synthesis of how each
concept shows up across the 2+ scrolls that share it — and every
concept page with one leads with it. Summaries are stored data
(schema v6), not compile output: a plain keyless `scrolls kb` keeps
including them, and generation is incremental — each summary records a
fingerprint of its member scrolls, an unchanged concept costs nothing
to re-run, and summaries whose concept dissolved are pruned. Model and
credentials follow the LLM classification engine (`ANTHROPIC_API_KEY`,
`[classify] llm_model`, `$SCROLLS_LLM_MODEL`); per-concept API failures
still compile the library, and a credentials abort keeps everything
already saved.

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

`scrolls doctor` checks the integrity the other commands assume: items
whose URLs normalize to the same resource (duplicates a pre-ADR-0023
library can hold), recorded scroll files missing on disk, captured media
files gone, orphan scrolls no item owns, and an FTS index out of sync
with the items table. `scrolls doctor --fix` repairs exactly what is
safe offline — merges each duplicate group into the id a clean re-add
would mint (content from the most advanced member, earliest save date,
classification merged), rewrites missing scrolls from the index, and
rebuilds the FTS index — while missing media stays `scrolls media`'s
job and orphan files are reported, never deleted. Exit 0 means the
library ended fully consistent (see `docs/adr/0026-doctor-command.md`).

`scrolls mcp` serves the same engines to MCP clients over stdio
(IDEAS.md §10's second phase — see `docs/adr/0014-mcp-server.md`):
`get_context_bundle`, `search_scrolls`, `get_scroll`,
`get_related_scrolls`, `get_concept_page`, `list_sources`,
`ingest_url`, the feed subscription tools `follow_feed`,
`unfollow_feed`, `list_feed_subscriptions`, and `sync_feeds`
(ADR 0020), and `compile_library` — the deterministic `scrolls kb`,
so an ingested or synced item reaches its concept pages without
shelling out (LLM summary generation stays a CLI step: an MCP tool
must never trigger paid API calls implicitly). Connect with
`claude mcp add scrolls -- uv run scrolls mcp` or equivalent client
config; the shell interface remains primary.

Item stages so far: `detected → fetched → rendered`; classification,
media capture, and KB compilation are stage-neutral. With the IDEAS.md
§6 MVP source trio (wikipedia, web, youtube) plus github, arxiv, pdf,
and x (via Field Theory import), search, two-layer classification
(rules + LLM), media capture, the compiled library, context bundles,
agent install, and the MCP server, all five IDEAS.md §14 MVP passes
have a working first version plus the full §8 classification stack
(rules, LLM, and `scrolls set` user overrides) and feed-based live
deltas via `scrolls sync` (IDEAS.md §13) with HTTP-cached polling
(ADR 0019), on both the shell and MCP interfaces (ADR 0020), with the
Batches API halving bulk classification cost (ADR 0022), item
identity robust to tracking-param junk (ADR 0023), `published_at`
one uniform UTC ISO 8601 vocabulary from every writer (ADR 0024), and
both halves of IDEAS.md §9 — the deterministic KB compiler and the
LLM concept engine behind `kb --engine llm` (ADR 0025) — and
`scrolls doctor` to find and repair index/file-tree drift, including
the pre-normalization duplicates ADR 0023 deferred (ADR 0026). Next
candidate: a Batches transport for concept summaries if libraries
outgrow per-call generation (ADR 0025).

The library root is `~/.scrolls`, overridable with `$SCROLLS_HOME`.
