"""Imported artifact paths never authorize access to unrelated files."""

import json
import os
from dataclasses import replace

import pytest

from scrolls.cli import main
from scrolls.db import init_db
from scrolls.doctor import run_doctor
from scrolls.items import ScrollItem, get_item, insert_item, make_item_id
from scrolls.media import capture_media
from scrolls.paths import get_paths
from scrolls.remove import remove_item
from scrolls.render import refresh_scroll, render_markdown, write_scroll


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


def test_removal_preserves_a_file_another_item_names_in_a_different_case(paths):
    # On a case-insensitive filesystem (macOS, Windows) both spellings are one
    # file, so comparing the recorded strings would delete the peer's copy.
    # On a case-sensitive one the second spelling names nothing.
    media_path = paths.media_dir / "photo.png"
    media_path.parent.mkdir()
    media_path.write_bytes(b"held")
    holder = replace(item(), media=({"path": "media/photo.png"},))
    insert_item(paths.db_path, holder)
    alias = replace(item(id="web:alias"), media=({"path": "media/PHOTO.png"},))
    insert_item(paths.db_path, alias)
    assert remove_item(paths, alias) == []
    assert media_path.read_bytes() == b"held"
    assert get_item(paths.db_path, alias.id) is None


def test_imported_scroll_path_cannot_overwrite_another_items_view(paths):
    first = write_scroll(paths, item())
    insert_item(paths.db_path, first)
    before = (paths.root / first.markdown_path).read_bytes()
    second = replace(first, id="web:second", extracted_text="Different body")
    rendered = write_scroll(paths, second)
    assert rendered.markdown_path != first.markdown_path
    assert (paths.root / first.markdown_path).read_bytes() == before
    assert "Different body" in (paths.root / rendered.markdown_path).read_text()


def test_render_keeps_a_peer_scroll_named_in_a_different_case(paths):
    # One file on a case-insensitive filesystem, so the peer must own it.
    first = write_scroll(paths, item())
    insert_item(paths.db_path, first)
    before = (paths.root / first.markdown_path).read_bytes()
    second = replace(
        first, id="web:second", extracted_text="Different body",
        markdown_path=first.markdown_path.replace("test.md", "TEST.md"),
    )
    insert_item(paths.db_path, second)
    rendered = write_scroll(paths, second)
    assert rendered.markdown_path.casefold() != first.markdown_path.casefold()
    assert (paths.root / first.markdown_path).read_bytes() == before
    assert "Different body" in (paths.root / rendered.markdown_path).read_text()


def test_duplicate_merge_keeps_a_scroll_an_outside_item_still_names(paths):
    def web(url, **fields):
        return item(id=make_item_id("web", None, url), url=url, source_id=None, **fields)

    donor = write_scroll(paths, web("https://example.com/post?utm_source=x"))
    insert_item(paths.db_path, donor)
    loser = write_scroll(paths, web("https://example.com/post", title="Again"))
    insert_item(paths.db_path, loser)
    outsider = item(id="rfc:1", source="rfc", url="https://example.com/rfc",
                    markdown_path=donor.markdown_path, stage="rendered")
    insert_item(paths.db_path, outsider)
    run_doctor(paths, fix=True, source="web")
    assert (paths.root / outsider.markdown_path).exists()


def test_doctor_repairs_two_rows_sharing_a_missing_scroll_without_an_orphan(paths):
    for id, title in [("web:one", "One"), ("web:two", "Two")]:
        insert_item(paths.db_path, item(
            id=id, title=title, url=f"https://example.com/{title}",
            markdown_path="scrolls/web/shared.md", stage="rendered"))
    report = run_doctor(paths, fix=True)
    assert report["stale_scrolls"] == []
    held = [get_item(paths.db_path, id) for id in ("web:one", "web:two")]
    files = sorted(p.relative_to(paths.root).as_posix() for p in paths.scrolls_dir.rglob("*.md"))
    assert files == sorted(entry.markdown_path for entry in held)
    for entry in held:
        assert (paths.root / entry.markdown_path).read_text() == render_markdown(entry)


def test_set_reports_an_unsafe_scroll_path(paths, capsys):
    insert_item(paths.db_path, item(markdown_path="db.sqlite"))
    assert main(["set", "web:test", "category=tool"]) == 1
    assert "error" in json.loads(capsys.readouterr().err)


