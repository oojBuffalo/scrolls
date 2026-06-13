# 0045: DataCite via a fetch-time fallback on the same `doi.org` detection

Date: 2026-06-13

Status: accepted

## Context

The Crossref adapter (ADR 0037) turns a `doi.org/<doi>` link into a clean
scroll from the work's registered metadata, but it covers only the DOIs
Crossref is the registration agency for: the published scholarly
literature — journal articles, conference papers, book chapters. A large
and growing share of saved DOIs are *not* Crossref's. The other major DOI
registration agency is **DataCite**, which registers the DOIs of datasets,
software, models, computational notebooks, and other research outputs
deposited in repositories like Zenodo, Dryad, and figshare. ADR 0037
already names the gap: a DataCite-only DOI 404s against
`api.crossref.org/works/<doi>`, so `crossref.fetch_item` raises a
`FetchError` and the item stays `detected` — or, before the Crossref
adapter, fell through to a `web` scrape of a JavaScript landing page. The
adapter's own docstring flagged the case ("a DataCite-only dataset DOI, for
instance, 404s here"), and ADR 0037's Consequences called the fix "the
obvious extension … a DataCite adapter on the same `doi.org` detection,
chosen by a fetch-time fallback."

DataCite publishes a stable, keyless REST API (`api.datacite.org/dois/<doi>`)
returning the work as a JSON:API document (`{data: {attributes: {…}}}`).
One GET, no auth, no runtime dependency — the same posture as every adapter
since ADR 0002.

One fact dominates the design: **a DOI's registration agency cannot be read
off its URL.** `doi.org/10.5281/zenodo.8408173` (DataCite) and
`doi.org/10.1145/2939672.2939754` (Crossref) are syntactically identical;
only a network round-trip reveals which agency holds a DOI. But Scrolls
mints item identity (`source:source_id`) at `add` time, from the URL alone,
before any fetch — and that identity, `crossref:<doi>`, is already woven
into the link graph: ADR 0038 has arXiv emit a `doi.org` link that
`related`/`graph` fold to a `crossref:<doi>` item, and ADR 0041 does the
same for a Hugging Face model's `arxiv:`/`doi` references. So the source
name in the id is fixed before the agency is knowable, and changing it at
fetch time would break dedupe (a re-add or feed re-sync would mint a second
id) and every existing cross-source edge.

## Decision

A `doi.org` link stays detected as the `crossref` source with a
`crossref:<doi>` id (unchanged — `detect.py`, `tests/test_detect.py`). The
*fetch* becomes a two-agency dispatch, and a DataCite adapter joins the
Crossref one:

- **A `doi.py` dispatcher is what `FETCH_ADAPTERS["crossref"]` points at.**
  It tries `crossref.fetch_item`; on its `FetchError` it tries
  `datacite.fetch_item`; if neither agency holds the DOI it raises a
  `FetchError` naming both failures (`src/scrolls/sources/doi.py`,
  `tests/test_doi.py`). A Crossref-registered DOI fetches on the first try
  and never touches DataCite; a DataCite-only DOI 404s against Crossref and
  is served by the fallback. The two agency adapters stay single-purpose
  and are each tested directly; the dispatcher injects them so its routing
  is tested without the network (ADR 0001).

- **The source name stays `crossref`; provenance tells the truth.** The
  `crossref` source is read as "the `doi.org` adapter, Crossref-first," not
  "the Crossref agency." A DataCite-served item records
  `provenance.adapter = "datacite"` and
  `extraction_method = "datacite-api:json"`, so which agency answered is
  honest even though the source column and id can't carry it. This is the
  deliberate cost of the fetch-time fallback ADR 0037 chose over a DOI-RA
  pre-lookup (`doi.org/doiRA/<doi>`): a DataCite fetch pays one wasted
  Crossref 404 first, in exchange for keeping detection pure and network-free.

