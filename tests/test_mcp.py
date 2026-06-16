"""Tests for the MCP server (IDEAS.md §10, ADR 0014).

The tool functions are plain wrappers over the same engines the CLI
uses, so they are tested directly against a temp library — no protocol
client, no network (the wikipedia transport is faked). One test builds
the real FastMCP server to lock the registered tool surface.
"""

import asyncio
import dataclasses

import pytest

import scrolls.sources.wikipedia as wikipedia
from scrolls import mcp_server
from scrolls.cli import main
from scrolls.kb import compile_kb
from scrolls.paths import get_paths


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


@pytest.fixture
def fake_wikipedia_api(monkeypatch):
    """Serve a canned MediaWiki extracts payload instead of the network."""
    payload = {
        "query": {
            "pages": [
                {
                    "pageid": 25387,
                    "title": "SQLite",
                    "fullurl": "https://en.wikipedia.org/wiki/SQLite",
                    "canonicalurl": "https://en.wikipedia.org/wiki/SQLite",
                    "extract": "SQLite is a database engine.\n\n\n== History ==\nEarly days.",
                    "categories": [
                        {"ns": 14, "title": "Category:Database management systems"}
                    ],
                }
            ]
        }
    }
    monkeypatch.setattr(wikipedia, "_get_json", lambda url: payload)
    return payload


@pytest.fixture
def fake_feed(monkeypatch):
    """A two-entry blog feed; serves an ETag and honors it with a 304."""
    import scrolls.feeds as feeds
    from scrolls.sources.http import ConditionalText

    document = """\
<rss version="2.0"><channel><title>A Weblog</title>
<item><title>Post one</title><link>https://blog.example.com/2026/post-one/</link></item>
<item><title>Post two</title><link>https://blog.example.com/2026/post-two/</link></item>
</channel></rss>"""
    url = "https://blog.example.com/atom.xml"

    def get_text(u):
        if u != url:
            raise OSError(f"connection refused: {u}")
        return document

    def get_conditional(u, etag, last_modified):
        if etag == 'W/"v1"':
            return ConditionalText(not_modified=True)
        return ConditionalText(text=get_text(u), etag='W/"v1"')

    monkeypatch.setattr(feeds, "_get_text", get_text)
    monkeypatch.setattr(feeds, "_get_conditional", get_conditional)
    return url


def test_server_exposes_exactly_the_documented_tools(scrolls_home):
    server = mcp_server.build_server()
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == {
        "search_scrolls",
        "list_scrolls",
        "list_facets",
        "get_scroll",
        "get_scroll_history",
        "get_related_scrolls",
        "get_link_graph",
        "get_works",
        "get_context_bundle",
        "get_concept_page",
        "get_tag_page",
        "list_sources",
        "ingest_url",
        "verify_scroll",
        "follow_feed",
        "unfollow_feed",
        "list_feed_subscriptions",
        "sync_feeds",
        "compile_library",
    }
    # every tool teaches the model what it does
    assert all(tool.description for tool in tools)


def test_ingest_url_returns_the_cli_payload(scrolls_home, fake_wikipedia_api):
    payload = mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    assert payload["id"] == "wikipedia:en:SQLite"
    assert payload["title"] == "SQLite"
    assert payload["category"] == "reference"
    assert payload["stage"] == "rendered"
    assert "error" not in payload


def test_ingest_url_without_adapter_reports_error_as_data(scrolls_home):
    payload = mcp_server.ingest_url("https://x.com/karpathy/status/1111")
    assert payload["stage"] == "detected"
    assert "no fetch adapter" in payload["error"]


def _seed_verifiable_item(content_hash="sha256:orig"):
    """A rendered web item with a captured hash, for verify_scroll tests."""
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    paths = get_paths()
    item = ScrollItem(
        id="web:demo", source="web", source_id=None,
        url="https://example.com/a", saved_at="2026-06-12T08:00:00+00:00",
        content_hash=content_hash, extracted_text="captured body", stage="rendered",
    )
    insert_item(paths.db_path, item)
    return item


def test_verify_scroll_records_drift(scrolls_home, monkeypatch):
    from scrolls.items import ScrollItem

    _seed_verifiable_item(content_hash="sha256:old")
    monkeypatch.setattr(
        mcp_server, "live_recapture",
        lambda i: ScrollItem(**{**dataclasses.asdict(i), "content_hash": "sha256:new"}),
    )

    event = mcp_server.verify_scroll("web:demo")
    assert event["status"] == "drifted"
    assert event["prior_hash"] == "sha256:old"
    assert event["observed_hash"] == "sha256:new"
    # the verdict reaches the doctor drift report
    from scrolls.custody import latest_events

    latest = latest_events(get_paths().db_path)
    assert latest["web:demo"].status == "drifted"


def test_get_scroll_history_returns_the_ledger_newest_first(scrolls_home, monkeypatch):
    # H66: the MCP twin of `scrolls history` emits the same per-item ledger the
    # CLI does — verify twice, the timeline reads newest-first with the 5-field
    # shape, and equals the shared `custody.item_history` primitive.
    from scrolls.custody import item_history
    from scrolls.items import ScrollItem

    _seed_verifiable_item(content_hash="sha256:old")
    monkeypatch.setattr(
        mcp_server, "live_recapture",
        lambda i: ScrollItem(**{**dataclasses.asdict(i), "content_hash": "sha256:new"}),
    )
    mcp_server.verify_scroll("web:demo")  # drifted
    monkeypatch.setattr(mcp_server, "live_recapture", lambda i: i)
    mcp_server.verify_scroll("web:demo")  # unchanged

    history = mcp_server.get_scroll_history("web:demo")
    assert [e["status"] for e in history] == ["unchanged", "drifted"]
    assert set(history[0]) == {"checked_at", "status", "prior_hash", "observed_hash", "detail"}
    assert history == item_history(get_paths().db_path, "web:demo")


def test_get_scroll_history_never_verified_is_empty(scrolls_home):
    _seed_verifiable_item()
    assert mcp_server.get_scroll_history("web:demo") == []


