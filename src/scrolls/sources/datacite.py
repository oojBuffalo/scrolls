"""DataCite DOI fetch adapter (IDEAS.md §6, ADR 0045).

The Crossref adapter (ADR 0037) turns a `doi.org/<doi>` link into a clean
scroll from the work's *registered* metadata — but it covers only the DOIs
Crossref runs the registration agency for: the published scholarly
literature. The other large DOI registration agency is **DataCite**, which
registers the DOIs of datasets, software, models, and other research
outputs deposited in repositories like Zenodo, Dryad, and figshare. A
DataCite-only DOI 404s against Crossref (`crossref.fetch_item` raises
`FetchError`), so until now it fell back to the generic `web` adapter —
a `trafilatura` scrape of a JavaScript landing page — or stayed stuck at
`detected`.

This adapter is the DataCite half, chosen by the fetch-time fallback in
`sources/doi.py`: same `doi.org` detection, same `crossref:<doi>` identity
(the registration agency can't be known from the URL alone, and item
identity is fixed at `add` time — `provenance.adapter` records which agency
actually answered). One GET against the keyless DataCite REST API
(`api.datacite.org/dois/<doi>`) returns the work as a JSON:API document
(`{data: {attributes: {...}}}`) — no auth, no runtime dependency.

DataCite's schema (Kernel 4) is the structural sibling of Crossref's with
different field names, confirmed against the live API:

1. **Identity is the DOI, folded.** Same as Crossref (ADR 0037): the id is
   lowercased at detection, and `attributes.doi` (echoed back) builds the
   canonical `https://doi.org/<doi>` URL.

2. **The abstract is a typed `description`, when present.** DataCite has no
   full text, so the searchable prose is the `descriptions` entry whose
   `descriptionType` is `Abstract`. It is usually plain text but may carry
   HTML, so it is reduced like Crossref's JATS abstract. No `Abstract`
   description → a metadata-only scroll (title, creators, publisher, date),
   the honest common case (ADR 0002), still far better than a `web` scrape.

3. **The resource type determines the category.** `types.resourceTypeGeneral`
   is a controlled vocabulary (`Dataset`, `Software`, `Text`, `Image`, …) —
   unlike Crossref (a published work is always a `paper`), a DataCite output
   is a dataset, a tool, a paper, or media depending on its type. The type
   can only be known *after* fetch (it is not in the URL), so it is recorded
   in `provenance.resource_type` and the rules engine maps it to a category
   (`classify.py`, ADR 0004) — the way Hugging Face's repo kind is read off
   the source id (ADR 0041).

`subjects` become `concepts` like github repo topics (ADR 0007); the
resource type, its free-text refinement, and the publishing repository
become `tags` (the controlled-facet slot, ADR 0008); the landing page and
the parent work's DOI (a dataset's `container`) become `links` — the latter
resolving through `scrolls related`/`graph` to a saved Crossref paper, a
DataCite-output↔parent-work edge in the spirit of ADR 0038/0041.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

API_ROOT = "https://api.datacite.org/dois"
DOI_RESOLVER = "https://doi.org"

# Like Crossref, some records carry hundreds of creators; the author field is
# a display string, so a long list is truncated to a readable head + "et al."
_MAX_AUTHORS = 10

# DataCite title types that are not the main title; everything else (no type,
# or an unknown one) is treated as the main title.
_SUBTITLE_TYPE = "Subtitle"
_NON_MAIN_TITLE_TYPES = {"Subtitle", "AlternativeTitle", "TranslatedTitle", "Other"}

# DataCite date types in publication-date precedence: when a record carries
# several dates, the one published wins, down to the record's own timestamps.
_DATE_TYPE_PRECEDENCE = ("Issued", "Available", "Accepted", "Created", "Submitted", "Updated")

GetJson = Callable[[str], Any]

_TAG_RE = re.compile(r"<[^>]+>")


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected DOI's DataCite metadata; return it at stage 'fetched'.

    Raises FetchError when the DOI is missing, the request fails, or the DOI
    is not registered with DataCite (a Crossref journal-article DOI, for
    instance, 404s here). The input item is never mutated.
    """
    get_json = get_json or _get_json
    if not item.source_id:
        raise FetchError(f"cannot determine DOI for item {item.id!r}")

    url = f"{API_ROOT}/{quote(item.source_id, safe='/')}"
    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"DataCite API request failed: {exc}") from exc

    record = data.get("data") if isinstance(data, dict) else None
    attributes = record.get("attributes") if isinstance(record, dict) else None
    if not isinstance(attributes, dict):
        raise FetchError(f"work not found: {item.source_id}")

    doi = _clean(attributes.get("doi")) or item.source_id
    canonical_url = f"{DOI_RESOLVER}/{doi}"
    summary = _abstract(attributes)
    raw = json.dumps(attributes, ensure_ascii=False)
    hashed = summary or raw
    return replace(
        item,
        title=_title(attributes, doi),
        author=_authors(attributes),
        published_at=_published(attributes) or item.published_at,
        canonical_url=canonical_url,
        raw_text=raw,
        summary=summary,
        tags=_tags(attributes),
        concepts=_concepts(attributes),
        links=_links(attributes, canonical_url),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "datacite",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "datacite-api:json",
            # The category-determining fact, read at fetch time and consumed
            # by the rules engine (classify.py) — DataCite outputs are not all
            # papers, unlike Crossref works.
            "resource_type": _resource_type(attributes) or "",
        },
        stage="fetched",
    )


