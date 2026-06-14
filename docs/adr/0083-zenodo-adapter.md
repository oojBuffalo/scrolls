# 0083: Zenodo adapter — open-science records, the landing page behind the DataCite DOI

Date: 2026-06-13

Status: accepted

## Context

Scrolls covers papers (arXiv, Crossref, PubMed, bioRxiv/medRxiv — ADR
0008/0037/0065/0068), standards (RFC), code (five hosts), packages (six
registries), ML artifacts (Hugging Face), books (Open Library, ADR 0073),
structured knowledge (Wikidata, ADR 0075), social posts, and forums. **Research
datasets and software deposits were missing a first-class home.**
[Zenodo](https://zenodo.org) — CERN's general-purpose open-science repository,
built on InvenioRDM — is where datasets, research software, preprints, posters,
and presentations are deposited and minted a DOI. It is the default archive for
EU-funded research output and the snapshot every released GitHub repo gets when
it wants a citable DOI (the GitHub↔Zenodo integration). A saved
`zenodo.org/records/<id>` landing page fell through to the `web` adapter: a
`trafilatura` scrape of a JavaScript app that loses the record's keywords, its
resource type, and — most of all — the DOI and the related-identifier edges that
tie a deposit to the paper it supplements or the software it archives. It was a
concept-less, edgeless island, the exact gap dev.to had before ADR 0061 and
books had before ADR 0073.

Zenodo's DOIs are **DataCite**-registered, so a saved `doi.org/10.5281/zenodo.<id>`
link already fetches a clean scroll through the DataCite adapter (ADR 0045). But
the URL a researcher actually pastes is the **landing page**, not the DOI — and
that landing page has its own keyless API. Zenodo's InvenioRDM REST API serves
each record as a plain JSON object at `zenodo.org/api/records/<recid>` — no auth,
no key, no runtime dependency (the arXiv/Crossref/Open Library discipline, ADR
0008/0037/0073), and no JSON:API envelope (unlike DataCite, the record fields are
at the top level with the descriptive metadata under `metadata`).

## Decision

Add a `zenodo` source (host-claimed on `zenodo.org`) and a keyless fetch adapter
(`sources/zenodo.py`).

- **Identity is the record id in the URL.** `/records/<id>`, the legacy singular
  `/record/<id>`, and the `/api/records/<id>` form people paste all carry the
  integer record id after a `record`/`records` path segment, so the id is taken
  from the digits there and a deeper link (`/records/<id>/files/...`,
  `/preview/...`) dedupes to it (the slug-dropped Discourse pattern, ADR 0054).
  The record id names a **specific version**; `conceptrecid`/`conceptdoi` name
  the all-versions concept. The URL identifies one version, so the recid is kept
  verbatim as identity — different versions are different items, the Open Library
  edition rule (ADR 0073). Communities, search, deposit, and badge routes carry
  no record. The sandbox test instance (`sandbox.zenodo.org`) is deliberately
  excluded — its records are throwaway.

- **The record's DOI is the edge to its DataCite scroll.** The record DOI becomes
  a `https://doi.org/<doi>` link, so the Zenodo landing page and the DataCite DOI
  scroll of the same deposit relate through `scrolls related`/`graph` and cluster
  as **one work** in `scrolls works` (the DOI-edge + clustering pattern of ADR
  0037/0045/0069). The `conceptdoi` (all-versions DOI) links to the concept.

- **The description is the summary; there is no full text.** Zenodo descriptions
  are HTML, reduced to plain text like Crossref's JATS / DataCite's abstract (ADR
  0037/0045). The deposit's *files* are the work body — captured separately by
  `scrolls media` if ever — so there is **no `extracted_text`**: the metadata-only
  shape of Crossref/DataCite/PubMed/Open Library, and the shape that keeps the
  Zenodo scroll consistent with its DataCite-DOI twin so `works` clustering stays
  clean.

- **The resource type determines the category.** `resource_type.type` (`dataset`,
  `software`, `publication`, `image`, `video`, …) is recorded in
  `provenance.resource_type`, and the rules engine maps it (`classify.py`) — a
  Zenodo deposit is not always a paper, exactly like a DataCite output (ADR 0045),
  and the type can only be known after fetch. `dataset → dataset`,
  `software → tool`, `publication → paper` (the whole journal-article/preprint/
  report/thesis family), `image`/`video → media`; the genuinely ambiguous types
  (`poster`, `presentation`, `lesson`, `physicalobject`, `other`) stay
  unclassified rather than guessed — DataCite's honesty rule.

- **Keywords + subjects → concepts; type/subtype/license → tags.** The deposit's
  free-text `keywords` and its controlled `subjects` (keyed `subject` or, in newer
  InvenioRDM, `term`) join the KB concept graph the way github repo topics do (ADR
  0007/0065). `resource_type.type` (the controlled facet slot, ADR 0008), its
  `subtype`, and `license.id` (`cc-by-4.0`, `cc-zero`) become `tags`.

- **Related identifiers are outgoing edges, resolved by scheme.** Each
  `related_identifiers` entry becomes a link by its `scheme`: a `doi` →
  `doi.org/<doi>` (a supplemented paper, an archived version), an `arxiv` →
  `arxiv.org/abs/<id>` (the preprint edge of ADR 0038, the `arXiv:` prefix
  stripped), a `url` kept when http(s). Other schemes (`isbn`, `pmid`, `handle`)
  are skipped — no resolver this library detects, so they would be dead links.
  Self-links and duplicates drop, the graph's rule.

## Consequences

- **Datasets and software join the library as first-class scrolls.** A saved
  Zenodo record now wires into the concept graph through its keywords/subjects,
  carries its resource-type category, and — through its DOI — relates to and
  clusters with its DataCite DOI scroll and any sibling paper. `test_zenodo.py`
  covers the core mapping, the HTML-summary/no-extracted-text posture, the
  keyword+subject concepts, the type/subtype/license tags, the partial-date
  padding, the full link set (record DOI, concept DOI, the three related-identifier
  schemes), dedupe, the metadata-only degrade, and error handling — all offline
  against a trimmed fixture recorded from the live API (ADR 0001). A live smoke
  test confirmed a dataset and a legacy concept-record URL ingest cleanly, the
  `isSupplementTo` arXiv link surfaces as a real edge, and `classify` assigns
  `dataset`.

- **The landing-page/DOI symmetry.** Zenodo is the first source whose preferred
  save URL (the landing page) and its DOI form (already covered by DataCite)
  describe the same deposit through two adapters — resolved not by a dispatcher
  (the agency-unknown DOI case of ADR 0045) but by two distinct detected sources
  (`zenodo` for the page, `crossref` for the DOI) that the DOI link binds back
  together in `works`. The same shape a future figshare/Dryad/OSF adapter would
  take (a DataCite-registered repository with its own landing-page API).

- **Deferred.** Version↔concept consolidation (deduping a record to its concept
  DOI — a fetch-time id rewrite every adapter defers, ADR 0048), the deposit's
  *files* as captured media (the `scrolls media` job, a binary download), and
  self-hosted InvenioRDM/Zenodo instances (no universal shape tell, deferred like
  self-hosted GitLab — ADR 0055) are left for later. This ADR adds the adapter.
