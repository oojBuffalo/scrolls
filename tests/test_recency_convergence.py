"""H413 — the recency (`last_checked`) convergence contract.

The twentieth **contract-consolidation** cell and the *time*-axis sibling of
H397's custody-axis surface matrix and H407's rank-axis matrix. Where H397 pins
that every surface carrying a custody axis (fidelity/drift/works/content) reads
the same *value* per item as the canonical fold, and H407 pins the same for the
explainable-rank *band*, this pins it for the **recency** axis: for *every* held
item its `last_checked` — *when* the latest verify verdict was taken, or `null`
when never re-checked (roadmap H84/H88, `custody.last_checked` over the same
`latest_events` verdict `drift_posture` reads) — reads **identically** wherever a
per-item surface carries it. It lifts the scattered per-surface H88 recency tests
(`tests/test_custody_convergence.py::test_every_surface_agrees_on_an_items_last
_checked`, `tests/test_search.py`, `tests/test_related.py`) to one completeness-
asserted invariant the way H407 consolidated the strength tests.

The claim (custody-vision §2.6 / §3.1, the PRD "per-item custody picture
everywhere" success metric, cap 1/8): the *as-of-when* behind a drift posture
travels with every result and reads identically across surfaces, so an agent can
pick a `verify --stale-before <ISO>` boundary straight from any browse/inspect/
relate row and can never see one surface fabricate a recency for an item another
surface honestly reports as never re-checked.

One canonical projection read straight off the verify ledger:
`last_checked(latest_events(db).get(id))` (`custody.py`) — the stored `checked_at`
of the item's latest verify verdict, or `None` for the honest absence of a
never-re-checked item (never a fabricated wall-clock time). Every recency surface
threads that *same* primitive (`drift`/`last_checked` are read from one
`latest_events` pass per surface), so convergence holds **by construction**; the
contract's job is to catch a **surface** that re-derives or fabricates the
timestamp differently — a row inventing an "x ago", a surface claiming a
never-checked item was checked.

**A roadmap correction (the H404/H407/H409/H412 precedent).** The roadmap's H413
line names `works`/`graph` (and their MCP twins) `_NO_RECENCY_AXIS` "with no
per-item recency field". The *live* code disagrees: `works_payload`'s
per-representation rows (`works.py`) and `graph_payload`'s per-node rows
(`graph.py`) each carry `last_checked` keyed by item id, the same primitive the
flat browse rows thread (the existing scattered H88 test already pins `graph`).
So `works`/`graph`/`get_works`/`get_link_graph` are classified here as recency
surfaces, not exemptions — exactly as H407 reclassified `graph` after finding the
roadmap had wrongly called it rank-bearing (there it genuinely was *not*; here it
genuinely *is*). What stays `_NO_RECENCY_AXIS` are the surfaces that render
recency at a *different granularity* than the per-item JSON row field — the
`context` excerpt tag string (`last seen <ts>` / `never re-checked`, H90) and the
compiled group-page custody marker (`· … · checked <ts>`, H93) — plus the reads
with no per-item recency at all (the aggregates, the rosters, the ledger
timelines, the archive-recovery snapshots).

This is why the contract builds its **own** fixture rather than reuse H397's: the
H397 `_seed_surface_parity_mix` work/graph members (`arxiv:work`/`crossref:work`)
are *both* unverified, so a works/graph recency leg over it would be vacuous
(`None == None`). `_seed_recency_surface_mix` puts a re-checked member *and* a
never-checked member in the clustered work and the connected graph, so every
surface — flat, related, graph, works — spans a real timestamp **and** `null`
(the H412 build-your-own-fixture precedent when the reused mix doesn't span the
axis).

Two faces, the H388/H394/H397/H407/H412 shape:

1. **The completeness keystone** — `_RECENCY_SURFACES` (each per-item recency-
   bearing read) ∪ a named `_NO_RECENCY_AXIS` exemption set partitions the live
   read registries (`_CLI_READ_PATHS`/H394, `_MCP_READ_TOOLS`/H388) *exactly*, so
   a *new* recency-bearing read fails the contract until it declares its
   convergence.

2. **The matrix guard** — over one fixture spanning the recency axis on every
   surface (a re-checked item, a drifted item, a never-checked item, *inside* the
   clustered work and the connected graph), every surface's `{id: last_checked}`
   reading equals the canonical projection; and the decisive **anti-fabrication**
   sabotage — one surface inventing a timestamp for a *never-checked* item — fails
   *only* that surface's leg (the H397/H407 binding-isolation precedent on the M2
   honesty tie).
"""

