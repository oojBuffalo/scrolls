"""Gitea/Forgejo fetch adapter (IDEAS.md §6, ADR 0056, ADR 0086).

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

Issues and pull requests are a second content kind on the same source
(ADR 0086): a `/issues/<n>` or `/pulls/<n>` URL detects as a discussion thread
distinct from the repo — `<host>/<owner>/<repo>#<n>` — and `fetch_item`
dispatches on the `#` in the source id (the github one-source-many-kinds shape,
ADR 0084), keeping the repo path byte-unchanged. Gitea/Forgejo unify issue and
PR numbering like github: one `GET /repos/<o>/<r>/issues/<index>` serves both
(a PR carries a `pull_request` object), so a single `#` marker suffices —
unlike gitlab's separate iid sequences that force two markers (ADR 0085). The
host stays in the identity (the per-instance API), so the adapter rebuilds the
API root from it; the kind and state go to `tags`, the labels to `concepts`,
and — unlike gitlab — the `/issues/<n>/comments` endpoint is keyless, so the
common case reaches the whole conversation with no token.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import discussion
from scrolls.sources import http
from scrolls.sources import urls

GetJson = Callable[[str], Any]
GetText = Callable[[str], str]


def fetch_item(
    item: ScrollItem,
    *,
    get_json: GetJson | None = None,
    get_text: GetText | None = None,
) -> ScrollItem:
    """Fetch a detected Gitea/Forgejo repo or issue/PR thread; return it at stage 'fetched'.

    Dispatches on the source id: a `<host>/<owner>/<repo>#<n>` id is a discussion
    thread (`_fetch_thread`, ADR 0086), a plain `<host>/<owner>/<repo>` id is a
    repository. Raises FetchError when the identity is missing or malformed, or
    the primary request fails; an enrichment (README, comments) only downgrades
    to metadata-only. The input item is never mutated.
    """
    get_json = get_json or _get_json
    get_text = get_text or _get_text

    if "#" in (item.source_id or ""):
        return _fetch_thread(item, get_json)

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


def _fetch_thread(item: ScrollItem, get_json: GetJson) -> ScrollItem:
    """Fetch a Gitea/Forgejo issue or pull-request thread (ADR 0086).

    The source id is `<host>/<owner>/<repo>#<number>`. Gitea/Forgejo unify issue
    and PR numbering like github (ADR 0084) — one `GET /repos/<o>/<r>/issues/<index>`
    endpoint serves both, a PR carrying a `pull_request` object — so a single `#`
    marker and one GET fetch the thread; comments cost a second GET, taken only
    when the thread has any (`issue["comments"]`) and degrading to body-only on
    failure (the github/HN economy, ADR 0084/0031). The host rides in the id (the
    per-instance API, ADR 0056), so the API root is rebuilt from it. The body is
    already Markdown, so there is no HTML to strip (Lobsters' economy, ADR 0046).
    """
    ref, _, number = (item.source_id or "").partition("#")
    parts = ref.split("/")
    if len(parts) < 3 or not all(parts[:3]) or not number.isdigit():
        raise FetchError(f"cannot determine gitea thread for item {item.id!r}")
    host, owner, name = parts[0], parts[1], parts[2]
    repo = f"{owner}/{name}"

    issue_url = f"https://{host}/api/v1/repos/{repo}/issues/{number}"
    try:
        issue = get_json(issue_url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"gitea API request failed: {exc}") from exc
    if not isinstance(issue, dict) or not issue.get("number"):
        raise FetchError(f"gitea thread not found: {item.source_id}")

    comments: list[dict[str, Any]] = []
    if issue.get("comments"):
        try:
            fetched = get_json(f"{issue_url}/comments?per_page=100")
            comments = [c for c in fetched if isinstance(c, dict)]
        except Exception:
            comments = []

    body = _plain(issue.get("body") or "")
    comments_text = _format_comments(comments)
    extracted = "\n\n".join(part for part in (body, comments_text) if part) or None

    raw = json.dumps({"issue": issue, "comments": comments}, ensure_ascii=False)
    hashed = extracted or raw
    method = "gitea-api:issue+comments" if comments_text else "gitea-api:issue"
    return replace(
        item,
        title=_thread_title(repo, number, issue),
        author=_login(issue.get("user")),
        published_at=to_utc_iso(issue.get("created_at")) or item.published_at,
        canonical_url=issue.get("html_url") or item.url,
        raw_text=raw,
        extracted_text=extracted,
        summary=_thread_summary(body, issue),
        tags=_thread_tags(issue),
        concepts=_labels(issue.get("labels")),
        links=_thread_links(host, repo, issue, body),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "gitea",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _thread_title(repo: str, number: str, issue: dict[str, Any]) -> str:
    """`owner/repo#<n>: <title>` — the cross-reference leads (the github rule).

    The host stays out of the title: the repo scroll's title is its `full_name`
    (`owner/repo`, no host), and Gitea references an issue as `owner/repo#<n>`,
    so leading with that keeps a search hit or library listing self-identifying
    and consistent with the repo (the RFC number-leads-title rule, ADR 0066/0084).
    The host stays in the id and `canonical_url` for disambiguation across
    instances. A titleless thread degrades to the bare reference.
    """
    title = (issue.get("title") or "").strip()
    ref = f"{repo}#{number}"
    return f"{ref}: {title}" if title else ref


def _thread_tags(issue: dict[str, Any]) -> tuple[str, ...]:
    """The kind and lifecycle state — the facet slot, like github's thread tags.

    A PR carries a `pull_request` object whose `merged_at` distinguishes a merged
    PR from a closed-unmerged one without a second GET (the github read, ADR 0084;
    Gitea exposes the same field). An issue is just open or closed. The vocabulary
    (`open`/`closed`/`merged`) matches github's, so a `--tag merged` query spans
    both hosts.
    """
    pull = issue.get("pull_request")
    if isinstance(pull, dict):
        state = "merged" if pull.get("merged_at") else (issue.get("state") or "closed")
        return ("pull request", state)
    return ("issue", issue.get("state") or "open")


def _labels(labels: Any) -> tuple[str, ...]:
    """Issue/PR labels → `concepts`, the curated topical facet (the github rule).

    Gitea returns label objects (`{name, color, …}`); blank names are dropped
    and duplicates collapse while preserving order (github's `_labels`, ADR 0084).
    """
    names: list[str] = []
    for label in labels or ():
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str) and name.strip() and name not in names:
            names.append(name)
    return tuple(names)


def _thread_summary(body: str, issue: dict[str, Any]) -> str | None:
    """The thread's lead paragraph, else its engagement (the github/Lobsters rule).

    A thread with a body leads with it; a bare thread (an issue or PR opened with
    none) gets the honest status — the comment count — rather than an invented
    summary (ADR 0084/0031). "Gitea" names the source: one adapter serves Gitea
    and Forgejo and the URL does not say which, so the source name is used.
    Neither present leaves it empty.
    """
    if body:
        return body.split("\n\n", 1)[0].strip()
    count = issue.get("comments")
    if count is None:
        return None
    return f"Gitea discussion: {count} {'comment' if count == 1 else 'comments'}."


def _format_comments(comments: list[dict[str, Any]]) -> str:
    """The conversation as a Markdown subsection, bylined like a github thread.

    Comments without an author or body carry nothing usable and are skipped; the
    rest are bylined with the commenter (ADR 0084/0046) and assembled by the
    shared thread renderer (ADR 0093). Returns "" when nothing remains.
    """
    rendered = []
    for comment in comments:
        text = _plain(comment.get("body") or "")
        if not text:
            continue
        who = _login(comment.get("user"))
        byline = f"Comment by {who}" if who else "Comment"
        rendered.append(discussion.Comment(byline, text))
    return discussion.format_thread(rendered, heading="Comments")


def _login(user: Any) -> str | None:
    """A Gitea account's login, falling back to `username` (the repo `_author` rule).

    Gitea user objects carry both `login` and `username`; the repo adapter's
    `_author` reads either, so threads do the same for consistency.
    """
    if not isinstance(user, dict):
        return None
    return user.get("login") or user.get("username") or None


def _thread_links(host: str, repo: str, issue: dict[str, Any], body: str) -> tuple[str, ...]:
    """The repo edge plus any URLs referenced in the body.

    A thread belongs to its repository, so a `<host>/<owner>/<repo>` link makes
    the thread↔repo edge `scrolls related`/`graph` resolves to the saved repo
    item (the github issue↔repo edge, ADR 0084). URLs in the body (cross-
    references to other issues, PRs, docs) become outbound edges, deduped and
    never self-linking the thread — the shared body-link grammar (ADR 0094).
    """
    return urls.body_edge_links(f"https://{host}/{repo}", issue.get("html_url") or "", body)


def _plain(text: str) -> str:
    """Normalize a Markdown body: CRLF to LF, collapse blank runs (the github rule)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
