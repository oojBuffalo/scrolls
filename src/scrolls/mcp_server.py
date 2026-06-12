"""MCP server: the library over the Model Context Protocol (IDEAS.md §10, ADR 0014).

`scrolls mcp` serves the same engines the CLI exposes — search, items,
related, context bundles, concept pages, ingest, feed subscriptions
(ADR 0020), KB compilation (deterministic only: an MCP tool must never
trigger paid API calls, so `kb --engine llm` stays a CLI step) — as MCP
tools over stdio, for agents that speak the
protocol instead of (or alongside) the shell. Tool functions are plain sync wrappers, defined apart from the
server so tests exercise them directly; the official SDK is imported
lazily so every other command stays free of it. Read tools mirror the
CLI conventions: an empty library returns empty results, unknown ids
raise (FastMCP turns the exception into a tool error for the client).
"""

from __future__ import annotations

import dataclasses
from typing import Any

from scrolls import feeds
from scrolls.context import DEFAULT_LIMIT as DEFAULT_CONTEXT_LIMIT
from scrolls.context import build_context
from scrolls.items import count_by_source, get_item
from scrolls.kb import compile_kb
from scrolls.paths import get_paths
from scrolls.pipeline import ingest_url as _ingest_url
from scrolls.related import DEFAULT_LIMIT as DEFAULT_RELATED_LIMIT
from scrolls.related import find_related
from scrolls.render import slugify
from scrolls.search import DEFAULT_LIMIT as DEFAULT_SEARCH_LIMIT
from scrolls.search import search_items

SERVER_NAME = "scrolls"

_INSTRUCTIONS = (
    "Search the user's saved internet artifacts (tweets, papers, videos, "
    "articles, repos) compiled as a local knowledge library. Start with "
    "get_context_bundle for a compact, citable overview of a topic; use "
    "search_scrolls and get_scroll for depth, get_related_scrolls and "
    "get_concept_page to follow connections, and ingest_url to save "
    "something new. follow_feed subscribes the library to an RSS/Atom "
    "feed and sync_feeds registers its new entries. compile_library "
    "rebuilds the knowledge-base pages get_concept_page serves."
)


