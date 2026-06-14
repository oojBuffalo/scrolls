# 0082: `scrolls export items` / `import items` — the lossless JSONL round-trip

Date: 2026-06-13
Status: accepted

## Context

ADR 0077 (`export opml`) and ADR 0079 (`export bookmarks`) built the `export`
namespace and each, in its Consequences, deferred the same remaining piece: a
**lossless** item export. Both deferred it for the same stated reason — "no
single universal format; the durable form is the Markdown scrolls" (0077), "a
different shape with no external importer to round-trip against" (0079). The
reserved `items/` directory in the library layout was earmarked as "the raw
record export's eventual job."

Both prior exports are spine-or-subscription interchange to a format an
*external* tool reads: OPML feeds for any RSS reader, Netscape bookmarks for any
browser. That external target is exactly what forced them to be lossy — a
bookmark file holds only URL/title/date/tags, an OPML file only feeds — so the
extracted text, summary, links, media refs, provenance, content hash, and stage
that make up most of a `ScrollItem` had no place to go.

But a library has a second thing it needs that neither export provides: a way to
**back itself up, migrate to another machine, or merge into another library**
without loss. That is not interchange with an external tool — it is a
Scrolls→Scrolls round-trip — and the moment the importer is Scrolls itself, the
"no external format to round-trip against" objection dissolves: the format to
round-trip against is Scrolls' own `ScrollItem` model. The serialization already
exists in one direction (`items._to_row`/`asdict`, the JSON columns), the
deduplicating insert already exists (`insert_item`'s `INSERT OR IGNORE`, the
universal import contract every other import uses), and `markdown_path` is stored
*relative* to the library root (`render._new_relpath`), so it is portable across
machines unchanged.

## Decision

Add a fourth `export` member, `scrolls export items`, and its inverse
`scrolls import items <path>`, exchanging the library as **JSON Lines** — one
complete `ScrollItem` per line (`src/scrolls/items_export.py`, the ScrollItem↔dict
mapping in `src/scrolls/items.py`).

- **Lossless, every field.** Unlike the spine exports, this carries the whole
  item via `items.item_to_dict` (`asdict`): identity, content (`raw_text`,
  `extracted_text`, `summary`), classification, `links`, `media`, `provenance`,
  `content_hash`, `markdown_path`, and `stage`. The round-trip target is Scrolls'
  own model, so there is nothing to drop. `item_from_dict` reverses it, restoring
  the four JSON list fields as tuples (the dataclass shape) and **ignoring
  unknown keys**, so an export written by a newer schema still loads under an
  older reader — forward compatibility a single-machine backup format wants.
- **JSON Lines, on stdout.** One JSON object per line: streamable, robust to a
  truncated tail (a partial last line fails only itself), `jq`/`grep`-friendly,
  and the same shape Field Theory's raw cache uses (IDEAS.md §13). Keys emit in
  dataclass field order, so a line is a stable diff. The stream **is** the
  artifact, so it prints raw on stdout (the `context`/`export opml`/`export
  bookmarks` exception to the JSON-on-stdout rule): `scrolls export items >
  library.jsonl`. No path argument — the shell owns redirection, so no overwrite,
  permission, or path-validation surface, exactly as the other two exports
  decided. This **supersedes the reserved `items/` directory idea**: the export
  is a stdout artifact like its siblings, not a managed directory, so `items/`
  stays unused (kept reserved rather than removed, in case a future managed-export
  need appears).
- **Strict on malformed input, unlike the spine imports.** Bookmarks and Pocket
  ingest heterogeneous third-party files and so *count* per-entry oddities and
  continue (a bookmarklet, a blank row). A Scrolls export is internally
  consistent, and this is a **backup** format — silently dropping a record would
  lose data without telling anyone — so `load_items_export` raises
  `ItemsSourceError` naming the line for any malformed line: invalid JSON, a
  non-object, or a record missing a required identity field (`id`, `source`,
  `url`, `saved_at`). A corrupt backup fails loudly and locatably; the user trims
  the bad line and retries (import is idempotent). Blank lines are skipped
  (trailing-newline and hand-edit tolerance). A missing file is an error envelope,
  the import convention.
- **Import restores the index rows; derived artifacts rebuild from them.** The
  SQLite row is the canonical record (the two-store model: "scrolls can always be
  rebuilt from the index"). `import items` inserts rows with `INSERT OR IGNORE`
  (dedupe by id — never overwrites an existing or edited row, so a re-import or a
  resumed partial restore is cheap and safe). It does *not* write Markdown
  scrolls or capture media; those rebuild from the restored rows with `scrolls
  doctor --fix` (rewrites missing scroll files and the FTS index — ADR 0026) and
  `scrolls kb`. The FTS index needs no special handling: it is trigger-maintained
  on insert, so imported items are searchable immediately.
- **The same three scoping filters as `export bookmarks`.** `--source`,
  `--category` (empty selects unclassified), and `--tag`, passed straight through
  the shared `items.list_items` query (AND-combined, whole library by default —
  the backup case). `--stage`/`--concept` are left off for symmetry with
  `export bookmarks`, a one-line passthrough if a need appears.
- **Round-trip is the contract.** `dump_items_export` then `load_items_export`
  reproduces identical items, every field intact
  (`test_dump_then_load_is_a_lossless_round_trip` in `tests/test_items_export.py`);
  through the CLI, an export imported into a fresh library is a faithful restore
  and into the same library skips every item as already-present
  (`test_export_items_round_trips_through_import`,
  `test_import_items_is_idempotent` in `tests/test_cli.py`).

## Consequences

- A Scrolls library is now a thing you can back up, move between machines, or
  merge — losslessly — with two commands and a file. This is the lossless item
  export ADRs 0077 and 0079 named and deferred; it answers their "no external
  importer to round-trip against" by making **Scrolls itself the importer**, the
  one case where a lossless round-trip is well-defined.
- The `export` namespace now spans three fidelities for three audiences: feeds
  out for any reader (`opml`), a URL spine out for any browser (`bookmarks`), and
  the whole library out for Scrolls itself (`items`). The lossy spine exports and
  the lossless full export coexist by design — interchange wants the spine, backup
  wants everything.
- `items.item_to_dict`/`item_from_dict` now exist as the model's public JSON
  projection, available to any future surface that needs a portable item (a JSON
  output mode, an MCP resource, a sync protocol) without reaching into the
  dataclass or the row codec.
- The reserved `items/` directory's "raw record export" purpose is fulfilled by a
  stdout artifact rather than a managed directory, matching the other exports; the
  directory stays reserved and unused. `docs/architecture.md` and `README.md`
  are updated to say so.
- Not exposed over MCP, consistent with every other `import`/`export` pair —
  these are operator/backup actions, not agent-facing reads. No schema change, no
  version bump (a new command, not a new record shape).
- Deferred: capturing the derived artifacts (scrolls/media/library) inside the
  export so a restore needs no rebuild step — they are deterministically
  reconstructable from the rows, so bundling them would only bloat the backup;
  a `--stage`/`--concept` scope; and a gzip/compressed variant for very large
  libraries (JSONL compresses well externally — `scrolls export items | gzip`).
