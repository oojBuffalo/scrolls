"""Tests for the DEV (dev.to / Forem) fetch adapter (IDEAS.md §6, ADR 0061).

The JSON transport is faked with payloads trimmed from the real
`dev.to/api/articles/<user>/<slug>` API, so the tags-as-concepts join, the
org-post byline, the cross-post link, image media, and metadata
degradation are all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.devto import fetch_item

# Trimmed from https://dev.to/api/articles/devteam/what-was-your-win-this-week-4k11
# — an organization post: the URL handle is the org (`devteam`), the byline
# author is a person (`jess`). canonical_url equals the dev.to url (not a cross-post).
ORG_ARTICLE = {
    "type_of": "article",
    "id": 3773107,
    "title": "What was your win this week?",
    "description": "Looking back on your week -- what was something you're proud of?",
    "slug": "what-was-your-win-this-week-4k11",
    "path": "/devteam/what-was-your-win-this-week-4k11",
    "url": "https://dev.to/devteam/what-was-your-win-this-week-4k11",
    "canonical_url": "https://dev.to/devteam/what-was-your-win-this-week-4k11",
    "cover_image": "https://media2.dev.to/dynamic/image/width=1000/articles/win.jpg",
    "social_image": "https://media2.dev.to/dynamic/image/width=1200/articles/win.jpg",
    "published_at": "2026-06-12T06:00:00Z",
    "published_timestamp": "2026-06-12T06:00:00Z",
    "tag_list": "discuss, weeklyretro",
    "tags": ["discuss", "weeklyretro"],
    "public_reactions_count": 45,
    "comments_count": 40,
    "body_markdown": "Looking back on your week -- what was something you're proud of?"
    "\r\n\r\nAll wins count -- big or small.",
    "body_html": "<p>Looking back ...</p>",
    "user": {"name": "Jess Lee", "username": "jess"},
    "organization": {"name": "The DEV Team", "username": "devteam"},
}

# Trimmed from https://dev.to/api/articles/odeeb/the-sec-edgar-api-... — a
# cross-posted technical article: canonical_url points at the author's own blog,
# no cover image, a real Markdown body.
CROSSPOST_ARTICLE = {
    "type_of": "article",
    "id": 3779999,
    "title": "The SEC EDGAR API: A Practical Guide to Free Filing Data in Python",
    "description": "A hands-on guide to the free SEC EDGAR API in Python.",
    "slug": "the-sec-edgar-api-a-practical-guide-to-free-filing-data-in-python-15b",
    "url": "https://dev.to/odeeb/the-sec-edgar-api-a-practical-guide-to-free-filing-data-in-python-15b",
    "canonical_url": "https://datatooly.xyz/sec-edgar-search/",
    "cover_image": None,
    "social_image": None,
    "published_at": "2026-06-13T16:31:52Z",
    "tag_list": "api, python, finance, datascience",
    "tags": ["api", "python", "finance", "datascience"],
    "public_reactions_count": 0,
    "comments_count": 0,
    "body_markdown": "The **SEC EDGAR API** is one of the best-kept secrets in "
    "financial data engineering.\n\nThe catch is small but absolute.",
    "user": {"name": "Omar Eldeeb", "username": "odeeb"},
    "organization": None,
}


def make_item(**overrides):
    base = dict(
        id="devto:devteam/what-was-your-win-this-week-4k11",
        source="devto",
        source_id="devteam/what-was-your-win-this-week-4k11",
        url="https://dev.to/devteam/what-was-your-win-this-week-4k11",
        saved_at="2026-06-12T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fetch(data=ORG_ARTICLE, item=None):
    return fetch_item(item or make_item(), get_json=lambda url: dict(data))


def test_fetch_records_article_metadata_and_concepts():
    fetched = fetch(ORG_ARTICLE)

    assert fetched.title == "What was your win this week?"
    # the byline is the person, not the org the post is published under
    assert fetched.author == "Jess Lee"
    assert fetched.published_at == "2026-06-12T06:00:00+00:00"
    # the scroll's canonical is the dev.to permalink
    assert fetched.canonical_url == "https://dev.to/devteam/what-was-your-win-this-week-4k11"
    # the curated tags become concepts (the whole point — github topics pattern)
    assert fetched.concepts == ("discuss", "weeklyretro")
    # dev.to has no license/classifier facet, so tags stay empty (github's posture)
    assert fetched.tags == ()
    # the Markdown body is the searchable text, CRLF normalized
    assert fetched.extracted_text.startswith("Looking back on your week")
    assert "\r" not in fetched.extracted_text
    # the platform's own excerpt is the summary
    assert fetched.summary == "Looking back on your week -- what was something you're proud of?"
    # the cover image becomes a thumbnail media ref
    assert fetched.media == (
        {"type": "thumbnail", "url": "https://media2.dev.to/dynamic/image/width=1000/articles/win.jpg"},
    )
    # not a cross-post: no external link
    assert fetched.links == ()
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.provenance["adapter"] == "devto"
    assert fetched.provenance["extraction_method"] == "devto-api:article"
    assert fetched.stage == "fetched"


def test_crosspost_canonical_becomes_a_link():
    item = make_item(
        id="devto:odeeb/the-sec-edgar-api-a-practical-guide-to-free-filing-data-in-python-15b",
        source_id="odeeb/the-sec-edgar-api-a-practical-guide-to-free-filing-data-in-python-15b",
        url=CROSSPOST_ARTICLE["url"],
    )
    fetched = fetch(CROSSPOST_ARTICLE, item=item)

    assert fetched.author == "Omar Eldeeb"
    assert fetched.concepts == ("api", "python", "finance", "datascience")
    # the dev.to permalink is the scroll's canonical; the external original is an edge
    assert fetched.canonical_url == CROSSPOST_ARTICLE["url"]
    assert fetched.links == ("https://datatooly.xyz/sec-edgar-search/",)
    # no cover image: no media ref
    assert fetched.media == ()
    assert fetched.summary == "A hands-on guide to the free SEC EDGAR API in Python."


def test_concepts_fall_back_to_tag_list_string():
    data = {key: value for key, value in ORG_ARTICLE.items() if key != "tags"}
    assert fetch(data).concepts == ("discuss", "weeklyretro")


def test_concepts_dedupe_preserving_order():
    data = {**ORG_ARTICLE, "tags": ["python", "api", "python", " api "]}
    assert fetch(data).concepts == ("python", "api")


def test_author_falls_back_to_handle_then_none():
    handle_only = {**ORG_ARTICLE, "user": {"username": "ghost"}}
    assert fetch(handle_only).author == "ghost"
    no_user = {**ORG_ARTICLE, "user": None}
    assert fetch(no_user).author is None


def test_summary_falls_back_to_body_lead_then_engagement():
    no_desc = {key: value for key, value in ORG_ARTICLE.items() if key != "description"}
    assert fetch(no_desc).summary.startswith("Looking back on your week")

    bare = {**no_desc, "body_markdown": "", "public_reactions_count": 45, "comments_count": 40}
    fetched = fetch(bare)
    assert fetched.extracted_text is None
    assert fetched.summary == "DEV post: 45 reactions, 40 comments."
    assert fetched.provenance["extraction_method"] == "devto-api:metadata"


def test_engagement_summary_uses_singular_units():
    data = {key: value for key, value in ORG_ARTICLE.items() if key != "description"}
    data = {**data, "body_markdown": "", "public_reactions_count": 1, "comments_count": 1}
    assert fetch(data).summary == "DEV post: 1 reaction, 1 comment."


def test_stub_without_excerpt_body_or_engagement_has_no_summary():
    data = {
        key: value
        for key, value in ORG_ARTICLE.items()
        if key not in ("description", "body_markdown", "public_reactions_count", "comments_count")
    }
    assert fetch(data).summary is None


def test_social_image_is_the_thumbnail_fallback():
    data = {**ORG_ARTICLE, "cover_image": None}
    assert fetch(data).media == (
        {"type": "thumbnail", "url": "https://media2.dev.to/dynamic/image/width=1200/articles/win.jpg"},
    )


def test_non_http_cover_image_is_dropped():
    data = {**ORG_ARTICLE, "cover_image": "data:image/png;base64,xxxx", "social_image": None}
    assert fetch(data).media == ()


def test_keeps_raw_record_for_rebuilds():
    raw = json.loads(fetch(ORG_ARTICLE).raw_text)
    assert raw["id"] == 3773107
    assert raw["organization"]["username"] == "devteam"


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://dev.to/devteam/what-was-your-win-this-week-4k11?utm_source=x")
    fetched = fetch(ORG_ARTICLE, item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url  # the URL the user saved, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_keeps_seeded_published_at_when_article_has_no_date():
    data = {
        key: value
        for key, value in ORG_ARTICLE.items()
        if key not in ("published_at", "published_timestamp")
    }
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(data, item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_requests_the_expected_api_url():
    seen = []

    def capture(url):
        seen.append(url)
        return dict(ORG_ARTICLE)

    fetch_item(make_item(), get_json=capture)
    assert seen == [
        "https://dev.to/api/articles/devteam/what-was-your-win-this-week-4k11"
    ]


@pytest.mark.parametrize("source_id", [None, "", "no-slash"])
def test_requires_a_user_slug_id(source_id):
    item = make_item(id="devto:profile", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine dev.to article"):
        fetch_item(item, get_json=lambda url: dict(ORG_ARTICLE))


def test_missing_article_is_a_fetch_error():
    # a body with no title (a 404 page parsed, or a stray payload) is rejected
    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_item(), get_json=lambda url: {"error": "not found", "status": 404})


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="request failed"):
        fetch_item(make_item(), get_json=boom)


def test_devto_adapter_is_registered():
    assert FETCH_ADAPTERS["devto"] is fetch_item
