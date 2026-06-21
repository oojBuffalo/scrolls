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
from scrolls.custody import CustodyEvent, item_events, record_events
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


# --- staleness-bounded recheck (--stale-before ISO, H79) ------------------
#
# The act-side `--since` sibling: re-verify only the held, hash-bearing items
# whose newest ledger verdict predates the boundary (plus the never-checked) —
# "re-check everything not seen since the last sweep". Completes the `--since`
# family across the read (`history --since`), the backup (`export events
# --since`), and the recheck.


def _seed_verdict(paths, item, checked_at, status="unchanged"):
    """Append one custody verdict for `item` stamped at a chosen `checked_at`."""
    record_events(
        paths.db_path,
        [CustodyEvent(item.id, checked_at, status, item.content_hash,
                      item.content_hash, None)],
    )


def test_verify_stale_before_selects_only_stale_and_never_checked(paths, monkeypatch, capsys):
    stale = _item("https://example.com/stale", content_hash="sha256:s")
    fresh = _item("https://example.com/fresh", content_hash="sha256:f")
    never = _item("https://example.com/never", content_hash="sha256:n")
    for it in (stale, fresh, never):
        insert_item(paths.db_path, it)
    _seed_verdict(paths, stale, "2026-06-10T00:00:00+00:00")  # before boundary
    _seed_verdict(paths, fresh, "2026-06-20T00:00:00+00:00")  # after boundary
    # `never` has no verdict → trivially stale
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--stale-before", "2026-06-15T00:00:00+00:00"])
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 2
    assert sorted(r["id"] for r in out["results"]) == sorted([stale.id, never.id])


def test_verify_stale_before_treats_an_at_boundary_check_as_fresh(paths, monkeypatch, capsys):
    # the boundary itself is fresh (predates = strictly before), the complement
    # of the `>= boundary` window `history --since` keeps
    item = _item("https://example.com/a", content_hash="sha256:a")
    insert_item(paths.db_path, item)
    boundary = "2026-06-15T00:00:00+00:00"
    _seed_verdict(paths, item, boundary)

    def explode(_):
        raise AssertionError("an at-boundary check is fresh; must not be re-verified")

    _stub_recapture(monkeypatch, explode)
    exit_code = main(["verify", "--stale-before", boundary])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and out["checked"] == 0


def test_verify_stale_before_future_boundary_subsumes_unverified(paths, monkeypatch, capsys):
    # a far-future boundary makes every verdict stale, so it re-checks the
    # never-checked set --unverified would *and* the long-ago-checked
    checked = _item("https://example.com/checked", content_hash="sha256:c")
    never = _item("https://example.com/never", content_hash="sha256:n")
    insert_item(paths.db_path, checked)
    insert_item(paths.db_path, never)
    _seed_verdict(paths, checked, "2026-06-10T00:00:00+00:00")
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--stale-before", "2099-01-01T00:00:00+00:00"])
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 2
    assert sorted(r["id"] for r in out["results"]) == sorted([checked.id, never.id])


def test_verify_stale_before_accepts_a_date_only_boundary(paths, monkeypatch, capsys):
    # the boundary normalizes through parse_since (date-only → that day's UTC
    # midnight), like `history --since`
    stale = _item("https://example.com/stale", content_hash="sha256:s")
    fresh = _item("https://example.com/fresh", content_hash="sha256:f")
    insert_item(paths.db_path, stale)
    insert_item(paths.db_path, fresh)
    _seed_verdict(paths, stale, "2026-06-14T23:00:00+00:00")  # before midnight
    _seed_verdict(paths, fresh, "2026-06-15T01:00:00+00:00")  # after midnight
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--stale-before", "2026-06-15"])
    out = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in out["results"]] == [stale.id]


def test_verify_stale_before_limit_caps_attempts(paths, monkeypatch, capsys):
    for n in range(3):  # all never checked → all stale before a future boundary
        insert_item(paths.db_path, _item(
            f"https://example.com/{n}", content_hash=f"sha256:{n}"))
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--stale-before", "2099-01-01T00:00:00+00:00", "--limit", "2"])
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 2  # oldest saved first, the third left for next pass


