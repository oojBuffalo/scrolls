"""Tests for the Go modules fetch adapter (IDEAS.md §6, ADR 0042).

Both transports are faked with payloads recorded (and trimmed) from the
live Go module proxy, so the field mapping, the go.mod-as-content choice,
the structurally-empty concepts/tags, the proxy case-encoding, the
Origin-or-path repo link (the package↔repo edge), metadata-only
degradation, and error handling are all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.go import fetch_item


# Recorded from https://proxy.golang.org/github.com/gin-gonic/gin/@latest
GIN_LATEST = {
    "Version": "v1.12.0",
    "Time": "2026-02-28T10:10:09Z",
    "Origin": {
        "VCS": "git",
        "URL": "https://github.com/gin-gonic/gin",
        "Hash": "73726dc606796a025971fe451f0aa6f1b9b847f6",
        "Ref": "refs/tags/v1.12.0",
    },
}

# Trimmed from https://proxy.golang.org/github.com/gin-gonic/gin/@v/v1.12.0.mod
GIN_GOMOD = """module github.com/gin-gonic/gin

go 1.25.0

require (
\tgithub.com/gin-contrib/sse v1.1.0
\tgithub.com/stretchr/testify v1.11.1
\tgolang.org/x/net v0.51.0
)
"""


def make_item(**overrides):
    base = dict(
        id="go:github.com/gin-gonic/gin",
        source="go",
        source_id="github.com/gin-gonic/gin",
        url="https://pkg.go.dev/github.com/gin-gonic/gin",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_get_json(latest=GIN_LATEST):
    def get_json(url):
        return json.loads(json.dumps(latest))  # deep copy

    return get_json


def fake_get_text(go_mod=GIN_GOMOD):
    def get_text(url):
        return go_mod

    return get_text


def fetch(latest=GIN_LATEST, go_mod=GIN_GOMOD, item=None):
    return fetch_item(
        item or make_item(),
        get_json=fake_get_json(latest),
        get_text=fake_get_text(go_mod),
    )


def test_fetch_maps_metadata():
    fetched = fetch()

    # the title is the authoritative module path from the go.mod declaration
    assert fetched.title == "github.com/gin-gonic/gin"
    # Time (RFC 3339, Z suffix) normalizes to UTC ISO 8601
    assert fetched.published_at == "2026-02-28T10:10:09+00:00"
    assert fetched.canonical_url == "https://pkg.go.dev/github.com/gin-gonic/gin"
    assert fetched.provenance["adapter"] == "go"
    assert fetched.provenance["extraction_method"] == "go-proxy:mod"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_go_mod_is_the_extracted_content():
    # the proxy carries no README; the go.mod manifest is the only content,
    # and it is searchable (module path + dependency graph)
    fetched = fetch()
    assert fetched.extracted_text.startswith("module github.com/gin-gonic/gin")
    assert "golang.org/x/net" in fetched.extracted_text


def test_summary_is_honestly_empty():
    # the proxy has no description field — no summary is invented
    assert fetch().summary is None


def test_concepts_and_tags_are_structurally_empty():
    # the proxy carries no keywords, license, or classifier facet at all
    fetched = fetch()
    assert fetched.concepts == ()
    assert fetched.tags == ()


def test_origin_url_becomes_the_repo_link():
    # the package↔repo edge: Origin.URL resolves to the saved github repo
    assert fetch().links == ("https://github.com/gin-gonic/gin",)


def test_origin_git_suffix_is_stripped():
    latest = json.loads(json.dumps(GIN_LATEST))
    latest["Origin"]["URL"] = "https://github.com/gin-gonic/gin.git"
    links = fetch(latest=latest).links
    assert "https://github.com/gin-gonic/gin" in links
    assert not any(link.endswith(".git") for link in links)


def test_repo_falls_back_to_module_path_when_origin_absent():
    # older modules omit Origin; a github module path still yields the repo
    latest = {"Version": "v1.5.4", "Time": "2023-03-17T12:55:57Z"}
    item = make_item(
        id="go:github.com/Masterminds/squirrel",
        source_id="github.com/Masterminds/squirrel",
        url="https://pkg.go.dev/github.com/Masterminds/squirrel",
    )
    assert fetch(latest=latest, item=item).links == (
        "https://github.com/Masterminds/squirrel",
    )


def test_vanity_module_without_origin_has_no_repo_link():
    # rsc.io/quote omits Origin and is not a known VCS host: no link guessed
    latest = {"Version": "v1.5.2", "Time": "2018-02-14T15:44:20Z"}
    item = make_item(
        id="go:rsc.io/quote", source_id="rsc.io/quote",
        url="https://pkg.go.dev/rsc.io/quote",
    )
    assert fetch(latest=latest, item=item).links == ()


def test_vanity_origin_url_is_used_verbatim():
    # golang.org/x/tools' repo is go.googlesource.com — only Origin knows it
    latest = json.loads(json.dumps(GIN_LATEST))
    latest["Origin"]["URL"] = "https://go.googlesource.com/tools"
    item = make_item(source_id="golang.org/x/tools")
    assert fetch(latest=latest, item=item).links == (
        "https://go.googlesource.com/tools",
    )


def test_failed_go_mod_degrades_to_metadata_only():
    def boom(url):
        raise OSError("HTTP Error 410: Gone")

    fetched = fetch_item(make_item(), get_json=fake_get_json(), get_text=boom)
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "go-proxy:latest"
    # the title falls back to the URL-derived module path
    assert fetched.title == "github.com/gin-gonic/gin"
    assert fetched.stage == "fetched"


def test_proxy_request_case_encodes_the_module_path():
    seen = []

    def get_json(url):
        seen.append(url)
        return json.loads(json.dumps(GIN_LATEST))

    item = make_item(
        id="go:github.com/Masterminds/squirrel",
        source_id="github.com/Masterminds/squirrel",
    )
    fetch_item(item, get_json=get_json, get_text=fake_get_text())
    # uppercase letters escape to !lowercase ('Masterminds' -> '!masterminds')
    assert seen == [
        "https://proxy.golang.org/github.com/!masterminds/squirrel/@latest"
    ]


def test_mod_request_uses_the_resolved_version():
    seen = []

    def get_text(url):
        seen.append(url)
        return GIN_GOMOD

    fetch_item(make_item(), get_json=fake_get_json(), get_text=get_text)
    assert seen == [
        "https://proxy.golang.org/github.com/gin-gonic/gin/@v/v1.12.0.mod"
    ]


def test_keeps_the_latest_json_as_raw_record():
    raw = json.loads(fetch().raw_text)
    assert raw["Version"] == "v1.12.0"
    assert raw["Origin"]["URL"] == "https://github.com/gin-gonic/gin"


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://pkg.go.dev/github.com/gin-gonic/gin@v1.12.0")
    fetched = fetch(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id)
    assert fetched.url == item.url  # the saved URL, not the canonical one
    assert fetched.saved_at == item.saved_at


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_a_module_path(source_id):
    item = make_item(id="go:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine module"):
        fetch_item(item, get_json=fake_get_json(), get_text=fake_get_text())


def test_missing_module_is_a_fetch_error():
    # the proxy 404s an unknown module / a sub-package that is not a module
    with pytest.raises(FetchError, match="not found"):
        fetch_item(
            make_item(), get_json=lambda url: {}, get_text=fake_get_text()
        )


def test_wraps_proxy_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom, get_text=fake_get_text())


def test_go_adapter_is_registered():
    assert FETCH_ADAPTERS["go"] is fetch_item
