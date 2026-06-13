"""Tests for the GitHub Gist fetch adapter (IDEAS.md §6, ADR 0078).

The JSON transport is faked; tests cover the one-request fetch (files inlined),
the files→`extracted_text` rendering, the distinct-languages→`tags` mapping with
empty `concepts` by design, the manifest summary, the description/first-filename
title, the all-blank-files degrade, the no-category-default decision, and the
keyless/token headers — all offline.
"""

import json

import pytest

from scrolls.classify import classify_item
from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.gist import _api_headers, fetch_item

GIST_ID = "0123456789abcdef0123456789abcdef"

GIST = {
    "id": GIST_ID,
    "html_url": f"https://gist.github.com/octocat/{GIST_ID}",
    "description": "Handy SQLite FTS snippets",
    "public": True,
    "created_at": "2021-03-04T09:00:00Z",
    "updated_at": "2021-03-05T10:00:00Z",
    "owner": {"login": "octocat", "type": "User"},
    "comments": 2,
    "files": {
        "search.py": {
            "filename": "search.py",
            "type": "application/x-python",
            "language": "Python",
            "size": 64,
            "truncated": False,
            "content": "import sqlite3\nprint('fts')\n",
        },
        "notes.md": {
            "filename": "notes.md",
            "type": "text/markdown",
            "language": "Markdown",
            "size": 20,
            "truncated": False,
            "content": "BM25 ranking notes\n",
        },
    },
}


def make_item(**overrides):
    base = dict(
        id=f"gist:{GIST_ID}",
        source="gist",
        source_id=GIST_ID,
        url=f"https://gist.github.com/octocat/{GIST_ID}",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fetch(item=None, gist=GIST):
    return fetch_item(item or make_item(), get_json=lambda url: dict(gist))


def test_fetch_item_maps_the_gist():
    fetched = fetch()

    assert fetched.title == "Handy SQLite FTS snippets"  # description is the title
    assert fetched.author == "octocat"
    assert fetched.published_at == "2021-03-04T09:00:00+00:00"
    assert fetched.canonical_url == f"https://gist.github.com/octocat/{GIST_ID}"
    assert fetched.summary == "2 files: notes.md, search.py"  # the manifest, sorted
    assert fetched.tags == ("Markdown", "Python")  # distinct languages, by filename
    assert fetched.concepts == ()  # a gist has no topic facet, by design
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.provenance["adapter"] == "gist"
    assert fetched.provenance["extraction_method"] == "github-api:gist"
    assert fetched.stage == "fetched"


def test_extracted_text_renders_each_file_as_a_sorted_fenced_section():
    body = fetch().extracted_text
    # files emitted in sorted-filename order (notes.md before search.py)
    assert body == (
        "### notes.md\n\n```markdown\nBM25 ranking notes\n\n```\n\n"
        "### search.py\n\n```python\nimport sqlite3\nprint('fts')\n\n```"
    )


def test_one_request_only():
    seen = []

    def get_json(url):
        seen.append(url)
        return dict(GIST)

    fetch_item(make_item(), get_json=get_json)
    assert seen == [f"https://api.github.com/gists/{GIST_ID}"]


def test_languages_dedupe_and_skip_files_without_a_language():
    gist = {
        **GIST,
        "files": {
            "a.py": {"language": "Python", "content": "a"},
            "b.py": {"language": "Python", "content": "b"},  # duplicate language
            "data.txt": {"language": None, "content": "raw"},  # no language
        },
    }
    fetched = fetch(gist=gist)
    assert fetched.tags == ("Python",)


def test_gist_without_description_titles_from_first_filename():
    gist = {**GIST, "description": ""}
    fetched = fetch(gist=gist)
    assert fetched.title == "notes.md"  # first filename, sorted
    assert fetched.summary == "2 files: notes.md, search.py"  # summary unchanged


def test_anonymous_gist_has_no_author():
    gist = {key: value for key, value in GIST.items() if key != "owner"}
    fetched = fetch(gist=gist)
    assert fetched.author is None


def test_blank_files_degrade_to_metadata_only():
    gist = {
        **GIST,
        "files": {"empty.txt": {"language": None, "content": "   \n\n"}},
    }
    fetched = fetch(gist=gist)
    assert fetched.extracted_text is None
    # the hash falls back to the gist JSON when there is no body
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.summary == "1 file: empty.txt"  # singular
    assert fetched.stage == "fetched"


def test_keeps_raw_gist_json_for_rebuilds():
    raw = json.loads(fetch().raw_text)
    assert raw["id"] == GIST_ID
    assert set(raw["files"]) == {"search.py", "notes.md"}


def test_preserves_identity_fields():
    item = make_item(url=f"https://gist.github.com/octocat/{GIST_ID}/revisions")
    fetched = fetch(item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url  # the URL the user saved, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_keeps_seeded_published_at_when_gist_has_no_created_at():
    gist = {key: value for key, value in GIST.items() if key != "created_at"}
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    fetched = fetch_item(item, get_json=lambda url: dict(gist))
    assert fetched.published_at == "2026-06-01T00:00:00+00:00"


def test_gist_has_no_category_default():
    # A gist is heterogeneous (config/script/repro), so — like a Hacker News
    # post — the rules engine leaves it unclassified rather than guessing.
    assert classify_item(fetch()).category is None


def test_fetch_item_requires_a_source_id():
    item = make_item(source_id=None, url="https://gist.github.com/octocat")
    with pytest.raises(FetchError, match="cannot determine gist id"):
        fetch_item(item)


def test_fetch_item_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom)


def test_api_headers_are_keyless_by_default(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    headers = _api_headers()
    assert "Authorization" not in headers
    assert headers["Accept"] == "application/vnd.github+json"


def test_api_headers_use_bearer_token_when_set(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-example")
    assert _api_headers()["Authorization"] == "Bearer ghp-example"


def test_gist_adapter_is_registered():
    assert FETCH_ADAPTERS["gist"] is fetch_item