import json

import pytest

import scrolls.cli as cli
import scrolls.mcp_server as mcp_server
from scrolls.custody import last_checked, latest_events
from scrolls.items import ScrollItem, insert_item, list_items
from scrolls.paths import get_paths
from scrolls.works import works_over

# The read registries the H394/H388 contracts hold to the live argparse / MCP
# surfaces. Keying the recency-surface classification to them makes a *new* read
# command/tool force a recency-or-exempt decision here too (it first fails
# H394/H388 until registered, then this contract until classified).
from test_cli_determinism import _CLI_READ_PATHS  # noqa: E402
from test_mcp import _MCP_READ_TOOLS  # noqa: E402

# Every fixture title carries this token, so a `search` for it returns the whole
# library and the per-item search surface enumerates every held item (the H397
# whole-library-read idiom). It is also a shared tag, so `related <seed>` reaches
# every other item (a tag edge fires for each — `scored_related`).
QUERY = "topic"

# The `related` anchor: a never-checked item, so its neighbourhood (every *other*
# item, all tag-related) still spans a real timestamp *and* `null` — the anchor's
# own `null` is excluded from a related read (a hit never includes its anchor).
_SEED = "web:never"


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


def _item(item_id, title, **overrides):
    base = dict(
        id=item_id,
        source="web",
        url=f"https://example.com/{item_id}",
        saved_at="2026-06-09T00:00:00+00:00",
        title=title,
        stage="fetched",
        tags=("topic",),
    )
    base.update(overrides)
    return ScrollItem(**base)


# The five held ids the flat per-item surfaces enumerate — fixed so a surface
# that *drops* an item (an empty read mistaken for convergence) is caught.
_FIXTURE_IDS = (
    "arxiv:dba", "crossref:dba", "web:checked", "web:drift", "web:never",
)


