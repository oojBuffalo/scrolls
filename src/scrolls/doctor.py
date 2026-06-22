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

from scrolls.classify import (
    RULESET_FINGERPRINT,
    classification_freshness,
    stale_classification_counts_by_source,
)
from scrolls.custody import (
    CUSTODY_STATUSES,
    custody_counts_by_source,
    latest_conflict_events,
    latest_events,
    recheck_coverage,
    unresolved_conflicts,
    unverified_items,
)
from scrolls.kb import load_concept_summaries
from scrolls.kb_llm import (
    eligible_concepts,
    members_hash,
    stale_summary_counts_by_source,
    summary_freshness,
)
from scrolls.items import (
    ScrollItem,
    get_fidelity,
    list_items,
    make_item_id,
    replace_items,
    update_item,
)
from scrolls.paths import LibraryPaths
from scrolls.render import write_scroll
from scrolls.sources.urls import normalize_url
from scrolls.works import at_risk_signal, works_over

_STAGE_RANK = {"detected": 0, "fetched": 1, "rendered": 2}


# `get_fidelity` lives in items.py (the custody tier is an item-model
# property); imported above so `doctor.get_fidelity` and the custody audit
# below share the one definition with `facets` and `list`.

# SQLite release that taught FTS5 'integrity-check' to verify the index
# against an external content table; older ones can only check internals
_FTS_VERIFY_VERSION = (3, 42, 0)


