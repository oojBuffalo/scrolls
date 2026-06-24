"""Compiled library pages (IDEAS.md §9, §14 Pass 5; ADR 0005, ADR 0025).

The KB compiler is deterministic: it rolls rendered scrolls up into an
index plus per-source, per-category, per-concept, and per-tag pages under
`library/`, linking back to scroll files with relative Markdown links.
Pages are honest rollups of data the pipeline already produced — the
compiler itself never calls a model. Concept pages additionally lead
with a stored synthesized summary when the LLM concept engine
(`kb_llm.py`, ADR 0025) has written one; the store lives here so the
compiler reads it without importing the engine.

The generated tree (`index.md`, `graph.md`, `works.md`, `sources/`,
`categories/`, `concepts/`, `tags/`) is rebuilt on every run so stale pages
can't linger; anything else under `library/` is left alone. Each generated
page is written inside a sentinel fence (`scrolls.generated`, ADR 0102): a
re-compile replaces only the fenced region, so a hand annotation outside it
survives. A page whose group vanishes is removed — unless it carries such an
annotation, in which case it is kept with the generated region tombstoned.
Compiling is a library-level operation like the FTS index, so it never
changes item stages.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from scrolls.classify import stale_classification_counts_by_source
from scrolls.custody import (
    CustodyEvent,
    custody_counts_by_source,
    custody_headline,
    drift_posture,
    last_checked,
    latest_events,
    render_custody_attention,
    render_custody_by_source,
    render_custody_refresh,
)
from scrolls.generated import fence, has_user_content, user_regions, write_generated
from scrolls.graph import Component, Edge, connected_components, graph_over
from scrolls.items import (
    ScrollItem,
    content_duplicate_index,
    get_fidelity,
    list_items,
)
from scrolls.paths import LibraryPaths
from scrolls.render import slugify
from scrolls.works import (
    Work,
    render_at_risk_works,
    render_work_custody_marker,
    work_custody,
    works_over,
)

_GENERATED_DIRS = ("sources", "categories", "concepts", "tags")
_GENERATED_FILES = ("index.md", "graph.md", "works.md")
_REGENERATED_BY = "scrolls kb"
_RECENT_LIMIT = 10
_RELATED_CONCEPTS_LIMIT = 10
_RELATED_TAGS_LIMIT = 10
# Replaces the generated region of a page that has gone stale (its group is now
# empty) but carries a user annotation we must not drop (ADR 0102).
_STALE_BODY = (
    "_This page is no longer part of the compiled library — its group is now "
    "empty — but your annotation outside this block was kept. Move the note "
    "elsewhere if you want this page removed on the next recompile._"
)


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
    # one ledger read for the whole compile, shared by every list-page row's
    # custody marker (the bundle/context pattern, roadmap H89) — the per-row
    # posture and doctor's drift aggregate read the same `latest_events`
    verdicts = latest_events(paths.db_path)
    # one content-identity grouping fold for the whole compile (roadmap H333),
    # shared by every list-page row's "also held as" marker — the batch form of
    # the per-item `content_duplicate_ids`, so a recompile renders every row's
    # byte-identical siblings from a single pass (not the per-row O(n²) fold)
    dup_index = content_duplicate_index(items)

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
    items_by_id = {item.id: item for item in items}

    paths.library_dir.mkdir(parents=True, exist_ok=True)
    # Pages written this run; a prior page absent from this set is stale and
    # reconciled below (removed, or tombstoned if it carries a user annotation).
    written: set[Path] = set()

    pages = 1  # the index
    for source, members in by_source.items():
        _write_page(
            paths, written, f"sources/{slugify(source) or 'untitled'}.md",
            f"Source: {source}", members, note=lambda i: i.category, verdicts=verdicts,
            summaries=summaries, dup_index=dup_index,
        )
        pages += 1
    for category, members in by_category.items():
        # category pages collapse a work's near-duplicate representations into
        # one consolidated entry (ADR 0071) — the one page where a paper's
        # arxiv/crossref/pubmed manifestations co-occur, since they share a
        # category but not a source
        _write_page(
            paths, written, f"categories/{slugify(category) or 'untitled'}.md",
            f"Category: {category}", members, note=lambda i: i.source, verdicts=verdicts,
            summaries=summaries, dup_index=dup_index,
            consolidate_works=items_by_id,
        )
        pages += 1
    summarized = 0
    for slug, entry in by_concept.items():
        stored = summaries.get(slug)
        summarized += 1 if stored else 0
        _write_page(
            paths, written, f"concepts/{slug}.md",
            f"Concept: {entry['display']}", entry["items"], note=lambda i: i.source,
            verdicts=verdicts,
            summaries=summaries, dup_index=dup_index,
            lead=stored.summary if stored else None,
            trailer=_related_lines(
                "Related Concepts", related.get(slug, []), lambda key: key
            ),
        )
        pages += 1
    for key, entry in by_tag.items():
        _write_page(
            paths, written, f"tags/{tag_filenames[key]}.md",
            f"Tag: {entry['display']}", entry["items"], note=lambda i: i.source,
            verdicts=verdicts,
            summaries=summaries, dup_index=dup_index,
            trailer=_related_lines(
                "Related Tags", related_tag_map.get(key, []),
                lambda other: tag_filenames[other],
            ),
        )
        pages += 1
    _write_graph_page(paths, written, components, items_by_id)
    pages += 1
    _write_works_page(paths, written, works, items_by_id, verdicts)
    pages += 1
    _write_index(
        paths, written, items, by_source, by_category, by_concept, by_tag, tag_filenames,
        components, works, verdicts, summaries,
    )
    _reconcile_generated(paths.library_dir, written)

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


def _custody_scope_block(
    items: list[ScrollItem],
    verdicts: dict[str, CustodyEvent],
    summaries: dict[str, ConceptSummary],
    *,
    at_risk_lines: list[str] | None = None,
    archive_lines: list[str] | None = None,
    duplicate_lines: list[str] | None = None,
) -> list[str]:
    """The readable scope-custody block under a compiled page's headline (roadmap H184).

    The compiled-`library/`-page counterpart of the `export bundle`/`scrolls
    context` briefing custody block: the readable weakest-source `_Attention:_`
    pointer (H159), the per-source `_Refresh:_` pointer (H178), then the
    `_By source:_` breakdown (H145/H152) — over this page's own member scope,
    through the *same* shared `render_custody_attention`/`render_custody_refresh`/
    `render_custody_by_source` primitives, so the lines read byte-identical across
    surfaces and converge with the JSON `status`/`maintain` `attention` flag and
    `doctor`'s `custody.enrichment.by_source`/`summaries.by_source` debt maps by
    construction. Each renderer ends its present block with a trailing blank (or is
    `[]` on honest absence), so a caller splices the block straight in.

    `at_risk_lines` is the optional work-level `_At-risk work:_` pointer (roadmap
    H269), spliced directly beneath the source `_Attention:_` line so the two
    custody-loss pointers — per-source (H159) then per-work (H264) — group above the
    `_Refresh:_`/`_By source:_` map, exactly the `export bundle`/`context` briefing
    order. Only the whole-library `index.md` passes it (`render_at_risk_works` over
    the rendered library): the consolidation alarm is a non-source-attributable
    whole-library signal (`doctor`'s `custody.works` skips under `--source`), so a
    *scoped* group page would fragment works and could not converge with the
    library-wide audit. Defaults to `[]` (omitted on every group page).

    `archive_lines` is the optional whole-library `_Archive:_` integrity pointer
    (roadmap H321) — one line when any archived prior is corrupt (`prior_hash` no
    longer equals its snapshot's `content_hash`). It splices directly after the
    at-risk line, the `export bundle`/`context` order (Attention → At-risk →
    [Conflicts] → Archive; the compiled pages carry no `_Conflicts:_` line). Like the
    at-risk alarm it is whole-library and non-source-attributable — the recovery
    store is a single store, so a scoped group page is not its view — so only the
    whole-library `index.md` passes it (`render_archive_integrity(db, None)`, the same
    fold `doctor`'s `custody.archive` reads). Defaults to `[]` (omitted on every
    group page).

    `duplicate_lines` is the optional whole-library `_Duplicates:_` content-identity
    pointer (roadmap H334) — one line when ≥2 held items carry byte-identical content
    under different ids (the same bytes saved from two URLs, a mirror, a cross-post, or
    one work captured by two adapters, custody-vision §2.7). It splices directly after
    the archive line, continuing the `export bundle`/`context` order (Attention →
    At-risk → [Conflicts] → Archive → Duplicates). Whole-library and
    non-source-attributable — a content group spans sources, so a scoped group page
    fragments it below the 2-id floor — so only the whole-library `index.md` passes it
    (`render_content_duplicates(None, db)`, the same fold `doctor`'s
    `custody.content_duplicates` reads). Defaults to `[]` (omitted on every group page).

    The refresh debt is computed over this page's *own* members (the
    scope-consistent posture H178 took): a whole-library `index.md` over every
    rendered item, a group page over its members — so a single-source `sources/*`
    page (or a category narrowing a multi-source concept below `MIN_MEMBERS`)
    names exactly the debt its scope carries. `stale_summary_counts_by_source` is
    imported lazily to avoid the `kb` ⇄ `kb_llm` import cycle (`kb_llm` imports
    this module).
    """
    from scrolls.kb_llm import stale_summary_counts_by_source

    by_source = custody_counts_by_source(items, verdicts)
    return (
        render_custody_attention(by_source)
        + (at_risk_lines or [])
        + (archive_lines or [])
        + (duplicate_lines or [])
        + render_custody_refresh(
            stale_classification_counts_by_source(items),
            stale_summary_counts_by_source(items, summaries),
        )
        + render_custody_by_source(by_source)
    )


def _archive_integrity_lines(db_path: Path) -> list[str]:
    """The whole-library `_Archive:_` integrity line for the compiled landing page
    (roadmap H321), or `[]` on a clean/empty store.

    Delegates to the shared `maintain.render_archive_integrity` with a `None` scope —
    the *whole-library* recovery store (`archived_records(db)`), exactly the set
    `doctor`'s `custody.archive` folds — so the compiled `index.md` line, the
    `export bundle`/`context` briefing lines, the `maintain` summary, and the JSON
    audit cannot desync (one fold, one renderer). Imported lazily because `maintain`
    imports `compile_kb` from this module, so a module-level import would close a
    cycle (the `kb_llm` lazy-import precedent above)."""
    from scrolls.maintain import render_archive_integrity

    return render_archive_integrity(db_path, None)


def _content_duplicate_lines(db_path: Path) -> list[str]:
    """The whole-library `_Duplicates:_` content-identity line for the compiled landing
    page (roadmap H334), or `[]` on a clean/unique/empty library.

    Delegates to the shared `maintain.render_content_duplicates` with a `None` scope —
    the *whole-library* holdings (`list_items(db)`), exactly the set `doctor`'s
    `custody.content_duplicates` folds — so the compiled `index.md` line, the
    `export bundle`/`context` briefing lines, the `maintain` headline, and the JSON audit
    cannot desync (one fold, one renderer). Whole-library because a content group spans
    sources (the same bytes under two ids in different sources), so the alarm is
    non-source-attributable, like the `_Archive:_`/`_At-risk work:_` index lines — *not*
    in-scope. Imported lazily because `maintain` imports `compile_kb` from this module, so
    a module-level import would close a cycle (the `_archive_integrity_lines` precedent
    above)."""
    from scrolls.maintain import render_content_duplicates

    return render_content_duplicates(None, db_path)


def _write_index(
    paths, written, items, by_source, by_category, by_concept, by_tag, tag_filenames,
    components, works, verdicts: dict[str, CustodyEvent],
    summaries: dict[str, ConceptSummary],
) -> None:
    lines = [
        "# Scrolls Library",
        "",
        f"{_count(len(items))} from {len(by_source)} source"
        f"{'' if len(by_source) == 1 else 's'}.",
        _graph_index_line(components),
        _works_index_line(works),
        # the library-wide custody headline (roadmap H96) — the landing-page
        # counterpart of `scrolls status` (H38), over the same shared
        # `custody.custody_headline`. Scoped to the *compiled* library (the
        # rendered `items` this page heads, matching its own count line above),
        # so the headline's N never disagrees with the page it summarises; it
        # equals `status`/`doctor` when every held item is rendered.
        custody_headline(items, verdicts),
    ]
    # the readable scope-custody block under the headline (roadmap H184): the
    # weakest-source `_Attention:_` pointer (H159), the work-level `_At-risk work:_`
    # pointer (H269), the whole-library `_Archive:_` integrity pointer (H321), the
    # whole-library `_Duplicates:_` content-identity pointer (H334), the per-source
    # `_Refresh:_` pointer (H178), then the `_By source:_` breakdown (H145) — the
    # compiled landing-page counterpart of the `export bundle`/`context` briefings,
    # over the same shared renderers so the lines read byte-identical across surfaces
    # and converge with JSON `status` (H133) + `doctor`'s debt maps by construction.
    # The work-level at-risk line (H269) is the consolidation alarm on the static
    # compiled surface — the at-risk counterpart of the whole-library `_Custody:_`
    # headline (H96), folded by the shared `render_at_risk_works` over the rendered
    # library so it names the same work `doctor`'s `custody.works` does. The
    # `_Archive:_` line (H321) is the recovery-store counterpart — folded by the
    # shared `render_archive_integrity` over the *whole-library* store so it converges
    # with `doctor`'s `custody.archive`. The `_Duplicates:_` line (H334) is the
    # content-identity counterpart — folded by the shared `render_content_duplicates`
    # over the *whole-library* holdings so it converges with `doctor`'s
    # `custody.content_duplicates`. All three are non-source-attributable
    # whole-library alarms, so only the whole-library `index.md` carries them (group
    # pages would fragment works/content groups / are not the single recovery store's
    # view). An empty/single-source clean library with no at-risk work, a clean store,
    # and no byte-identical holdings is the honest no-op (the block is []). The block's
    # trailing spacer is dropped: `## Sources` always follows when items exist and
    # supplies the separator.
    custody_block = _custody_scope_block(
        items, verdicts, summaries,
        at_risk_lines=render_at_risk_works(items, verdicts),
        archive_lines=_archive_integrity_lines(paths.db_path),
        duplicate_lines=_content_duplicate_lines(paths.db_path),
    )
    if custody_block:
        lines += [""] + custody_block[:-1]
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
    _emit(paths.library_dir / "index.md", lines, written)


def _write_page(paths: LibraryPaths, written: set[Path], relpath: str, title: str,
                members: list[ScrollItem], note, verdicts: dict[str, CustodyEvent],
                summaries: dict[str, ConceptSummary],
                dup_index: dict[str, list[str]] | None = None,
                lead: str | None = None, trailer: list[str] | None = None,
                consolidate_works: dict[str, ScrollItem] | None = None) -> None:
    page_dir = f"library/{relpath.rsplit('/', 1)[0]}"
    lines = [f"# {title}", ""]
    if lead:  # synthesized concept summary (ADR 0025) leads the page
        lines += [lead, ""]
    lines += [f"{_count(len(members))}.", ""]
    # the scope-level custody headline for this page's members (roadmap H95) — the
    # human-readable counterpart of the bundle/context scope headlines (H45/H47),
    # over the same shared `custody.custody_headline` so the line is byte-identical
    # across surfaces and its tier/posture totals equal this page's per-row markers
    # by construction (every scroll has one fidelity tier and one drift posture)
    lines += [custody_headline(members, verdicts), ""]
    # the readable scope-custody block under the headline (roadmap H184): the
    # weakest-source `_Attention:_` pointer (H159), the per-source `_Refresh:_`
    # pointer (H178), then the `_By source:_` breakdown (H152) — over this page's
    # own members, the compiled counterpart of the `export bundle`/`context`
    # briefings and `index.md`, through the same shared renderers so the lines read
    # byte-identical and sum to the headline by construction. `_Attention:_` and
    # `_By source:_` are `<2`-source no-ops (omitted on every single-source page —
    # `sources/*.md` and any single-source category/tag); `_Refresh:_` has no
    # single-source gate, so a single-source page still names its refresh debt. The
    # block's trailing spacer separates it from the first item bullet (the
    # consolidated or singleton body follows).
    lines += _custody_scope_block(members, verdicts, summaries)
    dup_index = dup_index or {}
    if consolidate_works is not None:  # category pages collapse works (ADR 0071)
        lines += _consolidated_body(
            members, page_dir, note, consolidate_works, verdicts, dup_index)
    else:
        ordered = sorted(members, key=_entry_sort_key)
        lines += [
            _item_line(item, page_dir, note(item),
                       _row_markers(item, verdicts, dup_index))
            for item in ordered
        ]
    if trailer:  # e.g. a concept page's Related Concepts section (ADR 0063)
        lines += trailer
    _emit(paths.library_dir / relpath, lines, written)


def _emit(target: Path, lines: list[str], written: set[Path]) -> None:
    """Write one generated page inside its sentinel fence and record it.

    The page body (`lines`) replaces only the fenced region, so a user
    annotation outside the fence survives the recompile (ADR 0102). `written`
    accumulates every page produced this run so `_reconcile_generated` can tell
    a freshly written page from a stale one.
    """
    write_generated(target, "\n".join(lines), _REGENERATED_BY)
    written.add(target)


def _entry_sort_key(item) -> tuple[str, str]:
    """A group page's bullet order: case-folded title, item id as tiebreak.

    Takes anything carrying `.title`/`.id` — a `ScrollItem` for a singleton
    bullet, a work's canonical `Representation` for a consolidated entry.
    """
    return ((item.title or item.id).casefold(), item.id)


def _consolidated_body(
    members: list[ScrollItem], page_dir: str, note,
    items_by_id: dict[str, ScrollItem], verdicts: dict[str, CustodyEvent],
    dup_index: dict[str, list[str]] | None = None,
) -> list[str]:
    """A category page's body with same-work representations collapsed (ADR 0071).

    Items that are 2+ representations of one scholarly work *on this page*
    (`works_over`, ADR 0069) render as a single consolidated entry — a bold
    work heading carrying the DOI resolver link and a representation count,
    then each representation as a nested bullet linking to its scroll —
    instead of N near-duplicate top-level bullets. Items in no
    multi-representation work on this page render as ordinary bullets, exactly
    as the other group pages do. Works and singletons interleave in one
    case-folded title order; a work sorts by its *canonical* representation's
    title (`Work.canonical`, ADR 0095), so the published record's title heads it.
    """
    dup_index = dup_index or {}
    works = works_over(members)
    consolidated_ids = {rep.id for work in works for rep in work.representations}
    entries: list[tuple[tuple[str, str], list[str]]] = []
    for work in works:
        reps = [items_by_id[rep.id] for rep in work.representations]
        canonical = work.canonical
        block = [
            f"- **{canonical.title or canonical.id}** — "
            f"{_representation_count(len(reps))} "
            f"([doi.org/{work.doi}]({work.url}))"
        ]
        # representations already sorted by id (works_over), nested beneath
        block += [
            f"  {_item_line(item, page_dir, note(item), _row_markers(item, verdicts, dup_index))}"
            for item in reps
        ]
        entries.append((_entry_sort_key(canonical), block))
    for item in members:
        if item.id in consolidated_ids:
            continue
        entries.append((
            _entry_sort_key(item),
            [_item_line(item, page_dir, note(item),
                        _row_markers(item, verdicts, dup_index))],
        ))
    entries.sort(key=lambda entry: entry[0])
    return [line for _, block in entries for line in block]


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
    written: set[Path],
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
    _emit(paths.library_dir / "graph.md", lines, written)


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
    written: set[Path],
    works: list[Work],
    items_by_id: dict[str, ScrollItem],
    verdicts: dict[str, CustodyEvent],
) -> None:
    """Write `library/works.md`: scholarly works clustered by shared DOI.

    The browsable, human/agent-readable form of `scrolls works`'s JSON
    (ADR 0069, ADR 0070). Built over the rendered items only, so every
    representation links to a scroll file (a representation whose target is
    unrendered drops out, and a work that thereby keeps fewer than two
    representations isn't shown — the same rendered-only rule the graph page
    and the rest of the KB follow). Each work is a `## <doi>` section: the
    resolver link and a representation count, a work-level custody marker, then
    every representation as a bullet linking to its scroll — the *canonical* one
    (`Work.canonical`, ADR 0095) marked, so the form that stands for the work is
    visible at a glance. Always written, like the index; a library with no DOI
    held in two-plus representations says so, so the page is a stable entry point.

    The `_Custody:` marker beneath each resolver line (roadmap H270) is the
    work-level aggregate verdict — the `render_work_custody_marker` distillation of
    the shared `works.work_custody` fold (H261) over this work's representations and
    the `verdicts` ledger — so a human browsing the rollup reads which works are
    *safely held* vs. *at risk* without opening `scrolls works` JSON. It folds the
    *same* `work_custody` dict the JSON `custody` block carries, so the two converge
    by construction; an at-risk section's marker agrees with whether `index.md`'s
    `_At-risk work:_` line / `doctor`'s `custody.works` names that work (the H269
    compiled-surface convergence, now per-work). Inside the page's `@generated`
    sentinel fence (M1, ADR 0102) like the rest of the body, so a recompile refreshes
    it (a recapture flips it to *safely held*) while a hand annotation survives.
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
            marker = render_work_custody_marker(
                work_custody(work.representations, verdicts)
            )
            lines += [
                "", f"## {work.doi}", "",
                f"[doi.org/{work.doi}]({work.url}) — {count}.", marker, "",
            ]
            for rep in work.representations:  # already sorted by id
                item = items_by_id[rep.id]
                note = item.source
                if rep.id == work.canonical.id:
                    note = f"{note} · canonical"
                lines.append(_item_line(item, page_dir, note=note))
    _emit(paths.library_dir / "works.md", lines, written)


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


