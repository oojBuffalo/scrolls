"""bioRxiv / medRxiv fetch adapter (IDEAS.md §6, ADR 0068).

One GET against the keyless `api.biorxiv.org/details/<server>/<doi>`
endpoint returns a preprint's metadata as JSON, parsed with stdlib `json`
— no auth, no runtime dependency, the arXiv adapter's discipline (ADR
0008). bioRxiv (biology) and medRxiv (health sciences) are sibling
preprint servers run by one operator (Cold Spring Harbor Laboratory) on
one shared API that differs only by the `<server>` path segment, so a
*single* adapter serves both, reading `item.source` to pick the server —
yet they stay two distinct sources, because a medRxiv paper does not live
on bioRxiv (ADR 0068). They are the preprint-server siblings of arXiv: the
fastest-moving feeds of un-peer-reviewed biology and medicine.

Three facts shape the design, confirmed against the live API:

1. **The latest version is the scroll.** A preprint accrues versions
   (`v1`, `v2`, …), returned as an ascending `collection` array under one
   DOI; the highest-numbered entry is the current preprint, so the adapter
   reads its fields and dedupes every version URL to one item (the arXiv
   `abs`/`pdf` dedupe, ADR 0008).

2. **The abstract is the content; there is no full text.** The API serves
   metadata and the abstract, not the body (the JATS full text exists but
   behind a separate fetch and an anti-bot wall), so the abstract is the
   searchable `summary` with no `extracted_text` — the Crossref/PubMed
   shape (ADR 0037, ADR 0065). The PDF is likewise *not* a media ref: the
   `.full.pdf` URL 403s an unauthenticated client, so a captured ref would
   only ever fail; an honest metadata-only scroll beats a broken link
   (ADR 0002, ADR 0011).

3. **The published DOI is the cross-source edge.** When a preprint has
   been published in a journal the API carries the published DOI; the
   resulting `https://doi.org/<doi>` link resolves (through source
   detection in `related`/`graph`) to the `crossref:<doi>` item a saved
   DOI mints — the preprint↔published edge, exactly arXiv's `arxiv:doi`
   link (ADR 0038). An unpublished preprint (`published == "NA"`) is
   honestly empty.

The single subject `category` (`microbiology`, `epidemiology`) becomes the
one `concept`, the curated-vocabulary slot github topics and arXiv taxonomy
names fill (ADR 0007, ADR 0012); the study `type` (`new results`,
`confirmatory results`), the server name as the venue, and a recognized CC
`license` become `tags`, the controlled-facet slot arXiv's taxonomy codes
fill. A preprint classifies as `paper` like an arXiv one (ADR 0004). The
chosen version's raw record is kept in `raw_text` so the scroll can be
rebuilt without refetching.
"""

from __future__ import annotations

import hashlib
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

API_ROOT = "https://api.biorxiv.org/details"
DOI_RESOLVER = "https://doi.org"

# Genomics/consortium preprints can carry hundreds of authors; `author` is a
# display string, so a long list keeps a readable head and appends "et al." —
# the Crossref/PubMed rule (ADR 0037, ADR 0065).
_MAX_AUTHORS = 10

# bioRxiv/medRxiv license codes → their canonical CC tag. `cc_no` ("no reuse
# without permission" — i.e. all rights reserved) is not a CC license and is
# deliberately absent, so it produces no tag rather than a misleading one.
_LICENSES = {
    "cc_by": "CC-BY",
    "cc_by_sa": "CC-BY-SA",
    "cc_by_nc": "CC-BY-NC",
    "cc_by_nd": "CC-BY-ND",
    "cc_by_nc_sa": "CC-BY-NC-SA",
    "cc_by_nc_nd": "CC-BY-NC-ND",
    "cc0": "CC0",
}

GetJson = Callable[[str], Any]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected bioRxiv/medRxiv preprint's metadata; return it 'fetched'.

    The server (`biorxiv` or `medrxiv`) is read off `item.source`, so one
    adapter serves both. Raises FetchError when the DOI is missing, the
    request fails, the response does not parse, or the DOI is unknown (an
    empty `collection`). Abstract/published-DOI absences never raise — the
    scroll degrades gracefully (ADR 0002). The input item is never mutated.
    """
    get_json = get_json or _get_json
    server = item.source  # "biorxiv" or "medrxiv"
    if not item.source_id:
        raise FetchError(f"cannot determine DOI for item {item.id!r}")

    url = f"{API_ROOT}/{server}/{quote(item.source_id, safe='/')}"
    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"bioRxiv API request failed: {exc}") from exc

    record = _latest_version(data)
    if record is None:
        raise FetchError(f"preprint not found: {item.source_id}")

    doi = _clean(record.get("doi")) or item.source_id
    version = _clean(record.get("version")) or "1"
    summary = _abstract(record.get("abstract"))
    raw = json.dumps(record, ensure_ascii=False)
    hashed = summary or raw
    return replace(
        item,
        title=_clean(record.get("title")) or item.title or doi,
        author=_authors(record.get("authors")),
        published_at=to_utc_iso(_clean(record.get("date"))) or item.published_at,
        canonical_url=f"https://www.{server}.org/content/{doi}v{version}",
        raw_text=raw,
        summary=summary,
        tags=_tags(record),
        concepts=_concepts(record),
        links=_published_links(record),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": server,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "biorxiv-api:json",
        },
        stage="fetched",
    )


def _latest_version(data: Any) -> dict[str, Any] | None:
    """The highest-numbered entry in the response's `collection`, or None.

    The API returns one entry per preprint version; the current preprint is
    the highest `version`. An unknown DOI returns an empty `collection`
    (with a "no posts found"/"DOI not recognizable" message), so an empty
    or malformed payload yields None — the caller's FetchError.
    """
    collection = data.get("collection") if isinstance(data, dict) else None
    versions = [c for c in collection or [] if isinstance(c, dict)]
    if not versions:
        return None
    return max(versions, key=_version_number)


def _version_number(record: dict[str, Any]) -> int:
    """A record's integer version, defaulting to 0 for a missing/odd value."""
    version = _clean(record.get("version"))
    return int(version) if version and version.isdigit() else 0