def _seed_recency_surface_mix(db):
    """A ring-linked library whose recency axis is non-vacuous on *every* surface.

    Five scrolls, all sharing the `topic` tag (so each matches a `topic` search
    and relates to any anchor) and ring-linked (each links to the next item's URL,
    so every item is a `graph` node — `build_graph` drops isolated nodes), with a
    DOI-clustered two-representation work folded into the ring:

    - **arxiv:dba** — a full preprint, DOI ``10.7000/dba``, **re-checked**
      (`verified` at ``2026-06-10``); ring → crossref:dba;
    - **crossref:dba** — its published reference-only record, the *same* DOI (so
      the two cluster into one work), **never re-checked** (`last_checked` None);
      ring → web:checked;
    - **web:checked** — full, re-checked (`verified` at ``2026-06-11``);
      ring → web:drift;
    - **web:drift** — full, **drifted** at ``2026-06-12`` (a real timestamp under
      a non-`verified` posture); ring → web:never;
    - **web:never** — full, **never re-checked** (`last_checked` None);
      ring → arxiv:dba (closing the ring).

    So the recency axis spans three distinct real timestamps and two `null`s, and
    — crucially — the clustered work (arxiv:dba + crossref:dba) and the connected
    graph each hold a re-checked *and* a never-checked member, so the `works` and
    `graph` recency legs are non-vacuous, not all-`None` as they would be over the
    H397 fixture.
    """
    doi = "https://doi.org/10.7000/dba"
    insert_item(db, _item(
        "arxiv:dba", "Topic arxiv dba", source="arxiv",
        extracted_text="topic arxiv body", raw_text="<raw>arxiv</raw>",
        content_hash="sha256:arxiv", stage="rendered",
        links=(doi, "https://example.com/crossref:dba")))
    insert_item(db, _item(
        "crossref:dba", "Topic crossref dba", source="crossref", stage="rendered",
        links=(doi, "https://example.com/web:checked")))
    insert_item(db, _item(
        "web:checked", "Topic web checked",
        extracted_text="topic checked body", raw_text="<raw>checked</raw>",
        content_hash="sha256:checked",
        links=("https://example.com/web:drift",)))
    insert_item(db, _item(
        "web:drift", "Topic web drift",
        extracted_text="topic drift body", raw_text="<raw>drift</raw>",
        content_hash="sha256:drift",
        links=("https://example.com/web:never",)))
    insert_item(db, _item(
        "web:never", "Topic web never",
        extracted_text="topic never body", raw_text="<raw>never</raw>",
        content_hash="sha256:never",
        links=("https://example.com/arxiv:dba",)))
    from scrolls.custody import CustodyEvent, record_events
    record_events(db, [
        CustodyEvent("arxiv:dba", "2026-06-10T00:00:00+00:00", "unchanged",
                     "sha256:arxiv", "sha256:arxiv", None),
        CustodyEvent("web:checked", "2026-06-11T00:00:00+00:00", "unchanged",
                     "sha256:checked", "sha256:checked", None),
        CustodyEvent("web:drift", "2026-06-12T00:00:00+00:00", "drifted",
                     "sha256:drift", "sha256:x", None),
        # crossref:dba + web:never left unverified → last_checked None
    ])


# --- the canonical recency projection (one source of truth) ------------------


def _canonical_recency(db):
    """`{id: last_checked(latest_events(db).get(id))}` — the per-item recency every
    surface is held to (the stored verdict timestamp, or `None` when never
    re-checked)."""
    verdicts = latest_events(db)
    return {item.id: last_checked(verdicts.get(item.id)) for item in list_items(db)}


# --- per-surface expected id sets --------------------------------------------
# Each recency surface enumerates a known slice of the library; the matrix guard
# holds the surface's reading to the canonical *over exactly that slice*, so a
# dropped or extra id is a desync, not silent convergence.


def _expected_all(db, canonical):
    """The flat browse/inspect surfaces enumerate every held item; the graph is
    fully ring-linked, so every item is a node too."""
    return set(canonical)


def _expected_neighbours(db, canonical):
    """A `related <_SEED>` read carries every *other* item (all share the `topic`
    tag) — never its anchor (a hit never includes the seed)."""
    return set(canonical) - {_SEED}


def _expected_work_reps(db, canonical):
    """`works` reports only the multi-representation clusters; here the one DOI
    work (arxiv:dba + crossref:dba). Computed from the live clustering so it can't
    drift from what the surface enumerates."""
    items = list_items(db)
    return {
        rep.id
        for work in works_over(items, min_representations=2)
        for rep in work.representations
    }


# --- per-surface recency readers (each via its own real entry point) ----------


def _read_search(capsys):
    assert cli.main(["search", QUERY]) == 0
    rows = json.loads(capsys.readouterr().out)
    return {row["id"]: row.get("last_checked") for row in rows}


def _read_list(capsys):
    assert cli.main(["list"]) == 0
    rows = json.loads(capsys.readouterr().out)
    return {row["id"]: row.get("last_checked") for row in rows}


def _read_show(capsys):
    out = {}
    for item_id in _FIXTURE_IDS:
        assert cli.main(["show", item_id]) == 0
        out[item_id] = json.loads(capsys.readouterr().out).get("last_checked")
    return out


def _read_related(capsys):
    assert cli.main(["related", _SEED]) == 0
    rows = json.loads(capsys.readouterr().out)
    return {row["id"]: row.get("last_checked") for row in rows}