def test_verify_stale_before_skips_reference_only_items(paths, monkeypatch, capsys):
    # a reference-only capture has no baseline to diff a re-fetch against, so it
    # is skipped like --all/--unverified even though it is never-checked
    insert_item(paths.db_path, _item("https://example.com/a", content_hash="sha256:a"))
    insert_item(paths.db_path, _item(
        "https://example.com/ref", content_hash=None, extracted_text=None,
        stage="detected"))
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--stale-before", "2099-01-01T00:00:00+00:00"])
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 1  # only the hash-bearing item


def test_verify_stale_before_on_empty_library(scrolls_home, capsys):
    exit_code = main(["verify", "--stale-before", "2099-01-01T00:00:00+00:00"])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and out["checked"] == 0


def test_verify_stale_before_malformed_boundary_is_a_loud_usage_error(paths, capsys):
    exit_code = main(["verify", "--stale-before", "yesterday"])
    assert exit_code == 2  # the export-events / maintain --trend precedent
    assert "error" in json.loads(capsys.readouterr().err)


def test_verify_stale_before_blank_boundary_is_a_usage_error(paths, capsys):
    # a blank boundary names no window — a loud usage error, not "select nothing"
    exit_code = main(["verify", "--stale-before", "   "])
    assert exit_code == 2
    assert "error" in json.loads(capsys.readouterr().err)


def test_verify_rejects_all_and_stale_before_together(paths, capsys):
    exit_code = main(["verify", "--all", "--stale-before", "2026-06-15T00:00:00+00:00"])
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


# --- posture-targeted recheck (--drift POSTURE, H80) ----------------------
#
# The recheck-side counterpart of `list --drift` (the read enumeration) and the
# verify-axis sibling of `--unverified`: re-capture only the held, hash-bearing
# items currently at a chosen drift posture, so a worker re-checks the suspect
# set (`--drift drifted` / `error` / `rotted`) instead of the whole library.


def test_verify_drift_selects_only_the_chosen_posture(paths, monkeypatch, capsys):
    drifted = _item("https://example.com/drifted", content_hash="sha256:d")
    verified = _item("https://example.com/verified", content_hash="sha256:v")
    never = _item("https://example.com/never", content_hash="sha256:n")
    for it in (drifted, verified, never):
        insert_item(paths.db_path, it)
    _seed_verdict(paths, drifted, "2026-06-10T00:00:00+00:00", status="drifted")
    _seed_verdict(paths, verified, "2026-06-10T00:00:00+00:00", status="unchanged")
    # `never` has no verdict → unverified posture
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--drift", "drifted"])
    out = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in out["results"]] == [drifted.id]


def test_verify_drift_rechecks_exactly_the_list_drift_rows(paths, monkeypatch, capsys):
    # the set --drift rechecks equals the rows `list --drift` enumerates — the
    # act-side ≡ read-side drill, via the shared `items_in_posture` selector
    a = _item("https://example.com/a", content_hash="sha256:a")
    b = _item("https://example.com/b", content_hash="sha256:b")
    insert_item(paths.db_path, a)
    insert_item(paths.db_path, b)
    _seed_verdict(paths, a, "2026-06-10T00:00:00+00:00", status="drifted")
    _seed_verdict(paths, b, "2026-06-10T00:00:00+00:00", status="unchanged")

    main(["list", "--drift", "drifted"])
    listed = {row["id"] for row in json.loads(capsys.readouterr().out)}

    _stub_recapture(monkeypatch, lambda i: i)
    main(["verify", "--drift", "drifted"])
    rechecked = {r["id"] for r in json.loads(capsys.readouterr().out)["results"]}
    assert rechecked == listed == {a.id}


def test_verify_drift_recheck_moves_the_posture(paths, monkeypatch, capsys):
    # re-checking a drifted item whose source has settled appends an `unchanged`
    # verdict, so it leaves the `drifted` bucket and enters `verified`
    item = _item("https://example.com/a", content_hash="sha256:a")
    insert_item(paths.db_path, item)
    _seed_verdict(paths, item, "2026-06-10T00:00:00+00:00", status="drifted")
    _stub_recapture(monkeypatch, lambda i: i)  # fresh hash matches the stored one

    main(["verify", "--drift", "drifted"])
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 1 and out["unchanged"] == 1

    main(["list", "--drift", "drifted"])
    assert json.loads(capsys.readouterr().out) == []  # left the drifted bucket
    main(["list", "--drift", "verified"])
    assert [r["id"] for r in json.loads(capsys.readouterr().out)] == [item.id]


