"""Tests for the Bitbucket Cloud fetch adapter (IDEAS.md §6, ADR 0057).

The JSON and text transports are faked; tests cover the README-optional fetch
semantics (README.md-first via the `/src/<mainbranch>` route, a root-listing
fallback for a differently-named README), the empty-`concepts`-by-design /
`language`→`tag` mapping, the single fixed API host (not host-in-id like gitea),
and the keyless/Bearer-token headers — all offline.
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.bitbucket import _api_headers, fetch_item

REPO = {
    "full_name": "atlassian/atlassian-plugins",
    "name": "atlassian-plugins",
    "slug": "atlassian-plugins",
    "description": "Atlassian plugin framework.",
    "scm": "git",
    "language": "java",
    "is_private": False,
    "created_on": "2011-10-13T23:37:59.955067+00:00",
    "updated_on": "2024-01-02T10:00:00.000000+00:00",
    "mainbranch": {"name": "master", "type": "branch"},
    "owner": {"display_name": "Atlassian", "username": "atlassian", "type": "team"},
    "links": {"html": {"href": "https://bitbucket.org/atlassian/atlassian-plugins"}},
}

README_TEXT = "# Atlassian Plugins\n\nThe plugin framework.\n"
REPO_API = "https://api.bitbucket.org/2.0/repositories/atlassian/atlassian-plugins"
README_RAW_URL = f"{REPO_API}/src/master/README.md"

# A root listing with a non-.md README (the only time the listing is consulted):
# README.md-first misses, so the adapter lists to find README.rst.
RST_LISTING = {
    "values": [
        {"path": "LICENSE", "type": "commit_file"},
        {"path": "src", "type": "commit_directory"},
        {"path": "README.rst", "type": "commit_file"},
    ]
}


def make_item(**overrides):
    base = dict(
        id="bitbucket:atlassian/atlassian-plugins",
        source="bitbucket",
        source_id="atlassian/atlassian-plugins",
        url="https://bitbucket.org/atlassian/atlassian-plugins",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def routed(repo=REPO, listing=None, files=None):
    """A (get_json, get_text) pair dispatching on the URL shape.

    `files` maps a raw filepath to its body (default `{"README.md": README_TEXT}`);
    an absent path 404s. `listing` is the root listing the fallback fetches
    (`None` makes the listing fail — the slow/failed-listing degrade).
    """
    if files is None:
        files = {"README.md": README_TEXT}

    def get_json(url):
        if "/src/" in url:  # the root listing has a trailing slash + ?pagelen
            if listing is None:
                raise OSError("HTTP Error 404: Not Found")
            return dict(listing)
        return dict(repo)

    def get_text(url):
        path = url.split("/src/master/", 1)[1]
        if path not in files:
            raise OSError("HTTP Error 404: Not Found")
        return files[path]

    return get_json, get_text


def fetch(item=None, **kwargs):
    get_json, get_text = routed(**kwargs)
    return fetch_item(item or make_item(), get_json=get_json, get_text=get_text)


def test_fetch_item_with_readme():
    fetched = fetch()

    assert fetched.title == "atlassian/atlassian-plugins"
    assert fetched.author == "Atlassian"
    assert fetched.published_at == "2011-10-13T23:37:59+00:00"  # microseconds dropped
    assert fetched.canonical_url == "https://bitbucket.org/atlassian/atlassian-plugins"
    assert fetched.summary == REPO["description"]
    assert fetched.extracted_text == README_TEXT
    assert fetched.concepts == ()  # Bitbucket Cloud has no topics, by design
    assert fetched.tags == ("java",)  # language is the one facet
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.provenance["adapter"] == "bitbucket"
    assert fetched.provenance["extraction_method"] == "bitbucket-api:repo+readme"
    assert fetched.stage == "fetched"


def test_fetch_item_keeps_raw_records_for_rebuilds():
    fetched = fetch()
    raw = json.loads(fetched.raw_text)
    assert raw["repo"]["full_name"] == "atlassian/atlassian-plugins"
    assert raw["readme"] == README_TEXT


def test_fetch_item_preserves_identity_fields():
    item = make_item(url="https://bitbucket.org/atlassian/atlassian-plugins/src/master/")
    fetched = fetch(item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url  # the URL the user saved, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_readme_md_first_is_one_fast_call_no_listing():
    # The dominant case (a root README.md) is a single keyless src GET; the
    # repo-root listing is never touched (the gitea fast-path rule, ADR 0056).
    seen = []

    def get_json(url):
        seen.append(url)
        return dict(REPO)

    def get_text(url):
        seen.append(url)
        return README_TEXT

    fetch_item(make_item(), get_json=get_json, get_text=get_text)
    assert seen == [REPO_API, README_RAW_URL]
    assert all("?pagelen" not in u for u in seen)


def test_single_fixed_api_host_regardless_of_workspace():
    # Unlike gitea, the API host is fixed (api.bitbucket.org) — Bitbucket Cloud
    # is one service, so the workspace rides only in the path, not a per-host API.
    seen = []

    def get_json(url):
        seen.append(url)
        return {"full_name": "team/widget", "mainbranch": {"name": "main"}}

    def get_text(url):
        seen.append(url)
        return "# widget"

    item = make_item(
        id="bitbucket:team/widget",
        source_id="team/widget",
        url="https://bitbucket.org/team/widget",
    )
    fetch_item(item, get_json=get_json, get_text=get_text)
    assert seen[0] == "https://api.bitbucket.org/2.0/repositories/team/widget"
    assert "https://api.bitbucket.org/2.0/repositories/team/widget/src/main/README.md" in seen


def test_readme_uses_main_branch_from_the_repo_payload():
    # The src route needs a commit-ish; the adapter reads `mainbranch.name`, so a
    # repo on `develop` fetches README from /src/develop/, not a hardcoded branch.
    seen = []

    def get_json(url):
        return {**REPO, "mainbranch": {"name": "develop"}}

    def get_text(url):
        seen.append(url)
        return README_TEXT

    fetch_item(make_item(), get_json=get_json, get_text=get_text)
    assert seen == [f"{REPO_API}/src/develop/README.md"]


def test_readme_falls_back_to_listing_for_non_markdown_readme():
    # No README.md, so the adapter lists the root and finds README.rst.
    fetched = fetch(listing=RST_LISTING, files={"README.rst": "RST body"})
    assert fetched.extracted_text == "RST body"
    assert fetched.provenance["extraction_method"] == "bitbucket-api:repo+readme"


def test_readme_listing_prefers_markdown_over_other_formats():
    # If README.md is absent from the raw route but a listing has both a .md and
    # a .rst, the .md still wins (the listing path's tiebreak).
    listing = {
        "values": [
            {"path": "README.rst", "type": "commit_file"},
            {"path": "README.markdown", "type": "commit_file"},
        ]
    }
    seen = []

    def get_json(url):
        return dict(listing) if "/src/" in url else dict(REPO)

    def get_text(url):
        seen.append(url)
        path = url.split("/src/master/", 1)[1]
        if path == "README.md":
            raise OSError("404")
        return "MD body"

    fetched = fetch_item(make_item(), get_json=get_json, get_text=get_text)
    assert fetched.extracted_text == "MD body"
    assert seen[-1] == f"{REPO_API}/src/master/README.markdown"  # .markdown beat .rst


def test_readme_listing_ignores_directories_named_like_readme():
    # A `readme/` directory in the root must not be mistaken for the README file.
    listing = {
        "values": [
            {"path": "readme", "type": "commit_directory"},
            {"path": "README.txt", "type": "commit_file"},
        ]
    }
    fetched = fetch(listing=listing, files={"README.txt": "TXT body"})
    assert fetched.extracted_text == "TXT body"


def test_fetch_item_without_any_readme_degrades_to_metadata_only():
    listing = {"values": [{"path": "main.py", "type": "commit_file"}]}
    fetched = fetch(listing=listing, files={})  # no README.md, none in listing
    assert fetched.extracted_text is None
    assert json.loads(fetched.raw_text)["readme"] is None
    assert fetched.provenance["extraction_method"] == "bitbucket-api:repo"
    assert fetched.stage == "fetched"


def test_fetch_item_with_failing_listing_degrades_to_metadata_only():
    fetched = fetch(listing=None, files={})  # README.md 404s, then listing 404s
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "bitbucket-api:repo"


def test_fetch_item_without_main_branch_skips_readme():
    # An empty repo has no main branch, so there is no src path to fetch.
    repo = {key: value for key, value in REPO.items() if key != "mainbranch"}
    fetched = fetch(repo=repo, files={})
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "bitbucket-api:repo"


def test_fetch_item_treats_blank_readme_as_metadata_only():
    # A present-but-blank README.md is honestly metadata-only; the listing
    # fallback skips README.md so it isn't re-fetched.
    listing = {"values": [{"path": "README.md", "type": "commit_file"}]}
    fetched = fetch(listing=listing, files={"README.md": "   \n\n"})
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "bitbucket-api:repo"


def test_fetch_item_without_language_has_no_tags():
    fetched = fetch(repo={**REPO, "language": ""})
    assert fetched.tags == ()


def test_fetch_item_without_description_has_no_summary():
    fetched = fetch(repo={**REPO, "description": ""})
    assert fetched.summary is None


def test_author_falls_back_to_handle_when_no_display_name():
    fetched = fetch(repo={**REPO, "owner": {"nickname": "octo"}})
    assert fetched.author == "octo"


def test_fetch_item_keeps_seeded_published_at_when_repo_has_no_created_on():
    repo = {key: value for key, value in REPO.items() if key != "created_on"}
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    get_json, get_text = routed(repo=repo)
    fetched = fetch_item(item, get_json=get_json, get_text=get_text)
    assert fetched.published_at == "2026-06-01T00:00:00+00:00"


def test_fetch_item_requires_a_repo_id():
    # a workspace-only id (no repo) is a profile/site route, not fetchable
    item = make_item(
        id="bitbucket:atlassian", source_id="atlassian",
        url="https://bitbucket.org/atlassian",
    )
    with pytest.raises(FetchError, match="cannot determine bitbucket repository"):
        fetch_item(item)


def test_fetch_item_requires_a_source_id():
    item = make_item(source_id=None, url="https://bitbucket.org/")
    with pytest.raises(FetchError, match="cannot determine bitbucket repository"):
        fetch_item(item)


def test_fetch_item_wraps_repo_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom, get_text=lambda url: README_TEXT)


def test_api_headers_are_keyless_by_default(monkeypatch):
    monkeypatch.delenv("BITBUCKET_TOKEN", raising=False)
    assert _api_headers() == {}


def test_api_headers_use_bearer_token_when_set(monkeypatch):
    monkeypatch.setenv("BITBUCKET_TOKEN", "bb-example")
    assert _api_headers() == {"Authorization": "Bearer bb-example"}


def test_bitbucket_adapter_is_registered():
    assert FETCH_ADAPTERS["bitbucket"] is fetch_item
