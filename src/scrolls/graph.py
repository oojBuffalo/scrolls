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

from scrolls.custody import (
    CustodyEvent,
    custody_counts,
    custody_counts_by_source,
    drift_posture,
    last_checked,
    weakest_source,
)
from scrolls.items import (
    ScrollItem,
    content_duplicate_index,
    get_fidelity,
    list_items,
    make_item_id,
)
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
    """A graph node: an item, in the same shape `scrolls related` reports.

    `fidelity` is the item's custody tier (full/partial/reference, ADR 0097/
    0100), so a node an agent lands on while reading the graph says how much of
    it the library holds — the same tier `scrolls related` carries, keeping the
    two shapes identical now that fidelity travels with related hits. The
    item-intrinsic fields live on the node; the per-node custody **drift posture**
    and **last_checked** timestamp (which need the verify ledger) and the
    **content_duplicate_ids** siblings (which need the whole-scope content fold) are
    added in `to_payload` (roadmap H56/H86/H343), so the node shape an agent reads
    carries the full per-item custody picture — *how much* (fidelity), *whether the
    source moved* (drift), *as of when* (last_checked), and *what else holds the same
    bytes* (content_duplicate_ids) — without coupling graph building to the ledger
    or re-grouping per node.
    """

    id: str
    source: str
    title: str | None
    url: str
    stage: str
    fidelity: str


@dataclass(frozen=True)
class Graph:
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    item_count: int
    # The whole input set the graph was resolved over — the `stats.items` scope,
    # retained (not just `item_count`) so `to_payload` can tally a scope-level
    # custody block over the same items `doctor`/`facets` count (roadmap H52).
    # Independent of `include_isolated`, exactly like `item_count`.
    items: tuple[ScrollItem, ...] = ()


@dataclass(frozen=True)
class Component:
    """One connected component of the graph — a cluster of linked items.

    Edges are treated as undirected for the partition (a link in either
    direction joins two items into the same cluster), but the original
    *directed* edges among the members are kept so a rendering can still
    show which way each link points.
    """

    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]


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
    return graph_over(items, include_isolated=include_isolated)


def graph_over(items: list[ScrollItem], *, include_isolated: bool = False) -> Graph:
    """Resolve a given set of items' links into a directed graph.

    The whole-library `build_graph` loads every item and calls this; the KB
    compiler (`kb.py`) passes only its *rendered* items so the compiled
    `graph.md` links resolve to scroll files. A link whose target is outside
    the given set never resolves — its identity isn't indexed — and the edge
    is dropped, exactly as the rest of the KB ignores unrendered items.
    `item_count` is the size of the given set, the total `nodes`/`edges`
    report connectivity against.
    """
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
    return Graph(
        nodes=tuple(nodes),
        edges=tuple(edges),
        item_count=len(items),
        items=tuple(items),
    )


