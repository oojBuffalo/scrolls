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
    bluesky,
    crates,
    crossref,
    datacite,
    doi,
    github,
    go,
    hackernews,
    huggingface,
    lemmy,
    lobsters,
    mastodon,
    misskey,
    npm,
    packagist,
    pdf,
    pypi,
    rubygems,
    stackexchange,
    web,
    wikipedia,
    youtube,
)

FETCH_ADAPTERS = {
    "arxiv": arxiv.fetch_item,
    "bluesky": bluesky.fetch_item,
    "crates": crates.fetch_item,
    # A `doi.org` link is detected as `crossref`, but its registration agency
    # (Crossref or DataCite) is resolved at fetch time by the doi dispatcher
    # (ADR 0045): Crossref first, DataCite fallback.
    "crossref": doi.fetch_item,
    "github": github.fetch_item,
    "go": go.fetch_item,
    "hackernews": hackernews.fetch_item,
    "huggingface": huggingface.fetch_item,
    # Lemmy is the federated link aggregator: Fediverse like mastodon but with
    # its own `/api/v3` API, so a separate source/adapter (ADR 0052).
    "lemmy": lemmy.fetch_item,
    "lobsters": lobsters.fetch_item,
    "mastodon": mastodon.fetch_item,
    # Misskey-family is Fediverse like mastodon but speaks its own API, so it
    # is a separate source/adapter, not a mastodon URL shape (ADR 0051).
    "misskey": misskey.fetch_item,
    "npm": npm.fetch_item,
    "packagist": packagist.fetch_item,
    "pdf": pdf.fetch_item,
    "pypi": pypi.fetch_item,
    "rubygems": rubygems.fetch_item,
    "stackexchange": stackexchange.fetch_item,
    "web": web.fetch_item,
    "wikipedia": wikipedia.fetch_item,
    "youtube": youtube.fetch_item,
}
