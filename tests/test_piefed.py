"""Tests for the PieFed fetch adapter (IDEAS.md §6, ADR 0053).

The HTTP transport is faked with payloads shaped from the real PieFed `/api/alpha`
API (`/api/alpha/post` and `/api/alpha/comment/list`), so the post+thread merge,
PieFed's field-name mapping (`post.title`, `creator.user_name`, `comment.body`,
the `post_type` enum), body extraction, link/cross-post edges, community→concept,
threaded comment render, deleted/removed skipping, image/thumbnail media,
engagement-status summary, canonical `ap_id`, and error handling are all covered
offline (ADR 0001). The dispatch (Lemmy first, PieFed fallback) is in
test_threadiverse.py.
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources.piefed import fetch_item

# Shaped from GET /api/alpha/post?id=<id>: a Link post (an external article) with
# a Markdown body that also carries an inline URL, a community, counts, a
# thumbnail, and a cross-post (PieFed nests cross_posts on the post itself, with
# a post_id and no ap_id — unlike Lemmy's top-level full post views).
POST_RESPONSE = {
    "post_view": {
        "post": {
            "id": 1600132,
            "title": "PieFed 1.4 is released — emoji and AI content filters",
            "url": "https://join.piefed.social/2026/06/release-1-4",
            "post_type": "Link",
            "body": "The release notes are long this time.\n\n"
            "See also https://arxiv.org/abs/1706.03762 for the attention model.",
            "thumbnail_url": "https://piefed.social/static/media/thumb.jpeg",
            "community_id": 9,
            "user_id": 5,
            "published": "2026-06-11T16:15:34.343Z",
            "ap_id": "https://piefed.social/post/1600132",
            "nsfw": False,
            "removed": False,
            "deleted": False,
            "cross_posts": [
                {"post_id": 1600200, "community_name": "fediverse", "reply_count": 3}
            ],
        },
        "creator": {
            "id": 5,
            "user_name": "rimu",
            "display_name": "Rimu",
            "title": "rimu@piefed.social",
            "actor_id": "https://piefed.social/u/rimu",
        },
        "community": {
            "id": 9,
            "name": "piefed_meta",
            "title": "PieFed Meta",
            "actor_id": "https://piefed.social/c/piefed_meta",
        },
        "counts": {
            "post_id": 1600132,
            "comments": 4,
            "score": 142,
            "upvotes": 150,
            "downvotes": 8,
        },
    },
}

# Shaped from GET /api/alpha/comment/list?post_id=<id>: a flat list whose `path`
# encodes the thread tree ("0.<id>" top-level, "0.<parent>.<id>" a reply). The
# comment text is in `body` (Lemmy's field is `content`). A deleted and a removed
# comment carry no usable text and are skipped.
COMMENTS = [
    {
        "comment": {
            "id": 5,
            "body": "Love the new emoji reactions.",
            "path": "0.5",
            "published": "2026-06-11T17:00:00Z",
            "ap_id": "https://piefed.social/comment/5",
            "deleted": False,
            "removed": False,
        },
        "creator": {"user_name": "alice", "display_name": "Alice"},
        "counts": {"score": 30, "child_count": 1},
    },
    {
        "comment": {
            "id": 12,
            "body": "Agreed — the AI filters are the headline feature though.",
            "path": "0.5.12",
            "deleted": False,
            "removed": False,
        },
        # display_name absent -> byline falls back to the bare user_name
        "creator": {"user_name": "bob", "display_name": None},
        "counts": {"score": 8, "child_count": 0},
    },
    {  # deleted by its author -> skipped
        "comment": {"id": 20, "body": "", "path": "0.20", "deleted": True, "removed": False},
        "creator": {"user_name": "carol", "display_name": "Carol"},
        "counts": {"score": 0, "child_count": 0},
    },
    {  # removed by a mod -> skipped
        "comment": {"id": 21, "body": "spammy text", "path": "0.21", "deleted": False, "removed": True},
        "creator": {"user_name": "spammer"},
        "counts": {"score": -5, "child_count": 0},
    },
]


def make_item(**overrides):
    # A PieFed post is detected and registered as a `lemmy` item — its URL is
    # indistinguishable from Lemmy's — so its source/source_id are the lemmy ones.
    base = dict(
        id="lemmy:piefed.social/1600132",
        source="lemmy",
        source_id="piefed.social/1600132",
        url="https://piefed.social/post/1600132",
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

    assert fetched.title == "PieFed 1.4 is released — emoji and AI content filters"
    assert fetched.author == "Rimu"
    assert fetched.published_at == "2026-06-11T16:15:34+00:00"
    # canonical is the federated ap_id (origin instance), not the saved URL
    assert fetched.canonical_url == "https://piefed.social/post/1600132"
    assert fetched.provenance["adapter"] == "piefed"
    assert fetched.provenance["extraction_method"] == "piefed-api:post+comments"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_hits_the_api_alpha_namespace():
    # PieFed serves /api/alpha, not Lemmy's /api/v3 — the whole reason it needs
    # its own adapter behind the shared detection (ADR 0053)
    calls = []
    fetch(on_call=calls.append)
    assert all("/api/alpha/" in url for url in calls)
    assert any("/api/v3/" in url for url in calls) is False


def test_title_comes_from_the_title_field():
    # PieFed's title field is `title` (Lemmy's is `name`) — the mapping that
    # most distinguishes the adapter
    post = {
        "post_view": {
            **POST_RESPONSE["post_view"],
            "post": {**POST_RESPONSE["post_view"]["post"], "name": "WRONG (lemmy field)"},
        }
    }
    assert fetch(post=post).title.startswith("PieFed 1.4")


def test_author_comes_from_user_name_field():
    # PieFed's username field is `user_name` (Lemmy's is `name`); here a post with
    # no display_name falls back to it
    post = {
        "post_view": {
            **POST_RESPONSE["post_view"],
            "creator": {"user_name": "rimu", "display_name": None},
        }
    }
    assert fetch(post=post).author == "rimu"


def test_summary_is_the_body_lead_paragraph():
    assert fetch().summary == "The release notes are long this time."


def test_community_becomes_a_concept():
    assert fetch().concepts == ("piefed_meta",)


def test_link_post_url_becomes_a_link():
    assert "https://join.piefed.social/2026/06/release-1-4" in fetch().links


def test_body_urls_become_links():
    # a URL in the markdown body is a cross-source edge (the arXiv paper)
    assert "https://arxiv.org/abs/1706.03762" in fetch().links


def test_cross_post_becomes_a_same_instance_link():
    # PieFed nests cross_posts with a post_id and no ap_id, so the edge is built
    # as a same-instance /post/<post_id> URL (ADR 0053)
    assert "https://piefed.social/post/1600200" in fetch().links


def test_comments_are_bylined_and_thread_ordered():
    text = fetch().extracted_text
    assert "### Comments" in text
    assert "#### Comment by Alice (score 30)" in text
    # a reply with no display name falls back to the bare user_name
    assert "#### Comment by bob (score 8)" in text
    # the post body leads the extracted content, before the comments
    assert text.index("release notes are long") < text.index("### Comments")
    # path order puts the reply (0.5.12) right after its parent (0.5)
    assert text.index("Alice (score 30)") < text.index("bob (score 8)")


def test_deleted_and_removed_comments_are_skipped():
    text = fetch().extracted_text
    assert "Carol" not in text  # deleted
    assert "spammy text" not in text  # removed


def test_no_comments_skips_the_comment_request():
    calls = []
    post = {
        "post_view": {
            **POST_RESPONSE["post_view"],
            "counts": {**POST_RESPONSE["post_view"]["counts"], "comments": 0},
        }
    }
    fetched = fetch(post=post, on_call=calls.append)
    assert not any("comment/list" in url for url in calls)
    assert fetched.provenance["extraction_method"] == "piefed-api:post"


def test_comment_failure_degrades_to_post_only():
    def get_json(url):
        if "/comment/list" in url:
            raise OSError("connection reset")
        return POST_RESPONSE

    fetched = fetch_item(make_item(), get_json=get_json)
    assert fetched.extracted_text.startswith("The release notes are long")
    assert "### Comments" not in fetched.extracted_text
    assert fetched.provenance["extraction_method"] == "piefed-api:post"


def test_raw_text_keeps_post_and_comments():
    raw = json.loads(fetch().raw_text)
    assert raw["post"]["post_view"]["post"]["id"] == 1600132
    assert len(raw["comments"]) == 4  # everything, including the skipped nodes


# --- a text (self) post: no external url, body is the content ---

TEXT_POST = {
    "post_view": {
        "post": {
            "id": 100,
            "title": "What note-taking setup do you use?",
            "url": None,
            "post_type": "Discussion",
            "body": "I'm looking for a local-first option. What works for you?",
            "thumbnail_url": None,
            "published": "2026-06-12T09:00:00Z",
            "ap_id": "https://piefed.social/post/100",
            "cross_posts": [],
        },
        "creator": {"user_name": "dave", "display_name": "Dave"},
        "community": {"name": "asklemmy", "title": "Ask"},
        "counts": {"comments": 0, "score": 5},
    },
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
            "title": "An interesting article",
            "url": "https://example.com/article",
            "post_type": "Link",
            "body": None,
            "thumbnail_url": "https://piefed.social/static/media/t.jpeg",
            "published": "2026-06-12T09:00:00Z",
            "ap_id": "https://piefed.social/post/200",
            "cross_posts": [],
        },
        "creator": {"user_name": "erin"},
        "community": {"name": "technology"},
        "counts": {"comments": 17, "score": 88},
    },
}


def test_link_only_post_summary_is_engagement_status():
    fetched = fetch(post=LINK_ONLY_POST, comments=[])
    assert fetched.summary == "PieFed discussion: 88 points, 17 comments."


def test_link_post_thumbnail_becomes_thumbnail_media():
    assert fetch(post=LINK_ONLY_POST, comments=[]).media == (
        {"type": "thumbnail", "url": "https://piefed.social/static/media/t.jpeg"},
    )
    assert "https://example.com/article" in fetch(post=LINK_ONLY_POST, comments=[]).links


# --- an image post: post_type == "Image", so the url IS the image (photo media) ---

IMAGE_POST = {
    "post_view": {
        "post": {
            "id": 300,
            "title": "A diagram of an SQLite FTS5 inverted index",
            "url": "https://piefed.social/static/media/diagram.png",
            "post_type": "Image",
            "body": None,
            "thumbnail_url": "https://piefed.social/static/media/diagram-thumb.png",
            "published": "2026-06-12T09:00:00Z",
            "ap_id": "https://piefed.social/post/300",
            "cross_posts": [],
        },
        "creator": {"user_name": "frank"},
        "community": {"name": "dataisbeautiful"},
        "counts": {"comments": 0, "score": 200},
    },
}


def test_image_post_url_becomes_photo_media():
    fetched = fetch(post=IMAGE_POST)
    assert fetched.media == (
        {"type": "photo", "url": "https://piefed.social/static/media/diagram.png"},
    )
    # the image url is media, never a duplicate link
    assert fetched.links == ()


def test_image_detected_by_post_type_even_without_extension():
    # post_type drives the decision, so an extensionless image url is still photo
    post = {
        "post_view": {
            **IMAGE_POST["post_view"],
            "post": {
                **IMAGE_POST["post_view"]["post"],
                "url": "https://piefed.social/static/media/abcdef",
            },
        }
    }
    fetched = fetch(post=post)
    assert fetched.media == (
        {"type": "photo", "url": "https://piefed.social/static/media/abcdef"},
    )


# --- a federated (remote) post viewed via another instance ---


def test_remote_post_canonical_is_the_origin_ap_id():
    post = {
        "post_view": {
            **POST_RESPONSE["post_view"],
            "post": {
                **POST_RESPONSE["post_view"]["post"],
                "ap_id": "https://lemmy.world/post/9999",
            },
            "counts": {**POST_RESPONSE["post_view"]["counts"], "comments": 0},
        }
    }
    assert fetch(post=post).canonical_url == "https://lemmy.world/post/9999"


# --- error handling (the dispatcher reads these FetchErrors as "not PieFed") ---


def test_missing_source_id_raises():
    with pytest.raises(FetchError, match="cannot determine piefed post"):
        fetch_item(make_item(source_id=None), get_json=fake_get_json())


def test_malformed_source_id_raises():
    with pytest.raises(FetchError, match="cannot determine piefed post"):
        fetch_item(make_item(source_id="noslash"), get_json=fake_get_json())


def test_post_not_found_raises():
    def get_json(url):
        return {"error": "couldnt_find_post"}

    with pytest.raises(FetchError, match="piefed post not found"):
        fetch_item(make_item(), get_json=get_json)


def test_api_request_failure_raises():
    def get_json(url):
        raise OSError("connection reset")

    with pytest.raises(FetchError, match="piefed API request failed"):
        fetch_item(make_item(), get_json=get_json)
