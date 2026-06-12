# Scrolls CLI Reference

The output contract for every command: arguments, JSON keys, exit codes,
and error envelopes. This is the reference for agents (and contributors)
consuming `scrolls` output programmatically; `README.md` tells the same
story in prose, and `docs/architecture.md` explains the system behind it.

Every example below is real output captured from `scrolls 0.1.0`
(schema version 3) on this branch — see
[Reproducing these examples](#reproducing-these-examples). Each behavior
claim cites the test that locks it; unless noted, tests live in
`tests/test_cli.py`.

## Conventions

- **JSON on stdout.** Every data command prints exactly one compact JSON
  document. Two deliberate exceptions emit Markdown: `scrolls context`
  (the bundle *is* the artifact) and the scroll/library files themselves.
- **Errors are JSON on stderr, exit 1.** Shape: `{"error": "<message>"}`.
  Nothing is printed to stdout in that case
  (`test_detect_rejects_non_http_url`, `test_show_unknown_id_is_an_error`).
- **Batch commands report per-item results.** `fetch`, `classify`, `md`,
  and `import fieldtheory` process every item, never abort mid-batch, and
  exit 1 if **any** item *failed* — skipped items do not fail the run
  (`test_fetch_continues_past_failures_and_exits_nonzero`,
  `test_fetch_all_skips_sources_without_adapter`).
- **`ingest` is the asymmetry to know about:** its failure payload goes to
  *stdout* (with an `error` key merged into the normal payload) plus
  exit 1, because the item was still registered
  (`test_ingest_without_adapter_registers_but_reports_failure`).
- **Library root** is `~/.scrolls`, overridden by `$SCROLLS_HOME`
  (`tests/test_paths.py`). Commands that write auto-initialize the
  library; read-only commands on a missing library return empty results
  rather than errors (`test_list_before_init_prints_empty_array`,
  `test_search_before_init_prints_empty_array`).
- **Item ids** are stable and deduplicating: `source:source_id` when the
  URL carries a source-local id (`wikipedia:en:SQLite`,
  `arxiv:1706.03762`, `x:1111`), else `source:` + a 12-hex-char SHA-256
  of the URL (`tests/test_items.py`).
- **Stages**: `detected → fetched → rendered`, advanced by
  `fetch` and `md`; `classify` and `kb` are stage-neutral.

## Library lifecycle

### `scrolls init`

Create the library skeleton (idempotent; an existing `config.toml` is
preserved — `test_init_is_idempotent_and_preserves_config`).

| Key | Meaning |
| --- | --- |
| `root` | library root in use |
| `created` | `false` when the skeleton already existed |

```console
$ scrolls init
{"root": "/tmp/scrolls-demo.BgrqMO/home", "created": true}
[exit 0]
```

### `scrolls status`

Report library state without creating anything
(`test_status_before_init`, `test_status_after_init`).
`schema_version` is `null` until `init` (current version: 3,
`src/scrolls/db.py`).

```console
$ scrolls status        # before init
{"initialized": false, "root": "/tmp/scrolls-demo.BgrqMO/home-empty", "schema_version": null}
[exit 0]

$ scrolls status        # after init
{"initialized": true, "root": "/tmp/scrolls-demo.BgrqMO/home", "schema_version": 3}
[exit 0]
```

### `scrolls paths`

Print every library path (`test_paths_prints_layout_json`). `items` and
`media` are reserved directories, currently unused.

```console
$ scrolls paths
{"root": "/tmp/scrolls-demo.BgrqMO/home", "items": "/tmp/scrolls-demo.BgrqMO/home/items", "scrolls": "/tmp/scrolls-demo.BgrqMO/home/scrolls", "library": "/tmp/scrolls-demo.BgrqMO/home/library", "media": "/tmp/scrolls-demo.BgrqMO/home/media", "agents": "/tmp/scrolls-demo.BgrqMO/home/agents", "db": "/tmp/scrolls-demo.BgrqMO/home/db.sqlite", "config": "/tmp/scrolls-demo.BgrqMO/home/config.toml"}
[exit 0]
```

## Getting items in

### `scrolls detect <url>`

Pure URL inspection, no network, nothing stored
(`tests/test_detect.py`). A known source with `"source_id": null` means
the adapter resolves identity at fetch time; unknown hosts fall back to
`"source": "web"`.

```console
$ scrolls detect https://en.wikipedia.org/wiki/SQLite
{"source": "wikipedia", "source_id": "en:SQLite"}
[exit 0]

$ scrolls detect notaurl
{"error": "not an http(s) URL: 'notaurl'"}
[exit 1]
```

### `scrolls add <url>`

Register a URL as an item at stage `detected` — no network. Re-adding
(or adding another URL form of the same item) returns the existing row
with `"created": false` (`test_add_persists_detected_item`,
`test_add_same_video_via_other_url_form_is_deduped`).

| Key | Meaning |
| --- | --- |
| `id`, `source`, `source_id`, `url` | identity as detected |
| `stage` | always `detected` for a new row |
| `created` | `false` when the item already existed |

```console
$ scrolls add https://example.com/papers/attention.pdf
{"id": "pdf:eb2e6487c357", "source": "pdf", "source_id": null, "url": "https://example.com/papers/attention.pdf", "stage": "detected", "created": true}
[exit 0]
```

### `scrolls ingest <url>`

`add` + `fetch` + `classify` + `md` for one URL (network). On success the
payload carries the rendered result; re-ingesting refreshes content but
never replaces an existing category
(`test_ingest_runs_add_fetch_md_in_one_command`,
`test_ingest_existing_url_refreshes_it`).

```console
$ scrolls ingest https://en.wikipedia.org/wiki/SQLite
{"id": "wikipedia:en:SQLite", "source": "wikipedia", "url": "https://en.wikipedia.org/wiki/SQLite", "created": true, "title": "SQLite", "category": "reference", "stage": "rendered", "markdown_path": "scrolls/wikipedia/sqlite.md"}
[exit 0]
```

When the source has no fetch adapter, or the fetch fails, the item is
still registered (stage `detected`) and the same payload gains an
`error` key — on **stdout**, exit 1
(`test_ingest_without_adapter_registers_but_reports_failure`,
`test_ingest_fetch_failure_leaves_item_detected`):

```console
$ scrolls ingest https://example.com/papers/attention.pdf
{"id": "pdf:eb2e6487c357", "source": "pdf", "url": "https://example.com/papers/attention.pdf", "created": false, "stage": "detected", "error": "no fetch adapter for source 'pdf'"}
[exit 1]
```

### `scrolls import fieldtheory [--root PATH]`

Bulk-import X bookmarks from a local Field Theory archive (default root
`~/.fieldtheory`; ADR 0009) — items arrive directly at stage `fetched`.
Existing items are never overwritten, so re-imports are cheap and safe
(`test_import_fieldtheory_end_to_end`,
`test_import_fieldtheory_is_idempotent`). Per-item success entries are
omitted (imports can cover hundreds of bookmarks); only line-level
failures are detailed, and any failure exits 1
(`test_import_fieldtheory_reports_bad_lines`). A missing archive is an
error envelope on stderr
(`test_import_fieldtheory_missing_archive_is_an_error`).

| Key | Meaning |
| --- | --- |
| `imported` | new items inserted |
| `skipped` | already existed (id collision is the dedupe working) |
| `failed` / `failures` | unparseable JSONL lines, with line numbers |

```console
$ scrolls import fieldtheory --root /tmp/scrolls-demo.BgrqMO/fieldtheory
{"imported": 2, "skipped": 0, "failed": 0, "failures": []}
[exit 0]

$ scrolls import fieldtheory --root /tmp/scrolls-demo.BgrqMO/fieldtheory
{"imported": 0, "skipped": 2, "failed": 0, "failures": []}
[exit 0]
```

## Pipeline stages

### `scrolls fetch [id]`

No argument: run the source adapter for every item at stage `detected`
(network). Items whose source has no adapter yet are *skipped* (they stay
`detected` for a future scrolls) and do not fail the run
(`test_fetch_all_skips_sources_without_adapter`). With an id: refetch
that one item regardless of stage — and asking for an adapterless item
by id is an honest *failure*, not a skip
(`test_fetch_by_id_refetches_regardless_of_stage`,
`test_fetch_by_id_without_adapter_fails`).

| Key | Meaning |
| --- | --- |
| `fetched` / `skipped` / `failed` | batch counts |
| `results[]` | per-item `{id, status, ...}`; `title`+`stage` on success, `reason` on skip, `error` on failure |

```console
$ scrolls fetch                       # only a pdf item is detected
{"fetched": 0, "skipped": 1, "failed": 0, "results": [{"id": "pdf:eb2e6487c357", "status": "skipped", "reason": "no fetch adapter for source 'pdf'"}]}
[exit 0]

$ scrolls fetch pdf:eb2e6487c357      # by id: same situation is a failure
{"fetched": 0, "skipped": 0, "failed": 1, "results": [{"id": "pdf:eb2e6487c357", "status": "failed", "error": "no fetch adapter for source 'pdf'"}]}
[exit 1]

$ scrolls fetch arxiv:1706.03762      # by id, with network
{"fetched": 1, "skipped": 0, "failed": 0, "results": [{"id": "arxiv:1706.03762", "status": "fetched", "title": "Attention Is All You Need", "stage": "fetched"}]}
[exit 0]
```

### `scrolls classify [id]`

No argument: assign a `category` (rules engine `rules-v1`, ADR 0004) to
every fetched/rendered item that has none — an existing category, user-set
or imported, is never overwritten
(`test_classify_batch_never_overwrites_an_existing_category`). Unmatched
items honestly report `"status": "unmatched"` and stay unclassified
(`test_classify_batch_reports_unmatched_items`). With an id: explicit
reclassify, replacing any existing category
(`test_classify_by_id_reclassifies_explicitly`). Already-rendered scrolls
are re-rendered so frontmatter stays in sync
(`test_classify_batch_categorizes_and_rerenders`).

```console
$ scrolls classify    # x:1111 already has a category from the import join
{"classified": 1, "unmatched": 0, "failed": 0, "results": [{"id": "x:2222", "status": "classified", "category": "tutorial"}]}
[exit 0]
```

### `scrolls md [id]`

No argument: render every item at stage `fetched` to a Markdown scroll
at `scrolls/<source>/<slug>.md` (`tests/test_render.py`). With an id:
re-render even if already rendered; `markdown_path` keeps the path stable
across re-renders (`test_md_by_id_rerenders_a_rendered_item`,
`test_md_bulk_run_is_idempotent`). An item with no fetched content fails
(`test_md_by_id_fails_for_unfetched_item`).

```console
$ scrolls md
{"rendered": 2, "failed": 0, "results": [{"id": "x:1111", "status": "rendered", "path": "scrolls/x/karpathy-sqlite-fts5-is-criminally-underrated-for-local-search.md"}, {"id": "x:2222", "status": "rendered", "path": "scrolls/x/simonw-attention-is-all-you-need-still-holds-up-a-guide-to-reading-it-prope.md"}]}
[exit 0]
```

## Reading the library

### `scrolls list`

Every item as a summary array (full records: `scrolls show`). An empty or
uninitialized library prints `[]` (`test_list_after_adds_prints_summaries`,
`test_list_before_init_prints_empty_array`). Summary keys: `id`,
`source`, `url`, `title`, `stage`, `saved_at`.

```console
$ scrolls list
[{"id": "x:1111", "source": "x", "url": "https://x.com/karpathy/status/1111", "title": "@karpathy: SQLite FTS5 is criminally underrated for local search.", "stage": "fetched", "saved_at": "2026-06-04T04:27:46+00:00"}, {"id": "x:2222", ...}, {"id": "pdf:eb2e6487c357", ..., "title": null, "stage": "detected", ...}, {"id": "arxiv:1706.03762", ...}]
[exit 0]
```

*(array entries after the first elided here for width — every entry has
the same six keys)*

### `scrolls show <id>`

One item in full: every `ScrollItem` field
(`docs/architecture.md` → "The data model"), with list fields always
present as JSON arrays (`test_show_prints_full_item_json`). Unset fields
are `null`, not omitted.

```console
$ scrolls show x:1111
{"id": "x:1111", "source": "x", "url": "https://x.com/karpathy/status/1111", "saved_at": "2026-06-04T04:27:46+00:00", "source_id": "1111", "canonical_url": null, "title": "@karpathy: SQLite FTS5 is criminally underrated for local search.", "author": "Andrej Karpathy (@karpathy)", "published_at": "2026-06-01T15:34:00+00:00", "raw_text": "{\"id\": \"1111\", \"tweetId\": \"1111\", …}", "extracted_text": "SQLite FTS5 is criminally underrated for local search.", "summary": null, "category": "technique", "domain": "databases", "tags": [], "concepts": [], "links": ["https://sqlite.org/fts5.html"], "media": [], "content_hash": "sha256:da27b0…", "markdown_path": "scrolls/x/karpathy-sqlite-fts5-is-criminally-underrated-for-local-search.md", "provenance": {"adapter": "fieldtheory-import", "fetched_at": "2026-06-12T19:10:47+00:00", "extraction_method": "fieldtheory:bookmarks.jsonl"}, "stage": "rendered"}
[exit 1 if no such item, else 0]
```

*(the `raw_text` and `content_hash` values are elided here for width;
the real output is one complete compact JSON document)*

```console
$ scrolls show x:9999
{"error": "no such item: x:9999"}
[exit 1]
```

### `scrolls search <query> [--limit N]`

FTS5 BM25 over title/summary/extracted text, title weighted highest
(`src/scrolls/search.py`, `tests/test_search.py`). Query tokens are
quoted and AND-ed, so arbitrary agent input never hits FTS5 syntax
errors. `score` is SQLite's `bm25()`: results are ordered best-first and
**more negative means a stronger match**. Default limit 20
(`test_search_respects_limit_flag`). No matches prints `[]`; a blank
query is an error (`test_search_blank_query_is_an_error`).

Hit keys: `id`, `source`, `title`, `url`, `stage`, `score`, `snippet`
(matches bracketed, `…` for elided context).

```console
$ scrolls search "sqlite fts5"
[{"id": "x:1111", "source": "x", "title": "@karpathy: SQLite FTS5 is criminally underrated for local search.", "url": "https://x.com/karpathy/status/1111", "stage": "rendered", "score": -2.9315057596986334, "snippet": "@karpathy: [SQLite] [FTS5] is criminally underrated for local search."}]
[exit 0]

$ scrolls search "   "
{"error": "search query has no searchable tokens"}
[exit 1]
```

### `scrolls related <id> [--limit N]`

Deterministic, explainable connections (IDEAS.md §10,
`tests/test_related.py`): link edges in either direction (resolved
through source detection, so a tweet linking to `arxiv.org/abs/X` finds
item `arxiv:X`), shared concepts, shared tags, same category/domain as
weak corroboration. `score` is an integer (higher = more connected) and
every hit carries its `reasons`. Default limit 10. Unknown id is an
error envelope on stderr.

```console
$ scrolls related x:2222
[{"id": "arxiv:1706.03762", "source": "arxiv", "title": null, "url": "https://arxiv.org/abs/1706.03762", "stage": "detected", "score": 5, "reasons": ["links to it"]}]
[exit 0]
```

### `scrolls context <query> [--limit N]`

The Markdown exception: a compact context bundle — best matches,
capped excerpts, source links — that agents drop directly into context
(IDEAS.md §11, `tests/test_context.py`). Each excerpt carries the item
id, source, and scroll path for follow-up with `scrolls show` or a file
read. Default limit 8. Errors are still JSON on stderr (blank query, as
with `search`).

```console
$ scrolls context "local search"
# Scrolls Context Bundle: local search

## Best Matches

1. @karpathy: SQLite FTS5 is criminally underrated for local search. (`x:1111`) — technique

## Excerpts

### @karpathy: SQLite FTS5 is criminally underrated for local search.

`x:1111` · x · scrolls/x/karpathy-sqlite-fts5-is-criminally-underrated-for-local-search.md

SQLite FTS5 is criminally underrated for local search.

## Links

- [@karpathy: SQLite FTS5 is criminally underrated for local search.](https://x.com/karpathy/status/1111)
[exit 0]
```

## Derived artifacts

### `scrolls kb`

Rebuild the interlinked library pages under `library/` from scratch
(stale groups can't linger; other files there are untouched — ADR 0005,
`tests/test_kb.py`). Output is the compile summary.

| Key | Meaning |
| --- | --- |
| `items` | rendered scrolls included |
| `sources` / `categories` / `concepts` | group pages written per kind |
| `pages` | total files written, including `index.md` |

```console
$ scrolls kb
{"items": 2, "sources": 1, "categories": 2, "concepts": 0, "pages": 4}
[exit 0]
```

### `scrolls agent install`

Write agent instruction files under `<root>/agents/` — never into
another tool's config tree; copy or symlink them where your tool expects
them (ADR 0006, `tests/test_agents.py`).

```console
$ scrolls agent install
{"root": "/tmp/scrolls-demo.BgrqMO/home", "installed": ["agents/claude/SKILL.md", "agents/codex/AGENTS.md", "agents/hermes/SKILL.md"]}
[exit 0]
```

## Reproducing these examples

Everything above except the two marked network calls (`ingest` of a
Wikipedia page, `fetch arxiv:1706.03762`) runs fully offline. Scratch
setup:

```bash
DEMO=$(mktemp -d)
export SCROLLS_HOME="$DEMO/home"

mkdir -p "$DEMO/fieldtheory/bookmarks" "$DEMO/fieldtheory/library/bookmarks"
cat > "$DEMO/fieldtheory/bookmarks/bookmarks.jsonl" <<'EOF'
{"id": "1111", "tweetId": "1111", "url": "https://x.com/karpathy/status/1111", "text": "SQLite FTS5 is criminally underrated for local search.", "authorHandle": "karpathy", "authorName": "Andrej Karpathy", "postedAt": "Mon Jun 01 15:34:00 +0000 2026", "syncedAt": "2026-06-04T04:27:46.057Z", "media": [], "links": ["https://sqlite.org/fts5.html"], "tags": []}
{"id": "2222", "tweetId": "2222", "url": "https://x.com/simonw/status/2222", "text": "Attention Is All You Need still holds up - a guide to reading it properly.", "authorHandle": "simonw", "authorName": "Simon Willison", "postedAt": "Tue Jun 02 09:12:00 +0000 2026", "syncedAt": "2026-06-04T04:27:46.057Z", "media": [], "links": ["https://arxiv.org/abs/1706.03762"], "tags": []}
EOF
cat > "$DEMO/fieldtheory/library/bookmarks/2026-06-01-karpathy.md" <<'EOF'
---
category: technique
domain: databases
tweet_id: "1111"
---
EOF
```

Then, in order (`uv run scrolls …` when running from a source checkout):

```bash
scrolls init
scrolls status
scrolls paths
scrolls detect https://en.wikipedia.org/wiki/SQLite
scrolls add https://example.com/papers/attention.pdf
scrolls fetch                                      # skips the pdf item
scrolls fetch pdf:<id-from-add>                    # by-id: fails, exit 1
scrolls import fieldtheory --root "$DEMO/fieldtheory"
scrolls import fieldtheory --root "$DEMO/fieldtheory"   # idempotent
scrolls add https://arxiv.org/abs/1706.03762
scrolls list
scrolls classify
scrolls md
scrolls search "sqlite fts5"
scrolls show x:1111
scrolls related x:2222
scrolls kb
scrolls context "local search"
scrolls agent install
```

The walkthrough exercises the dedupe (`x:` ids from the import collide
with `scrolls add` of the same tweet URL on purpose), the title-pattern
classify rule (`x:2222`'s "a guide to" → `tutorial`), and the
link-resolution path of `related` (`x:2222` → `arxiv:1706.03762`) — the
same behaviors the test suite locks.