def test_get_scroll_history_limit_returns_the_most_recent_n(scrolls_home):
    # H69: the twin bounds a long ledger to the most recent N, like the CLI
    from scrolls.custody import CustodyEvent, record_events

    _seed_verifiable_item()
    record_events(get_paths().db_path, [
        CustodyEvent("web:demo", "2026-06-13T00:00:00+00:00", "unchanged", "h", "h"),
        CustodyEvent("web:demo", "2026-06-14T00:00:00+00:00", "drifted", "h", "h2"),
        CustodyEvent("web:demo", "2026-06-15T00:00:00+00:00", "rotted", "h2", None, "x"),
    ])
    history = mcp_server.get_scroll_history("web:demo", limit=2)
    assert [e["status"] for e in history] == ["rotted", "drifted"]
    assert mcp_server.get_scroll_history("web:demo", limit=0) == []
    assert len(mcp_server.get_scroll_history("web:demo")) == 3  # unbounded default


def test_get_scroll_history_since_windows_like_the_cli(scrolls_home):
    # H71: the twin windows to checks at/after the boundary, like `scrolls
    # history --since`, and equals the shared `item_history` primitive
    from scrolls.custody import CustodyEvent, item_history, record_events

    _seed_verifiable_item()
    record_events(get_paths().db_path, [
        CustodyEvent("web:demo", "2026-06-13T00:00:00+00:00", "unchanged", "h", "h"),
        CustodyEvent("web:demo", "2026-06-14T00:00:00+00:00", "drifted", "h", "h2"),
        CustodyEvent("web:demo", "2026-06-15T00:00:00+00:00", "rotted", "h2", None, "x"),
    ])
    history = mcp_server.get_scroll_history("web:demo", since="2026-06-14T00:00:00+00:00")
    assert [e["status"] for e in history] == ["rotted", "drifted"]  # 06-13 dropped
    assert history == item_history(
        get_paths().db_path, "web:demo", since="2026-06-14T00:00:00+00:00"
    )
    # composes with limit (window then cap) and empty window is the honest []
    assert [e["status"] for e in mcp_server.get_scroll_history(
        "web:demo", since="2026-06-14T00:00:00+00:00", limit=1
    )] == ["rotted"]
    assert mcp_server.get_scroll_history("web:demo", since="2026-08-01T00:00:00+00:00") == []


def test_get_scroll_history_malformed_since_raises(scrolls_home):
    _seed_verifiable_item()
    with pytest.raises(ValueError):
        mcp_server.get_scroll_history("web:demo", since="yesterday")


def test_get_scroll_history_status_filters_like_the_cli(scrolls_home):
    # H77: the twin filters to one verdict, and equals the shared primitive
    from scrolls.custody import CustodyEvent, item_history, record_events

    _seed_verifiable_item()
    record_events(get_paths().db_path, [
        CustodyEvent("web:demo", "2026-06-13T00:00:00+00:00", "unchanged", "h", "h"),
        CustodyEvent("web:demo", "2026-06-14T00:00:00+00:00", "drifted", "h", "h2"),
        CustodyEvent("web:demo", "2026-06-15T00:00:00+00:00", "rotted", "h2", None, "x"),
    ])
    drifted = mcp_server.get_scroll_history("web:demo", status="drifted")
    assert [e["checked_at"] for e in drifted] == ["2026-06-14T00:00:00+00:00"]
    assert drifted == item_history(get_paths().db_path, "web:demo", status="drifted")


def test_get_scroll_history_unknown_status_raises(scrolls_home):
    _seed_verifiable_item()
    # closed vocabulary — `verified` is a posture, not a raw event status
    with pytest.raises(ValueError):
        mcp_server.get_scroll_history("web:demo", status="verified")


def test_get_scroll_history_unknown_item_raises(scrolls_home):
    main(["init"])
    with pytest.raises(ValueError, match="no such item"):
        mcp_server.get_scroll_history("web:nope")


def test_verify_scroll_unknown_item_raises(scrolls_home):
    main(["init"])
    with pytest.raises(ValueError, match="no such item"):
        mcp_server.verify_scroll("web:nope")


def test_verify_scroll_without_baseline_hash_raises(scrolls_home):
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    insert_item(get_paths().db_path, ScrollItem(
        id="web:ref", source="web", source_id=None, url="https://example.com/ref",
        saved_at="2026-06-12T08:00:00+00:00", stage="detected"))
    with pytest.raises(ValueError, match="no content hash"):
        mcp_server.verify_scroll("web:ref")


def test_search_scrolls_finds_ingested_content(scrolls_home, fake_wikipedia_api):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    hits = mcp_server.search_scrolls("database engine")
    assert [hit["id"] for hit in hits] == ["wikipedia:en:SQLite"]
    assert hits[0]["snippet"]


def test_search_scrolls_before_init_returns_empty(scrolls_home):
    assert mcp_server.search_scrolls("anything") == []


def test_search_scrolls_honors_facets(scrolls_home, fake_wikipedia_api):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")  # category: reference

    assert [h["id"] for h in mcp_server.search_scrolls("database", source="wikipedia")] == [
        "wikipedia:en:SQLite"
    ]
    assert mcp_server.search_scrolls("database", source="arxiv") == []
    assert [
        h["id"] for h in mcp_server.search_scrolls("database", category="reference")
    ] == ["wikipedia:en:SQLite"]
    # the item is classified, so the unclassified pool excludes it
    assert mcp_server.search_scrolls("database", category="") == []


def test_list_scrolls_browses_by_facet(scrolls_home):
    # The enumeration counterpart to search_scrolls (ADR 0060): no query,
    # filtered by the same facets, bounded by a limit.
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="arxiv:2401.0001", source="arxiv",
        url="https://arxiv.org/abs/2401.0001", saved_at="2026-06-12T00:00:00+00:00",
        title="A paper", category="paper", tags=("efficient",), stage="rendered",
    ))
    insert_item(db, ScrollItem(
        id="web:abc", source="web", url="https://example.org/post",
        saved_at="2026-06-12T01:00:00+00:00", title="A post", stage="fetched",
    ))

    # no facets: every item as a summary, oldest first
    rows = mcp_server.list_scrolls()
    assert [r["id"] for r in rows] == ["arxiv:2401.0001", "web:abc"]
    assert set(rows[0]) == {
        "id", "source", "url", "title", "category", "stage", "saved_at",
        "fidelity", "drift", "last_checked", "works",
    }
    assert rows[0]["works"] == []  # neither item shares a work (ADR 0101)
    assert rows[0]["drift"] == "unverified"  # never re-checked (H58)
    assert rows[0]["last_checked"] is None  # …so no timestamp to report (H84)

    # facets AND together, mirroring scrolls list (incl. the tag membership facet)
    assert [r["id"] for r in mcp_server.list_scrolls(source="arxiv", tag="EFFICIENT")] == [
        "arxiv:2401.0001"
    ]
    # empty-string category selects the unclassified pool
    assert [r["id"] for r in mcp_server.list_scrolls(category="")] == ["web:abc"]
    # the limit bounds the result
    assert len(mcp_server.list_scrolls(limit=1)) == 1


