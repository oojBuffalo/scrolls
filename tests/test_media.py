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


# --- rate limiting -----------------------------------------------------------
#
# Wikimedia answers a bulk capture with HTTP 429 once the request rate climbs.
# A capture that reports 456 of 473 items "failed" against a host that was only
# asking us to slow down is not a failure of custody, it is a failure of
# manners: the files are still there, we just asked too fast.


def _http_error(code, headers=None):
    import urllib.error

    return urllib.error.HTTPError(
        "https://u.w/a.jpg", code, "rate limited", headers or {}, None
    )


def test_a_rate_limited_download_is_retried_rather_than_failed(paths, monkeypatch):
    item = make_item()
    calls = []
    slept = []

    def flaky(url, *args, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise _http_error(429)
        return b"payload"

    monkeypatch.setattr(media, "_get_bytes", flaky)
    updated, results = capture_media(paths, item, sleep=slept.append)

    assert [r["status"] for r in results] == ["captured"]
    assert len(calls) == 2
    assert slept, "a 429 must be waited out, not hammered"


def test_a_persistent_rate_limit_fails_saying_so(paths, monkeypatch):
    item = make_item()

    def always_limited(url, *args, **kwargs):
        raise _http_error(429)

    monkeypatch.setattr(media, "_get_bytes", always_limited)
    _, results = capture_media(paths, item, sleep=lambda _s: None, max_attempts=2)

    assert results[0]["status"] == "failed"
    assert "rate limit" in results[0]["error"].lower()


def test_retry_after_is_honored_when_the_host_names_a_wait(paths, monkeypatch):
    item = make_item()
    slept = []
    calls = []

    def flaky(url, *args, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise _http_error(429, {"retry-after": "7"})
        return b"payload"

    monkeypatch.setattr(media, "_get_bytes", flaky)
    capture_media(paths, item, sleep=slept.append)

    assert slept[0] == 7.0


def test_downloads_are_paced_between_files(paths, monkeypatch):
    """Politeness is what keeps a bulk capture from earning the 429."""
    item = make_item(
        media=(
            {"type": "pdf", "url": "https://u.w/a.pdf"},
            {"type": "pdf", "url": "https://u.w/b.pdf"},
        )
    )
    slept = []
    monkeypatch.setattr(media, "_get_bytes", lambda *a, **k: b"payload")

    capture_media(paths, item, sleep=slept.append, delay=0.25)

    assert slept == [0.25, 0.25]


def test_a_non_rate_limit_error_is_not_retried(paths, monkeypatch):
    item = make_item()
    calls = []

    def gone(url, *args, **kwargs):
        calls.append(url)
        raise _http_error(404)

    monkeypatch.setattr(media, "_get_bytes", gone)
    _, results = capture_media(paths, item, sleep=lambda _s: None)

    assert results[0]["status"] == "failed"
    assert len(calls) == 1
