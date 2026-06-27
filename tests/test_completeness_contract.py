"""The completeness-honesty contract (roadmap H398) — one completeness-asserted invariant.

The fifth **contract-consolidation** cell (after H388's whole-MCP determinism
contract, H395's round-trip contract, H396's regeneration-safety contract, and
H397's surface-parity matrix). It lifts the scattered *per-surface* scope-echo
tests (`docs/cli.md` → completeness contract G2, pinned today in
`tests/test_cli.py`/`tests/test_search.py`/`tests/test_works.py`/
`tests/test_context.py`) to a single **registry-driven** invariant, so the
scope-honesty claim is pinned *once* over an enumerated surface registry rather
than re-stated per command.

The claim (PRD cap 7, MVP M2, custody-vision §6, adapted from obsidian-second-
brain's anti-fabrication rules): every browse/audit surface — `search`/`list`/
`related`/`works`/`context`/`doctor` and their MCP twins — is **scope-honest**
and **completeness-honest**, on two axes:

1. **scope echo** — a *scoped/filtered* read discloses, in its own payload, the
   scope it covered, so a reader holding only the result can recover the applied
   filter and never mistakes a filtered slice for the whole library. The uniform
   discriminator: a surface's scope *disclosure* under one scope must **differ**
   from its disclosure under a different scope (and name the applied scope). A
   surface that emitted a constant disclosure would let an agent read a filtered
   slice as library-wide completeness — the fabrication M2 forbids.

2. **empty honesty** — an empty *in-scope* read returns the empty form of its own
   shape (exit 0 / empty list / `No matching scrolls.` bundle / zero-finding
   report — never an error, never a fabricated hit) and is **distinguishable**
   from a could-not-check (bad input / unknown id → loud error envelope / raised
   tool error). "Nothing found" is never confused with "not checked."

Two faces, the H388/H394/H396/H397 shape:

A. **The completeness keystone** — the registry forces a *new* browse/audit
   surface to declare scope-honesty before it can ship:
   - every (surface × axis) cell is a live probe or a *named* exemption
     (`test_completeness_matrix_is_complete`);
   - the completeness surfaces partition the live read registries
     (`_CLI_READ_PATHS`/H394, `_MCP_READ_TOOLS`/H388) together with their named
     exemptions, so a *new browse surface* fails until classified
     (`test_completeness_surfaces_partition_the_live_read_registries`).

B. **The honesty guards** — over one wide non-vacuous fixture, every
   scope-echoing surface discloses a scope its other-scope read does not
   (`test_every_scope_echoing_surface_discloses_its_scope`), and every surface's
   empty form is distinguishable from a could-not-check
   (`test_cli_*`/`test_mcp_*_distinguishes_empty_from_not_checked`). The sabotage
   drops one surface's scope echo (so a per-ref read claims whole-library
   completeness) and fails *only* that surface's leg
   (`test_dropping_a_scope_echo_fails_only_that_surface`).

Test-only, no production change: the surfaces already echo scope (G2 shipped
H6–H8) and are honest-empty (G1, `tests/test_completeness.py`). This pins the
scope-honesty half *as the contract*, registry-driven, so a future surface
cannot ship silent about its scope.
"""

import json

import pytest

import scrolls.cli as cli
import scrolls.mcp_server as mcp_server
from scrolls.cli import main
from scrolls.items import ScrollItem, insert_item
from scrolls.paths import get_paths

