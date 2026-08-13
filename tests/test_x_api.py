"""Tests for the official X API v2 bookmarks path.

The endpoint returns a flat `data[]` with side-loaded `includes`, a different
shape from the internal GraphQL the cookie path walks. The property that
matters most here is that the *items* come out identical anyway: same ids,
same fields, same custody claims. Only the extraction method differs.
"""

import urllib.error

import pytest

from scrolls.x_api import (
    XAPIAuthError,
    XAPIError,
    XAPIRateLimited,
    _map_http_error,
    build_url,
    fetch_bookmarks,
    parse_bookmarks_page,
    resolve_user_id,
)
from scrolls.x_bookmarks import parse_bookmarks_page as parse_graphql_page

SYNCED_AT = "2026-08-13T12:00:00+00:00"


def _payload(records, *, users=None, tweets=None, media=None, next_token=None):
    payload = {
        "data": records,
        "includes": {
            "users": users or [{"id": "u1", "username": "karpathy", "name": "Andrej Karpathy"}],
            "tweets": tweets or [],
            "media": media or [],
        },
        "meta": {"result_count": len(records)},
    }
    if next_token:
        payload["meta"]["next_token"] = next_token
    return payload


def _record(tweet_id="1", **overrides):
    record = {
        "id": str(tweet_id),
        "text": f"a saved post {tweet_id}",
        "created_at": "2026-06-01T15:34:00.000Z",
        "author_id": "u1",
    }
    record.update(overrides)
    return record


# --- parsing -------------------------------------------------------------


def test_a_record_becomes_a_fetched_x_item():
    page = parse_bookmarks_page(_payload([_record(1)]), synced_at=SYNCED_AT)
    (item,) = page.items
    assert item.id == "x:1"
    assert item.source == "x"
    assert item.stage == "fetched"
    assert item.url == "https://x.com/karpathy/status/1"
    assert item.author == "Andrej Karpathy (@karpathy)"
    assert item.extracted_text == "a saved post 1"
    assert item.published_at == "2026-06-01T15:34:00+00:00"


def test_the_extraction_method_distinguishes_the_official_path():
    page = parse_bookmarks_page(_payload([_record(1)]), synced_at=SYNCED_AT)
    assert page.items[0].provenance["extraction_method"] == "x:api-v2"


def test_the_official_path_has_no_bookmark_timestamp_either():
    """Neither X path exposes one, so both must say so identically."""
    page = parse_bookmarks_page(_payload([_record(1)]), synced_at=SYNCED_AT)
    item = page.items[0]
    assert item.saved_at == SYNCED_AT
    assert item.provenance["saved_at_source"] == "synced_at"


def test_note_tweet_wins_over_the_truncated_text():
    record = _record(1, note_tweet={"text": "the whole long-form post"})
    item = parse_bookmarks_page(_payload([record]), synced_at=SYNCED_AT).items[0]
    assert item.extracted_text == "the whole long-form post"


def test_expanded_links_are_captured_not_the_t_co_shortener():
    record = _record(
        1,
        entities={
            "urls": [{"url": "https://t.co/abc", "expanded_url": "https://example.com/x"}]
        },
    )
    item = parse_bookmarks_page(_payload([record]), synced_at=SYNCED_AT).items[0]
    assert item.links == ("https://example.com/x",)


def test_media_keys_resolve_through_includes():
    record = _record(1, attachments={"media_keys": ["3_9"]})
    payload = _payload(
        [record],
        media=[{"media_key": "3_9", "type": "photo", "url": "https://pbs.twimg.com/a.jpg"}],
    )
    item = parse_bookmarks_page(payload, synced_at=SYNCED_AT).items[0]
    assert item.media == ({"type": "photo", "url": "https://pbs.twimg.com/a.jpg"},)


def test_a_video_falls_back_to_its_preview_frame():
    """Videos carry no `url`; the still is the addressable artifact."""
    record = _record(1, attachments={"media_keys": ["7_9"]})
    payload = _payload(
        [record],
        media=[
            {
                "media_key": "7_9",
                "type": "video",
                "preview_image_url": "https://pbs.twimg.com/p.jpg",
            }
        ],
    )
    item = parse_bookmarks_page(payload, synced_at=SYNCED_AT).items[0]
    assert item.media == ({"type": "video", "url": "https://pbs.twimg.com/p.jpg"},)


