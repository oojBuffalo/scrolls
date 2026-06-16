"""The custody-convergence cross-surface invariant (roadmap H50).

The custody picture an agent reads is now surfaced in six places — `scrolls
status` (H38), the shareable bundle briefing (H45), the `scrolls context` bundle
(H47), `scrolls facets fidelity`/`drift` (H48), the `scrolls graph` stats block
(H52), and `doctor`'s `custody` block — each *claimed* to converge for a given
scope because they all derive from one
custody tally (`custody.custody_counts`/`custody_headline` over `get_fidelity` +
`drift_posture`/`latest_events`). That claim is pinned per-surface in scattered
tests; this module pins it *once*, the way `tests/test_completeness.py` pins the
anti-fabrication contract across every read surface.

Over one seeded fidelity/drift fixture it asserts that every surface reports the
*same* fidelity-tier counts and the *same* drift-posture counts for the whole-
library scope, with the one documented vocabulary mapping: the posture
``verified`` is the ledger status ``unchanged`` (`doctor`/`status` keep the
ledger word; the headlines and `facets drift` read the posture word). It also
pins the *enumeration* drilled from those counts — `scrolls list --drift
<posture>` (roadmap H54) returns rows that total each posture's canonical count,
so the browse filter and the aggregate can never disagree. A future change that
desyncs any one surface fails here, in one obvious place.

This module also pins the **per-item** counterpart of that scope-level invariant
(roadmap H59). After H56/H58/H61 the per-item `drift` posture rides every
browse/landing/inspect surface — `list` rows, `search` hits, `related` hits,
`graph` nodes, the shareable bundle briefing, and `show`/`get_scroll` — each
claimed to read the same `custody.drift_posture` over `latest_events`. The
per-item section asserts that over one seeded fixture a given item reads the
*same* `drift` on every surface that carries it, and that each
whole-library-enumerating surface's per-item posture counts total `facets
drift`'s count for that posture — tying the per-item axis back to the aggregate
the scope-level invariant pins.
"""

import json
import re

import pytest

from scrolls.cli import main
from scrolls.custody import (
    CustodyEvent,
    custody_counts,
    custody_headline,
    drift_posture,
    latest_events,
    record_events,
)
from scrolls.doctor import run_doctor
from scrolls.facets import compute_facets
from scrolls.items import ScrollItem, insert_item, list_items
from scrolls.paths import get_paths


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


