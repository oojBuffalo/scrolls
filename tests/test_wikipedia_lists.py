"""Tests for the Wikipedia reading-lists collection pull.

Fixtures here are shaped from real payloads captured against a live
logged-in account on 2026-08-18 — the list objects, the entry objects and
the `continue` envelope are MediaWiki's own, not a reading of its docs.
The network is injected, so no test reaches Wikipedia or the Keychain.
"""

import pytest

from scrolls.items import make_item_id
from scrolls.sources.detect import detect_source
from scrolls.wikipedia_lists import (
    WikipediaAuthExpired,
    WikipediaListsError,
    WikipediaSession,
    collect_reading_lists,
    entry_url,
)

SESSION = WikipediaSession(username="NerdBuffalo", session="s3cr3t", origin="brave")

LISTS = {
    "batchcomplete": True,
    "query": {
        "readinglists": [
            {
                "id": 3167187,
                "name": "default",
                "default": True,
                "description": "",
                "created": "2021-06-25T17:29:02Z",
                "updated": "2021-06-25T17:29:02Z",
                "size": 2,
            },
            {
                "id": 3787206,
                "name": "$$$",
                "default": False,
                "description": "",
                "created": "2022-09-14T02:41:17Z",
                "updated": "2025-08-13T05:05:53Z",
                "size": 1,
            },
        ]
    },
}


def _entry(entry_id, list_id, title, created="2022-08-14T05:43:34Z"):
    return {
        "id": entry_id,
        "listId": list_id,
        "project": "https://en.wikipedia.org",
        "title": title,
        "created": created,
        "updated": created,
    }


def _responder(pages):
    """Serve `pages` in order, one per call, recording the URLs asked for."""
    calls = []

    def get_json(url):
        calls.append(url)
        return pages[min(len(calls) - 1, len(pages) - 1)]

    get_json.calls = calls
    return get_json


def _entries_page(entries, *, cont=None):
    page = {"query": {"readinglistentries": entries}}
    if cont:
        page["continue"] = {"rlecontinue": cont, "continue": "-||"}
    return page


def test_pulls_every_list_and_preserves_membership_as_tags():
    """Both lists arrive; a named list becomes a tag, the default list does not."""
    get_json = _responder(
        [
            LISTS,
            _entries_page(
                [
                    _entry(1, 3167187, "AI-complete"),
                    _entry(2, 3167187, "APL (programming language)"),
                    _entry(3, 3787206, "Bayes' theorem"),
                ]
            ),
        ]
    )
    result = collect_reading_lists(
        SESSION, imported_at="2026-08-18T00:00:00+00:00", get_json=get_json
    )

    assert [item.title for item in result.items] == [
        "AI-complete",
        "APL (programming language)",
        "Bayes' theorem",
    ]
    # the user's own curation survives; "default" is the absence of a choice
    assert result.items[0].tags == ()
    assert result.items[2].tags == ("$$$",)
    assert result.lists == {3167187: "default", 3787206: "$$$"}


def test_saved_at_comes_from_the_entry_created_time():
    """`created` is when the user saved it — never the article's own date."""
    get_json = _responder(
        [LISTS, _entries_page([_entry(1, 3167187, "AI-complete", "2021-09-25T08:38:28Z")])]
    )
    result = collect_reading_lists(
        SESSION, imported_at="2026-08-18T00:00:00+00:00", get_json=get_json
    )

    item = result.items[0]
    assert item.saved_at == "2021-09-25T08:38:28+00:00"
    assert item.published_at is None


def test_identity_matches_what_scrolls_add_would_mint():
    """A pulled article and an `add` of its URL converge on one item."""
    get_json = _responder(
        [LISTS, _entries_page([_entry(1, 3167187, "APL (programming language)")])]
    )
    result = collect_reading_lists(
        SESSION, imported_at="2026-08-18T00:00:00+00:00", get_json=get_json
    )

    added = detect_source("https://en.wikipedia.org/wiki/APL_(programming_language)")
    assert result.items[0].id == make_item_id(added.source, added.source_id, "")
    assert result.items[0].id == "wikipedia:en:APL_(programming_language)"
    assert result.items[0].stage == "detected"


def test_walks_past_the_first_page_of_entries():
    """A collection larger than one page is followed to the end."""
    get_json = _responder(
        [
            LISTS,
            _entries_page([_entry(1, 3167187, "One")], cont="One|1"),
            _entries_page([_entry(2, 3167187, "Two")]),
        ]
    )
    result = collect_reading_lists(
        SESSION, imported_at="2026-08-18T00:00:00+00:00", get_json=get_json
    )

    assert [item.title for item in result.items] == ["One", "Two"]
    assert result.pages == 2
    assert "rlecontinue=One%7C1" in get_json.calls[-1]


def test_repeated_cursor_terminates_the_walk():
    """A server that keeps handing back the same cursor cannot loop us forever."""
    get_json = _responder([LISTS, _entries_page([_entry(1, 3167187, "One")], cont="stuck")])
    result = collect_reading_lists(
        SESSION, imported_at="2026-08-18T00:00:00+00:00", get_json=get_json
    )

    # the walk stops rather than looping, and the repeat collapses to one item
    assert result.pages == 2
    assert len({item.id for item in result.items}) == 1


def test_empty_collection_is_not_an_error():
    """No saved articles is a true answer, not a failure."""
    get_json = _responder([{"query": {"readinglists": []}}])
    result = collect_reading_lists(
        SESSION, imported_at="2026-08-18T00:00:00+00:00", get_json=get_json
    )

    assert result.items == ()
    assert result.error is None
    assert result.pages == 0


