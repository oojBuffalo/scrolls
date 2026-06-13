"""crates.io fetch adapter (IDEAS.md §6, ADR 0036).

A saved crates.io crate page becomes a clean scroll instead of a
`trafilatura` scrape of its HTML. One GET against the keyless crates.io
JSON API (`crates.io/api/v1/crates/<name>`) returns the crate's full
metadata document — no auth, no runtime dependency. This is the Rust
sibling of the PyPI and npm adapters (ADR 0034, ADR 0035): the same
JSON-metadata shape, the same keywords→concepts / links→repo mapping.

Two facts shape the design, both confirmed by smoke-testing the live API:

1. **Identity is the name, normalized.** crates.io is case-insensitive
   and treats `-` and `_` as equivalent (`serde_json`, `serde-json`,
   and `SERDE_JSON` all resolve to one crate), so the source id folds
   them — the PyPI/PEP 503 spirit. The canonical published name (which
   the registry preserves, e.g. `serde_json` keeps its underscore) is
   read back from the response for the canonical URL and the download
   path, so a normalized id never breaks the fetch.

2. **The README lives only in the published `.crate` tarball.** Unlike
   npm's packument, the crates.io JSON carries no inline README — only a
   `readme_path` to an *HTML*-rendered endpoint. The canonical raw
   Markdown README ships inside the version's `.crate` (a gzipped tar
   with everything under `<name>-<version>/`), so the adapter downloads
   that capped tarball and extracts `README*` — reusing the bounded
   `http.get_bytes(max_bytes=…)` npm introduced (ADR 0035). Every
   tarball failure degrades to a metadata-only scroll (ADR 0002).

The crate's author-declared keywords become `concepts` the way github
repo topics do (ADR 0007); the curated category taxonomy's display names
become `tags`, the structured-taxonomy slot PyPI's trove classifiers and
arXiv's codes fill (ADR 0034, ADR 0008); and the homepage, docs, and
repository become `links`, the repository normalized so `scrolls related`
connects a crate to a saved github repo it ships from (the crate↔repo
edge). The chosen version's metadata is kept in `raw_text` for rebuilds.
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

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

API_ROOT = "https://crates.io/api/v1/crates"
SITE_ROOT = "https://crates.io"

# The `.crate` tarball is the source archive; cap the download so a crate
# that vendors large fixtures degrades to metadata-only rather than
# buffering tens of MB (the npm tarball cap, ADR 0035).
_MAX_TARBALL_BYTES = 8 * 1024 * 1024

GetJson = Callable[[str], Any]
GetBytes = Callable[..., bytes]


def fetch_item(
    item: ScrollItem,
    *,
    get_json: GetJson | None = None,
    get_bytes: GetBytes | None = None,
) -> ScrollItem:
    """Fetch a detected crate's metadata; return it at stage 'fetched'.

    Raises FetchError when the crate name is missing, the request fails,
    or the registry has no such crate. The input item is never mutated.
    """
    get_json = get_json or _get_json
    get_bytes = get_bytes or _get_bytes
    if not item.source_id:
        raise FetchError(f"cannot determine crate for item {item.id!r}")

    url = f"{API_ROOT}/{item.source_id}"
    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"crates.io API request failed: {exc}") from exc

    crate = data.get("crate") if isinstance(data, dict) else None
    name = crate.get("name") if isinstance(crate, dict) else None
    if not isinstance(name, str) or not name:
        raise FetchError(f"crate not found: {item.source_id}")

    version = _select_version(data, crate)
    readme = _readme_from_tarball(version, get_bytes)
    canonical_url = f"{SITE_ROOT}/crates/{name}"
    raw = json.dumps(
        {
            "crate": crate,
            "version": version,
            "keywords": data.get("keywords"),
            "categories": data.get("categories"),
        },
        ensure_ascii=False,
    )
    hashed = readme or raw
    method = "crates-api:json+tarball-readme" if readme else "crates-api:json"
    return replace(
        item,
        title=name,
        author=_publisher(version),
        published_at=_release_date(version) or item.published_at,
        canonical_url=canonical_url,
        raw_text=raw,
        extracted_text=readme,
        summary=_clean(crate.get("description")),
        tags=_categories(data, crate),
        concepts=_keywords(data, crate),
        links=_links(crate, canonical_url),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "crates",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _clean(value: Any) -> str | None:
    """A non-empty trimmed string, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _select_version(data: dict[str, Any], crate: dict[str, Any]) -> dict[str, Any]:
    """The crate's displayed version object, or the newest available, or {}.

    crates.io shows `default_version` on the crate page; that is the
    version a scroll should track (the PyPI/npm "latest release" choice).
    The `versions` array carries each version's download path, publish
    time, and publisher, so the chosen number is resolved to its object.
    Fallbacks walk newest/max-stable and finally the first listed version,
    so a malformed or partial response still yields *a* version.
    """
    versions = data.get("versions")
    if not isinstance(versions, list):
        return {}
    by_num = {v.get("num"): v for v in versions if isinstance(v, dict)}
    for key in ("default_version", "newest_version", "max_stable_version"):
        chosen = by_num.get(crate.get(key))
        if isinstance(chosen, dict):
            return chosen
    first = versions[0] if versions else None
    return first if isinstance(first, dict) else {}


