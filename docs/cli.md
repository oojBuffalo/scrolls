# Scrolls CLI Reference

The output contract for every command: arguments, JSON keys, exit codes,
and error envelopes. This is the reference for agents (and contributors)
consuming `scrolls` output programmatically; `README.md` tells the same
story in prose, and `docs/architecture.md` explains the system behind it.

Every example below is real output captured from `scrolls 0.1.0`
(schema version 5) on this branch — see
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
  `media`, `sync`, and `import fieldtheory` process every item (for
  `sync`, every subscription), never abort mid-batch, and exit 1 if
  **any** item *failed* — skipped items do not
  fail the run (`test_fetch_continues_past_failures_and_exits_nonzero`,
  `test_fetch_all_skips_sources_without_adapter`,
  `test_media_continues_past_failures_and_exits_nonzero`,
  `test_sync_continues_past_feed_failures_and_exits_nonzero`).
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
  `fetch` and `md`; `classify`, `media`, and `kb` are stage-neutral.

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
`schema_version` is `null` until `init` (current version: 5,
`src/scrolls/db.py`).

```console
$ scrolls status        # before init
{"initialized": false, "root": "/tmp/scrolls-demo.BgrqMO/home-empty", "schema_version": null}
[exit 0]

$ scrolls status        # after init
{"initialized": true, "root": "/tmp/scrolls-demo.BgrqMO/home", "schema_version": 5}
[exit 0]
```

### `scrolls paths`

Print every library path (`test_paths_prints_layout_json`). `items` is a
reserved directory, currently unused; `media` holds files downloaded by
`scrolls media`.

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
`test_add_same_video_via_other_url_form_is_deduped`). The URL is
normalized first (ADR 0023): tracking params (`utm_*`, `fbclid`, …),
fragments, host casing, and default ports are stripped before hashing
and storing, so differently decorated links to the same page dedupe to
one item with a clean `url`
(`test_add_strips_tracking_params_before_identity`,
`test_add_stores_the_normalized_url`; `tests/test_urls.py` pins what
normalization may and may not touch).

| Key | Meaning |
| --- | --- |
| `id`, `source`, `source_id`, `url` | identity as detected, URL normalized |
| `stage` | always `detected` for a new row |
| `created` | `false` when the item already existed |

```console
$ scrolls add https://x.com/karpathy/status/3333
{"id": "x:3333", "source": "x", "source_id": "3333", "url": "https://x.com/karpathy/status/3333", "stage": "detected", "created": true}
[exit 0]

$ scrolls add 'https://blog.example.com/post?utm_source=newsletter&fbclid=IwAR0'
{"id": "web:dc65501e6b9a", "source": "web", "source_id": null, "url": "https://blog.example.com/post", "stage": "detected", "created": true}
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
$ scrolls ingest https://x.com/karpathy/status/3333
{"id": "x:3333", "source": "x", "url": "https://x.com/karpathy/status/3333", "created": false, "stage": "detected", "error": "no fetch adapter for source 'x'"}
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

## Following feeds

Live delta updates are feed-based (IDEAS.md §13, ADR 0017): follow any
RSS 2.0/Atom feed — a blog, a YouTube channel or playlist, an arXiv
category, a GitHub releases feed — and `sync` registers its new entries
through the same detection/dedupe as `scrolls add`. The examples below
talk to a feed served from localhost; any feed URL behaves the same
(see [Reproducing these examples](#reproducing-these-examples)).

### `scrolls follow [url]`

Subscribe to a feed. The URL is fetched once (network) to validate it
and capture the feed's title — a typo'd or non-feed URL is rejected
with nothing stored, instead of failing every future sync
(`test_follow_unreachable_feed_is_an_error`;
`test_follow_feed_bad_feed_stores_nothing` in `tests/test_feeds.py`).
Re-following returns the stored row with `"created": false`
(`test_follow_is_idempotent`). YouTube playlist and channel-id page
URLs map to their public Atom feeds purely syntactically
(`test_follow_youtube_playlist_url_follows_its_feed`). Without a URL:
list current subscriptions
(`test_follow_without_url_lists_subscriptions`,
`test_follow_list_before_init_prints_empty_array`).

| Key | Meaning |
| --- | --- |
| `id` | subscription id — 12 hex chars of the feed URL's SHA-256 |
| `feed_url` | the feed that will be polled (after any URL mapping) |
| `title` | the feed's own title, if it declares one |
| `created` | `false` when the feed was already followed |

```console
$ scrolls follow http://localhost:8943/feed.xml
{"id": "ea77c1d5239e", "feed_url": "http://localhost:8943/feed.xml", "title": "Demo Weblog", "created": true}
[exit 0]

