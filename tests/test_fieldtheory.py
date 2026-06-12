"""Tests for the Field Theory bookmark importer (IDEAS.md §7)."""

import json

import pytest

from scrolls.fieldtheory import ImportSourceError, load_bookmarks

RECORD_FULL = {
    "id": "1111",
    "tweetId": "1111",
    "url": "https://x.com/karpathy/status/1111",
    "text": "SQLite FTS5 is criminally underrated.\nUse it for local search.",
    "authorHandle": "karpathy",
    "authorName": "Andrej Karpathy",
    "postedAt": "Mon Jun 01 15:34:00 +0000 2026",
    "bookmarkedAt": None,
    "syncedAt": "2026-06-04T04:27:46.057Z",
    "language": "en",
    "engagement": {"likeCount": 5, "repostCount": 1},
    "media": ["https://pbs.twimg.com/media/abc.png"],
    "mediaObjects": [
        {"type": "photo", "url": "https://pbs.twimg.com/media/abc.png"}
    ],
    "links": ["https://sqlite.org/fts5.html"],
    "tags": ["search"],
}

RECORD_QUOTING = {
    "id": "2222",
    "tweetId": "2222",
    "url": "https://x.com/someone/status/2222",
    "text": "This holds up well.",
    "authorHandle": "someone",
    "authorName": "Some One",
    "postedAt": "Tue Jun 02 08:00:00 +0000 2026",
    "bookmarkedAt": "2026-06-05T10:00:00.000Z",
    "syncedAt": "2026-06-06T00:00:00.000Z",
    "media": [],
    "mediaObjects": [],
    "links": [],
    "tags": [],
    "quotedTweet": {
        "id": "3333",
        "text": "Local-first software wins.",
        "authorHandle": "quoted_author",
    },
}

FT_LIBRARY_PAGE = """\
---
author: "@karpathy"
posted_at: 2026-06-01
category: technique
domain: databases
categories: [technique, tool]
source_url: https://x.com/karpathy/status/1111
tweet_id: "1111"
likes: 5
---

# @karpathy

SQLite FTS5 is criminally underrated.
"""


@pytest.fixture
def ft_root(tmp_path):
    """A miniature ~/.fieldtheory with two bookmarks and one classified page."""
    root = tmp_path / "fieldtheory"
    (root / "bookmarks").mkdir(parents=True)
    lines = [json.dumps(RECORD_FULL), json.dumps(RECORD_QUOTING)]
    (root / "bookmarks" / "bookmarks.jsonl").write_text("\n".join(lines) + "\n")
    pages = root / "library" / "bookmarks"
    pages.mkdir(parents=True)
    (pages / "2026-06-01-karpathy-sqlite.md").write_text(FT_LIBRARY_PAGE)
    return root


def test_imports_records_as_fetched_x_items(ft_root):
    items, failures = load_bookmarks(ft_root)
    assert failures == []
    assert [item.id for item in items] == ["x:1111", "x:2222"]
    item = items[0]
    assert item.source == "x"
    assert item.source_id == "1111"
    assert item.url == "https://x.com/karpathy/status/1111"
    assert item.stage == "fetched"


def test_maps_text_author_and_dates(ft_root):
    item = load_bookmarks(ft_root)[0][0]
    assert item.title == "@karpathy: SQLite FTS5 is criminally underrated. Use it for local search."
    assert item.author == "Andrej Karpathy (@karpathy)"
    assert item.published_at == "2026-06-01T15:34:00+00:00"
    # bookmarkedAt is null -> falls back to syncedAt, normalized to ISO seconds
    assert item.saved_at == "2026-06-04T04:27:46+00:00"
    assert "SQLite FTS5 is criminally underrated." in item.extracted_text
    assert item.raw_text == json.dumps(RECORD_FULL)
    assert item.tags == ("search",)
    assert item.links == ("https://sqlite.org/fts5.html",)
    assert item.media == ({"type": "photo", "url": "https://pbs.twimg.com/media/abc.png"},)
    assert item.content_hash and item.content_hash.startswith("sha256:")
    assert item.provenance["adapter"] == "fieldtheory-import"


def test_long_text_truncates_title():
    record = dict(RECORD_FULL, text="word " * 60)
    items, _ = _load_single(record)
    assert len(items[0].title) <= 80
    assert items[0].title.endswith("…")


def test_joins_category_and_domain_from_ft_library(ft_root):
    items, _ = load_bookmarks(ft_root)
    assert items[0].category == "technique"
    assert items[0].domain == "databases"
    # the second bookmark has no classified page
    assert items[1].category is None
    assert items[1].domain is None


def test_quoted_tweet_text_is_appended(ft_root):
    item = load_bookmarks(ft_root)[0][1]
    assert "This holds up well." in item.extracted_text
    assert "Quoting @quoted_author: Local-first software wins." in item.extracted_text
    # bookmarkedAt present -> wins over syncedAt
    assert item.saved_at == "2026-06-05T10:00:00+00:00"


def test_import_works_without_ft_library_pages(tmp_path):
    root = tmp_path / "ft"
    (root / "bookmarks").mkdir(parents=True)
    (root / "bookmarks" / "bookmarks.jsonl").write_text(json.dumps(RECORD_FULL) + "\n")
    items, failures = load_bookmarks(root)
    assert failures == []
    assert items[0].category is None


def test_malformed_lines_are_reported_not_fatal(tmp_path):
    root = tmp_path / "ft"
    (root / "bookmarks").mkdir(parents=True)
    (root / "bookmarks" / "bookmarks.jsonl").write_text(
        "not json\n" + json.dumps(RECORD_FULL) + "\n" + json.dumps({"text": "no id"}) + "\n"
    )
    items, failures = load_bookmarks(root)
    assert [item.id for item in items] == ["x:1111"]
    assert len(failures) == 2
    assert failures[0]["line"] == 1
    assert failures[1]["line"] == 3


def test_missing_jsonl_raises(tmp_path):
    with pytest.raises(ImportSourceError):
        load_bookmarks(tmp_path / "nowhere")


def test_unparseable_posted_at_keeps_item(tmp_path):
    record = dict(RECORD_FULL, postedAt="garbage")
    items, failures = _load_single(record, tmp_path=tmp_path)
    assert failures == []
    assert items[0].published_at is None


def _load_single(record, tmp_path=None):
    import tempfile
    from pathlib import Path

    base = Path(tempfile.mkdtemp()) if tmp_path is None else tmp_path
    root = base / "ft-single"
    (root / "bookmarks").mkdir(parents=True)
    (root / "bookmarks" / "bookmarks.jsonl").write_text(json.dumps(record) + "\n")
    return load_bookmarks(root)
