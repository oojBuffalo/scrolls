"""Tests for the Zenodo record fetch adapter (IDEAS.md §6, ADR 0083).

The JSON transport is faked with a record whose shape was recorded from the
real Zenodo REST API (`zenodo.org/api/records/<id>`, an InvenioRDM record —
no JSON:API envelope), so the field mapping, the resource-type → category
signal, the HTML description cleaning, the keyword/subject concepts, the
type/subtype/license tagging, the DOI and related-identifier links, and error
handling are all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources import zenodo
from scrolls.sources.zenodo import fetch_item

# Shape recorded from https://zenodo.org/api/records/7834392 (a COVID-19 Twitter
# dataset), trimmed and adapted to exercise every path: an HTML description, a
# version record with a concept DOI, keywords + a subject, a license, and the
# three related-identifier schemes (a url to an arXiv preprint, a doi, an arxiv
# id with the `arXiv:` prefix).
ZENODO_RECORD = {
    "id": 7834392,
    "recid": 7834392,
    "conceptrecid": 3723939,
    "doi": "10.5281/zenodo.7834392",
    "conceptdoi": "10.5281/zenodo.3723939",
    "title": "A large-scale COVID-19 Twitter chatter dataset",
    "links": {"self_html": "https://zenodo.org/records/7834392"},
    "metadata": {
        "title": "A large-scale COVID-19 Twitter chatter dataset",
        "doi": "10.5281/zenodo.7834392",
        "publication_date": "2023-04-16",
        "resource_type": {"title": "Dataset", "type": "dataset"},
        "license": {"id": "cc-by-4.0"},
        "creators": [
            {
                "name": "Banda, Juan M.",
                "affiliation": "Georgia State University",
                "orcid": "0000-0001-8499-824X",
            },
            {"name": "Tekumalla, Ramya", "affiliation": "Georgia State University"},
        ],
        "keywords": ["social media", "twitter", "nlp", "covid-19"],
        "subjects": [{"subject": "Computational social science"}],
        "description": "<p><em>Version 162</em> of the dataset. Twitter chatter "
        "about <strong>COVID-19</strong> .</p>",
        "related_identifiers": [
            {
                "relation": "isSupplementTo",
                "scheme": "url",
                "identifier": "https://arxiv.org/abs/2004.03688",
            },
            {"relation": "isPartOf", "scheme": "doi", "identifier": "10.11646/zootaxa.5351.1.1"},
            {"relation": "cites", "scheme": "arxiv", "identifier": "arXiv:1909.01066"},
        ],
    },
}


def make_item(**overrides):
    base = dict(
        id="zenodo:7834392",
        source="zenodo",
        source_id="7834392",
        url="https://zenodo.org/records/7834392",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_get_json(doc=ZENODO_RECORD):
    def get_json(url):
        return json.loads(json.dumps(doc))  # deep copy

    return get_json


def fetch(doc=ZENODO_RECORD, item=None):
    return fetch_item(item or make_item(), get_json=fake_get_json(doc))


def test_fetch_maps_core_metadata():
    fetched = fetch()

    assert fetched.title == "A large-scale COVID-19 Twitter chatter dataset"
    assert fetched.author == "Banda, Juan M., Tekumalla, Ramya"
    # the resolved version's landing page (self_html), not the saved URL
    assert fetched.canonical_url == "https://zenodo.org/records/7834392"
    assert fetched.published_at == "2023-04-16T00:00:00+00:00"
    assert fetched.provenance["adapter"] == "zenodo"
    assert fetched.provenance["extraction_method"] == "zenodo-api:json"
    # the resource type is recorded for the classifier (it can't be known from
    # the URL, so the source name can't carry it) — the DataCite mechanism
    assert fetched.provenance["resource_type"] == "dataset"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_description_is_cleaned_to_plain_summary_with_no_extracted_text():
    fetched = fetch()
    assert fetched.summary == "Version 162 of the dataset. Twitter chatter about COVID-19."
    assert "<em>" not in fetched.summary
    # catalog metadata, not a work body — the Crossref/DataCite/Open Library shape
    assert fetched.extracted_text is None


def test_no_description_degrades_to_metadata_only():
    doc = json.loads(json.dumps(ZENODO_RECORD))
    doc["metadata"].pop("description")
    fetched = fetch(doc)
    assert fetched.summary is None
    assert fetched.title == "A large-scale COVID-19 Twitter chatter dataset"
    assert fetched.stage == "fetched"


def test_keywords_and_subjects_become_concepts():
    assert fetch().concepts == (
        "social media",
        "twitter",
        "nlp",
        "covid-19",
        "Computational social science",
    )


def test_no_keywords_or_subjects_is_honestly_empty():
    doc = json.loads(json.dumps(ZENODO_RECORD))
    doc["metadata"].pop("keywords")
    doc["metadata"].pop("subjects")
    assert fetch(doc).concepts == ()


def test_subjects_term_key_is_also_read():
    # InvenioRDM subjects may key the label `term` rather than `subject`.
    doc = json.loads(json.dumps(ZENODO_RECORD))
    doc["metadata"]["keywords"] = []
    doc["metadata"]["subjects"] = [{"term": "Epidemiology"}]
    assert fetch(doc).concepts == ("Epidemiology",)


def test_type_subtype_and_license_become_tags():
    doc = json.loads(json.dumps(ZENODO_RECORD))
    doc["metadata"]["resource_type"] = {
        "title": "Journal article",
        "type": "publication",
        "subtype": "article",
    }
    assert fetch(doc).tags == ("publication", "article", "cc-by-4.0")


def test_tags_without_subtype_or_license():
    # the recorded dataset has no subtype; license is the only extra facet
    assert fetch().tags == ("dataset", "cc-by-4.0")


def test_published_at_pads_a_year_only_date():
    doc = json.loads(json.dumps(ZENODO_RECORD))
    doc["metadata"]["publication_date"] = "2020"
    assert fetch(doc).published_at == "2020-01-01T00:00:00+00:00"


def test_missing_publication_date_falls_back_to_the_seed():
    doc = json.loads(json.dumps(ZENODO_RECORD))
    doc["metadata"].pop("publication_date")
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(doc, item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_long_creator_list_is_truncated_with_et_al():
    doc = json.loads(json.dumps(ZENODO_RECORD))
    # real Zenodo creators are comma-bearing "Family, Given", so assert on the
    # names themselves, not a comma count: the head 10 kept, the 11th dropped
    doc["metadata"]["creators"] = [{"name": f"Surname{i}, Given"} for i in range(25)]
    author = fetch(doc).author
    assert author.endswith(", et al.")
    assert "Surname9, Given" in author  # the 10th (0-indexed) is kept
    assert "Surname10, Given" not in author  # the 11th is dropped


def test_missing_creators_leaves_author_absent():
    doc = json.loads(json.dumps(ZENODO_RECORD))
    doc["metadata"].pop("creators")
    assert fetch(doc).author is None


def test_title_falls_back_to_top_level_then_doi():
    doc = json.loads(json.dumps(ZENODO_RECORD))
    doc["metadata"].pop("title")
    assert fetch(doc).title == "A large-scale COVID-19 Twitter chatter dataset"  # top-level
    doc["title"] = None
    assert fetch(doc).title == "10.5281/zenodo.7834392"  # the DOI, never untitled


def test_canonical_falls_back_to_the_records_url_without_self_html():
    doc = json.loads(json.dumps(ZENODO_RECORD))
    doc.pop("links")
    assert fetch(doc).canonical_url == "https://zenodo.org/records/7834392"


def test_links_carry_record_doi_concept_doi_and_related_identifiers():
    # record DOI, concept DOI, then the three related-identifier schemes:
    # a url (the supplemented arXiv preprint), a doi, and an arxiv id
    assert fetch().links == (
        "https://doi.org/10.5281/zenodo.7834392",
        "https://doi.org/10.5281/zenodo.3723939",
        "https://arxiv.org/abs/2004.03688",
        "https://doi.org/10.11646/zootaxa.5351.1.1",
        "https://arxiv.org/abs/1909.01066",
    )


def test_arxiv_related_identifier_without_a_prefix():
    doc = json.loads(json.dumps(ZENODO_RECORD))
    doc["metadata"]["related_identifiers"] = [
        {"relation": "isSupplementTo", "scheme": "arxiv", "identifier": "2004.03688"}
    ]
    doc.pop("conceptdoi")
    assert fetch(doc).links == (
        "https://doi.org/10.5281/zenodo.7834392",
        "https://arxiv.org/abs/2004.03688",
    )


def test_non_http_url_and_unknown_scheme_related_identifiers_are_skipped():
    doc = json.loads(json.dumps(ZENODO_RECORD))
    doc.pop("conceptdoi")
    doc["metadata"]["related_identifiers"] = [
        {"relation": "isIdenticalTo", "scheme": "isbn", "identifier": "978-3-16-148410-0"},
        {"relation": "references", "scheme": "url", "identifier": "ftp://example.org/data"},
    ]
    # only the record DOI survives — neither related identifier resolves here
    assert fetch(doc).links == ("https://doi.org/10.5281/zenodo.7834392",)


def test_duplicate_related_identifier_is_deduped():
    doc = json.loads(json.dumps(ZENODO_RECORD))
    doc.pop("conceptdoi")
    doc["metadata"]["related_identifiers"] = [
        {"relation": "isPartOf", "scheme": "doi", "identifier": "10.11646/zootaxa.5351.1.1"},
        {"relation": "cites", "scheme": "doi", "identifier": "10.11646/ZOOTAXA.5351.1.1"},
    ]
    assert fetch(doc).links == (
        "https://doi.org/10.5281/zenodo.7834392",
        "https://doi.org/10.11646/zootaxa.5351.1.1",
    )


def test_record_with_no_doi_emits_no_doi_links():
    doc = json.loads(json.dumps(ZENODO_RECORD))
    doc.pop("doi")
    doc["metadata"].pop("doi")
    doc.pop("conceptdoi")
    doc["metadata"].pop("related_identifiers")
    assert fetch(doc).links == ()


@pytest.mark.parametrize(
    "mangle",
    [
        lambda m: m.update(title=123),
        lambda m: m.update(creators="nope"),
        lambda m: m.update(creators=["not a dict", {"name": None}]),
        lambda m: m.update(keywords="nope"),
        lambda m: m.update(subjects=[{"subject": None}, "x", {}]),
        lambda m: m.update(resource_type="not an object"),
        lambda m: m.update(resource_type={"type": None}),
        lambda m: m.update(license="nope"),
        lambda m: m.update(description=5),
        lambda m: m.update(publication_date=None),
        lambda m: m.update(related_identifiers="nope"),
        lambda m: m.update(related_identifiers=[{"identifier": None}, "x"]),
        lambda m: m.clear(),  # an essentially empty metadata object
    ],
)
def test_malformed_fields_never_raise(mangle):
    # A partial or garbage Zenodo response must degrade, never crash the batch
    # with an unhandled KeyError/AttributeError/TypeError.
    doc = json.loads(json.dumps(ZENODO_RECORD))
    mangle(doc["metadata"])
    fetched = fetch(doc)  # must not raise
    assert fetched.stage == "fetched"
    assert fetched.title  # always at least the DOI / a title


def test_keeps_the_raw_metadata_record():
    raw = json.loads(fetch().raw_text)
    assert raw["doi"] == "10.5281/zenodo.7834392"
    assert raw["resource_type"]["type"] == "dataset"


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://zenodo.org/record/7834392")  # legacy singular
    fetched = fetch(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id,
        item.source,
        item.source_id,
    )
    assert fetched.url == item.url  # the saved URL, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_requests_the_expected_api_url():
    seen = []

    def get_json(url):
        seen.append(url)
        return json.loads(json.dumps(ZENODO_RECORD))

    fetch_item(make_item(), get_json=get_json)
    assert seen == ["https://zenodo.org/api/records/7834392"]


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_a_record_id(source_id):
    item = make_item(id="zenodo:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine Zenodo record id"):
        fetch_item(item, get_json=fake_get_json())


def test_record_not_found_is_a_fetch_error():
    # a 404 returns a JSON error object with no `metadata`
    with pytest.raises(FetchError, match="record not found"):
        fetch_item(make_item(), get_json=lambda url: {"status": 404, "message": "not found"})


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom)


def test_registered_in_fetch_adapters():
    assert FETCH_ADAPTERS["zenodo"] is zenodo.fetch_item
