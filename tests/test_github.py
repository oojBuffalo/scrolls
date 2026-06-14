"""Tests for the GitHub fetch adapter (IDEAS.md §6, ADR 0007).

The JSON transport is faked; tests cover the README-optional fetch
semantics and the topics → concepts mapping offline.
"""

import base64
import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.github import _api_headers, fetch_item

REPO = {
    "name": "scrolls",
    "full_name": "oojBuffalo/scrolls",
    "html_url": "https://github.com/oojBuffalo/scrolls",
    "description": "Turn saved internet artifacts into agent-readable knowledge.",
    "owner": {"login": "oojBuffalo"},
    "created_at": "2026-05-01T12:00:00Z",
    "topics": ["knowledge-base", "sqlite", "agents"],
    "language": "Python",
}

README_TEXT = "# Scrolls\n\nA local-first CLI for agent-readable knowledge.\n"


def readme_payload(text=README_TEXT):
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    # GitHub chunks base64 content with embedded newlines
    chunked = "\n".join(encoded[i : i + 20] for i in range(0, len(encoded), 20)) + "\n"
    return {"content": chunked, "encoding": "base64"}


def make_item(**overrides):
    base = dict(
        id="github:oojBuffalo/scrolls",
        source="github",
        source_id="oojBuffalo/scrolls",
        url="https://github.com/oojBuffalo/scrolls",
        saved_at="2026-06-12T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def routed_get_json(repo=REPO, readme=None):
    readme = readme if readme is not None else readme_payload()

    def get_json(url):
        if url.endswith("/readme"):
            return dict(readme)
        return dict(repo)

    return get_json


def fetch(item=None, **kwargs):
    return fetch_item(item or make_item(), get_json=routed_get_json(**kwargs))


def test_fetch_item_with_readme():
    fetched = fetch()

    assert fetched.title == "oojBuffalo/scrolls"
    assert fetched.author == "oojBuffalo"
    assert fetched.published_at == "2026-05-01T12:00:00+00:00"  # REST Z-date, normalized
    assert fetched.canonical_url == "https://github.com/oojBuffalo/scrolls"
    assert fetched.summary == REPO["description"]
    assert fetched.extracted_text == README_TEXT
    assert fetched.concepts == ("knowledge-base", "sqlite", "agents")
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.provenance["adapter"] == "github"
    assert fetched.provenance["extraction_method"] == "github-api:repo+readme"
    assert fetched.stage == "fetched"


def test_fetch_item_keeps_raw_records_for_rebuilds():
    fetched = fetch()
    raw = json.loads(fetched.raw_text)
    assert raw["repo"]["full_name"] == "oojBuffalo/scrolls"
    assert raw["readme"] == README_TEXT


def test_fetch_item_preserves_identity_fields():
    item = make_item(url="https://github.com/oojBuffalo/scrolls/blob/main/README.md")
    fetched = fetch(item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url  # the URL the user saved, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_fetch_item_keeps_seeded_published_at_when_repo_has_no_created_at():
    # a feed-seeded date (ADR 0021) survives a fetch that finds no date
    repo = {key: value for key, value in REPO.items() if key != "created_at"}
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    fetched = fetch_item(item, get_json=routed_get_json(repo=repo))
    assert fetched.published_at == "2026-06-01T00:00:00+00:00"


def test_fetch_item_requests_the_expected_api_urls():
    seen = []
    routed = routed_get_json()

    def capture(url):
        seen.append(url)
        return routed(url)

    fetch_item(make_item(), get_json=capture)
    assert seen == [
        "https://api.github.com/repos/oojBuffalo/scrolls",
        "https://api.github.com/repos/oojBuffalo/scrolls/readme",
    ]


def test_fetch_item_without_readme_degrades_to_metadata_only():
    def get_json(url):
        if url.endswith("/readme"):
            raise OSError("HTTP Error 404: Not Found")
        return dict(REPO)

    fetched = fetch_item(make_item(), get_json=get_json)
    assert fetched.title == "oojBuffalo/scrolls"
    assert fetched.extracted_text is None
    assert fetched.content_hash.startswith("sha256:")
    assert json.loads(fetched.raw_text)["readme"] is None
    assert fetched.provenance["extraction_method"] == "github-api:repo"
    assert fetched.stage == "fetched"


def test_fetch_item_treats_blank_readme_as_metadata_only():
    fetched = fetch(readme=readme_payload("  \n\n"))
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "github-api:repo"


def test_fetch_item_ignores_unexpected_readme_encoding():
    fetched = fetch(readme={"content": "plain text", "encoding": "utf-8"})
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "github-api:repo"


def test_fetch_item_without_topics_has_no_concepts():
    repo = {key: value for key, value in REPO.items() if key != "topics"}
    fetched = fetch(repo=repo)
    assert fetched.concepts == ()


def test_fetch_item_without_description_has_no_summary():
    fetched = fetch(repo={**REPO, "description": None})
    assert fetched.summary is None


def test_fetch_item_requires_a_repo_id():
    item = make_item(id="github:abc123def456", source_id=None,
                     url="https://github.com/explore")
    with pytest.raises(FetchError, match="cannot determine github repository"):
        fetch_item(item, get_json=routed_get_json())


def test_fetch_item_wraps_repo_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom)


def test_api_headers_are_keyless_by_default(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    headers = _api_headers()
    assert headers["Accept"] == "application/vnd.github+json"
    assert "Authorization" not in headers


def test_api_headers_use_github_token_when_set(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_example")
    assert _api_headers()["Authorization"] == "Bearer ghp_example"


def test_api_headers_fall_back_to_gh_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "gho_example")
    assert _api_headers()["Authorization"] == "Bearer gho_example"


def test_github_adapter_is_registered():
    assert FETCH_ADAPTERS["github"] is fetch_item


# --- issues and pull requests (ADR 0084) ----------------------------------
#
# A `/issues/<n>` or `/pull/<n>` URL detects as `owner/repo#<n>`, a discussion
# thread distinct from the repo. The same `github` source/adapter serves it,
# dispatched on the `#` in the source id (the huggingface one-source-many-kinds
# shape) — keeping the repo path byte-unchanged.

ISSUE = {
    "number": 7,
    "title": "FTS5 ranking returns stale results",
    "body": "Rebuilding the index lags BM25 ranking.\n\nSee https://example.com/bug.",
    "html_url": "https://github.com/oojBuffalo/scrolls/issues/7",
    "user": {"login": "alice"},
    "state": "open",
    "created_at": "2026-05-10T09:00:00Z",
    "comments": 2,
    "labels": [{"name": "bug"}, {"name": "search"}],
}

PR = {
    "number": 12,
    "title": "Add faceted search",
    "body": "Implements `--source`/`--category` filters.",
    "html_url": "https://github.com/oojBuffalo/scrolls/pull/12",
    "user": {"login": "bob"},
    "state": "closed",
    "created_at": "2026-05-12T10:00:00Z",
    "comments": 0,
    "labels": [{"name": "enhancement"}],
    "pull_request": {"merged_at": "2026-05-13T11:00:00Z"},
}

COMMENTS = [
    {"user": {"login": "carol"}, "body": "I can repro this on main."},
    {"user": {"login": "alice"}, "body": "Fixed by the rebuild trigger."},
]


def issue_item(source_id="oojBuffalo/scrolls#7", **overrides):
    base = dict(
        id=f"github:{source_id}",
        source="github",
        source_id=source_id,
        url=f"https://github.com/{source_id.replace('#', '/issues/')}",
        saved_at="2026-06-12T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def routed_issue(issue=ISSUE, comments=COMMENTS):
    def get_json(url):
        if "/comments" in url:
            return [dict(c) for c in comments]
        return dict(issue)

    return get_json


def test_fetch_issue_maps_thread_fields():
    fetched = fetch_item(issue_item(), get_json=routed_issue())

    assert fetched.title == "oojBuffalo/scrolls#7: FTS5 ranking returns stale results"
    assert fetched.author == "alice"
    assert fetched.published_at == "2026-05-10T09:00:00+00:00"
    assert fetched.canonical_url == "https://github.com/oojBuffalo/scrolls/issues/7"
    # labels are the curated topical facet → concepts (the github-topics rule)
    assert fetched.concepts == ("bug", "search")
    # kind + state are the facet slot → tags
    assert fetched.tags == ("issue", "open")
    assert fetched.summary == "Rebuilding the index lags BM25 ranking."
    assert fetched.provenance["adapter"] == "github"
    assert fetched.provenance["extraction_method"] == "github-api:issue+comments"
    assert fetched.stage == "fetched"


def test_fetch_issue_body_and_comments_become_extracted_text():
    fetched = fetch_item(issue_item(), get_json=routed_issue())
    assert "Rebuilding the index lags BM25 ranking." in fetched.extracted_text
    assert "Comment by carol" in fetched.extracted_text
    assert "I can repro this on main." in fetched.extracted_text
    assert "Comment by alice" in fetched.extracted_text


def test_fetch_issue_links_carry_the_repo_edge_and_body_urls():
    fetched = fetch_item(issue_item(), get_json=routed_issue())
    # the issue belongs to its repo (issue↔repo edge, resolves to github:owner/repo)
    assert "https://github.com/oojBuffalo/scrolls" in fetched.links
    # a URL referenced in the body becomes an outbound edge
    assert "https://example.com/bug" in fetched.links
    # the thread's own URL is never a self-link
    assert fetched.canonical_url not in fetched.links


def test_fetch_issue_keeps_raw_records_for_rebuilds():
    fetched = fetch_item(issue_item(), get_json=routed_issue())
    raw = json.loads(fetched.raw_text)
    assert raw["issue"]["number"] == 7
    assert len(raw["comments"]) == 2


def test_fetch_pull_request_is_tagged_and_merge_aware():
    fetched = fetch_item(
        issue_item(source_id="oojBuffalo/scrolls#12"), get_json=routed_issue(issue=PR)
    )
    assert fetched.title == "oojBuffalo/scrolls#12: Add faceted search"
    # a merged PR is distinguishable from a closed-unmerged one (merged_at)
    assert fetched.tags == ("pull request", "merged")
    assert fetched.concepts == ("enhancement",)


def test_fetch_issue_skips_comment_request_when_there_are_none():
    seen = []

    def capture(url):
        seen.append(url)
        return dict(PR)

    fetch_item(issue_item(source_id="oojBuffalo/scrolls#12"), get_json=capture)
    assert seen == ["https://api.github.com/repos/oojBuffalo/scrolls/issues/12"]
    assert not any(url.endswith("/comments") for url in seen[1:])


def test_fetch_issue_requests_the_expected_api_urls():
    seen = []
    routed = routed_issue()

    def capture(url):
        seen.append(url)
        return routed(url)

    fetch_item(issue_item(), get_json=capture)
    assert seen == [
        "https://api.github.com/repos/oojBuffalo/scrolls/issues/7",
        "https://api.github.com/repos/oojBuffalo/scrolls/issues/7/comments?per_page=100",
    ]


def test_fetch_issue_degrades_when_comments_fail():
    def get_json(url):
        if "/comments" in url:
            raise OSError("HTTP Error 500: Server Error")
        return dict(ISSUE)

    fetched = fetch_item(issue_item(), get_json=get_json)
    # the thread survives without its comments, body still extracted
    assert "Rebuilding the index lags BM25 ranking." in fetched.extracted_text
    assert "Comment by" not in (fetched.extracted_text or "")
    assert fetched.provenance["extraction_method"] == "github-api:issue"
    assert fetched.stage == "fetched"


def test_fetch_issue_with_empty_body_summarizes_engagement():
    issue = {**ISSUE, "body": "", "comments": 3}
    fetched = fetch_item(issue_item(), get_json=routed_issue(issue=issue))
    assert fetched.summary == "GitHub discussion: 3 comments."
    # an empty body leaves only the comment thread as content
    assert fetched.extracted_text.startswith("### Comments")


def test_fetch_issue_wraps_request_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(issue_item(), get_json=boom)


def test_fetch_issue_rejects_a_malformed_thread_id():
    item = issue_item(source_id="oojBuffalo#7", id="github:oojBuffalo#7")
    with pytest.raises(FetchError, match="cannot determine github"):
        fetch_item(item, get_json=routed_issue())
