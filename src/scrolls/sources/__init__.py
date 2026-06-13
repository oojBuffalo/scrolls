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
    bitbucket,
    bluesky,
    crates,
    crossref,
    datacite,
    devto,
    discourse,
    doi,
    gitea,
    github,
    gitlab,
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
    piefed,
    pubmed,
    pypi,
    rfc,
    rubygems,
    stackexchange,
    threadiverse,
    web,
    wikipedia,
    youtube,
)

FETCH_ADAPTERS = {
    "arxiv": arxiv.fetch_item,
    # Bitbucket is the fourth code host; Bitbucket Cloud is a single hosted
    # service, so it is host-scoped with a flat `<workspace>/<repo>` identity
    # like github (not host-in-id like gitea), folded lowercase (ADR 0057).
    "bitbucket": bitbucket.fetch_item,
    "bluesky": bluesky.fetch_item,
    "crates": crates.fetch_item,
    # A `doi.org` link is detected as `crossref`, but its registration agency
    # (Crossref or DataCite) is resolved at fetch time by the doi dispatcher
    # (ADR 0045): Crossref first, DataCite fallback.
    "crossref": doi.fetch_item,
    # dev.to (Forem) articles fetch from the keyless `/api/articles/<user>/<slug>`
    # endpoint; tags become concepts so the post joins the KB concept graph a
    # `web` scrape never would (ADR 0061).
    "devto": devto.fetch_item,
    # Discourse forum software is host-less like the Fediverse sources, detected
    # by its `/t/<slug>/<id>` topic shape and fetched from that instance's
    # keyless `.json` view (ADR 0054).
    "discourse": discourse.fetch_item,
    # Gitea/Forgejo is the third code host; one adapter serves both the
    # original and its API-compatible fork (codeberg.org runs Forgejo,
    # gitea.com runs Gitea), the host riding in the id since the API lives on
    # each instance's own host (ADR 0056).
    "gitea": gitea.fetch_item,
    "github": github.fetch_item,
    # GitLab is the second major code host and the most self-hosted one, but
    # gitlab.com only here (host-scoped like github), with nested-group paths
    # URL-encoded whole (ADR 0055).
    "gitlab": gitlab.fetch_item,
    "go": go.fetch_item,
    "hackernews": hackernews.fetch_item,
    "huggingface": huggingface.fetch_item,
    # A `/post/<digits>` aggregator URL is detected as `lemmy`, but its backend
    # (Lemmy `/api/v3` or PieFed `/api/alpha` — PieFed shares the identical URL
    # shape) is resolved at fetch time by the threadiverse dispatcher (ADR 0053):
    # Lemmy first, PieFed fallback — the doi.py pattern (ADR 0045).
    "lemmy": threadiverse.fetch_item,
    "lobsters": lobsters.fetch_item,
    "mastodon": mastodon.fetch_item,
    # Misskey-family is Fediverse like mastodon but speaks its own API, so it
    # is a separate source/adapter, not a mastodon URL shape (ADR 0051).
    "misskey": misskey.fetch_item,
    "npm": npm.fetch_item,
    "packagist": packagist.fetch_item,
    "pdf": pdf.fetch_item,
    # PubMed indexes the biomedical literature, the arXiv/Crossref paper sibling;
    # MeSH descriptors become concepts and the article DOI links to its Crossref
    # scroll (the preprint↔published edge's biomedical analog, ADR 0065).
    "pubmed": pubmed.fetch_item,
    "pypi": pypi.fetch_item,
    # IETF RFCs are technical standards — a content type with no prior home;
    # keywords become concepts, the status a tag, and the RFC's DOI and its
    # obsoletes/updates relations become cross-document edges (ADR 0066).
    "rfc": rfc.fetch_item,
    "rubygems": rubygems.fetch_item,
    "stackexchange": stackexchange.fetch_item,
    "web": web.fetch_item,
    "wikipedia": wikipedia.fetch_item,
    "youtube": youtube.fetch_item,
}
