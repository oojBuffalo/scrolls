"""npm fetch adapter (IDEAS.md §6, ADR 0035).

A saved npm package page becomes a clean scroll instead of a
`trafilatura` scrape of its HTML. One GET against the keyless npm
registry (`registry.npmjs.org/<name>`) returns the package's full
metadata document — no auth, no runtime dependency. The package's README
(the `readme` field, the rendered package page's body) is the searchable
content, with the one-line `description` mapped to `summary` the way
every adapter leads.

This is the npm sibling of the PyPI adapter (ADR 0034): a package's
author-declared keywords become `concepts` the way github repo topics do
(ADR 0007), and its declared homepage and repository become `links` —
with the repository's `git+https://…​.git` form normalized to a clean
https URL so `scrolls related` connects a package to a saved github repo
it ships from (the package↔repo edge). npm has no trove-classifier
analog, so `tags` stay empty, honestly — a package with no structured
taxonomy contributes none.

Identity is the package name only (preserved verbatim in detection, the
registry being case-sensitive), so fetch always resolves the *latest*
release via the `dist-tags.latest` pointer: re-fetching a package
refreshes it to its current version, regardless of which version page
was saved. The latest version's metadata and the publish-time map are
kept in `raw_text` for rebuilds.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

API_ROOT = "https://registry.npmjs.org"

# npm writes this exact string into `readme` when a package ships none.
_NO_README = "ERROR: No README data found!"

# The published tarball carries the README when the registry's packument
# doesn't (true for high-traffic packages — express, react — whose
# top-level `readme` is empty). Cap the download so a package that bundles
# large files degrades to metadata-only instead of buffering tens of MB.
_MAX_TARBALL_BYTES = 8 * 1024 * 1024

GetJson = Callable[[str], Any]
GetBytes = Callable[..., bytes]


def fetch_item(
    item: ScrollItem,
    *,
    get_json: GetJson | None = None,
    get_bytes: GetBytes | None = None,
) -> ScrollItem:
    """Fetch a detected npm package's metadata; return it at stage 'fetched'.

    Raises FetchError when the package name is missing, the request fails,
    or the registry has no such package. The input item is never mutated.
    """
    get_json = get_json or _get_json
    get_bytes = get_bytes or _get_bytes
    if not item.source_id:
        raise FetchError(f"cannot determine npm package for item {item.id!r}")

    # Scoped names carry a slash; encode it so `@scope/name` is one path
    # segment the registry resolves (the documented form).
    url = f"{API_ROOT}/{quote(item.source_id, safe='@')}"
    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"npm registry request failed: {exc}") from exc

    name = data.get("name") if isinstance(data, dict) else None
    if not isinstance(name, str) or not name or "error" in data:
        raise FetchError(f"npm package not found: {item.source_id}")

    latest = _latest_version(data)
    versions = data.get("versions")
    version_info = versions.get(latest, {}) if isinstance(versions, dict) and latest else {}
    if not isinstance(version_info, dict):
        version_info = {}

    readme, readme_source = _resolve_readme(data, version_info, get_bytes)
    canonical_url = f"https://www.npmjs.com/package/{name}"
    raw = json.dumps(
        {
            "name": name,
            "dist-tags": data.get("dist-tags"),
            "time": data.get("time"),
            "version": version_info,
        },
        ensure_ascii=False,
    )
    hashed = readme or raw
    method = f"npm-registry:json+{readme_source}" if readme else "npm-registry:json"
    return replace(
        item,
        title=name,
        author=_author(data, version_info),
        published_at=_release_date(data.get("time"), latest) or item.published_at,
        canonical_url=canonical_url,
        raw_text=raw,
        extracted_text=readme,
        summary=_clean(_pick(data, version_info, "description")),
        concepts=_keywords(_pick(data, version_info, "keywords")),
        links=_links(data, version_info, canonical_url),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "npm",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _pick(data: dict[str, Any], version_info: dict[str, Any], key: str) -> Any:
    """A field from the packument top level, falling back to the latest version.

    The full document mirrors the latest version's descriptive fields at
    the top level, but not always, so the version object is the fallback.
    """
    value = data.get(key)
    if value in (None, "", [], {}):
        return version_info.get(key)
    return value


def _clean(value: Any) -> str | None:
    """A non-empty trimmed string, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _resolve_readme(
    data: dict[str, Any], version_info: dict[str, Any], get_bytes: GetBytes
) -> tuple[str | None, str | None]:
    """The package README and where it came from, or (None, None).

    Prefer the packument's `readme` (one GET, already in hand); fall back
    to extracting it from the published tarball when the registry doesn't
    carry one — common for high-traffic packages whose top-level `readme`
    is empty. The second element is the `extraction_method` suffix, so a
    scroll records which path produced its body.
    """
    packument_readme = _clean(data.get("readme"))
    if packument_readme and packument_readme != _NO_README:
        return packument_readme, "readme"
    tarball_readme = _readme_from_tarball(version_info, get_bytes)
    if tarball_readme:
        return tarball_readme, "tarball-readme"
    return None, None


def _readme_from_tarball(
    version_info: dict[str, Any], get_bytes: GetBytes
) -> str | None:
    """The root README extracted from the latest version's tarball, or None.

    npm tarballs are gzipped tars with every file under `package/`. The
    download is capped (`_MAX_TARBALL_BYTES`) and every failure mode —
    no tarball URL, an oversized or unreachable download, a corrupt
    archive, no root README — degrades to None so the scroll is
    metadata-only rather than broken (the graceful-degradation rule,
    ADR 0002).
    """
    dist = version_info.get("dist")
    tarball_url = dist.get("tarball") if isinstance(dist, dict) else None
    if not isinstance(tarball_url, str) or not tarball_url:
        return None
    try:
        blob = get_bytes(tarball_url, max_bytes=_MAX_TARBALL_BYTES)
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
            member = _pick_readme_member(archive.getmembers())
            if member is None:
                return None
            extracted = archive.extractfile(member)
            if extracted is None:
                return None
            text = extracted.read().decode("utf-8", errors="replace")
    except (OSError, ValueError, tarfile.TarError, EOFError):
        return None
    return _clean(text)


