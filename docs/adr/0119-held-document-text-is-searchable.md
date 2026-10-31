# 0119: Held document text is searchable

Date: 2026-10-29

Status: accepted

Settles issue #25 and the search deferral in
[0114](0114-captured-pdfs-are-read-into-the-scroll.md).

## Context

ADR 0114 reads a captured PDF into its media ref (`text`, `text_method`) and
renders it under `## Documents`, but the FTS index covered only `title`,
`summary` and `extracted_text`. So `search` and `context` answered "nothing
found" for words the library held in a document. That breaks the
completeness contract (MVP M2): an empty result must not imply that held text
was checked.

Two constraints shaped the fix:

- **The text is not `extracted_text`.** Every re-fetch rewrites
  `extracted_text`; the reading lives on the media ref so it survives one
  (ADR 0114). The index has to read it from there.
- **FTS5 reads its external content back.** `rebuild`, `integrity-check` and
  `snippet` query the content table by column. A view computing the text from
  the media JSON was tried and failed: FTS5 qualifies the view's names with
  `main.`, and `json_each` cannot be referenced that way.

## Decision

**A derived `items.document_text` column feeds a fourth FTS column.**

- **Derived on every write.** `items.document_text(media)` joins each ref's
  non-empty `text`, one per line, in ref order; unread (`text` absent) and
  unreadable (`text: null`) documents add nothing. `_to_row` sets it, so every
  write path (insert, update, replace, adopt) keeps it in step with the refs.
- **Never modelled, never exported.** It is not a `ScrollItem` field: `export
  items` and bundles never carry it, and an import recomputes it.
- **Migration 9** drops the 3-column index and its triggers, adds and
  backfills the column in SQL (an index-addressed `json_extract`, so a
  non-object ref cannot break it, deriving exactly what the Python write
  would), and rebuilds the index over four columns. A test pins the SQL
  backfill equal to the Python derivation.
- **Every command upgrades an older library first.** `db.upgrade_db` runs
  before dispatch: an older database is migrated, a current one is not
  written, and a newer or unreadable one is left for the command to report.
  Five write commands (`fetch`, `classify`, `md`, `media`, `set`) never
  called `init_db`; without this they would meet a missing column.
- **A body hit.** `document_text` weighs like `extracted_text` (BM25 1.0) and
  shares its `weak` band; `matched_fields` names it, and `--strength weak`
  selects by band rank rather than by field position, so it is included.

## Consequences

- **`search` and `context` find what a held PDF says**, and the hit says it
  landed in `document_text`. The MCP twins read the same index. A match
  found only there gets a `context` excerpt from the document, starting just
  before the match the index itself found (`search.document_passage`, so whole
  tokens and folded diacritics as `search` matched them) and marked "From a
  held document", since the item's own summary and body do not hold it.
- **Storage is unchanged in kind.** The external-content index stores no
  copy of the text; the one new column holds it once.
- **OCR stays deferred** (ADR 0114): a scanned PDF still adds nothing.

Tests: `tests/test_document_search.py`.
