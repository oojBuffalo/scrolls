"""Bluesky fetch adapter (IDEAS.md §6, ADR 0048).

IDEAS.md §6 deliberately deferred X/Twitter because its auth/session
complexity is annoying, and when this adapter landed `x` items arrived only
through the Field Theory import (ADR 0009), with no native `x` fetch adapter,
so a pasted tweet URL registered but never enriched. X has since grown both a
native collection sync and a fetch adapter (ADR 0108), each borrowing the
browser's own session. Bluesky remains the open social network that needs none
of that: the AT Protocol exposes a fully public, keyless *AppView*
(`public.api.bsky.app`), so a saved `bsky.app/profile/<actor>/post/<rkey>` post
becomes a clean scroll without a login, a cookie, or a token — no session to
borrow, and none to expire.

It is also the cheapest of the discussion-aggregator adapters in spirit:
one `app.bsky.feed.getPostThread` call returns the post *and* its reply
tree, so the whole conversation arrives the way a Lobsters story's `.json`
returns its comment thread (ADR 0046) — except a Bluesky URL carries a
*handle* (or a DID), and the thread API is keyed by the post's AT-URI
(`at://<did>/app.bsky.feed.post/<rkey>`), which needs the DID. So when the
saved URL names a handle, a first keyless GET resolves it
(`com.atproto.identity.resolveHandle`) — the two-request shape Stack
Exchange (ADR 0033) and Hugging Face (ADR 0041) already use; a DID URL
skips straight to the thread.

The post `text` is the searchable content; its reply tree is rendered like
Lobsters comments (deleted/blocked nodes skipped, each bylined). An
external link card or a quoted post becomes a `link` so `scrolls related`/
`graph` resolve it — a post pointing at an arXiv paper, a github repo, or
another saved Bluesky post — the cross-source edges the adapters build
(ADR 0044). Inline `#hashtag` richtext facets become `concepts` the way
github repo topics do (ADR 0007); embedded images become `media` (their
alt text is searchable when the post has no text of its own). Like Hacker
News (ADR 0031) and Lobsters (ADR 0046), a heterogeneous social post gets
*no* category default — it stays unclassified until a title rule or the
LLM engine names it. The whole thread is kept in `raw_text` for rebuilds.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlencode

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import discussion
from scrolls.sources import http

# The keyless AppView (read-only, no auth) and the public web app whose URLs
# users save and whose form canonical/quoted-post links take.
APPVIEW_ROOT = "https://public.api.bsky.app"
WEB_ROOT = "https://bsky.app"
_POST_COLLECTION = "app.bsky.feed.post"
# Reply tree depth to render. Bluesky's default is 6; deeper threads keep
# their full structure in raw_text for a future enrichment.
_THREAD_DEPTH = 6
_TITLE_SNIPPET = 100

GetJson = Callable[[str], Any]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected Bluesky post and its thread; return it at stage 'fetched'.

    Raises FetchError when the source_id is missing/malformed, the handle
    cannot be resolved, the request fails, or the post does not exist. The
    input item is never mutated.
    """
    get_json = get_json or _get_json
    actor, rkey = _split_source_id(item)

    try:
        did = _resolve_did(actor, get_json)
        at_uri = f"at://{did}/{_POST_COLLECTION}/{rkey}"
        query = urlencode({"uri": at_uri, "depth": _THREAD_DEPTH, "parentHeight": 0})
        data = get_json(f"{APPVIEW_ROOT}/xrpc/app.bsky.feed.getPostThread?{query}")
    except (OSError, ValueError) as exc:
        raise FetchError(f"bluesky API request failed: {exc}") from exc

    thread = data.get("thread") if isinstance(data, dict) else None
    post = thread.get("post") if isinstance(thread, dict) else None
    if not isinstance(post, dict) or not isinstance(post.get("record"), dict):
        raise FetchError(f"bluesky post not found: {actor}/{rkey}")

    record = post["record"]
    author = post.get("author") or {}
    handle = (author.get("handle") or actor).strip()
    text = (record.get("text") or "").strip()

    media, links, card = _embed_media_and_links(post.get("embed") or {})
    links = _dedupe(_facet_links(record) + links)
    body = text or _image_alts(media)
    replies = _format_replies(thread.get("replies") or [])
    extracted = "\n\n".join(part for part in (body, replies) if part) or None

    raw = json.dumps(thread, sort_keys=True, ensure_ascii=False)
    hashed = extracted or raw
    method = "bluesky-appview:post+thread" if replies else "bluesky-appview:post"
    return replace(
        item,
        title=_title(author, text),
        author=_display_name(author),
        published_at=to_utc_iso(record.get("createdAt")) or item.published_at,
        canonical_url=f"{WEB_ROOT}/profile/{handle}/post/{rkey}",
        raw_text=raw,
        extracted_text=extracted,
        summary=_summary(text, media, card, post),
        concepts=_hashtags(record),
        links=links,
        media=media,
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "bluesky",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _split_source_id(item: ScrollItem) -> tuple[str, str]:
    """The `<actor>/<rkey>` source id back into its two halves.

    Both halves are single URL path segments — an actor (a dotted handle or
    a colon-separated DID) and the record key — so neither contains a slash
    and one rsplit is exact.
    """
    source_id = item.source_id or ""
    if "/" not in source_id:
        raise FetchError(f"cannot determine bluesky post for item {item.id!r}")
    actor, rkey = source_id.rsplit("/", 1)
    if not actor or not rkey:
        raise FetchError(f"cannot determine bluesky post for item {item.id!r}")
    return actor, rkey


def _resolve_did(actor: str, get_json: GetJson) -> str:
    """The DID for an actor: itself if already a DID, else one keyless lookup.

    A `bsky.app` URL may name a handle (`bsky.app`) or a DID
    (`did:plc:…`); the thread API is keyed by AT-URI, which needs the DID,
    so a handle costs one extra `resolveHandle` GET (the Stack Exchange /
    Hugging Face two-request shape) while a DID URL skips it.
    """
    if actor.startswith("did:"):
        return actor
    query = urlencode({"handle": actor})
    resolved = get_json(f"{APPVIEW_ROOT}/xrpc/com.atproto.identity.resolveHandle?{query}")
    did = resolved.get("did") if isinstance(resolved, dict) else None
    if not did:
        raise FetchError(f"could not resolve bluesky handle: {actor}")
    return did


def _title(author: dict[str, Any], text: str) -> str:
    """A searchable title for a titleless post: byline plus its lead line.

    Social posts have no title field, so one is synthesized the way a feed
    UI labels a post — the author name and the opening of the text — which
    keeps it searchable and gives the scroll file a meaningful slug. An
    image- or link-only post (no text) falls back to a bare byline.
    """
    name = _display_name(author) or "someone"
    if not text:
        return f"Post by {name} on Bluesky"
    snippet = " ".join(text.split())
    if len(snippet) > _TITLE_SNIPPET:
        snippet = snippet[:_TITLE_SNIPPET].rstrip() + "…"
    return f"{name}: {snippet}"


def _display_name(author: dict[str, Any]) -> str | None:
    """The author's display name, else `@handle`, else None (the byline form)."""
    display = (author.get("displayName") or "").strip()
    handle = (author.get("handle") or "").strip()
    return display or (f"@{handle}" if handle else None)


def _byline(author: dict[str, Any]) -> str:
    """A reply byline: `Display (@handle)`, keeping the handle for identity."""
    display = (author.get("displayName") or "").strip()
    handle = (author.get("handle") or "").strip()
    if display and handle:
        return f"{display} (@{handle})"
    return display or (f"@{handle}" if handle else "someone")


def _summary(
    text: str, media: tuple, card: dict[str, Any] | None, post: dict[str, Any]
) -> str | None:
    """The post's lead paragraph, else the linked card, else its status.

    A text post leads with its own first paragraph (Lobsters' pattern,
    ADR 0046). A post that is only an image or a link card has no prose, so
    its honest summary is the image alt text, then the card's title — failing
    those, the engagement status Bluesky itself shows, the metadata-only
    fallback Hacker News uses for a link story (ADR 0031).
    """
    if text:
        return text.split("\n\n", 1)[0].strip()
    alts = _image_alts(media)
    if alts:
        return alts.split("\n\n", 1)[0].strip()
    if card and (card.get("title") or "").strip():
        return card["title"].strip()
    likes = post.get("likeCount")
    reposts = post.get("repostCount")
    replies = post.get("replyCount")
    if likes is None and reposts is None and replies is None:
        return None
    likes, reposts, replies = (n or 0 for n in (likes, reposts, replies))
    return (
        f"Bluesky post: {likes} {_plural(likes, 'like')}, "
        f"{reposts} {_plural(reposts, 'repost')}, "
        f"{replies} {_plural(replies, 'reply', 'replies')}."
    )


def _hashtags(record: dict[str, Any]) -> tuple[str, ...]:
    """`#hashtag` richtext facets as `concepts`, deduped in document order.

    Bluesky stores hashtags as `app.bsky.richtext.facet#tag` features with a
    bare `tag` value (no `#`); they are curated topical labels, so they feed
    the KB concept graph the way github repo topics do (ADR 0007).
    """
    tags = [
        feature["tag"]
        for feature in _facet_features(record, "#tag")
        if feature.get("tag")
    ]
    return tuple(dict.fromkeys(tags))


def _facet_links(record: dict[str, Any]) -> list[str]:
    """Inline `#link` richtext facet URLs — links embedded in the post text."""
    return [
        feature["uri"]
        for feature in _facet_features(record, "#link")
        if feature.get("uri")
    ]


def _facet_features(record: dict[str, Any], suffix: str) -> list[dict[str, Any]]:
    """Every richtext facet feature whose `$type` ends with `suffix`."""
    out = []
    for facet in record.get("facets") or []:
        for feature in facet.get("features") or []:
            if str(feature.get("$type", "")).endswith(suffix):
                out.append(feature)
    return out


def _embed_media_and_links(
    embed: dict[str, Any],
) -> tuple[tuple, list[str], dict[str, Any] | None]:
    """Media refs, outbound links, and an external card from a hydrated embed.

    Handles the embed view types `getPostThread` returns: images (each
    `fullsize` is a `photo` media ref), an external link card (its `uri` is
    a link and the card itself titles a textless post's summary), a quoted
    post (`record` → the quoted post's web URL, a post↔post link),
    `recordWithMedia` (a quote *and* media — both), and a video (its
    `thumbnail` is a media ref). Unknown embed types contribute nothing
    rather than failing.
    """
    media: list[dict[str, Any]] = []
    links: list[str] = []
    card: dict[str, Any] | None = None
    etype = str(embed.get("$type", ""))

    if etype.endswith("embed.recordWithMedia#view"):
        media_list, links, card = _embed_media_and_links(embed.get("media") or {})
        media += media_list
        quoted = _quoted_post_url((embed.get("record") or {}).get("record") or {})
        if quoted:
            links.append(quoted)
        return tuple(media), links, card

    if etype.endswith("embed.images#view"):
        for image in embed.get("images") or []:
            url = image.get("fullsize") or image.get("thumb")
            if url:
                ref = {"type": "photo", "url": url}
                if image.get("alt"):
                    ref["alt"] = image["alt"].strip()
                media.append(ref)
    elif etype.endswith("embed.external#view"):
        external = embed.get("external") or {}
        if external.get("uri"):
            links.append(external["uri"])
            card = external
    elif etype.endswith("embed.record#view"):
        quoted = _quoted_post_url(embed.get("record") or {})
        if quoted:
            links.append(quoted)
    elif etype.endswith("embed.video#view"):
        if embed.get("thumbnail"):
            media.append({"type": "thumbnail", "url": embed["thumbnail"]})

    return tuple(media), links, card


def _quoted_post_url(record: dict[str, Any]) -> str | None:
    """The web URL of a quoted post, or None for a blocked/detached/missing one.

    A hydrated quote is a `#viewRecord` carrying the quoted post's AT-URI and
    author; its `bsky.app` URL resolves (through source detection) back to
    the quoted post's item id, the post↔post edge. A blocked, detached, or
    not-found quote is a different view type with no usable identity.
    """
    if not str(record.get("$type", "")).endswith("#viewRecord"):
        return None
    uri = record.get("uri") or ""
    handle = ((record.get("author") or {}).get("handle") or "").strip()
    rkey = uri.rsplit("/", 1)[-1] if "/" in uri else ""
    if not handle or not rkey:
        return None
    return f"{WEB_ROOT}/profile/{handle}/post/{rkey}"


def _image_alts(media: tuple) -> str:
    """An image-only post's alt texts joined, so it is searchable by content."""
    alts = [ref["alt"] for ref in media if isinstance(ref, dict) and ref.get("alt")]
    return "\n\n".join(alts)


def _format_replies(reply_nodes: list[Any]) -> str:
    """The reply tree as a Markdown subsection, flattened depth-first.

    Deleted, blocked, and not-found reply nodes carry no usable post and
    are skipped (Lobsters' deleted/moderated handling, ADR 0046); every
    other reply is bylined with its author and like count, and the depth-first
    `### Replies` subsection is assembled by the shared thread renderer
    (ADR 0093). Threading survives in `raw_text` for a future nested render.
    """
    rendered: list[discussion.Comment] = []
    _walk_replies(reply_nodes, rendered)
    return discussion.format_thread(rendered, heading="Replies")


def _walk_replies(nodes: list[Any], rendered: list[discussion.Comment]) -> None:
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        post = node.get("post")
        if isinstance(post, dict) and isinstance(post.get("record"), dict):
            text = (post["record"].get("text") or "").strip()
            if text:
                byline = f"Reply by {_byline(post.get('author') or {})}"
                likes = post.get("likeCount")
                if likes is not None:
                    byline += f" ({likes} {_plural(likes, 'like')})"
                rendered.append(discussion.Comment(byline, text))
        _walk_replies(node.get("replies") or [], rendered)


def _dedupe(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(v for v in values if v))


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return singular
    return plural if plural is not None else singular + "s"


_get_json = http.get_json
