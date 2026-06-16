# Scrolls Library Format

What is inside the files Scrolls writes. This is the contract for
anything that reads a library directly off disk — an agent following a
scroll path out of a context bundle, a skill walking `library/`, or a
human in an editor. The companion references: `docs/cli.md` for command
*output* (JSON keys, exit codes), `docs/architecture.md` for the system
that produces these files.

Both pinned examples below are regenerated from the real renderer and
compiler by `tests/test_docs.py`
(`test_library_format_example_scroll_is_render_output`,
`test_library_format_kb_index_example_matches_compiler_output`), and the
frontmatter key table is diffed against the renderer's field list
(`test_library_format_frontmatter_table_matches_render_fields`) — if the
format drifts, the suite fails before this document lies.

A library holds three kinds of generated artifact, all under the root
(`~/.scrolls`, or `$SCROLLS_HOME`):

- **Scroll files** — `scrolls/<source>/<slug>.md`, one per item: the
  durable content artifact (written by `src/scrolls/render.py`).
- **Compiled library pages** — `library/index.md` plus group pages: the
  navigation layer (written by `src/scrolls/kb.py`).
- **Agent instruction files** — `agents/<tool>/…`: ready-made usage
  docs for coding agents (written by `src/scrolls/agents.py`).
- **Captured media files** — `media/<source>/…`: downloaded copies of
  items' media references (written by `src/scrolls/media.py`).

The SQLite database stays the canonical index (IDEAS.md §3): every file
here can be rebuilt from it, and nothing should be inferred from a
scroll that `scrolls show <id>` answers authoritatively.

## Scroll files: `scrolls/<source>/<slug>.md`

### Path and slug rules

- One directory per source; the filename is the slugified title —
  NFKD-folded to ascii, lowercased, runs of non-alphanumerics collapsed
  to `-`, capped at 80 characters (`slugify` in `src/scrolls/render.py`).
  An unusable title falls back to the slugified item id
  (`test_write_scroll_slug_falls_back_to_id_when_title_unusable`).
- If another item already owns that filename, an 8-hex-char suffix
  derived from the item id is appended
  (`test_write_scroll_disambiguates_slug_collisions`).
- Paths are stable: once written, the item's `markdown_path` is reused
  on every re-render even if the title changes, so links from KB pages
  and agent transcripts don't break
  (`test_write_scroll_reuses_stored_path_even_when_title_changes`).

### Frontmatter

Delimited by `---` lines. Every line is `key: <JSON value>` — JSON
scalars, arrays, and objects are valid YAML (YAML 1.2 is a JSON
superset), so standard YAML parsers read it, and so does a
zero-dependency line parser: split each line on the first `: ` and
`json.loads` the remainder (`test_render_markdown_frontmatter_round_trips_fields`).

Keys appear in the fixed order below. **A key whose value is null or an
empty list is omitted entirely** (`test_render_markdown_omits_empty_fields`),
so consumers must treat every key as optional — only `id`, `source`,
`url`, and `saved_at` are always present, because the model cannot
represent an item without them.

<!-- pinned: frontmatter-keys -->
| Key | Present | JSON type | Meaning |
| --- | --- | --- | --- |
| `id` | always | string | stable item id: `source:source_id`, else `source:` + 12-hex URL hash |
| `source` | always | string | adapter name: `wikipedia`, `web`, `youtube`, `github`, `arxiv`, `x`, `pdf` |
| `source_id` | when the source has local ids | string | platform-local identifier, e.g. `en:SQLite`, a tweet id |
| `url` | always | string | the URL the item was saved as, normalized at registration (ADR 0023) |
| `canonical_url` | when an adapter resolved one | string | platform-canonical form of the URL |
| `title` | once fetched | string | item title from the platform |
| `author` | when the platform exposes one | string | author or channel display name |
| `published_at` | when known | string | UTC ISO 8601 publication time, one shape from every writer (ADR 0024) |
| `saved_at` | always | string | ISO 8601 time the item entered the library |
| `category` | once classified | string | classification from the rules engine or an import join |
| `domain` | once assigned | string | finer topic area; today only the Field Theory import sets it |
| `tags` | when non-empty | array of strings | e.g. arXiv taxonomy codes (`cs.CL`) |
| `concepts` | when non-empty | array of strings | e.g. GitHub repo topics, Wikipedia page categories, arXiv taxonomy names |
| `media` | when non-empty | array of objects | media refs: `type` and `url` from the adapter, plus a root-relative `path` once `scrolls media` captured the file |
| `content_hash` | once fetched | string | `sha256:<hex>` over the fetched content |
| `provenance` | once fetched | object | `adapter`, `fetched_at`, `extraction_method` |

