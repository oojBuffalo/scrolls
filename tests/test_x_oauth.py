"""Tests for the X OAuth 2.0 + PKCE fallback.

The network and the browser are injected, so nothing here opens a window or
calls X. What is under test is the part that goes wrong quietly: PKCE
correctness, refresh-token rotation, and the file mode on a stored secret.
"""

import json
import stat
import time
from urllib.parse import parse_qs, urlparse

import pytest

from scrolls.x_oauth import (
    TOKEN_URL,
    XOAuthError,
    TokenSet,
    build_authorize_url,
    exchange_code,
    generate_pkce,
    load_tokens,
    refresh_tokens,
    resolve_access_token,
    save_tokens,
)


def _tokens(**overrides):
    base = dict(
        access_token="ACCESS",
        refresh_token="REFRESH",
        expires_at=time.time() + 3600,
        scope="tweet.read users.read bookmark.read offline.access",
    )
    base.update(overrides)
    return TokenSet(**base)


# --- PKCE ----------------------------------------------------------------


def test_pkce_challenge_is_the_sha256_of_the_verifier():
    """S256, not 'plain' — a plain challenge offers no protection at all."""
    import base64
    import hashlib

    verifier, challenge = generate_pkce()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    assert challenge == expected


def test_pkce_verifiers_are_unpredictable_and_long_enough():
    """RFC 7636 requires 43-128 characters, from a CSPRNG."""
    verifiers = {generate_pkce()[0] for _ in range(20)}
    assert len(verifiers) == 20
    assert all(43 <= len(v) <= 128 for v in verifiers)


def test_pkce_output_is_url_safe_and_unpadded():
    verifier, challenge = generate_pkce()
    assert "=" not in challenge and "+" not in challenge and "/" not in challenge
    assert "=" not in verifier


# --- the authorization request -------------------------------------------


