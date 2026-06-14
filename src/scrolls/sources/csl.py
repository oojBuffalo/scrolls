"""Generic DOI content-negotiation fetch adapter — the universal agency fallback.

The Crossref adapter (ADR 0037) and the DataCite adapter (ADR 0045) turn a
`doi.org/<doi>` link into a clean scroll from the work's *registered*
metadata, but each covers only the DOIs its own registration agency holds:
Crossref the published scholarly literature, DataCite the datasets/software/
repository outputs. There are a dozen more DOI registration agencies — JaLC
(the entire Japanese scholarly literature), mEDRA, KISTI, OP (the EU
Publications Office), Airiti, CNKI, ISTIC — and a DOI registered with any of
them 404s against *both* the Crossref and DataCite REST APIs, so until now it
fell through to the generic `web` adapter (a `trafilatura` scrape of whatever
landing page the DOI resolves to, often a paywall) or stayed at `detected`.

Rather than write one bespoke adapter per remaining agency, this adapter
reaches them *all* at once through **DOI content negotiation**
(citation.crosscite.org/docs): a GET to `https://doi.org/<doi>` with
`Accept: application/vnd.citationstyles.csl+json` is proxied by the DOI
resolver to whichever agency holds the DOI, and every agency's
content-negotiation server answers with the same **CSL-JSON** document
(Citation Style Language JSON). One uniform format, every agency, no auth,
no runtime dependency — the agency-agnostic complement to the two rich
agency-specific adapters.

It is the *third* tier of the `sources/doi.py` dispatcher: only reached when
both Crossref's and DataCite's REST APIs 404 a DOI, so a Crossref or DataCite
DOI still gets its richer agency-specific scroll first (Crossref's subjects,
DataCite's resource type and container links), and this catches only the
long tail. Identity stays `crossref:<doi>` — the registration agency cannot
be read off the URL, item identity is fixed at `add` time, and
`provenance.adapter="content-negotiation"` records the agency-agnostic truth
of how the metadata was obtained, the way `datacite` records its agency.

CSL-JSON is the structural sibling of Crossref's REST JSON (ADR 0037) with a
few shape differences confirmed against the spec and live resolver:

1. **`title`/`container-title` are strings, not arrays.** Crossref's REST API
   wraps them in single-element arrays; CSL-JSON carries plain strings (but a
   list is still tolerated, so a quirky agency feed never crashes).

2. **Authors use `family`/`given`/`literal`.** A personal author renders
   "Given Family"; an institutional author carries `literal` (CSL's org slot,
   DataCite's organizational `name` analog).

3. **`type` is the CSL controlled vocabulary** (`article-journal`, `dataset`,
   `book`, …), recorded in `provenance.resource_type` so the rules engine can
   honor a `dataset`/`software` output while defaulting the scholarly common
   case to `paper` (classify.py, ADR 0045) — the way DataCite's
   `resourceTypeGeneral` drives its category.

The rest mirrors Crossref exactly: the `abstract` (possibly JATS/HTML) reduces
to a plain `summary`, `subject` → `concepts`, `type` + venue → `tags`, the
`URL` landing page → the one outgoing `link`, and a record with no abstract is
an honest metadata-only scroll (ADR 0002).
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

DOI_RESOLVER = "https://doi.org"

# The CSL-JSON media type every DOI registration agency's content-negotiation
# server understands (citation.crosscite.org/docs).
CSL_ACCEPT = "application/vnd.citationstyles.csl+json"

# Papers in some fields carry hundreds of authors; the `author` field is a
# display string, so a long list is truncated to a readable head + "et al."
_MAX_AUTHORS = 10

GetJson = Callable[[str], Any]

_TAG_RE = re.compile(r"<[^>]+>")
_LEAD_LABEL_RE = re.compile(r"^\s*(abstract|summary)\b[:.\s]*", re.IGNORECASE)


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a DOI's CSL-JSON via content negotiation; return it at 'fetched'.

    Raises FetchError when the DOI is missing, the request fails (the resolver
    404s an unregistered DOI, or the agency 406s the CSL-JSON media type), or
    the response is not a usable CSL document — so a misroute degrades to a
    benign failed fetch, never a wrong scroll. The input item is never mutated.
    """
    get_json = get_json or _default_get_json
    if not item.source_id:
        raise FetchError(f"cannot determine DOI for item {item.id!r}")

    url = f"{DOI_RESOLVER}/{quote(item.source_id, safe='/')}"
    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"DOI content negotiation request failed: {exc}") from exc

    if not isinstance(data, dict) or not _looks_like_csl(data):
        raise FetchError(f"work not found: {item.source_id}")

    doi = (_clean(data.get("DOI")) or item.source_id).lower()
    canonical_url = f"{DOI_RESOLVER}/{doi}"
    summary = _clean_abstract(data.get("abstract"))
    raw = json.dumps(
        {k: v for k, v in data.items() if k != "reference"}, ensure_ascii=False
    )
    hashed = summary or raw
    return replace(
        item,
        title=_title(data, doi),
        author=_authors(data),
        published_at=_published(data) or item.published_at,
        canonical_url=canonical_url,
        raw_text=raw,
        summary=summary,
        tags=_tags(data),
        concepts=_concepts(data),
        links=_links(data, canonical_url),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "content-negotiation",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "doi-content-negotiation:csl+json",
            # The category-determining fact, read at fetch time and consumed by
            # the rules engine (classify.py) — a content-negotiated DOI defaults
            # to `paper` but a dataset/software CSL type is honored (ADR 0045).
            "resource_type": _clean(data.get("type")) or "",
        },
        stage="fetched",
    )


