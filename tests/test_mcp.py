"""Tests for the MCP server (IDEAS.md §10, ADR 0014).

The tool functions are plain wrappers over the same engines the CLI
uses, so they are tested directly against a temp library — no protocol
client, no network (the wikipedia transport is faked). One test builds
the real FastMCP server to lock the registered tool surface.
"""

import asyncio

import pytest

import scrolls.sources.wikipedia as wikipedia
from scrolls import mcp_server
from scrolls.kb import compile_kb
from scrolls.paths import get_paths


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


@pytest.fixture
def fake_wikipedia_api(monkeypatch):
    """Serve a canned MediaWiki extracts payload instead of the network."""
    payload = {
        "query": {
            "pages": [
                {
                    "pageid": 25387,
                    "title": "SQLite",
                    "fullurl": "https://en.wikipedia.org/wiki/SQLite",
                    "canonicalurl": "https://en.wikipedia.org/wiki/SQLite",
                    "extract": "SQLite is a database engine.\n\n\n== History ==\nEarly days.",
                    "categories": [
                        {"ns": 14, "title": "Category:Database management systems"}
                    ],
                }
            ]
        }
    }
    monkeypatch.setattr(wikipedia, "_get_json", lambda url: payload)
    return payload


@pytest.fixture
def fake_feed(monkeypatch):
    """A two-entry blog feed; serves an ETag and honors it with a 304."""
    import scrolls.feeds as feeds
    from scrolls.sources.http import ConditionalText

    document = """\
<rss version="2.0"><channel><title>A Weblog</title>
<item><title>Post one</title><link>https://blog.example.com/2026/post-one/</link></item>
<item><title>Post two</title><link>https://blog.example.com/2026/post-two/</link></item>
</channel></rss>"""
    url = "https://blog.example.com/atom.xml"

    def get_text(u):
        if u != url:
            raise OSError(f"connection refused: {u}")
        return document

    def get_conditional(u, etag, last_modified):
        if etag == 'W/"v1"':
            return ConditionalText(not_modified=True)
        return ConditionalText(text=get_text(u), etag='W/"v1"')

    monkeypatch.setattr(feeds, "_get_text", get_text)
    monkeypatch.setattr(feeds, "_get_conditional", get_conditional)
    return url


def test_server_exposes_exactly_the_documented_tools(scrolls_home):
    server = mcp_server.build_server()
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == {
        "search_scrolls",
        "get_scroll",
        "get_related_scrolls",
        "get_context_bundle",
        "get_concept_page",
        "list_sources",
        "ingest_url",
        "follow_feed",
        "unfollow_feed",
        "list_feed_subscriptions",
        "sync_feeds",
    }
    # every tool teaches the model what it does
    assert all(tool.description for tool in tools)


def test_ingest_url_returns_the_cli_payload(scrolls_home, fake_wikipedia_api):
    payload = mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    assert payload["id"] == "wikipedia:en:SQLite"
    assert payload["title"] == "SQLite"
    assert payload["category"] == "reference"
    assert payload["stage"] == "rendered"
    assert "error" not in payload


def test_ingest_url_without_adapter_reports_error_as_data(scrolls_home):
    payload = mcp_server.ingest_url("https://x.com/karpathy/status/1111")
    assert payload["stage"] == "detected"
    assert "no fetch adapter" in payload["error"]


def test_search_scrolls_finds_ingested_content(scrolls_home, fake_wikipedia_api):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    hits = mcp_server.search_scrolls("database engine")
    assert [hit["id"] for hit in hits] == ["wikipedia:en:SQLite"]
    assert hits[0]["snippet"]


def test_search_scrolls_before_init_returns_empty(scrolls_home):
    assert mcp_server.search_scrolls("anything") == []


