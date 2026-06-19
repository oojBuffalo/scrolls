"""The dogfood flow over MCP — the agent-facing sibling of test_dogfood.py (H201).

`tests/test_dogfood.py` pins Scrolls' success metric — *hold a topic → prove
custody → detect loss → take it with me* — as an agent runs it over the **CLI**
(custody-vision capability 8: "If an agent can't run it unattended, it isn't
done."). This module pins the same custody loop as an agent operating purely
over the **Model Context Protocol** would actually drive it — through the MCP
tools, offline against fixtures — now that every leg has an MCP surface:

- **hold** — seed rendered, full-fidelity items the way a finished `ingest`
  leaves them (the same shape test_dogfood/test_roundtrip build), then
  `compile_library()` the views.
- **prove** — `get_library_health()` reads the whole-library custody audit
  (score, fidelity tiers, drift posture), H161.
- **detect** — inject a scripted re-capture at the one network seam
  `verify_scroll` uses (`mcp_server.live_recapture`, exactly as the other MCP
  verify tests do) and `verify_scroll` each held item: one source has drifted.
- **recur** — `run_maintenance()` (H196) records a custody snapshot, a second
  pass appends another, and `get_maintenance_history(trend=True)` (H198) reads
  the recorded trajectory.

The MCP loop has no "take it with me" leg because export/import-bundle is a CLI
concern with no MCP twin; an MCP agent's *recurring* custody work is the
maintenance pass + its trend read instead. The MCP twins ≡ the CLI commands
they wrap is already pinned per-tool in test_mcp.py; this suite ties them into
one agent-driven flow and pins the custody narrative the composition tells.

The sharp custody point the flow makes visible (custody-vision §2.4): detecting
source drift **never lowers the integrity score**, because raw is sacred — the
source moving is a recorded custody *event*, not a loss of what we hold. The
before/after is the *drift posture* (unverified → drifted, recorded), while the
*integrity score* holds at 100 throughout — and the maintenance trend across
two passes that both carry the recorded drift reads `holding`, never
`regressing`, since nothing further degraded between them.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from scrolls import mcp_server
from scrolls.cli import main
from scrolls.doctor import run_doctor
from scrolls.items import ScrollItem, insert_item, make_item_id
from scrolls.maintain import load_snapshot, log_path, read_log, snapshot_path
from scrolls.paths import get_paths
from scrolls.render import write_scroll

TOPIC = "transformer"


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the active library at a temp home so the flow never touches ~/.scrolls."""
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "scrolls-home"))
    return get_paths()


def _rendered(source, source_id, url, **fields) -> ScrollItem:
    """A finished-ingest item: rendered, full-fidelity (raw + extracted + hash),
    with provenance — so every held scroll lands in the ``full`` custody tier
    (matches test_dogfood's `_rendered`)."""
    base = dict(
        id=make_item_id(source, source_id, url),
        source=source,
        source_id=source_id,
        url=url,
        saved_at="2026-06-14T00:00:00+00:00",
        content_hash="sha256:" + (source_id or url)[-8:],
        raw_text=f"<raw capture of {url}>",
        stage="rendered",
        provenance={"adapter": source, "fetched_at": "2026-06-14T00:00:05+00:00"},
    )
    base.update(fields)
    return ScrollItem(**base)


def _held_topic() -> list[ScrollItem]:
    """A small topic held in full: three interlinked transformer scrolls."""
    return [
        _rendered(
            "arxiv", "1706.03762", "https://arxiv.org/abs/1706.03762",
            title="Attention Is All You Need",
            extracted_text="The Transformer uses attention to model sequences.",
            summary="We propose the Transformer.",
            category="paper", domain="machine learning",
            concepts=("Transformer", "Attention"), tags=("cs.CL",),
        ),
        _rendered(
            "web", None, "https://example.com/transformer-explained",
            title="The Transformer, Explained",
            extracted_text="A transformer stacks self-attention and feed-forward layers.",
            category="technique", domain="machine learning",
            concepts=("Transformer",), tags=("explainer",),
        ),
        _rendered(
            "web", None, "https://example.com/scaling-transformers",
            title="Scaling Transformers",
            extracted_text="Larger transformer models keep improving with scale.",
            category="opinion", domain="machine learning",
            concepts=("Transformer",), tags=("scaling",),
        ),
    ]


