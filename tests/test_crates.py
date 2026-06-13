"""Tests for the crates.io fetch adapter (IDEAS.md §6, ADR 0036).

The JSON transport is faked with a crate document recorded (and trimmed)
from the real crates.io API, and the README from an in-memory `.crate`
tarball built in the test, so the field mapping, keyword/category
parsing, the repository-URL normalization that makes the crate↔repo link
resolve, version selection, release-date derivation, and error handling
are all covered offline (ADR 0001).
"""

import io
import json
import tarfile

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.crates import fetch_item


def make_tarball(files):
    """A gzipped `.crate` tarball with `files` mapping member path -> text."""
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


# Recorded (and trimmed) from https://crates.io/api/v1/crates/serde_json
CRATE_DOC = {
    "crate": {
        "id": "serde_json",
        "name": "serde_json",
        "description": "A JSON serialization file format",
        "homepage": None,
        "documentation": "https://docs.rs/serde_json",
        "repository": "https://github.com/serde-rs/json",
        "max_stable_version": "1.0.150",
        "newest_version": "1.0.150",
        "default_version": "1.0.150",
        "keywords": ["serialization", "json", "serde"],
        "categories": ["encoding", "no-std", "parser-implementations"],
        "created_at": "2015-08-07T19:04:18.632088Z",
        "updated_at": "2026-05-21T20:26:09.944672Z",
    },
    "versions": [
        {
            "num": "1.0.150",
            "created_at": "2026-05-21T20:26:09.944672Z",
            "dl_path": "/api/v1/crates/serde_json/1.0.150/download",
            "readme_path": "/api/v1/crates/serde_json/1.0.150/readme",
            "crate_size": 155574,
            "license": "MIT OR Apache-2.0",
            "published_by": {"id": 3618, "login": "dtolnay", "name": "David Tolnay"},
            "yanked": False,
        },
        {
            "num": "1.0.149",
            "created_at": "2026-04-01T00:00:00.000Z",
            "dl_path": "/api/v1/crates/serde_json/1.0.149/download",
            "published_by": {"login": "dtolnay", "name": "David Tolnay"},
            "yanked": False,
        },
    ],
    "keywords": [
        {"id": "serialization", "keyword": "serialization", "crates_cnt": 1343},
        {"id": "json", "keyword": "json", "crates_cnt": 1715},
        {"id": "serde", "keyword": "serde", "crates_cnt": 1408},
    ],
    "categories": [
        {"id": "encoding", "category": "Encoding", "slug": "encoding"},
        {"id": "no-std", "category": "No standard library", "slug": "no-std"},
        {
            "id": "parser-implementations",
            "category": "Parser implementations",
            "slug": "parser-implementations",
        },
    ],
}

README = "# Serde JSON\n\nServes JSON parsing and serialization for Rust.\n"


