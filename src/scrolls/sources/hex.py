"""Hex fetch adapter (IDEAS.md §6, ADR 0089).

A saved Hex package page becomes a clean scroll instead of a `trafilatura`
scrape of its JS-rendered page. One GET against the keyless Hex JSON API
(`hex.pm/api/packages/<name>`) returns the package's metadata document —
no auth, no runtime dependency. This is the Elixir/Erlang sibling of the
PyPI, npm, crates.io, Packagist, RubyGems, Go, and pub.dev adapters
(ADR 0034–0036, 0039, 0040, 0042, 0088): the same JSON-metadata shape, the
same source-URL→repo-link mapping. It is pub.dev's closest twin in field
layout — a `meta` object holding the description, licenses, and a links map.

Three facts shape the design, confirmed against the live API:

1. **Identity is the package name, folded lowercase.** Hex package names
   are lowercase (the registry enforces it), and the API is case-sensitive
   — live, `packages/Ecto` 404s while `packages/ecto` resolves — so the
   source id is folded lowercase (the PyPI/crates/Packagist/pub fold,
   ADR 0034/0036/0039/0088, not RubyGems' verbatim rule): a mistyped
   capital still resolves, and the canonical form is always lowercase.

2. **`meta` carries description, licenses, and links.** The endpoint
   returns the package, and `meta.description`, `meta.licenses`, and the
   `meta.links` map (`{"GitHub": "…", "Changelog": "…"}`) are the fields a
   scroll needs. `releases` is a newest-first list of `{version,
   inserted_at}`; the release matching `latest_stable_version` (else
   `latest_version`) dates the scroll.

3. **No keywords, and no README in the API.** Hex has no keywords field, so
   a Hex scroll contributes nothing to the KB concept graph — empty
   `concepts` by design, RubyGems' and Go's structural gap (ADR 0040/0042),
   not pub.dev's `topics` (ADR 0088). The README lives only in the package
   tarball, not the JSON, so the package description is the searchable
   content and the scroll is honestly metadata-only (ADR 0002).

The SPDX `meta.licenses` become `tags`, the structured-facet slot; the
`meta.links` values become `links`, the `GitHub` entry resolving to the
package's github repo through `scrolls related` (the package↔repo edge). A
Hex package classifies as `tool` like every other package (ADR 0004).
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

API_ROOT = "https://hex.pm/api/packages"
SITE_ROOT = "https://hex.pm"

GetJson = Callable[[str], Any]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected package's Hex metadata; return it at stage 'fetched'.

    Raises FetchError when the package name is missing, the request fails,
    or the registry has no such package. The input item is never mutated.
    """
    get_json = get_json or _get_json
    if not item.source_id:
        raise FetchError(f"cannot determine package for item {item.id!r}")

    url = f"{API_ROOT}/{item.source_id}"
    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"Hex API request failed: {exc}") from exc

    name = data.get("name") if isinstance(data, dict) else None
    if not isinstance(name, str) or not name:
        raise FetchError(f"package not found: {item.source_id}")

    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    canonical_url = _clean(data.get("html_url")) or f"{SITE_ROOT}/packages/{name}"
    summary = _clean(meta.get("description"))
    raw = json.dumps(
        {k: v for k, v in data.items() if k != "releases"}, ensure_ascii=False
    )
    hashed = summary or raw
    return replace(
        item,
        title=name,
        published_at=_release_date(data) or item.published_at,
        canonical_url=canonical_url,
        raw_text=raw,
        summary=summary,
        tags=_dedupe(meta.get("licenses")),
        concepts=(),  # Hex has no keywords — structurally empty
        links=_links(meta, canonical_url),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "hex",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "hexpm-api:json",
        },
        stage="fetched",
    )


def _clean(value: Any) -> str | None:
    """A non-empty trimmed string, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _release_date(data: dict[str, Any]) -> str | None:
    """The latest stable release's publish time as UTC ISO 8601, or None.

    `releases` is a newest-first list of `{version, inserted_at}`; the
    release whose `version` equals `latest_stable_version` (else
    `latest_version`) is the one the scroll tracks, with the newest release
    as the order-independent fallback. `inserted_at` carries microseconds
    and a `Z` suffix that the shared `to_utc_iso` (ADR 0024) normalizes.
    """
    releases = data.get("releases")
    if not isinstance(releases, list) or not releases:
        return None
    wanted = data.get("latest_stable_version") or data.get("latest_version")
    chosen = None
    for release in releases:
        if isinstance(release, dict) and release.get("version") == wanted:
            chosen = release
            break
    if chosen is None:
        chosen = releases[0] if isinstance(releases[0], dict) else None
    inserted = chosen.get("inserted_at") if isinstance(chosen, dict) else None
    return to_utc_iso(inserted) if isinstance(inserted, str) else None


def _dedupe(values: Any) -> tuple[str, ...]:
    """Non-empty trimmed strings, order-preserving and deduped."""
    if not isinstance(values, list):
        return ()
    cleaned = (_clean(v) for v in values)
    return tuple(dict.fromkeys(v for v in cleaned if v))


def _links(meta: dict[str, Any], canonical: str) -> tuple[str, ...]:
    """The `meta.links` map's values as deduped http(s) links.

    Hex stores outbound URLs as a `{label: url}` map (`GitHub`, `Changelog`,
    `Docs`, `Website`); every http(s) value becomes a `link` in the map's
    order. The `GitHub` value is a clean repo URL whose `git+`/`.git` is
    folded (the crates/RubyGems rule, ADR 0036/0040) so `scrolls related`
    resolves it to the package's github repo (the package↔repo edge). The
    Hex page itself (the canonical URL) is dropped, and trailing-slash
    variants collapse to one.
    """
    links_field = meta.get("links")
    if not isinstance(links_field, dict):
        return ()
    canonical_key = (canonical or "").rstrip("/")
    seen: set[str] = set()
    links: list[str] = []
    for value in links_field.values():
        url = (_repo_url(value) or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            continue
        key = url.rstrip("/")
        if key == canonical_key or key in seen:
            continue
        seen.add(key)
        links.append(url)
    return tuple(links)


def _repo_url(value: Any) -> str | None:
    """A link value as a clean https URL with no `git+`/`.git`, or None.

    Hex link values are usually clean https URLs; the `git+`/`.git` fold is
    the defensive normalization the crates/RubyGems/pub adapters apply so a
    repository URL resolves to a clean `owner/repo` in `detect_source`.
    """
    url = _clean(value)
    if not url:
        return None
    if url.startswith("git+"):
        url = url[len("git+"):]
    if url.endswith(".git"):
        url = url[: -len(".git")]
    return url or None


_get_json = http.get_json