def run_doctor(
    paths: LibraryPaths, fix: bool = False, source: str | None = None
) -> dict[str, Any]:
    """Diagnose (and with `fix`, repair) index/file-tree drift.

    Returns the report payload `scrolls doctor` prints: per-finding
    entries plus `issues` (found) and `fixed` (repaired) counts. The
    library is healthy when `issues` is 0 and fully repaired when
    `issues == fixed`. Never creates a library; a missing one is empty,
    hence healthy. One unrepairable finding never aborts the rest.

    `source` scopes the *whole* audit to one source's held items — the
    audit-side counterpart of the per-source act commands `verify --source`
    (roadmap H125) / `classify --stale --source` (H154), and the way a worker
    triaging "source <S> is weakest" (named by the per-source `by_source` map,
    H104, or the weakest-source `attention` flag, H119/H139) reads <S>'s *full*
    custody picture — drift, enrichment, coverage, score, and the offending-id
    lists — instead of slicing them out of the whole-library report by hand.

    Scoping filters the *input* item set (not the finished report), so every
    item-derived block is genuinely one-source: the custody view
    (`tiers`/`drift`/`coverage`/`enrichment`/`summaries`), the per-source
    `by_source` (which collapses to the singleton ``{S: …}``), **and** the
    offending-id lists (`drift.events`, `enrichment.items`, `missing_scrolls`,
    duplicates) all narrow to <S>. The convergence this guarantees by
    construction: a `--source S` audit's `tiers`/`drift`/`coverage` equals the
    whole-library audit's `by_source[S]` (same held subset, same tally) and its
    `enrichment.stale` equals `enrichment.by_source[S]` — pinned in
    `tests/test_custody_convergence.py`.

    Three checks are **not** source-attributable, so a scoped audit skips them:
    `orphan_scrolls` (an unowned scroll file belongs to no source, and scoping
    the item set would falsely flag *other* sources' legitimately-owned scrolls
    as orphans), `fts` (a single library-wide index, not a per-source view), and the
    `custody.works` at-risk-works alarm (roadmap H263) — a *work* is a cross-source
    consolidation (a preprint + its published record), so scoping the item set
    fragments works (a 2-representation work split arxiv+crossref drops below the
    floor and vanishes), making "no work is at risk" a falsehood the scope produced.
    All three are whole-library views left to an unscoped `scrolls doctor`; under a
    source scope they report empty/`skipped` (the works block keeps `status:
    "skipped"`, never a fabricated "0 at risk"). The exit-code rule is unchanged —
    structural `issues > fixed` fails — now over only <S>'s attributable findings (an
    unknown source holds nothing, so it is the honest empty audit: `score: 100`,
    zeroed counts, never an error).
    """
    report: dict[str, Any] = {
        "issues": 0,
        "fixed": 0,
        "duplicates": [],
        "missing_scrolls": [],
        "missing_media": [],
        "orphan_scrolls": [],
        "fts": {"in_sync": None, "status": "skipped"},
        "custody": {
            "score": None,
            "issues": 0,
            "tiers": {"full": 0, "partial": 0, "reference": 0},
            "by_source": {},
            "findings": [],
            "drift": {
                "basis": "last_verify",
                "as_of": None,
                "checked": 0,
                "unverified": 0,
                "unchanged": 0,
                "drifted": 0,
                "rotted": 0,
                "error": 0,
                "coverage": {"verified": 0, "total": 0},
                "events": [],
            },
            "conflicts": {
                # The import-conflict aggregate (roadmap H275, ADR 0104) — the
                # read-aggregate sibling of the drift block, over the *other*
                # provenance-of-divergence axis. ``basis`` names the source of the
                # view: these are read from the recorded import-conflict ledger
                # events, not confirmed live this run. ``items`` is the count of
                # currently-held items carrying an *unresolved* conflict (the latest
                # conflict's incoming hash still disagrees with the held copy);
                # ``events`` lists the latest unresolved conflict per affected item.
                # A report view only — never feeds ``issues``/``fixed`` or the exit
                # code (doctor cannot repair a divergence it must not overwrite).
                "basis": "import_ledger",
                "as_of": None,
                "items": 0,
                "events": [],
            },
            "enrichment": {
                "basis": "ruleset_fingerprint",
                "current_ruleset": RULESET_FINGERPRINT,
                "classified": 0,
                "current": 0,
                "stale": 0,
                "unfingerprinted": 0,
                "items": [],
                "by_source": {},
            },
            "summaries": {
                "basis": "members_hash",
                "eligible": 0,
                "summarized": 0,
                "current": 0,
                "stale": 0,
                "never": 0,
                "items": [],
                "by_source": {},
            },
            "works": {
                # The at-risk-works consolidation alarm (roadmap H263): the works no
                # representation safely holds (the H261 `safely_held == False` set).
                # `status` distinguishes a computed audit ("ok") from one a `--source`
                # scope skipped ("skipped") — a work spans sources, so a scoped item
                # set fragments works (see `_check_at_risk_works`); the honest default
                # is "skipped" so a missing-db/scoped report never reads as a confirmed
                # "0 at risk" it never computed (the drift block's `unverified` honesty).
                "status": "skipped",
                "total": 0,
                "at_risk": 0,
                "most_at_risk": None,
            },
        },
    }
    if not paths.db_path.exists():
        return report

    _check_duplicates(paths, report, fix, source)
    # re-read after merges so the other checks see the repaired rows
    items = list_items(paths.db_path, source=source)
    _check_missing_scrolls(paths, report, items, fix)
    _check_missing_media(paths, report, items)
    if source is None:
        # Not source-attributable (see the run_doctor docstring): an orphan file
        # owns no source, the single FTS index is a whole-library view, and a *work*
        # spans sources (a 2-rep work split arxiv+crossref fragments under a scope).
        # A scoped audit leaves all three at their honest empty/skipped defaults.
        _check_orphan_scrolls(paths, report, items)
        _check_fts(paths, report, fix)
        _check_at_risk_works(paths, report, items)
    _check_custody_integrity(paths, report, items)
    _check_custody_drift(paths, report, items)
    _check_custody_conflicts(paths, report, items)
    _check_enrichment_provenance(report, items)
    _check_summary_provenance(paths, report, items)
    return report


