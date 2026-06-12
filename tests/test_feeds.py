"""Tests for feed subscriptions and sync (IDEAS.md §13, ADR 0017).

`parse_feed` understands RSS 2.0 and Atom via stdlib ElementTree;
`follow_feed` validates a feed by fetching it once before storing the
subscription; `sync_subscription` registers new entry URLs as detected
items through the same detection/dedupe path as `scrolls add`. No test
touches the network — the fetcher is injected everywhere.
"""

import pytest

from scrolls.db import init_db
from scrolls.feeds import (
    Feed,
    FeedEntry,
    FeedError,
    Subscription,
    follow_feed,
    get_subscription,
    insert_subscription,
    list_subscriptions,
    make_subscription_id,
    parse_feed,
    remove_subscription,
    sync_subscription,
    to_feed_url,
)
from scrolls.items import get_item
from scrolls.paths import get_paths

ATOM_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <title>Two Minute Papers</title>
  <entry>
    <id>yt:video:abc123def45</id>
    <title>New Paper!</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=abc123def45"/>
  </entry>
  <entry>
    <id>yt:video:xyz987uvw65</id>
    <title>Another Paper!</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=xyz987uvw65"/>
  </entry>
</feed>
"""

RSS_FEED = """\
<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>A Weblog</title>
    <link>https://blog.example.com/</link>
    <item>
      <title>Post one</title>
      <link>https://blog.example.com/2026/post-one/</link>
    </item>
    <item>
      <title>Linkless item is dropped</title>
    </item>
    <item>
      <title>Post two</title>
      <link>https://blog.example.com/2026/post-two/</link>
    </item>
  </channel>
</rss>
"""


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "db.sqlite"
    init_db(path)
    return path


def _sub(feed_url, **overrides):
    defaults = {
        "id": make_subscription_id(feed_url),
        "feed_url": feed_url,
        "title": "A Feed",
        "added_at": "2026-06-12T08:00:00+00:00",
    }
    return Subscription(**{**defaults, **overrides})


# --- to_feed_url ---


def test_to_feed_url_passes_feed_urls_through():
    url = "https://blog.example.com/atom.xml"
    assert to_feed_url(f"  {url} ") == url


def test_to_feed_url_maps_youtube_playlist_to_its_feed():
    assert (
        to_feed_url("https://www.youtube.com/playlist?list=PLabc123")
        == "https://www.youtube.com/feeds/videos.xml?playlist_id=PLabc123"
    )


def test_to_feed_url_maps_youtube_channel_id_to_its_feed():
    assert (
        to_feed_url("https://www.youtube.com/channel/UCabc123/videos")
        == "https://www.youtube.com/feeds/videos.xml?channel_id=UCabc123"
    )


def test_to_feed_url_leaves_youtube_feed_urls_alone():
    url = "https://www.youtube.com/feeds/videos.xml?channel_id=UCabc123"
    assert to_feed_url(url) == url


def test_to_feed_url_rejects_non_http_url():
    with pytest.raises(ValueError, match="http"):
        to_feed_url("ftp://example.com/feed.xml")


# --- parse_feed ---


def test_parse_feed_atom():
    feed = parse_feed(ATOM_FEED)
    assert feed == Feed(
        title="Two Minute Papers",
        entries=(
            FeedEntry(url="https://www.youtube.com/watch?v=abc123def45", title="New Paper!"),
            FeedEntry(url="https://www.youtube.com/watch?v=xyz987uvw65", title="Another Paper!"),
        ),
    )


def test_parse_feed_rss_drops_linkless_items():
    feed = parse_feed(RSS_FEED)
    assert feed.title == "A Weblog"
    assert [entry.url for entry in feed.entries] == [
        "https://blog.example.com/2026/post-one/",
        "https://blog.example.com/2026/post-two/",
    ]


def test_parse_feed_rejects_html():
    with pytest.raises(FeedError, match="RSS 2.0 or Atom"):
        parse_feed("<html><body>not a feed</body></html>")


def test_parse_feed_rejects_garbage():
    with pytest.raises(FeedError, match="parseable"):
        parse_feed("certainly { not xml")


# --- subscription persistence ---


def test_subscription_roundtrip(db_path):
    sub = _sub("https://blog.example.com/atom.xml")
    assert insert_subscription(db_path, sub) is True
    assert get_subscription(db_path, sub.id) == sub
    assert list_subscriptions(db_path) == [sub]


def test_insert_subscription_dedupes_by_id(db_path):
    sub = _sub("https://blog.example.com/atom.xml")
    insert_subscription(db_path, sub)
    assert insert_subscription(db_path, _sub("https://blog.example.com/atom.xml")) is False
    assert len(list_subscriptions(db_path)) == 1


def test_remove_subscription(db_path):
    sub = _sub("https://blog.example.com/atom.xml")
    insert_subscription(db_path, sub)
    assert remove_subscription(db_path, sub.id) is True
    assert list_subscriptions(db_path) == []
    assert remove_subscription(db_path, sub.id) is False


# --- sync_subscription ---


def test_sync_registers_new_items_as_detected(db_path):
    sub = _sub("https://www.youtube.com/feeds/videos.xml?channel_id=UCabc123")
    insert_subscription(db_path, sub)

    result = sync_subscription(db_path, sub, get_text=lambda url: ATOM_FEED)

    assert result["status"] == "synced"
    assert result["new"] == 2 and result["known"] == 0 and result["skipped"] == 0
    assert result["new_items"] == ["youtube:abc123def45", "youtube:xyz987uvw65"]
    item = get_item(db_path, "youtube:abc123def45")
    assert item.source == "youtube" and item.stage == "detected"
    assert get_subscription(db_path, sub.id).last_synced_at is not None


def test_sync_second_run_reports_known(db_path):
    sub = _sub("https://www.youtube.com/feeds/videos.xml?channel_id=UCabc123")
    insert_subscription(db_path, sub)
    sync_subscription(db_path, sub, get_text=lambda url: ATOM_FEED)

    result = sync_subscription(db_path, sub, get_text=lambda url: ATOM_FEED)
    assert result["new"] == 0 and result["known"] == 2
    assert result["new_items"] == []


def test_sync_skips_entries_without_http_links(db_path):
    feed = """\
