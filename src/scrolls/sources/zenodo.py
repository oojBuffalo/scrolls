"""Zenodo record fetch adapter (IDEAS.md §6, ADR 0083).

Zenodo (CERN's open-science repository) is where research *datasets*,
*software*, preprints, posters, and presentations are deposited and minted a
DOI — the default archive for EU-funded output and for the snapshot every
released GitHub repo gets when it wants a citable DOI. A saved
`zenodo.org/records/<id>` landing page fell through to the generic `web`
adapter until now: a `trafilatura` scrape of a JavaScript app that loses the
record's keywords, its resource type, and — most of all — the DOI and the
related-identifier edges that tie a deposit to the paper it supplements or
the software it archives. It was a concept-less, edgeless island, the
dev.to/Open Library gap (ADR 0061/0073).

Zenodo's DOIs are *DataCite*-registered, so a saved `doi.org/10.5281/zenodo.<id>`
link already fetches through the DataCite adapter (ADR 0045). This adapter is
the complement for the **landing-page** URL people actually paste: one keyless
GET against the InvenioRDM REST API (`zenodo.org/api/records/<recid>`) returns
the record as a JSON object (no JSON:API envelope, unlike DataCite), and the
record's own DOI becomes a `doi.org` link so the landing page and its DataCite
DOI scroll relate through `scrolls related`/`graph` and cluster as one work in
`scrolls works` (the DOI-edge pattern of ADR 0037/0038/0045).

Field mapping, confirmed against the live API:

1. **Identity is the record id in the URL.** A Zenodo record is a *specific
   version*; its `conceptrecid`/`conceptdoi` name the all-versions concept.
   The recid the URL carries is the identity (kept verbatim) — different
   versions are different items, the way Open Library editions are (ADR 0073).
   Deduping a version to its concept would need a fetch-time id rewrite, which
   every adapter defers (ADR 0048).

2. **The description is the summary, HTML stripped.** Zenodo descriptions are
   HTML; they are reduced to plain text like Crossref's JATS / DataCite's
   abstract. There is no work *body* here (the files are the deposit, captured
   separately by `scrolls media` if ever), so there is **no `extracted_text`** —
   the metadata-only shape of Crossref/DataCite/PubMed/Open Library (ADR 0037).

3. **The resource type determines the category.** `resource_type.type`
   (`dataset`, `software`, `publication`, `image`, `video`, …) is a controlled
   vocabulary, and a Zenodo deposit is not always a paper — so, exactly like
   DataCite (ADR 0045), the type is recorded in `provenance.resource_type` and
   the rules engine maps it (`classify.py`). It can only be known after fetch.

`keywords` + `subjects` become `concepts` (the github-topics/MeSH role,
ADR 0007/0065); the resource type, its subtype, and the license become `tags`
(the controlled-facet slot, ADR 0008); the record DOI, the concept DOI, and
every `related_identifiers` entry (a `doi`/`arxiv`/`url` scheme) become `links`
— the supplemented paper, the archived-software repo, the sibling version —
resolving through `scrolls related`/`graph` to whatever is saved (ADR 0038/0041).
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

API_ROOT = "https://zenodo.org/api/records"
LANDING_ROOT = "https://zenodo.org/records"
DOI_RESOLVER = "https://doi.org"
ARXIV_ABS = "https://arxiv.org/abs"

# Some deposits list dozens of creators; the author field is a display string,
# so a long list keeps a readable head and appends "et al." (DataCite's cap).
_MAX_AUTHORS = 10

GetJson = Callable[[str], Any]

_TAG_RE = re.compile(r"<[^>]+>")
# An arXiv related identifier may be a bare id ("2004.03688", "math/0211159")
# or carry the `arXiv:` prefix; strip the prefix and keep the id.
_ARXIV_PREFIX = re.compile(r"^arxiv:", re.IGNORECASE)


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected Zenodo record's metadata; return it at stage 'fetched'.

    Raises FetchError when the record id is missing, the request fails, or the
    response is not a Zenodo record (a 404 returns a JSON error object with no
    `metadata`). The input item is never mutated.
    """
    get_json = get_json or _get_json
    if not item.source_id:
        raise FetchError(f"cannot determine Zenodo record id for item {item.id!r}")

    url = f"{API_ROOT}/{item.source_id}"
    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"Zenodo API request failed: {exc}") from exc

    metadata = data.get("metadata") if isinstance(data, dict) else None
    if not isinstance(metadata, dict):
        raise FetchError(f"record not found: {item.source_id}")

    doi = _clean(data.get("doi")) or _clean(metadata.get("doi"))
    canonical_url = _canonical(data, item.source_id)
    summary = _plain_text(metadata.get("description"))
    raw = json.dumps(metadata, ensure_ascii=False)
    hashed = summary or raw
    return replace(
        item,
        title=_title(data, metadata),
        author=_authors(metadata),
        published_at=_published(metadata) or item.published_at,
        canonical_url=canonical_url,
        raw_text=raw,
        summary=summary,
        tags=_tags(metadata),
        concepts=_concepts(metadata),
        links=_links(data, metadata, canonical_url, doi),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "zenodo",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "zenodo-api:json",
            # The category-determining fact, read at fetch time and consumed by
            # the rules engine (classify.py) — a Zenodo deposit is not always a
            # paper, the same as a DataCite output (ADR 0045).
            "resource_type": _resource_type(metadata) or "",
        },
        stage="fetched",
    )


