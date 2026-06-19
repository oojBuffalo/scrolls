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
    custody_counts,
    custody_counts_by_source,
    custody_headline,
    custody_sections,
    custody_source_breakdown,
    event_export_dict,
    event_from_dict,
    event_payload,
    events_for_items,
    import_events,
    item_events,
    item_history,
    items_checked_before,
    items_in_posture,
    last_checked,
    latest_events,
    live_recapture,
    parse_since,
    recheck_coverage,
    recheck_order,
    record_events,
    render_custody_by_source,
    render_custody_headline,
    render_custody_refresh,
    tally_custody,
    tally_custody_by_source,
    unverified_items,
    verify_item,
    weakest_source,
)
from scrolls.db import init_db
from scrolls.items import ScrollItem, get_fidelity
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


# --- last_checked primitive (the time axis of the per-item picture, H84) ---


def test_last_checked_reports_the_verdicts_timestamp():
    # the time-axis sibling of drift_posture: it reports *when* the latest
    # verdict was taken, verbatim from the event's checked_at.
    event = CustodyEvent("web:a", "2026-06-14T09:30:00+00:00", "drifted", "h", "h2")
    assert last_checked(event) == "2026-06-14T09:30:00+00:00"


def test_last_checked_is_none_when_never_verified():
    # no verdict ⇒ no timestamp — the null counterpart of drift_posture(None)'s
    # `unverified` posture, never a fabricated wall-clock time (honest absence).
    assert last_checked(None) is None


# --- tally_custody / custody_counts (the scope tally core, roadmap H98) ---


def test_tally_custody_folds_pairs_into_the_canonical_shape():
    # the shape-and-count core: every tier/posture present in canonical order with
    # zeros included, so a renderer can filter a stable shape (roadmap H98).
    counts = tally_custody([
        ("full", "verified"), ("full", "drifted"),
        ("partial", "unverified"), ("reference", "unverified"),
    ])
    assert counts == {
        "tiers": {"full": 2, "partial": 1, "reference": 1},
        "drift": {"verified": 1, "unverified": 2, "drifted": 1, "rotted": 0, "error": 0},
    }
    # the tier and posture sections each sum to the number of pairs
    assert sum(counts["tiers"].values()) == 4
    assert sum(counts["drift"].values()) == 4


def test_tally_custody_empty_is_the_zeroed_shape():
    # no pairs → all-zero counts (the honest empty scope the --stats envelope and
    # the empty-library `list` path both lean on), shape still stable.
    counts = tally_custody([])
    assert counts == {
        "tiers": {"full": 0, "partial": 0, "reference": 0},
        "drift": {"verified": 0, "unverified": 0, "drifted": 0, "rotted": 0, "error": 0},
    }


def test_custody_counts_delegates_to_tally_over_item_derived_pairs():
    # custody_counts(items, verdicts) must equal tally_custody over the same
    # (get_fidelity, drift_posture) pairs it derives — the one source of truth, so
    # the item-sourced tally and the hit-sourced one (search --stats) agree.
    full = _item("web:full", content_hash="h", extracted_text="b", raw_text="<r>b</r>")
    ref = _item("web:ref", content_hash=None, extracted_text=None, raw_text=None,
                stage="detected")
    items = [full, ref]
    verdicts = {"web:full": CustodyEvent("web:full", "t", "drifted", "h", "x")}
    expected = tally_custody([
        (get_fidelity(item), custody.drift_posture(verdicts.get(item.id)))
        for item in items
    ])
    assert custody_counts(items, verdicts) == expected
    # sanity: the fixture spans two tiers and two postures
    assert expected["tiers"]["full"] == 1 and expected["tiers"]["reference"] == 1
    assert expected["drift"]["drifted"] == 1 and expected["drift"]["unverified"] == 1


# --- tally_custody_by_source (the pairs-based per-source split, roadmap H155) ---


