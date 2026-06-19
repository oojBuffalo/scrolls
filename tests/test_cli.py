"""Tests for the `scrolls` CLI entry point."""

import dataclasses
import json

import pytest

import scrolls.sources.wikipedia as wikipedia
import scrolls.sources.youtube as youtube
from scrolls.classify import RULESET_FINGERPRINT
from scrolls.cli import main
from scrolls.custody import (
    CustodyEvent,
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
    snapshot_headline,
    weakest_source,
)
from scrolls.paths import get_paths
from scrolls.items import (
    ScrollItem,
    get_item,
    insert_item,
    list_items,
    make_item_id,
    update_item,
)
from scrolls.render import write_scroll


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


def test_fetch_all_skips_sources_without_adapter(scrolls_home, fake_wikipedia_api, capsys):
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
    scrolls_home, fake_wikipedia_api, capsys
):
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


def test_fetch_by_id_without_adapter_fails(scrolls_home, capsys):
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
    assert payload == {"rendered": 0, "failed": 0, "results": []}


def test_md_by_id_rerenders_a_rendered_item(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    main(["md"])
    capsys.readouterr()

    exit_code = main(["md", "wikipedia:en:SQLite"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rendered"] == 1
    assert payload["results"][0]["path"] == "scrolls/wikipedia/sqlite.md"


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
        "drift", "last_checked", "works",
    }
    # a freshly fetched Wikipedia article holds a re-derivable body — full custody
    assert hit["fidelity"] == "full"
    # never re-verified against its live source — the honest never-checked posture (H58)
    assert hit["drift"] == "unverified"
    # …and so no last-checked timestamp to report (H84 honest absence)
    assert hit["last_checked"] is None
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
    """The returned/matched/truncated trio, dropping the H98 `custody` member.

    The `--stats` envelope's `stats` block now also carries a `custody` tally
    (roadmap H98); these G2 truncation/scope tests pin the *denominator*, so they
    drop `custody` and let the dedicated H98 tests below own its value.
    """
    return {key: value for key, value in stats.items() if key != "custody"}


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


def test_ingest_without_adapter_registers_but_reports_failure(scrolls_home, capsys):
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
    assert payload == {"imported": 1, "skipped": 0, "items": 1}
    restored = get_item(get_paths().db_path, "arxiv:1706.03762")
    assert restored == seeded  # every field survived the round-trip


def test_import_items_is_idempotent(scrolls_home, tmp_path, capsys):
    _seed_rich_item(scrolls_home)
    capsys.readouterr()
    main(["export", "items"])
    out_path = tmp_path / "library.jsonl"
    out_path.write_text(capsys.readouterr().out, encoding="utf-8")
    # re-importing into the same library skips the already-present item
    exit_code = main(["import", "items", str(out_path)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"imported": 0, "skipped": 1, "items": 1}


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
    monkeypatch.setattr(media, "_get_bytes", lambda url: b"%PDF-1.4 fake")

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
    monkeypatch.setattr(media, "_get_bytes", lambda url: b"%PDF-1.4 fake")
    main(["media"])
    capsys.readouterr()

    def boom(url):
        raise AssertionError("captured refs must not be re-downloaded")

    monkeypatch.setattr(media, "_get_bytes", boom)
    exit_code = main(["media"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"captured": 0, "skipped": 0, "failed": 0, "results": []}


def test_media_by_id_recaptures_explicitly(scrolls_home, monkeypatch, capsys):
    import scrolls.media as media

    main(["init"])
    _seed_fetched_item_with_media()
    monkeypatch.setattr(media, "_get_bytes", lambda url: b"version 1")
    main(["media"])
    capsys.readouterr()

    monkeypatch.setattr(media, "_get_bytes", lambda url: b"version 2")
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

    monkeypatch.setattr(media, "_get_bytes", get_bytes)
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


def test_fetch_accepts_item_url(scrolls_home, capsys):
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