def _clean(value: Any) -> str | None:
    """A non-empty trimmed string, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _abstract(value: Any) -> str | None:
    """The abstract as one whitespace-collapsed line, or None.

    bioRxiv abstracts arrive as plain text with embedded section headers
    (`Importance…`) and `\\n\\n` breaks; collapsing whitespace keeps the whole
    abstract one searchable `summary` field, the Crossref/PubMed shape. A
    preprint with no abstract degrades to a metadata-only scroll (ADR 0002).
    """
    text = _clean(value)
    return re.sub(r"\s+", " ", text) if text else None


def _authors(value: Any) -> str | None:
    """The author list as a display string, truncated past `_MAX_AUTHORS`.

    The API gives authors as a `; `-joined `Family, G. I.` string; each is
    reordered to `G. I. Family` (the Crossref/PubMed "Given Family" order) and
    a list longer than the cap keeps its head and appends "et al." so a
    hundred-author consortium preprint does not produce a hundred-name field.
    """
    text = _clean(value)
    if not text:
        return None
    names = [n for n in (_format_author(a) for a in text.split(";")) if n]
    if not names:
        return None
    if len(names) > _MAX_AUTHORS:
        names = names[:_MAX_AUTHORS] + ["et al."]
    return ", ".join(names)


def _format_author(author: str) -> str | None:
    """One `Family, Given` author as `Given Family`, or the bare name."""
    author = author.strip()
    if "," in author:
        family, _, given = author.partition(",")
        family, given = family.strip(), given.strip()
        if family and given:
            return f"{given} {family}"
        return family or given or None
    return author or None


def _concepts(record: dict[str, Any]) -> tuple[str, ...]:
    """The subject `category` as the one concept (sentence-cased), or empty.

    bioRxiv/medRxiv tag each preprint with a single subject area
    (`microbiology`, `infectious diseases`); it joins the KB concept graph the
    way github topics and arXiv taxonomy names do (ADR 0007, ADR 0012). Only
    the first letter is upper-cased so acronyms a category carries
    (`HIV/AIDS`) survive, and the KB merges spellings by slug regardless.
    """
    category = _clean(record.get("category"))
    if not category:
        return ()
    return (category[0].upper() + category[1:],)


def _tags(record: dict[str, Any]) -> tuple[str, ...]:
    """The study type, the server (venue), and a CC license as deduped tags.

    The `type` (`new results`, `confirmatory results`, `contradictory
    results`) is title-cased, but only when it reads as a real type — a
    space-bearing phrase — so a sentinel token like medRxiv's
    `PUBLISHAHEADOFPRINT` is dropped rather than tagged. The `server`
    (`bioRxiv`/`medRxiv`) is the venue, the controlled-facet slot a journal
    name fills for Crossref/PubMed (ADR 0037, ADR 0065); a recognized CC
    `license` joins it, the code mapped to its canonical form.
    """
    tags: list[str | None] = []
    study_type = _clean(record.get("type"))
    if study_type and " " in study_type:
        tags.append(study_type.title())
    tags.append(_clean(record.get("server")))
    license_code = (_clean(record.get("license")) or "").lower()
    tags.append(_LICENSES.get(license_code))
    return tuple(dict.fromkeys(t for t in tags if t))


def _published_links(record: dict[str, Any]) -> tuple[str, ...]:
    """The published-journal DOI as a `doi.org` link, or empty.

    The `published` field carries the DOI of the peer-reviewed journal
    article a preprint became, or the sentinel `"NA"` while it is still a
    preprint. A real DOI becomes a `https://doi.org/<doi>` link that resolves
    (through source detection) to the `crossref:<doi>` item — the
    preprint↔published edge, arXiv's `arxiv:doi` analog (ADR 0038).
    """
    published = _clean(record.get("published"))
    if not published or published.upper() == "NA":
        return ()
    return (f"{DOI_RESOLVER}/{published}",)


_get_json = http.get_json
