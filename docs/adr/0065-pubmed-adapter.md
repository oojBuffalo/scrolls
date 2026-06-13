# ADR 0065: PubMed adapter — the biomedical literature, with MeSH as concepts and a DOI edge to Crossref

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

Scrolls reaches scholarly papers through two adapters: arXiv for preprints
(ADR 0008) and Crossref for the published works that carry a DOI (ADR 0037),
with DataCite filling the dataset/software DOIs (ADR 0045). All of them lean
toward the physical sciences and computer science — arXiv's home turf, and the
fields whose DOIs Crossref holds. **The biomedical and life-sciences literature
— the single largest body of scholarly writing — had no first-class home.** A
saved `pubmed.ncbi.nlm.nih.gov/<pmid>` link fell through to the generic `web`
adapter (ADR 0001): `trafilatura` would scrape the PubMed abstract page, but the
record's *structure* was lost — most importantly its **MeSH terms**, the curated
subject vocabulary that is exactly the high-signal `concepts` source the KB graph
wants (the github-topics/arXiv-taxonomy role, ADR 0007/0012). A PubMed `web`
scroll was a concept-poor island, the same gap dev.to had before ADR 0061.

NCBI's E-utilities expose this keyless. A single
`GET .../efetch.fcgi?db=pubmed&id=<pmid>&retmode=xml` returns the whole record —
title, authors, journal, dates, the abstract, the MeSH headings, the publication
types, and the article's DOI — as XML parsed with stdlib ElementTree, no auth and
no runtime dependency (the arXiv Atom discipline, ADR 0008). The adapter contract
(ADR 0002) and the existing paper adapters make this a near-template build; the
value is in three platform facts and one cross-source edge.

## Decision

Add `pubmed`, a keyless fetch adapter for the biomedical literature.

