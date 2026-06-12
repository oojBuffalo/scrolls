"""Tests for the Wikipedia fetch adapter (IDEAS.md §6, ADR 0002)."""

import hashlib
import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.wikipedia import fetch_item

EXTRACT = (
    "SQLite is a database engine written in the C programming language.\n"
    "It is not a standalone app.\n"
    "\n"
    "\n"
    "== History ==\n"
    "D. Richard Hipp designed SQLite in the spring of 2000.\n"
    "\n"
    "\n"
    "== Features ==\n"
    "SQLite implements most of the SQL-92 standard.\n"
)


def make_item(**overrides):
    base = dict(
        id="wikipedia:en:SQLite",
        source="wikipedia",
        source_id="en:SQLite",
        url="https://en.wikipedia.org/wiki/SQLite",
        saved_at="2026-06-12T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def make_payload(**page_overrides):
    page = {
        "pageid": 25387,
        "title": "SQLite",
        "fullurl": "https://en.wikipedia.org/wiki/SQLite",
        "canonicalurl": "https://en.wikipedia.org/wiki/SQLite",
        "extract": EXTRACT,
    }
    page.update(page_overrides)
    return {"query": {"pages": [page]}}


def test_fetch_item_normalizes_page_onto_item():
    fetched = fetch_item(make_item(), get_json=lambda url: make_payload())

    assert fetched.title == "SQLite"
    assert fetched.canonical_url == "https://en.wikipedia.org/wiki/SQLite"
    assert fetched.extracted_text == EXTRACT
    assert fetched.summary == (
        "SQLite is a database engine written in the C programming language.\n"
        "It is not a standalone app."
    )
    assert fetched.content_hash == (
        "sha256:" + hashlib.sha256(EXTRACT.encode("utf-8")).hexdigest()
    )
    assert json.loads(fetched.raw_text)["pageid"] == 25387
    assert fetched.provenance["adapter"] == "wikipedia"
    assert fetched.provenance["extraction_method"] == "mediawiki-api:extracts"
    assert fetched.provenance["fetched_at"]  # set, exact value is clock-dependent
    assert fetched.stage == "fetched"


def test_fetch_item_preserves_identity_fields():
    item = make_item()
    fetched = fetch_item(item, get_json=lambda url: make_payload())
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url
    assert fetched.saved_at == item.saved_at


def test_fetch_item_builds_action_api_url_for_language_and_title():
    seen = {}

    def capture(url):
        seen["url"] = url
        return make_payload()

    fetch_item(make_item(source_id="de:Straße"), get_json=capture)
    assert seen["url"].startswith("https://de.wikipedia.org/w/api.php?")
    assert "titles=Stra%C3%9Fe" in seen["url"]
    assert "explaintext=1" in seen["url"]
    assert "redirects=1" in seen["url"]
    assert "prop=extracts%7Cinfo%7Ccategories" in seen["url"]
    assert "clshow=%21hidden" in seen["url"]
    assert "cllimit=max" in seen["url"]


def test_fetch_item_maps_visible_categories_to_concepts():
    payload = make_payload(
        categories=[
            {"ns": 14, "title": "Category:Database management systems"},
            {"ns": 14, "title": "Category:SQLite"},
        ]
    )
    fetched = fetch_item(make_item(), get_json=lambda url: payload)
    assert fetched.concepts == ("Database management systems", "SQLite")
    # the raw page keeps the category records for rebuilds
    assert json.loads(fetched.raw_text)["categories"][0]["title"] == (
        "Category:Database management systems"
    )


def test_fetch_item_strips_localized_category_prefixes():
    payload = make_payload(categories=[{"ns": 14, "title": "Kategorie:Datenbanken"}])
    fetched = fetch_item(make_item(source_id="de:SQLite"), get_json=lambda url: payload)
    assert fetched.concepts == ("Datenbanken",)


def test_fetch_item_without_categories_has_no_concepts():
    fetched = fetch_item(make_item(), get_json=lambda url: make_payload())
    assert fetched.concepts == ()


def test_fetch_item_splits_source_id_on_first_colon_only():
    seen = {}

    def capture(url):
        seen["url"] = url
        return make_payload()

    fetch_item(make_item(source_id="en:Category:Databases"), get_json=capture)
    assert seen["url"].startswith("https://en.wikipedia.org/w/api.php?")
    assert "titles=Category%3ADatabases" in seen["url"]


def test_fetch_item_uses_redirect_resolved_title_but_keeps_item_id():
    # detect() recorded "en:Sqlite"; the API resolves the redirect to "SQLite".
    item = make_item(id="wikipedia:en:Sqlite", source_id="en:Sqlite")
    fetched = fetch_item(item, get_json=lambda url: make_payload())
    assert fetched.title == "SQLite"
    assert fetched.id == "wikipedia:en:Sqlite"  # identity assigned at add time


def test_fetch_item_rejects_missing_page():
    payload = {"query": {"pages": [{"title": "Nope", "missing": True}]}}
    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_item(source_id="en:Nope"), get_json=lambda url: payload)


def test_fetch_item_rejects_empty_pages_payload():
    with pytest.raises(FetchError):
        fetch_item(make_item(), get_json=lambda url: {"query": {"pages": []}})


def test_fetch_item_rejects_item_without_page_identity():
    with pytest.raises(FetchError, match="page"):
        fetch_item(make_item(source_id=None), get_json=lambda url: make_payload())


def test_fetch_item_wraps_transport_errors():
    def boom(url):
        raise OSError("connection refused")

    with pytest.raises(FetchError, match="connection refused"):
        fetch_item(make_item(), get_json=boom)


def test_wikipedia_adapter_is_registered():
    assert FETCH_ADAPTERS["wikipedia"] is fetch_item