def test_tally_custody_by_source_groups_triples_with_sorted_keys():
    # the `by_source` analogue of `tally_custody`: one `{tiers, drift}` tally per
    # source over already-derived (source, fidelity, drift) triples, keys sorted.
    by_source = tally_custody_by_source([
        ("web", "full", "verified"),
        ("arxiv", "full", "unverified"),
        ("web", "reference", "drifted"),
    ])
    assert list(by_source) == ["arxiv", "web"]  # sorted
    assert by_source["web"]["tiers"] == {"full": 1, "partial": 0, "reference": 1}
    assert by_source["web"]["drift"]["verified"] == 1
    assert by_source["web"]["drift"]["drifted"] == 1
    assert by_source["arxiv"]["tiers"] == {"full": 1, "partial": 0, "reference": 0}
    assert by_source["arxiv"]["drift"]["unverified"] == 1


def test_tally_custody_by_source_empty_is_the_honest_empty_map():
    # no triples → the empty `{}` map (the honest-empty scope the --stats envelope
    # and the empty `works`/`related` paths lean on), not a zeroed single entry.
    assert tally_custody_by_source([]) == {}


def test_tally_custody_by_source_carries_only_tiers_and_drift_not_coverage():
    # the lean browse-stats shape (H98–H101): each source entry is exactly the
    # `tally_custody` `{tiers, drift}` — *not* the per-source `coverage`
    # `custody_counts_by_source` adds (coverage needs content_hash presence, which a
    # (fidelity, drift) pair cannot recover), so it stays an audit/maintenance axis.
    by_source = tally_custody_by_source([("web", "full", "verified")])
    assert set(by_source["web"]) == {"tiers", "drift"}
    assert "coverage" not in by_source["web"]


def test_tally_custody_by_source_sums_to_the_whole_tally():
    # the load-bearing convergence: summing the per-source tallies re-counts the
    # whole iterable, so by_source can never disagree with `tally_custody` over the
    # same pairs (the H104 sum-to-whole posture, per the matched scope).
    triples = [
        ("web", "full", "verified"),
        ("web", "partial", "unverified"),
        ("arxiv", "full", "drifted"),
        ("arxiv", "reference", "unverified"),
    ]
    whole = tally_custody((fidelity, drift) for _, fidelity, drift in triples)
    by_source = tally_custody_by_source(triples)

    summed_tiers = {tier: 0 for tier in ("full", "partial", "reference")}
    summed_drift = {p: 0 for p in ("verified", "unverified", "drifted", "rotted", "error")}
    for counts in by_source.values():
        for tier, n in counts["tiers"].items():
            summed_tiers[tier] += n
        for posture, n in counts["drift"].items():
            summed_drift[posture] += n
    assert summed_tiers == whole["tiers"]
    assert summed_drift == whole["drift"]


def test_tally_custody_by_source_matches_custody_counts_by_source_on_tiers_drift():
    # the pairs-based split agrees with the items+ledger split (`custody_counts_by_
    # source`) on the tiers/drift axes — the two ways the per-source picture is
    # sourced (browse hits vs. doctor's held items) read one number, so the H155
    # browse `by_source` converges with doctor's for the same scope.
    full = _item("web:full", content_hash="h", extracted_text="b", raw_text="<r>b</r>")
    ref = _item("arxiv:ref", source="arxiv", content_hash=None, extracted_text=None,
                raw_text=None, stage="detected")
    items = [full, ref]
    verdicts = {"web:full": CustodyEvent("web:full", "t", "drifted", "h", "x")}
    item_based = custody_counts_by_source(items, verdicts)
    pairs_based = tally_custody_by_source(
        (item.source, get_fidelity(item), custody.drift_posture(verdicts.get(item.id)))
        for item in items
    )
    assert set(item_based) == set(pairs_based) == {"arxiv", "web"}
    for source in item_based:
        assert pairs_based[source]["tiers"] == item_based[source]["tiers"]
        assert pairs_based[source]["drift"] == item_based[source]["drift"]


