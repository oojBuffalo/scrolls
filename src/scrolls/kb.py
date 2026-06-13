"""Compiled library pages (IDEAS.md §9, §14 Pass 5; ADR 0005, ADR 0025).

The KB compiler is deterministic: it rolls rendered scrolls up into an
index plus per-source, per-category, and per-concept pages under
`library/`, linking back to scroll files with relative Markdown links.
Pages are honest rollups of data the pipeline already produced — the
compiler itself never calls a model. Concept pages additionally lead
with a stored synthesized summary when the LLM concept engine
(`kb_llm.py`, ADR 0025) has written one; the store lives here so the
compiler reads it without importing the engine.

The generated tree (`index.md`, `sources/`, `categories/`, `concepts/`)
is rebuilt from scratch on every run so stale pages can't linger;
anything else under `library/` is left alone. Compiling is a
library-level operation like the FTS index, so it never changes item
stages.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from scrolls.graph import Component, Edge, connected_components, graph_over
from scrolls.items import ScrollItem, list_items
from scrolls.paths import LibraryPaths
from scrolls.render import slugify

_GENERATED_DIRS = ("sources", "categories", "concepts")
_GENERATED_FILES = ("index.md", "graph.md")
_RECENT_LIMIT = 10


@dataclass(frozen=True)
class KbResult:
    items: int
    sources: int
    categories: int
    concepts: int
    summaries: int
    clusters: int
    pages: int


@dataclass(frozen=True)
class ConceptSummary:
    """One stored synthesized concept-page summary (ADR 0025)."""

    slug: str
    display: str
    summary: str
    members_hash: str
    engine: str
    model: str
    generated_at: str


def group_concepts(items: list[ScrollItem]) -> dict[str, dict]:
    """Concept slug → {"display", "items"} over the given rendered items.

    Spellings merge by slug; the smallest spelling is the display form.
    Shared by the compiler and the LLM concept engine so both see the
    same groups.
    """
    by_concept: dict[str, dict] = {}
    for item in items:
        for concept in dict.fromkeys(item.concepts):
            slug = slugify(concept)
            if not slug:
                continue
            entry = by_concept.setdefault(slug, {"display": concept, "items": []})
            entry["display"] = min(entry["display"], concept)
            entry["items"].append(item)
    return by_concept


def compile_kb(paths: LibraryPaths) -> KbResult:
    """Rebuild the compiled library under `library/`; return group/page counts.

    Only items with a `markdown_path` appear — KB pages link to scroll
    files, and unrendered items have nothing to link to. A missing
    database means an uninitialized library: nothing is written.
    """
    if not paths.db_path.exists():
        return KbResult(0, 0, 0, 0, 0, 0, 0)
    items = [item for item in list_items(paths.db_path) if item.markdown_path]

    by_source: dict[str, list[ScrollItem]] = {}
    by_category: dict[str, list[ScrollItem]] = {}
    for item in items:
        by_source.setdefault(item.source, []).append(item)
        if item.category:
            by_category.setdefault(item.category, []).append(item)
    by_concept = group_concepts(items)
    summaries = load_concept_summaries(paths.db_path)
    # the link graph over the rendered items only, so every edge it shows
    # resolves to a scroll file the page can link (graph_over drops links to
    # unrendered targets, just as the rest of the KB ignores unrendered items)
    components = connected_components(graph_over(items))

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
    summarized = 0
    for slug, entry in by_concept.items():
        stored = summaries.get(slug)
        summarized += 1 if stored else 0
        _write_page(
            paths, f"concepts/{slug}.md",
            f"Concept: {entry['display']}", entry["items"], note=lambda i: i.source,
            lead=stored.summary if stored else None,
        )
        pages += 1
    _write_graph_page(paths, components, {item.id: item for item in items})
    pages += 1
    _write_index(paths, items, by_source, by_category, by_concept, components)

    return KbResult(
        items=len(items),
        sources=len(by_source),
        categories=len(by_category),
        concepts=len(by_concept),
        summaries=summarized,
        clusters=len(components),
        pages=pages,
    )


def _write_index(paths, items, by_source, by_category, by_concept, components) -> None:
    lines = [
        "# Scrolls Library",
        "",
        f"{_count(len(items))} from {len(by_source)} source"
        f"{'' if len(by_source) == 1 else 's'}.",
        _graph_index_line(components),
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
                members: list[ScrollItem], note, lead: str | None = None) -> None:
    page_dir = f"library/{relpath.rsplit('/', 1)[0]}"
    ordered = sorted(members, key=lambda i: ((i.title or i.id).casefold(), i.id))
    lines = [f"# {title}", ""]
    if lead:  # synthesized concept summary (ADR 0025) leads the page
        lines += [lead, ""]
    lines += [f"{_count(len(members))}.", ""]
    lines += [_item_line(item, page_dir, note(item)) for item in ordered]
    target = paths.library_dir / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_graph_page(
    paths: LibraryPaths,
    components: tuple[Component, ...],
    items_by_id: dict[str, ScrollItem],
) -> None:
    """Write `library/graph.md`: the link graph as connected-item clusters.

    The browsable, human/agent-readable form of `scrolls graph`'s JSON
    (ADR 0044, ADR 0062). Built over the rendered items only, so every link
    resolves to a scroll file. Items that reach one another through links are
    grouped into clusters, largest first, and each cluster is rendered as an
    adjacency list: every member as a bullet linking to its scroll, with its
    outbound edges nested beneath as `→ target`. Always written, like the
    index; an empty graph (no links between rendered scrolls) says so, so the
    page is a stable entry point.
    """
    page_dir = "library"
    lines = ["# Scrolls Link Graph", ""]
    if not components:
        lines.append("No linked scrolls yet.")
    else:
        connected = sum(len(component.nodes) for component in components)
        lines.append(
            f"{_count(connected)} connected across "
            f"{_cluster_count(len(components))}."
        )
        for number, component in enumerate(components, start=1):
            lines += ["", f"## Cluster {number}", "", f"{_count(len(component.nodes))}.", ""]
            out_edges: dict[str, list[Edge]] = {}
            for edge in component.edges:
                out_edges.setdefault(edge.from_id, []).append(edge)
            for node in component.nodes:  # already sorted by id
                item = items_by_id[node.id]
                lines.append(_item_line(item, page_dir, note=item.source))
                for edge in out_edges.get(node.id, ()):
                    target = items_by_id[edge.to_id]
                    link = os.path.relpath(target.markdown_path, start=page_dir)
                    lines.append(f"  - → [{target.title or target.id}]({link})")
    (paths.library_dir / "graph.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _graph_index_line(components: tuple[Component, ...]) -> str:
    """The one-line link to `graph.md` the index carries under its count line."""
    if not components:
        return "[Link graph](graph.md) — no linked scrolls yet."
    connected = sum(len(component.nodes) for component in components)
    return (
        f"[Link graph](graph.md) — {_count(connected)} connected across "
        f"{_cluster_count(len(components))}."
    )


def _cluster_count(n: int) -> str:
    return f"{n} cluster{'' if n == 1 else 's'}"


def _item_line(item: ScrollItem, page_dir: str, note: str | None = None) -> str:
    link = os.path.relpath(item.markdown_path, start=page_dir)
    line = f"- [{item.title or item.id}]({link})"
    return f"{line} — {note}" if note else line


def _count(n: int) -> str:
    return f"{n} scroll{'' if n == 1 else 's'}"


def _clear_generated(library_dir: Path) -> None:
    for name in _GENERATED_FILES:
        path = library_dir / name
        if path.exists():
            path.unlink()
    for name in _GENERATED_DIRS:
        shutil.rmtree(library_dir / name, ignore_errors=True)


# --- The concept-summary store (ADR 0025) ---------------------------------
#
# The LLM concept engine (kb_llm.py) writes rows; the compiler above only
# reads them. Keeping the store on the compiler's side of the boundary
# means kb_llm imports kb, never the reverse, and a plain `scrolls kb`
# needs no model, key, or network.

_SUMMARY_FIELDS = (
    "slug", "display", "summary", "members_hash", "engine", "model", "generated_at"
)


def load_concept_summaries(db_path: Path) -> dict[str, ConceptSummary]:
    """All stored summaries by slug; {} when none (or the db predates them)."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_SUMMARY_FIELDS)} FROM concept_summaries"
        ).fetchall()
    except sqlite3.OperationalError:  # pre-v6 database opened read-only by kb
        return {}
    finally:
        conn.close()
    summaries = (ConceptSummary(*row) for row in rows)
    return {summary.slug: summary for summary in summaries}


def save_concept_summary(db_path: Path, summary: ConceptSummary) -> None:
    """Insert or replace one stored summary."""
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                f"INSERT OR REPLACE INTO concept_summaries "
                f"({', '.join(_SUMMARY_FIELDS)}) VALUES ({', '.join('?' * len(_SUMMARY_FIELDS))})",
                tuple(getattr(summary, field) for field in _SUMMARY_FIELDS),
            )
    finally:
        conn.close()


def delete_concept_summaries(db_path: Path, slugs: list[str]) -> None:
    """Drop stored summaries for concepts that no longer qualify."""
    if not slugs:
        return
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.executemany(
                "DELETE FROM concept_summaries WHERE slug = ?",
                [(slug,) for slug in slugs],
            )
    finally:
        conn.close()
