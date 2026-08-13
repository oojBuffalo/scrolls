"""X browser-session extraction (lineage:
`docs/inspiration/fieldtheory-cli-inspiration.md`).

The default X on-ramp borrows the session already sitting in the user's
browser rather than requiring a paid developer account. X's own web client
authenticates with two cookies — `auth_token` (the session) and `ct0` (the
CSRF token, echoed back in the `x-csrf-token` header) — so reading those two
values is the whole of "logging in".

Nothing here leaves the machine, and nothing is written: the cookie database
is copied before it is read, so a live browser profile is never locked or
mutated.

Chrome's macOS scheme is Chrome's, not ours:

- The AES key is `PBKDF2(keychain_password, 'saltysalt', 1003, 16, sha1)`.
- Values are `v10` + AES-128-CBC ciphertext under a sixteen-space IV.
- Cookie databases at schema version 24 and up prefix the plaintext with a
  32-byte SHA-256 of the host key, which is stripped after unpadding.

`SCROLLS_X_AUTH_TOKEN` / `SCROLLS_X_CT0` bypass all of it, for anyone who
would rather paste two cookies than grant Keychain access.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

CHROME_IV = b" " * 16
_CHROME_SALT = b"saltysalt"
_CHROME_ITERATIONS = 1003
_CHROME_KEY_LENGTH = 16
_DOMAIN_HASH_LENGTH = 32
_DOMAIN_HASH_MIN_DB_VERSION = 24

# Preference order: x.com is current, twitter.com is the legacy domain. Firefox
# stores hosts without the leading dot Chromium writes, so both spellings appear.
_X_HOSTS = (".x.com", "x.com", ".twitter.com", "twitter.com")
_REQUIRED_COOKIES = ("auth_token", "ct0")

AUTH_TOKEN_ENV = "SCROLLS_X_AUTH_TOKEN"
CT0_ENV = "SCROLLS_X_CT0"

_KEYCHAIN_SERVICE = "Chrome Safe Storage"
_KEYCHAIN_ACCOUNT = "Chrome"

_APP_SUPPORT = Path.home() / "Library" / "Application Support"


@dataclass(frozen=True)
class ChromiumBrowser:
    """One Chromium-family browser and where it keeps its secrets.

    Every fork uses Chrome's cookie scheme unchanged but encrypts under its
    own Keychain entry, so the only per-browser facts are the profile
    directory and the Safe Storage service name.

    Attributes:
        name: The `--browser` value that selects this browser.
        support_dir: Profile root, relative to ~/Library/Application Support.
        keychain_service: The macOS Keychain service holding the password.
        keychain_account: The Keychain account for that service.
    """

    name: str
    support_dir: str
    keychain_service: str
    keychain_account: str

    @property
    def profile_root(self) -> Path:
        """Absolute path to the directory holding this browser's profiles."""
        return _APP_SUPPORT / self.support_dir


CHROMIUM_BROWSERS: dict[str, ChromiumBrowser] = {
    browser.name: browser
    for browser in (
        ChromiumBrowser("chrome", "Google/Chrome", "Chrome Safe Storage", "Chrome"),
        ChromiumBrowser(
            "brave",
            "BraveSoftware/Brave-Browser",
            "Brave Safe Storage",
            "Brave",
        ),
        ChromiumBrowser("arc", "Arc/User Data", "Arc Safe Storage", "Arc"),
        ChromiumBrowser(
            "edge",
            "Microsoft Edge",
            "Microsoft Edge Safe Storage",
            "Microsoft Edge",
        ),
        ChromiumBrowser("vivaldi", "Vivaldi", "Vivaldi Safe Storage", "Vivaldi"),
        ChromiumBrowser("chromium", "Chromium", "Chromium Safe Storage", "Chromium"),
    )
}

FIREFOX_BROWSER = "firefox"
_FIREFOX_PROFILE_ROOT = _APP_SUPPORT / "Firefox" / "Profiles"


class XSessionError(Exception):
    """No usable X browser session could be read."""


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


def derive_chrome_key(password: str) -> bytes:
    """Derive Chrome's AES key from the Keychain password.

    Args:
        password: The 'Chrome Safe Storage' password from the macOS Keychain.

    Returns:
        The 16-byte AES key.
    """
    return hashlib.pbkdf2_hmac(
        "sha1",
        password.encode("utf-8"),
        _CHROME_SALT,
        _CHROME_ITERATIONS,
        dklen=_CHROME_KEY_LENGTH,
    )