# --- weakest_source include_coverage (the lean browse-stats flag, roadmap H174) ---


def _by_source_with_coverage():
    """A coverage-bearing per-source map (the `custody_counts_by_source` shape) with
    `web` the unambiguous max-loss source (2 drifted vs arxiv's 0)."""
    return {
        "arxiv": {
            "tiers": {"full": 1, "partial": 0, "reference": 0},
            "drift": {"verified": 1, "unverified": 0, "drifted": 0, "rotted": 0, "error": 0},
            "coverage": {"verified": 1, "total": 1},
        },
        "web": {
            "tiers": {"full": 2, "partial": 0, "reference": 0},
            "drift": {"verified": 0, "unverified": 0, "drifted": 2, "rotted": 0, "error": 0},
            "coverage": {"verified": 2, "total": 2},
        },
    }


def test_weakest_source_default_keeps_coverage():
    # the coverage-bearing surfaces (status/maintain/doctor/graph) feed a
    # `custody_counts_by_source` map, so the flag rides the per-source coverage along
    # (H153) — the default, unchanged.
    flag = weakest_source(_by_source_with_coverage())
    assert flag["source"] == "web"
    assert flag["coverage"] == {"verified": 2, "total": 2}
    assert set(flag) == {"source", "tiers", "drift", "coverage", "reason", "command"}


def test_weakest_source_lean_omits_coverage():
    # roadmap H174: the lean browse-stats family (search/list/related/works --stats)
    # passes `include_coverage=False` so the flag *omits* coverage rather than emit a
    # fabricated `0/0` — the honest lean projection for a lean (`tally_custody_by_
    # source`) map. Every other field is identical to the coverage-bearing flag.
    by_source = _by_source_with_coverage()
    lean = weakest_source(by_source, include_coverage=False)
    full = weakest_source(by_source)
    assert set(lean) == {"source", "tiers", "drift", "reason", "command"}
    assert "coverage" not in lean
    # convergent on every shared field — same source, same tally, same command
    assert {k: v for k, v in full.items() if k != "coverage"} == lean


def test_weakest_source_lean_over_a_coverageless_map_does_not_fabricate_zero():
    # the real browse case: a `tally_custody_by_source` map carries no `coverage` key
    # at all. The lean flag omits coverage (no `0/0` masquerading as "nothing
    # checked"); the gates (single-source/clean) are unchanged.
    lean_map = tally_custody_by_source([
        ("arxiv", "full", "verified"),
        ("web", "full", "drifted"),
        ("web", "full", "drifted"),
    ])
    assert all("coverage" not in entry for entry in lean_map.values())
    flag = weakest_source(lean_map, include_coverage=False)
    assert flag["source"] == "web"
    assert "coverage" not in flag


def test_weakest_source_lean_honest_absence_gates_unchanged():
    # `include_coverage=False` only governs the coverage member — the three honest-
    # absence gates (empty / single-source / fully-clean) are untouched.
    assert weakest_source({}, include_coverage=False) is None  # empty
    one = tally_custody_by_source([("web", "full", "drifted")])
    assert weakest_source(one, include_coverage=False) is None  # single source
    clean = tally_custody_by_source([
        ("web", "full", "verified"), ("arxiv", "full", "unverified")])
    assert weakest_source(clean, include_coverage=False) is None  # no actionable loss


# --- custody_counts_by_source (the per-source split, roadmap H104) ---


def _src(item_id, source, **overrides):
    return _item(item_id, source=source, url=f"https://example.com/{item_id}",
                 **overrides)


