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
from datetime import datetime

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
from scrolls.items_export import dump_items_export
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


# --- the adopt-a-peer's-better-capture leg (H284) -------------------------

PEER_HASH = "sha256:peer-recapture"


def _peer_recapture(original: ScrollItem) -> ScrollItem:
    """A peer's diverging re-capture of the *same* source (same id) — a fuller body
    and a fresh content hash. Imported, it conflicts with our held copy (custody
    §2.4: a peer disagreeing is a surfaced event, not an overwrite); adopted via
    `--accept-incoming`, it replaces the held copy while the prior is archived
    (recoverable via `scrolls archive show`). It stays full-fidelity (raw +
    extracted + hash + provenance), so adoption is a flip of *which* faithful copy
    we hold — never a loss of fidelity, so the integrity score is never lowered."""
    return replace(
        original,
        content_hash=PEER_HASH,
        raw_text=f"<peer's fuller capture of {original.url}>",
        extracted_text=original.extracted_text
        + " A worked example walks through the attention computation.",
    )


def _read_jsonl_lines(text: str) -> list[dict]:
    """Parse the JSONL an agent pipes between commands (`archive show`/`export`)."""
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_adopt_a_peers_better_capture_flips_the_held_copy_and_clears_the_conflict(
    home, capsys, tmp_path
):
    """*adopt* (H284): the accept-incoming sibling of the drift/refresh self-healing
    legs, the one custody move no other dogfood exercises end to end — *take a peer's
    better capture while keeping the prior recoverable*.

    A peer re-captured one of the sources we hold and got different bytes (a fuller
    body). They share a bundle. We import it (the divergence is **surfaced and
    recorded**, our held copy untouched — custody §2.4), review it via
    `doctor`/`history`, then **adopt** it with `import bundle --accept-incoming` (the
    held copy is replaced, its prior archived, the conflict cleared), and finally
    **restore** the prior with `archive show <id> | import items --accept-incoming`.

    The two custody points the leg makes visible, the adopt-axis twins of the drift
    leg's "drift never lowers the score":

    - **the conflict aggregate moves 0 → 1 → 0** — `doctor`'s `custody.conflicts`
      counts the open import conflict after the plain import, and the adoption (a
      `superseded` event that supersedes the open `conflict`) clears it; and
    - **the held content flips and flips back, the integrity score never lowered** —
      the held `content_hash` goes original → peer → original across the adopt and
      the restore, while `doctor`'s `custody.score` holds at 100 throughout, because
      adoption swaps one full-fidelity capture for another and the prior is archived,
      not destroyed (custody §2.4 — adoption is a recorded event, never a loss).
    """
    # 1. HOLD a topic in full; the arxiv paper is the one a peer will re-capture.
    lib = home("library")
    items = _held_topic()
    _build(items)
    original = items[0]
    assert original.source == "arxiv"
    assert get_item(lib.db_path, original.id).content_hash == original.content_hash
    capsys.readouterr()  # drain the kb report

    # prove: nothing diverges yet — the conflict aggregate is 0, the score 100.
    assert main(["doctor"]) == 0
    start = json.loads(capsys.readouterr().out)["custody"]
    assert start["score"] == 100
    assert start["conflicts"]["items"] == 0

    # 2. A PEER shares a bundle of the same topic — but their arxiv capture diverges
    #    (a fuller body, a fresh content hash); the two web scrolls are byte-identical.
    home("peer")
    assert main(["init"]) == 0
    capsys.readouterr()
    _build([_peer_recapture(original), items[1], items[2]])
    capsys.readouterr()
    assert main(["export", "bundle", TOPIC]) == 0
    peer_bundle = capsys.readouterr().out
    peer_path = tmp_path / "peer-briefing.md"
    peer_path.write_text(peer_bundle, encoding="utf-8")

    # 3. IMPORT the peer bundle WITHOUT adopting: the divergent arxiv capture is
    #    surfaced as a conflict and recorded; the held copy is kept (raw is sacred).
    home("library")
    assert main(["import", "bundle", str(peer_path)]) == 0
    detect = json.loads(capsys.readouterr().out)
    assert detect["conflict"] == 1
    assert detect["conflicts"] == [original.id]
    assert detect["adopted"] == []
    assert detect["unchanged"] == 2  # the two web scrolls travelled identical
    # the held copy is provably untouched — still our original capture
    assert get_item(lib.db_path, original.id).content_hash == original.content_hash

    # REVIEW via doctor: the conflict aggregate moved 0 → 1, the score still 100.
    assert main(["doctor"]) == 0
    detected = json.loads(capsys.readouterr().out)["custody"]
    assert detected["score"] == 100
    assert detected["conflicts"]["items"] == 1
    assert [e["id"] for e in detected["conflicts"]["events"]] == [original.id]
    assert detected["conflicts"]["events"][0]["observed_hash"] == PEER_HASH

    # REVIEW via history: the divergence is a queryable, recorded custody event.
    assert main(["history", original.id, "--status", "conflict"]) == 0
    conflict_events = json.loads(capsys.readouterr().out)
    assert len(conflict_events) == 1
    assert conflict_events[0]["status"] == "conflict"
    assert conflict_events[0]["observed_hash"] == PEER_HASH

    # 4. ADOPT: re-import the same bundle with --accept-incoming. The held copy is
    #    replaced by the peer's capture, its prior archived, the conflict cleared.
    assert main(["import", "bundle", str(peer_path), "--accept-incoming"]) == 0
    adopt = json.loads(capsys.readouterr().out)
    assert adopt["adopted"] == [original.id]
    assert adopt["conflicts"] == []
    # the held content FLIPPED to the peer's capture
    assert get_item(lib.db_path, original.id).content_hash == PEER_HASH

    # the conflict aggregate moved 1 → 0; the score was never lowered.
    assert main(["doctor"]) == 0
    adopted_state = json.loads(capsys.readouterr().out)["custody"]
    assert adopted_state["score"] == 100
    assert adopted_state["conflicts"]["items"] == 0

    # the adoption is a recorded `superseded` event; the prior is archived.
    assert main(["history", original.id, "--status", "superseded"]) == 0
    superseded = json.loads(capsys.readouterr().out)
    assert len(superseded) == 1
    assert superseded[0]["status"] == "superseded"
    assert main(["archive", "list", "--id", original.id]) == 0
    archive = json.loads(capsys.readouterr().out)
    assert archive["count"] == 1
    assert archive["archived"][0]["prior_hash"] == original.content_hash
    assert archive["archived"][0]["superseded_by"] == PEER_HASH

    # 5. RESTORE the prior: `archive show <id>` emits the original capture as a
    #    re-importable JSONL line; `import items --accept-incoming` re-adopts it
    #    (archiving the peer copy in turn — the symmetric round-trip, ADR 0106).
    assert main(["archive", "show", original.id]) == 0
    archived_line = capsys.readouterr().out
    recovered = _read_jsonl_lines(archived_line)
    assert len(recovered) == 1 and recovered[0]["content_hash"] == original.content_hash
    restore_path = tmp_path / "restore.jsonl"
    restore_path.write_text(archived_line, encoding="utf-8")

    assert main(["import", "items", str(restore_path), "--accept-incoming"]) == 0
    restore = json.loads(capsys.readouterr().out)
    assert restore["adopted"] == [original.id]
    # the held content FLIPPED BACK to our original capture
    assert get_item(lib.db_path, original.id).content_hash == original.content_hash

    # the conflict aggregate is still 0 (a superseded adoption, never an open
    # conflict); the score still 100 — the whole flip-and-flip-back kept custody
    # intact, every prior recoverable, integrity never lowered.
    assert main(["doctor"]) == 0
    final = json.loads(capsys.readouterr().out)["custody"]
    assert final["score"] == 100
    assert final["conflicts"]["items"] == 0


