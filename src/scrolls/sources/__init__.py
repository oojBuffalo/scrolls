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
from scrolls.sources import (  # noqa: E402
    arxiv,
    crates,
    github,
    hackernews,
    npm,
    pdf,
    pypi,
    stackexchange,
    web,
    wikipedia,
    youtube,
)

FETCH_ADAPTERS = {
    "arxiv": arxiv.fetch_item,
    "crates": crates.fetch_item,
    "github": github.fetch_item,
    "hackernews": hackernews.fetch_item,
    "npm": npm.fetch_item,
    "pdf": pdf.fetch_item,
    "pypi": pypi.fetch_item,
    "stackexchange": stackexchange.fetch_item,
    "web": web.fetch_item,
    "wikipedia": wikipedia.fetch_item,
    "youtube": youtube.fetch_item,
}
