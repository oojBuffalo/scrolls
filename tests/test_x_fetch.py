"""Tests for the X single-post fetch adapter — the re-capture half of ADR 0108.

The adapter exists so `scrolls verify` can tell a drifted post from a deleted
one. These fixtures mirror what `TweetResultByRestId` returns: the same tweet
subtree the bookmarks timeline carries, wrapped in `data.tweetResult.result`,
and — for a post that is gone — a perfectly normal 200 with that key empty.
"""

from dataclasses import replace

import pytest

from scrolls.custody import verify_item
from scrolls.sources import FETCH_ADAPTERS, FetchError, SourceGone
from scrolls.sources import x as x_source
from scrolls.x_bookmarks import parse_bookmarks_page
from scrolls.x_graphql import XAuthExpired, XQueryIdRotated

SYNCED_AT = "2026-08-11T12:00:00+00:00"
NOW = "2026-08-25T00:00:00+00:00"
TWEET_ID = "1111"

TEXT = "SQLite FTS5 is criminally underrated."


def _subtree(*, full_text=TEXT, tweet_id=TWEET_ID, typename="Tweet"):
    """The tweet subtree both X endpoints return."""
    return {
        "__typename": typename,
        "rest_id": tweet_id,
        "core": {
            "user_results": {
                "result": {
                    "rest_id": "9001",
                    "core": {"screen_name": "karpathy", "name": "Andrej Karpathy"},
                }
            }
        },
        "legacy": {
            "id_str": tweet_id,
            "full_text": full_text,
            "created_at": "Mon Jun 01 15:34:00 +0000 2026",
            "entities": {"urls": []},
        },
    }


def _payload(result=None):
    """A single-post response; `None` is how X reports a post that is gone."""
    return {"data": {"tweetResult": {} if result is None else {"result": result}}}