### Body

In order (`test_render_markdown_body_sections`):

1. An H1 — the title, falling back to the item id.
2. `## Summary` — the stored summary (an arXiv abstract, a tweet's
   classified gist). Omitted when there is none.
3. `## Extracted Content` — the extracted full text (article body,
   transcript, PDF text). Omitted when there is none.
4. `## Links` — always present. The first line is `- Source: <url>`; a
   `- Canonical: <canonical_url>` line follows only when it differs
   from the source URL
   (`test_render_markdown_shows_canonical_link_only_when_different`);
   then one `- <url>` line per link extracted from the content
   (`test_render_markdown_lists_item_links_in_links_section`).

Not in a scroll, by design: `raw_text` (the verbatim platform payload
stays in the index — render the extraction, keep the receipt), `stage`
(pipeline bookkeeping), and `markdown_path` (it is the file's own
location). When you need those, ask `scrolls show <id>`.

### Example

An illustrative arXiv item with every populated field, rendered by the
real renderer (`test_library_format_example_scroll_is_render_output`
regenerates it from the fixture in `tests/test_docs.py`). Note what the
omission rule did: the item has no `domain` and no `concepts`, so those
keys simply aren't there.

<!-- pinned: example-scroll -->
```markdown
---
id: "arxiv:1706.03762"
source: "arxiv"
source_id: "1706.03762"
url: "https://arxiv.org/abs/1706.03762"
canonical_url: "http://arxiv.org/abs/1706.03762v7"
title: "Attention Is All You Need"
author: "Ashish Vaswani et al."
published_at: "2017-06-12T17:57:34+00:00"
saved_at: "2026-06-12T08:00:00+00:00"
category: "paper"
tags: ["cs.CL", "cs.LG"]
media: [{"type": "pdf", "url": "https://arxiv.org/pdf/1706.03762", "path": "media/arxiv/1706-03762-1.pdf"}]
content_hash: "sha256:6d2e1066c2f3aae40f4ea846cebee5ee5cdc77a2f9bb582a0f5a526f70b48aaa"
provenance: {"adapter": "arxiv", "fetched_at": "2026-06-12T08:00:05+00:00", "extraction_method": "arxiv-atom+pypdf"}
---

# Attention Is All You Need

## Summary

We propose the Transformer, a model architecture relying entirely on attention.

## Extracted Content

The dominant sequence transduction models are based on complex recurrent or convolutional neural networks…

## Links

- Source: https://arxiv.org/abs/1706.03762
- Canonical: http://arxiv.org/abs/1706.03762v7
- https://arxiv.org/pdf/1706.03762
```

## Compiled library pages: `library/`

`scrolls kb` (ADR [0005](adr/0005-deterministic-kb-compiler.md))
rebuilds a generated tree — `library/index.md`, `library/graph.md`,
`library/works.md`, `library/sources/`, `library/categories/`,
`library/concepts/`, `library/tags/` — on every run, so a stale group
page can't linger; anything *else* under `library/` is preserved, so
hand-written notes can live alongside in their own file
(`test_kb_recompile_removes_stale_pages_but_keeps_user_files`). Only
rendered items appear: KB pages link to scroll files, and an unrendered
item has nothing to link to.

All links are **relative to the page's own location** (group pages link
scrolls as `../../scrolls/<source>/<slug>.md`), so a library tree can be
moved, mounted, or committed wholesale without breaking navigation.