# The read registries the H388/H394 contracts hold to the live MCP / argparse
# surfaces. Keying the completeness-surface classification to them makes a *new*
# read command/tool force a completeness-or-exempt decision here too (it first
# fails H388/H394 until registered, then this contract until classified).
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
        source=item_id.split(":")[0],
        url=f"https://example.org/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00",
        title=title,
        extracted_text="alpha beta gamma",
        summary="alpha beta gamma",
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def _seed_completeness_mix(db):
    """A wide library where both honesty axes are non-vacuous on every surface.

    - **`web:lonely`** — an isolated, never-verified item (no links/tags/DOI),
      its title carrying no ``topic`` token. So a ``topic`` search excludes it,
      `related`/`works` find no neighbour/sibling (a genuine *checked-and-empty*),
      and `history` has no ledger verdict (held-but-unchecked `[]`).
    - **`web:note` + `arxiv:paper`** — two ``topic``-titled items in two distinct
      sources, so a ``topic`` `search`/`list`/`context` over ``--source arxiv``
      narrows a real non-empty result (the scope echo has something to disclose),
      and `doctor`/`get_library_health` `by_source` spans both sources (a scoped
      audit collapses it to the singleton). All `fetched` (no `markdown_path`), so
      the structural audit finds nothing — `doctor`'s honest-empty stays exit 0.
    """
    insert_item(db, _item("web:lonely", "Lonely note"))
    insert_item(db, _item(
        "web:note", "Topic web note",
        extracted_text="topic web body", summary="topic web body"))
    insert_item(db, _item(
        "arxiv:paper", "Topic arxiv paper", source="arxiv",
        url="https://arxiv.org/abs/paper",
        extracted_text="topic arxiv body", summary="topic arxiv body"))


# --- the completeness-surface registry — the keystone -------------------------
#
# The browse/audit surfaces that carry the scope-honesty + empty-honesty
# contract, keyed (CLI) to the joined argparse path `_CLI_READ_PATHS` uses and
# (MCP) to the `_MCP_READ_TOOLS` tool name. Every other live read is a *named*
# exemption with where its honesty is actually pinned — never a silent skip.

_CLI_COMPLETENESS_SURFACES = {
    "search", "list", "related", "works", "context", "doctor", "history",
}
_CLI_EXEMPT_READS = {
    "facets": "aggregate dimension counts; an excluding facet is the empty form "
              "(G1, test_a_facet_that_excludes_everything_is_empty_not_error) and "
              "its per-item parity rides the H397 surface-parity matrix",
    "graph": "whole-library relationship aggregate; per-item parity H56/H59, "
             "honest absence G1 — no per-query filter scope to echo here",
    "status": "boot custody scalar; its scope honesty converges with `doctor` "
              "(H367 status≡doctor), pinned there",
    "maintain": "maintenance-ledger read (H377); offline `--no-recheck` honest "
                "absence is G1 (the `maintain` cases in test_completeness.py)",
    "archive list": "archive recovery read, not a custody-axis browse/audit scope",
    "archive show": "archive recovery read; its empty/unknown split rides H385",
    "show": "single-item inspect (H61); could-not-check on an unknown id is G1 "
            "(the `show` COULD_NOT_CHECK case in test_completeness.py)",
}

_MCP_COMPLETENESS_SURFACES = {
    "search_scrolls", "list_scrolls", "get_related_scrolls", "get_works",
    "get_context_bundle", "get_library_health", "get_scroll_history",
}
_MCP_EXEMPT_READS = {
    "list_facets": "aggregate facets twin; the CLI `facets` aggregate is exempt "
                   "for the same reason (empty-facet honesty is G1)",
    "get_scroll": "single-item inspect twin of `show` (H61)",
    "get_link_graph": "whole-library relationship aggregate twin of `graph`",
    "get_concept_page": "compiled-page render, not a browse/audit scope",
    "get_tag_page": "compiled-page render, not a browse/audit scope",
    "list_sources": "source roster, not a custody-axis browse/audit scope",
    "list_archived": "archive recovery read",
    "get_archived": "archive recovery read",
    "get_maintenance_history": "maintenance-ledger read twin of `maintain --history`",
    "list_feed_subscriptions": "feed roster, not a custody-axis browse/audit scope",
}

_COMPLETENESS_SURFACES = _CLI_COMPLETENESS_SURFACES | _MCP_COMPLETENESS_SURFACES

# The two honesty axes every completeness surface is held to.
_HONESTY_AXES = ("scope_echo", "empty_honesty")


