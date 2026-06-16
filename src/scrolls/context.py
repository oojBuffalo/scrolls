"""Agent context bundles (IDEAS.md §11, §14 Pass 5).

`scrolls context <query>` answers "what does my library know about X?"
with one compact Markdown document: ranked matches, capped excerpts, and
source links. Agents don't want 100 files — they want a high-signal
bundle they can drop straight into context, so unlike the data commands
this one emits Markdown, not JSON (the bundle *is* the artifact). Each
excerpt carries the item id, source, and scroll path so an agent can
follow up with `scrolls show <id>` or read the full scroll.

Ranking comes from the existing FTS5/BM25 search; excerpts prefer the
stored summary and fall back to the leading extracted text. A
"Synthesized Brief" needs an LLM and is omitted honestly, like LLM
classification (ADR 0004) and LLM concept pages (ADR 0005).

At the `full` budget each excerpt also carries two compact per-source trust
tags beneath its meta line (roadmap H44 + H62): *how the category was derived*
(the `classification_provenance` view, omitted on honest absence) and *whether
the source has moved* (the `custody.drift_posture`, `unverified` stated
explicitly). They derive from the same views every browse/inspect surface
reads, so an excerpt an agent drops into its window reports the same provenance
`show`/`list`/`search` would — the per-source counterpart of the scope-level
`_Custody:_` headline.

Beyond keyword matches the bundle carries a "Connected scrolls" section:
items linked to or from the matches through the cross-item link graph the
adapters build (a saved model's paper, a preprint's published DOI, a
package's repo — ADR 0044). These are high-precision connections FTS can't
find — the paper a match points at need not share its keywords — so the
graph the adapters spent so many adapters building finally surfaces in the
bundle an agent actually reads, not only in `scrolls related`/`graph`.

Duplicate representations of one scholarly work are collapsed (ADR 0101):
when a query matches both an arXiv preprint and its published Crossref
record — the same work, near-identical content — the bundle keeps the
best-ranked representation, names the folded sibling(s) and the work's
canonical form, and excerpts the work once. A high-signal bundle should not
spend two of its few slots on one work; the `works` membership search hits
now carry makes the collapse a lookup, not a re-derivation.
"""

from __future__ import annotations

from pathlib import Path

from scrolls.custody import CustodyEvent, custody_headline, drift_posture, latest_events
from scrolls.graph import build_graph
from scrolls.items import (
    ScrollItem,
    classification_phrase,
    classification_provenance,
    get_item,
)
from scrolls.search import SearchHit, count_matches, search_items

_EXCERPT_CHARS = 700
DEFAULT_LIMIT = 8

# Progressive context budget tiers (MVP M3, obsidian L0–L3 adaptation). A
# bundle is a *budgeted boot sequence*: identity/index first, deep bodies on
# demand. The tiers are strictly nested — each is a superset of the one before
# — so `--budget` bounds depth predictably:
#   index     — the catalog: Best Matches + Links (ids, titles, source URLs).
#               No bodies, and no link-graph build at all (the cheapest boot).
#   connected — index + the Connected scrolls link graph. Still no bodies.
#   full      — connected + Excerpts (the deep bodies). The default, the
#               current flat bundle, unchanged.
# A tier below `full` discloses the reduced depth in a `_Budget:_` note so an
# agent never reads a catalog-only bundle as "this is all there is to read" —
# the same anti-fabrication / honest-scope discipline the Coverage line applies
# to the match *set* (completeness contract G2), here applied to depth *per
# match*. The two are orthogonal and both always hold.
BUDGET_TIERS = ("index", "connected", "full")
DEFAULT_BUDGET = "full"


def _tier_at_least(budget: str, required: str) -> bool:
    """Whether `budget` includes everything tier `required` includes (nested)."""
    return BUDGET_TIERS.index(budget) >= BUDGET_TIERS.index(required)