def _item_line(item: ScrollItem, page_dir: str, note: str | None = None,
               custody: str = "") -> str:
    link = os.path.relpath(item.markdown_path, start=page_dir)
    line = f"- [{item.title or item.id}]({link})"
    if note:
        line = f"{line} — {note}"
    return f"{line}{custody}"


def _custody_marker(item: ScrollItem, verdicts: dict[str, CustodyEvent]) -> str:
    """A compact `· <fidelity> · <drift> · <when>` per-row custody marker (H89/H93).

    The full per-item custody picture every agent-facing surface already carries,
    rendered for a human browsing the compiled `library/` list pages — the one
    surface the picture skipped. Three axes, from the one `latest_events` read
    `compile_kb` shares across the whole compile:

    - **fidelity** (`get_fidelity`, how much we still hold);
    - **drift** (`custody.drift_posture` over the item's latest verdict, whether
      the source has moved) — honestly ``unverified`` when never re-checked
      (`drift_posture(None)`), never silently "clean";
    - **when** (roadmap H93) — ``checked <checked_at>`` carrying the verbatim
      `custody.last_checked` of that same verdict (so *as of when* the posture was
      taken — a human can pick a `verify --stale-before <ISO>` boundary by
      inspection, the H84 rationale on the human-readable surface), or
      ``never checked`` for the honest-absence `last_checked(None) is None`.

    The timestamp is the stored value verbatim (not a wall-clock-relative "x
    ago"), matching the bundle briefing's `as of <checked_at>` (H42) and the
    `context` excerpt's `last seen <checked_at>` (H90) — so the three axes equal
    what every other surface reports for the item, and the marker's timestamp
    equals the head of its `scrolls history` ledger by construction (the H88 tie,
    on the compiled surface). Trails the row's existing note rather than replacing
    it. Report-only: a derived read, never a stored or mutated field (custody
    §2.4). Rendered inside the page's `@generated` fence (ADR 0102), so a recompile
    refreshes it (after a re-verify moves the posture *or* its timestamp) without
    touching a hand annotation outside the block.
    """
    verdict = verdicts.get(item.id)
    checked = last_checked(verdict)
    when = f"checked {checked}" if checked else "never checked"
    return f" · {get_fidelity(item)} · {drift_posture(verdict)} · {when}"


