# 0116: A cited DOI is not a work identity

Date: 2026-10-29

Status: accepted

Amends: [0069](0069-works-by-doi.md) (membership rule 2). Settles issue #22.

## Context

ADR 0069 clusters items into *works* by the DOI that names the work. Rule 2
makes an item a representation of work `D` when one of its `links` is a
`doi.org/D` URL. Its premise: "every paper adapter emits the published work's
DOI as exactly such a link." In June that was the only way a `doi.org` link
reached `links`.

ADR 0110 (2026-08-18) gave Wikipedia articles every link in their body,
citations included. From then on, any article citing a paper became a
"representation" of that paper.

The live library showed the cost on 2026-10-29:

- **185 works, every one Wikipedia-only.** "Neural network (machine
  learning)" and "Stochastic gradient descent" were one work because both
  cite the 1986 backprop paper (`10.1038/323533a0`).
- **A false hard alarm.** Five of those works read as at-risk (no copy both
  full and unmoved), so `doctor`'s posture verdict was `at_risk` when
  nothing was lost.
- **False identity edges.** `related` scored those articles `same work`, and
  `kb` compiled 185 work pages from them.

Fixture tests could not see it. No fixture held a non-paper item that links
a DOI, and one test (`test_one_item_can_belong_to_two_works`) pinned a
citing review as a member of both works it cited.

## Decision

**A `doi.org` link names an item's work only when the item's source is a
scholarly record.** Those sources are declared in one allow-list,
`works.WORK_SOURCES`: `arxiv`, `biorxiv`, `medrxiv`, `crossref`, `pubmed`,
`rfc`, `zenodo`. Their adapters emit DOIs on purpose: the published version,
the record's own or concept DOI. Crossref and RFC already drop reference
lists for this reason ("references are not links", ADR 0037).

- **Rule 1 is unchanged.** An item whose `source_id` is itself a DOI is that
  work, whatever its source.
- **Every other source's `doi.org` link is a citation.** It stays in
  `links`, so `graph` edges and `related`'s "links to it" are untouched. It
  just names no work.
- **An allow-list, not a deny-list.** A new adapter that harvests links from
  a page cannot forge works by default. A new scholarly adapter joins the
  list deliberately; a test keeps the list inside `FETCH_ADAPTERS`.
- **One choke point.** `works.item_dois` applies the rule, and every
  consumer reads it: `works`, `related`'s same-work edge, `doctor`'s
  at-risk works and posture, `kb` work pages, MCP, and bundles.

## Consequences

- **Verified on a copy of the live library:** `works` reports 0 works
  where it reported 185. The posture verdict drops from `at_risk` to
  `attention`, its one remaining reason being `source_drift` (55 drifted
  articles).
- **The two-works case is still covered**, by a preprint published under two
  DOIs, which is the real shape of an item in two works.
- **Not changed:** a Zenodo or DataCite record's related-identifier DOIs
  still join works, as 0069 intended for supplements and versions. If that
  proves too loose, it is a separate decision.

Tests: `tests/test_works.py`, `tests/test_related.py`.
