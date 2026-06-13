"""Tests for the npm fetch adapter (IDEAS.md §6, ADR 0035).

The JSON transport is faked with a packument recorded (and trimmed) from
the real npm registry, so the field mapping, keyword parsing, the
repository-URL normalization that makes the package↔repo link resolve,
the "no README" sentinel, latest-version release-date derivation, scoped
names, and error handling are all covered offline (ADR 0001).
"""

import io
import json
import tarfile

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.npm import fetch_item


def make_tarball(files):
    """A gzipped npm tarball with `files` mapping member path -> text."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name=path)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def no_network(url, max_bytes=None):  # injected so no unit test touches the wire
    raise AssertionError(f"unexpected tarball fetch: {url}")

# Recorded (and trimmed) from https://registry.npmjs.org/express
PACKUMENT = {
    "_id": "express",
    "name": "express",
    "description": "Fast, unopinionated, minimalist web framework",
    "dist-tags": {"latest": "4.18.2", "next": "5.0.0-beta.1"},
    "versions": {
        "4.18.1": {"name": "express", "version": "4.18.1"},
        "4.18.2": {
            "name": "express",
            "version": "4.18.2",
            "description": "Fast, unopinionated, minimalist web framework",
            "author": {"name": "TJ Holowaychuk", "email": "tj@vision-media.ca"},
            "keywords": ["express", "framework", "sinatra", "web", "rest", "router"],
            "homepage": "http://expressjs.com/",
            "repository": {
                "type": "git",
                "url": "git+https://github.com/expressjs/express.git",
            },
            "bugs": {"url": "https://github.com/expressjs/express/issues"},
            "license": "MIT",
        },
    },
    "readme": "# Express\n\nFast, unopinionated, minimalist web framework for "
    "[Node.js](http://nodejs.org).\n\n```js\nconst app = require('express')()\n```\n",
    "readmeFilename": "Readme.md",
    "maintainers": [{"name": "dougwilson", "email": "doug@somethingdoug.com"}],
    "time": {
        "created": "2010-12-29T19:38:25.450Z",
        "modified": "2024-01-10T00:00:00.000Z",
        "4.18.1": "2022-04-29T01:51:54.107Z",
        "4.18.2": "2022-10-08T07:48:48.246Z",
    },
    "homepage": "http://expressjs.com/",
    "keywords": ["express", "framework", "sinatra", "web", "rest", "router"],
    "repository": {"type": "git", "url": "git+https://github.com/expressjs/express.git"},
    "author": {"name": "TJ Holowaychuk", "email": "tj@vision-media.ca"},
    "license": "MIT",
}


def make_item(**overrides):
    base = dict(
        id="npm:express",
        source="npm",
        source_id="express",
        url="https://www.npmjs.com/package/express",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_get_json(packument=PACKUMENT):
    def get_json(url):
        return json.loads(json.dumps(packument))  # deep copy

    return get_json


def fetch(packument=PACKUMENT, item=None, get_bytes=no_network):
    return fetch_item(
        item or make_item(), get_json=fake_get_json(packument), get_bytes=get_bytes
    )


def test_fetch_maps_metadata_and_readme():
    fetched = fetch()

    assert fetched.title == "express"
    assert fetched.author == "TJ Holowaychuk"
    assert fetched.summary == "Fast, unopinionated, minimalist web framework"
    assert "minimalist web framework for" in fetched.extracted_text
    assert fetched.canonical_url == "https://www.npmjs.com/package/express"
    # the latest version's publish time is the release moment
    assert fetched.published_at == "2022-10-08T07:48:48+00:00"
    assert fetched.provenance["adapter"] == "npm"
    assert fetched.provenance["extraction_method"] == "npm-registry:json+readme"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_keywords_become_concepts_like_github_topics():
    assert fetch().concepts == ("express", "framework", "sinatra", "web", "rest", "router")


def test_keywords_dedupe_and_tolerate_a_comma_string():
    pack = {**PACKUMENT, "keywords": ["http", "http", "client"]}
    assert fetch(pack).concepts == ("http", "client")
    # defensive: a comma-separated string still splits (ADR 0034 parallel)
    pack = {**PACKUMENT, "keywords": "http, client, api"}
    assert fetch(pack).concepts == ("http", "client", "api")


def test_repository_url_normalizes_to_the_clean_github_repo():
    # git+https://github.com/expressjs/express.git -> the repo `related` resolves
    assert fetch().links == ("http://expressjs.com/", "https://github.com/expressjs/express")


def test_repository_spellings_all_collapse_to_https_without_dotgit():
    forms = [
        "git://github.com/owner/repo.git",
        "git+ssh://git@github.com/owner/repo.git",
        "git@github.com:owner/repo.git",
        "github:owner/repo",
        {"type": "git", "url": "https://github.com/owner/repo"},
    ]
    for form in forms:
        pack = {**PACKUMENT, "repository": form}
        links = fetch(pack).links
        assert "https://github.com/owner/repo" in links, form
        assert not any(link.endswith(".git") for link in links), form


def test_no_tags_npm_has_no_classifier_taxonomy():
    # Unlike PyPI's trove classifiers, npm has no structured taxonomy → empty.
    assert fetch().tags == ()


def test_missing_readme_sentinel_becomes_absent():
    pack = {**PACKUMENT, "readme": "ERROR: No README data found!"}
    fetched = fetch(pack)
    assert fetched.extracted_text is None
    # no readme: hashed over the raw record, method records json-only
    assert fetched.provenance["extraction_method"] == "npm-registry:json"


def _packument_without_readme(tarball_url="https://registry.npmjs.org/x/-/x-1.0.0.tgz"):
    # high-traffic packages return an empty top-level readme; the tarball carries it
    pack = {**PACKUMENT, "readme": ""}
    pack["versions"] = {
        "4.18.2": {"name": "express", "version": "4.18.2",
                   "dist": {"tarball": tarball_url}},
    }
    return pack


def test_readme_falls_back_to_the_tarball_when_the_packument_has_none():
    seen = []

    def get_bytes(url, max_bytes=None):
        seen.append((url, max_bytes))
        return make_tarball({"package/README.md": "# Express\n\nThe real readme.\n",
                             "package/index.js": "module.exports = {}\n"})

    fetched = fetch(_packument_without_readme(), get_bytes=get_bytes)
    assert "The real readme." in fetched.extracted_text
    assert fetched.provenance["extraction_method"] == "npm-registry:json+tarball-readme"
    # the tarball is fetched from dist.tarball, capped
    assert seen[0][0] == "https://registry.npmjs.org/x/-/x-1.0.0.tgz"
    assert seen[0][1] and seen[0][1] > 0


def test_tarball_readme_picks_the_root_markdown_over_a_nested_one():
    def get_bytes(url, max_bytes=None):
        return make_tarball({
            "package/docs/README.md": "nested, not this one",
            "package/README": "plain readme",
            "package/README.md": "# root markdown readme",
        })

    # a Markdown README at the package root wins over plain and nested files
    assert fetch(_packument_without_readme(), get_bytes=get_bytes).extracted_text == (
        "# root markdown readme")


def test_tarball_with_no_readme_degrades_to_metadata_only():
    def get_bytes(url, max_bytes=None):
        return make_tarball({"package/index.js": "module.exports = {}\n"})

    fetched = fetch(_packument_without_readme(), get_bytes=get_bytes)
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "npm-registry:json"


def test_failed_or_oversized_tarball_degrades_to_metadata_only():
    def get_bytes(url, max_bytes=None):
        raise ValueError(f"response body exceeds {max_bytes} bytes")

    fetched = fetch(_packument_without_readme(), get_bytes=get_bytes)
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "npm-registry:json"


def test_no_tarball_url_skips_the_tarball_fetch():
    # version metadata without a dist.tarball never reaches the network
    pack = {**PACKUMENT, "readme": ""}
    pack["versions"] = {"4.18.2": {"name": "express", "version": "4.18.2"}}
    fetched = fetch(pack, get_bytes=no_network)
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "npm-registry:json"


def test_author_string_form_strips_email_and_url():
    pack = {**PACKUMENT, "author": "Jane Dev <jane@example.com> (https://jane.dev)"}
    assert fetch(pack).author == "Jane Dev"


def test_author_falls_back_to_first_maintainer():
    pack = {**PACKUMENT, "author": None}
    pack["versions"] = {"4.18.2": {"name": "express", "version": "4.18.2"}}
    assert fetch(pack).author == "dougwilson"


def test_release_date_falls_back_to_seeded_published_at():
    pack = {**PACKUMENT, "time": {"created": "2010-12-29T19:38:25.450Z"}}
    # latest version absent from time, no modified key -> keep the seeded date
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(pack, item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_release_date_falls_back_to_modified():
    pack = {**PACKUMENT, "time": {"modified": "2024-01-10T00:00:00.000Z"},
            "dist-tags": {}}
    assert fetch(pack).published_at == "2024-01-10T00:00:00+00:00"


def test_top_level_fields_fall_back_to_the_latest_version():
    # a packument without top-level descriptive fields still reads the version
    pack = {
        "name": "express",
        "dist-tags": {"latest": "4.18.2"},
        "versions": PACKUMENT["versions"],
        "time": PACKUMENT["time"],
    }
    fetched = fetch(pack)
    assert fetched.summary == "Fast, unopinionated, minimalist web framework"
    assert fetched.author == "TJ Holowaychuk"
    assert fetched.concepts[0] == "express"
    assert "https://github.com/expressjs/express" in fetched.links


def test_scoped_package_requests_the_encoded_registry_url():
    seen = []

    def get_json(url):
        seen.append(url)
        return {"name": "@babel/core", "dist-tags": {"latest": "7.24.0"},
                "versions": {"7.24.0": {"name": "@babel/core", "version": "7.24.0"}}}

    item = make_item(id="npm:@babel/core", source_id="@babel/core",
                     url="https://www.npmjs.com/package/@babel/core")
    fetched = fetch_item(item, get_json=get_json)
    assert seen == ["https://registry.npmjs.org/@babel%2Fcore"]
    assert fetched.title == "@babel/core"
    assert fetched.canonical_url == "https://www.npmjs.com/package/@babel/core"


def test_keeps_raw_records_for_rebuilds():
    raw = json.loads(fetch().raw_text)
    assert raw["dist-tags"]["latest"] == "4.18.2"
    assert raw["version"]["version"] == "4.18.2"
    assert raw["time"]["4.18.2"] == "2022-10-08T07:48:48.246Z"
    # the bulky all-versions blob and the readme aren't duplicated into raw
    assert "versions" not in raw
    assert "readme" not in raw


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://www.npmjs.com/package/express?activeTab=readme")
    fetched = fetch(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id)
    assert fetched.url == item.url  # the saved URL, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_requests_the_expected_api_url():
    seen = []

    def get_json(url):
        seen.append(url)
        return json.loads(json.dumps(PACKUMENT))

    fetch_item(make_item(), get_json=get_json)
    assert seen == ["https://registry.npmjs.org/express"]


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_a_package_name(source_id):
    item = make_item(id="npm:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine npm package"):
        fetch_item(item, get_json=fake_get_json())


def test_missing_package_is_a_fetch_error():
    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_item(), get_json=lambda url: {"error": "Not found"})


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom)


def test_npm_adapter_is_registered():
    assert FETCH_ADAPTERS["npm"] is fetch_item