def _hold() -> tuple[list[ScrollItem], object]:
    """*hold*: render + index the topic through the production `write_scroll`
    path, then compile the views via the MCP `compile_library` tool — a finished
    ingest's leftovers, built the way an agent would (no network)."""
    main(["init"])
    paths = get_paths()
    items = _held_topic()
    for item in items:
        insert_item(paths.db_path, write_scroll(paths, item))
    mcp_server.compile_library()
    return items, paths


def _recapture_drifting(drift_id: str):
    """A network-free re-capture: one held item has drifted upstream (a new
    content hash), every other comes back byte-identical (``unchanged``)."""

    def recapture(item: ScrollItem) -> ScrollItem:
        if item.id == drift_id:
            return replace(item, content_hash="sha256:drifted-upstream")
        return item

    return recapture


def _detect(items, paths, monkeypatch) -> list[dict]:
    """*detect*: verify every held item over MCP through a scripted drift at the
    `verify_scroll` seam; returns the per-item custody events (one drifted)."""
    drift_id = items[0].id
    monkeypatch.setattr(mcp_server, "live_recapture", _recapture_drifting(drift_id))
    return [mcp_server.verify_scroll(item.id) for item in items]


# --- the legs, each proven on its own -------------------------------------


def test_mcp_hold_then_prove_is_a_perfect_full_fidelity_score(scrolls_home):
    """*hold → prove*: a freshly held topic audits clean over MCP — integrity
    score 100, every scroll in the ``full`` tier, and the drift block honest that
    nothing has been re-checked yet (``unverified`` == the whole library, never
    silently ``unchanged``, M2). The MCP twin of test_dogfood's prove leg."""
    items, _ = _hold()

    health = mcp_server.get_library_health()
    assert health["score"] == 100
    assert health["issues"] == 0
    assert health["tiers"] == {"full": len(items), "partial": 0, "reference": 0}
    # M2 honesty: not yet verified is "unverified", never silently "unchanged"
    drift = health["drift"]
    assert drift["checked"] == 0
    assert drift["unverified"] == len(items)
    assert drift["as_of"] is None


def test_mcp_detect_records_drift_without_lowering_the_integrity_score(
    scrolls_home, monkeypatch
):
    """*detect*: `verify_scroll` over each held item re-checks against the live
    source (here a scripted re-capture); one has drifted. The drift is *recorded*
    (a custody event), the original capture is untouched, and — the sharp custody
    point — the integrity score stays 100, because the source moving is not a loss
    of what we hold (custody-vision §2.4). The MCP twin of test_dogfood's detect."""
    items, paths = _hold()
    drifted = items[0]
    before = mcp_server.get_scroll(drifted.id)["content_hash"]

    events = _detect(items, paths, monkeypatch)
    by_status = sorted(e["status"] for e in events)
    assert by_status == ["drifted", "unchanged", "unchanged"]
    drift_event = next(e for e in events if e["status"] == "drifted")
    assert drift_event["observed_hash"] == "sha256:drifted-upstream"

    # the capture itself is never clobbered by a drift verdict (custody §2.4)
    assert mcp_server.get_scroll(drifted.id)["content_hash"] == before == drifted.content_hash

    health = mcp_server.get_library_health()
    # integrity is unmoved: raw is sacred, drift is a separate ledger view
    assert health["score"] == 100
    drift = health["drift"]
    assert drift["checked"] == len(items)
    assert drift["drifted"] == 1
    assert drift["unverified"] == 0
    assert drift["as_of"] is not None
    assert [e["id"] for e in drift["events"]] == [drifted.id]
    assert drift["events"][0]["observed_hash"] == "sha256:drifted-upstream"


