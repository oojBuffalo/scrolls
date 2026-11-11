# 0116: Validate custody boundaries before a v1 release

Date: 2026-10-28
Status: accepted

## Context

Release testing reproduced capture overwrites on repeated ingest/fetch,
malformed imports that made a library unreadable, archive restores targeting
the wrong item, and artifact paths capable of overwriting or removing files
they did not own. Existing tests did not cover these boundary failures.

## Decision

- **Preserve captures.** Any held raw text, extracted text, or content hash
  prevents another `fetch`. Repeated ingest rebuilds from the held record.
  `verify` records upstream drift; explicit acceptance archives the prior copy.
- **Validate imports before writes.** Known model field types, portable
  artifact paths, ledger statuses, and archive snapshot identities are checked
  by shared mappings used by JSONL and bundles. Unknown fields remain tolerated.
- **Constrain artifact operations.** Scrolls and media stay in their own
  subtrees, without symlink aliases. Filename collisions cannot overwrite
  another item's artifact; removal retains files another item references.
- **Audit the actual view.** Doctor compares scroll bytes with the current
  renderer's output from the held record. Missing and stale views are explicit
  findings; `--fix` regenerates them without changing captured content.
- **Keep annotations attached to their group.** KB group filenames retain
  existing identity across slug collisions and tombstones. Counts deduplicate
  a member whose multiple spellings map to the same group.
- **Reject invalid result caps.** CLI and MCP use the same nonnegative integer
  range, bounded by SQLite's signed integer range. Zero means zero rows.

## Custody and scope

This strengthens vision §2.2, §2.4, §2.5, and §2.6 without adding adapters or
changing the canonical schema. Valid model-complete exports still round-trip;
malformed records fail before import mutation. Generated annotations remain
protected by ADR 0102's sentinel fences. No source hash is presented as an
offline recomputation: the view comparison checks rendering consistency.

## Verification

Regression tests exercise the actual CLI import/adopt/restore workflows and
shared engines. See `tests/test_capture_safety.py`,
`tests/test_import_validation.py`, `tests/test_artifact_paths.py`,
`tests/test_doctor_scroll_refresh.py`, `tests/test_v1_limits.py`, and
`tests/test_v1_kb_identity.py`. Dated release evidence and remaining external
validation gaps live in `docs/agents/progress/261028/report.md`.