def test_verify_drift_composes_with_limit(paths, monkeypatch, capsys):
    for n in range(3):
        it = _item(f"https://example.com/{n}", content_hash=f"sha256:{n}")
        insert_item(paths.db_path, it)
        _seed_verdict(paths, it, "2026-06-10T00:00:00+00:00", status="drifted")
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--drift", "drifted", "--limit", "2"])
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 2  # oldest saved first, the third left for next pass


def test_verify_drift_skips_reference_only_items(paths, monkeypatch, capsys):
    # a reference-only capture is `unverified` but has no baseline to diff, so
    # `--drift unverified` skips it like --all/--unverified/--stale-before
    insert_item(paths.db_path, _item("https://example.com/a", content_hash="sha256:a"))
    insert_item(paths.db_path, _item(
        "https://example.com/ref", content_hash=None, extracted_text=None,
        stage="detected"))
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--drift", "unverified"])
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 1  # only the hash-bearing unverified item


def test_verify_drift_empty_posture_is_a_noop(paths, monkeypatch, capsys):
    # a valid posture with no items in it re-checks nothing, no network touched
    item = _item("https://example.com/a", content_hash="sha256:a")
    insert_item(paths.db_path, item)
    _seed_verdict(paths, item, "2026-06-10T00:00:00+00:00", status="unchanged")

    def explode(_):
        raise AssertionError("recapture must not run when no item is at the posture")

    _stub_recapture(monkeypatch, explode)
    exit_code = main(["verify", "--drift", "rotted"])  # nothing is rotted
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and out["checked"] == 0


def test_verify_drift_rejects_an_unknown_posture(paths):
    # a closed vocabulary (argparse choices) — a typo is exit 2, never empty
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--drift", "drited"])
    assert excinfo.value.code == 2


def test_verify_rejects_all_and_drift_together(paths, capsys):
    exit_code = main(["verify", "--all", "--drift", "drifted"])
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


# --- per-source recheck (--source S, H125) --------------------------------
#
# The act-side of doctor/maintain's per-source custody breakdown: re-capture
# only the held, hash-bearing items from one source, so a worker re-checks the
# weakest source (named by doctor `custody.by_source` / maintain `attention`)
# without `--all` re-checking the whole library. The verify-axis sibling of
# `list --source`; an open vocabulary (sources are open-ended), so a source
# nothing is held for is an honest empty no-op, never an error.


def _arxiv_item(arxiv_id, content_hash="sha256:ax"):
    url = f"https://arxiv.org/abs/{arxiv_id}"
    return _item(
        url,
        content_hash=content_hash,
        id=make_item_id("arxiv", arxiv_id, url),
        source="arxiv",
        source_id=arxiv_id,
    )


def test_verify_source_selects_only_that_sources_items(paths, monkeypatch, capsys):
    web_a = _item("https://example.com/a", content_hash="sha256:a")
    web_b = _item("https://example.com/b", content_hash="sha256:b")
    ax = _arxiv_item("2401.00001")
    for it in (web_a, web_b, ax):
        insert_item(paths.db_path, it)
    _stub_recapture(monkeypatch, lambda i: i)

    exit_code = main(["verify", "--source", "web"])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert [r["id"] for r in out["results"]] == [web_a.id, web_b.id]


def test_verify_source_rechecks_exactly_the_list_source_hash_bearing_rows(
    paths, monkeypatch, capsys
):
    # the set --source rechecks equals `list --source S`'s held, hash-bearing
    # rows — the verify-axis ≡ read-axis drill on the source filter
    web = _item("https://example.com/a", content_hash="sha256:a")
    ax = _arxiv_item("2401.00002")
    # a reference-only web item is in `list --source web` but has no baseline
    ref = _item(
        "https://example.com/ref", content_hash=None, extracted_text=None,
        stage="detected",
    )
    for it in (web, ax, ref):
        insert_item(paths.db_path, it)

    main(["list", "--source", "web"])
    listed = json.loads(capsys.readouterr().out)
    listed_ids = {row["id"] for row in listed}
    # `list --source web` returns every web row (the source filter), including
    # the reference-only one; the held hash-bearing subset is just `web`.
    assert listed_ids == {web.id, ref.id}
    listed_hash_bearing = {row["id"] for row in listed if row["fidelity"] != "reference"}

    _stub_recapture(monkeypatch, lambda i: i)
    main(["verify", "--source", "web"])
    rechecked = {r["id"] for r in json.loads(capsys.readouterr().out)["results"]}
    assert rechecked == listed_hash_bearing == {web.id}