def build_context(
    db_path: Path,
    query: str,
    limit: int = DEFAULT_LIMIT,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
    budget: str = DEFAULT_BUDGET,
) -> str:
    """Render the Markdown bundle for a query; raises ValueError on a blank one.

    The optional `source`/`category`/`stage` facets (ADR 0058) and the
    `tag`/`concept` membership facets (ADR 0059) scope the bundle the same
    way they scope `scrolls search` — they narrow the underlying ranked
    match (and so the connected-scrolls graph that hangs off it), letting an
    agent ask "what do the *papers* tagged efficient say about X" rather than
    "anything about X". When any facet is set the title carries a scope note
    so the bundle is self-documenting; the empty-string `category` selects
    the unclassified pool and reads as `category=unclassified`.

    `budget` (MVP M3) bounds the bundle's *depth* through the nested
    `index`/`connected`/`full` tiers (`BUDGET_TIERS`): `index` is the catalog
    alone (matches + links), `connected` adds the link graph, `full` (default)
    adds the deep-body excerpts. A tier below `full` carries a `_Budget:_` note
    disclosing what it omitted, so a budgeted bundle stays honest about depth
    the way the Coverage line stays honest about scope. An unknown tier raises
    ValueError (the CLI also rejects it via argparse `choices`).

    From `connected` up the bundle also carries a one-line `_Custody:_` headline
    (roadmap H47) — fidelity-tier and drift-posture counts over the in-bundle
    scrolls, the same `custody_headline` the shareable bundle and `scrolls
    status` render — so an agent sees how much of what it is about to read is
    full-fidelity and how much has drifted. Gated off `index` so the leanest
    tier stays a bare catalog.

    No matches (or no library yet) still yields a valid bundle saying so,
    because agents shouldn't crash on an empty library.
    """
    if budget not in BUDGET_TIERS:
        raise ValueError(
            f"unknown budget {budget!r}; choose one of {', '.join(BUDGET_TIERS)}"
        )
    hits = search_items(
        db_path,
        query,
        limit=limit,
        source=source,
        category=category,
        stage=stage,
        tag=tag,
        concept=concept,
    )
    kept, folded = _collapse_by_work(hits)
    # (hit, item) pairs in kept order; drop any hit whose row vanished
    pairs = [(hit, get_item(db_path, hit.id)) for hit in kept]
    pairs = [(hit, item) for hit, item in pairs if item]
    items = [item for _, item in pairs]

    title = f"# Scrolls Context Bundle: {query}"
    scope = _scope_note(source, category, stage, tag, concept)
    if scope:
        title += f" ({scope})"
    lines = [title, ""]
    if not items:
        lines.append("No matching scrolls.")
        return "\n".join(lines) + "\n"

    # How much of the library this bundle saw: every match under the cap, or
    # the top-ranked slice of more (completeness contract G2). `count_matches`
    # is the same past-the-cap denominator `scrolls search --stats` uses, under
    # the same facets, so the bundle's coverage claim and a `--stats` search
    # over the same scope agree. The query is already validated by the
    # search_items call above, so this never raises on a blank query.
    matched = count_matches(
        db_path,
        query,
        source=source,
        category=category,
        stage=stage,
        tag=tag,
        concept=concept,
    )
    lines += [_coverage_line(matched, len(hits)), ""]
    budget_note = _budget_line(budget)
    if budget_note:
        lines += [budget_note, ""]

    # One `latest_events` ledger read for the whole scope, shared by the scope
    # custody headline (`connected`+) and the per-excerpt drift tags (`full`).
    # Skipped at `index`, where neither renders (the leanest tier touches no
    # ledger). `{}` there keeps `drift_posture(None)` → `unverified` honest.
    verdicts: dict[str, CustodyEvent] = (
        latest_events(db_path) if _tier_at_least(budget, "connected") else {}
    )

    # The scope custody headline (roadmap H47): how much of what the agent is
    # about to read is full-fidelity, and how much has drifted — the same
    # `custody_headline` the shareable bundle briefing (H45) and `scrolls status`
    # (H38) render, over the in-bundle scrolls (the kept representations the
    # Coverage line counts). Gated to `connected`/`full` like the depth-bearing
    # sections (H44): the leanest `index` tier stays a bare catalog.
    if _tier_at_least(budget, "connected"):
        lines += [custody_headline(items, verdicts), ""]

    lines += ["## Best Matches", ""]
    for rank, (hit, item) in enumerate(pairs, start=1):
        line = f"{rank}. {item.title or item.id} (`{item.id}`)"
        if item.category:
            line += f" — {item.category}"
        note = _work_note(hit, folded.get(hit.id, []))
        if note:
            line += f" · {note}"
        lines.append(line)

    # Deep bodies only at the `full` budget — the index/connected tiers boot an
    # agent on the catalog (and, for `connected`, the graph) and let it pull
    # bodies on demand with `scrolls show <id>` or a `--budget full` re-run.
    if _tier_at_least(budget, "full"):
        lines += ["", "## Excerpts"]
        for item in items:
            lines += ["", f"### {item.title or item.id}", "", _meta_line(item)]
            lines += _provenance_tags(item, verdicts.get(item.id))
            excerpt = _excerpt(item)
            if excerpt:
                lines += ["", excerpt]

    # The link graph from the `connected` tier up; `index` skips the graph build
    # entirely. Folded representations are the same work as a kept match, so
    # they must not resurface as "connected" neighbours (the preprint links to
    # the published DOI record it just absorbed) — exclude them too.
    if _tier_at_least(budget, "connected"):
        folded_ids = {item_id for ids in folded.values() for item_id in ids}
        connected = _connected_lines(db_path, [item.id for item in items], folded_ids)
        if connected:
            lines += ["", "## Connected scrolls", ""] + connected

    lines += ["", "## Links", ""]
    lines += [
        f"- [{item.title or item.id}]({item.canonical_url or item.url})"
        for item in items
    ]
    return "\n".join(lines) + "\n"