def _check_duplicates(
    paths: LibraryPaths, report: dict, fix: bool, source: str | None = None
) -> None:
    """Items minted from different spellings of one URL (ADR 0023's debt).

    Only url-hash identities qualify: for items with a `source_id`, the
    URL spelling never was the identity, and second-guessing source
    detection is not doctor's business. `source` scopes the scan to one
    source's items (duplicates group within a source — the key is
    ``(source, url)`` — so the filter only drops other sources' groups).
    """
    groups: dict[tuple[str, str], list[ScrollItem]] = {}
    for item in list_items(paths.db_path, source=source):
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


def _check_custody_integrity(
    paths: LibraryPaths, report: dict, items: list[ScrollItem]
) -> None:
    """Custody integrity audit (ADR 0097): is each item held as honestly as
    it claims, and can we still prove what we hold?

    This is a custody *view* over the library, kept deliberately separate from
    the repairable-drift accounting (`report["issues"]`/`["fixed"]`) that drives
    doctor's exit code. Its outputs live entirely under `report["custody"]`:

    - ``tiers``: the fidelity distribution (``get_fidelity`` per item).
    - ``findings``: per-item custody violations, each a deterministic,
      network-free integrity check:
        * ``missing_scroll`` — a rendered item whose scroll file is gone, so
          the rendered view it advertises no longer exists on disk. (The
          repairable side of this is `_check_missing_scrolls`; here it counts
          only toward the custody score, never twice toward `issues`.)
        * ``unrederivable_hash`` — a ``content_hash`` is stored but neither
          ``raw_text`` nor ``extracted_text`` survives, so we hold a
          fingerprint of content we can no longer reproduce or verify.
        * ``missing_provenance`` — content is held (full/partial) but neither
          ``url`` nor ``source_id`` records where it came from.
    - ``issues``: the count of items carrying at least one finding.
    - ``score``: percent of items free of custody findings (100 when empty).

    A reference-only item with complete provenance is honest custody, not a
    violation, so it never lowers the score.
    """
    custody = report["custody"]
    for item in items:
        tier = get_fidelity(item)
        custody["tiers"][tier] = custody["tiers"].get(tier, 0) + 1

        findings = []
        scroll_path = paths.root / item.markdown_path if item.markdown_path else None
        if item.stage == "rendered" and item.markdown_path:
            if not scroll_path or not scroll_path.exists():
                findings.append("missing_scroll")
        if item.content_hash and not item.raw_text and not item.extracted_text:
            findings.append("unrederivable_hash")
        if tier != "reference" and not item.url and not item.source_id:
            findings.append("missing_provenance")

        if findings:
            custody["issues"] += 1
            custody["findings"].append(
                {"id": item.id, "tier": tier, "issues": findings, "status": "found"}
            )

    total = len(items)
    clean = total - custody["issues"]
    custody["score"] = 100 if total == 0 else round(100 * clean / total)