1. **Identity is the PMID; detection claims the dedicated host and shape-matches
   the legacy one.** `pubmed:<pmid>`, the integer accession. The modern host
   `pubmed.ncbi.nlm.nih.gov` is claimed wholesale — the first path segment is the
   PMID, and a record subpage (`/<pmid>/citedby/`) dedupes to it (`_pubmed_id`,
   github's profile-page posture for non-record pages). The **legacy**
   `www.ncbi.nlm.nih.gov/pubmed/<pmid>` form (NCBI now redirects it) lives on a
   host that *also* serves PMC, Gene, Nucleotide, and many other databases, so it
   is **shape-matched** — only `/pubmed/<digits>` matches, every other NCBI path
   falls through to `web` (`_ncbi_pubmed_id`). A legacy and a modern link to the
   same record dedupe to one item. (PMC full text, `/pmc/articles/PMC<id>`, is a
   different artifact and stays `web` — a possible future sibling, the arXiv/PDF
   split.)

2. **MeSH descriptors are the concepts, with author keywords as the fallback.**
   `MeshHeadingList/MeshHeading/DescriptorName` is PubMed's curated controlled
   vocabulary (`DNA Cleavage`, `Protein Folding`) — the highest-signal `concepts`
   source any adapter has, joining github topics and arXiv taxonomy names in the
   KB concept graph (ADR 0007/0012). Descriptor *qualifiers* (`isolation &
   purification`) are dropped — the descriptor is the concept. A record not yet
   MEDLINE-indexed (an ahead-of-print article) carries no MeSH but often does
   carry author `Keyword`s, used as the fallback so a fresh article still joins
   the graph rather than becoming an island. The `tags` field stays for the
   controlled *facet* (below), not these topical terms — the github/devto posture
   (ADR 0007/0061).

3. **The abstract is the content; there is no full text.** PubMed holds metadata
   and abstracts, not full text (that is PubMed Central), so the abstract — the
   `AbstractText` sections joined with their structured labels (`BACKGROUND: …
   METHODS: …`) — is the searchable `summary`, with **no `extracted_text`**. This
   mirrors Crossref exactly (ADR 0037), the other metadata-only paper source; a
   record with no abstract degrades to a metadata-only scroll (ADR 0002), not a
   `FetchError`.

4. **The DOI is the one outgoing link — the PubMed↔Crossref paper edge.** A
   record's DOI (`ArticleIdList/ArticleId[@IdType='doi']`, or `ELocationID`) becomes
   a single `https://doi.org/<doi>` link, which resolves through source detection
   to the `crossref:<doi>` item a saved DOI mints — wiring a PubMed record to its
   published Crossref scroll. This is the **biomedical analog of arXiv's
   preprint↔published edge** (ADR 0038) and directly advances the cross-source
   paper-enrichment direction `docs/architecture.md` flagged. The PMC id is
   deliberately *not* a link — PMC is not a detected source, so it would resolve
   to no saved item (Crossref's "references are not links" discipline, ADR 0037).

5. **Date precedence: electronic `ArticleDate` → journal `PubDate` → history.**
   The electronic `ArticleDate` (clean numeric Y/M/D) is the earliest, most
   precise publication date and is preferred; the journal issue `PubDate` is next
   (it may carry a month *name* like `Aug`, only a year, or a free-text
   `MedlineDate`, all parsed); the PubMed history `pubmed` status date is the
   final fallback. A partial date pads to the start of the period — invented
   precision for one uniform shape (ADR 0024). Publication types
   (`Journal Article`, `Review`, …) plus the journal title become `tags`, the
   controlled-facet slot Crossref's `type`/venue fill (ADR 0037). A PubMed record
   classifies as `paper` like an arXiv or Crossref one (ADR 0004). Inline title/
   abstract markup (`<i>`, `<sup>`) is flattened via `itertext`, and the raw
   efetch XML stays in `raw_text` for rebuilds.

## Consequences

- A saved PubMed article now joins the concept graph (via MeSH) and the link
  graph (via its DOI → Crossref) instead of sitting as a `web` island. Re-adding a
  URL previously saved as `web` mints a *different* id (`pubmed:<pmid>` vs
  `web:<hash>`), so the two do not auto-merge — acceptable, like dev.to (ADR 0061);
  the `web` copy can be `scrolls rm`'d. This is not a pre-normalization duplicate,
  so `scrolls doctor` (ADR 0026) is not involved.
- The PubMed↔Crossref edge means a user who saves both a PubMed record and its DOI
  gets two scrolls that *relate* but do not merge — the same near-duplicate the
  arXiv↔Crossref edge produces (ADR 0038). A concept-level merge of a paper's
  several representations is the open enrichment step both edges now motivate.
- efetch returns `<PubmedArticle>`; `<PubmedBookArticle>` (NCBI Bookshelf entries)
  uses a different schema and is treated as "not found" — book records are
  deferred, a clean future extension.
- No `tool`/`email` query param or API key is wired. NCBI throttles anonymous use
  to ~3 requests/sec, fine for `scrolls add`/`ingest`; a heavy bulk run would want
  the `--limit` pacing (ADR, fetch batching) and, to lift the limit, an API key —
  the same optional-credential door the code-host adapters left open
  (ADR 0007/0055), deferred until a bulk biomedical workflow needs it.

## Proof

`src/scrolls/sources/pubmed.py` with transport-faked tests
(`tests/test_pubmed.py`, the fixture trimmed from the real efetch response for
PMID 22745249, Jinek et al. 2012, *Science*, DOI 10.1126/science.1225829): the
core metadata mapping and "Fore Last" author rendering, the MeSH-as-concepts join
(qualifiers dropped) and the author-keyword fallback (and the honestly-empty
case), the abstract-as-`summary` semantics with entity/inline-markup flattening
and structured-section labels (no `extracted_text`), the publication-type/venue
tags, the DOI → `doi.org` cross-source link (and the no-DOI empty case), the
ArticleDate→PubDate→history date precedence (including month-name, year-only, and
`MedlineDate` parsing), author truncation with "et al.", collective names, the
metadata-only degrade, the PMID title fallback, identity/URL preservation, the
requested efetch URL, and the missing-id / not-found / request-failed
`FetchError`s — all offline (ADR 0001). Detection is pinned in
`tests/test_detect.py` (the dedicated host, the shape-matched legacy host, PMC and
other NCBI databases falling through to `web`, subpage dedupe, search/home pages
carrying no record), the `pubmed → paper` rule in
`tests/test_classify.py` (`test_pubmed_classifies_as_paper`), and the
`FETCH_ADAPTERS["pubmed"]` registration in `test_registered_in_fetch_adapters`.
The PubMed↔Crossref edge was verified end-to-end through the unmodified
`graph.build_graph`/`related.find_related`: a fetched PubMed record's DOI link
resolves to a `crossref:<doi>` item as a directed edge ("links to it").

PubMed data sourced from PubMed; the fixture article's DOI is
[10.1126/science.1225829](https://doi.org/10.1126/science.1225829).