def _bookmarks_payload(subtree, sort_index="1799999999999999999"):
    """The same subtree as it arrives on a bookmarks page."""
    return {
        "data": {
            "bookmark_timeline_v2": {
                "timeline": {
                    "instructions": [
                        {
                            "type": "TimelineAddEntries",
                            "entries": [
                                {
                                    "entryId": f"tweet-{TWEET_ID}",
                                    "sortIndex": sort_index,
                                    "content": {
                                        "itemContent": {
                                            "tweet_results": {"result": subtree}
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


@pytest.fixture(autouse=True)
def _no_real_session(monkeypatch):
    """Never touch a browser, a Keychain, or the network in tests."""
    x_source.reset_session_cache()
    monkeypatch.setattr(
        x_source, "load_session", lambda *a, **k: object(), raising=True
    )
    yield
    x_source.reset_session_cache()


def _held(**overrides):
    """The item as the bookmarks walk stored it."""
    captured = parse_bookmarks_page(
        _bookmarks_payload(_subtree()), synced_at=SYNCED_AT
    ).items[0]
    return replace(captured, **overrides) if overrides else captured


def _stub_fetch(monkeypatch, payload_or_error):
    """Point the adapter's transport at a fixture instead of X."""

    def fake(session, tweet_id, **kwargs):
        if isinstance(payload_or_error, Exception):
            raise payload_or_error
        return payload_or_error

    monkeypatch.setattr(x_source, "fetch_tweet", fake, raising=True)


def test_x_is_registered_as_a_fetch_adapter():
    """Without this entry `verify` cannot check an x item at all."""
    assert FETCH_ADAPTERS.get("x") is x_source.fetch_item


def test_a_recapture_hashes_identically_to_the_original_capture(monkeypatch):
    """The property every X verify verdict rests on.

    The bookmarks walk and the single-post read return the same tweet subtree,
    so routing both through one parser must make their content hashes equal.
    If these two ever diverge, every unchanged post starts reporting drift.
    """
    held = _held()
    _stub_fetch(monkeypatch, _payload(_subtree()))

    fresh = x_source.fetch_item(held)

    assert fresh.content_hash == held.content_hash
    assert fresh.id == held.id
    assert verify_item(held, x_source.fetch_item, now=NOW).status == "unchanged"


def test_an_edited_post_is_drift_not_rot(monkeypatch):
    """Changed text is the source moving, which custody records as an event."""
    held = _held()
    _stub_fetch(monkeypatch, _payload(_subtree(full_text="Actually, DuckDB.")))

    event = verify_item(held, x_source.fetch_item, now=NOW)

    assert event.status == "drifted"
    assert event.prior_hash == held.content_hash
    assert event.observed_hash and event.observed_hash != held.content_hash


def test_a_deleted_post_is_rot_even_though_x_answers_200(monkeypatch):
    """X reports deletion inside a success envelope, not as a 404.

    `custody._is_gone` reads an HTTP status off the failure's cause precisely so
    a message string never decides rot. There is no status to read here, so the
    adapter has to carry the fact as a type — otherwise every deleted bookmark
    would be filed as a transient `error` and look retryable forever.
    """
    held = _held()
    _stub_fetch(monkeypatch, _payload(None))

    with pytest.raises(SourceGone):
        x_source.fetch_item(held)

    assert verify_item(held, x_source.fetch_item, now=NOW).status == "rotted"


def test_a_withheld_post_is_rot_too(monkeypatch):
    """A tombstone is not a Tweet, so there is nothing left to hold."""
    held = _held()
    _stub_fetch(monkeypatch, _payload(_subtree(typename="TweetTombstone")))

    assert verify_item(held, x_source.fetch_item, now=NOW).status == "rotted"


def test_a_visibility_envelope_is_unwrapped_not_treated_as_gone(monkeypatch):
    """X wraps some live posts in a visibility envelope; the post is still there."""
    held = _held()
    wrapped = {"__typename": "TweetWithVisibilityResults", "tweet": _subtree()}
    _stub_fetch(monkeypatch, _payload(wrapped))

    assert verify_item(held, x_source.fetch_item, now=NOW).status == "unchanged"


def test_an_expired_session_is_an_error_never_rot(monkeypatch):
    """A logged-out browser must not be mistaken for 482 deleted posts.

    This is the failure most likely to hit a whole-library sweep, and the one
    where a wrong verdict is worst: rot is a claim that the source is gone.
    """
    held = _held()
    _stub_fetch(monkeypatch, XAuthExpired("session no longer valid"))

    event = verify_item(held, x_source.fetch_item, now=NOW)

    assert event.status == "error"
    assert "session" in event.detail


def test_a_rotated_query_id_is_an_error_never_rot(monkeypatch):
    """X redeploying its API is our problem to fix, not evidence of deletion."""
    held = _held()
    _stub_fetch(monkeypatch, XQueryIdRotated("pinned query id no longer resolves"))

    assert verify_item(held, x_source.fetch_item, now=NOW).status == "error"


def test_a_recapture_never_restates_when_you_saved_something(monkeypatch):
    """The one thing the X on-ramp is careful never to invent.

    X exposes no bookmark timestamp, so the capture recorded `saved_at_source:
    synced_at` — "we do not know when you saved this". A re-read happens later
    and knows no more than the first read did, so it must carry that across
    rather than quietly stamping itself as the save time.
    """
    held = _held()
    _stub_fetch(monkeypatch, _payload(_subtree()))

    fresh = x_source.fetch_item(held)

    assert fresh.saved_at == held.saved_at
    assert fresh.provenance["saved_at_source"] == "synced_at"
    assert fresh.provenance["sort_index"] == held.provenance["sort_index"]
    assert fresh.provenance["adapter"] == "x"
    assert fresh.provenance["fetched_at"] != held.provenance["fetched_at"]


def test_the_session_is_resolved_once_across_a_sweep(monkeypatch):
    """Resolving a session can prompt the Keychain; 482 prompts is not a sweep."""
    calls = []

    def counting(*args, **kwargs):
        calls.append(1)
        return object()

    monkeypatch.setattr(x_source, "load_session", counting, raising=True)
    x_source.reset_session_cache()
    _stub_fetch(monkeypatch, _payload(_subtree()))

    held = _held()
    for _ in range(5):
        x_source.fetch_item(held)

    assert len(calls) == 1


def test_no_logged_in_session_is_a_fetch_error(monkeypatch):
    """Told to log in, rather than a stack trace mid-sweep."""
    from scrolls.x_session import XSessionError

    def logged_out(*args, **kwargs):
        raise XSessionError("no X session found — log in at https://x.com")

    monkeypatch.setattr(x_source, "load_session", logged_out, raising=True)
    x_source.reset_session_cache()

    with pytest.raises(FetchError, match="log in"):
        x_source.fetch_item(_held())


def test_the_post_id_falls_back_to_the_item_id(monkeypatch):
    """Rows saved before `source_id` was populated are still verifiable."""
    held = _held(source_id=None)
    seen = {}

    def capture(session, tweet_id, **kwargs):
        seen["id"] = tweet_id
        return _payload(_subtree())

    monkeypatch.setattr(x_source, "fetch_tweet", capture, raising=True)
    x_source.fetch_item(held)

    assert seen["id"] == TWEET_ID


def test_an_item_with_no_usable_post_id_is_an_error(monkeypatch):
    """Better to say which item cannot be identified than to guess at one."""
    held = _held(source_id=None, id="x:not-a-number")
    with pytest.raises(FetchError, match="which X post"):
        x_source.fetch_item(held)