def to_payload(
    graph: Graph, verdicts: dict[str, CustodyEvent] | None = None
) -> dict:
    """The graph as the JSON object the CLI and MCP tool both emit.

    `from`/`to` rather than the dataclass's `from_id`/`to_id` because
    `from` is a Python keyword; `stats.items` is the library total, against
    which `nodes`/`edges` report connectivity. `stats.clusters` is the
    number of connected components with 2+ members — the link clusters the
    KB's `graph.md` page renders (ADR 0062) — so a singleton isolate added
    by `--all` is *not* counted, and the count is the same notion whether or
    not isolates are included.

    Each node also carries its per-item custody `drift` posture (roadmap H56) —
    `custody.drift_posture` over its latest `verdicts` entry (`verified` /
    `unverified` / `drifted` / `rotted` / `error`), the same posture the bundle
    briefing and `scrolls related` hits carry — and `last_checked` (roadmap H86),
    `custody.last_checked` over the *same* verdict: when that posture was taken, or
    `null` when never re-checked. So an agent landing on a node sees not just *how
    much* of it the library holds (`fidelity`) but *whether the source drifted out
    from under it* and *as of when* — the same per-item custody picture the browse
    rows (`list`/`search`/`show`) and `related` hits report. The per-item parity
    counterpart of the scope-level `stats.custody` convergence.

    Each node also carries `content_duplicate_ids` (roadmap H343) — the *other*
    held ids byte-identical to it (its `content_hash` siblings, `[]` when unique or
    NULL-hash), the per-node form of the `show`/`get_scroll` read (H328) and the
    compiled "also held as" marker (H333). Folded once over the whole `stats.items`
    scope via `content_duplicate_index` (not a per-node O(n²) re-group, the H333
    compile precedent), so the sibling scope spans the graph's components — an agent
    walking the relationship graph sees a node's redundancy in place. It converges
    with the per-item `show`/`get_scroll` read by construction (both read the same
    H325 groups), the tenth surface of the H332 cross-surface guard. Report-only —
    a node names its byte-identical twins, never a merge command (raw is sacred).

    `stats.custody` is the graph-surface member of the custody-headline family
    (roadmap H52): the shared `custody.custody_counts` tally — fidelity-tier and
    drift-posture counts — over the *whole* `stats.items` scope (not just the
    connected nodes), so the graph's custody totals converge with `doctor`,
    `facets`, and the scope custody headlines for the same scope by construction.
    Carried as count maps (graph emits JSON, not a Markdown headline). `verdicts`
    is the `latest_events` ledger read the CLI/MCP pass; absent (the pure caller),
    every held item reads `unverified` — honest, nothing has been checked. The
    same `verdicts` feeds both the per-node `drift` and the `stats.custody` tally,
    so a node's posture and its contribution to the count can never disagree.

    `stats.custody.by_source` (roadmap H150) splits that whole-scope tally per
    source — the shared `custody.custody_counts_by_source` over the *same*
    `stats.items` scope, a map from source to its own `{tiers, drift, coverage}`
    (sorted keys). It is the graph-surface counterpart of the per-source `by_source`
    on JSON `status` (H133), the `export bundle` briefing (H141), the compiled
    `index.md` (H145), and the `context` bundle (H149), so a reader of the link
    graph sees *which* source's custody is weakest without dropping to
    `status`/`doctor`. Because both fold the same tally, the per-source entries sum
    to the whole `stats.custody` block beside them by construction (every item lands
    in exactly one source group) and — for the whole-library scope `build_graph`
    resolves — equal `doctor`'s `custody.by_source`, independent of
    `include_isolated` (which only changes which items become *nodes*, not the
    `stats.items` scope). An empty graph is the honest empty `{}` map.

    `stats.custody.attention` (roadmap H164) distils that per-source map to the
    single weakest source — the one carrying the most actionable loss
    (`drifted` + `rotted`) — via the shared `custody.weakest_source`, the *same*
    primitive JSON `scrolls status` (H139) and `scrolls maintain` (H119) thread, so
    a reader of the link graph sees *which* source most needs action without
    scanning `by_source` itself. It carries that source's own `{tiers, drift,
    coverage}` tally and the exact `scrolls verify --source <S>` recheck command
    (H137), and converges with `status`/`maintain`/`doctor` by construction (same
    primitive over the same map). Honest `null` on the same three gates as the JSON
    flags — empty / single-source / fully-clean — so a one-source or loss-free graph
    flags nothing even with drift. Ranks the whole `stats.custody.by_source` scope,
    so it is independent of `include_isolated` like the map it distils.
    """
    verdicts = verdicts or {}
    clusters = sum(
        1 for component in connected_components(graph) if len(component.nodes) >= 2
    )
    scope = list(graph.items)
    custody = custody_counts(scope, verdicts)
    custody["by_source"] = custody_counts_by_source(scope, verdicts)
    custody["attention"] = weakest_source(custody["by_source"])
    # The per-item content-identity siblings (roadmap H343): each node's *other*
    # held ids byte-identical to it, the per-node form of the `show`/`get_scroll`
    # `content_duplicate_ids` read (H328) beside the per-node `fidelity`/`drift`.
    # Folded once over the whole `scope` (the same `stats.custody` scope, not a
    # per-node O(n²) re-group), so a content group spans the graph's components —
    # an agent walking the relationship graph sees a node's redundancy without a
    # second `show`. A missing id reads as the honest empty `[]` (unique / NULL
    # hash, the H325 skip), the always-present derived-axis posture `fidelity`/
    # `drift` hold. Report-only, names no command (raw is sacred).
    dup_index = content_duplicate_index(scope)
    return {
        "nodes": [
            {
                "id": node.id,
                "source": node.source,
                "title": node.title,
                "url": node.url,
                "stage": node.stage,
                "fidelity": node.fidelity,
                "drift": drift_posture(verdicts.get(node.id)),
                "last_checked": last_checked(verdicts.get(node.id)),
                "content_duplicate_ids": dup_index.get(node.id, []),
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
            "clusters": clusters,
            "custody": custody,
        },
    }


def connected_components(graph: Graph) -> tuple[Component, ...]:
    """Partition the graph into clusters of mutually linked items, largest first.

    Edges are undirected for the partition (a link in either direction joins
    its endpoints), so each component is a maximal set of items reachable
    from one another by following links — the "islands of meaning" the
    cross-source adapters build (a model + its paper + its dataset, a package
    + its repo). The original directed edges among a component's members are
    preserved on it. Components are ordered by node count descending, then by
    their smallest node id; within a component nodes sort by id and edges by
    `(from_id, to_id)`, so the partition is stable run to run. Isolated
    nodes — present only when the graph was built with `include_isolated` —
    each form a singleton component.
    """
    parent = {node.id: node.id for node in graph.nodes}

    def find(x: str) -> str:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:  # path compression
            parent[x], x = root, parent[x]
        return root

    for edge in graph.edges:  # union the endpoints of every (undirected) edge
        ra, rb = find(edge.from_id), find(edge.to_id)
        if ra != rb:
            parent[ra] = rb

    nodes_by_root: dict[str, list[Node]] = {}
    for node in graph.nodes:
        nodes_by_root.setdefault(find(node.id), []).append(node)
    edges_by_root: dict[str, list[Edge]] = {}
    for edge in graph.edges:
        edges_by_root.setdefault(find(edge.from_id), []).append(edge)

    components = [
        Component(
            nodes=tuple(sorted(nodes, key=lambda node: node.id)),
            edges=tuple(sorted(
                edges_by_root.get(root, ()),
                key=lambda edge: (edge.from_id, edge.to_id),
            )),
        )
        for root, nodes in nodes_by_root.items()
    ]
    components.sort(key=lambda component: (-len(component.nodes), component.nodes[0].id))
    return tuple(components)


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
        fidelity=get_fidelity(item),
    )
