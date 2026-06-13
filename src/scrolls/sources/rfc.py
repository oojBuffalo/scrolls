"""RFC fetch adapter — IETF Requests for Comments (ADR 0066).

A saved RFC link — `rfc-editor.org/rfc/rfc<N>`, `datatracker.ietf.org/doc/rfc<N>`,
the legacy `tools.ietf.org/html/rfc<N>`, or `ietf.org/rfc/rfc<N>.txt` — becomes a
clean scroll from the RFC's published bibliographic metadata instead of a
`trafilatura` scrape of the spec's text. One keyless GET against the RFC Editor's
JSON view (`https://www.rfc-editor.org/rfc/rfc<N>.json`) returns the record — no
auth, no runtime dependency (the arXiv/Crossref discipline, ADR 0008/0037).

RFCs are technical *standards*, a content type with no prior first-class home: the
code-host adapters cover repos, the registries cover packages, arXiv/Crossref/
PubMed cover papers, but a normative protocol spec (HTTP, TLS, JSON, OAuth) was
only ever a `web` island — concept-poor and unlinked, the gap dev.to had before
ADR 0061. Three platform facts and two cross-document edges shape the design:

1. **Identity is the integer RFC number.** `rfc:9110`, leading zeros stripped, so
   the canonical `rfc9110` and the zero-padded `rfc0020` filename form dedupe. The
   number leads the title (`RFC 9110: HTTP Semantics`) because an RFC's canonical
   name *is* its number — agents search "RFC 9110" — so the number belongs in the
   FTS-weighted title and the scroll slug, not only the id.

2. **Keywords are the concepts; the status is the controlled-facet tag.** The RFC
   Editor's curated `keywords` become `concepts` (the github-topics/MeSH role,
   ADR 0007/0065) — many RFCs carry none (older ones store a whitespace-only
   placeholder, dropped), so a keyword-less RFC is honestly concept-light. The
   maturity `status` (`PROPOSED STANDARD`, `INTERNET STANDARD`, `INFORMATIONAL`,
   …) is title-cased into the one `tag`, the controlled facet Crossref's `type`
   fills (ADR 0037).

3. **The abstract is the content; there is no full text.** The RFC body is
   published separately (the `.txt`/`.html` a reader opens); the JSON view carries
   only the abstract, so it is the searchable `summary` with **no
   `extracted_text`** — the Crossref/PubMed shape (ADR 0037/0065). A record with
   no abstract degrades to a metadata-only scroll (ADR 0002), not a `FetchError`.

The two edges: the RFC's own DOI (`10.17487/RFC<N>`, registered with Crossref)
becomes a `doi.org` link resolving to its `crossref:<doi>` scroll — the
RFC↔Crossref edge, kin to arXiv's preprint↔published edge (ADR 0038); and each
`obsoletes`/`updates` target becomes an `rfc-editor.org/rfc/rfc<M>` link resolving
to that RFC's scroll — the RFC↔RFC standards-lineage edge. The inverse
`obsoleted_by`/`updated_by` relations are *not* re-emitted: they are the mirror of
some other saved RFC's `obsoletes`/`updates`, so the graph's bidirectional link
resolution already surfaces the edge from both ends (the Crossref "references are
not links" economy, ADR 0037). An RFC classifies as `reference` (ADR 0004), the
normative-spec sibling of a Wikipedia article.
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

RFC_EDITOR = "https://www.rfc-editor.org/rfc"
DOI_RESOLVER = "https://doi.org"

# Some RFCs (a few standards-track umbrellas) list many constituent RFCs in their
# relations and many editors; the author byline is a display string, so a long
# list is truncated to a readable head + "et al." (the Crossref/PubMed cap).
_MAX_AUTHORS = 10

GetJson = Callable[[str], Any]

# A relation entry is "RFCxxxx" (zero-padded for low numbers, "RFC0020"); the
# digits are the number, leading zeros dropped so the link matches the id form.
_RELATION_RE = re.compile(r"rfc0*(\d+)", re.IGNORECASE)

# English month names → number, so date parsing is locale-independent (strptime's
# %B follows LC_TIME, which would break a "June 2022" parse under a non-English
# locale).
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected RFC's bibliographic metadata; return it at stage 'fetched'.

    Raises FetchError when the RFC number is missing, the request fails, or the
    response is not an RFC record. The input item is never mutated.
    """
    get_json = get_json or _get_json
    if not item.source_id:
        raise FetchError(f"cannot determine RFC number for item {item.id!r}")

    number = item.source_id
    url = f"{RFC_EDITOR}/rfc{number}.json"
    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"RFC API request failed: {exc}") from exc

    if not isinstance(data, dict) or not (data.get("doc_id") or data.get("title")):
        raise FetchError(f"RFC not found: {number}")

    summary = _clean_text(data.get("abstract"))
    raw = json.dumps(data, ensure_ascii=False)
    hashed = summary or raw
    return replace(
        item,
        title=_title(data, number),
        author=_authors(data),
        published_at=_published(data.get("pub_date")) or item.published_at,
        canonical_url=f"{RFC_EDITOR}/rfc{number}",
        raw_text=raw,
        summary=summary,
        tags=_tags(data),
        concepts=_concepts(data),
        links=_links(data),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "rfc",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "rfc-editor:json",
        },
        stage="fetched",
    )


