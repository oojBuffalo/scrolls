"""CLI tests for `scrolls verify` — drift/rot custody events (ADR 0098).

`verify` re-captures held items and appends a custody verdict to the ledger
without touching the original capture. The network edge (`live_recapture`) is
monkeypatched here so every verdict path — unchanged / drifted / rotted /
error — and the ledger writes are exercised offline.
"""

import json
import urllib.error

import pytest

import scrolls.cli as cli
from scrolls.cli import main
from scrolls.custody import item_events
from scrolls.db import init_db
from scrolls.items import ScrollItem, get_item, insert_item, make_item_id
from scrolls.paths import get_paths
from scrolls.sources import FetchError


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


@pytest.fixture
def paths(scrolls_home):
    library = get_paths()
    library.root.mkdir(parents=True)
    init_db(library.db_path)
    return library


def _item(url, content_hash="sha256:orig", **overrides):
    fields = {
        "id": make_item_id("web", None, url),
        "source": "web",
        "source_id": None,
        "url": url,
        "saved_at": "2026-06-12T08:00:00+00:00",
        "content_hash": content_hash,
        "extracted_text": "captured body",
        "stage": "rendered",
    }
    fields.update(overrides)
    return ScrollItem(**fields)


def _stub_recapture(monkeypatch, fn):
    """Replace the network edge `_cmd_verify` passes into the engine."""
    monkeypatch.setattr(cli, "live_recapture", fn)


def _gone(code):
    http_error = urllib.error.HTTPError("https://e.com", code, "gone", {}, None)

    def recapture(_):
        raise FetchError("web request failed") from http_error

    return recapture


# --- single-item verdicts -------------------------------------------------


def test_verify_by_id_records_unchanged(paths, monkeypatch, capsys):
    item = _item("https://example.com/a", content_hash="sha256:same")
    insert_item(paths.db_path, item)
    _stub_recapture(monkeypatch, lambda i: i)  # same hash back

    exit_code = main(["verify", item.id])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert out["checked"] == 1
    assert out["unchanged"] == 1
    assert out["results"][0]["status"] == "unchanged"
    # one ledger event written
    history = item_events(paths.db_path, item.id)
    assert [e.status for e in history] == ["unchanged"]


def test_verify_by_id_records_drift(paths, monkeypatch, capsys):
    item = _item("https://example.com/a", content_hash="sha256:old")
    insert_item(paths.db_path, item)
    _stub_recapture(
        monkeypatch,
        lambda i: _item("https://example.com/a", content_hash="sha256:new"),
    )

    exit_code = main(["verify", item.id])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert out["drifted"] == 1
    result = out["results"][0]
    assert result["status"] == "drifted"
    assert result["prior_hash"] == "sha256:old"
    assert result["observed_hash"] == "sha256:new"


def test_verify_by_url_ref_resolves_to_the_item(paths, monkeypatch, capsys):
    item = _item("https://example.com/a", content_hash="sha256:old")
    insert_item(paths.db_path, item)
    _stub_recapture(
        monkeypatch,
        lambda i: _item("https://example.com/a", content_hash="sha256:new"),
    )

    main(["verify", "https://example.com/a"])
    out = json.loads(capsys.readouterr().out)
    assert out["results"][0]["id"] == item.id
    assert out["results"][0]["status"] == "drifted"


def test_verify_records_rot_on_http_404(paths, monkeypatch, capsys):
    item = _item("https://example.com/gone")
    insert_item(paths.db_path, item)
    _stub_recapture(monkeypatch, _gone(404))

    exit_code = main(["verify", item.id])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0  # a proven rot is a successful check
    assert out["rotted"] == 1
    assert out["results"][0]["status"] == "rotted"
    assert out["results"][0]["observed_hash"] is None


def test_verify_transient_failure_is_error_and_exits_nonzero(paths, monkeypatch, capsys):
    item = _item("https://example.com/a")
    insert_item(paths.db_path, item)

    def boom(_):
        raise FetchError("timed out")

    _stub_recapture(monkeypatch, boom)
    exit_code = main(["verify", item.id])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert out["error"] == 1
    assert out["results"][0]["status"] == "error"


def test_verify_never_clobbers_the_capture(paths, monkeypatch, capsys):
    item = _item("https://example.com/a", content_hash="sha256:old")
    insert_item(paths.db_path, item)
    _stub_recapture(
        monkeypatch,
        lambda i: _item(
            "https://example.com/a", content_hash="sha256:new",
            extracted_text="rewritten upstream",
        ),
    )

    main(["verify", item.id])
    stored = get_item(paths.db_path, item.id)
    assert stored == item  # original capture is untouched after a drift verdict


# --- argument handling ----------------------------------------------------


def test_verify_needs_an_id_or_all(paths, capsys):
    exit_code = main(["verify"])
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


