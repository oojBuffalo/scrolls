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
import re
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
from scrolls.maintain import (
    custody_snapshot,
    load_snapshot,
    log_path,
    read_log,
    snapshot_path,
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


# --- the scoped-triage leg (H206) -----------------------------------------


def test_attention_flag_drives_a_scoped_maintenance_triage_on_the_weakest_source(
    home, monkeypatch, capsys
):
    """*triage* (H206): the shell sibling of the MCP attention→scoped-pass flow
    (H204). After hold → detect leaves one source drifted, an agent reads
    `scrolls status` — whose `attention` flag names the single weakest source —
    and runs `scrolls maintain --source <that source>` to triage *only* it, never
    the whole library, never re-deriving the triage. The per-command pieces are
    pinned elsewhere (H139 status `attention`, H165 `maintain --source`, H182 the
    scoped suggestion); this ties them into one end-to-end shell sequence in the
    CLI dogfood home, the symmetric twin of H204's MCP flow — so the
    triage-where-the-loss-is point is pinned over *both* surfaces.

    The two custody points the leg makes visible, the CLI twins of H204's:

    - **triage where the loss is** — `status`'s `attention` names exactly the
      source `detect` drifted (arxiv; the two web scrolls verified `unchanged`, so
      that source carries no actionable loss), with the exact `scrolls verify
      --source <S>` recheck command — and the scoped `maintain --source <S>`
      collapses to that one source (singleton `by_source`, `attention` null: a
      single source has nothing to flag *across*), its `custody` ≡ `doctor
      --source <S>`'s distilled snapshot; and
    - **custody-safety** — the scoped triage is *non-persisting*: the whole-library
      trend baseline the dogfood's earlier whole-library `maintain` recorded is
      left byte-untouched and the scoped `delta` is honestly `null` (ADR 0082 — a
      one-source slice must never clobber the single trend baseline).
    """
    # hold + detect: arxiv drifts upstream, the two web scrolls come back unchanged.
    src = home("library")
    items = _held_topic()
    _build(items)
    drifted = items[0]
    assert drifted.source == "arxiv"
    monkeypatch.setattr(cli, "live_recapture", _recapture_drifting(drifted.id))
    assert main(["verify", "--all"]) == 0
    capsys.readouterr()  # drain the kb + verify output

    # the dogfood's whole-library maintenance leg records the single trend baseline.
    assert main(["maintain", "--no-recheck"]) == 0
    whole = json.loads(capsys.readouterr().out)
    # non-vacuous: ≥2 sources held, exactly one (arxiv) carries the loss — so the
    # scoped singleton/null below is a genuine narrowing, not a one-source library.
    assert set(whole["by_source"]) == {"arxiv", "web"}
    assert whole["attention"]["source"] == "arxiv"
    baseline = load_snapshot(snapshot_path(src))
    assert baseline is not None
    log_len = len(read_log(log_path(src)))
    assert log_len == 1

    # the agent reads `scrolls status`; its `attention` flag names the weakest
    # source and the exact recheck command — the bridge from "where" to the act.
    assert main(["status"]) == 0
    attention = json.loads(capsys.readouterr().out)["attention"]
    assert attention is not None
    assert attention["source"] == drifted.source
    assert attention["reason"] == "1 drifted"
    assert attention["command"] == f"scrolls verify --source {drifted.source}"
    # status and the whole-library maintain pass name one source by construction
    # (both distil `weakest_source` from the same audit) — the cross-surface tie.
    assert attention == whole["attention"]

    # it triages *only* that source — the scoped CLI pass the flag drives.
    weakest = attention["source"]
    assert main(["maintain", "--source", weakest, "--no-recheck"]) == 0
    scoped = json.loads(capsys.readouterr().out)
    assert scoped["source"] == weakest
    assert set(scoped["by_source"]) == {weakest}  # collapsed to the one source
    # a single-source scope has nothing to flag *across* → attention null (the
    # documented H139/H119 gate), even though that one source is itself drifted.
    assert scoped["attention"] is None

    # parity: the scoped pass's custody ≡ `doctor --source <S>`'s distilled snapshot
    # (the scoped audit both surfaces run over the same unchanged ledger).
    assert main(["doctor", "--source", weakest]) == 0
    doctor_report = json.loads(capsys.readouterr().out)
    assert scoped["custody"] == custody_snapshot(doctor_report)

    # custody-safety: the scoped triage writes no whole-library snapshot/log — the
    # trend baseline is byte-untouched and its delta is honestly null (ADR 0082).
    assert scoped["delta"] is None
    assert load_snapshot(snapshot_path(src)) == baseline
    assert len(read_log(log_path(src))) == log_len


# --- the refresh-act leg (H210) -------------------------------------------


def _held_topic_with_refresh_debt() -> list[ScrollItem]:
    """The held topic, seeded with both refresh-debt axes for the refresh-act leg.

    Two enrichment-freshness axes carry stale debt over *different* source sets, so
    the `_Refresh:_` pointer can't pass by conflating them and each scoped act clears
    exactly its own axis:

    - **enrichment** (a stale *classification*), confined to one source: the `web`
      explainer's rules category was produced under a *superseded* ruleset, so a
      re-classify would no longer reproduce it — the enrichment axis names ``{web}``.
      Its "guide" title matches the rules engine's ``tutorial`` pattern, so the
      refresh act re-derives a category and restamps the live ruleset (the debt
      actually clears, rather than a content-less item falling to an untouched
      ``unmatched``).
    - **summary** (a stale *concept summary*), spanning two sources: the
      ``Transformer`` cluster (an arxiv paper + two web scrolls) has a stored summary
      whose membership fingerprint no longer matches its live members — the summary
      axis names ``{arxiv, web}`` (the H171 multi-source attribution: a cluster is
      stale for *every* source it spans, so it counts toward each).
    """
    return [
        # arxiv paper — a `Transformer`-cluster member. Its category is
        # platform-curated (not rules-derived), so it carries no enrichment debt:
        # the enrichment axis stays web-only.
        _rendered(
            "arxiv", "1706.03762", "https://arxiv.org/abs/1706.03762",
            title="Attention Is All You Need",
            extracted_text="The Transformer uses attention to model sequences.",
            summary="We propose the Transformer.",
            category="paper",
            domain="machine learning",
            concepts=("Transformer",),
            tags=("cs.CL",),
        ),
        # web explainer — rules-classified under a SUPERSEDED ruleset (the
        # enrichment debt, confined to `web`). The "guide" title matches the rules
        # engine's tutorial pattern, so `classify --stale --source web` re-derives
        # the category and restamps the live ruleset. Also a cluster member.
        _rendered(
            "web", None, "https://example.com/transformer-guide",
            title="A Guide to the Transformer",
            extracted_text="A transformer stacks self-attention and feed-forward "
            "layers.",
            category="tutorial",
            domain="machine learning",
            concepts=("Transformer",),
            tags=("explainer",),
            provenance={
                "adapter": "web",
                "fetched_at": "2026-06-14T00:00:05+00:00",
                "classified_by": "rules-v1",
                "classified_basis": "title-pattern",
                "classified_ruleset": "deadbeef0000",  # superseded → stale
            },
        ),
        # a second web scroll, so the `Transformer` cluster spans arxiv + web with
        # ≥ MIN_MEMBERS members and the summary axis names two sources.
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


def _store_stale_summary(db_path, slug, display) -> None:
    """Save a concept summary whose membership fingerprint is already out of date,
    so `doctor` flags the cluster stale and `kb --stale` regenerates it — the
    summary-axis seed the convergence suite scripts behind, brought into the dogfood
    home (the `cli.live_recapture`-style deterministic stand-in for a prior synthesis
    that the library has since outgrown)."""
    from scrolls.kb import ConceptSummary, save_concept_summary

    save_concept_summary(db_path, ConceptSummary(
        slug=slug, display=display, summary="An older synthesis of the cluster.",
        members_hash="stale-old-fingerprint", engine="kb-llm-v1",
        model="claude-opus-4-8", generated_at="2026-06-14T00:00:00+00:00"))


_REFRESH_CLASS = re.compile(r"classifications stale in ([^—]+?) — refresh with")
_REFRESH_SUMM = re.compile(r"summaries stale in ([^—]+?) — refresh with")


def _refresh_sources(briefing: str, pattern) -> list[str]:
    """The sorted source names a briefing's `_Refresh:_` clause lists, or [] when the
    clause is absent — the readable pointer read back the way an agent skims it (the
    refresh-axis counterpart of the H206 leg's `attention` read)."""
    match = pattern.search(briefing)
    if match is None:
        return []
    return sorted(re.findall(r"`([^`]+)`", match.group(1)))


def test_refresh_pointer_drives_scoped_enrichment_then_summary_refresh(
    home, monkeypatch, capsys
):
    """*refresh* (H210): the enrichment/summary sibling of H206's drift-act triage.
    After hold leaves one source's classification stale and a two-source concept
    summary stale, an agent reads the `scrolls context` briefing — whose `_Refresh:_`
    line names exactly which sources to refresh on each axis (≡ doctor's
    `custody.enrichment.by_source`/`custody.summaries.by_source`) — and runs the
    scoped `classify --stale --source <S>` / `kb --stale --source <S>` it names. Each
    act clears *exactly* its own axis/source while the untouched axis persists, and
    the refresh act itself *is* the mutation (no scripted state change) — the
    refresh-act half of the dogfood's self-healing custody story.

    The per-command pieces are pinned elsewhere (H178 the `_Refresh:_` line, H154/H172
    the scoped acts, H183 the suggestion↔debt-map tie); this ties them into one
    end-to-end shell sequence in the CLI dogfood home, the refresh-axis twin of H206's
    drift triage — so the act-where-the-debt-is point is pinned on *both* the drift
    and the enrichment/summary axes.

    The two custody points the leg makes visible, the refresh-axis twins of H206's:

    - **act where the debt is** — the `_Refresh:_` line names exactly the sources
      doctor flags (enrichment ``{web}``, summary ``{arxiv, web}`` — different sets, so
      the two axes can't be conflated), and running the enrichment act drops *only*
      the enrichment clause while the summary clause stays, then running the summary
      act clears it too (honest absence: the whole line vanishes); and
    - **the H171 attribution** — a two-source stale cluster is refreshed under *any*
      one of its sources, so `kb --stale --source web` clears both `arxiv` and `web`
      from the summary map in lockstep, even though the act named only `web`.
    """
    # the summary refresh's one live edge (the model call) scripted offline at the
    # same seam the convergence/kb suites use — the `cli.live_recapture` of the
    # summary axis, so the refresh act runs network-free.
    import scrolls.kb_llm as kb_llm
    monkeypatch.setattr(
        kb_llm, "_anthropic_complete",
        lambda system, user, model: json.dumps(
            {"summary": "How the Transformer shows up across the held scrolls."}),
    )

    # hold + accrue both refresh-debt axes.
    home("library")
    items = _held_topic_with_refresh_debt()
    _build(items)
    _store_stale_summary(get_paths().db_path, "transformer", "Transformer")
    capsys.readouterr()  # drain the kb report

    # doctor's per-source debt maps — the canonical sources the pointer must name.
    assert main(["doctor"]) == 0
    custody = json.loads(capsys.readouterr().out)["custody"]
    enr_map = custody["enrichment"]["by_source"]
    summ_map = custody["summaries"]["by_source"]
    # non-vacuous: both axes carry debt, over DIFFERENT source sets.
    assert enr_map == {"web": 1}
    assert summ_map == {"arxiv": 1, "web": 1}

    # the agent reads `scrolls context <topic>`; its `_Refresh:_` line names exactly
    # those sources per axis — the bridge from "what's stale where" to the act.
    assert main(["context", TOPIC]) == 0
    briefing = capsys.readouterr().out
    assert _refresh_sources(briefing, _REFRESH_CLASS) == sorted(enr_map)  # ["web"]
    assert _refresh_sources(briefing, _REFRESH_SUMM) == sorted(summ_map)  # arxiv,web

    # ACT 1 — the enrichment axis: run exactly the scoped command the line named.
    assert main(["classify", "--stale", "--source", "web"]) == 0
    enrichment_run = json.loads(capsys.readouterr().out)
    assert enrichment_run["classified"] == 1  # the one stale web class'n, restamped

    # re-read: the enrichment clause is GONE, the summary clause UNCHANGED — the act
    # cleared its own axis and nothing else (≡ doctor: enrichment map now empty).
    assert main(["context", TOPIC]) == 0
    after_enrichment = capsys.readouterr().out
    assert _refresh_sources(after_enrichment, _REFRESH_CLASS) == []
    assert _refresh_sources(after_enrichment, _REFRESH_SUMM) == ["arxiv", "web"]
    assert main(["doctor"]) == 0
    mid = json.loads(capsys.readouterr().out)["custody"]
    assert mid["enrichment"]["by_source"] == {}
    assert mid["summaries"]["by_source"] == summ_map  # untouched

    # ACT 2 — the summary axis: run the scoped `kb --stale --source web` the line
    # named. web participates in the two-source cluster, so its refresh clears the
    # whole cluster — the H171 attribution: arxiv and web drop in lockstep.
    assert main(["kb", "--stale", "--source", "web"]) == 0
    summary_run = json.loads(capsys.readouterr().out)
    assert summary_run["generated"] == 1  # the one stale cluster, re-synthesized

    # re-read: the summary clause is GONE too — the whole `_Refresh:_` line vanishes
    # (honest absence: no source carries refresh debt on either axis).
    assert main(["context", TOPIC]) == 0
    assert "_Refresh:" not in capsys.readouterr().out

    # doctor: both maps empty — the debt fully cleared by exactly the acts the
    # pointer named, the refresh-act self-healing the drift triage (H206) mirrors.
    assert main(["doctor"]) == 0
    final = json.loads(capsys.readouterr().out)["custody"]
    assert final["enrichment"]["by_source"] == {}
    assert final["summaries"]["by_source"] == {}


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
