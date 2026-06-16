"""The dogfood proof: one agent-runnable flow that exercises M1–M4 end to end.

The custody vision (`docs/custody-vision.md`, capability 8) names dogfood
workflows as *the* success metric: "End-to-end, agent-runnable flows: *hold a
topic* (ingest → render → audit), *prove custody* (doctor → custody score),
*detect loss* (recheck → drift report), *take it with me* (export bundle →
reimport). If an agent can't run it unattended, it isn't done." The MVP slice
M5 (`docs/product/mvp.md`) is this proof, tying together the earlier slices:
refresh-safe regeneration (M1), the completeness contract (M2), context budgets
(M3), and the shareable custody bundle (M4).

This module *is* that flow, executed against fixtures with no network. The flow
has two genuinely live edges — *capture* (`scrolls ingest`) and *recheck*
(`scrolls verify`) — and this proof substitutes a deterministic stand-in for
each so the *composition and custody bookkeeping* are reproducible offline:

- **hold** seeds rendered, full-fidelity items the way a finished `ingest`
  leaves them (the same shape `test_roundtrip.py` builds), then compiles the KB.
- **detect** injects a scripted re-capture at the one network seam
  `scrolls verify` uses (`cli.live_recapture`, exactly as `test_verify_cli.py`
  does), so a known drift is observed without a live fetch.

The live edges themselves are covered by the adapter and `verify` tests; here we
prove they *compose* into the custody narrative the vision promises. The sharp
custody point the flow makes visible: detecting source drift **never lowers the
integrity score**, because raw is sacred — the source moving is a recorded
custody *event*, not a loss of what we hold (custody-vision §2.4). The
before/after the dogfood captures is the *drift posture* (unverified → checked),
not the integrity score, which holds at 100 throughout.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

import scrolls.cli as cli
from scrolls.cli import main
from scrolls.db import init_db
from scrolls.items import (
    ScrollItem,
    get_item,
    insert_item,
    item_to_dict,
    list_items,
    make_item_id,
)
from scrolls.paths import get_paths
from scrolls.render import write_scroll

TOPIC = "transformer"


def _rendered(source, source_id, url, **fields) -> ScrollItem:
    """A finished-ingest item: rendered, full-fidelity (raw + extracted + hash),
    with provenance — so every held scroll lands in the ``full`` custody tier."""
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
            category="paper",
            domain="machine learning",
            concepts=("Transformer", "Attention"),
            tags=("cs.CL",),
        ),
        _rendered(
            "web", None, "https://example.com/transformer-explained",
            title="The Transformer, Explained",
            extracted_text="A transformer stacks self-attention and feed-forward "
            "layers.",
            category="technique",
            domain="machine learning",
            concepts=("Transformer",),
            tags=("explainer",),
        ),
        _rendered(
            "web", None, "https://example.com/scaling-transformers",
            title="Scaling Transformers",
            extracted_text="Larger transformer models keep improving with scale.",
            category="opinion",
            domain="machine learning",
            concepts=("Transformer",),
            tags=("scaling",),
        ),
    ]


def _build(items: list[ScrollItem]) -> None:
    """Render + index a library at the active home, then compile the KB.

    Renders through the same `write_scroll` a real ingest uses (M1's refresh-safe
    regeneration runs underneath), so the held library is built by the production
    code path, not hand-laid files.
    """
    paths = get_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    init_db(paths.db_path)
    for item in items:
        rendered = write_scroll(paths, item)
        insert_item(paths.db_path, rendered)
    assert main(["kb"]) == 0


def _recapture_drifting(drift_id: str):
    """A network-free re-capture: one held item has drifted upstream (a new
    content hash), every other comes back byte-identical (``unchanged``)."""

    def recapture(item: ScrollItem) -> ScrollItem:
        if item.id == drift_id:
            return replace(item, content_hash="sha256:drifted-upstream")
        return item

    return recapture


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Point the active library at a named home under tmp_path; returns a factory
    so one test can build a held library and a fresh import target side by side."""

    def use(name):
        monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / name))
        return get_paths()

    return use


# --- the four legs, each proven on its own --------------------------------


def test_hold_then_prove_custody_is_a_perfect_full_fidelity_score(home, capsys):
    """*hold → prove*: a freshly held topic audits clean — integrity score 100,
    every scroll in the ``full`` tier, and the drift block honest that nothing
    has been re-checked yet (``unverified`` == the whole library, not ``clean``)."""
    home("held")
    items = _held_topic()
    _build(items)
    capsys.readouterr()  # drain the kb report

    assert main(["doctor"]) == 0
    report = json.loads(capsys.readouterr().out)["custody"]
    assert report["score"] == 100
    assert report["issues"] == 0
    assert report["tiers"] == {"full": len(items), "partial": 0, "reference": 0}
    # M2 honesty: not yet verified is "unknown", never silently "unchanged"
    drift = report["drift"]
    assert drift["checked"] == 0
    assert drift["unverified"] == len(items)
    assert drift["as_of"] is None