def _check_custody_drift(
    paths: LibraryPaths, report: dict, items: list[ScrollItem]
) -> None:
    """Aggregate the custody ledger's latest verdict per item (ADR 0098).

    Where the integrity audit is the offline "do we still hold it?" view, this
    is the network-derived "has the source drifted or rotted out from under our
    capture?" view, read from the events `scrolls verify` records. Only the
    most recent event per *currently held* item counts — a verdict for a since-
    deleted item is not this library's drift. ``drifted``/``rotted`` are the
    actionable losses, listed in ``events``; ``unchanged``/``error`` stay as
    counts. Like the integrity findings, drift is a *report*: it never feeds the
    structural ``issues``/``fixed`` or the exit code, because doctor cannot
    repair a source that changed upstream.

    The block is honest about *what it verified* (completeness contract G2,
    `docs/cli.md`): doctor is network-free, so every verdict here is read from
    the ledger, not confirmed live this run. ``basis`` names that source
    (``"last_verify"`` — these are as-of-the-last-`scrolls verify`, not
    "verified now") and ``as_of`` the freshest ``checked_at`` the picture rests
    on (``None`` when nothing is verified). ``unverified`` counts held items the
    ledger has *no* verdict for — never re-checked, so unknown, **not** clean:
    "absent from the drift counts" must never be read as "confirmed unchanged".

    ``coverage`` (``{verified, total}``, roadmap H113) reports the verdict
    coverage as a *fraction* the raw counts leave implicit: of the held items
    that *can* carry a verdict (``total`` — the hash-bearing set; a reference-only
    capture has no baseline hash to diff, so it is unverifiable and excluded), how
    many now do (``verified``). The same `custody.recheck_coverage`
    `scrolls maintain` reports on its recheck (H109), here with no `checked_ids`
    (doctor never rechecks — a pure read of the current ledger), so the audit
    shows "N of M verifiable items carry a verdict" at parity with maintain.
    ``verified`` ≡ ``checked`` by construction: every verdict-bearing held item is
    hash-bearing (verify never runs on a reference-only item), so the coverage
    numerator equals the block's own checked count.

    The held-filtered ledger this builds also feeds ``custody.by_source`` (roadmap
    H104): the whole-library tier/posture aggregate split per source (via the shared
    `custody_counts_by_source`), so the audit names *which* source's custody is
    weakest. It reads off the *same* `latest` this block aggregates — no second
    ledger read — so the per-source tallies sum to this block's counts by
    construction. Each per-source entry also carries its own ``coverage``
    (``{verified, total}``, roadmap H121) — of that source's hash-bearing held items,
    how many carry a verdict — the per-source counterpart of this block's whole-library
    ``coverage``, so the audit names not just which source has the most drift but
    which is least *covered* (most never-checked); the per-source coverage sums to
    ``drift.coverage`` by construction (the same `recheck_coverage` over each source's
    hash-bearing slice of the one held set).
    """
    drift = report["custody"]["drift"]
    held = {item.id for item in items}
    latest = {
        item_id: event
        for item_id, event in latest_events(paths.db_path).items()
        if item_id in held
    }
    # Per-source custody split over the same held-filtered ledger (H104): an
    # optional map the whole-library `tiers`/`drift` aggregate by source, so the
    # per-source tallies sum to this block by construction (one `custody_counts`).
    report["custody"]["by_source"] = custody_counts_by_source(items, latest)
    drift["checked"] = len(latest)
    # `held − verdicts` via the one shared predicate `scrolls verify --unverified`
    # selects on, so the count doctor reports and the set a re-check clears can
    # never disagree (convergence by construction).
    drift["unverified"] = len(unverified_items(items, latest))
    # Coverage over the verifiable (hash-bearing) held set — the same primitive
    # maintain reports on (H109), with no `checked_ids` since doctor only reads.
    drift["coverage"] = recheck_coverage(
        [item for item in items if item.content_hash], latest
    )
    drift["as_of"] = max((e.checked_at for e in latest.values()), default=None)
    for status in CUSTODY_STATUSES:
        drift[status] = sum(1 for e in latest.values() if e.status == status)
    drift["events"] = [
        {
            "id": event.item_id,
            "status": event.status,
            "checked_at": event.checked_at,
            "prior_hash": event.prior_hash,
            "observed_hash": event.observed_hash,
        }
        for _, event in sorted(latest.items())
        if event.status in ("drifted", "rotted")
    ]


