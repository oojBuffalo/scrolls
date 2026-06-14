"""Tests for the Hex (Elixir/Erlang) fetch adapter (IDEAS.md §6, ADR 0089).

The JSON transport is faked with a package document recorded (and trimmed)
from the real Hex API, so the field mapping, the empty-by-design concepts,
licenses→tags, the links-map extraction with its repo→edge resolution, the
release-date selection by latest_stable_version, and error handling are all
covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.hex import fetch_item


# Recorded (and trimmed) from https://hex.pm/api/packages/ecto
PKG_DOC = {
    "name": "ecto",
    "html_url": "https://hex.pm/packages/ecto",
    "updated_at": "2026-05-19T16:10:08.201534Z",
    "latest_stable_version": "3.14.0",
    "latest_version": "3.14.0",
    "meta": {
        "description": "A toolkit for data mapping and language integrated "
        "query for Elixir",
        "licenses": ["Apache-2.0"],
        "links": {
            "Changelog": "https://hexdocs.pm/ecto/changelog.html",
            "GitHub": "https://github.com/elixir-ecto/ecto",
        },
    },
    "releases": [
        {"version": "3.14.0", "inserted_at": "2026-05-19T16:02:40.684729Z"},
        {"version": "3.13.6", "inserted_at": "2026-05-05T14:28:17.970417Z"},
        {"version": "3.13.5", "inserted_at": "2025-11-09T08:10:52.139053Z"},
    ],
}


def make_item(**overrides):
    base = dict(
        id="hex:ecto",
        source="hex",
        source_id="ecto",
        url="https://hex.pm/packages/ecto",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_get_json(doc=PKG_DOC):
    def get_json(url):
        return json.loads(json.dumps(doc))  # deep copy

    return get_json


def fetch(doc=PKG_DOC, item=None):
    return fetch_item(item or make_item(), get_json=fake_get_json(doc))


def with_meta(**changes):
    """A deep copy of PKG_DOC with its meta updated."""
    doc = json.loads(json.dumps(PKG_DOC))
    doc["meta"].update(changes)
    return doc


def test_fetch_maps_metadata():
    fetched = fetch()

    assert fetched.title == "ecto"
    assert fetched.summary.startswith("A toolkit for data mapping")
    # no README in the API: a Hex scroll is honestly metadata-only
    assert fetched.extracted_text is None
    # the response's own html_url is the canonical url
    assert fetched.canonical_url == "https://hex.pm/packages/ecto"
    assert fetched.provenance["adapter"] == "hex"
    assert fetched.provenance["extraction_method"] == "hexpm-api:json"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_concepts_are_structurally_empty():
    # Hex has no keywords field, so a Hex scroll never feeds the concept
    # graph — empty by design (RubyGems/Go, not pub.dev's topics)
    assert fetch().concepts == ()


def test_licenses_become_tags():
    assert fetch().tags == ("Apache-2.0",)


def test_no_licenses_is_honestly_empty():
    doc = with_meta()
    doc["meta"].pop("licenses")
    assert fetch(doc).tags == ()


def test_links_map_values_become_links():
    # every http(s) value of meta.links, in the map's order, the GitHub
    # entry resolving to the repo via `scrolls related`
    assert fetch().links == (
        "https://hexdocs.pm/ecto/changelog.html",
        "https://github.com/elixir-ecto/ecto",
    )


def test_github_link_dotgit_suffix_is_stripped():
    doc = with_meta(links={"GitHub": "https://github.com/elixir-ecto/ecto.git"})
    links = fetch(doc).links
    assert "https://github.com/elixir-ecto/ecto" in links
    assert not any(link.endswith(".git") for link in links)


def test_no_links_map_is_honestly_empty():
    doc = with_meta()
    doc["meta"].pop("links")
    assert fetch(doc).links == ()


def test_release_date_matches_latest_stable_version():
    # the release whose version == latest_stable_version dates the scroll,
    # not merely the first list entry
    assert fetch().published_at == "2026-05-19T16:02:40+00:00"


def test_release_date_prefers_stable_over_a_newer_prerelease():
    doc = json.loads(json.dumps(PKG_DOC))
    # a newer prerelease tops the list, but latest_stable_version pins 3.14.0
    doc["latest_version"] = "3.15.0-rc.0"
    doc["releases"].insert(
        0, {"version": "3.15.0-rc.0", "inserted_at": "2026-06-01T00:00:00.0Z"}
    )
    assert fetch(doc).published_at == "2026-05-19T16:02:40+00:00"


def test_release_date_falls_back_to_seed_when_releases_absent():
    doc = json.loads(json.dumps(PKG_DOC))
    doc.pop("releases")
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(doc, item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_canonical_url_falls_back_when_html_url_absent():
    doc = json.loads(json.dumps(PKG_DOC))
    doc.pop("html_url")
    assert fetch(doc).canonical_url == "https://hex.pm/packages/ecto"


def test_keeps_raw_records_without_the_releases_list():
    raw = json.loads(fetch().raw_text)
    assert raw["name"] == "ecto"
    assert raw["meta"]["description"].startswith("A toolkit")
    # the releases list is dropped from raw_text to bound its size
    assert "releases" not in raw


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://hex.pm/packages/ecto/3.14.0")
    fetched = fetch(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id)
    assert fetched.url == item.url  # the saved URL, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_requests_the_expected_api_url():
    seen = []

    def get_json(url):
        seen.append(url)
        return json.loads(json.dumps(PKG_DOC))

    fetch_item(make_item(source_id="phoenix"), get_json=get_json)
    assert seen == ["https://hex.pm/api/packages/phoenix"]


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_a_package_name(source_id):
    item = make_item(id="hex:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine package"):
        fetch_item(item, get_json=fake_get_json())


def test_missing_package_is_a_fetch_error():
    # a response with no `name` is not a package document
    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_item(), get_json=lambda url: {"meta": {}})


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom)


def test_hex_adapter_is_registered():
    assert FETCH_ADAPTERS["hex"] is fetch_item
