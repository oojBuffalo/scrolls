"""Tests for the MCP server (IDEAS.md §10, ADR 0014).

The tool functions are plain wrappers over the same engines the CLI
uses, so they are tested directly against a temp library — no protocol
client, no network (the wikipedia transport is faked). One test builds
the real FastMCP server to lock the registered tool surface.
"""

import asyncio
import dataclasses
import json
import re

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


# --- H364: the MCP tool registry is a custody-safety boundary ---------------
# The registered tool surface is the agent transport into the library. Every
# tool must be a *read* or a *custody-safe write* — none may delete or overwrite
# a held capture (custody-vision §2.4, raw-is-sacred). The exact-set allow-list
# forces a new tool to be classified before it can ship (the registry-completeness
# analogue of M2's search-completeness contract); the verb scan is the backstop
# for a destroyer that someone also slipped into the allow-list.

# Reads — never touch a held capture.
_MCP_READ_TOOLS = frozenset(
    {
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
        "list_archived",
        "get_archived",
        "get_library_health",
        "get_maintenance_history",
        "list_feed_subscriptions",
    }
)
# Custody-safe writes — add a capture (`ingest_url`), record a ledger event
# (`verify_scroll`), regenerate a view (`run_maintenance`/`compile_library`), or
# manage a feed subscription (`follow_feed`/`unfollow_feed`/`sync_feeds`). None
# destroy or overwrite raw: the prune is the shell's explicit `scrolls rm`, never
# an MCP act (H355).
_MCP_SAFE_WRITE_TOOLS = frozenset(
    {
        "ingest_url",
        "verify_scroll",
        "run_maintenance",
        "compile_library",
        "follow_feed",
        "unfollow_feed",
        "sync_feeds",
    }
)
# Feed-subscription ops live in their own namespace: a future `remove_subscription`
# would carry a destructive verb yet only touch a subscription row, never a held
# capture. Whitelist them so the verb scan stays a clean backstop, not a false
# alarm — the exact-set allow-list still forces such a tool to be classified.
_MCP_FEED_OPS = frozenset(
    {"follow_feed", "unfollow_feed", "sync_feeds", "list_feed_subscriptions"}
)
# Verbs that, applied to a scroll/item/capture, would breach raw-is-sacred.
_MCP_DESTRUCTIVE_VERBS = frozenset(
    {"delete", "remove", "drop", "purge", "prune", "rm", "overwrite", "merge"}
)


def _assert_mcp_registry_is_classified(names):
    """Every registered MCP tool is a classified read or custody-safe write.

    A new tool must be triaged into one bucket to pass — adding a
    capture-mutating tool fails loudly and forces an ADR.
    """
    assert set(names) == _MCP_READ_TOOLS | _MCP_SAFE_WRITE_TOOLS


def _assert_mcp_registry_has_no_destroyer(names):
    """No non-feed MCP tool name carries a capture-destroying verb.

    Token-based (snake_case) so `transform`-style names never false-positive on
    the short `rm` verb; the backstop catches a destroyer even if it were also
    added to the allow-list above.
    """
    for name in names:
        if name in _MCP_FEED_OPS:
            continue
        offending = set(name.split("_")) & _MCP_DESTRUCTIVE_VERBS
        assert not offending, f"{name} carries capture-destroying verb(s) {sorted(offending)}"


def test_server_exposes_exactly_the_documented_tools(scrolls_home):
    server = mcp_server.build_server()
    tools = asyncio.run(server.list_tools())
    # one source of truth: the documented surface is the classified allow-list
    assert {tool.name for tool in tools} == _MCP_READ_TOOLS | _MCP_SAFE_WRITE_TOOLS
    # every tool teaches the model what it does
    assert all(tool.description for tool in tools)


def test_mcp_registry_holds_the_custody_line(scrolls_home):
    """H364: the registered MCP tool surface can never destroy or overwrite a
    held capture — every tool is a classified read or custody-safe write, and no
    tool name carries a capture-destroying verb (custody-vision §2.4,
    raw-is-sacred; the M2 tested-contract shape lifted to the tool registry).

    Pins `mcp_server._TOOLS` directly (the registration source), not only the
    built server — so a future convenience `delete_scroll` / a `update_item`
    that rewrites `raw_text`/`content_hash` fails loudly over the agent
    transport, the way H355's "the prune is a CLI choice" premise requires.
    """
    # `_TOOLS` is exactly what `build_server` registers — pin the "≡" the
    # contract leans on, so classifying `_TOOLS` classifies the live transport.
    server = mcp_server.build_server()
    registered = {tool.name for tool in asyncio.run(server.list_tools())}
    source = {fn.__name__ for fn in mcp_server._TOOLS}
    assert source == registered

    # (1) exact-set allow-list and (2) the verb-scan backstop both hold today.
    _assert_mcp_registry_is_classified(source)
    _assert_mcp_registry_has_no_destroyer(source)


def test_mcp_registry_guard_rejects_a_capture_destroying_tool():
    """Sabotage check: a stub `delete_scroll` appended to the registry must fail
    *both* halves of the H364 guard, so the contract isn't vacuous.

    It is unclassified (allow-list mismatch) and carries a destructive verb (the
    backstop) — either one would catch a regression that slipped it past the
    other (e.g. a destroyer also added to the allow-list).
    """
    sabotaged = {fn.__name__ for fn in mcp_server._TOOLS} | {"delete_scroll"}
    # half (1): unclassified — not in the read ∪ safe-write allow-list
    with pytest.raises(AssertionError):
        _assert_mcp_registry_is_classified(sabotaged)
    # half (2): the verb scan catches it independently of the allow-list
    with pytest.raises(AssertionError):
        _assert_mcp_registry_has_no_destroyer(sabotaged)


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


# --- list_archived / get_archived (H281, ADR 0106): the MCP *read* twin of the
# prior-content recovery store — what an accept-incoming adoption superseded, and
# the recoverable prior snapshot. The write stays operator-gated (custody §2.4). ---


def _seed_with_archived_prior(
    content_hash="sha256:held", *, archived_at="2026-06-22T00:00:00+00:00"
):
    """A held item whose prior copy was superseded by an accept-incoming adoption.

    Seeds the held item, then `adopt_incoming` (the one custody-safe overwrite) so
    the prior is archived (recoverable) and the held copy carries the incoming —
    exactly the state a CLI `import … --accept-incoming` leaves. Returns the prior.
    """
    from scrolls.items import adopt_incoming

    held = _seed_verifiable_item(content_hash=content_hash)
    incoming = dataclasses.replace(
        held, content_hash="sha256:peer", extracted_text="peer body"
    )
    prior = adopt_incoming(get_paths().db_path, incoming, archived_at=archived_at)
    return prior


def test_list_archived_indexes_superseded_captures(scrolls_home):
    # H281: the MCP recovery index — the metadata an accept-incoming adoption
    # archived (what was replaced, hash before/after, when), newest first.
    prior = _seed_with_archived_prior()
    listed = mcp_server.list_archived()
    assert listed["count"] == 1
    entry = listed["archived"][0]
    assert entry == {
        "item_id": "web:demo",
        "prior_hash": "sha256:held",       # what was archived
        "superseded_by": "sha256:peer",    # what replaced it
        "archived_at": "2026-06-22T00:00:00+00:00",
    }
    assert prior.content_hash == "sha256:held"  # the held copy that was superseded


def test_list_archived_empty_library_is_honest_empty(scrolls_home):
    # an initialized library that never adopted anything holds nothing — never error
    _seed_verifiable_item()
    assert mcp_server.list_archived() == {"count": 0, "archived": []}


def test_list_archived_before_init_is_honest_empty(scrolls_home):
    # a pre-v8 / uninitialized library honestly holds nothing, never an error
    assert mcp_server.list_archived() == {"count": 0, "archived": []}


def test_list_archived_scopes_to_one_item(scrolls_home):
    # `item_id` scopes the index to one item; an unrelated id has no archived priors
    _seed_with_archived_prior()
    assert mcp_server.list_archived("web:demo")["count"] == 1
    assert mcp_server.list_archived("web:other") == {"count": 0, "archived": []}


def test_list_archived_converges_with_cli_archive_list(scrolls_home, capsys):
    # convergence by construction: the MCP twin returns the *same* `{count, archived}`
    # shape the CLI `archive list` prints, folding the same `archive_entry_dict`.
    _seed_with_archived_prior()
    capsys.readouterr()
    assert main(["archive", "list"]) == 0
    cli = json.loads(capsys.readouterr().out)
    assert mcp_server.list_archived() == cli


def test_get_archived_returns_the_model_complete_snapshot(scrolls_home):
    # H281: the recoverable prior snapshot as the re-importable `item_to_dict` shape,
    # so an agent can recover the prior bytes (and hand them back to a CLI restore).
    from scrolls.items import item_from_dict

    prior = _seed_with_archived_prior()
    snapshot = mcp_server.get_archived("web:demo")
    assert snapshot["content_hash"] == "sha256:held"
    assert snapshot["extracted_text"] == "captured body"  # the prior body, recovered
    # re-importable: round-trips back to the archived prior ScrollItem byte-for-byte
    assert item_from_dict(snapshot) == prior


def test_get_archived_converges_with_cli_archive_show(scrolls_home, capsys):
    # convergence by construction: the MCP snapshot equals the CLI `archive show`
    # JSONL line (the same `item_to_dict` the export shape carries).
    _seed_with_archived_prior()
    capsys.readouterr()
    assert main(["archive", "show", "web:demo"]) == 0
    cli_line = json.loads(capsys.readouterr().out.splitlines()[0])
    assert mcp_server.get_archived("web:demo") == cli_line


def test_get_archived_no_prior_raises(scrolls_home):
    # a known but never-superseded item has no archived prior — the could-not-recover
    # signal (the MCP twin of `archive show`'s exit 1), never a silent empty
    _seed_verifiable_item()
    with pytest.raises(ValueError, match="no archived prior capture for web:demo"):
        mcp_server.get_archived("web:demo")


def test_get_archived_unknown_item_raises(scrolls_home):
    main(["init"])
    with pytest.raises(ValueError, match="no archived prior capture"):
        mcp_server.get_archived("web:nope")


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


def test_search_scrolls_hits_carry_the_match_explanation(scrolls_home, fake_wikipedia_api):
    # the explainable-ranking axis travels over MCP too: each hit names which
    # indexed fields the query landed in (`matched_fields`) and the qualitative
    # strength of the strongest (`match_strength`), the same keys `scrolls search`
    # surfaces — one home, via the shared `hit_payload`.
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    # the query term is the page title ("SQLite"), the highest-weighted field
    (hit,) = mcp_server.search_scrolls("SQLite")
    assert "title" in hit["matched_fields"]
    assert hit["match_strength"] == "strong"


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


def test_search_scrolls_filters_by_fidelity_tier(scrolls_home):
    # the holdings-axis filter on the ranked surface — the MCP twin of
    # `scrolls search --fidelity` and the search sibling of
    # `list_scrolls(fidelity=)` (ADR 0097). Returns only the matches the library
    # holds at the named tier, the same per-hit `fidelity` each hit already shows.
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:full0", source="web", url="https://ex.com/full0",
        saved_at="2026-06-12T00:00:00+00:00", title="Full database alpha",
        raw_text="A database engine held in full.", content_hash="sha256:a",
        stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:full1", source="web", url="https://ex.com/full1",
        saved_at="2026-06-12T00:00:01+00:00", title="Full database beta",
        raw_text="Another database engine held in full.", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:partial", source="web", url="https://ex.com/partial",
        saved_at="2026-06-12T00:00:02+00:00", title="Partial database",
        extracted_text="A database, content held but no hash.", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:reference", source="web", url="https://ex.com/reference",
        saved_at="2026-06-12T00:00:03+00:00", title="Reference database",
        stage="detected"))

    assert {r["id"] for r in mcp_server.search_scrolls("database", fidelity="full")} == {
        "web:full0", "web:full1"
    }
    assert [r["id"] for r in mcp_server.search_scrolls("database", fidelity="partial")] == [
        "web:partial"
    ]
    assert [
        r["id"] for r in mcp_server.search_scrolls("database", fidelity="reference")
    ] == ["web:reference"]
    # every returned hit shows exactly the tier it was selected by
    for tier in ("full", "partial", "reference"):
        hits = mcp_server.search_scrolls("database", fidelity=tier)
        assert hits and all(h["fidelity"] == tier for h in hits)


def test_search_scrolls_rejects_an_unknown_fidelity_tier(scrolls_home):
    # the same closed vocabulary as `list_scrolls(fidelity=)`; never a silent empty
    import pytest

    from scrolls.cli import main

    main(["init"])
    with pytest.raises(ValueError):
        mcp_server.search_scrolls("database", fidelity="ful")


def test_search_scrolls_filters_by_drift_posture(scrolls_home):
    # the ledger-claim-axis filter on the ranked surface — the MCP twin of
    # `scrolls search --drift` and the search sibling of `list_scrolls(drift=)`
    # (H58). Returns only the matches whose latest verify verdict reads at the
    # named posture, the same per-hit `drift` each hit already shows.
    from scrolls.cli import main
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    for ident in ("verified0", "verified1", "drifted", "never"):
        insert_item(db, ScrollItem(
            id=f"web:{ident}", source="web", url=f"https://ex.com/{ident}",
            saved_at="2026-06-12T00:00:00+00:00",
            title=f"{ident.capitalize()} database engine",
            raw_text="A database engine.", content_hash=f"sha256:{ident}",
            stage="rendered"))
    record_events(db, [
        CustodyEvent("web:verified0", "t", "unchanged", "h", "h", None),
        CustodyEvent("web:verified1", "t", "unchanged", "h", "h", None),
        CustodyEvent("web:drifted", "t", "drifted", "h", "x", None),
        # web:never left unverified
    ])

    assert {r["id"] for r in mcp_server.search_scrolls("database", drift="verified")} == {
        "web:verified0", "web:verified1"
    }
    assert [r["id"] for r in mcp_server.search_scrolls("database", drift="drifted")] == [
        "web:drifted"
    ]
    assert [
        r["id"] for r in mcp_server.search_scrolls("database", drift="unverified")
    ] == ["web:never"]
    # every returned hit shows exactly the posture it was selected by
    for posture in ("verified", "drifted", "unverified"):
        hits = mcp_server.search_scrolls("database", drift=posture)
        assert hits and all(h["drift"] == posture for h in hits)


def test_search_scrolls_rejects_an_unknown_drift_posture(scrolls_home):
    # the same closed vocabulary as `list_scrolls(drift=)`; never a silent empty
    import pytest

    from scrolls.cli import main

    main(["init"])
    with pytest.raises(ValueError):
        mcp_server.search_scrolls("database", drift="drift")


def test_search_scrolls_filters_by_match_strength(scrolls_home):
    # the rank-axis filter on the ranked surface — the MCP twin of `scrolls search
    # --strength` (H314) and the rank sibling of fidelity/drift. Keeps only the
    # matches whose query lands at or above a band (a threshold), the same per-hit
    # `match_strength` each hit already shows.
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:strong", source="web", url="https://ex.com/strong",
        saved_at="2026-06-12T00:00:00+00:00", title="widget overview",
        extracted_text="An intro line. The body discusses a gadget.", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:moderate", source="web", url="https://ex.com/moderate",
        saved_at="2026-06-12T00:00:01+00:00", title="gadget notes",
        extracted_text="A widget appears in the summary. More body text.",
        summary="A widget appears in the summary", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:weak", source="web", url="https://ex.com/weak",
        saved_at="2026-06-12T00:00:02+00:00", title="unrelated topic",
        extracted_text="A first sentence. Later the widget appears in the body.",
        summary="A first sentence", stage="fetched"))

    # strong keeps the title hit; moderate adds the summary hit; weak keeps all
    assert [r["id"] for r in mcp_server.search_scrolls("widget", strength="strong")] == [
        "web:strong"
    ]
    assert {r["id"] for r in mcp_server.search_scrolls("widget", strength="moderate")} == {
        "web:strong", "web:moderate"
    }
    assert {r["id"] for r in mcp_server.search_scrolls("widget", strength="weak")} == {
        "web:strong", "web:moderate", "web:weak"
    }
    # every returned hit reads at the band or stronger (the threshold)
    order = ["strong", "moderate", "weak"]
    for band in order:
        kept = set(order[: order.index(band) + 1])
        hits = mcp_server.search_scrolls("widget", strength=band)
        assert hits and all(h["match_strength"] in kept for h in hits)


def test_search_scrolls_rejects_an_unknown_match_strength(scrolls_home):
    # the same closed vocabulary as `scrolls search --strength`; never a silent empty
    import pytest

    from scrolls.cli import main

    main(["init"])
    with pytest.raises(ValueError):
        mcp_server.search_scrolls("widget", strength="strongest")


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


def test_list_scrolls_filters_by_fidelity_tier(scrolls_home):
    # the MCP twin of `scrolls list --fidelity` (ADR 0097): the holdings-axis
    # companion of the drift filter. The items returned for a tier total
    # `list_facets("fidelity")`'s count for it (drill-from-the-count).
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:full0", source="web", url="https://ex.com/full0",
        saved_at="2026-06-12T00:00:00+00:00", title="Full 0",
        extracted_text="A re-derivable body.", content_hash="sha256:a",
        stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:full1", source="web", url="https://ex.com/full1",
        saved_at="2026-06-12T00:00:01+00:00", title="Full 1",
        raw_text="Raw held in full.", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:partial", source="web", url="https://ex.com/partial",
        saved_at="2026-06-12T00:00:02+00:00", title="Partial",
        extracted_text="Content held, but no hash.", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:reference", source="web", url="https://ex.com/reference",
        saved_at="2026-06-12T00:00:03+00:00", title="Reference",
        stage="detected"))

    assert [r["id"] for r in mcp_server.list_scrolls(fidelity="full")] == [
        "web:full0", "web:full1"
    ]
    assert [r["id"] for r in mcp_server.list_scrolls(fidelity="partial")] == [
        "web:partial"
    ]
    assert [r["id"] for r in mcp_server.list_scrolls(fidelity="reference")] == [
        "web:reference"
    ]

    # convergence with the facet aggregate the twin `list_facets` reports
    counts = {
        e["value"]: e["count"]
        for e in mcp_server.list_facets("fidelity")["facets"]["fidelity"]
    }
    for tier, count in counts.items():
        assert len(mcp_server.list_scrolls(fidelity=tier)) == count


def test_list_scrolls_rejects_an_unknown_fidelity_tier(scrolls_home):
    # a closed vocabulary: an unknown tier is an error, never a silent empty
    import pytest

    from scrolls.cli import main

    main(["init"])
    with pytest.raises(ValueError):
        mcp_server.list_scrolls(fidelity="ful")


def test_list_scrolls_filters_by_stale_before(scrolls_home):
    # the MCP twin of `scrolls list --stale-before` (H85): the stale set — items
    # whose newest verdict predates the boundary, never-checked included.
    from scrolls.cli import main
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    for name in ("old", "new", "never"):
        insert_item(db, ScrollItem(
            id=f"web:{name}", source="web", url=f"https://ex.com/{name}",
            saved_at="2026-06-12T00:00:00+00:00", title=f"Post {name}",
            extracted_text="body", content_hash=f"sha256:{name}", stage="fetched"))
    record_events(db, [
        CustodyEvent("web:old", "2026-06-10T00:00:00+00:00", "unchanged", "h", "h", None),
        CustodyEvent("web:new", "2026-06-14T00:00:00+00:00", "unchanged", "h", "h", None),
    ])

    stale = {r["id"] for r in mcp_server.list_scrolls(stale_before="2026-06-12T00:00:00+00:00")}
    assert stale == {"web:old", "web:never"}


def test_list_scrolls_rejects_a_malformed_stale_before(scrolls_home):
    # a malformed boundary raises (the CLI maps the same ValueError to exit 2)
    import pytest

    from scrolls.cli import main

    main(["init"])
    with pytest.raises(ValueError):
        mcp_server.list_scrolls(stale_before="not-a-date")


def test_list_scrolls_before_init_returns_empty(scrolls_home):
    assert mcp_server.list_scrolls() == []


def _seed_stale_classified(db, item_id, source, ruleset):
    """Insert an item rules-classified under `ruleset` — a superseded one reads stale."""
    from scrolls.items import ScrollItem, insert_item

    insert_item(db, ScrollItem(
        id=item_id, source=source, url=f"https://{source}.example.com/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00", title=item_id, category="reference",
        extracted_text="body", content_hash=f"sha256:{item_id[-6:]}", stage="fetched",
        provenance={"classified_by": "rules-v1", "classified_basis": "curated-source",
                    "classified_ruleset": ruleset}))


def test_list_scrolls_filters_by_stale_classification(scrolls_home):
    # the MCP twin of `scrolls list --stale-classification` (H185): the items whose
    # category the live ruleset would no longer reproduce — the stale-enrichment set.
    from scrolls.classify import RULESET_FINGERPRINT

    main(["init"])
    db = get_paths().db_path
    _seed_stale_classified(db, "web:stale", "web", "deadbeef0000")    # superseded → stale
    _seed_stale_classified(db, "arxiv:stale", "arxiv", "deadbeef0000")  # superseded → stale
    _seed_stale_classified(db, "web:current", "web", RULESET_FINGERPRINT)  # live → not stale

    stale = {r["id"] for r in mcp_server.list_scrolls(stale_classification=True)}
    assert stale == {"web:stale", "arxiv:stale"}

    # ANDs with `source` to drill one source's refresh debt
    web = mcp_server.list_scrolls(stale_classification=True, source="web")
    assert [r["id"] for r in web] == ["web:stale"]


def test_list_scrolls_stale_classification_totals_the_health_aggregate(scrolls_home):
    # drill-from-the-count convergence (H185): the rows total `get_library_health`'s
    # custody.enrichment.stale, and the `source` narrowing its enrichment.by_source[S].
    from scrolls.classify import RULESET_FINGERPRINT

    main(["init"])
    db = get_paths().db_path
    _seed_stale_classified(db, "web:stale", "web", "deadbeef0000")
    _seed_stale_classified(db, "arxiv:stale", "arxiv", "deadbeef0000")
    _seed_stale_classified(db, "web:current", "web", RULESET_FINGERPRINT)

    enrichment = mcp_server.get_library_health()["enrichment"]
    rows = mcp_server.list_scrolls(stale_classification=True)
    assert len(rows) == enrichment["stale"]
    for source, count in enrichment["by_source"].items():
        scoped = mcp_server.list_scrolls(stale_classification=True, source=source)
        assert len(scoped) == count


def test_list_scrolls_stale_classification_is_empty_when_nothing_stale(scrolls_home):
    # honest absence: a library with no stale classifications is [], never an error
    from scrolls.classify import RULESET_FINGERPRINT

    main(["init"])
    db = get_paths().db_path
    _seed_stale_classified(db, "web:current", "web", RULESET_FINGERPRINT)
    assert mcp_server.list_scrolls(stale_classification=True) == []


def _seed_stale_summary_member(db, item_id, source, concept):
    """A rendered cluster member carrying one concept (stale-summary fixture)."""
    from scrolls.items import ScrollItem, insert_item

    insert_item(db, ScrollItem(
        id=item_id, source=source, url=f"https://{source}.example.com/{item_id}",
        saved_at="2026-06-14T00:00:00+00:00", title=item_id,
        extracted_text="A note about the concept.", content_hash="sha256:" + item_id,
        concepts=(concept,), stage="rendered",
        markdown_path=f"scrolls/{source}/{item_id}.md"))


def _store_stale_summary(db, slug, display):
    """A stored summary whose fingerprint no longer matches its live cluster."""
    from scrolls.kb import ConceptSummary, save_concept_summary

    save_concept_summary(db, ConceptSummary(
        slug=slug, display=display, summary="How it shows up.",
        members_hash="stale-old-digest", engine="kb-llm-v1",
        model="claude-opus-4-8", generated_at="2026-06-16T00:00:00+00:00"))


def _seed_stale_summaries(db):
    """Two stale summaries: Bm25 (web+arxiv) and Vector (web+web) → 4 members."""
    _seed_stale_summary_member(db, "web:bw", "web", "Bm25")
    _seed_stale_summary_member(db, "arxiv:ba", "arxiv", "Bm25")
    _seed_stale_summary_member(db, "web:v1", "web", "Vector")
    _seed_stale_summary_member(db, "web:v2", "web", "Vector")
    _store_stale_summary(db, "bm25", "Bm25")
    _store_stale_summary(db, "vector", "Vector")


def test_list_scrolls_filters_by_stale_summary(scrolls_home):
    # the MCP twin of `scrolls list --stale-summary` (H189): the items belonging to
    # a concept whose stored LLM summary the live members no longer reproduce — the
    # members a `kb --stale` refresh's clusters span.
    main(["init"])
    db = get_paths().db_path
    _seed_stale_summaries(db)

    stale = {r["id"] for r in mcp_server.list_scrolls(stale_summary=True)}
    assert stale == {"web:bw", "arxiv:ba", "web:v1", "web:v2"}

    # ANDs with `source`, carrying the H171 attribution: a multi-source stale
    # cluster lists every member, so `--source S` returns S's members.
    web = {r["id"] for r in mcp_server.list_scrolls(stale_summary=True, source="web")}
    assert web == {"web:bw", "web:v1", "web:v2"}
    arxiv = mcp_server.list_scrolls(stale_summary=True, source="arxiv")
    assert [r["id"] for r in arxiv] == ["arxiv:ba"]


def test_list_scrolls_stale_summary_lists_the_health_stale_concept_members(scrolls_home):
    # convergence with the audit (H189): the rows are exactly the members of the
    # concepts `get_library_health` flags stale in summaries.items.
    from scrolls.kb import slugify

    main(["init"])
    db = get_paths().db_path
    _seed_stale_summaries(db)

    stale_slugs = {
        e["slug"] for e in mcp_server.get_library_health()["summaries"]["items"]
    }
    assert stale_slugs == {"bm25", "vector"}

    from scrolls.items import list_items

    expected = {
        item.id
        for item in list_items(db)
        if any(slugify(c) in stale_slugs for c in item.concepts)
    }
    rows = {r["id"] for r in mcp_server.list_scrolls(stale_summary=True)}
    assert rows == expected


def test_list_scrolls_stale_summary_is_empty_when_nothing_stale(scrolls_home):
    # honest absence: a library with no stale summaries is [], never an error
    main(["init"])
    db = get_paths().db_path
    _seed_stale_summary_member(db, "web:fresh", "web", "Fresh")
    assert mcp_server.list_scrolls(stale_summary=True) == []


# --- H338: content-duplicate browse filter — MCP parity with the CLI ---------


def _seed_content_duplicate_mix(db):
    """Two byte-identical content groups + a unique held + a NULL-hash reference.

    Group 1 is cross-source (`web:a`/`arxiv:1`, full); group 2 single-source
    (`web:p`/`web:q`, partial — summary + hash, no body); `web:solo` is held
    unique; `web:ref` reference-only. The same mix the CLI H338 tests use, so the
    MCP twins can be checked at parity. All carry the `alpha` token so the ranked
    surface matches them.
    """
    from scrolls.items import ScrollItem, insert_item

    insert_item(db, ScrollItem(
        id="web:a", source="web", url="https://e.com/a",
        saved_at="2026-06-12T00:00:00+00:00", title="alpha copy",
        extracted_text="body", raw_text="<r>body</r>",
        content_hash="sha256:dup1", stage="rendered"))
    insert_item(db, ScrollItem(
        id="arxiv:1", source="arxiv", url="https://arxiv.org/abs/1",
        saved_at="2026-06-12T01:00:00+00:00", title="alpha mirror",
        extracted_text="body", raw_text="<r>body</r>",
        content_hash="sha256:dup1", stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:p", source="web", url="https://e.com/p",
        saved_at="2026-06-12T02:00:00+00:00", title="alpha p",
        summary="alpha digest", content_hash="sha256:dup2", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:q", source="web", url="https://e.com/q",
        saved_at="2026-06-12T03:00:00+00:00", title="alpha q",
        summary="alpha digest", content_hash="sha256:dup2", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:solo", source="web", url="https://e.com/solo",
        saved_at="2026-06-12T04:00:00+00:00", title="alpha solo",
        extracted_text="x", raw_text="<r>x</r>",
        content_hash="sha256:solo", stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:ref", source="web", url="https://e.com/ref",
        saved_at="2026-06-12T05:00:00+00:00", title="alpha ref"))


