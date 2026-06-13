"""Tests for the Mastodon fetch adapter (IDEAS.md §6, ADR 0049).

The REST transport is faked with payloads shaped from the real Mastodon
API (`/api/v1/statuses/:id` and `.../context`), so the status+thread merge,
HTML→text extraction, hashtag→concepts and content/card→links mapping,
media handling, summary fallbacks, reblog unwrapping, content-warning
handling, and error paths are all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.mastodon import fetch_item

HOST = "mastodon.social"
STATUS_ID = "109252172978473811"

# Shaped from /api/v1/statuses/:id — a text post with an inline plain link
# (arXiv), a @mention link (skipped), a #hashtag link (skipped), an external
# link card, and replies_count > 0 so the adapter fetches the context too.
STATUS = {
    "id": STATUS_ID,
    "created_at": "2026-06-11T16:15:34.000Z",
    "url": f"https://{HOST}/@alice/{STATUS_ID}",
    "uri": f"https://{HOST}/users/alice/statuses/{STATUS_ID}",
    "content": (
        "<p>New paper on local-first search is wild — read it "
        '<a href="https://arxiv.org/abs/1706.03762" rel="nofollow noopener" '
        'target="_blank">here</a>. '
        '<a href="https://mastodon.social/@bob" class="u-url mention">'
        "@<span>bob</span></a></p>"
        '<p>Big news for <a href="https://mastodon.social/tags/localfirst" '
        'class="mention hashtag" rel="tag">#<span>localfirst</span></a></p>'
    ),
    "spoiler_text": "",
    "language": "en",
    "account": {
        "username": "alice",
        "acct": "alice",
        "display_name": "Alice Researcher",
        "url": f"https://{HOST}/@alice",
    },
    "tags": [{"name": "localfirst", "url": f"https://{HOST}/tags/localfirst"}],
    "media_attachments": [],
    "card": {
        "url": "https://example.com/blog/local-first",
        "title": "Local-first search, explained",
        "description": "How BM25 over SQLite FTS works.",
    },
    "favourites_count": 128,
    "reblogs_count": 12,
    "replies_count": 3,
    "reblog": None,
}

# /api/v1/statuses/:id/context — descendants is a FLAT list (the API
# flattens the reply tree), unlike Bluesky's nested thread.
CONTEXT = {
    "ancestors": [],
    "descendants": [
        {
            "id": "109252173000000001",
            "content": "<p>Totally agree, the BM25 section is great.</p>",
            "account": {"acct": "bob", "display_name": "Bob"},
            "favourites_count": 7,
            "in_reply_to_id": STATUS_ID,
        },
        {
            "id": "109252173000000002",
            "content": "<p>Right? The trigger design especially.</p>",
            "account": {"acct": "alice", "display_name": "Alice Researcher"},
            "favourites_count": 2,
            "in_reply_to_id": "109252173000000001",
        },
        {  # empty-content reply (e.g. media-only): no text, must be skipped
            "id": "109252173000000003",
            "content": "<p></p>",
            "account": {"acct": "carol", "display_name": "Carol"},
            "favourites_count": 0,
        },
    ],
}


def make_item(**overrides):
    base = dict(
        id=f"mastodon:{HOST}/{STATUS_ID}",
        source="mastodon",
        source_id=f"{HOST}/{STATUS_ID}",
        url=f"https://{HOST}/@alice/{STATUS_ID}",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_get_json(status=STATUS, context=CONTEXT, on_call=None):
    """A get_json routing the status and context endpoints to fixtures."""

    def get_json(url):
        if on_call is not None:
            on_call(url)
        if url.endswith("/context"):
            if context is None:
                raise OSError("context fetch failed")
            return context
        if "/api/v1/statuses/" in url:
            return status
        raise AssertionError(f"unexpected URL: {url}")

    return get_json


def fetch(status=STATUS, context=CONTEXT, item=None, **kwargs):
    return fetch_item(
        item or make_item(), get_json=fake_get_json(status, context, **kwargs)
    )


def test_fetch_status_then_context():
    fetched = fetch()

    # title is the byline plus the post's lead line
    assert fetched.title == (
        "Alice Researcher: New paper on local-first search is wild — "
        "read it here. @bob"
    )
    assert fetched.author == "Alice Researcher"
    assert fetched.published_at == "2026-06-11T16:15:34+00:00"
    assert fetched.canonical_url == f"https://{HOST}/@alice/{STATUS_ID}"
    assert fetched.provenance["adapter"] == "mastodon"
    assert fetched.provenance["extraction_method"] == "mastodon-api:status+thread"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_summary_is_the_post_lead_paragraph():
    assert fetch().summary == (
        "New paper on local-first search is wild — read it here. @bob"
    )


def test_hashtags_become_concepts():
    # curated topical labels, like github topics (ADR 0007); the `#` is dropped
    assert fetch().concepts == ("localfirst",)


def test_content_and_card_urls_become_links_skipping_mentions_and_tags():
    # the inline plain link (arXiv) first, then the external card; the
    # @mention and #hashtag anchors are not outbound links
    assert fetch().links == (
        "https://arxiv.org/abs/1706.03762",
        "https://example.com/blog/local-first",
    )


def test_replies_are_bylined_and_flattened():
    text = fetch().extracted_text
    assert "### Replies" in text
    assert "#### Reply by Bob (@bob) (7 favourites)" in text
    assert "#### Reply by Alice Researcher (@alice) (2 favourites)" in text
    assert text.index("Bob (@bob") < text.index("Alice Researcher (@alice")
    # the post body leads the extracted content
    assert text.index("local-first search is wild") < text.index("### Replies")


def test_empty_replies_are_skipped():
    text = fetch().extracted_text
    assert "Carol" not in text


def test_no_replies_skips_the_context_request():
    calls = []
    status = json.loads(json.dumps(STATUS))
    status["replies_count"] = 0
    fetched = fetch(status=status, on_call=calls.append)
    assert not any(url.endswith("/context") for url in calls)
    assert fetched.extracted_text == (
        "New paper on local-first search is wild — read it here. @bob\n\n"
        "Big news for #localfirst"
    )
    assert fetched.provenance["extraction_method"] == "mastodon-api:status"


def test_context_failure_degrades_to_post_only():
    # a status with replies but a failed context fetch still produces a scroll
    fetched = fetch(context=None)
    assert "### Replies" not in (fetched.extracted_text or "")
    assert "local-first search is wild" in fetched.extracted_text
    assert fetched.provenance["extraction_method"] == "mastodon-api:status"


def test_raw_text_keeps_status_and_context():
    raw = json.loads(fetch().raw_text)
    assert raw["status"]["id"] == STATUS_ID
    assert len(raw["context"]["descendants"]) == 3  # everything, incl. skipped


def test_api_url_is_built_from_the_host_in_the_id():
    calls = []
    fetch(on_call=calls.append)
    assert calls[0] == f"https://{HOST}/api/v1/statuses/{STATUS_ID}"
    assert calls[1] == f"https://{HOST}/api/v1/statuses/{STATUS_ID}/context"


# --- image-only post: alt text is the searchable content and the summary ---

IMAGE_STATUS = {
    "id": "109252172978000001",
    "created_at": "2026-06-11T16:15:34Z",
    "url": f"https://{HOST}/@alice/109252172978000001",
    "content": "",
    "spoiler_text": "",
    "account": {"acct": "alice", "display_name": "Alice"},
    "tags": [],
    "media_attachments": [
        {
            "type": "image",
            "url": "https://files.mastodon.social/media/original/diagram.png",
            "preview_url": "https://files.mastodon.social/media/small/diagram.png",
            "description": "A diagram of an SQLite FTS5 inverted index.",
        }
    ],
    "card": None,
    "favourites_count": 5,
    "reblogs_count": 0,
    "replies_count": 0,
    "reblog": None,
}


def test_image_post_uses_alt_as_content_and_media():
    fetched = fetch(status=IMAGE_STATUS)
    assert fetched.title == "Post by Alice on Mastodon"
    assert fetched.extracted_text == "A diagram of an SQLite FTS5 inverted index."
    assert fetched.summary == "A diagram of an SQLite FTS5 inverted index."
    assert fetched.media == (
        {
            "type": "photo",
            "url": "https://files.mastodon.social/media/original/diagram.png",
            "alt": "A diagram of an SQLite FTS5 inverted index.",
        },
    )


def test_video_post_captures_the_preview_image():
    status = json.loads(json.dumps(IMAGE_STATUS))
    status["media_attachments"] = [
        {
            "type": "video",
            "url": "https://files.mastodon.social/media/original/clip.mp4",
            "preview_url": "https://files.mastodon.social/media/small/clip.png",
            "description": "A screen recording.",
        }
    ]
    fetched = fetch(status=status)
    # the video file itself is not captured; its preview image is
    assert fetched.media == (
        {
            "type": "thumbnail",
            "url": "https://files.mastodon.social/media/small/clip.png",
            "alt": "A screen recording.",
        },
    )


# --- link-only and engagement-status summaries ---


def test_link_only_post_summary_is_card_title():
    status = json.loads(json.dumps(STATUS))
    status["content"] = ""
    status["replies_count"] = 0
    fetched = fetch(status=status)
    assert fetched.summary == "Local-first search, explained"
    assert fetched.links == ("https://example.com/blog/local-first",)


def test_textless_cardless_post_summary_is_engagement_status():
    status = {
        "id": "109252172978000009",
        "created_at": "2026-06-11T16:15:34Z",
        "url": f"https://{HOST}/@alice/109252172978000009",
        "content": "<p></p>",
        "spoiler_text": "",
        "account": {"acct": "alice", "display_name": "Alice"},
        "tags": [],
        "media_attachments": [],
        "card": None,
        "favourites_count": 1,
        "reblogs_count": 0,
        "replies_count": 2,
        "reblog": None,
    }
    # the reply count can exceed the returned descendants (deletions, privacy);
    # an empty thread leaves no body but the count still drives the summary
    fetched = fetch(status=status, context={"ancestors": [], "descendants": []})
    # singular/plural agreement, including the irregular "reply"/"replies"
    assert fetched.summary == "Mastodon post: 1 favourite, 0 boosts, 2 replies."
    assert fetched.extracted_text is None


# --- content warning (spoiler_text) ---


def test_content_warning_leads_the_body_and_summary():
    status = json.loads(json.dumps(STATUS))
    status["spoiler_text"] = "Spoilers for the conference talk"
    status["replies_count"] = 0
    fetched = fetch(status=status)
    assert fetched.extracted_text.startswith("CW: Spoilers for the conference talk\n\n")
    assert "local-first search is wild" in fetched.extracted_text
    # the summary still leads with the actual post text, not the warning
    assert fetched.summary == (
        "New paper on local-first search is wild — read it here. @bob"
    )


# --- reblog (boost): the effective post is the boosted one ---


def test_reblog_unwraps_to_the_boosted_post():
    boost = {
        "id": "109252172978999999",
        "created_at": "2026-06-12T10:00:00Z",
        "url": f"https://{HOST}/@booster/109252172978999999",
        "content": "",
        "spoiler_text": "",
        "account": {"acct": "booster", "display_name": "Booster"},
        "tags": [],
        "media_attachments": [],
        "card": None,
        "favourites_count": 0,
        "reblogs_count": 0,
        "replies_count": 0,
        "reblog": STATUS,
    }
    fetched = fetch(status=boost)
    # content, author, concepts, and date come from the boosted post
    assert fetched.author == "Alice Researcher"
    assert "local-first search is wild" in fetched.extracted_text
    assert fetched.concepts == ("localfirst",)
    assert fetched.published_at == "2026-06-11T16:15:34+00:00"
    assert fetched.canonical_url == f"https://{HOST}/@alice/{STATUS_ID}"


# --- ActivityPub-form URL id (host/<id>, no @user) still works ---


def test_users_statuses_id_form_uses_the_same_identity():
    # /users/<user>/statuses/<id> dedupes to the same host/<id> identity
    item = make_item(
        id=f"mastodon:{HOST}/{STATUS_ID}",
        source_id=f"{HOST}/{STATUS_ID}",
        url=f"https://{HOST}/users/alice/statuses/{STATUS_ID}",
    )
    assert fetch(item=item).stage == "fetched"


# --- error handling ---


def test_missing_source_id_raises():
    with pytest.raises(FetchError, match="cannot determine mastodon"):
        fetch_item(make_item(source_id=None), get_json=fake_get_json())


def test_malformed_source_id_raises():
    with pytest.raises(FetchError, match="cannot determine mastodon"):
        fetch_item(make_item(source_id="noslash"), get_json=fake_get_json())


def test_not_found_status_raises():
    def get_json(url):
        return {"error": "Record not found"}

    with pytest.raises(FetchError, match="mastodon post not found"):
        fetch_item(make_item(), get_json=get_json)


def test_api_request_failure_raises():
    def get_json(url):
        raise OSError("connection reset")

    with pytest.raises(FetchError, match="mastodon API request failed"):
        fetch_item(make_item(), get_json=get_json)


def test_registered_in_fetch_adapters():
    assert FETCH_ADAPTERS["mastodon"] is fetch_item