def _default_get_json(url: str) -> Any:
    """The live transport: a content-negotiated GET asking for CSL-JSON."""
    return http.get_json(url, headers={"Accept": CSL_ACCEPT})


def _looks_like_csl(data: dict[str, Any]) -> bool:
    """True when the parsed body carries the marks of a CSL-JSON record.

    A valid CSL document always has a `type` and a `DOI`; requiring at least
    a `type`, a `DOI`, or a `title` rejects an HTML error page or an unrelated
    JSON that happened to parse, so a misroute raises rather than minting a
    junk scroll (the discourse/mastodon validate-before-scroll posture).
    """
    return bool(_clean(data.get("type")) or _clean(data.get("DOI")) or _text(data.get("title")))


def _clean(value: Any) -> str | None:
    """A non-empty trimmed string, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _str_list(value: Any) -> list[str]:
    """Non-empty trimmed strings from a list-valued field, in order."""
    if not isinstance(value, list):
        return []
    return [s for s in (_clean(v) for v in value) if s]


def _text(value: Any) -> str:
    """A CSL string field as plain text, tolerating a single-element array.

    CSL-JSON carries `title`/`container-title` as strings, but Crossref's REST
    JSON (and some agency feeds) wrap them in arrays, so both shapes collapse
    to one joined string — `""` when the field is absent.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(_str_list(value)).strip()
    return ""


def _title(data: dict[str, Any], doi: str) -> str | None:
    """The work's title, joined with its subtitle, falling back to venue then DOI."""
    main = _text(data.get("title"))
    subtitle = _text(data.get("subtitle"))
    if main and subtitle:
        main = f"{main}: {subtitle}"
    if main:
        return main
    container = _text(data.get("container-title"))
    return container or doi


def _authors(data: dict[str, Any]) -> str | None:
    """The CSL `author` list as a display string, truncated past `_MAX_AUTHORS`."""
    raw = data.get("author")
    if not isinstance(raw, list):
        return None
    names = [n for n in (_format_author(a) for a in raw if isinstance(a, dict)) if n]
    if not names:
        return None
    if len(names) > _MAX_AUTHORS:
        names = names[:_MAX_AUTHORS] + ["et al."]
    return ", ".join(names)


