"""Reading a logged-in session out of the user's own browser.

Some collections are only reachable as the account that saved them, and the
account is already signed in three inches away — in the browser. Borrowing
that session is what lets `scrolls sync x --bookmarks` and
`scrolls sync wikipedia --reading-lists` work with no developer account, no
API key and no bill.

This module is the part that is the same for every such service: find the
installed browsers, find their cookie databases, decrypt what needs
decrypting, and hand back the named cookies for one host. What differs per
service — which hosts, which cookie names, where to send the user when they
turn out to be logged out — is a `CookieSpec` the caller supplies.

Nothing here leaves the machine, and nothing is written: the cookie database
is copied before it is read, so a live browser profile is never locked or
mutated.

Chrome's macOS scheme is Chrome's, not ours:

- The AES key is `PBKDF2(keychain_password, 'saltysalt', 1003, 16, sha1)`.
- Values are `v10` + AES-128-CBC ciphertext under a sixteen-space IV.
- Cookie databases at schema version 24 and up prefix the plaintext with a
  32-byte SHA-256 of the host key, which is stripped after unpadding.

Every Chromium fork uses that scheme unchanged but encrypts under its own
Keychain entry, so the only per-browser facts are a profile directory and a
Safe Storage service name. Firefox stores cookie values in the clear, so that
path never prompts for Keychain access.
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

_KEYCHAIN_SERVICE = "Chrome Safe Storage"
_KEYCHAIN_ACCOUNT = "Chrome"

_APP_SUPPORT = Path.home() / "Library" / "Application Support"


class BrowserCookieError(Exception):
    """No usable browser session could be read."""


@dataclass(frozen=True)
class ChromiumBrowser:
    """One Chromium-family browser and where it keeps its secrets.

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

BROWSER_CHOICES = ("auto", "env", *CHROMIUM_BROWSERS, FIREFOX_BROWSER)


@dataclass(frozen=True)
class CookieSpec:
    """What one service needs out of a browser.

    Attributes:
        service: Human name of the service, used in every error message.
        hosts: Cookie hosts in preference order. Chromium writes a leading
            dot on domain cookies and Firefox does not, so both spellings
            usually belong here.
        required: Cookie names that must all be present. They must come from
            a single host: mixing a current session with a stale token from
            the service's legacy domain yields a rejection, not a session.
        login_url: Where to send a logged-out user, named in the error.
        env_vars: Optional (cookie name, environment variable) pairs that
            bypass the browser entirely.
    """

    service: str
    hosts: tuple[str, ...]
    required: tuple[str, ...]
    login_url: str
    env_vars: tuple[tuple[str, str], ...] = ()

    @property
    def env_names(self) -> tuple[str, ...]:
        """Just the environment variable names, in declaration order."""
        return tuple(env for _, env in self.env_vars)


