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
    parse_bundle,
    parse_bundle_events,
)
from scrolls.classify import classify_item, is_stale_classification
from scrolls.config import ConfigError, load_config, resolve_llm_model
from scrolls.custody import (
    CUSTODY_STATUSES,
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
    record_events,
    tally_custody,
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
from scrolls.graph import build_graph, to_payload as graph_payload
from scrolls.works import DEFAULT_MIN_REPRESENTATIONS as DEFAULT_WORK_MIN
from scrolls.works import (
    membership_payload,
    to_payload as works_payload,
    work_membership,
    works_for_item,
    works_over,
)
from scrolls.items import (
    ScrollItem,
    classification_provenance,
    get_fidelity,
    get_item,
    insert_item,
    item_summary,
    library_counts,
    list_items,
    update_item,
)
from scrolls.events_export import EventsSourceError, load_events_export
from scrolls.items_export import ItemsSourceError
from scrolls.items_export import dump_items_export, load_items_export
from scrolls.kb import compile_kb
from scrolls.maintain import (
    DEFAULT_HISTORY_LIMIT,
    append_log_entry,
    compute_delta,
    compute_trend,
    custody_snapshot,
    load_snapshot,
    log_path,
    read_log,
    save_snapshot,
    snapshot_path,
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
from scrolls.related import find_related, scored_related
from scrolls.remove import remove_item
from scrolls.render import write_scroll
from scrolls.scope import scope_envelope
from scrolls.search import count_matches, hit_payload, search_items
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
        choices=CUSTODY_STATUSES,
        default=None,
        help="Only checks with this verdict (unchanged/drifted/rotted/error) — "
        "e.g. the times this source actually drifted; composes with "
        "--since/--limit (verdict, then window, then cap)",
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
    import_bundle_parser = import_sub.add_parser(
        "bundle",
        help="Import scrolls from a custody bundle, losslessly (JSON output)",
    )
    import_bundle_parser.add_argument(
        "path",
        help="a custody bundle written by `scrolls export bundle`",
    )
    import_events_parser = import_sub.add_parser(
        "events",
        help="Restore custody events from a JSONL export, deduped (JSON output)",
    )
    import_events_parser.add_argument(
        "path",
        help="a JSONL custody-events export written by `scrolls export events`",
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
        help="Bound the drift recheck to N held items this run (oldest saved "
        "first); default rechecks every held item with a captured hash",
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

    subparsers.add_parser("status", help="Report library state (JSON output)")

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
        "--limit",
        type=int,
        default=None,
        help="Attempt at most N re-captures this run "
        "(--all/--unverified/--stale-before/--drift only), oldest saved first",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "add":
        return _cmd_add(args.url)
    if args.command == "agent":
        return _cmd_agent_install()
    if args.command == "classify":
        return _cmd_classify(args.id, args.engine, args.batch, args.stale)
    if args.command == "context":
        return _cmd_context(
            args.query,
            args.limit,
            args.source,
            args.category,
            args.stage,
            args.tag,
            args.concept,
            args.budget,
        )
    if args.command == "detect":
        return _cmd_detect(args.url)
    if args.command == "doctor":
        return _cmd_doctor(args.fix)
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
        return _cmd_graph(args.include_all)
    if args.command == "works":
        return _cmd_works(args.min_representations, args.ref)
    if args.command == "follow":
        return _cmd_follow(args.url)
    if args.command == "history":
        return _cmd_history(args.id, args.limit, args.since, args.status)
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
            return _cmd_import_items(args.path)
        if args.import_command == "bundle":
            return _cmd_import_bundle(args.path)
        if args.import_command == "events":
            return _cmd_import_events(args.path)
        return _cmd_import_fieldtheory(args.root)
    if args.command == "export":
        if args.export_command == "bookmarks":
            return _cmd_export_bookmarks(args.source, args.category, args.tag)
        if args.export_command == "items":
            return _cmd_export_items(args.source, args.category, args.tag)
        if args.export_command == "events":
            return _cmd_export_events(
                args.source, args.category, args.tag, args.since
            )
        if args.export_command == "bundle":
            return _cmd_export_bundle(
                args.query,
                args.source,
                args.category,
                args.stage,
                args.tag,
                args.concept,
            )
        return _cmd_export_opml()
    if args.command == "ingest":
        return _cmd_ingest(args.url)
    if args.command == "init":
        return _cmd_init()
    if args.command == "kb":
        return _cmd_kb(args.engine, args.batch, args.stale)
    if args.command == "list":
        return _cmd_list(
            args.source,
            args.stage,
            args.category,
            args.tag,
            args.concept,
            args.drift,
            args.stale_before,
            args.limit,
            args.stats,
        )
    if args.command == "maintain":
        if args.history is not None:
            return _cmd_maintain_history(args.history, args.trend)
        if args.trend:
            print(
                json.dumps({"error": "--trend requires --history"}), file=sys.stderr
            )
            return 2
        return _cmd_maintain(args.recheck, args.limit)
    if args.command == "mcp":
        return _cmd_mcp()
    if args.command == "md":
        return _cmd_md(args.id)
    if args.command == "media":
        return _cmd_media(args.id)
    if args.command == "paths":
        return _cmd_paths()
    if args.command == "related":
        return _cmd_related(args.id, args.limit, args.stats)
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
        )
    if args.command == "set":
        return _cmd_set(args.id, args.assignments)
    if args.command == "show":
        return _cmd_show(args.id)
    if args.command == "status":
        return _cmd_status()
    if args.command == "sync":
        return _cmd_sync(args.id)
    if args.command == "unfollow":
        return _cmd_unfollow(args.id)
    if args.command == "verify":
        return _cmd_verify(
            args.id, args.verify_all, args.unverified, args.limit, args.stale_before,
            args.drift,
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


def _cmd_doctor(fix: bool) -> int:
    paths = get_paths()
    payload = run_doctor(paths, fix=fix)
    print(json.dumps(payload))
    # healthy or fully repaired → 0; any drift left behind → 1
    return 1 if payload["issues"] > payload["fixed"] else 0


def _cmd_maintain(recheck: bool, limit: int | None) -> int:
    """One scheduled custody-maintenance pass (roadmap H22/H23/H34).

    The dogfood flow's recurring sibling, composed entirely from surfaces that
    already ship: *recheck* the live edge (`verify`, bounded by `--limit`, behind
    the `live_recapture` seam so it scripts offline), *regenerate* views
    (`compile_kb` — the deterministic compile, never an LLM re-synthesis), then
    *audit* once with `run_doctor` to read the post-maintenance custody picture,
    and report the **custody delta** against the snapshot the last run recorded.

    Report-only and idempotent (custody-vision §2.4): it records drift events and
    regenerates `library/` views, but never repairs index rows, reclassifies, or
    re-summarizes — `doctor --fix` / `classify --stale` / `kb --stale` stay the
    explicit, on-request mutations. The exit code mirrors `doctor`: nonzero only
    when structural `issues` remain (the operator should run `doctor --fix`);
    drift and stale enrichment/summaries are reported, never a failure.
    """
    paths = get_paths()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # 1. RECHECK — the one live edge, bounded; records drift events, never
    #    touching the captures (ADR 0098). Skipped entirely with --no-recheck.
    if recheck:
        recheck_report = _recheck_held_items(paths, limit, now)
    else:
        recheck_report = {
            "skipped": True, "checked": 0,
            "unchanged": 0, "drifted": 0, "rotted": 0, "error": 0,
        }

    # 2. REGENERATE views from canonical rows (views are regenerable).
    compiled = compile_kb(paths)

    # 3. AUDIT the post-maintenance state, read-only (maintain never --fixes).
    report = run_doctor(paths)
    current = custody_snapshot(report)

    # 4. DELTA vs the last recorded snapshot, then 5. record this run's: refresh
    #    the single baseline AND append the run to the append-only trend log.
    path = snapshot_path(paths)
    previous = load_snapshot(path)
    delta = compute_delta(previous, current)
    save_snapshot(path, {**current, "recorded_at": now})
    append_log_entry(
        log_path(paths),
        {"recorded_at": now, "snapshot": current, "delta": delta},
    )

    print(
        json.dumps(
            {
                "recorded_at": now,
                "recheck": recheck_report,
                "compiled": dataclasses.asdict(compiled),
                "custody": current,
                "delta": delta,
                "issues": report["issues"],
            }
        )
    )
    # nonzero only on structural drift the operator must address (mirrors doctor)
    return 1 if report["issues"] > 0 else 0


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
    if trend:
        print(json.dumps({"trend": compute_trend(runs), "runs": runs}))
    else:
        print(json.dumps(runs))
    return 0


def _recheck_held_items(paths: LibraryPaths, limit: int | None, now: str) -> dict:
    """Bounded re-capture of held items carrying a baseline hash; record events.

    The same core `verify --all` runs (re-capture through the `live_recapture`
    seam, diff the hash, append a custody event), distilled to the counts
    `maintain` reports. Reads the module-level `live_recapture` so tests can
    script the network edge offline, exactly as `_cmd_verify` does.
    """
    counts = {"skipped": False, "checked": 0,
              "unchanged": 0, "drifted": 0, "rotted": 0, "error": 0}
    if not paths.db_path.exists():
        return counts
    init_db(paths.db_path)  # ensure the ledger table exists before recording
    items = [item for item in list_items(paths.db_path) if item.content_hash]
    events = []
    for item in items:
        if limit is not None and counts["checked"] >= limit:
            break
        counts["checked"] += 1
        event = verify_item(item, live_recapture, now=now)
        events.append(event)
        counts[event.status] += 1
    record_events(paths.db_path, events)
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


def _cmd_import_items(path: str) -> int:
    try:
        imported_items, stats = load_items_export(Path(path).expanduser())
    except ItemsSourceError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    paths = get_paths()
    ensure_library(paths)
    counts = {"imported": 0, "skipped": 0}
    for item in imported_items:
        # INSERT OR IGNORE: an existing item (earlier import, or a manual
        # `add`/user edit) is never overwritten — re-imports stay cheap.
        # Derived artifacts rebuild from these rows: `doctor --fix` rewrites
        # missing scrolls and the FTS index, `kb` recompiles the library.
        if insert_item(paths.db_path, item):
            counts["imported"] += 1
        else:
            counts["skipped"] += 1

    print(json.dumps({**counts, **stats}))
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
    source: str | None, category: str | None, tag: str | None
) -> int:
    paths = get_paths()
    # the same durable-property facets `export bookmarks` offers scope the
    # export to a slice; they AND together and default to the whole library
    # (the backup case), in `list_items` saved order
    items = (
        list_items(paths.db_path, source=source, category=category, tag=tag)
        if paths.db_path.exists()
        else []
    )
    # the JSONL stream *is* the artifact, like `export opml`/`export bookmarks`,
    # so it prints raw — `scrolls export items > library.jsonl`
    sys.stdout.write(dump_items_export(items))
    return 0


def _cmd_export_events(
    source: str | None,
    category: str | None,
    tag: str | None,
    since: str | None = None,
) -> int:
    # whole-library portable custody (H72): the verify ledger as a lossless JSONL
    # stream, the custody sibling of `export items`. Scoped by the same
    # item-facet set (source/category/tag) — resolve the items, then their
    # events — so a slice's custody travels with the slice's items.
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
    items = (
        list_items(paths.db_path, source=source, category=category, tag=tag)
        if paths.db_path.exists()
        else []
    )
    events = (
        events_for_items(paths.db_path, [item.id for item in items], since=boundary)
        if items
        else []
    )
    # the JSONL stream *is* the artifact (the `export items` rule) —
    # `scrolls export events > ledger.jsonl`
    sys.stdout.write(dump_events_export(events))
    return 0


def _cmd_export_bundle(
    query: str,
    source: str | None,
    category: str | None,
    stage: str | None,
    tag: str | None,
    concept: str | None,
) -> int:
    paths = get_paths()
    try:
        # build_bundle tolerates a missing library (a valid empty bundle, no
        # library created — like `scrolls context` before `init`)
        bundle = build_bundle(
            paths.db_path,
            query,
            source=source,
            category=category,
            stage=stage,
            tag=tag,
            concept=concept,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    # the bundle Markdown *is* the artifact (the `context`/scroll exception to the
    # JSON-on-stdout rule) — `scrolls export bundle "<q>" > briefing.md`
    sys.stdout.write(bundle)
    return 0


def _cmd_import_bundle(path: str) -> int:
    try:
        text = Path(path).expanduser().read_text(encoding="utf-8")
        imported_items = parse_bundle(text)
        imported_events = parse_bundle_events(text)
    except OSError as exc:
        print(json.dumps({"error": f"cannot read {path}: {exc}"}), file=sys.stderr)
        return 1
    except BundleError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    paths = get_paths()
    ensure_library(paths)
    counts = {"imported": 0, "skipped": 0}
    for item in imported_items:
        # INSERT OR IGNORE (ADR 0082): a scroll the target library already holds
        # is never overwritten — custody-safe re-import. Derived artifacts rebuild
        # from these rows via `doctor --fix` / `kb`, as `import items` relies on.
        if insert_item(paths.db_path, item):
            counts["imported"] += 1
        else:
            counts["skipped"] += 1
    # restore the portable custody ledger (roadmap H67), deduped by content so a
    # re-import is a custody no-op — the verify-axis sibling of the items'
    # INSERT OR IGNORE. Events ride for *every* in-scope item, whether its row was
    # freshly inserted or already held (custody history merges), since dedup
    # prevents double-counting.
    ev_imported, ev_skipped = import_events(paths.db_path, imported_events)
    print(json.dumps({
        **counts,
        "items": len(imported_items),
        "events": {"imported": ev_imported, "skipped": ev_skipped},
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
    act-side sibling of `history --since` / `export events --since`), or
    `--drift <posture>` (the held, hash-bearing items currently at a chosen
    drift posture — the set `list --drift` enumerates and `facets drift`
    counts, so a worker re-checks the suspect set instead of `--all`). `error`
    (could-not-check) drives a nonzero exit; `drifted`/`rotted` are successful
    checks that found a custody event.
    """
    paths = get_paths()
    selections = (
        ref is not None, verify_all, unverified, stale_before is not None,
        drift is not None,
    )
    if sum(selections) != 1:
        print(
            json.dumps(
                {"error": "verify needs exactly one of an item id, --all, "
                 "--unverified, --stale-before, or --drift"}
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
                    {"error": "--limit paces --all/--unverified/--stale-before/--drift "
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
        # exactly doctor's custody.enrichment.stale set (one shared predicate);
        # zero the category so a re-classify recomputes it under the live
        # ruleset. An item the live ruleset no longer matches falls to
        # "unmatched" and its stored category is left untouched (non-destructive
        # — we surface that it no longer re-derives, we don't wipe it).
        everything = list_items(paths.db_path) if paths.db_path.exists() else []
        items = [
            dataclasses.replace(item, category=None)
            for item in everything
            if is_stale_classification(item)
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
    engine: str | None = None, batch: bool = False, stale: bool = False
) -> int:
    paths = get_paths()
    explicit_engine = engine
    engine = engine or "deterministic"
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
                    paths.db_path, model=resolve_llm_model(config), stale_only=stale
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
    drift: str | None = None,
    stale_before: str | None = None,
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
        "drift": drift,
        "stale_before": stale_before,
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
        # custody tally (roadmap H98) so the stats shape is stable even at empty.
        empty = (
            scope_envelope([], scope=scope, matched=0, custody=tally_custody([]))
            if stats else []
        )
        print(json.dumps(empty))
        return 0
    matched_items = list_items(
        paths.db_path,
        stage=stage,
        source=source,
        category=category,
        tag=tag,
        concept=concept,
        drift=drift,
        stale_before=boundary,
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
            budget=budget,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(bundle, end="")
    return 0


def _cmd_related(item_id: str, limit: int, stats: bool = False) -> int:
    paths = get_paths()
    try:
        resolved = resolve_item_id(item_id)
        # The full scored set when --stats needs the pre-cap denominator,
        # else just the capped public view. Both raise the same ValueError on
        # an unknown id, so the could-not-check path is identical (G1).
        hits = scored_related(paths.db_path, resolved) if stats else find_related(
            paths.db_path, resolved, limit=limit
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    if not stats:
        print(json.dumps(_related_rows(hits)))
        return 0
    matched = len(hits)
    rows = _related_rows(hits[:limit])
    scope = {"item": resolved, "limit": limit}
    # `stats.custody` (roadmap H99): the custody tally over the matched related
    # *neighbourhood* — the full scored `hits` (pre-cap), each already carrying its
    # own `fidelity`/`drift` (H56), so fold those through the same `tally_custody`
    # `search`/`list --stats` (H98) use. `scored_related` excludes the anchor, so
    # the tally answers "of the N items related to this one, how much is held in
    # full and how much has drifted" without folding in the anchor's own custody.
    custody = tally_custody((hit.fidelity, hit.drift) for hit in hits)
    print(json.dumps(scope_envelope(rows, scope=scope, matched=matched, custody=custody)))
    return 0


def _related_rows(hits: list) -> list[dict]:
    """Related hits as JSON dicts, with `reasons` as a list (not a tuple)."""
    payload = [dataclasses.asdict(hit) for hit in hits]
    for hit in payload:
        hit["reasons"] = list(hit["reasons"])
    return payload


def _cmd_graph(include_all: bool) -> int:
    paths = get_paths()
    graph = build_graph(paths.db_path, include_isolated=include_all)
    verdicts = latest_events(paths.db_path) if paths.db_path.exists() else {}
    print(json.dumps(graph_payload(graph, verdicts)))
    return 0


def _cmd_works(min_representations: int, ref: str | None = None) -> int:
    paths = get_paths()
    items = list_items(paths.db_path) if paths.db_path.exists() else []
    if ref is not None:  # the per-item lens: this item's work(s) and siblings
        try:
            resolved = resolve_item_id(ref)
            works = works_for_item(items, resolved)
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        # the per-item lens ignores --min, so the echoed scope is the anchor
        # alone (the resolved id, not the URL a caller may have passed) — G2
        scope = {"ref": resolved}
    else:
        works = works_over(items, min_representations=min_representations)
        scope = {"min_representations": min_representations}
    verdicts = latest_events(paths.db_path) if paths.db_path.exists() else {}
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
    )
    # `stats.custody` (roadmap H98): the custody tally over the *matched* scope, not
    # just the returned page — each hit already carries its `fidelity`/`drift` (the
    # per-item parity, roadmap H58), so tally those, sourcing the full match set.
    # Reuse the page when nothing was hidden; only re-run uncapped when truncated
    # (the cap is the common case, so the extra scan is paid only when it adds rows).
    matched_hits = hits if matched <= len(hits) else search_items(
        paths.db_path, query, limit=matched, source=source, category=category,
        stage=stage, tag=tag, concept=concept,
    )
    custody = tally_custody((hit.fidelity, hit.drift) for hit in matched_hits)
    scope = {
        "query": query,
        "source": source,
        "category": category,
        "stage": stage,
        "tag": tag,
        "concept": concept,
        "limit": limit,
    }
    print(json.dumps(scope_envelope(rows, scope=scope, matched=matched, custody=custody)))
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


def _cmd_status() -> int:
    paths = get_paths()
    schema_version = read_schema_version(paths.db_path)
    if schema_version is not None:
        items = library_counts(paths.db_path)
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
    custody = custody_snapshot(run_doctor(paths))
    print(
        json.dumps(
            {
                "initialized": schema_version is not None,
                "root": str(paths.root),
                "schema_version": schema_version,
                "items": items,
                "subscriptions": subscriptions,
                "custody": custody,
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