def test_list_scrolls_filters_by_content_duplicate(scrolls_home):
    # H338: the MCP twin of `scrolls list --content-duplicate` — keeps only the
    # held items carrying a byte-identical sibling, dropping the unique held item
    # and the NULL-hash reference; whole-library sibling scope (web:a kept under
    # source=web though its sibling is arxiv); composes with source/fidelity.
    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)

    assert {r["id"] for r in mcp_server.list_scrolls(content_duplicate=True)} == {
        "web:a", "arxiv:1", "web:p", "web:q"
    }
    # whole-library sibling scope: web:a's only sibling (arxiv:1) is out of scope
    assert {
        r["id"] for r in mcp_server.list_scrolls(content_duplicate=True, source="web")
    } == {"web:a", "web:p", "web:q"}
    # ANDs with fidelity
    assert {
        r["id"] for r in mcp_server.list_scrolls(content_duplicate=True, fidelity="full")
    } == {"web:a", "arxiv:1"}


def test_search_scrolls_filters_by_content_duplicate(scrolls_home):
    # H338: the MCP twin of `scrolls search --content-duplicate` — keeps only the
    # matches the library holds a byte-identical copy of, ANDed before the cap.
    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)

    assert {
        r["id"] for r in mcp_server.search_scrolls("alpha", content_duplicate=True)
    } == {"web:a", "arxiv:1", "web:p", "web:q"}
    assert {
        r["id"]
        for r in mcp_server.search_scrolls(
            "alpha", content_duplicate=True, fidelity="full"
        )
    } == {"web:a", "arxiv:1"}


def test_content_duplicate_filter_is_cli_mcp_byte_parity(scrolls_home, capsys):
    # H338: the MCP twins read byte-identical to the CLI surfaces on the
    # content-identity axis (the MCP-is-a-thin-wrapper invariant) — list and search.
    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)
    capsys.readouterr()

    # the MCP payloads carry tuples (works/matched_fields) the CLI renders as JSON
    # lists, so normalize both through one json round-trip — the standard parity tie
    def as_json(value):
        return json.loads(json.dumps(value))

    main(["list", "--content-duplicate"])
    cli_list = json.loads(capsys.readouterr().out)
    assert as_json(
        mcp_server.list_scrolls(content_duplicate=True, limit=len(cli_list) + 1)
    ) == cli_list

    main(["search", "alpha", "--content-duplicate"])
    cli_search = json.loads(capsys.readouterr().out)
    assert as_json(mcp_server.search_scrolls("alpha", content_duplicate=True)) == cli_search


def test_list_facets_content_duplicate_converges_with_the_drill_and_doctor(scrolls_home, capsys):
    # H342: `list_facets("content-duplicate")` partitions held items into
    # duplicate/unique by the SAME content_duplicate_index the `--content-duplicate`
    # drill selects on and doctor counts, so the `duplicate` count ≡ the drill's row
    # count ≡ doctor's total_items, and the MCP facet is byte-parity with the CLI.
    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)
    capsys.readouterr()

    facet = {
        e["value"]: e["count"]
        for e in mcp_server.list_facets("content-duplicate")["facets"]["content-duplicate"]
    }
    assert facet == {"duplicate": 4, "unique": 2}
    # drill-from-the-count: facet duplicate ≡ the rows --content-duplicate returns
    assert facet["duplicate"] == len(mcp_server.list_scrolls(content_duplicate=True))
    # and ≡ doctor's whole-library content-duplicate item total (get_library_health
    # returns the custody block directly)
    health = mcp_server.get_library_health()["content_duplicates"]
    assert facet["duplicate"] == health["total_items"] == 4

    # MCP facet reads byte-identical to the CLI `facets content-duplicate`
    main(["facets", "content-duplicate"])
    cli_facet = json.loads(capsys.readouterr().out)
    assert mcp_server.list_facets("content-duplicate") == cli_facet


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
            "content-duplicate": [],
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


def test_get_scroll_names_content_duplicate_siblings_at_parity_with_cli(scrolls_home, capsys):
    # H328: the MCP inspect twin carries `content_duplicate_ids` — the *other*
    # held ids byte-identical to this one — and reads byte-for-byte the same as the
    # CLI `show` payload for the same item (the per-item read companion of the
    # whole-library content-duplicate report, H325).
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:a", source="web", url="https://ex.com/a",
        saved_at="2026-06-12T00:00:00+00:00", title="A copy",
        extracted_text="body", raw_text="<raw>body</raw>",
        content_hash="sha256:dup", stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:b", source="web", url="https://ex.com/b",
        saved_at="2026-06-12T01:00:00+00:00", title="A byte-identical copy",
        extracted_text="body", raw_text="<raw>body</raw>",
        content_hash="sha256:dup", stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:solo", source="web", url="https://ex.com/solo",
        saved_at="2026-06-12T02:00:00+00:00", title="The only copy",
        extracted_text="other", raw_text="<raw>other</raw>",
        content_hash="sha256:solo", stage="rendered"))

    assert mcp_server.get_scroll("web:a")["content_duplicate_ids"] == ["web:b"]
    assert mcp_server.get_scroll("web:solo")["content_duplicate_ids"] == []

    # byte-for-byte parity with the CLI `show` payload (one fold, both surfaces)
    capsys.readouterr()
    main(["show", "web:a"])
    cli_ids = json.loads(capsys.readouterr().out)["content_duplicate_ids"]
    assert mcp_server.get_scroll("web:a")["content_duplicate_ids"] == cli_ids


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


# --- H254: get_related_scrolls(fidelity=/drift=) — the custody-filter family twins ---


def _related_custody_mix_mcp():
    """An anchor + three neighbours sharing a concept, spanning the custody axes:
    a `full` neighbour re-checked unchanged (→ verified), a `partial` one drifted,
    a `reference` one never re-checked (→ unverified). The MCP twin of
    `test_related._related_custody_mix`. Library must already exist.
    """
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:anchor", source="web", url="https://ex.com/anchor",
        saved_at="2026-06-12T00:00:00+00:00", title="Anchor", concepts=("ml",),
        raw_text="<raw>", content_hash="sha256:a", stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:full", source="web", url="https://ex.com/full",
        saved_at="2026-06-12T00:00:01+00:00", title="Full", concepts=("ml",),
        raw_text="<raw>", content_hash="sha256:f", stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:partial", source="web", url="https://ex.com/partial",
        saved_at="2026-06-12T00:00:02+00:00", title="Partial", concepts=("ml",),
        extracted_text="body", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:ref", source="web", url="https://ex.com/ref",
        saved_at="2026-06-12T00:00:03+00:00", title="Reference", concepts=("ml",),
        stage="detected"))
    record_events(db, [
        CustodyEvent("web:full", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:f", "sha256:f", None),
        CustodyEvent("web:partial", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:p", "sha256:x", None),
        # web:ref left with no verdict → unverified
    ])
    return db


def test_get_related_scrolls_filters_by_fidelity_tier(scrolls_home):
    # the holdings-axis sieve on the relationship surface — the MCP twin of
    # `scrolls related --fidelity` and the relationship sibling of
    # `list_scrolls(fidelity=)`/`search_scrolls(fidelity=)` (ADR 0097, roadmap H254).
    from scrolls.cli import main

    main(["init"])
    _related_custody_mix_mcp()

    assert [r["id"] for r in mcp_server.get_related_scrolls("web:anchor", fidelity="full")] == [
        "web:full"
    ]
    assert [
        r["id"] for r in mcp_server.get_related_scrolls("web:anchor", fidelity="partial")
    ] == ["web:partial"]
    assert [
        r["id"] for r in mcp_server.get_related_scrolls("web:anchor", fidelity="reference")
    ] == ["web:ref"]
    # row-shows-≡-filter: every kept hit shows exactly the tier it was selected by
    for tier in ("full", "partial", "reference"):
        hits = mcp_server.get_related_scrolls("web:anchor", fidelity=tier)
        assert hits and all(h["fidelity"] == tier for h in hits)


def test_get_related_scrolls_filters_by_drift_posture(scrolls_home):
    # the ledger-claim-axis sieve on the relationship surface — the MCP twin of
    # `scrolls related --drift` (roadmap H254). The mix reads verified/drifted/
    # unverified across its three neighbours.
    from scrolls.cli import main

    main(["init"])
    _related_custody_mix_mcp()

    assert [r["id"] for r in mcp_server.get_related_scrolls("web:anchor", drift="verified")] == [
        "web:full"
    ]
    assert [r["id"] for r in mcp_server.get_related_scrolls("web:anchor", drift="drifted")] == [
        "web:partial"
    ]
    assert [
        r["id"] for r in mcp_server.get_related_scrolls("web:anchor", drift="unverified")
    ] == ["web:ref"]
    # a posture no neighbour holds is an honest empty neighbourhood, never an error
    assert mcp_server.get_related_scrolls("web:anchor", drift="rotted") == []
    for posture in ("verified", "drifted", "unverified"):
        hits = mcp_server.get_related_scrolls("web:anchor", drift=posture)
        assert hits and all(h["drift"] == posture for h in hits)


def test_get_related_scrolls_ands_both_custody_axes(scrolls_home):
    # the two axes AND, the same as the CLI twin: full+verified is web:full alone,
    # full+drifted is empty (no neighbour is both).
    from scrolls.cli import main

    main(["init"])
    _related_custody_mix_mcp()

    assert [
        r["id"]
        for r in mcp_server.get_related_scrolls("web:anchor", fidelity="full", drift="verified")
    ] == ["web:full"]
    assert (
        mcp_server.get_related_scrolls("web:anchor", fidelity="full", drift="drifted") == []
    )


def test_get_related_scrolls_rejects_unknown_custody_vocab(scrolls_home):
    # the same closed vocabulary as the `list_scrolls`/`search_scrolls` twins; a typo
    # raises rather than silently returning an empty neighbourhood.
    import pytest

    from scrolls.cli import main

    main(["init"])
    _related_custody_mix_mcp()
    with pytest.raises(ValueError):
        mcp_server.get_related_scrolls("web:anchor", fidelity="ful")
    with pytest.raises(ValueError):
        mcp_server.get_related_scrolls("web:anchor", drift="drited")


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
    # the custody block tallies the whole `stats.items` scope (roadmap H52) and
    # splits it per source (roadmap H150) — `arxiv` and `x`, one scroll each
    _bare = {
        "tiers": {"full": 0, "partial": 0, "reference": 1},
        "drift": {"verified": 0, "unverified": 1, "drifted": 0, "rotted": 0, "error": 0},
        "coverage": {"verified": 0, "total": 0},
    }
    assert graph["stats"] == {
        "items": 2, "nodes": 2, "edges": 1, "clusters": 1,
        "custody": {
            "tiers": {"full": 0, "partial": 0, "reference": 2},
            "drift": {"verified": 0, "unverified": 2, "drifted": 0, "rotted": 0, "error": 0},
            "by_source": {"arxiv": _bare, "x": _bare},
            # no source carries drift loss → no weakest-source flag (roadmap H164)
            "attention": None,
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
                "by_source": {},  # honest empty per-source map (roadmap H150)
                "attention": None,  # nothing to flag in an empty library (roadmap H164)
            },
        },
    }


def test_get_link_graph_nodes_carry_content_duplicate_ids_at_parity_with_cli(scrolls_home, capsys):
    # roadmap H343: each MCP graph node carries `content_duplicate_ids` (its
    # byte-identical siblings) beside the per-node `fidelity`/`drift`, reading
    # byte-for-byte the same as the CLI `graph` payload (CLI + MCP share
    # `graph.to_payload`) — so an agent walking the link graph over MCP sees a
    # node's redundancy without a second `get_scroll`.
    import json

    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    # a byte-identical pair, both linked to a shared hub so all three are nodes
    insert_item(db, ScrollItem(
        id="web:a", source="web", url="https://ex.com/a",
        saved_at="2026-06-12T00:00:00+00:00", title="A copy",
        extracted_text="body", raw_text="<raw>body</raw>", content_hash="sha256:dup",
        stage="rendered", links=("https://ex.com/hub",)))
    insert_item(db, ScrollItem(
        id="web:b", source="web", url="https://ex.com/b",
        saved_at="2026-06-12T01:00:00+00:00", title="A byte-identical copy",
        extracted_text="body", raw_text="<raw>body</raw>", content_hash="sha256:dup",
        stage="rendered", links=("https://ex.com/hub",)))
    insert_item(db, ScrollItem(
        id="web:hub", source="web", url="https://ex.com/hub",
        saved_at="2026-06-12T02:00:00+00:00", title="Hub",
        extracted_text="other", raw_text="<raw>other</raw>", content_hash="sha256:hub",
        stage="rendered"))

    nodes = {n["id"]: n for n in mcp_server.get_link_graph()["nodes"]}
    assert nodes["web:a"]["content_duplicate_ids"] == ["web:b"]
    assert nodes["web:b"]["content_duplicate_ids"] == ["web:a"]
    assert nodes["web:hub"]["content_duplicate_ids"] == []  # unique content

    # byte-for-byte parity with the CLI `graph` payload (one fold, both surfaces)
    capsys.readouterr()
    assert main(["graph"]) == 0
    cli_nodes = {n["id"]: n for n in json.loads(capsys.readouterr().out)["nodes"]}
    assert {nid: n["content_duplicate_ids"] for nid, n in nodes.items()} == {
        nid: n["content_duplicate_ids"] for nid, n in cli_nodes.items()
    }


def test_get_link_graph_filters_by_content_duplicate(scrolls_home):
    # roadmap H352: `content_duplicate=True` scopes the graph to nodes the library
    # holds a byte-identical copy of under another id, with edges induced among
    # them — the MCP twin of `graph --content-duplicate`. A duplicate pair (linked
    # to each other) plus a unique hub: the filter keeps the pair, drops the hub,
    # and induces the a → b edge.
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:a", source="web", url="https://ex.com/a",
        saved_at="2026-06-12T00:00:00+00:00", title="A copy",
        extracted_text="body", raw_text="<raw>body</raw>", content_hash="sha256:dup",
        stage="rendered", links=("https://ex.com/b", "https://ex.com/hub")))
    insert_item(db, ScrollItem(
        id="web:b", source="web", url="https://ex.com/b",
        saved_at="2026-06-12T01:00:00+00:00", title="A byte-identical copy",
        extracted_text="body", raw_text="<raw>body</raw>", content_hash="sha256:dup",
        stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:hub", source="web", url="https://ex.com/hub",
        saved_at="2026-06-12T02:00:00+00:00", title="Hub",
        extracted_text="other", raw_text="<raw>other</raw>", content_hash="sha256:hub",
        stage="rendered"))

    scoped = mcp_server.get_link_graph(content_duplicate=True)
    assert [n["id"] for n in scoped["nodes"]] == ["web:a", "web:b"]  # hub dropped
    # a → b induced (both kept); a → hub dropped (hub removed) — well-formed
    assert [(e["from"], e["to"]) for e in scoped["edges"]] == [("web:a", "web:b")]
    assert scoped["stats"]["items"] == 2  # stats describe the scoped set


def test_get_link_graph_content_duplicate_is_cli_mcp_parity(scrolls_home, capsys):
    # the MCP filter result is byte-for-byte the CLI `graph --content-duplicate`
    # payload (CLI + MCP share `content_duplicate_subgraph` + `graph.to_payload`)
    import json

    from scrolls.cli import main

    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)

    mcp_scoped = mcp_server.get_link_graph(include_isolated=True, content_duplicate=True)
    capsys.readouterr()
    assert main(["graph", "--all", "--content-duplicate"]) == 0
    cli_scoped = json.loads(capsys.readouterr().out)
    assert mcp_scoped == cli_scoped
    # the two byte-identical groups in the mix → four content-duplicate nodes
    assert {n["id"] for n in mcp_scoped["nodes"]} == {"web:a", "arxiv:1", "web:p", "web:q"}


def test_get_link_graph_custody_carries_the_weakest_source_flag(scrolls_home):
    # roadmap H164: the weakest-source `attention` flag rides MCP `get_link_graph`
    # for free (CLI + MCP share `graph.to_payload`), and names the same source the
    # CLI `status` flag does — so an agent reading the link graph over MCP sees which
    # source most needs action without dropping to the shell.
    import json

    from scrolls.cli import main
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    # web carries the only actionable loss (web:full drifted); arxiv is clean
    insert_item(db, ScrollItem(
        id="web:full", source="web", url="https://example.org/a",
        saved_at="2026-06-12T00:00:00+00:00", title="A", stage="rendered",
        raw_text="<raw>a</raw>", extracted_text="a", content_hash="sha256:wf"))
    insert_item(db, ScrollItem(
        id="arxiv:1", source="arxiv", url="https://arxiv.org/abs/1",
        saved_at="2026-06-12T00:00:00+00:00", title="P", stage="rendered",
        raw_text="<raw>p</raw>", extracted_text="p", content_hash="sha256:af"))
    record_events(db, [CustodyEvent(
        "web:full", "2026-06-14T00:00:00+00:00", "drifted", "sha256:wf", "sha256:new", None)])

    attention = mcp_server.get_link_graph()["stats"]["custody"]["attention"]
    assert attention is not None
    assert attention["source"] == "web"
    assert attention["command"] == "scrolls verify --source web"

    # agrees with the CLI `status` flag — the two surfaces read one weak source
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert main(["status"]) == 0
    assert json.loads(buf.getvalue())["attention"] == attention


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


def test_node_shape_carries_last_checked_across_both_mcp_surfaces(scrolls_home):
    # the time axis (last_checked) rides the node shape on both MCP node-shape
    # twins beside `drift` and agrees with the `list_scrolls` row (H86)
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
        CustodyEvent("arxiv:2605.27848", "2026-06-14T00:00:00+00:00",
                     "drifted", "h", "x", None),
        # x:1111 left unverified
    ])

    ts = "2026-06-14T00:00:00+00:00"
    graph_nodes = {n["id"]: n for n in mcp_server.get_link_graph()["nodes"]}
    assert graph_nodes["arxiv:2605.27848"]["last_checked"] == ts
    assert graph_nodes["x:1111"]["last_checked"] is None  # never checked → null

    related = {r["id"]: r for r in mcp_server.get_related_scrolls("x:1111")}
    assert related["arxiv:2605.27848"]["last_checked"] == ts

    listed = {r["id"]: r for r in mcp_server.list_scrolls()}
    # all three node/browse surfaces agree on the same item's last_checked
    assert (
        related["arxiv:2605.27848"]["last_checked"]
        == graph_nodes["arxiv:2605.27848"]["last_checked"]
        == listed["arxiv:2605.27848"]["last_checked"]
        == ts
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


# The zeroed works stats.custody shape (no reported representations, H100).
_ZERO_WORKS_CUSTODY = {
    "tiers": {"full": 0, "partial": 0, "reference": 0},
    "drift": {p: 0 for p in
              ("verified", "unverified", "drifted", "rotted", "error")},
    "by_source": {},  # no reps → the empty per-source split (roadmap H155)
    "attention": None,  # no sources → the honest-null weakest-source flag (roadmap H174)
    # no works → the at-risk-works summary is the honest zeroed fold (roadmap H266)
    "at_risk": {"total": 0, "at_risk": 0, "most_at_risk": None},
}


def _works_core_stats(stats):
    """The works `items`/`works` pair, dropping the H100 `custody` member.

    The works stats block now carries a `custody` tally over the reported works'
    representations (roadmap H100); these structural-shape tests pin the counts,
    so they drop `custody` and let the dedicated H100 test own its value.
    """
    return {key: value for key, value in stats.items() if key != "custody"}


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
    assert _works_core_stats(payload["stats"]) == {"items": 2, "works": 1}
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
        # H87: the time axis travels too, at parity with the list row
        assert reps[item_id]["last_checked"] == rows[item_id]["last_checked"]
    assert reps["arxiv:1706.03762"]["drift"] == "verified"
    assert reps["arxiv:1706.03762"]["last_checked"] == "2026-06-14T00:00:00+00:00"
    assert reps["crossref:10.5555/3295222"]["last_checked"] is None


def test_get_works_empty_library(scrolls_home):
    assert mcp_server.get_works() == {
        "scope": {"min_representations": 2},
        "works": [],
        "stats": {"items": 0, "works": 0, "custody": _ZERO_WORKS_CUSTODY},
    }


def test_get_works_stats_custody_member_agrees_with_the_cli(scrolls_home):
    # H100: the MCP works twin carries the same stats.custody member the CLI
    # does — both route through `works.to_payload`, so the tally is identical.
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
        status="drifted", prior_hash="sha256:a", observed_hash="sha256:b")])

    custody = mcp_server.get_works()["stats"]["custody"]
    # one full+drifted preprint, one reference+unverified published record
    assert custody["tiers"] == {"full": 1, "partial": 0, "reference": 1}
    assert custody["drift"] == {
        "verified": 0, "unverified": 1, "drifted": 1, "rotted": 0, "error": 0}
    # the tally equals what the twin's own representation entries carry
    from scrolls.custody import tally_custody_by_source, weakest_source
    reps = [r for w in mcp_server.get_works()["works"][0:] for r in w["representations"]]
    expected = {"tiers": {"full": 0, "partial": 0, "reference": 0},
                "drift": {p: 0 for p in
                          ("verified", "unverified", "drifted", "rotted", "error")},
                "by_source": {}}
    for rep in reps:
        expected["tiers"][rep["fidelity"]] += 1
        expected["drift"][rep["drift"]] += 1
    # the per-source split (roadmap H155) rides the MCP twin too — both route through
    # `works.to_payload` — split over the same reps (this seed spans arxiv + crossref)
    expected["by_source"] = tally_custody_by_source(
        (rep["source"], rep["fidelity"], rep["drift"]) for rep in reps)
    # the weakest-source flag (roadmap H174) rides the MCP twin too (shared
    # `to_payload`): the lean flag (no fabricated coverage) names the drifted arxiv
    expected["attention"] = weakest_source(expected["by_source"], include_coverage=False)
    # the at-risk-works summary (roadmap H266) rides the MCP twin too (shared
    # `to_payload`): the one work is at risk (its full copy drifted, no safely-held rep)
    from scrolls.custody import latest_events
    from scrolls.items import list_items
    from scrolls.works import at_risk_signal, works_over

    expected["at_risk"] = at_risk_signal(works_over(list_items(db)), latest_events(db))
    assert custody == expected
    assert expected["attention"]["source"] == "arxiv"
    assert expected["at_risk"]["at_risk"] == 1


def test_get_works_carries_the_aggregate_custody_block(scrolls_home):
    # H261: the per-work `custody` block rides the MCP twin too — both route through
    # `works.to_payload` — and equals the shared `work_custody` fold by construction,
    # so the consolidation verdict reads identically on CLI and MCP.
    from scrolls.cli import main
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item
    from scrolls.works import work_custody, works_over

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

    work = mcp_server.get_works()["works"][0]
    assert work["custody"] == {
        "best_fidelity": "full",
        "safest_drift": "verified",
        "safely_held": True,  # the full preprint is held and verified unmoved
    }
    # the MCP block equals the shared helper over the same clustering + ledger
    from scrolls.items import list_items
    from scrolls.custody import latest_events

    items = list_items(db)
    (clustered,) = works_over(items)
    assert work["custody"] == work_custody(
        clustered.representations, latest_events(db)
    )


def test_get_works_flags_a_byte_identical_rep_pair_at_parity_with_cli(
    scrolls_home, capsys
):
    # H329: the per-work `content_duplicate` flag rides the MCP twin too — both route
    # through `works.to_payload` — so the consolidation-surface redundancy reads
    # identically on CLI and MCP. Two reps of one work holding the SAME bytes flag
    # true; a work whose reps differ flags false.
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    # work X: a preprint mirrored byte-identically into its DOI capture (same hash)
    insert_item(db, ScrollItem(
        id="arxiv:x", source="arxiv", source_id="x",
        url="https://arxiv.org/abs/x", saved_at="2026-06-12T00:00:00+00:00",
        title="X", links=("https://doi.org/10.1000/x",), stage="rendered",
        raw_text="the shared body", content_hash="sha256:same",
    ))
    insert_item(db, ScrollItem(
        id="crossref:10.1000/x", source="crossref", source_id="10.1000/x",
        url="https://doi.org/10.1000/x", saved_at="2026-06-12T00:00:00+00:00",
        title="X", stage="rendered",
        raw_text="the shared body", content_hash="sha256:same",
    ))
    # work Y: two reps holding distinct bytes (the normal preprint-vs-record case)
    insert_item(db, ScrollItem(
        id="arxiv:y", source="arxiv", source_id="y",
        url="https://arxiv.org/abs/y", saved_at="2026-06-12T00:00:00+00:00",
        title="Y", links=("https://doi.org/10.1000/y",), stage="rendered",
        raw_text="the preprint body", content_hash="sha256:ya",
    ))
    insert_item(db, ScrollItem(
        id="crossref:10.1000/y", source="crossref", source_id="10.1000/y",
        url="https://doi.org/10.1000/y", saved_at="2026-06-12T00:00:00+00:00",
        title="Y", stage="rendered",
        raw_text="the published body", content_hash="sha256:yb",
    ))

    works = {w["doi"]: w for w in mcp_server.get_works()["works"]}
    assert works["10.1000/x"]["content_duplicate"] is True
    assert works["10.1000/y"]["content_duplicate"] is False
    # CLI parity: the same flag, same source, both through `works.to_payload`
    capsys.readouterr()  # drop the `init` chatter before the JSON capture
    assert main(["works"]) == 0
    cli_works = {w["doi"]: w for w in json.loads(capsys.readouterr().out)["works"]}
    assert cli_works["10.1000/x"]["content_duplicate"] is True
    assert cli_works["10.1000/y"]["content_duplicate"] is False


def _seed_at_risk_works(db):
    """Two at-risk works for the H266 stats summary: X (full+drifted) + Z (all ref).

    Z (no content held anywhere) is the lowest-ceiling work; X holds a full copy that
    has merely drifted. Y (safely held) is intentionally absent so `at_risk == total`.
    """
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    insert_item(db, ScrollItem(
        id="arxiv:x", source="arxiv", source_id="x", url="https://arxiv.org/abs/x",
        saved_at="2026-06-12T00:00:00+00:00", title="X",
        links=("https://doi.org/10.1000/x",), stage="rendered",
        raw_text="body", content_hash="sha256:a"))
    insert_item(db, ScrollItem(
        id="crossref:cx", source="crossref", source_id="10.1000/x",
        url="https://doi.org/10.1000/x", saved_at="2026-06-12T00:00:00+00:00",
        title="X", stage="rendered"))
    insert_item(db, ScrollItem(
        id="arxiv:z", source="arxiv", source_id="z", url="https://arxiv.org/abs/z",
        saved_at="2026-06-12T00:00:00+00:00", title="Z",
        links=("https://doi.org/10.3000/z",), stage="rendered"))
    insert_item(db, ScrollItem(
        id="crossref:cz", source="crossref", source_id="10.3000/z",
        url="https://doi.org/10.3000/z", saved_at="2026-06-12T00:00:00+00:00",
        title="Z", stage="rendered"))
    record_events(db, [CustodyEvent(
        item_id="arxiv:x", checked_at="2026-06-14T00:00:00+00:00",
        status="drifted", prior_hash="sha256:a", observed_hash="sha256:b")])


