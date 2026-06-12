"""Tests for the YouTube fetch adapter (IDEAS.md §6, ADR 0003).

Both transports (oEmbed JSON, transcript client) are faked; tests cover
the transcript-optional fetch semantics offline.
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.youtube import fetch_item

OEMBED = {
    "title": "How SQLite FTS Works",
    "author_name": "Example Channel",
    "author_url": "https://www.youtube.com/@examplechannel",
    "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    "type": "video",
}

TRANSCRIPT = [
    {"text": "welcome back everyone", "start": 0.0, "duration": 2.0},
    {"text": "today  we look at\nSQLite FTS5", "start": 2.0, "duration": 3.5},
    {"text": "and BM25 ranking", "start": 5.5, "duration": 2.5},
]


def make_item(**overrides):
    base = dict(
        id="youtube:dQw4w9WgXcQ",
        source="youtube",
        source_id="dQw4w9WgXcQ",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42",
        saved_at="2026-06-12T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fetch(item=None, oembed=OEMBED, transcript=TRANSCRIPT):
    return fetch_item(
        item or make_item(),
        get_json=lambda url: dict(oembed),
        get_transcript=lambda video_id: list(transcript),
    )


def test_fetch_item_with_transcript():
    fetched = fetch()

    assert fetched.title == "How SQLite FTS Works"
    assert fetched.author == "Example Channel"
    assert fetched.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert fetched.extracted_text == (
        "welcome back everyone today we look at SQLite FTS5 and BM25 ranking"
    )
    assert fetched.summary is None  # oEmbed has no description; no fake summaries
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.media == ({"type": "thumbnail", "url": OEMBED["thumbnail_url"]},)
    assert fetched.provenance["adapter"] == "youtube"
    assert fetched.provenance["extraction_method"] == "oembed+youtube-transcript-api"
    assert fetched.stage == "fetched"


def test_fetch_item_keeps_raw_records_for_rebuilds():
    fetched = fetch()
    raw = json.loads(fetched.raw_text)
    assert raw["oembed"]["title"] == "How SQLite FTS Works"
    assert raw["transcript"][0]["text"] == "welcome back everyone"


def test_fetch_item_preserves_identity_fields():
    item = make_item()
    fetched = fetch(item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url  # the URL the user saved, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_fetch_item_keeps_seeded_published_at():
    # oEmbed has no publish date, so a channel-feed-seeded date (ADR 0021)
    # is the only one a synced video will ever carry — fetch must keep it
    item = make_item(published_at="2026-06-10T08:30:00+00:00")
    fetched = fetch(item)
    assert fetched.published_at == "2026-06-10T08:30:00+00:00"


def test_fetch_item_requests_oembed_for_the_canonical_url():
    seen = {}

    def capture(url):
        seen["url"] = url
        return dict(OEMBED)

    fetch_item(make_item(), get_json=capture, get_transcript=lambda vid: [])
    assert seen["url"] == (
        "https://www.youtube.com/oembed"
        "?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DdQw4w9WgXcQ&format=json"
    )


def test_fetch_item_without_transcript_degrades_to_metadata_only():
    def no_captions(video_id):
        raise RuntimeError("subtitles are disabled for this video")

    fetched = fetch_item(
        make_item(), get_json=lambda url: dict(OEMBED), get_transcript=no_captions
    )
    assert fetched.title == "How SQLite FTS Works"
    assert fetched.extracted_text is None
    assert fetched.content_hash.startswith("sha256:")
    assert json.loads(fetched.raw_text)["transcript"] is None
    assert fetched.provenance["extraction_method"] == "oembed"
    assert fetched.stage == "fetched"


def test_fetch_item_treats_empty_transcript_as_metadata_only():
    fetched = fetch(transcript=[{"text": "  ", "start": 0.0, "duration": 1.0}])
    assert fetched.extracted_text is None
    assert json.loads(fetched.raw_text)["transcript"] is None
    assert fetched.provenance["extraction_method"] == "oembed"


def test_fetch_item_playlist_skips_transcript():
    calls = []

    def tracking(video_id):
        calls.append(video_id)
        return list(TRANSCRIPT)

    item = make_item(
        id="youtube:PL1234567890abcdef",
        source_id="PL1234567890abcdef",
        url="https://www.youtube.com/playlist?list=PL1234567890abcdef",
    )
    fetched = fetch_item(item, get_json=lambda url: dict(OEMBED), get_transcript=tracking)
    assert calls == []
    assert fetched.canonical_url == (
        "https://www.youtube.com/playlist?list=PL1234567890abcdef"
    )
    assert fetched.provenance["extraction_method"] == "oembed"


def test_fetch_item_requires_a_video_id():
    item = make_item(id="youtube:abc123def456", source_id=None,
                     url="https://www.youtube.com/@somechannel")
    with pytest.raises(FetchError, match="cannot determine youtube video"):
        fetch_item(item, get_json=lambda url: dict(OEMBED),
                   get_transcript=lambda vid: [])


def test_fetch_item_wraps_oembed_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom, get_transcript=lambda vid: [])


def test_youtube_adapter_is_registered():
    assert FETCH_ADAPTERS["youtube"] is fetch_item
