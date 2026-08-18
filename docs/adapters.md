# Source adapters

Scrolls captures each saved item through a source-specific **adapter**. `scrolls
fetch` runs the adapter for each detected item, filling in title, extracted text,
summary, canonical URL, content hash, and provenance, and moving the item to stage
`fetched`. Items from sources without an adapter yet (today only `x`) are skipped,
and per-item failures don't abort the batch.

`x` is the one source that has a capture path but no *fetch* adapter: bookmarks
arrive already-captured through `scrolls sync x --bookmarks`. See
[`x`](#x) below for what that costs.

This page catalogs the adapters that exist today and the custody shape each one
captures. For the adapter *contract* (identity rules, fidelity tiers, and how to
add one), see [`architecture.md`](architecture.md) — "The source adapter model" and
"Adding a new adapter". Each adapter's decision record lives in
[`adr/`](adr/README.md).

*Amended: 2026-07-27 — catalog restructured into per-adapter sections for
readability; content unchanged.*

## Adapters so far

### wikipedia

A saved Wikipedia article becomes a scroll through the MediaWiki action API, with
no dependencies.

- **Captured:** visible page categories become `concepts`.
- **Decision:** `docs/adr/0002-first-fetch-adapter-wikipedia.md`.

### wikidata

The structured-knowledge sibling of Wikipedia: a saved `wikidata.org` entity
(`Q<digits>`) becomes a clean scroll from the keyless entity-data `.json` view
instead of a `trafilatura` scrape of a concept-poor JS-rendered page.

- **Identity:** only **Q items** are claimed (Properties and Lexemes deferred as
  schema/meta entities). The QID is taken from the first path segment that is a
  QID, so the web permalink `/wiki/Q42`, the RDF concept URI `/entity/Q42`, and
  the canonical `/wiki/Special:EntityData/Q42.json` all detect alike and
  uppercase to one canonical id.
- **Captured (concepts):** the entity's `P31` (instance of) and `P279`
  (subclass of) *type* relations become `concepts` — the ontological "what kind
  of thing is this" signal, the direct analog of the wikipedia adapter's page
  categories — their QID values resolved to labels in one batched
  `wbgetentities` call (the Open Library author-key resolution economized into a
  single request).
- **Captured (title and summary):** the label is the `title`, preferring the
  English label then the script-agnostic `mul` label Wikidata now mints for
  names that read alike across languages (so Douglas Adams's name, stored under
  `mul` with no `en`, is still found). The description is the searchable
  `summary` with no `extracted_text` (Wikidata holds structured facts, not a
  prose body — the Crossref/Open Library shape), and `tags` stay empty by
  design.
- **Captured (links and media):** the English Wikipedia sitelink becomes an
  `en.wikipedia.org` `link` — the Wikidata↔Wikipedia edge `scrolls related`
  resolves to the saved article about the same subject — the official website
  (`P856`) an outbound link too, and the representative image (`P18`) a Commons
  `thumbnail`.
- **Degrades:** `raw_text` keeps only the projection the adapter consumed, since
  an entity can be hundreds of KB. Property/Lexeme/portal pages register but
  have no entity to fetch.
- **Classification:** a Wikidata entity classifies as `reference`, like the
  article about it.
- **Decision:** `docs/adr/0075-wikidata-adapter.md`.

### web

Readable article extraction via `trafilatura` — the project's first per-adapter
dependency, per ADR 0001 (`docs/adr/0001-implementation-stack.md`).

### youtube

Keyless oEmbed metadata plus an optional transcript via `youtube-transcript-api`.

- **Degrades:** caption-less videos and playlists degrade to metadata-only
  scrolls.
- **Decision:** `docs/adr/0003-youtube-adapter-oembed-transcripts.md`.

### github

A saved repository URL becomes a scroll from the keyless GitHub REST API: repo
metadata plus an optional README. A saved issue or pull-request URL is a second
content kind on the same source — a discussion thread distinct from the repo.

- **Identity (threads):** `github.com/<owner>/<repo>/issues/<n>` and
  `/pull/<n>` detect as `owner/repo#<n>`, and the adapter dispatches on the `#`
  in the id.
- **Captured (repos):** author-curated repo topics become `concepts` — the
  first producer for the KB's concept pages.
- **Captured (threads):** the issues endpoint serves both issues and PRs, so
  one path fetches the thread and a second GET its conversation comments. The
  Markdown body and bylined comments become the searchable `extracted_text`,
  the curated labels become `concepts`, the kind and state (`issue`/`pull
  request`, `open`/`closed`/`merged`) become `tags`, and a
  `github.com/<owner>/<repo>` link wires the issue↔repo edge.
- **Degrades:** set `GITHUB_TOKEN`/`GH_TOKEN` to lift the rate limit; a failed
  comments fetch degrades a thread to body-only.
- **Classification:** a thread gets *no* category default — a bug, a feature
  request, and a design discussion are too heterogeneous for one label — so it
  stays unclassified like a Hacker News post until a title rule or the LLM
  engine names it.
- **Decision:** `docs/adr/0007-github-adapter-topics-as-concepts.md` (repos)
  and `docs/adr/0084-github-issue-pr-adapter.md` (threads).

### gist

The developer code-snippet sibling of the repo adapter, its own source since
`gist.github.com`'s host, API, and content all differ. One keyless
`GET /gists/<id>` returns the whole gist with each file's content inlined (the
Lobsters one-request economy), so a saved gist becomes a clean scroll instead of
a JS-rendered DOM scrape.

- **Identity:** the gist id alone (`gist:<id>`) — the owner login in the URL is
  decorative, the API is keyed by the id and resolves the owner — so
  `gist.github.com/<owner>/<id>`, a bare `gist.github.com/<id>`, and a revision
  permalink all dedupe, the hex id folded lowercase. A bare one-segment id is
  claimed only at full modern-id length, so a username's gist-list page isn't
  mistaken for a gist.
- **Captured:** each file becomes a sorted `### <filename>` fenced section in
  the searchable `extracted_text`; the distinct file languages become `tags`
  (the bitbucket `language`→tag facet) while `concepts` stay empty by design (a
  gist has no topic facet); the `title` is the gist description else the first
  filename, and the `summary` is a `"N files: …"` manifest.
- **Degrades:** the same `GITHUB_TOKEN`/`GH_TOKEN` lifts its rate limit, and a
  gist whose files are all empty degrades to a metadata-only scroll.
- **Classification:** *no* category default — a snippet is heterogeneous (a
  config, a script, a repro), so it stays unclassified like a Hacker News post
  until a title rule or the LLM engine names it.
- **Decision:** `docs/adr/0078-github-gist-adapter.md`.

### gitlab

The second major code host: a keyless REST API on gitlab.com serving project
metadata plus an optional README, with issue and merge-request threads as a
second content kind — the github thread template applied to GitLab.

- **Identity (projects):** nested-group project paths are URL-encoded whole and
  folded lowercase.
- **Identity (threads):** `/-/issues/<n>` and `/-/merge_requests/<n>` detect as
  a discussion thread in GitLab's own cross-reference notation —
  `group/project#<n>` for an issue, `group/project!<n>` for a merge request.
  GitLab keeps *separate* iid sequences for issues and MRs, so unlike github's
  unified `owner/repo#<n>` the `#`/`!` marker must distinguish them, and it
  doubles as the endpoint selector (`#` → `/issues/<iid>`, `!` →
  `/merge_requests/<iid>`).
- **Captured (projects):** the README is fetched from the project's `/-/raw/`
  route; `topics` become `concepts` like github's, and the SPDX license key
  becomes a `tag`.
- **Captured (threads):** the adapter dispatches on the marker, fetches the
  thread and its notes, and maps the Markdown description and bylined comments
  to `extracted_text` — dropping GitLab's automated *system* notes. Labels
  become `concepts`, and the kind and state become `tags` (the state
  normalized to github's vocabulary, so `--tag merged`/`open` spans both
  hosts). A `gitlab.com/<project>` link wires the thread↔project edge.
- **Degrades:** set `GITLAB_TOKEN` to lift the rate limit and reach private
  projects. gitlab.com serves the issue/MR metadata keyless but gates the notes
  endpoint behind auth (anonymous callers get a 401), so a keyless fetch
  degrades to body-only and `GITLAB_TOKEN` is what reaches the conversation.
- **Classification:** like a github thread, an issue/MR gets *no* category
  default and stays unclassified until a title rule or the LLM engine names it.
- **Decision:** `docs/adr/0055-gitlab-adapter.md` (projects) and
  `docs/adr/0085-gitlab-issue-mr-adapter.md` (threads).

### gitea

The third code host — Codeberg and gitea.com, one adapter for Gitea and its
API-compatible fork Forgejo (Codeberg runs Forgejo) the way the mastodon adapter
serves its forks. Keyless `GET /api/v1/repos/<owner>/<repo>`, repo metadata plus
an optional README.

- **Identity:** unlike github/gitlab, the Gitea API lives on each *instance's
  own host* (`codeberg.org/api/v1`, `gitea.com/api/v1`), not one fixed
  endpoint, so the instance host rides in the item id —
  `gitea:<host>/<owner>/<repo>`, the Fediverse `<host>/<id>` shape — and
  reaching a self-hosted instance later is a detection-only change.
