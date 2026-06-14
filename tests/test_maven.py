"""Tests for the Maven Central (JVM) fetch adapter (IDEAS.md §6, ADR 0092).

Both requests are faked — the maven-metadata.xml version index and the POM
manifest, both XML — with payloads trimmed from the real
`repo1.maven.org/maven2` flat repository, so the `<release>`-preferred version
selection, the group-path encoding of the request, the namespace-agnostic POM
parse, the concepts-empty-by-design posture, the license-name → tag mapping, the
url/scm → links with their repo→edge dedup and connection normalization, the
lastUpdated → published_at, and the error handling are all covered offline
(ADR 0001).
"""

import re
import xml.etree.ElementTree as ET

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.maven import fetch_item


# Trimmed from
# https://repo1.maven.org/maven2/com/google/guava/guava/maven-metadata.xml:
# a <release> pointer plus a <versions> list mixing the -jre/-android stable
# build classifiers (which a hyphen heuristic would wrongly treat as
# pre-releases) so the <release>-preferred selection has something to prove.
METADATA = """\
<?xml version="1.0" encoding="UTF-8"?>
<metadata>
  <groupId>com.google.guava</groupId>
  <artifactId>guava</artifactId>
  <versioning>
    <latest>33.4.0-jre</latest>
    <release>33.4.0-jre</release>
    <versions>
      <version>33.3.1-jre</version>
      <version>33.4.0-android</version>
      <version>33.4.0-jre</version>
    </versions>
    <lastUpdated>20241220153000</lastUpdated>
  </versioning>
</metadata>
"""

# Trimmed from
# https://repo1.maven.org/maven2/com/google/guava/guava/33.4.0-jre/guava-33.4.0-jre.pom:
# a <name>, a freeform license name, an organization byline, and an <scm> whose
# <url> equals the project <url> (so they dedupe to one package↔repo link).
POM = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.google.guava</groupId>
  <artifactId>guava</artifactId>
  <version>33.4.0-jre</version>
  <name>Guava: Google Core Libraries for Java</name>
  <description>Guava is a suite of core and expanded libraries that include
    utility classes, Google's collections, io classes, and much more.</description>
  <url>https://github.com/google/guava</url>
  <licenses>
    <license>
      <name>Apache License, Version 2.0</name>
      <url>http://www.apache.org/licenses/LICENSE-2.0.txt</url>
    </license>
  </licenses>
  <scm>
    <connection>scm:git:https://github.com/google/guava.git</connection>
    <developerConnection>scm:git:git@github.com:google/guava.git</developerConnection>
    <url>https://github.com/google/guava</url>
  </scm>
  <organization>
    <name>Google, Inc.</name>
    <url>http://www.google.com</url>
  </organization>
  <developers>
    <developer><name>Kevin Bourrillion</name></developer>
  </developers>
