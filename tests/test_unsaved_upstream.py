"""Tests for recording saves removed upstream (roadmap H444, ADR 0118).

A collection pull that walked the whole collection knows what the service
still holds. A held item an earlier walk saw, and this complete walk did not,
was removed upstream: un-bookmarked, taken off every reading list. That gets
an `unsaved_upstream` event on the ledger's membership axis. The item stays
held (ADR 0113 §5), its scroll untouched, its drift posture unmoved.

Only the network is faked, as in `test_cli_x_bookmarks.py`.
"""

from __future__ import annotations

import json

import pytest

from scrolls.cli import main
from scrolls.custody import (
    SAVED_UPSTREAM_STATUS,
    UNSAVED_UPSTREAM_STATUS,
    latest_events,
    latest_membership_events,
)
from scrolls.items import ScrollItem, get_item, insert_item
from scrolls.paths import get_paths
from scrolls.wikipedia_lists import collect_reading_lists
from scrolls.x_bookmarks import parse_bookmarks_page

KEY = "x/bookmarks"


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "scrolls-home"))
    monkeypatch.setenv("SCROLLS_X_AUTH_TOKEN", "AUTH")
    monkeypatch.setenv("SCROLLS_X_CT0", "CSRF")


def _tweet_entry(tweet_id):
    return {
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
                                "result": {
                                    "core": {"screen_name": "someone", "name": "Some One"}
                                }
                            }
                        },
                        "legacy": {
                            "full_text": f"post {tweet_id}",
                            "created_at": "Mon Jun 01 15:34:00 +0000 2026",
                        },
                    }
                }
            }
        },
    }


def _tombstone_entry(tweet_id):
    """A bookmark whose post was deleted: still bookmarked, no live post."""
    return {
        "entryId": f"tweet-{tweet_id}",
        "content": {
            "itemContent": {
                "tweet_results": {"result": {"__typename": "TweetTombstone"}}
            }
        },
    }


def _page(entries, cursor=None):
    entries = list(entries)
    if cursor:
        entries.append({"entryId": "cursor-bottom-0", "content": {"value": cursor}})
    return {
        "data": {
            "bookmark_timeline_v2": {
                "timeline": {
                    "instructions": [{"type": "TimelineAddEntries", "entries": entries}]
                }
            }
        }
    }


def _posts(*ids):
    return [_tweet_entry(i) for i in ids]


@pytest.fixture
def fake_x(monkeypatch):
    """Serve queued GraphQL pages instead of calling X."""

    def install(pages):
        queued = list(pages)
        monkeypatch.setattr(
            "scrolls.x_graphql._http_get_page", lambda url, headers: queued.pop(0)
        )
        monkeypatch.setattr("scrolls.x_graphql.time.sleep", lambda _: None)

    return install


def _sync(capsys, *extra):
    capsys.readouterr()
    code = main(["sync", "x", "--collection", "bookmarks", "--browser", "env", *extra])
    return code, json.loads(capsys.readouterr().out)


def _membership():
    events = latest_membership_events(get_paths().db_path, KEY)
    return {item_id: event.status for item_id, event in events.items()}


# --- the walk reports what it saw, readable or not ---------------------------


def test_a_deleted_bookmark_is_seen_though_it_cannot_be_read():
    page = parse_bookmarks_page(
        _page([_tweet_entry(1), _tombstone_entry(2)], "C1"), synced_at="2026-10-29T00:00:00+00:00"
    )
    assert [item.id for item in page.items] == ["x:1"]
    assert set(page.seen) == {"x:1", "x:2"}
    assert page.unidentified == 0


def test_an_entry_without_a_post_id_is_unidentified():
    broken = {"entryId": "tweet-broken", "content": {"itemContent": {}}}
    page = parse_bookmarks_page(_page([broken]), synced_at="2026-10-29T00:00:00+00:00")
    assert page.seen == ()
    assert page.unidentified == 1


