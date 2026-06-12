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

from scrolls import __version__
from scrolls.classify import classify_item
from scrolls.db import init_db, read_schema_version
from scrolls.items import (
    ScrollItem,
    get_item,
    insert_item,
    list_items,
    make_item_id,
    update_item,
)
from scrolls.kb import compile_kb
from scrolls.paths import LibraryPaths, get_paths
from scrolls.render import write_scroll
from scrolls.search import search_items
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.detect import detect_source

CONFIG_TEMPLATE = """\
# Scrolls configuration (no settings are read yet; this file is reserved
# for upcoming options such as [classify] engines).
"""


def main(argv: list[str] | None = None) -> int:
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

    classify_parser = subparsers.add_parser(
        "classify", help="Categorize items with the rules engine (JSON output)"
    )
    classify_parser.add_argument(
        "id",
        nargs="?",
        help="Classify one item by id, replacing any existing category; "
        "default is every fetched/rendered item without one",
    )

    detect_parser = subparsers.add_parser(
        "detect", help="Detect which source adapter handles a URL (JSON output)"
    )
    detect_parser.add_argument("url", help="URL to inspect")

    fetch_parser = subparsers.add_parser(
        "fetch", help="Fetch content for detected items (JSON output)"
    )
    fetch_parser.add_argument(
        "id",
        nargs="?",
        help="Fetch one item by id, refetching even if already fetched; "
        "default is every item at stage 'detected'",
    )

    ingest_parser = subparsers.add_parser(
        "ingest", help="Register, fetch, and render a URL in one step (JSON output)"
    )
    ingest_parser.add_argument("url", help="URL to ingest")

    subparsers.add_parser("init", help="Create the library skeleton (idempotent)")
    subparsers.add_parser(
        "kb", help="Compile the interlinked library pages (JSON output)"
    )
    subparsers.add_parser("list", help="List library items (JSON output)")

    md_parser = subparsers.add_parser(
        "md", help="Render fetched items as Markdown scrolls (JSON output)"
    )
    md_parser.add_argument(
        "id",
        nargs="?",
        help="Render one item by id, re-rendering even if already rendered; "
        "default is every item at stage 'fetched'",
    )
    subparsers.add_parser("paths", help="Print the library layout (JSON output)")

    search_parser = subparsers.add_parser(
        "search", help="Full-text search over items (JSON output)"
    )
    search_parser.add_argument("query", help="Free-text query; tokens are AND-ed")
    search_parser.add_argument(
        "--limit", type=int, default=20, help="Maximum hits to return (default 20)"
    )

    show_parser = subparsers.add_parser(
        "show", help="Print one item in full (JSON output)"
    )
    show_parser.add_argument("id", help="Item id, e.g. wikipedia:en:SQLite")

    subparsers.add_parser("status", help="Report library state (JSON output)")

    args = parser.parse_args(argv)

    if args.command == "add":
        return _cmd_add(args.url)
    if args.command == "classify":
        return _cmd_classify(args.id)
    if args.command == "detect":
        return _cmd_detect(args.url)
    if args.command == "fetch":
        return _cmd_fetch(args.id)
    if args.command == "ingest":
        return _cmd_ingest(args.url)
    if args.command == "init":
        return _cmd_init()
    if args.command == "kb":
        return _cmd_kb()
    if args.command == "list":
        return _cmd_list()
    if args.command == "md":
        return _cmd_md(args.id)
    if args.command == "paths":
        return _cmd_paths()
    if args.command == "search":
        return _cmd_search(args.query, args.limit)
    if args.command == "show":
        return _cmd_show(args.id)
    if args.command == "status":
        return _cmd_status()
    return 2  # pragma: no cover - argparse enforces a valid command


def _ensure_library(paths: LibraryPaths) -> bool:
    """Create the library skeleton if missing; return True if it already existed."""
    existed_before = paths.db_path.exists() and paths.config_path.exists() and all(
        d.is_dir() for d in paths.subdirs
    )
    paths.root.mkdir(parents=True, exist_ok=True)
    for subdir in paths.subdirs:
        subdir.mkdir(exist_ok=True)
    init_db(paths.db_path)
    if not paths.config_path.exists():
        paths.config_path.write_text(CONFIG_TEMPLATE)
    return existed_before


def _cmd_init() -> int:
    paths = get_paths()
    existed_before = _ensure_library(paths)
    print(json.dumps({"root": str(paths.root), "created": not existed_before}))
    return 0


