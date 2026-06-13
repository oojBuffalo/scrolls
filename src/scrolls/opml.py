"""OPML subscription-list import (IDEAS.md §13, ADR 0076).

`scrolls import opml <path>` turns an OPML file — the universal feed-list
interchange format every RSS reader (Feedly, Inoreader, NetNewsWire,
Reeder, The Old Reader, …) exports — into feed subscriptions, the bulk
sibling of single-feed `scrolls follow` (ADR 0017).

Where the other bulk imports (browser bookmarks ADR 0030, Pocket ADR 0074)
insert *items* at stage 'detected', OPML imports *subscriptions*: an OPML
file is a list of feeds, not of saved pages, so each feed outline becomes a
row in the `subscriptions` table and the first `scrolls sync` discovers its
entries — the `import` = resumable spine, `sync` = the live deltas split of
IDEAS.md §13.

Unlike `scrolls follow`, which validates a feed by fetching it once, OPML
import is **network-free** like its bulk-import siblings: an OPML can hold
hundreds of feeds and the `xmlUrl` is *declared* to be a feed by the
exporting reader, so a feed is trusted on import the way a bookmarks
export's URLs are. A dead or wrong feed surfaces on its first sync, failing
only its own subscription, never the batch (`feeds.sync_many`). Because an
`xmlUrl` is already the canonical feed URL, a feed imported here gets the
same subscription id `scrolls follow` of that feed URL would mint, so an
import and a manual follow of the same feed dedupe on purpose — `follow`'s
extra page→feed mapping for YouTube channel/playlist *page* URLs (ADR 0017)
isn't applied here because an `xmlUrl` is a feed already, not a page.

OPML is XML: an `<opml>` document whose `<body>` holds nested `<outline>`
elements. A feed outline carries a non-empty `xmlUrl` attribute (the feed
URL); folder/category outlines carry none and only group their children, so
the whole tree is walked and every `xmlUrl`-bearing outline is a feed. The
outline's `text` (the OPML-required display attribute) or, failing that,
`title` names the subscription. Folder grouping is display metadata in the
source reader and is dropped — subscriptions carry no tags, and a feed's
entries get their own tags from detection at sync time.

The document is parsed from *bytes*, not text: every reader writes an XML
declaration with an encoding (`<?xml version="1.0" encoding="UTF-8"?>`) and
ElementTree rejects an encoding-declared `str`, so bytes input is both the
robust path and the one that honors a non-UTF-8 declaration.

Only `http`/`https` feeds are imported. The `feed:` pseudo-scheme some older
exporters emit (`feed://host/…`) is ambiguous between http and https, so it
is counted under `ignored.not_http` rather than guessed at; unwrapping it is
deferred to a future slice.

`scrolls export opml` (ADR 0077) is the inverse: `dump_opml_export` serializes
the library's subscriptions back to an OPML document, so the feeds you curate
in Scrolls can move to another reader — the round-trip that makes the import
honest. The export is flat (subscriptions carry no folders) and re-imports to
the same feeds.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

from scrolls.feeds import Subscription, make_subscription_id

_XMLURL = "xmlurl"  # the spec spells it `xmlUrl`; matched case-insensitively
_HEAD_TITLE = "Scrolls subscriptions"


class ImportSourceError(Exception):
    """The OPML export is missing, unreadable, or not an OPML document."""


def load_opml_export(path: Path) -> tuple[list[Subscription], dict]:
    """Parse an OPML file into feed subscriptions.

    Returns (subscriptions, stats). The whole outline tree is walked, so
    feeds nested in folders and top-level feeds alike surface in document
    order; a feed URL repeated within the file collapses to one subscription
    (`stats['repeats']` counts the extras) and a non-http(s) feed is skipped
    (`stats['ignored']['not_http']`). `stats['feeds']` counts the http(s)
    feed outlines only (duplicates included, non-http excluded), so the
    distinct subscriptions returned number `feeds - repeats`. Raises
    ImportSourceError only for
    document-level problems: a missing/unreadable path, malformed XML, or a
    well-formed document whose root is not `<opml>` (e.g. an RSS feed passed
    by mistake). An OPML with no feed outlines imports nothing without error.
    """
    root = _parse(path)
    imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ignored = {"not_http": 0}
    feeds = 0
    seen: dict[str, Subscription] = {}
    order: list[str] = []
    # match `<outline>` by local name, not `root.iter("outline")`: conformant
    # OPML has no namespace, but a default-namespaced document would make every
    # child `{ns}outline` and a literal-tag walk would silently find nothing —
    # the same namespace-tolerance `_parse` applies to the root tag
    for outline in root.iter():
        if _local_name(outline.tag) != "outline":
            continue
        raw = _attr(outline, _XMLURL)
        if not raw:
            continue  # a folder/grouping outline, not a feed
        feed_url = raw.strip()
        if not _is_http(feed_url):
            ignored["not_http"] += 1
            continue
        feeds += 1
        sub_id = make_subscription_id(feed_url)
        if sub_id in seen:
            continue  # a duplicate feed within the file
        seen[sub_id] = Subscription(
            id=sub_id,
            feed_url=feed_url,
            title=_label(outline),
            added_at=imported_at,
        )
        order.append(sub_id)

    subscriptions = [seen[sub_id] for sub_id in order]
    stats = {
        "feeds": feeds,
        "repeats": feeds - len(subscriptions),
        "ignored": ignored,
    }
    return subscriptions, stats


def dump_opml_export(subscriptions: Iterable[Subscription]) -> str:
    """Serialize subscriptions to an OPML 2.0 document — the import inverse.

    Returns a complete OPML document as text: an XML declaration, a `<head>`
    with a title, then a **flat** `<body>` of
    `<outline type="rss" text=… title=… xmlUrl=…>` rows, one per subscription
    in the given order. A subscription with no title labels itself by its feed
    URL (OPML requires a display `text`). The list is flat because
    subscriptions carry no folder grouping — the import dropped it (ADR 0076),
    so the export honestly emits none rather than inventing one. Attribute
    values are XML-escaped, so a feed URL with `&` survives a re-import, and the
    document parses back through `load_opml_export` to the same feeds (the
    round-trip the importer's id and title rules guarantee).
    """
    opml = ElementTree.Element("opml", {"version": "2.0"})
    head = ElementTree.SubElement(opml, "head")
    ElementTree.SubElement(head, "title").text = _HEAD_TITLE
    body = ElementTree.SubElement(opml, "body")
    for subscription in subscriptions:
        label = subscription.title or subscription.feed_url
        ElementTree.SubElement(
            body,
            "outline",
            {
                "type": "rss",
                "text": label,
                "title": label,
                "xmlUrl": subscription.feed_url,
            },
        )
    ElementTree.indent(opml)
    document = ElementTree.tostring(opml, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{document}\n'


def _parse(path: Path) -> ElementTree.Element:
    """The `<opml>` root element, or an ImportSourceError for any other shape."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ImportSourceError(f"no OPML export at {path}: {exc}") from exc
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise ImportSourceError(f"could not parse OPML: {exc}") from exc
    if _local_name(root.tag) != "opml":
        raise ImportSourceError(
            f"not an OPML document (expected <opml>, got <{root.tag}>)"
        )
    return root


def _attr(outline: ElementTree.Element, name: str) -> str | None:
    """An outline attribute by lowercased name (OPML spells `xmlUrl` mixed)."""
    for key, value in outline.attrib.items():
        if _local_name(key).lower() == name:
            return value
    return None


def _label(outline: ElementTree.Element) -> str | None:
    """The outline's display label: `text` (spec-required) then `title`."""
    for name in ("text", "title"):
        value = _attr(outline, name)
        cleaned = " ".join((value or "").split())
        if cleaned:
            return cleaned
    return None


def _is_http(url: str) -> bool:
    return urlparse(url).scheme.lower() in ("http", "https")


def _local_name(tag: str) -> str:
    """A tag/attribute local name with any `{ns}` prefix dropped (OPML has none)."""
    return tag.rsplit("}", 1)[-1]