def test_verify_source_skips_reference_only_items(paths, monkeypatch, capsys):
    # a reference-only capture from the source has no baseline to diff, so it is
    # skipped like every other batch mode even though its source matches
    insert_item(paths.db_path, _item("https://example.com/a", content_hash="sha256:a"))
    insert_item(paths.db_path, _item(
        "https://example.com/ref", content_hash=None, extracted_text=None,
        stage="detected"))
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--source", "web"])
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 1  # only the hash-bearing web item


def test_verify_source_composes_with_limit(paths, monkeypatch, capsys):
    for n in range(3):
        insert_item(paths.db_path, _item(
            f"https://example.com/{n}", content_hash=f"sha256:{n}"))
    insert_item(paths.db_path, _arxiv_item("2401.00003"))  # other source, excluded
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--source", "web", "--limit", "2"])
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 2  # oldest saved first, the third web item left


def test_verify_source_unknown_source_is_an_empty_noop(paths, monkeypatch, capsys):
    # sources are open-ended, so an unheld source is the honest empty no-op,
    # never an error or a closed-vocabulary rejection — and no network touched
    insert_item(paths.db_path, _item("https://example.com/a", content_hash="sha256:a"))

    def explode(_):
        raise AssertionError("recapture must not run for an unheld source")

    _stub_recapture(monkeypatch, explode)
    exit_code = main(["verify", "--source", "reddit"])  # nothing held for reddit
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and out["checked"] == 0


def test_verify_source_on_empty_library(scrolls_home, capsys):
    exit_code = main(["verify", "--source", "web"])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and out["checked"] == 0


def test_verify_source_clears_that_sources_unverified_bucket(paths, monkeypatch, capsys):
    # re-verifying source S clears exactly that source's unverified count in
    # doctor's custody.by_source[S] — the per-source counterpart of how
    # --unverified clears the whole-library bucket
    web = _item("https://example.com/a", content_hash="sha256:a")
    ax = _arxiv_item("2401.00004")
    insert_item(paths.db_path, web)
    insert_item(paths.db_path, ax)
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--source", "web"])
    capsys.readouterr()

    main(["doctor"])
    report = json.loads(capsys.readouterr().out)
    by_source = report["custody"]["by_source"]
    assert by_source["web"]["drift"].get("unverified", 0) == 0  # web now covered
    assert by_source["arxiv"]["drift"]["unverified"] == 1  # arxiv untouched


def test_verify_source_id_and_source_together_is_an_error(paths, capsys):
    exit_code = main(["verify", "abc123", "--source", "web"])
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


def test_verify_rejects_all_and_source_together(paths, capsys):
    exit_code = main(["verify", "--all", "--source", "web"])
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


def test_verify_rejects_source_and_drift_together(paths, capsys):
    exit_code = main(["verify", "--source", "web", "--drift", "drifted"])
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


# --- per-fidelity recheck (--fidelity T, H252) ----------------------------
#
# The act-axis twin of `list --fidelity` / `search --fidelity` (H250/H251, the
# holdings axis): re-capture only the held items at one custody-fidelity tier
# (ADR 0097), folding the same `get_fidelity` primitive those read surfaces
# count with — no ledger read. Like every batch mode it touches only
# hash-bearing rows (a re-fetch needs a baseline hash to diff), so the set it
# re-checks is `list --fidelity T`'s held, *hash-bearing* subset. That makes it
# genuinely narrower than `list --fidelity` (a full-fidelity capture held by raw
# body alone carries no hash, so it lists `full` yet is skipped), and a tier
# holding no fingerprint at all — typically `reference` — is an honest empty
# no-op. A closed vocabulary (argparse choices): a typo is exit 2, never empty.


def _full_no_hash_item(url):
    """A full-fidelity capture held by raw body alone — no baseline to diff.

    `get_fidelity` is `full` (a re-derivable `raw_text` body at a captured
    stage), but with no `content_hash` there is nothing a re-fetch could diff,
    so it is *not* hash-bearing — in `list --fidelity full` yet skipped by
    `verify --fidelity full`, the real gap between the holdings axis and the
    verifiable subset.
    """
    return _item(url, content_hash=None, raw_text="raw body", extracted_text=None)


