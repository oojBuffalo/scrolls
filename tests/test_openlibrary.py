"""Tests for the Open Library fetch adapter — books (ADR 0073).

The JSON transport is faked with payloads trimmed from the real
`openlibrary.org/{works,books,isbn,authors}/*.json` records, so the
subjects-as-concepts join, the edition→work subject follow-up, the bounded
author resolution, the cover thumbnail, the date parsing, and the metadata-only
posture are all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.openlibrary import _published, fetch_item

# Trimmed from https://openlibrary.org/works/OL19932156W.json (Fluent Python).
# Subjects carry real topics, an exact case-duplicate, a call number, and two
# administrative flags — all exercised by `_clean_subjects`.
WORK_DOC = {
    "title": "Fluent Python",
    "key": "/works/OL19932156W",
    "authors": [
        {"author": {"key": "/authors/OL7584543A"}, "type": {"key": "/type/author_role"}}
    ],
    "description": {
        "type": "/type/text",
        "value": "A guide to writing effective, idiomatic Python code.\r\n\r\nFully updated.",
    },
    "subjects": [
        "Python (Computer program language)",
        "Computer programming",
        "Object-oriented programming languages",
        "Python (computer program language)",  # case-duplicate of the first
        "COMPUTERS",
        "Aa76.73.p98",  # a call number, not a topic
        "Accessible book",  # an administrative flag
        "Open Library Staff Picks",  # an administrative flag
    ],
    "covers": [-1, 10618446, 8743408],  # the -1 "no cover" sentinel is skipped
    "first_publish_date": "2015",
    "links": [
        {
            "title": "O'Reilly",
            "url": "https://www.oreilly.com/library/view/fluent-python/9781491946237/",
            "type": {"key": "/type/link"},
        }
    ],
}

# Trimmed from https://openlibrary.org/authors/OL7584543A.json
AUTHOR_DOC = {
    "name": "Luciano Ramalho",
    "key": "/authors/OL7584543A",
    "personal_name": "Ramalho, Luciano",
}

# Trimmed from https://openlibrary.org/books/OL27112900M.json — an edition with
# null subjects (they live on the work) and a flat author ref shape.
EDITION_DOC = {
    "title": "Fluent Python",
    "key": "/books/OL27112900M",
    "authors": [{"key": "/authors/OL7584543A"}],
    "works": [{"key": "/works/OL19932156W"}],
    "publishers": ["O'Reilly Media"],
    "publish_date": "Aug 20, 2015",
    "number_of_pages": 792,
    "isbn_10": ["1491946008"],
    "isbn_13": ["9781491946008"],
    "covers": [10618446, 8743408],
    "subjects": None,
    "description": None,
}

EXPECTED_CONCEPTS = (
    "Python (Computer program language)",
    "Computer programming",
    "Object-oriented programming languages",
    "COMPUTERS",
)


def fake_get_json(work=None, author=None, edition=None):
    """A URL-routing fetcher: /authors → author, /works → work, /books|/isbn → edition."""
    work = WORK_DOC if work is None else work
    author = AUTHOR_DOC if author is None else author
    edition = EDITION_DOC if edition is None else edition

    def get_json(url):
        if "/authors/" in url:
            return json.loads(json.dumps(author))
        if "/works/" in url:
            return json.loads(json.dumps(work))
        if "/books/" in url or "/isbn/" in url:
            return json.loads(json.dumps(edition))
        raise OSError(f"unexpected url: {url}")

    return get_json


def make_work(**overrides):
    base = dict(
        id="openlibrary:OL19932156W",
        source="openlibrary",
        source_id="OL19932156W",
        url="https://openlibrary.org/works/OL19932156W/Fluent_Python",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def make_edition(**overrides):
    base = dict(
        id="openlibrary:OL27112900M",
        source="openlibrary",
        source_id="OL27112900M",
        url="https://openlibrary.org/books/OL27112900M/Fluent_Python",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def make_isbn(**overrides):
    base = dict(
        id="openlibrary:isbn:9781491946008",
        source="openlibrary",
        source_id="isbn:9781491946008",
        url="https://openlibrary.org/isbn/9781491946008",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def test_work_fetch_records_metadata_and_concepts():
    fetched = fetch_item(make_work(), get_json=fake_get_json())

    assert fetched.title == "Fluent Python"
    # the author key is resolved to its name (a bounded second request)
    assert fetched.author == "Luciano Ramalho"
    # first_publish_date "2015" pads to the start of the year
    assert fetched.published_at == "2015-01-01T00:00:00+00:00"
    assert fetched.canonical_url == "https://openlibrary.org/works/OL19932156W"
    # subjects become concepts — filtered (call number + admin flags dropped) and
    # deduped case-insensitively (first spelling wins) — the whole point
    assert fetched.concepts == EXPECTED_CONCEPTS
    # a book has no clean controlled facet, so tags stay empty by design
    assert fetched.tags == ()
    # the blurb is the searchable summary, whitespace-collapsed
    assert fetched.summary == (
        "A guide to writing effective, idiomatic Python code. Fully updated."
    )
    # the catalog holds metadata, not the book's body
    assert fetched.extracted_text is None
    # the first present cover id (the -1 sentinel skipped) is the thumbnail
    assert fetched.media == (
        {"type": "thumbnail", "url": "https://covers.openlibrary.org/b/id/10618446-L.jpg"},
    )
    # a work's external links are outbound edges
    assert fetched.links == (
        "https://www.oreilly.com/library/view/fluent-python/9781491946237/",
    )
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.provenance["adapter"] == "openlibrary"
    assert fetched.provenance["extraction_method"] == "openlibrary:work"
    assert fetched.stage == "fetched"


def test_edition_follows_the_work_for_subjects_and_links_to_it():
    fetched = fetch_item(make_edition(), get_json=fake_get_json())

    assert fetched.title == "Fluent Python"
    assert fetched.author == "Luciano Ramalho"
    # the edition has null subjects, so the adapter follows its work ref for them
    assert fetched.concepts == EXPECTED_CONCEPTS
    # "Aug 20, 2015" parses to a full date
    assert fetched.published_at == "2015-08-20T00:00:00+00:00"
    # the edition canonicalizes to its /books page (OLID read back from the key)
    assert fetched.canonical_url == "https://openlibrary.org/books/OL27112900M"
    # an edition links to its FRBR work — the edition↔work edge
    assert fetched.links == ("https://openlibrary.org/works/OL19932156W",)
    assert fetched.provenance["extraction_method"] == "openlibrary:edition"


def test_isbn_routes_to_the_isbn_endpoint_and_canonicalizes_to_the_edition():
    fetched = fetch_item(make_isbn(), get_json=fake_get_json())

    assert fetched.title == "Fluent Python"
    # the /isbn record redirects to the edition, so its key gives the canonical
    assert fetched.canonical_url == "https://openlibrary.org/books/OL27112900M"
    assert fetched.concepts == EXPECTED_CONCEPTS
    assert fetched.provenance["extraction_method"] == "openlibrary:isbn"


def test_edition_uses_its_own_subjects_when_present_without_following_the_work():
    edition = {**EDITION_DOC, "subjects": ["Cooking", "Bread"]}
    seen = []

    def get_json(url):
        seen.append(url)
        if "/authors/" in url:
            return dict(AUTHOR_DOC)
        return dict(edition)

    fetched = fetch_item(make_edition(), get_json=get_json)
    assert fetched.concepts == ("Cooking", "Bread")
    # the work was never fetched (no /works/ URL requested for subjects)
    assert not any("/works/" in url for url in seen)


def test_subject_filtering_drops_admin_prefixes_and_dedupes():
    work = {
        **WORK_DOC,
        "subjects": [
            "Fiction",
            "fiction",  # case-duplicate
            "nyt:bestseller",  # an `nyt:` prefixed flag
            "Reading Level-Grade 4",  # a reading-level flag
            "In library science",  # a real subject the "In library" flag must not eat
            "Protected DAISY",
        ],
    }
    fetched = fetch_item(make_work(), get_json=fake_get_json(work=work))
    assert fetched.concepts == ("Fiction", "In library science")


def test_subjects_are_capped():
    work = {**WORK_DOC, "subjects": [f"Subject {n}" for n in range(50)]}
    fetched = fetch_item(make_work(), get_json=fake_get_json(work=work))
    assert len(fetched.concepts) == 30


def test_description_accepts_a_plain_string():
    work = {**WORK_DOC, "description": "  A short   blurb.  "}
    fetched = fetch_item(make_work(), get_json=fake_get_json(work=work))
    assert fetched.summary == "A short blurb."


def test_missing_description_has_no_summary():
    work = {key: value for key, value in WORK_DOC.items() if key != "description"}
    fetched = fetch_item(make_work(), get_json=fake_get_json(work=work))
    assert fetched.summary is None


def test_author_resolution_degrades_when_the_lookup_fails():
    def get_json(url):
        if "/authors/" in url:
            raise OSError("HTTP Error 404: Not Found")
        return dict(WORK_DOC)

    fetched = fetch_item(make_work(), get_json=get_json)
    assert fetched.author is None  # the book still fetches, byline empty


def test_many_authors_truncate_with_et_al():
    work = {
        **WORK_DOC,
        "authors": [
            {"author": {"key": f"/authors/OL{n}A"}} for n in range(12)
        ],
    }
    fetched = fetch_item(make_work(), get_json=fake_get_json(work=work))
    names = fetched.author.split(", ")
    assert names[-1] == "et al."
    assert len(names) == 11  # 10 resolved names + the et al. marker


def test_all_negative_covers_yield_no_media():
    work = {**WORK_DOC, "covers": [-1, -1]}
    fetched = fetch_item(make_work(), get_json=fake_get_json(work=work))
    assert fetched.media == ()


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Aug 20, 2015", "2015-08-20T00:00:00+00:00"),
        ("August 2015", "2015-08-01T00:00:00+00:00"),
        ("September 3, 2015", "2015-09-03T00:00:00+00:00"),
        ("Sept. 2015", "2015-09-01T00:00:00+00:00"),
        ("2015", "2015-01-01T00:00:00+00:00"),
        ("2008-09", "2008-09-01T00:00:00+00:00"),
        ("2008-09-15", "2008-09-15T00:00:00+00:00"),
        ("1999", "1999-01-01T00:00:00+00:00"),
        # a publisher/edition word that merely starts with month letters is NOT a
        # month — it degrades to the year, not a fabricated May/October/June
        ("Mayflower Press, 2016", "2016-01-01T00:00:00+00:00"),
        ("Octopus Books, 2016", "2016-01-01T00:00:00+00:00"),
        ("Junior readers, 2016", "2016-01-01T00:00:00+00:00"),
        # an impossible ISO day keeps the month, dropping only the bad day
        ("2015-02-30", "2015-02-01T00:00:00+00:00"),
        ("no date here", None),
        ("", None),
        (None, None),
    ],
)
def test_published_parses_open_library_date_dialects(raw, expected):
    assert _published(raw) == expected


def test_call_number_filter_keeps_real_subjects_with_a_trailing_digit():
    work = {
        **WORK_DOC,
        "subjects": ["U2 (Musical group)", "A1 Steak Sauce", "Pz7.d1515 Fan 2002"],
    }
    fetched = fetch_item(make_work(), get_json=fake_get_json(work=work))
    # the band and the product survive; only the dotted call number is dropped
    assert fetched.concepts == ("U2 (Musical group)", "A1 Steak Sauce")


def test_duplicate_author_keys_do_not_duplicate_the_byline():
    work = {
        **WORK_DOC,
        "authors": [
            {"author": {"key": "/authors/OL7584543A"}},
            {"author": {"key": "/authors/OL7584543A"}},  # the same contributor twice
        ],
    }
    fetched = fetch_item(make_work(), get_json=fake_get_json(work=work))
    assert fetched.author == "Luciano Ramalho"


def test_keeps_raw_record_for_rebuilds():
    raw = json.loads(fetch_item(make_work(), get_json=fake_get_json()).raw_text)
    assert raw["key"] == "/works/OL19932156W"


def test_preserves_identity_and_the_saved_url():
    item = make_work(url="https://openlibrary.org/works/OL19932156W?utm_source=x")
    fetched = fetch_item(item, get_json=fake_get_json())
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url  # the URL the user saved, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_keeps_seeded_published_at_when_record_has_no_date():
    work = {key: value for key, value in WORK_DOC.items() if key != "first_publish_date"}
    item = make_work(published_at="2020-01-01T00:00:00+00:00")
    fetched = fetch_item(item, get_json=fake_get_json(work=work))
    assert fetched.published_at == "2020-01-01T00:00:00+00:00"


def test_requests_the_expected_urls_for_a_work():
    seen = []

    def get_json(url):
        seen.append(url)
        return fake_get_json()(url)

    fetch_item(make_work(), get_json=get_json)
    assert seen == [
        "https://openlibrary.org/works/OL19932156W.json",
        "https://openlibrary.org/authors/OL7584543A.json",
    ]


def test_requests_the_expected_urls_for_an_edition():
    seen = []

    def get_json(url):
        seen.append(url)
        return fake_get_json()(url)

    fetch_item(make_edition(), get_json=get_json)
    # the edition record, the work followed for its subjects, then the author
    assert seen == [
        "https://openlibrary.org/books/OL27112900M.json",
        "https://openlibrary.org/works/OL19932156W.json",
        "https://openlibrary.org/authors/OL7584543A.json",
    ]


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_a_source_id(source_id):
    item = make_work(id="openlibrary:x", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine Open Library book"):
        fetch_item(item, get_json=fake_get_json())


def test_unrecognized_id_is_a_fetch_error():
    item = make_work(id="openlibrary:OL1A", source_id="OL1A")  # an author OLID
    with pytest.raises(FetchError, match="unrecognized Open Library id"):
        fetch_item(item, get_json=fake_get_json())


def test_missing_record_is_a_fetch_error():
    def get_json(url):
        return {"error": "notfound"}

    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_work(), get_json=get_json)


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 503")

    with pytest.raises(FetchError, match="request failed"):
        fetch_item(make_work(), get_json=boom)


def test_openlibrary_adapter_is_registered():
    assert FETCH_ADAPTERS["openlibrary"] is fetch_item
