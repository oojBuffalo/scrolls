"""Source adapters: each platform becomes the same kind of scroll.

A fetch adapter is a function `ScrollItem -> ScrollItem` that fills in
content for a detected item and moves it to stage 'fetched', raising
FetchError on any failure (ADR 0002). `FETCH_ADAPTERS` maps source names
(as produced by `detect.detect_source`) to their adapter; sources without
an entry are registered by `scrolls add` but skipped by `scrolls fetch`
until their adapter lands.
"""

from __future__ import annotations


class FetchError(Exception):
    """A source adapter could not fetch or normalize an item."""


# Imported below the FetchError definition because adapter modules import it
# back from this package.
from scrolls.sources import wikipedia  # noqa: E402

FETCH_ADAPTERS = {
    "wikipedia": wikipedia.fetch_item,
}
