"""The surface-parity contract (roadmap H397) — one completeness-asserted invariant.

The fourth **contract-consolidation** cell (after H388's whole-MCP determinism
contract, H395's round-trip contract, and H396's regeneration-safety contract).
It lifts the scattered pairwise/per-axis convergence guards in
`tests/test_custody_convergence.py` (`test_every_surface_agrees_on_an_items_drift
_posture`, `test_list_stats_custody_member_converges_with_facets`, …) to a single
**(surface × axis) matrix** guard, so the parity claim is pinned *once* in one
obvious place rather than re-stated per surface per axis.

The claim (custody-vision §2.6, the PRD "surface parity" success metric): for
*every* held item, its custody axes read **identically** across the browse-and-
enumerate family — `search` ≡ `list` ≡ the MCP `search_scrolls`/`list_scrolls`
twins ≡ `facets`. The per-item surfaces carry the axes as row fields; `facets` is
the aggregate counterpart, so its per-value counts must equal the tally of the
per-item axis. They meet at one canonical projection read straight from the
custody primitives (`get_fidelity` / `drift_posture` / `work_membership` /
`content_duplicate_ids`), so a surface re-deriving an axis differently desyncs
from the canonical and fails *its* cell — not every test that happens to touch it.

Two faces, the H388/H394/H396 shape:

1. **The completeness keystone** — three ties that force a *new* surface or axis
   into the matrix before it can ship:
   - `_PARITY_SURFACES × _CUSTODY_AXES` is covered cell-for-cell by a live
     assertion or a *named* exemption — no silent gap (a new axis added to
     `_CUSTODY_AXES`, or a new surface to `_PARITY_SURFACES`, fails until wired);
   - the per-item axes the browse row carries are exactly the custody-bearing
     fields of the live `item_summary` + `hit_payload` shapes (a *new custody
     field* on the row fails until it joins `_CUSTODY_AXES` or the named
     non-custody set);
   - the parity surfaces partition the live read registries (`_CLI_READ_PATHS`/
     H394, `_MCP_READ_TOOLS`/H388, each already held to the live argparse / MCP
     surface), so a *new browse surface* fails until classified as a parity
     surface or a named exemption.

2. **The matrix guard** — over one wide non-vacuous fixture (every fidelity tier,
   every drift posture, a content-duplicate pair, a two-representation work),
   every (surface, axis) cell agrees with the canonical; and a sabotage that
   re-derives one axis on one surface fails *only* that cell.
"""

import json
from collections import Counter

import pytest

import scrolls.cli as cli
import scrolls.mcp_server as mcp_server
from scrolls.cli import main
from scrolls.custody import CustodyEvent, drift_posture, latest_events, record_events
from scrolls.items import (
    ScrollItem,
    content_duplicate_ids,
    get_fidelity,
    insert_item,
    item_summary,
    list_items,
)
from scrolls.paths import get_paths
from scrolls.search import SearchHit, hit_payload
from scrolls.works import membership_payload, work_membership