def test_get_works_stats_custody_at_risk_rides_the_mcp_twin(scrolls_home):
    # H266: the MCP works twin carries the same `stats.custody.at_risk` summary the
    # CLI does — both route through `works.to_payload`, so the fold is identical.
    from scrolls.cli import main

    main(["init"])
    _seed_at_risk_works(get_paths().db_path)
    at_risk = mcp_server.get_works()["stats"]["custody"]["at_risk"]
    # both X (full+drifted) and Z (all-reference) are at risk; Z the lowest ceiling
    assert at_risk["total"] == 2
    assert at_risk["at_risk"] == 2
    assert at_risk["most_at_risk"]["doi"] == "10.3000/z"
    assert at_risk["most_at_risk"]["custody"]["best_fidelity"] == "reference"


def test_get_works_stats_custody_at_risk_converges_with_get_library_health(scrolls_home):
    # cross-surface invariant: the unscoped MCP `get_works` payload's
    # `stats.custody.at_risk` equals `get_library_health()`'s `works` block (minus its
    # `status`) — both fold the shared `at_risk_signal` over the same default 2+
    # clustering and ledger, the MCP twin of the CLI works↔doctor convergence.
    from scrolls.cli import main

    main(["init"])
    _seed_at_risk_works(get_paths().db_path)
    at_risk = mcp_server.get_works()["stats"]["custody"]["at_risk"]
    works_block = mcp_server.get_library_health()["works"]
    assert at_risk == {k: v for k, v in works_block.items() if k != "status"}


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
    # items = whole library; works/custody count only the reported work's reps
    assert _works_core_stats(payload["stats"]) == {"items": 3, "works": 1}
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


def _works_custody_mix_mcp():
    """Three 2-rep works across a custody spread — the MCP twin of
    `test_works._two_work_custody_mix`. Sorted by DOI: X, Y, Z.
    - Work X (10.1000/x): a *full* arxiv preprint that has **drifted** + a bare
      *reference* crossref record (unverified).
    - Work Y (10.2000/y): a *full* biorxiv preprint **verified** (unchanged) + a
      *partial* pubmed record (unverified).
    - Work Z (10.3000/z): two *reference* records, both unverified.
    Library must already exist.
    """
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    db = get_paths().db_path

    def _item(item_id, source, doi, **fields):
        return ScrollItem(
            id=item_id, source=source, source_id=item_id.split(":", 1)[1],
            url=f"https://ex.com/{item_id}", saved_at="2026-06-12T00:00:00+00:00",
            title=item_id, links=(f"https://doi.org/{doi}",), stage="rendered",
            **fields)

    insert_item(db, _item("arxiv:x", "arxiv", "10.1000/x",
                          raw_text="body", content_hash="sha256:x"))  # full
    insert_item(db, _item("crossref:cx", "crossref", "10.1000/x"))  # reference
    insert_item(db, _item("biorxiv:y", "biorxiv", "10.2000/y",
                          raw_text="body", content_hash="sha256:y"))  # full
    insert_item(db, _item("pubmed:y", "pubmed", "10.2000/y", summary="s"))  # partial
    insert_item(db, _item("arxiv:z", "arxiv", "10.3000/z"))  # reference
    insert_item(db, _item("crossref:cz", "crossref", "10.3000/z"))  # reference
    record_events(db, [
        CustodyEvent("arxiv:x", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:x", "sha256:moved", None),
        CustodyEvent("biorxiv:y", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:y", "sha256:y", None),
    ])
    return db


def _content_dup_works_mix_mcp():
    """Works spread across the content-identity axis — the MCP twin of
    `test_works._content_dup_work_mix` (roadmap H344). works_over order (-reps, doi):
    - Work B (10.2000/b, 3 reps): two *full* reps holding the SAME bytes (sha256:dupB)
      + a *reference* rep → content_duplicate, and it holds a reference form.
    - Work A (10.1000/a, 2 reps): two *full* reps holding the SAME bytes (sha256:dupA)
      → content_duplicate, both full.
    - Work C (10.3000/c, 2 reps): two *full* reps holding DIFFERENT bytes → not a dup.
    Library must already exist.
    """
    from scrolls.items import ScrollItem, insert_item

    db = get_paths().db_path

    def _item(item_id, source, doi, content_hash):
        return ScrollItem(
            id=item_id, source=source, source_id=item_id.split(":", 1)[1],
            url=f"https://ex.com/{item_id}", saved_at="2026-06-12T00:00:00+00:00",
            title=item_id, links=(f"https://doi.org/{doi}",), stage="rendered",
            raw_text="body" if content_hash else None, content_hash=content_hash)

    insert_item(db, _item("arxiv:a", "arxiv", "10.1000/a", "sha256:dupA"))
    insert_item(db, _item("crossref:ca", "crossref", "10.1000/a", "sha256:dupA"))
    insert_item(db, _item("arxiv:b", "arxiv", "10.2000/b", "sha256:dupB"))
    insert_item(db, _item("biorxiv:b", "biorxiv", "10.2000/b", "sha256:dupB"))
    insert_item(db, _item("crossref:cb", "crossref", "10.2000/b", None))  # reference
    insert_item(db, _item("arxiv:c", "arxiv", "10.3000/c", "sha256:c1"))
    insert_item(db, _item("crossref:cc", "crossref", "10.3000/c", "sha256:c2"))
    return db


def test_get_works_filters_by_fidelity_tier(scrolls_home):
    # the holdings axis on the consolidation surface — the MCP twin of
    # `scrolls works --fidelity` (roadmap H262), lifting `list_scrolls(fidelity=)`
    # to the work cluster.
    from scrolls.cli import main

    main(["init"])
    _works_custody_mix_mcp()

    assert [w["doi"] for w in mcp_server.get_works(fidelity="full")["works"]] == [
        "10.1000/x", "10.2000/y"]
    assert [w["doi"] for w in mcp_server.get_works(fidelity="reference")["works"]] == [
        "10.1000/x", "10.3000/z"]
    # the filter rides the scope echo (G2), pruned to the lean shape when unset
    assert mcp_server.get_works(fidelity="full")["scope"] == {
        "min_representations": 2, "fidelity": "full"}


def test_get_works_filters_by_drift_posture(scrolls_home):
    # the ledger-claim axis on the consolidation surface — the MCP twin of
    # `scrolls works --drift` (roadmap H262).
    from scrolls.cli import main

    main(["init"])
    _works_custody_mix_mcp()

    drifted = mcp_server.get_works(drift="drifted")
    assert [w["doi"] for w in drifted["works"]] == ["10.1000/x"]
    # the whole work travels (contains semantics): the drifted preprint + its sibling
    assert [r["id"] for r in drifted["works"][0]["representations"]] == [
        "arxiv:x", "crossref:cx"]
    # a posture no representation holds → an honest empty result, never an error
    assert mcp_server.get_works(drift="rotted")["works"] == []


def test_get_works_ands_both_custody_axes(scrolls_home):
    # the two axes AND on the SAME representation, the same as the CLI twin: full+
    # verified is work Y; reference+drifted is empty (X holds both values, but no
    # single rep is both — the ∃-lift of `get_related_scrolls`'s "no neighbour is both").
    from scrolls.cli import main

    main(["init"])
    _works_custody_mix_mcp()

    assert [
        w["doi"] for w in mcp_server.get_works(fidelity="full", drift="verified")["works"]
    ] == ["10.2000/y"]
    assert mcp_server.get_works(fidelity="reference", drift="drifted")["works"] == []


def test_get_works_rejects_unknown_custody_vocab(scrolls_home):
    # the same closed vocabulary as the `get_related_scrolls` twin; a typo raises
    # rather than silently returning an empty result (no argparse `choices=` over MCP).
    from scrolls.cli import main

    main(["init"])
    _works_custody_mix_mcp()

    with pytest.raises(ValueError, match="unknown fidelity tier"):
        mcp_server.get_works(fidelity="gold")
    with pytest.raises(ValueError, match="unknown drift posture"):
        mcp_server.get_works(drift="moved")


def test_get_works_filter_matches_the_cli_twin(scrolls_home, capsys):
    # CLI↔MCP parity: the same custody-scoped works payload on both surfaces
    # (both route through `filter_works` + `works.to_payload`).
    main(["init"])
    _works_custody_mix_mcp()
    capsys.readouterr()  # drain the `init` output so only the `works` JSON remains

    assert main(["works", "--fidelity", "full", "--drift", "verified"]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert mcp_server.get_works(fidelity="full", drift="verified") == cli_payload


def test_get_works_at_risk_browses_the_unsafely_held_works(scrolls_home):
    # the at-risk browse predicate on the consolidation surface — the MCP twin of
    # `scrolls works --at-risk` (roadmap H265), the `get_library_health` at-risk-works
    # alarm as a browse predicate.
    from scrolls.cli import main

    main(["init"])
    _works_custody_mix_mcp()

    payload = mcp_server.get_works(at_risk=True)
    # X (full+drifted) and Z (all-reference) are at risk; Y (full+verified) is safe
    assert [w["doi"] for w in payload["works"]] == ["10.1000/x", "10.3000/z"]
    # the whole work travels (contains semantics): X's drifted full preprint + sibling
    assert [r["id"] for r in payload["works"][0]["representations"]] == [
        "arxiv:x", "crossref:cx"]
    # the boolean predicate rides the scope echo, present only when set (G2)
    assert payload["scope"] == {"min_representations": 2, "at_risk": True}
    # unset → pruned, like the CLI twin
    assert "at_risk" not in mcp_server.get_works()["scope"]


def test_get_works_at_risk_ands_with_the_custody_filters(scrolls_home):
    # `at_risk` ANDs with the per-rep contains-filters, the same as the CLI twin:
    # at-risk AND holds a full rep → X only (the recapture candidate); Z is at risk
    # but all-reference, so it drops under fidelity="full".
    from scrolls.cli import main

    main(["init"])
    _works_custody_mix_mcp()

    assert [
        w["doi"] for w in mcp_server.get_works(at_risk=True, fidelity="full")["works"]
    ] == ["10.1000/x"]
    # at-risk AND verified → empty: the only verified rep is Y's, and Y is safely held
    assert mcp_server.get_works(at_risk=True, drift="verified")["works"] == []


def test_get_works_at_risk_matches_the_cli_twin(scrolls_home, capsys):
    # CLI↔MCP parity: the same at-risk-scoped works payload on both surfaces
    # (both route through `filter_works(at_risk=True)` + `works.to_payload`).
    main(["init"])
    _works_custody_mix_mcp()
    capsys.readouterr()  # drain the `init` output so only the `works` JSON remains

    assert main(["works", "--at-risk", "--fidelity", "full"]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert mcp_server.get_works(at_risk=True, fidelity="full") == cli_payload


def test_get_works_content_duplicate_browses_the_byte_identical_works(scrolls_home):
    # the content-identity browse predicate on the consolidation surface — the MCP twin
    # of `scrolls works --content-duplicate` (roadmap H344), the per-work
    # content_duplicate flag (H329) as a browse predicate.
    from scrolls.cli import main

    main(["init"])
    _content_dup_works_mix_mcp()

    payload = mcp_server.get_works(content_duplicate=True)
    # B (full pair shares bytes) and A (full pair shares bytes) are kept; C (distinct) drops
    assert [w["doi"] for w in payload["works"]] == ["10.2000/b", "10.1000/a"]
    # each kept work's content_duplicate flag reads true (the drill-from-the-flag tie)
    assert all(w["content_duplicate"] for w in payload["works"])
    # the boolean predicate rides the scope echo, present only when set (G2)
    assert payload["scope"] == {"min_representations": 2, "content_duplicate": True}
    # unset → pruned, like the CLI twin
    assert "content_duplicate" not in mcp_server.get_works()["scope"]


def test_get_works_content_duplicate_ands_with_the_custody_filters(scrolls_home):
    # `content_duplicate` ANDs with the per-rep contains-filters, the same as the CLI
    # twin: among the two duplicate works, only B holds a reference rep.
    from scrolls.cli import main

    main(["init"])
    _content_dup_works_mix_mcp()

    assert [
        w["doi"]
        for w in mcp_server.get_works(content_duplicate=True, fidelity="reference")["works"]
    ] == ["10.2000/b"]
    assert [
        w["doi"]
        for w in mcp_server.get_works(content_duplicate=True, fidelity="full")["works"]
    ] == ["10.2000/b", "10.1000/a"]


def test_get_works_content_duplicate_matches_the_cli_twin(scrolls_home, capsys):
    # CLI↔MCP parity: the same content-duplicate-scoped works payload on both surfaces
    # (both route through `filter_works(content_duplicate=True)` + `works.to_payload`).
    main(["init"])
    _content_dup_works_mix_mcp()
    capsys.readouterr()  # drain the `init` output so only the `works` JSON remains

    assert main(["works", "--content-duplicate", "--fidelity", "reference"]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert mcp_server.get_works(content_duplicate=True, fidelity="reference") == cli_payload


def test_mcp_browse_twins_are_array_only_per_source_custody_rides_object_twins(scrolls_home):
    # roadmap H163: the CLI `search`/`list --stats` envelope carries a per-source
    # `stats.custody.by_source` split (H155), but the MCP `search_scrolls`/
    # `list_scrolls`/`get_related_scrolls` twins are *array-only by design* — they
    # return the bare hit list, no `--stats` envelope (custody-vision §6 surface
    # parity; the bare array is the G1-locked browse contract, docs/cli.md G2). So
    # the per-source custody *scope* an agent reads over MCP rides the
    # object-returning twins instead — `get_link_graph`/`get_works`
    # `stats.custody.by_source` (H150/H100/H155) — and the dedicated whole-library
    # audit `get_library_health` `by_source` (H161). This pins the asymmetry so a
    # later run does not silently grow a divergent MCP browse-stats envelope, and
    # proves the per-source data is not lost over MCP, only relocated.
    from scrolls.cli import main
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    # Two sources that differ on every custody axis (non-vacuous): web holds a
    # full body that has *drifted*; arxiv holds a full body left *unverified*.
    # Shared concept so they relate; web links arxiv so the graph connects them.
    insert_item(db, ScrollItem(
        id="web:full", source="web", url="https://example.org/a",
        saved_at="2026-06-12T00:00:00+00:00", title="Attention survey",
        raw_text="<raw>attention</raw>", extracted_text="attention is all you need",
        content_hash="sha256:wf", concepts=("attention",), stage="rendered",
        links=("https://arxiv.org/abs/1706.03762",)))
    insert_item(db, ScrollItem(
        id="arxiv:1706.03762", source="arxiv", url="https://arxiv.org/abs/1706.03762",
        saved_at="2026-06-12T00:00:00+00:00", title="Attention Is All You Need",
        raw_text="<raw>attention</raw>", extracted_text="attention transformer model",
        content_hash="sha256:af", concepts=("attention",), stage="rendered"))
    record_events(db, [CustodyEvent(
        "web:full", "2026-06-14T00:00:00+00:00", "drifted",
        "sha256:wf", "sha256:new", None)])

    # The three browse twins are array-only: a bare list of per-item hit dicts,
    # never an envelope — there is no scope-level `stats`/`stats.custody.by_source`
    # to read off them over MCP.
    for hits in (
        mcp_server.search_scrolls("attention"),
        mcp_server.list_scrolls(),
        mcp_server.get_related_scrolls("web:full"),
    ):
        assert isinstance(hits, list)
        assert hits  # non-vacuous: every twin returns its result set
        assert all(isinstance(hit, dict) for hit in hits)
        # per-item custody axes ride each hit (H58), but never a scope aggregate
        assert all("stats" not in hit for hit in hits)
    # search/list span both sources, so the *absence* of a per-source envelope on
    # a genuinely multi-source result set is meaningful, not vacuous; related is
    # anchored on web:full and so reports its arxiv neighbour (anchor excluded).
    assert {h["source"] for h in mcp_server.search_scrolls("attention")} == {"arxiv", "web"}
    assert {h["source"] for h in mcp_server.list_scrolls()} == {"arxiv", "web"}
    assert {h["source"] for h in mcp_server.get_related_scrolls("web:full")} == {"arxiv"}

    # The per-source split *is* reachable over MCP — through the object-returning
    # stats-bearing twin `get_link_graph` (H150) — and it genuinely distinguishes
    # the two sources (web drifted, arxiv unverified), so the asymmetry costs the
    # agent nothing: it reads the per-source picture off the object twin instead.
    graph_by_source = mcp_server.get_link_graph()["stats"]["custody"]["by_source"]
    assert set(graph_by_source) == {"arxiv", "web"}
    assert graph_by_source["web"]["drift"]["drifted"] == 1
    assert graph_by_source["arxiv"]["drift"]["unverified"] == 1

    # ...and off the dedicated whole-library custody audit (H161), the scope-level
    # custody read over MCP — the same per-source key set.
    health_by_source = mcp_server.get_library_health()["by_source"]
    assert set(health_by_source) == {"arxiv", "web"}


# --- the MCP read-surface shape contract, pinned once (roadmap H186) ----------
#
# H163 pinned that the *browse* twins are array-only and that the per-source
# custody split rides the object twins; H180 pinned that `get_library_health`
# keeps the *nested* `run_doctor` audit block. Those two decisions lived apart.
# This is the "pin it once" capstone (the H157/H50 move): over ONE shared
# multi-source seed it records, in one obvious place, the whole MCP read-surface
# shape — the three shape classes a future tool addition has a single contract to
# satisfy. The decision-grade prose home is the "MCP read-surface shape contract"
# subsection of docs/architecture.md; this test is its enforcement.
#
#   class A — bare-array browse twins (no scope envelope):
#       search_scrolls / list_scrolls / get_related_scrolls  → list[dict]
#       Per-item custody (fidelity/drift) rides each hit; never a scope aggregate.
#   class B — object twins carrying stats.custody.by_source (the structural /
#       consolidation surfaces): get_link_graph / get_works  → {..., stats:{custody:
#       {by_source}}}. The per-source scope an agent reads over MCP rides here.
#   class C — the nested whole-library audit twin: get_library_health  → exactly
#       run_doctor's custody block (NOT a stats-wrapped envelope) — carries the
#       nested enrichment.by_source / summaries.by_source / by_source / attention /
#       headline.

# the MCP read tools by shape class — the contract's four groups, named once.
# A/B/C are the JSON scope-bearing twins (H186); D is the Markdown-string twins
# (H194) — the artifact-emitting reads that carry custody honesty *inside* the
# rendered text rather than in a JSON envelope (ADR 0077, "the output is the
# thing"). get_library_health (class C) is named inline, not a tuple of one.
_ARRAY_TWINS = ("search_scrolls", "list_scrolls", "get_related_scrolls")
_STATS_OBJECT_TWINS = ("get_link_graph", "get_works")
_STRING_TWINS = ("get_context_bundle", "get_concept_page", "get_tag_page")


def _seed_surface_shape_fixture(db):
    """One multi-source scope that makes all three shape classes non-vacuous.

    A genuine *same-work* pair across two sources — an arxiv preprint and its
    published crossref record, bound by the shared DOI `10.1234/attn` (the arxiv
    item via a `doi.org` link, the crossref item via its DOI `source_id`). So:

    * the pair spans two sources (arxiv, crossref) → every per-source `by_source`
      map is a genuine two-source split, not a singleton;
    * the arxiv link resolves to the crossref item → the link graph connects them
      and `get_related_scrolls(arxiv)` reports the crossref neighbour;
    * the shared DOI clusters them into one 2-representation work →
      `get_works`'s representation-scoped `stats.custody.by_source` is non-empty;
    * the two carry distinct custody (arxiv *drifted*, crossref left
      *unverified*) → the audit twin's drift posture is non-trivial;
    * both titles/bodies carry "attention" → `search_scrolls("attention")` spans
      both sources, so the *absence* of a scope envelope on the array twins is a
      meaningful pin over a genuinely multi-source result set.
    """
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    insert_item(db, ScrollItem(
        id="arxiv:1706", source="arxiv", url="https://arxiv.org/abs/1706",
        saved_at="2026-06-12T00:00:00+00:00", title="Attention Is All You Need",
        raw_text="<r>attention</r>", extracted_text="attention transformer model",
        content_hash="sha256:af", stage="rendered",
        links=("https://doi.org/10.1234/attn",)))
    insert_item(db, ScrollItem(
        id="crossref:10.1234/attn", source="crossref",
        url="https://doi.org/10.1234/attn",
        canonical_url="https://doi.org/10.1234/attn", source_id="10.1234/attn",
        saved_at="2026-06-12T00:00:00+00:00", title="Attention, published",
        raw_text="<r>attention</r>", extracted_text="attention published article",
        content_hash="sha256:cf", stage="rendered"))
    record_events(db, [CustodyEvent(
        "arxiv:1706", "2026-06-14T00:00:00+00:00", "drifted",
        "sha256:af", "sha256:new", None)])


def test_mcp_read_surface_shape_contract(scrolls_home):
    # roadmap H186: the single decision-grade pin of the whole MCP read-surface
    # shape — array twins, stats-object twins, and the nested audit twin — over
    # one shared multi-source seed. Folds the H163 (array-only browse) and H180
    # (nested audit block) decisions into one contract. See the
    # "MCP read-surface shape contract" subsection of docs/architecture.md.
    from scrolls.doctor import run_doctor

    main(["init"])
    db = get_paths().db_path
    _seed_surface_shape_fixture(db)

    sources = {"arxiv", "crossref"}  # the non-vacuous two-source universe

    # class A — bare-array browse twins: a list of per-item hit dicts, never an
    # envelope. No scope-level `stats` anywhere on the result or its hits, so an
    # agent cannot read a scope aggregate (e.g. by_source) off a browse twin.
    array_results = {
        "search_scrolls": mcp_server.search_scrolls("attention"),
        "list_scrolls": mcp_server.list_scrolls(),
        "get_related_scrolls": mcp_server.get_related_scrolls("arxiv:1706"),
    }
    assert set(array_results) == set(_ARRAY_TWINS)  # every array twin is covered
    for name, hits in array_results.items():
        assert isinstance(hits, list), f"{name} must return a bare array"
        assert hits, f"{name} result is vacuous"  # non-vacuous
        assert all(isinstance(hit, dict) for hit in hits), f"{name} hits are dicts"
        # per-item custody rides each hit, but never a scope-level envelope
        assert all("stats" not in hit for hit in hits), f"{name} hit grew a stats envelope"
        assert all("fidelity" in hit and "drift" in hit for hit in hits), \
            f"{name} hit dropped its per-item custody axes"
    # the array twins genuinely span both sources — the absence of an envelope is
    # meaningful over a multi-source set (related is anchored, so it reports the
    # cross-source neighbour, anchor excluded)
    assert {h["source"] for h in array_results["search_scrolls"]} == sources
    assert {h["source"] for h in array_results["list_scrolls"]} == sources
    assert {h["source"] for h in array_results["get_related_scrolls"]} == {"crossref"}

    # class B — object twins carrying stats.custody.by_source: the per-source
    # custody scope an agent reads over MCP rides HERE (not the array twins). The
    # split is a genuine two-source map and sums to the whole stats.custody tally.
    object_results = {
        "get_link_graph": mcp_server.get_link_graph(),
        "get_works": mcp_server.get_works(),
    }
    assert set(object_results) == set(_STATS_OBJECT_TWINS)
    for name, payload in object_results.items():
        assert isinstance(payload, dict), f"{name} must return an object"
        by_source = payload["stats"]["custody"]["by_source"]
        assert set(by_source) == sources, f"{name} by_source is not the two-source split"

    # class C — the nested whole-library audit twin: get_library_health IS
    # run_doctor's custody block (plus status's two distilled members), NOT a
    # stats-wrapped envelope — so it carries the *nested* re-derivability blocks
    # (enrichment.by_source / summaries.by_source) the object twins' lean
    # stats.custody does not. This is the deliberate asymmetry H180 records.
    health = mcp_server.get_library_health()
    custody = run_doctor(get_paths())["custody"]
    assert isinstance(health, dict)
    assert "stats" not in health  # the audit twin is the block itself, not wrapped
    for key in custody:  # every custody-block key carried verbatim
        assert health[key] == custody[key], f"get_library_health dropped/changed {key}"
    assert set(health["by_source"]) == sources
    # the nested re-derivability blocks the lean stats.custody by_source omits
    assert "by_source" in health["enrichment"]
    assert "by_source" in health["summaries"]
    # the two distilled members status adds on top of the raw custody block
    assert "attention" in health and "headline" in health

    # the three classes are disjoint and exhaustive over the read twins that
    # carry a scope: no twin is both a bare array and a stats-object, and the
    # audit twin is neither shape — the contract has no overlap or gap.
    assert set(_ARRAY_TWINS).isdisjoint(_STATS_OBJECT_TWINS)
    assert "get_library_health" not in _ARRAY_TWINS
    assert "get_library_health" not in _STATS_OBJECT_TWINS


def test_get_library_health_carries_the_conflicts_aggregate(scrolls_home):
    """H275: the import-conflict aggregate (`custody.conflicts`) rides the MCP
    `get_library_health` twin for free (the tool returns `run_doctor`'s whole custody
    block), so an agent operating purely over MCP can read the scope-level conflict
    count — and it converges with the CLI `doctor` by construction."""
    from scrolls.custody import conflict_event, record_events
    from scrolls.doctor import run_doctor

    _seed_verifiable_item(content_hash="sha256:held")
    # a peer's capture of the held id disagreed at import — a recorded conflict event
    record_events(get_paths().db_path, [
        conflict_event(
            "web:demo", held_hash="sha256:held", incoming_hash="sha256:incoming",
            now="2026-06-22T00:00:00+00:00",
        )
    ])

    health = mcp_server.get_library_health()["conflicts"]
    assert health["items"] == 1
    assert [e["id"] for e in health["events"]] == ["web:demo"]
    assert health["events"][0]["observed_hash"] == "sha256:incoming"
    # the drift axis stays disjoint — a conflict never inflates the MCP drift counts
    assert health["events"][0]["status"] == "conflict"
    assert mcp_server.get_library_health()["drift"]["checked"] == 0
    # converges field-for-field with the CLI doctor (the audit-twin guarantee)
    assert health == run_doctor(get_paths())["custody"]["conflicts"]


def test_get_library_health_carries_the_archive_integrity_block(scrolls_home):
    """H293: the archive-integrity audit (`custody.archive`) rides the MCP
    `get_library_health` twin for free (the tool returns `run_doctor`'s whole custody
    block), so an agent operating purely over MCP can read whether any archived prior's
    advertised `prior_hash` diverges from its snapshot body — and it converges with the
    CLI `doctor` by construction."""
    import sqlite3

    from scrolls.doctor import run_doctor

    _seed_with_archived_prior()  # one honest prior: prior_hash == snapshot.content_hash
    clean = mcp_server.get_library_health()["archive"]
    assert clean == {"status": "ok", "checked": 1, "mismatched": 0, "events": []}

    # corrupt the advertised fingerprint so it no longer matches the snapshot body
    conn = sqlite3.connect(get_paths().db_path)
    with conn:
        conn.execute(
            "UPDATE item_archive SET prior_hash = ? WHERE item_id = ?",
            ("sha256:tampered", "web:demo"),
        )
    conn.close()

    health = mcp_server.get_library_health()["archive"]
    assert health["mismatched"] == 1
    assert health["events"] == [
        {
            "item_id": "web:demo",
            "prior_hash": "sha256:tampered",
            "snapshot_hash": "sha256:held",
        }
    ]
    # converges field-for-field with the CLI doctor (the audit-twin guarantee)
    assert health == run_doctor(get_paths())["custody"]["archive"]


def test_get_library_health_carries_the_custody_posture(scrolls_home):
    """H369: the whole-library custody posture verdict (`custody.posture`,
    custody-vision §3.1) rides the MCP `get_library_health` twin for free (the tool
    returns `run_doctor`'s whole custody block), so an agent operating purely over MCP
    reads the single "is the library in good custody?" verdict in one field instead of
    cross-referencing seven blocks — and it converges with the CLI `doctor` by
    construction."""
    from scrolls.custody import conflict_event, record_events
    from scrolls.doctor import run_doctor

    # a clean rendered holding → sound
    _seed_verifiable_item(content_hash="sha256:held")
    assert mcp_server.get_library_health()["posture"] == {
        "verdict": "sound", "reasons": []}

    # an unresolved import conflict is a soft concern → attention (the integrity score
    # is untouched — a peer disagreement is not our drift, M2)
    record_events(get_paths().db_path, [conflict_event(
        "web:demo", held_hash="sha256:held", incoming_hash="sha256:peer",
        now="2026-06-22T00:00:00+00:00")])
    health = mcp_server.get_library_health()
    assert health["posture"] == {"verdict": "attention", "reasons": ["open_conflicts"]}
    assert health["score"] == 100
    # converges field-for-field with the CLI doctor (the audit-twin guarantee)
    assert health["posture"] == run_doctor(get_paths())["custody"]["posture"]


def _seed_string_twin_pages(db):
    """A rendered, concept- and tag-bearing pair so a compiled library has a
    concept page and a tag page for the string twins to serve.

    Distinct topic ("vectors"/`ranking`) from the H186 ``attention`` seed, so a
    `get_context_bundle("attention")` over the combined library is unchanged —
    these items don't match that query — keeping the context-bundle ↔ CLI
    parity a clean structural equality.
    """
    from scrolls.items import ScrollItem, insert_item

    insert_item(db, ScrollItem(
        id="arxiv:vec", source="arxiv", url="https://arxiv.org/abs/vec",
        saved_at="2026-06-12T00:00:00+00:00", title="Vector Retrieval",
        raw_text="<r>vectors</r>", extracted_text="dense vector retrieval ranking",
        content_hash="sha256:v1", stage="rendered",
        markdown_path="scrolls/arxiv/vec.md",
        concepts=("Vector retrieval",), tags=("ranking",)))
    insert_item(db, ScrollItem(
        id="crossref:vec", source="crossref", url="https://doi.org/10.1234/vec",
        canonical_url="https://doi.org/10.1234/vec", source_id="10.1234/vec",
        saved_at="2026-06-12T00:00:00+00:00", title="Vectors, published",
        raw_text="<r>vectors</r>", extracted_text="vector retrieval published ranking",
        content_hash="sha256:v2", stage="rendered",
        markdown_path="scrolls/crossref/vec.md",
        concepts=("Vector retrieval",), tags=("ranking",)))


def test_mcp_read_surface_markdown_string_class(scrolls_home, capsys):
    # roadmap H194: the *fourth* shape class beside the three JSON classes of
    # test_mcp_read_surface_shape_contract (H186). The Markdown-string read
    # twins — get_context_bundle/get_concept_page/get_tag_page — are a
    # genuinely distinct shape: they return a `str` (the artifact *is* the
    # output, ADR 0077, not a JSON report about it), so they carry their custody
    # honesty *inside* the rendered text (the custody_headline, the G2 Coverage:
    # line, the _By source:_/_Attention:_/_Refresh:_ lines), never a JSON
    # envelope. Pinning them as class D completes the read-surface taxonomy so a
    # future read tool's shape has one of four obvious contracts to satisfy.
    # See the "MCP read-surface shape contract" subsection of docs/architecture.md.
    main(["init"])
    db = get_paths().db_path
    _seed_surface_shape_fixture(db)   # the H186 attention seed → the context bundle
    _seed_string_twin_pages(db)       # rendered concept/tag-bearing pair → the pages
    compile_kb(get_paths())

    # class D — every string twin returns a `str` artifact, non-vacuous, and is
    # NOT a JSON envelope: an agent cannot json.loads() a scope/results object
    # off it (it is Markdown), so its honesty must be read from the text.
    string_results = {
        "get_context_bundle": mcp_server.get_context_bundle("attention"),
        "get_concept_page": mcp_server.get_concept_page("Vector retrieval"),
        "get_tag_page": mcp_server.get_tag_page("ranking"),
    }
    assert set(string_results) == set(_STRING_TWINS)  # every string twin covered
    for name, doc in string_results.items():
        assert isinstance(doc, str), f"{name} must return a Markdown string"
        assert doc.strip(), f"{name} returned an empty document"
        assert "# " in doc, f"{name} carries no Markdown heading"
        with pytest.raises(json.JSONDecodeError):
            json.loads(doc)  # not parseable into any JSON scope envelope
    # non-vacuous: each twin serves its own artifact's heading (the concept/tag
    # heading rides inside the @generated sentinel fence, ADR 0102)
    assert "# Scrolls Context Bundle: attention" in string_results["get_context_bundle"]
    assert "# Concept: Vector retrieval" in string_results["get_concept_page"]
    assert "# Tag: ranking" in string_results["get_tag_page"]

    # get_context_bundle carries the same headline / Coverage / action-line text
    # the CLI `context` does — the surface-parity the convergence suite proves
    # per-line; here we assert the *shape class* (the custody honesty rides in
    # the text, not a JSON field) by pinning byte-identity with the CLI surface
    # over one scope, so whatever custody/action lines the CLI emits ride
    # identically on the MCP twin.
    bundle = string_results["get_context_bundle"]
    capsys.readouterr()  # discard the `init` payload above
    assert main(["context", "attention"]) == 0
    cli_bundle = capsys.readouterr().out
    assert bundle == cli_bundle  # MCP twin == CLI artifact, byte-for-byte
    # the custody honesty lives inside the rendered text (not a JSON field):
    assert "# Scrolls Context Bundle: attention" in bundle
    assert "_Custody:" in bundle          # the scope custody headline
    assert "Coverage:" in bundle          # the G2 completeness line

    # the FOUR classes are disjoint and exhaustive over the custody-bearing read
    # twins: no twin belongs to two classes, and class C (the lone audit twin)
    # is none of the others — the taxonomy has no overlap or gap.
    assert set(_STRING_TWINS).isdisjoint(_ARRAY_TWINS)
    assert set(_STRING_TWINS).isdisjoint(_STATS_OBJECT_TWINS)
    assert "get_library_health" not in _STRING_TWINS


def test_get_context_bundle_is_markdown(scrolls_home, fake_wikipedia_api):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")
    bundle = mcp_server.get_context_bundle("database engine")
    assert bundle.startswith("# Scrolls Context Bundle: database engine")
    assert "wikipedia:en:SQLite" in bundle
    # the coverage line travels on the MCP twin too (completeness contract G2):
    # one match, under the cap, so the bundle states it is complete
    assert "Coverage: all 1 matching scrolls" in bundle


def test_get_context_bundle_carries_the_strength_explanation(scrolls_home):
    # roadmap H315 — the explainable-ranking surface lifted to the context bundle
    # over MCP: the same per-match `· <strength>` markers and `_Strength:_` headline
    # the CLI `scrolls context` renders, since the twin returns build_context's output.
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:title", source="web", url="https://ex.com/title",
        saved_at="2026-06-12T00:00:00+00:00", title="Widget ranking guide",
        extracted_text="a body about widgets.", summary="a summary about widgets.",
        stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:body", source="web", url="https://ex.com/body",
        saved_at="2026-06-12T00:00:01+00:00", title="Plain widget page",
        extracted_text="deep in the body ranking appears once.",
        summary="an unrelated widget summary.", stage="rendered"))

    bundle = mcp_server.get_context_bundle("ranking")
    # one title hit (strong) + one body-only hit (weak); the headline folds both
    assert "_Strength: strong 1, weak 1 (of 2)._" in bundle
    assert "(`web:title`) · strong" in bundle
    assert "(`web:body`) · weak" in bundle


def test_get_context_bundle_honors_facets(scrolls_home, fake_wikipedia_api):
    mcp_server.ingest_url("https://en.wikipedia.org/wiki/SQLite")  # category: reference

    bundle = mcp_server.get_context_bundle("database", source="wikipedia")
    assert bundle.startswith("# Scrolls Context Bundle: database (source=wikipedia)")
    assert "wikipedia:en:SQLite" in bundle
    # a facet that excludes everything still yields a valid, self-documenting bundle
    empty = mcp_server.get_context_bundle("database", source="arxiv")
    assert empty.startswith("# Scrolls Context Bundle: database (source=arxiv)")
    assert "No matching scrolls." in empty


def _seed_context_custody_mix(db):
    """Two full + two partial matching `database`; one full re-checked unchanged,
    one full drifted, the partials never re-checked (→ unverified)."""
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    insert_item(db, ScrollItem(
        id="web:full0", source="web", url="https://ex.com/full0",
        saved_at="2026-06-12T00:00:00+00:00", title="Full database zero",
        raw_text="A database engine held in full.", content_hash="sha256:f0",
        stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:full1", source="web", url="https://ex.com/full1",
        saved_at="2026-06-12T00:00:01+00:00", title="Full database one",
        raw_text="Another database engine held in full.", content_hash="sha256:f1",
        stage="rendered"))
    insert_item(db, ScrollItem(
        id="web:partial0", source="web", url="https://ex.com/partial0",
        saved_at="2026-06-12T00:00:02+00:00", title="Partial database zero",
        extracted_text="A database, content held but no hash.", stage="fetched"))
    insert_item(db, ScrollItem(
        id="web:partial1", source="web", url="https://ex.com/partial1",
        saved_at="2026-06-12T00:00:03+00:00", title="Partial database one",
        extracted_text="Another database, content held but no hash.", stage="fetched"))
    record_events(db, [
        CustodyEvent("web:full0", "t", "unchanged", "sha256:f0", "sha256:f0", None),
        CustodyEvent("web:full1", "t", "drifted", "sha256:f1", "sha256:x", None),
    ])


def test_get_context_bundle_filters_by_fidelity_tier(scrolls_home):
    # roadmap H257 — the custody-filter family reaches the agent context bundle
    # over MCP. The twin of `scrolls context --fidelity`: keeps only the matches
    # held at the named tier (the same per-hit `fidelity` `search_scrolls` shows),
    # sieved before the cap, and names the scope in the title.
    from scrolls.cli import main

    main(["init"])
    _seed_context_custody_mix(get_paths().db_path)

    bundle = mcp_server.get_context_bundle("database", fidelity="full")
    assert bundle.startswith("# Scrolls Context Bundle: database (fidelity=full)")
    assert "web:full0" in bundle and "web:full1" in bundle
    assert "web:partial0" not in bundle and "web:partial1" not in bundle
    # the rendered custody headline describes exactly the kept set
    headline = next(ln for ln in bundle.splitlines() if ln.startswith("_Custody:"))
    assert "fidelity full 2" in headline and "partial" not in headline


def test_get_context_bundle_filters_by_drift_posture(scrolls_home):
    # the ledger-axis twin: keeps only the matches at one verify-ledger posture
    from scrolls.cli import main

    main(["init"])
    _seed_context_custody_mix(get_paths().db_path)

    bundle = mcp_server.get_context_bundle("database", drift="drifted")
    assert bundle.startswith("# Scrolls Context Bundle: database (drift=drifted)")
    assert "web:full1" in bundle  # the one drifted match
    for absent in ("web:full0", "web:partial0", "web:partial1"):
        assert absent not in bundle
    # both axes AND, sieved before the cap
    both = mcp_server.get_context_bundle("database", fidelity="full", drift="verified")
    assert "web:full0" in both
    for absent in ("web:full1", "web:partial0", "web:partial1"):
        assert absent not in both


def test_get_context_bundle_rejects_unknown_custody_values(scrolls_home):
    # the same closed vocabulary as search_scrolls/list_scrolls; never a silent
    # empty bundle — an unknown tier/posture is an error the client sees.
    import pytest

    from scrolls.cli import main

    main(["init"])
    with pytest.raises(ValueError):
        mcp_server.get_context_bundle("database", fidelity="ful")
    with pytest.raises(ValueError):
        mcp_server.get_context_bundle("database", drift="drift")


def test_get_context_bundle_filters_by_match_strength(scrolls_home):
    # roadmap H316 — the rank-axis filter reaches the agent context bundle over
    # MCP, the twin of `scrolls context --strength` and the rank sibling of
    # get_context_bundle(fidelity=/drift=). Threshold semantics (at or above), the
    # same band `search_scrolls(strength=)` keeps: `strong` keeps title hits,
    # `moderate` title-or-summary, `weak` everything. Sieved before the cap, named
    # in the title, and the `_Strength:_` headline describes the kept set.
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="web:title", source="web", url="https://ex.com/title",
        saved_at="2026-06-12T00:00:00+00:00", title="Widget ranking guide",
        extracted_text="a body about widgets.", summary="a summary about widgets.",
        stage="rendered"))  # `ranking` in the title → strong
    insert_item(db, ScrollItem(
        id="web:summary", source="web", url="https://ex.com/summary",
        saved_at="2026-06-12T00:00:01+00:00", title="Plain widget page",
        extracted_text="a body about widgets.",
        summary="this summary covers ranking functions.", stage="rendered"))  # → moderate
    insert_item(db, ScrollItem(
        id="web:body", source="web", url="https://ex.com/body",
        saved_at="2026-06-12T00:00:02+00:00", title="Another widget page",
        extracted_text="deep in the body ranking appears once.",
        summary="an unrelated widget summary.", stage="rendered"))  # body-only → weak

    strong = mcp_server.get_context_bundle("ranking", strength="strong")
    assert strong.startswith("# Scrolls Context Bundle: ranking (strength=strong)")
    assert "web:title" in strong
    assert "web:summary" not in strong and "web:body" not in strong
    headline = next(ln for ln in strong.splitlines() if ln.startswith("_Strength:"))
    assert headline == "_Strength: strong 1 (of 1)._"

    # threshold semantics: moderate keeps strong+moderate, weak keeps all three
    moderate = mcp_server.get_context_bundle("ranking", strength="moderate")
    assert "web:title" in moderate and "web:summary" in moderate
    assert "web:body" not in moderate
    weak = mcp_server.get_context_bundle("ranking", strength="weak")
    for present in ("web:title", "web:summary", "web:body"):
        assert present in weak


def test_get_context_bundle_rejects_an_unknown_match_strength(scrolls_home):
    # the same closed vocabulary as search_scrolls(strength=)/`scrolls context
    # --strength`; never a silent empty bundle — an unknown band is an error.
    import pytest

    from scrolls.cli import main

    main(["init"])
    with pytest.raises(ValueError):
        mcp_server.get_context_bundle("ranking", strength="strongest")


def test_get_context_bundle_filters_by_content_duplicate(scrolls_home, capsys):
    # roadmap H345 — the content-identity browse filter reaches the agent context
    # bundle over MCP, the twin of `scrolls context --content-duplicate` and the
    # content sibling of get_context_bundle(fidelity=/drift=/strength=). Keeps only
    # the matches the library holds a byte-identical copy of under another id (the
    # same `content_hash`), whole-library sibling scope, named in the title; byte
    # parity with the CLI bundle.
    from scrolls.cli import main

    main(["init"])
    db = get_paths().db_path
    _seed_content_duplicate_mix(db)  # `alpha` matches the two dup groups + solo + ref

    bundle = mcp_server.get_context_bundle("alpha", content_duplicate=True)
    assert bundle.startswith("# Scrolls Context Bundle: alpha (content-duplicate)")
    # the four byte-identical members are kept (two cross-source/single-source groups)
    for kept in ("web:a", "arxiv:1", "web:p", "web:q"):
        assert kept in bundle
    # the unique-held and the NULL-hash reference are dropped
    assert "web:solo" not in bundle and "web:ref" not in bundle

    # byte parity with the CLI `context --content-duplicate`
    capsys.readouterr()  # clear the init/seed stdout
    main(["context", "alpha", "--content-duplicate"])
    cli_bundle = capsys.readouterr().out
    assert bundle == cli_bundle


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


def test_get_context_bundle_index_carries_the_fidelity_holdings_line(scrolls_home, capsys):
    # roadmap H214 — the MCP twin of H212. get_context_bundle is a read-through of
    # build_context, so the leanest `index` tier carries the same ledger-free
    # `_Fidelity:_` holdings line the CLI emits (fidelity travels with every result,
    # vision principle 3) and the same honest *absence* of any drift verdict — it
    # reads no ledger, so claiming `verified`/`unverified` there would be the M2
    # anti-fabrication violation. Pin that the agent-facing bundle and the CLI never
    # diverge on the leanest tier's fidelity read.
    from scrolls.cli import main
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, ScrollItem(
        id="wikipedia:en:Full", source="wikipedia",
        url="https://en.wikipedia.org/wiki/Full",
        saved_at="2026-06-12T00:00:00+00:00", title="Full database",
        extracted_text="A fully held database body.",
        raw_text="<raw>A fully held database body.</raw>",
        content_hash="deadbeef", stage="fetched",
    ))
    insert_item(db, ScrollItem(
        id="wikipedia:en:Partial", source="wikipedia",
        url="https://en.wikipedia.org/wiki/Partial",
        saved_at="2026-06-12T00:00:00+00:00", title="Partial database",
        extracted_text="A partial database body.", stage="fetched",
    ))  # no hash/raw → partial — a second tier, so the line is non-vacuous
    # a drift event the leanest tier must NOT read or claim
    record_events(db, [CustodyEvent(
        "wikipedia:en:Full", "2026-06-14T00:00:00+00:00", "drifted",
        "deadbeef", "cafe", None)])

    index = mcp_server.get_context_bundle("database", budget="index")
    fidelity = next(line for line in index.splitlines() if line.startswith("_Fidelity:"))
    assert "full 1, partial 1" in fidelity and "(of 2)" in fidelity
    # the leanest tier reads no ledger: no drift verdict, no `_Custody:` headline
    assert "_Custody:" not in index
    assert "drifted" not in index

    # the MCP twin never diverges from the CLI on that line (both are build_context)
    capsys.readouterr()
    assert main(["context", "database", "--budget", "index"]) == 0
    cli = capsys.readouterr().out
    cli_fidelity = next(line for line in cli.splitlines() if line.startswith("_Fidelity:"))
    assert fidelity == cli_fidelity

    # from `connected` up the full headline carries fidelity, so the dedicated
    # `_Fidelity:_` line is an index-only lever — not duplicated above, exactly
    # as on the CLI (the H212 no-duplication rule, here over MCP).
    connected = mcp_server.get_context_bundle("database", budget="connected")
    assert "_Fidelity:" not in connected
    headline = next(line for line in connected.splitlines() if line.startswith("_Custody:"))
    assert "fidelity full 1, partial 1" in headline