def test_a_quoted_post_is_folded_into_the_body():
    record = _record(
        1, referenced_tweets=[{"type": "quoted", "id": "99"}]
    )
    payload = _payload(
        [record],
        users=[
            {"id": "u1", "username": "karpathy", "name": "Andrej Karpathy"},
            {"id": "u2", "username": "quoted_one", "name": "Quoted"},
        ],
        tweets=[{"id": "99", "text": "the quoted text", "author_id": "u2"}],
    )
    item = parse_bookmarks_page(payload, synced_at=SYNCED_AT).items[0]
    assert "Quoting @quoted_one: the quoted text" in item.extracted_text


def test_a_replied_to_reference_is_not_treated_as_a_quote():
    record = _record(1, referenced_tweets=[{"type": "replied_to", "id": "99"}])
    payload = _payload([record], tweets=[{"id": "99", "text": "not a quote"}])
    item = parse_bookmarks_page(payload, synced_at=SYNCED_AT).items[0]
    assert "Quoting" not in (item.extracted_text or "")


def test_an_unknown_author_still_yields_a_usable_item():
    """A missing includes.users entry must not lose the bookmark."""
    record = _record(1, author_id="missing")
    item = parse_bookmarks_page(_payload([record]), synced_at=SYNCED_AT).items[0]
    assert item.url == "https://x.com/i/status/1"
    assert item.author is None


def test_a_record_without_an_id_is_a_failure_not_a_crash():
    page = parse_bookmarks_page(_payload([{"text": "orphan"}]), synced_at=SYNCED_AT)
    assert page.items == ()
    assert page.failures and "no tweet id" in page.failures[0]["error"]


def test_an_empty_collection_parses_to_nothing():
    page = parse_bookmarks_page({"meta": {"result_count": 0}}, synced_at=SYNCED_AT)
    assert page.items == () and page.next_token is None


# --- parity with the cookie path -----------------------------------------


def _graphql_payload(tweet_id):
    return {
        "data": {
            "bookmark_timeline_v2": {
                "timeline": {
                    "instructions": [
                        {
                            "type": "TimelineAddEntries",
                            "entries": [
                                {
                                    "entryId": f"tweet-{tweet_id}",
                                    "content": {
                                        "itemContent": {
                                            "tweet_results": {
                                                "result": {
                                                    "__typename": "Tweet",
                                                    "rest_id": str(tweet_id),
                                                    "core": {
                                                        "user_results": {
                                                            "result": {
                                                                "core": {
                                                                    "screen_name": "karpathy",
                                                                    "name": "Andrej Karpathy",
                                                                }
                                                            }
                                                        }
                                                    },
                                                    "legacy": {
                                                        "full_text": f"a saved post {tweet_id}",
                                                        "created_at": (
                                                            "Mon Jun 01 15:34:00 +0000 2026"
                                                        ),
                                                    },
                                                }
                                            }
                                        }
                                    },
                                }
                            ],
                        }
                    ]
                }
            }
        }
    }


def test_both_paths_produce_the_same_item_for_the_same_bookmark():
    """The route must not change the artifact — only how it was reached."""
    official = parse_bookmarks_page(_payload([_record(1)]), synced_at=SYNCED_AT).items[0]
    cookie = parse_graphql_page(_graphql_payload(1), synced_at=SYNCED_AT).items[0]

    for field in ("id", "source", "source_id", "url", "title", "author",
                  "published_at", "extracted_text", "content_hash", "saved_at",
                  "stage"):
        assert getattr(official, field) == getattr(cookie, field), field
    # Provenance differs in exactly one place, by design.
    assert official.provenance["extraction_method"] != cookie.provenance["extraction_method"]
    assert official.provenance["saved_at_source"] == cookie.provenance["saved_at_source"]


# --- transport -----------------------------------------------------------


class _Fetcher:
    """Returns queued payloads and records the URLs it was called with."""

    def __init__(self, pages, me="u1"):
        self.pages = list(pages)
        self.urls = []
        self.me = me

    def __call__(self, url, headers):
        self.urls.append(url)
        if url.endswith("/users/me"):
            return {"data": {"id": self.me}}
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return page


def test_the_url_requests_every_field_parity_depends_on():
    url = build_url("u1")
    for field in ("note_tweet", "created_at", "entities", "attachments"):
        assert field in url
    assert "expansions=" in url and "referenced_tweets.id" in url