def test_verify_rejects_id_and_all_together(paths, capsys):
    exit_code = main(["verify", "web:x", "--all"])
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


def test_verify_id_with_limit_is_an_error(paths, capsys):
    exit_code = main(["verify", "web:x", "--limit", "2"])
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


def test_verify_unknown_id_is_an_error(paths, capsys):
    exit_code = main(["verify", "web:nope"])
    assert exit_code == 1
    assert "no such item" in json.loads(capsys.readouterr().err)["error"]


def test_verify_item_without_content_hash_is_an_error(paths, capsys):
    item = _item("https://example.com/ref", content_hash=None,
                 extracted_text=None, stage="detected")
    insert_item(paths.db_path, item)
    exit_code = main(["verify", item.id])
    assert exit_code == 1
    assert "no content hash" in json.loads(capsys.readouterr().err)["error"]


# --- batch (--all) --------------------------------------------------------


def test_verify_all_checks_every_hash_bearing_item(paths, monkeypatch, capsys):
    insert_item(paths.db_path, _item("https://example.com/a", content_hash="sha256:a"))
    insert_item(paths.db_path, _item("https://example.com/b", content_hash="sha256:b"))
    # reference-only item with no baseline hash is skipped by --all
    insert_item(paths.db_path, _item(
        "https://example.com/ref", content_hash=None, extracted_text=None,
        stage="detected"))
    _stub_recapture(monkeypatch, lambda i: i)  # all unchanged

    main(["verify", "--all"])
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 2
    assert out["unchanged"] == 2


def test_verify_all_limit_caps_attempts(paths, monkeypatch, capsys):
    for n in range(3):
        insert_item(paths.db_path, _item(
            f"https://example.com/{n}", content_hash=f"sha256:{n}"))
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--all", "--limit", "2"])
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 2


def test_verify_all_on_empty_library(scrolls_home, capsys):
    exit_code = main(["verify", "--all"])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert out["checked"] == 0


def test_verify_feeds_the_doctor_drift_report(paths, monkeypatch, capsys):
    item = _item("https://example.com/a", content_hash="sha256:old")
    insert_item(paths.db_path, item)
    _stub_recapture(
        monkeypatch,
        lambda i: _item("https://example.com/a", content_hash="sha256:new"),
    )
    main(["verify", item.id])
    capsys.readouterr()  # drain

    main(["doctor"])
    drift = json.loads(capsys.readouterr().out)["custody"]["drift"]
    assert drift["checked"] == 1
    assert drift["drifted"] == 1
    assert drift["events"][0]["id"] == item.id
    assert drift["events"][0]["observed_hash"] == "sha256:new"


# --- unverified selection (--unverified) ----------------------------------


def test_verify_unverified_checks_only_never_verified_items(paths, monkeypatch, capsys):
    a = _item("https://example.com/a", content_hash="sha256:a")
    b = _item("https://example.com/b", content_hash="sha256:b")
    insert_item(paths.db_path, a)
    insert_item(paths.db_path, b)
    _stub_recapture(monkeypatch, lambda i: i)  # all unchanged

    main(["verify", a.id])  # a now has a ledger verdict; b never checked
    capsys.readouterr()  # drain

    main(["verify", "--unverified"])
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 1
    assert [r["id"] for r in out["results"]] == [b.id]


def test_verify_unverified_clears_the_doctor_signal(paths, monkeypatch, capsys):
    # the held − verdicts set --unverified re-checks is exactly what doctor
    # reports as `unverified`, so the re-check drives that count to zero
    insert_item(paths.db_path, _item("https://example.com/a", content_hash="sha256:a"))
    insert_item(paths.db_path, _item("https://example.com/b", content_hash="sha256:b"))
    _stub_recapture(monkeypatch, lambda i: i)  # all unchanged

    main(["doctor"])
    before = json.loads(capsys.readouterr().out)["custody"]["drift"]
    assert before["unverified"] == 2 and before["checked"] == 0

    main(["verify", "--unverified"])
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 2 and out["unchanged"] == 2

    main(["doctor"])
    after = json.loads(capsys.readouterr().out)["custody"]["drift"]
    assert after["unverified"] == 0 and after["checked"] == 2


def test_verify_unverified_skips_reference_only_items(paths, monkeypatch, capsys):
    # a reference-only capture is `unverified` (doctor counts it) but has no
    # baseline to diff a re-fetch against, so --unverified skips it like --all —
    # it honestly stays unverified, there is nothing to verify it on
    insert_item(paths.db_path, _item("https://example.com/a", content_hash="sha256:a"))
    insert_item(paths.db_path, _item(
        "https://example.com/ref", content_hash=None, extracted_text=None,
        stage="detected"))
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--unverified"])
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 1  # only the hash-bearing item

    main(["doctor"])
    drift = json.loads(capsys.readouterr().out)["custody"]["drift"]
    assert drift["unverified"] == 1  # the reference-only item remains


