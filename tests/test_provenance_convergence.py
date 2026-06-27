"""H412 — the enrichment-provenance convergence contract.

The nineteenth **contract-consolidation** cell and the *enrichment*-axis sibling
of H407's rank-explainability convergence. Where H407 pins that every surface
carrying an explainable-rank band reads the same *band* per item/edge as the
canonical fold, this pins that every surface carrying a classification marker
reads the same **provenance** — the engine/method (`by`), the rules precedence
tier / LLM model (`basis`/`model`), the ruleset fingerprint (`ruleset`), and the
confidence/recency marker (`confidence`: `level` + `freshness`) — per item as the
canonical projection. It lifts the scattered per-surface classification-view tests
to one completeness-asserted invariant.

The claim (custody-vision §3.6, the PRD "re-derivable enrichment + confidence /
recency markers" success metric, cap 8): the provenance behind a derived category
— *how* it was produced and *how much to trust it* — travels with every result
and reads identically wherever it appears, so an agent can never see one surface
call a stale-ruleset category fresh while another calls it stale.

One canonical projection read straight off the stored classification record:
`classification_provenance(item)` (the `classification_view` over the item's own
`provenance`, H20/H21/H26) — the engine stamp plus the derived `confidence`
(`level` deterministic|inferred, and `freshness` current|stale|unknown against the
*live* `RULESET_FINGERPRINT`), or `None` for the honest absence of a user-set or
unclassified category. Every provenance surface threads that same view (the per-
item rows via `classification_provenance`/`classification_view`, the `facets
method` aggregate via the same `classification_view` over the row's `provenance`),
so convergence holds *by construction*; the contract's job is to catch a
**surface** that re-derives or re-renders the marker differently — a row recomputing
freshness, an aggregate that misbuckets `user-set` vs `unclassified`.

Two surface kinds, each held to that one projection:

- **per-item** — `search` hits (H26), `list`/`show` rows, and the MCP
  `search_scrolls`/`list_scrolls`/`get_scroll` twins each carry the whole
  `classification` view as a row field (omitted on honest absence). The reading is
  `{id: view-or-None}`, compared item-for-item to the canonical.
- **aggregate** — `facets method` (H28) buckets the whole library by the engine
  that produced each category (`rules-v1`/`llm-v1`, plus the honest `user-set`/
  `unclassified` buckets the per-item `None` covers). The reading is `{bucket:
  count}`, compared to the tally of the canonical bucket projection.

**A roadmap correction (the H404/H407 precedent).** The roadmap's H412 line names
the compiled `library/` group pages "(H89-family marker)" as a provenance surface.
The live H89/H93 marker (`kb._custody_marker`) renders `· fidelity · drift · when`
— the *custody* picture, not a classification-method marker; the group pages carry
no per-item enrichment provenance. So `get_concept_page`/`get_tag_page` (and their
CLI-compiled origin) are classified `_NO_PROVENANCE_AXIS` here with a named reason,
exactly as H407 reclassified `graph`/`get_link_graph` after finding the roadmap had
wrongly called them rank-bearing. (Rendering the provenance marker on the human-
browse group pages — the H89 precedent on the enrichment axis — is a separate
*production* slice, deferred; this consolidation cell stays test-only.)

Two faces, the H388/H394/H397/H407 shape:

1. **The completeness keystone** — `_PROVENANCE_SURFACES` (each classification-
   bearing read) ∪ a named `_NO_PROVENANCE_AXIS` exemption set partitions the live
   read registries (`_CLI_READ_PATHS`/H394, `_MCP_READ_TOOLS`/H388) *exactly*, so a
   *new* enrichment-bearing read fails the contract until it declares its
   provenance convergence.

2. **The matrix guard** — over one fixture spanning the whole method axis
   (`rules-v1` current + `rules-v1` stale + `llm-v1` + a `user-set` category + an
   `unclassified` item) so the confidence sub-axes (`current`/`stale`/`inferred`)
   and honest absence are all non-vacuous, every surface's `{id: view}` reading
   equals the canonical projection and the `facets method` tally equals the
   canonical bucket tally; a sabotage that re-derives one item's freshness on one
   surface fails *only* that surface's leg (the H397/H407 binding-isolation
   precedent).
"""

