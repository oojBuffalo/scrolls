"""Tests for the RFC fetch adapter (IETF Requests for Comments, ADR 0066).

The JSON transport is faked with a record recorded (and trimmed) from the real
RFC Editor JSON view for RFC 9110 (HTTP Semantics, June 2022), so the field
mapping, keywords-as-concepts, the status tag, the month-name date parsing, the
DOI and obsoletes/updates cross-document links, and error handling are all
covered offline (ADR 0001).
"""

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.rfc import fetch_item

# Recorded (and trimmed) from https://www.rfc-editor.org/rfc/rfc9110.json. RFC
# 9110 obsoletes nine RFCs and updates one, carries keywords and a DOI, and its
# pub_date is the "Month Year" shape every RFC uses.
RFC_DOC = {
    "draft": "draft-ietf-httpbis-semantics-19",
    "doc_id": "RFC9110",
    "title": "HTTP Semantics",
    "authors": ["R. Fielding, Ed.", "M. Nottingham, Ed.", "J. Reschke, Ed."],
    "format": ["HTML", "TEXT", "PDF", "XML"],
    "page_count": "194",
    "pub_status": "INTERNET STANDARD",
    "status": "INTERNET STANDARD",
    "source": "HTTP",
    "abstract": (
        "The Hypertext Transfer Protocol (HTTP) is a stateless application-level "
        "protocol for distributed, collaborative, hypertext information systems. "
        "This document describes the overall architecture of HTTP."
    ),
    "pub_date": "June 2022",
    "keywords": [
        "Hypertext Transfer Protocol", "HTTP", "HTTP semantics",
        "HTTP content", "HTTP method", "HTTP status code",
    ],
    "obsoletes": [
        "RFC2818", "RFC7230", "RFC7231", "RFC7232", "RFC7233",
        "RFC7235", "RFC7538", "RFC7615", "RFC7694",
    ],
    "obsoleted_by": [],
    "updates": ["RFC3864"],
    "updated_by": [],
    "see_also": ["STD0097"],
    "doi": "10.17487/RFC9110",
    "errata_url": "https://www.rfc-editor.org/errata/rfc9110",
}


