"""Tests for the NuGet (.NET) fetch adapter (IDEAS.md §6, ADR 0090).

Both requests are faked — the flat-container version index (JSON) and the
`.nuspec` manifest (XML) — with payloads recorded (and trimmed) from the real
`api.nuget.org` service, so the latest-stable version selection, the
namespace-agnostic nuspec parse, the `<tags>` → concepts split, the SPDX
license → tag, the projectUrl/repository → links with their repo→edge
resolution and dedup, and the error handling are all covered offline (ADR 0001).
"""

import xml.etree.ElementTree as ET

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.nuget import fetch_item


# Recorded from https://api.nuget.org/v3-flatcontainer/polly/index.json
# (trimmed): ascending, mixing stable releases with newer pre-releases so the
# latest-stable selection has something to pass over.
VERSIONS = {
    "versions": ["6.0.1", "8.0.0-beta.1", "8.6.4", "8.7.0", "9.0.0-preview.1"]
}

# Recorded verbatim from
# https://api.nuget.org/v3-flatcontainer/polly/8.6.4/polly.nuspec — the
# 2013/05 nuspec namespace, a license *expression* (SPDX), a projectUrl that
# equals the repository url (so they dedupe to one link), and space-separated
# tags (with a repeated "Breaker" token across "Circuit Breaker"/"CircuitBreaker").
NUSPEC = """\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://schemas.microsoft.com/packaging/2013/05/nuspec.xsd">
  <metadata>
    <id>Polly</id>
    <version>8.7.0</version>
    <authors>Michael Wolfenden, App vNext</authors>
    <license type="expression">BSD-3-Clause</license>
    <licenseUrl>https://licenses.nuget.org/BSD-3-Clause</licenseUrl>
    <icon>package-icon.png</icon>
    <readme>package-readme.md</readme>
    <projectUrl>https://github.com/App-vNext/Polly</projectUrl>
    <description>Polly is a .NET resilience and transient-fault-handling library.</description>
    <copyright>Copyright (c) 2015-2025, App vNext</copyright>
    <tags>Polly Exception Handling Resilience Transient Fault Policy Circuit Breaker CircuitBreaker Retry</tags>
    <repository type="git" url="https://github.com/App-vNext/Polly" commit="5f9462dc" />
  </metadata>
</package>
"""