<rss version="2.0"><channel><title>T</title>
<item><title>ok</title><link>https://blog.example.com/post</link></item>
<item><title>bad</title><link>mailto:author@example.com</link></item>
</channel></rss>"""
    sub = _sub("https://blog.example.com/rss")
    insert_subscription(db_path, sub)

    result = sync_subscription(db_path, sub, get_text=lambda url: feed)
    assert result["new"] == 1 and result["skipped"] == 1


def test_sync_fetch_failure_raises_feed_error(db_path):
    sub = _sub("https://blog.example.com/atom.xml")
    insert_subscription(db_path, sub)

    def boom(url):
        raise OSError("connection refused")

    with pytest.raises(FeedError, match="connection refused"):
        sync_subscription(db_path, sub, get_text=boom)
    assert get_subscription(db_path, sub.id).last_synced_at is None


def test_sync_unparseable_feed_raises_feed_error(db_path):
    sub = _sub("https://blog.example.com/atom.xml")
    insert_subscription(db_path, sub)
    with pytest.raises(FeedError):
        sync_subscription(db_path, sub, get_text=lambda url: "<html></html>")


# --- follow_feed ---


def test_follow_feed_validates_and_stores_subscription(scrolls_home):
    paths, sub, created = follow_feed(
        "https://blog.example.com/atom.xml", get_text=lambda url: RSS_FEED
    )
    assert created is True
    assert sub.title == "A Weblog"
    assert sub.feed_url == "https://blog.example.com/atom.xml"
    assert get_paths().db_path == paths.db_path
    assert list_subscriptions(paths.db_path) == [sub]


def test_follow_feed_is_idempotent(scrolls_home):
    follow_feed("https://blog.example.com/atom.xml", get_text=lambda url: RSS_FEED)
    paths, sub, created = follow_feed(
        "https://blog.example.com/atom.xml", get_text=lambda url: RSS_FEED
    )
    assert created is False
    assert len(list_subscriptions(paths.db_path)) == 1


def test_follow_feed_transforms_youtube_playlist_urls(scrolls_home):
    _, sub, _ = follow_feed(
        "https://www.youtube.com/playlist?list=PLabc123", get_text=lambda url: ATOM_FEED
    )
    assert sub.feed_url == "https://www.youtube.com/feeds/videos.xml?playlist_id=PLabc123"


def test_follow_feed_bad_feed_stores_nothing(scrolls_home):
    paths = get_paths()
    from scrolls.pipeline import ensure_library

    ensure_library(paths)
    with pytest.raises(FeedError):
        follow_feed("https://blog.example.com/page", get_text=lambda url: "<html></html>")
    assert list_subscriptions(paths.db_path) == []
