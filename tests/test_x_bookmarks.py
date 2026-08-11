"""Tests for the native X bookmarks collection parser.

Fixtures mirror the shape X's internal GraphQL bookmarks endpoint returns
(`data.bookmark_timeline_v2.timeline.instructions[].entries[]`), including the
two author shapes X has shipped, note_tweet long-form text, quoted tweets, and
the `cursor-bottom` pagination entry.
"""

import json

from scrolls.x_bookmarks import parse_bookmarks_page

SYNCED_AT = "2026-08-11T12:00:00+00:00"


def _tweet_entry(
    tweet_id="1111",
    *,
    full_text="SQLite FTS5 is criminally underrated.",
    screen_name="karpathy",
    name="Andrej Karpathy",
    legacy_author=False,
    note_text=None,
    media=None,
    urls=None,
    quoted=None,
    sort_index="1799999999999999999",
):
    """Build one TimelineAddEntries tweet entry."""
    author_result = {"rest_id": "9001"}
    if legacy_author:
        author_result["legacy"] = {"screen_name": screen_name, "name": name}
    else:
        author_result["core"] = {"screen_name": screen_name, "name": name}

    legacy = {
        "id_str": tweet_id,
        "full_text": full_text,
        "created_at": "Mon Jun 01 15:34:00 +0000 2026",
        "lang": "en",
        "entities": {"urls": urls or []},
    }
    if media:
        legacy["extended_entities"] = {"media": media}

    result = {
        "__typename": "Tweet",
        "rest_id": tweet_id,
        "core": {"user_results": {"result": author_result}},
        "legacy": legacy,
    }
    if note_text:
        result["note_tweet"] = {
            "note_tweet_results": {"result": {"text": note_text}}
        }
    if quoted:
        result["quoted_status_result"] = {"result": quoted}

    entry = {
        "entryId": f"tweet-{tweet_id}",
        "content": {
            "entryType": "TimelineTimelineItem",
            "itemContent": {
                "itemType": "TimelineTweet",
                "tweet_results": {"result": result},
            },
        },
    }
    if sort_index is not None:
        entry["sortIndex"] = sort_index
    return entry


def _cursor_entry(value="CURSOR_NEXT"):
    return {
        "entryId": "cursor-bottom-0",
        "content": {"entryType": "TimelineTimelineCursor", "value": value},
    }


def _response(entries):
    return {
        "data": {
            "bookmark_timeline_v2": {
                "timeline": {
                    "instructions": [
                        {"type": "TimelineAddEntries", "entries": entries}
                    ]
                }
            }
        }
    }


def test_parses_a_single_bookmark_into_a_fetched_x_item():
    page = parse_bookmarks_page(
        _response([_tweet_entry(), _cursor_entry()]), synced_at=SYNCED_AT
    )

    assert len(page.items) == 1
    item = page.items[0]
    assert item.id == "x:1111"
    assert item.source == "x"
    assert item.source_id == "1111"
    assert item.url == "https://x.com/karpathy/status/1111"
    assert item.stage == "fetched"
    assert item.author == "Andrej Karpathy (@karpathy)"
    assert item.extracted_text == "SQLite FTS5 is criminally underrated."
    assert item.published_at == "2026-06-01T15:34:00+00:00"


def test_item_id_matches_what_detect_produces_for_a_status_url():
    """`x:<tweetId>` so `scrolls add` and a bookmarks pull converge on one item."""
    from scrolls.items import make_item_id

    page = parse_bookmarks_page(_response([_tweet_entry()]), synced_at=SYNCED_AT)
    expected = make_item_id("x", "1111", "https://x.com/karpathy/status/1111")
    assert page.items[0].id == expected


def test_reads_the_newer_core_author_shape_and_the_legacy_one():
    new_shape = parse_bookmarks_page(
        _response([_tweet_entry()]), synced_at=SYNCED_AT
    ).items[0]
    old_shape = parse_bookmarks_page(
        _response([_tweet_entry(legacy_author=True)]), synced_at=SYNCED_AT
    ).items[0]
    assert new_shape.author == old_shape.author == "Andrej Karpathy (@karpathy)"


def test_note_tweet_text_wins_over_truncated_full_text():
    long_form = "A much longer post that the legacy field truncates."
    page = parse_bookmarks_page(
        _response([_tweet_entry(full_text="A much longer post that…", note_text=long_form)]),
        synced_at=SYNCED_AT,
    )
    assert page.items[0].extracted_text == long_form


