"""The completeness contract — anti-fabrication / scope honesty (M2 G1).

`docs/cli.md` → "The completeness contract" promises that every browse and
audit surface (`search`, `list`, `related`, `works`, `context`, `doctor`,
`maintain`, `export bundle`) is scope-honest and completeness-honest: "nothing
found" is never confused with "not checked," and nothing is fabricated for
content the library does not hold (PRD cap 7, MVP M2, custody-vision §6).

`export bundle` (the shareable custody artifact, roadmap H12–H15) is the same
shape of promise on the *export* side: an empty scope yields a *valid,
importable* bundle that says ``No matching scrolls.`` — never an error and never
a fabricated entry — and an uninitialized library exports that same valid empty
bundle, never crashing on a missing store. A blank query is unparseable input,
so it errors loudly (the could-not-check half). Folding it here pins the
shareable artifact into the same G1 invariant every read surface satisfies.

`maintain` (the scheduled custody pass, roadmap H34) is an audit-shaped surface
too: run network-free with `--no-recheck`, its report must never fabricate a
custody picture for content the library does not hold — an uninitialized library
reports ``score: null`` (honest "no library"), never a perfect ``100``, and a
first run carries ``first_run: true`` with null deltas, never a fabricated
"no change". That honesty is the same G1 invariant, pinned here as the contract.

The compiled `library/` pages (roadmap H184) carry the same kind of derived
read — the `_Attention:_` (drift) and `_Refresh:_` (enrichment/summary debt)
action-pointer lines — so they obey G1 too: a clean / empty / single-source
compiled library never emits an `_Attention:_` it has no JSON `attention` basis
for, nor a `_Refresh:_` clause for an axis carrying no stale debt (roadmap H190,
the compiled-surface counterpart of the bundle/context honest-absence pinned in
`tests/test_custody_convergence.py`).

These tests pin G1 — *honest absence, honest failure* — as a single
cross-surface invariant rather than re-proving it per command, so the
already-true half cannot regress while G2 (scope echo + truncation honesty,
roadmap H6–H8) is implemented on top of it. The per-command empties and
errors are also asserted in their own suites; here we assert them *as the
contract*.
"""

import json

import pytest

from scrolls import mcp_server
from scrolls.cli import main
from scrolls.custody import CustodyEvent, record_events
from scrolls.doctor import run_doctor
from scrolls.items import ScrollItem, insert_item
from scrolls.paths import get_paths


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


