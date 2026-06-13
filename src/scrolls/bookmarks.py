"""Browser-bookmarks HTML import (IDEAS.md §13, ADR 0030).

`scrolls import bookmarks <path>` turns a Netscape-format bookmark
export — the `bookmarks.html` every major browser (and Pinboard-style
service) emits — into detected items. Like the Takeout import
(ADR 0029) this is a spine-only archive: a bookmark carries only URL,
anchor text, ADD_DATE, and folder placement, so items enter at stage
'detected' and `scrolls fetch` enriches them. Unlike Takeout the spine
is heterogeneous: every http(s) URL routes through the same source
detection as `scrolls add`, so a bookmarked video becomes a youtube
item and a repo a github item, with full dedupe against the rest of
the library.

Folder ancestry becomes `tags` — folders are the user's own curation,
free-form like `scrolls set` (root containers such as "Bookmarks bar"
are browser furniture, not curation, and are excluded). The format is
famously malformed HTML (unclosed <DT>/<DD>), so parsing is a stdlib
HTMLParser token stream, never a tree.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from scrolls.dates import epoch_to_utc_iso
from scrolls.items import ScrollItem, make_item_id
from scrolls.sources.detect import detect_source
from scrolls.sources.urls import normalize_url

_FORMAT_MARKER = "NETSCAPE-Bookmark-file"

# Container folders every browser invents around the user's own folders.
_ROOT_CONTAINERS = {
    "bookmarks bar", "bookmarks menu", "bookmarks toolbar",
    "other bookmarks", "mobile bookmarks", "unsorted bookmarks",
}


class ImportSourceError(Exception):
    """The bookmarks export is missing or not a Netscape-format file."""


def load_bookmark_export(path: Path) -> tuple[list[ScrollItem], dict]:
    """Parse a bookmarks HTML export into detected items.

    Returns (items, stats). Per-bookmark oddities — bookmarklets,
    `place:` smart folders, anchors without an href — are counted in
    stats['ignored'], never fatal; the same URL bookmarked in several
    folders collapses to one item (earliest ADD_DATE wins, tags
    unioned). Raises ImportSourceError only for document-level
    problems: missing file, or content without the format's DOCTYPE
    marker.
    """
    if not path.is_file():
        raise ImportSourceError(f"no bookmarks export at {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if _FORMAT_MARKER.lower() not in text.lower():
        raise ImportSourceError(
            f"{path} is not a NETSCAPE-Bookmark-file export; "
            "use your browser's bookmarks export (an HTML file)"
        )

    parser = _NetscapeParser()
    parser.feed(text)
    parser.close()

    imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ignored = {"not_http": 0, "no_url": 0}
    repeats = 0
    # item id -> (saved_at or None, item); same earliest-wins collapse
    # as the Takeout import, but tags union across occurrences
    earliest: dict[str, tuple[str | None, ScrollItem]] = {}
    tags_by_id: dict[str, list[str]] = {}
    order: list[str] = []
    for mark in parser.bookmarks:
        if not mark.href:
            ignored["no_url"] += 1
            continue
        url = normalize_url(mark.href)
        try:
            detected = detect_source(url)
        except ValueError:
            ignored["not_http"] += 1  # bookmarklets, place:, file:, ...
            continue
        saved_at = epoch_to_utc_iso(mark.add_date)
        item = ScrollItem(
            id=make_item_id(detected.source, detected.source_id, url),
            source=detected.source,
            source_id=detected.source_id,
            url=url,
            # the anchor text and <DD> note seed the item; fetch replaces
            # them with the source's own values (feed-sync semantics)
            title=mark.title,
            summary=mark.description,
            saved_at=saved_at or imported_at,
        )
        if item.id in earliest:
            repeats += 1
            known_at, _ = earliest[item.id]
            if saved_at and (known_at is None or saved_at < known_at):
                earliest[item.id] = (saved_at, item)
        else:
            earliest[item.id] = (saved_at, item)
            order.append(item.id)
        merged = tags_by_id.setdefault(item.id, [])
        merged.extend(tag for tag in mark.tags if tag not in merged)

    items = [
        replace(earliest[item_id][1], tags=tuple(tags_by_id[item_id]))
        for item_id in order
    ]
    stats = {
        "bookmarks": len(parser.bookmarks),
        "repeats": repeats,
        "ignored": ignored,
    }
    return items, stats


@dataclass
class _RawBookmark:
    href: str | None
    add_date: str | None
    title: str | None
    tags: tuple[str, ...]
    description: str | None = None


@dataclass
class _Folder:
    name: str | None  # None: root <DL> or nameless; "": a container


# Tags that delimit entries in the format; only these end an open <DD>
# note, so inline formatting inside a description doesn't truncate it.
_STRUCTURAL_TAGS = frozenset({"dt", "dd", "dl", "h3", "a"})


class _NetscapeParser(HTMLParser):
    """Token-stream reader for the Netscape bookmark format.

    <H3> text names the folder the *next* <DL> opens; </DL> closes it.
    <A> anchors become bookmarks tagged with their folder ancestry, and
    a following <DD> (which has no closing tag — it ends at the next
    structural tag) attaches to the bookmark just seen — unless an <H3>
    came between, which makes it a folder description, not a bookmark's.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.bookmarks: list[_RawBookmark] = []
        self._stack: list[_Folder] = []
        self._pending: _Folder | None = None
        self._text: list[str] | None = None  # active H3/A text collector
        self._anchor_attrs: dict[str, str | None] = {}
        self._anchor_is_open = False
        self._dd_text: list[str] | None = None
        self._dd_follows_anchor = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _STRUCTURAL_TAGS:  # formatting tags must not cut a <DD> note
            self._flush_dd()
        attributes = dict(attrs)
        if tag == "h3":
            self._pending = _Folder(name=None)
            if (attributes.get("personal_toolbar_folder") or "").lower() == "true":
                self._pending.name = ""  # container: a folder level, not a tag
            self._text = []
            self._dd_follows_anchor = False  # a following <DD> describes the folder
        elif tag == "dl":
            self._stack.append(self._pending or _Folder(name=None))
            self._pending = None
        elif tag == "a":
            self._anchor_attrs = attributes
            self._anchor_is_open = True
            self._text = []
        elif tag == "dd":
            self._dd_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in _STRUCTURAL_TAGS:
            self._flush_dd()
        if tag == "h3" and self._pending is not None:
            if self._pending.name is None:
                self._pending.name = self._collect_text()
            self._text = None
        elif tag == "dl" and self._stack:
            self._stack.pop()
        elif tag == "a" and self._anchor_is_open:
            self._finish_anchor()

    def handle_data(self, data: str) -> None:
        if self._dd_text is not None:
            self._dd_text.append(data)
        elif self._text is not None:
            self._text.append(data)

    def close(self) -> None:
        super().close()  # may emit buffered data into the collectors
        if self._anchor_is_open:  # truncated export: keep the dangling entry
            self._finish_anchor()
        self._flush_dd()

    def _collect_text(self) -> str:
        text = " ".join("".join(self._text or ()).split())
        return text

    def _finish_anchor(self) -> None:
        folder_tags = [
            folder.name for folder in self._stack
            if folder.name and folder.name.lower() not in _ROOT_CONTAINERS
        ]
        attr_tags = (self._anchor_attrs.get("tags") or "").split(",")
        tags = list(folder_tags)
        tags.extend(t for t in map(str.strip, attr_tags) if t and t not in tags)
        self.bookmarks.append(
            _RawBookmark(
                href=self._anchor_attrs.get("href"),
                add_date=self._anchor_attrs.get("add_date"),
                title=self._collect_text() or None,
                tags=tuple(tags),
            )
        )
        self._anchor_is_open = False
        self._anchor_attrs = {}
        self._text = None
        self._dd_follows_anchor = True

    def _flush_dd(self) -> None:
        if self._dd_text is None:
            return
        note = " ".join("".join(self._dd_text).split())
        self._dd_text = None
        if not self._dd_follows_anchor:
            return  # a folder's description, not a bookmark's
        if note and self.bookmarks and self.bookmarks[-1].description is None:
            self.bookmarks[-1].description = note
