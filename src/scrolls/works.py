"""Scholarly works clustered by shared DOI (ADR 0069).

The library now holds four paper sources that feed `doi.org` edges — arXiv
preprints (ADR 0038), Crossref/DataCite registered works (ADR 0037/0045),
PubMed records (ADR 0065), and bioRxiv/medRxiv preprints (ADR 0068) — plus
RFCs (ADR 0066), each of which carries the DOI of the work it represents.
So one scholarly work can sit in the library as several near-duplicate
`paper` entries: a preprint, its published article, an indexing record.

This module groups those representations into *works*, keyed by the DOI
that names the work. A work is the FRBR sense of the term (Crossref and
OpenAlex use it the same way): the abstract creation, of which the arXiv
preprint and the published article are *manifestations*.

Where `scrolls graph` (ADR 0044) clusters by *realized link edges* — two
items connect only when a link in one resolves to the other's identity, so
the binding Crossref hub item must itself be in the library — `works`
clusters by *shared DOI identity*. An arXiv preprint and a PubMed record
that both name `doi.org/D` are the same work even when no `crossref:D` item
is present: their links resolve to a URL token no item owns, so the graph
draws no edge between them, yet the DOI binds them here. When the hub *is*
present the two views coincide; `works` is the semantically correct lens
for "the same scholarly work", catching clusters the link graph cannot.

A representation contributes a work DOI in two ways, the same DOI plumbing
the rest of the system uses:

- its `source_id` is itself a DOI (`10.<registrant>/<suffix>`) — true for
  `crossref` items (the DOI folded lowercase, ADR 0037) and for
  `biorxiv`/`medrxiv` items (the `10.1101/<accession>` preprint DOI,
  ADR 0068), and naturally false for arXiv/PubMed/RFC integer ids; or
- one of its `links` is a `doi.org` URL — every paper adapter emits the
  published work's DOI as exactly such a link, and source detection reads
  the lowercased DOI back off it (`detect_source`, the same resolution
  `scrolls graph` and `scrolls related` use, ADR 0023).

Only works with two or more representations are reported by default — a
single-representation work is just a paper, with nothing to consolidate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scrolls.custody import (
    CustodyEvent,
    drift_posture,
    last_checked,
    tally_custody,
    tally_custody_by_source,
)
from scrolls.items import ScrollItem, get_fidelity, list_items
from scrolls.sources.detect import detect_source
from scrolls.sources.urls import normalize_url

DOI_RESOLVER = "https://doi.org"

# A single-representation "work" is just a paper; the default only reports
# works actually worth consolidating (2+ representations).
DEFAULT_MIN_REPRESENTATIONS = 2

# A DOI is `10.<registrant>/<suffix>`; the registrant is 4+ digits and the
# suffix is non-empty (the DOI Handbook §2.2). The same shape `detect.py`
# uses to read a DOI off a doi.org URL — kept here as a local copy so a
# work key never depends on the detector's internal regex.
_DOI_RE = re.compile(r"^10\.\d{4,}/.+$")

# Paper-source precedence for picking a work's *canonical* representation —
# the one form that stands for the whole work (ADR 0095). The registered
# published work (crossref) ranks first, then the indexed published record
# (pubmed), then the preprint servers (biorxiv/medrxiv/arxiv), then the
# standards track (rfc): published over pre-publication. A work's
# representations usually share a title, so the exact order rarely changes
# what an agent sees; the point is a single deterministic choice every
# surface agrees on. Sources outside this map rank last, ties broken by id.
# `kb.py`'s category-page consolidation (ADR 0071) reads `Work.canonical`
# instead of re-deriving this, so the rank lives here, with the work model.
CANONICAL_SOURCE_RANK = {
    "crossref": 0,
    "pubmed": 1,
    "biorxiv": 2,
    "medrxiv": 3,
    "arxiv": 4,
    "rfc": 5,
}
_RANK_OTHER = len(CANONICAL_SOURCE_RANK)


@dataclass(frozen=True)
class Representation:
    """One item that represents a work — the node shape graph/related use.

    Carries the item's custody `fidelity` tier (full/partial/reference,
    ADR 0097/0100) alongside the same fields graph nodes and related hits do,
    so an agent reading a work sees which of its representations the library
    holds in full and which only by reference — the published DOI record may be
    a bare pointer while the preprint is fully held, or vice versa.

    The item-intrinsic `fidelity` lives on the dataclass; the per-representation
    custody **drift posture** and **last_checked** timestamp (which need the verify
    ledger) are added in `to_payload` from the passed-in `verdicts`, not stored
    here — the H56 graph-node split, so a reader of a multi-representation work
    sees the full per-item custody picture per form: *how much* is held (fidelity),
    *whether the source moved* (drift, roadmap H64), and *as of when* (last_checked,
    roadmap H87).
    """

    id: str
    source: str
    title: str | None
    url: str
    stage: str
    fidelity: str


@dataclass(frozen=True)
class Work:
    """A scholarly work and the saved items that represent it.

    `doi` is the lowercased DOI that names the work and `url` its canonical
    `https://doi.org/<doi>` resolver link. `representations` are the items
    bound to it, sorted by id. `canonical` is the one representation that
    stands for the whole work (ADR 0095) — the published record over a
    preprint by `CANONICAL_SOURCE_RANK` — and is always one of
    `representations` (a single-representation work is its own canonical).
    """

    doi: str
    url: str
    representations: tuple[Representation, ...]
    canonical: Representation


@dataclass(frozen=True)
class WorkRef:
    """One item's membership in a multi-representation work — the compact form
    that travels with a browse hit (search, list), the way the custody
    `fidelity` tier does (ADR 0100).

    Where `Work` is the whole cluster with every representation, a `WorkRef` is
    the single-item view: this item is one of `representations` saved forms of
    the work named by `doi`, whose canonical representation (ADR 0095) is the
    item with id `canonical`. `is_canonical` says whether *this* item is that
    canonical one, so a search result can flag "you found the preprint; the
    published record `crossref:…` is the canonical form" without the agent
    re-deriving the clustering. Compact by design: an agent that wants the full
    representation set asks `scrolls works --ref <id>` / `get_works(item=…)`.
    """

    doi: str
    url: str
    canonical: str
    is_canonical: bool
    representations: int


def find_works(
    db_path: Path, *, min_representations: int = DEFAULT_MIN_REPRESENTATIONS
) -> list[Work]:
    """Cluster the library's items into works by shared DOI.

    A missing database (uninitialized library) yields no works. Works with
    fewer than `min_representations` members are dropped — the default of 2
    keeps only the works actually worth consolidating.
    """
    items = list_items(db_path) if db_path.exists() else []
    return works_over(items, min_representations=min_representations)


def works_over(
    items: list[ScrollItem], *, min_representations: int = DEFAULT_MIN_REPRESENTATIONS
) -> list[Work]:
    """Cluster a given set of items into works by shared DOI.

    `find_works` loads the whole library and calls this; a future KB page
    can pass only its rendered items. Works are ordered by representation
    count descending, then by DOI, so the output is stable run to run;
    within a work, representations sort by id.
    """
    # doi → {item id: item}, an inner dict so a representation that names a
    # DOI twice (a duplicate link) counts once, in first-seen (oldest) order.
    by_doi: dict[str, dict[str, ScrollItem]] = {}
    for item in items:
        for doi in item_dois(item):
            by_doi.setdefault(doi, {})[item.id] = item

    works = []
    for doi, members in by_doi.items():
        if len(members) < min_representations:
            continue
        reps = tuple(
            sorted(
                (_representation(item) for item in members.values()),
                key=lambda rep: rep.id,
            )
        )
        works.append(
            Work(
                doi=doi,
                url=f"{DOI_RESOLVER}/{doi}",
                representations=reps,
                canonical=_canonical(reps),
            )
        )
    works.sort(key=lambda work: (-len(work.representations), work.doi))
    return works


def works_for_item(items: list[ScrollItem], item_id: str) -> list[Work]:
    """The work(s) the item with `item_id` represents, with every representation.

    The per-item lens on the same clustering `works_over` computes for the
    whole library — `find_related` is to `build_graph` as this is to
    `works_over`: an agent that found one representation (a search hit, a
    scroll) asks which work it is and which *sibling* representations are
    also saved. The work(s) are keyed by the DOIs the item carries (its
    `source_id` DOI or its `doi.org` links) and clustered over the whole
    given `items` set with *all* their representations, the target included.

    Unlike `works_over`'s 2+ default, a work is reported even with a single
    representation — just the target itself — so "what work is this, and what
    siblings are saved" has an explicit answer ("none") when no other item
    shares the DOI. An item that names no DOI yields no works. Raises
    ValueError when no item in `items` has `item_id`, mirroring
    `find_related` (`tests/test_works.py`).
    """
    target = next((item for item in items if item.id == item_id), None)
    if target is None:
        raise ValueError(f"no such item: {item_id}")
    target_dois = item_dois(target)
    if not target_dois:
        return []
    # cluster over the whole set with no floor (min 1), then keep the works
    # the target itself contributes a DOI to — every such work includes the
    # target by construction, in works_over's representation-count-then-DOI order
    return [
        work
        for work in works_over(items, min_representations=1)
        if work.doi in target_dois
    ]


def work_membership(
    items: list[ScrollItem], *, min_representations: int = DEFAULT_MIN_REPRESENTATIONS
) -> dict[str, tuple[WorkRef, ...]]:
    """Index each item id to the multi-representation work(s) it belongs to.

    The browse-surface counterpart to `works_over`: that clusters the library
    into works; this inverts the clustering to a per-item lookup so `scrolls
    search` and `scrolls list` can annotate every hit with the work it
    represents and which form is canonical — one shared clustering, not one
    re-derived per surface. An item appears only when it belongs to a work with
    at least `min_representations` members (default 2); items that name no DOI,
    or whose DOI no sibling shares, are absent, and callers default a missing id
    to an empty tuple — "this is not (yet) a known duplicate of anything saved".

    An item that names two DOIs can be a representation of two works, so the
    value is a tuple, in the order `works_over` emits the works (representation
    count descending, then DOI — stable run to run), mirroring `works_for_item`'s
    list rather than forcing a single membership.
    """
    membership: dict[str, list[WorkRef]] = {}
    for work in works_over(items, min_representations=min_representations):
        count = len(work.representations)
        for rep in work.representations:
            membership.setdefault(rep.id, []).append(
                WorkRef(
                    doi=work.doi,
                    url=work.url,
                    canonical=work.canonical.id,
                    is_canonical=rep.id == work.canonical.id,
                    representations=count,
                )
            )
    return {item_id: tuple(refs) for item_id, refs in membership.items()}


def membership_payload(refs: tuple[WorkRef, ...]) -> list[dict]:
    """A browse hit's `works` field: its `WorkRef`s as JSON dicts (`[]` if none).

    Shared by `scrolls search`, `scrolls list`, and their MCP twins so the
    work-membership a hit carries has one shape across every browse surface
    (the same single-definition discipline `item_summary` keeps for the rest of
    a summary row).
    """
    return [
        {
            "doi": ref.doi,
            "url": ref.url,
            "canonical": ref.canonical,
            "is_canonical": ref.is_canonical,
            "representations": ref.representations,
        }
        for ref in refs
    ]


def to_payload(
    works: list[Work],
    item_count: int,
    *,
    scope: dict[str, Any],
    verdicts: dict[str, CustodyEvent] | None = None,
) -> dict:
    """Works as the JSON object the CLI and MCP tool both emit.

    `stats.items` is the library total (the denominator the works count is
    against), `stats.works` the number reported — the same `stats` shape
    `scrolls graph` uses. `canonical` names the work's canonical
    representation by id (ADR 0095), a pointer into its own `representations`
    so a consumer can highlight the one form that stands for the work.

    Each representation carries the per-item custody picture: its item-intrinsic
    `fidelity` tier (how much is held, ADR 0100), its `drift` posture (whether the
    source moved — `custody.drift_posture` over its latest `verdicts` entry,
    roadmap H64), and `last_checked` (as of when — `custody.last_checked` over the
    *same* verdict, `null` when never re-checked, roadmap H87). So a reader of a
    multi-representation work sees not just which form the library holds in full
    but which have drifted *and as of when* — the custody signal for "prefer the
    canonical, but note it drifted (last seen <date>)". The same
    `drift_posture`/`last_checked` over `latest_events` every other per-item surface
    reads (list, search, related, graph, show), so a representation's posture and
    timestamp agree with that item's `list` row by construction. `verdicts` is the
    `latest_events` ledger read the CLI/MCP pass; absent (the pure caller), every
    representation reads `unverified`/`null` — honest, nothing has been checked.

    `scope` echoes what the call was scoped to — the `min_representations`
    floor for the whole-library clustering, or the `ref` anchor for the
    per-item lens — so a reader holding *only* this payload can recover it
    (completeness contract G2, `docs/cli.md`). A `None` value is pruned the
    way `scope.scope_envelope` prunes search/list/related, so the echoed
    scope names exactly what was applied and never a facet the call left open
    — the per-item lens ignores the floor, so its scope carries `ref` alone.
    Unlike a capped browse result, `works` is uncapped (every work at or above
    the floor is reported), so the floor *is* the truncation story: a work
    missing from the payload was below the reported floor, not absent from the
    library, and `stats` already counts what cleared it.

    `stats.custody` is the works-surface member of the `stats.custody` family
    (roadmap H100, beside the browse `search`/`list`/`related --stats` envelopes
    H98/H99 and the `graph` stats block H52): the shared `custody.tally_custody`
    fidelity-tier and drift-posture count maps over the **reported works'
    representations** — the same `(fidelity, drift)` pairs each representation
    entry above already exposes — so a reader of the works lens sees "of the
    multi-representation works in scope, how much is held in full and how much
    drifted" without a second `facets` call. It is scoped to the *representation
    entries* (not the library `stats.items`, the works count denominator), so its
    totals equal the rendered representation entries by construction; an item that
    represents two works contributes to both, exactly as it is rendered twice. No
    new ledger read — the same `verdicts` the per-rep `drift` already folds.

    `stats.custody.by_source` (roadmap H155) splits that representation-scoped tally
    per source — `custody.tally_custody_by_source` over the same
    `(source, fidelity, drift)` rep triples, a `{source: {tiers, drift}}` map (sorted
    keys) — the works-surface counterpart of the per-source split on the browse
    `search`/`list`/`related --stats` envelopes and the `graph` stats block (H150).
    It sums to the whole `stats.custody` block beside it by construction (every rep
    lands in exactly one source group). An empty scope is the honest empty `{}`.
    """
    verdicts = verdicts or {}
    # `stats.custody` over the reported works' representations (roadmap H100), and its
    # per-source split (roadmap H155): the same `(source, fidelity, drift)` each rep
    # entry above exposes, grouped by source, so the split sums to the whole-scope
    # tally beside it and adds no ledger read beyond the per-rep `drift` already folds.
    custody = tally_custody(
        (rep.fidelity, drift_posture(verdicts.get(rep.id)))
        for work in works
        for rep in work.representations
    )
    custody["by_source"] = tally_custody_by_source(
        (rep.source, rep.fidelity, drift_posture(verdicts.get(rep.id)))
        for work in works
        for rep in work.representations
    )
    return {
        "scope": {key: value for key, value in scope.items() if value is not None},
        "works": [
            {
                "doi": work.doi,
                "url": work.url,
                "canonical": work.canonical.id,
                "representations": [
                    {
                        "id": rep.id,
                        "source": rep.source,
                        "title": rep.title,
                        "url": rep.url,
                        "stage": rep.stage,
                        "fidelity": rep.fidelity,
                        "drift": drift_posture(verdicts.get(rep.id)),
                        "last_checked": last_checked(verdicts.get(rep.id)),
                    }
                    for rep in work.representations
                ],
            }
            for work in works
        ],
        "stats": {
            "items": item_count,
            "works": len(works),
            "custody": custody,
        },
    }


def _canonical(representations: tuple[Representation, ...]) -> Representation:
    """The representation that stands for the whole work (ADR 0095).

    Picked by `CANONICAL_SOURCE_RANK` — the registered published record over a
    preprint — with the item id as a deterministic tiebreak, so the choice is
    stable run to run and identical to the one `kb.py`'s page consolidation
    once derived inline. `representations` is non-empty by construction (a work
    has at least one representation).
    """
    return min(
        representations,
        key=lambda rep: (CANONICAL_SOURCE_RANK.get(rep.source, _RANK_OTHER), rep.id),
    )


def item_dois(item: ScrollItem) -> set[str]:
    """The DOIs that name the work(s) this item represents.

    The item's own `source_id` when it is itself a DOI (crossref,
    biorxiv/medrxiv), plus the DOI of every `doi.org` link it carries.

    Public so `related` can score a *same-work* edge with the same
    DOI-extraction rule the work clustering uses — an item is a sibling
    representation of another exactly when they share one of these DOIs.
    """
    dois: set[str] = set()
    if item.source_id and _DOI_RE.match(item.source_id):
        dois.add(item.source_id.lower())
    for link in item.links:
        doi = _doi_from_link(link)
        if doi:
            dois.add(doi)
    return dois


def _doi_from_link(link: str) -> str | None:
    """The lowercased DOI a `doi.org` link names, or None.

    Resolution goes through `detect_source` — the same normalize-then-detect
    path `scrolls graph` resolves links with (ADR 0023) — which maps a
    `doi.org`/`dx.doi.org` URL to a `crossref` source with the DOI, folded
    lowercase, as its `source_id` (ADR 0037).
    """
    try:
        detected = detect_source(normalize_url(link))
    except ValueError:
        return None
    if detected.source == "crossref" and detected.source_id:
        return detected.source_id
    return None


def _representation(item: ScrollItem) -> Representation:
    return Representation(
        id=item.id,
        source=item.source,
        title=item.title,
        url=item.url,
        stage=item.stage,
        fidelity=get_fidelity(item),
    )
