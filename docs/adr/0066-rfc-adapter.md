# ADR 0066: RFC adapter — IETF standards, keywords as concepts, DOI and obsoletes/updates as edges

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

Scrolls now covers repos (four code hosts), packages (six registries), papers
(arXiv, Crossref, PubMed, DataCite), discussion (Hacker News, Lobsters, the
Fediverse aggregators, Discourse), and social posts (Bluesky, Mastodon, Misskey)
— but one content type a coding or research agent reaches for constantly had no
first-class home: **technical standards**. The normative protocol specifications
an agent cites every day — HTTP (RFC 9110), TLS (RFC 8446), JSON (RFC 8259),
OAuth (RFC 6749), URI syntax (RFC 3986) — are IETF **RFCs**, and a saved RFC link
fell through to the generic `web` adapter (ADR 0001). `trafilatura` would scrape
the spec's text, but the record's *structure* was lost: its curated keywords (the
high-signal `concepts` source the KB graph wants), its maturity status, its DOI,
and — most distinctively — its **obsoletes/updates relations**, the standards
lineage that connects one RFC to the ones it supersedes. An RFC `web` scroll was a
concept-poor, unlinked island, the same gap PubMed had before ADR 0065 and dev.to
had before ADR 0061.

The RFC Editor publishes this structure keyless. A single
`GET https://www.rfc-editor.org/rfc/rfc<N>.json` returns the whole bibliographic
record — title, authors/editors, abstract, publication date, keywords, status,
DOI, and the `obsoletes`/`updates`/`obsoleted_by`/`updated_by` relation arrays —
as JSON parsed with stdlib `json`, no auth and no runtime dependency (the arXiv/
Crossref discipline, ADR 0008/0037). The adapter contract (ADR 0002) and the paper
adapters make this a near-template build; the value is in three platform facts and
two cross-document edges.

## Decision

Add `rfc`, a keyless fetch adapter for IETF Requests for Comments.

1. **Identity is the integer RFC number; detection is host-restricted shape
   matching.** `rfc:9110`, the accession number with leading zeros stripped, so
   the canonical `rfc9110` and the zero-padded filename form `rfc0020` dedupe to
   `rfc:20`. RFCs are reachable across several hosts and shapes — the RFC Editor's
   `rfc-editor.org/rfc/rfc<N>[.txt|.html]` and `/info/rfc<N>`, the IETF
   `datatracker.ietf.org/doc/rfc<N>/` and `/doc/html/rfc<N>`, the legacy
   `tools.ietf.org/html/rfc<N>`, and `ietf.org/rfc/rfc<N>.txt` — so detection
   scans the path for an `rfc<digits>` segment. But these hosts **also serve
   Internet-Drafts, working-group pages, and the org site**, so the host is *not*
   claimed wholesale: only the `rfc<digits>` shape detects as `rfc`, and every
   other path (a `/doc/draft-ietf-…` draft, a `/wg/…` page) falls through to
   `web`. This is the shared-NCBI-host posture of ADR 0065 — host in a set *and* a
   shape required — not github's wholesale-host claim. The fetch adapter reads the
   RFC Editor's JSON view regardless of which host the saved URL named.

2. **Keywords are the concepts; the status is the controlled-facet tag.** The RFC
   Editor's curated `keywords` (`Hypertext Transfer Protocol`, `HTTP semantics`)
   become `concepts`, joining github topics, arXiv taxonomy names, and MeSH
   descriptors in the KB concept graph (ADR 0007/0012/0065). Many RFCs carry none
   — older records store a single whitespace-only placeholder (`["  "]`), dropped
   like an empty value — so a keyword-less RFC is honestly concept-light rather
   than carrying noise. The maturity `status` (`PROPOSED STANDARD`,
   `INTERNET STANDARD`, `INFORMATIONAL`, `BEST CURRENT PRACTICE`, `EXPERIMENTAL`,
   `HISTORIC`) is the controlled vocabulary Crossref's `type` and arXiv's taxonomy
   fill (ADR 0037/0008): it becomes the one `tag`, title-cased from the API's
   upper-case form (`Internet Standard`) for a readable KB tag page.

3. **The abstract is the content; there is no full text.** An RFC's body is
   published separately (the `.txt`/`.html` a reader opens); the JSON view carries
   only the abstract, so it is the searchable `summary` with **no
   `extracted_text`** — the metadata-only shape of Crossref and PubMed
   (ADR 0037/0065). A record with no abstract degrades to a metadata-only scroll
   (ADR 0002), not a `FetchError`. Fetching the spec text itself (the `.txt`) as
   `extracted_text` is a clean future enrichment, the arXiv/PDF split.

