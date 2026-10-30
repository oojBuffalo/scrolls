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

from scrolls.custody import (
    SAVED_UPSTREAM_STATUS,
    UNSAVED_UPSTREAM_STATUS,
    CustodyEvent,
)
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
        seen: The item id of every save the walk passed, readable or not.
        unidentified: Entries the walk could not name.
        complete: The walk ended on the service's own end signal, unlimited
            and unbroken, so `seen` is the whole collection (ADR 0118).
        account: A stable name for the account whose collection was walked
            (X's numeric user id, the Wikipedia account name), or None when
            the route cannot say. Membership is per account, so a walk with
            no account compares nothing.
    """

    items: tuple[ScrollItem, ...] = ()
    failures: tuple[dict, ...] = ()
    pages: int = 0
    session: str = ""
    error: str | None = None
    extra: dict = field(default_factory=dict)
    seen: tuple[str, ...] = ()
    unidentified: int = 0
    complete: bool = False
    account: str | None = None


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

    def key(self, account: str) -> str:
        """One account's copy of this collection on the ledger's membership axis.

        Args:
            account: The account the walk ran as.

        Returns:
            `<source>/<name>@<account>`, e.g. `x/bookmarks@12345`.
        """
        return f"{self.source}/{self.name}@{account}"

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
            account = result.account
        else:
            session = load_session(options.browser, profile=options.profile)
            origin = session.origin
            result = fetch_bookmarks(
                session, synced_at=pulled_at, limit=options.limit, stop_on_error=True
            )
            # Both routes name the same numeric user id, so one account's
            # membership is shared across them.
            account = session.user_id
    except (XSessionError, XGraphQLError, XOAuthError, XAPIError) as exc:
        raise CollectionUnavailable(str(exc)) from exc
    return CollectionPull(
        items=tuple(result.items),
        failures=tuple(result.failures),
        pages=result.pages,
        session=origin,
        error=result.error,
        seen=result.seen,
        unidentified=result.unidentified,
        complete=result.complete,
        account=account,
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
        seen=result.seen,
        unidentified=result.unidentified,
        complete=result.complete,
        account=session.display_name,
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


@dataclass(frozen=True)
class UpstreamComparison:
    """What one pull learned about the collection's membership (ADR 0118).

    Attributes:
        compared: Whether the walk was complete enough to compare at all.
        reason: Why it was not, or None when it was.
        events: The membership events to append to the ledger.
        saved: Items recorded as members for the first time.
        unsaved: Ids newly found removed upstream, sorted.
        resaved: Ids that returned after a removal, sorted.
        still_unsaved: Items already recorded as removed and still absent.
    """

    compared: bool
    reason: str | None = None
    events: tuple[CustodyEvent, ...] = ()
    saved: int = 0
    unsaved: tuple[str, ...] = ()
    resaved: tuple[str, ...] = ()
    still_unsaved: int = 0

    def payload(self) -> dict:
        """The `upstream` block the sync report carries."""
        return {
            "compared": self.compared,
            "reason": self.reason,
            "saved": self.saved,
            "unsaved": list(self.unsaved),
            "resaved": list(self.resaved),
            "still_unsaved": self.still_unsaved,
        }


def compare_upstream(
    collection: SavedCollection,
    pull: CollectionPull,
    *,
    limited: bool,
    held: list[ScrollItem],
    latest: dict[str, CustodyEvent],
    now: str,
) -> UpstreamComparison:
    """Compare a complete walk against what earlier walks found (ADR 0118).

    Membership is per account (`collection.key(pull.account)`). A member is an
    item the ledger last recorded as `saved_upstream` in that account's
    collection, so the first complete walk only records the baseline. A held
    member the walk did not see was removed upstream; a held item the walk saw
    is a member, and a first sighting or a return after a removal is recorded
    as one. Report-only: the events never touch an item, and an item no longer
    held gets none.

    Only a walk that saw the whole collection, as a known account, may say
    what is missing, so a limited walk, one that ended early, one with entries
    it could not name, or one whose account is unknown compares nothing.

    Args:
        collection: The collection walked.
        pull: The walk's outcome.
        limited: Whether the user bounded the walk with `--limit`.
        held: Every item the library holds after this pull's inserts.
        latest: Each item's latest membership event in this account's
            collection (empty when the account is unknown).
        now: The pull timestamp, stamped on every event.

    Returns:
        The comparison, with the events still to be recorded.
    """
    if limited:
        return UpstreamComparison(
            False, "a --limit walk sees only part of the collection"
        )
    if pull.error:
        return UpstreamComparison(False, f"the walk ended early: {pull.error}")
    if not pull.complete:
        return UpstreamComparison(
            False, "the walk stopped before the service said it was done"
        )
    if pull.unidentified:
        return UpstreamComparison(
            False, f"{pull.unidentified} collection entries could not be identified"
        )
    if not pull.account:
        # Membership is per account: another profile's collection is not this
        # one's, and a comparison across them would fabricate removals.
        return UpstreamComparison(
            False, "the account behind the walk could not be identified"
        )

    key = collection.key(pull.account)
    by_id = {item.id: item for item in held if item.source == collection.source}
    seen = set(pull.seen)

    def event(item_id: str, status: str) -> CustodyEvent:
        return CustodyEvent(item_id, now, status, by_id[item_id].content_hash, None, key)

    events: list[CustodyEvent] = []
    saved = 0
    resaved: list[str] = []
    unsaved: list[str] = []
    still_unsaved = 0
    for item_id in sorted(by_id):
        last = latest.get(item_id)
        if item_id in seen:
            if last is None:
                saved += 1
                events.append(event(item_id, SAVED_UPSTREAM_STATUS))
            elif last.status == UNSAVED_UPSTREAM_STATUS:
                resaved.append(item_id)
                events.append(event(item_id, SAVED_UPSTREAM_STATUS))
            continue
        if last is None:
            continue  # never seen in this account's collection: not a member
        if last.status == UNSAVED_UPSTREAM_STATUS:
            still_unsaved += 1
            continue
        unsaved.append(item_id)
        events.append(event(item_id, UNSAVED_UPSTREAM_STATUS))

    return UpstreamComparison(
        True, None, tuple(events), saved, tuple(unsaved), tuple(resaved), still_unsaved
    )
