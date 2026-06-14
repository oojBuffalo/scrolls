"""Tests for the pub.dev (Dart/Flutter) fetch adapter (IDEAS.md §6, ADR 0088).

The JSON transport is faked with a package document recorded (and trimmed)
from the real pub.dev API, so the field mapping, topics→concepts (the
KB-graph signal that sets pub apart from RubyGems/Go), the flutter tag, the
repository→repo link normalization, microsecond-date derivation, and error
handling are all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.pub import fetch_item


# Recorded (and trimmed) from https://pub.dev/api/packages/riverpod — a
# pure-Dart package (no Flutter dependency) that carries pubspec topics.
PKG_DOC = {
    "name": "riverpod",
    "latest": {
        "version": "3.3.2",
        "published": "2026-06-10T08:37:59.561403Z",
        "pubspec": {
            "name": "riverpod",
            "description": "A reactive caching and data-binding framework. "
            "Riverpod makes working with asynchronous code a breeze.\n",
            "version": "3.3.2",
            "repository": "https://github.com/rrousselGit/riverpod",
            "homepage": "https://riverpod.dev",
            "topics": [
                "state-management",
                "caching",
                "dependency-injection",
                "riverpod",
            ],
            "environment": {"sdk": "^3.7.0"},
            "dependencies": {"async": "any", "meta": "any"},
        },
    },
    "versions": [{"version": "3.3.2"}, {"version": "3.3.1"}],
}


def make_item(**overrides):
    base = dict(
        id="pub:riverpod",
        source="pub",
        source_id="riverpod",
        url="https://pub.dev/packages/riverpod",
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


def with_pubspec(**changes):
    """A deep copy of PKG_DOC with its latest pubspec updated."""
    doc = json.loads(json.dumps(PKG_DOC))
    doc["latest"]["pubspec"].update(changes)
    return doc


def test_fetch_maps_metadata():
    fetched = fetch()

    assert fetched.title == "riverpod"
    assert fetched.summary.startswith("A reactive caching and data-binding framework")
    # no README in the API: a pub.dev scroll is honestly metadata-only
    assert fetched.extracted_text is None
    # the canonical url is the package page, built from the resolved name
    assert fetched.canonical_url == "https://pub.dev/packages/riverpod"
    # latest.published (microseconds + Z) normalizes to UTC ISO 8601
    assert fetched.published_at == "2026-06-10T08:37:59+00:00"
    assert fetched.provenance["adapter"] == "pub"
    assert fetched.provenance["extraction_method"] == "pubdev-api:json"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_topics_become_concepts():
    # pub's topics are the github-repo-topics analog — the signal that wires
    # a pub package into the KB concept graph (unlike RubyGems/Go)
    assert fetch().concepts == (
        "state-management",
        "caching",
        "dependency-injection",
        "riverpod",
    )


def test_no_topics_is_honestly_empty():
    doc = with_pubspec()
    doc["latest"]["pubspec"].pop("topics")
    assert fetch(doc).concepts == ()


def test_pure_dart_package_is_untagged():
    # riverpod declares no Flutter SDK — a pure-Dart package, left untagged
    assert fetch().tags == ()


def test_flutter_environment_constraint_tags_flutter():
    doc = with_pubspec(environment={"sdk": "^3.6.0", "flutter": ">=3.27.0"})
    assert fetch(doc).tags == ("flutter",)


def test_flutter_sdk_dependency_tags_flutter():
    # a Flutter SDK dependency is the other half of the signal
    doc = with_pubspec(dependencies={"flutter": {"sdk": "flutter"}, "meta": "any"})
    assert fetch(doc).tags == ("flutter",)


def test_links_carry_repository_and_homepage():
    assert fetch().links == (
        "https://github.com/rrousselGit/riverpod",
        "https://riverpod.dev",
    )


def test_repository_into_monorepo_tree_is_kept():
    # a monorepo tree URL still resolves to the repo root via `scrolls
    # related` (detect reads owner/repo off the path)
    tree = "https://github.com/flutter/packages/tree/main/packages/url_launcher"
    links = fetch(with_pubspec(repository=tree)).links
    assert tree in links


def test_repository_dotgit_suffix_is_stripped():
    doc = with_pubspec(repository="https://github.com/rrousselGit/riverpod.git")
    links = fetch(doc).links
    assert "https://github.com/rrousselGit/riverpod" in links
    assert not any(link.endswith(".git") for link in links)


def test_published_falls_back_to_seed():
    doc = json.loads(json.dumps(PKG_DOC))
    doc["latest"].pop("published")
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(doc, item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_non_string_published_does_not_crash():
    doc = json.loads(json.dumps(PKG_DOC))
    doc["latest"]["published"] = 1700000000
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(doc, item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_keeps_the_latest_version_as_raw_records():
    raw = json.loads(fetch().raw_text)
    # raw_text is the latest version object (the slim half), not the whole
    # response with its potentially long `versions` list
    assert raw["version"] == "3.3.2"
    assert raw["pubspec"]["name"] == "riverpod"
    assert "versions" not in raw


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://pub.dev/packages/riverpod/versions/3.3.2")
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

    fetch_item(make_item(source_id="provider"), get_json=get_json)
    assert seen == ["https://pub.dev/api/packages/provider"]


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_a_package_name(source_id):
    item = make_item(id="pub:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine package"):
        fetch_item(item, get_json=fake_get_json())


def test_missing_package_is_a_fetch_error():
    # a response with no `latest`/`pubspec` is not a package document
    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_item(), get_json=lambda url: {"name": "riverpod"})


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom)


def test_pub_adapter_is_registered():
    assert FETCH_ADAPTERS["pub"] is fetch_item