import json
from collections import Counter

import pytest

import scrolls.cli as cli
import scrolls.mcp_server as mcp_server
from scrolls.classify import RULESET_FINGERPRINT
from scrolls.items import (
    ScrollItem,
    classification_provenance,
    insert_item,
    list_items,
)
from scrolls.paths import get_paths

# The read registries the H394/H388 contracts hold to the live argparse / MCP
# surfaces. Keying the provenance-surface classification to them makes a *new*
# read command/tool force a provenance-or-exempt decision here too (it first fails
# H394/H388 until registered, then this contract until classified).
from test_cli_determinism import _CLI_READ_PATHS  # noqa: E402
from test_mcp import _MCP_READ_TOOLS  # noqa: E402

# Every fixture title carries this token, so a `search` for it returns the whole
# library and the per-item search surface enumerates every held item (the H397
# whole-library-read idiom).
QUERY = "topic"


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
        saved_at="2026-06-20T00:00:00+00:00",
        title=title,
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def _seed_provenance_surface_mix(db):
    """A library spanning the whole classification-method axis, so the matrix is
    non-vacuous (an all-`rules-v1`-current library would pass a mis-rendered
    freshness too). Five items, one per method bucket / confidence sub-axis:

    - **rules-v1, current** — classified under the *live* ruleset fingerprint, so
      `confidence.freshness == "current"` (a re-classify would reproduce it);
    - **rules-v1, stale** — classified under a *different* fingerprint, so
      `freshness == "stale"` (the ruleset has moved; the category may no longer
      hold) — the load-bearing case the sabotage flips;
    - **llm-v1** — an inferred category, `confidence.level == "inferred"` with *no*
      freshness (no ruleset to compare; claiming one would be fabrication);
    - **user-set** — a category with no engine stamp (`scrolls set`), so the
      per-item view is `None` (honest absence) and the `facets method` bucket is
      `user-set`;
    - **unclassified** — no category at all, view `None`, `facets` bucket
      `unclassified`.

    Every title carries `QUERY` ("topic"), so each per-item surface — `search`
    included — enumerates all five.
    """
    insert_item(db, _item(
        "web:rules-current", "Topic rules current", category="lit",
        provenance={"classified_by": "rules-v1", "classified_basis": "source-domain",
                    "classified_ruleset": RULESET_FINGERPRINT}))
    insert_item(db, _item(
        "web:rules-stale", "Topic rules stale", category="lit",
        provenance={"classified_by": "rules-v1", "classified_basis": "source-domain",
                    "classified_ruleset": "deadbeef0000"}))
    insert_item(db, _item(
        "web:llm", "Topic llm note", category="research",
        provenance={"classified_by": "llm-v1", "classified_model": "claude-x"}))
    insert_item(db, _item(
        "web:userset", "Topic user set", category="manual",
        provenance={"adapter": "web"}))
    insert_item(db, _item(
        "web:unclassified", "Topic unclassified", provenance={"adapter": "web"}))


# --- the canonical provenance projection (one source of truth) ---------------

# The five held ids the per-item surfaces enumerate — fixed so a surface that
# *drops* an item (an empty read mistaken for convergence) is caught.
_FIXTURE_IDS = (
    "web:rules-current", "web:rules-stale", "web:llm", "web:userset",
    "web:unclassified",
)


def _canonical_view(db):
    """`{id: classification_provenance(item)}` — the per-item view every per-item
    surface is held to (the engine stamp + derived confidence, or `None`)."""
    return {item.id: classification_provenance(item) for item in list_items(db)}