def test_get_context_bundle_index_fidelity_scope_is_honest_under_truncation(
    scrolls_home, capsys
):
    # roadmap H222 — the MCP twin of H221. The leanest tier's `_Fidelity:_` line
    # counts the *in-bundle* set (the kept post-cap representations), so when the
    # bundle is capped its `(of N)` must equal the Coverage line's `returned`,
    # never the library-wide matched total — on the read an agent actually reaches
    # over MCP, byte-identical to the CLI (just as H214 pins the untruncated line).
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    # 3 full + 3 partial, all matching "database" — a mixed-fidelity scope larger
    # than the cap. With limit=4, pigeonhole forces the kept 4 to span *both*
    # tiers (only 3 of either exist), so the in-bundle split (sums to 4) is
    # provably not the library-wide `full 3, partial 3` (sums to 6).
    for index in range(3):
        insert_item(db, ScrollItem(
            id=f"wikipedia:en:Full_{index}", source="wikipedia",
            url=f"https://en.wikipedia.org/wiki/Full_{index}",
            saved_at="2026-06-12T00:00:00+00:00", title=f"Full database {index}",
            extracted_text="A fully held database body.",
            raw_text="<raw>A full database body.</raw>",
            content_hash=f"deadbeef0{index}", stage="fetched",
        ))
        insert_item(db, ScrollItem(
            id=f"wikipedia:en:Partial_{index}", source="wikipedia",
            url=f"https://en.wikipedia.org/wiki/Partial_{index}",
            saved_at="2026-06-12T00:00:00+00:00", title=f"Partial database {index}",
            extracted_text="A partial database body.", stage="fetched",
        ))  # no hash/raw → partial fidelity

    index = mcp_server.get_context_bundle("database", budget="index", limit=4)
    fidelity = next(line for line in index.splitlines() if line.startswith("_Fidelity:"))
    coverage = next(line for line in index.splitlines() if line.startswith("_Coverage:"))

    # the bundle is genuinely truncated: top 4 of 6
    returned, matched = (int(n) for n in re.search(r"the top (\d+) of (\d+)", coverage).groups())
    assert (returned, matched) == (4, 6)

    # the holdings scope names only what the bundle saw, tied to Coverage's
    # `returned` — never the library-wide matched total it never read
    scope = int(re.search(r"\(of (\d+)\)", fidelity).group(1))
    assert scope == returned        # (of 4), == Coverage's top
    assert scope != matched         # never (of 6)
    # and the tier counts sum to that in-bundle scope, not the whole library
    counts = {tier: int(n) for tier, n in re.findall(r"(full|partial|reference) (\d+)", fidelity)}
    assert sum(counts.values()) == returned     # sums to 4, not 6
    # the kept set is provably mixed (pigeonhole), so the line isn't accidentally
    # all-one-tier — a real holdings split over the truncated scope
    assert counts.get("full") and counts.get("partial")

    # the MCP twin never diverges from the CLI on the truncated line either (both
    # are build_context) — the H214 byte-identity, here under truncation
    capsys.readouterr()
    assert main(["context", "database", "--budget", "index", "--limit", "4"]) == 0
    cli = capsys.readouterr().out
    cli_fidelity = next(line for line in cli.splitlines() if line.startswith("_Fidelity:"))
    assert fidelity == cli_fidelity


def test_get_context_bundle_index_fidelity_scope_honors_the_active_facet(
    scrolls_home, capsys
):
    # roadmap H227 — the MCP twin of H223. The leanest `index` `_Fidelity:_` holdings
    # count the *post-facet* kept set, so a scoped get_context_bundle(..., source=<S>)
    # names only <S>'s fidelity tiers and `(of k)` scope — never the library-wide
    # holdings of a multi-source library — on the read an agent actually reaches over
    # MCP, byte-identical to the CLI's `context --budget index --source <S>` (just as
    # H214 pins the untruncated line and H222 the truncated one). The *facet*-axis
    # sibling of H222's *truncation*-axis `(of N)` scope-honesty.
    from scrolls.cli import main
    from scrolls.custody import custody_counts, custody_counts_by_source
    from scrolls.items import ScrollItem, insert_item, list_items

    main(["init"])
    db = get_paths().db_path
    # multi-source, mixed-fidelity *within* one source: web is full 1 + partial 1,
    # arxiv is full 2. So web's holdings (full 1, partial 1, of 2) are provably a
    # strict subset of — and a different tier split than — the library-wide holdings
    # (full 3, partial 1, of 4). All titles carry "database" so one query covers all.
    insert_item(db, ScrollItem(
        id="web:full", source="web", url="https://web.example/full",
        saved_at="2026-06-12T00:00:00+00:00", title="Full database",
        extracted_text="A full database body.",
        raw_text="<raw>A full database body.</raw>",
        content_hash="deadbeef", stage="fetched",
    ))
    insert_item(db, ScrollItem(
        id="web:partial", source="web", url="https://web.example/partial",
        saved_at="2026-06-12T00:00:00+00:00", title="Partial database",
        extracted_text="A partial database body.", stage="fetched",
    ))  # no hash/raw → partial
    for index in range(2):
        insert_item(db, ScrollItem(
            id=f"arxiv:{index}", source="arxiv",
            url=f"https://arxiv.org/abs/{index}",
            saved_at="2026-06-12T00:00:00+00:00", title=f"Arxiv database {index}",
            extracted_text="A database paper body.",
            raw_text="<raw>A database paper body.</raw>",
            content_hash=f"aa11bb2{index}", stage="fetched",
        ))

    # what web's holdings vs. the whole library's actually are, straight from the
    # shared `custody_counts*` primitive (`{}` verdicts — fidelity is ledger-free),
    # so the expectations are tied to the scoped subset, not independently hardcoded
    items = list_items(db)
    web_tiers = {t: n for t, n in custody_counts_by_source(items, {})["web"]["tiers"].items() if n}
    web_n = sum(custody_counts_by_source(items, {})["web"]["tiers"].values())
    whole_tiers = {t: n for t, n in custody_counts(items, {})["tiers"].items() if n}
    whole_n = len(items)

    def _fidelity_of(bundle):
        line = next(l for l in bundle.splitlines() if l.startswith("_Fidelity:"))
        counts = {t: int(n) for t, n in re.findall(r"(full|partial|reference) (\d+)", line)}
        scope = int(re.search(r"\(of (\d+)\)", line).group(1))
        return line, counts, scope

    scoped_line, scoped_counts, scoped_scope = _fidelity_of(
        mcp_server.get_context_bundle("database", budget="index", source="web"))
    _, unscoped_counts, unscoped_scope = _fidelity_of(
        mcp_server.get_context_bundle("database", budget="index"))

    # the scoped line names only web's holdings and its `(of k)` scope
    assert scoped_counts == web_tiers       # {full 1, partial 1}
    assert scoped_scope == web_n            # (of 2)
    # the unscoped line names the whole-library holdings
    assert unscoped_counts == whole_tiers   # {full 3, partial 1}
    assert unscoped_scope == whole_n        # (of 4)
    # the scope honesty is non-vacuous: the two genuinely differ on both axes — the
    # scoped read never silently reverts to the library-wide holdings it didn't see
    assert web_tiers != whole_tiers
    assert web_n != whole_n

    # the distinguishing MCP-twin assertion: the scoped bundle's `_Fidelity:_` line is
    # byte-identical to the CLI's scoped read (both are build_context, so the
    # agent-facing bundle and the CLI never diverge on the facet-scoped holdings line,
    # just as H214/H222 pin for the untruncated/truncated line).
    capsys.readouterr()
    assert main(["context", "database", "--budget", "index", "--source", "web"]) == 0
    cli = capsys.readouterr().out
    cli_fidelity = next(l for l in cli.splitlines() if l.startswith("_Fidelity:"))
    assert scoped_line == cli_fidelity