def test_authorize_url_carries_pkce_and_the_scopes_bookmarks_need():
    url = build_authorize_url(
        client_id="CID", redirect_uri="http://127.0.0.1:9000/callback",
        challenge="CHALLENGE", state="STATE",
    )
    query = parse_qs(urlparse(url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == ["CHALLENGE"]
    assert query["state"] == ["STATE"]
    assert query["response_type"] == ["code"]
    scopes = query["scope"][0].split()
    assert "bookmark.read" in scopes
    # Without offline.access X issues no refresh token and the user
    # re-authorizes by hand every two hours.
    assert "offline.access" in scopes


def test_authorize_url_points_at_x_not_twitter():
    assert urlparse(build_authorize_url(
        client_id="C", redirect_uri="R", challenge="H", state="S"
    )).netloc.endswith("x.com")


# --- the token exchange --------------------------------------------------


class _FakePoster:
    """Records the form it was posted and returns a queued response."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, form, headers):
        self.calls.append((url, form, headers))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_exchange_sends_the_verifier_and_returns_a_token_set():
    post = _FakePoster(
        {
            "access_token": "ACCESS",
            "refresh_token": "REFRESH",
            "expires_in": 7200,
            "scope": "bookmark.read offline.access",
        }
    )
    tokens = exchange_code(
        code="CODE", verifier="VERIFIER", client_id="CID",
        redirect_uri="REDIRECT", post=post,
    )
    url, form, _ = post.calls[0]
    assert url == TOKEN_URL
    assert form["code_verifier"] == "VERIFIER"
    assert form["grant_type"] == "authorization_code"
    assert tokens.access_token == "ACCESS"
    assert tokens.refresh_token == "REFRESH"
    assert tokens.expires_at > time.time()


def test_a_refresh_rotates_the_stored_refresh_token():
    """X returns a NEW refresh token; keeping the old one locks the user out."""
    post = _FakePoster(
        {"access_token": "A2", "refresh_token": "R2", "expires_in": 7200}
    )
    rotated = refresh_tokens(_tokens(), client_id="CID", post=post)
    assert rotated.refresh_token == "R2"
    assert rotated.access_token == "A2"


def test_a_refresh_response_without_a_new_token_keeps_the_old_one():
    post = _FakePoster({"access_token": "A2", "expires_in": 7200})
    assert refresh_tokens(_tokens(), client_id="CID", post=post).refresh_token == "REFRESH"


def test_refreshing_without_a_refresh_token_says_to_authorize_again():
    with pytest.raises(XOAuthError, match="scrolls x login"):
        refresh_tokens(_tokens(refresh_token=None), client_id="CID", post=_FakePoster())


# --- the token store -----------------------------------------------------


def test_stored_credentials_are_not_world_readable(tmp_path):
    """A refresh token is a long-lived credential in a plain file."""
    path = tmp_path / "credentials.json"
    save_tokens(path, _tokens())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_tokens_round_trip_through_the_store(tmp_path):
    path = tmp_path / "credentials.json"
    save_tokens(path, _tokens(access_token="A", refresh_token="R"))
    loaded = load_tokens(path)
    assert (loaded.access_token, loaded.refresh_token) == ("A", "R")


def test_saving_preserves_other_services_in_the_store(tmp_path):
    """The store is shared; writing X credentials must not drop the rest."""
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"somewhere-else": {"token": "KEEP"}}))
    save_tokens(path, _tokens())
    assert json.loads(path.read_text())["somewhere-else"] == {"token": "KEEP"}


def test_loading_from_an_absent_store_is_none_not_an_error(tmp_path):
    assert load_tokens(tmp_path / "nope.json") is None


def test_loading_a_corrupt_store_says_so_rather_than_crashing(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text("{not json")
    with pytest.raises(XOAuthError, match="could not read"):
        load_tokens(path)


# --- resolving a usable access token -------------------------------------


def test_a_live_token_is_used_without_calling_x(tmp_path):
    path = tmp_path / "credentials.json"
    save_tokens(path, _tokens(access_token="LIVE"))
    post = _FakePoster()
    assert resolve_access_token(path, client_id="CID", post=post) == "LIVE"
    assert post.calls == []


def test_an_expired_token_is_refreshed_and_the_rotation_persisted(tmp_path):
    """The rotated refresh token must reach disk or the next run cannot refresh."""
    path = tmp_path / "credentials.json"
    save_tokens(path, _tokens(access_token="OLD", expires_at=time.time() - 10))
    post = _FakePoster(
        {"access_token": "NEW", "refresh_token": "ROTATED", "expires_in": 7200}
    )
    assert resolve_access_token(path, client_id="CID", post=post) == "NEW"
    assert load_tokens(path).refresh_token == "ROTATED"


def test_a_token_expiring_imminently_is_refreshed_early(tmp_path):
    """A token with seconds left would expire mid-pagination."""
    path = tmp_path / "credentials.json"
    save_tokens(path, _tokens(access_token="OLD", expires_at=time.time() + 5))
    post = _FakePoster({"access_token": "NEW", "expires_in": 7200})
    assert resolve_access_token(path, client_id="CID", post=post) == "NEW"


def test_no_stored_credentials_points_at_the_login_command(tmp_path):
    with pytest.raises(XOAuthError, match="scrolls x login"):
        resolve_access_token(tmp_path / "absent.json", client_id="CID")


# --- the loopback authorization flow -------------------------------------


def _drive_callback(query):
    """Return an `open_browser` that calls back to the loopback server."""
    import threading
    import urllib.request as request

    def open_browser(url):
        redirect = parse_qs(urlparse(url).query)["redirect_uri"][0]

        def hit():
            try:
                request.urlopen(f"{redirect}?{query(url)}", timeout=5).read()
            except Exception:  # the assertion belongs to the test, not here
                pass

        threading.Thread(target=hit, daemon=True).start()

    return open_browser


def test_login_captures_the_code_and_exchanges_it(monkeypatch):
    from scrolls import x_oauth

    monkeypatch.setattr(
        x_oauth,
        "exchange_code",
        lambda **kw: TokenSet(access_token="ACCESS", refresh_token=kw["code"]),
    )
    opener = _drive_callback(
        lambda url: "code=THECODE&state="
        + parse_qs(urlparse(url).query)["state"][0]
    )
    tokens = x_oauth.run_login_flow(client_id="CID", open_browser=opener, timeout=10)
    assert tokens.access_token == "ACCESS"
    assert tokens.refresh_token == "THECODE"  # the captured code reached exchange


def test_a_forged_callback_state_is_rejected():
    from scrolls import x_oauth

    opener = _drive_callback(lambda url: "code=THECODE&state=WRONG")
    with pytest.raises(XOAuthError, match="did not match this request"):
        x_oauth.run_login_flow(client_id="CID", open_browser=opener, timeout=10)


def test_a_denied_authorization_reports_x_s_reason():
    from scrolls import x_oauth

    opener = _drive_callback(
        lambda url: "error=access_denied&error_description=User+said+no"
    )
    with pytest.raises(XOAuthError, match="User said no"):
        x_oauth.run_login_flow(client_id="CID", open_browser=opener, timeout=10)


def test_the_url_is_announced_so_a_headless_user_can_open_it_by_hand():
    from scrolls import x_oauth

    announced = []
    opener = _drive_callback(lambda url: "error=access_denied")
    with pytest.raises(XOAuthError):
        x_oauth.run_login_flow(
            client_id="CID", open_browser=opener, announce=announced.append, timeout=10
        )
    assert announced and announced[0].startswith("https://x.com/i/oauth2/authorize?")


def test_the_redirect_uri_is_loopback_only():
    """A non-loopback redirect would send the code across the network."""
    from scrolls import x_oauth

    seen = []

    def opener(url):
        seen.append(parse_qs(urlparse(url).query)["redirect_uri"][0])
        raise SystemExit  # stop the flow; the URL is all this test needs

    with pytest.raises(SystemExit):
        x_oauth.run_login_flow(client_id="CID", open_browser=opener, timeout=1)
    assert seen[0].startswith("http://127.0.0.1:")
    assert seen[0].endswith("/callback")