def _canonical_method_tally(db):
    """`{bucket: count}` — the method tally `facets method` is held to.

    Derived from the *per-item* view primitive (`classification_provenance` +
    `category`), the same `classification_view` the per-item surfaces thread — so
    the aggregate is cross-checked against the per-item projection, not against the
    `facets` fold itself. Mirrors `facets._method_bucket`: the engine `by` when a
    view is present, else `user-set` for a hand-set category and `unclassified` for
    none."""
    counts: Counter = Counter()
    for item in list_items(db):
        view = classification_provenance(item)
        if view is not None:
            counts[view["by"]] += 1
        elif item.category is not None:
            counts["user-set"] += 1
        else:
            counts["unclassified"] += 1
    return dict(counts)


def _on_the_wire(value):
    """The JSON form a surface actually emits — the honest cross-surface basis.

    A surface's parity is what an agent *reads*, i.e. its serialized JSON. The CLI
    prints through `json.dumps`; MCP returns native objects FastMCP later
    serializes. Normalise both (and `None` → `"null"`) through JSON with sorted
    keys before comparing, so a key-order or dict-vs-mapping difference is not a
    false desync (the H397/H400 normalisation on the enrichment axis)."""
    return json.dumps(value, sort_keys=True)


# --- per-surface provenance readers (each via its own real entry point) ------


def _read_search(capsys):
    assert cli.main(["search", QUERY]) == 0
    rows = json.loads(capsys.readouterr().out)
    return {row["id"]: row.get("classification") for row in rows}


def _read_list(capsys):
    assert cli.main(["list"]) == 0
    rows = json.loads(capsys.readouterr().out)
    return {row["id"]: row.get("classification") for row in rows}


def _read_show(capsys):
    out = {}
    for item_id in _FIXTURE_IDS:
        assert cli.main(["show", item_id]) == 0
        out[item_id] = json.loads(capsys.readouterr().out).get("classification")
    return out


def _read_search_scrolls(capsys):
    rows = mcp_server.search_scrolls(QUERY)
    return {row["id"]: row.get("classification") for row in rows}


def _read_list_scrolls(capsys):
    rows = mcp_server.list_scrolls()
    return {row["id"]: row.get("classification") for row in rows}


def _read_get_scroll(capsys):
    return {
        item_id: mcp_server.get_scroll(item_id).get("classification")
        for item_id in _FIXTURE_IDS
    }


def _read_facets_method(capsys):
    assert cli.main(["facets", "method"]) == 0
    entries = json.loads(capsys.readouterr().out)["facets"]["method"]
    return {entry["value"]: entry["count"] for entry in entries}


# --- the (surface → kind, reader) registry — the completeness keystone --------

# Every surface that carries a classification provenance marker, mapped to its
# kind (`per_item` view vs `aggregate` method tally) and its reader. The matrix
# guard holds each to the canonical projection.
_PROVENANCE_SURFACES = {
    "search": ("per_item", _read_search),
    "list": ("per_item", _read_list),
    "show": ("per_item", _read_show),
    "search_scrolls": ("per_item", _read_search_scrolls),
    "list_scrolls": ("per_item", _read_list_scrolls),
    "get_scroll": ("per_item", _read_get_scroll),
    "facets": ("aggregate", _read_facets_method),
}

# The CLI reads that carry a classification marker, vs the rest (each named).
# Their union is the whole CLI read registry — so a *new* read fails the partition
# until it declares provenance-or-no-provenance.
_CLI_PROVENANCE_READS = {"search", "list", "show", "facets"}
_CLI_NO_PROVENANCE_READS = {
    "works": "scholarly-work consolidation; the relation is the work, no classification marker",
    "graph": "link structure + per-node custody (H56/H59), no classification marker",
    "related": "relationship surface; per-node custody/rank only, no classification marker",
    "doctor": "whole-library audit aggregate; its `custody.enrichment` is a freshness "
              "*count*, not a per-item classification view",
    "status": "boot custody scalar, no classification marker",
    "history": "per-item verify-ledger timeline (H66), no classification marker",
    "maintain": "maintenance-ledger read (H377), no classification marker",
    "context": "model-facing bundle; provenance rides per-excerpt tags (H44), a "
               "different granularity than the per-item view this contract pins",
    "archive list": "archive recovery read, no classification marker",
    "archive show": "archive recovery read, no classification marker",
}