def test_custody_counts_by_source_groups_by_source_with_sorted_keys():
    # one tally per source, the same custody_counts shape, source keys sorted.
    items = [
        _src("web:a", "web"),
        _src("arxiv:1", "arxiv"),
        _src("web:b", "web", content_hash=None, extracted_text=None, stage="detected"),
    ]
    by_source = custody_counts_by_source(items, {})
    assert list(by_source) == ["arxiv", "web"]  # sorted
    assert by_source["web"]["tiers"] == {"full": 1, "partial": 0, "reference": 1}
    assert by_source["arxiv"]["tiers"] == {"full": 1, "partial": 0, "reference": 0}
    # never verified → every item unverified within its source
    assert by_source["web"]["drift"]["unverified"] == 2
    assert by_source["arxiv"]["drift"]["unverified"] == 1


def test_custody_counts_by_source_carries_the_per_source_posture():
    items = [_src("web:a", "web"), _src("arxiv:1", "arxiv")]
    verdicts = {
        "web:a": CustodyEvent("web:a", "t", "drifted", "h", "x"),
        "arxiv:1": CustodyEvent("arxiv:1", "t", "unchanged", "h", "h"),
    }
    by_source = custody_counts_by_source(items, verdicts)
    assert by_source["web"]["drift"]["drifted"] == 1
    assert by_source["arxiv"]["drift"]["verified"] == 1


def test_custody_counts_by_source_sums_to_the_whole_library_tally():
    # the load-bearing convergence: summing the per-source tallies re-counts the
    # whole library, so by_source can never disagree with custody_counts (H50).
    items = [
        _src("web:full", "web", content_hash="h", raw_text="<r>b</r>"),
        _src("web:ref", "web", content_hash=None, extracted_text=None, stage="detected"),
        _src("arxiv:1", "arxiv", content_hash="h2", raw_text="<r>p</r>"),
    ]
    verdicts = {"web:full": CustodyEvent("web:full", "t", "drifted", "h", "x")}
    whole = custody_counts(items, verdicts)
    by_source = custody_counts_by_source(items, verdicts)

    summed_tiers = {tier: 0 for tier in ("full", "partial", "reference")}
    summed_drift = {p: 0 for p in ("verified", "unverified", "drifted", "rotted", "error")}
    for counts in by_source.values():
        for tier, n in counts["tiers"].items():
            summed_tiers[tier] += n
        for posture, n in counts["drift"].items():
            summed_drift[posture] += n
    assert summed_tiers == whole["tiers"]
    assert summed_drift == whole["drift"]


def test_custody_counts_by_source_empty_is_the_empty_map():
    assert custody_counts_by_source([], {}) == {}


# --- per-source recheck coverage in the breakdown (roadmap H121) ------------


def test_custody_counts_by_source_carries_per_source_coverage():
    # each source carries its own coverage {verified, total} over that source's
    # verifiable (hash-bearing) held items — == recheck_coverage on them.
    items = [
        _src("web:a", "web", content_hash="h1"),  # hash-bearing, verified below
        _src("web:b", "web", content_hash=None, extracted_text=None, stage="detected"),
        _src("arxiv:1", "arxiv", content_hash="h2"),  # hash-bearing, never verified
    ]
    verdicts = {"web:a": CustodyEvent("web:a", "t", "unchanged", "h1", "h1")}
    by_source = custody_counts_by_source(items, verdicts)
    # web: one hash-bearing item with a verdict; the reference-only one excluded
    assert by_source["web"]["coverage"] == {"verified": 1, "total": 1}
    assert by_source["arxiv"]["coverage"] == {"verified": 0, "total": 1}
    # and each equals recheck_coverage over that source's hash-bearing members
    for source in ("web", "arxiv"):
        members = [i for i in items if i.source == source and i.content_hash]
        assert by_source[source]["coverage"] == recheck_coverage(members, verdicts)


