"""NuGet (.NET) fetch adapter (IDEAS.md §6, ADR 0090).

A saved NuGet package page (`nuget.org/packages/<id>`) becomes a clean scroll
instead of a `trafilatura` scrape of its JS-rendered page. NuGet is the .NET
sibling of the package-registry family (ADR 0034–0036, 0039, 0040, 0042, 0088,
0089) — the one major language ecosystem the family had not yet reached — and
the named next candidate of ADR 0088/0089. Like Go (ADR 0042) it takes **two
plain requests** against the keyless permanent host `api.nuget.org`, no auth and
no runtime dependency:

1. `GET /v3-flatcontainer/<id>/index.json` → `{"versions": [...]}` (ascending).
2. `GET /v3-flatcontainer/<id>/<version>/<id>.nuspec` → the package manifest,
   parsed with stdlib ElementTree (the arXiv/PubMed/RFC XML discipline).

Three facts shape the design, confirmed against the live API:

1. **Identity is the package id, folded lowercase.** NuGet package ids are
   case-insensitive (the registry routes `Newtonsoft.Json` and `newtonsoft.json`
   alike) and the flat-container path *requires* the lowercase form, so the
   source id is folded lowercase (the forgiving PyPI/crates/pub/Hex fold,
   ADR 0034/0036/0088/0089) — never npm/RubyGems' verbatim rule. The
   registrant's display casing is read back from the nuspec `<id>` for the
   title and canonical URL, the way crates reads its canonical name back.

2. **Latest *stable* version, then the nuspec.** The flat-container index lists
   every published version; the highest one is often a pre-release (a `-`-bearing
   SemVer), so the adapter selects the highest *stable* version (Packagist's
   comparator-free numeric ranking, ADR 0039), falling back to the highest
   pre-release only for a package that has never had a stable release. The
   chosen version's `.nuspec` is the authoritative manifest.

3. **`<tags>` feed the concept graph; the rest is metadata-only.** NuGet's
   `<tags>` are author-curated keywords (whitespace-separated by convention),
   so they become `concepts` like PyPI keywords and github repo topics (ADR
   0007/0034) — the .NET ecosystem joining the KB concept graph, the payoff a
   `web` scrape never delivered. The README lives in the `.nupkg`, not the
   nuspec, so the `<description>` is the searchable `summary` and the scroll is
   honestly metadata-only (RubyGems/Hex shape, ADR 0040/0089). The SPDX
   `<license type="expression">` becomes the one `tag` (the pub/Hex/Packagist
   license facet), and `<projectUrl>` + the `<repository url>` become `links`,
   the repository wiring the package↔repo edge `scrolls related` resolves to a
   saved github repo. The nuspec carries no publish date, so `published_at` is
   honestly left as the feed seed (Go's honest-empty posture, ADR 0042).

The nuspec *is* the metadata, so unlike Go's optional `go.mod` its failure is a
FetchError — there is no metadata-only scroll to degrade to. A NuGet package
classifies as `tool` like every other package (ADR 0004).
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

FLAT_ROOT = "https://api.nuget.org/v3-flatcontainer"
SITE_ROOT = "https://www.nuget.org"
# A nuspec is a few KB; cap the download defensively (the npm/crates/Go capped
# GET, ADR 0035/0042).
_NUSPEC_MAX_BYTES = 1_000_000

# Tags are whitespace-separated by convention, but some packages use commas or
# semicolons; split on any run of them.
_TAG_SEPARATORS = re.compile(r"[\s,;]+")

GetJson = Callable[[str], Any]
GetText = Callable[[str], str]


def fetch_item(
    item: ScrollItem,
    *,
    get_json: GetJson | None = None,
    get_text: GetText | None = None,
) -> ScrollItem:
    """Fetch a detected NuGet package's metadata; return it at stage 'fetched'.

    Raises FetchError when the package id is missing, either request fails, the
    registry has no such package, or the nuspec is unusable. The input item is
    never mutated.
    """
    get_json = get_json or http.get_json
    get_text = get_text or _get_nuspec_text
    name = item.source_id
    if not name:
        raise FetchError(f"cannot determine package for item {item.id!r}")

    try:
        index = get_json(f"{FLAT_ROOT}/{name}/index.json")
    except (OSError, ValueError) as exc:
        raise FetchError(f"NuGet API request failed: {exc}") from exc

    version = _latest_stable(_versions(index))
    if not version:
        raise FetchError(f"package not found: {name}")

    try:
        xml_text = get_text(f"{FLAT_ROOT}/{name}/{version}/{name}.nuspec")
    except (OSError, ValueError) as exc:
        raise FetchError(f"NuGet nuspec request failed: {exc}") from exc

    meta = _parse_nuspec(xml_text)
    canonical_id = _text(meta, "id") or name
    summary = _text(meta, "description") or _text(meta, "summary")
    canonical_url = f"{SITE_ROOT}/packages/{canonical_id}"
    hashed = summary or xml_text
    return replace(
        item,
        title=_text(meta, "title") or canonical_id,
        author=_text(meta, "authors"),
        # the nuspec has no publish date — never invent one (Go's posture)
        published_at=item.published_at,
        canonical_url=canonical_url,
        raw_text=xml_text,  # the nuspec manifest, kept for provenance
        extracted_text=None,  # README ships in the .nupkg — metadata-only
        summary=summary,
        tags=_license_tags(meta),
        concepts=_concepts(meta),
        links=_links(meta, canonical_url),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "nuget",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "nuget-flatcontainer:nuspec",
        },
        stage="fetched",
    )


def _versions(index: Any) -> list[str]:
    """The non-empty version strings in a flat-container index, else []."""
    versions = index.get("versions") if isinstance(index, dict) else None
    if not isinstance(versions, list):
        return []
    return [v for v in versions if isinstance(v, str) and v.strip()]


def _latest_stable(versions: list[str]) -> str | None:
    """The highest stable version, or the highest overall if none are stable.

    A NuGet version is `major.minor.patch[.revision][-prerelease][+build]`; a
    `-` marks a pre-release. The highest published version is often a
    pre-release, so the stable releases are ranked first (Packagist's numeric
    ranking, ADR 0039), with the pre-release pool the fallback for a package
    that has never shipped a stable release.
    """
    if not versions:
        return None
    stable = [v for v in versions if "-" not in v]
    return max(stable or versions, key=_version_key)


def _version_key(version: str) -> tuple[tuple[int, ...], int, str]:
    """A sort key: (release numbers, stable-outranks-prerelease, prerelease).

    Build metadata (`+…`) is dropped; the release numbers are compared first,
    then a stable version outranks a pre-release of the same release
    (`1.0.0` > `1.0.0-rc`, SemVer §11), then the pre-release identifiers break
    the remaining ties lexically — enough to pick a sensible newest among
    pre-releases when no stable release exists.
    """
    release, _, prerelease = version.split("+", 1)[0].partition("-")
    numbers = tuple(int(p) if p.isdigit() else 0 for p in release.split("."))
    numbers += (0,) * (4 - len(numbers))
    return (numbers, 0 if prerelease else 1, prerelease)


def _parse_nuspec(xml_text: str) -> ET.Element:
    """The nuspec `<metadata>` element, namespace-agnostic.

    The nuspec namespace URI varies by schema version
    (`…/2011/08/`, `…/2013/05/`, …), so children are matched by *local* name
    rather than a fixed `{ns}tag` — the one robust way to read every nuspec
    generation. A non-XML body or a nuspec with no `<metadata>` raises
    FetchError: the nuspec is the only metadata, so there is nothing to
    degrade to (unlike Go's optional go.mod, ADR 0042).
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FetchError(f"NuGet nuspec is not valid XML: {exc}") from exc
    meta = _find(root, "metadata")
    if meta is None:
        raise FetchError("NuGet nuspec has no <metadata> element")
    return meta


def _local(tag: str) -> str:
    """An element tag's local name, stripped of any `{namespace}` prefix."""
    return tag.rsplit("}", 1)[-1]


def _find(parent: ET.Element, name: str) -> ET.Element | None:
    """The first direct child with the given local name, or None."""
    for child in parent:
        if _local(child.tag) == name:
            return child
    return None


def _text(meta: ET.Element, name: str) -> str | None:
    """A child element's trimmed text, or None if absent/empty."""
    child = _find(meta, name)
    if child is None or child.text is None:
        return None
    return child.text.strip() or None


def _concepts(meta: ET.Element) -> tuple[str, ...]:
    """The `<tags>` keywords as deduped concepts, order preserved.

    NuGet tags are whitespace-separated by convention (some packages use
    commas or semicolons); each token is a concept the way a PyPI keyword or a
    github repo topic is (ADR 0007/0034), so the .NET package joins the KB
    concept graph a `web` scrape would have left it out of.
    """
    raw = _text(meta, "tags")
    if not raw:
        return ()
    tokens = (t.strip() for t in _TAG_SEPARATORS.split(raw))
    return tuple(dict.fromkeys(t for t in tokens if t))


def _license_tags(meta: ET.Element) -> tuple[str, ...]:
    """The SPDX `<license type="expression">` as the one tag, or empty.

    A `<license type="file">` names a file inside the package, not an SPDX
    identifier, so only the `expression` form becomes a tag (the pub/Hex/
    Packagist license facet, ADR 0088/0089/0039).
    """
    license_el = _find(meta, "license")
    if license_el is None or license_el.get("type") != "expression":
        return ()
    spdx = (license_el.text or "").strip()
    return (spdx,) if spdx else ()


def _links(meta: ET.Element, canonical: str) -> tuple[str, ...]:
    """`<projectUrl>` and the `<repository url>` as deduped http(s) links.

    The repository URL wires the package↔repo edge `scrolls related` resolves
    to a saved github repo; its `git+`/`.git` is folded so `detect_source`
    reads a clean `owner/repo` (the crates/Hex rule, ADR 0036/0089). The
    package's own NuGet page (the canonical URL) is dropped, and a projectUrl
    equal to the repository collapses to one link.
    """
    candidates = [_text(meta, "projectUrl")]
    repository = _find(meta, "repository")
    if repository is not None:
        candidates.append(repository.get("url"))
    canonical_key = (canonical or "").rstrip("/")
    seen: set[str] = set()
    links: list[str] = []
    for candidate in candidates:
        url = _clean_repo(candidate)
        if not url:
            continue
        key = url.rstrip("/")
        if key == canonical_key or key in seen:
            continue
        seen.add(key)
        links.append(url)
    return tuple(links)


def _clean_repo(url: Any) -> str | None:
    """An http(s) URL with no `git+` prefix or `.git` suffix, or None."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    if url.startswith("git+"):
        url = url[len("git+"):]
    if url.endswith(".git"):
        url = url[: -len(".git")]
    if not url.lower().startswith(("http://", "https://")):
        return None
    return url or None


def _get_nuspec_text(url: str) -> str:
    """Default nuspec fetcher: a capped GET decoded as UTF-8."""
    return http.get_bytes(url, max_bytes=_NUSPEC_MAX_BYTES).decode(
        "utf-8", errors="replace"
    )
