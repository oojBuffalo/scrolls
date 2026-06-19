"""Rules classification engine (IDEAS.md §8, ADR 0004).

Layer one of "regex/rules first → optional LLM second → user overrides
always win": a deterministic category from signals that don't need a
model — which platform the item came from, how its title reads, and what
its URL looks like. Items nothing matches stay unclassified rather than
getting a guessed label; a future LLM engine can pick them up.

Precedence (first hit wins):

1. curated-platform defaults — wikipedia/wikidata/rfc/arxiv/biorxiv/medrxiv/pubmed/
   crossref/zenodo/github/gitlab/gitea/bitbucket/pypi/npm/crates/packagist/rubygems/go/pub/hex/
   nuget/hackage/maven/
   huggingface items are what their platform makes them, whatever the title says
   (a github/gitlab/gitea/bitbucket repo is a `project`, but a github issue/PR
   `owner/repo#<n>`, gitlab issue/MR `group/project#<n>`/`!<n>`, gitea issue/PR
   `<host>/<owner>/<repo>#<n>`, or bitbucket issue/PR `workspace/repo#<n>`/`!<n>`
   is a discussion thread left unclassified — ADR 0084/0085/0086/0087);
2. title patterns (tutorial, opinion);
3. URL shape (documentation sites);
4. weak source defaults (youtube → media, stackexchange → reference).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import replace
from urllib.parse import urlparse

from scrolls.items import ScrollItem

ENGINE = "rules-v1"

# The precedence tiers, in the order `_category` consults them. The tier that
# fires is recorded as `provenance.classified_basis` — the "which signal"
# behind a category, the H19-flagged method granularity. These are the four
# documented tiers (this module's header), not finer (which exact map entry
# fired is over-granular for audit; the engine + ruleset fingerprint already
# pin the rest — custody §2.8, pay for complexity).
BASIS_CURATED = "curated-source"
BASIS_TITLE = "title-pattern"
BASIS_DOC_URL = "documentation-url"
BASIS_WEAK = "weak-source"

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
    # GitLab repos are projects to read like github's, not packages to install
    # (ADR 0055).
    "gitlab": "project",
    # Gitea/Forgejo repos are projects to read like github's/gitlab's (ADR 0056).
    "gitea": "project",
    # Bitbucket repos are projects to read like the other code hosts' (ADR 0057).
    "bitbucket": "project",
    # A published package is something you install and use — distinct from a
    # github repo (a "project" to read). PyPI, npm, crates.io, Packagist,
    # RubyGems, Go modules, pub.dev, Hex, NuGet, Hackage, and Maven Central all
    # ship packages, the rules that produce "tool".
    "pypi": "tool",
    "npm": "tool",
    "crates": "tool",
    "packagist": "tool",
    "rubygems": "tool",
    "go": "tool",
    "pub": "tool",
    "hex": "tool",
    "nuget": "tool",
    "hackage": "tool",
    # Maven Central is the JVM package registry (Java/Kotlin/Scala/…), a package
    # to depend on like the others (ADR 0092).
    "maven": "tool",
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

# Zenodo `resource_type.type` (the InvenioRDM upload-type vocabulary) → category.
# Like a DataCite output, a Zenodo deposit is not always a paper (ADR 0083): a
# dataset is the IDEAS.md §8 `dataset` term, software is a tool, the publication
# family is literature, and image/video deposits are media. The genuinely
# ambiguous types (`poster`, `presentation`, `lesson`, `physicalobject`, `other`)
# stay unclassified rather than guessed — the engine's standing rule, the same
# honesty DataCite's unmapped types get.
_ZENODO_CATEGORIES = {
    "dataset": "dataset",
    "software": "tool",
    "publication": "paper",
    "image": "media",
    "video": "media",
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

    The input item is never mutated. When a rule fires, the method is recorded
    in `provenance` alongside (never replacing) the fetch provenance, so a
    re-classify is reproducible and auditable:

    - ``classified_by`` — the engine (``rules-v1``);
    - ``classified_basis`` — which precedence tier fired (the H20 method
      granularity: ``curated-source`` / ``title-pattern`` / ``documentation-url``
      / ``weak-source``);
    - ``classified_ruleset`` — the fingerprint of the rule tables this run used
      (``RULESET_FINGERPRINT``), so a reader can tell whether the ruleset has
      changed since — i.e. whether a re-classify today would still reproduce
      this category.

    Stamping is idempotent: re-running on an already-classified item recomputes
    the same category, basis, and fingerprint and overwrites the same keys, so a
    re-classify of an unchanged library is a no-op in result.
    """
    verdict = _category(item)
    if verdict is None:
        return item
    category, basis = verdict
    return replace(
        item,
        category=category,
        provenance={
            **(item.provenance or {}),
            "classified_by": ENGINE,
            "classified_basis": basis,
            "classified_ruleset": RULESET_FINGERPRINT,
        },
    )


