"""H407 — the rank-explainability convergence contract.

The fourteenth **contract-consolidation** cell and the *rank*-axis sibling of
H397's custody-axis surface-parity matrix. Where H397 pins that every browse
surface reads the same *custody* axes (fidelity/drift/works/content-duplicate),
this pins that every surface carrying an **explainable-rank band** reads the same
band for the same item/edge as the canonical fold — lifting the scattered
per-surface strength tests (H312–H324) to one completeness-asserted invariant.

The claim (custody-vision §3.5, the PRD "re-derivable enrichment + confidence
markers" success metric): a rank band an agent reads is *grounded in the weights
that produced the rank*, and it reads identically wherever it appears, so the
explanation behind the opaque `score` can never disagree across surfaces.

Two rank axes, each with one canonical projection read straight from the
primitive that computes it:

- **match_strength** (`search.match_strength`, H312 — the band of the
  highest-weighted indexed field a query landed in) on `search`, `context`, and
  `export bundle`, plus the MCP twins `search_scrolls`/`get_context_bundle`. The
  canonical is `search_items(db, QUERY)` → `{id: match_strength}`.
- **relation_strength** (`related.relation_strength`, H322 — the band of the
  strongest contributing relation class) on `related`, plus the MCP twin
  `get_related_scrolls`. The canonical is `scored_related(db, ANCHOR)` →
  `{id: relation_strength}`.

Every match surface threads `search_items` and every relation surface threads
`scored_related`, so convergence holds *by construction*; the contract's job is
to catch a **surface** that re-derives or re-renders the band differently — a
markdown marker parsed off the wrong token, a JSON row recomputing the tier, a
headline tally that drifts from the per-row markers it summarises.

**A roadmap correction (the H404 precedent).** The roadmap's H407 line names
`graph`/`get_link_graph` as relation_strength surfaces. The live code carries no
rank band there: `graph.py`/`graph_payload`/`get_link_graph` fold per-node
custody (`fidelity`/`drift`, H56/H59) and the link structure, never a
`relation_strength` — exactly as H404 found the roadmap had wrongly called
`graph.md` custody-bearing. So `graph`/`get_link_graph` are classified
`_NO_RANK_AXIS` here (with a named reason), and the relation axis rides
`related`/`get_related_scrolls` alone.

Two faces, the H388/H394/H397 shape:

1. **The completeness keystone** — `_RANK_SURFACES` (each surface × its rank
   axis) ∪ a named `_NO_RANK_AXIS` exemption set partitions the live read
   registries (`_CLI_READ_PATHS`/H394, `_MCP_READ_TOOLS`/H388) *exactly*, so a
   *new* rank-bearing read fails the contract until it declares its band
   convergence. `export bundle` is the one rank surface *outside* the read
   registries — a lossless transport classified `_CLI_EXEMPT_READS` by H394 — so
   it is tied to that live classification and joins the matrix without breaking
   the registry partition.

2. **The matrix guard** — over one fixture spanning all three bands on each axis
   (a title/summary/body-only match and a same-work/shared-concept/same-category
   relation edge), every surface's `{id: band}` reading equals the canonical
   projection and its headline tally (where it renders one) converges with its
   own per-row bands; a sabotage that re-derives one band a tier high fails
   *only* that surface's leg (the H397 binding-isolation precedent).
"""

import json
import re

import pytest

import scrolls.cli as cli
import scrolls.mcp_server as mcp_server
from scrolls.cli import main
from scrolls.items import ScrollItem, insert_item
from scrolls.paths import get_paths
from scrolls.related import (
    RELATION_STRENGTH_BANDS,
    scored_related,
    tally_relation_strength,
)
from scrolls.search import STRENGTH_BANDS, search_items, tally_strength

# The read registries the H394/H388 contracts hold to the live argparse / MCP
# surfaces. Keying the rank-surface classification to them makes a *new* read
# command/tool force a rank-or-exempt decision here too (it first fails
# H394/H388 until registered, then this contract until classified).
from test_cli_determinism import _CLI_EXEMPT_READS, _CLI_READ_PATHS  # noqa: E402
from test_mcp import _MCP_READ_TOOLS  # noqa: E402