def test_entry_from_a_non_wikipedia_project_is_reported_not_guessed():
    """Reading lists span Wikimedia; only Wikipedia has an adapter here."""
    get_json = _responder(
        [
            LISTS,
            _entries_page(
                [
                    _entry(1, 3167187, "AI-complete"),
                    {
                        "id": 2,
                        "listId": 3167187,
                        "project": "https://commons.wikimedia.org",
                        "title": "File:Example.jpg",
                        "created": "2022-08-14T05:43:34Z",
                        "updated": "2022-08-14T05:43:34Z",
                    },
                ]
            ),
        ]
    )
    result = collect_reading_lists(
        SESSION, imported_at="2026-08-18T00:00:00+00:00", get_json=get_json
    )

    assert [item.title for item in result.items] == ["AI-complete"]
    assert len(result.failures) == 1
    assert result.failures[0]["project"] == "https://commons.wikimedia.org"


def test_a_logged_out_session_fails_the_whole_run():
    """No silent partial import: the credential problem is the whole answer."""

    def get_json(url):
        return {
            "error": {
                "code": "notloggedin",
                "info": "You must be logged in to view your private information.",
            }
        }

    with pytest.raises(WikipediaAuthExpired, match="logged in"):
        collect_reading_lists(
            SESSION, imported_at="2026-08-18T00:00:00+00:00", get_json=get_json
        )


def test_a_removed_reading_lists_api_says_so_rather_than_reporting_zero():
    """The one wrong answer is 'you saved nothing'."""

    def get_json(url):
        return {"error": {"code": "unknown_meta", "info": "Unrecognized value"}}

    with pytest.raises(WikipediaListsError, match="ReadingLists"):
        collect_reading_lists(
            SESSION, imported_at="2026-08-18T00:00:00+00:00", get_json=get_json
        )


def test_limit_stops_the_walk_early():
    get_json = _responder(
        [
            LISTS,
            _entries_page(
                [_entry(1, 3167187, "One"), _entry(2, 3167187, "Two")], cont="x"
            ),
        ]
    )
    result = collect_reading_lists(
        SESSION, imported_at="2026-08-18T00:00:00+00:00", get_json=get_json, limit=1
    )

    assert len(result.items) == 1


@pytest.mark.parametrize(
    "title,expected",
    [
        ("AI-complete", "https://en.wikipedia.org/wiki/AI-complete"),
        (
            "APL (programming language)",
            "https://en.wikipedia.org/wiki/APL_(programming_language)",
        ),
        ("24/7 service", "https://en.wikipedia.org/wiki/24%2F7_service"),
        ("C++", "https://en.wikipedia.org/wiki/C%2B%2B"),
    ],
)
def test_entry_url_encodes_titles_the_way_wikipedia_does(title, expected):
    """Spaces become underscores; everything else is percent-encoded."""
    assert entry_url("https://en.wikipedia.org", title) == expected


def test_session_repr_hides_the_session_cookie():
    assert "s3cr3t" not in repr(SESSION)
    assert "NerdBuffalo" in repr(SESSION)


def test_an_article_in_two_lists_collapses_to_one_item_keeping_both_tags():
    """The same article filed in `default` and a named list is one save.

    Wikipedia keeps an article in the default list *and* in whatever list you
    file it into, so the collection genuinely serves the same title twice.
    Inserting both would let `INSERT OR IGNORE` keep whichever arrived first
    and silently drop the other's list membership.
    """
    get_json = _responder(
        [
            LISTS,
            _entries_page(
                [
                    _entry(1, 3167187, "Bayes' theorem", "2021-01-01T00:00:00Z"),
                    _entry(2, 3787206, "Bayes' theorem", "2022-05-05T00:00:00Z"),
                ]
            ),
        ]
    )
    result = collect_reading_lists(
        SESSION, imported_at="2026-08-18T00:00:00+00:00", get_json=get_json
    )

    assert len(result.items) == 1
    assert result.items[0].tags == ("$$$",)
    # the earliest save is when the article entered the user's life
    assert result.items[0].saved_at == "2021-01-01T00:00:00+00:00"


def test_membership_in_two_named_lists_keeps_both_tags():
    get_json = _responder(
        [
            {
                "query": {
                    "readinglists": [
                        {"id": 1, "name": "default", "default": True},
                        {"id": 2, "name": "$$$"},
                        {"id": 3, "name": "physics"},
                    ]
                }
            },
            _entries_page(
                [_entry(1, 2, "Entropy"), _entry(2, 3, "Entropy")]
            ),
        ]
    )
    result = collect_reading_lists(
        SESSION, imported_at="2026-08-18T00:00:00+00:00", get_json=get_json
    )

    assert len(result.items) == 1
    assert result.items[0].tags == ("$$$", "physics")


def test_limit_counts_distinct_articles_not_entries():
    """Two list memberships of one article are one article against the limit."""
    get_json = _responder(
        [
            LISTS,
            _entries_page(
                [
                    _entry(1, 3167187, "One"),
                    _entry(2, 3787206, "One"),
                    _entry(3, 3167187, "Two"),
                ]
            ),
        ]
    )
    result = collect_reading_lists(
        SESSION, imported_at="2026-08-18T00:00:00+00:00", get_json=get_json, limit=2
    )

    assert [item.title for item in result.items] == ["One", "Two"]
