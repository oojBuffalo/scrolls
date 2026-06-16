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
    event_export_dict,
    event_from_dict,
    event_payload,
    events_for_items,
    import_events,
    item_events,
    item_history,
    items_checked_before,
    items_in_posture,
    latest_events,
    live_recapture,
    parse_since,
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


def test_event_payload_is_the_five_field_read_shape():
    # the per-event read shape behind `scrolls history` (H66): the item id is
    # omitted (history is scoped to one item), so only the five per-check fields
    event = CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "rotted", "h1", None, "gone")
    assert event_payload(event) == {
        "checked_at": "2026-06-15T00:00:00+00:00",
        "status": "rotted",
        "prior_hash": "h1",
        "observed_hash": None,
        "detail": "gone",
    }


def test_item_history_is_the_serialized_ledger_newest_first(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    record_events(db_path, [
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "unchanged", "h1", "h1"),
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "drifted", "h1", "h2"),
    ])
    history = item_history(db_path, "web:a")
    assert [e["status"] for e in history] == ["drifted", "unchanged"]  # newest first
    # equals item_events mapped through event_payload — the surfaces share it
    assert history == [event_payload(e) for e in item_events(db_path, "web:a")]


def test_item_history_of_a_never_checked_item_is_empty(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    assert item_history(db_path, "web:never") == []


def test_item_history_limit_returns_the_most_recent_n(tmp_path):
    # H69: a maintenance worker appends a verdict per pass; --limit reads the head
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    record_events(db_path, [
        CustodyEvent("web:a", "2026-06-13T00:00:00+00:00", "unchanged", "h", "h"),
        CustodyEvent("web:a", "2026-06-14T00:00:00+00:00", "drifted", "h", "h2"),
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "rotted", "h2", None, "gone"),
    ])
    # newest first, capped to the 2 most recent — oldest (unchanged) dropped
    assert [e["status"] for e in item_history(db_path, "web:a", limit=2)] == [
        "rotted", "drifted"
    ]
    # limit 0 is the honest empty; an over-count returns all; None is unbounded
    assert item_history(db_path, "web:a", limit=0) == []
    assert len(item_history(db_path, "web:a", limit=99)) == 3
    assert item_history(db_path, "web:a", limit=None) == item_history(db_path, "web:a")


# --- parse_since: the shared --since window normalizer/validator (H71/H75) ---


def test_parse_since_normalizes_to_the_stored_utc_iso_shape():
    # no window asked for (the default and an explicit blank both mean "no window")
    assert parse_since(None) is None
    assert parse_since("") is None
    assert parse_since("   ") is None
    # the stored `checked_at` vocabulary: isoformat(timespec="seconds") in +00:00
    assert parse_since("2026-06-15T12:00:00+00:00") == "2026-06-15T12:00:00+00:00"
    # a Z suffix and a date-only boundary both normalize to that shape, so the
    # downstream `checked_at >=` compare is apples-to-apples, not a string accident
    assert parse_since("2026-06-15T12:00:00Z") == "2026-06-15T12:00:00+00:00"
    assert parse_since("2026-06-15") == "2026-06-15T00:00:00+00:00"


def test_parse_since_rejects_a_malformed_boundary():
    # a non-blank value that is not a timestamp is a loud usage error, never a
    # silently-empty window that could mask a typo
    with pytest.raises(ValueError):
        parse_since("yesterday")
    with pytest.raises(ValueError):
        parse_since("not-a-date")


def test_item_history_since_windows_to_on_or_after(tmp_path):
    # H71: the time-axis sibling of --limit — "what has this source done since X"
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    record_events(db_path, [
        CustodyEvent("web:a", "2026-06-13T00:00:00+00:00", "unchanged", "h", "h"),
        CustodyEvent("web:a", "2026-06-14T00:00:00+00:00", "drifted", "h", "h2"),
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "rotted", "h2", None, "gone"),
    ])
    # only checks at or after the boundary survive — newest first, oldest dropped
    windowed = item_history(db_path, "web:a", since="2026-06-14T00:00:00+00:00")
    assert [e["status"] for e in windowed] == ["rotted", "drifted"]
    # the boundary is inclusive (>=, not >): a check exactly at the boundary stays
    assert windowed[-1]["checked_at"] == "2026-06-14T00:00:00+00:00"
    # None is the whole unwindowed ledger
    assert item_history(db_path, "web:a", since=None) == item_history(db_path, "web:a")


