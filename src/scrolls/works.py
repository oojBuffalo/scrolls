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

from scrolls.items import ScrollItem, list_items
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
    """One item that represents a work — the node shape graph/related use."""

    id: str
    source: str
    title: str | None
    url: str
    stage: str


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


def to_payload(works: list[Work], item_count: int) -> dict:
    """Works as the JSON object the CLI and MCP tool both emit.

    `stats.items` is the library total (the denominator the works count is
    against), `stats.works` the number reported — the same `stats` shape
    `scrolls graph` uses. `canonical` names the work's canonical
    representation by id (ADR 0095), a pointer into its own `representations`
    so a consumer can highlight the one form that stands for the work.
    """
    return {
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
                    }
                    for rep in work.representations
                ],
            }
            for work in works
        ],
        "stats": {"items": item_count, "works": len(works)},
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
    )