def _check_custody_conflicts(
    paths: LibraryPaths, report: dict, items: list[ScrollItem]
) -> None:
    """Aggregate the import-conflict ledger into a scope-level read (roadmap H275).

    The read-aggregate sibling of `_check_custody_drift`, over the *other*
    provenance-of-divergence axis (ADR 0104). The drift block folds the latest
    *verify* verdict per held item ("has the live source moved?"); this folds the
    latest *import-conflict* event per held item ("did a peer's capture of this id
    disagree with mine when I merged a bundle?"). The two read disjoint ledger
    slices — `latest_conflict_events` reads only the `conflict` rows, `latest_events`
    only the verify verdicts — so a conflict never inflates the drift counts and a
    drift verdict never appears here.

    A conflict is reported as **unresolved** while the latest conflict's incoming
    hash still disagrees with the held copy's current `content_hash`
    (`unresolved_conflicts`, the resolution-aware predicate): the held copy is never
    auto-overwritten (raw is sacred), so every recorded conflict is unresolved today,
    but the predicate already clears an item a future `reconcile` (H276) resolves —
    no read change needed. Held-filtered like the drift block (a conflict on a
    since-deleted id is not this library's divergence), so the count doctor reports
    is exactly the set a `reconcile` would act on.

    A **report view only** (ADR 0104, custody §2.4): like the drift block it never
    feeds the structural `issues`/`fixed` or the exit code — doctor cannot repair a
    divergence it must not silently overwrite. Because the fold runs over the
    (possibly `--source`-scoped) `items`, the aggregate scopes by source for free,
    exactly as `custody.drift` does — a held item owns a source, so an import
    conflict is source-attributable (unlike the cross-source `custody.works` alarm).
    """
    conflicts = report["custody"]["conflicts"]
    unresolved = unresolved_conflicts(items, latest_conflict_events(paths.db_path))
    conflicts["items"] = len(unresolved)
    conflicts["as_of"] = max(
        (e.checked_at for e in unresolved.values()), default=None
    )
    conflicts["events"] = [
        {
            "id": event.item_id,
            "status": event.status,
            "checked_at": event.checked_at,
            "prior_hash": event.prior_hash,
            "observed_hash": event.observed_hash,
        }
        for _, event in sorted(unresolved.items())
    ]


def _check_at_risk_works(
    paths: LibraryPaths, report: dict, items: list[ScrollItem]
) -> None:
    """At-risk works — the consolidation custody alarm (ADR 0069/0095, roadmap H263).

    The work-level counterpart of the per-source weakest-source `attention` flag: where
    that names the source carrying the most actionable per-*item* drift, this names the
    **works** carrying a *consolidation* loss. A work (the cluster of representations of
    one scholarly work — a preprint, its published record, an index entry, ADR 0069) is
    **at risk** when **no** representation is *safely held* (the H261 `work_custody`
    `safely_held == False`: there is no representation that is both `full` *and* unmoved
    anywhere in its cluster). That is a sharper alarm than the per-item drift count: an
    item drifting is survivable when a sibling representation of the *same* work is still
    `full`+verified; a work with no safe representation is a real custody loss — every
    copy of the work is degraded or moved.

    Lives entirely under `report["custody"]["works"]`, a custody *view* like the drift /
    enrichment / summary blocks — never the repairable `issues`/`fixed` or the exit code:
    doctor cannot repair a source that moved upstream, and a degraded work is reported,
    never silently overwritten (custody §2.4). Sets ``status: "ok"`` and fills
    ``{total, at_risk, most_at_risk}`` from the shared `works.at_risk_signal` over the
    library's multi-representation works (`works_over`'s 2+ default — the consolidation
    question only applies to a work with siblings) and the *same* `latest_events` ledger
    the drift block reads. Called **only on the unscoped audit** (the `source is None`
    branch beside `_check_orphan_scrolls`/`_check_fts`): a work spans sources, so a
    `--source`-scoped item set fragments works, and the block stays at its honest
    `status: "skipped"` default rather than reading a scope-induced "0 at risk".
    """
    works = works_over(items)
    verdicts = latest_events(paths.db_path)
    report["custody"]["works"] = {"status": "ok", **at_risk_signal(works, verdicts)}