$ scrolls follow http://localhost:8943/missing.xml
{"error": "feed request failed: HTTP Error 404: File not found"}
[exit 1]

$ scrolls follow
[{"id": "ea77c1d5239e", "feed_url": "http://localhost:8943/feed.xml", "title": "Demo Weblog", "added_at": "2026-06-12T22:07:58+00:00", "last_synced_at": null, "etag": null, "last_modified": null}]
[exit 0]
```

The listing's `etag`/`last_modified` are the feed's HTTP cache
validators, stored by the last full sync (ADR 0019) — always `null`
right after `follow`, which deliberately stores none
(`test_follow_feed_stores_no_validators` in `tests/test_feeds.py`):
follow registers no entries, so a stored validator would make the
first sync skip the feed's current entries.

### `scrolls sync [id]`

Poll every followed feed (network) and register each new entry URL as
an item at stage `detected` — exactly what `scrolls add` would store,
so a YouTube feed entry becomes a `youtube` item and a blog entry a
`web` item (`test_sync_registers_new_items_at_stage_detected`), except
that the entry's feed title names the item until fetch replaces it
(`test_sync_seeds_detected_items_with_entry_titles`,
`test_sync_never_retitles_known_items` in `tests/test_feeds.py`). Sync
only discovers URLs; run `scrolls fetch` (then `classify`/`md`) to
bring the new items in. Entries already in the library count as
`known`, so re-syncs are cheap (`test_sync_is_idempotent`); entries
whose link is not http(s) are skipped. Entry links are normalized like
`scrolls add` URLs (ADR 0023), so a feed that rotates tracking params
on its links never re-registers the same post
(`test_sync_normalizes_tracking_params_out_of_entry_links`). With an
id: sync only that
subscription (`test_sync_by_id_syncs_one_subscription`); unknown ids
are an error envelope (`test_sync_unknown_id_is_an_error`). One dead
feed fails its subscription but never the batch.

Each poll is a conditional GET (ADR 0019): a full response's
`ETag`/`Last-Modified` are stored on the subscription, and when the
server answers `304 Not Modified` on the next poll the subscription
reports `"status": "unchanged"` without re-downloading or re-parsing
the feed (`test_sync_unchanged_feed_reports_unchanged`;
`test_sync_not_modified_reports_unchanged` in `tests/test_feeds.py`).
Feeds that serve no validators just get a full response every time.

| Key | Meaning |
| --- | --- |
| `new` / `known` / `skipped` / `failed` / `unchanged` | totals (`failed` and `unchanged` count subscriptions) |
| `results[]` | per-subscription `{id, feed_url, status, ...}` with its own counts; `new_items` lists registered item ids, `error` the failure |

```console
$ scrolls sync
{"new": 2, "known": 0, "skipped": 0, "unchanged": 0, "failed": 0, "results": [{"id": "ea77c1d5239e", "feed_url": "http://localhost:8943/feed.xml", "status": "synced", "new": 2, "known": 0, "skipped": 0, "new_items": ["web:081e89b0b346", "web:dbeb9a37d69a"]}]}
[exit 0]

