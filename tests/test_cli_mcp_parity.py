"""The CLI↔MCP read-parity contract (roadmap H400) — one completeness-asserted invariant.

The seventh **contract-consolidation** cell (after H388's whole-MCP determinism
contract, H395's round-trip contract, H396's regeneration-safety contract, H397's
intra-CLI surface-parity matrix, H398's completeness-honesty contract, and H399's
re-import idempotency contract). It is the **cross-transport** sibling of H397:
where H397 pins that the *browse-and-enumerate* family (`search` ≡ `list` ≡ the MCP
`search_scrolls`/`list_scrolls` twins ≡ `facets`) reads one item's custody axes
identically, this lifts the scattered per-twin **inspect + aggregate** convergence
guards in `tests/test_custody_convergence.py` (`get_scroll`≡`show`,
`get_library_health`≡`status`/`doctor`, `get_works`≡`works`,
`get_link_graph`≡`graph`) to a single matrix guard, so the cross-transport custody
parity claim is pinned *once* over an enumerated twin registry rather than re-stated
per pair.

The claim (custody-vision §2.6, the PRD "surface parity" success metric on the
cross-transport axis): for *every* read a library exposes on **both** transports,
its custody-bearing payload reads **identically** across the (CLI command, MCP tool)
twin — the per-item custody axes (`fidelity`/`drift`/`last_checked`/
`content_duplicate_ids`) on the inspect twin, and the aggregate `custody` block on
the health/graph/works twins. The two transports meet at one shared builder
(`_cmd_show`/`get_scroll` build the same payload; `graph`/`get_link_graph` both call
`graph_payload`; `works`/`get_works` both call `works_payload`;
`doctor`/`get_library_health` both fold `run_doctor`'s `custody` block), so parity
holds **by construction** today — this contract pins that "≡" so a future divergence
(one transport re-deriving a custody axis differently) fails *its* twin's leg, not
every test that happens to touch it.

Two faces, the H388/H394/H396/H397 shape:

1. **The completeness keystone** — `_CLI_MCP_TWINS` (the custody-checked twins) ∪
   three named exemption sets must partition `_MCP_READ_TOOLS` (H388) *exactly*, so a
   *new* MCP read tool fails the contract until it declares a CLI twin (checked here)
   or a named exemption:
   - `_BROWSE_PARITY_BY_H397` — the browse-enumerate twins whose cross-transport
     custody parity is *already* the H397 matrix's job (a custody twin checked there,
     not re-checked here);
   - `_NON_CUSTODY_AXIS_TWIN` — reads with a CLI twin that carries a *non*-custody-axis
     payload (a ledger timeline, a relation-rank list, an archive-recovery snapshot, a
     maintenance ledger, the model-facing bundle), each pinned by its own contract;
   - `_MCP_ONLY` — reads with *no* CLI JSON twin (the compiled concept/tag page renders,
     the source roster, the feed roster).
   Each declared CLI twin path is also held to the live CLI read registry
   (`_CLI_READ_PATHS`/H394), so the twin can never name a CLI command that isn't a
   registered read — the "fails until *both* contracts register it" mechanism.

2. **The matrix guard** — over the shared wide read-surface fixture
   (`seed_read_surface_determinism_mix`, every custody axis non-vacuous), each custody
   twin's CLI custody projection equals its MCP custody projection on the wire; and a
   sabotage that re-derives one custody axis on one transport fails *only* that twin.
"""

import json

import pytest

import scrolls.mcp_server as mcp_server
from scrolls.cli import main
from scrolls.items import list_items
from scrolls.paths import get_paths

from read_surface_fixture import seed_read_surface_determinism_mix

# The read registries the H388/H394 contracts hold to the live MCP / argparse
# surfaces. Keying the twin classification to `_MCP_READ_TOOLS` makes a *new* MCP
# read tool force a twin-or-exempt decision here (it first fails H388 until
# registered, then this contract until classified); checking each declared CLI twin
# against `_CLI_READ_PATHS` ties the other half to the live argparse surface.
from test_cli_determinism import _CLI_READ_PATHS  # noqa: E402
from test_mcp import _MCP_READ_TOOLS  # noqa: E402


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


# --- the shared read helpers -------------------------------------------------


def _cli_json(argv, capsys):
    """Run a CLI read command and parse its JSON stdout (draining capsys)."""
    assert main(argv) == 0
    return json.loads(capsys.readouterr().out)


def _on_the_wire(value):
    """The JSON form a surface actually emits — the honest cross-transport basis.

    The CLI prints through `json.dumps`, so its arrays are Python `list`s; MCP
    returns native objects (a `tuple` is a JSON array only once FastMCP serializes
    it). A `tuple` and a `list` are the *same* array on the wire, so normalise both
    through JSON before comparing — the H397 normalisation, on the cross-transport
    axis. Strings/None pass through unchanged.
    """
    return json.dumps(value, sort_keys=True)


