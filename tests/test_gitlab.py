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


# --- issues and merge requests (ADR 0085) ---------------------------------
#
# A `/-/issues/<n>` or `/-/merge_requests/<n>` URL detects as a discussion
# thread in GitLab's own cross-reference notation — `group/project#<n>` for an
# issue, `group/project!<n>` for a merge request (GitLab keeps separate iid
# sequences, so the marker disambiguates). The same `gitlab` source/adapter
# serves it, dispatched on the marker in the source id, which also picks the
# endpoint (`/issues/<iid>` vs `/merge_requests/<iid>`).

ISSUE = {
    "iid": 7,
    "title": "FTS5 ranking returns stale results",
    "description": "Rebuilding the index lags BM25 ranking.\n\nSee https://example.com/bug.",
    "web_url": "https://gitlab.com/gitlab-org/gitlab/-/issues/7",
    "author": {"username": "alice", "name": "Alice A."},
    "state": "opened",
    "created_at": "2026-05-10T09:00:00.000Z",
    "user_notes_count": 2,
    "labels": ["bug", "search"],
}

MERGE_REQUEST = {
    "iid": 42,
    "title": "Add faceted search",
    "description": "Implements `--source`/`--category` filters.",
    "web_url": "https://gitlab.com/gitlab-org/gitlab/-/merge_requests/42",
    "author": {"username": "bob", "name": "Bob B."},
    "state": "merged",
    "created_at": "2026-05-12T10:00:00.000Z",
    "user_notes_count": 0,
    "labels": ["enhancement"],
}

NOTES = [
    {"system": False, "author": {"username": "carol"}, "body": "I can repro this on main."},
    # a system note (label change, assignment) is automated activity, not content
    {"system": True, "author": {"username": "alice"}, "body": "changed the milestone to v2"},
    {"system": False, "author": {"username": "alice"}, "body": "Fixed by the rebuild trigger."},
]