def test_get_context_bundle_index_fidelity_scope_is_honest_under_facet_and_truncation(
    scrolls_home, capsys
):
    # roadmap H232 — the MCP twin of H228 (the *composition* of H222's truncation
    # axis and H227's facet axis). The leanest `index` `_Fidelity:_` `(of N)` must
    # stay honest when BOTH scope-narrowing filters apply at once on the read an
    # agent actually reaches over MCP — neither silently reverting to a pre-filter
    # count when the other is active — and stay byte-identical to the CLI (just as
    # H222 pins the truncated line and H227 the facet-scoped line).
    from scrolls.cli import main
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path
    # web: 3 full + 3 partial (6 matching) — a mixed-fidelity scope larger than the
    # cap (4). arxiv: 2 full — so the library-wide match total (8) strictly exceeds
    # web's scoped total (6), and both exceed the cap. Every title carries "database"
    # so one query covers the whole library.
    for index in range(3):
        insert_item(db, ScrollItem(
            id=f"web:full_{index}", source="web",
            url=f"https://web.example/full/{index}",
            saved_at="2026-06-12T00:00:00+00:00", title=f"Full database {index}",
            extracted_text="A full database body.",
            raw_text="<raw>A full database body.</raw>",
            content_hash=f"deadbeef0{index}", stage="fetched",
        ))
        insert_item(db, ScrollItem(
            id=f"web:partial_{index}", source="web",
            url=f"https://web.example/partial/{index}",
            saved_at="2026-06-12T00:00:00+00:00", title=f"Partial database {index}",
            extracted_text="A partial database body.", stage="fetched",
        ))  # no hash/raw → partial fidelity
    for index in range(2):
        insert_item(db, ScrollItem(
            id=f"arxiv:{index}", source="arxiv",
            url=f"https://arxiv.org/abs/{index}",
            saved_at="2026-06-12T00:00:00+00:00", title=f"Arxiv database {index}",
            extracted_text="A database paper body.",
            raw_text="<raw>A database paper body.</raw>",
            content_hash=f"aa11bb2{index}", stage="fetched",
        ))

    # the scoped-and-truncated read an agent reaches over MCP: source="web" AND
    # limit=4, both filters live at once
    scoped = mcp_server.get_context_bundle(
        "database", budget="index", source="web", limit=4)
    fidelity = next(l for l in scoped.splitlines() if l.startswith("_Fidelity:"))
    coverage = next(l for l in scoped.splitlines() if l.startswith("_Coverage:"))

    # the Coverage line proves BOTH filters compose: the cap truncates web's 6 to 4
    # (`returned`), and the facet narrows the denominator to web's 6 (`matched`) —
    # never the library-wide 8 an unscoped read would show under the same cap
    returned, matched = (int(n) for n in re.search(r"the top (\d+) of (\d+)", coverage).groups())
    assert (returned, matched) == (4, 6)

    # the fidelity scope names only the post-facet, post-cap kept set, tied to the
    # scoped-and-truncated Coverage `returned` (parsed from both rendered lines, so
    # the two numbers are tied, not independently hardcoded)
    scope = int(re.search(r"\(of (\d+)\)", fidelity).group(1))
    assert scope == returned          # (of 4)
    assert scope != matched           # never the scoped-untruncated 6
    # the tier counts sum to that kept set, not any pre-filter count
    counts = {tier: int(n) for tier, n in re.findall(r"(full|partial|reference) (\d+)", fidelity)}
    assert sum(counts.values()) == returned   # sums to 4, not 6 or 8
    # the kept 4 of web's {3 full, 3 partial} must span both tiers (pigeonhole: only
    # 3 of either exist), so the line is a real holdings split over the
    # scoped-and-truncated scope, not accidentally all-one-tier
    assert counts.get("full") and counts.get("partial")

    # non-vacuous on the FACET axis under truncation: the *unscoped* read at the same
    # cap sees the whole library's 8 matches (top 4 of 8), so the scoped read
    # genuinely narrowed the denominator — never reverting to the unscoped-but-
    # truncated set (whose `(of 4)` shares the number but not the scope)
    unscoped = mcp_server.get_context_bundle("database", budget="index", limit=4)
    unscoped_cov = next(l for l in unscoped.splitlines() if l.startswith("_Coverage:"))
    unscoped_matched = int(re.search(r"the top \d+ of (\d+)", unscoped_cov).group(1))
    assert unscoped_matched == 8
    assert matched != unscoped_matched        # 6 (web) ≠ 8 (library)

    # non-vacuous on the TRUNCATION axis under facet scope: the *untruncated* scoped
    # read names web's full 6 (of 6), so the cap genuinely truncated — never
    # reverting to the scoped-but-untruncated set
    scoped_untruncated = mcp_server.get_context_bundle(
        "database", budget="index", source="web")
    su_fidelity = next(l for l in scoped_untruncated.splitlines() if l.startswith("_Fidelity:"))
    su_scope = int(re.search(r"\(of (\d+)\)", su_fidelity).group(1))
    assert su_scope == 6
    assert scope != su_scope                   # 4 ≠ 6

    # the distinguishing MCP-twin assertion: the scoped-and-truncated bundle's
    # `_Fidelity:_` line is byte-identical to the CLI's read under both filters (both
    # are build_context, so the agent-facing bundle and the CLI never diverge on the
    # composed holdings line either, just as H222/H227 pin each filter alone).
    capsys.readouterr()
    assert main([
        "context", "database", "--budget", "index", "--source", "web", "--limit", "4"
    ]) == 0
    cli = capsys.readouterr().out
    cli_fidelity = next(l for l in cli.splitlines() if l.startswith("_Fidelity:"))
    assert fidelity == cli_fidelity


def test_get_context_bundle_index_fidelity_counts_tie_to_scoped_library_health(
    scrolls_home,
):
    # roadmap H235 — the MCP twin of H229. Where H229 ties the *CLI*
    # `context --budget index --source <S>`'s `_Fidelity:_` tier counts to
    # `doctor --source <S>`'s `custody.tiers`, this carries that scoped tie onto the
    # read *pair* an agent reaches over MCP: over a multi-source, mixed-fidelity
    # library where one query matches all of <S>'s held items (no truncation),
    # `get_context_bundle(query, budget="index", source=<S>)`'s `_Fidelity:_` tier
    # counts ≡ `get_library_health(source=<S>)`'s `custody.tiers` (non-zero) — both
    # fold `get_fidelity` over the same scoped item set, so the leanest tier an agent
    # boots on over MCP and the deep custody audit it also reads over MCP never
    # disagree on what fraction of one source is held in full. The scoped sibling, on
    # the MCP read pair, of H214's unscoped MCP↔CLI fidelity-line tie.
    from scrolls.custody import custody_counts_by_source, get_fidelity
    from scrolls.items import ScrollItem, insert_item, list_items, update_item

    main(["init"])
    db = get_paths().db_path
    # web spans three tiers (full 2, partial 1, reference 1); one out-of-scope arxiv
    # `full` lifts the library-wide tiers to {full 3, …}, so web's scope is a strict
    # subset of — and a different tier split than — the whole library (scoping is
    # non-vacuous). Every title carries "topic" so one query matches all of web's held
    # items (no truncation: web holds 4 < the default limit, so the bundle's post-facet
    # set *is* the whole web scope the audit folds over).
    def _web(item_id, title, **kw):
        kw.setdefault("stage", "fetched")
        return ScrollItem(
            id=item_id, source="web", url=f"https://web.example/{item_id}",
            saved_at="2026-06-12T00:00:00+00:00", title=title, **kw)

    insert_item(db, _web("web:full1", "Topic full one",
                         extracted_text="topic one body",
                         raw_text="<raw>topic one</raw>", content_hash="sha256:f1"))
    insert_item(db, _web("web:full2", "Topic full two",
                         extracted_text="topic two body",
                         raw_text="<raw>topic two</raw>", content_hash="sha256:f2"))
    insert_item(db, _web("web:partial", "Topic partial",
                         extracted_text="topic partial body"))  # no hash/raw → partial
    insert_item(db, _web("web:ref", "Topic reference pointer",
                         stage="detected"))  # no content → reference
    insert_item(db, ScrollItem(
        id="arxiv:1", source="arxiv", url="https://arxiv.org/abs/1",
        saved_at="2026-06-12T00:00:00+00:00", title="Topic arxiv paper", stage="fetched",
        extracted_text="topic", raw_text="<raw>topic</raw>", content_hash="sha256:a"))

    def _nonzero(counts):
        return {tier: n for tier, n in counts.items() if n}

    def scoped_picture():
        # the leanest-tier holdings line for the web scope over MCP, and the canonical
        # scoped audit's tiers over MCP — the read *pair* an agent reaches over MCP.
        bundle = mcp_server.get_context_bundle("topic", budget="index", source="web")
        line = next(l for l in bundle.splitlines() if l.startswith("_Fidelity:"))
        index = {t: int(n) for t, n in re.findall(r"(full|partial|reference) (\d+)", line)}
        scope_n = int(re.search(r"\(of (\d+)\)", line).group(1))
        tiers = _nonzero(mcp_server.get_library_health(source="web")["tiers"])
        return index, scope_n, tiers

    index, scope_n, tiers = scoped_picture()
    # non-vacuous: web's scope is a genuine multi-tier mix (≥2 non-zero tiers)
    assert tiers == {"full": 2, "partial": 1, "reference": 1}
    # the precondition holds: the query matched all of web's held items, so `(of N)`
    # names the whole scoped held set — the line was never truncated (the H235 tie is a
    # count-equality only when the bundle saw the whole source; H236 is the boundary)
    assert scope_n == sum(tiers.values()) == 4
    # the tie: the scoped leanest-tier holdings over MCP ≡ the scoped audit's tiers over MCP
    assert index == tiers
    # tied to the shared per-source primitive too, not independently hardcoded — both the
    # bundle line and `get_library_health` fold `get_fidelity` over the same scoped subset
    web_tiers = _nonzero(custody_counts_by_source(list_items(db), {})["web"]["tiers"])
    assert index == web_tiers

    # the scope genuinely narrows: the *unscoped* MCP audit names the whole library
    # (arxiv's `full` lifts it to {full 3, …}), so the scoped read never silently reverts
    # to the library-wide holdings it didn't see
    whole = _nonzero(mcp_server.get_library_health()["tiers"])
    assert whole == {"full": 3, "partial": 1, "reference": 1}
    assert tiers != whole

    # mutation in lockstep — drop `web:full1`'s re-derivable body (raw_text + hash) so it
    # falls `full` → `partial`. The shift must register identically on the scoped MCP
    # `_Fidelity:_` line and the scoped `get_library_health(source="web")` audit, proving
    # each recomputes `get_fidelity` over the scoped set rather than echoing a cache.
    full1 = next(it for it in list_items(db) if it.id == "web:full1")
    assert update_item(db, dataclasses.replace(full1, raw_text=None, content_hash=None))
    mutated = next(it for it in list_items(db) if it.id == "web:full1")
    assert get_fidelity(mutated) == "partial"  # the dropped body cost it a tier

    index, scope_n, tiers = scoped_picture()
    assert tiers == {"full": 1, "partial": 2, "reference": 1}  # the shift, on the audit
    assert scope_n == 4                                        # still the whole web scope
    assert index == tiers                                      # and in lockstep on the line


def test_get_context_bundle_index_fidelity_diverges_from_scoped_health_under_truncation(
    scrolls_home,
):
    # roadmap H236 — the MCP twin of H234 (and the truncated boundary of H235).
    # H235 ties `get_context_bundle(query, budget="index", source=<S>)`'s `_Fidelity:_`
    # tier counts ≡ `get_library_health(source=<S>)`'s `tiers` *only when one query
    # matches all of <S>'s held items* (no truncation). But the two answer genuinely
    # different questions on the read pair an agent reaches over MCP: the bundle line is
    # a *this-bundle* fact — "what does this bundle hold in full", over the post-cap kept
    # set (`len(items)`) — while the scoped health audit is a *whole-source* fact — "what
    # does this source hold in full", over every held row. When <S>'s matching items
    # exceed the cap they must **differ**: the line sums to the kept slice `k`, the audit
    # to the source's held count (> k), so the leanest tier an agent boots on over MCP
    # never silently inflates to a source-wide custody claim the bundle didn't render.
    # Lifting the cap (`limit` ≥ the held count) collapses the divergence back to the
    # H235 equality — proving the gap is exactly the truncation, nothing else.
    from scrolls.custody import custody_counts_by_source, get_fidelity
    from scrolls.items import ScrollItem, insert_item, list_items

    main(["init"])
    db = get_paths().db_path
    # web spans three tiers (full 2, partial 1, reference 1 → 4 held); one out-of-scope
    # arxiv `full` lifts the library-wide audit to {full 3, …}, so the source-wide web
    # audit (full 2) is a third, distinct number from both the bundle-kept count and the
    # library-wide holdings — the `--source web` filter is genuinely exercised. Every
    # title carries "topic" so one query matches all of web's held items (truncation is
    # then forced only by the cap, never by the query missing items).
    def _web(item_id, title, **kw):
        kw.setdefault("stage", "fetched")
        return ScrollItem(
            id=item_id, source="web", url=f"https://web.example/{item_id}",
            saved_at="2026-06-12T00:00:00+00:00", title=title, **kw)

    insert_item(db, _web("web:full1", "Topic full one",
                         extracted_text="topic one body",
                         raw_text="<raw>topic one</raw>", content_hash="sha256:f1"))
    insert_item(db, _web("web:full2", "Topic full two",
                         extracted_text="topic two body",
                         raw_text="<raw>topic two</raw>", content_hash="sha256:f2"))
    insert_item(db, _web("web:partial", "Topic partial",
                         extracted_text="topic partial body"))  # no hash/raw → partial
    insert_item(db, _web("web:ref", "Topic reference pointer",
                         stage="detected"))  # no content → reference
    insert_item(db, ScrollItem(
        id="arxiv:1", source="arxiv", url="https://arxiv.org/abs/1",
        saved_at="2026-06-12T00:00:00+00:00", title="Topic arxiv paper", stage="fetched",
        extracted_text="topic", raw_text="<raw>topic</raw>", content_hash="sha256:a"))

    def _nonzero(counts):
        return {tier: n for tier, n in counts.items() if n}

    def scoped_index(limit):
        # the leanest-tier holdings line for the web scope at a given cap, over MCP. Its
        # `(of N)` and tier counts are both over the post-cap kept set (`build_context`
        # passes `len(items)` to `render_fidelity_holdings`, the kept representations).
        bundle = mcp_server.get_context_bundle(
            "topic", budget="index", source="web", limit=limit)
        line = next(l for l in bundle.splitlines() if l.startswith("_Fidelity:"))
        counts = {t: int(n) for t, n in re.findall(r"(full|partial|reference) (\d+)", line)}
        scope_n = int(re.search(r"\(of (\d+)\)", line).group(1))
        return counts, scope_n

    # the canonical *whole-source* audit over MCP: `get_library_health(source="web")`
    # folds `get_fidelity` over all four held web rows, independent of any query or cap.
    source_tiers = _nonzero(mcp_server.get_library_health(source="web")["tiers"])
    assert source_tiers == {"full": 2, "partial": 1, "reference": 1}  # ≥2 tiers, non-vacuous
    held = sum(source_tiers.values())
    assert held == 4
    # tied to the shared per-source primitive too, not independently hardcoded
    web_tiers = _nonzero(custody_counts_by_source(list_items(db), {})["web"]["tiers"])
    assert source_tiers == web_tiers

    # --- under truncation: a cap below the source's held count ----------------------
    cap = 2
    assert cap < held  # the cap genuinely truncates web's matching items (4 > 2)
    kept, scope_n = scoped_index(cap)
    # the bundle line is a *this-bundle* fact — its `(of N)` and tier counts sum to the
    # kept slice `k`, never the whole-source held count.
    assert scope_n == cap == 2
    assert sum(kept.values()) == cap == 2
    # the kept slice is provably mixed (the top-2 of a tier-spanning scope), so the line
    # is a real holdings split, not accidentally all-one-tier
    assert len(kept) >= 1
    # so the two genuinely differ over MCP: the leanest-tier holdings never inflate to the
    # source-wide custody claim (bundle-kept 2 ≠ source-wide {full 2, partial 1, reference 1}).
    assert kept != source_tiers
    assert sum(kept.values()) < sum(source_tiers.values())

    # --- lift the cap: the divergence collapses back to the H235 equality -----------
    # `limit` ≥ the source's held count keeps every matching web item, so the post-cap
    # kept set *is* the whole web scope the audit folds over — the H235 tie, recovered.
    lifted, scope_n = scoped_index(held)  # cap == 4 == held → no truncation
    assert scope_n == held == 4
    assert sum(lifted.values()) == held == 4
    assert lifted == source_tiers  # the gap was exactly the cap, nothing else

    # the `source="web"` filter is non-vacuous on both reads: the *unscoped* MCP audit
    # names the whole library (arxiv's `full` lifts it), so neither the bundle-kept count
    # nor the source-wide audit is ever the library-wide holdings.
    whole = _nonzero(mcp_server.get_library_health()["tiers"])
    assert whole == {"full": 3, "partial": 1, "reference": 1}
    assert source_tiers != whole
    assert kept != whole
    # sanity: `get_fidelity` is the shared fold under both surfaces (web:ref is the
    # reference tier the audit and the lifted bundle both name)
    ref = next(it for it in list_items(db) if it.id == "web:ref")
    assert get_fidelity(ref) == "reference"


def test_get_context_bundle_index_fidelity_ties_to_the_deeper_tier_headlines_over_mcp(
    scrolls_home,
):
    # roadmap H241 — the MCP twin of H213's deeper-tier convergence, under scope.
    # H235 ties the scoped `index` `_Fidelity:_` line to `get_library_health(source=<S>)`
    # *across tools* over MCP, and H227/H229 tie it to the CLI; but no test pins that the
    # *deeper budget tiers* an agent boots over MCP agree with the leanest one *over MCP*.
    # `get_context_bundle(query, budget="connected"/"full", source=<S>)`'s `_Custody:_`
    # headline renders its `fidelity` section via `render_custody_headline` — a *different*
    # function than the `index` line's `render_fidelity_holdings` — so their agreement is a
    # genuine cross-rendering guarantee, not the same code twice. Over a scoped, untruncated
    # mixed-fidelity library, all three fold `get_fidelity` over the same scoped post-facet
    # `items`, so the three MCP budget tiers must name identical fidelity holdings: an agent
    # that boots cheap on `index` then deepens to `connected`/`full` over MCP never sees the
    # held-fidelity counts shift under it. The deeper tiers additionally carry a drift verdict
    # the `index` line withholds (H214/H219) — that asymmetry stays intact, the tie is on the
    # *fidelity* section alone.
    from scrolls.custody import custody_counts_by_source, get_fidelity
    from scrolls.items import ScrollItem, insert_item, list_items, update_item

    main(["init"])
    db = get_paths().db_path
    # web spans three tiers (full 2, partial 1, reference 1 → 4 held); one out-of-scope
    # arxiv `full` lifts the library-wide audit to {full 3, …}, so web's scope is a strict
    # subset of — and a different tier split than — the whole library (scoping is
    # non-vacuous). Every title carries "topic" so one query matches all of web's held
    # items (no truncation: web holds 4 < the default limit, so each tier's post-facet set
    # *is* the whole web scope — the H241 precondition; H242 is the truncated boundary).
    def _web(item_id, title, **kw):
        kw.setdefault("stage", "fetched")
        return ScrollItem(
            id=item_id, source="web", url=f"https://web.example/{item_id}",
            saved_at="2026-06-12T00:00:00+00:00", title=title, **kw)

    insert_item(db, _web("web:full1", "Topic full one",
                         extracted_text="topic one body",
                         raw_text="<raw>topic one</raw>", content_hash="sha256:f1"))
    insert_item(db, _web("web:full2", "Topic full two",
                         extracted_text="topic two body",
                         raw_text="<raw>topic two</raw>", content_hash="sha256:f2"))
    insert_item(db, _web("web:partial", "Topic partial",
                         extracted_text="topic partial body"))  # no hash/raw → partial
    insert_item(db, _web("web:ref", "Topic reference pointer",
                         stage="detected"))  # no content → reference
    insert_item(db, ScrollItem(
        id="arxiv:1", source="arxiv", url="https://arxiv.org/abs/1",
        saved_at="2026-06-12T00:00:00+00:00", title="Topic arxiv paper", stage="fetched",
        extracted_text="topic", raw_text="<raw>topic</raw>", content_hash="sha256:a"))

    def _nonzero(counts):
        return {tier: n for tier, n in counts.items() if n}

    def _fidelity_counts(line):
        # tier words (full/partial/reference) never collide with the `(of N)`/`N scroll(s)`
        # scalars or the drift-posture words, so one parse reads either the `_Fidelity:_`
        # holdings line or the `_Custody:_` headline's `fidelity` section.
        return {t: int(n) for t, n in re.findall(r"(full|partial|reference) (\d+)", line)}

    def tier_picture():
        # the three budget tiers an agent boots over MCP, scoped to web. `index` carries the
        # ledger-free `_Fidelity:_` holdings line; `connected`/`full` carry the `_Custody:_`
        # headline whose `fidelity` section folds the same counts via a *different* renderer.
        bundles = {
            b: mcp_server.get_context_bundle("topic", budget=b, source="web")
            for b in ("index", "connected", "full")
        }
        index_line = next(
            l for l in bundles["index"].splitlines() if l.startswith("_Fidelity:"))
        counts = {"index": _fidelity_counts(index_line)}
        for b in ("connected", "full"):
            headline = next(
                l for l in bundles[b].splitlines() if l.startswith("_Custody:"))
            counts[b] = _fidelity_counts(headline)
        scope_n = int(re.search(r"\(of (\d+)\)", index_line).group(1))
        return bundles, counts, scope_n

    bundles, counts, scope_n = tier_picture()
    # non-vacuous: web's scope is a genuine multi-tier mix (≥2 non-zero tiers)
    assert counts["index"] == {"full": 2, "partial": 1, "reference": 1}
    # the precondition holds: the query matched all of web's held items, so the `index`
    # line's `(of N)` names the whole scoped held set — no truncation (H242 is the boundary).
    assert scope_n == sum(counts["index"].values()) == 4
    # the tie: the leanest `_Fidelity:_` holdings ≡ both deeper `_Custody:_` headlines'
    # `fidelity` section, all read over MCP — two renderers (`render_fidelity_holdings` vs.
    # `render_custody_headline`) over one scoped post-facet set, so the budget ladder never
    # disagrees *with itself* on what fraction of the source is held in full.
    assert counts["index"] == counts["connected"] == counts["full"]

    # the drift-withholding asymmetry stays intact (H214/H219): the leanest `index` tier
    # reads no ledger, so it carries no `_Custody:_` headline and no drift verdict; the
    # deeper tiers do. The cross-tier tie is on the *fidelity* section alone, never a drift
    # claim the leanest tier didn't read.
    assert "_Custody:" not in bundles["index"]
    assert "drift" not in bundles["index"]
    for b in ("connected", "full"):
        headline = next(
            l for l in bundles[b].splitlines() if l.startswith("_Custody:"))
        assert "drift unverified 4" in headline

    # tied to the shared per-source primitive too, not independently hardcoded — every tier
    # folds `get_fidelity` over the same scoped subset the per-source tally folds over.
    web_tiers = _nonzero(custody_counts_by_source(list_items(db), {})["web"]["tiers"])
    assert counts["index"] == web_tiers

    # the scope genuinely narrows: the *unscoped* MCP audit names the whole library (arxiv's
    # `full` lifts it to {full 3, …}), so no tier silently reverts to the library-wide
    # holdings it didn't see.
    whole = _nonzero(mcp_server.get_library_health()["tiers"])
    assert whole == {"full": 3, "partial": 1, "reference": 1}
    assert counts["index"] != whole

    # mutation in lockstep — drop `web:full1`'s re-derivable body (raw_text + hash) so it
    # falls `full` → `partial`. The shift must register identically on all three MCP budget
    # tiers, proving each recomputes `get_fidelity` over the scoped set rather than echoing
    # a cache or a single shared count snapshot.
    full1 = next(it for it in list_items(db) if it.id == "web:full1")
    assert update_item(db, dataclasses.replace(full1, raw_text=None, content_hash=None))
    mutated = next(it for it in list_items(db) if it.id == "web:full1")
    assert get_fidelity(mutated) == "partial"  # the dropped body cost it a tier

    _, counts, scope_n = tier_picture()
    assert counts["index"] == {"full": 1, "partial": 2, "reference": 1}  # the shift
    assert scope_n == 4                                                  # still whole web scope
    assert counts["index"] == counts["connected"] == counts["full"]      # in lockstep on all 3