def _held_ids(db):
    """Every held item id (sorted), the scope the per-item inspect twin enumerates."""
    return sorted(item.id for item in list_items(db))


# --- the per-twin custody projections ----------------------------------------

# The per-item inspect axes `show`/`get_scroll` both carry (roadmap H61/H84/H328):
# fidelity tier, drift posture, when that posture was taken, and the byte-identical
# siblings. `classification`/raw fields are not custody axes — left out so the
# projection is exactly the cross-transport custody claim.
_SCROLL_AXES = ("fidelity", "drift", "last_checked", "content_duplicate_ids")
# The per-node / per-rep custody axes the graph / works aggregate payloads carry on
# each node (the same fidelity/drift picture the browse rows carry, H150/H155).
_NODE_AXES = ("fidelity", "drift", "content_duplicate_ids")
_REP_AXES = ("fidelity", "drift")


def _scroll_projection(payload):
    return {axis: payload[axis] for axis in _SCROLL_AXES}


def _scroll_reading(db, get):
    """`{item_id: custody axes}` over every held item — the inspect twin's reading.

    `get` is the transport's single-item read (`get_scroll` or a `show <id>` thunk);
    we fold it over the whole library so the twin compares every item's inspect
    custody, the per-item counterpart of H397's enumerate matrix.
    """
    return {item_id: _scroll_projection(get(item_id)) for item_id in _held_ids(db)}


def _graph_projection(payload):
    """The graph's custody-bearing projection: the aggregate `stats.custody` block
    plus each node's per-node custody axes (whole-library scope, H195)."""
    return {
        "stats_custody": payload["stats"]["custody"],
        "by_node": {
            node["id"]: {axis: node[axis] for axis in _NODE_AXES}
            for node in payload["nodes"]
        },
    }


def _works_projection(payload):
    """The works' custody-bearing projection: the aggregate `stats.custody` block,
    plus each work's consolidation `custody` verdict, `content_duplicate` flag, and
    its representations' per-rep custody axes (the representation scope, H195/H261)."""
    return {
        "stats_custody": payload["stats"]["custody"],
        "by_work": {
            work["doi"]: {
                "custody": work["custody"],
                "content_duplicate": work["content_duplicate"],
                "reps": {
                    rep["id"]: {axis: rep[axis] for axis in _REP_AXES}
                    for rep in work["representations"]
                },
            }
            for work in payload["works"]
        },
    }


def _health_custody_block(payload):
    """The aggregate custody block both transports fold from `run_doctor` (H381).

    `get_library_health` returns exactly the `doctor` `custody` block *spread* with
    two distilled members (`attention`/`headline`) — `scrolls status` adds the same
    two beside the block, the H367 scalar-to-nested precedent. Strip them so the twin
    compares the shared custody block field-for-field; the `attention`/`headline`
    convergence is H367's own pin (status ≡ doctor).
    """
    return {key: value for key, value in payload.items()
            if key not in ("attention", "headline")}


# --- the twin registry — the completeness keystone ---------------------------

# The custody-checked CLI↔MCP twins: each MCP read tool whose CLI twin carries a
# comparable custody-bearing payload, with the CLI argv, the canonical projection,
# and how the two transports' payload shapes are read into it. These are exactly the
# inspect + aggregate reads H397's browse-enumerate matrix does *not* cover (it
# exempts content-duplicate to "rides show/get_scroll", and works/graph/doctor/status
# to "consolidation/relationship/audit surfaces, not a per-item browse row").
_CLI_MCP_TWINS = {
    "get_scroll": {
        "cli": ("show",),
        "label": "get_scroll ≡ show",
        # the per-item inspect twin — the H328 content-duplicate axis lives here
        "reading": lambda db, capsys: _scroll_reading(
            db, lambda item_id: _cli_json(["show", item_id], capsys)),
        "mcp_reading": lambda db: _scroll_reading(db, mcp_server.get_scroll),
    },
    "get_link_graph": {
        "cli": ("graph",),
        "label": "get_link_graph ≡ graph",
        "reading": lambda db, capsys: _graph_projection(_cli_json(["graph"], capsys)),
        "mcp_reading": lambda db: _graph_projection(mcp_server.get_link_graph()),
    },
    "get_works": {
        "cli": ("works",),
        "label": "get_works ≡ works",
        "reading": lambda db, capsys: _works_projection(_cli_json(["works"], capsys)),
        "mcp_reading": lambda db: _works_projection(mcp_server.get_works()),
    },
    "get_library_health": {
        "cli": ("doctor",),
        "label": "get_library_health ≡ doctor (≡ status, H367)",
        "reading": lambda db, capsys: _cli_json(["doctor"], capsys)["custody"],
        "mcp_reading": lambda db: _health_custody_block(mcp_server.get_library_health()),
    },
}