- **Captured:** inline `topics` become `concepts` like github's (no second
  call); Gitea carries no inline license, so `tags` stay empty (github-parallel,
  not gitlab's license tag). The README is fetched README.md-first via the
  keyless *API* raw route — the contents listing's `download_url` is the web raw
  route, which login-gates anonymous gitea.com clients, and listing a large
  repo's root times out (forgejo/forgejo did) — with a root-listing fallback
  that finds a differently-named README (`README.rst`).
- **Degrades:** set `GITEA_TOKEN`/`FORGEJO_TOKEN` to lift the rate limit and
  reach private repos; degrades to a metadata-only scroll.
- **Decision:** `docs/adr/0056-gitea-forgejo-adapter.md`.

### bitbucket

The fourth code host — Bitbucket Cloud's keyless `/2.0` API:
`GET /2.0/repositories/<workspace>/<repo>`.

- **Identity:** where gitea carries the instance host in the id because its API
  is per-host, Bitbucket *Cloud* is a single hosted service
  (`api.bitbucket.org`), so it is host-scoped with one fixed API host and the
  flat `<workspace>/<repo>` identity github uses — *not* host-in-id. The id is
  folded lowercase (Bitbucket auto-lowercases slugs and routes
  case-insensitively, so `/Workspace/Repo` and a deep `/src/...` link dedupe to
  one repo — the gitlab fold, not github's verbatim).
- **Captured (facets):** Bitbucket Cloud has no repository-topics feature, so
  `concepts` stay empty *by design* (the Go/RubyGems posture) — the repo's
  `language` is the one structured facet it offers and becomes the single `tag`
  (github ignores `language` because its richer topics fill that role).
- **Captured (README):** no `/readme` endpoint (github) or `/raw/` route
  (gitea): a file's body comes from the `/src/<commit>/<path>` route, which
  accepts a branch name. So the adapter reads `mainbranch.name` and fetches
  `README.md` first (one fast keyless GET). It falls back to a root listing
  (`commit_file`/`commit_directory` entries) only to find a differently-named
  README (`README.rst`) — the gitea README pattern on Bitbucket's src endpoint.
- **Captured (metadata):** `title` is `full_name`, `author` the owner's
  `display_name`, `published_at` the `created_on`, the canonical URL the
  `links.html.href`.
- **Degrades:** set `BITBUCKET_TOKEN` (a Bitbucket access token) to send
  `Authorization: Bearer` and lift the rate limit; Bitbucket Server/Data
  Center, the self-hosted product on a different API, is deferred like
  self-hosted GitLab; degrades to a metadata-only scroll.
- **Decision:** `docs/adr/0057-bitbucket-adapter.md`.

### arxiv

Keyless Atom export API, stdlib XML, with full text pulled from the paper's PDF.

- **Captured:** the abstract becomes the searchable summary, taxonomy codes
  become `tags` and their display names — "Computation and Language" for
  `cs.CL`, via a bundled taxonomy table — become `concepts`, the PDF link is
  recorded as `media`, and the paper's full text is extracted from the PDF with
  `pypdf` into searchable extracted text.
- **Degrades:** any PDF failure degrades to the abstract-only scroll.
- **Decision:** `docs/adr/0008-arxiv-adapter-atom-abstracts.md`,
  `docs/adr/0010-arxiv-pdf-full-text-pypdf.md`, and
  `docs/adr/0012-arxiv-taxonomy-names-as-concepts.md`.

### biorxiv and medrxiv

arXiv's biology and medicine preprint siblings. The two servers share one
operator and one keyless API (`api.biorxiv.org/details/<server>/<doi>`, stdlib
JSON), so one fetch adapter serves both — but they stay two distinct sources
because a medRxiv paper does not live on bioRxiv.

- **Captured:** the highest version is the scroll; the abstract becomes the
  searchable summary with no extracted text and no PDF media — the `.full.pdf`
  403s anonymous clients, unlike arXiv's. The subject area becomes the one
  `concept`; the study type, server, and CC license become `tags`; and the
  published-journal DOI becomes a `doi.org` link to its Crossref scroll, the
  preprint↔published edge arXiv and PubMed also carry.
- **Degrades:** degrades to a metadata-only scroll.
- **Decision:** `docs/adr/0068-biorxiv-medrxiv-adapter.md`.

### pdf

Any other `.pdf` URL: text and document metadata via `pypdf`.

- **Captured:** the `/Title`-or-filename as title, `/Subject` as the only
  honest summary, and the document itself as a media ref for `scrolls media`.
- **Degrades:** a non-PDF payload fails the fetch, while a textless-but-real
  PDF degrades to a metadata-only scroll.
- **Decision:** `docs/adr/0013-generic-pdf-adapter.md`.

### hackernews

The keyless Firebase API in one request.

- **Captured:** an Ask HN/Show HN/comment with a `text` body contributes it as
  extracted text with its lead paragraph as the summary. A link story has no
  body of its own: its summary is the discussion status — "104 points, 71
  comments" — and its linked article rides along as a bare URL in the Links
  section, one `scrolls add` away. The comment id tree stays in `raw_text` for
  a later enrichment.
- **Identity:** only `news.ycombinator.com/item?id=…` pages fetch — the front
  page and profiles register but have no item to fetch.
- **Degrades:** a link story degrades to a metadata-only scroll.
- **Decision:** `docs/adr/0031-hacker-news-adapter.md`.

### stackexchange

The keyless Stack Exchange API: one adapter serves the whole network, so a
Math.SE, Super User, or MathOverflow question enriches with no extra code.

- **Identity:** the per-site API slug is carried in the item id as
  `stackexchange:<site>:<id>` the way Wikipedia carries its language edition.
  Only `/questions/<id>` and the `/q/<id>` shortlink fetch, while tag, user,
  and `/a/<id>` answer-permalink pages register but have no question to fetch.
- **Captured:** a saved question's body and its top answers — accepted answer
  first — become the searchable scroll, and the question's author-applied tags
  become `concepts` like github repo topics.
- **Degrades:** the answers are an optional second request, so a question with
  none, or a failed answers fetch, still produces a question-only scroll.
- **Decision:** `docs/adr/0033-stack-exchange-adapter.md`.

### lobsters

The keyless Lobsters JSON API: a saved `lobste.rs/s/<short_id>` story becomes a
clean scroll instead of a `trafilatura` scrape of its HTML page, the third
discussion-aggregator adapter beside Hacker News and Stack Exchange.

Its distinctive trait is economy: a story's `.json` returns the submission, its
tags, *and* the entire comment thread in one request, where Hacker News defers
comments (a fetch per node) and Stack Exchange spends a second GET on answers.

- **Identity:** the short id is the identity; `/c`, `/t`, `/u`, and front pages
  register but have no story to fetch.
- **Captured (content):** the API ships pre-rendered plain text
  (`description_plain`, `comment_plain`), so there is no HTML grammar to
  write. A link submission's article rides along in `links` like a Hacker News
  link story, a text submission contributes its body, and either way the
  comment thread — deleted/moderated comments skipped, each bylined with
  author and score like a Stack Exchange answer, all kept since they come free
  in the one request — becomes the searchable extracted text.
- **Captured (facets and summary):** the curated tags (`css`, `security`,
  `ask`) become `concepts` like github repo topics; the `summary` leads with
  the body else the discussion status ("12 points, 1 comment").
- **Captured (raw):** the raw thread with comment `depth` stays in `raw_text`
  for a future threaded render.
- **Classification:** unlike Stack Exchange's weak `reference` default, a
  Lobsters story gets *no* category default — it is a heterogeneous aggregator
  entry, unclassified like Hacker News until a title rule or the LLM engine
  names it.
- **Degrades:** honestly keyless, where Reddit's `.json` now 403s
  unauthenticated clients.
- **Decision:** `docs/adr/0046-lobsters-adapter.md`.

### pypi

The keyless PyPI JSON API: a saved `pypi.org/project/<name>/` page becomes a
clean scroll from the project's latest-release metadata instead of a
`trafilatura` scrape.

- **Identity:** the PEP 503-normalized package name, so `Flask`, `flask`, and a
  version-pinned page all dedupe to `pypi:flask`.
- **Captured:** the long description (rendered README) is the searchable
  content, the author-declared keywords become `concepts` like github repo
  topics, the trove classifiers become `tags` like arXiv codes, and the
  declared project URLs become `links` — so a package's Source link to its
  github repo connects them in `scrolls related`.
- **Classification:** a PyPI package classifies as `tool`, the first rule to
  produce that category; search/user/help pages register but have no package to
  fetch.
- **Decision:** `docs/adr/0034-pypi-adapter.md`.

### npm

The keyless npm registry: a saved `npmjs.com/package/<name>` page becomes a
clean scroll from the package's latest-release metadata, the JavaScript sibling
of the PyPI adapter.

- **Identity:** the package name preserved verbatim — the registry is
  case-sensitive, so unlike PyPI it is not folded — with scoped names
  (`@babel/core`) and version pages handled.
- **Captured (content):** the README is the searchable content, taken from the
  registry's packument when present and otherwise extracted from the published
  tarball (`dist.tarball`, a capped download) — the fallback that matters,
  because the packument's README is empty for high-traffic packages like
  `express` and `react`.
- **Captured (facets and links):** author-declared keywords become `concepts`
  like github repo topics; npm has no trove-classifier analog so `tags` stay
  empty; and the homepage and repository become `links`, the repository's
  `git+https://….git` form normalized to a clean URL so a package's repo
  connects to it in `scrolls related`.
- **Classification:** an npm package classifies as `tool` like a PyPI one;
  search/user/org pages register but have no package to fetch.
- **Decision:** `docs/adr/0035-npm-adapter.md`.

### crates

The keyless crates.io JSON API: a saved `crates.io/crates/<name>` page becomes a
clean scroll from the crate's displayed-version metadata, the Rust sibling of
the PyPI and npm adapters.

- **Identity:** the crate name folded like a PyPI one — crates.io is
  case-insensitive and treats `-`/`_` as equivalent, so `serde_json`,
  `serde-json`, and a version page all dedupe to `crates:serde-json`, while the
  canonical published name is read back from the API for the canonical URL and
  the download path.
- **Captured (content):** the crate JSON carries no inline README — only a
  link to an HTML-rendered one — so the raw Markdown README is extracted from
  the published `.crate` tarball (the capped `http.get_bytes` npm introduced).
- **Captured (facets and links):** author-declared keywords become `concepts`
  like github repo topics; the curated category taxonomy's display names
  become `tags` like PyPI classifiers; and the homepage, `docs.rs` docs, and
  repository become `links`, the repository normalized so a crate's repo
  connects to it in `scrolls related`.
- **Degrades:** every tarball failure degrades to a metadata-only scroll.
- **Classification:** a crate classifies as `tool` like a PyPI or npm package;
  search/user/category pages register but have no crate to fetch.
- **Decision:** `docs/adr/0036-crates-io-adapter.md`.

### crossref

The keyless Crossref DOI metadata API: a saved `doi.org/<doi>` link becomes a
clean scroll from the work's registered metadata instead of a redirect into
whatever publisher page — often a paywall — the DOI resolves to.

- **Identity:** the DOI folded lowercase — DOIs are case-insensitive, so
  `doi.org` and the legacy `dx.doi.org`, and any case variant, dedupe to one
  `crossref:10.…` item, the canonical form read back from the response.
- **Captured:** Crossref carries metadata only, so the JATS-XML abstract — when
  one exists — is stripped to a plain `summary` that FTS indexes, with no
  `extracted_text` (there is no full text). The `subject` categories become
  `concepts` like github topics, the work `type` (`journal-article`,
  `proceedings-article`, …) and its publication venue become `tags`, and only
  the publisher's landing page becomes a `link` — a work's `reference` DOIs run
  to hundreds and are deliberately not turned into links. `published_at`
  follows Crossref's date precedence (`issued` first, `created` last).
- **Degrades:** a record with no abstract is an honest metadata-only scroll of
  title, authors, venue, and date, still far better than the `web` scrape it
  replaces.
- **Classification:** a Crossref work classifies as `paper` like an arXiv
  preprint, so Scrolls covers both halves of the literature; the bare resolver
  and non-DOI paths register but have no work to fetch.
- **Decision:** `docs/adr/0037-crossref-doi-adapter.md`.

The same `doi.org` detection carries a **datacite** fallback
(`docs/adr/0045-datacite-doi-fallback.md`):

- **Dispatch:** a DOI's registration agency — Crossref for the published
  literature, DataCite for datasets, software, and other repository outputs —
  can't be read off the URL, and the `crossref:<doi>` identity is fixed at
  `add` time, so the `doi.py` dispatcher resolves it at fetch time — Crossref
  first, DataCite when Crossref 404s the DOI.
- **Provenance:** a DataCite output keeps `source="crossref"` but records
  `provenance.adapter="datacite"`, and its `types.resourceTypeGeneral` rides in
  `provenance.resource_type` so the rules engine classifies it by *what it is*
  — a dataset as `dataset`, software as `tool`, the textual literature as
  `paper`, audiovisual as `media`, an ambiguous type left unclassified —
  instead of forcing every DOI to `paper`.
- **Captured:** the DataCite `attributes` map like Crossref's analogs: titles
  joined with a subtitle, creators as "Given Family", the `Abstract`-typed
  description as the searchable `summary` (no full text), `subjects` as
  `concepts`, and `resourceTypeGeneral`/`resourceType`/publisher as `tags`.
  The landing page plus the parent work's container DOI become `links` — that
  container DOI resolving through `scrolls related`/`graph` to a saved
  Crossref paper, a DataCite-output↔parent-work edge.

### pubmed

The keyless NCBI E-utilities efetch API: a saved `pubmed.ncbi.nlm.nih.gov/<pmid>`
link becomes a clean scroll for the biomedical literature, the life-sciences
sibling of the arXiv and Crossref paper adapters, instead of a `trafilatura`
scrape of the abstract page that drops the record's structure. One efetch GET
returns the record as XML, parsed with stdlib ElementTree.

- **Identity:** the integer PMID; the dedicated host is claimed wholesale (the
  PMID is the first path segment, subpages dedupe) while the legacy
  `ncbi.nlm.nih.gov/pubmed/<pmid>` form is shape-matched so the shared host's
  other databases — PMC, Gene, Nucleotide — fall through to `web`.
- **Captured (concepts):** the curated **MeSH** descriptors become `concepts`
  — the controlled subject vocabulary that joins github topics and arXiv
  taxonomy names in the KB concept graph — with author keywords the fallback
  for a not-yet-MEDLINE-indexed article.
- **Captured (summary and tags):** the abstract (structured sections kept)
  becomes a plain `summary` with no `extracted_text` (PubMed has no full text,
  the Crossref shape); publication types and the journal venue become `tags`.
- **Captured (dates and links):** `published_at` prefers the electronic
  article date, then the journal issue date, then the PubMed history; and the
  article DOI becomes a `doi.org` `link` that resolves to its `crossref:<doi>`
  scroll — the PubMed↔Crossref paper edge, the biomedical analog of the arXiv
  preprint↔published edge.
- **Degrades:** a record with no abstract is an honest metadata-only scroll.
- **Classification:** a PubMed record classifies as `paper`.
- **Decision:** `docs/adr/0065-pubmed-adapter.md`.

### packagist

The keyless Packagist JSON API: a saved `packagist.org/packages/<vendor>/<name>`
page becomes a clean scroll from the package's metadata, the PHP/Composer
sibling of the PyPI, npm, and crates adapters.

- **Identity:** the `vendor/name` folded lowercase — Composer names are
  case-insensitive, so `Monolog/Monolog` and a `/stats` subpage all dedupe to
  `packagist:monolog/monolog`, the canonical form read back from the API.
- **Version selection:** Packagist keys its `versions` by string and exposes no
  "default version" pointer, so the adapter selects the highest *stable*
  release by ranking the numeric `version_normalized` (`3.9.0` beats both a
  later-dated `2.9.x` patch and the `dev-main` branch), with no semver
  dependency.
- **Captured (summary):** the API carries no README — it lives only in the
  dist zip — so a Packagist scroll is honestly metadata-only, the package
  description becoming the `summary` that FTS indexes.
- **Captured (facets and links):** author-declared keywords become `concepts`
  like github repo topics; the package `type` and the release's SPDX
  `license`s become `tags` like PyPI classifiers; and the repository, homepage,
  and git source become `links`, the source's `….git` form normalized so a
  package's repo connects to it in `scrolls related`.
- **Classification:** a Composer package classifies as `tool` like a PyPI, npm,
  or crates one; the packages list, vendor pages, and search register but have
  no package to fetch.
- **Decision:** `docs/adr/0039-packagist-adapter.md`.

### rubygems

The keyless RubyGems JSON API: a saved `rubygems.org/gems/<name>` page becomes a
clean scroll from the gem's metadata, the Ruby sibling of the PyPI, npm, crates,
and Packagist adapters, and the simplest of the five — `gems/<name>.json`
returns the latest version inline, so there is no version to select.

- **Identity:** the gem name preserved verbatim — RubyGems is case-sensitive
  (`gems/Ascii85` resolves, `gems/ascii85` 404s), npm's rule rather than PyPI's
  fold.
- **Captured:** a gemspec has no keywords field, so a gem contributes nothing
  to the concept graph — `concepts` empty by design — and the API ships no
  README, so the gem's description becomes the `summary` that FTS indexes. The
  SPDX `license`s become `tags`; and the homepage, source, and documentation
  URIs become `links`, the source URI resolving to the gem's github repo in
  `scrolls related` even when it points at a tagged tree.
- **Classification:** a gem classifies as `tool` like the other packages; the
  gems list and search register but have no gem to fetch.
- **Decision:** `docs/adr/0040-rubygems-adapter.md`.

### huggingface

The keyless Hugging Face Hub API: a saved `huggingface.co/<org>/<name>` model
page or `huggingface.co/datasets/<...>` dataset page becomes a clean scroll from
the Hub's structured metadata instead of a `trafilatura` scrape of a JS-rendered
page, the ML-artifact sibling of the package-registry adapters. One adapter
serves both repo kinds the way the Stack Exchange adapter serves a whole
network.

- **Identity:** the *kind* rides in the item id as
  `huggingface:model:<org>/<name>` or `huggingface:dataset:<...>`, picked off
  the URL so the fetch routes to `/api/models` or `/api/datasets`. Repo ids are
  kept verbatim — the Hub is case-sensitive, npm's rule rather than PyPI's fold
  — and a `/tree/main` or `/blob/...` subpage dedupes to the two-segment repo.
- **Captured (content):** the model/dataset card (`README.md`, its YAML
  frontmatter stripped) is the searchable content, its lead paragraph the
  summary — cleaner than a dataset's `description` field, which the Hub derives
  crudely from the card.
- **Captured (facets):** the Hub flattens every tag into one noisy array
  (frameworks, `region:us`, file formats), so concepts come from the
  *structured* fields instead — the task (`pipeline_tag` for models,
  `task_categories` for datasets) and the author's `cardData.tags`, the
  github-topics parallel — while `library_name` and the license fill the `tags`
  facet slot.
- **Captured (links):** the flat array is read only for its cross-reference
  prefixes:
  - an `arxiv:<id>` tag becomes an `arxiv.org/abs/<id>` link that
    `scrolls related` resolves to the saved arXiv paper (the model↔paper edge,
    kin to ADR 0038's preprint↔published edge — a saved model wires to the
    paper that introduced it);
  - a `dataset:<name>` tag becomes the dataset's Hub page (the model↔dataset
    edge);
  - and a `base_model:<id>` tag becomes the base model's Hub page (the
    model↔base-model lineage edge, deduped across the bare and
    `base_model:finetune:` forms).
