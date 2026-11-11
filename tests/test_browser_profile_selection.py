"""An explicitly selected profile must never silently use another account."""

import sqlite3

import pytest

from scrolls import browser_cookies as cookies

SPEC = cookies.CookieSpec(service="Example", hosts=(".example.com",),
                          required=("session",), login_url="https://example.com/login")


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    chrome = cookies.ChromiumBrowser("chrome", str(tmp_path / "chrome"), "Test", "Test")
    for name in ("Default", "Chosen"):
        db = chrome.profile_root / name / "Network" / "Cookies"
        db.parent.mkdir(parents=True)
        db.touch()
    monkeypatch.setattr(cookies, "CHROMIUM_BROWSERS", {"chrome": chrome})
    monkeypatch.setattr(cookies, "keychain_password", lambda *_: "fixture-password")
    monkeypatch.setattr(cookies, "cookies_from_env", lambda _: None)
    monkeypatch.setattr(
        cookies, "read_chromium_cookies",
        lambda path, **kw: cookies.BrowserCookies({"session": path.parent.parent.name}, "chrome"),
    )
    firefox = tmp_path / "firefox"
    for name in ("default-release", "Chosen"):
        db = firefox / name / "cookies.sqlite"
        db.parent.mkdir(parents=True)
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE moz_cookies (host TEXT, name TEXT, value TEXT)")
            conn.execute("INSERT INTO moz_cookies VALUES (?, ?, ?)",
                         (".example.com", "session", name))
    monkeypatch.setattr(cookies, "_FIREFOX_PROFILE_ROOT", firefox)


@pytest.mark.parametrize("browser", ["auto", "chrome", "firefox"])
def test_requested_profile_is_the_only_account_used(profiles, browser):
    result = cookies.load_cookies(SPEC, browser, profile="Chosen")
    assert result.values == {"session": "Chosen"}


@pytest.mark.parametrize("browser", ["auto", "chrome", "firefox"])
def test_missing_profile_never_falls_back_to_another_account(profiles, browser):
    with pytest.raises(cookies.BrowserCookieError, match="Missing"):
        cookies.load_cookies(SPEC, browser, profile="Missing")


def test_profile_pin_does_not_get_overridden_by_environment(profiles, monkeypatch):
    monkeypatch.setattr(cookies, "cookies_from_env",
                        lambda _: cookies.BrowserCookies({"session": "environment"}, "env"))
    assert cookies.load_cookies(SPEC, profile="Chosen").values == {"session": "Chosen"}


def test_explicit_env_and_profile_are_incompatible(profiles, monkeypatch):
    monkeypatch.setattr(cookies, "cookies_from_env",
                        lambda _: cookies.BrowserCookies({"session": "environment"}, "env"))
    with pytest.raises(cookies.BrowserCookieError, match="profile"):
        cookies.load_cookies(SPEC, "env", profile="Chosen")