def test_custody_counts_by_source_coverage_sums_to_the_whole_recheck_coverage():
    # the coverage-axis sum-to-whole (the H121 sibling of the tiers/drift one):
    # summing the per-source coverage re-counts recheck_coverage over the whole
    # hash-bearing held set, so by_source can never disagree with it.
    items = [
        _src("web:a", "web", content_hash="h1"),
        _src("web:b", "web", content_hash="h2"),
        _src("web:ref", "web", content_hash=None, extracted_text=None, stage="detected"),
        _src("arxiv:1", "arxiv", content_hash="h3"),
    ]
    verdicts = {
        "web:a": CustodyEvent("web:a", "t", "unchanged", "h1", "h1"),
        "arxiv:1": CustodyEvent("arxiv:1", "t", "drifted", "h3", "x"),
    }
    by_source = custody_counts_by_source(items, verdicts)
    summed = {"verified": 0, "total": 0}
    for counts in by_source.values():
        summed["verified"] += counts["coverage"]["verified"]
        summed["total"] += counts["coverage"]["total"]
    hash_bearing = [i for i in items if i.content_hash]
    assert summed == recheck_coverage(hash_bearing, verdicts)
    assert summed == {"verified": 2, "total": 3}  # a + arxiv verified; b not; ref excluded


def test_custody_counts_by_source_coverage_excludes_reference_only():
    # a source holding only reference-only items has no verifiable items, so its
    # coverage denominator is 0 (can reach full, never stuck below 100%).
    items = [_src("web:ref", "web", content_hash=None, extracted_text=None,
                  stage="detected")]
    by_source = custody_counts_by_source(items, {})
    assert by_source["web"]["coverage"] == {"verified": 0, "total": 0}


# --- render_custody_headline (the shared one-line formatter, roadmap H103) ---


def test_render_custody_headline_from_counts_shows_only_non_zero_sections():
    # the counts-based formatter both custody_headline (item-sourced) and
    # maintain.snapshot_headline (snapshot-sourced) delegate to: non-zero
    # tiers/postures only, canonical order, each section summing to N.
    line = render_custody_headline(
        4,
        {"full": 2, "partial": 1, "reference": 1},
        {"verified": 1, "unverified": 2, "drifted": 1, "rotted": 0, "error": 0},
    )
    assert line == (
        "_Custody: 4 scroll(s) · fidelity full 2, partial 1, reference 1 "
        "· drift verified 1, unverified 2, drifted 1._"
    )


def test_render_custody_headline_empty_scope_is_zero_scrolls():
    assert render_custody_headline(0, {}, {}) == "_Custody: 0 scroll(s)._"


def test_render_custody_headline_is_the_renderer_custody_headline_delegates_to():
    # custody_headline(items, verdicts) must equal render_custody_headline over the
    # counts it derives — one formatter, so the item-sourced and snapshot-sourced
    # headlines can never drift apart.
    full = _item("web:full", content_hash="h", extracted_text="b", raw_text="<r>b</r>")
    ref = _item("web:ref", content_hash=None, extracted_text=None, raw_text=None,
                stage="detected")
    items = [full, ref]
    verdicts = {"web:full": CustodyEvent("web:full", "t", "drifted", "h", "x")}
    counts = custody_counts(items, verdicts)
    assert custody_headline(items, verdicts) == render_custody_headline(
        len(items), counts["tiers"], counts["drift"]
    )


# --- per-source coverage in the readable breakdown (roadmap H158) --------


def test_custody_sections_appends_coverage_when_provided():
    # the per-source path passes the source's coverage {verified, total}; the
    # section reads `coverage V/T` and rides last, after fidelity and drift.
    sections = custody_sections(
        {"full": 1, "partial": 0, "reference": 1},
        {"verified": 0, "unverified": 1, "drifted": 1, "rotted": 0, "error": 0},
        {"verified": 1, "total": 2},
    )
    assert sections == [
        "fidelity full 1, reference 1",
        "drift unverified 1, drifted 1",
        "coverage 1/2",
    ]


def test_custody_sections_omits_coverage_when_not_provided():
    # the scope-headline path passes no coverage (coverage stays a per-source
    # triage signal, never on the whole-scope `_Custody:_` line).
    sections = custody_sections(
        {"full": 1, "partial": 0, "reference": 0},
        {"verified": 1, "unverified": 0, "drifted": 0, "rotted": 0, "error": 0},
    )
    assert sections == ["fidelity full 1", "drift verified 1"]
    assert not any("coverage" in s for s in sections)