def _collapse_by_work(
    hits: list[SearchHit],
) -> tuple[list[SearchHit], dict[str, list[str]]]:
    """Fold same-work duplicate hits into their best-ranked representation.

    Walks the ranked hits keeping the first representation seen of each work
    (ADR 0101): a later hit whose every work already has a kept representative
    is folded under the earliest keeper it shares a work with — the published
    record folded under the preprint that out-ranked it, or vice versa. A hit
    that brings a *new* work (even while sharing an already-seen one) is kept,
    so a multi-work item is never dropped. Returns the kept hits in rank order
    and `{kept hit id: [folded hit id, …]}`. Hits with no work membership never
    fold — they are not duplicates of anything.
    """
    seen_dois: set[str] = set()
    owner: dict[str, str] = {}  # work DOI → the kept hit that represents it
    kept: list[SearchHit] = []
    folded: dict[str, list[str]] = {}
    for hit in hits:
        hit_dois = {ref.doi for ref in hit.works}
        if hit_dois and hit_dois <= seen_dois:
            keeper = next(owner[doi] for doi in hit_dois if doi in owner)
            folded.setdefault(keeper, []).append(hit.id)
            continue
        kept.append(hit)
        for doi in hit_dois - seen_dois:
            owner[doi] = hit.id
        seen_dois |= hit_dois
    return kept, folded


