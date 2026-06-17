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

from scrolls.classify import RULESET_FINGERPRINT, classification_freshness
from scrolls.custody import (
    CUSTODY_STATUSES,
    latest_events,
    recheck_coverage,
    unverified_items,
)
from scrolls.kb import load_concept_summaries
from scrolls.kb_llm import eligible_concepts, members_hash, summary_freshness
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

_STAGE_RANK = {"detected": 0, "fetched": 1, "rendered": 2}


# `get_fidelity` lives in items.py (the custody tier is an item-model
# property); imported above so `doctor.get_fidelity` and the custody audit
# below share the one definition with `facets` and `list`.

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
        "custody": {
            "score": None,
            "issues": 0,
            "tiers": {"full": 0, "partial": 0, "reference": 0},
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
            "enrichment": {
                "basis": "ruleset_fingerprint",
                "current_ruleset": RULESET_FINGERPRINT,
                "classified": 0,
                "current": 0,
                "stale": 0,
                "unfingerprinted": 0,
                "items": [],
            },
            "summaries": {
                "basis": "members_hash",
                "eligible": 0,
                "summarized": 0,
                "current": 0,
                "stale": 0,
                "never": 0,
                "items": [],
            },
        },
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
    _check_custody_drift(paths, report, items)
    _check_enrichment_provenance(report, items)
    _check_summary_provenance(paths, report, items)
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
    """
    drift = report["custody"]["drift"]
    held = {item.id for item in items}
    latest = {
        item_id: event
        for item_id, event in latest_events(paths.db_path).items()
        if item_id in held
    }
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
        live = members_hash(eligible[slug]["items"])
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
