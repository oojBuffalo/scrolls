"""Tests for the Google Takeout YouTube watch-history importer (IDEAS.md §13)."""

import json
import zipfile

import pytest

from scrolls.takeout import ImportSourceError, load_watch_history

WATCHED_VIDEO = {
    "header": "YouTube",
    "title": "Watched How SQLite FTS Works",
    "titleUrl": "https://www.youtube.com/watch?v=abc123xyz00",
    "subtitles": [
        {"name": "Some Channel", "url": "https://www.youtube.com/channel/UCsome"}
    ],
    "time": "2024-10-12T18:23:45.123Z",
    "products": ["YouTube"],
    "activityControls": ["YouTube watch history"],
}

# the same video watched again later; Takeout lists newest watches first
REPEAT_WATCH_NEWER = {
    "header": "YouTube",
    "title": "Watched How SQLite FTS Works",
    "titleUrl": "https://www.youtube.com/watch?v=abc123xyz00",
    "subtitles": [
        {"name": "Some Channel", "url": "https://www.youtube.com/channel/UCsome"}
    ],
    "time": "2025-03-01T09:00:00.000Z",
    "products": ["YouTube"],
}

MUSIC_PLAY = {
    "header": "YouTube Music",
    "title": "Watched Some Song",
    "titleUrl": "https://music.youtube.com/watch?v=musicvid001",
    "subtitles": [{"name": "Some Artist - Topic"}],
    "time": "2025-01-01T00:00:00.000Z",
    "products": ["YouTube"],
}

AD_ENTRY = {
    "header": "YouTube",
    "title": "Watched Buy Our Thing",
    "titleUrl": "https://www.youtube.com/watch?v=advideo0001",
    "details": [{"name": "From Google Ads"}],
    "time": "2025-01-02T00:00:00.000Z",
    "products": ["YouTube"],
}

REMOVED_VIDEO = {
    "header": "YouTube",
    "title": "Watched a video that has been removed",
    "time": "2025-01-03T00:00:00.000Z",
    "products": ["YouTube"],
}

POST_VISIT = {
    "header": "YouTube",
    "title": "Viewed a community post",
    "titleUrl": "https://www.youtube.com/post/UgkxSomePostId",
    "time": "2025-01-04T00:00:00.000Z",
    "products": ["YouTube"],
}

ALL_ENTRIES = [
    REPEAT_WATCH_NEWER,
    POST_VISIT,
    REMOVED_VIDEO,
    AD_ENTRY,
    MUSIC_PLAY,
    WATCHED_VIDEO,
]

# Takeout localizes the product directory name; the file name is stable
# enough to discover, and a direct file path is the full escape hatch.
HISTORY_RELPATH = "Takeout/YouTube and YouTube Music/history/watch-history.json"


def _write_history(base, entries):
    history = base / HISTORY_RELPATH
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_text(json.dumps(entries), encoding="utf-8")
    return history


def test_imports_watched_videos_as_detected_items(tmp_path):
    items, stats = load_watch_history(_write_history(tmp_path, [WATCHED_VIDEO]))
    assert len(items) == 1
    item = items[0]
    assert item.id == "youtube:abc123xyz00"
    assert item.source == "youtube"
    assert item.source_id == "abc123xyz00"
    assert item.url == "https://www.youtube.com/watch?v=abc123xyz00"
    assert item.stage == "detected"
    assert item.title == "How SQLite FTS Works"
    assert item.author == "Some Channel"
    assert item.saved_at == "2024-10-12T18:23:45+00:00"
    assert item.published_at is None  # Takeout records watch time, not publish time
    assert stats == {
        "events": 1,
        "repeats": 0,
        "ignored": {"ads": 0, "no_url": 0, "not_video": 0},
    }