def test_get_context_bundle_budget_ladder_stays_equal_under_truncation_over_mcp(
    scrolls_home,
):
    # roadmap H242 — the *MCP twin of H240* (and the truncated boundary of H241).
    # H241 ties `index` ≡ `connected` ≡ `full` over MCP *untruncated* (the deeper-tier
    # cross-rendering tie under scope); H236 pins only the leanest `index` `_Fidelity:_`
    # line diverging from `get_library_health(source=<S>)`'s `tiers` under truncation over
    # MCP. The untested cell is the *deeper* MCP tiers under a cap:
    # `get_context_bundle(query, budget="connected"/"full", source=<S>)`'s `_Custody:_`
    # headline renders its `fidelity` section via `render_custody_headline` — a *different*
    # function than the `index` line's `render_fidelity_holdings` — yet all three fold over
    # the *same* post-cap kept set (`build_context` applies `limit` at `search_items`
    # regardless of budget). So under truncation the three MCP budget tiers must stay
    # mutually *equal* (all bundle-kept, summing to the kept slice `k`) even as all three
    # *together* diverge from the scoped MCP audit (summing to the held count > k) — the
    # MCP budget ladder never disagrees *with itself* on holdings under a cap, and never
    # inflates the bundle-kept holdings to a source-wide claim. Lifting the cap (`limit` ≥
    # held) reconverges all three to the H241/H235 scoped MCP equality, completing the
    # leanest/cross-tier × untruncated/truncated × CLI/MCP fidelity-convergence matrix.
    from scrolls.custody import custody_counts_by_source, get_fidelity
    from scrolls.items import ScrollItem, insert_item, list_items

    main(["init"])
    db = get_paths().db_path
    # web spans three tiers (full 2, partial 1, reference 1 → 4 held); one out-of-scope
    # arxiv `full` lifts the library-wide audit to {full 3, …}, so web's source-wide audit
    # is a third, distinct number from both the bundle-kept count and the library-wide
    # holdings — `source="web"` is genuinely exercised. Every title carries "topic" so one
    # query matches all of web's held items (truncation is then forced only by the cap).
    def _web(item_id, title, **kw):
        kw.setdefault("stage", "fetched")
        return ScrollItem(
            id=item_id, source="web", url=f"https://web.example/{item_id}",
            saved_at="2026-06-12T00:00:00+00:00", title=title, **kw)

    insert_item(db, _web("web:full1", "Topic full one",
                         extracted_text="topic one body",
                         raw_text="<raw>topic one</raw>", content_hash="sha256:f1"))
    insert_item(db, _web("web:full2", "Topic full two",
                         extracted_text="topic two body",
                         raw_text="<raw>topic two</raw>", content_hash="sha256:f2"))
    insert_item(db, _web("web:partial", "Topic partial",
                         extracted_text="topic partial body"))  # no hash/raw → partial
    insert_item(db, _web("web:ref", "Topic reference pointer",
                         stage="detected"))  # no content → reference
    insert_item(db, ScrollItem(
        id="arxiv:1", source="arxiv", url="https://arxiv.org/abs/1",
        saved_at="2026-06-12T00:00:00+00:00", title="Topic arxiv paper", stage="fetched",
        extracted_text="topic", raw_text="<raw>topic</raw>", content_hash="sha256:a"))

    def _nonzero(counts):
        return {tier: n for tier, n in counts.items() if n}

    def _fidelity_counts(line):
        # tier words (full/partial/reference) never collide with the `(of N)`/`N scroll(s)`
        # scalars or the drift-posture words, so one parse reads either the `_Fidelity:_`
        # holdings line or the `_Custody:_` headline's `fidelity` section.
        return {t: int(n) for t, n in re.findall(r"(full|partial|reference) (\d+)", line)}

    def ladder(limit):
        # the three budget tiers an agent boots over MCP, scoped to web, at a given cap.
        # `index` carries the ledger-free `_Fidelity:_` holdings line; `connected`/`full`
        # carry the `_Custody:_` headline whose `fidelity` section folds the same counts via
        # a *different* renderer. All three see the one post-cap kept set.
        bundles = {
            b: mcp_server.get_context_bundle("topic", budget=b, source="web", limit=limit)
            for b in ("index", "connected", "full")
        }
        index_line = next(
            l for l in bundles["index"].splitlines() if l.startswith("_Fidelity:"))
        counts = {"index": _fidelity_counts(index_line)}
        for b in ("connected", "full"):
            headline = next(
                l for l in bundles[b].splitlines() if l.startswith("_Custody:"))
            counts[b] = _fidelity_counts(headline)
        scope_n = int(re.search(r"\(of (\d+)\)", index_line).group(1))
        return bundles, counts, scope_n

    # the canonical *whole-source* audit over MCP: `get_library_health(source="web")` folds
    # `get_fidelity` over all four held web rows, independent of any query or cap.
    source_tiers = _nonzero(mcp_server.get_library_health(source="web")["tiers"])
    assert source_tiers == {"full": 2, "partial": 1, "reference": 1}  # ≥2 tiers, non-vacuous
    held = sum(source_tiers.values())
    assert held == 4
    # tied to the shared per-source primitive too, not independently hardcoded
    web_tiers = _nonzero(custody_counts_by_source(list_items(db), {})["web"]["tiers"])
    assert source_tiers == web_tiers

    # --- under truncation: a cap below the source's held count ----------------------
    cap = 2
    assert cap < held  # the cap genuinely truncates web's matching items (4 > 2)
    bundles, capped, scope_n = ladder(cap)
    # the three MCP budget tiers stay mutually *equal* under the cap — the leanest
    # `_Fidelity:_` holdings line, and the `connected`/`full` `_Custody:_` headlines, all
    # fold over the one post-cap kept set, so the budget ladder never disagrees *with
    # itself* on what it holds in full.
    assert capped["index"] == capped["connected"] == capped["full"]
    # and all three sum to the kept slice `k`, never the whole-source held count; the
    # `index` line's `(of N)` agrees (a *this-bundle* fact over `len(items)`).
    assert scope_n == cap == 2
    assert sum(capped["index"].values()) == cap == 2
    # so the whole MCP ladder *together* diverges from the source-wide audit: no tier — not
    # the leanest, not the deeper ones — inflates the bundle-kept holdings to a source-wide
    # custody claim it didn't render.
    for budget in ("index", "connected", "full"):
        assert capped[budget] != source_tiers
        assert sum(capped[budget].values()) < sum(source_tiers.values())

    # the drift-withholding asymmetry stays intact under truncation too (H214/H219): the
    # leanest `index` tier reads no ledger, so it carries no `_Custody:_` headline and no
    # drift verdict; the deeper tiers carry one — and *their* drift count is also over the
    # kept set (the 2 kept items, all unverified), so the deeper tiers stay honest about the
    # bundle scope on the drift axis as well as the fidelity one.
    assert "_Custody:" not in bundles["index"]
    assert "drift" not in bundles["index"]
    for b in ("connected", "full"):
        headline = next(
            l for l in bundles[b].splitlines() if l.startswith("_Custody:"))
        assert "drift unverified 2" in headline  # over the kept slice, not web's held 4

    # --- lift the cap: the whole MCP ladder reconverges to the H241/H235 equality ----
    # `limit` ≥ the source's held count keeps every matching web item, so the post-cap kept
    # set *is* the whole web scope the audit folds over — index ≡ connected ≡ full ≡ the
    # scoped MCP audit, all four equal again (the gap was exactly the cap, nothing else).
    _, lifted, scope_n = ladder(held)  # cap == 4 == held → no truncation
    assert scope_n == held == 4
    assert lifted["index"] == lifted["connected"] == lifted["full"] == source_tiers

    # the `source="web"` filter is non-vacuous on every read: the *unscoped* MCP audit names
    # the whole library (arxiv's `full` lifts it), so neither the bundle-kept ladder nor the
    # source-wide audit is ever the library-wide holdings.
    whole = _nonzero(mcp_server.get_library_health()["tiers"])
    assert whole == {"full": 3, "partial": 1, "reference": 1}
    assert source_tiers != whole
    for budget in ("index", "connected", "full"):
        assert capped[budget] != whole
    # sanity: `get_fidelity` is the shared fold under every surface (web:ref is the
    # reference tier the audit and the lifted ladder both name).
    ref = next(it for it in list_items(db) if it.id == "web:ref")
    assert get_fidelity(ref) == "reference"


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


# --- get_library_health: the whole-library custody audit over MCP (H161) ---


def _seed_health_fixture(db):
    """Two sources spanning the fidelity tiers and drift postures.

    `web` carries the only actionable loss (one drifted), so it is the
    unambiguous weakest source the `attention` flag must name; `arxiv` is clean.
    """
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    def _item(item_id, source, url, **kw):
        kw.setdefault("stage", "fetched")
        return ScrollItem(
            id=item_id, source=source, url=url,
            saved_at="2026-06-12T00:00:00+00:00", title=f"Topic {item_id}", **kw)

    insert_item(db, _item("web:full", "web", "https://ex.com/full",
                          extracted_text="b", raw_text="<r>b</r>", content_hash="sha256:f"))
    insert_item(db, _item("web:drift", "web", "https://ex.com/drift",
                          extracted_text="b", raw_text="<r>b</r>", content_hash="sha256:d"))
    insert_item(db, _item("web:ref", "web", "https://ex.com/ref", stage="detected"))
    insert_item(db, _item("arxiv:1", "arxiv", "https://arxiv.org/abs/1",
                          extracted_text="b", raw_text="<r>b</r>", content_hash="sha256:a"))
    record_events(db, [
        CustodyEvent("web:full", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:f", "sha256:f", None),
        CustodyEvent("web:drift", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:d", "sha256:changed", None),
    ])


def test_get_library_health_returns_the_doctor_custody_block(scrolls_home):
    # the tool is exactly `run_doctor`'s custody block plus the two distilled
    # members `status` adds — no new derivation, the doctor-shaped whole-library read.
    from scrolls.custody import weakest_source
    from scrolls.doctor import run_doctor
    from scrolls.maintain import custody_snapshot, snapshot_headline

    main(["init"])
    db = get_paths().db_path
    _seed_health_fixture(db)

    health = mcp_server.get_library_health()
    report = run_doctor(get_paths())
    custody = report["custody"]

    # every custody-block key is carried verbatim
    for key in custody:
        assert health[key] == custody[key]
    # the fixture's non-trivial mix is reproduced (not an all-zero pass)
    assert health["tiers"] == {"full": 3, "partial": 0, "reference": 1}
    assert health["drift"]["unchanged"] == 1
    assert health["drift"]["drifted"] == 1
    assert health["drift"]["unverified"] == 2  # web:ref + arxiv:1, never checked
    # the two distilled members, via the same shared primitives `status` uses
    assert health["attention"] == weakest_source(custody["by_source"])
    assert health["attention"]["source"] == "web"
    assert health["attention"]["command"] == "scrolls verify --source web"
    assert health["headline"] == snapshot_headline(custody_snapshot(report))


def test_get_library_health_carries_the_at_risk_works_alarm(scrolls_home):
    # the H263 consolidation alarm rides the MCP doctor twin for free (it is part of
    # the custody block `get_library_health` spreads), so an agent operating purely
    # over MCP reads "which works have no safe representation" — convergent with the
    # CLI `doctor` by construction.
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.doctor import run_doctor
    from scrolls.items import ScrollItem, insert_item

    main(["init"])
    db = get_paths().db_path

    def rep(item_id, doi, tier):
        f = dict(id=item_id, source=item_id.split(":")[0],
                 source_id=item_id.split(":", 1)[1], url=f"https://example.org/{item_id}",
                 saved_at="2026-06-14T00:00:00+00:00",
                 links=(f"https://doi.org/{doi}",), stage="rendered")
        if tier == "full":
            f.update(extracted_text="body", content_hash=f"sha256:{item_id}")
        return ScrollItem(**f)

    for item in [rep("arxiv:z", "10.3000/z", "reference"),
                 rep("crossref:cz", "10.3000/z", "reference"),
                 rep("arxiv:s", "10.4000/s", "full"),
                 rep("crossref:cs", "10.4000/s", "reference")]:
        insert_item(db, item)
    record_events(db, [
        CustodyEvent("arxiv:s", "2026-06-14T00:00:00+00:00", "unchanged", "h", "h"),
    ])

    works = mcp_server.get_library_health()["works"]
    # Z is at risk (all reference); S is safely held (full+verified preprint)
    assert works["status"] == "ok"
    assert works["at_risk"] == 1
    assert works["most_at_risk"]["doi"] == "10.3000/z"
    # exactly `doctor`'s custody.works block — no MCP-side re-derivation
    assert works == run_doctor(get_paths())["custody"]["works"]


def test_get_library_health_carries_the_content_duplicates_report(scrolls_home):
    # the H325 content-identity redundancy report rides the MCP doctor twin for free
    # (it is part of the custody block `get_library_health` spreads), so an agent over
    # MCP reads "which held items are byte-identical under different ids" — convergent
    # with the CLI `doctor` by construction, no MCP-side re-derivation.
    from scrolls.doctor import run_doctor
    from scrolls.items import ScrollItem, insert_item, make_item_id

    main(["init"])
    db = get_paths().db_path
    for url in ("https://example.com/a", "https://example.com/b"):
        insert_item(db, ScrollItem(
            id=make_item_id("web", None, url), source="web", source_id=None, url=url,
            saved_at="2026-06-14T00:00:00+00:00", stage="fetched",
            extracted_text="same body", content_hash="sha256:dup"))

    dup = mcp_server.get_library_health()["content_duplicates"]
    assert dup["status"] == "ok"
    assert dup["total_groups"] == 1
    assert dup["total_items"] == 2
    assert dup["groups"][0]["content_hash"] == "sha256:dup"
    # exactly `doctor`'s custody.content_duplicates block — one fold, two surfaces
    assert dup == run_doctor(get_paths())["custody"]["content_duplicates"]


def test_get_library_health_matches_cli_status_field_for_field(scrolls_home, capsys):
    # MCP↔CLI parity: the tool's by_source/attention/score/tiers/headline equal a
    # `scrolls status` over the same seed — one custody picture, two surfaces.
    import json

    main(["init"])
    db = get_paths().db_path
    _seed_health_fixture(db)
    capsys.readouterr()

    health = mcp_server.get_library_health()

    assert main(["status"]) == 0
    status = json.loads(capsys.readouterr().out)

    assert health["by_source"] == status["by_source"]
    assert health["attention"] == status["attention"]
    assert health["headline"] == status["headline"]
    assert health["score"] == status["custody"]["score"]
    assert health["tiers"] == status["custody"]["tiers"]


def test_get_library_health_before_init_is_the_honest_empty_block(scrolls_home):
    # honest absence: an uninitialized library is the present-but-empty custody
    # block (`score: null`, zeroed counts), never an error or a fabricated 100.
    health = mcp_server.get_library_health()
    assert health["score"] is None
    assert health["tiers"] == {"full": 0, "partial": 0, "reference": 0}
    assert health["by_source"] == {}
    assert health["attention"] is None
    assert health["headline"] == "_Custody: 0 scroll(s)._"


def test_get_library_health_empty_initialized_library_is_fully_custodied(scrolls_home):
    # an empty *initialized* library holds nothing, so it is trivially healthy:
    # score 100 (no held item is at risk), no source to flag.
    main(["init"])
    health = mcp_server.get_library_health()
    assert health["score"] == 100
    assert health["by_source"] == {}
    assert health["attention"] is None


def test_get_library_health_source_scopes_the_read_to_one_source(scrolls_home):
    # roadmap H167: `source=` scopes the whole custody read to one source's held
    # items, reusing the same `run_doctor(source=)` pre-filter the CLI
    # `doctor --source`/`status --source` (H162/H166) use — the MCP sibling of the
    # per-source scope. The scoped block *is* `run_doctor(paths, source=S)`'s custody
    # block plus the two distilled members, so it equals the whole-library audit's
    # `by_source[S]` slice; `by_source` collapses to the present-and-singleton.
    from scrolls.doctor import run_doctor
    from scrolls.maintain import custody_snapshot, snapshot_headline

    main(["init"])
    db = get_paths().db_path
    _seed_health_fixture(db)

    health = mcp_server.get_library_health(source="web")
    scoped = run_doctor(get_paths(), source="web")["custody"]

    # every custody-block key is carried verbatim from the scoped audit
    for key in scoped:
        assert health[key] == scoped[key]
    # the one-source view: only web's items (full ×2 + the reference pointer),
    # by_source the singleton — arxiv:1 is excluded
    assert set(health["by_source"]) == {"web"}
    assert health["tiers"] == {"full": 2, "partial": 0, "reference": 1}
    assert health["drift"]["drifted"] == 1
    # the headline is the *scoped* block rendered; attention null on a single source
    assert health["headline"] == snapshot_headline(
        custody_snapshot(run_doctor(get_paths(), source="web"))
    )
    assert health["attention"] is None


def test_get_library_health_source_attention_is_null_under_a_single_source(scrolls_home):
    # under a single-source scope `attention` is naturally null with no special
    # casing — `by_source` is a singleton, so the `weakest_source` cross-source
    # gate (len < 2) returns None, exactly like CLI `status --source` (H166). The
    # whole-library read still flags web (the H139 max-loss source).
    main(["init"])
    _seed_health_fixture(get_paths().db_path)
    assert mcp_server.get_library_health()["attention"]["source"] == "web"
    assert mcp_server.get_library_health(source="web")["attention"] is None


def test_get_library_health_unknown_source_is_the_honest_empty_block(scrolls_home):
    # honest absence (H167, mirroring `doctor --source ghost`): an unknown source
    # holds nothing, so the scoped read is the empty-but-healthy block (score 100
    # over an initialized library, empty by_source, null attention) — never an error.
    main(["init"])
    _seed_health_fixture(get_paths().db_path)
    health = mcp_server.get_library_health(source="ghost")
    assert health["score"] == 100
    assert health["by_source"] == {}
    assert health["attention"] is None
    assert health["headline"] == "_Custody: 0 scroll(s)._"


def _seed_health_determinism_mix(paths):
    """A held mix where every order-sensitive sub-block of the MCP custody audit is
    non-vacuous, so the H381 byte-identity guards below are real claims (an all-empty
    payload would pass a mis-ordered fold too).

    Mirrors tests/test_doctor.py's `_seed_doctor_determinism_mix` (kept local —
    `tests/` is not a package), the H375 CLI `scrolls doctor` determinism fixture this
    MCP-surface guard is the sibling of:

    - **three sources** (web, arxiv, crossref) → a multi-key `by_source` map;
    - a **byte-identical content pair** under two ids → `content_duplicates.groups`;
    - a **drifted** full item that *also* carries an unresolved import **conflict**
      (disjoint ledger axes) → `drift.events` + `conflicts.events`;
    - a **tampered archived prior** → `archive.events` (one mismatched recovery row);
    - an **all-reference work** (two reference reps of one DOI) → `works.most_at_risk`.

    Every one is a list/map a set/dict-iteration leak would re-order between two reads —
    exactly what the cross-`PYTHONHASHSEED` pair catches. Structurally clean
    (`issues == 0`), so `get_library_health` is the honest custody audit.
    """
    import sqlite3

    from scrolls.custody import CustodyEvent, conflict_event, record_events
    from scrolls.items import ScrollItem, adopt_incoming, insert_item, make_item_id

    db = paths.db_path

    def _web(url, **overrides):
        fields = dict(id=make_item_id("web", None, url), source="web", source_id=None,
                      url=url, saved_at="2026-06-12T08:00:00+00:00")
        fields.update(overrides)
        return ScrollItem(**fields)

    def _rep(item_id, doi):  # an all-reference representation of a DOI work
        return ScrollItem(id=item_id, source=item_id.split(":")[0],
                          source_id=item_id.split(":", 1)[1],
                          url=f"https://example.org/{item_id}",
                          saved_at="2026-06-12T08:00:00+00:00",
                          links=(f"https://doi.org/{doi}",), stage="rendered")

    # a multi-source all-reference at-risk work (works.most_at_risk) — also the second
    # and third sources that make `by_source` a multi-key map
    insert_item(db, _rep("arxiv:z", "10.3000/z"))
    insert_item(db, _rep("crossref:cz", "10.3000/z"))
    # a byte-identical content pair under two ids (content_duplicates.groups)
    insert_item(db, _web("https://example.com/a", extracted_text="same body",
                         content_hash="sha256:dup", stage="fetched"))
    insert_item(db, _web("https://example.com/b", extracted_text="same body",
                         content_hash="sha256:dup", stage="fetched"))
    # a drifted full item that also carries an unresolved import conflict (the two
    # disjoint ledger axes — drift.events and conflicts.events both non-empty)
    drift = _web("https://example.com/drift", title="A Post", extracted_text="body",
                 content_hash="sha256:wd", stage="fetched")
    insert_item(db, drift)
    record_events(db, [
        CustodyEvent(item_id=drift.id, checked_at="2026-06-14T00:00:00+00:00",
                     status="drifted", prior_hash="sha256:wd",
                     observed_hash="sha256:changed"),
        conflict_event(drift.id, held_hash="sha256:wd", incoming_hash="sha256:incoming",
                       now="2026-06-15T00:00:00+00:00"),
    ])
    # a tampered archived prior (archive.events: one mismatched recovery row)
    held = _web("https://example.com/archived", title="A Post", extracted_text="body",
                content_hash="sha256:held", stage="fetched")
    insert_item(db, held)
    adopt_incoming(db, dataclasses.replace(held, extracted_text="a later capture",
                                           content_hash="sha256:moved"),
                   archived_at="2026-06-22T00:00:00+00:00")
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("UPDATE item_archive SET prior_hash = ? WHERE item_id = ?",
                     ("sha256:tampered", held.id))
    conn.close()


def _assert_health_mix_is_non_vacuous(health):
    """Every order-sensitive MCP-audit sub-block is populated (an all-empty payload
    would pass a mis-ordered fold too), so the byte-identity claims below are real."""
    assert sorted(health["by_source"]) == ["arxiv", "crossref", "web"]
    assert health["content_duplicates"]["groups"]      # the byte-identical pair
    assert health["drift"]["events"]                   # the drifted item
    assert health["conflicts"]["events"]               # the unresolved conflict
    assert health["archive"]["events"]                 # the tampered prior
    assert health["works"]["most_at_risk"] is not None  # the all-reference work


def test_get_library_health_is_byte_identical_across_two_same_process_reads(scrolls_home):
    # roadmap H381: two `get_library_health` reads of one unchanged library serialize
    # to byte-identical JSON — the *agent-facing* custody audit (the MCP twin of
    # `scrolls doctor`, H161) is a reproducible artifact, not a per-run snapshot. The
    # MCP-surface sibling of H375's CLI `scrolls doctor` determinism: H375 pinned the
    # CLI `print(json.dumps(run_doctor(...)))` path, but an agent driving MCP reads a
    # *separate serialization* (`get_library_health` re-keys the `run_doctor` report
    # through the MCP tool envelope — it spreads the custody block and adds
    # `attention`/`headline`, a distinct code path). This is the same-process face; the
    # cross-seed pair below catches the set-iteration leak this one — under a single
    # fixed hash seed — structurally cannot.
    from scrolls.doctor import run_doctor

    main(["init"])
    _seed_health_determinism_mix(get_paths())

    first = mcp_server.get_library_health()
    second = mcp_server.get_library_health()

    _assert_health_mix_is_non_vacuous(first)
    # the determinism guard rides the H186/H180 registered-twin shape contract: the
    # payload is exactly `run_doctor`'s custody block carried verbatim plus the two
    # distilled members `status` adds — no MCP-side re-derivation that could de-sync.
    custody = run_doctor(get_paths())["custody"]
    for key in custody:
        assert first[key] == custody[key]
    assert set(first) == set(custody) | {"attention", "headline"}
    assert mcp_server.get_library_health in mcp_server._TOOLS

    assert json.dumps(first) == json.dumps(second)


def test_get_library_health_is_deterministic_across_hash_seeds(scrolls_home, tmp_path):
    # roadmap H381: `get_library_health` emits a byte-identical serialized payload
    # across two processes with *different* `PYTHONHASHSEED`s — the cross-process face
    # the same-process pair structurally cannot see. The decisive half of the guard: a
    # `set` leaking into any sub-block fold in the MCP path (an unsorted by_source /
    # conflicts / archive / drift / works ordering, or an envelope keyed off a
    # set-derived map) iterates the *same* way twice under one fixed seed, so the
    # same-process read above stays green over it; only two processes seeded
    # differently surface the divergence. The H375 `scrolls doctor` cross-seed
    # precedent lifted to the MCP audit-twin surface.
    import os
    import shutil
    import subprocess
    import sys

    main(["init"])
    _seed_health_determinism_mix(get_paths())

    # two homes with the same seeded DB — each subprocess audits its own copy under its
    # own hash seed (the H375 / H363 copytree precedent)
    home_a = tmp_path / "home-a"
    home_b = tmp_path / "home-b"
    shutil.copytree(scrolls_home, home_a)
    shutil.copytree(scrolls_home, home_b)

    def _health(home, seed):
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys, json; from scrolls.mcp_server import get_library_health; "
             "sys.stdout.write(json.dumps(get_library_health()))"],
            env={**os.environ, "SCROLLS_HOME": str(home), "PYTHONHASHSEED": seed},
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    out_a = _health(home_a, "0")  # hash randomization off
    out_b = _health(home_b, "1")  # a different fixed seed

    # non-vacuity: the subprocess really produced the populated audit (not an early
    # empty return), so the byte-identity is a real claim.
    _assert_health_mix_is_non_vacuous(json.loads(out_a))

    assert out_a == out_b


# --- get_link_graph determinism over MCP (H387) ---
#
# H381 pinned the *audit* twin (`get_library_health`) and H382 the *bundle* twin
# (`get_context_bundle`) as reproducible MCP artifacts. This is the *structural* twin:
# an agent driving MCP over the H201/H204 dogfood loop caches `get_link_graph` — its
# whole-link-structure view — and re-fetches to detect "did the library's structure
# move?". `get_link_graph` folds the relatedness/link-graph engine (`build_graph` →
# `graph_payload`), a *distinct code path* from the `run_doctor` audit those twins wrap,
# so no existing determinism test pins it. If that fold leaks set-iteration order into
# its node list, its edge list, or the `stats.custody.by_source` map (or the envelope
# keys off a set-derived map), two calls of one unchanged library disagree byte-for-byte
# and the agent cries structural drift where there is none. The twentieth
# forward-hardening cell and the fourth MCP-surface determinism twin (after H381/H382/
# H383); deliberately *not* another content-identity guard.


def _seed_link_graph_determinism_mix(db):
    """A library whose link graph is wide enough that every order-sensitive section of
    the MCP `get_link_graph` payload is a multi-element fold, so the H387 byte-identity
    guards below are real claims (a one-node / one-source graph would pass a mis-ordered
    fold too). Built so:

    - **four sources** (x, arxiv, crossref, web) → `stats.custody.by_source` is a
      multi-key map (the per-source custody split, sorted keys);
    - a **link chain across sources** — an `x` thread → an `arxiv` preprint → its
      `crossref` published record (the arxiv item's `doi.org` link resolves to the
      crossref `source_id`) — → a multi-edge `edges` list spanning three sources;
    - a **byte-identical content pair** under two `web` ids, mutually linked → both are
      *nodes*, each carries a non-empty `content_duplicate_ids` list (the per-node
      content-identity fold, roadmap H343), and the pair adds two more edges;
    - the arxiv preprint left **drifted** (one recorded event) → the per-source `drift`
      tally is non-uniform across the four sources.

    Five connected nodes, four edges, a four-key `by_source` map — every list/map a
    set/dict-iteration leak would re-order between two reads, exactly what the
    cross-`PYTHONHASHSEED` pair catches. The local link-graph sibling of
    `_seed_health_determinism_mix` (`tests/` is not a package).
    """
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.items import ScrollItem, insert_item

    # an x thread → arxiv preprint → crossref published record (a three-source chain)
    insert_item(db, ScrollItem(
        id="x:9001", source="x", url="https://x.com/u/status/9001",
        saved_at="2026-06-12T00:00:00+00:00", title="a thread on the paper",
        links=("https://arxiv.org/abs/2605.99",), stage="fetched"))
    insert_item(db, ScrollItem(
        id="arxiv:2605.99", source="arxiv", url="https://arxiv.org/abs/2605.99",
        saved_at="2026-06-12T00:00:00+00:00", title="A Preprint",
        raw_text="<r>preprint</r>", extracted_text="preprint body",
        content_hash="sha256:pp", stage="rendered",
        links=("https://doi.org/10.1234/lg",)))
    insert_item(db, ScrollItem(
        id="crossref:10.1234/lg", source="crossref",
        url="https://doi.org/10.1234/lg", canonical_url="https://doi.org/10.1234/lg",
        source_id="10.1234/lg", saved_at="2026-06-12T00:00:00+00:00",
        title="The Published Record", raw_text="<r>published</r>",
        extracted_text="published body", content_hash="sha256:pub", stage="rendered"))
    # a byte-identical web pair, mutually linked so both become nodes (and each names
    # the other in content_duplicate_ids — the per-node content-identity fold)
    insert_item(db, ScrollItem(
        id="web:a", source="web", url="https://ex.com/a",
        saved_at="2026-06-12T00:00:00+00:00", title="A copy",
        raw_text="<raw>body</raw>", extracted_text="body", content_hash="sha256:dup",
        stage="rendered", links=("https://ex.com/b",)))
    insert_item(db, ScrollItem(
        id="web:b", source="web", url="https://ex.com/b",
        saved_at="2026-06-12T01:00:00+00:00", title="A byte-identical copy",
        raw_text="<raw>body</raw>", extracted_text="body", content_hash="sha256:dup",
        stage="rendered", links=("https://ex.com/a",)))
    # the arxiv preprint drifted out from under us → a non-uniform per-source drift tally
    record_events(db, [CustodyEvent(
        "arxiv:2605.99", "2026-06-14T00:00:00+00:00", "drifted",
        "sha256:pp", "sha256:moved", None)])


def _assert_link_graph_mix_is_non_vacuous(graph):
    """Every order-sensitive section of the MCP `get_link_graph` payload is a
    multi-element fold (a one-node / one-source graph would pass a mis-ordered fold
    too), so the byte-identity claims below are real."""
    assert len(graph["nodes"]) == 5            # the connected five-node structure
    assert len(graph["edges"]) == 4            # the chain (×2) + the mutual web pair
    by_source = graph["stats"]["custody"]["by_source"]
    assert set(by_source) == {"arxiv", "crossref", "web", "x"}  # multi-key map
    # the per-node content-identity fold is non-empty on the byte-identical web pair
    dup_ids = {n["id"]: n["content_duplicate_ids"] for n in graph["nodes"]}
    assert dup_ids["web:a"] == ["web:b"] and dup_ids["web:b"] == ["web:a"]
    assert graph["stats"]["custody"]["drift"]["drifted"] == 1   # the drifted preprint


def test_get_link_graph_is_byte_identical_across_two_same_process_reads(scrolls_home):
    # roadmap H387: two `get_link_graph()` reads of one unchanged library serialize to
    # byte-identical JSON — the *agent-facing* whole-link-structure view (the MCP twin
    # of `scrolls graph`) is a reproducible artifact, not a per-run snapshot. The
    # structural sibling of H381's `get_library_health` determinism: a *distinct code
    # path* (it folds the relatedness/link-graph engine `build_graph` → `graph_payload`,
    # not the `run_doctor` audit H381/H383 wrap), so no existing determinism test pins
    # it. This is the same-process face; the cross-seed pair below catches the
    # set-iteration leak this one — under a single fixed hash seed — structurally cannot.
    main(["init"])
    _seed_link_graph_determinism_mix(get_paths().db_path)

    first = mcp_server.get_link_graph()
    second = mcp_server.get_link_graph()

    _assert_link_graph_mix_is_non_vacuous(first)
    # the determinism guard rides the H186 MCP read-surface shape contract: the link
    # graph is a class-B stats-object twin (it carries `stats.custody.by_source`) and a
    # registered tool, so a future re-shaping that de-syncs it trips this too.
    assert mcp_server.get_link_graph in mcp_server._TOOLS
    assert set(first["stats"]["custody"]["by_source"]) == {"arxiv", "crossref", "web", "x"}

    assert json.dumps(first) == json.dumps(second)


def test_get_link_graph_is_deterministic_across_hash_seeds(scrolls_home, tmp_path):
    # roadmap H387: `get_link_graph()` emits a byte-identical serialized payload across
    # two processes with *different* `PYTHONHASHSEED`s — the cross-process face the
    # same-process pair structurally cannot see. The decisive half of the guard: a `set`
    # leaking into any fold in the link-graph path (the node list, the edge list, the
    # `by_source` map, or an envelope keyed off a set-derived map) iterates the *same*
    # way twice under one fixed seed, so the same-process read above stays green over it;
    # only two processes seeded differently surface the divergence. The H381/H375
    # cross-seed precedent lifted to the MCP structural-read twin.
    import os
    import shutil
    import subprocess
    import sys

    main(["init"])
    _seed_link_graph_determinism_mix(get_paths().db_path)

    # two homes with the same seeded DB — each subprocess folds its own copy under its
    # own hash seed (the H381 / H375 / H363 copytree precedent)
    home_a = tmp_path / "home-a"
    home_b = tmp_path / "home-b"
    shutil.copytree(scrolls_home, home_a)
    shutil.copytree(scrolls_home, home_b)

    def _graph(home, seed):
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys, json; from scrolls.mcp_server import get_link_graph; "
             "sys.stdout.write(json.dumps(get_link_graph()))"],
            env={**os.environ, "SCROLLS_HOME": str(home), "PYTHONHASHSEED": seed},
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    out_a = _graph(home_a, "0")  # hash randomization off
    out_b = _graph(home_b, "1")  # a different fixed seed

    # non-vacuity: the subprocess really produced the populated graph (not an early empty
    # return), so the byte-identity is a real claim.
    _assert_link_graph_mix_is_non_vacuous(json.loads(out_a))

    assert out_a == out_b


