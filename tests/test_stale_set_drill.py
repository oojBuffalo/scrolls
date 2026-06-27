"""The stale-set drill contract (roadmap H410) — one completeness-asserted invariant.

The seventeenth **contract-consolidation** cell and the *staleness*-axis sibling
of H403's browse-filter drill matrix. H403 pinned the value/band/flag custody
filters (`--fidelity`/`--drift`/`--strength`/`--content-duplicate`) and *named as
exempt* the three custody-adjacent **stale-axis** filters of its `_NON_DRILL_FLAGS`
(`--stale-before`/`--stale-classification`/`--stale-summary`), deferring each to
its own scattered act↔read convergence guard (H85/H185/H189). This cell
consolidates those three guards into one invariant: each `--stale-*` filter on
`list` (+ the MCP `list_scrolls` twin) selects *exactly* the rows its act-side
companion would act on —

- `--stale-before <ISO>` ≡ the set `verify --stale-before` re-captures (H85);
- `--stale-classification` ≡ `classify --stale`'s targets ≡ `doctor`'s
  `custody.enrichment.stale` (H185);
- `--stale-summary` ≡ `kb --stale`'s cluster members (H189);

— and, where it has one, totals the `doctor`/`get_library_health` aggregate.

Two faces, the H388/H394/H403 shape:

1. **The completeness keystone** — `_STALE_FILTERS` is held to *exactly* the
   stale-axis flags H403's `_NON_DRILL_FLAGS` names (imported from
   `test_browse_filter_drill`, so the two browse-filter registries can't drift: a
   `list` filter flag is either an H403 value/band/flag drill or an H410 stale-axis
   drill, never silently neither). A *new* stale-axis filter H403 exempts fails this
   contract until it declares a drill. The same partition holds on the MCP twin's
   `list_scrolls` signature.

2. **The drill matrix** — over one fixture non-vacuous on every stale axis (a
   ledger-old never-checked item, a superseded-ruleset classification, a member of
   a stale concept summary), each (`--stale-*`, surface) drill selects exactly the
   act-side selector's targets — read off the *real* selector (a reference captured
   before any monkeypatch), never the read-side's own lazily-bound seam — and the
   aggregate ties total it. A sabotage that admits one *fresh* row into one filter's
   post-SQL selector (`custody.items_checked_before` /
   `classify.stale_classifications` / `kb_llm.stale_summary_members` — three
   distinct seams, the H403 selector-isolation precedent) fails *only* that filter's
   two `list` legs (CLI + MCP twin), never its stale siblings nor the audit ties
   (which read an independent fold).

Test-only, no production change — the three stale filters are already convergent
with their act-side companions (one `is_stale_classification` /
`items_checked_before` / `is_stale_summary` home each); this pins the family as one
contract that auto-covers a *new* stale-axis filter.
"""

import dataclasses
import inspect
import json
from typing import Callable

import pytest

import scrolls.classify as classify
import scrolls.custody as custody
import scrolls.kb_llm as kb_llm
import scrolls.mcp_server as mcp_server
from scrolls.cli import main
from scrolls.custody import CustodyEvent, record_events
from scrolls.doctor import run_doctor
from scrolls.items import ScrollItem, insert_item, list_items
from scrolls.kb import load_concept_summaries, slugify
from scrolls.paths import get_paths

# Cross-imports — the keystone source. `_NON_DRILL_FLAGS`/`_BROWSE_FILTERS` are
# H403's browse-filter registries; importing them is what forces a *new*
# stale-axis exemption in H403 into this contract (the two can't drift). The H405
# `from test_roundtrip import …` cross-test idiom; `_seed_refresh_debt` is the
# proven H185/H189 refresh-debt fixture (stale-classification + stale-summary).
from test_browse_filter_drill import (  # noqa: E402
    _BROWSE_FILTERS,
    _NON_DRILL_FLAGS,
    _subparser_optionals,
)
from test_cli import _seed_refresh_debt  # noqa: E402


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


# The act-side selectors, captured *before* any monkeypatch, so the canonical
# target sets below read the real fold even when the read-side's lazily-bound seam
# is sabotaged (the H403 `real_items_in_posture` precedent on three seams).
_REAL_ITEMS_CHECKED_BEFORE = custody.items_checked_before
_REAL_STALE_CLASSIFICATIONS = classify.stale_classifications
_REAL_STALE_SUMMARY_MEMBERS = kb_llm.stale_summary_members

