"""Tests for the DataCite / DOI fetch adapter (IDEAS.md §6, ADR 0045).

The JSON transport is faked with a DOI document whose shape was recorded
from the real DataCite REST API (`api.datacite.org/dois/<doi>`, JSON:API),
so the field mapping, the resource-type → category signal, description
cleaning, creator formatting, the DataCite date precedence, the type/venue
tagging, the landing/container links, and error handling are all covered
offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources import doi as doi_dispatch
from scrolls.sources.datacite import fetch_item

# Shape recorded from https://api.datacite.org/dois/10.5281/zenodo.8408173
# (a Zenodo deposit), adapted into a dataset record exercising every path:
# a subtitle, a person + an organization creator, an Abstract description
# alongside an Other one, an Issued date winning over Created, a landing URL,
# and a container DOI (the parent work).
DOI_DOC = {
    "data": {
        "id": "10.5281/zenodo.8408173",
        "type": "dois",
        "attributes": {
            "doi": "10.5281/zenodo.8408173",
            "titles": [
                {"title": "Global Coastal Biodiversity Survey"},
                {"title": "Amphipoda of the Arabian Gulf", "titleType": "Subtitle"},
            ],
            "creators": [
                {
                    "name": "Al-Kandari, Manal",
                    "nameType": "Personal",
                    "givenName": "Manal",
                    "familyName": "Al-Kandari",
                    "affiliation": ["Kuwait Institute for Scientific Research"],
                },
                {
                    "name": "Kuwait Institute for Scientific Research",
                    "nameType": "Organizational",
                },
            ],
            "publisher": "Zenodo",
            "publicationYear": 2023,
            "subjects": [{"subject": "Biodiversity"}, {"subject": "Taxonomy"}],
            "types": {
                "resourceTypeGeneral": "Dataset",
                "resourceType": "Survey data",
                "schemaOrg": "Dataset",
            },
            "descriptions": [
                {
                    "description": "A regional survey of <i>amphipod</i> biodiversity "
                    "in the\nnorth-western Arabian Gulf .",
                    "descriptionType": "Abstract",
                },
                {
                    "description": "Published as part of Zootaxa 5351.",
                    "descriptionType": "Other",
                },
            ],
            "dates": [
                {"date": "2023-09-25", "dateType": "Issued"},
                {"date": "2023-09-01", "dateType": "Created"},
            ],
            "url": "https://zenodo.org/doi/10.5281/zenodo.8408173",
            "language": "en",
            "version": "1.0",
            "container": {
                "type": "Series",
                "identifier": "10.11646/zootaxa.5351.1.1",
                "identifierType": "DOI",
            },
            "relatedIdentifiers": [
                {"relationType": "IsVersionOf", "relatedIdentifier": "10.5281/zenodo.8408172"},
            ],
        },
    },
}


def make_item(**overrides):
    base = dict(
        id="crossref:10.5281/zenodo.8408173",
        source="crossref",
        source_id="10.5281/zenodo.8408173",
        url="https://doi.org/10.5281/zenodo.8408173",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_get_json(doc=DOI_DOC):
    def get_json(url):
        return json.loads(json.dumps(doc))  # deep copy

    return get_json


def fetch(doc=DOI_DOC, item=None):
    return fetch_item(item or make_item(), get_json=fake_get_json(doc))


def test_fetch_maps_core_metadata():
    fetched = fetch()

    assert fetched.title == "Global Coastal Biodiversity Survey: Amphipoda of the Arabian Gulf"
    # person creator rendered "Given Family"; org creator keeps its name
    assert fetched.author == "Manal Al-Kandari, Kuwait Institute for Scientific Research"
    assert fetched.canonical_url == "https://doi.org/10.5281/zenodo.8408173"
    assert fetched.provenance["adapter"] == "datacite"
    assert fetched.provenance["extraction_method"] == "datacite-api:json"
    # the resource type is recorded for the classifier (it can't be known
    # from the URL, so the source name can't carry it)
    assert fetched.provenance["resource_type"] == "Dataset"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_abstract_description_is_cleaned_to_plain_summary():
    summary = fetch().summary
    assert summary == "A regional survey of amphipod biodiversity in the north-western Arabian Gulf."
    assert "<i>" not in summary


def test_only_abstract_typed_description_becomes_summary():
    doc = json.loads(json.dumps(DOI_DOC))
    # drop the Abstract; leave only the Other description
    doc["data"]["attributes"]["descriptions"] = [
        {"description": "Published as part of Zootaxa 5351.", "descriptionType": "Other"}
    ]
    fetched = fetch(doc)
    assert fetched.summary is None  # an Other description is deposit context, not a summary


def test_no_descriptions_degrades_to_metadata_only():
    doc = json.loads(json.dumps(DOI_DOC))
    doc["data"]["attributes"].pop("descriptions")
    fetched = fetch(doc)
    assert fetched.summary is None
    assert fetched.title.startswith("Global Coastal Biodiversity Survey")


def test_subjects_become_concepts_like_github_topics():
    assert fetch().concepts == ("Biodiversity", "Taxonomy")


def test_no_subjects_is_honestly_empty():
    doc = json.loads(json.dumps(DOI_DOC))
    doc["data"]["attributes"].pop("subjects")
    assert fetch(doc).concepts == ()


def test_type_specific_type_and_publisher_become_tags():
    assert fetch().tags == ("Dataset", "Survey data", "Zenodo")


def test_published_at_prefers_issued_over_created():
    assert fetch().published_at == "2023-09-25T00:00:00+00:00"


def test_published_at_takes_range_start():
    doc = json.loads(json.dumps(DOI_DOC))
    doc["data"]["attributes"]["dates"] = [
        {"date": "2004-03-02/2005-06-02", "dateType": "Issued"}
    ]
    assert fetch(doc).published_at == "2004-03-02T00:00:00+00:00"


def test_published_at_falls_back_to_publication_year():
    doc = json.loads(json.dumps(DOI_DOC))
    doc["data"]["attributes"].pop("dates")
    assert fetch(doc).published_at == "2023-01-01T00:00:00+00:00"


def test_unknown_date_falls_back_to_seeded_published_at():
    doc = json.loads(json.dumps(DOI_DOC))
    doc["data"]["attributes"].pop("dates")
    doc["data"]["attributes"].pop("publicationYear")
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(doc, item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_organization_creator_uses_its_name():
    doc = json.loads(json.dumps(DOI_DOC))
    doc["data"]["attributes"]["creators"] = [
        {"name": "World Health Organization", "nameType": "Organizational"}
    ]
    assert fetch(doc).author == "World Health Organization"


def test_long_creator_list_is_truncated_with_et_al():
    doc = json.loads(json.dumps(DOI_DOC))
    doc["data"]["attributes"]["creators"] = [
        {"givenName": f"A{i}", "familyName": f"B{i}"} for i in range(25)
    ]
    author = fetch(doc).author
    assert author.endswith(", et al.")
    assert author.count(",") == 10


def test_missing_creators_leaves_author_absent():
    doc = json.loads(json.dumps(DOI_DOC))
    doc["data"]["attributes"].pop("creators")
    assert fetch(doc).author is None


def test_title_falls_back_to_doi_when_absent():
    doc = json.loads(json.dumps(DOI_DOC))
    doc["data"]["attributes"].pop("titles")
    assert fetch(doc).title == "10.5281/zenodo.8408173"


def test_subtitle_only_title_is_used():
    doc = json.loads(json.dumps(DOI_DOC))
    doc["data"]["attributes"]["titles"] = [
        {"title": "Amphipoda of the Arabian Gulf", "titleType": "Subtitle"}
    ]
    # no main title, but the subtitle is real prose — better than the DOI
    assert fetch(doc).title == "Amphipoda of the Arabian Gulf"


def test_publication_year_as_float_still_dates_the_scroll():
    doc = json.loads(json.dumps(DOI_DOC))
    doc["data"]["attributes"].pop("dates")
    doc["data"]["attributes"]["publicationYear"] = 2023.0  # some feeds JSON-type it as a float
    assert fetch(doc).published_at == "2023-01-01T00:00:00+00:00"


@pytest.mark.parametrize(
    "mangle",
    [
        lambda a: a.update(titles="not a list"),
        lambda a: a.update(titles=[{"title": 123}, "not a dict"]),
        lambda a: a.update(creators="nope"),
        lambda a: a.update(creators=["not a dict", {"givenName": None}]),
        lambda a: a.update(subjects=[{"subject": None}, "x", {}]),
        lambda a: a.update(types="not an object"),
        lambda a: a.update(types={"resourceTypeGeneral": None}),
        lambda a: a.update(descriptions="nope"),
        lambda a: a.update(descriptions=[{"description": 5, "descriptionType": "Abstract"}]),
        lambda a: a.update(dates="nope"),
        lambda a: a.update(dates=[{"date": None, "dateType": "Issued"}, "x"]),
        lambda a: a.update(publicationYear=True),  # a JSON bool, an int subclass
        lambda a: a.update(container="nope"),
        lambda a: a.update(url=None),
        lambda a: a.clear(),  # an essentially empty attributes object
    ],
)
def test_malformed_fields_never_raise(mangle):
    # A partial or garbage DataCite response must degrade, never crash the
    # batch with an unhandled KeyError/AttributeError/TypeError.
    doc = json.loads(json.dumps(DOI_DOC))
    mangle(doc["data"]["attributes"])
    fetched = fetch(doc)  # must not raise
    assert fetched.stage == "fetched"
    assert fetched.title  # always at least the DOI


def test_links_carry_landing_page_and_container_doi():
    # the landing page and the parent work's DOI (the dataset's container)
    assert fetch().links == (
        "https://zenodo.org/doi/10.5281/zenodo.8408173",
        "https://doi.org/10.11646/zootaxa.5351.1.1",
    )


def test_container_without_a_doi_identifier_is_not_linked():
    doc = json.loads(json.dumps(DOI_DOC))
    doc["data"]["attributes"]["container"] = {"type": "Journal", "title": "Some Journal"}
    assert fetch(doc).links == ("https://zenodo.org/doi/10.5281/zenodo.8408173",)


def test_landing_page_equal_to_canonical_is_dropped():
    doc = json.loads(json.dumps(DOI_DOC))
    doc["data"]["attributes"]["url"] = "https://doi.org/10.5281/zenodo.8408173"
    doc["data"]["attributes"].pop("container")
    assert fetch(doc).links == ()


def test_keeps_raw_attributes_record():
    raw = json.loads(fetch().raw_text)
    assert raw["doi"] == "10.5281/zenodo.8408173"
    assert raw["types"]["resourceTypeGeneral"] == "Dataset"


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://dx.doi.org/10.5281/zenodo.8408173")
    fetched = fetch(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id)
    assert fetched.url == item.url  # the saved URL, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_requests_the_expected_api_url():
    seen = []

    def get_json(url):
        seen.append(url)
        return json.loads(json.dumps(DOI_DOC))

    fetch_item(make_item(), get_json=get_json)
    assert seen == ["https://api.datacite.org/dois/10.5281/zenodo.8408173"]


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_a_doi(source_id):
    item = make_item(id="crossref:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine DOI"):
        fetch_item(item, get_json=fake_get_json())


def test_unregistered_doi_is_a_fetch_error():
    # a JSON:API error payload with no data.attributes
    with pytest.raises(FetchError, match="work not found"):
        fetch_item(make_item(), get_json=lambda url: {"errors": [{"status": "404"}]})


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom)


def test_doi_dispatcher_is_registered_not_the_bare_adapter():
    # `crossref` routes through the doi dispatcher, not either agency directly
    assert FETCH_ADAPTERS["crossref"] is doi_dispatch.fetch_item
