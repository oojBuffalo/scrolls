"""Compiled library pages (IDEAS.md §9, §14 Pass 5; ADR 0005, ADR 0025).

The KB compiler is deterministic: it rolls rendered scrolls up into an
index plus per-source, per-category, per-concept, and per-tag pages under
`library/`, linking back to scroll files with relative Markdown links.
Pages are honest rollups of data the pipeline already produced — the
compiler itself never calls a model. Concept pages additionally lead
with a stored synthesized summary when the LLM concept engine
(`kb_llm.py`, ADR 0025) has written one; the store lives here so the
compiler reads it without importing the engine.

The generated tree (`index.md`, `graph.md`, `sources/`, `categories/`,
`concepts/`, `tags/`) is rebuilt from scratch on every run so stale pages
can't linger; anything else under `library/` is left alone. Compiling is a
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
from scrolls.works import Work, works_over

_GENERATED_DIRS = ("sources", "categories", "concepts", "tags")
_GENERATED_FILES = ("index.md", "graph.md", "works.md")
_RECENT_LIMIT = 10
_RELATED_CONCEPTS_LIMIT = 10
_RELATED_TAGS_LIMIT = 10


@dataclass(frozen=True)
class KbResult:
    items: int
    sources: int
    categories: int
    concepts: int
    tags: int
    summaries: int
    clusters: int
    works: int
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


def group_tags(items: list[ScrollItem]) -> dict[str, dict]:
    """Tag case-fold key → {"display", "items"} over the given rendered items.

    Tags merge **case-insensitively** — the `--tag` membership facet's rule
    (ADR 0059), not concepts' coarser slug merge — so `MIT` and `mit` are one
    group while `C++` and `C#` stay distinct (they share a slug but not a fold).
    The smallest spelling is the display form, as with concepts.
    """
    by_tag: dict[str, dict] = {}
    for item in items:
        for tag in dict.fromkeys(item.tags):
            key = tag.lower()
            if not key:
                continue
            entry = by_tag.setdefault(key, {"display": tag, "items": []})
            entry["display"] = min(entry["display"], tag)
            entry["items"].append(item)
    return by_tag


def _co_occurring(
    by_group: dict[str, dict], limit: int
) -> dict[str, list[tuple[str, str, int]]]:
    """For each group key, the other groups that co-occur on its member scrolls.

    Two groups are *related* when at least one rendered scroll belongs to both;
    the strength is how many scrolls belong to both. Returns, per key, a list of
    `(other_key, other_display, shared_count)` ordered by shared count
    descending, then the other group's display (case-folded), then its key,
    capped at `limit`. A group whose members share no scroll with another maps
    to an empty list. Shared by the concept and tag co-occurrence maps.
    """
    members = {
        key: {item.id for item in entry["items"]} for key, entry in by_group.items()
    }
    related: dict[str, list[tuple[str, str, int]]] = {}
    for key, ids in members.items():
        scored = [
            (other, by_group[other]["display"], len(ids & other_ids))
            for other, other_ids in members.items()
            if other != key and (ids & other_ids)
        ]
        scored.sort(key=lambda row: (-row[2], row[1].casefold(), row[0]))
        related[key] = scored[:limit]
    return related


def related_concepts(
    by_concept: dict[str, dict], limit: int = _RELATED_CONCEPTS_LIMIT
) -> dict[str, list[tuple[str, str, int]]]:
    """For each concept slug, the concepts that co-occur on its member scrolls.

    The deterministic concept-graph complement to the link graph (`graph.py`):
    IDEAS.md §9's "Related Concepts". Computed here, on the concept pages,
    rather than as edges in `scrolls graph`, because concept co-occurrence forms
    dense cliques — every pair of concepts on one scroll is an edge — that would
    swamp the sparse, high-signal *link* edges the adapters build (ADR 0044/0047
    deferred concept edges in the link graph for exactly this reason).
    """
    return _co_occurring(by_concept, limit)


def related_tags(
    by_tag: dict[str, dict], limit: int = _RELATED_TAGS_LIMIT
) -> dict[str, list[tuple[str, str, int]]]:
    """For each tag, the tags that co-occur on its member scrolls (ADR 0064).

    The tag-facet analog of `related_concepts`: a co-occurrence list living on
    each tag page rather than as link-graph edges, for the same density reason.
    """
    return _co_occurring(by_tag, limit)


def compile_kb(paths: LibraryPaths) -> KbResult:
    """Rebuild the compiled library under `library/`; return group/page counts.

    Only items with a `markdown_path` appear — KB pages link to scroll
    files, and unrendered items have nothing to link to. A missing
    database means an uninitialized library: nothing is written.
    """
    if not paths.db_path.exists():
        return KbResult(0, 0, 0, 0, 0, 0, 0, 0, 0)
    items = [item for item in list_items(paths.db_path) if item.markdown_path]

    by_source: dict[str, list[ScrollItem]] = {}
    by_category: dict[str, list[ScrollItem]] = {}
    for item in items:
        by_source.setdefault(item.source, []).append(item)
        if item.category:
            by_category.setdefault(item.category, []).append(item)
    by_concept = group_concepts(items)
    related = related_concepts(by_concept)
    by_tag = group_tags(items)
    related_tag_map = related_tags(by_tag)
    tag_filenames = _tag_filenames(by_tag)
    summaries = load_concept_summaries(paths.db_path)
    # the link graph over the rendered items only, so every edge it shows
    # resolves to a scroll file the page can link (graph_over drops links to
    # unrendered targets, just as the rest of the KB ignores unrendered items)
    components = connected_components(graph_over(items))
    # scholarly works clustered by shared DOI (ADR 0069), over the same
    # rendered items so every representation links to a scroll file
    works = works_over(items)

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
            trailer=_related_lines(
                "Related Concepts", related.get(slug, []), lambda key: key
            ),
        )
        pages += 1
    for key, entry in by_tag.items():
        _write_page(
            paths, f"tags/{tag_filenames[key]}.md",
            f"Tag: {entry['display']}", entry["items"], note=lambda i: i.source,
            trailer=_related_lines(
                "Related Tags", related_tag_map.get(key, []),
                lambda other: tag_filenames[other],
            ),
        )
        pages += 1
    items_by_id = {item.id: item for item in items}
    _write_graph_page(paths, components, items_by_id)
    pages += 1
    _write_works_page(paths, works, items_by_id)
    pages += 1
    _write_index(
        paths, items, by_source, by_category, by_concept, by_tag, tag_filenames,
        components, works,
    )

    return KbResult(
        items=len(items),
        sources=len(by_source),
        categories=len(by_category),
        concepts=len(by_concept),
        tags=len(by_tag),
        summaries=summarized,
        clusters=len(components),
        works=len(works),
        pages=pages,
    )


def _write_index(
    paths, items, by_source, by_category, by_concept, by_tag, tag_filenames,
    components, works,
) -> None:
    lines = [
        "# Scrolls Library",
        "",
        f"{_count(len(items))} from {len(by_source)} source"
        f"{'' if len(by_source) == 1 else 's'}.",
        _graph_index_line(components),
        _works_index_line(works),
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
    if by_tag:
        lines += ["", "## Tags", ""]
        for key in sorted(by_tag):
            entry = by_tag[key]
            lines.append(
                f"- [{entry['display']}](tags/{tag_filenames[key]}.md) — {_count(len(entry['items']))}"
            )
    if items:
        # list_items returns oldest first, so newest is the reversed head
        lines += ["", "## Recent", ""]
        for item in list(reversed(items))[:_RECENT_LIMIT]:
            lines.append(_item_line(item, page_dir="library"))
    (paths.library_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_page(paths: LibraryPaths, relpath: str, title: str,
                members: list[ScrollItem], note, lead: str | None = None,
                trailer: list[str] | None = None) -> None:
    page_dir = f"library/{relpath.rsplit('/', 1)[0]}"
    ordered = sorted(members, key=lambda i: ((i.title or i.id).casefold(), i.id))
    lines = [f"# {title}", ""]
    if lead:  # synthesized concept summary (ADR 0025) leads the page
        lines += [lead, ""]
    lines += [f"{_count(len(members))}.", ""]
    lines += [_item_line(item, page_dir, note(item)) for item in ordered]
    if trailer:  # e.g. a concept page's Related Concepts section (ADR 0063)
        lines += trailer
    target = paths.library_dir / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _related_lines(heading: str, related: list[tuple[str, str, int]], name_for) -> list[str]:
    """A `## <heading>` co-occurrence trailer (Related Concepts/Tags), or [] when none.

    Each line links a co-occurring group's sibling page in the same directory
    (so the link is the bare `<name>.md`, resolved by `name_for(key)`) and notes
    how many scrolls belong to both. Shared by concept pages (ADR 0063) and tag
    pages (ADR 0064); for concepts the key *is* the page name, for tags
    `name_for` maps the case-fold key through the collision-free filename map.
    """
    if not related:
        return []
    lines = ["", f"## {heading}", ""]
    for key, display, shared in related:
        scrolls = f"{shared} shared scroll{'' if shared == 1 else 's'}"
        lines.append(f"- [{display}]({name_for(key)}.md) — {scrolls}")
    return lines


def _tag_filenames(by_tag: dict[str, dict]) -> dict[str, str]:
    """Collision-free `tags/<name>.md` stems, one per tag group (ADR 0064).

    Tags group by case-fold (`group_tags`), so distinct groups can share a slug
    (`C++`, `C#`, and `C` all slugify to `c`) where concepts — grouped *by* slug
    — never do. KB pages are rebuilt from scratch each run and link relatively,
    so colliding slugs get a deterministic numeric suffix in sorted-key order
    rather than a globally stable name.
    """
    used: dict[str, int] = {}
    names: dict[str, str] = {}
    for key in sorted(by_tag):
        base = slugify(key) or "untitled"
        count = used.get(base, 0) + 1
        used[base] = count
        names[key] = base if count == 1 else f"{base}-{count}"
    return names


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


def _write_works_page(
    paths: LibraryPaths,
    works: list[Work],
    items_by_id: dict[str, ScrollItem],
) -> None:
    """Write `library/works.md`: scholarly works clustered by shared DOI.

    The browsable, human/agent-readable form of `scrolls works`'s JSON
    (ADR 0069, ADR 0070). Built over the rendered items only, so every
    representation links to a scroll file (a representation whose target is
    unrendered drops out, and a work that thereby keeps fewer than two
    representations isn't shown — the same rendered-only rule the graph page
    and the rest of the KB follow). Each work is a `## <doi>` section: the
    resolver link and a representation count, then every representation as a
    bullet linking to its scroll. Always written, like the index; a library
    with no DOI held in two-plus representations says so, so the page is a
    stable entry point.
    """
    page_dir = "library"
    lines = ["# Scrolls Works", ""]
    if not works:
        lines.append("No works held in multiple representations yet.")
    else:
        reps = sum(len(work.representations) for work in works)
        lines.append(
            f"{_work_count(len(works))} held as {_representation_count(reps)}."
        )
        for work in works:
            count = _representation_count(len(work.representations))
            lines += [
                "", f"## {work.doi}", "",
                f"[doi.org/{work.doi}]({work.url}) — {count}.", "",
            ]
            for rep in work.representations:  # already sorted by id
                item = items_by_id[rep.id]
                lines.append(_item_line(item, page_dir, note=item.source))
    (paths.library_dir / "works.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _works_index_line(works: list[Work]) -> str:
    """The one-line link to `works.md` the index carries under the graph line."""
    if not works:
        return "[Works](works.md) — no works held in multiple representations yet."
    reps = sum(len(work.representations) for work in works)
    return (
        f"[Works](works.md) — {_work_count(len(works))} "
        f"held as {_representation_count(reps)}."
    )


def _work_count(n: int) -> str:
    return f"{n} work{'' if n == 1 else 's'}"


def _representation_count(n: int) -> str:
    return f"{n} representation{'' if n == 1 else 's'}"


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