def _clean(value: Any) -> str | None:
    """A non-empty trimmed string, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _resource_type(attributes: dict[str, Any]) -> str | None:
    """`types.resourceTypeGeneral`, the DataCite controlled resource vocabulary."""
    types = attributes.get("types")
    return _clean(types.get("resourceTypeGeneral")) if isinstance(types, dict) else None


def _title(attributes: dict[str, Any], doi: str) -> str | None:
    """The main title joined with its subtitle, falling back to the DOI.

    DataCite splits titles into a `titles` array of `{title, titleType?}`.
    The main title is the entry with no `titleType` (or an unrecognized one);
    a `titleType: "Subtitle"` entry is joined `Title: Subtitle`, the way
    Crossref joins `title` and `subtitle` (ADR 0037). A record with no usable
    title falls back to the DOI so the scroll is never untitled.
    """
    titles = attributes.get("titles")
    if not isinstance(titles, list):
        return doi
    main = subtitle = None
    for entry in titles:
        if not isinstance(entry, dict):
            continue
        text = _clean(entry.get("title"))
        if not text:
            continue
        kind = _clean(entry.get("titleType"))
        if kind == _SUBTITLE_TYPE and subtitle is None:
            subtitle = text
        elif kind not in _NON_MAIN_TITLE_TYPES and main is None:
            main = text
    if main and subtitle:
        return f"{main}: {subtitle}"
    return main or subtitle or doi


def _authors(attributes: dict[str, Any]) -> str | None:
    """The `creators` list as a display string, truncated past `_MAX_AUTHORS`.

    A personal creator carries `givenName`/`familyName` (rendered
    "Given Family" to match Crossref, not the DataCite `name`'s
    "Family, Given"); an organizational creator carries only `name`. A list
    longer than the cap keeps its head and appends "et al."
    """
    raw = attributes.get("creators")
    if not isinstance(raw, list):
        return None
    names = [n for n in (_format_creator(c) for c in raw if isinstance(c, dict)) if n]
    if not names:
        return None
    if len(names) > _MAX_AUTHORS:
        names = names[:_MAX_AUTHORS] + ["et al."]
    return ", ".join(names)


def _format_creator(creator: dict[str, Any]) -> str | None:
    """One creator as "Given Family", else its `name`, else the bare part."""
    given = _clean(creator.get("givenName"))
    family = _clean(creator.get("familyName"))
    if given and family:
        return f"{given} {family}"
    return _clean(creator.get("name")) or family or given


def _published(attributes: dict[str, Any]) -> str | None:
    """The publication date as UTC ISO 8601, by DataCite date precedence.

    `dates` is an array of `{date, dateType}`; the first present type in
    `_DATE_TYPE_PRECEDENCE` wins. A date may be a range (`start/end`); the
    start is taken. Failing all of that, `publicationYear` (a required field)
    pads to Jan 1 — the invented-but-uniform precision date-only values
    already get (ADR 0024).
    """
    by_type: dict[str, str] = {}
    dates = attributes.get("dates")
    if isinstance(dates, list):
        for entry in dates:
            if not isinstance(entry, dict):
                continue
            kind = _clean(entry.get("dateType"))
            value = _clean(entry.get("date"))
            if kind and value and kind not in by_type:
                by_type[kind] = value
    for kind in _DATE_TYPE_PRECEDENCE:
        if kind in by_type:
            iso = to_utc_iso(by_type[kind].split("/", 1)[0])
            if iso:
                return iso
    year = _year(attributes.get("publicationYear"))
    return to_utc_iso(f"{year:04d}-01-01") if year is not None else None


def _year(value: Any) -> int | None:
    """`publicationYear` as an int, however the JSON typed it (int/float/str).

    DataCite requires the field but feeds vary — an integer, a float
    (`2023.0`), or a string — so each shape is coerced; a bool (a JSON
    `true`/`false`, an int subclass) is rejected, and an out-of-range year
    is caught later by `to_utc_iso` failing to parse the padded date.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _abstract(attributes: dict[str, Any]) -> str | None:
    """The `Abstract`-typed description reduced to plain text, or None.

    DataCite descriptions are typed; only `descriptionType: "Abstract"` is
    the searchable prose. Other types (`Other`, `Methods`,
    `SeriesInformation`) are deposit context, not a summary, so they are
    deliberately left out — a record with no abstract is honestly
    metadata-only (ADR 0002), like a Crossref work with no abstract.
    """
    descriptions = attributes.get("descriptions")
    if not isinstance(descriptions, list):
        return None
    for entry in descriptions:
        if isinstance(entry, dict) and _clean(entry.get("descriptionType")) == "Abstract":
            return _plain_text(entry.get("description"))
    return None


