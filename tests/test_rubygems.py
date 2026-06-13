"""Tests for the RubyGems fetch adapter (IDEAS.md §6, ADR 0040).

The JSON transport is faked with a gem document recorded (and trimmed)
from the real RubyGems API, so the field mapping, the empty-by-design
concepts, license→tags, the source-URI normalization that makes the
gem↔repo link resolve, release-date derivation, and error handling are
all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.rubygems import fetch_item


# Recorded (and trimmed) from https://rubygems.org/api/v1/gems/rails.json
GEM_DOC = {
    "name": "rails",
    "version": "8.1.3",
    "version_created_at": "2026-03-24T20:27:42.098Z",
    "authors": "David Heinemeier Hansson",
    "info": "Ruby on Rails is a full-stack web framework optimized for "
    "programmer happiness.",
    "licenses": ["MIT"],
    "project_uri": "https://rubygems.org/gems/rails",
    "homepage_uri": "https://rubyonrails.org",
    "source_code_uri": "https://github.com/rails/rails/tree/v8.1.3",
    "documentation_uri": "https://api.rubyonrails.org/v8.1.3/",
    "bug_tracker_uri": "https://github.com/rails/rails/issues",
    "dependencies": {"runtime": [{"name": "actionpack"}, {"name": "activerecord"}]},
}


def make_item(**overrides):
    base = dict(
        id="rubygems:rails",
        source="rubygems",
        source_id="rails",
        url="https://rubygems.org/gems/rails",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_get_json(doc=GEM_DOC):
    def get_json(url):
        return json.loads(json.dumps(doc))  # deep copy

    return get_json


def fetch(doc=GEM_DOC, item=None):
    return fetch_item(item or make_item(), get_json=fake_get_json(doc))


def test_fetch_maps_metadata():
    fetched = fetch()

    assert fetched.title == "rails"
    assert fetched.author == "David Heinemeier Hansson"
    assert fetched.summary.startswith("Ruby on Rails is a full-stack web framework")
    # no README in the API: a RubyGems scroll is honestly metadata-only
    assert fetched.extracted_text is None
    # the response's own project_uri is the canonical url
    assert fetched.canonical_url == "https://rubygems.org/gems/rails"
    # version_created_at (fractional seconds + Z) normalizes to UTC ISO 8601
    assert fetched.published_at == "2026-03-24T20:27:42+00:00"
    assert fetched.provenance["adapter"] == "rubygems"
    assert fetched.provenance["extraction_method"] == "rubygems-api:json"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_concepts_are_structurally_empty():
    # a gemspec has no keywords field, so a RubyGems scroll never feeds the
    # concept graph — empty by design, not by an absent value
    assert fetch().concepts == ()


def test_licenses_become_tags():
    assert fetch().tags == ("MIT",)


def test_no_licenses_is_honestly_empty():
    doc = json.loads(json.dumps(GEM_DOC))
    doc.pop("licenses")
    assert fetch(doc).tags == ()


def test_links_carry_homepage_source_and_docs():
    # the source URI points at a tagged tree but still resolves to the repo
    # root via `scrolls related` (detect reads owner/repo off the path)
    assert fetch().links == (
        "https://rubyonrails.org",
        "https://github.com/rails/rails/tree/v8.1.3",
        "https://api.rubyonrails.org/v8.1.3/",
    )


def test_source_uri_dotgit_suffix_is_stripped():
    doc = json.loads(json.dumps(GEM_DOC))
    doc["source_code_uri"] = "https://github.com/rails/rails.git"
    links = fetch(doc).links
    assert "https://github.com/rails/rails" in links
    assert not any(link.endswith(".git") for link in links)


def test_canonical_url_falls_back_when_project_uri_absent():
    doc = json.loads(json.dumps(GEM_DOC))
    doc.pop("project_uri")
    assert fetch(doc).canonical_url == "https://rubygems.org/gems/rails"


def test_release_date_falls_back_to_seed():
    doc = json.loads(json.dumps(GEM_DOC))
    doc.pop("version_created_at")
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(doc, item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_non_string_created_at_does_not_crash():
    doc = json.loads(json.dumps(GEM_DOC))
    doc["version_created_at"] = 1700000000
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(doc, item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_keeps_raw_records_without_the_dependencies():
    raw = json.loads(fetch().raw_text)
    assert raw["name"] == "rails"
    assert raw["version"] == "8.1.3"
    # the dependency tree is dropped from raw_text to bound its size
    assert "dependencies" not in raw


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://rubygems.org/gems/rails/versions/8.1.3")
    fetched = fetch(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id)
    assert fetched.url == item.url  # the saved URL, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_requests_the_expected_api_url():
    seen = []

    def get_json(url):
        seen.append(url)
        return json.loads(json.dumps(GEM_DOC))

    # a case-sensitive name is preserved verbatim in the request
    fetch_item(make_item(source_id="Ascii85"), get_json=get_json)
    assert seen == ["https://rubygems.org/api/v1/gems/Ascii85.json"]


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_a_gem_name(source_id):
    item = make_item(id="rubygems:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine gem"):
        fetch_item(item, get_json=fake_get_json())


def test_missing_gem_is_a_fetch_error():
    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_item(), get_json=lambda url: {"error": "This rubygem could not be found."})


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom)


def test_rubygems_adapter_is_registered():
    assert FETCH_ADAPTERS["rubygems"] is fetch_item