def make_item(**overrides):
    base = dict(
        id="rfc:9110",
        source="rfc",
        source_id="9110",
        url="https://www.rfc-editor.org/rfc/rfc9110",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fetch(doc=None, item=None):
    payload = RFC_DOC if doc is None else doc
    return fetch_item(item or make_item(), get_json=lambda url: payload)


def variant(**changes):
    """RFC_DOC with some keys replaced."""
    doc = dict(RFC_DOC)
    doc.update(changes)
    return doc


def without(*keys):
    """RFC_DOC with some keys removed."""
    return {k: v for k, v in RFC_DOC.items() if k not in keys}


def test_fetch_maps_core_metadata():
    fetched = fetch()

    # the RFC number leads the title — an RFC's canonical name is its number
    assert fetched.title == "RFC 9110: HTTP Semantics"
    # the RFC Editor's display-string byline, joined verbatim (no name reorder)
    assert fetched.author == "R. Fielding, Ed., M. Nottingham, Ed., J. Reschke, Ed."
    assert fetched.canonical_url == "https://www.rfc-editor.org/rfc/rfc9110"
    assert fetched.provenance["adapter"] == "rfc"
    assert fetched.provenance["extraction_method"] == "rfc-editor:json"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_abstract_becomes_plain_summary_no_full_text():
    fetched = fetch()
    assert fetched.summary.startswith("The Hypertext Transfer Protocol")
    # the RFC body is published separately, so the JSON view has no full text —
    # the Crossref/PubMed metadata-only shape
    assert fetched.extracted_text is None


def test_no_abstract_degrades_to_metadata_only():
    fetched = fetch(without("abstract"))
    assert fetched.summary is None
    # still a useful scroll: title, authors, keywords, status, links
    assert fetched.title == "RFC 9110: HTTP Semantics"
    assert fetched.concepts[0] == "Hypertext Transfer Protocol"
    assert fetched.tags == ("Internet Standard",)


def test_whitespace_only_abstract_is_dropped():
    # older RFCs store a whitespace-only abstract placeholder
    assert fetch(variant(abstract="  ")).summary is None


def test_keywords_become_concepts():
    assert fetch().concepts == (
        "Hypertext Transfer Protocol", "HTTP", "HTTP semantics",
        "HTTP content", "HTTP method", "HTTP status code",
    )


def test_whitespace_only_keyword_placeholder_is_dropped():
    # older RFCs carry keywords == ["  "]; it must not become a concept
    assert fetch(variant(keywords=["  "])).concepts == ()


def test_duplicate_keywords_are_deduped():
    assert fetch(variant(keywords=["HTTP", "http ", "HTTP"])).concepts == (
        "HTTP", "http",
    )


def test_status_becomes_a_titlecased_tag():
    # the upper-cased maturity vocabulary is title-cased for a readable KB tag
    assert fetch().tags == ("Internet Standard",)
    assert fetch(variant(status="BEST CURRENT PRACTICE")).tags == (
        "Best Current Practice",
    )


def test_missing_status_leaves_tags_empty():
    assert fetch(without("status")).tags == ()


def test_doi_becomes_the_crossref_link():
    # the RFC's own DOI (10.17487/RFC<N>) resolves through detection to the
    # crossref:<doi> item — the RFC↔Crossref edge (ADR 0038's analog)
    assert fetch().links[0] == "https://doi.org/10.17487/RFC9110"


def test_obsoletes_and_updates_become_rfc_links():
    links = fetch().links
    # obsoletes first, then updates, after the DOI; each an rfc-editor link that
    # resolves to that RFC's scroll (the RFC↔RFC standards-lineage edge)
    assert "https://www.rfc-editor.org/rfc/rfc7230" in links
    assert "https://www.rfc-editor.org/rfc/rfc3864" in links  # the lone update
    assert links == (
        "https://doi.org/10.17487/RFC9110",
        "https://www.rfc-editor.org/rfc/rfc2818",
        "https://www.rfc-editor.org/rfc/rfc7230",
        "https://www.rfc-editor.org/rfc/rfc7231",
        "https://www.rfc-editor.org/rfc/rfc7232",
        "https://www.rfc-editor.org/rfc/rfc7233",
        "https://www.rfc-editor.org/rfc/rfc7235",
        "https://www.rfc-editor.org/rfc/rfc7538",
        "https://www.rfc-editor.org/rfc/rfc7615",
        "https://www.rfc-editor.org/rfc/rfc7694",
        "https://www.rfc-editor.org/rfc/rfc3864",
    )


def test_inverse_relations_are_not_emitted():
    # obsoleted_by/updated_by are the mirror of some other RFC's obsoletes/updates,
    # surfaced by the graph's bidirectional resolution, so they add no links here
    doc = variant(obsoletes=[], updates=[], obsoleted_by=["RFC9999"], updated_by=["RFC9998"])
    assert fetch(doc).links == ("https://doi.org/10.17487/RFC9110",)


def test_zero_padded_relation_number_is_normalized():
    # a low-numbered relation is zero-padded ("RFC0020"); the link drops the zeros
    doc = variant(obsoletes=["RFC0020"], updates=[], doi=None)
    assert fetch(doc).links == ("https://www.rfc-editor.org/rfc/rfc20",)


def test_no_doi_and_no_relations_leaves_links_empty():
    assert fetch(variant(doi=None, obsoletes=[], updates=[])).links == ()


def test_published_at_parses_month_year():
    # "June 2022" pads to the first of the month (ADR 0024's uniform shape)
    assert fetch().published_at == "2022-06-01T00:00:00+00:00"


def test_published_at_parses_a_legacy_month_name():
    assert fetch(variant(pub_date="October 1969")).published_at == (
        "1969-10-01T00:00:00+00:00"
    )


def test_published_at_falls_back_to_a_bare_year():
    assert fetch(variant(pub_date="Q1 2001")).published_at == (
        "2001-01-01T00:00:00+00:00"
    )


def test_unparseable_date_keeps_the_existing_value():
    item = make_item(published_at="2020-01-01T00:00:00+00:00")
    assert fetch(item=item, doc=variant(pub_date="someday")).published_at == (
        "2020-01-01T00:00:00+00:00"
    )


def test_zero_padded_number_in_title_and_url():
    # detection mints rfc:20 for a zero-padded rfc0020 URL; the scroll uses 20
    fetched = fetch(item=make_item(id="rfc:20", source_id="20"))
    assert fetched.title == "RFC 20: HTTP Semantics"
    assert fetched.canonical_url == "https://www.rfc-editor.org/rfc/rfc20"


def test_long_author_list_truncated_with_et_al():
    authors = [f"A. Author{i}" for i in range(25)]
    author = fetch(variant(authors=authors)).author
    assert author.endswith(", et al.")
    assert author.count(",") == 10  # 10 names + the trailing "et al." marker


def test_missing_authors_leaves_author_absent():
    assert fetch(without("authors")).author is None


def test_title_falls_back_to_rfc_number_when_absent():
    # a record always carries doc_id; only the human title is ever missing
    assert fetch(without("title")).title == "RFC 9110"


def test_keeps_raw_json():
    assert '"doc_id": "RFC9110"' in fetch().raw_text


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://datatracker.ietf.org/doc/html/rfc9110")
    fetched = fetch(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id)
    assert fetched.url == item.url  # the saved URL, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_requests_the_expected_json_url():
    seen = []

    def get_json(url):
        seen.append(url)
        return RFC_DOC

    fetch_item(make_item(), get_json=get_json)
    assert seen == ["https://www.rfc-editor.org/rfc/rfc9110.json"]


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_an_rfc_number(source_id):
    item = make_item(id="rfc:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine RFC number"):
        fetch_item(item, get_json=lambda url: RFC_DOC)


def test_non_record_response_is_a_fetch_error():
    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_item(), get_json=lambda url: {})


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom)


def test_registered_in_fetch_adapters():
    assert FETCH_ADAPTERS["rfc"] is fetch_item
