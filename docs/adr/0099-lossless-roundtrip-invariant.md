# 0099: The lossless round-trip is a verified invariant, not a docstring claim

Date: 2026-06-15

Status: accepted

## Context

The custody vision (`docs/custody-vision.md`) makes "take it with me" a
load-bearing promise, not a convenience:

> **The library is a way-station, not a sink.** Custody without exit is
> hostage-taking. Every artifact round-trips out losslessly (`export items`
> JSONL is the model-complete backup) … Idempotent import/export is
> load-bearing infrastructure, not a feature bolt-on.

Its capability 4 names the exact obligation this record discharges:

> **Lossless round-trip as a guarantee, not a command.** Treat `export items`
> ↔ `import items` as a tested *invariant* (export→import→export is byte-stable
> for the model-complete fields), and make "rebuild every derived view from
> raw" (`doctor --fix` + `kb`) a dogfood-verified path.

ADR 0082 built the lossless JSONL export/import and *asserted* the rebuild
contract in prose: `items_export.py` says the derived artifacts — "the Markdown
scrolls, captured media, the compiled `library/` — rebuild from those rows:
`scrolls doctor --fix` rewrites any missing scroll file and the FTS index, and
`scrolls kb` recompiles the library." But that claim was tested only at the
module level (`dump_items_export` → `load_items_export` returns equal items). The
**end-to-end** path — export a real library, throw it away, and reconstruct it
from the JSONL using only the documented commands — was never exercised. Per the
vision's eighth principle, *"integrity is verified, not asserted … every custody
claim must be backed by a fixture-driven test or concrete command output.
'Self-healing' that isn't continuously proven is just hope."* This slice turns
the prose into a continuously-run proof.

## Decision

**Treat the export→rebuild round-trip as a verified custody invariant**, locked
by `tests/test_roundtrip.py`. The invariant is exercised the way an agent would
run it — through the real CLI (`main([...])`), against a real multi-source
library — not through internal helpers.

**The rebuild contract.** Starting from a JSONL backup and an empty library, the
documented sequence reconstructs the library:

```bash
scrolls import items backup.jsonl   # canonical store + FTS (the insert trigger) restored
scrolls doctor --fix                # rewrites every missing scroll file from the rows
scrolls kb                          # recompiles library/ from the rows
```

`import items` restores the canonical `items` rows (`INSERT OR IGNORE`) and, via
the FTS insert trigger, the full-text index in the same step — so search works
*before* `doctor --fix` even runs. `doctor --fix` rewrites the rendered scroll
files (which a JSONL backup does not carry — they are a derived view) from the
stored rows. `kb` recompiles `library/`. Both derived views are functions of the
canonical rows alone.

**What round-trips losslessly (proven byte-stable):**

1. **The canonical store** — `list_items` after the rebuild equals the original,
   field-for-field (`item_to_dict` equality).
2. **The re-export JSONL itself** — export→import→export reproduces the backup
   byte-for-byte. `list_items`' `ORDER BY saved_at, id` is total and stable, and
   `item_to_dict` emits fields in dataclass order, so the cycle is deterministic.
3. **The rendered scrolls** — every scroll file reappears byte-identical, because
   `write_scroll` is a pure function of the item and **honors the stored
   `markdown_path`** rather than re-slugging. This is what makes slug collisions
   and post-render title changes survive: the path travels in the backup, so two
   items whose titles slug identically rebuild onto their original distinct paths
   instead of collapsing onto one (`test_slug_collision_survives_the_round_trip`).
4. **The compiled `library/` pages** — the deterministic KB engine iterates the
   rows in the same stable order, so every page rebuilds byte-identical.
5. **Full-text search** — the rebuilt FTS returns the same items for the same
   query.

And the rebuilt library **passes its own custody audit**: `scrolls doctor`
reports `issues: 0`, a custody `score` of 100, and `fts.in_sync: true`.

**The one honest gap: media blobs.** A JSONL backup carries media *references*
(type/url/path in the item's `media` field) but not the captured *bytes*. On
rebuild the scroll's media frontmatter round-trips intact, but the blob is
absent, and `doctor` reports it as `missing_media` rather than pretending the
library still holds it — so `doctor --fix` honestly exits **1** (one issue it
cannot repair offline; `scrolls media` re-downloads the blob). This is the
"graceful degradation" the vision names, made visible:
`test_media_blob_degrades_honestly_on_rebuild` pins it.

## Consequences

- The custody promise "you can always walk away with everything, and put it
  back" is no longer prose — it is a test that fails the moment any of
  `write_scroll`, the KB compiler, the export serializer, or `list_items`
  ordering becomes non-deterministic or lossy. The byte-stable assertions are
  strict on purpose: a round-trip that is "equal except for whitespace" is a
  regression worth catching.
- The rebuild **sequence is now stable, documented vocabulary** (`import` →
  `doctor --fix` → `kb`), which the future shareable-bundles capability
  (custody-vision capability 7) builds on: a portable bundle is this same
  round-trip scoped to a slice, and its importer can rely on the same rebuild
  path.
- The media gap is recorded as a *known, honest* boundary, not a silent loss.
  Any future "bundle" that wants to be blob-complete must carry the media
  alongside the JSONL; the item export deliberately does not, and now says so
  with a test rather than a docstring caveat.
- No production code changed: the invariant **held on first run**, which is
  itself the finding — the determinism ADR 0082 (export), ADR 0005 (KB), and
  the render path were each built to assume is real, and is now continuously
  proven together. The value is the regression wall, not a fix.
- Verified offline: `tests/test_roundtrip.py` — the byte-identical
  export/rebuild across rows, re-export, scrolls, `library/`, and search; the
  rebuilt library passing its own custody audit; idempotent re-import
  (`INSERT OR IGNORE` skips on the second pass); honest media degradation; and
  the slug-collision path-stability property.

## Deferred

- **Blob-complete bundles.** Carrying media bytes (and so closing the one gap)
  belongs to the shareable-bundle slice (capability 7), which needs a container
  format decision (tar/zip vs. a directory) the JSONL stream deliberately
  avoids.
- **A single `rebuild` command.** The three-command sequence is the contract;
  whether to wrap it as one `scrolls rebuild` is a UI convenience left until a
  workflow needs it, not a custody question.
- **Round-trip as a dogfood eval.** Wiring this test into a recurring
  "prove custody end-to-end" eval target (custody-vision capability 8) is the
  natural next step once an eval harness exists to host it.
