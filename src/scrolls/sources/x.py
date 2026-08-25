"""X single-post fetch adapter (ADR 0108, amended).

The re-capture half of the X on-ramp. `scrolls sync x --bookmarks` learns
which posts you saved and captures them in bulk; this reads *one* post again,
so `scrolls verify` can say whether a held post still says what it said —
`unchanged`, `drifted`, or `rotted` — instead of the honest shrug ADR 0108
originally had to settle for.

**It authenticates the way the rest of Scrolls reaches an account: with the
session already sitting in your browser.** X's public syndication CDN would
have been easier to call, but it is a different, anonymous surface — it cannot
see a protected account you follow, and a re-capture that sees less than the
capture did would read as drift that never happened. Borrowing the same
session the bookmarks walk uses means a re-read sees exactly what the original
read saw. Stored credentials stay the optional path (`scrolls x login`), never
the default.

Two properties make the verdicts trustworthy:

- **The same parser builds both captures.** Bookmarks pages and single-post
  responses carry the identical tweet subtree, so both route through
  `x_bookmarks.item_from_tweet_result`. The re-capture's `content_hash` is
  therefore comparable to the original's by construction, not by coincidence.
- **A deleted post is rot, not an error.** X reports deletion as a normal 200
  with an empty `data.tweetResult`, so there is no 404 for `custody._is_gone`
  to read. The adapter raises `SourceGone`, which carries the same fact as a
  type rather than inventing a status that never came over the wire.

The pinned query id rotates on X deploys, exactly like the bookmarks one; when
it does, the call fails with `XQueryIdRotated` naming the stale id rather than
looking like a post that vanished.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from scrolls.items import ScrollItem
from scrolls.sources import FetchError, SourceGone
from scrolls.x_bookmarks import item_from_tweet_result, tweet_result
from scrolls.x_graphql import XGraphQLError, fetch_tweet
from scrolls.x_session import XSession, XSessionError, load_session

ADAPTER = "x"

# Resolving a session decrypts cookies and may prompt the Keychain, so a
# whole-library sweep must not do it once per item. The process holds the first
# one it resolves; nothing here is written to disk.
_SESSION: XSession | None = None


def _session() -> XSession:
    """The browser session for this process, resolved once.

    Raises:
        FetchError: No logged-in X session could be found.
    """
    global _SESSION
    if _SESSION is None:
        try:
            _SESSION = load_session("auto")
        except XSessionError as exc:
            raise FetchError(str(exc)) from exc
    return _SESSION


def reset_session_cache() -> None:
    """Forget the cached session, so the next fetch resolves a fresh one."""
    global _SESSION
    _SESSION = None


def _tweet_id(item: ScrollItem) -> str:
    """The numeric post id for a held `x` item.

    Raises:
        FetchError: The item carries no usable post id.
    """
    if item.source_id:
        return str(item.source_id)
    # `x:<tweetId>` is the id shape both `sources/detect.py` and the bookmarks
    # walk produce, so it is a reliable fallback for a row saved before
    # `source_id` was populated.
    prefix, _, rest = (item.id or "").partition(":")
    if prefix == "x" and rest.isdigit():
        return rest
    raise FetchError(f"cannot tell which X post '{item.id}' is")


def fetch_item(item: ScrollItem) -> ScrollItem:
    """Re-capture one X post through the logged-in browser session.

    Args:
        item: The held item to re-read.

    Returns:
        The item with freshly captured content, at stage 'fetched'. `saved_at`
        is the held item's — this is a re-read of something already saved, not
        a new save.

    Raises:
        SourceGone: The post no longer exists, is suspended, or is withheld.
        FetchError: No session, a rotated query id, or any other failure.
    """
    tweet_id = _tweet_id(item)
    try:
        payload = fetch_tweet(_session(), tweet_id)
    except XGraphQLError as exc:
        raise FetchError(f"X post {tweet_id} could not be read: {exc}") from exc

    result = tweet_result(payload)
    if result is None:
        raise SourceGone(f"X post {tweet_id} is no longer available")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        fresh = item_from_tweet_result(result, synced_at=now, adapter=ADAPTER)
    except ValueError as exc:
        raise FetchError(f"X post {tweet_id} came back unreadable: {exc}") from exc
    return replace(
        fresh,
        saved_at=item.saved_at,
        provenance=_carry_over(item.provenance, fresh.provenance),
    )


def _carry_over(held: dict | None, fresh: dict) -> dict:
    """Fresh capture facts, keeping the held item's facts about *saving*.

    `item_from_tweet_result` describes a capture that just happened, so its
    `saved_at_source` and `sort_index` describe *this* read. But a re-capture
    keeps the held `saved_at`, and the bookmark ordering was never re-read at
    all — so both of those belong to the original save and are carried across.
    Claiming otherwise would let a re-read quietly restate when you saved
    something, which is the one thing the X on-ramp is careful never to invent.
    """
    carried = dict(fresh)
    held = held or {}
    for key in ("saved_at_source", "sort_index"):
        if key in held:
            carried[key] = held[key]
        else:
            carried.pop(key, None)
    return carried
