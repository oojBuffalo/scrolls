"""The cross-item link graph (IDEAS.md §9, §10; ADR 0044).

Source adapters store, in each item's `links`, the URLs that item points
at — a model's paper (ADR 0041), a preprint's published DOI (ADR 0038), a
Space's served model (ADR 0043), a tweet's linked article. Resolving those
raw link strings to the items they identify turns the library into a
directed graph: an edge `A → B` whenever a link inside `A` names `B`.

`scrolls related` scores *one* item's edges alongside concept/tag signals;
this module materializes the *whole* graph at once, so an agent can read
the library's connective structure (hubs, lineage chains, clusters) in a
single call. The two share their link-resolution primitives — `link_tokens`
and `identity_tokens` below — so "what does a link resolve to" and "what
identifies an item as a target" have exactly one definition (`related.py`
imports them back).

Resolution is the same two-sided match `scrolls related` uses (ADR 0023):
a stored URL is normalized at registration, while a link inside saved
content carries whatever decorations the author pasted, so both sides are
matched raw and normalized, and a link is additionally run through source
detection so `arxiv.org/pdf/X` still finds item `arxiv:X`. The build is
linear in the number of links — every item's identity tokens go into one
index, then each link probes it — never the O(n²) of scoring every pair.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scrolls.items import ScrollItem, list_items, make_item_id
from scrolls.sources.detect import detect_source
from scrolls.sources.urls import normalize_url


@dataclass(frozen=True)
class Edge:
    """A directed link edge: a link in item `from_id` resolves to `to_id`.

    `via` is the raw link string that matched — the evidence for the edge,
    the same role a search snippet plays.
    """

    from_id: str
    to_id: str
    via: str


@dataclass(frozen=True)
class Node:
    """A graph node: an item, in the same shape `scrolls related` reports."""

    id: str
    source: str
    title: str | None
    url: str
    stage: str


@dataclass(frozen=True)
class Graph:
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    item_count: int


def link_tokens(link: str) -> list[str]:
    """Identity tokens a single raw link could resolve to, most specific first.

    The minted `source:source_id` item id (when source detection reads one
    off the link) is the most precise match, then the normalized URL, then
    the raw URL as pasted (ADR 0023). Ordering makes resolution
    deterministic when more than one token is indexed; `related.py` folds
    the list into a set, where order does not matter.
    """
    normalized = normalize_url(link)
    tokens: list[str] = []
    try:
        detected = detect_source(normalized)
    except ValueError:
        detected = None
    if detected is not None and detected.source_id:
        tokens.append(make_item_id(detected.source, detected.source_id, normalized))
    tokens.append(normalized)
    if link != normalized:
        tokens.append(link)
    return tokens


def identity_tokens(item: ScrollItem) -> set[str]:
    """Everything that identifies an item as a link target: its id and URLs.

    URLs are kept raw and normalized so a link matches whichever form the
    target was registered under.
    """
    tokens = {item.id}
    for url in (item.url, item.canonical_url):
        if url:
            tokens.update((url, normalize_url(url)))
    return tokens


def build_graph(db_path: Path, *, include_isolated: bool = False) -> Graph:
    """Resolve every item's links into directed edges across the library.

    Nodes are the items that take part in at least one edge — the connected
    structure, the interesting part — unless `include_isolated` widens it to
    every item. Edges are sorted by `(from_id, to_id)` and nodes by `id`, so
    the output is stable run to run. A missing database (uninitialized
    library) yields an empty graph. `item_count` is always the library
    total, so callers can report connectivity against the whole.
    """
    items = list_items(db_path) if db_path.exists() else []

    # token → the first item whose identity it matches (list_items is
    # oldest-first, so collisions from duplicates resolve deterministically).
    index: dict[str, str] = {}
    for item in items:
        for token in identity_tokens(item):
            index.setdefault(token, item.id)

    edges: list[Edge] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        for link in item.links:
            target = _resolve(link, index)
            if target is None or target == item.id:
                continue
            key = (item.id, target)
            if key in seen:  # collapse parallel links A→B to one edge
                continue
            seen.add(key)
            edges.append(Edge(from_id=item.id, to_id=target, via=link))
    edges.sort(key=lambda edge: (edge.from_id, edge.to_id))

    connected = {edge.from_id for edge in edges} | {edge.to_id for edge in edges}
    nodes = [
        _node(item)
        for item in items
        if include_isolated or item.id in connected
    ]
    nodes.sort(key=lambda node: node.id)
    return Graph(nodes=tuple(nodes), edges=tuple(edges), item_count=len(items))


def to_payload(graph: Graph) -> dict:
    """The graph as the JSON object the CLI and MCP tool both emit.

    `from`/`to` rather than the dataclass's `from_id`/`to_id` because
    `from` is a Python keyword; `stats.items` is the library total, against
    which `nodes`/`edges` report connectivity.
    """
    return {
        "nodes": [
            {
                "id": node.id,
                "source": node.source,
                "title": node.title,
                "url": node.url,
                "stage": node.stage,
            }
            for node in graph.nodes
        ],
        "edges": [
            {"from": edge.from_id, "to": edge.to_id, "via": edge.via}
            for edge in graph.edges
        ],
        "stats": {
            "items": graph.item_count,
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
        },
    }


def _resolve(link: str, index: dict[str, str]) -> str | None:
    """The item id a link names, by the first of its tokens that is indexed."""
    for token in link_tokens(link):
        target = index.get(token)
        if target is not None:
            return target
    return None


def _node(item: ScrollItem) -> Node:
    return Node(
        id=item.id,
        source=item.source,
        title=item.title,
        url=item.url,
        stage=item.stage,
    )
