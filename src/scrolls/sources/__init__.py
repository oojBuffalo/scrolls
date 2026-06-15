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
    biorxiv,
    bitbucket,
    bluesky,
    crates,
    crossref as crossref,
    datacite as datacite,
    devto,
    discourse,
    doi,
    gist,
    gitea,
    github,
    gitlab,
    go,
    hackage,
    hackernews,
    hex,
    huggingface,
    lemmy as lemmy,
    lobsters,
    mastodon,
    maven,
    misskey,
    npm,
    nuget,
    openlibrary,
    packagist,
    pdf,
    piefed as piefed,
    pub,
    pubmed,
    pypi,
    rfc,
    rubygems,
    stackexchange,
    threadiverse,
    web,
    wikidata,
    wikipedia,
    youtube,
    zenodo,
)

FETCH_ADAPTERS = {
    "arxiv": arxiv.fetch_item,
    # bioRxiv (biology) and medRxiv (health sciences) are sibling preprint
    # servers on one shared API; one adapter serves both, reading `item.source`
    # to pick the server, but they stay two sources because a medRxiv paper does
    # not live on bioRxiv. The published-journal DOI links to its Crossref
    # scroll (arXiv's preprint↔published edge, ADR 0068).
    "biorxiv": biorxiv.fetch_item,
    "medrxiv": biorxiv.fetch_item,
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
    # A gist is the developer code-snippet content type the repo adapter
    # doesn't reach; one keyless `GET /gists/<id>` returns the whole gist —
    # files inlined — and the file languages become tags (ADR 0078).
    "gist": gist.fetch_item,
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
    # Hackage is the Haskell package registry, the tenth of the family; one
    # plain GET returns the latest version's cabal manifest, whose `category`
    # becomes concepts and `description` the searchable body (ADR 0091).
    "hackage": hackage.fetch_item,
    "hackernews": hackernews.fetch_item,
    # Hex is the Elixir/Erlang package registry, pub.dev's closest twin in
    # field layout (a `meta` object of description/licenses/links); no
    # keywords so `concepts` empty by design like RubyGems/Go (ADR 0089).
    "hex": hex.fetch_item,
    "huggingface": huggingface.fetch_item,
    # A `/post/<digits>` aggregator URL is detected as `lemmy`, but its backend
    # (Lemmy `/api/v3` or PieFed `/api/alpha` — PieFed shares the identical URL
    # shape) is resolved at fetch time by the threadiverse dispatcher (ADR 0053):
    # Lemmy first, PieFed fallback — the doi.py pattern (ADR 0045).
    "lemmy": threadiverse.fetch_item,
    "lobsters": lobsters.fetch_item,
    "mastodon": mastodon.fetch_item,
    # Maven Central is the JVM package registry (Java/Kotlin/Scala/Clojure/
    # Android), the largest ecosystem the family had not reached; two plain
    # requests against the flat repository (the maven-metadata.xml version index
    # + the POM manifest, the NuGet shape), identity the coordinate
    # `groupId:artifactId` verbatim, concepts empty by design like RubyGems/Go
    # (a POM has no keyword facet), the publish date read from the index's
    # lastUpdated (ADR 0092).
    "maven": maven.fetch_item,
    # Misskey-family is Fediverse like mastodon but speaks its own API, so it
    # is a separate source/adapter, not a mastodon URL shape (ADR 0051).
    "misskey": misskey.fetch_item,
    "npm": npm.fetch_item,
    # NuGet is the .NET package registry, the ninth of the family and the one
    # major-language ecosystem it had not reached; two plain requests (the
    # flat-container version index + the nuspec manifest, the Go shape), and
    # `<tags>` become concepts so the .NET package joins the KB concept graph
    # like PyPI/pub (ADR 0090).
    "nuget": nuget.fetch_item,
    # Open Library is the keyless bibliographic catalog for books — a content
    # type with no prior home; subjects become concepts (the github-topics role)
    # so a saved book joins the KB concept graph a `web` scrape never could, and
    # an edition links to its FRBR work (the edition↔work edge, ADR 0073).
    "openlibrary": openlibrary.fetch_item,
    "packagist": packagist.fetch_item,
    "pdf": pdf.fetch_item,
    # Pub.dev is the Dart/Flutter package registry, the seventh of the
    # package family; `pubspec.topics` become concepts (the github-topics
    # role) so a saved package joins the KB concept graph, and a Flutter
    # plugin is tagged `flutter` (ADR 0088).
    "pub": pub.fetch_item,
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
    # Wikidata is the structured-knowledge sibling of Wikipedia: an entity's
    # instance-of/subclass-of types become concepts and its English sitelink links
    # to the Wikipedia article about it (the Wikidata↔Wikipedia edge, ADR 0075).
    "wikidata": wikidata.fetch_item,
    "wikipedia": wikipedia.fetch_item,
    "youtube": youtube.fetch_item,
    # Zenodo is CERN's open-science repository for datasets, software, and
    # preprints; the landing-page URL fetches the keyless InvenioRDM record and
    # its DataCite DOI links to its DOI scroll, clustering as one work
    # (the metadata-only + DOI-edge shape of DataCite, ADR 0083).
    "zenodo": zenodo.fetch_item,
}
