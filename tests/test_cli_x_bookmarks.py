"""End-to-end tests for `scrolls sync x --bookmarks`.

Only the network is faked. Session resolution, pagination, parsing, and the
database insert all run for real, so these cover the on-ramp as a user meets
it rather than as three mocked units.
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
def x_session(monkeypatch):
    """Supply cookies via env so no test reaches for the Keychain."""
    monkeypatch.setenv("SCROLLS_X_AUTH_TOKEN", "AUTH")
    monkeypatch.setenv("SCROLLS_X_CT0", "CSRF")


def _page(tweet_ids, cursor=None):
    entries = [
        {
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
                                        "core": {
                                            "screen_name": "karpathy",
                                            "name": "Andrej Karpathy",
                                        }
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
        for tweet_id in tweet_ids
    ]
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


def test_sync_x_bookmarks_pulls_the_whole_collection(
    scrolls_home, x_session, fake_x, capsys
):
    fake_x([_page([1, 2], "C1"), _page([3])])

    exit_code = main(["sync", "x", "--bookmarks", "--browser", "env"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 3
    assert payload["skipped"] == 0
    assert payload["failed"] == 0
    assert payload["pages"] == 2
    assert payload["session"] == "env"

    stored = get_item(get_paths().db_path, "x:1")
    assert stored.source == "x"
    assert stored.stage == "fetched"
    assert stored.url == "https://x.com/karpathy/status/1"
    assert stored.author == "Andrej Karpathy (@karpathy)"
    assert stored.provenance["extraction_method"] == "x:graphql-internal"


def test_a_second_sync_skips_what_is_already_held(
    scrolls_home, x_session, fake_x, capsys
):
    """Re-syncing is cheap and never overwrites an existing item."""
    fake_x([_page([1, 2])])
    main(["sync", "x", "--bookmarks", "--browser", "env"])
    capsys.readouterr()

    fake_x([_page([1, 2, 3])])
    assert main(["sync", "x", "--bookmarks", "--browser", "env"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 1
    assert payload["skipped"] == 2


def test_limit_stops_early(scrolls_home, x_session, fake_x, capsys):
    fake_x([_page([1, 2, 3, 4], "C1")])
    main(["sync", "x", "--bookmarks", "--browser", "env", "--limit", "2"])
    assert json.loads(capsys.readouterr().out)["imported"] == 2


def test_bookmarks_flag_without_a_collection_source_is_rejected(scrolls_home, capsys):
    assert main(["sync", "--bookmarks"]) == 1
    assert "scrolls sync x --bookmarks" in json.loads(capsys.readouterr().err)["error"]


def test_a_missing_session_explains_what_to_set(scrolls_home, monkeypatch, capsys):
    monkeypatch.delenv("SCROLLS_X_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SCROLLS_X_CT0", raising=False)
    assert main(["sync", "x", "--bookmarks", "--browser", "env"]) == 1
    assert "SCROLLS_X_AUTH_TOKEN" in json.loads(capsys.readouterr().err)["error"]


def test_an_empty_collection_succeeds_with_nothing_imported(
    scrolls_home, x_session, fake_x, capsys
):
    fake_x([_page([])])
    assert main(["sync", "x", "--bookmarks", "--browser", "env"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 0
    assert "error" not in payload


class _FakeResponse:
    """Enough of an HTTP response for `_http_get_page` to read."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self):
        return self._body


