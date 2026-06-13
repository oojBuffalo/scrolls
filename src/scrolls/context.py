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

Beyond keyword matches the bundle carries a "Connected scrolls" section:
items linked to or from the matches through the cross-item link graph the
adapters build (a saved model's paper, a preprint's published DOI, a
package's repo — ADR 0044). These are high-precision connections FTS can't
find — the paper a match points at need not share its keywords — so the
graph the adapters spent so many adapters building finally surfaces in the
bundle an agent actually reads, not only in `scrolls related`/`graph`.
"""

from __future__ import annotations

from pathlib import Path

from scrolls.graph import build_graph
from scrolls.items import ScrollItem, get_item
from scrolls.search import search_items

_EXCERPT_CHARS = 700
DEFAULT_LIMIT = 8


def build_context(
    db_path: Path,
    query: str,
    limit: int = DEFAULT_LIMIT,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
) -> str:
    """Render the Markdown bundle for a query; raises ValueError on a blank one.

    The optional `source`/`category`/`stage` facets scope the bundle the
    same way they scope `scrolls search` (ADR 0058) — they narrow the
    underlying ranked match (and so the connected-scrolls graph that hangs
    off it), letting an agent ask "what do the *papers* say about X" rather
    than "anything about X". When any facet is set the title carries a scope
    note so the bundle is self-documenting; the empty-string `category`
    selects the unclassified pool and reads as `category=unclassified`.

    No matches (or no library yet) still yields a valid bundle saying so,
    because agents shouldn't crash on an empty library.
    """
    hits = search_items(
        db_path, query, limit=limit, source=source, category=category, stage=stage
    )
    items = [item for item in (get_item(db_path, hit.id) for hit in hits) if item]

    title = f"# Scrolls Context Bundle: {query}"
    scope = _scope_note(source, category, stage)
    if scope:
        title += f" ({scope})"
    lines = [title, ""]
    if not items:
        lines.append("No matching scrolls.")
        return "\n".join(lines) + "\n"

    lines += ["## Best Matches", ""]
    for rank, item in enumerate(items, start=1):
        line = f"{rank}. {item.title or item.id} (`{item.id}`)"
        if item.category:
            line += f" — {item.category}"
        lines.append(line)

    lines += ["", "## Excerpts"]
    for item in items:
        lines += ["", f"### {item.title or item.id}", "", _meta_line(item)]
        excerpt = _excerpt(item)
        if excerpt:
            lines += ["", excerpt]

    connected = _connected_lines(db_path, [item.id for item in items])
    if connected:
        lines += ["", "## Connected scrolls", ""] + connected

    lines += ["", "## Links", ""]
    lines += [
        f"- [{item.title or item.id}]({item.canonical_url or item.url})"
        for item in items
    ]
    return "\n".join(lines) + "\n"


def _scope_note(source: str | None, category: str | None, stage: str | None) -> str:
    """A `source=…, category=…, stage=…` summary of the active facets, else ''.

    The empty-string `category` (the unclassified pool, mirroring `scrolls
    search`/`list`) reads as `category=unclassified` so the title is honest
    about what an empty value selects.
    """
    parts = []
    if source is not None:
        parts.append(f"source={source}")
    if category is not None:
        parts.append(f"category={category or 'unclassified'}")
    if stage is not None:
        parts.append(f"stage={stage}")
    return ", ".join(parts)


def _connected_lines(db_path: Path, ranked_ids: list[str]) -> list[str]:
    """Bullet lines for scrolls linked to/from the matches but not matched.

    Resolves the whole-library link graph (`graph.build_graph`, the same
    edges `scrolls graph` reports) and keeps the items on the far end of an
    edge whose near end is a match. A match itself is never listed — it is
    already a keyword hit. Neighbors are ranked by how many distinct matches
    they connect to (centrality), then by the best match's rank, then by id,
    and capped at the match count so the bundle stays compact. Each line
    names the strongest match that pulled the neighbor in, the direction of
    the edge ("links to" / "linked from"), and how many further matches it
    touches.
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


def _excerpt(item: ScrollItem) -> str:
    # collapse whitespace so stray markdown in extracted text can't break
    # the bundle's own structure
    text = " ".join((item.summary or item.extracted_text or "").split())
    if len(text) <= _EXCERPT_CHARS:
        return text
    return text[:_EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"
