"""Tests for the generic DOI content-negotiation fetch adapter (ADR 0081).

The third tier of the `sources/doi.py` dispatcher: when both Crossref and
DataCite 404 a DOI, a `doi.org` GET asking for `application/vnd.citationstyles
.csl+json` reaches whichever long-tail agency (JaLC, mEDRA, KISTI, OP, …) holds
it and returns a uniform CSL-JSON document. The JSON transport is faked with a
CSL-JSON document whose shape matches the spec and the live resolver, so the
field mapping, the resource-type → category signal, abstract cleaning, author
formatting, the CSL date precedence, type/venue tagging, the landing link, the
content-type negotiation, and error handling are all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.classify import classify_item
from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS
from scrolls.sources import doi as doi_dispatch
from scrolls.sources import http
from scrolls.sources.csl import CSL_ACCEPT, fetch_item

# A JaLC journal article, the CSL-JSON shape a `doi.org` content-negotiation
# GET returns: a string `title` + `subtitle`, two person authors plus an
# institutional `literal` author, an `issued` date that must win over a later
# `created`, a JATS abstract led by an "Abstract" label, `subject` keywords, a
# `container-title` venue, and a landing `URL`.
ARTICLE_CSL = {
    "type": "article-journal",
    "DOI": "10.20965/jrm.2020.p0001",
    "title": "Autonomous Navigation for Mobile Robots",
    "subtitle": "A Survey of Recent Methods",
    "author": [
        {"given": "Hiroshi", "family": "Tanaka"},
        {"given": "Yuki", "family": "Sato"},
        {"literal": "Robotics Society of Japan"},
    ],
    "container-title": "Journal of Robotics and Mechatronics",
    "publisher": "Fuji Technology Press Ltd.",
    "issued": {"date-parts": [[2020, 2, 20]]},
    "created": {"date-parts": [[2021, 1, 1]]},
    "abstract": "<jats:title>Abstract</jats:title><jats:p>We present a "
    "navigation method for <jats:italic>mobile</jats:italic> robots .</jats:p>",
    "subject": ["Robotics", "Control Systems"],
    "URL": "https://www.fujipress.jp/jrm/rb/robot003200010001/",
    "volume": "32",
    "issue": "1",
    "reference": [{"DOI": "10.1000/cited"}],  # dropped from raw_text, never a link
}


def make_item(doi="10.20965/jrm.2020.p0001"):
    return ScrollItem(
        id=f"crossref:{doi}",
        source="crossref",
        source_id=doi,
        url=f"https://doi.org/{doi}",
        saved_at="2026-06-13T00:00:00+00:00",
    )


def fake_get_json(payload, capture=None):
    def get_json(url):
        if capture is not None:
            capture.append(url)
        return payload

    return get_json


def test_article_maps_every_field():
    item = fetch_item(make_item(), get_json=fake_get_json(ARTICLE_CSL))
    assert item.stage == "fetched"
    assert item.title == "Autonomous Navigation for Mobile Robots: A Survey of Recent Methods"
    assert item.author == "Hiroshi Tanaka, Yuki Sato, Robotics Society of Japan"
    assert item.canonical_url == "https://doi.org/10.20965/jrm.2020.p0001"
    # issued (2020) wins over created (2021), padded to midnight UTC.
    assert item.published_at == "2020-02-20T00:00:00+00:00"
    # JATS stripped, entities handled, inline-tag space before "." removed,
    # the leading "Abstract" label dropped.
    assert item.summary == "We present a navigation method for mobile robots."
    assert item.concepts == ("Robotics", "Control Systems")
    assert "article-journal" in item.tags
    assert "Journal of Robotics and Mechatronics" in item.tags
    assert item.links == ("https://www.fujipress.jp/jrm/rb/robot003200010001/",)
    assert item.provenance["adapter"] == "content-negotiation"
    assert item.provenance["resource_type"] == "article-journal"
    assert item.content_hash.startswith("sha256:")


def test_reference_array_dropped_from_raw_text():
    item = fetch_item(make_item(), get_json=fake_get_json(ARTICLE_CSL))
    raw = json.loads(item.raw_text)
    assert "reference" not in raw  # bounded raw_text, like Crossref (ADR 0037)
    assert raw["DOI"] == "10.20965/jrm.2020.p0001"


def test_default_transport_negotiates_csl_json(monkeypatch):
    seen = {}

    def fake_http_get_json(url, headers=None):
        seen["url"] = url
        seen["headers"] = headers
        return ARTICLE_CSL

    monkeypatch.setattr(http, "get_json", fake_http_get_json)
    item = fetch_item(make_item())  # no injected get_json → the live transport
    assert seen["url"] == "https://doi.org/10.20965/jrm.2020.p0001"
    assert seen["headers"] == {"Accept": CSL_ACCEPT}
    assert item.title.startswith("Autonomous Navigation")


def test_doi_is_folded_lowercase_in_the_canonical_url():
    upper = {"type": "article-journal", "DOI": "10.20965/JRM.2020.P0001", "title": "T"}
    item = fetch_item(make_item(), get_json=fake_get_json(upper))
    assert item.canonical_url == "https://doi.org/10.20965/jrm.2020.p0001"


def test_title_tolerates_a_single_element_array():
    # CSL carries strings, but Crossref's CSL output (and some feeds) wrap them
    # in arrays; both collapse to one title.
    payload = {
        "type": "article-journal",
        "DOI": "10.1/x",
        "title": ["Wrapped Title"],
        "container-title": ["Some Journal"],
    }
    item = fetch_item(make_item("10.1/x"), get_json=fake_get_json(payload))
    assert item.title == "Wrapped Title"
    assert "Some Journal" in item.tags


def test_author_with_only_a_family_name():
    payload = {"type": "article-journal", "DOI": "10.1/x", "title": "T",
               "author": [{"family": "Plato"}]}
    item = fetch_item(make_item("10.1/x"), get_json=fake_get_json(payload))
    assert item.author == "Plato"


def test_author_list_truncated_with_et_al():
    payload = {
        "type": "article-journal",
        "DOI": "10.1/x",
        "title": "T",
        "author": [{"family": f"A{n}"} for n in range(15)],
    }
    item = fetch_item(make_item("10.1/x"), get_json=fake_get_json(payload))
    assert item.author.endswith("et al.")
    assert item.author.count(",") == 10  # 10 names + the trailing "et al."


def test_date_from_raw_string_when_no_date_parts():
    payload = {
        "type": "article-journal",
        "DOI": "10.1/x",
        "title": "T",
        "issued": {"raw": "2019-07-04"},
    }
    item = fetch_item(make_item("10.1/x"), get_json=fake_get_json(payload))
    assert item.published_at == "2019-07-04T00:00:00+00:00"


# A real JaLC record (NDL DOI 10.11501/3158788), the headline third-tier case:
# JaLC's CSL-JSON omits `type` entirely and carries no abstract/subject, and a
# single-field non-Latin name lands in `given` with no `family`. Captured live
# from `https://doi.org/10.11501/3158788` content negotiation.
JALC_CSL = {
    "DOI": "10.11501/3158788",
    "URL": "https://dl.ndl.go.jp/info:ndljp/pid/3158788",
    "author": [{"given": "林, 志宏"}],
    "issued": {"date-parts": [[1998, 3, 23]]},
    "publisher": "Kyoto University",
    "title": "Phylogenetical analysis of animal species in Artiodactyla",
}


def test_jalc_record_without_a_type_field_is_an_honest_paper():
    # The common JaLC shape: no `type`, no abstract, no subject. It must still
    # produce a clean scroll (DOI + title pass the CSL check) and classify as a
    # paper by the scholarly default, with honestly empty tags/concepts/summary.
    item = fetch_item(make_item("10.11501/3158788"), get_json=fake_get_json(JALC_CSL))
    assert item.title == "Phylogenetical analysis of animal species in Artiodactyla"
    assert item.author == "林, 志宏"  # whole name in `given`, no `family`
    assert item.published_at == "1998-03-23T00:00:00+00:00"
    assert item.tags == ()  # no type, no container-title
    assert item.concepts == ()
    assert item.summary is None
    assert item.provenance["resource_type"] == ""  # absent type → empty, not a crash
    assert classify_item(item).category == "paper"


def test_metadata_only_record_has_no_summary_or_concepts():
    payload = {"type": "article-journal", "DOI": "10.1/x", "title": "Bare Record"}
    item = fetch_item(make_item("10.1/x"), get_json=fake_get_json(payload))
    assert item.title == "Bare Record"
    assert item.summary is None
    assert item.concepts == ()
    assert item.links == ()
    assert item.stage == "fetched"


def test_title_falls_back_to_venue_then_doi():
    venue = {"type": "article-journal", "DOI": "10.1/x", "container-title": "Nature"}
    assert fetch_item(make_item("10.1/x"), get_json=fake_get_json(venue)).title == "Nature"
    bare = {"type": "dataset", "DOI": "10.1/y"}
    assert fetch_item(make_item("10.1/y"), get_json=fake_get_json(bare)).title == "10.1/y"


def test_landing_url_equal_to_canonical_is_not_a_link():
    payload = {
        "type": "article-journal",
        "DOI": "10.1/x",
        "title": "T",
        "URL": "https://doi.org/10.1/x",
    }
    item = fetch_item(make_item("10.1/x"), get_json=fake_get_json(payload))
    assert item.links == ()  # the canonical doi.org link is not duplicated


def test_missing_source_id_raises():
    item = ScrollItem(
        id="crossref:", source="crossref", source_id=None,
        url="https://doi.org/", saved_at="2026-06-13T00:00:00+00:00",
    )
    with pytest.raises(doi_dispatch.FetchError):
        fetch_item(item, get_json=fake_get_json(ARTICLE_CSL))


def test_request_failure_raises_fetch_error():
    def boom(url):
        raise OSError("404 Not Found")

    with pytest.raises(doi_dispatch.FetchError):
        fetch_item(make_item(), get_json=boom)


def test_non_csl_response_raises_rather_than_minting_a_scroll():
    # An HTML error page or unrelated JSON that parsed but carries none of the
    # CSL marks — a misroute must degrade to a failed fetch, never a wrong scroll.
    with pytest.raises(doi_dispatch.FetchError):
        fetch_item(make_item(), get_json=fake_get_json({"message": "Not Found"}))


def test_content_negotiated_paper_classifies_as_paper():
    item = fetch_item(make_item(), get_json=fake_get_json(ARTICLE_CSL))
    assert classify_item(item).category == "paper"


def test_content_negotiated_dataset_classifies_as_dataset():
    payload = {"type": "dataset", "DOI": "10.1/d", "title": "A Data Set"}
    item = fetch_item(make_item("10.1/d"), get_json=fake_get_json(payload))
    assert classify_item(item).category == "dataset"


def test_content_negotiated_software_classifies_as_tool():
    payload = {"type": "software", "DOI": "10.1/s", "title": "A Program"}
    item = fetch_item(make_item("10.1/s"), get_json=fake_get_json(payload))
    assert classify_item(item).category == "tool"


def test_registered_through_the_doi_dispatcher():
    # The adapter is reached only via the dispatcher (the third tier), never
    # registered directly in FETCH_ADAPTERS.
    assert FETCH_ADAPTERS["crossref"] is doi_dispatch.fetch_item
    assert doi_dispatch._csl_fetch is fetch_item