### Refresh-safe regeneration (the sentinel fence)

Each generated page wraps its content in a **sentinel fence** (ADR
[0102](adr/0102-obsidian-second-brain-inspiration-and-refresh-safe-artifacts.md)):
an `@generated` begin marker and an `@end` marker, both HTML comments
(so they're invisible in rendered Markdown). A re-compile replaces only
the fenced region and is **authoritative** over it — stale generated
content can never linger — while anything *outside* the fence is
preserved byte-for-byte. So a human or agent can annotate a generated
page in place (a `@user` note as a prefix or suffix) and the next
`scrolls kb` keeps the note while refreshing the generated region
(`test_kb_recompile_preserves_a_user_annotation_outside_the_fence`):

<!-- pinned: example-sentinel-fence -->
```markdown
<!-- @user -->
My note: start with the full-text-search concept page.

<!-- @generated scrolls — regenerated by `scrolls kb`; edits inside this block are replaced. Annotate outside the markers (or in a separate file) to keep notes. -->
# Scrolls Library

3 scrolls from 2 sources.
<!-- @end scrolls -->
```

Rules a consumer can rely on
(`test_library_format_sentinel_fence_example_matches_helper`):

- The begin marker line starts with `<!-- @generated scrolls`; the end
  marker is `<!-- @end scrolls -->`. The begin marker's trailing prose
  (which command regenerates it) is presentational — match the prefix,
  not the whole line.
- The region a re-compile owns is exactly the text **between** those two
  markers. Everything before the begin marker and after the end marker
  is yours and survives untouched.
- A page that carries **no** fence — a pre-sentinel file, or one you
  wrote by hand — has no region to preserve, so a re-compile overwrites
  it wholesale. The compiler always writes the fence, so any annotation
  you add *after* a compile is safe.
- If a generated page's group later vanishes (a reclassified category, a
  dropped concept) the page is removed — **unless** it carries an
  annotation, in which case the file is kept with its generated region
  replaced by a short tombstone, so your note is never silently dropped
  (`test_kb_stale_annotated_page_is_kept_with_a_tombstone`).

The per-kind examples below show the **generated region** (what lives
inside the fence); on disk each page is wrapped as above.

### Group pages

`sources/<slug>.md`, `categories/<slug>.md`, `concepts/<slug>.md`, and
`tags/<slug>.md` share one shape
(`test_kb_compiles_index_source_and_category_pages`):

```markdown
# Source: wikipedia

1 scroll.

- [SQLite](../../scrolls/wikipedia/sqlite.md) — reference
```

- The H1 is `Source: <name>`, `Category: <name>`,
  `Concept: <display spelling>`, or `Tag: <display spelling>`.
- One bullet per member — the title as a Markdown link to its scroll
  file — sorted by case-folded title with the item id as tiebreak. The
  ` — note` suffix is the item's category on source pages, and its
  source on category, concept, and tag pages.
- Concept pages merge spellings that slugify identically (`RAG` and
  `rag` are one page) and display the lexically smallest spelling
  (`test_kb_groups_concepts_across_spellings`).
- Tag pages merge **case-insensitively** — the `--tag` facet's rule
  (ADR [0059](adr/0059-tag-concept-facets.md)), not concepts' coarser
  slug merge — so `MIT` and `mit` are one page while `C++` and `C#` stay
  distinct, even though both slugify to `c`. When distinct tags collide
  on a slug, the page filenames disambiguate with a numeric suffix
  (`c.md`, `c-2.md`) assigned in sorted-key order; KB page filenames are
  regenerated each run and linked relatively, so they are addressable but
  not globally stable (`test_kb_groups_tags_case_insensitively_but_keeps_distinct_folds`).
- A concept page *may* lead with a synthesized summary paragraph
  between the H1 and the count line, when the LLM concept engine
  (ADR [0025](adr/0025-llm-concept-summaries.md)) has stored one for
  that slug (`test_kb_concept_page_leads_with_stored_summary`).
  Consumers must treat the paragraph as optional: it appears only for
  concepts with 2+ scrolls whose owner has run `scrolls kb --engine
  llm`, and a plain recompile preserves it.
