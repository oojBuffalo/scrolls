"""The `scrolls` command-line interface.

Commands emit JSON on stdout so coding agents can consume them directly
(IDEAS.md §10: shell access first, MCP later).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from scrolls import __version__
from scrolls.agents import install_agent_docs
from scrolls.bookmarks import ImportSourceError as BookmarksSourceError
from scrolls.bookmarks import dump_bookmark_export, load_bookmark_export
from scrolls.bundle import (
    BundleError,
    build_bundle,
    build_bundle_html,
    parse_bundle,
    parse_bundle_archive,
    parse_bundle_events,
)
from scrolls.classify import classify_item, stale_classifications
from scrolls.config import ConfigError, load_config, resolve_llm_model
from scrolls.custody import (
    LEDGER_STATUSES,
    CustodyEvent,
    conflict_event,
    current_conflict,
    custody_counts,
    drift_posture,
    dump_events_export,
    events_for_items,
    import_events,
    item_events,
    item_history,
    items_checked_before,
    items_in_posture,
    last_checked,
    latest_events,
    live_recapture,
    parse_since,
    partition_resolvable_events,
    preview_import_events,
    recheck_coverage,
    recheck_order,
    record_events,
    resolution_event,
    supersession_event,
    tally_custody,
    tally_custody_by_source,
    unverified_items,
    verify_item,
)
from scrolls.context import BUDGET_TIERS as CONTEXT_BUDGET_TIERS
from scrolls.context import DEFAULT_BUDGET as DEFAULT_CONTEXT_BUDGET
from scrolls.context import DEFAULT_LIMIT as DEFAULT_CONTEXT_LIMIT
from scrolls.context import build_context
from scrolls.db import init_db, read_schema_version
from scrolls.doctor import run_doctor
from scrolls.facets import DEFAULT_LIMIT as DEFAULT_FACETS_LIMIT
from scrolls.facets import FIELDS as FACET_FIELDS
from scrolls.facets import compute_facets
from scrolls.feeds import (
    FeedError,
    follow_feed,
    get_subscription,
    insert_subscription,
    list_subscriptions,
    make_subscription_id,
    remove_subscription,
    sync_many,
    to_feed_url,
)
from scrolls.fieldtheory import DEFAULT_ROOT as FIELDTHEORY_ROOT
from scrolls.fieldtheory import ImportSourceError, load_bookmarks
from scrolls.graph import (
    build_graph,
    content_duplicate_subgraph,
    to_payload as graph_payload,
)
from scrolls.works import DEFAULT_MIN_REPRESENTATIONS as DEFAULT_WORK_MIN
from scrolls.works import (
    filter_works,
    membership_payload,
    to_payload as works_payload,
    work_membership,
    works_for_item,
    works_over,
)
from scrolls.items import (
    ScrollItem,
    adopt_incoming,
    archive_entry_dict,
    archived_records,
    archived_snapshots,
    classification_provenance,
    content_duplicate_ids,
    diff_snapshot,
    dump_archive_export,
    get_fidelity,
    get_item,
    import_archive,
    insert_item,
    item_summary,
    latest_archived,
    library_counts,
    list_archived,
    list_items,
    merge_item,
    preview_import_archive,
    prune_archive,
    select_archived_snapshot,
    select_prunable_archive,
    update_item,
)
from scrolls.archive_export import ArchiveSourceError, load_archive_export
from scrolls.events_export import EventsSourceError, load_events_export
from scrolls.items_export import ItemsSourceError
from scrolls.items_export import dump_items_export, load_items_export
from scrolls.kb import compile_kb
from scrolls.maintain import (
    DEFAULT_HISTORY_LIMIT,
    assemble_report,
    compute_trend,
    custody_snapshot,
    last_run_boundary,
    load_snapshot,
    log_path,
    read_log,
    report_by_source,
    report_enrichment_by_source,
    report_summary_by_source,
    skipped_recheck_report,
    snapshot_headline,
    snapshot_path,
    weakest_source,
)
from scrolls.media import capture_media, has_pending_media
from scrolls.overrides import OverrideError, apply_overrides, parse_assignments
from scrolls.paths import LibraryPaths, get_paths
from scrolls.opml import ImportSourceError as OPMLSourceError
from scrolls.opml import dump_opml_export, load_opml_export
from scrolls.pipeline import ensure_library, ingest_url, register_url, resolve_item_id
from scrolls.pocket import ImportSourceError as PocketSourceError
from scrolls.pocket import load_pocket_export
from scrolls.related import DEFAULT_LIMIT as DEFAULT_RELATED_LIMIT
from scrolls.related import (
    filter_related,
    related_duplicate_ids,
    scored_related,
    tally_relation_strength,
)
from scrolls.remove import remove_item
from scrolls.render import write_scroll
from scrolls.scope import scope_envelope
from scrolls.search import count_matches, hit_payload, search_items, tally_strength
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.detect import detect_source
from scrolls.takeout import ImportSourceError as TakeoutSourceError
from scrolls.takeout import load_watch_history


def build_parser() -> argparse.ArgumentParser:
    """The full `scrolls` argument parser.

    Separate from `main` so tests can introspect the command surface —
    `tests/test_docs.py` diffs it against `README.md` and `docs/cli.md`.
    """
    parser = argparse.ArgumentParser(
        prog="scrolls",
        description="Turn saved internet artifacts into an agent-readable knowledge library.",
    )
    parser.add_argument("--version", action="version", version=f"scrolls {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser(
        "add", help="Register a URL as a library item, unfetched (JSON output)"
    )
    add_parser.add_argument("url", help="URL to add")

    agent_parser = subparsers.add_parser(
        "agent", help="Agent integration commands"
    )
    agent_sub = agent_parser.add_subparsers(dest="agent_command", required=True)
    agent_sub.add_parser(
        "install",
        help="Write agent instruction files under <root>/agents (JSON output)",
    )

    classify_parser = subparsers.add_parser(
        "classify", help="Categorize items with the rules engine (JSON output)"
    )
    classify_parser.add_argument(
        "id",
        nargs="?",
        help="Classify one item by id or URL, replacing any existing category; "
        "default is every fetched/rendered item without one",
    )
    classify_parser.add_argument(
        "--engine",
        choices=("rules", "llm"),
        default=None,
        help="Classification engine: deterministic rules (default), or an "
        "LLM that also fills domain and concepts (needs ANTHROPIC_API_KEY; "
        "model overridable via SCROLLS_LLM_MODEL). Defaults to [classify] "
        "default_engine in config.toml, else rules",
    )
    classify_parser.add_argument(
        "--batch",
        action="store_true",
        help="Submit the whole run as one Message Batches API request "
        "(llm engine only): half the per-token price, but the command "
        "waits for the batch to finish — typically minutes",
    )
    classify_parser.add_argument(
        "--stale",
        action="store_true",
        help="Re-run the rules engine over items classified under a superseded "
        "ruleset (the ids `scrolls doctor` reports in custody.enrichment.stale), "
        "refreshing their category and ruleset fingerprint to the live ruleset; "
        "rules engine only, never with --batch or a single id",
    )
    classify_parser.add_argument(
        "--source",
        default=None,
        help="Narrow --stale to one source's stale classifications, e.g. web, "
        "arxiv (the ids `scrolls doctor` reports in "
        "custody.enrichment.by_source[<source>]) — the enrichment-axis "
        "counterpart of `verify --source`; requires --stale",
    )

    context_parser = subparsers.add_parser(
        "context",
        help="Compact context bundle of matching scrolls (Markdown output)",
    )
    context_parser.add_argument("query", help="Free-text query; tokens are AND-ed")
    context_parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_CONTEXT_LIMIT,
        help=f"Maximum scrolls in the bundle (default {DEFAULT_CONTEXT_LIMIT})",
    )
    context_parser.add_argument(
        "--source", default=None, help="Only scrolls from one source, e.g. web, arxiv"
    )
    context_parser.add_argument(
        "--category",
        default=None,
        help="Only scrolls with this category; an empty value selects "
        "unclassified items",
    )
    context_parser.add_argument(
        "--stage",
        choices=("detected", "fetched", "rendered"),
        default=None,
        help="Only scrolls at one pipeline stage",
    )
    context_parser.add_argument(
        "--tag", default=None, help="Only scrolls carrying this tag (case-insensitive)"
    )
    context_parser.add_argument(
        "--concept",
        default=None,
        help="Only scrolls carrying this concept (matched by slug)",
    )
    context_parser.add_argument(
        "--fidelity",
        choices=("full", "partial", "reference"),
        default=None,
        help="Only scrolls the library holds at this custody-fidelity tier "
        "(ADR 0097) — the holdings-axis companion of --drift; sieved before "
        "--limit, so the bundle covers the top matches *at that tier* (e.g. "
        "build context from only the full-fidelity sources you can re-derive "
        "offline). The rendered _Custody:_/_Fidelity:_ headline describes the "
        "kept set",
    )
    context_parser.add_argument(
        "--drift",
        choices=("verified", "unverified", "drifted", "rotted", "error"),
        default=None,
        help="Only scrolls at this custody drift posture (from the verify "
        "ledger) — the ledger-claim-axis companion of --fidelity; sieved "
        "before --limit, so the bundle covers the top matches *at that posture* "
        "(e.g. --drift drifted to brief on only the sources that have moved). "
        "ANDs with --fidelity",
    )
    context_parser.add_argument(
        "--strength",
        choices=("strong", "moderate", "weak"),
        default=None,
        help="Only scrolls whose query lands at or above this rank-strength band "
        "— strong (title), moderate (title or summary), weak (any field); the "
        "rank-axis companion of --fidelity/--drift, sieved before --limit, so the "
        "bundle covers the top matches *at that strength* (e.g. --strength strong "
        "to brief on only the excerpts whose query is in the title). The rendered "
        "_Strength:_ headline describes the kept set",
    )
    context_parser.add_argument(
        "--content-duplicate",
        dest="content_duplicate",
        action="store_true",
        help="Only matches the library holds a byte-identical copy of under "
        "another id — the content-duplicate set (the content-identity custody "
        "shape); the browse-axis companion of `scrolls list`/`search "
        "--content-duplicate` and `show`'s content_duplicate_ids, lifted to the "
        "context bundle. A boolean flag, report-only (never a merge), sieved "
        "before --limit/--budget. The sibling may live in another source (a "
        "content group spans the query scope), so it briefs the top matches with "
        "a byte-identical sibling anywhere held; the kept slice re-folds the "
        "Coverage line and the _Duplicates:_ briefing. ANDs with "
        "--fidelity/--drift/--strength",
    )
    context_parser.add_argument(
        "--budget",
        choices=CONTEXT_BUDGET_TIERS,
        default=DEFAULT_CONTEXT_BUDGET,
        help="Bundle depth tier: index (catalog only), connected (+ link "
        f"graph), or full (+ excerpts; default {DEFAULT_CONTEXT_BUDGET})",
    )

    detect_parser = subparsers.add_parser(
        "detect", help="Detect which source adapter handles a URL (JSON output)"
    )
    detect_parser.add_argument("url", help="URL to inspect")

    doctor_parser = subparsers.add_parser(
        "doctor", help="Check library integrity, repair drift with --fix (JSON output)"
    )
    doctor_parser.add_argument(
        "--fix",
        action="store_true",
        help="Repair what is safe offline: merge duplicate items, rewrite "
        "missing scrolls from the index, rebuild the search index. "
        "Missing media files (run `scrolls media`) and orphan scroll "
        "files are reported but never touched",
    )
    doctor_parser.add_argument(
        "--source",
        default=None,
        metavar="S",
        help="Scope the whole custody audit to one source (e.g. web, arxiv) — "
        "every block (score, tiers, drift, coverage, enrichment, by_source, and "
        "the offending-id lists) is that source's view, the audit-side of the "
        "per-source act commands. Orphan-file and FTS-index checks (not "
        "source-attributable) are skipped; an unknown source is the empty audit",
    )

    facets_parser = subparsers.add_parser(
        "facets",
        help="Enumerate the filterable vocabulary with item counts (JSON output)",
    )
    facets_parser.add_argument(
        "field",
        nargs="?",
        choices=FACET_FIELDS,
        default=None,
        help="Report only this dimension; default reports "
        f"{', '.join(FACET_FIELDS)}",
    )
    facets_parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_FACETS_LIMIT,
        help=f"Maximum values per dimension (default {DEFAULT_FACETS_LIMIT})",
    )
    facets_parser.add_argument(
        "--source", default=None, help="Only count items from one source, e.g. web, arxiv"
    )
    facets_parser.add_argument(
        "--category",
        default=None,
        help="Only count items with this category; an empty value selects "
        "unclassified items",
    )
    facets_parser.add_argument(
        "--stage",
        choices=("detected", "fetched", "rendered"),
        default=None,
        help="Only count items at one pipeline stage",
    )
    facets_parser.add_argument(
        "--tag", default=None, help="Only count items carrying this tag (case-insensitive)"
    )
    facets_parser.add_argument(
        "--concept",
        default=None,
        help="Only count items carrying this concept (matched by slug)",
    )

    fetch_parser = subparsers.add_parser(
        "fetch", help="Fetch content for detected items (JSON output)"
    )
    fetch_parser.add_argument(
        "id",
        nargs="?",
        help="Fetch one item by id or URL, refetching even if already fetched; "
        "default is every item at stage 'detected'",
    )
    fetch_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Attempt at most N fetches this run (batch mode only), oldest "
        "saved first; adapterless skips don't consume the limit",
    )

    graph_parser = subparsers.add_parser(
        "graph", help="The cross-item link graph (JSON output)"
    )
    graph_parser.add_argument(
        "--all",
        dest="include_all",
        action="store_true",
        help="Include isolated items (those in no edge) as nodes too",
    )
    graph_parser.add_argument(
        "--content-duplicate",
        dest="content_duplicate",
        action="store_true",
        help="Only nodes the library holds a byte-identical copy of under "
        "another id (their content_duplicate_ids is non-empty), with the "
        "edges induced among them; ANDs with --all",
    )

    works_parser = subparsers.add_parser(
        "works",
        help="Scholarly works clustered by shared DOI (JSON output)",
    )
    works_parser.add_argument(
        "ref",
        nargs="?",
        help="An item id or URL — report only the work(s) this item "
        "represents, with every saved representation (whole library when "
        "omitted; --min is ignored in this per-item form)",
    )
    works_parser.add_argument(
        "--min",
        dest="min_representations",
        type=int,
        default=DEFAULT_WORK_MIN,
        help=f"Minimum representations per work (default {DEFAULT_WORK_MIN})",
    )
    works_parser.add_argument(
        "--fidelity",
        choices=("full", "partial", "reference"),
        default=None,
        help="Only works with a representation the library holds at this "
        "custody-fidelity tier (ADR 0097) — the consolidation-surface twin of "
        "`scrolls list --fidelity` / `related --fidelity`. The whole work travels "
        "(every representation) when one matches, so you see the work and its "
        "siblings (e.g. --fidelity full for works with a form you can re-derive "
        "offline). ANDs with --drift on the same representation",
    )
    works_parser.add_argument(
        "--drift",
        choices=("verified", "unverified", "drifted", "rotted", "error"),
        default=None,
        help="Only works with a representation at this custody drift posture (from "
        "the verify ledger) — the ledger-claim-axis companion of --fidelity. The "
        "whole work travels when one matches (e.g. --drift drifted for the works "
        "needing a recapture decision, with their safe siblings intact). ANDs with "
        "--fidelity on the same representation",
    )
    works_parser.add_argument(
        "--at-risk",
        dest="at_risk",
        action="store_true",
        help="Only works NO representation safely holds — no copy is both full and "
        "unmoved anywhere in the cluster (the consolidation analogue of `scrolls "
        "list --drift`, the `doctor`/`maintain` at-risk-works alarm as a browse "
        "predicate). Not a single --fidelity/--drift value: it is the negation of "
        "\"a full, unmoved copy exists\", the works that are a real custody loss. "
        "ANDs with --fidelity/--drift (e.g. --at-risk --fidelity full for the "
        "recapture candidates whose content is still in hand)",
    )
    works_parser.add_argument(
        "--content-duplicate",
        dest="content_duplicate",
        action="store_true",
        help="Only works that hold the SAME bytes under two representations — a "
        "form byte-identical to a sibling (the consolidation-surface twin of "
        "`scrolls list --content-duplicate`, the per-work content_duplicate flag as "
        "a browse predicate). Within-work scope: a work is kept iff its own forms "
        "duplicate each other, distinct from `list`'s whole-library sibling scope. A "
        "boolean flag, report-only (never a merge); ANDs with --fidelity/--drift/--at-risk",
    )

    follow_parser = subparsers.add_parser(
        "follow", help="Subscribe to an RSS/Atom feed for sync (JSON output)"
    )
    follow_parser.add_argument(
        "url",
        nargs="?",
        help="Feed URL — or a YouTube playlist/channel URL, which maps to "
        "its public feed; omit to list current subscriptions",
    )

    history_parser = subparsers.add_parser(
        "history",
        help="Print one item's full custody-ledger timeline, newest first (JSON output)",
    )
    history_parser.add_argument(
        "id", help="Item id (e.g. wikipedia:en:SQLite), or the item's URL"
    )
    history_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Return only the most recent N checks (newest first); default is "
        "the whole timeline",
    )
    history_parser.add_argument(
        "--since",
        default=None,
        help="Only checks at or after this ISO-8601 timestamp (e.g. 2026-06-15 "
        "or 2026-06-15T12:00:00+00:00); composes with --limit (window then cap)",
    )
    history_parser.add_argument(
        "--status",
        choices=LEDGER_STATUSES,
        default=None,
        help="Only events with this status (unchanged/drifted/rotted/error, or "
        "the import-time conflict) — e.g. the times this source actually drifted, "
        "or every divergent re-import; composes with --since/--limit (status, "
        "then window, then cap)",
    )

    import_parser = subparsers.add_parser(
        "import", help="Bulk-import a local archive (JSON output)"
    )
    import_sub = import_parser.add_subparsers(dest="import_command", required=True)
    bookmarks_parser = import_sub.add_parser(
        "bookmarks",
        help="Import a browser bookmarks HTML export (JSON output)",
    )
    bookmarks_parser.add_argument(
        "path",
        help="exported bookmarks .html file (Netscape format: Chrome, "
        "Firefox, Safari, Edge)",
    )
    fieldtheory_parser = import_sub.add_parser(
        "fieldtheory",
        help="Import X bookmarks from a local Field Theory archive (JSON output)",
    )
    fieldtheory_parser.add_argument(
        "--root",
        default=None,
        help=f"Field Theory archive root (default {FIELDTHEORY_ROOT})",
    )
    takeout_parser = import_sub.add_parser(
        "google-takeout",
        help="Import YouTube watch history from a Google Takeout export "
        "(JSON output)",
    )
    takeout_parser.add_argument(
        "path",
        help="Takeout .zip, extracted directory, or watch-history.json itself "
        "(JSON export format required)",
    )
    pocket_parser = import_sub.add_parser(
        "pocket",
        help="Import a Pocket CSV data export (JSON output)",
    )
    pocket_parser.add_argument(
        "path",
        help="Pocket export .zip, a directory of CSV parts, or a single "
        "exported .csv file",
    )
    opml_parser = import_sub.add_parser(
        "opml",
        help="Import feed subscriptions from an OPML file (JSON output)",
    )
    opml_parser.add_argument(
        "path",
        help="exported OPML feed list (from Feedly, Inoreader, NetNewsWire, "
        "and most RSS readers)",
    )
    import_items_parser = import_sub.add_parser(
        "items",
        help="Import items from a Scrolls JSONL export (JSON output)",
    )
    import_items_parser.add_argument(
        "path",
        help="a JSONL items export written by `scrolls export items`",
    )
    import_items_parser.add_argument(
        "--accept-incoming",
        dest="accept_incoming",
        action="store_true",
        help="On a content conflict (a held id with a different captured content), "
        "*adopt* the incoming copy instead of keeping the held one — the held "
        "capture is archived first (recoverable via `scrolls archive show`) and "
        "the adoption recorded as a `superseded` custody event (ADR 0106). Opt-in; "
        "without it a conflict is surfaced and the held copy kept",
    )
    import_bundle_parser = import_sub.add_parser(
        "bundle",
        help="Import scrolls from a custody bundle, losslessly (JSON output)",
    )
    import_bundle_parser.add_argument(
        "path",
        help="a custody bundle written by `scrolls export bundle`",
    )
    import_bundle_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview what an import would add vs. skip, writing nothing (JSON output)",
    )
    import_bundle_parser.add_argument(
        "--accept-incoming",
        dest="accept_incoming",
        action="store_true",
        help="On a content conflict, adopt the incoming bundle copy (archiving the "
        "held capture, recoverable) instead of keeping the held one — recorded as a "
        "`superseded` event (ADR 0106). Composes with --dry-run, which then predicts "
        "the held→incoming adoptions without writing. Opt-in",
    )
    import_events_parser = import_sub.add_parser(
        "events",
        help="Restore custody events from a JSONL export, deduped (JSON output)",
    )
    import_events_parser.add_argument(
        "path",
        help="a JSONL custody-events export written by `scrolls export events`",
    )
    import_archive_parser = import_sub.add_parser(
        "archive",
        help="Restore the prior-content archive from a JSONL export, deduped "
        "(JSON output) — recovers the superseded captures `export archive` carries",
    )
    import_archive_parser.add_argument(
        "path",
        help="a JSONL archive export written by `scrolls export archive`",
    )

    export_parser = subparsers.add_parser(
        "export", help="Export library data to a portable format (to stdout)"
    )
    export_sub = export_parser.add_subparsers(dest="export_command", required=True)
    export_sub.add_parser(
        "opml",
        help="Export feed subscriptions as an OPML document (to stdout)",
    )
    export_bookmarks_parser = export_sub.add_parser(
        "bookmarks",
        help="Export items as a Netscape bookmark file (to stdout)",
    )
    export_bookmarks_parser.add_argument(
        "--source", default=None, help="Only items from one source, e.g. web, github"
    )
    export_bookmarks_parser.add_argument(
        "--category",
        default=None,
        help="Only items with this category; an empty value selects "
        "unclassified items",
    )
    export_bookmarks_parser.add_argument(
        "--tag", default=None, help="Only items carrying this tag (case-insensitive)"
    )
    export_items_parser = export_sub.add_parser(
        "items",
        help="Export items as a lossless JSONL stream (to stdout)",
    )
    export_items_parser.add_argument(
        "--source", default=None, help="Only items from one source, e.g. web, github"
    )
    export_items_parser.add_argument(
        "--category",
        default=None,
        help="Only items with this category; an empty value selects "
        "unclassified items",
    )
    export_items_parser.add_argument(
        "--tag", default=None, help="Only items carrying this tag (case-insensitive)"
    )
    export_items_parser.add_argument(
        "--fidelity",
        choices=("full", "partial", "reference"),
        default=None,
        help="Only back up items held at this custody-fidelity tier (ADR 0097) — "
        "the holdings-axis companion of --drift; the JSONL stream is the "
        "byte-identical subset `scrolls list --fidelity` enumerates (e.g. "
        "--fidelity full to back up only the holdings you can re-derive offline). "
        "ANDs with --drift",
    )
    export_items_parser.add_argument(
        "--drift",
        choices=("verified", "unverified", "drifted", "rotted", "error"),
        default=None,
        help="Only back up items at this custody drift posture (from the verify "
        "ledger) — the ledger-claim-axis companion of --fidelity; the JSONL "
        "stream is the subset `scrolls list --drift` enumerates (e.g. --drift "
        "drifted to ship only the moved rows for a recapture handoff). ANDs with "
        "--fidelity",
    )
    export_items_parser.add_argument(
        "--content-duplicate",
        dest="content_duplicate",
        action="store_true",
        help="Only back up items the library holds a byte-identical copy of under "
        "another id — the content-duplicate set (the content-identity custody "
        "shape); the JSONL is the subset `scrolls list --content-duplicate` "
        "enumerates, so a recipient can dedup the redundant copies. A boolean flag "
        "(yes/no per item), report-only (never a merge). The sibling may live in "
        "another source, so ANDed with --source it backs up that source's items "
        "with a byte-identical sibling anywhere. ANDs with --fidelity/--drift",
    )
    export_events_parser = export_sub.add_parser(
        "events",
        help="Export the verify ledger (custody events) as a lossless JSONL "
        "stream (to stdout)",
    )
    export_events_parser.add_argument(
        "--source", default=None, help="Only events for items from one source"
    )
    export_events_parser.add_argument(
        "--category",
        default=None,
        help="Only events for items with this category; an empty value selects "
        "unclassified items",
    )
    export_events_parser.add_argument(
        "--tag",
        default=None,
        help="Only events for items carrying this tag (case-insensitive)",
    )
    export_events_parser.add_argument(
        "--since",
        default=None,
        help="Only events at or after this ISO-8601 timestamp (an incremental "
        "backup since the last sweep); re-importing the overlapping union "
        "dedups, so it stays idempotent",
    )
    export_events_parser.add_argument(
        "--fidelity",
        choices=("full", "partial", "reference"),
        default=None,
        help="Only the custody history of items held at this fidelity tier "
        "(ADR 0097) — the holdings-axis companion of --drift; the item-set sieve "
        "selects the items `scrolls list --fidelity` enumerates, then their whole "
        "ledger travels (e.g. --fidelity full to back up only the custody record "
        "of holdings you can re-derive offline). ANDs with --drift",
    )
    export_events_parser.add_argument(
        "--drift",
        choices=("verified", "unverified", "drifted", "rotted", "error"),
        default=None,
        help="Only the custody history of items *currently* at this drift posture "
        "(from the verify ledger) — the ledger-claim-axis companion of --fidelity; "
        "the item-set sieve selects the items `scrolls list --drift` enumerates, "
        "then their whole ledger travels, not just the matching event rows (e.g. "
        "--drift drifted to ship the full custody history of the moved items for a "
        "recapture handoff). ANDs with --fidelity",
    )
    export_events_parser.add_argument(
        "--content-duplicate",
        dest="content_duplicate",
        action="store_true",
        help="Only the custody history of items the library holds a byte-identical "
        "copy of under another id — the content-duplicate set (the content-identity "
        "custody shape); the item-set sieve selects the items `scrolls list "
        "--content-duplicate` enumerates, then their whole ledger travels, so a "
        "recipient deduping the redundant copies gets the full proof of when each "
        "was verified. A boolean flag (yes/no per item), report-only (never a merge). "
        "The sibling may live in another source (whole-library scope), so ANDed with "
        "--source it ships that source's items with a byte-identical sibling "
        "anywhere. ANDs with --fidelity/--drift; composes with --since",
    )
    export_archive_parser = export_sub.add_parser(
        "archive",
        help="Export the prior-content archive (ADR 0106) as a lossless JSONL "
        "stream (to stdout) — the recovery-store sibling of `export events`",
    )
    export_archive_parser.add_argument(
        "--id",
        default=None,
        help="Only the archived prior captures of one item id (or its URL); the "
        "whole library's recovery store otherwise",
    )
    export_archive_parser.add_argument(
        "--source",
        default=None,
        help="Only the archived priors of one source's held items (e.g. web, "
        "arxiv) — the source-scoped recovery backup, the `export events --source` "
        "analogue; resolves the source to its held item ids, then their whole "
        "recovery store travels. Mutually exclusive with --id (one names a source, "
        "the other an item); ANDs with --fidelity/--drift",
    )
    export_archive_parser.add_argument(
        "--fidelity",
        choices=("full", "partial", "reference"),
        default=None,
        help="Only the recovery store of items held at this fidelity tier "
        "(ADR 0097) — the holdings-axis companion of --drift; the item-set sieve "
        "selects the items `scrolls list --fidelity` enumerates, then their whole "
        "archived history travels (e.g. --fidelity full to back up only the "
        "recovery history of holdings you can re-derive offline). ANDs with "
        "--drift/--source; mutually exclusive with --id",
    )
    export_archive_parser.add_argument(
        "--drift",
        choices=("verified", "unverified", "drifted", "rotted", "error"),
        default=None,
        help="Only the recovery store of items *currently* at this drift posture "
        "(from the verify ledger) — the ledger-claim-axis companion of --fidelity; "
        "the item-set sieve selects the items `scrolls list --drift` enumerates, "
        "then their whole archived history travels (e.g. --drift drifted to back up "
        "the recoverable priors of the moved items for a recapture handoff). ANDs "
        "with --fidelity/--source; mutually exclusive with --id",
    )
    export_archive_parser.add_argument(
        "--content-duplicate",
        dest="content_duplicate",
        action="store_true",
        help="Only the recovery store of items the library holds a byte-identical "
        "copy of under another id — the content-duplicate set (the content-identity "
        "custody shape); the item-set sieve selects the items `scrolls list "
        "--content-duplicate` enumerates, then their whole archived history travels. "
        "A boolean flag (yes/no per item), report-only (never a merge). The sibling "
        "may live in another source (whole-library scope), so ANDed with --source it "
        "ships that source's items with a byte-identical sibling anywhere. ANDs with "
        "--fidelity/--drift/--source; mutually exclusive with --id; composes with "
        "--since",
    )
    export_archive_parser.add_argument(
        "--since",
        default=None,
        help="Only priors archived at/after this ISO-8601 boundary (e.g. "
        "2026-06-15) — the incremental recovery backup since the last sweep, the "
        "`export events --since` analogue. An orthogonal *time* window on "
        "archived_at, not an item-set sieve: composes with --id/--source/"
        "--fidelity/--drift; re-importing the overlapping union stays idempotent "
        "(the archive dedups by (item_id, prior_hash))",
    )
    export_bundle_parser = export_sub.add_parser(
        "bundle",
        help="Export a scoped, self-contained custody bundle for a query "
        "(briefing + lossless block, to stdout)",
    )
    export_bundle_parser.add_argument(
        "query", help="Free-text query; tokens are AND-ed (as `scrolls context`)"
    )
    export_bundle_parser.add_argument(
        "--source", default=None, help="Only scrolls from one source, e.g. web, arxiv"
    )
    export_bundle_parser.add_argument(
        "--category",
        default=None,
        help="Only scrolls with this category; an empty value selects "
        "unclassified items",
    )
    export_bundle_parser.add_argument(
        "--stage",
        choices=("detected", "fetched", "rendered"),
        default=None,
        help="Only scrolls at one pipeline stage",
    )
    export_bundle_parser.add_argument(
        "--tag", default=None, help="Only scrolls carrying this tag (case-insensitive)"
    )
    export_bundle_parser.add_argument(
        "--concept",
        default=None,
        help="Only scrolls carrying this concept (matched by slug)",
    )
    export_bundle_parser.add_argument(
        "--fidelity",
        choices=("full", "partial", "reference"),
        default=None,
        help="Only scrolls the library holds at this custody-fidelity tier "
        "(ADR 0097) — the holdings-axis companion of --drift; the briefing and "
        "lossless block carry exactly the kept tier (e.g. --fidelity full to "
        "share only the sources you can re-derive offline). ANDs with --drift",
    )
    export_bundle_parser.add_argument(
        "--drift",
        choices=("verified", "unverified", "drifted", "rotted", "error"),
        default=None,
        help="Only scrolls at this custody drift posture (from the verify "
        "ledger) — the ledger-claim-axis companion of --fidelity; the briefing "
        "and lossless block carry exactly the kept posture (e.g. --drift drifted "
        "to export only the sources that have moved, for a recapture handoff). "
        "ANDs with --fidelity",
    )
    export_bundle_parser.add_argument(
        "--strength",
        choices=("strong", "moderate", "weak"),
        default=None,
        help="Only scrolls whose query lands at or above this rank-strength band "
        "— strong (title), moderate (title or summary), weak (any field); the "
        "rank-axis companion of --fidelity/--drift. The bundle carries no cap, so "
        "the sieve narrows the complete matched set (e.g. --strength strong to "
        "share only the matches whose query is in the title). The rendered "
        "_Strength:_ headline describes the kept set. ANDs with --fidelity/--drift",
    )
    export_bundle_parser.add_argument(
        "--content-duplicate",
        dest="content_duplicate",
        action="store_true",
        help="Only scrolls the library holds a byte-identical copy of under another "
        "id — the content-duplicate set (the content-identity custody shape); the "
        "briefing and lossless block carry exactly the redundant holdings, so a "
        "recipient can decide what to dedup. A boolean flag (yes/no per item), "
        "report-only (never a merge). The sibling may live in another source "
        "(whole-library scope), so ANDed with --source it ships that source's items "
        "with a byte-identical sibling anywhere. ANDs with --fidelity/--drift/"
        "--strength",
    )
    export_bundle_parser.add_argument(
        "--format",
        choices=("markdown", "html"),
        default="markdown",
        help="markdown (default): the canonical, lossless, re-importable bundle. "
        "html: a self-contained, browser-readable briefing (export-only — the "
        "Markdown form is the re-import unit)",
    )
    export_bundle_parser.add_argument(
        "--with-archive",
        action="store_true",
        help="Also carry the in-scope items' prior-content archive (ADR 0106) — "
        "the recoverable captures an `import … --accept-incoming` superseded — in a "
        "third fenced block, so 'take it with me' includes the recovery store and "
        "`scrolls archive show` works on the rebuilt library. Opt-in: the bundle "
        "stays lean by default (the `superseded` event already travels documenting "
        "that an adoption happened); `import bundle` restores any archive block it "
        "finds. The whole-library JSONL sibling is `scrolls export archive`",
    )

    ingest_parser = subparsers.add_parser(
        "ingest", help="Register, fetch, and render a URL in one step (JSON output)"
    )
    ingest_parser.add_argument("url", help="URL to ingest")

    subparsers.add_parser("init", help="Create the library skeleton (idempotent)")
    kb_parser = subparsers.add_parser(
        "kb", help="Compile the interlinked library pages (JSON output)"
    )
    kb_parser.add_argument(
        "--engine",
        choices=("deterministic", "llm"),
        default=None,
        help="deterministic (default): compile pages from stored data only. "
        "llm: first synthesize lead summaries for concept pages with 2+ "
        "scrolls — incremental, unchanged concepts cost nothing — then "
        "compile (needs ANTHROPIC_API_KEY; model overridable via "
        "SCROLLS_LLM_MODEL)",
    )
    kb_parser.add_argument(
        "--batch",
        action="store_true",
        help="Synthesize every concept summary in one Message Batches "
        "submission (--engine llm only): half the per-token price, but the "
        "command waits for the batch to finish — typically minutes",
    )
    kb_parser.add_argument(
        "--stale",
        action="store_true",
        help="Re-synthesize only the concept summaries `scrolls doctor` reports "
        "in custody.summaries.stale — members changed since synthesis — "
        "refreshing the summary and its members fingerprint to the live members "
        "(implies --engine llm; never-summarized concepts are left for a full "
        "--engine llm run)",
    )
    kb_parser.add_argument(
        "--source",
        default=None,
        help="Narrow --stale to one source's stale summaries, e.g. web, arxiv "
        "(the concepts that source participates in, doctor's "
        "custody.summaries.by_source[<source>]) — the summary-axis counterpart "
        "of `classify --stale --source`; requires --stale",
    )
    list_parser = subparsers.add_parser(
        "list", help="List library items (JSON output)"
    )
    list_parser.add_argument(
        "--source", default=None, help="Only items from one source, e.g. web, arxiv"
    )
    list_parser.add_argument(
        "--stage",
        choices=("detected", "fetched", "rendered"),
        default=None,
        help="Only items at one pipeline stage",
    )
    list_parser.add_argument(
        "--category",
        default=None,
        help="Only items with this category; an empty value selects "
        "unclassified items",
    )
    list_parser.add_argument(
        "--tag", default=None, help="Only items carrying this tag (case-insensitive)"
    )
    list_parser.add_argument(
        "--concept",
        default=None,
        help="Only items carrying this concept (matched by slug)",
    )
    list_parser.add_argument(
        "--fidelity",
        choices=("full", "partial", "reference"),
        default=None,
        help="Only items held at this custody-fidelity tier (ADR 0097) — the "
        "holdings-axis companion of --drift; the rows returned total `scrolls "
        "facets fidelity`'s count for that tier",
    )
    list_parser.add_argument(
        "--drift",
        choices=("verified", "unverified", "drifted", "rotted", "error"),
        default=None,
        help="Only items at this custody drift posture (from the verify "
        "ledger); the rows returned total `scrolls facets drift`'s count "
        "for that posture",
    )
    list_parser.add_argument(
        "--stale-before",
        dest="stale_before",
        default=None,
        metavar="ISO",
        help="Only items whose newest verify-ledger verdict predates this "
        "ISO-8601 boundary — the stale set; the read-side companion of "
        "`scrolls verify --stale-before` (the rows it shows are exactly the "
        "set that recheck would re-capture). A never-checked item is "
        "trivially stale, so it is included",
    )
    list_parser.add_argument(
        "--stale-classification",
        dest="stale_classification",
        action="store_true",
        help="Only items whose rules-classified category the live ruleset would "
        "no longer reproduce — the stale-enrichment set; the read-side companion "
        "of `scrolls classify --stale` (the rows it returns are exactly the items "
        "that refresh acts on, and total `scrolls doctor`'s "
        "custody.enrichment.stale). Composes with --source to drill one source's "
        "refresh debt",
    )
    list_parser.add_argument(
        "--stale-summary",
        dest="stale_summary",
        action="store_true",
        help="Only items that belong to a concept whose stored LLM summary the "
        "live members would no longer reproduce — the stale-summary set; the "
        "read-side companion of `scrolls kb --stale` (the members a refresh's "
        "clusters span). Composes with --source to drill one source's members of "
        "the stale clusters",
    )
    list_parser.add_argument(
        "--content-duplicate",
        dest="content_duplicate",
        action="store_true",
        help="Only items the library holds a byte-identical copy of under another "
        "id — the content-duplicate set (the same bytes saved twice, a mirror or "
        "cross-post; the content-identity custody shape). The browse-axis companion "
        "of `scrolls show`'s content_duplicate_ids; the rows returned are exactly "
        "the held members of `scrolls doctor`'s custody.content_duplicates groups. "
        "A boolean flag (yes/no per item), not a value filter; report-only, never a "
        "merge. The sibling may live in another source, so ANDed with --source it "
        "returns that source's items with a byte-identical sibling anywhere. ANDs "
        "with --fidelity/--drift",
    )
    list_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Return at most N items, oldest saved first; default is "
        "uncapped (every item in scope). With --stats, a capped listing "
        "reports whether it was truncated",
    )
    list_parser.add_argument(
        "--stats",
        action="store_true",
        help="Wrap the array in a scope-honest {scope, stats, results} "
        "envelope: the filters honored, how many matched in scope, and "
        "whether the result was truncated below --limit",
    )

    maintain_parser = subparsers.add_parser(
        "maintain",
        help="Run one scheduled custody-maintenance pass — recheck, regenerate "
        "views, audit, and report the custody delta since the last run "
        "(JSON output)",
    )
    maintain_group = maintain_parser.add_mutually_exclusive_group()
    maintain_group.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Bound the drift recheck to N held items this run (coverage-first: "
        "never-checked, then stalest); paces both the default stale recheck and "
        "--all",
    )
    maintain_parser.add_argument(
        "--all",
        dest="recheck_all",
        action="store_true",
        help="Recheck every held item with a captured hash, not just the stale "
        "set since the last run — the whole-library recheck (composes with "
        "--limit; conflicts with --no-recheck / --history)",
    )
    maintain_group.add_argument(
        "--no-recheck",
        dest="recheck",
        action="store_false",
        help="Skip the live re-capture edge entirely — a fully offline pass that "
        "regenerates views and audits without touching any source",
    )
    maintain_group.add_argument(
        "--history",
        nargs="?",
        type=int,
        const=DEFAULT_HISTORY_LIMIT,
        default=None,
        metavar="N",
        help="Print the last N recorded maintenance runs (default "
        f"{DEFAULT_HISTORY_LIMIT}) as a JSON array — the custody trajectory over "
        "time — instead of running a pass; read-only, never runs maintenance",
    )
    maintain_parser.add_argument(
        "--trend",
        action="store_true",
        help="With --history: wrap the runs in a {trend, runs} envelope whose "
        "trend distils the window's net score/drift movement into one posture "
        "(improving / holding / regressing); requires --history",
    )
    maintain_parser.add_argument(
        "--source",
        default=None,
        metavar="S",
        help="Scope the pass to one source's held items — the scheduled-"
        "maintenance counterpart of doctor --source / verify --source. The "
        "recheck, audit, by_source, and headline narrow to <S>; view "
        "regeneration stays whole-library. A scoped pass is a focused triage "
        "action: it records per-item drift events but never updates the whole-"
        "library trend baseline, so its delta is null (composes with "
        "--all/--limit/--no-recheck; conflicts with --history)",
    )
    maintain_parser.add_argument(
        "--fidelity",
        choices=("full", "partial", "reference"),
        default=None,
        help="Scope the pass to one custody-fidelity holdings tier (ADR 0097) — "
        "the scheduled-maintenance act twin of verify --fidelity, so a worker can "
        "maintain just its full-fidelity holdings. Only the recheck narrows to the "
        "tier (the verify --fidelity held, hash-bearing subset); the audit and view "
        "regeneration stay whole-library. Like --source the pass is non-persisting "
        "(records drift events, never the trend baseline, so its delta is null). "
        "Composes with --all/--limit/--no-recheck; conflicts with --source (one "
        "scope axis per pass) and --history",
    )

    subparsers.add_parser(
        "mcp",
        help="Serve the library to agents over the Model Context Protocol (stdio)",
    )

    md_parser = subparsers.add_parser(
        "md", help="Render fetched items as Markdown scrolls (JSON output)"
    )
    md_parser.add_argument(
        "id",
        nargs="?",
        help="Render one item by id or URL, re-rendering even if already rendered; "
        "default is every item at stage 'fetched'",
    )
    media_parser = subparsers.add_parser(
        "media",
        help="Download items' media references into media/ (JSON output)",
    )
    media_parser.add_argument(
        "id",
        nargs="?",
        help="Capture one item's media by id or URL, re-downloading even if captured; "
        "default is every item with uncaptured media references",
    )

    subparsers.add_parser("paths", help="Print the library layout (JSON output)")

    reconcile_parser = subparsers.add_parser(
        "reconcile",
        help="Resolve a recorded import conflict — affirm the held copy (JSON output)",
    )
    reconcile_parser.add_argument(
        "id", help="Item id (e.g. web:demo), or the item's URL, carrying the conflict"
    )
    reconcile_parser.add_argument(
        "--keep-held",
        dest="keep_held",
        action="store_true",
        help="Affirm the held copy as authoritative, recording the conflict as "
        "resolved-in-favor-of-held — the held copy is never overwritten and the "
        "original conflict stays on the `history` timeline. The only resolution "
        "implemented; --accept-incoming (adopt the peer's capture) is deferred — "
        "the incoming content is not retained, only its hash (ADR 0105)",
    )
    reconcile_parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Predict the resolution without recording it (writes nothing) — the "
        "same decision payload the live run would emit, plus dry_run: true",
    )

    archive_parser = subparsers.add_parser(
        "archive",
        help="Inspect the prior-content archive — captures superseded by "
        "accept-incoming (JSON output)",
    )
    archive_sub = archive_parser.add_subparsers(dest="archive_command", required=True)
    archive_list_parser = archive_sub.add_parser(
        "list",
        help="List archived prior captures (newest first), the recovery index",
    )
    archive_list_parser.add_argument(
        "--id",
        dest="item_id",
        default=None,
        help="Only the archived prior captures of one item id (or its URL)",
    )
    archive_show_parser = archive_sub.add_parser(
        "show",
        help="Emit one item's latest archived prior capture as a re-importable "
        "JSONL line (to stdout)",
    )
    archive_show_parser.add_argument(
        "id", help="Item id (e.g. web:demo), or the item's URL, with an archived prior"
    )
    archive_show_parser.add_argument(
        "--all",
        action="store_true",
        dest="all_history",
        help="Emit every archived prior capture for the id (newest first) as a JSONL "
        "stream, not just the latest — the full recoverable history",
    )
    archive_restore_parser = archive_sub.add_parser(
        "restore",
        help="Restore a specific archived prior in place (accept-incoming) — "
        "restore-by-version, default the latest; the displaced copy is itself "
        "archived (JSON output)",
    )
    archive_restore_parser.add_argument(
        "id", help="Item id (e.g. web:demo), or the item's URL, with an archived prior"
    )
    archive_restore_parser.add_argument(
        "--hash",
        dest="prior_hash",
        default=None,
        metavar="H",
        help="Restore the archived prior with this content hash (the `archive list` "
        "prior_hash) — a specific version, not just the latest",
    )
    archive_restore_parser.add_argument(
        "--at",
        dest="at",
        default=None,
        metavar="ISO",
        help="Restore the newest prior archived at or before this ISO-8601 timestamp "
        "(date-only ok → that day's UTC midnight) — the version held as of a point "
        "in time. At most one of --hash/--at; default is the latest archived prior",
    )
    archive_restore_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Predict the restore (the same decision the live run emits, plus "
        "dry_run: true) and write nothing — the preview-never-drifts discipline",
    )
    archive_diff_parser = archive_sub.add_parser(
        "diff",
        help="Compare the held copy against a selected archived prior — the "
        "decide-before-you-restore read (no write; JSON output)",
    )
    archive_diff_parser.add_argument(
        "id", help="Item id (e.g. web:demo), or the item's URL, with an archived prior"
    )
    archive_diff_parser.add_argument(
        "--hash",
        dest="prior_hash",
        default=None,
        metavar="H",
        help="Compare against the archived prior with this content hash (the "
        "`archive list` prior_hash) — a specific version, not just the latest",
    )
    archive_diff_parser.add_argument(
        "--at",
        dest="at",
        default=None,
        metavar="ISO",
        help="Compare against the newest prior archived at or before this ISO-8601 "
        "timestamp (date-only ok → that day's UTC midnight) — the version held as of "
        "a point in time. At most one of --hash/--at; default is the latest prior",
    )
    archive_prune_parser = archive_sub.add_parser(
        "prune",
        help="Drop archived prior captures by a retention policy — bounds the "
        "append-only recovery store (report-only until --apply; JSON output)",
    )
    archive_prune_parser.add_argument(
        "--before",
        dest="before",
        default=None,
        metavar="ISO",
        help="Drop priors archived strictly before this ISO-8601 timestamp "
        "(date-only ok → that day's UTC midnight) — the time-based policy; may "
        "drop an item's latest prior",
    )
    archive_prune_parser.add_argument(
        "--keep",
        dest="keep",
        type=int,
        default=None,
        metavar="N",
        help="Per item, keep the most recent N priors and drop the rest (N>=1, so "
        "`archive show` still recovers the latest) — the count-based policy. "
        "Exactly one of --before/--keep is required",
    )
    archive_prune_parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete the drop set; default is report-only — predict what "
        "would be dropped and write nothing (the dry-run discipline)",
    )

    related_parser = subparsers.add_parser(
        "related", help="Find items related to one item (JSON output)"
    )
    related_parser.add_argument("id", help="Item id (e.g. x:1111), or the item's URL")
    related_parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_RELATED_LIMIT,
        help=f"Maximum hits to return (default {DEFAULT_RELATED_LIMIT})",
    )
    related_parser.add_argument(
        "--fidelity",
        choices=("full", "partial", "reference"),
        default=None,
        help="Only neighbours the library holds at this custody-fidelity tier "
        "(ADR 0097) — the relationship-surface twin of `scrolls list "
        "--fidelity` / `search --fidelity`; the sieve runs before --limit, so "
        "you get the top neighbours *at that tier* (e.g. the full-fidelity ones "
        "you can re-derive offline)",
    )
    related_parser.add_argument(
        "--drift",
        choices=("verified", "unverified", "drifted", "rotted", "error"),
        default=None,
        help="Only neighbours at this custody drift posture (from the verify "
        "ledger) — the ledger-claim-axis companion of --fidelity; the sieve runs "
        "before --limit, so you get the top neighbours *at that posture* (e.g. "
        "--drift drifted to see which neighbours have moved). ANDs with --fidelity",
    )
    related_parser.add_argument(
        "--strength",
        choices=("strong", "moderate", "weak"),
        default=None,
        help="Only neighbours related at this strength band or stronger "
        "(roadmap H324) — the relationship-surface twin of `search --strength`: "
        "`strong` keeps only same-work/link (identity/citation) bonds, `moderate` "
        "adds shared concepts/tags, `weak` keeps every neighbour. Threshold (at or "
        "above); the sieve runs before --limit, so you get the top neighbours *at "
        "that strength*. ANDs with --fidelity/--drift",
    )
    related_parser.add_argument(
        "--content-duplicate",
        action="store_true",
        help="Only neighbours the library holds a byte-identical copy of under "
        "another id (roadmap H350) — the relationship-surface twin of `scrolls list "
        "--content-duplicate` / `search --content-duplicate`: keep the neighbours "
        "whose own content is also held under some other id (their "
        "`content_duplicate_ids` is non-empty). Whole-library sibling scope (the twin "
        "may live in another source, or be the anchor itself); the sieve runs before "
        "--limit; report-only. ANDs with --fidelity/--drift/--strength",
    )
    related_parser.add_argument(
        "--stats",
        action="store_true",
        help="Wrap the array in a scope-honest {scope, stats, results} "
        "envelope: the anchor item and limit honored, how many items relate "
        "in all, and whether the result was truncated below --limit",
    )

    rm_parser = subparsers.add_parser(
        "rm", help="Remove items and the files they own (JSON output)"
    )
    rm_parser.add_argument(
        "refs",
        nargs="+",
        metavar="id-or-url",
        help="Item id, or the item's URL — resolved to the same id "
        "`scrolls add` would mint, so the URL that saved an item removes it",
    )

    search_parser = subparsers.add_parser(
        "search", help="Full-text search over items (JSON output)"
    )
    search_parser.add_argument("query", help="Free-text query; tokens are AND-ed")
    search_parser.add_argument(
        "--limit", type=int, default=20, help="Maximum hits to return (default 20)"
    )
    search_parser.add_argument(
        "--source", default=None, help="Only hits from one source, e.g. web, arxiv"
    )
    search_parser.add_argument(
        "--category",
        default=None,
        help="Only hits with this category; an empty value selects "
        "unclassified items",
    )
    search_parser.add_argument(
        "--stage",
        choices=("detected", "fetched", "rendered"),
        default=None,
        help="Only hits at one pipeline stage",
    )
    search_parser.add_argument(
        "--tag", default=None, help="Only hits carrying this tag (case-insensitive)"
    )
    search_parser.add_argument(
        "--concept",
        default=None,
        help="Only hits carrying this concept (matched by slug)",
    )
    search_parser.add_argument(
        "--fidelity",
        choices=("full", "partial", "reference"),
        default=None,
        help="Only hits the library holds at this custody-fidelity tier (ADR "
        "0097) — the holdings-axis companion of --source/--stage; ANDed into the "
        "ranked match before --limit, so it returns the top hits at that tier",
    )
    search_parser.add_argument(
        "--drift",
        choices=("verified", "unverified", "drifted", "rotted", "error"),
        default=None,
        help="Only hits at this custody drift posture (from the verify ledger) — "
        "the ledger-claim-axis companion of --fidelity; ANDed into the ranked "
        "match before --limit, so it returns the top hits at that posture",
    )
    search_parser.add_argument(
        "--strength",
        choices=("strong", "moderate", "weak"),
        default=None,
        help="Only hits whose query lands at or above this rank-strength band — "
        "strong (title), moderate (title or summary), weak (any field); the "
        "rank-axis companion of --fidelity/--drift, ANDed into the ranked match "
        "before --limit, so it returns the top hits at that strength",
    )
    search_parser.add_argument(
        "--content-duplicate",
        dest="content_duplicate",
        action="store_true",
        help="Only hits the library holds a byte-identical copy of under another "
        "id — the content-duplicate set (the content-identity custody shape); the "
        "browse-axis companion of `scrolls list --content-duplicate` and `show`'s "
        "content_duplicate_ids. A boolean flag, report-only (never a merge), ANDed "
        "into the ranked match before --limit. The sibling may live in another "
        "source (a content group spans the query scope), so it returns the top "
        "matches with a byte-identical sibling anywhere held. ANDs with "
        "--fidelity/--drift/--strength",
    )
    search_parser.add_argument(
        "--stats",
        action="store_true",
        help="Wrap the array in a scope-honest {scope, stats, results} "
        "envelope: the query and filters honored, how many matched in "
        "scope, and whether the ranked result was truncated below --limit",
    )

    set_parser = subparsers.add_parser(
        "set", help="Set classification fields on one item by hand (JSON output)"
    )
    set_parser.add_argument("id", help="Item id (e.g. wikipedia:en:SQLite), or the item's URL")
    set_parser.add_argument(
        "assignments",
        nargs="+",
        metavar="field=value",
        help="category=..., domain=..., tags=a,b, concepts=a,b; "
        "an empty value clears the field",
    )

    show_parser = subparsers.add_parser(
        "show", help="Print one item in full (JSON output)"
    )
    show_parser.add_argument("id", help="Item id (e.g. wikipedia:en:SQLite), or the item's URL")

    status_parser = subparsers.add_parser(
        "status", help="Report library state (JSON output)"
    )
    status_parser.add_argument(
        "--source",
        default=None,
        metavar="S",
        help="Scope the custody read to one source (e.g. web, arxiv) — the items "
        "counts, custody headline, and by_source map are that source's view "
        "(by_source collapses to {S: …}, attention is null). The status-surface "
        "counterpart of `doctor --source`; an unknown source is the empty headline",
    )

    sync_parser = subparsers.add_parser(
        "sync", help="Register new items from followed feeds (JSON output)"
    )
    sync_parser.add_argument(
        "id",
        nargs="?",
        help="Sync one subscription by id; default is every followed feed",
    )

    unfollow_parser = subparsers.add_parser(
        "unfollow", help="Remove a feed subscription (JSON output)"
    )
    unfollow_parser.add_argument(
        "id", help="Subscription id (from `scrolls follow`), or the feed URL"
    )

    verify_parser = subparsers.add_parser(
        "verify",
        help="Re-capture items and record drift/rot custody events (JSON output)",
    )
    verify_parser.add_argument(
        "id",
        nargs="?",
        help="Verify one item by id or URL; use --all for every held item with "
        "a captured content hash",
    )
    verify_parser.add_argument(
        "--all",
        dest="verify_all",
        action="store_true",
        help="Verify every item that has a captured content hash to diff against",
    )
    verify_parser.add_argument(
        "--unverified",
        action="store_true",
        help="Verify only held items the ledger has no verdict for — the "
        "`unverified` bucket doctor/facets/status report (oldest saved first)",
    )
    verify_parser.add_argument(
        "--stale-before",
        dest="stale_before",
        metavar="ISO",
        default=None,
        help="Verify only held items whose newest ledger verdict predates this "
        "ISO-8601 boundary (plus never-checked items) — the stale set since the "
        "last sweep (oldest saved first)",
    )
    verify_parser.add_argument(
        "--drift",
        choices=("verified", "unverified", "drifted", "rotted", "error"),
        default=None,
        help="Verify only held items currently at this custody drift posture — "
        "the set `scrolls list --drift` enumerates and `facets drift` counts "
        "(e.g. --drift drifted to re-confirm a changed source; oldest saved first)",
    )
    verify_parser.add_argument(
        "--source",
        default=None,
        metavar="S",
        help="Verify only held items from one source (e.g. web, arxiv) — the "
        "act-side of doctor/maintain's per-source custody breakdown, so a worker "
        "re-checks the weakest source without --all (oldest saved first)",
    )
    verify_parser.add_argument(
        "--fidelity",
        choices=("full", "partial", "reference"),
        default=None,
        help="Verify only held items at this custody-fidelity tier (ADR 0097) — "
        "the act-axis twin of `scrolls list --fidelity` / `search --fidelity` "
        "(the holdings axis), so a worker re-checks exactly its full-fidelity (or "
        "partial) holdings without --all. Like every batch mode it touches only "
        "rows carrying a content hash to diff, so the set is `list --fidelity "
        "<tier>`'s held, hash-bearing subset; a tier with no fingerprint "
        "(typically reference) is an honest empty no-op (oldest saved first)",
    )
    verify_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Attempt at most N re-captures this run "
        "(--all/--unverified/--stale-before/--drift/--source/--fidelity only), "
        "oldest saved first",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "add":
        return _cmd_add(args.url)
    if args.command == "agent":
        return _cmd_agent_install()
    if args.command == "classify":
        return _cmd_classify(args.id, args.engine, args.batch, args.stale, args.source)
    if args.command == "context":
        return _cmd_context(
            args.query,
            args.limit,
            args.source,
            args.category,
            args.stage,
            args.tag,
            args.concept,
            args.fidelity,
            args.drift,
            args.strength,
            args.content_duplicate,
            args.budget,
        )
    if args.command == "detect":
        return _cmd_detect(args.url)
    if args.command == "doctor":
        return _cmd_doctor(args.fix, args.source)
    if args.command == "facets":
        return _cmd_facets(
            args.field,
            args.limit,
            args.source,
            args.category,
            args.stage,
            args.tag,
            args.concept,
        )
    if args.command == "fetch":
        return _cmd_fetch(args.id, args.limit)
    if args.command == "graph":
        return _cmd_graph(args.include_all, args.content_duplicate)
    if args.command == "works":
        return _cmd_works(
            args.min_representations,
            args.ref,
            args.fidelity,
            args.drift,
            args.at_risk,
            args.content_duplicate,
        )
    if args.command == "follow":
        return _cmd_follow(args.url)
    if args.command == "history":
        return _cmd_history(args.id, args.limit, args.since, args.status)
    if args.command == "reconcile":
        return _cmd_reconcile(args.id, args.keep_held, args.dry_run)
    if args.command == "archive":
        if args.archive_command == "show":
            return _cmd_archive_show(args.id, args.all_history)
        if args.archive_command == "restore":
            return _cmd_archive_restore(
                args.id,
                prior_hash=args.prior_hash,
                at=args.at,
                dry_run=args.dry_run,
            )
        if args.archive_command == "diff":
            return _cmd_archive_diff(
                args.id,
                prior_hash=args.prior_hash,
                at=args.at,
            )
        if args.archive_command == "prune":
            return _cmd_archive_prune(args.before, args.keep, args.apply)
        return _cmd_archive_list(args.item_id)
    if args.command == "import":
        if args.import_command == "bookmarks":
            return _cmd_import_bookmarks(args.path)
        if args.import_command == "google-takeout":
            return _cmd_import_takeout(args.path)
        if args.import_command == "pocket":
            return _cmd_import_pocket(args.path)
        if args.import_command == "opml":
            return _cmd_import_opml(args.path)
        if args.import_command == "items":
            return _cmd_import_items(args.path, accept_incoming=args.accept_incoming)
        if args.import_command == "bundle":
            return _cmd_import_bundle(
                args.path,
                dry_run=args.dry_run,
                accept_incoming=args.accept_incoming,
            )
        if args.import_command == "events":
            return _cmd_import_events(args.path)
        if args.import_command == "archive":
            return _cmd_import_archive(args.path)
        return _cmd_import_fieldtheory(args.root)
    if args.command == "export":
        if args.export_command == "bookmarks":
            return _cmd_export_bookmarks(args.source, args.category, args.tag)
        if args.export_command == "items":
            return _cmd_export_items(
                args.source, args.category, args.tag, args.fidelity, args.drift,
                args.content_duplicate,
            )
        if args.export_command == "events":
            return _cmd_export_events(
                args.source,
                args.category,
                args.tag,
                args.since,
                args.fidelity,
                args.drift,
                args.content_duplicate,
            )
        if args.export_command == "archive":
            return _cmd_export_archive(
                args.id, args.source, args.fidelity, args.drift, args.since,
                args.content_duplicate,
            )
        if args.export_command == "bundle":
            return _cmd_export_bundle(
                args.query,
                args.source,
                args.category,
                args.stage,
                args.tag,
                args.concept,
                args.format,
                args.fidelity,
                args.drift,
                args.strength,
                args.with_archive,
                args.content_duplicate,
            )
        return _cmd_export_opml()
    if args.command == "ingest":
        return _cmd_ingest(args.url)
    if args.command == "init":
        return _cmd_init()
    if args.command == "kb":
        return _cmd_kb(args.engine, args.batch, args.stale, args.source)
    if args.command == "list":
        return _cmd_list(
            args.source,
            args.stage,
            args.category,
            args.tag,
            args.concept,
            args.fidelity,
            args.drift,
            args.stale_before,
            args.stale_classification,
            args.stale_summary,
            args.content_duplicate,
            args.limit,
            args.stats,
        )
    if args.command == "maintain":
        # `--all` forces a whole-library recheck; it composes with `--limit` (so
        # it lives outside the mutually-exclusive group) but conflicts with the
        # non-recheck modes — rejected here rather than silently ignored (the
        # `--trend requires --history` precedent).
        if args.recheck_all and (not args.recheck or args.history is not None):
            other = "--no-recheck" if not args.recheck else "--history"
            print(
                json.dumps({"error": f"--all rechecks every held item; it conflicts "
                            f"with {other}"}),
                file=sys.stderr,
            )
            return 2
        # `--source` and `--fidelity` are the two custody scope axes — one per pass
        # (roadmap H255): the source axis scopes the recheck *and* audit, the
        # fidelity axis only the recheck, so combining them is ambiguous. Rejected
        # here rather than silently honoring one (the `--all`/`--trend` precedent).
        if args.source is not None and args.fidelity is not None:
            print(
                json.dumps({"error": "--source and --fidelity are two scope axes; "
                            "choose one per maintenance pass"}),
                file=sys.stderr,
            )
            return 2
        # Either scope axis scopes a *pass*; `--history` is a read of recorded
        # passes — mutually exclusive, rejected here (both axes live outside the
        # group so they compose with --all/--limit/--no-recheck).
        scope_axis = "--source" if args.source is not None else "--fidelity"
        if (args.source is not None or args.fidelity is not None) and args.history is not None:
            print(
                json.dumps({"error": f"{scope_axis} scopes a maintenance pass; it "
                            "conflicts with --history (a read, not a pass)"}),
                file=sys.stderr,
            )
            return 2
        if args.history is not None:
            return _cmd_maintain_history(args.history, args.trend)
        if args.trend:
            print(
                json.dumps({"error": "--trend requires --history"}), file=sys.stderr
            )
            return 2
        return _cmd_maintain(
            args.recheck, args.recheck_all, args.limit, args.source, args.fidelity
        )
    if args.command == "mcp":
        return _cmd_mcp()
    if args.command == "md":
        return _cmd_md(args.id)
    if args.command == "media":
        return _cmd_media(args.id)
    if args.command == "paths":
        return _cmd_paths()
    if args.command == "related":
        return _cmd_related(
            args.id, args.limit, args.stats, args.fidelity, args.drift, args.strength,
            args.content_duplicate,
        )
    if args.command == "rm":
        return _cmd_rm(args.refs)
    if args.command == "search":
        return _cmd_search(
            args.query,
            args.limit,
            args.source,
            args.category,
            args.stage,
            args.tag,
            args.concept,
            args.stats,
            args.fidelity,
            args.drift,
            args.strength,
            args.content_duplicate,
        )
    if args.command == "set":
        return _cmd_set(args.id, args.assignments)
    if args.command == "show":
        return _cmd_show(args.id)
    if args.command == "status":
        return _cmd_status(args.source)
    if args.command == "sync":
        return _cmd_sync(args.id)
    if args.command == "unfollow":
        return _cmd_unfollow(args.id)
    if args.command == "verify":
        return _cmd_verify(
            args.id, args.verify_all, args.unverified, args.limit, args.stale_before,
            args.drift, args.source, args.fidelity,
        )
    return 2  # pragma: no cover - argparse enforces a valid command


def _cmd_init() -> int:
    paths = get_paths()
    existed_before = ensure_library(paths)
    print(json.dumps({"root": str(paths.root), "created": not existed_before}))
    return 0


def _cmd_add(url: str) -> int:
    try:
        _, item, created = register_url(url)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "id": item.id,
                "source": item.source,
                "source_id": item.source_id,
                "url": item.url,
                "stage": item.stage,
                "created": created,
            }
        )
    )
    return 0


def _cmd_ingest(url: str) -> int:
    try:
        payload = ingest_url(url)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(payload))
    return 1 if "error" in payload else 0


def _cmd_doctor(fix: bool, source: str | None = None) -> int:
    paths = get_paths()
    # `source` scopes the whole audit to one source's held items (roadmap H162):
    # the audit-side of `verify --source`/`classify --stale --source`. Every block
    # is that source's view; orphan/FTS (not source-attributable) are skipped.
    payload = run_doctor(paths, fix=fix, source=source)
    print(json.dumps(payload))
    # healthy or fully repaired → 0; any drift left behind → 1
    return 1 if payload["issues"] > payload["fixed"] else 0


def _cmd_maintain(
    recheck: bool, recheck_all: bool, limit: int | None, source: str | None = None,
    fidelity: str | None = None,
) -> int:
    """One scheduled custody-maintenance pass (roadmap H22/H23/H34/H83/H165/H255).

    The dogfood flow's recurring sibling, composed entirely from surfaces that
    already ship: *recheck* the live edge (`verify`, bounded by `--limit`, behind
    the `live_recapture` seam so it scripts offline), *regenerate* views
    (`compile_kb` — the deterministic compile, never an LLM re-synthesis), then
    *audit* once with `run_doctor` to read the post-maintenance custody picture,
    and report the **custody delta** against the snapshot the last run recorded.

    The recheck is **stale-bounded by default** (roadmap H83): it re-verifies
    only the held items not seen since the last recorded run — the boundary is
    that run's `recorded_at` (`last_run_boundary`), so a scheduled pass does the
    *new* work, not the whole library. `--all` ignores the boundary and rechecks
    everything (the old behavior); a first run (no baseline) has no boundary and
    so also rechecks everything. The same `previous` snapshot is both the
    staleness boundary and the delta baseline, loaded once.

    `source` scopes the pass to one source's held items (roadmap H165) — the
    scheduled-maintenance counterpart of `doctor --source` (H162) and the act-side
    `verify --source` (H125), reusing the **same** `run_doctor(source=)` pre-filter
    so the scoped `custody`/`by_source`/`headline` converge with `doctor --source S`
    / `status --source S` by construction (H169). Under `--source`:

    - the **recheck** targets only <S>'s held, hash-bearing items (the
      `verify --source S` set, still stale-bounded / `--all`-able);
    - the **audit** is scoped (`run_doctor(source=S)`), so every reported block is
      the one-source view, and `by_source` collapses to the singleton ``{S: …}``
      (so `attention` is naturally `null` — a single source has nothing to flag
      across, the `weakest_source` `len < 2` gate);
    - **view regeneration stays whole-library** — `compile_kb` is a deterministic
      global recompile, not a per-source one (decision: only recheck + audit + delta
      narrow);
    - the pass is **non-persisting**: it records per-item drift events (the next
      whole-library pass folds them into the trend) but never writes the single
      whole-library snapshot/log baseline — a scoped pass is a focused triage
      action, not a trend checkpoint, and must not clobber the one baseline with a
      one-source slice (decision: no per-source storage shape, ADR 0082). Because
      no per-source baseline exists to diff against (the stored snapshot drops
      `by_source`), the scoped `delta` is `null` — the honest-absence posture; the
      per-pass `recheck` movement is the signal, and the whole-library `maintain`
      owns the cross-run trend.

    `fidelity` scopes the pass to one custody-fidelity *holdings* tier (roadmap
    H255) — the scheduled-maintenance act twin of `verify --fidelity` (H252), so a
    worker can run "a maintenance pass over just my full-fidelity holdings". It is
    the holdings-axis sibling of `--source`, but narrows *less*: only the **recheck**
    targets the tier (the `verify --fidelity <tier>` held, hash-bearing subset), and
    the **audit/regeneration stay whole-library**. A fidelity tier spans sources, so
    `run_doctor`'s source semantics (the `by_source` singleton-collapse, the
    orphan/FTS skip) don't apply to it — scoping the audit is a separate, larger
    change deferred unless the recheck-only shape proves insufficient. The pass is
    still **non-persisting** (`delta` is `null`, no snapshot/log recorded): a
    partial-recheck pass is a focused triage, not a trend checkpoint, and must not
    stamp the trend as if it had rechecked the whole library. Closed vocabulary
    (argparse `choices`): a typo is exit 2, never a silently empty pass. Composes
    with `--all`/`--limit`/`--no-recheck`; conflicts with `--source` (one scope axis
    per pass) and `--history` (a read, not a pass).

    Report-only and idempotent (custody-vision §2.4): it records drift events and
    regenerates `library/` views, but never repairs index rows, reclassifies, or
    re-summarizes — `doctor --fix` / `classify --stale` / `kb --stale` stay the
    explicit, on-request mutations. The exit code mirrors `doctor`: nonzero only
    when structural `issues` remain (the operator should run `doctor --fix`);
    drift and stale enrichment/summaries are reported, never a failure. Under
    `--source` the exit reflects only <S>'s attributable findings (orphan/FTS are
    not source-attributable, so the scoped audit skips them, per `run_doctor`).
    """
    paths = get_paths()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Load the last run's snapshot once: it is both this run's delta baseline AND
    # (via its recorded_at) the staleness boundary the default recheck windows by.
    # A scoped pass reads the same whole-library boundary (it shares the staleness
    # window semantics) but never writes it back (see below).
    path = snapshot_path(paths)
    previous = load_snapshot(path)
    boundary = None if recheck_all else last_run_boundary(previous)

    # 1. RECHECK — the one live edge, bounded; records drift events, never
    #    touching the captures (ADR 0098). Skipped entirely with --no-recheck.
    #    `source` narrows the candidate set to that source's held items (H165);
    #    `fidelity` narrows it to one custody-fidelity tier (H255, the `verify
    #    --fidelity` set). The two scope axes are mutually exclusive (one per pass).
    if recheck:
        recheck_report = _recheck_held_items(
            paths, limit, now, boundary, source, fidelity
        )
    else:
        # --no-recheck skips the live edge, reporting coverage from a standalone
        # ledger read (roadmap H109) — the same offline shape every MCP pass uses.
        recheck_report = skipped_recheck_report(paths, source, fidelity)

    # 2-5. REGENERATE views, AUDIT, DELTA, record, and assemble the report — the
    #       shared composition `maintain.assemble_report` owns, run identically by
    #       the MCP `run_maintenance` act (roadmap H196). A whole-library pass
    #       records the snapshot/log baseline; a scoped pass keeps none (its delta
    #       is honestly `null`). The report carries the live-pass-only per-source
    #       breakdowns, the weakest-source `attention` flag, and the `suggested`
    #       on-request repairs the audit implies.
    result = assemble_report(
        paths, recheck_report=recheck_report, previous=previous, source=source,
        fidelity=fidelity, now=now
    )
    print(json.dumps(result))
    # nonzero only on structural drift the operator must address (mirrors doctor)
    return 1 if result["issues"] > 0 else 0


def _cmd_maintain_history(limit: int | None, trend: bool) -> int:
    """Print the recorded maintenance runs — the custody trajectory (H36/H46).

    The read-only counterpart to a maintenance pass: rather than the single
    `delta` vs the last run, it prints the last N runs' `{recorded_at, snapshot,
    delta}` so a worker or agent reads the score/drift trend over time, not one
    diff. Never runs a pass and never mutates the library. Honest absence: a
    library that has never run `maintain` (or no library at all) prints `[]`.

    With ``--trend`` (H46) the runs are wrapped in a ``{trend, runs}`` envelope
    whose `trend` distils the window's net score/drift movement into one posture
    — the opt-in-envelope pattern (like `search --stats`), so the bare array
    stays the default and the completeness contract's empty `[]` never regresses.
    """
    runs = read_log(log_path(get_paths()), limit)
    # Each shown run carries the same one-line custody headline (roadmap H103),
    # rendered fresh from its recorded snapshot at read time — so a pre-H103 log
    # entry renders one too (forward-compatible), and `compute_trend` (which reads
    # only `recorded_at`/`snapshot`) is unaffected.
    runs = [{**run, "headline": snapshot_headline(run.get("snapshot", {}))} for run in runs]
    if trend:
        print(json.dumps({"trend": compute_trend(runs), "runs": runs}))
    else:
        print(json.dumps(runs))
    return 0


def _recheck_held_items(
    paths: LibraryPaths, limit: int | None, now: str, boundary: str | None,
    source: str | None = None, fidelity: str | None = None,
) -> dict:
    """Bounded re-capture of held items carrying a baseline hash; record events.

    The same core `verify --all` runs (re-capture through the `live_recapture`
    seam, diff the hash, append a custody event), distilled to the counts
    `maintain` reports. Reads the module-level `live_recapture` so tests can
    script the network edge offline, exactly as `_cmd_verify` does.

    Stale-bounded by default (roadmap H83): when `boundary` is given (the last
    run's `recorded_at`), the recheck targets only the *stale* set —
    `items_checked_before`, the held items whose newest verdict predates the
    boundary plus the never-checked — so a scheduled pass re-verifies the new
    work, not the whole library. A `None` boundary rechecks every held item
    (`--all`, or a first run with no baseline). The reported `scope`/`since`
    disclose which window the pass used.

    `source` scopes the candidate set to one source's held items (roadmap H165) —
    the same item-intrinsic filter `verify --source` applies, composed with the
    staleness window: an unbounded scoped recheck targets exactly the
    `verify --source S` set (`list --source S`'s held, hash-bearing rows), the
    stale default a window over it. A source nothing is held for is the honest
    empty no-op (sources are open-ended, never a closed vocabulary).

    `fidelity` is the holdings-axis scope (roadmap H255) — the same item-intrinsic
    filter `verify --fidelity` applies (H252), folding the `get_fidelity` primitive
    the read surfaces count with (ADR 0097). Like every batch recheck it touches
    only hash-bearing rows, so the candidate set is `list --fidelity <tier>`'s held,
    *hash-bearing* subset (genuinely narrower than the listing: a full capture held
    by raw body alone carries no hash, so it lists `full` yet is skipped here), and
    a tier holding no fingerprint (typically `reference`) is an honest empty no-op.
    It composes with the same staleness window and `--limit`. The two scope axes
    never combine — one scope axis per pass, enforced at the CLI — so only one
    filter ever bites.

    Coverage-first ordering (roadmap H55): the targeted set is then ordered by
    `recheck_order` — never-checked items first, then already-verified
    oldest-verdict-first — so a ``--limit``-bounded pass spends its budget on new
    custody coverage instead of re-checking the same head every run. The stale
    filter and the order share the one `latest_events` read.
    """
    counts = {"skipped": False, "scope": "all", "since": None,
              "checked": 0, "unchanged": 0, "drifted": 0, "rotted": 0, "error": 0,
              "coverage": {"verified": 0, "total": 0}}
    if not paths.db_path.exists():
        return counts
    init_db(paths.db_path)  # ensure the ledger table exists before recording
    hash_bearing = [
        item for item in list_items(paths.db_path, source=source) if item.content_hash
    ]
    if fidelity is not None:
        hash_bearing = [item for item in hash_bearing if get_fidelity(item) == fidelity]
    verdicts = latest_events(paths.db_path)
    if boundary is not None:
        counts["scope"] = "stale"
        counts["since"] = boundary
        candidates = items_checked_before(hash_bearing, verdicts, boundary)
    else:
        candidates = hash_bearing
    items = recheck_order(candidates, verdicts)
    events = []
    for item in items:
        if limit is not None and counts["checked"] >= limit:
            break
        counts["checked"] += 1
        event = verify_item(item, live_recapture, now=now)
        events.append(event)
        counts[event.status] += 1
    record_events(paths.db_path, events)
    # Coverage post-recheck (roadmap H109): of the verifiable (hash-bearing) held
    # set, how many now carry a verdict — folding this pass's events into the one
    # `verdicts` read already taken (no second ledger read). So a single report
    # shows the H55 coverage-first progress, and `verified` agrees with the
    # post-maintenance doctor audit's `custody.drift.checked`.
    counts["coverage"] = recheck_coverage(
        hash_bearing, verdicts, {event.item_id for event in events}
    )
    return counts


def _cmd_mcp() -> int:
    # lazy: only `scrolls mcp` pays the SDK import (ADR 0014)
    from scrolls.mcp_server import run

    run()  # blocks serving stdio until the client disconnects
    return 0


def _cmd_follow(url: str | None) -> int:
    paths = get_paths()
    if url is None:
        subs = list_subscriptions(paths.db_path) if paths.db_path.exists() else []
        print(json.dumps([dataclasses.asdict(sub) for sub in subs]))
        return 0
    try:
        _, subscription, created = follow_feed(url)
    except (ValueError, FeedError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "id": subscription.id,
                "feed_url": subscription.feed_url,
                "title": subscription.title,
                "created": created,
            }
        )
    )
    return 0


def _cmd_unfollow(ref: str) -> int:
    paths = get_paths()
    try:
        # a URL is resolved to its subscription id the same way follow minted it
        sub_id = make_subscription_id(to_feed_url(ref)) if "://" in ref else ref
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    removed = remove_subscription(paths.db_path, sub_id) if paths.db_path.exists() else False
    if not removed:
        print(json.dumps({"error": f"no such subscription: {ref}"}), file=sys.stderr)
        return 1
    print(json.dumps({"id": sub_id, "removed": True}))
    return 0


def _cmd_sync(sub_id: str | None) -> int:
    paths = get_paths()
    if sub_id is not None:
        subscription = (
            get_subscription(paths.db_path, sub_id) if paths.db_path.exists() else None
        )
        if subscription is None:
            print(json.dumps({"error": f"no such subscription: {sub_id}"}), file=sys.stderr)
            return 1
        subscriptions = [subscription]
    else:
        subscriptions = (
            list_subscriptions(paths.db_path) if paths.db_path.exists() else []
        )

    payload = sync_many(paths.db_path, subscriptions)
    print(json.dumps(payload))
    return 1 if payload["failed"] else 0


def _cmd_import_fieldtheory(root: str | None) -> int:
    ft_root = Path(root).expanduser() if root else FIELDTHEORY_ROOT
    try:
        imported_items, failures = load_bookmarks(ft_root)
    except ImportSourceError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    paths = get_paths()
    ensure_library(paths)
    counts = {"imported": 0, "skipped": 0, "failed": len(failures)}
    for item in imported_items:
        # INSERT OR IGNORE: an existing item (earlier import, or a manual
        # `add`/user edit) is never overwritten — re-imports stay cheap
        if insert_item(paths.db_path, item):
            counts["imported"] += 1
        else:
            counts["skipped"] += 1

    # bulk imports can cover hundreds of bookmarks, so per-item success
    # entries are omitted; only line-level failures are detailed
    print(json.dumps({**counts, "failures": failures}))
    return 1 if counts["failed"] else 0


def _cmd_import_bookmarks(path: str) -> int:
    try:
        imported_items, stats = load_bookmark_export(Path(path).expanduser())
    except BookmarksSourceError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    paths = get_paths()
    ensure_library(paths)
    counts = {"imported": 0, "skipped": 0}
    for item in imported_items:
        # INSERT OR IGNORE: an existing item (earlier import, or a manual
        # `add`/user edit) is never overwritten — re-imports stay cheap
        if insert_item(paths.db_path, item):
            counts["imported"] += 1
        else:
            counts["skipped"] += 1

    # ignored entries (bookmarklets, place: smart folders) are normal
    # in real exports, so they never fail the run
    print(json.dumps({**counts, **stats}))
    return 0


def _cmd_import_takeout(path: str) -> int:
    try:
        imported_items, stats = load_watch_history(Path(path).expanduser())
    except TakeoutSourceError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    paths = get_paths()
    ensure_library(paths)
    counts = {"imported": 0, "skipped": 0}
    for item in imported_items:
        # INSERT OR IGNORE: an existing item (earlier import, or a manual
        # `add`/user edit) is never overwritten — re-imports stay cheap
        if insert_item(paths.db_path, item):
            counts["imported"] += 1
        else:
            counts["skipped"] += 1

    # ignored entries (ads, deleted videos, community posts) are normal
    # in every watch history, so they never fail the run
    print(json.dumps({**counts, **stats}))
    return 0


def _cmd_import_pocket(path: str) -> int:
    try:
        imported_items, stats = load_pocket_export(Path(path).expanduser())
    except PocketSourceError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    paths = get_paths()
    ensure_library(paths)
    counts = {"imported": 0, "skipped": 0}
    for item in imported_items:
        # INSERT OR IGNORE: an existing item (earlier import, or a manual
        # `add`/user edit) is never overwritten — re-imports stay cheap
        if insert_item(paths.db_path, item):
            counts["imported"] += 1
        else:
            counts["skipped"] += 1

    # ignored entries (bookmarklets, blank URLs) are normal in real exports,
    # so they never fail the run
    print(json.dumps({**counts, **stats}))
    return 0


def _cmd_import_opml(path: str) -> int:
    try:
        subscriptions, stats = load_opml_export(Path(path).expanduser())
    except OPMLSourceError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    paths = get_paths()
    ensure_library(paths)
    counts = {"imported": 0, "skipped": 0}
    for subscription in subscriptions:
        # INSERT OR IGNORE: an already-followed feed (earlier follow/import) is
        # never overwritten, so a re-import keeps its sync state and stays cheap
        if insert_subscription(paths.db_path, subscription):
            counts["imported"] += 1
        else:
            counts["skipped"] += 1

    # ignored outlines (non-http feeds, folders) are normal in real exports,
    # so they never fail the run; the first `scrolls sync` discovers entries
    print(json.dumps({**counts, **stats}))
    return 0


_MAX_CONFLICT_IDS = 5


def _merge_items(
    db_path: Path, items: list[ScrollItem], *, accept_incoming: bool = False
) -> tuple[dict[str, int], list[str], list[str]]:
    """Insert items custody-safely, partitioning each skip into unchanged vs conflict.

    The shared core of the **lossless** importers (`import items`, and the bundle
    import — the Scrolls-native pair whose rows carry a model-complete
    ``content_hash``, unlike the heterogeneous third-party imports). Every row goes
    through `merge_item` (INSERT OR IGNORE — the held copy is never overwritten),
    and the skip is classified: an identical re-import is ``unchanged`` (a true
    no-op), a same-id/different-``content_hash`` row is a ``conflict`` (the incoming
    copy disagrees with what we hold — surfaced, never an overwrite, custody vision
    §2.4). Returns ``(counts, conflicts, adopted)`` where ``counts`` is
    ``{imported, skipped, unchanged, conflict, adopted}`` with ``skipped ==
    unchanged + conflict`` by construction, ``conflicts`` is the sorted, deduped,
    **uncapped** distinct ids whose held copy diverged and was *kept* — the M2
    structured-completeness twin of the bounded `_warn_conflicts` stderr line — and
    ``adopted`` the sorted distinct ids whose held copy was *replaced* (accept mode).

    Each kept conflict is **recorded** as a custody event on the held item (roadmap
    H274): a divergence is no longer just a transient warning the next import
    re-detects from scratch — it joins the append-only ledger as a typed ``conflict``
    event (held vs incoming `content_hash`, stamped at import time), queryable on the
    per-item `scrolls history` timeline. It is a *distinct* provenance-of-divergence
    axis, not a verify verdict, so it never enters the drift posture (`latest_events`
    reads only the verify verdicts) — the M2 honesty that a peer disagreement is not
    evidence the live source moved. A clean import records nothing (`record_events`
    no-ops on the empty list); this is the live, writing path, so the read-only
    `_preview_merge_items` deliberately does **not** record.

    With ``accept_incoming`` (roadmap H278, ADR 0106), a divergence is *adopted*
    instead of merely surfaced: the held copy is replaced by the incoming one via
    `adopt_incoming` (which archives the prior capture first — recoverable, never
    destroyed), and a ``superseded`` event supersedes the open conflict. An adopted
    row counts under ``adopted`` (not ``skipped``/``conflict``), so the disposition
    buckets ``imported`` + ``unchanged`` + ``adopted`` total the input. Once adopted,
    a re-import is ``unchanged`` (the held copy now *is* the incoming) — the slice is
    idempotent by construction, no special-casing.
    """
    counts = {"imported": 0, "skipped": 0, "unchanged": 0, "conflict": 0, "adopted": 0}
    conflict_ids: set[str] = set()
    adopted_ids: set[str] = set()
    events: list[CustodyEvent] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for item in items:
        outcome = merge_item(db_path, item)
        if outcome == "imported":
            counts["imported"] += 1
        elif outcome == "conflict" and accept_incoming:
            # adopt the incoming capture (ADR 0106): archive the held (prior) copy,
            # replace the row with the incoming one, and record the supersession —
            # the prior stays recoverable via `scrolls archive show`. The held copy
            # is *not* counted as skipped; it was replaced.
            prior = adopt_incoming(db_path, item, archived_at=now)
            counts["adopted"] += 1
            adopted_ids.add(item.id)
            if prior is not None:
                events.append(
                    supersession_event(
                        item.id,
                        prior_hash=prior.content_hash,
                        incoming_hash=item.content_hash,
                        now=now,
                    )
                )
        else:
            counts["skipped"] += 1
            counts[outcome] += 1
            if outcome == "conflict":
                conflict_ids.add(item.id)
                # the held copy (the kept, never-overwritten row) is what the
                # incoming capture diverged from — record both hashes so `history`
                # answers "what disagreed, and when". `held` is non-None barring a
                # concurrent delete (merge_item just read it); the `.content_hash`
                # falls back to None defensively rather than crash the import.
                held = get_item(db_path, item.id)
                events.append(
                    conflict_event(
                        item.id,
                        held_hash=held.content_hash if held is not None else None,
                        incoming_hash=item.content_hash,
                        now=now,
                    )
                )
    record_events(db_path, events)
    return counts, sorted(conflict_ids), sorted(adopted_ids)


def _warn_conflicts(conflict_ids: list[str]) -> None:
    """Surface content conflicts on stderr (the `_warn_orphan_events` idiom), loud not silent.

    A conflict — a held id re-imported with a different captured ``content_hash`` —
    is a custody signal an operator should see, so it rides stderr beside the
    structured ``conflicts`` field: the held copy was kept, but an incoming copy
    disagreed and was *not* silently discarded into an opaque ``skipped`` count
    (the obsidian reconcile adoption: surface, don't silently rewrite). Names the
    diverging ids, bounded with a ``(+N more)`` tail (the readable-surface cap; the
    structured field stays uncapped). No-op on a clean import.
    """
    if not conflict_ids:
        return
    named = ", ".join(f"`{item_id}`" for item_id in conflict_ids[:_MAX_CONFLICT_IDS])
    if len(conflict_ids) > _MAX_CONFLICT_IDS:
        named += f" (+{len(conflict_ids) - _MAX_CONFLICT_IDS} more)"
    print(
        json.dumps({
            "warning": (
                f"{len(conflict_ids)} item(s) in this import conflict with a held "
                f"copy (different content — kept the held copy, not overwritten): "
                f"{named}"
            )
        }),
        file=sys.stderr,
    )


def _warn_adopted(adopted_ids: list[str]) -> None:
    """Surface accept-incoming adoptions on stderr (the `_warn_conflicts` idiom).

    Under ``--accept-incoming`` a held copy is *replaced* by the incoming one — the
    first import-path write that changes a held capture (ADR 0106). That is a custody
    signal an operator should see even though they asked for it: it rides stderr
    beside the structured ``adopted`` field, naming the replaced ids and pointing at
    the recovery path (the prior capture is archived, never destroyed). Bounded with a
    ``(+N more)`` tail like `_warn_conflicts`; no-op when nothing was adopted.
    """
    if not adopted_ids:
        return
    named = ", ".join(f"`{item_id}`" for item_id in adopted_ids[:_MAX_CONFLICT_IDS])
    if len(adopted_ids) > _MAX_CONFLICT_IDS:
        named += f" (+{len(adopted_ids) - _MAX_CONFLICT_IDS} more)"
    print(
        json.dumps({
            "warning": (
                f"{len(adopted_ids)} held copy(ies) replaced by the incoming capture "
                f"(accept-incoming — prior archived, recoverable via "
                f"`scrolls archive show`): {named}"
            )
        }),
        file=sys.stderr,
    )


def _preview_merge_items(
    db_path: Path, items: list[ScrollItem], *, accept_incoming: bool = False
) -> tuple[dict[str, int], list[str], list[str], list[str], list[str]]:
    """Predict `_merge_items` without writing — the read-only twin of the merge.

    The dry-run sibling of `_merge_items` (the H233/H239 "the preview never drifts
    from reality" discipline, now on the conflict axis): it returns the *same*
    ``{imported, skipped, unchanged, conflict, adopted}`` counts and the *same*
    sorted ``conflicts``/``adopted`` lists a real `_merge_items` of the identical
    batch would, plus the reviewable, library-relative ``new``/``held`` partition
    (H226/H239).

    The catch is the **within-batch duplicate**. The live `merge_item` does INSERT
    OR IGNORE, so a bundle that repeats an id sees its own prior insert — the first
    occurrence is the kept copy and every later one is classified against *it*. The
    preview writes nothing, so `get_item` never reflects a within-batch insert; we
    track the kept content per id in ``kept_hash`` so a later occurrence with a
    different hash is the *same* ``conflict``/``adopted`` the live path would
    produce. ``new``/``held`` stay **library**-relative — an id absent from the
    library before the import is ``new`` even if it repeats (H239/H245), so a
    within-batch dup of a new id never leaks into ``held`` — while the
    unchanged/conflict/adopted split tracks the live merge's batch-aware view.

    With ``accept_incoming`` (ADR 0106), a divergence is predicted as *adopted*
    (the held copy would be replaced) rather than *conflict* (kept), and the kept
    content is advanced to the incoming hash so a subsequent same-batch occurrence
    compares against what the live adoption would have left behind — keeping the
    held→incoming transition prediction faithful to the live write.
    """
    counts = {"imported": 0, "skipped": 0, "unchanged": 0, "conflict": 0, "adopted": 0}
    conflict_ids: set[str] = set()
    adopted_ids: set[str] = set()
    new_ids: set[str] = set()
    held_ids: set[str] = set()
    kept_hash: dict[str, str | None] = {}  # id -> the current kept copy's content_hash
    for item in items:
        held = get_item(db_path, item.id)
        if item.id in kept_hash:
            # a within-batch occurrence (or an already-adopted one this batch):
            # classify against the content the prior occurrences would have left
            baseline, present = kept_hash[item.id], True
            if held is None:
                new_ids.add(item.id)  # library-absent id, even if it repeats
            else:
                held_ids.add(item.id)
        elif held is not None:
            # already in the library — INSERT OR IGNORE would skip; classify
            # against the held copy
            held_ids.add(item.id)
            baseline, present = held.content_hash, True
        else:
            # the first occurrence of a library-absent id — the inserted copy
            new_ids.add(item.id)
            kept_hash[item.id] = item.content_hash
            present = False
        if not present:
            counts["imported"] += 1
        elif baseline != item.content_hash:
            if accept_incoming:
                # the held copy would be replaced; the kept content advances to
                # the incoming one (the live adoption's effect)
                counts["adopted"] += 1
                adopted_ids.add(item.id)
                kept_hash[item.id] = item.content_hash
            else:
                counts["skipped"] += 1
                counts["conflict"] += 1
                conflict_ids.add(item.id)
        else:
            counts["skipped"] += 1
            counts["unchanged"] += 1
    return (
        counts,
        sorted(conflict_ids),
        sorted(new_ids),
        sorted(held_ids),
        sorted(adopted_ids),
    )


def _cmd_import_items(path: str, accept_incoming: bool = False) -> int:
    try:
        imported_items, stats = load_items_export(Path(path).expanduser())
    except ItemsSourceError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    paths = get_paths()
    ensure_library(paths)
    # INSERT OR IGNORE per row (an existing item — earlier import, or a manual
    # `add`/user edit — is never overwritten; re-imports stay cheap), but the skip
    # is no longer opaque: an identical re-import is `unchanged`, a same-id row with
    # a different `content_hash` is a surfaced `conflict` (custody vision §2.4 —
    # drift/conflict is a recorded event, never an overwrite). Derived artifacts
    # rebuild from these rows: `doctor --fix` rewrites missing scrolls and the FTS
    # index, `kb` recompiles the library.
    #
    # `--accept-incoming` (roadmap H278, ADR 0106) opts into *adopting* a diverging
    # incoming capture: the held copy is replaced by the incoming one (its prior
    # capture archived, recoverable), recorded as a `superseded` event. Opt-in only —
    # without the flag a conflict is surfaced and the held copy kept.
    counts, conflicts, adopted = _merge_items(
        paths.db_path, imported_items, accept_incoming=accept_incoming
    )
    _warn_conflicts(conflicts)
    _warn_adopted(adopted)
    print(json.dumps(
        {**counts, "conflicts": conflicts, "adopted": adopted, **stats}
    ))
    return 0


def _cmd_import_events(path: str) -> int:
    # whole-library portable custody (H72): restore the verify ledger from a
    # JSONL export through the same idempotent `import_events` the bundle import
    # uses, so re-importing a backup is a custody no-op (dedup by content, never
    # the per-library autoincrement id).
    try:
        events, stats = load_events_export(Path(path).expanduser())
    except EventsSourceError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    paths = get_paths()
    ensure_library(paths)
    imported, skipped = import_events(paths.db_path, events)
    print(json.dumps({"imported": imported, "skipped": skipped, **stats}))
    return 0


def _cmd_import_archive(path: str) -> int:
    # the portable recovery store (H280): restore the prior-content archive from a
    # JSONL export through the same idempotent `import_archive` the bundle import
    # uses, so re-importing a backup (or the overlapping union of two bundles) is a
    # no-op (dedup by `(item_id, prior_hash)`, never the per-library autoincrement
    # id). The archive is a standalone recovery store — this only appends to
    # `item_archive`, never touching a held row.
    try:
        records, stats = load_archive_export(Path(path).expanduser())
    except ArchiveSourceError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    paths = get_paths()
    ensure_library(paths)
    imported, skipped = import_archive(paths.db_path, records)
    print(json.dumps({"imported": imported, "skipped": skipped, **stats}))
    return 0


def _cmd_export_opml() -> int:
    paths = get_paths()
    subscriptions = (
        list_subscriptions(paths.db_path) if paths.db_path.exists() else []
    )
    # the OPML document *is* the artifact (the `context`/scroll exception to the
    # JSON-on-stdout rule), so it prints raw — `scrolls export opml > feeds.opml`
    sys.stdout.write(dump_opml_export(subscriptions))
    return 0


def _cmd_export_bookmarks(
    source: str | None, category: str | None, tag: str | None
) -> int:
    paths = get_paths()
    # the same durable-property facets `scrolls list` filters by (source,
    # category, tag) scope the export to a slice of the library; they AND
    # together and default to the whole library, in `list_items` saved order
    items = (
        list_items(paths.db_path, source=source, category=category, tag=tag)
        if paths.db_path.exists()
        else []
    )
    # the bookmark file *is* the artifact, like `export opml`, so it prints raw —
    # `scrolls export bookmarks > bookmarks.html` (the shell owns redirection)
    sys.stdout.write(dump_bookmark_export(items))
    return 0


def _cmd_export_items(
    source: str | None,
    category: str | None,
    tag: str | None,
    fidelity: str | None = None,
    drift: str | None = None,
    content_duplicate: bool = False,
) -> int:
    paths = get_paths()
    # the same durable-property facets `export bookmarks` offers scope the
    # export to a slice; they AND together and default to the whole library
    # (the backup case), in `list_items` saved order. `fidelity`/`drift` (H259)
    # add the two custody axes — "back up only my full-fidelity holdings" /
    # "ship only the drifted rows for a recapture handoff" — folding the same
    # `list --fidelity`/`--drift` sieve, so the JSONL is the byte-identical
    # subset of the unscoped backup. `content_duplicate` (H341) adds the
    # content-identity axis — "back up only the redundant copies so a recipient
    # can dedup" — folding the same `list --content-duplicate` whole-library
    # sibling sieve (H338, the `content_duplicate_index` fold); the post-SQL
    # sieve preserves saved order, so the scoped JSONL stays the byte-identical
    # subset. An unknown value is rejected by argparse `choices` (exit 2) before
    # reaching here; on the library path `list_items` raises ValueError (the
    # empty-vocabulary belt-and-braces → exit 1, the `export bundle` precedent).
    try:
        items = (
            list_items(
                paths.db_path,
                source=source,
                category=category,
                tag=tag,
                fidelity=fidelity,
                drift=drift,
                content_duplicate=content_duplicate,
            )
            if paths.db_path.exists()
            else []
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    # the JSONL stream *is* the artifact, like `export opml`/`export bookmarks`,
    # so it prints raw — `scrolls export items > library.jsonl`
    sys.stdout.write(dump_items_export(items))
    return 0


def _cmd_export_events(
    source: str | None,
    category: str | None,
    tag: str | None,
    since: str | None = None,
    fidelity: str | None = None,
    drift: str | None = None,
    content_duplicate: bool = False,
) -> int:
    # whole-library portable custody (H72): the verify ledger as a lossless JSONL
    # stream, the custody sibling of `export items`. Scoped by the same
    # item-facet set (source/category/tag) — resolve the items, then their
    # events — so a slice's custody travels with the slice's items.
    #
    # `fidelity`/`drift` (H260) add the two custody axes as an *item-set sieve*:
    # they narrow the item resolution (the same `list --fidelity`/`--drift` H250/
    # H54 primitives `export items` folds, H259), then the *whole* ledger of those
    # items travels — "ship the full custody history of the drifted items for a
    # recapture handoff." This mirrors how `--source` already scopes events by
    # item (and so `--drift drifted` carries an item's earlier non-drifted rows
    # too, the item's whole history, not just the matching event row). Both axes
    # AND with each other and the rest. An unknown value is rejected by argparse
    # `choices` (exit 2) before reaching here; on the library path `list_items`
    # raises ValueError (the empty-vocabulary belt-and-braces → exit 1, the
    # `export items`/`export bundle` precedent).
    #
    # `content_duplicate` (H347) is the content-identity axis on the same item-set
    # sieve — "ship the custody history of only the redundant copies, so a recipient
    # can dedup with the full proof of when each was verified" — folding the same
    # whole-library `list --content-duplicate` sibling sieve (H338) `export items`
    # already folds (H341). Whole-library scope (a content group spans sources), so
    # ANDed with --source it still ships a source's item whose byte-identical sibling
    # lives elsewhere. Report-only, never a merge (the H325 no-fabricated-act rule).
    #
    # `--since <ISO>` (H75) windows the stream to events at/after the boundary —
    # an incremental backup since the last sweep. Validated first so a malformed
    # boundary is a loud usage error (exit 2, the `maintain --trend` precedent),
    # never a silently-empty backup; an empty window is still a valid empty doc.
    try:
        boundary = parse_since(since)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    paths = get_paths()
    try:
        items = (
            list_items(
                paths.db_path,
                source=source,
                category=category,
                tag=tag,
                fidelity=fidelity,
                drift=drift,
                content_duplicate=content_duplicate,
            )
            if paths.db_path.exists()
            else []
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    events = (
        events_for_items(paths.db_path, [item.id for item in items], since=boundary)
        if items
        else []
    )
    # the JSONL stream *is* the artifact (the `export items` rule) —
    # `scrolls export events > ledger.jsonl`
    sys.stdout.write(dump_events_export(events))
    return 0


def _cmd_export_archive(
    ref: str | None,
    source: str | None = None,
    fidelity: str | None = None,
    drift: str | None = None,
    since: str | None = None,
    content_duplicate: bool = False,
) -> int:
    # the portable recovery store (H280): the prior-content archive (ADR 0106) as a
    # lossless JSONL stream, the recovery-store sibling of `export events`. A library
    # rebuilt from `export items` + `export events` reads *that* an adoption happened
    # (the `superseded` event travels) but cannot recover the prior bytes; this
    # carries them, so `scrolls archive show` works on the rebuilt library.
    #
    # `--id <ref>` scopes to one item's archived priors (resolving a URL to the id
    # `add` would mint, the `archive list --id` precedent). The *library-filter
    # group* `--source`/`--fidelity`/`--drift`/`--content-duplicate` is the other way
    # to pick the item set whose recovery store travels — an *item-set sieve*
    # (H301/H302, the content-identity axis added H347): resolve the in-scope held
    # item ids via the same `list --source`/`--fidelity`/`--drift`/
    # `--content-duplicate` primitive `export events` folds (H260/H347), then ship
    # their whole archived history. `--content-duplicate` backs up "the recoverable
    # priors of the redundant copies so a recipient can dedup"; its sibling scope is
    # whole-library (a content group spans sources), report-only / never a merge.
    # `--fidelity full` backs up "the recovery history of holdings I can re-derive
    # offline"; `--drift drifted` backs up "the recoverable priors of the moved
    # items for a recapture handoff" — the items' *whole* archive, exactly as
    # `--source` scopes by item. The three filters AND together; the whole library's
    # recovery store travels when none is given (the backup case).
    #
    # `--id` selects one precise item; the library-filter group selects a slice of
    # the held library — two different selection modes — so mixing them is a loud
    # usage error (exit 2, the `archive restore` "at most one version selector"
    # precedent). An unknown fidelity/drift value is rejected by argparse `choices`
    # (exit 2) before reaching here; on the library path `list_items` raises
    # ValueError (the empty-vocabulary belt-and-braces → exit 1, the `export events`
    # precedent).
    #
    # `--since <ISO>` (H303) is a third, *orthogonal* axis — a time window on
    # `archived_at`, not an item-set sieve — so it is **not** part of the mutual
    # exclusion: it composes with whichever item-set selector ran (`--id`, the
    # library-filter group, or none), narrowing the resolved priors to those
    # archived at/after the boundary. The incremental-backup window (`export events
    # --since` analogue): re-importing the overlapping union stays idempotent (the
    # archive dedups by `(item_id, prior_hash)`, ADR 0106).
    if ref is not None and (
        source is not None
        or fidelity is not None
        or drift is not None
        or content_duplicate
    ):
        print(
            json.dumps({
                "error": "export archive --id <ref> selects one item; it cannot "
                "combine with the library-filter scope "
                "(--source/--fidelity/--drift/--content-duplicate)"
            }),
            file=sys.stderr,
        )
        return 2
    # Validated before any item resolution so a malformed boundary is a loud usage
    # error (exit 2, the `export events --since`/`maintain --trend` precedent), never
    # a silently-empty backup that could mask a typo; an empty window is still a
    # valid empty document.
    try:
        boundary = parse_since(since)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    paths = get_paths()
    item_ids: list[str] | None = None
    if ref is not None:
        try:
            item_ids = [resolve_item_id(ref)]
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
    elif (
        source is not None
        or fidelity is not None
        or drift is not None
        or content_duplicate
    ):
        # resolve the library-filter group to its held item ids (the same
        # `list --source`/`--fidelity`/`--drift`/`--content-duplicate` item-set sieve
        # `export events` folds), then their archived priors travel. An empty
        # selection (a source with no held items, or no holding at the custody value)
        # is a valid empty backup (the unmatched `--id` precedent), never an error; a
        # missing/pre-init library likewise. An unknown fidelity/drift value surfaces
        # `list_items`' ValueError as exit 1 (argparse `choices` already rejects it as
        # exit 2).
        try:
            item_ids = (
                [
                    item.id
                    for item in list_items(
                        paths.db_path,
                        source=source,
                        fidelity=fidelity,
                        drift=drift,
                        content_duplicate=content_duplicate,
                    )
                ]
                if paths.db_path.exists()
                else []
            )
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
    records = (
        archived_records(paths.db_path, item_ids, since=boundary)
        if paths.db_path.exists()
        else []
    )
    # the JSONL stream *is* the artifact (the `export items`/`export events` rule) —
    # `scrolls export archive > archive.jsonl`
    sys.stdout.write(dump_archive_export(records))
    return 0


