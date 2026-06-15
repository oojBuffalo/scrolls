"""GitLab fetch adapter (IDEAS.md §6, ADR 0055).

The sibling of the GitHub adapter (ADR 0007): the second major code host,
and the most widely self-hosted one. Repository metadata comes from the
keyless GitLab REST API (`gitlab.com/api/v4/projects/<url-encoded path>`);
the searchable content is the README, fetched as raw text from the project's
`readme_url` rewritten to its `/-/raw/` route. The README is optional
enrichment: projects without one still become metadata-only scrolls, and
`provenance.extraction_method` records which path produced the item.
Author-curated repo `topics` become `concepts` like GitHub repo topics
(ADR 0007), and the SPDX license key becomes a `tag` like the package
registries (ADR 0036, ADR 0039). Setting `GITLAB_TOKEN` lifts the
unauthenticated rate limit (and reaches private projects the caller can
read); both raw payloads are kept in `raw_text` for rebuilds.

Identity differs from GitHub in one way the URL forces: GitLab supports
*nested* groups, so a project path is `group[/subgroup…]/project`, not a flat
`owner/repo`. The whole path before any `/-/` sub-resource separator is the
project, and the API takes it URL-encoded (`%2F` for the slashes), so the
adapter encodes `source_id` whole rather than splitting on `/`.

Issues and merge requests are a second content kind on the same source
(ADR 0085): a `/-/issues/<n>` or `/-/merge_requests/<n>` URL detects as a
discussion thread in GitLab's own cross-reference notation — `group/project#<n>`
for an issue, `group/project!<n>` for a merge request — and `fetch_item`
dispatches on the marker in the source id (the github one-source-many-kinds
shape, ADR 0084), keeping the project path byte-unchanged. GitLab keeps
*separate* iid sequences for issues and MRs, so the `#`/`!` marker is load-
bearing: it both disambiguates identity and picks which endpoint to GET
(`/issues/<iid>` vs `/merge_requests/<iid>`), unlike github's single
`/issues/<n>` endpoint that serves both. The kind and state go to `tags`, the
labels to `concepts`, and GitLab's automated *system* notes are dropped so only
human comments are content.
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

API_ROOT = "https://gitlab.com/api/v4"
WEB_ROOT = "https://gitlab.com"

GetJson = Callable[[str], dict[str, Any]]
GetText = Callable[[str], str]


def fetch_item(
    item: ScrollItem,
    *,
    get_json: GetJson | None = None,
    get_text: GetText | None = None,
) -> ScrollItem:
    """Fetch a detected GitLab project, issue, or MR thread; return it at stage 'fetched'.

    Dispatches on the source id: a `group/project#<iid>` (issue) or
    `group/project!<iid>` (merge request) id is a discussion thread
    (`_fetch_thread`, ADR 0085), a plain `group/project` id is a project. Raises
    FetchError when the project identity is missing or the project request
    fails; a missing README (or, for a thread, its notes) only downgrades the
    item to metadata-only. The input item is never mutated.
    """
    get_json = get_json or _get_json
    get_text = get_text or _get_text
    if not item.source_id or "/" not in item.source_id:
        raise FetchError(f"cannot determine gitlab project for item {item.id!r}")
    if "#" in item.source_id or "!" in item.source_id:
        return _fetch_thread(item, get_json)

    # The project path is URL-encoded whole (slashes → %2F) because nested
    # groups make it a multi-segment path, not a flat owner/repo.
    encoded = quote(item.source_id, safe="")
    project_url = f"{API_ROOT}/projects/{encoded}?license=true"
    try:
        project = get_json(project_url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"gitlab API request failed: {exc}") from exc

    # The README is optional: a project without one carries a null
    # `readme_url`, an odd payload fetches to nothing, and neither should
    # fail an otherwise-identified project.
    readme = _fetch_readme(project, get_text)

    hashed = readme or json.dumps(project, sort_keys=True, ensure_ascii=False)
    return replace(
        item,
        title=project.get("path_with_namespace") or item.title,
        author=_author(project),
        published_at=to_utc_iso(project.get("created_at")) or item.published_at,
        canonical_url=project.get("web_url"),
        raw_text=json.dumps({"project": project, "readme": readme}, ensure_ascii=False),
        extracted_text=readme,
        summary=project.get("description") or None,
        concepts=_topics(project),
        tags=_license_tags(project),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "gitlab",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "gitlab-api:project+readme" if readme else "gitlab-api:project",
        },
        stage="fetched",
    )


def _fetch_readme(project: dict[str, Any], get_text: GetText) -> str | None:
    """The project's README as raw text, or None when absent/blank/unfetchable.

    GitLab's project payload carries a `readme_url` pointing at the README's
    web *blob* (`…/-/blob/<ref>/<file>`); its raw twin (`…/-/raw/<ref>/<file>`)
    serves the file body with no HTML chrome. Rewriting the one route segment
    is exact — `/-/` is GitLab's reserved sub-resource separator, so it never
    occurs in a group or project slug — and avoids a second API round-trip for
    the repository file tree. Any failure (a 404, a non-blob URL) degrades to
    metadata-only.
    """
    blob_url = project.get("readme_url")
    if not isinstance(blob_url, str) or "/-/blob/" not in blob_url:
        return None
    raw_url = blob_url.replace("/-/blob/", "/-/raw/", 1)
    try:
        text = get_text(raw_url)
    except Exception:
        return None
    return text if text.strip() else None


def _author(project: dict[str, Any]) -> str | None:
    """The owning namespace's full path (its name under nested groups), else None."""
    namespace = project.get("namespace") or {}
    return namespace.get("full_path") or namespace.get("path") or namespace.get("name") or None


