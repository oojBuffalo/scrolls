"""Crossref / DOI fetch adapter (IDEAS.md §6, ADR 0037).

A saved `doi.org/<doi>` link becomes a clean scroll from the work's
registered metadata instead of a `trafilatura` scrape of whichever
publisher page the DOI happens to resolve to (often a paywall). One GET
against the keyless Crossref REST API (`api.crossref.org/works/<doi>`)
returns the work's metadata document — no auth, no runtime dependency.
This is the published-literature sibling of the arXiv adapter (ADR 0008):
arXiv covers preprints, Crossref covers the journal articles, books,
conference papers, and datasets that carry a DOI.

Three facts shape the design, confirmed against the live API:

1. **Identity is the DOI, folded.** DOIs are case-insensitive (the DOI
   Handbook §2.4) and Crossref stores them lowercased, so the detected
   source id is lowercased — `doi.org/10.1145/X`, the legacy
   `dx.doi.org/10.1145/X`, and case variants all dedupe to one item. The
   canonical DOI (which the response echoes back) builds the canonical
   `https://doi.org/<doi>` URL, so a folded id never breaks the fetch.

2. **The abstract is JATS XML, when it exists at all.** Crossref carries
   no full text, only metadata, so the abstract is the searchable
   content — but it arrives as JATS markup (`<jats:p>…</jats:p>`, often
   led by a `<jats:title>Abstract</jats:title>`). The adapter strips the
   tags, unescapes entities, and drops the leading "Abstract" label to a
   plain `summary`. Many records have no abstract (and Crossref largely
   stopped collecting `subject` keywords), so a metadata-only scroll —
   title, authors, venue, date — is the honest common case (ADR 0002).

3. **References are not links.** A work's `reference` array can run to
   hundreds of cited DOIs; dumping them as `links` would bury the one
   edge that matters. Only the publisher's direct landing page
   (`resource.primary.URL`) becomes a link, and the `reference` array is
   dropped from `raw_text` to bound its size.

Author-declared `subject` categories become `concepts` the way github
repo topics do (ADR 0007); the work `type` (`journal-article`,
`proceedings-article`, …) and its publication venue become `tags`, the
controlled-facet slot arXiv's taxonomy codes fill (ADR 0008); and the
publisher landing page becomes the one outgoing `link`. A Crossref work
classifies as `paper` like an arXiv one (ADR 0004).
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

API_ROOT = "https://api.crossref.org/works"
DOI_RESOLVER = "https://doi.org"

# Papers in some fields carry hundreds of authors; the `author` field is a
# display string, so a long list is truncated to a readable head + "et al."
_MAX_AUTHORS = 10

GetJson = Callable[[str], Any]

_TAG_RE = re.compile(r"<[^>]+>")
_LEAD_LABEL_RE = re.compile(r"^\s*(abstract|summary)\b[:.\s]*", re.IGNORECASE)


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected DOI's Crossref metadata; return it at stage 'fetched'.

    Raises FetchError when the DOI is missing, the request fails, or the
    DOI is not registered with Crossref (a DataCite-only dataset DOI, for
    instance, 404s here). The input item is never mutated.
    """
    get_json = get_json or _get_json
    if not item.source_id:
        raise FetchError(f"cannot determine DOI for item {item.id!r}")

    url = f"{API_ROOT}/{quote(item.source_id, safe='/')}"
    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"Crossref API request failed: {exc}") from exc

    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, dict) or data.get("status") != "ok":
        raise FetchError(f"work not found: {item.source_id}")

    doi = _clean(message.get("DOI")) or item.source_id
    canonical_url = f"{DOI_RESOLVER}/{doi}"
    summary = _clean_abstract(message.get("abstract"))
    raw = json.dumps(
        {k: v for k, v in message.items() if k != "reference"}, ensure_ascii=False
    )
    hashed = summary or raw
    return replace(
        item,
        title=_title(message, doi),
        author=_authors(message),
        published_at=_published(message) or item.published_at,
        canonical_url=canonical_url,
        raw_text=raw,
        summary=summary,
        tags=_tags(message),
        concepts=_concepts(message),
        links=_links(message, canonical_url),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "crossref",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "crossref-api:json",
        },
        stage="fetched",
    )


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


def _title(message: dict[str, Any], doi: str) -> str | None:
    """The work's title, joined with its subtitle, falling back to venue then DOI.

    Crossref splits `title` and `subtitle` into arrays (usually one element
    each). They are joined `Title: Subtitle`; a work with no title at all
    (rare, but possible for a stub record) falls back to its container
    title and finally the DOI, so the scroll is never untitled.
    """
    main = " ".join(_str_list(message.get("title"))).strip()
    subtitle = " ".join(_str_list(message.get("subtitle"))).strip()
    if main and subtitle:
        main = f"{main}: {subtitle}"
    if main:
        return main
    containers = _str_list(message.get("container-title"))
    return containers[0] if containers else doi


