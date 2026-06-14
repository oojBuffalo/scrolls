"""Tests for the Gitea/Forgejo fetch adapter (IDEAS.md §6, ADR 0056).

The JSON and text transports are faked; tests cover the README-optional
fetch semantics (README.md-first via the keyless API raw route, a root-listing
fallback for a differently-named README), the inline `topics` → `concepts`
mapping, the per-instance API root derived from the host in the id, and the
keyless/token headers — all offline.
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.gitea import _api_headers, fetch_item

REPO = {
    "name": "forgejo",
    "full_name": "forgejo/forgejo",
    "description": "Beyond coding. We forge.",
    "html_url": "https://codeberg.org/forgejo/forgejo",
    "website": "https://forgejo.org",
    "default_branch": "forgejo",
    "created_at": "2022-11-06T07:24:57+01:00",
    "owner": {"login": "forgejo", "username": "forgejo"},
    "language": "Go",
    "topics": ["forge", "forgejo", "git", "self-hosted"],
}

README_TEXT = "# Forgejo\n\nBeyond coding. We forge.\n"
REPO_API = "https://codeberg.org/api/v1/repos/forgejo/forgejo"
README_RAW_URL = f"{REPO_API}/raw/README.md"

# A root listing with a non-.md README (the only time the listing is consulted):
# README.md-first misses, so the adapter lists to find README.rst.
RST_CONTENTS = [
    {"name": "LICENSE", "type": "file", "download_url": "https://x/LICENSE"},
    {"name": "src", "type": "dir"},
    {"name": "README.rst", "path": "README.rst", "type": "file",
     "download_url": "https://codeberg.org/forgejo/forgejo/raw/branch/forgejo/README.rst"},
]


def make_item(**overrides):
    base = dict(
        id="gitea:codeberg.org/forgejo/forgejo",
        source="gitea",
        source_id="codeberg.org/forgejo/forgejo",
        url="https://codeberg.org/forgejo/forgejo",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def routed(repo=REPO, contents=None, files=None):
    """A (get_json, get_text) pair dispatching on the URL shape.

    `files` maps a raw filepath to its body (default `{"README.md": README_TEXT}`);
    an absent path 404s. `contents` is the root listing the fallback lists
    (`None` makes the listing fail — the slow/failed-listing degrade).
    """
    if files is None:
        files = {"README.md": README_TEXT}

    def get_json(url):
        if url.endswith("/contents"):
            if contents is None:
                raise OSError("HTTP Error 404: Not Found")
            return list(contents)
        return dict(repo)

    def get_text(url):
        path = url.split("/raw/", 1)[1]
        if path not in files:
            raise OSError("HTTP Error 404: Not Found")
        return files[path]

    return get_json, get_text


def fetch(item=None, **kwargs):
    get_json, get_text = routed(**kwargs)
    return fetch_item(item or make_item(), get_json=get_json, get_text=get_text)


def test_fetch_item_with_readme():
    fetched = fetch()

    assert fetched.title == "forgejo/forgejo"
    assert fetched.author == "forgejo"
    assert fetched.published_at == "2022-11-06T06:24:57+00:00"  # +01:00 normalized to UTC
    assert fetched.canonical_url == "https://codeberg.org/forgejo/forgejo"
    assert fetched.summary == REPO["description"]
    assert fetched.extracted_text == README_TEXT
    assert fetched.concepts == ("forge", "forgejo", "git", "self-hosted")
    assert fetched.tags == ()  # Gitea repo metadata carries no inline license (github-parallel)
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.provenance["adapter"] == "gitea"
    assert fetched.provenance["extraction_method"] == "gitea-api:repo+readme"
    assert fetched.stage == "fetched"


def test_fetch_item_keeps_raw_records_for_rebuilds():
    fetched = fetch()
    raw = json.loads(fetched.raw_text)
    assert raw["repo"]["full_name"] == "forgejo/forgejo"
    assert raw["readme"] == README_TEXT


def test_fetch_item_preserves_identity_fields():
    item = make_item(url="https://codeberg.org/forgejo/forgejo/issues/7")
    fetched = fetch(item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url  # the URL the user saved, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_readme_md_first_is_one_fast_call_no_listing():
    # The dominant case (a root README.md) is a single keyless raw GET; the
    # repo-root listing is never touched — the fix for the forgejo/forgejo
    # listing timeout discovered in live verification.
    seen = []

    def get_json(url):
        seen.append(url)
        return dict(REPO)

    def get_text(url):
        seen.append(url)
        return README_TEXT

    fetch_item(make_item(), get_json=get_json, get_text=get_text)
    assert seen == [REPO_API, README_RAW_URL]
    assert all(not u.endswith("/contents") for u in seen)


def test_api_root_derived_from_the_host_in_the_source_id():
    # The host rides in the id because the Gitea API lives on each instance's
    # own host — the key difference from github/gitlab's single API host.
    seen = []

    def get_json(url):
        seen.append(url)
        return dict(REPO)

    def get_text(url):
        seen.append(url)
        return README_TEXT

    fetch_item(make_item(), get_json=get_json, get_text=get_text)
    assert seen[0] == REPO_API
    assert README_RAW_URL in seen


def test_api_root_varies_by_instance_host():
    # A gitea.com repo hits gitea.com's API, not codeberg's — the host is data.
    seen = []

    def get_json(url):
        seen.append(url)
        return {"full_name": "gitea/tea"}

    def get_text(url):
        seen.append(url)
        return "# tea"

    item = make_item(
        id="gitea:gitea.com/gitea/tea",
        source_id="gitea.com/gitea/tea",
        url="https://gitea.com/gitea/tea",
    )
    fetch_item(item, get_json=get_json, get_text=get_text)
    assert seen[0] == "https://gitea.com/api/v1/repos/gitea/tea"
    assert "https://gitea.com/api/v1/repos/gitea/tea/raw/README.md" in seen


def test_readme_uses_api_raw_route_not_the_web_download_url():
    # Regression: the listing's download_url is the *web* raw route, which
    # gitea.com 303-redirects anonymous clients to a login page (urllib would
    # follow it and capture HTML). The adapter fetches the keyless API raw
    # route built from the file path, never the download_url.
    seen = []

    def get_json(url):
        return list(RST_CONTENTS) if url.endswith("/contents") else dict(REPO)

    def get_text(url):
        seen.append(url)
        path = url.split("/raw/", 1)[1]
        if path == "README.md":
            raise OSError("HTTP Error 404: Not Found")  # no README.md → list
        return "RST body"

    fetch_item(make_item(), get_json=get_json, get_text=get_text)
    rst_raw = f"{REPO_API}/raw/README.rst"
    assert rst_raw in seen
    assert all("/raw/branch/" not in u for u in seen)  # never the web download_url


def test_readme_falls_back_to_listing_for_non_markdown_readme():
    # No README.md, so the adapter lists the root and finds README.rst.
    fetched = fetch(contents=RST_CONTENTS, files={"README.rst": "RST body"})
    assert fetched.extracted_text == "RST body"
    assert fetched.provenance["extraction_method"] == "gitea-api:repo+readme"


def test_readme_listing_prefers_markdown_over_other_formats():
    # If README.md is absent from the raw route but a listing has both a .md
    # and a .rst, the .md still wins (the listing path's tiebreak).
    contents = [
        {"name": "README.rst", "path": "README.rst", "type": "file"},
        {"name": "README.markdown", "path": "README.markdown", "type": "file"},
    ]
    seen = []

    def get_json(url):
        return list(contents) if url.endswith("/contents") else dict(REPO)

    def get_text(url):
        seen.append(url)
        path = url.split("/raw/", 1)[1]
        if path == "README.md":
            raise OSError("404")
        return "MD body"

    fetched = fetch_item(make_item(), get_json=get_json, get_text=get_text)
    assert fetched.extracted_text == "MD body"
    assert seen[-1] == f"{REPO_API}/raw/README.markdown"  # .markdown beat .rst


def test_fetch_item_without_any_readme_degrades_to_metadata_only():
    contents = [{"name": "main.go", "type": "file"}]
    fetched = fetch(contents=contents, files={})  # no README.md, none in listing
    assert fetched.extracted_text is None
    assert json.loads(fetched.raw_text)["readme"] is None
    assert fetched.provenance["extraction_method"] == "gitea-api:repo"
    assert fetched.stage == "fetched"


def test_fetch_item_with_failing_contents_listing_degrades_to_metadata_only():
    fetched = fetch(contents=None, files={})  # README.md 404s, then listing 404s
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "gitea-api:repo"


def test_fetch_item_treats_blank_readme_as_metadata_only():
    # A present-but-blank README.md is honestly metadata-only; the listing
    # fallback skips README.md so it isn't re-fetched.
    fetched = fetch(contents=[{"name": "README.md", "path": "README.md", "type": "file"}],
                    files={"README.md": "   \n\n"})
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "gitea-api:repo"


def test_fetch_item_without_topics_has_no_concepts():
    repo = {key: value for key, value in REPO.items() if key != "topics"}
    fetched = fetch(repo=repo)
    assert fetched.concepts == ()


def test_fetch_item_without_description_has_no_summary():
    fetched = fetch(repo={**REPO, "description": None})
    assert fetched.summary is None


def test_fetch_item_keeps_seeded_published_at_when_repo_has_no_created_at():
    repo = {key: value for key, value in REPO.items() if key != "created_at"}
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    get_json, get_text = routed(repo=repo)
    fetched = fetch_item(item, get_json=get_json, get_text=get_text)
    assert fetched.published_at == "2026-06-01T00:00:00+00:00"


def test_fetch_item_requires_a_repo_id():
    # a host-only id (no owner/repo) is a profile/site route, not fetchable
    item = make_item(
        id="gitea:codeberg.org", source_id="codeberg.org",
        url="https://codeberg.org/explore",
    )
    with pytest.raises(FetchError, match="cannot determine gitea repository"):
        fetch_item(item)


def test_fetch_item_requires_a_source_id():
    item = make_item(source_id=None, url="https://codeberg.org/")
    with pytest.raises(FetchError, match="cannot determine gitea repository"):
        fetch_item(item)


def test_fetch_item_wraps_repo_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom, get_text=lambda url: README_TEXT)


def test_api_headers_are_keyless_by_default(monkeypatch):
    monkeypatch.delenv("GITEA_TOKEN", raising=False)
    monkeypatch.delenv("FORGEJO_TOKEN", raising=False)
    assert _api_headers() == {}


def test_api_headers_use_gitea_token_when_set(monkeypatch):
    monkeypatch.delenv("FORGEJO_TOKEN", raising=False)
    monkeypatch.setenv("GITEA_TOKEN", "gitea-example")
    assert _api_headers() == {"Authorization": "token gitea-example"}


def test_api_headers_accept_forgejo_token_alias(monkeypatch):
    monkeypatch.delenv("GITEA_TOKEN", raising=False)
    monkeypatch.setenv("FORGEJO_TOKEN", "forgejo-example")
    assert _api_headers() == {"Authorization": "token forgejo-example"}


def test_gitea_adapter_is_registered():
    assert FETCH_ADAPTERS["gitea"] is fetch_item


# --- issues and pull requests (ADR 0086) ----------------------------------
#
# A `/issues/<n>` or `/pulls/<n>` URL detects as `<host>/<owner>/<repo>#<n>`, a
# discussion thread distinct from the repo. The same `gitea` source/adapter
# serves it, dispatched on the `#` in the source id (the github one-source-many-
# kinds shape, ADR 0084) — keeping the repo path byte-unchanged. Gitea/Forgejo
# unify issue and PR numbering like github (one `/issues/<index>` endpoint
# serves both, a PR carrying a `pull_request` object), so one `#` marker
# suffices — unlike gitlab's two (ADR 0085).

ISSUE = {
    "number": 7,
    "title": "FTS5 ranking returns stale results",
    "body": "Rebuilding the index lags BM25 ranking.\n\nSee https://example.com/bug.",
    "html_url": "https://codeberg.org/forgejo/forgejo/issues/7",
    "user": {"login": "alice", "username": "alice"},
    "state": "open",
    "created_at": "2026-05-10T09:00:00+02:00",
    "comments": 2,
    "labels": [{"name": "bug"}, {"name": "search"}],
}

PR = {
    "number": 12,
    "title": "Add faceted search",
    "body": "Implements `--source`/`--category` filters.",
    "html_url": "https://codeberg.org/forgejo/forgejo/pulls/12",
    "user": {"login": "bob", "username": "bob"},
    "state": "closed",
    "created_at": "2026-05-12T10:00:00+02:00",
    "comments": 0,
    "labels": [{"name": "enhancement"}],
    "pull_request": {"merged": True, "merged_at": "2026-05-13T11:00:00+02:00"},
}

ISSUE_COMMENTS = [
    {"user": {"login": "carol", "username": "carol"}, "body": "I can repro this on main."},
    {"user": {"login": "alice", "username": "alice"}, "body": "Fixed by the rebuild trigger."},
]


def thread_item(source_id="codeberg.org/forgejo/forgejo#7", **overrides):
    base = dict(
        id=f"gitea:{source_id}",
        source="gitea",
        source_id=source_id,
        url="https://codeberg.org/forgejo/forgejo/issues/7",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def routed_thread(issue=ISSUE, comments=ISSUE_COMMENTS):
    def get_json(url):
        if "/comments" in url:
            return [dict(c) for c in comments]
        return dict(issue)

    return get_json


def test_fetch_thread_maps_fields():
    fetched = fetch_item(thread_item(), get_json=routed_thread())

    # the title leads with the host-free cross-reference, like the repo title
    assert fetched.title == "forgejo/forgejo#7: FTS5 ranking returns stale results"
    assert fetched.author == "alice"
    assert fetched.published_at == "2026-05-10T07:00:00+00:00"  # +02:00 normalized
    assert fetched.canonical_url == "https://codeberg.org/forgejo/forgejo/issues/7"
    # labels are the curated topical facet → concepts (the github-topics rule)
    assert fetched.concepts == ("bug", "search")
    # kind + state are the facet slot → tags
    assert fetched.tags == ("issue", "open")
    assert fetched.summary == "Rebuilding the index lags BM25 ranking."
    assert fetched.provenance["adapter"] == "gitea"
    assert fetched.provenance["extraction_method"] == "gitea-api:issue+comments"
    assert fetched.stage == "fetched"


def test_fetch_thread_body_and_comments_become_extracted_text():
    fetched = fetch_item(thread_item(), get_json=routed_thread())
    assert "Rebuilding the index lags BM25 ranking." in fetched.extracted_text
    assert "Comment by carol" in fetched.extracted_text
    assert "I can repro this on main." in fetched.extracted_text
    assert "Comment by alice" in fetched.extracted_text


def test_fetch_thread_links_carry_the_repo_edge_and_body_urls():
    fetched = fetch_item(thread_item(), get_json=routed_thread())
    # the thread belongs to its repo (thread↔repo edge, resolves to the repo item)
    assert "https://codeberg.org/forgejo/forgejo" in fetched.links
    # a URL referenced in the body becomes an outbound edge
    assert "https://example.com/bug" in fetched.links
    # the thread's own URL is never a self-link
    assert fetched.canonical_url not in fetched.links


def test_fetch_thread_keeps_raw_records_for_rebuilds():
    fetched = fetch_item(thread_item(), get_json=routed_thread())
    raw = json.loads(fetched.raw_text)
    assert raw["issue"]["number"] == 7
    assert len(raw["comments"]) == 2


def test_fetch_pull_request_is_tagged_and_merge_aware():
    fetched = fetch_item(
        thread_item(source_id="codeberg.org/forgejo/forgejo#12"),
        get_json=routed_thread(issue=PR),
    )
    assert fetched.title == "forgejo/forgejo#12: Add faceted search"
    # a merged PR is distinguishable from a closed-unmerged one (pull_request.merged_at)
    assert fetched.tags == ("pull request", "merged")
    assert fetched.concepts == ("enhancement",)


def test_fetch_thread_skips_comment_request_when_there_are_none():
    seen = []

    def capture(url):
        seen.append(url)
        return dict(PR)

    fetch_item(thread_item(source_id="codeberg.org/forgejo/forgejo#12"), get_json=capture)
    assert seen == ["https://codeberg.org/api/v1/repos/forgejo/forgejo/issues/12"]
    assert not any(url.endswith("/comments") for url in seen[1:])


def test_fetch_thread_requests_the_expected_api_urls():
    seen = []
    routed = routed_thread()

    def capture(url):
        seen.append(url)
        return routed(url)

    fetch_item(thread_item(), get_json=capture)
    assert seen == [
        "https://codeberg.org/api/v1/repos/forgejo/forgejo/issues/7",
        "https://codeberg.org/api/v1/repos/forgejo/forgejo/issues/7/comments?per_page=100",
    ]


def test_fetch_thread_api_root_varies_by_instance_host():
    # The host rides in the id (gitea's per-instance API), so a gitea.com thread
    # hits gitea.com's API, not codeberg's — the host is data.
    seen = []

    def capture(url):
        seen.append(url)
        return {"number": 5, "title": "t", "state": "open"}

    fetch_item(
        thread_item(
            source_id="gitea.com/gitea/tea#5",
            id="gitea:gitea.com/gitea/tea#5",
        ),
        get_json=capture,
    )
    assert seen[0] == "https://gitea.com/api/v1/repos/gitea/tea/issues/5"


def test_fetch_thread_degrades_when_comments_fail():
    def get_json(url):
        if "/comments" in url:
            raise OSError("HTTP Error 500: Server Error")
        return dict(ISSUE)

    fetched = fetch_item(thread_item(), get_json=get_json)
    # the thread survives without its comments, body still extracted
    assert "Rebuilding the index lags BM25 ranking." in fetched.extracted_text
    assert "Comment by" not in (fetched.extracted_text or "")
    assert fetched.provenance["extraction_method"] == "gitea-api:issue"
    assert fetched.stage == "fetched"


def test_fetch_thread_with_empty_body_summarizes_engagement():
    issue = {**ISSUE, "body": "", "comments": 3}
    fetched = fetch_item(thread_item(), get_json=routed_thread(issue=issue))
    assert fetched.summary == "Gitea discussion: 3 comments."
    # an empty body leaves only the comment thread as content
    assert fetched.extracted_text.startswith("### Comments")


def test_fetch_thread_wraps_request_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(thread_item(), get_json=boom)


def test_fetch_thread_rejects_a_malformed_thread_id():
    # a host/owner id with no repo segment before the marker is not a thread
    item = thread_item(source_id="codeberg.org/forgejo#7", id="gitea:codeberg.org/forgejo#7")
    with pytest.raises(FetchError, match="cannot determine gitea thread"):
        fetch_item(item, get_json=routed_thread())


def test_fetch_thread_not_found_when_payload_lacks_a_number():
    def get_json(url):
        return {"message": "Not found."}

    with pytest.raises(FetchError, match="gitea thread not found"):
        fetch_item(thread_item(), get_json=get_json)
