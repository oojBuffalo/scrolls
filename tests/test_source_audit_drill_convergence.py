"""H424 — per-source scoped audit-drill convergence.

The source-axis sibling of H418's whole-library audit drill: every per-source audit
count an agent reads (`doctor --source S`, `get_library_health(source=S)`, and the
whole audit's `by_source[S]` split) must enumerate exactly the rows returned by the
matching `list --source S --<filter>` drill.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

import scrolls.doctor as doctor
import scrolls.mcp_server as mcp_server
from scrolls.cli import main
from scrolls.custody import CustodyEvent, record_events
from scrolls.items import insert_item, list_items
from scrolls.paths import get_paths

from test_audit_drill_convergence import (  # noqa: E402
    _AUDIT_DRILL,
    _NO_DRILL,
    _count_leaves,
    _item,
    _seed_audit_drill_mix,
)


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


@dataclasses.dataclass(frozen=True)
class _SourceAuditDrill:
    """One source-scoped audit count and its row drill.

    H418's top-level drift count uses the ledger word `unchanged`; `by_source`
    exposes the row posture word `verified`. Keep both paths on one registry entry
    so the whole-audit sum and the per-source drill cannot silently compare the
    wrong vocabulary.
    """

    h418_key: str
    top_path: tuple
    by_source_path: tuple
    flags: tuple

    def top_count(self, custody: dict) -> int:
        value = custody
        for key in self.top_path:
            value = value[key]
        return value

    def by_source_count(self, custody: dict) -> int:
        value = custody
        for key in self.by_source_path:
            value = value[key]
        return value


def _source_field_for_h418_key(key: str) -> str:
    return "drift.verified" if key == "drift.unchanged" else key


def _by_source_path_for_h418_key(key: str, path: tuple) -> tuple:
    if key == "drift.unchanged":
        return ("drift", "verified")
    return path


# H424 deliberately reuses H418's audit-drill registry and narrows it to the axes
# the per-source `by_source` decomposition actually carries: fidelity tiers and
# drift postures. The remaining H418 drills are whole-library/source-debt axes whose
# source drill belongs to their own blocks (`enrichment.by_source`) or is skipped
# under source scope (`content_duplicates`).
_SOURCE_AUDIT_DRILL = {
    _source_field_for_h418_key(key): _SourceAuditDrill(
        h418_key=key,
        top_path=drill.path,
        by_source_path=_by_source_path_for_h418_key(key, drill.path),
        flags=drill.flags,
    )
    for key, drill in _AUDIT_DRILL.items()
    if key.startswith("tiers.") or key.startswith("drift.")
}
_WHOLE_LIBRARY_ONLY = {
    "enrichment.stale": "stale-classification source debt lives in `enrichment.by_source`, not `custody.by_source[S]`",
    "content_duplicates.total_items": "content-duplicate groups span sources and are skipped under source scope",
}
_SOURCE_NO_DRILL = {
    "coverage.verified": "coverage numerator over hash-bearing held items; no single list value filter",
    "coverage.total": "coverage denominator over hash-bearing held items; no single list value filter",
}


@dataclasses.dataclass(frozen=True)
class _SourceView:
    surface: str
    source: str
    custody: dict
    by_source: bool = False


def _seed_source_audit_drill_mix(db):
    """Start from H418's fixture, then widen source coverage.

    H418 makes every *whole-library* drill non-vacuous. H424 needs source-scoped
    legs too, so add a few rows/events ensuring every source axis value is present
    in at least two sources: partial/reference fidelity, and unchanged/drifted/
    rotted/error drift postures cannot hide behind a single-source accident.
    """
    _seed_audit_drill_mix(db)
    extras = [
        _item(
            "arxiv:partial2", "Beta partial arxiv", source="arxiv",
            url="https://arxiv.org/abs/partial2", extracted_text="partial arxiv",
            stage="rendered",
        ),
        _item("web:ref2", "Beta web pointer", source="web", url="https://example.com/ref2"),
        _item(
            "web:drifted2", "Beta web drifted", source="web",
            url="https://example.com/drifted2", extracted_text="web drifted",
            raw_text="<raw>web drifted</raw>", content_hash="sha256:web-drifted",
            stage="rendered",
        ),
        _item(
            "web:rotted2", "Beta web rotted", source="web",
            url="https://example.com/rotted2", extracted_text="web rotted",
            raw_text="<raw>web rotted</raw>", content_hash="sha256:web-rotted",
            stage="rendered",
        ),
        _item(
            "arxiv:unchanged2", "Beta arxiv unchanged", source="arxiv",
            url="https://arxiv.org/abs/unchanged2", extracted_text="arxiv unchanged",
            raw_text="<raw>arxiv unchanged</raw>", content_hash="sha256:arxiv-clean",
            stage="rendered",
        ),
        _item(
            "crossref:error2", "Beta crossref error", source="crossref",
            url="https://doi.org/10.0000/error2", extracted_text="crossref error",
            raw_text="<raw>crossref error</raw>", content_hash="sha256:crossref-error",
            stage="rendered",
        ),
    ]
    for item in extras:
        insert_item(db, item)
    record_events(db, [
        CustodyEvent("web:drifted2", "2026-06-15T00:00:00+00:00", "drifted",
                     "sha256:web-drifted", "sha256:web-drifted-now", None),
        CustodyEvent("web:rotted2", "2026-06-15T00:00:00+00:00", "rotted",
                     "sha256:web-rotted", None, "HTTP Error 410"),
        CustodyEvent("arxiv:unchanged2", "2026-06-15T00:00:00+00:00", "unchanged",
                     "sha256:arxiv-clean", "sha256:arxiv-clean", None),
        CustodyEvent("crossref:error2", "2026-06-15T00:00:00+00:00", "error",
                     "sha256:crossref-error", None, "timeout"),
    ])


# --- keystones ----------------------------------------------------------------


def test_source_audit_drill_registry_is_h418_restricted_to_by_source_axes(scrolls_home):
    """H424 reuses H418's drill registry rather than hand-copying it.

    The source-scoped audit drill consists exactly of H418's tier/drift axes; H418's
    stale-enrichment/content-duplicate drills are explicitly named whole-library-only
    for this contract. A future H418 drill fails here until it is declared source-
    scoped or named as a different-axis exemption.
    """
    assert {d.h418_key for d in _SOURCE_AUDIT_DRILL.values()} | set(_WHOLE_LIBRARY_ONLY) == set(_AUDIT_DRILL)
    assert set(_SOURCE_AUDIT_DRILL).isdisjoint(_WHOLE_LIBRARY_ONLY)
    assert _WHOLE_LIBRARY_ONLY.keys() <= _NO_DRILL.keys() | _AUDIT_DRILL.keys()
    assert set(_SOURCE_AUDIT_DRILL) == {
        "tiers.full", "tiers.partial", "tiers.reference",
        "drift.verified", "drift.unverified", "drift.drifted", "drift.rotted", "drift.error",
    }


def test_by_source_count_leaves_are_partitioned_by_source_drill_registry(scrolls_home):
    """The live `custody.by_source[S]` shape is exactly the source drill axes plus
    named non-drill coverage counters. If a new per-source count appears, this test
    fails until the H424 drill contract classifies it.
    """
    main(["init"])
    _seed_source_audit_drill_mix(get_paths().db_path)
    source_entry = doctor.run_doctor(get_paths())["custody"]["by_source"]["web"]
    live = _count_leaves(source_entry)
    drill = set(_SOURCE_AUDIT_DRILL)
    no_drill = set(_SOURCE_NO_DRILL)
    assert drill.isdisjoint(no_drill)
    assert drill | no_drill == live, (
        f"unclassified per-source counts: {live - drill - no_drill}; "
        f"stale registry entries: {(drill | no_drill) - live}"
    )


# --- read helpers -------------------------------------------------------------


def _list_count(source: str, flags: tuple, capsys) -> int:
    assert main(["list", "--limit", "1000", "--source", source, *flags]) == 0
    return len(json.loads(capsys.readouterr().out))


def _doctor_cli_custody(source: str, capsys) -> dict:
    assert main(["doctor", "--source", source]) == 0
    return json.loads(capsys.readouterr().out)["custody"]


def _source_views(source: str, whole_custody: dict, capsys) -> list[_SourceView]:
    cli_custody = _doctor_cli_custody(source, capsys)
    health = mcp_server.get_library_health(source=source)
    return [
        _SourceView("doctor.by_source", source, whole_custody["by_source"][source], True),
        _SourceView("doctor --source", source, cli_custody),
        _SourceView("doctor --source.by_source", source, cli_custody["by_source"][source], True),
        _SourceView("get_library_health(source)", source, health),
        _SourceView("get_library_health(source).by_source", source, health["by_source"][source], True),
    ]


def _source_drill_failures(capsys) -> set[tuple[str, str, str]]:
    whole_custody = doctor.run_doctor(get_paths())["custody"]
    failures: set[tuple[str, str, str]] = set()
    for source in sorted(whole_custody["by_source"]):
        for field, drill in _SOURCE_AUDIT_DRILL.items():
            rows = _list_count(source, drill.flags, capsys)
            for view in _source_views(source, whole_custody, capsys):
                observed = (
                    drill.by_source_count(view.custody)
                    if view.by_source else drill.top_count(view.custody)
                )
                if observed != rows:
                    failures.add((view.surface, source, field))
    return failures


def _sum_to_whole_failures() -> set[str]:
    custody = doctor.run_doctor(get_paths())["custody"]
    failures = set()
    for field, drill in _SOURCE_AUDIT_DRILL.items():
        total = sum(drill.by_source_count(entry) for entry in custody["by_source"].values())
        if total != drill.top_count(custody):
            failures.add(field)
    return failures


def _assert_source_fixture_non_vacuous():
    custody = doctor.run_doctor(get_paths())["custody"]
    sources = sorted(custody["by_source"])
    assert sources == ["arxiv", "crossref", "web", "wikipedia"]
    assert len(list_items(get_paths().db_path)) == 13
    for field, drill in _SOURCE_AUDIT_DRILL.items():
        nonzero = [source for source in sources if drill.by_source_count(custody["by_source"][source])]
        assert len(nonzero) >= 2, f"{field}: only {nonzero} nonzero — source leg vacuous"
        assert sum(drill.by_source_count(custody["by_source"][source]) for source in sources) == drill.top_count(custody)


# --- matrix -------------------------------------------------------------------


def test_every_per_source_audit_count_drills_exactly_the_source_scoped_rows(
    scrolls_home, capsys
):
    """For every held source and every source-scoped tier/drift count, the audit
    count equals exactly `list --source S --<filter>` on the CLI scoped audit, MCP
    scoped audit, and the whole audit's `by_source[S]` split. Summing the source
    splits reproduces the whole-library tier/drift counts.
    """
    main(["init"])
    _seed_source_audit_drill_mix(get_paths().db_path)
    capsys.readouterr()

    _assert_source_fixture_non_vacuous()
    assert _source_drill_failures(capsys) == set()
    assert _sum_to_whole_failures() == set()


def test_a_per_source_by_source_tier_misattribution_fails_only_that_source_field(
    scrolls_home, capsys, monkeypatch
):
    """Sabotage: inflate only `web`'s by-source `full` tier. The source-drill
    matrix catches exactly that source/field on the by-source views while the scoped
    top-level counts and other sources/fields stay green.
    """
    main(["init"])
    _seed_source_audit_drill_mix(get_paths().db_path)
    capsys.readouterr()
    assert _source_drill_failures(capsys) == set()

    real_counts = doctor.custody_counts_by_source

    def _misattribute_web_full(items, latest):
        by_source = real_counts(items, latest)
        if "web" in by_source:
            by_source["web"]["tiers"]["full"] += 1
        return by_source

    monkeypatch.setattr(doctor, "custody_counts_by_source", _misattribute_web_full)

    assert _source_drill_failures(capsys) == {
        ("doctor.by_source", "web", "tiers.full"),
        ("doctor --source.by_source", "web", "tiers.full"),
        ("get_library_health(source).by_source", "web", "tiers.full"),
    }