def test_a_page_of_only_deleted_posts_does_not_end_the_walk(scrolls_home, fake_x, capsys):
    fake_x([
        _page(_posts(1), "C1"),
        _page([_tombstone_entry(2)], "C2"),
        _page(_posts(3)),
    ])
    code, payload = _sync(capsys)
    assert code == 0
    assert payload["pages"] == 3
    assert payload["imported"] == 2


# --- a complete walk records membership ------------------------------------


def test_the_first_complete_walk_records_the_baseline(scrolls_home, fake_x, capsys):
    fake_x([_page(_posts(1, 2), "C1"), _page(_posts(3))])
    code, payload = _sync(capsys)

    assert code == 0
    assert payload["upstream"] == {
        "compared": True, "reason": None, "saved": 3,
        "unsaved": [], "resaved": [], "still_unsaved": 0,
    }
    assert _membership() == {
        "x:1": SAVED_UPSTREAM_STATUS,
        "x:2": SAVED_UPSTREAM_STATUS,
        "x:3": SAVED_UPSTREAM_STATUS,
    }


def test_a_save_removed_upstream_is_recorded_and_still_held(scrolls_home, fake_x, capsys):
    fake_x([_page(_posts(1, 2, 3))])
    _sync(capsys)
    db = get_paths().db_path
    before = get_item(db, "x:2")

    fake_x([_page(_posts(1, 3))])
    code, payload = _sync(capsys)

    assert code == 0
    assert payload["upstream"]["unsaved"] == ["x:2"]
    assert payload["upstream"]["saved"] == 0
    assert _membership()["x:2"] == UNSAVED_UPSTREAM_STATUS
    # report-only: the save stays held, untouched, and its drift posture unmoved
    assert get_item(db, "x:2") == before
    assert "x:2" not in latest_events(db)


def test_a_removal_is_recorded_once(scrolls_home, fake_x, capsys):
    fake_x([_page(_posts(1, 2))])
    _sync(capsys)
    fake_x([_page(_posts(1))])
    _sync(capsys)

    fake_x([_page(_posts(1))])
    _, payload = _sync(capsys)
    assert payload["upstream"]["unsaved"] == []
    assert payload["upstream"]["still_unsaved"] == 1


def test_a_save_that_returns_is_recorded_as_resaved(scrolls_home, fake_x, capsys):
    fake_x([_page(_posts(1, 2))])
    _sync(capsys)
    fake_x([_page(_posts(1))])
    _sync(capsys)

    fake_x([_page(_posts(1, 2))])
    _, payload = _sync(capsys)
    assert payload["upstream"]["resaved"] == ["x:2"]
    assert payload["upstream"]["still_unsaved"] == 0
    assert _membership()["x:2"] == SAVED_UPSTREAM_STATUS


def test_a_deleted_post_still_bookmarked_is_not_unsaved(scrolls_home, fake_x, capsys):
    fake_x([_page(_posts(1, 2))])
    _sync(capsys)

    fake_x([_page([_tweet_entry(1), _tombstone_entry(2)])])
    _, payload = _sync(capsys)
    assert payload["upstream"]["unsaved"] == []
    assert _membership()["x:2"] == SAVED_UPSTREAM_STATUS


# --- an incomplete walk compares nothing -----------------------------------


def test_a_limited_walk_records_nothing(scrolls_home, fake_x, capsys):
    fake_x([_page(_posts(1, 2))])
    _sync(capsys)

    fake_x([_page(_posts(1, 2))])
    _, payload = _sync(capsys, "--limit", "1")
    assert payload["upstream"]["compared"] is False
    assert "--limit" in payload["upstream"]["reason"]
    assert _membership() == {"x:1": SAVED_UPSTREAM_STATUS, "x:2": SAVED_UPSTREAM_STATUS}


def test_a_walk_that_ended_early_records_nothing(scrolls_home, fake_x, monkeypatch, capsys):
    fake_x([_page(_posts(1, 2))])
    _sync(capsys)

    from scrolls.x_graphql import XGraphQLError

    pages = [_page(_posts(1), "C1")]

    def flaky(url, headers):
        if pages:
            return pages.pop(0)
        raise XGraphQLError("HTTP 500 from X")

    monkeypatch.setattr("scrolls.x_graphql._http_get_page", flaky)
    _, payload = _sync(capsys)
    assert payload["upstream"]["compared"] is False
    assert "ended early" in payload["upstream"]["reason"]
    assert _membership()["x:2"] == SAVED_UPSTREAM_STATUS


