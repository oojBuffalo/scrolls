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


def test_mcp_attention_flag_drives_a_scoped_triage_pass_on_the_weakest_source(
    scrolls_home, monkeypatch, capsys
):
    """*triage* (H204): an agent reads *where* custody loss is and acts *only there*,
    custody-safely. After hold → detect leaves one source drifted, the whole-library
    `get_library_health` read's `attention` flag names that weakest source; the agent
    runs `run_maintenance(source=attention["source"])` to triage just it — never the
    whole library, never re-composing the triage. H201 tied the *whole-library*
    maintenance pass into the flow; this ties in the *scoped* one (H203).

    The two custody points the leg makes visible:

    - **parity** — the scoped pass converges field-for-field with the CLI
      `scrolls maintain --source <that source> --no-recheck` (the per-tool tie is
      pinned in test_mcp.py; here it rides the agent-driven flow); and
    - **custody-safety** — the scoped triage is *non-persisting*: the whole-library
      trend baseline an earlier whole-library pass recorded is left byte-untouched
      and the scoped `delta` is honestly `null` (ADR 0082 — a one-source slice must
      never clobber the single trend baseline). The agent reads the same conclusion
      without disturbing the trend.
    """
    import json

    # hold + detect: one source (arxiv) drifts upstream, web comes back unchanged.
    items, paths = _hold()
    drifted = items[0]
    _detect(items, paths, monkeypatch)

    # the loop's whole-library pass records the single trend baseline it maintains.
    mcp_server.run_maintenance()
    baseline = load_snapshot(snapshot_path(paths))
    assert baseline is not None
    log_len = len(read_log(log_path(paths)))
    assert log_len == 1

    # the agent reads whole-library health and lets `attention` point it at the
    # weakest source — here the one `detect` drifted, unambiguous across the two
    # sources held (web verified `unchanged`, so it carries no actionable loss).
    attention = mcp_server.get_library_health()["attention"]
    assert attention is not None
    assert attention["source"] == drifted.source
    assert attention["reason"] == "1 drifted"
    assert attention["command"] == f"scrolls verify --source {drifted.source}"

    # it triages *only* that source — the scoped MCP pass the flag drives.
    weakest = attention["source"]
    report_mcp = mcp_server.run_maintenance(source=weakest)
    assert report_mcp["source"] == weakest
    assert set(report_mcp["by_source"]) == {weakest}
    # a single-source scope has nothing to flag *across* → attention null (H167 gate),
    # even though that one source is itself drifted — the loss is already the headline.
    assert report_mcp["attention"] is None

    # parity: field-for-field with the CLI scoped pass over the same source/state.
    capsys.readouterr()
    assert main(["maintain", "--source", weakest, "--no-recheck"]) == 0
    report_cli = json.loads(capsys.readouterr().out)
    assert set(report_mcp) == set(report_cli)
    for key in report_cli:
        if key == "recorded_at":
            continue
        assert report_mcp[key] == report_cli[key], f"scoped pass diverged on {key}"

    # custody-safety: the scoped triage writes no whole-library snapshot/log — the
    # trend baseline is byte-untouched and its delta is honestly null (ADR 0082).
    assert report_mcp["delta"] is None
    assert load_snapshot(snapshot_path(paths)) == baseline
    assert len(read_log(log_path(paths))) == log_len


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