def _cmd_export_bundle(
    query: str,
    source: str | None,
    category: str | None,
    stage: str | None,
    tag: str | None,
    concept: str | None,
    fmt: str = "markdown",
    fidelity: str | None = None,
    drift: str | None = None,
    strength: str | None = None,
    with_archive: bool = False,
    content_duplicate: bool = False,
) -> int:
    paths = get_paths()
    # markdown (default) is the canonical, lossless, re-importable bundle; html
    # is a browser-readable, export-only briefing (roadmap H39). Both tolerate a
    # missing library (a valid empty document, no library created — like
    # `scrolls context` before `init`). `fidelity`/`drift` (H258) scope the bundle
    # to one custody tier/posture; an unknown value is rejected by argparse
    # `choices` (exit 2) before reaching here, and on the library path by
    # `search_items` (ValueError → exit 1, the empty-vocabulary belt-and-braces).
    # `strength` (H318) is the rank-axis third scope, rejected the same way.
    # `content_duplicate` (H341) is the content-identity axis — "ship only the
    # redundant copies so a recipient can dedup" — threaded through the same
    # `search_items`/`count_matches` whole-library `content_hash` sub-count clause
    # (H338), so the shared `_gather_scope` sieves the items, ledger, and events
    # block to exactly the byte-identical-held matches.
    # `--with-archive` (H280) appends the in-scope items' prior-content archive in a
    # third fenced block (opt-in — the bundle stays lean by default).
    builder = build_bundle_html if fmt == "html" else build_bundle
    try:
        bundle = builder(
            paths.db_path,
            query,
            source=source,
            category=category,
            stage=stage,
            tag=tag,
            concept=concept,
            fidelity=fidelity,
            drift=drift,
            strength=strength,
            with_archive=with_archive,
            content_duplicate=content_duplicate,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    # the bundle *is* the artifact (the `context`/scroll exception to the
    # JSON-on-stdout rule) — `scrolls export bundle "<q>" > briefing.md`, or
    # `… --format html > briefing.html`
    sys.stdout.write(bundle)
    return 0


_MAX_ORPHAN_ITEM_IDS = 5


def _orphan_item_ids(orphan_events: list) -> list[str]:
    """The distinct `item_id`s a batch of orphan events dangle on, sorted + deduped.

    The single source of truth for both diagnosable orphan surfaces (H225/H230):
    the human stderr warning (`_warn_orphan_events`, which bounds the *named* list
    with a `(+N more)` tail) and the structured `events.orphaned_items` summary
    field (which carries the list **uncapped** — the machine channel reports the
    complete loss; the cap is a human-readability concern, never a structured-field
    truncation, the M2 ethos). Two events on one missing item name it once.
    """
    return sorted({event.item_id for event in orphan_events})


def _warn_orphan_events(orphan_events: list) -> None:
    """Surface orphan custody events on stderr (roadmap H217/H225), loud not silent.

    Shared by the live import and the `--dry-run` preview so both report the same
    warning for the same corrupt bundle — the preview faithfully shows what the
    real import would flag.

    The warning names the *event* count (how many ledger rows dangle) **and** the
    distinct `item_id`s they point at (sorted, deduped, bounded with a `(+N more)`
    tail, the readable-surface idiom), so "2 orphan events" becomes a diagnosable
    "… not in this bundle …: `arxiv:x`, `web:ghost`" — the operator can see *which*
    rows the items block is missing, not just that the bundle is corrupt (H225).
    The leading count stays the event count; the id list is the distinct-item
    count, so two events on the same missing item name it once.
    """
    if not orphan_events:
        return
    distinct_ids = _orphan_item_ids(orphan_events)
    named = ", ".join(f"`{item_id}`" for item_id in distinct_ids[:_MAX_ORPHAN_ITEM_IDS])
    if len(distinct_ids) > _MAX_ORPHAN_ITEM_IDS:
        named += f" (+{len(distinct_ids) - _MAX_ORPHAN_ITEM_IDS} more)"
    print(
        json.dumps({
            "warning": (
                f"{len(orphan_events)} orphan custody event(s) reference items "
                f"not in this bundle and were not imported: {named}"
            )
        }),
        file=sys.stderr,
    )


def _cmd_import_bundle(
    path: str, dry_run: bool = False, accept_incoming: bool = False
) -> int:
    try:
        text = Path(path).expanduser().read_text(encoding="utf-8")
        imported_items = parse_bundle(text)
        imported_events = parse_bundle_events(text)
        imported_archive = parse_bundle_archive(text)
    except OSError as exc:
        print(json.dumps({"error": f"cannot read {path}: {exc}"}), file=sys.stderr)
        return 1
    except BundleError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    paths = get_paths()
    ensure_library(paths)

    if dry_run:
        return _preview_import_bundle(
            paths,
            imported_items,
            imported_events,
            imported_archive,
            accept_incoming=accept_incoming,
        )

    # INSERT OR IGNORE per row (ADR 0082): a scroll the target library already
    # holds is never overwritten — custody-safe re-import. But the skip is no
    # longer opaque (roadmap H273, the H272 partition lifted to the bundle
    # importer): an identical re-import is `unchanged`, a same-id row with a
    # different `content_hash` is a surfaced `conflict` (a peer's bundle of a
    # source that has since drifted — custody vision §2.4, drift/conflict is a
    # recorded event, never an overwrite). Derived artifacts rebuild from these
    # rows via `doctor --fix` / `kb`, as `import items` relies on.
    #
    # `--accept-incoming` (roadmap H278, ADR 0106) adopts a diverging incoming
    # capture: the held copy is replaced (its prior capture archived, recoverable),
    # recorded as a `superseded` event. Opt-in only.
    counts, conflicts, adopted = _merge_items(
        paths.db_path, imported_items, accept_incoming=accept_incoming
    )
    _warn_conflicts(conflicts)
    _warn_adopted(adopted)
    # restore the portable custody ledger (roadmap H67), deduped by content so a
    # re-import is a custody no-op — the verify-axis sibling of the items'
    # INSERT OR IGNORE. Events ride for *every* in-scope item, whether its row was
    # freshly inserted or already held (custody history merges), since dedup
    # prevents double-counting.
    #
    # First split off any **orphan** events — events whose item is neither held
    # nor imported (roadmap H217). A well-formed bundle has none (its events ride
    # only for in-scope items, all of which are in the items block above), so this
    # is the corrupt/hand-edited case: importing such an event would write a
    # dangling ledger row for an item `scrolls show` 404s on. We count it
    # (`orphaned`, always present, and a stderr warning when non-zero) and decline
    # to insert it — the take-it-with-me artifact is honest about what didn't
    # resolve, never silently retaining a phantom history nor silently dropping it.
    resolvable_events, orphan_events = partition_resolvable_events(
        paths.db_path, imported_events
    )
    ev_imported, ev_skipped = import_events(paths.db_path, resolvable_events)
    _warn_orphan_events(orphan_events)
    # restore the prior-content archive (roadmap H280) if the bundle carried one
    # (a `--with-archive` export, the optional third region). Unconditional —
    # whatever recovery store travelled is restored, deduped by `(item_id,
    # prior_hash)`, the events-restore idiom on the archive axis. A lean default
    # bundle carries no archive block → `imported_archive == []` → a clean (0, 0).
    # The archive is a standalone recovery store: this only appends to
    # `item_archive`, never touching a held row (no orphan concept needed).
    ar_imported, ar_skipped = import_archive(paths.db_path, imported_archive)
    print(json.dumps({
        **counts,
        # the distinct ids whose held copy diverged from the incoming bundle row
        # (H273) — sorted, deduped, **uncapped**: the structured, machine-complete
        # twin of the bounded `_warn_conflicts` stderr line. `[]` is the honest
        # clean re-import (no divergence), and `conflict == len(conflicts)` unless
        # a within-bundle dup names one id twice (then `conflict` counts the raw
        # occurrences while `conflicts` names the distinct divergent id once).
        "conflicts": conflicts,
        # the distinct ids whose held copy was *replaced* by the incoming capture
        # (H278, accept-incoming) — `[]` unless `--accept-incoming` was given; the
        # prior copies are archived (recoverable via `scrolls archive`).
        "adopted": adopted,
        "items": len(imported_items),
        "events": {
            "imported": ev_imported,
            "skipped": ev_skipped,
            "orphaned": len(orphan_events),
            # the distinct ids the orphan events dangle on (H230) — the structured,
            # **uncapped** twin of the bounded stderr warning, so an agent piping
            # stdout learns *which* items the bundle is missing, not just how many.
            # Always present (`[]` is the honest "we checked, none dangled").
            "orphaned_items": _orphan_item_ids(orphan_events),
        },
        # the prior-content archive restore (roadmap H280) — always present, like
        # `events`: a lean default bundle carries no archive block → a clean
        # `{imported: 0, skipped: 0}` ("we checked, none travelled"), a
        # `--with-archive` bundle restores its recovery store (deduped).
        "archive": {"imported": ar_imported, "skipped": ar_skipped},
    }))
    return 0


def _preview_import_bundle(
    paths,
    imported_items,
    imported_events,
    imported_archive,
    accept_incoming: bool = False,
) -> int:
    """The read-only sibling of the bundle import (roadmap H220, H273).

    An agent handed a portable "take it with me" bundle should be able to see
    *exactly* what a merge would add vs. skip — new items, already-held skips,
    held-copy **conflicts** (H273), custody events added/deduped, orphan
    events (H217), and the prior-content archive restore (H280) — **without
    writing**. The same summary the live import prints, computed by diffing against
    the library: the item partition via `_preview_merge_items` (the read-only twin
    of `_merge_items`, predicting the same conflict set INSERT OR IGNORE would
    surface), the event-dedup preview, the orphan-event split, and the
    archive-restore prediction via `preview_import_archive`.

    The bundle's own item ids anchor the event partition (`known_ids`): the live
    import inserts those rows *before* partitioning, so an event for a not-yet-held
    bundle item resolves in the preview exactly as it would after the write —
    otherwise a fresh-library preview would mis-flag every event as an orphan.
    """
    bundle_item_ids = {item.id for item in imported_items}
    # Predict the live merge without writing (roadmap H273): `_preview_merge_items`
    # is the read-only twin of `_merge_items`, returning the same
    # `{imported, skipped, unchanged, conflict}` counts, the same `conflicts` list,
    # and the reviewable `new`/`held` partition. It simulates INSERT OR IGNORE's
    # within-batch view (a bundle that repeats an id sees its own prior insert) so a
    # within-bundle dup classifies identically to the live path, while `new`/`held`
    # stay library-relative (H239/H245).
    #
    # `new`/`held` are the *reviewable* half of the preview (roadmap H226): the
    # counts say how much a merge would change, these name *what* — the distinct
    # ids an operator can confirm before committing. Sorted + deduped, and
    # **uncapped** (the structured channel carries the complete sets; only the human
    # orphan/conflict warnings bound their tails — M2: structured completeness vs.
    # human readability). A within-bundle repeat of a new id lands once in `new`; a
    # repeat of a held id once in `held`; so over a well-formed bundle (no repeats)
    # `len(new) == imported` and `len(held) == skipped`.
    #
    # Under `--accept-incoming` (H278) the preview predicts the *adopted* set — the
    # held copies a live merge would replace with the incoming capture — instead of
    # surfacing them as kept conflicts (the held→incoming transition prediction, the
    # H245/H273 "predict the write effect" discipline on the adopt axis).
    counts, conflicts, new_ids, held_ids, adopted = _preview_merge_items(
        paths.db_path, imported_items, accept_incoming=accept_incoming
    )
    # the conflict/adoption warnings are loud in the preview too (the
    # `_warn_orphan_events` idiom), so the dry-run faithfully shows what the real
    # import would flag
    _warn_conflicts(conflicts)
    _warn_adopted(adopted)

    resolvable_events, orphan_events = partition_resolvable_events(
        paths.db_path, imported_events, known_ids=bundle_item_ids
    )
    ev_imported, ev_skipped = preview_import_events(paths.db_path, resolvable_events)
    _warn_orphan_events(orphan_events)
    # predict the archive restore without writing (roadmap H280) — the read-only
    # twin of `import_archive`, the same `{imported, skipped}` the live path reports
    # for the same recovery store, so the dry-run never drifts from the real import
    # (the H220/H233 preview-fidelity discipline on the archive axis).
    ar_imported, ar_skipped = preview_import_archive(paths.db_path, imported_archive)
    print(json.dumps({
        "dry_run": True,
        **counts,
        "conflicts": conflicts,
        "adopted": adopted,
        "items": len(imported_items),
        "new": new_ids,
        "held": held_ids,
        "events": {
            "imported": ev_imported,
            "skipped": ev_skipped,
            "orphaned": len(orphan_events),
            # the same uncapped distinct-id list the live import reports (H230) —
            # the preview is honest about *which* items orphan, not just how many.
            "orphaned_items": _orphan_item_ids(orphan_events),
        },
        # the archive-restore prediction (H280), the same shape the live import
        # carries — `{imported: 0, skipped: 0}` for a lean default bundle.
        "archive": {"imported": ar_imported, "skipped": ar_skipped},
    }))
    return 0


def _find_item(paths: LibraryPaths, ref: str) -> tuple[ScrollItem | None, str]:
    """Look up an item by id-or-URL ref; return (item, "") or (None, error).

    A URL resolves to the id `add` would mint (ADR 0028); the error
    names the resolved id so the resolution stays visible.
    """
    try:
        item_id = resolve_item_id(ref)
    except ValueError as exc:
        return None, str(exc)
    item = get_item(paths.db_path, item_id) if paths.db_path.exists() else None
    if item is None:
        suffix = f" (from {ref})" if item_id != ref else ""
        return None, f"no such item: {item_id}{suffix}"
    return item, ""


def _cmd_fetch(ref: str | None, limit: int | None = None) -> int:
    paths = get_paths()
    if ref is not None:
        if limit is not None:
            print(
                json.dumps({"error": "--limit paces batch runs; drop it when fetching one item"}),
                file=sys.stderr,
            )
            return 1
        item, error = _find_item(paths, ref)
        if item is None:
            print(json.dumps({"error": error}), file=sys.stderr)
            return 1
        items = [item]
    else:
        items = list_items(paths.db_path, stage="detected") if paths.db_path.exists() else []

    results = []
    counts = {"fetched": 0, "skipped": 0, "failed": 0}
    attempted = 0
    for item in items:
        # the limit counts fetch attempts, not adapterless skips — skipped
        # items stay detected at the front of the saved order, and counting
        # them would wedge every paced run on the same skips
        if limit is not None and attempted >= limit:
            break
        adapter = FETCH_ADAPTERS.get(item.source)
        if adapter is None:
            # Bulk runs leave adapterless items for a future scrolls; asking
            # for one by id deserves an honest failure.
            if ref is None:
                counts["skipped"] += 1
                results.append(
                    {
                        "id": item.id,
                        "status": "skipped",
                        "reason": f"no fetch adapter for source '{item.source}'",
                    }
                )
                continue
            counts["failed"] += 1
            results.append(
                {
                    "id": item.id,
                    "status": "failed",
                    "error": f"no fetch adapter for source '{item.source}'",
                }
            )
            continue
        attempted += 1
        try:
            fetched = adapter(item)
        except FetchError as exc:
            counts["failed"] += 1
            results.append({"id": item.id, "status": "failed", "error": str(exc)})
            continue
        update_item(paths.db_path, fetched)
        counts["fetched"] += 1
        results.append(
            {
                "id": fetched.id,
                "status": "fetched",
                "title": fetched.title,
                "stage": fetched.stage,
            }
        )

    print(json.dumps({**counts, "results": results}))
    return 1 if counts["failed"] else 0


def _cmd_verify(
    ref: str | None,
    verify_all: bool,
    unverified: bool = False,
    limit: int | None = None,
    stale_before: str | None = None,
    drift: str | None = None,
    source: str | None = None,
    fidelity: str | None = None,
) -> int:
    """Re-capture items and record drift/rot custody events (ADR 0098).

    Verifying re-fetches an item through its adapter, diffs the fresh content
    hash against the stored one, and appends a custody event — never touching
    the original capture, so proving the source changed can't lose what we
    held. Exactly one *selection* is required: a single item ref, `--all`
    (every held item carrying a captured hash), `--unverified` (only the
    held, hash-bearing items the ledger has no verdict for — the `unverified`
    bucket doctor/facets/status report, made actionable), `--stale-before
    <ISO>` (the held, hash-bearing items whose newest verdict predates the
    boundary, plus the never-checked — the staleness-bounded recheck, the
    act-side sibling of `history --since` / `export events --since`),
    `--drift <posture>` (the held, hash-bearing items currently at a chosen
    drift posture — the set `list --drift` enumerates and `facets drift`
    counts, so a worker re-checks the suspect set instead of `--all`), or
    `--source <S>` (the held, hash-bearing items from one source — the
    act-side of doctor/maintain's per-source custody breakdown, the verify-axis
    sibling of `list --source`, so a worker re-checks the weakest source
    without `--all`), or `--fidelity <tier>` (the held, hash-bearing items at
    one custody-fidelity tier — the act-axis twin of `list --fidelity` /
    `search --fidelity`, the holdings axis, so a worker re-verifies exactly its
    full-fidelity holdings without `--all`). `error` (could-not-check) drives a
    nonzero exit; `drifted`/`rotted` are successful checks that found a custody
    event.
    """
    paths = get_paths()
    selections = (
        ref is not None, verify_all, unverified, stale_before is not None,
        drift is not None, source is not None, fidelity is not None,
    )
    if sum(selections) != 1:
        print(
            json.dumps(
                {"error": "verify needs exactly one of an item id, --all, "
                 "--unverified, --stale-before, --drift, --source, or --fidelity"}
            ),
            file=sys.stderr,
        )
        return 1

    # Normalize (and validate) the staleness boundary before any item lookup, so
    # a malformed --stale-before is a loud usage error (exit 2, the
    # `export events --since` / `maintain --trend` precedent), never a silently
    # empty recheck that could mask a typo'd boundary.
    boundary: str | None = None
    if stale_before is not None:
        try:
            boundary = parse_since(stale_before)
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        if boundary is None:
            print(
                json.dumps(
                    {"error": "--stale-before needs an ISO-8601 timestamp boundary"}
                ),
                file=sys.stderr,
            )
            return 2

    if ref is not None:
        if limit is not None:
            print(
                json.dumps(
                    {"error": "--limit paces "
                     "--all/--unverified/--stale-before/--drift/--source/--fidelity "
                     "runs; drop it when verifying one item"}
                ),
                file=sys.stderr,
            )
            return 1
        item, error = _find_item(paths, ref)
        if item is None:
            print(json.dumps({"error": error}), file=sys.stderr)
            return 1
        if not item.content_hash:
            print(
                json.dumps(
                    {"error": f"item {item.id!r} holds no content hash to verify against"}
                ),
                file=sys.stderr,
            )
            return 1
        items = [item]
    else:
        # Every batch mode re-checks only items with a captured baseline hash: a
        # reference-only or detected item has nothing to diff a re-fetch against
        # (so it stays `unverified` — honestly, there is nothing to verify it on).
        all_items = list_items(paths.db_path) if paths.db_path.exists() else []
        hash_bearing = [item for item in all_items if item.content_hash]
        if verify_all:
            items = hash_bearing
        elif source is not None:
            # `--source` is orthogonal to the ledger-driven selections: a plain
            # item-intrinsic filter (the verify-axis sibling of `list --source`),
            # so the rows it re-captures are exactly `list --source S`'s held,
            # hash-bearing rows. Sources are open-ended (no closed vocabulary),
            # so a source nothing is held for is an honest empty no-op, never an
            # error. Preserves the oldest-saved-first order for `--limit`.
            items = [item for item in hash_bearing if item.source == source]
        elif fidelity is not None:
            # `--fidelity` is the holdings-axis sibling of `--source`: a plain
            # item-intrinsic filter (the act-axis twin of `list --fidelity` /
            # `search --fidelity`), folding the same `get_fidelity` primitive
            # those read surfaces count with — no ledger read. Like every batch
            # mode it re-captures only hash-bearing rows, so the set it touches
            # is `list --fidelity <tier>`'s held, *hash-bearing* subset — genuinely
            # narrower than the listing (a full capture held by raw body alone
            # carries no hash, so it lists `full` yet is skipped here), and a tier
            # holding no fingerprint (typically `reference`, which keeps no content)
            # is an honest empty no-op. Preserves oldest-saved-first for `--limit`.
            items = [item for item in hash_bearing if get_fidelity(item) == fidelity]
        else:
            # The ledger-driven selections all read the latest verdict per item.
            # `--unverified` takes the held − verdicts set doctor's
            # `custody.drift.unverified` counts (so a re-check clears exactly that
            # bucket); `--stale-before` takes the items whose newest verdict
            # predates the boundary (plus the never-checked — it subsumes
            # `--unverified`); `--drift` takes the items currently at a posture
            # (the same set `list --drift` enumerates and `facets drift` counts).
            # Empty ledger ⇒ no verdicts ⇒ everything is `unverified`.
            verdicts = latest_events(paths.db_path) if paths.db_path.exists() else {}
            if unverified:
                items = unverified_items(hash_bearing, verdicts)
            elif drift is not None:
                items = items_in_posture(hash_bearing, verdicts, drift)
            else:  # stale_before
                items = items_checked_before(hash_bearing, verdicts, boundary)

    if paths.db_path.exists():
        init_db(paths.db_path)  # ensure the ledger table exists before recording

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    counts = {"unchanged": 0, "drifted": 0, "rotted": 0, "error": 0}
    events = []
    results = []
    attempted = 0
    for item in items:
        if limit is not None and attempted >= limit:
            break
        attempted += 1
        event = verify_item(item, live_recapture, now=now)
        events.append(event)
        counts[event.status] += 1
        results.append(
            {
                "id": event.item_id,
                "status": event.status,
                "prior_hash": event.prior_hash,
                "observed_hash": event.observed_hash,
                "detail": event.detail,
            }
        )
    record_events(paths.db_path, events)
    print(json.dumps({"checked": len(results), **counts, "results": results}))
    return 1 if counts["error"] else 0


def _cmd_classify(
    item_id: str | None,
    engine: str | None = None,
    batch: bool = False,
    stale: bool = False,
    source: str | None = None,
) -> int:
    paths = get_paths()
    try:
        config = load_config(paths.config_path)
    except ConfigError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    # the --engine flag beats config.toml's [classify] default_engine
    explicit_engine = engine
    engine = engine or config.default_engine

    # `--source` is a *narrowing* of `--stale` (the per-source refresh, H154), not
    # a standalone selection like `verify --source`: the unattended worker reads
    # "source web carries 2 stale categories" off doctor and refreshes just those.
    # `--source` alone has no stale set to narrow, so it is a loud usage error.
    if source is not None and not stale:
        print(
            json.dumps(
                {"error": "classify --source narrows the --stale refresh; pass --stale"}
            ),
            file=sys.stderr,
        )
        return 1

    if stale:
        # --stale refreshes the *rules* ruleset fingerprint, so it is rules-only
        # and forces the engine regardless of the config default; an explicit
        # `--engine llm`, `--batch`, or a single id is a contradiction.
        if explicit_engine == "llm":
            print(
                json.dumps(
                    {"error": "classify --stale refreshes rules classifications; "
                     "it cannot use --engine llm"}
                ),
                file=sys.stderr,
            )
            return 1
        if batch:
            print(
                json.dumps(
                    {"error": "classify --stale is a rules refresh; "
                     "it cannot be combined with --batch"}
                ),
                file=sys.stderr,
            )
            return 1
        if item_id is not None:
            print(
                json.dumps(
                    {"error": "classify --stale refreshes a batch; "
                     "it cannot target one item"}
                ),
                file=sys.stderr,
            )
            return 1
        engine = "rules"

    if batch and engine != "llm":
        print(
            json.dumps({"error": "--batch requires the llm engine (--engine llm)"}),
            file=sys.stderr,
        )
        return 1
    if batch and item_id is not None:
        print(
            json.dumps(
                {"error": "--batch classifies the whole run; it cannot target one item"}
            ),
            file=sys.stderr,
        )
        return 1

    if engine == "llm":
        # lazy: only the llm engine pays the import (ADR 0015)
        from scrolls.classify_llm import (
            classify_item_llm,
            classify_items_llm_batch,
        )
        from scrolls.llm import LLMAuthError, LLMError

        llm_model = resolve_llm_model(config)

    if item_id is not None:
        item, error = _find_item(paths, item_id)
        if item is None:
            print(json.dumps({"error": error}), file=sys.stderr)
            return 1
        # Asking for one item by id is an explicit reclassify; batch runs
        # below never overwrite an existing category (user overrides win).
        items = [dataclasses.replace(item, category=None)]
    elif stale:
        # exactly doctor's custody.enrichment.stale set (one shared selector),
        # narrowed to `--source` when given (the per-source slice doctor reports
        # in custody.enrichment.by_source[<source>], H154); zero the category so a
        # re-classify recomputes it under the live ruleset. An item the live
        # ruleset no longer matches falls to "unmatched" and its stored category
        # is left untouched (non-destructive — we surface that it no longer
        # re-derives, we don't wipe it). A source with no stale debt is the honest
        # empty no-op (network-free, no targets).
        everything = list_items(paths.db_path) if paths.db_path.exists() else []
        items = [
            dataclasses.replace(item, category=None)
            for item in stale_classifications(everything, source=source)
        ]
    else:
        everything = list_items(paths.db_path) if paths.db_path.exists() else []
        items = [
            item
            for item in everything
            if item.category is None and item.stage in ("fetched", "rendered")
        ]

    if engine == "llm" and batch:
        # one Batches submission for the whole run (ADR 0022); a whole-batch
        # failure (no credentials, rejected submission) aborts like auth does
        try:
            pairs = classify_items_llm_batch(items, model=llm_model)
        except LLMError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
    else:
        pairs = [(item, None) for item in items]

    results = []
    counts = {"classified": 0, "unmatched": 0, "failed": 0}
    for item, outcome in pairs:
        if engine == "llm":
            if isinstance(outcome, LLMError):
                counts["failed"] += 1
                results.append(
                    {"id": item.id, "status": "failed", "error": str(outcome)}
                )
                continue
            if outcome is not None:
                classified = outcome
            else:
                try:
                    classified = classify_item_llm(item, model=llm_model)
                except LLMAuthError as exc:
                    # no credentials: every remaining item would fail the same way
                    print(json.dumps({"error": str(exc)}), file=sys.stderr)
                    return 1
                except LLMError as exc:
                    counts["failed"] += 1
                    results.append(
                        {"id": item.id, "status": "failed", "error": str(exc)}
                    )
                    continue
        else:
            classified = classify_item(item)
        if classified.category is None:
            counts["unmatched"] += 1
            results.append({"id": item.id, "status": "unmatched"})
            continue
        if classified.markdown_path:
            # keep the rendered scroll's frontmatter in sync with the DB
            try:
                classified = write_scroll(paths, classified)
            except OSError as exc:
                counts["failed"] += 1
                results.append({"id": item.id, "status": "failed", "error": str(exc)})
                continue
        update_item(paths.db_path, classified)
        counts["classified"] += 1
        result = {
            "id": classified.id,
            "status": "classified",
            "category": classified.category,
        }
        if engine == "llm":
            result["domain"] = classified.domain
            result["concepts"] = list(classified.concepts)
        results.append(result)

    print(json.dumps({**counts, "results": results}))
    return 1 if counts["failed"] else 0


def _cmd_md(item_id: str | None) -> int:
    paths = get_paths()
    if item_id is not None:
        item, error = _find_item(paths, item_id)
        if item is None:
            print(json.dumps({"error": error}), file=sys.stderr)
            return 1
        items = [item]
    else:
        items = list_items(paths.db_path, stage="fetched") if paths.db_path.exists() else []

    results = []
    counts = {"rendered": 0, "failed": 0}
    for item in items:
        if not item.extracted_text and not item.title:
            counts["failed"] += 1
            results.append(
                {
                    "id": item.id,
                    "status": "failed",
                    "error": f"item has no fetched content (stage '{item.stage}')",
                }
            )
            continue
        try:
            rendered = write_scroll(paths, item)
        except OSError as exc:
            counts["failed"] += 1
            results.append({"id": item.id, "status": "failed", "error": str(exc)})
            continue
        update_item(paths.db_path, rendered)
        counts["rendered"] += 1
        results.append(
            {"id": rendered.id, "status": "rendered", "path": rendered.markdown_path}
        )

    print(json.dumps({**counts, "results": results}))
    return 1 if counts["failed"] else 0


def _cmd_media(item_id: str | None) -> int:
    paths = get_paths()
    if item_id is not None:
        item, error = _find_item(paths, item_id)
        if item is None:
            print(json.dumps({"error": error}), file=sys.stderr)
            return 1
        # By id: explicit re-capture, like `fetch <id>` refetches.
        items, force = [item], True
    else:
        everything = list_items(paths.db_path) if paths.db_path.exists() else []
        items = [item for item in everything if has_pending_media(paths, item)]
        force = False

    results = []
    counts = {"captured": 0, "skipped": 0, "failed": 0}
    for item in items:
        updated, ref_results = capture_media(paths, item, force=force)
        files = [r["path"] for r in ref_results if r["status"] == "captured"]
        errors = [r["error"] for r in ref_results if r["status"] == "failed"]
        if updated is not item:
            update_item(paths.db_path, updated)
            if updated.markdown_path:
                # keep the rendered scroll's frontmatter in sync with the DB
                rendered = write_scroll(paths, updated)
                update_item(paths.db_path, rendered)
        if errors:
            counts["failed"] += 1
            results.append(
                {"id": item.id, "status": "failed", "error": errors[0], "files": files}
            )
        elif files:
            counts["captured"] += 1
            results.append({"id": item.id, "status": "captured", "files": files})
        else:
            counts["skipped"] += 1
            results.append(
                {
                    "id": item.id,
                    "status": "skipped",
                    "reason": "no media references to capture",
                }
            )

    print(json.dumps({**counts, "results": results}))
    return 1 if counts["failed"] else 0


def _cmd_agent_install() -> int:
    paths = get_paths()
    ensure_library(paths)
    installed = install_agent_docs(paths)
    print(json.dumps({"root": str(paths.root), "installed": installed}))
    return 0


def _cmd_kb(
    engine: str | None = None,
    batch: bool = False,
    stale: bool = False,
    source: str | None = None,
) -> int:
    paths = get_paths()
    explicit_engine = engine
    engine = engine or "deterministic"
    # `--source` is a *narrowing* of `--stale` (the per-source refresh, H172), not
    # a standalone selection: the worker reads "source web's summaries are stale"
    # off doctor's custody.summaries.by_source and refreshes just those. `--source`
    # alone has no stale set to narrow, so it is a loud usage error (the
    # `classify --source` posture, H154).
    if source is not None and not stale:
        print(
            json.dumps(
                {"error": "kb --source narrows the --stale refresh; pass --stale"}
            ),
            file=sys.stderr,
        )
        return 1
    if stale:
        # --stale refreshes *LLM concept summaries*, so it is an llm operation:
        # the deterministic compiler has no summaries to refresh. It forces the
        # llm engine regardless of the default; an explicit `--engine
        # deterministic` is a contradiction (the H27 explicit-vs-default posture).
        if explicit_engine == "deterministic":
            print(
                json.dumps(
                    {"error": "kb --stale re-synthesizes LLM concept summaries; "
                     "it cannot use --engine deterministic"}
                ),
                file=sys.stderr,
            )
            return 1
        engine = "llm"
    if batch and engine != "llm":
        print(
            json.dumps({"error": "--batch requires the llm engine (--engine llm)"}),
            file=sys.stderr,
        )
        return 1
    generation = {}
    if engine == "llm":
        # lazy: only the llm engine pays the import (ADR 0025)
        from scrolls.kb_llm import (
            generate_concept_summaries,
            generate_concept_summaries_batch,
        )
        from scrolls.llm import LLMError

        try:
            config = load_config(paths.config_path)
        except ConfigError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        counts = {"generated": 0, "current": 0, "failed": 0, "pruned": 0}
        results: list[dict] = []
        if paths.db_path.exists():  # kb never creates a library
            generate = (
                generate_concept_summaries_batch
                if batch
                else generate_concept_summaries
            )
            try:
                counts, results = generate(
                    paths.db_path,
                    model=resolve_llm_model(config),
                    stale_only=stale,
                    source=source,
                )
            except LLMError as exc:
                # whole-run failure (no credentials, or — for --batch — a
                # rejected submission): summaries saved before the abort
                # stay saved; the next run picks up where this one stopped
                print(json.dumps({"error": str(exc)}), file=sys.stderr)
                return 1
        generation = {**counts, "results": results}
    result = compile_kb(paths)
    print(json.dumps({**generation, **dataclasses.asdict(result)}))
    return 1 if generation.get("failed") else 0


def _cmd_list(
    source: str | None = None,
    stage: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
    fidelity: str | None = None,
    drift: str | None = None,
    stale_before: str | None = None,
    stale_classification: bool = False,
    stale_summary: bool = False,
    content_duplicate: bool = False,
    limit: int | None = None,
    stats: bool = False,
) -> int:
    paths = get_paths()
    scope = {
        "source": source,
        "category": category,
        "stage": stage,
        "tag": tag,
        "concept": concept,
        "fidelity": fidelity,
        "drift": drift,
        "stale_before": stale_before,
        # a boolean filter rides the `None`-is-pruned convention (scope_envelope):
        # echoed only when honored, so the scope names exactly the filters applied
        "stale_classification": True if stale_classification else None,
        "stale_summary": True if stale_summary else None,
        "content_duplicate": True if content_duplicate else None,
        "limit": limit,
    }
    # A `--stale-before` boundary normalizes through the one `checked_at`
    # vocabulary (the `--since` family precedent, H79/H75); a malformed boundary
    # is a loud usage error (exit 2) validated *before* the store read, so a typo
    # never masquerades as a checked-and-empty listing.
    try:
        boundary = parse_since(stale_before)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    if not paths.db_path.exists():
        # Empty in the surface's own shape, capped or not — never an error
        # (completeness contract G1). The --stats envelope says so explicitly:
        # a checked-and-empty library, scoped to the same facets — with a zeroed
        # custody tally (roadmap H98) and an empty `by_source` split (roadmap H155)
        # so the stats shape is stable even at empty.
        if stats:
            empty_custody = tally_custody([])
            empty_custody["by_source"] = tally_custody_by_source(())
            # the weakest-source flag is honestly `null` over an empty scope
            # (the `weakest_source` empty-map gate), so the stats shape stays
            # stable even at empty (roadmap H174).
            empty_custody["attention"] = weakest_source(
                empty_custody["by_source"], include_coverage=False
            )
            empty = scope_envelope([], scope=scope, matched=0, custody=empty_custody)
        else:
            empty = []
        print(json.dumps(empty))
        return 0
    matched_items = list_items(
        paths.db_path,
        stage=stage,
        source=source,
        category=category,
        tag=tag,
        concept=concept,
        fidelity=fidelity,
        drift=drift,
        stale_before=boundary,
        stale_classification=stale_classification,
        stale_summary=stale_summary,
        content_duplicate=content_duplicate,
    )
    matched = len(matched_items)
    items = matched_items[:limit] if limit is not None else matched_items
    # Work membership is a whole-library property (ADR 0101): a filtered listing
    # (e.g. source=arxiv) hides an item's sibling representation, so clustering
    # over the filtered rows would undercount it. Cluster over every item, then
    # annotate the rows this listing shows.
    membership = work_membership(list_items(paths.db_path))
    # One ledger read for the whole listing (the way `related`/`graph`/`search`
    # read it once): each row's `drift` posture is `drift_posture` over the same
    # `latest_events` `--drift` filtered on, so a row's shown posture matches the
    # `--drift X` it would be selected by, and the `facets drift` count for X. The
    # `last_checked` time axis (H84) reads the same verdict's timestamp.
    verdicts = latest_events(paths.db_path)
    rows = [
        item_summary(
            item,
            membership_payload(membership.get(item.id, ())),
            drift=drift_posture(verdicts.get(item.id)),
            last_checked=last_checked(verdicts.get(item.id)),
        )
        for item in items
    ]
    if not stats:
        print(json.dumps(rows))
        return 0
    # `stats.custody` (roadmap H98): the custody tally over the *matched* scope —
    # the full uncapped `matched_items`, not just the returned page — over the same
    # `verdicts` the rows' postures read, so the tier/posture counts sum to
    # `stats.matched` and (for a filter-only scope) equal `facets fidelity`/`drift`.
    custody = custody_counts(matched_items, verdicts)
    # `stats.custody.by_source` (roadmap H155): the same matched scope split per
    # source — each item's own `source`/`fidelity`/`drift`, the lean `{tiers, drift}`
    # shape `stats.custody` carries, summing to the whole-scope block beside it.
    custody["by_source"] = tally_custody_by_source(
        (item.source, get_fidelity(item), drift_posture(verdicts.get(item.id)))
        for item in matched_items
    )
    # `stats.custody.attention` (roadmap H174): the matched scope's single weakest
    # source distilled from the `by_source` map beside it — the browse-surface
    # counterpart of the `graph` flag (H164), via the same shared `weakest_source`.
    # The browse `by_source` is the *lean* projection (no per-source coverage, H155),
    # so `include_coverage=False` keeps the flag honest — no fabricated `0/0`.
    custody["attention"] = weakest_source(custody["by_source"], include_coverage=False)
    print(json.dumps(scope_envelope(rows, scope=scope, matched=matched, custody=custody)))
    return 0


def _cmd_facets(
    field: str | None,
    limit: int,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
) -> int:
    paths = get_paths()
    payload = compute_facets(
        paths.db_path,
        field=field,
        source=source,
        category=category,
        stage=stage,
        tag=tag,
        concept=concept,
        limit=limit,
    )
    print(json.dumps(payload))
    return 0


def _cmd_paths() -> int:
    paths = get_paths()
    print(
        json.dumps(
            {
                "root": str(paths.root),
                "items": str(paths.items_dir),
                "scrolls": str(paths.scrolls_dir),
                "library": str(paths.library_dir),
                "media": str(paths.media_dir),
                "agents": str(paths.agents_dir),
                "db": str(paths.db_path),
                "config": str(paths.config_path),
            }
        )
    )
    return 0


def _cmd_context(
    query: str,
    limit: int,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
    fidelity: str | None = None,
    drift: str | None = None,
    strength: str | None = None,
    content_duplicate: bool = False,
    budget: str = DEFAULT_CONTEXT_BUDGET,
) -> int:
    paths = get_paths()
    try:
        bundle = build_context(
            paths.db_path,
            query,
            limit=limit,
            source=source,
            category=category,
            stage=stage,
            tag=tag,
            concept=concept,
            fidelity=fidelity,
            drift=drift,
            strength=strength,
            content_duplicate=content_duplicate,
            budget=budget,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(bundle, end="")
    return 0


def _cmd_related(
    item_id: str,
    limit: int,
    stats: bool = False,
    fidelity: str | None = None,
    drift: str | None = None,
    strength: str | None = None,
    content_duplicate: bool = False,
) -> int:
    paths = get_paths()
    try:
        resolved = resolve_item_id(item_id)
        # The full custody-/rank-/content-filtered scored set (roadmap H254/H324/H350):
        # `filter_related` narrows per axis *before* the cap, so the bare view's
        # `[:limit]` returns the top neighbours at that value and the --stats
        # denominator counts the kept set. An unknown id and an unknown custody/rank
        # value both raise ValueError, so the could-not-check path is identical
        # (G1) — though argparse's `choices=` already rejects a bad CLI value
        # with exit 2 before we get here. `--content-duplicate` is a boolean property
        # (no closed vocab), so it folds the whole-library content sieve (H350) — the
        # twin may live anywhere, even outside the neighbourhood.
        duplicate_ids = (
            related_duplicate_ids(paths.db_path) if content_duplicate else None
        )
        hits = filter_related(
            scored_related(paths.db_path, resolved),
            fidelity=fidelity,
            drift=drift,
            strength=strength,
            duplicate_ids=duplicate_ids,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    if not stats:
        print(json.dumps(_related_rows(hits[:limit])))
        return 0
    matched = len(hits)
    rows = _related_rows(hits[:limit])
    # The custody/rank/content filters ride the scope echo so a reader holding only the
    # envelope recovers which neighbourhood it covered (G2); `None` is pruned
    # by `scope_envelope`, so an unfiltered call keeps the lean scope shape. The
    # content-duplicate flag echoes as a bare boolean (the H338 present/absent idiom).
    scope = {
        "item": resolved,
        "fidelity": fidelity,
        "drift": drift,
        "strength": strength,
        "content_duplicate": True if content_duplicate else None,
        "limit": limit,
    }
    # `stats.custody` (roadmap H99): the custody tally over the matched related
    # *neighbourhood* — the full scored `hits` (pre-cap), each already carrying its
    # own `fidelity`/`drift` (H56), so fold those through the same `tally_custody`
    # `search`/`list --stats` (H98) use. `scored_related` excludes the anchor, so
    # the tally answers "of the N items related to this one, how much is held in
    # full and how much has drifted" without folding in the anchor's own custody.
    custody = tally_custody((hit.fidelity, hit.drift) for hit in hits)
    # `stats.custody.by_source` (roadmap H155): the same neighbourhood split per
    # source, folding each hit's own `source`/`fidelity`/`drift` (the anchor stays
    # excluded), summing to the whole-scope `stats.custody` beside it.
    custody["by_source"] = tally_custody_by_source(
        (hit.source, hit.fidelity, hit.drift) for hit in hits
    )
    # `stats.custody.attention` (roadmap H174): the related neighbourhood's single
    # weakest source distilled from the lean `by_source` beside it (no per-source
    # coverage on the browse-stats projection, H155 — `include_coverage=False`).
    custody["attention"] = weakest_source(custody["by_source"], include_coverage=False)
    # `stats.strength` (roadmap H323): the relation-strength tally over the matched
    # neighbourhood, the H313 analogue on the relation axis — folding each hit's own
    # `relation_strength` (H322) the same way `search --stats` folds `match_strength`.
    # Partitions the matched scope (each hit has one band), so the counts sum to
    # `matched`, the drill-from-strength tie H324's `--strength` filter reads.
    strength = tally_relation_strength(hit.relation_strength for hit in hits)
    print(json.dumps(scope_envelope(
        rows, scope=scope, matched=matched, custody=custody, strength=strength
    )))
    return 0


def _related_rows(hits: list) -> list[dict]:
    """Related hits as JSON dicts, with `reasons` as a list (not a tuple)."""
    payload = [dataclasses.asdict(hit) for hit in hits]
    for hit in payload:
        hit["reasons"] = list(hit["reasons"])
    return payload


def _cmd_graph(include_all: bool, content_duplicate: bool = False) -> int:
    paths = get_paths()
    graph = build_graph(paths.db_path, include_isolated=include_all)
    # The content-identity node-set filter (roadmap H352): scope to nodes the
    # library holds a byte-identical copy of under another id, with the edges
    # induced among them — applied after the full graph is built so resolution is
    # intact (induced, not re-resolved over the subset) and it ANDs with --all.
    if content_duplicate:
        graph = content_duplicate_subgraph(graph)
    verdicts = latest_events(paths.db_path) if paths.db_path.exists() else {}
    print(json.dumps(graph_payload(graph, verdicts)))
    return 0


def _cmd_works(
    min_representations: int,
    ref: str | None = None,
    fidelity: str | None = None,
    drift: str | None = None,
    at_risk: bool = False,
    content_duplicate: bool = False,
) -> int:
    paths = get_paths()
    items = list_items(paths.db_path) if paths.db_path.exists() else []
    verdicts = latest_events(paths.db_path) if paths.db_path.exists() else {}
    # `--at-risk`/`--content-duplicate` are boolean predicates, not vocabulary values, so
    # each rides the scope echo only when set (`or None` → pruned by `to_payload` like an
    # unset facet, G2).
    at_risk_scope = at_risk or None
    content_duplicate_scope = content_duplicate or None
    try:
        if ref is not None:  # the per-item lens: this item's work(s) and siblings
            resolved = resolve_item_id(ref)
            works = works_for_item(items, resolved)
            # the per-item lens ignores --min, so the echoed scope is the anchor
            # (the resolved id, not the URL a caller may have passed) plus the
            # custody filters that narrowed it — G2
            scope = {
                "ref": resolved,
                "fidelity": fidelity,
                "drift": drift,
                "at_risk": at_risk_scope,
                "content_duplicate": content_duplicate_scope,
            }
        else:
            works = works_over(items, min_representations=min_representations)
            scope = {
                "min_representations": min_representations,
                "fidelity": fidelity,
                "drift": drift,
                "at_risk": at_risk_scope,
                "content_duplicate": content_duplicate_scope,
            }
        # The consolidation-surface custody sieve (roadmap H262/H265/H344): keep whole
        # works that contain a representation at the custody value(s), that no
        # representation safely holds (`--at-risk`), and/or that hold the same bytes
        # under two forms (`--content-duplicate`) — before `to_payload`, so
        # `stats.custody` partitions the reported set. An unknown id and an unknown
        # custody value both raise ValueError (the identical could-not-check path, G1),
        # though argparse `choices=` already rejects a bad CLI value with exit 2.
        works = filter_works(
            works,
            verdicts,
            fidelity=fidelity,
            drift=drift,
            at_risk=at_risk,
            content_duplicate=content_duplicate,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(works_payload(works, len(items), scope=scope, verdicts=verdicts)))
    return 0


def _cmd_rm(refs: list[str]) -> int:
    paths = get_paths()
    results = []
    counts = {"removed": 0, "failed": 0}
    for ref in refs:
        item, error = _find_item(paths, ref)
        if item is None:
            counts["failed"] += 1
            results.append({"ref": ref, "status": "failed", "error": error})
            continue
        try:
            files = remove_item(paths, item)
        except (OSError, ValueError) as exc:
            counts["failed"] += 1
            results.append({"ref": ref, "status": "failed", "error": str(exc)})
            continue
        counts["removed"] += 1
        # url is the receipt: `scrolls add <url>` re-registers the item
        results.append(
            {
                "ref": ref,
                "id": item.id,
                "url": item.url,
                "status": "removed",
                "files": files,
            }
        )

    print(json.dumps({**counts, "results": results}))
    return 1 if counts["failed"] else 0


def _cmd_search(
    query: str,
    limit: int,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
    stats: bool = False,
    fidelity: str | None = None,
    drift: str | None = None,
    strength: str | None = None,
    content_duplicate: bool = False,
) -> int:
    paths = get_paths()
    try:
        hits = search_items(
            paths.db_path,
            query,
            limit=limit,
            source=source,
            category=category,
            stage=stage,
            tag=tag,
            concept=concept,
            fidelity=fidelity,
            drift=drift,
            strength=strength,
            content_duplicate=content_duplicate,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    rows = [hit_payload(hit) for hit in hits]
    if not stats:
        print(json.dumps(rows))
        return 0
    # The honest denominator behind the truncation marker (G2): count every
    # match in scope, ignoring the cap, so `len(rows) == limit` no longer has
    # to mean "exactly the library's matches". The query already parsed above,
    # so this count never re-raises.
    matched = count_matches(
        paths.db_path,
        query,
        source=source,
        category=category,
        stage=stage,
        tag=tag,
        concept=concept,
        fidelity=fidelity,
        drift=drift,
        strength=strength,
        content_duplicate=content_duplicate,
    )
    # `stats.custody` (roadmap H98): the custody tally over the *matched* scope, not
    # just the returned page — each hit already carries its `fidelity`/`drift` (the
    # per-item parity, roadmap H58), so tally those, sourcing the full match set.
    # Reuse the page when nothing was hidden; only re-run uncapped when truncated
    # (the cap is the common case, so the extra scan is paid only when it adds rows).
    matched_hits = hits if matched <= len(hits) else search_items(
        paths.db_path, query, limit=matched, source=source, category=category,
        stage=stage, tag=tag, concept=concept, fidelity=fidelity, drift=drift,
        strength=strength, content_duplicate=content_duplicate,
    )
    custody = tally_custody((hit.fidelity, hit.drift) for hit in matched_hits)
    # `stats.custody.by_source` (roadmap H155): the query-matched scope split per
    # source, folding each hit's own `source`/`fidelity`/`drift` over the same full
    # match set, summing to the whole-scope `stats.custody` beside it.
    custody["by_source"] = tally_custody_by_source(
        (hit.source, hit.fidelity, hit.drift) for hit in matched_hits
    )
    # `stats.custody.attention` (roadmap H174): the query-matched scope's single
    # weakest source distilled from the lean `by_source` beside it (no per-source
    # coverage on the browse-stats projection, H155 — `include_coverage=False`).
    custody["attention"] = weakest_source(custody["by_source"], include_coverage=False)
    # `stats.strength` (roadmap H313): the rank-quality tally over the same matched
    # scope, beside `stats.custody` — each hit already carries its own
    # `match_strength` (H312), so fold those into the `{strong, moderate, weak}`
    # histogram. The bands partition the matched scope (sum to `stats.matched`), so
    # `--strength <band>` drills to the sum of the bands at or above `<band>` (H314).
    strength_tally = tally_strength(hit.match_strength for hit in matched_hits)
    scope = {
        "query": query,
        "source": source,
        "category": category,
        "stage": stage,
        "tag": tag,
        "concept": concept,
        "fidelity": fidelity,
        "drift": drift,
        "strength": strength,
        # the content-identity flag rides the `None`-is-pruned boolean convention
        # (H338): echoed only when honored, so the scope names exactly the filters
        "content_duplicate": True if content_duplicate else None,
        "limit": limit,
    }
    print(json.dumps(scope_envelope(
        rows, scope=scope, matched=matched, custody=custody, strength=strength_tally
    )))
    return 0


def _cmd_set(item_id: str, assignments: list[str]) -> int:
    paths = get_paths()
    item, error = _find_item(paths, item_id)
    if item is None:
        print(json.dumps({"error": error}), file=sys.stderr)
        return 1
    try:
        overrides = parse_assignments(assignments)
    except OverrideError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    updated = apply_overrides(item, overrides)
    if updated.markdown_path:
        # keep the rendered scroll's frontmatter in sync with the DB
        try:
            updated = write_scroll(paths, updated)
        except OSError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
    update_item(paths.db_path, updated)
    print(
        json.dumps(
            {
                "id": updated.id,
                "status": "set",
                "category": updated.category,
                "domain": updated.domain,
                "tags": list(updated.tags),
                "concepts": list(updated.concepts),
                "markdown_path": updated.markdown_path,
            }
        )
    )
    return 0


def _cmd_show(item_id: str) -> int:
    paths = get_paths()
    item, error = _find_item(paths, item_id)
    if item is None:
        print(json.dumps({"error": error}), file=sys.stderr)
        return 1
    payload = dataclasses.asdict(item)
    for name in ("tags", "concepts", "links", "media"):
        payload[name] = list(payload[name])
    # The derived per-item custody axes, so the inspect surface carries the same
    # picture `list`/`search` rows do (roadmap H61/H84): `fidelity` (how much is
    # held) from the item alone, and from the item's latest verify-ledger verdict
    # both `drift` (whether the source moved) and `last_checked` (as of when, or
    # null when never re-checked) — one ledger read, the same verdict.
    payload["fidelity"] = get_fidelity(item)
    events = item_events(paths.db_path, item.id)
    latest = events[0] if events else None
    payload["drift"] = drift_posture(latest)
    payload["last_checked"] = last_checked(latest)
    # The per-item content-identity siblings (roadmap H328): the *other* held ids
    # byte-identical to this one — "also held under X, Y" — the per-item read
    # companion of `doctor`'s whole-library `custody.content_duplicates` count,
    # empty when this content is unique. The custody-surface-propagation pattern
    # `fidelity`/`drift` already follow; reuses the H325 grouping primitive.
    payload["content_duplicate_ids"] = content_duplicate_ids(
        item, list_items(paths.db_path)
    )
    # The derived classification view alongside the raw provenance, so `show`
    # presents how the category was produced at parity with `list` (and MCP).
    classification = classification_provenance(item)
    if classification is not None:
        payload["classification"] = classification
    print(json.dumps(payload))
    return 0


def _cmd_history(
    item_id: str,
    limit: int | None = None,
    since: str | None = None,
    status: str | None = None,
) -> int:
    """Print one item's custody-ledger timeline, newest first (roadmap H66).

    `verify` appends an append-only custody event per check; `show`/`list` carry
    only the *latest* `drift` posture and `doctor`/`facets` only aggregate
    counts. This emits the ledger for one item — each
    ``{checked_at, status, prior_hash, observed_hash, detail}``, newest first —
    so an agent can see *when* a source drifted and *how often* it has been
    re-checked, the per-item counterpart of `maintain --history`'s scope-level
    trajectory. Three filter axes, applied verdict → time → count: `--status`
    keeps only checks with that verdict (roadmap H77 — "the times this source
    actually drifted"), `--since <ISO>` windows to checks at/after a boundary
    (roadmap H71), `--limit N` bounds to the most recent N (roadmap H69); each is
    off by default, so the whole timeline is the default. Read-only and honest: a
    known-but-never-verified item (or a filter/window nothing matches) is the
    empty `[]` (completeness G1, checked-and-empty), an *unknown* ref is a loud
    could-not-check error (exit 1) — the same empty-vs-error split
    `show`/`related` draw, so the per-item ledger never masquerades a typo as
    "no history" — and a malformed `--since` is a loud usage error (exit 2, the
    `maintain --trend` precedent), validated before the item lookup. `--status`
    is a closed vocabulary guarded by argparse `choices`.
    """
    try:
        boundary = parse_since(since)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    paths = get_paths()
    item, error = _find_item(paths, item_id)
    if item is None:
        print(json.dumps({"error": error}), file=sys.stderr)
        return 1
    print(
        json.dumps(
            item_history(
                paths.db_path, item.id, limit=limit, since=boundary, status=status
            )
        )
    )
    return 0


def _cmd_reconcile(ref: str, keep_held: bool, dry_run: bool = False) -> int:
    """Resolve a recorded import conflict by affirming the held copy (roadmap H276).

    The operator **act** on the conflict-on-import detection/read legs (ADR
    0104/0105): an import conflict surfaced by `import items`/`import bundle` and
    recorded as a `conflict` custody event (queryable via `scrolls history <id>
    --status conflict`, counted by `doctor`'s `custody.conflicts`) is here resolved
    on **explicit operator instruction**. The only resolution implemented is
    ``--keep-held``: affirm the held copy as authoritative, recording a `resolved`
    conflict-axis event that supersedes the open conflict. The held copy is **never
    overwritten** (raw is sacred, custody §2.4) and the original `conflict` event is
    never removed (append-only) — the divergence stays on the timeline while the
    alarm clears across `doctor`/the `_Conflicts:_` line (the shared
    `unresolved_conflicts` fold). ``--accept-incoming`` (adopt the peer's capture)
    is deferred: the incoming content is not retained, only its hash (ADR 0105).

    Honest and safe: a missing resolution flag is a loud usage error (exit 2, no
    write); an unknown ref is a could-not-check (exit 1, the `history`/`verify`
    split); a held item with **no** unresolved conflict is an idempotent no-op
    (``resolved: false``, exit 0) — so re-running after a resolution does nothing.
    ``--dry-run`` predicts the decision (the same payload the live run emits, plus
    ``dry_run: true``) and writes nothing — the "preview never drifts from reality"
    discipline (H245/H273) on the resolution axis.
    """
    paths = get_paths()
    if not keep_held:
        print(
            json.dumps(
                {"error": "reconcile needs a resolution: --keep-held (affirm the "
                 "held copy). --accept-incoming (adopt the peer's capture) is "
                 "deferred — the incoming content is not retained (ADR 0105)"}
            ),
            file=sys.stderr,
        )
        return 2
    item, error = _find_item(paths, ref)
    if item is None:
        print(json.dumps({"error": error}), file=sys.stderr)
        return 1
    conflict = current_conflict(paths.db_path, item)
    if conflict is None:
        # idempotent no-op: nothing unresolved to reconcile (already resolved,
        # never conflicted, or the held copy adopted the incoming content)
        print(
            json.dumps(
                {"id": item.id, "resolved": False, "decision": "keep_held",
                 "reason": "no unresolved import conflict", "dry_run": dry_run}
            )
        )
        return 0
    decision = {
        "id": item.id,
        "resolved": True,
        "decision": "keep_held",
        "held_hash": item.content_hash,
        "incoming_hash": conflict.observed_hash,
        "dry_run": dry_run,
    }
    if not dry_run:
        if paths.db_path.exists():
            init_db(paths.db_path)  # ensure the ledger table exists before recording
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        record_events(
            paths.db_path,
            [resolution_event(
                item.id,
                held_hash=item.content_hash,
                incoming_hash=conflict.observed_hash,
                now=now,
            )],
        )
    print(json.dumps(decision))
    return 0


def _cmd_archive_list(ref: str | None = None) -> int:
    """List archived prior captures — the accept-incoming recovery index (H278).

    Every held copy an `import … --accept-incoming` replaced was archived first
    (raw is never destroyed — custody §2.4, ADR 0106); this is the queryable index
    of what was superseded, newest first: the item id, the hash before/after, and
    when. ``--id`` scopes to one item (an id or its URL). Lightweight metadata only
    — the model-complete prior snapshot is fetched on demand by `archive show`.
    A pre-v8 / uninitialized library honestly holds nothing (empty list).
    """
    paths = get_paths()
    item_id: str | None = None
    if ref is not None:
        try:
            item_id = resolve_item_id(ref)
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
    entries = list_archived(paths.db_path, item_id) if paths.db_path.exists() else []
    print(json.dumps({
        "count": len(entries),
        "archived": [archive_entry_dict(entry) for entry in entries],
    }))
    return 0


def _cmd_archive_show(ref: str, all_history: bool = False) -> int:
    """Emit an item's archived prior capture(s) as re-importable JSONL line(s) (H278/H285).

    The recovery read (ADR 0106): the superseded copy/copies of the item, serialized
    in the exact `export items` JSONL shape, so restoring is just
    ``scrolls archive show <id> | scrolls import items /dev/stdin --accept-incoming``
    (the symmetric round-trip — accept-incoming of the archived snapshot re-adopts
    it, archiving the current copy in turn). The line(s) *are* the artifact, like
    `export items`, so they print raw to stdout.

    Default emits only the latest archived prior (one line). With ``--all`` (H285) it
    emits **every** archived prior for the id, newest first — the full recoverable
    history of a multi-supersession item, not just its newest copy. Either way exit 1
    when the id has no archived prior (never superseded) or is unknown — the
    could-not-recover signal.
    """
    paths = get_paths()
    try:
        item_id = resolve_item_id(ref)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    if not paths.db_path.exists():
        priors: list[ScrollItem] = []
    elif all_history:
        priors = archived_snapshots(paths.db_path, item_id)
    else:
        latest = latest_archived(paths.db_path, item_id)
        priors = [latest] if latest is not None else []
    if not priors:
        suffix = f" (from {ref})" if item_id != ref else ""
        print(
            json.dumps({"error": f"no archived prior capture for {item_id}{suffix}"}),
            file=sys.stderr,
        )
        return 1
    sys.stdout.write(dump_items_export(priors))
    return 0


def _restore_outcome(counts: dict[str, int]) -> str:
    """The single disposition of a one-prior restore — the readable ``outcome`` field.

    Exactly one prior feeds the accept-incoming merge, so exactly one count is set:
    ``adopted`` (the held copy was replaced by the chosen prior, the displaced copy
    itself archived), ``unchanged`` (the prior already *is* the held copy — the
    idempotent no-op), or ``imported`` (the id was absent — the archived prior
    re-created it). Read in that custody-priority order so the field names the write
    that actually happened.
    """
    for key in ("adopted", "imported", "unchanged"):
        if counts.get(key):
            return key
    return "unchanged"


def _cmd_archive_restore(
    ref: str,
    *,
    prior_hash: str | None = None,
    at: str | None = None,
    dry_run: bool = False,
) -> int:
    """Restore a *specific* archived prior in place — restore-by-version (H286, ADR 0106).

    `archive show <id> | import items --accept-incoming` already restores the
    **latest** archived prior; this picks a *specific* version and adopts it through
    the **same** custody-safe write (`_merge_items` accept-incoming → `adopt_incoming`),
    so there is **no new write path** — just a selection over the H285 archive history
    (`select_archived_snapshot`) feeding the existing adoption. ``--hash <prior_hash>``
    picks the archived prior with that content hash; ``--at <ISO>`` picks the newest
    prior archived at/before the boundary (the `verify --stale-before` normalization,
    inclusive); the default is the latest — byte-identical to `archive show`'s default
    (convergence by construction). At most one selector (the explicit gate); both is a
    usage error (exit 2).

    Custody-safe because the adoption archives the *currently-held* copy before
    replacing it (raw is never destroyed — custody §2.4): restoring an older version
    is fully reversible, and `archive show` afterward recovers the just-displaced
    copy. Idempotent: restoring the already-held content is an ``unchanged`` no-op
    (no archive row, no event). A deleted id whose archive survives is re-created
    from the prior (``imported``).

    Honest exits: an unresolvable ref is a usage error (exit 2, the `archive show`
    precedent); a malformed ``--at`` is a loud usage error (exit 2, the `archive
    prune --before` precedent); an id with no archived prior — or none matching the
    selector — is a could-not-recover (exit 1, the `archive show` signal).
    ``--dry-run`` predicts the decision (the same payload the live run emits, plus
    ``dry_run: true``) via the read-only `_preview_merge_items` and writes nothing —
    the "preview never drifts from reality" discipline (H245/H273).
    """
    paths = get_paths()
    try:
        item_id = resolve_item_id(ref)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    # at most one version selector — the explicit gate (the `archive prune` /
    # `reconcile` opt-in precedent); none means "the latest" (today's behavior)
    if prior_hash is not None and at is not None:
        print(
            json.dumps({
                "error": "archive restore takes at most one version selector: "
                "--hash <prior_hash> or --at <ISO> (default: the latest archived prior)"
            }),
            file=sys.stderr,
        )
        return 2
    boundary: str | None = None
    if at is not None:
        # a malformed --at is a loud usage error (exit 2, the `archive prune --before`
        # / `verify --stale-before` precedent), never a silently empty selection
        try:
            boundary = parse_since(at)
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        if boundary is None:
            print(
                json.dumps({"error": "--at needs an ISO-8601 timestamp boundary"}),
                file=sys.stderr,
            )
            return 2
    selector: dict = (
        {"hash": prior_hash} if prior_hash is not None
        else {"at": boundary} if boundary is not None
        else {"latest": True}
    )
    selected = (
        select_archived_snapshot(
            paths.db_path, item_id, prior_hash=prior_hash, at=boundary
        )
        if paths.db_path.exists()
        else None
    )
    if selected is None:
        suffix = f" (from {ref})" if item_id != ref else ""
        scoped = (
            f" matching {json.dumps(selector)}"
            if prior_hash is not None or boundary is not None
            else ""
        )
        print(
            json.dumps(
                {"error": f"no archived prior capture for {item_id}{suffix}{scoped}"}
            ),
            file=sys.stderr,
        )
        return 1
    entry, prior = selected
    held = get_item(paths.db_path, item_id)
    held_hash = held.content_hash if held is not None else None
    if dry_run:
        counts, _conflicts, _new, _held, adopted = _preview_merge_items(
            paths.db_path, [prior], accept_incoming=True
        )
    else:
        counts, _conflicts, adopted = _merge_items(
            paths.db_path, [prior], accept_incoming=True
        )
    outcome = _restore_outcome(counts)
    decision = {
        "id": item_id,
        "selector": selector,
        "prior_hash": entry.prior_hash,      # the restored version's content hash
        "archived_at": entry.archived_at,    # when that version was archived
        "held_hash": held_hash,              # what was held before (archived if adopted)
        "outcome": outcome,                  # adopted | unchanged | imported
        "restored": outcome in ("adopted", "imported"),
        "dry_run": dry_run,
    }
    if not dry_run:
        _warn_adopted(adopted)
    print(json.dumps(decision))
    return 0


def _cmd_archive_diff(
    ref: str,
    *,
    prior_hash: str | None = None,
    at: str | None = None,
) -> int:
    """Compare the held copy against a selected archived prior — decide-before-you-restore (H288).

    The read that answers "what would I get back, and what would I lose?" *before* the
    H286 `archive restore` writes anything. Folds the **same** `select_archived_snapshot`
    selector restore uses (``--hash``/``--at``, default the latest) against the
    currently-held copy (`get_item`), reporting the custody-relevant delta:

    - ``held_hash`` vs ``prior_hash`` — the captured-content fingerprints either side;
    - ``held_fidelity`` / ``prior_fidelity`` — each copy's custody-fidelity tier
      (`get_fidelity`, ADR 0097), so a degradation (full → partial) is visible before
      the swap;
    - ``changed_fields`` — the model-complete fields a restore would surface
      (`items.diff_snapshot`); and
    - ``would_restore`` — whether a restore would actually change the held copy (the
      H286 idempotency predicted as a read: the same ``content_hash`` compare
      `merge_item` makes — an absent id would be re-imported, an equal-hash prior is
      the held copy already, so the restore is an ``unchanged`` no-op).

    CLI-only read — it writes nothing (the `archive show` gate; the MCP twin is
    deferred). Honest exits mirror `archive restore`: an unresolvable ref is a usage
    error (exit 2); at most one version selector (exit 2); a malformed ``--at`` is a
    loud usage error (exit 2); an id with no archived prior — or none matching the
    selector — is a could-not-recover (exit 1).
    """
    paths = get_paths()
    try:
        item_id = resolve_item_id(ref)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    # at most one version selector — the explicit gate (the `archive restore` precedent)
    if prior_hash is not None and at is not None:
        print(
            json.dumps({
                "error": "archive diff takes at most one version selector: "
                "--hash <prior_hash> or --at <ISO> (default: the latest archived prior)"
            }),
            file=sys.stderr,
        )
        return 2
    boundary: str | None = None
    if at is not None:
        # a malformed --at is a loud usage error (exit 2), never a silently empty read
        try:
            boundary = parse_since(at)
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        if boundary is None:
            print(
                json.dumps({"error": "--at needs an ISO-8601 timestamp boundary"}),
                file=sys.stderr,
            )
            return 2
    selector: dict = (
        {"hash": prior_hash} if prior_hash is not None
        else {"at": boundary} if boundary is not None
        else {"latest": True}
    )
    selected = (
        select_archived_snapshot(
            paths.db_path, item_id, prior_hash=prior_hash, at=boundary
        )
        if paths.db_path.exists()
        else None
    )
    if selected is None:
        suffix = f" (from {ref})" if item_id != ref else ""
        scoped = (
            f" matching {json.dumps(selector)}"
            if prior_hash is not None or boundary is not None
            else ""
        )
        print(
            json.dumps(
                {"error": f"no archived prior capture for {item_id}{suffix}{scoped}"}
            ),
            file=sys.stderr,
        )
        return 1
    entry, prior = selected
    held = get_item(paths.db_path, item_id)
    held_hash = held.content_hash if held is not None else None
    # would a restore actually change the held copy? the H286 idempotency predicted
    # *before* the write — the same content_hash compare `merge_item` acts on (an
    # absent id would be re-imported; an equal-hash prior is the held copy already).
    would_restore = held is None or held.content_hash != prior.content_hash
    report = {
        "id": item_id,
        "selector": selector,
        "prior_hash": entry.prior_hash,                       # the prior's content hash
        "archived_at": entry.archived_at,                     # when that version was archived
        "held_hash": held_hash,                               # what is held now
        "held_fidelity": get_fidelity(held) if held is not None else None,
        "prior_fidelity": get_fidelity(prior),
        "changed_fields": diff_snapshot(held, prior),         # model-complete field delta
        "would_restore": would_restore,
    }
    print(json.dumps(report))
    return 0


def _warn_pruned(dropped: list) -> None:
    """Surface an applied archive prune on stderr (the `_warn_adopted` idiom).

    `archive prune --apply` *deletes* archived prior captures — the recovery store
    was shrunk. Even though the operator asked for it, that is a custody signal that
    rides stderr beside the structured report: how many priors were dropped, across
    which items, bounded with a ``(+N more)`` tail (the readable-surface cap). The
    held copies are untouched (the archive is a recovery convenience, not the root of
    trust — ADR 0106), so it is a `warning`, not an error. No-op on a 0-drop prune.
    """
    if not dropped:
        return
    item_ids = sorted({entry.item_id for entry in dropped})
    named = ", ".join(f"`{item_id}`" for item_id in item_ids[:_MAX_CONFLICT_IDS])
    if len(item_ids) > _MAX_CONFLICT_IDS:
        named += f" (+{len(item_ids) - _MAX_CONFLICT_IDS} more)"
    print(
        json.dumps({
            "warning": (
                f"pruned {len(dropped)} archived prior capture(s) across "
                f"{len(item_ids)} item(s) (held copies untouched): {named}"
            )
        }),
        file=sys.stderr,
    )


def _archive_prune_report(
    *, before: str | None, keep: int | None, drop: list, applied: bool, remaining: int
) -> dict:
    """The `archive prune` JSON report — the drop set, scalars, and per-item rollup.

    Shared by the report-only preview and the ``--apply`` run so both describe the
    same drop set (the H273 "predict the write" discipline). ``matched`` is the drop
    set size the policy selects; ``dropped`` is what was actually deleted (0 in
    preview, == ``matched`` after ``--apply``); ``remaining`` is the archive rows that
    survive. ``by_item`` rolls the drop set per item (newest-first item order), and
    ``archived`` carries the full entry dicts for review (the `archive list` shape).
    """
    policy = {"before": before} if before is not None else {"keep": keep}
    by_item: list[dict] = []
    counts: dict[str, int] = {}
    for entry in drop:  # newest-first; first sight fixes the item's report order
        if entry.item_id not in counts:
            by_item.append({"item_id": entry.item_id, "dropped": 0})
        counts[entry.item_id] = counts.get(entry.item_id, 0) + 1
    for row in by_item:
        row["dropped"] = counts[row["item_id"]]
    return {
        "policy": policy,
        "applied": applied,
        "matched": len(drop),
        "dropped": len(drop) if applied else 0,
        "remaining": remaining,
        "by_item": by_item,
        "archived": [archive_entry_dict(entry) for entry in drop],
    }


def _cmd_archive_prune(
    before: str | None, keep: int | None, apply: bool
) -> int:
    """Bound the append-only prior-content archive by a retention policy (H282).

    The archive grows on every accept-incoming adoption (and the symmetric restore
    round-trip). It is a **recovery convenience**, not the root of trust — raw is
    sacred for the *held* copy, and a superseded prior is already a deliberate
    replacement (ADR 0106 / custody §2.4) — so pruning it is custody-safe, but the
    act is explicit, report-only by default, and never touches a held row.

    Exactly one retention policy is required: ``--before ISO`` (drop priors archived
    before the boundary) or ``--keep N`` (per item, keep the most recent N, drop the
    rest). Neither / both is a usage error (exit 2 — the `reconcile --keep-held`
    opt-in gate). ``--keep`` needs N>=1, so the latest prior always survives and
    `archive show` keeps recovering it. Report-only by default — predict the drop set
    and write nothing (the H245/H273 dry-run discipline); ``--apply`` performs the
    deletion and warns loudly on stderr. Idempotent: a second ``--apply`` with the
    same policy drops nothing.
    """
    # exactly one policy — the explicit opt-in gate (a bare prune is a usage error,
    # the `reconcile <id>` without a resolution flag precedent)
    if (before is None) == (keep is None):
        print(
            json.dumps({
                "error": "archive prune needs exactly one retention policy: "
                "--before <ISO> or --keep <N>"
            }),
            file=sys.stderr,
        )
        return 2
    boundary: str | None = None
    if before is not None:
        # a malformed --before is a loud usage error (exit 2, the `verify
        # --stale-before` / `export events --since` precedent), never a silently
        # empty prune that could mask a typo'd boundary
        try:
            boundary = parse_since(before)
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        if boundary is None:
            print(
                json.dumps(
                    {"error": "--before needs an ISO-8601 timestamp boundary"}
                ),
                file=sys.stderr,
            )
            return 2
    if keep is not None and keep < 1:
        print(
            json.dumps({
                "error": "--keep needs N>=1 (the latest prior always survives a "
                "keep-prune so `archive show` can still recover it; use --before to "
                "drop regardless of recency)"
            }),
            file=sys.stderr,
        )
        return 2

    paths = get_paths()
    if not paths.db_path.exists():
        # an uninitialized / pre-v8 library honestly holds no archive — nothing to
        # prune, the empty-but-shaped report (the `archive list` honesty)
        print(json.dumps(_archive_prune_report(
            before=boundary, keep=keep, drop=[], applied=apply, remaining=0
        )))
        return 0

    if apply:
        dropped = prune_archive(paths.db_path, before=boundary, keep=keep)
        remaining = len(list_archived(paths.db_path))  # post-delete survivors
    else:
        dropped = select_prunable_archive(paths.db_path, before=boundary, keep=keep)
        remaining = len(list_archived(paths.db_path)) - len(dropped)  # would-remain
    report = _archive_prune_report(
        before=boundary, keep=keep, drop=dropped, applied=apply, remaining=remaining
    )
    if apply:
        _warn_pruned(dropped)
    print(json.dumps(report))
    return 0


def _cmd_status(source: str | None = None) -> int:
    paths = get_paths()
    schema_version = read_schema_version(paths.db_path)
    if schema_version is not None:
        items = library_counts(paths.db_path, source=source)
        subscriptions = len(list_subscriptions(paths.db_path))
    else:
        # an uninitialized library honestly holds nothing; zero-filled
        # counts keep the payload shape stable for agents
        items = {
            "total": 0,
            "by_stage": {"detected": 0, "fetched": 0, "rendered": 0},
            "by_source": {},
            "unclassified": 0,
        }
        subscriptions = 0
    # Custody headline (roadmap H38): the one-line "how custody stands" an agent
    # can read without parsing a full `doctor` report — integrity `score`,
    # fidelity `tiers`, the drift posture (checked/unverified/drifted/…), and the
    # stale enrichment/summary counts. Distilled from the same `run_doctor`
    # custody view (network-free) via the `custody_snapshot` primitive `maintain`
    # already records, so `status` can never disagree with `doctor` or a
    # maintenance snapshot (the H21/H25 convergence-by-construction posture).
    # `run_doctor` guards a missing store itself, so before `init` this is the
    # honest zero block (`score: null`), not an error.
    #
    # `--source` (roadmap H166) scopes the whole custody read to one source's held
    # items — the status-surface counterpart of `doctor --source` (H162), reusing
    # the same `run_doctor(source=)` pre-filter. Every block then reads one-source:
    # the `items` counts (narrowed via `library_counts(source=)` above), the custody
    # snapshot, the headline, and `by_source` (which collapses to the singleton
    # `{S: …}`). `attention` is naturally `null` under a single-source scope — the
    # `weakest_source` gate only flags a source that *stands out* across sources, and
    # one source has nothing to discriminate against (the documented H139/H119 gate).
    # An unknown source holds nothing → the honest empty headline, never an error.
    report = run_doctor(paths, source=source)
    custody = custody_snapshot(report)
    # The per-source custody breakdown the audit already produced (roadmap H133),
    # read faithfully via the shared primitive — computed once so the displayed map
    # and the `attention` flag distilled from it can never disagree.
    by_source = report_by_source(report)
    print(
        json.dumps(
            {
                "initialized": schema_version is not None,
                "root": str(paths.root),
                "schema_version": schema_version,
                "items": items,
                "subscriptions": subscriptions,
                "custody": custody,
                # The one-line custody picture (roadmap H117): the shared
                # `custody_headline` rendered from the snapshot above, so a reader
                # gets "how custody stands" without assembling the tiers/drift
                # counts — at full parity with the `maintain` report, which carries
                # both the structured block and the rendered line. Rendered from the
                # same snapshot it sits beside, so the two converge by construction;
                # before `init` the all-zero snapshot renders `_Custody: 0 scroll(s)._`
                # (never a fabricated count).
                "headline": snapshot_headline(custody),
                # The per-source custody breakdown (roadmap H133): the
                # `{tiers, drift, coverage}` tally split per source the same
                # `run_doctor` call already produced (`report["custody"]["by_source"]`,
                # H104) — so a reader of `status` sees *which* source's custody is
                # weakest without running `maintain`/`doctor`. A faithful read via the
                # shared `report_by_source` primitive `maintain` carries (H123): **no
                # new audit, no new ledger read**, the map is already computed in the
                # report above. Source keys sorted; the per-source tallies sum to the
                # `custody` block beside it by construction (every item lands in exactly
                # one source group, the H104 sum-to-whole posture), so `status`,
                # `maintain`, `doctor`, and `facets fidelity`/`drift --source <name>`
                # read one number. Honest absence: an empty/uninitialized library is
                # the empty `{}` map (no sources held).
                "by_source": by_source,
                # The single weakest source (roadmap H139): the one carrying the most
                # actionable loss (drifted + rotted), distilled from `by_source` via the
                # shared `weakest_source` primitive `maintain`'s `attention` uses (H119)
                # — so a human reading `status` sees not just *how much* is held and
                # drifted but *which source* most needs action, plus the exact `scrolls
                # verify --source <S>` recheck command (H137). Derived from the audit
                # `status` already makes (no new ledger read), so it converges with
                # `maintain`'s `attention` and `doctor`'s max-loss source by construction.
                # Honest `null` on the same three gates `maintain` uses — empty /
                # single-source / fully-clean (nothing stands out).
                "attention": weakest_source(by_source),
                # The per-source stale-classification debt (roadmap H177): doctor's
                # `custody.enrichment.by_source` map (H135) — a flat `{source:
                # stale_count}` of the offending sources only — read faithfully so an
                # agent reading `status` (its *primary* read surface) names *which*
                # source's `classify --stale` to run, at parity with the scheduled
                # worker's `maintain` report (H147). A pure read of the audit `status`
                # already makes (no new audit, no new ledger read), via the same
                # `report_enrichment_by_source` primitive `maintain` uses — so the two
                # surfaces report one number. Standalone member (not folded into the
                # drift `by_source`, so its H104 sum-to-whole stays untouched); sums to
                # `custody.enrichment_stale` by construction (each item one source).
                # `--source` collapses it to that source's debt (the scoped audit's
                # own map). Honest empty `{}` when no source carries stale debt or the
                # library is empty/uninitialized (the offenders-only posture).
                "enrichment_by_source": report_enrichment_by_source(report),
                # The per-source stale-summary debt (roadmap H177): doctor's
                # `custody.summaries.by_source` map (H171) — a flat `{source:
                # stale_count}` of the offending sources only — read faithfully so an
                # agent reading `status` names *which* source's `kb --stale` to run, at
                # parity with `maintain` (H175). The summary-axis sibling of
                # `enrichment_by_source`. Unlike that map it need **not** sum to
                # `summaries_stale`: a concept spanning several sources counts toward
                # each (the H171 asymmetry), so the status↔doctor tie is faithful-read
                # equality, never a sum-to-whole check. Honest empty `{}` when no source
                # carries stale-summary debt or the library is empty/uninitialized.
                "summary_by_source": report_summary_by_source(report),
            }
        )
    )
    return 0


def _cmd_detect(url: str) -> int:
    try:
        detected = detect_source(url)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({"source": detected.source, "source_id": detected.source_id}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
