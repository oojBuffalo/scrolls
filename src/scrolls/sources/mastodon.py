"""Mastodon fetch adapter (IDEAS.md §6, ADR 0049).

The open-network social-post sibling of the Bluesky adapter (ADR 0048).
Where Bluesky is one network behind one AppView host, Mastodon is the
*Fediverse*: thousands of independent instances (`mastodon.social`,
`hachyderm.io`, `infosec.exchange`, …) speaking one keyless REST API. A
saved `https://<instance>/@<user>/<id>` status becomes a clean scroll from
`<instance>/api/v1/statuses/<id>` — no login, no token — instead of a
`trafilatura` scrape of a JS-rendered page.

Two facts shape the design:

1. **There is no shared host.** Detection (`detect.py`) can't key off a
   hostname the way every other adapter does, so a Mastodon status is
   recognized by its URL *shape* on whatever instance the saved URL names,
   and the instance host rides in the item id (`mastodon:<host>/<id>`)
   because a status id is unique only within its instance. The adapter
   talks to that same host's API.

2. **The thread is a second request.** The status (`/statuses/:id`) and its
   reply tree (`/statuses/:id/context`) are two endpoints — the
   two-request shape Stack Exchange (ADR 0033) and Bluesky (ADR 0048) use.
   `context.descendants` arrives already flattened (unlike Bluesky's nested
   tree), so the replies render with one pass; a status with none, or a
   failed context fetch, still produces a post-only scroll.

The post `content` is HTML (`<p>`, `<br>`, `<a>`); it is reduced to plain
text with a stdlib parser (no `trafilatura` dependency — the keyless spirit
of the adapter family). Inline `#hashtag` links become `concepts` the way
github repo topics do (ADR 0007); the external link card and any plain
outbound links in the body become `links` (a post pointing at an arXiv
paper or github repo wiring to it through `scrolls related`/`graph`, the
cross-source edges of ADR 0044); `@mention` and `#hashtag` anchors are
*not* outbound links. Image attachments become `photo` media (their alt
text searchable when the post has none of its own), video attachments
their preview image. A content warning (`spoiler_text`) leads the body so
the hidden text stays honest and searchable. Like Bluesky, Hacker News
(ADR 0031), and Lobsters (ADR 0046), a heterogeneous social post gets *no*
category default — unclassified until a title rule or the LLM engine names
it. The whole thread is kept in `raw_text` for rebuilds.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

_TITLE_SNIPPET = 100

GetJson = Callable[[str], Any]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected Mastodon status and its thread; return it at stage 'fetched'.

    Raises FetchError when the source_id is missing/malformed, the request
    fails, or the status does not exist. The input item is never mutated.
    """
    get_json = get_json or _get_json
    host, status_id = _split_source_id(item)
    api_root = f"https://{host}/api/v1/statuses/{status_id}"

    try:
        status = get_json(api_root)
    except (OSError, ValueError) as exc:
        raise FetchError(f"mastodon API request failed: {exc}") from exc
    if not isinstance(status, dict) or status.get("error") or "id" not in status:
        raise FetchError(f"mastodon post not found: {host}/{status_id}")

    # A boost (reblog) wraps an empty shell around the real post.
    post = status.get("reblog") if isinstance(status.get("reblog"), dict) else status
    account = post.get("account") or {}

    text = _html_to_text(post.get("content"))
    media = _media(post.get("media_attachments"))
    card, card_link = _card(post.get("card"))
    links = _dedupe(_content_links(post.get("content")) + card_link)
    body = _body(text, post.get("spoiler_text"), media)

    context = _fetch_context(api_root, post, get_json)
    replies = _format_replies(context)
    extracted = "\n\n".join(part for part in (body, replies) if part) or None

    raw = json.dumps({"status": status, "context": context}, sort_keys=True, ensure_ascii=False)
    hashed = extracted or raw
    method = "mastodon-api:status+thread" if replies else "mastodon-api:status"
    return replace(
        item,
        title=_title(account, text),
        author=_display_name(account),
        published_at=to_utc_iso(post.get("created_at")) or item.published_at,
        canonical_url=_clean(post.get("url")) or _clean(post.get("uri")) or item.url,
        raw_text=raw,
        extracted_text=extracted,
        summary=_summary(text, media, card, post),
        concepts=_hashtags(post.get("tags")),
        links=links,
        media=media,
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "mastodon",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _split_source_id(item: ScrollItem) -> tuple[str, str]:
    """The `<host>/<status_id>` source id into its two halves.

    The host is a single dotted hostname and the status id a run of digits,
    so neither contains a slash and one rsplit is exact.
    """
    source_id = item.source_id or ""
    if "/" not in source_id:
        raise FetchError(f"cannot determine mastodon post for item {item.id!r}")
    host, status_id = source_id.rsplit("/", 1)
    if not host or not status_id:
        raise FetchError(f"cannot determine mastodon post for item {item.id!r}")
    return host, status_id


def _fetch_context(api_root: str, post: dict[str, Any], get_json: GetJson) -> dict[str, Any] | None:
    """The status's reply context, or None when it has no replies or the fetch fails.

    A status with `replies_count == 0` skips the second request entirely
    (Bluesky's economy, ADR 0048); a failed context fetch degrades to a
    post-only scroll rather than failing the whole item (Stack Exchange's
    answers-are-optional rule, ADR 0033).
    """
    if (post.get("replies_count") or 0) <= 0:
        return None
    try:
        context = get_json(f"{api_root}/context")
    except (OSError, ValueError):
        return None
    return context if isinstance(context, dict) else None


class _HtmlToText(HTMLParser):
    """Reduce Mastodon status HTML to plain text, collecting outbound links.

    `<p>` boundaries become blank lines and `<br>` a newline so paragraph
    structure survives; `convert_charrefs` (the default) unescapes entities
    in the data. Anchor hrefs are collected too, except `@mention` and
    `#hashtag` links — Mastodon marks those with a `mention`/`hashtag`
    class — which are navigation, not outbound references.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self._parts.append("\n")
        elif tag == "a":
            attr = dict(attrs)
            href = (attr.get("href") or "").strip()
            classes = attr.get("class") or ""
            if href and "mention" not in classes and "hashtag" not in classes:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "p":
            self._parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _parse(content: Any) -> _HtmlToText:
    parser = _HtmlToText()
    if isinstance(content, str):
        parser.feed(content)
    return parser


def _html_to_text(content: Any) -> str | None:
    """A status's HTML content reduced to plain text, or None when empty.

    Paragraphs (split on the blank lines `</p>` leaves) have their internal
    whitespace collapsed and are rejoined with one blank line, so the body
    is clean searchable text with structure preserved.
    """
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", _parse(content).text())]
    return "\n\n".join(p for p in paragraphs if p) or None


def _content_links(content: Any) -> list[str]:
    """Plain outbound links in the status body (not `@mention`/`#hashtag` anchors)."""
    return _parse(content).links


def _body(text: str | None, spoiler: Any, media: tuple) -> str | None:
    """The searchable body: a content-warning line, the post text, else image alts.

    A `spoiler_text` content warning leads the body so the text it hides
    stays honest and searchable; a post with no text of its own falls back
    to its images' alt text (Bluesky's image-only rule, ADR 0048).
    """
    cw = _clean(spoiler)
    parts = [f"CW: {cw}" if cw else None, text or _image_alts(media)]
    return "\n\n".join(p for p in parts if p) or None


def _title(account: dict[str, Any], text: str | None) -> str:
    """A searchable title for a titleless post: byline plus its lead line.

    Social posts have no title field, so one is synthesized the way a feed
    UI labels a post — the author name and the opening of the text. An
    image- or link-only post (no text) falls back to a bare byline.
    """
    name = _display_name(account) or "someone"
    if not text:
        return f"Post by {name} on Mastodon"
    lead = " ".join(text.split("\n\n", 1)[0].split())
    if len(lead) > _TITLE_SNIPPET:
        lead = lead[:_TITLE_SNIPPET].rstrip() + "…"
    return f"{name}: {lead}"


def _display_name(account: dict[str, Any]) -> str | None:
    """The account's display name, else `@acct`, else None (the byline form)."""
    display = (account.get("display_name") or "").strip()
    acct = (account.get("acct") or "").strip()
    return display or (f"@{acct}" if acct else None)