def _item(item_id, **overrides):
    base = dict(
        id=item_id,
        source=item_id.split(":")[0],
        url=f"https://example.org/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00",
        title=item_id,
        extracted_text="alpha beta gamma delta",
        summary="alpha beta gamma delta",
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


@pytest.fixture
def populated(scrolls_home):
    """A non-empty, fully offline library.

    Deliberately populated so a "checked-and-empty" result proves the
    surface *looked at a real library and found nothing in scope* — not
    merely that the store was empty (which `before_init` covers separately).
    The lone item carries no links, tags, concepts, or DOI, so it is its own
    isolated node: `related` finds no neighbour and `works` finds no sibling.
    """
    main(["init"])
    db = get_paths().db_path
    insert_item(db, _item("web:lonely"))
    return db


# --- The empty form of each surface's own output shape -----------------------
#
# Each entry: argv that *checks a real, non-empty library and finds nothing
# in scope*, plus a predicate proving the surface returned the empty form of
# ITS shape (not an error, not a fabricated row).

CHECKED_EMPTY_CASES = {
    # a query no item's text matches → empty ranked array
    "search": (["search", "zzznotatoken"], lambda out: json.loads(out) == []),
    # a tag nothing carries → empty summary array (scope-honest empty)
    "list": (["list", "--tag", "nonexistent"], lambda out: json.loads(out) == []),
    # an isolated item → empty neighbour array
    "related": (["related", "web:lonely"], lambda out: json.loads(out) == []),
    # no multi-representation work in the library → empty works, stats present
    "works": (
        ["works"],
        lambda out: json.loads(out)["works"] == []
        and "items" in json.loads(out)["stats"],
    ),
    # an item that names no DOI → empty per-item works lens, not an error
    "works_ref": (
        ["works", "web:lonely"],
        lambda out: json.loads(out)["works"] == [],
    ),
    # a query nothing matches → a valid bundle that says so
    "context": (["context", "zzznotatoken"], lambda out: "No matching scrolls." in out),
    # a healthy library → a zero-finding report
    "doctor": (["doctor"], lambda out: json.loads(out)["issues"] == 0),
    # a healthy library, offline pass → zero structural issues, honest delta
    "maintain": (
        ["maintain", "--no-recheck"],
        lambda out: json.loads(out)["issues"] == 0
        and json.loads(out)["delta"]["first_run"] is True,
    ),
    # never maintained → an empty trend (honest absence), never a fabricated run
    "maintain_history": (
        ["maintain", "--history"],
        lambda out: json.loads(out) == [],
    ),
    # a query no item matches → a valid, importable bundle that says so
    "export_bundle": (
        ["export", "bundle", "zzznotatoken"],
        lambda out: "No matching scrolls." in out,
    ),
    # a held item the ledger never checked → an honest empty timeline, not an
    # error (the per-item custody ledger, roadmap H66): checked-and-empty
    "history": (["history", "web:lonely"], lambda out: json.loads(out) == []),
}


@pytest.mark.parametrize("name", sorted(CHECKED_EMPTY_CASES))
def test_checked_and_empty_is_exit_zero_in_normal_shape(populated, capsys, name):
    argv, is_empty_shape = CHECKED_EMPTY_CASES[name]
    capsys.readouterr()

    exit_code = main(argv)

    captured = capsys.readouterr()
    assert exit_code == 0, f"{name}: checked-and-empty must be exit 0, not a failure"
    assert captured.err == "", f"{name}: a real answer writes nothing to stderr"
    assert is_empty_shape(captured.out), f"{name}: must return the empty form of its shape"


# --- Could-not-check is loud: error envelope on stderr, empty stdout, exit≠0 --
#
# Bad input and unknown ids are "not checked." They must never masquerade as
# an empty success — that is the half of "empty ≠ error" an agent leans on.

COULD_NOT_CHECK_CASES = {
    "search_blank": ["search", '""'],
    "context_blank": ["context", '""'],
    "export_bundle_blank": ["export", "bundle", '""'],
    "related_unknown_id": ["related", "web:does-not-exist"],
    "works_unknown_ref": ["works", "web:does-not-exist"],
    "show_unknown_id": ["show", "web:does-not-exist"],
    # an unknown ref has no item to time-line — a loud could-not-check, never an
    # empty `[]` that a typo could masquerade as "no history" (the H66 split)
    "history_unknown_id": ["history", "web:does-not-exist"],
}


@pytest.mark.parametrize("name", sorted(COULD_NOT_CHECK_CASES))
def test_could_not_check_errors_loudly_not_emptily(populated, capsys, name):
    argv = COULD_NOT_CHECK_CASES[name]
    capsys.readouterr()

    exit_code = main(argv)

    captured = capsys.readouterr()
    assert exit_code != 0, f"{name}: a check that could not run must not exit 0"
    assert captured.out == "", f"{name}: nothing on stdout when the check could not run"
    assert "error" in json.loads(captured.err), f"{name}: an error envelope on stderr"


def test_empty_is_distinguishable_from_could_not_check(populated, capsys):
    """The contract's load-bearing distinction, asserted directly.

    The same surface, two situations: a query it *checked* and one it
    *could not parse*. Exit code + stream must tell them apart, so an agent
    never mistakes a fabrication-safe empty for a swallowed failure.
    """
    capsys.readouterr()

    # checked the library, found nothing
    checked = main(["search", "zzznotatoken"])
    checked_out = capsys.readouterr()
    assert checked == 0
    assert json.loads(checked_out.out) == []
    assert checked_out.err == ""

    # could not check: a blank query is unparseable input
    unchecked = main(["search", '""'])
    unchecked_out = capsys.readouterr()
    assert unchecked != 0
    assert unchecked_out.out == ""
    assert "error" in json.loads(unchecked_out.err)


def test_a_facet_that_excludes_everything_is_empty_not_error(populated, capsys):
    """A scope that matches no item is a first-class empty answer.

    "Nothing in *this* scope" must be the empty shape, exit 0 — never an
    error, and never a silent claim about the whole library. Covers the
    AND-ed facets on the query/browse surfaces.
    """
    surfaces = {
        "search": (["search", "alpha", "--source", "doesnotexist"], list),
        "list": (["list", "--category", "nope"], list),
        "context": (["context", "alpha", "--source", "doesnotexist"], None),
    }
    for name, (argv, _kind) in surfaces.items():
        capsys.readouterr()
        exit_code = main(argv)
        captured = capsys.readouterr()
        assert exit_code == 0, f"{name}: an excluding facet is empty, not an error"
        assert captured.err == "", f"{name}: no error envelope for an empty scope"
        if name == "context":
            assert "No matching scrolls." in captured.out
        else:
            assert json.loads(captured.out) == []


# Surfaces that browse the whole library (no anchoring id) must answer with
# the empty form of their shape before `init`, never an error — so the
# payload shape never varies between "no library yet" and "no matches."
BEFORE_INIT_CASES = {
    "search": (["search", "anything"], lambda out: json.loads(out) == []),
    "list": (["list"], lambda out: json.loads(out) == []),
    "works": (["works"], lambda out: json.loads(out)["works"] == []),
    "context": (["context", "anything"], lambda out: "No matching scrolls." in out),
    "doctor": (["doctor"], lambda out: json.loads(out).get("issues") == 0),
    # no library → honest null score (never a fabricated 100), first-run delta
    "maintain": (
        ["maintain", "--no-recheck"],
        lambda out: json.loads(out)["issues"] == 0
        and json.loads(out)["custody"]["score"] is None
        and json.loads(out)["delta"]["first_run"] is True,
    ),
    # no library → a valid empty importable bundle, never a crash on a missing store
    "export_bundle": (
        ["export", "bundle", "anything"],
        lambda out: "No matching scrolls." in out,
    ),
    # no library → an empty trend, never an error on a missing log
    "maintain_history": (
        ["maintain", "--history"],
        lambda out: json.loads(out) == [],
    ),
}


@pytest.mark.parametrize("name", sorted(BEFORE_INIT_CASES))
def test_before_init_is_empty_in_shape_across_surfaces(scrolls_home, capsys, name):
    argv, is_empty_shape = BEFORE_INIT_CASES[name]
    capsys.readouterr()

    exit_code = main(argv)

    captured = capsys.readouterr()
    assert exit_code == 0, f"{name}: a missing library reads empty, not an error"
    assert captured.err == "", f"{name}: no error envelope before init"
    assert is_empty_shape(captured.out), f"{name}: empty form of its shape before init"


# --- The MCP twins honor the same contract (surface parity) ------------------
#
# The contract claims G1 holds for "their MCP twins" too — the integrity
# boundary is the same whether an agent reads the CLI or the MCP tools
# (custody-vision §6: search ≡ list ≡ MCP ≡ facets). The MCP wrappers are
# plain functions over the same engines, so the analog of "exit 0 + empty
# shape" is "returns the empty form," and the analog of an error envelope on
# stderr is a raised exception the framework surfaces as a tool error.

MCP_CHECKED_EMPTY = {
    "search_scrolls": lambda: mcp_server.search_scrolls("zzznotatoken") == [],
    "list_scrolls": lambda: mcp_server.list_scrolls(tag="nonexistent") == [],
    "get_scroll_history": lambda: mcp_server.get_scroll_history("web:lonely") == [],
    "get_related_scrolls": lambda: mcp_server.get_related_scrolls("web:lonely") == [],
    "get_works": lambda: mcp_server.get_works()["works"] == [],
    "get_works_item": lambda: mcp_server.get_works(item="web:lonely")["works"] == [],
    "get_context_bundle": lambda: "No matching scrolls."
    in mcp_server.get_context_bundle("zzznotatoken"),
    # a never-maintained library → an empty trend (honest absence), never a
    # fabricated run; the MCP twin of `maintain --history`'s empty `[]` (H198)
    "get_maintenance_history": lambda: mcp_server.get_maintenance_history() == [],
}


@pytest.mark.parametrize("name", sorted(MCP_CHECKED_EMPTY))
def test_mcp_checked_and_empty_returns_the_empty_shape(populated, name):
    assert MCP_CHECKED_EMPTY[name](), f"{name}: checked-and-empty must be the empty form"


MCP_COULD_NOT_CHECK = {
    "search_scrolls_blank": lambda: mcp_server.search_scrolls("   "),
    "get_context_bundle_blank": lambda: mcp_server.get_context_bundle("   "),
    "get_related_unknown": lambda: mcp_server.get_related_scrolls("web:does-not-exist"),
    "get_works_unknown_item": lambda: mcp_server.get_works(item="web:does-not-exist"),
    "get_scroll_unknown": lambda: mcp_server.get_scroll("web:does-not-exist"),
    "get_scroll_history_unknown": lambda: mcp_server.get_scroll_history("web:does-not-exist"),
}


@pytest.mark.parametrize("name", sorted(MCP_COULD_NOT_CHECK))
def test_mcp_could_not_check_raises_not_emptily(populated, name):
    # The MCP analog of "loud failure": a check it could not run raises, so the
    # framework reports a tool error — never a silent empty success.
    with pytest.raises(ValueError):
        MCP_COULD_NOT_CHECK[name]()


# --- The compiled `library/` pages honor the same honest-absence contract -----
#
# The compiled `library/` index + group pages carry the readable `_Attention:_`
# (drift, roadmap H159/H184) and `_Refresh:_` (enrichment/summary debt, roadmap
# H178/H184) action-pointer lines. Those are *derived reads*, so they obey G1: a
# compiled page never shows an `_Attention:_` it has no JSON `attention` basis for,
# nor a `_Refresh:_` clause for an axis carrying no stale debt — the compiled-page
# counterpart of the bundle/context honest-absence already pinned for the JSON flag
# (`test_readable_attention_line_absent_together_with_the_json_flag`) and the
# refresh line (`test_bundle_refresh_line_omitted_when_no_stale_debt`). Roadmap H190.


def _stale_classified(item_id, **overrides):
    """A rendered item whose rules category was stamped under a superseded ruleset.

    The live ruleset would no longer reproduce it, so `doctor` reports enrichment
    debt for its source — a real basis for a `_Refresh:_` classifications clause.
    """
    base = dict(
        category="tutorial",
        stage="rendered",
        markdown_path=f"scrolls/{item_id.replace(':', '/')}.md",
        raw_text="<raw>alpha</raw>",
        content_hash=f"sha256:{item_id}",
        provenance={
            "classified_by": "rules-v1",
            "classified_basis": "weak-source",
            "classified_ruleset": "deadbeef0000",
        },
    )
    base.update(overrides)
    return _item(item_id, **base)


def _rendered(item_id, **overrides):
    """A clean, fully-held rendered item (full fidelity, no drift, no stale debt)."""
    base = dict(
        stage="rendered",
        markdown_path=f"scrolls/{item_id.replace(':', '/')}.md",
        raw_text="<raw>alpha</raw>",
        content_hash=f"sha256:{item_id}",
    )
    base.update(overrides)
    return _item(item_id, **base)


def test_compiled_pages_omit_action_lines_with_no_basis(scrolls_home, capsys):
    # An empty library and a clean multi-source library each compile pages that show
    # the custody headline (and, multi-source, the `_By source:_` split) but never an
    # `_Attention:_`/`_Refresh:_` pointer — tied to the JSON `attention` being null.
    library = get_paths().library_dir

    # phase 1: an empty initialized library compiles with no action lines anywhere
    main(["init"])
    assert main(["kb"]) == 0
    capsys.readouterr()
    index_md = (library / "index.md").read_text(encoding="utf-8")
    assert "_Custody: 0 scroll(s)._" in index_md  # the honest empty headline
    assert "_Attention:" not in index_md
    assert "_Refresh:" not in index_md

    # phase 2: a clean two-source library — held, verified, no stale enrichment/summary
    db = get_paths().db_path
    insert_item(db, _rendered("web:a"))
    insert_item(
        db, _rendered("arxiv:b", url="https://arxiv.org/abs/b")
    )
    capsys.readouterr()

    # the JSON basis: doctor finds no cross-source loss and no stale debt, so the
    # `status` attention flag is null and both debt maps are empty
    custody = run_doctor(get_paths())["custody"]
    assert set(custody["by_source"]) == {"web", "arxiv"}  # genuinely multi-source
    assert custody["enrichment"]["by_source"] == {}
    assert custody["summaries"]["by_source"] == {}
    assert main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["attention"] is None

    assert main(["kb"]) == 0
    capsys.readouterr()
    index_md = (library / "index.md").read_text(encoding="utf-8")
    assert "_By source:_" in index_md     # the multi-source split DID compute...
    assert "_Attention:" not in index_md  # ...but no loss → no fabricated pointer
    assert "_Refresh:" not in index_md    # no stale debt → no fabricated pointer


def test_compiled_refresh_line_is_per_axis_honest(scrolls_home, capsys):
    # The `_Refresh:_` line shows only the axes that carry stale debt: a library with
    # a stale *classification* but no stale *summary* shows the classifications clause
    # and never fabricates a summaries clause — axis-level honest absence, tied to
    # doctor's empty summary map (the basis a fabricated clause would lack).
    main(["init"])
    db = get_paths().db_path
    insert_item(db, _stale_classified("web:stale"))
    capsys.readouterr()

    custody = run_doctor(get_paths())["custody"]
    assert custody["enrichment"]["by_source"] == {"web": 1}  # a real refresh basis
    assert custody["summaries"]["by_source"] == {}           # no summary basis

    assert main(["kb"]) == 0
    capsys.readouterr()
    index_md = (get_paths().library_dir / "index.md").read_text(encoding="utf-8")
    assert "classifications stale in" in index_md   # the axis that has a basis
    assert "summaries stale in" not in index_md     # the axis that does not → omitted
    assert "_Attention:" not in index_md            # single source, no drift → no pointer


# --- The leanest `context` budget names fidelity holdings, never a drift verdict --
#
# The progressive `context --budget` tiers (MVP M3) bound bundle *depth*. The
# leanest `index` tier reads no custody ledger at all (`context.py`: the
# `latest_events` read is gated to `connected`+), so it must obey G1 the way the
# compiled pages do (H190): it states what it *holds* — the `_Fidelity:_` holdings
# line, fidelity being a ledger-free fact derived from stored fields (roadmap H212,
# vision principle 3: *fidelity travels with every result*) — but it never asserts a
# *drift* verdict it did not read. A `verified`/`unverified`/`drifted` claim over an
# unread ledger would be the exact fabrication M2 forbids ("nothing checked" dressed
# as a verdict). The same query at `connected`+ *does* read the ledger and carries
# the `_Custody:_` headline with its drift section, so the `index` absence is a
# genuine withholding, not an empty scope with nothing to report. This is the
# budget/tier-honesty counterpart of the compiled-page action-line honest-absence
# (H190) and the per-excerpt drift block's honesty (the `full` budget): the holdings
# fact travels at every tier, the drift claim only where a ledger was read. Roadmap
# H215; the MCP twin of this read-surface contract is H219.


def _fidelity_line(out):
    return next(line for line in out.splitlines() if line.startswith("_Fidelity:"))


def test_index_budget_names_fidelity_holdings_but_no_drift_verdict(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    # a held item the query matches, carrying a *recorded* drift verdict in the
    # ledger — so the `index` tier's silence below is the withholding of a real
    # verdict it didn't read, not the emptiness of a scope with nothing to report.
    # The id/title carry no "drift" substring, so the absence assertion below targets
    # the rendered drift *verdict*, not the item's own name.
    insert_item(db, _rendered("web:moved"))
    record_events(
        db,
        [
            CustodyEvent(
                item_id="web:moved",
                checked_at="2026-06-14T00:00:00+00:00",
                status="drifted",
                prior_hash="sha256:web:moved",
                observed_hash="cafe1234",
            )
        ],
    )
    capsys.readouterr()

    # the leanest tier states what it HOLDS — the fidelity holdings fact and its
    # scope (`of K`) — so fidelity travels even where no ledger is read ...
    assert main(["context", "alpha", "--budget", "index"]) == 0
    index_out = capsys.readouterr().out
    line = _fidelity_line(index_out)
    assert "full 1" in line          # the holdings fact (the item is full-fidelity)
    assert "(of 1)" in line          # ... named with its holdings scope
    # ... but never a drift verdict it did not read (the M2 anti-fabrication half):
    # no `_Custody:_` headline and no drift token of any posture.
    assert "_Custody:" not in index_out
    assert "drift" not in index_out

    # the SAME query at `connected`+ DID read the ledger → the `_Custody:_` headline
    # carries the recorded drift verdict, proving the `index` absence above is a
    # genuine withholding (the tier could have read it; it honestly did not).
    for tier in ("connected", "full"):
        assert main(["context", "alpha", "--budget", tier]) == 0
        deep_out = capsys.readouterr().out
        assert "_Custody:" in deep_out
        assert "drift drifted 1" in deep_out
        assert "_Fidelity:" not in deep_out  # the headline carries fidelity above index