def test_quoted_tweet_text_is_folded_into_the_extracted_body():
    quoted = {
        "core": {"user_results": {"result": {"core": {"screen_name": "someone"}}}},
        "legacy": {"full_text": "the original claim"},
    }
    page = parse_bookmarks_page(
        _response([_tweet_entry(full_text="This holds up.", quoted=quoted)]),
        synced_at=SYNCED_AT,
    )
    assert page.items[0].extracted_text == (
        "This holds up.\n\nQuoting @someone: the original claim"
    )


def test_media_and_expanded_links_are_captured():
    page = parse_bookmarks_page(
        _response(
            [
                _tweet_entry(
                    media=[
                        {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/abc.png"}
                    ],
                    urls=[{"expanded_url": "https://sqlite.org/fts5.html"}],
                )
            ]
        ),
        synced_at=SYNCED_AT,
    )
    item = page.items[0]
    assert item.media == ({"type": "photo", "url": "https://pbs.twimg.com/media/abc.png"},)
    assert item.links == ("https://sqlite.org/fts5.html",)


def test_raw_text_preserves_the_verbatim_tweet_subtree():
    """Raw is sacred: the captured subtree must round-trip as JSON."""
    page = parse_bookmarks_page(_response([_tweet_entry()]), synced_at=SYNCED_AT)
    restored = json.loads(page.items[0].raw_text)
    assert restored["rest_id"] == "1111"
    assert restored["legacy"]["full_text"] == "SQLite FTS5 is criminally underrated."


def test_cursor_is_returned_for_pagination_and_is_none_at_the_end():
    with_cursor = parse_bookmarks_page(
        _response([_tweet_entry(), _cursor_entry("CURSOR_NEXT")]), synced_at=SYNCED_AT
    )
    assert with_cursor.next_cursor == "CURSOR_NEXT"

    without = parse_bookmarks_page(_response([_tweet_entry()]), synced_at=SYNCED_AT)
    assert without.next_cursor is None


def test_saved_at_falls_back_to_sync_time_when_x_gives_no_bookmark_timestamp():
    """X's GraphQL carries no bookmark timestamp; sortIndex is ordering only.

    Field Theory's own types call sortIndex "useful for chronology, not
    timestamps", so `saved_at` falls back to the sync time and provenance
    records that it did — rather than inventing a save time from an opaque key.
    """
    page = parse_bookmarks_page(_response([_tweet_entry()]), synced_at=SYNCED_AT)
    item = page.items[0]
    assert item.saved_at == SYNCED_AT
    assert item.provenance["saved_at_source"] == "synced_at"


def test_sort_index_is_preserved_as_opaque_ordering_in_provenance():
    page = parse_bookmarks_page(
        _response([_tweet_entry(sort_index="1799999999999999999")]), synced_at=SYNCED_AT
    )
    assert page.items[0].provenance["sort_index"] == "1799999999999999999"


def test_provenance_names_the_graphql_extraction_path():
    page = parse_bookmarks_page(_response([_tweet_entry()]), synced_at=SYNCED_AT)
    provenance = page.items[0].provenance
    assert provenance["adapter"] == "x-bookmarks"
    assert provenance["extraction_method"] == "x:graphql-internal"


def test_a_malformed_entry_is_reported_without_aborting_the_page():
    broken = {
        "entryId": "tweet-broken",
        "content": {"itemContent": {"tweet_results": {"result": {}}}},
    }
    page = parse_bookmarks_page(
        _response([_tweet_entry(), broken]), synced_at=SYNCED_AT
    )
    assert len(page.items) == 1
    assert len(page.failures) == 1
    assert page.failures[0]["entry_id"] == "tweet-broken"


def test_tombstoned_and_non_tweet_entries_are_skipped_quietly():
    """Deleted/suspended bookmarks come back as a non-Tweet typename."""
    tombstone = {
        "entryId": "tweet-9999",
        "content": {
            "itemContent": {
                "tweet_results": {"result": {"__typename": "TweetTombstone"}}
            }
        },
    }
    page = parse_bookmarks_page(
        _response([_tweet_entry(), tombstone]), synced_at=SYNCED_AT
    )
    assert len(page.items) == 1
    assert page.failures == ()


def test_an_empty_bookmark_collection_yields_nothing_and_no_cursor():
    page = parse_bookmarks_page(_response([]), synced_at=SYNCED_AT)
    assert page.items == ()
    assert page.next_cursor is None
    assert page.failures == ()
