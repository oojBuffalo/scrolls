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
from scrolls.classify import classify_item
from scrolls.config import ConfigError, load_config, resolve_llm_model
from scrolls.context import DEFAULT_LIMIT as DEFAULT_CONTEXT_LIMIT
from scrolls.context import build_context
from scrolls.db import read_schema_version
from scrolls.fieldtheory import DEFAULT_ROOT as FIELDTHEORY_ROOT
from scrolls.fieldtheory import ImportSourceError, load_bookmarks
from scrolls.items import get_item, insert_item, list_items, update_item
from scrolls.kb import compile_kb
from scrolls.media import capture_media, has_pending_media
from scrolls.paths import get_paths
from scrolls.pipeline import ensure_library, ingest_url, register_url
from scrolls.related import DEFAULT_LIMIT as DEFAULT_RELATED_LIMIT
from scrolls.related import find_related
from scrolls.render import write_scroll
from scrolls.search import search_items
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.detect import detect_source


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
        help="Classify one item by id, replacing any existing category; "
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

    import_parser = subparsers.add_parser(
        "import", help="Bulk-import a local archive (JSON output)"
    )
    import_sub = import_parser.add_subparsers(dest="import_command", required=True)
    fieldtheory_parser = import_sub.add_parser(
        "fieldtheory",
        help="Import X bookmarks from a local Field Theory archive (JSON output)",
    )
    fieldtheory_parser.add_argument(
        "--root",
        default=None,
        help=f"Field Theory archive root (default {FIELDTHEORY_ROOT})",
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
        help="Render one item by id, re-rendering even if already rendered; "
        "default is every item at stage 'fetched'",
    )
    media_parser = subparsers.add_parser(
        "media",
        help="Download items' media references into media/ (JSON output)",
    )
    media_parser.add_argument(
        "id",
        nargs="?",
        help="Capture one item's media by id, re-downloading even if captured; "
        "default is every item with uncaptured media references",
    )

    subparsers.add_parser("paths", help="Print the library layout (JSON output)")

    related_parser = subparsers.add_parser(
        "related", help="Find items related to one item (JSON output)"
    )
    related_parser.add_argument("id", help="Item id, e.g. x:1111")
    related_parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_RELATED_LIMIT,
        help=f"Maximum hits to return (default {DEFAULT_RELATED_LIMIT})",
    )

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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "add":
        return _cmd_add(args.url)
    if args.command == "agent":
        return _cmd_agent_install()
    if args.command == "classify":
        return _cmd_classify(args.id, args.engine)
    if args.command == "context":
        return _cmd_context(args.query, args.limit)
    if args.command == "detect":
        return _cmd_detect(args.url)
    if args.command == "fetch":
        return _cmd_fetch(args.id)
    if args.command == "import":
        return _cmd_import_fieldtheory(args.root)
    if args.command == "ingest":
        return _cmd_ingest(args.url)
    if args.command == "init":
        return _cmd_init()
    if args.command == "kb":
        return _cmd_kb()
    if args.command == "list":
        return _cmd_list()
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
    if args.command == "search":
        return _cmd_search(args.query, args.limit)
    if args.command == "show":
        return _cmd_show(args.id)
    if args.command == "status":
        return _cmd_status()
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


def _cmd_mcp() -> int:
    # lazy: only `scrolls mcp` pays the SDK import (ADR 0014)
    from scrolls.mcp_server import run

    run()  # blocks serving stdio until the client disconnects
    return 0


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


def _cmd_classify(item_id: str | None, engine: str | None = None) -> int:
    paths = get_paths()
    try:
        config = load_config(paths.config_path)
    except ConfigError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    # the --engine flag beats config.toml's [classify] default_engine
    engine = engine or config.default_engine

    if engine == "llm":
        # lazy: only the llm engine pays the import (ADR 0015)
        from scrolls.classify_llm import (
            LLMAuthError,
            LLMClassifyError,
            classify_item_llm,
        )

        llm_model = resolve_llm_model(config)

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
        if engine == "llm":
            try:
                classified = classify_item_llm(item, model=llm_model)
            except LLMAuthError as exc:
                # no credentials: every remaining item would fail the same way
                print(json.dumps({"error": str(exc)}), file=sys.stderr)
                return 1
            except LLMClassifyError as exc:
                counts["failed"] += 1
                results.append({"id": item.id, "status": "failed", "error": str(exc)})
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


def _cmd_media(item_id: str | None) -> int:
    paths = get_paths()
    if item_id is not None:
        item = get_item(paths.db_path, item_id) if paths.db_path.exists() else None
        if item is None:
            print(json.dumps({"error": f"no such item: {item_id}"}), file=sys.stderr)
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
                "agents": str(paths.agents_dir),
                "db": str(paths.db_path),
                "config": str(paths.config_path),
            }
        )
    )
    return 0


def _cmd_context(query: str, limit: int) -> int:
    paths = get_paths()
    try:
        bundle = build_context(paths.db_path, query, limit=limit)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(bundle, end="")
    return 0


def _cmd_related(item_id: str, limit: int) -> int:
    paths = get_paths()
    try:
        hits = find_related(paths.db_path, item_id, limit=limit)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    payload = [dataclasses.asdict(hit) for hit in hits]
    for hit in payload:
        hit["reasons"] = list(hit["reasons"])
    print(json.dumps(payload))
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