def test_repeat_watches_collapse_to_the_earliest(tmp_path):
    items, stats = load_watch_history(
        _write_history(tmp_path, [REPEAT_WATCH_NEWER, WATCHED_VIDEO])
    )
    assert [item.id for item in items] == ["youtube:abc123xyz00"]
    assert items[0].saved_at == "2024-10-12T18:23:45+00:00"
    assert stats["repeats"] == 1


def test_music_plays_are_youtube_items(tmp_path):
    items, _ = load_watch_history(_write_history(tmp_path, [MUSIC_PLAY]))
    assert items[0].id == "youtube:musicvid001"
    assert items[0].title == "Some Song"


def test_ads_removed_videos_and_posts_are_ignored(tmp_path):
    items, stats = load_watch_history(_write_history(tmp_path, ALL_ENTRIES))
    # first-seen (file) order; the repeat watch of abc123xyz00 leads the file
    assert [item.id for item in items] == [
        "youtube:abc123xyz00",
        "youtube:musicvid001",
    ]
    assert stats == {
        "events": 6,
        "repeats": 1,
        "ignored": {"ads": 1, "no_url": 1, "not_video": 1},
    }


def test_title_without_watched_prefix_survives(tmp_path):
    # localized exports phrase the action differently; keep the title as-is
    entry = dict(WATCHED_VIDEO, title="How SQLite FTS Works angesehen")
    items, _ = load_watch_history(_write_history(tmp_path, [entry]))
    assert items[0].title == "How SQLite FTS Works angesehen"


def test_missing_time_falls_back_to_import_time(tmp_path):
    entry = {k: v for k, v in WATCHED_VIDEO.items() if k != "time"}
    items, _ = load_watch_history(_write_history(tmp_path, [entry]))
    assert items[0].saved_at  # never empty: list/doctor rely on saved_at


def test_missing_channel_leaves_author_unset(tmp_path):
    entry = {k: v for k, v in WATCHED_VIDEO.items() if k != "subtitles"}
    items, _ = load_watch_history(_write_history(tmp_path, [entry]))
    assert items[0].author is None


def test_tracking_params_are_stripped_from_urls(tmp_path):
    entry = dict(
        WATCHED_VIDEO,
        titleUrl="https://www.youtube.com/watch?v=abc123xyz00&utm_source=share",
    )
    items, _ = load_watch_history(_write_history(tmp_path, [entry]))
    assert items[0].url == "https://www.youtube.com/watch?v=abc123xyz00"


def test_reads_extracted_takeout_directory(tmp_path):
    _write_history(tmp_path, [WATCHED_VIDEO])
    items, _ = load_watch_history(tmp_path)
    assert [item.id for item in items] == ["youtube:abc123xyz00"]


def test_reads_takeout_zip(tmp_path):
    archive = tmp_path / "takeout.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(HISTORY_RELPATH, json.dumps([WATCHED_VIDEO]))
    items, _ = load_watch_history(archive)
    assert [item.id for item in items] == ["youtube:abc123xyz00"]


def test_missing_path_raises(tmp_path):
    with pytest.raises(ImportSourceError):
        load_watch_history(tmp_path / "nowhere")


def test_directory_without_history_raises(tmp_path):
    (tmp_path / "Takeout").mkdir()
    with pytest.raises(ImportSourceError, match="watch-history.json"):
        load_watch_history(tmp_path)


def test_zip_without_history_raises(tmp_path):
    archive = tmp_path / "takeout.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Takeout/archive_browser.html", "<html></html>")
    with pytest.raises(ImportSourceError, match="watch-history.json"):
        load_watch_history(archive)


def test_invalid_json_raises(tmp_path):
    history = tmp_path / "watch-history.json"
    history.write_text("<html>not the JSON export</html>", encoding="utf-8")
    with pytest.raises(ImportSourceError, match="JSON"):
        load_watch_history(history)


def test_non_list_document_raises(tmp_path):
    history = tmp_path / "watch-history.json"
    history.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(ImportSourceError):
        load_watch_history(history)