$ scrolls sync          # the feed is unchanged: the server answers 304
{"new": 0, "known": 0, "skipped": 0, "unchanged": 1, "failed": 0, "results": [{"id": "ea77c1d5239e", "feed_url": "http://localhost:8943/feed.xml", "status": "unchanged", "new": 0, "known": 0, "skipped": 0, "new_items": []}]}
[exit 0]

$ touch "$DEMO/site/feed.xml"   # the feed "changes" (new Last-Modified)
$ scrolls sync          # full response again; the same entries are known
{"new": 0, "known": 2, "skipped": 0, "unchanged": 0, "failed": 0, "results": [{"id": "ea77c1d5239e", "feed_url": "http://localhost:8943/feed.xml", "status": "synced", "new": 0, "known": 2, "skipped": 0, "new_items": []}]}
[exit 0]
```

### `scrolls unfollow <id>`

Remove a subscription by id — or by feed URL, which resolves to the
same id `follow` minted (`test_unfollow_removes_subscription`,
`test_unfollow_accepts_the_feed_url`). Items the feed registered stay
in the library; only the subscription goes. Unknown ids are an error
envelope (`test_unfollow_unknown_id_is_an_error`).

```console
$ scrolls unfollow http://localhost:8943/feed.xml
{"id": "ea77c1d5239e", "removed": true}
[exit 0]

$ scrolls unfollow ea77c1d5239e
{"error": "no such subscription: ea77c1d5239e"}
[exit 1]
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
$ scrolls fetch                       # only an x item is detected
{"fetched": 0, "skipped": 1, "failed": 0, "results": [{"id": "x:3333", "status": "skipped", "reason": "no fetch adapter for source 'x'"}]}
[exit 0]

$ scrolls fetch x:3333                # by id: same situation is a failure
{"fetched": 0, "skipped": 0, "failed": 1, "results": [{"id": "x:3333", "status": "failed", "error": "no fetch adapter for source 'x'"}]}
[exit 1]

$ scrolls fetch arxiv:1706.03762      # by id, with network
{"fetched": 1, "skipped": 0, "failed": 0, "results": [{"id": "arxiv:1706.03762", "status": "fetched", "title": "Attention Is All You Need", "stage": "fetched"}]}
[exit 0]
```

### `scrolls classify [id]`

No argument: assign a `category` (rules engine `rules-v1`, ADR 0004) to
every fetched/rendered item that has none — an existing category, user-set
or imported, is never overwritten
(`test_classify_batch_never_overwrites_an_existing_category`,
`test_classify_llm_batch_never_overwrites_an_existing_category`). Unmatched
items honestly report `"status": "unmatched"` and stay unclassified
(`test_classify_batch_reports_unmatched_items`). With an id: explicit
reclassify, replacing any existing category
(`test_classify_by_id_reclassifies_explicitly`). Already-rendered scrolls
are re-rendered so frontmatter stays in sync
(`test_classify_batch_categorizes_and_rerenders`).

`--engine llm` (engine `llm-v1`, ADR 0015) classifies with a model via the
Anthropic API instead (network; needs `ANTHROPIC_API_KEY`; default model
`claude-opus-4-8`, overridable via `SCROLLS_LLM_MODEL`). It uses the full
IDEAS.md §8 category vocabulary and additionally fills `domain` and merges
model `concepts` after the platform-curated ones; classified results carry
`domain` and `concepts` keys
(`test_classify_llm_engine_classifies_and_rerenders`, in
`tests/test_classify_llm.py` for the engine itself). Batch semantics are
unchanged — never overwrites an existing category, per-item API failures
don't abort the batch
(`test_classify_llm_failure_is_reported_not_raised`) — except that missing
credentials abort the whole run with the standard error envelope, since
every remaining item would fail identically
(`test_classify_llm_without_credentials_aborts_with_error_envelope`).

`--batch` (ADR 0022) submits the whole `--engine llm` run as one Message
Batches API request at half the per-token price, polling until the batch
ends — typically minutes — instead of one API call per item
(`test_classify_llm_batch_flag_submits_one_batch`;
`test_batch_classifies_every_item_in_order` and
`test_real_batch_submits_polls_and_collects_results` in
`tests/test_classify_llm.py` for the engine and transport). Per-request
failures — errored, expired, refused — fail their item without aborting
the batch (`test_batch_per_item_errors_pass_through`), and missing
credentials still abort the run
(`test_classify_llm_batch_without_credentials_aborts_with_error_envelope`).
The flag needs the llm engine and a whole-run invocation
(`test_classify_batch_flag_requires_the_llm_engine`,
`test_classify_batch_flag_rejects_an_item_id`).

`config.toml`'s `[classify]` section (ADR 0016) sets the defaults:
`default_engine = "llm"` routes a bare `scrolls classify` to the LLM
engine (`test_classify_config_default_engine_llm_is_used`) and
`llm_model` picks its model
(`test_classify_config_llm_model_is_used`). Per-invocation overrides
win — `--engine` beats `default_engine`
(`test_classify_engine_flag_overrides_config`) and `$SCROLLS_LLM_MODEL`
beats `llm_model` (`test_classify_env_model_beats_config`). A malformed
or invalid config is an error envelope, never a silent fallback
(`test_classify_malformed_config_is_an_error_envelope`,
`tests/test_config.py` for the parser itself).

```console
$ scrolls classify    # x:1111 already has a category from the import join
{"classified": 1, "unmatched": 0, "failed": 0, "results": [{"id": "x:2222", "status": "classified", "category": "tutorial"}]}
[exit 0]