# --- the restore-by-version leg (H287): roll back to a *specific* earlier
#     version across multiple supersessions — the H284 analogue on the
#     H285/H286 reads -----------------------------------------------------------

ORIG_HASH = "sha256:06.03762"  # _held_topic()'s arxiv capture (content_hash = source_id[-8:])


def _divergent_recapture(held: ScrollItem, content_hash: str, note: str) -> ScrollItem:
    """A successive divergent re-capture of the same arxiv source — same id, a fresh
    content hash, a fuller body — still full-fidelity (raw + extracted + hash +
    provenance), so each adoption is a flip of *which* faithful copy we hold, never
    a loss. Built from the *held DB row* so it carries the rendered `markdown_path`
    (an adoption replaces every column, so a recapture lacking it would orphan the
    scroll file — the `_seed_with_archived_priors` discipline). The chain v1→v2→v3
    stands in for an operator adopting several peer captures over time before
    realising a *specific earlier* one was right."""
    return replace(
        held,
        content_hash=content_hash,
        raw_text=f"<recapture {content_hash} of {held.url}>",
        extracted_text=f"{held.extracted_text} {note}",
    )


def _scripted_clock(holder: dict):
    """A `datetime` stand-in whose `now()` reads `holder['now']`, so the dogfood can
    archive successive accept-incoming adoptions at *spaced* UTC moments — the
    real-world 'adoptions made over several days' an operator later bisects with
    `archive restore --at`. Controlling the archive clock is the same offline
    stand-in discipline this module applies to its two live edges (capture, recheck):
    the archive timestamp is the one seam restore-by-version's `--at` selector reads."""

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(holder["now"])

    return _Clock


