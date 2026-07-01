"""The truncation / scope-echo honesty contract (roadmap H420).

One completeness-asserted invariant — the twenty-seventh **contract-consolidation**
cell and the *truncation*-axis sibling of H414's could-not-check (G1) parity.
G1 pins empty != could-not-check; this pins a truncated page != the whole answer.

The claim, for every CLI read that carries the G2 `{scope, stats, results}`
truncation envelope (`search --stats`, `list --stats`, `related --stats`):

- `stats.matched` is the full in-scope count before the page cap, never just the
  number returned in this payload;
- `stats.truncated` is exactly `matched > returned`;
- `results` are exactly the top-`limit` prefix of the full ordered/ranked set.

The MCP browse twins stay array-only by design (H163); their per-source custody
picture rides object/audit twins instead. `works` / `get_works` are included as
the non-truncating stats-object sibling: their `stats` describe the whole reported
work scope and deliberately carry no page-truncation flag.

Two faces, following the H388/H394 contract-consolidation shape:

1. **The completeness keystone** — the stats-axis registry partitions the live CLI
   and MCP read registries, so a new paginated read fails until classified as a
   truncation-envelope surface, a non-truncating stats object, or a named
   no-stats/no-page surface.
2. **The truncation guard** — over one non-vacuous fixture where every truncation
   surface has more in-scope rows than the requested limit, the envelope's count,
   truncation boolean, and prefix rows are checked against the full uncapped read.

Test-only: the surfaces already compute these facts through `scope_envelope` and
shared count primitives. This file pins the family as one contract.
"""

import json

import pytest

import scrolls.cli as cli
import scrolls.mcp_server as mcp_server
from scrolls.cli import main
from scrolls.items import ScrollItem, insert_item, list_items
from scrolls.paths import get_paths
from scrolls.related import scored_related
from scrolls.search import search_items

# The live read registries the H394/H388 contracts hold to argparse / MCP.
from test_cli_determinism import _CLI_READ_PATHS  # noqa: E402
from test_mcp import _MCP_READ_TOOLS  # noqa: E402


_QUERY = "h420needle"
_ANCHOR = "web:h420-anchor"
_LIMIT = 2


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