def decrypt_chrome_value(encrypted: bytes, key: bytes, *, db_version: int = 0) -> str:
    """Decrypt one Chrome cookie value.

    Args:
        encrypted: The raw `encrypted_value` column.
        key: The key from `derive_chrome_key`.
        db_version: The cookie database schema version; at 24 and above a
            32-byte host-key hash prefixes the plaintext.

    Returns:
        The decrypted cookie value. Values without a `v10` prefix are already
        plaintext and are returned as-is.

    Raises:
        XSessionError: The value could not be decrypted with this key.
    """
    if not encrypted.startswith(b"v10"):
        return encrypted.decode("utf-8", "replace")

    try:
        decryptor = Cipher(algorithms.AES(key), modes.CBC(CHROME_IV)).decryptor()
        plain = decryptor.update(encrypted[3:]) + decryptor.finalize()
        plain = _unpad(plain)
        if db_version >= _DOMAIN_HASH_MIN_DB_VERSION and len(plain) > _DOMAIN_HASH_LENGTH:
            plain = plain[_DOMAIN_HASH_LENGTH:]
        return plain.decode("utf-8")
    except (ValueError, InvalidTag, UnicodeDecodeError) as exc:
        raise XSessionError(
            "could not decrypt the Chrome cookie — the Keychain password does "
            "not match this profile"
        ) from exc


def _unpad(plain: bytes) -> bytes:
    """Strip PKCS#7 padding, rejecting anything malformed."""
    if not plain:
        raise ValueError("empty plaintext")
    pad = plain[-1]
    if pad < 1 or pad > 16 or len(plain) < pad:
        raise ValueError("bad padding")
    if plain[-pad:] != bytes([pad]) * pad:
        raise ValueError("bad padding")
    return plain[:-pad]


def keychain_password(
    service: str = _KEYCHAIN_SERVICE, account: str = _KEYCHAIN_ACCOUNT
) -> str:
    """Read Chrome's Safe Storage password from the macOS Keychain.

    The user may see a Keychain authorization prompt the first time.

    Raises:
        XSessionError: The Keychain entry is absent or access was denied.
    """
    try:
        completed = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", service, "-a", account],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - platform
        raise XSessionError(f"could not run the macOS security tool: {exc}") from exc
    if completed.returncode != 0:
        raise XSessionError(
            f"no Keychain entry for {service!r} — open Chrome once, and allow "
            "Keychain access when prompted"
        )
    return completed.stdout.strip()


def read_chrome_session(db_path: Path, *, key: bytes, origin: str = "chrome") -> XSession:
    """Read the X session out of a Chromium-family cookie database.

    The database is copied to a temporary file before reading, so a running
    browser is neither locked nor modified.

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
    db_path = Path(db_path)
    if not db_path.is_file():
        raise XSessionError(f"no {origin} cookie database at {db_path}")

    with _readonly_copy(db_path) as copy:
        rows, db_version = _read_cookie_rows(copy)

    found = _pick_x_cookies(rows)
    if found is None:
        raise XSessionError(
            f"no complete X session in {origin} — open your browser, go to "
            "https://x.com, and make sure you are logged in"
        )
    return XSession(
        auth_token=decrypt_chrome_value(found["auth_token"], key, db_version=db_version),
        ct0=decrypt_chrome_value(found["ct0"], key, db_version=db_version),
        origin=origin,
    )


def _pick_x_cookies(rows: list[tuple]) -> dict | None:
    """Select `auth_token` and `ct0` from the most current X host present.

    Args:
        rows: (host, name, value) triples, values still encrypted for Chromium.

    Returns:
        A name-to-value mapping, or None when no single host carries both.
        Both cookies must come from the same host: mixing an `x.com` session
        with a stale `twitter.com` CSRF token yields a 403, not a session.
    """
    for host in _X_HOSTS:
        found = {
            name: value
            for host_key, name, value in rows
            if host_key == host and name in _REQUIRED_COOKIES
        }
        if all(name in found for name in _REQUIRED_COOKIES):
            return found
    return None


@contextmanager
def _readonly_copy(db_path: Path):
    """Yield a throwaway copy of a cookie database.

    Reading the original in place would lock a running browser's profile and
    risks writing a journal beside it. Copying first keeps this strictly
    read-only from the browser's point of view.
    """
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "cookies.db"
        try:
            shutil.copy2(db_path, copy)
        except OSError as exc:
            raise XSessionError(f"could not read {db_path}: {exc}") from exc
        yield copy


def read_firefox_session(db_path: Path) -> XSession:
    """Read the X session out of a Firefox cookie database.

    Firefox stores cookie values in the clear, so there is no key derivation
    and no Keychain prompt on this path.

    Args:
        db_path: Path to a profile's `cookies.sqlite`.

    Returns:
        The extracted XSession.

    Raises:
        XSessionError: The database is missing, unreadable, or holds no
            complete X session.
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        raise XSessionError(f"no Firefox cookie database at {db_path}")

    with _readonly_copy(db_path) as copy:
        conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        try:
            rows = list(conn.execute("SELECT host, name, value FROM moz_cookies"))
        except sqlite3.Error as exc:
            raise XSessionError(f"could not read cookies from {db_path}: {exc}") from exc
        finally:
            conn.close()

    found = _pick_x_cookies(rows)
    if found is None:
        raise XSessionError(
            "no complete X session in firefox — open your browser, go to "
            "https://x.com, and make sure you are logged in"
        )
    return XSession(
        auth_token=found["auth_token"], ct0=found["ct0"], origin=FIREFOX_BROWSER
    )