def test_item_history_since_composes_with_limit_window_then_cap(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    record_events(db_path, [
        CustodyEvent("web:a", "2026-06-13T00:00:00+00:00", "unchanged", "h", "h"),
        CustodyEvent("web:a", "2026-06-14T00:00:00+00:00", "drifted", "h", "h2"),
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "rotted", "h2", None, "gone"),
    ])
    # window to the last two checks, then cap to the most recent one of those
    capped = item_history(
        db_path, "web:a", since="2026-06-14T00:00:00+00:00", limit=1
    )
    assert [e["status"] for e in capped] == ["rotted"]


def test_item_history_since_empty_window_is_honest_empty(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    record_events(db_path, [
        CustodyEvent("web:a", "2026-06-13T00:00:00+00:00", "unchanged", "h", "h"),
    ])
    # nothing falls in the window — checked-and-empty, never an error
    assert item_history(db_path, "web:a", since="2026-07-01T00:00:00+00:00") == []


def test_item_history_status_filters_to_one_verdict(tmp_path):
    # H77: the verdict axis — "only the times this source actually changed"
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    record_events(db_path, [
        CustodyEvent("web:a", "2026-06-13T00:00:00+00:00", "unchanged", "h", "h"),
        CustodyEvent("web:a", "2026-06-14T00:00:00+00:00", "drifted", "h", "h2"),
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "unchanged", "h2", "h2"),
        CustodyEvent("web:a", "2026-06-16T00:00:00+00:00", "rotted", "h2", None, "gone"),
    ])
    # only the drifted check survives the verdict filter
    drifted = item_history(db_path, "web:a", status="drifted")
    assert [e["checked_at"] for e in drifted] == ["2026-06-14T00:00:00+00:00"]
    # a verdict nothing matches is the honest empty, never an error
    assert item_history(db_path, "web:a", status="error") == []
    # None keeps the whole ledger
    assert item_history(db_path, "web:a", status=None) == item_history(db_path, "web:a")


def test_item_history_status_composes_verdict_then_window_then_cap(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    record_events(db_path, [
        CustodyEvent("web:a", "2026-06-13T00:00:00+00:00", "drifted", "h", "h1"),
        CustodyEvent("web:a", "2026-06-14T00:00:00+00:00", "unchanged", "h1", "h1"),
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "drifted", "h1", "h2"),
        CustodyEvent("web:a", "2026-06-16T00:00:00+00:00", "drifted", "h2", "h3"),
    ])
    # verdict (drifted) → window (>= 06-14) → cap (1): the two drifts in window
    # are 06-15 and 06-16; newest-first cap to 1 keeps 06-16
    out = item_history(
        db_path, "web:a", status="drifted", since="2026-06-14T00:00:00+00:00", limit=1
    )
    assert [e["checked_at"] for e in out] == ["2026-06-16T00:00:00+00:00"]


