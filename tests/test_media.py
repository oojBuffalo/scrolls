"""Tests for media capture (`src/scrolls/media.py`, ADR 0011)."""

import urllib.error

import pytest

import scrolls.media as media
from scrolls.items import ScrollItem
from scrolls.media import capture_media, has_pending_media
from scrolls.paths import get_paths


@pytest.fixture
def paths(tmp_path):
    p = get_paths(tmp_path / "home")
    p.root.mkdir(parents=True)
    return p


def make_item(**overrides):
    base = dict(
        id="arxiv:1706.03762",
        source="arxiv",
        source_id="1706.03762",
        url="https://arxiv.org/abs/1706.03762",
        saved_at="2026-06-12T08:00:00+00:00",
        media=({"type": "pdf", "url": "https://arxiv.org/pdf/1706.03762"},),
    )
    base.update(overrides)
    return ScrollItem(**base)


def test_capture_downloads_ref_and_records_root_relative_path(paths, monkeypatch):
    monkeypatch.setattr(media, "_get_bytes", lambda url: b"%PDF-1.4 fake")
    item = make_item()

    updated, results = capture_media(paths, item)

    target = paths.root / "media" / "arxiv" / "1706-03762-1.pdf"
    assert target.read_bytes() == b"%PDF-1.4 fake"
    assert updated.media[0] == {
        "type": "pdf",
        "url": "https://arxiv.org/pdf/1706.03762",
        "path": "media/arxiv/1706-03762-1.pdf",
    }
    assert results == [
        {
            "url": "https://arxiv.org/pdf/1706.03762",
            "status": "captured",
            "path": "media/arxiv/1706-03762-1.pdf",
        }
    ]


def test_capture_extension_comes_from_url_path(paths, monkeypatch):
    monkeypatch.setattr(media, "_get_bytes", lambda url: b"jpeg-bytes")
    item = make_item(
        id="youtube:abc123",
        source="youtube",
        source_id="abc123",
        url="https://youtube.com/watch?v=abc123",
        media=({"type": "thumbnail", "url": "https://i.ytimg.com/vi/abc123/hqdefault.jpg"},),
    )

    updated, _ = capture_media(paths, item)

    assert updated.media[0]["path"] == "media/youtube/abc123-1.jpg"
    assert (paths.root / "media" / "youtube" / "abc123-1.jpg").exists()


def test_capture_extension_falls_back_to_ref_type(paths, monkeypatch):
    monkeypatch.setattr(media, "_get_bytes", lambda url: b"bytes")
    item = make_item(
        id="x:1111",
        source="x",
        source_id="1111",
        url="https://x.com/karpathy/status/1111",
        media=(
            # pbs URLs carry the format in the query, not the path
            {"type": "photo", "url": "https://pbs.twimg.com/media/GExyzAB?format=jpg"},
            {"type": "mystery", "url": "https://example.com/blob"},
        ),
    )

    updated, _ = capture_media(paths, item)

    assert updated.media[0]["path"] == "media/x/1111-1.jpg"
    assert updated.media[1]["path"] == "media/x/1111-2.bin"


def test_capture_skips_already_captured_refs(paths, monkeypatch):
    def boom(url):
        raise AssertionError("network must not be touched")

    monkeypatch.setattr(media, "_get_bytes", boom)
    relpath = "media/arxiv/1706-03762-1.pdf"
    target = paths.root / relpath
    target.parent.mkdir(parents=True)
    target.write_bytes(b"already here")
    item = make_item(
        media=({"type": "pdf", "url": "https://arxiv.org/pdf/1706.03762", "path": relpath},)
    )

    updated, results = capture_media(paths, item)

    assert updated is item
    assert results == [
        {"url": "https://arxiv.org/pdf/1706.03762", "status": "skipped", "path": relpath}
    ]


def test_capture_redownloads_to_recorded_path_when_file_missing(paths, monkeypatch):
    monkeypatch.setattr(media, "_get_bytes", lambda url: b"healed")
    relpath = "media/arxiv/1706-03762-1.pdf"
    item = make_item(
        media=({"type": "pdf", "url": "https://arxiv.org/pdf/1706.03762", "path": relpath},)
    )

    updated, results = capture_media(paths, item)

    assert (paths.root / relpath).read_bytes() == b"healed"
    assert updated.media[0]["path"] == relpath
    assert results[0]["status"] == "captured"


def test_capture_force_overwrites_existing_file(paths, monkeypatch):
    monkeypatch.setattr(media, "_get_bytes", lambda url: b"version 2")
    relpath = "media/arxiv/1706-03762-1.pdf"
    target = paths.root / relpath
    target.parent.mkdir(parents=True)
    target.write_bytes(b"version 1")
    item = make_item(
        media=({"type": "pdf", "url": "https://arxiv.org/pdf/1706.03762", "path": relpath},)
    )

    _, results = capture_media(paths, item, force=True)

    assert target.read_bytes() == b"version 2"
    assert results[0]["status"] == "captured"


def test_capture_failure_keeps_other_refs(paths, monkeypatch):
    def get_bytes(url):
        if "bad" in url:
            raise urllib.error.URLError("connection refused")
        return b"good bytes"

    monkeypatch.setattr(media, "_get_bytes", get_bytes)
    item = make_item(
        id="x:2222",
        source="x",
        source_id="2222",
        url="https://x.com/simonw/status/2222",
        media=(
            {"type": "photo", "url": "https://pbs.twimg.com/bad"},
            {"type": "photo", "url": "https://pbs.twimg.com/fine.png"},
        ),
    )

    updated, results = capture_media(paths, item)

    assert results[0]["status"] == "failed"
    assert "connection refused" in results[0]["error"]
    assert "path" not in updated.media[0]
    assert results[1]["status"] == "captured"
    assert updated.media[1]["path"] == "media/x/2222-2.png"
    assert (paths.root / "media" / "x" / "2222-2.png").read_bytes() == b"good bytes"


def test_capture_skips_refs_without_a_url(paths, monkeypatch):
    def boom(url):
        raise AssertionError("network must not be touched")

    monkeypatch.setattr(media, "_get_bytes", boom)
    # a typeless dict and a legacy bare string must not crash capture
    item = make_item(media=({"type": "thumbnail"}, "https://example.com/legacy.jpg"))

    updated, results = capture_media(paths, item)

    assert updated is item
    assert [r["status"] for r in results] == ["skipped", "skipped"]


def test_has_pending_media_only_for_uncaptured_url_refs(paths):
    relpath = "media/arxiv/1706-03762-1.pdf"
    target = paths.root / relpath
    target.parent.mkdir(parents=True)
    target.write_bytes(b"here")

    captured = make_item(
        media=({"type": "pdf", "url": "https://arxiv.org/pdf/1706.03762", "path": relpath},)
    )
    pending = make_item(media=({"type": "pdf", "url": "https://arxiv.org/pdf/1706.03762"},))
    no_media = make_item(media=())
    urlless = make_item(media=({"type": "thumbnail"},))

    assert not has_pending_media(paths, captured)
    assert has_pending_media(paths, pending)
    assert not has_pending_media(paths, no_media)
    assert not has_pending_media(paths, urlless)


def test_has_pending_media_when_recorded_file_was_deleted(paths):
    item = make_item(
        media=(
            {
                "type": "pdf",
                "url": "https://arxiv.org/pdf/1706.03762",
                "path": "media/arxiv/1706-03762-1.pdf",
            },
        )
    )
    assert has_pending_media(paths, item)