def _content_duplicate_marker(item: ScrollItem, dup_index: dict[str, list[str]]) -> str:
    """A compact `· also held as `<id>`, `<id>`` per-row content-identity marker (H333).

    The Markdown surface of H328's JSON `content_duplicate_ids`: when the library
    holds **byte-identical content under another id** (the same non-null
    `content_hash` — a mirror, a cross-post, one work captured twice), this names
    the *other* held ids on the rendered row, so a human browsing the compiled
    `library/` list pages sees a scroll's redundancy without scanning `doctor`'s
    whole-library `custody.content_duplicates` report. The per-item read names
    **siblings, never a count** (the per-item-vs-whole-library split, H328); a
    unique or NULL-hash item carries **no** clause (the honest omit, the empty
    `content_duplicate_ids`).

    Reads the shared `content_duplicate_index` `dup_index` folded once for the whole
    compile (so the marker is the batch form of `content_duplicate_ids` and cannot
    drift from the per-item `show`/`get_scroll` read, H332). The sibling ids are
    backticked (they carry `:` separators) and whole-library scoped — a content
    group spans sources, so a cross-source sibling **is** named (the H328
    cross-source-sibling rule), even on a single-source page. Trails the custody
    marker on the same row; rendered inside the page's `@generated` fence (ADR
    0102), so a recompile refreshes it (a newly-held copy appears, a pruned one
    drops) without touching a hand annotation outside the block (the H89/H93
    refresh-safe discipline on the content-identity axis).
    """
    siblings = dup_index.get(item.id)
    if not siblings:
        return ""
    return " · also held as " + ", ".join(f"`{sid}`" for sid in siblings)


