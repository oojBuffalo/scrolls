# ADR 0027: `scrolls rm` — item removal, files first, row last

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

Items were create-only. Every command grows the library (`add`,
`ingest`, `import`, `sync`) or transforms what is there (`fetch`, `md`,
`classify`, `set`, `media`); `unfollow` removes subscriptions but not
the items they registered, and `doctor` merges duplicates but
deliberately deletes nothing it cannot prove redundant. A mistaken
`add`, or junk registered by a followed feed, had no way out short of
hand-editing SQLite and hand-deleting files — which desyncs the index
from the file tree, exactly the drift doctor exists to flag.

## Decision

1. **`scrolls rm <id-or-url>...`** removes items: the row, the rendered
   scroll at `markdown_path`, and captured media files (`path` on media
   refs). The engine lives in `src/scrolls/remove.py`; the CLI stays a
   thin `_cmd_rm`. The FTS delete trigger (schema v3) keeps search in
   sync with no extra work.
2. **The URL that saved an item removes it.** A ref containing `://` is
   resolved through the same normalize → detect → mint chain as
   `register_url` (ADR 0023 included), so any tracking-decorated
   spelling of the saved URL is a valid handle — mirroring `unfollow`'s
   id-or-URL contract. Anything else is taken as an id verbatim.
3. **Files first, row last.** SQLite is canonical (IDEAS.md §3): if a
   file deletion fails, the surviving row makes `rm` re-runnable,
   whereas deleting the row first could strand orphan files that
   doctor reports but refuses to delete. Files already gone are fine —
   the goal state is absence.
4. **Only paths scrolls wrote, only inside the root.** Every recorded
   path is validated against the library root *before* anything is
   deleted; one poisoned ref fails its item untouched rather than
   half-deleting it. `rm` deletes files based on stored strings, so it
   is the one command where this guard pays for itself.
5. **Batch semantics, batch payload.** Multiple refs, per-ref results,
   never abort mid-batch, exit 1 if any ref failed — the `fetch`/`md`/
   `media` contract. Results carry `ref` (the argument as given) plus
   `id`/`url`/`files` on success; the echoed `url` is the receipt, since
   `scrolls add <url>` re-registers the item and `fetch` re-fills it.
6. **What `rm` does *not* do.** KB pages referencing a removed scroll
   stay until the next `scrolls kb` (every other mutation behaves the
   same); concept summaries for dissolved concepts are pruned by the
   next `kb --engine llm` (ADR 0025). And `rm` keeps no tombstone: an
   item still listed in a followed feed returns on the next `sync`,
   because sync's `INSERT OR IGNORE` knows nothing of past deletions.
   Tombstones need schema and "deleted forever" semantics; deferred,
   like ADR 0023 deferred its migration, until it bites.
7. **Not exposed over MCP.** Removal is destructive; it stays a
   deliberate CLI action, consistent with doctor (ADR 0026) and with
   ADR 0025's rule that MCP tools never do consequential things
   implicitly.

## Consequences

- The item lifecycle closes: register → enrich → render → remove, all
  index-and-files consistent, so `scrolls doctor` stays green after a
  removal.
- Removal is honest deletion, not archival: nothing remembers the item
  existed. Re-add and re-fetch reconstruct it from the source, which is
  the local-first posture — the source of truth for unsaved content is
  the internet, not a trash can.
- The feed re-registration gap is documented behavior. Users pruning a
  noisy feed will likely want `unfollow` first; if rm-then-resync pain
  shows up in practice, a tombstone table is the named next step.
- `items.delete_item` exists now; future code that deletes rows any
  other way (bypassing the engine) would leave files behind — the
  module docstring says so.

## Proof

`src/scrolls/remove.py` and `items.delete_item`, tested in
`tests/test_remove.py` (resolution parity with `add`, file + row
deletion, missing-file tolerance, root-escape refusal validated before
any deletion, FTS sync) and `tests/test_cli.py` (payload contract,
URL handle, mixed-batch exit codes, uninitialized library); captured
CLI output in `docs/cli.md`. 552 passing.
