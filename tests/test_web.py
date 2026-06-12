"""Tests for the web article fetch adapter (IDEAS.md §6).

The download is faked; extraction runs through the real trafilatura on
fixed HTML, so these tests cover actual extraction behavior offline.
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.web import fetch_item

ARTICLE_HTML = """
<html><head>
<title>How SQLite FTS Works - Example Blog</title>
<meta name="author" content="Jane Dev">
<meta property="article:published_time" content="2025-03-01T10:00:00Z">
<meta property="og:url" content="https://blog.example.com/sqlite-fts">
<meta property="og:description" content="A walkthrough of FTS5 internals.">
</head><body>
<article>
<h1>How SQLite FTS Works</h1>
<p>SQLite ships a full-text engine called FTS5. It builds an inverted index
over your rows and keeps it in sync with triggers or special commands.</p>
<p>BM25 ranking is the default scoring function. This post walks through the
internals step by step, with examples you can run in the sqlite3 shell.</p>
</article>
</body></html>
"""


def make_item(**overrides):
    base = dict(
        id="web:3f1a2b3c4d5e",
        source="web",
        source_id=None,
        url="https://blog.example.com/sqlite-fts?utm_source=feed",
        saved_at="2026-06-12T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def test_fetch_item_extracts_article_onto_item():
    fetched = fetch_item(make_item(), get_html=lambda url: ARTICLE_HTML)

    assert fetched.title == "How SQLite FTS Works"
    assert fetched.author == "Jane Dev"
    assert fetched.published_at == "2025-03-01T00:00:00+00:00"  # trafilatura date, normalized
    assert fetched.canonical_url == "https://blog.example.com/sqlite-fts"
    assert "inverted index" in fetched.extracted_text
    assert fetched.summary == "A walkthrough of FTS5 internals."
    assert fetched.content_hash.startswith("sha256:")
    assert json.loads(fetched.raw_text)["fingerprint"]
    assert fetched.provenance["adapter"] == "web"
    assert fetched.provenance["extraction_method"].startswith("trafilatura-")
    assert fetched.stage == "fetched"


def test_fetch_item_preserves_identity_fields():
    item = make_item()
    fetched = fetch_item(item, get_html=lambda url: ARTICLE_HTML)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url  # the URL the user saved, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_fetch_item_keeps_seeded_published_at_when_page_has_none():
    # a feed-seeded date (ADR 0021) survives a fetch that finds no date
    html = ARTICLE_HTML.replace(
        '<meta property="article:published_time" content="2025-03-01T10:00:00Z">', ""
    )
    item = make_item(published_at="2025-02-28T00:00:00+00:00")
    fetched = fetch_item(item, get_html=lambda url: html)
    assert fetched.published_at == "2025-02-28T00:00:00+00:00"


def test_fetch_item_page_date_beats_seeded_published_at():
    item = make_item(published_at="2025-02-28T00:00:00+00:00")
    fetched = fetch_item(item, get_html=lambda url: ARTICLE_HTML)
    assert fetched.published_at == "2025-03-01T00:00:00+00:00"


def test_fetch_item_requests_the_item_url():
    seen = {}

    def capture(url):
        seen["url"] = url
        return ARTICLE_HTML

    fetch_item(make_item(), get_html=capture)
    assert seen["url"] == "https://blog.example.com/sqlite-fts?utm_source=feed"


def test_fetch_item_summary_falls_back_to_first_text_line():
    html = ARTICLE_HTML.replace(
        '<meta property="og:description" content="A walkthrough of FTS5 internals.">',
        "",
    )
    fetched = fetch_item(make_item(), get_html=lambda url: html)
    assert fetched.summary == fetched.extracted_text.split("\n", 1)[0]


def test_fetch_item_rejects_pages_without_article_content():
    html = "<html><body></body></html>"
    with pytest.raises(FetchError, match="extract"):
        fetch_item(make_item(), get_html=lambda url: html)


def test_fetch_item_wraps_transport_errors():
    def boom(url):
        raise OSError("connection refused")

    with pytest.raises(FetchError, match="connection refused"):
        fetch_item(make_item(), get_html=boom)


def test_web_adapter_is_registered():
    assert FETCH_ADAPTERS["web"] is fetch_item
