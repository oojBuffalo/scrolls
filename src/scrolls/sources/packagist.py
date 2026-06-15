"""Packagist / Composer fetch adapter (IDEAS.md §6, ADR 0039).

A saved Packagist package page becomes a clean scroll instead of a
`trafilatura` scrape of its HTML. One GET against the keyless Packagist
JSON API (`packagist.org/packages/<vendor>/<name>.json`) returns the
package's full metadata document — no auth, no runtime dependency. This
is the PHP sibling of the PyPI, npm, and crates.io adapters (ADR 0034,
ADR 0035, ADR 0036): the same JSON-metadata shape, the same
keywords→concepts / source-URL→repo-link mapping.

Three facts shape the design, confirmed against the live API:

1. **Identity is the `vendor/name`, lowercased.** Composer package names
   are case-insensitive and canonically lowercase (the schema forbids
   uppercase), so the detected source id folds case — `Monolog/Monolog`
   and `monolog/monolog` dedupe to one item. The canonical name (which
   the response echoes back) builds the canonical URL, so a folded id
   never breaks the fetch.

2. **The `versions` map mixes releases with dev branches.** Packagist
   keys `versions` by version string and includes branch aliases
   (`dev-main`, `2.x-dev`). The adapter picks the highest *stable*
   release by comparing the numeric `version_normalized`
   (`3.8.1.0` > `2.9.0.0`) — a dependency-free analog of the
   "latest release" PyPI/npm/crates track — falling back to the newest
   pre-release, then the newest dev branch, so a package with only
   pre-releases still yields a version.

3. **The API carries no README, only a description.** Unlike npm's
   packument or the crates `.crate` tarball, the Packagist JSON has no
   inline README and no cheap path to one (it lives in the dist zip).
   The package description is the searchable content, so a Packagist
   scroll is honestly metadata-only — title, description, author,
   keywords — far better than the `web` scrape it replaces (ADR 0002).

The chosen version's keywords become `concepts` the way github repo
topics do (ADR 0007); the package `type` (`library`, `project`,
`composer-plugin`, …) and the release's SPDX `license`s become `tags`,
the structured-facet slot PyPI's trove classifiers and crates' category
taxonomy fill; and the homepage, declared repository, and the version's
git source become `links`, the git source normalized so `scrolls related`
connects a package to a saved github repo it ships from (the
package↔repo edge). A Composer package classifies as `tool` like a PyPI,
npm, or crates one (ADR 0004).
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

API_ROOT = "https://packagist.org/packages"
SITE_ROOT = "https://packagist.org"

# Some packages declare long author lists; `author` is a display string,
# so a long list keeps a readable head and appends "et al." (the Crossref
# author cap, ADR 0037).
_MAX_AUTHORS = 10

GetJson = Callable[[str], Any]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected package's Packagist metadata; return it at stage 'fetched'.

    Raises FetchError when the package name is missing, the request fails,
    or the registry has no such package. The input item is never mutated.
    """
    get_json = get_json or _get_json
    if not item.source_id:
        raise FetchError(f"cannot determine package for item {item.id!r}")

    url = f"{API_ROOT}/{item.source_id}.json"
    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"Packagist API request failed: {exc}") from exc

    package = data.get("package") if isinstance(data, dict) else None
    name = package.get("name") if isinstance(package, dict) else None
    if not isinstance(name, str) or not name:
        raise FetchError(f"package not found: {item.source_id}")

    version = _select_version(package)
    canonical_url = f"{SITE_ROOT}/packages/{name}"
    summary = _clean(version.get("description")) or _clean(package.get("description"))
    raw = json.dumps(
        {
            "package": {k: v for k, v in package.items() if k != "versions"},
            "version": version,
        },
        ensure_ascii=False,
    )
    hashed = summary or raw
    return replace(
        item,
        title=name,
        author=_authors(version, package),
        published_at=_release_date(version, package) or item.published_at,
        canonical_url=canonical_url,
        raw_text=raw,
        summary=summary,
        tags=_tags(version, package),
        concepts=_keywords(version),
        links=_links(version, package, canonical_url),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "packagist",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "packagist-api:json",
        },
        stage="fetched",
    )


