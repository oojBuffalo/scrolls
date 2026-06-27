"""The browse-filter drill contract (roadmap H403) — one completeness-asserted invariant.

The tenth **contract-consolidation** cell (after H388's whole-MCP determinism
contract … H402's reconcile-safety contract) and the *filter*-axis sibling of
H397's read-parity matrix. Where H397 pins that every browse surface reads the
*same per-item custody axis*, this pins the dual: that **drilling** from the
unfiltered surface by a custody/rank filter returns *exactly* the rows that
surface already carries at the filter's axis value — the drill-from-the-aggregate
guarantee (custody-vision §2.6; the PRD "filter consistency / surface parity"
success metric).

The claim, for *every* custody/rank browse filter (`--fidelity`, `--drift`,
`--strength`, `--content-duplicate`) on `search`/`list` (+ the MCP
`search_scrolls`/`list_scrolls` twins): the filtered surface selects exactly
`{id : the unfiltered surface's row at that id matches the filter at this value}`,
and every returned row's own axis reading is consistent with the filter (no
off-axis leak). The drill is read off the *unfiltered surface itself* (and, for
the content-duplicate flag, the canonical `content_duplicate_ids` projection
the browse row does not carry), so a filter whose selection diverges from the
rows the surface reports its own axis on desyncs and fails *its* leg — not every
test that happens to exercise it.

Two faces, the H388/H394/H397 shape:

1. **The completeness keystone** — `_BROWSE_FILTERS` (each custody/rank filter ×
   the surfaces it rides) is held to the live argparse registry: for each of
   `search`/`list`, the declared drill flags ∪ a *named* non-drill set partition
   that subparser's optionals *exactly*, so a *new* browse filter fails the
   contract until it declares a drill (or is named non-drill). The same tie holds
   on the MCP twins' signatures. The H394 registry-completeness mechanism on the
   browse-filter axis.

2. **The matrix guard** — over one wide non-vacuous fixture (every fidelity tier,
   every drift posture, a content-duplicate pair, and a query that lands in all
   three strength bands), every (filter, surface, value) drill holds; and a
   sabotage that admits one off-axis row into one filter's selection fails *only*
   that filter's legs (the `--drift` selector `items_in_posture`, distinct from
   the row's `drift_posture` and the search surfaces' SQL UDF).
"""

import argparse
import dataclasses
import inspect
import json

import pytest

import scrolls.custody as custody
import scrolls.mcp_server as mcp_server
from scrolls.cli import build_parser, main
from scrolls.custody import CustodyEvent, record_events
from scrolls.items import ScrollItem, content_duplicate_ids, insert_item, list_items
from scrolls.paths import get_paths
from scrolls.search import STRENGTH_BANDS


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


