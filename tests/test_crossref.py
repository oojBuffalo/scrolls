"""Tests for the Crossref / DOI fetch adapter (IDEAS.md §6, ADR 0037).

The JSON transport is faked with a work document recorded (and trimmed)
from the real Crossref REST API, so the field mapping, JATS abstract
cleaning, author formatting and truncation, the Crossref date precedence,
the venue/type tagging, and error handling are all covered offline
(ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.crossref import fetch_item

# Recorded (and trimmed) from
# https://api.crossref.org/works/10.1145/2939672.2939754 (node2vec, KDD 2016).
WORK_DOC = {
    "status": "ok",
    "message-type": "work",
    "message": {
        "DOI": "10.1145/2939672.2939754",
        "type": "proceedings-article",
        "title": ["node2vec"],
        "subtitle": ["Scalable Feature Learning for Networks"],
        "author": [
            {"given": "Aditya", "family": "Grover", "sequence": "first"},
            {"given": "Jure", "family": "Leskovec", "sequence": "additional"},
        ],
        "container-title": ["Proceedings of the 22nd ACM SIGKDD International "
                            "Conference on Knowledge Discovery and Data Mining"],
        "publisher": "ACM",
        "subject": ["Machine Learning", "Data Mining"],
        "abstract": "<jats:title>Abstract</jats:title><jats:p>Prediction tasks "
        "over nodes and edges in networks require careful effort in "
        "engineering features. We propose <jats:italic>node2vec</jats:italic>, "
        "a framework for learning continuous feature representations.</jats:p>",
        "issued": {"date-parts": [[2016, 8, 13]]},
        "published": {"date-parts": [[2016, 8, 13]]},
        "created": {"date-time": "2016-07-25T12:34:56Z", "date-parts": [[2016, 7, 25]]},
        "URL": "https://doi.org/10.1145/2939672.2939754",
        "resource": {"primary": {"URL": "https://dl.acm.org/doi/10.1145/2939672.2939754"}},
        "reference": [{"key": "ref1", "DOI": "10.5555/somewhere"}],
        "is-referenced-by-count": 4242,
    },
}


def make_item(**overrides):
    base = dict(
        id="crossref:10.1145/2939672.2939754",
        source="crossref",
        source_id="10.1145/2939672.2939754",
        url="https://doi.org/10.1145/2939672.2939754",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_get_json(doc=WORK_DOC):
    def get_json(url):
        return json.loads(json.dumps(doc))  # deep copy

    return get_json


def fetch(doc=WORK_DOC, item=None):
    return fetch_item(item or make_item(), get_json=fake_get_json(doc))


def test_fetch_maps_core_metadata():
    fetched = fetch()

    # title and subtitle are joined
    assert fetched.title == "node2vec: Scalable Feature Learning for Networks"
    assert fetched.author == "Aditya Grover, Jure Leskovec"
    # canonical url is built from the response's DOI (folded id never breaks it)
    assert fetched.canonical_url == "https://doi.org/10.1145/2939672.2939754"
    assert fetched.provenance["adapter"] == "crossref"
    assert fetched.provenance["extraction_method"] == "crossref-api:json"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_jats_abstract_is_cleaned_to_plain_summary():
    summary = fetch().summary
    # the JATS tags and leading "Abstract" label are gone, entities collapsed
    assert summary.startswith("Prediction tasks over nodes and edges")
    assert "<jats:" not in summary
    assert "node2vec, a framework" in summary  # inline <jats:italic> unwrapped


def test_no_abstract_degrades_to_metadata_only():
    doc = json.loads(json.dumps(WORK_DOC))
    doc["message"].pop("abstract")
    fetched = fetch(doc)
    assert fetched.summary is None
    # still a useful scroll: title, authors, venue, date
    assert fetched.title.startswith("node2vec")


def test_subjects_become_concepts_like_github_topics():
    assert fetch().concepts == ("Machine Learning", "Data Mining")


def test_no_subjects_is_honestly_empty():
    # Crossref largely stopped collecting subjects — empty, not guessed
    doc = json.loads(json.dumps(WORK_DOC))
    doc["message"].pop("subject")
    assert fetch(doc).concepts == ()


def test_type_and_venue_become_tags():
    assert fetch().tags == (
        "proceedings-article",
        "Proceedings of the 22nd ACM SIGKDD International "
        "Conference on Knowledge Discovery and Data Mining",
    )


def test_links_carry_only_the_publisher_landing_page():
    # the doi.org URL is the canonical link, not an outgoing one; cited DOIs
    # in `reference` are deliberately not turned into links
    assert fetch().links == ("https://dl.acm.org/doi/10.1145/2939672.2939754",)


def test_landing_page_equal_to_canonical_is_dropped():
    doc = json.loads(json.dumps(WORK_DOC))
    doc["message"]["resource"]["primary"]["URL"] = "https://doi.org/10.1145/2939672.2939754"
    assert fetch(doc).links == ()


def test_published_at_prefers_issued_date():
    # issued [2016, 8, 13] wins over created's full timestamp
    assert fetch().published_at == "2016-08-13T00:00:00+00:00"


def test_published_at_falls_back_to_created_timestamp():
    doc = json.loads(json.dumps(WORK_DOC))
    for key in ("issued", "published", "published-online", "published-print"):
        doc["message"].pop(key, None)
    # created carries a full date-time, used verbatim
    assert fetch(doc).published_at == "2016-07-25T12:34:56+00:00"


def test_partial_date_parts_pads_to_first_of_period():
    doc = json.loads(json.dumps(WORK_DOC))
    doc["message"]["issued"] = {"date-parts": [[2016]]}  # year only
    assert fetch(doc).published_at == "2016-01-01T00:00:00+00:00"


def test_unknown_date_falls_back_to_seeded_published_at():
    doc = json.loads(json.dumps(WORK_DOC))
    for key in ("issued", "published", "published-online", "published-print", "created"):
        doc["message"].pop(key, None)
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(doc, item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_organization_author_uses_its_name():
    doc = json.loads(json.dumps(WORK_DOC))
    doc["message"]["author"] = [{"name": "World Health Organization"}]
    assert fetch(doc).author == "World Health Organization"


def test_long_author_list_is_truncated_with_et_al():
    doc = json.loads(json.dumps(WORK_DOC))
    doc["message"]["author"] = [
        {"given": f"A{i}", "family": f"B{i}"} for i in range(25)
    ]
    author = fetch(doc).author
    assert author.endswith(", et al.")
    assert author.count(",") == 10  # 10 names + the trailing "et al." marker


def test_missing_authors_leaves_author_absent():
    doc = json.loads(json.dumps(WORK_DOC))
    doc["message"].pop("author")
    assert fetch(doc).author is None


def test_title_falls_back_to_doi_when_absent():
    doc = json.loads(json.dumps(WORK_DOC))
    doc["message"].pop("title")
    doc["message"].pop("subtitle")
    doc["message"].pop("container-title")
    assert fetch(doc).title == "10.1145/2939672.2939754"


def test_keeps_raw_records_without_the_reference_list():
    raw = json.loads(fetch().raw_text)
    assert raw["DOI"] == "10.1145/2939672.2939754"
    assert raw["type"] == "proceedings-article"
    # the (potentially huge) reference list is dropped to bound raw_text size
    assert "reference" not in raw


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://dx.doi.org/10.1145/2939672.2939754")
    fetched = fetch(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id)
    assert fetched.url == item.url  # the saved URL, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_requests_the_expected_api_url():
    seen = []

    def get_json(url):
        seen.append(url)
        return json.loads(json.dumps(WORK_DOC))

    fetch_item(make_item(), get_json=get_json)
    assert seen == ["https://api.crossref.org/works/10.1145/2939672.2939754"]


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_a_doi(source_id):
    item = make_item(id="crossref:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine DOI"):
        fetch_item(item, get_json=fake_get_json())


def test_unregistered_doi_is_a_fetch_error():
    # a malformed response with no ok status / message
    with pytest.raises(FetchError, match="work not found"):
        fetch_item(make_item(), get_json=lambda url: {"status": "error"})


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_item(), get_json=boom)


def test_crossref_adapter_is_registered():
    assert FETCH_ADAPTERS["crossref"] is fetch_item
