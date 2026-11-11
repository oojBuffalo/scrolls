# ADR 0114: Captured PDFs are read into the scroll

Date: 2026-10-22

Status: accepted

Settles: issue #10. Closes the deferral in
[0112](0112-configurable-media-size-limits.md).

## Context

ADR 0112 kept documents uncapped by default, because a document is
"exactly the knowledge the library exists for". The live library holds
three PDFs (63 MB, ADR 0110's document class), one a 62.6 MB CIA report
attached to a Wikipedia article.

They were held but unread. `scrolls media` downloaded each file and
stopped, so the text never reached the scroll, the index row, or an agent.

The capability already existed. The `pdf` adapter (ADR 0013) and the
`arxiv` adapter (ADR 0010) read PDFs with pypdf through one seam,
`scrolls.sources.pdf.extract_text`. Only the media path never called it.

## Decision

1. **Read on capture, through the one seam.** `scrolls media` reads every
   PDF it holds with `extract_text`. A fresh download is read as it lands.
   A file already on disk that predates this is read from disk, never
   downloaded again. A ref is a PDF when it is typed `pdf` or its file name
   ends in `.pdf`.
2. **The text lives on the media ref.** `text` holds it and `text_method`
   names the extractor (`pypdf-<version>`), so the method is recorded like
   every other enrichment. It does not go into `extracted_text`: that is
   the adapter's output, and a re-fetch rightly replaces it.
3. **A re-fetch keeps the ref's capture state.** An adapter rebuilds media
   refs from the source every time, so `scrolls fetch` and `ingest` carry
   each ref's `path`, size decline (`oversize`/`bytes`) and `text`/
   `text_method` across by URL (`media.carry_capture_state`). The adapter's
   own fields still win. Without this a re-fetch forgot the held file and
   its reading until `scrolls media` downloaded it again. The state belongs
   to a capture, so it carries only when the re-fetch reports the same
   `content_hash`; a changed capture — the `pdf` adapter hashes the document
   itself — starts its refs over, and `scrolls media` reads them afresh.
4. **Three states, never confused.** Per the completeness contract
   (ADR 0102 §3), "nothing there" must not read as "never looked":
   - `text` is a string — read;
   - `text` is null — read, and nothing extractable (a scanned or encrypted
     PDF); the file stays held;
   - no `text` key — not read yet.
5. **The scroll renders it under `## Documents`.** One `###` heading per
   held document, named by its original file name, between
   `## Extracted Content` and `## Links`. A null reads as an honest absence
   line; an unread file points at `scrolls media`. Frontmatter keeps the
   ref but drops its `text`, which can run to megabytes.
6. **No double reading.** An item whose own adapter already read its PDF
   into `extracted_text` (a pypdf extraction method and text present — the
   `pdf` adapter, a normal arXiv paper) is skipped. An arXiv paper whose
   PDF text failed at fetch gets a second reading here.
7. **A derived view, outside the hash.** Like a summary, the text is
   regenerated from the held file. `content_hash` never moves, so verify
   and drift are untouched.

## Consequences

- **`scrolls media` selects one more kind of pending item:** a held PDF
  never read. Such an item reports `status: "extracted"` with
  `documents: [{path, text: "extracted" | "none"}]`; a download that read
  a PDF carries the same `documents` list.
- **Existing libraries backfill offline** on the next `scrolls media` run.
  A held file that cannot be read fails its own ref and stays unread for
  the next run; it never stops the batch.
- **The round-trip stays lossless.** Media refs travel whole through
  `export items` and bundles, text included; `show` and MCP `get_scroll`
  return it too.
- **Deferred: full-text search.** The FTS index covers `title`, `summary`
  and `extracted_text`, read from the items table, so indexing document
  text needs an index schema change and a rebuild. Until then `search` and
  `context` do not find document text; the scroll, `show` and `get_scroll`
  carry it. *Settled 2026-10-29 by [0119](0119-held-document-text-is-searchable.md).*
- **Deferred: OCR.** Scanned PDFs stay honestly `text: null`.

Tests: `tests/test_documents.py`.
