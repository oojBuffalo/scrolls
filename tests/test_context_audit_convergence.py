"""H421 — the context-briefing ↔ live-audit convergence contract.

The twenty-eighth **contract-consolidation** cell and the *agent-read* sibling of
H415's portable bundle-briefing convergence. H415 pins that every custody fact in a
shareable `export bundle` briefing equals the live `doctor` audit for the same
whole-library scope; this pins the same facts on the model-facing `scrolls context`
briefing.

The claim: at `--budget full`, every context custody briefing line with a
whole-scope audit counterpart reads the same fact as `run_doctor` over the same
scope:

  - `_Custody:_`      fidelity holdings ≡ `custody.tiers`
  - `_Attention:_`                   ≡ `weakest_source(custody.by_source)`
  - `_At-risk work:_`                ≡ `custody.works.most_at_risk`/`at_risk`
  - `_Conflicts:_`                   ≡ `custody.conflicts.items`
  - `_Archive:_`                     ≡ `custody.archive.mismatched`
  - `_Duplicates:_`                  ≡ `custody.content_duplicates.total_{groups,items}`
  - `_Posture:_`                     ≡ `custody.posture.verdict`
  - `_Refresh:_`                     ≡ `custody.enrichment/summaries.by_source`

This deliberately reuses H415's `_AUDIT_BASIS` registry and briefing-side parsers:
the Markdown fact shape is shared, only the surface being rendered changes from
`build_bundle` to `build_context`. The completeness keystone holds the live
`context.build_context` helper-call surface to that registry plus named non-audit
context briefing lines (`_Coverage:_`, `_Strength:_`, `_Budget:_`, `_Fidelity:_`, and
`_By source:_`).
"""

import ast
import inspect
import re

import pytest

import scrolls.context as context
from scrolls.cli import main
from scrolls.context import build_context
from scrolls.doctor import run_doctor
from scrolls.items import list_items
from scrolls.paths import get_paths

# H401's composite fixture / Markdown line parser, and H415's audit-basis registry +
# fact extractors. Cross-importing keeps this contract a thin rebinding of the bundle
# audit contract: a new H415 audit-basis line automatically becomes a context line to
# prove here.
from test_bundle_audit_convergence import (  # noqa: E402
    _AUDIT_BASIS,
    _NO_AUDIT_BASIS,
    _convergence_failures,
)
from test_bundle_format_parity import _BRIEFING_LINES, _md_marker, _seed_every_briefing_line  # noqa: E402


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


_CONTEXT_AUDIT_FNS = {
    "headline": "custody_headline",
    "attention": "render_custody_attention",
    "at_risk": "render_at_risk_works",
    "conflicts": "render_custody_conflicts",
    "archive": "render_archive_integrity",
    "duplicates": "render_content_duplicates",
    "posture": "render_posture",
    "refresh": "render_custody_refresh",
}

_CONTEXT_NO_AUDIT_BASIS = {
    "coverage": dict(
        fn="_coverage_line",
        reason="the G2 scope/count honesty line; its truncation arithmetic is pinned by H420",
    ),
    "strength": dict(
        fn="render_strength_headline",
        reason=_NO_AUDIT_BASIS["strength"],
    ),
    "budget": dict(
        fn="_budget_line",
        reason="the depth-honesty line for non-full budgets; H421 drives --budget full",
    ),
    "fidelity_index": dict(
        fn="render_fidelity_holdings",
        reason="the index-budget holdings-only line; the full-budget _Custody:_ headline carries its audit tie",
    ),
    "by_source": dict(
        fn="render_custody_by_source",
        reason=_NO_AUDIT_BASIS["by_source"],
    ),
}

# Module-level helper calls in `build_context` that are data gathering, branch gates,
# per-entry rendering, or section builders rather than one-line custody briefing facts.
_CONTEXT_STRUCTURAL = {
    "search_items",                         # query+scope read
    "_collapse_by_work",                    # ADR 0101 display fold
    "get_item",                             # item hydrate
    "_scope_note",                          # title scope note
    "count_matches",                        # Coverage denominator
    "tally_strength",                       # Strength data fold
    "_tier_at_least",                       # budget gate
    "latest_events",                        # ledger read
    "custody_counts_by_source",             # by-source/attention data fold
    "latest_conflict_events",               # conflict-ledger data fold
    "stale_classification_counts_by_source", # Refresh data fold
    "stale_summary_counts_by_source",       # Refresh data fold
    "load_concept_summaries",               # summary-refresh data read
    "custody_counts",                       # Fidelity-index data fold
    "_work_note",                           # per-Best-Matches annotation
    "_meta_line",                           # per-excerpt metadata
    "_provenance_tags",                     # per-excerpt provenance tags
    "_excerpt",                             # per-excerpt body
    "_connected_lines",                     # connected-scrolls section
}