- A concept page *may* end with a `## Related Concepts` section
  (ADR [0063](adr/0063-kb-related-concepts.md)) — the concepts that
  **co-occur** on its member scrolls, the deterministic concept-graph
  complement to the link-graph page. Each bullet links a co-occurring
  concept's sibling page (a bare `<slug>.md`) and notes how many scrolls
  carry both, strongest first:

  ```markdown
  ## Related Concepts

  - [Full-text search](full-text-search.md) — 2 shared scrolls
  - [SQLite](sqlite.md) — 1 shared scroll
  ```

  The section is omitted when no other concept shares a scroll, and the
  list is capped at the 10 strongest co-occurrences, so consumers must
  treat it as optional and non-exhaustive
  (`test_kb_concept_page_lists_related_concepts`,
  `test_kb_concept_page_without_co_occurrence_omits_related_section`).
- A tag page likewise *may* end with a `## Related Tags` section
  (ADR [0064](adr/0064-kb-tag-pages.md)) — the tags that **co-occur** on
  its member scrolls, the same co-occurrence rollup as Related Concepts,
  capped and omit-when-empty the same way. Each bullet links the
  co-occurring tag's sibling page (the bare collision-free `<name>.md`)
  and notes how many scrolls carry both
  (`test_kb_tag_page_lists_related_tags`,
  `test_kb_tag_page_without_co_occurrence_omits_related_section`).

#### Consolidated works on category pages

A **category page** is the one group page where a scholarly work's
near-duplicate representations co-occur: an arXiv preprint, its published
Crossref article, and a PubMed record all classify as `paper`, so a flat
list would show the same work several times. So a category page collapses
each multi-representation work (ADR [0071](adr/0071-kb-category-work-consolidation.md))
into one consolidated entry — a **bold work heading** carrying the
`doi.org` resolver link and a representation count, then each
representation as a **nested** bullet linking to its own scroll:

<!-- pinned: example-category-consolidation -->
```markdown
# Category: paper

2 scrolls.

- **Attention Is All You Need** — 2 representations ([doi.org/10.5555/3295222](https://doi.org/10.5555/3295222))
  - [Attention Is All You Need](../../scrolls/arxiv/attention-is-all-you-need.md) — arxiv
  - [Attention Is All You Need](../../scrolls/crossref/attention-is-all-you-need.md) — crossref
```

The clustering is `works.works_over` over *this page's* members — the same
DOI identity `scrolls works` (ADR [0069](adr/0069-works-by-doi.md)) and
`library/works.md` (ADR [0070](adr/0070-kb-works-page.md)) use — so a work
consolidates only when **two or more** of its representations are rendered
**in this category**; a lone representation on the page stays an ordinary
bullet. The heading's title is the work's *canonical* representation (the
published record outranks the preprint), and consolidated works interleave
with ordinary bullets in the same case-folded title order. The count line
still counts **scrolls** (every representation is one), not entries, so it
can exceed the number of top-level bullets. The other group pages —
`sources/`, `concepts/`, `tags/` — are **not** consolidated: a source page
is single-source, so a work's cross-source representations never co-occur
there (`test_kb_category_page_consolidates_work_representations`,
`test_kb_category_page_uses_canonical_title_and_interleaves`,
`test_kb_source_pages_do_not_consolidate`).

### The index

`library/index.md` is the entry point: a count line, then one-line links
to the link-graph page (`graph.md`) and the works page (`works.md`) each
summarising what it holds, then
`## Sources`, `## Categories`, `## Concepts`, and `## Tags` lists linking
to group pages (the categories list ends with an unlinked
`- unclassified — N scrolls` line when any rendered item lacks a category,
`test_kb_counts_unclassified_items_in_index`), then `## Recent` linking
the 10 newest scrolls, newest first
(`test_kb_index_links_recent_scrolls_newest_first`). Sections with
nothing to list are omitted.