def _register_url(url: str) -> tuple[LibraryPaths, ScrollItem, bool]:
    """Detect, ensure the library exists, and register the URL as an item.

    Returns the (existing) item and whether it was newly created; raises
    ValueError for URLs no adapter can handle.
    """
    detected = detect_source(url)
    paths = get_paths()
    _ensure_library(paths)
    cleaned = url.strip()
    item = ScrollItem(
        id=make_item_id(detected.source, detected.source_id, cleaned),
        source=detected.source,
        source_id=detected.source_id,
        url=cleaned,
        saved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    created = insert_item(paths.db_path, item)
    if not created:
        item = get_item(paths.db_path, item.id) or item
    return paths, item, created


def _cmd_add(url: str) -> int:
    try:
        _, item, created = _register_url(url)
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
        paths, item, created = _register_url(url)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    payload = {"id": item.id, "source": item.source, "url": item.url, "created": created}

    adapter = FETCH_ADAPTERS.get(item.source)
    if adapter is None:
        payload.update(
            {"stage": item.stage, "error": f"no fetch adapter for source '{item.source}'"}
        )
        print(json.dumps(payload))
        return 1
    try:
        fetched = adapter(item)
    except FetchError as exc:
        payload.update({"stage": item.stage, "error": str(exc)})
        print(json.dumps(payload))
        return 1
    update_item(paths.db_path, fetched)

    # classify before the first render so frontmatter carries the category;
    # an existing category (user override or earlier run) is never replaced
    if fetched.category is None:
        fetched = classify_item(fetched)

    rendered = write_scroll(paths, fetched)
    update_item(paths.db_path, rendered)
    payload.update(
        {
            "title": rendered.title,
            "category": rendered.category,
            "stage": rendered.stage,
            "markdown_path": rendered.markdown_path,
        }
    )
    print(json.dumps(payload))
    return 0


def _cmd_fetch(item_id: str | None) -> int:
    paths = get_paths()
    if item_id is not None:
        item = get_item(paths.db_path, item_id) if paths.db_path.exists() else None
        if item is None:
            print(json.dumps({"error": f"no such item: {item_id}"}), file=sys.stderr)
            return 1
        items = [item]
    else:
        items = list_items(paths.db_path, stage="detected") if paths.db_path.exists() else []

    results = []
    counts = {"fetched": 0, "skipped": 0, "failed": 0}
    for item in items:
        adapter = FETCH_ADAPTERS.get(item.source)
        if adapter is None:
            # Bulk runs leave adapterless items for a future scrolls; asking
            # for one by id deserves an honest failure.
            if item_id is None:
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


def _cmd_classify(item_id: str | None) -> int:
    paths = get_paths()
    if item_id is not None:
        item = get_item(paths.db_path, item_id) if paths.db_path.exists() else None
        if item is None:
            print(json.dumps({"error": f"no such item: {item_id}"}), file=sys.stderr)
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

    results = []
    counts = {"classified": 0, "unmatched": 0, "failed": 0}
    for item in items:
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
        results.append(
            {"id": classified.id, "status": "classified", "category": classified.category}
        )

    print(json.dumps({**counts, "results": results}))
    return 1 if counts["failed"] else 0


def _cmd_md(item_id: str | None) -> int:
    paths = get_paths()
    if item_id is not None:
        item = get_item(paths.db_path, item_id) if paths.db_path.exists() else None
        if item is None:
            print(json.dumps({"error": f"no such item: {item_id}"}), file=sys.stderr)
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


def _cmd_kb() -> int:
    paths = get_paths()
    result = compile_kb(paths)
    print(json.dumps(dataclasses.asdict(result)))
    return 0


def _cmd_list() -> int:
    paths = get_paths()
    items = list_items(paths.db_path) if paths.db_path.exists() else []
    print(
        json.dumps(
            [
                {
                    "id": item.id,
                    "source": item.source,
                    "url": item.url,
                    "title": item.title,
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
                "db": str(paths.db_path),
                "config": str(paths.config_path),
            }
        )
    )
    return 0


def _cmd_search(query: str, limit: int) -> int:
    paths = get_paths()
    try:
        hits = search_items(paths.db_path, query, limit=limit)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps([dataclasses.asdict(hit) for hit in hits]))
    return 0


def _cmd_show(item_id: str) -> int:
    paths = get_paths()
    item = get_item(paths.db_path, item_id) if paths.db_path.exists() else None
    if item is None:
        print(json.dumps({"error": f"no such item: {item_id}"}), file=sys.stderr)
        return 1
    payload = dataclasses.asdict(item)
    for name in ("tags", "concepts", "links", "media"):
        payload[name] = list(payload[name])
    print(json.dumps(payload))
    return 0


def _cmd_status() -> int:
    paths = get_paths()
    schema_version = read_schema_version(paths.db_path)
    print(
        json.dumps(
            {
                "initialized": schema_version is not None,
                "root": str(paths.root),
                "schema_version": schema_version,
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
