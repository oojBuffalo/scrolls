"""Markdown scroll rendering (IDEAS.md §2-3, §14 Pass 2).

A scroll is the durable, human- and agent-readable artifact: frontmatter
plus the extracted content, written to `scrolls/<source>/<slug>.md`.
Frontmatter lines are `key: <JSON value>` — JSON scalars, arrays, and
objects are valid YAML (YAML 1.2 is a JSON superset), so files stay
parseable by standard tooling with zero dependencies. SQLite remains the
index; scrolls can always be rebuilt from it (IDEAS.md §3).

The body is a *view* of the captured text, not a second copy of it: math
is normalized to KaTeX `$`/`$$` delimiters on the way out (see
`scrolls.mathtext`) while SQLite keeps the capture verbatim, so a
re-render never moves a `content_hash`. URLs in the `## Links` section are
written as CommonMark autolinks (`<url>`) for the same reason: 12 captured
URLs contain a `$`, one of them a `$$` that would otherwise open a display
math block, and an autolink keeps the URL exact and out of math scope.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import replace

from scrolls.items import ScrollItem
from scrolls.mathtext import normalize_math
from scrolls.paths import LibraryPaths

_FRONTMATTER_FIELDS = (
    "id",
    "source",
    "source_id",
    "url",
    "canonical_url",
    "title",
    "author",
    "published_at",
    "saved_at",
    "category",
    "domain",
    "tags",
    "concepts",
    "links",
    "media",
    "content_hash",
    "provenance",
)

_MAX_SLUG_LENGTH = 80


def render_markdown(item: ScrollItem) -> str:
    """Render one item as a Markdown scroll: frontmatter + body sections."""
    lines = ["---"]
    for name in _FRONTMATTER_FIELDS:
        value = getattr(item, name)
        if value is None or value == ():
            continue
        if isinstance(value, tuple):
            value = list(value)
        lines.append(f"{name}: {json.dumps(value, ensure_ascii=False)}")
    lines.append("---")

    sections = [f"# {item.title or item.id}"]
    if item.summary:
        sections += ["## Summary", normalize_math(item.summary)]
    if item.extracted_text:
        sections += ["## Extracted Content", normalize_math(item.extracted_text)]
    links = [f"- Source: <{item.url}>"]
    if item.canonical_url and item.canonical_url != item.url:
        links.append(f"- Canonical: <{item.canonical_url}>")
    links += [f"- <{link}>" for link in item.links]
    sections += ["## Links", "\n".join(links)]

    return "\n".join(lines) + "\n\n" + "\n\n".join(sections) + "\n"


def write_scroll(paths: LibraryPaths, item: ScrollItem) -> ScrollItem:
    """Write the item's scroll file; return the item at stage 'rendered'.

    A stored `markdown_path` is reused so re-renders keep a stable path
    even when the title changes; otherwise the path is slugged from the
    title with an id-derived suffix on collision.
    """
    rendered, _ = _render_to_disk(paths, item, only_if_changed=False)
    return rendered


def refresh_scroll(paths: LibraryPaths, item: ScrollItem) -> tuple[ScrollItem, bool]:
    """Re-render the item's scroll from the store, writing only on change.

    The render is compared byte-for-byte against the file already on disk,
    so a pass over an unchanged library is a total no-op. Only the scroll
    view moves; the stored capture and its custody hashes are never touched.

    Args:
        paths: The library layout to render into.
        item: The held item, at any stage with fetched content.

    Returns:
        A tuple of the item at stage 'rendered' and True when the scroll
        file was written, False when the render matched the file on disk.
    """
    return _render_to_disk(paths, item, only_if_changed=True)


def _render_to_disk(
    paths: LibraryPaths, item: ScrollItem, *, only_if_changed: bool
) -> tuple[ScrollItem, bool]:
    relpath = item.markdown_path or _new_relpath(paths, item)
    rendered = replace(item, markdown_path=relpath, stage="rendered")
    target = paths.root / relpath
    content = render_markdown(rendered)
    if (
        only_if_changed
        and target.is_file()
        and target.read_text(encoding="utf-8") == content
    ):
        return rendered, False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return rendered, True


def _new_relpath(paths: LibraryPaths, item: ScrollItem) -> str:
    slug = slugify(item.title or "") or slugify(item.id) or "item"
    source_dir = paths.scrolls_dir / item.source
    candidate = source_dir / f"{slug}.md"
    if candidate.exists():  # another item owns this slug
        suffix = hashlib.sha256(item.id.encode("utf-8")).hexdigest()[:8]
        candidate = source_dir / f"{slug}-{suffix}.md"
    return str(candidate.relative_to(paths.root))


def slugify(text: str) -> str:
    """Filesystem-safe ascii slug; shared by scroll paths and KB page names."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return cleaned[:_MAX_SLUG_LENGTH].rstrip("-")