def _row_markers(item: ScrollItem, verdicts: dict[str, CustodyEvent],
                 dup_index: dict[str, list[str]]) -> str:
    """The full trailing per-row marker string: custody picture then content-identity.

    Concatenates the H89/H93 `· fidelity · drift · when` custody marker with the
    H333 `· also held as …` content-duplicate clause (empty when the item holds no
    byte-identical sibling), so the two derived per-item custody axes ride one row.
    """
    return _custody_marker(item, verdicts) + _content_duplicate_marker(item, dup_index)


def _count(n: int) -> str:
    return f"{n} scroll{'' if n == 1 else 's'}"


def _reconcile_generated(library_dir: Path, written: set[Path]) -> None:
    """Clear stale generated pages a recompile left behind, sparing annotations.

    A generated file from a prior run that this run did not rewrite (its group
    vanished — a reclassified category, a dropped concept) is removed, keeping
    the "stale pages can't linger" guarantee. The exception is a page that
    carries a user annotation outside its sentinel fence: that file is kept, its
    generated region replaced by a tombstone, so the annotation is never
    silently dropped (ADR 0102). Always-written pages (`index.md`, `graph.md`,
    `works.md`) are in `written`, so they are never reconciled here.
    """
    candidates: list[Path] = [library_dir / name for name in _GENERATED_FILES]
    for name in _GENERATED_DIRS:
        directory = library_dir / name
        if directory.is_dir():
            candidates += sorted(p for p in directory.iterdir() if p.is_file())
    for path in candidates:
        if path in written or not path.exists():
            continue
        existing = path.read_text(encoding="utf-8")
        if has_user_content(existing):
            prefix, suffix = user_regions(existing)
            path.write_text(
                prefix + fence(_STALE_BODY, _REGENERATED_BY) + suffix,
                encoding="utf-8",
            )
        else:
            path.unlink()
    for name in _GENERATED_DIRS:
        directory = library_dir / name
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


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
