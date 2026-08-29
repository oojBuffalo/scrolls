"""Wikipedia fetch adapter (IDEAS.md §6, ADR 0002).

One GET against the MediaWiki action API (`prop=extracts|info|categories|
links|extlinks`, `explaintext`, `redirects`) returns the full plain-text page
plus its canonical URL — no auth, no runtime dependencies. Visible
(editor-curated) page categories become `concepts`, joining github repo topics
as honest concept producers (ADR 0007); hidden maintenance categories are
excluded server-side. The raw page object is kept in `raw_text` so scrolls and
indexes can be rebuilt without refetching.

An article's outbound links are content, not decoration: mainspace links become
wiki URLs minted the same way `scrolls add` mints them, so `scrolls graph`
resolves a link between two saved articles into an edge — a wiki's backlinks,
answered from the library rather than from Wikipedia. External links follow
them, because on a Wikipedia article they are the citations.

Figures need a second GET (`generator=images` replaces the page set, so it
cannot ride along with the article query). MediaWiki lists every file a page
renders, so the editorial icons — `Commons-logo`, `Edit-clear`, the ambox
maintenance banners — are filtered out by name. That filter is a heuristic over
a slow-moving set, not a guarantee: a new icon leaks through as a media ref
until its pattern is added. The figures request is best-effort, because losing
a diagram must never cost the article text.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote, urlencode, urlsplit

from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

_API_PARAMS = {
    "action": "query",
    "format": "json",
    "formatversion": "2",
    "redirects": "1",
    "prop": "extracts|info|categories|links|extlinks",
    "explaintext": "1",
    "inprop": "url",
    "clshow": "!hidden",
    "cllimit": "max",
    "plnamespace": "0",
    "pllimit": "max",
    "ellimit": "max",
}

_IMAGE_PARAMS = {
    "action": "query",
    "format": "json",
    "formatversion": "2",
    "redirects": "1",
    "generator": "images",
    "gimlimit": "max",
    "prop": "imageinfo",
    "iiprop": "url|mime|size",
    "iiurlwidth": "1280",
}

# Widest raster kept whole. Above it MediaWiki's own thumbnail is taken
# instead: a 3857px press photo is not more useful to an agent than a
# 1280px one, and the original costs an order of magnitude more disk.
# Below it the original always wins — a vector diagram's "thumbnail" is a
# rasterization that is both larger and lossier than the SVG it came from.
_MAX_IMAGE_WIDTH = 1600

# MediaWiki reports every file a page renders, so an article's figures arrive
# mixed with the encyclopedia's own furniture. These are matched against the
# file name with the "File:" prefix stripped. Substring, not prefix: the icons
# appear as "OOjs UI icon edit-ltr-progressive.svg" and "Symbol support vote.svg"
# alike. Adding a pattern is the maintenance path when a new icon leaks through.
#
# Patterns are kept narrow on purpose. A pattern that is too broad drops a real
# figure silently, which is worse than an icon leaking in: "padlock-" spares an
# article's photograph of a padlock, and the vote symbols are named rather than
# matched as "symbol ".
_CHROME_PATTERNS = (
    "ambox",
    "commons-logo",
    "crystal clear",
    "disambig",
    "edit-clear",
    "emblem-",
    "folder hexagonal",
    "increase2.svg",
    "loudspeaker.svg",
    "merge-arrow",
    "nuvola",
    "oojs ui icon",
    "padlock-",
    "portal-puzzle",
    "question book",
    "red pog",
    "star full",
    "symbol comment",
    "symbol neutral vote",
    "symbol oppose vote",
    "symbol question",
    "symbol support vote",
    "text document",
    "wiki letter",
    "wikidata-logo",
    "wikiquote-logo",
    "wikisource-logo",
    "wikispecies-logo",
    "wikiversity-logo",
    "wiktionary-logo",
    "x mark",
    "yes check",
)

GetJson = Callable[[str], dict[str, Any]]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected Wikipedia item's page text; return the item at stage 'fetched'.

    Raises FetchError when the page identity is missing, the request fails,
    or the page does not exist. The input item is never mutated.
    """
    get_json = get_json or _get_json
    lang, _, title = (item.source_id or "").partition(":")
    if not lang or not title:
        raise FetchError(f"cannot determine wikipedia page for item {item.id!r}")

    url = _api_url(lang, title)
    try:
        payload = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"wikipedia API request failed: {exc}") from exc

    page = _single_page(payload)
    extract = page.get("extract") or ""
    if page.get("missing") or not extract:
        raise FetchError(f"wikipedia page not found: {lang}:{title}")

    return replace(
        item,
        title=page.get("title") or item.title,
        canonical_url=page.get("canonicalurl") or page.get("fullurl"),
        raw_text=json.dumps(page, ensure_ascii=False),
        extracted_text=extract,
        summary=_lead_section(extract),
        concepts=_concepts(page),
        links=_links(lang, page),
        media=_media(get_json, lang, title),
        content_hash="sha256:" + hashlib.sha256(extract.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "wikipedia",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "mediawiki-api:extracts",
        },
        stage="fetched",
    )


def _api_url(lang: str, title: str) -> str:
    query = urlencode({**_API_PARAMS, "titles": title})
    return f"https://{lang}.wikipedia.org/w/api.php?{query}"


def _image_api_url(lang: str, title: str) -> str:
    query = urlencode({**_IMAGE_PARAMS, "titles": title})
    return f"https://{lang}.wikipedia.org/w/api.php?{query}"


