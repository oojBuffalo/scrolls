"""Rules classification engine (IDEAS.md §8, ADR 0004).

Layer one of "regex/rules first → optional LLM second → user overrides
always win": a deterministic category from signals that don't need a
model — which platform the item came from, how its title reads, and what
its URL looks like. Items nothing matches stay unclassified rather than
getting a guessed label; a future LLM engine can pick them up.

Precedence (first hit wins):

1. curated-platform defaults — wikipedia/wikidata/rfc/arxiv/biorxiv/medrxiv/pubmed/
   crossref/github/gitlab/gitea/bitbucket/pypi/npm/crates/packagist/rubygems/go/
   huggingface items are what their platform makes them, whatever the title says;
2. title patterns (tutorial, opinion);
3. URL shape (documentation sites);
4. weak source defaults (youtube → media, stackexchange → reference).
"""

from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import urlparse

from scrolls.items import ScrollItem

ENGINE = "rules-v1"

# Platforms whose category is inherent to the platform itself. A `doi.org`
# link (the `crossref` source) is handled separately in `_curated_category`:
# a Crossref work is a paper, but a DataCite output's category depends on its
# resource type (ADR 0045).
_CURATED_SOURCE_CATEGORIES = {
    "wikipedia": "reference",
    # Wikidata is Wikipedia's structured-knowledge sibling — a graph entity is an
    # encyclopedic entry to consult, a reference like the article about it
    # (ADR 0075).
    "wikidata": "reference",
    # An RFC is a normative technical standard — used as a reference spec, like a
    # Wikipedia article rather than a paper to cite (ADR 0066).
    "rfc": "reference",
    "arxiv": "paper",
    # bioRxiv and medRxiv are preprint servers — arXiv's biology/medicine
    # siblings, so their preprints are papers too (ADR 0068).
    "biorxiv": "paper",
    "medrxiv": "paper",
    # PubMed indexes biomedical papers — the arXiv/Crossref paper sibling
    # (ADR 0065).
    "pubmed": "paper",
    "github": "project",
    # GitLab repos are projects to read like github's, not packages to install
    # (ADR 0055).
    "gitlab": "project",
    # Gitea/Forgejo repos are projects to read like github's/gitlab's (ADR 0056).
    "gitea": "project",
    # Bitbucket repos are projects to read like the other code hosts' (ADR 0057).
    "bitbucket": "project",
    # A published package is something you install and use — distinct from a
    # github repo (a "project" to read). PyPI, npm, crates.io, Packagist,
    # RubyGems, and Go modules all ship packages, the rules that produce "tool".
    "pypi": "tool",
    "npm": "tool",
    "crates": "tool",
    "packagist": "tool",
    "rubygems": "tool",
    "go": "tool",
}

# Ordered: first matching pattern decides.
_TITLE_RULES = (
    (
        re.compile(
            r"\b(tutorial|how to|guide|walkthrough|getting started"
            r"|introduction to|intro to)\b",
            re.IGNORECASE,
        ),
        "tutorial",
    ),
    (
        re.compile(r"\b(why i|i think|opinion|in defense of|hot take)\b", re.IGNORECASE),
        "opinion",
    ),
    # A "Show HN" post is someone presenting a thing they built (Ask HN,
    # by contrast, is a question with no honest single category).
    (re.compile(r"\bShow HN\b", re.IGNORECASE), "project"),
)

_WEAK_SOURCE_CATEGORIES = {
    "youtube": "media",
    # A Q&A thread is used as a reference answer, but an explicit "how to"
    # title (a title rule, checked first) is a tutorial, so this stays weak.
    "stackexchange": "reference",
}

# DataCite `resourceTypeGeneral` (lowercased) → category. A DataCite DOI is
# not always a paper (unlike Crossref): a dataset is the IDEAS.md §8 `dataset`
# term, software and other runnable/usable artifacts are tools, the textual
# literature types are papers, and audiovisual outputs are media. A type not
# listed here (`Collection`, `Event`, `Other`, …) is genuinely ambiguous and
# stays unclassified rather than guessed — the engine's standing rule.
_DATACITE_CATEGORIES = {
    "dataset": "dataset",
    "software": "tool",
    "computationalnotebook": "tool",
    "workflow": "tool",
    "model": "tool",
    "service": "tool",
    "text": "paper",
    "book": "paper",
    "bookchapter": "paper",
    "journalarticle": "paper",
    "conferencepaper": "paper",
    "dissertation": "paper",
    "report": "paper",
    "preprint": "paper",
    "datapaper": "paper",
    "peerreview": "paper",
    "standard": "paper",
    "audiovisual": "media",
    "image": "media",
    "sound": "media",
}