def _topics(project: dict[str, Any]) -> tuple[str, ...]:
    """Author-curated repo topics as `concepts` (github-topics pattern, ADR 0007).

    Modern GitLab returns `topics`; the deprecated `tag_list` is the fallback
    for older instances and is identical in content.
    """
    topics = project.get("topics")
    if not topics:
        topics = project.get("tag_list")
    return tuple(t for t in (topics or ()) if t)


def _license_tags(project: dict[str, Any]) -> tuple[str, ...]:
    """The SPDX-style license key as a single `tag`, or empty.

    Requested with `?license=true`; the key (`mit`, `apache-2.0`) is the
    registry adapters' SPDX-license-as-tag facet (ADR 0036, ADR 0039).
    """
    key = (project.get("license") or {}).get("key")
    return (key,) if key else ()


def _fetch_thread(item: ScrollItem, get_json: GetJson) -> ScrollItem:
    """Fetch a GitLab issue or merge-request discussion thread (ADR 0085).

    The source id is `group/project#<iid>` (an issue) or `group/project!<iid>`
    (a merge request) — GitLab's own cross-reference notation, and the marker
    that says which endpoint to GET: GitLab keeps *separate* iid sequences for
    issues and MRs, so unlike github's one `/issues/<n>` endpoint (ADR 0084) the
    kind is part of identity. The project path is URL-encoded whole like a repo
    fetch (nested groups). The thread costs one GET; its notes a second, taken
    only when it has any (`user_notes_count`) and degrading to body-only on
    failure (the github/HN economy, ADR 0084/0031). gitlab.com serves the
    issue/MR *metadata* keyless but gates the `/notes` endpoint behind auth — an
    anonymous caller gets 401 on notes (verified live) — so the common keyless
    case degrades to body-only and `GITLAB_TOKEN` is what reaches the
    conversation. GitLab *system* notes — its automated activity events
    ("changed milestone", "assigned") — are dropped; only human comments are
    content (the Discourse mod-action skip, ADR 0054). The description is already
    Markdown, so there is no HTML to strip.
    """
    project, marker, iid = _split_ref(item.source_id)
    if "/" not in project or not iid.isdigit():
        raise FetchError(f"cannot determine gitlab thread for item {item.id!r}")
    kind = "merge_requests" if marker == "!" else "issues"

    encoded = quote(project, safe="")
    thread_url = f"{API_ROOT}/projects/{encoded}/{kind}/{iid}"
    try:
        thread = get_json(thread_url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"gitlab API request failed: {exc}") from exc
    if not isinstance(thread, dict) or not thread.get("iid"):
        raise FetchError(f"gitlab thread not found: {item.source_id}")

    notes: list[dict[str, Any]] = []
    if thread.get("user_notes_count"):
        try:
            fetched = get_json(
                f"{thread_url}/notes?per_page=100&sort=asc&order_by=created_at"
            )
            notes = [n for n in fetched if isinstance(n, dict)]
        except Exception:
            notes = []

    body = _plain(thread.get("description") or "")
    notes_text = _format_notes(notes)
    extracted = "\n\n".join(part for part in (body, notes_text) if part) or None

    raw = json.dumps({"thread": thread, "notes": notes}, ensure_ascii=False)
    hashed = extracted or raw
    base = "gitlab-api:merge_request" if marker == "!" else "gitlab-api:issue"
    method = f"{base}+notes" if notes_text else base
    return replace(
        item,
        title=_thread_title(item.source_id, thread),
        author=(thread.get("author") or {}).get("username") or None,
        published_at=to_utc_iso(thread.get("created_at")) or item.published_at,
        canonical_url=thread.get("web_url") or item.url,
        raw_text=raw,
        extracted_text=extracted,
        summary=_thread_summary(body, thread),
        tags=_thread_tags(marker, thread),
        concepts=_labels(thread.get("labels")),
        links=_thread_links(project, thread, body),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "gitlab",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _split_ref(source_id: str) -> tuple[str, str, str]:
    """Split a thread id into `(project, marker, iid)`; marker is `#` or `!`.

    A project slug is ASCII `[a-z0-9._-]` and never contains `#`/`!`, so the
    first marker present unambiguously separates the project from the iid.
    """
    for marker in ("#", "!"):
        if marker in (source_id or ""):
            project, _, iid = source_id.partition(marker)
            return project, marker, iid
    return source_id or "", "", ""


def _thread_title(ref: str, thread: dict[str, Any]) -> str:
    """`group/project#<n>: <title>` — the cross-reference leads (the github rule).

    The source id *is* the GitLab cross-reference (`group/project#7`,
    `group/project!42`), so leading the title with it keeps a search hit or
    library listing self-identifying — the RFC number-leads-title rule
    (ADR 0066/0084). A titleless thread degrades to the bare reference.
    """
    title = (thread.get("title") or "").strip()
    return f"{ref}: {title}" if title else ref


def _thread_tags(marker: str, thread: dict[str, Any]) -> tuple[str, ...]:
    """The kind and lifecycle state — the facet slot, like github's thread tags.

    GitLab reports an MR's merged state directly (`state == "merged"`), so no
    extra GET is needed to tell a merged MR from a closed one (github derives it
    from `merged_at`). The state vocabulary is normalized to github's: GitLab's
    `opened` becomes `open`, so a `--tag open` query spans both hosts.
    """
    kind = "merge request" if marker == "!" else "issue"
    state = (thread.get("state") or "").strip().lower()
    state = "open" if state == "opened" else state
    return (kind, state or "open")


def _labels(labels: Any) -> tuple[str, ...]:
    """Issue/MR labels → `concepts`, the curated topical facet (the github rule).

    GitLab returns labels as bare strings by default (`["bug", "frontend"]`);
    `?with_labels_details=true` would return objects, so both shapes are read
    like github's `_labels`. Blank names are dropped and duplicates collapse
    while preserving order.
    """
    names: list[str] = []
    for label in labels or ():
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str) and name.strip() and name not in names:
            names.append(name)
    return tuple(names)