def test_list_scrolls_filters_by_drift_posture(scrolls_home):
    # the MCP twin of `scrolls list --drift` (H54): the items returned for a
    # posture total `list_facets("drift")`'s count for it (drill-from-the-count)
    from scrolls.cli import main
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    for index in range(3):
        insert_item(db, ScrollItem(
            id=f"web:{index}", source="web", url=f"https://ex.com/{index}",
            saved_at="2026-06-12T00:00:00+00:00", title=f"Post {index}",
            stage="fetched"))
    record_events(db, [
        CustodyEvent("web:0", "2026-06-14T00:00:00+00:00", "unchanged", "h", "h", None),
        CustodyEvent("web:1", "2026-06-14T00:00:00+00:00", "drifted", "h", "x", None),
        # web:2 left unverified
    ])

    assert [r["id"] for r in mcp_server.list_scrolls(drift="drifted")] == ["web:1"]
    assert [r["id"] for r in mcp_server.list_scrolls(drift="verified")] == ["web:0"]
    assert [r["id"] for r in mcp_server.list_scrolls(drift="unverified")] == ["web:2"]

    # convergence with the facet aggregate the twin `list_facets` reports
    counts = {
        e["value"]: e["count"]
        for e in mcp_server.list_facets("drift")["facets"]["drift"]
    }
    for posture, count in counts.items():
        assert len(mcp_server.list_scrolls(drift=posture)) == count


def test_list_scrolls_rejects_an_unknown_drift_posture(scrolls_home):
    # a closed vocabulary: an unknown posture is an error, never a silent empty
    import pytest

    from scrolls.cli import main

    main(["init"])
    with pytest.raises(ValueError):
        mcp_server.list_scrolls(drift="drited")


def test_list_scrolls_before_init_returns_empty(scrolls_home):
    assert mcp_server.list_scrolls() == []


def test_list_scrolls_surfaces_the_custody_fidelity_tier(scrolls_home):
    # custody state travels with browse results (ADR 0097): an agent sees which
    # items it holds in full without a follow-up get_scroll
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:full", source="web", url="https://ex.com/full",
        saved_at="2026-06-12T00:00:00+00:00",
        extracted_text="body", content_hash="sha256:a", stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:ref", source="web", url="https://ex.com/ref",
        saved_at="2026-06-12T01:00:00+00:00"))

    tiers = {r["id"]: r["fidelity"] for r in mcp_server.list_scrolls()}
    assert tiers == {"web:full": "full", "web:ref": "reference"}


def test_list_and_search_scrolls_carry_the_drift_posture(scrolls_home):
    # H58: the second custody axis (drift) travels with both MCP browse twins,
    # the same posture the CLI rows/hits and the node-shape surfaces carry, and
    # the twins agree on a given item.
    from scrolls.cli import main
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:drifted", source="web", url="https://ex.com/drifted",
        saved_at="2026-06-12T00:00:00+00:00", title="Drifted post about topic",
        extracted_text="drifted topic body", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:never", source="web", url="https://ex.com/never",
        saved_at="2026-06-12T01:00:00+00:00", title="Never-checked post about topic",
        extracted_text="never topic body", stage="fetched"))
    record_events(db, [
        CustodyEvent("web:drifted", "2026-06-14T00:00:00+00:00", "drifted", "h", "x", None),
    ])

    listed = {r["id"]: r["drift"] for r in mcp_server.list_scrolls()}
    assert listed == {"web:drifted": "drifted", "web:never": "unverified"}

    searched = {h["id"]: h["drift"] for h in mcp_server.search_scrolls("topic")}
    assert searched["web:drifted"] == "drifted"
    assert searched["web:never"] == "unverified"
    # the two twins agree on the same item's posture
    assert listed["web:drifted"] == searched["web:drifted"]


def test_list_and_search_scrolls_carry_work_membership(scrolls_home):
    # which scholarly work a browse result represents travels with it (ADR 0101),
    # the same way fidelity does — across both MCP browse surfaces
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="arxiv:1706.03762", source="arxiv",
        url="https://arxiv.org/abs/1706.03762", saved_at="2026-06-12T00:00:00+00:00",
        title="Attention Is All You Need",
        extracted_text="We propose the Transformer based on attention.",
        links=("https://doi.org/10.5555/3295222",), stage="fetched"))
    insert_item(db, ScrollItem(
        id="crossref:10.5555/3295222", source="crossref",
        source_id="10.5555/3295222", url="https://doi.org/10.5555/3295222",
        saved_at="2026-06-12T01:00:00+00:00", title="Attention Is All You Need",
        extracted_text="We propose the Transformer based on attention.",
        stage="fetched"))

    listed = {r["id"]: r["works"] for r in mcp_server.list_scrolls()}
    assert listed["arxiv:1706.03762"][0]["canonical"] == "crossref:10.5555/3295222"
    assert listed["arxiv:1706.03762"][0]["is_canonical"] is False
    assert listed["crossref:10.5555/3295222"][0]["is_canonical"] is True

    searched = {h["id"]: h["works"] for h in mcp_server.search_scrolls("attention")}
    assert searched["arxiv:1706.03762"][0]["representations"] == 2
    assert searched["arxiv:1706.03762"][0]["canonical"] == "crossref:10.5555/3295222"


