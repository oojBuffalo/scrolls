# ADR 0068: bioRxiv / medRxiv adapter — preprint servers, two sources on one adapter, with a DOI edge to Crossref

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

Scrolls reaches scholarly papers through arXiv for preprints (ADR 0008),
Crossref for the published works that carry a DOI (ADR 0037), DataCite for the
dataset/software DOIs (ADR 0045), and PubMed for the biomedical literature
(ADR 0065). One conspicuous gap remained on the preprint side: **arXiv was the
only preprint server.** Biology and medicine moved their fast, un-peer-reviewed
output to **bioRxiv** and **medRxiv** — the two largest preprint servers outside
arXiv's physics/CS home turf — yet a saved
`biorxiv.org/content/10.1101/<accession>` link fell through to the generic `web`
adapter (ADR 0001). `trafilatura` would scrape the landing page, but the
record's *structure* was lost: its subject area, its version, its study type,
and — most importantly — the **published-journal DOI** that wires a preprint to
the peer-reviewed article it became. A bioRxiv `web` scroll was a concept-poor,
edgeless island, the same gap dev.to had before ADR 0061 and PubMed before
ADR 0065.

bioRxiv and medRxiv are run by one operator (Cold Spring Harbor Laboratory) on
**one shared keyless API**: a single `GET api.biorxiv.org/details/<server>/<doi>`
returns the whole record — title, authors, date, version history, abstract,
subject category, license, and the published DOI — as JSON parsed with stdlib
`json`, no auth and no runtime dependency (the arXiv Atom discipline, ADR 0008).
The two servers differ *only* by the `<server>` path segment. The adapter
contract (ADR 0002) and the existing paper adapters make this a near-template
build; the value is in one identity decision, three platform facts, and one
cross-source edge.

## Decision

Add `biorxiv` and `medrxiv` as **two distinct sources served by one fetch
adapter** (`sources/biorxiv.py`).

1. **Two sources, not one — honesty over the unify-by-platform reflex.** The
   Hugging Face adapter put three repo kinds under one source with the kind in
   `source_id` (ADR 0041/0043), and bioRxiv/medRxiv sharing one operator and one
   API invites the same move. It is rejected: a medRxiv paper **does not live on
   bioRxiv** — they are sibling servers with distinct scopes (biology vs. health
   sciences) and distinct brands — so labeling a medRxiv paper `source=biorxiv`
   would be dishonest in a way a `huggingface` dataset is not (a dataset really
   is on Hugging Face). Honesty is a standing project value (`provenance.adapter
   = "datacite"` while `source = "crossref"`, ADR 0045; "honestly empty"
   throughout). So detection returns `biorxiv` or `medrxiv` by host, identity is
   the clean `biorxiv:10.1101/<accession>` / `medrxiv:10.1101/<accession>` (no
   redundant server prefix), and `scrolls list --source medrxiv` filters cleanly.
   **One adapter still serves both:** `FETCH_ADAPTERS` maps both sources to
   `biorxiv.fetch_item`, which reads `item.source` to pick the `<server>` path
   segment — the DRY of a shared module without the dishonesty of a shared source
   (the inverse of the `doi.py`/`threadiverse.py` shape, where one source
   dispatches over several adapters; here several sources share one adapter).

2. **The latest version is the scroll.** A preprint accrues versions (`v1`,
   `v2`, …), returned as an ascending `collection` array under one DOI. The
   highest-numbered entry is the current preprint, so the adapter reads its
   fields and every version/view URL
   (`/content/10.1101/<acc>v2.full`, `…v2.full.pdf`, the legacy
   `/content/early/<Y>/<M>/<D>/<acc>v1`) dedupes to one `10.1101/<accession>`
   item — the arXiv `abs`/`pdf` dedupe (ADR 0008). The DOI is the lookup key the
   adapter passes back to the API, so a folded/variant URL never breaks the
   fetch.

3. **The abstract is the content; there is no full text.** The API serves
   metadata and the abstract, not the body (the JATS full text exists behind a
   separate fetch and an anti-bot wall), so the whitespace-collapsed abstract is
   the searchable `summary` with **no `extracted_text`** — the Crossref/PubMed
   shape (ADR 0037/0065). The PDF is likewise **not** a media ref: the
   `.full.pdf` URL `403`s an unauthenticated client (verified against the live
   site), so a captured ref would only ever fail; an honest metadata-only scroll
   beats a broken link (ADR 0002/0011). This is the deliberate divergence from
   arXiv, whose `arxiv.org/pdf` *does* serve anonymously and so becomes `media`
   plus `extracted_text` (ADR 0010).

4. **The published DOI is the cross-source edge — the preprint↔published link.**
   When a preprint has been published in a journal, the `published` field carries
   that DOI (else the sentinel `"NA"`). A real DOI becomes a single
   `https://doi.org/<doi>` link that resolves, through source detection in
   `related`/`graph`, to the `crossref:<doi>` item a saved DOI mints — wiring the
   preprint to its peer-reviewed article. This is **exactly arXiv's `arxiv:doi`
   preprint↔published edge** (ADR 0038), and PubMed's biomedical analog
   (ADR 0065), and directly advances the cross-source paper-enrichment direction
   `docs/architecture.md` flags. An unpublished preprint is honestly edgeless.