# A pre-normalized UTC boundary (the form `parse_since` is idempotent on): the
# fixture verifies some members *after* it (fresh) and leaves others never-checked
# (trivially stale), so `--stale-before` selects a non-empty proper subset.
_STALE_BOUNDARY = "2026-06-13T00:00:00+00:00"


def _seed_stale_mix(paths):
    """A library non-vacuous on every stale axis, every item hash-bearing.

    Reuses the H185/H189 `_seed_refresh_debt` fixture — four rendered concept
    members (all `content_hash`-bearing) carrying both stale-classification debt
    (three superseded-ruleset items) and stale-summary debt (two stale concept
    clusters, four members) — and adds:

    - a **stale-before window**: two members verified fresh (a verdict *after* the
      boundary) and the other two left never-checked (trivially stale), so the
      `--stale-before` set is a non-empty *proper* subset; and
    - a **plain off-axis item** (`web:plain`, no concept, never stale-classified,
      verified fresh) — fresh on all three axes, so each stale set leaves an
      off-axis row for the sabotage's one-fresh-row leak to land on.

    Every held item is hash-bearing, so `verify --stale-before`'s hash-bearing
    candidate set coincides with `list`'s whole-library scope and the two converge
    exactly (the H85 act↔read tie has no hash-fidelity gap to reconcile here).
    """
    _seed_refresh_debt(paths)
    db = paths.db_path
    members = list_items(db)  # the four concept members, all hash-bearing
    insert_item(db, ScrollItem(
        id="web:plain", source="web", url="https://web.example.com/plain",
        saved_at="2026-06-14T00:00:00+00:00", title="Plain note",
        extracted_text="a plain body", content_hash="sha256:plain",
        stage="rendered"))
    # the stale-before window: verify the first two members + the plain item after
    # the boundary (fresh); leave the remaining members never-checked (stale).
    fresh = list(members[:2]) + [
        it for it in list_items(db) if it.id == "web:plain"
    ]
    record_events(db, [
        CustodyEvent(it.id, "2026-06-14T00:00:00+00:00", "unchanged",
                     it.content_hash, it.content_hash, None)
        for it in fresh
    ])
    return db


# --- the stale-filter registry — the completeness keystone -------------------


@dataclasses.dataclass(frozen=True)
class _StaleAudit:
    """How a stale filter ties to the live `doctor`/`get_library_health` audit.

    `ids(report, db)` re-derives the expected stale id set from the audit (an
    *independent* fold from the read-side's selector seam, so it stays correct
    under a read-side sabotage). `count`/`health` are the scalar aggregate tie when
    the audit carries one — `None` when it does not (a member set with no scalar).
    """

    ids: Callable
    count: Callable | None
    health: Callable | None


@dataclasses.dataclass(frozen=True)
class _StaleFilter:
    """One stale-axis browse filter and how to drill it.

    `flag`/`param` are the `list` argparse flag and the `list_items`/MCP kwarg.
    `arg` is the value the drill applies (the ISO boundary, or `True` for the
    booleans). `seam` is the `(module, attr)` the read-side resolves *lazily* —
    the selector a sabotage patches. `canonical(db)` is the act-side companion's
    target id set (via the captured real refs). `audit` ties it to `doctor`.
    """

    flag: str
    param: str
    arg: object
    seam: tuple
    canonical: Callable
    audit: _StaleAudit | None


def _stale_before_targets(db):
    """The ids `verify --stale-before` re-captures: the stale window over the
    *hash-bearing* held set (verify can only re-diff a captured baseline hash)."""
    held = list_items(db)
    hash_bearing = [it for it in held if it.content_hash]
    verdicts = custody.latest_events(db)
    return {
        it.id
        for it in _REAL_ITEMS_CHECKED_BEFORE(hash_bearing, verdicts, _STALE_BOUNDARY)
    }


def _stale_classification_targets(db):
    """The ids `classify --stale` refreshes: `stale_classifications` over the held set."""
    return {it.id for it in _REAL_STALE_CLASSIFICATIONS(list_items(db))}


def _stale_summary_targets(db):
    """The ids a `kb --stale` refresh's clusters span: `stale_summary_members` over
    the whole library + the stored summaries."""
    return {
        it.id
        for it in _REAL_STALE_SUMMARY_MEMBERS(
            list_items(db), load_concept_summaries(db)
        )
    }