4. **The DOI is the RFC↔Crossref edge.** Every modern RFC is registered with a
   DOI (`10.17487/RFC<N>`) through Crossref, exposed as the record's `doi`. It
   becomes a single `https://doi.org/<doi>` link, which resolves through source
   detection to the `crossref:<doi>` item a saved DOI mints — wiring an RFC to its
   published Crossref scroll. This is the **biomedical-edge pattern of ADR 0065
   applied to standards**, kin to arXiv's preprint↔published edge (ADR 0038).

5. **Obsoletes/updates are the RFC↔RFC standards-lineage edges; the inverse
   relations are not re-emitted.** Each `obsoletes` and `updates` target
   (`RFC7230`, `RFC3864`) becomes an `rfc-editor.org/rfc/rfc<M>` link, which
   resolves through detection to that RFC's `rfc:<M>` item — so a saved RFC 9110
   wires to the RFCs it supersedes when they too are in the library. The inverse
   `obsoleted_by`/`updated_by` relations are **deliberately omitted**: each is the
   exact mirror of some other RFC's `obsoletes`/`updates`, and the link graph
   resolves edges in both directions (`related`/`graph`), so re-emitting them
   would only add links pointing at RFCs that aren't in the library — the Crossref
   "references are not links" economy (ADR 0037). The RFC number leads the title
   (`RFC 9110: HTTP Semantics`) and the scroll slug because an RFC's canonical name
   *is* its number — agents search "RFC 9110" — so the number belongs in the
   FTS-weighted title, not only the id. Publication dates are `Month Year`
   (`June 2022`), parsed locale-independently and padded to the first of the month
   (ADR 0024's uniform-shape rule). An RFC classifies as `reference` (ADR 0004),
   the normative-spec sibling of a Wikipedia article — used as a spec to consult,
   not a paper to cite.

## Consequences

- A saved RFC now joins the concept graph (via keywords), the link graph (via its
  DOI → Crossref and its obsoletes/updates → other RFCs), and the `reference`
  facet, instead of sitting as a `web` island. Re-adding a URL previously saved as
  `web` mints a *different* id (`rfc:<N>` vs `web:<hash>`), so the two do not
  auto-merge — acceptable, like dev.to/PubMed (ADR 0061/0065); the `web` copy can
  be `scrolls rm`'d. This is not a pre-normalization duplicate, so `scrolls doctor`
  (ADR 0026) is not involved.
- The standards-lineage edges make a library of related RFCs navigable: saving
  RFC 9110 and the RFC 723x series it obsoletes produces a cluster in
  `library/graph.md` and mutual `related` hits, the same shape arXiv↔Crossref and
  the package↔repo edges produce.
- Sub-series documents (`STD`, `BCP`, `FYI`) and Internet-Drafts are out of scope:
  STD/BCP map to one *or more* RFCs (`see_also` carries `STD0097`) and a draft is
  not yet an RFC. They stay `web` for now; a future `std`/`bcp` grouping or a draft
  adapter would be a clean extension. The originating stream/working group
  (`source`) is not yet a tag or concept — `status` is the one clear facet; adding
  the WG as a second tag is a small future enrichment.
- No `tool`/`email` query param or API key is wired — the RFC Editor serves the
  JSON view without throttling concerns for `scrolls add`/`ingest`. A heavy bulk
  run would want the `--limit` pacing every adapter shares.

## Proof

`src/scrolls/sources/rfc.py` with transport-faked tests (`tests/test_rfc.py`, the
fixture trimmed from the real RFC Editor JSON for RFC 9110, *HTTP Semantics*, June
2022, DOI 10.17487/RFC9110): the core metadata mapping and `RFC <N>: <title>`
title with its number-only fallback, the editor byline rendering and truncation,
the keywords-as-concepts join (whitespace placeholder and duplicates dropped), the
title-cased status tag (and the honestly-empty case), the abstract-as-`summary`
semantics with no `extracted_text` (and the metadata-only and whitespace-abstract
degrades), the DOI → `doi.org` cross-source link, the obsoletes/updates → rfc
links (zero-padded numbers normalized, inverse relations not emitted), the
`Month Year` and bare-year date parsing, identity/URL preservation, the requested
JSON URL, and the missing-number / non-record / request-failed `FetchError`s — all
offline (ADR 0001). Detection is pinned in `tests/test_detect.py` (the RFC Editor,
datatracker, and legacy tools/ietf hosts and shapes; zero-padded dedupe; drafts,
working-group, and org pages falling through to `web`; the shape on an unknown host
not claimed), the `rfc → reference` rule in `tests/test_classify.py`
(`test_rfc_classifies_as_reference`), and the `FETCH_ADAPTERS["rfc"]` registration
in `test_registered_in_fetch_adapters`.

RFC data sourced from the RFC Editor; the fixture RFC's DOI is
[10.17487/RFC9110](https://doi.org/10.17487/RFC9110).
