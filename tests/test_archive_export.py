"""Lossless JSONL prior-content-archive export/import — the portable recovery
store (roadmap H280, the archive-axis counterpart of the events export's H72
portable custody).

`dump_archive_export` serializes the prior-content archive to JSON Lines and
`load_archive_export` reads them back; the contract is a faithful round-trip at
the ArchiveRecord level (every column, the nested model-complete snapshot), the
recovery-store sibling of `export items`/`export events`. Restore is through
`items.import_archive`, deduped by `(item_id, prior_hash)`, so re-importing a
backup is a no-op (proven in `test_items.py`); here the JSONL framing,
validation, and the load↔dump round-trip are exercised.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scrolls.archive_export import ArchiveSourceError, load_archive_export
from scrolls.items import ArchiveRecord, dump_archive_export


def _snapshot(item_id: str) -> dict:
    return {
        "id": item_id, "source": "web", "url": f"https://{item_id}.example",
        "saved_at": "2026-06-11T00:00:00+00:00", "content_hash": "sha256:old",
    }


def _records() -> list[ArchiveRecord]:
    return [
        ArchiveRecord("web:a", "2026-06-22T00:00:00+00:00", "sha256:old",
                      "sha256:new", _snapshot("web:a")),
        ArchiveRecord("web:b", "2026-06-22T01:00:00+00:00", None,
                      "sha256:nb", _snapshot("web:b")),
    ]


def test_dump_emits_one_json_object_per_record_with_the_nested_snapshot():
    out = dump_archive_export(_records())
    lines = out.splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first == {
        "item_id": "web:a", "archived_at": "2026-06-22T00:00:00+00:00",
        "prior_hash": "sha256:old", "superseded_by": "sha256:new",
        "snapshot": _snapshot("web:a"),
    }
    # the snapshot is a nested object, not a string-in-string (jq-friendly)
    assert isinstance(first["snapshot"], dict)
    # a NULL prior_hash survives as JSON null
    assert json.loads(lines[1])["prior_hash"] is None


def test_dump_then_load_is_a_lossless_round_trip(tmp_path):
    records = _records()
    path = tmp_path / "archive.jsonl"
    path.write_text(dump_archive_export(records), encoding="utf-8")

    loaded, stats = load_archive_export(path)
    assert loaded == records  # every field survives, in order
    assert stats == {"archive": 2}


def test_dump_empty_is_an_empty_document():
    assert dump_archive_export([]) == ""


def test_load_empty_document_yields_no_records(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    loaded, stats = load_archive_export(path)
    assert loaded == [] and stats == {"archive": 0}


def test_load_skips_blank_lines(tmp_path):
    path = tmp_path / "archive.jsonl"
    line = json.dumps({"item_id": "web:x", "archived_at": "t",
                       "snapshot": _snapshot("web:x")})
    path.write_text(f"\n{line}\n\n", encoding="utf-8")
    loaded, stats = load_archive_export(path)
    assert stats == {"archive": 1} and loaded[0].item_id == "web:x"


def test_load_missing_file_raises():
    with pytest.raises(ArchiveSourceError):
        load_archive_export(Path("/no/such/archive.jsonl"))


def test_load_malformed_json_line_raises_naming_the_line(tmp_path):
    path = tmp_path / "bad.jsonl"
    good = json.dumps({"item_id": "web:x", "archived_at": "t",
                       "snapshot": _snapshot("web:x")})
    path.write_text(f"{good}\nnot json at all\n", encoding="utf-8")
    with pytest.raises(ArchiveSourceError, match="line 2"):
        load_archive_export(path)


def test_load_non_object_line_raises(tmp_path):
    path = tmp_path / "array.jsonl"
    path.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(ArchiveSourceError, match="line 1"):
        load_archive_export(path)


def test_load_line_missing_required_field_raises(tmp_path):
    # an archived prior without identity is corruption; silently dropping it from a
    # recovery backup would lose the only copy of a superseded capture
    path = tmp_path / "incomplete.jsonl"
    path.write_text(
        json.dumps({"item_id": "web:x", "archived_at": "t"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ArchiveSourceError, match="snapshot"):
        load_archive_export(path)


def test_load_ignores_unknown_keys_including_the_autoincrement_id(tmp_path):
    # forward-compat + the per-library id is never part of the identity
    path = tmp_path / "future.jsonl"
    record = {
        "id": 42, "item_id": "web:x", "archived_at": "2026-06-22T00:00:00+00:00",
        "prior_hash": "h", "superseded_by": "h2", "snapshot": _snapshot("web:x"),
        "future_field": "from a newer scrolls",
    }
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    loaded, _ = load_archive_export(path)
    assert loaded[0] == ArchiveRecord(
        "web:x", "2026-06-22T00:00:00+00:00", "h", "h2", _snapshot("web:x")
    )