def _category(item: ScrollItem) -> tuple[str, str] | None:
    """The (category, precedence-tier) a rule produces, or None if none match."""
    curated = _curated_category(item)
    if curated:
        return curated, BASIS_CURATED

    title = item.title or ""
    for pattern, category in _TITLE_RULES:
        if pattern.search(title):
            return category, BASIS_TITLE

    if _is_documentation_url(item.url):
        return "documentation", BASIS_DOC_URL

    weak = _WEAK_SOURCE_CATEGORIES.get(item.source)
    if weak is not None:
        return weak, BASIS_WEAK
    return None


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
    # GitHub serves two kinds under one source (ADR 0084): a repo (`owner/repo`)
    # is a `project`, but an issue or pull request (`owner/repo#<n>`) is a
    # heterogeneous discussion thread — unclassified by default like HN/Lobsters,
    # leaving its title patterns free to decide (a "how to" issue is a tutorial).
    if item.source == "github":
        return None if "#" in (item.source_id or "") else "project"
    # GitLab serves the same two kinds (ADR 0085): a project (`group/project`)
    # is a `project`, but an issue (`…#<n>`) or merge request (`…!<n>`) is a
    # heterogeneous discussion thread — unclassified by default like github's,
    # leaving its title patterns free to decide.
    if item.source == "gitlab":
        source_id = item.source_id or ""
        return None if ("#" in source_id or "!" in source_id) else "project"
    # Gitea/Forgejo serves the same two kinds (ADR 0086): a repo
    # (`<host>/<owner>/<repo>`) is a `project`, but an issue or pull request
    # (`…#<n>`) is a heterogeneous discussion thread — unclassified by default
    # like github's, leaving its title patterns free to decide. Gitea unifies
    # numbering like github, so one `#` marker carves out (not gitlab's two).
    if item.source == "gitea":
        return None if "#" in (item.source_id or "") else "project"
    # Bitbucket serves the same two kinds (ADR 0087): a repo (`workspace/repo`)
    # is a `project`, but an issue (`…#<n>`) or pull request (`…!<n>`) is a
    # heterogeneous discussion thread — unclassified by default like github's.
    # Bitbucket splits numbering like gitlab, so two markers (`#`/`!`) carve out.
    if item.source == "bitbucket":
        source_id = item.source_id or ""
        return None if ("#" in source_id or "!" in source_id) else "project"
    if item.source == "crossref":
        return _doi_category(item)
    # A Zenodo deposit's category depends on its resource type, a fetch-time
    # fact the adapter records in `provenance.resource_type` — the DataCite
    # mechanism (ADR 0045/0083). An unfetched or unmapped/ambiguous type stays
    # unclassified.
    if item.source == "zenodo":
        resource_type = ((item.provenance or {}).get("resource_type") or "").lower()
        return _ZENODO_CATEGORIES.get(resource_type)
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


