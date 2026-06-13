"""Tests for the OPML subscription-list importer (IDEAS.md §13, ADR 0076)
and the symmetric exporter (ADR 0077)."""

import pytest

from scrolls.feeds import Subscription, make_subscription_id
from scrolls.opml import ImportSourceError, dump_opml_export, load_opml_export


def _sub(feed_url, title=None):
    return Subscription(
        id=make_subscription_id(feed_url),
        feed_url=feed_url,
        title=title,
        added_at="2026-06-13T00:00:00+00:00",
    )

# A realistic OPML export: an `<opml>` document whose `<body>` nests feed
# outlines (carrying `xmlUrl`) inside folder outlines (carrying none). The
# XML declaration with an encoding is included on purpose — every reader
# writes one, and ElementTree rejects an encoding-declared *str*, so the
# importer must parse bytes. A duplicate feed, a non-http feed, and a
# top-level (unfoldered) feed exercise the dedupe/ignore/walk paths.
EXPORT = """\
<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head><title>Subscriptions</title></head>
  <body>
    <outline text="Tech" title="Tech">
      <outline type="rss" text="Simon Willison" title="Simon Willison"
               xmlUrl="https://simonwillison.net/atom/everything/"
               htmlUrl="https://simonwillison.net/"/>
      <outline type="rss" text="Julia Evans"
               xmlUrl="https://jvns.ca/atom.xml" htmlUrl="https://jvns.ca/"/>
    </outline>
    <outline type="rss" text="Top-level blog"
             xmlUrl="https://example.com/feed.xml"/>
    <outline type="rss" text="Dup of Simon"
             xmlUrl="https://simonwillison.net/atom/everything/"/>
    <outline type="rss" text="Local-only" xmlUrl="file:///home/me/feed.xml"/>
  </body>
</opml>
"""