def test_classify_reports_an_unsafe_scroll_path_and_continues_batch(paths, capsys):
    arxiv = dict(source="arxiv", url="https://arxiv.org/abs/2401.00001")
    insert_item(paths.db_path, item(id="arxiv:bad", markdown_path="db.sqlite", **arxiv))
    insert_item(paths.db_path, item(id="arxiv:good", **arxiv))
    assert main(["classify"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert (result["failed"], result["classified"]) == (1, 1)
    assert get_item(paths.db_path, "arxiv:good").category == "paper"


def test_media_reports_an_unsafe_scroll_path_and_continues_batch(paths, capsys, monkeypatch):
    monkeypatch.setattr("scrolls.media._download", lambda url, **_: (url.encode(), len(url)))
    monkeypatch.setattr("scrolls.media.time.sleep", lambda _: None, raising=False)
    ref = ({"url": "https://example.com/a.png"},)
    insert_item(paths.db_path, item(id="web:bad", markdown_path="db.sqlite", media=ref))
    insert_item(paths.db_path, item(id="web:good", title="Good", media=ref))
    assert main(["media"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert (result["failed"], result["captured"]) == (1, 1)


def test_forced_capture_keeps_media_a_peer_names_in_a_different_case(paths, monkeypatch):
    monkeypatch.setattr("scrolls.media._download", lambda url, **_: (b"new", 3))
    media_path = paths.media_dir / "photo.png"
    media_path.parent.mkdir()
    media_path.write_bytes(b"held")
    insert_item(paths.db_path, item(media=({"url": "https://example.com/a.png", "path": "media/photo.png"},)))
    alias = item(id="web:alias", media=({"url": "https://example.com/b.png", "path": "media/PHOTO.png"},))
    insert_item(paths.db_path, alias)
    updated, results = capture_media(paths, alias, force=True, delay=0)
    assert results[0]["status"] == "captured"
    assert updated.media[0]["path"].casefold() != "media/photo.png"
    assert media_path.read_bytes() == b"held"


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="needs POSIX permissions")
def test_removal_keeps_the_row_when_its_file_cannot_be_inspected(paths):
    locked = paths.media_dir / "locked"
    locked.mkdir(parents=True)
    (locked / "a.png").write_bytes(b"held")
    held = item(media=({"path": "media/locked/a.png"},))
    insert_item(paths.db_path, held)
    locked.chmod(0)
    try:
        with pytest.raises(OSError):
            remove_item(paths, held)
    finally:
        locked.chmod(0o755)
    assert get_item(paths.db_path, held.id) == held
    assert (locked / "a.png").read_bytes() == b"held"


def test_forced_capture_never_takes_a_path_a_peer_records_without_its_file(paths, monkeypatch):
    # After an items-only import a peer can record a path whose file is absent.
    monkeypatch.setattr("scrolls.media._download", lambda url, **_: (b"new", 3))
    media_path = paths.media_dir / "photo.png"
    media_path.parent.mkdir()
    media_path.write_bytes(b"held")
    insert_item(paths.db_path, item(media=({"url": "https://example.com/a.png", "path": "media/photo.png"},)))
    alias = item(id="web:alias", media=({"url": "https://example.com/b.png", "path": "media/PHOTO.png"},))
    insert_item(paths.db_path, alias)
    first, _ = capture_media(paths, alias, force=True, delay=0)
    taken = first.media[0]["path"]
    (paths.root / taken).unlink()
    insert_item(paths.db_path, item(id="web:third", media=({"url": "https://example.com/c.png", "path": taken},)))
    second, _ = capture_media(paths, alias, force=True, delay=0)
    assert second.media[0]["path"] != taken
    assert not (paths.root / taken).exists()


def test_removal_handles_two_refs_to_one_file(paths):
    media_path = paths.media_dir / "a.png"
    media_path.parent.mkdir()
    media_path.write_bytes(b"held")
    held = item(media=({"path": "media/a.png"}, {"path": "media/a.png"}))
    insert_item(paths.db_path, held)
    assert remove_item(paths, held) == ["media/a.png"]
    assert not media_path.exists()
    assert get_item(paths.db_path, held.id) is None


def test_a_scroll_whose_held_text_has_crlf_is_current_once_rendered(paths):
    # Scrolls are written and compared as exact bytes, on every platform.
    rendered = write_scroll(paths, item(extracted_text="line one\r\nline two"))
    insert_item(paths.db_path, rendered)
    assert b"line one\r\nline two" in (paths.root / rendered.markdown_path).read_bytes()
    assert run_doctor(paths)["stale_scrolls"] == []
    assert refresh_scroll(paths, rendered) == (rendered, False)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs named pipes")
def test_doctor_reports_a_scroll_path_that_is_not_a_regular_file(paths):
    insert_item(paths.db_path, item(markdown_path="scrolls/web/pipe.md", stage="rendered"))
    (paths.scrolls_dir / "web").mkdir(parents=True)
    os.mkfifo(paths.scrolls_dir / "web" / "pipe.md")
    [entry] = run_doctor(paths, fix=True)["stale_scrolls"]  # must not block on the pipe
    assert entry["status"] == "failed"


def test_failed_media_write_keeps_the_recorded_size_decision(paths, monkeypatch):
    monkeypatch.setattr("scrolls.media._download", lambda url, **_: (b"new", 3))
    paths.media_dir.mkdir()
    (paths.media_dir / "web").write_bytes(b"")  # a file where the directory must go
    declined = item(media=({"url": "https://example.com/a.png", "oversize": 10, "bytes": 99},))
    updated, results = capture_media(paths, declined, delay=0)
    assert results[0]["status"] == "failed"
    assert updated == declined


def test_doctor_rebuilds_a_scroll_that_is_not_valid_utf8(paths):
    rendered = write_scroll(paths, item())
    insert_item(paths.db_path, rendered)
    target = paths.root / rendered.markdown_path
    target.write_bytes(b"\xff\xfe not text scrolls wrote")
    [entry] = run_doctor(paths, fix=True)["stale_scrolls"]
    assert entry["status"] == "rewritten"
    assert target.read_text() == render_markdown(get_item(paths.db_path, rendered.id))


def test_removal_unlinks_every_path_the_item_records_for_one_file(paths):
    first = paths.media_dir / "a.png"
    first.parent.mkdir()
    first.write_bytes(b"held")
    os.link(first, paths.media_dir / "b.png")
    held = item(media=({"path": "media/a.png"}, {"path": "media/b.png"}))
    insert_item(paths.db_path, held)
    assert remove_item(paths, held) == ["media/a.png", "media/b.png"]
    assert list(paths.media_dir.iterdir()) == []
