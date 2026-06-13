"""Link-aggregator fetch dispatch: Lemmy first, PieFed fallback (ADR 0052, 0053).

A `/post/<digits>` link-aggregator URL is detected as the `lemmy` source
(`detect.py`), but the *backend* serving it — Lemmy's `/api/v3` or PieFed's
`/api/alpha` — can't be read off the URL: PieFed posts have the byte-identical
`https://<instance>/post/<id>` shape (autoincrement integer ids), so detection
can't tell them apart, and item identity (`lemmy:<host>/<post_id>`) is fixed at
`add` time. So which API holds a post is resolved here, at fetch time — the same
move the `doi.py` dispatcher makes for Crossref vs DataCite (ADR 0045): try
Lemmy; if it has no such post (`FetchError`), try PieFed. The adapter that
answers records itself in `provenance.adapter`, so the source name stays `lemmy`
while the truth of which implementation served the post is honest.

Lemmy is tried first because it is by far the more widely deployed of the two, so
the common case pays no extra request and only a PieFed post spends a wasted
`/api/v3` GET (which 404s) before its real `/api/alpha` fetch — DataCite's
one-extra-request tax (ADR 0045). "Threadiverse" is the established community name
for this Reddit-like corner of the Fediverse (Lemmy, PieFed, Mbin, …), so it names
the dispatcher the way `doi` names the Crossref/DataCite one — after the shared
scheme, not either implementation.

This dispatcher is what `FETCH_ADAPTERS["lemmy"]` points at; the two
implementation adapters (`lemmy.py`, `piefed.py`) stay single-purpose and are
each tested directly.
"""

from __future__ import annotations

from typing import Callable

from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources.lemmy import fetch_item as _lemmy_fetch
from scrolls.sources.piefed import fetch_item as _piefed_fetch

Fetch = Callable[[ScrollItem], ScrollItem]


def fetch_item(
    item: ScrollItem,
    *,
    lemmy_fetch: Fetch = _lemmy_fetch,
    piefed_fetch: Fetch = _piefed_fetch,
) -> ScrollItem:
    """Fetch a link-aggregator post from Lemmy, falling back to PieFed.

    A Lemmy instance serves the post on the first try and never touches PieFed.
    A PieFed instance 404s the Lemmy `/api/v3` call (it implements only
    `/api/alpha`), so the fallback serves it. A `/post/<digits>` URL that is
    neither (a transient outage, or a misdetected non-aggregator URL) raises a
    FetchError naming both failures. The implementation adapters are injectable so
    the dispatch is tested without the network (ADR 0001).
    """
    try:
        return lemmy_fetch(item)
    except FetchError as lemmy_error:
        try:
            return piefed_fetch(item)
        except FetchError as piefed_error:
            raise FetchError(
                f"post {item.source_id!r} not served by Lemmy ({lemmy_error}) "
                f"or PieFed ({piefed_error})"
            ) from piefed_error