# --- axis 1: scope echo -------------------------------------------------------
#
# Each live probe returns `(here, there, token)`: the surface's scope *disclosure*
# under one scope and under a *different* scope, plus a token the `here`
# disclosure must name. The guard asserts `here != there` (the disclosure tracks
# the scope, so a filtered slice can't read as the whole library) and that the
# applied scope is named. Surfaces with no browse filter to echo are *named*
# exemptions on this axis — their honesty is the empty-vs-unchecked split (axis 2).

_SCOPE_ECHO_EXEMPT = {
    "history": "per-item custody ledger — a bare timeline array, no browse filter "
               "to echo; its honesty is the empty-vs-unchecked split (axis 2)",
    "get_scroll_history": "per-item ledger timeline twin of `history`; bare array, "
                          "no browse filter to echo",
    "search_scrolls": "MCP browse twin is array-only by design (H163, docs/cli.md) "
                      "— the `--stats` scope envelope is a CLI affordance with no "
                      "MCP analogue; the per-source picture relocates to "
                      "get_works/get_library_health (which this contract pins)",
    "list_scrolls": "MCP browse twin is array-only by design (H163)",
    "get_related_scrolls": "MCP browse twin is array-only by design (H163)",
}


def _cli_json(argv, capsys):
    assert main(argv) == 0
    return json.loads(capsys.readouterr().out)


def _cli_text(argv, capsys):
    assert main(argv) == 0
    return capsys.readouterr().out


def _context_title(bundle):
    """The bundle's scope-bearing title line — `# Scrolls Context Bundle: <q> (…)`."""
    return next(
        line for line in bundle.splitlines()
        if line.startswith("# Scrolls Context Bundle:")
    )


def _se_search(capsys):
    here = _cli_json(["search", "topic", "--source", "arxiv", "--stats"], capsys)["scope"]
    there = _cli_json(["search", "topic", "--stats"], capsys)["scope"]
    return here, there, "arxiv"


def _se_list(capsys):
    here = _cli_json(["list", "--source", "arxiv", "--stats"], capsys)["scope"]
    there = _cli_json(["list", "--stats"], capsys)["scope"]
    return here, there, "arxiv"


def _se_related(capsys):
    # related is always anchored, so a *different anchor* is the differing scope:
    # the `scope.item` echo names which neighbourhood the result covers.
    here = _cli_json(["related", "web:note", "--stats"], capsys)["scope"]
    there = _cli_json(["related", "web:lonely", "--stats"], capsys)["scope"]
    return here, there, "web:note"


def _se_works(capsys):
    here = _cli_json(["works", "web:note"], capsys)["scope"]
    there = _cli_json(["works"], capsys)["scope"]
    return here, there, "web:note"


def _se_context(capsys):
    here = _context_title(_cli_text(["context", "topic", "--source", "arxiv"], capsys))
    there = _context_title(_cli_text(["context", "topic"], capsys))
    return here, there, "source=arxiv"


def _se_doctor(capsys):
    here = sorted(_cli_json(["doctor", "--source", "arxiv"], capsys)["custody"]["by_source"])
    there = sorted(_cli_json(["doctor"], capsys)["custody"]["by_source"])
    return here, there, "arxiv"


def _se_get_works(_capsys):
    here = mcp_server.get_works(item="web:note")["scope"]
    there = mcp_server.get_works()["scope"]
    return here, there, "web:note"


def _se_get_context_bundle(_capsys):
    here = _context_title(mcp_server.get_context_bundle("topic", source="arxiv"))
    there = _context_title(mcp_server.get_context_bundle("topic"))
    return here, there, "source=arxiv"


def _se_get_library_health(_capsys):
    here = sorted(mcp_server.get_library_health(source="arxiv")["by_source"])
    there = sorted(mcp_server.get_library_health()["by_source"])
    return here, there, "arxiv"


