"""The `scrolls` command-line interface.

Commands emit JSON on stdout so coding agents can consume them directly
(IDEAS.md §10: shell access first, MCP later).
"""

from __future__ import annotations

import argparse
import json
import sys

from scrolls import __version__
from scrolls.sources.detect import detect_source


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

    args = parser.parse_args(argv)

    if args.command == "detect":
        return _cmd_detect(args.url)
    return 2  # pragma: no cover - argparse enforces a valid command


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