def _doctor_enrichment_ids(report, db):
    """The stale-classification offenders `doctor` lists (`custody.enrichment.items`)."""
    return {entry["id"] for entry in report["custody"]["enrichment"]["items"]}


def _doctor_summary_member_ids(report, db):
    """The members of the concepts `doctor` flags stale (`custody.summaries.items`) —
    an independent fold (per-concept `is_stale_summary`) from the read-side's
    `stale_summary_members` selector, so it stays correct under that sabotage."""
    stale_slugs = {entry["slug"] for entry in report["custody"]["summaries"]["items"]}
    return {
        it.id
        for it in list_items(db)
        if any(slugify(c) in stale_slugs for c in it.concepts)
    }


_STALE_FILTERS = {
    "stale_before": _StaleFilter(
        "--stale-before", "stale_before", _STALE_BOUNDARY,
        (custody, "items_checked_before"), _stale_before_targets,
        # a moving time window — `doctor` carries no fixed stale-before aggregate
        audit=None,
    ),
    "stale_classification": _StaleFilter(
        "--stale-classification", "stale_classification", True,
        (classify, "stale_classifications"), _stale_classification_targets,
        audit=_StaleAudit(
            ids=_doctor_enrichment_ids,
            count=lambda r: r["custody"]["enrichment"]["stale"],
            health=lambda h: h["enrichment"]["stale"],
        ),
    ),
    "stale_summary": _StaleFilter(
        "--stale-summary", "stale_summary", True,
        (kb_llm, "stale_summary_members"), _stale_summary_targets,
        audit=_StaleAudit(
            ids=_doctor_summary_member_ids,
            # `custody.summaries.stale` counts stale *concepts*, not members — no
            # scalar member-count tie; the member-set tie (`ids`) carries the audit.
            count=None,
            health=None,
        ),
    ),
}


# --- keystone 1: the registry equals H403's named stale-axis flags -----------


def test_stale_filter_registry_equals_the_h403_named_stale_axis_flags():
    """`_STALE_FILTERS` covers *exactly* the `--stale-*` flags H403's
    `_NON_DRILL_FLAGS` names — imported, so a *new* stale-axis flag H403 exempts
    fails this contract until it declares a drill. Disjoint from H403's own
    value/band/flag drills, so the two browse-filter registries jointly partition
    the whole `list` filter surface (no flag is both, none is silently neither)."""
    stale_axis = {flag for flag in _NON_DRILL_FLAGS if flag.startswith("--stale-")}
    assert {f.flag for f in _STALE_FILTERS.values()} == stale_axis

    # every declared stale filter is a real `list` optional (not a typo'd flag)...
    live_list = _subparser_optionals("list")
    assert {f.flag for f in _STALE_FILTERS.values()} <= live_list

    # ...and disjoint from H403's own `list` drill flags — a flag is a value/band/
    # flag drill (H403) xor a stale-axis drill (here), never both.
    h403_list_drills = {
        f.flag for f in _BROWSE_FILTERS.values() if "list" in f.commands
    }
    assert {f.flag for f in _STALE_FILTERS.values()}.isdisjoint(h403_list_drills)

    # the load-bearing sanity (not a tautology): the stale filters are list-only —
    # `search` carries none of them, so the contract rides `list`/`list_scrolls`.
    assert stale_axis.isdisjoint(_subparser_optionals("search"))


def test_stale_filter_registry_covers_the_mcp_list_scrolls_stale_params():
    """The same partition on the MCP twin: the declared stale params are exactly
    the `stale_*` kwargs `list_scrolls` carries, so a *new* stale kwarg on the twin
    fails until classified (the H403 MCP-signature keystone on the stale axis)."""
    params = set(inspect.signature(mcp_server.list_scrolls).parameters)
    declared = {f.param for f in _STALE_FILTERS.values()}
    assert declared <= params
    assert declared == {p for p in params if p.startswith("stale_")}


# --- the drill matrix --------------------------------------------------------


def _cli_flags(param, value):
    """`{param: value}` → the argv flag(s) `_rows` appends to a CLI `list`."""
    flag = next(f.flag for f in _STALE_FILTERS.values() if f.param == param)
    if isinstance(value, bool):
        return [flag] if value else []
    return [flag, value]