- **The DataCite adapter maps the schema's analogs of Crossref's fields**
  (`src/scrolls/sources/datacite.py`, `tests/test_datacite.py`). Identity
  is the folded DOI, `attributes.doi` echoed back builds the canonical
  `https://doi.org/<doi>` URL (ADR 0037's pattern). The main `titles` entry
  joins a `titleType: "Subtitle"` entry `Title: Subtitle`; `creators` render
  "Given Family" (or an organization's `name`), truncated past ten with
  "et al."; the `Abstract`-typed `descriptions` entry is reduced to a plain
  `summary` (tags stripped, entities unescaped — DataCite has no full text,
  so like Crossref there is no `extracted_text`, and a record with no
  abstract is honestly metadata-only); `subjects` become `concepts` (the
  github-topics parallel, ADR 0007); the date is chosen by a DataCite
  precedence (`Issued` → `Available` → … → `Updated`, range start taken),
  falling back to `publicationYear` then the feed/import seed (ADR 0021/0024).

- **The resource type drives classification, carried in provenance.**
  Unlike Crossref (a published work is always a `paper`), a DataCite output
  is a dataset, a tool, a paper, or media depending on
  `types.resourceTypeGeneral`. That fact is knowable only at fetch — it is
  not in the URL — so the adapter records it as `provenance.resource_type`
  and the rules engine maps it (`classify.py`, ADR 0004):
  `Dataset → dataset` (the IDEAS.md §8 term), `Software`/`Model`/`Workflow`/
  `ComputationalNotebook`/`Service → tool`, the textual literature types
  (`Text`, `Book`, `JournalArticle`, …) `→ paper`, audiovisual types
  (`Image`, `Sound`, `Audiovisual`) `→ media`. An ambiguous or absent type
  (`Collection`, `Event`, `Other`) stays unclassified rather than guessed —
  the engine's standing rule. This mirrors how Hugging Face's repo kind is
  read off the source id (ADR 0041, ADR 0043); the difference is the kind
  there is a *detection*-time fact (in the URL), here a *fetch*-time fact
  (in provenance).

- **`resourceTypeGeneral` + `resourceType` + `publisher` become `tags`,**
  the controlled-facet slot (ADR 0008/0037), the publisher being the
  depositing repository so `related` can corroborate two outputs from the
  same one.

- **The landing page and the parent work's DOI become `links`.**
  `attributes.url` (the page the DOI resolves to) is kept when http(s) and
  distinct from the canonical link; a `container` whose `identifierType` is
  `DOI` — a dataset's source paper, a software version's concept record — is
  kept as `https://doi.org/<doi>`. That parent link resolves through
  `related`/`graph` to a saved Crossref paper or sibling DataCite item, the
  cross-source edge of ADR 0038/0041 (verified live: a Zenodo dataset wires
  to its Zootaxa article's `crossref:` item via the container DOI). As with
  Crossref's `reference` array, no other related identifiers are turned into
  links, to bound the edge set.

Per the no-network rule (ADR 0001) the JSON GET is injected; tests run
against a DOI document whose shape was recorded from the live DataCite API
(`tests/test_datacite.py`), and the decision was smoke-tested end-to-end
through `scrolls ingest` against real Zenodo (software, text) and Crossref
(regression) DOIs.

## Consequences

- A saved DataCite DOI becomes a clean scroll — title, creators, the
  depositing repository, publication date, an abstract when present,
  subjects-as-concepts, resource-type tags, and the landing/parent links —
  classified by what it actually is (a dataset as `dataset`, software as
  `tool`), instead of staying stuck at `detected` or falling to a `web`
  scrape. With Crossref (ADR 0037) and arXiv (ADR 0008), Scrolls now spans
  preprints, the published literature, *and* the dataset/software record.
- `x` (Field Theory import only, ADR 0009) remains the sole detected source
  with no fetch adapter. The DataCite adapter is not counted as a new
  *detected* source — it shares `crossref`'s `doi.org` detection — but it is
  the first time two fetch adapters serve one detected source through a
  fetch-time dispatch, a pattern a future agency (mEDRA, JaLC, the Korea/
  China registration agencies) could join in the same `doi.py`.
- The source name `crossref` is now a slight misnomer for a DataCite item;
  `provenance.adapter` is the field that disambiguates, and any consumer
  that cares about the agency (or wants to render "DataCite") reads it
  there. Renaming the source to a neutral `doi` was considered and rejected:
  it is a breaking identity change (`crossref:<doi>` → `doi:<doi>`) that
  would split existing libraries and rewrite the ADR 0038/0041 edge
  resolution, for a cosmetic gain.
- The full DataCite `attributes` record is kept in `raw_text` (it carries no
  full text, so it is small), so a future enrichment — the
  `relatedIdentifiers` graph, funder/affiliation extraction, version lineage
  across a Zenodo concept DOI — can expand a work without a refetch, the
  raw-record-spine discipline every API adapter follows.