def _seed_refresh_debt(paths):
    """A two-source library carrying both stale-classification and stale-summary debt.

    Mirrors tests/test_cli.py's `_seed_refresh_debt` (kept local — `tests/` is not a
    package): stale classifications on arxiv (1) + web (2), each item one source so the
    enrichment map sums to the whole; stale summaries over a web+arxiv Bm25 cluster
    (attributes to BOTH) and a web-only Vector cluster — so `summary_by_source` is
    {arxiv:1, web:2} though only 2 summaries are stale (the H171 double-attribution
    asymmetry). Enough to make both per-source refresh-debt maps non-vacuous.
    """
    import dataclasses

    from scrolls.db import init_db
    from scrolls.items import ScrollItem, get_item, insert_item, make_item_id, update_item
    from scrolls.kb import ConceptSummary, save_concept_summary
    from scrolls.render import write_scroll

    def _member(source, slug, concept):
        return ScrollItem(
            id=make_item_id(source, None, f"https://{source}.example.com/{slug}"),
            source=source, source_id=None,
            url=f"https://{source}.example.com/{slug}",
            saved_at="2026-06-14T00:00:00+00:00", title=slug,
            extracted_text="A note about the concept.",
            content_hash="sha256:" + slug[-8:], concepts=(concept,), stage="rendered",
            provenance={"adapter": source, "fetched_at": "2026-06-14T00:00:05+00:00"})

    def _mark_stale(item_id):
        persisted = get_item(paths.db_path, item_id)
        update_item(paths.db_path, dataclasses.replace(persisted, provenance={
            **persisted.provenance, "classified_by": "rules-v1",
            "classified_basis": "title-pattern",
            "classified_ruleset": "deadbeef0000"}))  # superseded by the live ruleset

    def _store_stale_summary(slug, display):
        save_concept_summary(paths.db_path, ConceptSummary(
            slug=slug, display=display, summary="How it shows up.",
            members_hash="stale-old-digest", engine="kb-llm-v1",
            model="claude-opus-4-8", generated_at="2026-06-16T00:00:00+00:00"))

    paths.root.mkdir(parents=True, exist_ok=True)
    init_db(paths.db_path)
    members = [
        _member("web", "bm25-web", "Bm25"),
        _member("arxiv", "bm25-arxiv", "Bm25"),
        _member("web", "vector-1", "Vector"),
        _member("web", "vector-2", "Vector"),
    ]
    for item in members:
        insert_item(paths.db_path, write_scroll(paths, item))
    assert main(["kb"]) == 0
    _mark_stale(members[1].id)  # arxiv
    _mark_stale(members[0].id)  # web
    _mark_stale(members[2].id)  # web
    _store_stale_summary("bm25", "Bm25")
    _store_stale_summary("vector", "Vector")


def test_get_library_health_refresh_debt_equals_cli_status_flat_maps(scrolls_home, capsys):
    # roadmap H180: H177 hoisted the per-source refresh-debt maps to *flat* top-level
    # members on CLI `status` (`enrichment_by_source`/`summary_by_source`); the MCP
    # audit twin `get_library_health` deliberately carries the *fuller nested*
    # re-derivability blocks (`custody.enrichment`/`custody.summaries`, of which
    # `by_source` is one slice — beside `basis`/`stale`/`current`/`items`). This is the
    # H163-style "the MCP twin keeps its richer natural shape" call — the audit twin is
    # exactly `run_doctor`'s custody block, not a flattened projection. So the per-source
    # refresh debt is not lost over MCP, only nested: the flat CLI maps equal the nested
    # MCP maps by construction (both read `report["custody"][...]["by_source"]` off the
    # one `run_doctor` audit). This pins that flat≡nested convergence.
    import json

    paths = get_paths()
    _seed_refresh_debt(paths)
    capsys.readouterr()

    health = mcp_server.get_library_health()
    assert main(["status"]) == 0
    status = json.loads(capsys.readouterr().out)

    # non-vacuous: the seed makes concrete per-source debt on both axes
    assert status["enrichment_by_source"] == {"arxiv": 1, "web": 2}
    assert status["summary_by_source"] == {"arxiv": 1, "web": 2}

    # the flat CLI maps equal the nested MCP maps — same slice, one audit
    assert status["enrichment_by_source"] == health["enrichment"]["by_source"]
    assert status["summary_by_source"] == health["summaries"]["by_source"]

    # ...and the MCP twin carries the *fuller* re-derivability block the flat CLI member
    # is just one slice of — the richer nested shape the audit twin deliberately keeps
    # (the whole-library `stale` scalar + the `basis` fingerprint the flat map drops).
    assert health["enrichment"]["stale"] == 3  # sums to the whole (each item one source)
    assert health["enrichment"]["basis"] == "ruleset_fingerprint"
    assert health["summaries"]["basis"] == "members_hash"
    # the flat CLI payload carries only the by_source slice, not the nested block
    assert "enrichment" not in status
    assert "summaries" not in status


def test_get_library_health_source_scopes_the_refresh_debt(scrolls_home, capsys):
    # roadmap H180, the scoped sibling: `get_library_health(source=S)` (H167) scopes the
    # nested refresh-debt blocks to one source, equalling CLI `status --source S`'s flat
    # maps over the same scope — so an agent triaging the weakest source's refresh debt
    # over MCP reads the same per-source numbers the CLI does.
    import json

    paths = get_paths()
    _seed_refresh_debt(paths)
    capsys.readouterr()

    health = mcp_server.get_library_health(source="web")
    assert main(["status", "--source", "web"]) == 0
    status = json.loads(capsys.readouterr().out)

    assert status["enrichment_by_source"] == {"web": 2}
    assert status["enrichment_by_source"] == health["enrichment"]["by_source"]
    assert status["summary_by_source"] == health["summaries"]["by_source"]


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


# --- run_maintenance: the scheduled custody pass over MCP (H196) ---


def test_run_maintenance_returns_the_maintain_report_shape(scrolls_home):
    # H196: the MCP act wraps the shipped `maintain` engine, returning the same
    # report shape — custody/headline/delta/by_source/attention/the per-source
    # refresh-debt maps/suggested — as the CLI `scrolls maintain` pass.
    from scrolls.custody import weakest_source
    from scrolls.doctor import run_doctor
    from scrolls.maintain import custody_snapshot, snapshot_headline

    main(["init"])
    _seed_health_fixture(get_paths().db_path)

    report = mcp_server.run_maintenance()

    assert set(report) == {
        "recorded_at", "source", "fidelity", "recheck", "compiled", "custody",
        "headline", "at_risk_headline", "conflicts_headline",
        "archive_integrity_headline", "duplicates_headline", "posture_headline",
        "by_source", "attention", "at_risk_works",
        "enrichment_by_source",
        "summary_by_source", "delta", "issues", "suggested", "duplicate_prunes",
    }
    # whole-library and offline by default: the recheck is the one live network
    # edge (behind the `live_recapture` seam), and an MCP tool must not trigger
    # implicit re-captures — so the MCP path defaults to --no-recheck (regenerate
    # + audit + delta + record), leaving targeted live rechecks to `verify_scroll`.
    assert report["source"] is None
    assert report["recheck"]["skipped"] is True
    assert report["recheck"]["scope"] is None
    # the custody picture reproduces the fixture's mix (not an all-zero pass) and
    # equals the doctor audit + the shared distillation primitives `status` uses.
    audit = run_doctor(get_paths())
    assert report["custody"] == custody_snapshot(audit)
    assert report["headline"] == snapshot_headline(custody_snapshot(audit))
    assert report["attention"] == weakest_source(audit["custody"]["by_source"])
    assert report["attention"]["source"] == "web"


def test_run_maintenance_records_the_snapshot_and_log(scrolls_home):
    # H196: like the CLI pass, the MCP act records this run's snapshot (the next
    # delta baseline) and appends to the append-only trend log — idempotent,
    # report-only bookkeeping (the custody-ledger posture, custody-vision §2.4).
    from scrolls.maintain import load_snapshot, log_path, read_log, snapshot_path

    main(["init"])
    _seed_health_fixture(get_paths().db_path)

    first = mcp_server.run_maintenance()
    assert first["delta"]["first_run"] is True
    snap = load_snapshot(snapshot_path(get_paths()))
    assert snap is not None and "recorded_at" in snap
    assert len(read_log(log_path(get_paths()))) == 1

    # a second pass sees the first as its baseline (no longer a first run) and the
    # log grows by one — the append-only trend posture, never a rewrite.
    second = mcp_server.run_maintenance()
    assert second["delta"]["first_run"] is False
    assert len(read_log(log_path(get_paths()))) == 2


def test_run_maintenance_before_init_is_the_honest_empty_pass(scrolls_home):
    # honest before-init (H196): an uninitialized library is the honest-empty pass
    # — score null (never a fabricated 100), the zero-scroll headline — never a crash.
    report = mcp_server.run_maintenance()
    assert report["custody"]["score"] is None
    assert report["headline"] == "_Custody: 0 scroll(s)._"
    assert report["by_source"] == {}
    assert report["attention"] is None
    assert report["issues"] == 0


def test_run_maintenance_converges_with_cli_maintain_no_recheck(scrolls_home, capsys):
    # H196 MCP↔CLI parity: the tool's report equals `scrolls maintain --no-recheck`
    # over the same seed, field for field (modulo the per-run `recorded_at` stamp) —
    # one maintenance pass, two surfaces.
    import json

    from scrolls.maintain import snapshot_path

    main(["init"])
    _seed_health_fixture(get_paths().db_path)
    capsys.readouterr()

    report_mcp = mcp_server.run_maintenance()

    # the MCP pass recorded a snapshot; drop it so the CLI pass is also a first run
    # over the *same* (recheck-free, hence unchanged) custody state — the two reports
    # then differ only in their `recorded_at` timestamps.
    snapshot_path(get_paths()).unlink()
    assert main(["maintain", "--no-recheck"]) == 0
    report_cli = json.loads(capsys.readouterr().out)

    assert set(report_mcp) == set(report_cli)
    for key in report_cli:
        if key == "recorded_at":
            continue
        assert report_mcp[key] == report_cli[key], f"diverged on {key}"


# --- run_maintenance determinism + no-movement settle over MCP (H383) ---
#
# H377 pinned the CLI `scrolls maintain --no-recheck` path both settles (two passes
# over an unchanged library record byte-equal scalars, the second's delta is
# no-movement) and reproduces across `PYTHONHASHSEED`. But an agent driving MCP never
# calls the CLI — it calls `run_maintenance`, which passes a `skipped_recheck_report`
# (no live edge, H196) and returns the same `assemble_report` through the MCP tool
# envelope (a *distinct entry point* + serialization no determinism/settle test pins).
# An MCP-driven dogfood loop (H201/H204) that re-fetches `run_maintenance` to detect
# custody movement reads the *MCP* payload: if that twin re-folds a snapshot/headline
# section over a `set`, or its envelope phantom-moves a delta, two calls of one
# unchanged library disagree and the agent cries drift where there is none. The
# sixteenth forward-hardening cell — the MCP-surface twin of H377's CLI settle/
# determinism; deliberately *not* another content-identity guard.
#
# These helpers replicate tests/test_maintain.py's H377 fixture + assertions locally
# (`tests/` is not a package), the same way `_seed_health_determinism_mix` (H381)
# replicates the doctor determinism mix.


