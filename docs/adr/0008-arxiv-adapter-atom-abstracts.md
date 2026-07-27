# ADR 0008: arXiv adapter — keyless Atom export API, abstract as summary

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

*Amended: 2026-07-26 — the Field Theory import proposal moved from the
IDEAS.md brainstorm into `docs/inspiration/fieldtheory-cli-inspiration.md`;
the citation below now points at ADR 0009. Decision content unchanged.*

## Context

arXiv is the second post-MVP source (README "Initial platform targets":
"PDFs/arXiv papers, where extractable"). As with github (ADR 0007), the
pipeline already anticipated it: `detect.py` maps `arxiv.org/abs|pdf/…`
URLs to source `arxiv` (handling both new-style `2310.06825` and
old-style `math/0211159` ids, stripping `.pdf`), and the rules engine
carries a curated `arxiv → paper` category. The open question was what a
paper scroll's content should be when full-text extraction needs heavy
PDF dependencies the stack has deliberately avoided so far (ADR 0001).

## Decision

1. **Keyless arXiv export API, stdlib XML.** One GET against
   `https://export.arxiv.org/api/query?id_list=<id>&max_results=1`
   returns an Atom feed parsed with `xml.etree.ElementTree` — no auth,
   no new dependencies, and the adapter takes an injectable `get_text`
   (the first text-transport adapter, alongside the JSON ones). Atom's
   line-wrapping whitespace is collapsed out of title/summary/published.
2. **The abstract is the summary, not extracted text.** It maps to
   `summary` only — it *is* a summary by definition, and faking it into
   `extracted_text` would overstate what was extracted. Search still
   finds papers by abstract because FTS indexes `summary`. Full text
   waits for a PDF-extraction slice (PyMuPDF/marker-grade dependency),
   which is also why the PDF link is stored as a `media` entry
   (`{"type": "pdf", "url": …}`) — the same pattern as youtube
   thumbnails: recorded, not yet downloaded.
3. **Taxonomy codes go to `tags`, not `concepts`.** arXiv categories
   (`cs.CL`) are curated but are opaque codes, not readable concept
   names like repo topics or wikipedia categories; putting them in
   `concepts` would make cryptic KB pages. Translating codes to display
   names ("Computation and Language") would mean carrying the arXiv
   taxonomy table — a fine future slice, deliberately not this one.
4. **All authors, comma-joined,** in the single `author` field; papers
   are the first source where authorship is a list. `published_at` comes
   from `<published>` (v1 submission time), `canonical_url` from the
   versioned `rel=alternate` link, and the raw Atom feed is kept in
   `raw_text` for rebuilds. `content_hash` covers the abstract when
   present, else the feed.
5. **Errors:** an empty feed (well-formed but unknown id) and the API's
   error entries (`/api/errors` ids for malformed input) both raise
   `FetchError`; a blank abstract degrades to a metadata-only scroll.

## Consequences

- Paper scrolls carry no full text until a PDF slice lands; the `media`
  PDF link and `raw_text` feed give that slice everything it needs.
- `concepts` stays empty for papers, so they appear in KB source and
  category pages but not concept pages, until a taxonomy-name mapping
  or LLM engine produces readable concepts.
- The export API is rate-limited by etiquette (arXiv asks for ~1 request
  per 3 seconds in bursts); fine for one-off `add`, a bulk import would
  need throttling.
- CLI tests that needed an adapterless source now use `x`, which stays
  adapterless longest (Field Theory import is the planned path, ADR 0009).

## Proof

`src/scrolls/sources/arxiv.py` with transport-faked tests
(`tests/test_arxiv.py`, end-to-end CLI test in `tests/test_cli.py`), and
a live keyless smoke test: `scrolls ingest
https://arxiv.org/abs/2310.06825` produced a rendered `paper` scroll for
"Mistral 7B" with all 18 authors, tags `cs.CL/cs.AI/cs.LG`, the abstract
as summary, and a PDF media link.