def _coverage_line(matched: int, returned: int) -> str:
    """The bundle's scope-honest coverage note (completeness contract G2).

    States whether the bundle was built from every matching scroll or only the
    top-ranked slice of more, so a reader holding *only* the bundle can tell
    "this is everything my library knows about X" from "the top N — there is
    more" and never reads a capped bundle as library-wide absence. `matched`
    is the past-the-cap match total (`search.count_matches`); `returned` is
    how many the cap let the bundle see (`<= matched`); the bundle is truncated
    exactly when `matched > returned`, the same arithmetic the `--stats`
    envelope pins (`src/scrolls/scope.py`). The count is of matching *scrolls*
    (raw matches): a same-work duplicate folded into its best-ranked sibling
    (ADR 0101) is still covered — it is named in that sibling's note — so a
    collapsed bundle is complete, not truncated.
    """
    if matched > returned:
        return (
            f"_Coverage: the top {returned} of {matched} matching scrolls — "
            "raise `--limit` or narrow the query to see the rest._"
        )
    return f"_Coverage: all {matched} matching scrolls._"


def _budget_line(budget: str) -> str:
    """The bundle's depth-honesty note for a tier below `full` (MVP M3), else ''.

    Discloses what the budget held back and names the lever to get it, so a
    catalog-only bundle is never mistaken for "all there is to read" — the
    depth-axis counterpart to the Coverage line's scope honesty. `full` omits
    nothing, so it carries no note and the default bundle is unchanged.
    """
    if budget == "index":
        return (
            "_Budget: index — the catalog only (best matches and source "
            "links). Re-run with `--budget connected` for the link graph or "
            "`--budget full` for excerpts; `scrolls show <id>` reads a body._"
        )
    if budget == "connected":
        return (
            "_Budget: connected — best matches, the link graph, and source "
            "links, no excerpts. Re-run with `--budget full` for excerpts; "
            "`scrolls show <id>` reads a body._"
        )
    return ""


def _work_note(hit: SearchHit, folded_ids: list[str]) -> str:
    """The Best-Matches annotation for a hit that absorbed same-work siblings.

    Empty unless siblings were folded into this hit, so the note appears only
    where the bundle actually collapsed a duplicate. Names the folded
    representation(s) and the work's canonical form (ADR 0095) — which may be a
    folded sibling, this very hit, or a representation that did not match at all
    — so an agent sees the preferred form even though the bundle kept the
    best-ranked one.
    """
    if not folded_ids:
        return ""
    note = "same work as " + ", ".join(f"`{item_id}`" for item_id in folded_ids)
    canonical = hit.works[0].canonical if hit.works else None
    if canonical == hit.id:
        note += " (this is the canonical form)"
    elif canonical:
        note += f"; canonical `{canonical}`"
    return note


def _scope_note(
    source: str | None,
    category: str | None,
    stage: str | None,
    tag: str | None,
    concept: str | None,
) -> str:
    """A `source=…, category=…, …` summary of the active facets, else ''.

    The empty-string `category` (the unclassified pool, mirroring `scrolls
    search`/`list`) reads as `category=unclassified` so the title is honest
    about what an empty value selects. `tag`/`concept` (ADR 0059) carry no
    such overload — they report their value verbatim.
    """
    parts = []
    if source is not None:
        parts.append(f"source={source}")
    if category is not None:
        parts.append(f"category={category or 'unclassified'}")
    if stage is not None:
        parts.append(f"stage={stage}")
    if tag is not None:
        parts.append(f"tag={tag}")
    if concept is not None:
        parts.append(f"concept={concept}")
    return ", ".join(parts)


