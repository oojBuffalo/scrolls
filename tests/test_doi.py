"""Tests for the DOI fetch dispatcher (ADR 0045, ADR 0081).

A `doi.org` link is detected as the `crossref` source, but which agency
holds the DOI — Crossref, DataCite, or one of the long-tail agencies reached
by content negotiation — is resolved at fetch time in a three-tier cascade:
Crossref first, DataCite second, content negotiation last. The agency
adapters are injected so the dispatch logic is exercised without the network
(ADR 0001).
"""

from dataclasses import replace

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.doi import fetch_item


def make_item():
    return ScrollItem(
        id="crossref:10.5281/zenodo.8408173",
        source="crossref",
        source_id="10.5281/zenodo.8408173",
        url="https://doi.org/10.5281/zenodo.8408173",
        saved_at="2026-06-13T00:00:00+00:00",
    )


def stub(label, error=None):
    """A fake agency fetch: tags the item with `label`, or raises FetchError."""
    calls = []

    def fetch(item):
        calls.append(item)
        if error is not None:
            raise FetchError(error)
        return replace(item, title=label, stage="fetched")

    fetch.calls = calls
    return fetch


def dispatch(item, crossref, datacite, csl):
    return fetch_item(
        item, crossref_fetch=crossref, datacite_fetch=datacite, csl_fetch=csl
    )


def test_crossref_hit_never_touches_the_fallbacks():
    crossref = stub("from crossref")
    datacite = stub("from datacite")
    csl = stub("from content negotiation")
    fetched = dispatch(make_item(), crossref, datacite, csl)
    assert fetched.title == "from crossref"
    assert len(crossref.calls) == 1
    assert datacite.calls == []  # Crossref answered, so the fallbacks are never asked
    assert csl.calls == []


def test_crossref_miss_falls_back_to_datacite_not_content_negotiation():
    crossref = stub("", error="work not found: 10.5281/zenodo.8408173")
    datacite = stub("from datacite")
    csl = stub("from content negotiation")
    fetched = dispatch(make_item(), crossref, datacite, csl)
    assert fetched.title == "from datacite"
    assert len(crossref.calls) == 1
    assert len(datacite.calls) == 1
    assert csl.calls == []  # DataCite answered, so content negotiation is skipped


def test_both_agencies_miss_falls_back_to_content_negotiation():
    crossref = stub("", error="work not found")
    datacite = stub("", error="work not found")
    csl = stub("from content negotiation")
    fetched = dispatch(make_item(), crossref, datacite, csl)
    assert fetched.title == "from content negotiation"
    assert len(crossref.calls) == 1
    assert len(datacite.calls) == 1
    assert len(csl.calls) == 1


def test_no_agency_holds_the_doi_raises_naming_all_three():
    crossref = stub("", error="crossref says no")
    datacite = stub("", error="datacite says no")
    csl = stub("", error="content negotiation says no")
    with pytest.raises(FetchError) as excinfo:
        dispatch(make_item(), crossref, datacite, csl)
    message = str(excinfo.value)
    assert "Crossref" in message and "DataCite" in message
    assert "content negotiation" in message
    assert "10.5281/zenodo.8408173" in message


def test_real_dispatcher_is_registered_for_crossref():
    assert FETCH_ADAPTERS["crossref"] is fetch_item
