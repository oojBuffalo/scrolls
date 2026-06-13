"""GitHub Gist fetch adapter (IDEAS.md §6, ADR 0078).

A gist is a collection of files — the developer **code-snippet** content
type the repo adapter (ADR 0007) doesn't reach: a config, a script, a bug
repro, a notebook. The keyless GitHub REST API serves the whole gist in
*one* request — `GET /gists/<id>` inlines each file's `content` alongside
the description, owner, and dates (the Lobsters one-request economy,
ADR 0046) — so the searchable scroll needs no second fetch.

Identity is the gist id alone: the owner login that may precede it in the
URL is decorative (the API is keyed by the id and resolves the owner
itself, ADR 0078), so every URL form for one gist dedupes. The files'
contents become the `extracted_text` (each a fenced section, sorted by
filename); the distinct file languages become `tags` — the one structured
facet a gist offers, the bitbucket `language`→tag mapping (ADR 0057) —
while `concepts` stay empty (a gist has no topic facet, the bitbucket/go
posture) and there is **no category default** (a snippet is heterogeneous,
like a Hacker News post — ADR 0031). Setting `GITHUB_TOKEN`/`GH_TOKEN`
lifts the unauthenticated rate limit, github's posture; the raw gist JSON
is kept in `raw_text` for rebuilds.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

API_ROOT = "https://api.github.com"
_API_VERSION = "2022-11-28"

GetJson = Callable[[str], dict[str, Any]]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected gist's files and metadata; return it at stage 'fetched'.

    Raises FetchError when the gist id is missing or the API request fails. A
    gist whose files are all empty degrades to a metadata-only scroll rather
    than failing (the README-less-repo degrade). The input item is never
    mutated.
    """
    get_json = get_json or _get_json
    if not item.source_id:
        raise FetchError(f"cannot determine gist id for item {item.id!r}")

    try:
        gist = get_json(f"{API_ROOT}/gists/{item.source_id}")
    except (OSError, ValueError) as exc:
        raise FetchError(f"github gist API request failed: {exc}") from exc

    files = gist.get("files") or {}
    filenames = sorted(files)
    description = (gist.get("description") or "").strip()
    body = _render_files(files, filenames)

    hashed = body or json.dumps(gist, sort_keys=True, ensure_ascii=False)
    return replace(
        item,
        title=description or (filenames[0] if filenames else f"Gist {item.source_id}"),
        author=(gist.get("owner") or {}).get("login") or None,
        published_at=to_utc_iso(gist.get("created_at")) or item.published_at,
        canonical_url=gist.get("html_url"),
        raw_text=json.dumps(gist, ensure_ascii=False),
        extracted_text=body,
        summary=_file_listing(filenames),
        tags=_languages(files, filenames),
        concepts=(),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "gist",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "github-api:gist",
        },
        stage="fetched",
    )


def _render_files(files: dict[str, Any], filenames: list[str]) -> str | None:
    """The gist's files as one searchable Markdown body, or None if all blank.

    Each file becomes a `### <filename>` heading and a fenced code block hinted
    with the file's language; files are emitted in sorted-filename order so the
    body (and its content hash) is deterministic, and a blank file is skipped.
    """
    sections = []
    for name in filenames:
        info = files[name] or {}
        content = info.get("content") or ""
        if not content.strip():
            continue
        language = (info.get("language") or "").lower()
        sections.append(f"### {name}\n\n```{language}\n{content}\n```")
    return "\n\n".join(sections) or None


def _file_listing(filenames: list[str]) -> str | None:
    """A `N files: a, b` manifest summary, or None for a fileless gist.

    A gist's description is its `title`; the summary is the manifest of what the
    snippet contains — informative at a glance and searchable whether or not the
    gist has a description.
    """
    if not filenames:
        return None
    count = f"{len(filenames)} file{'s' if len(filenames) != 1 else ''}"
    return f"{count}: " + ", ".join(filenames)


def _languages(files: dict[str, Any], filenames: list[str]) -> tuple[str, ...]:
    """The distinct file languages in first-appearance order — the one tag facet."""
    languages: list[str] = []
    for name in filenames:
        language = (files[name] or {}).get("language")
        if language and language not in languages:
            languages.append(language)
    return tuple(languages)


def _api_headers() -> dict[str, str]:
    # Mirrors github's auth: a gist shares the same API host, rate limit, and
    # token env vars (GITHUB_TOKEN / GH_TOKEN), ADR 0007.
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": _API_VERSION,
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_json(url: str) -> dict[str, Any]:
    return http.get_json(url, headers=_api_headers())