def test_verify_unverified_limit_caps_attempts(paths, monkeypatch, capsys):
    for n in range(3):
        insert_item(paths.db_path, _item(
            f"https://example.com/{n}", content_hash=f"sha256:{n}"))
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--unverified", "--limit", "2"])
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 2  # oldest saved first, the third left unverified


def test_verify_unverified_on_empty_library(scrolls_home, capsys):
    exit_code = main(["verify", "--unverified"])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert out["checked"] == 0


def test_verify_unverified_no_targets_is_a_noop(paths, monkeypatch, capsys):
    # every hash-bearing item already verified ⇒ nothing left, no network touched
    item = _item("https://example.com/a", content_hash="sha256:a")
    insert_item(paths.db_path, item)

    def explode(_):
        raise AssertionError("recapture must not run when there is nothing to verify")

    _stub_recapture(monkeypatch, lambda i: i)
    main(["verify", item.id])  # records a verdict
    capsys.readouterr()  # drain
    _stub_recapture(monkeypatch, explode)

    exit_code = main(["verify", "--unverified"])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert out["checked"] == 0


def test_verify_rejects_all_and_unverified_together(paths, capsys):
    exit_code = main(["verify", "--all", "--unverified"])
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


# --- scrolls history <id> — the per-item custody ledger timeline (H66) -----
#
# `verify` appends an append-only event per check; `show`/`list` carry only the
# *latest* drift posture and doctor/facets only aggregate counts. `history`
# emits the *full* ledger for one item as JSON, newest first — when a source
# drifted and how often it was re-checked, the per-item counterpart of
# `maintain --history`'s scope-level trajectory.


def _drifts_to(new_hash):
    """A recapture stub returning the stored item with a changed content hash."""
    import dataclasses

    return lambda item: dataclasses.replace(item, content_hash=new_hash)


def test_history_lists_every_event_newest_first(paths, monkeypatch, capsys):
    item = _item("https://example.com/a", content_hash="sha256:orig")
    insert_item(paths.db_path, item)

    _stub_recapture(monkeypatch, _drifts_to("sha256:changed"))
    main(["verify", item.id])  # event 1: drifted
    capsys.readouterr()
    _stub_recapture(monkeypatch, lambda i: i)
    main(["verify", item.id])  # event 2: unchanged (same stored hash)
    capsys.readouterr()

    exit_code = main(["history", item.id])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert [e["status"] for e in out] == ["unchanged", "drifted"]  # newest first


def test_history_event_carries_the_five_field_shape(paths, monkeypatch, capsys):
    item = _item("https://example.com/a", content_hash="sha256:orig")
    insert_item(paths.db_path, item)
    _stub_recapture(monkeypatch, _drifts_to("sha256:changed"))
    main(["verify", item.id])
    capsys.readouterr()

    exit_code = main(["history", item.id])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert len(out) == 1
    assert set(out[0]) == {"checked_at", "status", "prior_hash", "observed_hash", "detail"}
    assert out[0]["status"] == "drifted"
    assert out[0]["prior_hash"] == "sha256:orig"
    assert out[0]["observed_hash"] == "sha256:changed"
    assert out[0]["detail"] is None
    assert out[0]["checked_at"]  # a real timestamp, not empty


def test_history_converges_with_the_item_history_primitive(paths, monkeypatch, capsys):
    """The CLI emits exactly the shared `custody.item_history` primitive."""
    from scrolls.custody import item_history

    item = _item("https://example.com/a", content_hash="sha256:orig")
    insert_item(paths.db_path, item)
    _stub_recapture(monkeypatch, _drifts_to("sha256:changed"))
    main(["verify", item.id])
    capsys.readouterr()

    exit_code = main(["history", item.id])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert out == item_history(paths.db_path, item.id)


def test_history_of_a_never_verified_item_is_empty(paths, capsys):
    item = _item("https://example.com/a", content_hash="sha256:orig")
    insert_item(paths.db_path, item)

    exit_code = main(["history", item.id])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out) == []
    assert captured.err == ""  # checked-and-empty writes nothing to stderr


def test_history_resolves_a_url_to_its_id(paths, monkeypatch, capsys):
    item = _item("https://example.com/a", content_hash="sha256:orig")
    insert_item(paths.db_path, item)
    _stub_recapture(monkeypatch, lambda i: i)
    main(["verify", item.id])
    capsys.readouterr()

    # the URL that saved it resolves to the same id (ADR 0028)
    exit_code = main(["history", "https://example.com/a"])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert [e["status"] for e in out] == ["unchanged"]


def test_history_unknown_id_errors_loudly(paths, capsys):
    exit_code = main(["history", "web:does-not-exist"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""  # nothing on stdout when the check could not run
    assert "error" in json.loads(captured.err)