def test_list_facets_enumerates_the_filterable_vocabulary(scrolls_home):
    # The discovery counterpart to search_scrolls/list_scrolls (ADR 0080):
    # which values can the same facets be filtered by?
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="arxiv:2401.0001", source="arxiv",
        url="https://arxiv.org/abs/2401.0001", saved_at="2026-06-12T00:00:00+00:00",
        title="A paper", category="paper", concepts=("Machine Learning",),
        stage="rendered",
    ))
    insert_item(db, ScrollItem(
        id="web:abc", source="web", url="https://example.org/post",
        saved_at="2026-06-12T01:00:00+00:00", title="A post", tags=("loose",),
        stage="fetched",
    ))

    payload = mcp_server.list_facets()
    assert payload["facets"]["sources"] == [
        {"value": "arxiv", "count": 1},
        {"value": "web", "count": 1},
    ]
    # the unclassified web item is the "" category, round-trippable to category=""
    assert {"value": "", "count": 1} in payload["facets"]["categories"]

    # a field narrows to one dimension, and the scoping facets apply
    scoped = mcp_server.list_facets("concepts", source="arxiv")
    assert scoped == {
        "facets": {
            "concepts": [
                {"value": "Machine Learning", "slug": "machine-learning", "count": 1}
            ]
        }
    }


def test_list_facets_before_init_is_empty_but_well_shaped(scrolls_home):
    assert mcp_server.list_facets() == {
        "facets": {
            "sources": [],
            "categories": [],
            "tags": [],
            "concepts": [],
            "fidelity": [],
            "drift": [],
            "method": [],
        }
    }


def test_list_facets_method_buckets_how_categories_were_produced(scrolls_home):
    # the MCP twin of `scrolls facets method` (H28): the aggregate of the
    # per-item classification view, with honest user-set/unclassified buckets
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="wikipedia:en:SQLite", source="wikipedia", source_id="en:SQLite",
        url="https://en.wikipedia.org/wiki/SQLite", saved_at="2026-06-12T00:00:00+00:00",
        title="SQLite", category="reference", stage="fetched",
        provenance={"classified_by": "rules-v1", "classified_basis": "curated-source",
                    "classified_ruleset": "abc123"}))
    insert_item(db, ScrollItem(
        id="web:bare", source="web", url="https://ex.com/b",
        saved_at="2026-06-12T00:00:00+00:00", title="An unclassified post", stage="fetched"))

    method = mcp_server.list_facets("method")["facets"]["method"]
    assert method == [
        {"value": "rules-v1", "count": 1},
        {"value": "unclassified", "count": 1},
    ]


def test_list_facets_drift_buckets_held_items_by_custody_posture(scrolls_home):
    # the MCP twin of `scrolls facets drift` (H48): held items by drift posture
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    for index in range(3):
        insert_item(db, ScrollItem(
            id=f"web:{index}", source="web", url=f"https://ex.com/{index}",
            saved_at="2026-06-12T00:00:00+00:00", title=f"Post {index}", stage="fetched"))
    record_events(db, [
        CustodyEvent("web:0", "2026-06-14T00:00:00+00:00", "unchanged", "h", "h", None),
        CustodyEvent("web:1", "2026-06-14T00:00:00+00:00", "drifted", "h", "x", None),
        # web:2 left unverified
    ])

    drift = mcp_server.list_facets("drift")["facets"]["drift"]
    assert {entry["value"]: entry["count"] for entry in drift} == {
        "verified": 1, "drifted": 1, "unverified": 1,
    }


def test_get_scroll_returns_the_full_item(scrolls_home, fake_wikipedia_api):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    item = mcp_server.get_scroll("wikipedia:en:SQLite")
    assert item["title"] == "SQLite"
    assert item["concepts"] == ["Database management systems"]
    assert item["markdown_path"] == "scrolls/wikipedia/sqlite.md"


def test_get_scroll_carries_the_two_custody_axes_at_parity_with_list(scrolls_home):
    # H61: the MCP inspect twin carries the derived `fidelity` + `drift` axes,
    # and agrees with the `list_scrolls` row for the same item (per-item parity).
    from scrolls.cli import main
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:a", source="web", url="https://ex.com/a",
        saved_at="2026-06-12T00:00:00+00:00", title="A scroll",
        extracted_text="body", raw_text="<raw>body</raw>",
        content_hash="sha256:a", stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:b", source="web", url="https://ex.com/b",
        saved_at="2026-06-12T01:00:00+00:00", title="Never checked",
        extracted_text="body", stage="fetched"))
    record_events(db, [
        CustodyEvent("web:a", "2026-06-14T00:00:00+00:00", "drifted", "h", "x", None),
    ])

    scroll = mcp_server.get_scroll("web:a")
    assert scroll["fidelity"] == "full"
    assert scroll["drift"] == "drifted"
    # agrees with the list_scrolls row for the same item
    row = next(r for r in mcp_server.list_scrolls() if r["id"] == "web:a")
    assert (scroll["fidelity"], scroll["drift"]) == (row["fidelity"], row["drift"])
    # honest never-checked default for an item with no verdict
    assert mcp_server.get_scroll("web:b")["drift"] == "unverified"


def test_mcp_surfaces_carry_last_checked_at_parity(scrolls_home):
    # H84: the time axis of the custody picture rides every MCP browse/inspect
    # twin — `get_scroll`, `list_scrolls`, `search_scrolls` — and reads the same
    # timestamp for the same item (one ledger, one `last_checked` primitive),
    # null when never re-checked.
    from scrolls.cli import main
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:a", source="web", url="https://ex.com/a",
        saved_at="2026-06-12T00:00:00+00:00", title="A database scroll",
        extracted_text="a database body", raw_text="<raw>db</raw>",
        content_hash="sha256:a", stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:b", source="web", url="https://ex.com/b",
        saved_at="2026-06-12T01:00:00+00:00", title="Never checked",
        extracted_text="body", stage="fetched"))
    record_events(db, [
        CustodyEvent("web:a", "2026-06-14T09:30:00+00:00", "drifted", "h", "x", None),
    ])

    scroll = mcp_server.get_scroll("web:a")
    row = next(r for r in mcp_server.list_scrolls() if r["id"] == "web:a")
    hit = next(h for h in mcp_server.search_scrolls("database") if h["id"] == "web:a")
    assert scroll["last_checked"] == row["last_checked"] == hit["last_checked"]
    assert scroll["last_checked"] == "2026-06-14T09:30:00+00:00"
    # honest never-checked default for an item with no verdict
    assert mcp_server.get_scroll("web:b")["last_checked"] is None


