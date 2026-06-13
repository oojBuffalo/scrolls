"""Tests for the Lobsters fetch adapter (IDEAS.md §6, ADR 0046).

The JSON transport is faked with payloads trimmed from the real
`lobste.rs/s/<id>.json` API, so the link/text split, the one-request
comment thread, deleted/moderated skipping, and metadata degradation are
all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.lobsters import fetch_item

# Trimmed from https://lobste.rs/s/<id>.json
LINK_STORY = {  # a link submission carrying a submitter note and a threaded discussion
    "short_id": "lxoosd",
    "short_id_url": "https://lobste.rs/s/lxoosd",
    "created_at": "2026-06-12T08:43:51.000-05:00",
    "title": "German court ruling declares Google's AI Overviews are Google's own words",
    "url": "https://the-decoder.com/landmark-german-ruling/",
    "score": 281,
    "comment_count": 3,
    "description_plain": "Title trimmed slightly without altering meaning.",
    "submitter_user": "gspr",
    "tags": ["law"],
    "comments": [
        {
            "short_id": "c_a", "depth": 0, "score": 163,
            "commenting_user": "gspr",
            "is_deleted": False, "is_moderated": False,
            "comment_plain": "This seems eminently reasonable to me.",
        },
        {
            "short_id": "c_b", "depth": 1, "score": 12,
            "commenting_user": "alice",
            "is_deleted": False, "is_moderated": False,
            "comment_plain": "Agreed, though the liability question is murkier.",
        },
        {  # a removed comment contributes nothing
            "short_id": "c_c", "depth": 1, "score": -2,
            "commenting_user": "bob",
            "is_deleted": True, "is_moderated": False,
            "comment_plain": "",
        },
    ],
}

TEXT_STORY = {  # a text submission: a body, an empty url, no comments
    "short_id": "qnv1dy",
    "short_id_url": "https://lobste.rs/s/qnv1dy",
    "created_at": "2026-06-12T07:00:00.000-05:00",
    "title": "What are you doing this weekend?",
    "url": "",
    "score": 9,
    "comment_count": 0,
    "description_plain": "Feel free to tell what you plan on doing this weekend.\r\n\r\n"
    "It's more than OK to do nothing at all too!",
    "submitter_user": "caleb",
    "tags": ["ask", "programming"],
    "comments": [],
}


def make_item(**overrides):
    base = dict(
        id="lobsters:lxoosd",
        source="lobsters",
        source_id="lxoosd",
        url="https://lobste.rs/s/lxoosd",
        saved_at="2026-06-12T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fetch(data=LINK_STORY, item=None):
    return fetch_item(item or make_item(), get_json=lambda url: dict(data))


def test_fetch_link_story_records_article_and_discussion():
    fetched = fetch(LINK_STORY)

    assert fetched.title.startswith("German court ruling")
    assert fetched.author == "gspr"
    # the source date carries a -05:00 offset; it is normalized to UTC
    assert fetched.published_at == "2026-06-12T13:43:51+00:00"
    assert fetched.canonical_url == "https://lobste.rs/s/lxoosd"
    # curated tags become concepts, like github repo topics
    assert fetched.concepts == ("law",)
    # the linked article rides along in links so `related`/`graph` can resolve it
    assert fetched.links == ("https://the-decoder.com/landmark-german-ruling/",)
    # the whole thread arrives in one request and becomes searchable text
    text = fetched.extracted_text
    assert "### Comments" in text
    assert "Comment by gspr (score 163)" in text
    assert "This seems eminently reasonable" in text
    assert "Comment by alice (score 12)" in text
    # the submitter note (a body) precedes the discussion
    assert text.index("Title trimmed slightly") < text.index("### Comments")
    assert fetched.summary == "Title trimmed slightly without altering meaning."
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.provenance["adapter"] == "lobsters"
    assert fetched.provenance["extraction_method"] == "lobsters-api:story+comments"
    assert fetched.stage == "fetched"


def test_fetch_text_story_keeps_body_and_lead_summary():
    fetched = fetch(TEXT_STORY, item=make_item(id="lobsters:qnv1dy", source_id="qnv1dy"))

    assert fetched.author == "caleb"
    assert fetched.concepts == ("ask", "programming")
    # CRLF is normalized; the body is the searchable text
    assert fetched.extracted_text.startswith("Feel free to tell what you plan")
    assert "\r" not in fetched.extracted_text
    # the lead paragraph is the summary, the way wikipedia/HN/SE lead
    assert fetched.summary == "Feel free to tell what you plan on doing this weekend."
    # a text submission has no external article
    assert fetched.links == ()
    # no comments: story-only method
    assert fetched.provenance["extraction_method"] == "lobsters-api:story"


def test_skips_deleted_and_moderated_comments():
    data = {
        **LINK_STORY,
        "comments": [
            {"commenting_user": "alice", "score": 5, "is_deleted": False,
             "is_moderated": False, "comment_plain": "a kept reply"},
            {"commenting_user": "bob", "score": 1, "is_deleted": True,
             "is_moderated": False, "comment_plain": "a removed reply"},
            {"commenting_user": "carol", "score": 1, "is_deleted": False,
             "is_moderated": True, "comment_plain": "a hidden reply"},
        ],
    }
    text = fetch(data).extracted_text
    assert "a kept reply" in text
    assert "a removed reply" not in text
    assert "a hidden reply" not in text


def test_link_story_without_body_or_comments_uses_status_summary():
    data = {**LINK_STORY, "description_plain": "", "comments": [],
            "score": 281, "comment_count": 71}
    fetched = fetch(data)
    assert fetched.extracted_text is None
    assert fetched.summary == "Lobsters discussion: 281 points, 71 comments."
    assert fetched.links == ("https://the-decoder.com/landmark-german-ruling/",)
    assert fetched.provenance["extraction_method"] == "lobsters-api:story"


def test_status_summary_uses_singular_units():
    data = {**LINK_STORY, "description_plain": "", "comments": [],
            "score": 1, "comment_count": 1}
    assert fetch(data).summary == "Lobsters discussion: 1 point, 1 comment."


def test_story_without_status_has_no_summary():
    data = {key: value for key, value in LINK_STORY.items()
            if key not in ("score", "comment_count", "description_plain")}
    data["comments"] = []
    assert fetch(data).summary is None


def test_keeps_raw_records_for_rebuilds():
    raw = json.loads(fetch(LINK_STORY).raw_text)
    assert raw["short_id"] == "lxoosd"
    # comment depth survives for a future threaded-render enrichment
    assert raw["comments"][1]["depth"] == 1


def test_reads_legacy_submitter_object_shape():
    data = {**LINK_STORY, "submitter_user": {"username": "legacy"}}
    assert fetch(data).author == "legacy"


def test_canonical_url_falls_back_to_the_story_path():
    data = {key: value for key, value in LINK_STORY.items() if key != "short_id_url"}
    assert fetch(data).canonical_url == "https://lobste.rs/s/lxoosd"


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://lobste.rs/s/lxoosd/some_slug?utm_source=x")
    fetched = fetch(LINK_STORY, item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url  # the URL the user saved, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_keeps_seeded_published_at_when_story_has_no_date():
    data = {key: value for key, value in LINK_STORY.items() if key != "created_at"}
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(data, item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_requests_the_expected_api_url():
    seen = []

    def capture(url):
        seen.append(url)
        return dict(LINK_STORY)

    fetch_item(make_item(), get_json=capture)
    assert seen == ["https://lobste.rs/s/lxoosd.json"]


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_a_story_id(source_id):
    item = make_item(id="lobsters:front", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine lobsters story"):
        fetch_item(item, get_json=lambda url: dict(LINK_STORY))


def test_missing_story_is_a_fetch_error():
    # a body with no short_id (a 404 page parsed, or a stray payload) is rejected
    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_item(), get_json=lambda url: {})


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="request failed"):
        fetch_item(make_item(), get_json=boom)


def test_lobsters_adapter_is_registered():
    assert FETCH_ADAPTERS["lobsters"] is fetch_item