- **Spaces:** hosted demos and apps are the third repo kind
  (`space:<org>/<name>`, ADR 0043): the same adapter routes to `/api/spaces`.
  The `sdk` (gradio/streamlit/docker) fills the `tags` facet `library_name`
  fills for a model, and the card `title` is the human name. The card's
  `models`/`datasets` lists become space↔model/dataset links — a saved demo
  wiring to the model it serves and the dataset it draws on, surviving even a
  card-less degrade since they come from the metadata.
- **Degrades:** a repo with no card degrades to a metadata-only scroll, and
  site routes and bare profiles register but have no repo to fetch.
- **Classification:** a model and a Space classify as `tool` like a package, a
  dataset as `dataset` — the IDEAS.md §8 vocabulary term.
- **Decision:** `docs/adr/0041-huggingface-hub-adapter.md`.

### go

The keyless Go module proxy: a saved `pkg.go.dev/<module>` page becomes a clean
scroll from `proxy.golang.org` instead of a `trafilatura` scrape of a
JS-rendered docs page, the Go sibling of the package-registry family on the
JSON-metadata pattern.

- **Identity:** the module path kept verbatim — module paths are
  case-sensitive, and the proxy *case-encodes* the request
  (`github.com/Masterminds/squirrel` → `github.com/!masterminds/squirrel`), so
  the escaping touches the request, not the identity. The module is everything
  before any `@version`, so a versioned sub-package URL dedupes to its module,
  and a domain-first-segment rule keeps the standard library and site routes
  from fetching.