def thread_item(source_id="gitlab-org/gitlab#7", **overrides):
    base = dict(
        id=f"gitlab:{source_id}",
        source="gitlab",
        source_id=source_id,
        url="https://gitlab.com/gitlab-org/gitlab/-/issues/7",
        saved_at="2026-06-12T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def routed_thread(thread=ISSUE, notes=NOTES):
    def get_json(url):
        if "/notes" in url:
            return [dict(n) for n in notes]
        return dict(thread)

    return get_json


def fetch_thread(item=None, **kwargs):
    return fetch_item(item or thread_item(), get_json=routed_thread(**kwargs))


def test_fetch_issue_maps_thread_fields():
    fetched = fetch_thread()

    assert fetched.title == "gitlab-org/gitlab#7: FTS5 ranking returns stale results"
    assert fetched.author == "alice"  # the username, not the display name
    assert fetched.published_at == "2026-05-10T09:00:00+00:00"
    assert fetched.canonical_url == "https://gitlab.com/gitlab-org/gitlab/-/issues/7"
    # labels are the curated topical facet → concepts (the github-topics rule)
    assert fetched.concepts == ("bug", "search")
    # kind + state are the facet slot → tags; `opened` normalizes to github's `open`
    assert fetched.tags == ("issue", "open")
    assert fetched.summary == "Rebuilding the index lags BM25 ranking."
    assert fetched.provenance["adapter"] == "gitlab"
    assert fetched.provenance["extraction_method"] == "gitlab-api:issue+notes"
    assert fetched.stage == "fetched"


def test_fetch_issue_body_and_notes_become_extracted_text():
    fetched = fetch_thread()
    assert "Rebuilding the index lags BM25 ranking." in fetched.extracted_text
    assert "Comment by carol" in fetched.extracted_text
    assert "I can repro this on main." in fetched.extracted_text
    assert "Comment by alice" in fetched.extracted_text
    # the system note is dropped — it is automated activity, not discussion
    assert "changed the milestone" not in fetched.extracted_text


def test_fetch_thread_links_carry_the_project_edge_and_body_urls():
    fetched = fetch_thread()
    # the thread belongs to its project (thread↔project edge → gitlab:group/project)
    assert "https://gitlab.com/gitlab-org/gitlab" in fetched.links
    # a URL referenced in the description becomes an outbound edge
    assert "https://example.com/bug" in fetched.links
    # the thread's own URL is never a self-link
    assert fetched.canonical_url not in fetched.links


def test_fetch_thread_keeps_raw_records_for_rebuilds():
    fetched = fetch_thread()
    raw = json.loads(fetched.raw_text)
    assert raw["thread"]["iid"] == 7
    # the system note is preserved in raw_text for rebuilds, only filtered from content
    assert len(raw["notes"]) == 3


def test_fetch_merge_request_is_tagged_and_merge_aware():
    item = thread_item(source_id="gitlab-org/gitlab!42",
                       url="https://gitlab.com/gitlab-org/gitlab/-/merge_requests/42")
    fetched = fetch_item(item, get_json=routed_thread(thread=MERGE_REQUEST))
    assert fetched.title == "gitlab-org/gitlab!42: Add faceted search"
    # GitLab reports a merged MR's state directly (no merged_at derivation needed)
    assert fetched.tags == ("merge request", "merged")
    assert fetched.concepts == ("enhancement",)
    assert fetched.provenance["extraction_method"] == "gitlab-api:merge_request"


def test_fetch_thread_dispatches_to_the_right_endpoint():
    seen = []

    def capture(url):
        seen.append(url)
        return dict(MERGE_REQUEST)

    item = thread_item(source_id="gitlab-org/gitlab!42")
    fetch_item(item, get_json=capture)
    # the `!` marker routes to /merge_requests, and user_notes_count == 0 skips notes
    assert seen == [
        "https://gitlab.com/api/v4/projects/gitlab-org%2Fgitlab/merge_requests/42"
    ]


def test_fetch_issue_requests_the_expected_api_urls():
    seen = []
    routed = routed_thread()

    def capture(url):
        seen.append(url)
        return routed(url)

    fetch_item(thread_item(), get_json=capture)
    assert seen == [
        "https://gitlab.com/api/v4/projects/gitlab-org%2Fgitlab/issues/7",
        "https://gitlab.com/api/v4/projects/gitlab-org%2Fgitlab/issues/7"
        "/notes?per_page=100&sort=asc&order_by=created_at",
    ]


def test_fetch_thread_url_encodes_nested_group_path():
    seen = []

    def capture(url):
        seen.append(url)
        return {**ISSUE, "user_notes_count": 0}

    item = thread_item(source_id="group/subgroup/project#9")
    fetch_item(item, get_json=capture)
    assert seen[0] == (
        "https://gitlab.com/api/v4/projects/group%2Fsubgroup%2Fproject/issues/9"
    )


def test_fetch_thread_degrades_when_notes_fail():
    def get_json(url):
        if "/notes" in url:
            raise OSError("HTTP Error 500")
        return dict(ISSUE)

    fetched = fetch_item(thread_item(), get_json=get_json)
    # the thread survives without its notes, body still extracted
    assert "Rebuilding the index lags BM25 ranking." in fetched.extracted_text
    assert "Comment by" not in (fetched.extracted_text or "")
    assert fetched.provenance["extraction_method"] == "gitlab-api:issue"


def test_fetch_thread_degrades_on_anonymous_notes_gate():
    # gitlab.com serves issue/MR *metadata* keyless but gates the /notes
    # endpoint behind auth — a keyless caller gets 401 on notes (verified live).
    # So the common keyless case is body-only; GITLAB_TOKEN reaches the
    # conversation. The body still extracts and the method records the degrade.
    from urllib.error import HTTPError

    def get_json(url):
        if "/notes" in url:
            raise HTTPError(url, 401, "Unauthorized", {}, None)
        return dict(ISSUE)

    fetched = fetch_item(thread_item(), get_json=get_json)
    assert "Rebuilding the index lags BM25 ranking." in fetched.extracted_text
    assert "Comment by" not in (fetched.extracted_text or "")
    assert fetched.provenance["extraction_method"] == "gitlab-api:issue"
    assert fetched.stage == "fetched"


def test_fetch_thread_with_empty_description_summarizes_engagement():
    thread = {**ISSUE, "description": "", "user_notes_count": 3}
    fetched = fetch_thread(thread=thread)
    assert fetched.summary == "GitLab discussion: 3 comments."


def test_fetch_thread_without_title_degrades_to_the_bare_reference():
    thread = {**ISSUE, "title": ""}
    fetched = fetch_thread(thread=thread)
    assert fetched.title == "gitlab-org/gitlab#7"


def test_fetch_thread_with_label_objects_reads_names():
    # `?with_labels_details=true` returns objects, not bare strings; both read
    thread = {**ISSUE, "labels": [{"name": "bug"}, {"name": "search"}]}
    fetched = fetch_thread(thread=thread)
    assert fetched.concepts == ("bug", "search")


def test_fetch_thread_skips_notes_when_none():
    seen = []

    def capture(url):
        seen.append(url)
        return {**ISSUE, "user_notes_count": 0}

    fetch_item(thread_item(), get_json=capture)
    assert not any("/notes" in url for url in seen)


def test_fetch_thread_requires_a_numeric_iid():
    item = thread_item(source_id="gitlab-org/gitlab#notanumber")
    with pytest.raises(FetchError, match="cannot determine gitlab thread"):
        fetch_item(item, get_json=routed_thread())


def test_fetch_thread_raises_when_not_found():
    def get_json(url):
        return {}  # no iid

    with pytest.raises(FetchError, match="gitlab thread not found"):
        fetch_item(thread_item(), get_json=get_json)
