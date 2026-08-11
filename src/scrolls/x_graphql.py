"""Transport for X's internal GraphQL bookmarks endpoint (lineage:
`docs/inspiration/fieldtheory-cli-inspiration.md`).

This is the same endpoint x.com calls in the browser, reached with the
session cookies `x_session.py` extracts. It needs no developer account and
costs nothing, which is why it is the default path.

The tradeoff is honest and worth stating where the code lives: the query id
below is one of X's internal build hashes. X rotates them on deploy, and when
that happens this endpoint returns 404 and the on-ramp stops working until the
id is refreshed. That is the maintenance bill for not requiring a paid API
key, and `scrolls sync x --bookmarks` reports it as a rotated-id error rather
than as an empty collection — the failure mode that would otherwise look like
"you have no bookmarks".

Pagination ends on any of: no cursor, an empty page (X keeps offering a cursor
past the end), a repeated cursor, or the caller's limit.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from scrolls.items import ScrollItem
from scrolls.x_bookmarks import parse_bookmarks_page
from scrolls.x_session import XSession

# X's public web-client bearer. Not a secret — it ships in x.com's JavaScript
# and is identical for every visitor; the session cookies do the authenticating.
X_PUBLIC_BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

# Internal build hash — rotated by X without notice. See the module docstring.
BOOKMARKS_QUERY_ID = "Z9GWmP0kP2dajyckAaDUBw"
BOOKMARKS_OPERATION = "Bookmarks"
_ENDPOINT = "https://x.com/i/api/graphql/{query_id}/{operation}"

_CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_DEFAULT_PAGE_SIZE = 100
_DEFAULT_DELAY_SECONDS = 0.6
_DEFAULT_MAX_ATTEMPTS = 4
_BACKOFF_BASE_SECONDS = 15
_BACKOFF_CAP_SECONDS = 120
_TIMEOUT_SECONDS = 30

# The feature flags x.com sends. X rejects the call when a required flag is
# absent, and adds new ones over time; unknown extras are ignored.
GRAPHQL_FEATURES: dict[str, bool] = {
    "graphql_timeline_v2_bookmark_timeline": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}


class XGraphQLError(Exception):
    """A bookmarks request failed."""


class XAuthExpired(XGraphQLError):
    """The browser session is no longer valid."""


class XQueryIdRotated(XGraphQLError):
    """X rotated the internal query id; the pinned one no longer resolves."""


class XRateLimited(XGraphQLError):
    """X asked us to slow down.

    Attributes:
        retry_after: Seconds X asked us to wait, when it said.
    """

    def __init__(self, message: str = "rate limited", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class BookmarksSync:
    """The outcome of walking the bookmarks collection.

    Attributes:
        items: Every item collected, in the order X returned them.
        failures: Per-entry parse problems that did not abort the walk.
        pages: How many pages were fetched.
        error: The error that ended the walk early, if one did.
    """

    items: tuple[ScrollItem, ...] = ()
    failures: tuple[dict, ...] = ()
    pages: int = 0
    error: str | None = None


PageFetcher = Callable[[str, dict], dict]


def build_headers(session: XSession) -> dict[str, str]:
    """The headers X's web client sends.

    `x-csrf-token` must equal the `ct0` cookie or X answers 403.
    """
    return {
        "authorization": f"Bearer {X_PUBLIC_BEARER}",
        "x-csrf-token": session.csrf_token,
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "content-type": "application/json",
        "user-agent": _CHROME_UA,
        "cookie": session.cookie_header,
    }


def build_url(*, cursor: str | None = None, count: int = _DEFAULT_PAGE_SIZE) -> str:
    """The bookmarks URL for one page."""
    variables: dict[str, Any] = {
        "count": count,
        "includePromotedContent": False,
    }
    if cursor:
        variables["cursor"] = cursor
    query = urllib.parse.urlencode(
        {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(GRAPHQL_FEATURES, separators=(",", ":")),
        }
    )
    endpoint = _ENDPOINT.format(
        query_id=BOOKMARKS_QUERY_ID, operation=BOOKMARKS_OPERATION
    )
    return f"{endpoint}?{query}"


def fetch_bookmarks(
    session: XSession,
    *,
    synced_at: str,
    limit: int | None = None,
    page_size: int = _DEFAULT_PAGE_SIZE,
    get_page: PageFetcher | None = None,
    sleep: Callable[[float], None] = time.sleep,
    delay: float = _DEFAULT_DELAY_SECONDS,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    stop_on_error: bool = False,
) -> BookmarksSync:
    """Walk the bookmarks collection and return fetched items.

    Args:
        session: The browser session to authenticate with.
        synced_at: UTC ISO-8601 timestamp for this run.
        limit: Stop after this many items; None walks the whole collection.
        page_size: Items requested per page.
        get_page: Injected page fetcher, for tests. Defaults to a real request.
        sleep: Injected sleep, for tests.
        delay: Seconds to pause between successful pages.
        max_attempts: Attempts per page before giving up on rate limits.
        stop_on_error: Return what was collected instead of raising when a page
            fails mid-walk.

    Returns:
        A BookmarksSync. Items already collected are always kept.

    Raises:
        XGraphQLError: A page failed and `stop_on_error` is False.
    """
    fetcher = get_page or _http_get_page
    headers = build_headers(session)

    items: list[ScrollItem] = []
    failures: list[dict] = []
    seen_cursors: set[str] = set()
    cursor: str | None = None
    pages = 0
    error: str | None = None

    while True:
        url = build_url(cursor=cursor, count=page_size)
        try:
            payload = _fetch_with_backoff(
                fetcher, url, headers, sleep=sleep, max_attempts=max_attempts
            )
        except XGraphQLError as exc:
            if stop_on_error:
                error = str(exc)
                break
            raise

        pages += 1
        page = parse_bookmarks_page(payload, synced_at=synced_at)
        items.extend(page.items)
        failures.extend(page.failures)

        if limit is not None and len(items) >= limit:
            items = items[:limit]
            break
        # X keeps offering a cursor past the end of the collection, so an empty
        # page — not a missing cursor — is the real terminator.
        if not page.items or not page.next_cursor:
            break
        if page.next_cursor in seen_cursors:
            break
        seen_cursors.add(page.next_cursor)
        cursor = page.next_cursor
        sleep(delay)

    return BookmarksSync(tuple(items), tuple(failures), pages, error)


def _fetch_with_backoff(
    fetcher: PageFetcher,
    url: str,
    headers: dict,
    *,
    sleep: Callable[[float], None],
    max_attempts: int,
) -> dict:
    """Fetch one page, backing off on rate limits."""
    for attempt in range(max_attempts):
        try:
            return fetcher(url, headers)
        except XRateLimited as exc:
            if attempt == max_attempts - 1:
                raise XGraphQLError(
                    f"X rate limit not cleared after {max_attempts} attempts"
                ) from exc
            wait = exc.retry_after
            if wait is None:
                wait = min(
                    _BACKOFF_BASE_SECONDS * (2**attempt), _BACKOFF_CAP_SECONDS
                )
            sleep(wait)
    raise XGraphQLError("exhausted attempts")  # pragma: no cover - loop always returns


def _http_get_page(url: str, headers: dict) -> dict:
    """Fetch one page over HTTPS, mapping X's status codes to typed errors."""
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _map_http_error(exc) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise XGraphQLError(f"bookmarks request failed: {exc}") from exc


def _map_http_error(exc: urllib.error.HTTPError) -> XGraphQLError:
    """Turn an HTTP status into the error that tells the user what to do."""
    if exc.code == 429:
        return XRateLimited(retry_after=_retry_after(exc))
    if exc.code in (401, 403):
        return XAuthExpired(
            "the X session is no longer valid — open your browser, go to "
            "https://x.com, and make sure you are logged in"
        )
    if exc.code == 404:
        return XQueryIdRotated(
            "X no longer recognizes the pinned bookmarks query id "
            f"({BOOKMARKS_QUERY_ID}); it rotates on X deploys and needs "
            "refreshing. This is not an empty bookmark collection."
        )
    return XGraphQLError(f"bookmarks request failed with HTTP {exc.code}")


def _retry_after(exc: urllib.error.HTTPError) -> float | None:
    """Seconds to wait, from whichever header X populated."""
    headers = getattr(exc, "headers", None)
    if headers is None:
        return None
    raw = headers.get("retry-after")
    if raw:
        try:
            return float(raw)
        except ValueError:
            return None
    reset = headers.get("x-rate-limit-reset")
    if reset:
        try:
            return max(0.0, float(reset) - time.time())
        except ValueError:
            return None
    return None