def test_an_unidentified_entry_blocks_the_comparison(scrolls_home, fake_x, capsys):
    fake_x([_page(_posts(1, 2))])
    _sync(capsys)

    broken = {"entryId": "tweet-broken", "content": {"itemContent": {}}}
    fake_x([_page([_tweet_entry(1), broken])])
    _, payload = _sync(capsys)
    assert payload["upstream"]["compared"] is False
    assert "could not be identified" in payload["upstream"]["reason"]
    assert _membership()["x:2"] == SAVED_UPSTREAM_STATUS


# --- what counts as an earlier member --------------------------------------


def test_a_bookmark_pulled_before_this_existed_is_compared(scrolls_home, fake_x, capsys):
    # The live library's 482 bookmarks have no membership events; their
    # provenance names the on-ramp that pulled them, so they are members.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="x:9", source="x", source_id="9", url="https://x.com/a/status/9",
        title="old bookmark", saved_at="2026-08-25T00:00:00+00:00", stage="fetched",
        provenance={"adapter": "x-bookmarks"},
    ))
    insert_item(db, ScrollItem(
        id="x:8", source="x", source_id="8", url="https://x.com/a/status/8",
        title="ingested by URL", saved_at="2026-08-25T00:00:00+00:00", stage="fetched",
        provenance={"adapter": "x"},
    ))

    fake_x([_page(_posts(1))])
    _, payload = _sync(capsys)
    assert payload["upstream"]["unsaved"] == ["x:9"]  # x:8 was never a bookmark
    assert "x:8" not in _membership()


def test_an_item_removed_from_the_library_gets_no_event(scrolls_home, fake_x, capsys):
    fake_x([_page(_posts(1, 2))])
    _sync(capsys)
    capsys.readouterr()
    assert main(["rm", "x:2"]) == 0

    fake_x([_page(_posts(1))])
    _, payload = _sync(capsys)
    assert payload["upstream"]["unsaved"] == []


# --- the timeline ---------------------------------------------------------


def test_history_shows_and_filters_the_membership_axis(scrolls_home, fake_x, capsys):
    fake_x([_page(_posts(1, 2))])
    _sync(capsys)
    fake_x([_page(_posts(1))])
    _sync(capsys)

    capsys.readouterr()
    assert main(["history", "x:2", "--status", UNSAVED_UPSTREAM_STATUS]) == 0
    (event,) = json.loads(capsys.readouterr().out)
    assert event["status"] == UNSAVED_UPSTREAM_STATUS
    assert event["detail"] == KEY


# --- reading lists --------------------------------------------------------


class _Session:
    cookie_header = "c=1"
    origin = "env"
    display_name = "Reader"


def test_reading_lists_report_every_article_they_hold():
    lists = {"query": {"readinglists": [{"id": 1, "name": "default", "default": True}]}}
    entries = {"query": {"readinglistentries": [
        {"id": 10, "listId": 1, "project": "https://en.wikipedia.org", "title": "SQLite",
         "created": "2026-01-01T00:00:00Z"},
        {"id": 11, "listId": 1, "project": "https://commons.wikimedia.org", "title": "File:X.png",
         "created": "2026-01-01T00:00:00Z"},
        {"id": 12, "listId": 1, "project": "", "title": "",
         "created": "2026-01-01T00:00:00Z"},
    ]}}

    def get_json(url):
        return entries if "readinglistentries" in url else lists

    result = collect_reading_lists(
        _Session(), imported_at="2026-10-29T00:00:00+00:00", get_json=get_json
    )
    assert result.seen == ("wikipedia:en:SQLite",)
    # Commons can never be held, so it does not block a comparison; an entry
    # with no title could be anything, so it does.
    assert result.unidentified == 1
