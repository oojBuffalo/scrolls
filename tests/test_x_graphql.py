"""Tests for the X bookmarks GraphQL transport.

The page fetcher is injected, so nothing here touches the network. What is
under test is the part that goes wrong in practice: pagination termination,
rate-limit backoff, and the headers X rejects requests without.
"""

import json
import urllib.error
from urllib.parse import parse_qs, urlparse

import pytest

from scrolls.x_graphql import (
    BOOKMARKS_OPERATION,
    BOOKMARKS_QUERY_ID,
    XAuthExpired,
    XGraphQLError,
    XQueryIdRotated,
    XRateLimited,
    _map_http_error,
    build_headers,
    build_url,
    fetch_bookmarks,
)
from scrolls.x_session import XSession

SESSION = XSession(auth_token="AUTH", ct0="CSRF", origin="chrome")
SYNCED_AT = "2026-08-11T12:00:00+00:00"


def _page(tweet_ids, cursor=None):
    entries = [
        {
            "entryId": f"tweet-{tweet_id}",
            "sortIndex": "1799999999999999999",
            "content": {
                "itemContent": {
                    "tweet_results": {
                        "result": {
                            "__typename": "Tweet",
                            "rest_id": str(tweet_id),
                            "core": {
                                "user_results": {
                                    "result": {"core": {"screen_name": "a", "name": "A"}}
                                }
                            },
                            "legacy": {"full_text": f"post {tweet_id}"},
                        }
                    }
                }
            },
        }
        for tweet_id in tweet_ids
    ]
    if cursor:
        entries.append(
            {"entryId": "cursor-bottom-0", "content": {"value": cursor}}
        )
    return {
        "data": {
            "bookmark_timeline_v2": {
                "timeline": {
                    "instructions": [{"type": "TimelineAddEntries", "entries": entries}]
                }
            }
        }
    }


