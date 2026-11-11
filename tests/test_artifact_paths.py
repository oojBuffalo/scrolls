"""Imported artifact paths never authorize access to unrelated files."""

import json
from dataclasses import replace

import pytest

from scrolls.cli import main
from scrolls.db import init_db
from scrolls.doctor import run_doctor
from scrolls.items import ScrollItem, get_item, insert_item
from scrolls.media import capture_media
from scrolls.paths import get_paths
from scrolls.remove import remove_item
from scrolls.render import write_scroll


@pytest.fixture
def paths(tmp_path, monkeypatch):
    root = tmp_path / "home"
    root.mkdir()
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    paths = get_paths()
    init_db(paths.db_path)
    return paths


def item(**fields):
    base = ScrollItem(
        id="web:test", source="web", url="https://example.com/test",
        saved_at="2026-10-28T00:00:00+00:00", title="Test",
        extracted_text="Held text", stage="fetched",
    )
    return replace(base, **fields)


@pytest.mark.parametrize("relpath", ["../victim.md", "db.sqlite", "media/victim.md"])
def test_render_rejects_paths_outside_scrolls(paths, relpath):
    victim = paths.root / relpath
    if relpath != "db.sqlite":
        victim.parent.mkdir(parents=True, exist_ok=True)
        victim.write_text("keep me")
    before = victim.read_bytes()
    with pytest.raises(ValueError):
        write_scroll(paths, item(markdown_path=relpath))
    assert victim.read_bytes() == before


def test_render_rejects_symlink_escape(paths, tmp_path):
    paths.scrolls_dir.mkdir()
    victim = tmp_path / "victim.md"
    victim.write_text("keep me")
    (paths.scrolls_dir / "victim.md").symlink_to(victim)
    with pytest.raises(ValueError):
        write_scroll(paths, item(markdown_path="scrolls/victim.md"))
    assert victim.read_text() == "keep me"


def test_symlink_alias_cannot_overwrite_or_remove_another_items_file(paths):
    first = write_scroll(paths, item())
    insert_item(paths.db_path, first)
    (paths.scrolls_dir / "alias").symlink_to(paths.scrolls_dir / "web", target_is_directory=True)
    alias = replace(first, id="web:alias", markdown_path="scrolls/alias/test.md")
    insert_item(paths.db_path, alias)
    before = (paths.root / first.markdown_path).read_bytes()
    with pytest.raises(ValueError):
        write_scroll(paths, alias)
    with pytest.raises(ValueError):
        remove_item(paths, alias)
    assert (paths.root / first.markdown_path).read_bytes() == before


def test_render_rejects_source_traversal(paths):
    with pytest.raises(ValueError):
        write_scroll(paths, item(source="../../outside"))
    assert not (paths.root.parent / "outside").exists()


@pytest.mark.parametrize("field", ["markdown_path", "media"])
def test_remove_cannot_delete_the_database(paths, field):
    bad = item(**{field: "db.sqlite"} if field == "markdown_path" else {
        "media": ({"url": "https://example.com/file", "path": "db.sqlite"},)
    })
    insert_item(paths.db_path, bad)
    before = paths.db_path.read_bytes()
    with pytest.raises(ValueError):
        remove_item(paths, bad)
    assert paths.db_path.read_bytes() == before
    assert get_item(paths.db_path, bad.id) == bad


def test_media_rejects_unsafe_ref_before_downloading(paths, monkeypatch):
    called = []
    monkeypatch.setattr("scrolls.media._download", lambda *args, **kwargs: (called.append(args), 0))
    bad = item(media=({"url": "https://example.com/file", "path": "db.sqlite"},))
    before = paths.db_path.read_bytes()
    updated, results = capture_media(paths, bad, force=True)
    assert updated == bad
    assert results[0]["status"] == "failed"
    assert not called
    assert paths.db_path.read_bytes() == before


def test_md_reports_bad_path_and_continues_batch(paths, capsys):
    insert_item(paths.db_path, item(markdown_path="db.sqlite"))
    insert_item(paths.db_path, item(id="web:good", title="Good"))
    assert main(["md", "--all"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["failed"] == 1
    assert result["rendered"] == 1
    assert get_item(paths.db_path, "web:good").stage == "rendered"


def test_doctor_refuses_unsafe_paths_and_duplicate_cleanup(paths, tmp_path):
    victim = tmp_path / "victim.md"
    victim.write_text("keep me")
    for id, relpath in [("web:one", "../victim.md"), ("web:two", "db.sqlite")]:
        insert_item(paths.db_path, item(id=id, markdown_path=relpath, stage="rendered"))
    report = run_doctor(paths, fix=True)
    assert report["issues"] > report["fixed"]
    assert report["custody"]["posture"]["verdict"] == "at_risk"
    assert victim.read_text() == "keep me"
    assert get_item(paths.db_path, "web:one") is not None
    assert get_item(paths.db_path, "web:two") is not None


def test_distinct_items_with_colliding_media_slugs_keep_both_files(paths, monkeypatch):
    monkeypatch.setattr("scrolls.media._download", lambda url, **_: (url.encode(), len(url)))
    held = []
    for id, url in [("web:a.b", "https://example.com/a.png"), ("web:a-b", "https://example.com/b.png")]:
        updated, results = capture_media(paths, item(id=id, media=({"url": url},)), delay=0)
        assert results[0]["status"] == "captured"
        insert_item(paths.db_path, updated)
        held.append(updated)
    assert held[0].media[0]["path"] != held[1].media[0]["path"]
    for entry in held:
        assert (paths.root / entry.media[0]["path"]).read_bytes() == entry.media[0]["url"].encode()
    remove_item(paths, held[0])
    assert (paths.root / held[1].media[0]["path"]).exists()


def test_removal_preserves_artifacts_still_referenced_by_another_item(paths):
    rendered = write_scroll(paths, item())
    media_path = paths.media_dir / "shared.png"
    media_path.parent.mkdir()
    media_path.write_bytes(b"held")
    rendered = replace(rendered, media=({"path": "media/shared.png"},))
    insert_item(paths.db_path, rendered)
    peer = replace(rendered, id="web:peer")
    insert_item(paths.db_path, peer)
    assert remove_item(paths, rendered) == []
    assert (paths.root / peer.markdown_path).exists()
    assert media_path.read_bytes() == b"held"
    assert get_item(paths.db_path, peer.id) == peer


def test_imported_scroll_path_cannot_overwrite_another_items_view(paths):
    first = write_scroll(paths, item())
    insert_item(paths.db_path, first)
    before = (paths.root / first.markdown_path).read_bytes()
    second = replace(first, id="web:second", extracted_text="Different body")
    rendered = write_scroll(paths, second)
    assert rendered.markdown_path != first.markdown_path
    assert (paths.root / first.markdown_path).read_bytes() == before
    assert "Different body" in (paths.root / rendered.markdown_path).read_text()