def test_item_history_rejects_an_unknown_status(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    # a closed vocabulary — never a silent empty (the `list --drift` posture);
    # note `verified` is a reader-facing *posture*, not a raw event *status*
    with pytest.raises(ValueError):
        item_history(db_path, "web:a", status="verified")
    with pytest.raises(ValueError):
        item_history(db_path, "web:a", status="nonsense")


def test_events_for_items_since_windows_within_the_id_scope(tmp_path):
    # H75: the incremental-backup window over the export read, after id scoping
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    record_events(db_path, [
        CustodyEvent("web:a", "2026-06-13T00:00:00+00:00", "unchanged", "h", "h"),
        CustodyEvent("web:b", "2026-06-14T00:00:00+00:00", "drifted", "h", "h2"),
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "drifted", "h", "h3"),
    ])
    scoped = events_for_items(
        db_path, ["web:a"], since="2026-06-14T00:00:00+00:00"
    )
    # only web:a's events (id scope) that are at/after the boundary (time window)
    assert [(e.item_id, e.checked_at) for e in scoped] == [
        ("web:a", "2026-06-15T00:00:00+00:00")
    ]
    # None (the bundle/H72 callers' value) exports the whole scoped ledger
    assert events_for_items(db_path, ["web:a"], since=None) == events_for_items(
        db_path, ["web:a"]
    )
    # an empty window over a non-empty scope is an empty read, never a crash
    assert events_for_items(db_path, ["web:a"], since="2026-08-01T00:00:00+00:00") == []


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


# --- items_checked_before selector (the `verify --stale-before` act window) --


def test_items_checked_before_selects_verdicts_strictly_before_the_boundary():
    a, b, c = _item("web:a"), _item("web:b"), _item("web:c")
    verdicts = {
        "web:a": CustodyEvent("web:a", "2026-06-10T00:00:00+00:00", "unchanged", "h", "h"),
        "web:b": CustodyEvent("web:b", "2026-06-20T00:00:00+00:00", "unchanged", "h", "h"),
        # web:c has no verdict → never checked → trivially stale
    }
    boundary = "2026-06-15T00:00:00+00:00"
    # web:a (checked before) and web:c (never checked) are stale; web:b is fresh
    assert items_checked_before([a, b, c], verdicts, boundary) == [a, c]


def test_items_checked_before_treats_an_at_boundary_check_as_fresh():
    # the boundary itself is fresh — the exact complement of the `>= boundary`
    # window `history --since` / `export events --since` keep (predates = `<`)
    a = _item("web:a")
    boundary = "2026-06-15T00:00:00+00:00"
    verdicts = {"web:a": CustodyEvent("web:a", boundary, "unchanged", "h", "h")}
    assert items_checked_before([a], verdicts, boundary) == []


def test_items_checked_before_never_checked_is_trivially_stale():
    # an item the ledger has no verdict for is stale at any boundary
    items = [_item("web:a"), _item("web:b")]
    assert items_checked_before(items, {}, "2000-01-01T00:00:00+00:00") == items


def test_items_checked_before_with_a_future_boundary_subsumes_unverified():
    # a far-future boundary makes every verdict "before" it, so the stale set is
    # everything — a superset of the never-checked `unverified_items` set
    a, b, c = _item("web:a"), _item("web:b"), _item("web:c")
    verdicts = {
        "web:a": CustodyEvent("web:a", "2026-06-10T00:00:00+00:00", "unchanged", "h", "h"),
        "web:b": CustodyEvent("web:b", "2026-06-12T00:00:00+00:00", "drifted", "h", "x"),
    }
    future = "2099-01-01T00:00:00+00:00"
    stale = items_checked_before([a, b, c], verdicts, future)
    assert stale == [a, b, c]
    # ⊇ the never-checked set
    stale_ids = {i.id for i in stale}
    assert all(i.id in stale_ids for i in unverified_items([a, b, c], verdicts))


def test_items_checked_before_preserves_input_order():
    items = [_item(f"web:{n}") for n in range(4)]  # all never checked → all stale
    boundary = "2026-06-15T00:00:00+00:00"
    assert [i.id for i in items_checked_before(items, {}, boundary)] == [
        "web:0", "web:1", "web:2", "web:3"
    ]


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


# --- portable custody: export/import the ledger (roadmap H67) ---------------


