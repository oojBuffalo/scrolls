"""`scrolls sync <source> --collection <name>`: the one collection on-ramp verb.

Only the network is faked, as in the per-source CLI suites. These pin the
generic surface ADR 0113 settles — dispatch through the declaration, the
legacy per-source flags as aliases, and honest absence.
"""

import json

import pytest

from scrolls.cli import main


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


@pytest.fixture
def wiki_session(monkeypatch):
    monkeypatch.setenv("SCROLLS_WIKIPEDIA_USER", "NerdBuffalo")
    monkeypatch.setenv("SCROLLS_WIKIPEDIA_SESSION", "SESSION")


@pytest.fixture
def fake_wikipedia(monkeypatch):
    def install(pages):
        queued = list(pages)
        monkeypatch.setattr(
            "scrolls.wikipedia_lists.http.get_json",
            lambda url, headers=None: queued.pop(0),
        )

    return install


ONE_LIST = {
    "query": {"readinglists": [{"id": 1, "name": "default", "default": True}]}
}
ONE_ENTRY = {
    "query": {
        "readinglistentries": [
            {
                "id": 10,
                "listId": 1,
                "project": "https://en.wikipedia.org",
                "title": "AI-complete",
                "created": "2024-01-01T00:00:00Z",
                "updated": "2024-01-01T00:00:00Z",
            }
        ]
    }
}


def test_collection_flag_pulls_through_the_declaration(
    scrolls_home, wiki_session, fake_wikipedia, capsys
):
    fake_wikipedia([ONE_LIST, ONE_ENTRY])
    exit_code = main(
        ["sync", "wikipedia", "--collection", "reading-lists", "--browser", "env"]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 1
    assert payload["collection"] == "reading-lists"
    assert payload["source"] == "wikipedia"


def test_the_legacy_flag_and_the_collection_flag_are_one_path(
    scrolls_home, wiki_session, fake_wikipedia, capsys
):
    fake_wikipedia([ONE_LIST, ONE_ENTRY])
    main(["sync", "wikipedia", "--reading-lists", "--browser", "env"])
    first = json.loads(capsys.readouterr().out)

    fake_wikipedia([ONE_LIST, ONE_ENTRY])
    main(["sync", "wikipedia", "--collection", "reading-lists", "--browser", "env"])
    second = json.loads(capsys.readouterr().out)

    assert first["imported"] == 1 and second["skipped"] == 1
    assert first["collection"] == second["collection"] == "reading-lists"


def test_a_source_without_collections_is_refused_with_what_exists(
    scrolls_home, capsys
):
    assert main(["sync", "youtube", "--collection", "playlists"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert "youtube offers no saved collection" in error


def test_collection_without_a_source_is_refused(scrolls_home, capsys):
    assert main(["sync", "--collection", "bookmarks"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert "scrolls sync x --collection bookmarks" in error


def test_a_route_the_collection_does_not_offer_is_refused(
    scrolls_home, wiki_session, capsys
):
    assert (
        main(["sync", "wikipedia", "--collection", "reading-lists", "--auth", "oauth"])
        == 1
    )
    error = json.loads(capsys.readouterr().err)["error"]
    assert "oauth" in error and "browser" in error


def test_two_collection_flags_at_once_are_refused(scrolls_home, capsys):
    assert main(["sync", "x", "--bookmarks", "--collection", "bookmarks"]) == 1
    assert "one collection" in json.loads(capsys.readouterr().err)["error"]


def test_list_collections_names_every_declared_collection(scrolls_home, capsys):
    assert main(["sync", "--list-collections"]) == 0
    payload = json.loads(capsys.readouterr().out)
    pairs = {(c["source"], c["collection"]) for c in payload["collections"]}
    assert pairs == {("x", "bookmarks"), ("wikipedia", "reading-lists")}


def test_list_collections_for_a_bare_source_is_an_honest_empty(scrolls_home, capsys):
    assert main(["sync", "youtube", "--list-collections"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"source": "youtube", "collections": []}


def test_a_collection_source_named_without_a_collection_points_at_it(
    scrolls_home, capsys
):
    """`sync x` used to fall through to the feed path as an unknown id."""
    assert main(["sync", "x"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert "scrolls sync x --collection bookmarks" in error
