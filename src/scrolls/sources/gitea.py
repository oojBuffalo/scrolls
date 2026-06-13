"""Gitea/Forgejo fetch adapter (IDEAS.md §6, ADR 0056).

The third code host after GitHub (ADR 0007) and GitLab (ADR 0055), and the
first whose API lives on each *instance's own host* rather than a single
fixed endpoint: Codeberg's is `codeberg.org/api/v1`, gitea.com's is
`gitea.com/api/v1`. So — like the Fediverse sources (ADR 0049–0054) — the
instance host rides in the identity (`gitea:<host>/<owner>/<repo>`), and the
adapter reconstructs the API root from it. (github/gitlab can hardcode one
API host because each is a single service; the Gitea software is deployed
per-host.)

One adapter serves both Gitea and its API-compatible soft-fork Forgejo
(Codeberg runs Forgejo, gitea.com runs Gitea), exactly as the mastodon
adapter serves GoToSocial and Pleroma (ADR 0050): Forgejo implements the
"Gitea API v1" surface this adapter speaks, so the `source` stays `gitea`
and which software answered is not read off the URL.

Repository metadata comes from the keyless `GET /api/v1/repos/<owner>/<repo>`;
`topics` is inline on modern Gitea/Forgejo, so repo topics become `concepts`
like github's (ADR 0007) with no second call. The README is optional
enrichment: Gitea has no auto-detecting `/readme` endpoint (unlike github), so
the adapter tries the dominant `README.md` via the keyless API raw route first
(one fast GET, the common case), and only when that misses lists the repo root
(`/contents`) to find a differently-named README (`README.rst`, `readme.txt`)
and fetch that — degrading to a metadata-only scroll when there is none. The
raw route is the *API* one (`/api/v1/.../raw/<path>`), not the listing's
`download_url`: that web route 303-redirects anonymous gitea.com clients to a
login page, and listing a large repo's root can be slow (forgejo/forgejo times
out), so README.md-first keeps the common case fast and robust. Setting
`GITEA_TOKEN` (or `FORGEJO_TOKEN`) sends
Gitea's `Authorization: token <token>` header to lift the rate limit and
reach private repos the caller can read; both raw payloads are kept in
`raw_text` for rebuilds.
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

GetJson = Callable[[str], Any]
GetText = Callable[[str], str]


def fetch_item(
    item: ScrollItem,
    *,
    get_json: GetJson | None = None,
    get_text: GetText | None = None,
) -> ScrollItem:
    """Fetch a detected Gitea/Forgejo repo's metadata and README; return it at stage 'fetched'.

    Raises FetchError when the repo identity is missing or malformed, or the
    repo request fails; a missing README only downgrades the item to
    metadata-only. The input item is never mutated.
    """
    get_json = get_json or _get_json
    get_text = get_text or _get_text

    host, owner, name = _split_source_id(item)
    repo_url = f"https://{host}/api/v1/repos/{owner}/{name}"
    try:
        repo = get_json(repo_url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"gitea API request failed: {exc}") from exc
    if not isinstance(repo, dict):
        raise FetchError(f"unexpected gitea repo payload for item {item.id!r}")

    # The README is optional: Gitea exposes no auto-README endpoint, so it is
    # fetched README.md-first via the API raw route, with a repo-root listing
    # fallback for a differently-named one. A failure at any step degrades to a
    # metadata-only scroll, never a failed fetch.
    readme = _fetch_readme(repo_url, get_json, get_text)

    hashed = readme or json.dumps(repo, sort_keys=True, ensure_ascii=False)
    return replace(
        item,
        title=repo.get("full_name") or item.title,
        author=_author(repo),
        published_at=to_utc_iso(repo.get("created_at")) or item.published_at,
        canonical_url=repo.get("html_url"),
        raw_text=json.dumps({"repo": repo, "readme": readme}, ensure_ascii=False),
        extracted_text=readme,
        summary=repo.get("description") or None,
        concepts=tuple(t for t in (repo.get("topics") or ()) if t),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "gitea",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "gitea-api:repo+readme" if readme else "gitea-api:repo",
        },
        stage="fetched",
    )


def _split_source_id(item: ScrollItem) -> tuple[str, str, str]:
    """`<host>, <owner>, <repo>` from a `<host>/<owner>/<repo>` source id.

    The host rides in the id because the Gitea API lives on each instance's
    own host (Codeberg, gitea.com), unlike github/gitlab's single API host —
    the Fediverse identity shape (ADR 0049). Raises FetchError on a missing or
    short id so an unfetchable registration (a profile or site route) fails
    cleanly rather than hitting a malformed URL.
    """
    parts = (item.source_id or "").split("/")
    if len(parts) < 3 or not all(parts[:3]):
        raise FetchError(f"cannot determine gitea repository for item {item.id!r}")
    return parts[0], parts[1], parts[2]


def _fetch_readme(repo_url: str, get_json: GetJson, get_text: GetText) -> str | None:
    """The repo's README as raw text, or None when absent/blank/unfetchable.

    README.md-first (the dominant case, one fast keyless GET), then a root
    listing only for a differently-named README. Any failure at any step (a
    404, an empty repo, a slow/failed listing, a blank body) degrades to
    metadata-only. The listing path skips `README.md` since the fast path
    already tried it (a present-but-blank README.md is honestly metadata-only).
    """
    text = _fetch_raw(repo_url, "README.md", get_text)
    if text is not None:
        return text

    try:
        entries = get_json(f"{repo_url}/contents")
    except Exception:
        return None
    if not isinstance(entries, list):
        return None
    path = _pick_readme_path(entries)
    if path is None or path == "README.md":
        return None
    return _fetch_raw(repo_url, path, get_text)


def _fetch_raw(repo_url: str, path: str, get_text: GetText) -> str | None:
    """A repo file's bytes from the keyless API raw route, or None on any miss.

    The *API* raw route (`/api/v1/.../raw/<path>`, default branch) is used, not
    the listing's web `download_url`, because the web route 303-redirects
    anonymous gitea.com clients to a login page (urllib would follow it and
    capture HTML). A 404, transport error, or blank body all return None.
    """
    try:
        text = get_text(f"{repo_url}/raw/{quote(path, safe='/')}")
    except Exception:
        return None
    return text if text.strip() else None


def _pick_readme_path(entries: list[Any]) -> str | None:
    """The README-like root file's path, preferring `.md`, else None.

    Files whose name starts with `readme` (case-insensitive) are candidates;
    a Markdown README wins over an `.rst`/`.txt` one, and ties break
    alphabetically so the pick is deterministic. The entry's `path` (a root
    file's path is its name) is returned, since the raw route is keyed by path.
    """
    candidates = [
        e
        for e in entries
        if isinstance(e, dict)
        and e.get("type") == "file"
        and isinstance(e.get("name"), str)
        and e["name"].lower().startswith("readme")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda e: (not e["name"].lower().endswith(".md"), e["name"].lower()))
    chosen = candidates[0]
    path = chosen.get("path") or chosen.get("name")
    return path if isinstance(path, str) and path else None


def _author(repo: dict[str, Any]) -> str | None:
    """The owning account's login (the github mapping), else None."""
    owner = repo.get("owner") or {}
    return owner.get("login") or owner.get("username") or None


def _api_headers() -> dict[str, str]:
    """Keyless by default; `GITEA_TOKEN`/`FORGEJO_TOKEN` lifts the rate limit.

    Gitea and Forgejo both accept `Authorization: token <token>`. A single
    env var applies to whatever host the id names — useful for one's own
    instance, with the caveat that a token is valid only on the instance that
    issued it (the multi-host trade-off the per-instance API forces).
    """
    token = os.environ.get("GITEA_TOKEN") or os.environ.get("FORGEJO_TOKEN")
    return {"Authorization": f"token {token}"} if token else {}


def _get_json(url: str) -> Any:
    return http.get_json(url, headers=_api_headers())


def _get_text(url: str) -> str:
    return http.get_text(url, headers=_api_headers())