def _partial_hash_item(url):
    """A hash-bearing partial: an extracted body + hash at an *uncaptured* stage.

    `extracted_text` + `content_hash` would be `full` at a captured stage, but
    a `detected` stage holds it at `partial` (ADR 0097) — and it still carries a
    hash, so it is verifiable, the partial tier `verify --fidelity partial`
    acts on.
    """
    return _item(url, content_hash="sha256:p", stage="detected")


def test_verify_fidelity_selects_only_that_tier(paths, monkeypatch, capsys):
    full = _item("https://example.com/full", content_hash="sha256:f")
    partial = _partial_hash_item("https://example.com/partial")
    insert_item(paths.db_path, full)
    insert_item(paths.db_path, partial)
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--fidelity", "full"])
    assert [r["id"] for r in json.loads(capsys.readouterr().out)["results"]] == [full.id]

    main(["verify", "--fidelity", "partial"])
    out = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in out["results"]] == [partial.id]


def test_verify_fidelity_full_skips_a_full_item_without_a_baseline_hash(
    paths, monkeypatch, capsys
):
    # the distinguishing case vs --source: a full-fidelity capture held by raw
    # body alone is in `list --fidelity full` but carries no hash to diff, so
    # `verify --fidelity full` skips it like every other batch mode
    hashed = _item("https://example.com/a", content_hash="sha256:a")
    no_hash = _full_no_hash_item("https://example.com/b")
    insert_item(paths.db_path, hashed)
    insert_item(paths.db_path, no_hash)

    main(["list", "--fidelity", "full"])
    listed = {row["id"] for row in json.loads(capsys.readouterr().out)}
    assert listed == {hashed.id, no_hash.id}  # both are full fidelity

    _stub_recapture(monkeypatch, lambda i: i)
    main(["verify", "--fidelity", "full"])
    out = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in out["results"]] == [hashed.id]  # only the hash-bearing one


def test_verify_fidelity_rechecks_exactly_the_list_fidelity_hash_bearing_rows(
    paths, monkeypatch, capsys
):
    # the set --fidelity rechecks equals `list --fidelity T`'s held, hash-bearing
    # rows — the verify-axis ≡ read-axis drill on the fidelity filter (the
    # holdings-axis twin of the --source convergence)
    full_hashed = _item("https://example.com/a", content_hash="sha256:a")
    full_no_hash = _full_no_hash_item("https://example.com/b")
    partial = _partial_hash_item("https://example.com/c")  # other tier, excluded
    for it in (full_hashed, full_no_hash, partial):
        insert_item(paths.db_path, it)

    main(["list", "--fidelity", "full"])
    listed = json.loads(capsys.readouterr().out)
    assert {row["id"] for row in listed} == {full_hashed.id, full_no_hash.id}
    # the verifiable subset is those carrying a baseline hash to diff (item_summary
    # omits content_hash, so drill back through the store for the honest predicate)
    listed_hash_bearing = {
        row["id"] for row in listed if get_item(paths.db_path, row["id"]).content_hash
    }

    _stub_recapture(monkeypatch, lambda i: i)
    main(["verify", "--fidelity", "full"])
    rechecked = {r["id"] for r in json.loads(capsys.readouterr().out)["results"]}
    assert rechecked == listed_hash_bearing == {full_hashed.id}


def test_verify_fidelity_reference_is_an_empty_noop(paths, monkeypatch, capsys):
    # reference-only items hold no content to fingerprint, so the reference tier
    # has no hash-bearing rows — an honest empty no-op, no network touched
    insert_item(paths.db_path, _item("https://example.com/a", content_hash="sha256:a"))
    insert_item(paths.db_path, _item(
        "https://example.com/ref", content_hash=None, extracted_text=None,
        stage="detected"))

    def explode(_):
        raise AssertionError("recapture must not run for a tier with no baseline")

    _stub_recapture(monkeypatch, explode)
    exit_code = main(["verify", "--fidelity", "reference"])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and out["checked"] == 0


