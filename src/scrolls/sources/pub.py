"""Pub.dev fetch adapter (IDEAS.md §6, ADR 0088).

A saved pub.dev package page becomes a clean scroll instead of a
`trafilatura` scrape of its JS-rendered page. One GET against the keyless
pub.dev JSON API (`pub.dev/api/packages/<name>`) returns the package's
latest-version document — no auth, no runtime dependency. This is the
Dart/Flutter sibling of the PyPI, npm, crates.io, Packagist, RubyGems, and
Go adapters (ADR 0034–0036, 0039, 0040, 0042): the same JSON-metadata
shape, the same source-URL→repo-link mapping.

Three facts shape the design, confirmed against the live API:

1. **Identity is the package name, folded lowercase.** Pub package names
   are lowercase Dart identifiers (`[a-z0-9_]`, enforced by the registry),
   and the API is case-sensitive — live, `packages/Provider` 404s while
   `packages/provider` returns 200 — so the source id is folded lowercase
   (the PyPI/crates/Packagist fold, ADR 0034/0036/0039, not RubyGems'
   verbatim rule): a mistyped capital still resolves, and the canonical
   form is always lowercase anyway.

2. **`latest.pubspec` carries the manifest.** The endpoint returns the
   whole package; `latest` is the most-recent version, and `latest.pubspec`
   is that version's `pubspec.yaml` as JSON — name, description, topics,
   repository, homepage. There is no version to select (unlike Packagist's
   `versions` map, ADR 0039), and a re-fetch refreshes the scroll to the
   current latest release.

3. **`topics` are the concept signal; no README in the API.** Pub's
   `pubspec.topics` (`state-management`, `networking`) are the author's
   curated labels — the github-repo-topics analog (ADR 0007) — so a pub
   scroll feeds the KB concept graph, unlike its siblings RubyGems and Go
   (ADR 0040/0042) whose registries carry no keywords. The README lives
   only in the package archive, not the metadata, so the package
   description is the searchable content and the scroll is metadata-only
   (ADR 0002).

A Flutter package — one that depends on the Flutter SDK (`environment.flutter`
or a `flutter` SDK dependency) — is tagged `flutter`, the one structured
facet pub offers to tell Flutter plugins from pure-Dart packages; a
pure-Dart package carries no tag (the honest-empty `tags` posture of Go,
ADR 0042). The repository and homepage become `links`, the repository
resolving to the package's github repo through `scrolls related` (the
package↔repo edge) even when it points into a monorepo tree. A pub package
classifies as `tool` like every other package (ADR 0004).
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

API_ROOT = "https://pub.dev/api/packages"
SITE_ROOT = "https://pub.dev"

GetJson = Callable[[str], Any]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected package's pub.dev metadata; return it at stage 'fetched'.

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
        raise FetchError(f"pub.dev API request failed: {exc}") from exc

    latest = data.get("latest") if isinstance(data, dict) else None
    pubspec = latest.get("pubspec") if isinstance(latest, dict) else None
    if not isinstance(pubspec, dict):
        raise FetchError(f"package not found: {item.source_id}")

    name = _clean(pubspec.get("name")) or item.source_id
    canonical_url = f"{SITE_ROOT}/packages/{name}"
    summary = _clean(pubspec.get("description"))
    raw = json.dumps(latest, ensure_ascii=False)
    hashed = summary or raw
    return replace(
        item,
        title=name,
        author=_clean(pubspec.get("author")),  # deprecated field, usually absent
        published_at=_published(latest) or item.published_at,
        canonical_url=canonical_url,
        raw_text=raw,
        summary=summary,
        tags=_tags(pubspec),
        concepts=_dedupe(pubspec.get("topics")),
        links=_links(pubspec, canonical_url),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "pub",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "pubdev-api:json",
        },
        stage="fetched",
    )


def _clean(value: Any) -> str | None:
    """A non-empty trimmed string, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _published(latest: dict[str, Any]) -> str | None:
    """The latest version's publish time as UTC ISO 8601, or None.

    `published` is an ISO 8601 timestamp with microseconds and a `Z`
    suffix; the shared `to_utc_iso` (ADR 0024) normalizes it. Guarded with
    `isinstance` because `to_utc_iso` strips its argument.
    """
    published = latest.get("published")
    return to_utc_iso(published) if isinstance(published, str) else None


def _tags(pubspec: dict[str, Any]) -> tuple[str, ...]:
    """`("flutter",)` for a Flutter-dependent package, else `()`.

    A Flutter plugin declares the Flutter SDK — as an `environment.flutter`
    constraint, a `flutter` SDK dependency, or both (a real plugin like
    `url_launcher` carries both) — while a pure-Dart package (`riverpod`)
    declares neither. The one structured facet pub offers, so the `--tag
    flutter` query separates the two halves of the ecosystem; a pure-Dart
    package is left untagged rather than given a synthesized `dart` label.
    """
    environment = pubspec.get("environment")
    dependencies = pubspec.get("dependencies")
    flutter = (isinstance(environment, dict) and "flutter" in environment) or (
        isinstance(dependencies, dict) and "flutter" in dependencies
    )
    return ("flutter",) if flutter else ()


def _dedupe(values: Any) -> tuple[str, ...]:
    """Non-empty trimmed strings, order-preserving and deduped."""
    if not isinstance(values, list):
        return ()
    cleaned = (_clean(v) for v in values)
    return tuple(dict.fromkeys(v for v in cleaned if v))


def _links(pubspec: dict[str, Any], canonical: str) -> tuple[str, ...]:
    """Repository and homepage as deduped http(s) links.

    The two that match the crates/RubyGems homepage/repository shape
    (ADR 0036/0040); the repository's occasional `git+`/`.git` is folded so
    `scrolls related` resolves it to the package's github repo (the
    package↔repo edge), which works even when it points into a monorepo
    tree (`…​/flutter/packages/tree/main/packages/url_launcher`) since
    `detect_source` reads `owner/repo` off the path. The pub.dev page itself
    (the canonical URL) is dropped, and trailing-slash variants collapse.
    """
    candidates = [
        _repo_url(pubspec.get("repository")),
        _clean(pubspec.get("homepage")),
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


def _repo_url(repository: Any) -> str | None:
    """A repository URL as a clean https URL with no `git+`/`.git`, or None.

    Pub stores the pubspec's `repository` verbatim — usually a clean https
    URL, occasionally with a `git+` prefix or `.git` suffix. Folding them is
    what lets `detect_source` read a clean `owner/repo` (the crates/npm/
    RubyGems rule, ADR 0036/0035/0040).
    """
    url = _clean(repository)
    if not url:
        return None
    if url.startswith("git+"):
        url = url[len("git+"):]
    if url.endswith(".git"):
        url = url[: -len(".git")]
    return url or None


_get_json = http.get_json
