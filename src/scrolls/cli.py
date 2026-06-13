"""The `scrolls` command-line interface.

Commands emit JSON on stdout so coding agents can consume them directly
(IDEAS.md §10: shell access first, MCP later).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from scrolls import __version__
from scrolls.agents import install_agent_docs
from scrolls.bookmarks import ImportSourceError as BookmarksSourceError
from scrolls.bookmarks import load_bookmark_export
from scrolls.classify import classify_item
from scrolls.config import ConfigError, load_config, resolve_llm_model
from scrolls.context import DEFAULT_LIMIT as DEFAULT_CONTEXT_LIMIT
from scrolls.context import build_context
from scrolls.db import read_schema_version
from scrolls.doctor import run_doctor
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
from scrolls.works import to_payload as works_payload, works_for_item, works_over
from scrolls.items import (
    ScrollItem,
    get_item,
    insert_item,
    library_counts,
    list_items,
    update_item,
)
from scrolls.kb import compile_kb
from scrolls.media import capture_media, has_pending_media
from scrolls.overrides import OverrideError, apply_overrides, parse_assignments
from scrolls.paths import LibraryPaths, get_paths
from scrolls.opml import ImportSourceError as OPMLSourceError
from scrolls.opml import load_opml_export
from scrolls.pipeline import ensure_library, ingest_url, register_url, resolve_item_id
from scrolls.pocket import ImportSourceError as PocketSourceError
from scrolls.pocket import load_pocket_export
from scrolls.related import DEFAULT_LIMIT as DEFAULT_RELATED_LIMIT
from scrolls.related import find_related
from scrolls.remove import remove_item
from scrolls.render import write_scroll
from scrolls.search import search_items
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
        default="deterministic",
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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "add":
        return _cmd_add(args.url)
    if args.command == "agent":
        return _cmd_agent_install()
    if args.command == "classify":
        return _cmd_classify(args.id, args.engine, args.batch)
    if args.command == "context":
        return _cmd_context(
            args.query,
            args.limit,
            args.source,
            args.category,
            args.stage,
            args.tag,
            args.concept,
        )
    if args.command == "detect":
        return _cmd_detect(args.url)
    if args.command == "doctor":
        return _cmd_doctor(args.fix)
    if args.command == "fetch":
        return _cmd_fetch(args.id, args.limit)
    if args.command == "graph":
        return _cmd_graph(args.include_all)
    if args.command == "works":
        return _cmd_works(args.min_representations, args.ref)
    if args.command == "follow":
        return _cmd_follow(args.url)
    if args.command == "import":
        if args.import_command == "bookmarks":
            return _cmd_import_bookmarks(args.path)
        if args.import_command == "google-takeout":
            return _cmd_import_takeout(args.path)
        if args.import_command == "pocket":
            return _cmd_import_pocket(args.path)
        if args.import_command == "opml":
            return _cmd_import_opml(args.path)
        return _cmd_import_fieldtheory(args.root)
    if args.command == "ingest":
        return _cmd_ingest(args.url)
    if args.command == "init":
        return _cmd_init()
    if args.command == "kb":
        return _cmd_kb(args.engine, args.batch)
    if args.command == "list":
        return _cmd_list(
            args.source, args.stage, args.category, args.tag, args.concept
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
        return _cmd_related(args.id, args.limit)
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


def _cmd_classify(
    item_id: str | None, engine: str | None = None, batch: bool = False
) -> int:
    paths = get_paths()
    try:
        config = load_config(paths.config_path)
    except ConfigError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    # the --engine flag beats config.toml's [classify] default_engine
    engine = engine or config.default_engine

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


def _cmd_kb(engine: str = "deterministic", batch: bool = False) -> int:
    paths = get_paths()
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
                    paths.db_path, model=resolve_llm_model(config)
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
) -> int:
    paths = get_paths()
    items = (
        list_items(
            paths.db_path,
            stage=stage,
            source=source,
            category=category,
            tag=tag,
            concept=concept,
        )
        if paths.db_path.exists()
        else []
    )
    print(
        json.dumps(
            [
                {
                    "id": item.id,
                    "source": item.source,
                    "url": item.url,
                    "title": item.title,
                    "category": item.category,
                    "stage": item.stage,
                    "saved_at": item.saved_at,
                }
                for item in items
            ]
        )
    )
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
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(bundle, end="")
    return 0


def _cmd_related(item_id: str, limit: int) -> int:
    paths = get_paths()
    try:
        hits = find_related(paths.db_path, resolve_item_id(item_id), limit=limit)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    payload = [dataclasses.asdict(hit) for hit in hits]
    for hit in payload:
        hit["reasons"] = list(hit["reasons"])
    print(json.dumps(payload))
    return 0


def _cmd_graph(include_all: bool) -> int:
    paths = get_paths()
    graph = build_graph(paths.db_path, include_isolated=include_all)
    print(json.dumps(graph_payload(graph)))
    return 0


def _cmd_works(min_representations: int, ref: str | None = None) -> int:
    paths = get_paths()
    items = list_items(paths.db_path) if paths.db_path.exists() else []
    if ref is not None:  # the per-item lens: this item's work(s) and siblings
        try:
            works = works_for_item(items, resolve_item_id(ref))
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
    else:
        works = works_over(items, min_representations=min_representations)
    print(json.dumps(works_payload(works, len(items))))
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
    print(json.dumps([dataclasses.asdict(hit) for hit in hits]))
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
    print(json.dumps(payload))
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
    print(
        json.dumps(
            {
                "initialized": schema_version is not None,
                "root": str(paths.root),
                "schema_version": schema_version,
                "items": items,
                "subscriptions": subscriptions,
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