def make_item(**overrides):
    base = dict(
        id="crates:serde-json",
        source="crates",
        source_id="serde-json",
        url="https://crates.io/crates/serde_json",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_get_json(doc=CRATE_DOC):
    def get_json(url):
        return json.loads(json.dumps(doc))  # deep copy

    return get_json


def readme_tarball(url, max_bytes=None):
    return make_tarball(
        {
            "serde_json-1.0.150/README.md": README,
            "serde_json-1.0.150/src/lib.rs": "// code\n",
        }
    )


def fetch(doc=CRATE_DOC, item=None, get_bytes=readme_tarball):
    return fetch_item(
        item or make_item(), get_json=fake_get_json(doc), get_bytes=get_bytes
    )


def test_fetch_maps_metadata_and_readme():
    fetched = fetch()

    assert fetched.title == "serde_json"
    assert fetched.author == "David Tolnay"
    assert fetched.summary == "A JSON serialization file format"
    assert "JSON parsing and serialization" in fetched.extracted_text
    # canonical url uses the response's canonical name, not the normalized id
    assert fetched.canonical_url == "https://crates.io/crates/serde_json"
    # the displayed (default) version's publish time is the release moment
    assert fetched.published_at == "2026-05-21T20:26:09+00:00"
    assert fetched.provenance["adapter"] == "crates"
    assert fetched.provenance["extraction_method"] == "crates-api:json+tarball-readme"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_keywords_become_concepts_like_github_topics():
    assert fetch().concepts == ("serialization", "json", "serde")


def test_categories_become_tags_as_a_structured_taxonomy():
    # crates.io categories are a curated taxonomy -> tags (PyPI classifiers' slot);
    # the readable display name is used, not the slug.
    assert fetch().tags == ("Encoding", "No standard library", "Parser implementations")


def test_keywords_and_categories_fall_back_to_the_crate_string_lists():
    # an older/partial response without the rich top-level arrays still reads
    # the crate's own bare-string lists
    doc = {**CRATE_DOC}
    doc.pop("keywords")
    doc.pop("categories")
    fetched = fetch(doc)
    assert fetched.concepts == ("serialization", "json", "serde")
    assert fetched.tags == ("encoding", "no-std", "parser-implementations")


def test_links_carry_docs_and_normalized_repository():
    # serde_json has no homepage; docs + repository become links, the repo
    # resolvable to the same github repo by `scrolls related`
    assert fetch().links == (
        "https://docs.rs/serde_json",
        "https://github.com/serde-rs/json",
    )


def test_repository_dotgit_suffix_is_stripped():
    doc = json.loads(json.dumps(CRATE_DOC))
    doc["crate"]["repository"] = "https://github.com/serde-rs/json.git"
    links = fetch(doc).links
    assert "https://github.com/serde-rs/json" in links
    assert not any(link.endswith(".git") for link in links)


def test_no_keywords_or_categories_is_honestly_empty():
    doc = json.loads(json.dumps(CRATE_DOC))
    doc["keywords"] = []
    doc["categories"] = []
    doc["crate"]["keywords"] = []
    doc["crate"]["categories"] = []
    fetched = fetch(doc)
    assert fetched.concepts == ()
    assert fetched.tags == ()


def test_readme_picks_the_root_markdown_over_a_nested_one():
    def get_bytes(url, max_bytes=None):
        return make_tarball(
            {
                "serde_json-1.0.150/docs/README.md": "nested, not this one",
                "serde_json-1.0.150/README": "plain readme",
                "serde_json-1.0.150/README.md": "# root markdown readme",
            }
        )

    assert fetch(get_bytes=get_bytes).extracted_text == "# root markdown readme"


def test_tarball_with_no_readme_degrades_to_metadata_only():
    def get_bytes(url, max_bytes=None):
        return make_tarball({"serde_json-1.0.150/src/lib.rs": "// code\n"})

    fetched = fetch(get_bytes=get_bytes)
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "crates-api:json"


def test_failed_or_oversized_tarball_degrades_to_metadata_only():
    def get_bytes(url, max_bytes=None):
        raise ValueError(f"response body exceeds {max_bytes} bytes")

    fetched = fetch(get_bytes=get_bytes)
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "crates-api:json"


def test_tarball_is_downloaded_capped_from_the_dl_path():
    seen = []

    def get_bytes(url, max_bytes=None):
        seen.append((url, max_bytes))
        return readme_tarball(url, max_bytes)

    fetch(get_bytes=get_bytes)
    assert seen[0][0] == "https://crates.io/api/v1/crates/serde_json/1.0.150/download"
    assert seen[0][1] and seen[0][1] > 0


def test_no_dl_path_skips_the_tarball_fetch():
    doc = json.loads(json.dumps(CRATE_DOC))
    for v in doc["versions"]:
        v.pop("dl_path", None)
    fetched = fetch(doc, get_bytes=no_network)
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "crates-api:json"


def test_version_selection_prefers_default_version():
    doc = json.loads(json.dumps(CRATE_DOC))
    # point default_version at the older release; its date and dl_path win
    doc["crate"]["default_version"] = "1.0.149"
    seen = []

    def get_bytes(url, max_bytes=None):
        seen.append(url)
        return make_tarball({"serde_json-1.0.149/README.md": "old readme"})

    fetched = fetch(doc, get_bytes=get_bytes)
    assert fetched.published_at == "2026-04-01T00:00:00+00:00"
    assert seen[0].endswith("/serde_json/1.0.149/download")


def test_version_selection_falls_back_to_newest_then_first():
    doc = json.loads(json.dumps(CRATE_DOC))
    doc["crate"].pop("default_version")
    doc["crate"]["newest_version"] = "1.0.150"
    assert fetch(doc).published_at == "2026-05-21T20:26:09+00:00"


def test_publisher_falls_back_to_login():
    doc = json.loads(json.dumps(CRATE_DOC))
    doc["versions"][0]["published_by"] = {"login": "dtolnay"}
    assert fetch(doc).author == "dtolnay"


def test_missing_publisher_leaves_author_absent():
    doc = json.loads(json.dumps(CRATE_DOC))
    doc["versions"][0].pop("published_by")
    assert fetch(doc).author is None


def test_release_date_falls_back_to_seeded_published_at():
    doc = json.loads(json.dumps(CRATE_DOC))
    doc["versions"][0].pop("created_at")
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(doc, item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_non_string_created_at_does_not_crash():
    # a malformed/partial response (the kind _select_version anticipates)
    # degrades to the seed instead of raising in to_utc_iso
    doc = json.loads(json.dumps(CRATE_DOC))
    doc["versions"][0]["created_at"] = 1700000000
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(doc, item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_keeps_raw_records_for_rebuilds():
    raw = json.loads(fetch().raw_text)
    assert raw["crate"]["name"] == "serde_json"
    assert raw["version"]["num"] == "1.0.150"
    assert raw["keywords"][0]["keyword"] == "serialization"
    assert raw["categories"][0]["category"] == "Encoding"


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://crates.io/crates/serde_json/1.0.150")
    fetched = fetch(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id)
    assert fetched.url == item.url  # the saved URL, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_requests_the_expected_api_url():
    seen = []

    def get_json(url):
        seen.append(url)
        return json.loads(json.dumps(CRATE_DOC))

    fetch_item(make_item(), get_json=get_json, get_bytes=readme_tarball)
    assert seen == ["https://crates.io/api/v1/crates/serde-json"]


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_a_crate_name(source_id):
    item = make_item(id="crates:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine crate"):
        fetch_item(item, get_json=fake_get_json())


def test_missing_crate_is_a_fetch_error():
    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_item(), get_json=lambda url: {"errors": [{"detail": "Not Found"}]})


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom)


def test_crates_adapter_is_registered():
    assert FETCH_ADAPTERS["crates"] is fetch_item
