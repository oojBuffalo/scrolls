# 0081: DOI content negotiation — the universal agency fallback behind Crossref and DataCite

Date: 2026-06-13

Status: accepted

## Context

A `doi.org/<doi>` link is detected as the `crossref` source, and which
agency holds the DOI is resolved at fetch time by the `doi.py` dispatcher:
Crossref first, DataCite second (ADR 0037, ADR 0045). That covers the two
largest DOI registration agencies — the published scholarly literature
(Crossref) and the datasets/software/repository outputs (DataCite) — but
they are not the only two. The DOI system has roughly a dozen registration
agencies, and several register a great deal of saved-worthy scholarship:

- **JaLC** (Japan Link Center) — the registration agency for essentially the
  entire Japanese scholarly literature, journals and university repositories.
- **mEDRA** — the European multilingual agency (Italian and EU publishers).
- **KISTI** (Korea), **ISTIC**/**CNKI** (China), **Airiti** (Taiwan), and
  the **EU Publications Office** (OP).

A DOI registered with any of these 404s against *both* `api.crossref.org`
and `api.datacite.org`, so before this change the `doi.py` dispatcher
exhausted its two tiers and raised — the item stayed `detected`, or (before
the Crossref adapter) fell through to a `web` scrape of whatever landing
page the DOI resolved to, often a paywall in a language the extractor
mangles. ADR 0045's Consequences anticipated this: "a third DOI registration
agency (mEDRA, JaLC) joining the same `doi.py` dispatch" was a named next
candidate.

The naive reading is "write a JaLC adapter, then an mEDRA adapter, then…" —
one bespoke adapter per agency, each against that agency's own REST API.
But the DOI system already solves the multi-agency problem with **content
negotiation** (citation.crosscite.org/docs): a GET to `https://doi.org/<doi>`
with `Accept: application/vnd.citationstyles.csl+json` is proxied by the DOI
resolver to whichever agency holds the DOI, and *every* agency's
content-negotiation server answers with the same **CSL-JSON** document
(Citation Style Language JSON — the format Zotero, Pandoc, and citation
processors consume). One request shape, one response format, every agency at
once, no auth, no runtime dependency — the same posture as every adapter
since ADR 0002.

CSL-JSON is the structural sibling of Crossref's REST JSON (ADR 0037): the
same `DOI`, `author`, `issued`, `abstract`, `subject`, `URL`, `type` fields,
with a few shape differences (`title`/`container-title` are plain strings,
not single-element arrays; authors carry `literal` for organizations). The
Crossref adapter's whole shape — JATS abstract cleaning, author truncation,
date precedence, subject→concepts, type+venue→tags, landing-page link, the
metadata-only honest default — transfers almost verbatim.

## Decision

Add a **third tier** to the `doi.py` dispatcher: a generic
content-negotiation adapter (`src/scrolls/sources/csl.py`) reached only when
both Crossref and DataCite 404 a DOI.

- **The dispatcher is now a three-tier cascade.** `FETCH_ADAPTERS["crossref"]`
  still points at `doi.fetch_item`, which tries `crossref.fetch_item`, then
  `datacite.fetch_item`, then `csl.fetch_item`; if none holds the DOI it
  raises a `FetchError` naming all three failures
  (`src/scrolls/sources/doi.py`, `tests/test_doi.py`). A Crossref DOI fetches
  on tier one and never touches the fallbacks; a DataCite DOI on tier two; a
  JaLC/mEDRA/KISTI/OP DOI on tier three. The three adapters stay
  single-purpose and are each tested directly; the dispatcher injects them so
  its routing is tested without the network (ADR 0001).

- **One adapter for the entire long tail, not one per agency.** Because
  content negotiation is agency-agnostic, `csl.py` reaches every remaining
  agency through one code path — a strictly larger coverage win than a
  single JaLC adapter would have been, for comparable code. It GETs
  `https://doi.org/<doi>` with the CSL-JSON `Accept` header (the existing
  `http.get_json` already takes a `headers` argument) and maps the CSL-JSON
  document to a `ScrollItem` the way `crossref.py` maps Crossref's JSON
  (`tests/test_csl.py`).

- **The source name stays `crossref`; provenance tells the truth.** Like the
  DataCite fallback (ADR 0045), identity is fixed at `add` time before the
  agency is knowable, so the source stays `crossref` and the id stays
  `crossref:<doi>`. A content-negotiated item records
  `provenance.adapter = "content-negotiation"` and
  `extraction_method = "doi-content-negotiation:csl+json"`, so which path
  served the metadata is honest even though the source column can't carry it.

- **Classification defaults to `paper`, honoring an explicit non-paper type.**
  The agencies reached *only* by content negotiation (JaLC, mEDRA, KISTI, OP,
  Airiti, CNKI) are scholarly-literature registries — the dataset/software
  repositories are DataCite's, caught on tier two — so `paper` is the honest
  default, matching Crossref. But CSL carries a `type`, recorded in
  `provenance.resource_type`, so a `dataset`/`software`/`figure` CSL type is
  redirected to `dataset`/`tool`/`media` rather than mislabeled (a small
  `_CSL_CATEGORIES` map in `classify.py`, the DataCite-resource-type pattern
  of ADR 0045 but with a `paper` default instead of "unclassified", justified
  by the scholarly nature of the post-DataCite agencies — `tests/test_csl.py`).

- **A misroute degrades, never mints a wrong scroll.** The resolver 404s an
  unregistered DOI and 406s an agency that can't serve CSL-JSON (both raise);
  a response that parses but lacks the CSL marks (`type`/`DOI`/`title`) raises
  a `FetchError` rather than producing a junk scroll — the
  validate-before-scroll posture of the Discourse and Mastodon adapters
  (ADR 0054, ADR 0049).

## Consequences

- A saved DOI from any registration agency now becomes a clean, structured
  scroll — title, authors, venue, date, abstract-as-summary, subjects as
  concepts — instead of a failed fetch or a `web` scrape. The DOI coverage
  gap closes comprehensively, not one agency at a time.

- A long-tail DOI pays two wasted requests (a Crossref 404 and a DataCite
  404) before content negotiation answers — the same "try the common agency
  first" trade ADR 0045 accepted for the DataCite tier, and the PieFed
  one-wasted-request trade of ADR 0053. Crossref and DataCite DOIs, the
  overwhelming majority, are unaffected. A DOI-RA pre-lookup
  (`doi.org/doiRA/<doi>`) that routes directly would add a request to the
  *common* case to save two in the rare one — the wrong trade, and it was
  rejected for the same reason ADR 0045 rejected it for tier two.

- Content negotiation also serves Crossref and DataCite DOIs (the resolver
  proxies to their CN servers too), so the third tier doubles as a graceful
  degradation if a rich agency's REST API has a transient outage but its CN
  server is up — a bonus, never a regression, since the rich adapters win
  first when healthy.

- `provenance.adapter` now takes a third value (`content-negotiation`)
  alongside `crossref` and `datacite` for the one `crossref` source — the
  one-source-many-adapters shape of ADR 0045, extended by one.

- Deferred: a DOI-RA lookup to route directly (the request-count trade above
  isn't worth it); per-agency adapters that would extract richer fields than
  CSL-JSON carries (CSL is a citation format — it has no full text, no
  reference graph, no funder data — but neither does the `web` scrape it
  replaces, and the scholarly-literature agencies expose little more); and
  CSL-JSON's `page`/`volume`/`issue`/`ISSN` bibliographic detail, kept in
  `raw_text` for a future structured render.