$ scrolls classify wikipedia:en:SQLite --engine llm   # no credentials set
{"error": "llm engine needs Anthropic credentials: set ANTHROPIC_API_KEY (\"Could not resolve authentication method. Expected one of api_key, auth_token, or credentials to be set. Or for one of the `X-Api-Key` or `Authorization` headers to be explicitly omitted\")"}
[exit 1]

$ scrolls classify       # after writing broken TOML into config.toml
{"error": "config.toml: invalid TOML: Expected ']' at the end of a table declaration (at line 1, column 10)"}
[exit 1]

$ scrolls classify --batch     # the rules engine has nothing to batch
{"error": "--batch requires the llm engine (--engine llm)"}
[exit 1]
```

### `scrolls set <id> field=value...`

Layer three of IDEAS.md §8 — user overrides always win (ADR 0018). Set
exactly the fields the classification engines write: `category`,
`domain`, and the comma-separated lists `tags` and `concepts`
(`test_set_overrides_fields_and_rerenders`). Values are free-form —
engines pin vocabularies, the user's word is final. An empty value
clears the field, returning the item to the batch-classifiable pool
(`test_set_empty_value_clears_for_reclassification`); list values
replace, not merge. A set category sticks because batch `classify`
never overwrites one (`test_set_survives_batch_classify`). A rendered
scroll is re-rendered so frontmatter stays in sync; nothing is applied
when any assignment is invalid (`test_set_unknown_field_is_an_error`,
`test_set_malformed_assignment_is_an_error`; the parser itself in
`tests/test_overrides.py`).

```console
$ scrolls set x:1111 tags=sqlite,fts "concepts=full-text search"
{"id": "x:1111", "status": "set", "category": "technique", "domain": "databases", "tags": ["sqlite", "fts"], "concepts": ["full-text search"], "markdown_path": "scrolls/x/karpathy-sqlite-fts5-is-criminally-underrated-for-local-search.md"}
[exit 0]

$ scrolls set x:1111 usefulness=high
{"error": "cannot set 'usefulness'; settable fields: category, domain, tags, concepts"}
[exit 1]
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

### `scrolls media [id]`

