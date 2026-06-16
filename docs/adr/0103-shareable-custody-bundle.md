# 0103: The shareable custody bundle — a scoped, self-describing briefing with a lossless re-import block

Date: 2026-06-16

Status: accepted

## Context

Scrolls already has a lossless whole-library round-trip: `scrolls export items`
/ `import items` (ADR 0082) serialize every `ScrollItem` field to JSON Lines and
restore them byte-for-byte, the contract the lossless-round-trip invariant (ADR
0099) guards. It is a *backup/migration* format — machine-oriented JSONL,
whole-library or coarsely faceted, streamed to stdout, with no human-readable
briefing.

Scrolls also has `scrolls context` (IDEAS.md §11): a scoped, readable Markdown
briefing on a topic — best matches, capped excerpts, source links — built to
drop straight into a model's context. But it is *lossy*: it carries excerpts,
not raw text; it surfaces no per-item provenance or fidelity; and it cannot be
re-imported.

The custody-vision (§3.7) and the obsidian-second-brain "vendor-neutral export
bundle" adaptation (ADR 0102, `docs/agents/obsidian-second-brain-inspiration.md`)
call for the artifact that is *both*: a scoped, self-contained briefing an agent
can hand to a person or another library, that reads as a topic briefing carrying
provenance + fidelity per item **and** re-imports losslessly. This is PRD
capability 9 and MVP slice M4 — the "take it with me" half of the dogfood flow
(M5): *hold a topic → prove custody → detect loss → take it with me*.

The gap is narrow and specific: neither existing surface is both readable and
re-importable. The decision is what envelope closes it without forking the
lossless core or the scope vocabulary.

## Decision

**Add `scrolls export bundle <query>` / `scrolls import bundle <path>`: one
self-contained Markdown file that is a readable briefing *and* a lossless
re-import unit.** The bundle reuses, rather than re-invents, the three pieces
that already exist.

1. **One Markdown file, two layers.** A *briefing body* (human/agent-readable):
   title + scope note, then one entry per in-scope scroll naming its id, source,
   custody **fidelity** tier (ADR 0100, via `get_fidelity`), capture timestamp,
   link, content hash, and a capped excerpt. Below it, a *custody block*: the
   canonical rows as JSON Lines (the same `item_to_dict` output
   `dump_items_export` writes, ADR 0082) inside a ` ```jsonl ` code fence,
   wrapped in the ADR 0102 `@generated`…`@end` sentinel. Markdown because it is
   the vendor-neutral, human-and-agent format Scrolls already emits for
   `context` and `library/`, and it renders anywhere. (HTML is a later view of
   the same model; deferred.)

2. **The lossless core is inherited, not rebuilt.** The custody block's JSONL is
   byte-identical to `export items`, so the bundle's round-trip losslessness is
   the property ADR 0082/0099 already test. `import bundle` parses the block
   exactly as `import items` parses a JSONL file (`item_from_dict`, the same
   required identity fields `id`/`source`/`url`/`saved_at`, unknown keys
   tolerated for forward compatibility) and inserts rows with `INSERT OR IGNORE`
   — so re-import never overwrites a scroll the target library already holds
   (custody-safe), and derived artifacts (scrolls, media, the compiled
   `library/`) rebuild from the rows via `doctor --fix` / `kb`, the same way
   `import items` relies on.

3. **The sentinel makes the block machine-locatable and the briefing
   annotatable.** Wrapping the custody block in the ADR 0102 fence means a
   re-export replaces only the fenced rows while any hand annotation in the
   briefing body around it survives — the refresh-safe contract applied to a
   shareable artifact. `parse_bundle` finds the block by `generated_body`, so it
   is robust to edits above/below it.

4. **Scope is the read-surface vocabulary, and complete.** `export bundle` takes
   a query + the same five facets `context`/`search` use
   (`--source`/`--category`/`--stage`/`--tag`/`--concept`, via `search_items`),
   so a bundle covers exactly what a `context`/`search` of the same scope would.
   But it carries **every** matching scroll, not a top-N: `count_matches` is the
   limit. A custody artifact must be complete about its scope — a silently
   truncated bundle would violate the M2 completeness contract the moment it
   were re-imported as "the whole topic." A whole-library or query-less backup
   stays the job of `export items`; the bundle is the *topic-scoped, readable,
   shareable* complement.

5. **Placement mirrors the existing round-trip pair.** `export bundle` joins
   `export {opml,bookmarks,items}`; `import bundle` joins the importers. The
   bundle Markdown is the artifact, so `export bundle` prints raw on stdout (the
   `context`/`export items` exception to the JSON-on-stdout rule); `import
   bundle` reports `{imported, skipped, items}` like `import items`.

## Consequences

- New module `src/scrolls/bundle.py` (`build_bundle`, `parse_bundle`,
  `BundleError`) composing existing primitives: `search_items`/`count_matches`
  (scope), `get_fidelity` (tier), `dump_items_export`/`item_from_dict` (the
  lossless rows, ADR 0082), and `generated.fence`/`generated_body` (the sentinel,
  ADR 0102). The CLI wires `export bundle`/`import bundle`. No new storage and no
  new lossless mapping — the bundle is an *envelope*.
- Relationship to ADR 0082 is now explicit and non-overlapping: `export items`
  is the machine, whole-library, streamed *backup*; the bundle is the scoped,
  readable, shareable *briefing*. Same lossless rows, different envelope and
  audience.
- The round-trip is verified end to end, not asserted: `tests/test_bundle.py`
  exports a topic from one library and rebuilds it in a fresh, empty one
  (`test_export_import_round_trips_across_a_fresh_library`), proves the briefing
  excerpt is capped while the block keeps the full raw text
  (`test_bundle_carries_the_raw_body_even_when_the_excerpt_is_capped`), and pins
  completeness, scope filtering, custody-safe re-import, and the corrupt-block
  error path.
- Refresh-safe by construction: a bundle's custody block is sentinel-fenced, so
  the briefing body is hand-annotatable and a re-export clobbers only the rows
  (ADR 0102).
- **Deferred** (noted, not built): an HTML render of the same model; an MCP
  `export_bundle` tool; and a checksum/signature over the bundle itself (custody
  provenance *of the bundle*, distinct from the items' provenance it already
  carries). None blocks M4's done-criterion (a verified lossless round-trip of a
  self-describing, scoped briefing), and each is additive.
- This completes MVP slice M4. It unblocks M5 (the dogfood flow), whose final
  step — "take it with me" — is now `export bundle` → `import bundle`.