_MCP_PROVENANCE_TOOLS = {"search_scrolls", "list_scrolls", "get_scroll"}
_MCP_NO_PROVENANCE_TOOLS = {
    "list_facets": "aggregate facets twin; the CLI `facets method` aggregate carries "
                   "the provenance leg (the H397 facets-twin precedent)",
    "get_scroll_history": "per-item verify-ledger timeline twin of `history`",
    "get_related_scrolls": "relationship surface twin of `related`",
    "get_link_graph": "link structure + per-node custody twin of `graph`",
    "get_works": "consolidation surface twin of `works`",
    "get_context_bundle": "model-facing bundle twin of `context`; provenance rides "
                          "per-excerpt tags (H44)",
    "get_concept_page": "compiled library group-page render; carries the H89/H93 "
                        "custody marker (· fidelity · drift · when), NOT a "
                        "classification-method marker — the roadmap's '(H89-family "
                        "marker)' conflated custody with provenance (the H404/H407 "
                        "roadmap-correction precedent)",
    "get_tag_page": "compiled library group-page render; H89/H93 custody marker only, "
                    "no classification marker (the H404/H407 roadmap correction)",
    "list_sources": "source roster, no per-item classification marker",
    "list_archived": "archive recovery read",
    "get_archived": "archive recovery read",
    "get_library_health": "whole-library audit twin of `doctor`/`status`",
    "get_maintenance_history": "maintenance-ledger twin of `maintain --history`",
    "list_feed_subscriptions": "feed roster, no classification marker",
}


def _provenance_failures(db, capsys):
    """The set of provenance surfaces that disagree with the canonical projection.

    The matrix guard asserts this is empty; the sabotage asserts it is exactly the
    one surface it broke. A per-item surface's whole `{id: view}` reading must equal
    the canonical `{id: view}` (completeness + convergence in one — the fixture has
    every per-item surface show all five ids); the aggregate's `{bucket: count}`
    must equal the canonical bucket tally. Compared on the wire (`_on_the_wire`), so
    a key-order difference is not a false desync."""
    canonical_view = _canonical_view(db)
    canonical_tally = _canonical_method_tally(db)
    failures = set()
    for key, (kind, read) in _PROVENANCE_SURFACES.items():
        reading = read(capsys)
        if kind == "per_item":
            expected = {item_id: _on_the_wire(canonical_view[item_id]) for item_id in reading}
            got = {item_id: _on_the_wire(view) for item_id, view in reading.items()}
            # the surface must enumerate every held item (a dropped id is a desync,
            # not silent convergence) and read each one's view as the canonical
            if set(reading) != set(canonical_view) or got != expected:
                failures.add(key)
        else:  # aggregate
            if reading != canonical_tally:
                failures.add(key)
    return failures


# --- keystone 1: the provenance surfaces partition the live read registries ---


def test_provenance_surfaces_partition_the_live_read_registries():
    """`_PROVENANCE_SURFACES` ∪ the named `_NO_PROVENANCE_AXIS` exemptions partition
    the live read registries (`_CLI_READ_PATHS`/H394, `_MCP_READ_TOOLS`/H388)
    exactly — so a *new* enrichment-bearing read fails until it declares its
    provenance convergence. The H394 registry-completeness mechanism on the
    enrichment-provenance axis."""
    cli_reads = {" ".join(path) for path in _CLI_READ_PATHS}
    assert _CLI_PROVENANCE_READS.isdisjoint(_CLI_NO_PROVENANCE_READS)
    assert _CLI_PROVENANCE_READS | set(_CLI_NO_PROVENANCE_READS) == cli_reads

    assert _MCP_PROVENANCE_TOOLS.isdisjoint(_MCP_NO_PROVENANCE_TOOLS)
    assert _MCP_PROVENANCE_TOOLS | set(_MCP_NO_PROVENANCE_TOOLS) == set(_MCP_READ_TOOLS)

    # the matrix's provenance surfaces are exactly the CLI + MCP provenance reads
    assert set(_PROVENANCE_SURFACES) == _CLI_PROVENANCE_READS | _MCP_PROVENANCE_TOOLS