def _authors(message: dict[str, Any]) -> str | None:
    """The author list as a display string, truncated past `_MAX_AUTHORS`.

    Each Crossref author is `{given, family}` for a person or `{name}` for
    an organization; people render "Given Family". A list longer than the
    cap keeps its head and appends "et al." so a 200-author physics paper
    does not produce a 200-name author field.
    """
    raw = message.get("author")
    if not isinstance(raw, list):
        return None
    names = [n for n in (_format_author(a) for a in raw if isinstance(a, dict)) if n]
    if not names:
        return None
    if len(names) > _MAX_AUTHORS:
        names = names[:_MAX_AUTHORS] + ["et al."]
    return ", ".join(names)


def _format_author(author: dict[str, Any]) -> str | None:
    """One author as "Given Family", the bare family/given, or an org name."""
    org = _clean(author.get("name"))
    if org:
        return org
    given = _clean(author.get("given"))
    family = _clean(author.get("family"))
    if given and family:
        return f"{given} {family}"
    return family or given


def _published(message: dict[str, Any]) -> str | None:
    """The work's publication date as UTC ISO 8601, by Crossref date precedence.

    `issued` is Crossref's canonical "date this was published"; the rest
    are fallbacks down to `created` (the record's registration date), so a
    record missing the preferred field still dates the scroll.
    """
    for key in ("issued", "published", "published-online", "published-print", "created"):
        iso = _date_from(message.get(key))
        if iso:
            return iso
    return None


def _date_from(field: Any) -> str | None:
    """A Crossref date field as UTC ISO 8601, or None.

    A field may carry a full `date-time` string (used verbatim) or only
    `date-parts` `[[year, month?, day?]]`. A partial date pads missing
    month/day to 01 — invented precision, but `dates.to_utc_iso` already
    makes date-only values midnight UTC for one uniform shape (ADR 0024).
    """
    if not isinstance(field, dict):
        return None
    iso = to_utc_iso(field.get("date-time")) if isinstance(field.get("date-time"), str) else None
    if iso:
        return iso
    parts = field.get("date-parts")
    if isinstance(parts, list) and parts and isinstance(parts[0], list):
        nums = [n for n in parts[0] if isinstance(n, int)]
        if nums:
            year = nums[0]
            month = nums[1] if len(nums) > 1 else 1
            day = nums[2] if len(nums) > 2 else 1
            return to_utc_iso(f"{year:04d}-{month:02d}-{day:02d}")
    return None


def _clean_abstract(value: Any) -> str | None:
    """A Crossref JATS abstract reduced to plain text, or None.

    Strips JATS/HTML tags, unescapes entities, collapses whitespace, and
    drops a leading "Abstract"/"Summary" label left by `<jats:title>`. Tags
    become a space so block boundaries don't glue words together; the space
    a *inline* tag leaves before following punctuation is then removed, so
    `propose <jats:italic>node2vec</jats:italic>, a` reads `node2vec, a`.
    """
    if not isinstance(value, str):
        return None
    text = html.unescape(_TAG_RE.sub(" ", value))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?)])", r"\1", text)
    text = _LEAD_LABEL_RE.sub("", text, count=1).strip()
    return text or None


def _concepts(message: dict[str, Any]) -> tuple[str, ...]:
    """Crossref `subject` categories as deduped concepts (the github-topics parallel).

    Crossref largely stopped collecting subjects, so this is empty for most
    modern records — honestly empty rather than guessed.
    """
    return _dedupe(message.get("subject"))


def _tags(message: dict[str, Any]) -> tuple[str, ...]:
    """The work `type` and its publication venue as deduped tags.

    `type` is a controlled vocabulary (`journal-article`,
    `proceedings-article`, `book-chapter`, `dataset`, …) — the structured
    facet arXiv's taxonomy codes fill. The `container-title` (journal or
    conference proceedings) joins it so `scrolls related` can corroborate
    two works from the same venue; KB pages are built per concept, not per
    tag, so a long venue name here costs nothing.
    """
    return _dedupe([message.get("type"), *_str_list(message.get("container-title"))])


def _dedupe(values: Any) -> tuple[str, ...]:
    """Non-empty trimmed strings, order-preserving and deduped."""
    if not isinstance(values, list):
        return ()
    cleaned = (_clean(v) for v in values)
    return tuple(dict.fromkeys(v for v in cleaned if v))


def _links(message: dict[str, Any], canonical: str) -> tuple[str, ...]:
    """The publisher's direct landing page as the one outgoing link, or none.

    `resource.primary.URL` is the page the DOI resolves to; it is kept only
    when it is an http(s) URL distinct from the canonical doi.org link. The
    `reference` array (cited DOIs) is deliberately not turned into links.
    """
    resource = message.get("resource")
    primary = resource.get("primary") if isinstance(resource, dict) else None
    url = _clean(primary.get("URL")) if isinstance(primary, dict) else None
    if not url or not url.lower().startswith(("http://", "https://")):
        return ()
    if url.rstrip("/") == (canonical or "").rstrip("/"):
        return ()
    return (url,)


_get_json = http.get_json