def test_custody_sections_coverage_is_always_shown_even_when_zero():
    # always-show keeps the section positionally stable: a source with no
    # verifiable items renders `coverage 0/0`, not an omitted section.
    sections = custody_sections(
        {"full": 0, "partial": 0, "reference": 1},
        {"verified": 0, "unverified": 1, "drifted": 0, "rotted": 0, "error": 0},
        {"verified": 0, "total": 0},
    )
    assert sections[-1] == "coverage 0/0"


def test_render_custody_by_source_carries_per_source_coverage():
    # each readable per-source bullet ends with `· coverage V/T` over that
    # source's own hash-bearing held items — the readable counterpart of the
    # JSON by_source coverage (H121).
    items = [
        _src("web:a", "web", content_hash="h1"),  # verified below
        _src("web:b", "web", content_hash="h2"),  # hash-bearing, never checked
        _src("arxiv:1", "arxiv", content_hash="h3"),  # hash-bearing, never checked
    ]
    verdicts = {"web:a": CustodyEvent("web:a", "t", "unchanged", "h1", "h1")}
    by_source = custody_counts_by_source(items, verdicts)
    lines = render_custody_by_source(by_source)
    # web: 1 of 2 hash-bearing verified; arxiv: 0 of 1.
    assert "- `web` — 2 scroll(s) · fidelity full 2 · drift verified 1, " \
        "unverified 1 · coverage 1/2" in lines
    assert "- `arxiv` — 1 scroll(s) · fidelity full 1 · drift unverified 1 " \
        "· coverage 0/1" in lines
    # the coverage shown == the JSON by_source coverage for that source.
    for source in ("web", "arxiv"):
        cov = by_source[source]["coverage"]
        assert any(f"coverage {cov['verified']}/{cov['total']}" in ln for ln in lines)


def test_render_custody_by_source_coverage_shows_zero_over_zero_for_reference_only():
    # a reference-only source has no verifiable items; always-show renders
    # `coverage 0/0` so the section is positionally stable across sources.
    items = [
        _src("web:ref", "web", content_hash=None, extracted_text=None,
             stage="detected"),
        _src("arxiv:1", "arxiv", content_hash="h"),
    ]
    lines = render_custody_by_source(custody_counts_by_source(items, {}))
    assert any("`web`" in ln and ln.endswith("coverage 0/0") for ln in lines)


def test_custody_source_breakdown_sections_end_with_coverage():
    # the structured layer both the Markdown and HTML renderers fold carries the
    # coverage section, so the two readable forms can never disagree on it.
    items = [_src("web:a", "web", content_hash="h"),
             _src("arxiv:1", "arxiv", content_hash="h2")]
    breakdown = custody_source_breakdown(custody_counts_by_source(items, {}))
    for _source, _n, sections in breakdown:
        assert sections[-1].startswith("coverage ")


def test_render_custody_headline_stays_coverage_free():
    # regression for the H158 boundary: the whole-scope headline never grows a
    # coverage section (it is a posture summary, not a per-source triage signal).
    items = [_src("web:a", "web", content_hash="h")]
    assert "coverage" not in custody_headline(items, {})
    assert "coverage" not in render_custody_headline(
        1, {"full": 1}, {"unverified": 1}
    )


# --- render_custody_refresh: the readable per-source `_Refresh:_` line (H178) -


def test_render_custody_refresh_carries_both_axes():
    lines = render_custody_refresh({"arxiv": 1, "web": 2}, {"web": 1})
    assert lines == [
        "_Refresh: classifications stale in `arxiv`, `web` — refresh with "
        "`scrolls classify --stale --source <S>`; summaries stale in `web` — "
        "refresh with `scrolls kb --stale --source <S>`._",
        "",
    ]


