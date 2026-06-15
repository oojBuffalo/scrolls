"""DEV (dev.to / Forem) fetch adapter (IDEAS.md §6, ADR 0061).

dev.to is a large developer-blogging community built on Forem, and a
common save target for Scrolls' audience. Until now a
`dev.to/<user>/<slug>` article URL fell through to the generic `web`
adapter (ADR 0001), which scrapes the rendered HTML — extracting the
article text but none of the structured signal the platform actually
publishes. The crucial loss is concepts: a `web` scroll never joins the
KB concept graph (it has no `concepts`), so a saved dev.to post became a
concept-less island. Forem exposes a stable, keyless JSON API, and a
single `GET /api/articles/<user>/<slug>` returns the whole article —
title, author, the author's Markdown body, the platform's curated tags,
and the canonical URL — in one request with no auth.

The article's `body_markdown` (already Markdown, so no HTML grammar is
needed — Lobsters' `*_plain` economy, ADR 0046) becomes the searchable
`extracted_text`, with the platform's own `description` excerpt as the
summary. The curated `tags` (`python`, `api`, `webdev`) become
`concepts` the way github repo topics do (ADR 0007) — the whole point of
a dedicated adapter, wiring the post into `scrolls related`, the concept
facets, and context bundles. When the author cross-posted from their own
blog, dev.to records the original in `canonical_url`; that external
original rides along in `links` as a cross-source edge (ADR 0044) while
the scroll's own `canonical_url` stays the dev.to permalink. The cover
image becomes a `thumbnail` media ref (the youtube/Discourse convention,
ADR 0011). The raw API object is kept in `raw_text` for rebuilds.

No platform category is assigned: dev.to is heterogeneous (tutorials,
opinions, project show-and-tells), so an item flows through the title
rules (a "How to" → tutorial, "Why I" → opinion) and otherwise stays
honestly unclassified — Hacker News's posture (ADR 0031), not a guessed
default.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http
from scrolls.sources.text import normalize_markdown

API_ROOT = "https://dev.to/api/articles"

GetJson = Callable[[str], Any]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected dev.to article; return it at stage 'fetched'.

    Raises FetchError when the `<user>/<slug>` id is missing/malformed, the
    request fails, or the response is not a usable article. The input item
    is never mutated.
    """
    get_json = get_json or _get_json
    if not item.source_id or "/" not in item.source_id:
        raise FetchError(f"cannot determine dev.to article for item {item.id!r}")

    username, slug = item.source_id.split("/", 1)
    url = f"{API_ROOT}/{username}/{slug}"
    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"dev.to API request failed: {exc}") from exc

    if not isinstance(data, dict) or not data.get("title"):
        raise FetchError(f"dev.to article not found: {item.source_id}")

    body = _plain(data.get("body_markdown") or "")
    devto_url = data.get("url") or item.url
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    hashed = body or raw
    method = "devto-api:article" if body else "devto-api:metadata"
    return replace(
        item,
        title=data.get("title") or item.title,
        author=_author(data.get("user")),
        published_at=to_utc_iso(
            data.get("published_at") or data.get("published_timestamp")
        )
        or item.published_at,
        canonical_url=devto_url,
        raw_text=raw,
        extracted_text=body or None,
        summary=_summary(body, data),
        concepts=_concepts(data),
        links=_links(devto_url, data.get("canonical_url")),
        media=_media(data),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "devto",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _author(user: Any) -> str | None:
    """The article's author: the person's display name, else their handle.

    `user` is always the author (a person), even for an organization post
    whose URL carries the org handle — the org is a separate `organization`
    field, not the byline. A deleted/absent user becomes None.
    """
    if not isinstance(user, dict):
        return None
    return user.get("name") or user.get("username") or None


def _concepts(data: dict[str, Any]) -> tuple:
    """The curated tags as concepts, like github repo topics (ADR 0007).

    The API gives both a `tags` list and a comma-joined `tag_list`; the
    list is preferred, falling back to splitting the string for an older
    payload shape. Tags are topical (`python`, `webdev`), so they are
    concepts, not the license/classifier `tags` facet the registries use —
    dev.to has no such facet, so `tags` stays empty (github's posture).
    """
    tags = data.get("tags")
    if isinstance(tags, list):
        cleaned = [str(tag).strip() for tag in tags if str(tag).strip()]
    else:
        cleaned = [part.strip() for part in (data.get("tag_list") or "").split(",")]
        cleaned = [part for part in cleaned if part]
    return tuple(dict.fromkeys(cleaned))


def _links(devto_url: str, canonical_url: Any) -> tuple:
    """The cross-post original as a cross-source edge, else ().

    A dev.to article often cross-posts from the author's own blog; dev.to
    records that origin in `canonical_url`. The scroll's own canonical is
    the dev.to permalink, so the *external* original (a different artifact)
    rides along in `links` — the cross-source edge `scrolls related`/`graph`
    resolves (ADR 0044) — only when it actually points elsewhere.
    """
    canonical = canonical_url.strip() if isinstance(canonical_url, str) else ""
    if canonical and canonical != devto_url:
        return (canonical,)
    return ()


def _media(data: dict[str, Any]) -> tuple:
    """The cover (else social) image as a single `thumbnail` media ref, else ().

    The youtube/Discourse thumbnail convention (ADR 0011): a preview image
    kept as a media ref the capture step can localize. dev.to serves it as
    an absolute CDN URL, so no host resolution is needed.
    """
    cover = data.get("cover_image") or data.get("social_image")
    if not isinstance(cover, str):
        return ()
    cover = cover.strip()
    if not cover or urlparse(cover).scheme not in ("http", "https"):
        return ()
    return ({"type": "thumbnail", "url": cover},)


def _summary(body: str, data: dict[str, Any]) -> str | None:
    """The platform's excerpt, else the body lead, else the engagement status.

    dev.to's `description` is its own chosen excerpt (author-set or
    auto-generated from the lead), so it is the honest summary. With no
    excerpt the body's lead paragraph leads the way Wikipedia/HN/Lobsters
    do; with neither, the post's reactions/comments are stated — Hacker
    News's link-post pattern (ADR 0031). A bare stub gets no invented
    summary (the honestly-empty posture, ADR 0004).
    """
    description = (data.get("description") or "").strip()
    if description:
        return description
    if body:
        return body.split("\n\n", 1)[0].strip()
    reactions = data.get("public_reactions_count")
    comments = data.get("comments_count")
    if reactions is None and comments is None:
        return None
    likes = 0 if reactions is None else reactions
    replies = 0 if comments is None else comments
    return (
        f"DEV post: {likes} {_plural(likes, 'reaction')}, "
        f"{replies} {_plural(replies, 'comment')}."
    )


def _plural(count: int, noun: str) -> str:
    return noun if count == 1 else noun + "s"


def _plain(text: str) -> str:
    """Tidy the author's Markdown: CRLF to LF, collapse blank runs.

    `body_markdown` is already Markdown (no HTML to strip, unlike the web
    adapter), so only line-ending and blank-line normalization is needed —
    Lobsters' `*_plain` economy (ADR 0046).
    """
    return normalize_markdown(text)


_get_json = http.get_json
