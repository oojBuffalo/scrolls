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
  library/        # compiled interlinked KB (index, graph, works, sources, categories, concepts, tags)
  agents/         # generated agent instruction files (SKILL.md, AGENTS.md)
  items/          # reserved (the raw record export is `scrolls export items`, to stdout)
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
uv run scrolls status         # initialized? schema? item/stage/source counts + custody headline, as JSON
uv run scrolls paths          # library layout, as JSON
uv run scrolls detect <url>   # URL → source adapter + source-local ID, as JSON
uv run scrolls add <url>      # register a URL as an item (stage: detected), as JSON
uv run scrolls ingest <url>   # add + fetch + md in one step, as JSON
uv run scrolls import fieldtheory [--root PATH]  # bulk-import X bookmarks from ~/.fieldtheory, as JSON
uv run scrolls import google-takeout <path>  # bulk-import YouTube watch history from a Takeout export, as JSON
uv run scrolls import bookmarks <path>  # bulk-import a browser bookmarks HTML export, as JSON
uv run scrolls import pocket <path>  # bulk-import a Pocket CSV data export, as JSON
uv run scrolls import opml <path>  # bulk-import feed subscriptions from an OPML file (RSS-reader export), as JSON
uv run scrolls import items <path>  # restore items from a Scrolls JSONL export (lossless), as JSON
uv run scrolls import events <path>  # restore the verify ledger from a JSONL export, deduped (whole-library portable custody, H72), as JSON
uv run scrolls export opml    # export feed subscriptions as an OPML document, to stdout
uv run scrolls export bookmarks  # export items as a Netscape bookmark file, to stdout
uv run scrolls export bookmarks --source github  # export a scoped slice (--source/--category/--tag), to stdout
uv run scrolls export items   # export items as a lossless JSONL stream (back up / migrate), to stdout
uv run scrolls export events  # export the verify ledger (custody events) as a lossless JSONL stream (back up custody, H72), to stdout
uv run scrolls export events --since 2026-06-16  # incremental backup: only checks since a boundary; the union re-imports idempotently (H75)
uv run scrolls export bundle "<query>" > briefing.md  # scoped, self-contained custody bundle: readable briefing + lossless block + verify-ledger events, shareable & re-importable
uv run scrolls import bundle <path>  # restore scrolls AND their custody ledger from a bundle, losslessly (the "take it with me" half); events dedup on re-import (H67), as JSON
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
uv run scrolls classify --stale  # refresh categories produced under a superseded ruleset (what doctor flags stale)
uv run scrolls classify --engine llm  # LLM pass: category + domain + concepts (needs ANTHROPIC_API_KEY)
uv run scrolls classify --engine llm --batch  # same LLM pass via the Batches API at half price
uv run scrolls set <id> category=tool tags=a,b  # set classification fields by hand; empty value clears
uv run scrolls rm <id-or-url> [...]  # remove items and the files they own, as JSON
uv run scrolls search <query> [--limit N]  # BM25-ranked full-text search, as JSON (default 20)
uv run scrolls search <query> --source arxiv --category paper  # scope the ranked match; filters AND, "" = unclassified
uv run scrolls search <query> --tag rust --concept "full text search"  # membership facets: tag case-insensitive, concept by slug
uv run scrolls search <query> --limit 20 --stats  # scope-honest {scope, stats, results} envelope: names the scope + marks truncation (completeness contract G2)
uv run scrolls show <id>      # print one item in full, as JSON
uv run scrolls history <id> [--limit N] [--since ISO] [--status V]  # the item's custody-ledger timeline (every verify check, newest first), as JSON; three filter axes applied verdict → window → cap: --status (unchanged/drifted/rotted/error), --since (time), --limit (count); [] when never verified (H66, H69, H71, H77)
uv run scrolls related <id> [--limit N] [--stats]  # items connected to one item, with reasons, as JSON (default 10); --stats adds the scope-honest envelope (G2)
uv run scrolls graph [--all]  # the whole-library link graph (nodes + directed edges), as JSON
uv run scrolls works [ref] [--min N]  # scholarly works clustered by DOI; echoes its scope (the --min floor or ref anchor) so the payload is completeness-honest (G2); with an id/URL, that item's work + siblings (ADR 0069, 0072)
uv run scrolls list           # list items, as JSON
uv run scrolls list --source web --stage detected --category ""  # filters AND together; "" = unclassified
uv run scrolls list --tag python --concept "machine learning"  # membership facets over tags/concepts (ADR 0059)
uv run scrolls list --drift drifted  # browse by custody drift posture; rows total `facets drift`'s count for it (H54)
uv run scrolls list --limit 50 --stats  # cap the listing + wrap it in the scope-honest envelope (completeness contract G2)
uv run scrolls facets         # the filterable vocabulary (sources/categories/tags/concepts) with counts, as JSON
uv run scrolls facets concepts --source arxiv  # one dimension, scoped by the same facets as search (ADR 0080)
uv run scrolls kb             # compile the interlinked library pages, as JSON
uv run scrolls kb --engine llm  # synthesize concept-page summaries first (needs ANTHROPIC_API_KEY), then compile
uv run scrolls kb --engine llm --batch  # same synthesis via the Batches API at half price
uv run scrolls context <query> [--limit N]  # compact context bundle, as Markdown (default 8); a Coverage: line marks "all N" vs "top N of M" so a capped bundle is never read as library-wide absence (G2)
uv run scrolls context <query> --budget index  # depth tier: index (catalog only) | connected (+ link graph) | full (+ excerpts, default) — identity/index first, deep bodies on demand
uv run scrolls context <query> --source arxiv  # scope the bundle (same --source/--category/--stage/--tag/--concept facets as search)
uv run scrolls agent install  # write agent instruction files, as JSON
uv run scrolls doctor         # check index/file-tree integrity, as JSON
uv run scrolls doctor --fix   # repair what is safe offline: merge dupes, rewrite scrolls, rebuild FTS
uv run scrolls maintain       # one scheduled custody pass: recheck → regenerate views → audit → custody delta since last run, as JSON
uv run scrolls maintain --no-recheck  # the offline pass: regenerate + audit + delta, no live re-capture
uv run scrolls maintain --history     # the custody trend: last N recorded runs (score/drift trajectory), as JSON
uv run scrolls maintain --history --trend  # + a one-word posture (improving/holding/regressing) over the window
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
become `concepts`), **wikidata**
(the structured-knowledge sibling of Wikipedia — see
`docs/adr/0075-wikidata-adapter.md`: a saved `wikidata.org` entity
(`Q<digits>`) becomes a clean scroll from the keyless entity-data `.json`
view instead of a `trafilatura` scrape of a concept-poor JS-rendered page.
Only **Q items** are claimed (Properties and Lexemes deferred as
schema/meta entities), the QID taken from the first path segment that is a
QID so the web permalink `/wiki/Q42`, the RDF concept URI `/entity/Q42`,
and the canonical `/wiki/Special:EntityData/Q42.json` all detect alike and
uppercase to one canonical id. The entity's `P31` (instance of) and `P279`
(subclass of) *type* relations become `concepts` — the ontological "what
kind of thing is this" signal, the direct analog of the wikipedia
adapter's page categories — their QID values resolved to labels in one
batched `wbgetentities` call (the Open Library author-key resolution
economized into a single request). The label is the `title`, preferring
the English label then the script-agnostic `mul` label Wikidata now mints
for names that read alike across languages (so Douglas Adams's name, stored
under `mul` with no `en`, is still found); the description is the
searchable `summary` with no `extracted_text` (Wikidata holds structured
facts, not a prose body — the Crossref/Open Library shape), and `tags` stay
empty by design. The English Wikipedia sitelink becomes an
`en.wikipedia.org` `link` — the Wikidata↔Wikipedia edge `scrolls related`
resolves to the saved article about the same subject — the official website
(`P856`) an outbound link too, and the representative image (`P18`) a
Commons `thumbnail`. A Wikidata entity classifies as `reference` like the
article about it; `raw_text` keeps only the projection the adapter consumed
since an entity can be hundreds of KB, and Property/Lexeme/portal pages
register but have no entity to fetch), **web** (readable
article extraction via `trafilatura`, the project's first per-adapter
dependency per ADR 0001), **youtube** (keyless oEmbed metadata plus
optional transcript via `youtube-transcript-api`; caption-less videos and
playlists degrade to metadata-only scrolls — see
`docs/adr/0003-youtube-adapter-oembed-transcripts.md`), **github**
(keyless REST API: repo metadata plus optional README; author-curated
repo topics become `concepts`, the first producer for the KB's concept
pages; set `GITHUB_TOKEN`/`GH_TOKEN` to lift the rate limit — see
`docs/adr/0007-github-adapter-topics-as-concepts.md`. A saved issue or
pull-request URL is a second content kind on the same source — see
`docs/adr/0084-github-issue-pr-adapter.md`: `github.com/<owner>/<repo>/issues/<n>`
and `/pull/<n>` detect as `owner/repo#<n>`, a discussion thread distinct
from the repo, and the adapter dispatches on the `#` in the id. The issues
endpoint serves both issues and PRs, so one path fetches the thread and a
second GET its conversation comments (degrading to body-only on failure);
the Markdown body and bylined comments become the searchable
`extracted_text`, the curated labels become `concepts`, the kind and state
(`issue`/`pull request`, `open`/`closed`/`merged`) become `tags`, and a
`github.com/<owner>/<repo>` link wires the issue↔repo edge. A thread gets
*no* category default — a bug, a feature request, and a design discussion
are too heterogeneous for one label — so it stays unclassified like a
Hacker News post until a title rule or the LLM engine names it),
**gist**
(the developer code-snippet sibling of the repo adapter, its own source
since `gist.github.com`'s host, API, and content all differ — see
`docs/adr/0078-github-gist-adapter.md`: one keyless `GET /gists/<id>`
returns the whole gist with each file's content inlined (the Lobsters
one-request economy), so a saved gist becomes a clean scroll instead of a
JS-rendered DOM scrape. Identity is the gist id alone (`gist:<id>`) — the
owner login in the URL is decorative, the API is keyed by the id and
resolves the owner, so `gist.github.com/<owner>/<id>`, a bare
`gist.github.com/<id>`, and a revision permalink all dedupe, the hex id
folded lowercase; a bare one-segment id is claimed only at full
modern-id length so a username's gist-list page isn't mistaken for a gist.
Each file becomes a sorted `### <filename>` fenced section in the
searchable `extracted_text`, the distinct file languages become `tags`
(the bitbucket `language`→tag facet) while `concepts` stay empty by design
(a gist has no topic facet), the `title` is the gist description else the
first filename, and the `summary` is a `"N files: …"` manifest. A gist
gets *no* category default — a snippet is heterogeneous (a config, a
script, a repro), so it stays unclassified like a Hacker News post until a
title rule or the LLM engine names it; the same `GITHUB_TOKEN`/`GH_TOKEN`
lifts its rate limit, and a gist whose files are all empty degrades to a
metadata-only scroll), **gitlab**
(the second major code host, keyless REST API on gitlab.com — see
`docs/adr/0055-gitlab-adapter.md`: project metadata plus optional README
fetched from the project's `/-/raw/` route; `topics` become `concepts`
like github's, the SPDX license key becomes a `tag`; nested-group project
paths are URL-encoded whole and folded lowercase; set `GITLAB_TOKEN` to
lift the rate limit and reach private projects. A saved issue or
merge-request URL is a second content kind on the same source, the github
thread template applied to GitLab — see
`docs/adr/0085-gitlab-issue-mr-adapter.md`: `/-/issues/<n>` and
`/-/merge_requests/<n>` detect as a discussion thread in GitLab's own
cross-reference notation, `group/project#<n>` for an issue and
`group/project!<n>` for a merge request. GitLab keeps *separate* iid
sequences for issues and MRs — so unlike github's unified `owner/repo#<n>`
the `#`/`!` marker must distinguish them, and it doubles as the endpoint
selector (`#` → `/issues/<iid>`, `!` → `/merge_requests/<iid>`). The
adapter dispatches on the marker, fetches the thread and its notes, and
maps the Markdown description and bylined comments to `extracted_text` —
dropping GitLab's automated *system* notes — while labels become
`concepts`, the kind and state become `tags`
(the state normalized to github's vocabulary, so `--tag merged`/`open`
spans both hosts), and a `gitlab.com/<project>` link wires the
thread↔project edge. gitlab.com serves the issue/MR metadata keyless but
gates the notes endpoint behind auth (anonymous callers get a 401), so a
keyless fetch degrades to body-only and `GITLAB_TOKEN` is what reaches the
conversation. Like a github thread it gets *no* category default and stays
unclassified until a title rule or the LLM engine names it), and **gitea**
(the third code host — Codeberg and gitea.com, one adapter for Gitea and
its API-compatible fork Forgejo (Codeberg runs Forgejo) the way the
mastodon adapter serves its forks — see
`docs/adr/0056-gitea-forgejo-adapter.md`: keyless
`GET /api/v1/repos/<owner>/<repo>`, repo metadata plus an optional README.
Unlike github/gitlab, the Gitea API lives on each *instance's own host*
(`codeberg.org/api/v1`, `gitea.com/api/v1`), not one fixed endpoint, so the
instance host rides in the item id — `gitea:<host>/<owner>/<repo>`, the
Fediverse `<host>/<id>` shape — and reaching a self-hosted instance later is
a detection-only change. Inline `topics` become `concepts` like github's
(no second call); Gitea carries no inline license, so `tags` stay empty
(github-parallel, not gitlab's license tag). The README is fetched
README.md-first via the keyless *API* raw route — the contents listing's
`download_url` is the web raw route, which login-gates anonymous gitea.com
clients, and listing a large repo's root times out (forgejo/forgejo did) —
with a root-listing fallback that finds a differently-named README
(`README.rst`); set `GITEA_TOKEN`/`FORGEJO_TOKEN` to lift the rate limit and
reach private repos; degrades to a metadata-only scroll), and **bitbucket**
(the fourth code host — Bitbucket Cloud's keyless `/2.0` API, see
`docs/adr/0057-bitbucket-adapter.md`: `GET /2.0/repositories/<workspace>/<repo>`.
Where gitea carries the instance host in the id because its API is per-host,
Bitbucket *Cloud* is a single hosted service (`api.bitbucket.org`), so it is
host-scoped with one fixed API host and the flat `<workspace>/<repo>` identity
github uses — *not* host-in-id. The id is folded lowercase (Bitbucket
auto-lowercases slugs and routes case-insensitively, so `/Workspace/Repo` and a
deep `/src/...` link dedupe to one repo — the gitlab fold, not github's
verbatim). Bitbucket Cloud has no repository-topics feature, so `concepts` stay
empty *by design* (the Go/RubyGems posture) — the repo's `language` is the one
structured facet it offers and becomes the single `tag` (github ignores
`language` because its richer topics fill that role). The README needs no
`/readme` endpoint (github) or `/raw/` route (gitea): a file's body comes from
the `/src/<commit>/<path>` route, which accepts a branch name, so the adapter
reads `mainbranch.name` and fetches `README.md` first (one fast keyless GET),
falling back to a root listing (`commit_file`/`commit_directory` entries) only to
find a differently-named README (`README.rst`) — the gitea README pattern on
Bitbucket's src endpoint. `title` is `full_name`, `author` the owner's
`display_name`, `published_at` the `created_on`, the canonical URL the
`links.html.href`; set `BITBUCKET_TOKEN` (a Bitbucket access token) to send
`Authorization: Bearer` and lift the rate limit; Bitbucket Server/Data Center,
the self-hosted product on a different API, is deferred like self-hosted GitLab;
degrades to a metadata-only scroll), and **arxiv**
(keyless Atom export API, stdlib XML: the abstract becomes the
searchable summary, taxonomy codes become `tags` and their display
names — "Computation and Language" for `cs.CL`, via a bundled taxonomy
table — become `concepts`, the PDF link is
recorded as `media`, and the paper's full text is extracted from the
PDF with `pypdf` into searchable extracted text — any PDF failure
degrades to the abstract-only scroll — see
`docs/adr/0008-arxiv-adapter-atom-abstracts.md`,
`docs/adr/0010-arxiv-pdf-full-text-pypdf.md`, and
`docs/adr/0012-arxiv-taxonomy-names-as-concepts.md`), and **biorxiv** and
**medrxiv** (arXiv's biology and medicine preprint siblings — see
`docs/adr/0068-biorxiv-medrxiv-adapter.md`: the two servers share one
operator and one keyless API
(`api.biorxiv.org/details/<server>/<doi>`, stdlib JSON) so one fetch
adapter serves both, but they stay two distinct sources because a
medRxiv paper does not live on bioRxiv; the highest version is the
scroll, the abstract becomes the searchable summary with no extracted
text and no PDF media — the `.full.pdf` 403s anonymous clients, unlike
arXiv's — the subject area becomes the one `concept`, the study type,
server, and CC license become `tags`, and the published-journal DOI
becomes a `doi.org` link to its Crossref scroll, the preprint↔published
edge arXiv and PubMed also carry; degrades to a metadata-only scroll),
and **pdf**
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
fetch), and **lobsters** (the keyless Lobsters JSON API — see
`docs/adr/0046-lobsters-adapter.md`: a saved `lobste.rs/s/<short_id>`
story becomes a clean scroll instead of a `trafilatura` scrape of its
HTML page, the third discussion-aggregator adapter beside Hacker News and
Stack Exchange. Its distinctive trait is economy: a story's `.json`
returns the submission, its tags, *and* the entire comment thread in one
request, where Hacker News defers comments (a fetch per node) and Stack
Exchange spends a second GET on answers. The API ships pre-rendered plain
text (`description_plain`, `comment_plain`), so there is no HTML grammar
to write. A link submission's article rides along in `links` like a
Hacker News link story, a text submission contributes its body, and
either way the comment thread — deleted/moderated comments skipped, each
bylined with author and score like a Stack Exchange answer, all kept
since they come free in the one request — becomes the searchable
extracted text. The curated tags (`css`, `security`, `ask`) become
`concepts` like github repo topics; the `summary` leads with the body
else the discussion status ("12 points, 1 comment"). Unlike Stack
Exchange's weak `reference` default, a Lobsters story gets *no* category
default — it is a heterogeneous aggregator entry, unclassified like
Hacker News until a title rule or the LLM engine names it. The short id
is the identity (`/c`, `/t`, `/u`, and front pages register but have no
story to fetch), and the raw thread with comment `depth` stays in
`raw_text` for a future threaded render; honestly keyless where Reddit's
`.json` now 403s unauthenticated clients), and **pypi** (the keyless PyPI JSON API — see
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
with a **datacite** fallback on the same `doi.org` detection (see
`docs/adr/0045-datacite-doi-fallback.md`: a DOI's registration agency —
Crossref for the published literature, DataCite for datasets, software,
and other repository outputs — can't be read off the URL, and the
`crossref:<doi>` identity is fixed at `add` time, so the `doi.py`
dispatcher resolves it at fetch time — Crossref first, DataCite when
Crossref 404s the DOI. A DataCite output keeps `source="crossref"` but
records `provenance.adapter="datacite"`, and its
`types.resourceTypeGeneral` rides in `provenance.resource_type` so the
rules engine classifies it by *what it is* — a dataset as `dataset`,
software as `tool`, the textual literature as `paper`, audiovisual as
`media`, an ambiguous type left unclassified — instead of forcing every
DOI to `paper`. The DataCite `attributes` map like Crossref's analogs:
titles joined with a subtitle, creators as "Given Family", the
`Abstract`-typed description as the searchable `summary` (no full text),
`subjects` as `concepts`, `resourceTypeGeneral`/`resourceType`/publisher
as `tags`, and the landing page plus the parent work's container DOI as
`links` — that container DOI resolving through `scrolls related`/`graph`
to a saved Crossref paper, a DataCite-output↔parent-work edge),
**pubmed** (the keyless NCBI E-utilities efetch API — see
`docs/adr/0065-pubmed-adapter.md`: a saved `pubmed.ncbi.nlm.nih.gov/<pmid>`
link becomes a clean scroll for the biomedical literature, the
life-sciences sibling of the arXiv and Crossref paper adapters, instead
of a `trafilatura` scrape of the abstract page that drops the record's
structure. Identity is the integer PMID; the dedicated host is claimed
wholesale (the PMID is the first path segment, subpages dedupe) while the
legacy `ncbi.nlm.nih.gov/pubmed/<pmid>` form is shape-matched so the
shared host's other databases — PMC, Gene, Nucleotide — fall through to
`web`. One efetch GET returns the record as XML, parsed with stdlib
ElementTree. The curated **MeSH** descriptors become `concepts` — the
controlled subject vocabulary that joins github topics and arXiv taxonomy
names in the KB concept graph — with author keywords the fallback for a
not-yet-MEDLINE-indexed article; the abstract (structured sections kept)
becomes a plain `summary` with no `extracted_text` (PubMed has no full
text, the Crossref shape); publication types and the journal venue become
`tags`; `published_at` prefers the electronic article date, then the
journal issue date, then the PubMed history; and the article DOI becomes a
`doi.org` `link` that resolves to its `crossref:<doi>` scroll — the
PubMed↔Crossref paper edge, the biomedical analog of the
arXiv preprint↔published edge. A PubMed record classifies as `paper`; a
record with no abstract is an honest metadata-only scroll),
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
family on the JSON-metadata pattern. Identity is the module
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
library, search, and site routes register but have no module to fetch),
and **pub** (the keyless pub.dev JSON API — see
`docs/adr/0088-pub-dev-adapter.md`: a saved `pub.dev/packages/<name>` page
becomes a clean scroll from the package's latest-version metadata, the
Dart/Flutter sibling of the package-registry family. One keyless `GET
pub.dev/api/packages/<name>` returns the whole package, `latest.pubspec`
its `pubspec.yaml` as JSON, so there is no version to select. Identity is
the package name folded lowercase — pub names are lowercase Dart
identifiers (`[a-z0-9_]`) and the API is case-sensitive (`packages/Provider`
404s, `packages/provider` resolves), so folding is the *forgiving* choice
the case-sensitive npm/RubyGems rule isn't: the canonical name is always
lowercase, so a mistyped capital is rescued, never missed, and version,
publisher, and search pages dedupe or register without a fetchable item.
What sets pub apart from its siblings RubyGems and Go — whose registries
carry no keywords — is that `pubspec.topics` become `concepts` like github
repo topics, so a saved package joins the KB concept graph; the package
description is the searchable `summary` with no `extracted_text` (the
README ships only in the package archive, not the JSON — RubyGems'
metadata-only situation). pub exposes no license or classifier facet, but
it does carry the one signal that matters across the ecosystem: a package
that declares the Flutter SDK (`environment.flutter` or a `flutter`
dependency) is tagged `flutter` — the family's first *derived* tag — so
`--tag flutter` separates Flutter plugins from pure-Dart packages, while a
pure-Dart package is left untagged rather than given a synthesized `dart`
label (Go's honest-empty posture). The `repository` and `homepage` become
`links`, the repository's `git+`/`.git` folded so it resolves to the
package's github repo through `scrolls related` (the package↔repo edge)
even when it points into a monorepo tree
(`github.com/flutter/packages/tree/main/packages/url_launcher`); a pub
package classifies as `tool` like every other package, and a package whose
pubspec lists no topics simply contributes empty `concepts`), and **hex**
(the keyless Hex JSON API — see `docs/adr/0089-hex-adapter.md`: a saved
`hex.pm/packages/<name>` page becomes a clean scroll from the package's
metadata, the Elixir/Erlang sibling of the package-registry family and
pub.dev's closest twin in field layout — a `meta` object holding the
description, the licenses, and a links map. One keyless `GET
hex.pm/api/packages/<name>` returns the whole package. Identity is the
package name folded lowercase — Hex names are lowercase and the API is
case-sensitive (`packages/Ecto` 404s, `packages/ecto` resolves), so folding
is the forgiving choice pub uses: the canonical name is always lowercase, so
a mistyped capital is rescued, version pages dedupe, and the docs host
`hexdocs.pm` is left to the `web` adapter since it serves rendered docs, not
package metadata. The `meta.description` is the searchable `summary` with no
`extracted_text` (the README ships only in the package tarball — RubyGems'
metadata-only situation). This is the axis on which Hex and its
layout-twin pub.dev diverge: pub's `topics` feed the KB concept graph, but
Hex has no keywords field, so its `concepts` are empty *by design* like
RubyGems and Go — the registry's data, not the adapter, deciding whether a
package can join the concept graph. The SPDX `meta.licenses` become `tags`;
and the `meta.links` map — a `{label: url}` of `GitHub`, `Changelog`,
`Docs` — becomes `links` by iterating its values (where RubyGems and pub
read named scalar fields), the `GitHub` entry resolving to the package's
github repo through `scrolls related` (the package↔repo edge). The publish
date is read from the release matching `latest_stable_version`, robust to a
pre-release topping the list; the author is left unset, since Hex exposes
only an owner list with emails and no clean byline), and **nuget**
(the keyless .NET package registry — see `docs/adr/0090-nuget-adapter.md`:
a saved `nuget.org/packages/<id>` page becomes a clean scroll, the ninth of
the package family and the one top-tier ecosystem it had not reached. NuGet's
rich registration API is **gzip-encoded even on a plain GET** — the shared
UTF-8 transport can't read it — and paginates for large packages, so the
adapter takes the **flat container** instead, the Go module shape (ADR 0042)
of two plain requests: `GET api.nuget.org/v3-flatcontainer/<id>/index.json`
returns the ascending version list, and the chosen version's `.nuspec`
manifest carries the metadata, parsed with stdlib ElementTree. The highest
listed version is often a pre-release, so the **latest stable** version is
selected by Packagist's comparator-free numeric ranking (ADR 0039). Identity
is the package id folded lowercase — the forgiving fold (PyPI/crates/pub/Hex
rule), since NuGet ids are case-insensitive and the flat-container path
*requires* the lowercase form — while the registrant's display casing
(`Newtonsoft.Json`) is read back from the nuspec `<id>` for the title and
canonical URL. The nuspec namespace URI varies by schema generation, so its
children are matched by *local* name. Author-curated `<tags>` (whitespace-,
comma-, or semicolon-separated) become `concepts` like PyPI keywords and
github topics, so the .NET ecosystem joins the KB concept graph a `web` scrape
would have left it out of; the `<description>` is the searchable `summary`
with no `extracted_text` (the README ships in the `.nupkg`, not the nuspec —
RubyGems' and Hex's metadata-only situation); the SPDX
`<license type="expression">` becomes the one `tag` (a `type="file"` names a
package file, not an SPDX id, so it is skipped); and `<projectUrl>` plus the
`<repository url>` become `links`, the repository resolving to the package's
github repo through `scrolls related` (the package↔repo edge). The nuspec
carries no publish date, so `published_at` is honestly left as the feed seed
(Go's honest-empty posture); a NuGet package classifies as `tool` like every
other package, and because the nuspec *is* the metadata its failure is a fetch
error rather than a metadata-only scroll, unlike Go's optional go.mod), and
**hackage** (the keyless Haskell package registry — see
`docs/adr/0091-hackage-adapter.md`: a saved `hackage.haskell.org/package/<name>`
page becomes a clean scroll, the tenth of the package family and the one that
breaks the JSON mold. One plain `GET hackage.haskell.org/package/<name>/<name>.cabal`
returns the latest version's **cabal** manifest — no API host and no version to
select (RubyGems' inline-latest economy) — but the cabal is an
indentation-structured `field: value` format, not JSON, so the adapter carries
a small cabal parser: top-level package fields sit at column 0 with
more-indented continuation lines, a column-0 line with no `field:` shape is a
section header (`library`, `source-repository head`) whose body is skipped
except the repository `location`, and `--` comments are dropped. Identity is the
package name preserved **verbatim** — Hackage names are case-sensitive
(`QuickCheck`, `HUnit`) and the cabal endpoint only resolves the exact case, the
npm/RubyGems rule — with the singular `/package/<name>` claimed (the browse list
is the *plural* `/packages/`) and a trailing dotted-numeric version stripped so
`/package/aeson-2.3.0.0` dedupes to `aeson` while `aeson-pretty` stays whole.
The `category` field is comma-separated curated keywords that become `concepts`
like github repo topics, so Haskell joins the KB concept graph; and unlike the
metadata-only registries, the cabal's `description` is a real prose body that
becomes the searchable `extracted_text` (the `.`-only line is cabal's
blank-line marker), with the `synopsis` the short `summary` — the first registry
whose own manifest carries prose. The `license` becomes the one `tag`, taken
verbatim (an SPDX id on modern cabals, a legacy cabal id like `BSD2` on older
ones); the `author`'s `<email>` is stripped to a clean byline; and the
`homepage` plus the `source-repository` `location` become `links`, the
repository resolving to the package's github repo through `scrolls related`
(the package↔repo edge). The cabal carries no upload date, so `published_at` is
honestly left as the feed seed (Go's and NuGet's honest gap); a Hackage package
classifies as `tool`, and a cabal with no `name` field is a fetch error rather
than a junk scroll), and **maven**
(the keyless Maven Central flat repository — Haskell's JVM successor and the
eleventh of the package family, reaching the largest ecosystem of all
(Java, Kotlin, Scala, Clojure, Groovy, Android) — see
`docs/adr/0092-maven-central-adapter.md`: a saved Maven artifact URL becomes a
clean scroll from the static repository `repo1.maven.org/maven2`, what a build
tool resolves against, rather than the rate-limited Solr search API or a
`trafilatura` scrape. Two plain requests, the Go/NuGet "version index + manifest"
shape (ADR 0042/0090): `GET /<group-path>/<artifact>/maven-metadata.xml` returns
the `<versioning>` with the `<release>` pointer, the `<versions>` list, and a
`<lastUpdated>` stamp, and the chosen version's `.pom` is the manifest, both
parsed with stdlib ElementTree. Identity is the Maven **coordinate
`groupId:artifactId`** — the family's only colon-joined coordinate (distinct from
Packagist's `vendor/name` slash), a reverse-DNS `groupId` (`com.google.guava`)
plus an `artifactId` (`guava`) — kept **verbatim** since the repository is a
literal, case-sensitive file tree (the npm/RubyGems/Hackage rule), with the
group **path-encoded** to address the directory (`com.google.guava` →
`com/google/guava`, the structural cousin of Go's request case-encoding).
Detection spans **two grammars**: the unambiguous `/artifact/<group>/<artifact>`
browse pages of the official UIs (`central.sonatype.com`, `search.maven.org`)
and the popular third-party index (`mvnrepository.com`, whose non-Central
artifacts degrade to a failed fetch), and the raw `/maven2/<group-path>/<artifact>`
file tree where the slash-encoded group is reassembled around the version
directory. The latest **release** is preferred from the index `<release>` —
which gets the stable build classifiers `-jre`/`-android` right where a "hyphen
means pre-release" heuristic fails (Guava's versions are all suffixed) — with a
SNAPSHOT-excluded numeric ranking the fallback. This is where Maven **diverges
from NuGet on two axes**: a POM has no keyword/topic facet, so its `concepts`
are empty *by design* (the RubyGems/Go/Hex posture — the JVM joins as a
metadata-and-edges source, not a concept source), and its `published_at` is read
from the **version index's `<lastUpdated>`** (`yyyyMMddHHmmss` UTC), the only
adapter whose date lives outside its own content manifest. The POM is parsed
namespace-agnostically (the nuspec lesson): `<name>` else the coordinate is the
`title`, the `<description>` the searchable `summary` with no `extracted_text`
(the README ships in the artifact jar — RubyGems'/NuGet's metadata-only
situation), the `<organization>` name else the lead developer the `author`, the
freeform `<licenses><license><name>` values the `tags` (kept verbatim, the
Hackage license rule), and the `<url>` plus the `<scm>` repository the `links`
— the SCM taken from `<scm><url>` or the `scm:<tool>:<url>`
`<connection>`/`<developerConnection>` (the ssh `git@host:path` and `git://`
forms normalized to https, the `.git` suffix stripped), the repository resolving
to the package's github repo through `scrolls related` (the package↔repo edge).
The POM *is* the metadata, so its failure is a fetch error rather than a
metadata-only scroll (NuGet's posture, unlike Go's optional go.mod); a Maven
artifact classifies as `tool` like every package, and parent-POM inheritance —
a multi-module child that inherits its description/licenses/scm from a
`<parent>` — is deferred), and
**datacite** (the
keyless DataCite JSON:API — see
`docs/adr/0045-datacite-doi-fallback.md`: not a new detected source but a
fetch-time fallback behind `crossref`'s `doi.org` detection, the second
DOI registration agency. The `doi.py` dispatcher tries Crossref first and
DataCite when Crossref 404s the DOI, so a dataset, software, or other
repository output deposited in Zenodo/Dryad/figshare becomes a clean
scroll classified by `types.resourceTypeGeneral` — `Dataset → dataset`,
`Software`/`Model` → `tool`, text types → `paper`, `Image`/`Sound` →
`media` — instead of falling to a `web` scrape; the source stays
`crossref` because identity is fixed at `add` time before the agency is
knowable, with `provenance.adapter="datacite"` recording the truth),
and a generic **content-negotiation** fallback on the same `doi.org`
detection (see `docs/adr/0081-doi-content-negotiation-fallback.md`: the
*third* tier of the `doi.py` dispatch, reached when both Crossref and
DataCite 404 a DOI. The DOI system has ~a dozen registration agencies —
JaLC (essentially the entire Japanese scholarly literature), mEDRA, KISTI,
OP, Airiti, CNKI — whose DOIs neither rich API holds, so rather than a
bespoke adapter per agency, `csl.py` reaches them all at once through DOI
**content negotiation**: a `https://doi.org/<doi>` GET with
`Accept: application/vnd.citationstyles.csl+json` is proxied by the resolver
to whichever agency holds the DOI, and every agency answers with the same
**CSL-JSON** document. CSL-JSON is Crossref's REST JSON's structural sibling
(`title`/`container-title` plain strings, authors carry `literal` for orgs),
so the Crossref mapping transfers almost verbatim — the JATS abstract
reduced to a plain `summary`, `subject` → `concepts`, `type` + venue →
`tags`, the landing `URL` → the one `link`, a record with no abstract an
honest metadata-only scroll. The `type` (recorded in
`provenance.resource_type`) defaults classification to `paper` like Crossref
— the post-DataCite agencies are scholarly-literature registries — while a
`dataset`/`software`/`figure` CSL type is honored instead of mislabeled;
the source stays `crossref`, `provenance.adapter="content-negotiation"` is
honest, and a parsed-but-non-CSL body raises rather than minting a junk
scroll), and **bluesky** (the keyless AT Protocol AppView — see
`docs/adr/0048-bluesky-adapter.md`: the open social-post source X could
never be. IDEAS.md §6 deferred X for its auth/session complexity, and X's
read API is now paywalled, so a keyless `x` adapter is off the table — but
Bluesky's `public.api.bsky.app` serves posts and their threads with no
login, cookie, or token. A saved `bsky.app/profile/<actor>/post/<rkey>`
post becomes a clean scroll instead of a `trafilatura` scrape of a
JS-rendered page. The wrinkle is identity: the URL carries a *handle* (or
a DID), but the thread endpoint is keyed by the post's AT-URI
(`at://<did>/app.bsky.feed.post/<rkey>`), which needs the DID — so a handle
URL costs one keyless `resolveHandle` GET (the Stack Exchange / Hugging
Face two-request shape) while a `did:` URL skips straight to the thread,
and the actor is folded lowercase in the `<actor>/<rkey>` source id since
handles and DIDs are case-insensitive. One `getPostThread` call returns
the post *and* its nested reply tree (the way a Lobsters story's `.json`
returns its comments): the post text leads the searchable
`extracted_text`, the replies follow as a `### Replies` subsection each
bylined with author and like count (deleted/blocked/empty nodes skipped),
and an image-only post contributes its images' alt text as the body so it
stays searchable. An external link card, a quoted post, and inline
`#link` richtext facets become `links` — a post pointing at an arXiv
paper, a github repo, or another saved post wiring to it through
`scrolls related`/`graph` (the quoted-post URL is the post↔post edge);
embedded images become `photo` media (the CDN's extensionless `…@jpeg`
URL resolving to `.jpg` through the same fallback tweet photos use); and
`#hashtag` facets become `concepts` like github repo topics. Posts have no
title, so one is synthesized from the byline and lead line; the `summary`
leads with the post's first paragraph, falling back for a textless post to
image alt text, then the link card's title, then the engagement status
("128 likes, 12 reposts, 3 replies"). Like Hacker News and Lobsters, a
heterogeneous social post gets *no* category default — unclassified until
a title rule or the LLM engine names it; the whole thread stays in
`raw_text` for a future nested render, and profile/feed/list/home routes
register but have no post to fetch), and **mastodon** (the keyless
Mastodon REST API — see `docs/adr/0049-mastodon-adapter.md`: the second
open social network after Bluesky, and the first source matched by URL
*shape* rather than host. Mastodon is federated — an account lives on one
of thousands of independent instances (`mastodon.social`, `hachyderm.io`,
`infosec.exchange`), so there is no host set to claim. Detection instead
recognizes a status by its shape on whatever instance the URL names —
`/@<user>/<digits>` (the web permalink) or `/users/<user>/statuses/<digits>`
(the ActivityPub object URL), both collapsing to one `<host>/<status_id>`
identity since a status id is unique only within its instance. The
all-digits id is the safety: it keeps a Medium `/@author/<slug>` post or a
Threads/TikTok `/@user/<kind>/<id>` from being stolen, and a misdetected
URL degrades to a benign failed fetch (the API 404s), never a wrong
scroll. The adapter talks to that same host's keyless API: one GET for the
status (`/api/v1/statuses/<id>`) and, when it has replies, a second for the
thread (`.../context`) — the two-request shape Bluesky and Stack Exchange
use, the context call skipped for a reply-less post and degrading to a
post-only scroll on failure. The post `content` is HTML, reduced to
searchable text by a stdlib parser (no `trafilatura` dependency); the
context's `descendants` arrive already flattened, so the bylined replies
render in one pass (Bluesky returns a nested tree). The external link card
and plain body links become `links` — `@mention` and `#hashtag` anchors
excluded as navigation, not references — so a post pointing at an arXiv
paper or github repo wires to it through `scrolls related`/`graph`; image
attachments become `photo` media and videos their preview image (alt text
searchable when the post has no text); `tags[].name` hashtags become
`concepts` like github topics. A `spoiler_text` content warning leads the
body so the hidden text stays honest, a boost unwraps to the post it
boosts, and the synthesized title and `summary` (lead else alt else card
title else "N favourites, M boosts, K replies") mirror Bluesky. Like
Bluesky, Hacker News, and Lobsters, a heterogeneous social post gets *no*
category default; the whole `{status, context}` stays in `raw_text`, and
profile, timeline, and tag routes carry no status id to fetch). The same
`mastodon` source and adapter now also serve its API-compatible forks —
**GoToSocial** and **Pleroma/Akkoma** (see
`docs/adr/0050-fediverse-forks-mastodon-api.md`): they expose the identical
keyless `/api/v1/statuses/<id>` + `/context` endpoints and return
Mastodon-shaped JSON, so only detection learns their extra routes —
GoToSocial's `/@<user>/statuses/<ULID>`, Pleroma/Akkoma's `/notice/<FlakeId>`,
and the shared ActivityPub `/users/<user>/statuses/<id>` — and their
non-numeric ids (a ULID, a FlakeId). The all-digits safety generalizes to
"a distinctive literal anchors the shape, the id constraint as strict as
that anchor is weak": the `statuses`-bearing forms admit any base62 id
because the `statuses` literal is unambiguous, while the weak `/notice/`
form carries a 16-char length floor a real FlakeId clears but a
`/notice/privacy` legal page does not; a Pleroma AP *Object* URL
(`/objects/<uuid>`) is left to `web` since its uuid is not a status id.
Identity stays `<host>/<status_id>` (web and AP forms still dedupe), and
`provenance.adapter` stays `mastodon` — the adapter that served it, the
specific fork unknowable from the URL.
The third open social network is **misskey** (the keyless Misskey API —
see `docs/adr/0051-misskey-adapter.md`: Misskey and its forks Sharkey,
Firefish/Calckey, and Foundkey are Fediverse software like Mastodon, but
they do *not* speak the Mastodon API, so — unlike GoToSocial and
Pleroma/Akkoma — Misskey is its own source and adapter, not another
mastodon URL shape. It is still detected the same host-less, shape-only
way: a `/notes/<id>` permalink on any instance becomes `misskey:<host>/<id>`,
the weak `notes` literal carrying a base62 + length floor of 10 — Misskey's
shortest id format, `aid` — so a `/notes/getting-started` slug or a
sub-floor word stays a web page and a misdetect degrades to a benign failed
fetch. A note is fetched with `POST /api/notes/show` (a JSON request body —
the first adapter to need the shared transport's new `post_json`) and its
replies with a second POST to `notes/children`, skipped when the note has
none and degrading to a note-only scroll on failure. The note `text` is MFM
(Misskey Flavored Markdown), already plain, so no HTML parser is needed
(Lobsters' economy); outbound links are scanned straight from the text and a
quote-renote's note becomes a post↔post link, both wiring through `scrolls
related`/`graph`; drive `files` become `photo`/video-thumbnail media (their
`comment` alt text searchable), bare-string `tags` become `concepts`, a `cw`
content warning leads the body, and a pure renote unwraps to the boosted
note. The synthesized title and `summary` (lead else alt else "N reactions,
M renotes, K replies") mirror Bluesky and Mastodon; like them it gets *no*
category default, and the whole `{note, children}` stays in `raw_text`).
The first federated *link aggregator* is **lemmy** (the keyless Lemmy API —
see `docs/adr/0052-lemmy-adapter.md`: Lemmy is the Reddit-shaped,
community-organized discussion site — the federated cousin of Hacker News
and Lobsters — and Fediverse software like Mastodon and Misskey, but it
speaks its own API, so like Misskey it is its own source and adapter, the
*third* Fediverse split by client API rather than host. It is detected the
same host-less, shape-only way: a `/post/<id>` permalink on any instance
becomes `lemmy:<host>/<id>`, the weak `post` literal carrying an all-digits
+ exactly-two-segments guard (Lemmy mints autoincrement integer post ids) —
so a blog's `/post/<slug>` or a `/post/<id>/<extra>` URL stays a web page,
and a misdetect degrades to a benign failed fetch. The API is plain GET, so
the shared `http.get_json` serves it (no `post_json`): a post is fetched
with `GET /api/v3/post?id=<id>` and its comments with a second GET to
`/comment/list`, skipped when the post has none and degrading to a
post-only scroll on failure. The comments arrive as a flat list whose
`path` (`0.<id>`, `0.<parent>.<id>`) encodes the thread tree, so they are
sorted into pre-order — a parent right before its replies — and bylined
with author and score like a Lobsters comment (deleted and mod-removed
comments skipped). Unlike the social posts, a Lemmy post has a *real* title
(it is an aggregator entry, like a Hacker News or Lobsters story), and its
`ap_id` is the canonical URL — pointing at the origin instance even when
fetched through another. A link post's external `url` becomes a `link` (the
article), a text post's Markdown `body` is the searchable content, and an
image post's `url` becomes `photo` media (told apart by `url_content_type`),
its pict-rs `thumbnail_url` a preview `thumbnail`; outbound URLs in the body
are scanned and the `cross_posts` — the same submission in other communities
— become post↔post links by `ap_id`, both wiring through `scrolls
related`/`graph`. The post's community (`c/rust`, its subreddit-like topical
home) becomes a `concept` like a github repo topic; the `summary` leads with
the body else the engagement status ("142 points, 4 comments"). Like Hacker
News, Lobsters, and the social posts, it gets *no* category default, and the
whole `{post, comments}` stays in `raw_text`. We target API v3, the
near-universal backwards-compatible surface; Lemmy 1.0's v4 keeps it
working). The same `/post/<digits>` shape is also served by **PieFed**
(see `docs/adr/0053-piefed-adapter.md`: PieFed is the *other* federated
link aggregator, and its post URL is byte-identical to Lemmy's — same
`/post/<integer-id>` shape — so it can't be told apart at detection. But its
API is its own: `/api/alpha` rather than Lemmy's `/api/v3`, with diverging
field names (`post.title` not `post.name`, `creator.user_name` not `name`,
`comment.body` not `content`, a `post_type` enum rather than
`url_content_type`). So PieFed can't ride Lemmy's adapter the way GoToSocial
rides Mastodon's, nor be its own detected source the way Misskey is — it is a
hybrid: its own *adapter* on Lemmy's *source*, reached by a fetch-time
fallback the way DataCite sits behind Crossref (ADR 0045). A new
`threadiverse` dispatcher backs the `lemmy` source: it tries Lemmy's
`/api/v3` first — Lemmy is far more deployed, so only a PieFed post pays the
one wasted request — and falls back to PieFed's `/api/alpha` when Lemmy 404s
the instance. Identity stays `lemmy:<host>/<id>`, minted before the backend
is knowable, and `provenance.adapter="piefed"` records which implementation
answered. The adapter mirrors Lemmy's behavior under the field-name mapping:
post + comments in two GETs, the flat comments sorted into thread pre-order by
their integer `path` and bylined, an image post told by `post_type=="Image"`,
a link/video post's `url` a `link` (so a PieFed video pointing at a YouTube
URL becomes a cross-source edge), cross-posts — which PieFed nests with a
`post_id` and no `ap_id` — becoming same-instance `/post/<id>` post↔post
links, the community a `concept`, no category default, and the `Poll`/`Event`
payloads kept in `raw_text` for a future render), and **discourse** (the
keyless Discourse forum `.json` view — see
`docs/adr/0054-discourse-adapter.md`: Discourse is the open-source software
behind countless dev communities (discuss.python.org, meta.discourse.org,
users.rust-lang.org), the *centralized-forum* sibling of the aggregators
Hacker News, Lobsters, Lemmy, and PieFed — and the **first non-Fediverse
host-less source**, proving the shape-only detection the Fediverse adapters
built generalizes beyond ActivityPub. Like them it has no host set to claim:
a `/t/<slug>/<topic_id>` topic on any instance becomes
`discourse:<host>/<topic_id>`, the display-only slug dropped from identity and
the all-digits id carrying the weak `t` literal — so a blog's `/t/<slug>` tag
page or a `/t/<slug>/<non-numeric>` stays a web page, and a misdetect degrades
to a benign failed fetch (the adapter validates the response is a Discourse
topic before producing a scroll, never a wrong one). Unlike the two-request
social and aggregator adapters, `GET /t/<id>.json` returns the topic *and* its
first page of posts in *one* request (Lobsters' economy): a real `title` (a
forum thread, not a synthesized social post), the opening post the searchable
body, the later posts a bylined `### Replies` section (moderator-action,
whisper, and deleted posts skipped), the `cooked` HTML reduced to text by a
stdlib parser (no `trafilatura`, Mastodon's rule). The topic's `tags` become
`concepts` like github topics, its outbound `details.links` — the
internal-navigation and incoming-reflection links filtered out — become
`links` so a thread pointing at an arXiv paper or github repo wires to it
through `scrolls related`/`graph`, and its representative `image_url` becomes a
`thumbnail`. The `summary` leads with the opening post else the engagement
status ("3 replies, 20 likes"); like Hacker News, Lobsters, Lemmy, and the
social posts it gets *no* category default. A long thread is bounded to the
first page, the full post-id `stream` surviving in `raw_text` for a later paged
render; category/user/tag routes carry no topic id to fetch), and **devto**
(the keyless dev.to / Forem articles API — see
`docs/adr/0061-devto-adapter.md`: dev.to is one of the largest
developer-blogging communities, and a saved `dev.to/<user>/<slug>` article used
to fall through to the `web` adapter, which extracts the text but produces no
`concepts` — so the post became a concept-less *island*, invisible to `scrolls
related`, the concept facets, and the KB concept pages. One keyless `GET
/api/articles/<user>/<slug>` returns the whole article, and the curated `tags`
(`python`, `api`, `webdev`) become `concepts` like github repo topics — the
structured signal the `web` scrape could never produce, finally wiring the post
into the concept graph. The identity `<user>/<slug>` is folded lowercase
because Forem mints lowercase handles and slugs and its API is case-sensitive —
only the lowercase form resolves (a mixed-case request 404s), the
gitlab/bitbucket fold — and a deeper link dedupes to the article. A subtlety
the API surfaces: for an organization post the URL handle is the *org* while
the byline `user` is a *person*, and the fetch keys on the handle (the org), so
`source_id` carries it and `author` reads `user.name`. The `body_markdown` is
already Markdown (no HTML grammar, Lobsters' economy) and becomes the searchable
text; the platform's `description` excerpt is the summary (else the body lead,
else a "45 reactions, 40 comments" engagement status). When the author
cross-posted from their own blog, the external original recorded in
`canonical_url` rides along in `links` as the cross-source edge while the
scroll's own canonical stays the dev.to permalink, and the `cover_image` becomes
a `thumbnail`. Like Hacker News, Lobsters, and the social posts, a heterogeneous
dev.to article gets *no* category default — the title rules and the LLM engine
decide; self-hosted Forem instances have no shape tell and are deferred like
self-hosted GitLab, and bare profiles and reserved site routes register but have
no article to fetch), and **rfc** (the keyless RFC Editor JSON view — see
`docs/adr/0066-rfc-adapter.md`: IETF **RFCs** are technical standards — the
normative protocol specs an agent cites constantly (HTTP's RFC 9110, TLS's
RFC 8446, JSON's RFC 8259, OAuth's RFC 6749) — a content type with no prior
first-class home, so a saved RFC link fell through to `web`, a concept-poor
unlinked island. One keyless `GET rfc-editor.org/rfc/rfc<N>.json` returns the
whole bibliographic record. Detection is host-restricted shape matching across the
RFC Editor and IETF hosts (`rfc-editor.org`, `datatracker.ietf.org`,
`tools.ietf.org`, `ietf.org`): only the `rfc<digits>` path shape is claimed, so an
Internet-Draft (`/doc/draft-…`), a working-group page, or the org site on those
same hosts falls through to `web` — the shared-NCBI-host posture (ADR 0065), not a
wholesale host claim. Identity is the integer RFC number with leading zeros
stripped, so `rfc0020` and `rfc20` dedupe to `rfc:20`, and the number leads the
title (`RFC 9110: HTTP Semantics`) and the scroll slug because an RFC's canonical
name *is* its number. The RFC Editor's curated `keywords` become `concepts` — the
controlled subject vocabulary that joins github topics, arXiv taxonomy, and MeSH
in the KB concept graph, with the whitespace-only placeholder older RFCs store
dropped — and the maturity `status` (`Internet Standard`, `Proposed Standard`,
`Informational`, …) is title-cased into the one `tag`, the controlled facet
Crossref's `type` fills. The abstract becomes the plain `summary`, and the
published spec text (`rfc-editor.org/rfc/rfc<N>.txt`) is fetched and normalized
into `extracted_text` so an agent can search the actual normative content
(`docs/adr/0067-rfc-full-text.md`, the arXiv abstract+PDF split): one de-pagination
pass strips the form-feed page breaks, `[Page N]` footers, and running headers
classic RFCs carry for print while the modern unpaginated format passes through,
and any `.txt` failure degrades to an abstract-only scroll (the arXiv PDF-degrade
contract). Two cross-document edges: the RFC's own DOI
(`10.17487/RFC<N>`, Crossref-registered) becomes a `doi.org` `link` resolving to
its `crossref:<doi>` scroll — the RFC↔Crossref edge, ADR 0038's analog — and each
`obsoletes`/`updates` target becomes an `rfc-editor.org/rfc/rfc<M>` `link`
resolving to that RFC's scroll, the RFC↔RFC standards-lineage edge (the inverse
`obsoleted_by`/`updated_by` relations are not re-emitted, since the graph resolves
edges in both directions). Publication dates are `Month Year`, padded to the first
of the month. An RFC classifies as `reference` — a normative spec to consult, like
a Wikipedia article, not a paper to cite; a record with neither an abstract nor
fetchable text is an honest metadata-only scroll, and STD/BCP sub-series and
Internet-Drafts are deferred), and **openlibrary**
(the keyless Open Library `.json` view — see
`docs/adr/0073-openlibrary-adapter.md`: **books** were the missing content
type, a saved `openlibrary.org` link falling through to `web` as a
concept-less unlinked island the way dev.to and RFCs did before their
adapters (ADR 0061/0066). Open Library is the Internet Archive's open,
keyless bibliographic catalog — books' Crossref — and models them in the
same FRBR sense `scrolls works` uses (ADR 0069): a *work*
(`openlibrary.org/works/OL…W`, the abstract book), an *edition*
(`/books/OL…M`, a specific manifestation), and an ISBN (`/isbn/<isbn>`,
which names an edition). All three are common save targets, so all three
are claimed, the kind riding in the item id — but the OLID's own type
letter (`W` for a work, `M` for an edition) already encodes
work-vs-edition, so only the ISBN form needs an explicit `isbn:` prefix
(the Hugging Face kind-in-id without the prefix). The OLID is uppercased to
a canonical form (Open Library routes case-insensitively but displays
uppercase — the crates/gitlab fold), a title slug or `/editions` subpage
deduping to it, and an ISBN is hyphen-stripped and `X`-uppercased. The
adapter routes on the id — a work reads `/works/<OLID>.json`, an edition
`/books/<OLID>.json`, an `isbn:` id `/isbn/<isbn>.json` (which Open Library
302-redirects to the edition record, urllib following it). The curated
`subjects` become `concepts` like github repo topics — the whole point of a
dedicated adapter, joining a book to the concept graph a `web` scrape never
could — with Open Library's administrative/accessibility flags
(`Accessible book`, `Open Library Staff Picks`) and library call numbers
(`Pz7.d1515`) filtered as noise, the list deduped case-insensitively and
capped; subjects live on the *work*, so an edition/ISBN fetch follows its
`works` ref with one extra GET to pull them (the Bluesky/Stack Exchange
two-request shape), degrading to the edition's own subjects on any failure.
The `description` blurb (a string or a `{value}` text object) becomes the
searchable `summary` with no `extracted_text` — the catalog holds metadata,
not the book's body, so a book is honestly summary-only (the Crossref/PubMed
shape) — and `tags` stay empty by design, a book having no clean controlled
facet like an RFC's status or a package's license (the go/rubygems posture).
Authors are named by key only (`/authors/OL…A`), so each is resolved with a
bounded GET to its name (truncated past a cap with "et al.", a failed lookup
skipped so the byline degrades rather than failing). An edition links to its
FRBR work (`/works/<OLID>`, the edition↔work edge `scrolls related`/`graph`
resolves when both are saved), a work's external `links` become outbound
edges, the first present cover (Open Library's `-1` "no cover" sentinel
skipped) becomes a `thumbnail` media ref on `covers.openlibrary.org`, and
free-form publication dates (`Aug 20, 2015`, `August 2015`, `2015`,
`2008-09`) parse to UTC ISO 8601 padded to the start of the period. No
category default is assigned: Open Library spans fiction and non-fiction, so
forcing `reference` (right for a textbook) would be dishonest for a novel —
the honesty value that keeps a medRxiv paper off the `biorxiv` label — so a
book flows through the title rules and otherwise stays honestly
unclassified, like a Hacker News post; author-bio enrichment, `identifiers`
cross-references (Wikidata/Goodreads), and a true work↔edition scroll merge
are deferred), and **zenodo**
(the keyless InvenioRDM REST API — see
`docs/adr/0083-zenodo-adapter.md`: research **datasets and software** were the
content type a saved `zenodo.org/records/<id>` landing page left as a `web`
scrape, a concept-less edgeless island the way dev.to and books were before
their adapters (ADR 0061/0073). Zenodo is CERN's general-purpose open-science
repository — the default archive for EU-funded output and the citable-DOI
snapshot every released GitHub repo gets. Its DOIs are *DataCite*-registered, so
a saved `doi.org/10.5281/zenodo.<id>` already fetches through the DataCite
adapter (ADR 0045) — but the URL researchers paste is the landing page, which
has its own keyless API (`zenodo.org/api/records/<recid>`, a plain JSON record
with no JSON:API envelope, stdlib only). Identity is the version-specific record
id the URL carries — taken from the digits after a `record`/`records` segment so
the modern `/records/<id>`, the legacy `/record/<id>`, and the pasted
`/api/records/<id>` forms all dedupe, deeper `/files`/`/preview` links deduping
to the record — kept verbatim because `conceptrecid`/`conceptdoi` name the
all-versions concept while the URL identifies one version (the Open Library
edition rule). The record's DOI becomes a `doi.org` `link` that ties the landing
page to its DataCite DOI scroll and clusters them as **one work** in `scrolls
works` (the DOI-edge pattern, ADR 0037/0045/0069); the `conceptdoi` links the
concept. The HTML `description` becomes the plain-text `summary` with no
`extracted_text` — the deposit's files are the body, not the catalog metadata,
so a record is honestly summary-only (the Crossref/DataCite shape), and the shape
that keeps the Zenodo scroll consistent with its DataCite-DOI twin. The
`resource_type.type` (`dataset`, `software`, `publication`, `image`, `video`, …)
rides in `provenance.resource_type` and the rules engine maps it — `dataset →
dataset`, `software → tool`, `publication → paper`, `image`/`video → media`, the
ambiguous `poster`/`presentation`/`lesson` honestly unclassified — the DataCite
fetch-time-fact mechanism (ADR 0045), since a deposit is not always a paper.
Free-text `keywords` and controlled `subjects` become `concepts` (the
github-topics/MeSH role), and `type`/`subtype`/`license.id` become `tags`. Each
`related_identifiers` entry becomes an outgoing edge by its scheme — a `doi` to
`doi.org`, an `arxiv` to `arxiv.org/abs` (the preprint edge, ADR 0038, the
`arXiv:` prefix stripped), a `url` kept when http(s), other schemes skipped as
dead links — so a dataset that supplements a paper or archives a repo wires into
the graph; partial publication dates (`2023`, `2023-04`) pad to the start of the
period (the RFC rule). Version↔concept consolidation, the deposit's files as
captured media, and self-hosted InvenioRDM are deferred).
Items from
sources without an adapter yet (today only `x`) are
skipped, and per-item failures don't abort the batch.

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

`scrolls export bookmarks` is the inverse (see
`docs/adr/0079-bookmarks-export.md`): it serializes the library's items
back to a Netscape bookmark file on stdout, so a curated Scrolls library
can move into any browser or read-later tool, or be backed up —
`scrolls export bookmarks > bookmarks.html`. The export carries each
item's spine — URL, title, `saved_at` as `ADD_DATE`, and `tags` as a flat
`TAGS` attribute (a browser ignores the attribute but keeps the bookmark;
Pinboard-style tools read it) — while the extracted content stays in the
Markdown scrolls. An item with no title labels itself by its URL, and the
round-trip is the contract: an export re-imports to the same items. With
import and export, `import bookmarks` is a way-station rather than a sink.
By default the whole library is exported; the same durable item-property
filters `scrolls list` offers — `--source`, `--category`, `--tag` — scope
it to a slice, so `scrolls export bookmarks --source github > repos.html`
exports just the github items.

`scrolls import pocket <path>` bulk-imports a Pocket data export — the
CSV (`title,url,time_added,tags,status`) Mozilla mailed users when
Pocket shut down in 2025, where the saved internet of a large population
lived (see `docs/adr/0074-pocket-import.md`). `path` is the export
`.zip` (large accounts split across `part_*.csv`), a directory of CSV
parts, or a single `.csv`. It reuses the bookmarks spine wholesale:
items enter at stage `detected` with `time_added` as `saved_at`, every
URL routes through the same detection/normalization as `scrolls add`
(so a saved video becomes a `youtube` item and dedupes against the
library), pipe-delimited Pocket `tags` become `tags` curation, and a
title equal to the URL — Pocket's "no title" marker — is dropped so
fetch fills the real one. The unread/archive `status` split is reported
as migration context, blank or non-http rows are counted rather than
failing the run, and `scrolls fetch --limit N` paces the enrichment of a
years-deep pile. Columns are read by header name, so the importer also
takes any CSV carrying a `url` column.

`scrolls import opml <path>` bulk-imports feed subscriptions from an OPML
file — the universal feed-list format every RSS reader (Feedly,
Inoreader, NetNewsWire, Reeder, …) exports (see
`docs/adr/0076-opml-import.md`). It is the bulk sibling of single-feed
`scrolls follow`, and the one import that produces **subscriptions**
rather than items: an OPML file lists feeds, not saved pages, so each
feed outline becomes a row in the same subscription table `scrolls
follow` writes, and the first `scrolls sync` discovers each feed's
entries. Unlike `follow`, which fetches a feed once to validate it, OPML
import is network-free like the other bulk imports — an export can hold
hundreds of feeds and the `xmlUrl` is declared to be a feed by the
exporting reader, so a dead feed surfaces only on its first sync, failing
its own subscription and never the batch. A feed imported here gets the
same subscription id a manual `follow` of that URL would mint, so the two
acquisition paths dedupe; folders are walked through but dropped (a
subscription carries no tags), and non-http feeds are counted rather than
failing the run.

`scrolls export opml` is the inverse (see
`docs/adr/0077-opml-export.md`): it serializes the library's feed
subscriptions back to an OPML 2.0 document on stdout, so the feeds you
curate in Scrolls can move to another reader, get backed up, or sync a
second device — `scrolls export opml > feeds.opml`. The export is flat
(subscriptions carry no folders), each feed one `<outline>` with its feed
URL, and the round-trip is the contract: an export re-imports to the same
feeds. With import and export, Scrolls is a way-station on a feed list's
life rather than a sink.

`scrolls export items` / `scrolls import items <path>` are the **lossless**
export pair (see `docs/adr/0082-items-jsonl-export.md`): the export
serializes the whole library to a JSON Lines stream on stdout
(`scrolls export items > library.jsonl`) and the import restores it. Where
`export bookmarks` and `export opml` round-trip against external tools — and
so carry only a spine those formats can hold — this round-trips against
Scrolls' own model, so it carries every field: extracted text, links, media
refs, provenance, content hash, and stage. That makes it the backup,
migration, and library-merge format. The import restores the index rows
(`INSERT OR IGNORE` by id, so re-imports are cheap and never overwrite);
the derived artifacts rebuild from them with `scrolls doctor --fix` and
`scrolls kb`. That export→rebuild round-trip is byte-verified end to end
(`tests/test_roundtrip.py`, `docs/adr/0099-lossless-roundtrip-invariant.md`):
the rebuilt scrolls, `library/`, re-export, and search match the original,
with captured media blobs the one thing a JSONL backup can't carry (doctor
reports them for `scrolls media` to re-download). The same
`--source`/`--category`/`--tag` filters as `export bookmarks` scope a slice.
`scrolls export events` / `scrolls import events <path>` are the **custody**
companion (H72): the verify ledger as a lossless JSONL stream, so a whole-library
backup carries the *custody record* — every `verify` check — alongside the items.
Import dedups by content (the same idempotent restore the bundle uses), so
re-importing a backup is a custody no-op.

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
so arbitrary agent input never hits FTS5 syntax errors. Optional
`--source`, `--category`, and `--stage` facets scope the ranked match
(see `docs/adr/0058-faceted-search.md`): with 30+ heterogeneous sources
in one library, they answer "what *papers* does my library know about
transformers" (`--source arxiv` or `--category paper`) or "which
*unclassified* items mention SQLite" (`--category ""`) — the filters AND
with the match and with each other, leaving the BM25 order untouched, and
mirror `scrolls list`'s exactly (`""` selects unclassified). Two more
facets, `--tag` and `--concept`, scope by *membership* in the JSON list
columns (see `docs/adr/0059-tag-concept-facets.md`): `--tag` matches
case-insensitively and `--concept` by slug — exactly as `scrolls related`
and the KB concept pages compare them, so `--concept "full text search"`
finds an item whose concept is `Full-text search` — answering "papers
about transformers *tagged* efficient" or "items carrying the *BM25*
concept". They AND with the other facets and carry no empty-string
overload (a value nothing has returns nothing). All five facets flow
through `scrolls list`, `scrolls context`, and the MCP `search_scrolls`
and `get_context_bundle` tools. `scrolls show <id>`
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

`scrolls graph` materializes the whole library's link structure at once
(ADR 0044): every item's links resolved into directed edges (`from → to`,
with the matching link as `via`), using the same source-detecting match
`related` uses. Where `related` explores one item's neighborhood, the
graph is the connective tissue the adapters have been building — a model
to its paper, a preprint to its published DOI, a Space to the model it
serves — in a single JSON object an agent can reason over. Nodes are the
connected items; `--all` includes isolated ones too.

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
existing category; `scrolls classify <id>` explicitly reclassifies, and
`scrolls classify --stale` re-runs the engine over exactly the items
`scrolls doctor` flags as classified under a superseded ruleset —
regeneration on request, never doctor's silent overwrite.
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
`library/index.md`, `library/graph.md`, `library/works.md`, plus
per-source, per-category, per-concept, and per-tag pages that link back to
rendered scrolls with relative Markdown links. The generated pages are rebuilt from scratch each
run so stale groups can't linger; other files under `library/` are left
alone. Concept pages merge spellings by slug; github repo topics, wikipedia
page categories, and arXiv taxonomy names populate them today. `library/tags/`
pages (see `docs/adr/0064-kb-tag-pages.md`) are the browsable complement to
the `--tag` query facet: the library's items grouped by each `tag` — arXiv
taxonomy codes, SPDX licenses, languages, classifiers, bookmark folders —
**case-insensitively** the way `--tag` matches (so `MIT` and `mit` are one
page while `C++` and `C#` stay two despite sharing the slug `c`, the page
filenames disambiguated with a numeric suffix), each ending with a
**Related Tags** co-occurrence section like a concept page's. `library/graph.md`
is the browsable form of `scrolls graph`'s link structure (see
`docs/adr/0062-kb-link-graph-page.md`): the rendered scrolls that link to
one another — a model wired to its paper, a package to its repo — grouped
into clusters (connected components), largest first, each rendered as an
adjacency list of members and their `→ target` edges; built over rendered
items only so every link on the page resolves to a scroll file, always
written (empty → `No linked scrolls yet.`), and linked from the index.
`library/works.md` is the browsable form of `scrolls works`'s DOI
clustering (see `docs/adr/0070-kb-works-page.md`): the rendered scrolls
that are the same scholarly work — a preprint and its published article, an
indexing record — grouped under the DOI that names the work, each a
`## <doi>` section linking its representations' scrolls; built over rendered
items only, always written (empty → `No works held in multiple
representations yet.`), and linked from the index.
Each concept page additionally ends with a **Related Concepts** section
(see `docs/adr/0063-kb-related-concepts.md`): the concepts that co-occur on
its member scrolls, ranked by how many scrolls carry both — the
deterministic concept-graph complement to `graph.md`'s link graph, kept on
the concept pages (where a concept's neighbours are a short ranked list)
rather than as `scrolls graph` edges (where concept cliques would swamp the
sparse link edges).

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
can follow up with `scrolls show <id>` or read the full scroll. When the
matches link to or from other saved scrolls, a **Connected scrolls**
section lists those neighbors from the link graph (ADR 0047) — a match's
arXiv paper, source repo, or parent dataset that keyword search alone
would miss — each naming the match and direction that pulled it in, so
the cross-source edges the adapters built (model↔paper, package↔repo,
dataset↔parent-work) surface in the bundle itself, not only in
`scrolls related`/`scrolls graph`. The same `--source`, `--category`, and
`--stage` facets `scrolls search` takes (ADR 0058) scope the bundle —
`scrolls context "attention" --source arxiv` answers "what do the *papers*
say about X" — and a scoped bundle names its facets in the title so it
stays self-documenting once dropped into context.

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
`get_related_scrolls`, `get_concept_page`, `get_tag_page`, `list_sources`,
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
facet to offer (ADR 0042), and a keyless DataCite adapter reached by a
fetch-time fallback behind `crossref`'s `doi.org` detection, so a dataset,
software, or other repository-deposited DOI Crossref doesn't hold becomes
a clean scroll classified by its resource type — the first time two fetch
adapters serve one detected source through the `doi.py` dispatcher, with
the source name held to `crossref` because identity is minted before the
registration agency is knowable (ADR 0045), and a keyless Lobsters
adapter joining Hacker News and Stack Exchange as the third
discussion-aggregator source — and the cheapest, since a story's `.json`
returns the submission, its tags, and the whole comment thread in one
request, classified like Hacker News with no category default (ADR 0046),
and a keyless Bluesky adapter reaching the social-post source IDEAS.md §6
deferred X for — on the open AT Protocol AppView, no login, where X's read
API is now paywalled — so a saved `bsky.app` post becomes a clean scroll
carrying its text and reply thread (one `getPostThread` call, after a
`resolveHandle` GET turns a handle into the DID the AT-URI needs), its
external card / quoted post / inline links as edges, its images as media,
and its hashtags as concepts, classified like Hacker News and Lobsters
with no category default (ADR 0048), and a keyless Mastodon adapter
reaching the *second* open social network — and the first source matched
by URL *shape* rather than host, since the Fediverse is federated across
thousands of instances with no host set to claim: a saved
`<instance>/@<user>/<id>` (or `/users/<user>/statuses/<id>`) status becomes
a clean scroll from that instance's keyless REST API, its all-digits id the
safety that keeps Medium/Threads lookalikes out and a misdetect a benign
failed fetch; status + thread are two requests like Bluesky, the HTML
content reduced to text by a stdlib parser (no `trafilatura`), the flat
`descendants` rendered as bylined replies in one pass, the card and body
links as edges, images and video previews as media, hashtags as concepts,
a content warning leading the body, a boost unwrapped, classified like
Bluesky and Hacker News with no category default (ADR 0049), now also
serving the Mastodon-API-compatible forks **GoToSocial** and
**Pleroma/Akkoma** on the same source and fetch adapter — they expose the
identical `/api/v1/statuses` surface and return Mastodon-shaped JSON, so
only detection learns their routes (GoToSocial's `/@<user>/statuses/<ULID>`,
Pleroma's `/notice/<FlakeId>`, the shared AP `/users/<user>/statuses/<id>`)
and non-numeric ids, the all-digits safety generalizing to a literal anchor
plus a `/notice/` length floor (ADR 0050), and a keyless Misskey adapter
reaching the Misskey-family software (Sharkey, Firefish, Foundkey) on its
`/notes/<id>` shape — which, unlike the mastodon forks, speaks its *own*
`POST /api/notes/show` API rather than Mastodon's, so the Fediverse is now
covered by two adapters split by client API not host (ADR 0051), and a
keyless Lemmy adapter reaching the first federated *link aggregator* — the
Reddit-shaped cousin of Hacker News and Lobsters — on its `/post/<digits>`
shape, which like Misskey speaks its own API (`GET /api/v3/post`) rather
than Mastodon's, the *third* Fediverse split by client API: a post + its
comment thread are two GETs (the shared `http.get_json`, no `post_json`),
the flat comments sorted into thread pre-order by their `path` and bylined
like Lobsters, a *real* title (it is an aggregator entry, not a synthesized
social post), the link/text/image post handled by `url_content_type`, body
URLs and `cross_posts` as edges, the community as a concept, classified with
no category default (ADR 0052), and a keyless **PieFed** adapter joining it on
the *same* `lemmy` source — PieFed shares Lemmy's byte-identical
`/post/<digits>` URL (so it can't be told apart at detection) but speaks its
own `/api/alpha` API with diverging field names (so it can't ride Lemmy's
adapter either), making it a hybrid: its own *adapter* on Lemmy's *source*,
reached by a fetch-time `threadiverse` dispatcher (Lemmy first, PieFed
fallback) the way DataCite sits behind Crossref, with `source="lemmy"` kept
and `provenance.adapter="piefed"` recording the truth (ADR 0053). The
discussion family then reached the *forums*: **Discourse** — the centralized
forum software behind countless dev communities — joins on its
`/t/<slug>/<id>` topic shape, the first non-Fediverse host-less source, its
topic and first page of posts fetched from the keyless `.json` view in one
request (ADR 0054). The DOI dispatch then grew a **third tier** behind
Crossref and DataCite: rather than a bespoke adapter per remaining
registration agency (the named candidate was "a third agency, mEDRA/JaLC"),
a generic **content-negotiation** adapter (`csl.py`) reaches *every* other
agency at once — a `doi.org/<doi>` GET asking for CSL-JSON is proxied to
whichever agency holds the DOI (JaLC, mEDRA, KISTI, OP, Airiti, CNKI, …) and
all answer in one uniform format, so a DOI neither Crossref nor DataCite
holds becomes a clean scroll instead of a foreign-language paywall scrape;
it is the third tier of `doi.py`, reached only when both rich agencies 404,
`provenance.adapter="content-negotiation"` recording the agency-agnostic
truth (ADR 0081). Next candidates: home-instance-canonical
Mastodon/Misskey/Lemmy and DID-canonical Bluesky identity so a post saved
through two routes dedupes — the fetch-time id rewrite no adapter does yet
(ADR 0048–0053); or two-phase batch submit/collect if a terminal wait
ever outgrows the library (ADR 0022, ADR 0032). **Mbin** (the kbin fork) was
the named next aggregator, but its read API is OAuth-gated — its
`security.yaml` grants no anonymous `/api/entry` and live instances 401/403 an
unauthenticated read — so it cannot be a keyless adapter without a
client-credentials token dance, and is deferred (ADR 0054). A native `x` fetch adapter
remains out of reach while X's read API stays paywalled; `x` enriches only
through the Field Theory import (ADR 0009).

Custody integrity is a first-class, network-free report: `scrolls doctor`
carries a `custody` block with each item's **fidelity** tier — `full` (a
re-derivable body is held), `partial` (degraded but honest), or `reference`
(pointer and provenance only) — and a percent-clean integrity **score** over
per-item findings, with `fidelity` queryable as its own facet (ADR 0097). On
top of that, `scrolls verify` re-captures a held item through its adapter and
records a drift/rot **custody event** — `unchanged`, `drifted` (the source
changed since capture), `rotted` (HTTP 404/410, gone), or `error` (could not
check) — into an append-only ledger *without* overwriting the original
capture, and `scrolls doctor` aggregates the latest verdict per item into its
`custody.drift` report, so the library can always answer "what have I lost, or
what changed, since I saved it?" (ADR 0098). `scrolls history <id>` reads that
ledger back per item — the full timeline of every check, newest first — so an
agent can see *when* a source drifted and *how often* it has been re-checked,
not just its current posture. That custody record is **portable**: a
`scrolls export bundle` carries the in-scope items' verify ledger alongside
their canonical rows, and `scrolls import bundle` restores it — deduped so a
re-import is a custody no-op — so a recipient inherits the drift *history*, not
just the exporter's last-seen posture frozen in prose (H67).

The library root is `~/.scrolls`, overridable with `$SCROLLS_HOME`.