_SCOPE_ECHO_LIVE = {
    "search": _se_search,
    "list": _se_list,
    "related": _se_related,
    "works": _se_works,
    "context": _se_context,
    "doctor": _se_doctor,
    "get_works": _se_get_works,
    "get_context_bundle": _se_get_context_bundle,
    "get_library_health": _se_get_library_health,
}


def _scope_echo_failures(capsys):
    """The set of live scope-echo surfaces whose disclosure does not track its scope.

    A surface fails when its `here` disclosure equals its `there` disclosure (a
    constant disclosure — a filtered slice would read as the whole library) or
    when the `here` disclosure does not name the applied scope token. The guard
    asserts this is empty; the sabotage asserts it is exactly the one cell broken.
    """
    failures = set()
    for surface, probe in _SCOPE_ECHO_LIVE.items():
        here, there, token = probe(capsys)
        if here == there or token not in json.dumps(here):
            failures.add(surface)
    return failures


# --- axis 2: empty honesty ----------------------------------------------------
#
# A checked-and-empty *in-scope* read (left) returns the empty form of its shape;
# a could-not-check (right) is loud. Surfaces with no required input have no
# could-not-check form — each *named* in `_NO_COULD_NOT_CHECK`, never a silent gap.

_NO_COULD_NOT_CHECK = {
    "list": "no required query/id — an excluding facet is the empty form; there is "
            "nothing to fail to parse",
    "doctor": "audits whatever is held — a zero-finding report is the empty form; "
              "an excluding scope is honestly empty, never a could-not-check",
    "list_scrolls": "no required query/id — an excluding facet is the empty form",
    "get_library_health": "audits whatever is held — an unknown `source=` scope is "
                          "the honest present-but-empty block (never an error)",
}

# CLI: argv that checks a real library and finds nothing in scope, plus the
# predicate proving the surface returned the empty form of ITS shape.
_CLI_EMPTY = {
    "search": (["search", "zzznotatoken"], lambda out: json.loads(out) == []),
    "list": (["list", "--tag", "nonexistent"], lambda out: json.loads(out) == []),
    "related": (["related", "web:lonely"], lambda out: json.loads(out) == []),
    "works": (["works", "web:lonely"], lambda out: json.loads(out)["works"] == []),
    "context": (["context", "zzznotatoken"], lambda out: "No matching scrolls." in out),
    "doctor": (["doctor"], lambda out: json.loads(out)["issues"] == 0),
    "history": (["history", "web:lonely"], lambda out: json.loads(out) == []),
}
# CLI: argv that *could not check* — bad input / unknown id, loud on stderr.
_CLI_NOT_CHECKED = {
    "search": ["search", '""'],
    "related": ["related", "web:does-not-exist"],
    "works": ["works", "web:does-not-exist"],
    "context": ["context", '""'],
    "history": ["history", "web:does-not-exist"],
}

# MCP: the analog — "returns the empty form" and a raised tool error for
# could-not-check (the framework surfaces it as an error, never a silent empty).
_MCP_EMPTY = {
    "search_scrolls": lambda: mcp_server.search_scrolls("zzznotatoken") == [],
    "list_scrolls": lambda: mcp_server.list_scrolls(tag="nonexistent") == [],
    "get_related_scrolls": lambda: mcp_server.get_related_scrolls("web:lonely") == [],
    "get_works": lambda: mcp_server.get_works(item="web:lonely")["works"] == [],
    "get_context_bundle": lambda: "No matching scrolls."
    in mcp_server.get_context_bundle("zzznotatoken"),
    "get_library_health": lambda: mcp_server.get_library_health(
        source="zzznosuchsource")["by_source"] == {},
    "get_scroll_history": lambda: mcp_server.get_scroll_history("web:lonely") == [],
}
_MCP_NOT_CHECKED = {
    "search_scrolls": lambda: mcp_server.search_scrolls("   "),
    "get_related_scrolls": lambda: mcp_server.get_related_scrolls("web:does-not-exist"),
    "get_works": lambda: mcp_server.get_works(item="web:does-not-exist"),
    "get_context_bundle": lambda: mcp_server.get_context_bundle("   "),
    "get_scroll_history": lambda: mcp_server.get_scroll_history("web:does-not-exist"),
}