Compiled from the example item above (its `cs.CL`/`cs.LG` taxonomy codes
are `tags`) plus one rendered Wikipedia item (title `SQLite`, category
`reference`, concept `Database software` — the second fixture in
`tests/test_docs.py`,
`test_library_format_kb_index_example_matches_compiler_output`); neither
links to the other and neither carries a DOI, so the graph and works lines
both report nothing held:

<!-- pinned: example-kb-index -->
```markdown
# Scrolls Library

2 scrolls from 2 sources.
[Link graph](graph.md) — no linked scrolls yet.
[Works](works.md) — no works held in multiple representations yet.

## Sources

- [arxiv](sources/arxiv.md) — 1 scroll
- [wikipedia](sources/wikipedia.md) — 1 scroll

## Categories

- [paper](categories/paper.md) — 1 scroll
- [reference](categories/reference.md) — 1 scroll

## Concepts

- [Database software](concepts/database-software.md) — 1 scroll

## Tags

- [cs.CL](tags/cs-cl.md) — 1 scroll
- [cs.LG](tags/cs-lg.md) — 1 scroll

## Recent

- [SQLite](../scrolls/wikipedia/sqlite.md)
- [Attention Is All You Need](../scrolls/arxiv/attention-is-all-you-need.md)
```

### The link graph

`library/graph.md` is the browsable, human- and agent-readable form of
`scrolls graph`'s JSON (ADR [0044](adr/0044-link-graph-command.md),
ADR [0062](adr/0062-kb-link-graph-page.md)): the cross-source connective
tissue the adapters build — a model wired to its paper, a package to its
repo, a preprint to its published DOI — laid out as clusters. It is built
over the rendered items only, so every link on the page resolves to a
scroll file, and items that reach one another by following links (in
either direction) are grouped into **clusters**, largest first. Each
cluster is an adjacency list: every member as a bullet linking to its
scroll, with its outbound edges nested beneath as `→ target`. The page is
always written, like the index; a library whose rendered scrolls don't yet
link to one another gets a single `No linked scrolls yet.` line, so the
page is a stable entry point
(`test_kb_graph_page_clusters_linked_scrolls`,
`test_kb_graph_page_is_empty_when_no_scrolls_link`).

Compiled from the example arXiv paper above plus a rendered Hugging Face
model whose card cites it (`huggingface:model:google-bert/bert-base-uncased`,
linking `https://arxiv.org/abs/1706.03762` — the model↔paper edge of
ADR [0041](adr/0041-huggingface-hub-adapter.md); the third fixture in
`tests/test_docs.py`,
`test_library_format_graph_page_example_matches_compiler_output`):

<!-- pinned: example-graph-page -->
```markdown
# Scrolls Link Graph

2 scrolls connected across 1 cluster.

## Cluster 1

2 scrolls.

- [Attention Is All You Need](../scrolls/arxiv/attention-is-all-you-need.md) — arxiv
- [google-bert/bert-base-uncased](../scrolls/huggingface/google-bert-bert-base-uncased.md) — huggingface
  - → [Attention Is All You Need](../scrolls/arxiv/attention-is-all-you-need.md)
```

### The works page

