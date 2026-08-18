"""End-to-end tests for `scrolls sync wikipedia --reading-lists`.

Only the network is faked. Session resolution, list-and-entry pagination,
identity minting and the database insert all run for real, so these cover the
on-ramp as a user meets it rather than as three mocked units.
"""

import json

import pytest

from scrolls.cli import main
from scrolls.items import get_item
from scrolls.paths import get_paths


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


@pytest.fixture
def wiki_session(monkeypatch):
    """Supply cookies via env so no test reaches for the Keychain."""
    monkeypatch.setenv("SCROLLS_WIKIPEDIA_USER", "NerdBuffalo")
    monkeypatch.setenv("SCROLLS_WIKIPEDIA_SESSION", "SESSION")


def _lists(*lists):
    return {"query": {"readinglists": list(lists)}}


def _list(list_id, name, *, default=False):
    return {
        "id": list_id,
        "name": name,
        "default": default,
        "created": "2021-06-25T17:29:02Z",
        "updated": "2021-06-25T17:29:02Z",
        "size": 1,
    }


def _entries(entries, cursor=None):
    page = {"query": {"readinglistentries": entries}}
    if cursor:
        page["continue"] = {"rlecontinue": cursor, "continue": "-||"}
    return page


def _entry(entry_id, list_id, title, created="2022-08-14T05:43:34Z"):
    return {
        "id": entry_id,
        "listId": list_id,
        "project": "https://en.wikipedia.org",
        "title": title,
        "created": created,
        "updated": created,
    }


@pytest.fixture
def fake_wikipedia(monkeypatch):
    """Serve queued API responses instead of calling MediaWiki."""

    def install(pages):
        queued = list(pages)
        monkeypatch.setattr(
            "scrolls.wikipedia_lists.http.get_json",
            lambda url, headers=None: queued.pop(0),
        )

    return install


DEFAULT_AND_NAMED = _lists(_list(1, "default", default=True), _list(2, "$$$"))