def _item(item_id: str, title: str, *, saved_index: int, **overrides) -> ScrollItem:
    base = dict(
        id=item_id,
        source=item_id.split(":", 1)[0],
        source_id=item_id.split(":", 1)[1] if ":" in item_id else None,
        url=f"https://example.org/{item_id}",
        saved_at=f"2026-06-12T00:00:0{saved_index}+00:00",
        title=title,
        summary=f"{_QUERY} summary {saved_index}",
        extracted_text=f"{_QUERY} body {saved_index}",
        raw_text=f"raw {_QUERY} {saved_index}",
        content_hash=f"sha256:h420-{saved_index}",
        tags=("h420-shared",),
        category="note",
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def _seed_truncation_mix(db_path):
    """Five query/list matches and four related neighbours; one two-rep work.

    Every title carries `_QUERY`, so `search _QUERY` matches all five. Every row
    carries the shared tag, so the anchor has four related neighbours. Two rows
    share one DOI, so `works`/`get_works` expose a non-vacuous stats object.
    """
    rows = [
        _item(_ANCHOR, "H420 needle anchor", saved_index=0),
        _item("web:h420-b", "H420 needle web B", saved_index=1),
        _item("web:h420-c", "H420 needle web C", saved_index=2),
        _item(
            "arxiv:h420-paper",
            "H420 needle preprint",
            saved_index=3,
            source="arxiv",
            url="https://arxiv.org/abs/h420",
            links=("https://doi.org/10.4242/h420",),
        ),
        _item(
            "crossref:10.4242/h420",
            "H420 needle DOI record",
            saved_index=4,
            source="crossref",
            url="https://doi.org/10.4242/h420",
        ),
    ]
    for row in rows:
        insert_item(db_path, row)


def _cli_json(argv, capsys):
    assert main(argv) == 0
    return json.loads(capsys.readouterr().out)


def _ids(rows):
    return [row["id"] for row in rows]


# --- the stats-axis registry — the keystone ----------------------------------

_CLI_TRUNCATION_SURFACES = {"search", "list", "related"}
_CLI_NON_TRUNCATING_STATS = {"works"}
_CLI_NO_STATS_AXIS = {
    "facets": "aggregate vocabulary counts; no result page or truncation envelope",
    "graph": "whole-library graph object; stats describe the graph scope, not a page cap",
    "doctor": "audit report; no capped result page",
    "context": "Markdown artifact; coverage line pins its cap separately (H7/H366)",
    "status": "boot custody scalar, not a paginated read",
    "history": "per-item ledger timeline; `--limit` is a timeline window, not a browse page",
    "maintain": "maintenance history read; trend window pinned by H377",
    "archive list": "archive recovery index, not a custody browse page",
    "archive show": "archive recovery JSONL stream, not a paginated browse envelope",
    "show": "single-item inspect, no page",
}

_MCP_NON_TRUNCATING_STATS = {"get_works"}
_MCP_NO_STATS_AXIS = {
    "search_scrolls": "array-only browse twin by design (H163); CLI owns --stats",
    "list_scrolls": "array-only browse twin by design (H163); CLI owns --stats",
    "get_related_scrolls": "array-only browse twin by design (H163); CLI owns --stats",
    "list_facets": "aggregate vocabulary counts; no result page",
    "get_scroll": "single-item inspect, no page",
    "get_scroll_history": "per-item ledger timeline, not a browse page",
    "get_link_graph": "whole-library graph object; stats describe graph scope",
    "get_context_bundle": "Markdown-string artifact; coverage line pins its cap",
    "get_concept_page": "compiled Markdown page, not a stats envelope",
    "get_tag_page": "compiled Markdown page, not a stats envelope",
    "list_sources": "source roster, no page-truncation stats",
    "list_archived": "archive recovery index, not a custody browse page",
    "get_archived": "archive recovery JSONL stream, not a paginated browse envelope",
    "get_library_health": "audit report; no capped result page",
    "get_maintenance_history": "maintenance-ledger read; no browse page",
    "list_feed_subscriptions": "feed roster, no page-truncation stats",
}


def test_stats_axis_registry_partitions_the_live_read_surfaces():
    """A new read must declare whether it has a truncation stats contract.

    The registry is keyed to the H394/H388 live read registries. A future
    paginated read first fails there until registered, then fails here until it is
    placed in the truncation-envelope set, the non-truncating stats-object set, or
    a named no-stats/no-page exemption.
    """
    cli_reads = {" ".join(path) for path in _CLI_READ_PATHS}
    cli_classified = (
        _CLI_TRUNCATION_SURFACES | _CLI_NON_TRUNCATING_STATS | set(_CLI_NO_STATS_AXIS)
    )
    assert cli_classified == cli_reads
    assert len(_CLI_TRUNCATION_SURFACES) + len(_CLI_NON_TRUNCATING_STATS) + len(
        _CLI_NO_STATS_AXIS
    ) == len(cli_classified)

    mcp_classified = _MCP_NON_TRUNCATING_STATS | set(_MCP_NO_STATS_AXIS)
    assert mcp_classified == set(_MCP_READ_TOOLS)
    assert len(_MCP_NON_TRUNCATING_STATS) + len(_MCP_NO_STATS_AXIS) == len(
        mcp_classified
    )

    # Non-triviality: the load-bearing truncation family is exactly the three CLI
    # scope-envelope reads, while the works object is explicitly a stats-bearing
    # but non-truncating sibling on both transports.
    assert _CLI_TRUNCATION_SURFACES == {"search", "list", "related"}
    assert _CLI_NON_TRUNCATING_STATS == {"works"}
    assert _MCP_NON_TRUNCATING_STATS == {"get_works"}


def _assert_truncation_envelope(surface: str, payload: dict, expected_ids: list[str]):
    stats = payload["stats"]
    actual_ids = _ids(payload["results"])
    expected_page = expected_ids[:_LIMIT]

    assert stats["matched"] == len(expected_ids), f"{surface}: full pre-cap count"
    assert stats["returned"] == len(actual_ids), f"{surface}: returned count"
    assert stats["truncated"] is (len(expected_ids) > len(actual_ids)), (
        f"{surface}: truncated iff matched > returned"
    )
    assert len(expected_ids) > _LIMIT, f"{surface}: fixture must be truncated"
    assert actual_ids == expected_page, f"{surface}: top-limit prefix"


def _truncation_failures(capsys) -> set[str]:
    """Run every truncation surface and return the cells whose envelope lies."""
    db_path = get_paths().db_path
    failures: set[str] = set()

    probes = {
        "search": (
            lambda: _cli_json(["search", _QUERY, "--limit", str(_LIMIT), "--stats"], capsys),
            lambda: [hit.id for hit in search_items(db_path, _QUERY, limit=100)],
        ),
        "list": (
            lambda: _cli_json(["list", "--limit", str(_LIMIT), "--stats"], capsys),
            lambda: [item.id for item in list_items(db_path)],
        ),
        "related": (
            lambda: _cli_json(
                ["related", _ANCHOR, "--limit", str(_LIMIT), "--stats"], capsys
            ),
            lambda: [hit.id for hit in scored_related(db_path, _ANCHOR)],
        ),
    }

    assert set(probes) == _CLI_TRUNCATION_SURFACES
    for surface, (payload_fn, expected_fn) in probes.items():
        try:
            _assert_truncation_envelope(surface, payload_fn(), expected_fn())
        except AssertionError:
            failures.add(surface)
    return failures


def test_truncation_stats_are_full_scope_counts_and_prefixes(scrolls_home, capsys):
    """Every G2 stats envelope distinguishes a truncated page from the whole answer."""
    main(["init"])
    _seed_truncation_mix(get_paths().db_path)
    capsys.readouterr()

    assert _truncation_failures(capsys) == set()


def test_works_stats_objects_are_complete_uncapped_scopes(scrolls_home, capsys):
    """`works`/`get_works` are stats-bearing, but not page-truncating surfaces.

    Their `stats` block describes the complete reported work scope: no
    `matched`/`returned`/`truncated` trio is fabricated, and the CLI/MCP twins
    agree because both route through `works_payload`.
    """
    main(["init"])
    _seed_truncation_mix(get_paths().db_path)
    capsys.readouterr()

    cli_payload = _cli_json(["works"], capsys)
    mcp_payload = mcp_server.get_works()

    for payload in (cli_payload, mcp_payload):
        assert payload["scope"] == {"min_representations": 2}
        assert [work["doi"] for work in payload["works"]] == ["10.4242/h420"]
        assert payload["stats"]["items"] == 5
        assert payload["stats"]["works"] == len(payload["works"]) == 1
        assert {"matched", "returned", "truncated"}.isdisjoint(payload["stats"])

    assert cli_payload == mcp_payload


def test_page_count_masquerading_as_full_count_fails_only_that_surface(
    scrolls_home, capsys, monkeypatch
):
    """Sabotage: `search --stats` reports the page count as `matched`.

    The failure isolates to `search`: `list` computes its denominator from the
    uncapped `list_items` fold, and `related` from the uncapped `scored_related`
    fold. This proves the H420 guard catches the specific false-completeness
    regression a page-sized fixture would hide.
    """
    main(["init"])
    _seed_truncation_mix(get_paths().db_path)
    capsys.readouterr()
    assert _truncation_failures(capsys) == set()

    monkeypatch.setattr(cli, "count_matches", lambda *args, **kwargs: _LIMIT)

    assert _truncation_failures(capsys) == {"search"}