def encode_title(title: str) -> str:
    """Percent-encode a page title for a `/wiki/` URL.

    Spaces become underscores, as MediaWiki writes them. Parentheses are
    left literal, which is how Wikipedia publishes its own disambiguated
    titles; everything else is encoded, because a title like "24/7" carries
    a slash that is part of the title, not a path separator. Both forms mint
    the same item id, so this is a readability choice, not an identity one.
    """
    return quote(title.replace(" ", "_"), safe="()")


def article_url(lang: str, title: str) -> str:
    """The canonical `/wiki/` URL for a page.

    This is the one minting path: `detect.py` reads these URLs back into
    `wikipedia:<lang>:<title>` ids, so a captured link to a saved article
    resolves to that article in `scrolls graph`.
    """
    return f"https://{lang}.wikipedia.org/wiki/{encode_title(title)}"


def _links(lang: str, page: dict[str, Any]) -> tuple[str, ...]:
    """Mainspace article links, then the external citations, deduped in order."""
    urls = [
        article_url(lang, link["title"])
        for link in page.get("links") or ()
        if link.get("title")
    ]
    urls += [
        link["url"] for link in page.get("extlinks") or () if link.get("url")
    ]
    return tuple(dict.fromkeys(urls))


def _media(get_json: GetJson, lang: str, title: str) -> tuple[dict[str, Any], ...]:
    """The page's figures as media refs, or empty when they cannot be had.

    Never raises: an article whose figure list failed to load is still the
    article, and re-fetching it by id picks the figures up later.
    """
    try:
        payload = get_json(_image_api_url(lang, title))
    except (OSError, ValueError):
        return ()
    refs = []
    for file_page in (payload or {}).get("query", {}).get("pages") or ():
        name = (file_page.get("title") or "").partition(":")[2]
        info = (file_page.get("imageinfo") or [{}])[0]
        url = _clean_media_url(info.get("url"))
        if not name or not url or _is_chrome(name):
            continue
        ref = {"type": _media_type(info.get("mime"), url), "url": url, "title": name}
        thumb = _clean_media_url(info.get("thumburl"))
        if thumb and (info.get("width") or 0) > _MAX_IMAGE_WIDTH:
            # keep the full-resolution address: the capture is a choice, and
            # custody should record what was passed over, not hide it
            ref["url"], ref["original_url"] = thumb, url
        refs.append(ref)
    return tuple(refs)


# The Ogg profiles that pin a kind by extension; the multiplexed `.ogx`
# deliberately stays out — it can hold anything, so `file` is the honest type.
_OGG_SUFFIX_TYPES = {
    ".ogv": "video",
    ".ogg": "audio",  # Wikimedia's spoken-word and music files
    ".oga": "audio",
    ".opus": "audio",
}


def _media_type(mime: str | None, url: str = "") -> str:
    """The ref's media type, from the file's MIME type.

    A Wikipedia page carries spoken-word recordings and video as readily as
    diagrams, and calling an `.ogg` an image would be a claim the response
    does not support. MediaWiki reports the bare container `application/ogg`
    for Ogg media (ADR 0112's named gap), so there the extension carries the
    kind and the per-type size caps apply as an operator would expect.

    Args:
        mime: The MIME type MediaWiki reported for the file, if any.
        url: The file's URL; consulted only for `application/ogg`.

    Returns:
        One of 'image', 'audio', 'video', 'pdf', or 'file'.
    """
    kind, _, _ = (mime or "").partition("/")
    if kind in ("image", "audio", "video"):
        return kind
    if mime == "application/pdf":
        return "pdf"
    if mime == "application/ogg":
        path = urlsplit(url).path
        suffix = "." + path.rpartition(".")[2].lower() if "." in path else ""
        return _OGG_SUFFIX_TYPES.get(suffix, "file")
    return "file"


def _clean_media_url(url: str | None) -> str | None:
    """Drop the `utm_*` analytics parameters Wikimedia appends to imageinfo URLs.

    They describe the API call that produced the answer, not the file, and
    two captures of the same image must not differ by a campaign tag.
    """
    if not url:
        return None
    base, sep, query = url.partition("?")
    if not sep:
        return url
    kept = [
        pair
        for pair in query.split("&")
        if pair and not pair.startswith("utm_")
    ]
    return f"{base}?{'&'.join(kept)}" if kept else base


def _is_chrome(name: str) -> bool:
    """Whether a file name is Wikipedia's own furniture rather than a figure.

    The namespace badges ("Symbol list class.svg", "Symbol template class
    pink.svg") get their own rule rather than a bare "symbol " pattern,
    which would also discard a diode's schematic symbol or IEEE 315's
    circuit symbols — figures that are the article's whole subject.
    """
    lowered = name.lower()
    if lowered.startswith("symbol ") and " class" in lowered:
        return True
    return any(pattern in lowered for pattern in _CHROME_PATTERNS)


def _single_page(payload: dict[str, Any]) -> dict[str, Any]:
    pages = payload.get("query", {}).get("pages") or []
    if not pages:
        raise FetchError("wikipedia API returned no pages")
    return pages[0]


def _lead_section(extract: str) -> str:
    """Plain-text extract before the first '== Heading ==' marker."""
    return extract.split("\n==", 1)[0].strip()


def _concepts(page: dict[str, Any]) -> tuple:
    """Visible category names, with the localized 'Category:' prefix stripped."""
    names = []
    for category in page.get("categories") or ():
        title = category.get("title") or ""
        name = title.partition(":")[2] or title
        if name:
            names.append(name)
    return tuple(names)


_get_json = http.get_json
