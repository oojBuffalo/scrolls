"""Malformed backups must fail before mutating a healthy library."""

import json
import sqlite3
from dataclasses import asdict

import pytest

from scrolls.cli import main
from scrolls.generated import fence
from scrolls.items import ScrollItem, get_item, insert_item, item_from_dict
from scrolls.pipeline import ensure_library
from scrolls.paths import get_paths
from scrolls.media import capture_media
from scrolls.items_export import dump_items_export, load_items_export


def row(**changes):
    return {**asdict(ScrollItem("web:a", "web", "https://example.com/a", "2026-01-01")), **changes}


def test_declined_media_with_unknown_size_still_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr("scrolls.media._download", lambda *args, **kwargs: (None, None))
    original = item_from_dict(row(media=[{"url": "https://example.com/large.mp4", "type": "video"}]))
    declined, _ = capture_media(get_paths(tmp_path), original, limit_for=lambda _: 10, delay=0)
    assert declined.media[0]["bytes"] is None
    backup = tmp_path / "items.jsonl"
    backup.write_text(dump_items_export([declined]))
    restored, _ = load_items_export(backup)
    assert restored == [declined]


def bundle(*blocks):
    return "\n".join(fence("```jsonl\n" + "\n".join(json.dumps(r) for r in rows) + "\n```", "export bundle") for rows in blocks)


@pytest.mark.parametrize("field,value", [
    ("id", 123), ("source", ["web"]), ("url", True), ("saved_at", {}),
    ("title", []), ("content_hash", 42), ("stage", "invalid"),
    ("tags", None), ("concepts", "abc"), ("links", [None]),
    ("media", [123]), ("provenance", []),
])
@pytest.mark.parametrize("transport", ["items", "bundle"])
def test_invalid_item_field_rejects_whole_import_before_writing(tmp_path, monkeypatch, capsys, field, value, transport):
    home = tmp_path / "library"
    monkeypatch.setenv("SCROLLS_HOME", str(home))
    records = [row(id="web:good"), row(**{field: value})]
    path = tmp_path / "input"
    path.write_text(bundle(records) if transport == "bundle" else "\n".join(json.dumps(r) for r in records))
    assert main(["import", transport, str(path)]) == 1
    captured = capsys.readouterr()
    assert field in json.loads(captured.err)["error"]
    assert captured.out == ""
    assert not (home / "db.sqlite").exists()


@pytest.mark.parametrize("snapshot", ["invalid", {"id": "web:b"}, row(id="web:b"), row(tags=None)])
@pytest.mark.parametrize("transport", ["archive", "bundle"])
def test_archive_snapshot_is_validated_before_import(tmp_path, monkeypatch, capsys, snapshot, transport):
    home = tmp_path / "library"
    monkeypatch.setenv("SCROLLS_HOME", str(home))
    record = {"item_id": "web:a", "archived_at": "2026-01-01", "prior_hash": "old", "superseded_by": "new", "snapshot": snapshot}
    path = tmp_path / "input"
    path.write_text(bundle([], [], [record]) if transport == "bundle" else json.dumps(record))
    assert main(["import", transport, str(path)]) == 1
    assert "snapshot" in json.loads(capsys.readouterr().err)["error"]
    assert not (home / "db.sqlite").exists()


@pytest.mark.parametrize("transport", ["items", "events", "archive", "bundle"])
def test_invalid_utf8_backup_is_a_structured_error(tmp_path, monkeypatch, capsys, transport):
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library"))
    path = tmp_path / "input"
    path.write_bytes(b"\xff")
    assert main(["import", transport, str(path)]) == 1
    assert "error" in json.loads(capsys.readouterr().err)


@pytest.mark.parametrize("field,value", [("item_id", []), ("checked_at", 123), ("status", "invalid"), ("detail", {})])
@pytest.mark.parametrize("transport", ["events", "bundle"])
def test_invalid_event_is_rejected_before_writing(tmp_path, monkeypatch, capsys, field, value, transport):
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library"))
    record = {"item_id": "web:a", "checked_at": "2026-01-01", "status": "unchanged", field: value}
    path = tmp_path / "input"
    path.write_text(bundle([], [record]) if transport == "bundle" else json.dumps(record))
    assert main(["import", transport, str(path)]) == 1
    assert field in json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "library" / "db.sqlite").exists()


