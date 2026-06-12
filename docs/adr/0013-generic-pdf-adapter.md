# 0013: Generic PDF fetch adapter via pypdf

- Status: accepted
- Date: 2026-06-12

## Context

`detect_source` has mapped `.pdf` URLs to a `pdf` source since the
detection table was built, but no fetch adapter existed: `scrolls add`
registered PDF items and `scrolls ingest <url>.pdf` exited 1 with
"no fetch adapter for source 'pdf'". That made `pdf` the only detected
source besides `x` that the pipeline couldn't carry to a scroll — and
`x` items arrive through Field Theory import by design (ADR 0009).
Meanwhile `pypdf` is already a dependency (arXiv full text, ADR 0010),
so closing the gap costs no new packages.

Unlike every platform adapter, a bare PDF URL offers no metadata API:
there is no feed, oEmbed, or REST endpoint to lean on — only the
document itself and its URL.

## Decision

Add `sources/pdf.py` with the standard adapter contract
(`ScrollItem -> ScrollItem`, `FetchError`, injectable transport),
registered for source `pdf`:

- **Identity is the URL.** No source-local id exists, so item ids stay
  `pdf:<12-hex URL hash>` via the existing `make_item_id` fallback —
  the same scheme as `web`.
- **Metadata comes from the document-information dictionary.**
  `/Title` → `title` (falling back to the de-slugged URL filename,
  "attention-is-all-you-need" → "attention is all you need"),
  `/Author` → `author`, `/Subject` → `summary`, `/CreationDate` →
  `published_at`. No `/Subject` means no summary — nothing is
  fabricated; context bundles already fall back to leading extracted
  text. Each field is independently fallible: one malformed entry never
  drops the others.
- **The binary is the raw record, not `raw_text`.** PDF bytes don't
  belong in a TEXT column. `content_hash` is the SHA-256 of the exact
  downloaded bytes, and the document is recorded as a
  `{"type": "pdf", "url": ...}` media ref so `scrolls media` captures
  the file itself into `media/pdf/` (ADR 0011). `raw_text` stays NULL.
- **Failure vs degradation.** A failed download or a payload pypdf
  cannot open raises `FetchError` — an HTML error page or paywall stub
  must not become a scroll. A *readable* PDF whose text extraction
  fails or yields nothing (scanned pages, encryption) degrades to a
  metadata-only scroll with the media ref intact: the document still
  gets captured and the item can be re-fetched later.
- **No classification rule.** A generic PDF is not inherently a paper,
  manual, or report, so the rules engine leaves it unclassified
  (ADR 0004's honesty posture); the future LLM engine picks it up.
- **Shared extraction.** The bytes→text path lives in
  `pdf.extract_text`, and the arXiv adapter's `_pdf_text` now delegates
  to it — one implementation of the "any PDF failure returns None"
  contract (ADR 0010) instead of two.

## Consequences

- Every detected source except `x` now has a fetch adapter;
  `scrolls ingest https://…/report.pdf` produces a scroll end to end
  (`tests/test_pdf.py`, `test_ingest_pdf_url_end_to_end`).
- `docs/cli.md`'s no-adapter walkthrough examples moved from the `pdf`
  source to `x`, the only remaining adapter-less source.
- PDF text quality is whatever pypdf extracts — no OCR, no layout
  reconstruction. Good enough for search and excerpts; a richer
  extractor (e.g. marker, PyMuPDF) would be a separate decision.
- A PDF URL is re-downloaded at media-capture time even though fetch
  already had the bytes — the same trade the arXiv adapter makes
  (ADR 0011: the media tree is cache, not canon).