- **Captured (facets):** Go is the sparsest adapter of the family: `/@latest`
  carries only the version, publish time, and source `Origin`, so there is no
  description (`summary` stays empty — honest, not synthesized), no keywords
  (`concepts` empty by design, like RubyGems), and no license or classifier
  facet (`tags` empty too).
- **Captured (content):** the one content the proxy holds is the `go.mod`
  manifest, fetched from `/@v/<version>.mod` and kept as the searchable
  extracted text — the module path plus its dependency graph, the first
  adapter whose content is a manifest rather than prose.
- **Captured (link):** the source repository becomes the one `link`: from
  `Origin.URL` when present — the only way to learn a vanity path's repo
  (`golang.org/x/tools` → `go.googlesource.com/tools`) — else derived from the
  module path for the well-known VCS hosts, resolving through
  `scrolls related` to a saved github repo (the package↔repo edge).
- **Classification:** a Go module classifies as `tool` like the other packages;
  the standard library, search, and site routes register but have no module to
  fetch.
- **Decision:** `docs/adr/0042-go-modules-adapter.md`.

### pub

The keyless pub.dev JSON API: a saved `pub.dev/packages/<name>` page becomes a
clean scroll from the package's latest-version metadata, the Dart/Flutter
sibling of the package-registry family. One keyless
`GET pub.dev/api/packages/<name>` returns the whole package, `latest.pubspec`
its `pubspec.yaml` as JSON, so there is no version to select.

- **Identity:** the package name folded lowercase — pub names are lowercase
  Dart identifiers (`[a-z0-9_]`) and the API is case-sensitive
  (`packages/Provider` 404s, `packages/provider` resolves). So folding is the
  *forgiving* choice the case-sensitive npm/RubyGems rule isn't: the canonical
  name is always lowercase, so a mistyped capital is rescued, never missed.
  Version, publisher, and search pages dedupe or register without a fetchable
  item.
- **Captured (concepts):** what sets pub apart from its siblings RubyGems and
  Go — whose registries carry no keywords — is that `pubspec.topics` become
  `concepts` like github repo topics, so a saved package joins the KB concept
  graph; a package whose pubspec lists no topics simply contributes empty
  `concepts`.