def test_a_rotated_query_id_is_not_reported_as_an_empty_collection(
    scrolls_home, x_session, monkeypatch, capsys
):
    """The one wrong answer a custody tool must never give.

    Patched at urlopen rather than at `_http_get_page`, so the status-to-error
    mapping under test actually runs.
    """
    import urllib.error

    def rotated(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr("scrolls.x_graphql.urllib.request.urlopen", rotated)
    assert main(["sync", "x", "--bookmarks", "--browser", "env"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert "rotate" in error
    assert "not an empty bookmark collection" in error


def test_an_expired_session_is_reported_as_such(
    scrolls_home, x_session, monkeypatch, capsys
):
    import urllib.error

    def expired(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr("scrolls.x_graphql.urllib.request.urlopen", expired)
    assert main(["sync", "x", "--bookmarks", "--browser", "env"]) == 1
    assert "logged in" in json.loads(capsys.readouterr().err)["error"]


def test_a_partial_pull_keeps_what_it_captured(
    scrolls_home, x_session, monkeypatch, capsys
):
    """A pull that dies halfway still holds what it captured."""
    import urllib.error

    pages = [_page([1, 2], "C1")]

    def flaky(request, timeout=None):
        if pages:
            return _FakeResponse(pages.pop(0))
        raise urllib.error.HTTPError(request.full_url, 500, "Server Error", {}, None)

    monkeypatch.setattr("scrolls.x_graphql.urllib.request.urlopen", flaky)
    monkeypatch.setattr("scrolls.x_graphql.time.sleep", lambda _: None)

    exit_code = main(["sync", "x", "--bookmarks", "--browser", "env"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 2
    assert payload["error"] is not None
    assert exit_code == 1
    assert get_item(get_paths().db_path, "x:1") is not None


# --- the OAuth route -----------------------------------------------------


def _api_payload(ids, next_token=None):
    payload = {
        "data": [
            {
                "id": str(i),
                "text": f"post {i}",
                "created_at": "2026-06-01T15:34:00.000Z",
                "author_id": "u1",
            }
            for i in ids
        ],
        "includes": {
            "users": [{"id": "u1", "username": "karpathy", "name": "Andrej Karpathy"}]
        },
        "meta": {"result_count": len(ids)},
    }
    if next_token:
        payload["meta"]["next_token"] = next_token
    return payload


@pytest.fixture
def stored_grant(scrolls_home, monkeypatch):
    """A live OAuth grant on disk and a client id in the environment."""
    import time

    from scrolls.paths import get_paths
    from scrolls.x_oauth import TokenSet, save_tokens

    monkeypatch.setenv("SCROLLS_X_CLIENT_ID", "CID")
    save_tokens(
        get_paths().credentials_path,
        TokenSet(access_token="ACCESS", refresh_token="R", expires_at=time.time() + 3600),
    )


@pytest.fixture
def fake_x_api(monkeypatch):
    """Serve queued API v2 payloads instead of calling X."""

    def install(pages):
        queued = list(pages)

        def get(url, headers):
            if url.endswith("/users/me"):
                return {"data": {"id": "u1"}}
            return queued.pop(0)

        monkeypatch.setattr("scrolls.x_api._http_get", get)
        monkeypatch.setattr("scrolls.x_api.time.sleep", lambda _: None)

    return install


def test_the_oauth_route_pulls_the_collection_and_says_which_route_it_took(
    stored_grant, fake_x_api, capsys
):
    fake_x_api([_api_payload([1, 2], "T1"), _api_payload([3])])

    assert main(["sync", "x", "--bookmarks", "--auth", "oauth"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 3
    assert payload["session"] == "oauth"

    stored = get_item(get_paths().db_path, "x:1")
    assert stored.provenance["extraction_method"] == "x:api-v2"


def test_the_two_routes_dedupe_against_each_other(
    scrolls_home, x_session, stored_grant, fake_x, fake_x_api, capsys
):
    """The same bookmark pulled either way is one item, not two."""
    fake_x([_page([1, 2])])
    main(["sync", "x", "--bookmarks", "--browser", "env"])
    capsys.readouterr()

    fake_x_api([_api_payload([1, 2, 3])])
    assert main(["sync", "x", "--bookmarks", "--auth", "oauth"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 1
    assert payload["skipped"] == 2


def test_the_oauth_route_without_a_stored_grant_points_at_login(
    scrolls_home, monkeypatch, capsys
):
    monkeypatch.setenv("SCROLLS_X_CLIENT_ID", "CID")
    assert main(["sync", "x", "--bookmarks", "--auth", "oauth"]) == 1
    assert "scrolls x login" in json.loads(capsys.readouterr().err)["error"]


def test_the_oauth_route_without_a_client_id_says_how_to_get_one(
    scrolls_home, monkeypatch, capsys
):
    monkeypatch.delenv("SCROLLS_X_CLIENT_ID", raising=False)
    assert main(["sync", "x", "--bookmarks", "--auth", "oauth"]) == 1
    assert "developer.x.com" in json.loads(capsys.readouterr().err)["error"]


def test_the_browser_route_never_touches_the_credential_store(
    scrolls_home, x_session, fake_x, capsys
):
    """The free default must not require, or create, a stored secret."""
    fake_x([_page([1])])
    assert main(["sync", "x", "--bookmarks", "--browser", "env"]) == 0
    assert not get_paths().credentials_path.exists()


def test_logout_forgets_the_grant_and_is_idempotent(stored_grant, capsys):
    assert main(["x", "logout"]) == 0
    assert json.loads(capsys.readouterr().out) == {"forgotten": True}
    assert main(["x", "logout"]) == 0
    assert json.loads(capsys.readouterr().out) == {"forgotten": False}


def test_login_stores_the_grant_and_reports_it_refreshable(
    scrolls_home, monkeypatch, capsys
):
    from scrolls.x_oauth import TokenSet, load_tokens

    monkeypatch.setenv("SCROLLS_X_CLIENT_ID", "CID")
    monkeypatch.setattr(
        "scrolls.cli.run_login_flow",
        lambda **kw: TokenSet(
            access_token="A", refresh_token="R", scope="bookmark.read offline.access"
        ),
    )
    assert main(["x", "login"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["authorized"] is True
    assert payload["refreshable"] is True
    assert load_tokens(get_paths().credentials_path).access_token == "A"
