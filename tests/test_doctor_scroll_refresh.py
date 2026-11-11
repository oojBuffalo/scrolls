"""Existing scrolls must agree with an adopted or restored canonical capture."""

import json
from dataclasses import replace

import pytest

from scrolls.cli import main
from scrolls.items import ScrollItem, get_item, item_to_dict
from scrolls.paths import get_paths


@pytest.mark.parametrize("restore", [False, True], ids=["accept-incoming", "archive-restore"])
def test_doctor_finds_and_repairs_a_stale_scroll_after_adoption(
    tmp_path, monkeypatch, capsys, restore
):
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library"))
    path = tmp_path / "items.jsonl"
    original = ScrollItem(
        "web:a", "web", "https://example.com/a", "2026-01-01",
        title="A", extracted_text="ORIGINAL CAPTURE", content_hash="sha256:original",
        stage="fetched",
    )
    path.write_text(json.dumps(item_to_dict(original)))
    assert main(["import", "items", str(path)]) == 0
    assert main(["md"]) == 0
    paths = get_paths()
    held = get_item(paths.db_path, original.id)
    target = paths.root / held.markdown_path
    peer = replace(held, extracted_text="PEER CAPTURE", content_hash="sha256:peer")
    path.write_text(json.dumps(item_to_dict(peer)))
    assert main(["import", "items", str(path), "--accept-incoming"]) == 0
    capsys.readouterr()

    if restore:
        # First materialize the adopted copy, then restore the original row.
        assert main(["md", "--all"]) == 0
        assert "PEER CAPTURE" in target.read_text()
        assert main(["archive", "restore", held.id]) == 0
        expected, old = "ORIGINAL CAPTURE", "PEER CAPTURE"
    else:
        expected, old = "PEER CAPTURE", "ORIGINAL CAPTURE"
    capsys.readouterr()
    canonical = get_item(paths.db_path, held.id)
    assert old in target.read_text()
    before = paths.db_path.read_bytes()

    assert main(["doctor"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["stale_scrolls"] == [
        {"id": held.id, "path": held.markdown_path, "status": "found"}
    ]
    assert report["custody"]["score"] == 0
    assert report["custody"]["findings"][0]["issues"] == ["stale_scroll"]
    assert paths.db_path.read_bytes() == before
    assert old in target.read_text()

    assert main(["maintain", "--no-recheck"]) == 1
    maintenance = json.loads(capsys.readouterr().out)
    assert maintenance["suggested"] == [
        {"command": "scrolls doctor --fix", "addresses": ["stale_scrolls"]}
    ]
    assert old in target.read_text()  # maintenance reports; repair stays explicit

    assert main(["doctor", "--fix"]) == 0
    repaired = json.loads(capsys.readouterr().out)
    assert repaired["stale_scrolls"][0]["status"] == "rewritten"
    assert repaired["fixed"] == 1
    assert repaired["custody"]["score"] == 100
    assert expected in target.read_text() and old not in target.read_text()
    assert get_item(paths.db_path, held.id) == canonical

    assert main(["doctor"]) == 0
    assert json.loads(capsys.readouterr().out)["stale_scrolls"] == []
