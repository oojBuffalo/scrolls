"""Tests for the Wikidata fetch adapter — structured knowledge (ADR 0075).

The JSON transport is faked with payloads trimmed from the real
`wikidata.org/wiki/Special:EntityData/*.json` entity records and the
`w/api.php?action=wbgetentities` label view, so the type-relations-as-concepts
resolution, the en/`mul` label fallback, the Wikidata↔Wikipedia sitelink edge,
the official-website link, the Commons image thumbnail, and the metadata-only
posture are all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.classify import classify_item
from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.wikidata import _best_text, fetch_item


def _value_claim(value):
    return {"mainsnak": {"snaktype": "value", "datavalue": {"value": value}}}


def _qid_claim(qid):
    return _value_claim({"entity-type": "item", "id": qid, "numeric-id": int(qid[1:])})


# Trimmed from https://www.wikidata.org/wiki/Special:EntityData/Q42.json (Douglas
# Adams). The English label is genuinely absent — Wikidata stores his name under
# the script-agnostic `mul` label — which exercises the en→mul title fallback.
PERSON_ENTITY = {
    "type": "item",
    "id": "Q42",
    "labels": {"mul": {"language": "mul", "value": "Douglas Adams"}},
    "descriptions": {
        "en": {
            "language": "en",
            "value": "British science fiction writer and humorist (1952–2001)",
        }
    },
    "claims": {
        "P31": [_qid_claim("Q5")],  # instance of: human
        "P18": [
            _value_claim("Douglas adams portrait.jpg"),
            _value_claim("Douglas adams portrait cropped.jpg"),  # only the first is kept
        ],
        "P856": [_value_claim("https://douglasadams.com")],  # official website
    },
    "sitelinks": {"enwiki": {"site": "enwiki", "title": "Douglas Adams", "badges": []}},
}

# Trimmed from .../Special:EntityData/Q11660.json (artificial intelligence) — a
# concept entity: an English label, and subclass-of (P279) relations that make the
# better concepts than its abstract instance-of metaclasses.
CONCEPT_ENTITY = {
    "type": "item",
    "id": "Q11660",
    "labels": {"en": {"language": "en", "value": "artificial intelligence"}},
    "descriptions": {
        "en": {"language": "en", "value": "field of computer science"}
    },
    "claims": {
        "P31": [_qid_claim("Q112057532")],
        "P279": [_qid_claim("Q21198"), _qid_claim("Q120208")],  # subclass of
    },
    "sitelinks": {
        "enwiki": {"site": "enwiki", "title": "Artificial intelligence", "badges": []}
    },
}

# The label view (wbgetentities&props=labels) for the QIDs the entities reference.
LABELS = {
    "Q5": "human",
    "Q112057532": "type of artificial system",
    "Q21198": "computer science",
    "Q120208": "formal science",
}


def fake_get_json(entity=None, labels=None):
    """A URL-routing fetcher: Special:EntityData → the entity, w/api.php → labels."""
    entity = PERSON_ENTITY if entity is None else entity
    labels = LABELS if labels is None else labels

    def get_json(url):
        if "Special:EntityData/" in url:
            return {"entities": {entity["id"]: json.loads(json.dumps(entity))}}
        if "wbgetentities" in url:
            ids = _ids_param(url)
            return {
                "entities": {
                    qid: {"labels": {"en": {"language": "en", "value": labels[qid]}}}
                    for qid in ids
                    if qid in labels
                }
            }
        raise OSError(f"unexpected url: {url}")

    return get_json


def _ids_param(url):
    from urllib.parse import parse_qs, urlparse

    raw = parse_qs(urlparse(url).query).get("ids", [""])[0]
    return [qid for qid in raw.split("|") if qid]


def make_item(**overrides):
    base = dict(
        id="wikidata:Q42",
        source="wikidata",
        source_id="Q42",
        url="https://www.wikidata.org/wiki/Q42",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def test_person_entity_records_metadata_concepts_links_and_media():
    fetched = fetch_item(make_item(), get_json=fake_get_json())

    # the English label is absent, so the title falls back to the `mul` label
    assert fetched.title == "Douglas Adams"
    # the English description is the searchable summary
    assert fetched.summary == "British science fiction writer and humorist (1952–2001)"
    # the catalog holds structured facts, not a prose body
    assert fetched.extracted_text is None
    # the instance-of type QID is resolved to its label — the whole point
    assert fetched.concepts == ("human",)
    # no facet of its own, so tags stay empty (none were seeded here)
    assert fetched.tags == ()
    # the English sitelink is the Wikidata↔Wikipedia edge; P856 is the second link
    assert fetched.links == (
        "https://en.wikipedia.org/wiki/Douglas_Adams",
        "https://douglasadams.com",
    )
    # the first P18 image becomes a Commons thumbnail (the second is skipped)
    assert fetched.media == (
        {
            "type": "thumbnail",
            "url": "https://commons.wikimedia.org/wiki/Special:FilePath/"
            "Douglas%20adams%20portrait.jpg?width=640",
        },
    )
    assert fetched.canonical_url == "https://www.wikidata.org/wiki/Q42"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.provenance["adapter"] == "wikidata"
    assert fetched.provenance["extraction_method"] == "wikidata:entitydata"
    assert fetched.stage == "fetched"


def test_concept_entity_resolves_instance_and_subclass_types_in_order():
    fetched = fetch_item(make_item(source_id="Q11660"), get_json=fake_get_json(CONCEPT_ENTITY))

    assert fetched.title == "artificial intelligence"
    # P31 value first, then the two P279 values — resolved labels, in claim order
    assert fetched.concepts == (
        "type of artificial system",
        "computer science",
        "formal science",
    )
    # only the English Wikipedia sitelink (no P856 on this entity)
    assert fetched.links == ("https://en.wikipedia.org/wiki/Artificial_intelligence",)
    # a concept with no P18 has no media
    assert fetched.media == ()


def test_concepts_dedupe_case_insensitively():
    entity = {
        **CONCEPT_ENTITY,
        "claims": {"P31": [_qid_claim("Q21198")], "P279": [_qid_claim("Q120208")]},
    }
    labels = {"Q21198": "Science", "Q120208": "science"}  # same concept, two cases
    fetched = fetch_item(
        make_item(source_id="Q11660"), get_json=fake_get_json(entity, labels)
    )
    assert fetched.concepts == ("Science",)


def test_concept_resolution_degrades_when_the_label_view_fails():
    def get_json(url):
        if "Special:EntityData/" in url:
            return {"entities": {"Q42": dict(PERSON_ENTITY)}}
        raise OSError("HTTP Error 503")  # the wbgetentities call fails

    fetched = fetch_item(make_item(), get_json=get_json)
    # the entity still fetches; concepts degrade to empty rather than failing
    assert fetched.concepts == ()
    assert fetched.title == "Douglas Adams"


def test_entity_with_no_types_makes_no_label_request():
    entity = {key: value for key, value in PERSON_ENTITY.items() if key != "claims"}
    seen = []

    def get_json(url):
        seen.append(url)
        return fake_get_json(entity)(url)

    fetched = fetch_item(make_item(), get_json=get_json)
    assert fetched.concepts == ()
    # with no type QIDs to resolve, the label view is never requested
    assert not any("wbgetentities" in url for url in seen)


def test_somevalue_type_snaks_are_skipped():
    entity = {
        **PERSON_ENTITY,
        "claims": {
            "P31": [
                {"mainsnak": {"snaktype": "somevalue"}},  # asserted-unknown, no value
                _qid_claim("Q5"),
            ]
        },
    }
    fetched = fetch_item(make_item(), get_json=fake_get_json(entity))
    assert fetched.concepts == ("human",)


def test_label_fallback_prefers_en_then_mul_then_any():
    assert _best_text({"en": {"value": "A"}, "mul": {"value": "B"}}) == "A"
    assert _best_text({"mul": {"value": "B"}, "de": {"value": "C"}}) == "B"
    assert _best_text({"en-gb": {"value": "D"}, "fr": {"value": "E"}}) == "D"
    assert _best_text({"fr": {"value": "E"}}) == "E"
    assert _best_text({}) is None
    assert _best_text(None) is None


def test_raw_text_is_a_slim_projection_not_the_whole_entity():
    bloated = {
        **PERSON_ENTITY,
        "labels": {**PERSON_ENTITY["labels"], "fr": {"value": "x"}, "de": {"value": "y"}},
        "sitelinks": {
            **PERSON_ENTITY["sitelinks"],
            "dewiki": {"site": "dewiki", "title": "x"},
            "frwiki": {"site": "frwiki", "title": "y"},
        },
        "claims": {**PERSON_ENTITY["claims"], "P569": [_value_claim("date noise")]},
    }
    raw = json.loads(fetch_item(make_item(), get_json=fake_get_json(bloated)).raw_text)
    # only en/mul labels, the four read properties, and the English sitelink survive
    assert set(raw["labels"]) == {"mul"}  # this entity has only a mul label
    assert set(raw["sitelinks"]) == {"enwiki"}
    assert set(raw["claims"]) <= {"P31", "P279", "P18", "P856"}
    assert "P569" not in raw["claims"]


def test_redirected_entity_uses_the_target_id():
    # a merged QID's data view returns the target entity under its own key
    def get_json(url):
        if "Special:EntityData/" in url:
            return {"entities": {"Q42": json.loads(json.dumps(PERSON_ENTITY))}}
        return fake_get_json()(url)

    fetched = fetch_item(make_item(source_id="Q1", id="wikidata:Q1"), get_json=get_json)
    # the canonical url follows the record's own id, not the requested one
    assert fetched.canonical_url == "https://www.wikidata.org/wiki/Q42"


def test_seeded_tags_survive_the_fetch():
    # tags an import seeded (browser-folder ancestry, ADR 0030) are not wiped — the
    # adapter has no facet of its own, so it leaves `tags` untouched
    item = make_item(tags=("reference", "people"))
    fetched = fetch_item(item, get_json=fake_get_json())
    assert fetched.tags == ("reference", "people")


def test_wikidata_entity_classifies_as_reference():
    item = make_item(title="Douglas Adams")
    assert classify_item(item).category == "reference"


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://www.wikidata.org/wiki/Q42?utm_source=x")
    fetched = fetch_item(item, get_json=fake_get_json())
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url  # the URL the user saved, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_keeps_seeded_title_when_entity_has_no_label():
    entity = {key: value for key, value in PERSON_ENTITY.items() if key != "labels"}
    item = make_item(title="Seeded Title")
    fetched = fetch_item(item, get_json=fake_get_json(entity))
    assert fetched.title == "Seeded Title"
    assert fetched.summary == "British science fiction writer and humorist (1952–2001)"


def test_requests_the_expected_urls():
    seen = []

    def get_json(url):
        seen.append(url)
        return fake_get_json()(url)

    fetch_item(make_item(), get_json=get_json)
    assert seen[0] == "https://www.wikidata.org/wiki/Special:EntityData/Q42.json"
    assert any("wbgetentities" in url and "ids=Q5" in url for url in seen)


@pytest.mark.parametrize("source_id", [None, "", "P31", "L1", "notaqid"])
def test_requires_a_q_item_id(source_id):
    item = make_item(id="wikidata:x", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine Wikidata entity"):
        fetch_item(item, get_json=fake_get_json())


def test_lowercase_source_id_is_accepted_and_canonicalized():
    fetched = fetch_item(make_item(source_id="q42"), get_json=fake_get_json())
    assert fetched.canonical_url == "https://www.wikidata.org/wiki/Q42"


def test_missing_entity_is_a_fetch_error():
    def get_json(url):
        return {"entities": {}}

    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_item(), get_json=get_json)


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 503")

    with pytest.raises(FetchError, match="request failed"):
        fetch_item(make_item(), get_json=boom)


def test_wikidata_adapter_is_registered():
    assert FETCH_ADAPTERS["wikidata"] is fetch_item
