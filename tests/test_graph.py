"""Tests for the cross-item link graph (ADR 0044)."""

import json

import pytest

from scrolls.cli import main
from scrolls.custody import CustodyEvent, record_events
from scrolls.doctor import run_doctor
from scrolls.graph import build_graph, connected_components, graph_over
from scrolls.items import ScrollItem, insert_item
from scrolls.paths import get_paths


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


@pytest.fixture
def db(scrolls_home):
    main(["init"])
    return get_paths().db_path


def make_item(item_id, **overrides):
    base = dict(
        id=item_id,
        source=item_id.split(":")[0],
        url=f"https://example.org/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00",
        title=item_id,
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def _all_reference_unverified(n):
    """The `stats.custody` block for `n` bare items — every one `reference`
    fidelity (no content) and `unverified` (never re-checked), the default
    `make_item` shape these graph fixtures use."""
    return {
        "tiers": {"full": 0, "partial": 0, "reference": n},
        "drift": {"verified": 0, "unverified": n, "drifted": 0, "rotted": 0, "error": 0},
    }


def test_edge_resolves_a_link_to_the_item_it_names(db):
    insert_item(db, make_item(
        "x:1111",
        url="https://x.com/a/status/1111",
        links=("https://arxiv.org/pdf/2605.27848",),
    ))
    insert_item(db, make_item(
        "arxiv:2605.27848",
        url="https://arxiv.org/abs/2605.27848",
    ))

    graph = build_graph(db)
    assert [(e.from_id, e.to_id) for e in graph.edges] == [
        ("x:1111", "arxiv:2605.27848")
    ]
    assert graph.edges[0].via == "https://arxiv.org/pdf/2605.27848"


def test_nodes_carry_their_custody_fidelity(db):
    # a graph node reports the same custody tier `scrolls related` does, so the
    # two "node shapes" stay identical (ADR 0100); the graph already holds the
    # full item, so the tier is derived for free.
    insert_item(db, make_item(
        "x:1111",
        url="https://x.com/a/status/1111",
        links=("https://arxiv.org/abs/2605.27848",),
    ))  # a tweet: pointer only, no body
    insert_item(db, make_item(
        "arxiv:2605.27848",
        url="https://arxiv.org/abs/2605.27848",
        raw_text="the abstract and body", content_hash="sha256:p", stage="rendered",
    ))

    by_id = {node.id: node for node in build_graph(db).nodes}
    assert by_id["x:1111"].fidelity == "reference"
    assert by_id["arxiv:2605.27848"].fidelity == "full"


def test_only_connected_items_are_nodes_by_default(db):
    insert_item(db, make_item(
        "x:1111",
        url="https://x.com/a/status/1111",
        links=("https://arxiv.org/abs/2605.27848",),
    ))
    insert_item(db, make_item("arxiv:2605.27848", url="https://arxiv.org/abs/2605.27848"))
    insert_item(db, make_item("wikipedia:en:Pelican"))  # isolated

    graph = build_graph(db)
    assert [n.id for n in graph.nodes] == ["arxiv:2605.27848", "x:1111"]
    assert graph.item_count == 3  # the whole library, including the isolate


def test_include_isolated_adds_unconnected_items_as_nodes(db):
    insert_item(db, make_item(
        "x:1111",
        url="https://x.com/a/status/1111",
        links=("https://arxiv.org/abs/2605.27848",),
    ))
    insert_item(db, make_item("arxiv:2605.27848", url="https://arxiv.org/abs/2605.27848"))
    insert_item(db, make_item("wikipedia:en:Pelican"))

    graph = build_graph(db, include_isolated=True)
    assert [n.id for n in graph.nodes] == [
        "arxiv:2605.27848",
        "wikipedia:en:Pelican",
        "x:1111",
    ]


def test_edge_resolves_through_source_detection_with_case_folding(db):
    # arXiv stamps the published DOI as a doi.org link (ADR 0038); it
    # resolves to the crossref item id even though the link's DOI case
    # differs from the stored id — DOIs fold through source detection.
    insert_item(db, make_item(
        "arxiv:2310.06825",
        url="https://arxiv.org/abs/2310.06825",
        links=("https://doi.org/10.1109/Example.2024.12345",),  # mixed case
    ))
    insert_item(db, make_item(
        "crossref:10.1109/example.2024.12345",
        url="https://doi.org/10.1109/example.2024.12345",
    ))

    graph = build_graph(db)
    assert [(e.from_id, e.to_id) for e in graph.edges] == [
        ("arxiv:2310.06825", "crossref:10.1109/example.2024.12345")
    ]


def test_link_with_tracking_params_matches_the_clean_stored_url(db):
    insert_item(db, make_item(
        "x:1111",
        url="https://x.com/a/status/1111",
        links=("https://blog.example.com/post?utm_source=tweet#intro",),
    ))
    insert_item(db, make_item("web:abc123", url="https://blog.example.com/post"))

    graph = build_graph(db)
    assert [(e.from_id, e.to_id) for e in graph.edges] == [("x:1111", "web:abc123")]


def test_parallel_links_collapse_to_one_edge(db):
    insert_item(db, make_item(
        "x:1111",
        url="https://x.com/a/status/1111",
        links=(
            "https://arxiv.org/abs/2605.27848",
            "https://arxiv.org/pdf/2605.27848",  # same target, different form
        ),
    ))
    insert_item(db, make_item("arxiv:2605.27848", url="https://arxiv.org/abs/2605.27848"))

    graph = build_graph(db)
    assert len(graph.edges) == 1
    # the first link in declared order is the kept evidence
    assert graph.edges[0].via == "https://arxiv.org/abs/2605.27848"


def test_self_links_are_not_edges(db):
    insert_item(db, make_item(
        "web:self",
        url="https://blog.example.com/post",
        canonical_url="https://blog.example.com/post",
        links=("https://blog.example.com/post",),  # points at itself
    ))

    graph = build_graph(db)
    assert graph.edges == ()
    assert graph.nodes == ()


def test_links_to_items_outside_the_library_are_dropped(db):
    insert_item(db, make_item(
        "x:1111",
        url="https://x.com/a/status/1111",
        links=("https://arxiv.org/abs/9999.99999",),  # never saved
    ))

    graph = build_graph(db)
    assert graph.edges == ()
    assert graph.nodes == ()
    assert graph.item_count == 1


def test_empty_or_uninitialized_library_is_an_empty_graph(scrolls_home):
    graph = build_graph(get_paths().db_path)
    assert graph == build_graph(get_paths().db_path)  # stable
    assert graph.nodes == ()
    assert graph.edges == ()
    assert graph.item_count == 0


def test_cli_graph_prints_nodes_edges_and_stats(db, capsys):
    insert_item(db, make_item(
        "x:1111",
        url="https://x.com/a/status/1111",
        title="@a: paper thread",
        links=("https://arxiv.org/abs/2605.27848",),
    ))
    insert_item(db, make_item(
        "arxiv:2605.27848",
        url="https://arxiv.org/abs/2605.27848",
        title="A Paper",
    ))
    insert_item(db, make_item("wikipedia:en:Pelican"))  # isolated
    capsys.readouterr()

    exit_code = main(["graph"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["stats"] == {
        "items": 3, "nodes": 2, "edges": 1, "clusters": 1,
        "custody": _all_reference_unverified(3),  # over the whole library, not just nodes
    }
    assert payload["edges"] == [
        {"from": "x:1111", "to": "arxiv:2605.27848", "via": "https://arxiv.org/abs/2605.27848"}
    ]
    assert [n["id"] for n in payload["nodes"]] == ["arxiv:2605.27848", "x:1111"]
    paper = next(n for n in payload["nodes"] if n["id"] == "arxiv:2605.27848")
    assert paper["title"] == "A Paper"
    assert paper["source"] == "arxiv"


def test_cli_graph_all_includes_isolated_items(db, capsys):
    insert_item(db, make_item("wikipedia:en:Pelican"))
    capsys.readouterr()

    exit_code = main(["graph", "--all"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [n["id"] for n in payload["nodes"]] == ["wikipedia:en:Pelican"]
    # the lone isolate is a singleton, not a cluster: clusters counts 2+ only
    assert payload["stats"] == {
        "items": 1, "nodes": 1, "edges": 0, "clusters": 0,
        "custody": _all_reference_unverified(1),
    }


def test_cli_graph_empty_library_is_empty_json(scrolls_home, capsys):
    main(["init"])
    capsys.readouterr()
    exit_code = main(["graph"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"nodes": [], "edges": [], "stats": {
        "items": 0, "nodes": 0, "edges": 0, "clusters": 0,
        "custody": _all_reference_unverified(0),  # empty graph: honest zero counts
    }}


# --- connected_components (the KB graph.md clustering, ADR 0062) ----------


def test_connected_components_groups_linked_items(db):
    insert_item(db, make_item("web:a", links=("https://example.org/web:b",)))
    insert_item(db, make_item("web:b"))

    components = connected_components(build_graph(db))
    assert len(components) == 1
    assert [n.id for n in components[0].nodes] == ["web:a", "web:b"]
    assert [(e.from_id, e.to_id) for e in components[0].edges] == [("web:a", "web:b")]


def test_connected_components_orders_clusters_by_size_then_id(db):
    # a three-item chain c1 → c2 → c3
    insert_item(db, make_item("web:c1", links=("https://example.org/web:c2",)))
    insert_item(db, make_item("web:c2", links=("https://example.org/web:c3",)))
    insert_item(db, make_item("web:c3"))
    # a two-item cluster a1 → a2
    insert_item(db, make_item("web:a1", links=("https://example.org/web:a2",)))
    insert_item(db, make_item("web:a2"))

    components = connected_components(build_graph(db))
    assert [[n.id for n in c.nodes] for c in components] == [
        ["web:c1", "web:c2", "web:c3"],  # larger cluster first
        ["web:a1", "web:a2"],
    ]


def test_connected_components_group_is_undirected(db):
    # two items both pointing at one hub still form a single cluster
    insert_item(db, make_item("web:a", links=("https://example.org/web:hub",)))
    insert_item(db, make_item("web:c", links=("https://example.org/web:hub",)))
    insert_item(db, make_item("web:hub"))

    components = connected_components(build_graph(db))
    assert len(components) == 1
    assert [n.id for n in components[0].nodes] == ["web:a", "web:c", "web:hub"]
    assert [(e.from_id, e.to_id) for e in components[0].edges] == [
        ("web:a", "web:hub"),
        ("web:c", "web:hub"),
    ]


def test_connected_components_tie_breaks_equal_clusters_by_smallest_id(db):
    insert_item(db, make_item("web:b1", links=("https://example.org/web:b2",)))
    insert_item(db, make_item("web:b2"))
    insert_item(db, make_item("web:a1", links=("https://example.org/web:a2",)))
    insert_item(db, make_item("web:a2"))

    components = connected_components(build_graph(db))
    assert [c.nodes[0].id for c in components] == ["web:a1", "web:b1"]


def test_connected_components_of_empty_graph_is_empty(scrolls_home):
    main(["init"])
    assert connected_components(build_graph(get_paths().db_path)) == ()


def test_cli_graph_stats_count_clusters(db, capsys):
    # two independent 2-item clusters plus one isolate
    insert_item(db, make_item("web:a", links=("https://example.org/web:b",)))
    insert_item(db, make_item("web:b"))
    insert_item(db, make_item("web:c", links=("https://example.org/web:d",)))
    insert_item(db, make_item("web:d"))
    insert_item(db, make_item("web:lonely"))
    capsys.readouterr()

    main(["graph", "--all"])
    payload = json.loads(capsys.readouterr().out)
    # the isolate inflates items/nodes but not clusters (2+ members only)
    assert payload["stats"] == {
        "items": 5, "nodes": 5, "edges": 2, "clusters": 2,
        "custody": _all_reference_unverified(5),
    }


# --- stats.custody (the graph-surface custody headline, roadmap H52) -------


def test_graph_stats_custody_reflects_fidelity_and_drift(db, capsys):
    # a full-fidelity item (raw + hash), a partial (extracted only), a reference
    # pointer; one verify event so the drift axis spans verified + unverified
    insert_item(db, make_item("web:full", raw_text="<raw>b</raw>",
                              extracted_text="b", content_hash="sha256:full"))
    insert_item(db, make_item("web:partial", extracted_text="b"))
    insert_item(db, make_item("web:ref"))  # reference, never verified
    record_events(db, [CustodyEvent(
        "web:full", "2026-06-14T00:00:00+00:00", "unchanged",
        "sha256:full", "sha256:full")])
    capsys.readouterr()

    main(["graph", "--all"])
    custody = json.loads(capsys.readouterr().out)["stats"]["custody"]
    assert custody == {
        "tiers": {"full": 1, "partial": 1, "reference": 1},
        "drift": {"verified": 1, "unverified": 2, "drifted": 0, "rotted": 0, "error": 0},
    }


def test_graph_stats_custody_is_independent_of_include_all(db, capsys):
    # like item_count/clusters, the custody block counts the whole stats.items
    # scope — the unlinked isolate is held custody either way, so --all (which
    # only changes which items become *nodes*) must not change the tally
    insert_item(db, make_item("web:a", links=("https://example.org/web:b",)))
    insert_item(db, make_item("web:b"))
    insert_item(db, make_item("web:isolate"))  # no edges → not a default node
    capsys.readouterr()

    main(["graph"])
    default = json.loads(capsys.readouterr().out)["stats"]
    main(["graph", "--all"])
    widened = json.loads(capsys.readouterr().out)["stats"]
    assert default["nodes"] == 2 and widened["nodes"] == 3  # --all adds the isolate
    assert default["custody"] == widened["custody"] == _all_reference_unverified(3)


def test_graph_custody_block_converges_with_doctor(db, capsys):
    # the H52 convergence: graph's custody totals equal doctor's for the same
    # whole-library scope, with the one vocabulary mapping (ledger `unchanged`
    # is the posture `verified`)
    insert_item(db, make_item("web:full", raw_text="<raw>b</raw>",
                              extracted_text="b", content_hash="sha256:full"))
    insert_item(db, make_item("web:partial", extracted_text="b"))
    insert_item(db, make_item("web:ref"))
    record_events(db, [CustodyEvent(
        "web:full", "2026-06-14T00:00:00+00:00", "drifted",
        "sha256:full", "sha256:new")])
    capsys.readouterr()

    main(["graph"])
    custody = json.loads(capsys.readouterr().out)["stats"]["custody"]
    drift = run_doctor(get_paths())["custody"]
    assert custody["tiers"] == drift["tiers"]
    assert custody["drift"]["verified"] == drift["drift"]["unchanged"]
    assert custody["drift"]["unverified"] == drift["drift"]["unverified"]
    assert custody["drift"]["drifted"] == drift["drift"]["drifted"]


def test_graph_over_drops_links_to_items_outside_the_given_set():
    a = make_item("web:a", links=("https://example.org/web:b",))
    b = make_item("web:b")
    # only `a` is in the set: its link's target identity isn't indexed,
    # so the edge is dropped — the rendered-only behavior kb.py relies on
    assert graph_over([a]).edges == ()
    assert [(e.from_id, e.to_id) for e in graph_over([a, b]).edges] == [("web:a", "web:b")]