`library/works.md` is the browsable form of `scrolls works`'s JSON
(ADR [0069](adr/0069-works-by-doi.md),
ADR [0070](adr/0070-kb-works-page.md)): the library's scholarly works
that sit in it as more than one near-duplicate `paper` entry — an arXiv
preprint, its published Crossref article, a PubMed record, a
bioRxiv/medRxiv preprint — grouped by the **DOI that names the work**.
Like the graph page it is built over the rendered items only, so every
representation links to a scroll file (a work whose rendered
representations drop below two isn't shown). Each work is a `## <doi>`
section: the `doi.org` resolver link and a representation count, then every
representation as a bullet linking to its scroll. The page is always
written, like the index; a library with no DOI held in two-plus
representations gets a single `No works held in multiple representations
yet.` line, so the page is a stable entry point
(`test_kb_works_page_clusters_representations_by_shared_doi`,
`test_kb_works_page_is_empty_when_no_shared_doi`).

Because the page scopes to *rendered* items while `scrolls works` clusters
over the whole library, the page's work count can be smaller than the
CLI's — the same rendered-only divergence the graph page has from `scrolls
graph`.

Compiled from a rendered arXiv preprint that names its published DOI as a
link and the rendered Crossref record whose `source_id` *is* that DOI (the
preprint↔published edge of ADR [0038](adr/0038-arxiv-published-doi-link.md);
the fourth and fifth fixtures in `tests/test_docs.py`,
`test_library_format_works_page_example_matches_compiler_output`). The
representation that stands for the whole work — the registered published
record over the preprint, by `Work.canonical`
(ADR [0095](adr/0095-canonical-representation.md)) — is marked `· canonical`:

<!-- pinned: example-works-page -->
```markdown
# Scrolls Works

1 work held as 2 representations.

## 10.5555/3295222

[doi.org/10.5555/3295222](https://doi.org/10.5555/3295222) — 2 representations.

- [Attention Is All You Need](../scrolls/arxiv/attention-is-all-you-need.md) — arxiv
- [Attention Is All You Need](../scrolls/crossref/attention-is-all-you-need.md) — crossref · canonical
```

## Captured media files: `media/`

`scrolls media` (ADR [0011](adr/0011-media-capture-command.md))
downloads items' media references — arXiv PDFs, youtube thumbnails, x
photos — to `media/<source>/<id-slug>-<n><ext>`, where `<n>` is the
ref's 1-based position in the item's `media` array and the extension
comes from the URL path, else from the ref's `type`
(`tests/test_media.py`). The file's root-relative location is recorded
back onto the ref as `path` (the frontmatter example above shows the
result), and a recorded `path` is reused on re-capture, so locations are
as stable as scroll paths. Files are plain downloads — no
transformation — and can always be re-fetched from the recorded `url`,
so the media tree is cache, not canon.

## Agent instruction files: `agents/`

`scrolls agent install` (ADR
[0006](adr/0006-agent-install-stays-in-library-root.md)) writes exactly
three files — `agents/claude/SKILL.md`, `agents/codex/AGENTS.md`,
`agents/hermes/SKILL.md` — one shared command-reference body, wrapped in
skill frontmatter for Claude Code and Hermes and left plain for Codex
(`test_skill_files_carry_frontmatter_and_commands`,
`test_codex_file_is_plain_markdown_without_frontmatter`). They are
regenerated templates, overwritten on every install run
(`test_agent_install_regenerates_edited_files`): customize the copy you
wire into your tool, not the originals.
`test_library_format_names_every_generated_artifact` keeps this section
in sync with what the code actually writes.

## What consumers may rely on

Stable — agents and scripts may depend on these:

- Frontmatter is line-oriented `key: <JSON value>` between `---`
  delimiters; any key present parses as JSON. Absent means unknown or
  empty, never `""` or `[]`.
- `id`, `source`, `url`, `saved_at` are always in frontmatter; the H1
  and the `## Links` section (starting with the `- Source:` line) are
  always in the body.
- A scroll's path never changes once written.
- After a `scrolls kb` run, `library/index.md`, `library/graph.md`, and
  `library/works.md` exist and every link in the generated tree resolves;
  non-generated files under `library/` survive recompiles.
- Every generated page is wrapped in the sentinel fence (`<!-- @generated
  scrolls … -->` … `<!-- @end scrolls -->`). A re-compile replaces only the
  fenced region; an annotation outside the fence survives (ADR 0102).

Not stable — expect these to grow without notice:

- New frontmatter keys, new body sections, and new generated
  subtrees may appear as features land (parse by key and heading, not
  by position or count).
- Wording of count lines and note suffixes on KB pages is
  presentational, not data — parse scroll frontmatter or call the CLI
  (`docs/cli.md`) when you need structured answers.
