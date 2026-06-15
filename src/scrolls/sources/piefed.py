"""PieFed fetch adapter (IDEAS.md §6, ADR 0053).

PieFed is the *other* federated link aggregator — a Reddit-shaped, ActivityPub
discussion site like Lemmy (ADR 0052), and the analog of GoToSocial to Mastodon:
a younger, compatible-ish implementation of the same niche. But two facts pull it
between the two precedents the project already has for "a compatible sibling":

1. **Its URL shape is identical to Lemmy's.** A PieFed post permalink is
   `https://<instance>/post/<id>` with an autoincrement integer id — byte-for-byte
   the shape `detect.py`'s `_lemmy_id` already claims for `lemmy`. So PieFed is
   *not* its own detected source (there is nothing in the URL to tell it from
   Lemmy). It is reached, like DataCite behind Crossref (ADR 0045), by a
   fetch-time fallback behind the `lemmy` detection: the `threadiverse.py`
   dispatcher tries Lemmy's `/api/v3`, then PieFed's `/api/alpha`.

2. **Its API is its own.** PieFed serves `/api/alpha`, not Lemmy's `/api/v3`, and
   though it is deliberately Lemmy-*shaped* (a `post_view` of `post`/`creator`/
   `community`/`counts`, a flat comment list with a materialized-path tree), the
   field names diverge enough that it cannot ride Lemmy's adapter the way
   GoToSocial rides Mastodon's (ADR 0050): `post.title` not `post.name`,
   `creator.user_name` not `creator.name`, `comment.body` not `comment.content`,
   and a `post_type` enum (`Image`/`Link`/`Discussion`/…) instead of Lemmy's
   `url_content_type`. So PieFed needs its own normalization — its own adapter —
   even though it shares Lemmy's *source* and identity.

The result is a hybrid of the two precedents: PieFed is its own *adapter* (like
Misskey vs the mastodon forks, ADR 0051) but not its own *detected source* (like
DataCite vs Crossref, ADR 0045). Identity stays `lemmy:<host>/<post_id>` — minted
at `add` time, before the backend (Lemmy or PieFed) is knowable — and
`provenance.adapter="piefed"` records which API actually answered, exactly as a
DataCite-served DOI keeps `source="crossref"` with `provenance.adapter="datacite"`.

Everything downstream of the field-name mapping mirrors the Lemmy adapter: the
post + comments are two GETs (the second skipped when there are none, degrading on
failure); the flat comments are sorted into thread pre-order by their integer
`path` and bylined with author and score; a link post's external `url` is a
`link`, a text post's Markdown `body` is the searchable content, an image post's
`url` is `photo` media; body URLs and cross-posts are post↔post / cross-source
edges; the community is the one `concept`; and a heterogeneous aggregator entry
gets *no* category default. The whole `{post, comments}` is kept in `raw_text`.
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
from scrolls.sources import discussion
from scrolls.sources import http
from scrolls.sources import urls

# Comments to request: bounded so a huge thread stays a tractable scroll, the
# deeper tail surviving in raw_text for a future render (Lemmy's cap, ADR 0052).
_MAX_DEPTH = 8
_COMMENT_LIMIT = 50

# Image extensions a post `url` points at when it is itself an image — the
# fallback when `post_type` is absent or unexpected (Lemmy's `_IMAGE_EXTS`).
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif")

GetJson = Callable[[str], Any]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected PieFed post and its comments; return it at stage 'fetched'.

    Raises FetchError when the source_id is missing/malformed, the request
    fails, or the post does not exist (the dispatcher reads that FetchError as
    "not a PieFed instance either"). The input item is never mutated.
    """
    get_json = get_json or _get_json
    host, post_id = _split_source_id(item)
    api = f"https://{host}/api/alpha"

    try:
        data = get_json(f"{api}/post?id={post_id}")
    except (OSError, ValueError) as exc:
        raise FetchError(f"piefed API request failed: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("post_view"), dict):
        raise FetchError(f"piefed post not found: {host}/{post_id}")
    post_view = data["post_view"]
    post = post_view.get("post")
    if not isinstance(post, dict) or "id" not in post:
        raise FetchError(f"piefed post not found: {host}/{post_id}")

    creator = post_view.get("creator") or {}
    community = post_view.get("community") or {}
    counts = post_view.get("counts") or {}

    body_text = _text(post.get("body"))
    media, article = _media_and_article(post)
    links = _dedupe(
        ([article] if article else [])
        + _content_links(post.get("body"))
        + _cross_post_links(post, host)
    )

    comments = _fetch_comments(api, post_id, counts.get("comments") or 0, get_json)
    comments_text = _format_comments(comments)
    extracted = "\n\n".join(part for part in (body_text, comments_text) if part) or None

    raw = json.dumps({"post": data, "comments": comments}, sort_keys=True, ensure_ascii=False)
    hashed = extracted or raw
    method = "piefed-api:post+comments" if comments_text else "piefed-api:post"
    return replace(
        item,
        title=_clean(post.get("title")) or item.title,
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
            "adapter": "piefed",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _split_source_id(item: ScrollItem) -> tuple[str, str]:
    """The `<host>/<post_id>` source id into its two halves.

    Identical to Lemmy's split because the source id is the same — a PieFed post
    is detected and registered as a `lemmy` item (its URL is indistinguishable),
    so `<host>/<post_id>` is exactly what `_lemmy_id` minted (ADR 0053).
    """
    source_id = item.source_id or ""
    if "/" not in source_id:
        raise FetchError(f"cannot determine piefed post for item {item.id!r}")
    host, post_id = source_id.rsplit("/", 1)
    if not host or not post_id:
        raise FetchError(f"cannot determine piefed post for item {item.id!r}")
    return host, post_id


def _fetch_comments(
    api: str, post_id: str, count: int, get_json: GetJson
) -> list[Any] | None:
    """The post's comments, or None when it has none or the fetch fails.

    A post with zero comments skips the second GET entirely (Lemmy's economy,
    ADR 0052); a failed comment fetch degrades to a post-only scroll rather than
    failing the whole item (Stack Exchange's answers-are-optional rule, ADR 0033).
    `sort` is deliberately omitted (PieFed's comment-sort vocabulary differs from
    Lemmy's, and a rejected value would needlessly degrade the scroll): the flat
    list is re-sorted by `path` here anyway, so server order is irrelevant.
    """
    if count <= 0:
        return None
    url = (
        f"{api}/comment/list?post_id={post_id}"
        f"&max_depth={_MAX_DEPTH}&limit={_COMMENT_LIMIT}"
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

    PieFed (like Lemmy, ADR 0052) returns a flat list whose `path` (`"0.<id>"`,
    `"0.<parent>.<id>"`) encodes the tree, so sorting by the path's integer
    segments puts a parent immediately before its replies. Deleted and
    moderator-removed comments carry no usable text and are skipped (Lobsters'
    rule, ADR 0046); every other comment is bylined with its author and score the
    way Stack Exchange bylines an answer (ADR 0033) and assembled by the shared
    thread renderer (ADR 0093). The comment text is in `body` (Lemmy's field is
    `content`). The threading `path` is not rendered into the text but survives in
    `raw_text` for a future nested render.
    """
    rows: list[tuple[tuple[int, ...], dict[str, Any], str]] = []
    for view in comments or []:
        if not isinstance(view, dict):
            continue
        comment = view.get("comment") or {}
        if comment.get("deleted") or comment.get("removed"):
            continue
        text = _text(comment.get("body"))
        if not text:
            continue
        rows.append((_path_key(comment.get("path")), view, text))
    rows.sort(key=lambda r: r[0])

    rendered = []
    for _, view, text in rows:
        name = _name(view.get("creator") or {})
        byline = f"Comment by {name}" if name else "Comment"
        score = (view.get("counts") or {}).get("score")
        if score is not None:
            byline += f" (score {score})"
        rendered.append(discussion.Comment(byline, text))
    return discussion.format_thread(rendered, heading="Comments")


def _path_key(path: Any) -> tuple[int, ...]:
    """A comment `path` ("0.5.12") as an int tuple for pre-order sorting.

    A missing or malformed path sorts first (empty tuple) — a defensive default,
    since a PieFed comment, like a Lemmy one, carries a dotted-integer path.
    """
    if not isinstance(path, str) or not path:
        return ()
    try:
        return tuple(int(seg) for seg in path.split("."))
    except ValueError:
        return ()


def _media_and_article(post: dict[str, Any]) -> tuple[tuple, str | None]:
    """Split the post's `url` into (media refs, external article link).

    The Lemmy logic (ADR 0052), but driven by PieFed's `post_type` enum rather
    than Lemmy's `url_content_type`: a `post_type == "Image"` post's `url` is the
    image itself, recorded as `photo` media; any other post's `url` (a `Link`,
    `Video`, …) is an external article/resource recorded as a `link` — so a PieFed
    video post pointing at a YouTube URL becomes a link that resolves to a saved
    YouTube item, a cross-source edge for free. The `post_type` read falls back to
    the URL extension when the enum is absent or unexpected. An article post's
    pict-rs `thumbnail_url` is kept as a preview `thumbnail` (the youtube/Mastodon
    convention, ADR 0011), but not when the url already gave a photo.
    """
    refs: list[dict[str, Any]] = []
    article: str | None = None
    url = _clean(post.get("url"))
    if url:
        if _is_image(url, post.get("post_type")):
            refs.append({"type": "photo", "url": url})
        else:
            article = url
    thumbnail = _clean(post.get("thumbnail_url"))
    if thumbnail and not refs:
        refs.append({"type": "thumbnail", "url": thumbnail})
    return tuple(refs), article


def _is_image(url: str, post_type: Any) -> bool:
    """Whether a post `url` points at an image, by `post_type` then extension."""
    if isinstance(post_type, str) and post_type.strip().lower() == "image":
        return True
    return urlparse(url).path.lower().endswith(_IMAGE_EXTS)


def _cross_post_links(post: dict[str, Any], host: str) -> list[str]:
    """The `cross_posts` as same-instance post links — the post↔post edges.

    A cross-post is the same submission in another community. PieFed nests its
    cross-posts *on the post* as `{post_id, community_name, reply_count}` with no
    `ap_id` (Lemmy puts full post views with `ap_id` at the response top level,
    ADR 0052), so the link is built as `https://<host>/post/<post_id>` on the
    fetched instance — which resolves back through source detection to the saved
    cross-post if it is in the library (a PieFed post↔post edge, ADR 0044). Only
    an integer `post_id` yields a link (no id → no honest URL).
    """
    out = []
    for cross in post.get("cross_posts") or []:
        if not isinstance(cross, dict):
            continue
        post_id = cross.get("post_id")
        if isinstance(post_id, int):
            out.append(f"https://{host}/post/{post_id}")
    return out


def _community_concepts(community: dict[str, Any]) -> tuple[str, ...]:
    """The community name as a single `concept` — the post's topical home.

    A PieFed community (`c/technology`, `c/piefed_meta`) is the one curated
    topical label a post carries, like a subreddit, so it feeds the KB concept
    graph the way github repo topics and Lemmy communities do (ADR 0007, 0052).
    The slug `name` is used (not the human `title`) since KB pages merge by slug.
    """
    name = _clean(community.get("name"))
    return (name,) if name else ()


def _summary(body_text: str | None, counts: dict[str, Any]) -> str | None:
    """A text post's lead paragraph, else the discussion's engagement status.

    A link or image post has no body of its own, so its honest summary is what
    PieFed itself shows — score and comment count, the Hacker News/Lobsters/Lemmy
    pattern (ADR 0031, 0046, 0052). A post with neither body nor counts gets no
    invented summary (the honestly-empty posture, ADR 0004).
    """
    if body_text:
        return body_text.split("\n\n", 1)[0].strip()
    score, comments = counts.get("score"), counts.get("comments")
    if score is None and comments is None:
        return None
    points = 0 if score is None else score
    replies = 0 if comments is None else comments
    return (
        f"PieFed discussion: {points} {_plural(points, 'point')}, "
        f"{replies} {_plural(replies, 'comment')}."
    )


def _name(user: dict[str, Any]) -> str | None:
    """A user's display name, falling back to the bare username, else None.

    PieFed's username field is `user_name` (Lemmy's is `name`); the human label
    is `display_name` in both.
    """
    return _clean(user.get("display_name")) or _clean(user.get("user_name"))


def _content_links(body: Any) -> list[str]:
    """Plain `http(s)` URLs in the post body, trailing punctuation trimmed.

    The body is Markdown, so an outbound URL is read straight from it by the
    shared body-URL scan (ADR 0094): a post pointing at an arXiv paper or github
    repo wires to it through `scrolls related`/`graph` (cross-source edges,
    ADR 0044).
    """
    return urls.scan_urls(body)


def _text(value: Any) -> str | None:
    """Markdown body/comment text reduced to clean searchable paragraphs, or None.

    PieFed ships Markdown (already human-readable, no HTML to strip — Lemmy's
    economy, ADR 0052), so paragraphs are split on blank lines, their internal
    whitespace collapsed, and rejoined with one blank line.
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