def _thread_summary(body: str, thread: dict[str, Any]) -> str | None:
    """The thread's lead paragraph, else its engagement (the github/Lobsters rule).

    A thread with a description leads with it; a bare thread (an issue or MR
    opened with none) gets the honest status GitLab shows — the human-comment
    count (`user_notes_count`, which already excludes system notes) — rather
    than an invented summary (ADR 0084/0031). Neither present leaves it empty.
    """
    if body:
        return body.split("\n\n", 1)[0].strip()
    count = thread.get("user_notes_count")
    if count is None:
        return None
    return f"GitLab discussion: {count} {'comment' if count == 1 else 'comments'}."


def _format_notes(notes: list[dict[str, Any]]) -> str:
    """The conversation as a Markdown subsection, bylined like a github thread.

    GitLab *system* notes (automated activity: label changes, assignments,
    milestone edits) carry `system: true` and are not discussion, so they are
    dropped — the Discourse mod-action skip (ADR 0054). Notes without an author
    or body carry nothing usable and are skipped too; the rest are bylined with
    the commenter (ADR 0084/0046) and assembled by the shared thread renderer
    (ADR 0093). Returns "" when nothing remains.
    """
    rendered = []
    for note in notes:
        if note.get("system"):
            continue
        text = _plain(note.get("body") or "")
        if not text:
            continue
        who = (note.get("author") or {}).get("username")
        byline = f"Comment by {who}" if who else "Comment"
        rendered.append(discussion.Comment(byline, text))
    return discussion.format_thread(rendered, heading="Comments")


# A plain URL run in Markdown body text, stopping at whitespace or an angle
# bracket; trailing prose/`[label](url)` punctuation is trimmed (the github
# thread scan, ADR 0084).
_URL_RE = re.compile(r"https?://[^\s<>]+")
_URL_TRAILING = ".,;:!?\"')]}>"


def _thread_links(project: str, thread: dict[str, Any], body: str) -> tuple[str, ...]:
    """The project edge plus any URLs referenced in the description.

    A thread belongs to its project, so a `gitlab.com/<project>` link makes the
    thread↔project edge `scrolls related`/`graph` resolves to the saved project
    item (the github issue↔repo edge, ADR 0084). URLs in the description (cross-
    references to other issues, MRs, docs) become outbound edges, deduped and
    never self-linking the thread.
    """
    self_url = thread.get("web_url") or ""
    links = [f"{WEB_ROOT}/{project}"]
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


def _api_headers() -> dict[str, str]:
    """Keyless by default; `GITLAB_TOKEN` lifts the rate limit (GitLab's header)."""
    token = os.environ.get("GITLAB_TOKEN")
    return {"PRIVATE-TOKEN": token} if token else {}


def _get_json(url: str) -> dict[str, Any]:
    return http.get_json(url, headers=_api_headers())


def _get_text(url: str) -> str:
    return http.get_text(url, headers=_api_headers())
