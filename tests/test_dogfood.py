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
    archived_records,
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


# --- the decide-before-you-restore leg (H289): read `archive diff`, then act,
#     and the act matches exactly what the read predicted — the H287 analogue on
#     the H288 read ------------------------------------------------------------


def test_archive_diff_decides_then_restore_acts_exactly_as_predicted(
    home, capsys, tmp_path
):
    """*decide-before-you-restore* (H289): the read that precedes the rollback.

    H287 dogfoods restore-by-version (roll back by ``--hash``/``--at``); it never
    exercised the **read an operator runs first** — `archive diff` (H288), the
    decide-before-you-restore inspection that answers *what would a restore change,
    and would it change anything at all?* before `archive restore` (H286) writes.
    This leg runs the whole decide → act loop offline: hold a topic, adopt one
    divergent peer capture (so a single prior is archived), then **diff → restore →
    diff again → restore again**, asserting at each step that the act lands exactly
    on the diff's prediction.

    The two custody points the leg pins — the decide-before-you-restore twins of the
    restore-by-version leg's "the rollback lands the chosen version":

    - **read-then-act convergence** — `archive diff`'s ``would_restore`` *is* the
      subsequent `archive restore`'s ``restored``, and the diff's
      ``prior_hash``/``held_hash`` are exactly the version a restore lands and the
      copy it displaces. The read and the write fold the *same*
      `select_archived_snapshot` selector + ``content_hash`` compare, so the decision
      an operator reads can never disagree with the write they then run. Pinned on
      **both** outcomes: the would-change case (diff says ``true`` → restore adopts)
      *and* the idempotent case (a second diff against the just-restored prior says
      ``false`` + empty ``changed_fields`` → a restore is an ``unchanged`` no-op); and

    - **the diff is a true read** — the held ``content_hash`` is untouched across each
      diff, only the `restore` between them moves it (so an operator can inspect as
      many times as they like before deciding), and `doctor`'s ``custody.score`` holds
      at 100 the whole way (no inspection, and no reversible rollback, ever lowers
      integrity — custody §2.4).
    """

    def _custody() -> dict:
        assert main(["doctor"]) == 0
        return json.loads(capsys.readouterr().out)["custody"]

    # 1. HOLD the topic in full; the arxiv paper is the one a peer re-captures.
    lib = home("library")
    items = _held_topic()
    _build(items)
    original = items[0]
    assert original.source == "arxiv" and original.content_hash == ORIG_HASH
    capsys.readouterr()  # drain the kb report
    held0 = get_item(lib.db_path, original.id)  # the rendered row (carries markdown_path)
    assert _custody()["score"] == 100

    # 2. ADOPT one divergent peer capture: the prior (our original) is archived, the
    #    held copy flips to the peer's. Built from the held DB row so the recapture
    #    carries the rendered markdown_path (the H287 discipline — an adoption replaces
    #    every column, so a recapture lacking it would orphan the scroll file).
    recapture = _divergent_recapture(held0, PEER_HASH, "Adds a worked attention example.")
    incoming = tmp_path / "peer.jsonl"
    incoming.write_text(dump_items_export([recapture]), encoding="utf-8")
    assert main(["import", "items", str(incoming), "--accept-incoming"]) == 0
    assert json.loads(capsys.readouterr().out)["adopted"] == [original.id]
    assert get_item(lib.db_path, original.id).content_hash == PEER_HASH

    # 3. DECIDE — `archive diff` (default selector = the latest, our only, prior):
    #    what would a restore get back, and what would it cost?
    assert main(["archive", "diff", original.id]) == 0
    diff = json.loads(capsys.readouterr().out)
    assert diff["selector"] == {"latest": True}
    assert diff["held_hash"] == PEER_HASH      # what we hold now (the peer's capture)
    assert diff["prior_hash"] == ORIG_HASH     # the version a restore would land
    assert diff["held_fidelity"] == "full" and diff["prior_fidelity"] == "full"
    # the model-complete fields a restore would surface — exactly the three the peer
    # recapture diverged on, nothing more (a full→full swap, no fidelity loss).
    assert diff["changed_fields"] == ["content_hash", "extracted_text", "raw_text"]
    assert diff["would_restore"] is True       # the held copy and the prior differ
    # the diff is a *read* — it wrote nothing; the held copy is still the peer's.
    assert get_item(lib.db_path, original.id).content_hash == PEER_HASH

    # 4. ACT — `archive restore` with the same (default) selector, and assert it lands
    #    exactly on the diff's prediction: read-then-act convergence.
    assert main(["archive", "restore", original.id]) == 0
    restore = json.loads(capsys.readouterr().out)
    assert restore["selector"] == diff["selector"]          # same version selected
    assert restore["restored"] == diff["would_restore"]     # would_restore *is* restored
    assert restore["prior_hash"] == diff["prior_hash"]      # landed the version diff named
    assert restore["held_hash"] == diff["held_hash"]        # displaced the copy diff named
    assert restore["outcome"] == "adopted"
    # the rollback happened: the held copy flipped to our original.
    assert get_item(lib.db_path, original.id).content_hash == ORIG_HASH
    assert _custody()["score"] == 100  # a reversible swap never lowers integrity

    # 5. DECIDE AGAIN — `archive diff --hash <ORIG>` against the now-restored prior:
    #    there is nothing left to restore, exactly the idempotency the first diff's
    #    `would_restore` chain implies.
    assert main(["archive", "diff", original.id, "--hash", ORIG_HASH]) == 0
    diff2 = json.loads(capsys.readouterr().out)
    assert diff2["selector"] == {"hash": ORIG_HASH}
    assert diff2["held_hash"] == ORIG_HASH and diff2["prior_hash"] == ORIG_HASH
    assert diff2["changed_fields"] == []        # the prior already *is* the held copy
    assert diff2["would_restore"] is False
    # still a read — the held copy is untouched between the two diffs.
    assert get_item(lib.db_path, original.id).content_hash == ORIG_HASH

    # 6. ACT AGAIN — restoring the already-held version is the `unchanged` no-op the
    #    second diff predicted: would_restore is restored, on the idempotent case too.
    assert main(["archive", "restore", original.id, "--hash", ORIG_HASH]) == 0
    restore2 = json.loads(capsys.readouterr().out)
    assert restore2["selector"] == diff2["selector"]
    assert restore2["restored"] == diff2["would_restore"]   # False == False, never lies
    assert restore2["outcome"] == "unchanged"
    assert get_item(lib.db_path, original.id).content_hash == ORIG_HASH
    assert _custody()["score"] == 100


# --- the cross-machine recovery leg (H292): the whole decide→restore recovery
#     workflow survives a `--with-archive` bundle handoff — you can decide-and-
#     restore on a machine that never saw the original adoptions (the H287/H289
#     analogue across the bundle boundary) ---------------------------------------


