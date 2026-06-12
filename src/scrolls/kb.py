"""Compiled library pages (IDEAS.md §9, §14 Pass 5; ADR 0005).

The KB compiler is deterministic: it rolls rendered scrolls up into an
index plus per-source, per-category, and per-concept pages under
`library/`, linking back to scroll files with relative Markdown links.
Pages are honest rollups of frontmatter the pipeline already produced —
no LLM synthesis (that is a future engine, like LLM classification).

The generated tree (`index.md`, `sources/`, `categories/`, `concepts/`)
is rebuilt from scratch on every run so stale pages can't linger;
anything else under `library/` is left alone. Compiling is a
library-level operation like the FTS index, so it never changes item
stages.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from scrolls.items import ScrollItem, list_items
from scrolls.paths import LibraryPaths
from scrolls.render import slugify

_GENERATED_DIRS = ("sources", "categories", "concepts")
_RECENT_LIMIT = 10


@dataclass(frozen=True)
class KbResult:
    items: int
    sources: int
    categories: int
    concepts: int
    pages: int


def compile_kb(paths: LibraryPaths) -> KbResult:
    """Rebuild the compiled library under `library/`; return group/page counts.

    Only items with a `markdown_path` appear — KB pages link to scroll
    files, and unrendered items have nothing to link to. A missing
    database means an uninitialized library: nothing is written.
    """
    if not paths.db_path.exists():
        return KbResult(0, 0, 0, 0, 0)
    items = [item for item in list_items(paths.db_path) if item.markdown_path]

    by_source: dict[str, list[ScrollItem]] = {}
    by_category: dict[str, list[ScrollItem]] = {}
    # concept spellings merge by slug; the smallest spelling is the display form
    by_concept: dict[str, dict] = {}
    for item in items:
        by_source.setdefault(item.source, []).append(item)
        if item.category:
            by_category.setdefault(item.category, []).append(item)
        for concept in dict.fromkeys(item.concepts):
            slug = slugify(concept)
            if not slug:
                continue
            entry = by_concept.setdefault(slug, {"display": concept, "items": []})
            entry["display"] = min(entry["display"], concept)
            entry["items"].append(item)

    _clear_generated(paths.library_dir)
    paths.library_dir.mkdir(parents=True, exist_ok=True)

    pages = 1  # the index
    for source, members in by_source.items():
        _write_page(
            paths, f"sources/{slugify(source) or 'untitled'}.md",
            f"Source: {source}", members, note=lambda i: i.category,
        )
        pages += 1
    for category, members in by_category.items():
        _write_page(
            paths, f"categories/{slugify(category) or 'untitled'}.md",
            f"Category: {category}", members, note=lambda i: i.source,
        )
        pages += 1
    for slug, entry in by_concept.items():
        _write_page(
            paths, f"concepts/{slug}.md",
            f"Concept: {entry['display']}", entry["items"], note=lambda i: i.source,
        )
        pages += 1
    _write_index(paths, items, by_source, by_category, by_concept)

    return KbResult(
        items=len(items),
        sources=len(by_source),
        categories=len(by_category),
        concepts=len(by_concept),
        pages=pages,
    )


def _write_index(paths, items, by_source, by_category, by_concept) -> None:
    lines = [
        "# Scrolls Library",
        "",
        f"{_count(len(items))} from {len(by_source)} source"
        f"{'' if len(by_source) == 1 else 's'}.",
    ]
    if by_source:
        lines += ["", "## Sources", ""]
        for source in sorted(by_source):
            slug = slugify(source) or "untitled"
            lines.append(
                f"- [{source}](sources/{slug}.md) — {_count(len(by_source[source]))}"
            )
    unclassified = sum(1 for item in items if not item.category)
    if by_category or unclassified:
        lines += ["", "## Categories", ""]
        for category in sorted(by_category):
            slug = slugify(category) or "untitled"
            lines.append(
                f"- [{category}](categories/{slug}.md) — {_count(len(by_category[category]))}"
            )
        if unclassified:
            lines.append(f"- unclassified — {_count(unclassified)}")
    if by_concept:
        lines += ["", "## Concepts", ""]
        for slug in sorted(by_concept):
            entry = by_concept[slug]
            lines.append(
                f"- [{entry['display']}](concepts/{slug}.md) — {_count(len(entry['items']))}"
            )
    if items:
        # list_items returns oldest first, so newest is the reversed head
        lines += ["", "## Recent", ""]
        for item in list(reversed(items))[:_RECENT_LIMIT]:
            lines.append(_item_line(item, page_dir="library"))
    (paths.library_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_page(paths: LibraryPaths, relpath: str, title: str,
                members: list[ScrollItem], note) -> None:
    page_dir = f"library/{relpath.rsplit('/', 1)[0]}"
    ordered = sorted(members, key=lambda i: ((i.title or i.id).casefold(), i.id))
    lines = [f"# {title}", "", f"{_count(len(members))}.", ""]
    lines += [_item_line(item, page_dir, note(item)) for item in ordered]
    target = paths.library_dir / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _item_line(item: ScrollItem, page_dir: str, note: str | None = None) -> str:
    link = os.path.relpath(item.markdown_path, start=page_dir)
    line = f"- [{item.title or item.id}]({link})"
    return f"{line} — {note}" if note else line


def _count(n: int) -> str:
    return f"{n} scroll{'' if n == 1 else 's'}"


def _clear_generated(library_dir: Path) -> None:
    index = library_dir / "index.md"
    if index.exists():
        index.unlink()
    for name in _GENERATED_DIRS:
        shutil.rmtree(library_dir / name, ignore_errors=True)
