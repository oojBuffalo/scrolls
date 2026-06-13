"""Tests for the Packagist / Composer fetch adapter (IDEAS.md §6, ADR 0039).

The JSON transport is faked with a package document recorded (and
trimmed) from the real Packagist API, so the field mapping,
keyword/license parsing, the source-URL normalization that makes the
package↔repo link resolve, stable-version selection, release-date
derivation, and error handling are all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.packagist import fetch_item


# Recorded (and trimmed) from https://packagist.org/packages/monolog/monolog.json
PACKAGE_DOC = {
    "package": {
        "name": "monolog/monolog",
        "description": "Logs to files, sockets, inboxes, databases and web services",
        "time": "2011-09-25T20:33:33+00:00",
        "type": "library",
        "repository": "https://github.com/Seldaek/monolog",
        "maintainers": [{"name": "Seldaek", "avatar_url": "…"}],
        "versions": {
            "dev-main": {
                "name": "monolog/monolog",
                "version": "dev-main",
                "version_normalized": "dev-main",
                "license": ["MIT"],
                "type": "library",
                "time": "2026-01-02T00:00:00+00:00",
            },
            "3.8.1": {
                "name": "monolog/monolog",
                "version": "3.8.1",
                "version_normalized": "3.8.1.0",
                "description": "Sends your logs to files, sockets, and web services",
                "keywords": ["log", "logging", "psr-3"],
                "homepage": "https://github.com/Seldaek/monolog",
                "license": ["MIT"],
                "authors": [{"name": "Jordi Boggiano", "email": "j@seld.be"}],
                "source": {
                    "url": "https://github.com/Seldaek/monolog.git",
                    "type": "git",
                    "reference": "aef6ee7",
                },
                "type": "library",
                "time": "2024-12-05T17:15:07+00:00",
            },
            "3.9.0": {
                "name": "monolog/monolog",
                "version": "3.9.0",
                "version_normalized": "3.9.0.0",
                "description": "Sends your logs to files, sockets, and web services",
                "keywords": ["log", "logging", "psr-3"],
                "homepage": "https://github.com/Seldaek/monolog",
                "license": ["MIT"],
                "authors": [{"name": "Jordi Boggiano", "email": "j@seld.be"}],
                "source": {
                    "url": "https://github.com/Seldaek/monolog.git",
                    "type": "git",
                    "reference": "bb01b6f",
                },
                "type": "library",
                "time": "2025-03-24T10:11:12+00:00",
            },
            "2.9.3": {
                "name": "monolog/monolog",
                "version": "2.9.3",
                "version_normalized": "2.9.3.0",
                "keywords": ["log", "events"],
                "license": ["MIT"],
                "type": "library",
                "time": "2024-04-12T20:14:51+00:00",
            },
        },
    }
}


def make_item(**overrides):
    base = dict(
        id="packagist:monolog/monolog",
        source="packagist",
        source_id="monolog/monolog",
        url="https://packagist.org/packages/monolog/monolog",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_get_json(doc=PACKAGE_DOC):
    def get_json(url):
        return json.loads(json.dumps(doc))  # deep copy

    return get_json


def fetch(doc=PACKAGE_DOC, item=None):
    return fetch_item(item or make_item(), get_json=fake_get_json(doc))


def test_fetch_maps_metadata():
    fetched = fetch()

    assert fetched.title == "monolog/monolog"
    assert fetched.author == "Jordi Boggiano"
    # the chosen (highest stable) release's description wins over the package's
    assert fetched.summary == "Sends your logs to files, sockets, and web services"
    # no README in the API: a Packagist scroll is honestly metadata-only
    assert fetched.extracted_text is None
    assert fetched.canonical_url == "https://packagist.org/packages/monolog/monolog"
    assert fetched.provenance["adapter"] == "packagist"
    assert fetched.provenance["extraction_method"] == "packagist-api:json"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_selects_highest_stable_version_not_newest_by_time():
    # 3.9.0 is the highest stable release; a later-dated 2.9.x patch or the
    # dev-main branch must not win.
    assert fetch().published_at == "2025-03-24T10:11:12+00:00"


def test_keywords_become_concepts_like_github_topics():
    assert fetch().concepts == ("log", "logging", "psr-3")


def test_type_and_licenses_become_tags_as_structured_facets():
    assert fetch().tags == ("library", "MIT")


def test_links_carry_normalized_repository_and_homepage():
    # repository (clean), homepage, and the git source all point at the same
    # github repo, so they dedupe to one resolvable link (package↔repo edge)
    assert fetch().links == ("https://github.com/Seldaek/monolog",)


def test_git_source_dotgit_suffix_is_stripped():
    doc = json.loads(json.dumps(PACKAGE_DOC))
    # drop the clean repository + homepage so only the .git source remains
    doc["package"].pop("repository")
    doc["package"]["versions"]["3.9.0"].pop("homepage")
    links = fetch(doc).links
    assert "https://github.com/Seldaek/monolog" in links
    assert not any(link.endswith(".git") for link in links)


def test_no_keywords_is_honestly_empty():
    doc = json.loads(json.dumps(PACKAGE_DOC))
    doc["package"]["versions"]["3.9.0"].pop("keywords")
    assert fetch(doc).concepts == ()


def test_authors_fall_back_to_maintainers():
    doc = json.loads(json.dumps(PACKAGE_DOC))
    doc["package"]["versions"]["3.9.0"].pop("authors")
    assert fetch(doc).author == "Seldaek"


def test_many_authors_are_truncated_with_et_al():
    doc = json.loads(json.dumps(PACKAGE_DOC))
    doc["package"]["versions"]["3.9.0"]["authors"] = [
        {"name": f"Author {i}"} for i in range(15)
    ]
    author = fetch(doc).author
    assert author.endswith("et al.")
    assert author.count(",") == 10  # 10 names + the "et al." tail


def test_only_prereleases_picks_the_highest_prerelease():
    doc = json.loads(json.dumps(PACKAGE_DOC))
    versions = doc["package"]["versions"]
    for num in ("3.8.1", "3.9.0", "2.9.3"):
        versions.pop(num)
    versions["3.0.0-RC1"] = {
        "name": "monolog/monolog",
        "version": "3.0.0-RC1",
        "version_normalized": "3.0.0.0-RC1",
        "license": ["MIT"],
        "type": "library",
        "time": "2026-02-02T00:00:00+00:00",
    }
    fetched = fetch(doc)
    assert fetched.published_at == "2026-02-02T00:00:00+00:00"
    assert fetched.tags == ("library", "MIT")


def test_only_dev_branches_still_yields_a_version():
    doc = json.loads(json.dumps(PACKAGE_DOC))
    versions = doc["package"]["versions"]
    for num in ("3.8.1", "3.9.0", "2.9.3"):
        versions.pop(num)
    # only dev-main remains; the newest dev branch by time is used
    assert fetch(doc).published_at == "2026-01-02T00:00:00+00:00"


def test_release_date_falls_back_to_package_time_then_seed():
    doc = json.loads(json.dumps(PACKAGE_DOC))
    doc["package"]["versions"]["3.9.0"].pop("time")
    # falls back to the package-level first-published time
    assert fetch(doc).published_at == "2011-09-25T20:33:33+00:00"


def test_non_string_version_time_does_not_crash():
    doc = json.loads(json.dumps(PACKAGE_DOC))
    doc["package"]["versions"]["3.9.0"]["time"] = 1700000000
    doc["package"].pop("time")
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(doc, item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_keeps_raw_records_for_rebuilds_without_the_versions_map():
    raw = json.loads(fetch().raw_text)
    assert raw["package"]["name"] == "monolog/monolog"
    assert raw["version"]["version"] == "3.9.0"
    # the full versions map is dropped from raw_text to bound its size
    assert "versions" not in raw["package"]


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://packagist.org/packages/monolog/monolog#requireme")
    fetched = fetch(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id)
    assert fetched.url == item.url  # the saved URL, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_requests_the_expected_api_url():
    seen = []

    def get_json(url):
        seen.append(url)
        return json.loads(json.dumps(PACKAGE_DOC))

    fetch_item(make_item(), get_json=get_json)
    assert seen == ["https://packagist.org/packages/monolog/monolog.json"]


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_a_package_name(source_id):
    item = make_item(id="packagist:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine package"):
        fetch_item(item, get_json=fake_get_json())


def test_missing_package_is_a_fetch_error():
    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_item(), get_json=lambda url: {"status": "error"})


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom)


def test_packagist_adapter_is_registered():
    assert FETCH_ADAPTERS["packagist"] is fetch_item