# The browse-enumerate twins whose cross-transport custody parity is *already* the
# H397 surface-parity matrix's job (`search`≡`search_scrolls`, `list`≡`list_scrolls`,
# `facets`≡`list_facets` on fidelity/drift/works/content-duplicate). Named here so a
# new browse tool is forced into one matrix or the other, never a silent gap.
_BROWSE_PARITY_BY_H397 = {
    "search_scrolls": "browse-enumerate twin of `search`; custody parity pinned by H397",
    "list_scrolls": "browse-enumerate twin of `list`; custody parity pinned by H397",
    "list_facets": "aggregate-count twin of `facets`; custody-count parity pinned by H397",
}

# Reads with a CLI twin that carries a *non*-custody-axis payload — each pinned by its
# own contract (a ledger timeline, a relation-rank list, an archive-recovery snapshot,
# a maintenance ledger, the model-facing bundle). The CLI twin path is held to the
# live read registry below, so these still can't name a phantom command.
_NON_CUSTODY_AXIS_TWIN = {
    "get_scroll_history": ("history",
        "per-item ledger timeline twin of `history` (H70); an event list, not a "
        "custody-axis projection — determinism pinned by H388/H394"),
    "get_related_scrolls": ("related",
        "relationship-surface twin of `related`; its primary read is the explainable "
        "rank/reasons (H312/H322), per-neighbour fidelity/drift ride the shared row "
        "builders H397 pins"),
    "list_archived": ("archive list",
        "archive-recovery twin of `archive list`; recovery-read determinism/round-trip "
        "pinned by H385/H390/H394"),
    "get_archived": ("archive show",
        "archive-recovery twin of `archive show`; pinned by H385/H394"),
    "get_maintenance_history": ("maintain",
        "maintenance-ledger twin of `maintain --history` (the read mode of the "
        "`maintain` command); trend determinism pinned by H377/H383/H394"),
    "get_context_bundle": ("context",
        "model-facing bundle twin of `context`; CLI≡MCP byte-identity pinned by H382, "
        "determinism by H376"),
}

# Reads with *no* CLI JSON twin — MCP-only by construction. The compiled concept/tag
# pages are rendered into `library/` (no CLI JSON read command), the source/feed
# rosters have no CLI read counterpart (the CLI surfaces sources via the `by_source`
# custody map, and follow/unfollow/sync are writes).
_MCP_ONLY = {
    "get_concept_page": "compiled `library/concepts/*` page render; no CLI JSON twin",
    "get_tag_page": "compiled `library/tags/*` page render; no CLI JSON twin",
    "list_sources": "source roster (dict); no CLI JSON read twin — the CLI surfaces "
                    "sources via the per-source `by_source` custody map on doctor/status",
    "list_feed_subscriptions": "feed roster; no CLI read command (follow/unfollow/sync "
                               "are custody-safe writes, not reads)",
}


def _cli_keys(paths):
    """The flat `" ".join(path)` keys for a set/iterable of CLI command paths."""
    return {" ".join(path) for path in paths}


def test_cli_mcp_twin_registry_partitions_the_mcp_read_surface():
    """Every MCP read tool is a custody-checked twin or a *named* exemption — so a
    *new* MCP read tool fails until it declares a CLI twin (or an exemption). The
    H388 registry-completeness mechanism on the cross-transport parity axis."""
    checked = set(_CLI_MCP_TWINS)
    exempt = set(_BROWSE_PARITY_BY_H397) | set(_NON_CUSTODY_AXIS_TWIN) | set(_MCP_ONLY)
    # the four classes are pairwise disjoint ...
    classes = [checked, set(_BROWSE_PARITY_BY_H397),
               set(_NON_CUSTODY_AXIS_TWIN), set(_MCP_ONLY)]
    for i, left in enumerate(classes):
        for right in classes[i + 1:]:
            assert left.isdisjoint(right)
    # ... and together cover the live MCP read surface exactly (H388)
    assert checked | exempt == set(_MCP_READ_TOOLS)

    # sanity: the checked matrix is the inspect + aggregate quartet the spec names,
    # non-trivial (a registry that quietly emptied itself would pass the partition)
    assert checked == {"get_scroll", "get_link_graph", "get_works", "get_library_health"}


