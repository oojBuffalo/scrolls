"""Tests for the Hacker News fetch adapter (IDEAS.md §6, ADR 0031).

The Firebase JSON transport is faked with payloads recorded from the
real API, so the text/link split, HTML-entity decoding, and metadata
degradation are all covered offline.
"""

import json

import pytest

from scrolls.dates import epoch_to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.hackernews import fetch_item

# Recorded from https://hacker-news.firebaseio.com/v0/item/<id>.json
STORY = {  # a link post: title + url, no text
    "by": "dhouston",
    "descendants": 71,
    "id": 8863,
    "kids": [9224, 8917, 8884],
    "score": 104,
    "time": 1175714200,
    "title": "My YC app: Dropbox - Throw away your USB drive",
    "type": "story",
    "url": "http://www.getdropbox.com/u/2/screencast.html",
}

ASK = {  # a text post: title + HTML text, no url
    "by": "tel",
    "descendants": 16,
    "id": 121003,
    "kids": [121016, 121109],
    "score": 25,
    "text": "<i>or</i> HN: the Next Iteration<p>I get the impression that with "
    "Arc being released a lot of people who never had time for HN before are "
    "suddenly dropping in more often.<p>Not to say that isn't great.",
    "time": 1203647620,
    "title": "Ask HN: The Arc Effect",
    "type": "story",
}

COMMENT = {  # no title, no score; HTML text with an entity
    "by": "norvig",
    "id": 2921983,
    "kids": [2922097],
    "parent": 2921506,
    "text": "Aw shucks, guys ... you make me blush.<p>I&#39;ll keep writing if "
    "you keep reading. K?",
    "time": 1314211127,
    "type": "comment",
}


def make_item(**overrides):
    base = dict(
        id="hackernews:8863",
        source="hackernews",
        source_id="8863",
        url="https://news.ycombinator.com/item?id=8863",
        saved_at="2026-06-12T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fetch(data=STORY, item=None):
    return fetch_item(item or make_item(), get_json=lambda url: dict(data))


def test_fetch_link_story():
    fetched = fetch(STORY)

    assert fetched.title == "My YC app: Dropbox - Throw away your USB drive"
    assert fetched.author == "dhouston"
    assert fetched.published_at == "2007-04-04T19:16:40+00:00"
    assert fetched.canonical_url == "https://news.ycombinator.com/item?id=8863"
    # a link post has no body: metadata-only scroll, status as summary
    assert fetched.extracted_text is None
    assert fetched.summary == "Hacker News discussion: 104 points, 71 comments."
    # the linked article rides along as a bare URL so `related` can resolve it
    assert fetched.links == ("http://www.getdropbox.com/u/2/screencast.html",)
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.provenance["adapter"] == "hackernews"
    assert fetched.provenance["extraction_method"] == "hn-firebase:item"
    assert fetched.stage == "fetched"


def test_fetch_text_post_keeps_body_and_lead_summary():
    fetched = fetch(ASK, item=make_item(id="hackernews:121003", source_id="121003"))

    assert fetched.author == "tel"
    assert fetched.published_at == "2008-02-22T02:33:40+00:00"
    # <p> become paragraph breaks; <i> tags are stripped
    assert fetched.extracted_text.startswith("or HN: the Next Iteration")
    assert "I get the impression" in fetched.extracted_text
    assert "<p>" not in fetched.extracted_text and "<i>" not in fetched.extracted_text
    # the lead paragraph is the summary, the way wikipedia leads
    assert fetched.summary == "or HN: the Next Iteration"
    # a text post has no external article
    assert fetched.links == ()
    assert fetched.provenance["extraction_method"] == "hn-firebase:item+text"


def test_fetch_comment_synthesizes_a_title_and_decodes_entities():
    fetched = fetch(COMMENT, item=make_item(id="hackernews:2921983", source_id="2921983"))

    assert fetched.title == "Comment by norvig"
    assert fetched.published_at == "2011-08-24T18:38:47+00:00"
    # &#39; is decoded to an apostrophe
    assert "I'll keep writing" in fetched.extracted_text
    assert "Aw shucks" in fetched.summary
    assert fetched.canonical_url == "https://news.ycombinator.com/item?id=2921983"


def test_link_story_summary_uses_singular_units():
    data = {**STORY, "score": 1, "descendants": 1}
    assert fetch(data).summary == "Hacker News discussion: 1 point, 1 comment."


def test_metadata_only_post_without_status_has_no_summary():
    data = {key: value for key, value in STORY.items()
            if key not in ("score", "descendants")}
    assert fetch(data).summary is None


def test_keeps_raw_records_for_rebuilds():
    raw = json.loads(fetch(STORY).raw_text)
    assert raw["id"] == 8863
    assert raw["kids"] == [9224, 8917, 8884]  # comment ids preserved for later


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://news.ycombinator.com/item?id=8863&utm_source=x")
    fetched = fetch(STORY, item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url  # the URL the user saved, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_keeps_seeded_published_at_when_item_has_no_time():
    data = {key: value for key, value in STORY.items() if key != "time"}
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(data, item=item).published_at == "2026-06-01T00:00:00+00:00"
    # the helper agrees a missing epoch is unparseable
    assert epoch_to_utc_iso(str(data.get("time"))) is None


def test_requests_the_expected_api_url():
    seen = []

    def capture(url):
        seen.append(url)
        return dict(STORY)

    fetch_item(make_item(), get_json=capture)
    assert seen == ["https://hacker-news.firebaseio.com/v0/item/8863.json"]


@pytest.mark.parametrize("source_id", [None, "", "user", "abc"])
def test_requires_a_numeric_item_id(source_id):
    item = make_item(id="hackernews:front", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine hacker news item"):
        fetch_item(item, get_json=lambda url: dict(STORY))


def test_missing_item_is_a_fetch_error():
    # the API answers a nonexistent id with literal JSON null
    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_item(), get_json=lambda url: None)


@pytest.mark.parametrize("flag", ["deleted", "dead"])
def test_unavailable_item_is_a_fetch_error(flag):
    data = {"id": 8863, "type": "comment", flag: True}
    with pytest.raises(FetchError, match="unavailable"):
        fetch_item(make_item(), get_json=lambda url: data)


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 503: Service Unavailable")

    with pytest.raises(FetchError, match="503"):
        fetch_item(make_item(), get_json=boom)


def test_hackernews_adapter_is_registered():
    assert FETCH_ADAPTERS["hackernews"] is fetch_item
