"""The collection declaration: which sources offer a saved collection (ADR 0113).

A source with no collection is an honest, first-class answer — an empty
tuple — never an error. These pin the registry itself; the CLI surface built
on it is covered in `test_cli_sync_collections.py`.
"""

import pytest

from scrolls.saved_collections import (
    COLLECTIONS,
    UnknownCollection,
    collections_for,
    resolve_collection,
)


def test_the_two_shipped_collections_are_declared():
    declared = {(c.source, c.name) for c in COLLECTIONS}
    assert declared == {("x", "bookmarks"), ("wikipedia", "reading-lists")}


def test_a_source_without_a_collection_answers_empty_not_error():
    assert collections_for("youtube") == ()
    assert collections_for("no-such-source") == ()


def test_each_collection_declares_its_custody_shape():
    x = resolve_collection("x", "bookmarks")
    assert x.shape == "capture-at-pull"
    assert x.entry_stage == "fetched"
    assert x.saved_at == "sync-time"
    assert x.routes == ("browser", "oauth")

    wiki = resolve_collection("wikipedia", "reading-lists")
    assert wiki.shape == "enumerate-only"
    assert wiki.entry_stage == "detected"
    assert wiki.saved_at == "service"
    assert wiki.routes == ("browser",)


def test_the_browser_session_is_always_the_default_route():
    """Repo rule: the logged-in session first, stored credentials optional."""
    for collection in COLLECTIONS:
        assert collection.routes[0] == "browser"


def test_describe_is_the_json_shape_the_cli_lists():
    described = resolve_collection("wikipedia", "reading-lists").describe()
    assert described["source"] == "wikipedia"
    assert described["collection"] == "reading-lists"
    assert described["command"] == "scrolls sync wikipedia --collection reading-lists"
    assert described["adr"] == "0109"
    assert "pull" not in described


def test_an_unknown_name_on_a_collection_source_names_what_exists():
    with pytest.raises(UnknownCollection) as exc:
        resolve_collection("x", "likes")
    assert "bookmarks" in str(exc.value)


def test_a_source_with_no_collections_says_so_plainly():
    with pytest.raises(UnknownCollection) as exc:
        resolve_collection("youtube", "playlists")
    message = str(exc.value)
    assert "youtube offers no saved collection" in message
    assert "x" in message and "wikipedia" in message
