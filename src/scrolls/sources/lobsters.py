"""Lobsters fetch adapter (IDEAS.md §6, ADR 0046).

Lobste.rs is a small computing-focused link aggregator — the same
developer-discussion niche as Hacker News (ADR 0031), and a common save
target for Scrolls' audience (IDEAS.md §11). Until now a
`lobste.rs/s/<id>` URL fell through to the generic `web` adapter
(ADR 0001), which scrapes the HTML page and mangles the threaded
discussion. Lobsters publishes a stable, keyless JSON view of every page
(append `.json`), and a story's `.json` returns the submission, its tags,
*and* the entire comment thread in one request — so unlike Hacker News
(whose comments are a separate fetch per node, deferred — ADR 0031) or
Stack Exchange (whose answers cost a second GET — ADR 0033), the whole
discussion arrives for the price of one keyless request.

A link submission (`url` set) records the linked article in `links` so
`scrolls related`/`graph` can resolve it, the way a Hacker News link
story does. A text submission (`url` empty) contributes its
`description_plain` body. Either way the comment thread — already
rendered to plain text by the API as `comment_plain`, so no HTML grammar
is needed (contrast HN and Stack Exchange) — becomes the searchable
`extracted_text`, each comment bylined with its author and score the way
Stack Exchange bylines an answer (ADR 0033). The story's curated `tags`
(`css`, `security`, `ask`) become `concepts` like github repo topics
(ADR 0007). The raw story object — comments and their `depth` included —
is kept in `raw_text` for rebuilds.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import discussion
from scrolls.sources import http
from scrolls.sources.text import normalize_markdown

API_ROOT = "https://lobste.rs"

GetJson = Callable[[str], Any]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected Lobsters story; return it at stage 'fetched'.

    Raises FetchError when the short id is missing, the request fails, or
    the story does not exist. The input item is never mutated.
    """
    get_json = get_json or _get_json
    if not item.source_id:
        raise FetchError(f"cannot determine lobsters story for item {item.id!r}")

    url = f"{API_ROOT}/s/{item.source_id}.json"
    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"lobsters API request failed: {exc}") from exc

    if not isinstance(data, dict) or not data.get("short_id"):
        raise FetchError(f"lobsters story not found: {item.source_id}")

    body = _plain(data.get("description_plain") or "")
    comments_text = _format_comments(data.get("comments") or [])
    extracted = "\n\n".join(part for part in (body, comments_text) if part) or None
    article_url = data.get("url") or None

    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    hashed = extracted or raw
    method = "lobsters-api:story+comments" if comments_text else "lobsters-api:story"
    return replace(
        item,
        title=data.get("title") or item.title,
        author=_username(data.get("submitter_user")),
        published_at=to_utc_iso(data.get("created_at")) or item.published_at,
        canonical_url=data.get("short_id_url") or f"{API_ROOT}/s/{item.source_id}",
        raw_text=raw,
        extracted_text=extracted,
        summary=_summary(body, data),
        concepts=tuple(data.get("tags") or ()),
        links=(article_url,) if article_url else (),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "lobsters",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _summary(body: str, data: dict[str, Any]) -> str | None:
    """A submission's lead paragraph, else the discussion's status.

    A link submission has no body of its own (the article is elsewhere),
    so its honest summary is what Lobsters itself shows: score and comment
    count — Hacker News's pattern (ADR 0031). A submitter note on a link
    submission counts as a body and leads, like any text. A bare stub with
    neither gets no invented summary (the honestly-empty posture, ADRs
    0004, 0031).
    """
    if body:
        return body.split("\n\n", 1)[0].strip()
    score, comments = data.get("score"), data.get("comment_count")
    if score is None and comments is None:
        return None
    points = 0 if score is None else score
    replies = 0 if comments is None else comments
    return (
        f"Lobsters discussion: {points} {_plural(points, 'point')}, "
        f"{replies} {_plural(replies, 'comment')}."
    )


def _format_comments(comments: list[dict[str, Any]]) -> str:
    """The thread as a Markdown subsection, in the API's thread order.

    Deleted and moderated comments carry no usable text and are skipped;
    every other comment is bylined with its author and score the way Stack
    Exchange bylines an answer (ADR 0033) and assembled by the shared thread
    renderer (ADR 0093). Returns "" when nothing remains. Threading `depth` is
    not rendered into the plain text but survives in `raw_text` for a future
    enrichment, the way Hacker News keeps `kids`.
    """
    rendered = []
    for comment in comments:
        if comment.get("is_deleted") or comment.get("is_moderated"):
            continue
        text = _plain(comment.get("comment_plain") or "")
        if not text:
            continue
        who = _username(comment.get("commenting_user"))
        byline = f"Comment by {who}" if who else "Comment"
        score = comment.get("score")
        if score is not None:
            byline += f" (score {score})"
        rendered.append(discussion.Comment(byline, text))
    return discussion.format_thread(rendered, heading="Comments")


def _username(value: Any) -> str | None:
    """A username from the API's bare-string form (today) or legacy object.

    `submitter_user`/`commenting_user` are plain usernames in the current
    API; older payloads nested them under a `{username: ...}` object, so
    both shapes are read. A deleted user (empty) becomes None.
    """
    if isinstance(value, dict):
        return value.get("username") or None
    return value or None


def _plain(text: str) -> str:
    """Tidy the API's already-plain text: CRLF to LF, collapse blank runs.

    Lobsters ships `description_plain`/`comment_plain` already rendered
    from Markdown, so there is no HTML to strip (contrast HN and Stack
    Exchange) — only line-ending and blank-line normalization.
    """
    return normalize_markdown(text)


def _plural(count: int, noun: str) -> str:
    return noun if count == 1 else noun + "s"


_get_json = http.get_json