def test_mcp_recurring_maintenance_trend_reads_holding(scrolls_home, monkeypatch):
    """*recur*: with the drift already recorded, two `run_maintenance` passes each
    record a custody snapshot, and `get_maintenance_history(trend=True)` reads the
    trajectory as ``holding`` — the score holds at 100 and no *new* drift appeared
    between the two passes, so the recurring custody point (drift recorded, raw
    sacred) reads as steady, never ``regressing``. The MCP recurring tail."""
    items, paths = _hold()
    _detect(items, paths, monkeypatch)

    first = mcp_server.run_maintenance()
    assert first["delta"]["first_run"] is True
    assert first["custody"]["score"] == 100
    assert first["custody"]["drift"]["drifted"] == 1
    assert load_snapshot(snapshot_path(paths)) is not None
    assert len(read_log(log_path(paths))) == 1

    second = mcp_server.run_maintenance()
    assert second["delta"]["first_run"] is False
    assert second["custody"]["score"] == 100
    assert len(read_log(log_path(paths))) == 2

    envelope = mcp_server.get_maintenance_history(trend=True)
    assert len(envelope["runs"]) == 2
    trend = envelope["trend"]
    # the score held (no drop) and no new drift appeared between the two recorded
    # passes — the integrity-first posture is steady, never a regression.
    assert trend["score"] == {"first": 100, "last": 100, "change": 0}
    assert trend["drift_change"] == 0
    assert trend["posture"] == "holding"


# --- the whole flow, unattended, in order ---------------------------------


def test_mcp_dogfood_flow_hold_prove_detect_then_recurring_maintenance(
    scrolls_home, monkeypatch
):
    """The headline proof: an agent runs the whole custody loop over MCP — hold →
    prove → detect → recurring maintenance — offline, and the custody story holds
    at every step. This captures the before/after the dogfood is about: the *drift
    posture* moves from "unverified" to "drifted, recorded", while the *integrity
    score* holds at 100 throughout.

    It also pins the surface-for-surface tie: the MCP prove surface
    (`get_library_health`) reaches the **same custody conclusion** the CLI dogfood's
    `scrolls doctor` does over the identical post-drift state (the per-tool MCP↔CLI
    convergence is already pinned in test_mcp.py; here it carries the composed flow).
    """
    # 1. HOLD a topic: a finished ingest leaves rendered, full-fidelity scrolls.
    items, paths = _hold()

    # 2. PROVE custody: the whole-library audit over MCP scores the held library.
    before = mcp_server.get_library_health()
    assert before["score"] == 100
    assert before["drift"]["unverified"] == len(items)
    assert before["drift"]["checked"] == 0

    # 3. DETECT loss: verify every held item over MCP through a scripted re-capture.
    #    One scroll has drifted; it is recorded, not overwritten.
    drifted = items[0]
    events = _detect(items, paths, monkeypatch)
    assert sum(e["status"] == "drifted" for e in events) == 1
    assert sum(e["status"] == "unchanged" for e in events) == len(items) - 1

    after = mcp_server.get_library_health()
    # integrity unchanged (raw is sacred); the drift posture is what moved
    assert after["score"] == before["score"] == 100
    assert after["drift"]["checked"] == len(items)
    assert after["drift"]["drifted"] == 1
    assert after["drift"]["unverified"] == 0
    assert [e["id"] for e in after["drift"]["events"]] == [drifted.id]

    # surface-for-surface: the MCP prove read IS the CLI dogfood's `doctor` custody
    # block over the same post-drift state — the agent reaches the same conclusion.
    custody = run_doctor(paths)["custody"]
    for key in custody:
        assert after[key] == custody[key], f"MCP health diverged from doctor on {key}"

    # 4. RECUR: the maintenance pass records the snapshot, a second pass appends
    #    another, and the trend reads the trajectory as holding — custody steady.
    mcp_server.run_maintenance()
    mcp_server.run_maintenance()
    envelope = mcp_server.get_maintenance_history(trend=True)
    assert len(envelope["runs"]) == 2
    # every recorded pass holds the score at 100 with the drift recorded — the
    # recurring form of the one-shot custody point.
    assert all(run["snapshot"]["score"] == 100 for run in envelope["runs"])
    assert all(run["snapshot"]["drift"]["drifted"] == 1 for run in envelope["runs"])
    assert envelope["trend"]["score"]["change"] == 0
    assert envelope["trend"]["posture"] == "holding"
