"""Tests for the Discourse fetch adapter (IDEAS.md §6, ADR 0054).

The HTTP transport is faked with a payload shaped from the real Discourse topic
view (`GET /t/<id>.json`), so the topic+replies merge in one request, the
HTML-`cooked` reduction, the opening-post body vs bylined replies, tags→concepts,
outbound `details.links` (internal/reflection filtered), the representative
image→thumbnail, deleted/hidden/action-post skipping, the engagement-status
summary, the slug-bearing canonical URL, and error/misdetect handling are all
covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.discourse import fetch_item

# Shaped from GET https://<host>/t/<id>.json: a topic with an opening post (the
# body, post_number 1) and three reply posts in `post_stream.posts`, plus a
# moderator-action post, a deleted post, and a whisper that must all be skipped.
# `details.links` carries an outbound link, an internal nav link, and a
# reflection (an incoming link) — only the outbound one becomes a `link`.
TOPIC_RESPONSE = {
    "post_stream": {
        "posts": [
            {
                "id": 1001,
                "username": "ferris",
                "name": "Ferris the Crab",
                "created_at": "2026-06-11T16:15:34.343Z",
                "cooked": "<p>How do you structure a local-first knowledge base?</p>"
                "<p>See <a href=\"https://arxiv.org/abs/1706.03762\">this paper</a> "
                "for background.</p>",
                "post_number": 1,
                "post_type": 1,
                "reply_count": 2,
                "score": 25.5,
                "actions_summary": [{"id": 2, "count": 12}],
            },
            {
                "id": 1002,
                "username": "alice",
                "name": "Alice",
                "cooked": "<p>I use SQLite with FTS5 and a folder of Markdown files.</p>",
                "post_number": 2,
                "post_type": 1,
                "reply_to_post_number": 1,
                "actions_summary": [{"id": 2, "count": 8}],
            },
            {
                "id": 1003,
                "username": "bob",
                "name": "",  # no display name -> byline falls back to the username
                "cooked": "<p>Same here. The Markdown files are the durable artifact.</p>",
                "post_number": 3,
                "post_type": 1,
            },
            {  # a moderator action (post_type 2) -> skipped
                "id": 1004,
                "username": "system",
                "cooked": "<p>This topic was closed.</p>",
                "post_number": 4,
                "post_type": 2,
            },
            {  # deleted -> skipped
                "id": 1005,
                "username": "spammer",
                "cooked": "<p>buy my thing</p>",
                "post_number": 5,
                "post_type": 1,
                "deleted_at": "2026-06-11T18:00:00.000Z",
            },
            {  # whisper (post_type 4, staff-only) -> skipped
                "id": 1006,
                "username": "mod",
                "cooked": "<p>internal staff note</p>",
                "post_number": 6,
                "post_type": 4,
            },
        ],
        "stream": [1001, 1002, 1003, 1004, 1005, 1006],
    },
    "id": 8,
    "title": "How do you structure a local-first knowledge base?",
    "slug": "how-do-you-structure-a-local-first-knowledge-base",
    "posts_count": 4,
    "created_at": "2026-06-11T16:15:34.343Z",
    "like_count": 20,
    "views": 412,
    "category_id": 9,
    "image_url": "https://discuss.example.org/uploads/diagram.png",
    "tags": ["knowledge-base", "sqlite", "local-first"],
    "details": {
        "created_by": {"id": 5, "username": "ferris", "name": "Ferris the Crab"},
        "last_poster": {"id": 7, "username": "bob"},
        "links": [
            {
                "url": "https://arxiv.org/abs/1706.03762",
                "title": "Attention Is All You Need",
                "internal": False,
                "reflection": False,
                "clicks": 4,
            },
            {  # internal nav link to the same instance -> excluded
                "url": "https://discuss.example.org/u/alice",
                "internal": True,
                "reflection": False,
            },
            {  # a reflection: another topic links *here* -> excluded
                "url": "https://discuss.example.org/t/another-topic/42",
                "internal": True,
                "reflection": True,
            },
        ],
    },
}


def make_item(**overrides):
    base = dict(
        id="discourse:discuss.example.org/8",
        source="discourse",
        source_id="discuss.example.org/8",
        url="https://discuss.example.org/t/how-do-you-structure-a-local-first-knowledge-base/8",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_get_json(topic=TOPIC_RESPONSE, on_call=None):
    """A get_json returning the topic fixture for the `.json` view."""

    def get_json(url):
        if on_call is not None:
            on_call(url)
        if url.endswith("/t/8.json"):
            return topic
        raise AssertionError(f"unexpected URL: {url}")

    return get_json


def fetch(topic=TOPIC_RESPONSE, item=None, **kwargs):
    return fetch_item(item or make_item(), get_json=fake_get_json(topic, **kwargs))


def test_fetch_topic_in_one_request():
    calls = []
    fetched = fetch(on_call=calls.append)

    assert fetched.title == "How do you structure a local-first knowledge base?"
    assert fetched.author == "Ferris the Crab"
    assert fetched.published_at == "2026-06-11T16:15:34+00:00"
    assert fetched.provenance["adapter"] == "discourse"
    assert fetched.provenance["extraction_method"] == "discourse-api:topic+replies"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"
    # topic + replies come in one GET — no second request (Lobsters' economy)
    assert len(calls) == 1


def test_hits_the_slug_free_json_view():
    calls = []
    fetch(on_call=calls.append)
    assert calls == ["https://discuss.example.org/t/8.json"]


def test_canonical_url_carries_the_slug_from_the_response():
    # Discourse's canonical permalink includes the slug; the adapter fetches the
    # slug-free route but rebuilds the canonical from the response slug
    assert fetch().canonical_url == (
        "https://discuss.example.org/t/how-do-you-structure-a-local-first-knowledge-base/8"
    )


def test_opening_post_is_the_body_and_leads_the_extracted_text():
    text = fetch().extracted_text
    assert text.startswith("How do you structure a local-first knowledge base?")
    assert text.index("structure a local-first") < text.index("### Replies")


def test_summary_is_the_opening_post_lead_paragraph():
    assert fetch().summary == "How do you structure a local-first knowledge base?"


def test_replies_are_bylined_with_like_counts():
    text = fetch().extracted_text
    assert "### Replies" in text
    # a reply with a display name and likes is bylined with both
    assert "#### Reply by Alice (@alice) (8 likes)" in text
    # a reply with no display name falls back to the bare @username, no likes
    assert "#### Reply by @bob" in text
    assert "SQLite with FTS5" in text


def test_action_deleted_and_whisper_posts_are_skipped():
    text = fetch().extracted_text
    assert "This topic was closed" not in text  # moderator action (post_type 2)
    assert "buy my thing" not in text  # deleted
    assert "internal staff note" not in text  # whisper (post_type 4)


def test_html_cooked_is_reduced_to_plain_text():
    text = fetch().extracted_text
    # the <a> anchor text survives, the HTML tags do not
    assert "this paper" in text
    assert "<a href" not in text and "<p>" not in text


def test_tags_become_concepts():
    assert fetch().concepts == ("knowledge-base", "sqlite", "local-first")


def test_outbound_link_becomes_a_link_internal_and_reflection_excluded():
    links = fetch().links
    assert links == ("https://arxiv.org/abs/1706.03762",)
    # the internal nav link and the incoming reflection are not outbound edges
    assert "https://discuss.example.org/u/alice" not in links
    assert "https://discuss.example.org/t/another-topic/42" not in links


def test_image_url_becomes_a_thumbnail_media_ref():
    assert fetch().media == (
        {"type": "thumbnail", "url": "https://discuss.example.org/uploads/diagram.png"},
    )


def test_relative_image_url_is_resolved_against_the_host():
    topic = {**TOPIC_RESPONSE, "image_url": "/uploads/local.png"}
    assert fetch(topic=topic).media == (
        {"type": "thumbnail", "url": "https://discuss.example.org/uploads/local.png"},
    )


def test_raw_text_keeps_the_whole_topic():
    raw = json.loads(fetch().raw_text)
    assert raw["id"] == 8
    # everything, including the skipped action/deleted/whisper posts and the
    # full stream of post ids, survives for a future paged render
    assert len(raw["post_stream"]["posts"]) == 6
    assert raw["post_stream"]["stream"] == [1001, 1002, 1003, 1004, 1005, 1006]


def test_no_category_default():
    # a heterogeneous forum thread is unclassified like Hacker News / Lobsters /
    # Lemmy until a title rule or the LLM engine names it (classify.py untouched)
    assert fetch().category is None


# --- a topic with only the opening post (no replies) ---

OP_ONLY_TOPIC = {
    "post_stream": {
        "posts": [
            {
                "id": 2001,
                "username": "dave",
                "name": "Dave",
                "cooked": "<p>Announcing v2.0 of the library.</p>",
                "post_number": 1,
                "post_type": 1,
            }
        ],
        "stream": [2001],
    },
    "id": 99,
    "title": "Announcing v2.0",
    "slug": "announcing-v2-0",
    "posts_count": 1,
    "created_at": "2026-06-12T09:00:00.000Z",
    "like_count": 3,
    "tags": [],
    "details": {"created_by": {"username": "dave", "name": "Dave"}, "links": []},
}


def test_author_falls_back_to_the_opening_post_when_created_by_absent():
    # a payload with no details.created_by uses the opening post's author
    topic = {**TOPIC_RESPONSE, "details": {"links": []}}
    assert fetch(topic=topic).author == "Ferris the Crab"


def test_op_only_topic_is_topic_not_replies():
    def get_json(url):
        assert url.endswith("/t/99.json")
        return OP_ONLY_TOPIC

    fetched = fetch_item(make_item(source_id="discuss.example.org/99"), get_json=get_json)
    assert fetched.extracted_text == "Announcing v2.0 of the library."
    assert "### Replies" not in fetched.extracted_text
    assert fetched.provenance["extraction_method"] == "discourse-api:topic"
    assert fetched.concepts == ()
    assert fetched.links == ()


# --- a topic whose opening post has no prose: summary is the engagement status ---


def test_empty_op_summary_is_engagement_status():
    topic = {
        **TOPIC_RESPONSE,
        "post_stream": {
            "posts": [
                {"id": 3001, "username": "x", "cooked": "", "post_number": 1, "post_type": 1}
            ],
            "stream": [3001],
        },
        "posts_count": 4,
        "like_count": 20,
    }
    # posts_count includes the opening post, so 4 posts -> 3 replies
    assert fetch(topic=topic).summary == "Discourse topic: 3 replies, 20 likes."


# --- error handling and the benign-misdetect path ---


def test_missing_source_id_raises():
    with pytest.raises(FetchError, match="cannot determine discourse topic"):
        fetch_item(make_item(source_id=None), get_json=fake_get_json())


def test_malformed_source_id_raises():
    with pytest.raises(FetchError, match="cannot determine discourse topic"):
        fetch_item(make_item(source_id="noslash"), get_json=fake_get_json())


def test_non_discourse_json_raises_the_misdetect_path():
    # a non-Discourse `/t/<slug>/<digits>.json` URL returns JSON with no
    # post_stream -> FetchError (a benign failed fetch, never a wrong scroll)
    def get_json(url):
        return {"some": "other site"}

    with pytest.raises(FetchError, match="discourse topic not found"):
        fetch_item(make_item(), get_json=get_json)


def test_api_request_failure_raises():
    def get_json(url):
        raise OSError("connection reset")

    with pytest.raises(FetchError, match="discourse API request failed"):
        fetch_item(make_item(), get_json=get_json)


def test_registered_in_fetch_adapters():
    assert FETCH_ADAPTERS["discourse"] is fetch_item