No argument: download every uncaptured media reference — arXiv PDFs,
youtube thumbnails, x photos — to `media/<source>/<id-slug>-<n><ext>`
(network), recording each file's root-relative path on the item's media
ref and re-rendering its scroll so frontmatter points at the local file
(`test_media_batch_captures_pending_refs_and_rerenders`). Captured refs
are never re-downloaded by a batch run, and a deleted file is healed on
the next one (`test_media_batch_is_idempotent`,
`tests/test_media.py`). With an id: explicit re-capture, overwriting the
recorded paths (`test_media_by_id_recaptures_explicitly`); an item with
nothing to capture is a *skip*, not a failure
(`test_media_by_id_without_refs_reports_skip`). One failed download
fails its item but never the batch, and refs captured before the failure
keep their files (`test_media_continues_past_failures_and_exits_nonzero`).

| Key | Meaning |
| --- | --- |
| `captured` / `skipped` / `failed` | batch counts (per item) |
| `results[]` | per-item `{id, status, ...}`; `files` lists captured root-relative paths, `error` is the first failed ref's message, `reason` explains a skip |

```console
$ scrolls media                       # one fetched arXiv item is pending
{"captured": 1, "skipped": 0, "failed": 0, "results": [{"id": "arxiv:1706.03762", "status": "captured", "files": ["media/arxiv/1706-03762-1.pdf"]}]}
[exit 0]

$ scrolls media                       # idempotent: nothing pending now
{"captured": 0, "skipped": 0, "failed": 0, "results": []}
[exit 0]

$ scrolls media x:1111                # this bookmark has no media refs
{"captured": 0, "skipped": 1, "failed": 0, "results": [{"id": "x:1111", "status": "skipped", "reason": "no media references to capture"}]}
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
[{"id": "x:1111", "source": "x", "url": "https://x.com/karpathy/status/1111", "title": "@karpathy: SQLite FTS5 is criminally underrated for local search.", "stage": "fetched", "saved_at": "2026-06-04T04:27:46+00:00"}, {"id": "x:2222", ...}, {"id": "arxiv:1706.03762", ..., "title": null, "stage": "detected", ...}, {"id": "x:3333", ...}]
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
{"id": "x:1111", "source": "x", "url": "https://x.com/karpathy/status/1111", "saved_at": "2026-06-04T04:27:46+00:00", "source_id": "1111", "canonical_url": null, "title": "@karpathy: SQLite FTS5 is criminally underrated for local search.", "author": "Andrej Karpathy (@karpathy)", "published_at": "2026-06-01T15:34:00+00:00", "raw_text": "{\"id\": \"1111\", \"tweetId\": \"1111\", …}", "extracted_text": "SQLite FTS5 is criminally underrated for local search.", "summary": null, "category": "technique", "domain": "databases", "tags": [], "concepts": [], "links": ["https://sqlite.org/fts5.html"], "media": [], "content_hash": "sha256:da27b0…", "markdown_path": "scrolls/x/karpathy-sqlite-fts5-is-criminally-underrated-for-local-search.md", "provenance": {"adapter": "fieldtheory-import", "fetched_at": "2026-06-12T20:29:15+00:00", "extraction_method": "fieldtheory:bookmarks.jsonl"}, "stage": "rendered"}
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

## Agent protocol server

### `scrolls mcp`

The one command that blocks and prints nothing: serve the library to
MCP clients over stdio until the client disconnects (ADR 0014,
`tests/test_mcp.py`). Connect a client to the command itself, e.g.:

```bash
claude mcp add scrolls -- uv run scrolls mcp
```

The tools wrap the same engines as the CLI commands
(`test_server_exposes_exactly_the_documented_tools`):

| Tool | CLI equivalent | Returns |
| --- | --- | --- |
| `get_context_bundle(query, limit=8)` | `scrolls context` | Markdown bundle |
| `search_scrolls(query, limit=20)` | `scrolls search` | hit list with snippets |
| `get_scroll(item_id)` | `scrolls show` | full item record |
| `get_related_scrolls(item_id, limit=10)` | `scrolls related` | hits with `reasons` |
| `get_concept_page(concept)` | reading `library/concepts/<slug>.md` | Markdown page |
| `list_sources()` | — | item counts per source |
| `ingest_url(url)` | `scrolls ingest` | the ingest payload, `error` key included (`test_ingest_url_without_adapter_reports_error_as_data`) |
| `follow_feed(url)` | `scrolls follow <url>` | the subscription plus `created` (ADR 0020) |
| `unfollow_feed(ref)` | `scrolls unfollow <id>` | `{id, removed}`; accepts id or feed URL |
| `list_feed_subscriptions()` | `scrolls follow` | subscriptions with sync state |
| `sync_feeds(subscription_id=None)` | `scrolls sync [id]` | the sync batch payload; per-feed failures are `failed` results, not tool errors (`test_sync_feeds_registers_entries_then_reports_unchanged`) |

Read tools follow the CLI conventions: an empty or uninitialized
library yields empty results (`test_search_scrolls_before_init_returns_empty`),
unknown ids are tool errors (`test_get_scroll_unknown_id_raises`).

## Reproducing these examples

Everything above except the three marked network calls (`ingest` of a
Wikipedia page, `fetch arxiv:1706.03762`, and the `scrolls media` run
that downloads its PDF) runs fully offline — the feed examples talk
only to a local server. Scratch setup:

```bash
DEMO=$(mktemp -d)
export SCROLLS_HOME="$DEMO/home"