def test_get_scroll_and_list_surface_the_classification_method(
    scrolls_home, fake_wikipedia_api
):
    # the derived classification view travels with both MCP inspect surfaces,
    # identical to the CLI `show`/`list` payload (H20 parity)
    from scrolls.classify import RULESET_FINGERPRINT

    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")  # classifies inline
    expected = {
        "by": "rules-v1",
        "basis": "curated-source",
        "ruleset": RULESET_FINGERPRINT,
        # the confidence marker (H21) rides both MCP inspect surfaces identically
        "confidence": {"level": "deterministic", "freshness": "current"},
    }

    assert mcp_server.get_scroll("wikipedia:en:SQLite")["classification"] == expected
    row = next(r for r in mcp_server.list_scrolls() if r["id"] == "wikipedia:en:SQLite")
    assert row["classification"] == expected


def test_search_scrolls_surfaces_the_classification_method(scrolls_home, fake_wikipedia_api):
    # the derived classification view travels with ranked MCP hits too (H26),
    # identical to the CLI `search` payload and the inspect surfaces (H20 parity)
    from scrolls.classify import RULESET_FINGERPRINT

    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")  # classifies inline
    hits = mcp_server.search_scrolls("SQLite")
    assert hits[0]["classification"] == {
        "by": "rules-v1",
        "basis": "curated-source",
        "ruleset": RULESET_FINGERPRINT,
        "confidence": {"level": "deterministic", "freshness": "current"},
    }


def test_search_scrolls_omits_classification_for_an_unclassified_item(scrolls_home):
    # honest absence on the MCP ranked surface, matching list_scrolls' row shape
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    insert_item(get_paths().db_path, ScrollItem(
        id="web:plain", source="web", url="https://ex.com/plain",
        saved_at="2026-06-12T00:00:00+00:00", title="An ordinary post about pelicans",
        extracted_text="Pelicans are large water birds.", stage="fetched"))

    hits = mcp_server.search_scrolls("pelicans")
    assert "classification" not in hits[0]


def test_get_scroll_unknown_id_raises(scrolls_home):
    with pytest.raises(ValueError, match="no such item"):
        mcp_server.get_scroll("x:9999")


def test_get_scroll_accepts_the_items_url(scrolls_home, fake_wikipedia_api):
    # the saved URL is a valid handle anywhere an id is, like the CLI (ADR 0028)
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    item = mcp_server.get_scroll("https://en.wikipedia.org/wiki/SQLite")
    assert item["id"] == "wikipedia:en:SQLite"
    assert item["title"] == "SQLite"


def test_get_scroll_unknown_url_names_the_resolved_id(scrolls_home):
    # a miss reports the id the URL resolved to, so the resolution stays visible
    with pytest.raises(ValueError, match=r"no such item: wikipedia:en:SQLite \(from "):
        mcp_server.get_scroll("https://en.wikipedia.org/wiki/SQLite")


def test_get_related_scrolls_for_lonely_item_is_empty(scrolls_home, fake_wikipedia_api):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    assert mcp_server.get_related_scrolls("wikipedia:en:SQLite") == []


def test_get_related_scrolls_accepts_the_items_url(scrolls_home, fake_wikipedia_api):
    # resolving the present item's URL returns its (empty) related set, not an error
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    assert mcp_server.get_related_scrolls("https://en.wikipedia.org/wiki/SQLite") == []


def test_get_link_graph_returns_directed_edges(scrolls_home):
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="x:1111", source="x", url="https://x.com/a/status/1111",
        saved_at="2026-06-12T00:00:00+00:00", title="thread",
        links=("https://arxiv.org/abs/2605.27848",), stage="fetched",
    ))
    insert_item(db, ScrollItem(
        id="arxiv:2605.27848", source="arxiv", url="https://arxiv.org/abs/2605.27848",
        saved_at="2026-06-12T00:00:00+00:00", title="A Paper", stage="fetched",
    ))

    graph = mcp_server.get_link_graph()
    assert graph["edges"] == [
        {"from": "x:1111", "to": "arxiv:2605.27848", "via": "https://arxiv.org/abs/2605.27848"}
    ]
    # both items are bare → reference fidelity, never re-checked → unverified;
    # the custody block tallies the whole `stats.items` scope (roadmap H52)
    assert graph["stats"] == {
        "items": 2, "nodes": 2, "edges": 1, "clusters": 1,
        "custody": {
            "tiers": {"full": 0, "partial": 0, "reference": 2},
            "drift": {"verified": 0, "unverified": 2, "drifted": 0, "rotted": 0, "error": 0},
        },
    }


def test_get_link_graph_empty_library(scrolls_home):
    assert mcp_server.get_link_graph() == {
        "nodes": [], "edges": [], "stats": {
            "items": 0, "nodes": 0, "edges": 0, "clusters": 0,
            "custody": {
                "tiers": {"full": 0, "partial": 0, "reference": 0},
                "drift": {"verified": 0, "unverified": 0, "drifted": 0,
                          "rotted": 0, "error": 0},
            },
        },
    }


def test_node_shape_carries_drift_across_both_mcp_surfaces(scrolls_home):
    # the per-item drift posture rides the node shape on both MCP node-shape
    # twins — get_link_graph nodes and get_related_scrolls hits — and agrees (H56)
    from scrolls.cli import main
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="x:1111", source="x", url="https://x.com/a/status/1111",
        saved_at="2026-06-12T00:00:00+00:00", title="thread", concepts=("ml",),
        links=("https://arxiv.org/abs/2605.27848",), stage="fetched",
    ))
    insert_item(db, ScrollItem(
        id="arxiv:2605.27848", source="arxiv", url="https://arxiv.org/abs/2605.27848",
        saved_at="2026-06-12T00:00:00+00:00", title="A Paper", concepts=("ml",),
        stage="fetched",
    ))
    record_events(db, [
        CustodyEvent("arxiv:2605.27848", "t", "drifted", "h", "x", None),
        # x:1111 left unverified
    ])

    graph_nodes = {n["id"]: n for n in mcp_server.get_link_graph()["nodes"]}
    assert graph_nodes["arxiv:2605.27848"]["drift"] == "drifted"
    assert graph_nodes["x:1111"]["drift"] == "unverified"

    related = {r["id"]: r for r in mcp_server.get_related_scrolls("x:1111")}
    # the same item reads the same posture whichever node-shape surface reaches it
    assert related["arxiv:2605.27848"]["drift"] == "drifted"
    assert (
        related["arxiv:2605.27848"]["drift"]
        == graph_nodes["arxiv:2605.27848"]["drift"]
    )