def test_render_custody_refresh_one_axis_only_emits_that_clause():
    enr = render_custody_refresh({"web": 1}, {})
    assert enr == [
        "_Refresh: classifications stale in `web` — refresh with "
        "`scrolls classify --stale --source <S>`._",
        "",
    ]
    summ = render_custody_refresh({}, {"web": 1})
    assert summ == [
        "_Refresh: summaries stale in `web` — refresh with "
        "`scrolls kb --stale --source <S>`._",
        "",
    ]


def test_render_custody_refresh_empty_when_no_debt():
    # honest absence: both maps empty → no line (the `_Attention:_`/`_By source:_`
    # no-op posture)
    assert render_custody_refresh({}, {}) == []


def test_render_custody_refresh_has_no_single_source_gate():
    # unlike `_Attention:_`/`_By source:_`, refresh debt is per-source actionable
    # work, not a cross-source comparison — a single source with stale debt shows
    line = render_custody_refresh({"web": 1}, {})
    assert line and "`web`" in line[0]


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


# --- recheck_order (the maintain coverage-first ordering, roadmap H55) -------


def test_recheck_order_puts_the_never_checked_first():
    # never-checked items lead (so a bounded maintain pass spends its budget on
    # new coverage), then the already-verified ones
    a, b, c = _item("web:a"), _item("web:b"), _item("web:c")
    verdicts = {
        "web:a": CustodyEvent("web:a", "2026-06-10T00:00:00+00:00", "unchanged", "h", "h"),
        # web:b, web:c never checked
    }
    assert [i.id for i in recheck_order([a, b, c], verdicts)] == ["web:b", "web:c", "web:a"]


def test_recheck_order_sorts_the_verified_oldest_verdict_first():
    # among already-verified items, the stalest verdict is rechecked first, so a
    # bounded pass keeps coverage moving across the whole library over time
    a, b, c = _item("web:a"), _item("web:b"), _item("web:c")
    verdicts = {
        "web:a": CustodyEvent("web:a", "2026-06-14T00:00:00+00:00", "unchanged", "h", "h"),
        "web:b": CustodyEvent("web:b", "2026-06-10T00:00:00+00:00", "drifted", "h", "x"),
        "web:c": CustodyEvent("web:c", "2026-06-12T00:00:00+00:00", "unchanged", "h", "h"),
    }
    assert [i.id for i in recheck_order([a, b, c], verdicts)] == ["web:b", "web:c", "web:a"]


def test_recheck_order_never_checked_lead_then_oldest_verified():
    # the full ordering: unverified set (in input/oldest-saved order) then the
    # verified set oldest-verdict-first
    a, b, c, d = _item("web:a"), _item("web:b"), _item("web:c"), _item("web:d")
    verdicts = {
        "web:a": CustodyEvent("web:a", "2026-06-14T00:00:00+00:00", "unchanged", "h", "h"),
        "web:c": CustodyEvent("web:c", "2026-06-10T00:00:00+00:00", "drifted", "h", "x"),
        # web:b, web:d never checked → lead in input order
    }
    assert [i.id for i in recheck_order([a, b, c, d], verdicts)] == [
        "web:b", "web:d", "web:c", "web:a"
    ]


def test_recheck_order_leads_with_unverified_items():
    # the head of the order is exactly the `unverified_items` set, in its order —
    # the relationship the slice is built on (never-checked goes first)
    items = [_item(f"web:{n}") for n in range(4)]
    verdicts = {
        "web:1": CustodyEvent("web:1", "2026-06-12T00:00:00+00:00", "unchanged", "h", "h"),
        "web:3": CustodyEvent("web:3", "2026-06-11T00:00:00+00:00", "unchanged", "h", "h"),
    }
    ordered = recheck_order(items, verdicts)
    never = unverified_items(items, verdicts)
    assert ordered[: len(never)] == never


def test_recheck_order_empty_ledger_is_input_order_unchanged():
    # a fresh library (no verdicts) → everything is unverified → no reordering, so
    # the first maintain pass behaves exactly as before
    items = [_item(f"web:{n}") for n in range(4)]
    assert recheck_order(items, {}) == items


