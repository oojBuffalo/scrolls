"""Discourse fetch adapter (IDEAS.md §6, ADR 0054).

Discourse is the open-source forum software behind countless developer and
community sites — `discuss.python.org`, `meta.discourse.org`,
`users.rust-lang.org`, `discourse.llvm.org`, `forum.obsidian.md`, and thousands
more — and the centralized-forum sibling of the federated link aggregators Lemmy
(ADR 0052) and PieFed (ADR 0053) and the discussion aggregators Hacker News
(ADR 0031) and Lobsters (ADR 0046). A saved
`https://<instance>/t/<slug>/<topic_id>` topic becomes a clean scroll from that
instance's keyless `.json` view — no login, no token — instead of a
`trafilatura` scrape of a JS-rendered page.

Three facts shape the design, two shared with the link aggregators and one its
own:

1. **There is no shared host** (the Fediverse problem, ADR 0049/0052). Discourse
   runs on thousands of independent hosts, so detection (`detect.py`) recognizes
   a topic by its `/t/<slug>/<topic_id>` URL *shape* on whatever instance the
   saved URL names, and the instance host rides in the item id
   (`discourse:<host>/<topic_id>`) because a topic id is unique only within its
   instance. The adapter talks to that same host's `.json` view. The slug is
   display-only (Discourse redirects a wrong slug), so identity and the fetch
   both use the slug-free `/t/<topic_id>.json` route.

2. **The topic and its replies come in one request** (Lobsters' economy,
   ADR 0046, not the two-request shape of Lemmy/Mastodon). `GET /t/<id>.json`
   returns the topic *and* the first page of its `post_stream.posts` — the
   opening post plus the leading replies — so no second request is needed for a
   normal topic. A very long thread is bounded: only the first page renders, the
   full ordering (`post_stream.stream`, a list of every post id) surviving in
   `raw_text` for a future paged render (Bluesky's depth cap, ADR 0048).

3. **A Discourse topic is a forum thread, so it has a real title** (unlike a
   Bluesky/Mastodon social post, whose title is synthesized — like a Lemmy
   aggregator entry, ADR 0052). The opening post's content is the body; the
   later posts are bylined `### Replies`. The post `cooked` field is HTML, so it
   is reduced to plain searchable text by a stdlib parser (no `trafilatura`
   dependency — the keyless spirit of the adapter family, Mastodon's rule,
   ADR 0049). The topic's `tags` become `concepts` the way github repo topics do
   (ADR 0007); the topic's outbound `details.links` (the non-internal,
   non-reflection ones) become `links` so a thread pointing at an arXiv paper or
   github repo wires to it through `scrolls related`/`graph` (ADR 0044); the
   topic's representative `image_url` becomes a `thumbnail` media ref. Like the
   link aggregators and the social adapters, a heterogeneous forum thread gets
   *no* category default. The whole topic JSON is kept in `raw_text`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urlparse

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

# The Discourse "like" action's id in a post's `actions_summary` list.
_LIKE_ACTION_ID = 2

# Block-level HTML end tags in a `cooked` body that mark a paragraph boundary,
# so the reduced text keeps its structure (Mastodon reduces only `</p>`, but
# Discourse `cooked` is richer — lists, headings, quotes, code blocks).
_BLOCK_TAGS = frozenset(
    {"p", "li", "blockquote", "aside", "div", "tr", "pre", "h1", "h2", "h3", "h4", "h5", "h6"}
)

GetJson = Callable[[str], Any]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected Discourse topic and its replies; return it at stage 'fetched'.

    Raises FetchError when the source_id is missing/malformed, the request
    fails, or the response is not a Discourse topic (no `post_stream.posts`) —
    the benign-misdetect path a host-less URL shape forces. The input item is
    never mutated.
    """
    get_json = get_json or _get_json
    host, topic_id = _split_source_id(item)

    try:
        data = get_json(f"https://{host}/t/{topic_id}.json")
    except (OSError, ValueError) as exc:
        raise FetchError(f"discourse API request failed: {exc}") from exc
    posts = _topic_posts(data)
    if posts is None:
        raise FetchError(f"discourse topic not found: {host}/{topic_id}")

    details = data.get("details") if isinstance(data.get("details"), dict) else {}
    op = posts[0] if posts else None
    replies = posts[1:]

    body_text = _html_to_text(op.get("cooked")) if op else None
    replies_text = _format_replies(replies)
    extracted = "\n\n".join(part for part in (body_text, replies_text) if part) or None

    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    hashed = extracted or raw
    method = "discourse-api:topic+replies" if replies_text else "discourse-api:topic"
    return replace(
        item,
        title=_clean(data.get("title")) or item.title,
        author=_name(details.get("created_by") or {}) or (_name(op) if op else None),
        published_at=to_utc_iso(data.get("created_at")) or item.published_at,
        canonical_url=_canonical_url(host, topic_id, data),
        raw_text=raw,
        extracted_text=extracted,
        summary=_summary(body_text, data),
        concepts=_tags(data.get("tags")),
        links=_outbound_links(details),
        media=_media(host, data.get("image_url")),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "discourse",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _split_source_id(item: ScrollItem) -> tuple[str, str]:
    """The `<host>/<topic_id>` source id into its two halves.

    The host is a single dotted hostname and the topic id an all-digits run with
    no slash of its own, so one rsplit on the last slash is exact (Lemmy's
    `_split_source_id`, ADR 0052).
    """
    source_id = item.source_id or ""
    if "/" not in source_id:
        raise FetchError(f"cannot determine discourse topic for item {item.id!r}")
    host, topic_id = source_id.rsplit("/", 1)
    if not host or not topic_id:
        raise FetchError(f"cannot determine discourse topic for item {item.id!r}")
    return host, topic_id


def _topic_posts(data: Any) -> list[dict[str, Any]] | None:
    """The renderable posts (opening post first, then replies), or None.

    Returns None — read by `fetch_item` as "not a Discourse topic" — when the
    payload has no `post_stream.posts` list, which is what a non-Discourse
    `/t/<slug>/<digits>.json` URL returns (the benign-misdetect guard a
    host-less URL shape forces, ADR 0049/0052).

    The posts are sorted by `post_number` (the opening post is number 1) and
    filtered to renderable ones — moderator actions, small actions, whispers,
    and deleted/hidden posts carry no real content and are dropped, the way
    Lemmy skips deleted/removed comments (ADR 0052).
    """
    if not isinstance(data, dict):
        return None
    post_stream = data.get("post_stream")
    if not isinstance(post_stream, dict):
        return None
    posts = post_stream.get("posts")
    if not isinstance(posts, list):
        return None
    renderable = [p for p in posts if isinstance(p, dict) and _renderable(p)]
    renderable.sort(key=lambda p: p.get("post_number") or 0)
    return renderable


def _renderable(post: dict[str, Any]) -> bool:
    """Whether a post carries real content (not a deleted/hidden post or an action).

    Discourse `post_type` 1 is a regular post; 2 (moderator action), 3 (small
    action like "closed the topic"), and 4 (whisper) are not user content. A
    `deleted_at`/`user_deleted`/`hidden` post is skipped like a deleted Lemmy
    comment (ADR 0052).
    """
    if post.get("deleted_at") or post.get("user_deleted") or post.get("hidden"):
        return False
    return post.get("post_type") in (None, 1)


def _format_replies(replies: list[dict[str, Any]]) -> str:
    """The reply posts as a bylined Markdown `### Replies` subsection.

    Each reply is bylined with its author and like count the way a Mastodon
    reply is (ADR 0049) and a Lemmy comment is (ADR 0052) — the post `cooked`
    HTML reduced to text, a reply with no text (e.g. an image-only post) skipped.
    The posts arrive already in thread order (by `post_number`), so one pass
    renders them — Discourse's flat-with-`reply_to_post_number` tree is not
    re-nested here (the indentation is deferred to `raw_text`, Lemmy's posture).
    """
    blocks = []
    for post in replies:
        text = _html_to_text(post.get("cooked"))
        if not text:
            continue
        byline = f"Reply by {_byline(post)}"
        likes = _likes(post)
        if likes:
            byline += f" ({likes} {_plural(likes, 'like')})"
        blocks.append(f"#### {byline}\n\n{text}")
    if not blocks:
        return ""
    return "### Replies\n\n" + "\n\n".join(blocks)


def _likes(post: dict[str, Any]) -> int:
    """A post's like count, from the `actions_summary` "like" action, else 0."""
    for action in post.get("actions_summary") or []:
        if isinstance(action, dict) and action.get("id") == _LIKE_ACTION_ID:
            count = action.get("count")
            return count if isinstance(count, int) else 0
    return 0


def _byline(post: dict[str, Any]) -> str:
    """A post's byline: `Display Name (@username)`, keeping the username.

    Discourse posts carry both a `name` (display name, often blank) and a
    `username` (the handle); the byline pairs them when both are present and
    distinct, the way a Mastodon reply byline pairs display name and acct
    (ADR 0049), falling back to whichever exists.
    """
    name = _clean(post.get("name"))
    username = _clean(post.get("username"))
    if name and username and name != username:
        return f"{name} (@{username})"
    return name or (f"@{username}" if username else "someone")


def _name(user: dict[str, Any]) -> str | None:
    """A user's display name, falling back to the bare username, else None.

    The topic's `details.created_by` carries `name` (display) and `username`
    (handle); the display name is preferred, the way Lemmy prefers a creator's
    `display_name` over `name` (ADR 0052).
    """
    return _clean(user.get("name")) or _clean(user.get("username"))


def _summary(body_text: str | None, data: dict[str, Any]) -> str | None:
    """The opening post's lead paragraph, else the topic's engagement status.

    A normal topic leads its summary with its opening post's first paragraph.
    A topic whose opening post has no prose (an image-only or moved/empty OP)
    falls back to the engagement status Discourse itself shows — reply and like
    counts, the Hacker News/Lobsters/Lemmy pattern (ADR 0031, 0046, 0052) — and
    a topic with neither gets no invented summary (the honestly-empty posture,
    ADR 0004).
    """
    if body_text:
        return body_text.split("\n\n", 1)[0].strip()
    posts_count = data.get("posts_count")
    likes = data.get("like_count")
    if posts_count is None and likes is None:
        return None
    replies = max((posts_count or 1) - 1, 0)  # posts_count includes the opening post
    likes = likes or 0
    return (
        f"Discourse topic: {replies} {_plural(replies, 'reply', 'replies')}, "
        f"{likes} {_plural(likes, 'like')}."
    )


def _tags(tags: Any) -> tuple[str, ...]:
    """The topic's `tags` as `concepts`, deduped in order.

    Discourse tags are bare strings (`python`, `packaging`, `help`), the curated
    topical labels a topic carries, so they feed the KB concept graph the way
    github repo topics and Lemmy communities do (ADR 0007, 0052).
    """
    if not isinstance(tags, list):
        return ()
    return tuple(dict.fromkeys(t.strip() for t in tags if isinstance(t, str) and t.strip()))


def _outbound_links(details: dict[str, Any]) -> tuple[str, ...]:
    """The topic's outbound external links from `details.links`, deduped.

    Discourse aggregates every link in the topic into `details.links`, each
    flagged `internal` (a link to the same instance — navigation, excluded like
    Mastodon's mentions, ADR 0049) and `reflection` (an *incoming* link from
    another topic — excluded as it is not a link this thread makes). The
    remaining outbound links are the cross-source edges (ADR 0044): a thread
    pointing at an arXiv paper or github repo wiring to it through `scrolls
    related`/`graph`.
    """
    out = []
    for link in details.get("links") or []:
        if not isinstance(link, dict) or link.get("internal") or link.get("reflection"):
            continue
        url = _clean(link.get("url"))
        if url:
            out.append(url)
    return tuple(dict.fromkeys(out))


def _media(host: str, image_url: Any) -> tuple:
    """The topic's representative image as a single `thumbnail` media ref, else ().

    Discourse's `image_url` is the topic's social/preview image (usually the
    first image in the opening post); it is kept as a preview `thumbnail` ref
    (the youtube/Lemmy thumbnail convention, ADR 0011), resolved against the
    instance host when it is a site-relative path.
    """
    url = _clean(image_url)
    if not url:
        return ()
    if url.startswith("/"):
        url = f"https://{host}{url}"
    if urlparse(url).scheme not in ("http", "https"):
        return ()
    return ({"type": "thumbnail", "url": url},)


def _canonical_url(host: str, topic_id: str, data: dict[str, Any]) -> str:
    """The canonical topic URL `https://<host>/t/<slug>/<id>`, slug from the response.

    Discourse's canonical permalink carries the slug (it redirects the slug-free
    `/t/<id>` form to it), so the slug read back from the response rebuilds it;
    a response with no slug falls back to the slug-free form.
    """
    slug = _clean(data.get("slug"))
    return f"https://{host}/t/{slug}/{topic_id}" if slug else f"https://{host}/t/{topic_id}"


class _HtmlToText(HTMLParser):
    """Reduce a Discourse post's `cooked` HTML to plain text.

    Block-level end tags (`</p>`, `</li>`, `</blockquote>`, headings, `</pre>`,
    …) become blank lines and `<br>` a newline so paragraph and list structure
    survives; `convert_charrefs` (the default) unescapes entities in the data.
    Unlike Mastodon's reducer this does not collect anchor hrefs — Discourse
    aggregates the topic's links in `details.links`, the cleaner source.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self._parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _html_to_text(content: Any) -> str | None:
    """A post's `cooked` HTML reduced to clean searchable paragraphs, or None.

    Paragraphs (split on the blank lines block tags leave) have their internal
    whitespace collapsed and are rejoined with one blank line — the Mastodon
    normalization (ADR 0049), so a forum post reads like every other adapter's
    body.
    """
    if not isinstance(content, str):
        return None
    parser = _HtmlToText()
    parser.feed(content)
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", parser.text())]
    return "\n\n".join(p for p in paragraphs if p) or None


def _clean(value: Any) -> str | None:
    """A non-empty trimmed string, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return singular
    return plural if plural is not None else singular + "s"


_get_json = http.get_json
