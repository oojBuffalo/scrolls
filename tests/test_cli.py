"""Tests for the `scrolls` CLI entry point."""

import dataclasses
import json

import pytest

import scrolls.sources.wikipedia as wikipedia
import scrolls.sources.youtube as youtube
from scrolls.classify import RULESET_FINGERPRINT, stale_classifications
from scrolls.cli import main
from scrolls.custody import (
    CustodyEvent,
    conflict_event,
    custody_counts_by_source,
    custody_headline,
    latest_events,
    record_events,
)
from scrolls.db import SCHEMA_VERSION
from scrolls.doctor import run_doctor
from scrolls.feeds import Subscription, insert_subscription, list_subscriptions
from scrolls.maintain import (
    custody_snapshot,
    report_by_source,
    report_enrichment_by_source,
    report_summary_by_source,
    snapshot_headline,
    weakest_source,
)
from scrolls.paths import get_paths
from scrolls.items import (
    ScrollItem,
    adopt_incoming,
    archived_records,
    archived_snapshots,
    delete_item,
    get_item,
    insert_item,
    latest_archived,
    list_archived,
    list_items,
    make_item_id,
    update_item,
)
from scrolls.items_export import dump_items_export
from scrolls.render import write_scroll
from scrolls.sources import FETCH_ADAPTERS


def _as_download(fake):
    """Adapt a `url -> bytes` fake to the `(payload, size)` download seam."""

    def download(url, *, max_bytes=None):
        payload = fake(url)
        return payload, len(payload)

    return download

@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


def test_detect_prints_json(capsys):
    exit_code = main(["detect", "https://youtu.be/dQw4w9WgXcQ"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"source": "youtube", "source_id": "dQw4w9WgXcQ"}


def test_detect_web_fallback_has_null_source_id(capsys):
    exit_code = main(["detect", "https://example.com/post"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"source": "web", "source_id": None}


def test_detect_rejects_non_http_url(capsys):
    exit_code = main(["detect", "ftp://example.com/file"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_no_command_exits_with_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


def test_paths_prints_layout_json(scrolls_home, capsys):
    exit_code = main(["paths"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "root": str(scrolls_home),
        "items": str(scrolls_home / "items"),
        "scrolls": str(scrolls_home / "scrolls"),
        "library": str(scrolls_home / "library"),
        "media": str(scrolls_home / "media"),
        "agents": str(scrolls_home / "agents"),
        "db": str(scrolls_home / "db.sqlite"),
        "config": str(scrolls_home / "config.toml"),
    }


def test_init_creates_library_skeleton(scrolls_home, capsys):
    exit_code = main(["init"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"root": str(scrolls_home), "created": True}
    for subdir in ("items", "scrolls", "library", "media", "agents"):
        assert (scrolls_home / subdir).is_dir()
    assert (scrolls_home / "db.sqlite").is_file()
    assert (scrolls_home / "config.toml").is_file()


def test_init_is_idempotent_and_preserves_config(scrolls_home, capsys):
    main(["init"])
    config = scrolls_home / "config.toml"
    config.write_text("# user edits must survive re-init\n")
    capsys.readouterr()

    exit_code = main(["init"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"root": str(scrolls_home), "created": False}
    assert config.read_text() == "# user edits must survive re-init\n"


_EMPTY_COUNTS = {
    "total": 0,
    "by_stage": {"detected": 0, "fetched": 0, "rendered": 0},
    "by_source": {},
    "unclassified": 0,
}


def _custody_headline(score):
    """The status custody block for a library with no findings/drift/staleness.

    `score` is `null` before `init` (no store) and `100` for an empty but
    initialized library — mirroring `run_doctor`'s own missing-vs-empty split.
    """
    return {
        "score": score,
        "tiers": {"full": 0, "partial": 0, "reference": 0},
        "drift": {
            "checked": 0,
            "unverified": 0,
            "unchanged": 0,
            "drifted": 0,
            "rotted": 0,
            "error": 0,
        },
        # the snapshot's recheck-coverage fraction (H115): an empty/uninitialized
        # library has no verifiable held items, so the honest zeroed coverage
        "coverage": {"verified": 0, "total": 0},
        "enrichment_stale": 0,
        "summaries_stale": 0,
        # the at-risk-works count (H267): no multi-rep work held → none at risk
        "at_risk": 0,
        # the unresolved import-conflict count (H279): an empty/uninitialized
        # library has recorded no divergence → the honest 0
        "conflicts": 0,
        # the archive-integrity mismatch count (H298): no archived prior → the
        # honest 0 (a clean recovery store)
        "archive_mismatched": 0,
        # the content-duplicate redundancy scalars (H327): an empty/uninitialized
        # library holds no byte-identical content → the honest 0s
        "content_duplicate_groups": 0,
        "content_duplicate_items": 0,
        # the whole-library posture verdict (H370): an empty/uninitialized library
        # holds nothing to lose → the honest `sound`/empty skeleton default
        "posture": {"verdict": "sound", "reasons": []},
    }


def test_status_before_init(scrolls_home, capsys):
    exit_code = main(["status"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "initialized": False,
        "root": str(scrolls_home),
        "schema_version": None,
        "items": _EMPTY_COUNTS,
        "subscriptions": 0,
        # no store yet → the custody score is honestly null, not a fabricated 100
        "custody": _custody_headline(None),
        # the rendered one-liner (H117): no held scrolls → the honest empty form
        "headline": "_Custody: 0 scroll(s)._",
        # the per-source breakdown (H133): no sources held → the honest empty map
        "by_source": {},
        # the weakest-source flag (H139): nothing held → nothing stands out
        "attention": None,
        # the per-source refresh-debt maps (H177): no store → the honest empty maps
        "enrichment_by_source": {},
        "summary_by_source": {},
    }


def test_status_after_init(scrolls_home, capsys):
    main(["init"])
    capsys.readouterr()

    exit_code = main(["status"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "initialized": True,
        "root": str(scrolls_home),
        "schema_version": SCHEMA_VERSION,
        "items": _EMPTY_COUNTS,
        "subscriptions": 0,
        # an empty-but-initialized library is trivially fully custodied (100),
        # the same "empty is healthy" doctor reports
        "custody": _custody_headline(100),
        # the rendered one-liner (H117): an empty library still holds no scrolls
        "headline": "_Custody: 0 scroll(s)._",
        # the per-source breakdown (H133): no sources held → the honest empty map
        "by_source": {},
        # the weakest-source flag (H139): nothing held → nothing stands out
        "attention": None,
        # the per-source refresh-debt maps (H177): empty library → honest empty maps
        "enrichment_by_source": {},
        "summary_by_source": {},
    }


def test_status_custody_headline_converges_with_doctor(scrolls_home, capsys):
    """The custody headline is the same `run_doctor` custody view, distilled —
    so `status` can never disagree with `doctor` (the H21/H25 convergence)."""
    # A fidelity mix the headline must report: two full-fidelity rendered scrolls
    # and one reference-only pointer (no content held).
    paths = get_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    from scrolls.db import init_db

    init_db(paths.db_path)
    full = ScrollItem(
        id=make_item_id("web", None, "https://example.com/held"),
        source="web",
        source_id=None,
        url="https://example.com/held",
        saved_at="2026-06-14T00:00:00+00:00",
        extracted_text="A fully held capture we can re-derive.",
        content_hash="sha256:held1234",
        stage="rendered",
        provenance={"adapter": "web", "fetched_at": "2026-06-14T00:00:05+00:00"},
    )
    drifting = ScrollItem(
        id=make_item_id("web", None, "https://example.com/moved"),
        source="web",
        source_id=None,
        url="https://example.com/moved",
        saved_at="2026-06-14T00:00:00+00:00",
        extracted_text="A capture whose source has since drifted.",
        content_hash="sha256:moved567",
        stage="rendered",
        provenance={"adapter": "web", "fetched_at": "2026-06-14T00:00:05+00:00"},
    )
    reference = ScrollItem(
        id=make_item_id("web", None, "https://example.com/pointer"),
        source="web",
        source_id=None,
        url="https://example.com/pointer",
        saved_at="2026-06-14T00:00:00+00:00",
        stage="detected",
        provenance={"adapter": "web"},
    )
    for item in (full, drifting, reference):
        insert_item(paths.db_path, write_scroll(paths, item))
    # one recorded drift verdict so the headline's drift posture is non-trivial
    record_events(
        paths.db_path,
        [
            CustodyEvent(
                drifting.id, "2026-06-15T00:00:00+00:00", "drifted",
                "sha256:moved567", "sha256:changed99", None,
            )
        ],
    )
    capsys.readouterr()

    assert main(["status"]) == 0
    custody = json.loads(capsys.readouterr().out)["custody"]

    # convergence by construction: the headline IS the doctor custody view distilled
    report = run_doctor(paths)
    assert custody == custody_snapshot(report)
    # and it is the concrete, non-trivial posture doctor reports for this scope
    assert custody["score"] == report["custody"]["score"]
    assert custody["tiers"] == {"full": 2, "partial": 0, "reference": 1}
    assert custody["drift"]["drifted"] == 1
    assert custody["drift"]["unverified"] == 2  # the two never-rechecked scrolls


def test_status_carries_rendered_headline_converging_with_the_block(
    scrolls_home, capsys
):
    """`status` carries the one-line `headline` string (H117) beside its custody
    block, rendered from the same snapshot — so the rendered line, the structured
    block, and the shared `custody_headline` over the held library all agree."""
    paths = get_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    from scrolls.db import init_db

    init_db(paths.db_path)
    full = ScrollItem(
        id=make_item_id("web", None, "https://example.com/held"),
        source="web",
        source_id=None,
        url="https://example.com/held",
        saved_at="2026-06-14T00:00:00+00:00",
        extracted_text="A fully held capture we can re-derive.",
        content_hash="sha256:held1234",
        stage="rendered",
        provenance={"adapter": "web", "fetched_at": "2026-06-14T00:00:05+00:00"},
    )
    reference = ScrollItem(
        id=make_item_id("web", None, "https://example.com/pointer"),
        source="web",
        source_id=None,
        url="https://example.com/pointer",
        saved_at="2026-06-14T00:00:00+00:00",
        stage="detected",
        provenance={"adapter": "web"},
    )
    for item in (full, reference):
        insert_item(paths.db_path, write_scroll(paths, item))
    record_events(
        paths.db_path,
        [
            CustodyEvent(
                full.id, "2026-06-15T00:00:00+00:00", "unchanged",
                "sha256:held1234", "sha256:held1234", None,
            )
        ],
    )
    capsys.readouterr()

    assert main(["status"]) == 0
    payload = json.loads(capsys.readouterr().out)

    # the rendered headline is the snapshot block it sits beside, rendered
    assert payload["headline"] == snapshot_headline(payload["custody"])
    # …and the shared formatter over the held library + the live ledger agrees
    assert payload["headline"] == custody_headline(
        list_items(paths.db_path), latest_events(paths.db_path)
    )
    # the concrete, non-trivial line this fidelity/drift mix produces
    assert payload["headline"] == (
        "_Custody: 2 scroll(s) · fidelity full 1, reference 1 "
        "· drift verified 1, unverified 1._"
    )


def test_status_by_source_breakdown_converges_with_doctor(scrolls_home, capsys):
    """`status` carries the per-source custody breakdown (H133) — the per-source
    split of the `custody` block beside it — read faithfully from the same
    `run_doctor` audit `status` already makes, so it equals `doctor`'s own
    `custody.by_source`, `custody_counts_by_source` over the held items, and sums
    to the whole-library `custody` block."""
    paths = get_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    from scrolls.db import init_db

    init_db(paths.db_path)
    # a two-source mix: a held + drifted `web` pair, plus one `arxiv` paper.
    held = ScrollItem(
        id=make_item_id("web", None, "https://example.com/held"),
        source="web",
        source_id=None,
        url="https://example.com/held",
        saved_at="2026-06-14T00:00:00+00:00",
        extracted_text="A fully held web capture.",
        content_hash="sha256:webheld",
        stage="rendered",
        provenance={"adapter": "web", "fetched_at": "2026-06-14T00:00:05+00:00"},
    )
    moved = ScrollItem(
        id=make_item_id("web", None, "https://example.com/moved"),
        source="web",
        source_id=None,
        url="https://example.com/moved",
        saved_at="2026-06-14T00:00:00+00:00",
        extracted_text="A web capture whose source drifted.",
        content_hash="sha256:webmoved",
        stage="rendered",
        provenance={"adapter": "web", "fetched_at": "2026-06-14T00:00:05+00:00"},
    )
    paper = ScrollItem(
        id="arxiv:2401.00001",
        source="arxiv",
        source_id="2401.00001",
        url="https://arxiv.org/abs/2401.00001",
        saved_at="2026-06-14T00:00:00+00:00",
        extracted_text="An arxiv paper held in full.",
        content_hash="sha256:arxivpaper",
        stage="rendered",
        provenance={"adapter": "arxiv", "fetched_at": "2026-06-14T00:00:05+00:00"},
    )
    for item in (held, moved, paper):
        insert_item(paths.db_path, write_scroll(paths, item))
    record_events(
        paths.db_path,
        [
            CustodyEvent(
                held.id, "2026-06-15T00:00:00+00:00", "unchanged",
                "sha256:webheld", "sha256:webheld", None,
            ),
            CustodyEvent(
                moved.id, "2026-06-15T00:00:00+00:00", "drifted",
                "sha256:webmoved", "sha256:changed99", None,
            ),
        ],
    )
    capsys.readouterr()

    assert main(["status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    by_source = payload["by_source"]

    # both sources present, keys sorted (arxiv before web)
    assert list(by_source) == ["arxiv", "web"]

    report = run_doctor(paths)
    # 1. == a faithful read of the audit `status` already makes (no new audit)
    assert by_source == report_by_source(report)
    # 2. == doctor's own `custody.by_source` over the same library
    assert by_source == report["custody"]["by_source"]
    # 3. == the canonical per-source tally over the held items
    assert by_source == custody_counts_by_source(
        list_items(paths.db_path), latest_events(paths.db_path)
    )

    # 4. the concrete, non-trivial per-source picture this seed produces
    assert by_source["web"]["tiers"] == {"full": 2, "partial": 0, "reference": 0}
    assert by_source["web"]["drift"]["verified"] == 1
    assert by_source["web"]["drift"]["drifted"] == 1
    assert by_source["arxiv"]["tiers"] == {"full": 1, "partial": 0, "reference": 0}
    assert by_source["arxiv"]["drift"]["unverified"] == 1

    # 5. the per-source tallies sum to the `custody` block beside them (H104
    #    sum-to-whole, per source — so `status`'s two members can never disagree)
    summed_tiers = {tier: 0 for tier in ("full", "partial", "reference")}
    for entry in by_source.values():
        for tier, n in entry["tiers"].items():
            summed_tiers[tier] += n
    assert summed_tiers == payload["custody"]["tiers"]


def _status_custody_seed(paths):
    """A two-source library where `web` carries the only actionable loss.

    `web`: one held-unchanged + one drifted (the loss). `arxiv`: one held,
    never re-checked. So `web` is the unambiguous weakest source `attention`
    must flag, `arxiv` carries none — the multi-source picture H139 needs.
    """
    from scrolls.db import init_db

    paths.root.mkdir(parents=True, exist_ok=True)
    init_db(paths.db_path)
    held = ScrollItem(
        id=make_item_id("web", None, "https://example.com/held"),
        source="web",
        source_id=None,
        url="https://example.com/held",
        saved_at="2026-06-14T00:00:00+00:00",
        extracted_text="A fully held web capture.",
        content_hash="sha256:webheld",
        stage="rendered",
        provenance={"adapter": "web", "fetched_at": "2026-06-14T00:00:05+00:00"},
    )
    moved = ScrollItem(
        id=make_item_id("web", None, "https://example.com/moved"),
        source="web",
        source_id=None,
        url="https://example.com/moved",
        saved_at="2026-06-14T00:00:00+00:00",
        extracted_text="A web capture whose source drifted.",
        content_hash="sha256:webmoved",
        stage="rendered",
        provenance={"adapter": "web", "fetched_at": "2026-06-14T00:00:05+00:00"},
    )
    paper = ScrollItem(
        id="arxiv:2401.00001",
        source="arxiv",
        source_id="2401.00001",
        url="https://arxiv.org/abs/2401.00001",
        saved_at="2026-06-14T00:00:00+00:00",
        extracted_text="An arxiv paper held in full.",
        content_hash="sha256:arxivpaper",
        stage="rendered",
        provenance={"adapter": "arxiv", "fetched_at": "2026-06-14T00:00:05+00:00"},
    )
    for item in (held, moved, paper):
        insert_item(paths.db_path, write_scroll(paths, item))
    record_events(
        paths.db_path,
        [
            CustodyEvent(
                held.id, "2026-06-15T00:00:00+00:00", "unchanged",
                "sha256:webheld", "sha256:webheld", None,
            ),
            CustodyEvent(
                moved.id, "2026-06-15T00:00:00+00:00", "drifted",
                "sha256:webmoved", "sha256:changed99", None,
            ),
        ],
    )
    return moved


def test_status_attention_names_the_weakest_source(scrolls_home, capsys):
    """`status` carries an `attention` flag (H139) — the single source with the most
    actionable loss, distilled from the per-source breakdown via the same
    `weakest_source` primitive `maintain`'s `attention` uses (H119), so a human
    reading `status` sees *which* source most needs action, plus the recheck command
    (H137). Derived from the audit `status` already makes — no new ledger read — so it
    equals `maintain`'s `attention` for the same state."""
    paths = get_paths()
    _status_custody_seed(paths)  # `web` carries the only drift; `arxiv` is clean
    capsys.readouterr()

    assert main(["status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    attention = payload["attention"]

    # the flag names the weakest source, carries its own tally + reason + command
    assert attention is not None
    assert attention["source"] == "web"
    assert attention["drift"]["drifted"] == 1
    assert attention["reason"] == "1 drifted"
    # H137: the exact recheck command (a recheck, not a `doctor --fix` repair)
    assert attention["command"] == "scrolls verify --source web"
    # the flagged tally == the `by_source` entry beside it (status's two members agree)
    assert attention["tiers"] == payload["by_source"]["web"]["tiers"]
    assert attention["drift"] == payload["by_source"]["web"]["drift"]
    # == the same `weakest_source` over `maintain`'s faithful read of the audit
    assert attention == weakest_source(report_by_source(run_doctor(paths)))


def test_status_attention_is_null_when_nothing_stands_out(scrolls_home, capsys):
    """The honest-`null` gates (H139/H119): `attention` flags only a source that
    *stands out* across sources, so a single-source library (even with drift — the
    whole-library `custody` block already says everything) and a fully-clean
    multi-source library both report `null`."""
    from scrolls.db import init_db

    paths = get_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    init_db(paths.db_path)
    # one source, with a drift — but nothing to discriminate across, so null
    held = ScrollItem(
        id=make_item_id("web", None, "https://example.com/held"),
        source="web",
        source_id=None,
        url="https://example.com/held",
        saved_at="2026-06-14T00:00:00+00:00",
        extracted_text="A held web capture.",
        content_hash="sha256:onlyweb",
        stage="rendered",
        provenance={"adapter": "web", "fetched_at": "2026-06-14T00:00:05+00:00"},
    )
    insert_item(paths.db_path, write_scroll(paths, held))
    record_events(
        paths.db_path,
        [
            CustodyEvent(
                held.id, "2026-06-15T00:00:00+00:00", "drifted",
                "sha256:onlyweb", "sha256:changed99", None,
            )
        ],
    )
    capsys.readouterr()
    assert main(["status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # one source carrying drift → still null (no cross-source discrimination)
    assert list(payload["by_source"]) == ["web"]
    assert payload["by_source"]["web"]["drift"]["drifted"] == 1
    assert payload["attention"] is None


def test_status_source_scopes_the_whole_payload_to_one_source(scrolls_home, capsys):
    """`scrolls status --source <S>` (H166) scopes the whole status read to one
    source's held items — the status-surface counterpart of `doctor --source`
    (H162) and the read-side sibling of the per-source act commands (`verify
    --source` H125). Every block is the one-source view: the `items` counts, the
    `custody` headline, the `by_source` map (collapsed to the singleton `{S: …}`),
    and the rendered `headline` — and the `attention` flag is `null` (a single
    source has nothing to discriminate across, the `weakest_source` gate)."""
    paths = get_paths()
    _status_custody_seed(paths)  # web: held + drifted; arxiv: one held paper
    capsys.readouterr()

    assert main(["status", "--source", "web"]) == 0
    payload = json.loads(capsys.readouterr().out)

    # 1. the custody block is web's view, == the whole-library by_source[web] slice
    whole = run_doctor(paths)["custody"]["by_source"]["web"]
    custody = payload["custody"]
    assert custody["tiers"] == whole["tiers"] == {"full": 2, "partial": 0, "reference": 0}
    # the snapshot's ledger-vocab drift maps to the by_source posture vocab
    assert custody["drift"]["unchanged"] == whole["drift"]["verified"] == 1
    assert custody["drift"]["drifted"] == whole["drift"]["drifted"] == 1
    assert custody["coverage"] == whole["coverage"]
    # the whole block == the scoped doctor audit distilled (convergence by construction)
    assert custody == custody_snapshot(run_doctor(paths, source="web"))

    # 2. by_source collapses to the present-and-singleton {web: …}
    assert list(payload["by_source"]) == ["web"]
    assert payload["by_source"]["web"] == whole

    # 3. the rendered headline is web's, and names only web's two held scrolls
    assert payload["headline"] == snapshot_headline(custody)
    assert payload["headline"] == (
        "_Custody: 2 scroll(s) · fidelity full 2 · drift verified 1, drifted 1._"
    )

    # 4. the items count block narrows to web too (the whole payload is one-source)
    assert payload["items"]["total"] == 2
    assert payload["items"]["by_source"] == {"web": 2}
    assert payload["items"]["by_stage"] == {"detected": 0, "fetched": 0, "rendered": 2}

    # 5. attention is null under a single-source scope (nothing stands out)
    assert payload["attention"] is None


def test_status_source_unknown_is_the_honest_empty_headline(scrolls_home, capsys):
    """An unknown source holds nothing, so `status --source <ghost>` is the honest
    empty headline (`_Custody: 0 scroll(s)._`, score 100 for an initialized library),
    never an error — the H162 unknown-source posture on the status surface."""
    paths = get_paths()
    _status_custody_seed(paths)
    capsys.readouterr()

    assert main(["status", "--source", "ghost"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["items"]["total"] == 0
    assert payload["items"]["by_source"] == {}
    assert payload["custody"]["tiers"] == {"full": 0, "partial": 0, "reference": 0}
    assert payload["by_source"] == {}
    assert payload["headline"] == "_Custody: 0 scroll(s)._"
    assert payload["attention"] is None


def test_status_source_before_init_is_the_empty_payload(scrolls_home, capsys):
    """Before `init` the store holds nothing, so `--source` is moot — the payload is
    the same honest empty form `status` reports without a source (no crash on a
    missing store)."""
    assert main(["status", "--source", "web"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["initialized"] is False
    assert payload["items"] == _EMPTY_COUNTS
    assert payload["custody"]["score"] is None
    assert payload["headline"] == "_Custody: 0 scroll(s)._"
    assert payload["by_source"] == {}
    assert payload["attention"] is None


# --- per-source refresh-debt maps on `status` (roadmap H177) -----------------
#
# `maintain` names *which* source's `classify --stale`/`kb --stale` to run via
# `enrichment_by_source` (H147) / `summary_by_source` (H175), but those refresh-debt
# maps rode only the scheduled-worker report. `status` — the agent's *primary* read
# surface — now carries the same two maps as faithful reads of the `run_doctor`
# audit `_cmd_status` already makes (no new audit, no new ledger read), so the agent
# reading `status` names per-source refresh debt at parity with the worker.


def _mark_stale_classified(item_id):
    """Stamp a persisted item rules-classified under a *superseded* ruleset, so the
    live ruleset reads it stale (the `doctor`/`maintain` stale-classification fixture)."""
    persisted = get_item(get_paths().db_path, item_id)
    update_item(
        get_paths().db_path,
        dataclasses.replace(
            persisted,
            provenance={
                **persisted.provenance,
                "classified_by": "rules-v1",
                "classified_basis": "title-pattern",
                "classified_ruleset": "deadbeef0000",  # superseded by the live ruleset
            },
        ),
    )


def _concept_member(source, slug, concept) -> ScrollItem:
    """A minimal rendered cluster member carrying one concept (stale-summary fixture)."""
    return ScrollItem(
        id=make_item_id(source, None, f"https://{source}.example.com/{slug}"),
        source=source,
        source_id=None,
        url=f"https://{source}.example.com/{slug}",
        saved_at="2026-06-14T00:00:00+00:00",
        title=slug,
        extracted_text="A note about the concept.",
        content_hash="sha256:" + slug[-8:],
        concepts=(concept,),
        stage="rendered",
        provenance={"adapter": source, "fetched_at": "2026-06-14T00:00:05+00:00"},
    )


def _store_stale_summary(slug, display) -> None:
    """Store a concept summary whose fingerprint no longer matches its live cluster,
    so the live ruleset reads it stale (the summary-axis stale fixture)."""
    from scrolls.kb import ConceptSummary, save_concept_summary

    save_concept_summary(get_paths().db_path, ConceptSummary(
        slug=slug, display=display, summary="How it shows up.",
        members_hash="stale-old-digest", engine="kb-llm-v1",
        model="claude-opus-4-8", generated_at="2026-06-16T00:00:00+00:00"))


def _seed_refresh_debt(paths):
    """A two-source library carrying both stale-classification and stale-summary debt.

    Stale classifications: arxiv:1, web:2 (each item one source → sums to whole).
    Stale summaries: a Bm25 concept over a web+arxiv cluster (attributes to BOTH) and
    a Vector concept over a web-only cluster — so `summary_by_source` is {arxiv:1, web:2}
    while only 2 summaries are stale (the H171 double-attribution asymmetry)."""
    from scrolls.db import init_db

    paths.root.mkdir(parents=True, exist_ok=True)
    init_db(paths.db_path)
    members = [
        _concept_member("web", "bm25-web", "Bm25"),
        _concept_member("arxiv", "bm25-arxiv", "Bm25"),
        _concept_member("web", "vector-1", "Vector"),
        _concept_member("web", "vector-2", "Vector"),
    ]
    for item in members:
        insert_item(paths.db_path, write_scroll(paths, item))
    assert main(["kb"]) == 0
    # stale classifications on arxiv (1) + web (2)
    _mark_stale_classified(members[1].id)  # arxiv
    _mark_stale_classified(members[0].id)  # web
    _mark_stale_classified(members[2].id)  # web
    # stale summaries spanning the clusters
    _store_stale_summary("bm25", "Bm25")
    _store_stale_summary("vector", "Vector")


def test_status_carries_per_source_refresh_debt_maps(scrolls_home, capsys):
    """`status` carries `enrichment_by_source` + `summary_by_source` (H177) — the
    per-source stale-classification / stale-summary debt maps `maintain` names
    (H147/H175), read faithfully from the same `run_doctor` audit `status` already
    makes, so they equal `doctor`'s own maps and `maintain`'s. The agent's primary
    read surface names which source's `classify --stale`/`kb --stale` to run."""
    paths = get_paths()
    _seed_refresh_debt(paths)
    capsys.readouterr()

    assert main(["status"]) == 0
    payload = json.loads(capsys.readouterr().out)

    enrichment = payload["enrichment_by_source"]
    summary = payload["summary_by_source"]

    # offenders-only, sorted source keys; the concrete per-source debt this seed makes
    assert enrichment == {"arxiv": 1, "web": 2}
    assert summary == {"arxiv": 1, "web": 2}

    # 1. == a faithful read of the audit `status` already makes (no new audit)
    report = run_doctor(paths)
    assert enrichment == report_enrichment_by_source(report)
    assert summary == report_summary_by_source(report)
    # 2. == doctor's own maps over the same library
    assert enrichment == report["custody"]["enrichment"]["by_source"]
    assert summary == report["custody"]["summaries"]["by_source"]


def test_status_refresh_debt_summary_need_not_sum_to_the_whole(scrolls_home, capsys):
    """The H171 asymmetry, carried faithfully onto `status`: the enrichment map sums
    to the whole-library `enrichment_stale` (each item one source), but the summary
    map can exceed `summaries_stale` because a multi-source concept is attributed to
    every contributing source — so the status↔doctor tie is faithful-read equality,
    never a sum-to-whole check."""
    paths = get_paths()
    _seed_refresh_debt(paths)
    capsys.readouterr()
    assert main(["status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    report = run_doctor(paths)

    # enrichment: one source per item → sums to the whole scalar
    assert sum(payload["enrichment_by_source"].values()) == 3
    assert report["custody"]["enrichment"]["stale"] == 3
    # summary: Bm25 double-attributed (web + arxiv) → exceeds the whole scalar
    assert report["custody"]["summaries"]["stale"] == 2
    assert sum(payload["summary_by_source"].values()) == 3 > 2


def test_status_refresh_debt_maps_are_empty_on_a_clean_library(scrolls_home, capsys):
    """No stale debt → the honest empty maps (offenders-only — a source with no stale
    classifications/summaries is omitted, never a 0 entry)."""
    paths = get_paths()
    _status_custody_seed(paths)  # held items, categories never rules-stamped → not stale
    capsys.readouterr()
    assert main(["status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["enrichment_by_source"] == {}
    assert payload["summary_by_source"] == {}


def test_status_refresh_debt_maps_are_empty_before_init(scrolls_home, capsys):
    """Before `init` the store holds nothing, so both refresh-debt maps are the honest
    empty `{}` — the first-run honesty the rest of the payload already keeps, never a
    KeyError on the absent audit block."""
    assert main(["status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["initialized"] is False
    assert payload["enrichment_by_source"] == {}
    assert payload["summary_by_source"] == {}


def test_status_source_scopes_the_refresh_debt_maps(scrolls_home, capsys):
    """`status --source <S>` (H166) scopes the refresh-debt maps to one source too —
    the maps collapse to that source's debt only, equal to the *scoped* doctor audit's
    maps, so the whole status payload reads one-source on the refresh axis as well.
    Scoped to `web`: its two stale classifications, and the web-only Vector summary
    (Bm25 drops below `MIN_MEMBERS` under the scope, so it is no longer eligible)."""
    paths = get_paths()
    _seed_refresh_debt(paths)
    capsys.readouterr()

    assert main(["status", "--source", "web"]) == 0
    payload = json.loads(capsys.readouterr().out)

    # web's slice only: its two stale classifications; its one eligible stale summary
    assert payload["enrichment_by_source"] == {"web": 2}
    assert payload["summary_by_source"] == {"web": 1}
    # == the scoped doctor audit's own maps (convergence by construction)
    scoped = run_doctor(paths, source="web")
    assert payload["enrichment_by_source"] == report_enrichment_by_source(scoped)
    assert payload["summary_by_source"] == report_summary_by_source(scoped)


def test_status_counts_items_and_subscriptions(scrolls_home, capsys):
    main(["add", "https://x.com/karpathy/status/1111"])
    main(["add", "https://example.com/post"])
    item = get_item(get_paths().db_path, "x:1111")
    update_item(
        get_paths().db_path,
        dataclasses.replace(
            item, title="A tweet", extracted_text="text", category="technique",
            stage="fetched",
        ),
    )
    insert_subscription(
        get_paths().db_path,
        Subscription(
            id="feedfeedfeed",
            feed_url="https://blog.example/feed.xml",
            title="Demo Weblog",
            added_at="2026-06-12T08:00:00+00:00",
        ),
    )
    capsys.readouterr()

    exit_code = main(["status"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["items"] == {
        "total": 2,
        "by_stage": {"detected": 1, "fetched": 1, "rendered": 0},
        "by_source": {"web": 1, "x": 1},
        "unclassified": 1,
    }
    assert payload["subscriptions"] == 1


def test_add_persists_detected_item(scrolls_home, capsys):
    exit_code = main(["add", "https://youtu.be/dQw4w9WgXcQ"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "id": "youtube:dQw4w9WgXcQ",
        "source": "youtube",
        "source_id": "dQw4w9WgXcQ",
        "url": "https://youtu.be/dQw4w9WgXcQ",
        "stage": "detected",
        "created": True,
    }
    # add auto-initializes the library skeleton
    assert (scrolls_home / "db.sqlite").is_file()
    assert (scrolls_home / "config.toml").is_file()


def test_add_same_video_via_other_url_form_is_deduped(scrolls_home, capsys):
    main(["add", "https://youtu.be/dQw4w9WgXcQ"])
    capsys.readouterr()

    exit_code = main(["add", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is False
    assert payload["id"] == "youtube:dQw4w9WgXcQ"
    assert payload["url"] == "https://youtu.be/dQw4w9WgXcQ"  # first record wins


def test_add_strips_tracking_params_before_identity(scrolls_home, capsys):
    main(["add", "https://blog.example.com/post"])
    first = json.loads(capsys.readouterr().out)

    exit_code = main(
        ["add", "https://blog.example.com/post?utm_source=newsletter&fbclid=IwAR0"]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is False
    assert payload["id"] == first["id"]


def test_add_stores_the_normalized_url(scrolls_home, capsys):
    exit_code = main(["add", "https://blog.example.com/post?utm_campaign=launch#hero"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is True
    assert payload["url"] == "https://blog.example.com/post"


def test_add_rejects_non_http_url(scrolls_home, capsys):
    exit_code = main(["add", "not-a-url"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)
    assert not scrolls_home.exists()  # no library created on failure


def test_list_before_init_prints_empty_array(scrolls_home, capsys):
    exit_code = main(["list"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


@pytest.fixture
def fake_wikipedia_api(monkeypatch):
    """Serve a canned MediaWiki extracts payload instead of the network."""
    payload = {
        "query": {
            "pages": [
                {
                    "pageid": 25387,
                    "title": "SQLite",
                    "fullurl": "https://en.wikipedia.org/wiki/SQLite",
                    "canonicalurl": "https://en.wikipedia.org/wiki/SQLite",
                    "extract": "SQLite is a database engine.\n\n\n== History ==\nEarly days.",
                    "categories": [
                        {"ns": 14, "title": "Category:Database management systems"}
                    ],
                }
            ]
        }
    }
    monkeypatch.setattr(wikipedia, "_get_json", lambda url: payload)
    return payload


def test_fetch_all_fetches_detected_wikipedia_item(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    exit_code = main(["fetch"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fetched"] == 1
    assert payload["failed"] == 0
    assert payload["results"] == [
        {"id": "wikipedia:en:SQLite", "status": "fetched", "title": "SQLite", "stage": "fetched"}
    ]

    stored = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    assert stored.stage == "fetched"
    assert stored.title == "SQLite"
    assert stored.extracted_text.startswith("SQLite is a database engine.")


def test_fetch_all_skips_sources_without_adapter(
    scrolls_home, fake_wikipedia_api, monkeypatch, capsys
):
    # `x` was the last detected source without a fetch adapter; now that it has
    # one, the adapterless case is reached only by a source this build does not
    # know (an imported bundle from a newer one). Dropping the entry reproduces
    # that without pretending x is unfetchable -- and keeps the test offline,
    # since the adapter would otherwise reach live X over the browser session.
    monkeypatch.delitem(FETCH_ADAPTERS, "x")
    main(["add", "https://x.com/karpathy/status/1234567890123456789"])
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    exit_code = main(["fetch"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fetched"] == 1
    assert payload["skipped"] == 1
    by_id = {entry["id"]: entry for entry in payload["results"]}
    assert by_id["x:1234567890123456789"]["status"] == "skipped"
    assert "x" in by_id["x:1234567890123456789"]["reason"]
    # the skipped item is untouched and will be picked up once an adapter lands
    assert get_item(get_paths().db_path, "x:1234567890123456789").stage == "detected"


def test_fetch_all_with_nothing_detected(scrolls_home, capsys):
    exit_code = main(["fetch"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"fetched": 0, "skipped": 0, "failed": 0, "results": []}


def test_fetch_limit_caps_attempts_and_resumes(scrolls_home, fake_wikipedia_api, capsys):
    main(["init"])
    for n, day in ((1, "01"), (2, "02")):
        insert_item(
            get_paths().db_path,
            ScrollItem(
                id=f"wikipedia:en:Page_{n}",
                source="wikipedia",
                source_id=f"en:Page_{n}",
                url=f"https://en.wikipedia.org/wiki/Page_{n}",
                saved_at=f"2026-06-{day}T00:00:00+00:00",
            ),
        )
    capsys.readouterr()

    exit_code = main(["fetch", "--limit", "1"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fetched"] == 1
    assert len(payload["results"]) == 1  # items beyond the limit aren't reported
    assert payload["results"][0]["id"] == "wikipedia:en:Page_1"  # oldest saved first
    assert get_item(get_paths().db_path, "wikipedia:en:Page_2").stage == "detected"

    # the next run picks up where this one stopped
    main(["fetch", "--limit", "1"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["id"] == "wikipedia:en:Page_2"


def test_fetch_limit_does_not_count_adapterless_skips(
    scrolls_home, fake_wikipedia_api, monkeypatch, capsys
):
    # `x` was the last detected source without a fetch adapter; now that it has
    # one, the adapterless case is reached only by a source this build does not
    # know (an imported bundle from a newer one). Dropping the entry reproduces
    # that without pretending x is unfetchable -- and keeps the test offline,
    # since the adapter would otherwise reach live X over the browser session.
    monkeypatch.delitem(FETCH_ADAPTERS, "x")
    main(["init"])
    insert_item(
        get_paths().db_path,
        ScrollItem(
            id="x:111",
            source="x",
            source_id="111",
            url="https://x.com/a/status/111",
            saved_at="2026-06-01T00:00:00+00:00",
        ),
    )
    insert_item(
        get_paths().db_path,
        ScrollItem(
            id="wikipedia:en:SQLite",
            source="wikipedia",
            source_id="en:SQLite",
            url="https://en.wikipedia.org/wiki/SQLite",
            saved_at="2026-06-02T00:00:00+00:00",
        ),
    )
    capsys.readouterr()

    # the x item sits first in saved order; if skips consumed the limit it
    # would wedge the batch on every run
    exit_code = main(["fetch", "--limit", "1"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fetched"] == 1
    assert payload["skipped"] == 1
    assert get_item(get_paths().db_path, "wikipedia:en:SQLite").stage == "fetched"


def test_fetch_limit_with_explicit_id_is_an_error(scrolls_home, capsys):
    exit_code = main(["fetch", "wikipedia:en:SQLite", "--limit", "1"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_fetch_continues_past_failures_and_exits_nonzero(scrolls_home, monkeypatch, capsys):
    def boom(url):
        raise OSError("connection refused")

    monkeypatch.setattr(wikipedia, "_get_json", boom)
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    exit_code = main(["fetch"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed"] == 1
    assert payload["results"][0]["status"] == "failed"
    assert "connection refused" in payload["results"][0]["error"]
    # the item stays detected so a later fetch can retry it
    assert get_item(get_paths().db_path, "wikipedia:en:SQLite").stage == "detected"


def test_fetch_by_id_refetches_regardless_of_stage(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    exit_code = main(["fetch", "wikipedia:en:SQLite"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fetched"] == 1
    assert payload["results"][0]["id"] == "wikipedia:en:SQLite"


def test_fetch_by_id_without_adapter_fails(scrolls_home, monkeypatch, capsys):
    # `x` was the last detected source without a fetch adapter; now that it has
    # one, the adapterless case is reached only by a source this build does not
    # know (an imported bundle from a newer one). Dropping the entry reproduces
    # that without pretending x is unfetchable -- and keeps the test offline,
    # since the adapter would otherwise reach live X over the browser session.
    monkeypatch.delitem(FETCH_ADAPTERS, "x")
    main(["add", "https://x.com/karpathy/status/1234567890123456789"])
    capsys.readouterr()

    exit_code = main(["fetch", "x:1234567890123456789"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed"] == 1
    assert payload["results"][0]["status"] == "failed"
    assert "'x'" in payload["results"][0]["error"]


def test_fetch_unknown_id_is_an_error(scrolls_home, capsys):
    exit_code = main(["fetch", "wikipedia:en:Missing"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_md_renders_fetched_items_to_scroll_files(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    exit_code = main(["md"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rendered"] == 1
    assert payload["failed"] == 0
    assert payload["results"] == [
        {
            "id": "wikipedia:en:SQLite",
            "status": "rendered",
            "path": "scrolls/wikipedia/sqlite.md",
        }
    ]

    scroll = scrolls_home / "scrolls" / "wikipedia" / "sqlite.md"
    assert scroll.is_file()
    assert "# SQLite" in scroll.read_text(encoding="utf-8")
    stored = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    assert stored.stage == "rendered"
    assert stored.markdown_path == "scrolls/wikipedia/sqlite.md"


def test_md_bulk_run_is_idempotent(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    main(["md"])
    capsys.readouterr()

    exit_code = main(["md"])  # nothing left at stage 'fetched'
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"rendered": 0, "unchanged": 0, "failed": 0, "results": []}


def test_md_by_id_reports_an_identical_rerender_unchanged(
    scrolls_home, fake_wikipedia_api, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    main(["md"])
    capsys.readouterr()

    exit_code = main(["md", "wikipedia:en:SQLite"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rendered"] == 0
    assert payload["unchanged"] == 1
    assert payload["results"][0] == {
        "id": "wikipedia:en:SQLite",
        "status": "unchanged",
        "path": "scrolls/wikipedia/sqlite.md",
    }


@pytest.fixture
def fake_wikipedia_pair(monkeypatch):
    """Serve per-title MediaWiki payloads so two articles can coexist."""

    def _get_json(url):
        title = "Redis" if "Redis" in url else "SQLite"
        return {
            "query": {
                "pages": [
                    {
                        "pageid": 100 if title == "Redis" else 200,
                        "title": title,
                        "fullurl": f"https://en.wikipedia.org/wiki/{title}",
                        "canonicalurl": f"https://en.wikipedia.org/wiki/{title}",
                        "extract": f"{title} is a database engine.",
                    }
                ]
            }
        }

    monkeypatch.setattr(wikipedia, "_get_json", _get_json)


def test_md_all_takes_fetched_and_rendered_never_unfetched(
    scrolls_home, fake_wikipedia_pair, capsys
):
    # SQLite: rendered already; Redis: fetched but never rendered;
    # PostgreSQL: only detected, so there is nothing to render from.
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    main(["md"])
    main(["add", "https://en.wikipedia.org/wiki/Redis"])
    main(["fetch"])
    main(["add", "https://en.wikipedia.org/wiki/PostgreSQL"])
    capsys.readouterr()

    exit_code = main(["md", "--all"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rendered"] == 1
    assert payload["unchanged"] == 1
    assert payload["failed"] == 0
    by_id = {r["id"]: r["status"] for r in payload["results"]}
    assert by_id == {
        "wikipedia:en:SQLite": "unchanged",
        "wikipedia:en:Redis": "rendered",
    }
    assert get_item(get_paths().db_path, "wikipedia:en:Redis").stage == "rendered"
    assert get_item(get_paths().db_path, "wikipedia:en:PostgreSQL").stage == "detected"


def test_md_all_rewrites_a_scroll_the_current_renderer_would_write_differently(
    scrolls_home, fake_wikipedia_pair, capsys
):
    # A renderer improvement is indistinguishable from a stale file on disk:
    # the stored capture re-renders to different bytes than the scroll holds.
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["add", "https://en.wikipedia.org/wiki/Redis"])
    main(["fetch"])
    main(["md"])
    capsys.readouterr()
    stale = scrolls_home / "scrolls" / "wikipedia" / "redis.md"
    stale.write_text("an older renderer wrote this\n", encoding="utf-8")

    exit_code = main(["md", "--all"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rendered"] == 1
    assert payload["unchanged"] == 1
    assert "# Redis" in stale.read_text(encoding="utf-8")


def test_md_all_second_pass_is_a_total_noop_and_custody_stays_put(
    scrolls_home, fake_wikipedia_pair, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["add", "https://en.wikipedia.org/wiki/Redis"])
    main(["fetch"])
    main(["md", "--all"])
    capsys.readouterr()
    before = {
        item_id: get_item(get_paths().db_path, item_id)
        for item_id in ("wikipedia:en:SQLite", "wikipedia:en:Redis")
    }

    exit_code = main(["md", "--all"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rendered"] == 0
    assert payload["unchanged"] == 2
    assert payload["failed"] == 0
    for item_id, held in before.items():
        after = get_item(get_paths().db_path, item_id)
        assert after == held  # no DB write, no custody movement
        assert after.content_hash == held.content_hash


def test_md_all_settles_each_item_so_a_failure_costs_only_that_item(
    scrolls_home, fake_wikipedia_pair, monkeypatch, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["add", "https://en.wikipedia.org/wiki/Redis"])
    main(["fetch"])
    capsys.readouterr()

    import scrolls.cli as cli_module

    real_refresh = cli_module.refresh_scroll

    def failing_refresh(paths, item):
        if item.id == "wikipedia:en:Redis":
            raise OSError("disk full")
        return real_refresh(paths, item)

    monkeypatch.setattr(cli_module, "refresh_scroll", failing_refresh)
    exit_code = main(["md", "--all"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["rendered"] == 1
    assert payload["failed"] == 1
    # the finished item settled: file on disk, stage advanced in the DB
    assert get_item(get_paths().db_path, "wikipedia:en:SQLite").stage == "rendered"

    monkeypatch.setattr(cli_module, "refresh_scroll", real_refresh)
    exit_code = main(["md", "--all"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rendered"] == 1  # only the item the failure cost
    assert payload["unchanged"] == 1


def test_md_all_with_an_id_is_an_error(scrolls_home, capsys):
    exit_code = main(["md", "--all", "wikipedia:en:SQLite"])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_md_by_id_fails_for_unfetched_item(scrolls_home, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    exit_code = main(["md", "wikipedia:en:SQLite"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed"] == 1
    assert "detected" in payload["results"][0]["error"]
    # still no scroll file, stage unchanged
    assert not (scrolls_home / "scrolls" / "wikipedia").exists()
    assert get_item(get_paths().db_path, "wikipedia:en:SQLite").stage == "detected"


def test_md_unknown_id_is_an_error(scrolls_home, capsys):
    exit_code = main(["md", "wikipedia:en:Missing"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_search_returns_ranked_hits_json(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    exit_code = main(["search", "database engine"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    hit = payload[0]
    assert hit["id"] == "wikipedia:en:SQLite"
    assert hit["title"] == "SQLite"
    assert set(hit) == {
        "id", "source", "title", "url", "stage", "score", "snippet", "fidelity",
        "drift", "last_checked", "works", "matched_fields", "match_strength",
    }
    # a freshly fetched Wikipedia article holds a re-derivable body — full custody
    assert hit["fidelity"] == "full"
    # never re-verified against its live source — the honest never-checked posture (H58)
    assert hit["drift"] == "unverified"
    # …and so no last-checked timestamp to report (H84 honest absence)
    assert hit["last_checked"] is None
    # the rank explanation: "database engine" lands in the summary and body, not
    # the title "SQLite" — a summary-led match, the moderate band (the opaque
    # score made legible)
    assert hit["matched_fields"] == ["summary", "extracted_text"]
    assert hit["match_strength"] == "moderate"
    # a lone item is no duplicate of any saved work (ADR 0101)
    assert hit["works"] == []


def test_search_no_matches_prints_empty_array(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    exit_code = main(["search", "pelicans"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


def test_search_before_init_prints_empty_array(scrolls_home, capsys):
    exit_code = main(["search", "anything"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


def test_search_blank_query_is_an_error(scrolls_home, capsys):
    exit_code = main(["search", '""'])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_search_respects_limit_flag(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    exit_code = main(["search", "database", "--limit", "0"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


def test_search_filters_by_source_and_category(
    scrolls_home, fake_wikipedia_api, fake_github_api, capsys
):
    main(["ingest", "https://en.wikipedia.org/wiki/SQLite"])  # category: reference
    main(["ingest", "https://github.com/oojBuffalo/scrolls"])  # category: project
    capsys.readouterr()

    # both scrolls mention SQLite, so an unfiltered search returns both
    main(["search", "SQLite"])
    assert {hit["id"] for hit in json.loads(capsys.readouterr().out)} == {
        "wikipedia:en:SQLite",
        "github:oojBuffalo/scrolls",
    }

    # --source scopes the ranked match to one source
    exit_code = main(["search", "SQLite", "--source", "github"])
    assert exit_code == 0
    hits = json.loads(capsys.readouterr().out)
    assert [hit["id"] for hit in hits] == ["github:oojBuffalo/scrolls"]

    # --category scopes to one category (the github default is "project")
    main(["search", "SQLite", "--category", "reference"])
    hits = json.loads(capsys.readouterr().out)
    assert [hit["id"] for hit in hits] == ["wikipedia:en:SQLite"]

    # a filter that matches nothing is an empty result, not an error
    exit_code = main(["search", "SQLite", "--source", "arxiv"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


def test_search_and_list_filter_by_tag_and_concept(
    scrolls_home, fake_wikipedia_api, fake_github_api, capsys
):
    main(["ingest", "https://en.wikipedia.org/wiki/SQLite"])  # concept: db management
    main(["ingest", "https://github.com/oojBuffalo/scrolls"])  # concepts: kb, sqlite
    capsys.readouterr()

    # --concept scopes by slug; only the github repo carries the "sqlite" topic
    main(["search", "SQLite", "--concept", "SQLite"])
    assert [h["id"] for h in json.loads(capsys.readouterr().out)] == [
        "github:oojBuffalo/scrolls"
    ]

    # the wikipedia page's category concept matches by slug despite spacing/case
    main(["list", "--concept", "database management systems"])
    assert [i["id"] for i in json.loads(capsys.readouterr().out)] == [
        "wikipedia:en:SQLite"
    ]

    # a hand-set tag is then filterable case-insensitively
    main(["set", "wikipedia:en:SQLite", "tags=Python,SQLite"])
    capsys.readouterr()
    exit_code = main(["list", "--tag", "python"])
    assert exit_code == 0
    assert [i["id"] for i in json.loads(capsys.readouterr().out)] == [
        "wikipedia:en:SQLite"
    ]

    # a tag nothing carries is an empty result, not an error
    assert main(["search", "SQLite", "--tag", "rust"]) == 0
    assert json.loads(capsys.readouterr().out) == []


# --- The completeness contract G2: --stats scope echo + truncation honesty ---
#
# `docs/cli.md` G2: a scoped or --limit-capped result must let a reader holding
# *only the result* recover the scope it covered and whether it was truncated.
# The bare array (G1-locked default) cannot; `--stats` opts into the
# self-describing {scope, stats, results} envelope. These pin H6 (search+list).


def _stats_item(item_id, **overrides):
    base = dict(
        id=item_id,
        source=item_id.split(":")[0],
        url=f"https://example.org/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00",
        title=item_id,
        extracted_text="alpha beta gamma delta",
        summary="alpha beta gamma delta",
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def _core_stats(stats):
    """The returned/matched/truncated trio, dropping the derived tally members.

    The `search`/`list` `--stats` block now also carries a `custody` tally (roadmap
    H98) and, on `search`, a `strength` tally (roadmap H313); these G2
    truncation/scope tests pin the *denominator*, so they drop both and let the
    dedicated H98/H313 tests below own their values.
    """
    return {
        key: value
        for key, value in stats.items()
        if key not in ("custody", "strength")
    }


def test_search_stats_envelope_echoes_scope_and_marks_truncation(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    for index in range(5):
        insert_item(db, _stats_item(f"web:page{index}"))
    capsys.readouterr()

    exit_code = main(["search", "alpha", "--limit", "2", "--stats"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert list(payload) == ["scope", "stats", "results"]
    # the scope a reader recovers from the result alone
    assert payload["scope"] == {"query": "alpha", "limit": 2}
    # 2 of 5 → truncated: absence below the cap is NOT library-wide absence
    assert _core_stats(payload["stats"]) == {"returned": 2, "matched": 5, "truncated": True}
    assert len(payload["results"]) == 2


def test_search_stats_is_opt_in_default_stays_a_bare_array(scrolls_home, capsys):
    """Without --stats the result is the G1-locked bare array, unchanged."""
    main(["init"])
    insert_item(get_paths().db_path, _stats_item("web:one"))
    capsys.readouterr()

    main(["search", "alpha"])
    assert isinstance(json.loads(capsys.readouterr().out), list)

    main(["search", "alpha", "--stats"])
    assert isinstance(json.loads(capsys.readouterr().out), dict)


def test_search_stats_empty_scope_is_scope_honest_not_truncated(scrolls_home, capsys):
    """The dangerous empty case: nothing matched, but the scope is named.

    An empty scoped result must say *which* scope it checked, so it can never
    be misread as "the library holds nothing about this".
    """
    main(["init"])
    insert_item(get_paths().db_path, _stats_item("web:one"))
    capsys.readouterr()

    exit_code = main(["search", "alpha", "--source", "arxiv", "--stats"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"] == []
    assert payload["scope"] == {"query": "alpha", "source": "arxiv", "limit": 20}
    assert _core_stats(payload["stats"]) == {"returned": 0, "matched": 0, "truncated": False}


def test_search_stats_not_truncated_when_every_match_is_returned(scrolls_home, capsys):
    main(["init"])
    insert_item(get_paths().db_path, _stats_item("web:one"))
    capsys.readouterr()

    main(["search", "alpha", "--stats"])
    payload = json.loads(capsys.readouterr().out)
    assert _core_stats(payload["stats"]) == {"returned": 1, "matched": 1, "truncated": False}


def test_search_stats_keeps_the_unclassified_pool_in_scope(scrolls_home, capsys):
    """An empty-string `--category` is a real applied facet, not an absent one."""
    main(["init"])
    insert_item(get_paths().db_path, _stats_item("web:one"))
    capsys.readouterr()

    main(["search", "alpha", "--category", "", "--stats"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == {"query": "alpha", "category": "", "limit": 20}


def test_list_stats_echoes_applied_facets_and_marks_truncation(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, _stats_item("web:one"))
    insert_item(db, _stats_item("web:two"))
    capsys.readouterr()

    exit_code = main(["list", "--source", "web", "--limit", "1", "--stats"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == {"source": "web", "limit": 1}
    assert _core_stats(payload["stats"]) == {"returned": 1, "matched": 2, "truncated": True}
    assert len(payload["results"]) == 1


def test_list_stats_is_opt_in_default_stays_a_bare_array(scrolls_home, capsys):
    main(["init"])
    insert_item(get_paths().db_path, _stats_item("web:one"))
    capsys.readouterr()

    main(["list"])
    assert isinstance(json.loads(capsys.readouterr().out), list)

    main(["list", "--stats"])
    assert isinstance(json.loads(capsys.readouterr().out), dict)


def test_list_stats_uncapped_omits_limit_and_never_truncates(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, _stats_item("web:one"))
    insert_item(db, _stats_item("web:two"))
    capsys.readouterr()

    main(["list", "--stats"])
    payload = json.loads(capsys.readouterr().out)
    assert "limit" not in payload["scope"]  # uncapped: returned everything
    assert _core_stats(payload["stats"]) == {"returned": 2, "matched": 2, "truncated": False}


def test_list_limit_caps_the_bare_array_too(scrolls_home, capsys):
    """`--limit` is a real cap, not a --stats-only knob: it bounds the array."""
    main(["init"])
    db = get_paths().db_path
    for index in range(3):
        insert_item(db, _stats_item(f"web:item{index}"))
    capsys.readouterr()

    main(["list", "--limit", "2"])
    rows = json.loads(capsys.readouterr().out)
    assert isinstance(rows, list)
    assert len(rows) == 2  # oldest two, no envelope


def test_list_stats_before_init_is_the_empty_envelope_not_an_error(scrolls_home, capsys):
    """Before init, --stats still answers in shape — G1 parity across surfaces."""
    exit_code = main(["list", "--source", "web", "--limit", "5", "--stats"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["results"] == []
    assert payload["scope"] == {"source": "web", "limit": 5}
    assert _core_stats(payload["stats"]) == {"returned": 0, "matched": 0, "truncated": False}
    # the custody member is present even at empty — a stable zeroed shape (H98)
    # with the empty per-source split (roadmap H155) and the honest-null
    # weakest-source flag (roadmap H174)
    assert payload["stats"]["custody"] == {
        "tiers": {"full": 0, "partial": 0, "reference": 0},
        "drift": {"verified": 0, "unverified": 0, "drifted": 0, "rotted": 0, "error": 0},
        "by_source": {},
        "attention": None,
    }


# --- H98: stats.custody — the custody tally over the matched scope -----------


def _seed_custody_mix(db):
    """Three held scrolls matching `alpha`, spanning fidelity + drift: a full one
    re-checked unchanged (→ verified), a partial one drifted, a reference one
    never re-checked (→ unverified). So the matched-scope custody tally is the
    non-trivial mix `{full:1, partial:1, reference:1}` / `{verified:1, drifted:1,
    unverified:1}` every H98 assertion can drill.
    """
    insert_item(db, _stats_item(
        "web:full", raw_text="<raw>alpha</raw>", content_hash="sha256:full"))
    insert_item(db, _stats_item("web:partial"))  # extracted only → partial
    insert_item(db, _stats_item(
        "web:ref", extracted_text=None, summary=None, stage="detected"))  # reference
    record_events(db, [
        CustodyEvent("web:full", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:full", "sha256:full", None),
        CustodyEvent("web:partial", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:p", "sha256:x", None),
    ])


_MIX_TIERS = {"full": 1, "partial": 1, "reference": 1}
_MIX_DRIFT = {"verified": 1, "unverified": 1, "drifted": 1, "rotted": 0, "error": 0}
_MIX_CUSTODY = {
    "tiers": _MIX_TIERS,
    "drift": _MIX_DRIFT,
    # the seed is single-source `web`, so the per-source split (roadmap H155) folds
    # to one `{web: {tiers, drift}}` entry re-stating the whole-scope tally
    "by_source": {"web": {"tiers": _MIX_TIERS, "drift": _MIX_DRIFT}},
    # single source → the weakest-source flag is honestly `null` (roadmap H174)
    "attention": None,
}


def test_list_stats_custody_tallies_the_matched_scope(scrolls_home, capsys):
    # roadmap H98: `list --stats` carries a `stats.custody` tally over the matched
    # scope — fidelity tiers + drift postures — so a reader sees "of the N matched,
    # how much is held in full and how much drifted" without a second `facets` call.
    main(["init"])
    _seed_custody_mix(get_paths().db_path)
    capsys.readouterr()

    main(["list", "--stats"])
    stats = json.loads(capsys.readouterr().out)["stats"]
    assert stats["custody"] == _MIX_CUSTODY
    # the tier/posture sections each sum to `matched` (every scroll has one of each)
    assert sum(stats["custody"]["tiers"].values()) == stats["matched"] == 3
    assert sum(stats["custody"]["drift"].values()) == stats["matched"]


def test_list_stats_custody_is_the_matched_scope_not_the_returned_page(scrolls_home, capsys):
    # the load-bearing H98 claim: a `--limit 1` cap returns one row but the custody
    # tally still covers the *whole* matched scope (all three), so paging never
    # shrinks the custody picture.
    main(["init"])
    _seed_custody_mix(get_paths().db_path)
    capsys.readouterr()

    main(["list", "--limit", "1", "--stats"])
    stats = json.loads(capsys.readouterr().out)["stats"]
    assert stats["returned"] == 1 and stats["matched"] == 3 and stats["truncated"] is True
    assert stats["custody"] == _MIX_CUSTODY  # over the matched 3, not the returned 1


# `search alpha` is query-scoped: the contentless `web:ref` pointer has no body to
# full-text match, so it is *not* in the search-matched scope (only `list` lists it).
# So search custody tallies the two items that match the query — a sharper picture
# than `list`'s, and exactly the honest "of the N that matched *this query*" scope.
_SEARCH_TIERS = {"full": 1, "partial": 1, "reference": 0}
_SEARCH_DRIFT = {"verified": 1, "unverified": 0, "drifted": 1, "rotted": 0, "error": 0}
_MIX_CUSTODY_SEARCH = {
    "tiers": _SEARCH_TIERS,
    "drift": _SEARCH_DRIFT,
    # both query-matched hits are `web`, so the per-source split (roadmap H155)
    # re-states the whole-scope tally under one key
    "by_source": {"web": {"tiers": _SEARCH_TIERS, "drift": _SEARCH_DRIFT}},
    # single source → the weakest-source flag is honestly `null` (roadmap H174)
    "attention": None,
}


def test_search_stats_custody_tallies_the_matched_scope(scrolls_home, capsys):
    # the `search` twin of the list tally — each hit carries its own fidelity/drift
    # (H58), and the envelope folds them over the query-matched scope.
    main(["init"])
    _seed_custody_mix(get_paths().db_path)
    capsys.readouterr()

    main(["search", "alpha", "--stats"])
    stats = json.loads(capsys.readouterr().out)["stats"]
    assert stats["custody"] == _MIX_CUSTODY_SEARCH
    assert sum(stats["custody"]["tiers"].values()) == stats["matched"] == 2


def test_search_stats_custody_covers_the_matched_scope_past_the_cap(scrolls_home, capsys):
    # the truncated search case: `--limit 1` returns one ranked hit, but the custody
    # tally re-reads the full match set past the cap (the uncapped fetch only when
    # truncated), so the picture is the whole matched scope, not the one returned hit.
    main(["init"])
    _seed_custody_mix(get_paths().db_path)
    capsys.readouterr()

    main(["search", "alpha", "--limit", "1", "--stats"])
    stats = json.loads(capsys.readouterr().out)["stats"]
    assert stats["returned"] == 1 and stats["matched"] == 2 and stats["truncated"] is True
    assert stats["custody"] == _MIX_CUSTODY_SEARCH  # over the matched 2, not the returned 1


def test_stats_custody_is_opt_in_absent_from_the_bare_array(scrolls_home, capsys):
    # the custody member rides only the opt-in envelope — the bare default array
    # (G1-locked) is unchanged, carrying no envelope and so no custody block.
    main(["init"])
    _seed_custody_mix(get_paths().db_path)
    capsys.readouterr()

    for argv in (["list"], ["search", "alpha"]):
        main(argv)
        out = json.loads(capsys.readouterr().out)
        assert isinstance(out, list)  # no envelope → nowhere for a custody block


# --- H313/H314: stats.strength — the rank-quality tally + the --strength filter ---
# Each hit carries its own `match_strength` (H312); `search --stats` folds those into
# a `{strong, moderate, weak}` histogram beside `stats.custody` (H313), and
# `--strength <band>` keeps only the matches at or above that band (H314), the
# rank-axis sibling of `--fidelity`/`--drift`.


def _seed_strength_mix(db):
    """Three scrolls matching `alpha`, one landing in each rank-strength band.

    `alpha` in the title (strong), in the summary but not the title (moderate), and
    only in the body (weak) — so the matched-scope strength tally is the non-trivial
    `{strong:1, moderate:1, weak:1}` every H313/H314 assertion can drill.
    """
    insert_item(db, _stats_item(
        "web:strong", title="alpha overview",
        extracted_text="intro about things", summary="intro about things"))
    insert_item(db, _stats_item(
        "web:moderate", title="overview",
        extracted_text="alpha appears in the summary. more body text here.",
        summary="alpha appears in the summary"))
    insert_item(db, _stats_item(
        "web:weak", title="another overview",
        extracted_text="a first sentence. later the alpha token appears in body.",
        summary="a first sentence"))


_MIX_STRENGTH = {"strong": 1, "moderate": 1, "weak": 1}


def test_search_stats_strength_tallies_the_matched_scope(scrolls_home, capsys):
    # roadmap H313: `search --stats` carries a `stats.strength` histogram over the
    # matched scope, beside `stats.custody`, summing to `stats.matched`.
    main(["init"])
    _seed_strength_mix(get_paths().db_path)
    capsys.readouterr()

    main(["search", "alpha", "--stats"])
    stats = json.loads(capsys.readouterr().out)["stats"]
    assert stats["strength"] == _MIX_STRENGTH
    assert sum(stats["strength"].values()) == stats["matched"] == 3


def test_search_stats_strength_covers_the_matched_scope_past_the_cap(scrolls_home, capsys):
    # the truncated case: `--limit 1` returns one ranked hit, but the strength tally
    # re-reads the full match set past the cap (the H98 custody-tally precedent).
    main(["init"])
    _seed_strength_mix(get_paths().db_path)
    capsys.readouterr()

    main(["search", "alpha", "--limit", "1", "--stats"])
    stats = json.loads(capsys.readouterr().out)["stats"]
    assert stats["returned"] == 1 and stats["matched"] == 3 and stats["truncated"] is True
    assert stats["strength"] == _MIX_STRENGTH  # over the matched 3, not the returned 1


def test_search_stats_strength_is_opt_in_absent_from_the_bare_array(scrolls_home, capsys):
    # the strength member rides only the opt-in envelope; the bare default array is
    # unchanged (a list hit has no rank, so `list --stats` carries no strength block).
    main(["init"])
    _seed_strength_mix(get_paths().db_path)
    capsys.readouterr()

    main(["search", "alpha"])
    assert isinstance(json.loads(capsys.readouterr().out), list)
    main(["list", "--stats"])
    assert "strength" not in json.loads(capsys.readouterr().out)["stats"]


def test_search_strength_filter_keeps_the_band_and_echoes_scope(scrolls_home, capsys):
    # roadmap H314: --strength strong keeps only title hits; the honored filter rides
    # the scope echo (G2), and the strength tally narrows to the kept scope.
    main(["init"])
    _seed_strength_mix(get_paths().db_path)
    capsys.readouterr()

    exit_code = main(["search", "alpha", "--strength", "strong", "--stats"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in payload["results"]] == ["web:strong"]
    assert payload["scope"]["strength"] == "strong"
    assert payload["stats"]["matched"] == 1
    # the kept scope is all strong: the narrowed tally re-states it
    assert payload["stats"]["strength"] == {"strong": 1, "moderate": 0, "weak": 0}


def test_search_strength_drills_from_the_unfiltered_tally(scrolls_home, capsys):
    # the drill-from-strength tie: the --strength <band> matched count equals the sum
    # of the unfiltered tally's bands at or above <band> (threshold semantics).
    main(["init"])
    _seed_strength_mix(get_paths().db_path)
    capsys.readouterr()

    order = ["strong", "moderate", "weak"]
    matched_by_band = {}
    for band in order:
        main(["search", "alpha", "--strength", band, "--stats"])
        matched_by_band[band] = json.loads(capsys.readouterr().out)["stats"]["matched"]
    # cumulative: strong=1, moderate=strong+moderate=2, weak=all=3
    assert matched_by_band == {"strong": 1, "moderate": 2, "weak": 3}


def test_search_unknown_strength_band_is_exit_2(scrolls_home, capsys):
    # a closed vocabulary at the argparse layer (choices=) — exit 2, like a bad
    # --stage/--fidelity, never a silent empty selection.
    main(["init"])
    _seed_strength_mix(get_paths().db_path)
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        main(["search", "alpha", "--strength", "bogus"])
    assert exc.value.code == 2


# --- H155: stats.custody.by_source — the per-source split on the browse envelopes -


def _seed_multi_source_custody(db):
    """Three held scrolls matching `alpha` across two sources: a `web` full one
    re-checked unchanged (→ verified), a `web` partial one never re-checked
    (→ unverified), and an `arxiv` full one drifted. So the matched-scope custody
    splits per source into a non-trivial `{web: {full:1, partial:1}, arxiv: {full:1}}`
    fidelity picture and a `{web: verified+unverified, arxiv: drifted}` drift picture.
    """
    insert_item(db, _stats_item(
        "web:full", raw_text="<raw>alpha</raw>", content_hash="sha256:wf"))
    insert_item(db, _stats_item("web:partial"))  # extracted only → partial
    insert_item(db, _stats_item(
        "arxiv:1", raw_text="<raw>alpha</raw>", content_hash="sha256:af"))
    record_events(db, [
        CustodyEvent("web:full", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:wf", "sha256:wf", None),
        CustodyEvent("arxiv:1", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:af", "sha256:x", None),
    ])


_MULTI_BY_SOURCE = {
    "arxiv": {
        "tiers": {"full": 1, "partial": 0, "reference": 0},
        "drift": {"verified": 0, "unverified": 0, "drifted": 1, "rotted": 0, "error": 0},
    },
    "web": {
        "tiers": {"full": 1, "partial": 1, "reference": 0},
        "drift": {"verified": 1, "unverified": 1, "drifted": 0, "rotted": 0, "error": 0},
    },
}


def _sum_by_source(by_source):
    """Sum the per-source tallies back into one `{tiers, drift}` whole."""
    tiers = {tier: 0 for tier in ("full", "partial", "reference")}
    drift = {p: 0 for p in ("verified", "unverified", "drifted", "rotted", "error")}
    for counts in by_source.values():
        for tier, n in counts["tiers"].items():
            tiers[tier] += n
        for posture, n in counts["drift"].items():
            drift[posture] += n
    return {"tiers": tiers, "drift": drift}


def test_list_stats_by_source_splits_the_matched_scope(scrolls_home, capsys):
    # roadmap H155: `list --stats` carries a `stats.custody.by_source` member —
    # the matched-scope custody split per source, sorted keys, the lean
    # `{tiers, drift}` shape — beside the whole-scope `stats.custody`.
    main(["init"])
    _seed_multi_source_custody(get_paths().db_path)
    capsys.readouterr()

    main(["list", "--stats"])
    custody = json.loads(capsys.readouterr().out)["stats"]["custody"]
    by_source = custody["by_source"]
    assert list(by_source) == ["arxiv", "web"]  # sorted keys
    assert by_source == _MULTI_BY_SOURCE
    # the per-source split sums to the whole-scope tally beside it (the H104
    # sum-to-whole posture, per the matched scope)
    assert _sum_by_source(by_source) == {"tiers": custody["tiers"], "drift": custody["drift"]}
    # lean: no per-source coverage on the browse envelope (the H98–H101 family shape)
    assert all("coverage" not in entry for entry in by_source.values())


def test_list_stats_by_source_equals_doctor_for_the_whole_library(scrolls_home, capsys):
    # for the uncapped whole-library scope the browse-stats `by_source` equals
    # `doctor`'s `custody.by_source` (and `custody_counts_by_source`) on the
    # tiers/drift axes — the audit and the browse envelope read one number (H155).
    paths = get_paths()
    main(["init"])
    _seed_multi_source_custody(paths.db_path)
    capsys.readouterr()

    main(["list", "--stats"])
    by_source = json.loads(capsys.readouterr().out)["stats"]["custody"]["by_source"]
    doctor_by_source = run_doctor(paths)["custody"]["by_source"]
    assert set(by_source) == set(doctor_by_source)
    for source, entry in by_source.items():
        assert entry["tiers"] == doctor_by_source[source]["tiers"]
        assert entry["drift"] == doctor_by_source[source]["drift"]


def test_list_stats_by_source_covers_the_matched_scope_past_the_cap(scrolls_home, capsys):
    # the load-bearing claim mirrors the whole-scope tally: a `--limit 1` cap returns
    # one row but the per-source split still covers the *whole* matched scope.
    main(["init"])
    _seed_multi_source_custody(get_paths().db_path)
    capsys.readouterr()

    main(["list", "--limit", "1", "--stats"])
    stats = json.loads(capsys.readouterr().out)["stats"]
    assert stats["returned"] == 1 and stats["matched"] == 3 and stats["truncated"] is True
    assert stats["custody"]["by_source"] == _MULTI_BY_SOURCE  # over the matched 3


def test_list_stats_by_source_empty_scope_is_the_empty_map(scrolls_home, capsys):
    # an empty matched scope → the honest empty `{}` split, never omitted.
    main(["init"])
    capsys.readouterr()
    main(["list", "--source", "arxiv", "--stats"])
    assert json.loads(capsys.readouterr().out)["stats"]["custody"]["by_source"] == {}


def test_search_stats_by_source_splits_the_matched_scope(scrolls_home, capsys):
    # the `search` twin: each hit carries its own source/fidelity/drift (H58), and
    # the envelope folds them per source over the query-matched scope (H155).
    main(["init"])
    _seed_multi_source_custody(get_paths().db_path)
    capsys.readouterr()

    main(["search", "alpha", "--stats"])
    custody = json.loads(capsys.readouterr().out)["stats"]["custody"]
    assert custody["by_source"] == _MULTI_BY_SOURCE  # all three match the query
    assert _sum_by_source(custody["by_source"]) == {
        "tiers": custody["tiers"], "drift": custody["drift"]}


# --- H174: stats.custody.attention — the weakest-source flag on the browse envelopes -


def test_list_stats_attention_names_the_weakest_source(scrolls_home, capsys):
    # roadmap H174: `list --stats` distils its `by_source` map (H155) to a single
    # weakest-source `attention` flag — the browse-surface counterpart of the graph
    # flag (H164). The seed makes `arxiv` the only drifted source, so it is the
    # unambiguous max-loss source the flag must name (a literal pick — `web` is clean).
    main(["init"])
    _seed_multi_source_custody(get_paths().db_path)
    capsys.readouterr()

    main(["list", "--stats"])
    attention = json.loads(capsys.readouterr().out)["stats"]["custody"]["attention"]
    assert attention is not None
    assert attention["source"] == "arxiv"  # the only source with actionable loss
    assert attention["drift"]["drifted"] == 1
    assert attention["reason"] == "1 drifted"
    # the recheck command bridges to the act (H137)
    assert attention["command"] == "scrolls verify --source arxiv"


def test_list_stats_attention_is_lean_no_coverage(scrolls_home, capsys):
    # the load-bearing H174 decision: the browse `by_source` is the *lean* projection
    # (no per-source coverage, H155), so the flag distilled from it carries no
    # `coverage` member — never a fabricated `0/0` a reader would misread as "nothing
    # checked". A lean flag for a lean map. (`status`/`graph` carry the heavier flag.)
    main(["init"])
    _seed_multi_source_custody(get_paths().db_path)
    capsys.readouterr()

    main(["list", "--stats"])
    attention = json.loads(capsys.readouterr().out)["stats"]["custody"]["attention"]
    assert set(attention) == {"source", "tiers", "drift", "reason", "command"}
    assert "coverage" not in attention


def test_search_stats_attention_names_the_weakest_source(scrolls_home, capsys):
    # the `search` twin: the query-matched scope's weakest source, distilled from the
    # same lean `by_source` the search envelope folds (H155/H174).
    main(["init"])
    _seed_multi_source_custody(get_paths().db_path)
    capsys.readouterr()

    main(["search", "alpha", "--stats"])
    attention = json.loads(capsys.readouterr().out)["stats"]["custody"]["attention"]
    assert attention is not None
    assert attention["source"] == "arxiv"
    assert "coverage" not in attention


def test_browse_stats_attention_is_null_single_source(scrolls_home, capsys):
    # the honest-null gate (H174/H139): a single-source matched scope flags nothing —
    # `attention` only discriminates *across* sources. The `_seed_custody_mix` seed is
    # single-source `web` (with drift), so the flag is `null` on `list` and `search`.
    main(["init"])
    _seed_custody_mix(get_paths().db_path)
    capsys.readouterr()

    main(["list", "--stats"])
    assert json.loads(capsys.readouterr().out)["stats"]["custody"]["attention"] is None
    main(["search", "alpha", "--stats"])
    assert json.loads(capsys.readouterr().out)["stats"]["custody"]["attention"] is None


def test_list_stats_attention_empty_scope_is_null(scrolls_home, capsys):
    # an empty matched scope → the honest `null` flag (the `weakest_source` empty-map
    # gate), the stats shape stable even at empty (the H155 empty-envelope posture).
    main(["init"])
    capsys.readouterr()
    main(["list", "--source", "arxiv", "--stats"])
    assert json.loads(capsys.readouterr().out)["stats"]["custody"]["attention"] is None


def test_show_prints_full_item_json(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    exit_code = main(["show", "wikipedia:en:SQLite"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "wikipedia:en:SQLite"
    assert payload["title"] == "SQLite"
    assert payload["stage"] == "fetched"
    assert payload["extracted_text"].startswith("SQLite is a database engine.")
    assert payload["provenance"]["adapter"] == "wikipedia"
    assert payload["tags"] == []


def test_show_unknown_id_is_an_error(scrolls_home, capsys):
    exit_code = main(["show", "wikipedia:en:Missing"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_show_surfaces_the_classification_method(scrolls_home, fake_wikipedia_api, capsys):
    # how the category was derived travels with `show` (H20): the engine, the
    # precedence tier that fired, and the ruleset fingerprint it ran under
    from scrolls.classify import RULESET_FINGERPRINT

    main(["ingest", "https://en.wikipedia.org/wiki/SQLite"])  # ingest classifies inline
    capsys.readouterr()

    main(["show", "wikipedia:en:SQLite"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["category"] == "reference"
    assert payload["classification"] == {
        "by": "rules-v1",
        "basis": "curated-source",
        "ruleset": RULESET_FINGERPRINT,
        # the derived confidence marker (H21): a deterministic rule match, current
        # under the live ruleset
        "confidence": {"level": "deterministic", "freshness": "current"},
    }
    # the raw provenance keys are still present (show is the full dump)
    assert payload["provenance"]["classified_basis"] == "curated-source"


def test_show_carries_the_two_custody_axes(scrolls_home, capsys):
    # H61: the inspect surface carries the same per-item custody picture the
    # browse rows do — `fidelity` (how much is held) and `drift` (whether the
    # source moved) — derived, beside the raw record, at parity with `list`.
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:a", source="web", url="https://ex.com/a",
        saved_at="2026-06-12T00:00:00+00:00", title="Held in full",
        extracted_text="body", raw_text="<raw>body</raw>",
        content_hash="sha256:a", stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:b", source="web", url="https://ex.com/b",
        saved_at="2026-06-12T01:00:00+00:00", title="Never checked",
        extracted_text="body", raw_text="<raw>body</raw>",
        content_hash="sha256:b", stage="rendered"))
    record_events(db, [
        CustodyEvent("web:a", "2026-06-14T00:00:00+00:00", "drifted", "h", "x", None),
    ])
    capsys.readouterr()

    main(["show", "web:a"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["fidelity"] == "full"
    assert payload["drift"] == "drifted"  # latest ledger verdict

    # an item the ledger has no verdict for is honestly `unverified`
    main(["show", "web:b"])
    assert json.loads(capsys.readouterr().out)["drift"] == "unverified"


def test_show_custody_axes_match_the_list_row(scrolls_home, capsys):
    # H61 parity: the inspect surface reads the *same* fidelity/drift the browse
    # row does for the same item — the per-item picture reads the same everywhere.
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:a", source="web", url="https://ex.com/a",
        saved_at="2026-06-12T00:00:00+00:00", title="A scroll",
        extracted_text="body", stage="fetched"))
    record_events(db, [
        CustodyEvent("web:a", "2026-06-14T00:00:00+00:00", "rotted", "h", None, "404"),
    ])
    capsys.readouterr()

    main(["list"])
    row = json.loads(capsys.readouterr().out)[0]
    main(["show", "web:a"])
    shown = json.loads(capsys.readouterr().out)
    assert (shown["fidelity"], shown["drift"]) == (row["fidelity"], row["drift"])
    assert shown["drift"] == "rotted"


def test_show_carries_the_last_checked_timestamp(scrolls_home, capsys):
    # H84: the inspect surface carries `last_checked` beside `drift` — *when* the
    # latest verdict was taken, verbatim, or null when the item was never checked.
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:a", source="web", url="https://ex.com/a",
        saved_at="2026-06-12T00:00:00+00:00", title="Checked",
        extracted_text="body", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:b", source="web", url="https://ex.com/b",
        saved_at="2026-06-12T01:00:00+00:00", title="Never checked",
        extracted_text="body", stage="fetched"))
    record_events(db, [
        CustodyEvent("web:a", "2026-06-14T09:30:00+00:00", "drifted", "h", "x", None),
    ])
    capsys.readouterr()

    main(["show", "web:a"])
    assert json.loads(capsys.readouterr().out)["last_checked"] == "2026-06-14T09:30:00+00:00"
    main(["show", "web:b"])
    assert json.loads(capsys.readouterr().out)["last_checked"] is None  # honest absence


def test_last_checked_reads_the_same_across_list_search_show(scrolls_home, capsys):
    # H84 parity: the timestamp a `list` row, a `search` hit, and `show` report
    # for the same item are identical — one ledger read, one `last_checked`
    # primitive, the per-item time axis reading the same everywhere.
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:a", source="web", url="https://ex.com/a",
        saved_at="2026-06-12T00:00:00+00:00", title="Searchable database scroll",
        extracted_text="a database body", raw_text="<raw>db</raw>",
        content_hash="sha256:a", stage="rendered"))
    record_events(db, [
        CustodyEvent("web:a", "2026-06-14T09:30:00+00:00", "unchanged", "sha256:a", "sha256:a", None),
    ])
    capsys.readouterr()

    main(["list"])
    list_ts = json.loads(capsys.readouterr().out)[0]["last_checked"]
    main(["search", "database"])
    search_ts = json.loads(capsys.readouterr().out)[0]["last_checked"]
    main(["show", "web:a"])
    show_ts = json.loads(capsys.readouterr().out)["last_checked"]
    assert list_ts == search_ts == show_ts == "2026-06-14T09:30:00+00:00"


def test_show_names_the_content_duplicate_siblings(scrolls_home, capsys):
    # H328: `show` carries `content_duplicate_ids` — the *other* held ids
    # byte-identical to this one ("also held under <id>"), the per-item read
    # companion of `doctor`'s whole-library content-duplicate report (H325).
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:a", source="web", url="https://ex.com/a",
        saved_at="2026-06-12T00:00:00+00:00", title="A copy",
        extracted_text="body", raw_text="<raw>body</raw>",
        content_hash="sha256:dup", stage="rendered"))
    insert_item(db, ScrollItem(
        id="arxiv:1", source="arxiv", url="https://arxiv.org/abs/1",
        saved_at="2026-06-12T01:00:00+00:00", title="A mirror",
        extracted_text="body", raw_text="<raw>body</raw>",
        content_hash="sha256:dup", stage="rendered"))
    capsys.readouterr()

    # the cross-source byte-identical sibling is named (a content group spans sources)
    main(["show", "web:a"])
    assert json.loads(capsys.readouterr().out)["content_duplicate_ids"] == ["arxiv:1"]
    main(["show", "arxiv:1"])
    assert json.loads(capsys.readouterr().out)["content_duplicate_ids"] == ["web:a"]


def test_show_unique_item_names_no_content_duplicates(scrolls_home, capsys):
    # H328: a singleton content_hash and a reference-only (NULL-hash) item each
    # name no siblings — the honest empty list, the H325 NULL-safe rule per item.
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:solo", source="web", url="https://ex.com/solo",
        saved_at="2026-06-12T00:00:00+00:00", title="Only copy",
        extracted_text="body", raw_text="<raw>body</raw>",
        content_hash="sha256:solo", stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:ref", source="web", url="https://ex.com/ref",
        saved_at="2026-06-12T01:00:00+00:00", title="Reference only"))
    capsys.readouterr()

    main(["show", "web:solo"])
    assert json.loads(capsys.readouterr().out)["content_duplicate_ids"] == []
    main(["show", "web:ref"])
    assert json.loads(capsys.readouterr().out)["content_duplicate_ids"] == []


# --- H338: list/search --content-duplicate — the content-identity browse filter --


def _seed_content_duplicate_mix(db):
    """Two byte-identical content groups + a unique held + a reference-only item.

    Group 1 (full fidelity) is cross-source — `web:a` and `arxiv:1` share
    `content_hash=dup1` (a mirror captured by two adapters); group 2 (partial
    fidelity) is single-source — `web:p`/`web:q` share `content_hash=dup2`,
    holding only a summary + the fingerprint (no body → partial). `web:solo` is a
    held singleton and `web:ref` a NULL-hash reference. So `--content-duplicate`
    keeps exactly the four group members, `--source web` narrows to the web ones
    (the cross-source sibling still earns `web:a` its keep), and `--fidelity full`
    narrows to group 1 — and the kept set equals `doctor`'s content-duplicate
    group members.
    """
    insert_item(db, ScrollItem(
        id="web:a", source="web", url="https://e.com/a",
        saved_at="2026-06-12T00:00:00+00:00", title="alpha copy",
        extracted_text="body", raw_text="<r>body</r>",
        content_hash="sha256:dup1", stage="rendered"))
    insert_item(db, ScrollItem(
        id="arxiv:1", source="arxiv", url="https://arxiv.org/abs/1",
        saved_at="2026-06-12T01:00:00+00:00", title="alpha mirror",
        extracted_text="body", raw_text="<r>body</r>",
        content_hash="sha256:dup1", stage="rendered"))
    # partial: summary + hash only (no raw/extracted body), so get_fidelity → partial
    insert_item(db, ScrollItem(
        id="web:p", source="web", url="https://e.com/p",
        saved_at="2026-06-12T02:00:00+00:00", title="alpha p",
        summary="alpha digest", content_hash="sha256:dup2", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:q", source="web", url="https://e.com/q",
        saved_at="2026-06-12T03:00:00+00:00", title="alpha q",
        summary="alpha digest", content_hash="sha256:dup2", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:solo", source="web", url="https://e.com/solo",
        saved_at="2026-06-12T04:00:00+00:00", title="alpha solo",
        extracted_text="x", raw_text="<r>x</r>",
        content_hash="sha256:solo", stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:ref", source="web", url="https://e.com/ref",
        saved_at="2026-06-12T05:00:00+00:00", title="alpha ref"))


def test_list_content_duplicate_keeps_only_siblings(scrolls_home, capsys):
    # H338: `list --content-duplicate` keeps only the held items carrying a
    # byte-identical sibling (the two content groups), dropping the unique held
    # item and the NULL-hash reference — and the kept ids equal exactly the union
    # of `doctor`'s content-duplicate group members (the drill-from-the-report tie).
    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)
    capsys.readouterr()

    main(["list", "--content-duplicate"])
    kept = {row["id"] for row in json.loads(capsys.readouterr().out)}
    assert kept == {"web:a", "arxiv:1", "web:p", "web:q"}  # unique + ref dropped

    # converges with doctor: the kept set is exactly the group members
    main(["doctor"])
    groups = json.loads(capsys.readouterr().out)["custody"]["content_duplicates"]["groups"]
    members = {item_id for group in groups for item_id in group["ids"]}
    assert kept == members


def test_list_content_duplicate_composes_with_source_and_fidelity(scrolls_home, capsys):
    # H338: the filter ANDs with --source and --fidelity (the H251/H253 fold
    # composition), and the sibling scope is whole-library (a content group spans
    # sources, the H328 rule), so --source web still keeps web:a whose only sibling
    # (arxiv:1) lives in another source.
    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)
    capsys.readouterr()

    # whole-library sibling scope: web:a is kept though its sibling is arxiv (now
    # out of scope); arxiv:1 itself is dropped by --source web
    main(["list", "--content-duplicate", "--source", "web"])
    kept = {row["id"] for row in json.loads(capsys.readouterr().out)}
    assert kept == {"web:a", "web:p", "web:q"}

    # --fidelity full narrows to group 1 (the partial group 2 drops)
    main(["list", "--content-duplicate", "--fidelity", "full"])
    kept = {row["id"] for row in json.loads(capsys.readouterr().out)}
    assert kept == {"web:a", "arxiv:1"}

    # --fidelity partial narrows to group 2
    main(["list", "--content-duplicate", "--fidelity", "partial"])
    kept = {row["id"] for row in json.loads(capsys.readouterr().out)}
    assert kept == {"web:p", "web:q"}


def test_list_content_duplicate_stats_echoes_scope(scrolls_home, capsys):
    # H338: the `--stats` envelope echoes `content_duplicate: true` (the
    # `None`-is-pruned boolean convention) and `matched` counts only the kept set.
    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)
    capsys.readouterr()

    main(["list", "--content-duplicate", "--stats"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"]["content_duplicate"] is True
    assert payload["stats"]["matched"] == 4
    # a plain listing prunes the key (honored-only echo)
    main(["list", "--stats"])
    assert "content_duplicate" not in json.loads(capsys.readouterr().out)["scope"]


def test_search_content_duplicate_keeps_only_siblings(scrolls_home, capsys):
    # H338: `search --content-duplicate` keeps only the matches the library holds a
    # byte-identical copy of, dropping the unique held match and the NULL-hash
    # reference — the browse filter on the ranked surface, ANDed before the cap.
    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)
    capsys.readouterr()

    main(["search", "alpha", "--content-duplicate"])
    kept = {hit["id"] for hit in json.loads(capsys.readouterr().out)}
    assert kept == {"web:a", "arxiv:1", "web:p", "web:q"}  # solo + ref dropped

    # composes with --fidelity (ANDed into the ranked match before the cap)
    main(["search", "alpha", "--content-duplicate", "--fidelity", "full"])
    kept = {hit["id"] for hit in json.loads(capsys.readouterr().out)}
    assert kept == {"web:a", "arxiv:1"}


def test_search_content_duplicate_stats_denominator(scrolls_home, capsys):
    # H338: `count_matches` honors the flag, so the G2 truncation denominator
    # counts only the duplicated matches (never marked truncated by unique hits it
    # never showed), and the scope echoes the honored flag.
    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)
    capsys.readouterr()

    main(["search", "alpha", "--content-duplicate", "--limit", "2", "--stats"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"]["content_duplicate"] is True
    assert payload["stats"]["matched"] == 4  # the four duplicated matches, not 6
    assert payload["stats"]["returned"] == 2
    assert payload["stats"]["truncated"] is True


def test_facets_content_duplicate_partitions_and_drills_from_the_count(scrolls_home, capsys):
    # H342: `facets content-duplicate` partitions held items into duplicate/unique,
    # and the `duplicate` count folds the SAME content_duplicate_index the
    # `--content-duplicate` drill selects on and `doctor` counts — so the three agree.
    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)
    capsys.readouterr()

    main(["facets", "content-duplicate"])
    facet = json.loads(capsys.readouterr().out)["facets"]["content-duplicate"]
    # the full partition over the six held items: 4 duplicated, 2 (solo + ref) not
    assert {e["value"]: e["count"] for e in facet} == {"duplicate": 4, "unique": 2}
    assert facet[0] == {"value": "duplicate", "count": 4}  # ranked by count desc

    # drill-from-the-count: the `duplicate` bucket equals the rows the drill returns
    main(["list", "--content-duplicate"])
    drilled = json.loads(capsys.readouterr().out)
    assert len(drilled) == 4

    # ...and equals doctor's whole-library content-duplicate item total
    main(["doctor"])
    duplicates = json.loads(capsys.readouterr().out)["custody"]["content_duplicates"]
    assert duplicates["total_items"] == 4
    assert duplicates["total_groups"] == 2


def test_facets_content_duplicate_scope_is_whole_library_sibling(scrolls_home, capsys):
    # H342: --source narrows the partitioned set but the sibling fold stays
    # whole-library (the H328 cross-source rule), so web:a counts as `duplicate`
    # under --source web even though its only sibling (arxiv:1) lives in another
    # source — exactly the set `list --source web --content-duplicate` returns.
    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)
    capsys.readouterr()

    main(["facets", "content-duplicate", "--source", "web"])
    facet = {
        e["value"]: e["count"]
        for e in json.loads(capsys.readouterr().out)["facets"]["content-duplicate"]
    }
    # web items: web:a (sibling in arxiv) + web:p + web:q are duplicate; solo + ref unique
    assert facet == {"duplicate": 3, "unique": 2}

    main(["list", "--source", "web", "--content-duplicate"])
    assert len(json.loads(capsys.readouterr().out)) == facet["duplicate"]


def test_list_surfaces_the_classification_method(scrolls_home, fake_wikipedia_api, capsys):
    from scrolls.classify import RULESET_FINGERPRINT

    main(["ingest", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    main(["list"])
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["classification"] == {
        "by": "rules-v1",
        "basis": "curated-source",
        "ruleset": RULESET_FINGERPRINT,
        "confidence": {"level": "deterministic", "freshness": "current"},
    }


def test_list_omits_classification_for_an_unclassified_item(scrolls_home, capsys):
    # honest absence: an item no engine classified carries no classification key,
    # keeping the row shape stable (parity with the documented browse fields)
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    insert_item(get_paths().db_path, ScrollItem(
        id="web:plain", source="web", url="https://ex.com/plain",
        saved_at="2026-06-12T00:00:00+00:00", title="An ordinary post", stage="fetched"))
    capsys.readouterr()

    main(["list"])
    rows = json.loads(capsys.readouterr().out)
    assert "classification" not in rows[0]


def test_search_surfaces_the_classification_method(scrolls_home, fake_wikipedia_api, capsys):
    # how a hit's category was produced travels with `search` too (H26), so it
    # reads identically on every browse surface (search ≡ list ≡ show)
    from scrolls.classify import RULESET_FINGERPRINT

    main(["ingest", "https://en.wikipedia.org/wiki/SQLite"])  # ingest classifies inline
    capsys.readouterr()

    main(["search", "SQLite"])
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["classification"] == {
        "by": "rules-v1",
        "basis": "curated-source",
        "ruleset": RULESET_FINGERPRINT,
        # the same confidence marker reads identically on the ranked surface
        "confidence": {"level": "deterministic", "freshness": "current"},
    }


def test_search_stats_envelope_carries_the_classification_method(
    scrolls_home, fake_wikipedia_api, capsys
):
    # the derived view rides the --stats envelope's results too, unchanged
    main(["ingest", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    main(["search", "SQLite", "--stats"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["classification"]["by"] == "rules-v1"


def test_search_omits_classification_for_an_unclassified_item(scrolls_home, capsys):
    # honest absence on the ranked surface, matching `list`'s stable row shape
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    insert_item(get_paths().db_path, ScrollItem(
        id="web:plain", source="web", url="https://ex.com/plain",
        saved_at="2026-06-12T00:00:00+00:00", title="An ordinary post about pelicans",
        extracted_text="Pelicans are large water birds.", stage="fetched"))
    capsys.readouterr()

    main(["search", "pelicans"])
    rows = json.loads(capsys.readouterr().out)
    assert "classification" not in rows[0]


def test_classification_view_is_identical_across_browse_surfaces(
    scrolls_home, fake_wikipedia_api, capsys
):
    # H26's whole point: for one item, how its category was produced reads
    # identically whether an agent searched for it, listed it, or showed it.
    main(["ingest", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    main(["search", "SQLite"])
    search_view = json.loads(capsys.readouterr().out)[0]["classification"]
    main(["list"])
    list_view = next(
        r for r in json.loads(capsys.readouterr().out) if r["id"] == "wikipedia:en:SQLite"
    )["classification"]
    main(["show", "wikipedia:en:SQLite"])
    show_view = json.loads(capsys.readouterr().out)["classification"]

    assert search_view == list_view == show_view


def test_confidence_marker_surfaces_a_stale_recency_on_browse_surfaces(
    scrolls_home, capsys
):
    # H21's agent-facing payoff: an item classified under a superseded ruleset
    # reads `freshness: stale` on the browse surfaces themselves, so an agent
    # knows the category may no longer reproduce without consulting `doctor`
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    insert_item(get_paths().db_path, ScrollItem(
        id="web:stale", source="web", url="https://ex.com/stale",
        saved_at="2026-06-12T00:00:00+00:00", title="An older tutorial",
        extracted_text="Prose about a database engine.", stage="fetched",
        category="tutorial",
        provenance={"classified_by": "rules-v1", "classified_basis": "title-pattern",
                    "classified_ruleset": "deadbeef0000"}))
    capsys.readouterr()

    main(["show", "web:stale"])
    show_confidence = json.loads(capsys.readouterr().out)["classification"]["confidence"]
    assert show_confidence == {"level": "deterministic", "freshness": "stale"}

    main(["search", "database engine"])
    hit_confidence = json.loads(capsys.readouterr().out)[0]["classification"]["confidence"]
    assert hit_confidence == show_confidence  # the recency reads identically on search


@pytest.fixture
def fake_youtube_api(monkeypatch):
    """Serve canned oEmbed metadata and transcript instead of the network."""
    oembed = {
        "title": "How SQLite FTS Works",
        "author_name": "Example Channel",
        "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    }
    transcript = [
        {"text": "today we look at SQLite FTS5", "start": 0.0, "duration": 3.0},
        {"text": "and BM25 ranking", "start": 3.0, "duration": 2.0},
    ]
    monkeypatch.setattr(youtube, "_get_json", lambda url: dict(oembed))
    monkeypatch.setattr(youtube, "_get_transcript", lambda video_id: list(transcript))
    return oembed


def test_ingest_youtube_video_end_to_end(scrolls_home, fake_youtube_api, capsys):
    exit_code = main(["ingest", "https://youtu.be/dQw4w9WgXcQ"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "id": "youtube:dQw4w9WgXcQ",
        "source": "youtube",
        "url": "https://youtu.be/dQw4w9WgXcQ",
        "created": True,
        "title": "How SQLite FTS Works",
        "category": "media",  # classified inline: youtube source default
        "stage": "rendered",
        "markdown_path": "scrolls/youtube/how-sqlite-fts-works.md",
    }
    scroll = (scrolls_home / "scrolls" / "youtube" / "how-sqlite-fts-works.md").read_text()
    assert "SQLite FTS5 and BM25 ranking" in scroll
    capsys.readouterr()

    # the transcript is indexed: search finds the video by spoken content
    exit_code = main(["search", "BM25 ranking"])
    assert exit_code == 0
    hits = json.loads(capsys.readouterr().out)
    assert [hit["id"] for hit in hits] == ["youtube:dQw4w9WgXcQ"]


@pytest.fixture
def fake_github_api(monkeypatch):
    """Serve canned repo metadata and README instead of the network."""
    import base64

    import scrolls.sources.github as github

    repo = {
        "full_name": "oojBuffalo/scrolls",
        "html_url": "https://github.com/oojBuffalo/scrolls",
        "description": "Turn saved internet artifacts into agent-readable knowledge.",
        "owner": {"login": "oojBuffalo"},
        "created_at": "2026-05-01T12:00:00Z",
        "topics": ["knowledge-base", "sqlite"],
    }
    readme = "# Scrolls\n\nSQLite FTS5 keeps the library searchable.\n"
    encoded = base64.b64encode(readme.encode("utf-8")).decode("ascii")

    def get_json(url):
        if url.endswith("/readme"):
            return {"content": encoded, "encoding": "base64"}
        return dict(repo)

    monkeypatch.setattr(github, "_get_json", get_json)
    return repo


def test_ingest_github_repo_end_to_end(scrolls_home, fake_github_api, capsys):
    exit_code = main(["ingest", "https://github.com/oojBuffalo/scrolls"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "id": "github:oojBuffalo/scrolls",
        "source": "github",
        "url": "https://github.com/oojBuffalo/scrolls",
        "created": True,
        "title": "oojBuffalo/scrolls",
        "category": "project",  # classified inline: github curated default
        "stage": "rendered",
        "markdown_path": "scrolls/github/oojbuffalo-scrolls.md",
    }
    scroll = (scrolls_home / "scrolls" / "github" / "oojbuffalo-scrolls.md").read_text()
    assert '\nconcepts: ["knowledge-base", "sqlite"]\n' in scroll
    assert "SQLite FTS5 keeps the library searchable." in scroll
    capsys.readouterr()

    # repo topics are the first concepts producer: kb builds concept pages
    exit_code = main(["kb"])
    assert exit_code == 0
    kb_payload = json.loads(capsys.readouterr().out)
    assert kb_payload["concepts"] == 2
    concept_page = scrolls_home / "library" / "concepts" / "knowledge-base.md"
    assert "oojBuffalo/scrolls" in concept_page.read_text()


@pytest.fixture
def fake_arxiv_api(monkeypatch):
    """Serve a canned Atom feed and PDF instead of the network."""
    import scrolls.sources.arxiv as arxiv
    from pdf_fixtures import make_pdf

    feed = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2310.06825v1</id>
    <published>2023-10-10T17:54:02Z</published>
    <title>Mistral 7B</title>
    <summary>We introduce Mistral 7B, a 7-billion-parameter language model.</summary>
    <author><name>Albert Q. Jiang</name></author>
    <link href="http://arxiv.org/abs/2310.06825v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2310.06825v1" rel="related"
          type="application/pdf"/>
    <category term="cs.CL"/>
  </entry>
</feed>"""
    pdf = make_pdf("Grouped-query attention accelerates decoding throughput.")
    monkeypatch.setattr(arxiv, "_get_text", lambda url: feed)
    monkeypatch.setattr(arxiv, "_get_bytes", lambda url: pdf)
    return feed


def test_ingest_arxiv_paper_end_to_end(scrolls_home, fake_arxiv_api, capsys):
    exit_code = main(["ingest", "https://arxiv.org/abs/2310.06825"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "id": "arxiv:2310.06825",
        "source": "arxiv",
        "url": "https://arxiv.org/abs/2310.06825",
        "created": True,
        "title": "Mistral 7B",
        "category": "paper",  # classified inline: arxiv curated default
        "stage": "rendered",
        "markdown_path": "scrolls/arxiv/mistral-7b.md",
    }
    scroll = (scrolls_home / "scrolls" / "arxiv" / "mistral-7b.md").read_text()
    assert '\ntags: ["cs.CL"]\n' in scroll
    # taxonomy display names join the concept graph (ADR 0012)
    assert '\nconcepts: ["Computation and Language"]\n' in scroll
    assert "We introduce Mistral 7B" in scroll
    # PDF full text lands in the scroll's extracted content (ADR 0010)
    assert "Grouped-query attention accelerates decoding throughput." in scroll
    capsys.readouterr()

    # the abstract is indexed: search finds the paper by its summary
    exit_code = main(["search", "language model"])
    assert exit_code == 0
    hits = json.loads(capsys.readouterr().out)
    assert [hit["id"] for hit in hits] == ["arxiv:2310.06825"]
    capsys.readouterr()

    # the PDF full text is indexed too: this phrase appears nowhere else
    exit_code = main(["search", "decoding throughput"])
    assert exit_code == 0
    hits = json.loads(capsys.readouterr().out)
    assert [hit["id"] for hit in hits] == ["arxiv:2310.06825"]


def test_ingest_pdf_url_end_to_end(scrolls_home, monkeypatch, capsys):
    import scrolls.sources.pdf as pdf
    from pdf_fixtures import make_pdf

    blob = make_pdf(
        "Grouped-query attention trades model capacity for decode speed.",
        {"Title": "GQA Technical Report", "Subject": "A grouped-query attention report."},
    )
    monkeypatch.setattr(pdf, "_get_bytes", lambda url: blob)

    exit_code = main(["ingest", "https://example.com/papers/attention.pdf"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "id": "pdf:eb2e6487c357",
        "source": "pdf",
        "url": "https://example.com/papers/attention.pdf",
        "created": True,
        "title": "GQA Technical Report",
        "category": None,  # honestly unclassified: no rule for generic PDFs
        "stage": "rendered",
        "markdown_path": "scrolls/pdf/gqa-technical-report.md",
    }
    scroll = (scrolls_home / "scrolls" / "pdf" / "gqa-technical-report.md").read_text()
    assert "A grouped-query attention report." in scroll
    assert "Grouped-query attention trades model capacity" in scroll
    # the document itself is a media ref, so `scrolls media` can capture it
    assert (
        '\nmedia: [{"type": "pdf", "url": "https://example.com/papers/attention.pdf"}]\n'
        in scroll
    )
    capsys.readouterr()

    # the PDF text is indexed for search
    exit_code = main(["search", "decode speed"])
    assert exit_code == 0
    hits = json.loads(capsys.readouterr().out)
    assert [hit["id"] for hit in hits] == ["pdf:eb2e6487c357"]


def test_ingest_runs_add_fetch_md_in_one_command(scrolls_home, fake_wikipedia_api, capsys):
    exit_code = main(["ingest", "https://en.wikipedia.org/wiki/SQLite"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "id": "wikipedia:en:SQLite",
        "source": "wikipedia",
        "url": "https://en.wikipedia.org/wiki/SQLite",
        "created": True,
        "title": "SQLite",
        "category": "reference",
        "stage": "rendered",
        "markdown_path": "scrolls/wikipedia/sqlite.md",
    }
    # the first render already carries the category — no second pass needed
    scroll = (scrolls_home / "scrolls" / "wikipedia" / "sqlite.md").read_text()
    assert '\ncategory: "reference"\n' in scroll
    # visible page categories arrive as concepts (ADR 0007 follow-up)
    assert '\nconcepts: ["Database management systems"]\n' in scroll

    stored = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    assert stored.category == "reference"
    assert stored.provenance["classified_by"] == "rules-v1"


def test_ingest_leaves_unmatched_items_unclassified(scrolls_home, monkeypatch, capsys):
    import scrolls.sources.web as web

    html = (
        "<html><head><title>An ordinary post</title></head><body><article>"
        "<h1>An ordinary post</h1><p>Some long enough paragraph about nothing "
        "in particular, just plain prose for the extractor to find.</p>"
        "</article></body></html>"
    )
    monkeypatch.setattr(web, "_get_html", lambda url: html)

    exit_code = main(["ingest", "https://blog.example.com/post"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["category"] is None
    assert payload["stage"] == "rendered"


def test_ingest_existing_url_refreshes_it(scrolls_home, fake_wikipedia_api, capsys):
    main(["ingest", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    exit_code = main(["ingest", "https://en.wikipedia.org/wiki/SQLite"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is False
    assert payload["stage"] == "rendered"
    assert payload["markdown_path"] == "scrolls/wikipedia/sqlite.md"  # stable path


def test_ingest_without_adapter_registers_but_reports_failure(
    scrolls_home, monkeypatch, capsys
):
    # `x` was the last detected source without a fetch adapter; now that it has
    # one, the adapterless case is reached only by a source this build does not
    # know (an imported bundle from a newer one). Dropping the entry reproduces
    # that without pretending x is unfetchable -- and keeps the test offline,
    # since the adapter would otherwise reach live X over the browser session.
    monkeypatch.delitem(FETCH_ADAPTERS, "x")
    exit_code = main(["ingest", "https://x.com/karpathy/status/1234567890123456789"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "x:1234567890123456789"
    assert payload["stage"] == "detected"
    assert "'x'" in payload["error"]
    # the item is still durably registered for a future adapter
    assert get_item(get_paths().db_path, "x:1234567890123456789").stage == "detected"


def test_ingest_fetch_failure_leaves_item_detected(scrolls_home, monkeypatch, capsys):
    def boom(url):
        raise OSError("connection refused")

    monkeypatch.setattr(wikipedia, "_get_json", boom)
    exit_code = main(["ingest", "https://en.wikipedia.org/wiki/SQLite"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == "detected"
    assert "connection refused" in payload["error"]


def test_ingest_rejects_non_http_url(scrolls_home, capsys):
    exit_code = main(["ingest", "not-a-url"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)
    assert not scrolls_home.exists()


def test_classify_batch_categorizes_and_rerenders(scrolls_home, fake_wikipedia_api, capsys):
    # add + fetch + md, not ingest: ingest classifies inline, and this test
    # exercises the batch path over an already-rendered uncategorized scroll
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    main(["md"])
    capsys.readouterr()

    exit_code = main(["classify"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["classified"] == 1
    assert payload["results"] == [
        {"id": "wikipedia:en:SQLite", "status": "classified", "category": "reference"}
    ]

    stored = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    assert stored.category == "reference"
    assert stored.provenance["classified_by"] == "rules-v1"
    assert stored.stage == "rendered"
    # the already-rendered scroll was re-rendered with the category in frontmatter
    scroll = (scrolls_home / "scrolls" / "wikipedia" / "sqlite.md").read_text()
    assert '\ncategory: "reference"\n' in scroll


def test_classify_batch_reports_unmatched_items(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    # make the stored item look like an unclassifiable web post
    plain = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    import dataclasses
    update_item(
        get_paths().db_path,
        dataclasses.replace(plain, source="web", title="An ordinary post",
                            url="https://blog.example.com/post"),
    )

    exit_code = main(["classify"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["classified"] == 0
    assert payload["unmatched"] == 1
    assert payload["results"][0]["status"] == "unmatched"
    assert get_item(get_paths().db_path, "wikipedia:en:SQLite").category is None


def test_classify_batch_never_overwrites_an_existing_category(
    scrolls_home, fake_wikipedia_api, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    # a user-set category must win over the rules engine (IDEAS.md §8)
    import dataclasses
    item = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    update_item(get_paths().db_path, dataclasses.replace(item, category="tool"))

    exit_code = main(["classify"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"classified": 0, "unmatched": 0, "failed": 0, "results": []}
    assert get_item(get_paths().db_path, "wikipedia:en:SQLite").category == "tool"


def test_classify_batch_ignores_unfetched_items(scrolls_home, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])  # stage: detected
    capsys.readouterr()

    exit_code = main(["classify"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"classified": 0, "unmatched": 0, "failed": 0, "results": []}


def test_classify_by_id_reclassifies_explicitly(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    import dataclasses
    item = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    update_item(get_paths().db_path, dataclasses.replace(item, category="tool"))

    exit_code = main(["classify", "wikipedia:en:SQLite"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["classified"] == 1
    assert get_item(get_paths().db_path, "wikipedia:en:SQLite").category == "reference"


def test_classify_unknown_id_is_an_error(scrolls_home, capsys):
    exit_code = main(["classify", "wikipedia:en:Missing"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


# --- classify --stale: refresh categories produced under a superseded ruleset
#
# `scrolls classify --stale` re-runs the rules engine over exactly the items
# `scrolls doctor` reports in custody.enrichment.stale, refreshing their
# category and ruleset fingerprint to the live ruleset. It is the user-invoked
# counterpart to H25's read-only report (regenerate on request, never doctor's
# silent overwrite — custody §2.4), closing the loop H20 → H25 → H27.


def _make_stale(item_id, fingerprint="deadbeef0000"):
    """Rewrite a held item's recorded ruleset to a superseded fingerprint."""
    item = get_item(get_paths().db_path, item_id)
    provenance = {**(item.provenance or {}), "classified_ruleset": fingerprint}
    update_item(get_paths().db_path, dataclasses.replace(item, provenance=provenance))


def test_classify_stale_refreshes_a_superseded_item(
    scrolls_home, fake_wikipedia_api, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    main(["md"])
    main(["classify"])  # reference, stamped with the live fingerprint
    _make_stale("wikipedia:en:SQLite")
    capsys.readouterr()

    exit_code = main(["classify", "--stale"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["classified"] == 1
    assert payload["results"] == [
        {"id": "wikipedia:en:SQLite", "status": "classified", "category": "reference"}
    ]
    stored = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    assert stored.category == "reference"
    # the recorded ruleset is refreshed to the live one — no longer stale
    assert stored.provenance["classified_ruleset"] == RULESET_FINGERPRINT
    assert stored.provenance["classified_by"] == "rules-v1"


def test_classify_stale_skips_current_ruleset_items(
    scrolls_home, fake_wikipedia_api, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    main(["md"])
    main(["classify"])  # current fingerprint
    capsys.readouterr()

    exit_code = main(["classify", "--stale"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "classified": 0, "unmatched": 0, "failed": 0, "results": []
    }


def test_classify_stale_leaves_user_set_categories_untouched(
    scrolls_home, fake_wikipedia_api, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    main(["md"])
    main(["classify"])
    _make_stale("wikipedia:en:SQLite")  # stale in the rules sense ...
    main(["set", "wikipedia:en:SQLite", "category=tool"])  # ... then user override
    capsys.readouterr()

    exit_code = main(["classify", "--stale"])
    assert exit_code == 0
    # nothing selected: the override dropped the engine stamp, so it is not stale
    assert json.loads(capsys.readouterr().out)["classified"] == 0
    stored = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    assert stored.category == "tool"  # user wins
    assert "classified_by" not in (stored.provenance or {})


def test_classify_stale_clears_the_doctor_stale_signal(
    scrolls_home, fake_wikipedia_api, capsys
):
    # the loop converges: what doctor flags stale is exactly what --stale acts on
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    main(["md"])
    main(["classify"])
    _make_stale("wikipedia:en:SQLite")
    capsys.readouterr()

    main(["doctor"])
    before = json.loads(capsys.readouterr().out)["custody"]["enrichment"]
    assert before["stale"] == 1

    main(["classify", "--stale"])
    capsys.readouterr()

    main(["doctor"])
    after = json.loads(capsys.readouterr().out)["custody"]["enrichment"]
    assert after["stale"] == 0
    assert after["current"] == 1


def test_classify_stale_rejects_the_llm_engine(scrolls_home, capsys):
    exit_code = main(["classify", "--stale", "--engine", "llm"])
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


def test_classify_stale_rejects_batch(scrolls_home, capsys):
    exit_code = main(["classify", "--stale", "--batch"])
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


def test_classify_stale_rejects_an_item_id(scrolls_home, capsys):
    exit_code = main(["classify", "wikipedia:en:SQLite", "--stale"])
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


def test_classify_stale_empty_is_a_clean_noop(scrolls_home, capsys):
    exit_code = main(["classify", "--stale"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "classified": 0, "unmatched": 0, "failed": 0, "results": []
    }


# --- classify --stale --source <S>: the per-source enrichment refresh (H154) ---
#
# `--source` narrows `--stale` to exactly one source's stale-classified items
# (the slice doctor reports in custody.enrichment.by_source[<source>]) — the
# enrichment-axis counterpart of `verify --source <S>`. Refreshing one source
# restamps just its items and clears that source's entry from the per-source map.


def _insert_stale(item_id, source, *, ruleset="deadbeef0000"):
    """Insert a held item rules-classified under a superseded ruleset.

    Source defaults that the live ruleset still matches (wikipedia → reference,
    arxiv → paper, youtube → media), so a `--stale` refresh restamps it
    `current` rather than dropping it to `unmatched`.
    """
    matched = {"wikipedia": "reference", "arxiv": "paper", "youtube": "media"}
    insert_item(
        get_paths().db_path,
        ScrollItem(
            id=item_id,
            source=source,
            source_id=item_id.split(":", 1)[1],
            url=f"https://example.com/{item_id}",
            saved_at="2026-06-14T00:00:00+00:00",
            title="A held scroll",
            category=matched[source],
            stage="rendered",
            provenance={
                "adapter": source,
                "classified_by": "rules-v1",
                "classified_basis": "curated-source",
                "classified_ruleset": ruleset,
            },
        ),
    )


def test_classify_stale_source_refreshes_only_that_source(scrolls_home, capsys):
    main(["init"])
    _insert_stale("wikipedia:SQLite", "wikipedia")
    _insert_stale("wikipedia:Redis", "wikipedia")
    _insert_stale("arxiv:2401.00001", "arxiv")
    capsys.readouterr()

    exit_code = main(["classify", "--stale", "--source", "wikipedia"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["classified"] == 2
    assert {r["id"] for r in payload["results"]} == {
        "wikipedia:SQLite", "wikipedia:Redis"
    }
    # the two wikipedia items are restamped to the live ruleset ...
    for item_id in ("wikipedia:SQLite", "wikipedia:Redis"):
        stored = get_item(get_paths().db_path, item_id)
        assert stored.provenance["classified_ruleset"] == RULESET_FINGERPRINT
    # ... and arxiv's stale item is left untouched (a different source)
    arxiv = get_item(get_paths().db_path, "arxiv:2401.00001")
    assert arxiv.provenance["classified_ruleset"] == "deadbeef0000"


def test_classify_stale_source_count_matches_doctor_by_source(scrolls_home, capsys):
    # the H154 convergence: the count `--stale --source S` refreshes equals
    # doctor's `custody.enrichment.by_source[S]`, and the refresh clears S's entry.
    main(["init"])
    _insert_stale("wikipedia:SQLite", "wikipedia")
    _insert_stale("wikipedia:Redis", "wikipedia")
    _insert_stale("arxiv:2401.00001", "arxiv")
    capsys.readouterr()

    main(["doctor"])
    by_source = json.loads(capsys.readouterr().out)["custody"]["enrichment"]["by_source"]
    assert by_source == {"arxiv": 1, "wikipedia": 2}

    main(["classify", "--stale", "--source", "wikipedia"])
    refreshed = json.loads(capsys.readouterr().out)["classified"]
    assert refreshed == by_source["wikipedia"]  # exactly the per-source count

    # wikipedia drops out of the offenders-only map; arxiv's debt is untouched
    main(["doctor"])
    after = json.loads(capsys.readouterr().out)["custody"]["enrichment"]["by_source"]
    assert after == {"arxiv": 1}


def test_classify_stale_source_with_no_stale_is_a_clean_noop(scrolls_home, capsys):
    main(["init"])
    _insert_stale("wikipedia:SQLite", "wikipedia")
    capsys.readouterr()

    # a source nothing stale is held for selects nothing — exit 0, no error
    exit_code = main(["classify", "--stale", "--source", "reddit"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "classified": 0, "unmatched": 0, "failed": 0, "results": []
    }
    # the wikipedia debt is left for a `--source wikipedia` run
    main(["doctor"])
    by_source = json.loads(capsys.readouterr().out)["custody"]["enrichment"]["by_source"]
    assert by_source == {"wikipedia": 1}


def test_classify_source_without_stale_is_an_error(scrolls_home, capsys):
    # `--source` is a narrowing of `--stale`, not a standalone selection
    exit_code = main(["classify", "--source", "web"])
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


def test_classify_stale_source_rejects_the_llm_engine(scrolls_home, capsys):
    exit_code = main(["classify", "--stale", "--source", "web", "--engine", "llm"])
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the Anthropic completer with a canned classification."""
    import scrolls.classify_llm as classify_llm

    calls = []

    def complete(system, user, model):
        calls.append({"system": system, "user": user, "model": model})
        return json.dumps(
            {
                "category": "reference",
                "domain": "databases",
                "concepts": ["SQLite", "embedded databases"],
            }
        )

    monkeypatch.setattr(classify_llm, "_anthropic_complete", complete)
    return calls


def test_classify_llm_engine_classifies_and_rerenders(
    scrolls_home, fake_wikipedia_api, fake_llm, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    main(["md"])
    capsys.readouterr()

    exit_code = main(["classify", "--engine", "llm"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["classified"] == 1
    assert payload["results"][0]["category"] == "reference"
    assert payload["results"][0]["domain"] == "databases"
    assert "SQLite" in payload["results"][0]["concepts"]
    assert len(fake_llm) == 1

    stored = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    assert stored.category == "reference"
    assert stored.domain == "databases"
    # platform-curated concepts kept first, model concepts appended
    assert stored.concepts[0] == "Database management systems"
    assert "embedded databases" in stored.concepts
    assert stored.provenance["classified_by"] == "llm-v1"
    # the already-rendered scroll was re-rendered with the new frontmatter
    scroll = (scrolls_home / "scrolls" / "wikipedia" / "sqlite.md").read_text()
    assert '\ndomain: "databases"\n' in scroll


def test_classify_default_engine_never_calls_the_llm(
    scrolls_home, fake_wikipedia_api, fake_llm, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    exit_code = main(["classify"])
    assert exit_code == 0
    assert fake_llm == []
    stored = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    assert stored.provenance["classified_by"] == "rules-v1"


def test_classify_llm_batch_never_overwrites_an_existing_category(
    scrolls_home, fake_wikipedia_api, fake_llm, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    main(["classify"])  # rules assign 'reference'
    capsys.readouterr()

    exit_code = main(["classify", "--engine", "llm"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"classified": 0, "unmatched": 0, "failed": 0, "results": []}
    assert fake_llm == []


def test_classify_llm_by_id_reclassifies_explicitly(
    scrolls_home, fake_wikipedia_api, fake_llm, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    main(["classify"])  # rules assign 'reference', no domain
    capsys.readouterr()

    exit_code = main(["classify", "wikipedia:en:SQLite", "--engine", "llm"])
    assert exit_code == 0
    stored = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    assert stored.domain == "databases"
    assert stored.provenance["classified_by"] == "llm-v1"


@pytest.fixture
def fake_llm_batch(monkeypatch):
    """Replace the Batches transport with one canned answer per request."""
    import scrolls.classify_llm as classify_llm

    calls = []

    def complete_batch(system, requests, model):
        calls.append({"system": system, "requests": list(requests), "model": model})
        raw = json.dumps(
            {
                "category": "reference",
                "domain": "databases",
                "concepts": ["SQLite", "embedded databases"],
            }
        )
        return {cid: raw for cid, _ in requests}

    monkeypatch.setattr(classify_llm, "_anthropic_complete_batch", complete_batch)
    return calls


def test_classify_llm_batch_flag_submits_one_batch(
    scrolls_home, fake_wikipedia_api, fake_llm, fake_llm_batch, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    main(["md"])
    capsys.readouterr()

    exit_code = main(["classify", "--engine", "llm", "--batch"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["classified"] == 1
    assert payload["results"][0]["category"] == "reference"
    assert payload["results"][0]["domain"] == "databases"
    assert len(fake_llm_batch) == 1  # one Batches submission...
    assert fake_llm == []  # ...and no per-item calls

    stored = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    assert stored.provenance["classified_by"] == "llm-v1"
    # the already-rendered scroll was re-rendered with the new frontmatter
    scroll = (scrolls_home / "scrolls" / "wikipedia" / "sqlite.md").read_text()
    assert '\ndomain: "databases"\n' in scroll


def test_classify_batch_flag_requires_the_llm_engine(scrolls_home, capsys):
    exit_code = main(["classify", "--batch"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "llm" in json.loads(captured.err)["error"]


def test_classify_batch_flag_rejects_an_item_id(
    scrolls_home, fake_wikipedia_api, fake_llm_batch, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    exit_code = main(
        ["classify", "wikipedia:en:SQLite", "--engine", "llm", "--batch"]
    )
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)
    assert fake_llm_batch == []


def test_classify_llm_batch_without_credentials_aborts_with_error_envelope(
    scrolls_home, fake_wikipedia_api, monkeypatch, capsys
):
    import scrolls.classify_llm as classify_llm

    def no_auth(system, requests, model):
        raise classify_llm.LLMAuthError("llm engine needs Anthropic credentials")

    monkeypatch.setattr(classify_llm, "_anthropic_complete_batch", no_auth)
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    exit_code = main(["classify", "--engine", "llm", "--batch"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "credentials" in json.loads(captured.err)["error"]
    assert get_item(get_paths().db_path, "wikipedia:en:SQLite").category is None


def test_classify_llm_failure_is_reported_not_raised(
    scrolls_home, fake_wikipedia_api, monkeypatch, capsys
):
    import scrolls.classify_llm as classify_llm

    def broken(system, user, model):
        raise classify_llm.LLMClassifyError("Anthropic API error: overloaded")

    monkeypatch.setattr(classify_llm, "_anthropic_complete", broken)
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    exit_code = main(["classify", "--engine", "llm"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed"] == 1
    assert payload["results"][0]["status"] == "failed"
    assert "overloaded" in payload["results"][0]["error"]
    assert get_item(get_paths().db_path, "wikipedia:en:SQLite").category is None


def test_classify_llm_without_credentials_aborts_with_error_envelope(
    scrolls_home, fake_wikipedia_api, monkeypatch, capsys
):
    import scrolls.classify_llm as classify_llm

    def no_auth(system, user, model):
        raise classify_llm.LLMAuthError("llm engine needs Anthropic credentials")

    monkeypatch.setattr(classify_llm, "_anthropic_complete", no_auth)
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    exit_code = main(["classify", "--engine", "llm"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # no partial batch payload
    assert "credentials" in json.loads(captured.err)["error"]


def test_classify_config_default_engine_llm_is_used(
    scrolls_home, fake_wikipedia_api, fake_llm, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()
    (scrolls_home / "config.toml").write_text('[classify]\ndefault_engine = "llm"\n')

    exit_code = main(["classify"])
    assert exit_code == 0
    assert len(fake_llm) == 1
    stored = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    assert stored.provenance["classified_by"] == "llm-v1"


def test_classify_engine_flag_overrides_config(
    scrolls_home, fake_wikipedia_api, fake_llm, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()
    (scrolls_home / "config.toml").write_text('[classify]\ndefault_engine = "llm"\n')

    exit_code = main(["classify", "--engine", "rules"])
    assert exit_code == 0
    assert fake_llm == []
    stored = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    assert stored.provenance["classified_by"] == "rules-v1"


def test_classify_config_llm_model_is_used(
    scrolls_home, fake_wikipedia_api, fake_llm, monkeypatch, capsys
):
    monkeypatch.delenv("SCROLLS_LLM_MODEL", raising=False)
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()
    (scrolls_home / "config.toml").write_text(
        '[classify]\nllm_model = "claude-haiku-4-5"\n'
    )

    exit_code = main(["classify", "--engine", "llm"])
    assert exit_code == 0
    assert fake_llm[0]["model"] == "claude-haiku-4-5"


def test_classify_env_model_beats_config(
    scrolls_home, fake_wikipedia_api, fake_llm, monkeypatch, capsys
):
    monkeypatch.setenv("SCROLLS_LLM_MODEL", "claude-sonnet-4-6")
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()
    (scrolls_home / "config.toml").write_text(
        '[classify]\nllm_model = "claude-haiku-4-5"\n'
    )

    exit_code = main(["classify", "--engine", "llm"])
    assert exit_code == 0
    assert fake_llm[0]["model"] == "claude-sonnet-4-6"


def test_classify_malformed_config_is_an_error_envelope(
    scrolls_home, fake_wikipedia_api, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()
    (scrolls_home / "config.toml").write_text("[classify\nbroken =")

    exit_code = main(["classify"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "config.toml" in json.loads(captured.err)["error"]


@pytest.fixture
def fake_fieldtheory_root(tmp_path):
    """A miniature ~/.fieldtheory archive with one classified bookmark."""
    record = {
        "id": "1111",
        "tweetId": "1111",
        "url": "https://x.com/karpathy/status/1111",
        "text": "SQLite FTS5 is criminally underrated for local search.",
        "authorHandle": "karpathy",
        "authorName": "Andrej Karpathy",
        "postedAt": "Mon Jun 01 15:34:00 +0000 2026",
        "bookmarkedAt": None,
        "syncedAt": "2026-06-04T04:27:46.057Z",
        "media": [],
        "mediaObjects": [],
        "links": ["https://sqlite.org/fts5.html"],
        "tags": [],
    }
    root = tmp_path / "fieldtheory"
    (root / "bookmarks").mkdir(parents=True)
    (root / "bookmarks" / "bookmarks.jsonl").write_text(json.dumps(record) + "\n")
    pages = root / "library" / "bookmarks"
    pages.mkdir(parents=True)
    (pages / "2026-06-01-karpathy.md").write_text(
        '---\ncategory: technique\ndomain: databases\ntweet_id: "1111"\n---\n'
    )
    return root


def test_import_fieldtheory_end_to_end(scrolls_home, fake_fieldtheory_root, capsys):
    exit_code = main(["import", "fieldtheory", "--root", str(fake_fieldtheory_root)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"imported": 1, "skipped": 0, "failed": 0, "failures": []}

    stored = get_item(get_paths().db_path, "x:1111")
    assert stored.stage == "fetched"
    assert stored.category == "technique"
    assert stored.domain == "databases"
    assert stored.saved_at == "2026-06-04T04:27:46+00:00"

    # the imported bookmark flows through md and search unchanged
    main(["md"])
    capsys.readouterr()
    exit_code = main(["search", "criminally underrated"])
    assert exit_code == 0
    hits = json.loads(capsys.readouterr().out)
    assert [hit["id"] for hit in hits] == ["x:1111"]
    scroll = scrolls_home / "scrolls" / "x"
    assert list(scroll.glob("*.md"))


def test_import_fieldtheory_is_idempotent(scrolls_home, fake_fieldtheory_root, capsys):
    main(["import", "fieldtheory", "--root", str(fake_fieldtheory_root)])
    capsys.readouterr()
    exit_code = main(["import", "fieldtheory", "--root", str(fake_fieldtheory_root)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"imported": 0, "skipped": 1, "failed": 0, "failures": []}


def test_import_fieldtheory_never_overwrites_existing_item(
    scrolls_home, fake_fieldtheory_root, capsys
):
    main(["import", "fieldtheory", "--root", str(fake_fieldtheory_root)])
    import dataclasses
    item = get_item(get_paths().db_path, "x:1111")
    update_item(get_paths().db_path, dataclasses.replace(item, category="tool"))
    main(["import", "fieldtheory", "--root", str(fake_fieldtheory_root)])
    assert get_item(get_paths().db_path, "x:1111").category == "tool"


def test_import_fieldtheory_reports_bad_lines(scrolls_home, fake_fieldtheory_root, capsys):
    jsonl = fake_fieldtheory_root / "bookmarks" / "bookmarks.jsonl"
    jsonl.write_text("not json\n" + jsonl.read_text())
    exit_code = main(["import", "fieldtheory", "--root", str(fake_fieldtheory_root)])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 1
    assert payload["failed"] == 1
    assert payload["failures"][0]["line"] == 1


def test_import_fieldtheory_missing_archive_is_an_error(scrolls_home, tmp_path, capsys):
    exit_code = main(["import", "fieldtheory", "--root", str(tmp_path / "nowhere")])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


@pytest.fixture
def fake_takeout_zip(tmp_path):
    """A miniature Takeout zip: two watches of one video, plus one ad."""
    import zipfile

    entries = [
        {
            "header": "YouTube",
            "title": "Watched How SQLite FTS Works",
            "titleUrl": "https://www.youtube.com/watch?v=abc123xyz00",
            "subtitles": [{"name": "Some Channel"}],
            "time": "2025-03-01T09:00:00.000Z",
        },
        {
            "header": "YouTube",
            "title": "Watched Buy Our Thing",
            "titleUrl": "https://www.youtube.com/watch?v=advideo0001",
            "details": [{"name": "From Google Ads"}],
            "time": "2025-01-02T00:00:00.000Z",
        },
        {
            "header": "YouTube",
            "title": "Watched How SQLite FTS Works",
            "titleUrl": "https://www.youtube.com/watch?v=abc123xyz00",
            "subtitles": [{"name": "Some Channel"}],
            "time": "2024-10-12T18:23:45.123Z",
        },
    ]
    archive = tmp_path / "takeout.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "Takeout/YouTube and YouTube Music/history/watch-history.json",
            json.dumps(entries),
        )
    return archive


def test_import_google_takeout_end_to_end(scrolls_home, fake_takeout_zip, capsys):
    exit_code = main(["import", "google-takeout", str(fake_takeout_zip)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "imported": 1,
        "skipped": 0,
        "events": 3,
        "repeats": 1,
        "ignored": {"ads": 1, "no_url": 0, "not_video": 0},
    }

    stored = get_item(get_paths().db_path, "youtube:abc123xyz00")
    assert stored.stage == "detected"
    assert stored.title == "How SQLite FTS Works"
    assert stored.author == "Some Channel"
    assert stored.saved_at == "2024-10-12T18:23:45+00:00"  # earliest watch


def test_import_google_takeout_is_idempotent(scrolls_home, fake_takeout_zip, capsys):
    main(["import", "google-takeout", str(fake_takeout_zip)])
    capsys.readouterr()
    exit_code = main(["import", "google-takeout", str(fake_takeout_zip)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 0
    assert payload["skipped"] == 1


def test_import_google_takeout_never_overwrites_existing_item(
    scrolls_home, fake_takeout_zip, capsys
):
    main(["add", "https://www.youtube.com/watch?v=abc123xyz00"])
    main(["import", "google-takeout", str(fake_takeout_zip)])
    # `add` registered the item without a title; import must not touch it
    assert get_item(get_paths().db_path, "youtube:abc123xyz00").title is None


def test_import_google_takeout_missing_export_is_an_error(scrolls_home, tmp_path, capsys):
    exit_code = main(["import", "google-takeout", str(tmp_path / "nowhere")])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


@pytest.fixture
def fake_bookmarks_html(tmp_path):
    """A miniature browser export: one folder, one bookmarklet, one repeat."""
    export = """\
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 PERSONAL_TOOLBAR_FOLDER="true">Bookmarks bar</H3>
    <DL><p>
        <DT><H3>Databases</H3>
        <DL><p>
            <DT><A HREF="https://www.youtube.com/watch?v=abc123xyz00" ADD_DATE="1614556800">How SQLite FTS Works</A>
            <DT><A HREF="https://www.youtube.com/watch?v=abc123xyz00" ADD_DATE="1700000000">same video again</A>
        </DL><p>
        <DT><A HREF="javascript:void(0)" ADD_DATE="1610000000">Bookmarklet</A>
    </DL><p>
</DL><p>
"""
    path = tmp_path / "bookmarks.html"
    path.write_text(export, encoding="utf-8")
    return path


def test_import_bookmarks_end_to_end(scrolls_home, fake_bookmarks_html, capsys):
    exit_code = main(["import", "bookmarks", str(fake_bookmarks_html)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "imported": 1,
        "skipped": 0,
        "bookmarks": 3,
        "repeats": 1,
        "ignored": {"not_http": 1, "no_url": 0},
    }

    stored = get_item(get_paths().db_path, "youtube:abc123xyz00")
    assert stored.stage == "detected"
    assert stored.title == "How SQLite FTS Works"
    assert stored.tags == ("Databases",)
    assert stored.saved_at == "2021-03-01T00:00:00+00:00"  # earliest ADD_DATE


def test_import_bookmarks_is_idempotent(scrolls_home, fake_bookmarks_html, capsys):
    main(["import", "bookmarks", str(fake_bookmarks_html)])
    capsys.readouterr()
    exit_code = main(["import", "bookmarks", str(fake_bookmarks_html)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 0
    assert payload["skipped"] == 1


def test_import_bookmarks_never_overwrites_existing_item(
    scrolls_home, fake_bookmarks_html, capsys
):
    main(["add", "https://www.youtube.com/watch?v=abc123xyz00"])
    main(["import", "bookmarks", str(fake_bookmarks_html)])
    # `add` registered the item without a title; import must not touch it
    assert get_item(get_paths().db_path, "youtube:abc123xyz00").title is None


def test_import_bookmarks_missing_file_is_an_error(scrolls_home, tmp_path, capsys):
    exit_code = main(["import", "bookmarks", str(tmp_path / "nowhere.html")])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


@pytest.fixture
def fake_pocket_csv(tmp_path):
    """A miniature Pocket export: one video, one repeat, one blank URL."""
    export = (
        "title,url,time_added,tags,status\n"
        "How SQLite FTS Works,https://www.youtube.com/watch?v=abc123xyz00,1700000000,db|search,unread\n"
        "same video again,https://www.youtube.com/watch?v=abc123xyz00,1600000000,,archive\n"
        ",,1600000000,,unread\n"
    )
    path = tmp_path / "part_000000.csv"
    path.write_text(export, encoding="utf-8")
    return path


def test_import_pocket_end_to_end(scrolls_home, fake_pocket_csv, capsys):
    exit_code = main(["import", "pocket", str(fake_pocket_csv)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "imported": 1,
        "skipped": 0,
        "rows": 3,
        "repeats": 1,
        "ignored": {"no_url": 1, "not_http": 0},
        "status": {"unread": 1, "archive": 1},
    }

    stored = get_item(get_paths().db_path, "youtube:abc123xyz00")
    assert stored.stage == "detected"
    assert stored.title == "same video again"  # earliest save's row wins
    assert stored.tags == ("db", "search")
    assert stored.saved_at == "2020-09-13T12:26:40+00:00"  # earliest time_added


def test_import_pocket_is_idempotent(scrolls_home, fake_pocket_csv, capsys):
    main(["import", "pocket", str(fake_pocket_csv)])
    capsys.readouterr()
    exit_code = main(["import", "pocket", str(fake_pocket_csv)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 0
    assert payload["skipped"] == 1


def test_import_pocket_never_overwrites_existing_item(
    scrolls_home, fake_pocket_csv, capsys
):
    main(["add", "https://www.youtube.com/watch?v=abc123xyz00"])
    main(["import", "pocket", str(fake_pocket_csv)])
    # `add` registered the item without a title; import must not touch it
    assert get_item(get_paths().db_path, "youtube:abc123xyz00").title is None


def test_import_pocket_missing_file_is_an_error(scrolls_home, tmp_path, capsys):
    exit_code = main(["import", "pocket", str(tmp_path / "nowhere.csv")])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


@pytest.fixture
def fake_opml(tmp_path):
    """A miniature OPML export: a foldered feed, a top-level feed, a duplicate."""
    export = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<opml version="2.0"><head><title>Subscriptions</title></head><body>'
        '<outline text="Blogs">'
        '<outline type="rss" text="A Weblog" xmlUrl="https://blog.example.com/atom.xml"/>'
        "</outline>"
        '<outline type="rss" text="News" xmlUrl="https://news.example.com/rss"/>'
        '<outline type="rss" text="dup" xmlUrl="https://blog.example.com/atom.xml"/>'
        "</body></opml>"
    )
    path = tmp_path / "subscriptions.opml"
    path.write_text(export, encoding="utf-8")
    return path


def test_import_opml_registers_subscriptions(scrolls_home, fake_opml, capsys):
    exit_code = main(["import", "opml", str(fake_opml)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "imported": 2,
        "skipped": 0,
        "feeds": 3,
        "repeats": 1,
        "ignored": {"not_http": 0},
    }

    # the subscriptions are queryable through the same path `scrolls follow` lists,
    # with no sync state yet so the first sync discovers their entries
    subs = list_subscriptions(get_paths().db_path)
    assert {s.feed_url for s in subs} == {
        "https://blog.example.com/atom.xml",
        "https://news.example.com/rss",
    }
    assert all(s.last_synced_at is None and s.etag is None for s in subs)


def test_import_opml_dedupes_against_a_prior_follow(scrolls_home, fake_feeds, fake_opml, capsys):
    # a feed already followed manually is the same subscription id an import mints,
    # so the import skips it instead of duplicating it
    main(["follow", "https://blog.example.com/atom.xml"])
    capsys.readouterr()
    main(["import", "opml", str(fake_opml)])
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 1  # only the news feed is new
    assert payload["skipped"] == 1  # the already-followed weblog


def test_import_opml_is_idempotent(scrolls_home, fake_opml, capsys):
    main(["import", "opml", str(fake_opml)])
    capsys.readouterr()
    exit_code = main(["import", "opml", str(fake_opml)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 0
    assert payload["skipped"] == 2


def test_import_opml_missing_file_is_an_error(scrolls_home, tmp_path, capsys):
    exit_code = main(["import", "opml", str(tmp_path / "nowhere.opml")])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_export_opml_emits_subscriptions(scrolls_home, fake_opml, capsys):
    main(["import", "opml", str(fake_opml)])
    capsys.readouterr()
    exit_code = main(["export", "opml"])
    assert exit_code == 0
    out = capsys.readouterr().out
    # the OPML document is emitted raw on stdout (not JSON), declaration first
    assert out.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert 'xmlUrl="https://blog.example.com/atom.xml"' in out
    assert 'xmlUrl="https://news.example.com/rss"' in out


def test_export_opml_round_trips_through_import(scrolls_home, fake_opml, tmp_path, capsys):
    main(["import", "opml", str(fake_opml)])
    capsys.readouterr()
    main(["export", "opml"])
    exported = capsys.readouterr().out

    # re-importing the export reproduces the same subscriptions: skipped, not new
    out_path = tmp_path / "round-trip.opml"
    out_path.write_text(exported, encoding="utf-8")
    exit_code = main(["import", "opml", str(out_path)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 0
    assert payload["skipped"] == 2


def test_export_opml_empty_library_is_valid(scrolls_home, capsys):
    main(["init"])
    capsys.readouterr()
    exit_code = main(["export", "opml"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert '<opml version="2.0">' in out  # a valid, empty OPML document


def test_export_bookmarks_emits_items(scrolls_home, fake_bookmarks_html, capsys):
    main(["import", "bookmarks", str(fake_bookmarks_html)])
    capsys.readouterr()
    exit_code = main(["export", "bookmarks"])
    assert exit_code == 0
    out = capsys.readouterr().out
    # the bookmark file is emitted raw on stdout (not JSON), the DOCTYPE first
    assert out.startswith("<!DOCTYPE NETSCAPE-Bookmark-file-1>")
    assert 'HREF="https://www.youtube.com/watch?v=abc123xyz00"' in out
    assert ">How SQLite FTS Works</A>" in out
    assert 'TAGS="Databases"' in out  # the import's folder tag rides back out


def test_export_bookmarks_round_trips_through_import(
    scrolls_home, fake_bookmarks_html, tmp_path, capsys
):
    main(["import", "bookmarks", str(fake_bookmarks_html)])
    capsys.readouterr()
    main(["export", "bookmarks"])
    exported = capsys.readouterr().out

    # re-importing the export reproduces the same item: skipped, not new
    out_path = tmp_path / "round-trip.html"
    out_path.write_text(exported, encoding="utf-8")
    exit_code = main(["import", "bookmarks", str(out_path)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 0
    assert payload["skipped"] == 1


def test_export_bookmarks_empty_library_is_valid(scrolls_home, capsys):
    main(["init"])
    capsys.readouterr()
    exit_code = main(["export", "bookmarks"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "<!DOCTYPE NETSCAPE-Bookmark-file-1>" in out  # a valid, empty document
    assert "<DT>" not in out


def test_export_bookmarks_source_filter_scopes_the_export(scrolls_home, capsys):
    main(["add", "https://github.com/sqlite/sqlite"])
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()
    exit_code = main(["export", "bookmarks", "--source", "github"])
    assert exit_code == 0
    out = capsys.readouterr().out
    # only the one source's item is exported; the wikipedia one is held back
    assert "https://github.com/sqlite/sqlite" in out
    assert "en.wikipedia.org" not in out


def test_export_bookmarks_tag_filter_scopes_the_export(scrolls_home, capsys):
    main(["add", "https://example.com/a"])
    main(["add", "https://example.com/b"])
    main(["set", "https://example.com/a", "tags=keep"])
    capsys.readouterr()
    exit_code = main(["export", "bookmarks", "--tag", "keep"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "https://example.com/a" in out
    assert "https://example.com/b" not in out


def _seed_rich_item(scrolls_home):
    """A fully-populated rendered item, so the lossless round-trip is real."""
    main(["init"])
    item = ScrollItem(
        id="arxiv:1706.03762",
        source="arxiv",
        url="https://arxiv.org/abs/1706.03762",
        saved_at="2026-06-12T08:00:00+00:00",
        source_id="1706.03762",
        title="Attention Is All You Need",
        author="Ashish Vaswani et al.",
        extracted_text="The dominant sequence transduction models…",
        summary="We propose the Transformer.",
        category="paper",
        domain="machine learning",
        tags=("cs.CL", "cs.LG"),
        concepts=("Attention",),
        links=("https://doi.org/10.5555/3295222",),
        media=({"type": "pdf", "url": "https://arxiv.org/pdf/1706.03762"},),
        content_hash="sha256:abc",
        markdown_path="scrolls/arxiv/attention-is-all-you-need.md",
        provenance={"adapter": "arxiv", "extraction_method": "arxiv-atom+pypdf"},
        stage="rendered",
    )
    insert_item(get_paths().db_path, item)
    return item


def test_export_items_emits_jsonl_to_stdout(scrolls_home, capsys):
    _seed_rich_item(scrolls_home)
    capsys.readouterr()
    exit_code = main(["export", "items"])
    assert exit_code == 0
    out = capsys.readouterr().out
    # one JSON object per line, raw on stdout (not a JSON envelope), lossless
    record = json.loads(out.splitlines()[0])
    assert record["id"] == "arxiv:1706.03762"
    assert record["extracted_text"] == "The dominant sequence transduction models…"
    assert record["provenance"]["adapter"] == "arxiv"
    assert record["media"][0]["type"] == "pdf"


def test_export_items_round_trips_through_import(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    seeded = _seed_rich_item(scrolls_home)
    capsys.readouterr()
    main(["export", "items"])
    exported = capsys.readouterr().out
    out_path = tmp_path / "library.jsonl"
    out_path.write_text(exported, encoding="utf-8")

    # import into a *fresh* library: a full, faithful restore of the item
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "restored-home"))
    exit_code = main(["import", "items", str(out_path)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "imported": 1,
        "skipped": 0,
        "unchanged": 0,
        "conflict": 0,
        "adopted": [],
        "conflicts": [],
        # a single fresh item into an empty library — no byte-identical sibling (H353)
        "content_duplicates": 0,
        "items": 1,
    }
    restored = get_item(get_paths().db_path, "arxiv:1706.03762")
    assert restored == seeded  # every field survived the round-trip


def test_import_items_is_idempotent(scrolls_home, tmp_path, capsys):
    _seed_rich_item(scrolls_home)
    capsys.readouterr()
    main(["export", "items"])
    out_path = tmp_path / "library.jsonl"
    out_path.write_text(capsys.readouterr().out, encoding="utf-8")
    # re-importing into the same library skips the already-present item — and the
    # skip is an honest `unchanged` no-op (identical content_hash), not a conflict
    exit_code = main(["import", "items", str(out_path)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "imported": 0,
        "skipped": 1,
        "unchanged": 1,
        "conflict": 0,
        "adopted": [],
        "conflicts": [],
        # nothing was freshly inserted, so the import added no redundant copy (H353)
        "content_duplicates": 0,
        "items": 1,
    }


def test_import_items_never_overwrites_existing_item(scrolls_home, tmp_path, capsys):
    seeded = _seed_rich_item(scrolls_home)
    capsys.readouterr()
    main(["export", "items"])
    exported = capsys.readouterr().out
    # mutate the stored row, then re-import the *old* export: INSERT OR IGNORE
    # keeps the current row rather than reverting it
    update_item(get_paths().db_path, dataclasses.replace(seeded, title="Edited"))
    out_path = tmp_path / "library.jsonl"
    out_path.write_text(exported, encoding="utf-8")
    main(["import", "items", str(out_path)])
    assert get_item(get_paths().db_path, "arxiv:1706.03762").title == "Edited"


def test_import_items_title_only_edit_is_unchanged_not_a_conflict(
    scrolls_home, tmp_path, capsys
):
    """A skip whose held row differs only in a *derived/metadata* field (title)
    is `unchanged`, not a `conflict` — the conflict signal is content-custody
    (the `content_hash` the verify ledger drifts on), not every column. A title
    edit does not change `content_hash`, so the captured content is identical."""
    seeded = _seed_rich_item(scrolls_home)
    capsys.readouterr()
    main(["export", "items"])
    exported = capsys.readouterr().out
    update_item(get_paths().db_path, dataclasses.replace(seeded, title="Edited"))
    out_path = tmp_path / "library.jsonl"
    out_path.write_text(exported, encoding="utf-8")
    main(["import", "items", str(out_path)])
    payload = json.loads(capsys.readouterr().out)
    assert payload["unchanged"] == 1
    assert payload["conflict"] == 0 and payload["conflicts"] == []


def test_import_items_surfaces_a_content_conflict(scrolls_home, tmp_path, capsys):
    """A held id re-imported with a *different* `content_hash` is surfaced as a
    `conflict`, never silently swallowed — and the held copy is never overwritten
    (custody vision §2.4: a conflict is a recorded, surfaced event, not an
    overwrite). The obsidian reconcile adoption: surface, don't silently rewrite."""
    from scrolls.items_export import dump_items_export

    _seed_rich_item(scrolls_home)
    capsys.readouterr()
    # an incoming row for the *same id* but a divergent capture (different
    # content_hash + body) — e.g. another library's copy captured at another time
    held = get_item(get_paths().db_path, "arxiv:1706.03762")
    divergent = dataclasses.replace(
        held, content_hash="sha256:moved", extracted_text="A different capture…"
    )
    out_path = tmp_path / "incoming.jsonl"
    out_path.write_text(dump_items_export([divergent]), encoding="utf-8")

    exit_code = main(["import", "items", str(out_path)])
    assert exit_code == 0
    out, err = capsys.readouterr()
    payload = json.loads(out)
    assert payload == {
        "imported": 0,
        "skipped": 1,
        "unchanged": 0,
        "conflict": 1,
        "adopted": [],
        "conflicts": ["arxiv:1706.03762"],
        # a conflict is a same-id divergence, not a freshly-inserted copy — no content
        # duplicate added (H353); the two notices are distinct custody axes
        "content_duplicates": 0,
        "items": 1,
    }
    # the held copy is preserved byte-for-byte — surfaced, never overwritten
    kept = get_item(get_paths().db_path, "arxiv:1706.03762")
    assert kept.content_hash == "sha256:abc"
    assert kept.extracted_text == "The dominant sequence transduction models…"
    # loud, not silent: a stderr warning names the conflicting id (the
    # `_warn_orphan_events` idiom — a content divergence is a custody signal)
    warning = json.loads(err)
    assert "arxiv:1706.03762" in warning["warning"]
    assert "conflict" in warning["warning"].lower()


def test_import_items_partitions_a_mixed_batch(scrolls_home, tmp_path, capsys):
    """One import can carry a new row, an identical re-import, and a divergent
    copy of a held id — partitioned into imported / unchanged / conflict, with
    `skipped == unchanged + conflict` (the coherence invariant) and the conflict
    ids sorted and uncapped (the M2 structured-completeness idiom)."""
    from scrolls.items_export import dump_items_export

    held = _seed_rich_item(scrolls_home)
    capsys.readouterr()
    fresh = dataclasses.replace(
        held,
        id="web:fresh",
        source="web",
        url="https://example.com/fresh",
        content_hash="sha256:fresh",
    )
    same = held  # identical → unchanged
    divergent = dataclasses.replace(held, content_hash="sha256:moved")
    out_path = tmp_path / "incoming.jsonl"
    out_path.write_text(
        dump_items_export([fresh, same, divergent]), encoding="utf-8"
    )

    main(["import", "items", str(out_path)])
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 1  # web:fresh
    assert payload["unchanged"] == 1  # the identical re-import
    assert payload["conflict"] == 1  # the divergent copy of arxiv:1706.03762
    assert payload["conflicts"] == ["arxiv:1706.03762"]
    # the coherence invariant: every skip is exactly one of unchanged | conflict
    assert payload["skipped"] == payload["unchanged"] + payload["conflict"]


def _incoming_item(item_id, content_hash, *, source="web", body="body"):
    """A model-complete incoming row (a lossless `import items` line) for the
    content-duplicate-on-import tests — its `content_hash` is what content identity
    folds on (roadmap H353). A `None` body + `None` hash makes a reference-only row."""
    return ScrollItem(
        id=item_id,
        source=source,
        url=f"https://e.com/{item_id.replace(':', '_')}",
        saved_at="2026-06-20T00:00:00+00:00",
        title=f"title {item_id}",
        extracted_text=body,
        raw_text=f"<r>{body}</r>" if body is not None else None,
        content_hash=content_hash,
        stage="rendered" if body is not None else "detected",
    )


def test_import_items_reports_a_content_duplicate_against_a_held_copy(
    scrolls_home, tmp_path, capsys
):
    """H353: a freshly-imported row that lands byte-identical to a *distinct held id*
    is counted in `content_duplicates` — the import-time, point-in-time counterpart
    of `doctor`'s whole-library `custody.content_duplicates`. Report-only: the held
    copy is untouched, no stderr warning rides (a redundancy fact, not a divergence),
    and the count points an operator at the existing prune flow."""
    from scrolls.items_export import dump_items_export

    main(["init"])
    db = get_paths().db_path
    insert_item(db, _incoming_item("web:held", "sha256:dup"))
    capsys.readouterr()

    # an incoming row under a *new* id but the *same* bytes (a mirror saved twice)
    out_path = tmp_path / "incoming.jsonl"
    out_path.write_text(
        dump_items_export([_incoming_item("web:mirror", "sha256:dup")]), encoding="utf-8"
    )
    assert main(["import", "items", str(out_path)]) == 0
    out, err = capsys.readouterr()
    payload = json.loads(out)
    assert payload["imported"] == 1
    assert payload["content_duplicates"] == 1  # the mirror is redundant with web:held
    # report-only: the held copy is preserved and no stderr warning rides (a content
    # duplicate is a redundancy fact, never a defect — unlike a conflict)
    assert get_item(db, "web:held").content_hash == "sha256:dup"
    assert err == ""
    # converges with the whole-library report: both members are now a flagged group
    main(["doctor"])
    dup = json.loads(capsys.readouterr().out)["custody"]["content_duplicates"]
    members = {item_id for group in dup["groups"] for item_id in group["ids"]}
    assert members == {"web:held", "web:mirror"}


def test_import_items_reports_content_duplicates_within_the_same_import(
    scrolls_home, tmp_path, capsys
):
    """H353: the "or to another row in the same import" leg — two freshly-imported
    rows byte-identical to *each other* (neither held before) both count, so a single
    import of a redundant pair reports `content_duplicates == 2`."""
    from scrolls.items_export import dump_items_export

    main(["init"])
    capsys.readouterr()
    out_path = tmp_path / "pair.jsonl"
    out_path.write_text(
        dump_items_export([
            _incoming_item("web:one", "sha256:same"),
            _incoming_item("web:two", "sha256:same"),
        ]),
        encoding="utf-8",
    )
    assert main(["import", "items", str(out_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 2
    assert payload["content_duplicates"] == 2


def test_import_items_content_duplicates_is_zero_on_an_idempotent_reimport(
    scrolls_home, tmp_path, capsys
):
    """H353: the notice is scoped to what *this* import freshly inserts, so a clean
    re-import of an already-held redundant pair adds nothing — `content_duplicates`
    falls to 0 even though the library still holds the duplicate group (that standing
    redundancy is `doctor`'s job, not the import's). Idempotent and honest."""
    from scrolls.items_export import dump_items_export

    main(["init"])
    capsys.readouterr()
    out_path = tmp_path / "pair.jsonl"
    out_path.write_text(
        dump_items_export([
            _incoming_item("web:one", "sha256:same"),
            _incoming_item("web:two", "sha256:same"),
        ]),
        encoding="utf-8",
    )
    main(["import", "items", str(out_path)])
    assert json.loads(capsys.readouterr().out)["content_duplicates"] == 2

    # re-import the identical batch: every row is `unchanged`, nothing freshly added
    main(["import", "items", str(out_path)])
    second = json.loads(capsys.readouterr().out)
    assert second["imported"] == 0 and second["unchanged"] == 2
    assert second["content_duplicates"] == 0  # added no redundant copy this run

    # but the standing whole-library redundancy is unchanged — still one group
    main(["doctor"])
    dup = json.loads(capsys.readouterr().out)["custody"]["content_duplicates"]
    assert dup["total_groups"] == 1


def test_import_items_content_duplicates_is_zero_for_a_unique_import(
    scrolls_home, tmp_path, capsys
):
    """H353: distinct content earns no notice — two rows with different bytes, none
    held, report `content_duplicates == 0`."""
    from scrolls.items_export import dump_items_export

    main(["init"])
    capsys.readouterr()
    out_path = tmp_path / "unique.jsonl"
    out_path.write_text(
        dump_items_export([
            _incoming_item("web:a", "sha256:aaa"),
            _incoming_item("web:b", "sha256:bbb"),
        ]),
        encoding="utf-8",
    )
    main(["import", "items", str(out_path)])
    assert json.loads(capsys.readouterr().out)["content_duplicates"] == 0


def test_import_items_content_duplicates_skips_null_hash_references(
    scrolls_home, tmp_path, capsys
):
    """H353: a reference-only row holds no captured bytes (NULL `content_hash`), so it
    fingerprints nothing — importing two such rows counts no content duplicate (the
    H325 NULL-safe rule, the same skip the whole-library fold makes)."""
    from scrolls.items_export import dump_items_export

    main(["init"])
    capsys.readouterr()
    out_path = tmp_path / "refs.jsonl"
    out_path.write_text(
        dump_items_export([
            _incoming_item("web:r1", None, body=None),
            _incoming_item("web:r2", None, body=None),
        ]),
        encoding="utf-8",
    )
    main(["import", "items", str(out_path)])
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 2
    assert payload["content_duplicates"] == 0


def test_merge_item_classifies_the_insert_outcome(scrolls_home):
    """The shared primitive: a new id imports, an identical re-insert is
    `unchanged`, a same-id/different-`content_hash` re-insert is a `conflict`,
    and the held row is never overwritten."""
    from scrolls.items import get_item, merge_item

    held = _seed_rich_item(scrolls_home)
    db = get_paths().db_path
    fresh = dataclasses.replace(
        held, id="web:new", source="web", url="https://example.com/new"
    )
    assert merge_item(db, fresh) == "imported"
    assert merge_item(db, fresh) == "unchanged"  # identical re-insert
    divergent = dataclasses.replace(fresh, content_hash="sha256:elsewhere")
    assert merge_item(db, divergent) == "conflict"
    # surfaced, never overwritten — the first capture's hash survives
    assert get_item(db, "web:new").content_hash == fresh.content_hash


def test_import_items_records_a_conflict_as_a_custody_event(
    scrolls_home, tmp_path, capsys
):
    """H274: a surfaced import conflict is no longer just a transient warning — it
    joins the append-only ledger as a typed `conflict` event on the held item
    (held vs incoming `content_hash`, stamped at import time), queryable on the
    per-item `scrolls history` timeline. Crucially it is a *distinct* axis: it
    never moves the item's drift posture (a peer disagreement is not evidence the
    live source moved — the M2 honesty)."""
    from scrolls.custody import drift_posture, item_events, latest_events
    from scrolls.items_export import dump_items_export

    _seed_rich_item(scrolls_home)
    db = get_paths().db_path
    capsys.readouterr()
    held = get_item(db, "arxiv:1706.03762")
    divergent = dataclasses.replace(
        held, content_hash="sha256:moved", extracted_text="A different capture…"
    )
    out_path = tmp_path / "incoming.jsonl"
    out_path.write_text(dump_items_export([divergent]), encoding="utf-8")

    assert main(["import", "items", str(out_path)]) == 0
    capsys.readouterr()

    # the divergence is now a recorded ledger event, not just a printed warning
    events = item_events(db, "arxiv:1706.03762")
    assert [e.status for e in events] == ["conflict"]
    conflict = events[0]
    assert conflict.prior_hash == "sha256:abc"  # what we hold (the kept copy)
    assert conflict.observed_hash == "sha256:moved"  # the incoming capture
    assert conflict.detail and "conflict" in conflict.detail.lower()

    # the conflict is a *distinct* axis — the drift posture stays `unverified`
    # (never re-checked against the live source); doctor's drift block, which folds
    # `latest_events`, is wholly unaffected by the conflict event
    assert drift_posture(latest_events(db).get("arxiv:1706.03762")) == "unverified"
    report = run_doctor(get_paths(), fix=False)
    assert report["custody"]["drift"]["checked"] == 0
    assert report["custody"]["drift"]["drifted"] == 0

    # the event is reachable straight from the CLI `scrolls history --status conflict`
    assert main(["history", "arxiv:1706.03762", "--status", "conflict"]) == 0
    timeline = json.loads(capsys.readouterr().out)
    assert [e["status"] for e in timeline] == ["conflict"]
    assert timeline[0]["observed_hash"] == "sha256:moved"


def test_import_items_clean_reimport_records_no_event(scrolls_home, tmp_path, capsys):
    """A clean (idempotent) re-import writes no ledger noise — `record_events`
    no-ops on the empty conflict list, so only a genuine divergence leaves a
    trace (the verify ledger's append-only honesty, conflict axis)."""
    from scrolls.custody import item_events
    from scrolls.items_export import dump_items_export

    seeded = _seed_rich_item(scrolls_home)
    db = get_paths().db_path
    capsys.readouterr()
    out_path = tmp_path / "incoming.jsonl"
    out_path.write_text(dump_items_export([seeded]), encoding="utf-8")

    assert main(["import", "items", str(out_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["unchanged"] == 1 and payload["conflict"] == 0
    # an idempotent re-import is a custody no-op — nothing recorded
    assert item_events(db, "arxiv:1706.03762") == []


def _import_a_divergent_copy(scrolls_home, tmp_path):
    """Seed an item, then `import items` a copy with a different content hash so the
    held item carries one recorded (unresolved) import conflict — the H275 fixture."""
    from scrolls.items_export import dump_items_export

    seeded = _seed_rich_item(scrolls_home)
    held = get_item(get_paths().db_path, seeded.id)
    divergent = dataclasses.replace(
        held, content_hash="sha256:moved", extracted_text="A different capture…"
    )
    out_path = tmp_path / "incoming.jsonl"
    out_path.write_text(dump_items_export([divergent]), encoding="utf-8")
    assert main(["import", "items", str(out_path)]) == 0
    return seeded


def test_doctor_custody_conflicts_surfaces_an_unresolved_import_conflict(
    scrolls_home, tmp_path, capsys
):
    """H275: `doctor`'s `custody.conflicts` is the scope-level read of the recorded
    import-conflict events (the read-aggregate sibling of `custody.drift`). After a
    divergent re-import, the held item carries one unresolved conflict the aggregate
    counts and lists with held-vs-incoming hashes — and it stays a *report* view
    (never `issues`/`fixed`/the exit code), wholly disjoint from the drift axis."""
    _import_a_divergent_copy(scrolls_home, tmp_path)
    capsys.readouterr()

    report = run_doctor(get_paths(), fix=False)
    conflicts = report["custody"]["conflicts"]
    assert conflicts["basis"] == "import_ledger"
    assert conflicts["items"] == 1
    assert conflicts["as_of"] is not None
    assert [e["id"] for e in conflicts["events"]] == ["arxiv:1706.03762"]
    event = conflicts["events"][0]
    assert event["status"] == "conflict"
    assert event["prior_hash"] == "sha256:abc"  # the held copy (kept, never overwritten)
    assert event["observed_hash"] == "sha256:moved"  # the incoming capture that disagreed

    # the conflict axis never bleeds into the drift axis (ADR 0104) — drift is empty
    assert report["custody"]["drift"]["checked"] == 0
    assert report["custody"]["drift"]["drifted"] == 0
    # and it is a report view, disjoint from the integrity-findings axis that drives
    # `custody.issues`/`score`: a conflict is never a per-item custody *finding*
    conflict_findings = [
        f for f in report["custody"]["findings"] if "conflict" in f["issues"]
    ]
    assert conflict_findings == []


def test_doctor_custody_conflicts_clean_library_is_empty(scrolls_home, capsys):
    """No recorded conflict ⇒ an honest empty aggregate (the drift block's
    zeroed-default shape), not a fabricated count."""
    _seed_rich_item(scrolls_home)
    capsys.readouterr()
    conflicts = run_doctor(get_paths(), fix=False)["custody"]["conflicts"]
    assert conflicts["items"] == 0
    assert conflicts["events"] == []
    assert conflicts["as_of"] is None


def test_doctor_custody_conflicts_excludes_a_since_deleted_item(
    scrolls_home, tmp_path, capsys
):
    """Held-filtered like the drift block: a conflict on an id no longer held is not
    this library's divergence, so removing the item clears the aggregate even though
    the ledger row survives (the `latest_events` held-filter precedent)."""
    seeded = _import_a_divergent_copy(scrolls_home, tmp_path)
    capsys.readouterr()
    assert run_doctor(get_paths(), fix=False)["custody"]["conflicts"]["items"] == 1

    assert delete_item(get_paths().db_path, seeded.id) is True
    conflicts = run_doctor(get_paths(), fix=False)["custody"]["conflicts"]
    assert conflicts["items"] == 0
    assert conflicts["events"] == []


def test_doctor_custody_conflicts_scopes_by_source(scrolls_home, tmp_path, capsys):
    """The aggregate folds over the (possibly `--source`-scoped) item set, so it
    scopes by source for free — a held item owns a source, so a conflict is
    source-attributable (unlike the cross-source `custody.works` alarm)."""
    _import_a_divergent_copy(scrolls_home, tmp_path)
    capsys.readouterr()
    # the conflicting item is an arxiv capture: the matching scope sees it…
    assert run_doctor(get_paths(), source="arxiv")["custody"]["conflicts"]["items"] == 1
    # …a disjoint source scope sees none (no arxiv item in its frame)
    other = run_doctor(get_paths(), source="github")["custody"]["conflicts"]
    assert other["items"] == 0
    assert other["events"] == []


# --- reconcile --keep-held: the operator act on a recorded conflict (H276, ADR 0105) ---


def test_reconcile_keep_held_resolves_a_recorded_conflict(
    scrolls_home, tmp_path, capsys
):
    """H276: `reconcile <id> --keep-held` is the operator act — it affirms the held
    copy, recording a `resolved` conflict-axis event that supersedes the open
    conflict so `doctor`'s `custody.conflicts` clears, while the held copy is never
    overwritten and the original `conflict` event survives on the timeline."""
    from scrolls.custody import item_events

    seeded = _import_a_divergent_copy(scrolls_home, tmp_path)
    db = get_paths().db_path
    held_before = get_item(db, seeded.id)
    assert run_doctor(get_paths(), fix=False)["custody"]["conflicts"]["items"] == 1
    capsys.readouterr()

    assert main(["reconcile", seeded.id, "--keep-held"]) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision == {
        "id": seeded.id,
        "resolved": True,
        "decision": "keep_held",
        "held_hash": "sha256:abc",         # the affirmed held copy
        "incoming_hash": "sha256:moved",   # the rejected incoming capture
        "dry_run": False,
    }

    # the aggregate (and every surface folding it) clears
    assert run_doctor(get_paths(), fix=False)["custody"]["conflicts"]["items"] == 0

    # the held copy is provably untouched — raw is sacred (custody §2.4)
    held_after = get_item(db, seeded.id)
    assert held_after.content_hash == held_before.content_hash == "sha256:abc"
    assert held_after.extracted_text == held_before.extracted_text

    # append-only: the original conflict survives, the resolution is a *new* row
    assert [e.status for e in item_events(db, seeded.id)] == ["resolved", "conflict"]


def test_reconcile_keep_held_is_idempotent(scrolls_home, tmp_path, capsys):
    """A second `reconcile --keep-held` after a resolution is an honest no-op
    (`resolved: false`) — the latest conflict-axis event is already `resolved`, so
    `current_conflict` returns None and nothing is recorded."""
    from scrolls.custody import item_events

    seeded = _import_a_divergent_copy(scrolls_home, tmp_path)
    db = get_paths().db_path
    assert main(["reconcile", seeded.id, "--keep-held"]) == 0
    capsys.readouterr()

    assert main(["reconcile", seeded.id, "--keep-held"]) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["resolved"] is False
    assert decision["reason"] == "no unresolved import conflict"
    # no second resolution row — the no-op records nothing
    assert [e.status for e in item_events(db, seeded.id)] == ["resolved", "conflict"]


def test_reconcile_dry_run_predicts_without_recording(scrolls_home, tmp_path, capsys):
    """`--dry-run` predicts the same decision the live run would emit (plus
    `dry_run: true`) but writes nothing — the conflict stays unresolved and no
    `resolved` event is recorded (the H245/H273 predict-the-write discipline)."""
    from scrolls.custody import item_events

    seeded = _import_a_divergent_copy(scrolls_home, tmp_path)
    db = get_paths().db_path
    capsys.readouterr()

    assert main(["reconcile", seeded.id, "--keep-held", "--dry-run"]) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["resolved"] is True
    assert decision["dry_run"] is True
    assert decision["held_hash"] == "sha256:abc"
    assert decision["incoming_hash"] == "sha256:moved"

    # nothing was written: the conflict is still unresolved and no resolution exists
    assert run_doctor(get_paths(), fix=False)["custody"]["conflicts"]["items"] == 1
    assert [e.status for e in item_events(db, seeded.id)] == ["conflict"]


def test_reconcile_requires_a_resolution_flag(scrolls_home, tmp_path, capsys):
    """A bare `reconcile <id>` (no resolution) is a loud usage error (exit 2) — a
    custody-changing write must carry an explicit operator decision, and nothing is
    written."""
    from scrolls.custody import item_events

    seeded = _import_a_divergent_copy(scrolls_home, tmp_path)
    db = get_paths().db_path
    capsys.readouterr()

    assert main(["reconcile", seeded.id]) == 2
    err = json.loads(capsys.readouterr().err)
    assert "keep-held" in err["error"]
    # the conflict is untouched — no resolution written
    assert [e.status for e in item_events(db, seeded.id)] == ["conflict"]


def test_reconcile_unknown_id_is_a_could_not_check(scrolls_home, capsys):
    """An unknown ref is a could-not-check (exit 1), the `history`/`verify`
    empty-vs-error split — never a silent success."""
    _seed_rich_item(scrolls_home)
    capsys.readouterr()
    assert main(["reconcile", "web:does-not-exist", "--keep-held"]) == 1
    err = json.loads(capsys.readouterr().err)
    assert "no such item" in err["error"]


def test_reconcile_held_item_with_no_conflict_is_a_noop(scrolls_home, capsys):
    """A held item that never carried a conflict is an honest no-op (`resolved:
    false`, exit 0) — there is nothing to reconcile, not an error."""
    seeded = _seed_rich_item(scrolls_home)
    capsys.readouterr()
    assert main(["reconcile", seeded.id, "--keep-held"]) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["resolved"] is False
    assert decision["reason"] == "no unresolved import conflict"


def test_reconcile_keeps_the_conflict_on_history_beside_the_resolved_row(
    scrolls_home, tmp_path, capsys
):
    """After a resolution, `history --status conflict` still surfaces the divergence
    (append-only — the record of *when* a peer disagreed is never destroyed) and
    `history --status resolved` surfaces the operator decision, both off the drift
    axis (`history --status drifted` is empty)."""
    seeded = _import_a_divergent_copy(scrolls_home, tmp_path)
    assert main(["reconcile", seeded.id, "--keep-held"]) == 0
    capsys.readouterr()

    assert main(["history", seeded.id, "--status", "conflict"]) == 0
    conflicts = json.loads(capsys.readouterr().out)
    assert [e["status"] for e in conflicts] == ["conflict"]
    assert conflicts[0]["observed_hash"] == "sha256:moved"

    assert main(["history", seeded.id, "--status", "resolved"]) == 0
    resolved = json.loads(capsys.readouterr().out)
    assert [e["status"] for e in resolved] == ["resolved"]
    assert resolved[0]["prior_hash"] == "sha256:abc"      # the affirmed held copy
    assert resolved[0]["observed_hash"] == "sha256:moved"  # the rejected capture

    assert main(["history", seeded.id, "--status", "drifted"]) == 0
    assert json.loads(capsys.readouterr().out) == []  # never on the drift axis


# --- import --accept-incoming (H278, ADR 0106): the content-bearing reconcile
# resolution that *adopts* the peer's capture — the first import-path write that
# changes a held capture, the held copy archived (recoverable) not destroyed. ---


def test_import_items_accept_incoming_adopts_and_archives_the_prior(
    scrolls_home, tmp_path, capsys
):
    """`import items --accept-incoming` replaces the held copy with the diverging
    incoming one — the held body becomes the incoming, a `superseded` event is
    recorded, and the prior capture is archived (recoverable), never destroyed
    (custody §2.4)."""
    from scrolls.custody import item_events

    seeded = _seed_rich_item(scrolls_home)
    db = get_paths().db_path
    held = get_item(db, seeded.id)
    divergent = dataclasses.replace(
        held, content_hash="sha256:moved", extracted_text="A different capture…"
    )
    out_path = tmp_path / "incoming.jsonl"
    out_path.write_text(dump_items_export([divergent]), encoding="utf-8")
    capsys.readouterr()

    assert main(["import", "items", str(out_path), "--accept-incoming"]) == 0
    out, err = capsys.readouterr()
    payload = json.loads(out)
    assert payload["adopted"] == ["arxiv:1706.03762"]
    assert payload["conflict"] == 0 and payload["conflicts"] == []
    # imported + unchanged + adopted totals the input; nothing left as a kept conflict
    assert payload["imported"] + payload["unchanged"] + len(payload["adopted"]) == 1
    # the held copy now carries the incoming content (the adoption happened)
    now_held = get_item(db, seeded.id)
    assert now_held.content_hash == "sha256:moved"
    assert now_held.extracted_text == "A different capture…"
    # …recorded as a `superseded` conflict-axis event (held→incoming hash)
    assert [e.status for e in item_events(db, seeded.id)] == ["superseded"]
    superseded = item_events(db, seeded.id)[0]
    assert superseded.prior_hash == "sha256:abc"       # the archived prior copy
    assert superseded.observed_hash == "sha256:moved"  # the adopted incoming copy
    # the prior capture is archived, recoverable byte-for-byte
    assert main(["archive", "show", seeded.id]) == 0
    recovered = json.loads(capsys.readouterr().out.splitlines()[0])
    assert recovered["content_hash"] == "sha256:abc"
    assert recovered["extracted_text"] == seeded.extracted_text
    # loud on stderr — a held copy was replaced (the operator asked, but it is a write)
    assert "arxiv:1706.03762" in json.loads(err)["warning"]


def test_import_items_accept_incoming_clears_the_conflict_aggregate(
    scrolls_home, tmp_path, capsys
):
    """Adopting the incoming capture clears `doctor`'s `custody.conflicts` and the
    `status` scalar — both gates agree (the latest axis event is `superseded`, and
    the held hash now equals the adopted one) — while the drift axis stays empty."""
    seeded = _import_a_divergent_copy(scrolls_home, tmp_path)
    db = get_paths().db_path
    # the divergence is open before the adoption
    assert run_doctor(get_paths(), fix=False)["custody"]["conflicts"]["items"] == 1

    # re-supply the same divergent content with --accept-incoming → adopt it
    held_now = get_item(db, seeded.id)  # still the original held copy
    divergent = dataclasses.replace(
        held_now, content_hash="sha256:moved", extracted_text="A different capture…"
    )
    out_path = tmp_path / "incoming2.jsonl"
    out_path.write_text(dump_items_export([divergent]), encoding="utf-8")
    capsys.readouterr()
    assert main(["import", "items", str(out_path), "--accept-incoming"]) == 0
    capsys.readouterr()

    report = run_doctor(get_paths(), fix=False)
    assert report["custody"]["conflicts"]["items"] == 0  # cleared on both gates
    assert report["custody"]["drift"]["checked"] == 0     # never on the drift axis
    # the original `conflict` event survives beside the `superseded` (append-only)
    assert main(["history", seeded.id]) == 0
    statuses = [e["status"] for e in json.loads(capsys.readouterr().out)]
    assert "conflict" in statuses and "superseded" in statuses


def test_import_items_accept_incoming_is_idempotent(scrolls_home, tmp_path, capsys):
    """Once adopted, re-importing the same content with --accept-incoming is an
    `unchanged` no-op — the held copy *is* the incoming now (no second archive,
    no second event). Idempotency falls out of the content-hash compare."""
    from scrolls.items import list_archived
    from scrolls.custody import item_events

    seeded = _seed_rich_item(scrolls_home)
    db = get_paths().db_path
    held = get_item(db, seeded.id)
    divergent = dataclasses.replace(held, content_hash="sha256:moved", raw_text="peer")
    out_path = tmp_path / "incoming.jsonl"
    out_path.write_text(dump_items_export([divergent]), encoding="utf-8")
    capsys.readouterr()

    assert main(["import", "items", str(out_path), "--accept-incoming"]) == 0
    json.loads(capsys.readouterr().out)
    # second --accept-incoming of the identical content: a clean no-op
    assert main(["import", "items", str(out_path), "--accept-incoming"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["adopted"] == [] and second["unchanged"] == 1
    # exactly one archive row and one supersession event — no churn on the no-op
    assert len(list_archived(db, seeded.id)) == 1
    assert [e.status for e in item_events(db, seeded.id)] == ["superseded"]


def test_archive_show_round_trips_back_through_accept_incoming(
    scrolls_home, tmp_path, capsys
):
    """The symmetric recovery the design rests on: after adopting the incoming, pipe
    `archive show` back through `import items --accept-incoming` to *restore* the
    prior capture — the held copy is the original again, the incoming now archived."""
    seeded = _seed_rich_item(scrolls_home)
    db = get_paths().db_path
    held = get_item(db, seeded.id)
    divergent = dataclasses.replace(
        held, content_hash="sha256:peer", extracted_text="peer body"
    )
    out_path = tmp_path / "incoming.jsonl"
    out_path.write_text(dump_items_export([divergent]), encoding="utf-8")
    capsys.readouterr()
    assert main(["import", "items", str(out_path), "--accept-incoming"]) == 0
    capsys.readouterr()
    assert get_item(db, seeded.id).content_hash == "sha256:peer"

    # recover the archived prior, write it out, and re-adopt it
    assert main(["archive", "show", seeded.id]) == 0
    restore_path = tmp_path / "restore.jsonl"
    restore_path.write_text(capsys.readouterr().out, encoding="utf-8")
    assert main(["import", "items", str(restore_path), "--accept-incoming"]) == 0
    capsys.readouterr()

    # the held copy is the original again, byte-for-byte
    assert get_item(db, seeded.id) == seeded


def test_archive_list_indexes_superseded_captures(scrolls_home, tmp_path, capsys):
    """`scrolls archive list` is the recovery index — the prior captures an
    accept-incoming replaced, with before/after hashes; `--id` scopes to one item.
    A clean library honestly holds nothing."""
    seeded = _seed_rich_item(scrolls_home)
    db = get_paths().db_path
    capsys.readouterr()
    # honest empty on a library that never adopted anything
    assert main(["archive", "list"]) == 0
    assert json.loads(capsys.readouterr().out) == {"count": 0, "archived": []}

    held = get_item(db, seeded.id)
    divergent = dataclasses.replace(held, content_hash="sha256:peer", raw_text="peer")
    out_path = tmp_path / "incoming.jsonl"
    out_path.write_text(dump_items_export([divergent]), encoding="utf-8")
    assert main(["import", "items", str(out_path), "--accept-incoming"]) == 0
    capsys.readouterr()

    assert main(["archive", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["count"] == 1
    entry = listed["archived"][0]
    assert entry["item_id"] == seeded.id
    assert entry["prior_hash"] == "sha256:abc"        # what was archived
    assert entry["superseded_by"] == "sha256:peer"    # what replaced it
    # --id scopes; an unrelated id has no archived priors
    assert main(["archive", "list", "--id", seeded.id]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 1


def test_archive_show_unknown_id_is_a_could_not_recover(scrolls_home, capsys):
    """`archive show` for an id with no archived prior (never superseded) exits 1 —
    the could-not-recover signal, like `verify`/`reconcile` on a missing target."""
    _seed_rich_item(scrolls_home)
    capsys.readouterr()
    assert main(["archive", "show", "arxiv:1706.03762"]) == 1
    err = json.loads(capsys.readouterr().err)
    assert "no archived prior" in err["error"]


def test_archive_show_all_emits_the_full_history_newest_first(
    scrolls_home, tmp_path, capsys
):
    """`archive show <id> --all` (H285) emits *every* archived prior as a JSONL
    stream, newest first — after three adoptions the archive holds three priors
    (the original + two intermediates), and `--all` re-emits all three (the
    default emits only the latest). Each line is a re-importable `export items`
    snapshot, so the whole recoverable history can be backed up, not just the head."""
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 3)
    capsys.readouterr()

    # --all emits the full history: three priors, newest first (v2, v1, then the
    # original abc — the prior each successive adoption displaced)
    assert main(["archive", "show", item_id, "--all"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    hashes = [json.loads(line)["content_hash"] for line in lines]
    assert hashes == ["sha256:v2", "sha256:v1", "sha256:abc"]

    # the default (no --all) still emits exactly one line — the latest prior — and
    # it is byte-identical to the --all stream's head (convergence by construction)
    assert main(["archive", "show", item_id]) == 0
    default_lines = capsys.readouterr().out.splitlines()
    assert len(default_lines) == 1
    assert main(["archive", "show", item_id, "--all"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == default_lines[0]


def test_archive_show_all_with_one_prior_is_a_single_line(
    scrolls_home, tmp_path, capsys
):
    """With a single archived prior, `--all` and the default agree exactly — the
    full history *is* the latest, one line."""
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 1)
    capsys.readouterr()
    assert main(["archive", "show", item_id, "--all"]) == 0
    all_out = capsys.readouterr().out
    assert main(["archive", "show", item_id]) == 0
    assert capsys.readouterr().out == all_out


def test_archive_show_all_unknown_id_is_a_could_not_recover(scrolls_home, capsys):
    """`archive show --all` for a never-superseded id exits 1 with the same
    could-not-recover signal as the single-snapshot read — an empty history is
    not a recovery."""
    _seed_rich_item(scrolls_home)
    capsys.readouterr()
    assert main(["archive", "show", "arxiv:1706.03762", "--all"]) == 1
    err = json.loads(capsys.readouterr().err)
    assert "no archived prior" in err["error"]


def test_archive_show_is_a_reproducible_recovery_artifact(
    scrolls_home, tmp_path, capsys
):
    """`archive show` is the archive-recovery transport (the superseded prior the
    un-launderable integrity alarm preserves, ADR 0106/H278/H285), and a recovery
    read must be a *reproducible artifact* (H385):

    1. `archive show <id>` of the same unchanged archived snapshot twice yields a
       **byte-identical** JSONL — both the single-prior default *and* the `--all`
       multi-prior fold (the order-sensitive `archived_snapshots` path the default
       never hits): an operator restoring from `archive show` on two machines must
       get byte-identical JSONL, and
    2. a real `archive show <id>` → `import items --accept-incoming` re-adopts the
       archived prior (the documented restore, _cmd_archive_show docstring) — the
       recovery round-trip a single-read identity check misses.

    The archive-recovery-transport sibling of
    `test_export_items_is_a_reproducible_artifact` (H379, the held-set backup): both
    fold `dump_items_export`, but this folds it over `item_archive` rows
    (`archived_snapshots`, `ORDER BY id DESC`) — a **distinct code path** from
    `list_items` no determinism test pins. H278/H285 pin the *adopted* disposition of
    the restore round-trip, not the JSONL *bytes*: a set-iteration leak in the
    multi-prior `archived_snapshots` fold (or an unsorted `item_archive` read) would
    pass those restore-outcome tests yet make two recovery reads disagree, breaking an
    operator who `diff`s two machines' recovery backups.

    **Decisive choices:** compare the *whole JSONL document* (not one row), exercise
    the `--all` multi-prior fold (the order-sensitive path the single-prior default
    never hits), and include the restore round-trip. Not cross-seed —
    `archived_snapshots` is an `ORDER BY id DESC` fold with no set to scramble across
    `PYTHONHASHSEED`s, so a same-process two-read check suffices (the H384 guidance).
    """
    # three adoptions → the archive holds three priors, newest first (v2, v1, abc),
    # so the `--all` fold is a real multi-line document, not a single row.
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 3)
    capsys.readouterr()

    # 1a. the single-prior default: two reads, no DB change between them, are
    #     byte-identical (the latest archived prior — v2 — the restore default uses).
    assert main(["archive", "show", item_id]) == 0
    first_default = capsys.readouterr().out
    assert main(["archive", "show", item_id]) == 0
    second_default = capsys.readouterr().out
    assert second_default == first_default
    assert first_default.count("\n") == 1  # non-vacuous: a real one-prior recovery line

    # 1b. the `--all` multi-prior fold: two reads of the *whole recoverable history*
    #     are byte-identical whole-document — the order-sensitive `archived_snapshots`
    #     path (three priors folded newest-first) the single-prior default never hits.
    assert main(["archive", "show", item_id, "--all"]) == 0
    first_all = capsys.readouterr().out
    assert main(["archive", "show", item_id, "--all"]) == 0
    second_all = capsys.readouterr().out
    assert second_all == first_all
    assert first_all.count("\n") == 3  # non-vacuous: the whole three-prior history
    # the default read is byte-identical to the --all stream's head (convergence by
    # construction — `latest_archived` is exactly `archived_snapshots`' head)
    assert first_all.splitlines(keepends=True)[0] == first_default

    # 2. the recovery round-trip: pipe `archive show <id>` (the latest archived prior,
    #    v2) through `import items --accept-incoming` and assert the prior is
    #    re-adopted — the held copy becomes the recovered prior (the displaced v3 is
    #    itself archived, fully reversible). H278/H285's outcome leg on this guard.
    recovered = json.loads(first_default)["content_hash"]
    assert recovered == "sha256:v2"  # the latest archived prior, what restore adopts
    db = get_paths().db_path
    assert get_item(db, item_id).content_hash == "sha256:v3"  # held before restore
    restore_path = tmp_path / "restore.jsonl"
    restore_path.write_text(first_default, encoding="utf-8")
    assert main(["import", "items", str(restore_path), "--accept-incoming"]) == 0
    capsys.readouterr()
    # the archived prior was re-adopted: the held copy is the recovered prior now
    assert get_item(db, item_id).content_hash == "sha256:v2"


def test_reimport_archive_is_whole_store_idempotent(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    """`import archive` is the prior-content recovery transport (ADR 0106/H280), and
    re-importing the *same* archive backup into a library that already holds those
    priors must be a true **whole-store** no-op (H386) on three axes:

    1. the second pass reports ``imported == 0`` / ``skipped == N`` — the report axis,
    2. the raw ``item_archive`` row count is unchanged across the two passes — the
       *store* axis a "reports skipped" check is blind to (a re-keyed dedup that both
       skips *and* re-inserts would pass the report axis yet double the store), and
    3. every item's ``archived_snapshots(id)`` recovery read is identical list-for-list
       across the two passes — the *recovery-read* axis a scalar count is blind to.

    The third member of the ingest-idempotency triptych — after `import bundle`
    (H374, items transport, `merge_item`'s ``INSERT OR IGNORE``) and `import events`
    (H380, the `_EVENT_IDENTITY` 5-tuple) — on the **archive** transport:
    `import_archive` content-dedups on ``_ARCHIVE_IDENTITY = (item_id, prior_hash)``,
    a **distinct code path** from both siblings; deliberately *not* a content-identity
    guard. The pre-existing `test_import_archive_is_idempotent` already pins the
    *single-prior, scalar-count* same-library re-import; this is its **multi-prior**
    sharpening: a three-prior recovery history (so the order-sensitive
    `archived_snapshots` fold is non-vacuous) re-imported into a **fresh home**, so
    a dedup keyed on ``item_id`` alone (dropping ``prior_hash``) — which a one-prior
    archive cannot distinguish from the full key — collapses the history to a single
    row and is caught here, where the scalar-count single-prior test stays green.

    **Decisive choice:** assert *both* the raw `item_archive` row count (catches a
    silent double-insert) and the per-item `archived_snapshots` list identity over a
    multi-prior history (catches a dedup that drops the wrong prior) — the H380
    both-axes precedent (a "reports skipped" check is blind to a re-keyed dedup that
    both skips *and* re-inserts).
    """
    # seed a non-vacuous recovery store: one item with three superseded priors, so the
    # archive holds [abc, v1, v2] (newest-archived v2) and the order-sensitive
    # `archived_snapshots` fold reads newest-first [v2, v1, abc] — a real multi-prior
    # history, not the single row the pre-existing idempotency test exercises.
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 3)
    capsys.readouterr()

    # export the whole-library recovery store to a portable backup (raw JSONL on stdout)
    assert main(["export", "archive"]) == 0
    backup = tmp_path / "archive-backup.jsonl"
    backup.write_text(capsys.readouterr().out, encoding="utf-8")
    assert backup.read_text(encoding="utf-8").count("\n") == 3  # non-vacuous, 3 priors

    # restore into a *fresh* home (an empty recovery store the backup populates) — the
    # recipient operator restoring a backup, not the source library that minted it.
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "fresh-home"))
    assert main(["init"]) == 0
    db = get_paths().db_path
    capsys.readouterr()

    # first pass: every prior is new — the backup populates the empty archive
    assert main(["import", "archive", str(backup)]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["imported"] == 3 and first["skipped"] == 0
    first_count = len(archived_records(db))
    first_history = [s.content_hash for s in archived_snapshots(db, item_id)]
    assert first_count == 3
    assert first_history == ["sha256:v2", "sha256:v1", "sha256:abc"]  # newest-first

    # second pass: the *same* backup into the now-populated archive is a true no-op
    assert main(["import", "archive", str(backup)]) == 0
    second = json.loads(capsys.readouterr().out)
    # report axis: nothing imported, every prior skipped
    assert second["imported"] == 0 and second["skipped"] == 3
    # store axis: not one row silently re-inserted (the count is byte-for-byte stable)
    assert len(archived_records(db)) == first_count
    # recovery axis: every item's whole recoverable history is identical list-for-list
    assert [s.content_hash for s in archived_snapshots(db, item_id)] == first_history


# --- archive restore (H286): restore a *specific* archived prior in place via the
# accept-incoming adoption (the displaced copy itself archived — fully reversible).
# --hash / --at select the version; default the latest; idempotent; --dry-run
# predicts and writes nothing (ADR 0106's deferred restore-by-version). ---


def _seed_archived_chain_at(scrolls_home, steps):
    """Seed a rich item (held `sha256:abc`), then adopt a chain of divergent captures
    at *controlled* `archived_at` timestamps (via `adopt_incoming` directly, bypassing
    the now-stamp the live import flow uses) so `archive restore --at` has a spaced
    history to bisect. `steps` is a list of `(content_hash, archived_at)`. Returns the
    seeded id; the held copy ends as the last step's hash."""
    seeded = _seed_rich_item(scrolls_home)
    db = get_paths().db_path
    held = get_item(db, seeded.id)
    for new_hash, at in steps:
        incoming = dataclasses.replace(held, content_hash=new_hash, raw_text=f"body {new_hash}")
        adopt_incoming(db, incoming, archived_at=at)
        held = incoming
    return seeded.id


def test_archive_restore_by_hash_adopts_that_version_and_archives_the_displaced(
    scrolls_home, tmp_path, capsys
):
    """`archive restore <id> --hash H` re-adopts the archived prior with content hash
    H — a *specific* older version, not just the latest — through the accept-incoming
    write, and the *currently-held* copy it displaces is itself archived (recoverable),
    so restore-by-version is fully reversible (ADR 0106 / custody §2.4)."""
    # archive ends holding priors [abc, v1, v2] (newest-first v2,v1,abc); held = v3
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 3)
    db = get_paths().db_path
    assert get_item(db, item_id).content_hash == "sha256:v3"
    capsys.readouterr()

    # restore the *oldest* prior by its hash
    assert main(["archive", "restore", item_id, "--hash", "sha256:abc"]) == 0
    out, err = capsys.readouterr()
    decision = json.loads(out)
    assert decision["restored"] is True and decision["outcome"] == "adopted"
    assert decision["selector"] == {"hash": "sha256:abc"}
    assert decision["prior_hash"] == "sha256:abc"   # the restored version
    assert decision["held_hash"] == "sha256:v3"     # what it displaced
    # the held copy is the restored prior now
    assert get_item(db, item_id).content_hash == "sha256:abc"
    # …and the displaced copy (v3) was itself archived — fully reversible
    assert latest_archived(db, item_id).content_hash == "sha256:v3"
    # loud on stderr: a held copy was replaced (the accept-incoming custody signal)
    assert item_id in json.loads(err)["warning"]


def test_archive_restore_default_restores_the_latest_prior(
    scrolls_home, tmp_path, capsys
):
    """With no selector, restore re-adopts the *latest* archived prior — the
    behaviour of `archive show <id> | import items --accept-incoming`, just in one
    command. The selector echoes ``{latest: true}``."""
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 3)  # latest prior = v2
    db = get_paths().db_path
    capsys.readouterr()
    assert main(["archive", "restore", item_id]) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["selector"] == {"latest": True}
    assert decision["restored"] is True and decision["prior_hash"] == "sha256:v2"
    assert get_item(db, item_id).content_hash == "sha256:v2"  # the latest prior
    assert latest_archived(db, item_id).content_hash == "sha256:v3"  # v3 displaced


def test_archive_restore_by_at_picks_the_version_held_as_of_a_time(
    scrolls_home, capsys
):
    """`archive restore <id> --at ISO` re-adopts the newest prior archived at/before
    the boundary — the version held as of a point in time. Priors stamped 06-22/23/24;
    --at 06-23T12:00 picks the 06-23 prior (the 06-24 one is after the boundary)."""
    item_id = _seed_archived_chain_at(scrolls_home, [
        ("sha256:m1", "2026-06-22T00:00:00+00:00"),
        ("sha256:m2", "2026-06-23T00:00:00+00:00"),
        ("sha256:m3", "2026-06-24T00:00:00+00:00"),
    ])  # archive: [m2@06-24, m1@06-23, abc@06-22]; held = m3
    db = get_paths().db_path
    capsys.readouterr()
    assert main(["archive", "restore", item_id, "--at", "2026-06-23T12:00:00+00:00"]) == 0
    decision = json.loads(capsys.readouterr().out)
    # the newest prior at/before the boundary is m1 (archived 06-23), not m2 (06-24)
    assert decision["prior_hash"] == "sha256:m1"
    assert decision["archived_at"] == "2026-06-23T00:00:00+00:00"  # when m1 was archived
    # the selector echoes the (normalized) boundary the operator passed, not the
    # selected prior's archived_at
    assert decision["selector"] == {"at": "2026-06-23T12:00:00+00:00"}
    assert get_item(db, item_id).content_hash == "sha256:m1"


def test_archive_restore_is_idempotent_when_the_prior_is_already_held(
    scrolls_home, tmp_path, capsys
):
    """Restoring a prior that already *is* the held copy is an ``unchanged`` no-op —
    no second archive row, no event (idempotency falls out of the content-hash
    compare, the `import --accept-incoming` precedent)."""
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 3)
    db = get_paths().db_path
    capsys.readouterr()
    # first restore of the oldest prior adopts it (held becomes abc)
    assert main(["archive", "restore", item_id, "--hash", "sha256:abc"]) == 0
    capsys.readouterr()
    rows_after_first = len(list_archived(db, item_id))
    # abc is still in the archive *and* now the held copy → a second restore is a no-op
    assert main(["archive", "restore", item_id, "--hash", "sha256:abc"]) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["restored"] is False and decision["outcome"] == "unchanged"
    assert get_item(db, item_id).content_hash == "sha256:abc"
    assert len(list_archived(db, item_id)) == rows_after_first  # no churn


def test_archive_restore_dry_run_predicts_and_writes_nothing(
    scrolls_home, tmp_path, capsys
):
    """`--dry-run` predicts the same decision the live run would emit (``dry_run:
    true``, ``restored: true``) but the held copy is untouched and no prior is
    archived — the preview-never-drifts discipline (H245/H273)."""
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 2)  # held = v2
    db = get_paths().db_path
    rows_before = len(list_archived(db, item_id))
    capsys.readouterr()
    assert main(["archive", "restore", item_id, "--hash", "sha256:abc", "--dry-run"]) == 0
    out, err = capsys.readouterr()
    decision = json.loads(out)
    assert decision["dry_run"] is True
    assert decision["restored"] is True and decision["outcome"] == "adopted"
    assert decision["prior_hash"] == "sha256:abc"
    # nothing was written: the held copy still v2, no new archive row, no warning
    assert get_item(db, item_id).content_hash == "sha256:v2"
    assert len(list_archived(db, item_id)) == rows_before
    assert err == ""


def test_archive_restore_unmatched_selector_is_a_could_not_recover(
    scrolls_home, tmp_path, capsys
):
    """A `--hash`/`--at` that no archived prior matches is a could-not-recover (exit
    1) — the held copy is never touched on a miss."""
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 2)
    db = get_paths().db_path
    capsys.readouterr()
    # a hash no prior carries
    assert main(["archive", "restore", item_id, "--hash", "sha256:ghost"]) == 1
    assert "no archived prior" in json.loads(capsys.readouterr().err)["error"]
    # an --at boundary before the whole history
    assert main(["archive", "restore", item_id, "--at", "2020-01-01T00:00:00+00:00"]) == 1
    assert "no archived prior" in json.loads(capsys.readouterr().err)["error"]
    # the held copy survived both misses untouched
    assert get_item(db, item_id).content_hash == "sha256:v2"


def test_archive_restore_rejects_both_selectors_and_a_malformed_at(
    scrolls_home, tmp_path, capsys
):
    """At most one version selector (the explicit gate, exit 2); a malformed `--at`
    is a loud usage error (exit 2, the `archive prune --before` precedent), never a
    silently empty selection."""
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 1)
    capsys.readouterr()
    assert main(["archive", "restore", item_id, "--hash", "sha256:abc",
                 "--at", "2026-06-23"]) == 2
    assert "at most one" in json.loads(capsys.readouterr().err)["error"]
    assert main(["archive", "restore", item_id, "--at", "not-a-timestamp"]) == 2
    assert "ISO-8601" in json.loads(capsys.readouterr().err)["error"]


def test_archive_restore_unknown_id_is_a_could_not_recover(scrolls_home, capsys):
    """`archive restore` for an id with no archived prior (never superseded) exits 1 —
    the same could-not-recover signal as `archive show`."""
    _seed_rich_item(scrolls_home)
    capsys.readouterr()
    assert main(["archive", "restore", "arxiv:1706.03762"]) == 1
    assert "no archived prior" in json.loads(capsys.readouterr().err)["error"]


# --- archive diff (H288): the decide-before-you-restore read — compare the held
# copy against a selected archived prior (the same --hash/--at selector restore
# uses, default the latest), reporting the held↔prior content-hash + fidelity delta,
# the model-complete changed-field set, and `would_restore`. CLI-only read, no
# write; unmatched selector / unknown id → exit 1 (the `archive restore` signals). ---


def test_archive_diff_reports_the_held_vs_prior_delta_and_writes_nothing(
    scrolls_home, tmp_path, capsys
):
    """`archive diff <id> --hash H` compares the currently-held copy against the
    selected archived prior: held↔prior content hashes, each side's fidelity tier, the
    model-complete fields a restore would surface, and `would_restore`. It is a *read*
    — the held copy, the archive, and stderr are untouched."""
    # archive holds priors [v2, v1, abc] (newest-first); held = v3
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 3)
    db = get_paths().db_path
    rows_before = len(list_archived(db, item_id))
    capsys.readouterr()

    assert main(["archive", "diff", item_id, "--hash", "sha256:abc"]) == 0
    out, err = capsys.readouterr()
    report = json.loads(out)
    assert report["id"] == item_id
    assert report["selector"] == {"hash": "sha256:abc"}
    assert report["held_hash"] == "sha256:v3"     # what is held now
    assert report["prior_hash"] == "sha256:abc"   # the archived version compared against
    assert report["archived_at"]                  # when that prior was archived
    assert report["held_fidelity"] == "full" and report["prior_fidelity"] == "full"
    # the original (abc) carried extracted_text/no raw_text; the held v3 carries a raw
    # body and a different hash → exactly those fields differ, sorted
    assert report["changed_fields"] == ["content_hash", "raw_text"]
    assert report["would_restore"] is True        # the hashes differ → a restore acts
    # it wrote nothing: the held copy, the archive, and stderr are all untouched
    assert get_item(db, item_id).content_hash == "sha256:v3"
    assert len(list_archived(db, item_id)) == rows_before
    assert err == ""


def test_archive_diff_default_compares_against_the_latest_prior(
    scrolls_home, tmp_path, capsys
):
    """With no selector, diff compares against the *latest* archived prior — the
    version `archive restore` (no selector) would adopt. The selector echoes
    ``{latest: true}``."""
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 3)  # latest prior = v2
    capsys.readouterr()
    assert main(["archive", "diff", item_id]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["selector"] == {"latest": True}
    assert report["prior_hash"] == "sha256:v2"  # the latest archived prior
    assert report["held_hash"] == "sha256:v3"
    assert report["would_restore"] is True


def test_archive_diff_by_at_picks_the_version_held_as_of_a_time(scrolls_home, capsys):
    """`archive diff <id> --at ISO` compares against the newest prior archived at/before
    the boundary — the same point-in-time selection `archive restore --at` makes."""
    item_id = _seed_archived_chain_at(scrolls_home, [
        ("sha256:m1", "2026-06-22T00:00:00+00:00"),
        ("sha256:m2", "2026-06-23T00:00:00+00:00"),
        ("sha256:m3", "2026-06-24T00:00:00+00:00"),
    ])  # archive: [m2@06-24, m1@06-23, abc@06-22]; held = m3
    capsys.readouterr()
    assert main(["archive", "diff", item_id, "--at", "2026-06-23T12:00:00+00:00"]) == 0
    report = json.loads(capsys.readouterr().out)
    # the newest prior at/before the boundary is m1 (archived 06-23), not m2 (06-24)
    assert report["prior_hash"] == "sha256:m1"
    assert report["archived_at"] == "2026-06-23T00:00:00+00:00"
    assert report["selector"] == {"at": "2026-06-23T12:00:00+00:00"}
    assert report["would_restore"] is True


def test_archive_diff_would_restore_false_when_the_prior_is_the_held_copy(
    scrolls_home, tmp_path, capsys
):
    """When the selected prior already *is* the held copy, nothing differs and
    ``would_restore`` is false — the H286 idempotency predicted as a read (a restore
    would be an ``unchanged`` no-op)."""
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 3)
    db = get_paths().db_path
    capsys.readouterr()
    # restore abc into place so the held copy *is* abc (abc stays in the archive)
    assert main(["archive", "restore", item_id, "--hash", "sha256:abc"]) == 0
    capsys.readouterr()
    assert get_item(db, item_id).content_hash == "sha256:abc"
    # now diff against that same prior: it is the held copy → empty delta, no restore
    assert main(["archive", "diff", item_id, "--hash", "sha256:abc"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["held_hash"] == report["prior_hash"] == "sha256:abc"
    assert report["changed_fields"] == []
    assert report["would_restore"] is False


def test_archive_diff_reports_each_sides_fidelity_tier(scrolls_home, capsys):
    """``held_fidelity`` and ``prior_fidelity`` are derived independently, so a
    degradation — the held copy now partial, the archived prior still full — is visible
    *before* a restore recovers the fuller copy (ADR 0097)."""
    seeded = _seed_rich_item(scrolls_home)  # full: extracted_text + content_hash, rendered
    db = get_paths().db_path
    held = get_item(db, seeded.id)
    # adopt a degraded capture (only a summary survives → partial): the full original
    # (abc) is archived, the held copy becomes partial
    degraded = dataclasses.replace(
        held, extracted_text=None, raw_text=None, summary="just a note",
        content_hash="sha256:thin",
    )
    adopt_incoming(db, degraded, archived_at="2026-06-22T00:00:00+00:00")
    capsys.readouterr()
    assert main(["archive", "diff", seeded.id]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["held_fidelity"] == "partial"  # the degraded held copy
    assert report["prior_fidelity"] == "full"    # the archived original
    assert report["would_restore"] is True       # restoring recovers the full copy


def test_archive_diff_unmatched_selector_is_a_could_not_recover(
    scrolls_home, tmp_path, capsys
):
    """A `--hash`/`--at` that no archived prior matches is a could-not-recover (exit
    1) — the same signal as `archive restore`, and nothing is written."""
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 2)
    capsys.readouterr()
    assert main(["archive", "diff", item_id, "--hash", "sha256:ghost"]) == 1
    assert "no archived prior" in json.loads(capsys.readouterr().err)["error"]
    assert main(["archive", "diff", item_id, "--at", "2020-01-01T00:00:00+00:00"]) == 1
    assert "no archived prior" in json.loads(capsys.readouterr().err)["error"]


def test_archive_diff_unknown_id_is_a_could_not_recover(scrolls_home, capsys):
    """`archive diff` for an id with no archived prior (never superseded) exits 1 —
    the same could-not-recover signal as `archive show`/`restore`."""
    _seed_rich_item(scrolls_home)
    capsys.readouterr()
    assert main(["archive", "diff", "arxiv:1706.03762"]) == 1
    assert "no archived prior" in json.loads(capsys.readouterr().err)["error"]


def test_archive_diff_rejects_both_selectors_and_a_malformed_at(
    scrolls_home, tmp_path, capsys
):
    """At most one version selector (exit 2, the `archive restore` gate); a malformed
    `--at` is a loud usage error (exit 2), never a silently empty read."""
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 1)
    capsys.readouterr()
    assert main(["archive", "diff", item_id, "--hash", "sha256:abc",
                 "--at", "2026-06-23"]) == 2
    assert "at most one" in json.loads(capsys.readouterr().err)["error"]
    assert main(["archive", "diff", item_id, "--at", "not-a-timestamp"]) == 2
    assert "ISO-8601" in json.loads(capsys.readouterr().err)["error"]


def test_archive_diff_would_restore_agrees_with_archive_restore_dry_run(
    scrolls_home, tmp_path, capsys
):
    """`archive diff <id> <sel>`'s ``would_restore`` *is* `archive restore <id> <sel>
    --dry-run`'s ``restored`` — the cross-command write-prediction tie (H290).

    Both commands predict the *same* accept-incoming write — would a restore change the
    held copy? — from the *same* inputs: `select_archived_snapshot` picks the prior, then
    the ``content_hash`` compare `merge_item` makes decides. But they reach the verdict by
    **separate** code paths: `archive diff` folds the compare directly
    (``would_restore``), while `archive restore --dry-run` routes it through
    `_preview_merge_items` → `_restore_outcome` (``restored``). A reader may trust `diff`
    to decide and `restore --dry-run` to confirm; a divergence between two reads of one
    predicted write would be a silent custody-honesty bug. Pin that they never disagree
    across every selector (``--hash``, ``--at``, default-latest) and both the would-change
    and the idempotent-no-op cases, and that `diff`'s ``prior_hash``/``held_hash`` match
    the dry-run's — same selection, same held-vs-prior reading.
    """
    # archive holds priors [v2, v1, abc] (newest-first); held = v3
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 3)
    db = get_paths().db_path
    rows_before = len(list_archived(db, item_id))

    def diff(sel):
        capsys.readouterr()
        assert main(["archive", "diff", item_id, *sel]) == 0
        return json.loads(capsys.readouterr().out)

    def restore_dry_run(sel):
        capsys.readouterr()
        assert main(["archive", "restore", item_id, *sel, "--dry-run"]) == 0
        out, err = capsys.readouterr()
        assert err == ""  # a dry-run writes nothing and says nothing on stderr
        return json.loads(out)

    def assert_agree(sel):
        d, r = diff(sel), restore_dry_run(sel)
        # the two predictions of the one write agree…
        assert d["would_restore"] == r["restored"], sel
        # …and they read the *same* held-vs-prior copies (same selection)
        assert d["prior_hash"] == r["prior_hash"], sel
        assert d["held_hash"] == r["held_hash"], sel
        return d

    # the three selectors restore uses — by hash, by point-in-time, and the default
    # latest. Real-now archived_at values cluster in one second, so a far-future --at
    # boundary robustly resolves to the latest prior; *which* prior --at picks is H288's
    # concern, this test pins only that the two commands agree on it.
    far_future = "2099-01-01T00:00:00+00:00"
    for sel in (["--hash", "sha256:abc"], ["--at", far_future], []):
        d = assert_agree(sel)
        # held v3 differs from every selected prior → a would-change restore on each
        assert d["would_restore"] is True, sel

    # the reads/dry-runs leaked nothing: the held copy and the archive are untouched
    assert get_item(db, item_id).content_hash == "sha256:v3"
    assert len(list_archived(db, item_id)) == rows_before

    # the idempotent-no-op case: restore abc into place so it *is* the held copy (abc
    # stays archived), then re-diff/-dry-run against abc — both must predict no write
    capsys.readouterr()
    assert main(["archive", "restore", item_id, "--hash", "sha256:abc"]) == 0
    capsys.readouterr()
    assert get_item(db, item_id).content_hash == "sha256:abc"
    d = assert_agree(["--hash", "sha256:abc"])
    assert d["would_restore"] is False  # the prior already is the held copy
    assert d["held_hash"] == d["prior_hash"] == "sha256:abc"


# --- archive prune (H282): a retention act bounding the append-only recovery
# store. Report-only by default; --apply deletes; exactly one of --before/--keep;
# never touches a held row (the archive is a recovery convenience, not the root of
# trust — ADR 0106). ---


def _seed_with_archived_priors(scrolls_home, tmp_path, count):
    """Seed a rich item, then adopt `count` divergent captures via accept-incoming,
    so the archive ends up holding `count` prior copies (newest last archived).
    Returns the seeded id; the held copy is the last adopted capture."""
    seeded = _seed_rich_item(scrolls_home)
    db = get_paths().db_path
    for i in range(count):
        held = get_item(db, seeded.id)
        divergent = dataclasses.replace(
            held, content_hash=f"sha256:v{i + 1}", raw_text=f"peer {i + 1}"
        )
        out_path = tmp_path / f"incoming{i}.jsonl"
        out_path.write_text(dump_items_export([divergent]), encoding="utf-8")
        assert main(["import", "items", str(out_path), "--accept-incoming"]) == 0
    return seeded.id


def test_archive_prune_requires_exactly_one_policy(scrolls_home, tmp_path, capsys):
    """The explicit opt-in gate (the `reconcile <id>` precedent): a bare prune, or
    both policies at once, is a usage error (exit 2) — never an ambiguous write."""
    _seed_with_archived_priors(scrolls_home, tmp_path, 1)
    capsys.readouterr()
    assert main(["archive", "prune"]) == 2
    assert "exactly one retention policy" in json.loads(capsys.readouterr().err)["error"]
    assert main(["archive", "prune", "--keep", "1", "--before", "2026-01-01"]) == 2
    assert "exactly one retention policy" in json.loads(capsys.readouterr().err)["error"]


def test_archive_prune_rejects_keep_below_one(scrolls_home, tmp_path, capsys):
    """`--keep 0` would nuke an item's whole history including the latest prior —
    rejected, so `archive show` always survives a keep-prune (use --before to drop
    regardless of recency)."""
    _seed_with_archived_priors(scrolls_home, tmp_path, 1)
    capsys.readouterr()
    assert main(["archive", "prune", "--keep", "0"]) == 2
    assert "N>=1" in json.loads(capsys.readouterr().err)["error"]


def test_archive_prune_rejects_a_malformed_before(scrolls_home, tmp_path, capsys):
    """A malformed `--before` is a loud usage error (exit 2, the `verify
    --stale-before` precedent), never a silently empty prune that masks a typo."""
    _seed_with_archived_priors(scrolls_home, tmp_path, 1)
    capsys.readouterr()
    assert main(["archive", "prune", "--before", "not-a-date"]) == 2
    assert "ISO" in json.loads(capsys.readouterr().err)["error"] or \
        "not a valid" in json.loads(capsys.readouterr().err).get("error", "")


def test_archive_prune_report_only_by_default_writes_nothing(
    scrolls_home, tmp_path, capsys
):
    """Default is report-only: it predicts the drop set (matched>0) but deletes
    nothing (dropped==0, applied false) and the archive is unchanged on disk — the
    dry-run discipline (H245/H273)."""
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 3)  # 3 priors
    capsys.readouterr()
    assert main(["archive", "list"]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 3

    assert main(["archive", "prune", "--keep", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["applied"] is False
    assert report["policy"] == {"keep": 1}
    assert report["matched"] == 2          # the two oldest priors selected
    assert report["dropped"] == 0          # …but nothing actually removed
    assert report["remaining"] == 1        # one would survive
    assert report["by_item"] == [{"item_id": item_id, "dropped": 2}]
    assert len(report["archived"]) == 2    # the reviewable drop set (the list shape)
    # the archive is genuinely untouched — count still 3
    assert main(["archive", "list"]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 3


def test_archive_prune_apply_keep_drops_oldest_keeps_latest_and_warns(
    scrolls_home, tmp_path, capsys
):
    """`--apply --keep 1` deletes all but the most recent prior per item, warns
    loudly on stderr (a recovery store was shrunk), and leaves the latest prior
    recoverable via `archive show` (the keep>=1 invariant)."""
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 3)
    capsys.readouterr()

    assert main(["archive", "prune", "--keep", "1", "--apply"]) == 0
    out, err = capsys.readouterr()
    report = json.loads(out)
    assert report["applied"] is True
    assert report["matched"] == 2 and report["dropped"] == 2 and report["remaining"] == 1
    # loud on stderr — a held copy was *not* touched, but the recovery store shrank
    warning = json.loads(err)["warning"]
    assert "pruned 2" in warning and item_id in warning
    # the archive now holds exactly the latest prior, still recoverable
    assert main(["archive", "list"]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 1
    assert main(["archive", "show", item_id]) == 0
    recovered = json.loads(capsys.readouterr().out.splitlines()[0])
    assert recovered["content_hash"] == "sha256:v2"  # the newest archived prior


def test_archive_prune_apply_is_idempotent(scrolls_home, tmp_path, capsys):
    """A second `--apply` with the same policy finds the rows already gone and drops
    nothing — idempotent, like the rest of the custody writes."""
    _seed_with_archived_priors(scrolls_home, tmp_path, 3)
    capsys.readouterr()
    assert main(["archive", "prune", "--keep", "1", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["dropped"] == 2
    # second run: nothing left to drop
    assert main(["archive", "prune", "--keep", "1", "--apply"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["dropped"] == 0 and second["matched"] == 0 and second["remaining"] == 1


def test_archive_prune_apply_never_touches_a_held_item(scrolls_home, tmp_path, capsys):
    """Pruning the recovery store leaves the held copy byte-for-byte intact — the
    archive is a convenience, not the root of trust (ADR 0106 / custody §2.4)."""
    item_id = _seed_with_archived_priors(scrolls_home, tmp_path, 2)
    db = get_paths().db_path
    held_before = get_item(db, item_id)
    capsys.readouterr()
    assert main(["archive", "prune", "--keep", "1", "--apply"]) == 0
    capsys.readouterr()
    assert get_item(db, item_id) == held_before  # the held capture is untouched


def test_archive_prune_before_can_drop_the_whole_archive(scrolls_home, tmp_path, capsys):
    """The time-based policy drops priors archived before the boundary, latest
    included — a far-future `--before --apply` clears the store; a far-past one is a
    no-op. (The per-row boundary slicing is unit-tested with controlled timestamps.)"""
    _seed_with_archived_priors(scrolls_home, tmp_path, 2)
    capsys.readouterr()
    # a far-past boundary drops nothing (everything is newer)
    assert main(["archive", "prune", "--before", "2000-01-01", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["dropped"] == 0
    # a far-future boundary drops the whole archive, latest included
    assert main(["archive", "prune", "--before", "2099-01-01", "--apply"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dropped"] == 2 and report["remaining"] == 0
    assert main(["archive", "list"]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 0


def test_archive_prune_on_a_clean_library_is_an_empty_report(scrolls_home, capsys):
    """A library that never adopted holds an empty archive — prune honestly reports
    a zero drop set (shaped like a real report), never a crash."""
    _seed_rich_item(scrolls_home)
    capsys.readouterr()
    assert main(["archive", "prune", "--keep", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["matched"] == 0 and report["dropped"] == 0 and report["remaining"] == 0
    assert report["by_item"] == [] and report["archived"] == []


# --- status custody.conflicts scalar (H279): the JSON-status counterpart of the
# readable `_Conflicts:_` briefing line (H277), folding the same
# `unresolved_conflicts` doctor's `custody.conflicts` reads into the machine
# `custody` snapshot `scrolls status` carries. ---


def test_status_custody_conflicts_surfaces_an_unresolved_import_conflict(
    scrolls_home, tmp_path, capsys
):
    """H279: `status`'s machine `custody` snapshot carries the unresolved-import-
    conflict count beside drift/at-risk — the JSON-status counterpart of H277's
    readable `_Conflicts:_` briefing line. After a divergent re-import, the held
    item carries one unresolved conflict the scalar surfaces, converging
    field-for-field with `doctor`'s `custody.conflicts.items` by construction (the
    same distilled `run_doctor` view `status` already renders)."""
    _import_a_divergent_copy(scrolls_home, tmp_path)
    capsys.readouterr()

    assert main(["status"]) == 0
    custody = json.loads(capsys.readouterr().out)["custody"]
    assert custody["conflicts"] == 1

    # convergence by construction: the scalar is the doctor custody view distilled
    report = run_doctor(get_paths())
    assert custody == custody_snapshot(report)
    assert custody["conflicts"] == report["custody"]["conflicts"]["items"]
    # the conflict axis never bleeds into drift (ADR 0104) — the drift posture is
    # untouched by the recorded conflict event
    assert custody["drift"]["drifted"] == 0


def test_status_custody_conflicts_clears_after_reconcile(
    scrolls_home, tmp_path, capsys
):
    """H276/H279: the scalar is resolution-aware — once `reconcile --keep-held`
    records a `resolved` event superseding the open conflict, the `status` count
    clears (the held copy never overwritten), exactly as `doctor`'s aggregate does."""
    seeded = _import_a_divergent_copy(scrolls_home, tmp_path)
    capsys.readouterr()

    assert main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["custody"]["conflicts"] == 1

    assert main(["reconcile", seeded.id, "--keep-held"]) == 0
    capsys.readouterr()

    assert main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["custody"]["conflicts"] == 0


def test_status_custody_conflicts_is_zero_on_a_clean_library(scrolls_home, capsys):
    """No recorded conflict ⇒ an honest `0` (never a fabricated count) — the drift
    scalar's zeroed-default honesty, on the conflict axis."""
    _seed_rich_item(scrolls_home)
    capsys.readouterr()
    assert main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["custody"]["conflicts"] == 0


def test_status_custody_conflicts_source_scopes_like_the_drift_scalar(
    scrolls_home, tmp_path, capsys
):
    """H279/H166: a held item owns a source, so the conflict scalar scopes by
    `--source` for free (unlike the cross-source at-risk-works alarm) — `run_doctor`'s
    item pre-filter narrows the conflict fold. The conflicting source reports `1`, an
    unaffected source reports `0`, and the whole-library read reports the `1`."""
    _import_a_divergent_copy(scrolls_home, tmp_path)  # an arxiv conflict
    # a second source, held clean (no conflict)
    web = ScrollItem(
        id=make_item_id("web", None, "https://example.com/clean"),
        source="web",
        source_id=None,
        url="https://example.com/clean",
        saved_at="2026-06-14T00:00:00+00:00",
        extracted_text="A clean web capture, no peer disagreement.",
        content_hash="sha256:web1234",
        stage="rendered",
        provenance={"adapter": "web", "fetched_at": "2026-06-14T00:00:05+00:00"},
    )
    insert_item(get_paths().db_path, web)
    capsys.readouterr()

    def conflicts_for(args: list[str]) -> int:
        assert main(["status", *args]) == 0
        return json.loads(capsys.readouterr().out)["custody"]["conflicts"]

    assert conflicts_for([]) == 1                       # whole library
    assert conflicts_for(["--source", "arxiv"]) == 1    # the conflicting source
    assert conflicts_for(["--source", "web"]) == 0      # the unaffected source


# --- status custody.posture verdict (H370): the JSON-status counterpart of the
# readable `_Posture:_` maintain line (H370), carrying `doctor`'s whole-library
# `custody.posture` verdict block (H369) *whole* (verdict + reasons) into the machine
# `custody` snapshot `scrolls status` renders — `status` shows no readable posture line,
# so it carries the machine value (the `archive_mismatched`/`conflicts` precedent). ---


def _held_full_item(paths, url="https://example.com/held", content_hash="sha256:held1"):
    """A full-fidelity held scroll written to disk (raw + extracted + hash), so the
    integrity audit finds nothing to flag — the clean `sound` starting point."""
    item = ScrollItem(
        id=make_item_id("web", None, url),
        source="web",
        source_id=None,
        url=url,
        saved_at="2026-06-14T00:00:00+00:00",
        extracted_text="A fully held capture we can re-derive.",
        content_hash=content_hash,
        stage="rendered",
        provenance={"adapter": "web", "fetched_at": "2026-06-14T00:00:05+00:00"},
    )
    insert_item(paths.db_path, write_scroll(paths, item))
    return item


def test_status_custody_posture_is_sound_on_a_clean_library(scrolls_home, capsys):
    """A fully held, re-derivable capture with no losses anywhere ⇒ the honest `sound`
    verdict with empty reasons (the skeleton default's healthy state), converging
    field-for-field with `doctor`'s `custody.posture` by construction."""
    paths = get_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    from scrolls.db import init_db

    init_db(paths.db_path)
    _held_full_item(paths)
    capsys.readouterr()

    assert main(["status"]) == 0
    custody = json.loads(capsys.readouterr().out)["custody"]
    assert custody["posture"] == {"verdict": "sound", "reasons": []}
    # convergence by construction: the verdict IS the doctor custody view, carried whole
    assert custody["posture"] == run_doctor(paths)["custody"]["posture"]


def test_status_custody_posture_surfaces_an_open_conflict_as_attention(
    scrolls_home, capsys
):
    """H370: `status`'s machine `custody` snapshot carries the whole-library posture
    verdict beside drift/at-risk/conflicts. An unresolved import conflict is a soft
    concern ⇒ `attention` naming `open_conflicts`, converging field-for-field with
    `doctor`'s `custody.posture` by construction (the same distilled `run_doctor` view
    `status` already renders) — and it never lowers the integrity score (a peer
    divergence is not our drift, M2)."""
    paths = get_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    from scrolls.db import init_db

    init_db(paths.db_path)
    held = _held_full_item(paths)
    # a peer's re-import disagreed with the held copy — an unresolved conflict, no loss
    record_events(paths.db_path, [conflict_event(
        held.id, held_hash="sha256:held1", incoming_hash="sha256:peer",
        now="2026-06-22T00:00:00+00:00")])
    capsys.readouterr()

    assert main(["status"]) == 0
    custody = json.loads(capsys.readouterr().out)["custody"]
    assert custody["posture"] == {"verdict": "attention", "reasons": ["open_conflicts"]}
    # convergence by construction: the verdict is the doctor custody view, carried whole
    report = run_doctor(paths)
    assert custody["posture"] == report["custody"]["posture"]
    assert custody == custody_snapshot(report)
    assert custody["score"] == 100  # the conflict moves the posture, never the score


# --- status custody.archive_mismatched scalar (H298): the JSON-status counterpart
# of the readable `_Archive:_` maintain line, folding doctor's
# `custody.archive.mismatched` (H293) into the machine `custody` snapshot `scrolls
# status` carries — since `status` renders no readable archive line. ---


def _tamper_prior_hash(db, item_id, value):
    """Out-of-band rewrite of a prior's advertised hash — a corrupt/laundered store."""
    import sqlite3

    conn = sqlite3.connect(db)
    with conn:
        conn.execute(
            "UPDATE item_archive SET prior_hash = ? WHERE item_id = ?", (value, item_id)
        )
    conn.close()


def test_status_custody_archive_mismatched_surfaces_a_corrupt_prior(
    scrolls_home, capsys
):
    """H298: `status`'s machine `custody` snapshot carries the archive-integrity
    mismatch count beside drift/at-risk/conflicts — the JSON-status counterpart of
    the readable `_Archive:_` maintain line. A tampered prior is surfaced, converging
    field-for-field with `doctor`'s `custody.archive.mismatched` by construction (the
    same distilled `run_doctor` view `status` already renders)."""
    db, prior = _seed_archived_prior()
    _tamper_prior_hash(db, prior.id, "sha256:tampered")
    capsys.readouterr()

    assert main(["status"]) == 0
    custody = json.loads(capsys.readouterr().out)["custody"]
    assert custody["archive_mismatched"] == 1

    # convergence by construction: the scalar is the doctor custody view distilled
    report = run_doctor(get_paths())
    assert custody == custody_snapshot(report)
    assert custody["archive_mismatched"] == report["custody"]["archive"]["mismatched"]


def test_status_custody_archive_mismatched_is_zero_on_a_clean_store(
    scrolls_home, capsys
):
    """An honest archive (prior_hash == snapshot.content_hash) ⇒ a `0`, never a
    fabricated count — the conflict scalar's zeroed-default honesty, on the archive
    axis."""
    _seed_archived_prior()
    capsys.readouterr()
    assert main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["custody"]["archive_mismatched"] == 0


def test_status_custody_archive_mismatched_skipped_under_a_source_scope(
    scrolls_home, capsys
):
    """H298/H166: the archive is a single whole-library recovery store (the integrity
    check runs unscoped only), so a `--source` read leaves it skipped → the scalar
    reads the honest `0` even with a tampered prior, unlike the source-attributable
    conflict scalar. The whole-library read still surfaces the `1`."""
    db, prior = _seed_archived_prior()
    _tamper_prior_hash(db, prior.id, "sha256:tampered")
    capsys.readouterr()

    def archive_mismatched_for(args: list[str]) -> int:
        assert main(["status", *args]) == 0
        return json.loads(capsys.readouterr().out)["custody"]["archive_mismatched"]

    assert archive_mismatched_for([]) == 1                   # whole library
    assert archive_mismatched_for(["--source", "web"]) == 0  # scoped → skipped → 0


def test_export_items_empty_library_is_valid(scrolls_home, capsys):
    main(["init"])
    capsys.readouterr()
    exit_code = main(["export", "items"])
    assert exit_code == 0
    assert capsys.readouterr().out == ""  # an empty JSONL document


def test_export_items_source_filter_scopes_the_export(scrolls_home, capsys):
    main(["add", "https://github.com/sqlite/sqlite"])
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()
    exit_code = main(["export", "items", "--source", "github"])
    assert exit_code == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["source"] == "github"


# --- export items --fidelity / --drift: the custody-filter family on the
# whole-library JSONL backup (H259), the backup-path sibling of `export bundle`
# --fidelity/--drift (H258). A pure thread-through: `list_items` already applies
# both axes (the `list --fidelity`/`--drift` primitives, H250/H54), so the backup
# scopes to "only my full-fidelity holdings" / "only the drifted rows for a
# recapture handoff" with no new sieve. ---


def test_export_items_fidelity_scopes_the_backup(scrolls_home, capsys):
    # back up only the holdings at one custody-fidelity tier — the JSONL is the
    # subset `scrolls list --fidelity` enumerates, in saved order (ADR 0097)
    main(["init"])
    _seed_fidelity_tiers()
    capsys.readouterr()

    exit_code = main(["export", "items", "--fidelity", "full"])
    assert exit_code == 0
    ids = [json.loads(line)["id"] for line in capsys.readouterr().out.splitlines()]
    assert ids == ["web:full0", "web:full1"]

    main(["export", "items", "--fidelity", "reference"])
    ids = [json.loads(line)["id"] for line in capsys.readouterr().out.splitlines()]
    assert ids == ["web:reference"]


def test_export_items_drift_scopes_the_backup(scrolls_home, capsys):
    # ship only the rows at one custody drift posture (from the verify ledger) —
    # the backup of the set `scrolls list --drift` enumerates, for a recapture
    # handoff. The two seed reference-fidelity items differ only by ledger posture.
    main(["init"])
    _seed_drift_postures()
    capsys.readouterr()

    exit_code = main(["export", "items", "--drift", "drifted"])
    assert exit_code == 0
    ids = [json.loads(line)["id"] for line in capsys.readouterr().out.splitlines()]
    assert ids == ["web:1"]

    main(["export", "items", "--drift", "verified"])
    ids = [json.loads(line)["id"] for line in capsys.readouterr().out.splitlines()]
    assert ids == ["web:0"]


def test_export_items_fidelity_is_byte_identical_to_the_unscoped_subset(
    scrolls_home, capsys
):
    # the core backup guarantee: a custody-scoped backup is byte-for-byte the
    # matching subset of the whole-library backup — `dump_items_export` over the
    # kept rows, and `list_items` preserves saved order under the post-SQL sieve,
    # so the scoped stream is exactly the unscoped lines for those ids.
    main(["init"])
    _seed_fidelity_tiers()
    capsys.readouterr()

    main(["export", "items"])
    unscoped = capsys.readouterr().out
    main(["export", "items", "--fidelity", "full"])
    scoped = capsys.readouterr().out

    full_ids = {"web:full0", "web:full1"}
    expected = "".join(
        line
        for line in unscoped.splitlines(keepends=True)
        if json.loads(line)["id"] in full_ids
    )
    assert scoped == expected
    assert scoped  # non-vacuous: the seed holds full-fidelity rows


def test_export_items_custody_axes_and_together(scrolls_home, capsys):
    # both axes AND: --fidelity intersects --drift (and every other facet). A
    # full-fidelity drifted item plus reference-fidelity rows in mixed postures.
    main(["init"])
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:fulldrift", source="web", url="https://ex.com/fulldrift",
        saved_at="2026-06-12T00:00:00+00:00", title="Full + drifted",
        raw_text="A re-derivable body whose source moved.", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:ref", source="web", url="https://ex.com/ref",
        saved_at="2026-06-12T00:00:01+00:00", title="Reference + drifted",
        stage="detected"))
    record_events(db, [
        CustodyEvent("web:fulldrift", "2026-06-14T00:00:00+00:00", "drifted", "h", "x", None),
        CustodyEvent("web:ref", "2026-06-14T00:00:00+00:00", "drifted", "h", "x", None),
    ])
    capsys.readouterr()

    # the intersection: full *and* drifted is exactly the one row in both sets
    main(["export", "items", "--fidelity", "full", "--drift", "drifted"])
    ids = [json.loads(line)["id"] for line in capsys.readouterr().out.splitlines()]
    assert ids == ["web:fulldrift"]

    # the drift axis alone keeps both drifted rows regardless of fidelity
    main(["export", "items", "--drift", "drifted"])
    ids = [json.loads(line)["id"] for line in capsys.readouterr().out.splitlines()]
    assert ids == ["web:fulldrift", "web:ref"]

    # an empty intersection is the honest empty document, never an error
    exit_code = main(["export", "items", "--fidelity", "reference", "--drift", "verified"])
    assert exit_code == 0
    assert capsys.readouterr().out == ""


def test_export_items_custody_scoped_backup_round_trips_through_import(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    # the lossless round-trip holds over a custody scope: `import items` of a
    # scoped backup re-holds exactly the exported rows — no leakage of the
    # filtered-out tiers (the H216 round-trip narrowed to one custody value).
    main(["init"])
    _seed_fidelity_tiers()
    capsys.readouterr()

    main(["export", "items", "--fidelity", "full"])
    out_path = tmp_path / "full-only.jsonl"
    out_path.write_text(capsys.readouterr().out, encoding="utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "restored-home"))
    exit_code = main(["import", "items", str(out_path)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "imported": 2,
        "skipped": 0,
        "unchanged": 0,
        "conflict": 0,
        "adopted": [],
        "conflicts": [],
        # the two full-tier rows hold distinct bytes (one hashed, one NULL) — no
        # content duplicate (H353)
        "content_duplicates": 0,
        "items": 2,
    }

    db = get_paths().db_path
    assert get_item(db, "web:full0") is not None
    assert get_item(db, "web:full1") is not None
    # the filtered-out tiers never travelled
    assert get_item(db, "web:partial") is None
    assert get_item(db, "web:reference") is None


def test_export_items_rejects_an_unknown_fidelity_tier(scrolls_home):
    # fidelity tiers are a closed vocabulary; a typo is exit 2, never a silent
    # empty backup (the `list --fidelity` precedent)
    with pytest.raises(SystemExit) as excinfo:
        main(["export", "items", "--fidelity", "ful"])
    assert excinfo.value.code == 2


def test_export_items_rejects_an_unknown_drift_posture(scrolls_home):
    # drift postures are a closed vocabulary; a typo is exit 2, never a silent empty
    with pytest.raises(SystemExit) as excinfo:
        main(["export", "items", "--drift", "drited"])
    assert excinfo.value.code == 2


def test_cmd_export_items_unknown_tier_on_the_programmatic_path_is_exit_1(
    scrolls_home, capsys
):
    # belt-and-braces below argparse: a direct call past `choices` surfaces the
    # `list_items` ValueError as a JSON error on stderr, exit 1 (the
    # `_cmd_export_bundle` precedent), never a stdout backup
    from scrolls.cli import _cmd_export_items

    main(["init"])
    _seed_fidelity_tiers()
    capsys.readouterr()

    exit_code = _cmd_export_items(None, None, None, "bogus-tier", None)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


# --- export items --content-duplicate: the content-identity axis on the JSONL
# backup (H341), the content-identity sibling of `export items --fidelity`/`--drift`
# (H259). A pure thread-through: `list_items` already applies the
# `--content-duplicate` whole-library sibling sieve (H338, the
# `content_duplicate_index` fold), so the backup scopes to "only the redundant
# copies, so a recipient can dedup" with no new sieve. ---


def test_export_items_content_duplicate_scopes_the_backup(scrolls_home, capsys):
    # `export items --content-duplicate` backs up only the held items carrying a
    # byte-identical sibling (the two content groups), dropping the unique held
    # item and the NULL-hash reference — and the backed-up ids equal exactly the
    # union of `doctor`'s content-duplicate group members (the drill-from-the-report
    # tie the `list --content-duplicate` browse filter already pins).
    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)
    capsys.readouterr()

    exit_code = main(["export", "items", "--content-duplicate"])
    assert exit_code == 0
    ids = {json.loads(line)["id"] for line in capsys.readouterr().out.splitlines()}
    assert ids == {"web:a", "arxiv:1", "web:p", "web:q"}  # unique + ref dropped

    main(["doctor"])
    groups = json.loads(capsys.readouterr().out)["custody"]["content_duplicates"]["groups"]
    members = {item_id for group in groups for item_id in group["ids"]}
    assert ids == members


def test_export_items_content_duplicate_is_byte_identical_to_the_unscoped_subset(
    scrolls_home, capsys
):
    # the core backup guarantee (the H259 shape): a content-duplicate-scoped backup
    # is byte-for-byte the matching subset of the whole-library backup — `list_items`
    # preserves saved order under the post-SQL sibling sieve, so the scoped stream is
    # exactly the unscoped lines for the redundant ids.
    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)
    capsys.readouterr()

    main(["export", "items"])
    unscoped = capsys.readouterr().out
    main(["export", "items", "--content-duplicate"])
    scoped = capsys.readouterr().out

    dup_ids = {"web:a", "arxiv:1", "web:p", "web:q"}
    expected = "".join(
        line
        for line in unscoped.splitlines(keepends=True)
        if json.loads(line)["id"] in dup_ids
    )
    assert scoped == expected
    assert scoped  # non-vacuous: the seed holds byte-identical pairs


def test_export_items_content_duplicate_composes_with_source(scrolls_home, capsys):
    # the filter ANDs with --source, and the sibling scope is whole-library (a
    # content group spans sources, the H328 rule), so --source web still backs up
    # web:a whose only sibling (arxiv:1) lives in another source. --fidelity narrows
    # to one group (the H338 composition, carried to the backup path).
    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)
    capsys.readouterr()

    main(["export", "items", "--content-duplicate", "--source", "web"])
    ids = {json.loads(line)["id"] for line in capsys.readouterr().out.splitlines()}
    assert ids == {"web:a", "web:p", "web:q"}  # arxiv:1 out of source scope

    main(["export", "items", "--content-duplicate", "--fidelity", "full"])
    ids = {json.loads(line)["id"] for line in capsys.readouterr().out.splitlines()}
    assert ids == {"web:a", "arxiv:1"}  # group 1 (full); the partial group drops


def test_export_items_content_duplicate_round_trips_and_reflags(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    # the round-trip custody guarantee (the H336 `content_hash`-travels shape): an
    # unscoped content-duplicate backup → fresh `import items` into B re-holds
    # exactly the redundant rows, and B's `doctor.custody.content_duplicates`
    # re-flags the *same* groups — the redundancy is a property the lossless backup
    # carries, not one silently lost because `content_hash` did not travel.
    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)
    capsys.readouterr()

    main(["export", "items", "--content-duplicate"])
    out_path = tmp_path / "dups-only.jsonl"
    out_path.write_text(capsys.readouterr().out, encoding="utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "restored-home"))
    main(["init"])
    capsys.readouterr()
    exit_code = main(["import", "items", str(out_path)])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["items"] == 4

    # the filtered-out unique + reference rows never travelled
    db_b = get_paths().db_path
    assert get_item(db_b, "web:solo") is None
    assert get_item(db_b, "web:ref") is None

    # B re-flags the same two groups (4 members) — the content_hash survived
    main(["doctor"])
    dup = json.loads(capsys.readouterr().out)["custody"]["content_duplicates"]
    assert dup["total_groups"] == 2
    assert dup["total_items"] == 4


def test_import_items_missing_file_is_an_error(scrolls_home, tmp_path, capsys):
    exit_code = main(["import", "items", str(tmp_path / "nowhere.jsonl")])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_import_items_malformed_line_is_an_error(scrolls_home, tmp_path, capsys):
    path = tmp_path / "bad.jsonl"
    path.write_text("not json at all\n", encoding="utf-8")
    exit_code = main(["import", "items", str(path)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_export_items_then_restore_rebuilds_the_whole_library(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    # the disaster-recovery contract the ADR claims: a JSONL export alone is
    # enough to reconstruct the library — index rows, then the derived scroll
    # files (doctor --fix) and the compiled library/ (kb) — byte-for-byte.
    main(["init"])
    paths_a = get_paths()
    items = [
        ScrollItem(
            id="wikipedia:en:SQLite",
            source="wikipedia",
            url="https://en.wikipedia.org/wiki/SQLite",
            saved_at="2026-06-12T09:00:00+00:00",
            source_id="en:SQLite",
            title="SQLite",
            extracted_text="SQLite is a C-language library.",
            summary="An embedded SQL database engine.",
            category="reference",
            concepts=("Database software",),
            markdown_path="scrolls/wikipedia/sqlite.md",
            stage="rendered",
        ),
        ScrollItem(
            id="github:sqlite/sqlite",
            source="github",
            url="https://github.com/sqlite/sqlite",
            saved_at="2026-06-12T10:00:00+00:00",
            source_id="sqlite/sqlite",
            title="sqlite/sqlite",
            extracted_text="The official SQLite mirror.",
            category="project",
            markdown_path="scrolls/github/sqlite-sqlite.md",
            stage="rendered",
        ),
    ]
    for item in items:
        insert_item(paths_a.db_path, item)
        write_scroll(paths_a, item)
    main(["kb"])
    original_scrolls = {
        item.markdown_path: (paths_a.root / item.markdown_path).read_text(
            encoding="utf-8"
        )
        for item in items
    }
    original_index = (paths_a.library_dir / "index.md").read_text(encoding="utf-8")

    capsys.readouterr()
    main(["export", "items"])
    out_path = tmp_path / "library.jsonl"
    out_path.write_text(capsys.readouterr().out, encoding="utf-8")

    # restore into a fresh home from the export alone
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "restored"))
    main(["import", "items", str(out_path)])
    capsys.readouterr()

    # FTS is trigger-maintained on insert, so search works before any rebuild
    main(["search", "embedded SQL database"])
    hits = json.loads(capsys.readouterr().out)
    assert hits[0]["id"] == "wikipedia:en:SQLite"

    # doctor --fix rewrites the missing scroll files; kb recompiles library/
    main(["doctor", "--fix"])
    main(["kb"])
    paths_b = get_paths()
    for relpath, text in original_scrolls.items():
        assert (paths_b.root / relpath).read_text(encoding="utf-8") == text
    assert (paths_b.library_dir / "index.md").read_text(encoding="utf-8") == original_index


# --- export/import events: whole-library portable custody (H72) -------------


def _seed_item_with_events(scrolls_home, item_id="web:demo", source="web"):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id=item_id, source=source, url=f"https://ex.org/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00", title=item_id,
        extracted_text="A held scroll.", content_hash="h",
        markdown_path=f"scrolls/{source}/x.md", stage="rendered",
    ))
    record_events(db, [
        CustodyEvent(item_id, "2026-06-13T00:00:00+00:00", "unchanged", "h", "h"),
        CustodyEvent(item_id, "2026-06-15T00:00:00+00:00", "drifted", "h", "h2"),
    ])
    return db


def test_export_events_emits_the_ledger_as_jsonl(scrolls_home, capsys):
    _seed_item_with_events(scrolls_home)
    capsys.readouterr()
    assert main(["export", "events"]) == 0
    lines = capsys.readouterr().out.splitlines()
    # raw JSONL on stdout (not a JSON envelope), one row per check, item_id named
    assert len(lines) == 2
    assert json.loads(lines[0]) == {
        "item_id": "web:demo", "checked_at": "2026-06-13T00:00:00+00:00",
        "status": "unchanged", "prior_hash": "h", "observed_hash": "h",
        "detail": None,
    }


def test_export_events_round_trips_into_a_fresh_library(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    _seed_item_with_events(scrolls_home)
    capsys.readouterr()
    main(["export", "events"])
    out_path = tmp_path / "ledger.jsonl"
    out_path.write_text(capsys.readouterr().out, encoding="utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "restored"))
    main(["init"])
    capsys.readouterr()
    assert main(["import", "events", str(out_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "imported": 2, "skipped": 0, "events": 2
    }
    # the ledger landed, newest-first, so the restored library reads the posture
    from scrolls.custody import item_events
    restored = item_events(get_paths().db_path, "web:demo")
    assert [e.status for e in restored] == ["drifted", "unchanged"]


def test_import_events_is_idempotent(scrolls_home, tmp_path, capsys):
    _seed_item_with_events(scrolls_home)
    capsys.readouterr()
    main(["export", "events"])
    out_path = tmp_path / "ledger.jsonl"
    out_path.write_text(capsys.readouterr().out, encoding="utf-8")
    # re-importing into the same library dedups every event — a custody no-op
    assert main(["import", "events", str(out_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "imported": 0, "skipped": 2, "events": 2
    }


def test_export_events_source_filter_scopes_to_the_items_facet(scrolls_home, capsys):
    _seed_item_with_events(scrolls_home, item_id="web:w", source="web")
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="github:g/g", source="github", url="https://github.com/g/g",
        saved_at="2026-06-12T00:00:00+00:00", title="g", content_hash="hg",
        markdown_path="scrolls/github/g.md", stage="rendered",
    ))
    record_events(db, [CustodyEvent("github:g/g", "2026-06-14T00:00:00+00:00", "rotted", "hg", None, "404")])
    capsys.readouterr()
    assert main(["export", "events", "--source", "github"]) == 0
    lines = capsys.readouterr().out.splitlines()
    # only the github item's events travel (scoped by the same items facet)
    assert len(lines) == 1
    assert json.loads(lines[0])["item_id"] == "github:g/g"


def test_export_events_empty_library_is_valid(scrolls_home, capsys):
    main(["init"])
    capsys.readouterr()
    assert main(["export", "events"]) == 0
    assert capsys.readouterr().out == ""  # an empty JSONL document, never a crash


def test_export_events_before_init_is_an_empty_document(scrolls_home, capsys):
    capsys.readouterr()
    assert main(["export", "events"]) == 0
    assert capsys.readouterr().out == ""
    assert not scrolls_home.exists()  # export never creates a library


def test_import_events_missing_file_is_an_error(scrolls_home, tmp_path, capsys):
    assert main(["import", "events", str(tmp_path / "nowhere.jsonl")]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


# --- export events --since: the incremental custody backup (H75) ------------


def test_export_events_since_windows_the_ledger(scrolls_home, capsys):
    # the seed has a 06-13 unchanged and a 06-15 drifted check for web:demo
    _seed_item_with_events(scrolls_home)
    capsys.readouterr()
    assert main(["export", "events", "--since", "2026-06-15T00:00:00+00:00"]) == 0
    lines = capsys.readouterr().out.splitlines()
    # only the 06-15 check travels; the 06-13 one is before the window (boundary
    # inclusive — the 06-15 check exactly at it stays)
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["checked_at"] == "2026-06-15T00:00:00+00:00"
    assert row["status"] == "drifted"


def test_export_events_since_empty_window_is_an_empty_document(scrolls_home, capsys):
    _seed_item_with_events(scrolls_home)
    capsys.readouterr()
    # nothing falls in the window — a valid empty JSONL doc, never a crash
    assert main(["export", "events", "--since", "2026-08-01T00:00:00+00:00"]) == 0
    assert capsys.readouterr().out == ""


def test_export_events_malformed_since_is_a_usage_error(scrolls_home, capsys):
    _seed_item_with_events(scrolls_home)
    capsys.readouterr()
    exit_code = main(["export", "events", "--since", "yesterday"])
    captured = capsys.readouterr()
    assert exit_code == 2  # loud usage error, the `maintain --trend` precedent
    assert captured.out == ""  # no partial backup written
    assert "error" in json.loads(captured.err)


def test_export_events_since_composes_with_the_source_facet(scrolls_home, capsys):
    # window then scope: a github check inside the window, a web one outside it
    _seed_item_with_events(scrolls_home, item_id="web:w", source="web")
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="github:g/g", source="github", url="https://github.com/g/g",
        saved_at="2026-06-12T00:00:00+00:00", title="g", content_hash="hg",
        markdown_path="scrolls/github/g.md", stage="rendered",
    ))
    record_events(db, [
        CustodyEvent("github:g/g", "2026-06-16T00:00:00+00:00", "rotted", "hg", None, "404"),
    ])
    capsys.readouterr()
    assert main(
        ["export", "events", "--since", "2026-06-16T00:00:00+00:00", "--source", "github"]
    ) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["item_id"] == "github:g/g"


def test_export_events_since_union_reimports_idempotently(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    # the incremental-backup contract: a full backup plus an overlapping --since
    # backup, imported together into a fresh library, dedups to the whole ledger
    _seed_item_with_events(scrolls_home)  # 06-13 + 06-15 for web:demo
    capsys.readouterr()

    main(["export", "events"])
    full = tmp_path / "full.jsonl"
    full.write_text(capsys.readouterr().out, encoding="utf-8")

    main(["export", "events", "--since", "2026-06-15T00:00:00+00:00"])
    incremental = tmp_path / "incr.jsonl"  # overlaps the full backup's 06-15 row
    incremental.write_text(capsys.readouterr().out, encoding="utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "restored"))
    main(["init"])
    capsys.readouterr()
    assert main(["import", "events", str(full)]) == 0
    assert json.loads(capsys.readouterr().out) == {"imported": 2, "skipped": 0, "events": 2}
    # the incremental backup's one row is already held — a custody no-op
    assert main(["import", "events", str(incremental)]) == 0
    assert json.loads(capsys.readouterr().out) == {"imported": 0, "skipped": 1, "events": 1}

    from scrolls.custody import item_events
    restored = item_events(get_paths().db_path, "web:demo")
    assert [e.status for e in restored] == ["drifted", "unchanged"]  # whole ledger, once


# --- export/import archive: the portable prior-content recovery store (H280) -


def _seed_archived_prior(item_id="web:demo", *, archived_at="2026-06-22T00:00:00+00:00"):
    """Init a library, hold an item, adopt a divergent capture so one prior is
    archived. Returns (db_path, prior) — the prior recoverable byte-for-byte."""
    main(["init"])
    db = get_paths().db_path
    prior = ScrollItem(
        id=item_id, source=item_id.split(":")[0], url=f"https://{item_id}.example",
        saved_at="2026-06-11T00:00:00+00:00", title="Held", raw_text="OLD",
        extracted_text="OLD", content_hash="sha256:old",
        markdown_path=f"scrolls/{item_id}.md", stage="rendered",
    )
    insert_item(db, prior)
    incoming = dataclasses.replace(prior, raw_text="NEW", extracted_text="NEW",
                                   content_hash="sha256:new")
    adopt_incoming(db, incoming, archived_at=archived_at)
    return db, prior


def test_export_archive_emits_the_recovery_store_as_jsonl(scrolls_home, capsys):
    _seed_archived_prior()
    capsys.readouterr()
    assert main(["export", "archive"]) == 0
    lines = capsys.readouterr().out.splitlines()
    # raw JSONL on stdout (not a JSON envelope), one row per archived prior
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["item_id"] == "web:demo"
    assert row["prior_hash"] == "sha256:old"
    assert row["superseded_by"] == "sha256:new"
    assert row["archived_at"] == "2026-06-22T00:00:00+00:00"
    assert row["snapshot"]["content_hash"] == "sha256:old"  # the model-complete prior


def test_export_archive_round_trips_into_a_fresh_library(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    _, prior = _seed_archived_prior()
    capsys.readouterr()
    main(["export", "archive"])
    out_path = tmp_path / "archive.jsonl"
    out_path.write_text(capsys.readouterr().out, encoding="utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "restored"))
    main(["init"])
    capsys.readouterr()
    assert main(["import", "archive", str(out_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "imported": 1, "skipped": 0, "archive": 1
    }
    # the prior is recoverable on the restored library, byte-for-byte
    assert latest_archived(get_paths().db_path, "web:demo") == prior


def test_import_archive_is_idempotent(scrolls_home, tmp_path, capsys):
    _seed_archived_prior()
    capsys.readouterr()
    main(["export", "archive"])
    out_path = tmp_path / "archive.jsonl"
    out_path.write_text(capsys.readouterr().out, encoding="utf-8")
    # re-importing into the same library dedups by (item_id, prior_hash) — a no-op
    assert main(["import", "archive", str(out_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "imported": 0, "skipped": 1, "archive": 1
    }
    assert len(archived_records(get_paths().db_path)) == 1


def test_export_archive_id_filter_scopes_to_one_item(scrolls_home, capsys):
    db, _ = _seed_archived_prior("web:a")
    # a second held item with its own archived prior
    other = ScrollItem(
        id="web:b", source="web", url="https://b.example",
        saved_at="2026-06-11T00:00:00+00:00", content_hash="sha256:ob",
        raw_text="x", stage="rendered",
    )
    insert_item(db, other)
    adopt_incoming(db, dataclasses.replace(other, content_hash="sha256:nb", raw_text="y"),
                   archived_at="2026-06-22T01:00:00+00:00")
    capsys.readouterr()
    assert main(["export", "archive", "--id", "web:a"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["item_id"] == "web:a"


def test_export_archive_empty_library_is_valid(scrolls_home, capsys):
    main(["init"])
    capsys.readouterr()
    assert main(["export", "archive"]) == 0
    assert capsys.readouterr().out == ""  # a valid empty JSONL doc, never a crash


def test_export_archive_before_init_is_an_empty_document(scrolls_home, capsys):
    capsys.readouterr()
    assert main(["export", "archive"]) == 0
    assert capsys.readouterr().out == ""
    assert not scrolls_home.exists()  # export never creates a library


def test_import_archive_missing_file_is_an_error(scrolls_home, tmp_path, capsys):
    assert main(["import", "archive", str(tmp_path / "nowhere.jsonl")]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_export_archive_unmatched_id_is_an_empty_document(scrolls_home, capsys):
    _seed_archived_prior()  # archives a prior for web:demo
    capsys.readouterr()
    # a literal id with no archived prior selects nothing — a valid empty doc
    assert main(["export", "archive", "--id", "web:never-superseded"]) == 0
    assert capsys.readouterr().out == ""


def test_export_archive_bad_url_id_is_a_usage_error(scrolls_home, capsys):
    _seed_archived_prior()
    capsys.readouterr()
    # a URL no adapter can handle can't resolve to an item id — a loud error, no output
    assert main(["export", "archive", "--id", "ftp://example.com/file"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def _seed_archived_chain_cli(item_id="web:demo", *, query_token="database"):
    """Init a library and adopt a *chain* of divergent captures at controlled
    `archived_at` stamps — a multi-supersession item whose archive holds several
    recoverable priors, not just one (`_seed_archived_prior`'s deeper cousin, the
    test_bundle `_seed_archived_chain` twin on the export/import-archive side).

    The held copy ends as v3; the archive ends holding [v0@06-20, v1@06-21,
    v2@06-22]. Strictly-increasing `archived_at` is deliberate: `export archive`
    orders by `(archived_at, item_id, prior_hash)` and the rebuilt library imports
    in that order, so A's adoption order and B's import order both yield the same
    `id DESC` newest-first history — `archive show --all` reads identically on
    either side. Returns the source library's db_path."""
    main(["init"])
    db = get_paths().db_path
    held = ScrollItem(
        id=item_id, source=item_id.split(":")[0], url=f"https://{item_id}.example",
        saved_at="2026-06-11T00:00:00+00:00", title="Held",
        raw_text=f"<raw>The original {query_token} capture.</raw>",
        extracted_text=f"The original {query_token} capture.",
        content_hash="sha256:v0",
        markdown_path=f"scrolls/{item_id}.md", stage="rendered",
    )
    insert_item(db, held)
    for n, at in ((1, "2026-06-20T00:00:00+00:00"),
                  (2, "2026-06-21T00:00:00+00:00"),
                  (3, "2026-06-22T00:00:00+00:00")):
        incoming = dataclasses.replace(
            held,
            raw_text=f"<raw>A v{n} {query_token} capture.</raw>",
            extracted_text=f"A v{n} {query_token} capture.",
            content_hash=f"sha256:v{n}",
        )
        adopt_incoming(db, incoming, archived_at=at)
        held = incoming
    return db


def test_jsonl_backup_round_trips_the_archive_recovery_read_family(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    """The whole archive-recovery *read* family reads identically on a library
    rebuilt from `export items` + `export archive` — the H291 twin on the
    JSONL-backup path (H294).

    H291 pins that the *portable bundle*'s fenced `--with-archive` block carries
    the whole recovery family across a rebuild. The whole-library `export archive`
    JSONL is a *different* serialization (its own `import archive` restore, deduped
    by `(item_id, prior_hash)`), and nothing pinned that the recovery family
    survives *that* round-trip. Pin it: adopt a multi-supersession chain in A, back
    A up with `export items` + `export archive` to two files, rebuild a fresh B
    with `import items` + `import archive`, then assert `archive show --all`
    (byte-for-byte), `archive diff` (held↔prior hashes / fidelities /
    `changed_fields` / `would_restore`), and `archive restore --dry-run` agree
    field-for-field across A and B over all three selectors (`--hash`, `--at`,
    default-latest)."""
    item_id = "web:demo"
    db_a = _seed_archived_chain_cli(item_id)
    assert get_item(db_a, item_id).content_hash == "sha256:v3"
    assert len(list_archived(db_a, item_id)) == 3  # a genuine multi-supersession chain

    # the selectors the family reads over: the oldest prior by hash, a point-in-time
    # boundary mid-chain (picks v1@06-21, the newest at/before it), and default-latest
    selectors = (["--hash", "sha256:v0"], ["--at", "2026-06-21T12:00:00+00:00"], [])

    def read_family():
        """Run the whole recovery read-family — non-mutating (reads + a dry-run), so
        it is safe to run identically on A and on B."""
        out = {}
        capsys.readouterr()
        assert main(["archive", "show", item_id, "--all"]) == 0
        out["show_all"] = capsys.readouterr().out  # raw JSONL, compared byte-for-byte
        for sel in selectors:
            key = " ".join(sel) or "latest"
            capsys.readouterr()
            assert main(["archive", "diff", item_id, *sel]) == 0
            out[f"diff:{key}"] = json.loads(capsys.readouterr().out)
            capsys.readouterr()
            assert main(["archive", "restore", item_id, *sel, "--dry-run"]) == 0
            out[f"restore:{key}"] = json.loads(capsys.readouterr().out)
        return out

    family_a = read_family()
    # sanity: the family read something non-trivial in A — the full 3-prior chain and a
    # real would-change delta (a vacuous all-empty read would pass the A==B tie falsely)
    assert len(family_a["show_all"].splitlines()) == 3
    assert family_a["diff:--hash sha256:v0"]["would_restore"] is True
    assert family_a["restore:--at 2026-06-21T12:00:00+00:00"]["prior_hash"] == "sha256:v1"

    # back A up to two JSONL files — the whole-library backup, no bundle
    capsys.readouterr()
    assert main(["export", "items"]) == 0
    items_path = tmp_path / "library.jsonl"
    items_path.write_text(capsys.readouterr().out, encoding="utf-8")
    capsys.readouterr()
    assert main(["export", "archive"]) == 0
    archive_path = tmp_path / "archive.jsonl"
    archive_path.write_text(capsys.readouterr().out, encoding="utf-8")

    # rebuild a fresh library B from the two backups (held rows, then their priors)
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()
    assert main(["import", "items", str(items_path)]) == 0
    assert main(["import", "archive", str(archive_path)]) == 0
    capsys.readouterr()

    # the rebuilt library holds the same head and the same chain depth before reading
    assert get_item(db_b, item_id).content_hash == "sha256:v3"
    assert len(list_archived(db_b, item_id)) == 3

    # the whole recovery read-family is byte/field-identical across the round trip
    assert read_family() == family_a


def test_jsonl_backup_round_trip_breaks_if_the_archive_stream_is_truncated(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    """Mutation guard: the A==B family tie is non-vacuous — dropping rows from the
    `export archive` stream before rebuilding B makes the recovery family read
    *differently* on B, so the round-trip assertion would catch a lossy backup."""
    item_id = "web:demo"
    _seed_archived_chain_cli(item_id)
    capsys.readouterr()
    main(["export", "items"])
    items_path = tmp_path / "library.jsonl"
    items_path.write_text(capsys.readouterr().out, encoding="utf-8")
    main(["export", "archive"])
    archive_path = tmp_path / "archive.jsonl"
    full = capsys.readouterr().out
    # truncate the recovery store to its oldest prior alone (drop v1, v2)
    archive_path.write_text(full.splitlines(keepends=True)[0], encoding="utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()
    main(["import", "items", str(items_path)])
    main(["import", "archive", str(archive_path)])
    capsys.readouterr()
    # B's archive lost two priors — the recovery family cannot read identically
    assert len(list_archived(db_b, item_id)) == 1
    capsys.readouterr()
    assert main(["archive", "show", item_id, "--all"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 1  # vs. 3 on the full backup


# --- export archive --id <ref>: the scoped per-item recovery-store backup
# round-trips one item's recovery read-family identically while excluding its
# siblings (H300, the H294 whole-library twin on the --id-scoped export path) ---


def _seed_one_prior_cli(item_id, *, query_token="database"):
    """Adopt a *single*-supersession chain on `item_id` in an already-init'd
    library — the one-prior cousin of `_seed_archived_chain_cli`, used to seed a
    *sibling* item whose archive must be correctly *excluded* from a scoped
    `export archive --id <X>` (H300). Held ends as v1; the archive holds
    [y0@06-20]. Distinct `sha256:y*` hashes keep it clearly apart from the
    `sha256:v*` chain. Returns the db_path."""
    db = get_paths().db_path
    held = ScrollItem(
        id=item_id, source=item_id.split(":")[0], url=f"https://{item_id}.example",
        saved_at="2026-06-11T00:00:00+00:00", title="Held sibling",
        raw_text=f"<raw>The original {query_token} sibling.</raw>",
        extracted_text=f"The original {query_token} sibling.",
        content_hash="sha256:y0",
        markdown_path=f"scrolls/{item_id}.md", stage="rendered",
    )
    insert_item(db, held)
    incoming = dataclasses.replace(
        held,
        raw_text=f"<raw>A v1 {query_token} sibling.</raw>",
        extracted_text=f"A v1 {query_token} sibling.",
        content_hash="sha256:y1",
    )
    adopt_incoming(db, incoming, archived_at="2026-06-20T00:00:00+00:00")
    return db


def test_scoped_export_archive_round_trips_one_items_recovery_read_family(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    """The *per-item* `export archive --id <X>` round-trips X's whole recovery
    read-family identically — the H294 twin on the scoped export path — while a
    sibling item Y's archive is correctly *excluded* from the backup.

    H294 pins the *whole-library* `export archive` (`archived_records(db, None)`)
    round-trip. The `--id <ref>`-scoped export folds a *different* read
    (`archived_records(db, [item_id])`) — the operator move "back up *just this
    item's* recoverable history" — and nothing pinned that the scoped fold
    round-trips the recovery family for that item identically *and* genuinely
    excludes the others. Pin it: adopt a multi-supersession chain on X *and* a
    one-prior chain on Y in A, `export archive --id X` (+ a whole-library
    `export items`), rebuild a fresh B, then assert X's `archive show --all`
    (byte-for-byte), `archive diff`, and `archive restore --dry-run` agree
    field-for-field across A and B over all three selectors (`--hash`/`--at`/
    default-latest), and Y's archive is *absent* on B (a vacuous "everything
    travelled" would pass falsely)."""
    item_x, item_y = "web:demo", "web:sibling"
    db_a = _seed_archived_chain_cli(item_x)  # X: 3-prior chain, held = v3
    _seed_one_prior_cli(item_y)              # Y: 1-prior chain, held = y1
    assert get_item(db_a, item_x).content_hash == "sha256:v3"
    assert len(list_archived(db_a, item_x)) == 3
    assert len(list_archived(db_a, item_y)) == 1  # Y has a real archive in A

    selectors = (["--hash", "sha256:v0"], ["--at", "2026-06-21T12:00:00+00:00"], [])

    def read_family(item_id):
        """The whole recovery read-family for one item — non-mutating (reads + a
        dry-run), so it is safe to run identically on A and on B."""
        out = {}
        capsys.readouterr()
        assert main(["archive", "show", item_id, "--all"]) == 0
        out["show_all"] = capsys.readouterr().out  # raw JSONL, compared byte-for-byte
        for sel in selectors:
            key = " ".join(sel) or "latest"
            capsys.readouterr()
            assert main(["archive", "diff", item_id, *sel]) == 0
            out[f"diff:{key}"] = json.loads(capsys.readouterr().out)
            capsys.readouterr()
            assert main(["archive", "restore", item_id, *sel, "--dry-run"]) == 0
            out[f"restore:{key}"] = json.loads(capsys.readouterr().out)
        return out

    family_x_a = read_family(item_x)
    # sanity: a non-trivial read in A — the full 3-prior chain and a real
    # would-change delta (a vacuous all-empty read would pass the A==B tie falsely)
    assert len(family_x_a["show_all"].splitlines()) == 3
    assert family_x_a["diff:--hash sha256:v0"]["would_restore"] is True
    assert family_x_a["restore:--at 2026-06-21T12:00:00+00:00"]["prior_hash"] == "sha256:v1"

    # back A up: whole-library held rows, but ONLY X's recovery store (--id X)
    capsys.readouterr()
    assert main(["export", "items"]) == 0
    items_path = tmp_path / "library.jsonl"
    items_path.write_text(capsys.readouterr().out, encoding="utf-8")
    capsys.readouterr()
    assert main(["export", "archive", "--id", item_x]) == 0
    archive_path = tmp_path / "archive-x.jsonl"
    scoped = capsys.readouterr().out
    archive_path.write_text(scoped, encoding="utf-8")
    # the scoped backup carries only X's priors (3 lines), none of Y's
    assert len(scoped.splitlines()) == 3
    assert all(json.loads(line)["item_id"] == item_x for line in scoped.splitlines())

    # rebuild a fresh B from the whole-library items + the X-scoped recovery store
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()
    assert main(["import", "items", str(items_path)]) == 0
    assert main(["import", "archive", str(archive_path)]) == 0
    capsys.readouterr()

    # B holds both held heads (the whole-library items backup) ...
    assert get_item(db_b, item_x).content_hash == "sha256:v3"
    assert get_item(db_b, item_y).content_hash == "sha256:y1"
    # ... but only X's recovery store travelled; Y's archive is absent on B
    assert len(list_archived(db_b, item_x)) == 3
    assert list_archived(db_b, item_y) == []
    capsys.readouterr()
    assert main(["archive", "show", item_y, "--all"]) == 1  # no history → could-not-recover

    # X's whole recovery read-family is byte/field-identical across the scoped round trip
    assert read_family(item_x) == family_x_a


def test_scoped_export_archive_excludes_the_unscoped_items_history(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    """Mutation guard: the scope genuinely *selects* one item — `export archive
    --id Y` carries Y's history and leaves X's out, so X's recovery family cannot
    read on the rebuild. Inverts the H300 happy path (scope Y instead of X), so a
    bug that ignored `--id` and dumped the whole archive would fail here."""
    item_x, item_y = "web:demo", "web:sibling"
    _seed_archived_chain_cli(item_x)  # X: 3-prior chain
    _seed_one_prior_cli(item_y)       # Y: 1-prior chain

    capsys.readouterr()
    assert main(["export", "items"]) == 0
    items_path = tmp_path / "library.jsonl"
    items_path.write_text(capsys.readouterr().out, encoding="utf-8")
    capsys.readouterr()
    assert main(["export", "archive", "--id", item_y]) == 0  # scope the *sibling*
    scoped = capsys.readouterr().out
    archive_path = tmp_path / "archive-y.jsonl"
    archive_path.write_text(scoped, encoding="utf-8")
    # only Y's single prior travelled — X's three are excluded by the scope
    assert [json.loads(line)["item_id"] for line in scoped.splitlines()] == [item_y]

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()
    main(["import", "items", str(items_path)])
    main(["import", "archive", str(archive_path)])
    capsys.readouterr()

    # Y's history is recoverable on B; X's is empty — the scope excluded it
    assert len(list_archived(db_b, item_y)) == 1
    assert list_archived(db_b, item_x) == []
    capsys.readouterr()
    assert main(["archive", "show", item_x, "--all"]) == 1  # the family cannot read X


# --- export archive --source <S>: the source-scoped recovery-store backup, the
# `export events --source` analogue on the archive axis (H301) ----------------


def test_export_archive_source_filter_scopes_to_one_source(scrolls_home, capsys):
    """`--source <S>` selects exactly the held items of one source — unlike `--id`
    (one item) it gathers *all* of a source's items' archived priors. Two `web`
    items and one `arxiv` item, each with an archived prior: `--source web` carries
    the two web priors and excludes the arxiv one (the `--id` selection test's
    source-scoped twin)."""
    db = _seed_archived_chain_cli("web:demo")  # web, 3-prior chain
    _seed_one_prior_cli("web:two")             # web, 1-prior chain (same source)
    _seed_one_prior_cli("arxiv:sib")           # arxiv, 1-prior chain (excluded)
    capsys.readouterr()
    assert main(["export", "archive", "--source", "web"]) == 0
    lines = capsys.readouterr().out.splitlines()
    # the two web items' priors travel (3 + 1), none of arxiv's
    assert {json.loads(line)["item_id"] for line in lines} == {"web:demo", "web:two"}
    assert len(lines) == 4


def test_source_scoped_export_archive_round_trips_a_sources_recovery_read_family(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    """The *source*-scoped `export archive --source web` round-trips the whole
    recovery read-family for every web item identically — the H300 `--id` twin one
    level up (a source spans many items) — while a *different*-source item's archive
    is correctly *excluded* from the backup.

    H300 pins the per-*item* `export archive --id X` round-trip. `--source S` folds a
    different read: resolve the source to its held item ids (the `export events
    --source` enumeration), then *all* their archived priors travel — the operator
    move "back up *one source's* recoverable history." Pin it: a 3-prior chain on
    `web:demo` *and* a 1-prior chain on `web:two` (same source) *and* a 1-prior chain
    on `arxiv:sib` (a different source) in A, `export archive --source web` (+ a
    whole-library `export items`), rebuild a fresh B, then assert `web:demo`'s
    `archive show --all` (byte-for-byte), `archive diff`, and `archive restore
    --dry-run` agree field-for-field across A and B over all three selectors
    (`--hash`/`--at`/default-latest), `web:two`'s prior travelled too, and
    `arxiv:sib`'s archive is *absent* on B (a vacuous "everything travelled" would
    pass falsely)."""
    db_a = _seed_archived_chain_cli("web:demo")  # web, 3-prior chain, held = v3
    _seed_one_prior_cli("web:two")               # web, 1-prior chain, held = y1
    _seed_one_prior_cli("arxiv:sib")             # arxiv, 1-prior chain (excluded)
    assert get_item(db_a, "web:demo").content_hash == "sha256:v3"
    assert len(list_archived(db_a, "web:demo")) == 3
    assert len(list_archived(db_a, "web:two")) == 1
    assert len(list_archived(db_a, "arxiv:sib")) == 1  # arxiv has a real archive in A

    selectors = (["--hash", "sha256:v0"], ["--at", "2026-06-21T12:00:00+00:00"], [])

    def read_family(item_id):
        """The whole recovery read-family for one item — non-mutating (reads + a
        dry-run), so it is safe to run identically on A and on B."""
        out = {}
        capsys.readouterr()
        assert main(["archive", "show", item_id, "--all"]) == 0
        out["show_all"] = capsys.readouterr().out  # raw JSONL, compared byte-for-byte
        for sel in selectors:
            key = " ".join(sel) or "latest"
            capsys.readouterr()
            assert main(["archive", "diff", item_id, *sel]) == 0
            out[f"diff:{key}"] = json.loads(capsys.readouterr().out)
            capsys.readouterr()
            assert main(["archive", "restore", item_id, *sel, "--dry-run"]) == 0
            out[f"restore:{key}"] = json.loads(capsys.readouterr().out)
        return out

    family_demo_a = read_family("web:demo")
    # sanity: a non-trivial read in A — the full 3-prior chain and a real
    # would-change delta (a vacuous all-empty read would pass the A==B tie falsely)
    assert len(family_demo_a["show_all"].splitlines()) == 3
    assert family_demo_a["diff:--hash sha256:v0"]["would_restore"] is True
    assert family_demo_a["restore:--at 2026-06-21T12:00:00+00:00"]["prior_hash"] == "sha256:v1"

    # back A up: whole-library held rows, but ONLY the web source's recovery store
    capsys.readouterr()
    assert main(["export", "items"]) == 0
    items_path = tmp_path / "library.jsonl"
    items_path.write_text(capsys.readouterr().out, encoding="utf-8")
    capsys.readouterr()
    assert main(["export", "archive", "--source", "web"]) == 0
    scoped = capsys.readouterr().out
    archive_path = tmp_path / "archive-web.jsonl"
    archive_path.write_text(scoped, encoding="utf-8")
    # the scoped backup carries only the two web items' priors (3 + 1), no arxiv
    assert {json.loads(line)["item_id"] for line in scoped.splitlines()} == {
        "web:demo", "web:two"
    }
    assert len(scoped.splitlines()) == 4

    # rebuild a fresh B from the whole-library items + the web-scoped recovery store
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()
    assert main(["import", "items", str(items_path)]) == 0
    assert main(["import", "archive", str(archive_path)]) == 0
    capsys.readouterr()

    # B holds all three held heads (the whole-library items backup) ...
    assert get_item(db_b, "web:demo").content_hash == "sha256:v3"
    assert get_item(db_b, "web:two").content_hash == "sha256:y1"
    assert get_item(db_b, "arxiv:sib").content_hash == "sha256:y1"
    # ... but only the web source's recovery store travelled; arxiv's is absent
    assert len(list_archived(db_b, "web:demo")) == 3
    assert len(list_archived(db_b, "web:two")) == 1
    assert list_archived(db_b, "arxiv:sib") == []
    capsys.readouterr()
    assert main(["archive", "show", "arxiv:sib", "--all"]) == 1  # no history → exit 1

    # web:demo's whole recovery read-family is byte/field-identical across the round trip
    assert read_family("web:demo") == family_demo_a


def test_source_scoped_export_archive_excludes_other_sources(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    """Mutation guard: the scope genuinely *selects* one source — `export archive
    --source arxiv` carries arxiv's history and leaves the web items' out, so the
    web items' recovery family cannot read on the rebuild. Inverts the H301 happy
    path (scope arxiv instead of web), so a bug that ignored `--source` and dumped
    the whole archive would fail here."""
    _seed_archived_chain_cli("web:demo")  # web, 3-prior chain
    _seed_one_prior_cli("web:two")        # web, 1-prior chain
    _seed_one_prior_cli("arxiv:sib")      # arxiv, 1-prior chain

    capsys.readouterr()
    assert main(["export", "items"]) == 0
    items_path = tmp_path / "library.jsonl"
    items_path.write_text(capsys.readouterr().out, encoding="utf-8")
    capsys.readouterr()
    assert main(["export", "archive", "--source", "arxiv"]) == 0  # scope the *other* source
    scoped = capsys.readouterr().out
    archive_path = tmp_path / "archive-arxiv.jsonl"
    archive_path.write_text(scoped, encoding="utf-8")
    # only arxiv's single prior travelled — the four web priors are excluded
    assert [json.loads(line)["item_id"] for line in scoped.splitlines()] == ["arxiv:sib"]

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()
    main(["import", "items", str(items_path)])
    main(["import", "archive", str(archive_path)])
    capsys.readouterr()

    # arxiv's history is recoverable on B; the web items' are empty — the scope excluded them
    assert len(list_archived(db_b, "arxiv:sib")) == 1
    assert list_archived(db_b, "web:demo") == []
    assert list_archived(db_b, "web:two") == []
    capsys.readouterr()
    assert main(["archive", "show", "web:demo", "--all"]) == 1  # the family cannot read web:demo


def test_export_archive_rejects_both_id_and_source(scrolls_home, capsys):
    """`--id` (one item) and `--source` (one source) are independent single-scope
    selectors; supplying both is a loud usage error (exit 2, stderr JSON, no
    stdout) — the `archive restore` "at most one version selector" precedent."""
    _seed_archived_prior()
    capsys.readouterr()
    assert main(["export", "archive", "--id", "web:demo", "--source", "web"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""  # never a partial backup
    assert "error" in json.loads(captured.err)


# --- export archive --fidelity / --drift: the custody-filter family on the
# recovery-store backup — the last un-filtered export surface (H302) ----------


def _seed_archive_for_custody_scope():
    """A full-fidelity item with a multi-prior recovery store *and* a
    reference-fidelity item with its own recovery store, spanning a fidelity tier
    and a drift posture; inits the library and returns its db path.

    `web:full` is full-fidelity (a re-derivable body + hash), a 3-prior chain
    [v0,v1,v2] (held v3), and recorded *drifted*; `web:ref` is reference-only (its
    held copy holds just the pointer, the prior was a full capture), a 1-prior
    chain [r0] (held r1), and recorded *rotted*. Each carries a non-empty archive,
    so `--fidelity full` keeping only web:full's priors (and `--drift drifted`
    likewise) is a *non-vacuous* selection — the excluded item has a recovery store
    of its own to leave behind, not a phantom. The distinct archive depths (3 vs 1)
    prove the *whole* recovery store of the selected items travels."""
    db = _seed_archived_chain_cli("web:full")  # full fidelity, 3-prior chain, held v3
    # web:ref — a held copy degraded to reference-only (no body), with one archived
    # full prior; the prior travels in the recovery store, the held tier is reference
    insert_item(db, ScrollItem(
        id="web:ref", source="web", url="https://web-ref.example",
        saved_at="2026-06-11T00:00:01+00:00", title="Held (full prior)",
        raw_text="<raw>The original reference capture.</raw>",
        extracted_text="The original reference capture.",
        content_hash="sha256:r0",
        markdown_path="scrolls/web-ref.md", stage="rendered"))
    adopt_incoming(db, ScrollItem(
        id="web:ref", source="web", url="https://web-ref.example",
        saved_at="2026-06-11T00:00:01+00:00", title="Held (reference now)",
        content_hash="sha256:r1", stage="detected"),
        archived_at="2026-06-20T00:00:00+00:00")
    record_events(db, [
        CustodyEvent("web:full", "2026-06-23T00:00:00+00:00", "drifted",
                     "sha256:v3", "sha256:v4"),
        CustodyEvent("web:ref", "2026-06-23T00:00:00+00:00", "rotted",
                     "sha256:r1", None, "404"),
    ])
    return db


def test_export_archive_fidelity_scopes_to_the_items_recovery_store(
    scrolls_home, capsys
):
    # back up only the recovery store of items held at one fidelity tier — the
    # item-set sieve selects the items `scrolls list --fidelity` enumerates, then
    # their whole archived history travels (ADR 0097, the holdings-axis companion
    # of --drift). The reference item's recovery store stays home.
    _seed_archive_for_custody_scope()
    capsys.readouterr()

    assert main(["export", "archive", "--fidelity", "full"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    # only web:full's archive (its whole 3-prior chain); the reference item stays home
    assert {row["item_id"] for row in rows} == {"web:full"}
    assert len(rows) == 3

    assert main(["export", "archive", "--fidelity", "reference"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {row["item_id"] for row in rows} == {"web:ref"}
    assert len(rows) == 1


def test_export_archive_drift_is_the_item_set_sieve_carrying_the_whole_store(
    scrolls_home, capsys
):
    # the item-set-vs-per-prior decision (the H260 shape): `--drift drifted`
    # selects the items *currently* drifted, then ships their *whole* archived
    # history — mirroring how `--source` already scopes the recovery store by item,
    # not a per-prior filter. web:full is drifted (3 priors), web:ref rotted (1).
    _seed_archive_for_custody_scope()
    capsys.readouterr()

    assert main(["export", "archive", "--drift", "drifted"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {row["item_id"] for row in rows} == {"web:full"}
    assert len(rows) == 3  # the moved item's whole recovery store, for a recapture handoff

    # the rotted item is reachable by its current posture on the same axis
    assert main(["export", "archive", "--drift", "rotted"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {row["item_id"] for row in rows} == {"web:ref"}
    assert len(rows) == 1


def test_export_archive_custody_axes_and_together(scrolls_home, capsys):
    # both axes AND: --fidelity intersects --drift. The seed's web:full is
    # full+drifted, web:ref is reference+rotted.
    _seed_archive_for_custody_scope()
    capsys.readouterr()

    # the intersection full *and* drifted is exactly web:full's recovery store
    assert main(["export", "archive", "--fidelity", "full", "--drift", "drifted"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {row["item_id"] for row in rows} == {"web:full"}

    # an empty intersection (no full-fidelity rotted item) is the honest empty
    # document, never an error — the `export items`/`export events` precedent
    assert main(["export", "archive", "--fidelity", "full", "--drift", "rotted"]) == 0
    assert capsys.readouterr().out == ""


def test_export_archive_custody_scope_ands_with_source(scrolls_home, capsys):
    # --source (H301) ANDs with --fidelity/--drift (H302): each narrows the item
    # set, the intersection's whole recovery store travels. A *different*-source
    # full-fidelity item proves --source genuinely intersects the custody axis.
    _seed_archive_for_custody_scope()  # web:full (full, 3 priors), web:ref (reference, 1)
    _seed_one_prior_cli("arxiv:full")  # arxiv, full fidelity, 1-prior chain
    capsys.readouterr()

    # web AND full = web:full only (arxiv:full is full but a different source;
    # web:ref is web but reference)
    assert main(["export", "archive", "--source", "web", "--fidelity", "full"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {row["item_id"] for row in rows} == {"web:full"}
    assert len(rows) == 3

    # web AND rotted = web:ref only
    assert main(["export", "archive", "--source", "web", "--drift", "rotted"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {row["item_id"] for row in rows} == {"web:ref"}


def test_custody_scoped_export_archive_round_trips_the_recovery_read_family(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    """A custody-scoped `export archive --fidelity full` round-trips the whole
    recovery read-family for the selected items identically — the H300/H301 shape
    under a *custody* scope — while an excluded (reference-fidelity) item's archive
    is correctly absent on the rebuild.

    H300 pins the `--id`-scoped round-trip, H301 the `--source`-scoped one. H302's
    custody filter folds a *different* item resolution (`list_items(fidelity=...)`),
    and nothing pinned that its scoped archive round-trips the recovery family
    identically *and* genuinely leaves the other-tier items behind. Pin it: a
    full-fidelity multi-supersession item *and* a reference-fidelity item, each with
    a recovery store, `export archive --fidelity full` (+ a whole-library `export
    items`), rebuild a fresh B, then assert web:full's `archive show --all`
    (byte-for-byte), `archive diff`, and `archive restore --dry-run` agree
    field-for-field across A and B over all three selectors (`--hash`/`--at`/
    default-latest), and web:ref's archive is *absent* on B (a vacuous "everything
    travelled" would pass falsely). The --drift axis folds the same `list_items`
    sieve, so this one round-trip pins both axes."""
    from scrolls.items import get_fidelity

    db_a = _seed_archive_for_custody_scope()
    assert get_item(db_a, "web:full").content_hash == "sha256:v3"
    assert len(list_archived(db_a, "web:full")) == 3
    assert len(list_archived(db_a, "web:ref")) == 1  # the excluded item has a real archive
    assert get_fidelity(get_item(db_a, "web:ref")) == "reference"  # excluded by --fidelity full

    selectors = (["--hash", "sha256:v0"], ["--at", "2026-06-21T12:00:00+00:00"], [])

    def read_family(item_id):
        """The whole recovery read-family for one item — non-mutating (reads + a
        dry-run), so it is safe to run identically on A and on B."""
        out = {}
        capsys.readouterr()
        assert main(["archive", "show", item_id, "--all"]) == 0
        out["show_all"] = capsys.readouterr().out  # raw JSONL, compared byte-for-byte
        for sel in selectors:
            key = " ".join(sel) or "latest"
            capsys.readouterr()
            assert main(["archive", "diff", item_id, *sel]) == 0
            out[f"diff:{key}"] = json.loads(capsys.readouterr().out)
            capsys.readouterr()
            assert main(["archive", "restore", item_id, *sel, "--dry-run"]) == 0
            out[f"restore:{key}"] = json.loads(capsys.readouterr().out)
        return out

    family_full_a = read_family("web:full")
    # sanity: a non-trivial read in A — the full 3-prior chain and a real
    # would-change delta (a vacuous all-empty read would pass the A==B tie falsely)
    assert len(family_full_a["show_all"].splitlines()) == 3
    assert family_full_a["diff:--hash sha256:v0"]["would_restore"] is True
    assert family_full_a["restore:--at 2026-06-21T12:00:00+00:00"]["prior_hash"] == "sha256:v1"

    # back A up: whole-library held rows, but ONLY the full-fidelity recovery store
    capsys.readouterr()
    assert main(["export", "items"]) == 0
    items_path = tmp_path / "library.jsonl"
    items_path.write_text(capsys.readouterr().out, encoding="utf-8")
    capsys.readouterr()
    assert main(["export", "archive", "--fidelity", "full"]) == 0
    scoped = capsys.readouterr().out
    archive_path = tmp_path / "archive-full.jsonl"
    archive_path.write_text(scoped, encoding="utf-8")
    # the scoped backup carries only the full item's priors (3 lines), none of the reference's
    assert {json.loads(line)["item_id"] for line in scoped.splitlines()} == {"web:full"}
    assert len(scoped.splitlines()) == 3

    # rebuild a fresh B from the whole-library items + the full-fidelity recovery store
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()
    assert main(["import", "items", str(items_path)]) == 0
    assert main(["import", "archive", str(archive_path)]) == 0
    capsys.readouterr()

    # B holds both held heads (the whole-library items backup) ...
    assert get_item(db_b, "web:full").content_hash == "sha256:v3"
    assert get_item(db_b, "web:ref").content_hash == "sha256:r1"
    # ... but only the full item's recovery store travelled; the reference item's is absent
    assert len(list_archived(db_b, "web:full")) == 3
    assert list_archived(db_b, "web:ref") == []
    capsys.readouterr()
    assert main(["archive", "show", "web:ref", "--all"]) == 1  # no history → exit 1

    # web:full's whole recovery read-family is byte/field-identical across the round trip
    assert read_family("web:full") == family_full_a


def test_export_archive_rejects_id_combined_with_custody_filters(scrolls_home, capsys):
    """`--id` selects one precise item; `--fidelity`/`--drift` are the
    library-filter group (an item-set sieve) — two selection modes, so mixing them
    is a loud usage error (exit 2, stderr JSON, no stdout), the both-id-and-source
    precedent extended to the custody axes."""
    _seed_archived_prior()
    for extra in (["--fidelity", "full"], ["--drift", "drifted"]):
        capsys.readouterr()
        assert main(["export", "archive", "--id", "web:demo", *extra]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""  # never a partial backup
        assert "error" in json.loads(captured.err)


def test_export_archive_rejects_an_unknown_fidelity_tier(scrolls_home):
    # fidelity tiers are a closed vocabulary; a typo is exit 2, never a silent
    # empty backup (the `export events --fidelity` precedent)
    with pytest.raises(SystemExit) as excinfo:
        main(["export", "archive", "--fidelity", "ful"])
    assert excinfo.value.code == 2


def test_export_archive_rejects_an_unknown_drift_posture(scrolls_home):
    # drift postures are a closed vocabulary; a typo is exit 2, never a silent empty
    with pytest.raises(SystemExit) as excinfo:
        main(["export", "archive", "--drift", "drited"])
    assert excinfo.value.code == 2


def test_cmd_export_archive_unknown_tier_on_the_programmatic_path_is_exit_1(
    scrolls_home, capsys
):
    # belt-and-braces below argparse: a direct call past `choices` surfaces the
    # `list_items` ValueError as a JSON error on stderr, exit 1 (the
    # `_cmd_export_events` precedent), never a stdout backup
    from scrolls.cli import _cmd_export_archive

    main(["init"])
    capsys.readouterr()
    exit_code = _cmd_export_archive(None, None, "bogus-tier", None)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


# --- export archive --content-duplicate: the content-identity item-set sieve on
# the recovery-store backup (H347), the content-identity sibling of `export archive
# --fidelity`/`--drift` (H302) and the archive counterpart of `export events
# --content-duplicate`. The *whole* recovery store of each selected item travels, so
# a recipient deduping the redundant copies keeps the recoverable priors of each. --


def _seed_archive_for_content_duplicate_scope():
    """A cross-source byte-identical *held* pair, each with its own recovery store,
    + a unique held item with its own store; inits the library, returns the db path.

    `web:a` and `arxiv:1` both end *held* at `content_hash=sha256:dup` (a mirror
    captured by two adapters → a cross-source content group, so the sibling scope is
    whole-library), and each archived divergent priors on the way there — web:a a
    2-prior chain (`wa0`@06-21, `wa1`@06-22), arxiv:1 a 1-prior chain (`ar0`@06-21).
    The distinct depths prove the *whole* recovery store of the selected items
    travels. `web:solo` holds unique bytes with its own 1-prior store (`so0`), the
    non-vacuous item left behind. All three are full-fidelity (a re-derivable body),
    so `--fidelity full` keeps the pair and `--fidelity reference` empties it."""
    main(["init"])
    db = get_paths().db_path

    def hold(item_id, source, initial_hash, adopt_hashes):
        # insert a held capture, then adopt a chain ending held at adopt_hashes[-1];
        # each adoption archives the prior held capture (ADR 0106) at a fixed stamp
        held = ScrollItem(
            id=item_id, source=source, url=f"https://{item_id}.example",
            saved_at="2026-06-11T00:00:00+00:00", title="Held",
            raw_text="<raw>a body</raw>", extracted_text="a body",
            content_hash=initial_hash,
            markdown_path=f"scrolls/{item_id}.md", stage="rendered")
        insert_item(db, held)
        for n, h in enumerate(adopt_hashes, 1):
            held = dataclasses.replace(held, content_hash=h)
            adopt_incoming(db, held, archived_at=f"2026-06-2{n}T00:00:00+00:00")

    hold("web:a", "web", "sha256:wa0", ["sha256:wa1", "sha256:dup"])
    hold("arxiv:1", "arxiv", "sha256:ar0", ["sha256:dup"])
    hold("web:solo", "web", "sha256:so0", ["sha256:solo"])
    return db


def test_export_archive_content_duplicate_ships_the_siblings_recovery_store(
    scrolls_home, capsys
):
    # `--content-duplicate` selects the items the library holds a byte-identical copy
    # of under another id (the H338 sibling sieve), then ships their *whole* archived
    # history (web:a's 2 priors + arxiv:1's 1 — distinct depths), dropping web:solo's
    # recovery store. The whole-library sibling scope mirrors `export items
    # --content-duplicate` (H341).
    _seed_archive_for_content_duplicate_scope()
    capsys.readouterr()

    assert main(["export", "archive", "--content-duplicate"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {row["item_id"] for row in rows} == {"web:a", "arxiv:1"}  # web:solo dropped
    assert len(rows) == 3  # web:a's 2 priors + arxiv:1's 1 — the whole stores

    # ANDs with --source; the sibling scope stays whole-library, so --source web still
    # keeps web:a (its sibling arxiv:1 lives in another source), arxiv:1 falls out
    assert main(["export", "archive", "--content-duplicate", "--source", "web"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {row["item_id"] for row in rows} == {"web:a"}
    assert len(rows) == 2  # web:a's whole store; arxiv:1 out of source scope


def test_export_archive_content_duplicate_ands_with_fidelity_and_composes_with_since(
    scrolls_home, capsys
):
    # --content-duplicate ANDs with --fidelity (both narrow the item set) and
    # composes with the orthogonal --since window on archived_at. The pair is
    # full-fidelity, so --fidelity full keeps it and --fidelity reference empties it.
    _seed_archive_for_content_duplicate_scope()
    capsys.readouterr()

    assert main(["export", "archive", "--content-duplicate", "--fidelity", "full"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {row["item_id"] for row in rows} == {"web:a", "arxiv:1"}
    assert len(rows) == 3

    # an empty intersection (no reference-fidelity duplicate) is the honest empty doc
    assert main(["export", "archive", "--content-duplicate", "--fidelity", "reference"]) == 0
    assert capsys.readouterr().out == ""

    # --since is an orthogonal time window: web:a's wa1 prior was archived 06-22, all
    # other priors at 06-21, so a 06-22 boundary windows them out — only wa1 survives
    assert main([
        "export", "archive", "--content-duplicate", "--since", "2026-06-22T00:00:00+00:00",
    ]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["prior_hash"] for row in rows] == ["sha256:wa1"]
    assert all(row["archived_at"] >= "2026-06-22T00:00:00+00:00" for row in rows)


def test_export_archive_content_duplicate_rejects_combination_with_id(
    scrolls_home, capsys
):
    # `--id` selects one precise item; `--content-duplicate` is the library-filter
    # group (an item-set sieve) — two selection modes, so mixing them is a loud usage
    # error (exit 2, stderr JSON, no stdout), the both-id-and-source / id-and-custody
    # precedent extended to the content-identity axis.
    _seed_archive_for_content_duplicate_scope()
    capsys.readouterr()
    assert main(["export", "archive", "--id", "web:a", "--content-duplicate"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""  # never a partial backup
    assert "error" in json.loads(captured.err)


# --- export archive --since <ISO>: the incremental recovery-store backup, the
# `export events --since` analogue on the archive axis — an orthogonal *time*
# window on archived_at (H303) ------------------------------------------------


def test_export_archive_since_windows_to_the_priors_at_or_after_the_boundary(
    scrolls_home, capsys
):
    """`--since <ISO>` carries only priors archived at/after the boundary — the
    incremental backup since the last sweep. The chain archives [v0@06-20,
    v1@06-21, v2@06-22] (held = v3); a mid-chain boundary windows the earlier
    priors out, the boundary is inclusive (``>=``), a date-only form normalizes to
    that day's midnight UTC (the `parse_since` shape), and a boundary before every
    prior carries the whole store (the un-windowed shape unchanged)."""
    _seed_archived_chain_cli("web:demo")  # priors v0@06-20, v1@06-21, v2@06-22
    capsys.readouterr()

    def priors(*args):
        assert main(["export", "archive", *args]) == 0
        rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        return [row["prior_hash"] for row in rows]

    # mid-chain: only the prior archived strictly after the boundary survives
    assert priors("--since", "2026-06-21T12:00:00+00:00") == ["sha256:v2"]
    # inclusive at the exact stamp: the boundary prior itself is kept (>=, not >)
    assert priors("--since", "2026-06-21T00:00:00+00:00") == ["sha256:v1", "sha256:v2"]
    # a date-only boundary normalizes to that day's midnight UTC — picks v2 alone
    assert priors("--since", "2026-06-22") == ["sha256:v2"]
    # a boundary at/before the first prior carries the whole store (un-windowed)
    assert priors("--since", "2026-06-20T00:00:00+00:00") == [
        "sha256:v0", "sha256:v1", "sha256:v2"
    ]
    # no --since is the same whole store — the window is opt-in
    assert priors() == ["sha256:v0", "sha256:v1", "sha256:v2"]


def test_export_archive_empty_since_window_is_a_valid_empty_document(
    scrolls_home, capsys
):
    """A boundary after every archived prior carries nothing — a valid empty backup
    (exit 0, empty stdout), never an error: an incremental sweep that finds no new
    priors since the last one is the honest empty document, the `export events
    --since` / unmatched-`--id` precedent."""
    _seed_archived_chain_cli("web:demo")  # newest prior archived 2026-06-22
    capsys.readouterr()
    assert main(["export", "archive", "--since", "2026-06-23T00:00:00+00:00"]) == 0
    assert capsys.readouterr().out == ""


def test_export_archive_since_is_an_orthogonal_window_composing_with_the_item_scope(
    scrolls_home, capsys
):
    """`--since` is a *time* window, not an item-set sieve, so it ANDs with whichever
    item selector ran — it is **not** part of the `--id` vs library-filter mutual
    exclusion. With a 3-prior `web:demo` chain and a 1-prior `arxiv:sib` (archived
    06-20), `--source web --since <mid>` keeps only web:demo's later prior (arxiv
    excluded by source, web:demo's earlier priors by the window), and `--id web:demo
    --since <inclusive>` keeps that item's at/after-boundary priors."""
    _seed_archived_chain_cli("web:demo")  # web, priors v0@06-20, v1@06-21, v2@06-22
    _seed_one_prior_cli("arxiv:sib")       # arxiv, one prior y0@06-20 (excluded by source)
    capsys.readouterr()

    def rows(*args):
        assert main(["export", "archive", *args]) == 0
        return [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    # --source AND --since: the source picks web's items, the window picks the later prior
    web_recent = rows("--source", "web", "--since", "2026-06-21T12:00:00+00:00")
    assert [(r["item_id"], r["prior_hash"]) for r in web_recent] == [
        ("web:demo", "sha256:v2")
    ]

    # --id AND --since: one item's at/after-boundary priors (inclusive at the stamp)
    by_id = rows("--id", "web:demo", "--since", "2026-06-21T00:00:00+00:00")
    assert [r["prior_hash"] for r in by_id] == ["sha256:v1", "sha256:v2"]

    # sanity: dropping the window widens the same --source scope to the whole web store
    assert len(rows("--source", "web")) == 3


def test_export_archive_rejects_a_malformed_since(scrolls_home, capsys):
    """A non-timestamp `--since` is a loud usage error (exit 2, stderr JSON, no
    stdout), never a silently-empty backup that could mask a typo — the `export
    events --since` / `maintain --trend` precedent, validated before any item
    resolution."""
    _seed_archived_chain_cli("web:demo")
    capsys.readouterr()
    assert main(["export", "archive", "--since", "not-a-date"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""  # never a partial backup
    assert "error" in json.loads(captured.err)


def test_incremental_export_archive_re_imports_idempotently_over_the_full_backup(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    """The headline incremental-backup guarantee (H303): a `--since` mid-chain
    backup carries only the later priors, and re-importing the full backup *then*
    the overlapping incremental one yields the *same* archive as importing the full
    backup alone — the union is idempotent because `import archive` dedups by
    `(item_id, prior_hash)` (ADR 0106).

    The real maintenance shape: a worker takes a full backup, then later re-exports
    only `--since` the last sweep; restoring both onto a peer must never
    double-count the overlap. Pin it: seed a 3-prior chain in A, write a full
    `export archive` and an incremental `--since` (which must carry strictly fewer
    priors — non-vacuous), rebuild B from full **+** incremental and C from full
    alone, then assert B's and C's recovery stores are byte-for-byte identical and
    the whole recovery read-family reads the same on both."""
    item_id = "web:demo"
    db_a = _seed_archived_chain_cli(item_id)  # priors v0@06-20, v1@06-21, v2@06-22
    assert len(list_archived(db_a, item_id)) == 3

    capsys.readouterr()
    assert main(["export", "items"]) == 0
    items_path = tmp_path / "library.jsonl"
    items_path.write_text(capsys.readouterr().out, encoding="utf-8")

    # the full backup (all 3 priors) and the incremental window (strictly fewer)
    assert main(["export", "archive"]) == 0
    full = capsys.readouterr().out
    full_path = tmp_path / "archive-full.jsonl"
    full_path.write_text(full, encoding="utf-8")
    assert main(["export", "archive", "--since", "2026-06-21T12:00:00+00:00"]) == 0
    incremental = capsys.readouterr().out
    incremental_path = tmp_path / "archive-incremental.jsonl"
    incremental_path.write_text(incremental, encoding="utf-8")
    # non-vacuous: the incremental is a strict subset of the full backup (1 < 3),
    # and its priors are all present in the full backup (a genuine overlap)
    assert len(incremental.splitlines()) == 1
    assert len(full.splitlines()) == 3
    assert set(incremental.splitlines()).issubset(set(full.splitlines()))

    def build_library(home, *archive_files):
        monkeypatch.setenv("SCROLLS_HOME", str(home))
        main(["init"])
        capsys.readouterr()
        assert main(["import", "items", str(items_path)]) == 0
        for path in archive_files:
            assert main(["import", "archive", str(path)]) == 0
        capsys.readouterr()
        return get_paths().db_path

    # B: full THEN the overlapping incremental — the re-import-the-window workflow
    db_b = build_library(tmp_path / "library-b", full_path, incremental_path)
    # C: the full backup alone — the reference the union must equal
    db_c = build_library(tmp_path / "library-c", full_path)

    # the union is idempotent: re-importing the incremental added nothing the full
    # backup did not already carry — B's recovery store == C's, record-for-record
    assert archived_records(db_b, [item_id]) == archived_records(db_c, [item_id])
    assert len(archived_records(db_b, [item_id])) == 3  # not 4 — the overlap deduped

    # and the whole recovery read-family reads identically on the two rebuilds
    selectors = (["--hash", "sha256:v0"], ["--at", "2026-06-21T12:00:00+00:00"], [])

    def read_family(home):
        monkeypatch.setenv("SCROLLS_HOME", str(home))
        out = {}
        capsys.readouterr()
        assert main(["archive", "show", item_id, "--all"]) == 0
        out["show_all"] = capsys.readouterr().out  # raw JSONL, byte-for-byte
        for sel in selectors:
            key = " ".join(sel) or "latest"
            capsys.readouterr()
            assert main(["archive", "diff", item_id, *sel]) == 0
            out[f"diff:{key}"] = json.loads(capsys.readouterr().out)
            capsys.readouterr()
            assert main(["archive", "restore", item_id, *sel, "--dry-run"]) == 0
            out[f"restore:{key}"] = json.loads(capsys.readouterr().out)
        return out

    family_b = read_family(tmp_path / "library-b")
    assert len(family_b["show_all"].splitlines()) == 3  # the full chain survived
    assert family_b == read_family(tmp_path / "library-c")


# --- export archive --since is byte-stable across the recovery-store round-trip:
# a windowed backup re-exported from an `import archive`-rebuilt library reproduces
# the same stream byte-for-byte, even though the rebuild renumbers local ids (H305)


def _seed_interleaved_archive_cli(x_id="web:demo", y_id="arxiv:sib"):
    """Seed two items whose priors are archived in an order that *differs* from the
    content-determined `(archived_at, item_id, prior_hash)` export order, so an
    `import archive` rebuild genuinely renumbers the local autoincrement `id`.

    Adoption order (the per-library `id` order): X@06-23, Y@06-20, X@06-24, Y@06-21.
    Content-determined export order: Y@06-20, Y@06-21, X@06-23, X@06-24. The two
    differ, so windowing on `id` and windowing on `archived_at` pick *different*
    subsets — and a rebuild that imports in content order assigns local ids that no
    longer match A's (`arxiv:sib`'s 06-21 prior is the last-adopted, highest id in
    A but an early row in B). Each item's own chain stays monotonic in `archived_at`
    so `latest_archived` keeps its newest-prior meaning. Returns the db_path."""
    main(["init"])
    db = get_paths().db_path

    def _hold(item_id):
        held = ScrollItem(
            id=item_id, source=item_id.split(":")[0], url=f"https://{item_id}.example",
            saved_at="2026-06-11T00:00:00+00:00", title=f"Held {item_id}",
            raw_text=f"<raw>The original database capture for {item_id}.</raw>",
            extracted_text=f"The original database capture for {item_id}.",
            content_hash=f"sha256:{item_id}:v0",
            markdown_path=f"scrolls/{item_id}.md", stage="rendered",
        )
        insert_item(db, held)
        return held

    held = {x_id: _hold(x_id), y_id: _hold(y_id)}
    # interleave adoptions so id-order (X,Y,X,Y) ≠ content-order (Y,Y,X,X)
    for item_id, n, at in (
        (x_id, 1, "2026-06-23T00:00:00+00:00"),
        (y_id, 1, "2026-06-20T00:00:00+00:00"),
        (x_id, 2, "2026-06-24T00:00:00+00:00"),
        (y_id, 2, "2026-06-21T00:00:00+00:00"),
    ):
        incoming = dataclasses.replace(
            held[item_id],
            raw_text=f"<raw>A v{n} database capture for {item_id}.</raw>",
            extracted_text=f"A v{n} database capture for {item_id}.",
            content_hash=f"sha256:{item_id}:v{n}",
        )
        adopt_incoming(db, incoming, archived_at=at)
        held[item_id] = incoming
    return db


def _archive_id_order(db):
    """The (item_id, archived_at) of each prior in local `id` order — the per-library
    insertion order, which `export archive` deliberately does *not* key on."""
    import sqlite3

    conn = sqlite3.connect(db)
    try:
        return [
            (row[0], row[1])
            for row in conn.execute(
                "SELECT item_id, archived_at FROM item_archive ORDER BY id"
            ).fetchall()
        ]
    finally:
        conn.close()


def test_export_archive_since_is_byte_stable_across_the_recovery_round_trip(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    """`export archive --since <mid>` reproduces byte-for-byte from an
    `import archive`-rebuilt library — the incremental backup is reproducible, not
    just the full one (H305).

    H280 pins the *whole* `export archive` stream byte-identical across a rebuild:
    the content-determined `(archived_at, item_id, prior_hash)` ordering survives
    the local-`id` reshuffle `import archive` causes. The untested cell is the
    *windowed* (`--since`) stream — the window edge selects a subset, and a naive
    impl that windowed on the per-library `id` rather than `archived_at` would pick
    a *different* subset once the rebuild renumbered the rows. Pin it: seed two
    items whose priors are archived in an order that *differs* from the content
    order (so the rebuild genuinely renumbers), `export archive --since <mid>` from
    A, rebuild a fresh B via `import items` + `import archive`, then re-window B and
    assert the two windowed streams are byte-identical."""
    boundary = "2026-06-21T00:00:00+00:00"
    db_a = _seed_interleaved_archive_cli()
    assert len(archived_records(db_a)) == 4  # four priors across the two items

    capsys.readouterr()
    assert main(["export", "items"]) == 0
    items_path = tmp_path / "library.jsonl"
    items_path.write_text(capsys.readouterr().out, encoding="utf-8")

    # the windowed (incremental) backup from A and the full one for the rebuild
    assert main(["export", "archive", "--since", boundary]) == 0
    window_a = capsys.readouterr().out
    assert main(["export", "archive"]) == 0
    full_a = capsys.readouterr().out
    full_path = tmp_path / "archive-full.jsonl"
    full_path.write_text(full_a, encoding="utf-8")

    # non-vacuous: the window drops the one pre-boundary prior (arxiv:sib@06-20),
    # keeps the other three, and carries multiple rows so line order matters
    assert len(window_a.splitlines()) == 3
    assert len(full_a.splitlines()) == 4
    assert set(window_a.splitlines()).issubset(set(full_a.splitlines()))
    excluded = json.loads(
        next(ln for ln in full_a.splitlines() if ln not in window_a.splitlines())
    )
    assert (excluded["item_id"], excluded["archived_at"]) == (
        "arxiv:sib",
        "2026-06-20T00:00:00+00:00",
    )

    # rebuild a fresh B from the whole-library backup (held rows + every prior); the
    # archive imports in content order, renumbering the local ids relative to A
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()
    assert main(["import", "items", str(items_path)]) == 0
    assert main(["import", "archive", str(full_path)]) == 0
    capsys.readouterr()

    # the reshuffle is real, not assumed: the same priors sit in a *different* local
    # `id` order on B than on A (so a `--since` that keyed on `id` would diverge here)
    assert _archive_id_order(db_a) != _archive_id_order(db_b)
    assert len(archived_records(db_b)) == 4

    # yet the windowed re-export from B is byte-identical to A's — the window selects
    # on archived_at, not the reshuffled local id, so the incremental backup is
    # reproducible across the round trip, not just the full one (H280, windowed)
    assert main(["export", "archive", "--since", boundary]) == 0
    window_b = capsys.readouterr().out
    assert window_b == window_a


# --- a custody-scoped *incremental* backup (`export archive --source S --since T`
# and `--fidelity F --since T`) is byte-stable across the recovery-store round-trip
# — the composition of H305 (the windowed round-trip) and H302 (the custody-scoped
# round-trip): the AND of an item-set sieve and a time window, neither keyed on the
# local id, so the intersection survives the rebuild's reshuffle byte-for-byte (H307)


def _seed_scoped_windowed_archive_cli():
    """Seed a multi-source, multi-prior, mixed-fidelity recovery store whose priors
    straddle a `--since` boundary on *both* a source scope and a fidelity scope, and
    whose archival adoption order differs from the content-determined export order so
    an `import archive` rebuild genuinely renumbers the local `id`s.

    Holdings (priors archived around a 06-22 boundary):

    - ``web:full``   — source web, *full* fidelity, a 3-prior chain v0@06-20,
      v1@06-22, v2@06-24 (held v3): two priors at/after the 06-22 edge, one before.
    - ``web:ref``    — source web, *reference* fidelity (held copy degraded to a
      pointer), one prior r0@06-21 (before the boundary).
    - ``arxiv:full`` — source arxiv, *full* fidelity, one prior a0@06-25 (after).

    So ``--source web --since 06-22`` keeps web:full's {v1@06-22, v2@06-24} (2 of
    web's 4 priors — a strict, non-vacuous subset; the inclusive edge keeps v1), and
    ``--fidelity full --since 06-22`` keeps web:full's two + arxiv:full's a0 (3 of the
    full tier's 4 priors, across two sources, so line order matters). The adoptions
    interleave the items so the per-library `id` order differs from the
    `(archived_at, item_id, prior_hash)` export order. Returns the db_path."""
    main(["init"])
    db = get_paths().db_path

    full = ScrollItem(
        id="web:full", source="web", url="https://web-full.example",
        saved_at="2026-06-11T00:00:00+00:00", title="Held web:full",
        raw_text="<raw>The original database capture.</raw>",
        extracted_text="The original database capture.",
        content_hash="sha256:v0",
        markdown_path="scrolls/web-full.md", stage="rendered",
    )
    arx = ScrollItem(
        id="arxiv:full", source="arxiv", url="https://arxiv-full.example",
        saved_at="2026-06-11T00:00:00+00:00", title="Held arxiv:full",
        raw_text="<raw>The original arxiv capture.</raw>",
        extracted_text="The original arxiv capture.",
        content_hash="sha256:a0",
        markdown_path="scrolls/arxiv-full.md", stage="rendered",
    )
    for held in (full, arx):
        insert_item(db, held)
    insert_item(db, ScrollItem(
        id="web:ref", source="web", url="https://web-ref.example",
        saved_at="2026-06-11T00:00:00+00:00", title="Held (full prior)",
        raw_text="<raw>The original reference capture.</raw>",
        extracted_text="The original reference capture.",
        content_hash="sha256:r0",
        markdown_path="scrolls/web-ref.md", stage="rendered"))

    def _adopt_full(item, n, at):
        incoming = dataclasses.replace(
            item,
            raw_text=f"<raw>A v{n} database capture.</raw>",
            extracted_text=f"A v{n} database capture.",
            content_hash=f"sha256:v{n}",
        )
        adopt_incoming(db, incoming, archived_at=at)
        return incoming

    # interleave the adoptions so id-order ≠ content-order: each item's own chain
    # stays monotonic in archived_at (latest_archived keeps its newest-prior meaning)
    full = _adopt_full(full, 1, "2026-06-20T00:00:00+00:00")  # prior v0@06-20
    full = _adopt_full(full, 2, "2026-06-22T00:00:00+00:00")  # prior v1@06-22
    adopt_incoming(db, ScrollItem(  # web:ref's prior r0@06-21 — a full capture
        id="web:ref", source="web", url="https://web-ref.example",
        saved_at="2026-06-11T00:00:00+00:00", title="Held (reference now)",
        content_hash="sha256:r1", stage="detected"),  # superseded by a pointer-only head
        archived_at="2026-06-21T00:00:00+00:00")
    adopt_incoming(db, dataclasses.replace(  # arxiv:full's prior a0@06-25
        arx,
        raw_text="<raw>A v1 arxiv capture.</raw>",
        extracted_text="A v1 arxiv capture.",
        content_hash="sha256:a1",
    ), archived_at="2026-06-25T00:00:00+00:00")
    _adopt_full(full, 3, "2026-06-24T00:00:00+00:00")  # prior v2@06-24
    return db


def test_scoped_incremental_export_archive_is_byte_stable_across_the_round_trip(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    """A *custody-scoped incremental* backup — `export archive --source S --since T`
    and `--fidelity F --since T` — reproduces byte-for-byte from an `import
    archive`-rebuilt library: the composition of H305 (the windowed round-trip) and
    H302 (the custody-scoped round-trip) (H307).

    H305 pins the `--since` window survives the local-`id` reshuffle a rebuild
    causes; H302 pins the `--source`/`--fidelity` item-set sieve round-trips. The
    untested cell is their **AND** — a backup that is *both* scoped *and* windowed.
    Correct-by-construction: the window selects on `archived_at` and the scope on the
    held row's custody value (resolved through the same `list_items` sieve), neither
    on the local `id`, and `archived_records` orders content-deterministically
    `(archived_at, item_id, prior_hash)`, so the intersection's membership *and* line
    order both survive the reshuffle. Pin it on a multi-source, multi-prior,
    mixed-fidelity seed whose adoption order differs from the export order (so the
    rebuild genuinely renumbers): export each scoped+windowed stream from A, rebuild a
    fresh B, re-export the same stream from B, assert byte-identity — and, separately,
    that the scope-AND-window is a strict, non-vacuous subset of *both* the whole
    store and the un-windowed scope."""
    boundary = "2026-06-22T00:00:00+00:00"  # the inclusive edge sits on web:full's v1
    db_a = _seed_scoped_windowed_archive_cli()
    assert len(archived_records(db_a)) == 5  # the whole recovery store across 3 items

    # back A up: the whole-library held rows + the *whole* recovery store (the rebuild
    # input — a scoped backup would not carry the excluded items' priors B needs)
    capsys.readouterr()
    assert main(["export", "items"]) == 0
    items_path = tmp_path / "library.jsonl"
    items_path.write_text(capsys.readouterr().out, encoding="utf-8")
    assert main(["export", "archive"]) == 0
    full_a = capsys.readouterr().out
    full_path = tmp_path / "archive-full.jsonl"
    full_path.write_text(full_a, encoding="utf-8")

    # the two custody-scoped + windowed (incremental) streams from A, each asserted a
    # strict, non-vacuous subset of *both* the un-windowed scope and the whole store —
    # the AND genuinely narrows on the time axis *and* the custody axis
    scopes = {"source": ["--source", "web"], "fidelity": ["--fidelity", "full"]}
    windowed_a = {}
    for key, scope in scopes.items():
        capsys.readouterr()
        assert main(["export", "archive", *scope]) == 0  # the un-windowed scope
        unwindowed = capsys.readouterr().out
        assert main(["export", "archive", *scope, "--since", boundary]) == 0
        windowed_a[key] = capsys.readouterr().out
        win, un, whole = (
            set(windowed_a[key].splitlines()),
            set(unwindowed.splitlines()),
            set(full_a.splitlines()),
        )
        assert win, f"{key}: the window is non-vacuous"
        assert win < un, f"{key}: a strict subset of the un-windowed scope"
        assert un < whole, f"{key}: the scope is a strict subset of the whole store"

    # the source window keeps web:full's two at/after-boundary priors (the inclusive
    # 06-22 edge is load-bearing — v1@06-22 is kept) and drops the pre-boundary ones
    assert len(windowed_a["source"].splitlines()) == 2
    assert {json.loads(ln)["item_id"] for ln in windowed_a["source"].splitlines()} == {
        "web:full"
    }
    # the fidelity window spans two sources (web:full + arxiv:full), so line order matters
    assert len(windowed_a["fidelity"].splitlines()) == 3
    assert {json.loads(ln)["item_id"] for ln in windowed_a["fidelity"].splitlines()} == {
        "web:full",
        "arxiv:full",
    }

    # rebuild a fresh B from the whole-library backup (held rows + every prior); the
    # archive imports in content order, renumbering the local ids relative to A
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()
    assert main(["import", "items", str(items_path)]) == 0
    assert main(["import", "archive", str(full_path)]) == 0
    capsys.readouterr()

    # the reshuffle is real, not assumed: the priors sit in a *different* local `id`
    # order on B than on A (so a `--since`/scope that keyed on `id` would diverge here)
    assert _archive_id_order(db_a) != _archive_id_order(db_b)
    assert len(archived_records(db_b)) == 5

    # the scoped+windowed re-export from B is byte-identical to A's on *both* axes —
    # the AND of the custody sieve and the time window is reproducible across the round
    # trip, neither leg keyed on the reshuffled local id
    for key, scope in scopes.items():
        capsys.readouterr()
        assert main(["export", "archive", *scope, "--since", boundary]) == 0
        assert capsys.readouterr().out == windowed_a[key], f"{key}: byte-identical on B"


# --- the --since family shares one boundary-normalization contract: `history
# --since` ≡ `export events --since` ≡ `export archive --since` pick *coherent*
# windows from the one `parse_since` validator (inclusive >=) (H304) ----------


def test_since_family_agrees_on_the_window_edge(scrolls_home, capsys):
    """The three time-windowed reads pick the *same* window edge — `history
    --since` (H71), `export events --since` (H75), and `export archive --since`
    (H303) all normalize their boundary through the one `parse_since` validator
    and compare lexicographically `>=` against a stored `+00:00` isoformat stamp
    (`history`/`export events` on `checked_at`, `export archive` on
    `archived_at`). Each was pinned in isolation, but nothing pinned that they
    agree on the *edge*, so a future change to one read's boundary could silently
    drift from the others.

    Pin it on a single item carrying a `checked_at` ledger row *and* an
    `archived_at` prior stamped at the **same** instant T: a `--since T` (the
    exact stamp) includes both the event and the prior on all three reads (the
    boundary is inclusive, `>=` not `>`); a `--since` one second after T excludes
    both, in lockstep. So a maintenance worker using one `--since` value across
    the backup family windows them coherently (the search/list/filter-consistency
    theme on the time axis)."""
    instant = "2026-06-21T12:00:00+00:00"
    one_second_later = "2026-06-21T12:00:01+00:00"
    # one item with a prior archived at T (the recovery-store row) ...
    db, _ = _seed_archived_prior("web:demo", archived_at=instant)
    # ... and a ledger check stamped at the same instant T (the custody-event row)
    record_events(db, [
        CustodyEvent("web:demo", instant, "unchanged", "sha256:new", "sha256:new"),
    ])
    capsys.readouterr()

    def history_checks(boundary):
        assert main(["history", "web:demo", "--since", boundary]) == 0
        return [e["checked_at"] for e in json.loads(capsys.readouterr().out)]

    def exported_events(boundary):
        assert main(["export", "events", "--since", boundary]) == 0
        lines = capsys.readouterr().out.splitlines()
        return [json.loads(line)["checked_at"] for line in lines]

    def archived_priors(boundary):
        assert main(["export", "archive", "--since", boundary]) == 0
        lines = capsys.readouterr().out.splitlines()
        return [json.loads(line)["archived_at"] for line in lines]

    # `--since T` (the exact stamp) — inclusive `>=`: all three keep their T row
    assert history_checks(instant) == [instant]
    assert exported_events(instant) == [instant]
    assert archived_priors(instant) == [instant]

    # a `Z`-suffixed spelling of T normalizes to the same edge (the shared
    # `parse_since` funnel, not a per-command string-shape accident): same result
    assert history_checks("2026-06-21T12:00:00Z") == [instant]
    assert exported_events("2026-06-21T12:00:00Z") == [instant]
    assert archived_priors("2026-06-21T12:00:00Z") == [instant]

    # `--since T+1s` — all three drop the T row together (the edge is shared, so a
    # single boundary value never includes one read's row while excluding another's)
    assert history_checks(one_second_later) == []
    assert exported_events(one_second_later) == []
    assert archived_priors(one_second_later) == []


# --- export events --fidelity / --drift: the custody-filter family on the
# whole-library custody-ledger backup (H260) ---------------------------------


def _seed_events_for_custody_scope():
    """Two held items spanning a fidelity tier *and* a drift posture, each with a
    multi-row ledger; library must already exist.

    `web:full` is full-fidelity (extracted body + hash) and currently *drifted*
    (an `unchanged` recheck then a later `drifted` one); `web:ref` is
    reference-only (just the pointer) and currently *rotted* (a single 404). The
    two-row ledger on `web:full` is what proves `--drift drifted` ships its
    *whole* custody history, not only the matching row. Returns the db path.
    """
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:full", source="web", url="https://ex.com/full",
        saved_at="2026-06-12T00:00:00+00:00", title="Full + drifted",
        extracted_text="A re-derivable body.", content_hash="sha256:a",
        markdown_path="scrolls/web/full.md", stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:ref", source="web", url="https://ex.com/ref",
        saved_at="2026-06-12T00:00:01+00:00", title="Reference + rotted",
        stage="detected"))
    record_events(db, [
        CustodyEvent("web:full", "2026-06-13T00:00:00+00:00", "unchanged", "sha256:a", "sha256:a"),
        CustodyEvent("web:full", "2026-06-15T00:00:00+00:00", "drifted", "sha256:a", "sha256:b"),
        CustodyEvent("web:ref", "2026-06-14T00:00:00+00:00", "rotted", "sha256:a", None, "404"),
    ])
    return db


def test_export_events_fidelity_scopes_to_the_items_custody_history(
    scrolls_home, capsys
):
    # back up only the custody history of items at one fidelity tier — the
    # item-set sieve selects the items `scrolls list --fidelity` enumerates, then
    # their whole ledger travels (ADR 0097, the holdings-axis companion of --drift)
    main(["init"])
    _seed_events_for_custody_scope()
    capsys.readouterr()

    exit_code = main(["export", "events", "--fidelity", "full"])
    assert exit_code == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    # only web:full's ledger (both its rows); the reference item's 404 stays home
    assert {row["item_id"] for row in rows} == {"web:full"}
    assert [row["status"] for row in rows] == ["unchanged", "drifted"]

    main(["export", "events", "--fidelity", "reference"])
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {row["item_id"] for row in rows} == {"web:ref"}
    assert [row["status"] for row in rows] == ["rotted"]


def test_export_events_drift_is_the_item_set_sieve_carrying_the_whole_ledger(
    scrolls_home, capsys
):
    # the crux of the item-set-vs-per-row decision (H260): `--drift drifted`
    # selects the items *currently* drifted, then ships their *whole* ledger — so
    # web:full's earlier `unchanged` row travels too, not just the `drifted` one.
    # This mirrors how `--source` already scopes events by item ("the drifted
    # items' full custody history travels, for a recapture handoff").
    main(["init"])
    _seed_events_for_custody_scope()
    capsys.readouterr()

    exit_code = main(["export", "events", "--drift", "drifted"])
    assert exit_code == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {row["item_id"] for row in rows} == {"web:full"}
    # both rows — including the pre-drift `unchanged` one (NOT a per-row status filter)
    assert [row["status"] for row in rows] == ["unchanged", "drifted"]

    # the rotted item is reachable by its current posture on the same axis
    main(["export", "events", "--drift", "rotted"])
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {row["item_id"] for row in rows} == {"web:ref"}
    assert [row["status"] for row in rows] == ["rotted"]


def test_export_events_custody_axes_and_together(scrolls_home, capsys):
    # both axes AND: --fidelity intersects --drift (and every item facet). The
    # seed's web:full is full+drifted, web:ref is reference+rotted.
    main(["init"])
    _seed_events_for_custody_scope()
    capsys.readouterr()

    # the intersection full *and* drifted is exactly web:full's ledger
    main(["export", "events", "--fidelity", "full", "--drift", "drifted"])
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {row["item_id"] for row in rows} == {"web:full"}

    # an empty intersection (no full-fidelity rotted item) is the honest empty
    # document, never an error — the `export items` precedent
    exit_code = main(["export", "events", "--fidelity", "full", "--drift", "rotted"])
    assert exit_code == 0
    assert capsys.readouterr().out == ""


def test_export_events_custody_scope_composes_with_since(scrolls_home, capsys):
    # window then item-set sieve: --since narrows the event rows, --drift selects
    # the items whose ledger travels — they compose. web:full's 06-13 unchanged is
    # before the window, its 06-15 drifted is at it, so only the latter survives.
    main(["init"])
    _seed_events_for_custody_scope()
    capsys.readouterr()

    exit_code = main([
        "export", "events", "--drift", "drifted", "--since", "2026-06-15T00:00:00+00:00",
    ])
    assert exit_code == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(rows) == 1
    assert rows[0]["item_id"] == "web:full"
    assert rows[0]["status"] == "drifted"


def test_export_events_custody_scoped_backup_round_trips_into_a_fresh_library(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    # the recapture-handoff contract: `import events` of a drift-scoped backup
    # restores exactly the moved items' custody history — no leakage of the
    # filtered-out items' events (the H72 round-trip narrowed to one posture).
    main(["init"])
    _seed_events_for_custody_scope()
    capsys.readouterr()

    main(["export", "events", "--drift", "drifted"])
    out_path = tmp_path / "drifted-ledger.jsonl"
    out_path.write_text(capsys.readouterr().out, encoding="utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "restored"))
    main(["init"])
    capsys.readouterr()
    assert main(["import", "events", str(out_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"imported": 2, "skipped": 0, "events": 2}

    from scrolls.custody import item_events
    db = get_paths().db_path
    # web:full's whole ledger restored, newest-first; web:ref's 404 never travelled
    assert [e.status for e in item_events(db, "web:full")] == ["drifted", "unchanged"]
    assert item_events(db, "web:ref") == []


def test_export_events_rejects_an_unknown_fidelity_tier(scrolls_home):
    # fidelity tiers are a closed vocabulary; a typo is exit 2, never a silent
    # empty backup (the `list --fidelity` / `export items` precedent)
    with pytest.raises(SystemExit) as excinfo:
        main(["export", "events", "--fidelity", "ful"])
    assert excinfo.value.code == 2


def test_export_events_rejects_an_unknown_drift_posture(scrolls_home):
    # drift postures are a closed vocabulary; a typo is exit 2, never a silent empty
    with pytest.raises(SystemExit) as excinfo:
        main(["export", "events", "--drift", "drited"])
    assert excinfo.value.code == 2


def test_cmd_export_events_unknown_tier_on_the_programmatic_path_is_exit_1(
    scrolls_home, capsys
):
    # belt-and-braces below argparse: a direct call past `choices` surfaces the
    # `list_items` ValueError as a JSON error on stderr, exit 1 (the
    # `_cmd_export_items` precedent), never a stdout backup
    from scrolls.cli import _cmd_export_events

    main(["init"])
    _seed_events_for_custody_scope()
    capsys.readouterr()

    exit_code = _cmd_export_events(None, None, None, None, "bogus-tier", None)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


# --- export events --content-duplicate: the content-identity item-set sieve on
# the verify-ledger backup (H347), the content-identity sibling of `export events
# --fidelity`/`--drift` (H260) and the ledger counterpart of `export items
# --content-duplicate` (H341). `list_items` already applies the whole-library
# sibling sieve (H338); the *whole ledger* of each selected item travels, so a
# recipient deduping the redundant copies gets the full proof of when each was
# verified. ----------------------------------------------------------------------


def _seed_events_for_content_duplicate_scope():
    """A cross-source byte-identical pair (each with a custody ledger) + a unique
    held item with its own ledger; inits the library and returns its db path.

    `web:a` (web) and `arxiv:1` (arxiv) end *held* at `content_hash=sha256:dup` — a
    mirror captured by two adapters, a *cross-source* content group, so the sibling
    scope is genuinely whole-library. `web:solo` holds unique bytes. web:a carries a
    two-row ledger (an `unchanged` then a `drifted`), so `--content-duplicate`
    shipping its *whole* ledger (not just one matching row) is observable; the drift
    event records a divergence but never overwrites the held `content_hash` column
    (custody §2.1), so the pair still groups byte-identical."""
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:a", source="web", url="https://e.com/a",
        saved_at="2026-06-12T00:00:00+00:00", title="alpha copy",
        extracted_text="body", raw_text="<r>body</r>",
        content_hash="sha256:dup", stage="rendered"))
    insert_item(db, ScrollItem(
        id="arxiv:1", source="arxiv", url="https://arxiv.org/abs/1",
        saved_at="2026-06-12T01:00:00+00:00", title="alpha mirror",
        extracted_text="body", raw_text="<r>body</r>",
        content_hash="sha256:dup", stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:solo", source="web", url="https://e.com/solo",
        saved_at="2026-06-12T02:00:00+00:00", title="alpha solo",
        extracted_text="x", raw_text="<r>x</r>",
        content_hash="sha256:solo", stage="rendered"))
    record_events(db, [
        CustodyEvent("web:a", "2026-06-13T00:00:00+00:00", "unchanged",
                     "sha256:dup", "sha256:dup"),
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "drifted",
                     "sha256:dup", "sha256:moved"),
        CustodyEvent("arxiv:1", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:dup", "sha256:dup"),
        CustodyEvent("web:solo", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:solo", "sha256:solo"),
    ])
    return db


def test_export_events_content_duplicate_ships_the_siblings_whole_ledger(
    scrolls_home, capsys
):
    # `--content-duplicate` selects the items the library holds a byte-identical
    # copy of under another id (the H338 sibling sieve), then ships their *whole*
    # ledger — web:a's pre-drift `unchanged` row travels with its `drifted` one (the
    # item-set-vs-per-row decision, the H260 shape) — and drops web:solo's ledger.
    # The kept ids equal doctor's content-duplicate group members.
    main(["init"])
    _seed_events_for_content_duplicate_scope()
    capsys.readouterr()

    assert main(["export", "events", "--content-duplicate"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {row["item_id"] for row in rows} == {"web:a", "arxiv:1"}  # web:solo dropped
    # web:a's whole two-row ledger travelled, not just the drifted row
    web_a = [row["status"] for row in rows if row["item_id"] == "web:a"]
    assert web_a == ["unchanged", "drifted"]

    main(["doctor"])
    groups = json.loads(capsys.readouterr().out)["custody"]["content_duplicates"]["groups"]
    members = {item_id for group in groups for item_id in group["ids"]}
    assert {row["item_id"] for row in rows} == members


def test_export_events_content_duplicate_is_whole_library_scope_under_source(
    scrolls_home, capsys
):
    # the sibling scope is whole-library (a content group spans sources, the H328
    # rule), so `--source web` still ships web:a whose only sibling (arxiv:1) lives
    # in another source; arxiv:1 falls out of source scope, web:solo has no sibling.
    main(["init"])
    _seed_events_for_content_duplicate_scope()
    capsys.readouterr()

    assert main(["export", "events", "--content-duplicate", "--source", "web"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {row["item_id"] for row in rows} == {"web:a"}  # arxiv:1 out of source scope

    # composes with --since (window the rows) and ANDs with --drift (select the
    # item): only web:a's drifted row at/after the boundary survives
    assert main([
        "export", "events", "--content-duplicate", "--drift", "drifted",
        "--since", "2026-06-15T00:00:00+00:00",
    ]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(rows) == 1
    assert rows[0]["item_id"] == "web:a"
    assert rows[0]["status"] == "drifted"


def test_export_events_content_duplicate_round_trips_into_a_fresh_library(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    # the dedup-handoff contract: `import events` of a content-duplicate-scoped
    # backup restores exactly the redundant items' custody history — no leakage of
    # the unique item's events (the H72 round-trip narrowed to the content-identity
    # shape, the H260 drift-scoped precedent).
    main(["init"])
    _seed_events_for_content_duplicate_scope()
    capsys.readouterr()

    main(["export", "events", "--content-duplicate"])
    out_path = tmp_path / "dups-ledger.jsonl"
    out_path.write_text(capsys.readouterr().out, encoding="utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "restored"))
    main(["init"])
    capsys.readouterr()
    assert main(["import", "events", str(out_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"imported": 3, "skipped": 0, "events": 3}

    from scrolls.custody import item_events
    db = get_paths().db_path
    # the pair's whole ledgers restored (newest-first); web:solo's event never travelled
    assert [e.status for e in item_events(db, "web:a")] == ["drifted", "unchanged"]
    assert [e.status for e in item_events(db, "arxiv:1")] == ["unchanged"]
    assert item_events(db, "web:solo") == []


def test_list_after_adds_prints_summaries(scrolls_home, capsys):
    main(["add", "https://youtu.be/dQw4w9WgXcQ"])
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    exit_code = main(["list"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert {entry["id"] for entry in payload} == {"youtube:dQw4w9WgXcQ", "wikipedia:en:SQLite"}
    for entry in payload:
        assert entry["stage"] == "detected"
        assert entry["fidelity"] == "reference"  # detected, no content held yet
        assert entry["drift"] == "unverified"  # never re-checked (H58)
        assert entry["last_checked"] is None  # …so no timestamp to report (H84)
        assert entry["works"] == []  # neither is a saved form of a shared work
        assert set(entry) == {
            "id", "source", "url", "title", "category", "stage", "saved_at",
            "fidelity", "drift", "last_checked", "works",
        }


def test_list_filters_by_source_stage_and_category(scrolls_home, capsys):
    main(["add", "https://youtu.be/dQw4w9WgXcQ"])
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["set", "wikipedia:en:SQLite", "category=reference"])
    capsys.readouterr()

    main(["list", "--source", "wikipedia"])
    payload = json.loads(capsys.readouterr().out)
    assert [entry["id"] for entry in payload] == ["wikipedia:en:SQLite"]

    main(["list", "--category", "reference"])
    payload = json.loads(capsys.readouterr().out)
    assert [entry["id"] for entry in payload] == ["wikipedia:en:SQLite"]
    assert payload[0]["category"] == "reference"

    # the empty value selects unclassified items, mirroring `scrolls set`'s
    # empty-clears convention
    main(["list", "--category", ""])
    payload = json.loads(capsys.readouterr().out)
    assert [entry["id"] for entry in payload] == ["youtube:dQw4w9WgXcQ"]

    main(["list", "--stage", "detected", "--source", "youtube"])
    payload = json.loads(capsys.readouterr().out)
    assert [entry["id"] for entry in payload] == ["youtube:dQw4w9WgXcQ"]

    main(["list", "--stage", "rendered"])
    assert json.loads(capsys.readouterr().out) == []


def test_list_rejects_an_unknown_stage(scrolls_home):
    # stages are a closed vocabulary; a typo should not silently match nothing
    with pytest.raises(SystemExit) as excinfo:
        main(["list", "--stage", "rendred"])
    assert excinfo.value.code == 2


def _seed_drift_postures():
    """Three held items in distinct drift postures; library must already exist.

    `web:0` verified (re-checked unchanged), `web:1` drifted (source changed),
    `web:2` unverified (never re-checked). Returns the db path.
    """
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    db = get_paths().db_path
    for index in range(3):
        insert_item(db, ScrollItem(
            id=f"web:{index}", source="web", url=f"https://ex.com/{index}",
            saved_at="2026-06-12T00:00:00+00:00", title=f"Post {index}",
            stage="fetched"))
    record_events(db, [
        CustodyEvent("web:0", "2026-06-14T00:00:00+00:00", "unchanged", "h", "h", None),
        CustodyEvent("web:1", "2026-06-14T00:00:00+00:00", "drifted", "h", "x", None),
        # web:2 left unverified
    ])
    return db


def test_list_drift_selects_items_by_custody_posture(scrolls_home, capsys):
    # the read-side companion of `facets drift`: enumerate the items in a posture
    main(["init"])
    _seed_drift_postures()
    capsys.readouterr()

    main(["list", "--drift", "drifted"])
    assert [r["id"] for r in json.loads(capsys.readouterr().out)] == ["web:1"]

    main(["list", "--drift", "verified"])
    assert [r["id"] for r in json.loads(capsys.readouterr().out)] == ["web:0"]

    main(["list", "--drift", "unverified"])
    assert [r["id"] for r in json.loads(capsys.readouterr().out)] == ["web:2"]


def test_list_drift_rows_total_the_facets_drift_count(scrolls_home, capsys):
    # drill-from-the-count convergence: the rows `--drift X` returns total the
    # `facets drift` count for X, over the same scope (H54)
    main(["init"])
    _seed_drift_postures()
    capsys.readouterr()

    main(["facets", "drift"])
    counts = {
        e["value"]: e["count"]
        for e in json.loads(capsys.readouterr().out)["facets"]["drift"]
    }
    for posture, count in counts.items():
        main(["list", "--drift", posture])
        rows = json.loads(capsys.readouterr().out)
        assert len(rows) == count, f"{posture}: {len(rows)} rows != facet count {count}"


def test_list_drift_is_honestly_empty_for_a_posture_with_no_items(scrolls_home, capsys):
    # a valid posture nothing is in is [], never an error (completeness G1)
    main(["init"])
    _seed_drift_postures()
    capsys.readouterr()

    main(["list", "--drift", "rotted"])
    assert json.loads(capsys.readouterr().out) == []


def test_list_drift_is_echoed_in_the_stats_scope(scrolls_home, capsys):
    # the --stats envelope names the drift filter it honored, and matched is the
    # post-drift count (so it equals the facet count, not the library total)
    main(["init"])
    _seed_drift_postures()
    capsys.readouterr()

    main(["list", "--drift", "unverified", "--stats"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"]["drift"] == "unverified"
    assert payload["stats"]["matched"] == 1
    assert [r["id"] for r in payload["results"]] == ["web:2"]


def test_list_rejects_an_unknown_drift_posture(scrolls_home):
    # drift postures are a closed vocabulary; a typo should not silently match nothing
    with pytest.raises(SystemExit) as excinfo:
        main(["list", "--drift", "drited"])
    assert excinfo.value.code == 2


def _seed_fidelity_tiers():
    """Four held items spanning the custody-fidelity tiers; library must exist.

    Two `full` (a re-derivable body held at a captured stage — one via raw, one
    via extracted+hash), one `partial` (extracted content but no hash to
    re-derive against), one `reference` (only the pointer is held). The holdings
    -axis twin of `_seed_drift_postures`. Returns the db path.
    """
    from scrolls.items import ScrollItem, insert_item

    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:full0", source="web", url="https://ex.com/full0",
        saved_at="2026-06-12T00:00:00+00:00", title="Full 0",
        extracted_text="A re-derivable body.", content_hash="sha256:a",
        stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:full1", source="web", url="https://ex.com/full1",
        saved_at="2026-06-12T00:00:01+00:00", title="Full 1",
        raw_text="Raw held in full.", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:partial", source="web", url="https://ex.com/partial",
        saved_at="2026-06-12T00:00:02+00:00", title="Partial",
        extracted_text="Content held, but no hash to re-derive against.",
        stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:reference", source="web", url="https://ex.com/reference",
        saved_at="2026-06-12T00:00:03+00:00", title="Reference",
        stage="detected"))
    return db


def test_list_fidelity_selects_items_by_custody_tier(scrolls_home, capsys):
    # the holdings-axis companion of `--drift`: enumerate the items held at one
    # custody-fidelity tier — the read-side of `facets fidelity` (ADR 0097)
    main(["init"])
    _seed_fidelity_tiers()
    capsys.readouterr()

    main(["list", "--fidelity", "full"])
    assert [r["id"] for r in json.loads(capsys.readouterr().out)] == [
        "web:full0", "web:full1"
    ]

    main(["list", "--fidelity", "partial"])
    assert [r["id"] for r in json.loads(capsys.readouterr().out)] == ["web:partial"]

    main(["list", "--fidelity", "reference"])
    assert [r["id"] for r in json.loads(capsys.readouterr().out)] == ["web:reference"]


def test_list_fidelity_rows_total_the_facets_fidelity_count(scrolls_home, capsys):
    # drill-from-the-count convergence: the rows `--fidelity X` returns total the
    # `facets fidelity` count for X over the same scope — the holdings-axis twin
    # of `--drift` ↔ `facets drift`. Both fold the one `fidelity_tier` primitive.
    main(["init"])
    _seed_fidelity_tiers()
    capsys.readouterr()

    main(["facets", "fidelity"])
    counts = {
        e["value"]: e["count"]
        for e in json.loads(capsys.readouterr().out)["facets"]["fidelity"]
    }
    assert counts  # non-vacuous: the seed produced tiered holdings
    for tier, count in counts.items():
        main(["list", "--fidelity", tier])
        rows = json.loads(capsys.readouterr().out)
        assert len(rows) == count, f"{tier}: {len(rows)} rows != facet count {count}"


def test_list_fidelity_is_honestly_empty_for_a_tier_with_no_items(scrolls_home, capsys):
    # a valid tier nothing is held at is [], never an error (completeness G1)
    main(["init"])
    from scrolls.items import ScrollItem, insert_item

    insert_item(get_paths().db_path, ScrollItem(
        id="web:0", source="web", url="https://ex.com/0",
        saved_at="2026-06-12T00:00:00+00:00", title="Full",
        raw_text="held in full", stage="fetched"))
    capsys.readouterr()

    main(["list", "--fidelity", "reference"])
    assert json.loads(capsys.readouterr().out) == []


def test_list_fidelity_is_echoed_in_the_stats_scope(scrolls_home, capsys):
    # the --stats envelope names the fidelity filter it honored, and matched is
    # the post-filter count (so it equals the facet count, not the library total)
    main(["init"])
    _seed_fidelity_tiers()
    capsys.readouterr()

    main(["list", "--fidelity", "full", "--stats"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"]["fidelity"] == "full"
    assert payload["stats"]["matched"] == 2
    assert [r["id"] for r in payload["results"]] == ["web:full0", "web:full1"]


def test_list_fidelity_composes_with_another_facet(scrolls_home, capsys):
    # AND semantics: --fidelity intersects with --source (and every other facet),
    # filtering the already-filtered set rather than the whole library
    main(["init"])
    _seed_fidelity_tiers()
    from scrolls.items import ScrollItem, insert_item

    insert_item(get_paths().db_path, ScrollItem(
        id="arxiv:1", source="arxiv", url="https://arxiv.org/abs/1",
        saved_at="2026-06-12T00:00:04+00:00", title="Arxiv full",
        raw_text="held in full", stage="fetched"))
    capsys.readouterr()

    main(["list", "--fidelity", "full", "--source", "web"])
    assert [r["id"] for r in json.loads(capsys.readouterr().out)] == [
        "web:full0", "web:full1"
    ]

    main(["list", "--fidelity", "full", "--source", "arxiv"])
    assert [r["id"] for r in json.loads(capsys.readouterr().out)] == ["arxiv:1"]


def test_list_row_fidelity_matches_the_fidelity_filter_value(scrolls_home, capsys):
    # the tier a row *shows* (its `fidelity` field) is exactly the tier it would
    # be *selected* by — `list --fidelity X` returns precisely the rows whose
    # shown `fidelity` is X. The filter and the field can never disagree.
    main(["init"])
    _seed_fidelity_tiers()
    capsys.readouterr()

    for tier in ("full", "partial", "reference"):
        main(["list", "--fidelity", tier])
        rows = json.loads(capsys.readouterr().out)
        assert rows  # each tier is populated by the seed
        assert all(r["fidelity"] == tier for r in rows)


def test_list_rejects_an_unknown_fidelity_tier(scrolls_home):
    # fidelity tiers are a closed vocabulary; a typo should not silently match nothing
    with pytest.raises(SystemExit) as excinfo:
        main(["list", "--fidelity", "ful"])
    assert excinfo.value.code == 2


# --- search --fidelity: the holdings-axis filter on the *ranked* surface (H251) ---


def _seed_fidelity_search():
    """Matches for "database" spanning the fidelity tiers, every title shares the
    token so one query reaches all of them. Two `full`, one `partial`, one
    `reference` — the search twin of `_seed_fidelity_tiers`. Library must exist.
    """
    from scrolls.items import ScrollItem, insert_item

    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:full0", source="web", url="https://ex.com/full0",
        saved_at="2026-06-12T00:00:00+00:00", title="Full database alpha",
        raw_text="A database engine held in full.", content_hash="sha256:a",
        stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:full1", source="web", url="https://ex.com/full1",
        saved_at="2026-06-12T00:00:01+00:00", title="Full database beta",
        raw_text="Another database engine held in full.", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:partial", source="web", url="https://ex.com/partial",
        saved_at="2026-06-12T00:00:02+00:00", title="Partial database",
        extracted_text="A database, content held but no hash.", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:reference", source="web", url="https://ex.com/reference",
        saved_at="2026-06-12T00:00:03+00:00", title="Reference database",
        stage="detected"))
    return db


def test_search_fidelity_selects_hits_by_custody_tier(scrolls_home, capsys):
    # the holdings-axis filter on the ranked surface: only the matches the library
    # holds at the named tier, the search twin of `list --fidelity` (ADR 0097)
    main(["init"])
    _seed_fidelity_search()
    capsys.readouterr()

    main(["search", "database", "--fidelity", "full"])
    assert {h["id"] for h in json.loads(capsys.readouterr().out)} == {
        "web:full0", "web:full1"
    }

    main(["search", "database", "--fidelity", "partial"])
    assert [h["id"] for h in json.loads(capsys.readouterr().out)] == ["web:partial"]

    main(["search", "database", "--fidelity", "reference"])
    assert [h["id"] for h in json.loads(capsys.readouterr().out)] == ["web:reference"]


def test_search_fidelity_hits_match_the_filter_value(scrolls_home, capsys):
    # every returned hit shows exactly the tier it was selected by — the filter
    # and the per-hit `fidelity` field can never disagree (the row-shows-≡-filter
    # guarantee, the search twin of `test_list_row_fidelity_matches_...`)
    main(["init"])
    _seed_fidelity_search()
    capsys.readouterr()

    for tier in ("full", "partial", "reference"):
        main(["search", "database", "--fidelity", tier])
        hits = json.loads(capsys.readouterr().out)
        assert hits  # each tier is populated by the seed
        assert all(h["fidelity"] == tier for h in hits)


def test_search_fidelity_scope_echo_and_truncation_denominator(scrolls_home, capsys):
    # the --stats envelope names the fidelity filter it honored, and the matched
    # denominator counts only that tier — so a capped `--fidelity full` result is
    # truncated by *full* matches it hid, never by partials it never showed (G2).
    main(["init"])
    _seed_fidelity_search()
    capsys.readouterr()

    main(["search", "database", "--fidelity", "full", "--limit", "1", "--stats"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"]["fidelity"] == "full"
    # two full matches, capped at 1 → truncated, denominator is the full count (2),
    # not the library-wide match count (4)
    assert payload["stats"]["returned"] == 1
    assert payload["stats"]["matched"] == 2
    assert payload["stats"]["truncated"] is True


def test_search_fidelity_composes_with_source(scrolls_home, capsys):
    # AND semantics: --fidelity intersects with --source like every other facet
    main(["init"])
    _seed_fidelity_search()
    from scrolls.items import ScrollItem, insert_item

    insert_item(get_paths().db_path, ScrollItem(
        id="arxiv:1", source="arxiv", url="https://arxiv.org/abs/1",
        saved_at="2026-06-12T00:00:04+00:00", title="Arxiv database full",
        raw_text="A database paper held in full.", stage="rendered"))
    capsys.readouterr()

    main(["search", "database", "--fidelity", "full", "--source", "arxiv"])
    assert [h["id"] for h in json.loads(capsys.readouterr().out)] == ["arxiv:1"]

    main(["search", "database", "--fidelity", "full", "--source", "web"])
    assert {h["id"] for h in json.loads(capsys.readouterr().out)} == {
        "web:full0", "web:full1"
    }


def test_search_rejects_an_unknown_fidelity_tier(scrolls_home):
    # the same closed vocabulary as `list --fidelity`; a typo is an exit-2 error
    with pytest.raises(SystemExit) as excinfo:
        main(["search", "database", "--fidelity", "ful"])
    assert excinfo.value.code == 2


# --- search --drift: the ledger-claim-axis filter on the *ranked* surface (H253) ---


def _seed_drift_search():
    """Matches for "database" spanning drift postures, every title sharing the
    token so one query reaches all of them. Two `verified`, one `drifted`, one
    `unverified` — the search/ledger twin of `_seed_fidelity_search`. Library
    must exist.
    """
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    db = get_paths().db_path
    for ident in ("verified0", "verified1", "drifted", "never"):
        insert_item(db, ScrollItem(
            id=f"web:{ident}", source="web", url=f"https://ex.com/{ident}",
            saved_at="2026-06-12T00:00:00+00:00",
            title=f"{ident.capitalize()} database engine",
            raw_text="A database engine.", content_hash=f"sha256:{ident}",
            stage="rendered"))
    record_events(db, [
        CustodyEvent("web:verified0", "t", "unchanged", "h", "h", None),
        CustodyEvent("web:verified1", "t", "unchanged", "h", "h", None),
        CustodyEvent("web:drifted", "t", "drifted", "h", "x", None),
        # web:never left with no verdict -> unverified
    ])
    return db


def test_search_drift_selects_hits_by_custody_posture(scrolls_home, capsys):
    # the ledger-claim-axis filter on the ranked surface: only the matches whose
    # latest verify verdict reads at the named posture, the search twin of
    # `list --drift` (H58)
    main(["init"])
    _seed_drift_search()
    capsys.readouterr()

    main(["search", "database", "--drift", "verified"])
    assert {h["id"] for h in json.loads(capsys.readouterr().out)} == {
        "web:verified0", "web:verified1"
    }

    main(["search", "database", "--drift", "drifted"])
    assert [h["id"] for h in json.loads(capsys.readouterr().out)] == ["web:drifted"]

    main(["search", "database", "--drift", "unverified"])
    assert [h["id"] for h in json.loads(capsys.readouterr().out)] == ["web:never"]


def test_search_drift_hits_match_the_filter_value(scrolls_home, capsys):
    # every returned hit shows exactly the posture it was selected by — the filter
    # and the per-hit `drift` field can never disagree (both via
    # posture_from_status), the ledger-axis twin of the fidelity row-≡-filter
    main(["init"])
    _seed_drift_search()
    capsys.readouterr()

    for posture in ("verified", "drifted", "unverified"):
        main(["search", "database", "--drift", posture])
        hits = json.loads(capsys.readouterr().out)
        assert hits  # each posture is populated by the seed
        assert all(h["drift"] == posture for h in hits)


def test_search_drift_scope_echo_and_truncation_denominator(scrolls_home, capsys):
    # the --stats envelope names the drift filter it honored, and the matched
    # denominator counts only that posture — so a capped `--drift verified` result
    # is truncated by *verified* matches it hid, never by other postures (G2)
    main(["init"])
    _seed_drift_search()
    capsys.readouterr()

    main(["search", "database", "--drift", "verified", "--limit", "1", "--stats"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"]["drift"] == "verified"
    # two verified matches, capped at 1 → truncated, denominator is the verified
    # count (2), not the library-wide match count (4)
    assert payload["stats"]["returned"] == 1
    assert payload["stats"]["matched"] == 2
    assert payload["stats"]["truncated"] is True


def test_search_drift_composes_with_source(scrolls_home, capsys):
    # AND semantics: --drift intersects with --source like every other facet
    main(["init"])
    _seed_drift_search()
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="arxiv:1", source="arxiv", url="https://arxiv.org/abs/1",
        saved_at="2026-06-12T00:00:04+00:00", title="Arxiv database drifted",
        raw_text="A database paper.", content_hash="sha256:x", stage="rendered"))
    record_events(db, [CustodyEvent("arxiv:1", "t", "drifted", "h", "y", None)])
    capsys.readouterr()

    main(["search", "database", "--drift", "drifted", "--source", "arxiv"])
    assert [h["id"] for h in json.loads(capsys.readouterr().out)] == ["arxiv:1"]

    main(["search", "database", "--drift", "drifted", "--source", "web"])
    assert [h["id"] for h in json.loads(capsys.readouterr().out)] == ["web:drifted"]


def test_search_drift_composes_with_fidelity(scrolls_home, capsys):
    # the two custody axes AND independently on the ranked surface: holdings
    # (--fidelity) and ledger (--drift) scope the same match together
    main(["init"])
    _seed_drift_search()
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    db = get_paths().db_path
    # a partial (no hash) drifted match — excluded by --fidelity full
    insert_item(db, ScrollItem(
        id="web:partialdrift", source="web", url="https://ex.com/pd",
        saved_at="2026-06-12T00:00:05+00:00", title="Partial drifted database",
        extracted_text="A database, no hash.", stage="fetched"))
    record_events(db, [CustodyEvent("web:partialdrift", "t", "drifted", None, "x", None)])
    capsys.readouterr()

    main(["search", "database", "--fidelity", "full", "--drift", "drifted"])
    assert [h["id"] for h in json.loads(capsys.readouterr().out)] == ["web:drifted"]


def test_search_rejects_an_unknown_drift_posture(scrolls_home):
    # the same closed vocabulary as `list --drift`; a typo is an exit-2 error
    with pytest.raises(SystemExit) as excinfo:
        main(["search", "database", "--drift", "drift"])
    assert excinfo.value.code == 2


def test_list_rows_carry_the_drift_posture(scrolls_home, capsys):
    # H58: every browse row shows the second custody axis — the drift posture —
    # not just `fidelity`, so a plain `list` reads the same posture `--drift`
    # filters on (the filter no longer being the only place the posture appears)
    main(["init"])
    _seed_drift_postures()
    capsys.readouterr()

    main(["list"])
    rows = {r["id"]: r for r in json.loads(capsys.readouterr().out)}
    assert rows["web:0"]["drift"] == "verified"  # re-checked unchanged
    assert rows["web:1"]["drift"] == "drifted"  # source changed
    assert rows["web:2"]["drift"] == "unverified"  # never re-checked


def test_list_row_drift_matches_the_drift_filter_value(scrolls_home, capsys):
    # H58: the posture a row *shows* is exactly the posture it would be
    # *selected* by — `list --drift X` returns precisely the rows whose shown
    # `drift` is X. The filter (H54) and the field (H58) can never disagree.
    main(["init"])
    _seed_drift_postures()
    capsys.readouterr()

    main(["list"])
    all_rows = json.loads(capsys.readouterr().out)
    for row in all_rows:
        main(["list", "--drift", row["drift"]])
        selected = {r["id"] for r in json.loads(capsys.readouterr().out)}
        assert row["id"] in selected, f"{row['id']} shows {row['drift']} but isn't selected by it"


def _seed_staleness():
    """Three held, hash-bearing scrolls partitioned by a staleness boundary.

    `web:old` last checked 2026-06-10 (stale before 2026-06-12), `web:new` last
    checked 2026-06-14 (fresh after it), `web:never` never re-checked (trivially
    stale at any boundary). The browse-side companion of `test_verify_cli`'s
    stale-before fixtures.
    """
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    db = get_paths().db_path
    for name in ("old", "new", "never"):
        insert_item(db, ScrollItem(
            id=f"web:{name}", source="web", url=f"https://ex.com/{name}",
            saved_at="2026-06-12T00:00:00+00:00", title=f"Post {name}",
            extracted_text="body", content_hash=f"sha256:{name}", stage="fetched"))
    record_events(db, [
        CustodyEvent("web:old", "2026-06-10T00:00:00+00:00", "unchanged", "h", "h", None),
        CustodyEvent("web:new", "2026-06-14T00:00:00+00:00", "unchanged", "h", "h", None),
        # web:never left unverified
    ])
    return db


def test_list_stale_before_selects_the_stale_set(scrolls_home, capsys):
    # H85: enumerate the held items whose newest verdict predates the boundary —
    # the stale set. A never-checked item is trivially stale (included); an item
    # checked exactly at the boundary is fresh (the exclusive `< boundary`).
    main(["init"])
    _seed_staleness()
    capsys.readouterr()

    main(["list", "--stale-before", "2026-06-12T00:00:00+00:00"])
    assert {r["id"] for r in json.loads(capsys.readouterr().out)} == {"web:old", "web:never"}

    # boundary is exclusive: web:new checked exactly at 2026-06-14 is fresh
    main(["list", "--stale-before", "2026-06-14T00:00:00+00:00"])
    assert {r["id"] for r in json.loads(capsys.readouterr().out)} == {"web:old", "web:never"}

    # a date-only boundary normalizes to that day's midnight UTC (parse_since)
    main(["list", "--stale-before", "2026-06-09"])
    assert {r["id"] for r in json.loads(capsys.readouterr().out)} == {"web:never"}


def test_list_stale_before_composes_with_facets_and_stats(scrolls_home, capsys):
    # the time window ANDs with the stored facets (window then scope), and under
    # --stats `matched` is the post-filter count (the `--drift` precedent)
    main(["init"])
    _seed_staleness()
    from scrolls.items import ScrollItem, insert_item
    insert_item(get_paths().db_path, ScrollItem(
        id="arxiv:1", source="arxiv", url="https://arxiv.org/abs/1",
        saved_at="2026-06-12T00:00:00+00:00", title="An old arxiv paper",
        extracted_text="body", content_hash="sha256:ax", stage="fetched"))
    capsys.readouterr()

    # arxiv:1 is never-checked (stale) but excluded by --source web
    main(["list", "--stale-before", "2026-06-12T00:00:00+00:00", "--source", "web", "--stats"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"]["stale_before"] == "2026-06-12T00:00:00+00:00"
    assert payload["scope"]["source"] == "web"
    assert payload["stats"]["matched"] == 2  # web:old + web:never, not arxiv:1
    assert {r["id"] for r in payload["results"]} == {"web:old", "web:never"}


def test_list_stale_before_composes_with_drift(scrolls_home, capsys):
    # both ledger-derived filters AND over one read: stale AND at a given posture
    main(["init"])
    _seed_staleness()
    capsys.readouterr()

    # web:old (verified, stale) and web:never (unverified, stale): filter to the
    # stale set then to the `verified` posture → just web:old
    main(["list", "--stale-before", "2026-06-12T00:00:00+00:00", "--drift", "verified"])
    assert {r["id"] for r in json.loads(capsys.readouterr().out)} == {"web:old"}


def test_list_stale_before_rejects_a_malformed_boundary(scrolls_home, capsys):
    # a malformed boundary is a loud usage error (exit 2), validated before the
    # store read — never a silently-empty listing (the `--since` family precedent)
    main(["init"])
    capsys.readouterr()
    assert main(["list", "--stale-before", "not-a-date"]) == 2
    assert "error" in json.loads(capsys.readouterr().err)


def test_list_stale_before_malformed_beats_a_missing_store(scrolls_home, capsys):
    # validated before the db-existence check, so a typo'd boundary is exit 2 even
    # before `init` — a usage error, not a checked-and-empty `[]`
    assert main(["list", "--stale-before", "not-a-date"]) == 2
    assert "error" in json.loads(capsys.readouterr().err)


def test_list_stale_classification_selects_the_stale_enrichment_set(scrolls_home, capsys):
    # H185: enumerate the items whose rules-classified category the live ruleset
    # would no longer reproduce — the read-side companion of `classify --stale`.
    # The `_seed_refresh_debt` fixture marks arxiv:1 + web:2 stale (3 total).
    paths = get_paths()
    _seed_refresh_debt(paths)
    capsys.readouterr()

    main(["list", "--stale-classification"])
    stale = json.loads(capsys.readouterr().out)
    stale_ids = {r["id"] for r in stale}

    # exactly the items `classify.stale_classifications` selects over the library
    expected = {item.id for item in stale_classifications(list_items(paths.db_path))}
    assert stale_ids == expected
    assert len(stale) == 3  # arxiv:1 + web:2


def test_list_stale_classification_rows_total_the_doctor_aggregate(scrolls_home, capsys):
    # drill-from-the-count convergence (H185): the rows `--stale-classification`
    # returns total `doctor`'s custody.enrichment.stale, and the `--source`
    # narrowing totals its enrichment.by_source[S].
    paths = get_paths()
    _seed_refresh_debt(paths)
    capsys.readouterr()
    report = run_doctor(paths)
    enrichment = report["custody"]["enrichment"]

    main(["list", "--stale-classification"])
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == enrichment["stale"]  # whole-library tie

    for source, count in enrichment["by_source"].items():
        main(["list", "--stale-classification", "--source", source])
        scoped = json.loads(capsys.readouterr().out)
        assert len(scoped) == count, f"{source}: {len(scoped)} != aggregate {count}"
        assert all(r["source"] == source for r in scoped)


def test_list_stale_classification_ands_with_other_facets(scrolls_home, capsys):
    # the filter composes with the stored facets (AND): web has 2 stale, arxiv 1
    paths = get_paths()
    _seed_refresh_debt(paths)
    capsys.readouterr()

    main(["list", "--stale-classification", "--source", "web"])
    assert len({r["id"] for r in json.loads(capsys.readouterr().out)}) == 2

    main(["list", "--stale-classification", "--source", "arxiv"])
    arxiv = json.loads(capsys.readouterr().out)
    assert len(arxiv) == 1 and arxiv[0]["source"] == "arxiv"


def test_list_stale_classification_is_honestly_empty_when_nothing_stale(scrolls_home, capsys):
    # a library with no stale classifications is [], never an error (completeness G1)
    main(["init"])
    insert_item(get_paths().db_path, ScrollItem(
        id="web:fresh", source="web", url="https://ex.com/fresh",
        saved_at="2026-06-12T00:00:00+00:00", title="A fresh post",
        extracted_text="body", content_hash="sha256:fresh", stage="fetched"))
    capsys.readouterr()

    main(["list", "--stale-classification"])
    assert json.loads(capsys.readouterr().out) == []


def test_list_stale_classification_is_echoed_in_the_stats_scope(scrolls_home, capsys):
    # the --stats envelope names the filter it honored (only when honored — the
    # boolean rides the None-is-pruned convention), and `matched` is the post-filter count
    paths = get_paths()
    _seed_refresh_debt(paths)
    capsys.readouterr()

    main(["list", "--stale-classification", "--stats"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"]["stale_classification"] is True
    assert payload["stats"]["matched"] == 3
    assert len(payload["results"]) == 3

    # absent when not requested: the scope names exactly the filters applied
    main(["list", "--stats"])
    assert "stale_classification" not in json.loads(capsys.readouterr().out)["scope"]


def test_list_stale_summary_selects_the_stale_summary_members(scrolls_home, capsys):
    # H189: enumerate the held items that belong to a concept whose stored LLM
    # summary the live members would no longer reproduce — the read-side companion
    # of `kb --stale` (the members a refresh's clusters span). `_seed_refresh_debt`
    # makes two stale summaries: Bm25 (web+arxiv) and Vector (web+web) — 4 members.
    from scrolls.kb import load_concept_summaries
    from scrolls.kb_llm import stale_summary_members

    paths = get_paths()
    _seed_refresh_debt(paths)
    capsys.readouterr()

    main(["list", "--stale-summary"])
    rows = json.loads(capsys.readouterr().out)
    row_ids = {r["id"] for r in rows}

    # exactly the selector's set over the whole library + the stored summaries
    expected = {
        item.id
        for item in stale_summary_members(
            list_items(paths.db_path), load_concept_summaries(paths.db_path)
        )
    }
    assert row_ids == expected
    assert len(rows) == 4  # bm25-web, bm25-arxiv, vector-1, vector-2


def test_list_stale_summary_lists_the_members_of_the_doctor_stale_concepts(
    scrolls_home, capsys
):
    # convergence with the audit (H189): the rows are exactly the members of the
    # concepts `doctor` flags stale in custody.summaries.items — the clusters a
    # `kb --stale` refresh spans. (The rows are *members*, so they total member
    # count, not the per-source *concept* count `summary_by_source` carries.)
    from scrolls.kb import slugify

    paths = get_paths()
    _seed_refresh_debt(paths)
    capsys.readouterr()
    report = run_doctor(paths)
    stale_slugs = {entry["slug"] for entry in report["custody"]["summaries"]["items"]}
    assert stale_slugs == {"bm25", "vector"}  # the two stale concepts

    expected = {
        item.id
        for item in list_items(paths.db_path)
        if any(slugify(c) in stale_slugs for c in item.concepts)
    }
    main(["list", "--stale-summary"])
    row_ids = {r["id"] for r in json.loads(capsys.readouterr().out)}
    assert row_ids == expected


def test_list_stale_summary_ands_with_source_carrying_the_h171_attribution(
    scrolls_home, capsys
):
    # AND-composes with --source (H189): a multi-source stale cluster lists *every*
    # member, so `--stale-summary --source S` returns S's members of the clusters S
    # participates in. Bm25 spans web+arxiv, Vector is web-only → web has 3 members
    # (bm25-web, vector-1, vector-2), arxiv has 1 (bm25-arxiv).
    paths = get_paths()
    _seed_refresh_debt(paths)
    capsys.readouterr()

    main(["list", "--stale-summary", "--source", "web"])
    web = json.loads(capsys.readouterr().out)
    assert len(web) == 3 and all(r["source"] == "web" for r in web)

    main(["list", "--stale-summary", "--source", "arxiv"])
    arxiv = json.loads(capsys.readouterr().out)
    assert len(arxiv) == 1 and arxiv[0]["source"] == "arxiv"


def test_list_stale_summary_dedupes_an_item_in_several_stale_concepts(
    scrolls_home, capsys
):
    # H189 inspect-first decision: an item belonging to several stale concepts is
    # included once (deduped by id). Alpha = {X, Y}, Beta = {X, Z}; X is in both.
    paths = get_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    from scrolls.db import init_db

    init_db(paths.db_path)

    def member(slug, concepts):
        return ScrollItem(
            id=make_item_id("web", None, f"https://web.example.com/{slug}"),
            source="web", source_id=None,
            url=f"https://web.example.com/{slug}",
            saved_at="2026-06-14T00:00:00+00:00", title=slug,
            extracted_text="A note.", content_hash="sha256:" + slug,
            concepts=concepts, stage="rendered",
            provenance={"adapter": "web", "fetched_at": "2026-06-14T00:00:05+00:00"})

    members = [
        member("x", ("Alpha", "Beta")),
        member("y", ("Alpha",)),
        member("z", ("Beta",)),
    ]
    for item in members:
        insert_item(paths.db_path, write_scroll(paths, item))
    assert main(["kb"]) == 0
    _store_stale_summary("alpha", "Alpha")
    _store_stale_summary("beta", "Beta")
    capsys.readouterr()

    main(["list", "--stale-summary"])
    rows = json.loads(capsys.readouterr().out)
    ids = [r["id"] for r in rows]
    assert sorted(ids) == sorted({item.id for item in members})  # all three
    assert len(ids) == len(set(ids))  # X appears once, not twice


def test_list_stale_summary_is_honestly_empty_when_nothing_stale(scrolls_home, capsys):
    # a library with no stale summaries is [], never an error (completeness G1).
    # A single fresh-summarized cluster: current, so nothing stale.
    paths = get_paths()
    _seed_refresh_debt(paths)
    capsys.readouterr()
    # refresh both stale clusters offline by storing fingerprints that match live
    from scrolls.kb import load_concept_summaries, save_concept_summary
    from scrolls.kb_llm import eligible_concepts, members_hash

    eligible = eligible_concepts(
        [i for i in list_items(paths.db_path) if i.markdown_path]
    )
    for slug, stored in load_concept_summaries(paths.db_path).items():
        if slug in eligible:
            save_concept_summary(
                paths.db_path,
                dataclasses.replace(
                    stored, members_hash=members_hash(eligible[slug]["items"])
                ),
            )
    capsys.readouterr()

    main(["list", "--stale-summary"])
    assert json.loads(capsys.readouterr().out) == []


def test_list_stale_summary_is_echoed_in_the_stats_scope(scrolls_home, capsys):
    # the --stats envelope names the filter only when honored (the None-is-pruned
    # convention), and `matched` is the post-filter member count
    paths = get_paths()
    _seed_refresh_debt(paths)
    capsys.readouterr()

    main(["list", "--stale-summary", "--stats"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"]["stale_summary"] is True
    assert payload["stats"]["matched"] == 4
    assert len(payload["results"]) == 4

    # absent when not requested: the scope names exactly the filters applied
    main(["list", "--stats"])
    assert "stale_summary" not in json.loads(capsys.readouterr().out)["scope"]


def test_search_hit_echoes_the_drift_posture(scrolls_home, capsys):
    # H58: the drift posture rides ranked hits on the CLI too (the search ≡ list
    # parity on the new axis). The seeded titles all carry "Post", so the FTS
    # query matches every item.
    main(["init"])
    _seed_drift_postures()
    capsys.readouterr()

    main(["search", "Post"])
    hits = {h["id"]: h for h in json.loads(capsys.readouterr().out)}
    assert hits["web:0"]["drift"] == "verified"
    assert hits["web:1"]["drift"] == "drifted"
    assert hits["web:2"]["drift"] == "unverified"


def test_list_search_related_graph_agree_on_an_items_drift(scrolls_home, capsys):
    # H58: the per-item drift posture reads identically on every surface that
    # carries it — list rows, search hits, related hits, and graph nodes — the
    # per-item parity H56 began on the node shape, now completed on the primary
    # browse rows. (The full cross-surface invariant is pinned in H59.)
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    # two linked items so `related`/`graph` actually produce a hit/node for each
    insert_item(db, ScrollItem(
        id="web:a", source="web", url="https://ex.com/a",
        saved_at="2026-06-12T00:00:00+00:00", title="Alpha post about topic",
        extracted_text="alpha topic", links=("https://ex.com/b",), stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:b", source="web", url="https://ex.com/b",
        saved_at="2026-06-12T00:01:00+00:00", title="Beta post about topic",
        extracted_text="beta topic", links=("https://ex.com/a",), stage="fetched"))
    record_events(db, [
        CustodyEvent("web:b", "2026-06-14T00:00:00+00:00", "drifted", "h", "x", None),
    ])
    capsys.readouterr()

    # list
    main(["list"])
    list_drift = {r["id"]: r["drift"] for r in json.loads(capsys.readouterr().out)}
    # search
    main(["search", "topic"])
    search_drift = {h["id"]: h["drift"] for h in json.loads(capsys.readouterr().out)}
    # related (neighbours of web:a → web:b)
    main(["related", "web:a"])
    related_drift = {h["id"]: h["drift"] for h in json.loads(capsys.readouterr().out)}
    # graph nodes
    main(["graph"])
    graph_drift = {n["id"]: n["drift"] for n in json.loads(capsys.readouterr().out)["nodes"]}

    # web:b reads `drifted` on every surface that carries it
    assert list_drift["web:b"] == "drifted"
    assert search_drift["web:b"] == "drifted"
    assert related_drift["web:b"] == "drifted"
    assert graph_drift["web:b"] == "drifted"
    # and web:a reads the honest never-checked default everywhere
    assert list_drift["web:a"] == "unverified"
    assert search_drift["web:a"] == "unverified"


# --- scrolls facets (ADR 0080) ---


def _seed_facet_items():
    """Insert a small classified library; library must already exist."""
    db = get_paths().db_path
    rows = [
        ScrollItem(
            id="arxiv:1",
            source="arxiv",
            url="https://arxiv.org/abs/1",
            saved_at="2026-01-01T00:00:00+00:00",
            category="paper",
            tags=("cs.CL",),
            concepts=("Machine Learning",),
        ),
        ScrollItem(
            id="arxiv:2",
            source="arxiv",
            url="https://arxiv.org/abs/2",
            saved_at="2026-01-02T00:00:00+00:00",
            category="paper",
            tags=("cs.LG",),
            concepts=("machine learning",),
        ),
        ScrollItem(
            id="web:1",
            source="web",
            url="https://example.com/a",
            saved_at="2026-01-03T00:00:00+00:00",
            tags=("Rust",),
            concepts=("Cooking",),
        ),
    ]
    for item in rows:
        insert_item(db, item)


def test_facets_uninitialized_library_is_empty_but_well_shaped(scrolls_home, capsys):
    exit_code = main(["facets"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "facets": {
            "sources": [],
            "categories": [],
            "tags": [],
            "concepts": [],
            "fidelity": [],
            "drift": [],
            "method": [],
            "content-duplicate": [],
        }
    }


def test_facets_method_buckets_how_categories_were_produced(scrolls_home, capsys):
    # the aggregate counterpart of the per-item `classification` view (H28):
    # how much of the library was rules-classified vs set by hand vs unclassified
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="wikipedia:en:SQLite", source="wikipedia", source_id="en:SQLite",
        url="https://en.wikipedia.org/wiki/SQLite", saved_at="2026-06-12T00:00:00+00:00",
        title="SQLite", category="reference", stage="fetched",
        provenance={"classified_by": "rules-v1", "classified_basis": "curated-source",
                    "classified_ruleset": "abc123"}))
    insert_item(db, ScrollItem(
        id="web:user", source="web", url="https://ex.com/u",
        saved_at="2026-06-12T00:00:00+00:00", title="A hand-set post",
        category="opinion", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:bare", source="web", url="https://ex.com/b",
        saved_at="2026-06-12T00:00:00+00:00", title="An unclassified post", stage="fetched"))
    capsys.readouterr()

    main(["facets", "method"])
    payload = json.loads(capsys.readouterr().out)
    assert set(payload["facets"]) == {"method"}
    assert payload["facets"]["method"] == [
        {"value": "rules-v1", "count": 1},
        {"value": "unclassified", "count": 1},
        {"value": "user-set", "count": 1},
    ]


def test_facets_drift_buckets_held_items_by_custody_posture(scrolls_home, capsys):
    # the browse aggregate of the verify ledger (H48): held items by drift posture
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    for index in range(3):
        insert_item(db, ScrollItem(
            id=f"web:{index}", source="web", url=f"https://ex.com/{index}",
            saved_at="2026-06-12T00:00:00+00:00", title=f"Post {index}", stage="fetched"))
    record_events(db, [
        CustodyEvent("web:0", "2026-06-14T00:00:00+00:00", "unchanged", "h", "h", None),
        CustodyEvent("web:1", "2026-06-14T00:00:00+00:00", "drifted", "h", "x", None),
        # web:2 left unverified
    ])
    capsys.readouterr()

    main(["facets", "drift"])
    payload = json.loads(capsys.readouterr().out)
    assert set(payload["facets"]) == {"drift"}
    assert {e["value"]: e["count"] for e in payload["facets"]["drift"]} == {
        "verified": 1, "drifted": 1, "unverified": 1,
    }


def test_facets_reports_every_dimension(scrolls_home, capsys):
    main(["init"])
    _seed_facet_items()
    capsys.readouterr()

    main(["facets"])
    facets = json.loads(capsys.readouterr().out)["facets"]
    assert facets["sources"] == [
        {"value": "arxiv", "count": 2},
        {"value": "web", "count": 1},
    ]
    # the unclassified web item surfaces as the "" category, round-trippable
    # to `--category ""`
    assert facets["categories"] == [
        {"value": "paper", "count": 2},
        {"value": "", "count": 1},
    ]
    # the two spellings of "machine learning" merge by slug, smallest spelling
    # the display form, counting two distinct items
    assert facets["concepts"][0] == {
        "value": "Machine Learning",
        "slug": "machine-learning",
        "count": 2,
    }


def test_facets_single_field_returns_only_that_dimension(scrolls_home, capsys):
    main(["init"])
    _seed_facet_items()
    capsys.readouterr()

    main(["facets", "concepts"])
    payload = json.loads(capsys.readouterr().out)
    assert set(payload["facets"]) == {"concepts"}


def test_facets_scopes_to_a_source(scrolls_home, capsys):
    main(["init"])
    _seed_facet_items()
    capsys.readouterr()

    main(["facets", "concepts", "--source", "arxiv"])
    concepts = json.loads(capsys.readouterr().out)["facets"]["concepts"]
    assert concepts == [
        {"value": "Machine Learning", "slug": "machine-learning", "count": 2},
    ]


def test_facets_limit_caps_each_dimension(scrolls_home, capsys):
    main(["init"])
    _seed_facet_items()
    capsys.readouterr()

    main(["facets", "concepts", "--limit", "1"])
    concepts = json.loads(capsys.readouterr().out)["facets"]["concepts"]
    assert len(concepts) == 1


def test_facets_rejects_an_unknown_field(scrolls_home):
    with pytest.raises(SystemExit) as excinfo:
        main(["facets", "bogus"])
    assert excinfo.value.code == 2


# --- scrolls media (ADR 0011) ---


def _seed_fetched_item_with_media(item_id="arxiv:1706.03762", **overrides):
    """Insert a fetched item carrying one media ref; library must exist."""
    base = dict(
        id=item_id,
        source=item_id.split(":", 1)[0],
        source_id=item_id.split(":", 1)[1],
        url="https://arxiv.org/abs/1706.03762",
        saved_at="2026-06-12T08:00:00+00:00",
        title="Attention Is All You Need",
        summary="We propose the Transformer.",
        media=({"type": "pdf", "url": "https://arxiv.org/pdf/1706.03762"},),
        stage="fetched",
    )
    base.update(overrides)
    item = ScrollItem(**base)
    insert_item(get_paths().db_path, item)
    return item


def test_media_batch_captures_pending_refs_and_rerenders(scrolls_home, monkeypatch, capsys):
    import scrolls.media as media

    main(["init"])
    _seed_fetched_item_with_media()
    main(["md"])
    capsys.readouterr()
    monkeypatch.setattr(media, "_download", _as_download(lambda url: b"%PDF-1.4 fake"))

    exit_code = main(["media"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "captured": 1,
        "skipped": 0,
        "failed": 0,
        "results": [
            {
                "id": "arxiv:1706.03762",
                "status": "captured",
                "files": ["media/arxiv/1706-03762-1.pdf"],
            }
        ],
    }
    assert (
        scrolls_home / "media" / "arxiv" / "1706-03762-1.pdf"
    ).read_bytes() == b"%PDF-1.4 fake"
    stored = get_item(get_paths().db_path, "arxiv:1706.03762")
    assert stored.media[0]["path"] == "media/arxiv/1706-03762-1.pdf"
    # the rendered scroll's frontmatter now points at the local file
    scroll = (scrolls_home / "scrolls" / "arxiv" / "attention-is-all-you-need.md").read_text()
    assert '"path": "media/arxiv/1706-03762-1.pdf"' in scroll


def test_media_batch_is_idempotent(scrolls_home, monkeypatch, capsys):
    import scrolls.media as media

    main(["init"])
    _seed_fetched_item_with_media()
    monkeypatch.setattr(media, "_download", _as_download(lambda url: b"%PDF-1.4 fake"))
    main(["media"])
    capsys.readouterr()

    def boom(url):
        raise AssertionError("captured refs must not be re-downloaded")

    monkeypatch.setattr(media, "_download", _as_download(boom))
    exit_code = main(["media"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"captured": 0, "skipped": 0, "failed": 0, "results": []}


def test_media_by_id_recaptures_explicitly(scrolls_home, monkeypatch, capsys):
    import scrolls.media as media

    main(["init"])
    _seed_fetched_item_with_media()
    monkeypatch.setattr(media, "_download", _as_download(lambda url: b"version 1"))
    main(["media"])
    capsys.readouterr()

    monkeypatch.setattr(media, "_download", _as_download(lambda url: b"version 2"))
    exit_code = main(["media", "arxiv:1706.03762"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["captured"] == 1
    assert (
        scrolls_home / "media" / "arxiv" / "1706-03762-1.pdf"
    ).read_bytes() == b"version 2"


def test_media_by_id_unknown_item_is_an_error(scrolls_home, capsys):
    exit_code = main(["media", "arxiv:nope"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_media_by_id_without_refs_reports_skip(scrolls_home, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    exit_code = main(["media", "wikipedia:en:SQLite"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "captured": 0,
        "skipped": 1,
        "failed": 0,
        "results": [
            {
                "id": "wikipedia:en:SQLite",
                "status": "skipped",
                "reason": "no media references to capture",
            }
        ],
    }


def test_media_continues_past_failures_and_exits_nonzero(scrolls_home, monkeypatch, capsys):
    import scrolls.media as media

    main(["init"])
    _seed_fetched_item_with_media()
    _seed_fetched_item_with_media(
        item_id="x:1111",
        url="https://x.com/karpathy/status/1111",
        title="SQLite FTS5 is criminally underrated.",
        summary=None,
        media=({"type": "photo", "url": "https://pbs.twimg.com/bad"},),
    )
    capsys.readouterr()

    def get_bytes(url):
        if "bad" in url:
            raise OSError("connection refused")
        return b"good bytes"

    monkeypatch.setattr(media, "_download", _as_download(get_bytes))
    exit_code = main(["media"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["captured"] == 1
    assert payload["failed"] == 1
    by_id = {entry["id"]: entry for entry in payload["results"]}
    assert by_id["arxiv:1706.03762"]["status"] == "captured"
    assert by_id["x:1111"]["status"] == "failed"
    assert "connection refused" in by_id["x:1111"]["error"]
    # the failed ref stays pending: no path recorded, nothing on disk
    stored = get_item(get_paths().db_path, "x:1111")
    assert "path" not in stored.media[0]


# --- follow / unfollow / sync (feed subscriptions, ADR 0017) ---

FEED_BY_URL = {
    "https://blog.example.com/atom.xml": """\
<rss version="2.0"><channel><title>A Weblog</title>
<item><title>Post one</title><link>https://blog.example.com/2026/post-one/</link></item>
<item><title>Post two</title><link>https://blog.example.com/2026/post-two/</link></item>
</channel></rss>""",
    "https://www.youtube.com/feeds/videos.xml?playlist_id=PLabc123": """\
<feed xmlns="http://www.w3.org/2005/Atom"><title>A Playlist</title>
<entry><title>Video</title><link rel="alternate" href="https://www.youtube.com/watch?v=abc123def45"/></entry>
</feed>""",
}


@pytest.fixture
def fake_feeds(monkeypatch):
    """Feeds that serve no cache validators, so every sync is a full 200."""
    import scrolls.feeds as feeds
    from scrolls.sources.http import ConditionalText

    def get_text(url):
        if url not in FEED_BY_URL:
            raise OSError(f"connection refused: {url}")
        return FEED_BY_URL[url]

    monkeypatch.setattr(feeds, "_get_text", get_text)
    monkeypatch.setattr(
        feeds,
        "_get_conditional",
        lambda url, etag, last_modified: ConditionalText(text=get_text(url)),
    )


@pytest.fixture
def fake_caching_feed(monkeypatch):
    """A feed that serves an ETag and honors If-None-Match with a 304."""
    import scrolls.feeds as feeds
    from scrolls.sources.http import ConditionalText

    url = "https://blog.example.com/atom.xml"
    monkeypatch.setattr(feeds, "_get_text", lambda u: FEED_BY_URL[url])

    def get_conditional(u, etag, last_modified):
        if etag == 'W/"v1"':
            return ConditionalText(not_modified=True)
        return ConditionalText(text=FEED_BY_URL[url], etag='W/"v1"')

    monkeypatch.setattr(feeds, "_get_conditional", get_conditional)
    return url


def test_follow_registers_subscription(scrolls_home, fake_feeds, capsys):
    exit_code = main(["follow", "https://blog.example.com/atom.xml"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "id": payload["id"],
        "feed_url": "https://blog.example.com/atom.xml",
        "title": "A Weblog",
        "created": True,
    }
    assert len(payload["id"]) == 12


def test_follow_is_idempotent(scrolls_home, fake_feeds, capsys):
    main(["follow", "https://blog.example.com/atom.xml"])
    capsys.readouterr()
    exit_code = main(["follow", "https://blog.example.com/atom.xml"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["created"] is False


def test_follow_youtube_playlist_url_follows_its_feed(scrolls_home, fake_feeds, capsys):
    exit_code = main(["follow", "https://www.youtube.com/playlist?list=PLabc123"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["feed_url"] == "https://www.youtube.com/feeds/videos.xml?playlist_id=PLabc123"
    assert payload["title"] == "A Playlist"


def test_follow_unreachable_feed_is_an_error(scrolls_home, fake_feeds, capsys):
    exit_code = main(["follow", "https://nowhere.example.com/feed"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "connection refused" in json.loads(captured.err)["error"]


def test_follow_without_url_lists_subscriptions(scrolls_home, fake_feeds, capsys):
    main(["follow", "https://blog.example.com/atom.xml"])
    capsys.readouterr()
    exit_code = main(["follow"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["feed_url"] == "https://blog.example.com/atom.xml"
    assert payload[0]["title"] == "A Weblog"
    assert payload[0]["last_synced_at"] is None


def test_follow_list_before_init_prints_empty_array(scrolls_home, capsys):
    exit_code = main(["follow"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


def test_unfollow_removes_subscription(scrolls_home, fake_feeds, capsys):
    main(["follow", "https://blog.example.com/atom.xml"])
    sub_id = json.loads(capsys.readouterr().out)["id"]

    exit_code = main(["unfollow", sub_id])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {"id": sub_id, "removed": True}
    main(["follow"])
    assert json.loads(capsys.readouterr().out) == []


def test_unfollow_accepts_the_feed_url(scrolls_home, fake_feeds, capsys):
    main(["follow", "https://blog.example.com/atom.xml"])
    capsys.readouterr()
    exit_code = main(["unfollow", "https://blog.example.com/atom.xml"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["removed"] is True


def test_unfollow_unknown_id_is_an_error(scrolls_home, capsys):
    exit_code = main(["unfollow", "feedcafe1234"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no such subscription" in json.loads(captured.err)["error"]


def test_sync_registers_new_items_at_stage_detected(scrolls_home, fake_feeds, capsys):
    main(["follow", "https://blog.example.com/atom.xml"])
    capsys.readouterr()

    exit_code = main(["sync"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["new"] == 2 and payload["known"] == 0 and payload["failed"] == 0
    assert payload["results"][0]["status"] == "synced"
    assert len(payload["results"][0]["new_items"]) == 2

    item_id = payload["results"][0]["new_items"][0]
    stored = get_item(get_paths().db_path, item_id)
    assert stored.source == "web" and stored.stage == "detected"


def test_sync_is_idempotent(scrolls_home, fake_feeds, capsys):
    main(["follow", "https://blog.example.com/atom.xml"])
    main(["sync"])
    capsys.readouterr()
    exit_code = main(["sync"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["new"] == 0 and payload["known"] == 2


def test_sync_by_id_syncs_one_subscription(scrolls_home, fake_feeds, capsys):
    main(["follow", "https://blog.example.com/atom.xml"])
    sub_id = json.loads(capsys.readouterr().out)["id"]
    main(["follow", "https://www.youtube.com/playlist?list=PLabc123"])
    capsys.readouterr()

    exit_code = main(["sync", sub_id])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["new"] == 2
    assert [r["id"] for r in payload["results"]] == [sub_id]


def test_sync_unknown_id_is_an_error(scrolls_home, capsys):
    exit_code = main(["sync", "feedcafe1234"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no such subscription" in json.loads(captured.err)["error"]


def test_sync_continues_past_feed_failures_and_exits_nonzero(
    scrolls_home, fake_feeds, monkeypatch, capsys
):
    import scrolls.feeds as feeds

    main(["follow", "https://blog.example.com/atom.xml"])
    capsys.readouterr()
    # the feed goes dark after the follow
    monkeypatch.setattr(
        feeds,
        "_get_conditional",
        lambda url, etag, last_modified: (_ for _ in ()).throw(OSError("gone")),
    )

    exit_code = main(["sync"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed"] == 1
    assert payload["results"][0]["status"] == "failed"
    assert "gone" in payload["results"][0]["error"]


def test_sync_unchanged_feed_reports_unchanged(scrolls_home, fake_caching_feed, capsys):
    main(["follow", fake_caching_feed])
    main(["sync"])  # full 200: registers entries, stores the ETag
    capsys.readouterr()

    exit_code = main(["sync"])  # the feed now answers 304
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["unchanged"] == 1
    assert payload["new"] == 0 and payload["known"] == 0 and payload["failed"] == 0
    assert payload["results"][0]["status"] == "unchanged"


def test_sync_before_init_reports_nothing_to_do(scrolls_home, capsys):
    exit_code = main(["sync"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "new": 0,
        "known": 0,
        "skipped": 0,
        "unchanged": 0,
        "failed": 0,
        "results": [],
    }


# --- set (user classification overrides, ADR 0018) ---


def _seed_rendered_item(item_id="x:1111", **overrides):
    """Insert a fetched item and render it; library must exist."""
    base = dict(
        id=item_id,
        source=item_id.split(":", 1)[0],
        source_id=item_id.split(":", 1)[1],
        url="https://x.com/karpathy/status/1111",
        saved_at="2026-06-12T08:00:00+00:00",
        title="SQLite FTS5 is criminally underrated.",
        extracted_text="SQLite FTS5 is criminally underrated for local search.",
        stage="fetched",
    )
    base.update(overrides)
    insert_item(get_paths().db_path, ScrollItem(**base))
    main(["md", item_id])
    return get_item(get_paths().db_path, item_id)


def test_set_overrides_fields_and_rerenders(scrolls_home, capsys):
    main(["init"])
    item = _seed_rendered_item(category="technique")
    capsys.readouterr()

    exit_code = main(["set", item.id, "category=tool", "domain=databases", "tags=sqlite,fts"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "id": item.id,
        "status": "set",
        "category": "tool",
        "domain": "databases",
        "tags": ["sqlite", "fts"],
        "concepts": [],
        "markdown_path": item.markdown_path,
    }
    stored = get_item(get_paths().db_path, item.id)
    assert stored.category == "tool" and stored.domain == "databases"
    assert stored.stage == "rendered"  # set is stage-neutral
    scroll = (get_paths().root / item.markdown_path).read_text()
    assert '"tool"' in scroll and '"sqlite"' in scroll


def test_set_empty_value_clears_for_reclassification(scrolls_home, capsys):
    main(["init"])
    item = _seed_rendered_item(category="technique")
    capsys.readouterr()

    main(["set", item.id, "category="])
    capsys.readouterr()
    assert get_item(get_paths().db_path, item.id).category is None

    # the cleared item is batch-classifiable again (title rule: none matches here)
    exit_code = main(["classify"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(r["id"] == item.id for r in payload["results"])


def test_set_survives_batch_classify(scrolls_home, capsys):
    """IDEAS.md §8: user overrides always win over batch runs."""
    main(["init"])
    item = _seed_rendered_item(item_id="x:2222", title="a guide to reading papers")
    capsys.readouterr()

    main(["set", item.id, "category=opinion"])
    main(["classify"])  # title would match the tutorial rule, but category is set
    capsys.readouterr()
    assert get_item(get_paths().db_path, item.id).category == "opinion"


def test_set_unknown_field_is_an_error(scrolls_home, capsys):
    main(["init"])
    item = _seed_rendered_item()
    capsys.readouterr()

    exit_code = main(["set", item.id, "usefulness=high"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cannot set 'usefulness'" in json.loads(captured.err)["error"]
    assert get_item(get_paths().db_path, item.id).category is None  # nothing applied


def test_set_malformed_assignment_is_an_error(scrolls_home, capsys):
    main(["init"])
    item = _seed_rendered_item()
    capsys.readouterr()

    exit_code = main(["set", item.id, "category"])
    assert exit_code == 1
    assert "field=value" in json.loads(capsys.readouterr().err)["error"]


def test_set_unknown_id_is_an_error(scrolls_home, capsys):
    exit_code = main(["set", "x:9999", "category=tool"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no such item" in json.loads(captured.err)["error"]


def test_set_unrendered_item_skips_rerender(scrolls_home, capsys):
    main(["add", "https://x.com/karpathy/status/7777"])
    capsys.readouterr()

    exit_code = main(["set", "x:7777", "category=tool"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["category"] == "tool" and payload["markdown_path"] is None
    assert get_item(get_paths().db_path, "x:7777").category == "tool"


def test_rm_removes_item_and_its_files(scrolls_home, capsys):
    main(["add", "https://x.com/karpathy/status/1111"])
    item = get_item(get_paths().db_path, "x:1111")
    rendered = write_scroll(
        get_paths(),
        dataclasses.replace(
            item, title="A tweet", extracted_text="text", stage="fetched"
        ),
    )
    update_item(get_paths().db_path, rendered)
    capsys.readouterr()

    exit_code = main(["rm", "x:1111"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "removed": 1,
        "failed": 0,
        "results": [
            {
                "ref": "x:1111",
                "id": "x:1111",
                "url": "https://x.com/karpathy/status/1111",
                "status": "removed",
                "files": [rendered.markdown_path],
            }
        ],
    }
    assert get_item(get_paths().db_path, "x:1111") is None
    assert not (scrolls_home / rendered.markdown_path).exists()


def test_rm_accepts_the_url_that_added_the_item(scrolls_home, capsys):
    main(["add", "https://example.com/post?utm_source=newsletter"])
    capsys.readouterr()

    # the clean spelling resolves to the same id (ADR 0023 normalization)
    exit_code = main(["rm", "https://example.com/post"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] == 1
    assert payload["results"][0]["status"] == "removed"
    assert main(["list"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_rm_unknown_id_fails_with_batch_payload(scrolls_home, capsys):
    main(["init"])
    capsys.readouterr()

    exit_code = main(["rm", "web:nope"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] == 0 and payload["failed"] == 1
    assert payload["results"][0] == {
        "ref": "web:nope",
        "status": "failed",
        "error": "no such item: web:nope",
    }


def test_rm_continues_past_failures_and_exits_nonzero(scrolls_home, capsys):
    main(["add", "https://x.com/karpathy/status/1111"])
    capsys.readouterr()

    exit_code = main(["rm", "web:nope", "x:1111", "ftp://bad"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] == 1 and payload["failed"] == 2
    statuses = [result["status"] for result in payload["results"]]
    assert statuses == ["failed", "removed", "failed"]
    assert get_item(get_paths().db_path, "x:1111") is None


def test_rm_before_init_fails(scrolls_home, capsys):
    exit_code = main(["rm", "x:1111"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] == 0 and payload["failed"] == 1


# --- every item-id argument accepts the item's URL (ADR 0028) ---


def test_show_accepts_item_url(scrolls_home, capsys):
    main(["add", "https://example.com/post?utm_source=newsletter"])
    capsys.readouterr()

    exit_code = main(["show", "https://example.com/post"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["url"] == "https://example.com/post"
    assert payload["source"] == "web"


def test_show_unknown_url_reports_the_resolved_id(scrolls_home, capsys):
    main(["init"])
    capsys.readouterr()

    exit_code = main(["show", "https://example.com/never-saved"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)["error"]
    assert error.startswith("no such item: web:")
    assert "(from https://example.com/never-saved)" in error


def test_fetch_accepts_item_url(scrolls_home, monkeypatch, capsys):
    # `x` was the last detected source without a fetch adapter; now that it has
    # one, the adapterless case is reached only by a source this build does not
    # know (an imported bundle from a newer one). Dropping the entry reproduces
    # that without pretending x is unfetchable -- and keeps the test offline,
    # since the adapter would otherwise reach live X over the browser session.
    monkeypatch.delitem(FETCH_ADAPTERS, "x")
    main(["add", "https://x.com/karpathy/status/1111"])
    capsys.readouterr()

    # resolution worked iff fetch reaches the adapter check, not "no such item"
    exit_code = main(["fetch", "https://x.com/karpathy/status/1111"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["error"] == "no fetch adapter for source 'x'"


def test_set_accepts_item_url(scrolls_home, capsys):
    main(["add", "https://example.com/post"])
    capsys.readouterr()

    exit_code = main(["set", "https://example.com/post", "category=tool"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "set" and payload["category"] == "tool"


def test_related_accepts_item_url(scrolls_home, capsys):
    main(["add", "https://example.com/post"])
    capsys.readouterr()

    exit_code = main(["related", "https://example.com/post"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


def test_md_accepts_item_url(scrolls_home, capsys):
    main(["add", "https://example.com/post"])
    item_id = json.loads(capsys.readouterr().out)["id"]
    item = get_item(get_paths().db_path, item_id)
    update_item(
        get_paths().db_path,
        dataclasses.replace(item, title="A Post", extracted_text="text", stage="fetched"),
    )

    exit_code = main(["md", "https://example.com/post"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rendered"] == 1
    assert payload["results"][0]["id"] == item_id