def _read_graph(capsys):
    assert cli.main(["graph"]) == 0
    nodes = json.loads(capsys.readouterr().out)["nodes"]
    return {node["id"]: node.get("last_checked") for node in nodes}


def _read_works(capsys):
    assert cli.main(["works"]) == 0
    works = json.loads(capsys.readouterr().out)["works"]
    return {
        rep["id"]: rep.get("last_checked")
        for work in works
        for rep in work["representations"]
    }


def _read_search_scrolls(capsys):
    rows = mcp_server.search_scrolls(QUERY)
    return {row["id"]: row.get("last_checked") for row in rows}


def _read_list_scrolls(capsys):
    rows = mcp_server.list_scrolls()
    return {row["id"]: row.get("last_checked") for row in rows}


def _read_get_scroll(capsys):
    return {
        item_id: mcp_server.get_scroll(item_id).get("last_checked")
        for item_id in _FIXTURE_IDS
    }


def _read_get_related_scrolls(capsys):
    rows = mcp_server.get_related_scrolls(_SEED)
    return {row["id"]: row.get("last_checked") for row in rows}


def _read_get_link_graph(capsys):
    nodes = mcp_server.get_link_graph()["nodes"]
    return {node["id"]: node.get("last_checked") for node in nodes}


def _read_get_works(capsys):
    works = mcp_server.get_works()["works"]
    return {
        rep["id"]: rep.get("last_checked")
        for work in works
        for rep in work["representations"]
    }


# --- the (surface → reader, expected-ids) registry — the completeness keystone -

# Every surface that carries a per-item `last_checked` recency field, mapped to
# its reader and the slice of the library it enumerates. The matrix guard holds
# each to the canonical projection over exactly that slice.
_RECENCY_SURFACES = {
    "search": (_read_search, _expected_all),
    "list": (_read_list, _expected_all),
    "show": (_read_show, _expected_all),
    "related": (_read_related, _expected_neighbours),
    "graph": (_read_graph, _expected_all),
    "works": (_read_works, _expected_work_reps),
    "search_scrolls": (_read_search_scrolls, _expected_all),
    "list_scrolls": (_read_list_scrolls, _expected_all),
    "get_scroll": (_read_get_scroll, _expected_all),
    "get_related_scrolls": (_read_get_related_scrolls, _expected_neighbours),
    "get_link_graph": (_read_get_link_graph, _expected_all),
    "get_works": (_read_get_works, _expected_work_reps),
}

# The CLI reads that carry a per-item recency field, vs the rest (each named).
# Their union is the whole CLI read registry — so a *new* read fails the partition
# until it declares recency-or-no-recency. **Roadmap correction:** `works`/`graph`
# carry per-rep/per-node `last_checked` (works.py/graph.py), so they are recency
# surfaces, not exemptions as the roadmap line stated.
_CLI_RECENCY_READS = {"search", "list", "show", "related", "graph", "works"}
_CLI_NO_RECENCY_READS = {
    "facets": "aggregate per-value counts; no per-item recency dimension "
              "(`facets` has no `last_checked` field)",
    "doctor": "whole-library audit aggregate (H367/H375); recency is the per-item "
              "time axis, not an audit count",
    "status": "boot custody scalar (H367); not a per-item row",
    "history": "per-item verify-ledger *timeline* (H66/H70) — every verdict's "
               "`checked_at`, the source the single `last_checked` recency is the "
               "head of, not the one derived field this contract pins",
    "maintain": "maintenance-ledger read (H377); not a per-item row",
    "context": "model-facing bundle; recency rides the per-excerpt tag string "
               "(`last seen <ts>` / `never re-checked`, H90), a rendered-prose "
               "granularity, not the per-item JSON row field this contract pins",
    "archive list": "archive recovery read; snapshots carry `archived_at`, not the "
                    "live `last_checked` recency",
    "archive show": "archive recovery read; snapshots carry `archived_at`, not the "
                    "live `last_checked` recency",
}