- **Captured (summary):** the package description is the searchable `summary`
  with no `extracted_text` (the README ships only in the package archive, not
  the JSON — RubyGems' metadata-only situation).
- **Captured (links):** the `repository` and `homepage` become `links`, the
  repository's `git+`/`.git` folded so it resolves to the package's github
  repo through `scrolls related` (the package↔repo edge) even when it points
  into a monorepo tree
  (`github.com/flutter/packages/tree/main/packages/url_launcher`).
- **Tags:** pub exposes no license or classifier facet, but it does carry the
  one signal that matters across the ecosystem. A package that declares the
  Flutter SDK (`environment.flutter` or a `flutter` dependency) is tagged
  `flutter` — the family's first *derived* tag — so `--tag flutter` separates
  Flutter plugins from pure-Dart packages. A pure-Dart package is left
  untagged rather than given a synthesized `dart` label (Go's honest-empty
  posture).
- **Classification:** a pub package classifies as `tool` like every other
  package.
- **Decision:** `docs/adr/0088-pub-dev-adapter.md`.

### hex

The keyless Hex JSON API: a saved `hex.pm/packages/<name>` page becomes a clean
scroll from the package's metadata, the Elixir/Erlang sibling of the
package-registry family and pub.dev's closest twin in field layout — a `meta`
object holding the description, the licenses, and a links map. One keyless
`GET hex.pm/api/packages/<name>` returns the whole package.

- **Identity:** the package name folded lowercase — Hex names are lowercase and
  the API is case-sensitive (`packages/Ecto` 404s, `packages/ecto` resolves),
  so folding is the forgiving choice pub uses. The canonical name is always
  lowercase, so a mistyped capital is rescued and version pages dedupe. The
  docs host `hexdocs.pm` is left to the `web` adapter since it serves rendered
  docs, not package metadata.
- **Captured (summary):** the `meta.description` is the searchable `summary`
  with no `extracted_text` (the README ships only in the package tarball —
  RubyGems' metadata-only situation).
- **Captured (concepts):** this is the axis on which Hex and its layout-twin
  pub.dev diverge: pub's `topics` feed the KB concept graph, but Hex has no
  keywords field, so its `concepts` are empty *by design* like RubyGems and Go
  — the registry's data, not the adapter, deciding whether a package can join
  the concept graph.
- **Captured (tags and links):** the SPDX `meta.licenses` become `tags`; and
  the `meta.links` map — a `{label: url}` of `GitHub`, `Changelog`, `Docs` —
  becomes `links` by iterating its values (where RubyGems and pub read named
  scalar fields), the `GitHub` entry resolving to the package's github repo
  through `scrolls related` (the package↔repo edge).
- **Dates and byline:** the publish date is read from the release matching
  `latest_stable_version`, robust to a pre-release topping the list; the author
  is left unset, since Hex exposes only an owner list with emails and no clean
  byline.
- **Decision:** `docs/adr/0089-hex-adapter.md`.

### nuget

The keyless .NET package registry: a saved `nuget.org/packages/<id>` page
becomes a clean scroll, the ninth of the package family and the one top-tier
ecosystem it had not reached.

- **Mechanism:** NuGet's rich registration API is **gzip-encoded even on a
  plain GET** — the shared UTF-8 transport can't read it — and paginates for
  large packages. So the adapter takes the **flat container** instead, the Go
  module shape (ADR 0042) of two plain requests. `GET
  api.nuget.org/v3-flatcontainer/<id>/index.json` returns the ascending
  version list, and the chosen version's `.nuspec` manifest carries the
  metadata, parsed with stdlib ElementTree.
- **Version selection:** the highest listed version is often a pre-release, so
  the **latest stable** version is selected by Packagist's comparator-free
  numeric ranking (ADR 0039).
- **Identity:** the package id folded lowercase — the forgiving fold
  (PyPI/crates/pub/Hex rule), since NuGet ids are case-insensitive and the
  flat-container path *requires* the lowercase form — while the registrant's
  display casing (`Newtonsoft.Json`) is read back from the nuspec `<id>` for
  the title and canonical URL.
- **Captured (parsing):** the nuspec namespace URI varies by schema
  generation, so its children are matched by *local* name.
- **Captured (concepts and summary):** author-curated `<tags>` (whitespace-,
  comma-, or semicolon-separated) become `concepts` like PyPI keywords and
  github topics, so the .NET ecosystem joins the KB concept graph a `web`
  scrape would have left it out of. The `<description>` is the searchable
  `summary` with no `extracted_text` (the README ships in the `.nupkg`, not
  the nuspec — RubyGems' and Hex's metadata-only situation).
- **Captured (tags and links):** the SPDX `<license type="expression">`
  becomes the one `tag` (a `type="file"` names a package file, not an SPDX id,
  so it is skipped); and `<projectUrl>` plus the `<repository url>` become
  `links`, the repository resolving to the package's github repo through
  `scrolls related` (the package↔repo edge).
- **Degrades:** the nuspec carries no publish date, so `published_at` is
  honestly left as the feed seed (Go's honest-empty posture); and because the
  nuspec *is* the metadata its failure is a fetch error rather than a
  metadata-only scroll, unlike Go's optional go.mod.
- **Classification:** a NuGet package classifies as `tool` like every other
  package.
- **Decision:** `docs/adr/0090-nuget-adapter.md`.

### hackage

The keyless Haskell package registry: a saved
`hackage.haskell.org/package/<name>` page becomes a clean scroll, the tenth of
the package family and the one that breaks the JSON mold.

- **Mechanism:** one plain
  `GET hackage.haskell.org/package/<name>/<name>.cabal` returns the latest
  version's **cabal** manifest — no API host and no version to select
  (RubyGems' inline-latest economy). But the cabal is an
  indentation-structured `field: value` format, not JSON, so the adapter
  carries a small cabal parser:
  - top-level package fields sit at column 0 with more-indented continuation
    lines;
  - a column-0 line with no `field:` shape is a section header (`library`,
    `source-repository head`) whose body is skipped except the repository
    `location`;
  - and `--` comments are dropped.
- **Identity:** the package name preserved **verbatim** — Hackage names are
  case-sensitive (`QuickCheck`, `HUnit`) and the cabal endpoint only resolves
  the exact case, the npm/RubyGems rule — with the singular `/package/<name>`
  claimed (the browse list is the *plural* `/packages/`) and a trailing
  dotted-numeric version stripped so `/package/aeson-2.3.0.0` dedupes to
  `aeson` while `aeson-pretty` stays whole.
- **Captured (concepts and text):** the `category` field is comma-separated
  curated keywords that become `concepts` like github repo topics, so Haskell
  joins the KB concept graph. And unlike the metadata-only registries, the
  cabal's `description` is a real prose body that becomes the searchable
  `extracted_text` (the `.`-only line is cabal's blank-line marker). The
  `synopsis` is the short `summary` — the first registry whose own manifest
  carries prose.
- **Captured (tags, byline, links):** the `license` becomes the one `tag`,
  taken verbatim (an SPDX id on modern cabals, a legacy cabal id like `BSD2`
  on older ones); the `author`'s `<email>` is stripped to a clean byline; and
  the `homepage` plus the `source-repository` `location` become `links`, the
  repository resolving to the package's github repo through `scrolls related`
  (the package↔repo edge).
- **Degrades:** the cabal carries no upload date, so `published_at` is honestly
  left as the feed seed (Go's and NuGet's honest gap); a cabal with no `name`
  field is a fetch error rather than a junk scroll.
- **Classification:** a Hackage package classifies as `tool`.
- **Decision:** `docs/adr/0091-hackage-adapter.md`.

### maven

The keyless Maven Central flat repository — Haskell's JVM successor and the
eleventh of the package family, reaching the largest ecosystem of all (Java,
Kotlin, Scala, Clojure, Groovy, Android). A saved Maven artifact URL becomes a
clean scroll from the static repository `repo1.maven.org/maven2`, what a build
tool resolves against, rather than the rate-limited Solr search API or a
`trafilatura` scrape.

- **Mechanism:** two plain requests, the Go/NuGet "version index + manifest"
  shape (ADR 0042/0090): `GET /<group-path>/<artifact>/maven-metadata.xml`
  returns the `<versioning>` with the `<release>` pointer, the `<versions>`
  list, and a `<lastUpdated>` stamp, and the chosen version's `.pom` is the
  manifest, both parsed with stdlib ElementTree.
- **Identity:** the Maven **coordinate `groupId:artifactId`** — the family's
  only colon-joined coordinate (distinct from Packagist's `vendor/name` slash),
  a reverse-DNS `groupId` (`com.google.guava`) plus an `artifactId` (`guava`) —
  kept **verbatim** since the repository is a literal, case-sensitive file tree
  (the npm/RubyGems/Hackage rule), with the group **path-encoded** to address
  the directory (`com.google.guava` → `com/google/guava`, the structural cousin
  of Go's request case-encoding).
- **Detection:** spans **two grammars**: the unambiguous
  `/artifact/<group>/<artifact>` browse pages of the official UIs
  (`central.sonatype.com`, `search.maven.org`) and the popular third-party
  index (`mvnrepository.com`, whose non-Central artifacts degrade to a failed
  fetch), and the raw `/maven2/<group-path>/<artifact>` file tree where the
  slash-encoded group is reassembled around the version directory.
- **Version selection:** the latest **release** is preferred from the index
  `<release>` — which gets the stable build classifiers `-jre`/`-android` right
  where a "hyphen means pre-release" heuristic fails (Guava's versions are all
  suffixed) — with a SNAPSHOT-excluded numeric ranking the fallback.
- **Divergence from NuGet:** two axes. A POM has no keyword/topic facet, so its
  `concepts` are empty *by design* (the RubyGems/Go/Hex posture — the JVM joins
  as a metadata-and-edges source, not a concept source), and its `published_at`
  is read from the **version index's `<lastUpdated>`** (`yyyyMMddHHmmss` UTC),
  the only adapter whose date lives outside its own content manifest.
- **Captured (metadata):** the POM is parsed namespace-agnostically (the
  nuspec lesson): `<name>` else the coordinate is the `title`, the
  `<description>` the searchable `summary` with no `extracted_text` (the
  README ships in the artifact jar — RubyGems'/NuGet's metadata-only
  situation), and the `<organization>` name else the lead developer the
  `author`.
- **Captured (tags):** the freeform `<licenses><license><name>` values become
  the `tags` (kept verbatim, the Hackage license rule).
- **Captured (links):** the `<url>` plus the `<scm>` repository become the
  `links` — the SCM taken from `<scm><url>` or the `scm:<tool>:<url>`
  `<connection>`/`<developerConnection>` (the ssh `git@host:path` and `git://`
  forms normalized to https, the `.git` suffix stripped), the repository
  resolving to the package's github repo through `scrolls related` (the
  package↔repo edge).
- **Degrades:** the POM *is* the metadata, so its failure is a fetch error
  rather than a metadata-only scroll (NuGet's posture, unlike Go's optional
  go.mod); parent-POM inheritance — a multi-module child that inherits its
  description/licenses/scm from a `<parent>` — is deferred.
- **Classification:** a Maven artifact classifies as `tool` like every package.
- **Decision:** `docs/adr/0092-maven-central-adapter.md`.

### datacite

The keyless DataCite JSON:API: not a new detected source but a fetch-time
fallback behind `crossref`'s `doi.org` detection, the second DOI registration
agency.

- **Dispatch:** the `doi.py` dispatcher tries Crossref first and DataCite when
  Crossref 404s the DOI, so a dataset, software, or other repository output
  deposited in Zenodo/Dryad/figshare becomes a clean scroll instead of falling
  to a `web` scrape.
- **Classification:** by `types.resourceTypeGeneral` — `Dataset → dataset`,
  `Software`/`Model` → `tool`, text types → `paper`, `Image`/`Sound` → `media`.
- **Provenance:** the source stays `crossref` because identity is fixed at
  `add` time before the agency is knowable, with
  `provenance.adapter="datacite"` recording the truth.
- **Decision:** `docs/adr/0045-datacite-doi-fallback.md`.

### content-negotiation

A generic fallback on the same `doi.org` detection: the *third* tier of the
`doi.py` dispatch, reached when both Crossref and DataCite 404 a DOI. The DOI
system has ~a dozen registration agencies — JaLC (essentially the entire
Japanese scholarly literature), mEDRA, KISTI, OP, Airiti, CNKI — whose DOIs
neither rich API holds, so rather than a bespoke adapter per agency, `csl.py`
reaches them all at once through DOI **content negotiation**.

- **Mechanism:** a `https://doi.org/<doi>` GET with
  `Accept: application/vnd.citationstyles.csl+json` is proxied by the resolver
  to whichever agency holds the DOI, and every agency answers with the same
  **CSL-JSON** document.
- **Captured:** CSL-JSON is Crossref's REST JSON's structural sibling
  (`title`/`container-title` plain strings, authors carry `literal` for orgs),
  so the Crossref mapping transfers almost verbatim — the JATS abstract reduced
  to a plain `summary`, `subject` → `concepts`, `type` + venue → `tags`, the
  landing `URL` → the one `link`, a record with no abstract an honest
  metadata-only scroll.
- **Classification:** the `type` (recorded in `provenance.resource_type`)
  defaults classification to `paper` like Crossref — the post-DataCite agencies
  are scholarly-literature registries — while a `dataset`/`software`/`figure`
  CSL type is honored instead of mislabeled.
- **Provenance and degrades:** the source stays `crossref`,
  `provenance.adapter="content-negotiation"` is honest, and a
  parsed-but-non-CSL body raises rather than minting a junk scroll.
- **Decision:** `docs/adr/0081-doi-content-negotiation-fallback.md`.

### bluesky

The keyless AT Protocol AppView — the open social-post source X could never be.
IDEAS.md §6 deferred X for its auth/session complexity, and X's read API is now
paywalled, so a keyless `x` adapter is off the table — but Bluesky's
`public.api.bsky.app` serves posts and their threads with no login, cookie, or
token.

A saved `bsky.app/profile/<actor>/post/<rkey>` post becomes a clean
scroll instead of a `trafilatura` scrape of a JS-rendered page.

- **Identity:** the wrinkle is that the URL carries a *handle* (or a DID), but
  the thread endpoint is keyed by the post's AT-URI
  (`at://<did>/app.bsky.feed.post/<rkey>`), which needs the DID. So a handle
  URL costs one keyless `resolveHandle` GET (the Stack Exchange / Hugging Face
  two-request shape) while a `did:` URL skips straight to the thread. The
  actor is folded lowercase in the `<actor>/<rkey>` source id since handles and
  DIDs are case-insensitive.
- **Captured (content):** one `getPostThread` call returns the post *and* its
  nested reply tree (the way a Lobsters story's `.json` returns its comments).
  The post text leads the searchable `extracted_text`, and the replies follow
  as a `### Replies` subsection each bylined with author and like count
  (deleted/blocked/empty nodes skipped). An image-only post contributes its
  images' alt text as the body so it stays searchable.
- **Captured (links, media, concepts):** an external link card, a quoted post,
  and inline `#link` richtext facets become `links` — a post pointing at an
  arXiv paper, a github repo, or another saved post wiring to it through
  `scrolls related`/`graph` (the quoted-post URL is the post↔post edge).
  Embedded images become `photo` media (the CDN's extensionless `…@jpeg` URL
  resolving to `.jpg` through the same fallback tweet photos use). And
  `#hashtag` facets become `concepts` like github repo topics.
- **Captured (title and summary):** posts have no title, so one is synthesized
  from the byline and lead line; the `summary` leads with the post's first
  paragraph, falling back for a textless post to image alt text, then the link
  card's title, then the engagement status ("128 likes, 12 reposts, 3
  replies").
- **Classification:** like Hacker News and Lobsters, a heterogeneous social
  post gets *no* category default — unclassified until a title rule or the LLM
  engine names it.
- **Degrades:** the whole thread stays in `raw_text` for a future nested
  render, and profile/feed/list/home routes register but have no post to fetch.
- **Decision:** `docs/adr/0048-bluesky-adapter.md`.

### mastodon

The keyless Mastodon REST API: the second open social network after Bluesky,
and the first source matched by URL *shape* rather than host. Mastodon is
federated — an account lives on one of thousands of independent instances
(`mastodon.social`, `hachyderm.io`, `infosec.exchange`), so there is no host set
to claim.

- **Identity:** detection recognizes a status by its shape on whatever instance
  the URL names — `/@<user>/<digits>` (the web permalink) or
  `/users/<user>/statuses/<digits>` (the ActivityPub object URL), both
  collapsing to one `<host>/<status_id>` identity since a status id is unique
  only within its instance. The all-digits id is the safety: it keeps a Medium
  `/@author/<slug>` post or a Threads/TikTok `/@user/<kind>/<id>` from being
  stolen, and a misdetected URL degrades to a benign failed fetch (the API
  404s), never a wrong scroll.
- **Mechanism:** the adapter talks to that same host's keyless API: one GET for
  the status (`/api/v1/statuses/<id>`) and, when it has replies, a second for
  the thread (`.../context`) — the two-request shape Bluesky and Stack Exchange
  use, the context call skipped for a reply-less post and degrading to a
  post-only scroll on failure.
- **Captured (content):** the post `content` is HTML, reduced to searchable
  text by a stdlib parser (no `trafilatura` dependency); the context's
  `descendants` arrive already flattened, so the bylined replies render in one
  pass (Bluesky returns a nested tree).
- **Captured (links, media, concepts):** the external link card and plain body
  links become `links` — `@mention` and `#hashtag` anchors excluded as
  navigation, not references — so a post pointing at an arXiv paper or github
  repo wires to it through `scrolls related`/`graph`. Image attachments become
  `photo` media and videos their preview image (alt text searchable when the
  post has no text). `tags[].name` hashtags become `concepts` like github
  topics.
- **Captured (honesty details):** a `spoiler_text` content warning leads the
  body so the hidden text stays honest, a boost unwraps to the post it boosts,
  and the synthesized title and `summary` (lead else alt else card title else
  "N favourites, M boosts, K replies") mirror Bluesky.
- **Classification:** like Bluesky, Hacker News, and Lobsters, a heterogeneous
  social post gets *no* category default.
- **Degrades:** the whole `{status, context}` stays in `raw_text`, and profile,
  timeline, and tag routes carry no status id to fetch.
- **Decision:** `docs/adr/0049-mastodon-adapter.md`.

The same `mastodon` source and adapter now also serve its API-compatible forks
**GoToSocial** and **Pleroma/Akkoma**
(`docs/adr/0050-fediverse-forks-mastodon-api.md`):

- **Mechanism:** they expose the identical keyless `/api/v1/statuses/<id>` +
  `/context` endpoints and return Mastodon-shaped JSON, so only detection
  learns their extra routes — GoToSocial's `/@<user>/statuses/<ULID>`,
  Pleroma/Akkoma's `/notice/<FlakeId>`, and the shared ActivityPub
  `/users/<user>/statuses/<id>` — and their non-numeric ids (a ULID, a
  FlakeId).
- **Identity:** the all-digits safety generalizes to "a distinctive literal
  anchors the shape, the id constraint as strict as that anchor is weak": the
  `statuses`-bearing forms admit any base62 id because the `statuses` literal
  is unambiguous. The weak `/notice/` form, by contrast, carries a 16-char
  length floor a real FlakeId clears but a `/notice/privacy` legal page does
  not. A Pleroma AP *Object* URL (`/objects/<uuid>`) is left to `web` since
  its uuid is not a status id. Identity stays `<host>/<status_id>` (web and AP
  forms still dedupe).
- **Provenance:** `provenance.adapter` stays `mastodon` — the adapter that
  served it, the specific fork unknowable from the URL.

### misskey

The keyless Misskey API — the third open social network. Misskey and its forks
Sharkey, Firefish/Calckey, and Foundkey are Fediverse software like Mastodon,
but they do *not* speak the Mastodon API, so — unlike GoToSocial and
Pleroma/Akkoma — Misskey is its own source and adapter, not another mastodon
URL shape.

- **Identity:** still detected the same host-less, shape-only way: a
  `/notes/<id>` permalink on any instance becomes `misskey:<host>/<id>`, the
  weak `notes` literal carrying a base62 + length floor of 10 — Misskey's
  shortest id format, `aid` — so a `/notes/getting-started` slug or a
  sub-floor word stays a web page and a misdetect degrades to a benign failed
  fetch.
- **Mechanism:** a note is fetched with `POST /api/notes/show` (a JSON request
  body — the first adapter to need the shared transport's new `post_json`) and
  its replies with a second POST to `notes/children`, skipped when the note has
  none and degrading to a note-only scroll on failure.
- **Captured:** the note `text` is MFM (Misskey Flavored Markdown), already
  plain, so no HTML parser is needed (Lobsters' economy). Outbound links are
  scanned straight from the text and a quote-renote's note becomes a post↔post
  link, both wiring through `scrolls related`/`graph`. Drive `files` become
  `photo`/video-thumbnail media (their `comment` alt text searchable),
  bare-string `tags` become `concepts`, a `cw` content warning leads the body,
  and a pure renote unwraps to the boosted note.
- **Title and summary:** the synthesized title and `summary` (lead else alt
  else "N reactions, M renotes, K replies") mirror Bluesky and Mastodon.
- **Classification:** like them it gets *no* category default.
- **Degrades:** the whole `{note, children}` stays in `raw_text`.
- **Decision:** `docs/adr/0051-misskey-adapter.md`.

### lemmy

The keyless Lemmy API — the first federated *link aggregator*. Lemmy is the
Reddit-shaped, community-organized discussion site — the federated cousin of
Hacker News and Lobsters — and Fediverse software like Mastodon and Misskey,
but it speaks its own API, so like Misskey it is its own source and adapter,
the *third* Fediverse split by client API rather than host.

- **Identity:** detected the same host-less, shape-only way: a `/post/<id>`
  permalink on any instance becomes `lemmy:<host>/<id>`, the weak `post`
  literal carrying an all-digits + exactly-two-segments guard (Lemmy mints
  autoincrement integer post ids) — so a blog's `/post/<slug>` or a
  `/post/<id>/<extra>` URL stays a web page, and a misdetect degrades to a
  benign failed fetch.
- **Mechanism:** the API is plain GET, so the shared `http.get_json` serves it
  (no `post_json`): a post is fetched with `GET /api/v3/post?id=<id>` and its
  comments with a second GET to `/comment/list`, skipped when the post has none
  and degrading to a post-only scroll on failure. We target API v3, the
  near-universal backwards-compatible surface; Lemmy 1.0's v4 keeps it working.
- **Captured (thread):** the comments arrive as a flat list whose `path`
  (`0.<id>`, `0.<parent>.<id>`) encodes the thread tree, so they are sorted
  into pre-order — a parent right before its replies — and bylined with author
  and score like a Lobsters comment (deleted and mod-removed comments skipped).
- **Captured (title and canonical):** unlike the social posts, a Lemmy post has
  a *real* title (it is an aggregator entry, like a Hacker News or Lobsters
  story), and its `ap_id` is the canonical URL — pointing at the origin
  instance even when fetched through another.
- **Captured (links and media):** a link post's external `url` becomes a
  `link` (the article), and a text post's Markdown `body` is the searchable
  content. An image post's `url` becomes `photo` media (told apart by
  `url_content_type`), its pict-rs `thumbnail_url` a preview `thumbnail`.
  Outbound URLs in the body are scanned and the `cross_posts` — the same
  submission in other communities — become post↔post links by `ap_id`, both
  wiring through `scrolls related`/`graph`.
- **Captured (concepts and summary):** the post's community (`c/rust`, its
  subreddit-like topical home) becomes a `concept` like a github repo topic;
  the `summary` leads with the body else the engagement status ("142 points, 4
  comments").
- **Classification:** like Hacker News, Lobsters, and the social posts, it gets
  *no* category default.
- **Degrades:** the whole `{post, comments}` stays in `raw_text`.
- **Decision:** `docs/adr/0052-lemmy-adapter.md`.

### piefed

The same `/post/<digits>` shape is also served by **PieFed** — the *other*
federated link aggregator. Its post URL is byte-identical to Lemmy's (same
`/post/<integer-id>` shape), so it can't be told apart at detection — but its
API is its own: `/api/alpha` rather than Lemmy's `/api/v3`, with diverging
field names (`post.title` not `post.name`, `creator.user_name` not `name`,
`comment.body` not `content`, a `post_type` enum rather than
`url_content_type`).

- **Dispatch:** PieFed can't ride Lemmy's adapter the way GoToSocial rides
  Mastodon's, nor be its own detected source the way Misskey is — it is a
  hybrid: its own *adapter* on Lemmy's *source*, reached by a fetch-time
  fallback the way DataCite sits behind Crossref (ADR 0045). A new
  `threadiverse` dispatcher backs the `lemmy` source: it tries Lemmy's
  `/api/v3` first — Lemmy is far more deployed, so only a PieFed post pays the
  one wasted request — and falls back to PieFed's `/api/alpha` when Lemmy 404s
  the instance.
- **Identity and provenance:** identity stays `lemmy:<host>/<id>`, minted
  before the backend is knowable, and `provenance.adapter="piefed"` records
  which implementation answered.
- **Captured:** the adapter mirrors Lemmy's behavior under the field-name
  mapping:
  - post + comments in two GETs, the flat comments sorted into thread
    pre-order by their integer `path` and bylined;
  - an image post told by `post_type=="Image"`;
  - a link/video post's `url` a `link` (so a PieFed video pointing at a
    YouTube URL becomes a cross-source edge);
  - cross-posts — which PieFed nests with a `post_id` and no `ap_id` —
    becoming same-instance `/post/<id>` post↔post links;
  - and the community a `concept`.
- **Classification:** no category default.
- **Degrades:** the `Poll`/`Event` payloads are kept in `raw_text` for a future
  render.
- **Decision:** `docs/adr/0053-piefed-adapter.md`.

### discourse

The keyless Discourse forum `.json` view. Discourse is the open-source software
behind countless dev communities (discuss.python.org, meta.discourse.org,
users.rust-lang.org), the *centralized-forum* sibling of the aggregators Hacker
News, Lobsters, Lemmy, and PieFed — and the **first non-Fediverse host-less
source**, proving the shape-only detection the Fediverse adapters built
generalizes beyond ActivityPub.

- **Identity:** like them it has no host set to claim: a `/t/<slug>/<topic_id>`
  topic on any instance becomes `discourse:<host>/<topic_id>`, the display-only
  slug dropped from identity and the all-digits id carrying the weak `t`
  literal. So a blog's `/t/<slug>` tag page or a `/t/<slug>/<non-numeric>`
  stays a web page. A misdetect degrades to a benign failed fetch (the
  adapter validates the response is a Discourse topic before producing a
  scroll, never a wrong one).
- **Mechanism:** unlike the two-request social and aggregator adapters,
  `GET /t/<id>.json` returns the topic *and* its first page of posts in *one*
  request (Lobsters' economy).
- **Captured (content):** a real `title` (a forum thread, not a synthesized
  social post), the opening post the searchable body, the later posts a bylined
  `### Replies` section (moderator-action, whisper, and deleted posts skipped),
  the `cooked` HTML reduced to text by a stdlib parser (no `trafilatura`,
  Mastodon's rule).
- **Captured (facets and links):** the topic's `tags` become `concepts` like
  github topics, its outbound `details.links` — the internal-navigation and
  incoming-reflection links filtered out — become `links` so a thread pointing
  at an arXiv paper or github repo wires to it through
  `scrolls related`/`graph`, and its representative `image_url` becomes a
  `thumbnail`. The `summary` leads with the opening post else the engagement
  status ("3 replies, 20 likes").
- **Classification:** like Hacker News, Lobsters, Lemmy, and the social posts
  it gets *no* category default.
- **Degrades:** a long thread is bounded to the first page, the full post-id
  `stream` surviving in `raw_text` for a later paged render; category/user/tag
  routes carry no topic id to fetch.
- **Decision:** `docs/adr/0054-discourse-adapter.md`.

### devto

The keyless dev.to / Forem articles API. dev.to is one of the largest
developer-blogging communities, and a saved `dev.to/<user>/<slug>` article used
to fall through to the `web` adapter, which extracts the text but produces no
`concepts` — so the post became a concept-less *island*, invisible to
`scrolls related`, the concept facets, and the KB concept pages.

One keyless `GET /api/articles/<user>/<slug>` returns the whole article.

- **Identity:** the identity `<user>/<slug>` is folded lowercase because Forem
  mints lowercase handles and slugs and its API is case-sensitive — only the
  lowercase form resolves (a mixed-case request 404s), the gitlab/bitbucket
  fold — and a deeper link dedupes to the article. A subtlety the API surfaces:
  for an organization post the URL handle is the *org* while the byline `user`
  is a *person*, and the fetch keys on the handle (the org), so `source_id`
  carries it and `author` reads `user.name`.
- **Captured (concepts):** the curated `tags` (`python`, `api`, `webdev`)
  become `concepts` like github repo topics — the structured signal the `web`
  scrape could never produce, finally wiring the post into the concept graph.
- **Captured (content and summary):** the `body_markdown` is already Markdown
  (no HTML grammar, Lobsters' economy) and becomes the searchable text; the
  platform's `description` excerpt is the summary (else the body lead, else a
  "45 reactions, 40 comments" engagement status).
- **Captured (links and media):** when the author cross-posted from their own
  blog, the external original recorded in `canonical_url` rides along in
  `links` as the cross-source edge while the scroll's own canonical stays the
  dev.to permalink, and the `cover_image` becomes a `thumbnail`.
- **Classification:** like Hacker News, Lobsters, and the social posts, a
  heterogeneous dev.to article gets *no* category default — the title rules and
  the LLM engine decide.
- **Degrades:** self-hosted Forem instances have no shape tell and are deferred
  like self-hosted GitLab, and bare profiles and reserved site routes register
  but have no article to fetch.
- **Decision:** `docs/adr/0061-devto-adapter.md`.

### rfc

The keyless RFC Editor JSON view. IETF **RFCs** are technical standards — the
normative protocol specs an agent cites constantly (HTTP's RFC 9110, TLS's
RFC 8446, JSON's RFC 8259, OAuth's RFC 6749) — a content type with no prior
first-class home, so a saved RFC link fell through to `web`, a concept-poor
unlinked island.

One keyless `GET rfc-editor.org/rfc/rfc<N>.json` returns the whole
bibliographic record.

- **Detection:** host-restricted shape matching across the RFC Editor and IETF
  hosts (`rfc-editor.org`, `datatracker.ietf.org`, `tools.ietf.org`,
  `ietf.org`): only the `rfc<digits>` path shape is claimed, so an
  Internet-Draft (`/doc/draft-…`), a working-group page, or the org site on
  those same hosts falls through to `web` — the shared-NCBI-host posture
  (ADR 0065), not a wholesale host claim.
- **Identity:** the integer RFC number with leading zeros stripped, so
  `rfc0020` and `rfc20` dedupe to `rfc:20`, and the number leads the title
  (`RFC 9110: HTTP Semantics`) and the scroll slug because an RFC's canonical
  name *is* its number.
- **Captured (facets):** the RFC Editor's curated `keywords` become `concepts`
  — the controlled subject vocabulary that joins github topics, arXiv taxonomy,
  and MeSH in the KB concept graph, with the whitespace-only placeholder older
  RFCs store dropped — and the maturity `status` (`Internet Standard`,
  `Proposed Standard`, `Informational`, …) is title-cased into the one `tag`,
  the controlled facet Crossref's `type` fills.
- **Captured (text):** the abstract becomes the plain `summary`, and the
  published spec text (`rfc-editor.org/rfc/rfc<N>.txt`) is fetched and
  normalized into `extracted_text` so an agent can search the actual normative
  content (`docs/adr/0067-rfc-full-text.md`, the arXiv abstract+PDF split): one
  de-pagination pass strips the form-feed page breaks, `[Page N]` footers, and
  running headers classic RFCs carry for print while the modern unpaginated
  format passes through.
- **Captured (edges):** two cross-document edges. The RFC's own DOI
  (`10.17487/RFC<N>`, Crossref-registered) becomes a `doi.org` `link` resolving
  to its `crossref:<doi>` scroll — the RFC↔Crossref edge, ADR 0038's analog —
  and each `obsoletes`/`updates` target becomes an `rfc-editor.org/rfc/rfc<M>`
  `link` resolving to that RFC's scroll, the RFC↔RFC standards-lineage edge
  (the inverse `obsoleted_by`/`updated_by` relations are not re-emitted, since
  the graph resolves edges in both directions).
- **Dates:** publication dates are `Month Year`, padded to the first of the
  month.
- **Degrades:** any `.txt` failure degrades to an abstract-only scroll (the
  arXiv PDF-degrade contract); a record with neither an abstract nor fetchable
  text is an honest metadata-only scroll; and STD/BCP sub-series and
  Internet-Drafts are deferred.
- **Classification:** an RFC classifies as `reference` — a normative spec to
  consult, like a Wikipedia article, not a paper to cite.
- **Decision:** `docs/adr/0066-rfc-adapter.md` and
  `docs/adr/0067-rfc-full-text.md`.

### openlibrary

The keyless Open Library `.json` view. **Books** were the missing content type,
a saved `openlibrary.org` link falling through to `web` as a concept-less
unlinked island the way dev.to and RFCs did before their adapters
(ADR 0061/0066).

Open Library is the Internet Archive's open, keyless
bibliographic catalog — books' Crossref — and models them in the same FRBR
sense `scrolls works` uses (ADR 0069): a *work* (`openlibrary.org/works/OL…W`,
the abstract book), an *edition* (`/books/OL…M`, a specific manifestation), and
an ISBN (`/isbn/<isbn>`, which names an edition).

- **Identity:** all three are common save targets, so all three are claimed,
  the kind riding in the item id — but the OLID's own type letter (`W` for a
  work, `M` for an edition) already encodes work-vs-edition, so only the ISBN
  form needs an explicit `isbn:` prefix (the Hugging Face kind-in-id without
  the prefix). The OLID is uppercased to a canonical form (Open Library routes
  case-insensitively but displays uppercase — the crates/gitlab fold), a title
  slug or `/editions` subpage deduping to it, and an ISBN is hyphen-stripped
  and `X`-uppercased.
- **Mechanism:** the adapter routes on the id — a work reads
  `/works/<OLID>.json`, an edition `/books/<OLID>.json`, an `isbn:` id
  `/isbn/<isbn>.json` (which Open Library 302-redirects to the edition record,
  urllib following it).
- **Captured (concepts):** the curated `subjects` become `concepts` like github
  repo topics — the whole point of a dedicated adapter, joining a book to the
  concept graph a `web` scrape never could.
  - Open Library's administrative/accessibility flags (`Accessible book`,
    `Open Library Staff Picks`) and library call numbers (`Pz7.d1515`) are
    filtered as noise, the list deduped case-insensitively and capped.
  - Subjects live on the *work*, so an edition/ISBN fetch follows its `works`
    ref with one extra GET to pull them (the Bluesky/Stack Exchange
    two-request shape), degrading to the edition's own subjects on any
    failure.
- **Captured (summary and tags):** the `description` blurb (a string or a
  `{value}` text object) becomes the searchable `summary` with no
  `extracted_text` — the catalog holds metadata, not the book's body, so a book
  is honestly summary-only (the Crossref/PubMed shape). And `tags` stay empty
  by design, a book having no clean controlled facet like an RFC's status or a
  package's license (the go/rubygems posture).
- **Captured (authors):** authors are named by key only (`/authors/OL…A`), so
  each is resolved with a bounded GET to its name (truncated past a cap with
  "et al.", a failed lookup skipped so the byline degrades rather than
  failing).
- **Captured (edges, media, dates):** an edition links to its FRBR work
  (`/works/<OLID>`, the edition↔work edge `scrolls related`/`graph` resolves
  when both are saved), and a work's external `links` become outbound edges.
  The first present cover (Open Library's `-1` "no cover" sentinel skipped)
  becomes a `thumbnail` media ref on `covers.openlibrary.org`. And free-form
  publication dates (`Aug 20, 2015`, `August 2015`, `2015`, `2008-09`) parse to
  UTC ISO 8601 padded to the start of the period.
- **Classification:** no category default is assigned: Open Library spans
  fiction and non-fiction, so forcing `reference` (right for a textbook) would
  be dishonest for a novel — the honesty value that keeps a medRxiv paper off
  the `biorxiv` label — so a book flows through the title rules and otherwise
  stays honestly unclassified, like a Hacker News post.
- **Deferred:** author-bio enrichment, `identifiers` cross-references
  (Wikidata/Goodreads), and a true work↔edition scroll merge.
- **Decision:** `docs/adr/0073-openlibrary-adapter.md`.

### zenodo

The keyless InvenioRDM REST API. Research **datasets and software** were the
content type a saved `zenodo.org/records/<id>` landing page left as a `web`
scrape, a concept-less edgeless island the way dev.to and books were before
their adapters (ADR 0061/0073). Zenodo is CERN's general-purpose open-science
repository — the default archive for EU-funded output and the citable-DOI
snapshot every released GitHub repo gets.

Its DOIs are *DataCite*-registered,
so a saved `doi.org/10.5281/zenodo.<id>` already fetches through the DataCite
adapter (ADR 0045) — but the URL researchers paste is the landing page, which
has its own keyless API (`zenodo.org/api/records/<recid>`, a plain JSON record
with no JSON:API envelope, stdlib only).

- **Identity:** the version-specific record id the URL carries — taken from the
  digits after a `record`/`records` segment so the modern `/records/<id>`, the
  legacy `/record/<id>`, and the pasted `/api/records/<id>` forms all dedupe,
  deeper `/files`/`/preview` links deduping to the record — kept verbatim
  because `conceptrecid`/`conceptdoi` name the all-versions concept while the
  URL identifies one version (the Open Library edition rule).
- **Captured (DOI edges):** the record's DOI becomes a `doi.org` `link` that
  ties the landing page to its DataCite DOI scroll and clusters them as **one
  work** in `scrolls works` (the DOI-edge pattern, ADR 0037/0045/0069); the
  `conceptdoi` links the concept.
- **Captured (summary):** the HTML `description` becomes the plain-text
  `summary` with no `extracted_text` — the deposit's files are the body, not
  the catalog metadata, so a record is honestly summary-only (the
  Crossref/DataCite shape), and the shape that keeps the Zenodo scroll
  consistent with its DataCite-DOI twin.
- **Classification:** the `resource_type.type` (`dataset`, `software`,
  `publication`, `image`, `video`, …) rides in `provenance.resource_type` and
  the rules engine maps it — `dataset → dataset`, `software → tool`,
  `publication → paper`, `image`/`video → media`, the ambiguous
  `poster`/`presentation`/`lesson` honestly unclassified — the DataCite
  fetch-time-fact mechanism (ADR 0045), since a deposit is not always a paper.
- **Captured (facets and edges):** free-text `keywords` and controlled
  `subjects` become `concepts` (the github-topics/MeSH role), and
  `type`/`subtype`/`license.id` become `tags`.
  - Each `related_identifiers` entry becomes an outgoing edge by its scheme: a
    `doi` to `doi.org`, an `arxiv` to `arxiv.org/abs` (the preprint edge,
    ADR 0038, the `arXiv:` prefix stripped), a `url` kept when http(s), other
    schemes skipped as dead links. So a dataset that supplements a paper or
    archives a repo wires into the graph.
  - Partial publication dates (`2023`, `2023-04`) pad to the start of the
    period (the RFC rule).
- **Deferred:** version↔concept consolidation, the deposit's files as captured
  media, and self-hosted InvenioRDM.
- **Decision:** `docs/adr/0083-zenodo-adapter.md`.

### x

**The one source with a capture path but no fetch adapter.** X bookmarks are a
*collection*: not a file someone exported and not a feed delta, but the user's
own saved set, copied out of the service they saved it in. So `x` arrives
through `scrolls sync x --bookmarks` rather than through `scrolls fetch`.

- **Custody shape — capture-at-pull.** Items enter at stage `fetched` with
  content taken from the same response that enumerated them. This is a third
  shape beside the adapter/importer split: fetch adapters pull one item from
  the network, importers bulk-read a local archive, and this pulls a live
  remote collection already populated.
- **Identity:** `x:<tweetId>`, matching what `detect.py` mints for x.com status
  URLs — so a pulled bookmark dedupes against a `scrolls add` of the same
  tweet.
- **Auth:** the two session cookies already in the user's browser
  (`auth_token`, `ct0`), read live per run and never stored. Chrome, Brave,
  Arc, Edge, Vivaldi, Chromium and Firefox are all searched; `--browser` and
  `--profile` pin one, and `SCROLLS_X_AUTH_TOKEN`/`SCROLLS_X_CT0` skip browser
  access entirely. `--auth oauth` takes the official API instead, under the
  grant from `scrolls x login`; both routes mint the same items and dedupe
  against each other, differing only in `provenance.extraction_method`
  (`x:graphql-internal` vs `x:api-v2`).
- **Captured:** text (`note_tweet` preferred over a truncated `full_text`),
  author handle and name, posted-at, media references, expanded links, and
  quoted-tweet text folded into the body.
- **`saved_at` is the sync time, not a bookmark timestamp.** X exposes no
  bookmark timestamp on either the internal or the official path, so
  `provenance.saved_at_source` records `"synced_at"` and says so rather than
  minting a plausible one from X's opaque ordering key.
- **No drift detection.** Because there is no `x` entry in `FETCH_ADAPTERS`,
  `scrolls verify` cannot re-capture a bookmarked post and fails with `no
  fetch adapter for source 'x'`. An x item is captured once and held; Scrolls
  does not claim to know whether the post has since changed or been deleted.
  This is deliberate and recorded, not an oversight.
- **Volatility:** the default route uses X's internal GraphQL API, pinned to a
  build hash that X rotates on deploy. A rotated id is reported as such, never
  as an empty collection. The pinned id and feature flags were confirmed
  working against live X on 2026-08-18.
- **The OAuth route is unverified and will stay that way.** Verifying it needs
  a registered X developer app on a paid plan, which the maintainer does not
  hold. It is code-reviewed and covered by tests with the network injected,
  but no request on that path has ever reached X. Use `--auth oauth` only if
  you have an app and are willing to debug it; the cookie default is the
  proven one.
- **Decision:** `docs/adr/0108-x-bookmarks-native-sync.md`, superseding
  `docs/adr/0009-fieldtheory-import.md`.