def _module_fn_calls(fn) -> set[str]:
    tree = ast.parse(inspect.getsource(fn))
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and callable(getattr(context, node.func.id, None))
    }


def _context_doc(db_path) -> str:
    # Decisive choice: drive full budget and a limit at the whole-library count. The
    # H401 fixture puts "database" in every title, so this is a whole-library context
    # scope; `limit == len(list_items)` avoids G2 truncation while still exercising
    # same-work collapse (the catalog can fold reps, but the audit lines must not).
    return build_context(
        db_path,
        "database",
        limit=len(list_items(db_path)),
        budget="full",
    )


def test_context_audit_basis_partitions_the_context_briefing_surface():
    """A context briefing-line emitter must declare either an H415 audit tie or a named
    non-audit reason. The AST keystone makes a future context custody line fail until
    classified instead of silently bypassing the live-audit convergence contract.
    """
    calls = _module_fn_calls(context.build_context)
    audit_fns = set(_CONTEXT_AUDIT_FNS.values())
    no_audit_fns = {entry["fn"] for entry in _CONTEXT_NO_AUDIT_BASIS.values()}
    declared = audit_fns | no_audit_fns

    assert set(_CONTEXT_AUDIT_FNS) == set(_AUDIT_BASIS)
    assert set(_CONTEXT_NO_AUDIT_BASIS) == {
        "coverage", "strength", "budget", "fidelity_index", "by_source",
    }
    # Context carries every H415 query briefing line except the concept-summary line;
    # the latter is bundle-only and has no context renderer.
    assert set(_CONTEXT_AUDIT_FNS) | {"strength", "by_source"} == set(_BRIEFING_LINES) - {"concept"}

    assert calls - _CONTEXT_STRUCTURAL == declared
    assert _CONTEXT_STRUCTURAL == calls - declared
    assert all(callable(getattr(context, name, None)) for name in _CONTEXT_STRUCTURAL)


def test_every_context_briefing_line_equals_the_live_audit(scrolls_home):
    """Over the H401/H415 composite fixture rendered as a whole-library-scope
    `scrolls context --budget full`, every H415 audit-basis line equals the live
    `run_doctor` custody projection for that same scope.
    """
    main(["init"])
    db = get_paths().db_path
    _seed_every_briefing_line(db)

    md_doc = _context_doc(db)
    custody = run_doctor(get_paths())["custody"]

    # Whole-library scope: every fixture title carries the query token, and the limit
    # is the held-row count. The context catalog may collapse same-work reps, but the
    # audit/custody briefing lines must describe all matched rows.
    headline = _md_marker("Custody:")(md_doc)
    scope_n = int(re.search(r"Custody: (\d+) scroll", headline).group(1))
    assert scope_n == len(list_items(db)) > 0
    assert _md_marker("Coverage:")(md_doc) == f"Coverage: all {scope_n} matching scrolls."

    for key, line in _AUDIT_BASIS.items():
        assert line["brief"](md_doc) is not None, f"{key} did not render in context"

    # Non-vacuity on the audit side: every tied axis carries a real signal in the
    # composite fixture, so the equality is not a None/default coincidence.
    assert custody["posture"]["verdict"] == "at_risk"
    assert _AUDIT_BASIS["headline"]["audit"](custody).keys() >= {"full", "reference"}
    assert _AUDIT_BASIS["attention"]["audit"](custody) is not None
    assert _AUDIT_BASIS["at_risk"]["audit"](custody)[1] >= 1
    assert _AUDIT_BASIS["conflicts"]["audit"](custody) >= 1
    assert _AUDIT_BASIS["archive"]["audit"](custody) >= 1
    assert _AUDIT_BASIS["duplicates"]["audit"](custody) == (1, 2)
    assert all(_AUDIT_BASIS["refresh"]["audit"](custody))

    assert _convergence_failures(md_doc, custody) == set()


def test_a_context_line_folding_a_tampered_count_fails_only_that_line(
    scrolls_home, monkeypatch
):
    """Sabotage: a context briefing line re-derives a count differently from the audit.

    Monkeypatch the context module's imported renderer (a distinct binding from the
    doctor/audit fold and from the bundle test) to invent duplicate counts. The matrix
    should fail exactly the `_Duplicates:_` leg.
    """
    main(["init"])
    db = get_paths().db_path
    _seed_every_briefing_line(db)
    custody = run_doctor(get_paths())["custody"]
    assert _convergence_failures(_context_doc(db), custody) == set()

    monkeypatch.setattr(
        context,
        "render_content_duplicates",
        lambda items, db_path=None: [
            "_Duplicates: 9 group(s) of byte-identical content (99 item(s))._", ""
        ],
    )

    assert _convergence_failures(_context_doc(db), custody) == {"duplicates"}