def _clean(value: Any) -> str | None:
    """A non-empty trimmed string, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _canonical(data: dict[str, Any], recid: str) -> str:
    """The record's own landing page — `links.self_html`, else built from the id.

    `self_html` points at the *resolved* version (a concept-recid request lands
    on the latest version's page), so it is preferred; a record missing it falls
    back to the canonical `zenodo.org/records/<recid>` form.
    """
    links = data.get("links")
    if isinstance(links, dict):
        self_html = _clean(links.get("self_html"))
        if self_html and self_html.lower().startswith(("http://", "https://")):
            return self_html
    return f"{LANDING_ROOT}/{recid}"


def _resource_type(metadata: dict[str, Any]) -> str | None:
    """`resource_type.type`, the Zenodo upload-type vocabulary (lowercased form)."""
    resource_type = metadata.get("resource_type")
    return _clean(resource_type.get("type")) if isinstance(resource_type, dict) else None


def _title(data: dict[str, Any], metadata: dict[str, Any]) -> str | None:
    """The record title — `metadata.title`, the top-level title, else the DOI."""
    return (
        _clean(metadata.get("title"))
        or _clean(data.get("title"))
        or _clean(data.get("doi"))
    )


def _authors(metadata: dict[str, Any]) -> str | None:
    """The `creators` list as a display string, truncated past `_MAX_AUTHORS`.

    A Zenodo creator carries a free-form `name` ("Family, Given" for a person,
    the organization name for an org) — kept verbatim, not reformatted, since
    the deposit chose the form. A list longer than the cap keeps its head and
    appends "et al."
    """
    creators = metadata.get("creators")
    if not isinstance(creators, list):
        return None
    names = [
        n for n in (_clean(c.get("name")) for c in creators if isinstance(c, dict)) if n
    ]
    if not names:
        return None
    if len(names) > _MAX_AUTHORS:
        names = names[:_MAX_AUTHORS] + ["et al."]
    return ", ".join(names)


def _published(metadata: dict[str, Any]) -> str | None:
    """`publication_date` as UTC ISO 8601, partial EDTF dates padded to first-of.

    Zenodo dates are ISO (EDTF level 0): usually `YYYY-MM-DD`, but a deposit may
    declare only `YYYY` or `YYYY-MM`. `to_utc_iso` parses a full date-only value
    but not a partial one, so a bare year/year-month is padded to the first of
    the period — the invented-but-uniform precision partial dates already get
    (RFC's `Month Year`, ADR 0024/0066) — before parsing.
    """
    raw = _clean(metadata.get("publication_date")) or ""
    if re.fullmatch(r"\d{4}", raw):
        raw = f"{raw}-01-01"
    elif re.fullmatch(r"\d{4}-\d{2}", raw):
        raw = f"{raw}-01"
    return to_utc_iso(raw)


def _plain_text(value: Any) -> str | None:
    """A string reduced to plain text: tags stripped, entities unescaped.

    Mirrors DataCite/Crossref cleaning (ADR 0037/0045): tags become a space so
    block boundaries don't glue words, whitespace collapses, and the space an
    inline tag leaves before punctuation is removed.
    """
    if not isinstance(value, str):
        return None
    text = html.unescape(_TAG_RE.sub(" ", value))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?)])", r"\1", text)
    return text or None


def _concepts(metadata: dict[str, Any]) -> tuple[str, ...]:
    """Free-text `keywords` plus controlled `subjects` as deduped concepts.

    `keywords` is the deposit's own tag list (often `None`); `subjects` is the
    controlled-vocabulary list, each entry `{subject|term, ...}`. Both join the
    KB concept graph the way github repo topics do (ADR 0007).
    """
    values: list[Any] = []
    keywords = metadata.get("keywords")
    if isinstance(keywords, list):
        values.extend(keywords)
    subjects = metadata.get("subjects")
    if isinstance(subjects, list):
        values.extend(
            s.get("subject") or s.get("term") for s in subjects if isinstance(s, dict)
        )
    return _dedupe(values)


def _tags(metadata: dict[str, Any]) -> tuple[str, ...]:
    """The resource type, its subtype, and the license id as tags.

    `resource_type.type` is the controlled facet (the slot arXiv's taxonomy
    codes and DataCite's `resourceTypeGeneral` fill, ADR 0008/0045); `subtype`
    is its refinement (a publication's `article`/`preprint`); `license.id`
    (`cc-by-4.0`, `cc-zero`) is the rights facet the code-host/registry adapters
    also tag with (ADR 0055).
    """
    values: list[Any] = []
    resource_type = metadata.get("resource_type")
    if isinstance(resource_type, dict):
        values.append(resource_type.get("type"))
        values.append(resource_type.get("subtype"))
    license_ = metadata.get("license")
    if isinstance(license_, dict):
        values.append(license_.get("id"))
    return _dedupe(values)


def _dedupe(values: Any) -> tuple[str, ...]:
    """Non-empty trimmed strings, order-preserving and deduped."""
    cleaned = (_clean(v) for v in values)
    return tuple(dict.fromkeys(v for v in cleaned if v))


def _links(
    data: dict[str, Any],
    metadata: dict[str, Any],
    canonical: str,
    doi: str | None,
) -> tuple[str, ...]:
    """The record DOI, the concept DOI, and the related identifiers as links.

    The record's own DOI (`https://doi.org/<doi>`) is the edge that ties this
    landing page to its DataCite DOI scroll and clusters them in `scrolls works`
    (ADR 0045/0069). The `conceptdoi` (the all-versions DOI) links to the
    concept. Each `related_identifiers` entry is an outgoing edge resolved by
    its `scheme`: a `doi` to `doi.org`, an `arxiv` to `arxiv.org/abs` (the
    supplemented preprint — ADR 0038), a `url` kept as-is. Self-links (the
    record's own DOI echoed, the canonical page) are dropped, the graph's rule.
    """
    out: list[str] = []
    canonical_key = (canonical or "").rstrip("/")

    def add(link: str | None) -> None:
        if not link:
            return
        if link.rstrip("/") == canonical_key or link in out:
            return
        out.append(link)

    if doi:
        add(f"{DOI_RESOLVER}/{doi.lower()}")
    add(_doi_link(data.get("conceptdoi")))

    related = metadata.get("related_identifiers")
    if isinstance(related, list):
        for entry in related:
            if isinstance(entry, dict):
                add(_related_link(entry))
    return tuple(out)


def _doi_link(value: Any) -> str | None:
    """A bare DOI as a `doi.org` link, lowercased, else None."""
    doi = _clean(value)
    return f"{DOI_RESOLVER}/{doi.lower()}" if doi else None


def _related_link(entry: dict[str, Any]) -> str | None:
    """One `related_identifiers` entry as an outgoing link, by its scheme.

    `doi` → `doi.org/<doi>` (the work graph); `arxiv` → `arxiv.org/abs/<id>`
    (the preprint edge of ADR 0038, prefix stripped); `url` kept when http(s).
    Any other scheme (`isbn`, `pmid`, `handle`, …) is skipped — it has no
    resolver this library detects, so it would be a dead link.
    """
    identifier = _clean(entry.get("identifier"))
    if not identifier:
        return None
    scheme = (_clean(entry.get("scheme")) or "").lower()
    if scheme == "doi":
        return f"{DOI_RESOLVER}/{identifier.lower()}"
    if scheme == "arxiv":
        return f"{ARXIV_ABS}/{_ARXIV_PREFIX.sub('', identifier)}"
    if scheme == "url" and identifier.lower().startswith(("http://", "https://")):
        return identifier
    return None


_get_json = http.get_json
