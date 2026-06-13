"""PyPI fetch adapter (IDEAS.md §6, ADR 0034).

A saved PyPI project page becomes a clean scroll instead of a
`trafilatura` scrape of its HTML. One GET against the keyless PyPI JSON
API (`/pypi/<name>/json`) returns the project's metadata for its latest
release — no auth, no runtime dependency. The package's long description
(the rendered README) is the searchable content, with the one-line
summary mapped to `summary` the way every adapter leads.

A package's author-declared keywords are curated topical labels, so they
become `concepts` the way github repo topics do (ADR 0007), feeding the
KB's concept pages. The PyPI trove classifiers — a structured taxonomy
like arXiv's category codes (ADR 0008) — go to `tags`, and the project's
declared URLs (homepage, docs, source) become `links`, so `scrolls
related` connects a package to a saved github repo it points at.

Identity is the project name only (PEP 503-normalized in detection), so
fetch always resolves the *latest* release: re-fetching a package
refreshes it to its current version, regardless of which version page
was saved. Legacy PyPI metadata writes the literal "UNKNOWN" for absent
fields, which is normalized back to absent. The raw metadata record is
kept in `raw_text` for rebuilds.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

API_ROOT = "https://pypi.org/pypi"

GetJson = Callable[[str], Any]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected PyPI project's metadata; return it at stage 'fetched'.

    Raises FetchError when the project name is missing, the request fails,
    or the response carries no `info`. The input item is never mutated.
    """
    get_json = get_json or _get_json
    if not item.source_id:
        raise FetchError(f"cannot determine pypi project for item {item.id!r}")

    url = f"{API_ROOT}/{item.source_id}/json"
    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"pypi API request failed: {exc}") from exc

    info = data.get("info") if isinstance(data, dict) else None
    if not isinstance(info, dict):  # 404s raise above; a malformed body lands here
        raise FetchError(f"pypi project not found: {item.source_id}")

    description = _clean(info.get("description"))
    raw = json.dumps({"info": info, "urls": data.get("urls")}, ensure_ascii=False)
    hashed = description or raw
    method = "pypi-api:json+description" if description else "pypi-api:json"
    return replace(
        item,
        title=_clean(info.get("name")) or item.title,
        author=_clean(info.get("author")) or _clean(info.get("maintainer")),
        published_at=_release_date(data.get("urls")) or item.published_at,
        canonical_url=info.get("package_url") or info.get("project_url"),
        raw_text=raw,
        extracted_text=description,
        summary=_clean(info.get("summary")),
        tags=_classifiers(info),
        concepts=_keywords(info.get("keywords")),
        links=_links(info),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "pypi",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _clean(value: Any) -> str | None:
    """A non-empty string, or None — folding PyPI's legacy "UNKNOWN" to absent."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return None if not text or text == "UNKNOWN" else text


def _keywords(raw: Any) -> tuple[str, ...]:
    """Author-declared keywords as deduped concepts (the github-topics parallel).

    Metadata 2.x exposes keywords as a list; the older free-form string is
    comma-separated by convention, but space-separated in the wild, so a
    comma-less string splits on whitespace.
    """
    if isinstance(raw, (list, tuple)):
        values = [str(value) for value in raw]
    else:
        text = _clean(raw)
        if not text:
            return ()
        values = text.split(",") if "," in text else text.split()
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def _classifiers(info: dict[str, Any]) -> tuple[str, ...]:
    """The PyPI trove classifiers verbatim, deduped (a structured taxonomy → tags)."""
    classifiers = info.get("classifiers") or []
    return tuple(
        dict.fromkeys(c for c in classifiers if isinstance(c, str) and c.strip())
    )


def _links(info: dict[str, Any]) -> tuple[str, ...]:
    """Declared project URLs (homepage, docs, source) as deduped http(s) links.

    The PyPI project page itself is dropped (it is the canonical URL), and
    trailing-slash variants collapse to one so a homepage listed twice —
    `home_page` and a `project_urls` entry — appears once.
    """
    canonical = (info.get("package_url") or "").rstrip("/")
    candidates = [info.get("home_page"), *(info.get("project_urls") or {}).values()]
    seen: set[str] = set()
    links: list[str] = []
    for url in candidates:
        url = (url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            continue
        key = url.rstrip("/")
        if key == canonical or key in seen:
            continue
        seen.add(key)
        links.append(url)
    return tuple(links)


def _release_date(urls: Any) -> str | None:
    """The latest release's earliest file upload time as UTC ISO 8601, or None.

    `urls` lists the files for the latest version; the earliest upload is
    the moment that version was published. UTC ISO 8601 strings sort
    chronologically, so `min` finds it.
    """
    if not isinstance(urls, list):
        return None
    stamps = [
        stamp
        for entry in urls
        if isinstance(entry, dict)
        for stamp in (to_utc_iso(entry.get("upload_time_iso_8601")),)
        if stamp
    ]
    return min(stamps) if stamps else None


_get_json = http.get_json
