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
from datetime import datetime, timezone
from typing import Any

from scrolls import feeds
from scrolls.context import DEFAULT_BUDGET as DEFAULT_CONTEXT_BUDGET
from scrolls.context import DEFAULT_LIMIT as DEFAULT_CONTEXT_LIMIT
from scrolls.context import build_context
from scrolls.custody import (
    drift_posture,
    item_events,
    item_history,
    last_checked,
    latest_events,
    live_recapture,
    parse_since,
    record_events,
    verify_item,
)
from scrolls.db import init_db
from scrolls.generated import generated_body
from scrolls.facets import DEFAULT_LIMIT as DEFAULT_FACETS_LIMIT
from scrolls.facets import compute_facets
from scrolls.graph import build_graph
from scrolls.graph import to_payload as graph_payload
from scrolls.works import DEFAULT_MIN_REPRESENTATIONS
from scrolls.works import membership_payload, work_membership
from scrolls.works import to_payload as works_payload
from scrolls.works import works_for_item, works_over
from scrolls.items import (
    classification_provenance,
    count_by_source,
    get_fidelity,
    get_item,
    item_summary,
    list_items,
)
from scrolls.kb import compile_kb
from scrolls.paths import get_paths
from scrolls.pipeline import ingest_url as _ingest_url
from scrolls.pipeline import resolve_item_id
from scrolls.related import DEFAULT_LIMIT as DEFAULT_RELATED_LIMIT
from scrolls.related import find_related
from scrolls.render import slugify
from scrolls.search import DEFAULT_LIMIT as DEFAULT_SEARCH_LIMIT
from scrolls.search import hit_payload, search_items

SERVER_NAME = "scrolls"

DEFAULT_LIST_LIMIT = 50