# --- the content-identity MCP-surface dogfood leg (H355) ------------------
#
# The content-identity theme (byte-identical holdings under different ids, H325)
# is dogfooded over the CLI read/render/maintain surfaces (H340) and the compiled
# `library/` pages (H351). The surface an *agent* actually drives — the Model
# Context Protocol — had no content-identity dogfood: an agent reading
# `get_library_health`'s `content_duplicates` block (the H325 twin) should be able
# to enumerate *precisely* those redundant holdings via
# `list_scrolls(content_duplicate=True)` (the H338 twin), and after a real prune of
# one copy `get_library_health` should re-read zero groups — the MCP-transport
# analogue of the CLI `doctor → list --content-duplicate → prune → doctor` loop.
#
# The prune itself has **no MCP twin** (the MCP surface is read-only on holdings —
# the same read/act boundary `get_library_health` draws against `scrolls doctor
# --fix`, and the reason this module's flow has no "take it with me" leg): a prune
# is an operator choice the shell makes (`scrolls rm`), never an auto-merge (H325:
# raw is sacred, two faithful copies are a redundancy *fact*, not a defect to
# collapse). So the *reads* run over MCP and the *act* is the CLI `rm` the operator
# chooses — the same composition the H204 attention leg uses (read the MCP signal,
# act on the shell).

# Two captures of the same bytes under two ids — a content-identity duplicate
# (H325), the MCP module's analogue of test_dogfood's `_held_topic_with_a_mirror`.
_MIRROR_BODY = "One survey's bytes, mirrored under two ids."
_MIRROR_HASH = "sha256:byte-identical-mirror"


def _held_topic_with_a_mirror() -> tuple[list[ScrollItem], ScrollItem, ScrollItem]:
    """The held topic plus a byte-identical pair: same `content_hash`/body, two ids.

    The pair is held under two sources/urls (web + blog) so the content group spans
    sources — the whole-library sibling scope (H328) the MCP twins read — while the
    three unique topic scrolls carry their own distinct hashes, so the duplicate
    surfaces single out *only* the redundant pair, never a unique holding.
    """
    mirror_a = _rendered(
        "web", None, "https://example.com/transformer-survey-mirror-a",
        title="Transformer Survey (mirror A)",
        raw_text=_MIRROR_BODY, extracted_text=_MIRROR_BODY,
        content_hash=_MIRROR_HASH, category="survey", domain="machine learning",
        concepts=("Transformer",), tags=("mirror",),
    )
    mirror_b = _rendered(
        "blog", None, "https://example.com/transformer-survey-mirror-b",
        title="Transformer Survey (mirror B)",
        raw_text=_MIRROR_BODY, extracted_text=_MIRROR_BODY,
        content_hash=_MIRROR_HASH, category="survey", domain="machine learning",
        concepts=("Transformer",), tags=("mirror",),
    )
    return _held_topic() + [mirror_a, mirror_b], mirror_a, mirror_b


def _hold_with_mirror() -> tuple[list[ScrollItem], ScrollItem, ScrollItem, object]:
    """*hold* the topic plus a byte-identical mirror pair, then compile the views —
    the `_hold` shape with a content duplicate planted (a finished ingest's
    leftovers, built the way an agent would, no network)."""
    main(["init"])
    paths = get_paths()
    items, mirror_a, mirror_b = _held_topic_with_a_mirror()
    for item in items:
        insert_item(paths.db_path, write_scroll(paths, item))
    mcp_server.compile_library()
    return items, mirror_a, mirror_b, paths


