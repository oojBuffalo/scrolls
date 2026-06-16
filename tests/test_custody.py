"""Tests for custody drift/rot detection (ADR 0098).

`verify_item` re-captures a stored item, compares the fresh content hash to
the stored one, and returns a `CustodyEvent` verdict — ``unchanged`` /
``drifted`` / ``rotted`` / ``error`` — without ever writing the item. The
verdict is pure given an injected `recapture`, so the whole taxonomy is
exercised offline here; the ledger (`record_events` / `latest_events` /
`item_events`) is the append-only store doctor aggregates.
"""

import sqlite3
import urllib.error

import pytest

import scrolls.custody as custody
from scrolls.custody import (
    CustodyEvent,
    item_events,
    items_in_posture,
    latest_events,
    live_recapture,
    record_events,
    unverified_items,
    verify_item,
)
from scrolls.db import init_db
from scrolls.items import ScrollItem
from scrolls.sources import FetchError


def _item(item_id="web:a", content_hash="sha256:orig", **overrides):
    fields = {
        "id": item_id,
        "source": "web",
        "source_id": None,
        "url": "https://example.com/a",
        "saved_at": "2026-06-12T08:00:00+00:00",
        "content_hash": content_hash,
        "extracted_text": "captured body",
        "stage": "rendered",
    }
    fields.update(overrides)
    return ScrollItem(**fields)


def _gone_fetch_error(code):
    """A FetchError whose cause is a real urllib HTTPError, like adapters raise."""
    http_error = urllib.error.HTTPError(
        "https://example.com/a", code, "gone", {}, None
    )
    try:
        raise FetchError("web request failed") from http_error
    except FetchError as exc:
        return exc


# --- verify_item verdicts (pure, network-free) ---------------------------


def test_matching_hash_is_unchanged():
    item = _item(content_hash="sha256:same")

    def recapture(_):
        return _item(content_hash="sha256:same")

    event = verify_item(item, recapture, now="2026-06-15T00:00:00+00:00")
    assert event.status == "unchanged"
    assert event.prior_hash == "sha256:same"
    assert event.observed_hash == "sha256:same"
    assert event.detail is None
    assert event.checked_at == "2026-06-15T00:00:00+00:00"


def test_differing_hash_is_drifted():
    item = _item(content_hash="sha256:old")

    def recapture(_):
        return _item(content_hash="sha256:new")

    event = verify_item(item, recapture, now="2026-06-15T00:00:00+00:00")
    assert event.status == "drifted"
    assert event.prior_hash == "sha256:old"
    assert event.observed_hash == "sha256:new"


def test_http_404_is_rotted():
    item = _item()

    def recapture(_):
        raise _gone_fetch_error(404)

    event = verify_item(item, recapture, now="2026-06-15T00:00:00+00:00")
    assert event.status == "rotted"
    assert event.observed_hash is None
    assert event.prior_hash == "sha256:orig"
    assert "web request failed" in event.detail


def test_http_410_is_rotted():
    def recapture(_):
        raise _gone_fetch_error(410)

    event = verify_item(_item(), recapture, now="2026-06-15T00:00:00+00:00")
    assert event.status == "rotted"


def test_transient_failure_is_error_not_rot():
    # a 503 / timeout is "could not check now", never a custody verdict of rot
    def recapture(_):
        raise _gone_fetch_error(503)

    event = verify_item(_item(), recapture, now="2026-06-15T00:00:00+00:00")
    assert event.status == "error"
    assert event.observed_hash is None


def test_failure_without_http_cause_is_error():
    def recapture(_):
        raise FetchError("could not extract article text")

    event = verify_item(_item(), recapture, now="2026-06-15T00:00:00+00:00")
    assert event.status == "error"


def test_verify_never_writes_the_item(tmp_path):
    # the core custody property: detecting drift must not destroy the capture
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    from scrolls.items import get_item, insert_item

    original = _item(content_hash="sha256:old")
    insert_item(db_path, original)

    def recapture(_):
        return _item(content_hash="sha256:new", extracted_text="rewritten body")

    verify_item(original, recapture, now="2026-06-15T00:00:00+00:00")
    stored = get_item(db_path, original.id)
    assert stored == original  # untouched: still the original capture


# --- live_recapture (the network edge) ------------------------------------


def test_live_recapture_without_adapter_is_a_fetch_error():
    item = _item(source="nosuchsource")
    with pytest.raises(FetchError, match="no fetch adapter"):
        live_recapture(item)


def test_live_recapture_routes_to_the_source_adapter(monkeypatch):
    captured = {}

    def fake_adapter(item):
        captured["called"] = item.id
        return _item(content_hash="sha256:fresh")

    monkeypatch.setitem(custody.FETCH_ADAPTERS, "web", fake_adapter)
    result = live_recapture(_item())
    assert captured["called"] == "web:a"
    assert result.content_hash == "sha256:fresh"


# --- ledger persistence ---------------------------------------------------


