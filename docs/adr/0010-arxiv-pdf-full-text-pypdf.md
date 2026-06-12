# ADR 0010: arXiv PDF full text via pypdf, inline with graceful degradation

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

ADR 0008 shipped arXiv scrolls with the abstract as `summary` and left
`extracted_text` empty, recording the feed's PDF link as a `media` entry
"for a future full-text slice". That slice is this one. Full text is the
highest-value missing content in the library: papers are exactly the
items agents want deep, citable context from (`scrolls context`,
`scrolls search`), and an abstract alone misses the methods, numbers,
and references that make a paper worth saving.

Open questions were where extraction runs, which dependency to take on,
and what happens when a PDF misbehaves.

## Decision

1. **Extraction runs inline in the arxiv fetch adapter,** not as a new
   pipeline stage or command. Precedent: the youtube adapter fetches
   transcripts inline and degrades to metadata-only for caption-less
   videos (ADR 0003). One `scrolls fetch`/`ingest` of a paper produces
   the complete scroll; no second pass to remember.
2. **pypdf, not PyMuPDF or pdfminer.six.** PyMuPDF extracts better but
   is AGPL-licensed — wrong for an MIT project. pypdf is BSD, pure
   Python, has a one-call text API, and is sufficient for arXiv's
   born-digital LaTeX PDFs (scanned/OCR documents, where pypdf is weak,
   don't occur there). It is imported lazily inside the fetch path, the
   same pattern as trafilatura in the web adapter (ADR 0001's light
   per-adapter dependency posture).
3. **Any PDF failure degrades to the abstract-only scroll** — download
   errors, unparseable bytes, and text-less PDFs alike. The degradation
   is deliberately a broad `except` around the download+extract block:
   the ADR 0008 scroll was already useful, and no PDF problem may take
   it away. Degradation is observable: `extracted_text` stays null and
   `provenance.extraction_method` stays `arxiv-api:atom`, versus
   `arxiv-api:atom+pypdf-<version>` on success.
4. **Page texts join with blank lines; `content_hash` covers the full
   text when present** (else abstract, else feed — consistent with the
   web adapter hashing what was extracted). The feed's plain-`http://`
   PDF link is upgraded to `https://` before download to skip arXiv's
   redirect; the `media` entry keeps the URL exactly as the feed gave it
   (it is provenance, not transport).
5. **The PDF bytes are not persisted to `media/`.** Adapters are
   `ScrollItem -> ScrollItem` functions with no library-paths access;
   capturing media files to disk is its own slice with its own decision
   (interface change vs. a CLI-level download step over `media`
   entries). The `media` link keeps that future open.
6. **Shared transport grows `http.get_bytes`;** `get_text` is now a
   decode of it. The adapter takes an injectable `get_bytes`, so tests
   build a minimal valid one-page PDF by hand (correct xref offsets, a
   single `Tj` text op) and never touch the network or fixture files.

## Consequences

- Paper scrolls and the FTS index now carry full text; `scrolls search`
  and `scrolls context` reach into paper bodies, not just abstracts.
- Fetching a paper costs one extra request and a multi-MB download.
  arXiv's etiquette (~1 request per 3s) already applied per ADR 0008;
  bulk paper imports would need throttling regardless.
- Extracted text is unbounded; a long paper makes a long scroll and a
  bigger FTS index. Local-first and acceptable; revisit only if a real
  library shows pathology.
- pypdf's extraction has LaTeX artifacts (ligatures, hyphenation, math
  spacing). Good enough for search and agent context; a higher-fidelity
  extractor (e.g. marker) could replace `_pdf_text` without touching
  the adapter contract.
- Re-fetching a pre-ADR-0010 paper (`scrolls fetch <id>`) upgrades it
  in place to full text.

## Proof

`tests/test_arxiv.py` covers extraction, the https upgrade, hash
semantics, and all three degradation modes offline;
`tests/test_cli.py::test_ingest_arxiv_paper_end_to_end` proves a
PDF-only phrase is searchable after `ingest`. Live smoke: `scrolls
ingest https://arxiv.org/abs/2310.06825` extracted 24,831 chars
(`extraction_method: arxiv-api:atom+pypdf-6.13.2`), and `scrolls search
"sliding window attention"` found the paper in a fresh library.
