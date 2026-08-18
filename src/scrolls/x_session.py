"""X browser-session extraction (lineage:
`docs/inspiration/fieldtheory-cli-inspiration.md`).

The default X on-ramp borrows the session already sitting in the user's
browser rather than requiring a paid developer account. X's own web client
authenticates with two cookies — `auth_token` (the session) and `ct0` (the
CSRF token, echoed back in the `x-csrf-token` header) — so reading those two
values is the whole of "logging in".

Finding and decrypting those cookies is generic work and lives in
`browser_cookies.py`; what is X-specific is only which hosts to search, which
two cookie names to take, and the shape the rest of the X code wants them in.

`SCROLLS_X_AUTH_TOKEN` / `SCROLLS_X_CT0` bypass all of it, for anyone who
would rather paste two cookies than grant Keychain access.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scrolls.browser_cookies import (
    BROWSER_CHOICES,
    CHROME_IV,
    CHROMIUM_BROWSERS,
    FIREFOX_BROWSER,
    BrowserCookieError,
    ChromiumBrowser,
    CookieSpec,
    chromium_cookie_dbs,
    cookies_from_env,
    decrypt_chrome_value,
    derive_chrome_key,
    firefox_cookie_dbs,
    keychain_password,
    load_cookies,
    pinned_db,
    read_chromium_cookies,
    read_firefox_cookies,
)

__all__ = [
    "AUTH_TOKEN_ENV",
    "BROWSER_CHOICES",
    "CHROME_IV",
    "CHROMIUM_BROWSERS",
    "CT0_ENV",
    "FIREFOX_BROWSER",
    "ChromiumBrowser",
    "XSession",
    "XSessionError",
    "X_COOKIES",
    "chrome_cookie_db_path",
    "chromium_cookie_dbs",
    "decrypt_chrome_value",
    "derive_chrome_key",
    "firefox_cookie_dbs",
    "keychain_password",
    "load_session",
    "load_session_from_env",
    "read_chrome_session",
    "read_firefox_session",
]

AUTH_TOKEN_ENV = "SCROLLS_X_AUTH_TOKEN"
CT0_ENV = "SCROLLS_X_CT0"

# One error type covers "no usable browser session", whatever the service; the
# message says which one. Kept under the X name for the call sites that read
# better that way.
XSessionError = BrowserCookieError

# Preference order: x.com is current, twitter.com is the legacy domain. Firefox
# stores hosts without the leading dot Chromium writes, so both spellings appear.
X_COOKIES = CookieSpec(
    service="X",
    hosts=(".x.com", "x.com", ".twitter.com", "twitter.com"),
    required=("auth_token", "ct0"),
    login_url="https://x.com",
    env_vars=(("auth_token", AUTH_TOKEN_ENV), ("ct0", CT0_ENV)),
)


@dataclass(frozen=True)
class XSession:
    """The two cookies X's web client authenticates with.

    Attributes:
        auth_token: The `auth_token` cookie — the session itself.
        ct0: The `ct0` cookie, echoed back as the `x-csrf-token` header.
        origin: Where the session came from ('chrome', 'firefox', 'env'),
            recorded in provenance so a capture's path is auditable.
    """

    auth_token: str
    ct0: str
    origin: str

    @property
    def cookie_header(self) -> str:
        """The Cookie header X expects."""
        return f"auth_token={self.auth_token}; ct0={self.ct0}"

    @property
    def csrf_token(self) -> str:
        """The x-csrf-token value, which X requires to equal `ct0`."""
        return self.ct0

    def __repr__(self) -> str:
        """Redacted: a session must not leak into tracebacks or debug logs."""
        return f"XSession(origin={self.origin!r}, auth_token=<redacted>, ct0=<redacted>)"


def _as_session(cookies) -> XSession:
    """Turn generic browser cookies into the X-shaped session."""
    return XSession(
        auth_token=cookies.values["auth_token"],
        ct0=cookies.values["ct0"],
        origin=cookies.origin,
    )


def read_chrome_session(db_path: Path, *, key: bytes, origin: str = "chrome") -> XSession:
    """Read the X session out of a Chromium-family cookie database.

    Args:
        db_path: Path to the browser's `Cookies` SQLite database.
        key: The key from `derive_chrome_key`.
        origin: Which browser this is, recorded on the session.

    Returns:
        The extracted XSession.

    Raises:
        XSessionError: The database is missing, unreadable, or holds no
            complete X session.
    """
    return _as_session(
        read_chromium_cookies(db_path, key=key, spec=X_COOKIES, origin=origin)
    )


def read_firefox_session(db_path: Path) -> XSession:
    """Read the X session out of a Firefox cookie database.

    Args:
        db_path: Path to a profile's `cookies.sqlite`.

    Returns:
        The extracted XSession.

    Raises:
        XSessionError: The database is missing, unreadable, or holds no
            complete X session.
    """
    return _as_session(read_firefox_cookies(db_path, spec=X_COOKIES))


def load_session_from_env() -> XSession | None:
    """Build a session from the cookie environment variables.

    Returns:
        The XSession, or None when neither variable is set.

    Raises:
        XSessionError: Only one of the pair is set — a half-configured
            session is a mistake worth naming, not a silent fallthrough.
    """
    cookies = cookies_from_env(X_COOKIES)
    return None if cookies is None else _as_session(cookies)


def chrome_cookie_db_path(profile: str = "Default") -> Path:
    """Where Chrome keeps its cookie database on macOS.

    Chrome 96 and later use `<profile>/Network/Cookies`; older builds keep it
    directly under the profile. The newer path wins when both exist.
    """
    return pinned_db(CHROMIUM_BROWSERS["chrome"], profile)


def load_session(browser: str = "auto", *, profile: str | None = None) -> XSession:
    """Resolve an X session, preferring explicitly supplied cookies.

    Args:
        browser: 'auto' tries the environment, then every installed browser.
        profile: Pin one profile directory by name; None searches all of them.

    Returns:
        The resolved XSession.

    Raises:
        XSessionError: No session could be resolved by the requested path.
    """
    return _as_session(load_cookies(X_COOKIES, browser, profile=profile))