def _rows(surface, param, value, capsys):
    """`{id: row}` for one browse surface with one stale filter applied. A large
    `limit` keeps the page cap from truncating the drill set."""
    if surface == "list":
        assert main(["list", "--limit", "100", *_cli_flags(param, value)]) == 0
        data = json.loads(capsys.readouterr().out)
    elif surface == "list_scrolls":
        data = mcp_server.list_scrolls(limit=100, **{param: value})
    else:  # pragma: no cover - guarded by the keystone
        raise AssertionError(f"unknown stale browse surface {surface!r}")
    return {row["id"]: row for row in data}


def _drill_failures(db, capsys):
    """The set of (surface, filter-key) cells whose stale drill disagrees with the
    act-side canonical (or, for the audit cells, with the independent `doctor`
    fold). The matrix asserts this is empty; the sabotage asserts it is exactly the
    cells it broke."""
    report = run_doctor(get_paths())
    health = mcp_server.get_library_health()
    failures = set()
    for key, f in _STALE_FILTERS.items():
        canonical = f.canonical(db)
        for surface in ("list", "list_scrolls"):
            rows = _rows(surface, f.param, f.arg, capsys)
            if set(rows) != canonical:
                failures.add((surface, key))
        if f.audit is not None:
            if f.audit.ids(report, db) != canonical:
                failures.add(("doctor", key))
            if f.audit.count is not None and f.audit.count(report) != len(canonical):
                failures.add(("doctor_count", key))
            if f.audit.health is not None and f.audit.health(health) != len(canonical):
                failures.add(("get_library_health", key))
    return failures


def _assert_fixture_non_vacuous(db):
    """Every stale filter's drill bites — each selects a non-empty *proper* subset
    of the held library, so a mis-derived filter has a wrong set to land on (not
    0 == 0) and the sabotage's one-fresh-row leak has an off-axis row to admit."""
    held = {it.id for it in list_items(db)}
    assert len(held) == 5  # 4 concept members + the plain off-axis item
    for key, f in _STALE_FILTERS.items():
        stale = f.canonical(db)
        assert stale, f"{key}: empty stale set — fixture vacuous"
        assert stale < held, f"{key}: stale set is the whole library — no off-axis row"


def test_every_stale_filter_drills_exactly_its_act_side_targets(scrolls_home, capsys):
    """Over the fixture non-vacuous on every stale axis, each (`--stale-*`, surface)
    drill on `list`/`list_scrolls` returns exactly the rows its act-side companion
    (`verify`/`classify`/`kb --stale`) would act on, and the `--stale-classification`
    aggregate totals `doctor`/`get_library_health`'s `custody.enrichment.stale` —
    the three scattered H85/H185/H189 convergence guards pinned as one contract."""
    main(["init"])
    db = _seed_stale_mix(get_paths())
    capsys.readouterr()

    _assert_fixture_non_vacuous(db)

    assert _drill_failures(db, capsys) == set()


@pytest.mark.parametrize("target_key", list(_STALE_FILTERS))
def test_a_stale_filter_admitting_one_fresh_row_fails_only_that_filter(
    scrolls_home, capsys, monkeypatch, target_key
):
    """The sabotage proves the matrix has teeth and isolates to the *filter*:
    leaking one fresh row into one stale filter's post-SQL selector
    (`items_checked_before` / `stale_classifications` / `stale_summary_members` —
    three distinct seams `list_items` resolves lazily) fails *only* that filter's
    two `list` legs (CLI + MCP twin), never its stale siblings nor the audit ties
    (which read an independent `doctor` fold, so they stay green)."""
    main(["init"])
    db = _seed_stale_mix(get_paths())
    capsys.readouterr()

    assert _drill_failures(db, capsys) == set()  # baseline: clean

    module, attr = _STALE_FILTERS[target_key].seam
    real_fn = getattr(module, attr)
    held = list_items(db)

    def _leaky(*args, **kwargs):
        kept = list(real_fn(*args, **kwargs))
        kept_ids = {it.id for it in kept}
        extra = next((it for it in held if it.id not in kept_ids), None)
        return kept + ([extra] if extra is not None else [])

    monkeypatch.setattr(module, attr, _leaky)

    assert _drill_failures(db, capsys) == {
        ("list", target_key),
        ("list_scrolls", target_key),
    }
