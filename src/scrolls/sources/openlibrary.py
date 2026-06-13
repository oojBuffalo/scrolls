"""Open Library fetch adapter — books (ADR 0073).

A saved Open Library link — a work (`openlibrary.org/works/OL…W`), an edition
(`/books/OL…M`), or an ISBN (`/isbn/<isbn>`) — becomes a clean scroll from the
catalog's structured metadata instead of a `trafilatura` scrape of a
JS-rendered page. One keyless GET against the record's `.json` view returns the
book — no auth, no runtime dependency (the arXiv/Crossref discipline,
ADR 0008/0037).

Books are a content type with no prior first-class home: the code-host adapters
cover repos, the registries cover packages, arXiv/Crossref/PubMed cover papers,
RFCs cover standards — but a book was only ever a `web` island, concept-poor and
unlinked, the gap dev.to and RFCs had before ADR 0061/0066. Open Library is the
keyless, open bibliographic catalog (the Internet Archive's), so it is to books
what Crossref is to papers.

Open Library models books in the FRBR sense Scrolls' own `works` engine uses
(ADR 0069): a **work** is the abstract book, an **edition** a specific
manifestation, an **ISBN** names an edition. The adapter routes on the source id
the detector minted (ADR 0073):

- a work id (`OL…W`) → `GET /works/<OLID>.json`;
- an edition id (`OL…M`) → `GET /books/<OLID>.json`;
- an `isbn:<isbn>` id → `GET /isbn/<isbn>.json`, which Open Library 302-redirects
  to the edition record (urllib follows it), so the ISBN and edition paths share
  one normalizer.

Three platform facts shape the output:

1. **Subjects are the concepts.** Open Library's curated `subjects` become
   `concepts` — the github-topics/MeSH role (ADR 0007/0065) — the whole point of
   a dedicated adapter, wiring a book into `scrolls related`, the concept facets,
   and the KB concept graph a `web` scrape never could. Administrative subjects
   (`Accessible book`, `Open Library Staff Picks`, library-classification call
   numbers) are filtered out as noise, and the list is deduped case-insensitively
   and capped. Subjects live on the **work**, not the edition, so an edition/ISBN
   fetch follows its `works` ref with one extra GET to pull them (the two-request
   shape Bluesky/Stack Exchange/Hugging Face use); a missing or failed follow
   degrades to whatever subjects the edition itself carries.

2. **The description is the summary; there is no full text.** The blurb
   (`description`, a string or a `{value}` text object) becomes the searchable
   `summary` with **no `extracted_text`** — Open Library holds catalog metadata,
   not the book's body, so a book is honestly summary-only (the Crossref/PubMed
   metadata-only shape, ADR 0037/0065). Tags stay empty by design: a book has no
   clean controlled facet like an RFC's status or a package's license (the
   go/rubygems posture, ADR 0042/0040).

3. **Authors are references to resolve.** A record names authors by key
   (`/authors/OL…A`), not name, so each is resolved with a bounded GET to its
   `.json` `name` (capped, failures skipped) — the byline assembled the way an
   RFC's editor list is, degrading rather than failing.

The cover image (the first present `covers` id, Open Library's `-1` "no cover"
sentinel skipped) becomes a `thumbnail` media ref pointing at
`covers.openlibrary.org` (the youtube/Discourse convention, ADR 0011). An
edition links to its work (`/works/<OLID>`, the edition↔work edge `scrolls
related`/`graph` resolves when both are saved), and a work's external `links`
become outbound edges. The raw record is kept in `raw_text` for rebuilds.

No platform category is assigned: Open Library spans fiction and non-fiction, so
forcing `reference` (right for a textbook) would be dishonest for a novel — the
honesty value that keeps a medRxiv paper off the `biorxiv` label (ADR 0068/0045).
A book flows through the title rules (a "How to" → tutorial) and otherwise stays
honestly unclassified — Hacker News's posture (ADR 0031), not a guessed default.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

SITE = "https://openlibrary.org"
COVERS = "https://covers.openlibrary.org/b/id"

GetJson = Callable[[str], Any]

# A book rarely has many authors; a long editor list (an anthology) is truncated
# to a readable head + "et al." (the RFC/Crossref cap).
_MAX_AUTHORS = 10
# Subjects feed the concept graph, so the list is capped to keep one over-tagged
# book from swamping a concept page.
_MAX_SUBJECTS = 30

# Open Library mixes real topics into `subjects` with administrative and
# accessibility flags (and library-classification call numbers); these are noise
# in the concept graph, so they are dropped. Matched case-insensitively, exactly
# — not as a prefix, so a real subject like "In library science" survives the
# "In library" flag.
_SUBJECT_STOPWORDS = frozenset(
    s.lower()
    for s in (
        "Accessible book",
        "Protected DAISY",
        "In library",
        "Open Library Staff Picks",
        "Internet Archive Wishlist",
        "Lending library",
        "OverDrive",
        "Large type books",
        "New York Times bestseller",
    )
)
# Flags Open Library mints with a variable tail (a reading-level grade, a Lexile
# score, an `nyt:` namespaced tag); matched as a case-insensitive prefix.
_SUBJECT_STOP_PREFIXES = ("nyt:", "reading level", "lexile")
# A Library of Congress / Dewey call number ("Pz7.d1515 Fan", "Aa76.73.p98")
# looks like a subject in the data but is a shelf code, not a topic — dropped.
# The dotted shape (1–3 letters, digits, then a `.`) is required so a real
# subject like "U2 (Musical group)" or "A1 Steak Sauce" (letters+digit, no dot)
# survives — the call number always carries a cutter dot, a band name does not.
_CALL_NUMBER_RE = re.compile(r"^[A-Za-z]{1,3}\d+\.", re.ASCII)

# English month names + their abbreviations → number, so `publish_date` parsing
# is locale-independent (strptime's %B follows LC_TIME). A token is treated as a
# month only when the *whole word* is a name or abbreviation here, so an ordinary
# word that merely starts with three month letters ("Mayflower", "Octopus") is
# not misread as a month.
_MONTH_NAMES = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)
_MONTHS = {"sept": 9}
for _index, _name in enumerate(_MONTH_NAMES, start=1):
    _MONTHS[_name] = _index
    _MONTHS[_name[:3]] = _index


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected Open Library book; return it at stage 'fetched'.

    Routes on the source id the detector minted: a work id (`OL…W`) reads the
    `/works` record, an edition id (`OL…M`) the `/books` record, and an
    `isbn:<isbn>` id the `/isbn` record (which redirects to the edition). Raises
    FetchError when the id is missing/unrecognized, the request fails, or the
    response is not a usable book record. Author resolution and the edition's
    subject follow-up degrade rather than fail. The input item is never mutated.
    """
    get_json = get_json or _get_json
    source_id = item.source_id or ""
    if not source_id:
        raise FetchError(f"cannot determine Open Library book for item {item.id!r}")

    if source_id.startswith("isbn:"):
        url = f"{SITE}/isbn/{source_id[len('isbn:'):]}.json"
        kind = "isbn"
    elif source_id.endswith("W"):
        url = f"{SITE}/works/{source_id}.json"
        kind = "work"
    elif source_id.endswith("M"):
        url = f"{SITE}/books/{source_id}.json"
        kind = "edition"
    else:
        raise FetchError(f"unrecognized Open Library id {source_id!r}")

    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"Open Library API request failed: {exc}") from exc
    if not isinstance(data, dict) or not (data.get("title") or data.get("key")):
        raise FetchError(f"Open Library record not found: {source_id}")

    # For a work/edition the source id *is* the OLID, a fallback when a record
    # omits its `key`; an ISBN id is not an OLID, so it stays None (the canonical
    # then falls back to the `/isbn` URL).
    olid = _olid_from_key(data.get("key")) or (
        source_id if kind in ("work", "edition") else None
    )
    is_work = kind == "work"
    concepts = (
        _clean_subjects(data.get("subjects"))
        if is_work
        else _edition_concepts(data, get_json)
    )
    summary = _description(data.get("description"))
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    hashed = summary or raw
    return replace(
        item,
        title=_clean(data.get("title")) or item.title,
        author=_authors(data, get_json),
        published_at=_published(
            data.get("first_publish_date") if is_work else data.get("publish_date")
        )
        or item.published_at,
        canonical_url=_canonical(kind, olid, source_id),
        raw_text=raw,
        extracted_text=None,  # the catalog holds metadata, not the book's body
        summary=summary,
        concepts=concepts,
        links=_links(data, is_work),
        media=_media(data),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "openlibrary",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": f"openlibrary:{kind}",
        },
        stage="fetched",
    )