class _Fetcher:
    """Returns queued pages and records the URLs it was called with."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.urls = []

    def __call__(self, url, headers):
        self.urls.append(url)
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return page


def _cursor_of(url):
    variables = json.loads(parse_qs(urlparse(url).query)["variables"][0])
    return variables.get("cursor")


# --- request construction ------------------------------------------------


def test_headers_carry_everything_x_rejects_requests_without():
    headers = build_headers(SESSION)
    assert headers["authorization"].startswith("Bearer ")
    assert headers["x-csrf-token"] == "CSRF"
    assert headers["cookie"] == "auth_token=AUTH; ct0=CSRF"
    assert headers["x-twitter-auth-type"] == "OAuth2Session"
    assert headers["x-twitter-active-user"] == "yes"


def test_csrf_header_always_matches_the_ct0_cookie():
    """X compares the two and 403s when they disagree."""
    headers = build_headers(XSession(auth_token="A", ct0="MATCHME", origin="env"))
    assert headers["x-csrf-token"] == "MATCHME"
    assert "ct0=MATCHME" in headers["cookie"]


def test_url_pins_the_query_id_and_operation():
    path = urlparse(build_url()).path
    assert path.endswith(f"/{BOOKMARKS_QUERY_ID}/{BOOKMARKS_OPERATION}")


def test_cursor_is_absent_on_the_first_page_and_present_after():
    assert _cursor_of(build_url()) is None
    assert _cursor_of(build_url(cursor="ABC")) == "ABC"


# --- pagination ----------------------------------------------------------


def test_walks_every_page_and_concatenates_in_order():
    fetcher = _Fetcher([_page([1, 2], "C1"), _page([3, 4], "C2"), _page([5])])
    result = fetch_bookmarks(SESSION, synced_at=SYNCED_AT, get_page=fetcher, sleep=lambda _: None)
    assert [item.source_id for item in result.items] == ["1", "2", "3", "4", "5"]
    assert result.pages == 3


def test_each_page_after_the_first_sends_the_previous_cursor():
    fetcher = _Fetcher([_page([1], "C1"), _page([2])])
    fetch_bookmarks(SESSION, synced_at=SYNCED_AT, get_page=fetcher, sleep=lambda _: None)
    assert [_cursor_of(url) for url in fetcher.urls] == [None, "C1"]


def test_stops_at_the_requested_limit_without_fetching_further_pages():
    fetcher = _Fetcher([_page([1, 2], "C1"), _page([3, 4], "C2")])
    result = fetch_bookmarks(
        SESSION, synced_at=SYNCED_AT, limit=3, get_page=fetcher, sleep=lambda _: None
    )
    assert len(result.items) == 3
    assert result.pages == 2


def test_stops_when_a_page_returns_no_cursor():
    fetcher = _Fetcher([_page([1])])
    result = fetch_bookmarks(SESSION, synced_at=SYNCED_AT, get_page=fetcher, sleep=lambda _: None)
    assert len(result.items) == 1


def test_an_empty_page_ends_the_walk_even_with_a_cursor_still_offered():
    """X keeps handing back a cursor past the end of the collection."""
    fetcher = _Fetcher([_page([1], "C1"), _page([], "C2")])
    result = fetch_bookmarks(SESSION, synced_at=SYNCED_AT, get_page=fetcher, sleep=lambda _: None)
    assert len(result.items) == 1
    assert result.pages == 2


def test_a_repeated_cursor_ends_the_walk_instead_of_looping_forever():
    fetcher = _Fetcher([_page([1], "SAME"), _page([2], "SAME"), _page([3], "SAME")])
    result = fetch_bookmarks(SESSION, synced_at=SYNCED_AT, get_page=fetcher, sleep=lambda _: None)
    assert len(result.items) == 2


def test_an_empty_collection_yields_no_items_and_does_not_error():
    result = fetch_bookmarks(
        SESSION, synced_at=SYNCED_AT, get_page=_Fetcher([_page([])]), sleep=lambda _: None
    )
    assert result.items == ()


def test_pauses_between_pages_to_avoid_hammering_x():
    slept = []
    fetcher = _Fetcher([_page([1], "C1"), _page([2])])
    fetch_bookmarks(
        SESSION, synced_at=SYNCED_AT, get_page=fetcher, sleep=slept.append, delay=0.6
    )
    assert 0.6 in slept


# --- failure handling ----------------------------------------------------


def test_retries_after_a_rate_limit_and_then_succeeds():
    slept = []
    fetcher = _Fetcher([XRateLimited(retry_after=7.0), _page([1])])
    result = fetch_bookmarks(
        SESSION, synced_at=SYNCED_AT, get_page=fetcher, sleep=slept.append
    )
    assert len(result.items) == 1
    assert 7.0 in slept


def test_backs_off_exponentially_when_x_gives_no_retry_after():
    slept = []
    fetcher = _Fetcher([XRateLimited(), XRateLimited(), _page([1])])
    fetch_bookmarks(SESSION, synced_at=SYNCED_AT, get_page=fetcher, sleep=slept.append)
    assert slept[0] < slept[1]


def test_gives_up_after_the_attempt_budget_rather_than_retrying_forever():
    fetcher = _Fetcher([XRateLimited() for _ in range(10)])
    with pytest.raises(XGraphQLError, match="rate limit"):
        fetch_bookmarks(
            SESSION,
            synced_at=SYNCED_AT,
            get_page=fetcher,
            sleep=lambda _: None,
            max_attempts=3,
        )


def test_an_expired_session_propagates_instead_of_being_retried():
    fetcher = _Fetcher([XAuthExpired("session gone")])
    with pytest.raises(XAuthExpired):
        fetch_bookmarks(SESSION, synced_at=SYNCED_AT, get_page=fetcher, sleep=lambda _: None)
    assert fetcher.pages == []  # not retried: a dead session will not revive


def _http_error(code, headers=None):
    return urllib.error.HTTPError("https://x.com", code, "err", headers or {}, None)


@pytest.mark.parametrize("code", [401, 403])
def test_auth_statuses_map_to_an_actionable_message(code):
    mapped = _map_http_error(_http_error(code))
    assert isinstance(mapped, XAuthExpired)
    assert "logged in" in str(mapped)


def test_a_404_is_reported_as_a_rotated_query_id_not_an_empty_collection():
    """The failure mode that would otherwise read as "you have no bookmarks"."""
    mapped = _map_http_error(_http_error(404))
    assert isinstance(mapped, XQueryIdRotated)
    assert BOOKMARKS_QUERY_ID in str(mapped)
    assert "not an empty bookmark collection" in str(mapped)


def test_a_429_carries_the_retry_after_x_asked_for():
    mapped = _map_http_error(_http_error(429, {"retry-after": "7"}))
    assert isinstance(mapped, XRateLimited)
    assert mapped.retry_after == 7.0


def test_a_429_without_a_retry_after_leaves_the_backoff_to_us():
    assert _map_http_error(_http_error(429)).retry_after is None


def test_other_statuses_surface_the_code():
    mapped = _map_http_error(_http_error(500))
    assert type(mapped) is XGraphQLError
    assert "500" in str(mapped)


def test_items_already_collected_survive_a_later_page_failing():
    """A partial pull is still custody; it must not be discarded."""
    fetcher = _Fetcher([_page([1, 2], "C1"), XGraphQLError("boom")])
    result = fetch_bookmarks(
        SESSION,
        synced_at=SYNCED_AT,
        get_page=fetcher,
        sleep=lambda _: None,
        stop_on_error=True,
    )
    assert [item.source_id for item in result.items] == ["1", "2"]
    assert result.error is not None