def test_verify_fidelity_records_a_verdict_for_each_checked_item(
    paths, monkeypatch, capsys
):
    # the re-check appends an append-only verdict the ledger now carries (so it
    # feeds doctor's drift report, the act half of report↔refresh)
    full = _item("https://example.com/a", content_hash="sha256:a")
    insert_item(paths.db_path, full)
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--fidelity", "full"])
    capsys.readouterr()
    assert [e.status for e in item_events(paths.db_path, full.id)] == ["unchanged"]


def test_verify_fidelity_composes_with_limit(paths, monkeypatch, capsys):
    for n in range(3):
        insert_item(paths.db_path, _item(
            f"https://example.com/{n}", content_hash=f"sha256:{n}"))
    insert_item(paths.db_path, _partial_hash_item("https://example.com/p"))  # excluded
    _stub_recapture(monkeypatch, lambda i: i)

    main(["verify", "--fidelity", "full", "--limit", "2"])
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 2  # oldest saved first, the third full item left


def test_verify_fidelity_empty_library(scrolls_home, capsys):
    exit_code = main(["verify", "--fidelity", "full"])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and out["checked"] == 0


def test_verify_fidelity_rejects_an_unknown_tier(paths):
    # a closed vocabulary (argparse choices) — a typo is exit 2, never empty
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--fidelity", "ful"])
    assert excinfo.value.code == 2


def test_verify_rejects_all_and_fidelity_together(paths, capsys):
    exit_code = main(["verify", "--all", "--fidelity", "full"])
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


def test_verify_rejects_source_and_fidelity_together(paths, capsys):
    exit_code = main(["verify", "--source", "web", "--fidelity", "full"])
    assert exit_code == 1
    assert "error" in json.loads(capsys.readouterr().err)


def test_verify_rejects_id_and_fidelity_together(paths, capsys):
    exit_code = main(["verify", "abc123", "--fidelity", "full"])
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


def _seed_three_checks(paths, item):
    insert_item(paths.db_path, item)
    record_events(paths.db_path, [
        CustodyEvent(item.id, "2026-06-13T00:00:00+00:00", "unchanged", "h", "h"),
        CustodyEvent(item.id, "2026-06-14T00:00:00+00:00", "drifted", "h", "h2"),
        CustodyEvent(item.id, "2026-06-15T00:00:00+00:00", "rotted", "h2", None, "gone"),
    ])


def test_history_limit_returns_the_most_recent_n(paths, capsys):
    item = _item("https://example.com/a", content_hash="sha256:orig")
    _seed_three_checks(paths, item)

    exit_code = main(["history", item.id, "--limit", "2"])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert [e["status"] for e in out] == ["rotted", "drifted"]  # newest 2, oldest dropped