def _clean(value: Any) -> str | None:
    """A non-empty trimmed string, or None (drops the whitespace-only placeholder)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _title(data: dict[str, Any], number: str) -> str:
    """`RFC <N>: <title>`, falling back to bare `RFC <N>` when the title is absent.

    The RFC number leads because it is the work's canonical name (agents and
    readers refer to "RFC 9110", not "HTTP Semantics"), so it belongs in the
    FTS-weighted title and the scroll slug.
    """
    title = _clean(data.get("title"))
    return f"RFC {number}: {title}" if title else f"RFC {number}"


def _authors(data: dict[str, Any]) -> str | None:
    """The editor/author byline, truncated past `_MAX_AUTHORS` with "et al.".

    The RFC Editor already formats each entry as a display string ("R. Fielding,
    Ed."), so they are cleaned and joined — no name reordering like Crossref's
    `{given, family}` records.
    """
    names = [s for s in (_clean(a) for a in _as_list(data.get("authors"))) if s]
    if not names:
        return None
    if len(names) > _MAX_AUTHORS:
        names = names[:_MAX_AUTHORS] + ["et al."]
    return ", ".join(names)


def _published(pub_date: Any) -> str | None:
    """The RFC's publication date as UTC ISO 8601, or None.

    RFC dates are "Month Year" (`June 2022`); the day is padded to the first of
    the month — invented precision for one uniform shape (ADR 0024), the
    Crossref/PubMed partial-date rule. A value that is not "Month Year" but still
    carries a four-digit year pads to the start of that year.
    """
    text = _clean(pub_date)
    if not text:
        return None
    parts = text.split()
    if len(parts) == 2 and parts[0].lower() in _MONTHS and parts[1].isdigit():
        month = _MONTHS[parts[0].lower()]
        return to_utc_iso(f"{int(parts[1]):04d}-{month:02d}-01")
    year = re.search(r"\b(\d{4})\b", text)
    if year:
        return to_utc_iso(f"{int(year.group(1)):04d}-01-01")
    return None


def _clean_text(value: Any) -> str | None:
    """A whitespace-collapsed string, or None for absent/whitespace-only text."""
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text or None


def _concepts(data: dict[str, Any]) -> tuple[str, ...]:
    """The RFC Editor `keywords` as deduped concepts (the github-topics parallel).

    Older RFCs store a single whitespace-only keyword placeholder, dropped by
    `_clean`, so a keyword-less RFC is honestly concept-light rather than carrying
    an empty string.
    """
    cleaned = (_clean(v) for v in _as_list(data.get("keywords")))
    return tuple(dict.fromkeys(v for v in cleaned if v))


def _tags(data: dict[str, Any]) -> tuple[str, ...]:
    """The maturity `status` as the one title-cased tag, or none.

    `status` is the RFC Editor's controlled maturity vocabulary
    (`PROPOSED STANDARD`, `INTERNET STANDARD`, `INFORMATIONAL`, …) — the
    structured facet Crossref's `type` fills. It arrives upper-cased; it is
    title-cased for a readable KB tag page (`Internet Standard`).
    """
    status = _clean(data.get("status"))
    return (status.title(),) if status else ()


def _links(data: dict[str, Any]) -> tuple[str, ...]:
    """The RFC's outgoing edges: its DOI, then each obsoletes/updates target.

    The DOI (`10.17487/RFC<N>`, Crossref-registered) leads as a `doi.org` link —
    the RFC↔Crossref edge (ADR 0038's analog) — followed by an
    `rfc-editor.org/rfc/rfc<M>` link for every `obsoletes`/`updates` target, the
    RFC↔RFC standards-lineage edge. The inverse `obsoleted_by`/`updated_by`
    relations are deliberately omitted: each is the mirror of some other RFC's
    `obsoletes`/`updates`, and the link graph resolves edges in both directions,
    so re-emitting them only adds links to RFCs that aren't in the library.
    """
    links: list[str] = []
    doi = _clean(data.get("doi"))
    if doi:
        links.append(f"{DOI_RESOLVER}/{doi}")
    for key in ("obsoletes", "updates"):
        for ref in _as_list(data.get(key)):
            text = _clean(ref)
            match = _RELATION_RE.fullmatch(text) if text else None
            if match:
                links.append(f"{RFC_EDITOR}/rfc{int(match.group(1))}")
    return tuple(dict.fromkeys(links))


_get_json = http.get_json