def _seed_mixed_custody(db):
    """Four held scrolls spanning the fidelity tiers and drift postures.

    Every title carries "topic" so a `topic` query matches the whole library
    (the bundle/context surfaces are query-scoped). Fidelity: two `full`
    (raw_text + content_hash, captured), one `partial` (extracted text only,
    no hash), one `reference` (a detected pointer, no content). Drift: one
    re-checked unchanged (→ `verified`), one drifted, two never re-checked
    (→ `unverified`).
    """
    insert_item(db, _item(
        "web:full1", "Topic full one",
        extracted_text="topic one body", raw_text="<raw>topic one</raw>",
        content_hash="sha256:full1",
    ))
    insert_item(db, _item(
        "web:full2", "Topic full two",
        extracted_text="topic two body", raw_text="<raw>topic two</raw>",
        content_hash="sha256:full2",
    ))
    insert_item(db, _item(
        "web:partial", "Topic partial",
        extracted_text="topic partial body",  # no hash/raw → partial
    ))
    insert_item(db, _item(
        "web:ref", "Topic reference pointer", stage="detected",  # no content → reference
    ))
    record_events(db, [
        CustodyEvent("web:full1", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:full1", "sha256:full1", None),
        CustodyEvent("web:full2", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:full2", "sha256:changed", None),
        # web:partial, web:ref left unverified
    ])


def _posture_from_ledger_counts(drift):
    """Normalise a `doctor`/`status` drift block to the posture vocabulary.

    The only vocabulary difference across the surfaces: the ledger-status word
    ``unchanged`` is the posture ``verified``; everything else shares its name.
    """
    return {
        "verified": drift["unchanged"],
        "unverified": drift["unverified"],
        "drifted": drift["drifted"],
        "rotted": drift["rotted"],
        "error": drift["error"],
    }


def _nonzero(counts):
    return {key: value for key, value in counts.items() if value}


def _facet_map(entries):
    return {entry["value"]: entry["count"] for entry in entries}


def test_every_custody_surface_converges_on_one_picture(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    _seed_mixed_custody(db)
    capsys.readouterr()

    # The canonical picture: the shared tally over the whole library + ledger.
    items = list_items(db)
    verdicts = latest_events(db)
    canonical = custody_counts(items, verdicts)
    # sanity: the fixture is the non-trivial mix the surfaces must all reproduce
    assert canonical["tiers"] == {"full": 2, "partial": 1, "reference": 1}
    assert _nonzero(canonical["drift"]) == {"verified": 1, "unverified": 2, "drifted": 1}

    # 1. doctor — the custody aggregate every other surface is measured against
    custody = run_doctor(get_paths())["custody"]
    assert custody["tiers"] == canonical["tiers"]
    assert _posture_from_ledger_counts(custody["drift"]) == canonical["drift"]

    # 2. status — the headline block is custody_snapshot(run_doctor), so it
    #    carries doctor's tiers/drift verbatim
    assert main(["status"]) == 0
    status_custody = json.loads(capsys.readouterr().out)["custody"]
    assert status_custody["tiers"] == canonical["tiers"]
    assert _posture_from_ledger_counts(status_custody["drift"]) == canonical["drift"]

    # 3. facets — the browse aggregates of the same two axes
    fidelity = _facet_map(compute_facets(db, field="fidelity")["facets"]["fidelity"])
    drift = _facet_map(compute_facets(db, field="drift")["facets"]["drift"])
    assert fidelity == _nonzero(canonical["tiers"])
    assert drift == _nonzero(canonical["drift"])

    # 4. the bundle briefing + context bundle headlines — the *rendered* line is
    #    the shared custody_headline over the whole (uncapped, uncollapsed) scope
    headline = custody_headline(items, verdicts)
    assert "fidelity full 2, partial 1, reference 1" in headline  # canonical, rendered
    assert "drift verified 1, unverified 2, drifted 1" in headline

    assert main(["export", "bundle", "topic"]) == 0
    bundle_out = capsys.readouterr().out
    assert headline in bundle_out

    assert main(["context", "topic"]) == 0
    context_out = capsys.readouterr().out
    assert headline in context_out

    # 5. the graph stats block — the JSON custody counts (posture words, like
    #    custody_counts) over the whole stats.items scope (roadmap H52)
    assert main(["graph", "--all"]) == 0
    graph_custody = json.loads(capsys.readouterr().out)["stats"]["custody"]
    assert graph_custody["tiers"] == canonical["tiers"]
    assert graph_custody["drift"] == canonical["drift"]

    # 6. `list --drift <posture>` — the row enumeration drilled from the count.
    #    The rows for each posture *total* that posture's canonical count, so the
    #    browse filter and the aggregate can never disagree (roadmap H54).
    for posture, count in canonical["drift"].items():
        assert main(["list", "--drift", posture]) == 0
        rows = json.loads(capsys.readouterr().out)
        assert len(rows) == count, f"list --drift {posture}: {len(rows)} != {count}"


def test_convergence_holds_under_a_scope_filter(scrolls_home, capsys):
    # the surfaces converge for *any* shared scope, not only the whole library:
    # the same `--source` filter narrows doctor-free surfaces identically
    main(["init"])
    db = get_paths().db_path
    _seed_mixed_custody(db)
    # add an out-of-scope item so a source filter actually excludes something
    insert_item(db, _item("arxiv:1", "Topic arxiv paper", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:arxiv"))
    capsys.readouterr()

    # canonical picture for the web-only scope
    web_items = [item for item in list_items(db) if item.source == "web"]
    verdicts = latest_events(db)
    canonical = custody_counts(web_items, verdicts)

    # facets drift/fidelity scoped to source=web agree with the scoped tally
    fidelity = _facet_map(
        compute_facets(db, field="fidelity", source="web")["facets"]["fidelity"]
    )
    drift = _facet_map(compute_facets(db, field="drift", source="web")["facets"]["drift"])
    assert fidelity == _nonzero(canonical["tiers"])
    assert drift == _nonzero(canonical["drift"])

    # the context bundle scoped to source=web carries the same scoped headline
    assert main(["context", "topic", "--source", "web"]) == 0
    assert custody_headline(web_items, verdicts) in capsys.readouterr().out


# --- the per-item invariant (roadmap H59) ------------------------------------


def _seed_linked_drift_postures(db):
    """Four ring-linked scrolls, one per drift posture, all matching "topic".

    Every scroll links to the next (`web:1`→`web:2`→`web:3`→`web:4`→`web:1`), so
    every item participates in a graph edge and is a `graph` node; every title
    and a shared `topic` tag make all four match a `topic` search and relate to
    any anchor — so each whole-library surface enumerates all four, and
    `related <anchor>` reaches every other item. The four postures: `web:1`
    re-checked unchanged (→`verified`), `web:2` drifted, `web:3` rotted, `web:4`
    never re-checked (→`unverified`).
    """
    ring = {1: 2, 2: 3, 3: 4, 4: 1}
    for index, nxt in ring.items():
        insert_item(db, _item(
            f"web:{index}", f"Topic scroll {index}",
            extracted_text=f"topic body {index}",
            raw_text=f"<raw>topic {index}</raw>", content_hash=f"sha256:{index}",
            tags=("topic",), links=(f"https://example.com/web:{nxt}",),
        ))
    record_events(db, [
        CustodyEvent("web:1", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:1", "sha256:1", None),
        CustodyEvent("web:2", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:2", "sha256:x", None),
        CustodyEvent("web:3", "2026-06-14T00:00:00+00:00", "rotted",
                     "sha256:3", None, "HTTP Error 404"),
        # web:4 left unverified
    ])


def _bundle_postures(text):
    """Map item id → drift posture parsed from a bundle briefing's per-scroll lines.

    Each entry heads with ``## N. <title> (`<id>`)`` and carries a
    ``- custody `<posture>` …`` line (roadmap H42); pair each id with the posture
    that follows it, so the briefing's per-scroll posture can be compared against
    the JSON surfaces.
    """
    postures = {}
    current = None
    for line in text.splitlines():
        heading = re.match(r"^## \d+\. .*\(`([^`]+)`\)\s*$", line)
        if heading:
            current = heading.group(1)
            continue
        custody = re.match(r"^- custody `(\w+)`", line)
        if custody and current is not None:
            postures[current] = custody.group(1)
            current = None
    return postures


def test_every_surface_agrees_on_an_items_drift_posture(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    _seed_linked_drift_postures(db)
    capsys.readouterr()

    # the canonical per-item posture: drift_posture over each item's latest verdict
    verdicts = latest_events(db)
    canonical = {
        item.id: drift_posture(verdicts.get(item.id)) for item in list_items(db)
    }
    # sanity: the fixture spans four distinct postures
    assert set(canonical.values()) == {"verified", "drifted", "rotted", "unverified"}

    # list rows (H58)
    assert main(["list"]) == 0
    list_drift = {r["id"]: r["drift"] for r in json.loads(capsys.readouterr().out)}
    # search hits (H58) — every title carries "topic"
    assert main(["search", "topic"]) == 0
    search_drift = {h["id"]: h["drift"] for h in json.loads(capsys.readouterr().out)}
    # graph nodes (H56) — every item is a node via the ring of links
    assert main(["graph"]) == 0
    graph_drift = {
        n["id"]: n["drift"] for n in json.loads(capsys.readouterr().out)["nodes"]
    }
    # bundle briefing (H42) — every match is in scope and carries a custody line
    assert main(["export", "bundle", "topic"]) == 0
    bundle_drift = _bundle_postures(capsys.readouterr().out)
    # related hits (H56) from web:1 — reaches every other item (link + shared tag)
    assert main(["related", "web:1"]) == 0
    related_drift = {h["id"]: h["drift"] for h in json.loads(capsys.readouterr().out)}
    # show — the inspect surface (H61), one item at a time
    show_drift = {}
    for item_id in canonical:
        assert main(["show", item_id]) == 0
        show_drift[item_id] = json.loads(capsys.readouterr().out)["drift"]

    # every whole-library surface reports the canonical posture for every item
    assert list_drift == canonical
    assert search_drift == canonical
    assert graph_drift == canonical
    assert bundle_drift == canonical
    assert show_drift == canonical
    # related carries every item *except its anchor*, each at the canonical posture
    assert related_drift == {
        item_id: posture
        for item_id, posture in canonical.items()
        if item_id != "web:1"
    }


def test_per_item_drift_totals_the_facets_count(scrolls_home, capsys):
    # tie the per-item axis back to the aggregate: each whole-library surface's
    # per-item posture counts equal `facets drift`'s count for that posture, so a
    # change that desyncs the per-item field from the aggregate fails here.
    main(["init"])
    db = get_paths().db_path
    _seed_linked_drift_postures(db)
    capsys.readouterr()

    main(["facets", "drift"])
    facet_counts = _facet_map(json.loads(capsys.readouterr().out)["facets"]["drift"])

    def _posture_counts(rows):
        counts = {}
        for posture in (row["drift"] for row in rows):
            counts[posture] = counts.get(posture, 0) + 1
        return counts

    assert main(["list"]) == 0
    assert _posture_counts(json.loads(capsys.readouterr().out)) == facet_counts
    assert main(["search", "topic"]) == 0
    assert _posture_counts(json.loads(capsys.readouterr().out)) == facet_counts
    assert main(["graph"]) == 0
    assert _posture_counts(json.loads(capsys.readouterr().out)["nodes"]) == facet_counts
