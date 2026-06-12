"""GitHub fetch adapter (IDEAS.md §6, ADR 0007).

Repository metadata comes from the keyless GitHub REST API; the
searchable content is the README, fetched as base64 JSON and decoded
locally so the shared transport needs no media-type negotiation. The
README is optional enrichment: repos without one still become
metadata-only scrolls, and `provenance.extraction_method` records which
path produced the item. Author-curated repo topics become `concepts` —
the first adapter to populate them, feeding the KB's concept pages.
Setting `GITHUB_TOKEN` (or `GH_TOKEN`) lifts the unauthenticated rate
limit; both raw payloads are kept in `raw_text` for rebuilds.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

API_ROOT = "https://api.github.com"
_API_VERSION = "2022-11-28"

GetJson = Callable[[str], dict[str, Any]]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected GitHub repo's metadata and README; return it at stage 'fetched'.

    Raises FetchError when the repo identity is missing or the repo request
    fails; a missing README only downgrades the item to metadata-only. The
    input item is never mutated.
    """
    get_json = get_json or _get_json
    if not item.source_id or "/" not in item.source_id:
        raise FetchError(f"cannot determine github repository for item {item.id!r}")

    repo_url = f"{API_ROOT}/repos/{item.source_id}"
    try:
        repo = get_json(repo_url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"github API request failed: {exc}") from exc

    # The README is optional: missing files 404 and odd payloads decode to
    # nothing, and neither should fail an otherwise-identified repo.
    try:
        readme = _decode_readme(get_json(f"{repo_url}/readme"))
    except Exception:
        readme = None

    hashed = readme or json.dumps(repo, sort_keys=True, ensure_ascii=False)
    return replace(
        item,
        title=repo.get("full_name") or item.title,
        author=(repo.get("owner") or {}).get("login") or None,
        published_at=repo.get("created_at") or None,
        canonical_url=repo.get("html_url"),
        raw_text=json.dumps({"repo": repo, "readme": readme}, ensure_ascii=False),
        extracted_text=readme,
        summary=repo.get("description") or None,
        concepts=tuple(repo.get("topics") or ()),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "github",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "github-api:repo+readme" if readme else "github-api:repo",
        },
        stage="fetched",
    )


def _decode_readme(payload: dict[str, Any]) -> str | None:
    if payload.get("encoding") != "base64":
        return None
    # b64decode discards the newlines GitHub chunks content with
    decoded = base64.b64decode(payload.get("content") or "").decode(
        "utf-8", errors="replace"
    )
    return decoded if decoded.strip() else None


def _api_headers() -> dict[str, str]:
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