def test_the_user_id_is_looked_up_once_then_reused():
    fetcher = _Fetcher([_payload([_record(1)], next_token="T1"), _payload([_record(2)])])
    fetch_bookmarks(
        "TOKEN", synced_at=SYNCED_AT, get=fetcher, sleep=lambda _: None
    )
    assert sum(1 for url in fetcher.urls if url.endswith("/users/me")) == 1


def test_a_supplied_user_id_skips_the_lookup_entirely():
    fetcher = _Fetcher([_payload([_record(1)])])
    fetch_bookmarks(
        "TOKEN", synced_at=SYNCED_AT, user_id="u9", get=fetcher, sleep=lambda _: None
    )
    assert not any(url.endswith("/users/me") for url in fetcher.urls)
    assert "/users/u9/bookmarks" in fetcher.urls[0]


def test_walks_every_page_and_concatenates_in_order():
    fetcher = _Fetcher(
        [
            _payload([_record(1), _record(2)], next_token="T1"),
            _payload([_record(3)]),
        ]
    )
    result = fetch_bookmarks(
        "TOKEN", synced_at=SYNCED_AT, get=fetcher, sleep=lambda _: None
    )
    assert [item.source_id for item in result.items] == ["1", "2", "3"]
    assert result.pages == 2


def test_each_page_after_the_first_sends_the_previous_token():
    fetcher = _Fetcher([_payload([_record(1)], next_token="T1"), _payload([_record(2)])])
    fetch_bookmarks("TOKEN", synced_at=SYNCED_AT, get=fetcher, sleep=lambda _: None)
    assert "pagination_token=T1" in fetcher.urls[-1]


def test_stops_at_the_requested_limit():
    fetcher = _Fetcher([_payload([_record(1), _record(2)], next_token="T1")])
    result = fetch_bookmarks(
        "TOKEN", synced_at=SYNCED_AT, limit=1, get=fetcher, sleep=lambda _: None
    )
    assert len(result.items) == 1


def test_an_empty_page_ends_the_walk_even_with_a_token_offered():
    fetcher = _Fetcher(
        [_payload([_record(1)], next_token="T1"), _payload([], next_token="T2")]
    )
    result = fetch_bookmarks(
        "TOKEN", synced_at=SYNCED_AT, get=fetcher, sleep=lambda _: None
    )
    assert len(result.items) == 1


def test_a_repeated_token_ends_the_walk_instead_of_looping():
    fetcher = _Fetcher(
        [
            _payload([_record(1)], next_token="SAME"),
            _payload([_record(2)], next_token="SAME"),
            _payload([_record(3)], next_token="SAME"),
        ]
    )
    result = fetch_bookmarks(
        "TOKEN", synced_at=SYNCED_AT, get=fetcher, sleep=lambda _: None
    )
    assert len(result.items) == 2


def test_items_already_collected_survive_a_later_page_failing():
    fetcher = _Fetcher([_payload([_record(1)], next_token="T1"), XAPIError("boom")])
    result = fetch_bookmarks(
        "TOKEN", synced_at=SYNCED_AT, get=fetcher, sleep=lambda _: None,
        stop_on_error=True,
    )
    assert [item.source_id for item in result.items] == ["1"]
    assert result.error is not None


def test_a_grant_with_no_user_id_is_an_honest_error():
    with pytest.raises(XAPIError, match="no user id"):
        resolve_user_id("TOKEN", get=lambda url, headers: {"data": {}})


# --- status mapping ------------------------------------------------------


def _http_error(code, headers=None):
    return urllib.error.HTTPError("https://api.x.com", code, "err", headers or {}, None)


@pytest.mark.parametrize("code", [401, 403])
def test_auth_statuses_name_the_scope_and_the_fix(code):
    mapped = _map_http_error(_http_error(code))
    assert isinstance(mapped, XAPIAuthError)
    assert "scrolls x login" in str(mapped)
    assert "bookmark.read" in str(mapped)


def test_a_402_says_the_problem_is_billing_not_the_code():
    """The official path is metered; a paywall must not read as a bug."""
    mapped = _map_http_error(_http_error(402))
    assert "billed per resource" in str(mapped)


def test_a_429_carries_the_retry_after():
    mapped = _map_http_error(_http_error(429, {"retry-after": "9"}))
    assert isinstance(mapped, XAPIRateLimited)
    assert mapped.retry_after == 9.0


def test_other_statuses_surface_the_code():
    assert "500" in str(_map_http_error(_http_error(500)))