def test_mcp_spot_a_content_duplicate_then_prune_clears_it_over_the_transport(
    scrolls_home, capsys
):
    """*spot the redundancy → enumerate it → prune → it clears* over MCP (H355):
    the content-identity agent loop end to end on the transport an agent drives.

    Hold the same bytes under two ids and the two MCP read twins name the *same*
    pair — `get_library_health`'s `content_duplicates` block (the whole-library
    audit, H325) reports one group of two, and `list_scrolls(content_duplicate=True)`
    (H338) enumerates *exactly* those two held ids (the group's members — the two
    surfaces converge by construction, H332). Then the operator prunes one copy with
    the CLI `scrolls rm` (the chosen act — the MCP surface holds no delete twin; raw
    is sacred, never an auto-merge, H325), and **both MCP reads fall to clean in one
    step**: zero groups and an empty enumeration (H330's unconditional omit-when-clean
    — a count that fell *to* zero is a pruned copy, not a defect repaired). The three
    unique topic scrolls are named by *neither* read throughout, so the loop is a
    genuine narrowing, not a one-pair library.
    """
    import json

    items, mirror_a, mirror_b, _ = _hold_with_mirror()
    capsys.readouterr()  # drain the `init` report so only the `rm` output is read

    # --- spot: the whole-library audit names one group of two -----------------
    dups = mcp_server.get_library_health()["content_duplicates"]
    assert dups["total_groups"] == 1 and dups["total_items"] == 2
    assert dups["groups"] == [
        {"content_hash": _MIRROR_HASH, "ids": sorted([mirror_a.id, mirror_b.id])}
    ]

    # --- enumerate: `list_scrolls(content_duplicate=True)` returns *exactly* the
    #     held members of that group — the audit's `ids`, member-for-member (H338
    #     ≡ H325 by construction); the three unique topic scrolls are excluded.
    redundant = mcp_server.list_scrolls(content_duplicate=True)
    assert sorted(s["id"] for s in redundant) == sorted([mirror_a.id, mirror_b.id])
    assert sorted(s["id"] for s in redundant) == dups["groups"][0]["ids"]
    # the three distinct-hash topic scrolls (items minus the planted mirror pair)
    unique_ids = {item.id for item in items} - {mirror_a.id, mirror_b.id}
    assert len(unique_ids) == 3
    assert unique_ids.isdisjoint({s["id"] for s in redundant})

    # --- prune: a real `scrolls rm` the operator chooses (no MCP delete twin) --
    assert main(["rm", mirror_a.id]) == 0
    rm_out = json.loads(capsys.readouterr().out)
    assert rm_out["removed"] == 1 and rm_out["failed"] == 0

    # --- clears: both MCP reads fall to clean in lockstep ---------------------
    cleared = mcp_server.get_library_health()["content_duplicates"]
    assert cleared["total_groups"] == 0 and cleared["total_items"] == 0
    assert cleared["groups"] == []
    # the surviving copy is now unique — no held sibling, so the enumeration empties
    assert mcp_server.list_scrolls(content_duplicate=True) == []
    # …but the survivor is still held (the prune removed one copy, not the bytes):
    # an unfiltered list still carries mirror B, and `get_scroll` still resolves it.
    survivors = {s["id"] for s in mcp_server.list_scrolls()}
    assert mirror_b.id in survivors and mirror_a.id not in survivors
    assert mcp_server.get_scroll(mirror_b.id)["content_duplicate_ids"] == []


def test_mcp_skipping_the_prune_leaves_the_content_duplicate_flagged(scrolls_home):
    """*the prune is what clears it* (H355, the mutation guard): re-reading both MCP
    twins **without** the `rm` leaves the pair still flagged on each — so the clean
    reads above are driven by the operator's chosen prune, not by the re-read.

    `get_library_health`/`list_scrolls` are read-only custody posture (H325 — no MCP
    surface collapses a content duplicate; only an explicit `scrolls rm` removes a
    held copy), so the redundancy persists across re-reads until the operator acts —
    the H340/H351 prune-drives-the-clear discipline on the MCP transport.
    """
    items, mirror_a, mirror_b, _ = _hold_with_mirror()

    # re-read both twins with no `rm` — the only change from the loop above
    dups = mcp_server.get_library_health()["content_duplicates"]
    assert dups["total_groups"] == 1 and dups["total_items"] == 2
    assert dups["groups"][0]["ids"] == sorted([mirror_a.id, mirror_b.id])

    redundant = mcp_server.list_scrolls(content_duplicate=True)
    assert sorted(s["id"] for s in redundant) == sorted([mirror_a.id, mirror_b.id])

    # and the per-item twin still names the cross-source sibling each way (H328)
    assert mcp_server.get_scroll(mirror_a.id)["content_duplicate_ids"] == [mirror_b.id]
    assert mcp_server.get_scroll(mirror_b.id)["content_duplicate_ids"] == [mirror_a.id]