def test_pulls_every_article_across_every_list(
    scrolls_home, wiki_session, fake_wikipedia, capsys
):
    fake_wikipedia(
        [
            DEFAULT_AND_NAMED,
            _entries(
                [_entry(10, 1, "AI-complete"), _entry(11, 2, "APL (programming language)")]
            ),
        ]
    )

    exit_code = main(["sync", "wikipedia", "--reading-lists", "--browser", "env"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 2
    assert payload["failed"] == 0
    assert payload["session"] == "env"
    assert payload["account"] == "NerdBuffalo"
    assert payload["lists"] == ["$$$", "default"]

    stored = get_item(get_paths().db_path, "wikipedia:en:AI-complete")
    assert stored.source == "wikipedia"
    # a collection indexes; the fetch adapter is what captures
    assert stored.stage == "detected"
    assert stored.url == "https://en.wikipedia.org/wiki/AI-complete"
    assert stored.saved_at == "2022-08-14T05:43:34+00:00"
    assert stored.extracted_text is None


def test_a_named_list_survives_as_a_tag(
    scrolls_home, wiki_session, fake_wikipedia, capsys
):
    fake_wikipedia([DEFAULT_AND_NAMED, _entries([_entry(11, 2, "Bayes' theorem")])])
    main(["sync", "wikipedia", "--reading-lists", "--browser", "env"])

    stored = get_item(get_paths().db_path, "wikipedia:en:Bayes'_theorem")
    assert stored.tags == ("$$$",)


def test_pagination_walks_past_the_first_page(
    scrolls_home, wiki_session, fake_wikipedia, capsys
):
    fake_wikipedia(
        [
            DEFAULT_AND_NAMED,
            _entries([_entry(10, 1, "One")], cursor="One|10"),
            _entries([_entry(11, 1, "Two")]),
        ]
    )

    assert main(["sync", "wikipedia", "--reading-lists", "--browser", "env"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 2
    assert payload["pages"] == 2


def test_a_pulled_article_dedupes_against_one_added_by_url(
    scrolls_home, wiki_session, fake_wikipedia, capsys
):
    """`scrolls add` then a pull converge on one item (ADR 0009 identity)."""
    main(["init"])
    main(["add", "https://en.wikipedia.org/wiki/APL_(programming_language)"])
    capsys.readouterr()

    fake_wikipedia(
        [DEFAULT_AND_NAMED, _entries([_entry(11, 1, "APL (programming language)")])]
    )
    assert main(["sync", "wikipedia", "--reading-lists", "--browser", "env"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 0
    assert payload["skipped"] == 1


def test_a_second_sync_skips_what_is_already_held(
    scrolls_home, wiki_session, fake_wikipedia, capsys
):
    fake_wikipedia([DEFAULT_AND_NAMED, _entries([_entry(10, 1, "One")])])
    main(["sync", "wikipedia", "--reading-lists", "--browser", "env"])
    capsys.readouterr()

    fake_wikipedia(
        [DEFAULT_AND_NAMED, _entries([_entry(10, 1, "One"), _entry(11, 1, "Two")])]
    )
    assert main(["sync", "wikipedia", "--reading-lists", "--browser", "env"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 1
    assert payload["skipped"] == 1


def test_an_empty_collection_reports_zero_without_failing(
    scrolls_home, wiki_session, fake_wikipedia, capsys
):
    fake_wikipedia([_lists()])
    assert main(["sync", "wikipedia", "--reading-lists", "--browser", "env"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 0
    assert payload["lists"] == []


def test_limit_stops_early(scrolls_home, wiki_session, fake_wikipedia, capsys):
    fake_wikipedia(
        [
            DEFAULT_AND_NAMED,
            _entries(
                [_entry(10, 1, "One"), _entry(11, 1, "Two"), _entry(12, 1, "Three")],
                cursor="x",
            ),
        ]
    )
    main(["sync", "wikipedia", "--reading-lists", "--browser", "env", "--limit", "2"])
    assert json.loads(capsys.readouterr().out)["imported"] == 2


def test_missing_credentials_fail_the_whole_run(scrolls_home, monkeypatch, capsys):
    """No silent partial import — and the error names what to set."""
    monkeypatch.delenv("SCROLLS_WIKIPEDIA_USER", raising=False)
    monkeypatch.delenv("SCROLLS_WIKIPEDIA_SESSION", raising=False)

    assert main(["sync", "wikipedia", "--reading-lists", "--browser", "env"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert "SCROLLS_WIKIPEDIA_USER" in error
    assert "SCROLLS_WIKIPEDIA_SESSION" in error


def test_a_logged_out_session_is_reported_not_read_as_empty(
    scrolls_home, wiki_session, fake_wikipedia, capsys
):
    fake_wikipedia([{"error": {"code": "notloggedin", "info": "You must be logged in."}}])

    assert main(["sync", "wikipedia", "--reading-lists", "--browser", "env"]) == 1
    assert "logged in" in json.loads(capsys.readouterr().err)["error"]


def test_reading_lists_flag_without_a_collection_source_is_rejected(
    scrolls_home, capsys
):
    assert main(["sync", "--reading-lists"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert "scrolls sync wikipedia --reading-lists" in error


def test_a_non_wikipedia_project_is_counted_as_a_failure(
    scrolls_home, wiki_session, fake_wikipedia, capsys
):
    """Commons and Wiktionary have no adapter here; that is said, not guessed."""
    fake_wikipedia(
        [
            DEFAULT_AND_NAMED,
            _entries(
                [
                    _entry(10, 1, "AI-complete"),
                    {
                        "id": 11,
                        "listId": 1,
                        "project": "https://en.wiktionary.org",
                        "title": "encyclopedia",
                        "created": "2022-08-14T05:43:34Z",
                        "updated": "2022-08-14T05:43:34Z",
                    },
                ]
            ),
        ]
    )

    assert main(["sync", "wikipedia", "--reading-lists", "--browser", "env"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 1
    assert payload["failed"] == 1
    assert payload["failures"][0]["project"] == "https://en.wiktionary.org"