def _connected_lines(
    db_path: Path, ranked_ids: list[str], exclude: set[str] = frozenset()
) -> list[str]:
    """Bullet lines for scrolls linked to/from the matches but not matched.

    Resolves the whole-library link graph (`graph.build_graph`, the same
    edges `scrolls graph` reports) and keeps the items on the far end of an
    edge whose near end is a match. A match itself is never listed — it is
    already a keyword hit — nor is any id in `exclude` (the representations
    folded into a kept match, ADR 0101: the same work, already shown).
    Neighbors are ranked by how many distinct matches they connect to
    (centrality), then by the best match's rank, then by id, and capped at the
    match count so the bundle stays compact. Each line names the strongest
    match that pulled the neighbor in, the direction of the edge ("links to" /
    "linked from"), and how many further matches it touches.
    """
    ranks = {item_id: rank for rank, item_id in enumerate(ranked_ids)}
    graph = build_graph(db_path)
    nodes = {node.id: node for node in graph.nodes}

    # neighbor id → {match id: direction}; the neighbor is the non-match end.
    connections: dict[str, dict[str, str]] = {}
    for edge in graph.edges:
        from_match = edge.from_id in ranks
        to_match = edge.to_id in ranks
        if from_match == to_match:  # both matched, or neither — not a bridge
            continue
        if from_match:
            match_id, neighbor_id, direction = edge.from_id, edge.to_id, "linked from"
        else:
            match_id, neighbor_id, direction = edge.to_id, edge.from_id, "links to"
        if neighbor_id in exclude:  # a folded same-work representation
            continue
        connections.setdefault(neighbor_id, {}).setdefault(match_id, direction)

    def order_key(neighbor_id: str) -> tuple:
        matches = connections[neighbor_id]
        return (-len(matches), min(ranks[m] for m in matches), neighbor_id)

    lines = []
    for neighbor_id in sorted(connections, key=order_key)[: len(ranked_ids)]:
        node = nodes.get(neighbor_id)
        if node is None:  # defensive: a connected neighbor is always a node
            continue
        matches = connections[neighbor_id]
        best_match = min(matches, key=lambda m: ranks[m])
        match_node = nodes.get(best_match)
        match_label = (match_node.title if match_node else None) or best_match
        reason = f"{matches[best_match]} {match_label}"
        if len(matches) > 1:
            reason += f" (+{len(matches) - 1} more)"
        line = f"- {node.title or node.id} (`{node.id}`)"
        if node.source:
            line += f" · {node.source}"
        lines.append(f"{line} — {reason}")
    return lines


def _meta_line(item: ScrollItem) -> str:
    parts = [f"`{item.id}`", item.source]
    if item.markdown_path:
        parts.append(item.markdown_path)
    return " · ".join(parts)


def _provenance_tags(item: ScrollItem, verdict: CustodyEvent | None) -> list[str]:
    """The per-excerpt custody/provenance tags at the `full` budget (H44 + H62).

    The model-facing bundle drops excerpts straight into an agent's window, so
    each excerpt names the two trust signals cap 8 ("an agent knows what to
    trust") asks for, beneath the id/source/path meta line:

    - **Classification** (roadmap H44) — *how the category was derived*: the same
      `classification_provenance` view `show`/`list`/`search` and the shareable
      bundle briefing carry, rendered through the shared `classification_phrase`
      so the method/confidence reads byte-identical across surfaces. Omitted on
      honest absence — an unclassified or user-set item claims no method, so the
      line is simply dropped (the excerpt's shape stays stable).
    - **Drift** (roadmap H62) — *whether the source has moved*: the
      `custody.drift_posture` over the item's latest verify-ledger verdict, the
      per-source counterpart of the scope `_Custody:_` headline (H47). Always
      shown, with `unverified` stated explicitly — never silently "clean", the
      drift block's honesty on the per-excerpt axis.

    Both derive from the views every other surface reads (the same `verdicts`
    `latest_events` read the headline shares), so an excerpt reads the same
    provenance an agent would see on `show`/`list`/`search` for that item. Gated
    to `full` by the caller — `index`/`connected` stay lean catalogs (the H10
    depth honesty); the two tags are a `full`-only deepening, like the excerpts.
    """
    tags = []
    view = classification_provenance(item)
    if view is not None:
        tags.append(f"_classified {classification_phrase(view)}_")
    tags.append(f"_drift `{drift_posture(verdict)}`_")
    return tags


def _excerpt(item: ScrollItem) -> str:
    # collapse whitespace so stray markdown in extracted text can't break
    # the bundle's own structure
    text = " ".join((item.summary or item.extracted_text or "").split())
    if len(text) <= _EXCERPT_CHARS:
        return text
    return text[:_EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"