def _canonical(kind: str, olid: str | None, source_id: str) -> str | None:
    """The book's canonical Open Library URL for its kind.

    A work canonicalizes to `/works/<OLID>`; an edition or ISBN to the edition's
    `/books/<OLID>` — the ISBN form reads the edition OLID back from the record's
    `key`, so a `/isbn/<isbn>` save canonicalizes to the stable edition page (the
    crossref read-canonical-back pattern, ADR 0037). An ISBN whose record carried
    no `key` falls back to the `/isbn` URL.
    """
    if kind == "work" and olid:
        return f"{SITE}/works/{olid}"
    if olid:
        return f"{SITE}/books/{olid}"
    if kind == "isbn":
        return f"{SITE}/isbn/{source_id[len('isbn:'):]}"
    return None


def _authors(data: dict[str, Any], get_json: GetJson) -> str | None:
    """The byline, resolving each author key to its name (bounded, degrading).

    A record names authors by reference only (`/authors/OL…A`), in two shapes:
    a work nests the key under `author` (`{"author": {"key": …}}`), an edition
    lists it flat (`{"key": …}`). Each key (capped at `_MAX_AUTHORS`) is resolved
    with one GET to its `.json` `name`; a failed or nameless lookup is skipped, so
    a byline degrades to the names that resolved rather than failing the fetch.
    """
    keys: list[str] = []
    for entry in _as_list(data.get("authors")):
        if not isinstance(entry, dict):
            continue
        ref = entry.get("author") if isinstance(entry.get("author"), dict) else entry
        key = ref.get("key") if isinstance(ref, dict) else None
        if isinstance(key, str) and key.startswith("/authors/"):
            keys.append(key)
    keys = list(dict.fromkeys(keys))  # a record may list one contributor twice

    names: list[str] = []
    for key in keys[:_MAX_AUTHORS]:
        try:
            record = get_json(f"{SITE}{key}.json")
        except Exception:  # an author lookup failure must not fail the book
            continue
        name = _clean(record.get("name")) if isinstance(record, dict) else None
        if name:
            names.append(name)
    if not names:
        return None
    if len(keys) > _MAX_AUTHORS:
        names = names + ["et al."]
    return ", ".join(names)


