"""Bitbucket Cloud fetch adapter (IDEAS.md §6, ADR 0057).

The fourth code host after GitHub (ADR 0007), GitLab (ADR 0055), and
Gitea/Forgejo (ADR 0056) — "the remaining big one" the architecture doc named.
Bitbucket *Cloud* is a single hosted service (`api.bitbucket.org/2.0`), so —
unlike Gitea, whose API lives on each instance's own host — its identity is
github's flat `<workspace>/<repo>` with one fixed API host. Bitbucket
*Server*/Data Center (self-hosted, a different `/rest/api/1.0/` API) is deferred
exactly as self-hosted GitLab is (ADR 0055).

Repository metadata comes from the keyless
`GET /2.0/repositories/<workspace>/<repo>`. Two things make the mapping
distinct from its siblings:

- **No topics.** Bitbucket Cloud has no repository-topics feature, so
  `concepts` are empty *by design* (the Go/RubyGems posture, ADR 0040/0042) —
  there is nothing author-curated to feed the KB's concept pages. The repo's
  `language` is the one structured facet Bitbucket offers, so it becomes the
  single `tag` (the registries' SPDX-license-as-tag slot, ADR 0036/0055);
  github ignores `language` because its richer `topics` fill that role.
- **README via the `/src` route.** Bitbucket exposes no auto-detecting
  `/readme` endpoint (github) and no `/raw/` route (gitea); a file's body comes
  from `GET /2.0/repositories/<ws>/<repo>/src/<commit>/<path>`, where `<commit>`
  may be a branch name. So the adapter reads the repo's `mainbranch.name` and
  fetches `README.md` first (one fast keyless GET, the common case), falling
  back to a root listing (`/src/<branch>/`) to find a differently-named README
  — the gitea README pattern (ADR 0056) on Bitbucket's src endpoint.

Setting `BITBUCKET_TOKEN` sends `Authorization: Bearer <token>` (a Bitbucket
access token / API token) to lift the unauthenticated rate limit and reach
private repos the caller can read; both raw payloads are kept in `raw_text` for
rebuilds.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

API_ROOT = "https://api.bitbucket.org/2.0"

GetJson = Callable[[str], Any]
GetText = Callable[[str], str]


def fetch_item(
    item: ScrollItem,
    *,
    get_json: GetJson | None = None,
    get_text: GetText | None = None,
) -> ScrollItem:
    """Fetch a detected Bitbucket repo's metadata and README; return it at stage 'fetched'.

    Raises FetchError when the repo identity is missing or malformed, or the
    repo request fails; a missing README only downgrades the item to
    metadata-only. The input item is never mutated.
    """
    get_json = get_json or _get_json
    get_text = get_text or _get_text
    if not item.source_id or "/" not in item.source_id:
        raise FetchError(f"cannot determine bitbucket repository for item {item.id!r}")

    repo_url = f"{API_ROOT}/repositories/{item.source_id}"
    try:
        repo = get_json(repo_url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"bitbucket API request failed: {exc}") from exc
    if not isinstance(repo, dict):
        raise FetchError(f"unexpected bitbucket repo payload for item {item.id!r}")

    # The README is optional: Bitbucket has no auto-README endpoint, so it is
    # fetched README.md-first via the `/src/<mainbranch>` route, with a
    # repo-root listing fallback for a differently-named one. A failure at any
    # step degrades to a metadata-only scroll, never a failed fetch.
    readme = _fetch_readme(repo_url, repo, get_json, get_text)

    hashed = readme or json.dumps(repo, sort_keys=True, ensure_ascii=False)
    return replace(
        item,
        title=repo.get("full_name") or item.title,
        author=_author(repo),
        published_at=to_utc_iso(repo.get("created_on")) or item.published_at,
        canonical_url=_html_url(repo),
        raw_text=json.dumps({"repo": repo, "readme": readme}, ensure_ascii=False),
        extracted_text=readme,
        summary=repo.get("description") or None,
        # Bitbucket Cloud has no repository-topics feature, so `concepts` stay
        # empty by design (the detected item's default); `language` is the one
        # facet it offers and becomes the single `tag`.
        tags=_language_tags(repo),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "bitbucket",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "bitbucket-api:repo+readme" if readme else "bitbucket-api:repo",
        },
        stage="fetched",
    )


def _fetch_readme(
    repo_url: str, repo: dict[str, Any], get_json: GetJson, get_text: GetText
) -> str | None:
    """The repo's README as raw text, or None when absent/blank/unfetchable.

    README.md-first via the `/src/<mainbranch>/README.md` route (the dominant
    case, one fast keyless GET), then a root listing only for a differently-named
    README. Any failure at any step (no main branch on an empty repo, a 404, a
    blank body, a slow/failed listing) degrades to metadata-only. The listing
    path skips `README.md` since the fast path already tried it (a
    present-but-blank README.md is honestly metadata-only).
    """
    branch = (repo.get("mainbranch") or {}).get("name")
    if not branch:
        return None

    text = _fetch_raw(repo_url, branch, "README.md", get_text)
    if text is not None:
        return text

    try:
        listing = get_json(f"{repo_url}/src/{quote(branch, safe='/')}/?pagelen=100")
    except Exception:
        return None
    values = listing.get("values") if isinstance(listing, dict) else None
    if not isinstance(values, list):
        return None
    path = _pick_readme_path(values)
    if path is None or path == "README.md":
        return None
    return _fetch_raw(repo_url, branch, path, get_text)


def _fetch_raw(repo_url: str, branch: str, path: str, get_text: GetText) -> str | None:
    """A repo file's body from the `/src/<branch>/<path>` route, or None on any miss.

    Bitbucket's source endpoint serves a file's raw contents when the path
    resolves to a file (and a JSON listing when it resolves to a directory), and
    accepts a branch name in the `<commit>` position. A 404, transport error, or
    blank body all return None.
    """
    try:
        text = get_text(
            f"{repo_url}/src/{quote(branch, safe='/')}/{quote(path, safe='/')}"
        )
    except Exception:
        return None
    return text if text.strip() else None


def _pick_readme_path(entries: list[Any]) -> str | None:
    """The README-like root file's path, preferring `.md`, else None.

    Root-listing entries are `{"type": "commit_file"|"commit_directory",
    "path": ...}`; a file whose basename starts with `readme` (case-insensitive)
    is a candidate, a Markdown README wins over an `.rst`/`.txt` one, and ties
    break alphabetically so the pick is deterministic. The entry's `path` (a
    root file's path is its name) is returned, since the src route is keyed by
    path.
    """
    candidates = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "commit_file":
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            continue
        if path.rsplit("/", 1)[-1].lower().startswith("readme"):
            candidates.append(path)
    if not candidates:
        return None
    candidates.sort(key=lambda p: (not p.lower().endswith(".md"), p.lower()))
    return candidates[0]


def _author(repo: dict[str, Any]) -> str | None:
    """The owning account's name, else None.

    Bitbucket's `owner` carries a `display_name` (always, human-readable), plus
    a `nickname` (users) or `username` (teams/workspaces); the display name is
    the cleanest author, with the handles as fallbacks — github's `owner.login`
    analog.
    """
    owner = repo.get("owner") or {}
    return owner.get("display_name") or owner.get("nickname") or owner.get("username") or None


def _html_url(repo: dict[str, Any]) -> str | None:
    """The repo's web URL from `links.html.href`, else None."""
    html = (repo.get("links") or {}).get("html") or {}
    href = html.get("href")
    return href if isinstance(href, str) and href else None


def _language_tags(repo: dict[str, Any]) -> tuple[str, ...]:
    """The primary `language` as a single `tag`, or empty.

    Bitbucket has no topics and no inline license, so `language` is the one
    structured facet it offers (the registries' license-as-tag slot,
    ADR 0036/0055); an unset language (`""`/`None`) yields no tag.
    """
    language = repo.get("language")
    return (language,) if language else ()


def _api_headers() -> dict[str, str]:
    """Keyless by default; `BITBUCKET_TOKEN` lifts the rate limit (Bearer auth).

    Bitbucket Cloud access tokens / API tokens authenticate with
    `Authorization: Bearer <token>` (github's Bearer posture, ADR 0007). App
    passwords — which use Basic auth with a username — are deliberately not
    handled: the keyless public path is the dominant case.
    """
    token = os.environ.get("BITBUCKET_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _get_json(url: str) -> Any:
    return http.get_json(url, headers=_api_headers())


def _get_text(url: str) -> str:
    return http.get_text(url, headers=_api_headers())