def test_get_scroll_returns_the_full_item(scrolls_home, fake_wikipedia_api):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    item = mcp_server.get_scroll("wikipedia:en:SQLite")
    assert item["title"] == "SQLite"
    assert item["concepts"] == ["Database management systems"]
    assert item["markdown_path"] == "scrolls/wikipedia/sqlite.md"


def test_get_scroll_unknown_id_raises(scrolls_home):
    with pytest.raises(ValueError, match="no such item"):
        mcp_server.get_scroll("x:9999")


def test_get_related_scrolls_for_lonely_item_is_empty(scrolls_home, fake_wikipedia_api):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    assert mcp_server.get_related_scrolls("wikipedia:en:SQLite") == []


def test_get_context_bundle_is_markdown(scrolls_home, fake_wikipedia_api):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    bundle = mcp_server.get_context_bundle("database engine")
    assert bundle.startswith("# Scrolls Context Bundle: database engine")
    assert "wikipedia:en:SQLite" in bundle


def test_get_concept_page_round_trips_spelling_via_slug(scrolls_home, fake_wikipedia_api):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    compile_kb(get_paths())
    page = mcp_server.get_concept_page("database MANAGEMENT systems")
    assert "# Concept: Database management systems" in page
    assert "SQLite" in page


def test_get_concept_page_missing_raises_with_remedy(scrolls_home):
    with pytest.raises(ValueError, match="scrolls kb"):
        mcp_server.get_concept_page("nonexistent concept")


def test_list_sources_counts_items(scrolls_home, fake_wikipedia_api):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    mcp_server.ingest_url("https://x.com/karpathy/status/1111")  # stays detected
    assert mcp_server.list_sources() == {"wikipedia": 1, "x": 1}


def test_list_sources_before_init_is_empty(scrolls_home):
    assert mcp_server.list_sources() == {}


# --- feed subscriptions (ADR 0020) ---


def test_follow_feed_subscribes_and_lists(scrolls_home, fake_feed):
    payload = mcp_server.follow_feed(fake_feed)
    assert payload["feed_url"] == fake_feed
    assert payload["title"] == "A Weblog"
    assert payload["created"] is True

    listed = mcp_server.list_feed_subscriptions()
    assert [sub["feed_url"] for sub in listed] == [fake_feed]


def test_follow_feed_unreachable_url_raises(scrolls_home, fake_feed):
    from scrolls.feeds import FeedError

    with pytest.raises(FeedError, match="connection refused"):
        mcp_server.follow_feed("https://nowhere.example.com/feed")
    assert mcp_server.list_feed_subscriptions() == []


def test_list_feed_subscriptions_before_init_is_empty(scrolls_home):
    assert mcp_server.list_feed_subscriptions() == []


def test_sync_feeds_registers_entries_then_reports_unchanged(scrolls_home, fake_feed):
    mcp_server.follow_feed(fake_feed)

    first = mcp_server.sync_feeds()
    assert first["new"] == 2 and first["failed"] == 0
    assert first["results"][0]["status"] == "synced"

    second = mcp_server.sync_feeds()  # the stored ETag now answers 304
    assert second["unchanged"] == 1 and second["new"] == 0
    assert second["results"][0]["status"] == "unchanged"


def test_sync_feeds_by_unknown_id_raises(scrolls_home):
    with pytest.raises(ValueError, match="no such subscription"):
        mcp_server.sync_feeds("feedcafe1234")


def test_sync_feeds_before_init_is_empty_success(scrolls_home):
    payload = mcp_server.sync_feeds()
    assert payload["results"] == [] and payload["failed"] == 0


def test_unfollow_feed_accepts_id_or_url(scrolls_home, fake_feed):
    sub_id = mcp_server.follow_feed(fake_feed)["id"]
    assert mcp_server.unfollow_feed(fake_feed) == {"id": sub_id, "removed": True}
    assert mcp_server.list_feed_subscriptions() == []

    with pytest.raises(ValueError, match="no such subscription"):
        mcp_server.unfollow_feed(sub_id)  # already gone