def _clean(value: Any) -> str | None:
    """A non-empty trimmed string, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _select_version(package: dict[str, Any]) -> dict[str, Any]:
    """The package's highest stable release object, or the best fallback, or {}.

    Packagist keys `versions` by version string and mixes real releases
    with branch aliases (`dev-main`, `2.x-dev`). Releases are ranked by
    their numeric `version_normalized` (`3.8.1.0`), so `3.10.0` beats
    `3.9.0` and a stable beats a pre-release regardless of publish order.
    Preference: highest stable release, else newest pre-release, else
    newest dev branch, else the first listed — a package with only
    pre-releases or branches still yields *a* version (graceful
    degradation, ADR 0002).
    """
    versions = package.get("versions")
    if not isinstance(versions, dict):
        return {}
    objs = [v for v in versions.values() if isinstance(v, dict)]
    if not objs:
        return {}

    stable = [v for v in objs if _kind(v) == "stable"]
    if stable:
        return max(stable, key=_version_key)
    prerelease = [v for v in objs if _kind(v) == "prerelease"]
    if prerelease:
        return max(prerelease, key=_version_key)
    return max(objs, key=lambda v: _release_date(v, {}) or "")


def _kind(version: dict[str, Any]) -> str:
    """Classify a version as 'stable', 'prerelease', or 'dev'.

    A dev branch's `version` is `dev-<branch>` or `<branch>-dev`; its
    `version_normalized` carries a `-dev` stability suffix. A pre-release
    keeps a numeric core but a `-alpha`/`-beta`/`-RC`/`-pre` suffix. A
    stable release's normalized form is purely numeric (`3.8.1.0`).
    """
    num = _clean(version.get("version"))
    if num and (num.startswith("dev-") or num.endswith("-dev")):
        return "dev"
    normalized = _clean(version.get("version_normalized")) or num or ""
    if "-dev" in normalized:
        return "dev"
    return "prerelease" if "-" in normalized else "stable"


def _version_key(version: dict[str, Any]) -> tuple[int, ...]:
    """The numeric core of `version_normalized` as an int tuple for ordering.

    `3.8.1.0` -> `(3, 8, 1, 0)`; a pre-release's stability suffix
    (`3.0.0.0-RC1`) is dropped before the split, so its core orders among
    the releases. A malformed or absent value sorts lowest as `()`.
    """
    normalized = _clean(version.get("version_normalized")) or ""
    core = normalized.split("-", 1)[0]
    parts = []
    for piece in core.split("."):
        if not piece.isdigit():
            break
        parts.append(int(piece))
    return tuple(parts)


def _release_date(version: dict[str, Any], package: dict[str, Any]) -> str | None:
    """The chosen version's publish time as UTC ISO 8601, falling back to the package's.

    Each version carries its own `time`; a malformed/absent one falls back
    to the package-level `time` (its first-published date). Guarded with
    `isinstance` because `to_utc_iso` strips its argument.
    """
    for source in (version.get("time"), package.get("time")):
        if isinstance(source, str):
            iso = to_utc_iso(source)
            if iso:
                return iso
    return None


def _authors(version: dict[str, Any], package: dict[str, Any]) -> str | None:
    """The version's declared authors as a display string, else the maintainers'.

    Each Composer author is `{name, email?, homepage?, role?}`; names join
    with ", " and a list longer than the cap keeps its head + "et al."
    (the Crossref author cap). When a release declares no authors the
    package's Packagist maintainer accounts are the honest fallback.
    """
    names = _author_names(version.get("authors"))
    if not names:
        names = _author_names(package.get("maintainers"))
    if not names:
        return None
    if len(names) > _MAX_AUTHORS:
        names = names[:_MAX_AUTHORS] + ["et al."]
    return ", ".join(names)


def _author_names(authors: Any) -> list[str]:
    """Trimmed non-empty `name` values from a list of author/maintainer dicts."""
    if not isinstance(authors, list):
        return []
    return [n for n in (_clean(a.get("name")) for a in authors if isinstance(a, dict)) if n]


def _keywords(version: dict[str, Any]) -> tuple[str, ...]:
    """The release's declared keywords as deduped concepts (the github-topics parallel)."""
    return _dedupe(version.get("keywords"))


def _tags(version: dict[str, Any], package: dict[str, Any]) -> tuple[str, ...]:
    """The package `type` and the release's SPDX licenses as deduped tags.

    `type` is a controlled vocabulary (`library`, `project`,
    `composer-plugin`, `metapackage`, `symfony-bundle`, …) and `license`
    is an array of SPDX identifiers — both structured facets, the slot
    PyPI's trove classifiers and crates' categories fill. KB pages are
    built per concept, not per tag, so these cost nothing there but give
    `scrolls related` same-type / same-license corroboration.
    """
    type_ = _clean(version.get("type")) or _clean(package.get("type"))
    licenses = _str_list(version.get("license"))
    return _dedupe([type_, *licenses])


def _str_list(value: Any) -> list[str]:
    """Non-empty trimmed strings from a list-valued field, in order."""
    if not isinstance(value, list):
        return []
    return [s for s in (_clean(v) for v in value) if s]


def _dedupe(values: Any) -> tuple[str, ...]:
    """Non-empty trimmed strings, order-preserving and deduped."""
    if not isinstance(values, list):
        return ()
    cleaned = (_clean(v) for v in values)
    return tuple(dict.fromkeys(v for v in cleaned if v))


def _links(
    version: dict[str, Any], package: dict[str, Any], canonical: str
) -> tuple[str, ...]:
    """Declared repository, homepage, and git source as deduped http(s) links.

    The package-level `repository` is Packagist's clean repo URL; the
    version's `source.url` is the raw git URL (usually `…​.git`), folded so
    `scrolls related` resolves it to the same github repo the package
    ships from (the package↔repo edge, ADR 0023/0028). The canonical
    Packagist page is dropped, and trailing-slash variants collapse to one.
    """
    source = version.get("source")
    source_url = source.get("url") if isinstance(source, dict) else None
    candidates = [
        _repo_url(package.get("repository")),
        _clean(version.get("homepage")),
        _repo_url(source_url),
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
    """A repository as a clean https URL with no `git+` prefix or `.git` suffix, or None.

    Composer stores the author's git URL verbatim — usually a clean https
    URL, often with a trailing `.git`. Folding `git+` and `.git` is what
    lets `detect_source` read a clean `owner/repo` (the crates/npm rule).
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