# --- keystone 2: the convergence is per-item cross-transport + one aggregate ---


def test_every_provenance_surface_declares_a_known_kind():
    """Each provenance surface is a `per_item` view or the one `aggregate` tally,
    and the per-item view is exercised on **both** a CLI and an MCP surface — so the
    convergence the matrix pins is genuinely cross-transport, not one-sided."""
    for key, (kind, _read) in _PROVENANCE_SURFACES.items():
        assert kind in ("per_item", "aggregate"), key
    per_item = {k for k, (kind, _r) in _PROVENANCE_SURFACES.items() if kind == "per_item"}
    aggregate = {k for k, (kind, _r) in _PROVENANCE_SURFACES.items() if kind == "aggregate"}
    # per-item provenance is pinned on both transports (CLI + MCP), browse + inspect
    assert {"search", "list", "show"} <= per_item  # CLI: browse, browse, inspect
    assert {"search_scrolls", "list_scrolls", "get_scroll"} <= per_item  # MCP twins
    assert aggregate == {"facets"}


# --- the matrix guard --------------------------------------------------------


def test_every_surface_reads_the_canonical_provenance(scrolls_home, capsys):
    """Over the wide non-vacuous fixture, every provenance surface's reading equals
    the canonical projection — the per-item `classification` view per id and the
    `facets method` tally. The one invariant the scattered per-surface classification
    tests pinned piecemeal."""
    cli.main(["init"])
    db = get_paths().db_path
    _seed_provenance_surface_mix(db)
    capsys.readouterr()

    # sanity: the fixture spans the whole method axis and the confidence sub-axes
    # (a mis-rendered marker has a wrong value to land on, not None == None)
    tally = _canonical_method_tally(db)
    assert tally == {"rules-v1": 2, "llm-v1": 1, "user-set": 1, "unclassified": 1}
    views = _canonical_view(db)
    rules_freshness = {
        view["confidence"]["freshness"]
        for view in views.values()
        if view is not None and view["confidence"]["level"] == "deterministic"
    }
    assert rules_freshness == {"current", "stale"}
    assert any(
        view is not None and view["confidence"]["level"] == "inferred"
        for view in views.values()
    )
    assert sum(1 for view in views.values() if view is None) == 2  # user-set + unclassified
    capsys.readouterr()

    assert _provenance_failures(db, capsys) == set()


def test_one_surface_re_deriving_freshness_fails_only_that_surface(
    scrolls_home, capsys, monkeypatch
):
    """The sabotage proves the matrix has teeth and is *isolating*: re-deriving one
    item's freshness on one surface fails *only* that surface's leg, not its twins.

    `cli.item_summary` is the CLI `list` row builder — a *distinct* module binding
    from `mcp_server.item_summary` (the `list_scrolls` twin) and from the
    `hit_payload`/`get_scroll`/`facets` paths the other surfaces render — so claiming
    the stale-ruleset item's category is freshly classified on the CLI list desyncs
    only `list`. The canonical reads `classification_provenance` directly, untouched;
    the `facets method` aggregate buckets by engine, blind to freshness. This is the
    cross-surface regression the matrix catches that a surface's own tests miss."""
    cli.main(["init"])
    db = get_paths().db_path
    _seed_provenance_surface_mix(db)
    capsys.readouterr()

    # baseline: every surface converges
    assert _provenance_failures(db, capsys) == set()

    real_item_summary = cli.item_summary

    def _wrong(item, works=None, drift="unverified", last_checked=None):
        summary = real_item_summary(item, works, drift=drift, last_checked=last_checked)
        marker = summary.get("classification")
        if item.id == "web:rules-stale" and marker is not None:
            # call a stale-ruleset category fresh — a real provenance desync an agent
            # would read as "this category still holds" when the ruleset has moved
            marker["confidence"]["freshness"] = "current"
        return summary

    monkeypatch.setattr(cli, "item_summary", _wrong)

    assert _provenance_failures(db, capsys) == {"list"}