</project>
"""


def make_item(**overrides):
    base = dict(
        id="maven:com.google.guava:guava",
        source="maven",
        source_id="com.google.guava:guava",
        url="https://central.sonatype.com/artifact/com.google.guava/guava",
        saved_at="2026-06-14T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fakes(metadata=METADATA, pom=POM):
    """A get_text that records URLs and dispatches metadata vs POM by suffix."""
    seen = []

    def get_text(url):
        seen.append(url)
        if url.endswith("maven-metadata.xml"):
            if metadata is None:
                raise OSError("HTTP Error 404: Not Found")
            return metadata
        if pom is None:
            raise OSError("HTTP Error 404: Not Found")
        return pom

    return get_text, seen


def fetch(metadata=METADATA, pom=POM, item=None):
    get_text, _ = fakes(metadata, pom)
    return fetch_item(item or make_item(), get_text=get_text)


def pom_without(*elements):
    """The POM with the named elements removed whole (open tag through close).

    A word boundary keeps `<license>` from also matching `<licenses>`, so a
    paired multi-line element can be excised without leaving a dangling tag.
    """
    text = POM
    for el in elements:
        text = re.sub(rf"\s*<{el}\b.*?</{el}>", "", text, flags=re.DOTALL)
    return text


def test_fetch_maps_metadata():
    fetched = fetch()

    assert fetched.title == "Guava: Google Core Libraries for Java"
    assert fetched.author == "Google, Inc."  # the <organization><name> byline
    assert fetched.summary.startswith("Guava is a suite of core")
    # the README lives in the jar, not the POM: a Maven scroll is honestly
    # metadata-only (RubyGems/NuGet/Hex shape)
    assert fetched.extracted_text is None
    assert fetched.canonical_url == (
        "https://central.sonatype.com/artifact/com.google.guava/guava"
    )
    assert fetched.provenance["adapter"] == "maven"
    assert fetched.provenance["extraction_method"] == "maven-repository:pom"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_concepts_empty_by_design():
    # a POM has no keyword/topic facet, so a Maven artifact contributes nothing
    # to the KB concept graph (the RubyGems/Go/Hex posture)
    assert fetch().concepts == ()


def test_license_name_becomes_a_tag():
    # Maven license names are freeform, kept verbatim (the Hackage rule)
    assert fetch().tags == ("Apache License, Version 2.0",)


def test_multiple_licenses_become_tags():
    pom = POM.replace(
        "    </license>\n",
        "    </license>\n"
        "    <license>\n      <name>The MIT License</name>\n    </license>\n",
        1,
    )
    assert fetch(pom=pom).tags == ("Apache License, Version 2.0", "The MIT License")


def test_no_license_is_honestly_empty():
    assert fetch(pom=pom_without("licenses")).tags == ()


def test_url_and_scm_dedupe_to_one_link():
    # the project <url> equals the <scm><url>, so the package↔repo edge is one link
    assert fetch().links == ("https://github.com/google/guava",)


def test_distinct_url_and_scm_are_both_links():
    pom = POM.replace(
        "<url>https://github.com/google/guava</url>\n  <licenses>",
        "<url>https://guava.dev</url>\n  <licenses>",
    )
    assert fetch(pom=pom).links == (
        "https://guava.dev",
        "https://github.com/google/guava",
    )


def test_scm_url_dotgit_suffix_is_stripped_from_the_connection():
    # drop the <scm><url> so the repo link comes from the scm:git: connection,
    # whose .git suffix must be stripped
    pom = POM.replace(
        "    <url>https://github.com/google/guava</url>\n  </scm>",
        "  </scm>",
    ).replace(
        "  <url>https://github.com/google/guava</url>\n  <licenses>",
        "  <licenses>",
    )
    links = fetch(pom=pom).links
    assert links == ("https://github.com/google/guava",)
    assert not any(link.endswith(".git") for link in links)


def test_scm_ssh_connection_is_normalized_to_https():
    # only the ssh developerConnection remains; git@host:path → https://host/path
    pom = POM.replace(
        "    <connection>scm:git:https://github.com/google/guava.git</connection>\n",
        "",
    ).replace(
        "    <url>https://github.com/google/guava</url>\n  </scm>",
        "  </scm>",
    ).replace(
        "  <url>https://github.com/google/guava</url>\n  <licenses>",
        "  <licenses>",
    )
    assert fetch(pom=pom).links == ("https://github.com/google/guava",)


def test_no_url_or_scm_is_honestly_empty():
    pom = pom_without("scm").replace(
        "  <url>https://github.com/google/guava</url>\n", ""
    )
    assert fetch(pom=pom).links == ()


def test_title_falls_back_to_the_coordinate():
    pom = POM.replace(
        "  <name>Guava: Google Core Libraries for Java</name>\n", ""
    )
    assert fetch(pom=pom).title == "com.google.guava:guava"


def test_author_falls_back_to_the_lead_developer():
    # the <organization> block is removed whole, so the byline falls to the
    # first <developers><developer><name>
    assert fetch(pom=pom_without("organization")).author == "Kevin Bourrillion"


def test_published_at_comes_from_the_index_last_updated():
    # the POM has no date; maven-metadata.xml's lastUpdated is the deploy time
    assert fetch().published_at == "2024-12-20T15:30:00+00:00"


def test_published_at_falls_back_to_the_seed_without_last_updated():
    metadata = METADATA.replace(
        "    <lastUpdated>20241220153000</lastUpdated>\n", ""
    )
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(metadata=metadata, item=item).published_at == (
        "2026-06-01T00:00:00+00:00"
    )


def test_requests_the_metadata_then_the_release_pom_with_group_path_encoding():
    get_text, seen = fakes()
    fetch_item(make_item(), get_text=get_text)
    assert seen == [
        # the reverse-DNS group is path-encoded: com.google.guava → com/google/guava
        "https://repo1.maven.org/maven2/com/google/guava/guava/maven-metadata.xml",
        # the <release> version (33.4.0-jre), not a ranked guess
        "https://repo1.maven.org/maven2/com/google/guava/guava/"
        "33.4.0-jre/guava-33.4.0-jre.pom",
    ]


def test_falls_back_to_versions_ranking_when_no_release():
    # no <release> pointer → the highest non-SNAPSHOT version is chosen
    metadata = METADATA.replace(
        "    <release>33.4.0-jre</release>\n", ""
    )
    get_text, seen = fakes(metadata=metadata)
    fetch_item(make_item(), get_text=get_text)
    assert seen[-1].endswith("/33.4.0-jre/guava-33.4.0-jre.pom")


def test_fallback_excludes_snapshots():
    metadata = """\
