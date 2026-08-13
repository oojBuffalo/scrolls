"""X API v2 bookmarks — the official path's parser and transport (ADR 0108).

The OAuth fallback reaches a different endpoint from the cookie default, and
that endpoint returns a completely different shape: `GET /2/users/:id/bookmarks`
answers a flat `data[]` array with side-loaded `includes`, where the internal
GraphQL answers a nested timeline. So the two paths need two parsers.

What they must **not** differ on is the item. Both mint `x:<tweetId>`, both
capture the same fields, and both record `saved_at_source: "synced_at"` —
because the official endpoint exposes no bookmark timestamp either. Only
`provenance.extraction_method` distinguishes them, which is exactly the
distinction custody should keep: same artifact, different route.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from scrolls.items import ScrollItem, make_item_id
# Shared with the GraphQL parser so both paths title and collapse identically.
from scrolls.x_bookmarks import _collapse, _make_title

API_ROOT = "https://api.x.com/2"
ME_URL = f"{API_ROOT}/users/me"

_DEFAULT_PAGE_SIZE = 100  # X's maximum for this endpoint
_DEFAULT_DELAY_SECONDS = 0.6
_TIMEOUT_SECONDS = 30

# Ask for everything the cookie path already captures; a field omitted here is
# simply absent from the response, so parity is decided by this tuple.
TWEET_FIELDS = (
    "created_at",
    "note_tweet",
    "entities",
    "attachments",
    "referenced_tweets",
    "author_id",
)
USER_FIELDS = ("username", "name")
MEDIA_FIELDS = ("type", "url", "preview_image_url")
EXPANSIONS = ("author_id", "referenced_tweets.id", "attachments.media_keys")


class XAPIError(Exception):
    """An official-API bookmarks request failed."""


class XAPIAuthError(XAPIError):
    """The access token was rejected or lacks the bookmark.read scope."""


class XAPIRateLimited(XAPIError):
    """X asked us to slow down.

    Attributes:
        retry_after: Seconds X asked us to wait, when it said.
    """

    def __init__(self, message: str = "rate limited", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class BookmarksPage:
    """One parsed page of the official bookmarks response.

    Attributes:
        items: Fetched `x` items, in the order X returned them.
        next_token: Pagination token for the following page, or None.
        failures: Per-entry problems that did not abort the page.
    """

    items: tuple[ScrollItem, ...] = ()
    next_token: str | None = None
    failures: tuple[dict, ...] = ()


def parse_bookmarks_page(payload: dict, *, synced_at: str) -> BookmarksPage:
    """Parse one API v2 bookmarks response into items and a page token.

    Args:
        payload: The decoded JSON body of a `/2/users/:id/bookmarks` call.
        synced_at: UTC ISO-8601 timestamp for this run, used as the `saved_at`
            fallback and as `provenance.fetched_at`.

    Returns:
        A BookmarksPage. A malformed entry becomes a failure rather than
        aborting the page, matching the GraphQL parser and `scrolls fetch`.
    """
    payload = payload or {}
    includes = payload.get("includes") or {}
    users = {user["id"]: user for user in includes.get("users") or () if user.get("id")}
    tweets = {
        tweet["id"]: tweet for tweet in includes.get("tweets") or () if tweet.get("id")
    }
    media = {
        entry["media_key"]: entry
        for entry in includes.get("media") or ()
        if entry.get("media_key")
    }

    items: list[ScrollItem] = []
    failures: list[dict] = []
    for record in payload.get("data") or ():
        if not isinstance(record, dict):
            continue
        try:
            items.append(_to_item(record, users, tweets, media, synced_at))
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            failures.append({"entry_id": str(record.get("id") or ""), "error": str(exc)})

    next_token = (payload.get("meta") or {}).get("next_token")
    return BookmarksPage(
        tuple(items), next_token if isinstance(next_token, str) else None, tuple(failures)
    )


def _to_item(
    record: dict, users: dict, tweets: dict, media: dict, synced_at: str
) -> ScrollItem:
    """Build one fetched `x` item from an API v2 tweet record.

    Raises:
        ValueError: The record carries no usable tweet id.
    """
    tweet_id = str(record.get("id") or "")
    if not tweet_id:
        raise ValueError("record has no tweet id")

    author = users.get(record.get("author_id")) or {}
    handle = author.get("username") or ""
    name = author.get("name") or ""
    url = (
        f"https://x.com/{handle}/status/{tweet_id}"
        if handle
        else f"https://x.com/i/status/{tweet_id}"
    )

    extracted = _body_text(record)
    quoted_handle, quoted_text = _quoted(record, users, tweets)
    if quoted_text:
        extracted += f"\n\nQuoting @{quoted_handle or 'unknown'}: {quoted_text}"

    provenance: dict[str, Any] = {
        "adapter": "x-bookmarks",
        "fetched_at": synced_at,
        "extraction_method": "x:api-v2",
        # The official endpoint exposes no bookmark timestamp either.
        "saved_at_source": "synced_at",
    }

    return ScrollItem(
        id=make_item_id("x", tweet_id, url),
        source="x",
        source_id=tweet_id,
        url=url,
        saved_at=synced_at,
        title=_make_title(handle, _collapse(extracted), tweet_id),
        author=f"{name} (@{handle})" if name and handle else (name or handle or None),
        published_at=_parse_posted_at(record.get("created_at")),
        raw_text=json.dumps(record, ensure_ascii=False, sort_keys=True),
        extracted_text=extracted or None,
        links=_links(record),
        media=_media(record, media),
        content_hash="sha256:" + hashlib.sha256(extracted.encode("utf-8")).hexdigest(),
        provenance=provenance,
        stage="fetched",
    )


def _body_text(record: dict) -> str:
    """Long-form note text when present, else the truncated `text`."""
    note = (record.get("note_tweet") or {}).get("text")
    return note or record.get("text") or ""


def _quoted(record: dict, users: dict, tweets: dict) -> tuple[str, str]:
    """Handle and text of the quoted post, side-loaded from `includes`."""
    for reference in record.get("referenced_tweets") or ():
        if not isinstance(reference, dict) or reference.get("type") != "quoted":
            continue
        quoted = tweets.get(reference.get("id"))
        if not quoted:
            continue
        author = users.get(quoted.get("author_id")) or {}
        return author.get("username") or "", _body_text(quoted)
    return "", ""


def _links(record: dict) -> tuple:
    urls = (record.get("entities") or {}).get("urls") or ()
    return tuple(
        url["expanded_url"]
        for url in urls
        if isinstance(url, dict) and url.get("expanded_url")
    )


def _media(record: dict, media: dict) -> tuple:
    """Media references, resolved from media keys through `includes.media`."""
    found = []
    for key in (record.get("attachments") or {}).get("media_keys") or ():
        entry = media.get(key)
        if not entry:
            continue
        # A video carries no `url`; its still frame is the addressable artifact.
        location = entry.get("url") or entry.get("preview_image_url")
        if location:
            found.append({"type": entry.get("type") or "media", "url": location})
    return tuple(found)


def _parse_posted_at(value: str | None) -> str | None:
    """Parse X's ISO-8601 `created_at` ('2026-06-01T15:34:00.000Z')."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