def _edition_concepts(data: dict[str, Any], get_json: GetJson) -> tuple:
    """Concepts for an edition/ISBN record: its own subjects, else the work's.

    An edition rarely carries `subjects` (they live on the work), so when it has
    none the adapter follows the edition's first `works` ref with one extra GET
    and reads the work's subjects — the two-request enrichment Bluesky/Stack
    Exchange use. A missing ref or a failed follow degrades to the edition's own
    (usually empty) subjects rather than failing the fetch.
    """
    own = _clean_subjects(data.get("subjects"))
    if own:
        return own
    works = _as_list(data.get("works"))
    key = works[0].get("key") if works and isinstance(works[0], dict) else None
    if not (isinstance(key, str) and key.startswith("/works/")):
        return own
    try:
        work = get_json(f"{SITE}{key}.json")
    except Exception:  # the subject follow-up is enrichment, never fatal
        return own
    return _clean_subjects(work.get("subjects")) if isinstance(work, dict) else own


def _clean_subjects(value: Any) -> tuple:
    """Topical subjects: stopword- and call-number-filtered, deduped, capped.

    Administrative/accessibility flags and library call numbers are dropped as
    concept-graph noise; the rest are deduped case-insensitively (first spelling
    wins) and capped at `_MAX_SUBJECTS` so an over-tagged book can't swamp a
    concept page.
    """
    seen: dict[str, str] = {}
    for raw in _as_list(value):
        subject = _clean(raw)
        if not subject:
            continue
        lowered = subject.lower()
        if lowered in _SUBJECT_STOPWORDS or _CALL_NUMBER_RE.match(subject):
            continue
        if any(lowered.startswith(prefix) for prefix in _SUBJECT_STOP_PREFIXES):
            continue
        seen.setdefault(lowered, subject)
        if len(seen) >= _MAX_SUBJECTS:
            break
    return tuple(seen.values())


def _links(data: dict[str, Any], is_work: bool) -> tuple:
    """A book's outbound edges: an edition→work link, plus any external links.

    An edition links to its work (`/works/<OLID>`) — the edition↔work edge
    `scrolls related`/`graph` resolves to the work's scroll when both are saved
    (the RFC↔RFC intra-source edge, ADR 0066). A record's curated external
    `links` (`{"url": …}` objects, Open Library lets a work carry them) become
    outbound edges too — a book pointing at an author site or a related resource.
    Deduped, order preserved.
    """
    links: list[str] = []
    if not is_work:
        works = _as_list(data.get("works"))
        key = works[0].get("key") if works and isinstance(works[0], dict) else None
        if isinstance(key, str) and key.startswith("/works/"):
            links.append(f"{SITE}{key}")
    for entry in _as_list(data.get("links")):
        url = entry.get("url") if isinstance(entry, dict) else None
        cleaned = _clean(url)
        if cleaned:
            links.append(cleaned)
    return tuple(dict.fromkeys(links))