def test_github_issue_thread_is_reachable_through_mcp(scrolls_home):
    # An issue/PR thread carries a '#' in its id (ADR 0084), a novel character
    # for the id<->URL resolver — confirm the agent-facing surface handles it:
    # the thread is fetchable by id and by URL, and its issue↔repo edge surfaces.
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="github:owner/repo#7", source="github", source_id="owner/repo#7",
        url="https://github.com/owner/repo/issues/7",
        saved_at="2026-06-12T00:00:00+00:00", title="owner/repo#7: A bug",
        links=("https://github.com/owner/repo",), stage="rendered",
    ))
    insert_item(db, ScrollItem(
        id="github:owner/repo", source="github", source_id="owner/repo",
        url="https://github.com/owner/repo",
        saved_at="2026-06-12T00:00:00+00:00", title="owner/repo", stage="rendered",
    ))

    # fetchable by the '#'-bearing id, and by the saved issue URL (resolve_item_id)
    assert mcp_server.get_scroll("github:owner/repo#7")["title"] == "owner/repo#7: A bug"
    by_url = mcp_server.get_scroll("https://github.com/owner/repo/issues/7")
    assert by_url["id"] == "github:owner/repo#7"

    # the issue↔repo edge surfaces in both per-item relate and the whole graph
    related = mcp_server.get_related_scrolls("https://github.com/owner/repo/issues/7")
    assert [r["id"] for r in related] == ["github:owner/repo"]
    assert mcp_server.get_link_graph()["edges"] == [
        {"from": "github:owner/repo#7", "to": "github:owner/repo",
         "via": "https://github.com/owner/repo"}
    ]


def test_get_works_clusters_by_shared_doi(scrolls_home):
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="arxiv:1706.03762", source="arxiv", source_id="1706.03762",
        url="https://arxiv.org/abs/1706.03762",
        saved_at="2026-06-12T00:00:00+00:00", title="Attention Is All You Need",
        links=("https://doi.org/10.5555/3295222",), stage="rendered",
    ))
    insert_item(db, ScrollItem(
        id="crossref:10.5555/3295222", source="crossref", source_id="10.5555/3295222",
        url="https://doi.org/10.5555/3295222",
        saved_at="2026-06-12T00:00:00+00:00", title="Attention Is All You Need",
        stage="fetched",
    ))

    payload = mcp_server.get_works()
    assert payload["stats"] == {"items": 2, "works": 1}
    # the floor travels with the result, same scope echo the CLI emits (G2)
    assert payload["scope"] == {"min_representations": 2}
    work = payload["works"][0]
    assert work["doi"] == "10.5555/3295222"
    assert [r["id"] for r in work["representations"]] == [
        "arxiv:1706.03762",
        "crossref:10.5555/3295222",
    ]
    # the published record is the work's canonical representation (ADR 0095)
    assert work["canonical"] == "crossref:10.5555/3295222"


def test_get_works_representation_carries_drift_at_parity_with_list(scrolls_home):
    # H64: the MCP works twin carries each representation's `drift` posture, in
    # agreement with the `list_scrolls` row for the same item (per-item parity)
    from scrolls.cli import main
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="arxiv:1706.03762", source="arxiv", source_id="1706.03762",
        url="https://arxiv.org/abs/1706.03762",
        saved_at="2026-06-12T00:00:00+00:00", title="Attention Is All You Need",
        links=("https://doi.org/10.5555/3295222",), stage="rendered",
        raw_text="the preprint body", content_hash="sha256:a",
    ))
    insert_item(db, ScrollItem(
        id="crossref:10.5555/3295222", source="crossref", source_id="10.5555/3295222",
        url="https://doi.org/10.5555/3295222",
        saved_at="2026-06-12T00:00:00+00:00", title="Attention Is All You Need",
        stage="rendered",
    ))
    record_events(db, [CustodyEvent(
        item_id="arxiv:1706.03762", checked_at="2026-06-14T00:00:00+00:00",
        status="unchanged", prior_hash="sha256:a", observed_hash="sha256:a")])

    reps = {
        r["id"]: r for r in mcp_server.get_works()["works"][0]["representations"]
    }
    rows = {r["id"]: r for r in mcp_server.list_scrolls()}
    for item_id in ("arxiv:1706.03762", "crossref:10.5555/3295222"):
        assert reps[item_id]["drift"] == rows[item_id]["drift"]
    assert reps["arxiv:1706.03762"]["drift"] == "verified"


def test_get_works_empty_library(scrolls_home):
    assert mcp_server.get_works() == {
        "scope": {"min_representations": 2},
        "works": [],
        "stats": {"items": 0, "works": 0},
    }


def test_get_works_item_lens_reports_one_items_work(scrolls_home):
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="arxiv:1706.03762", source="arxiv", source_id="1706.03762",
        url="https://arxiv.org/abs/1706.03762",
        saved_at="2026-06-12T00:00:00+00:00", title="Attention Is All You Need",
        links=("https://doi.org/10.5555/3295222",), stage="rendered",
    ))
    insert_item(db, ScrollItem(
        id="crossref:10.5555/3295222", source="crossref", source_id="10.5555/3295222",
        url="https://doi.org/10.5555/3295222",
        saved_at="2026-06-12T00:00:00+00:00", title="Attention Is All You Need",
        stage="fetched",
    ))
    # an unrelated paper that must not appear in the per-item view
    insert_item(db, ScrollItem(
        id="arxiv:2010.0", source="arxiv", source_id="2010.0",
        url="https://arxiv.org/abs/2010.0",
        saved_at="2026-06-12T00:00:00+00:00", title="Unrelated", stage="fetched",
    ))

    payload = mcp_server.get_works(item="arxiv:1706.03762")
    assert payload["stats"] == {"items": 3, "works": 1}  # items = whole library
    assert [w["doi"] for w in payload["works"]] == ["10.5555/3295222"]
    # the per-item lens echoes the resolved anchor, not the floor it ignores
    assert payload["scope"] == {"ref": "arxiv:1706.03762"}
    # the saved URL resolves the same as the id (ADR 0028) — including the
    # scope echo, which names the resolved id rather than the URL passed
    by_url = mcp_server.get_works(item="https://arxiv.org/abs/1706.03762")
    assert by_url == payload