5. **Subject → concept; type/venue/license → tags; preprint → paper.** The
   single subject `category` (`microbiology`, `epidemiology`) becomes the one
   `concept` (sentence-cased so an acronym like `HIV/AIDS` survives), the
   curated-vocabulary slot github topics and arXiv taxonomy names fill
   (ADR 0007/0012). The study `type` (`new results`, `confirmatory results`) is
   title-cased into a `tag` — but **only when it reads as a real type** (a
   space-bearing phrase), so medRxiv's legacy sentinel `PUBLISHAHEADOFPRINT` is
   dropped rather than tagged; the `server` name (`bioRxiv`/`medRxiv`) is the
   venue tag (the controlled-facet slot a journal name fills for Crossref/PubMed),
   joined by a recognized CC `license` mapped to its canonical form (`cc_by_nc_nd`
   → `CC-BY-NC-ND`; the non-CC `cc_no` produces no tag). A preprint classifies as
   `paper` like an arXiv one (ADR 0004). The chosen version's raw record stays in
   `raw_text` for rebuilds; authors arrive `; `-joined as `Family, G. I.` and are
   reordered to `G. I. Family` and truncated past ten with "et al." — the
   Crossref/PubMed rule (ADR 0037/0065).

## Consequences

- A saved bioRxiv/medRxiv preprint now joins the concept graph (via its subject)
  and the link graph (via its published DOI → Crossref) instead of sitting as a
  `web` island. Re-adding a URL previously saved as `web` mints a *different* id
  (`biorxiv:<acc>` vs `web:<hash>`), so the two do not auto-merge — acceptable,
  like dev.to and PubMed (ADR 0061/0065); the `web` copy can be `scrolls rm`'d.
- The preprint↔published edge means a user who saves both a bioRxiv preprint and
  its journal DOI gets two scrolls that *relate* but do not merge — the same
  near-duplicate the arXiv↔Crossref and PubMed↔Crossref edges produce
  (ADR 0038/0065). With four paper sources now feeding `doi.org` edges, the
  concept-level merge of a work's several representations (preprint, PubMed
  record, published DOI) is the increasingly-motivated open enrichment step.
- Detection claims the whole `biorxiv.org`/`medrxiv.org` hosts: a non-content
  page (the homepage, a subject collection, an about page) resolves to the source
  with no fetchable id (github's profile-page posture), not `web`. This is
  consistent with every other host-claimed source.
- `cc_no` and any unrecognized license code produce no license tag rather than a
  misleading one; an `abstract`-less or `published`-less record degrades
  gracefully (no `summary` / no link), never a `FetchError`.
- No API key or `tool`/`email` param is wired; the API is fully keyless. A heavy
  bulk run would want the `--limit` fetch pacing, the same door every keyless
  adapter leaves open. ChemRxiv, Research Square, and the other Rxiv-family
  servers run *different* APIs and would each be their own adapter (or `web`)
  until one is built — they are not `api.biorxiv.org` servers, so they cannot
  ride this one the way medRxiv does.

## Proof

`src/scrolls/sources/biorxiv.py` with transport-faked tests
(`tests/test_biorxiv.py`, fixtures trimmed from the real `api.biorxiv.org`
responses for `10.1101/2020.03.20.001008` — a two-version bioRxiv preprint that
became a *PLoS Biology* paper — and `10.1101/2020.03.09.20033357` — a
single-version medRxiv preprint): latest-version selection, the
abstract-as-`summary` whitespace collapse (no `extracted_text`), `Family, G. I.`
→ `G. I. Family` reordering with "et al." truncation, the subject-as-concept
(sentence-cased), the type/venue/license tags (and the `PUBLISHAHEADOFPRINT`
sentinel drop), the published-DOI → Crossref edge (and the unpublished empty
case), the shared adapter dispatching on `item.source` to the right `<server>`
endpoint, `biorxiv`/`medrxiv` → `paper` classification, the metadata-only
degrade, and the missing-id / not-found / request-failed `FetchError`s — all
offline (ADR 0001). Detection is pinned in `tests/test_detect.py` (the modern
and legacy-early content shapes, version/view dedupe, the 6- vs 8-digit
accession serials, medRxiv as its own source, non-content pages carrying no
item), the classification rules in
`tests/test_classify.py::test_biorxiv_and_medrxiv_classify_as_paper`, and the
shared registration in
`tests/test_biorxiv.py::test_both_sources_register_the_shared_adapter`. The
preprint↔published edge was verified end-to-end through the unmodified pipeline:
a fetched bioRxiv preprint's `published` DOI link resolves to a saved
`crossref:<doi>` item as a directed edge ("links to it") in `scrolls related`.

bioRxiv/medRxiv data sourced from bioRxiv/medRxiv (Cold Spring Harbor
Laboratory); the fixture preprint was published as
[10.1371/journal.pbio.3000896](https://doi.org/10.1371/journal.pbio.3000896).