def _byline(account: dict[str, Any]) -> str:
    """A reply byline: `Display (@acct)`, keeping the acct for identity."""
    display = (account.get("display_name") or "").strip()
    acct = (account.get("acct") or "").strip()
    if display and acct:
        return f"{display} (@{acct})"
    return display or (f"@{acct}" if acct else "someone")


def _summary(
    text: str | None, media: tuple, card: dict[str, Any] | None, post: dict[str, Any]
) -> str | None:
    """The post's lead paragraph, else its image alt, the card title, or its status.

    A text post leads with its own first paragraph. A post that is only an
    image or a link card has no prose, so its honest summary is the image
    alt text, then the card's title — failing those, the engagement status
    Mastodon itself shows, the metadata-only fallback Bluesky and Hacker
    News use (ADR 0048, ADR 0031).
    """
    if text:
        return text.split("\n\n", 1)[0].strip()
    alts = _image_alts(media)
    if alts:
        return alts.split("\n\n", 1)[0].strip()
    if card and _clean(card.get("title")):
        return card["title"].strip()
    favourites = post.get("favourites_count")
    reblogs = post.get("reblogs_count")
    replies = post.get("replies_count")
    if favourites is None and reblogs is None and replies is None:
        return None
    favourites, reblogs, replies = (n or 0 for n in (favourites, reblogs, replies))
    return (
        f"Mastodon post: {favourites} {_plural(favourites, 'favourite')}, "
        f"{reblogs} {_plural(reblogs, 'boost')}, "
        f"{replies} {_plural(replies, 'reply', 'replies')}."
    )