def _write(tmp_path, text=EXPORT, name="subscriptions.opml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_imports_opml_outlines_as_subscriptions(tmp_path):
    subscriptions, stats = load_opml_export(_write(tmp_path))

    # the whole tree is walked: feeds nested in folders and a top-level feed
    # all surface, in first-seen document order; the duplicate collapses and
    # the non-http outline is ignored
    assert [s.feed_url for s in subscriptions] == [
        "https://simonwillison.net/atom/everything/",
        "https://jvns.ca/atom.xml",
        "https://example.com/feed.xml",
    ]
    simon, julia, blog = subscriptions

    # each subscription's id is exactly what `scrolls follow` of the same feed
    # URL would mint, so an OPML import and a manual follow dedupe on purpose
    assert simon.id == make_subscription_id("https://simonwillison.net/atom/everything/")
    # the outline's text/title names the subscription; sync state starts empty
    assert simon.title == "Simon Willison"
    assert simon.last_synced_at is None
    assert simon.etag is None and simon.last_modified is None
    # added_at is stamped at import time (a UTC ISO 8601 string)
    assert simon.added_at and simon.added_at.endswith("+00:00")

    # an outline with only `text` (no `title`) still gets a label
    assert julia.title == "Julia Evans"
    assert blog.title == "Top-level blog"

    assert stats == {
        "feeds": 4,  # four http(s) feed outlines, the duplicate included
        "repeats": 1,  # the second Simon Willison outline
        "ignored": {"not_http": 1},  # the file:// feed
    }


def test_subscriptions_carry_no_validators_so_first_sync_sees_entries(tmp_path):
    # OPML import is network-free, unlike `follow` which fetches once: a feed
    # is trusted on import and its entries are discovered by the first sync.
    # Storing no etag/last_modified is what makes that first sync non-empty.
    subscriptions, _ = load_opml_export(_write(tmp_path))
    assert all(
        s.etag is None and s.last_modified is None and s.last_synced_at is None
        for s in subscriptions
    )


def test_label_prefers_text_then_title(tmp_path):
    text = (
        '<opml version="2.0"><body>'
        '<outline title="Only Title" xmlUrl="https://a.example/feed"/>'
        '<outline text="" title="Title Fallback" xmlUrl="https://b.example/feed"/>'
        '<outline xmlUrl="https://c.example/feed"/>'
        "</body></opml>"
    )
    subscriptions, _ = load_opml_export(_write(tmp_path, text))
    titles = [s.title for s in subscriptions]
    # text preferred; an empty text falls back to title; neither present → None
    assert titles == ["Only Title", "Title Fallback", None]


def test_lowercase_xmlurl_attribute_is_tolerated(tmp_path):
    # the OPML spec capitalizes `xmlUrl`, but some exporters lowercase it;
    # attribute lookup is case-insensitive so those feeds are not dropped
    text = (
        '<opml version="1.0"><body>'
        '<outline text="Lower" xmlurl="https://lower.example/feed"/>'
        "</body></opml>"
    )
    subscriptions, stats = load_opml_export(_write(tmp_path, text))
    assert [s.feed_url for s in subscriptions] == ["https://lower.example/feed"]
    assert stats["feeds"] == 1


def test_default_namespaced_opml_still_imports(tmp_path):
    # conformant OPML has no namespace, but some exporters emit a default one;
    # the outline walk matches by local name so a `{ns}outline` is not silently
    # dropped — the root-tag check is namespace-tolerant the same way
    text = (
        '<opml xmlns="urn:scripting:opml" version="2.0"><body>'
        '<outline text="Ns Feed" xmlUrl="https://ns.example/feed"/>'
        "</body></opml>"
    )
    subscriptions, stats = load_opml_export(_write(tmp_path, text))
    assert [s.feed_url for s in subscriptions] == ["https://ns.example/feed"]
    assert subscriptions[0].title == "Ns Feed"
    assert stats["feeds"] == 1


def test_empty_opml_imports_nothing_without_error(tmp_path):
    text = '<opml version="2.0"><head/><body/></opml>'
    subscriptions, stats = load_opml_export(_write(tmp_path, text))
    assert subscriptions == []
    assert stats == {"feeds": 0, "repeats": 0, "ignored": {"not_http": 0}}


def test_non_opml_document_raises(tmp_path):
    # an RSS feed is XML but not an OPML document; passing one (e.g. the feed
    # URL's body instead of the reader's export) is a document-level error
    feed = '<rss version="2.0"><channel><title>x</title></channel></rss>'
    with pytest.raises(ImportSourceError, match="OPML"):
        load_opml_export(_write(tmp_path, feed))


def test_malformed_xml_raises(tmp_path):
    with pytest.raises(ImportSourceError, match="parse"):
        load_opml_export(_write(tmp_path, "<opml><body><outline></opml"))


def test_missing_file_raises(tmp_path):
    with pytest.raises(ImportSourceError, match="no OPML export"):
        load_opml_export(tmp_path / "nope.opml")


# --- export (ADR 0077) ---------------------------------------------------


def test_dump_serializes_subscriptions_as_opml():
    opml = dump_opml_export(
        [
            _sub("https://blog.example.com/atom.xml", "A Weblog"),
            _sub("https://news.example.com/rss", "Daily News"),
        ]
    )
    # a proper declaration (so a reader honors the encoding) and an OPML 2.0 root
    assert opml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert '<opml version="2.0">' in opml
    assert "<title>Scrolls subscriptions</title>" in opml
    # each feed is one <outline> carrying the feed URL and its display label
    assert 'xmlUrl="https://blog.example.com/atom.xml"' in opml
    assert 'text="A Weblog"' in opml and 'title="A Weblog"' in opml
    assert 'type="rss"' in opml


def test_export_then_import_round_trips(tmp_path):
    subs = [
        _sub("https://blog.example.com/atom.xml", "A Weblog"),
        _sub("https://news.example.com/rss", "Daily News"),
    ]
    path = tmp_path / "out.opml"
    path.write_text(dump_opml_export(subs), encoding="utf-8")

    reloaded, stats = load_opml_export(path)
    # feed URLs and titles survive a full export → import cycle, in order
    assert [(s.feed_url, s.title) for s in reloaded] == [
        ("https://blog.example.com/atom.xml", "A Weblog"),
        ("https://news.example.com/rss", "Daily News"),
    ]
    assert stats == {"feeds": 2, "repeats": 0, "ignored": {"not_http": 0}}


def test_dump_titleless_subscription_falls_back_to_feed_url(tmp_path):
    opml = dump_opml_export([_sub("https://nameless.example/feed")])
    # OPML requires a `text`; a subscription with no title labels itself by URL
    assert 'text="https://nameless.example/feed"' in opml
    path = tmp_path / "out.opml"
    path.write_text(opml, encoding="utf-8")
    reloaded, _ = load_opml_export(path)
    assert reloaded[0].title == "https://nameless.example/feed"


def test_dump_escapes_ampersands_in_feed_urls(tmp_path):
    url = "https://www.youtube.com/feeds/videos.xml?channel_id=UC123&extra=1"
    opml = dump_opml_export([_sub(url, "Chan")])
    # raw `&` would be invalid XML; it must be escaped and survive a re-parse
    assert "&amp;" in opml
    path = tmp_path / "out.opml"
    path.write_text(opml, encoding="utf-8")
    reloaded, _ = load_opml_export(path)
    assert reloaded[0].feed_url == url


def test_dump_empty_is_valid_parseable_opml(tmp_path):
    opml = dump_opml_export([])
    assert '<opml version="2.0">' in opml
    path = tmp_path / "out.opml"
    path.write_text(opml, encoding="utf-8")
    # a valid, empty OPML round-trips to no subscriptions without error
    reloaded, stats = load_opml_export(path)
    assert reloaded == []
    assert stats == {"feeds": 0, "repeats": 0, "ignored": {"not_http": 0}}