def chromium_cookie_dbs(profile_root: Path) -> list[Path]:
    """Every cookie database under a Chromium profile root.

    Chrome 96 and later keep the database at `<profile>/Network/Cookies`;
    older builds put it directly under the profile. `Default` sorts first
    because that is where a signed-in session usually lives.

    Args:
        profile_root: The browser's user-data directory.

    Returns:
        Cookie database paths, Default first, then the rest in name order.
    """
    profile_root = Path(profile_root)
    if not profile_root.is_dir():
        return []

    found = []
    for profile in sorted(
        (path for path in profile_root.iterdir() if path.is_dir()),
        key=lambda path: (path.name != "Default", path.name),
    ):
        for candidate in (profile / "Network" / "Cookies", profile / "Cookies"):
            if candidate.is_file():
                found.append(candidate)
                break
    return found


def firefox_cookie_dbs() -> list[Path]:
    """Every Firefox profile's cookie database, default-release profiles first."""
    if not _FIREFOX_PROFILE_ROOT.is_dir():
        return []
    return sorted(
        (
            path
            for path in _FIREFOX_PROFILE_ROOT.glob("*/cookies.sqlite")
            if path.is_file()
        ),
        key=lambda path: ("default" not in path.parent.name, path.parent.name),
    )


def _read_cookie_rows(db_path: Path) -> tuple[list[tuple], int]:
    """Return (host_key, name, encrypted_or_plain_value) rows and schema version."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        try:
            version_row = conn.execute(
                "SELECT value FROM meta WHERE key = 'version'"
            ).fetchone()
            db_version = int(version_row[0]) if version_row else 0
        except (sqlite3.Error, TypeError, ValueError):
            db_version = 0
        # SQLite tracks a storage class per value, not per column, and Chrome
        # writes ciphertext as TEXT. Without the cast, sqlite3 tries to UTF-8
        # decode it and raises before we see the bytes.
        rows = [
            (host_key, name, encrypted or (value or "").encode("utf-8"))
            for host_key, name, value, encrypted in conn.execute(
                "SELECT host_key, name, value, CAST(encrypted_value AS BLOB) "
                "FROM cookies"
            )
        ]
    except sqlite3.Error as exc:
        raise XSessionError(f"could not read cookies from {db_path}: {exc}") from exc
    finally:
        conn.close()
    return rows, db_version


def load_session_from_env() -> XSession | None:
    """Build a session from the cookie environment variables.

    Returns:
        The XSession, or None when neither variable is set.

    Raises:
        XSessionError: Only one of the pair is set — a half-configured
            session is a mistake worth naming, not a silent fallthrough.
    """
    auth_token = os.environ.get(AUTH_TOKEN_ENV)
    ct0 = os.environ.get(CT0_ENV)
    if not auth_token and not ct0:
        return None
    if not auth_token:
        raise XSessionError(f"{AUTH_TOKEN_ENV} is set but {CT0_ENV} is missing")
    if not ct0:
        raise XSessionError(f"{CT0_ENV} is missing but {AUTH_TOKEN_ENV} is set")
    return XSession(auth_token=auth_token, ct0=ct0, origin="env")


def chrome_cookie_db_path(profile: str = "Default") -> Path:
    """Where Chrome keeps its cookie database on macOS.

    Chrome 96 and later use `<profile>/Network/Cookies`; older builds keep it
    directly under the profile. The newer path wins when both exist.
    """
    base = CHROMIUM_BROWSERS["chrome"].profile_root / profile
    modern = base / "Network" / "Cookies"
    return modern if modern.is_file() else base / "Cookies"


BROWSER_CHOICES = ("auto", "env", *CHROMIUM_BROWSERS, FIREFOX_BROWSER)


def _load_chromium_session(browser: ChromiumBrowser) -> XSession:
    """Read the first profile of one Chromium browser that holds an X session.

    Raises:
        XSessionError: The browser is absent, its Keychain entry is
            unavailable, or no profile is signed in.
    """
    databases = chromium_cookie_dbs(browser.profile_root)
    if not databases:
        raise XSessionError(f"{browser.name} is not installed on this machine")

    key = derive_chrome_key(
        keychain_password(browser.keychain_service, browser.keychain_account)
    )
    last: XSessionError | None = None
    for db_path in databases:
        try:
            return read_chrome_session(db_path, key=key, origin=browser.name)
        except XSessionError as exc:
            last = exc
    raise last  # every profile failed; the last reason is as good as any


def _load_firefox_session() -> XSession:
    """Read the first Firefox profile that holds an X session.

    Raises:
        XSessionError: Firefox is absent or no profile is signed in.
    """
    databases = firefox_cookie_dbs()
    if not databases:
        raise XSessionError("firefox is not installed on this machine")
    last: XSessionError | None = None
    for db_path in databases:
        try:
            return read_firefox_session(db_path)
        except XSessionError as exc:
            last = exc
    raise last


def load_session(browser: str = "auto", *, profile: str | None = None) -> XSession:
    """Resolve an X session, preferring explicitly supplied cookies.

    Args:
        browser: 'auto' tries the environment, then every installed browser.
            Any single name pins one path, so a failure names the thing that
            actually failed rather than a generic "not found".
        profile: Pin one profile directory by name; None searches all of them.

    Returns:
        The resolved XSession.

    Raises:
        XSessionError: No session could be resolved by the requested path.
    """
    if browser in ("auto", "env"):
        session = load_session_from_env()
        if session is not None:
            return session
        if browser == "env":
            raise XSessionError(f"{AUTH_TOKEN_ENV} and {CT0_ENV} are not set")

    if browser in CHROMIUM_BROWSERS:
        chosen = CHROMIUM_BROWSERS[browser]
        if profile:
            return read_chrome_session(
                _pinned_db(chosen, profile),
                key=derive_chrome_key(
                    keychain_password(chosen.keychain_service, chosen.keychain_account)
                ),
                origin=chosen.name,
            )
        return _load_chromium_session(chosen)

    if browser == FIREFOX_BROWSER:
        return _load_firefox_session()

    if browser != "auto":
        raise XSessionError(
            f"unknown browser: {browser!r} — choose from {', '.join(BROWSER_CHOICES)}"
        )

    # Auto: try every browser and report the whole search, because "no session
    # found" is only actionable if the user can see where we looked.
    reasons = []
    for candidate in (*CHROMIUM_BROWSERS.values(), FIREFOX_BROWSER):
        try:
            if candidate == FIREFOX_BROWSER:
                return _load_firefox_session()
            return _load_chromium_session(candidate)
        except XSessionError as exc:
            name = candidate if isinstance(candidate, str) else candidate.name
            reasons.append(f"{name}: {exc}")

    raise XSessionError(
        "no X session found in any installed browser.\n  "
        + "\n  ".join(reasons)
        + f"\nAlternatively set {AUTH_TOKEN_ENV} and {CT0_ENV} directly."
    )


def _pinned_db(browser: ChromiumBrowser, profile: str) -> Path:
    """The cookie database for one named profile of one browser."""
    base = browser.profile_root / profile
    modern = base / "Network" / "Cookies"
    return modern if modern.is_file() else base / "Cookies"