def _media(data: dict[str, Any]) -> tuple:
    """The cover image as a single `thumbnail` media ref, else ().

    `covers` is a list of cover ids ordered best-first, with `-1` as the "no
    cover" sentinel; the first present (positive) id becomes a `thumbnail` (the
    youtube/Discourse preview convention, ADR 0011) at
    `covers.openlibrary.org/b/id/<id>-L.jpg` — an absolute CDN URL the capture
    step can localize.
    """
    for cover in _as_list(data.get("covers")):
        if isinstance(cover, int) and cover > 0:
            return ({"type": "thumbnail", "url": f"{COVERS}/{cover}-L.jpg"},)
    return ()


def _description(value: Any) -> str | None:
    """The blurb as a whitespace-collapsed summary, or None.

    Open Library stores `description` as either a plain string or a typed text
    object (`{"type": "/type/text", "value": "…"}`); both reduce to the same
    searchable summary. There is no `extracted_text` — the catalog holds no full
    text (the Crossref/PubMed shape, ADR 0037/0065).
    """
    if isinstance(value, dict):
        value = value.get("value")
    return _clean_text(value)


def _published(value: Any) -> str | None:
    """An Open Library date as UTC ISO 8601, or None.

    Edition `publish_date` is free-form ("Aug 20, 2015", "August 2015", "2015"),
    work `first_publish_date` similar; an ISO date passes straight through, an
    `YYYY-MM` pads to the first of the month, and a textual date is parsed from a
    four-digit year plus an optional month name and day. Missing parts pad to the
    start of the period — invented precision for one uniform shape (the RFC/
    Crossref partial-date rule, ADR 0024). An unparseable value yields None.
    """
    text = _clean(value)
    if not text:
        return None
    iso = to_utc_iso(text)
    if iso:
        return iso
    # An ISO-shaped value to_utc_iso rejected (an impossible day like `2015-02-30`,
    # or a dayless `2015-09`): keep the year and month, dropping only the bad day,
    # rather than re-scanning the digits as free text.
    iso_shape = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", text)
    if iso_shape:
        year, month = int(iso_shape.group(1)), int(iso_shape.group(2))
        if not 1 <= month <= 12:
            month = 1
        return _pad(year, month, int(iso_shape.group(3) or 1))
    # A textual date: a four-digit year, with an optional whole-word month name
    # and a day taken only when a month was actually found (so "August 2015" → the
    # 1st, but "Mayflower Press, 2016" degrades to the start of the year, not May).
    year_match = re.search(r"\b(\d{4})\b", text)
    if not year_match:
        return None
    year = int(year_match.group(1))
    month = _month_in(text)
    if month is None:
        return _pad(year, 1, 1)
    rest = text[: year_match.start()] + text[year_match.end() :]
    day_match = re.search(r"\b(\d{1,2})\b", rest)
    return _pad(year, month, int(day_match.group(1)) if day_match else 1)


def _month_in(text: str) -> int | None:
    """The first whole-word month name/abbreviation in `text`, else None."""
    for token in re.findall(r"[A-Za-z]+", text):
        month = _MONTHS.get(token.lower())
        if month is not None:
            return month
    return None


def _pad(year: int, month: int, day: int) -> str | None:
    """`year-month-day` as UTC ISO, falling back to the 1st when the day is bad."""
    return to_utc_iso(f"{year:04d}-{month:02d}-{day:02d}") or to_utc_iso(
        f"{year:04d}-{month:02d}-01"
    )


def _olid_from_key(key: Any) -> str | None:
    """The OLID from a record `key` (`/works/OL…W`, `/books/OL…M`), else None."""
    if isinstance(key, str):
        parts = [p for p in key.split("/") if p]
        if len(parts) == 2 and parts[0] in ("works", "books"):
            return parts[1]
    return None


def _clean(value: Any) -> str | None:
    """A non-empty trimmed string, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _clean_text(value: Any) -> str | None:
    """A whitespace-collapsed string, or None for absent/whitespace-only text."""
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text or None


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


_get_json = http.get_json
