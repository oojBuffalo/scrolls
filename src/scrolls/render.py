"""Markdown scroll rendering (IDEAS.md §2-3, §14 Pass 2).

A scroll is the durable, human- and agent-readable artifact: frontmatter
plus the extracted content, written to `scrolls/<source>/<slug>.md`.
Frontmatter lines are `key: <JSON value>` — JSON scalars, arrays, and
objects are valid YAML (YAML 1.2 is a JSON superset), so files stay
parseable by standard tooling with zero dependencies. SQLite remains the
index; scrolls can always be rebuilt from it (IDEAS.md §3).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import replace

from scrolls.items import ScrollItem
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
        sections += ["## Summary", item.summary]
    if item.extracted_text:
        sections += ["## Extracted Content", item.extracted_text]
    links = [f"- Source: {item.url}"]
    if item.canonical_url and item.canonical_url != item.url:
        links.append(f"- Canonical: {item.canonical_url}")
    sections += ["## Links", "\n".join(links)]

    return "\n".join(lines) + "\n\n" + "\n\n".join(sections) + "\n"


def write_scroll(paths: LibraryPaths, item: ScrollItem) -> ScrollItem:
    """Write the item's scroll file; return the item at stage 'rendered'.

    A stored `markdown_path` is reused so re-renders keep a stable path
    even when the title changes; otherwise the path is slugged from the
    title with an id-derived suffix on collision.
    """
    relpath = item.markdown_path or _new_relpath(paths, item)
    rendered = replace(item, markdown_path=relpath, stage="rendered")
    target = paths.root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_markdown(rendered), encoding="utf-8")
    return rendered


def _new_relpath(paths: LibraryPaths, item: ScrollItem) -> str:
    slug = _slug(item.title or "") or _slug(item.id) or "item"
    source_dir = paths.scrolls_dir / item.source
    candidate = source_dir / f"{slug}.md"
    if candidate.exists():  # another item owns this slug
        suffix = hashlib.sha256(item.id.encode("utf-8")).hexdigest()[:8]
        candidate = source_dir / f"{slug}-{suffix}.md"
    return str(candidate.relative_to(paths.root))


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return cleaned[:_MAX_SLUG_LENGTH].rstrip("-")