_MCP_RECENCY_TOOLS = {
    "search_scrolls", "list_scrolls", "get_scroll",
    "get_related_scrolls", "get_link_graph", "get_works",
}
_MCP_NO_RECENCY_TOOLS = {
    "list_facets": "aggregate facets twin; no per-item recency dimension",
    "get_scroll_history": "per-item verify-ledger timeline twin of `history` (H70)",
    "get_maintenance_history": "maintenance-ledger twin of `maintain --history`",
    "get_library_health": "whole-library audit twin of `doctor`/`status` (H381)",
    "get_context_bundle": "model-facing bundle twin of `context`; recency rides the "
                          "per-excerpt tag string (H90), a different granularity",
    "get_concept_page": "compiled group-page render; recency rides the H89/H93 "
                        "custody marker string (`· … · checked <ts>`), a "
                        "rendered-prose granularity, not the per-item JSON row "
                        "field this contract pins (rendering it as a structured "
                        "field is the deferred H419 production slice)",
    "get_tag_page": "compiled group-page render; recency rides the H89/H93 custody "
                    "marker string, not a per-item JSON row field",
    "list_sources": "source roster; no per-item recency field",
    "list_archived": "archive recovery read; archived snapshots, not live recency",
    "get_archived": "archive recovery read; archived snapshots, not live recency",
    "list_feed_subscriptions": "feed roster; no per-item recency field",
}


def _recency_failures(db, capsys):
    """The set of recency surfaces that disagree with the canonical projection.

    The matrix guard asserts this is empty; the sabotage asserts it is exactly the
    one surface it broke. Each surface's `{id: last_checked}` reading must equal
    the canonical recency over the exact slice it enumerates — dict equality pins
    both completeness (every expected id present, none dropped or extra) and
    convergence (each id's timestamp the canonical one) in one comparison. Values
    are plain strings / `None`, so they compare on the wire directly."""
    canonical = _canonical_recency(db)
    failures = set()
    for key, (read, expected_ids) in _RECENCY_SURFACES.items():
        reading = read(capsys)
        expected = {item_id: canonical[item_id] for item_id in expected_ids(db, canonical)}
        if reading != expected:
            failures.add(key)
    return failures


# --- keystone 1: the recency surfaces partition the live read registries ------


def test_recency_surfaces_partition_the_live_read_registries():
    """`_RECENCY_SURFACES` ∪ the named `_NO_RECENCY_AXIS` exemptions partition the
    live read registries (`_CLI_READ_PATHS`/H394, `_MCP_READ_TOOLS`/H388) exactly
    — so a *new* recency-bearing read fails until it declares its convergence. The
    H394 registry-completeness mechanism on the recency axis."""
    cli_reads = {" ".join(path) for path in _CLI_READ_PATHS}
    assert _CLI_RECENCY_READS.isdisjoint(_CLI_NO_RECENCY_READS)
    assert _CLI_RECENCY_READS | set(_CLI_NO_RECENCY_READS) == cli_reads

    assert _MCP_RECENCY_TOOLS.isdisjoint(_MCP_NO_RECENCY_TOOLS)
    assert _MCP_RECENCY_TOOLS | set(_MCP_NO_RECENCY_TOOLS) == set(_MCP_READ_TOOLS)

    # the matrix's recency surfaces are exactly the CLI + MCP recency reads
    assert set(_RECENCY_SURFACES) == _CLI_RECENCY_READS | _MCP_RECENCY_TOOLS


# --- keystone 2: the convergence is genuinely cross-transport -----------------


def test_recency_is_pinned_cross_transport():
    """Every recency surface is exercised on **both** a CLI and an MCP twin —
    browse (`search`/`list`), inspect (`show`/`get_scroll`), relate (`related`),
    consolidate (`works`), and link-graph (`graph`) — so the convergence the matrix
    pins is genuinely cross-transport, not one-sided."""
    cli_surfaces = set(_RECENCY_SURFACES) & _CLI_RECENCY_READS
    mcp_surfaces = set(_RECENCY_SURFACES) & _MCP_RECENCY_TOOLS
    assert {"search", "list", "show", "related", "graph", "works"} <= cli_surfaces
    assert {
        "search_scrolls", "list_scrolls", "get_scroll",
        "get_related_scrolls", "get_link_graph", "get_works",
    } <= mcp_surfaces
    # every CLI recency read has its MCP twin in the matrix (and vice versa)
    assert len(cli_surfaces) == len(mcp_surfaces) == 6