def test_event_export_dict_includes_the_item_id():
    # the bundle-export shape carries item_id (the block spans many items),
    # unlike event_payload (the per-item `history` shape, which omits it)
    event = CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "rotted", "h1", None, "gone")
    assert event_export_dict(event) == {
        "item_id": "web:a",
        "checked_at": "2026-06-15T00:00:00+00:00",
        "status": "rotted",
        "prior_hash": "h1",
        "observed_hash": None,
        "detail": "gone",
    }
    # round-trips through event_from_dict (the autoincrement id is not exported)
    assert event_from_dict(event_export_dict(event)) == event


def test_event_from_dict_tolerates_unknown_keys():
    data = {
        "item_id": "web:a", "checked_at": "2026-06-15T00:00:00+00:00",
        "status": "unchanged", "prior_hash": "h", "observed_hash": "h",
        "detail": None, "id": 7, "future_field": "ignored",
    }
    assert event_from_dict(data) == CustodyEvent(
        "web:a", "2026-06-15T00:00:00+00:00", "unchanged", "h", "h", None
    )


def test_events_for_items_scopes_to_the_id_set_in_append_order(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    record_events(db_path, [
        CustodyEvent("web:a", "2026-06-13T00:00:00+00:00", "unchanged", "h", "h"),
        CustodyEvent("web:b", "2026-06-14T00:00:00+00:00", "drifted", "h", "h2"),
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "drifted", "h", "h3"),
    ])
    # only the requested items, in the append (chronological/id) order
    scoped = events_for_items(db_path, ["web:a"])
    assert [(e.item_id, e.status) for e in scoped] == [
        ("web:a", "unchanged"), ("web:a", "drifted")
    ]
    # empty id set is an empty read, never the whole ledger
    assert events_for_items(db_path, []) == []


def test_events_for_items_tolerates_a_pre_v7_library(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute("DROP TABLE custody_events")
    conn.close()
    assert events_for_items(db_path, ["web:a"]) == []


def test_import_events_restores_into_a_fresh_ledger(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    events = [
        CustodyEvent("web:a", "2026-06-13T00:00:00+00:00", "unchanged", "h", "h"),
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "drifted", "h", "h2"),
    ]
    assert import_events(db_path, events) == (2, 0)
    # newest-first read back, and the latest verdict is the chronologically-latest
    assert [e.status for e in item_events(db_path, "web:a")] == ["drifted", "unchanged"]
    assert latest_events(db_path)["web:a"].status == "drifted"


def test_import_events_dedups_by_content_so_re_import_is_a_no_op(tmp_path):
    # the idempotent-restore key: same (item_id, checked_at, status, prior, observed)
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    events = [
        CustodyEvent("web:a", "2026-06-13T00:00:00+00:00", "unchanged", "h", "h"),
        CustodyEvent("web:b", "2026-06-14T00:00:00+00:00", "drifted", "h", "h2", "moved"),
    ]
    assert import_events(db_path, events) == (2, 0)
    # a second import of the same events adds nothing — a custody no-op
    assert import_events(db_path, events) == (0, 2)
    # the ledger did not grow
    conn = sqlite3.connect(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM custody_events").fetchone()[0]
    finally:
        conn.close()
    assert total == 2


def test_import_events_dedup_ignores_the_id_and_detail(tmp_path):
    # detail is not part of the identity: a same-check row with a different
    # detail message still dedups (the 5-tuple identifies the check)
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    import_events(db_path, [
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "error", "h", None, "timeout"),
    ])
    again = import_events(db_path, [
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "error", "h", None, "different message"),
    ])
    assert again == (0, 1)


def test_import_events_orders_inserts_by_checked_at_for_correct_recency(tmp_path):
    # an out-of-order block still yields the chronologically-latest posture: the
    # restore sorts by checked_at before appending, so latest_events is correct
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    import_events(db_path, [
        CustodyEvent("web:a", "2026-06-15T00:00:00+00:00", "drifted", "h", "h2"),
        CustodyEvent("web:a", "2026-06-13T00:00:00+00:00", "unchanged", "h", "h"),
    ])
    assert latest_events(db_path)["web:a"].status == "drifted"


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
