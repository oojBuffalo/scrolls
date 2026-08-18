"""X OAuth 2.0 + PKCE — the official, opt-in fallback (ADR 0108).

The default X on-ramp borrows the session already in the user's browser
(`x_session.py`). This is the other path: X's documented OAuth flow, for
anyone who would rather hold a developer app than let Scrolls read a cookie
database.

It is a *fallback*, not the default, for two honest reasons. It needs an app
the user registers themselves, and X's bookmark reads are billed per resource
since the free tier closed to new signups. The cookie path costs nothing.

What makes this path different from every other credential in the codebase is
that it **writes**. X rotates the refresh token on every use, so a store that
cannot be updated locks the user out after one refresh. Hence the credential
file, at 0600, rather than an environment variable.

UNVERIFIED AGAINST LIVE X, AND EXPECTED TO STAY THAT WAY
--------------------------------------------------------
No request in this module has ever reached X. Everything here is exercised
only by `tests/test_x_oauth.py`, which injects the network and the browser, so
the tests prove the logic is self-consistent — PKCE is really S256, a rotated
refresh token is really persisted, the store is really 0600 — and prove
nothing about whether X accepts any of it.

Verifying it requires a registered X developer app on a paid plan. The
maintainer deliberately does not hold one, so this will not be verified here.
That is a considered tradeoff, not an oversight: the cookie default in
`x_session.py` / `x_graphql.py` is verified live, costs nothing, and is what
`scrolls sync x --bookmarks` uses unless you pass `--auth oauth`.

If you have a developer app and this path misbehaves, assume the bug is here
rather than in your setup. The likeliest failure points, in order: the
authorize/token URLs or scope strings drifting from X's current docs, the
refresh-rotation contract, and the callback handling. Fixes are welcome —
please amend this banner to record what you confirmed and when.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable

AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"

# offline.access is what makes X issue a refresh token at all; without it the
# user re-authorizes by hand every two hours.
SCOPES = ("tweet.read", "users.read", "bookmark.read", "offline.access")

CLIENT_ID_ENV = "SCROLLS_X_CLIENT_ID"

_STORE_KEY = "x"
_TIMEOUT_SECONDS = 30
# Refresh this far ahead of expiry so a token cannot die mid-pagination.
_EXPIRY_MARGIN_SECONDS = 60
_VERIFIER_BYTES = 64  # → 86 url-safe chars, inside RFC 7636's 43-128


class XOAuthError(Exception):
    """The OAuth path could not produce a usable access token."""


@dataclass(frozen=True)
class TokenSet:
    """One X OAuth grant.

    Attributes:
        access_token: The bearer token for API calls.
        refresh_token: The rotating long-lived credential, when the grant
            included `offline.access`.
        expires_at: Unix time the access token stops working.
        scope: The space-separated scopes X actually granted.
    """

    access_token: str
    refresh_token: str | None = None
    expires_at: float = 0.0
    scope: str = ""

    @property
    def is_live(self) -> bool:
        """Whether the access token is still usable with margin to spare."""
        return time.time() + _EXPIRY_MARGIN_SECONDS < self.expires_at

    def __repr__(self) -> str:
        """Redacted: tokens must not leak into tracebacks or debug logs."""
        return (
            f"TokenSet(expires_at={self.expires_at!r}, scope={self.scope!r}, "
            "access_token=<redacted>, refresh_token=<redacted>)"
        )


Poster = Callable[[str, dict, dict], dict]


def generate_pkce() -> tuple[str, str]:
    """Make a PKCE verifier and its S256 challenge.

    Returns:
        (verifier, challenge). The verifier stays local until the token
        exchange; only the challenge travels with the authorization request,
        which is the whole point of PKCE.
    """
    verifier = (
        base64.urlsafe_b64encode(secrets.token_bytes(_VERIFIER_BYTES))
        .decode("ascii")
        .rstrip("=")
    )
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    return verifier, challenge


def build_authorize_url(
    *, client_id: str, redirect_uri: str, challenge: str, state: str
) -> str:
    """The URL the user opens to grant access.

    Args:
        client_id: The registered app's client id.
        redirect_uri: Must match the app registration exactly.
        challenge: The S256 challenge from `generate_pkce`.
        state: Random value echoed back, checked to reject a forged callback.

    Returns:
        The full authorization URL.
    """
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(SCOPES),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def exchange_code(
    *,
    code: str,
    verifier: str,
    client_id: str,
    redirect_uri: str,
    post: Poster | None = None,
) -> TokenSet:
    """Trade an authorization code for tokens.

    Args:
        code: The `code` parameter X sent to the callback.
        verifier: The PKCE verifier held back from the authorization request.
        client_id: The registered app's client id.
        redirect_uri: The same URI sent to authorize.
        post: Injected form poster, for tests.

    Returns:
        The granted TokenSet.

    Raises:
        XOAuthError: X rejected the exchange.

    Note:
        Unverified against live X — see the module docstring. The form below
        matches X's documented exchange, but no real code has been traded.
    """
    payload = (post or _post_form)(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "client_id": client_id,
        },
        {"content-type": "application/x-www-form-urlencoded"},
    )
    return _token_set_from(payload)


def refresh_tokens(
    tokens: TokenSet, *, client_id: str, post: Poster | None = None
) -> TokenSet:
    """Exchange a refresh token for a fresh grant.

    X rotates the refresh token on every use, so the returned set — not the
    one passed in — is what must be persisted.

    Args:
        tokens: The stored grant.
        client_id: The registered app's client id.
        post: Injected form poster, for tests.

    Returns:
        The rotated TokenSet.

    Raises:
        XOAuthError: There is no refresh token, or X rejected the refresh.

    Note:
        Unverified against live X — see the module docstring. The rotation
        contract is the risky part: if X ever stops returning a new refresh
        token, or invalidates the old one before the write lands, the user is
        locked out and must run `scrolls x login` again.
    """
    if not tokens.refresh_token:
        raise XOAuthError(
            "the stored X grant has no refresh token — authorize again with "
            "`scrolls x login`"
        )
    payload = (post or _post_form)(
        TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
            "client_id": client_id,
        },
        {"content-type": "application/x-www-form-urlencoded"},
    )
    # A response that omits refresh_token leaves the old one valid; dropping
    # it here would strand the next run with nothing to refresh from.
    return _token_set_from(payload, fallback_refresh=tokens.refresh_token)


def _token_set_from(payload: dict, *, fallback_refresh: str | None = None) -> TokenSet:
    """Build a TokenSet from X's token response."""
    access_token = payload.get("access_token")
    if not access_token:
        raise XOAuthError(f"X returned no access token: {payload!r}")
    try:
        expires_in = float(payload.get("expires_in", 0))
    except (TypeError, ValueError):
        expires_in = 0.0
    return TokenSet(
        access_token=access_token,
        refresh_token=payload.get("refresh_token") or fallback_refresh,
        expires_at=time.time() + expires_in,
        scope=payload.get("scope", ""),
    )