@pytest.mark.parametrize("command", [["archive", "restore", "web:a"], ["archive", "restore", "web:a", "--dry-run"], ["archive", "diff", "web:a"], ["archive", "show", "web:a"], ["archive", "show", "web:a", "--all"]])
def test_legacy_archive_identity_mismatch_never_restores_another_item(tmp_path, monkeypatch, capsys, command):
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library"))
    paths = get_paths()
    ensure_library(paths)
    a = item_from_dict(row(content_hash="a"))
    b = item_from_dict(row(id="web:b", content_hash="b"))
    insert_item(paths.db_path, a)
    insert_item(paths.db_path, b)
    with sqlite3.connect(paths.db_path) as conn:
        conn.execute("INSERT INTO item_archive (item_id, archived_at, prior_hash, superseded_by, snapshot) VALUES (?, ?, ?, ?, ?)", (a.id, "2026-01-01", "old", "a", json.dumps(row(id="web:b", content_hash="old"))))
    before = paths.db_path.read_bytes()
    assert main(command) == 1
    assert "snapshot" in json.loads(capsys.readouterr().err)["error"]
    assert get_item(paths.db_path, a.id) == a
    assert get_item(paths.db_path, b.id) == b
    assert paths.db_path.read_bytes() == before


@pytest.mark.parametrize("changes", [
    {"source": "../outside"}, {"source": ".."}, {"source": "nested/source"},
    {"source": "bad\\source"}, {"source": "bad\x00source"},
    {"markdown_path": "../outside.md"}, {"markdown_path": "db.sqlite"},
    {"markdown_path": "/scrolls/outside.md"},
    {"media": [{"path": "../outside.bin"}]},
    {"media": [{"path": "credentials.json"}]},
    {"media": [{"path": "media/../db.sqlite"}]},
])
@pytest.mark.parametrize("transport", ["items", "archive", "bundle", "bundle-archive"])
def test_unsafe_paths_reject_backups_before_any_writes(tmp_path, monkeypatch, capsys, changes, transport):
    home = tmp_path / "library"
    monkeypatch.setenv("SCROLLS_HOME", str(home))
    record = row(**changes)
    if transport in ("archive", "bundle-archive"):
        record = {"item_id": "web:a", "archived_at": "2026-01-01", "snapshot": record}
    path = tmp_path / "input"
    if transport == "bundle":
        content = bundle([record])
    elif transport == "bundle-archive":
        content = bundle([], [], [record])
    else:
        content = json.dumps(record)
    path.write_text(content)
    assert main(["import", "bundle" if transport.startswith("bundle") else transport, str(path)]) == 1
    assert "error" in json.loads(capsys.readouterr().err)
    assert not (home / "db.sqlite").exists()


def test_legacy_string_media_refs_still_round_trip():
    record = row(media=["legacy reference"])
    assert item_from_dict(record).media == ("legacy reference",)


@pytest.mark.parametrize("ref", [
    {"url": ["https://example.com/image.png"]},
    {"text": ["invalid document text"]},
    {"bytes": {"invalid": 1}},
    {"oversize": -1},
])
@pytest.mark.parametrize("transport", ["items", "bundle"])
def test_malformed_known_media_fields_are_rejected_before_writing(
    tmp_path, monkeypatch, capsys, ref, transport
):
    home = tmp_path / "library"
    monkeypatch.setenv("SCROLLS_HOME", str(home))
    record = row(media=[ref])
    path = tmp_path / "input"
    path.write_text(bundle([record]) if transport == "bundle" else json.dumps(record))
    assert main(["import", transport, str(path)]) == 1
    assert "media" in json.loads(capsys.readouterr().err)["error"]
    assert not (home / "db.sqlite").exists()