def _check_enrichment_provenance(report: dict, items: list[ScrollItem]) -> None:
    """Re-derivability of rules classification (cap 8, ADR 0004 / roadmap H20).

    `scrolls classify` records `classified_ruleset` — the fingerprint of the
    ruleset that produced a category (`classify.RULESET_FINGERPRINT`). This
    aggregates how the held, rules-classified items stand against the *live*
    ruleset, so a reader can tell which categories a re-classify today would
    re-derive unchanged and which were produced under a ruleset that has since
    changed:

    - ``classified`` — held items the rules engine classified (the denominator;
      LLM classifications are a different re-derivability axis and out of scope).
    - ``current`` — classified under the live ruleset (`current_ruleset`).
    - ``stale`` — classified under a *superseded* ruleset; the offending ids and
      their recorded fingerprint are listed in ``items`` so a re-classify can be
      targeted.
    - ``unfingerprinted`` — rules-classified before H20, so no fingerprint was
      recorded: we cannot tell whether a re-classify would differ. Like the
      drift block's ``unverified``, this is *unknown*, not silently current.
    - ``by_source`` — the stale count split per source (roadmap H135): a flat
      ``{source: stale_count}`` map of the *offending* sources only (a source
      with no stale debt is omitted, the ``items``-list posture), source keys in
      sorted order. The re-derivability counterpart of the per-source coverage
      `custody.by_source` carries (H121), so the audit names *which* source has
      the most categories to refresh with `classify --stale`. Every stale item
      has exactly one source, so the values sum to ``stale`` by construction (the
      H104/H121 sum-to-whole posture on the enrichment axis). Kept under this
      block rather than folded into `custody.by_source` so the shared
      `custody_counts_by_source` — and the `maintain` report that faithfully
      reads it (H123/H127) — stay byte-identical, and `custody.py` (the verify-
      ledger module) stays free of classification coupling.

    Like drift, this is a *report*, never repairable ``issues`` and never the
    exit code: a stale fingerprint means the ruleset changed, not that the
    stored category is wrong (the recorded method is still valid for the ruleset
    that produced it). Doctor never auto-reclassifies — a regenerated view is
    produced on request, never as a silent overwrite (custody §2.4).
    """
    enrichment = report["custody"]["enrichment"]
    # The per-item `confidence.freshness` marker an agent reads (H21) and this
    # aggregate share one derivation — `classify.classification_freshness` — so
    # the count here can never disagree with the marker or the `classify --stale`
    # pool (the H25/H27 convergence). `unknown` is doctor's `unfingerprinted`.
    bucket = {"current": "current", "stale": "stale", "unknown": "unfingerprinted"}
    stale = []
    for item in items:
        freshness = classification_freshness(item.provenance)
        if freshness is None:  # not a rules classification — a different axis
            continue
        enrichment["classified"] += 1
        enrichment[bucket[freshness]] += 1
        if freshness == "stale":
            stale.append(
                {"id": item.id, "ruleset": item.provenance["classified_ruleset"]}
            )
    enrichment["items"] = sorted(stale, key=lambda entry: entry["id"])
    # Per-source stale-classification debt (roadmap H135, see the `by_source`
    # docstring bullet): offending sources only, sorted; sums to `stale`. Built by
    # the one shared `stale_classification_counts_by_source` the readable `_Refresh:_`
    # briefing line (H178) also folds, so the audit map and the briefing's named
    # sources can never disagree (convergence by construction).
    enrichment["by_source"] = stale_classification_counts_by_source(items)


