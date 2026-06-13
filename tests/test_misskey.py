"""Tests for the Misskey fetch adapter (IDEAS.md §6, ADR 0051).

The JSON-POST transport is faked with payloads shaped from the real Misskey
API (`notes/show` and `notes/children`), so the note+thread merge, MFM-text
extraction, URL-scan links, hashtag→concepts, drive-file media, content
warning, boost/quote handling, textless-note summary fallback, and error
handling are all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.misskey import fetch_item

# Shaped from notes/show: a text note with an inline #hashtag and a plain URL,
# two replies' worth of thread, hashtags, and reaction/renote/reply counts.
NOTE = {
    "id": "9bf2dbi3p4",
    "createdAt": "2026-06-11T16:15:34.343Z",
    "userId": "9aliceid",
    "user": {
        "id": "9aliceid",
        "name": "Alice Researcher",
        "username": "alice",
        "host": None,
    },
    "text": "New paper on local-first search is wild — read it here.\n\n"
    "https://arxiv.org/abs/1706.03762 #localfirst",
    "cw": None,
    "visibility": "public",
    "renoteCount": 12,
    "repliesCount": 2,
    "reactions": {":+1:": 100, ":heart:": 28},
    "fileIds": [],
    "files": [],
    "replyId": None,
    "renoteId": None,
    "renote": None,
    "tags": ["localfirst"],
    "uri": None,
    "url": None,
}

# notes/children: a flat list — a text reply, a not-a-dict node, an empty-text
# reply (media-only), all of which exercise the render/skip rules.
CHILDREN = [
    {
        "id": "9reply1",
        "user": {"name": "Bob", "username": "bob", "host": "remote.example"},
        "text": "Totally agree, the BM25 section is great.",
        "reactions": {":+1:": 7},
    },
    "not-a-note-node",
    {
        "id": "9reply2",
        "user": {"name": "Carol", "username": "carol", "host": None},
        "text": "",
        "reactions": {},
    },
]


def make_item(**overrides):
    base = dict(
        id="misskey:misskey.io/9bf2dbi3p4",
        source="misskey",
        source_id="misskey.io/9bf2dbi3p4",
        url="https://misskey.io/notes/9bf2dbi3p4",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_post_json(note=NOTE, children=CHILDREN, on_call=None):
    """A post_json routing notes/show and notes/children to fixtures."""

    def post_json(url, payload):
        if on_call is not None:
            on_call(url, payload)
        if url.endswith("/notes/show"):
            return note
        if url.endswith("/notes/children"):
            return children
        raise AssertionError(f"unexpected URL: {url}")

    return post_json


def fetch(note=NOTE, children=CHILDREN, item=None, **kwargs):
    return fetch_item(item or make_item(), post_json=fake_post_json(note, children, **kwargs))


def test_fetch_shows_note_then_children():
    fetched = fetch()

    # the synthesized title is the byline plus the note's lead paragraph only
    assert fetched.title == "Alice Researcher: New paper on local-first search is wild — read it here."
    assert fetched.author == "Alice Researcher"
    assert fetched.published_at == "2026-06-11T16:15:34+00:00"
    # a local note carries no url/uri, so canonical falls back to the saved URL
    assert fetched.canonical_url == "https://misskey.io/notes/9bf2dbi3p4"
    assert fetched.provenance["adapter"] == "misskey"
    assert fetched.provenance["extraction_method"] == "misskey-api:note+thread"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_summary_is_the_note_lead_paragraph():
    # the first paragraph of the note text, before the link/hashtag line
    assert fetch().summary == "New paper on local-first search is wild — read it here."


def test_hashtags_become_concepts():
    # curated topical labels, like github topics (ADR 0007); the `#` is dropped
    assert fetch().concepts == ("localfirst",)


def test_text_urls_become_links():
    # Misskey has no facet list or link card, so links are scanned from the MFM
    # text — the arXiv URL becomes a cross-source edge
    assert fetch().links == ("https://arxiv.org/abs/1706.03762",)


def test_replies_are_bylined_and_flattened():
    text = fetch().extracted_text
    assert "### Replies" in text
    # a local user is `@username`, a remote one `@username@host`
    assert "#### Reply by Bob (@bob@remote.example) (7 reactions)" in text
    # the note body leads the extracted content
    assert text.index("local-first search is wild") < text.index("### Replies")


def test_empty_text_and_non_dict_replies_are_skipped():
    text = fetch().extracted_text
    # Carol's empty-text reply and the bare-string node contribute nothing
    assert "Carol" not in text


def test_no_replies_skips_the_children_request():
    calls = []
    note = {**NOTE, "repliesCount": 0}
    fetched = fetch(note=note, on_call=lambda url, payload: calls.append(url))
    assert not any("children" in url for url in calls)
    assert fetched.provenance["extraction_method"] == "misskey-api:note"


def test_children_failure_degrades_to_note_only():
    def post_json(url, payload):
        if url.endswith("/notes/show"):
            return NOTE
        raise OSError("connection reset")  # the children fetch fails

    fetched = fetch_item(make_item(), post_json=post_json)
    # the note still produces a scroll, just without the reply thread
    assert fetched.extracted_text.startswith("New paper on local-first search")
    assert "### Replies" not in fetched.extracted_text
    assert fetched.provenance["extraction_method"] == "misskey-api:note"


def test_raw_text_keeps_note_and_children():
    raw = json.loads(fetch().raw_text)
    assert raw["note"]["id"] == "9bf2dbi3p4"
    assert len(raw["children"]) == 3  # everything, including the skipped nodes


# --- content warning leads the body ---


def test_content_warning_leads_the_body():
    note = {**NOTE, "cw": "spoilers for the paper's conclusion"}
    fetched = fetch(note=note)
    assert fetched.extracted_text.startswith("CW: spoilers for the paper's conclusion")
    # the summary still leads with the actual text, not the warning
    assert fetched.summary == "New paper on local-first search is wild — read it here."


# --- image-only note: alt text is the searchable content and the summary ---

IMAGE_NOTE = {
    "id": "9imgnote",
    "createdAt": "2026-06-11T16:15:34Z",
    "user": {"name": "Alice", "username": "alice", "host": None},
    "text": None,
    "cw": None,
    "repliesCount": 0,
    "renoteCount": 0,
    "reactions": {":+1:": 5},
    "files": [
        {
            "id": "9file1",
            "type": "image/png",
            "url": "https://media.misskey.io/full.png",
            "thumbnailUrl": "https://media.misskey.io/thumb.png",
            "comment": "A diagram of an SQLite FTS5 inverted index.",
        }
    ],
    "tags": [],
}


def test_image_note_uses_alt_as_content_and_media():
    fetched = fetch(note=IMAGE_NOTE)
    assert fetched.title == "Post by Alice on Misskey"
    assert fetched.extracted_text == "A diagram of an SQLite FTS5 inverted index."
    assert fetched.summary == "A diagram of an SQLite FTS5 inverted index."
    assert fetched.media == (
        {
            "type": "photo",
            "url": "https://media.misskey.io/full.png",
            "alt": "A diagram of an SQLite FTS5 inverted index.",
        },
    )
    assert fetched.provenance["extraction_method"] == "misskey-api:note"


def test_video_note_captures_the_thumbnail():
    note = {
        **IMAGE_NOTE,
        "files": [
            {
                "id": "9vid",
                "type": "video/mp4",
                "url": "https://media.misskey.io/clip.mp4",
                "thumbnailUrl": "https://media.misskey.io/clip-thumb.jpg",
                "comment": None,
            }
        ],
    }
    assert fetch(note=note).media == (
        {"type": "thumbnail", "url": "https://media.misskey.io/clip-thumb.jpg"},
    )


# --- boost (pure renote) unwraps to the boosted note ---

BOOST_NOTE = {
    "id": "9boost",
    "createdAt": "2026-06-12T10:00:00Z",
    "user": {"name": "Booster", "username": "booster", "host": None},
    "text": None,  # a pure renote has no text of its own
    "renoteCount": 0,
    "repliesCount": 0,
    "renote": {
        "id": "9original",
        "createdAt": "2026-06-11T16:15:34Z",
        "user": {"name": "Original Author", "username": "author", "host": "remote.example"},
        "text": "The original insight everyone is boosting.",
        "url": "https://remote.example/notes/9original",
        "tags": ["insight"],
        "repliesCount": 0,
        "reactions": {":+1:": 50},
    },
}


def test_renote_unwraps_to_the_boosted_note():
    fetched = fetch(note=BOOST_NOTE)
    assert fetched.author == "Original Author"
    assert fetched.extracted_text == "The original insight everyone is boosting."
    assert fetched.concepts == ("insight",)
    # canonical and date come from the boosted note, keeping the saved identity
    assert fetched.canonical_url == "https://remote.example/notes/9original"
    assert fetched.published_at == "2026-06-11T16:15:34+00:00"


# --- quote (renote with text) keeps its own text and links the quoted note ---

QUOTE_NOTE = {
    "id": "9quote",
    "createdAt": "2026-06-12T10:00:00Z",
    "user": {"name": "Quoter", "username": "quoter", "host": None},
    "text": "This is the announcement everyone's been waiting for:",
    "renoteCount": 0,
    "repliesCount": 0,
    "reactions": {},
    "tags": [],
    "renote": {
        "id": "9announce",
        "user": {"name": "Team", "username": "team", "host": None},
        "text": "Group chats are rolling out today.",
        "url": None,
        "uri": None,
    },
}


def test_quote_note_keeps_text_and_links_the_quoted_note():
    fetched = fetch(note=QUOTE_NOTE)
    assert fetched.extracted_text == "This is the announcement everyone's been waiting for:"
    # the quoted (local) note's implicit /notes/<id> URL becomes a post↔post link
    assert fetched.links == ("https://misskey.io/notes/9announce",)


# --- textless, mediless note: summary is the engagement status ---


def test_textless_note_summary_is_engagement_status():
    note = {
        "id": "9bare",
        "createdAt": "2026-06-11T16:15:34Z",
        "user": {"name": "Alice", "username": "alice", "host": None},
        "text": None,
        "files": [],
        "reactions": {":+1:": 1},
        "renoteCount": 0,
        "repliesCount": 3,
        "tags": [],
    }
    # repliesCount is 3 but the thread is unavailable/empty here: a bare note
    fetched = fetch(note=note, children=[])
    # reaction sum from the map; singular/plural agreement incl. "reply"/"replies"
    assert fetched.summary == "Misskey post: 1 reaction, 0 renotes, 3 replies."
    assert fetched.extracted_text is None


# --- error handling ---


def test_missing_source_id_raises():
    with pytest.raises(FetchError, match="cannot determine misskey note"):
        fetch_item(make_item(source_id=None), post_json=fake_post_json())


def test_malformed_source_id_raises():
    with pytest.raises(FetchError, match="cannot determine misskey note"):
        fetch_item(make_item(source_id="noslash"), post_json=fake_post_json())


def test_note_not_found_raises():
    def post_json(url, payload):
        return {"error": {"code": "NO_SUCH_NOTE", "message": "No such note."}}

    with pytest.raises(FetchError, match="misskey note not found"):
        fetch_item(make_item(), post_json=post_json)


def test_api_request_failure_raises():
    def post_json(url, payload):
        raise OSError("connection reset")

    with pytest.raises(FetchError, match="misskey API request failed"):
        fetch_item(make_item(), post_json=post_json)


def test_registered_in_fetch_adapters():
    assert FETCH_ADAPTERS["misskey"] is fetch_item