def test_get_works_item_lens_unknown_item_raises(scrolls_home):
    from scrolls.cli import main

    main(["init"])
    with pytest.raises(ValueError, match="no such item: arxiv:nope"):
        mcp_server.get_works(item="arxiv:nope")


def test_get_context_bundle_is_markdown(scrolls_home, fake_wikipedia_api):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    bundle = mcp_server.get_context_bundle("database engine")
    assert bundle.startswith("# Scrolls Context Bundle: database engine")
    assert "wikipedia:en:SQLite" in bundle
    # the coverage line travels on the MCP twin too (completeness contract G2):
    # one match, under the cap, so the bundle states it is complete
    assert "Coverage: all 1 matching scrolls" in bundle


def test_get_context_bundle_honors_facets(scrolls_home, fake_wikipedia_api):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")  # category: reference

    bundle = mcp_server.get_context_bundle("database", source="wikipedia")
    assert bundle.startswith("# Scrolls Context Bundle: database (source=wikipedia)")
    assert "wikipedia:en:SQLite" in bundle
    # a facet that excludes everything still yields a valid, self-documenting bundle
    empty = mcp_server.get_context_bundle("database", source="arxiv")
    assert empty.startswith("# Scrolls Context Bundle: database (source=arxiv)")
    assert "No matching scrolls." in empty


def test_search_and_bundle_honor_tag_and_concept_facets(scrolls_home):
    # The tag/concept membership facets (ADR 0059) reach MCP clients through
    # the same search_items/build_context, so lock both surfaces here.
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="wikipedia:en:SQLite", source="wikipedia",
        url="https://en.wikipedia.org/wiki/SQLite",
        saved_at="2026-06-12T00:00:00+00:00",
        title="SQLite", extracted_text="SQLite is a database engine.",
        summary="SQLite is a database engine.",
        tags=("Database",), concepts=("Full-text search",), stage="rendered",
    ))
    insert_item(db, ScrollItem(
        id="arxiv:2401.0001", source="arxiv",
        url="https://arxiv.org/abs/2401.0001",
        saved_at="2026-06-12T00:00:00+00:00",
        title="A database paper",
        extracted_text="This paper studies database engines.",
        summary="This paper studies database engines.",
        tags=("ml",), concepts=("Neural networks",), stage="rendered",
    ))

    # concept facet (by slug) and tag facet (case-insensitive) on search_scrolls
    assert [h["id"] for h in mcp_server.search_scrolls(
        "database", concept="full text search"
    )] == ["wikipedia:en:SQLite"]
    assert [h["id"] for h in mcp_server.search_scrolls(
        "database", tag="DATABASE"
    )] == ["wikipedia:en:SQLite"]

    # the bundle inherits both facets and names them in the title
    bundle = mcp_server.get_context_bundle("database", concept="Full-text search")
    assert bundle.startswith(
        "# Scrolls Context Bundle: database (concept=Full-text search)"
    )
    assert "wikipedia:en:SQLite" in bundle
    assert "arxiv:2401.0001" not in bundle


def test_get_context_bundle_surfaces_connected_scrolls(scrolls_home):
    # The CLI's link-graph enrichment (ADR 0047) reaches MCP clients through
    # the same build_context — no MCP-side code, so it must be locked here.
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="wikipedia:en:SQLite", source="wikipedia",
        url="https://en.wikipedia.org/wiki/SQLite",
        saved_at="2026-06-12T00:00:00+00:00", title="SQLite",
        summary="SQLite is a database engine.", stage="rendered",
        links=("https://arxiv.org/abs/1706.03762",),
    ))
    insert_item(db, ScrollItem(
        id="arxiv:1706.03762", source="arxiv",
        url="https://arxiv.org/abs/1706.03762",
        saved_at="2026-06-12T00:00:00+00:00", title="Attention Is All You Need",
        summary="A sequence model built on attention.", stage="fetched",
    ))

    bundle = mcp_server.get_context_bundle("database engine")
    _, _, connected = bundle.partition("## Connected scrolls")
    assert "Attention Is All You Need" in connected
    assert "`arxiv:1706.03762`" in connected


def test_get_context_bundle_honors_budget(scrolls_home):
    # The progressive budget tiers (MVP M3) reach MCP clients through the same
    # build_context — no MCP-side code — so the tiering must be locked here too.
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    insert_item(get_paths().db_path, ScrollItem(
        id="wikipedia:en:SQLite", source="wikipedia",
        url="https://en.wikipedia.org/wiki/SQLite",
        saved_at="2026-06-12T00:00:00+00:00", title="SQLite",
        extracted_text="SQLite is a database engine with full-text search.",
        summary="SQLite is a database engine.", stage="rendered",
    ))

    # default is the full bundle (excerpts, no budget note)
    full = mcp_server.get_context_bundle("database")
    assert "## Excerpts" in full
    assert "Budget:" not in full

    # the index budget is catalog-only and self-discloses the reduced depth
    index = mcp_server.get_context_bundle("database", budget="index")
    assert "## Best Matches" in index
    assert "## Excerpts" not in index
    assert "Budget: index" in index


def test_get_concept_page_round_trips_spelling_via_slug(scrolls_home, fake_wikipedia_api):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    compile_kb(get_paths())
    page = mcp_server.get_concept_page("database MANAGEMENT systems")
    assert "# Concept: Database management systems" in page
    assert "SQLite" in page


def test_get_concept_page_missing_raises_with_remedy(scrolls_home):
    with pytest.raises(ValueError, match="scrolls kb"):
        mcp_server.get_concept_page("nonexistent concept")


def _insert_rendered(db, iid, source, title, *, tags=()):
    from scrolls.items import ScrollItem, insert_item
    slug = title.lower().replace(" ", "-")
    insert_item(db, ScrollItem(
        id=iid, source=source, url=f"https://e.org/{iid}",
        saved_at="2026-06-01T00:00:00+00:00", title=title, tags=tuple(tags),
        markdown_path=f"scrolls/{source}/{slug}.md", stage="rendered"))