def _plain_text(value: Any) -> str | None:
    """A string reduced to plain text: tags stripped, entities unescaped.

    Mirrors Crossref's JATS cleaning (ADR 0037): tags become a space so block
    boundaries don't glue words, whitespace collapses, and the space an inline
    tag leaves before punctuation is removed.
    """
    if not isinstance(value, str):
        return None
    text = html.unescape(_TAG_RE.sub(" ", value))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?)])", r"\1", text)
    return text or None


def _concepts(attributes: dict[str, Any]) -> tuple[str, ...]:
    """DataCite `subjects` as deduped concepts (the github-topics parallel)."""
    subjects = attributes.get("subjects")
    if not isinstance(subjects, list):
        return ()
    values = (s.get("subject") for s in subjects if isinstance(s, dict))
    return _dedupe(values)


def _tags(attributes: dict[str, Any]) -> tuple[str, ...]:
    """The resource type, its free-text refinement, and the publisher as tags.

    `resourceTypeGeneral` is the controlled facet (the slot arXiv's taxonomy
    codes and Crossref's `type` fill, ADR 0008/0037); `resourceType` is its
    free-text refinement; and `publisher` (the depositing repository — Zenodo,
    Dryad, figshare) is the venue analog, so `scrolls related` can corroborate
    two outputs from the same repository. KB pages are per concept, not per
    tag, so a noisy publisher name here costs nothing.
    """
    types = attributes.get("types")
    general = types.get("resourceTypeGeneral") if isinstance(types, dict) else None
    specific = types.get("resourceType") if isinstance(types, dict) else None
    return _dedupe([general, specific, attributes.get("publisher")])


def _dedupe(values: Any) -> tuple[str, ...]:
    """Non-empty trimmed strings, order-preserving and deduped."""
    cleaned = (_clean(v) for v in values)
    return tuple(dict.fromkeys(v for v in cleaned if v))


def _links(attributes: dict[str, Any], canonical: str) -> tuple[str, ...]:
    """The landing page and the parent work's DOI as outgoing links.

    `attributes.url` is the page the DOI resolves to (kept when it is an
    http(s) URL distinct from the canonical doi.org link). A `container` whose
    `identifierType` is `DOI` is the parent work — a dataset's source paper, a
    software version's concept record — kept as `https://doi.org/<doi>` so it
    resolves through `scrolls related`/`graph` to a saved Crossref paper or
    sibling DataCite item (the cross-source edge of ADR 0038/0041).
    """
    out: list[str] = []
    url = _clean(attributes.get("url"))
    if url and url.lower().startswith(("http://", "https://")):
        if url.rstrip("/") != (canonical or "").rstrip("/"):
            out.append(url)
    container = attributes.get("container")
    if isinstance(container, dict) and _clean(container.get("identifierType")) == "DOI":
        ident = _clean(container.get("identifier"))
        if ident:
            doi_link = f"{DOI_RESOLVER}/{ident.lower()}"
            if doi_link.rstrip("/") != (canonical or "").rstrip("/") and doi_link not in out:
                out.append(doi_link)
    return tuple(out)


_get_json = http.get_json