def test_recovery_workflow_survives_a_machine_handoff(
    home, capsys, tmp_path, monkeypatch
):
    """*cross-machine recovery* (H292): the decide→restore loop, end to end, on a
    library rebuilt from a portable `--with-archive` bundle.

    H280 makes the prior-content archive *travel* in the portable bundle; H291 pins
    that the whole recovery *read*-family (`archive show --all`/`diff`/`restore
    --dry-run`) reads identically on the rebuilt library — but only as non-mutating
    reads, never running the recovery *act*. This leg is the operator-workflow layer
    above that test: someone hands you a `--with-archive` bundle, you `import bundle`
    into a fresh library on a machine that *never saw the original adoptions*, repair
    it to materialize the rendered scrolls, then **recover on it for real** — read
    `archive diff` to decide, run `archive restore` (a genuine write that moves the
    held copy) to act. The "take it with me" guarantee (M4/cap 4) extended from "the
    archive travels" (H280) to "the whole recovery *workflow* travels".

    The three custody points the leg pins — the cross-machine twins of the
    decide-before-you-restore leg's "the act lands exactly on the read's prediction":

    - **the whole recovery workflow travels** — both the decision (`archive diff`)
      and the act (`archive restore`, a real write) run on library B, which was
      rebuilt *purely from the bundle* and never saw the chain of adoptions made on
      A; the full recoverable history (`archive show --all`) is there to inspect and
      a *specific earlier* prior is selectable by `--hash`, not just the latest;

    - **read-then-act convergence across the boundary** — `archive diff`'s
      ``would_restore`` *is* the subsequent `archive restore`'s ``restored``, with
      matching ``prior_hash``/``held_hash``, on **both** the would-change and the
      idempotent no-op cases (the H289 convergence, now across a machine handoff);
      and

    - **the recovery write keeps custody intact** — the real restore flips the held
      copy to the chosen prior and re-archives the copy it displaced (reversible —
      custody §2.4: nothing is destroyed), and `doctor`'s ``custody.score`` holds at
      100 through the whole recovery on the freshly-imported library.
    """

    def _custody() -> dict:
        assert main(["doctor"]) == 0
        return json.loads(capsys.readouterr().out)["custody"]

    # 1. HOLD + ADOPT a chain on machine A: hold the topic in full, then adopt two
    #    divergent peer captures of the arxiv paper over two days (v1→v2), each
    #    archiving the prior. A's archive ends holding [original, v1] (held = v2) — a
    #    genuine multi-supersession chain, so a restore can reach *past* the latest
    #    prior (v1) to a specific earlier version. Recaptures are built from the held
    #    DB row so they carry the rendered markdown_path (the H287 discipline); a
    #    scripted clock spaces the archive timestamps deterministically.
    a = home("machine-a")
    items = _held_topic()
    _build(items)
    original = items[0]
    assert original.source == "arxiv" and original.content_hash == ORIG_HASH
    capsys.readouterr()  # drain the kb report
    held0 = get_item(a.db_path, original.id)  # the rendered row (carries markdown_path)

    clock = {"now": "2026-06-19T00:00:00+00:00"}
    monkeypatch.setattr(cli, "datetime", _scripted_clock(clock))
    for new_hash, archived_at, note in (
        ("sha256:peer-v1", "2026-06-19T00:00:00+00:00", "Adds a worked attention example."),
        ("sha256:peer-v2", "2026-06-20T00:00:00+00:00", "Adds the multi-head derivation."),
    ):
        clock["now"] = archived_at
        recapture = _divergent_recapture(held0, new_hash, note)
        incoming = tmp_path / f"{new_hash.split(':')[1]}.jsonl"
        incoming.write_text(dump_items_export([recapture]), encoding="utf-8")
        assert main(["import", "items", str(incoming), "--accept-incoming"]) == 0
        assert json.loads(capsys.readouterr().out)["adopted"] == [original.id]
    assert get_item(a.db_path, original.id).content_hash == "sha256:peer-v2"

    # 2. PACK: export a portable `--with-archive` bundle — the artifact handed off, so
    #    the prior-content archive travels with the holdings (H280), not just the head.
    assert main(["export", "bundle", TOPIC, "--with-archive"]) == 0
    bundle_path = tmp_path / "transformer-with-archive.md"
    bundle_path.write_text(capsys.readouterr().out, encoding="utf-8")

    # 3. HANDOFF to machine B — a fresh library that never saw A's adoptions. Import
    #    the bundle, repair to materialize the rendered scrolls (import inserts the
    #    rows but doesn't render — the same `doctor --fix` the take-it-with-me flow
    #    runs), then prove custody: the score is 100 and the whole recovery store
    #    travelled (both archived priors, not just the latest head).
    b = home("machine-b")
    assert main(["init"]) == 0
    capsys.readouterr()
    assert main(["import", "bundle", str(bundle_path)]) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["imported"] == len(items)
    assert imported["archive"]["imported"] == 2  # both archived priors travelled
    assert main(["doctor", "--fix"]) == 0
    assert main(["kb"]) == 0
    capsys.readouterr()
    rebuilt = _custody()
    assert rebuilt["score"] == 100 and rebuilt["issues"] == 0
    # the head travelled: B holds the peer's latest capture, as A did.
    assert get_item(b.db_path, original.id).content_hash == "sha256:peer-v2"

    # 4. INSPECT the full recoverable history on B — newest-first [v1, original]: the
    #    machine that never saw the adoptions can still see every recoverable prior.
    assert main(["archive", "show", original.id, "--all"]) == 0
    history = _read_jsonl_lines(capsys.readouterr().out)
    assert [snap["content_hash"] for snap in history] == ["sha256:peer-v1", ORIG_HASH]
    assert main(["archive", "list", "--id", original.id]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 2  # the chain depth travelled

    # 5. DECIDE on B — `archive diff --hash <ORIG>` reaches *past* the latest prior
    #    (v1) to the original capture: what would restoring it get back, and what
    #    would it cost?
    assert main(["archive", "diff", original.id, "--hash", ORIG_HASH]) == 0
    diff = json.loads(capsys.readouterr().out)
    assert diff["selector"] == {"hash": ORIG_HASH}
    assert diff["held_hash"] == "sha256:peer-v2"   # what B holds now
    assert diff["prior_hash"] == ORIG_HASH         # the version a restore would land
    assert diff["held_fidelity"] == "full" and diff["prior_fidelity"] == "full"
    # exactly the three fields the recapture diverged on (a full→full swap, no loss).
    assert diff["changed_fields"] == ["content_hash", "extracted_text", "raw_text"]
    assert diff["would_restore"] is True
    # the diff wrote nothing — B still holds the peer's latest capture.
    assert get_item(b.db_path, original.id).content_hash == "sha256:peer-v2"

    # 6. ACT on B — `archive restore` with the same selector (a *real* write), and
    #    assert it lands exactly on the diff's prediction: read-then-act convergence
    #    across the machine boundary.
    clock["now"] = "2026-06-21T00:00:00+00:00"
    assert main(["archive", "restore", original.id, "--hash", ORIG_HASH]) == 0
    restore = json.loads(capsys.readouterr().out)
    assert restore["selector"] == diff["selector"]          # same version selected
    assert restore["restored"] == diff["would_restore"]     # would_restore *is* restored
    assert restore["prior_hash"] == diff["prior_hash"]      # landed the version diff named
    assert restore["held_hash"] == diff["held_hash"]        # displaced the copy diff named
    assert restore["outcome"] == "adopted"
    # the recovery happened on B: the held copy flipped to our original capture.
    assert get_item(b.db_path, original.id).content_hash == ORIG_HASH
    # the displaced v2 is itself archived — the rollback is reversible on B too.
    assert main(["archive", "show", original.id]) == 0
    displaced = _read_jsonl_lines(capsys.readouterr().out)
    assert len(displaced) == 1 and displaced[0]["content_hash"] == "sha256:peer-v2"
    # the real recovery write never lowered integrity on the freshly-imported library.
    assert _custody()["score"] == 100

    # 7. DECIDE + ACT AGAIN — the idempotent no-op the convergence implies: a second
    #    diff against the now-restored original says there is nothing left to restore,
    #    and the restore agrees — `would_restore` is `restored` on the no-op case too.
    assert main(["archive", "diff", original.id, "--hash", ORIG_HASH]) == 0
    diff2 = json.loads(capsys.readouterr().out)
    assert diff2["would_restore"] is False and diff2["changed_fields"] == []
    assert main(["archive", "restore", original.id, "--hash", ORIG_HASH]) == 0
    restore2 = json.loads(capsys.readouterr().out)
    assert restore2["restored"] == diff2["would_restore"]   # False == False, never lies
    assert restore2["outcome"] == "unchanged"
    assert get_item(b.db_path, original.id).content_hash == ORIG_HASH
    assert _custody()["score"] == 100


# --- the JSONL-backup recovery leg (H297): the same decide→restore recovery
#     workflow survives an `export items` + `export archive` handoff — the H292
#     twin on the whole-library JSONL-backup transport (the *other* portable
#     recovery store: two backup files, not one shareable bundle) ----------------


def test_recovery_workflow_survives_a_jsonl_backup_handoff(
    home, capsys, tmp_path, monkeypatch
):
    """*JSONL-backup recovery* (H297): the decide→restore loop, end to end, on a
    library rebuilt from a whole-library `export items` + `export archive` backup —
    the H292 cross-machine dogfood on the *other* portable recovery transport.

    H292 runs the recovery *act* on a library rebuilt from a single `--with-archive`
    *bundle*; H294 pins that the recovery *read*-family (`archive show --all`/`diff`/
    `restore --dry-run`) round-trips the *JSONL-backup* path identically — but only
    as non-mutating reads, never running the recovery *act* on the backup-rebuilt
    library. This leg is the operator-workflow layer above H294, the JSONL-backup
    twin of H292: back machine A up to two files (`export items` → the holdings +
    ledger, `export archive` → the prior-content recovery store), rebuild a fresh
    library B from *both backups alone* on a machine that *never saw the original
    adoptions*, repair it, then **recover on it for real** — read `archive diff` to
    decide, run `archive restore` (a genuine write that moves the held copy) to act.
    The "back it up / take it with me" guarantee extended from "the read-family
    round-trips the backup" (H294) to "the whole recovery *workflow* round-trips it".

    The three custody points the leg pins — the JSONL-backup twins of the
    cross-machine bundle leg's (H292) "the whole recovery workflow travels":

    - **the whole recovery workflow round-trips the backup** — both the decision
      (`archive diff`) and the act (`archive restore`, a real write) run on library
      B, rebuilt *purely from the two backup files* (`import items` + `import
      archive`) and never witness to the chain of adoptions made on A; the full
      recoverable history (`archive show --all`) is there to inspect and a *specific
      earlier* prior is selectable by `--hash`, not just the latest;

    - **read-then-act convergence across the backup boundary** — `archive diff`'s
      ``would_restore`` *is* the subsequent `archive restore`'s ``restored``, with
      matching ``prior_hash``/``held_hash``, on **both** the would-change and the
      idempotent no-op cases (the H289 convergence, now across a JSONL-backup
      rebuild); and

    - **the recovery write keeps custody intact** — the real restore flips the held
      copy to the chosen prior and re-archives the copy it displaced (reversible —
      custody §2.4: nothing is destroyed), and `doctor`'s ``custody.score`` holds at
      100 through the whole recovery on the backup-rebuilt library.
    """

    def _custody() -> dict:
        assert main(["doctor"]) == 0
        return json.loads(capsys.readouterr().out)["custody"]

    # 1. HOLD + ADOPT a chain on machine A: hold the topic in full, then adopt two
    #    divergent peer captures of the arxiv paper over two days (v1→v2), each
    #    archiving the prior. A's archive ends holding [original, v1] (held = v2) — a
    #    genuine multi-supersession chain, so a restore can reach *past* the latest
    #    prior (v1) to a specific earlier version. Recaptures are built from the held
    #    DB row so they carry the rendered markdown_path (the H287 discipline); a
    #    scripted clock spaces the archive timestamps deterministically.
    a = home("machine-a")
    items = _held_topic()
    _build(items)
    original = items[0]
    assert original.source == "arxiv" and original.content_hash == ORIG_HASH
    capsys.readouterr()  # drain the kb report
    held0 = get_item(a.db_path, original.id)  # the rendered row (carries markdown_path)

    clock = {"now": "2026-06-19T00:00:00+00:00"}
    monkeypatch.setattr(cli, "datetime", _scripted_clock(clock))
    for new_hash, archived_at, note in (
        ("sha256:peer-v1", "2026-06-19T00:00:00+00:00", "Adds a worked attention example."),
        ("sha256:peer-v2", "2026-06-20T00:00:00+00:00", "Adds the multi-head derivation."),
    ):
        clock["now"] = archived_at
        recapture = _divergent_recapture(held0, new_hash, note)
        incoming = tmp_path / f"{new_hash.split(':')[1]}.jsonl"
        incoming.write_text(dump_items_export([recapture]), encoding="utf-8")
        assert main(["import", "items", str(incoming), "--accept-incoming"]) == 0
        assert json.loads(capsys.readouterr().out)["adopted"] == [original.id]
    assert get_item(a.db_path, original.id).content_hash == "sha256:peer-v2"

    # 2. BACK UP: the whole-library JSONL backup — two files, not one bundle. `export
    #    items` is the holdings + custody ledger; `export archive` is the prior-content
    #    recovery store. Together they are the backup an operator stores off-machine, so
    #    the archive travels alongside the holdings (H294), not just the latest head.
    capsys.readouterr()
    assert main(["export", "items"]) == 0
    items_backup = tmp_path / "library-items.jsonl"
    items_backup.write_text(capsys.readouterr().out, encoding="utf-8")
    assert main(["export", "archive"]) == 0
    archive_backup = tmp_path / "library-archive.jsonl"
    archive_backup.write_text(capsys.readouterr().out, encoding="utf-8")

    # 3. HANDOFF to machine B — a fresh library that never saw A's adoptions. Restore
    #    from the two backups (the holdings first, then their priors), repair to
    #    materialize the rendered scrolls (`import items` inserts the rows but doesn't
    #    render — the same `doctor --fix` the take-it-with-me flow runs), then prove
    #    custody: the score is 100 and the whole recovery store travelled (both
    #    archived priors, not just the latest head).
    b = home("machine-b")
    assert main(["init"]) == 0
    capsys.readouterr()
    assert main(["import", "items", str(items_backup)]) == 0
    restored_items = json.loads(capsys.readouterr().out)
    assert restored_items["imported"] == len(items)
    assert main(["import", "archive", str(archive_backup)]) == 0
    restored_archive = json.loads(capsys.readouterr().out)
    assert restored_archive["imported"] == 2  # both archived priors travelled
    assert restored_archive["skipped"] == 0
    assert main(["doctor", "--fix"]) == 0
    assert main(["kb"]) == 0
    capsys.readouterr()
    rebuilt = _custody()
    assert rebuilt["score"] == 100 and rebuilt["issues"] == 0
    # the head travelled: B holds the peer's latest capture, as A did.
    assert get_item(b.db_path, original.id).content_hash == "sha256:peer-v2"

    # 4. INSPECT the full recoverable history on B — newest-first [v1, original]: the
    #    machine that never saw the adoptions can still see every recoverable prior.
    assert main(["archive", "show", original.id, "--all"]) == 0
    history = _read_jsonl_lines(capsys.readouterr().out)
    assert [snap["content_hash"] for snap in history] == ["sha256:peer-v1", ORIG_HASH]
    assert main(["archive", "list", "--id", original.id]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 2  # the chain depth travelled

    # 5. DECIDE on B — `archive diff --hash <ORIG>` reaches *past* the latest prior
    #    (v1) to the original capture: what would restoring it get back, and what
    #    would it cost?
    assert main(["archive", "diff", original.id, "--hash", ORIG_HASH]) == 0
    diff = json.loads(capsys.readouterr().out)
    assert diff["selector"] == {"hash": ORIG_HASH}
    assert diff["held_hash"] == "sha256:peer-v2"   # what B holds now
    assert diff["prior_hash"] == ORIG_HASH         # the version a restore would land
    assert diff["held_fidelity"] == "full" and diff["prior_fidelity"] == "full"
    # exactly the three fields the recapture diverged on (a full→full swap, no loss).
    assert diff["changed_fields"] == ["content_hash", "extracted_text", "raw_text"]
    assert diff["would_restore"] is True
    # the diff wrote nothing — B still holds the peer's latest capture.
    assert get_item(b.db_path, original.id).content_hash == "sha256:peer-v2"

    # 6. ACT on B — `archive restore` with the same selector (a *real* write), and
    #    assert it lands exactly on the diff's prediction: read-then-act convergence
    #    across the JSONL-backup boundary.
    clock["now"] = "2026-06-21T00:00:00+00:00"
    assert main(["archive", "restore", original.id, "--hash", ORIG_HASH]) == 0
    restore = json.loads(capsys.readouterr().out)
    assert restore["selector"] == diff["selector"]          # same version selected
    assert restore["restored"] == diff["would_restore"]     # would_restore *is* restored
    assert restore["prior_hash"] == diff["prior_hash"]      # landed the version diff named
    assert restore["held_hash"] == diff["held_hash"]        # displaced the copy diff named
    assert restore["outcome"] == "adopted"
    # the recovery happened on B: the held copy flipped to our original capture.
    assert get_item(b.db_path, original.id).content_hash == ORIG_HASH
    # the displaced v2 is itself archived — the rollback is reversible on B too.
    assert main(["archive", "show", original.id]) == 0
    displaced = _read_jsonl_lines(capsys.readouterr().out)
    assert len(displaced) == 1 and displaced[0]["content_hash"] == "sha256:peer-v2"
    # the real recovery write never lowered integrity on the backup-rebuilt library.
    assert _custody()["score"] == 100

    # 7. DECIDE + ACT AGAIN — the idempotent no-op the convergence implies: a second
    #    diff against the now-restored original says there is nothing left to restore,
    #    and the restore agrees — `would_restore` is `restored` on the no-op case too.
    assert main(["archive", "diff", original.id, "--hash", ORIG_HASH]) == 0
    diff2 = json.loads(capsys.readouterr().out)
    assert diff2["would_restore"] is False and diff2["changed_fields"] == []
    assert main(["archive", "restore", original.id, "--hash", ORIG_HASH]) == 0
    restore2 = json.loads(capsys.readouterr().out)
    assert restore2["restored"] == diff2["would_restore"]   # False == False, never lies
    assert restore2["outcome"] == "unchanged"
    assert get_item(b.db_path, original.id).content_hash == ORIG_HASH
    assert _custody()["score"] == 100


# --- the incremental-backup leg (H306): a full `export archive` at T0, then a
#     later `export archive --since T0` increment, restored onto a peer, is an
#     idempotent union that reads the recovery family identically — the H297
#     dogfood on the `--since` (incremental) axis ---------------------------------


def test_incremental_backup_workflow_round_trips_the_recovery_family(
    home, capsys, tmp_path, monkeypatch
):
    """*incremental-backup recovery* (H306): the operator-workflow layer above
    H303's data-layer idempotence test — a full `export archive` at T0, then a
    later `export archive --since T0` increment, restored onto a fresh peer, is an
    idempotent union (no double-count) that reads the recovery family identically.

    H297 backs a library up to a *whole-library* `export items` + `export archive`
    and recovers on the rebuild; this leg narrates the *incremental* backup an
    operator actually runs once the archive grows: take a full backup at T0, adopt
    more captures, then re-export **only** `export archive --since T0` (the cheap
    incremental — the append-only recovery store, not the whole thing again),
    re-snapshotting the small holdings (`export items`) each run. On a fresh machine
    B you restore the latest holdings + the full archive + every increment since.

    The custody points this leg pins — the `--since`-axis twins of H297's "the whole
    recovery workflow round-trips a backup":

    - **the increment is genuinely incremental** — `export archive --since T0`
      carries a *strict subset* of A's whole recovery store (the priors archived
      since T0), not the whole thing, yet it *overlaps* the full backup at the
      inclusive boundary prior;

    - **the union is idempotent — every prior lands exactly once** — `import archive
      <full>` then `import archive <increment>` *skips* the boundary prior the full
      already restored (ADR 0106's `(item_id, prior_hash)` dedup), so B's recovery
      store holds each prior once (no double-count), reconstructing A's whole archive
      from full + increment; and

    - **the recovery family reads identically across the boundary** — `archive show
      --all` (byte-for-byte), `archive diff`, and `archive restore --dry-run` over
      every selector read the same on B, rebuilt purely from full + increment, as on
      A, and `doctor`'s ``custody.score`` holds at 100 on the rebuilt library.
    """
    V1, V2, V3 = "sha256:peer-v1", "sha256:peer-v2", "sha256:peer-v3"
    # the boundary the operator passes to every incremental backup — the inclusive
    # (>=) edge, so the prior archived exactly at T0 rides in *both* backups (the
    # overlap that exercises the import dedup).
    T0 = "2026-06-19T00:00:00+00:00"

    def _custody() -> dict:
        assert main(["doctor"]) == 0
        return json.loads(capsys.readouterr().out)["custody"]

    # selectors the recovery family reads over: the oldest prior by hash (reach
    # *past* the latest priors), a point-in-time boundary mid-chain, default-latest.
    selectors = (["--hash", ORIG_HASH], ["--at", "2026-06-19T12:00:00+00:00"], [])

    def read_family():
        """The whole recovery read-family — non-mutating (reads + a dry-run), so it
        runs identically on A and on B without moving the held copy."""
        out = {}
        capsys.readouterr()
        assert main(["archive", "show", original.id, "--all"]) == 0
        out["show_all"] = capsys.readouterr().out  # raw JSONL, compared byte-for-byte
        for sel in selectors:
            key = " ".join(sel) or "latest"
            capsys.readouterr()
            assert main(["archive", "diff", original.id, *sel]) == 0
            out[f"diff:{key}"] = json.loads(capsys.readouterr().out)
            capsys.readouterr()
            assert main(["archive", "restore", original.id, *sel, "--dry-run"]) == 0
            out[f"restore:{key}"] = json.loads(capsys.readouterr().out)
        return out

    # 1. HOLD on machine A, then adopt a chain: original → v1@06-18 → v2@06-19. The
    #    held copy ends as v2; the archive holds [original@06-18, v1@06-19].
    a = home("machine-a")
    items = _held_topic()
    _build(items)
    original = items[0]
    assert original.source == "arxiv" and original.content_hash == ORIG_HASH
    capsys.readouterr()  # drain the kb report
    held0 = get_item(a.db_path, original.id)  # the rendered row (carries markdown_path)

    clock = {"now": T0}
    monkeypatch.setattr(cli, "datetime", _scripted_clock(clock))
    for new_hash, archived_at, note in (
        (V1, "2026-06-18T00:00:00+00:00", "Adds a worked attention example."),
        (V2, "2026-06-19T00:00:00+00:00", "Adds the multi-head derivation."),
    ):
        clock["now"] = archived_at
        incoming = tmp_path / f"{new_hash.split(':')[1]}.jsonl"
        incoming.write_text(
            dump_items_export([_divergent_recapture(held0, new_hash, note)]),
            encoding="utf-8",
        )
        assert main(["import", "items", str(incoming), "--accept-incoming"]) == 0
        assert json.loads(capsys.readouterr().out)["adopted"] == [original.id]
    assert get_item(a.db_path, original.id).content_hash == V2

    # 2. FULL backup at T0: the whole holdings + the whole recovery store. The
    #    archive holds the two priors archived so far [original@06-18, v1@06-19].
    capsys.readouterr()
    assert main(["export", "items"]) == 0
    items_t0 = capsys.readouterr().out  # holdings as of T0 (head = v2)
    assert main(["export", "archive"]) == 0
    archive_full = capsys.readouterr().out
    full_path = tmp_path / "archive-full.jsonl"
    full_path.write_text(archive_full, encoding="utf-8")
    assert [r["prior_hash"] for r in _read_jsonl_lines(archive_full)] == [ORIG_HASH, V1]

    # 3. Adopt MORE after T0: v3@06-20. The held copy advances to v3; the archive
    #    grows to [original@06-18, v1@06-19, v2@06-20].
    clock["now"] = "2026-06-20T00:00:00+00:00"
    incoming = tmp_path / "peer-v3.jsonl"
    incoming.write_text(
        dump_items_export([_divergent_recapture(held0, V3, "Adds the positional study.")]),
        encoding="utf-8",
    )
    assert main(["import", "items", str(incoming), "--accept-incoming"]) == 0
    assert json.loads(capsys.readouterr().out)["adopted"] == [original.id]
    assert get_item(a.db_path, original.id).content_hash == V3

    # 4. INCREMENTAL backup: re-snapshot the (now-advanced) holdings in full, but
    #    re-export only `export archive --since T0` — the cheap increment. The head
    #    advanced (v2 → v3), which is why the increment re-snapshots the holdings.
    assert main(["export", "items"]) == 0
    items_inc = capsys.readouterr().out  # holdings as of the increment (head = v3)
    items_path = tmp_path / "library-items.jsonl"
    items_path.write_text(items_inc, encoding="utf-8")
    assert main(["export", "archive", "--since", T0]) == 0
    archive_inc = capsys.readouterr().out
    inc_path = tmp_path / "archive-incremental.jsonl"
    inc_path.write_text(archive_inc, encoding="utf-8")

    # the holdings re-snapshot moved with the head (v2 at T0 → v3 at the increment),
    # so the latest items backup — not the T0 one — is what reconstructs A's head.
    assert _read_jsonl_lines(items_t0)  # the T0 holdings existed (superseded by items_inc)
    head_t0 = next(r for r in _read_jsonl_lines(items_t0) if r["id"] == original.id)
    head_inc = next(r for r in _read_jsonl_lines(items_inc) if r["id"] == original.id)
    assert (head_t0["content_hash"], head_inc["content_hash"]) == (V2, V3)

    # the increment is genuinely incremental: a strict subset of A's whole archive
    # (2 of 3 priors — original@06-18 is *before* T0, so it stays only in the full
    # backup), yet it OVERLAPS the full at the inclusive boundary prior (v1@06-19).
    inc_priors = [r["prior_hash"] for r in _read_jsonl_lines(archive_inc)]
    assert inc_priors == [V1, V2]  # archived at/after T0, not the pre-T0 original
    assert len(_read_jsonl_lines(archive_full)) == 2  # full backup carries 2…
    assert len(inc_priors) == 2 and len(archived_records(a.db_path)) == 3  # …of A's 3
    assert V1 in [r["prior_hash"] for r in _read_jsonl_lines(archive_full)]  # the overlap

    # capture A's recovery read-family for the cross-machine comparison.
    family_a = read_family()
    assert len(family_a["show_all"].splitlines()) == 3  # the full 3-prior chain
    assert family_a["diff:--hash " + ORIG_HASH]["would_restore"] is True

    # 5. HANDOFF to a fresh machine B: restore the latest holdings, then the full
    #    archive, then the increment. The increment SKIPS the boundary prior the
    #    full already restored (the dedup) — the union is idempotent, no double-count.
    b = home("machine-b")
    assert main(["init"]) == 0
    capsys.readouterr()
    assert main(["import", "items", str(items_path)]) == 0
    assert json.loads(capsys.readouterr().out)["imported"] == len(items)
    assert main(["import", "archive", str(full_path)]) == 0
    full_report = json.loads(capsys.readouterr().out)
    assert (full_report["imported"], full_report["skipped"]) == (2, 0)
    assert main(["import", "archive", str(inc_path)]) == 0
    # the boundary prior (v1@06-19) is already held from the full backup → skipped;
    # only v2@06-20 (archived after T0, absent from the full) is new.
    inc_report = json.loads(capsys.readouterr().out)
    assert (inc_report["imported"], inc_report["skipped"]) == (1, 1)
    assert main(["doctor", "--fix"]) == 0
    assert main(["kb"]) == 0
    capsys.readouterr()

    # 6. PROVE on B: the score is 100, the head matches A (v3), and the recovery
    #    store reconstructs A's whole archive — every prior exactly once (no
    #    double-count from the overlapping increment).
    rebuilt = _custody()
    assert rebuilt["score"] == 100 and rebuilt["issues"] == 0
    assert get_item(b.db_path, original.id).content_hash == V3
    assert archived_records(b.db_path, [original.id]) == archived_records(
        a.db_path, [original.id]
    )
    assert len(archived_records(b.db_path)) == 3  # not 4 — the boundary prior deduped

    # 7. the whole recovery read-family reads identically on B — rebuilt purely from
    #    the full backup + the increment — as it did on A: the incremental backup is
    #    a faithful recovery transport, not just a smaller file.
    assert read_family() == family_a


# --- the append-only boundary (H308): an `archive prune` on A does NOT
#     propagate through a later `export archive --since` increment, so a peer
#     rebuilt from an earlier full backup + the increment KEEPS the pruned prior;
#     retention propagation requires a fresh full backup, not an increment ------


def test_a_prune_does_not_propagate_through_an_incremental_backup(
    home, capsys, tmp_path, monkeypatch
):
    """*the incremental backup is honestly append-only* (H308): an `archive prune`
    on machine A is a retention *removal*, and `import archive` has no delete path —
    it only appends/dedups by ``(item_id, prior_hash)`` (ADR 0106) — so a prune
    leaves no trace an `export archive --since` increment could carry.

    H306 proves the union of a full backup + an overlapping increment *grows* the
    recovery store losslessly; the unstated boundary is that it can only ever grow.
    An operator who prunes old priors on A and then ships only an increment would
    wrongly assume the prune travelled. It does not: a peer **B** rebuilt from an
    *earlier* full backup (taken before the prune, so it still holds the pruned
    prior) + the increment **still holds the pruned prior** afterwards. The prune
    and the `--since` window meet at the *same* boundary T0 — the prune drops
    everything ``< T0``, the increment carries everything ``>= T0`` — so the pruned
    prior is *exactly* the part the increment can never reach.

    To propagate retention you re-take a **full** backup: a fresh peer **C** rebuilt
    from a post-prune full backup (which simply omits the pruned prior) matches A's
    recovery store. The remedy is a fresh full backup, not an increment.
    """
    V1, V2, V3 = "sha256:prune-v1", "sha256:prune-v2", "sha256:prune-v3"
    # the boundary shared by BOTH the prune (drops < T0) and the increment (carries
    # >= T0): they partition the archive cleanly at T0, so the pruned prior is the
    # one part the increment can never reach.
    T0 = "2026-06-19T00:00:00+00:00"

    def _custody() -> dict:
        assert main(["doctor"]) == 0
        return json.loads(capsys.readouterr().out)["custody"]

    def _archive_priors(db_path) -> list[str]:
        """A's recovery store as prior hashes, oldest-first (archived_at order)."""
        return [r.prior_hash for r in archived_records(db_path, [original.id])]

    def _rebuild_peer(name: str, items_file, *archive_files) -> object:
        """Restore a fresh machine from a holdings snapshot + archive backup(s)."""
        peer = home(name)
        assert main(["init"]) == 0
        capsys.readouterr()
        assert main(["import", "items", str(items_file)]) == 0
        for archive_file in archive_files:
            assert main(["import", "archive", str(archive_file)]) == 0
        assert main(["doctor", "--fix"]) == 0
        assert main(["kb"]) == 0
        capsys.readouterr()
        return peer

    # 1. HOLD on machine A, then adopt original → v1@06-18 → v2@06-19. The held copy
    #    ends as v2; the archive holds [original@06-18, v1@06-19].
    a = home("machine-a")
    items = _held_topic()
    _build(items)
    original = items[0]
    assert original.source == "arxiv" and original.content_hash == ORIG_HASH
    capsys.readouterr()  # drain the kb report
    held0 = get_item(a.db_path, original.id)  # the rendered row (carries markdown_path)

    clock = {"now": T0}
    monkeypatch.setattr(cli, "datetime", _scripted_clock(clock))
    for new_hash, archived_at, note in (
        (V1, "2026-06-18T00:00:00+00:00", "Adds a worked attention example."),
        (V2, "2026-06-19T00:00:00+00:00", "Adds the multi-head derivation."),
    ):
        clock["now"] = archived_at
        incoming = tmp_path / f"{new_hash.split(':')[1]}.jsonl"
        incoming.write_text(
            dump_items_export([_divergent_recapture(held0, new_hash, note)]),
            encoding="utf-8",
        )
        assert main(["import", "items", str(incoming), "--accept-incoming"]) == 0
        assert json.loads(capsys.readouterr().out)["adopted"] == [original.id]
    assert _archive_priors(a.db_path) == [ORIG_HASH, V1]

    # 2. The EARLIER FULL backup's recovery store (taken BEFORE the prune): the whole
    #    archive so far. This is the archive B will rebuild from — it still holds the
    #    original@06-18 that the prune will later remove from A. (B re-snapshots the
    #    holdings with the head, so it restores the *latest* `export items`, step 5a.)
    assert main(["export", "archive"]) == 0
    full_path = tmp_path / "archive-full.jsonl"
    full_path.write_text(capsys.readouterr().out, encoding="utf-8")
    assert [r["prior_hash"] for r in _read_jsonl_lines(full_path.read_text())] == [
        ORIG_HASH,
        V1,
    ]

    # 3. Adopt MORE after T0: v3@06-20 — genuine new content for the increment to
    #    carry. The archive grows to [original@06-18, v1@06-19, v2@06-20].
    clock["now"] = "2026-06-20T00:00:00+00:00"
    incoming = tmp_path / "prune-v3.jsonl"
    incoming.write_text(
        dump_items_export([_divergent_recapture(held0, V3, "Adds the positional study.")]),
        encoding="utf-8",
    )
    assert main(["import", "items", str(incoming), "--accept-incoming"]) == 0
    assert json.loads(capsys.readouterr().out)["adopted"] == [original.id]
    assert _archive_priors(a.db_path) == [ORIG_HASH, V1, V2]

    # 4. PRUNE on A: drop priors archived strictly before T0 — exactly the
    #    original@06-18 (v1@06-19 sits ON the inclusive boundary and survives). This
    #    is the retention *removal* the operator wants to propagate.
    assert main(["archive", "prune", "--before", T0, "--apply"]) == 0
    prune_report = json.loads(capsys.readouterr().out)
    assert prune_report["dropped"] == 1 and prune_report["remaining"] == 2
    assert [e["prior_hash"] for e in prune_report["archived"]] == [ORIG_HASH]
    assert _archive_priors(a.db_path) == [V1, V2]  # the original is gone from A

    # 5. Both of A's post-prune backups, taken while A is the active library:
    #
    #    (a) the INCREMENTAL backup — the latest holdings + only `export archive
    #        --since T0`. The increment carries [v1@06-19, v2@06-20]; it never had
    #        the pruned original (archived BEFORE T0 → outside the `--since` window).
    assert main(["export", "items"]) == 0
    items_inc = tmp_path / "items-inc.jsonl"
    items_inc.write_text(capsys.readouterr().out, encoding="utf-8")  # head = v3
    assert main(["export", "archive", "--since", T0]) == 0
    inc_path = tmp_path / "archive-incremental.jsonl"
    inc_path.write_text(capsys.readouterr().out, encoding="utf-8")
    assert [r["prior_hash"] for r in _read_jsonl_lines(inc_path.read_text())] == [V1, V2]

    #    (b) a FRESH FULL backup — the latest holdings + the WHOLE post-prune
    #        recovery store. It simply omits the pruned original (it's gone from A),
    #        so it is the transport that propagates the retention (used for peer C).
    assert main(["export", "items"]) == 0
    items_post = tmp_path / "items-post-prune.jsonl"
    items_post.write_text(capsys.readouterr().out, encoding="utf-8")
    assert main(["export", "archive"]) == 0
    full2_path = tmp_path / "archive-full-post-prune.jsonl"
    full2_path.write_text(capsys.readouterr().out, encoding="utf-8")
    assert [r["prior_hash"] for r in _read_jsonl_lines(full2_path.read_text())] == [V1, V2]

    # 6. Rebuild peer B from the EARLIER FULL backup + the increment. The full
    #    restores [original, v1]; the increment adds v2 and dedups v1 — B's recovery
    #    store reconstructs THREE priors, INCLUDING the original A pruned.
    b = _rebuild_peer("machine-b", items_inc, full_path, inc_path)
    assert get_item(b.db_path, original.id).content_hash == V3  # head matches A
    assert _custody()["score"] == 100  # the extra recovery prior is custody-harmless
    assert _archive_priors(b.db_path) == [ORIG_HASH, V1, V2]

    # THE BOUNDARY: A pruned the original, but B (earlier full + increment) STILL
    #    holds it — the increment is additive-only; the prune did NOT travel. A and
    #    B's recovery stores genuinely DIVERGE on the pruned prior.
    assert ORIG_HASH not in _archive_priors(a.db_path)
    assert ORIG_HASH in _archive_priors(b.db_path)
    assert _archive_priors(a.db_path) != _archive_priors(b.db_path)

    # 7. THE REMEDY: retention propagates only through a FRESH FULL backup. Peer C,
    #    rebuilt from the post-prune full backup (step 5b — which omits the original),
    #    matches A's recovery store exactly: the prune travelled.
    c = _rebuild_peer("machine-c", items_post, full2_path)
    assert get_item(c.db_path, original.id).content_hash == V3  # head still matches A
    assert _custody()["score"] == 100
    assert _archive_priors(c.db_path) == _archive_priors(a.db_path) == [V1, V2]
    assert ORIG_HASH not in _archive_priors(c.db_path)  # the prune travelled


# --- the content-identity dogfood leg (H340) ------------------------------
#
# The custody surfaces for *byte-identical holdings under different ids* shipped
# one leg at a time (H325 doctor, H327 maintain, H328 `show`, H333 the compiled
# `· also held as` marker); the untested whole is the operator *loop* the theme
# exists to serve: hold the same bytes twice → every surface names the redundancy
# → the operator prunes one copy → the count clears in lockstep. The sharp custody
# point: the act is a real `rm` the operator *chooses* — the tool never auto-merges
# a content duplicate (H325/H337: raw is sacred, two faithful copies are a
# redundancy fact, never a defect to collapse) — so the redundancy is proven
# *operator-resolvable without custody loss*, the self-healing-dogfood analogue
# (H204/H206/H210) on the content-identity axis.

# Two captures of the *same bytes* under two ids/sources/urls — a content-identity
# duplicate (H325), distinct from a URL-spelling one (same normalized url, ADR 0023).
_MIRROR_BODY = "One survey's bytes, mirrored under two ids."
_MIRROR_HASH = "sha256:byte-identical-mirror"


def _held_topic_with_a_mirror() -> tuple[list[ScrollItem], ScrollItem, ScrollItem]:
    """The held topic plus a byte-identical pair: same `content_hash`/body, two ids.

    The pair lands on its own category page (``survey``) so the compiled-page
    assertions read a row set isolated from the three unique topic scrolls — the
    surfaces must single out *only* the redundant pair, never the unique holdings.
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


def test_spot_a_content_duplicate_then_prune_clears_it_across_every_surface(
    home, capsys
):
    """*spot the redundancy → prune → it clears* (H340): the content-identity loop
    end to end across the read/render/maintain surfaces.

    Hold the same bytes under two ids and **every** surface names the *same* pair —
    `doctor`'s whole-library `custody.content_duplicates` (one group of two, H325),
    the per-item `show` `content_duplicate_ids` (each names the other, H328), the
    compiled `library/` `· also held as` marker (H333), and the `maintain`
    `_Duplicates:_` headline (H327). Then the operator runs a real `rm` on one copy
    (the chosen act — never an auto-merge; raw is sacred, H325/H337) and recompiles,
    and **all four fall to clean in one step** (zero groups, empty siblings, the
    omitted marker, the omitted line — H330's unconditional omit-when-clean: a count
    that fell *to* zero is a pruned copy, not a defect repaired). The three unique
    topic scrolls are flagged by *none* of these throughout, so the loop is a genuine
    narrowing, not a one-pair library.
    """
    src = home("library")
    items, mirror_a, mirror_b = _held_topic_with_a_mirror()
    _build(items)
    capsys.readouterr()  # drain the kb report

    survey_page = src.root / "library" / "categories" / "survey.md"

    def doctor_dups() -> dict:
        assert main(["doctor"]) == 0
        return json.loads(capsys.readouterr().out)["custody"]["content_duplicates"]

    def show_siblings(item_id: str) -> list[str]:
        assert main(["show", item_id]) == 0
        return json.loads(capsys.readouterr().out)["content_duplicate_ids"]

    def maintain_line() -> str | None:
        assert main(["maintain", "--no-recheck"]) == 0
        return json.loads(capsys.readouterr().out)["duplicates_headline"]

    # --- spot: hold two copies, every surface names the *same* pair ----------
    report = doctor_dups()
    assert report["total_groups"] == 1 and report["total_items"] == 2
    assert report["groups"] == [
        {"content_hash": _MIRROR_HASH, "ids": sorted([mirror_a.id, mirror_b.id])}
    ]
    # the per-item read names the cross-source sibling each way (a content group
    # spans sources — the whole-library scope, H328)
    assert show_siblings(mirror_a.id) == [mirror_b.id]
    assert show_siblings(mirror_b.id) == [mirror_a.id]
    # the compiled page row trails the `· also held as <sibling>` marker (H333)
    page = survey_page.read_text(encoding="utf-8")
    assert f"also held as `{mirror_b.id}`" in page  # the mirror A row names B
    assert f"also held as `{mirror_a.id}`" in page  # the mirror B row names A
    # the scheduled-pass headline names the one group of two (H327)
    assert maintain_line() == (
        "_Duplicates: 1 group(s) of byte-identical content (2 item(s))._"
    )
    # non-vacuous: a unique topic scroll is flagged by none of these
    assert show_siblings(items[0].id) == []

    # --- prune: a real `rm` the operator chooses, then recompile the views ---
    assert main(["rm", mirror_a.id]) == 0
    rm_out = json.loads(capsys.readouterr().out)
    assert rm_out["removed"] == 1 and rm_out["failed"] == 0
    assert main(["kb"]) == 0  # the compiled pages refresh on the next `kb`
    capsys.readouterr()

    # --- clears: every surface falls to clean in lockstep --------------------
    cleared = doctor_dups()
    assert cleared["total_groups"] == 0 and cleared["total_items"] == 0
    assert cleared["groups"] == []
    # the surviving copy is now unique — no sibling to name
    assert show_siblings(mirror_b.id) == []
    # the recompiled page keeps the survivor's row but drops the marker
    page = survey_page.read_text(encoding="utf-8")
    assert "Transformer Survey (mirror B)" in page  # the survivor stayed held
    assert "also held as" not in page
    # the headline is omitted entirely (H330: a fall *to* zero is a pruned copy,
    # not a defect repaired — no `▼1 / repaired` clause, the unconditional omit)
    assert maintain_line() is None


def test_skipping_the_prune_leaves_the_content_duplicate_flagged_everywhere(
    home, capsys
):
    """*the prune is what clears it* (H340, the mutation guard): recompiling and
    re-reading **without** the `rm` leaves every surface still flagging the pair —
    so the clean reads above are driven by the operator's chosen `rm`, not by the
    recompile or the re-read. A `kb` recompile is deterministic and report-only; it
    never collapses a content duplicate (H325 — only an explicit `rm` removes a
    held copy), so the redundancy persists until the operator acts.
    """
    src = home("library")
    items, mirror_a, mirror_b = _held_topic_with_a_mirror()
    _build(items)
    capsys.readouterr()

    # recompile + re-audit with no `rm` — the only change from the loop above
    assert main(["kb"]) == 0
    capsys.readouterr()

    assert main(["doctor"]) == 0
    report = json.loads(capsys.readouterr().out)["custody"]["content_duplicates"]
    assert report["total_groups"] == 1 and report["total_items"] == 2

    assert main(["show", mirror_a.id]) == 0
    assert json.loads(capsys.readouterr().out)["content_duplicate_ids"] == [mirror_b.id]

    page = (src.root / "library" / "categories" / "survey.md").read_text(
        encoding="utf-8")
    assert f"also held as `{mirror_b.id}`" in page

    assert main(["maintain", "--no-recheck"]) == 0
    assert json.loads(capsys.readouterr().out)["duplicates_headline"] == (
        "_Duplicates: 1 group(s) of byte-identical content (2 item(s))._"
    )


# --- the suggested-prune dogfood leg (H357) -------------------------------
#
# H356 turned the content-identity finding into *actionable* guidance: a per-group
# `duplicate_prunes` block naming the keep copy + the `scrolls rm` that prunes the
# rest (the content-identity counterpart of the `suggest_repairs` by-finding repair
# blocks, H40). `suggest_repairs`' guarantee is that it "never points at a command
# that would not close the gap"; the new prune guidance owes the same proof on the
# content-identity axis — run *exactly* the named `scrolls rm` and the byte-identical
# group clears, the suggestion's own keep left standing. The H340 loop pruned a copy
# the *test* chose; this one prunes the copy the *suggestion* names and asserts the
# suggestion told the truth (the named keep is the survivor) — the suggested → act →
# clear loop (H40's "the command closes the gap", H340's *act-where-the-loss-is*
# discipline) over the prune guidance, the H340/H351/H355 dogfood family's prune leg.


def test_the_suggested_prune_command_clears_the_content_duplicate(home, capsys):
    """*suggested → act → clear* (H357): `maintain` names the keep copy + the
    `scrolls rm` prune command, the operator runs *exactly that command*, and the
    byte-identical group clears with the named keep left standing.

    The `suggest_repairs` "never points at a command that would not close the gap"
    guarantee (H40) proven on the content-identity prune guidance (H356): the test
    never picks which copy to drop — it reads the suggestion's `keep`/`prune`/`command`,
    runs the command verbatim (`scrolls rm <prune ids>`), and asserts the suggestion
    told the truth — the named keep survives held, the named prune is gone, and every
    duplicates surface (`doctor`, the `_Duplicates:_` headline, the prune block itself)
    falls to clean. Report-only until the operator acts: the pass *names* the `rm`,
    never runs it (the H325 raw-is-sacred discipline — a prune is an operator choice,
    never an auto-merge).
    """
    src = home("library")
    items, mirror_a, mirror_b = _held_topic_with_a_mirror()
    _build(items)
    capsys.readouterr()  # drain the kb report

    def maintain_report() -> dict:
        assert main(["maintain", "--no-recheck"]) == 0
        return json.loads(capsys.readouterr().out)

    def doctor_dups() -> dict:
        assert main(["doctor"]) == 0
        return json.loads(capsys.readouterr().out)["custody"]["content_duplicates"]

    # --- suggested: `maintain` names one keep + the `scrolls rm` for the rest ----
    report = maintain_report()
    [prune_block] = report["duplicate_prunes"]
    assert prune_block["content_hash"] == _MIRROR_HASH
    # the suggestion partitions the group into one keep + the redundant rest, and the
    # union is exactly the held pair (converges with `doctor`'s authoritative group by
    # construction, H356) — a pair yields one keep, one prune
    assert prune_block["keep"] in (mirror_a.id, mirror_b.id)
    assert len(prune_block["prune"]) == 1
    assert sorted([prune_block["keep"], *prune_block["prune"]]) == sorted(
        [mirror_a.id, mirror_b.id]
    )
    # the headline names the same group the suggestion sits beside (H327)
    assert report["duplicates_headline"] == (
        "_Duplicates: 1 group(s) of byte-identical content (2 item(s))._"
    )
    # non-vacuous: a unique topic scroll is named by no prune block (a genuine
    # narrowing, not a one-pair library)
    assert all(
        items[0].id not in [b["keep"], *b["prune"]]
        for b in report["duplicate_prunes"]
    )

    keep = prune_block["keep"]
    [pruned] = prune_block["prune"]

    # --- act: run *exactly* the suggested command, token for token ---------------
    command = prune_block["command"].split()
    assert command[:2] == ["scrolls", "rm"]  # the named act is a `scrolls rm`
    assert command[2:] == prune_block["prune"]  # listing every redundant copy
    assert main(command[1:]) == 0  # `scrolls <argv>` → run `rm <prune ids>` verbatim
    rm_out = json.loads(capsys.readouterr().out)
    assert rm_out["removed"] == 1 and rm_out["failed"] == 0

    # --- clears: the named keep stood, the named prune is gone, all surfaces clean -
    assert get_item(src.db_path, keep) is not None  # the suggestion's keep survived
    assert get_item(src.db_path, pruned) is None  # the suggestion's prune is gone
    cleared = doctor_dups()
    assert cleared["total_groups"] == 0 and cleared["total_items"] == 0
    after = maintain_report()
    assert after["duplicate_prunes"] == []  # nothing left to prune
    # H330's unconditional omit-when-clean: a fall *to* zero is a pruned copy, not a
    # defect repaired — the line is dropped (no `▼1 / repaired` clause), even though
    # this `maintain` run *does* see a delta (1 → 0 groups since the prior pass)
    assert after["duplicates_headline"] is None


def test_skipping_the_suggested_prune_leaves_the_block_and_the_finding(home, capsys):
    """*the prune is what clears it* (H357, the mutation guard): re-auditing with
    `maintain` **without** running the suggested `rm` leaves the same prune block —
    same keep, same `scrolls rm` command — and `doctor` still flagging the pair, both
    copies still held. So the clean reads above are driven by the operator running the
    named command, not by the re-audit. The pass is report-only: it *names* the `rm`,
    never executes it (H325/H356), so the redundancy and its guidance persist until
    the operator chooses to prune.
    """
    src = home("library")
    items, mirror_a, mirror_b = _held_topic_with_a_mirror()
    _build(items)
    capsys.readouterr()

    # re-audit with no `rm` — the only change from the loop above
    assert main(["maintain", "--no-recheck"]) == 0
    report = json.loads(capsys.readouterr().out)

    [block] = report["duplicate_prunes"]
    assert block["content_hash"] == _MIRROR_HASH
    assert sorted([block["keep"], *block["prune"]]) == sorted(
        [mirror_a.id, mirror_b.id]
    )
    assert block["command"] == "scrolls rm " + " ".join(block["prune"])
    assert report["duplicates_headline"] == (
        "_Duplicates: 1 group(s) of byte-identical content (2 item(s))._"
    )

    # `doctor` still flags the pair, and BOTH copies are still held — the pass named
    # the `rm` but never ran it
    assert main(["doctor"]) == 0
    dupes = json.loads(capsys.readouterr().out)["custody"]["content_duplicates"]
    assert dupes["total_groups"] == 1 and dupes["total_items"] == 2
    assert get_item(src.db_path, mirror_a.id) is not None
    assert get_item(src.db_path, mirror_b.id) is not None


# --- the compiled-surface dogfood leg (H351, rescoped) --------------------
#
# H340 ran the *spot → prune → clear* loop over the live read surfaces
# (`doctor`/`show` JSON, the `maintain` JSON headline) and a category page's
# `· also held as` marker. The one content-identity surface that loop never
# opened is the **compiled `library/index.md` file itself** — the static landing
# artifact a human or an agent actually opens — and its whole-library
# `_Duplicates:_` line (H334, the compiled counterpart of the `maintain` headline,
# folded by the *same* `render_content_duplicates`). This leg runs the same loop
# over that compiled artifact: the landing line + the H333 per-row markers name the
# redundancy after `kb`, a real `rm` + recompile clears both in lockstep, and a
# recompile *without* the `rm` leaves both flagged (the prune, not the recompile,
# drives the clear). RESCOPE (2026-06-25): the queued group-page `_Duplicates:_`
# headline (H349) was declined, so this reads the landing line (H334) + the per-row
# markers (H333) on a compiled list page, never a group-page headline.

# The exact landing/`maintain` line for the one mirror group of two (rendered by
# the shared `render_content_duplicates`, so it reads byte-identical on every
# surface — `doctor`, `maintain`, the bundle/context briefings, and `index.md`).
_DUP_LINE = "_Duplicates: 1 group(s) of byte-identical content (2 item(s))._"


def test_the_compiled_landing_page_names_then_drops_the_content_duplicate(
    home, capsys
):
    """*compile → the landing `index.md` names the redundancy → prune → recompile
    → it clears* (H351): the content-identity dogfood loop over the **compiled
    `library/` artifact a human or agent actually opens**, the compile-surface
    analogue of the H340 read/render/maintain loop.

    Where H340 read the live `doctor`/`maintain` JSON and a category page, this
    reads the *static compiled* landing surface — the whole-library `_Duplicates:_`
    line on `library/index.md` (H334) and the per-row `· also held as` marker (H333)
    on a compiled list page (`concepts/transformer.md`, which also carries the three
    unique topic scrolls, so the markers are a genuine narrowing — they name *only*
    the mirror pair). A real `rm` of one copy + a `kb` recompile then clears **both
    the landing line and the markers in one step** (H330's unconditional
    omit-when-clean: a count fallen *to* zero is a pruned copy, not a defect
    repaired — no `▼1 / repaired` clause).
    """
    src = home("library")
    items, mirror_a, mirror_b = _held_topic_with_a_mirror()
    _build(items)
    capsys.readouterr()  # drain the kb report

    index_md = src.root / "library" / "index.md"
    # the concept page heads every Transformer scroll (the 3 unique topic holds +
    # the mirror pair), so the markers must single out *only* the redundant pair
    concept_md = src.root / "library" / "concepts" / "transformer.md"

    # --- compile: the landing page + the compiled rows name the redundancy ----
    index = index_md.read_text(encoding="utf-8")
    assert _DUP_LINE in index  # the whole-library landing line (H334)
    concept = concept_md.read_text(encoding="utf-8")
    assert f"also held as `{mirror_b.id}`" in concept  # the mirror A row names B
    assert f"also held as `{mirror_a.id}`" in concept  # the mirror B row names A
    # non-vacuous: a unique topic scroll on the *same* page is never named a sibling
    assert f"also held as `{items[0].id}`" not in concept
    assert items[0].title in concept  # …but it is on the page, just unmarked

    # --- prune: a real `rm` the operator chooses, then recompile the views ----
    assert main(["rm", mirror_a.id]) == 0
    rm_out = json.loads(capsys.readouterr().out)
    assert rm_out["removed"] == 1 and rm_out["failed"] == 0
    assert main(["kb"]) == 0  # the compiled pages refresh on the next `kb`
    capsys.readouterr()

    # --- clears: the landing line and the markers fall to clean in lockstep ---
    index = index_md.read_text(encoding="utf-8")
    assert "_Duplicates:" not in index  # omitted entirely (H330) — no `0 group(s)`
    concept = concept_md.read_text(encoding="utf-8")
    assert mirror_b.title in concept  # the survivor stayed held + rendered
    assert "also held as" not in concept  # the marker dropped with the redundancy


def test_skipping_the_prune_leaves_the_compiled_landing_line_and_markers(
    home, capsys
):
    """*the prune is what clears it* (H351, the mutation guard): recompiling with
    `kb` **without** the `rm` leaves the landing `_Duplicates:_` line and the
    per-row markers both still flagging the pair — so the clean compiled reads above
    are driven by the operator's chosen `rm`, not by the recompile. `kb` is
    deterministic and report-only; it never collapses a content duplicate (H325 —
    only an explicit `rm` removes a held copy), so the redundancy persists on the
    compiled artifact until the operator acts.
    """
    src = home("library")
    items, mirror_a, mirror_b = _held_topic_with_a_mirror()
    _build(items)
    capsys.readouterr()

    # recompile with no `rm` — the only change from the loop above
    assert main(["kb"]) == 0
    capsys.readouterr()

    index = (src.root / "library" / "index.md").read_text(encoding="utf-8")
    assert _DUP_LINE in index  # the landing line still flags the pair
    concept = (src.root / "library" / "concepts" / "transformer.md").read_text(
        encoding="utf-8"
    )
    assert f"also held as `{mirror_b.id}`" in concept
    assert f"also held as `{mirror_a.id}`" in concept


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