# a local feed for the follow/sync examples (any RSS/Atom URL works the same)
mkdir "$DEMO/site"
cat > "$DEMO/site/feed.xml" <<'EOF'
<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Demo Weblog</title>
    <link>http://localhost:8943/</link>
    <item>
      <title>Post one</title>
      <link>http://localhost:8943/2026/post-one/</link>
    </item>
    <item>
      <title>Post two</title>
      <link>http://localhost:8943/2026/post-two/</link>
    </item>
  </channel>
</rss>
EOF
(cd "$DEMO/site" && python3 -m http.server 8943 &)

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
scrolls add https://x.com/karpathy/status/3333
scrolls ingest https://x.com/karpathy/status/3333  # no adapter: exit 1
scrolls fetch                                      # skips the x item
scrolls fetch x:3333                               # by-id: fails, exit 1
scrolls import fieldtheory --root "$DEMO/fieldtheory"
scrolls import fieldtheory --root "$DEMO/fieldtheory"   # idempotent
scrolls add https://arxiv.org/abs/1706.03762
scrolls list
scrolls ingest https://en.wikipedia.org/wiki/SQLite  # network
scrolls classify
scrolls classify wikipedia:en:SQLite --engine llm  # without a key: exit 1
scrolls md
scrolls fetch arxiv:1706.03762                     # network
scrolls media                                      # network: downloads the PDF
scrolls media                                      # idempotent, offline
scrolls media x:1111                               # skip: no media refs
scrolls search "sqlite fts5"
scrolls show x:1111
scrolls related x:2222
scrolls kb
scrolls context "local search"
scrolls agent install
scrolls follow http://localhost:8943/feed.xml     # local server only
scrolls follow http://localhost:8943/missing.xml  # 404: exit 1
scrolls follow                                    # list subscriptions
scrolls sync                                      # 2 new items
scrolls sync                                      # 304: unchanged (http.server honors If-Modified-Since)
touch "$DEMO/site/feed.xml"                       # new Last-Modified
scrolls sync                                      # full response again: 2 known
scrolls unfollow http://localhost:8943/feed.xml
scrolls unfollow ea77c1d5239e                     # already gone: exit 1
scrolls set x:1111 tags=sqlite,fts "concepts=full-text search"
scrolls set x:1111 usefulness=high                # unknown field: exit 1
```

(Stop the feed server with `kill %1` when done.)

The walkthrough exercises the dedupe (`x:` ids from the import collide
with `scrolls add` of the same tweet URL on purpose), the title-pattern
classify rule (`x:2222`'s "a guide to" → `tutorial`), and the
link-resolution path of `related` (`x:2222` → `arxiv:1706.03762`) — the
same behaviors the test suite locks.