def _format_author(author: dict[str, Any]) -> str | None:
    """One CSL author as "Given Family", a `literal`/`name` org, or the bare part."""
    literal = _clean(author.get("literal")) or _clean(author.get("name"))
    given = _clean(author.get("given"))
    family = _clean(author.get("family"))
    if given and family:
        return f"{given} {family}"
    return family or given or literal


def _published(data: dict[str, Any]) -> str | None:
    """The publication date as UTC ISO 8601, by CSL date precedence.

    `issued` is CSL's canonical publication date; the rest are fallbacks down
    to `created` (the deposit timestamp), so a record missing the preferred
    field still dates the scroll.
    """
    for key in ("issued", "published", "published-online", "published-print", "created"):
        iso = _date_from(data.get(key))
        if iso:
            return iso
    return None


def _date_from(field: Any) -> str | None:
    """A CSL date object as UTC ISO 8601, or None.

    A CSL date carries `date-parts` `[[year, month?, day?]]` (a partial date
    pads missing month/day to 01 — invented precision, but `to_utc_iso` already
    makes date-only values midnight UTC for one uniform shape, ADR 0024), or a
    free-form `raw`/`literal` string when the agency couldn't structure it.
    """
    if not isinstance(field, dict):
        return None
    parts = field.get("date-parts")
    if isinstance(parts, list) and parts and isinstance(parts[0], list):
        nums = [n for n in parts[0] if isinstance(n, int) and not isinstance(n, bool)]
        if nums:
            year = nums[0]
            month = nums[1] if len(nums) > 1 else 1
            day = nums[2] if len(nums) > 2 else 1
            return to_utc_iso(f"{year:04d}-{month:02d}-{day:02d}")
    for key in ("raw", "literal", "date-time"):
        value = field.get(key)
        if isinstance(value, str):
            iso = to_utc_iso(value)
            if iso:
                return iso
    return None


def _clean_abstract(value: Any) -> str | None:
    """A CSL `abstract` reduced to plain text, or None.

    Mirrors Crossref's JATS cleaning (ADR 0037): some agencies deposit a JATS
    or HTML abstract, so tags are stripped (a tag becomes a space so block
    boundaries don't glue words), entities unescaped, whitespace collapsed, the
    space an inline tag leaves before punctuation removed, and a leading
    "Abstract" label dropped.
    """
    if not isinstance(value, str):
        return None
    text = html.unescape(_TAG_RE.sub(" ", value))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?)])", r"\1", text)
    text = _LEAD_LABEL_RE.sub("", text, count=1).strip()
    return text or None


def _concepts(data: dict[str, Any]) -> tuple[str, ...]:
    """CSL `subject` categories as deduped concepts (the github-topics parallel)."""
    return _dedupe(data.get("subject"))


def _tags(data: dict[str, Any]) -> tuple[str, ...]:
    """The CSL `type` and the publication venue as deduped tags.

    `type` is the controlled vocabulary (the slot arXiv's taxonomy codes and
    Crossref's `type` fill); the `container-title` (journal or proceedings)
    joins it so `scrolls related` can corroborate two works from the same venue.
    """
    container = _text(data.get("container-title"))
    return _dedupe([data.get("type"), container or None])


def _dedupe(values: Any) -> tuple[str, ...]:
    """Non-empty trimmed strings, order-preserving and deduped."""
    if not isinstance(values, list):
        return ()
    cleaned = (_clean(v) for v in values)
    return tuple(dict.fromkeys(v for v in cleaned if v))


def _links(data: dict[str, Any], canonical: str) -> tuple[str, ...]:
    """The CSL `URL` landing page as the one outgoing link, or none.

    Kept only when it is an http(s) URL distinct from the canonical doi.org
    link; CSL carries no reference list to bury it (ADR 0037).
    """
    url = _clean(data.get("URL"))
    if not url or not url.lower().startswith(("http://", "https://")):
        return ()
    if url.rstrip("/") == (canonical or "").rstrip("/"):
        return ()
    return (url,)