def test_detect_loss_records_drift_without_lowering_the_integrity_score(
    home, monkeypatch, capsys
):
    """*detect*: `verify --all` re-checks every held item; one has drifted at the
    source. The drift is *recorded* (a custody event), the original capture is
    untouched, and — the sharp custody point — the integrity score stays 100,
    because the source moving is not a loss of what we hold."""
    home("held")
    items = _held_topic()
    _build(items)
    drifted = items[0]
    before = get_item(get_paths().db_path, drifted.id)
    capsys.readouterr()

    monkeypatch.setattr(cli, "live_recapture", _recapture_drifting(drifted.id))
    assert main(["verify", "--all"]) == 0
    verify_out = json.loads(capsys.readouterr().out)
    assert verify_out["checked"] == len(items)
    assert verify_out["drifted"] == 1
    assert verify_out["unchanged"] == len(items) - 1

    # the capture itself is never clobbered by a drift verdict (custody §2.4)
    assert get_item(get_paths().db_path, drifted.id) == before

    assert main(["doctor"]) == 0
    report = json.loads(capsys.readouterr().out)["custody"]
    # integrity is unmoved: raw is sacred, drift is a separate ledger view
    assert report["score"] == 100
    drift = report["drift"]
    assert drift["checked"] == len(items)
    assert drift["drifted"] == 1
    assert drift["unverified"] == 0
    assert drift["as_of"] is not None
    assert [e["id"] for e in drift["events"]] == [drifted.id]
    assert drift["events"][0]["observed_hash"] == "sha256:drifted-upstream"


def test_take_it_with_me_bundle_round_trips_into_a_fresh_library(home, capsys):
    """*take it with me*: a scoped custody bundle exports the held topic and
    re-imports losslessly into an empty library — the items recovered are the
    canonical records, byte-for-byte (ADR 0099/0103)."""
    src = home("held")
    items = _held_topic()
    _build(items)
    src_rows = {i.id: item_to_dict(i) for i in list_items(src.db_path)}
    capsys.readouterr()

    assert main(["export", "bundle", TOPIC]) == 0
    bundle_text = capsys.readouterr().out
    bundle_path = src.root.parent / "transformer-briefing.md"
    bundle_path.write_text(bundle_text, encoding="utf-8")

    dst = home("fresh")
    assert main(["init"]) == 0
    capsys.readouterr()
    assert main(["import", "bundle", str(bundle_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["imported"] == len(items)

    dst_rows = {i.id: item_to_dict(i) for i in list_items(dst.db_path)}
    assert dst_rows == src_rows  # the whole held topic travelled losslessly

    # re-import is idempotent and never overwrites (custody-safe restore)
    assert main(["import", "bundle", str(bundle_path)]) == 0
    again = json.loads(capsys.readouterr().out)
    assert again["imported"] == 0 and again["skipped"] == len(items)


# --- the whole flow, unattended, in order ---------------------------------


def test_dogfood_flow_hold_prove_detect_take(home, monkeypatch, capsys):
    """The headline proof: an agent runs hold → prove → detect → take it with me
    end to end, offline, and the custody story holds at every step.

    This captures the before/after the dogfood is about: the *drift posture*
    moves from "unverified" to "drifted, recorded", while the *integrity score*
    holds at 100 throughout — custody intact even as the source rots.
    """
    # 1. HOLD a topic: a finished ingest leaves rendered, full-fidelity scrolls.
    src = home("library")
    items = _held_topic()
    _build(items)
    capsys.readouterr()

    # 2. PROVE custody: doctor scores the held library.
    assert main(["doctor"]) == 0
    before = json.loads(capsys.readouterr().out)["custody"]
    assert before["score"] == 100
    assert before["drift"]["unverified"] == len(items)
    assert before["drift"]["checked"] == 0

    # 3. DETECT loss: verify re-checks against the live source (here, a scripted
    #    re-capture). One scroll has drifted; it is recorded, not overwritten.
    drifted = items[0]
    monkeypatch.setattr(cli, "live_recapture", _recapture_drifting(drifted.id))
    assert main(["verify", "--all"]) == 0
    verify_out = json.loads(capsys.readouterr().out)
    assert verify_out["drifted"] == 1 and verify_out["unchanged"] == len(items) - 1

    assert main(["doctor"]) == 0
    after = json.loads(capsys.readouterr().out)["custody"]
    # integrity unchanged (raw is sacred); the drift posture is what moved
    assert after["score"] == before["score"] == 100
    assert after["drift"]["checked"] == len(items)
    assert after["drift"]["drifted"] == 1
    assert after["drift"]["unverified"] == 0
    assert [e["id"] for e in after["drift"]["events"]] == [drifted.id]

    # 4. TAKE IT WITH ME: export a scoped bundle, re-import into a fresh library.
    src_rows = {i.id: item_to_dict(i) for i in list_items(src.db_path)}
    assert main(["export", "bundle", TOPIC]) == 0
    bundle_text = capsys.readouterr().out
    bundle_path = src.root.parent / "briefing.md"
    bundle_path.write_text(bundle_text, encoding="utf-8")

    dst = home("elsewhere")
    assert main(["init"]) == 0
    capsys.readouterr()
    assert main(["import", "bundle", str(bundle_path)]) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["imported"] == len(items)

    # the topic survived the journey to a fresh library, byte-for-byte
    assert {i.id: item_to_dict(i) for i in list_items(dst.db_path)} == src_rows

    # and the fresh library proves its own custody from the imported records
    assert main(["doctor", "--fix"]) == 0
    capsys.readouterr()
    assert main(["doctor"]) == 0
    rebuilt = json.loads(capsys.readouterr().out)["custody"]
    assert rebuilt["score"] == 100
    assert rebuilt["tiers"]["full"] == len(items)
