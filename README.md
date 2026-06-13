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
uv run scrolls status         # initialized? schema? item/stage/source counts? as JSON
uv run scrolls paths          # library layout, as JSON
uv run scrolls detect <url>   # URL → source adapter + source-local ID, as JSON
uv run scrolls add <url>      # register a URL as an item (stage: detected), as JSON
uv run scrolls ingest <url>   # add + fetch + md in one step, as JSON
uv run scrolls import fieldtheory [--root PATH]  # bulk-import X bookmarks from ~/.fieldtheory, as JSON
uv run scrolls import google-takeout <path>  # bulk-import YouTube watch history from a Takeout export, as JSON
uv run scrolls import bookmarks <path>  # bulk-import a browser bookmarks HTML export, as JSON
uv run scrolls follow <url>   # subscribe to an RSS/Atom feed (validated by fetching it once), as JSON
uv run scrolls follow         # list feed subscriptions, as JSON
uv run scrolls sync           # register new items from followed feeds, as JSON
uv run scrolls sync <id>      # sync one subscription by id, as JSON
uv run scrolls unfollow <id>  # remove a subscription by id or feed URL, as JSON
uv run scrolls fetch          # fetch content for detected items, as JSON
uv run scrolls fetch --limit 50  # at most 50 fetch attempts, oldest first; resumes next run
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
uv run scrolls rm <id-or-url> [...]  # remove items and the files they own, as JSON
uv run scrolls search <query> [--limit N]  # BM25-ranked full-text search, as JSON (default 20)
uv run scrolls show <id>      # print one item in full, as JSON
uv run scrolls related <id> [--limit N]  # items connected to one item, with reasons, as JSON (default 10)
uv run scrolls list           # list items, as JSON
uv run scrolls list --source web --stage detected --category ""  # filters AND together; "" = unclassified
uv run scrolls kb             # compile the interlinked library pages, as JSON
uv run scrolls kb --engine llm  # synthesize concept-page summaries first (needs ANTHROPIC_API_KEY), then compile
uv run scrolls kb --engine llm --batch  # same synthesis via the Batches API at half price
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
metadata-only scroll — see `docs/adr/0013-generic-pdf-adapter.md`), and
**hackernews** (the keyless Firebase API in one request — see
`docs/adr/0031-hacker-news-adapter.md`: an Ask HN/Show HN/comment with a
`text` body contributes it as extracted text with its lead paragraph as
the summary, while a link story has no body of its own and degrades to a
metadata-only scroll whose summary is the discussion status — "104
points, 71 comments" — and whose linked article rides along as a bare
URL in the Links section, one `scrolls add` away; the comment id tree
stays in `raw_text` for a later enrichment, and only `news.ycombinator.com/item?id=…`
pages fetch — the front page and profiles register but have no item to
fetch), and **stackexchange** (the keyless Stack Exchange API — see
`docs/adr/0033-stack-exchange-adapter.md`: one adapter serves the whole
network, the per-site API slug carried in the item id as
`stackexchange:<site>:<id>` the way Wikipedia carries its language
edition, so a Math.SE, Super User, or MathOverflow question enriches
with no extra code. A saved question's body and its top answers —
accepted answer first — become the searchable scroll, the question's
author-applied tags become `concepts` like github repo topics, and the
answers are an optional second request so a question with none, or a
failed answers fetch, still produces a question-only scroll; only
`/questions/<id>` and the `/q/<id>` shortlink fetch, while tag, user,
and `/a/<id>` answer-permalink pages register but have no question to
fetch), and **pypi** (the keyless PyPI JSON API — see
`docs/adr/0034-pypi-adapter.md`: a saved `pypi.org/project/<name>/`
page becomes a clean scroll from the project's latest-release metadata
instead of a `trafilatura` scrape. Identity is the PEP 503-normalized
package name, so `Flask`, `flask`, and a version-pinned page all dedupe
to `pypi:flask`; the long description (rendered README) is the
searchable content, the author-declared keywords become `concepts` like
github repo topics, the trove classifiers become `tags` like arXiv
codes, and the declared project URLs become `links` — so a package's
Source link to its github repo connects them in `scrolls related`. A
PyPI package classifies as `tool`, the first rule to produce that
category; search/user/help pages register but have no package to fetch),
and **npm** (the keyless npm registry — see
`docs/adr/0035-npm-adapter.md`: a saved `npmjs.com/package/<name>` page
becomes a clean scroll from the package's latest-release metadata, the
JavaScript sibling of the PyPI adapter. Identity is the package name
preserved verbatim — the registry is case-sensitive, so unlike PyPI it
is not folded — with scoped names (`@babel/core`) and version pages
handled. The README is the searchable content, taken from the registry's
packument when present and otherwise extracted from the published
tarball (`dist.tarball`, a capped download) — the fallback that matters,
because the packument's README is empty for high-traffic packages like
`express` and `react`. Author-declared keywords become `concepts` like
github repo topics; npm has no trove-classifier analog so `tags` stay
empty; and the homepage and repository become `links`, the repository's
`git+https://…​.git` form normalized to a clean URL so a package's repo
connects to it in `scrolls related`. An npm package classifies as
`tool` like a PyPI one; search/user/org pages register but have no
package to fetch), and **crates** (the keyless crates.io JSON API — see
`docs/adr/0036-crates-io-adapter.md`: a saved `crates.io/crates/<name>`
page becomes a clean scroll from the crate's displayed-version metadata,
the Rust sibling of the PyPI and npm adapters. Identity is the crate
name folded like a PyPI one — crates.io is case-insensitive and treats
`-`/`_` as equivalent, so `serde_json`, `serde-json`, and a version page
all dedupe to `crates:serde-json`, while the canonical published name is
read back from the API for the canonical URL and the download path. The
crate JSON carries no inline README — only a link to an HTML-rendered
one — so the raw Markdown README is extracted from the published
`.crate` tarball (the capped `http.get_bytes` npm introduced), every
tarball failure degrading to a metadata-only scroll. Author-declared
keywords become `concepts` like github repo topics; the curated category
taxonomy's display names become `tags` like PyPI classifiers; and the
homepage, `docs.rs` docs, and repository become `links`, the repository
normalized so a crate's repo connects to it in `scrolls related`. A
crate classifies as `tool` like a PyPI or npm package;
search/user/category pages register but have no crate to fetch), and
**crossref** (the keyless Crossref DOI metadata API — see
`docs/adr/0037-crossref-doi-adapter.md`: a saved `doi.org/<doi>` link
becomes a clean scroll from the work's registered metadata instead of a
redirect into whatever publisher page — often a paywall — the DOI
resolves to. Identity is the DOI folded lowercase — DOIs are
case-insensitive, so `doi.org` and the legacy `dx.doi.org`, and any case
variant, dedupe to one `crossref:10.…` item, the canonical form read
back from the response. Crossref carries metadata only, so the JATS-XML
abstract — when one exists — is stripped to a plain `summary` that FTS
indexes, with no `extracted_text` (there is no full text); a record with
no abstract is an honest metadata-only scroll of title, authors, venue,
and date, still far better than the `web` scrape it replaces. The
`subject` categories become `concepts` like github topics, the work
`type` (`journal-article`, `proceedings-article`, …) and its publication
venue become `tags`, and only the publisher's landing page becomes a
`link` — a work's `reference` DOIs run to hundreds and are deliberately
not turned into links. `published_at` follows Crossref's date precedence
(`issued` first, `created` last). A Crossref work classifies as `paper`
like an arXiv preprint, so Scrolls covers both halves of the literature;
the bare resolver and non-DOI paths register but have no work to fetch),
and **packagist** (the keyless Packagist JSON API — see
`docs/adr/0039-packagist-adapter.md`: a saved
`packagist.org/packages/<vendor>/<name>` page becomes a clean scroll from
the package's metadata, the PHP/Composer sibling of the PyPI, npm, and
crates adapters. Identity is the `vendor/name` folded lowercase —
Composer names are case-insensitive, so `Monolog/Monolog` and a
`/stats` subpage all dedupe to `packagist:monolog/monolog`, the canonical
form read back from the API. Packagist keys its `versions` by string and
exposes no "default version" pointer, so the adapter selects the highest
*stable* release by ranking the numeric `version_normalized`
(`3.9.0` beats both a later-dated `2.9.x` patch and the `dev-main`
branch), with no semver dependency. The API carries no README — it lives
only in the dist zip — so a Packagist scroll is honestly metadata-only,
the package description becoming the `summary` that FTS indexes.
Author-declared keywords become `concepts` like github repo topics; the
package `type` and the release's SPDX `license`s become `tags` like PyPI
classifiers; and the repository, homepage, and git source become `links`,
the source's `…​.git` form normalized so a package's repo connects to it
in `scrolls related`. A Composer package classifies as `tool` like a
PyPI, npm, or crates one; the packages list, vendor pages, and search
register but have no package to fetch), and **rubygems** (the keyless
RubyGems JSON API — see `docs/adr/0040-rubygems-adapter.md`: a saved
`rubygems.org/gems/<name>` page becomes a clean scroll from the gem's
metadata, the Ruby sibling of the PyPI, npm, crates, and Packagist
adapters, and the simplest of the five — `gems/<name>.json` returns the
latest version inline, so there is no version to select. Identity is the
gem name preserved verbatim — RubyGems is case-sensitive (`gems/Ascii85`
resolves, `gems/ascii85` 404s), npm's rule rather than PyPI's fold. A
gemspec has no keywords field, so a gem contributes nothing to the
concept graph — `concepts` empty by design — and the API ships no README,
so the gem's description becomes the `summary` that FTS indexes. The SPDX
`license`s become `tags`; and the homepage, source, and documentation
URIs become `links`, the source URI resolving to the gem's github repo in
`scrolls related` even when it points at a tagged tree. A gem classifies
as `tool` like the other packages; the gems list and search register but
have no gem to fetch), and **huggingface** (the keyless Hugging Face Hub
API — see `docs/adr/0041-huggingface-hub-adapter.md`: a saved
`huggingface.co/<org>/<name>` model page or
`huggingface.co/datasets/<...>` dataset page becomes a clean scroll from
the Hub's structured metadata instead of a `trafilatura` scrape of a
JS-rendered page, the ML-artifact sibling of the package-registry
adapters. One adapter serves both repo kinds the way the Stack Exchange
adapter serves a whole network: the *kind* rides in the item id as
`huggingface:model:<org>/<name>` or `huggingface:dataset:<...>`, picked
off the URL so the fetch routes to `/api/models` or `/api/datasets`. Repo
ids are kept verbatim — the Hub is case-sensitive, npm's rule rather than
PyPI's fold — and a `/tree/main` or `/blob/...` subpage dedupes to the
two-segment repo. The model/dataset card (`README.md`, its YAML
frontmatter stripped) is the searchable content, its lead paragraph the
summary — cleaner than a dataset's `description` field, which the Hub
derives crudely from the card. The Hub flattens every tag into one noisy
array (frameworks, `region:us`, file formats), so concepts come from the
*structured* fields instead — the task (`pipeline_tag` for models,
`task_categories` for datasets) and the author's `cardData.tags`, the
github-topics parallel — while `library_name` and the license fill the
`tags` facet slot. The flat array is read only for its cross-reference
prefixes: an `arxiv:<id>` tag becomes an `arxiv.org/abs/<id>` link that
`scrolls related` resolves to the saved arXiv paper (the model↔paper
edge, kin to ADR 0038's preprint↔published edge — a saved model wires to
the paper that introduced it), a `dataset:<name>` tag becomes the
dataset's Hub page (the model↔dataset edge), and a `base_model:<id>` tag
becomes the base model's Hub page (the model↔base-model lineage edge,
deduped across the bare and `base_model:finetune:` forms). Spaces — hosted
demos and apps — are the third repo kind (`space:<org>/<name>`, ADR 0043):
the same adapter routes to `/api/spaces`, the `sdk`
(gradio/streamlit/docker) fills the `tags` facet `library_name` fills for a
model, the card `title` is the human name, and the card's `models`/`datasets`
lists become space↔model/dataset links — a saved demo wiring to the model
it serves and the dataset it draws on, surviving even a card-less degrade
since they come from the metadata. A model and a Space classify as `tool`
like a package, a dataset as `dataset` — the IDEAS.md §8 vocabulary term;
a repo with no card degrades to a metadata-only scroll, and site routes
and bare profiles register but have no repo to fetch), and
**go** (the keyless Go module proxy — see
`docs/adr/0042-go-modules-adapter.md`: a saved `pkg.go.dev/<module>` page
becomes a clean scroll from `proxy.golang.org` instead of a `trafilatura`
scrape of a JS-rendered docs page, the Go sibling of the package-registry
family and the last on the JSON-metadata pattern. Identity is the module
path kept verbatim — module paths are case-sensitive, and the proxy
*case-encodes* the request (`github.com/Masterminds/squirrel` →
`github.com/!masterminds/squirrel`), so the escaping touches the request,
not the identity; the module is everything before any `@version`, so a
versioned sub-package URL dedupes to its module, and a domain-first-segment
rule keeps the standard library and site routes from fetching. Go is the
sparsest adapter of the family: `/@latest` carries only the version,
publish time, and source `Origin`, so there is no description (`summary`
stays empty — honest, not synthesized), no keywords (`concepts` empty by
design, like RubyGems), and no license or classifier facet (`tags` empty
too). The one content the proxy holds is the `go.mod` manifest, fetched
from `/@v/<version>.mod` and kept as the searchable extracted text — the
module path plus its dependency graph, the first adapter whose content is
a manifest rather than prose. The source repository becomes the one
`link`: from `Origin.URL` when present — the only way to learn a vanity
path's repo (`golang.org/x/tools` → `go.googlesource.com/tools`) — else
derived from the module path for the well-known VCS hosts, resolving
through `scrolls related` to a saved github repo (the package↔repo edge).
A Go module classifies as `tool` like the other packages; the standard
library, search, and site routes register but have no module to fetch).
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