def _seed_browse_filter_mix(db):
    """A wide library where every browse-filter drill is non-vacuous.

    So the drill below is real (an all-`full`, all-`unverified`, no-duplicate
    library would pass a mis-derived filter too). Every title carries "topic" so
    `search topic` enumerates the whole library — the same scope `list` reads, so
    the search and list drills share a denominator:

    - **fidelity** spans all three tiers — eight `full` (raw + hash, captured
      stage), one `partial` (`web:partial`, extracted-only, no hash), one
      `reference` (`crossref:ref`, a title-only pointer);
    - **drift** spans all five postures — `verified` (`web:dup1`, re-checked
      unchanged), `drifted`, `rotted`, `error`, and `unverified` (never checked);
    - **content-duplicate** — `web:dup1`/`web:dup2` are byte-identical (one
      `content_hash`) → the only duplicate pair; every other item is unique;
    - **strength** — a rare token "beacon" lands in a *title* (`web:s_strong` →
      strong), a *summary* (`web:s_moderate` → moderate), and a *body* sentence
      (`web:s_weak` → weak), so `search beacon` returns one hit in each band.
    """
    # the content-duplicate pair: byte-identical, both full + verified/unverified
    insert_item(db, _item(
        "web:dup1", "Topic full dup one",
        extracted_text="same dup body", raw_text="<raw>dup</raw>",
        content_hash="sha256:dup", stage="rendered"))
    insert_item(db, _item(
        "web:dup2", "Topic full dup two",
        extracted_text="same dup body", raw_text="<raw>dup</raw>",
        content_hash="sha256:dup", stage="rendered"))
    # the four moved-posture full holdings
    insert_item(db, _item(
        "web:drift", "Topic full drift",
        extracted_text="topic drift", raw_text="<raw>drift</raw>",
        content_hash="sha256:wd", stage="rendered"))
    insert_item(db, _item(
        "web:rot", "Topic full rot",
        extracted_text="topic rot", raw_text="<raw>rot</raw>",
        content_hash="sha256:rt", stage="rendered"))
    insert_item(db, _item(
        "web:err", "Topic full err",
        extracted_text="topic err", raw_text="<raw>err</raw>",
        content_hash="sha256:er", stage="rendered"))
    # the lower-fidelity tiers: partial (extracted, no hash) + reference (pointer)
    insert_item(db, _item(
        "web:partial", "Topic partial", extracted_text="topic partial body"))
    insert_item(db, _item(
        "crossref:ref", "Topic crossref ref", source="crossref",
        url="https://example.org/crossref-ref"))
    # the three strength bands under the rare token "beacon" — each full + unverified
    insert_item(db, _item(
        "web:s_strong", "Topic beacon strong one",
        summary="ordinary opener", extracted_text="an ordinary body sentence",
        raw_text="<raw>s1</raw>", content_hash="sha256:s1", stage="rendered"))
    insert_item(db, _item(
        "web:s_moderate", "Topic moderate two",
        summary="beacon in the summary", extracted_text="an ordinary body sentence",
        raw_text="<raw>s2</raw>", content_hash="sha256:s2", stage="rendered"))
    insert_item(db, _item(
        "web:s_weak", "Topic weak three",
        summary="ordinary opener", extracted_text="later a beacon appears in the body",
        raw_text="<raw>s3</raw>", content_hash="sha256:s3", stage="rendered"))
    record_events(db, [
        CustodyEvent("web:dup1", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:dup", "sha256:dup", None),
        CustodyEvent("web:drift", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:wd", "sha256:x", None),
        CustodyEvent("web:rot", "2026-06-14T00:00:00+00:00", "rotted",
                     "sha256:rt", None, "HTTP Error 404"),
        CustodyEvent("web:err", "2026-06-14T00:00:00+00:00", "error",
                     "sha256:er", None, "boom"),
        # dup2, partial, crossref:ref, and the three beacon items left unverified
    ])


# --- the browse-filter registry — the completeness keystone ------------------


@dataclasses.dataclass(frozen=True)
class _BrowseFilter:
    """One custody/rank browse filter and how to drill it.

    `flag`/`param` are the argparse flag and the `search_items`/`list_items`/MCP
    kwarg name. `commands` names the CLI subcommands the filter rides (each
    expands to its CLI + MCP twin surfaces). `kind` chooses the drill semantics:
    `value` (exact equality on `axis_key`), `band` (the at-or-above rank-band
    prefix), or `flag` (the boolean content-identity predicate, read off the
    canonical projection the browse row does not carry). `values` is the domain to
    drill over; `query` is the search term that makes the drill non-vacuous on the
    ranked surfaces.
    """

    flag: str
    param: str
    commands: tuple
    kind: str
    values: tuple
    axis_key: str | None
    query: str


_BROWSE_FILTERS = {
    "fidelity": _BrowseFilter(
        "--fidelity", "fidelity", ("search", "list"), "value",
        ("full", "partial", "reference"), "fidelity", "topic"),
    "drift": _BrowseFilter(
        "--drift", "drift", ("search", "list"), "value",
        ("verified", "unverified", "drifted", "rotted", "error"), "drift", "topic"),
    "strength": _BrowseFilter(
        "--strength", "strength", ("search",), "band",
        STRENGTH_BANDS, "match_strength", "beacon"),
    "content_duplicate": _BrowseFilter(
        "--content-duplicate", "content_duplicate", ("search", "list"), "flag",
        (True,), None, "topic"),
}

# Each CLI command's two browse surfaces — the CLI command and its MCP twin —
# read by the *same* `search_items`/`list_items` core, so the matrix pins both.
_SURFACE_TWINS = {
    "search": ("search", "search_scrolls"),
    "list": ("list", "list_scrolls"),
}

# The `search`/`list` optionals that are *not* custody/rank drill filters — each
# named, never a silent skip. The plain facets (`--source`/`--category`/…) and
# the page/envelope toggles (`--limit`/`--stats`) carry no custody axis to drill;
# the `--stale-*` filters are custody-adjacent but range/flag reads whose drill is
# pinned by their own act↔read convergence guards (H85/H185/H189), not this
# value/band/flag matrix.
_NON_DRILL_FLAGS = {
    "--limit": "page-size cap, not a custody/rank axis",
    "--stats": "scope-honesty envelope toggle (H6), not a row filter",
    "--source": "source facet; aggregate parity pinned by H397/facets",
    "--category": "category facet, not a custody/rank axis",
    "--stage": "pipeline-stage facet, not a custody/rank axis",
    "--tag": "tag membership facet, not a custody/rank axis",
    "--concept": "concept membership facet, not a custody/rank axis",
    "--stale-before": "drift-time window; drill pinned by H85 (verify --stale-before twin)",
    "--stale-classification": "enrichment stale set; drill pinned by H185 (classify --stale)",
    "--stale-summary": "summary stale set; drill pinned by H189 (kb --stale)",
}

# The MCP-signature analogue: the `search_scrolls`/`list_scrolls` kwargs that are
# not drill filters (the same vocabulary as `_NON_DRILL_FLAGS`, on the param axis).
_NON_DRILL_PARAMS = {
    "query", "limit", "source", "category", "stage", "tag", "concept",
    "stale_before", "stale_classification", "stale_summary",
}


def _subparser_optionals(command):
    """The `--flag` optionals of one live subparser (minus argparse's `--help`)."""
    parser = build_parser()
    sub = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    cmd = sub.choices[command]
    flags = set()
    for action in cmd._actions:
        for opt in action.option_strings:
            if opt.startswith("--") and opt != "--help":
                flags.add(opt)
    return flags


# --- keystone 1: the registry covers the live argparse filter surface --------


def test_browse_filter_registry_partitions_the_search_list_flags():
    """`_BROWSE_FILTERS` (the drill flags) ∪ `_NON_DRILL_FLAGS` partition the live
    `search`/`list` subparser optionals *exactly* — so a *new* filter flag fails
    the contract until it declares a drill or is named non-drill. The H394
    registry-completeness mechanism on the browse-filter axis."""
    for command in ("search", "list"):
        live = _subparser_optionals(command)
        drill = {f.flag for f in _BROWSE_FILTERS.values() if command in f.commands}
        non_drill = set(_NON_DRILL_FLAGS) & live
        # every declared drill flag for this command really exists on it
        assert drill <= live, (command, drill - live)
        # disjoint, and together cover the whole subparser optional surface
        assert drill.isdisjoint(non_drill)
        assert drill | non_drill == live, (
            command, f"unclassified={live - drill - non_drill}"
        )
    # the load-bearing distinctions the registry encodes (sanity, not a tautology):
    # --strength is a search-only rank filter, and the registry says so
    assert "--strength" in _subparser_optionals("search")
    assert "--strength" not in _subparser_optionals("list")
    assert _BROWSE_FILTERS["strength"].commands == ("search",)
    # every named non-drill flag is a real flag on at least one of the two surfaces
    every_flag = _subparser_optionals("search") | _subparser_optionals("list")
    assert set(_NON_DRILL_FLAGS) <= every_flag


def test_browse_filter_registry_partitions_the_mcp_twin_signatures():
    """The same partition on the MCP twins' kwargs — the drill params each twin
    declares ∪ the named non-drill params cover its signature *exactly*, so a
    *new* filter kwarg on `search_scrolls`/`list_scrolls` fails until classified."""
    twins = {
        "search": mcp_server.search_scrolls,
        "list": mcp_server.list_scrolls,
    }
    for command, fn in twins.items():
        params = set(inspect.signature(fn).parameters)
        drill = {f.param for f in _BROWSE_FILTERS.values() if command in f.commands}
        non_drill = _NON_DRILL_PARAMS & params
        assert drill <= params, (command, drill - params)
        assert drill.isdisjoint(non_drill)
        assert drill | non_drill == params, (
            command, f"unclassified={params - drill - non_drill}"
        )


# --- the drill matrix --------------------------------------------------------


def _rows(surface, query, applied, capsys):
    """`{id: row}` for one browse surface, optionally with one filter applied.

    `applied` is `{param: value}` (empty for the unfiltered read). A large
    `limit` keeps the cap from truncating the drill denominator on the ranked
    surfaces."""
    if surface == "search":
        argv = ["search", query, "--limit", "100", *_cli_flags(applied)]
        assert main(argv) == 0
        data = json.loads(capsys.readouterr().out)
    elif surface == "list":
        argv = ["list", "--limit", "100", *_cli_flags(applied)]
        assert main(argv) == 0
        data = json.loads(capsys.readouterr().out)
    elif surface == "search_scrolls":
        data = mcp_server.search_scrolls(query, limit=100, **applied)
    elif surface == "list_scrolls":
        data = mcp_server.list_scrolls(limit=100, **applied)
    else:  # pragma: no cover - guarded by the keystone
        raise AssertionError(f"unknown browse surface {surface!r}")
    return {row["id"]: row for row in data}


def _cli_flags(applied):
    """`{param: value}` → the argv flags `_rows` appends to a CLI read."""
    flags = []
    for param, value in applied.items():
        flag = next(f.flag for f in _BROWSE_FILTERS.values() if f.param == param)
        if isinstance(value, bool):
            if value:
                flags.append(flag)
        else:
            flags += [flag, value]
    return flags


def _at_or_above(band):
    """The strength bands at or above `band` — the prefix `--strength` keeps."""
    order = list(STRENGTH_BANDS)
    return set(order[: order.index(band) + 1])


def _expected_ids(f, value, unfiltered, dup_members):
    """The ids the drill *should* keep: read off the unfiltered surface's own axis
    (or, for the content-duplicate flag, the canonical duplicate-member set)."""
    if f.kind == "value":
        return {iid for iid, row in unfiltered.items() if row[f.axis_key] == value}
    if f.kind == "band":
        bands = _at_or_above(value)
        return {iid for iid, row in unfiltered.items() if row[f.axis_key] in bands}
    # flag: the browse row carries no content-duplicate field, so the drill basis
    # is the canonical projection the per-item read rides (H328)
    return {iid for iid in unfiltered if iid in dup_members}


def _row_consistent(f, value, iid, row, dup_members):
    """Whether a returned row's own axis reading is consistent with the filter —
    the no-off-axis-leak half (exact for value, at-or-above for band, membership
    for the flag)."""
    if f.kind == "value":
        return row[f.axis_key] == value
    if f.kind == "band":
        return row[f.axis_key] in _at_or_above(value)
    return iid in dup_members


def _drill_failures(db, capsys):
    """The set of (surface, filter-key) cells whose drill disagrees with the
    unfiltered surface. The matrix guard asserts this is empty; the sabotage
    asserts it is exactly the cells it broke."""
    items = list_items(db)
    dup_members = {it.id for it in items if content_duplicate_ids(it, items)}
    failures = set()
    for fkey, f in _BROWSE_FILTERS.items():
        for command in f.commands:
            for surface in _SURFACE_TWINS[command]:
                unfiltered = _rows(surface, f.query, {}, capsys)
                cell_ok = True
                for value in f.values:
                    filtered = _rows(surface, f.query, {f.param: value}, capsys)
                    expected = _expected_ids(f, value, unfiltered, dup_members)
                    if set(filtered) != expected:
                        cell_ok = False
                    elif not all(
                        _row_consistent(f, value, iid, row, dup_members)
                        for iid, row in filtered.items()
                    ):
                        cell_ok = False
                if not cell_ok:
                    failures.add((surface, fkey))
    return failures


def _assert_fixture_non_vacuous(db, capsys):
    """Every filter's drill bites — each value selects a non-empty *proper* subset
    of the unfiltered scope, so a mis-derived filter has a wrong set to land on
    (not 0 == 0). Read off the `search` surface (the whole "topic"/"beacon"
    scope)."""
    items = list_items(db)
    dup_members = {it.id for it in items if content_duplicate_ids(it, items)}
    assert dup_members == {"web:dup1", "web:dup2"}

    topic = _rows("search", "topic", {}, capsys)
    assert len(topic) == 10  # the whole library matches "topic"
    fidelities = {row["fidelity"] for row in topic.values()}
    assert fidelities == {"full", "partial", "reference"}
    drifts = {row["drift"] for row in topic.values()}
    assert drifts == {"verified", "unverified", "drifted", "rotted", "error"}

    beacon = _rows("search", "beacon", {}, capsys)
    assert {row["match_strength"] for row in beacon.values()} == {
        "strong", "moderate", "weak"}
    assert {iid: row["match_strength"] for iid, row in beacon.items()} == {
        "web:s_strong": "strong",
        "web:s_moderate": "moderate",
        "web:s_weak": "weak",
    }


def test_every_browse_filter_drills_exactly_the_unfiltered_rows(scrolls_home, capsys):
    """Over the wide non-vacuous fixture, every (filter, surface, value) drill keeps
    exactly the rows the unfiltered surface carries at that axis value, with every
    returned row's own axis consistent with the filter — the drill-from-the-
    aggregate guarantee, pinned once across `search`/`list` and their MCP twins."""
    main(["init"])
    db = get_paths().db_path
    _seed_browse_filter_mix(db)
    capsys.readouterr()

    _assert_fixture_non_vacuous(db, capsys)

    assert _drill_failures(db, capsys) == set()


def test_a_filter_admitting_one_off_axis_row_fails_only_that_filter(
    scrolls_home, capsys, monkeypatch
):
    """The sabotage proves the matrix has teeth and isolates to the *filter*:
    leaking one off-axis row into the `--drift` selection fails *only* the drift
    legs, not its fidelity/strength/content-duplicate siblings nor the search
    surfaces.

    `custody.items_in_posture` is the selector `list_items(drift=)` filters
    through — a *distinct* code path from the row's own `drift_posture` field and
    from the search surfaces' `scrolls_drift` SQL UDF. So admitting the genuinely
    *drifted* `web:drift` into the `verified` selection desyncs only the two list
    drift legs from the rows those surfaces report `verified` on; the search drift
    legs (SQL UDF) and every other filter stay green."""
    main(["init"])
    db = get_paths().db_path
    _seed_browse_filter_mix(db)
    capsys.readouterr()

    # baseline: clean
    assert _drill_failures(db, capsys) == set()

    real_items_in_posture = custody.items_in_posture

    def _leaky(items, verdicts, posture):
        kept = real_items_in_posture(items, verdicts, posture)
        if posture == "verified":
            extra = [it for it in items if it.id == "web:drift"]
            return kept + [it for it in extra if it not in kept]
        return kept

    monkeypatch.setattr(custody, "items_in_posture", _leaky)

    assert _drill_failures(db, capsys) == {("list", "drift"), ("list_scrolls", "drift")}
