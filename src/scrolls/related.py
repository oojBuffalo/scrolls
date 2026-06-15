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
(and the future MCP `get_related_scrolls`) can show *why* — same spirit
as search snippets.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scrolls.graph import identity_tokens, link_tokens
from scrolls.items import ScrollItem, get_item, list_items
from scrolls.render import slugify
from scrolls.works import DOI_RESOLVER, item_dois

DEFAULT_LIMIT = 10

_WORK_POINTS = 6
_LINK_POINTS = 5
_CONCEPT_POINTS = 3
_TAG_POINTS = 2
_GROUP_POINTS = 1


@dataclass(frozen=True)
class RelatedHit:
    id: str
    source: str
    title: str | None
    url: str
    stage: str
    score: int
    reasons: tuple


def find_related(
    db_path: Path, item_id: str, limit: int = DEFAULT_LIMIT
) -> list[RelatedHit]:
    """Score every other item against `item_id`; best matches first.

    Raises ValueError when the item does not exist. Ties break on id so
    output is stable run to run.
    """
    item = get_item(db_path, item_id) if db_path.exists() else None
    if item is None:
        raise ValueError(f"no such item: {item_id}")

    item_targets = _link_targets(item)
    item_urls = _own_urls(item)
    item_concepts = {slugify(c): c for c in item.concepts if slugify(c)}
    item_tags = {t.lower(): t for t in item.tags}
    item_work_dois = item_dois(item)

    hits = []
    for other in list_items(db_path):
        if other.id == item.id:
            continue
        score = 0
        reasons = []

        shared_dois = sorted(item_work_dois & item_dois(other))
        if shared_dois:
            score += _WORK_POINTS * len(shared_dois)
            reasons.append(
                "same work: "
                + ", ".join(f"{DOI_RESOLVER}/{doi}" for doi in shared_dois)
            )

        if other.id in item_targets or _own_urls(other) & item_targets:
            score += _LINK_POINTS
            reasons.append("links to it")
        other_targets = _link_targets(other)
        if item.id in other_targets or item_urls & other_targets:
            score += _LINK_POINTS
            reasons.append("linked from it")

        shared_concepts = [
            item_concepts[slug]
            for slug in dict.fromkeys(slugify(c) for c in other.concepts)
            if slug in item_concepts
        ]
        if shared_concepts:
            score += _CONCEPT_POINTS * len(shared_concepts)
            reasons.append("shared concepts: " + ", ".join(sorted(shared_concepts)))

        shared_tags = [
            item_tags[tag]
            for tag in dict.fromkeys(t.lower() for t in other.tags)
            if tag in item_tags
        ]
        if shared_tags:
            score += _TAG_POINTS * len(shared_tags)
            reasons.append("shared tags: " + ", ".join(sorted(shared_tags)))

        if item.category and other.category == item.category:
            score += _GROUP_POINTS
            reasons.append(f"same category: {item.category}")
        if item.domain and other.domain == item.domain:
            score += _GROUP_POINTS
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
                )
            )

    hits.sort(key=lambda hit: (-hit.score, hit.id))
    return hits[:limit]


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
