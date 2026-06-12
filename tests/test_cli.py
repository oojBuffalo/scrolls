"""Tests for the `scrolls` CLI entry point."""

import json

import pytest

from scrolls.cli import main


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
        "db": str(scrolls_home / "db.sqlite"),
        "config": str(scrolls_home / "config.toml"),
    }


def test_init_creates_library_skeleton(scrolls_home, capsys):
    exit_code = main(["init"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"root": str(scrolls_home), "created": True}
    for subdir in ("items", "scrolls", "library", "media"):
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


def test_status_before_init(scrolls_home, capsys):
    exit_code = main(["status"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "initialized": False,
        "root": str(scrolls_home),
        "schema_version": None,
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
        "schema_version": 1,
    }
