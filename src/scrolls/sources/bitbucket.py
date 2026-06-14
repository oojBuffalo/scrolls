"""Bitbucket Cloud fetch adapter (IDEAS.md §6, ADR 0057, ADR 0087).

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

Issues and pull requests are a second content kind on the same source
(ADR 0087): a `/issues/<n>` or `/pull-requests/<n>` URL detects as a discussion
thread distinct from the repo, and `fetch_item` dispatches on a marker in the
source id (the gitlab one-source-many-kinds shape, ADR 0085). Bitbucket — like
gitlab, *unlike* github/gitea — keeps **separate** numbering for issues and PRs
on **separate** endpoints (`/issues/<n>` vs `/pullrequests/<n>`), so a bare
`#<n>` is ambiguous; the gitlab cross-reference markers disambiguate and pick
the endpoint — `workspace/repo#<n>` for an issue, `workspace/repo!<n>` for a
pull request. The fourth and last of the web-discoverable code hosts to carry
threads. Note Bitbucket Cloud's native **issue tracker is deprecated by
Atlassian** (its API returns `410 Gone` on repos with issues disabled, which is
now most of them), so the issue path degrades honestly while the pull-request
path — the common, still-supported case — is the live-verified one.
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
    """Fetch a detected Bitbucket repo or issue/PR thread; return it at stage 'fetched'.

    Dispatches on the source id: a `workspace/repo#<n>` (issue) or
    `workspace/repo!<n>` (pull request) id is a discussion thread
    (`_fetch_thread`, ADR 0087), a plain `workspace/repo` id is a repository.
    Raises FetchError when the identity is missing or malformed, or the primary
    request fails; an enrichment (README, comments) only downgrades the item to
    metadata-only. The input item is never mutated.
    """
    get_json = get_json or _get_json
    get_text = get_text or _get_text
    if "#" in (item.source_id or "") or "!" in (item.source_id or ""):
        return _fetch_thread(item, get_json)
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


WEB_ROOT = "https://bitbucket.org"

# Bitbucket issue states (the deprecated tracker's vocabulary) that are still
# active; everything else (`resolved`, `closed`, `duplicate`, `invalid`,
# `wontfix`) is a closed state. Normalized to github's open/closed binary so a
# cross-host `--tag closed` query spans every code host (the gitlab `opened`→
# `open` normalization, ADR 0085).
_OPEN_ISSUE_STATES = {"new", "open", "on hold"}


def _fetch_thread(item: ScrollItem, get_json: GetJson) -> ScrollItem:
    """Fetch a Bitbucket issue or pull-request discussion thread (ADR 0087).

    The source id is `workspace/repo#<n>` (an issue) or `workspace/repo!<n>` (a
    pull request) — the gitlab cross-reference markers (ADR 0085), and the marker
    says which endpoint to GET: Bitbucket keeps *separate* numbering for issues
    and PRs on separate endpoints (`/issues/<n>` vs `/pullrequests/<n>`), so —
    unlike github/gitea's one endpoint (ADR 0084/0086) — the kind is part of
    identity. One GET fetches the thread; its comments a second, taken unless the
    API reports none and degrading to body-only on failure (the github/HN
    economy, ADR 0084/0031). The body is already Markdown, so there is no HTML to
    strip (Lobsters' economy, ADR 0046). Bitbucket Cloud's issue tracker is
    deprecated (a `410` on most repos), so a `#` issue fetch degrades honestly;
    the `!` pull-request path is the common, supported case.
    """
    repo, marker, num = _split_ref(item.source_id)
    if "/" not in repo or not num.isdigit():
        raise FetchError(f"cannot determine bitbucket thread for item {item.id!r}")
    is_pr = marker == "!"
    kind = "pullrequests" if is_pr else "issues"

    thread_url = f"{API_ROOT}/repositories/{repo}/{kind}/{num}"
    try:
        thread = get_json(thread_url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"bitbucket API request failed: {exc}") from exc
    if not isinstance(thread, dict) or not thread.get("id"):
        raise FetchError(f"bitbucket thread not found: {item.source_id}")

    # The comment count gates the second GET: skip it only when the API reports
    # exactly zero (PRs carry `comment_count`); when the field is absent — the
    # issue payload's shape we cannot live-verify against the deprecated tracker
    # — fetch anyway rather than silently drop the conversation.
    count = thread.get("comment_count")
    comments: list[dict[str, Any]] = []
    if count is None or count:
        try:
            fetched = get_json(f"{thread_url}/comments?pagelen=100")
            values = fetched.get("values") if isinstance(fetched, dict) else fetched
            comments = [c for c in (values or []) if isinstance(c, dict)]
        except Exception:
            comments = []

    body = _plain(_thread_body(is_pr, thread))
    comments_text = _format_comments(comments)
    extracted = "\n\n".join(part for part in (body, comments_text) if part) or None

    raw = json.dumps({"thread": thread, "comments": comments}, ensure_ascii=False)
    hashed = extracted or raw
    base = "bitbucket-api:pullrequest" if is_pr else "bitbucket-api:issue"
    method = f"{base}+comments" if comments_text else base
    author = thread.get("author") if is_pr else thread.get("reporter")
    return replace(
        item,
        title=_thread_title(item.source_id, thread),
        author=_login(author),
        published_at=to_utc_iso(thread.get("created_on")) or item.published_at,
        canonical_url=_html_url(thread) or item.url,
        raw_text=raw,
        extracted_text=extracted,
        summary=_thread_summary(body, thread),
        tags=_thread_tags(is_pr, thread),
        # Bitbucket has no labels/topics feature, so `concepts` stay empty by
        # design — the repo adapter's posture (the issue `kind`/`priority` enums
        # are kept in `raw_text`, not promoted to the concept graph).
        concepts=(),
        links=_thread_links(repo, thread, body),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "bitbucket",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _split_ref(source_id: str) -> tuple[str, str, str]:
    """Split a thread id into `(repo, marker, num)`; marker is `#` or `!`.

    A Bitbucket workspace/repo slug is lowercase ASCII and never contains `#`/`!`,
    so the first marker present unambiguously separates the repo from the number
    (the gitlab `_split_ref`, ADR 0085).
    """
    for marker in ("#", "!"):
        if marker in (source_id or ""):
            repo, _, num = source_id.partition(marker)
            return repo, marker, num
    return source_id or "", "", ""


def _thread_body(is_pr: bool, thread: dict[str, Any]) -> str:
    """The thread's Markdown body: a PR's `description`, an issue's `content.raw`."""
    if is_pr:
        return thread.get("description") or ""
    return (thread.get("content") or {}).get("raw") or ""


def _thread_title(ref: str, thread: dict[str, Any]) -> str:
    """`workspace/repo#<n>: <title>` — the cross-reference leads (the gitlab rule).

    The source id *is* the Bitbucket cross-reference (`workspace/repo#7`,
    `workspace/repo!42`), so leading the title with it keeps a search hit or
    library listing self-identifying (the RFC number-leads-title rule,
    ADR 0066/0084). Bitbucket Cloud is a single host, so — unlike gitea — no host
    rides in the id and the ref is the source id verbatim. A titleless thread
    degrades to the bare reference.
    """
    title = (thread.get("title") or "").strip()
    return f"{ref}: {title}" if title else ref


def _thread_tags(is_pr: bool, thread: dict[str, Any]) -> tuple[str, ...]:
    """The kind and lifecycle state — the facet slot, like gitlab's thread tags.

    The state is normalized to github's vocab so a `--tag merged`/`open`/`closed`
    query spans every code host (ADR 0085). A PR is `open`/`merged` (Bitbucket's
    `OPEN`/`MERGED`), else `closed` (a `DECLINED` or `SUPERSEDED` PR is closed-
    unmerged, like github's closed PR). An issue is `open` for an active state
    (`new`/`open`/`on hold`) else `closed` (`resolved`/`wontfix`/… all read as
    closed).
    """
    state = (thread.get("state") or "").strip().lower()
    if is_pr:
        return ("pull request", {"open": "open", "merged": "merged"}.get(state, "closed"))
    return ("issue", "open" if state in _OPEN_ISSUE_STATES or not state else "closed")


def _thread_summary(body: str, thread: dict[str, Any]) -> str | None:
    """The thread's lead paragraph, else its engagement (the github/Lobsters rule).

    A thread with a body leads with it; a bare thread (a PR or issue opened with
    none) gets the honest status — the comment count Bitbucket shows on a PR
    (`comment_count`) — rather than an invented summary (ADR 0084/0031). An issue
    payload carries no such count, so a body-less issue leaves the summary empty
    (the github `count is None` posture).
    """
    if body:
        return body.split("\n\n", 1)[0].strip()
    count = thread.get("comment_count")
    if count is None:
        return None
    return f"Bitbucket discussion: {count} {'comment' if count == 1 else 'comments'}."


def _format_comments(comments: list[dict[str, Any]]) -> str:
    """The conversation as a Markdown subsection, bylined like a github thread.

    Deleted comments and **inline** diff-line review comments are skipped — the
    inline thread is the PR-review-comments slice deferred like github/gitlab's
    (ADR 0084/0085), and a deleted comment carries no body. The rest are bylined
    with the commenter's display name (ADR 0084/0046). Returns "" when nothing
    remains.
    """
    blocks = []
    for comment in comments:
        if comment.get("deleted") or "inline" in comment:
            continue
        text = _plain((comment.get("content") or {}).get("raw") or "")
        if not text:
            continue
        who = _login(comment.get("user"))
        byline = f"Comment by {who}" if who else "Comment"
        blocks.append(f"#### {byline}\n\n{text}")
    if not blocks:
        return ""
    return "### Comments\n\n" + "\n\n".join(blocks)


def _login(account: Any) -> str | None:
    """A Bitbucket account's display name, falling back to its handle (the `_author` rule)."""
    if not isinstance(account, dict):
        return None
    return (
        account.get("display_name")
        or account.get("nickname")
        or account.get("username")
        or None
    )


# A plain URL run in Markdown body text, stopping at whitespace or an angle
# bracket; trailing prose/`[label](url)` punctuation is trimmed (the github
# thread scan, ADR 0084).
_URL_RE = re.compile(r"https?://[^\s<>]+")
_URL_TRAILING = ".,;:!?\"')]}>"


def _thread_links(repo: str, thread: dict[str, Any], body: str) -> tuple[str, ...]:
    """The repo edge plus any URLs referenced in the body.

    A thread belongs to its repository, so a `bitbucket.org/<workspace>/<repo>`
    link makes the thread↔repo edge `scrolls related`/`graph` resolves to the
    saved repo item (the github issue↔repo edge, ADR 0084). URLs in the body
    become outbound edges, deduped and never self-linking the thread.
    """
    self_url = _html_url(thread) or ""
    links = [f"{WEB_ROOT}/{repo}"]
    for match in _URL_RE.finditer(body):
        url = match.group(0).rstrip(_URL_TRAILING)
        if url and url != self_url and url not in links:
            links.append(url)
    return tuple(links)


def _plain(text: str) -> str:
    """Normalize a Markdown body: CRLF to LF, collapse blank runs (the github rule)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
