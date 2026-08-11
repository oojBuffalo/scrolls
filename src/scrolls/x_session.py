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

_X_HOSTS = (".x.com", ".twitter.com")  # preference order: x.com is current
_REQUIRED_COOKIES = ("auth_token", "ct0")

AUTH_TOKEN_ENV = "SCROLLS_X_AUTH_TOKEN"
CT0_ENV = "SCROLLS_X_CT0"

_KEYCHAIN_SERVICE = "Chrome Safe Storage"
_KEYCHAIN_ACCOUNT = "Chrome"


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


def read_chrome_session(db_path: Path, *, key: bytes) -> XSession:
    """Read the X session out of a Chrome cookie database.

    The database is copied to a temporary file before reading, so a running
    browser is neither locked nor modified.

    Args:
        db_path: Path to Chrome's `Cookies` SQLite database.
        key: The key from `derive_chrome_key`.

    Returns:
        The extracted XSession.

    Raises:
        XSessionError: The database is missing, unreadable, or holds no
            complete X session.
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        raise XSessionError(f"no Chrome cookie database at {db_path}")

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "Cookies"
        try:
            shutil.copy2(db_path, copy)
        except OSError as exc:
            raise XSessionError(f"could not read {db_path}: {exc}") from exc
        rows, db_version = _read_cookie_rows(copy)

    for host in _X_HOSTS:
        found = {
            name: value
            for host_key, name, value in rows
            if host_key == host and name in _REQUIRED_COOKIES
        }
        if all(name in found for name in _REQUIRED_COOKIES):
            return XSession(
                auth_token=decrypt_chrome_value(found["auth_token"], key, db_version=db_version),
                ct0=decrypt_chrome_value(found["ct0"], key, db_version=db_version),
                origin="chrome",
            )

    raise XSessionError(
        "no complete X session in Chrome — open your browser, go to "
        "https://x.com, and make sure you are logged in"
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
        rows = [
            (host_key, name, encrypted or (value or "").encode("utf-8"))
            for host_key, name, value, encrypted in conn.execute(
                "SELECT host_key, name, value, encrypted_value FROM cookies"
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