def test_recheck_order_is_a_permutation_of_the_input():
    # ordering never drops or duplicates an item — an unbounded pass checks the
    # same set, only the order differs
    items = [_item(f"web:{n}") for n in range(5)]
    verdicts = {
        "web:0": CustodyEvent("web:0", "2026-06-14T00:00:00+00:00", "unchanged", "h", "h"),
        "web:2": CustodyEvent("web:2", "2026-06-10T00:00:00+00:00", "drifted", "h", "x"),
    }
    ordered = recheck_order(items, verdicts)
    assert sorted(i.id for i in ordered) == sorted(i.id for i in items)


def test_recheck_order_breaks_a_same_timestamp_tie_by_input_order():
    # two verdicts at the same instant keep input (oldest-saved-first) order — a
    # stable sort, so the ordering stays deterministic
    a, b = _item("web:a"), _item("web:b")
    same = "2026-06-10T00:00:00+00:00"
    verdicts = {
        "web:a": CustodyEvent("web:a", same, "unchanged", "h", "h"),
        "web:b": CustodyEvent("web:b", same, "unchanged", "h", "h"),
    }
    assert [i.id for i in recheck_order([a, b], verdicts)] == ["web:a", "web:b"]


# --- recheck_coverage (the maintain coverage figure, roadmap H109) ----------


def test_recheck_coverage_counts_the_verified_of_the_hash_bearing_set():
    # of the verifiable held items, how many carry a verdict — the pre-recheck
    # state when no items were checked this pass (empty checked_ids)
    items = [_item(f"web:{n}") for n in range(4)]
    verdicts = {
        "web:0": CustodyEvent("web:0", "2026-06-12T00:00:00+00:00", "unchanged", "h", "h"),
        "web:2": CustodyEvent("web:2", "2026-06-11T00:00:00+00:00", "drifted", "h", "x"),
    }
    assert recheck_coverage(items, verdicts) == {"verified": 2, "total": 4}


def test_recheck_coverage_folds_this_passs_checked_ids_post_recheck():
    # an item checked this pass counts as verified-after even with no prior
    # verdict — coverage is the post-recheck state (verdicts ∪ checked_ids)
    items = [_item(f"web:{n}") for n in range(4)]
    verdicts = {
        "web:0": CustodyEvent("web:0", "2026-06-12T00:00:00+00:00", "unchanged", "h", "h"),
    }
    # this pass re-checked web:1 and web:3 (never-checked-first, H55)
    coverage = recheck_coverage(items, verdicts, {"web:1", "web:3"})
    assert coverage == {"verified": 3, "total": 4}  # web:0 (prior) + web:1 + web:3


def test_recheck_coverage_total_is_the_hash_bearing_count_the_caller_passes():
    # `total` is just len(items); the caller passes its hash-bearing (verifiable)
    # set, so a reference-only item it filtered out is already absent from total
    items = [_item("web:a"), _item("web:b")]  # both hash-bearing
    assert recheck_coverage(items, {})["total"] == 2


def test_recheck_coverage_empty_set_is_an_honest_zero():
    # nothing verifiable → 0 of 0, never a fabricated 100%
    assert recheck_coverage([], {}) == {"verified": 0, "total": 0}


def test_recheck_coverage_verified_never_exceeds_total():
    # an item checked this pass that *also* had a prior verdict is counted once —
    # verified is a set membership, not a double count
    items = [_item("web:a"), _item("web:b")]
    verdicts = {
        "web:a": CustodyEvent("web:a", "2026-06-12T00:00:00+00:00", "unchanged", "h", "h"),
    }
    # web:a re-checked this pass (already had a verdict) → still 1 of 2 verified
    coverage = recheck_coverage(items, verdicts, {"web:a"})
    assert coverage == {"verified": 1, "total": 2}


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