def make_item(**overrides):
    base = dict(
        id="nuget:polly",
        source="nuget",
        source_id="polly",
        url="https://www.nuget.org/packages/Polly",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fakes(versions=VERSIONS, nuspec=NUSPEC):
    """A (get_json, get_text) pair that records the URLs they were asked for."""
    seen = []

    def get_json(url):
        seen.append(url)
        return versions

    def get_text(url):
        seen.append(url)
        if nuspec is None:
            raise OSError("HTTP Error 404: Not Found")
        return nuspec

    return get_json, get_text, seen


def fetch(versions=VERSIONS, nuspec=NUSPEC, item=None):
    get_json, get_text, _ = fakes(versions, nuspec)
    return fetch_item(item or make_item(), get_json=get_json, get_text=get_text)


def nuspec_without(*elements):
    """The NUSPEC with the named metadata elements removed."""
    lines = NUSPEC.splitlines(keepends=True)
    kept = [
        line for line in lines
        if not any(f"<{el}" in line for el in elements)
    ]
    return "".join(kept)


def test_fetch_maps_metadata():
    fetched = fetch()

    assert fetched.title == "Polly"  # no <title>, so the canonical <id>
    assert fetched.author == "Michael Wolfenden, App vNext"
    assert fetched.summary == (
        "Polly is a .NET resilience and transient-fault-handling library."
    )
    # the README lives in the .nupkg, not the nuspec: a NuGet scroll is
    # honestly metadata-only (RubyGems/Hex shape)
    assert fetched.extracted_text is None
    assert fetched.canonical_url == "https://www.nuget.org/packages/Polly"
    assert fetched.provenance["adapter"] == "nuget"
    assert fetched.provenance["extraction_method"] == "nuget-flatcontainer:nuspec"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_tags_become_concepts():
    # <tags> are whitespace-separated keywords → concepts (the github-topics
    # role, like PyPI/pub.dev); duplicate tokens collapse, order preserved
    assert fetch().concepts == (
        "Polly", "Exception", "Handling", "Resilience", "Transient",
        "Fault", "Policy", "Circuit", "Breaker", "CircuitBreaker", "Retry",
    )


def test_comma_or_semicolon_separated_tags_split_too():
    nuspec = NUSPEC.replace(
        "<tags>Polly Exception Handling Resilience Transient Fault Policy "
        "Circuit Breaker CircuitBreaker Retry</tags>",
        "<tags>json, parser; serialization</tags>",
    )
    assert fetch(nuspec=nuspec).concepts == ("json", "parser", "serialization")


def test_no_tags_is_honestly_empty():
    assert fetch(nuspec=nuspec_without("tags")).concepts == ()


def test_spdx_license_expression_becomes_a_tag():
    assert fetch().tags == ("BSD-3-Clause",)


def test_license_file_is_not_a_tag():
    # a <license type="file"> names a file in the package, not an SPDX id
    nuspec = NUSPEC.replace(
        '<license type="expression">BSD-3-Clause</license>',
        '<license type="file">LICENSE.txt</license>',
    )
    assert fetch(nuspec=nuspec).tags == ()


def test_no_license_is_honestly_empty():
    assert fetch(nuspec=nuspec_without("license")).tags == ()


def test_projecturl_and_repository_dedupe_to_one_link():
    # projectUrl == repository url here, so the package↔repo edge is one link
    assert fetch().links == ("https://github.com/App-vNext/Polly",)


def test_distinct_projecturl_and_repository_are_both_links():
    nuspec = NUSPEC.replace(
        "<projectUrl>https://github.com/App-vNext/Polly</projectUrl>",
        "<projectUrl>https://www.thepollyproject.org</projectUrl>",
    )
    assert fetch(nuspec=nuspec).links == (
        "https://www.thepollyproject.org",
        "https://github.com/App-vNext/Polly",
    )


def test_repository_dotgit_suffix_is_stripped():
    nuspec = NUSPEC.replace(
        'url="https://github.com/App-vNext/Polly"',
        'url="https://github.com/App-vNext/Polly.git"',
    ).replace(
        "<projectUrl>https://github.com/App-vNext/Polly</projectUrl>", ""
    )
    links = fetch(nuspec=nuspec).links
    assert "https://github.com/App-vNext/Polly" in links
    assert not any(link.endswith(".git") for link in links)


def test_no_links_is_honestly_empty():
    assert fetch(nuspec=nuspec_without("projectUrl", "repository")).links == ()


def test_title_element_wins_over_id():
    nuspec = NUSPEC.replace(
        "<id>Polly</id>", "<id>Polly</id>\n    <title>Polly Resilience</title>"
    )
    assert fetch(nuspec=nuspec).title == "Polly Resilience"


def test_canonical_url_uses_the_nuspec_id_casing():
    # the URL was lowercased for the API; the display case comes from <id>
    item = make_item(source_id="newtonsoft.json", id="nuget:newtonsoft.json")
    nuspec = NUSPEC.replace("<id>Polly</id>", "<id>Newtonsoft.Json</id>")
    fetched = fetch(nuspec=nuspec, item=item)
    assert fetched.canonical_url == "https://www.nuget.org/packages/Newtonsoft.Json"


def test_summary_falls_back_to_summary_element():
    nuspec = NUSPEC.replace(
        "<description>Polly is a .NET resilience and "
        "transient-fault-handling library.</description>",
        "<summary>A short tagline.</summary>",
    )
    assert fetch(nuspec=nuspec).summary == "A short tagline."


def test_requests_the_flatcontainer_index_then_the_chosen_nuspec():
    get_json, get_text, seen = fakes()
    fetch_item(make_item(), get_json=get_json, get_text=get_text)
    assert seen == [
        "https://api.nuget.org/v3-flatcontainer/polly/index.json",
        # the latest *stable* (8.7.0), not the 9.0.0-preview that tops the list
        "https://api.nuget.org/v3-flatcontainer/polly/8.7.0/polly.nuspec",
    ]


def test_picks_the_highest_prerelease_when_no_stable_release_exists():
    get_json, get_text, seen = fakes(
        versions={"versions": ["1.0.0-alpha.1", "1.0.0-alpha.2", "0.9.0-rc.1"]}
    )
    fetch_item(make_item(), get_json=get_json, get_text=get_text)
    assert seen[-1].endswith("/1.0.0-alpha.2/polly.nuspec")


def test_published_at_is_left_as_the_seed():
    # the nuspec carries no publish date; the adapter never invents one
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_raw_text_keeps_the_nuspec_manifest():
    assert "<id>Polly</id>" in fetch().raw_text


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://www.nuget.org/packages/Polly/8.6.4")
    fetched = fetch(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id)
    assert fetched.url == item.url  # the saved URL, not the canonical one
    assert fetched.saved_at == item.saved_at


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_a_package_name(source_id):
    item = make_item(id="nuget:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine package"):
        fetch_item(item, get_json=lambda url: VERSIONS, get_text=lambda url: NUSPEC)


def test_missing_package_is_a_fetch_error():
    # the flat-container 404s a nonexistent package → empty/absent versions
    with pytest.raises(FetchError, match="not found"):
        fetch_item(
            make_item(),
            get_json=lambda url: {"versions": []},
            get_text=lambda url: NUSPEC,
        )


def test_wraps_index_request_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom, get_text=lambda url: NUSPEC)


def test_nuspec_failure_is_a_fetch_error_not_a_metadata_only_scroll():
    # the nuspec *is* the metadata, so unlike Go's optional go.mod its failure
    # cannot degrade to a metadata-only scroll — there would be no metadata
    with pytest.raises(FetchError, match="nuspec"):
        fetch(nuspec=None)


def test_malformed_nuspec_is_a_fetch_error():
    with pytest.raises(FetchError, match="XML"):
        fetch(nuspec="<package><metadata><id>broken")


def test_nuget_adapter_is_registered():
    assert FETCH_ADAPTERS["nuget"] is fetch_item


def test_nuspec_namespace_is_irrelevant():
    # an older nuspec schema namespace must parse identically (local-name match)
    nuspec = NUSPEC.replace("/2013/05/", "/2011/08/")
    assert fetch(nuspec=nuspec).title == "Polly"
    assert ET.fromstring(nuspec) is not None  # sanity: still well-formed
