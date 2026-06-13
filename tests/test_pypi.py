"""Tests for the PyPI fetch adapter (IDEAS.md §6, ADR 0034).

The JSON transport is faked with a payload recorded (and trimmed) from
the real PyPI JSON API, so the field mapping, keyword parsing,
classifiers→tags, project-urls→links dedupe, the "UNKNOWN" legacy
sentinel, release-date derivation, and error handling are all covered
offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.pypi import fetch_item

# Recorded (and trimmed) from https://pypi.org/pypi/rich/json
INFO = {
    "name": "rich",
    "version": "13.7.1",
    "summary": "Render rich text, tables, progress bars, syntax highlighting, "
    "markdown and more to the terminal",
    "description": "# Rich\n\nRich is a Python library for rich text and beautiful "
    "formatting in the terminal.\n\n## Installation\n\n    pip install rich\n",
    "description_content_type": "text/markdown",
    "author": "Will McGugan",
    "author_email": "willmcgugan@gmail.com",
    "maintainer": "",
    "keywords": "ansi,color,console,markdown,rich,syntax,tables,terminal",
    "license": "MIT",
    "home_page": "https://github.com/Textualize/rich",
    "package_url": "https://pypi.org/project/rich/",
    "project_url": "https://pypi.org/project/rich/",
    "project_urls": {
        "Documentation": "https://rich.readthedocs.io/en/latest/",
        "Homepage": "https://github.com/Textualize/rich",
        "Source": "https://github.com/Textualize/rich",
    },
    "requires_python": ">=3.7.0",
    "classifiers": [
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.11",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
}

URLS = [
    {
        "filename": "rich-13.7.1-py3-none-any.whl",
        "upload_time_iso_8601": "2024-02-28T14:13:24.873920Z",
    },
    {
        "filename": "rich-13.7.1.tar.gz",
        "upload_time_iso_8601": "2024-02-28T14:13:27.331600Z",
    },
]


def make_item(**overrides):
    base = dict(
        id="pypi:rich",
        source="pypi",
        source_id="rich",
        url="https://pypi.org/project/rich/",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_get_json(info=INFO, urls=URLS):
    def get_json(url):
        return {"info": dict(info), "urls": [dict(u) for u in urls]}

    return get_json


def fetch(info=INFO, urls=URLS, item=None):
    return fetch_item(item or make_item(), get_json=fake_get_json(info, urls))


def test_fetch_maps_metadata_and_description():
    fetched = fetch()

    assert fetched.title == "rich"
    assert fetched.author == "Will McGugan"
    assert fetched.summary.startswith("Render rich text")
    assert "beautiful formatting in the terminal" in fetched.extracted_text
    assert fetched.canonical_url == "https://pypi.org/project/rich/"
    # the latest release's earliest file upload is the publish moment
    assert fetched.published_at == "2024-02-28T14:13:24+00:00"
    assert fetched.provenance["adapter"] == "pypi"
    assert fetched.provenance["extraction_method"] == "pypi-api:json+description"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_keywords_become_concepts_like_github_topics():
    # comma-separated keywords split into concepts (ADR 0007 parallel)
    assert fetch().concepts == (
        "ansi", "color", "console", "markdown", "rich", "syntax", "tables", "terminal",
    )


def test_keywords_accept_a_list_and_whitespace_forms():
    # metadata 2.x exposes keywords as a list
    assert fetch(info={**INFO, "keywords": ["http", "client"]}).concepts == ("http", "client")
    # legacy space-separated keywords (no commas) split on whitespace
    assert fetch(info={**INFO, "keywords": "http  client api"}).concepts == (
        "http", "client", "api",
    )
    assert fetch(info={**INFO, "keywords": ""}).concepts == ()


def test_classifiers_become_tags():
    tags = fetch().tags
    assert "Programming Language :: Python :: 3.11" in tags
    assert "Topic :: Software Development :: Libraries :: Python Modules" in tags
    assert len(tags) == len(set(tags))  # deduped, order preserved


def test_project_urls_become_links_deduped_without_the_pypi_page():
    links = fetch().links
    # home_page + project_urls, collapsed by trailing slash, pypi page dropped
    assert links == (
        "https://github.com/Textualize/rich",
        "https://rich.readthedocs.io/en/latest/",
    )
    # the github link lets `scrolls related` connect a package to its repo
    assert "https://pypi.org/project/rich/" not in links


def test_unknown_sentinel_and_blanks_become_absent():
    legacy = {**INFO, "author": "UNKNOWN", "summary": "UNKNOWN", "description": "UNKNOWN",
              "maintainer": ""}
    fetched = fetch(info=legacy)
    assert fetched.author is None
    assert fetched.summary is None
    assert fetched.extracted_text is None
    # no description: hashed over the raw record, method records json-only
    assert fetched.provenance["extraction_method"] == "pypi-api:json"


def test_author_falls_back_to_maintainer():
    info = {**INFO, "author": "", "maintainer": "The Maintainers"}
    assert fetch(info=info).author == "The Maintainers"


def test_release_date_falls_back_to_seeded_published_at():
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(urls=[], item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_keeps_raw_records_for_rebuilds():
    raw = json.loads(fetch().raw_text)
    assert raw["info"]["version"] == "13.7.1"
    assert raw["urls"][0]["filename"] == "rich-13.7.1-py3-none-any.whl"


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://pypi.org/project/rich/?utm_source=newsletter")
    fetched = fetch(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (item.id, item.source, item.source_id)
    assert fetched.url == item.url  # the saved URL, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_requests_the_expected_api_url():
    seen = []

    def get_json(url):
        seen.append(url)
        return {"info": dict(INFO), "urls": [dict(u) for u in URLS]}

    fetch_item(make_item(), get_json=get_json)
    assert seen == ["https://pypi.org/pypi/rich/json"]


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_a_project_name(source_id):
    item = make_item(id="pypi:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine pypi project"):
        fetch_item(item, get_json=fake_get_json())


def test_missing_project_is_a_fetch_error():
    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_item(), get_json=lambda url: {"message": "Not Found"})


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom)


def test_pypi_adapter_is_registered():
    assert FETCH_ADAPTERS["pypi"] is fetch_item
