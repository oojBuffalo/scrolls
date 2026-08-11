"""Tests for X browser-session extraction.

The Chrome scheme under test — PBKDF2(password, 'saltysalt', 1003, 16, sha1)
then AES-128-CBC with a sixteen-space IV — is Chrome's, not ours, so the
round-trip tests encrypt with the same parameters rather than asserting
against a frozen blob. The macOS Keychain lookup is injected so no test ever
prompts for credentials.
"""

import sqlite3

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from scrolls.x_session import (
    CHROME_IV,
    XSession,
    XSessionError,
    decrypt_chrome_value,
    derive_chrome_key,
    load_session_from_env,
    read_chrome_session,
)


def _encrypt(value: bytes, key: bytes, *, prefix=b"v10", pad_to_block=True):
    """Encrypt as Chrome does, for round-trip tests."""
    if pad_to_block:
        padding = 16 - (len(value) % 16)
        value = value + bytes([padding]) * padding
    encryptor = Cipher(algorithms.AES(key), modes.CBC(CHROME_IV)).encryptor()
    return prefix + encryptor.update(value) + encryptor.finalize()


def _cookie_db(path, rows, *, version=24):
    """Build a minimal Chrome cookie database."""
    conn = sqlite3.connect(path)
    with conn:
        conn.execute("CREATE TABLE meta (key TEXT, value TEXT)")
        conn.execute("INSERT INTO meta VALUES ('version', ?)", (str(version),))
        conn.execute(
            "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB)"
        )
        conn.executemany("INSERT INTO cookies VALUES (?, ?, ?, ?)", rows)
    conn.close()


# --- session shape -------------------------------------------------------


def test_cookie_header_carries_both_cookies_x_requires():
    session = XSession(auth_token="AUTH", ct0="CSRF", origin="chrome")
    assert session.cookie_header == "auth_token=AUTH; ct0=CSRF"


def test_csrf_token_is_the_ct0_cookie():
    """x-csrf-token must equal ct0 or X rejects the request."""
    assert XSession(auth_token="AUTH", ct0="CSRF", origin="chrome").csrf_token == "CSRF"


# --- key derivation and decryption ---------------------------------------


def test_derive_chrome_key_is_deterministic_and_16_bytes():
    key = derive_chrome_key("some-keychain-password")
    assert len(key) == 16
    assert key == derive_chrome_key("some-keychain-password")
    assert key != derive_chrome_key("a-different-password")


def test_decrypts_a_v10_value_round_trip():
    key = derive_chrome_key("pw")
    assert decrypt_chrome_value(_encrypt(b"secret-token", key), key) == "secret-token"


def test_strips_the_32_byte_domain_hash_on_newer_databases():
    """Chrome >= v24 prefixes the plaintext with a SHA256 of the host key."""
    key = derive_chrome_key("pw")
    encrypted = _encrypt(b"\x00" * 32 + b"real-token", key)
    assert decrypt_chrome_value(encrypted, key, db_version=24) == "real-token"
    # On older databases that prefix does not exist and must not be stripped.
    assert decrypt_chrome_value(_encrypt(b"real-token", key), key, db_version=23) == (
        "real-token"
    )


def test_an_unencrypted_value_is_passed_through():
    """Some profiles keep cookies in the plaintext column."""
    assert decrypt_chrome_value(b"plain-token", derive_chrome_key("pw")) == "plain-token"


def test_a_value_encrypted_under_a_different_key_fails_loudly():
    encrypted = _encrypt(b"secret-token", derive_chrome_key("right"))
    with pytest.raises(XSessionError, match="decrypt"):
        decrypt_chrome_value(encrypted, derive_chrome_key("wrong"), db_version=0)


# --- reading the cookie database -----------------------------------------


def test_reads_auth_token_and_ct0_for_x_com(tmp_path):
    key = derive_chrome_key("pw")
    db = tmp_path / "Cookies"
    _cookie_db(
        db,
        [
            (".x.com", "auth_token", "", _encrypt(b"\x00" * 32 + b"AUTH", key)),
            (".x.com", "ct0", "", _encrypt(b"\x00" * 32 + b"CSRF", key)),
            (".example.com", "auth_token", "", _encrypt(b"\x00" * 32 + b"OTHER", key)),
        ],
    )
    session = read_chrome_session(db, key=key)
    assert session.auth_token == "AUTH"
    assert session.ct0 == "CSRF"
    assert session.origin == "chrome"