# --- the matrix guard --------------------------------------------------------


def test_every_surface_reads_the_canonical_recency(scrolls_home, capsys):
    """Over the wide non-vacuous fixture, every recency surface's `{id:
    last_checked}` reading equals the canonical projection — `search` ≡ `list` ≡
    `show` ≡ `related` ≡ `graph` ≡ `works` ≡ the MCP twins, per item. The one
    invariant the scattered per-surface H88 recency tests pinned piecemeal."""
    cli.main(["init"])
    db = get_paths().db_path
    _seed_recency_surface_mix(db)
    capsys.readouterr()

    canonical = _canonical_recency(db)
    # sanity: the recency axis is non-vacuous — three distinct real timestamps and
    # two never-checked `null`s (a mis-rendered recency has a wrong value to land
    # on, not None == None)
    assert canonical == {
        "arxiv:dba": "2026-06-10T00:00:00+00:00",
        "crossref:dba": None,
        "web:checked": "2026-06-11T00:00:00+00:00",
        "web:drift": "2026-06-12T00:00:00+00:00",
        "web:never": None,
    }
    timestamps = {v for v in canonical.values() if v is not None}
    assert len(timestamps) == 3 and None in canonical.values()

    # sanity: the *subset* surfaces (related/works) — the roadmap-corrected
    # additions — each span a real timestamp *and* `null`, so their legs are real
    for expected_ids in (_expected_neighbours, _expected_work_reps):
        slice_values = {canonical[i] for i in expected_ids(db, canonical)}
        assert any(v is not None for v in slice_values), slice_values
        assert None in slice_values, slice_values
    # and the DOI work is the two-representation cluster (works enumerates it)
    assert _expected_work_reps(db, canonical) == {"arxiv:dba", "crossref:dba"}
    capsys.readouterr()

    assert _recency_failures(db, capsys) == set()


def test_one_surface_fabricating_recency_fails_only_that_surface(
    scrolls_home, capsys, monkeypatch
):
    """The sabotage proves the matrix has teeth and is *isolating* — and pins the
    decisive M2 anti-fabrication choice: inventing a recency for a *never-checked*
    item on one surface fails *only* that surface's leg, not its twins.

    `cli.item_summary` is the CLI `list` row builder — a *distinct* module binding
    from `mcp_server.item_summary` (the `list_scrolls` twin), from `hit_payload`
    (the search surfaces), and from the `show`/`related`/`graph`/`works` builders —
    so claiming a never-checked item *was* checked on the CLI list desyncs only
    `list`. The canonical reads `last_checked(latest_events(...))` directly,
    untouched. This is the cross-surface fabrication the matrix catches that a
    surface's own tests miss: an agent picking a `verify --stale-before` boundary
    off this row would skip an item it has never actually re-checked."""
    cli.main(["init"])
    db = get_paths().db_path
    _seed_recency_surface_mix(db)
    capsys.readouterr()

    # baseline: every surface converges
    assert _recency_failures(db, capsys) == set()

    real_item_summary = cli.item_summary

    def _wrong(item, works=None, drift="unverified", last_checked=None):
        if item.id == "web:never":
            # fabricate a recency for a never-checked item — the precise M2 honesty
            # violation (claiming "checked as of <ts>" where there is no verdict)
            last_checked = "2099-01-01T00:00:00+00:00"
        return real_item_summary(item, works, drift=drift, last_checked=last_checked)

    monkeypatch.setattr(cli, "item_summary", _wrong)

    assert _recency_failures(db, capsys) == {"list"}