`scrolls import google-takeout <path>` bulk-imports YouTube watch
history from a Google Takeout export (IDEAS.md §13's bulk-archive path
for YouTube — see `docs/adr/0029-google-takeout-import.md`). `path` is
the Takeout `.zip`, an extracted directory, or `watch-history.json`
itself (JSON export format required). Takeout carries only the spine —
video URL, title, channel, watch time — so unlike the Field Theory
import, items enter at stage `detected` with the watch time as
`saved_at`, and `scrolls fetch` enriches them through the youtube
adapter like any synced feed entry. Repeat watches collapse to one item
(earliest watch wins), ads and deleted videos are counted as ignored
rather than failing the run, and item ids (`youtube:<videoId>`) dedupe
against `scrolls add` and feed sync. `scrolls fetch --limit N` paces
the enrichment of a large spine: at most N fetch attempts per run,
oldest saved first, resuming where the last run stopped — cron-able
and polite to the platform.

`scrolls import bookmarks <path>` bulk-imports a browser bookmarks
export — the Netscape-format `bookmarks.html` that Chrome, Firefox,
Safari, and Edge all emit (see
`docs/adr/0030-browser-bookmarks-import.md`). Like Takeout it is a
spine-only archive (URL, anchor text, `ADD_DATE`, folder placement),
so items enter at stage `detected` with the bookmark's `ADD_DATE` as
`saved_at`, and `scrolls fetch --limit N` paces their enrichment.
Unlike Takeout the spine is heterogeneous: every http(s) URL routes
through the same source detection and normalization as `scrolls add`,
so a bookmarked video becomes a `youtube` item, a repo a `github`
item, and everything dedupes against the library. Folder ancestry
becomes `tags` (root containers like "Bookmarks bar" are excluded as
browser furniture, and Firefox's `TAGS` attribute merges in), a `<DD>`
note seeds `summary`, and bookmarklets or `place:` smart folders are
counted as ignored rather than failing the run.

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
prints the full stored item. Every command that takes an item id also
accepts the item's URL — `scrolls show https://example.com/post`
resolves through the same normalization and detection as `add` (see
`docs/adr/0028-item-refs-accept-urls.md`) — so nobody has to compute
hash ids for web items.

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

`scrolls rm <id-or-url>...` takes items back out — the row, the
rendered scroll, and any captured media files, with the search index
following automatically (see `docs/adr/0027-rm-command.md`). A ref can
be the item id or the URL that saved it, in any tracking-decorated
spelling (ADR 0023's normalization applies), so the receipt from `add`
is also the handle for undoing it — and re-adding the echoed URL
reconstructs the item from the source. Files are deleted before the
row, so an interrupted removal is re-runnable rather than leaving
orphan files. There is no tombstone: an item still listed in a followed
feed returns on the next `sync`, so `unfollow` first when pruning a
feed; KB pages mentioning the removed scroll stay until the next
`scrolls kb`.

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
already saved. Adding `--batch` (ADR 0032) synthesizes every concept
that needs (re)generation in one Message Batches submission at half the
per-token price — same prompts, schema, validation, and incremental
skipping, polled until the batch ends — sharing the Batches transport
with `classify --engine llm --batch` (ADR 0022) in the LLM tier's
`llm.py`.

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
the pre-normalization duplicates ADR 0023 deferred (ADR 0026), and
`scrolls rm` to take items — row, scroll file, captured media — back
out of the library (ADR 0027), with the saved URL usable wherever a
command takes an item id (ADR 0028), and YouTube watch history
arriving in bulk via Google Takeout import with `fetch --limit` pacing
the enrichment (ADR 0029), plus browser bookmarks — the most universal
saved-content archive — via `import bookmarks` with folder names
becoming tags (ADR 0030), and a keyless Hacker News adapter so a saved
discussion becomes a clean scroll instead of a scrape of its comment
page, with link stories degrading to metadata-only and Show HN posts
classified as projects (ADR 0031), and the Batches API now halving the
cost of concept-summary synthesis too via `kb --engine llm --batch`,
sharing one Message Batches transport with bulk classification in the
LLM tier's `llm.py` (ADR 0032), and a keyless Stack Exchange adapter so
a saved Stack Overflow — or any network site's — question becomes a
clean scroll carrying the question and its accepted-first top answers,
with the question's tags as concepts and the whole network served by one
adapter (ADR 0033), and a keyless PyPI adapter so a saved package page
becomes a clean scroll from the project's latest-release metadata —
keywords as concepts, classifiers as tags, the source-repo URL as a
`related` edge, and the package classified as `tool` (the first rule to
produce that category), with the package name PEP 503-normalized so a
version-pinned page dedupes to the package (ADR 0034), and a keyless npm
adapter — the JavaScript sibling — so a saved `npmjs.com/package/<name>`
becomes a clean scroll with its README pulled from the registry packument
or, when that is empty (as it is for high-traffic packages), from the
published tarball, keywords as concepts and the normalized repository URL
as the package↔repo `related` edge (ADR 0035), and a keyless crates.io
adapter — the Rust sibling completing the package-registry trio — so a
saved `crates.io/crates/<name>` page becomes a clean scroll from the
crate's displayed-version metadata, its README extracted from the
published `.crate` tarball (the crate JSON carries no inline README), the
name folded like a PyPI one since crates.io is case-insensitive, keywords
as concepts, the curated category taxonomy as tags, and the normalized
repository URL as the crate↔repo `related` edge (ADR 0036), and a keyless
Crossref adapter so a saved `doi.org/<doi>` link becomes a clean scroll
from the work's registered metadata — title, authors, venue, date, and a
JATS abstract reduced to plain text — instead of a redirect into a
publisher paywall, classified as `paper` alongside arXiv so Scrolls now
spans both preprints and the published literature (ADR 0037), and the
arXiv adapter learning to record a preprint's published `arxiv:doi` as a
`doi.org` link so `scrolls related` wires a saved preprint to its
published paper, the literature loop closed both ways (ADR 0038), and
keyless Packagist (ADR 0039) and RubyGems (ADR 0040) adapters extending
the package-registry family to PHP/Composer and Ruby — both honestly
metadata-only (neither API ships a README), Packagist ranking its
`versions` map for the highest stable release with no comparator
dependency and RubyGems the simplest of the family (the latest version
inline), and a keyless Hugging Face Hub adapter so a saved model or
dataset page becomes a clean scroll from the Hub's structured metadata —
one adapter for both repo kinds (the kind in the item id), the card
README as searchable text, the task and card tags as concepts (not the
Hub's noisy flat tag soup), and the `arxiv:` tag wired to the saved arXiv
paper that introduced the model (the model↔paper edge, ADR 0041) and now
serving Spaces too — a saved demo's `sdk`, card title, and the models and
datasets it runs becoming space↔model/dataset edges (ADR 0043), and a
keyless Go modules adapter completing the package-registry family across
six languages — a saved `pkg.go.dev` module becomes a clean scroll from
the `proxy.golang.org` proxy, the go.mod manifest as searchable content
and the source repo (from `Origin` or the module path) as the package↔repo
edge, the sparsest of the family with no description, keywords, or license
facet to offer (ADR 0042). Next candidates: a native `x` fetch adapter so
saved tweets enrich beyond the Field Theory import; a DataCite adapter on
the same `doi.org` detection for dataset DOIs Crossref doesn't hold; or
two-phase batch submit/collect if a terminal wait ever outgrows the
library (ADR 0022, ADR 0032).

The library root is `~/.scrolls`, overridable with `$SCROLLS_HOME`.
