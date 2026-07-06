"""H425 — compiled group-page custody-marker convergence.

The custody-axis sibling of H419's rendered classification-provenance leg: the
compiled ``library/`` concept/tag rows already render ``kb._custody_marker`` as
``· <fidelity> · <drift> · <when>``. This contract pins that human-readable row
marker to the same per-item custody projection the JSON inspect/browse surfaces
carry: ``get_fidelity(item)`` plus ``drift_posture`` / ``last_checked`` over the
latest verify-ledger verdict.

The fixture deliberately shares one concept and one tag across every item, so the
MCP ``get_concept_page`` and ``get_tag_page`` rendered surfaces enumerate the same
whole-library set that ``list`` / ``show`` / ``get_scroll`` expose as JSON. It also
puts H419 classification markers after the custody clause (and a duplicate-content
clause on one pair) so the parser proves it reads the original H89/H93 custody
clause correctly even after newer row markers trail it.
"""

import json
import re

import pytest

import scrolls.cli as cli
import scrolls.kb as kb
import scrolls.mcp_server as mcp_server
from scrolls.classify import RULESET_FINGERPRINT
from scrolls.custody import CustodyEvent, drift_posture, last_checked, latest_events, record_events
from scrolls.generated import generated_body
from scrolls.items import ScrollItem, get_fidelity, insert_item, list_items
from scrolls.paths import get_paths

# H425's rendered page legs should stay in lockstep with the H419 rendered
# classification-provenance legs: the same two compiled group pages carry both
# trailing row markers.
from test_provenance_convergence import _PROVENANCE_SURFACES  # noqa: E402

CONCEPT = "Custody Markers"
TAG = "custody-demo"

_TIERS = ("full", "partial", "reference")
_POSTURES = ("verified", "drifted", "unverified")

_FIXTURE_IDS = tuple(
    f"web:{tier}-{posture}" for tier in _TIERS for posture in _POSTURES
)
_FIXTURE_TITLES = {
    item_id: "Topic " + item_id.removeprefix("web:").replace("-", " ")
    for item_id in _FIXTURE_IDS
}


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


def _item(item_id: str, **overrides) -> ScrollItem:
    tier = item_id.split(":", 1)[1].split("-", 1)[0]
    base = dict(
        id=item_id,
        source="web",
        url=f"https://example.com/{item_id}",
        saved_at="2026-07-05T00:00:00+00:00",
        title=_FIXTURE_TITLES[item_id],
        category="research",
        concepts=(CONCEPT,),
        tags=(TAG,),
        markdown_path=f"scrolls/{item_id.replace(':', '/')}.md",
        stage="rendered",
        provenance={
            "classified_by": "rules-v1",
            "classified_basis": "source-domain",
            "classified_ruleset": RULESET_FINGERPRINT,
        },
    )
    if tier == "full":
        # Two full rows share a hash so one page row carries the H333
        # ``also held as`` clause between the custody and classification clauses.
        shared = item_id in {"web:full-verified", "web:full-drifted"}
        base.update(
            raw_text=f"<html>{item_id}</html>",
            extracted_text=f"body for {item_id}",
            content_hash="sha256:full-shared" if shared else f"sha256:{item_id}",
        )
    elif tier == "partial":
        base.update(summary=f"summary for {item_id}")
    # reference rows intentionally carry no body/summary/hash.
    base.update(overrides)
    return ScrollItem(**base)  # type: ignore[arg-type]


def _seed_custody_marker_mix(db):
    """Seed every fidelity tier crossed with verified/drifted/never-checked.

    All rows share one concept and tag so both rendered page tools enumerate the
    complete matrix. Every row also has a classification provenance marker, proving
    the custody parser stops before H419's trailing classification clause.
    """
    for item_id in _FIXTURE_IDS:
        insert_item(db, _item(item_id))

    events = []
    for tier in _TIERS:
        verified = f"web:{tier}-verified"
        drifted = f"web:{tier}-drifted"
        events.append(CustodyEvent(
            verified,
            f"2026-07-05T0{_TIERS.index(tier)}:00:00+00:00",
            "unchanged",
            None,
            None,
            None,
        ))
        events.append(CustodyEvent(
            drifted,
            f"2026-07-05T1{_TIERS.index(tier)}:00:00+00:00",
            "drifted",
            None,
            f"sha256:changed-{tier}",
            None,
        ))
    record_events(db, events)


# --- canonical custody projection -------------------------------------------


def _canonical_custody(db):
    """``{id: (fidelity, drift, last_checked)}`` from the model + ledger.

    This is the same source of truth every JSON per-item surface is expected to
    carry and every rendered page marker should faithfully display.
    """
    verdicts = latest_events(db)
    return {
        item.id: (
            get_fidelity(item),
            drift_posture(verdicts.get(item.id)),
            last_checked(verdicts.get(item.id)),
        )
        for item in list_items(db)
    }


# --- per-surface readers -----------------------------------------------------


def _row_tuple(row):
    return (row["fidelity"], row["drift"], row["last_checked"])