def test_restore_by_version_rolls_back_to_a_specific_earlier_capture(
    home, capsys, tmp_path, monkeypatch
):
    """*restore-by-version* (H287): the multi-supersession sibling of the adopt leg.

    H284 adopts *one* peer capture and restores the latest prior; this exercises the
    case the H285/H286 reads were built for — an operator adopts a *chain* of
    divergent captures (v1→v2→v3) over several days, then realises a *specific
    earlier* version was right and rolls back to it by `--hash` (an intermediate) and
    by `--at` (the original, as held at the earliest point in time), not merely the
    latest. The full history is inspected via `archive show <id> --all` (H285) before
    each rollback, then `archive restore <id> --hash/--at` (H286) selects the version.

    The three custody points the leg pins, the restore-by-version twins of the adopt
    leg's "adoption never lowers the score":

    - **the held `content_hash` flips to the *chosen* prior**, not the latest —
      `--hash` lands the intermediate v1 (the latest prior was v2), `--at` lands the
      original (the earliest archived prior);
    - **the displaced copy is itself archived** — after each rollback `archive show`
      recovers exactly the version we just left, so the rollback is reversible
      (custody §2.4: nothing is destroyed, every version stays recoverable); and
    - **`doctor`'s `custody.score` holds at 100 throughout** — restore-by-version
      swaps one full-fidelity capture for another and the displaced one is archived,
      so integrity is never lowered across the whole chain of adoptions + rollbacks.
    """

    def _custody() -> dict:
        assert main(["doctor"]) == 0
        return json.loads(capsys.readouterr().out)["custody"]

    # 1. HOLD the topic in full; the arxiv paper is the one we'll recapture in a chain.
    lib = home("library")
    items = _held_topic()
    _build(items)
    original = items[0]
    assert original.source == "arxiv" and original.content_hash == ORIG_HASH
    capsys.readouterr()  # drain the kb report
    held0 = get_item(lib.db_path, original.id)  # the rendered row (carries markdown_path)
    start = _custody()
    assert start["score"] == 100 and start["tiers"]["full"] == 3

    # 2. ADOPT a chain of three divergent captures over three days, each archiving the
    #    prior. A scripted clock spaces the archive timestamps so `--at` can bisect
    #    them deterministically (the offline stand-in this module applies to the live
    #    edges, here on the adoption clock).
    clock = {"now": "2026-06-19T00:00:00+00:00"}
    monkeypatch.setattr(cli, "datetime", _scripted_clock(clock))
    chain = [
        ("sha256:peer-v1", "2026-06-19T00:00:00+00:00", "Adds a worked attention example."),
        ("sha256:peer-v2", "2026-06-20T00:00:00+00:00", "Adds the multi-head derivation."),
        ("sha256:peer-v3", "2026-06-21T00:00:00+00:00", "Adds the positional-encoding proof."),
    ]
    for new_hash, archived_at, note in chain:
        clock["now"] = archived_at
        recapture = _divergent_recapture(held0, new_hash, note)
        incoming = tmp_path / f"{new_hash.split(':')[1]}.jsonl"
        incoming.write_text(dump_items_export([recapture]), encoding="utf-8")
        assert main(["import", "items", str(incoming), "--accept-incoming"]) == 0
        assert json.loads(capsys.readouterr().out)["adopted"] == [original.id]
    # held is the newest capture; the original + two intermediates are archived.
    assert get_item(lib.db_path, original.id).content_hash == "sha256:peer-v3"

    # 3. INSPECT the full recoverable history (H285): three priors, newest first.
    assert main(["archive", "show", original.id, "--all"]) == 0
    history = _read_jsonl_lines(capsys.readouterr().out)
    assert [snap["content_hash"] for snap in history] == [
        "sha256:peer-v2", "sha256:peer-v1", ORIG_HASH,
    ]
    # …and the recovery index agrees, with the spaced archive timestamps --at bisects.
    assert main(["archive", "list", "--id", original.id]) == 0
    index = json.loads(capsys.readouterr().out)
    assert index["count"] == 3
    assert [e["prior_hash"] for e in index["archived"]] == [
        "sha256:peer-v2", "sha256:peer-v1", ORIG_HASH,
    ]
    assert [e["archived_at"] for e in index["archived"]] == [
        "2026-06-21T00:00:00+00:00",
        "2026-06-20T00:00:00+00:00",
        "2026-06-19T00:00:00+00:00",
    ]
    # three adoptions, every copy full-fidelity → the score never moved.
    assert _custody()["score"] == 100

    # 4. ROLL BACK by --hash to a *specific intermediate* (v1, NOT the latest prior v2).
    clock["now"] = "2026-06-22T00:00:00+00:00"
    assert main(["archive", "restore", original.id, "--hash", "sha256:peer-v1"]) == 0
    by_hash = json.loads(capsys.readouterr().out)
    assert by_hash["selector"] == {"hash": "sha256:peer-v1"}
    assert by_hash["restored"] is True and by_hash["outcome"] == "adopted"
    assert by_hash["prior_hash"] == "sha256:peer-v1"   # the chosen version
    assert by_hash["held_hash"] == "sha256:peer-v3"    # what it displaced
    # (a) the held content flipped to the *chosen* prior, not the latest (v2).
    assert get_item(lib.db_path, original.id).content_hash == "sha256:peer-v1"
    # (b) the displaced v3 is itself archived — `archive show` recovers it (reversible).
    assert main(["archive", "show", original.id]) == 0
    displaced = _read_jsonl_lines(capsys.readouterr().out)
    assert len(displaced) == 1 and displaced[0]["content_hash"] == "sha256:peer-v3"
    # (c) the score held at 100.
    assert _custody()["score"] == 100

    # 5. ROLL BACK by --at to the *original*, as held at the earliest point in time:
    #    the newest prior archived at/before 06-19T12 is the original (06-19); v1/v2/v3
    #    were archived later, so they fall after the boundary.
    clock["now"] = "2026-06-23T00:00:00+00:00"
    assert main(
        ["archive", "restore", original.id, "--at", "2026-06-19T12:00:00+00:00"]
    ) == 0
    by_at = json.loads(capsys.readouterr().out)
    assert by_at["selector"] == {"at": "2026-06-19T12:00:00+00:00"}
    assert by_at["restored"] is True and by_at["outcome"] == "adopted"
    assert by_at["prior_hash"] == ORIG_HASH                     # the original capture
    assert by_at["archived_at"] == "2026-06-19T00:00:00+00:00"  # when it was archived
    assert by_at["held_hash"] == "sha256:peer-v1"               # what it displaced
    # (a) the held content rolled all the way back to our original capture.
    assert get_item(lib.db_path, original.id).content_hash == ORIG_HASH
    # (b) the displaced v1 is archived in turn — every version still recoverable.
    assert main(["archive", "show", original.id]) == 0
    displaced_again = _read_jsonl_lines(capsys.readouterr().out)
    assert len(displaced_again) == 1 and displaced_again[0]["content_hash"] == "sha256:peer-v1"
    # (c) the score never moved across the whole chain of adoptions + rollbacks.
    assert _custody()["score"] == 100


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