@dataclass(frozen=True)
class BrowserCookies:
    """Cookies read for one service, and where they came from.

    Attributes:
        values: Cookie name to value, covering exactly the spec's `required`.
        origin: Which browser this came from ('brave', 'firefox', 'env'),
            recorded in provenance so a capture's path is auditable.
    """

    values: dict[str, str]
    origin: str

    def header(self) -> str:
        """The Cookie header carrying these values."""
        return "; ".join(f"{name}={value}" for name, value in self.values.items())

    def __repr__(self) -> str:
        """Redacted: a session must not leak into tracebacks or debug logs."""
        names = ", ".join(f"{name}=<redacted>" for name in self.values)
        return f"BrowserCookies(origin={self.origin!r}, {names})"


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
        BrowserCookieError: The value could not be decrypted with this key.
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
        raise BrowserCookieError(
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
    """Read a browser's Safe Storage password from the macOS Keychain.

    The user may see a Keychain authorization prompt the first time.

    Raises:
        BrowserCookieError: The Keychain entry is absent or access was denied.
    """
    try:
        completed = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", service, "-a", account],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - platform
        raise BrowserCookieError(f"could not run the macOS security tool: {exc}") from exc
    if completed.returncode != 0:
        raise BrowserCookieError(
            f"no Keychain entry for {service!r} — open the browser once, and "
            "allow Keychain access when prompted"
        )
    return completed.stdout.strip()


def pick_cookies(rows: list[tuple], spec: CookieSpec) -> dict | None:
    """Select the spec's required cookies from the most preferred host present.

    Args:
        rows: (host, name, value) triples, values still encrypted for Chromium.
        spec: What to look for.

    Returns:
        A name-to-value mapping, or None when no single host carries them all.
    """
    for host in spec.hosts:
        found = {
            name: value
            for host_key, name, value in rows
            if host_key == host and name in spec.required
        }
        if all(name in found for name in spec.required):
            return found
    return None


def _logged_out(spec: CookieSpec, origin: str) -> BrowserCookieError:
    """The error for a browser that is installed but not signed in."""
    return BrowserCookieError(
        f"no complete {spec.service} session in {origin} — open your browser, "
        f"go to {spec.login_url}, and make sure you are logged in"
    )


def read_chromium_cookies(
    db_path: Path, *, key: bytes, spec: CookieSpec, origin: str = "chrome"
) -> BrowserCookies:
    """Read one service's cookies out of a Chromium-family cookie database.

    The database is copied to a temporary file before reading, so a running
    browser is neither locked nor modified.

    Args:
        db_path: Path to the browser's `Cookies` SQLite database.
        key: The key from `derive_chrome_key`.
        spec: Which hosts and cookie names to look for.
        origin: Which browser this is, recorded on the result.

    Returns:
        The extracted cookies.

    Raises:
        BrowserCookieError: The database is missing, unreadable, or holds no
            complete session for this service.
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        raise BrowserCookieError(f"no {origin} cookie database at {db_path}")

    with readonly_copy(db_path) as copy:
        rows, db_version = read_cookie_rows(copy)

    found = pick_cookies(rows, spec)
    if found is None:
        raise _logged_out(spec, origin)
    return BrowserCookies(
        values={
            name: decrypt_chrome_value(found[name], key, db_version=db_version)
            for name in spec.required
        },
        origin=origin,
    )


def read_firefox_cookies(db_path: Path, *, spec: CookieSpec) -> BrowserCookies:
    """Read one service's cookies out of a Firefox cookie database.

    Firefox stores cookie values in the clear, so there is no key derivation
    and no Keychain prompt on this path.

    Args:
        db_path: Path to a profile's `cookies.sqlite`.
        spec: Which hosts and cookie names to look for.

    Returns:
        The extracted cookies.

    Raises:
        BrowserCookieError: The database is missing, unreadable, or holds no
            complete session for this service.
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        raise BrowserCookieError(f"no Firefox cookie database at {db_path}")

    with readonly_copy(db_path) as copy:
        conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        try:
            rows = list(conn.execute("SELECT host, name, value FROM moz_cookies"))
        except sqlite3.Error as exc:
            raise BrowserCookieError(
                f"could not read cookies from {db_path}: {exc}"
            ) from exc
        finally:
            conn.close()

    found = pick_cookies(rows, spec)
    if found is None:
        raise _logged_out(spec, FIREFOX_BROWSER)
    return BrowserCookies(
        values={name: found[name] for name in spec.required}, origin=FIREFOX_BROWSER
    )


@contextmanager
def readonly_copy(db_path: Path):
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
            raise BrowserCookieError(f"could not read {db_path}: {exc}") from exc
        yield copy


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


def read_cookie_rows(db_path: Path) -> tuple[list[tuple], int]:
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
        raise BrowserCookieError(f"could not read cookies from {db_path}: {exc}") from exc
    finally:
        conn.close()
    return rows, db_version


def cookies_from_env(spec: CookieSpec) -> BrowserCookies | None:
    """Build cookies from the spec's environment variables.

    Returns:
        The cookies, or None when none of the variables are set.

    Raises:
        BrowserCookieError: Some but not all are set — a half-configured
            session is a mistake worth naming, not a silent fallthrough.
    """
    if not spec.env_vars:
        return None
    present = {name: os.environ.get(env) for name, env in spec.env_vars}
    if not any(present.values()):
        return None
    for (name, env), value in zip(spec.env_vars, present.values()):
        if not value:
            others = ", ".join(other for _, other in spec.env_vars if other != env)
            raise BrowserCookieError(f"{env} is missing but {others} is set")
    return BrowserCookies(values={name: value for name, value in present.items()}, origin="env")


def pinned_db(browser: ChromiumBrowser, profile: str) -> Path:
    """The cookie database for one named profile of one browser."""
    base = browser.profile_root / profile
    modern = base / "Network" / "Cookies"
    return modern if modern.is_file() else base / "Cookies"


def _load_chromium(browser: ChromiumBrowser, spec: CookieSpec) -> BrowserCookies:
    """Read the first profile of one Chromium browser that holds a session.

    Raises:
        BrowserCookieError: The browser is absent, its Keychain entry is
            unavailable, or no profile is signed in.
    """
    databases = chromium_cookie_dbs(browser.profile_root)
    if not databases:
        raise BrowserCookieError(f"{browser.name} is not installed on this machine")

    key = derive_chrome_key(
        keychain_password(browser.keychain_service, browser.keychain_account)
    )
    last: BrowserCookieError | None = None
    for db_path in databases:
        try:
            return read_chromium_cookies(db_path, key=key, spec=spec, origin=browser.name)
        except BrowserCookieError as exc:
            last = exc
    raise last  # every profile failed; the last reason is as good as any


def _load_firefox(spec: CookieSpec) -> BrowserCookies:
    """Read the first Firefox profile that holds a session.

    Raises:
        BrowserCookieError: Firefox is absent or no profile is signed in.
    """
    databases = firefox_cookie_dbs()
    if not databases:
        raise BrowserCookieError("firefox is not installed on this machine")
    last: BrowserCookieError | None = None
    for db_path in databases:
        try:
            return read_firefox_cookies(db_path, spec=spec)
        except BrowserCookieError as exc:
            last = exc
    raise last


def load_cookies(
    spec: CookieSpec, browser: str = "auto", *, profile: str | None = None
) -> BrowserCookies:
    """Resolve one service's cookies, preferring explicitly supplied values.

    Args:
        spec: Which hosts and cookie names the service needs.
        browser: 'auto' tries the environment, then every installed browser.
            Any single name pins one path, so a failure names the thing that
            actually failed rather than a generic "not found".
        profile: Pin one profile directory by name; None searches all of them.

    Returns:
        The resolved cookies.

    Raises:
        BrowserCookieError: No session could be resolved by the requested path.
    """
    if browser in ("auto", "env"):
        found = cookies_from_env(spec)
        if found is not None:
            return found
        if browser == "env":
            raise BrowserCookieError(f"{' and '.join(spec.env_names)} are not set")

    if browser in CHROMIUM_BROWSERS:
        chosen = CHROMIUM_BROWSERS[browser]
        if profile:
            return read_chromium_cookies(
                pinned_db(chosen, profile),
                key=derive_chrome_key(
                    keychain_password(chosen.keychain_service, chosen.keychain_account)
                ),
                spec=spec,
                origin=chosen.name,
            )
        return _load_chromium(chosen, spec)

    if browser == FIREFOX_BROWSER:
        return _load_firefox(spec)

    if browser != "auto":
        raise BrowserCookieError(
            f"unknown browser: {browser!r} — choose from {', '.join(BROWSER_CHOICES)}"
        )

    # Auto: try every browser and report the whole search, because "no session
    # found" is only actionable if the user can see where we looked.
    reasons = []
    for candidate in (*CHROMIUM_BROWSERS.values(), FIREFOX_BROWSER):
        try:
            if candidate == FIREFOX_BROWSER:
                return _load_firefox(spec)
            return _load_chromium(candidate, spec)
        except BrowserCookieError as exc:
            name = candidate if isinstance(candidate, str) else candidate.name
            reasons.append(f"{name}: {exc}")

    message = (
        f"no {spec.service} session found in any installed browser.\n  "
        + "\n  ".join(reasons)
    )
    if spec.env_vars:
        message += f"\nAlternatively set {' and '.join(spec.env_names)} directly."
    raise BrowserCookieError(message)
