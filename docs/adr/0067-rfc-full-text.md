# ADR 0067: RFC full text — the spec body becomes searchable, with plaintext de-pagination

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

ADR 0066 shipped the RFC adapter abstract-first: the RFC Editor's JSON view gives
the abstract (the `summary`) and the structured metadata (concepts, tags, the DOI
and obsoletes/updates edges), but **no full text** — the scroll carried no
`extracted_text`, so an agent could search an RFC's *abstract* but not its
*normative content*. For a knowledge base whose whole point is searchable, cited
context bundles for agents (IDEAS.md §11), that is the more valuable half of an RFC:
the actual rules for chunked transfer encoding, the TLS handshake state machine,
the JSON grammar. ADR 0066 explicitly flagged fetching the spec text as "a clean
future enrichment, the arXiv/PDF split."

That split is a settled pattern here: the arXiv adapter shipped abstract-only
(ADR 0008), then ADR 0010 added PDF full-text extraction — abstract for the
`summary`, full text for `extracted_text`, degrading to abstract-only on any PDF
failure. RFCs make this *easier* than arXiv: the body is published as plain text at
`https://www.rfc-editor.org/rfc/rfc<N>.txt`, so there is no `pypdf` dependency and
no binary extraction — just a second keyless GET and a text normalizer.

The one wrinkle is pagination. RFCs come in two plaintext formats:

- **Modern (post-2019 xml2rfc v3, e.g. RFC 9110):** unpaginated — no form feeds, no
  `[Page N]` footers, no running headers. A leading BOM and generous blank lines
  are the only noise.
- **Classic (e.g. RFC 2616):** paginated for print — a form-feed (`\f`) between
  pages, a right-aligned `Author, et al.  Standards Track  [Page N]` footer ending
  each page, and a running `RFC <N>  <centered title>  <date>` header atop every
  continuation page.

Left in, the classic boilerplate would pollute the searchable body (a BM25 hit on
"Fielding, et al." or a date repeated 176 times) and break the reading flow.

## Decision

Fetch the RFC's `.txt` and normalize it into `extracted_text`.

1. **A second keyless GET, injectable, degrading.** After the JSON metadata fetch
   (ADR 0066), the adapter GETs `rfc-editor.org/rfc/rfc<N>.txt` through an
   injectable `get_text` (so tests stay offline, ADR 0001). Any failure — a 404, a
   transport error, an empty body — returns `None` and the scroll degrades to
   abstract-only, exactly the arXiv PDF-degrade contract (ADR 0010): full text
   never raises, only the *metadata* fetch can `FetchError`. `provenance.
   extraction_method` records which happened (`rfc-editor:json+txt` vs
   `rfc-editor:json`), and the content hash covers the full text when present
   (`full_text or summary or raw`), so a later body change re-renders.

2. **A de-pagination normalizer that handles both formats with one pass.** The
   text is split on the form feed `\f`; for each page after the first, the running
   header (the first non-blank line, only when it matches `^RFC\s+\d+`) is dropped,
   and every `[Page N]` footer line is removed; runs of three-plus blank lines
   collapse to one. The BOM is stripped. The **modern unpaginated format has no
   form feeds, footers, or headers, so it passes through with only blank-line
   collapsing** — the same code path, no format flag. The page-1 document header
   block (`Network Working Group … Obsoletes: …`) is *content*, not a running
   header, and is kept. The running-header drop is guarded by the `^RFC <digits>`
   match rather than blindly removing each page's first line, so a malformed page
   loses boilerplate at worst, never a line of spec.

The abstract stays the `summary` and the full normalized body becomes
`extracted_text` — the arXiv abstract+PDF division (ADR 0008/0010). Everything
else from ADR 0066 (identity, concepts, tags, the DOI and obsoletes/updates edges,
`rfc → reference`) is unchanged.

## Consequences

- An RFC scroll is now searchable on its actual normative text, not only its
  abstract — `scrolls search`/`context` over a library of RFCs returns the spec
  that *says* the thing, the payoff arXiv's PDF text delivered for papers. The
  body is large (RFC 9110 is ~500 KB; RFC 2616 ~395 KB after de-pagination, 27 KB
  of pagination boilerplate removed), comparable to an arXiv PDF's extracted text;
  `scrolls fetch --limit N` paces a bulk run, and a single `add`/`ingest` pays one
  extra GET.
- `extracted_text` is the normalized body; `raw_text` stays the small JSON metadata
  (not the 500 KB text), so a rebuild re-fetches the body the way arXiv re-fetches
  the PDF — the index is not bloated with a second copy.
- The de-pagination is heuristic but conservative: validated against the real
  RFC 9110 (modern, clean pass-through) and RFC 2616 (classic, all 176 form feeds,
  `[Page N]` footers, and running headers removed, no spec lines lost). A future
  RFC with an unusual header that doesn't match `^RFC <digits>` simply keeps that
  one line — visible noise, never lost content.
- The `.html`/`.xml`/`.pdf` renderings are deliberately ignored: the `.txt` is the
  canonical, dependency-free body. Section-structured extraction (one scroll
  section per RFC section) is a possible future refinement; the flat normalized
  text is enough for FTS today.

## Proof

`src/scrolls/sources/rfc.py` (`_full_text`, `_normalize_rfc_text`) with the
transport faked in `tests/test_rfc.py`: the full text extracted from a modern
unpaginated `.txt` (`test_full_text_extracted_from_the_txt`), the classic
form-feed/`[Page N]`/running-header pagination stripped while every page body
survives and blank-line runs collapse
(`test_full_text_strips_pagination_headers_and_footers`), the `.txt` failure and
empty-body degrades to abstract-only with the honest `extraction_method`
(`test_full_text_failure_degrades_to_abstract_only`,
`test_empty_txt_degrades_to_abstract_only`), the content hash covering the body
(`test_content_hash_covers_the_full_text`), the abstract still the summary
(`test_abstract_becomes_the_plain_summary`), the no-abstract-but-text and the
no-abstract-no-text scrolls (`test_no_abstract_leaves_summary_none_but_keeps_the_rest`,
`test_no_abstract_and_no_text_is_a_metadata_only_scroll`), and both request URLs
(`test_requests_the_expected_json_and_txt_urls`) — all offline (ADR 0001). The
normalizer was additionally validated against the live RFC 9110 and RFC 2616 `.txt`
files (modern and classic formats) before this record was written: zero form feeds,
`[Page N]` footers, or running headers remained, and no spec content was dropped.

RFC text sourced from the RFC Editor.