# --- keystone 1: the matrix is complete (no unclassified cell) ---------------


def test_completeness_matrix_is_complete():
    """Every (surface × axis) cell is a live probe or a *named* exemption — so a
    new completeness surface, or a new honesty axis, fails until its cells are
    wired. The H388/H397 registry-completeness mechanism on the (surface, axis)
    cross product."""
    # axis 1 — scope_echo: live or named-exempt for every completeness surface
    assert set(_SCOPE_ECHO_LIVE).isdisjoint(_SCOPE_ECHO_EXEMPT)
    assert set(_SCOPE_ECHO_LIVE) | set(_SCOPE_ECHO_EXEMPT) == _COMPLETENESS_SURFACES

    # axis 2 — empty_honesty: live for every completeness surface (the empty form
    # is non-negotiable; no exemptions), pinned per transport
    assert set(_CLI_EMPTY) == _CLI_COMPLETENESS_SURFACES
    assert set(_MCP_EMPTY) == _MCP_COMPLETENESS_SURFACES
    # the could-not-check half is live except where the surface has no required
    # input (each *named* in `_NO_COULD_NOT_CHECK`)
    assert set(_CLI_NOT_CHECKED) == _CLI_COMPLETENESS_SURFACES - set(_NO_COULD_NOT_CHECK)
    assert set(_MCP_NOT_CHECKED) == _MCP_COMPLETENESS_SURFACES - set(_NO_COULD_NOT_CHECK)
    assert set(_NO_COULD_NOT_CHECK) <= _COMPLETENESS_SURFACES

    # the matrix axes are exactly the two declared (a new axis fails until wired)
    assert set(_HONESTY_AXES) == {"scope_echo", "empty_honesty"}

    # sanity: the contract is non-trivial — the load-bearing browse + audit
    # surfaces carry scope-echo live on *both* transports
    for surface in ("search", "works", "context", "doctor",
                    "get_works", "get_context_bundle", "get_library_health"):
        assert surface in _SCOPE_ECHO_LIVE


# --- keystone 2: the surfaces partition the live read registries -------------


def test_completeness_surfaces_partition_the_live_read_registries():
    """The completeness surfaces + their named exemptions partition the live read
    registries (`_CLI_READ_PATHS`/H394, `_MCP_READ_TOOLS`/H388, each already held
    to the live argparse / MCP surface) — so a *new browse/audit surface* fails
    until it is a declared completeness surface or a named exemption. The H394
    mechanism on the completeness-honesty axis."""
    cli_reads = {" ".join(path) for path in _CLI_READ_PATHS}
    assert _CLI_COMPLETENESS_SURFACES.isdisjoint(_CLI_EXEMPT_READS)
    assert _CLI_COMPLETENESS_SURFACES | set(_CLI_EXEMPT_READS) == cli_reads

    assert _MCP_COMPLETENESS_SURFACES.isdisjoint(_MCP_EXEMPT_READS)
    assert _MCP_COMPLETENESS_SURFACES | set(_MCP_EXEMPT_READS) == set(_MCP_READ_TOOLS)


# --- the honesty guards ------------------------------------------------------


def test_every_scope_echoing_surface_discloses_its_scope(scrolls_home, capsys):
    """Over the wide non-vacuous fixture, every scope-echoing surface discloses a
    scope its other-scope read does not — so a reader holding only the result
    recovers the applied filter and never reads a filtered slice as the whole
    library. The one invariant the scattered per-surface scope-echo tests pinned
    piecemeal."""
    main(["init"])
    db = get_paths().db_path
    _seed_completeness_mix(db)
    capsys.readouterr()

    # sanity: the fixture is non-vacuous — the whole-library audit spans both
    # sources (so the scoped `by_source` collapse is a real narrowing)
    whole = _cli_json(["doctor"], capsys)
    assert set(whole["custody"]["by_source"]) == {"web", "arxiv"}

    assert _scope_echo_failures(capsys) == set()


