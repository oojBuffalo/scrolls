"""Rules classification engine (IDEAS.md §8, ADR 0004).

Layer one of "regex/rules first → optional LLM second → user overrides
always win": a deterministic category from signals that don't need a
model — which platform the item came from, how its title reads, and what
its URL looks like. Items nothing matches stay unclassified rather than
getting a guessed label; a future LLM engine can pick them up.

Precedence (first hit wins):

1. curated-platform defaults — wikipedia/arxiv/crossref/github/pypi/npm/
   crates/packagist/rubygems/go/huggingface items are what their platform
   makes them, whatever the title says;
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

# Platforms whose category is inherent to the platform itself.
_CURATED_SOURCE_CATEGORIES = {
    "wikipedia": "reference",
    "arxiv": "paper",
    # A Crossref work is a published paper (journal article, conference
    # paper, book chapter) — arXiv's preprint sibling, the same category.
    "crossref": "paper",
    "github": "project",
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
    """
    if item.source == "huggingface":
        source_id = item.source_id or ""
        if source_id.startswith("dataset:"):
            return "dataset"
        if source_id.startswith(("model:", "space:")):
            return "tool"
        return None
    return _CURATED_SOURCE_CATEGORIES.get(item.source)


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