# The read registries the H388/H394 contracts hold to the live MCP / argparse
# surfaces. Keying the parity-surface classification to them makes a *new* read
# command/tool force a parity-or-exempt decision here too (it first fails
# H388/H394 until registered, then this contract until classified).
from test_cli_determinism import _CLI_READ_PATHS  # noqa: E402
from test_mcp import _MCP_READ_TOOLS  # noqa: E402


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
        saved_at="2026-06-12T00:00:00+00:00",
        title=title,
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def _seed_surface_parity_mix(db):
    """A wide library where every custody axis is non-vacuous on every surface.

    So the per-item / aggregate parity below is real (an all-`full`, all-`unique`
    library would pass a mis-derived axis too). Every title carries "topic" so a
    `topic` search returns the whole library — each per-item surface enumerates
    every held item:

    - **fidelity** spans all three tiers — six `full` (raw + hash), one `partial`
      (extracted only), one `reference` (`crossref:work`, a pointer);
    - **drift** spans all five postures — `verified` (`web:dup1`, re-checked
      unchanged), `drifted`, `rotted`, `error`, and `unverified` (never checked);
    - **works** — `arxiv:work` (a full preprint) + `crossref:work` (its published
      record) share one DOI → a two-representation work, so both carry a non-empty
      `works` membership while every other item carries `[]`;
    - **content-duplicate** — `web:dup1`/`web:dup2` are byte-identical (one
      `content_hash`) → the `duplicate` bucket; every other item is `unique`.
    """
    insert_item(db, _item(
        "web:dup1", "Topic full dup one",
        extracted_text="same dup body", raw_text="<raw>dup</raw>",
        content_hash="sha256:dup"))
    insert_item(db, _item(
        "web:dup2", "Topic full dup two",
        extracted_text="same dup body", raw_text="<raw>dup</raw>",
        content_hash="sha256:dup"))
    insert_item(db, _item(
        "web:drift", "Topic full drift",
        extracted_text="topic drift", raw_text="<raw>drift</raw>",
        content_hash="sha256:wd"))
    insert_item(db, _item(
        "web:rot", "Topic full rot",
        extracted_text="topic rot", raw_text="<raw>rot</raw>",
        content_hash="sha256:rt"))
    insert_item(db, _item(
        "web:err", "Topic full err",
        extracted_text="topic err", raw_text="<raw>err</raw>",
        content_hash="sha256:er"))
    insert_item(db, _item(
        "web:partial", "Topic partial", extracted_text="topic partial body"))
    # a two-representation work: a full preprint + its reference-only record,
    # both DOI-linked so they cluster (the DOI needs a ≥4-digit registrant)
    insert_item(db, _item(
        "arxiv:work", "Topic arxiv work", source="arxiv",
        url="https://arxiv.org/abs/work", extracted_text="topic arxiv work",
        raw_text="<raw>arxiv work</raw>", content_hash="sha256:aw",
        links=("https://doi.org/10.7000/w",), stage="rendered"))
    insert_item(db, _item(
        "crossref:work", "Topic crossref work", source="crossref",
        url="https://example.org/crossref-work",
        links=("https://doi.org/10.7000/w",), stage="rendered"))
    record_events(db, [
        CustodyEvent("web:dup1", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:dup", "sha256:dup", None),
        CustodyEvent("web:drift", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:wd", "sha256:x", None),
        CustodyEvent("web:rot", "2026-06-14T00:00:00+00:00", "rotted",
                     "sha256:rt", None, "HTTP Error 404"),
        CustodyEvent("web:err", "2026-06-14T00:00:00+00:00", "error",
                     "sha256:er", None, "boom"),
        # web:dup2, web:partial, arxiv:work, crossref:work left unverified
    ])


# --- the (surface × axis) registry — the completeness keystone ---------------

# The four per-item custody axes a browse surface reports, each with its canonical
# per-item projection read straight from the custody primitives.
_CUSTODY_AXES = ("fidelity", "drift", "works", "content_duplicate")


def _canonical_axes(db):
    """`{axis: {item_id: value}}` — the canonical custody projection.

    The one source of truth every surface is held to: `get_fidelity` (the
    holdings tier), `drift_posture` over the latest verify-ledger verdict (the
    drift posture), `membership_payload(work_membership(...))` (the scholarly-work
    membership), and `content_duplicate_ids` collapsed to a `duplicate`/`unique`
    bucket (the content-identity partition `facets content-duplicate` counts).
    """
    items = list_items(db)
    verdicts = latest_events(db)
    membership = work_membership(items)
    return {
        "fidelity": {item.id: get_fidelity(item) for item in items},
        "drift": {item.id: drift_posture(verdicts.get(item.id)) for item in items},
        "works": {item.id: membership_payload(membership.get(item.id, ())) for item in items},
        "content_duplicate": {
            item.id: "duplicate" if content_duplicate_ids(item, items) else "unique"
            for item in items
        },
    }


# Which browse-row field each axis rides on the *per-item* surfaces — `None` when
# no per-item browse row carries it (the content-duplicate *siblings* read rides
# the inspect surface `show`/`get_scroll`, H328, not the browse row).
_AXIS_ROW_KEY = {
    "fidelity": "fidelity",
    "drift": "drift",
    "works": "works",
    "content_duplicate": None,
}

# Which `facets` field counts each axis on the *aggregate* surface — `None` when
# `facets` has no dimension for it (there is no works facet).
_AXIS_FACET_FIELD = {
    "fidelity": "fidelity",
    "drift": "drift",
    "works": None,
    "content_duplicate": "content-duplicate",
}

# The five browse surfaces this contract pins at parity. The per-item surfaces
# return one row per held item; the aggregate surface returns per-value counts.
_PER_ITEM_SURFACES = ("search", "list", "search_scrolls", "list_scrolls")
_AGGREGATE_SURFACES = ("facets",)
_PARITY_SURFACES = _PER_ITEM_SURFACES + _AGGREGATE_SURFACES

# The cells genuinely not exposed by a surface — each *named*, never a silent
# skip: the per-item browse rows carry no content-duplicate field (only the
# aggregate + inspect surfaces do), and `facets` has no works dimension.
_EXEMPT_CELLS = {
    ("search", "content_duplicate"):
        "browse row names no content-duplicate siblings; that per-item read rides "
        "show/get_scroll (content_duplicate_ids, H328), the aggregate rides facets",
    ("list", "content_duplicate"):
        "browse row names no content-duplicate siblings; rides show/get_scroll (H328)",
    ("search_scrolls", "content_duplicate"):
        "browse row names no content-duplicate siblings; rides get_scroll (H328)",
    ("list_scrolls", "content_duplicate"):
        "browse row names no content-duplicate siblings; rides get_scroll (H328)",
    ("facets", "works"):
        "facets has no works dimension; work membership is a per-item consolidation "
        "fact, pinned per-item on the four browse surfaces above",
}


def _per_item_rows(surface, capsys):
    """`{item_id: row}` for a per-item surface over the whole-library `topic` read."""
    if surface == "search":
        assert main(["search", "topic"]) == 0
        rows = json.loads(capsys.readouterr().out)
    elif surface == "list":
        assert main(["list"]) == 0
        rows = json.loads(capsys.readouterr().out)
    elif surface == "search_scrolls":
        rows = mcp_server.search_scrolls("topic")
    elif surface == "list_scrolls":
        rows = mcp_server.list_scrolls()
    else:  # pragma: no cover - guarded by the keystone
        raise AssertionError(f"unknown per-item surface {surface!r}")
    return {row["id"]: row for row in rows}


def _facet_counts(field, capsys):
    """`{value: count}` for one `facets` dimension."""
    assert main(["facets", field]) == 0
    entries = json.loads(capsys.readouterr().out)["facets"][field]
    return {entry["value"]: entry["count"] for entry in entries}


def _on_the_wire(value):
    """The JSON form a surface actually emits — the honest cross-surface basis.

    A surface's parity is what an agent *reads*, i.e. its serialized JSON: the
    CLI prints through `json.dumps`, so its `works` is a JSON array (Python
    `list`); MCP returns native objects (`works` is a `tuple`, a JSON array only
    once FastMCP serializes it). A `tuple` and a `list` are the *same* array on
    the wire, so normalise both through JSON before comparing — the "normalise the
    CLI JSON shape to the MCP payload shape" the cross-transport contract (H400)
    anticipates. Strings/None pass through unchanged.
    """
    return json.dumps(value, sort_keys=True)


def _parity_failures(db, capsys):
    """The set of (surface, axis) cells that disagree with the canonical projection.

    The matrix guard asserts this is empty; the sabotage asserts it is exactly the
    one cell it broke. Per-item surfaces are compared item-for-item (each returned
    row's axis value equals the canonical); the aggregate surface is compared
    count-for-count (each facet's per-value count equals the tally of the canonical
    axis over the whole library). Values are compared on the wire (`_on_the_wire`),
    so a `tuple`/`list` JSON-array difference is not a false desync. Exempt cells
    (`_AXIS_ROW_KEY`/`_AXIS_FACET_FIELD` `None`) are skipped — they carry no reading
    to disagree.
    """
    canonical = _canonical_axes(db)
    failures = set()
    for surface in _PER_ITEM_SURFACES:
        rows = _per_item_rows(surface, capsys)
        for axis in _CUSTODY_AXES:
            key = _AXIS_ROW_KEY[axis]
            if key is None:
                continue
            reading = {item_id: _on_the_wire(row[key]) for item_id, row in rows.items()}
            expected = {
                item_id: _on_the_wire(canonical[axis][item_id]) for item_id in rows
            }
            if reading != expected:
                failures.add((surface, axis))
    for axis in _CUSTODY_AXES:
        field = _AXIS_FACET_FIELD[axis]
        if field is None:
            continue
        counts = _facet_counts(field, capsys)
        expected = dict(Counter(canonical[axis].values()))
        if counts != expected:
            failures.add(("facets", axis))
    return failures


# --- keystone 1: the matrix is complete (no unclassified cell) ---------------


def test_surface_parity_matrix_is_complete():
    """Every (surface × axis) cell is a live parity assertion or a *named*
    exemption — so a new axis in `_CUSTODY_AXES` or a new surface in
    `_PARITY_SURFACES` fails until its cells are wired. The H388 registry-
    completeness mechanism on the (surface, axis) cross product."""
    cross = {(s, a) for s in _PARITY_SURFACES for a in _CUSTODY_AXES}
    live = set()
    for surface in _PER_ITEM_SURFACES:
        for axis in _CUSTODY_AXES:
            if _AXIS_ROW_KEY[axis] is not None:
                live.add((surface, axis))
    for axis in _CUSTODY_AXES:
        if _AXIS_FACET_FIELD[axis] is not None:
            live.add(("facets", axis))
    # live and exempt are disjoint and together cover the whole matrix
    assert live.isdisjoint(_EXEMPT_CELLS)
    assert live | set(_EXEMPT_CELLS) == cross
    # sanity: the matrix is non-trivial — the load-bearing fidelity/drift axes are
    # live on every surface, and each axis is live on at least one surface
    for axis in ("fidelity", "drift"):
        for surface in _PARITY_SURFACES:
            assert (surface, axis) in live
    for axis in _CUSTODY_AXES:
        assert any((surface, axis) in live for surface in _PARITY_SURFACES)


# --- keystone 2: the axes are exactly the row's custody-bearing fields -------

# Browse-row fields that are *not* custody axes — each named so a new custody
# field on `item_summary`/`hit_payload` fails the partition until classified.
_NON_CUSTODY_ROW_FIELDS = {
    "id", "source", "url", "title", "category", "stage", "saved_at",
    "last_checked",   # the time axis of drift, pinned by the H88 last_checked invariant
    "classification",  # how the category was derived (H26), pinned by enrichment-provenance
    "score", "snippet", "matched_fields", "match_strength",  # search-only rank fields
}


def test_custody_axes_cover_the_browse_row_shape():
    """The per-item axes the browse row carries are exactly the custody-bearing
    fields of the live `item_summary` + `hit_payload` shapes — so a *new custody
    field* on either row fails until it joins `_CUSTODY_AXES` (carried) or the
    named non-custody set. The H364 registry-completeness mechanism on the
    browse-row field shape."""
    classified = _item(
        "web:probe", "Probe", extracted_text="x", raw_text="<raw>x</raw>",
        content_hash="sha256:probe",
        provenance={"classified_by": "rules-v1", "classified_basis": "weak-source",
                    "classified_ruleset": "deadbeef0000"})
    summary_keys = set(item_summary(classified, [], drift="verified",
                                    last_checked="2026-06-14T00:00:00+00:00").keys())
    hit = SearchHit(
        id="web:probe", source="web", title="Probe", url="u", stage="fetched",
        score=1.0, snippet="x", fidelity="full",
        classification={"method": "rules-v1"})
    row_keys = summary_keys | set(hit_payload(hit).keys())
    # every non-custody field this contract names is really a row field (the set
    # can't rot into naming fields that no longer exist)
    assert _NON_CUSTODY_ROW_FIELDS <= row_keys
    carried = {_AXIS_ROW_KEY[axis] for axis in _CUSTODY_AXES if _AXIS_ROW_KEY[axis]}
    assert carried == row_keys - _NON_CUSTODY_ROW_FIELDS


# --- keystone 3: the parity surfaces partition the live read registries ------

# The CLI read commands this contract treats as parity browse surfaces, vs the
# rest of the CLI read surface — each named with where its per-item parity (or
# aggregate honesty) is actually pinned.
_CLI_PARITY_SURFACES = {"search", "list", "facets"}
_CLI_NON_PARITY_READS = {
    "works": "consolidation surface; per-item parity pinned by the H64 works-rep invariant",
    "graph": "relationship surface; per-item parity pinned by H56/H59",
    "related": "relationship surface; per-item parity pinned by H56/H59",
    "context": "model-facing bundle; excerpt custody pinned by H94",
    "doctor": "whole-library audit aggregate (H367/H375), not a per-item browse row",
    "status": "boot custody scalar (H367), not a per-item browse row",
    "history": "per-item ledger timeline (H70), not a custody-axis browse row",
    "maintain": "maintenance-ledger read (H377), not a browse row",
    "show": "single-item inspect surface (H61), not an enumerate surface",
    "archive list": "archive recovery read, not a custody-axis browse row",
    "archive show": "archive recovery read, not a custody-axis browse row",
}

_MCP_PARITY_SURFACES = {"search_scrolls", "list_scrolls"}
_MCP_NON_PARITY_READS = {
    "list_facets": "aggregate facets twin; the CLI `facets` aggregate carries the "
                   "parity leg, CLI≡MCP facet parity pinned elsewhere",
    "get_scroll": "single-item inspect twin of `show` (H61)",
    "get_scroll_history": "per-item ledger timeline twin of `history` (H70)",
    "get_related_scrolls": "relationship surface twin of `related`",
    "get_link_graph": "relationship surface twin of `graph`",
    "get_works": "consolidation surface twin of `works`",
    "get_context_bundle": "model-facing bundle twin of `context`",
    "get_concept_page": "compiled-page render, not a custody-axis browse row",
    "get_tag_page": "compiled-page render, not a custody-axis browse row",
    "list_sources": "source roster, not a per-item custody browse row",
    "list_archived": "archive recovery read",
    "get_archived": "archive recovery read",
    "get_library_health": "whole-library audit aggregate twin of `doctor`/`status` (H381)",
    "get_maintenance_history": "maintenance-ledger read twin of `maintain --history`",
    "list_feed_subscriptions": "feed roster, not a per-item custody browse row",
}


def test_parity_surfaces_classify_the_live_read_registries():
    """The CLI/MCP parity surfaces partition the live read registries
    (`_CLI_READ_PATHS`/H394, `_MCP_READ_TOOLS`/H388, each already held to the live
    argparse / MCP surface) — so a *new browse surface* fails until it is a
    declared parity surface or a named exemption. The H394 mechanism on the
    surface-parity axis."""
    cli_reads = {" ".join(path) for path in _CLI_READ_PATHS}
    assert _CLI_PARITY_SURFACES.isdisjoint(_CLI_NON_PARITY_READS)
    assert _CLI_PARITY_SURFACES | set(_CLI_NON_PARITY_READS) == cli_reads

    assert _MCP_PARITY_SURFACES.isdisjoint(_MCP_NON_PARITY_READS)
    assert _MCP_PARITY_SURFACES | set(_MCP_NON_PARITY_READS) == set(_MCP_READ_TOOLS)

    # the surfaces enumerated in the matrix are exactly the CLI + MCP parity sets
    assert set(_PARITY_SURFACES) == _CLI_PARITY_SURFACES | _MCP_PARITY_SURFACES


# --- the matrix guard --------------------------------------------------------


def test_every_browse_surface_agrees_on_every_custody_axis(scrolls_home, capsys):
    """Over the wide non-vacuous fixture, every (surface, axis) cell agrees with
    the canonical custody projection — `search` ≡ `list` ≡ `search_scrolls` ≡
    `list_scrolls` ≡ `facets`, per item per axis. The one invariant the scattered
    pairwise convergence tests pinned piecemeal."""
    main(["init"])
    db = get_paths().db_path
    _seed_surface_parity_mix(db)
    capsys.readouterr()

    # sanity: the fixture is non-vacuous on every axis (a mis-derivation has a
    # wrong value to land on, not 0 == 0)
    canonical = _canonical_axes(db)
    assert set(canonical["fidelity"].values()) == {"full", "partial", "reference"}
    assert set(canonical["drift"].values()) == {
        "verified", "unverified", "drifted", "rotted", "error"}
    assert sum(1 for membership in canonical["works"].values() if membership) == 2
    assert sum(1 for bucket in canonical["content_duplicate"].values()
               if bucket == "duplicate") == 2

    assert _parity_failures(db, capsys) == set()


def test_a_single_surface_re_deriving_one_axis_fails_only_that_cell(
    scrolls_home, capsys, monkeypatch
):
    """The sabotage proves the matrix has teeth and is *isolating*: re-deriving one
    axis on one surface fails *only* that (surface, axis) cell, not its twins.

    `cli.item_summary` is the CLI `list` row builder, a *distinct* module binding
    from `mcp_server.item_summary` (the `list_scrolls` twin) and `hit_payload`
    (the two search surfaces) — so claiming the drifted source is clean on the CLI
    list desyncs only `(list, drift)`. The aggregate `facets` reads the ledger
    directly, untouched. This is the regression the matrix catches that a
    surface's own tests miss."""
    main(["init"])
    db = get_paths().db_path
    _seed_surface_parity_mix(db)
    capsys.readouterr()

    # baseline: clean
    assert _parity_failures(db, capsys) == set()

    real_item_summary = cli.item_summary

    def _wrong(item, works=None, drift="unverified", last_checked=None):
        if item.id == "web:drift":
            drift = "verified"  # claim the drifted source is clean — a real desync
        return real_item_summary(item, works, drift=drift, last_checked=last_checked)

    monkeypatch.setattr(cli, "item_summary", _wrong)

    assert _parity_failures(db, capsys) == {("list", "drift")}