_INSTRUCTIONS = (
    "Search the user's saved internet artifacts (tweets, papers, videos, "
    "articles, repos) compiled as a local knowledge library. Start with "
    "get_context_bundle for a compact, citable overview of a topic; use "
    "search_scrolls and get_scroll for depth, list_scrolls to browse the "
    "library by facet (source, category, tag, concept) without a query, "
    "list_facets to discover which facet values exist before filtering, "
    "get_related_scrolls and "
    "get_concept_page (or get_tag_page) to follow connections, get_link_graph "
    "for the whole "
    "library's link structure at once, and ingest_url to save "
    "something new. verify_scroll re-captures a held scroll and reports "
    "whether its source has drifted or rotted since it was saved. "
    "follow_feed subscribes the library to an RSS/Atom "
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

    `score` is SQLite bm25(): more negative means a stronger match. Each hit
    also carries the per-item custody axes — its `fidelity` tier (full/
    partial/reference, ADR 0097), its `drift` posture (verified/unverified/
    drifted/rotted/error, from the verify ledger), and `last_checked` (when that
    posture was taken, or null when never re-checked) — so a result says not just
    *what* matched but at what fidelity the library still holds it, whether that
    source has drifted out from under the capture, and as of when; the same axes
    `list_scrolls` rows and `get_related_scrolls` hits report. The
    optional facets scope the ranked match (they AND together): `source`
    limits to one source (e.g. arxiv, github, web), `category` to one
    category (an empty string selects unclassified items), `stage` to one
    pipeline stage (detected, fetched, rendered), `tag` to items carrying a
    tag (case-insensitive), and `concept` to items carrying a concept
    (matched by slug, so "BM25" and "bm25" agree). Use them to ask, e.g.,
    what *papers* tagged efficient the library knows about a topic, not just
    what mentions it.

    Each hit also carries the scholarly `works` it represents (ADR 0101):
    empty for most hits, but when two hits are the same work — a preprint and
    its published record — each names the work's DOI and which hit is the
    canonical form, so you can collapse the duplicate and follow the canonical
    rather than treating the two as unrelated matches.

    When an engine produced a hit's category, the hit also carries a derived
    `classification` view — the engine (`by`), the rules precedence tier
    (`basis`) and ruleset fingerprint (`ruleset`), or the LLM `model` — the same
    view `get_scroll`/`list_scrolls` surface, so how a category was produced
    reads identically whether you browsed or searched. The key is omitted for a
    user-set or unclassified hit (honest absence).
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
    return [hit_payload(hit) for hit in hits]


def list_scrolls(
    source: str | None = None,
    stage: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
    drift: str | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
) -> list[dict[str, Any]]:
    """Browse library items by facet — the enumeration counterpart to search_scrolls.

    Where search_scrolls ranks items by relevance to a query, this lists
    them with no query at all, filtered by the same facets (they AND
    together): `source` and `stage` match exactly, `category` exactly except
    an empty string which selects unclassified items, `tag` by membership
    (case-insensitive), and `concept` by membership (matched by slug). `drift`
    selects items by custody drift posture from the verify ledger
    (`verified`/`unverified`/`drifted`/`rotted`/`error`) — the items returned
    total `list_facets("drift")`'s count for that posture, so you can drill from
    the aggregate to the rows. Items come oldest-saved first, capped at `limit`
    (default 50) to stay context-friendly — raise it to see more. Each entry is a
    summary (id, source, url, title, category, stage, saved_at, the custody
    axes — the `fidelity` tier (full/partial/reference, ADR 0097), the `drift`
    posture (verified/unverified/drifted/rotted/error) the same row's `--drift`
    filter selects on, and `last_checked` (when that posture was taken, or null
    when never re-checked) — and the scholarly `works` it represents, ADR 0101: empty
    unless the item is one of several saved forms of one work, in which case each
    entry names the work's DOI and canonical form); follow up with get_scroll for
    the full record. Use it for
    "what arxiv papers tagged efficient are in the library", which has no natural
    search query.
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
        drift=drift,
    )[:limit]
    # Membership is a whole-library property (ADR 0101): cluster over every
    # item so a filtered/limited listing still reports an item's siblings, then
    # annotate the rows shown — the same approach `scrolls list` takes.
    membership = work_membership(list_items(paths.db_path))
    # One ledger read for the whole listing (the CLI twin's approach): each row's
    # `drift` posture is `drift_posture` over the same `latest_events`, and
    # `last_checked` the same verdict's timestamp (the H84 time axis).
    verdicts = latest_events(paths.db_path)
    return [
        item_summary(
            item,
            membership_payload(membership.get(item.id, ())),
            drift=drift_posture(verdicts.get(item.id)),
            last_checked=last_checked(verdicts.get(item.id)),
        )
        for item in items
    ]


def list_facets(
    field: str | None = None,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
    limit: int = DEFAULT_FACETS_LIMIT,
) -> dict[str, Any]:
    """Enumerate the library's filterable vocabulary with item counts.

    The discovery counterpart to search_scrolls/list_scrolls: it answers
    "what can I filter by?" before you filter. With no `field`, reports every
    dimension — `sources`, `categories`, `tags`, `concepts`, plus the derived
    `fidelity` (custody tier) and `method` (how each held category was produced:
    `rules-v1`/`llm-v1`, or the honest `user-set`/`unclassified` buckets) — as
    `{"facets": {dimension: [{"value", "count", ...}, ...]}}`; pass a `field`
    to narrow to one. Each list is ranked by count then value and capped at
    `limit` (default 20). Categories report the unclassified pool as the empty
    string ""; concepts carry the `slug` you would pass as the `concept` facet.
    The same optional facets that scope search_scrolls scope these counts, so
    `list_facets("concepts", source="arxiv")` asks which concepts the saved
    arXiv papers carry, and `list_facets("method")` asks how much of the library
    was auto-classified vs set by hand. Use it to learn the real category, tag,
    and concept values before calling search_scrolls/list_scrolls with one.
    """
    return compute_facets(
        get_paths().db_path,
        field=field,
        source=source,
        category=category,
        stage=stage,
        tag=tag,
        concept=concept,
        limit=limit,
    )


def get_scroll(item_id: str) -> dict[str, Any]:
    """One saved item in full: metadata, summary, extracted text, links, media.

    `item_id` is the item's id (`arxiv:1706.03762`) or, equivalently, the URL
    that saved it — a search hit's `url`, a user's paste — resolved through the
    same normalize → detect → mint chain `ingest_url` registers with (ADR 0028).
    An unknown item is an error; if a URL was passed, the message names the id it
    resolved to so the resolution stays visible.

    Beside the raw record, the payload carries the derived per-item custody
    axes the browse surfaces report (roadmap H61/H84) — `fidelity` (the custody
    tier, full/partial/reference), `drift` (the verify-ledger posture, verified/
    unverified/drifted/rotted/error), and `last_checked` (when that posture was
    taken, or null when never re-checked) — plus the `classification` view
    (omitted on honest absence), so the inspect surface reads at parity with
    `list_scrolls`/`search_scrolls`.
    """
    paths = get_paths()
    resolved = resolve_item_id(item_id)
    item = get_item(paths.db_path, resolved) if paths.db_path.exists() else None
    if item is None:
        suffix = f" (from {item_id})" if resolved != item_id else ""
        raise ValueError(f"no such item: {resolved}{suffix}")
    payload = dataclasses.asdict(item)
    for name in ("tags", "concepts", "links", "media"):
        payload[name] = list(payload[name])
    # The derived per-item custody axes (roadmap H61/H84), matching the CLI
    # `show` payload and the `list`/`search` rows: `fidelity` (how much is held),
    # and from the latest ledger verdict both `drift` (whether the source moved)
    # and `last_checked` (as of when, or null when never re-checked).
    payload["fidelity"] = get_fidelity(item)
    events = item_events(paths.db_path, resolved)
    latest = events[0] if events else None
    payload["drift"] = drift_posture(latest)
    payload["last_checked"] = last_checked(latest)
    # The derived classification view alongside raw provenance, matching the CLI
    # `show` payload so both inspect surfaces present how the category was made.
    classification = classification_provenance(item)
    if classification is not None:
        payload["classification"] = classification
    return payload


def get_scroll_history(
    item_id: str,
    limit: int | None = None,
    since: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """One item's custody-ledger timeline — every verify check, newest first.

    Where `get_scroll` carries only the *latest* `drift` posture, this returns
    the append-only ledger `scrolls verify` writes: each
    ``{checked_at, status, prior_hash, observed_hash, detail}``, newest first —
    so an agent can see *when* a source drifted and *how often* it was
    re-checked, the per-item counterpart of the scope-level `maintain --history`
    trajectory. Three filter axes, applied verdict → time → count: `status`
    keeps only checks with that verdict (``unchanged``/``drifted``/``rotted``/
    ``error`` — an unknown verdict is an error, the closed-vocabulary `list
    --drift` posture, roadmap H77), `since` (an ISO-8601 timestamp) windows to
    checks at/after a boundary — "what has this source done since the last
    sweep" (roadmap H71), `limit` bounds to the most recent N (roadmap H69); each
    is off by default, so the whole timeline is the default. `item_id` is the
    item's id or the URL that saved it (ADR 0028), resolved like `get_scroll`'s.
    A known-but-never-verified item (or a filter/window nothing matches) is the
    honest empty `[]` (completeness G1); an *unknown* item — or a malformed
    `since` / unknown `status` — is an error, the same empty-vs-error split
    `get_scroll`/`get_related_scrolls` draw.
    """
    paths = get_paths()
    boundary = parse_since(since)  # malformed → ValueError (the MCP error idiom)
    resolved = resolve_item_id(item_id)
    item = get_item(paths.db_path, resolved) if paths.db_path.exists() else None
    if item is None:
        suffix = f" (from {item_id})" if resolved != item_id else ""
        raise ValueError(f"no such item: {resolved}{suffix}")
    # an unknown `status` raises inside item_history (closed vocabulary)
    return item_history(
        paths.db_path, resolved, limit=limit, since=boundary, status=status
    )


def get_related_scrolls(
    item_id: str, limit: int = DEFAULT_RELATED_LIMIT
) -> list[dict[str, Any]]:
    """Items connected to one item — same-work, link edges, shared concepts/tags — with reasons.

    Ranked best-first by explainable signals: a *same-work* sibling (a
    preprint and its published article, bound by a shared DOI — the strongest
    signal, and one that binds representations even when no link edge does),
    then link edges, shared concepts, shared tags, and same category/domain.
    Each hit's `reasons` say why it matched and its `fidelity` says at what
    custody tier the library holds the neighbour (full/partial/reference,
    ADR 0097), the same tier `list_scrolls` and `search_scrolls` report.
    `item_id` is the item's id or the URL that saved it (ADR 0028), resolved
    like `get_scroll`'s. An unknown item is an error.
    """
    paths = get_paths()
    resolved = resolve_item_id(item_id)
    if not paths.db_path.exists():
        raise ValueError(f"no such item: {resolved}")
    hits = [dataclasses.asdict(hit) for hit in find_related(paths.db_path, resolved, limit=limit)]
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
    total. Each node carries its custody `fidelity` tier (full/partial/
    reference, ADR 0097), the same tier get_related_scrolls reports, so a node
    says how much of the item the library holds. `stats.custody` summarises how
    custody stands across the whole `stats.items` scope — fidelity-tier and
    drift-posture counts (the same tally doctor/facets/the headlines report), so
    the graph's custody totals converge with them for the scope.
    """
    paths = get_paths()
    graph = build_graph(paths.db_path, include_isolated=include_isolated)
    verdicts = latest_events(paths.db_path) if paths.db_path.exists() else {}
    return graph_payload(graph, verdicts)


def get_works(
    item: str | None = None,
    min_representations: int = DEFAULT_MIN_REPRESENTATIONS,
) -> dict[str, Any]:
    """Scholarly works the library holds more than one representation of.

    Groups items that are the *same work* — an arXiv preprint, its published
    Crossref article, a PubMed record, a bioRxiv/medRxiv preprint — keyed by
    the DOI that names the work. Unlike get_link_graph, which connects items
    only when one's link resolves to another already in the library, this
    clusters by shared DOI, so two representations bind into one work even
    when the Crossref item that links them is absent. Each work carries its
    `doi`, `url`, `representations` (the same node shape as the graph), and
    `canonical` — the id of the one representation that stands for the whole
    work (the registered published record over a preprint), a pointer into
    its own `representations` so a caller can cite or display that form. Each
    representation carries both per-item custody axes: its `fidelity` tier
    (full/partial/reference, ADR 0097 — how much of the form is held) and its
    `drift` posture (verified/unverified/drifted/rotted/error — whether the
    source moved, roadmap H64), so a caller sees which forms the library holds in
    full and which have drifted — the same two-axis picture `list_scrolls`/
    `get_related_scrolls`/`get_link_graph` carry.
    Works with fewer than `min_representations` items are omitted (default 2,
    so only works actually worth consolidating are returned); `stats.items`
    is the library total.

    Pass `item` (an id or URL) for the *per-item* lens — the work(s) that one
    item represents, with every saved sibling representation: an item that
    found one form (a search hit) learns which other forms of the same work
    are in the library. In this form `min_representations` is ignored and a
    work is reported even with a single representation (just that item), so
    "no sibling saved" is an explicit answer; an unknown item is an error.
    """
    paths = get_paths()
    items = list_items(paths.db_path) if paths.db_path.exists() else []
    if item is not None:
        resolved = resolve_item_id(item)
        works = works_for_item(items, resolved)
        scope: dict[str, Any] = {"ref": resolved}
    else:
        works = works_over(items, min_representations=min_representations)
        scope = {"min_representations": min_representations}
    verdicts = latest_events(paths.db_path) if paths.db_path.exists() else {}
    return works_payload(works, len(items), scope=scope, verdicts=verdicts)


def get_context_bundle(
    query: str,
    limit: int = DEFAULT_CONTEXT_LIMIT,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
    budget: str = DEFAULT_CONTEXT_BUDGET,
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

    `budget` bounds the bundle's depth (a budgeted boot sequence, identity/index
    first): `index` is the catalog alone (best matches + links), `connected`
    adds the link graph, `full` (default) adds the deep-body excerpts. A tier
    below `full` discloses what it omitted in a `Budget:` note, so a catalog
    bundle is never read as the whole story — an agent can boot cheap, then pull
    bodies on demand with `get_scroll`/`scrolls show` or a `full` re-run.
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
        budget=budget,
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
    than by filename alone. The heading is read from the page's generated
    region, inside the sentinel fence (ADR 0102).
    """
    paths = get_paths()
    base = slugify(tag) or "untitled"
    tags_dir = paths.library_dir / "tags"
    wanted = tag.casefold()
    if tags_dir.is_dir():
        candidates = sorted(tags_dir.glob(f"{base}.md")) + sorted(tags_dir.glob(f"{base}-*.md"))
        for page in candidates:
            text = page.read_text(encoding="utf-8")
            body = generated_body(text) or text
            heading = body.split("\n", 1)[0]
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


def verify_scroll(item_id: str) -> dict[str, Any]:
    """Re-capture a held scroll and record whether its source drifted/rotted (network).

    Re-fetches the item through its source adapter, diffs the fresh content
    hash against the stored one, and appends a custody event to the ledger
    *without* overwriting the original capture (ADR 0098). Returns the event:
    `status` is `unchanged`, `drifted` (the source changed since capture),
    `rotted` (gone — HTTP 404/410), or `error` (could not check now), with
    `prior_hash`/`observed_hash`/`detail`. `item_id` is an id or the item's URL
    (ADR 0028). Raises for an unknown item, or one holding no captured content
    hash to verify against. Read the aggregate drift report with `scrolls
    doctor` (its `custody.drift` block).
    """
    paths = get_paths()
    item = (
        get_item(paths.db_path, resolve_item_id(item_id))
        if paths.db_path.exists()
        else None
    )
    if item is None:
        raise ValueError(f"no such item: {item_id}")
    if not item.content_hash:
        raise ValueError(f"item {item.id!r} holds no content hash to verify against")
    init_db(paths.db_path)  # ensure the ledger table exists before recording
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    event = verify_item(item, live_recapture, now=now)
    record_events(paths.db_path, [event])
    return dataclasses.asdict(event)


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
    list_facets,
    get_scroll,
    get_scroll_history,
    get_related_scrolls,
    get_link_graph,
    get_works,
    get_context_bundle,
    get_concept_page,
    get_tag_page,
    list_sources,
    ingest_url,
    verify_scroll,
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