# --- transport -----------------------------------------------------------


@dataclass
class BookmarksSync:
    """The outcome of walking the collection over the official API.

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


Getter = Callable[[str, dict], dict]


def build_headers(access_token: str) -> dict[str, str]:
    """The headers the official API expects."""
    return {
        "authorization": f"Bearer {access_token}",
        "content-type": "application/json",
    }


def build_url(user_id: str, *, token: str | None = None, count: int = _DEFAULT_PAGE_SIZE) -> str:
    """The bookmarks URL for one page."""
    query = {
        "max_results": count,
        "tweet.fields": ",".join(TWEET_FIELDS),
        "user.fields": ",".join(USER_FIELDS),
        "media.fields": ",".join(MEDIA_FIELDS),
        "expansions": ",".join(EXPANSIONS),
    }
    if token:
        query["pagination_token"] = token
    return f"{API_ROOT}/users/{user_id}/bookmarks?{urllib.parse.urlencode(query)}"


def resolve_user_id(access_token: str, *, get: Getter | None = None) -> str:
    """Look up the authenticated user's numeric id.

    The bookmarks endpoint is addressed by user id, which the OAuth grant
    does not include, so this is one unavoidable extra call per run.

    Raises:
        XAPIError: X returned no user id.
    """
    payload = (get or _http_get)(ME_URL, build_headers(access_token))
    user_id = ((payload or {}).get("data") or {}).get("id")
    if not user_id:
        raise XAPIError(f"X returned no user id for the stored grant: {payload!r}")
    return str(user_id)


def fetch_bookmarks(
    access_token: str,
    *,
    synced_at: str,
    user_id: str | None = None,
    limit: int | None = None,
    page_size: int = _DEFAULT_PAGE_SIZE,
    get: Getter | None = None,
    sleep: Callable[[float], None] = time.sleep,
    delay: float = _DEFAULT_DELAY_SECONDS,
    stop_on_error: bool = False,
) -> BookmarksSync:
    """Walk the bookmarks collection over the official API.

    Args:
        access_token: A live OAuth access token.
        synced_at: UTC ISO-8601 timestamp for this run.
        user_id: The authenticated user's id; looked up when omitted.
        limit: Stop after this many items; None walks the whole collection.
        page_size: Items requested per page.
        get: Injected fetcher, for tests.
        sleep: Injected sleep, for tests.
        delay: Seconds to pause between pages.
        stop_on_error: Return what was collected instead of raising.

    Returns:
        A BookmarksSync. Items already collected are always kept.

    Raises:
        XAPIError: A request failed and `stop_on_error` is False.
    """
    fetcher = get or _http_get
    headers = build_headers(access_token)

    items: list[ScrollItem] = []
    failures: list[dict] = []
    seen_tokens: set[str] = set()
    token: str | None = None
    pages = 0
    error: str | None = None

    try:
        resolved = user_id or resolve_user_id(access_token, get=fetcher)
    except XAPIError as exc:
        if not stop_on_error:
            raise
        return BookmarksSync(error=str(exc))

    while True:
        try:
            payload = fetcher(build_url(resolved, token=token, count=page_size), headers)
        except XAPIError as exc:
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
        # Same terminator as the GraphQL walk: an empty page ends it, whatever
        # token X still offers.
        if not page.items or not page.next_token:
            break
        if page.next_token in seen_tokens:
            break
        seen_tokens.add(page.next_token)
        token = page.next_token
        sleep(delay)

    return BookmarksSync(tuple(items), tuple(failures), pages, error)


def _http_get(url: str, headers: dict) -> dict:
    """GET one page, mapping X's status codes to typed errors."""
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _map_http_error(exc) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise XAPIError(f"bookmarks request failed: {exc}") from exc


def _map_http_error(exc: urllib.error.HTTPError) -> XAPIError:
    """Turn an HTTP status into the error that tells the user what to do."""
    if exc.code == 429:
        return XAPIRateLimited(retry_after=_retry_after(exc))
    if exc.code in (401, 403):
        return XAPIAuthError(
            "X rejected the stored credentials — re-authorize with "
            "`scrolls x login`, and check the app has the bookmark.read scope"
        )
    if exc.code == 402:
        return XAPIError(
            "X declined the request for billing reasons — bookmark reads are "
            "billed per resource, so check the balance in the Developer Console"
        )
    return XAPIError(f"bookmarks request failed with HTTP {exc.code}")


def _retry_after(exc: urllib.error.HTTPError) -> float | None:
    """Seconds to wait, from whichever header X populated."""
    headers = getattr(exc, "headers", None)
    if headers is None:
        return None
    for key, transform in (
        ("retry-after", float),
        ("x-rate-limit-reset", lambda raw: max(0.0, float(raw) - time.time())),
    ):
        raw = headers.get(key)
        if raw:
            try:
                return transform(raw)
            except ValueError:
                return None
    return None
