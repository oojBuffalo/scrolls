"""Tests for the Bluesky fetch adapter (IDEAS.md §6, ADR 0048).

The AppView JSON transport is faked with payloads shaped from the real
`public.api.bsky.app` API (`resolveHandle` and `getPostThread`), so the
handle→DID resolution, post+thread merge, hashtag→concepts and facet/embed
→links mapping, image-alt searchability, textless-post summary fallback,
and error handling are all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.bluesky import fetch_item

DID = "did:plc:abc123researcher"

# Shaped from getPostThread: a text post with an inline #hashtag and a link
# facet, an external link card, and a reply tree (a nested reply, a
# not-found node, and an empty-text reply that must be skipped).
THREAD = {
    "$type": "app.bsky.feed.defs#threadViewPost",
    "post": {
        "uri": f"at://{DID}/app.bsky.feed.post/3kqpost1",
        "cid": "bafyreipost",
        "author": {
            "did": DID,
            "handle": "alice.bsky.social",
            "displayName": "Alice Researcher",
        },
        "record": {
            "$type": "app.bsky.feed.post",
            "createdAt": "2026-06-11T16:15:34.343Z",
            "text": "New paper on local-first search is wild — read it here.\n\n#localfirst",
            "facets": [
                {
                    "features": [
                        {
                            "$type": "app.bsky.richtext.facet#link",
                            "uri": "https://arxiv.org/abs/1706.03762",
                        }
                    ],
                    "index": {"byteStart": 45, "byteEnd": 54},
                },
                {
                    "features": [
                        {"$type": "app.bsky.richtext.facet#tag", "tag": "localfirst"}
                    ],
                    "index": {"byteStart": 56, "byteEnd": 67},
                },
            ],
            "langs": ["en"],
        },
        "embed": {
            "$type": "app.bsky.embed.external#view",
            "external": {
                "uri": "https://example.com/blog/local-first",
                "title": "Local-first search, explained",
                "description": "How BM25 over SQLite FTS works.",
                "thumb": "https://cdn.bsky.app/img/feed_thumbnail/plain/x@jpeg",
            },
        },
        "likeCount": 128,
        "repostCount": 12,
        "replyCount": 3,
        "quoteCount": 1,
        "indexedAt": "2026-06-11T16:16:23.275Z",
        "labels": [],
    },
    "replies": [
        {
            "$type": "app.bsky.feed.defs#threadViewPost",
            "post": {
                "author": {"handle": "bob.bsky.social", "displayName": "Bob"},
                "record": {"text": "Totally agree, the BM25 section is great."},
                "likeCount": 7,
            },
            "replies": [
                {
                    "$type": "app.bsky.feed.defs#threadViewPost",
                    "post": {
                        "author": {
                            "handle": "alice.bsky.social",
                            "displayName": "Alice Researcher",
                        },
                        "record": {"text": "Right? The trigger design especially."},
                        "likeCount": 2,
                    },
                    "replies": [],
                }
            ],
        },
        {  # a deleted/unavailable reply node: no usable post, must be skipped
            "$type": "app.bsky.feed.defs#notFoundPost",
            "notFound": True,
            "uri": f"at://{DID}/app.bsky.feed.post/gone",
        },
        {  # an empty-text reply (e.g. image-only): no text, must be skipped
            "$type": "app.bsky.feed.defs#threadViewPost",
            "post": {
                "author": {"handle": "carol.bsky.social", "displayName": "Carol"},
                "record": {"text": ""},
                "likeCount": 0,
            },
            "replies": [],
        },
    ],
}


def make_item(**overrides):
    base = dict(
        id="bluesky:alice.bsky.social/3kqpost1",
        source="bluesky",
        source_id="alice.bsky.social/3kqpost1",
        url="https://bsky.app/profile/alice.bsky.social/post/3kqpost1",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_get_json(thread=THREAD, did=DID, on_call=None):
    """A get_json routing resolveHandle and getPostThread to fixtures."""

    def get_json(url):
        if on_call is not None:
            on_call(url)
        if "resolveHandle" in url:
            return {"did": did}
        if "getPostThread" in url:
            return {"thread": thread}
        raise AssertionError(f"unexpected URL: {url}")

    return get_json


def fetch(thread=THREAD, item=None, **kwargs):
    return fetch_item(item or make_item(), get_json=fake_get_json(thread, **kwargs))


def test_fetch_resolves_handle_then_thread():
    fetched = fetch()

    # the synthesized title is the byline plus the post's lead line
    assert fetched.title == "Alice Researcher: New paper on local-first search is wild — read it here. #localfirst"
    assert fetched.author == "Alice Researcher"
    assert fetched.published_at == "2026-06-11T16:15:34+00:00"
    # a DID-saved URL would differ; canonical normalizes to the readable handle form
    assert fetched.canonical_url == "https://bsky.app/profile/alice.bsky.social/post/3kqpost1"
    assert fetched.provenance["adapter"] == "bluesky"
    assert fetched.provenance["extraction_method"] == "bluesky-appview:post+thread"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_summary_is_the_post_lead_paragraph():
    # the first paragraph of the post text, before the trailing hashtag line
    assert fetch().summary == "New paper on local-first search is wild — read it here."


def test_hashtag_facets_become_concepts():
    # curated topical labels, like github topics (ADR 0007); the `#` is dropped
    assert fetch().concepts == ("localfirst",)


def test_facet_and_embed_urls_become_links():
    # the inline link facet (arXiv) first, then the external card's URL
    assert fetch().links == (
        "https://arxiv.org/abs/1706.03762",
        "https://example.com/blog/local-first",
    )


def test_replies_are_bylined_and_flattened_depth_first():
    text = fetch().extracted_text
    assert "### Replies" in text
    assert "#### Reply by Bob (@bob.bsky.social) (7 likes)" in text
    # the nested reply is flattened in under its parent, keeping order
    assert "#### Reply by Alice Researcher (@alice.bsky.social) (2 likes)" in text
    assert text.index("Bob (@bob") < text.index("Alice Researcher (@alice")
    # the post body leads the extracted content
    assert text.index("local-first search is wild") < text.index("### Replies")


def test_deleted_and_empty_replies_are_skipped():
    text = fetch().extracted_text
    # the notFoundPost node and Carol's empty-text reply contribute nothing
    assert "Carol" not in text
    assert "gone" not in text


def test_did_url_skips_handle_resolution():
    calls = []
    item = make_item(
        id=f"bluesky:{DID}/3kqpost1",
        source_id=f"{DID}/3kqpost1",
        url=f"https://bsky.app/profile/{DID}/post/3kqpost1",
    )
    fetched = fetch_item(item, get_json=fake_get_json(on_call=calls.append))
    assert not any("resolveHandle" in url for url in calls)
    assert fetched.stage == "fetched"
    assert fetched.canonical_url == "https://bsky.app/profile/alice.bsky.social/post/3kqpost1"


def test_raw_text_keeps_the_whole_thread():
    raw = json.loads(fetch().raw_text)
    assert raw["post"]["author"]["handle"] == "alice.bsky.social"
    assert len(raw["replies"]) == 3  # everything, including the skipped nodes


# --- image-only post: alt text is the searchable content and the summary ---

IMAGE_THREAD = {
    "$type": "app.bsky.feed.defs#threadViewPost",
    "post": {
        "uri": f"at://{DID}/app.bsky.feed.post/3kqimg",
        "author": {"did": DID, "handle": "alice.bsky.social", "displayName": "Alice"},
        "record": {
            "$type": "app.bsky.feed.post",
            "createdAt": "2026-06-11T16:15:34Z",
            "text": "",
        },
        "embed": {
            "$type": "app.bsky.embed.images#view",
            "images": [
                {
                    "thumb": "https://cdn.bsky.app/img/feed_thumbnail/plain/x@jpeg",
                    "fullsize": "https://cdn.bsky.app/img/feed_fullsize/plain/x@jpeg",
                    "alt": "A diagram of an SQLite FTS5 inverted index.",
                    "aspectRatio": {"height": 800, "width": 1200},
                }
            ],
        },
        "likeCount": 5,
        "repostCount": 0,
        "replyCount": 0,
    },
    "replies": [],
}


def test_image_post_uses_alt_as_content_and_media():
    fetched = fetch(thread=IMAGE_THREAD)
    assert fetched.title == "Post by Alice on Bluesky"
    assert fetched.extracted_text == "A diagram of an SQLite FTS5 inverted index."
    assert fetched.summary == "A diagram of an SQLite FTS5 inverted index."
    assert fetched.media == (
        {
            "type": "photo",
            "url": "https://cdn.bsky.app/img/feed_fullsize/plain/x@jpeg",
            "alt": "A diagram of an SQLite FTS5 inverted index.",
        },
    )
    assert fetched.provenance["extraction_method"] == "bluesky-appview:post"


# --- quoted post becomes a post↔post link ---

QUOTE_THREAD = {
    "$type": "app.bsky.feed.defs#threadViewPost",
    "post": {
        "uri": f"at://{DID}/app.bsky.feed.post/3kqquote",
        "author": {"did": DID, "handle": "alice.bsky.social", "displayName": "Alice"},
        "record": {
            "$type": "app.bsky.feed.post",
            "createdAt": "2026-06-11T16:15:34Z",
            "text": "This is the announcement everyone's been waiting for:",
        },
        "embed": {
            "$type": "app.bsky.embed.record#view",
            "record": {
                "$type": "app.bsky.embed.record#viewRecord",
                "uri": "at://did:plc:teamaccount/app.bsky.feed.post/3kqorig",
                "author": {"handle": "bsky.app", "displayName": "Bluesky"},
                "value": {"text": "Group chats are rolling out today."},
            },
        },
        "likeCount": 9,
    },
    "replies": [],
}


def test_quoted_post_becomes_a_link():
    fetched = fetch(thread=QUOTE_THREAD)
    assert fetched.links == ("https://bsky.app/profile/bsky.app/post/3kqorig",)


def test_blocked_quote_contributes_no_link():
    thread = json.loads(json.dumps(QUOTE_THREAD))
    thread["post"]["embed"]["record"] = {
        "$type": "app.bsky.embed.record#viewBlocked",
        "uri": "at://did:plc:teamaccount/app.bsky.feed.post/3kqorig",
        "blocked": True,
    }
    assert fetch(thread=thread).links == ()


# --- link-only post: summary falls back to the card title ---


def test_link_only_post_summary_is_card_title():
    thread = json.loads(json.dumps(THREAD))
    thread["post"]["record"]["text"] = ""
    thread["post"]["record"].pop("facets")
    thread["replies"] = []
    fetched = fetch(thread=thread)
    assert fetched.summary == "Local-first search, explained"
    assert fetched.links == ("https://example.com/blog/local-first",)


def test_textless_cardless_post_summary_is_engagement_status():
    thread = {
        "$type": "app.bsky.feed.defs#threadViewPost",
        "post": {
            "uri": f"at://{DID}/app.bsky.feed.post/3kqbare",
            "author": {"did": DID, "handle": "alice.bsky.social", "displayName": "Alice"},
            "record": {"$type": "app.bsky.feed.post", "createdAt": "2026-06-11T16:15:34Z", "text": ""},
            "likeCount": 1,
            "repostCount": 0,
            "replyCount": 3,
        },
        "replies": [],
    }
    fetched = fetch(thread=thread)
    # singular/plural agreement, including the irregular "reply"/"replies"
    assert fetched.summary == "Bluesky post: 1 like, 0 reposts, 3 replies."
    assert fetched.extracted_text is None


# --- error handling ---


def test_missing_source_id_raises():
    with pytest.raises(FetchError, match="cannot determine bluesky post"):
        fetch_item(make_item(source_id=None), get_json=fake_get_json())


def test_malformed_source_id_raises():
    with pytest.raises(FetchError, match="cannot determine bluesky post"):
        fetch_item(make_item(source_id="noslash"), get_json=fake_get_json())


def test_unresolvable_handle_raises():
    def get_json(url):
        return {}  # resolveHandle with no did

    with pytest.raises(FetchError, match="could not resolve bluesky handle"):
        fetch_item(make_item(), get_json=get_json)


def test_not_found_post_raises():
    def get_json(url):
        if "resolveHandle" in url:
            return {"did": DID}
        return {"thread": {"$type": "app.bsky.feed.defs#notFoundPost", "notFound": True}}

    with pytest.raises(FetchError, match="bluesky post not found"):
        fetch_item(make_item(), get_json=get_json)


def test_api_request_failure_raises():
    def get_json(url):
        raise OSError("connection reset")

    with pytest.raises(FetchError, match="bluesky API request failed"):
        fetch_item(make_item(), get_json=get_json)


def test_registered_in_fetch_adapters():
    assert FETCH_ADAPTERS["bluesky"] is fetch_item
