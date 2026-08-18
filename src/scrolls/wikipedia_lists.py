"""Wikipedia reading lists — the saved collection behind a logged-in account.

`scrolls sync wikipedia --reading-lists` pulls what the user tapped "Save" on
in the Wikipedia app or while signed in on the web: articles synced to the
account and filed into named lists. Not the watchlist, which is "notify me
when this changes" — a different intent, deliberately out of scope.

**A collection is an index, not a capture.** This is the honest difference
from the X bookmarks pull, which gets the whole post in the same response and
so enters items at stage `fetched`. MediaWiki's reading-list entry carries
only `project`, `title` and the time you saved it — no article text at all.
So items enter at stage `detected`, exactly as the Pocket and browser-bookmark
importers do, and the existing Wikipedia fetch adapter (ADR 0002) captures
them on the next `scrolls fetch`. Claiming stage `fetched` for a row that
holds no prose would be the fabrication custody is supposed to prevent.

Identity is minted by building the article URL and handing it to the same
`detect_source` that `scrolls add` uses, rather than by re-deriving the id
here. A reading-list pull and `scrolls add` of the same article therefore
converge on one item by construction, not by two rules that agree today.

Auth is CentralAuth's, not the local wiki's, which is worth knowing because
it is not what you would guess: `centralauth_User` **and**
`centralauth_Session` are what the API accepts. A valid per-wiki
`enwikiSession` alone answers `notloggedin` — reading lists are a global
feature, so the global session is the one that counts. Verified against live
en.wikipedia.org on 2026-08-18.

The two API modules are flagged `internal` by MediaWiki (`action=paraminfo`
says so), meaning they carry no stability promise even though they are
documented at Extension:ReadingLists. That is this on-ramp's equivalent of
X's rotating query id: it works, it is the same call the Wikipedia app makes,
and if it disappears the failure says the extension is gone rather than
reporting an empty collection.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable
from urllib.parse import quote, unquote, urlencode, urlparse

from scrolls.browser_cookies import BrowserCookies, CookieSpec, load_cookies
from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem, make_item_id
from scrolls.sources import http
from scrolls.sources.detect import detect_source
from scrolls.sources.urls import normalize_url

USER_ENV = "SCROLLS_WIKIPEDIA_USER"
SESSION_ENV = "SCROLLS_WIKIPEDIA_SESSION"

# CentralAuth cookies live on the registrable domain, so one pair covers every
# language edition. Chromium writes the leading dot; Firefox does not.
WIKIPEDIA_COOKIES = CookieSpec(
    service="Wikipedia",
    hosts=(".wikipedia.org", "wikipedia.org", ".wikimedia.org", "wikimedia.org"),
    required=("centralauth_User", "centralauth_Session"),
    login_url="https://en.wikipedia.org",
    env_vars=(("centralauth_User", USER_ENV), ("centralauth_Session", SESSION_ENV)),
)

# Reading lists are global, but the API is reached through any one wiki. The
# English edition is the safe host for an account of unknown home wiki.
API_ENDPOINT = "https://en.wikipedia.org/w/api.php"

_LISTS_PAGE_SIZE = "max"
_ENTRIES_PAGE_SIZE = "max"
_MAX_PAGES = 500

GetJson = Callable[[str], dict[str, Any]]


class WikipediaListsError(Exception):
    """A reading-lists request failed."""


class WikipediaAuthExpired(WikipediaListsError):
    """The browser session no longer authenticates the account."""


@dataclass(frozen=True)
class WikipediaSession:
    """The CentralAuth cookies the reading-lists API authenticates with.

    Attributes:
        username: The account name, from the `centralauth_User` cookie. Public
            information — it is the signature on every edit — so it is shown
            rather than redacted, and reporting it is how a user confirms the
            pull ran as the right account.
        session: The `centralauth_Session` cookie. This one is the secret.
        origin: Where the session came from ('brave', 'firefox', 'env'),
            recorded so a capture's path is auditable.
    """

    username: str
    session: str
    origin: str

    @property
    def cookie_header(self) -> str:
        """The Cookie header MediaWiki expects."""
        return f"centralauth_User={self.username}; centralauth_Session={self.session}"

    @property
    def display_name(self) -> str:
        """The account name as a human reads it, underscores and escapes undone."""
        return unquote(self.username).replace("_", " ")

    def __repr__(self) -> str:
        """Redacted: the session cookie must not leak into a traceback."""
        return (
            f"WikipediaSession(username={self.username!r}, "
            f"origin={self.origin!r}, session=<redacted>)"
        )


def load_wikipedia_session(
    browser: str = "auto", *, profile: str | None = None
) -> WikipediaSession:
    """Read a Wikipedia session out of the user's browser.

    Args:
        browser: 'auto' tries the environment, then every installed browser.
        profile: Pin one browser profile directory by name.

    Returns:
        The resolved session.

    Raises:
        BrowserCookieError: No session could be resolved by that path.
    """
    return session_from_cookies(
        load_cookies(WIKIPEDIA_COOKIES, browser, profile=profile)
    )


def session_from_cookies(cookies: BrowserCookies) -> WikipediaSession:
    """Turn generic browser cookies into the Wikipedia-shaped session."""
    return WikipediaSession(
        username=cookies.values["centralauth_User"],
        session=cookies.values["centralauth_Session"],
        origin=cookies.origin,
    )


@dataclass(frozen=True)
class ReadingListSync:
    """The outcome of walking the reading-list collection.

    Attributes:
        items: Every article collected, in the order MediaWiki returned them.
        lists: List id to list name, for every list the account holds.
        failures: Entries that could not become items, with the reason.
        pages: How many entry pages were fetched.
        error: The error that ended the walk early, if one did.
    """

    items: tuple[ScrollItem, ...] = ()
    lists: dict[int, str] = None
    failures: tuple[dict, ...] = ()
    pages: int = 0
    error: str | None = None


def entry_url(project: str, title: str) -> str:
    """The article URL for one reading-list entry.

    MediaWiki hands back a display title with spaces; the canonical URL uses
    underscores. Everything else is percent-encoded, including the slash in a
    title like `24/7 service`, which would otherwise read as a path segment.

    Args:
        project: The entry's project, e.g. `https://en.wikipedia.org`.
        title: The entry's display title.

    Returns:
        The article URL.
    """
    return f"{project.rstrip('/')}/wiki/{quote(title.replace(' ', '_'), safe='')}"


def _api_url(**params: str) -> str:
    """One MediaWiki action-API URL."""
    query = urlencode({"action": "query", "format": "json", "formatversion": "2", **params})
    return f"{API_ENDPOINT}?{query}"


def _check(payload: dict) -> dict:
    """Raise on an API error envelope; otherwise return the payload.

    MediaWiki answers 200 with an `error` object rather than an HTTP status,
    so a caller that only checks the status silently treats a rejection as an
    empty collection — the one answer a custody tool must never give.
    """
    error = payload.get("error")
    if not error:
        return payload
    code = error.get("code", "")
    info = error.get("info", "")
    if code in ("notloggedin", "assertuserfailed", "mustbeloggedin"):
        raise WikipediaAuthExpired(
            "the Wikipedia session is no longer valid — open your browser, go "
            "to https://en.wikipedia.org, and make sure you are logged in"
        )
    if code in ("unknown_meta", "unknown_list", "badvalue", "unknown_action"):
        raise WikipediaListsError(
            "this wiki does not offer the ReadingLists API "
            f"(MediaWiki said {code!r}: {info}). The extension may have been "
            "removed or disabled; this is not an empty reading list."
        )
    raise WikipediaListsError(f"reading-lists request failed ({code}): {info}")


def fetch_lists(
    session: WikipediaSession, *, get_json: GetJson
) -> tuple[dict[int, str], set[int]]:
    """Every reading list the account holds.

    Args:
        session: The authenticated session.
        get_json: Injected JSON fetcher.

    Returns:
        A (list id to name, ids of default lists) pair. The default list is
        Wikipedia's unnamed catch-all — where an article goes when the user
        filed it nowhere — so it is flagged rather than treated as a name.

    Raises:
        WikipediaListsError: The API rejected the request.
    """
    lists: dict[int, str] = {}
    defaults: set[int] = set()
    params = {"meta": "readinglists", "rllimit": _LISTS_PAGE_SIZE}
    seen: set[str] = set()
    for _ in range(_MAX_PAGES):
        payload = _check(get_json(_api_url(**params)))
        for entry in payload.get("query", {}).get("readinglists") or ():
            lists[entry["id"]] = entry.get("name") or ""
            if entry.get("default"):
                defaults.add(entry["id"])
        cursor = (payload.get("continue") or {}).get("rlcontinue")
        if not cursor or cursor in seen:
            break
        seen.add(cursor)
        params = {**params, "rlcontinue": cursor}
    return lists, defaults


def collect_reading_lists(
    session: WikipediaSession,
    *,
    imported_at: str,
    get_json: GetJson | None = None,
    limit: int | None = None,
    stop_on_error: bool = False,
) -> ReadingListSync:
    """Walk every reading list and return detected items.

    Args:
        session: The authenticated session.
        imported_at: UTC ISO-8601 fallback for an entry with no save time.
        get_json: Injected JSON fetcher; defaults to a real request.
        limit: Stop after this many articles; None walks the whole collection.
        stop_on_error: Return what was collected instead of raising when a
            page fails mid-walk.

    Returns:
        A ReadingListSync. Items already collected are always kept.

    Raises:
        WikipediaListsError: A request failed and `stop_on_error` is False.
    """
    fetch = get_json or _session_fetcher(session)
    all_lists, defaults = fetch_lists(session, get_json=fetch)
    if not all_lists:
        return ReadingListSync(lists={}, pages=0)

    # A named list is the user's own curation and becomes a tag; the default
    # list is the absence of a choice, so it contributes none.
    tags_by_list = {
        list_id: ("" if list_id in defaults else name)
        for list_id, name in all_lists.items()
    }

    ids = "|".join(str(list_id) for list_id in sorted(all_lists))
    params = {
        "list": "readinglistentries",
        "rlelists": ids,
        "rlelimit": _ENTRIES_PAGE_SIZE,
    }

    # Keyed by item id, because Wikipedia keeps an article in the default list
    # *and* in whatever list it was filed into, so one article legitimately
    # arrives as several entries. Collapsing here rather than at the insert is
    # what keeps every list's membership: `INSERT OR IGNORE` would keep
    # whichever copy landed first and silently drop the other's tag.
    by_id: dict[str, ScrollItem] = {}
    failures: list[dict] = []
    seen_cursors: set[str] = set()
    pages = 0
    error: str | None = None

    for _ in range(_MAX_PAGES):
        try:
            payload = _check(fetch(_api_url(**params)))
        except WikipediaListsError as exc:
            if stop_on_error:
                error = str(exc)
                break
            raise

        pages += 1
        for entry in payload.get("query", {}).get("readinglistentries") or ():
            item = _to_item(entry, tags_by_list, imported_at, failures)
            if item is None:
                continue
            held = by_id.get(item.id)
            by_id[item.id] = item if held is None else _merge(held, item)

        if limit is not None and len(by_id) >= limit:
            break
        cursor = (payload.get("continue") or {}).get("rlecontinue")
        if not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
        params = {**params, "rlecontinue": cursor}

    items = list(by_id.values())
    return ReadingListSync(
        items=tuple(items if limit is None else items[:limit]),
        lists=all_lists,
        failures=tuple(failures),
        pages=pages,
        error=error,
    )


def _merge(held: ScrollItem, found: ScrollItem) -> ScrollItem:
    """Fold a second membership of the same article into the one held.

    Tags are unioned in first-seen order and the earliest save wins, the rule
    the Pocket and browser-bookmark importers already use for a URL saved
    twice (ADR 0030).
    """
    tags = held.tags + tuple(tag for tag in found.tags if tag not in held.tags)
    return replace(held, tags=tags, saved_at=min(held.saved_at, found.saved_at))


def _to_item(
    entry: dict, tags_by_list: dict[int, str], imported_at: str, failures: list[dict]
) -> ScrollItem | None:
    """Turn one reading-list entry into a detected item, or record why not."""
    project = (entry.get("project") or "").strip()
    title = (entry.get("title") or "").strip()
    if not project or not title:
        failures.append({"entry": entry.get("id"), "reason": "entry has no project or title"})
        return None

    host = urlparse(project).netloc
    if not (host == "wikipedia.org" or host.endswith(".wikipedia.org")):
        # Reading lists span all of Wikimedia — Commons, Wiktionary, Wikidata.
        # Only Wikipedia has an adapter here, and minting an item for a project
        # this library cannot fetch would be a promise it can't keep.
        failures.append(
            {
                "entry": entry.get("id"),
                "project": project,
                "title": title,
                "reason": "not a Wikipedia project",
            }
        )
        return None

    url = normalize_url(entry_url(project, title))
    detected = detect_source(url)
    if detected.source != "wikipedia" or not detected.source_id:
        failures.append(
            {"entry": entry.get("id"), "title": title, "reason": "unrecognized article URL"}
        )
        return None

    name = tags_by_list.get(entry.get("listId"), "")
    return ScrollItem(
        id=make_item_id(detected.source, detected.source_id, url),
        source=detected.source,
        source_id=detected.source_id,
        url=url,
        # the list's title seeds the item; `scrolls fetch` replaces it with
        # the page's own title (feed-sync semantics, ADR 0021)
        title=title,
        # `created` is when this article entered the user's life. The article's
        # own dates are Wikipedia's, and belong to `fetch`, never here.
        saved_at=to_utc_iso(entry.get("created")) or imported_at,
        tags=(name,) if name else (),
    )


def _session_fetcher(session: WikipediaSession) -> GetJson:
    """A JSON fetcher carrying the session cookies and a descriptive agent."""

    def get_json(url: str) -> dict[str, Any]:
        try:
            return http.get_json(url, {"Cookie": session.cookie_header})
        except (OSError, ValueError) as exc:
            raise WikipediaListsError(f"reading-lists request failed: {exc}") from exc

    return get_json
