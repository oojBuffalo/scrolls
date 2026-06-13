"""Lemmy fetch adapter (IDEAS.md §6, ADR 0052).

The fourth open Fediverse source, after Bluesky (ADR 0048), Mastodon
(ADR 0049), and Misskey (ADR 0051), and the first federated *link aggregator* —
the Reddit-shaped niche Hacker News (ADR 0031) and Lobsters (ADR 0046) fill on
the centralized web. Like Misskey, Lemmy is Fediverse software that does *not*
speak the Mastodon API: a saved `https://<instance>/post/<id>` post is fetched
from that instance's own keyless `/api/v3/post`, not `/api/v1/statuses/<id>`,
so — exactly as ADR 0051 reasoned for Misskey — Lemmy is its own source and
adapter rather than another mastodon URL shape. (GoToSocial and Pleroma rode
the mastodon adapter only because they *are* Mastodon-API-compatible, ADR 0050.)

Three facts shape the design, two shared with the social adapters and one its
own as a link aggregator:

1. **There is no shared host** (the Fediverse problem, ADR 0049/0051). Detection
   (`detect.py`) recognizes a Lemmy post by its `/post/<digits>` URL *shape* on
   whatever instance the saved URL names, and the instance host rides in the
   item id (`lemmy:<host>/<id>`) because a post id is unique only within its
   instance. The adapter talks to that same host's `/api/v3`. Lemmy's API is
   plain GET with query params, so the shared `http.get_json` transport serves
   it — no `post_json` (Misskey's JSON-body POST, ADR 0051) is needed.

2. **The thread is a second request** (the Bluesky/Mastodon/Misskey/Stack
   Exchange shape, ADR 0048/0049/0051/0033). The post (`/post`) and its comments
   (`/comment/list`) are two GETs; a post with zero comments skips the second,
   and a failed comment fetch still produces a post-only scroll. Lemmy returns
   comments as a flat list whose `path` (`"0.<id>"`, `"0.<parent>.<id>"`)
   encodes the thread tree, so the comments are sorted into pre-order before
   rendering — a parent immediately precedes its replies — and each is bylined
   with its author and score the way Lobsters/Stack Exchange byline a comment.

3. **A Lemmy post is a link aggregator entry, so it has a real title** (unlike a
   Bluesky/Mastodon/Misskey social post, whose title is synthesized). A link
   post records its external article in `links` (the Hacker News/Lobsters
   pattern), a text post contributes its Markdown `body`, and either way the
   comment thread becomes the searchable `extracted_text`. Outbound URLs in the
   body are scanned as links (Misskey's URL scan), and the post's `cross_posts`
   — the same submission in other communities — become post↔post links by their
   `ap_id` (Misskey's quote-renote edge). An image post's `url` is `photo`
   media; an article post's pict-rs `thumbnail_url` is a preview `thumbnail`.
   The post's `community` (its topical home, like a subreddit) becomes a
   `concept` the way github repo topics do (ADR 0007). Like Hacker News,
   Lobsters, and the social adapters, a heterogeneous aggregator entry gets *no*
   category default. The whole `{post, comments}` is kept in `raw_text`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

# Comments to request: bounded so a huge thread stays a tractable scroll, the
# deeper tail surviving in raw_text for a future render (Bluesky's depth cap,
# ADR 0048; Misskey's reply limit, ADR 0051).
_MAX_DEPTH = 8
_COMMENT_LIMIT = 50

# Image extensions a pict-rs/url post points at when it is itself an image.
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif")

GetJson = Callable[[str], Any]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected Lemmy post and its comments; return it at stage 'fetched'.

    Raises FetchError when the source_id is missing/malformed, the request
    fails, or the post does not exist. The input item is never mutated.
    """
    get_json = get_json or _get_json
    host, post_id = _split_source_id(item)
    api = f"https://{host}/api/v3"

    try:
        data = get_json(f"{api}/post?id={post_id}")
    except (OSError, ValueError) as exc:
        raise FetchError(f"lemmy API request failed: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("post_view"), dict):
        raise FetchError(f"lemmy post not found: {host}/{post_id}")
    post_view = data["post_view"]
    post = post_view.get("post")
    if not isinstance(post, dict) or "id" not in post:
        raise FetchError(f"lemmy post not found: {host}/{post_id}")

    creator = post_view.get("creator") or {}
    community = post_view.get("community") or {}
    counts = post_view.get("counts") or {}

    body_text = _text(post.get("body"))
    media, article = _media_and_article(post)
    links = _dedupe(
        ([article] if article else [])
        + _content_links(post.get("body"))
        + _cross_post_links(data)
    )

    comments = _fetch_comments(api, post_id, counts.get("comments") or 0, get_json)
    comments_text = _format_comments(comments)
    extracted = "\n\n".join(part for part in (body_text, comments_text) if part) or None

    raw = json.dumps({"post": data, "comments": comments}, sort_keys=True, ensure_ascii=False)
    hashed = extracted or raw
    method = "lemmy-api:post+comments" if comments_text else "lemmy-api:post"
    return replace(
        item,
        title=_clean(post.get("name")) or item.title,
        author=_name(creator),
        published_at=to_utc_iso(post.get("published")) or item.published_at,
        canonical_url=_clean(post.get("ap_id")) or f"https://{host}/post/{post_id}",
        raw_text=raw,
        extracted_text=extracted,
        summary=_summary(body_text, counts),
        concepts=_community_concepts(community),
        links=links,
        media=media,
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "lemmy",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _split_source_id(item: ScrollItem) -> tuple[str, str]:
    """The `<host>/<post_id>` source id into its two halves.

    The host is a single dotted hostname and the post id an all-digits run with
    no slash of its own, so one rsplit on the last slash is exact (Misskey's
    `_split_source_id`, ADR 0051).
    """
    source_id = item.source_id or ""
    if "/" not in source_id:
        raise FetchError(f"cannot determine lemmy post for item {item.id!r}")
    host, post_id = source_id.rsplit("/", 1)
    if not host or not post_id:
        raise FetchError(f"cannot determine lemmy post for item {item.id!r}")
    return host, post_id


def _fetch_comments(
    api: str, post_id: str, count: int, get_json: GetJson
) -> list[Any] | None:
    """The post's comments, or None when it has none or the fetch fails.

    A post with zero comments skips the second GET entirely (Misskey's economy,
    ADR 0051); a failed comment fetch degrades to a post-only scroll rather than
    failing the whole item (Stack Exchange's answers-are-optional rule, ADR 0033).
    """
    if count <= 0:
        return None
    url = (
        f"{api}/comment/list?post_id={post_id}"
        f"&max_depth={_MAX_DEPTH}&limit={_COMMENT_LIMIT}&sort=Top"
    )
    try:
        data = get_json(url)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    comments = data.get("comments")
    return comments if isinstance(comments, list) else None


def _format_comments(comments: list[Any] | None) -> str:
    """The comment list as a Markdown subsection, sorted into thread pre-order.

    Lemmy returns a flat list whose `path` (`"0.<id>"`, `"0.<parent>.<id>"`)
    encodes the tree, so sorting by the path's integer segments puts a parent
    immediately before its replies. Deleted and moderator-removed comments carry
    no usable text and are skipped (Lobsters' rule, ADR 0046); every other
    comment is bylined with its author and score the way Stack Exchange bylines
    an answer (ADR 0033). The threading `path` is not rendered into the text but
    survives in `raw_text` for a future nested render (Lobsters' `depth`).
    """
    rows: list[tuple[tuple[int, ...], dict[str, Any], str]] = []
    for view in comments or []:
        if not isinstance(view, dict):
            continue
        comment = view.get("comment") or {}
        if comment.get("deleted") or comment.get("removed"):
            continue
        text = _text(comment.get("content"))
        if not text:
            continue
        rows.append((_path_key(comment.get("path")), view, text))
    rows.sort(key=lambda r: r[0])

    blocks = []
    for _, view, text in rows:
        name = _name(view.get("creator") or {})
        byline = f"Comment by {name}" if name else "Comment"
        score = (view.get("counts") or {}).get("score")
        if score is not None:
            byline += f" (score {score})"
        blocks.append(f"#### {byline}\n\n{text}")
    if not blocks:
        return ""
    return "### Comments\n\n" + "\n\n".join(blocks)


def _path_key(path: Any) -> tuple[int, ...]:
    """A comment `path` ("0.5.12") as an int tuple for pre-order sorting.

    A missing or malformed path sorts first (empty tuple) — a defensive default,
    since a real Lemmy comment always carries a dotted-integer path.
    """
    if not isinstance(path, str) or not path:
        return ()
    try:
        return tuple(int(seg) for seg in path.split("."))
    except ValueError:
        return ()


def _media_and_article(post: dict[str, Any]) -> tuple[tuple, str | None]:
    """Split the post's `url` into (media refs, external article link).

    A link post's `url` is an external article, recorded as a link (the Hacker
    News/Lobsters pattern). An *image* post's `url` is the image itself, so it
    is `photo` media instead — told apart by the `url_content_type` the API
    reports, falling back to the URL's extension. An article post's pict-rs
    `thumbnail_url` is kept as a preview `thumbnail` ref (the youtube/Mastodon
    thumbnail convention, ADR 0011), but not when the url already gave a photo
    (the thumbnail would just duplicate it).
    """
    refs: list[dict[str, Any]] = []
    article: str | None = None
    url = _clean(post.get("url"))
    if url:
        if _is_image(url, post.get("url_content_type")):
            refs.append({"type": "photo", "url": url})
        else:
            article = url
    thumbnail = _clean(post.get("thumbnail_url"))
    if thumbnail and not refs:
        refs.append({"type": "thumbnail", "url": thumbnail})
    return tuple(refs), article


def _is_image(url: str, content_type: Any) -> bool:
    """Whether a post `url` points at an image, by content type then extension."""
    if isinstance(content_type, str) and content_type.strip().lower().startswith("image/"):
        return True
    return urlparse(url).path.lower().endswith(_IMAGE_EXTS)


def _cross_post_links(data: dict[str, Any]) -> list[str]:
    """The `cross_posts` as links by their `ap_id` — the post↔post edges.

    A cross-post is the same submission posted to another community (often on
    another instance); its `ap_id` is that post's canonical URL, which resolves
    back through source detection to the saved cross-post if it is in the library
    (a Lemmy post↔post edge, kin to Misskey's quote-renote, ADR 0051).
    """
    out = []
    for cross in data.get("cross_posts") or []:
        if not isinstance(cross, dict):
            continue
        ap_id = _clean((cross.get("post") or {}).get("ap_id"))
        if ap_id:
            out.append(ap_id)
    return out


def _community_concepts(community: dict[str, Any]) -> tuple[str, ...]:
    """The community name as a single `concept` — the post's topical home.

    A Lemmy community (`c/rust`, `c/selfhosted`) is the one curated topical label
    a post carries, like a subreddit, so it feeds the KB concept graph the way
    github repo topics and Lobsters tags do (ADR 0007). The slug `name` is used
    (not the human `title`) since KB pages merge concepts by slug.
    """
    name = _clean(community.get("name"))
    return (name,) if name else ()


def _summary(body_text: str | None, counts: dict[str, Any]) -> str | None:
    """A text post's lead paragraph, else the discussion's engagement status.

    A link or image post has no body of its own (the content is elsewhere), so
    its honest summary is what Lemmy itself shows — score and comment count, the
    Hacker News/Lobsters pattern (ADR 0031, ADR 0046). A post with neither body
    nor counts gets no invented summary (the honestly-empty posture, ADR 0004).
    """
    if body_text:
        return body_text.split("\n\n", 1)[0].strip()
    score, comments = counts.get("score"), counts.get("comments")
    if score is None and comments is None:
        return None
    points = 0 if score is None else score
    replies = 0 if comments is None else comments
    return (
        f"Lemmy discussion: {points} {_plural(points, 'point')}, "
        f"{replies} {_plural(replies, 'comment')}."
    )


def _name(user: dict[str, Any]) -> str | None:
    """A user's display name, falling back to the bare username, else None."""
    return _clean(user.get("display_name")) or _clean(user.get("name"))


# A plain URL run in Markdown body text, stopping at whitespace or an angle
# bracket; trailing punctuation a prose scan over-captures is trimmed (Misskey's
# `_content_links`, ADR 0051).
_URL_RE = re.compile(r"https?://[^\s<>]+")
_URL_TRAILING = ".,;:!?\"')]}>"


def _content_links(body: Any) -> list[str]:
    """Plain `http(s)` URLs in the post body, trailing punctuation trimmed.

    The body is Markdown, so an outbound URL is read straight from it (Misskey's
    URL scan, ADR 0051): a post pointing at an arXiv paper or github repo wires
    to it through `scrolls related`/`graph` (the cross-source edges, ADR 0044).
    """
    if not isinstance(body, str):
        return []
    links = []
    for match in _URL_RE.finditer(body):
        url = match.group(0).rstrip(_URL_TRAILING)
        if url:
            links.append(url)
    return links


def _text(value: Any) -> str | None:
    """Markdown body/comment text reduced to clean searchable paragraphs, or None.

    Lemmy ships Markdown (already human-readable, no HTML to strip — Lobsters'
    `*_plain` economy, ADR 0046), so paragraphs are split on blank lines, their
    internal whitespace collapsed, and rejoined with one blank line — the same
    normalization the other social adapters apply, so the body reads alike.
    """
    if not isinstance(value, str):
        return None
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", value)]
    return "\n\n".join(p for p in paragraphs if p) or None


def _clean(value: Any) -> str | None:
    """A non-empty trimmed string, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _dedupe(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(v for v in values if v))


def _plural(count: int, noun: str) -> str:
    return noun if count == 1 else noun + "s"


_get_json = http.get_json