<metadata><versioning>
  <versions>
    <version>2.0.0</version>
    <version>2.1.0-SNAPSHOT</version>
  </versions>
</versioning></metadata>
"""
    get_text, seen = fakes(metadata=metadata)
    fetch_item(make_item(), get_text=get_text)
    assert seen[-1].endswith("/2.0.0/guava-2.0.0.pom")


def test_raw_text_keeps_the_pom_manifest():
    assert "<artifactId>guava</artifactId>" in fetch().raw_text


def test_preserves_identity_and_the_saved_url():
    item = make_item(
        url="https://mvnrepository.com/artifact/com.google.guava/guava/33.4.0-jre"
    )
    fetched = fetch(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id)
    assert fetched.url == item.url  # the saved URL, not the canonical one
    assert fetched.saved_at == item.saved_at


@pytest.mark.parametrize("source_id", [None, "", "guava", "a:b:c"])
def test_requires_a_valid_coordinate(source_id):
    item = make_item(id="maven:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine artifact"):
        fetch_item(item, get_text=lambda url: POM)


def test_missing_artifact_is_a_fetch_error():
    # no <release> and an empty <versions> → no resolvable version
    metadata = "<metadata><versioning><versions></versions></versioning></metadata>"
    with pytest.raises(FetchError, match="not found"):
        fetch(metadata=metadata)


def test_wraps_metadata_request_errors():
    with pytest.raises(FetchError, match="404"):
        fetch(metadata=None)


def test_pom_failure_is_a_fetch_error_not_a_metadata_only_scroll():
    # the POM *is* the metadata, so its failure cannot degrade to a thin scroll
    with pytest.raises(FetchError, match="POM"):
        fetch(pom=None)


def test_malformed_metadata_is_a_fetch_error():
    with pytest.raises(FetchError, match="XML"):
        fetch(metadata="<metadata><versioning>")


def test_malformed_pom_is_a_fetch_error():
    with pytest.raises(FetchError, match="XML"):
        fetch(pom="<project><name>broken")


def test_metadata_without_versioning_is_a_fetch_error():
    with pytest.raises(FetchError, match="versioning"):
        fetch(metadata="<metadata><groupId>x</groupId></metadata>")


def test_pom_namespace_is_irrelevant():
    # a POM with no namespace must parse identically (local-name match)
    pom = POM.replace('xmlns="http://maven.apache.org/POM/4.0.0"', "")
    assert fetch(pom=pom).title == "Guava: Google Core Libraries for Java"
    assert ET.fromstring(pom) is not None  # sanity: still well-formed


def test_maven_adapter_is_registered():
    assert FETCH_ADAPTERS["maven"] is fetch_item
