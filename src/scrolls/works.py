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
    DRIFT_POSTURES,
    FIDELITY_TIERS,
    SAFE_DRIFT_POSTURES,
    CustodyEvent,
    drift_posture,
    last_checked,
    tally_custody,
    tally_custody_by_source,
    weakest_source,
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

    `content_hash` — the item's captured-content fingerprint (the column
    `items.content_duplicate_groups` keys on, H325) — also rides the dataclass, the
    same item-intrinsic-content posture `fidelity` takes: it lets the work-level
    `work_content_duplicate` fold (roadmap H329) ask "do two of this work's forms
    hold the *same bytes*?" without a second item read. `None` for a reference-only
    representation (nothing captured), so it never reaches a JSON surface — it feeds
    the boolean fold alone, the H56 split (an intrinsic fact carried, not re-read).
    """

    id: str
    source: str
    title: str | None
    url: str
    stage: str
    fidelity: str
    content_hash: str | None


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


def filter_works(
    works: list[Work],
    verdicts: dict[str, CustodyEvent] | None = None,
    *,
    fidelity: str | None = None,
    drift: str | None = None,
    at_risk: bool = False,
    content_duplicate: bool = False,
) -> list[Work]:
    """Keep only the works matching the given custody scope(s).

    The custody-filter family on the **consolidation** surface (roadmap H262): the
    family scoped each per-*item* custody axis (fidelity, drift) on every read, act,
    and export surface (H250–H260); this lifts the same per-item predicate to the
    *work* — the cluster of representations the family never reached. The **contains**
    semantics for `fidelity`/`drift`: a work is kept *whole* (every representation
    still travels) iff it has **at least one representation** that matches, since a
    work is a set of forms and the natural read of "show me the works with a drifted
    representation" wants the *work* and all its siblings — so a reader can see whether
    a safe sibling exists — not the lone matching form. So `--drift drifted` surfaces
    *the works needing a recapture decision*, their whole representation set intact.

    Folds the **same** per-rep custody every other works surface reads — the
    item-intrinsic `Representation.fidelity` and `drift_posture` over the `verdicts`
    ledger `to_payload`'s per-rep `drift` folds — so a work is kept by exactly the
    values its representations show. The `fidelity`/`drift` axes AND **on the same
    representation**, the ∃-lift of the per-item filter (`filter_related`'s "no
    neighbour is *both*", H254): `fidelity="full"`/`drift="drifted"` keeps a work iff
    some representation is *both* full *and* drifted — a fully-held copy whose source
    moved, the recapture candidate where the content is in hand — not merely some full
    rep and some (possibly different) drifted rep. An unknown tier/posture outside the
    closed vocabulary (`FIDELITY_TIERS`/`DRIFT_POSTURES`) raises ValueError, so a typo
    is a loud could-not-check (G1), exactly as `filter_related` and the CLI `choices=`
    (exit 2) reject one.

    `content_duplicate` is the **content-identity browse predicate** (roadmap H344):
    when ``True`` it keeps only the works that **hold the same bytes under two
    representations** — the H329 `work_content_duplicate` flag (≥2 reps share a non-null
    `content_hash`) turned into a sieve, the consolidation analogue of `list
    --content-duplicate` (H338). It is the **within-work** scope the flag already carries
    (the H329 consolidation discipline): a work is kept iff *its own* representations
    duplicate each other, so a cross-source content pair that forms no work is never kept
    here — distinct from `list --content-duplicate`'s whole-library sibling scope, which
    keeps an item whose byte-identical twin lives *anywhere*. Like `at_risk` it is a
    boolean property, not a vocabulary value, and reads no ledger (`content_hash` is
    item-intrinsic, carried on the `Representation`), so it composes with — **ANDs** with
    — the contains-axes and `at_risk` over the same already-clustered works. Report-only,
    names no merge (the H325 raw-is-sacred discipline; content-identity across forms is
    custody-distinct provenance, never a fabricated act).

    `at_risk` is the **at-risk browse predicate** (roadmap H265): when ``True`` it
    keeps only the works **no representation safely holds** — the H261 `work_custody`
    `safely_held == False` set the H263 alarm counts (no copy is both `full` *and*
    unmoved anywhere in the cluster). It is a genuinely new predicate, *not* a
    fidelity/drift value: "no rep is safely held" is the **negation of ∃(full ∧
    safe)**, so it cannot be expressed as a single per-rep `fidelity`/`drift` filter,
    the consolidation analogue of `list --drift`. It **ANDs** with the contains-axes:
    `at_risk=True, fidelity="full"` keeps the at-risk works that *also* hold a full
    rep — the recapture candidates whose content is in hand but whose work is still at
    risk (the full copy drifted). The predicate is the same `work_custody` fold the
    aggregate `custody` block and `at_risk_signal` read, so a work is browsed by
    exactly the verdict it shows.

    Pure over the already-clustered works (the `filter_related` shape): cluster first
    (`works_over`/`works_for_item`), sieve here, *then* `to_payload`. Because whole
    works are kept (no representation is pruned), the sieve commutes with the
    `min_representations` floor `works_over` already applied, and `to_payload`'s
    `stats.custody` — folded over the reported works' representations — partitions
    exactly the kept set with no change. `verdicts` is the `latest_events` ledger read
    keyed by item id; absent (no `--drift`/`--at-risk`), every representation reads
    `unverified` (and a never-checked full copy is safely held — the M2 honesty).
    """
    if fidelity is not None and fidelity not in FIDELITY_TIERS:
        raise ValueError(
            f"unknown fidelity tier {fidelity!r}; "
            f"choose one of {', '.join(FIDELITY_TIERS)}"
        )
    if drift is not None and drift not in DRIFT_POSTURES:
        raise ValueError(
            f"unknown drift posture {drift!r}; "
            f"choose one of {', '.join(DRIFT_POSTURES)}"
        )
    if fidelity is None and drift is None and not at_risk and not content_duplicate:
        return works
    verdicts = verdicts or {}
    return [
        work
        for work in works
        if (
            not at_risk
            or not work_custody(work.representations, verdicts)["safely_held"]
        )
        and (
            not content_duplicate
            or work_content_duplicate(work.representations)
        )
        and any(
            (fidelity is None or rep.fidelity == fidelity)
            and (drift is None or drift_posture(verdicts.get(rep.id)) == drift)
            for rep in work.representations
        )
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


def work_custody(
    representations: tuple[Representation, ...],
    verdicts: dict[str, CustodyEvent],
) -> dict[str, Any]:
    """The aggregate custody posture of a work — its representations *consolidated*.

    The new custody *shape* (vision §3.5, custody-vision §2.7, roadmap H261): the
    custody-filter family made each per-*item* axis (fidelity, drift) readable
    everywhere, but a *work* is a cluster of representations and had no aggregate
    custody verdict. This folds the per-rep custody every other works surface
    already reads — the item-intrinsic `fidelity` on each `Representation` and the
    `drift_posture` over the *same* `verdicts` `to_payload`'s per-rep `drift` folds
    — into one work-level block, **no schema change, no extra ledger read**:

    - ``best_fidelity`` — the best (most complete) tier any representation holds,
      by the canonical `FIDELITY_TIERS` order (full > partial > reference): "what is
      the most re-derivable form of this work the library holds?"
    - ``safest_drift`` — the safest (most reassuring) drift posture any
      representation carries, by the canonical `DRIFT_POSTURES` order (verified >
      unverified > drifted > rotted > error): "what is the least-moved form?"
    - ``safely_held`` — the consolidation verdict: ``True`` iff **∃ a representation
      that is `full` *and* whose drift ∈ `SAFE_DRIFT_POSTURES`** ({verified,
      unverified}). An *unmoved, fully re-derivable* copy of the work exists somewhere
      in its cluster, so the work survives even if its other forms have degraded or
      drifted.

    The ``safely_held`` predicate is the **strong** form, resolving the one judgement
    the H261 spec flagged: a `partial` capture is missing content and so cannot fully
    re-derive the work offline — it is *not* a safe hold even when verified. And a
    `full` copy that has *drifted*/*rotted* (or could not be checked — *error*) is not
    safe either: the source has moved away from, or we cannot confirm it still matches,
    our capture. Both axes must hold on the *same* representation — a work with a
    drifted full preprint and a verified *partial* record is **not** safely held, since
    neither form is both full and unmoved. ``best_fidelity``/``safest_drift`` are
    picked *independently* across the cluster (the best on each axis, possibly from
    different reps), so they report what the work offers per axis without implying a
    single rep achieves both.

    `representations` is non-empty by construction (a `Work` has at least one), so the
    `min` picks never see an empty sequence. `verdicts` is the `latest_events` ledger
    read keyed by item id; absent (the pure caller), every representation reads
    `unverified`/safe, so a never-verified full copy is safely held — honest, no
    network. The shared primitive H262's `works --fidelity`/`--drift` filter and
    H263's at-risk-works signal reuse, so the consolidation rule keeps one home.
    """
    postures = [
        (rep.fidelity, drift_posture(verdicts.get(rep.id)))
        for rep in representations
    ]
    return {
        "best_fidelity": min(
            (fidelity for fidelity, _ in postures), key=FIDELITY_TIERS.index
        ),
        "safest_drift": min(
            (drift for _, drift in postures), key=DRIFT_POSTURES.index
        ),
        "safely_held": any(
            fidelity == "full" and drift in SAFE_DRIFT_POSTURES
            for fidelity, drift in postures
        ),
    }


def work_content_duplicate(representations: tuple[Representation, ...]) -> bool:
    """Does this work hold the *same bytes* under two representations? (roadmap H329).

    The consolidation-surface analogue of the whole-library
    `items.content_duplicate_groups` report (H325): where that fold flags
    byte-identical holdings anywhere in the library, this asks the question *within a
    work* — is one of this work's forms a byte-identical copy of another (a preprint
    mirrored into its DOI capture, a published record duplicating the arxiv body)? A
    redundancy an operator consolidating the work may want to know, the content
    sibling of the H261 `custody` block's aggregate posture, **no schema change** (a
    pure fold over the per-rep `content_hash` already carried on the dataclass).

    Returns ``True`` iff **≥2 representations share a non-null `content_hash`**. The
    H325 NULL-skip holds: a reference-only representation captures no content, so its
    ``None`` hash fingerprints nothing and never forms a byte-identical pair (two
    reference reps are not "the same bytes" — they hold no bytes). Report-only — never
    an act, never a merge (content-identity across forms is custody-distinct
    provenance; raw is sacred, the H325 no-fabricated-act discipline).

    A `Work` always has ≥1 representation, and a single representation never
    duplicates itself (it is one row, the first-seen-per-id `works_over` dedup), so a
    one-rep work is honestly ``False``.
    """
    seen: set[str] = set()
    for rep in representations:
        if not rep.content_hash:  # reference-only: no captured content to fingerprint
            continue
        if rep.content_hash in seen:  # a second rep holds these exact bytes
            return True
        seen.add(rep.content_hash)
    return False


def render_work_custody_marker(custody: dict[str, Any]) -> str:
    """One-line work-level custody marker for the compiled `works.md` rollup (H270).

    The works-page analogue of the per-item `· <fidelity> · <drift>` marker on the
    compiled list pages (`kb._custody_marker`): distils the H261 `work_custody`
    aggregate `{best_fidelity, safest_drift, safely_held}` into one readable line
    beneath a work's resolver line, so a human browsing `library/works.md` reads the
    same consolidation verdict an agent reads from `scrolls works`'s per-work
    `custody` block — which form is most re-derivable, which least moved, and whether
    *the work* is safely held — without opening the JSON:

        _Custody: best held <tier>, safest drift <posture> — safely held._
        _Custody: best held <tier>, safest drift <posture> — at risk._

    Takes the `work_custody` dict the JSON payload already carries (not the
    representations), so the compiled marker and the `scrolls works` `custody` block
    are two renders of the *same* fold — convergent by construction. The trailing
    clause is the H261 strong-form `safely_held` verdict (∃ a representation that is
    `full` *and* unmoved), the very predicate `at_risk_signal`'s alarm reads, so an
    at-risk work's marker here agrees with whether `index.md`'s `_At-risk work:_`
    line / `doctor`'s `custody.works` names it (the H269 compiled-surface
    convergence, now per-work).
    """
    verdict = "safely held" if custody["safely_held"] else "at risk"
    return (
        f"_Custody: best held {custody['best_fidelity']}, "
        f"safest drift {custody['safest_drift']} — {verdict}._"
    )


def at_risk_signal(
    works: list[Work],
    verdicts: dict[str, CustodyEvent],
) -> dict[str, Any]:
    """The *at-risk works* consolidation alarm — the works no representation safely holds.

    The consolidation-level custody signal (roadmap H263, vision §3.5): the
    per-source weakest-source `attention` flag (`custody.weakest_source`, H119) names
    the source carrying the most actionable per-*item* loss; this names the **works**
    carrying a *consolidation* loss — a work is **at risk** when **no** representation
    is *safely held* (the H261 `work_custody` `safely_held == False`: there is no
    representation that is both `full` *and* unmoved anywhere in its cluster). That is
    a sharper alarm than the per-item drift count: an item drifting is survivable when
    a sibling representation of the *same* work is still `full`+verified; a work with no
    safe representation is a real custody loss — the only copies of the work are
    degraded (`partial`/`reference`) or moved (`drifted`/`rotted`/`error`).

    A pure fold over the H261 aggregate — `work_custody` over each work's
    representations and the *same* `verdicts` ledger every other works surface reads —
    **no schema change, no extra ledger read** beyond the one the caller already loads.
    Returns ``{total, at_risk, most_at_risk}``:

    - ``total`` — the works in scope (the multi-representation clusters `works_over`
      reported; the consolidation question only applies to a work with siblings, a
      single-representation paper's loss being the per-item signal already).
    - ``at_risk`` — how many of them are not safely held.
    - ``most_at_risk`` — the single work with the **lowest custody ceiling** (``None``
      when none is at risk), so a report can name *one* work to act on without the
      reader scanning the whole at-risk set. Picked deterministically by worst
      ``best_fidelity`` first (a work holding *no* full content — `reference` best — is
      more at risk than one holding a `full`-but-drifted copy: the content is gone vs.
      merely moved), then worst ``safest_drift``, then ``doi`` as a stable tiebreak. The
      entry carries the work's identity (``doi``/``url``/``canonical``), its
      ``representations`` count, the H261 ``custody`` block, and a self-describing
      ``reason`` — but **no `command`**: unlike the weakest-source flag (whose
      `scrolls verify --source <S>` recheck exists), there is no whole-library
      "recapture this work" act to name, and inventing a path that would not close the
      gap is exactly what `suggest_repairs` refuses (the orphan-scroll discipline).

    `verdicts` is the `latest_events` ledger read keyed by item id; absent entries
    read `unverified` (a never-checked `full` copy is safely held — the M2 honesty,
    no network). The shared primitive both `doctor`'s `custody.works` block and the
    `maintain` report's `at_risk_works` pointer surface, so the count and the named
    work are *the same* on both by construction.
    """
    risked = [
        (work, work_custody(work.representations, verdicts))
        for work in works
    ]
    risked = [(work, custody) for work, custody in risked if not custody["safely_held"]]
    return {
        "total": len(works),
        "at_risk": len(risked),
        "most_at_risk": _most_at_risk_entry(risked),
    }


def _most_at_risk_entry(
    risked: list[tuple[Work, dict[str, Any]]]
) -> dict[str, Any] | None:
    """The single lowest-custody-ceiling work among the at-risk set, or ``None``.

    Worst ``best_fidelity`` first (highest `FIDELITY_TIERS` index — `reference`, the
    work whose content was never captured, over a `full`-but-moved copy), then worst
    ``safest_drift`` (highest `DRIFT_POSTURES` index), then ``doi`` so the pick is
    stable run to run. The `custody` block is the H261 verdict the ranking read, so
    the named work agrees with the aggregate it carries by construction.
    """
    if not risked:
        return None
    work, custody = min(
        risked,
        key=lambda wc: (
            -FIDELITY_TIERS.index(wc[1]["best_fidelity"]),
            -DRIFT_POSTURES.index(wc[1]["safest_drift"]),
            wc[0].doi,
        ),
    )
    return {
        "doi": work.doi,
        "url": work.url,
        "canonical": work.canonical.id,
        "representations": len(work.representations),
        "custody": custody,
        "reason": (
            "no representation is both full and unmoved "
            f"(best held {custody['best_fidelity']}, "
            f"safest drift {custody['safest_drift']})"
        ),
    }


def render_at_risk_works(
    items: list[ScrollItem],
    verdicts: dict[str, CustodyEvent],
    *,
    min_representations: int = DEFAULT_MIN_REPRESENTATIONS,
) -> list[str]:
    """The readable at-risk-works `_At-risk work:_` line for a briefing (roadmap H264).

    The *consolidation*-level counterpart of the per-source weakest-source drift
    `_Attention:_` line (`custody.render_custody_attention`, H159): where that names
    the single source carrying the most actionable per-*item* loss, this names the
    single **work** carrying a consolidation loss — a work no representation *safely
    holds* (no copy is both `full` and unmoved anywhere in its cluster, the H261
    `safely_held == False`). So an agent skimming the `export bundle`/`scrolls
    context` briefing reads "this work is at risk" without re-running `doctor`:

        ``_At-risk work: `<doi>` — no representation is both full and unmoved (best
        held <tier>, safest drift <posture>); N work(s) at risk._``

    Distilled by the shared `at_risk_signal` over the briefing scope's own clustered
    works — `works_over` over the *gathered* item set, the **lean-scope** decision
    (H264): the briefing describes what it *carries*, mirroring how the per-source
    `by_source` map is the scope's own. So a work counts here only when its
    multi-representation cluster is visible within the scope (a query matching one
    lone representation leaves a single-rep cluster, dropped by the
    `min_representations` floor — the consolidation question needs the siblings).
    The line names the same work `most_at_risk` does and reuses its `reason`
    verbatim, so it converges field-for-field with `doctor`'s `custody.works` /
    `maintain`'s `at_risk_works` / MCP `get_library_health` by construction; the
    trailing ``N work(s) at risk`` is the `at_risk` count, so a reader knows whether
    the named work is the only one or merely the worst of several.

    Lives here beside `at_risk_signal` (not in `custody.py` with
    `render_custody_attention`) because the signal it distils lives here: `works.py`
    imports `custody`, so a `custody.render_at_risk_works` calling `at_risk_signal`
    would close an import cycle. The shape is the H159 renderer's — the roadmap's
    "`custody.render_at_risk_works`-style helper", the home following the primitive.

    Returns ``[line, ""]`` (the line plus a trailing blank) so a caller splices it
    straight in above the `_Refresh:_`/`_By source:_` lines. Returns ``[]`` on honest
    absence — exactly when `at_risk_signal`'s `most_at_risk` is `None` (no
    multi-representation work in scope is at risk: a clean, single-representation, or
    empty scope), the same no-op the source `_Attention:_` line takes.
    """
    works = works_over(items, min_representations=min_representations)
    signal = at_risk_signal(works, verdicts)
    entry = signal["most_at_risk"]
    if entry is None:
        return []
    line = (
        f"_At-risk work: `{entry['doi']}` — {entry['reason']}; "
        f"{signal['at_risk']} work(s) at risk._"
    )
    return [line, ""]


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

    Each work also carries a `custody` block — the *aggregate* custody posture of
    the work, the consolidation of its representations' per-item custody (roadmap
    H261, the new custody *shape* vision §3.5): `{best_fidelity, safest_drift,
    safely_held}` from `work_custody` over the work's representations and the same
    `verdicts`. So a reader of a 3-representation work sees not just "the preprint
    is full, the DOI record rotted" per row but the work-level verdict "this work
    is **safely held** (an unmoved, fully re-derivable copy exists — via the
    preprint)" — the custody promise applied to the *work*, not just the item. A
    pure fold over the per-rep `fidelity`/`drift` below, so it adds no ledger read
    and agrees with the representation entries it rides beside by construction.

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

    `stats.custody.at_risk` (roadmap H266) is the *scope-level at-risk-works summary*:
    the `at_risk_signal` fold (`{total, at_risk, most_at_risk}`, H263) over the
    **reported** works, beside `attention` in the same `stats.custody` loss-summary
    family (`attention` being itself a scope-level custody-loss summary — a source
    flag, not a rep tally). It is the works-surface counterpart of `doctor`'s
    `custody.works` at-risk alarm, so a reader of any `works` payload sees "N of the
    reported works are at risk; worst is `<doi>`" without a second `doctor` call. A
    pure fold over the reported works, so it composes with the H262/H265 filters
    (under `--at-risk`, `at_risk == total`; under `--fidelity full`, the at-risk subset
    of the kept works) and `at_risk.total` equals `stats.works` beside it by
    construction. It converges with `doctor`'s `custody.works` (and MCP
    `get_library_health`) over the **same scope** field-for-field — the unscoped works
    payload reports the same default 2+ clustering and ledger `doctor` audits, so the
    two read the identical `{total, at_risk, most_at_risk}`. No schema change beyond
    stats, no extra ledger read — the same `verdicts` the per-rep `drift` already folds.
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
    # `stats.custody.attention` (roadmap H174): the reported works' single weakest
    # source distilled from the lean `by_source` beside it — the works-surface
    # counterpart of the `graph` flag (H164), riding MCP `get_works` for free (the
    # shared `to_payload`). The browse-stats `by_source` carries no per-source
    # coverage (H155), so `include_coverage=False` keeps the flag honest.
    custody["attention"] = weakest_source(custody["by_source"], include_coverage=False)
    # `stats.custody.at_risk` (roadmap H266): the scope-level at-risk-works summary —
    # the `at_risk_signal` fold (`{total, at_risk, most_at_risk}`, H263) over the
    # **reported** works, the works-surface counterpart of `doctor`'s `custody.works`
    # alarm and the exact precedent of `attention` beside it (itself a scope-level
    # custody-loss summary, not a rep tally). So a reader of any `works` payload sees
    # "N of the reported works are at risk; worst is `<doi>`" without a second `doctor`
    # call. A pure fold over the reported works, so it composes with the H262/H265
    # filters (under `--at-risk`, `at_risk == total`; under `--fidelity full` it counts
    # the at-risk subset of the kept works) and converges with `doctor`'s `custody.works`
    # / `get_library_health` over the same scope by construction. No schema change beyond
    # stats, no extra ledger read — the same `verdicts` the per-rep `drift` already folds.
    custody["at_risk"] = at_risk_signal(works, verdicts)
    return {
        "scope": {key: value for key, value in scope.items() if value is not None},
        "works": [
            {
                "doi": work.doi,
                "url": work.url,
                "canonical": work.canonical.id,
                # the work-level aggregate custody verdict (roadmap H261): the
                # consolidation of the per-rep custody below into "is this work
                # safely held?", a pure fold over the same `fidelity`/`drift` the
                # representations carry — no schema change, no extra ledger read.
                "custody": work_custody(work.representations, verdicts),
                # the work-level content-identity flag (roadmap H329): True iff two
                # of this work's forms hold byte-identical content (the same
                # `content_hash`) — the consolidation-surface sibling of the whole-
                # library `doctor.custody.content_duplicates` report (H325),
                # report-only and a pure fold over the per-rep `content_hash`.
                "content_duplicate": work_content_duplicate(work.representations),
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
        content_hash=item.content_hash,
    )