# CSL `type` (lowercased) → category, for a DOI served by content negotiation
# (ADR 0081). The agencies reached only this way (JaLC, mEDRA, KISTI, OP, …)
# are scholarly-literature registries, so unlike DataCite a content-negotiated
# DOI defaults to `paper` (see `_doi_category`); this map only redirects the
# few CSL types that are honestly not papers.
_CSL_CATEGORIES = {
    "dataset": "dataset",
    "software": "tool",
    "figure": "media",
    "graphic": "media",
    "motion_picture": "media",
    "song": "media",
}


def classify_item(item: ScrollItem) -> ScrollItem:
    """Return the item with a rule-derived category, or unchanged if none match.

    The input item is never mutated. When a rule fires, the engine name is
    recorded as `provenance.classified_by` alongside the fetch provenance.
    """
    category = _category(item)
    if category is None:
        return item
    return replace(
        item,
        category=category,
        provenance={**(item.provenance or {}), "classified_by": ENGINE},
    )


def _category(item: ScrollItem) -> str | None:
    curated = _curated_category(item)
    if curated:
        return curated

    title = item.title or ""
    for pattern, category in _TITLE_RULES:
        if pattern.search(title):
            return category

    if _is_documentation_url(item.url):
        return "documentation"

    return _WEAK_SOURCE_CATEGORIES.get(item.source)


def _curated_category(item: ScrollItem) -> str | None:
    """The platform-inherent category, or None.

    Hugging Face serves three repo kinds under one source (ADR 0041,
    ADR 0043), so the category is read off the source id's prefix: a
    `model:` or `space:` repo is a `tool` (a published artifact you use —
    a package, a hosted demo), a `dataset:` repo is a `dataset` (the
    IDEAS.md §8 vocabulary term). A huggingface item that is none of these
    — a profile or listing page registered but never fetched — has no
    inherent category and falls through.

    A `doi.org` link (the `crossref` source) is likewise type-dependent
    (ADR 0045) and handled by `_doi_category`.
    """
    if item.source == "huggingface":
        source_id = item.source_id or ""
        if source_id.startswith("dataset:"):
            return "dataset"
        if source_id.startswith(("model:", "space:")):
            return "tool"
        return None
    if item.source == "crossref":
        return _doi_category(item)
    return _CURATED_SOURCE_CATEGORIES.get(item.source)


def _doi_category(item: ScrollItem) -> str | None:
    """The category of a `doi.org` item, by which agency served it (ADR 0045, 0081).

    A Crossref work is always a published `paper` (arXiv's preprint sibling).
    A DataCite output's category depends on its resource type, which the
    DataCite adapter records in `provenance.resource_type` because it can only
    be known at fetch time — the same fetch-time fact the source name can't
    carry. An unmapped or absent DataCite type stays unclassified. A DOI served
    by content negotiation (the long-tail agencies — JaLC, mEDRA, …, all
    scholarly-literature registries) defaults to `paper` like Crossref, but an
    explicit `dataset`/`software` CSL type is honored. A DOI not yet fetched
    (no adapter provenance) defaults to `paper`, the common case.
    """
    provenance = item.provenance or {}
    adapter = provenance.get("adapter")
    resource_type = (provenance.get("resource_type") or "").lower()
    if adapter == "datacite":
        return _DATACITE_CATEGORIES.get(resource_type)
    if adapter == "content-negotiation":
        return _CSL_CATEGORIES.get(resource_type, "paper")
    return "paper"


def _is_documentation_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path_parts = [p.lower() for p in parsed.path.split("/") if p]
    return (
        host.startswith("docs.")
        or host.endswith(".readthedocs.io")
        or "docs" in path_parts
        or "documentation" in path_parts
    )