def test_every_declared_cli_twin_is_a_live_read_command():
    """Each CLI twin a custody/non-custody-axis entry names is a *registered* CLI read
    (`_CLI_READ_PATHS`/H394) — so the twin registry can never drift to a CLI command
    that isn't a real read. The other half of the "fails until *both* contracts
    register it" tie (the MCP half is the partition above)."""
    live = _cli_keys(_CLI_READ_PATHS)
    declared = {" ".join(twin["cli"]) for twin in _CLI_MCP_TWINS.values()}
    declared |= {cli for cli, _ in _NON_CUSTODY_AXIS_TWIN.values()}
    assert declared <= live
    # and the custody-checked twins name distinct CLI commands (no two twins collide)
    checked_cli = [" ".join(twin["cli"]) for twin in _CLI_MCP_TWINS.values()]
    assert len(checked_cli) == len(set(checked_cli))


# --- the matrix guard --------------------------------------------------------


def _twin_parity_failures(db, capsys):
    """The set of twins whose CLI custody projection disagrees with the MCP one.

    The matrix guard asserts this is empty; the sabotage asserts it is exactly the one
    twin it broke. Values are compared on the wire (`_on_the_wire`), so a `tuple`/`list`
    JSON-array difference between the CLI (`json.dumps` → list) and MCP (native tuple)
    surfaces is not a false desync.
    """
    failures = set()
    for tool, twin in _CLI_MCP_TWINS.items():
        cli_reading = twin["reading"](db, capsys)
        mcp_reading = twin["mcp_reading"](db)
        if _on_the_wire(cli_reading) != _on_the_wire(mcp_reading):
            failures.add(tool)
    return failures


def test_every_cli_mcp_read_twin_agrees_on_its_custody_payload(scrolls_home, capsys):
    """Over the wide non-vacuous fixture, each custody twin's CLI projection equals
    its MCP projection — `show`≡`get_scroll`, `graph`≡`get_link_graph`,
    `works`≡`get_works`, `doctor`≡`get_library_health` — the one invariant the
    scattered per-twin convergence tests pinned piecemeal."""
    main(["init"])
    db = get_paths().db_path
    seed_read_surface_determinism_mix(get_paths())
    capsys.readouterr()

    # sanity: the fixture is non-vacuous on every custody axis (a mis-derivation has a
    # wrong value to land on, not 0 == 0) — multi-source, multi-tier, multi-posture,
    # a duplicate pair, a multi-representation work, an at-risk posture.
    graph = mcp_server.get_link_graph()
    assert len(graph["stats"]["custody"]["by_source"]) >= 3            # ≥3 sources
    assert graph["stats"]["custody"]["tiers"]["full"] >= 1
    assert graph["stats"]["custody"]["tiers"]["reference"] >= 1        # ≥2 tiers
    postures = {node["drift"] for node in graph["nodes"]}
    assert len(postures) >= 2                                          # ≥2 drift postures
    # the content-duplicate axis rides the inspect twin (the byte-identical pair is
    # isolated, so it is no graph node — H328's "rides show/get_scroll" scope)
    assert any(mcp_server.get_scroll(item_id)["content_duplicate_ids"]
               for item_id in _held_ids(db))                           # a dup pair
    assert len(mcp_server.get_works()["works"]) >= 2                   # ≥2 works
    assert mcp_server.get_library_health()["posture"]["verdict"] in {
        "sound", "attention", "at_risk"}

    assert _twin_parity_failures(db, capsys) == set()


def test_a_single_transport_re_deriving_one_axis_fails_only_that_twin(
    scrolls_home, capsys, monkeypatch
):
    """The sabotage proves the matrix has teeth and is *isolating*: re-deriving one
    custody axis on one transport fails *only* that twin's leg, not its siblings.

    `mcp_server.get_fidelity` is the binding `get_scroll` reads an item's fidelity
    through — a *distinct* module binding from `cli.get_fidelity` (the `show` twin) and
    from the `graph`/`works`/`doctor` payload builders, which each carry their own
    `get_fidelity` (`graph.get_fidelity`/`works.get_fidelity`/`run_doctor`). So
    misreporting one full item's tier on the MCP inspect read desyncs only
    `get_scroll`≡`show`; the aggregate twins (whose fidelity is folded through their own
    builders) stay byte-identical to their CLI sides. This is the regression the
    cross-transport matrix catches that a single surface's own tests miss."""
    main(["init"])
    db = get_paths().db_path
    seed_read_surface_determinism_mix(get_paths())
    capsys.readouterr()

    # baseline: every twin agrees
    assert _twin_parity_failures(db, capsys) == set()

    real_get_fidelity = mcp_server.get_fidelity

    def _wrong(item):
        tier = real_get_fidelity(item)
        if item.id == "arxiv:dba" and tier == "full":
            return "reference"  # claim a full holding is a bare pointer — a real desync
        return tier

    monkeypatch.setattr(mcp_server, "get_fidelity", _wrong)

    assert _twin_parity_failures(db, capsys) == {"get_scroll"}
