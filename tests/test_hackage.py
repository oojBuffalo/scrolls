"""Tests for the Hackage (Haskell) fetch adapter (IDEAS.md §6, ADR 0091).

The cabal-file transport is faked with a manifest recorded (and trimmed) from
the real Hackage service, so the cabal-format parse (inline fields, multi-line
continuations, the `.`-blank-line description convention, the
`source-repository` stanza, comments, and sections), the `category` → concepts
split, the license → tag, the homepage/repo → links dedup, and the error
handling are all covered offline (ADR 0001).
"""

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.hackage import fetch_item


# Recorded (and trimmed) from
# https://hackage.haskell.org/package/aeson/aeson.cabal — a modern cabal with
# an SPDX license, a comma-separated category, a multi-line description using
# the cabal `.` blank-line marker, a `source-repository` stanza whose `.git`
# location dedupes against the homepage, a full-line comment, and a `library`
# section whose fields must not be read as package fields.
CABAL = """\
cabal-version:      2.2
name:               aeson
version:            2.3.0.0
x-revision: 1
-- a full-line comment that must be ignored
license:            BSD-3-Clause
license-file:       LICENSE
category:           Text, Web, JSON
copyright:
  (c) 2011-2016 Bryan O'Sullivan
author:             Bryan O'Sullivan <bos@serpentine.com>
maintainer:         Adam Bergmark <adam@bergmark.nl>
synopsis:           Fast JSON parsing and encoding
homepage:           https://github.com/haskell/aeson
bug-reports:        https://github.com/haskell/aeson/issues
build-type:         Simple
description:
  A JSON parsing and encoding library optimized for ease of use
  and high performance.
  .
  A note on naming: Aeson was the father of Jason.

source-repository head
  type:     git
  location: https://github.com/haskell/aeson.git

library
  exposed-modules:  Data.Aeson
  build-depends:    base
  homepage:         https://not-a-package-field.example
"""


def make_item(**overrides):
    base = dict(
        id="hackage:aeson",
        source="hackage",
        source_id="aeson",
        url="https://hackage.haskell.org/package/aeson",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fetch(cabal=CABAL, item=None):
    def get_text(url):
        if cabal is None:
            raise OSError("HTTP Error 404: Not Found")
        return cabal

    return fetch_item(item or make_item(), get_text=get_text)


def fetch_recording(cabal=CABAL, item=None):
    """Fetch and also return the list of URLs the fetcher was asked for."""
    seen = []

    def get_text(url):
        seen.append(url)
        return cabal

    fetched = fetch_item(item or make_item(), get_text=get_text)
    return fetched, seen


def without(field):
    """The CABAL with a top-level `field:` line removed (its value inline)."""
    return "\n".join(
        line for line in CABAL.splitlines()
        if not line.startswith(f"{field}:")
    ) + "\n"


def test_fetch_maps_metadata():
    fetched = fetch()

    assert fetched.title == "aeson"
    # the author's <email> is stripped to a clean byline
    assert fetched.author == "Bryan O'Sullivan"
    # synopsis is the short summary
    assert fetched.summary == "Fast JSON parsing and encoding"
    assert fetched.canonical_url == "https://hackage.haskell.org/package/aeson"
    assert fetched.provenance["adapter"] == "hackage"
    assert fetched.provenance["extraction_method"] == "hackage-cabal"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_description_becomes_the_searchable_body():
    # the cabal's prose description → extracted_text, the `.` line a paragraph
    # break (the cabal/haddock blank-line convention)
    assert fetch().extracted_text == (
        "A JSON parsing and encoding library optimized for ease of use\n"
        "and high performance.\n"
        "\n"
        "A note on naming: Aeson was the father of Jason."
    )


def test_category_becomes_concepts():
    # category is comma-separated → concepts (the github-topics/keywords role),
    # so a Haskell package joins the KB concept graph
    assert fetch().concepts == ("Text", "Web", "JSON")


def test_no_category_is_honestly_empty():
    assert fetch(cabal=without("category")).concepts == ()


def test_license_becomes_a_tag():
    assert fetch().tags == ("BSD-3-Clause",)


def test_legacy_cabal_license_is_kept_verbatim():
    # older cabal files carry cabal's own license ids (e.g. BSD2), not SPDX;
    # the field is taken verbatim as a still-useful filter tag
    assert fetch(cabal=CABAL.replace("BSD-3-Clause", "BSD2")).tags == ("BSD2",)


def test_no_license_is_honestly_empty():
    assert fetch(cabal=without("license")).tags == ()


def test_homepage_and_repo_dedupe_to_one_link():
    # homepage and the source-repository location point at the same repo (one
    # with a `.git` suffix), so the package↔repo edge is one link;
    # bug-reports is not a link
    assert fetch().links == ("https://github.com/haskell/aeson",)


def test_distinct_homepage_and_repo_are_both_links():
    # a homepage distinct from the repo yields two links, in order
    cabal = CABAL.replace(
        "homepage:           https://github.com/haskell/aeson",
        "homepage:           https://aeson.example.org",
    )
    assert fetch(cabal=cabal).links == (
        "https://aeson.example.org",
        "https://github.com/haskell/aeson",
    )


def test_section_fields_are_not_read_as_package_fields():
    # the `library` stanza's homepage must not override the package homepage
    assert "not-a-package-field" not in str(fetch().links)


def test_requests_the_cabal_endpoint():
    _, seen = fetch_recording()
    assert seen == ["https://hackage.haskell.org/package/aeson/aeson.cabal"]


def test_case_sensitive_name_is_preserved_in_the_request():
    # Hackage package names are case-sensitive (QuickCheck, not quickcheck)
    item = make_item(id="hackage:QuickCheck", source_id="QuickCheck")
    cabal = CABAL.replace("name:               aeson", "name:               QuickCheck")
    _, seen = fetch_recording(cabal=cabal, item=item)
    assert seen == [
        "https://hackage.haskell.org/package/QuickCheck/QuickCheck.cabal"
    ]


def test_published_at_is_left_as_the_seed():
    # the cabal carries no upload date; the adapter never invents one
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_raw_text_keeps_the_cabal_manifest():
    assert "name:               aeson" in fetch().raw_text


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://hackage.haskell.org/package/aeson-2.3.0.0")
    fetched = fetch(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id)
    assert fetched.url == item.url
    assert fetched.saved_at == item.saved_at


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_a_package_name(source_id):
    item = make_item(id="hackage:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine package"):
        fetch_item(item, get_text=lambda url: CABAL)


def test_missing_package_is_a_fetch_error():
    with pytest.raises(FetchError, match="request failed"):
        fetch(cabal=None)


def test_cabal_without_a_name_is_a_fetch_error():
    with pytest.raises(FetchError, match="not found|no package"):
        fetch(cabal="synopsis: orphan\nlicense: MIT\n")


def test_hackage_adapter_is_registered():
    assert FETCH_ADAPTERS["hackage"] is fetch_item
