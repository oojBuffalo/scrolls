"""Maven Central (JVM) fetch adapter (IDEAS.md §6, ADR 0092).

A saved Maven artifact page becomes a clean scroll instead of a `trafilatura`
scrape of a JS-rendered index page. Maven Central is the JVM sibling of the
package-registry family (ADR 0034–0036, 0039, 0040, 0042, 0088–0091) — the one
top-tier ecosystem the family had not reached, and the largest: Java, Kotlin,
Scala, Clojure, Groovy, and Android libraries all publish here. Like NuGet (ADR
0090) and Go (ADR 0042) it takes **two plain requests** against the keyless,
permanent flat repository `repo1.maven.org/maven2` — no auth, no runtime
dependency, no rate-limited search API:

1. `GET /<group-path>/<artifact>/maven-metadata.xml` → `<versioning>` with the
   `<release>` pointer and the full `<versions>` list, parsed with stdlib
   ElementTree (the arXiv/PubMed/RFC/nuspec XML discipline).
2. `GET /<group-path>/<artifact>/<version>/<artifact>-<version>.pom` → the POM
   manifest, the metadata that becomes the scroll.

Four facts shape the design, confirmed against the live repository:

1. **Identity is the Maven coordinate `groupId:artifactId`, verbatim.** A Maven
   artifact is addressed by two parts — a reverse-DNS `groupId`
   (`com.google.guava`) and an `artifactId` (`guava`) — joined here with a colon
   in the registry's own coordinate notation (`maven:com.google.guava:guava`).
   The repository is a literal file tree, case-sensitive, so the coordinate is
   preserved verbatim (the npm/RubyGems/Hackage rule, ADR 0035/0040/0091, not the
   case-folding PyPI/crates rule). The reverse-DNS group is **path-encoded** —
   its dots become slashes (`com.google.guava` → `com/google/guava`) — to address
   the artifact's directory, the structural cousin of Go's request case-encoding
   (ADR 0042).

2. **Latest *release*, from the version index.** maven-metadata.xml's `<release>`
   is exactly the "latest non-SNAPSHOT release" Maven itself resolves, and it
   handles stable build classifiers (Guava's `-jre`/`-android`) the naive
   "a hyphen marks a pre-release" heuristic gets wrong — so it is preferred
   outright, with a SNAPSHOT-excluded numeric ranking (ADR 0039) the fallback
   only when an artifact has no `<release>` pointer. The chosen version's POM is
   the authoritative manifest.

3. **`concepts` empty by design; the rest is metadata-only.** A POM has no
   keyword/topic facet, so a Maven artifact contributes nothing to the KB concept
   graph — `concepts` empty like RubyGems, Go, and Hex (ADR 0040/0042/0089), the
   registry's data (not the adapter) deciding whether a package can join the
   graph. The README ships in the artifact jar, not the POM, so the
   `<description>` is the searchable `summary` and the scroll is honestly
   metadata-only (RubyGems/NuGet/Hex shape). The `<licenses>` names become `tags`
   (the package-family license facet), and `<url>` plus the `<scm>` repository
   become `links`, the repository wiring the package↔repo edge `scrolls related`
   resolves to a saved github repo.

4. **The publish date lives in the index, not the manifest.** A POM carries no
   reliable upload date, but maven-metadata.xml's `<lastUpdated>`
   (`yyyyMMddHHmmss`, UTC) records when the artifact was last deployed — for a
   release artifact, its latest release. So `published_at` is read from the
   *version index*, the only adapter whose date comes from outside its content
   manifest, degrading to the feed seed when absent or unparseable.

The POM *is* the metadata, so (like NuGet's nuspec) its failure is a FetchError —
there is no metadata-only scroll to degrade to. A Maven artifact classifies as
`tool` like every other package (ADR 0004). Parent-POM inheritance (a child POM
that inherits its description/licenses/scm from a `<parent>`) is deferred: the
adapter reads the POM directly, so a multi-module child that omits those fields
yields a thinner scroll rather than a second request chain.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

REPO_ROOT = "https://repo1.maven.org/maven2"
SITE_ROOT = "https://central.sonatype.com/artifact"
# A POM or maven-metadata.xml is a few KB; cap the download defensively (the
# npm/crates/Go/NuGet capped GET, ADR 0035/0042/0090).
_MAX_BYTES = 2_000_000

GetText = Callable[[str], str]


def fetch_item(item: ScrollItem, *, get_text: GetText | None = None) -> ScrollItem:
    """Fetch a detected Maven artifact's metadata; return it at stage 'fetched'.

    Raises FetchError when the coordinate is missing or malformed, either
    request fails, the registry resolves no version, or the POM is unusable.
    The input item is never mutated.
    """
    get_text = get_text or _get_text
    group, artifact = _coordinate(item)
    base = f"{REPO_ROOT}/{group.replace('.', '/')}/{artifact}"

    try:
        metadata_xml = get_text(f"{base}/maven-metadata.xml")
    except (OSError, ValueError) as exc:
        raise FetchError(f"Maven metadata request failed: {exc}") from exc

    version, last_updated = _select_version(metadata_xml)
    if not version:
        raise FetchError(f"artifact not found: {group}:{artifact}")

    try:
        pom_xml = get_text(f"{base}/{version}/{artifact}-{version}.pom")
    except (OSError, ValueError) as exc:
        raise FetchError(f"Maven POM request failed: {exc}") from exc

    project = _parse_pom(pom_xml)
    coordinate = f"{group}:{artifact}"
    summary = _text(project, "description")
    canonical_url = f"{SITE_ROOT}/{group}/{artifact}"
    hashed = summary or pom_xml
    return replace(
        item,
        title=_text(project, "name") or coordinate,
        author=_author(project),
        # the POM has no date; the version index's lastUpdated is the deploy time
        published_at=_last_updated_iso(last_updated) or item.published_at,
        canonical_url=canonical_url,
        raw_text=pom_xml,  # the POM manifest, kept for provenance
        extracted_text=None,  # README ships in the jar — metadata-only
        summary=summary,
        # a POM has no keyword/topic facet — concepts empty by design
        # (RubyGems/Go/Hex, ADR 0040/0042/0089)
        concepts=(),
        tags=_license_tags(project),
        links=_links(project, canonical_url),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "maven",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "maven-repository:pom",
        },
        stage="fetched",
    )


def _coordinate(item: ScrollItem) -> tuple[str, str]:
    """Split the `groupId:artifactId` source id, or raise FetchError.

    A coordinate has exactly one colon (the group is reverse-DNS dotted, the
    artifact has neither dots-as-slashes nor colons), so a missing or malformed
    id is a fetch error before any request is made.
    """
    name = item.source_id or ""
    group, sep, artifact = name.partition(":")
    if not sep or not group or not artifact or ":" in artifact:
        raise FetchError(f"cannot determine artifact for item {item.id!r}")
    return group, artifact


def _select_version(xml_text: str) -> tuple[str | None, str | None]:
    """The chosen version and the metadata's `<lastUpdated>` from maven-metadata.xml.

    Prefers `<versioning><release>` — Maven's own authoritative latest-release
    pointer, which gets stable build classifiers (`-jre`/`-android`) right where
    a hyphen heuristic does not — falling back to the highest non-SNAPSHOT
    version in `<versions>` (Packagist's numeric ranking, ADR 0039) for an
    artifact that has no `<release>`. A non-XML body or one with no
    `<versioning>` raises FetchError.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FetchError(f"Maven metadata is not valid XML: {exc}") from exc
    versioning = _find(root, "versioning")
    if versioning is None:
        raise FetchError("Maven metadata has no <versioning> element")
    release = _text(versioning, "release")
    latest = _text(versioning, "latest")
    versions = _versions(versioning)
    last_updated = _text(versioning, "lastUpdated")
    return (release or _latest_release(versions) or latest, last_updated)


def _versions(versioning: ET.Element) -> list[str]:
    """The `<versioning><versions><version>` strings, in document order."""
    container = _find(versioning, "versions")
    if container is None:
        return []
    out = []
    for child in container:
        if _local(child.tag) == "version" and child.text and child.text.strip():
            out.append(child.text.strip())
    return out


def _latest_release(versions: list[str]) -> str | None:
    """The highest non-SNAPSHOT version, or the highest overall if all are snapshots.

    The fallback for an artifact with no `<release>` pointer: a `-SNAPSHOT`
    suffix marks a definite non-release and is excluded, then the remaining
    versions are ranked numerically (ADR 0039). Stable build classifiers
    (`-jre`) are *not* excluded — only `<release>` (preferred above) discriminates
    those perfectly, so this honest fallback ranks them by their numbers.
    """
    if not versions:
        return None
    released = [v for v in versions if "-SNAPSHOT" not in v.upper()]
    return max(released or versions, key=_version_key)


def _version_key(version: str) -> tuple[tuple[int, ...], int, str]:
    """A sort key: (release numbers, release-outranks-qualified, qualifier).

    The numeric core before any `-` qualifier is compared first, then an
    unqualified version outranks a qualified one of the same numbers, then the
    qualifier breaks remaining ties lexically — enough to pick a sensible newest.
    """
    release, _, qualifier = version.partition("-")
    numbers = tuple(int(p) if p.isdigit() else 0 for p in release.split("."))
    numbers += (0,) * (4 - len(numbers))
    return (numbers, 0 if qualifier else 1, qualifier)


def _last_updated_iso(last_updated: str | None) -> str | None:
    """maven-metadata's `yyyyMMddHHmmss` (UTC) as UTC ISO 8601, or None."""
    if not last_updated:
        return None
    try:
        stamp = datetime.strptime(last_updated.strip(), "%Y%m%d%H%M%S")
    except (ValueError, TypeError):
        return None
    return stamp.replace(tzinfo=timezone.utc).isoformat(timespec="seconds")


def _parse_pom(xml_text: str) -> ET.Element:
    """The POM `<project>` root, namespace-agnostic.

    POMs declare the `http://maven.apache.org/POM/4.0.0` namespace but some omit
    it, so children are matched by *local* name (the nuspec lesson, ADR 0090). A
    non-XML body raises FetchError: the POM is the only metadata, so there is
    nothing to degrade to (unlike Go's optional go.mod, ADR 0042).
    """
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FetchError(f"Maven POM is not valid XML: {exc}") from exc


def _local(tag: str) -> str:
    """An element tag's local name, stripped of any `{namespace}` prefix."""
    return tag.rsplit("}", 1)[-1]


def _find(parent: ET.Element, name: str) -> ET.Element | None:
    """The first direct child with the given local name, or None."""
    for child in parent:
        if _local(child.tag) == name:
            return child
    return None


def _text(parent: ET.Element, name: str) -> str | None:
    """A child element's trimmed text, or None if absent/empty."""
    child = _find(parent, name)
    if child is None or child.text is None:
        return None
    return child.text.strip() or None


def _author(project: ET.Element) -> str | None:
    """The `<organization><name>`, else the first `<developers><developer><name>`.

    A POM has no single author field; the publishing organization is the best
    byline, with the lead developer the fallback (an artifact with neither leaves
    `author` unset).
    """
    org = _find(project, "organization")
    if org is not None:
        name = _text(org, "name")
        if name:
            return name
    developers = _find(project, "developers")
    if developers is not None:
        for child in developers:
            if _local(child.tag) == "developer":
                name = _text(child, "name")
                if name:
                    return name
    return None


def _license_tags(project: ET.Element) -> tuple[str, ...]:
    """The `<licenses><license><name>` values as deduped tags, order preserved.

    Maven license names are freeform (`Apache License, Version 2.0`,
    `The MIT License`), so they are kept verbatim (the Hackage license rule, ADR
    0091) rather than normalized to SPDX — the package-family license facet.
    """
    licenses = _find(project, "licenses")
    if licenses is None:
        return ()
    names = []
    for child in licenses:
        if _local(child.tag) == "license":
            name = _text(child, "name")
            if name:
                names.append(name)
    return tuple(dict.fromkeys(names))


def _links(project: ET.Element, canonical: str) -> tuple[str, ...]:
    """`<url>` (homepage) and the `<scm>` repository as deduped http(s) links.

    The SCM repository wires the package↔repo edge `scrolls related` resolves to
    a saved github repo; it comes from `<scm><url>` or, failing that, the
    `scm:<tool>:<url>` `<connection>`/`<developerConnection>` (ssh `git@host:path`
    and `git://` forms normalized to https, the `.git` suffix stripped). A
    homepage equal to the repository collapses to one link, and the artifact's
    own Central page (the canonical URL) is dropped.
    """
    candidates = [_clean_repo(_text(project, "url")), _scm_url(_find(project, "scm"))]
    canonical_key = (canonical or "").rstrip("/")
    seen: set[str] = set()
    links: list[str] = []
    for url in candidates:
        if not url:
            continue
        key = url.rstrip("/")
        if key == canonical_key or key in seen:
            continue
        seen.add(key)
        links.append(url)
    return tuple(links)


def _scm_url(scm: ET.Element | None) -> str | None:
    """A single cleaned repository URL from an `<scm>` element, or None."""
    if scm is None:
        return None
    url = _clean_repo(_text(scm, "url"))
    if url:
        return url
    for field in ("connection", "developerConnection"):
        derived = _clean_scm_connection(_text(scm, field))
        if derived:
            return derived
    return None


def _clean_scm_connection(value: str | None) -> str | None:
    """An `scm:<tool>:<url>` connection string as a clean http(s) URL, or None.

    Strips the `scm:<tool>:` prefix, rewrites the ssh `git@host:path` and the
    `git://host/path` forms to `https://host/path`, then cleans the result.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    prefix = re.match(r"scm:[^:]+:", text)
    if prefix:
        text = text[prefix.end():]
    ssh = re.match(r"[\w.-]+@([\w.-]+):(.+)", text)
    if ssh:
        text = f"https://{ssh.group(1)}/{ssh.group(2)}"
    elif text.startswith("git://"):
        text = "https://" + text[len("git://"):]
    return _clean_repo(text)


def _clean_repo(url: str | None) -> str | None:
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


def _get_text(url: str) -> str:
    """Default fetcher: a capped GET decoded as UTF-8."""
    return http.get_bytes(url, max_bytes=_MAX_BYTES).decode("utf-8", errors="replace")
