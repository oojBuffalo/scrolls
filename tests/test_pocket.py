"""Tests for the Pocket CSV-export importer (IDEAS.md §13, ADR 0074)."""

import zipfile

import pytest

from scrolls.items import make_item_id
from scrolls.pocket import ImportSourceError, load_pocket_export

# A realistic Pocket data export: the CSV Mozilla mailed users when Pocket
# shut down (header `title,url,time_added,tags,status`). `time_added` is
# epoch seconds, tags are pipe-delimited, and the last row stores the URL
# in the title field — Pocket's "no title" marker.
EXPORT = """\
title,url,time_added,tags,status
SQLite,https://en.wikipedia.org/wiki/SQLite,1600000000,databases|search,unread
How SQLite FTS Works,https://www.youtube.com/watch?v=abc123xyz00,1700000000,,archive
https://example.com/post?utm_source=pocket,https://example.com/post?utm_source=pocket,1600000000,,unread
"""


def _write(tmp_path, text=EXPORT, name="part_000000.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_imports_pocket_rows_as_detected_items(tmp_path):
    items, stats = load_pocket_export(_write(tmp_path))
    assert [item.id for item in items] == [
        "wikipedia:en:SQLite",
        "youtube:abc123xyz00",
        make_item_id("web", None, "https://example.com/post"),
    ]
    article, video, post = items

    assert article.source == "wikipedia"
    assert article.stage == "detected"
    assert article.title == "SQLite"
    # time_added (epoch seconds) becomes saved_at, never published_at
    assert article.saved_at == "2020-09-13T12:26:40+00:00"
    assert article.published_at is None
    # pipe-delimited tags are the user's own curation (the bookmarks-folder analog)
    assert article.tags == ("databases", "search")

    assert video.source == "youtube"
    assert video.source_id == "abc123xyz00"
    assert video.title == "How SQLite FTS Works"
    assert video.saved_at == "2023-11-14T22:13:20+00:00"

    # a title equal to the URL is Pocket's "no title" marker — dropped so
    # fetch fills the real one; tracking params are stripped before identity
    assert post.title is None
    assert post.url == "https://example.com/post"

    assert stats == {
        "rows": 3,
        "repeats": 0,
        "ignored": {"no_url": 0, "not_http": 0},
        "status": {"unread": 2, "archive": 1},
    }


def test_non_http_and_missing_urls_are_ignored(tmp_path):
    text = (
        "title,url,time_added,tags,status\n"
        "Bookmarklet,javascript:void(0),1600000000,,unread\n"
        ",,1600000000,,unread\n"
        "SQLite,https://en.wikipedia.org/wiki/SQLite,1600000000,,unread\n"
    )
    items, stats = load_pocket_export(_write(tmp_path, text))
    assert [item.id for item in items] == ["wikipedia:en:SQLite"]
    # status is tallied for the saves that become items, not for the
    # bookmarklet/blank-URL rows that never enter the library
    assert stats == {
        "rows": 3,
        "repeats": 0,
        "ignored": {"no_url": 1, "not_http": 1},
        "status": {"unread": 1, "archive": 0},
    }


def test_duplicate_urls_collapse_earliest_wins_tags_union(tmp_path):
    text = (
        "title,url,time_added,tags,status\n"
        "Newer,https://en.wikipedia.org/wiki/SQLite,1700000000,fresh,unread\n"
        "Older,https://en.wikipedia.org/wiki/SQLite,1600000000,early,archive\n"
    )
    items, stats = load_pocket_export(_write(tmp_path, text))
    assert len(items) == 1
    (article,) = items
    # earliest time_added wins saved_at (and its row's title); tags union
    # across both occurrences in encounter order
    assert article.title == "Older"
    assert article.saved_at == "2020-09-13T12:26:40+00:00"
    assert article.tags == ("fresh", "early")
    assert stats["repeats"] == 1
    assert stats["rows"] == 2


def test_missing_time_falls_back_to_import_time(tmp_path):
    text = (
        "title,url,time_added,tags,status\n"
        "SQLite,https://en.wikipedia.org/wiki/SQLite,,,unread\n"
    )
    items, _ = load_pocket_export(_write(tmp_path, text))
    # an absent/zero time_added is not stored as garbage; saved_at falls back
    # to the import time (a real UTC ISO timestamp), published_at stays unset
    assert items[0].saved_at is not None
    assert items[0].published_at is None


def test_quoted_field_with_comma_survives(tmp_path):
    text = (
        "title,url,time_added,tags,status\n"
        '"SQLite, the database",https://en.wikipedia.org/wiki/SQLite,1600000000,,unread\n'
    )
    items, _ = load_pocket_export(_write(tmp_path, text))
    assert items[0].title == "SQLite, the database"


def test_reads_zip_of_csv_parts(tmp_path):
    archive = tmp_path / "pocket.zip"
    header = "title,url,time_added,tags,status\n"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "part_000000.csv",
            header + "SQLite,https://en.wikipedia.org/wiki/SQLite,1600000000,,unread\n",
        )
        zf.writestr(
            "part_000001.csv",
            header
            + "How SQLite FTS Works,https://www.youtube.com/watch?v=abc123xyz00,1600000000,,unread\n",
        )
        zf.writestr("README.txt", "not a csv")  # non-CSV members are skipped
    items, stats = load_pocket_export(archive)
    assert {item.id for item in items} == {"wikipedia:en:SQLite", "youtube:abc123xyz00"}
    assert stats["rows"] == 2