def test_record_and_read_back_events(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    events = [
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "unchanged", "h1", "h1"),
        CustodyEvent("web:b", "2026-06-15T00:00:00+00:00", "drifted", "h2", "h3"),
    ]
    assert record_events(db_path, events) == 2

    a_history = item_events(db_path, "web:a")
    assert [e.status for e in a_history] == ["unchanged"]
    assert a_history[0].prior_hash == "h1"


def test_record_empty_is_a_noop(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    assert record_events(db_path, []) == 0


def test_item_events_are_newest_first(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    record_events(db_path, [
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "unchanged", "h1", "h1"),
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "drifted", "h1", "h2"),
    ])
    history = item_events(db_path, "web:a")
    assert [e.status for e in history] == ["drifted", "unchanged"]


def test_latest_events_takes_the_most_recent_per_item(tmp_path):
    # same-second checks: the monotonic id, not checked_at, picks the latest
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    same_second = "2026-06-15T00:00:00+00:00"
    record_events(db_path, [
        CustodyEvent("web:a", same_second, "unchanged", "h1", "h1"),
        CustodyEvent("web:a", same_second, "drifted", "h1", "h2"),
        CustodyEvent("web:b", same_second, "rotted", "h3", None, "gone"),
    ])
    latest = latest_events(db_path)
    assert set(latest) == {"web:a", "web:b"}
    assert latest["web:a"].status == "drifted"  # the later same-second event
    assert latest["web:b"].status == "rotted"


def test_latest_events_empty_ledger(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    assert latest_events(db_path) == {}


# --- unverified_items predicate (held − verdicts) ------------------------


def test_unverified_items_returns_held_without_a_verdict():
    a, b, c = _item("web:a"), _item("web:b"), _item("web:c")
    verdicts = {"web:b": CustodyEvent("web:b", "t", "unchanged", "h", "h")}
    assert unverified_items([a, b, c], verdicts) == [a, c]


def test_unverified_items_empty_ledger_is_all_held():
    items = [_item("web:a"), _item("web:b")]
    assert unverified_items(items, {}) == items


def test_unverified_items_preserves_input_order_for_an_oldest_first_limit():
    items = [_item(f"web:{n}") for n in range(4)]
    verdicts = {"web:1": CustodyEvent("web:1", "t", "unchanged", "h", "h")}
    # order is preserved (web:0, web:2, web:3), so a caller can bound the
    # oldest-saved-first slice with a limit
    assert [i.id for i in unverified_items(items, verdicts)] == ["web:0", "web:2", "web:3"]


# --- items_in_posture selector (the `list --drift` read-side selection) ---


def test_items_in_posture_selects_one_posture():
    a, b, c = _item("web:a"), _item("web:b"), _item("web:c")
    verdicts = {
        "web:a": CustodyEvent("web:a", "t", "unchanged", "h", "h"),
        "web:b": CustodyEvent("web:b", "t", "drifted", "h", "x"),
        # web:c has no verdict → unverified
    }
    # `unchanged` reads back as the `verified` posture (the documented mapping)
    assert items_in_posture([a, b, c], verdicts, "verified") == [a]
    assert items_in_posture([a, b, c], verdicts, "drifted") == [b]
    assert items_in_posture([a, b, c], verdicts, "unverified") == [c]


def test_items_in_posture_unverified_equals_unverified_items():
    # the verify-axis selection is the same set as the `unverified` posture bucket
    items = [_item(f"web:{n}") for n in range(4)]
    verdicts = {"web:1": CustodyEvent("web:1", "t", "unchanged", "h", "h")}
    assert items_in_posture(items, verdicts, "unverified") == unverified_items(
        items, verdicts
    )


def test_items_in_posture_preserves_input_order():
    items = [_item(f"web:{n}") for n in range(4)]
    verdicts = {
        f"web:{n}": CustodyEvent(f"web:{n}", "t", "drifted", "h", "x") for n in range(4)
    }
    assert [i.id for i in items_in_posture(items, verdicts, "drifted")] == [
        "web:0", "web:1", "web:2", "web:3"
    ]


def test_items_in_posture_is_honestly_empty_when_no_item_matches():
    # a valid posture with no items in it is [], not an error
    items = [_item("web:a")]  # never verified → unverified
    assert items_in_posture(items, {}, "drifted") == []


def test_ledger_reads_tolerate_a_pre_v7_library(tmp_path):
    # a v6 library never migrated to v7 has no custody_events table; a
    # read-only consumer (doctor's drift report) must see an empty ledger,
    # not crash
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute("DROP TABLE custody_events")
    conn.close()

    assert latest_events(db_path) == {}
    assert item_events(db_path, "web:a") == []


def test_ledger_is_append_only_history(tmp_path):
    # re-verifying the same item never overwrites — every check is kept
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    for status in ("unchanged", "unchanged", "drifted"):
        record_events(db_path, [
            CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", status, "h1", "h1"),
        ])
    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM custody_events WHERE item_id = 'web:a'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 3
