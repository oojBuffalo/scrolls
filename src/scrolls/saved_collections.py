"""The collection declaration: which sources offer a saved collection (ADR 0113).

The fourth on-ramp. Not a URL (`add`), not a file someone exported
(`import`), not a feed delta (`follow`/`sync`) — the user's own saved
collection, copied out of the service they saved it in. Every collection a
source can enumerate is declared here once, with the custody facts a reader
needs before running it: what shape the pull has, what stage its items enter
at, where `saved_at` comes from, and which credential routes reach it.

A source that offers no collection is answered with an empty tuple. That is
the honest, first-class answer, not an error: most sources are things you
point at, not places you keep things.

Each declared `pull` turns a start-up failure (no session, expired session,
missing grant, rotated query id) into `CollectionUnavailable`, so the CLI can
fail the whole run in one envelope. A failure *mid-walk* rides on
`CollectionPull.error` instead, so whatever was already collected is kept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from scrolls.items import ScrollItem
from scrolls.paths import get_paths
from scrolls.wikipedia_lists import (
    WikipediaListsError,
    collect_reading_lists,
    load_wikipedia_session,
)
from scrolls.x_api import XAPIError
from scrolls.x_api import fetch_bookmarks as api_fetch_bookmarks
from scrolls.x_graphql import XGraphQLError, fetch_bookmarks
from scrolls.x_oauth import XOAuthError, client_id_from_env, resolve_access_token
from scrolls.x_session import XSessionError, load_session


class CollectionUnavailable(Exception):
    """The pull could not start, so nothing was collected."""


class UnknownCollection(Exception):
    """The source offers no collection by that name, or none at all."""


@dataclass(frozen=True)
class PullOptions:
    """How to reach the collection, as the user asked on the command line.

    Attributes:
        limit: Stop after this many saved items; None walks everything.
        browser: Where to read the logged-in session from.
        profile: One browser profile directory to pin, or None for all.
        route: Which credential route to use (`browser` or `oauth`).
    """

    limit: int | None = None
    browser: str = "auto"
    profile: str | None = None
    route: str = "browser"


@dataclass(frozen=True)
class CollectionPull:
    """The outcome of one pull, in the shape every collection shares.

    Attributes:
        items: Every item collected, in the order the service returned them.
        failures: Per-entry problems that did not abort the walk.
        pages: How many pages were fetched.
        session: Where the credential came from (a browser, `env`, `oauth`).
        error: The error that ended the walk early, if one did.
        extra: Source-specific facts for the report (account, list names).
    """

    items: tuple[ScrollItem, ...] = ()
    failures: tuple[dict, ...] = ()
    pages: int = 0
    session: str = ""
    error: str | None = None
    extra: dict = field(default_factory=dict)


Pull = Callable[[PullOptions, str], CollectionPull]


@dataclass(frozen=True)
class SavedCollection:
    """One collection a source can enumerate.

    Attributes:
        source: The source name, as `detect_source` mints it.
        name: The collection's name on the command line.
        summary: One line saying what the collection is.
        shape: `capture-at-pull` when the enumerating response carries the
            artifact itself, `enumerate-only` when it only names it.
        entry_stage: The stage pulled items enter at — `fetched` for
            capture-at-pull, `detected` for enumerate-only.
        saved_at: `service` when the service says when you saved it,
            `sync-time` when it does not and the pull time stands in.
        routes: Credential routes, the browser session always first.
        adr: The ADR that records this collection's decisions.
        pull: Walks the collection; given options and the pull timestamp.
    """

    source: str
    name: str
    summary: str
    shape: str
    entry_stage: str
    saved_at: str
    routes: tuple[str, ...]
    adr: str
    pull: Pull = field(repr=False, compare=False)

    @property
    def command(self) -> str:
        """The command that pulls this collection."""
        return f"scrolls sync {self.source} --collection {self.name}"

    def describe(self) -> dict:
        """The JSON shape `scrolls sync --list-collections` prints."""
        return {
            "source": self.source,
            "collection": self.name,
            "summary": self.summary,
            "shape": self.shape,
            "entry_stage": self.entry_stage,
            "saved_at": self.saved_at,
            "routes": list(self.routes),
            "adr": self.adr,
            "command": self.command,
        }


def _pull_x_bookmarks(options: PullOptions, pulled_at: str) -> CollectionPull:
    """Walk X bookmarks over the browser session or the stored OAuth grant.

    Both routes reach identical items (ADR 0108); only the session origin
    and each item's `provenance.extraction_method` say which was taken.
    """
    try:
        if options.route == "oauth":
            client_id = client_id_from_env()
            token = resolve_access_token(
                get_paths().credentials_path, client_id=client_id
            )
            origin = "oauth"
            result = api_fetch_bookmarks(
                token, synced_at=pulled_at, limit=options.limit, stop_on_error=True
            )
        else:
            session = load_session(options.browser, profile=options.profile)
            origin = session.origin
            result = fetch_bookmarks(
                session, synced_at=pulled_at, limit=options.limit, stop_on_error=True
            )
    except (XSessionError, XGraphQLError, XOAuthError, XAPIError) as exc:
        raise CollectionUnavailable(str(exc)) from exc
    return CollectionPull(
        items=tuple(result.items),
        failures=tuple(result.failures),
        pages=result.pages,
        session=origin,
        error=result.error,
    )


def _pull_wikipedia_reading_lists(
    options: PullOptions, pulled_at: str
) -> CollectionPull:
    """Walk every Wikipedia reading list over the CentralAuth session."""
    try:
        session = load_wikipedia_session(options.browser, profile=options.profile)
        result = collect_reading_lists(
            session, imported_at=pulled_at, limit=options.limit, stop_on_error=True
        )
    except (XSessionError, WikipediaListsError) as exc:
        raise CollectionUnavailable(str(exc)) from exc
    return CollectionPull(
        items=tuple(result.items),
        failures=tuple(result.failures),
        pages=result.pages,
        session=session.origin,
        error=result.error,
        extra={
            "account": session.display_name,
            "lists": sorted((result.lists or {}).values()),
        },
    )


COLLECTIONS: tuple[SavedCollection, ...] = (
    SavedCollection(
        source="x",
        name="bookmarks",
        summary="Posts you bookmarked on X",
        shape="capture-at-pull",
        entry_stage="fetched",
        saved_at="sync-time",
        routes=("browser", "oauth"),
        adr="0108",
        pull=_pull_x_bookmarks,
    ),
    SavedCollection(
        source="wikipedia",
        name="reading-lists",
        summary="Articles you saved to your Wikipedia reading lists",
        shape="enumerate-only",
        entry_stage="detected",
        saved_at="service",
        routes=("browser",),
        adr="0109",
        pull=_pull_wikipedia_reading_lists,
    ),
)


def collections_for(source: str) -> tuple[SavedCollection, ...]:
    """Every collection the source declares; empty when it offers none."""
    return tuple(c for c in COLLECTIONS if c.source == source)


def resolve_collection(source: str, name: str) -> SavedCollection:
    """Find one declared collection.

    Raises:
        UnknownCollection: The source offers no collection by that name, or
            no collection at all. The message names what does exist.
    """
    offered = collections_for(source)
    for collection in offered:
        if collection.name == name:
            return collection
    if offered:
        names = ", ".join(c.name for c in offered)
        raise UnknownCollection(
            f"{source} has no collection named {name!r}; it offers: {names}"
        )
    everywhere = "; ".join(f"`{c.command}`" for c in COLLECTIONS)
    raise UnknownCollection(
        f"{source} offers no saved collection Scrolls can pull. "
        f"Declared collections: {everywhere}"
    )


def now_iso() -> str:
    """The pull timestamp every item in one run shares."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
