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
from scrolls.graph import build_graph
from scrolls.graph import to_payload as graph_payload
from scrolls.items import count_by_source, get_item, list_items
from scrolls.kb import compile_kb
from scrolls.paths import get_paths
from scrolls.pipeline import ingest_url as _ingest_url
from scrolls.related import DEFAULT_LIMIT as DEFAULT_RELATED_LIMIT
from scrolls.related import find_related
from scrolls.render import slugify
from scrolls.search import DEFAULT_LIMIT as DEFAULT_SEARCH_LIMIT
from scrolls.search import search_items

SERVER_NAME = "scrolls"

DEFAULT_LIST_LIMIT = 50

_INSTRUCTIONS = (
    "Search the user's saved internet artifacts (tweets, papers, videos, "
    "articles, repos) compiled as a local knowledge library. Start with "
    "get_context_bundle for a compact, citable overview of a topic; use "
    "search_scrolls and get_scroll for depth, list_scrolls to browse the "
    "library by facet (source, category, tag, concept) without a query, "
    "get_related_scrolls and "
    "get_concept_page (or get_tag_page) to follow connections, get_link_graph "
    "for the whole "
    "library's link structure at once, and ingest_url to save "
    "something new. follow_feed subscribes the library to an RSS/Atom "
    "feed and sync_feeds registers its new entries. compile_library "
    "rebuilds the knowledge-base pages get_concept_page and get_tag_page serve."
)


def search_scrolls(
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
) -> list[dict[str, Any]]:
    """Full-text search over the library; hits are best-first with snippets.

    `score` is SQLite bm25(): more negative means a stronger match. The
    optional facets scope the ranked match (they AND together): `source`
    limits to one source (e.g. arxiv, github, web), `category` to one
    category (an empty string selects unclassified items), `stage` to one
    pipeline stage (detected, fetched, rendered), `tag` to items carrying a
    tag (case-insensitive), and `concept` to items carrying a concept
    (matched by slug, so "BM25" and "bm25" agree). Use them to ask, e.g.,
    what *papers* tagged efficient the library knows about a topic, not just
    what mentions it.
    """
    paths = get_paths()
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
    return [dataclasses.asdict(hit) for hit in hits]


def list_scrolls(
    source: str | None = None,
    stage: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
) -> list[dict[str, Any]]:
    """Browse library items by facet — the enumeration counterpart to search_scrolls.

    Where search_scrolls ranks items by relevance to a query, this lists
    them with no query at all, filtered by the same facets (they AND
    together): `source` and `stage` match exactly, `category` exactly except
    an empty string which selects unclassified items, `tag` by membership
    (case-insensitive), and `concept` by membership (matched by slug). Items
    come oldest-saved first, capped at `limit` (default 50) to stay
    context-friendly — raise it to see more. Each entry is a summary (id,
    source, url, title, category, stage, saved_at); follow up with get_scroll
    for the full record. Use it for "what arxiv papers tagged efficient are
    in the library", which has no natural search query.
    """
    paths = get_paths()
    if not paths.db_path.exists():
        return []
    items = list_items(
        paths.db_path,
        stage=stage,
        source=source,
        category=category,
        tag=tag,
        concept=concept,
    )[:limit]
    return [
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


def get_link_graph(include_isolated: bool = False) -> dict[str, Any]:
    """The library's cross-item link graph: directed edges between saved items.

    An edge `from → to` means a link inside one saved item resolves to
    another (a model to its paper, a preprint to its published DOI, a tweet
    to the article it cites); `via` is the link that matched. Where
    get_related_scrolls explores one item's neighborhood, this returns the
    whole structure at once. Nodes are the connected items unless
    `include_isolated` widens it to every item; `stats.items` is the library
    total.
    """
    paths = get_paths()
    return graph_payload(build_graph(paths.db_path, include_isolated=include_isolated))


def get_context_bundle(
    query: str,
    limit: int = DEFAULT_CONTEXT_LIMIT,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
) -> str:
    """A compact Markdown bundle for a topic: best matches, excerpts, source links.

    The bundle is designed to be dropped directly into model context. The
    optional facets scope it the same way they scope search_scrolls (they
    AND together): `source` limits to one source (e.g. arxiv, github),
    `category` to one category (an empty string selects unclassified items),
    `stage` to one pipeline stage, `tag` to items carrying a tag
    (case-insensitive), and `concept` to items carrying a concept (matched by
    slug) — so the bundle can cover, e.g., what the *papers* say about a
    topic. A scoped bundle names its facets in the title.
    """
    paths = get_paths()
    return build_context(
        paths.db_path,
        query,
        limit=limit,
        source=source,
        category=category,
        stage=stage,
        tag=tag,
        concept=concept,
    )


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


def get_tag_page(tag: str) -> str:
    """The compiled knowledge-base page for one tag, as Markdown (ADR 0064).

    Tags are matched case-insensitively ("MIT" and "mit" are the same page),
    the way the `--tag` facet matches. Tag pages share a slug when distinct
    tags fold to it (`C++` and `C#` both slugify to "c"), so the page is found
    among the slug's candidate files by its `# Tag: <display>` heading rather
    than by filename alone.
    """
    paths = get_paths()
    base = slugify(tag) or "untitled"
    tags_dir = paths.library_dir / "tags"
    wanted = tag.casefold()
    if tags_dir.is_dir():
        candidates = sorted(tags_dir.glob(f"{base}.md")) + sorted(tags_dir.glob(f"{base}-*.md"))
        for page in candidates:
            text = page.read_text(encoding="utf-8")
            heading = text.split("\n", 1)[0]
            if heading.startswith("# Tag: ") and heading[len("# Tag: "):].casefold() == wanted:
                return text
    raise ValueError(
        f"no tag page for {tag!r} — compile the library first "
        "(the compile_library tool, or `scrolls kb`)"
    )


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
    list_scrolls,
    get_scroll,
    get_related_scrolls,
    get_link_graph,
    get_context_bundle,
    get_concept_page,
    get_tag_page,
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
