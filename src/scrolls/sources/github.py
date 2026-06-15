"""GitHub fetch adapter (IDEAS.md §6, ADR 0007, ADR 0084).

Repository metadata comes from the keyless GitHub REST API; the
searchable content is the README, fetched as base64 JSON and decoded
locally so the shared transport needs no media-type negotiation. The
README is optional enrichment: repos without one still become
metadata-only scrolls, and `provenance.extraction_method` records which
path produced the item. Author-curated repo topics become `concepts` —
the first adapter to populate them, feeding the KB's concept pages.
Setting `GITHUB_TOKEN` (or `GH_TOKEN`) lifts the unauthenticated rate
limit; both raw payloads are kept in `raw_text` for rebuilds.

Issues and pull requests are a second content kind on the same source
(ADR 0084): a `/issues/<n>` or `/pull/<n>` URL detects as `owner/repo#<n>`
— a discussion thread distinct from the repo — and `fetch_item` dispatches
on the `#` in the source id (the Hugging Face one-source-many-kinds shape,
ADR 0041), keeping the repo path byte-unchanged. The issues endpoint serves
both issues and PRs, so one path covers them; the kind and state (open /
closed / merged) go to `tags`, the curated labels to `concepts`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import discussion
from scrolls.sources import http
from scrolls.sources import urls

API_ROOT = "https://api.github.com"
WEB_ROOT = "https://github.com"
_API_VERSION = "2022-11-28"

GetJson = Callable[[str], Any]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected GitHub repo or issue/PR thread; return it at stage 'fetched'.

    Dispatches on the source id: an `owner/repo#<n>` id is a discussion thread
    (`_fetch_issue`, ADR 0084), a plain `owner/repo` id is a repository. Raises
    FetchError when the identity is missing or the primary request fails; an
    enrichment (README, comments) only downgrades to metadata-only. The input
    item is never mutated.
    """
    get_json = get_json or _get_json
    if not item.source_id or "/" not in item.source_id:
        raise FetchError(f"cannot determine github repository for item {item.id!r}")
    if "#" in item.source_id:
        return _fetch_issue(item, get_json)

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
        published_at=to_utc_iso(repo.get("created_at")) or item.published_at,
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


def _fetch_issue(item: ScrollItem, get_json: GetJson) -> ScrollItem:
    """Fetch a GitHub issue or pull-request thread (ADR 0084).

    The source id is `owner/repo#<number>`. The issues endpoint serves both
    issues and PRs (a PR carries a `pull_request` object), so one GET fetches
    the thread; the conversation comments cost a second GET, taken only when
    the thread has any and degrading to body-only on failure (the HN/Discourse
    economy, ADR 0031/0054). The body is already Markdown, so there is no HTML
    to strip (Lobsters' economy, ADR 0046).
    """
    repo, _, number = item.source_id.partition("#")
    if "/" not in repo or not number.isdigit():
        raise FetchError(f"cannot determine github issue for item {item.id!r}")

    issue_url = f"{API_ROOT}/repos/{repo}/issues/{number}"
    try:
        issue = get_json(issue_url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"github API request failed: {exc}") from exc
    if not isinstance(issue, dict) or not issue.get("number"):
        raise FetchError(f"github issue not found: {item.source_id}")

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
    method = "github-api:issue+comments" if comments_text else "github-api:issue"
    return replace(
        item,
        title=_issue_title(repo, number, issue),
        author=(issue.get("user") or {}).get("login") or None,
        published_at=to_utc_iso(issue.get("created_at")) or item.published_at,
        canonical_url=issue.get("html_url") or item.url,
        raw_text=raw,
        extracted_text=extracted,
        summary=_issue_summary(body, issue),
        tags=_issue_tags(issue),
        concepts=_labels(issue.get("labels")),
        links=_issue_links(repo, issue, body),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "github",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _issue_title(repo: str, number: str, issue: dict[str, Any]) -> str:
    """`owner/repo#<n>: <title>` — the number leads, as GitHub references it.

    A GitHub issue title is often terse ("Fix the bug"), and `owner/repo#<n>`
    is the work's canonical reference notation, so leading with it keeps a
    search hit or library listing self-identifying — the RFC number-leads-title
    rule (ADR 0066). A titleless thread degrades to the bare reference.
    """
    title = (issue.get("title") or "").strip()
    ref = f"{repo}#{number}"
    return f"{ref}: {title}" if title else ref


def _issue_tags(issue: dict[str, Any]) -> tuple[str, ...]:
    """The kind and lifecycle state — the facet slot, like Crossref's type+venue.

    A PR carries a `pull_request` object whose `merged_at` distinguishes a
    merged PR from a closed-unmerged one without the extra `/pulls/<n>` GET the
    PR-specific fields would need. An issue is just open or closed.
    """
    pull = issue.get("pull_request")
    if isinstance(pull, dict):
        state = "merged" if pull.get("merged_at") else (issue.get("state") or "closed")
        return ("pull request", state)
    return ("issue", issue.get("state") or "open")


def _labels(labels: Any) -> tuple[str, ...]:
    """Issue/PR labels → `concepts`, the curated topical facet (the topics rule).

    The REST API returns label objects (`{name, color, …}`); older or terse
    payloads can carry bare strings, so both shapes are read. Blank names are
    dropped and duplicates collapse while preserving order.
    """
    names: list[str] = []
    for label in labels or ():
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str) and name.strip() and name not in names:
            names.append(name)
    return tuple(names)


def _issue_summary(body: str, issue: dict[str, Any]) -> str | None:
    """The thread's lead paragraph, else its engagement (the Lobsters rule).

    A thread with a body leads with it; a bare thread (a PR or issue opened with
    no description) gets the honest status GitHub itself shows — the comment
    count — rather than an invented summary (ADR 0031/0046). Neither present
    leaves it empty.
    """
    if body:
        return body.split("\n\n", 1)[0].strip()
    count = issue.get("comments")
    if count is None:
        return None
    return f"GitHub discussion: {count} {'comment' if count == 1 else 'comments'}."


def _format_comments(comments: list[dict[str, Any]]) -> str:
    """The conversation as a Markdown subsection, bylined like a Lobsters thread.

    Comments without an author or body carry nothing usable and are skipped;
    the rest are bylined with the commenter the way Lobsters/Stack Exchange
    byline a reply (ADR 0046/0033). The `### Comments` subsection is assembled
    by the shared thread renderer (ADR 0093). Returns "" when nothing remains.
    """
    rendered = []
    for comment in comments:
        text = _plain(comment.get("body") or "")
        if not text:
            continue
        who = (comment.get("user") or {}).get("login")
        byline = f"Comment by {who}" if who else "Comment"
        rendered.append(discussion.Comment(byline, text))
    return discussion.format_thread(rendered, heading="Comments")


def _issue_links(repo: str, issue: dict[str, Any], body: str) -> tuple[str, ...]:
    """The repo edge plus any URLs referenced in the body.

    A thread belongs to its repository, so a `github.com/<owner>/<repo>` link
    makes the issue↔repo edge `scrolls related`/`graph` resolves to the saved
    repo item. URLs in the body (cross-references to other issues, PRs, docs)
    become outbound edges the way a social post's body links do (ADR 0051),
    deduped and never self-linking the thread — the shared body-link grammar
    (ADR 0094).
    """
    return urls.body_edge_links(f"{WEB_ROOT}/{repo}", issue.get("html_url") or "", body)


def _plain(text: str) -> str:
    """Normalize a Markdown body: CRLF to LF, collapse blank runs (Lobsters' rule)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