def test_falls_back_to_twitter_com_when_x_com_is_absent(tmp_path):
    key = derive_chrome_key("pw")
    db = tmp_path / "Cookies"
    _cookie_db(
        db,
        [
            (".twitter.com", "auth_token", "", _encrypt(b"\x00" * 32 + b"AUTH", key)),
            (".twitter.com", "ct0", "", _encrypt(b"\x00" * 32 + b"CSRF", key)),
        ],
    )
    assert read_chrome_session(db, key=key).auth_token == "AUTH"


def test_x_com_wins_when_both_hosts_have_cookies(tmp_path):
    key = derive_chrome_key("pw")
    db = tmp_path / "Cookies"
    _cookie_db(
        db,
        [
            (".twitter.com", "auth_token", "", _encrypt(b"\x00" * 32 + b"OLD", key)),
            (".twitter.com", "ct0", "", _encrypt(b"\x00" * 32 + b"OLDCSRF", key)),
            (".x.com", "auth_token", "", _encrypt(b"\x00" * 32 + b"NEW", key)),
            (".x.com", "ct0", "", _encrypt(b"\x00" * 32 + b"NEWCSRF", key)),
        ],
    )
    assert read_chrome_session(db, key=key).auth_token == "NEW"


def test_a_logged_out_profile_says_so_rather_than_returning_half_a_session(tmp_path):
    key = derive_chrome_key("pw")
    db = tmp_path / "Cookies"
    _cookie_db(db, [(".x.com", "ct0", "", _encrypt(b"\x00" * 32 + b"CSRF", key))])
    with pytest.raises(XSessionError, match="logged in"):
        read_chrome_session(db, key=key)


def test_a_missing_cookie_database_names_the_path(tmp_path):
    with pytest.raises(XSessionError, match="no Chrome cookie database"):
        read_chrome_session(tmp_path / "absent", key=derive_chrome_key("pw"))


def test_the_cookie_database_is_never_opened_read_write(tmp_path):
    """Scrolls must not risk corrupting the user's live browser profile."""
    key = derive_chrome_key("pw")
    db = tmp_path / "Cookies"
    _cookie_db(
        db,
        [
            (".x.com", "auth_token", "", _encrypt(b"\x00" * 32 + b"AUTH", key)),
            (".x.com", "ct0", "", _encrypt(b"\x00" * 32 + b"CSRF", key)),
        ],
    )
    before = db.read_bytes()
    read_chrome_session(db, key=key)
    assert db.read_bytes() == before


# --- the credential-free escape hatch ------------------------------------


def test_env_session_lets_a_user_supply_cookies_without_keychain_access(monkeypatch):
    monkeypatch.setenv("SCROLLS_X_AUTH_TOKEN", "AUTH")
    monkeypatch.setenv("SCROLLS_X_CT0", "CSRF")
    session = load_session_from_env()
    assert (session.auth_token, session.ct0, session.origin) == ("AUTH", "CSRF", "env")


def test_env_session_is_none_when_unset(monkeypatch):
    monkeypatch.delenv("SCROLLS_X_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SCROLLS_X_CT0", raising=False)
    assert load_session_from_env() is None


def test_a_half_set_env_pair_is_an_error_not_a_silent_skip(monkeypatch):
    monkeypatch.setenv("SCROLLS_X_AUTH_TOKEN", "AUTH")
    monkeypatch.delenv("SCROLLS_X_CT0", raising=False)
    with pytest.raises(XSessionError, match="SCROLLS_X_CT0"):
        load_session_from_env()


def test_a_session_never_renders_its_secrets(monkeypatch):
    """A traceback or debug log must not leak the session cookie."""
    session = XSession(auth_token="SUPERSECRET", ct0="CSRFSECRET", origin="chrome")
    assert "SUPERSECRET" not in repr(session)
    assert "CSRFSECRET" not in repr(session)
