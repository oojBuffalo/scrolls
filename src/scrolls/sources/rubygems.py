"""RubyGems fetch adapter (IDEAS.md §6, ADR 0040).

A saved RubyGems gem page becomes a clean scroll instead of a
`trafilatura` scrape of its HTML. One GET against the keyless RubyGems
JSON API (`rubygems.org/api/v1/gems/<name>.json`) returns the gem's
latest-version metadata document — no auth, no runtime dependency. This
is the Ruby sibling of the PyPI, npm, crates.io, and Packagist adapters
(ADR 0034–0036, 0039): the same JSON-metadata shape, the same
source-URL→repo-link mapping.

Three facts shape the design, confirmed against the live API:

1. **Identity is the gem name, case-sensitive.** RubyGems gem names are
   case-sensitive — live, `gems/Ascii85.json` returns 200 while
   `gems/ascii85.json` returns 404 — so the source id is preserved
   verbatim, npm's rule (ADR 0035), not the case-folding PyPI/crates/
   Packagist apply. Folding could turn a `RedCloth` URL into a fetch
   miss.

2. **The endpoint returns the latest version inline.** Unlike Packagist's
   `versions` map (ADR 0039) or the crates `versions` array, `gems/<name>`
   *is* the gem's most-recent release — name, version, authors,
   description, licenses, the project URLs — so there is no version to
   select. Re-fetching refreshes the scroll to the current latest release.

3. **No keywords, and no README in the API.** A gemspec has no keywords
   field, so a RubyGems scroll contributes nothing to the concept graph —
   honestly empty `concepts`, the first registry adapter for which that is
   structural rather than incidental. And the README lives only in the
   `.gem` (a nested tar-in-tar), with no inline copy, so the gem's
   description is the searchable content and the scroll is metadata-only
   (ADR 0002) — Packagist's situation.

The gem has no concepts to offer; its SPDX `licenses` become `tags`, the
structured-facet slot PyPI's classifiers and crates' categories fill; and
the homepage, source, and documentation URIs become `links`, the source
URI resolving to the gem's github repo through `scrolls related` (the
package↔repo edge) even when it points at a tagged tree. A gem classifies
as `tool` like a PyPI, npm, crates, or Composer package (ADR 0004).
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

API_ROOT = "https://rubygems.org/api/v1/gems"
SITE_ROOT = "https://rubygems.org"

GetJson = Callable[[str], Any]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected gem's RubyGems metadata; return it at stage 'fetched'.

    Raises FetchError when the gem name is missing, the request fails, or
    the registry has no such gem. The input item is never mutated.
    """
    get_json = get_json or _get_json
    if not item.source_id:
        raise FetchError(f"cannot determine gem for item {item.id!r}")

    url = f"{API_ROOT}/{item.source_id}.json"
    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"RubyGems API request failed: {exc}") from exc

    name = data.get("name") if isinstance(data, dict) else None
    if not isinstance(name, str) or not name:
        raise FetchError(f"gem not found: {item.source_id}")

    canonical_url = _clean(data.get("project_uri")) or f"{SITE_ROOT}/gems/{name}"
    summary = _clean(data.get("info"))
    raw = json.dumps(
        {k: v for k, v in data.items() if k != "dependencies"}, ensure_ascii=False
    )
    hashed = summary or raw
    return replace(
        item,
        title=name,
        author=_clean(data.get("authors")),
        published_at=_release_date(data) or item.published_at,
        canonical_url=canonical_url,
        raw_text=raw,
        summary=summary,
        tags=_dedupe(data.get("licenses")),
        concepts=(),  # a gemspec has no keywords — structurally empty
        links=_links(data, canonical_url),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "rubygems",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "rubygems-api:json",
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
    """The latest version's publish time as UTC ISO 8601, or None.

    `version_created_at` is an ISO 8601 timestamp with fractional seconds
    and a `Z` suffix; the shared `to_utc_iso` (ADR 0024) normalizes it.
    Guarded with `isinstance` because `to_utc_iso` strips its argument.
    """
    created = data.get("version_created_at")
    return to_utc_iso(created) if isinstance(created, str) else None


def _dedupe(values: Any) -> tuple[str, ...]:
    """Non-empty trimmed strings, order-preserving and deduped."""
    if not isinstance(values, list):
        return ()
    cleaned = (_clean(v) for v in values)
    return tuple(dict.fromkeys(v for v in cleaned if v))


def _links(data: dict[str, Any], canonical: str) -> tuple[str, ...]:
    """Homepage, source, and documentation URIs as deduped http(s) links.

    The three that match the crates adapter's homepage/repository/docs
    shape (ADR 0036); the source URI's occasional `git+`/`.git` is folded
    so `scrolls related` resolves it to the gem's github repo (the
    package↔repo edge), which works even when the URI points at a tagged
    tree (`…​/rails/rails/tree/v8.1.3`) since `detect_source` reads
    `owner/repo` off the path. The RubyGems page itself (the canonical
    URL) is dropped, and trailing-slash variants collapse to one.
    """
    candidates = [
        _clean(data.get("homepage_uri")),
        _repo_url(data.get("source_code_uri")),
        _clean(data.get("documentation_uri")),
    ]
    canonical_key = (canonical or "").rstrip("/")
    seen: set[str] = set()
    links: list[str] = []
    for url in candidates:
        url = (url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            continue
        key = url.rstrip("/")
        if key == canonical_key or key in seen:
            continue
        seen.add(key)
        links.append(url)
    return tuple(links)


def _repo_url(source_uri: Any) -> str | None:
    """A source URI as a clean https URL with no `git+` prefix or `.git` suffix, or None.

    RubyGems stores the gemspec's `source_code_uri` verbatim — usually a
    clean https URL, occasionally with a `git+` prefix or `.git` suffix.
    Folding them is what lets `detect_source` read a clean `owner/repo`
    (the crates/npm/Packagist rule).
    """
    url = _clean(source_uri)
    if not url:
        return None
    if url.startswith("git+"):
        url = url[len("git+"):]
    if url.endswith(".git"):
        url = url[: -len(".git")]
    return url or None


_get_json = http.get_json