def _readme_from_tarball(
    version: dict[str, Any], get_bytes: GetBytes
) -> str | None:
    """The root README extracted from the version's `.crate` tarball, or None.

    A `.crate` is a gzipped tar with every file under `<name>-<version>/`.
    The download is capped (`_MAX_TARBALL_BYTES`) and every failure mode —
    no download path, an oversized or unreachable download, a corrupt
    archive, no root README — degrades to None so the scroll is
    metadata-only rather than broken (graceful degradation, ADR 0002).
    """
    dl_path = version.get("dl_path")
    if not isinstance(dl_path, str) or not dl_path:
        return None
    tarball_url = dl_path if dl_path.startswith(("http://", "https://")) else SITE_ROOT + dl_path
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
    """The best root README among tar members: `<dir>/README*`, `.md` first.

    A `.crate` has a single top-level `<name>-<version>/` directory, so a
    file exactly one level deep is at the crate root; a `<dir>/docs/README`
    never masks the real one. Among candidates a Markdown README wins, then
    a `.markdown`, then anything else, ties broken by path for determinism
    (the npm ranking, ADR 0035).
    """
    candidates = [
        m
        for m in members
        if m.isfile() and re.fullmatch(r"[^/]+/[^/]+", m.name)
        and m.name.rsplit("/", 1)[1].lower().startswith("readme")
    ]
    if not candidates:
        return None

    def rank(member: tarfile.TarInfo) -> tuple[int, str]:
        lower = member.name.lower()
        ext = 0 if lower.endswith(".md") else 1 if lower.endswith(".markdown") else 2
        return ext, member.name

    return min(candidates, key=rank)


def _release_date(version: dict[str, Any]) -> str | None:
    """The chosen version's publish time as UTC ISO 8601, or None.

    Guarded with `isinstance` because `to_utc_iso` strips its argument:
    a malformed non-string `created_at` (which `_select_version`'s
    fallbacks anticipate) becomes None rather than raising.
    """
    created = version.get("created_at")
    return to_utc_iso(created) if isinstance(created, str) else None


def _publisher(version: dict[str, Any]) -> str | None:
    """The version's publisher name, falling back to their login, or None.

    crates.io has no crate-level author field; `published_by` is the
    closest honest "author" — the account that published the version.
    """
    person = version.get("published_by")
    if isinstance(person, dict):
        return _clean(person.get("name")) or _clean(person.get("login"))
    return None


def _keywords(data: dict[str, Any], crate: dict[str, Any]) -> tuple[str, ...]:
    """Author-declared keywords as deduped concepts (the github-topics parallel).

    The top-level `keywords` array carries the rich objects; the crate's
    own `keywords` list of bare strings is the fallback.
    """
    rich = data.get("keywords")
    if isinstance(rich, list):
        values = [k.get("keyword") for k in rich if isinstance(k, dict)]
    else:
        values = crate.get("keywords") if isinstance(crate.get("keywords"), list) else []
    return _dedupe(values)


def _categories(data: dict[str, Any], crate: dict[str, Any]) -> tuple[str, ...]:
    """The curated category taxonomy's display names as deduped tags.

    crates.io categories are a controlled vocabulary (like PyPI's trove
    classifiers and arXiv's codes), so they fill the structured-taxonomy
    `tags` slot. The top-level `categories` array carries the readable
    display name (`category`); the crate's bare slug list is the fallback.
    """
    rich = data.get("categories")
    if isinstance(rich, list):
        values = [c.get("category") for c in rich if isinstance(c, dict)]
    else:
        values = crate.get("categories") if isinstance(crate.get("categories"), list) else []
    return _dedupe(values)


def _dedupe(values: Any) -> tuple[str, ...]:
    """Non-empty trimmed strings, order-preserving and deduped."""
    if not isinstance(values, list):
        return ()
    cleaned = (_clean(v) for v in values)
    return tuple(dict.fromkeys(v for v in cleaned if v))


def _links(crate: dict[str, Any], canonical: str) -> tuple[str, ...]:
    """Declared homepage, documentation, and repository as deduped http(s) links.

    The repository's `.git` suffix is dropped so `scrolls related` resolves
    it to the same github repo the crate ships from (ADR 0023, ADR 0028 —
    the crate↔repo edge). The crates.io page itself (the canonical URL) is
    dropped, and trailing-slash variants collapse to one.
    """
    canonical_key = (canonical or "").rstrip("/")
    candidates = [
        _clean(crate.get("homepage")),
        _clean(crate.get("documentation")),
        _repo_url(crate.get("repository")),
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
    """A crate's repository as a clean https URL with no `.git` suffix, or None.

    crates.io stores the author's `Cargo.toml` `repository` verbatim —
    usually a clean https URL, occasionally with a trailing `.git`. Folding
    `git+` and `.git` is what lets `detect_source` read a clean `owner/repo`.
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
_get_bytes = http.get_bytes
