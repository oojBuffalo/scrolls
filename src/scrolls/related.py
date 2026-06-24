"""Deterministic related-scroll discovery (IDEAS.md §10).

`scrolls related <id>` answers "what else in my library belongs next to
this?" without an LLM, scoring explainable signals:

- same work (6 points per shared DOI): the two items are the same
  scholarly work — a preprint and its published article, an indexing
  record — bound by a shared DOI (the `works` lens, ADR 0069). This
  outranks a one-way link because identity is stronger than a citation,
  and it catches the case `scrolls graph` cannot: two representations
  that both name `doi.org/D` with no Crossref hub item present share no
  realized link edge, yet they are siblings of one work.
- link connections (5 points per direction): one item's extracted links
  resolve to the other's identity — a bookmarked tweet pointing at a
  saved arXiv paper, a saved article both ways. Links are matched by
  exact URL against `url`/`canonical_url` and by running the URL through
  source detection so e.g. `arxiv.org/pdf/X` still finds item `arxiv:X`.
- shared concepts (3 each): curated, readable signals; spellings merge
  by slug exactly as KB concept pages do.
- shared tags (2 each, case-insensitive).
- same category / same domain (1 each): weak corroboration, never enough
  to rank an item without a stronger overlap... unless that's all there is.

A genuine same-work pair whose binding hub *is* present scores both the
same-work edge and the link edge — complementary facts (these are the
same work, *and* one points at the other), not double counting.

Every hit carries human/agent-readable `reasons`, so downstream callers
(and the MCP `get_related_scrolls`) can show *why* — same spirit as search
snippets — plus a one-word `relation_strength` band (`strong`/`moderate`/`weak`,
roadmap H322): the qualitative confidence the relation point weights imply, the
relationship-surface analogue of search's `match_strength`. It is the band of the
*strongest contributing signal class* — a same-work (shared DOI) or link edge is
an identity-/citation-grade bond (`strong`), shared concepts/tags are curated
topical overlap (`moderate`), and same category/domain is the weak corroboration
"never enough on its own" (`weak`) — so an agent reads not just *what* relates the
two but *how strongly*, and the legible band the opaque integer `score` lacks
(the score gives the order, the band the kind). The band names the kind of the
strongest bond, never the multiplied magnitude (three shared tags is still
topical, not identity) — grounded in the weights, not an invented relevance.
Beside it travels the neighbour's custody `fidelity` tier (full/partial/
reference, ADR 0097), its custody `drift` posture (verified/unverified/
drifted/rotted/error, roadmap H56), and `last_checked` — when that drift verdict
was taken, or `null` when never re-checked (roadmap H86) — all read from the
verify ledger, so an agent following a related edge sees at a glance how much of
the item it lands on the library holds, whether that source has drifted out from
under the capture, *and as of when* — the same per-item custody picture
`scrolls list` and the graph node shape report.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from scrolls.custody import (
    DRIFT_POSTURES,
    FIDELITY_TIERS,
    drift_posture,
    last_checked,
    latest_events,
)
from scrolls.graph import identity_tokens, link_tokens
from scrolls.items import ScrollItem, get_fidelity, get_item, list_items
from scrolls.render import slugify
from scrolls.works import DOI_RESOLVER, item_dois

DEFAULT_LIMIT = 10

_WORK_POINTS = 6
_LINK_POINTS = 5
_CONCEPT_POINTS = 3
_TAG_POINTS = 2
_GROUP_POINTS = 1

# The relation signal classes in descending point-weight order (strongest first),
# each tagged with the qualitative band its presence implies. `relation_strength`
# is the band of the *strongest contributing class* — the relationship-surface
# analogue of search's `match_strength` = band of the highest-weighted matched
# field (roadmap H322/H312). Grounded in the point weights above, not an invented
# relevance: a same-work (shared DOI) or link edge is an identity-/citation-grade
# bond (→ `strong`), shared concepts/tags are curated topical overlap
# (→ `moderate`), and same category/domain is the weak corroboration that is
# "never enough on its own" (→ `weak`). The band names the *kind* of the strongest
# bond, never the multiplied magnitude — three shared tags (6 points, the weight of
# one same-work edge) is still a topical bond, not an identity one, exactly as
# `match_strength` bands on the field, not the BM25 score.
_RELATION_KINDS = ("work", "link", "concept", "tag", "group")
_STRENGTH_BY_KIND = {
    "work": "strong",
    "link": "strong",
    "concept": "moderate",
    "tag": "moderate",
    "group": "weak",
}
# The strength bands in descending kind-weight order (strongest first), the closed
# vocabulary `tally_relation_strength` partitions over and `--strength` filters by;
# derived from `_STRENGTH_BY_KIND` so the band order can never drift from the
# weights (the `search.STRENGTH_BANDS`-from-`_STRENGTH_BY_FIELD` precedent).
RELATION_STRENGTH_BANDS = tuple(
    dict.fromkeys(_STRENGTH_BY_KIND[kind] for kind in _RELATION_KINDS)
)


def relation_strength(kinds: Iterable[str]) -> str:
    """The qualitative relation confidence: the band of the strongest signal class.

    A fold over the contributing signal `kinds` returning the `_STRENGTH_BY_KIND`
    band of the highest-weighted class present — `strong` for a same-work or link
    bond, `moderate` for shared concepts/tags, `weak` for a same-category/domain-only
    edge — so the one-word signal an agent reads is grounded in the relation point
    weights that produced the rank, not the multiplied `score` magnitude (three
    shared tags is still a topical bond). The relationship-surface analogue of
    `search._match_strength` over `matched_fields` (H312). Defaults to `weak` only
    for the structurally-impossible empty case (a real hit always has ≥1 signal).
    """
    present = set(kinds)
    for kind in _RELATION_KINDS:  # descending weight, strongest first
        if kind in present:
            return _STRENGTH_BY_KIND[kind]
    return "weak"


def tally_relation_strength(strengths: Iterable[str]) -> dict[str, int]:
    """Per-band relation-strength counts from a stream of `relation_strength` values.

    The relationship-surface analogue of `search.tally_strength` (roadmap H323):
    it folds each related hit's own `relation_strength` into the
    `{strong, moderate, weak}` histogram, every band present in
    `RELATION_STRENGTH_BANDS` order with zeros included, so the shape is stable for
    a reader. The bands partition the matched neighbourhood — each hit has exactly
    one `relation_strength` — so the counts sum to `stats.matched` by construction,
    the drill-from-strength tie behind `--strength` (H324): the `--strength <band>`
    result count equals the sum of the bands at or above `<band>` in this tally
    (threshold semantics, the strongest-first prefix of `RELATION_STRENGTH_BANDS`).
    """
    counts = {band: 0 for band in RELATION_STRENGTH_BANDS}
    for strength in strengths:
        counts[strength] += 1
    return counts


@dataclass(frozen=True)
class RelatedHit:
    id: str
    source: str
    title: str | None
    url: str
    stage: str
    score: int
    reasons: tuple
    relation_strength: str
    fidelity: str
    drift: str
    last_checked: str | None


def find_related(
    db_path: Path,
    item_id: str,
    limit: int = DEFAULT_LIMIT,
    *,
    fidelity: str | None = None,
    drift: str | None = None,
    strength: str | None = None,
) -> list[RelatedHit]:
    """The best `limit` items related to `item_id`, best matches first.

    The capped public view (the MCP `get_related_scrolls` and bare `scrolls
    related` both read it). Raises ValueError when the item does not exist.

    `fidelity`/`drift`/`strength` narrow the neighbourhood per axis *before* the
    cap (roadmap H254/H324, the `list`-sieve shape), so the cap returns the
    top-`limit` neighbours **at that value**, not the matching ones among the
    top-`limit`. Each folds the same per-hit field it is read off
    (`get_fidelity`/`drift_posture`/`relation_strength`), so a neighbour is selected
    by exactly the value it shows; `strength` is a threshold (at or above the band).
    The axes AND. An unknown tier/posture/band raises ValueError (closed vocab), the
    same could-not-check contract `list_items` enforces.
    """
    return filter_related(
        scored_related(db_path, item_id),
        fidelity=fidelity,
        drift=drift,
        strength=strength,
    )[:limit]


def count_related(
    db_path: Path,
    item_id: str,
    *,
    fidelity: str | None = None,
    drift: str | None = None,
    strength: str | None = None,
) -> int:
    """How many items relate to `item_id` at all, ignoring the cap.

    The honest denominator behind `scrolls related --stats`' truncation
    marker (completeness contract G2): `find_related` returns at most
    `limit` neighbours, so on its own it cannot tell "those are all the
    related items" from "the top N of more". Raises ValueError on an unknown
    id, exactly like `find_related`, so the could-not-check path is identical.

    `fidelity`/`drift`/`strength` narrow the count to the same filtered neighbourhood
    `find_related` returns (roadmap H254/H324), so the `--stats` denominator counts
    the kept set — never the whole scored set when a filter is in play.
    """
    return len(
        filter_related(
            scored_related(db_path, item_id),
            fidelity=fidelity,
            drift=drift,
            strength=strength,
        )
    )


def filter_related(
    hits: list[RelatedHit],
    *,
    fidelity: str | None = None,
    drift: str | None = None,
    strength: str | None = None,
) -> list[RelatedHit]:
    """Narrow scored related hits per custody/rank axis (the H254/H324 sieve).

    The relationship-surface twin of `list --fidelity`/`--drift` and `search
    --strength`: it folds the *same* per-hit `fidelity`/`drift`/`relation_strength`
    the node shape is read off (`get_fidelity`/`drift_posture`, roadmap H56; the
    H322 band), so a neighbour is kept by exactly the value it shows. The axes AND.
    `strength` is a **threshold** (at or above the band): `strong` keeps only
    identity/citation bonds, `moderate` adds topical overlap, `weak` keeps all —
    the columns at or above `strength` being the strongest-first prefix of
    `RELATION_STRENGTH_BANDS` (the H314 `search --strength` semantics on the relation
    axis). Closed vocabulary (`FIDELITY_TIERS`/`DRIFT_POSTURES`/`RELATION_STRENGTH_BANDS`)
    → ValueError, so a typo is a loud could-not-check, never a silent empty
    neighbourhood (the `list_items` contract). Order is preserved, so a caller slicing
    `[:limit]` after this still gets the top-`k` neighbours *at that value*.
    """
    if fidelity is not None:
        if fidelity not in FIDELITY_TIERS:
            raise ValueError(
                f"unknown fidelity tier {fidelity!r}; "
                f"choose one of {', '.join(FIDELITY_TIERS)}"
            )
        hits = [hit for hit in hits if hit.fidelity == fidelity]
    if drift is not None:
        if drift not in DRIFT_POSTURES:
            raise ValueError(
                f"unknown drift posture {drift!r}; "
                f"choose one of {', '.join(DRIFT_POSTURES)}"
            )
        hits = [hit for hit in hits if hit.drift == drift]
    if strength is not None:
        if strength not in RELATION_STRENGTH_BANDS:
            raise ValueError(
                f"unknown relation strength {strength!r}; "
                f"choose one of {', '.join(RELATION_STRENGTH_BANDS)}"
            )
        # Threshold (at or above): the bands at or above `strength` are the
        # strongest-first prefix of `RELATION_STRENGTH_BANDS`, so a hit is kept iff
        # its own `relation_strength` lands in that prefix — the H314 column-prefix
        # idea on the in-Python relation sieve.
        kept = set(RELATION_STRENGTH_BANDS[: RELATION_STRENGTH_BANDS.index(strength) + 1])
        hits = [hit for hit in hits if hit.relation_strength in kept]
    return hits


def scored_related(db_path: Path, item_id: str) -> list[RelatedHit]:
    """Every item with a non-zero relation to `item_id`, best matches first.

    The uncapped scoring `find_related`/`count_related` are built on. Raises
    ValueError when the item does not exist. Ties break on id so output is
    stable run to run.
    """
    item = get_item(db_path, item_id) if db_path.exists() else None
    if item is None:
        raise ValueError(f"no such item: {item_id}")

    item_targets = _link_targets(item)
    item_urls = _own_urls(item)
    item_concepts = {slugify(c): c for c in item.concepts if slugify(c)}
    item_tags = {t.lower(): t for t in item.tags}
    item_work_dois = item_dois(item)
    # One ledger read for the whole scoring pass: each hit's `drift` posture is
    # `drift_posture` over its latest verdict and its `last_checked` the same
    # verdict's timestamp — the same primitives the graph node shape and the bundle
    # briefing read, so the posture and staleness an agent reads here and the
    # count `doctor`/`facets drift` report can never disagree (roadmap H56/H86).
    verdicts = latest_events(db_path)

    hits = []
    for other in list_items(db_path):
        if other.id == item.id:
            continue
        score = 0
        reasons = []
        # The signal classes that fired, parallel to `reasons` — folded into the
        # one-word `relation_strength` band (the band of the strongest class
        # present, roadmap H322). Tracked alongside the points rather than parsed
        # back out of the reason strings, so the band can never drift from the
        # signal that earned the score.
        kinds: list[str] = []

        shared_dois = sorted(item_work_dois & item_dois(other))
        if shared_dois:
            score += _WORK_POINTS * len(shared_dois)
            kinds.append("work")
            reasons.append(
                "same work: "
                + ", ".join(f"{DOI_RESOLVER}/{doi}" for doi in shared_dois)
            )

        if other.id in item_targets or _own_urls(other) & item_targets:
            score += _LINK_POINTS
            kinds.append("link")
            reasons.append("links to it")
        other_targets = _link_targets(other)
        if item.id in other_targets or item_urls & other_targets:
            score += _LINK_POINTS
            kinds.append("link")
            reasons.append("linked from it")

        shared_concepts = [
            item_concepts[slug]
            for slug in dict.fromkeys(slugify(c) for c in other.concepts)
            if slug in item_concepts
        ]
        if shared_concepts:
            score += _CONCEPT_POINTS * len(shared_concepts)
            kinds.append("concept")
            reasons.append("shared concepts: " + ", ".join(sorted(shared_concepts)))

        shared_tags = [
            item_tags[tag]
            for tag in dict.fromkeys(t.lower() for t in other.tags)
            if tag in item_tags
        ]
        if shared_tags:
            score += _TAG_POINTS * len(shared_tags)
            kinds.append("tag")
            reasons.append("shared tags: " + ", ".join(sorted(shared_tags)))

        if item.category and other.category == item.category:
            score += _GROUP_POINTS
            kinds.append("group")
            reasons.append(f"same category: {item.category}")
        if item.domain and other.domain == item.domain:
            score += _GROUP_POINTS
            kinds.append("group")
            reasons.append(f"same domain: {item.domain}")

        if score:
            hits.append(
                RelatedHit(
                    id=other.id,
                    source=other.source,
                    title=other.title,
                    url=other.url,
                    stage=other.stage,
                    score=score,
                    reasons=tuple(reasons),
                    relation_strength=relation_strength(kinds),
                    fidelity=get_fidelity(other),
                    drift=drift_posture(verdicts.get(other.id)),
                    last_checked=last_checked(verdicts.get(other.id)),
                )
            )

    hits.sort(key=lambda hit: (-hit.score, hit.id))
    return hits


def _link_targets(item: ScrollItem) -> set[str]:
    """Everything an item's extracted links could identify: URLs and item ids.

    The link-resolution primitive lives in `graph.py` so the per-item
    `related` view and the whole-library `graph` agree on what a link
    resolves to (ADR 0023, ADR 0044).
    """
    targets: set[str] = set()
    for link in item.links:
        targets.update(link_tokens(link))
    return targets


def _own_urls(item: ScrollItem) -> set[str]:
    """The item's own URLs (raw and normalized) — its identity minus its id.

    `related` scores a url-overlap hit and an id hit separately, so the id
    is dropped from the identity set here.
    """
    return identity_tokens(item) - {item.id}
