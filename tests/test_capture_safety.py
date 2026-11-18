"""Capture commands cannot silently replace an artifact already held."""

from dataclasses import replace
import json

import pytest

from scrolls import cli, mcp_server, pipeline
from scrolls.items import get_item, update_item

URL = "https://example.com/held"


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library"))
    paths, item, _ = pipeline.register_url(URL)
    return paths, item


@pytest.mark.parametrize("entrypoint", ["cli", "mcp"])
@pytest.mark.parametrize("stage", ["detected", "fetched", "rendered"])
@pytest.mark.parametrize("capture", [
    {"raw_text": "held response"},
    {"extracted_text": "held body"},
    {"content_hash": "sha256:held"},
])
def test_reingest_preserves_any_held_capture(
    library, monkeypatch, capsys, entrypoint, stage, capture
):
    paths, item = library
    held = replace(item, stage=stage, title="Held title", category="reference",
                   provenance={"adapter": "held", "fetched_at": "2026-01-01"}, **capture)
    update_item(paths.db_path, held)

    def forbidden(_):
        pytest.fail("reingest must not re-capture a held artifact")

    monkeypatch.setitem(pipeline.FETCH_ADAPTERS, "web", forbidden)
    if entrypoint == "cli":
        assert cli.main(["ingest", URL]) == 0
        result = json.loads(capsys.readouterr().out)
    else:
        result = mcp_server.ingest_url(URL)
    assert result["created"] is False
    assert result["stage"] == "rendered"
    after = get_item(paths.db_path, held.id)
    for field in ("raw_text", "extracted_text", "content_hash", "provenance", "saved_at"):
        assert getattr(after, field) == getattr(held, field)


@pytest.mark.parametrize("stage", ["detected", "fetched", "rendered"])
def test_fetch_held_capture_requires_verify(library, monkeypatch, capsys, stage):
    paths, item = library
    held = replace(item, stage=stage, raw_text="held response", extracted_text="held body",
                   content_hash="sha256:held")
    update_item(paths.db_path, held)
    monkeypatch.setitem(cli.FETCH_ADAPTERS, "web", lambda _: pytest.fail("must use verify"))
    assert cli.main(["fetch", held.id]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["fetched"] == 0
    assert result["failed"] == 1
    assert "verify" in result["results"][0]["error"]
    assert get_item(paths.db_path, held.id) == held


@pytest.mark.parametrize("command", ["fetch", "ingest"])
@pytest.mark.parametrize("stage", ["detected", "fetched", "rendered"])
def test_reference_without_capture_can_be_fetched(library, monkeypatch, capsys, command, stage):
    paths, item = library
    reference = replace(item, stage=stage, summary="Saved reference")
    update_item(paths.db_path, reference)
    calls = []

    def capture(row):
        calls.append(row.id)
        return replace(row, raw_text="new response", extracted_text="new body",
                       content_hash="sha256:new", stage="fetched")

    monkeypatch.setitem(pipeline.FETCH_ADAPTERS, "web", capture)
    assert cli.main([command, item.id if command == "fetch" else URL]) == 0
    capsys.readouterr()
    assert calls == [item.id]
    assert get_item(paths.db_path, item.id).raw_text == "new response"


def test_batch_fetch_preserves_detected_capture_and_continues(library, monkeypatch, capsys):
    paths, item = library
    held = replace(item, raw_text="held response")
    update_item(paths.db_path, held)
    _, pending, _ = pipeline.register_url("https://example.com/pending")
    calls = []

    def capture(row):
        calls.append(row.id)
        return replace(row, raw_text="fresh response", stage="fetched")

    monkeypatch.setitem(cli.FETCH_ADAPTERS, "web", capture)
    assert cli.main(["fetch", "--limit", "1"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["fetched"] == 1
    assert result["failed"] == 1
    assert calls == [pending.id]
    assert get_item(paths.db_path, item.id) == held
