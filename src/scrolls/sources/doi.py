"""DOI fetch dispatch: Crossref, DataCite, then content negotiation
(ADR 0037, ADR 0045, ADR 0081).

A `doi.org/<doi>` link is detected as the `crossref` source (`detect.py`),
but a DOI's *registration agency* — Crossref for the published literature,
DataCite for datasets, software, and other repository outputs, and a dozen
more for the long tail (JaLC, mEDRA, KISTI, OP, …) — can't be read off the
URL, and item identity (`crossref:<doi>`) is fixed at `add` time. So which
agency holds a DOI is resolved here, at fetch time, in a three-tier cascade:

1. **Crossref** — the published scholarly literature (the common case).
2. **DataCite** — datasets, software, and other repository outputs, when
   Crossref 404s the DOI.
3. **Content negotiation** — the agency-agnostic fallback (`csl.py`): a
   `doi.org` GET asking for CSL-JSON reaches *every* remaining agency at
   once, when both Crossref and DataCite 404 the DOI. This catches the long
   tail (JaLC, mEDRA, …) without a bespoke adapter per agency.

The adapter that answers records itself in `provenance.adapter`, so the
source name stays `crossref` while the truth of which agency served the
metadata — and, for DataCite and content negotiation, the resource type that
drives classification — is honest.

This dispatcher is what `FETCH_ADAPTERS["crossref"]` points at; the three
adapters (`crossref.py`, `datacite.py`, `csl.py`) stay single-purpose and are
each tested directly.
"""

from __future__ import annotations

from typing import Callable

from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources.crossref import fetch_item as _crossref_fetch
from scrolls.sources.csl import fetch_item as _csl_fetch
from scrolls.sources.datacite import fetch_item as _datacite_fetch

Fetch = Callable[[ScrollItem], ScrollItem]


def fetch_item(
    item: ScrollItem,
    *,
    crossref_fetch: Fetch = _crossref_fetch,
    datacite_fetch: Fetch = _datacite_fetch,
    csl_fetch: Fetch = _csl_fetch,
) -> ScrollItem:
    """Fetch a DOI from Crossref, then DataCite, then content negotiation.

    A Crossref-registered DOI fetches on the first try and never touches the
    fallbacks. A DataCite-only DOI 404s against Crossref and is served by
    DataCite. A DOI held by any other agency (JaLC, mEDRA, …) 404s against
    both and is served by content negotiation. A DOI registered with none (or
    a transient outage of all three) raises a FetchError naming every failure.
    The adapters are injectable so the dispatch is tested without the network
    (ADR 0001).
    """
    try:
        return crossref_fetch(item)
    except FetchError as crossref_error:
        try:
            return datacite_fetch(item)
        except FetchError as datacite_error:
            try:
                return csl_fetch(item)
            except FetchError as csl_error:
                raise FetchError(
                    f"DOI {item.source_id!r} not found in Crossref "
                    f"({crossref_error}), DataCite ({datacite_error}), or via "
                    f"content negotiation ({csl_error})"
                ) from csl_error