def _ruleset_digest() -> str:
    """A short content fingerprint of the rule *tables*.

    Recorded as `provenance.classified_ruleset` so a held classification names
    the exact ruleset that produced it: if these tables change, the fingerprint
    changes, and a reader can tell a re-classify would no longer reproduce the
    stored category without re-running the engine. The fingerprint covers the
    data-driven rules (the category maps and title patterns); the engine's
    code-level logic — the URL shape test, the per-platform `source_id` parsing
    — is versioned by the engine name (`rules-v1` → a future `rules-v2` on a
    behavior change), so the two together pin the whole ruleset.
    """
    payload = {
        "engine": ENGINE,
        "curated_source": _CURATED_SOURCE_CATEGORIES,
        "title_rules": [(pattern.pattern, category) for pattern, category in _TITLE_RULES],
        "weak_source": _WEAK_SOURCE_CATEGORIES,
        "datacite": _DATACITE_CATEGORIES,
        "zenodo": _ZENODO_CATEGORIES,
        "csl": _CSL_CATEGORIES,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


# Computed once at import: a fixed input → a stable digest, the determinism the
# re-derivation contract rests on (`tests/test_classify.py`).
RULESET_FINGERPRINT = _ruleset_digest()


def classification_freshness(provenance: dict | None) -> str | None:
    """Recency of a rules classification against the *live* ruleset, or None.

    The single freshness primitive shared by every surface that asks "would a
    re-classify today still reproduce this category?" — the per-item confidence
    marker (`items.classification_view`, roadmap H21), `doctor`'s
    `custody.enrichment` aggregate (H25), and `is_stale_classification` (the
    `classify --stale` selector, H27). One home, so the marker an agent reads on
    a search hit can never disagree with the count doctor reports or the pool a
    refresh acts on.

    Recency here is the *ruleset* fingerprint, not a wall-clock timestamp: the
    classification stamps are deterministic and idempotent (re-classify is a
    no-op in result, the H19/H20 contract), so a `classified_at` would break
    that contract — the ruleset digest *is* the honest, idempotent recency
    signal. Returns:

    - ``current`` — classified under the live ruleset (`RULESET_FINGERPRINT`);
    - ``stale`` — classified under a *superseded* ruleset (a re-classify may
      now differ);
    - ``unknown`` — rules-classified before H20, so no fingerprint was recorded
      (doctor's ``unfingerprinted`` bucket): we cannot tell, so it is not
      silently called current;
    - ``None`` — not a rules classification at all (an LLM category, a hand-set
      override carrying no engine stamp, or an unclassified item): freshness
      against the rules ruleset is not a question we can answer, so no claim is
      made (honest absence).
    """
    provenance = provenance or {}
    if provenance.get("classified_by") != ENGINE:
        return None
    fingerprint = provenance.get("classified_ruleset")
    if fingerprint is None:
        return "unknown"
    return "current" if fingerprint == RULESET_FINGERPRINT else "stale"


def is_stale_classification(item: ScrollItem) -> bool:
    """True if `item` was rules-classified under a *superseded* ruleset.

    The selector behind both `doctor`'s `custody.enrichment.stale` report (the
    items it flags) and `scrolls classify --stale` (the items it refreshes), so
    the count doctor shows equals the count a refresh acts on — closing the loop
    H20 (record the ruleset) → H25 (report what's stale) → H27 (refresh it on
    request). A thin reading of `classification_freshness`, so the stale pool, the
    doctor aggregate, and the per-item confidence marker share one derivation.

    Excluded, deliberately (each `classification_freshness != "stale"`):

    - an *unfingerprinted* classification (pre-H20, ``classified_ruleset`` is
      absent) is *unknown*, not stale — we cannot tell whether a re-classify
      would differ, so it is left alone (doctor's separate ``unfingerprinted``
      bucket);
    - an LLM classification (``classified_by != rules-v1``) — a different
      re-derivability axis, out of scope;
    - a hand-set category, which carries no engine stamp at all
      (`overrides.apply_overrides`) — user overrides always win, so a refresh
      must never reach them.
    """
    return classification_freshness(item.provenance) == "stale"


def stale_classifications(
    items: Iterable[ScrollItem], source: str | None = None
) -> list[ScrollItem]:
    """The rules-classified items a re-classify would no longer reproduce.

    The selection behind both `scrolls classify --stale` (whole-library) and its
    per-source narrowing `classify --stale --source <S>` (roadmap H154): the
    `is_stale_classification` set, optionally intersected with one source — the
    enrichment-axis counterpart of `verify --source <S>` (the per-source *drift*
    recheck). One home for the predicate, so the pool a refresh acts on can never
    disagree with the count `doctor` reports:

    - whole-library (``source=None``) is exactly the set `doctor`'s
      ``custody.enrichment.stale`` flags and `--stale` alone refreshes;
    - per-source (``source=S``) is exactly that set filtered to one source, so
      ``len(stale_classifications(items, source=S))`` equals `doctor`'s
      ``custody.enrichment.by_source[S]`` by construction (both filter the same
      stale set by source), and refreshing them restamps each to the live
      ruleset — clearing that source's entry from the offenders-only map (the
      H27 report↔refresh convergence, per source).

    Sources are open-ended (no closed vocabulary), so a source nothing stale is
    held for is the honest empty selection — a network-free no-op, never an
    error. Pure: it selects, leaving the caller to zero the category and re-run
    the engine, so a test can re-derive the per-source count independently.
    """
    return [
        item
        for item in items
        if is_stale_classification(item) and (source is None or item.source == source)
    ]


def stale_classification_counts_by_source(items: Iterable[ScrollItem]) -> dict[str, int]:
    """Per-source stale-classification debt over an item set: ``{source: count}``.

    The one builder behind both `doctor`'s ``custody.enrichment.by_source`` (roadmap
    H135) and the readable ``_Refresh:_`` briefing line (roadmap H178), so the count
    the audit reports and the sources the briefing names can never disagree — the
    enrichment-axis counterpart of how `custody_counts_by_source` is the one home for
    the drift `by_source`. Offending sources only (a source with nothing stale is
    omitted, the ``items``-list posture), keys in sorted order. Every stale item has
    exactly one source, so the values sum to ``len(stale_classifications(items))`` by
    construction (the H104/H121 sum-to-whole posture on the enrichment axis).

    Pure over whatever item set it is given: `doctor` passes the whole-library (or
    `--source`-scoped) held items; the briefing passes its query scope, so the
    briefing's per-source debt is computed over exactly the scope it covers (the
    scope-consistent posture the readable drift `_Attention:_` line takes). A source
    with no stale debt is the honest empty map — a network-free no-op, never an error.
    """
    counts: dict[str, int] = {}
    for item in items:
        if is_stale_classification(item):
            counts[item.source] = counts.get(item.source, 0) + 1
    return {source: counts[source] for source in sorted(counts)}
