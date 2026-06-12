"""The `scrolls` command-line interface.

Commands emit JSON on stdout so coding agents can consume them directly
(IDEAS.md §10: shell access first, MCP later).
"""

from __future__ import annotations

import argparse
import json
import sys

from scrolls import __version__
from scrolls.db import init_db, read_schema_version
from scrolls.paths import get_paths
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

    detect_parser = subparsers.add_parser(
        "detect", help="Detect which source adapter handles a URL (JSON output)"
    )
    detect_parser.add_argument("url", help="URL to inspect")

    subparsers.add_parser("init", help="Create the library skeleton (idempotent)")
    subparsers.add_parser("paths", help="Print the library layout (JSON output)")
    subparsers.add_parser("status", help="Report library state (JSON output)")

    args = parser.parse_args(argv)

    if args.command == "detect":
        return _cmd_detect(args.url)
    if args.command == "init":
        return _cmd_init()
    if args.command == "paths":
        return _cmd_paths()
    if args.command == "status":
        return _cmd_status()
    return 2  # pragma: no cover - argparse enforces a valid command


def _cmd_init() -> int:
    paths = get_paths()
    existed_before = paths.db_path.exists() and paths.config_path.exists() and all(
        d.is_dir() for d in paths.subdirs
    )
    paths.root.mkdir(parents=True, exist_ok=True)
    for subdir in paths.subdirs:
        subdir.mkdir(exist_ok=True)
    init_db(paths.db_path)
    if not paths.config_path.exists():
        paths.config_path.write_text(CONFIG_TEMPLATE)
    print(json.dumps({"root": str(paths.root), "created": not existed_before}))
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