# The query whose terms land in exactly one indexed field per match item, and the
# anchor whose neighbours span the three relation bands — both set by the fixture.
QUERY = "alpha"
ANCHOR = "x:anchor"


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


def _item(item_id, source, url, **overrides):
    base = dict(
        id=item_id, source=source, url=url,
        saved_at="2026-06-20T00:00:00+00:00", stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def _seed_rank_surface_mix(db):
    """A library spanning all three bands on *both* rank axes, so the matrix is
    non-vacuous (an all-`weak` library would pass a mis-rendered band too).

    The two clusters are kept disjoint (no shared text/category/concept/DOI), so
    a match item is never a relation neighbour and vice versa:

    - the **match cluster** — `QUERY` ("alpha") lands in exactly one indexed FTS
      field per item (`title` → `strong`, `summary` → `moderate`,
      `extracted_text` → `weak`, the `_STRENGTH_BY_FIELD` weights), and none share
      a DOI, so `context` never folds a same-work duplicate (every surface shows
      all three);
    - the **relation cluster** — `ANCHOR` ("x:anchor") gains one neighbour per
      `relation_strength` band: a shared-DOI same-work edge (`strong`), a shared
      concept (`moderate`), and a same-category-only edge (`weak`, the "never
      enough on its own" corroboration).
    """
    # match cluster: one match_strength band per indexed field
    insert_item(db, _item(
        "web:title", "web", "https://example.com/title",
        title="Alpha overview", extracted_text="general overview notes",
        category="lit"))
    insert_item(db, _item(
        "web:summary", "web", "https://example.com/summary",
        title="Beta notes", summary="alpha methodology",
        extracted_text="methodology writeup", category="lit"))
    insert_item(db, _item(
        "web:body", "web", "https://example.com/body",
        title="Gamma log", extracted_text="alpha deep dive", category="lit"))
    # relation cluster: one relation_strength band per neighbour
    insert_item(db, _item(
        "x:anchor", "x", "https://x.com/anchor", title="Network anchor",
        category="social", concepts=("Graphs",), tags=("viral",),
        links=("https://doi.org/10.6000/r",)))
    insert_item(db, _item(  # shared DOI → same-work edge → strong
        "crossref:work", "crossref", "https://example.org/work",
        title="Work record", category="ref",
        links=("https://doi.org/10.6000/r",)))
    insert_item(db, _item(  # shared concept → moderate
        "web:concept", "web", "https://web.test/concept",
        title="Concept note", category="topic", concepts=("Graphs",)))
    insert_item(db, _item(  # same category only → group corroboration → weak
        "web:cat", "web", "https://web.test/cat",
        title="Category sibling", category="social"))


# --- the canonical rank projections (one source of truth per axis) -----------


def _canonical_match(db):
    """`{id: match_strength}` — the band `search_items` reads off the BM25 column
    weights, the projection every match surface is held to (H312)."""
    return {hit.id: hit.match_strength for hit in search_items(db, QUERY)}


def _canonical_relation(db):
    """`{id: relation_strength}` — the band `scored_related` reads off the relation
    point weights, the projection every relation surface is held to (H322)."""
    return {hit.id: hit.relation_strength for hit in scored_related(db, ANCHOR)}


# --- per-surface band readers (each via its own real entry point) ------------

_ID_RE = re.compile(r"\(`([^`]+)`\)")
_HEADLINE_RE = re.compile(r"_Strength: (.+?) \(of \d+\)\._")
_RANK_MARKER_RE = re.compile(r"· rank `([^`]+)`")


def _parse_strength_headline(text):
    """`{band: count}` from a rendered `_Strength: strong a, moderate b … (of N)._`
    line (nonzero bands only — `render_strength_headline` drops the zeros)."""
    for line in text.splitlines():
        match = _HEADLINE_RE.search(line)
        if match:
            counts = {}
            for token in match.group(1).split(", "):
                band, num = token.rsplit(" ", 1)
                counts[band] = int(num)
            return counts
    return None


def _bestmatch_reading(text):
    """Context bundle: the `· <band>` marker per Best-Matches line + the headline.

    Reads only the `## Best Matches` section (the markered ranked list), never the
    `## Connected`/`## Excerpts` sections below it, which carry no rank marker."""
    section = text.partition("## Best Matches")[2].split("\n## ", 1)[0]
    bands = {}
    for line in section.splitlines():
        ident = _ID_RE.search(line)
        if not ident:
            continue
        markers = [seg.strip() for seg in line.split(" · ")]
        found = [seg for seg in markers if seg in STRENGTH_BANDS]
        if found:
            bands[ident.group(1)] = found[0]
    return bands, _parse_strength_headline(text)


def _briefing_reading(text):
    """Export bundle: the `· rank `<band>`` marker per scroll entry + the headline.

    Each entry opens with a `## N. <title> (`id`)` heading and carries its band on
    the drift line below; markers are keyed to the most recent entry id."""
    bands = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            heading = _ID_RE.search(line)
            current = heading.group(1) if heading else None
        marker = _RANK_MARKER_RE.search(line)
        if marker and current is not None:
            bands[current] = marker.group(1)
    return bands, _parse_strength_headline(text)


def _read_search(capsys):
    main(["search", QUERY, "--stats"])
    env = json.loads(capsys.readouterr().out)
    rows = env["results"]
    return {row["id"]: row["match_strength"] for row in rows}, env["stats"]["strength"]


def _read_search_scrolls(capsys):
    rows = mcp_server.search_scrolls(QUERY)
    return {row["id"]: row["match_strength"] for row in rows}, None


def _read_context(capsys):
    main(["context", QUERY, "--budget", "full"])
    return _bestmatch_reading(capsys.readouterr().out)


def _read_context_mcp(capsys):
    return _bestmatch_reading(mcp_server.get_context_bundle(QUERY, budget="full"))


def _read_export_bundle(capsys):
    main(["export", "bundle", QUERY])
    return _briefing_reading(capsys.readouterr().out)


def _read_related(capsys):
    main(["related", ANCHOR, "--stats"])
    env = json.loads(capsys.readouterr().out)
    rows = env["results"]
    return (
        {row["id"]: row["relation_strength"] for row in rows},
        env["stats"]["strength"],
    )


def _read_related_mcp(capsys):
    rows = mcp_server.get_related_scrolls(ANCHOR)
    return {row["id"]: row["relation_strength"] for row in rows}, None


# --- the (surface × rank axis) registry — the completeness keystone ----------

# Every surface that renders a rank band, mapped to (axis, reader). The matrix
# guard holds each to its axis's canonical projection.
_RANK_SURFACES = {
    "search": ("match", _read_search),
    "context": ("match", _read_context),
    "export bundle": ("match", _read_export_bundle),
    "search_scrolls": ("match", _read_search_scrolls),
    "get_context_bundle": ("match", _read_context_mcp),
    "related": ("relation", _read_related),
    "get_related_scrolls": ("relation", _read_related_mcp),
}

# The CLI reads that carry a rank band, vs the rest (each named). Their union is
# the whole CLI read registry — so a *new* read fails the partition until it
# declares rank-or-no-rank.
_CLI_RANK_READS = {"search", "context", "related"}
_CLI_NO_RANK_READS = {
    "list": "browse rows carry custody axes only (H397 parity surface), no rank band",
    "facets": "aggregate per-value counts, no per-row rank band",
    "works": "consolidation surface; the relation is the work, not a ranked edge",
    "graph": "link structure + per-node custody (H56/H59); graph_payload folds no "
             "rank axis — the roadmap's 'related/graph' was inaccurate (cf. H404's "
             "graph.md correction)",
    "doctor": "whole-library audit aggregate, no rank band",
    "status": "boot custody scalar, no rank band",
    "history": "per-item ledger timeline, no rank band",
    "maintain": "maintenance-ledger read, no rank band",
    "show": "single-item inspect; one item, nothing to rank against",
    "archive list": "archive recovery read, no rank band",
    "archive show": "archive recovery read, no rank band",
}

# The rank surfaces that render a `_Strength:_`/`stats.strength` headline tally
# (the bands fold-up), vs the row-only surfaces (the MCP read tools return rows,
# no headline). Asserted in the matrix so a headline that fails to render — or a
# markdown one the parser can't find — fails loudly rather than silently skipping
# the headline-convergence leg.
_HEADLINE_SURFACES = {"search", "related", "context", "get_context_bundle",
                      "export bundle"}

_MCP_RANK_TOOLS = {"search_scrolls", "get_context_bundle", "get_related_scrolls"}
_MCP_NO_RANK_TOOLS = {
    "list_scrolls": "browse rows, custody axes only (H397)",
    "list_facets": "aggregate per-value counts, no rank band",
    "get_scroll": "single-item inspect twin of show",
    "get_scroll_history": "per-item ledger timeline twin of history",
    "get_link_graph": "link structure + per-node custody twin of graph; folds no "
                      "relation_strength band",
    "get_works": "consolidation twin of works",
    "get_concept_page": "compiled-page render, no rank band",
    "get_tag_page": "compiled-page render, no rank band",
    "list_sources": "source roster, no rank band",
    "list_archived": "archive recovery read",
    "get_archived": "archive recovery read",
    "get_library_health": "whole-library audit twin of doctor/status",
    "get_maintenance_history": "maintenance-ledger twin of maintain --history",
    "list_feed_subscriptions": "feed roster, no rank band",
}


def _nonzero(counts):
    """The band→count map with the zero bands dropped — the form a markdown
    `_Strength:_` headline renders, so the JSON `stats.strength` (zeros included)
    and the parsed markdown headline compare on equal footing."""
    return {band: count for band, count in counts.items() if count}


def _tally(axis, bands):
    values = list(bands.values())
    return tally_strength(values) if axis == "match" else tally_relation_strength(values)


def _rank_failures(db, capsys):
    """The set of rank surfaces that disagree with the canonical projection.

    The matrix guard asserts this is empty; the sabotage asserts it is exactly the
    one surface it broke. Each surface's whole `{id: band}` reading must equal the
    canonical `{id: band}` projection for its axis (completeness + convergence in
    one — the fixture has every surface show the full ranked set), and its headline
    tally (where it renders one) must equal the tally of its own per-row bands.
    """
    canonical = {"match": _canonical_match(db), "relation": _canonical_relation(db)}
    failures = set()
    for key, (axis, read) in _RANK_SURFACES.items():
        bands, headline = read(capsys)
        if bands != canonical[axis]:
            failures.add(key)
            continue
        # a headline surface must render a parseable tally; a row-only surface must
        # not claim one — so a dropped/garbled `_Strength:_` line fails its leg
        # rather than silently skipping the headline-convergence check.
        if (headline is not None) != (key in _HEADLINE_SURFACES):
            failures.add(key)
            continue
        if headline is not None and _nonzero(headline) != _nonzero(_tally(axis, bands)):
            failures.add(key)
    return failures


# --- keystone 1: the rank surfaces partition the live read registries --------


def test_rank_surfaces_partition_the_live_read_registries():
    """`_RANK_SURFACES` ∪ the named `_NO_RANK_AXIS` exemptions partition the live
    read registries (`_CLI_READ_PATHS`/H394, `_MCP_READ_TOOLS`/H388) exactly — so a
    *new* rank-bearing read fails until it declares its band convergence. The H394
    registry-completeness mechanism on the rank-explainability axis."""
    cli_reads = {" ".join(path) for path in _CLI_READ_PATHS}
    assert _CLI_RANK_READS.isdisjoint(_CLI_NO_RANK_READS)
    assert _CLI_RANK_READS | set(_CLI_NO_RANK_READS) == cli_reads

    assert _MCP_RANK_TOOLS.isdisjoint(_MCP_NO_RANK_TOOLS)
    assert _MCP_RANK_TOOLS | set(_MCP_NO_RANK_TOOLS) == set(_MCP_READ_TOOLS)

    # `export bundle` is a rank surface *outside* the read registries — a lossless
    # transport classified `_CLI_EXEMPT_READS` by H394, not a JSON read. Tie it to
    # that live classification so the name can't rot, and assert it is honestly not
    # a read, so the registry partitions above stay exact while the bundle still
    # joins the matrix below.
    assert ("export", "bundle") in _CLI_EXEMPT_READS
    assert "export bundle" not in cli_reads

    # the matrix's rank surfaces are exactly the registry rank reads/tools plus the
    # one non-registry transport — so the matrix covers every band-bearing surface.
    assert set(_RANK_SURFACES) == _CLI_RANK_READS | _MCP_RANK_TOOLS | {"export bundle"}


# --- keystone 2: every rank surface declares one known, cross-transport axis --


def test_every_rank_surface_declares_a_known_axis():
    """Each rank surface maps to one of the two known rank axes, and each axis is
    exercised on both a CLI and an MCP surface — so the convergence the matrix pins
    is genuinely cross-transport, not one-sided."""
    for key, (axis, _read) in _RANK_SURFACES.items():
        assert axis in ("match", "relation"), key
    assert {axis for axis, _read in _RANK_SURFACES.values()} == {"match", "relation"}

    match_surfaces = {k for k, (a, _r) in _RANK_SURFACES.items() if a == "match"}
    relation_surfaces = {k for k, (a, _r) in _RANK_SURFACES.items() if a == "relation"}
    assert {"search", "search_scrolls"} <= match_surfaces  # CLI + MCP
    assert {"related", "get_related_scrolls"} <= relation_surfaces  # CLI + MCP


# --- the matrix guard --------------------------------------------------------


def test_every_rank_surface_reads_the_canonical_band(scrolls_home, capsys):
    """Over the wide non-vacuous fixture, every rank surface's `{id: band}` reading
    equals the canonical projection for its axis, and each headline tally converges
    with its own per-row bands. The one invariant the scattered per-surface strength
    tests (H312–H324) pinned piecemeal."""
    main(["init"])
    db = get_paths().db_path
    _seed_rank_surface_mix(db)
    capsys.readouterr()

    # sanity: the fixture spans all three bands on each axis (a mis-rendered band
    # has a wrong value to land on, not 0 == 0)
    match_canonical = _canonical_match(db)
    relation_canonical = _canonical_relation(db)
    assert set(match_canonical.values()) == {"strong", "moderate", "weak"}
    assert set(relation_canonical.values()) == {"strong", "moderate", "weak"}
    capsys.readouterr()

    assert _rank_failures(db, capsys) == set()


def test_one_surface_re_deriving_a_band_a_tier_high_fails_only_that_surface(
    scrolls_home, capsys, monkeypatch
):
    """The sabotage proves the matrix has teeth and is *isolating*: re-deriving one
    band a tier high on one surface fails *only* that surface's leg, not its twins.

    `cli.hit_payload` is the CLI `search` row builder — a *distinct* module binding
    from `mcp_server.hit_payload` (the `search_scrolls` twin) and from the
    `build_context`/`build_bundle`/`find_related` paths the other surfaces render —
    so bumping the body-only match's `weak` band to `strong` on the CLI search row
    desyncs only `search`. The canonical reads `search_items` directly, untouched.
    This is the cross-surface regression the matrix catches that a surface's own
    tests miss."""
    main(["init"])
    db = get_paths().db_path
    _seed_rank_surface_mix(db)
    capsys.readouterr()

    # baseline: every surface converges
    assert _rank_failures(db, capsys) == set()

    real_hit_payload = cli.hit_payload

    def _wrong(hit):
        payload = real_hit_payload(hit)
        if payload["id"] == "web:body":
            payload["match_strength"] = "strong"  # a tier high — a real desync
        return payload

    monkeypatch.setattr(cli, "hit_payload", _wrong)

    assert _rank_failures(db, capsys) == {"search"}
