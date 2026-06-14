"""Hackage (Haskell) fetch adapter (IDEAS.md §6, ADR 0091).

A saved Hackage package page (`hackage.haskell.org/package/<name>`) becomes a
clean scroll instead of a `trafilatura` scrape of its JS-rendered page. Hackage
is the Haskell sibling of the package-registry family (ADR 0034–0036, 0039,
0040, 0042, 0088–0090), and the named next candidate of ADR 0090. One plain
keyless `GET hackage.haskell.org/package/<name>/<name>.cabal` returns the
latest version's **cabal** manifest — no auth, no runtime dependency, and no
version to select (the endpoint already serves the latest, like RubyGems'
inline-latest, ADR 0040).

Two facts shape the design, confirmed against the live API:

1. **Identity is the package name, case-sensitive.** Hackage package names are
   case-sensitive (`QuickCheck`, `HUnit`), and the cabal endpoint only resolves
   the exact case, so the source id is preserved verbatim — npm/RubyGems' rule
   (ADR 0035/0040), *not* the case-folding the lowercase-canonical registries
   use. A `/package/<name>-<version>` page or a subpage dedupes to the name.

2. **The cabal carries a prose body and a curated category.** Unlike the
   metadata-only registries (RubyGems/Hex), the cabal's `description` is a real
   prose body, so it becomes the searchable `extracted_text` (the `.`-only line
   is cabal's blank-line marker), with `synopsis` the short `summary` — the
   arXiv abstract+body split applied to a manifest. The `category` field is
   comma-separated curated keywords → `concepts` like github repo topics /
   PyPI keywords (ADR 0007/0034), so a Haskell package joins the KB concept
   graph. The `license` (an SPDX id on modern cabals, a legacy cabal id like
   `BSD2` on older ones — kept verbatim either way) → the one `tag`, and
   `homepage` + the `source-repository` `location` → `links`, the repository
   wiring the package↔repo edge `scrolls related` resolves to a saved github
   repo. The cabal carries no upload date, so `published_at` is honestly left
   as the feed seed (Go/NuGet's honest-empty posture, ADR 0042/0090).

A Hackage package classifies as `tool` like every other package (ADR 0004).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

API_ROOT = "https://hackage.haskell.org/package"
# A cabal file is a few KB; cap the download defensively (the npm/crates/Go/
# NuGet capped GET, ADR 0035/0042/0090).
_CABAL_MAX_BYTES = 1_000_000

_EMAIL = re.compile(r"\s*<[^>]*>")

GetText = Callable[[str], str]


def fetch_item(item: ScrollItem, *, get_text: GetText | None = None) -> ScrollItem:
    """Fetch a detected Hackage package's cabal metadata; return it 'fetched'.

    Raises FetchError when the package name is missing, the request fails, or
    the cabal has no `name` field (not a package). The input item is never
    mutated.
    """
    get_text = get_text or _get_cabal_text
    name = item.source_id
    if not name:
        raise FetchError(f"cannot determine package for item {item.id!r}")

    try:
        cabal = get_text(f"{API_ROOT}/{name}/{name}.cabal")
    except (OSError, ValueError) as exc:
        raise FetchError(f"Hackage request failed: {exc}") from exc

    fields, repo_location = _parse_cabal(cabal)
    canonical_name = fields.get("name") or name
    if not fields.get("name"):
        # a cabal with no `name` field is not a package manifest
        raise FetchError(f"package not found: {name}")

    summary = fields.get("synopsis")
    description = _description(fields.get("description"))
    canonical_url = f"{API_ROOT}/{canonical_name}"
    hashed = description or summary or cabal
    return replace(
        item,
        title=canonical_name,
        author=_byline(fields.get("author")),
        published_at=item.published_at,  # the cabal has no date — never invent
        canonical_url=canonical_url,
        raw_text=cabal,
        extracted_text=description,
        summary=summary,
        tags=_license_tags(fields.get("license")),
        concepts=_concepts(fields.get("category")),
        links=_links(fields.get("homepage"), repo_location, canonical_url),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "hackage",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "hackage-cabal",
        },
        stage="fetched",
    )


def _parse_cabal(text: str) -> tuple[dict[str, str], str | None]:
    """Parse a cabal manifest into (top-level fields, source-repository location).

    Cabal is an indentation-structured `field: value` format. Top-level package
    fields sit at column 0; a value may continue on more-indented lines. A
    column-0 line with no colon before a space is a *section* header
    (`library`, `executable foo`, `source-repository head`), whose indented
    body must not be read as package fields — only the `source-repository`
    block's `location` is wanted. Full-line `--` comments are dropped. Field
    names are lowercased; the first occurrence wins.
    """
    fields: dict[str, str] = {}
    repo_location: str | None = None
    current: str | None = None  # the top-level field currently accumulating
    in_source_repo = False
    for raw in text.splitlines():
        if raw.lstrip().startswith("--"):
            continue
        if not raw.strip():
            current = None
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 0:
            current = None
            in_source_repo = False
            head, sep, value = stripped.partition(":")
            if sep and " " not in head.strip():
                name = head.strip().lower()
                fields.setdefault(name, value.strip())
                current = name
            else:  # a section header
                in_source_repo = head.strip().lower().split()[:1] == [
                    "source-repository"
                ]
        elif in_source_repo:
            key, sep, value = stripped.partition(":")
            if sep and key.strip().lower() == "location" and repo_location is None:
                repo_location = value.strip()
        elif current is not None:
            joined = f"{fields[current]}\n{stripped}" if fields[current] else stripped
            fields[current] = joined
    return fields, repo_location


def _description(value: str | None) -> str | None:
    """A cabal description's continuation lines as prose, or None.

    A line that is just `.` is cabal/haddock's blank-line marker, so it becomes
    an empty line (a paragraph break); the rest is kept verbatim.
    """
    if not value:
        return None
    lines = ["" if line.strip() == "." else line for line in value.split("\n")]
    text = "\n".join(lines).strip()
    return text or None


def _concepts(category: str | None) -> tuple[str, ...]:
    """The comma-separated `category` field as deduped concepts, order preserved."""
    if not category:
        return ()
    parts = (part.strip() for part in category.replace("\n", " ").split(","))
    return tuple(dict.fromkeys(p for p in parts if p))


def _license_tags(license_field: str | None) -> tuple[str, ...]:
    """The `license` field verbatim as the one tag, or empty.

    Modern cabals carry an SPDX id (`BSD-3-Clause`); older ones carry cabal's
    own id (`BSD2`, `GPL-3`). Both are kept verbatim — a still-useful filter
    tag — rather than mapped, which would need a per-id table to little gain.
    """
    value = (license_field or "").strip()
    return (value,) if value else ()


def _byline(author: str | None) -> str | None:
    """The `author` field with `<email>` parts stripped, or None."""
    if not author:
        return None
    cleaned = _EMAIL.sub("", author.replace("\n", " ")).strip()
    return cleaned or None


def _links(
    homepage: str | None, repo_location: str | None, canonical: str
) -> tuple[str, ...]:
    """`homepage` and the source-repository `location` as deduped http(s) links.

    The repository (its `git+`/`.git` folded) wires the package↔repo edge
    `scrolls related` resolves to a saved github repo (the crates/Hex rule,
    ADR 0036/0089); a homepage equal to it collapses to one link, and the
    package's own Hackage page is dropped.
    """
    canonical_key = (canonical or "").rstrip("/")
    seen: set[str] = set()
    links: list[str] = []
    for candidate in (homepage, repo_location):
        url = _clean_repo(candidate)
        if not url:
            continue
        key = url.rstrip("/")
        if key == canonical_key or key in seen:
            continue
        seen.add(key)
        links.append(url)
    return tuple(links)


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


def _get_cabal_text(url: str) -> str:
    """Default cabal fetcher: a capped GET decoded as UTF-8."""
    return http.get_bytes(url, max_bytes=_CABAL_MAX_BYTES).decode(
        "utf-8", errors="replace"
    )