def _read_list(capsys):
    assert cli.main(["list"]) == 0
    rows = json.loads(capsys.readouterr().out)
    return {row["id"]: _row_tuple(row) for row in rows}


def _read_show(capsys):
    out = {}
    for item_id in _FIXTURE_IDS:
        assert cli.main(["show", item_id]) == 0
        out[item_id] = _row_tuple(json.loads(capsys.readouterr().out))
    return out


def _read_get_scroll(capsys):
    return {
        item_id: _row_tuple(mcp_server.get_scroll(item_id))
        for item_id in _FIXTURE_IDS
    }


def _custody_markers_from_page(text):
    """``{id: (fidelity, drift, last_checked)}`` parsed from group-page rows.

    The custody clause comes first in ``kb._row_markers`` but may be followed by
    H333 content-duplicate markers and H419 classification markers. Parse the
    custody triple and ignore any later row-marker clauses.
    """
    title_to_id = {title: item_id for item_id, title in _FIXTURE_TITLES.items()}
    body = generated_body(text) or text
    out = {}
    pattern = re.compile(
        r"^\s*- \[([^\]]+)\]\([^)]+\).* · "
        r"(full|partial|reference) · "
        r"(verified|unverified|drifted|rotted|error) · "
        r"(?:checked (\S+)|never checked)"
        r"(?: · also held as .*?)?"
        r"(?: · classified .*)?\s*$"
    )
    for line in body.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        item_id = title_to_id.get(match.group(1))
        if item_id is None:
            continue
        out[item_id] = (match.group(2), match.group(3), match.group(4))
    return out


def _read_get_concept_page(capsys):
    return _custody_markers_from_page(mcp_server.get_concept_page(CONCEPT))


def _read_get_tag_page(capsys):
    return _custody_markers_from_page(mcp_server.get_tag_page(TAG))


_CUSTODY_MARKER_SURFACES = {
    "list": ("per_item", _read_list),
    "show": ("per_item", _read_show),
    "get_scroll": ("per_item", _read_get_scroll),
    "get_concept_page": ("rendered", _read_get_concept_page),
    "get_tag_page": ("rendered", _read_get_tag_page),
}


def _custody_marker_failures(db, capsys):
    canonical = _canonical_custody(db)
    failures = set()
    for key, (_kind, read) in _CUSTODY_MARKER_SURFACES.items():
        reading = read(capsys)
        expected = {item_id: canonical[item_id] for item_id in reading}
        if set(reading) != set(canonical) or reading != expected:
            failures.add(key)
    return failures


# --- keystone: the rendered legs are the H419 rendered group-page legs --------


def test_custody_marker_surface_registry_reuses_the_h419_rendered_pages():
    for key, (kind, _read) in _CUSTODY_MARKER_SURFACES.items():
        assert kind in {"per_item", "rendered"}, key

    per_item = {key for key, (kind, _read) in _CUSTODY_MARKER_SURFACES.items() if kind == "per_item"}
    rendered = {key for key, (kind, _read) in _CUSTODY_MARKER_SURFACES.items() if kind == "rendered"}
    h419_rendered = {
        key for key, (kind, _read) in _PROVENANCE_SURFACES.items() if kind == "rendered"
    }

    assert per_item == {"list", "show", "get_scroll"}
    assert rendered == h419_rendered == {"get_concept_page", "get_tag_page"}


# --- matrix guard ------------------------------------------------------------


def test_group_pages_read_the_canonical_per_item_custody_marker(scrolls_home, capsys):
    cli.main(["init"])
    db = get_paths().db_path
    _seed_custody_marker_mix(db)
    assert cli.main(["kb"]) == 0
    capsys.readouterr()

    canonical = _canonical_custody(db)
    assert set(canonical) == set(_FIXTURE_IDS)
    assert {value[0] for value in canonical.values()} == set(_TIERS)
    assert {value[1] for value in canonical.values()} == set(_POSTURES)
    assert sum(1 for _fid, _drift, checked in canonical.values() if checked is None) == len(_TIERS)
    assert any(checked is not None for _fid, _drift, checked in canonical.values())

    assert _custody_marker_failures(db, capsys) == set()


def test_page_marker_rendering_wrong_drift_fails_only_the_page_legs(
    scrolls_home, capsys, monkeypatch
):
    cli.main(["init"])
    db = get_paths().db_path
    _seed_custody_marker_mix(db)
    assert cli.main(["kb"]) == 0
    capsys.readouterr()

    assert _custody_marker_failures(db, capsys) == set()

    real = kb._custody_marker

    def _wrong(item, verdicts):
        marker = real(item, verdicts)
        if item.id == "web:full-drifted":
            return marker.replace(" · drifted · ", " · verified · ")
        return marker

    monkeypatch.setattr(kb, "_custody_marker", _wrong)
    assert cli.main(["kb"]) == 0
    capsys.readouterr()

    assert _custody_marker_failures(db, capsys) == {"get_concept_page", "get_tag_page"}