def search_scrolls(query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[dict[str, Any]]:
    """Full-text search over the library; hits are best-first with snippets.

    `score` is SQLite bm25(): more negative means a stronger match.
    """
    paths = get_paths()
    return [dataclasses.asdict(hit) for hit in search_items(paths.db_path, query, limit=limit)]


def get_scroll(item_id: str) -> dict[str, Any]:
    """One saved item in full: metadata, summary, extracted text, links, media."""
    paths = get_paths()
    item = get_item(paths.db_path, item_id) if paths.db_path.exists() else None
    if item is None:
        raise ValueError(f"no such item: {item_id}")
    payload = dataclasses.asdict(item)
    for name in ("tags", "concepts", "links", "media"):
        payload[name] = list(payload[name])
    return payload


def get_related_scrolls(
    item_id: str, limit: int = DEFAULT_RELATED_LIMIT
) -> list[dict[str, Any]]:
    """Items connected to one item — link edges, shared concepts/tags — with reasons."""
    paths = get_paths()
    if not paths.db_path.exists():
        raise ValueError(f"no such item: {item_id}")
    hits = [dataclasses.asdict(hit) for hit in find_related(paths.db_path, item_id, limit=limit)]
    for hit in hits:
        hit["reasons"] = list(hit["reasons"])
    return hits


def get_context_bundle(query: str, limit: int = DEFAULT_CONTEXT_LIMIT) -> str:
    """A compact Markdown bundle for a topic: best matches, excerpts, source links.

    The bundle is designed to be dropped directly into model context.
    """
    paths = get_paths()
    return build_context(paths.db_path, query, limit=limit)


def get_concept_page(concept: str) -> str:
    """The compiled knowledge-base page for one concept, as Markdown.

    Spellings are matched by slug ("BM25" and "bm25" are the same page).
    """
    paths = get_paths()
    page = paths.library_dir / "concepts" / f"{slugify(concept)}.md"
    if not page.exists():
        raise ValueError(
            f"no concept page for {concept!r} — compile the library first "
            "(the compile_library tool, or `scrolls kb`)"
        )
    return page.read_text(encoding="utf-8")


def list_sources() -> dict[str, int]:
    """Item counts per source (wikipedia, arxiv, x, ...) in the library."""
    paths = get_paths()
    if not paths.db_path.exists():
        return {}
    return count_by_source(paths.db_path)


def ingest_url(url: str) -> dict[str, Any]:
    """Save a URL into the library: register, fetch, classify, render (network).

    On fetch problems the item stays registered and the payload carries
    an `error` key; raises only for non-http(s) URLs.
    """
    return _ingest_url(url)


def follow_feed(url: str) -> dict[str, Any]:
    """Subscribe the library to an RSS/Atom feed for sync_feeds (network).

    The feed is fetched once to validate it; a typo'd or non-feed URL is
    an error and stores nothing. YouTube playlist/channel URLs map to
    their public feeds automatically. `created` is false when the feed
    was already followed.
    """
    _, subscription, created = feeds.follow_feed(url)
    return {**dataclasses.asdict(subscription), "created": created}


def unfollow_feed(ref: str) -> dict[str, Any]:
    """Remove a feed subscription by id or feed URL.

    Items the feed registered stay in the library; only the
    subscription goes.
    """
    paths = get_paths()
    sub_id = feeds.make_subscription_id(feeds.to_feed_url(ref)) if "://" in ref else ref
    removed = (
        feeds.remove_subscription(paths.db_path, sub_id) if paths.db_path.exists() else False
    )
    if not removed:
        raise ValueError(f"no such subscription: {ref}")
    return {"id": sub_id, "removed": True}


def list_feed_subscriptions() -> list[dict[str, Any]]:
    """Every followed feed with its sync state and HTTP cache validators."""
    paths = get_paths()
    if not paths.db_path.exists():
        return []
    return [dataclasses.asdict(sub) for sub in feeds.list_subscriptions(paths.db_path)]


def sync_feeds(subscription_id: str | None = None) -> dict[str, Any]:
    """Poll followed feeds and register new entries as detected items (network).

    Run ingest/fetch afterwards to bring the new items in. Polls are
    HTTP-cached: an unchanged feed reports status 'unchanged'. Per-feed
    failures are 'failed' results in the payload, not tool errors; only
    an unknown subscription_id raises.
    """
    paths = get_paths()
    if subscription_id is not None:
        subscription = (
            feeds.get_subscription(paths.db_path, subscription_id)
            if paths.db_path.exists()
            else None
        )
        if subscription is None:
            raise ValueError(f"no such subscription: {subscription_id}")
        subscriptions = [subscription]
    else:
        subscriptions = (
            feeds.list_subscriptions(paths.db_path) if paths.db_path.exists() else []
        )
    return feeds.sync_many(paths.db_path, subscriptions)


def compile_library() -> dict[str, Any]:
    """Rebuild the compiled knowledge-base pages under library/ (no network).

    Runs the deterministic compiler: the index plus source, category,
    and concept pages, including any stored concept summaries. Run it
    after ingesting or syncing so get_concept_page sees the new items.
    LLM summary generation stays a CLI step (`scrolls kb --engine llm`,
    ADR 0025) — this tool never makes paid API calls.
    """
    paths = get_paths()
    return dataclasses.asdict(compile_kb(paths))


_TOOLS = (
    search_scrolls,
    get_scroll,
    get_related_scrolls,
    get_context_bundle,
    get_concept_page,
    list_sources,
    ingest_url,
    follow_feed,
    unfollow_feed,
    list_feed_subscriptions,
    sync_feeds,
    compile_library,
)


def build_server():
    """The FastMCP server with every library tool registered."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(SERVER_NAME, instructions=_INSTRUCTIONS)
    for tool in _TOOLS:
        server.add_tool(tool)
    return server


def run() -> None:
    """Serve over stdio until the client disconnects."""
    build_server().run()
