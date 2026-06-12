"""Tests for the arXiv fetch adapter (IDEAS.md §6, ADR 0008).

The Atom transport is faked; tests cover the abstract-as-summary
semantics and error entries offline.
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.arxiv import fetch_item

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title type="html">ArXiv Query: search_query=&amp;id_list=2310.06825</title>
  <entry>
    <id>http://arxiv.org/abs/2310.06825v1</id>
    <updated>2023-10-10T17:54:02Z</updated>
    <published>2023-10-10T17:54:02Z</published>
    <title>Mistral
 7B</title>
    <summary>  We introduce Mistral 7B, a 7-billion-parameter language model.
It outperforms Llama 2 13B across all evaluated benchmarks.
</summary>
    <author><name>Albert Q. Jiang</name></author>
    <author><name>Alexandre Sablayrolles</name></author>
    <link href="http://arxiv.org/abs/2310.06825v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2310.06825v1" rel="related"
          type="application/pdf"/>
    <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="cs.CL"/>
    <category term="cs.CL"/>
    <category term="cs.AI"/>
    <category term="cs.CL"/>
  </entry>
</feed>"""

EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title type="html">ArXiv Query: search_query=&amp;id_list=2310.99999</title>
</feed>"""

ERROR_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/api/errors#incorrect_id_format_for_bogus</id>
    <title>Error</title>
    <summary>incorrect id format for bogus</summary>
  </entry>
</feed>"""


def make_item(**overrides):
    base = dict(
        id="arxiv:2310.06825",
        source="arxiv",
        source_id="2310.06825",
        url="https://arxiv.org/abs/2310.06825",
        saved_at="2026-06-12T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fetch(item=None, feed=FEED):
    return fetch_item(item or make_item(), get_text=lambda url: feed)


def test_fetch_item_normalizes_entry_onto_item():
    fetched = fetch()

    assert fetched.title == "Mistral 7B"  # whitespace collapsed
    assert fetched.author == "Albert Q. Jiang, Alexandre Sablayrolles"
    assert fetched.published_at == "2023-10-10T17:54:02Z"
    assert fetched.canonical_url == "http://arxiv.org/abs/2310.06825v1"
    assert fetched.summary == (
        "We introduce Mistral 7B, a 7-billion-parameter language model. "
        "It outperforms Llama 2 13B across all evaluated benchmarks."
    )
    assert fetched.extracted_text is None  # full text waits for a pdf slice
    assert fetched.tags == ("cs.CL", "cs.AI")  # taxonomy codes, deduped
    assert fetched.concepts == ()  # codes are not readable concept names
    assert fetched.media == (
        {"type": "pdf", "url": "http://arxiv.org/pdf/2310.06825v1"},
    )
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.provenance["adapter"] == "arxiv"
    assert fetched.provenance["extraction_method"] == "arxiv-api:atom"
    assert fetched.stage == "fetched"


def test_fetch_item_keeps_raw_feed_for_rebuilds():
    fetched = fetch()
    assert fetched.raw_text == FEED


def test_fetch_item_preserves_identity_fields():
    item = make_item()
    fetched = fetch(item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url
    assert fetched.saved_at == item.saved_at


def test_fetch_item_requests_the_export_api():
    seen = {}

    def capture(url):
        seen["url"] = url
        return FEED

    fetch_item(make_item(), get_text=capture)
    assert seen["url"] == (
        "https://export.arxiv.org/api/query?id_list=2310.06825&max_results=1"
    )


def test_fetch_item_handles_old_style_slashed_ids():
    seen = {}

    def capture(url):
        seen["url"] = url
        return FEED

    item = make_item(id="arxiv:math/0211159", source_id="math/0211159",
                     url="https://arxiv.org/abs/math/0211159")
    fetch_item(item, get_text=capture)
    assert "id_list=math%2F0211159" in seen["url"]


def test_fetch_item_without_summary_degrades_to_metadata_only():
    feed = FEED.replace(
        "<summary>  We introduce Mistral 7B, a 7-billion-parameter language model.\n"
        "It outperforms Llama 2 13B across all evaluated benchmarks.\n</summary>",
        "<summary> </summary>",
    )
    fetched = fetch(feed=feed)
    assert fetched.summary is None
    assert fetched.title == "Mistral 7B"
    assert fetched.content_hash.startswith("sha256:")


def test_fetch_item_rejects_unknown_paper():
    with pytest.raises(FetchError, match="not found"):
        fetch(feed=EMPTY_FEED)


def test_fetch_item_rejects_api_error_entries():
    with pytest.raises(FetchError, match="incorrect id format"):
        fetch(feed=ERROR_FEED)


def test_fetch_item_rejects_item_without_paper_identity():
    with pytest.raises(FetchError, match="cannot determine arxiv paper"):
        fetch_item(make_item(source_id=None), get_text=lambda url: FEED)


def test_fetch_item_wraps_transport_errors():
    def boom(url):
        raise OSError("connection refused")

    with pytest.raises(FetchError, match="connection refused"):
        fetch_item(make_item(), get_text=boom)


def test_fetch_item_wraps_malformed_xml():
    with pytest.raises(FetchError, match="arxiv API request failed"):
        fetch(feed="this is not xml")


def test_arxiv_adapter_is_registered():
    assert FETCH_ADAPTERS["arxiv"] is fetch_item


def test_payloads_round_trip_through_json():
    fetched = fetch()
    assert json.loads(json.dumps(list(fetched.media)))[0]["type"] == "pdf"
