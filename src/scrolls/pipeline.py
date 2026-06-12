"""Library lifecycle and the one-URL ingest chain (IDEAS.md §4-5).

The importable engine behind `scrolls add`/`scrolls ingest` and the MCP
server's `ingest_url` tool (ADR 0014). The CLI owns process concerns —
JSON printing, exit codes — while this module owns registering a URL and
carrying it through add → fetch → classify → md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scrolls.classify import classify_item
from scrolls.db import init_db
from scrolls.items import ScrollItem, get_item, insert_item, make_item_id, update_item
from scrolls.paths import LibraryPaths, get_paths
from scrolls.render import write_scroll
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.detect import detect_source
from scrolls.sources.urls import normalize_url

CONFIG_TEMPLATE = """\
# Scrolls configuration. Settings read today (ADR 0016):
#
# [classify]
# default_engine = "rules"        # engine for `scrolls classify` without
#                                 # --engine: "rules" or "llm"
# llm_model = "claude-opus-4-8"   # model for the llm engine; the
#                                 # SCROLLS_LLM_MODEL env var overrides it
"""


def ensure_library(paths: LibraryPaths) -> bool:
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


def register_url(url: str) -> tuple[LibraryPaths, ScrollItem, bool]:
    """Detect, ensure the library exists, and register the URL as an item.

    Returns the (existing) item and whether it was newly created; raises
    ValueError for URLs no adapter can handle. The URL is normalized
    first (ADR 0023) — tracking params, fragments, host casing — so one
    resource saved via different decorated links stays one item.
    """
    cleaned = normalize_url(url)
    detected = detect_source(cleaned)
    paths = get_paths()
    ensure_library(paths)
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


def ingest_url(url: str) -> dict[str, Any]:
    """Run add → fetch → classify → md for one URL; return the result payload.

    Raises ValueError for non-http(s) URLs. Fetch problems do not raise:
    the item stays registered at stage 'detected' and the payload carries
    an `error` key (the CLI exits 1 on it; MCP clients read it as data).
    An existing category — user-set or from an earlier run — is never
    replaced, so re-ingesting refreshes content only.
    """
    paths, item, created = register_url(url)
    payload: dict[str, Any] = {
        "id": item.id,
        "source": item.source,
        "url": item.url,
        "created": created,
    }

    adapter = FETCH_ADAPTERS.get(item.source)
    if adapter is None:
        payload.update(
            {"stage": item.stage, "error": f"no fetch adapter for source '{item.source}'"}
        )
        return payload
    try:
        fetched = adapter(item)
    except FetchError as exc:
        payload.update({"stage": item.stage, "error": str(exc)})
        return payload
    update_item(paths.db_path, fetched)

    # classify before the first render so frontmatter carries the category
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
    return payload