def _hashtags(tags: Any) -> tuple[str, ...]:
    """`#hashtag` names as `concepts`, deduped in document order.

    Mastodon stores hashtags as `{name, url}` objects with a bare `name`
    (no `#`); they are curated topical labels, so they feed the KB concept
    graph the way github repo topics do (ADR 0007).
    """
    if not isinstance(tags, list):
        return ()
    names = [t["name"].strip() for t in tags if isinstance(t, dict) and _clean(t.get("name"))]
    return tuple(dict.fromkeys(names))


def _media(attachments: Any) -> tuple:
    """Image and video attachments as media refs (a video keeps its preview image).

    An image is a `photo` ref pointing at its full-size `url`; a video or
    GIF is a `thumbnail` ref pointing at its `preview_url` — the video file
    itself can be huge, so only its poster image is captured (the youtube
    thumbnail rule, ADR 0011). Alt text (`description`) rides along so an
    image-only post stays searchable. Audio and unknown types contribute
    nothing rather than failing.
    """
    refs: list[dict[str, Any]] = []
    for att in attachments or []:
        if not isinstance(att, dict):
            continue
        atype = att.get("type")
        if atype == "image":
            url = _clean(att.get("url")) or _clean(att.get("preview_url"))
            kind = "photo"
        elif atype in ("video", "gifv"):
            url = _clean(att.get("preview_url")) or _clean(att.get("url"))
            kind = "thumbnail"
        else:
            continue
        if not url:
            continue
        ref: dict[str, Any] = {"type": kind, "url": url}
        alt = _clean(att.get("description"))
        if alt:
            ref["alt"] = alt
        refs.append(ref)
    return tuple(refs)


def _card(card: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """A link-preview card and its URL as a one-element link list (or empty).

    Mastodon attaches one `card` describing the first link in the post; its
    `url` is the outbound link, and the card itself titles a textless
    link-only post's summary.
    """
    if not isinstance(card, dict):
        return None, []
    url = _clean(card.get("url"))
    return (card, [url]) if url else (None, [])


def _image_alts(media: tuple) -> str:
    """An image-only post's alt texts joined, so it is searchable by content."""
    alts = [ref["alt"] for ref in media if isinstance(ref, dict) and ref.get("alt")]
    return "\n\n".join(alts)


def _format_replies(context: dict[str, Any] | None) -> str:
    """The flat `descendants` list as a bylined Markdown subsection.

    Mastodon's context endpoint returns descendants already flattened in
    thread order, so one pass renders them — each bylined with its author
    and favourite count (Bluesky's reply format, ADR 0048). A reply with no
    text (e.g. media-only) is skipped.
    """
    descendants = context.get("descendants") if isinstance(context, dict) else None
    blocks: list[str] = []
    for reply in descendants or []:
        if not isinstance(reply, dict):
            continue
        text = _html_to_text(reply.get("content"))
        if not text:
            continue
        byline = f"Reply by {_byline(reply.get('account') or {})}"
        favourites = reply.get("favourites_count")
        if favourites is not None:
            byline += f" ({favourites} {_plural(favourites, 'favourite')})"
        blocks.append(f"#### {byline}\n\n{text}")
    if not blocks:
        return ""
    return "### Replies\n\n" + "\n\n".join(blocks)


def _clean(value: Any) -> str | None:
    """A non-empty trimmed string, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _dedupe(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(v for v in values if v))


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return singular
    return plural if plural is not None else singular + "s"


_get_json = http.get_json
