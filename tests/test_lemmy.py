"""Tests for the Lemmy fetch adapter (IDEAS.md §6, ADR 0052).

The HTTP transport is faked with payloads shaped from the real Lemmy v3 API
(`/api/v3/post` and `/api/v3/comment/list`), so the post+thread merge, body
extraction, link/cross-post edges, community→concept, threaded comment render,
deleted/removed skipping, image/thumbnail media, engagement-status summary,
canonical `ap_id`, and error handling are all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.lemmy import fetch_item

# Shaped from GET /api/v3/post?id=<id>: a link post (an external article) with
# a body that also carries an inline URL, a community, counts, a thumbnail, and
# a cross-post to another instance.
POST_RESPONSE = {
    "post_view": {
        "post": {
            "id": 27855171,
            "name": "Rust 2.0 will never happen — and that's fine",
            "url": "https://blog.rust-lang.org/rust-2-0",
            "url_content_type": "text/html; charset=utf-8",
            "body": "A discussion of why a breaking 2.0 isn't planned.\n\n"
            "See also https://arxiv.org/abs/1706.03762 for background.",
            "thumbnail_url": "https://lemmy.world/pictrs/image/thumb.jpeg",
            "creator_id": 5,
            "community_id": 9,
            "published": "2026-06-11T16:15:34.343Z",
            "ap_id": "https://lemmy.world/post/27855171",
            "local": True,
            "nsfw": False,
            "removed": False,
            "deleted": False,
        },
        "creator": {
            "id": 5,
            "name": "ferris",
            "display_name": "Ferris the Crab",
            "actor_id": "https://lemmy.world/u/ferris",
        },
        "community": {
            "id": 9,
            "name": "rust",
            "title": "Rust Programming",
            "actor_id": "https://lemmy.world/c/rust",
        },
        "counts": {
            "post_id": 27855171,
            "comments": 4,
            "score": 142,
            "upvotes": 150,
            "downvotes": 8,
        },
    },
    "community_view": {"community": {"name": "rust"}},
    "moderators": [],
    # cross_posts: the same article submitted to other communities/instances —
    # each a post↔post edge, like a Misskey quote-renote (ADR 0051).
    "cross_posts": [
        {
            "post": {
                "id": 88,
                "name": "Rust 2.0 will never happen",
                "ap_id": "https://programming.dev/post/12345",
            }
        }
    ],
}

# Shaped from GET /api/v3/comment/list?post_id=<id>: a flat list whose `path`
# encodes the thread tree ("0.<id>" top-level, "0.<parent>.<id>" a reply). A
# deleted and a removed comment carry no usable text and are skipped.
COMMENTS = [
    {
        "comment": {
            "id": 5,
            "content": "Backwards compatibility is the whole point of editions.",
            "path": "0.5",
            "published": "2026-06-11T17:00:00Z",
            "ap_id": "https://lemmy.world/comment/5",
            "deleted": False,
            "removed": False,
        },
        "creator": {"name": "alice", "display_name": "Alice", "actor_id": "x"},
        "counts": {"score": 30, "child_count": 1},
    },
    {
        "comment": {
            "id": 12,
            "content": "Agreed — editions solve almost all of it.",
            "path": "0.5.12",
            "deleted": False,
            "removed": False,
        },
        # display_name absent -> byline falls back to the bare username
        "creator": {"name": "bob", "display_name": None, "actor_id": "y"},
        "counts": {"score": 8, "child_count": 0},
    },
    {  # deleted by its author -> skipped
        "comment": {"id": 20, "content": "", "path": "0.20", "deleted": True, "removed": False},
        "creator": {"name": "carol", "display_name": "Carol"},
        "counts": {"score": 0, "child_count": 0},
    },
    {  # removed by a mod -> skipped
        "comment": {"id": 21, "content": "spammy text", "path": "0.21", "deleted": False, "removed": True},
        "creator": {"name": "spammer"},
        "counts": {"score": -5, "child_count": 0},
    },
]


def make_item(**overrides):
    base = dict(
        id="lemmy:lemmy.world/27855171",
        source="lemmy",
        source_id="lemmy.world/27855171",
        url="https://lemmy.world/post/27855171",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_get_json(post=POST_RESPONSE, comments=COMMENTS, on_call=None):
    """A get_json routing /post and /comment/list to fixtures."""

    def get_json(url):
        if on_call is not None:
            on_call(url)
        if "/comment/list" in url:
            return {"comments": comments}
        if "/post" in url:
            return post
        raise AssertionError(f"unexpected URL: {url}")

    return get_json


def fetch(post=POST_RESPONSE, comments=COMMENTS, item=None, **kwargs):
    return fetch_item(item or make_item(), get_json=fake_get_json(post, comments, **kwargs))


def test_fetch_post_then_comments():
    fetched = fetch()

    assert fetched.title == "Rust 2.0 will never happen — and that's fine"
    assert fetched.author == "Ferris the Crab"
    assert fetched.published_at == "2026-06-11T16:15:34+00:00"
    # canonical is the federated ap_id (origin instance), not the saved URL
    assert fetched.canonical_url == "https://lemmy.world/post/27855171"
    assert fetched.provenance["adapter"] == "lemmy"
    assert fetched.provenance["extraction_method"] == "lemmy-api:post+comments"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_summary_is_the_body_lead_paragraph():
    # a post with a text body leads its summary with that body's first paragraph
    assert fetch().summary == "A discussion of why a breaking 2.0 isn't planned."


def test_community_becomes_a_concept():
    # the community (the topical home, like a subreddit) is the one curated
    # topical label Lemmy gives, so it feeds the KB concept graph (ADR 0007)
    assert fetch().concepts == ("rust",)


def test_link_post_url_becomes_a_link():
    # the external article rides along as a link (Hacker News/Lobsters pattern)
    assert "https://blog.rust-lang.org/rust-2-0" in fetch().links


def test_body_urls_become_links():
    # a URL in the markdown body is a cross-source edge (the arXiv paper)
    assert "https://arxiv.org/abs/1706.03762" in fetch().links


def test_cross_post_becomes_a_link():
    # the same article in another community is a post↔post edge via its ap_id
    assert "https://programming.dev/post/12345" in fetch().links


def test_comments_are_bylined_and_thread_ordered():
    text = fetch().extracted_text
    assert "### Comments" in text
    # top-level comment bylined with author display name and score
    assert "#### Comment by Alice (score 30)" in text
    # a reply with no display name falls back to the bare username
    assert "#### Comment by bob (score 8)" in text
    # the post body leads the extracted content, before the comments
    assert text.index("breaking 2.0 isn't planned") < text.index("### Comments")
    # path order puts the reply (0.5.12) right after its parent (0.5)
    assert text.index("Alice (score 30)") < text.index("bob (score 8)")


def test_deleted_and_removed_comments_are_skipped():
    text = fetch().extracted_text
    assert "Carol" not in text  # deleted
    assert "spammy text" not in text  # removed


def test_no_comments_skips_the_comment_request():
    calls = []
    post = {
        **POST_RESPONSE,
        "post_view": {
            **POST_RESPONSE["post_view"],
            "counts": {**POST_RESPONSE["post_view"]["counts"], "comments": 0},
        },
    }
    fetched = fetch(post=post, on_call=calls.append)
    assert not any("comment/list" in url for url in calls)
    assert fetched.provenance["extraction_method"] == "lemmy-api:post"


def test_comment_failure_degrades_to_post_only():
    def get_json(url):
        if "/comment/list" in url:
            raise OSError("connection reset")
        return POST_RESPONSE

    fetched = fetch_item(make_item(), get_json=get_json)
    assert fetched.extracted_text.startswith("A discussion of why a breaking 2.0")
    assert "### Comments" not in fetched.extracted_text
    assert fetched.provenance["extraction_method"] == "lemmy-api:post"


def test_raw_text_keeps_post_and_comments():
    raw = json.loads(fetch().raw_text)
    assert raw["post"]["post_view"]["post"]["id"] == 27855171
    assert len(raw["comments"]) == 4  # everything, including the skipped nodes


# --- a text (self) post: no external url, body is the content ---

TEXT_POST = {
    "post_view": {
        "post": {
            "id": 100,
            "name": "What note-taking setup do you use?",
            "url": None,
            "body": "I'm looking for a local-first option. What works for you?",
            "thumbnail_url": None,
            "published": "2026-06-12T09:00:00Z",
            "ap_id": "https://lemmy.world/post/100",
        },
        "creator": {"name": "dave", "display_name": "Dave"},
        "community": {"name": "asklemmy", "title": "Ask Lemmy"},
        "counts": {"comments": 0, "score": 5},
    },
    "cross_posts": [],
}


def test_text_post_has_no_link_and_keeps_its_body():
    fetched = fetch(post=TEXT_POST)
    assert fetched.links == ()
    assert fetched.extracted_text == "I'm looking for a local-first option. What works for you?"
    assert fetched.concepts == ("asklemmy",)


# --- a link/image post with no body: summary is the engagement status ---

LINK_ONLY_POST = {
    "post_view": {
        "post": {
            "id": 200,
            "name": "An interesting article",
            "url": "https://example.com/article",
            "url_content_type": "text/html",
            "body": None,
            "thumbnail_url": "https://lemmy.world/pictrs/image/t.jpeg",
            "published": "2026-06-12T09:00:00Z",
            "ap_id": "https://lemmy.world/post/200",
        },
        "creator": {"name": "erin"},
        "community": {"name": "technology"},
        "counts": {"comments": 17, "score": 88},
    },
    "cross_posts": [],
}


def test_link_only_post_summary_is_engagement_status():
    # no body of its own, so the honest summary is the discussion status
    fetched = fetch(post=LINK_ONLY_POST, comments=[])
    assert fetched.summary == "Lemmy discussion: 88 points, 17 comments."


def test_link_post_thumbnail_becomes_thumbnail_media():
    # an article link post keeps its pict-rs preview image as a thumbnail ref
    assert fetch(post=LINK_ONLY_POST, comments=[]).media == (
        {"type": "thumbnail", "url": "https://lemmy.world/pictrs/image/t.jpeg"},
    )
    # and the external article is a link, not media
    assert "https://example.com/article" in fetch(post=LINK_ONLY_POST, comments=[]).links


# --- an image post: the url IS the image, so it is photo media, not a link ---

IMAGE_POST = {
    "post_view": {
        "post": {
            "id": 300,
            "name": "A diagram of an SQLite FTS5 inverted index",
            "url": "https://lemmy.world/pictrs/image/diagram.png",
            "url_content_type": "image/png",
            "body": None,
            "thumbnail_url": "https://lemmy.world/pictrs/image/diagram-thumb.png",
            "published": "2026-06-12T09:00:00Z",
            "ap_id": "https://lemmy.world/post/300",
        },
        "creator": {"name": "frank"},
        "community": {"name": "dataisbeautiful"},
        "counts": {"comments": 0, "score": 200},
    },
    "cross_posts": [],
}


def test_image_post_url_becomes_photo_media():
    fetched = fetch(post=IMAGE_POST)
    assert fetched.media == (
        {"type": "photo", "url": "https://lemmy.world/pictrs/image/diagram.png"},
    )
    # the image url is media, never a duplicate link
    assert fetched.links == ()


# --- a federated (remote) post viewed via another instance ---


def test_remote_post_canonical_is_the_origin_ap_id():
    # a post that originated on another instance carries that instance's ap_id;
    # canonical points there even though we fetched it via lemmy.world
    post = {
        **POST_RESPONSE,
        "post_view": {
            **POST_RESPONSE["post_view"],
            "post": {
                **POST_RESPONSE["post_view"]["post"],
                "local": False,
                "ap_id": "https://programming.dev/post/9999",
            },
            "counts": {**POST_RESPONSE["post_view"]["counts"], "comments": 0},
        },
    }
    assert fetch(post=post).canonical_url == "https://programming.dev/post/9999"


# --- error handling ---


def test_missing_source_id_raises():
    with pytest.raises(FetchError, match="cannot determine lemmy post"):
        fetch_item(make_item(source_id=None), get_json=fake_get_json())


def test_malformed_source_id_raises():
    with pytest.raises(FetchError, match="cannot determine lemmy post"):
        fetch_item(make_item(source_id="noslash"), get_json=fake_get_json())


def test_post_not_found_raises():
    def get_json(url):
        return {"error": "couldnt_find_post"}

    with pytest.raises(FetchError, match="lemmy post not found"):
        fetch_item(make_item(), get_json=get_json)


def test_api_request_failure_raises():
    def get_json(url):
        raise OSError("connection reset")

    with pytest.raises(FetchError, match="lemmy API request failed"):
        fetch_item(make_item(), get_json=get_json)


def test_registered_via_the_threadiverse_dispatcher():
    # `lemmy` no longer points straight at this adapter: a `/post/<digits>` URL
    # is detected as `lemmy` but its backend (Lemmy or PieFed) is resolved at
    # fetch time, so the registered fetcher is the threadiverse dispatcher that
    # tries this adapter first, then PieFed (ADR 0053).
    from scrolls.sources import threadiverse

    assert FETCH_ADAPTERS["lemmy"] is threadiverse.fetch_item