def _post_form(url: str, form: dict, headers: dict) -> dict:
    """POST a form to X's token endpoint and decode the JSON reply.

    Unverified against live X — see the module docstring. This is the only
    function here that opens a socket, so it is where a documentation-vs-reality
    mismatch would first surface.
    """
    request = urllib.request.Request(
        url, data=urllib.parse.urlencode(form).encode("ascii"), headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:  # pragma: no cover - body already consumed
            pass
        raise XOAuthError(f"X token request failed with HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise XOAuthError(f"X token request failed: {exc}") from exc


# --- the credential store ------------------------------------------------


def load_tokens(path: Path) -> TokenSet | None:
    """Read the stored X grant.

    Args:
        path: The credential store.

    Returns:
        The stored TokenSet, or None when nothing is stored yet.

    Raises:
        XOAuthError: The store exists but cannot be read.
    """
    path = Path(path)
    if not path.is_file():
        return None
    try:
        stored = json.loads(path.read_text(encoding="utf-8")).get(_STORE_KEY)
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        raise XOAuthError(f"could not read the credential store at {path}: {exc}") from exc
    if not stored:
        return None
    return TokenSet(
        access_token=stored.get("access_token", ""),
        refresh_token=stored.get("refresh_token"),
        expires_at=float(stored.get("expires_at", 0)),
        scope=stored.get("scope", ""),
    )


def save_tokens(path: Path, tokens: TokenSet) -> None:
    """Write the X grant to the credential store at 0600.

    Other services' entries are preserved, and the file is created with
    owner-only permissions from the start rather than chmod'ed afterwards,
    so the secret is never briefly world-readable.

    Args:
        path: The credential store.
        tokens: The grant to persist.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    store = {}
    if path.is_file():
        try:
            store = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            store = {}
    store[_STORE_KEY] = {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "expires_at": tokens.expires_at,
        "scope": tokens.scope,
    }

    _write_store(path, store)


def _write_store(path: Path, store: dict) -> None:
    """Write the credential store at 0600.

    Created with owner-only permissions from the start rather than chmod'ed
    afterwards, so a secret is never briefly world-readable.
    """
    body = json.dumps(store, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, body.encode("utf-8"))
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)  # an existing file keeps its old mode without this


def forget_tokens(path: Path) -> bool:
    """Drop the stored X grant, leaving other services' entries intact.

    Args:
        path: The credential store.

    Returns:
        Whether there was an X grant to forget.
    """
    path = Path(path)
    if not path.is_file():
        return False
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if store.pop(_STORE_KEY, None) is None:
        return False
    _write_store(path, store)
    return True


def resolve_access_token(
    path: Path, *, client_id: str, post: Poster | None = None
) -> str:
    """Return a usable access token, refreshing and re-persisting if needed.

    Args:
        path: The credential store.
        client_id: The registered app's client id.
        post: Injected form poster, for tests.

    Returns:
        A live access token.

    Raises:
        XOAuthError: Nothing is stored, or the refresh failed.
    """
    tokens = load_tokens(path)
    if tokens is None:
        raise XOAuthError(
            "no stored X credentials — authorize once with `scrolls x login`"
        )
    if tokens.is_live:
        return tokens.access_token

    rotated = refresh_tokens(tokens, client_id=client_id, post=post)
    save_tokens(path, rotated)
    return rotated.access_token


def client_id_from_env() -> str:
    """The registered app's client id.

    Raises:
        XOAuthError: The variable is not set.
    """
    client_id = os.environ.get(CLIENT_ID_ENV)
    if not client_id:
        raise XOAuthError(
            f"{CLIENT_ID_ENV} is not set — register an app at "
            "developer.x.com, enable OAuth 2.0 with a native/public client, "
            f"and export its client id as {CLIENT_ID_ENV}"
        )
    return client_id


# --- the loopback authorization flow -------------------------------------

REDIRECT_HOST = "127.0.0.1"
REDIRECT_PATH = "/callback"
_LOGIN_TIMEOUT_SECONDS = 300

_DONE_PAGE = (
    "<!doctype html><meta charset=utf-8><title>Scrolls</title>"
    "<body style='font:16px system-ui;padding:3rem'>"
    "<h1>{heading}</h1><p>{detail}</p>"
)


class _CallbackHandler(BaseHTTPRequestHandler):
    """Catches X's single redirect back to the loopback address."""

    result: dict = {}

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != REDIRECT_PATH:
            self.send_error(404)
            return
        query = urllib.parse.parse_qs(parsed.query)
        type(self).result = {
            key: value[0] for key, value in query.items() if value
        }
        ok = "code" in type(self).result
        body = _DONE_PAGE.format(
            heading="Authorized" if ok else "Authorization failed",
            detail=(
                "You can close this tab and return to the terminal."
                if ok
                else type(self).result.get("error_description")
                or type(self).result.get("error", "X sent no authorization code.")
            ),
        )
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args) -> None:
        """Silence the default stderr access log; the CLI speaks for itself."""


def run_login_flow(
    *,
    client_id: str,
    port: int = 0,
    open_browser: Callable[[str], object] | None = None,
    announce: Callable[[str], None] | None = None,
    timeout: float = _LOGIN_TIMEOUT_SECONDS,
) -> TokenSet:
    """Run the browser authorization once and return the granted tokens.

    A loopback redirect is used rather than a pasted code: X delivers the
    authorization code to a local one-shot HTTP server, so the code never
    passes through a clipboard or a terminal scrollback.

    Args:
        client_id: The registered app's client id.
        port: Loopback port; 0 picks a free one. X requires the redirect URI
            to match the app registration exactly, so a registered fixed port
            must be passed here.
        open_browser: Injected browser opener, for tests.
        announce: Injected reporter for the URL, so a user on a headless box
            can open it by hand.
        timeout: Seconds to wait for the redirect.

    Returns:
        The granted TokenSet.

    Raises:
        XOAuthError: The user denied access, the callback was forged, or no
            redirect arrived in time.

    Note:
        Unverified against live X — see the module docstring. The tests drive
        this loop by calling the loopback server themselves, so the server,
        the state check and the timeout are all exercised; what has never
        happened is X redirecting to it. A real app registration must list
        this exact redirect URI, which is why `port` exists.
    """
    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(24)

    _CallbackHandler.result = {}
    server = HTTPServer((REDIRECT_HOST, port), _CallbackHandler)
    server.timeout = timeout
    try:
        redirect_uri = f"http://{REDIRECT_HOST}:{server.server_port}{REDIRECT_PATH}"
        url = build_authorize_url(
            client_id=client_id,
            redirect_uri=redirect_uri,
            challenge=challenge,
            state=state,
        )
        if announce:
            announce(url)
        (open_browser or webbrowser.open)(url)
        server.handle_request()
    finally:
        server.server_close()

    result = _CallbackHandler.result
    if not result:
        raise XOAuthError(f"no authorization redirect arrived within {timeout:g}s")
    if "error" in result:
        raise XOAuthError(
            "X denied the authorization: "
            + (result.get("error_description") or result["error"])
        )
    # Constant-time compare: the state is the only thing standing between a
    # forged callback and an adopted grant.
    if not secrets.compare_digest(result.get("state", ""), state):
        raise XOAuthError("the authorization callback did not match this request")
    if "code" not in result:
        raise XOAuthError("the authorization callback carried no code")

    return exchange_code(
        code=result["code"],
        verifier=verifier,
        client_id=client_id,
        redirect_uri=redirect_uri,
    )