def test_history_limit_zero_is_the_honest_empty(paths, capsys):
    item = _item("https://example.com/a", content_hash="sha256:orig")
    _seed_three_checks(paths, item)

    exit_code = main(["history", item.id, "--limit", "0"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out) == []
    assert captured.err == ""


def test_history_limit_over_count_returns_the_whole_ledger(paths, capsys):
    item = _item("https://example.com/a", content_hash="sha256:orig")
    _seed_three_checks(paths, item)

    assert main(["history", item.id, "--limit", "99"]) == 0
    capped = json.loads(capsys.readouterr().out)
    assert main(["history", item.id]) == 0  # the unbounded default
    full = json.loads(capsys.readouterr().out)

    assert capped == full
    assert len(full) == 3


# --- scrolls history <id> --since <ISO> — the time-axis ledger window (H71) --


def test_history_since_windows_to_checks_on_or_after_the_boundary(paths, capsys):
    item = _item("https://example.com/a", content_hash="sha256:orig")
    _seed_three_checks(paths, item)  # 06-13 unchanged, 06-14 drifted, 06-15 rotted

    exit_code = main(["history", item.id, "--since", "2026-06-14T00:00:00+00:00"])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    # only the 06-14 and 06-15 checks, newest first; 06-13 falls out of the window
    assert [e["status"] for e in out] == ["rotted", "drifted"]
    # the boundary is inclusive (>=): the 06-14 check exactly at it stays
    assert out[-1]["checked_at"] == "2026-06-14T00:00:00+00:00"


def test_history_since_accepts_a_date_only_boundary(paths, capsys):
    item = _item("https://example.com/a", content_hash="sha256:orig")
    _seed_three_checks(paths, item)

    # a bare date normalizes to that day's midnight UTC, so the whole day is in
    assert main(["history", item.id, "--since", "2026-06-15"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [e["status"] for e in out] == ["rotted"]


def test_history_since_composes_with_limit_window_then_cap(paths, capsys):
    item = _item("https://example.com/a", content_hash="sha256:orig")
    _seed_three_checks(paths, item)

    # window to the last two checks, then cap to the most recent one of those
    assert main(
        ["history", item.id, "--since", "2026-06-14T00:00:00+00:00", "--limit", "1"]
    ) == 0
    out = json.loads(capsys.readouterr().out)
    assert [e["status"] for e in out] == ["rotted"]


def test_history_since_empty_window_is_the_honest_empty(paths, capsys):
    item = _item("https://example.com/a", content_hash="sha256:orig")
    _seed_three_checks(paths, item)

    exit_code = main(["history", item.id, "--since", "2026-07-01T00:00:00+00:00"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out) == []  # checked-and-empty, never an error
    assert captured.err == ""


def test_history_malformed_since_is_a_loud_usage_error(paths, capsys):
    item = _item("https://example.com/a", content_hash="sha256:orig")
    _seed_three_checks(paths, item)

    exit_code = main(["history", item.id, "--since", "yesterday"])
    captured = capsys.readouterr()

    assert exit_code == 2  # usage error, the `maintain --trend` precedent
    assert captured.out == ""  # nothing emitted when the request itself is malformed
    assert "error" in json.loads(captured.err)


def test_history_malformed_since_beats_an_unknown_id(paths, capsys):
    # a malformed window is a usage error caught before the item lookup, so a
    # typo'd boundary on an unknown item is exit 2 (usage), not exit 1 (no item)
    exit_code = main(["history", "web:does-not-exist", "--since", "not-a-date"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


# --- scrolls history <id> --status <verdict> — the verdict-axis filter (H77) -


def _seed_four_verdicts(paths, item):
    insert_item(paths.db_path, item)
    record_events(paths.db_path, [
        CustodyEvent(item.id, "2026-06-13T00:00:00+00:00", "unchanged", "h", "h"),
        CustodyEvent(item.id, "2026-06-14T00:00:00+00:00", "drifted", "h", "h2"),
        CustodyEvent(item.id, "2026-06-15T00:00:00+00:00", "unchanged", "h2", "h2"),
        CustodyEvent(item.id, "2026-06-16T00:00:00+00:00", "rotted", "h2", None, "gone"),
    ])


def test_history_status_filters_to_one_verdict(paths, capsys):
    item = _item("https://example.com/a", content_hash="sha256:orig")
    _seed_four_verdicts(paths, item)

    exit_code = main(["history", item.id, "--status", "unchanged"])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    # only the two unchanged re-checks, newest first
    assert [e["checked_at"] for e in out] == [
        "2026-06-15T00:00:00+00:00", "2026-06-13T00:00:00+00:00"
    ]


def test_history_status_composes_with_since_and_limit(paths, capsys):
    item = _item("https://example.com/a", content_hash="sha256:orig")
    _seed_four_verdicts(paths, item)

    # verdict (unchanged) → window (>= 06-14) → cap (1): only the 06-15 unchanged
    assert main([
        "history", item.id, "--status", "unchanged",
        "--since", "2026-06-14T00:00:00+00:00", "--limit", "1",
    ]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [e["checked_at"] for e in out] == ["2026-06-15T00:00:00+00:00"]


def test_history_status_no_match_is_the_honest_empty(paths, capsys):
    item = _item("https://example.com/a", content_hash="sha256:orig")
    _seed_four_verdicts(paths, item)  # no `error` verdict in the ledger

    exit_code = main(["history", item.id, "--status", "error"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out) == []
    assert captured.err == ""


def test_history_status_is_a_closed_vocabulary(paths, capsys):
    item = _item("https://example.com/a", content_hash="sha256:orig")
    _seed_four_verdicts(paths, item)

    # `verified` is a reader-facing posture, not a raw event status — argparse
    # rejects it with the usage exit code, never a silent empty
    with pytest.raises(SystemExit) as excinfo:
        main(["history", item.id, "--status", "verified"])
    assert excinfo.value.code == 2
