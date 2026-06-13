"""Misskey fetch adapter (IDEAS.md §6, ADR 0051).

The third open social-post source, after Bluesky (ADR 0048) and Mastodon
(ADR 0049). Misskey — and its forks Sharkey, Firefish/Calckey, and Foundkey —
is Fediverse software like Mastodon, but it does *not* speak the Mastodon API:
where GoToSocial and Pleroma/Akkoma could ride the mastodon adapter unchanged
because they expose the identical `/api/v1/statuses/<id>` surface (ADR 0050),
Misskey has its own keyless API. So a saved `https://<instance>/notes/<id>`
note becomes a clean scroll from `<instance>/api/notes/show` — a *POST* with a
`{"noteId": <id>}` body, the first adapter to need the shared transport's
`post_json` (ADR 0051) — and that distinct API is why Misskey is its own source
and adapter rather than another mastodon URL shape.

Three facts shape the design, two shared with Mastodon and one its own:

1. **There is no shared host** (the Mastodon problem, ADR 0049). Detection
   (`detect.py`) recognizes a Misskey note by its `/notes/<id>` URL *shape* on
   whatever instance the saved URL names, and the instance host rides in the
   item id (`misskey:<host>/<id>`) because a note id is unique only within its
   instance. The adapter talks to that same host's API.

2. **The thread is a second request** (Bluesky/Mastodon/Stack Exchange's shape,
   ADR 0048/0049/0033). The note (`notes/show`) and its replies
   (`notes/children`) are two POSTs; a note with no replies skips the second,
   and a failed children fetch still produces a note-only scroll. Children
   arrive as a flat list, so the replies render in one pass.

3. **The content is plain text, not HTML.** A Misskey note's `text` is MFM
   (Misskey Flavored Markdown), already human-readable — unlike Mastodon's HTML
   `content`, it needs no stdlib HTML parser (Lobsters' `*_plain` economy,
   ADR 0046). Outbound links are plain URLs in that text, so they are extracted
   by a URL scan (a note pointing at an arXiv paper or github repo wiring to it
   through `scrolls related`/`graph`, the cross-source edges of ADR 0044); a
   quote-renote's note becomes a post↔post link. Hashtags (`tags`, bare names)
   become `concepts` the way github repo topics do (ADR 0007). Drive `files`
   become media — an image a `photo` (its `comment` alt text searchable when
   the note has none of its own), a video its thumbnail. A `cw` content warning
   leads the body so the hidden text stays honest and searchable. A pure renote
   (boost) unwraps to the boosted note (Mastodon's `reblog` rule). Like Bluesky,
   Mastodon, Hacker News (ADR 0031), and Lobsters, a heterogeneous social post
   gets *no* category default. The whole `{note, children}` is kept in
   `raw_text` for rebuilds.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

_TITLE_SNIPPET = 100
# Direct replies to render; deeper descendants stay in raw_text for a future
# nested render (Bluesky's depth cap, ADR 0048).
_REPLY_LIMIT = 30

PostJson = Callable[[str, Any], Any]


def fetch_item(item: ScrollItem, *, post_json: PostJson | None = None) -> ScrollItem:
    """Fetch a detected Misskey note and its replies; return it at stage 'fetched'.

    Raises FetchError when the source_id is missing/malformed, the request
    fails, or the note does not exist. The input item is never mutated.
    """
    post_json = post_json or _post_json
    host, note_id = _split_source_id(item)
    api = f"https://{host}/api"

    try:
        note = post_json(f"{api}/notes/show", {"noteId": note_id})
    except (OSError, ValueError) as exc:
        raise FetchError(f"misskey API request failed: {exc}") from exc
    if not isinstance(note, dict) or note.get("error") or "id" not in note:
        raise FetchError(f"misskey note not found: {host}/{note_id}")

    # A pure renote (boost) carries no text of its own and wraps the boosted
    # note; a quote-renote keeps its own text *and* a renote, so it is not
    # unwrapped — the renote becomes a post↔post link instead.
    renote = note.get("renote") if isinstance(note.get("renote"), dict) else None
    own_text = _clean(note.get("text"))
    post = renote if (renote is not None and not own_text) else note
    user = post.get("user") or {}

    text = _text(post.get("text"))
    media = _media(post.get("files"))
    quote_links = []
    if post is note and renote is not None and own_text:
        quoted = _note_url(renote, host)
        if quoted:
            quote_links.append(quoted)
    links = _dedupe(_content_links(post.get("text")) + quote_links)
    body = _body(text, post.get("cw"), media)

    children = _fetch_children(api, post, note_id, post_json)
    replies = _format_replies(children)
    extracted = "\n\n".join(part for part in (body, replies) if part) or None

    raw = json.dumps({"note": note, "children": children}, sort_keys=True, ensure_ascii=False)
    hashed = extracted or raw
    method = "misskey-api:note+thread" if replies else "misskey-api:note"
    return replace(
        item,
        title=_title(user, text),
        author=_display_name(user),
        published_at=to_utc_iso(post.get("createdAt")) or item.published_at,
        canonical_url=_note_url(post, host) or item.url,
        raw_text=raw,
        extracted_text=extracted,
        summary=_summary(text, media, post),
        concepts=_hashtags(post.get("tags")),
        links=links,
        media=media,
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "misskey",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _split_source_id(item: ScrollItem) -> tuple[str, str]:
    """The `<host>/<note_id>` source id into its two halves.

    The host is a single dotted hostname and the note id an opaque token (an
    `aid`/`aidx`/`objectid`/`ulid`) with no slash of its own, so one rsplit on
    the last slash is exact (Mastodon's `_split_source_id`, ADR 0049).
    """
    source_id = item.source_id or ""
    if "/" not in source_id:
        raise FetchError(f"cannot determine misskey note for item {item.id!r}")
    host, note_id = source_id.rsplit("/", 1)
    if not host or not note_id:
        raise FetchError(f"cannot determine misskey note for item {item.id!r}")
    return host, note_id


def _fetch_children(
    api: str, post: dict[str, Any], fallback_id: str, post_json: PostJson
) -> list[Any] | None:
    """The note's direct replies, or None when it has none or the fetch fails.

    A note with `repliesCount == 0` skips the second POST entirely (Bluesky's
    economy, ADR 0048); a failed children fetch degrades to a note-only scroll
    rather than failing the whole item (Stack Exchange's answers-are-optional
    rule, ADR 0033).
    """
    if (post.get("repliesCount") or 0) <= 0:
        return None
    note_id = _clean(post.get("id")) or fallback_id
    try:
        children = post_json(f"{api}/notes/children", {"noteId": note_id, "limit": _REPLY_LIMIT})
    except (OSError, ValueError):
        return None
    return children if isinstance(children, list) else None


def _text(text: Any) -> str | None:
    """A note's MFM `text` reduced to clean searchable paragraphs, or None.

    MFM is already plain text (no HTML grammar, unlike Mastodon), so paragraphs
    are split on blank lines, their internal whitespace collapsed, and rejoined
    with one blank line — the same normalization Mastodon applies after its HTML
    parse, so the body reads the same across the social adapters.
    """
    if not isinstance(text, str):
        return None
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paragraphs if p) or None


# A plain URL run in MFM text, stopping at whitespace or an angle bracket.
_URL_RE = re.compile(r"https?://[^\s<>]+")
# Trailing punctuation a URL scan over prose over-captures — sentence
# punctuation and the closing bracket of a `[label](url)` MFM/markdown link.
_URL_TRAILING = ".,;:!?\"')]}>"


def _content_links(text: Any) -> list[str]:
    """Plain `http(s)` URLs in the note text, trailing punctuation trimmed.

    Misskey has no Bluesky-style facet list or Mastodon-style link card, so
    outbound links are read straight from the MFM text. The trailing-punctuation
    trim handles a URL at the end of a sentence and the `)` of a `[label](url)`
    markdown link; a URL that legitimately ends in such a character (rare in a
    social post) loses it — a benign miss that just doesn't resolve an edge.
    """
    if not isinstance(text, str):
        return []
    links = []
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(_URL_TRAILING)
        if url:
            links.append(url)
    return links


def _body(text: str | None, cw: Any, media: tuple) -> str | None:
    """The searchable body: a content-warning line, the note text, else image alts.

    A `cw` content warning leads the body so the text it hides stays honest and
    searchable (Mastodon's `spoiler_text` rule, ADR 0049); a note with no text
    of its own falls back to its images' alt text (Bluesky's image-only rule,
    ADR 0048).
    """
    warning = _clean(cw)
    parts = [f"CW: {warning}" if warning else None, text or _image_alts(media)]
    return "\n\n".join(p for p in parts if p) or None


def _title(user: dict[str, Any], text: str | None) -> str:
    """A searchable title for a titleless note: byline plus its lead line.

    Social posts have no title field, so one is synthesized the way a feed UI
    labels a post — the author name and the opening of the text. An image- or
    link-only note (no text) falls back to a bare byline (Mastodon's `_title`).
    """
    name = _display_name(user) or "someone"
    if not text:
        return f"Post by {name} on Misskey"
    lead = " ".join(text.split("\n\n", 1)[0].split())
    if len(lead) > _TITLE_SNIPPET:
        lead = lead[:_TITLE_SNIPPET].rstrip() + "…"
    return f"{name}: {lead}"


def _acct(user: dict[str, Any]) -> str | None:
    """The fediverse handle: `@username` for a local user, `@username@host` remote."""
    username = _clean(user.get("username"))
    if not username:
        return None
    host = _clean(user.get("host"))
    return f"@{username}@{host}" if host else f"@{username}"


def _display_name(user: dict[str, Any]) -> str | None:
    """The user's display name, else `@acct`, else None (the byline form)."""
    return _clean(user.get("name")) or _acct(user)


def _byline(user: dict[str, Any]) -> str:
    """A reply byline: `Display (@acct)`, keeping the acct for identity."""
    name = _clean(user.get("name"))
    acct = _acct(user)
    if name and acct:
        return f"{name} ({acct})"
    return name or acct or "someone"


def _summary(text: str | None, media: tuple, post: dict[str, Any]) -> str | None:
    """The note's lead paragraph, else its image alt, else its engagement status.

    A text note leads with its own first paragraph. A note that is only an image
    has no prose, so its honest summary is the image alt text — failing that,
    the engagement status Misskey itself shows, the metadata-only fallback
    Bluesky and Mastodon use (ADR 0048, ADR 0049).
    """
    if text:
        return text.split("\n\n", 1)[0].strip()
    alts = _image_alts(media)
    if alts:
        return alts.split("\n\n", 1)[0].strip()
    reactions = _reaction_total(post)
    renotes = post.get("renoteCount")
    replies = post.get("repliesCount")
    if reactions is None and renotes is None and replies is None:
        return None
    reactions, renotes, replies = (n or 0 for n in (reactions, renotes, replies))
    return (
        f"Misskey post: {reactions} {_plural(reactions, 'reaction')}, "
        f"{renotes} {_plural(renotes, 'renote')}, "
        f"{replies} {_plural(replies, 'reply', 'replies')}."
    )


def _reaction_total(note: dict[str, Any]) -> int | None:
    """A note's total reactions: `reactionCount` if present, else the `reactions` sum.

    Misskey records reactions as a `{":emoji:": count}` map; older payloads
    carry a precomputed `reactionCount`, newer ones only the map, so the sum is
    the fallback. None when neither is present (so the summary can tell a note
    with no engagement data from one with zero reactions).
    """
    count = note.get("reactionCount")
    if isinstance(count, int):
        return count
    reactions = note.get("reactions")
    if isinstance(reactions, dict):
        return sum(v for v in reactions.values() if isinstance(v, int))
    return None


def _hashtags(tags: Any) -> tuple[str, ...]:
    """`#hashtag` names as `concepts`, deduped in document order.

    Misskey stores hashtags as bare strings (no `#`, unlike Mastodon's
    `{name, url}` objects); they are curated topical labels, so they feed the
    KB concept graph the way github repo topics do (ADR 0007).
    """
    if not isinstance(tags, list):
        return ()
    names = [t.strip() for t in tags if isinstance(t, str) and t.strip()]
    return tuple(dict.fromkeys(names))


def _media(files: Any) -> tuple:
    """Image and video drive `files` as media refs (a video keeps its thumbnail).

    An image is a `photo` ref pointing at its `url`; a video is a `thumbnail`
    ref pointing at its `thumbnailUrl` — the video file can be huge, so only its
    poster image is captured (the youtube/Mastodon thumbnail rule, ADR 0011,
    ADR 0049). Misskey's `comment` is the alt text, carried so an image-only
    note stays searchable. Audio and unknown MIME types contribute nothing
    rather than failing.
    """
    refs: list[dict[str, Any]] = []
    for f in files or []:
        if not isinstance(f, dict):
            continue
        mime = f.get("type") or ""
        if mime.startswith("image/"):
            url = _clean(f.get("url")) or _clean(f.get("thumbnailUrl"))
            kind = "photo"
        elif mime.startswith("video/"):
            url = _clean(f.get("thumbnailUrl")) or _clean(f.get("url"))
            kind = "thumbnail"
        else:
            continue
        if not url:
            continue
        ref: dict[str, Any] = {"type": kind, "url": url}
        alt = _clean(f.get("comment"))
        if alt:
            ref["alt"] = alt
        refs.append(ref)
    return tuple(refs)


def _note_url(note: dict[str, Any], host: str) -> str | None:
    """A note's canonical web URL: its `url`/`uri` if set, else built from the host.

    A remote note carries the original instance's `url`/`uri` (its ActivityPub
    id); a local note carries neither, so its URL is the implicit
    `https://<host>/notes/<id>` — the same `/notes/<id>` shape detection reads,
    so a quoted note's link resolves back through source detection (the
    post↔post edge).
    """
    url = _clean(note.get("url")) or _clean(note.get("uri"))
    if url:
        return url
    note_id = _clean(note.get("id"))
    return f"https://{host}/notes/{note_id}" if note_id else None


def _image_alts(media: tuple) -> str:
    """An image-only note's alt texts joined, so it is searchable by content."""
    alts = [ref["alt"] for ref in media if isinstance(ref, dict) and ref.get("alt")]
    return "\n\n".join(alts)


def _format_replies(children: list[Any] | None) -> str:
    """The flat `children` list as a bylined Markdown subsection.

    Misskey's `notes/children` returns direct replies as a flat list, so one
    pass renders them — each bylined with its author and reaction count
    (Mastodon's reply format, ADR 0049). A reply with no text (e.g. media-only)
    is skipped.
    """
    blocks: list[str] = []
    for reply in children or []:
        if not isinstance(reply, dict):
            continue
        text = _text(reply.get("text"))
        if not text:
            continue
        byline = f"Reply by {_byline(reply.get('user') or {})}"
        reactions = _reaction_total(reply)
        if reactions is not None:
            byline += f" ({reactions} {_plural(reactions, 'reaction')})"
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


_post_json = http.post_json