def _pick_readme_member(members: list[tarfile.TarInfo]) -> tarfile.TarInfo | None:
    """The best root README among tar members: `package/README*`, `.md` first.

    Only files one level under `package/` count, so a `package/docs/README`
    never masks the real one. Among candidates a Markdown README wins, then
    a `.markdown`, then anything else, ties broken by path for determinism.
    """
    candidates = [
        m
        for m in members
        if m.isfile() and re.fullmatch(r"package/[^/]+", m.name)
        and m.name.rsplit("/", 1)[1].lower().startswith("readme")
    ]
    if not candidates:
        return None

    def rank(member: tarfile.TarInfo) -> tuple[int, str]:
        lower = member.name.lower()
        ext = 0 if lower.endswith(".md") else 1 if lower.endswith(".markdown") else 2
        return ext, member.name

    return min(candidates, key=rank)


def _author(data: dict[str, Any], version_info: dict[str, Any]) -> str | None:
    """The package author's name, falling back to the first maintainer.

    npm's `author`/`maintainer` is either an object `{name, email, url}`
    or the string form `"Name <email> (url)"`.
    """
    name = _person_name(data.get("author")) or _person_name(version_info.get("author"))
    if name:
        return name
    maintainers = data.get("maintainers") or version_info.get("maintainers") or []
    if isinstance(maintainers, list):
        for entry in maintainers:
            person = _person_name(entry)
            if person:
                return person
    return None


def _person_name(value: Any) -> str | None:
    """A person's name from npm's object or `"Name <email> (url)"` string form."""
    if isinstance(value, dict):
        return _clean(value.get("name"))
    text = _clean(value)
    if not text:
        return None
    return _clean(re.split(r"[<(]", text, maxsplit=1)[0])


def _keywords(raw: Any) -> tuple[str, ...]:
    """Author-declared keywords as deduped concepts (the github-topics parallel).

    npm keywords are a JSON array; a comma-separated string is tolerated
    defensively the way the PyPI adapter does (ADR 0034).
    """
    if isinstance(raw, (list, tuple)):
        values = [str(value) for value in raw]
    else:
        text = _clean(raw)
        if not text:
            return ()
        values = text.split(",")
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def _links(
    data: dict[str, Any], version_info: dict[str, Any], canonical: str
) -> tuple[str, ...]:
    """Declared homepage and repository as deduped http(s) links.

    The repository's VCS URL (`git+https://…​.git`, `git://…`, `git@…`,
    `github:owner/repo`) is normalized to a clean https URL so
    `scrolls related` resolves it to the same github repo the package
    ships from (ADR 0023, ADR 0028). The npm page itself (the canonical
    URL) is dropped, and trailing-slash variants collapse to one.
    """
    canonical_key = (canonical or "").rstrip("/")
    candidates = [
        _clean(_pick(data, version_info, "homepage")),
        _repo_url(data.get("repository") or version_info.get("repository")),
    ]
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
    """A package's repository as a clean https URL, or None.

    npm stores the repository as `{type, url}` or a bare string. The URL
    arrives in many VCS spellings; normalizing them to https with no
    `.git` suffix is what lets `detect_source` read a clean `owner/repo`.
    """
    if isinstance(repository, dict):
        raw = repository.get("url")
    elif isinstance(repository, str):
        raw = repository
    else:
        raw = None
    raw = _clean(raw)
    return _normalize_git_url(raw) if raw else None


def _normalize_git_url(raw: str) -> str | None:
    """Collapse a git remote spelling to a clean https URL, `.git` dropped."""
    url = raw.strip()
    if url.startswith("git+"):
        url = url[len("git+"):]
    # scp-like / ssh-with-user: (ssh://)?git@host[:/]owner/repo
    scp = re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+)$", url)
    if scp:
        url = f"https://{scp.group(1)}/{scp.group(2)}"
    elif url.startswith("git://"):
        url = "https://" + url[len("git://"):]
    elif url.startswith("ssh://"):
        url = "https://" + url[len("ssh://"):]
    elif url.startswith("github:"):
        url = "https://github.com/" + url[len("github:"):]
    if not url.lower().startswith(("http://", "https://")):
        return None
    if url.endswith(".git"):
        url = url[: -len(".git")]
    return url


def _latest_version(data: dict[str, Any]) -> str | None:
    """The `dist-tags.latest` version pointer, or None."""
    dist_tags = data.get("dist-tags")
    if isinstance(dist_tags, dict):
        latest = dist_tags.get("latest")
        if isinstance(latest, str) and latest:
            return latest
    return None


def _release_date(time: Any, latest: str | None) -> str | None:
    """The latest version's publish time as UTC ISO 8601, or None.

    npm's `time` map keys each version to its publish timestamp, plus
    `created`/`modified` for the package. The latest version's stamp is
    the publish moment; `modified` is the fallback when it is absent.
    """
    if not isinstance(time, dict):
        return None
    for key in (latest, "modified"):
        if not key:
            continue
        stamp = to_utc_iso(time.get(key)) if isinstance(time.get(key), str) else None
        if stamp:
            return stamp
    return None


_get_json = http.get_json
_get_bytes = http.get_bytes