def _maintain_determinism_item(item_id, title, **overrides):
    """One held scroll for `_seed_maintain_determinism_mix` — `web`/`fetched` by
    default, every field overridable (the H377 `_maintain_determinism_item` shape)."""
    from scrolls.items import ScrollItem

    base = dict(
        id=item_id, source="web", url=f"https://example.com/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00", title=title, stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def _seed_maintain_determinism_mix(db):
    """The H377 non-vacuous custody mix, seeded for a `run_maintenance` pass: every
    load-bearing snapshot scalar is non-zero, so the settle / determinism guards below
    are real claims (an all-zeros library would pass a phantom-delta or a mis-ordered
    fold too). A local replica of tests/test_maintain.py's `_seed_maintain_determinism_mix`
    (`tests/` is not a package), the CLI fixture this MCP-surface twin is the sibling of:

    - a **byte-identical content pair** (two `full` ids sharing one `content_hash`)
      → `content_duplicate_groups == 1`, `content_duplicate_items == 2`;
    - the pair's first member classified against a **stale ruleset** → `enrichment_stale`;
    - a **drifted** `full` item that *also* carries an unresolved import **conflict**
      (disjoint ledger axes) → `drift.drifted` + `conflicts`;
    - the pair's other member re-checked clean → `drift.unchanged` + recheck `coverage`;
    - a `partial` item → the `partial` tier;
    - an **all-reference work** (two reference reps of one DOI) → `works.at_risk` and
      the `reference` tier;
    - the worst custody band any axis fires → a `posture` verdict of `at_risk` with
      multiple `reasons` (the comma-joined render a reasons set-leak would re-order).
    """
    from scrolls.custody import CustodyEvent, conflict_event, record_events
    from scrolls.items import insert_item

    # byte-identical content pair; dup1 is also stale-classified (enrichment_stale)
    insert_item(db, _maintain_determinism_item(
        "web:dup1", "Topic full one", category="tutorial",
        extracted_text="topic one body", raw_text="<raw>topic one</raw>",
        content_hash="sha256:dup",
        provenance={"classified_by": "rules-v1", "classified_basis": "weak-source",
                    "classified_ruleset": "deadbeef0000"}))  # stale ruleset
    insert_item(db, _maintain_determinism_item(
        "web:dup2", "Topic full two",
        extracted_text="topic two body", raw_text="<raw>topic two</raw>",
        content_hash="sha256:dup"))
    # a drifted full item that also carries an unresolved import conflict
    insert_item(db, _maintain_determinism_item(
        "web:drift", "Topic drift",
        extracted_text="topic drift body", raw_text="<raw>topic drift</raw>",
        content_hash="sha256:wd"))
    insert_item(db, _maintain_determinism_item(
        "web:partial", "Topic partial", extracted_text="topic partial body"))  # partial
    # an all-reference work: two reference reps of the same DOI, no full copy
    insert_item(db, _maintain_determinism_item(
        "arxiv:workz", "Topic arxiv z", source="arxiv",
        url="https://arxiv.org/abs/workz", links=("https://doi.org/10.3000/z",),
        stage="rendered"))
    insert_item(db, _maintain_determinism_item(
        "crossref:workz", "Topic crossref z", source="crossref",
        url="https://example.org/crossref-workz",
        links=("https://doi.org/10.3000/z",), stage="rendered"))
    record_events(db, [
        CustodyEvent("web:dup1", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:dup", "sha256:dup", None),
        CustodyEvent("web:drift", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:wd", "sha256:changed", None),
        # disjoint conflict axis: an import disagreed with the held copy, unresolved
        conflict_event("web:drift", held_hash="sha256:wd",
                       incoming_hash="sha256:incoming", now="2026-06-15T00:00:00+00:00"),
    ])


def _no_movement_delta(delta):
    """Assert a `compute_delta` result is the all-zero / no-movement shape every axis:
    a present baseline (`first_run` False), every numeric `change` zero, the categorical
    posture band steady (`changed` False). Walks *every* axis (scalar and per-key
    mapping), so a phantom `+1` injected anywhere is caught, not just `score` (the H377
    `_no_movement_delta`)."""
    assert delta["first_run"] is False
    assert delta["posture"]["changed"] is False
    for axis, value in delta.items():
        if axis in ("first_run", "since", "posture"):
            continue
        changes = (
            [value["change"]] if "change" in value
            else [sub["change"] for sub in value.values()]
        )
        assert all(change == 0 for change in changes), (axis, changes)


def _comparable_snapshot(snapshot):
    """A recorded snapshot minus its wall-clock `recorded_at` — the comparable custody
    scalars two passes of one unchanged library must reproduce exactly (the H377 helper)."""
    return {key: value for key, value in snapshot.items() if key != "recorded_at"}


_RUN_MAINTENANCE_SHAPE = {
    "recorded_at", "source", "fidelity", "recheck", "compiled", "custody",
    "headline", "at_risk_headline", "conflicts_headline",
    "archive_integrity_headline", "duplicates_headline", "posture_headline",
    "by_source", "attention", "at_risk_works", "enrichment_by_source",
    "summary_by_source", "delta", "issues", "suggested", "duplicate_prunes",
}


def _assert_run_maintenance_mix_is_non_vacuous(report):
    """Every order-sensitive / movement-bearing snapshot scalar is non-zero (an
    all-zeros pass would settle past a phantom delta and mis-order a fold the same),
    so the settle / byte-identity claims below are real."""
    custody = report["custody"]
    assert custody["score"] == 100
    assert custody["tiers"] == {"full": 3, "partial": 1, "reference": 2}
    assert custody["drift"]["drifted"] == 1
    assert custody["drift"]["unchanged"] == 1
    assert custody["enrichment_stale"] == 1
    assert custody["at_risk"] == 1
    assert custody["conflicts"] == 1
    assert custody["content_duplicate_groups"] == 1
    assert custody["content_duplicate_items"] == 2
    assert custody["posture"]["verdict"] == "at_risk"
    assert len(custody["posture"]["reasons"]) >= 2  # the comma-joined render axis
    assert report["at_risk_works"]["at_risk"] == 1
    assert report["issues"] == 0


def test_run_maintenance_settles_to_a_no_movement_delta(scrolls_home):
    # roadmap H383 (the settle face): two `run_maintenance()` passes over one unchanged
    # library record the *same* comparable custody scalars, and the second pass's delta
    # vs the first's baseline is the all-zero / no-movement shape on every axis — so an
    # MCP-driven worker reads "nothing moved", never a phantom drift. Every MCP pass is
    # offline (`--no-recheck`, H196), so it never mutates the ledger; the only thing
    # varying between passes is the wall-clock `recorded_at`. The value-based face a
    # single fixed hash seed catches; the cross-seed pair below catches the
    # iteration-order leak this one structurally cannot (a `set` iterates the same way
    # twice under one fixed seed). The MCP-surface twin of H377's CLI `scrolls maintain`
    # settle.
    from scrolls.maintain import compute_delta, load_snapshot, snapshot_path

    main(["init"])
    _seed_maintain_determinism_mix(get_paths().db_path)

    first = mcp_server.run_maintenance()
    snapshot_one = load_snapshot(snapshot_path(get_paths()))

    second = mcp_server.run_maintenance()
    snapshot_two = load_snapshot(snapshot_path(get_paths()))

    # non-vacuity: every order-sensitive / movement-bearing scalar is non-zero, so the
    # settle below is a real claim (an all-zeros snapshot would settle past a phantom
    # delta too).
    _assert_run_maintenance_mix_is_non_vacuous(first)
    # the first pass has no baseline; the second sees the first as its baseline — so a
    # no-movement second delta is a real settle, not a vacuous first run.
    assert first["delta"]["first_run"] is True
    assert second["delta"]["first_run"] is False

    # the recorded snapshot settles: two passes over the unchanged library record
    # byte-equal comparable scalars (only `recorded_at` may differ) …
    assert _comparable_snapshot(snapshot_one) == _comparable_snapshot(snapshot_two)
    # … and so does the report's distilled `custody` block (the snapshot the MCP
    # envelope carries — a phantom move in the MCP path would diverge here).
    assert first["custody"] == second["custody"]

    # the delta between the two recorded snapshots is the no-movement shape …
    _no_movement_delta(compute_delta(snapshot_one, snapshot_two))
    # … as is the *production* delta the second MCP pass reported vs the first's
    # baseline (the very figure the agent reads — a stray `+1` in the MCP delta fails
    # here while the same-process determinism stays green).
    _no_movement_delta(second["delta"])

    # the guard rides the H186/H180 registered-twin shape contract: the MCP pass is a
    # registered tool returning the documented report shape, so the settle is pinned to
    # the same surface the per-tool shape tests lock.
    assert mcp_server.run_maintenance in mcp_server._TOOLS
    assert set(first) == _RUN_MAINTENANCE_SHAPE


def test_run_maintenance_payload_is_deterministic_across_hash_seeds(scrolls_home, tmp_path):
    # roadmap H383 (the determinism face): `run_maintenance()` emits a byte-identical
    # serialized payload (minus the wall-clock `recorded_at`) across two processes
    # seeded with *different* `PYTHONHASHSEED`s — the decisive half the same-process
    # settle structurally cannot see. A `set` leaking into any snapshot/headline fold in
    # the MCP path (the posture `reasons` order, `by_source`, the `at_risk_works`/
    # `duplicate_prunes` lists) iterates the *same* way twice under one fixed seed, so
    # the settle above stays green over it; only two differently-seeded processes
    # surface the re-ordering. The H377 CLI cross-seed precedent lifted to the MCP
    # scheduled-maintenance twin (the MCP envelope + serialization the CLI test never
    # exercises). Each subprocess runs one pass on its own fresh copy (a `first_run`,
    # the same delta shape on both), so the whole payload bar `recorded_at` is identical.
    import os
    import shutil
    import subprocess
    import sys

    main(["init"])
    _seed_maintain_determinism_mix(get_paths().db_path)

    # two homes with the same seeded DB — each subprocess runs its own pass under its
    # own hash seed (the H381 / H375 / H363 copytree precedent)
    home_a = tmp_path / "home-a"
    home_b = tmp_path / "home-b"
    shutil.copytree(scrolls_home, home_a)
    shutil.copytree(scrolls_home, home_b)

    def _maintain(home, seed):
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys, json; from scrolls.mcp_server import run_maintenance; "
             "sys.stdout.write(json.dumps(run_maintenance()))"],
            env={**os.environ, "SCROLLS_HOME": str(home), "PYTHONHASHSEED": seed},
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    out_a = _maintain(home_a, "0")  # hash randomization off
    out_b = _maintain(home_b, "1")  # a different fixed seed

    report_a = json.loads(out_a)
    report_b = json.loads(out_b)

    # non-vacuity: the subprocess really produced the populated maintenance report (not
    # an early skipped/empty return), so the byte-identity is a real claim.
    _assert_run_maintenance_mix_is_non_vacuous(report_a)
    assert len(report_a["custody"]["posture"]["reasons"]) >= 2

    # the whole MCP payload is reproducible bar the one wall-clock field — a set/dict
    # leak anywhere (snapshot scalar, readable headline, by-source map, prune guidance,
    # or the envelope itself) would diverge across the two seeds.
    report_a.pop("recorded_at")
    report_b.pop("recorded_at")
    assert json.dumps(report_a) == json.dumps(report_b)


# --- run_maintenance(source=): the source-scoped custody pass over MCP (H203) ---


def test_run_maintenance_source_scopes_the_pass_to_one_source(scrolls_home):
    # H203: an agent that has just read `get_library_health`'s `attention` flag
    # (the weakest source) runs a scoped maintenance pass on *that* source via the
    # `source=` arg — the MCP sibling of CLI `scrolls maintain --source <S>` (H165),
    # threaded into the shipped source-aware `skipped_recheck_report`/`assemble_report`
    # seams. Every reported block is the one-source view; offline like every MCP pass.
    from scrolls.doctor import run_doctor
    from scrolls.maintain import custody_snapshot, snapshot_headline

    main(["init"])
    _seed_health_fixture(get_paths().db_path)

    report = mcp_server.run_maintenance(source="web")

    # the shape is the whole-library report's; only the scope narrows
    assert set(report) == {
        "recorded_at", "source", "fidelity", "recheck", "compiled", "custody",
        "headline", "at_risk_headline", "conflicts_headline",
        "archive_integrity_headline", "duplicates_headline", "posture_headline",
        "by_source", "attention", "at_risk_works",
        "enrichment_by_source",
        "summary_by_source", "delta", "issues", "suggested", "duplicate_prunes",
    }
    assert report["source"] == "web"
    # offline, the H196 posture — an MCP pass never triggers an implicit re-capture
    assert report["recheck"]["skipped"] is True
    # the scoped custody view == the scoped doctor audit distilled (convergence by
    # construction: the same `run_doctor(source=)` pre-filter the CLI scoped pass uses)
    scoped = run_doctor(get_paths(), source="web")
    assert report["custody"] == custody_snapshot(scoped)
    assert report["headline"] == snapshot_headline(report["custody"])
    # the one-source view: only web's items (full ×2 + the reference pointer),
    # by_source collapses to the present-and-singleton (arxiv excluded)
    assert set(report["by_source"]) == {"web"}
    assert report["custody"]["tiers"] == {"full": 2, "partial": 0, "reference": 1}
    assert report["custody"]["drift"]["drifted"] == 1
    # attention is null under a single-source scope (nothing to flag across), the
    # `get_library_health(source=)` H167 / weakest_source single-source gate
    assert report["attention"] is None


def test_run_maintenance_source_is_non_persisting(scrolls_home):
    # H203 custody safety: a scoped pass must not clobber the single whole-library
    # snapshot/log baseline with a one-source slice (no per-source storage shape,
    # ADR 0082) — so its `delta` is honestly null and the recorded trend is untouched.
    from scrolls.maintain import load_snapshot, log_path, read_log, snapshot_path

    main(["init"])
    _seed_health_fixture(get_paths().db_path)

    # one whole-library MCP pass records the single baseline + first log entry
    mcp_server.run_maintenance()
    baseline = load_snapshot(snapshot_path(get_paths()))
    assert baseline is not None
    assert len(read_log(log_path(get_paths()))) == 1

    # a scoped pass: delta null, and the baseline/log are untouched afterwards
    report = mcp_server.run_maintenance(source="web")
    assert report["delta"] is None
    assert load_snapshot(snapshot_path(get_paths())) == baseline  # not clobbered
    assert len(read_log(log_path(get_paths()))) == 1  # no scoped run appended


def test_run_maintenance_source_converges_with_cli_maintain_source(scrolls_home, capsys):
    # H203 MCP↔CLI parity: the scoped tool's report equals `scrolls maintain
    # --source web --no-recheck` over the same seed, field for field (modulo the
    # per-run `recorded_at` stamp). A scoped pass writes no snapshot, so unlike the
    # whole-library convergence test there is nothing to drop between the two passes.
    import json

    main(["init"])
    _seed_health_fixture(get_paths().db_path)
    capsys.readouterr()

    report_mcp = mcp_server.run_maintenance(source="web")

    assert main(["maintain", "--source", "web", "--no-recheck"]) == 0
    report_cli = json.loads(capsys.readouterr().out)

    assert set(report_mcp) == set(report_cli)
    for key in report_cli:
        if key == "recorded_at":
            continue
        assert report_mcp[key] == report_cli[key], f"diverged on {key}"


def test_run_maintenance_unknown_source_is_an_honest_empty_pass(scrolls_home):
    # H203 honest absence: an unknown source holds nothing → the honest empty pass
    # (zero-scroll headline, null attention/delta, empty by_source), never an error
    # — the `get_library_health(source=ghost)` H167 mirror, sources being open-ended.
    main(["init"])
    _seed_health_fixture(get_paths().db_path)

    report = mcp_server.run_maintenance(source="ghost")
    assert report["source"] == "ghost"
    assert report["headline"] == "_Custody: 0 scroll(s)._"
    assert report["by_source"] == {}
    assert report["attention"] is None
    assert report["delta"] is None
    assert report["recheck"]["coverage"] == {"verified": 0, "total": 0}


# --- get_maintenance_history: the custody trend over MCP, the read sibling of
#     run_maintenance (H198) ---


def test_get_maintenance_history_before_init_is_the_honest_empty_array(scrolls_home):
    # H198 honest absence: a never-maintained / uninitialized library is the
    # bare `[]` — never a fabricated run, never an error — the read sibling of
    # run_maintenance's honest-empty pass and the MCP twin of `maintain --history`.
    assert mcp_server.get_maintenance_history() == []
    # the opt-in trend envelope's own honest absence: a window of <2 runs has no
    # direction, so an empty runs array and the `insufficient-history` posture.
    envelope = mcp_server.get_maintenance_history(trend=True)
    assert envelope["runs"] == []
    assert envelope["trend"]["posture"] == "insufficient-history"


def test_get_maintenance_history_returns_the_recorded_runs(scrolls_home):
    # H198: after maintenance passes the read returns the recorded runs oldest-first
    # — the custody trajectory run_maintenance records and this reads back. Each run
    # carries its `{recorded_at, snapshot, delta}` plus the one-line `headline`
    # rendered fresh from its snapshot at read time (the H103 forward-compat posture).
    from scrolls.maintain import snapshot_headline

    main(["init"])
    _seed_health_fixture(get_paths().db_path)
    mcp_server.run_maintenance()
    mcp_server.run_maintenance()

    runs = mcp_server.get_maintenance_history()
    assert len(runs) == 2
    assert all(
        {"recorded_at", "snapshot", "delta", "headline"} <= set(run) for run in runs
    )
    assert runs[0]["headline"] == snapshot_headline(runs[0]["snapshot"])
    # `limit` bounds the window to the most recent N (the CLI `--history N` parity);
    # the default `limit=None` is the full history (read_log's own default).
    assert mcp_server.get_maintenance_history(limit=1) == runs[-1:]


def test_get_maintenance_history_matches_cli_maintain_history(scrolls_home, capsys):
    # H198 MCP↔CLI parity: the tool returns `scrolls maintain --history` field for
    # field (the same `read_log` + per-run `snapshot_headline` composition), and
    # `trend=True` returns the `{trend, runs}` envelope `--history --trend` prints —
    # the opt-in-envelope parity, so the bare-array completeness `[]` never regresses.
    import json

    main(["init"])
    _seed_health_fixture(get_paths().db_path)
    mcp_server.run_maintenance()
    mcp_server.run_maintenance()
    capsys.readouterr()

    assert main(["maintain", "--history"]) == 0
    cli_runs = json.loads(capsys.readouterr().out)
    assert mcp_server.get_maintenance_history() == cli_runs

    assert main(["maintain", "--history", "--trend"]) == 0
    cli_trend = json.loads(capsys.readouterr().out)
    assert mcp_server.get_maintenance_history(trend=True) == cli_trend


def _hold_content_pair(db, ids, content_hash):
    """Hold a byte-identical content-duplicate pair (one new H325 group)."""
    from scrolls.items import ScrollItem, insert_item

    for ident in ids:
        insert_item(db, ScrollItem(
            id=ident, source="web", url=f"https://ex.com/{ident}",
            saved_at="2026-06-12T00:00:00+00:00", title=ident,
            extracted_text="body", raw_text="<raw>body</raw>",
            content_hash=content_hash, stage="rendered"))


def _log_a_content_duplicate_trajectory(db):
    """Record two whole-library passes whose content-duplicate count climbs 1 → 2
    groups (2 → 4 items) — a known content-identity trajectory for the trend axis."""
    _hold_content_pair(db, ("web:a", "web:b"), "sha256:dup1")
    mcp_server.run_maintenance()  # pass 1: 1 group / 2 items
    _hold_content_pair(db, ("web:c", "web:d"), "sha256:dup2")
    mcp_server.run_maintenance()  # pass 2: 2 groups / 4 items


def test_get_maintenance_history_trend_carries_content_identity_at_cli_parity(
    scrolls_home, capsys
):
    # H335: the content-identity trend axis (H330) rides `get_maintenance_history(
    # trend=True)` — `content_duplicates_change` + the trend `duplicates_headline`
    # — at byte-parity with CLI `maintain --history --trend`. H330 put the axis on
    # the shared `compute_trend` and the MCP twin already calls it, so the keys flow
    # through for free; this pins that they actually converge over a *real logged
    # window* with a known content-duplicate trajectory (the keyset/parity tests
    # predate H330). The MCP path is offline by default (`--no-recheck`), so the CLI
    # comparison reads the *same* recorded log (one `read_log` + `compute_trend`).
    main(["init"])
    db = get_paths().db_path
    _log_a_content_duplicate_trajectory(db)

    trend = mcp_server.get_maintenance_history(trend=True)["trend"]
    # the net first→last group movement: 1 → 2 groups across the window.
    assert trend["content_duplicates_change"] == 1
    # the readable trend twin of the report's `_Duplicates:_` line: the last run's
    # 2 groups / 4 items + the ▲ movement clause, the window span "over 2 runs".
    assert trend["duplicates_headline"] == (
        "_Duplicates: 2 group(s) of byte-identical content (4 item(s)) "
        "(▲1 over 2 runs)._"
    )

    # byte-parity with CLI `maintain --history --trend` on the content-identity
    # axis (the H247/H242 MCP-twin convergence discipline) — the whole envelope is
    # equal, and so are the two content-identity members in particular.
    capsys.readouterr()
    assert main(["maintain", "--history", "--trend"]) == 0
    cli_trend = json.loads(capsys.readouterr().out)["trend"]
    assert mcp_server.get_maintenance_history(trend=True)["trend"] == cli_trend
    assert trend["content_duplicates_change"] == cli_trend["content_duplicates_change"]
    assert trend["duplicates_headline"] == cli_trend["duplicates_headline"]


def test_get_maintenance_history_content_identity_trend_moves_with_the_log(
    scrolls_home, capsys
):
    # H335 mutation guard: perturbing one logged snapshot's `content_duplicate_groups`
    # moves both surfaces in lockstep — proof the parity above is non-vacuous (both
    # read the same `read_log`, neither hard-codes the count). Rewrite the *first*
    # logged run's group scalar 1 → 5 so the net first→last movement flips from a ▲1
    # rise to a ▼3 fall, then re-read both surfaces: they agree, and they moved.
    from scrolls.maintain import log_path

    main(["init"])
    db = get_paths().db_path
    _log_a_content_duplicate_trajectory(db)

    before = mcp_server.get_maintenance_history(trend=True)["trend"]
    assert before["content_duplicates_change"] == 1  # the unperturbed ▲1 rise

    path = log_path(get_paths())
    lines = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["snapshot"]["content_duplicate_groups"] = 5
    lines[0] = json.dumps(first)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    after = mcp_server.get_maintenance_history(trend=True)["trend"]
    # the surface moved with the log (5 → 2 groups now reads a ▼3 fall, not ▲1)
    assert after["content_duplicates_change"] == -3
    assert after["duplicates_headline"] == (
        "_Duplicates: 2 group(s) of byte-identical content (4 item(s)) "
        "(▼3 over 2 runs)._"
    )

    # and the CLI moved in lockstep — both read the same edited log
    capsys.readouterr()
    assert main(["maintain", "--history", "--trend"]) == 0
    cli_after = json.loads(capsys.readouterr().out)["trend"]
    assert after["content_duplicates_change"] == cli_after["content_duplicates_change"]
    assert after["duplicates_headline"] == cli_after["duplicates_headline"]


# --- the cross-run posture-movement clause over MCP (roadmap H372) ----------


def _hold_clean_web_item(db, item_id, content_hash="sha256:held"):
    """Hold one clean web capture (the H372 MCP fixture's `sound` baseline)."""
    from scrolls.items import ScrollItem, insert_item

    insert_item(db, ScrollItem(
        id=item_id, source="web", url=f"https://ex.com/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00", title=item_id,
        extracted_text="body", raw_text="<raw>body</raw>",
        content_hash=content_hash, stage="rendered"))


def test_run_maintenance_posture_movement_clause_rides_the_mcp_report(
    scrolls_home, capsys
):
    # H372: the cross-run posture-movement clause (`sound → attention`) rides the MCP
    # `run_maintenance` report (H196 reuses `assemble_report`, so the clause flows for
    # free), and the windowed verdict movement rides `get_maintenance_history(
    # trend=True)` — both at CLI parity. Pass 1 holds a clean capture → `sound`; an
    # unresolved import conflict (soft, `open_conflicts`) then moves the band on pass 2.
    from scrolls.custody import conflict_event, record_events

    main(["init"])
    db = get_paths().db_path
    _hold_clean_web_item(db, "web:demo")

    first = mcp_server.run_maintenance()  # pass 1: a clean held capture → sound
    assert first["custody"]["posture"]["verdict"] == "sound"
    assert first["posture_headline"] == "_Posture: sound._"  # first run, no baseline

    # a peer capture disagreed with the held copy (raw is sacred, never overwritten):
    # the unresolved conflict is the soft `open_conflicts` axis → the band moves attention
    record_events(db, [conflict_event(
        "web:demo", held_hash="sha256:held", incoming_hash="sha256:peer",
        now="2026-06-15T00:00:00+00:00")])
    second = mcp_server.run_maintenance()  # pass 2: the band moved sound → attention
    assert second["custody"]["posture"]["verdict"] == "attention"
    assert second["delta"]["posture"] == {"before": "sound", "after": "attention",
                                          "changed": True}
    assert second["posture_headline"] == (
        "_Posture: attention (open_conflicts) (sound → attention since last run)._"
    )

    # the windowed verdict movement rides the trend twin, at CLI parity (the H335
    # content-identity-trend MCP precedent on the posture axis)
    trend = mcp_server.get_maintenance_history(trend=True)["trend"]
    assert trend["posture_change"] == {"first": "sound", "last": "attention",
                                       "changed": True}
    assert trend["posture_headline"] == (
        "_Posture: attention (open_conflicts) (sound → attention over 2 runs)._"
    )
    capsys.readouterr()
    assert main(["maintain", "--history", "--trend"]) == 0
    cli_trend = json.loads(capsys.readouterr().out)["trend"]
    assert trend["posture_change"] == cli_trend["posture_change"]
    assert trend["posture_headline"] == cli_trend["posture_headline"]


# ---------------------------------------------------------------------------
# The MCP read-surface determinism contract (roadmap H388)
#
# One guard over the *whole* registered read surface, superseding the per-tool
# determinism-twin treadmill (the shipped H381/H382/H383/H387 cells and the
# queued per-tool H389–H393 cells). Every read tool an agent caches over the
# H201/H204 dogfood loop must be a *reproducible artifact*: two reads of one
# unchanged library agree byte-for-byte, same-process AND across a
# `PYTHONHASHSEED` subprocess pair (the set-iteration leak a single fixed seed
# cannot surface — a `set` iterates the same way twice in one process, so only
# two differently-seeded processes reveal a leaked fold).
#
# Rather than hand-write one determinism cell per tool forever, this pins the
# invariant once over `_MCP_READ_TOOLS` and carries a *completeness* assertion:
# a new read tool added to the registry fails the contract until it is given a
# call here, forcing determinism coverage by construction. That is the M2
# search-completeness / H364 registry-completeness contract lifted to the
# determinism axis — the mechanism that retires the treadmill.
# ---------------------------------------------------------------------------


# (tool name, positional args, kwargs) for every registered read tool, args
# resolved from `_seed_read_surface_determinism_mix`. The chosen args drive each
# tool's heaviest order-sensitive fold (the trend envelope, a multi-hit query,
# the full-budget bundle). The name set MUST equal `_MCP_READ_TOOLS` — the
# completeness keystone asserted below.
_READ_SURFACE_CALLS = (
    ("search_scrolls", ("database",), {}),
    ("list_scrolls", (), {}),
    ("list_facets", (), {}),
    ("get_scroll", ("arxiv:dba",), {}),
    ("get_scroll_history", ("web:hub",), {}),
    ("get_related_scrolls", ("arxiv:dba",), {}),
    ("get_link_graph", (), {}),
    ("get_works", (), {}),
    ("get_context_bundle", ("database",), {"budget": "full"}),
    ("get_concept_page", ("Database",), {}),
    ("get_tag_page", ("efficient",), {}),
    ("list_sources", (), {}),
    ("list_archived", (), {}),
    ("get_archived", ("web:archived",), {}),
    ("get_library_health", (), {}),
    ("get_maintenance_history", (), {"trend": True}),
    ("list_feed_subscriptions", (), {}),
)


def _seed_read_surface_determinism_mix(paths):
    """One wide library where every order-sensitive read-tool fold is non-vacuous.

    A single fixture that drives the *whole* read surface, so the byte-identity
    claims below are real (an all-empty payload passes a mis-ordered fold too):

    - **four sources** (arxiv, crossref, web, x) → a multi-key `by_source` map
      on `get_library_health`/`get_link_graph`/`list_sources`;
    - **three DOI-clustered works** (`get_works`): two with a full preprint + a
      reference DOI record, and a third all-reference work so `works.most_at_risk`
      is non-null;
    - **link edges** (`web:hub`, `arxiv:dbb`, `crossref:dba` all link to
      `arxiv:dba`'s URL) → a ≥3-node, ≥2-edge graph;
    - a **"Database" concept** with ≥3 members and an **"efficient" tag** with ≥3
      members → multi-element `get_concept_page`/`get_tag_page` renders;
    - a **byte-identical content pair** → `content_duplicates.groups`;
    - a **drifted** item carrying an unresolved **conflict** → `drift.events` +
      `conflicts.events` + a non-empty `get_scroll_history`;
    - a **tampered archived prior** → `archive.events` + `list_archived`/
      `get_archived` recovery reads.
    """
    import sqlite3

    from scrolls.custody import CustodyEvent, conflict_event, record_events
    from scrolls.items import ScrollItem, adopt_incoming, insert_item
    from scrolls.render import write_scroll

    db = paths.db_path

    def _item(ident, source, **overrides):
        sid = ident.split(":", 1)[1]
        fields = dict(
            id=ident, source=source, source_id=sid,
            url=f"https://{source}.example/{sid}",
            saved_at="2026-06-12T08:00:00+00:00", stage="rendered",
        )
        fields.update(overrides)
        return ScrollItem(**fields)

    def _render(item):
        # a rendered scroll file (markdown_path set) so the KB compiler folds it
        # into the concept/tag pages get_concept_page/get_tag_page read
        insert_item(db, write_scroll(paths, item))

    # --- three DOI-clustered works (get_works) -------------------------------
    # work A: a full preprint (the link-graph hub target, a Database/Indexing member)
    #         + a reference DOI record
    _render(_item(
        "arxiv:dba", "arxiv", title="Indexing in a database",
        raw_text="A database index keeps lookups fast.",
        extracted_text="A database index keeps lookups fast.",
        content_hash="sha256:dba", concepts=("Database", "Indexing"),
        tags=("efficient",), links=("https://doi.org/10.1000/db",)))
    insert_item(db, _item(
        "crossref:dba", "crossref",
        links=("https://doi.org/10.1000/db", "https://arxiv.example/dba")))
    # work B: a second full preprint (a Database member) + reference DOI record
    _render(_item(
        "arxiv:dbb", "arxiv", title="A database query engine",
        raw_text="A database query engine plans joins.",
        extracted_text="A database query engine plans joins.",
        content_hash="sha256:dbb", concepts=("Database",), tags=("efficient",),
        links=("https://doi.org/10.2000/db", "https://arxiv.example/dba")))
    insert_item(db, _item(
        "crossref:dbb", "crossref", links=("https://doi.org/10.2000/db",)))
    # work C: two reference reps of one DOI → an all-reference at-risk work
    insert_item(db, _item("arxiv:ref1", "arxiv", links=("https://doi.org/10.3000/db",)))
    insert_item(db, _item("crossref:ref2", "crossref", links=("https://doi.org/10.3000/db",)))

    # --- a web hub: a rendered search/concept/tag member that links into the graph
    _render(_item(
        "web:hub", "web", title="Database hub overview",
        raw_text="An overview of database tools.",
        extracted_text="An overview of database tools and indexing.",
        content_hash="sha256:hub", concepts=("Database", "Indexing"),
        tags=("efficient",), links=("https://arxiv.example/dba",)))
    # an x thread → a 4th source and a cross-source search hit
    insert_item(db, _item(
        "x:post", "x", title="A database thread",
        raw_text="A thread about database internals.",
        extracted_text="A thread about database internals.",
        content_hash="sha256:xp"))

    # --- a byte-identical content-duplicate pair (content_duplicates) ---------
    for ident in ("web:dup1", "web:dup2"):
        insert_item(db, _item(
            ident, "web", title="A duplicated note",
            extracted_text="same body", content_hash="sha256:dup", stage="fetched"))

    # --- a drifted item that also carries an unresolved conflict -------------
    record_events(db, [
        CustodyEvent(item_id="web:hub", checked_at="2026-06-14T00:00:00+00:00",
                     status="drifted", prior_hash="sha256:hub",
                     observed_hash="sha256:moved"),
        conflict_event("web:hub", held_hash="sha256:hub",
                       incoming_hash="sha256:incoming",
                       now="2026-06-15T00:00:00+00:00"),
    ])

    # --- a tampered archived prior (the archive.events integrity alarm, plus the
    #     list_archived / get_archived recovery reads) ------------------------
    held = _item("web:archived", "web", title="An archived note",
                 extracted_text="the prior body", content_hash="sha256:held",
                 stage="fetched")
    insert_item(db, held)
    adopt_incoming(db, dataclasses.replace(
        held, extracted_text="a later capture", content_hash="sha256:moved"),
        archived_at="2026-06-22T00:00:00+00:00")
    # tamper the recorded prior hash so doctor's archive integrity alarm fires —
    # the un-launderable recovery-mismatch row (the H381 health-mix precedent)
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("UPDATE item_archive SET prior_hash = ? WHERE item_id = ?",
                     ("sha256:tampered", held.id))
    conn.close()


def _prepare_read_surface_library():
    """init + seed + compile + two maintenance passes — the shared setup the
    determinism reads run against, so the compiled concept/tag pages, the verify
    ledger, the archive store, and a non-trivial maintenance trend all exist for
    every read tool (compile_library is offline; run_maintenance is --no-recheck
    over MCP, so this is network-free)."""
    main(["init"])
    _seed_read_surface_determinism_mix(get_paths())
    mcp_server.compile_library()  # concept/tag pages for get_concept_page/get_tag_page
    mcp_server.run_maintenance()  # two passes → a real custody trajectory for the trend
    mcp_server.run_maintenance()


def _assert_read_surface_mix_is_non_vacuous(results):
    """Every leak-prone read tool returned a multi-element fold, so the
    byte-identity claims are real (a mis-ordered empty fold would pass too)."""
    search = results["search_scrolls"]
    assert len(search) >= 3 and len({h["source"] for h in search}) >= 2
    assert len(results["list_scrolls"]) >= 8
    graph = results["get_link_graph"]
    assert len(graph["nodes"]) >= 3 and len(graph["edges"]) >= 2
    assert len(graph["stats"]["custody"]["by_source"]) >= 3
    assert len(results["get_works"]["works"]) >= 2
    assert results["get_related_scrolls"]  # arxiv:dba has neighbours
    health = results["get_library_health"]
    assert sorted(health["by_source"]) == ["arxiv", "crossref", "web", "x"]
    assert health["content_duplicates"]["groups"]
    assert health["drift"]["events"] and health["conflicts"]["events"]
    assert health["archive"]["events"]
    assert health["works"]["most_at_risk"] is not None
    history = results["get_maintenance_history"]
    assert len(history["runs"]) == 2
    assert history["trend"]["posture"] != "insufficient-history"
    assert results["get_scroll_history"]  # the drifted item's ledger
    assert results["list_archived"]["count"] >= 1
    # the compiled-page reads list their multi-element member folds
    concept_page = results["get_concept_page"]
    assert "Indexing in a database" in concept_page
    assert "A database query engine" in concept_page
    assert "A database hub" in concept_page or "Database hub" in concept_page
    assert "efficient" in results["get_tag_page"].casefold()


def _read_surface_results():
    """Call every read tool once and return {tool_name: payload}."""
    return {
        name: getattr(mcp_server, name)(*args, **kwargs)
        for name, args, kwargs in _READ_SURFACE_CALLS
    }


def test_mcp_read_surface_calls_cover_exactly_the_registered_read_tools():
    """The completeness keystone (roadmap H388): the determinism call list covers
    *exactly* `_MCP_READ_TOOLS`, so a new read tool fails this until it is given a
    determinism call — forcing reproducibility coverage by construction and
    retiring the per-tool twin treadmill. Also pins each named tool is a live
    registered tool (the H364 `_TOOLS ≡ build_server` invariant)."""
    covered = {name for name, _, _ in _READ_SURFACE_CALLS}
    assert covered == _MCP_READ_TOOLS, (
        f"determinism coverage drift: missing={_MCP_READ_TOOLS - covered}, "
        f"extra={covered - _MCP_READ_TOOLS}"
    )
    registered = {fn.__name__ for fn in mcp_server._TOOLS}
    assert covered <= registered


def test_mcp_read_surface_is_byte_identical_across_two_same_process_reads(scrolls_home):
    # roadmap H388: every registered read tool serializes to byte-identical output
    # across two reads of one unchanged library — the *whole agent-read surface* is a
    # reproducible artifact, pinned once. The same-process face; the cross-seed pair
    # below catches the set-iteration leak this one (under a single fixed hash seed)
    # structurally cannot.
    _prepare_read_surface_library()

    first = _read_surface_results()
    second = _read_surface_results()

    _assert_read_surface_mix_is_non_vacuous(first)
    for name, _, _ in _READ_SURFACE_CALLS:
        assert json.dumps(first[name]) == json.dumps(second[name]), f"{name} not stable"


def _read_surface_driver(sabotage_set_size=64):
    """A standalone driver (run under a fresh interpreter) that calls every read
    tool from the single source of truth `_READ_SURFACE_CALLS` and writes each
    payload as `name=<json>`. When `SCROLLS_DETERMINISM_SABOTAGE=<tool>` is set it
    wraps that tool's payload with a `list(set(...))` leak — an order that is fixed
    within one process but varies across `PYTHONHASHSEED`, the exact regression the
    cross-seed face exists to catch."""
    leak = "{'k%d' % i for i in range(" + str(sabotage_set_size) + ")}"
    return (
        "import sys, json, os\n"
        "from scrolls import mcp_server\n"
        "calls = " + repr(list(_READ_SURFACE_CALLS)) + "\n"
        "sabotage = os.environ.get('SCROLLS_DETERMINISM_SABOTAGE')\n"
        "parts = []\n"
        "for name, args, kwargs in calls:\n"
        "    result = getattr(mcp_server, name)(*args, **kwargs)\n"
        "    if name == sabotage:\n"
        "        result = {'_leak': list(" + leak + "), 'payload': result}\n"
        "    parts.append(name + '=' + json.dumps(result))\n"
        "sys.stdout.write(chr(10).join(parts))\n"
    )


def _run_read_surface(home, seed, *, sabotage=None):
    import os
    import subprocess
    import sys

    env = {**os.environ, "SCROLLS_HOME": str(home), "PYTHONHASHSEED": seed}
    if sabotage is not None:
        env["SCROLLS_DETERMINISM_SABOTAGE"] = sabotage
    result = subprocess.run(
        [sys.executable, "-c", _read_surface_driver()],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_mcp_read_surface_is_deterministic_across_hash_seeds(scrolls_home):
    # roadmap H388: the whole read surface emits byte-identical output across two
    # processes with *different* `PYTHONHASHSEED`s — the cross-process face the
    # same-process pair structurally cannot see. One subprocess pair covers every
    # registered read tool at once (the consolidation that retires the per-tool
    # cross-seed twins): a `set` leaking into *any* read fold iterates the same way
    # twice under one fixed seed, so the same-process read stays green over it; only
    # two differently-seeded processes surface the divergence.
    _prepare_read_surface_library()

    out_a = _run_read_surface(scrolls_home, "0")  # hash randomization off
    out_b = _run_read_surface(scrolls_home, "1")  # a different fixed seed

    # non-vacuity: the subprocess really produced the populated surface
    parsed = {
        line.split("=", 1)[0]: json.loads(line.split("=", 1)[1])
        for line in out_a.split("\n")
    }
    _assert_read_surface_mix_is_non_vacuous(parsed)
    assert {name for name, _, _ in _READ_SURFACE_CALLS} <= set(parsed)

    assert out_a == out_b


def test_mcp_read_surface_determinism_guard_has_teeth(scrolls_home):
    # roadmap H388 sabotage: a `set`-fold leaked into one read tool (`get_works`)
    # must (1) stay invisible to two reads under the *same* seed — proving the
    # cross-seed dimension is the load-bearing half, not redundant — and (2) be
    # caught by the cross-seed pair, proving the contract above is non-vacuous. So
    # the same set leak the per-tool twins each caught for one tool is caught here
    # for any read tool, by construction.
    _prepare_read_surface_library()

    same_seed_a = _run_read_surface(scrolls_home, "0", sabotage="get_works")
    same_seed_b = _run_read_surface(scrolls_home, "0", sabotage="get_works")
    # (1) a single fixed seed cannot see the leak — the same-process blind spot
    assert same_seed_a == same_seed_b

    cross_seed = _run_read_surface(scrolls_home, "1", sabotage="get_works")
    # (2) two differently-seeded processes do — the contract has teeth
    assert same_seed_a != cross_seed
