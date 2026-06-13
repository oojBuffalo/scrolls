"""Tests for the bioRxiv / medRxiv fetch adapter (IDEAS.md §6, ADR 0068).

The JSON transport is faked with `details` documents recorded (and
trimmed) from the real `api.biorxiv.org` API, so version selection, the
abstract-as-summary semantics, author reordering and truncation, the
subject-as-concept and type/venue/license tagging, the preprint↔published
DOI edge, the shared adapter serving both servers, and error handling are
all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.classify import classify_item
from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.biorxiv import fetch_item

# Recorded (and trimmed) from
# https://api.biorxiv.org/details/biorxiv/10.1101/2020.03.20.001008 — two
# versions, both carrying the published-journal DOI (it became a PLoS Biology
# paper). The collection is returned ascending, so v2 is the current preprint.
BIORXIV_DOC = {
    "messages": [{"status": "ok", "category": "all"}],
    "collection": [
        {
            "title": "RT-qPCR DETECTION OF SARS-CoV-2 RNA (extraction kit version)",
            "authors": "Bruce, E. A.; Tighe, S.; Hoffman, J. J.; Botten, J. W.",
            "author_corresponding": "Jason W Botten",
            "doi": "10.1101/2020.03.20.001008",
            "date": "2020-03-21",
            "version": "1",
            "type": "new results",
            "license": "cc_by_nc_nd",
            "category": "microbiology",
            "abstract": "An older v1 abstract that should not win.",
            "published": "10.1371/journal.pbio.3000896",
            "server": "bioRxiv",
        },
        {
            "title": "DIRECT RT-qPCR DETECTION OF SARS-CoV-2 RNA WITHOUT AN "
            "RNA EXTRACTION STEP",
            "authors": "Bruce, E. A.; Huang, M.-L.; Perchetti, G. A.; Tighe, S.; "
            "Hoffman, J. J.; Laaguiby, P.; Gerrard, D. L.; Nalla, A.; Wei, Y.; "
            "Greninger, A. L.; Diehl, S. A.; Botten, J. W.",
            "author_corresponding": "Jason W Botten",
            "doi": "10.1101/2020.03.20.001008",
            "date": "2020-04-06",
            "version": "2",
            "type": "new results",
            "license": "cc_by_nc_nd",
            "category": "microbiology",
            "abstract": "The ongoing COVID-19 pandemic has caused an "
            "unprecedented need for rapid diagnostic testing.\n\nImportanceWe "
            "show an RNA-extraction-free protocol.",
            "published": "10.1371/journal.pbio.3000896",
            "server": "bioRxiv",
        },
    ],
}

# Recorded (and trimmed) from
# https://api.biorxiv.org/details/medrxiv/10.1101/2020.03.09.20033357 — one
# version, still a preprint (published == "NA"), an 8-digit accession serial,
# and the legacy `PUBLISHAHEADOFPRINT` sentinel in `type`.
MEDRXIV_DOC = {
    "messages": [{"status": "ok", "category": "all"}],
    "collection": [
        {
            "title": "Estimates of the severity of COVID-19 disease",
            "authors": "Verity, R.; Okell, L. C.; Dorigatti, I.; Ghani, A.; "
            "Ferguson, N.",
            "author_corresponding": "Azra Ghani",
            "doi": "10.1101/2020.03.09.20033357",
            "date": "2020-03-13",
            "version": "1",
            "type": "PUBLISHAHEADOFPRINT",
            "license": "cc_by_nc_nd",
            "category": "epidemiology",
            "abstract": "BackgroundA range of case fatality ratio estimates exist.",
            "published": "NA",
            "server": "medRxiv",
        }
    ],
}

NOT_FOUND_DOC = {"messages": [{"status": "no posts found"}], "collection": []}


def make_item(source="biorxiv", source_id="10.1101/2020.03.20.001008", **overrides):
    base = dict(
        id=f"{source}:{source_id}",
        source=source,
        source_id=source_id,
        url=f"https://www.{source}.org/content/{source_id}v1",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_get_json(doc=BIORXIV_DOC):
    def get_json(url):
        return json.loads(json.dumps(doc))  # deep copy

    return get_json


def fetch(doc=BIORXIV_DOC, item=None):
    return fetch_item(item or make_item(), get_json=fake_get_json(doc))


def test_fetch_maps_core_metadata_from_latest_version():
    fetched = fetch()

    # v2 wins over v1 — the highest version is the current preprint
    assert fetched.title.startswith("DIRECT RT-qPCR")
    assert fetched.summary.startswith("The ongoing COVID-19 pandemic")
    assert fetched.published_at == "2020-04-06T00:00:00+00:00"
    # the canonical URL is rebuilt at the latest version
    assert fetched.canonical_url == (
        "https://www.biorxiv.org/content/10.1101/2020.03.20.001008v2"
    )
    assert fetched.provenance["adapter"] == "biorxiv"
    assert fetched.provenance["extraction_method"] == "biorxiv-api:json"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_authors_are_reordered_and_truncated():
    # "Family, G. I." -> "G. I. Family"; v2 has 12 authors, so the head of 10
    # is kept and "et al." appended
    authors = fetch().author
    assert authors.startswith("E. A. Bruce, M.-L. Huang, G. A. Perchetti")
    assert authors.endswith("et al.")
    assert authors.count(",") == 10  # 10 names + the et-al joiner


def test_abstract_whitespace_is_collapsed_to_one_summary():
    summary = fetch().summary
    assert "\n" not in summary
    assert "rapid diagnostic testing. ImportanceWe show" in summary


def test_subject_category_becomes_the_one_concept():
    # the subject area is the concept (sentence-cased), the github-topics slot
    assert fetch().concepts == ("Microbiology",)


def test_tags_are_type_venue_and_license():
    # a real type is title-cased; the server is the venue; the CC code maps
    assert fetch().tags == ("New Results", "bioRxiv", "CC-BY-NC-ND")


def test_published_doi_becomes_the_crossref_edge():
    # the journal DOI links to the crossref item — the preprint↔published edge
    assert fetch().links == ("https://doi.org/10.1371/journal.pbio.3000896",)


def test_biorxiv_preprint_classifies_as_paper():
    assert classify_item(fetch()).category == "paper"


# --- medRxiv: same adapter, other server -------------------------------------


def test_medrxiv_uses_the_same_adapter_via_source():
    item = make_item(source="medrxiv", source_id="10.1101/2020.03.09.20033357")
    fetched = fetch_item(item, get_json=fake_get_json(MEDRXIV_DOC))

    assert fetched.title == "Estimates of the severity of COVID-19 disease"
    assert fetched.provenance["adapter"] == "medrxiv"
    assert fetched.canonical_url == (
        "https://www.medrxiv.org/content/10.1101/2020.03.09.20033357v1"
    )
    assert fetched.concepts == ("Epidemiology",)


def test_medrxiv_sentinel_type_is_dropped_and_unpublished_has_no_links():
    item = make_item(source="medrxiv", source_id="10.1101/2020.03.09.20033357")
    fetched = fetch_item(item, get_json=fake_get_json(MEDRXIV_DOC))

    # the PUBLISHAHEADOFPRINT sentinel (no space) is not tagged; venue+license stay
    assert fetched.tags == ("medRxiv", "CC-BY-NC-ND")
    # a preprint not yet published in a journal has no outgoing edge
    assert fetched.links == ()


def test_medrxiv_classifies_as_paper():
    item = make_item(source="medrxiv", source_id="10.1101/2020.03.09.20033357")
    fetched = fetch_item(item, get_json=fake_get_json(MEDRXIV_DOC))
    assert classify_item(fetched).category == "paper"


def test_url_targets_the_servers_endpoint():
    captured = {}

    def get_json(url):
        captured["url"] = url
        return json.loads(json.dumps(MEDRXIV_DOC))

    item = make_item(source="medrxiv", source_id="10.1101/2020.03.09.20033357")
    fetch_item(item, get_json=get_json)
    assert captured["url"] == (
        "https://api.biorxiv.org/details/medrxiv/10.1101/2020.03.09.20033357"
    )


# --- registration & error handling -------------------------------------------


def test_both_sources_register_the_shared_adapter():
    assert FETCH_ADAPTERS["biorxiv"] is fetch_item
    assert FETCH_ADAPTERS["medrxiv"] is fetch_item


def test_unknown_doi_raises_fetch_error():
    with pytest.raises(FetchError, match="preprint not found"):
        fetch(NOT_FOUND_DOC)


def test_missing_source_id_raises_fetch_error():
    item = make_item(source_id=None)
    with pytest.raises(FetchError, match="cannot determine DOI"):
        fetch_item(item, get_json=fake_get_json())


def test_network_failure_raises_fetch_error():
    def boom(url):
        raise OSError("connection reset")

    with pytest.raises(FetchError, match="bioRxiv API request failed"):
        fetch_item(make_item(), get_json=boom)


def test_missing_abstract_degrades_to_metadata_only():
    doc = json.loads(json.dumps(BIORXIV_DOC))
    for entry in doc["collection"]:
        entry["abstract"] = ""
    fetched = fetch(doc)
    assert fetched.summary is None
    assert fetched.title.startswith("DIRECT RT-qPCR")  # still a usable scroll
    assert fetched.content_hash.startswith("sha256:")