def test_reads_directory_of_csv_parts(tmp_path):
    header = "title,url,time_added,tags,status\n"
    _write(
        tmp_path,
        header + "SQLite,https://en.wikipedia.org/wiki/SQLite,1600000000,,unread\n",
        "part_000000.csv",
    )
    _write(
        tmp_path,
        header
        + "How SQLite FTS Works,https://www.youtube.com/watch?v=abc123xyz00,1600000000,,unread\n",
        "part_000001.csv",
    )
    items, _ = load_pocket_export(tmp_path)
    assert {item.id for item in items} == {"wikipedia:en:SQLite", "youtube:abc123xyz00"}


def test_bom_prefixed_csv_is_read(tmp_path):
    path = tmp_path / "part_000000.csv"
    path.write_bytes(b"\xef\xbb\xbf" + EXPORT.encode("utf-8"))
    items, _ = load_pocket_export(path)
    # the BOM must not corrupt the first header cell (`title`), which would
    # otherwise hide the `url` column and fail the export
    assert items[0].id == "wikipedia:en:SQLite"


def test_zip_with_a_non_pocket_csv_part_skips_it(tmp_path):
    archive = tmp_path / "pocket.zip"
    header = "title,url,time_added,tags,status\n"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "part_000000.csv",
            header + "SQLite,https://en.wikipedia.org/wiki/SQLite,1600000000,,unread\n",
        )
        # a stray CSV with no url column must not abort the whole export
        zf.writestr("notes.csv", "comment,body\nhi,there\n")
    items, _ = load_pocket_export(archive)
    assert [item.id for item in items] == ["wikipedia:en:SQLite"]


def test_directory_with_a_non_pocket_csv_part_skips_it(tmp_path):
    header = "title,url,time_added,tags,status\n"
    _write(
        tmp_path,
        header + "SQLite,https://en.wikipedia.org/wiki/SQLite,1600000000,,unread\n",
        "part_000000.csv",
    )
    _write(tmp_path, "comment,body\nhi,there\n", "notes.csv")
    items, _ = load_pocket_export(tmp_path)
    assert [item.id for item in items] == ["wikipedia:en:SQLite"]


def test_zip_with_no_pocket_shaped_csv_raises(tmp_path):
    archive = tmp_path / "pocket.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("notes.csv", "comment,body\nhi,there\n")
    with pytest.raises(ImportSourceError, match="url"):
        load_pocket_export(archive)


def test_missing_path_raises(tmp_path):
    with pytest.raises(ImportSourceError):
        load_pocket_export(tmp_path / "nowhere")


def test_csv_without_a_url_column_raises(tmp_path):
    text = "title,link,added\nSQLite,https://en.wikipedia.org/wiki/SQLite,1600000000\n"
    with pytest.raises(ImportSourceError, match="url"):
        load_pocket_export(_write(tmp_path, text))


def test_empty_zip_raises(tmp_path):
    archive = tmp_path / "pocket.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("README.txt", "no csv parts here")
    with pytest.raises(ImportSourceError, match="csv"):
        load_pocket_export(archive)