def test_get_tag_page_round_trips_spelling_case_insensitively(scrolls_home):
    main(["init"])
    db = get_paths().db_path
    _insert_rendered(db, "pypi:flask", "pypi", "Flask", tags=("MIT",))
    _insert_rendered(db, "npm:express", "npm", "express", tags=("mit",))
    compile_kb(get_paths())
    # requested with a different case than the stored display spelling
    page = mcp_server.get_tag_page("mit")
    assert "# Tag: MIT" in page  # MIT/mit merged; smallest spelling displayed
    assert "Flask" in page and "express" in page


def test_get_tag_page_disambiguates_slug_collisions_by_heading(scrolls_home):
    """C++ and C# share the slug "c"; get_tag_page returns the right file."""
    main(["init"])
    db = get_paths().db_path
    _insert_rendered(db, "bitbucket:o/cpp", "bitbucket", "cpp", tags=("C++",))
    _insert_rendered(db, "bitbucket:o/cs", "bitbucket", "csharp", tags=("C#",))
    compile_kb(get_paths())
    assert "# Tag: C++" in mcp_server.get_tag_page("c++")
    assert "# Tag: C#" in mcp_server.get_tag_page("C#")


def test_get_tag_page_missing_raises_with_remedy(scrolls_home):
    with pytest.raises(ValueError, match="scrolls kb"):
        mcp_server.get_tag_page("nonexistent tag")


def test_list_sources_counts_items(scrolls_home, fake_wikipedia_api):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    mcp_server.ingest_url("https://x.com/karpathy/status/1111")  # stays detected
    assert mcp_server.list_sources() == {"wikipedia": 1, "x": 1}


def test_list_sources_before_init_is_empty(scrolls_home):
    assert mcp_server.list_sources() == {}


# --- feed subscriptions (ADR 0020) ---


def test_follow_feed_subscribes_and_lists(scrolls_home, fake_feed):
    payload = mcp_server.follow_feed(fake_feed)
    assert payload["feed_url"] == fake_feed
    assert payload["title"] == "A Weblog"
    assert payload["created"] is True

    listed = mcp_server.list_feed_subscriptions()
    assert [sub["feed_url"] for sub in listed] == [fake_feed]


def test_follow_feed_unreachable_url_raises(scrolls_home, fake_feed):
    from scrolls.feeds import FeedError

    with pytest.raises(FeedError, match="connection refused"):
        mcp_server.follow_feed("https://nowhere.example.com/feed")
    assert mcp_server.list_feed_subscriptions() == []


def test_list_feed_subscriptions_before_init_is_empty(scrolls_home):
    assert mcp_server.list_feed_subscriptions() == []


def test_sync_feeds_registers_entries_then_reports_unchanged(scrolls_home, fake_feed):
    mcp_server.follow_feed(fake_feed)

    first = mcp_server.sync_feeds()
    assert first["new"] == 2 and first["failed"] == 0
    assert first["results"][0]["status"] == "synced"

    second = mcp_server.sync_feeds()  # the stored ETag now answers 304
    assert second["unchanged"] == 1 and second["new"] == 0
    assert second["results"][0]["status"] == "unchanged"


def test_sync_feeds_by_unknown_id_raises(scrolls_home):
    with pytest.raises(ValueError, match="no such subscription"):
        mcp_server.sync_feeds("feedcafe1234")


def test_sync_feeds_before_init_is_empty_success(scrolls_home):
    payload = mcp_server.sync_feeds()
    assert payload["results"] == [] and payload["failed"] == 0


def test_unfollow_feed_accepts_id_or_url(scrolls_home, fake_feed):
    sub_id = mcp_server.follow_feed(fake_feed)["id"]
    assert mcp_server.unfollow_feed(fake_feed) == {"id": sub_id, "removed": True}
    assert mcp_server.list_feed_subscriptions() == []

    with pytest.raises(ValueError, match="no such subscription"):
        mcp_server.unfollow_feed(sub_id)  # already gone

def test_compile_library_builds_the_pages_get_concept_page_serves(
    scrolls_home, fake_wikipedia_api
):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    with pytest.raises(ValueError):
        mcp_server.get_concept_page("Database management systems")

    payload = mcp_server.compile_library()
    assert payload["items"] == 1
    assert payload["concepts"] == 1
    assert payload["pages"] >= 3  # index + source + concept (+ category)

    page = mcp_server.get_concept_page("Database management systems")
    assert "SQLite" in page


def test_get_concept_page_serves_related_concepts(scrolls_home):
    """The deterministic Related Concepts section (ADR 0063) reaches MCP for free."""
    from scrolls.db import init_db
    from scrolls.items import ScrollItem, insert_item

    paths = get_paths()
    paths.root.mkdir(parents=True)
    init_db(paths.db_path)
    for item_id, concepts in (
        ("web:a", ("BM25", "Full-text search")),
        ("web:b", ("BM25", "Full-text search")),
    ):
        insert_item(paths.db_path, ScrollItem(
            id=item_id, source="web", url=f"https://ex.org/{item_id}",
            saved_at="2026-06-01T00:00:00+00:00", title=item_id,
            concepts=concepts, markdown_path=f"scrolls/web/{item_id[-1]}.md",
            stage="rendered"))
    mcp_server.compile_library()

    page = mcp_server.get_concept_page("BM25")
    assert "## Related Concepts" in page
    assert "[Full-text search](full-text-search.md) — 2 shared scrolls" in page


def test_compile_library_includes_stored_concept_summaries(
    scrolls_home, fake_wikipedia_api
):
    from scrolls.kb import ConceptSummary, save_concept_summary

    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    save_concept_summary(get_paths().db_path, ConceptSummary(
        slug="database-management-systems",
        display="Database management systems",
        summary="The library's database scrolls cluster here.",
        members_hash="abc",
        engine="kb-llm-v1",
        model="claude-test",
        generated_at="2026-06-12T00:00:00+00:00",
    ))

    payload = mcp_server.compile_library()
    assert payload["summaries"] == 1
    page = mcp_server.get_concept_page("Database management systems")
    assert "The library's database scrolls cluster here." in page


def test_compile_library_before_init_is_a_zero_run(scrolls_home):
    payload = mcp_server.compile_library()
    assert payload == {"items": 0, "sources": 0, "categories": 0,
                       "concepts": 0, "tags": 0, "summaries": 0, "clusters": 0, "works": 0, "pages": 0}
    assert not scrolls_home.exists()  # compiling never creates a library
