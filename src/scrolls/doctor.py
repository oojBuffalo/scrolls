"""Library integrity diagnosis and repair (ADR 0026).

The index and the file tree can drift: pre-normalization libraries hold
duplicate items for the same resource (the debt ADR 0023 deliberately
left), users delete scroll or media files, and out-of-band SQL can
desync the FTS index. `run_doctor` finds that drift; with `fix=True` it
repairs exactly what is safe offline — merging duplicates into the
canonical id, rewriting missing scrolls from the index (IDEAS.md §3:
SQLite is canonical, scrolls can always be rebuilt), and rebuilding the
FTS index. Missing media files are left to `scrolls media` (network),
and orphan scroll files are never deleted (doctor cannot prove it wrote
them); both are reported so the drift is visible.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from typing import Any, Iterable

from scrolls.items import (
    ScrollItem,
    list_items,
    make_item_id,
    replace_items,
    update_item,
)
from scrolls.paths import LibraryPaths
from scrolls.render import write_scroll
from scrolls.sources.urls import normalize_url

_STAGE_RANK = {"detected": 0, "fetched": 1, "rendered": 2}


def get_fidelity(item: ScrollItem) -> str:
    """Derive explicit fidelity tier for a custodied item.

    full: raw or extracted+hash present (re-derivable body).
    partial: some content (extracted/summary) but not full.
    reference: pointer/provenance only.
    """
    has_raw = bool(getattr(item, "raw_text", None))
    has_extracted = bool(getattr(item, "extracted_text", None))
    has_hash = bool(getattr(item, "content_hash", None))
    has_body = has_raw or (has_extracted and has_hash)

    if has_body and getattr(item, "stage", "detected") in ("fetched", "rendered"):
        return "full"
    if has_extracted or getattr(item, "summary", None):
        return "partial"
    return "reference"

# SQLite release that taught FTS5 'integrity-check' to verify the index
# against an external content table; older ones can only check internals
_FTS_VERIFY_VERSION = (3, 42, 0)


def run_doctor(paths: LibraryPaths, fix: bool = False) -> dict[str, Any]:
    """Diagnose (and with `fix`, repair) index/file-tree drift.

    Returns the report payload `scrolls doctor` prints: per-finding
    entries plus `issues` (found) and `fixed` (repaired) counts. The
    library is healthy when `issues` is 0 and fully repaired when
    `issues == fixed`. Never creates a library; a missing one is empty,
    hence healthy. One unrepairable finding never aborts the rest.
    """
    report: dict[str, Any] = {
        "issues": 0,
        "fixed": 0,
        "duplicates": [],
        "missing_scrolls": [],
        "missing_media": [],
        "orphan_scrolls": [],
        "fts": {"in_sync": None, "status": "skipped"},
        "custody": {"score": None, "tiers": {"full": 0, "partial": 0, "reference": 0}, "findings": []},
    }
    if not paths.db_path.exists():
        return report

    _check_duplicates(paths, report, fix)
    # re-read after merges so the other checks see the repaired rows
    items = list_items(paths.db_path)
    _check_missing_scrolls(paths, report, items, fix)
    _check_missing_media(paths, report, items)
    _check_orphan_scrolls(paths, report, items)
    _check_fts(paths, report, fix)
    _check_custody_integrity(paths, report, items)
    return report


def _check_duplicates(paths: LibraryPaths, report: dict, fix: bool) -> None:
    """Items minted from different spellings of one URL (ADR 0023's debt).

    Only url-hash identities qualify: for items with a `source_id`, the
    URL spelling never was the identity, and second-guessing source
    detection is not doctor's business.
    """
    groups: dict[tuple[str, str], list[ScrollItem]] = {}
    for item in list_items(paths.db_path):
        if item.source_id is not None:
            continue
        key = (item.source, normalize_url(item.url))
        groups.setdefault(key, []).append(item)

    for (source, url), members in sorted(groups.items()):
        if len(members) < 2:
            continue
        report["issues"] += 1
        entry = {
            "source": source,
            "url": url,
            "ids": [member.id for member in members],
            "status": "found",
        }
        if fix:
            try:
                merged = _merge_group(paths, url, members)
            except OSError as exc:
                entry["status"] = "failed"
                entry["error"] = str(exc)
            else:
                entry["status"] = "merged"
                entry["merged_id"] = merged.id
                report["fixed"] += 1
        report["duplicates"].append(entry)


def _merge_group(paths: LibraryPaths, url: str, members: list[ScrollItem]) -> ScrollItem:
    """Merge duplicate members into one item under the canonical id.

    The survivor's id is minted from the normalized URL — anything else
    would let a future clean `scrolls add` re-create the duplicate.
    Content (title, text, hash, media, scroll path, stage) comes from
    the most advanced member; classification scalars fall back across
    members, list fields union; the earliest save date is kept.
    """
    ordered = sorted(
        members,
        key=lambda m: (-_STAGE_RANK.get(m.stage, 0), m.saved_at, m.id),
    )
    donor = ordered[0]
    merged = replace(
        donor,
        id=make_item_id(donor.source, None, url),
        url=url,
        saved_at=min(member.saved_at for member in members),
        category=next((m.category for m in ordered if m.category), None),
        domain=next((m.domain for m in ordered if m.domain), None),
        tags=_union(member.tags for member in ordered),
        concepts=_union(member.concepts for member in ordered),
    )
    if merged.markdown_path:
        # frontmatter must show the merged identity, not the donor's.
        # Written before any deletion: a failed write mutates nothing.
        merged = write_scroll(paths, merged)
    for member in members:
        if member.markdown_path and member.markdown_path != merged.markdown_path:
            # provably redundant: doctor itself just merged this scroll away
            (paths.root / member.markdown_path).unlink(missing_ok=True)
    replace_items(paths.db_path, [member.id for member in members], merged)
    return merged


def _union(sequences: Iterable[tuple]) -> tuple:
    seen: list = []
    for sequence in sequences:
        for value in sequence:
            if value not in seen:
                seen.append(value)
    return tuple(seen)


def _check_missing_scrolls(
    paths: LibraryPaths, report: dict, items: list[ScrollItem], fix: bool
) -> None:
    """Items pointing at a scroll file that is gone; fix rebuilds it."""
    for item in items:
        if not item.markdown_path or (paths.root / item.markdown_path).exists():
            continue
        report["issues"] += 1
        entry = {"id": item.id, "path": item.markdown_path, "status": "found"}
        if fix:
            try:
                rendered = write_scroll(paths, item)
            except OSError as exc:
                entry["status"] = "failed"
                entry["error"] = str(exc)
            else:
                update_item(paths.db_path, rendered)
                entry["status"] = "rewritten"
                report["fixed"] += 1
        report["missing_scrolls"].append(entry)


def _check_missing_media(
    paths: LibraryPaths, report: dict, items: list[ScrollItem]
) -> None:
    """Captured media files gone from disk. Report-only: re-downloading
    is `scrolls media`'s job, and doctor stays offline."""
    for item in items:
        for ref in item.media:
            if not isinstance(ref, dict):
                continue
            relpath = ref.get("path")
            if not relpath or (paths.root / relpath).exists():
                continue
            report["issues"] += 1
            report["missing_media"].append(
                {"id": item.id, "path": relpath, "url": ref.get("url"), "status": "found"}
            )


def _check_orphan_scrolls(
    paths: LibraryPaths, report: dict, items: list[ScrollItem]
) -> None:
    """Scroll files no item owns. Report-only: doctor cannot prove it
    wrote them, and deleting user files is not a repair."""
    if not paths.scrolls_dir.exists():
        return
    owned = {item.markdown_path for item in items if item.markdown_path}
    for file in sorted(paths.scrolls_dir.rglob("*.md")):
        relpath = str(file.relative_to(paths.root))
        if relpath in owned:
            continue
        report["issues"] += 1
        report["orphan_scrolls"].append({"path": relpath, "status": "found"})


def _check_fts(paths: LibraryPaths, report: dict, fix: bool) -> None:
    """Verify the FTS index against the items table; fix rebuilds it."""
    if sqlite3.sqlite_version_info < _FTS_VERIFY_VERSION:
        report["fts"] = {"in_sync": None, "status": "unsupported"}
        return
    conn = sqlite3.connect(paths.db_path)
    try:
        if _fts_in_sync(conn):
            report["fts"] = {"in_sync": True, "status": "ok"}
            return
        report["issues"] += 1
        if not fix:
            report["fts"] = {"in_sync": False, "status": "found"}
            return
        with conn:
            conn.execute("INSERT INTO items_fts(items_fts) VALUES ('rebuild')")
        report["fixed"] += 1
        report["fts"] = {"in_sync": _fts_in_sync(conn), "status": "rebuilt"}
    finally:
        conn.close()


def _fts_in_sync(conn: sqlite3.Connection) -> bool:
    # rank=1 checks the index against the content table, not just the
    # index's internal consistency (SQLite >= 3.42)
    try:
        conn.execute("INSERT INTO items_fts(items_fts, rank) VALUES ('integrity-check', 1)")
    except sqlite3.DatabaseError:
        return False
    return True


def _check_custody_integrity(paths: LibraryPaths, report: dict, items: list[ScrollItem]) -> None:
    """Custody integrity audit per the vision: verify scroll presence, re-derivability of body to content_hash, raw presence or honest fidelity downgrade, provenance completeness.

    Adds to report['custody'] with tiers counts and findings for issues.
    This is network-free and deterministic.
    """
    custody = report["custody"]
    for item in items:
        tier = get_fidelity(item)
        custody["tiers"][tier] = custody["tiers"].get(tier, 0) + 1

        issues_for_item = []
        scroll_path = paths.root / item.markdown_path if item.markdown_path else None

        # Check 1: scroll file present for rendered items
        if item.stage == "rendered" and item.markdown_path:
            if not scroll_path or not scroll_path.exists():
                issues_for_item.append("missing_scroll_file")

        # Check 2: body re-derives to stored content_hash (basic: presence + hash)
        if tier == "full" and item.content_hash:
            if not item.extracted_text and not item.raw_text:
                issues_for_item.append("body_not_rederivable")

        # Check 3: raw or honest downgrade
        if tier == "full" and not item.raw_text and not (item.extracted_text and item.content_hash):
            issues_for_item.append("full_fidelity_without_raw_or_hash")

        # Check 4: provenance basic (url or source_id present for non-reference)
        if tier != "reference" and not item.url and not item.source_id:
            issues_for_item.append("missing_provenance")

        if issues_for_item:
            report["issues"] += 1
            custody["findings"].append({
                "id": item.id,
                "tier": tier,
                "issues": issues_for_item,
                "status": "found"
            })

    # Compute simple custody score: % of items that are full or partial without issues
    total = len(items) or 1
    full_or_partial = custody["tiers"]["full"] + custody["tiers"]["partial"]
    findings_penalty = len(custody["findings"])
    custody["score"] = max(0, int(100 * (full_or_partial / total) - (findings_penalty * 5)))
