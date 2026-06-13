# Scrolls CLI Reference

The output contract for every command: arguments, JSON keys, exit codes,
and error envelopes. This is the reference for agents (and contributors)
consuming `scrolls` output programmatically; `README.md` tells the same
story in prose, and `docs/architecture.md` explains the system behind it.

Every example below is real output captured from `scrolls 0.1.0`
(schema version 6) on this branch — see
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
  `media`, `rm`, `sync`, `import fieldtheory`, and `kb --engine llm`
  process every item (for `rm`, every ref; for `sync`, every
  subscription; for `kb --engine llm`, every qualifying concept), never
  abort mid-batch, and exit 1 if **any** item *failed* — skipped items
  do not fail the run
  (`test_fetch_continues_past_failures_and_exits_nonzero`,
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
- **The saved URL works wherever an item id does** (ADR 0028): every
  command that takes an item id (`show`, `fetch`, `classify`, `md`,
  `media`, `set`, `related`, `rm`) also accepts the item's URL, in any
  tracking-decorated spelling — resolved to the id `add` would mint
  (`tests/test_pipeline.py`, `test_show_accepts_item_url`,
  `test_fetch_accepts_item_url`). A URL that matches nothing reports
  the id it resolved to
  (`test_show_unknown_url_reports_the_resolved_id`). Subscription ids
  (`sync`, `unfollow`) are a separate namespace; `unfollow` accepts
  feed URLs already.
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
`schema_version` is `null` until `init` (current version: 6,
`src/scrolls/db.py`). The counts answer "what should run next":
`by_stage.detected` items await `fetch`, `by_stage.fetched` await `md`,
and `unclassified` is the pool a batch `classify` would pick up
(`test_status_counts_items_and_subscriptions`,
`tests/test_items.py`). An uninitialized library reports zero-filled
counts, so the payload shape never varies.

| Key | Meaning |
| --- | --- |
| `initialized` / `schema_version` | `false`/`null` until `init` |
| `root` | library root in use |
| `items` | `total`, `by_stage` (always all three stages), `by_source` (present sources only), `unclassified` |
| `subscriptions` | followed feeds (`scrolls follow`) |

```console
$ scrolls status        # before init
{"initialized": false, "root": "/tmp/scrolls-demo.BgrqMO/home-empty", "schema_version": null, "items": {"total": 0, "by_stage": {"detected": 0, "fetched": 0, "rendered": 0}, "by_source": {}, "unclassified": 0}, "subscriptions": 0}
[exit 0]

$ scrolls status        # after the imports and adds below
{"initialized": true, "root": "/tmp/scrolls-demo.BgrqMO/home", "schema_version": 6, "items": {"total": 4, "by_stage": {"detected": 2, "fetched": 2, "rendered": 0}, "by_source": {"arxiv": 1, "x": 3}, "unclassified": 3}, "subscriptions": 0}
[exit 0]
```

*(x:1111 is already classified here — the Field Theory import's
frontmatter join carries `category` over — which is why `unclassified`
is 3 of 4)*

### `scrolls paths`

Print every library path (`test_paths_prints_layout_json`). `items` is a
reserved directory, currently unused; `media` holds files downloaded by
`scrolls media`.

```console
$ scrolls paths
{"root": "/tmp/scrolls-demo.BgrqMO/home", "items": "/tmp/scrolls-demo.BgrqMO/home/items", "scrolls": "/tmp/scrolls-demo.BgrqMO/home/scrolls", "library": "/tmp/scrolls-demo.BgrqMO/home/library", "media": "/tmp/scrolls-demo.BgrqMO/home/media", "agents": "/tmp/scrolls-demo.BgrqMO/home/agents", "db": "/tmp/scrolls-demo.BgrqMO/home/db.sqlite", "config": "/tmp/scrolls-demo.BgrqMO/home/config.toml"}
[exit 0]
```

### `scrolls doctor [--fix]`

Check integrity between the SQLite index and the file tree, offline
(ADR 0026; all cited tests in `tests/test_doctor.py`). Five checks,
each a top-level key:

| Key | Finding | With `--fix` |
| --- | --- | --- |
| `duplicates` | url-hash items (no source-local id) whose URLs normalize to the same resource — the pre-normalization legacy ADR 0023 left in place | merged (`test_fix_merges_duplicates_into_canonical_id`) |
| `missing_scrolls` | items whose recorded scroll file is gone | rewritten from the index (`test_fix_rewrites_missing_scroll_from_the_index`) |
| `missing_media` | captured media files gone from disk | report-only; `scrolls media` re-downloads (`test_fix_leaves_missing_media_to_scrolls_media`) |
| `orphan_scrolls` | `.md` files under `scrolls/` no item owns | report-only; never deleted (`test_fix_never_deletes_orphan_scrolls`) |
| `fts` | search index out of sync with the items table | rebuilt (`test_fix_rebuilds_drifted_fts`) |

A duplicate merge keeps the most advanced member's content under the id
a clean re-add of the URL would mint (so the duplicate cannot recur —
`test_merged_duplicates_do_not_recur`), keeps the earliest `saved_at`,
fills `category`/`domain` from any member, unions `tags`/`concepts`,
deletes the losing rows and scroll files, and re-renders the survivor's
scroll (`test_fix_merges_classification_across_members`,
`test_fix_deletes_the_losing_duplicates_scroll_file`).

Exit semantics differ from the batch commands: exit 0 only when the
library ends fully consistent — already healthy, or every finding
repaired (`issues == fixed`); any drift left behind exits 1, including
the report-only kinds
(`test_doctor_fix_exits_one_when_unfixable_drift_remains`). Without
`--fix` nothing is mutated (`test_doctor_reports_issues_and_exits_one`),
and doctor never creates a library
(`test_doctor_before_init_exits_zero`). A repair the filesystem refuses
marks its finding `failed` (with `error`) and never aborts the rest; a
failed merge mutates nothing
(`test_fix_reports_a_scroll_it_cannot_rewrite`,
`test_fix_reports_a_merge_it_cannot_complete`).

```console
$ scrolls doctor        # healthy library
{"issues": 0, "fixed": 0, "duplicates": [], "missing_scrolls": [], "missing_media": [], "orphan_scrolls": [], "fts": {"in_sync": true, "status": "ok"}}
[exit 0]

$ scrolls doctor        # a planted pre-ADR-0023 duplicate + a deleted scroll file
{"issues": 2, "fixed": 0, "duplicates": [{"source": "web", "url": "https://blog.example/post", "ids": ["web:5e1a18c8f0f3", "web:af2e70e87b6d"], "status": "found"}], "missing_scrolls": [{"id": "x:1111", "path": "scrolls/x/karpathy-sqlite-fts5-is-criminally-underrated-for-local-search.md", "status": "found"}], "missing_media": [], "orphan_scrolls": [], "fts": {"in_sync": true, "status": "ok"}}
[exit 1]

$ scrolls doctor --fix
{"issues": 2, "fixed": 2, "duplicates": [{"source": "web", "url": "https://blog.example/post", "ids": ["web:5e1a18c8f0f3", "web:af2e70e87b6d"], "status": "merged", "merged_id": "web:af2e70e87b6d"}], "missing_scrolls": [{"id": "x:1111", "path": "scrolls/x/karpathy-sqlite-fts5-is-criminally-underrated-for-local-search.md", "status": "rewritten"}], "missing_media": [], "orphan_scrolls": [], "fts": {"in_sync": true, "status": "ok"}}
[exit 0]
```

`fts.status` is `ok`, `found`, `rebuilt`, `unsupported` (SQLite older
than 3.42 cannot verify the index against the table —
`test_fts_check_degrades_on_old_sqlite`), or `skipped` (no database).

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

### `scrolls import bookmarks <path>`

Bulk-import a browser bookmarks export (ADR 0030). `path` is the
`bookmarks.html` every major browser emits (Chrome, Firefox, Safari,
Edge — the Netscape bookmark file format, also spoken by Pinboard-style
services). A missing file, or one without the format's DOCTYPE marker,
is an error envelope on stderr
(`test_import_bookmarks_missing_file_is_an_error` in
`tests/test_cli.py`; `test_non_bookmark_html_raises` in
`tests/test_bookmarks.py`).

Bookmarks are a spine-only archive like Takeout — URL, anchor text,
`ADD_DATE`, folder placement — so items enter at stage `detected` and
`scrolls fetch` enriches them. Unlike Takeout the spine is
heterogeneous: every http(s) URL routes through the same source
detection and URL normalization as `scrolls add`, so a bookmarked
video becomes a `youtube` item, a repo a `github` item, a tweet an
`x` item, and they all dedupe against items the library already has
(`test_imports_bookmarks_as_detected_items`,
`test_x_bookmarks_register_without_an_adapter`,
`test_import_bookmarks_never_overwrites_existing_item`).

Folder ancestry becomes `tags` — the user's own curation, free-form
like `scrolls set`; root containers ("Bookmarks bar", "Other
Bookmarks", …) are browser furniture and excluded, and Firefox's
`TAGS` attribute merges in
(`test_folder_ancestry_becomes_tags`,
`test_root_container_folders_are_not_tags`,
`test_firefox_tags_attribute_merges_with_folder_tags`). The anchor
text seeds `title`, a `<DD>` note seeds `summary`, and `ADD_DATE`
(epoch seconds, or the milli/microsecond variants some exporters
write) becomes `saved_at` — when the page entered the user's life,
never `published_at` (`test_dd_description_seeds_summary`,
`test_millisecond_add_dates_are_normalized`).

Per-bookmark oddities never fail the run — exports accumulate
bookmarklets and smart folders — so the command exits 0 and counts
them instead:

| Key | Meaning |
| --- | --- |
| `imported` | new items inserted |
| `skipped` | already existed (id collision is the dedupe working) |
| `bookmarks` | total bookmark entries in the export |
| `repeats` | extra copies of an already-seen URL (earliest `ADD_DATE` wins `saved_at`; folder tags union) |
| `ignored.not_http` | non-http(s) bookmarks (`javascript:` bookmarklets, Firefox `place:` folders, `file:` links) |
| `ignored.no_url` | anchors without an href |

```console
$ scrolls import bookmarks /tmp/scrolls-demo.BgrqMO/bookmarks.html
{"imported": 2, "skipped": 0, "bookmarks": 4, "repeats": 1, "ignored": {"not_http": 1, "no_url": 0}}
[exit 0]

$ scrolls import bookmarks /tmp/scrolls-demo.BgrqMO/bookmarks.html
{"imported": 0, "skipped": 2, "bookmarks": 4, "repeats": 1, "ignored": {"not_http": 1, "no_url": 0}}
[exit 0]
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

### `scrolls import google-takeout <path>`

Bulk-import YouTube watch history from a Google Takeout export
(ADR 0029). `path` is the Takeout `.zip`, an extracted directory, or
`watch-history.json` itself — the direct file path is the escape hatch
for localized exports whose directory names are translated. The JSON
export format is required (Takeout's default HTML history is not
parsed); a missing or non-JSON export is an error envelope on stderr
(`test_import_google_takeout_missing_export_is_an_error`,
`tests/test_takeout.py`).

Unlike `import fieldtheory`, Takeout carries no content — only video
URL, title, channel, and watch time — so items enter at stage
`detected` and `scrolls fetch` enriches them through the youtube
adapter, exactly like feed-synced entries. The watch time becomes
`saved_at`; `published_at` stays unset because Takeout doesn't know it
(`test_import_google_takeout_end_to_end`). Existing items are never
overwritten (`test_import_google_takeout_is_idempotent`,
`test_import_google_takeout_never_overwrites_existing_item`).

Per-entry oddities never fail the run — every watch history contains
ads, deleted videos, and community-post visits, so the command exits 0
and counts them instead:

| Key | Meaning |
| --- | --- |
| `imported` | new items inserted |
| `skipped` | already existed (id collision is the dedupe working) |
| `events` | total watch events in the export |
| `repeats` | extra watches of an already-seen video (earliest watch wins `saved_at`) |
| `ignored.ads` | entries marked "From Google Ads" |
| `ignored.no_url` | entries with no URL (deleted/private videos) |
| `ignored.not_video` | YouTube URLs that aren't videos/playlists (posts, channel visits) |

```console
$ scrolls import google-takeout /tmp/scrolls-demo.BgrqMO/takeout.zip
{"imported": 1, "skipped": 0, "events": 4, "repeats": 1, "ignored": {"ads": 1, "no_url": 1, "not_video": 0}}
[exit 0]

$ scrolls import google-takeout /tmp/scrolls-demo.BgrqMO/takeout.zip
{"imported": 0, "skipped": 1, "events": 4, "repeats": 1, "ignored": {"ads": 1, "no_url": 1, "not_video": 0}}
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

### `scrolls fetch [id] [--limit N]`

No argument: run the source adapter for every item at stage `detected`
(network). Items whose source has no adapter yet are *skipped* (they stay
`detected` for a future scrolls) and do not fail the run
(`test_fetch_all_skips_sources_without_adapter`). With an id: refetch
that one item regardless of stage — and asking for an adapterless item
by id is an honest *failure*, not a skip
(`test_fetch_by_id_refetches_regardless_of_stage`,
`test_fetch_by_id_without_adapter_fails`).

`--limit N` paces a batch run: at most N fetches are attempted, oldest
saved first, and the next run resumes where this one stopped — the way
to enrich a large `import google-takeout` spine incrementally
(`test_fetch_limit_caps_attempts_and_resumes`). The limit counts fetch
*attempts* (fetched + failed), not adapterless skips: skipped items
stay `detected` at the front of the saved order, so counting them
would wedge every paced run on the same skips
(`test_fetch_limit_does_not_count_adapterless_skips`). Items beyond
the limit are not reported. Combining `--limit` with an explicit id is
an error (`test_fetch_limit_with_explicit_id_is_an_error`).

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

### `scrolls rm <id-or-url>...`

Remove items: the row, the rendered scroll, and captured media files —
the search index follows via the FTS delete trigger
(`test_removed_item_leaves_the_search_index`, `tests/test_remove.py`).
Each ref is an item id, or a URL resolved to the id `add` would mint —
normalization included, so any tracking-decorated spelling of the saved
URL is a valid handle (`test_rm_accepts_the_url_that_added_the_item`).
Files are deleted before the row, so an interrupted removal leaves a
re-runnable item, never orphan files
(`test_remove_rejects_paths_escaping_the_root` also locks the guard:
a recorded path escaping the library root fails its item before
anything is deleted). Batch semantics
(`test_rm_continues_past_failures_and_exits_nonzero`): per-ref results,
exit 1 if any ref failed.

Two things `rm` deliberately does not do (ADR 0027): KB pages
referencing the removed scroll stay until the next `scrolls kb`, and
there is no tombstone — an item still listed in a followed feed returns
on the next `sync`, so `unfollow` first when pruning a feed.

| Key | Meaning |
| --- | --- |
| `removed` / `failed` | batch counts (per ref) |
| `results[]` | per-ref `{ref, status, ...}`; on success `id`, `url` (the re-add receipt: `scrolls add <url>` re-registers the item), and `files` — deleted root-relative paths |

```console
$ scrolls rm x:3333                          # registered but never fetched
{"removed": 1, "failed": 0, "results": [{"ref": "x:3333", "id": "x:3333", "url": "https://x.com/karpathy/status/3333", "status": "removed", "files": []}]}
[exit 0]

$ scrolls rm https://x.com/simonw/status/2222     # by URL: files go too
{"removed": 1, "failed": 0, "results": [{"ref": "https://x.com/simonw/status/2222", "id": "x:2222", "url": "https://x.com/simonw/status/2222", "status": "removed", "files": ["scrolls/x/simonw-attention-is-all-you-need-still-holds-up-a-guide-to-reading-it-prope.md"]}]}
[exit 0]

$ scrolls rm x:2222 x:1111                   # x:2222 is already gone
{"removed": 1, "failed": 1, "results": [{"ref": "x:2222", "status": "failed", "error": "no such item: x:2222"}, {"ref": "x:1111", "id": "x:1111", "url": "https://x.com/karpathy/status/1111", "status": "removed", "files": ["scrolls/x/karpathy-sqlite-fts5-is-criminally-underrated-for-local-search.md"]}]}
[exit 1]
```

## Reading the library

### `scrolls list [--source S] [--stage S] [--category C]`

Every matching item as a summary array (full records: `scrolls show`).
An empty or uninitialized library prints `[]`
(`test_list_after_adds_prints_summaries`,
`test_list_before_init_prints_empty_array`). Summary keys: `id`,
`source`, `url`, `title`, `category`, `stage`, `saved_at`.

Filters combine with AND
(`test_list_filters_by_source_stage_and_category`): `--source` and
`--category` match exactly, `--stage` only accepts the three real
stages (a typo is a usage error, exit 2 —
`test_list_rejects_an_unknown_stage`), and `--category ""` selects
items *without* a category — the pool a batch `classify` would pick
up — mirroring `scrolls set`'s empty-clears convention.

```console
$ scrolls list
[{"id": "x:1111", "source": "x", "url": "https://x.com/karpathy/status/1111", "title": "@karpathy: SQLite FTS5 is criminally underrated for local search.", "category": "technique", "stage": "fetched", "saved_at": "2026-06-04T04:27:46+00:00"}, {"id": "x:2222", ...}, {"id": "arxiv:1706.03762", ..., "title": null, "stage": "detected", ...}, {"id": "x:3333", ...}]
[exit 0]

$ scrolls list --source x --category technique
[{"id": "x:1111", "source": "x", "url": "https://x.com/karpathy/status/1111", "title": "@karpathy: SQLite FTS5 is criminally underrated for local search.", "category": "technique", "stage": "fetched", "saved_at": "2026-06-04T04:27:46+00:00"}]
[exit 0]
```

*(in the first call, array entries after the first are elided here for
width — every entry has the same seven keys)*

### `scrolls show <id>`

One item in full: every `ScrollItem` field
(`docs/architecture.md` → "The data model"), with list fields always
present as JSON arrays (`test_show_prints_full_item_json`). Unset fields
are `null`, not omitted. The id may also be the item's URL — see
Conventions (`test_show_accepts_item_url`).

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

### `scrolls search <query> [--limit N] [--source S] [--category C] [--stage ST]`

FTS5 BM25 over title/summary/extracted text, title weighted highest
(`src/scrolls/search.py`, `tests/test_search.py`). Query tokens are
quoted and AND-ed, so arbitrary agent input never hits FTS5 syntax
errors. `score` is SQLite's `bm25()`: results are ordered best-first and
**more negative means a stronger match**. Default limit 20
(`test_search_respects_limit_flag`). No matches prints `[]`; a blank
query is an error (`test_search_blank_query_is_an_error`).

`--source`, `--category`, and `--stage` scope the ranked match
(`test_search_filters_by_source_and_category`, ADR 0058): they AND with
the FTS match and with each other and leave the BM25 order untouched.
`--source` and `--stage` match exactly (`--stage` choices:
`detected`/`fetched`/`rendered`); `--category` matches exactly too,
except an empty value (`--category ""`), which selects unclassified
items — the same convention `scrolls list`/`scrolls set` use. A facet
that excludes every hit prints `[]`, not an error.

Hit keys: `id`, `source`, `title`, `url`, `stage`, `score`, `snippet`
(matches bracketed, `…` for elided context).

```console
$ scrolls search "sqlite fts5"
[{"id": "x:1111", "source": "x", "title": "@karpathy: SQLite FTS5 is criminally underrated for local search.", "url": "https://x.com/karpathy/status/1111", "stage": "rendered", "score": -2.9315057596986334, "snippet": "@karpathy: [SQLite] [FTS5] is criminally underrated for local search."}]
[exit 0]

$ scrolls search "sqlite fts5" --source arxiv
[]
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

### `scrolls graph [--all]`

The whole-library link graph in one call (ADR 0044, `tests/test_graph.py`).
Where `related` scores *one* item's neighborhood, this resolves *every*
item's links into directed edges — `from → to` whenever a link inside one
saved item names another (a tweet citing a paper, a model's `arxiv:` tag,
a preprint's published DOI), with `via` the link that matched. Resolution
is the same two-sided, source-detecting match `related` uses (ADR 0023),
so the graph is exactly the connections `related` would find, materialized
at once. Nodes carry the `id`, `source`, `title`, `url`, `stage` shape
`related`/`search` hits use, sorted by id; edges sorted by `(from, to)`.

Nodes are the *connected* items by default — `--all` widens it to every
item, isolated ones included. `stats.items` is always the library total,
so `nodes`/`edges` read as connectivity against the whole. An empty or
uninitialized library is an empty graph, exit 0.

```console
$ scrolls graph
{"nodes": [{"id": "arxiv:1706.03762", "source": "arxiv", "title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762", "stage": "rendered"}, {"id": "x:2222", "source": "x", "title": "@karpathy: the attention paper still holds up", "url": "https://x.com/karpathy/status/2222", "stage": "rendered"}], "edges": [{"from": "x:2222", "to": "arxiv:1706.03762", "via": "https://arxiv.org/abs/1706.03762"}], "stats": {"items": 2, "nodes": 2, "edges": 1}}
[exit 0]
```

### `scrolls context <query> [--limit N]`

The Markdown exception: a compact context bundle — best matches,
capped excerpts, source links — that agents drop directly into context
(IDEAS.md §11, `tests/test_context.py`). Each excerpt carries the item
id, source, and scroll path for follow-up with `scrolls show` or a file
read. When the matches link to or from other saved scrolls, a
`## Connected scrolls` section (between Excerpts and Links) lists those
neighbors from the link graph (`scrolls graph`, ADR 0044/0047) — a match's
paper, repo, or dataset that keyword search would miss — each naming the
match and direction that pulled it in
(`test_context_surfaces_connected_scrolls`). It is omitted when there are
no such connections. Default limit 8. Errors are still JSON on stderr
(blank query, as with `search`).

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

### `scrolls kb [--engine ...]`

Rebuild the interlinked library pages under `library/` from scratch
(stale groups can't linger; other files there are untouched — ADR 0005,
`tests/test_kb.py`). Output is the compile summary. Concept pages lead
with a stored synthesized summary when the LLM concept engine has
written one — the default compile includes them without any model call
(`test_kb_concept_page_leads_with_stored_summary`,
`test_kb_llm_engine_synthesizes_then_compiles`).

| Key | Meaning |
| --- | --- |
| `items` | rendered scrolls included |
| `sources` / `categories` / `concepts` | group pages written per kind |
| `summaries` | concept pages that carried a stored synthesized summary |
| `pages` | total files written, including `index.md` |

`--engine llm` (engine `kb-llm-v1`, ADR 0025) first brings the summary
store up to date via the Anthropic API (network; needs
`ANTHROPIC_API_KEY`; model from `[classify] llm_model`, overridable via
`SCROLLS_LLM_MODEL` — `test_kb_llm_engine_uses_config_llm_model`), then
compiles. Only concepts with 2+ scrolls qualify, and generation is
incremental: a concept whose members haven't changed reports `current`
without a model call, so re-running on an unchanged library costs
nothing (`test_kb_llm_engine_rerun_is_free_when_nothing_changed`);
summaries whose concept no longer qualifies are `pruned`
(`test_generate_prunes_summaries_for_disqualified_concepts` in
`tests/test_kb_llm.py`). The payload adds `generated` / `current` /
`failed` / `pruned` and per-concept `results` ahead of the compile
summary. Per-concept API failures are reported and the compile still
runs, exit 1 (`test_kb_llm_engine_reports_failures_but_still_compiles`);
missing credentials abort before compiling with the standard error
envelope, keeping any summaries already saved
(`test_kb_llm_engine_without_credentials_aborts_before_compiling`).

`--batch` (ADR 0032) synthesizes every concept that needs (re)generation
in one Message Batches submission at half the per-token price, polling
until the batch ends — typically minutes — instead of one API call per
concept (`test_kb_llm_batch_flag_submits_one_batch`;
`test_batch_summarizes_multi_member_concepts_in_one_submission` in
`tests/test_kb_llm.py` for the engine). Eligibility, incremental skipping,
pruning, the result shape, and per-concept failure isolation are
identical to the per-call path — only the transport differs, and both
share one validation and save path. A concept whose batch request failed
is reported and the compile still runs
(`test_batch_isolates_per_concept_failures`); missing credentials still
abort before compiling
(`test_kb_llm_batch_without_credentials_aborts_before_compiling`). The
flag needs the llm engine (`test_kb_batch_flag_requires_the_llm_engine`)
and shares the Batches transport with `classify --engine llm --batch`
(`tests/test_classify_llm.py`).

```console
$ scrolls kb
{"items": 2, "sources": 1, "categories": 2, "concepts": 0, "summaries": 0, "pages": 4}
[exit 0]

$ scrolls kb --engine llm     # no 2-scroll concepts yet: a zero run, no key needed
{"generated": 0, "current": 0, "failed": 0, "pruned": 0, "results": [], "items": 2, "sources": 1, "categories": 2, "concepts": 0, "summaries": 0, "pages": 4}
[exit 0]

$ scrolls kb --engine llm     # with a 2-scroll concept but no credentials set
{"error": "llm engine needs Anthropic credentials: set ANTHROPIC_API_KEY (\"Could not resolve authentication method. Expected one of api_key, auth_token, or credentials to be set. Or for one of the `X-Api-Key` or `Authorization` headers to be explicitly omitted\")"}
[exit 1]

$ scrolls kb --batch          # the deterministic engine has nothing to batch
{"error": "--batch requires the llm engine (--engine llm)"}
[exit 1]
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
| `search_scrolls(query, limit=20, source=None, category=None, stage=None)` | `scrolls search` | hit list with snippets, optionally faceted |
| `get_scroll(item_id)` | `scrolls show` | full item record |
| `get_related_scrolls(item_id, limit=10)` | `scrolls related` | hits with `reasons` |
| `get_concept_page(concept)` | reading `library/concepts/<slug>.md` | Markdown page |
| `list_sources()` | — | item counts per source |
| `ingest_url(url)` | `scrolls ingest` | the ingest payload, `error` key included (`test_ingest_url_without_adapter_reports_error_as_data`) |
| `follow_feed(url)` | `scrolls follow <url>` | the subscription plus `created` (ADR 0020) |
| `unfollow_feed(ref)` | `scrolls unfollow <id>` | `{id, removed}`; accepts id or feed URL |
| `list_feed_subscriptions()` | `scrolls follow` | subscriptions with sync state |
| `sync_feeds(subscription_id=None)` | `scrolls sync [id]` | the sync batch payload; per-feed failures are `failed` results, not tool errors (`test_sync_feeds_registers_entries_then_reports_unchanged`) |
| `compile_library()` | `scrolls kb` | the compile summary; deterministic only — LLM summary generation stays a CLI step (`test_compile_library_builds_the_pages_get_concept_page_serves`) |

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

cat > "$DEMO/bookmarks.html" <<'EOF'
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 PERSONAL_TOOLBAR_FOLDER="true">Bookmarks bar</H3>
    <DL><p>
        <DT><H3>Databases</H3>
        <DL><p>
            <DT><A HREF="https://www.youtube.com/watch?v=fts5video01" ADD_DATE="1614556800">SQLite Internals: B-trees</A>
            <DT><A HREF="https://example.com/sqlite-article?utm_source=share" ADD_DATE="1620000000">SQLite &amp; FTS Internals</A>
            <DD>Why SQLite's full-text search is enough.
        </DL><p>
        <DT><A HREF="javascript:void(0)" ADD_DATE="1610000000">Bookmarklet</A>
    </DL><p>
    <DT><H3>Reading</H3>
    <DL><p>
        <DT><A HREF="https://example.com/sqlite-article" ADD_DATE="1700000000">SQLite article again</A>
    </DL><p>
</DL><p>
EOF

python3 - "$DEMO" <<'EOF'
import json, sys, zipfile
from pathlib import Path
entries = [
    {"header": "YouTube", "title": "Watched How SQLite FTS Works",
     "titleUrl": "https://www.youtube.com/watch?v=abc123xyz00",
     "subtitles": [{"name": "Some Channel"}],
     "time": "2025-03-01T09:00:00.000Z"},
    {"header": "YouTube", "title": "Watched Buy Our Thing",
     "titleUrl": "https://www.youtube.com/watch?v=advideo0001",
     "details": [{"name": "From Google Ads"}],
     "time": "2025-01-02T00:00:00.000Z"},
    {"header": "YouTube", "title": "Watched a video that has been removed",
     "time": "2025-01-03T00:00:00.000Z"},
    {"header": "YouTube", "title": "Watched How SQLite FTS Works",
     "titleUrl": "https://www.youtube.com/watch?v=abc123xyz00",
     "subtitles": [{"name": "Some Channel"}],
     "time": "2024-10-12T18:23:45.123Z"},
]
with zipfile.ZipFile(Path(sys.argv[1]) / "takeout.zip", "w") as zf:
    zf.writestr("Takeout/YouTube and YouTube Music/history/watch-history.json",
                json.dumps(entries))
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
scrolls import google-takeout "$DEMO/takeout.zip"
scrolls import google-takeout "$DEMO/takeout.zip"       # idempotent
scrolls import bookmarks "$DEMO/bookmarks.html"
scrolls import bookmarks "$DEMO/bookmarks.html"         # idempotent
scrolls add https://arxiv.org/abs/1706.03762
scrolls status                                    # populated counts now
scrolls list
scrolls list --source x --category technique      # filters AND together
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
scrolls kb --engine llm                            # no 2-scroll concepts yet: zero run
scrolls kb --batch                                 # deterministic engine: guard, exit 1
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
scrolls set x:2222 "concepts=full-text search"    # a 2-scroll concept now exists
scrolls kb --engine llm                           # without a key: exit 1
scrolls kb --engine llm --batch                   # batch transport, without a key: exit 1
scrolls doctor                                    # healthy: exit 0

# plant the legacy state doctor repairs: a pre-ADR-0023 junk-URL row
# (today's `add` normalizes, so only an old library can hold one) ...
python3 -c "
from scrolls.paths import get_paths
from scrolls.items import ScrollItem, insert_item, make_item_id
url = 'https://blog.example/post?utm_source=newsletter'
insert_item(get_paths().db_path, ScrollItem(id=make_item_id('web', None, url),
    source='web', url=url, saved_at='2026-06-01T00:00:00+00:00'))
"
scrolls add https://blog.example/post             # ... its clean twin ...
rm "$SCROLLS_HOME"/scrolls/x/karpathy-*.md        # ... and a lost scroll file
scrolls doctor                                    # 2 findings: exit 1
scrolls doctor --fix                              # merged + rewritten: exit 0
scrolls doctor                                    # healthy again
scrolls rm x:3333                                 # never fetched: row only
scrolls rm https://x.com/simonw/status/2222       # by URL; scroll file too
scrolls rm x:2222 x:1111                          # one already gone: exit 1
```

(Stop the feed server with `kill %1` when done.)

The walkthrough exercises the dedupe (`x:` ids from the import collide
with `scrolls add` of the same tweet URL on purpose), the title-pattern
classify rule (`x:2222`'s "a guide to" → `tutorial`), and the
link-resolution path of `related` (`x:2222` → `arxiv:1706.03762`) — the
same behaviors the test suite locks.