def _check_summary_provenance(
    paths: LibraryPaths, report: dict, items: list[ScrollItem]
) -> None:
    """Re-derivability of LLM concept summaries (cap 8, ADR 0025 / roadmap H29).

    The summary-axis counterpart of `_check_enrichment_provenance`. `scrolls kb
    --engine llm` stores each concept summary with a `members_hash` fingerprint
    of the scrolls it was synthesized from (`kb_llm.members_hash`). This
    aggregates how the held, summary-eligible concepts stand against their *live*
    members, so a reader can tell which summaries a re-synthesis today would
    reproduce unchanged and which were written before the membership changed:

    - ``eligible`` — held concepts that qualify for a summary (≥ `MIN_MEMBERS`
      rendered members, the generator's denominator). LLM-only: the deterministic
      compiler's pages need no synthesis.
    - ``summarized`` — eligible concepts that have a stored summary
      (``current`` + ``stale``).
    - ``current`` — the stored summary's `members_hash` matches the live members:
      a re-synthesis is a no-op (the generator's incremental-skip condition).
    - ``stale`` — the members changed since synthesis (or a superseded engine
      wrote it); the slug, the stored `members_hash`, and the live `live_hash`
      are listed in ``items`` so a re-synthesis can be targeted.
    - ``never`` — eligible but never summarized: unknown, not silently current
      (the drift block's ``unverified`` honesty, on the summary axis).
    - ``by_source`` — the stale count split per source (roadmap H171): a flat
      ``{source: stale_count}`` map of the *offending* sources only (a source
      with no stale debt is omitted, the ``items``-list posture), source keys in
      sorted order. The summary-axis counterpart of `enrichment.by_source`
      (H135), so a worker triaging "source <S>'s summaries are stale" sees which
      source's items drove a cluster stale without scanning ``items`` — the
      read-side precursor of `scrolls kb --stale --source <S>` (roadmap H172).

      **The load-bearing decision (H171), and why this map differs from the
      drift/enrichment ones.** A concept summary spans a *cluster* whose members
      may come from several sources, and the stored fingerprint records only the
      members digest, not which member moved — so we cannot attribute a stale
      summary to a single member's source. A stale summary is therefore
      attributed to **every source present among its live members** (a summary is
      "stale for source S" if S participates in the concept), which is exactly the
      offenders set `kb --stale --source S` must act on: `kb --stale` operates on
      *concepts*, not members, so refreshing source S re-synthesizes every stale
      concept S is a member of. The consequence: one multi-source stale concept
      counts toward >1 source, so ``by_source`` **need not sum to ``stale``**
      (``sum(by_source.values()) >= stale``, equality iff every stale concept is
      single-source) — unlike the drift/enrichment maps, where each item has
      exactly one source and the per-source values sum to the whole. This
      supersedes the H135-era decision to omit the breakdown: the omission was
      justified by the sum-to-whole convergence, which this map deliberately does
      not claim (and so cannot break).

    Like drift and the enrichment block, this is a *report*, never repairable
    ``issues`` and never the exit code: stale members mean the concept's
    membership moved, not that the stored summary is wrong (it is still a valid
    synthesis of the members it was written from). Doctor never auto-regenerates —
    a refreshed summary is produced on request (`scrolls kb --stale`, roadmap
    H31), never as a silent overwrite (custody §2.4).
    """
    summaries = report["custody"]["summaries"]
    # Same denominator the generator uses: rendered members only (an unrendered
    # item has no scroll file to synthesize from), grouped into eligible concepts
    # via the one shared `eligible_concepts` helper so the audit and the
    # generator can never disagree on which concepts a summary is expected for.
    rendered = [item for item in items if item.markdown_path]
    eligible = eligible_concepts(rendered)
    if not eligible:
        return
    stored = load_concept_summaries(paths.db_path)
    # The per-concept `summary_freshness` marker (the H29 view) and this aggregate
    # share one derivation, so the count here can never disagree with the view or
    # the `kb --stale` pool (the H31 convergence the classification axis pins too).
    stale = []
    for slug in sorted(eligible):
        members = eligible[slug]["items"]
        live = members_hash(members)
        prior = stored.get(slug)
        freshness = summary_freshness(prior, live)
        summaries["eligible"] += 1
        if prior is not None:
            summaries["summarized"] += 1
        summaries[freshness] += 1  # never / current / stale
        if freshness == "stale":
            stale.append(
                {"slug": slug, "members_hash": prior.members_hash, "live_hash": live}
            )
    summaries["items"] = stale  # already slug-ordered (sorted iteration)
    # Per-source stale-summary debt (roadmap H171): offenders only, sorted keys; the
    # multi-source attribution (a cluster counts toward each member source, so the
    # map need not sum to the stale-concept count). Built by the one shared
    # `stale_summary_counts_by_source` the readable `_Refresh:_` briefing line (H178)
    # also folds, so the audit map and the briefing's named sources can never disagree.
    summaries["by_source"] = stale_summary_counts_by_source(rendered, stored)