def test_cli_every_surface_distinguishes_empty_from_not_checked(scrolls_home, capsys):
    """Every CLI completeness surface returns the empty form of its shape for a
    checked-and-empty in-scope read (exit 0, nothing on stderr), and — where it
    has a could-not-check form — that form is loud (exit ≠ 0, `error` on stderr,
    empty stdout). 'Nothing found' is never confused with 'not checked.'"""
    main(["init"])
    db = get_paths().db_path
    _seed_completeness_mix(db)
    capsys.readouterr()

    for surface in sorted(_CLI_COMPLETENESS_SURFACES):
        argv, is_empty_shape = _CLI_EMPTY[surface]
        assert main(argv) == 0, f"{surface}: checked-and-empty must be exit 0"
        captured = capsys.readouterr()
        assert captured.err == "", f"{surface}: a real answer writes nothing to stderr"
        assert is_empty_shape(captured.out), f"{surface}: must return the empty form"

        if surface in _CLI_NOT_CHECKED:
            assert main(_CLI_NOT_CHECKED[surface]) != 0, (
                f"{surface}: a check that could not run must not exit 0")
            captured = capsys.readouterr()
            assert captured.out == "", f"{surface}: nothing on stdout when not checked"
            assert "error" in json.loads(captured.err), f"{surface}: error envelope"
        else:
            assert surface in _NO_COULD_NOT_CHECK, (
                f"{surface}: a surface with no could-not-check probe must be named")


def test_mcp_every_surface_distinguishes_empty_from_not_checked(scrolls_home):
    """The MCP twins honor the same axis-2 contract: a checked-and-empty read
    returns the empty form, and a could-not-check raises (the framework surfaces
    it as a tool error, never a silent empty success) — surface parity with the
    CLI guard above (custody-vision §6)."""
    main(["init"])
    db = get_paths().db_path
    _seed_completeness_mix(db)

    for surface in sorted(_MCP_COMPLETENESS_SURFACES):
        assert _MCP_EMPTY[surface](), f"{surface}: checked-and-empty must be the empty form"
        if surface in _MCP_NOT_CHECKED:
            with pytest.raises(ValueError):
                _MCP_NOT_CHECKED[surface]()
        else:
            assert surface in _NO_COULD_NOT_CHECK, (
                f"{surface}: a surface with no could-not-check probe must be named")


# --- the sabotage: dropping one scope echo fails only that surface -----------


def test_dropping_a_scope_echo_fails_only_that_surface(scrolls_home, capsys, monkeypatch):
    """The sabotage proves the scope-echo guard has teeth and is *isolating*:
    dropping one surface's scope echo (so a per-ref read claims whole-library
    completeness) fails *only* that surface's cell, not its twins.

    `cli.works_payload` is the CLI `works` payload builder, a *distinct* module
    binding from `mcp_server.works_payload` (the `get_works` twin) — so emitting
    the whole-library scope shape regardless of the ref desyncs only `works`. The
    MCP `get_works`, and every other browse/audit surface, read their own scope
    untouched. This is the regression the registry catches that a surface's own
    scope test misses."""
    main(["init"])
    db = get_paths().db_path
    _seed_completeness_mix(db)
    capsys.readouterr()

    # baseline: every live scope-echo surface discloses its scope
    assert _scope_echo_failures(capsys) == set()

    real_works_payload = cli.works_payload

    def _no_scope_echo(works, item_count, *, scope=None, verdicts=None):
        # the whole-library scope shape regardless of the ref — a per-ref read
        # now *claims whole-library completeness*, the exact fabrication forbidden
        return real_works_payload(
            works, item_count, scope={"min_representations": 2}, verdicts=verdicts)

    monkeypatch.setattr(cli, "works_payload", _no_scope_echo)

    assert _scope_echo_failures(capsys) == {"works"}
