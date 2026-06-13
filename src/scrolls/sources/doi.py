"""DOI fetch dispatch: Crossref first, DataCite fallback (ADR 0037, ADR 0045).

A `doi.org/<doi>` link is detected as the `crossref` source (`detect.py`),
but a DOI's *registration agency* — Crossref for the published literature,
DataCite for datasets, software, and other repository outputs — can't be
read off the URL, and item identity (`crossref:<doi>`) is fixed at `add`
time. So which agency holds a DOI is resolved here, at fetch time: try
Crossref; if it has no such work (`FetchError`), try DataCite. The adapter
that answers records itself in `provenance.adapter`, so the source name
stays `crossref` while the truth of which agency served the metadata — and,
for DataCite, the resource type that drives classification — is honest.

This dispatcher is what `FETCH_ADAPTERS["crossref"]` points at; the two
agency adapters (`crossref.py`, `datacite.py`) stay single-purpose and are
each tested directly.
"""

from __future__ import annotations

from typing import Callable

from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources.crossref import fetch_item as _crossref_fetch
from scrolls.sources.datacite import fetch_item as _datacite_fetch

Fetch = Callable[[ScrollItem], ScrollItem]


def fetch_item(
    item: ScrollItem,
    *,
    crossref_fetch: Fetch = _crossref_fetch,
    datacite_fetch: Fetch = _datacite_fetch,
) -> ScrollItem:
    """Fetch a DOI from Crossref, falling back to DataCite.

    A Crossref-registered DOI fetches on the first try and never touches
    DataCite. A DataCite-only DOI 404s against Crossref and is served by the
    fallback. A DOI registered with neither (or a transient outage of both)
    raises a FetchError naming both failures. The agency adapters are
    injectable so the dispatch is tested without the network (ADR 0001).
    """
    try:
        return crossref_fetch(item)
    except FetchError as crossref_error:
        try:
            return datacite_fetch(item)
        except FetchError as datacite_error:
            raise FetchError(
                f"DOI {item.source_id!r} not found in Crossref ({crossref_error}) "
                f"or DataCite ({datacite_error})"
            ) from datacite_error
