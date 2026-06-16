"""Lossless JSONL custody-event export/import — whole-library portable custody
(roadmap H72, the backup-path counterpart of the bundle's H67 portable custody).

`dump_events_export` serializes the verify ledger to JSON Lines and
`load_events_export` reads them back; the contract is a faithful round-trip at
the CustodyEvent level (every column, `item_id` included), the custody sibling
of `export items`. Restore is through `custody.import_events`, deduped by
content, so re-importing a backup is a no-op (proven in `test_custody.py`); here
the JSONL framing, validation, and the load↔dump round-trip are exercised.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scrolls.custody import CustodyEvent, dump_events_export
from scrolls.events_export import EventsSourceError, load_events_export


def _events() -> list[CustodyEvent]:
    return [
        CustodyEvent("web:a", "2026-06-13T00:00:00+00:00", "unchanged", "h1", "h1"),
        CustodyEvent("web:b", "2026-06-14T00:00:00+00:00", "rotted", "h2", None, "gone"),
    ]


def test_dump_emits_one_json_object_per_event_with_the_item_id():
    out = dump_events_export(_events())
    lines = out.splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    # the export row carries item_id (the stream spans many items), unlike the
    # item-scoped `history` shape
    assert first == {
        "item_id": "web:a", "checked_at": "2026-06-13T00:00:00+00:00",
        "status": "unchanged", "prior_hash": "h1", "observed_hash": "h1",
        "detail": None,
    }
    assert json.loads(lines[1])["detail"] == "gone"


def test_dump_then_load_is_a_lossless_round_trip(tmp_path):
    events = _events()
    path = tmp_path / "ledger.jsonl"
    path.write_text(dump_events_export(events), encoding="utf-8")

    loaded, stats = load_events_export(path)
    assert loaded == events  # every field survives, in order
    assert stats == {"events": 2}


def test_dump_empty_is_an_empty_document():
    assert dump_events_export([]) == ""


def test_load_empty_document_yields_no_events(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    loaded, stats = load_events_export(path)
    assert loaded == [] and stats == {"events": 0}


def test_load_skips_blank_lines(tmp_path):
    path = tmp_path / "ledger.jsonl"
    line = json.dumps({"item_id": "web:x", "checked_at": "t", "status": "unchanged"})
    path.write_text(f"\n{line}\n\n", encoding="utf-8")
    loaded, stats = load_events_export(path)
    assert stats == {"events": 1} and loaded[0].item_id == "web:x"


def test_load_missing_file_raises():
    with pytest.raises(EventsSourceError):
        load_events_export(Path("/no/such/ledger.jsonl"))


def test_load_malformed_json_line_raises_naming_the_line(tmp_path):
    path = tmp_path / "bad.jsonl"
    good = json.dumps({"item_id": "web:x", "checked_at": "t", "status": "unchanged"})
    path.write_text(f"{good}\nnot json at all\n", encoding="utf-8")
    with pytest.raises(EventsSourceError, match="line 2"):
        load_events_export(path)


def test_load_non_object_line_raises(tmp_path):
    path = tmp_path / "array.jsonl"
    path.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(EventsSourceError, match="line 1"):
        load_events_export(path)


def test_load_line_missing_required_field_raises(tmp_path):
    # a custody event without identity is corruption; silently dropping it from a
    # backup would lose the proof of a verify check
    path = tmp_path / "incomplete.jsonl"
    path.write_text(
        json.dumps({"item_id": "web:x", "status": "unchanged"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(EventsSourceError, match="checked_at"):
        load_events_export(path)


def test_load_ignores_unknown_keys_including_the_autoincrement_id(tmp_path):
    # forward-compat + the per-library id is never part of the identity: a row
    # carrying `id` (or a newer field) still loads, dropping what it doesn't know
    path = tmp_path / "future.jsonl"
    record = {
        "id": 42, "item_id": "web:x", "checked_at": "2026-06-13T00:00:00+00:00",
        "status": "drifted", "prior_hash": "h", "observed_hash": "h2",
        "detail": None, "future_field": "from a newer scrolls",
    }
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    loaded, _ = load_events_export(path)
    assert loaded[0] == CustodyEvent(
        "web:x", "2026-06-13T00:00:00+00:00", "drifted", "h", "h2", None
    )
