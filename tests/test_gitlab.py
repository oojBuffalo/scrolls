"""Tests for the GitLab fetch adapter (IDEAS.md §6, ADR 0055).

The JSON and text transports are faked; tests cover the README-optional
fetch semantics, the topics → concepts and license → tags mappings, the
nested-group path encoding, and the keyless/token headers — all offline.
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.gitlab import _api_headers, fetch_item

PROJECT = {
    "id": 13083,
    "name": "Inkscape",
    "path_with_namespace": "inkscape/inkscape",
    "web_url": "https://gitlab.com/inkscape/inkscape",
    "description": "Inkscape vector graphics editor.",
    "namespace": {"name": "Inkscape", "path": "inkscape", "full_path": "inkscape"},
    "created_at": "2015-06-29T15:55:31.232Z",
    "last_activity_at": "2026-06-01T08:00:00.000Z",
    "topics": ["vector-graphics", "svg", "design"],
    "default_branch": "master",
    "readme_url": "https://gitlab.com/inkscape/inkscape/-/blob/master/README.md",
    "license": {"key": "gpl-3.0", "name": "GNU General Public License v3.0"},
}

README_TEXT = "# Inkscape\n\nAn open-source vector graphics editor.\n"
README_RAW_URL = "https://gitlab.com/inkscape/inkscape/-/raw/master/README.md"


def make_item(**overrides):
    base = dict(
        id="gitlab:inkscape/inkscape",
        source="gitlab",
        source_id="inkscape/inkscape",
        url="https://gitlab.com/inkscape/inkscape",
        saved_at="2026-06-12T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def routed(project=PROJECT, readme=README_TEXT):
    def get_json(url):
        return dict(project)

    def get_text(url):
        if readme is None:
            raise OSError("HTTP Error 404: Not Found")
        return readme

    return get_json, get_text


def fetch(item=None, **kwargs):
    get_json, get_text = routed(**kwargs)
    return fetch_item(item or make_item(), get_json=get_json, get_text=get_text)


def test_fetch_item_with_readme():
    fetched = fetch()

    assert fetched.title == "inkscape/inkscape"
    assert fetched.author == "inkscape"
    assert fetched.published_at == "2015-06-29T15:55:31+00:00"  # ms-precision date normalized
    assert fetched.canonical_url == "https://gitlab.com/inkscape/inkscape"
    assert fetched.summary == PROJECT["description"]
    assert fetched.extracted_text == README_TEXT
    assert fetched.concepts == ("vector-graphics", "svg", "design")
    assert fetched.tags == ("gpl-3.0",)
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.provenance["adapter"] == "gitlab"
    assert fetched.provenance["extraction_method"] == "gitlab-api:project+readme"
    assert fetched.stage == "fetched"


def test_fetch_item_keeps_raw_records_for_rebuilds():
    fetched = fetch()
    raw = json.loads(fetched.raw_text)
    assert raw["project"]["path_with_namespace"] == "inkscape/inkscape"
    assert raw["readme"] == README_TEXT


def test_fetch_item_preserves_identity_fields():
    item = make_item(url="https://gitlab.com/inkscape/inkscape/-/issues/7")
    fetched = fetch(item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url  # the URL the user saved, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_fetch_item_keeps_seeded_published_at_when_project_has_no_created_at():
    # a feed-seeded date (ADR 0021) survives a fetch that finds no date
    project = {key: value for key, value in PROJECT.items() if key != "created_at"}
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    get_json, get_text = routed(project=project)
    fetched = fetch_item(item, get_json=get_json, get_text=get_text)
    assert fetched.published_at == "2026-06-01T00:00:00+00:00"


def test_fetch_item_url_encodes_nested_group_path():
    seen = []

    def get_json(url):
        seen.append(url)
        return dict(PROJECT)

    def get_text(url):
        seen.append(url)
        return README_TEXT

    item = make_item(
        id="gitlab:group/subgroup/project",
        source_id="group/subgroup/project",
        url="https://gitlab.com/group/subgroup/project",
    )
    fetch_item(item, get_json=get_json, get_text=get_text)
    assert seen[0] == (
        "https://gitlab.com/api/v4/projects/group%2Fsubgroup%2Fproject?license=true"
    )
    # the README is fetched from the project's raw route, not refetched by path
    assert seen[1] == README_RAW_URL


def test_fetch_item_requests_the_readme_raw_route():
    seen = []
    get_json, _ = routed()

    def capture_text(url):
        seen.append(url)
        return README_TEXT

    fetch_item(make_item(), get_json=get_json, get_text=capture_text)
    assert seen == [README_RAW_URL]


def test_fetch_item_without_readme_url_degrades_to_metadata_only():
    project = {key: value for key, value in PROJECT.items() if key != "readme_url"}
    fetched = fetch(project=project)
    assert fetched.extracted_text is None
    assert json.loads(fetched.raw_text)["readme"] is None
    assert fetched.provenance["extraction_method"] == "gitlab-api:project"
    assert fetched.stage == "fetched"


def test_fetch_item_with_failing_readme_degrades_to_metadata_only():
    fetched = fetch(readme=None)  # the raw GET 404s
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "gitlab-api:project"


def test_fetch_item_treats_blank_readme_as_metadata_only():
    fetched = fetch(readme="   \n\n")
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "gitlab-api:project"


def test_fetch_item_ignores_non_blob_readme_url():
    # a readme_url that isn't a /-/blob/ route can't be rewritten to /-/raw/
    project = {**PROJECT, "readme_url": "https://gitlab.com/inkscape/inkscape/wikis/home"}
    fetched = fetch(project=project)
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "gitlab-api:project"


def test_fetch_item_falls_back_to_tag_list_for_topics():
    project = {key: value for key, value in PROJECT.items() if key != "topics"}
    project["tag_list"] = ["legacy", "tags"]
    fetched = fetch(project=project)
    assert fetched.concepts == ("legacy", "tags")


def test_fetch_item_without_topics_has_no_concepts():
    project = {key: value for key, value in PROJECT.items()
               if key not in ("topics", "tag_list")}
    fetched = fetch(project=project)
    assert fetched.concepts == ()


def test_fetch_item_without_license_has_no_tags():
    project = {key: value for key, value in PROJECT.items() if key != "license"}
    fetched = fetch(project=project)
    assert fetched.tags == ()


def test_fetch_item_without_description_has_no_summary():
    fetched = fetch(project={**PROJECT, "description": None})
    assert fetched.summary is None


def test_fetch_item_requires_a_project_id():
    item = make_item(id="gitlab:abc123def456", source_id=None,
                     url="https://gitlab.com/explore")
    with pytest.raises(FetchError, match="cannot determine gitlab project"):
        fetch_item(item)


def test_fetch_item_wraps_project_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom, get_text=lambda url: README_TEXT)


def test_api_headers_are_keyless_by_default(monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    assert _api_headers() == {}


def test_api_headers_use_gitlab_token_when_set(monkeypatch):
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-example")
    assert _api_headers() == {"PRIVATE-TOKEN": "glpat-example"}


def test_gitlab_adapter_is_registered():
    assert FETCH_ADAPTERS["gitlab"] is fetch_item
