"""Tests for context bundles (IDEAS.md §11, §14 Pass 5)."""

import dataclasses
import json
import re

import pytest

from scrolls.cli import main
from scrolls.context import build_context
from scrolls.custody import CustodyEvent, record_events
from scrolls.items import ScrollItem, insert_item
from scrolls.paths import get_paths


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


def make_item(item_id, title, extracted_text, **overrides):
    base = dict(
        id=item_id,
        source="wikipedia",
        url=f"https://example.org/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00",
        title=title,
        extracted_text=extracted_text,
        summary=extracted_text.split(".")[0] + ".",
        markdown_path=f"scrolls/wikipedia/{title.lower().replace(' ', '-')}.md",
        stage="rendered",
    )
    base.update(overrides)
    return ScrollItem(**base)


def run_context(capsys, *args):
    exit_code = main(["context", *args])
    assert exit_code == 0
    return capsys.readouterr().out


def test_context_outputs_markdown_bundle(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine with full-text search support.",
    ))
    insert_item(db, make_item(
        "wikipedia:en:Pelican", "Pelican",
        "Pelicans are large water birds with throat pouches.",
    ))
    capsys.readouterr()

    out = run_context(capsys, "database engine")
    assert out.startswith("# Scrolls Context Bundle: database engine\n")
    assert "## Best Matches" in out
    assert "1. SQLite (`wikipedia:en:SQLite`)" in out
    assert "Pelican" not in out
    assert "## Excerpts" in out
    assert "### SQLite" in out
    assert "`wikipedia:en:SQLite` · wikipedia · scrolls/wikipedia/sqlite.md" in out
    assert "SQLite is a database engine with full-text search support." in out
    assert "## Links" in out
    assert "- [SQLite](https://example.org/wikipedia:en:SQLite)" in out


def test_context_facets_scope_the_bundle(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine.", category="reference",
    ))
    insert_item(db, make_item(
        "arxiv:2401.0001", "A database paper",
        "This paper studies database engines.",
        source="arxiv", category="paper",
    ))
    capsys.readouterr()

    out = run_context(capsys, "database", "--source", "arxiv")
    # the title is self-documenting about the scope
    assert out.startswith("# Scrolls Context Bundle: database (source=arxiv)\n")
    assert "arxiv:2401.0001" in out
    assert "wikipedia:en:SQLite" not in out


def test_context_unclassified_facet_uses_a_clear_scope_note(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine.", category="reference",
    ))
    insert_item(db, make_item(
        "web:abc", "A database blog post",
        "Some database thoughts.", source="web", category=None,
    ))
    capsys.readouterr()

    out = run_context(capsys, "database", "--category", "")
    assert out.startswith(
        "# Scrolls Context Bundle: database (category=unclassified)\n"
    )
    assert "web:abc" in out
    assert "wikipedia:en:SQLite" not in out


def test_context_facet_with_no_matches_keeps_the_scope_note(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))
    capsys.readouterr()

    out = run_context(capsys, "database", "--source", "arxiv")
    assert out.startswith("# Scrolls Context Bundle: database (source=arxiv)\n")
    assert "No matching scrolls." in out


def test_context_tag_and_concept_facets_scope_the_bundle(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine.",
        tags=("Database",), concepts=("Full-text search",),
    ))
    insert_item(db, make_item(
        "arxiv:2401.0001", "A database paper",
        "This paper studies database engines.",
        source="arxiv", tags=("ml",), concepts=("Neural networks",),
    ))
    capsys.readouterr()

    # --concept matches by slug and names itself in the title
    out = run_context(capsys, "database", "--concept", "full text search")
    assert out.startswith(
        "# Scrolls Context Bundle: database (concept=full text search)\n"
    )
    assert "wikipedia:en:SQLite" in out
    assert "arxiv:2401.0001" not in out

    # --tag matches case-insensitively, AND-ing with the rest
    out = run_context(capsys, "database", "--tag", "database")
    assert out.startswith("# Scrolls Context Bundle: database (tag=database)\n")
    assert "wikipedia:en:SQLite" in out
    assert "arxiv:2401.0001" not in out


def test_context_ranks_title_matches_first(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:BM25", "Okapi BM25",
        "BM25 is a ranking function used by search engines.",
    ))
    insert_item(db, make_item(
        "wikipedia:en:Search", "Search engine",
        "A search engine may use ranking functions such as BM25 internally.",
    ))
    capsys.readouterr()

    out = run_context(capsys, "BM25 ranking")
    assert out.index("1. Okapi BM25") < out.index("2. Search engine")


def test_context_respects_limit(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    for index in range(5):
        insert_item(db, make_item(
            f"wikipedia:en:Page_{index}", f"Page {index}",
            "Every page mentions databases.",
        ))
    capsys.readouterr()

    out = run_context(capsys, "databases", "--limit", "2")
    assert "1. " in out and "2. " in out and "3. " not in out


def test_context_excerpt_falls_back_to_capped_extracted_text(scrolls_home, capsys):
    main(["init"])
    long_text = "databases " * 200  # ~2000 chars, no sentence structure
    insert_item(get_paths().db_path, make_item(
        "wikipedia:en:Long", "Long page", long_text.strip(), summary=None,
    ))
    capsys.readouterr()

    out = run_context(capsys, "databases")
    excerpt = out.split("### Long page\n")[1].split("\n## Links")[0]
    assert "databases …" in excerpt
    # the block (meta + per-source tags + capped body) stays well below the
    # ~2000-char full text; the H90 `· never re-checked` tag widened it slightly
    assert len(excerpt) < 850


def test_context_uses_canonical_url_in_links_when_present(scrolls_home, capsys):
    main(["init"])
    insert_item(get_paths().db_path, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine.",
        canonical_url="https://en.wikipedia.org/wiki/SQLite",
    ))
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert "- [SQLite](https://en.wikipedia.org/wiki/SQLite)" in out


def test_context_surfaces_connected_scrolls(scrolls_home, capsys):
    # A match that links to a saved arXiv paper which is *not* itself a
    # keyword hit: the link graph the adapters build (ADR 0044) should pull
    # the paper into the bundle even though FTS never would.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine with full-text search support.",
        links=("https://arxiv.org/abs/1706.03762",),
    ))
    insert_item(db, make_item(
        "arxiv:1706.03762", "Attention Is All You Need",
        "We propose the Transformer, a sequence model built on attention.",
        source="arxiv", url="https://arxiv.org/abs/1706.03762",
    ))
    capsys.readouterr()

    out = run_context(capsys, "database engine")
    above, _, connected = out.partition("## Connected scrolls")
    # The paper is connected, not a keyword match: absent above the section...
    assert connected, "expected a Connected scrolls section"
    assert "Attention Is All You Need" not in above
    # ...and present in it, named with its id and the match that pulled it in.
    assert "Attention Is All You Need" in connected
    assert "`arxiv:1706.03762`" in connected
    assert "linked from" in connected.lower()
    assert "SQLite" in connected


def test_context_connected_includes_reverse_links(scrolls_home, capsys):
    # A model that links *to* a matched paper is connected by the reverse edge.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "arxiv:1706.03762", "A paper on database engines",
        "This paper studies database engines and attention.",
        source="arxiv", url="https://arxiv.org/abs/1706.03762",
    ))
    insert_item(db, make_item(
        "huggingface:model:google/bert", "BERT base",
        "A pretrained language model card.",
        source="huggingface", url="https://huggingface.co/google/bert",
        links=("https://arxiv.org/abs/1706.03762",),
    ))
    capsys.readouterr()

    out = run_context(capsys, "database engines")
    _, _, connected = out.partition("## Connected scrolls")
    assert "BERT base" in connected
    assert "`huggingface:model:google/bert`" in connected
    assert "links to" in connected.lower()


def test_context_ranks_connected_by_centrality(scrolls_home, capsys):
    # A neighbor connected to two matches outranks one connected to a single
    # match, and the busier neighbor reports the extra connection.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite database engine",
        "SQLite is a small database engine.",
        links=("https://arxiv.org/abs/0001.0001", "https://arxiv.org/abs/0002.0002"),
    ))
    insert_item(db, make_item(
        "wikipedia:en:Postgres", "Postgres database engine",
        "Postgres is a database engine server.",
        links=("https://arxiv.org/abs/0001.0001",),
    ))
    insert_item(db, make_item(
        "arxiv:0001.0001", "Shared Hub Paper", "An attention model.",
        source="arxiv", url="https://arxiv.org/abs/0001.0001",
    ))
    insert_item(db, make_item(
        "arxiv:0002.0002", "Solo Paper", "Another attention model.",
        source="arxiv", url="https://arxiv.org/abs/0002.0002",
    ))
    capsys.readouterr()

    out = run_context(capsys, "database engine")
    _, _, connected = out.partition("## Connected scrolls")
    assert connected.index("Shared Hub Paper") < connected.index("Solo Paper")
    assert "(+1 more)" in connected  # the hub connects to two matches


def test_context_connected_shows_unfetched_neighbor_by_id(scrolls_home, capsys):
    # A linked paper that is saved but not yet fetched has no title; it still
    # surfaces (by id), honestly flagging "you have this but haven't pulled it".
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine with full-text search.",
        links=("https://arxiv.org/abs/1706.03762",),
    ))
    insert_item(db, ScrollItem(
        id="arxiv:1706.03762", source="arxiv",
        url="https://arxiv.org/abs/1706.03762",
        saved_at="2026-06-12T00:00:00+00:00", stage="detected",
    ))
    capsys.readouterr()

    out = run_context(capsys, "database engine")
    _, _, connected = out.partition("## Connected scrolls")
    assert "- arxiv:1706.03762 (`arxiv:1706.03762`) · arxiv — linked from SQLite" in connected


def test_context_omits_connected_section_when_no_links(scrolls_home, capsys):
    main(["init"])
    insert_item(get_paths().db_path, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert "## Connected scrolls" not in out


def test_context_connected_excludes_items_already_matched(scrolls_home, capsys):
    # Two matches that link to each other must not list each other as
    # connected — a keyword hit is already in Best Matches.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite database",
        "SQLite is a database engine.",
        links=("https://example.org/wikipedia:en:Postgres",),
    ))
    insert_item(db, make_item(
        "wikipedia:en:Postgres", "Postgres database",
        "Postgres is a database engine.",
        links=("https://example.org/wikipedia:en:SQLite",),
    ))
    capsys.readouterr()

    out = run_context(capsys, "database engine")
    assert "## Connected scrolls" not in out


def test_context_no_matches_prints_empty_bundle(scrolls_home, capsys):
    main(["init"])
    capsys.readouterr()

    out = run_context(capsys, "pelicans")
    assert "# Scrolls Context Bundle: pelicans" in out
    assert "No matching scrolls." in out


def test_context_before_init_prints_empty_bundle(scrolls_home, capsys):
    out = run_context(capsys, "anything")
    assert "No matching scrolls." in out
    assert not scrolls_home.exists()  # context never creates a library


# --- coverage / truncation honesty: completeness contract G2 ---------------


def test_context_marks_truncation_when_matches_exceed_the_limit(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    for index in range(5):
        insert_item(db, make_item(
            f"wikipedia:en:Page_{index}", f"Page {index}",
            "Every page mentions databases.",
        ))
    capsys.readouterr()

    out = run_context(capsys, "databases", "--limit", "2")
    # the bundle is built from the top 2 of 5 matches and says so, so absence
    # below the cap is never read as absence in the library (G2 truncation)
    assert "Coverage: the top 2 of 5 matching scrolls" in out
    assert "--limit" in out  # names the lever to see the rest


def test_context_states_full_coverage_when_nothing_is_truncated(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    for index in range(2):
        insert_item(db, make_item(
            f"wikipedia:en:Page_{index}", f"Page {index}",
            "Every page mentions databases.",
        ))
    capsys.readouterr()

    out = run_context(capsys, "databases")
    # every match fits under the cap: the bundle states it is complete, the
    # G2 "this is every match" half of the same distinction
    assert "Coverage: all 2 matching scrolls" in out
    assert "top " not in out  # not the truncated phrasing


def test_context_empty_bundle_has_no_coverage_line(scrolls_home, capsys):
    main(["init"])
    capsys.readouterr()

    out = run_context(capsys, "nothingmatcheshere")
    # the G1-locked empty form is untouched: no coverage line where there are
    # no matches to be honest about the completeness of
    assert "No matching scrolls." in out
    assert "Coverage:" not in out


def test_context_blank_query_is_an_error(scrolls_home, capsys):
    exit_code = main(["context", '""'])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


# --- progressive context budgets (MVP M3) ----------------------------------


def _insert_match_with_linked_paper(db):
    # a keyword match that links to a saved paper which is not itself a hit, so
    # both an Excerpts and a Connected scrolls section exist at the full budget
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine with full-text search support.",
        links=("https://arxiv.org/abs/1706.03762",),
    ))
    insert_item(db, make_item(
        "arxiv:1706.03762", "Attention Is All You Need",
        "We propose the Transformer, a sequence model built on attention.",
        source="arxiv", url="https://arxiv.org/abs/1706.03762",
    ))


def test_context_full_budget_is_the_default(scrolls_home, capsys):
    main(["init"])
    _insert_match_with_linked_paper(get_paths().db_path)
    capsys.readouterr()

    default = run_context(capsys, "database engine")
    explicit = run_context(capsys, "database engine", "--budget", "full")
    # the default budget is full and full is the current flat bundle, unchanged:
    # excerpts, the connected graph, and no budget note (full omits nothing)
    assert default == explicit
    assert "## Excerpts" in default
    assert "## Connected scrolls" in default
    assert "Budget:" not in default


def test_context_index_budget_is_catalog_only(scrolls_home, capsys):
    main(["init"])
    _insert_match_with_linked_paper(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "database engine", "--budget", "index")
    # the cheapest tier: the catalog (best matches + source links), no bodies
    # and no graph build — identity/index first, deep bodies on demand
    assert "## Best Matches" in out
    assert "## Links" in out
    assert "## Excerpts" not in out
    assert "## Connected scrolls" not in out
    # honest about the reduced depth, and names the levers to get more
    assert "Budget: index" in out
    assert "--budget full" in out
    # the match is still named so the agent can follow up with `scrolls show`
    assert "1. SQLite (`wikipedia:en:SQLite`)" in out


def test_context_connected_budget_keeps_the_graph_omits_excerpts(scrolls_home, capsys):
    main(["init"])
    _insert_match_with_linked_paper(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "database engine", "--budget", "connected")
    # the middle tier adds the link graph back but still holds no deep bodies
    assert "## Connected scrolls" in out
    assert "Attention Is All You Need" in out
    assert "## Excerpts" not in out
    assert "Budget: connected" in out
    assert "--budget full" in out


def test_context_budget_note_absent_at_full(scrolls_home, capsys):
    main(["init"])
    _insert_match_with_linked_paper(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "database engine", "--budget", "full")
    # full omits nothing, so there is no depth to disclaim
    assert "Budget:" not in out


def test_context_budget_preserves_coverage_truncation(scrolls_home, capsys):
    # the coverage line (G2) is about the match *set*, the budget about depth
    # *per match*: a reduced budget must not weaken the truncation honesty
    main(["init"])
    db = get_paths().db_path
    for index in range(5):
        insert_item(db, make_item(
            f"wikipedia:en:Page_{index}", f"Page {index}",
            "Every page mentions databases.",
        ))
    capsys.readouterr()

    out = run_context(capsys, "databases", "--limit", "2", "--budget", "index")
    assert "Coverage: the top 2 of 5 matching scrolls" in out


def test_context_index_budget_still_collapses_same_work(scrolls_home, capsys):
    # same-work collapse (ADR 0101) is an index-level fact, not a body: it must
    # hold at every budget, so the catalog never spends two slots on one work
    main(["init"])
    _insert_attention_pair(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "attention transformer", "--budget", "index")
    assert out.count("Attention Is All You Need (`") == 1
    assert "same work as `crossref:10.5555/3295222`" in out
    assert "canonical `crossref:10.5555/3295222`" in out
    # no bodies at the index budget — the work's excerpt is not rendered at all
    assert "## Excerpts" not in out
    assert "We propose the Transformer based on attention mechanisms." not in out


def test_context_empty_bundle_ignores_budget(scrolls_home, capsys):
    main(["init"])
    capsys.readouterr()

    out = run_context(capsys, "nothingmatcheshere", "--budget", "index")
    # the G1-locked empty form is untouched: no budget note where there are no
    # matches to have any depth over
    assert "No matching scrolls." in out
    assert "Budget:" not in out
    assert "Coverage:" not in out


def test_context_invalid_budget_raises(scrolls_home):
    # build_context defends the contract for the MCP path (the CLI also rejects
    # an unknown tier via argparse choices, tested separately)
    from scrolls.context import build_context

    main(["init"])
    with pytest.raises(ValueError):
        build_context(get_paths().db_path, "database", budget="bogus")


def test_context_cli_rejects_unknown_budget(scrolls_home):
    main(["init"])
    with pytest.raises(SystemExit):
        main(["context", "database", "--budget", "bogus"])


# --- budget tiers are strictly nested (roadmap H366) ------------------------
#
# The per-tier tests above pin each block's presence *one tier at a time*; none
# pins that the tiers are strictly nested *as a whole* over one library — that a
# leaner budget reduces depth *per match* but never the match *set* (the M3
# depth-vs-set orthogonality: "the two are orthogonal and both always hold"). A
# regression that dropped a Best Match at a leaner budget (a plausible "save
# tokens" change) would pass the per-block presence tests yet silently break the
# contract an agent relies on to read a lean `index` boot as "the same matches,
# less depth" — never "fewer matches". This guard pins the whole contract over
# one seeded library, and mirrors it on the MCP `get_context_bundle` twin so the
# agent transport carries it too.


def _seed_nested_library(db):
    # a non-vacuous fixture: three keyword matches for "database" (a multi-item
    # Best-Match set, so set-equality is a real constraint, not a singleton) plus
    # one linked-but-unmatched paper (a non-empty Connected block) — so every
    # tier-gated section (matches, the link graph, the deep-body excerpts) is
    # populated and the nesting has teeth at each level.
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine with full-text search.",
        links=("https://arxiv.org/abs/1706.03762",),
    ))
    insert_item(db, make_item(
        "wikipedia:en:PostgreSQL", "PostgreSQL",
        "PostgreSQL is a relational database system.",
    ))
    insert_item(db, make_item(
        "wikipedia:en:Redis", "Redis",
        "Redis is an in-memory database used as a cache.",
    ))
    # linked from SQLite but holds no "database" keyword, so it surfaces only as a
    # Connected neighbour, never as a Best Match
    insert_item(db, make_item(
        "arxiv:1706.03762", "Attention Is All You Need",
        "We propose the Transformer, a sequence model built on attention.",
        source="arxiv", url="https://arxiv.org/abs/1706.03762",
    ))


def _best_match_ids(bundle):
    """The ordered ids on the bundle's Best Matches lines."""
    section = bundle.partition("## Best Matches")[2].split("\n## ", 1)[0]
    return re.findall(r"^\d+\. .*?\(`([^`]+)`\)", section, re.MULTILINE)


def _connected_block(bundle):
    """The Connected scrolls section text (heading through to the next ## )."""
    return bundle.partition("## Connected scrolls")[2].partition("## Links")[0]


def _assert_budget_tiers_strictly_nested(by_tier):
    """Pin the M3 strictly-nested `index`/`connected`/`full` contract.

    `by_tier` maps each tier name to its rendered bundle text (one library, one
    query). Asserts the four legs of the nesting: (a) the Best-Match set is
    identical across all three tiers — the load-bearing depth-vs-set
    orthogonality; (b) the Connected link-graph block is absent at `index`,
    present at `connected`/`full`, and byte-identical between the two; (c) the
    deep-body Excerpts block appears only at `full`; (d) a sub-`full` tier
    discloses its reduced depth in a `_Budget:_` note, omitted at `full`.
    """
    index_out, connected_out, full_out = (
        by_tier["index"], by_tier["connected"], by_tier["full"]
    )

    # (a) the load-bearing invariant: the Best-Match set never shrinks with
    # depth. The same ranked search drives every tier, so the *ordered* ids are
    # equal (stronger), and so the *set* is equal (the documented contract M3
    # pins and the sabotage below breaks).
    index_ids = _best_match_ids(index_out)
    connected_ids = _best_match_ids(connected_out)
    full_ids = _best_match_ids(full_out)
    assert len(full_ids) >= 2, "fixture must seed a multi-item Best-Match set"
    assert index_ids == connected_ids == full_ids
    assert set(index_ids) == set(connected_ids) == set(full_ids)

    # (b) the Connected link-graph block: absent at index, present at
    # connected/full, and byte-identical between them (depth doesn't perturb it)
    assert "## Connected scrolls" not in index_out
    assert "## Connected scrolls" in connected_out
    assert "## Connected scrolls" in full_out
    connected_block = _connected_block(connected_out)
    assert connected_block.strip(), "fixture must seed a non-empty Connected block"
    assert connected_block == _connected_block(full_out)

    # (c) the deep-body Excerpts block appears only at full
    assert "## Excerpts" not in index_out
    assert "## Excerpts" not in connected_out
    assert "## Excerpts" in full_out

    # (d) the honest `_Budget:_` depth note on the lean tiers, omitted at full
    assert "_Budget: index" in index_out
    assert "_Budget: connected" in connected_out
    assert "Budget:" not in full_out


def test_context_budget_tiers_are_strictly_nested(scrolls_home, capsys):
    main(["init"])
    _seed_nested_library(get_paths().db_path)
    capsys.readouterr()

    by_tier = {
        tier: run_context(capsys, "database", "--budget", tier)
        for tier in ("index", "connected", "full")
    }
    _assert_budget_tiers_strictly_nested(by_tier)


def test_mcp_context_budget_tiers_are_strictly_nested(scrolls_home):
    # the same nesting tie on the MCP `get_context_bundle(budget=)` twin, so the
    # agent transport an agent boots through carries the contract too
    from scrolls import mcp_server

    main(["init"])
    _seed_nested_library(get_paths().db_path)

    by_tier = {
        tier: mcp_server.get_context_bundle("database", budget=tier)
        for tier in ("index", "connected", "full")
    }
    _assert_budget_tiers_strictly_nested(by_tier)


# --- scope custody headline (roadmap H47) ----------------------------------


def _custody_line(out):
    return next(line for line in out.splitlines() if line.startswith("_Custody:"))


def _drift_event(item_id, status, observed=None):
    return CustodyEvent(
        item_id=item_id, checked_at="2026-06-14T00:00:00+00:00", status=status,
        prior_hash="deadbeef", observed_hash=observed,
    )


def test_context_carries_a_scope_custody_headline(scrolls_home, capsys):
    # how much of what the agent is about to read is full-fidelity / has drifted
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:Full", "Full database", "A fully held database body.",
        content_hash="deadbeef", raw_text="<raw>A fully held database body.</raw>",
    ))
    insert_item(db, make_item(
        "wikipedia:en:Partial", "Partial database", "A partial database body.",
    ))  # no hash/raw → partial fidelity
    record_events(db, [_drift_event("wikipedia:en:Full", "drifted", observed="cafe1234")])
    capsys.readouterr()

    headline = _custody_line(run_context(capsys, "database"))
    assert "2 scroll(s)" in headline
    assert "fidelity full 1, partial 1" in headline
    # the full-fidelity scroll drifted; the partial one was never re-checked
    assert "drift unverified 1, drifted 1" in headline


def test_context_custody_headline_gated_off_index(scrolls_home, capsys):
    # the leanest `index` tier stays a bare catalog — no custody headline (H44 gate)
    main(["init"])
    insert_item(get_paths().db_path, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "index")
    assert "_Custody:" not in out
    # but the catalog (best matches + links) is still there
    assert "## Best Matches" in out


def test_context_custody_headline_present_from_connected_up(scrolls_home, capsys):
    main(["init"])
    insert_item(get_paths().db_path, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "connected")
    assert "_Custody: 1 scroll(s)" in out


def test_context_custody_headline_converges_with_doctor(scrolls_home, capsys):
    # an uncapped, uncollapsed whole-library scope: the headline counts equal
    # doctor's custody aggregate (the H42 convergence, lifted to the bundle scope)
    from scrolls.doctor import run_doctor

    main(["init"])
    db = get_paths().db_path
    for index in range(3):
        insert_item(db, make_item(
            f"wikipedia:en:Page_{index}", f"Page {index} database",
            "Every page is a database.",
            content_hash="deadbeef", raw_text="<raw>body</raw>",
        ))
    record_events(db, [
        _drift_event("wikipedia:en:Page_0", "unchanged", observed="deadbeef"),
        _drift_event("wikipedia:en:Page_1", "drifted", observed="cafe1234"),
        # Page_2 left unverified
    ])
    capsys.readouterr()

    headline = _custody_line(run_context(capsys, "database"))  # full, 3 < limit 8
    custody = run_doctor(get_paths())["custody"]
    assert "fidelity full 3" in headline and custody["tiers"]["full"] == 3
    # verified ≡ ledger `unchanged`; unverified = held − verdicts
    assert "drift verified 1, unverified 1, drifted 1" in headline
    assert custody["drift"]["unchanged"] == 1
    assert custody["drift"]["drifted"] == 1
    assert custody["drift"]["unverified"] == 1


# --- `_Fidelity:_` holdings line at the `index` budget (roadmap H212) -------
#
# The leanest `index` tier stays a bare catalog for *depth* (no bodies, no graph)
# and a bare *ledger* (no drift read), but fidelity is a ledger-free holdings fact
# (`get_fidelity`), so it travels even there (vision principle 3): an agent reading
# an `index` catalog learns how much of the matched set it holds in full *before*
# spending budget on a deeper tier. The line carries **only** fidelity — never a
# drift verdict, because the leanest tier reads no ledger and claiming
# `verified`/`unverified` there would be the M2 anti-fabrication violation.


def _fidelity_line(out):
    return next(line for line in out.splitlines() if line.startswith("_Fidelity:"))


def test_context_index_budget_carries_fidelity_holdings(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:Full", "Full database", "A fully held database body.",
        content_hash="deadbeef", raw_text="<raw>A fully held database body.</raw>",
    ))
    insert_item(db, make_item(
        "wikipedia:en:Partial", "Partial database", "A partial database body.",
    ))  # no hash/raw → partial fidelity — a second tier, so the line is non-vacuous
    # a drift event the leanest tier must NOT read or claim
    record_events(db, [_drift_event("wikipedia:en:Full", "drifted", observed="cafe")])
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "index")
    # fidelity travels even at the leanest tier — the holdings fact, with scope
    line = _fidelity_line(out)
    assert "full 1, partial 1" in line
    assert "(of 2)" in line
    # but the leanest tier reads no ledger: no drift verdict, no `_Custody:` headline
    assert "_Custody:" not in out
    assert "drift" not in line and "drifted" not in out
    # and the catalog itself is still there (depth honesty unchanged)
    assert "## Best Matches" in out


def test_context_fidelity_line_only_at_index_headline_carries_it_above(
    scrolls_home, capsys
):
    # from `connected` up the full `_Custody:_` headline already carries fidelity,
    # so the dedicated `_Fidelity:_` line is an `index`-only lever (no duplication)
    main(["init"])
    insert_item(get_paths().db_path, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
        content_hash="deadbeef", raw_text="<raw>SQLite is a database engine.</raw>",
    ))
    capsys.readouterr()

    for tier in ("connected", "full"):
        out = run_context(capsys, "database", "--budget", tier)
        assert "_Fidelity:" not in out          # not duplicated above index
        assert "fidelity full 1" in _custody_line(out)  # the headline carries it


def test_context_index_fidelity_counts_match_the_connected_headline(
    scrolls_home, capsys
):
    # cross-tier convergence (the H213 seed): the `index` `_Fidelity:_` counts are
    # the *same* tier counts the `connected` `_Custody:_` headline renders — both
    # fold `get_fidelity` through `custody_counts`, so a tier never disagrees with
    # another tier on what fraction is held in full.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:Full", "Full database", "A fully held database body.",
        content_hash="deadbeef", raw_text="<raw>A fully held database body.</raw>",
    ))
    insert_item(db, make_item(
        "wikipedia:en:Partial", "Partial database", "A partial database body.",
    ))
    capsys.readouterr()

    index_line = _fidelity_line(run_context(capsys, "database", "--budget", "index"))
    headline = _custody_line(run_context(capsys, "database", "--budget", "connected"))
    # the headline's `fidelity <counts>` section == the index line's counts
    assert "full 1, partial 1" in index_line
    assert "fidelity full 1, partial 1" in headline


def _fidelity_scope(line):
    """The `N` from a `_Fidelity: … (of N)._` line's scope suffix."""
    return int(re.search(r"\(of (\d+)\)", line).group(1))


# --- custody filters on the context bundle (roadmap H257) -------------------
#
# The custody-filter family — browsable/rankable/actable/relatable on
# `list`/`search`/`verify`/`related` — reaches the agent *context bundle*, the
# one progressive read surface it had not. `--fidelity`/`--drift` scope the
# candidate set by the per-item *holdings* (content-column) and *ledger-claim*
# (verify-posture) axes *before* the `--limit` cap, the `list`-sieve shape, so
# an agent can build context from "only the full-fidelity sources I can
# re-derive offline" or "only the ones that have drifted". Both fold the same
# `scrolls_fidelity`/`scrolls_drift` UDFs `search --fidelity`/`--drift` use
# (`build_context` passes them straight to `search_items`/`count_matches`), so
# the rendered `_Custody:_`/`_Fidelity:_` headline describes exactly the kept
# set and the Coverage denominator counts only matches at that custody value.


def _seed_custody_mix(db):
    """Two full + two partial + one reference, all matching `database`.

    Drift: both full items re-checked (one verified, one drifted); the rest
    never re-checked (→ unverified). A `database` query matches the whole set
    (every title carries it), so the bundle's scope is the whole library.
    """
    insert_item(db, make_item(
        "wikipedia:en:Full0", "Full database zero", "A fully held database body.",
        content_hash="sha256:f0", raw_text="<raw>full zero</raw>",
    ))
    insert_item(db, make_item(
        "wikipedia:en:Full1", "Full database one", "Another fully held database body.",
        content_hash="sha256:f1", raw_text="<raw>full one</raw>",
    ))
    insert_item(db, make_item(
        "wikipedia:en:Partial0", "Partial database zero", "A partial database body.",
    ))  # no hash/raw → partial
    insert_item(db, make_item(
        "wikipedia:en:Partial1", "Partial database one", "Another partial database body.",
    ))
    insert_item(db, make_item(
        "wikipedia:en:Ref", "Reference database pointer", "",
        summary=None, stage="detected",
    ))  # no content → reference
    record_events(db, [
        _drift_event("wikipedia:en:Full0", "unchanged", observed="sha256:f0"),
        _drift_event("wikipedia:en:Full1", "drifted", observed="sha256:changed"),
    ])


def test_context_fidelity_filter_keeps_only_that_tier(scrolls_home, capsys):
    # `--fidelity full` keeps only the matches held at the full tier, and the
    # rendered headline describes exactly that kept set — not the whole library.
    main(["init"])
    _seed_custody_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "database", "--fidelity", "full")
    # only the two full-fidelity scrolls appear; the partials/reference do not
    assert "wikipedia:en:Full0" in out and "wikipedia:en:Full1" in out
    for absent in ("Partial0", "Partial1", "Ref"):
        assert f"wikipedia:en:{absent}" not in out
    # the headline describes the kept set: all full, nothing else
    headline = _custody_line(out)
    assert "2 scroll(s)" in headline
    assert "fidelity full 2" in headline and "partial" not in headline


def test_context_drift_filter_keeps_only_that_posture(scrolls_home, capsys):
    # `--drift drifted` keeps only the matches whose latest verdict reads drifted
    main(["init"])
    _seed_custody_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "database", "--drift", "drifted")
    assert "wikipedia:en:Full1" in out  # the one drifted scroll
    for absent in ("Full0", "Partial0", "Partial1", "Ref"):
        assert f"wikipedia:en:{absent}" not in out
    headline = _custody_line(out)
    assert "1 scroll(s)" in headline
    assert "drift drifted 1" in headline and "unverified" not in headline


def test_context_custody_filters_sieve_before_the_limit(scrolls_home, capsys):
    # the before-cap sieve (the list-sieve shape): `--fidelity full --limit 1`
    # returns the top *full* match, not the top match then sieved to nothing —
    # and the Coverage denominator counts only the full-tier matches (2), so a
    # capped custody bundle stays scope-honest about its own custody scope.
    main(["init"])
    _seed_custody_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "database", "--fidelity", "full", "--limit", "1")
    # exactly one match, and it is a full-fidelity one (the sieve ran first)
    assert "1. " in out
    assert "wikipedia:en:Full0" in out or "wikipedia:en:Full1" in out
    # the denominator is the *full-tier* match count (2), never the library-wide 5
    assert "the top 1 of 2 matching scrolls" in out


def test_context_custody_filters_and_together(scrolls_home, capsys):
    # the two axes AND: `--fidelity full --drift verified` keeps only the match
    # that is both held in full *and* re-checked unchanged (Full0).
    main(["init"])
    _seed_custody_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "database", "--fidelity", "full", "--drift", "verified")
    assert "wikipedia:en:Full0" in out
    for absent in ("Full1", "Partial0", "Partial1", "Ref"):
        assert f"wikipedia:en:{absent}" not in out


def test_context_custody_scope_named_in_the_title(scrolls_home, capsys):
    # a custody-scoped bundle is self-documenting: the title names which holdings
    # tier / drift posture it covers, beside the existing facet echo.
    main(["init"])
    _seed_custody_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "database", "--fidelity", "full")
    assert out.startswith("# Scrolls Context Bundle: database (fidelity=full)\n")
    out = run_context(capsys, "database", "--drift", "drifted")
    assert out.startswith("# Scrolls Context Bundle: database (drift=drifted)\n")
    # both axes, and ANDed after a facet, all read in the title
    out = run_context(
        capsys, "database", "--source", "wikipedia",
        "--fidelity", "full", "--drift", "verified",
    )
    assert out.startswith(
        "# Scrolls Context Bundle: database "
        "(source=wikipedia, fidelity=full, drift=verified)\n"
    )


def test_context_drift_filter_describes_kept_set_at_full_budget(scrolls_home, capsys):
    # the genuine subtlety (H257): the sieve runs *before* the budget tier nests
    # its excerpts, so the `full`-budget per-excerpt drift tags describe the kept
    # items — a `--drift drifted` bundle's excerpts all carry the `drifted` tag,
    # never a `verified`/`unverified` one for a sieved-out item.
    main(["init"])
    _seed_custody_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "database", "--drift", "drifted", "--budget", "full")
    assert "## Excerpts" in out
    assert "_drift `drifted`" in out
    # no excerpt for a sieved-out posture leaked through
    assert "_drift `verified`" not in out
    assert "_drift `unverified`" not in out


def test_context_fidelity_holdings_line_describes_kept_set_at_index(scrolls_home, capsys):
    # the leanest `index` tier's ledger-free `_Fidelity:_` line is folded over the
    # kept (sieved) set too: `--fidelity partial` reports only the partial holdings.
    main(["init"])
    _seed_custody_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "database", "--fidelity", "partial", "--budget", "index")
    line = _fidelity_line(out)
    assert "partial 2" in line and "full" not in line
    assert _fidelity_scope(line) == 2  # the kept set, not the library-wide 5


def test_context_unknown_fidelity_raises(scrolls_home):
    main(["init"])
    with pytest.raises(ValueError):
        build_context(get_paths().db_path, "database", fidelity="ful")


def test_context_unknown_drift_raises(scrolls_home):
    main(["init"])
    with pytest.raises(ValueError):
        build_context(get_paths().db_path, "database", drift="drift")


def test_context_cli_rejects_unknown_custody_values(scrolls_home):
    # argparse `choices=` rejects a bad value with exit 2 before any DB access —
    # the closed-vocabulary contract `list`/`search --fidelity`/`--drift` keep.
    main(["init"])
    with pytest.raises(SystemExit) as exc:
        main(["context", "database", "--fidelity", "bogus"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        main(["context", "database", "--drift", "bogus"])
    assert exc.value.code == 2


def _fidelity_counts(line):
    """The `{tier: count}` map parsed from a `_Fidelity:` line's tier tokens."""
    return {
        tier: int(n) for tier, n in re.findall(r"(full|partial|reference) (\d+)", line)
    }


def _coverage_top_of(out):
    """The `(returned, matched)` from a truncated `_Coverage: the top R of M` line."""
    line = next(line for line in out.splitlines() if line.startswith("_Coverage:"))
    match = re.search(r"the top (\d+) of (\d+)", line)
    return int(match.group(1)), int(match.group(2))


def test_context_index_fidelity_scope_is_honest_under_truncation(scrolls_home, capsys):
    # roadmap H221: the `index` `_Fidelity:_` line counts the *in-bundle* set (the
    # kept post-cap representations, `len(items)`), never the library-wide matched
    # total. When the bundle is capped (`matched > returned`) its `(of N)` must
    # equal the Coverage line's `returned`, and its tier counts must sum to that
    # returned — the fidelity holdings never over-claim scope the bundle didn't see
    # (the depth-axis sibling of the Coverage line's match-set honesty; the
    # *fidelity* counterpart of that line's truncation honesty).
    main(["init"])
    db = get_paths().db_path
    # 3 full + 3 partial, all matching "database" — a mixed-fidelity scope larger
    # than the cap. With `--limit 4`, pigeonhole forces the kept 4 to span *both*
    # tiers (only 3 of either exist), so the in-bundle split (sums to 4) is
    # provably not the library-wide `full 3, partial 3` (sums to 6).
    for index in range(3):
        insert_item(db, make_item(
            f"wikipedia:en:Full_{index}", f"Full database {index}",
            "A fully held database body.",
            content_hash=f"deadbeef0{index}",
            raw_text="<raw>A full database body.</raw>",
        ))
        insert_item(db, make_item(
            f"wikipedia:en:Partial_{index}", f"Partial database {index}",
            "A partial database body.",
        ))  # no hash/raw → partial fidelity
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "index", "--limit", "4")
    fidelity = _fidelity_line(out)
    returned, matched = _coverage_top_of(out)

    # the bundle is genuinely truncated: top 4 of 6
    assert (returned, matched) == (4, 6)
    # the holdings scope names only what the bundle saw, tied to Coverage's
    # `returned` — never the library-wide matched total it never read
    assert _fidelity_scope(fidelity) == returned   # (of 4), == Coverage's top
    assert _fidelity_scope(fidelity) != matched    # never (of 6)
    # and the tier counts sum to that in-bundle scope, not the whole library
    counts = _fidelity_counts(fidelity)
    assert sum(counts.values()) == returned        # sums to 4, not 6
    # the kept set is provably mixed (pigeonhole), so the line isn't accidentally
    # all-one-tier — a real holdings split over the truncated scope
    assert counts.get("full") and counts.get("partial")


def test_context_index_fidelity_scope_honors_the_active_facet(scrolls_home, capsys):
    # roadmap H223: the leanest `index` `_Fidelity:_` holdings count the *post-facet*
    # kept set (the representations `build_context` keeps after the
    # source/category/stage/tag/concept filter), so a scoped `--source <S>` names only
    # <S>'s fidelity tiers and `(of k)` scope — never the library-wide holdings of a
    # multi-source library. The *facet*-axis sibling of H221's *truncation*-axis
    # `(of N)` scope-honesty: the holdings fact never over-claims beyond the agent's
    # chosen scope.
    from scrolls.custody import custody_counts, custody_counts_by_source
    from scrolls.items import list_items

    main(["init"])
    db = get_paths().db_path
    # multi-source, mixed-fidelity *within* one source: web is full 1 + partial 1,
    # arxiv is full 2. So web's holdings (full 1, partial 1, of 2) are provably a
    # strict subset of — and a different tier split than — the library-wide holdings
    # (full 3, partial 1, of 4). All titles carry "database" so one query covers all.
    insert_item(db, make_item(
        "web:full", "Full database", "A full database body.",
        source="web", url="https://web.example/full",
        content_hash="deadbeef", raw_text="<raw>A full database body.</raw>"))
    insert_item(db, make_item(
        "web:partial", "Partial database", "A partial database body.",
        source="web", url="https://web.example/partial"))  # no hash/raw → partial
    for index in range(2):
        insert_item(db, make_item(
            f"arxiv:{index}", f"Arxiv database {index}", "A database paper body.",
            source="arxiv", url=f"https://arxiv.org/abs/{index}",
            content_hash=f"aa11bb2{index}",
            raw_text="<raw>A database paper body.</raw>"))
    capsys.readouterr()

    # what web's holdings vs. the whole library's actually are, straight from the
    # shared `custody_counts*` primitive (`{}` verdicts — fidelity is ledger-free),
    # so the expectations are tied to the scoped subset, not independently hardcoded
    items = list_items(db)
    web_tiers = {t: n for t, n in custody_counts_by_source(items, {})["web"]["tiers"].items() if n}
    web_n = sum(custody_counts_by_source(items, {})["web"]["tiers"].values())
    whole_tiers = {t: n for t, n in custody_counts(items, {})["tiers"].items() if n}
    whole_n = len(items)

    scoped = _fidelity_line(
        run_context(capsys, "database", "--budget", "index", "--source", "web"))
    unscoped = _fidelity_line(run_context(capsys, "database", "--budget", "index"))

    # the scoped line names only web's holdings and its `(of k)` scope
    assert _fidelity_counts(scoped) == web_tiers       # {full 1, partial 1}
    assert _fidelity_scope(scoped) == web_n            # (of 2)
    # the unscoped line names the whole-library holdings
    assert _fidelity_counts(unscoped) == whole_tiers   # {full 3, partial 1}
    assert _fidelity_scope(unscoped) == whole_n        # (of 4)
    # the scope honesty is non-vacuous: the two genuinely differ on both axes — the
    # scoped read never silently reverts to the library-wide holdings it didn't see
    assert web_tiers != whole_tiers
    assert web_n != whole_n


def test_context_index_fidelity_scope_is_honest_under_facet_and_truncation(
    scrolls_home, capsys
):
    # roadmap H228: the *composition* of H221 (truncation) and H223 (facet). The
    # leanest `index` `_Fidelity:_` `(of N)` must stay honest when BOTH scope-
    # narrowing filters apply at once — neither silently reverting to a pre-filter
    # count when the other is active. Over a mixed-fidelity, multi-source library
    # where one source's matching scope exceeds the cap, the scoped-and-truncated
    # holdings name only the post-facet, post-cap kept set: `(of k)` equals the
    # scoped Coverage `returned`, and the tier counts sum to it — never the
    # library-wide holdings, the unscoped-but-truncated set, or the
    # scoped-but-untruncated set.
    main(["init"])
    db = get_paths().db_path
    # web: 3 full + 3 partial (6 matching) — a mixed-fidelity scope larger than the
    # cap (4). arxiv: 2 full — so the library-wide match total (8) strictly exceeds
    # web's scoped total (6), and both exceed the cap. Every title carries "database"
    # so one query covers the whole library.
    for index in range(3):
        insert_item(db, make_item(
            f"web:full_{index}", f"Full database {index}", "A full database body.",
            source="web", url=f"https://web.example/full/{index}",
            content_hash=f"deadbeef0{index}",
            raw_text="<raw>A full database body.</raw>"))
        insert_item(db, make_item(
            f"web:partial_{index}", f"Partial database {index}",
            "A partial database body.",
            source="web", url=f"https://web.example/partial/{index}"))  # → partial
    for index in range(2):
        insert_item(db, make_item(
            f"arxiv:{index}", f"Arxiv database {index}", "A database paper body.",
            source="arxiv", url=f"https://arxiv.org/abs/{index}",
            content_hash=f"aa11bb2{index}",
            raw_text="<raw>A database paper body.</raw>"))
    capsys.readouterr()

    # the scoped-and-truncated read: `--source web` AND `--limit 4`, both filters live
    scoped = run_context(
        capsys, "database", "--budget", "index", "--source", "web", "--limit", "4")
    fidelity = _fidelity_line(scoped)
    returned, matched = _coverage_top_of(scoped)

    # the Coverage line proves BOTH filters compose: the cap truncates web's 6 to 4
    # (`returned`), and the facet narrows the denominator to web's 6 (`matched`) —
    # never the library-wide 8 an unscoped read would show under the same cap
    assert (returned, matched) == (4, 6)
    # the fidelity scope names only the post-facet, post-cap kept set, tied to the
    # scoped-and-truncated Coverage `returned` (parsed from both rendered lines, so
    # the two numbers are tied, not independently hardcoded)
    assert _fidelity_scope(fidelity) == returned          # (of 4)
    assert _fidelity_scope(fidelity) != matched           # never the scoped-untruncated 6
    # the tier counts sum to that kept set, not any pre-filter count
    counts = _fidelity_counts(fidelity)
    assert sum(counts.values()) == returned               # sums to 4, not 6 or 8
    # the kept 4 of web's {3 full, 3 partial} must span both tiers (pigeonhole: only
    # 3 of either exist), so the line is a real holdings split over the
    # scoped-and-truncated scope, not accidentally all-one-tier
    assert counts.get("full") and counts.get("partial")

    # non-vacuous on the FACET axis under truncation: the *unscoped* read at the same
    # cap sees the whole library's 8 matches (top 4 of 8), so the scoped read
    # genuinely narrowed the denominator — it never reverted to the
    # unscoped-but-truncated set (whose `(of 4)` shares the number but not the scope)
    unscoped = run_context(capsys, "database", "--budget", "index", "--limit", "4")
    _, unscoped_matched = _coverage_top_of(unscoped)
    assert unscoped_matched == 8
    assert matched != unscoped_matched                    # 6 (web) ≠ 8 (library)

    # non-vacuous on the TRUNCATION axis under facet scope: the *untruncated* scoped
    # read names web's full 6 (of 6), so the cap genuinely truncated — it never
    # reverted to the scoped-but-untruncated set
    scoped_untruncated = _fidelity_line(
        run_context(capsys, "database", "--budget", "index", "--source", "web"))
    assert _fidelity_scope(scoped_untruncated) == 6
    assert _fidelity_scope(fidelity) != _fidelity_scope(scoped_untruncated)  # 4 ≠ 6


# --- per-source custody breakdown (roadmap H149) ---------------------------


def _seed_multi_source(db):
    """Two `web` scrolls (verified + drifted) and one never-checked `arxiv`.

    Every title carries "database" so a `database` query covers the whole scope.
    web: fidelity full 2, drift verified 1 + drifted 1. arxiv: fidelity full 1,
    drift unverified 1 — a non-trivial multi-source custody split (the sources
    differ in custody, which is what a per-source breakdown must surface).
    """
    insert_item(db, make_item(
        "web:full", "Full database", "A full database body.",
        source="web", url="https://web.example/full",
        content_hash="deadbeef", raw_text="<raw>A full database body.</raw>"))
    insert_item(db, make_item(
        "web:moved", "Moved database", "A moved database body.",
        source="web", url="https://web.example/moved",
        content_hash="beefcafe", raw_text="<raw>A moved database body.</raw>"))
    insert_item(db, make_item(
        "arxiv:1", "Arxiv database paper", "A database paper body.",
        source="arxiv", url="https://arxiv.org/abs/1",
        content_hash="aa11bb22", raw_text="<raw>A database paper body.</raw>"))
    record_events(db, [_drift_event("web:full", "unchanged", observed="deadbeef")])
    record_events(db, [_drift_event("web:moved", "drifted", observed="cafe1234")])


def test_context_carries_a_per_source_custody_breakdown(scrolls_home, capsys):
    # roadmap H149: a multi-source model-facing bundle names which source's
    # custody is weakest within the scope, under the scope `_Custody:_` headline
    # (sources sorted) — the context-surface counterpart of the bundle briefing.
    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert "_By source:_" in out
    # the per-source recheck coverage rides each bullet too (roadmap H158)
    assert (
        "- `arxiv` — 1 scroll(s) · fidelity full 1 · drift unverified 1"
        " · coverage 0/1" in out
    )
    assert (
        "- `web` — 2 scroll(s) · fidelity full 2 · drift verified 1, drifted 1"
        " · coverage 2/2" in out
    )


def test_context_per_source_breakdown_sums_to_the_scope_headline(scrolls_home, capsys):
    # the rendered lines come straight from the shared primitive, and the
    # per-source tallies sum to the scope headline's whole-scope counts (H45/H104)
    from scrolls.custody import (
        custody_counts,
        custody_counts_by_source,
        latest_events,
        render_custody_by_source,
    )
    from scrolls.items import list_items

    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)
    items = list_items(db)
    verdicts = latest_events(db)
    by_source = custody_counts_by_source(items, verdicts)

    out = run_context(capsys, "database")
    expected = render_custody_by_source(by_source)
    assert expected  # the seed is genuinely multi-source (non-vacuous)
    for line in expected:
        assert line in out

    whole = custody_counts(items, verdicts)
    summed_tiers = {tier: 0 for tier in ("full", "partial", "reference")}
    summed_drift = {p: 0 for p in ("verified", "unverified", "drifted", "rotted", "error")}
    for counts in by_source.values():
        for tier, n in counts["tiers"].items():
            summed_tiers[tier] += n
        for posture, n in counts["drift"].items():
            summed_drift[posture] += n
    assert summed_tiers == whole["tiers"]
    assert summed_drift == whole["drift"]


def test_context_per_source_breakdown_gated_off_index(scrolls_home, capsys):
    # like the scope headline, the per-source split is gated to `connected`/`full`
    # — the leanest `index` tier stays a bare catalog (H47 gate)
    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "index")
    assert "_By source:_" not in out
    assert "_Custody:" not in out
    assert "## Best Matches" in out


def test_context_per_source_breakdown_present_from_connected_up(scrolls_home, capsys):
    # the split rides `connected` (no excerpts) just as the scope headline does
    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "connected")
    assert "_By source:_" in out
    assert "- `arxiv` — 1 scroll(s)" in out


def test_context_per_source_breakdown_omitted_for_a_single_source(scrolls_home, capsys):
    # the whole-scope headline already says everything when there is one source
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "web:a", "A database", "A database body.", source="web",
        url="https://web/a"))
    insert_item(db, make_item(
        "web:b", "B database", "B database body.", source="web",
        url="https://web/b"))
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert "_Custody:" in out
    assert "_By source:_" not in out


def test_context_per_source_breakdown_empty_scope_is_a_no_op(scrolls_home, capsys):
    # an empty scope carries no headline and no per-source split (honest no-op)
    main(["init"])
    capsys.readouterr()

    out = run_context(capsys, "nothingmatcheshere")
    assert "_By source:_" not in out
    assert "No matching scrolls." in out


def test_context_per_source_breakdown_mcp_parity(scrolls_home):
    # the MCP twin routes through the same build_context, so it carries the
    # identical per-source line (CLI ≡ MCP)
    from scrolls.mcp_server import get_context_bundle

    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)

    bundle = get_context_bundle("database")
    assert "_By source:_" in bundle
    assert (
        "- `arxiv` — 1 scroll(s) · fidelity full 1 · drift unverified 1"
        " · coverage 0/1" in bundle
    )
    assert (
        "- `web` — 2 scroll(s) · fidelity full 2 · drift verified 1, drifted 1"
        " · coverage 2/2" in bundle
    )


# --- readable weakest-source `_Attention:_` line (roadmap H159) --------------


def test_context_carries_a_weakest_source_attention_line(scrolls_home, capsys):
    # roadmap H159: a model-facing bundle names the single source with the most
    # actionable loss + the recheck command, skimmed before the per-source map.
    # In `_seed_multi_source`, web carries the only loss (1 drifted).
    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert (
        "_Attention: source `web` carries the most drift (1 drifted) — "
        "recheck with `scrolls verify --source web`._" in out
    )
    assert out.index("_Attention:") < out.index("_By source:_")


def test_context_attention_line_converges_with_weakest_source(scrolls_home, capsys):
    # the line is the shared `weakest_source`/`render_custody_attention` over the
    # bundle scope's own `custody_counts_by_source`, so it names the same source as
    # the JSON `attention` flag status/maintain carry, by construction
    from scrolls.custody import (
        custody_counts_by_source,
        latest_events,
        render_custody_attention,
        weakest_source,
    )
    from scrolls.items import list_items

    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)
    items = list_items(db)
    verdicts = latest_events(db)
    by_source = custody_counts_by_source(items, verdicts)

    out = run_context(capsys, "database")
    expected = render_custody_attention(by_source)
    assert expected  # the seed is genuinely multi-source with loss (non-vacuous)
    for line in expected:
        assert line in out
    assert weakest_source(by_source)["source"] == "web"


def test_context_attention_line_gated_off_index(scrolls_home, capsys):
    # like the scope headline/per-source split, the attention line is gated to
    # `connected`/`full` — the leanest `index` tier stays a bare catalog (H47 gate)
    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "index")
    assert "_Attention:" not in out
    assert "## Best Matches" in out


def test_context_attention_line_present_from_connected_up(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "connected")
    assert "_Attention: source `web`" in out


def test_context_attention_line_omitted_for_a_single_source(scrolls_home, capsys):
    # one source never stands out, even when it carries drift (the JSON flag's
    # single-source honest absence)
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "web:moved", "Moved database", "A moved database body.", source="web",
        url="https://web/moved", content_hash="beefcafe",
        raw_text="<raw>A moved database body.</raw>"))
    record_events(db, [_drift_event("web:moved", "drifted", observed="cafe1234")])
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert "_Custody:" in out
    assert "_Attention:" not in out


def test_context_attention_line_omitted_for_a_clean_multi_source_scope(scrolls_home, capsys):
    # multi-source but no drifted/rotted loss → the split renders, no pointer
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "web:ok", "OK database", "An ok database body.", source="web",
        url="https://web/ok", content_hash="deadbeef",
        raw_text="<raw>An ok database body.</raw>"))
    insert_item(db, make_item(
        "arxiv:2", "Arxiv database note", "A database note body.", source="arxiv",
        url="https://arxiv.org/abs/2", content_hash="aa11bb22",
        raw_text="<raw>A database note body.</raw>"))
    record_events(db, [_drift_event("web:ok", "unchanged", observed="deadbeef")])
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert "_By source:_" in out
    assert "_Attention:" not in out


def test_context_attention_line_mcp_parity(scrolls_home):
    # the MCP twin routes through the same build_context, so the attention line
    # rides MCP identically (CLI ≡ MCP)
    from scrolls.mcp_server import get_context_bundle

    main(["init"])
    db = get_paths().db_path
    _seed_multi_source(db)

    bundle = get_context_bundle("database")
    assert (
        "_Attention: source `web` carries the most drift (1 drifted) — "
        "recheck with `scrolls verify --source web`._" in bundle
    )


# --- readable work-level at-risk `_At-risk work:_` line (roadmap H264) --------


def _ref_item(item_id, title, doi, **overrides):
    """A reference-only representation (no content) of the work named by `doi`."""
    item = make_item(
        item_id, title, "ignored", links=(f"https://doi.org/{doi}",), **overrides)
    return dataclasses.replace(
        item, raw_text=None, extracted_text=None, summary=None, content_hash=None)


def _seed_at_risk_work(db):
    """One at-risk multi-rep work (Z, all-reference) + one safely-held work (Y).

    Work Z (10.3000/z): two reference-only reps (no full form) → at risk, the lowest
    custody ceiling. Work Y (10.2000/y): a full + never-checked preprint (unverified
    ∈ the safe set → safely held) + a reference record. Both titles carry "database"
    so a `database` query covers the whole scope. 2 works, 1 at risk → Z is named.
    """
    insert_item(db, _ref_item(
        "arxiv:zref", "Zeta database preprint", "10.3000/z",
        source="arxiv", url="https://arxiv.org/abs/zref"))
    insert_item(db, _ref_item(
        "crossref:10.3000/z", "Zeta database record", "10.3000/z",
        source="crossref", url="https://doi.org/10.3000/z"))
    insert_item(db, make_item(
        "arxiv:yfull", "Ypsilon database preprint", "A full database body.",
        source="arxiv", url="https://arxiv.org/abs/yfull",
        links=("https://doi.org/10.2000/y",), content_hash="deadbeef",
        raw_text="<raw>A full database body.</raw>"))
    insert_item(db, _ref_item(
        "crossref:10.2000/y", "Ypsilon database record", "10.2000/y",
        source="crossref", url="https://doi.org/10.2000/y"))


def test_context_carries_an_at_risk_work_line(scrolls_home, capsys):
    # roadmap H264: a model-facing bundle names the single work no representation
    # safely holds — the consolidation counterpart of the per-source `_Attention:_`.
    main(["init"])
    db = get_paths().db_path
    _seed_at_risk_work(db)
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert (
        "_At-risk work: `10.3000/z` — no representation is both full and unmoved "
        "(best held reference, safest drift unverified); 1 work(s) at risk._" in out
    )
    # skimmed above the per-source map, like the per-source `_Attention:_` line
    assert out.index("_At-risk work:") < out.index("_By source:_")


def test_context_at_risk_work_line_converges_with_at_risk_signal(scrolls_home, capsys):
    # the line is the shared `render_at_risk_works`/`at_risk_signal` over the bundle
    # scope's own clustered works, so it names the same work as `doctor`'s
    # `custody.works`/MCP `get_library_health` by construction
    from scrolls.custody import latest_events
    from scrolls.items import list_items
    from scrolls.works import at_risk_signal, render_at_risk_works, works_over

    main(["init"])
    db = get_paths().db_path
    _seed_at_risk_work(db)
    items = list_items(db)
    verdicts = latest_events(db)

    out = run_context(capsys, "database")
    expected = render_at_risk_works(items, verdicts)
    assert expected  # the seed genuinely carries an at-risk work (non-vacuous)
    for line in expected:
        assert line in out
    assert at_risk_signal(works_over(items), verdicts)["most_at_risk"]["doi"] == "10.3000/z"


def test_context_at_risk_work_line_gated_off_index(scrolls_home, capsys):
    # like the scope headline/attention line, gated to `connected`/`full` — the
    # leanest `index` tier reads no ledger, so it makes no drift-bearing claim
    main(["init"])
    db = get_paths().db_path
    _seed_at_risk_work(db)
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "index")
    assert "_At-risk work:" not in out
    assert "## Best Matches" in out


def test_context_at_risk_work_line_present_from_connected_up(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    _seed_at_risk_work(db)
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "connected")
    assert "_At-risk work: `10.3000/z`" in out


def test_context_at_risk_work_line_omitted_when_no_work_at_risk(scrolls_home, capsys):
    # a single safely-held work (full + never-checked) → honest absence, no pointer
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "arxiv:yfull", "Ypsilon database preprint", "A full database body.",
        source="arxiv", url="https://arxiv.org/abs/yfull",
        links=("https://doi.org/10.2000/y",), content_hash="deadbeef",
        raw_text="<raw>A full database body.</raw>"))
    insert_item(db, _ref_item(
        "crossref:10.2000/y", "Ypsilon database record", "10.2000/y",
        source="crossref", url="https://doi.org/10.2000/y"))
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert "_Custody:" in out
    assert "_At-risk work:" not in out


def test_context_at_risk_work_line_mcp_parity(scrolls_home):
    # the MCP twin routes through the same build_context, so the line rides MCP
    # identically (CLI ≡ MCP), the consolidation counterpart of the attention parity
    from scrolls.mcp_server import get_context_bundle

    main(["init"])
    db = get_paths().db_path
    _seed_at_risk_work(db)

    bundle = get_context_bundle("database")
    assert (
        "_At-risk work: `10.3000/z` — no representation is both full and unmoved "
        "(best held reference, safest drift unverified); 1 work(s) at risk._"
        in bundle
    )


# --- readable import-conflict `_Conflicts:_` line (roadmap H277) --------------
# The readable completion of H275's JSON `custody.conflicts` aggregate (ADR 0104):
# the conflict-axis counterpart of the drift `_Attention:_` line, gated to
# `connected`+ like the headline (a ledger read), naming no command (the `reconcile`
# act is roadmap H276). Honest absence when no held item carries an unresolved
# import conflict.


def _record_conflict(db, item_id, *, held, incoming):
    """Record an unresolved import-conflict event on a held item (H274 shape)."""
    from scrolls.custody import conflict_event

    record_events(
        db,
        [conflict_event(
            item_id, held_hash=held, incoming_hash=incoming,
            now="2026-06-22T00:00:00+00:00")],
    )


def test_context_carries_a_conflicts_line(scrolls_home, capsys):
    # roadmap H277: a held item carrying an unresolved import conflict surfaces one
    # `_Conflicts:_` line in the model-facing bundle
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database", "Body.",
                              content_hash="deadbeef"))
    _record_conflict(db, "wikipedia:en:SQLite", held="deadbeef", incoming="moved")
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert "_Conflicts: 1 item(s) carry an unresolved import conflict._" in out
    assert out.index("_Conflicts:") > out.index("_Custody:")


def test_context_conflicts_line_converges_with_doctor(scrolls_home, capsys):
    # the line folds the *same* `unresolved_conflicts` `doctor`'s `custody.conflicts`
    # reads, so the readable count and the JSON aggregate cannot disagree
    from scrolls.doctor import run_doctor

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database", "B.",
                              content_hash="deadbeef"))
    insert_item(db, make_item("wikipedia:en:Postgres", "Postgres database", "B.",
                              content_hash="deadbeef"))
    _record_conflict(db, "wikipedia:en:SQLite", held="deadbeef", incoming="moved")
    _record_conflict(db, "wikipedia:en:Postgres", held="deadbeef", incoming="moved")
    capsys.readouterr()

    out = run_context(capsys, "database")
    items = run_doctor(get_paths())["custody"]["conflicts"]["items"]
    assert items == 2
    assert f"_Conflicts: {items} item(s) carry an unresolved import conflict._" in out


def test_context_conflicts_line_gated_off_index(scrolls_home, capsys):
    # the `index` tier reads no ledger, so it makes no conflict claim (the H47 gate),
    # exactly like the headline/`_Attention:_`/`_At-risk work:_` lines
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database", "Body.",
                              content_hash="deadbeef"))
    _record_conflict(db, "wikipedia:en:SQLite", held="deadbeef", incoming="moved")
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "index")
    assert "_Conflicts:" not in out
    assert "## Best Matches" in out


def test_context_conflicts_line_present_from_connected_up(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database", "Body.",
                              content_hash="deadbeef"))
    _record_conflict(db, "wikipedia:en:SQLite", held="deadbeef", incoming="moved")
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "connected")
    assert "_Conflicts: 1 item(s) carry an unresolved import conflict._" in out


def test_context_conflicts_line_omitted_when_clean(scrolls_home, capsys):
    # no recorded conflict → honest absence (the no-op shape)
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database", "Body."))
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert "_Custody:" in out
    assert "_Conflicts:" not in out


def test_context_conflicts_line_mcp_parity(scrolls_home):
    # the MCP twin routes through the same build_context, so the conflict line rides
    # MCP identically (CLI ≡ MCP)
    from scrolls.mcp_server import get_context_bundle

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database", "Body.",
                              content_hash="deadbeef"))
    _record_conflict(db, "wikipedia:en:SQLite", held="deadbeef", incoming="moved")

    bundle = get_context_bundle("database")
    assert "_Conflicts: 1 item(s) carry an unresolved import conflict._" in bundle


# --- readable archive-integrity `_Archive:_` line (roadmap H320) --------------
# The H319 shareable-bundle surface lifted to the agent context briefing: one
# `_Archive:_` line when an in-scope item's archived prior is corrupt — its
# advertised `prior_hash` no longer equals its snapshot's `content_hash`, a
# custody-honesty bug invisible until restore. The archive-axis sibling of the
# `_Conflicts:_` line above, folding the *same* `archive_integrity_block` over the
# in-scope `archived_records` and rendered by the *same* `archive_integrity_headline`
# the `maintain` summary and the `export bundle` line use. Gated to `connected`+
# like the headline (the leanest `index` tier reads no recovery store); honest
# absence on a clean/empty scope.


def _seed_corrupt_prior(db, item_id, title, *, archived_at="2026-06-22T00:00:00+00:00"):
    """Hold a matchable item, archive a prior via an adoption, then tamper the
    archived row's `prior_hash` so it diverges from its snapshot's `content_hash`
    — the corrupt recovery store the integrity alarm must name. The held copy keeps
    its title (so the context query still matches it)."""
    import sqlite3

    from scrolls.items import adopt_incoming

    held = make_item(item_id, title, "Body.", content_hash="deadbeef")
    insert_item(db, held)
    incoming = dataclasses.replace(held, extracted_text="a later capture",
                                   content_hash="moved")
    adopt_incoming(db, incoming, archived_at=archived_at)
    conn = sqlite3.connect(db)
    with conn:
        conn.execute(
            "UPDATE item_archive SET prior_hash = ? WHERE item_id = ?",
            ("sha256:tampered", item_id),
        )
    conn.close()


def test_context_carries_an_archive_integrity_line(scrolls_home, capsys):
    # roadmap H320: an in-scope item whose archived prior is corrupt surfaces one
    # `_Archive:_` line — the H319 shareable-bundle surface on the context briefing.
    main(["init"])
    db = get_paths().db_path
    _seed_corrupt_prior(db, "wikipedia:en:SQLite", "SQLite database")
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert "_Archive: 1 prior(s) fail integrity (prior_hash ≠ snapshot)._" in out
    # grouped with the divergence lines, below the scope custody headline
    assert out.index("_Archive:") > out.index("_Custody:")


def test_context_archive_line_converges_with_doctor(scrolls_home, capsys):
    # the count is the *same* `archive_integrity_block` fold `doctor`'s
    # `custody.archive` reads — here the in-scope set is the whole library, so the
    # readable line and the JSON audit report the same mismatch count
    from scrolls.doctor import run_doctor

    main(["init"])
    db = get_paths().db_path
    _seed_corrupt_prior(db, "wikipedia:en:SQLite", "SQLite database")
    _seed_corrupt_prior(db, "wikipedia:en:Postgres", "Postgres database")
    capsys.readouterr()

    out = run_context(capsys, "database")  # matches both held items
    mismatched = run_doctor(get_paths())["custody"]["archive"]["mismatched"]
    assert mismatched == 2
    assert f"_Archive: {mismatched} prior(s) fail integrity" in out


def test_context_archive_line_gated_off_index(scrolls_home, capsys):
    # the `index` tier reads no recovery store, so it makes no archive-integrity
    # claim (the H47 gate), exactly like the headline/`_Conflicts:_`/`_At-risk work:_`
    main(["init"])
    db = get_paths().db_path
    _seed_corrupt_prior(db, "wikipedia:en:SQLite", "SQLite database")
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "index")
    assert "_Archive:" not in out
    assert "## Best Matches" in out


def test_context_archive_line_present_from_connected_up(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    _seed_corrupt_prior(db, "wikipedia:en:SQLite", "SQLite database")
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "connected")
    assert "_Archive: 1 prior(s) fail integrity (prior_hash ≠ snapshot)._" in out


def test_context_archive_line_is_in_scope(scrolls_home, capsys):
    # in-scope semantics (the `_Conflicts:_` precedent): a corrupt prior on an item
    # *outside* the query scope is not named — the briefing reports custody honesty
    # for the items it actually carries, not the whole library.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database", "Body."))
    _seed_corrupt_prior(db, "wikipedia:en:Tarragon", "Tarragon herb")  # off-scope
    capsys.readouterr()

    out = run_context(capsys, "database")  # matches SQLite only
    assert "SQLite database" in out
    assert "Tarragon" not in out
    assert "_Archive:" not in out  # the off-scope corruption is not the briefing's


def test_context_archive_line_omitted_when_clean(scrolls_home, capsys):
    # honest absence: a clean (untampered) archived prior → no `_Archive:` line
    main(["init"])
    db = get_paths().db_path
    held = make_item("wikipedia:en:SQLite", "SQLite database", "Body.",
                     content_hash="deadbeef")
    insert_item(db, held)
    from scrolls.items import adopt_incoming
    adopt_incoming(db, dataclasses.replace(held, extracted_text="later",
                                           content_hash="moved"),
                   archived_at="2026-06-22T00:00:00+00:00")
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert "_Custody:" in out
    assert "_Archive:" not in out


def test_context_archive_line_mcp_parity(scrolls_home):
    # the MCP twin routes through the same build_context, so the archive line rides
    # MCP identically (CLI ≡ MCP)
    from scrolls.mcp_server import get_context_bundle

    main(["init"])
    db = get_paths().db_path
    _seed_corrupt_prior(db, "wikipedia:en:SQLite", "SQLite database")

    bundle = get_context_bundle("database")
    assert "_Archive: 1 prior(s) fail integrity (prior_hash ≠ snapshot)._" in bundle


# --- readable content-duplicate `_Duplicates:_` line (roadmap H331) -----------
# The H319/H331 shareable-`export bundle` surface lifted to the agent context
# briefing: one `_Duplicates:_` line when ≥2 in-scope items hold byte-identical
# content under different ids (the same `content_hash` — a genuinely new custody
# shape, custody-vision §2.7). The content-identity sibling of the `_Archive:_` line
# above, folding the *same* `content_duplicate_groups` via the *same*
# `duplicates_headline` (`render_content_duplicates`) the bundle line and `maintain`'s
# summary use. Gated to `connected`+ like the headline. Folded over the **uncollapsed**
# `scope_items` (like `_At-risk work:_`, not the per-item `_Conflicts:_`/`_Archive:_`
# lines): content identity is relational across distinct ids, so a work-collapse must
# not hide two byte-identical representations of one work. Report-only; omit-when-clean.


def test_context_carries_a_content_duplicates_line(scrolls_home, capsys):
    # roadmap H331: ≥2 in-scope items holding byte-identical content surface one
    # `_Duplicates:_` line — the H319/H331 shareable-bundle surface on the context
    # briefing, the readable completion of `doctor`'s `custody.content_duplicates`.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database",
                              "A database body.", content_hash="deadbeef"))
    insert_item(db, make_item("wikipedia:en:Mirror", "SQLite database mirror",
                              "A mirror body.", content_hash="deadbeef"))
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert "_Duplicates: 1 group(s) of byte-identical content (2 item(s))._" in out
    # grouped with the divergence lines, below the scope custody headline
    assert out.index("_Duplicates:") > out.index("_Custody:")


def test_context_duplicates_line_converges_with_doctor(scrolls_home, capsys):
    # the count is the *same* `content_duplicate_groups` fold `doctor`'s
    # `custody.content_duplicates` reads — here the in-scope set is the whole library,
    # so the readable line and the JSON audit report the same group/item count
    from scrolls.doctor import run_doctor

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:A", "Alpha database", "A body.",
                              content_hash="deadbeef"))
    insert_item(db, make_item("wikipedia:en:B", "Beta database", "B body.",
                              content_hash="deadbeef"))
    capsys.readouterr()

    out = run_context(capsys, "database")  # matches both held items
    dup = run_doctor(get_paths())["custody"]["content_duplicates"]
    assert dup["total_groups"] == 1 and dup["total_items"] == 2
    assert (
        f"_Duplicates: {dup['total_groups']} group(s) of byte-identical content "
        f"({dup['total_items']} item(s))._" in out
    )


def test_context_duplicates_line_sees_within_work_copies(scrolls_home, capsys):
    # the decisive scope choice (roadmap H331): the line folds the *uncollapsed*
    # `scope_items`, not the work-collapsed `items` — two byte-identical
    # representations of ONE work (the H329 preprint-mirrored-into-DOI case) collapse
    # to a single canonical id in the readable Best Matches (ADR 0101), which would
    # hide the group; folding the uncollapsed set keeps both ids, so the redundancy is
    # named (it patterns with `_At-risk work:_`, not the per-item lines).
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "arxiv:dup", "Delta database preprint", "A full database body.",
        source="arxiv", url="https://arxiv.org/abs/dup",
        links=("https://doi.org/10.7000/dup",),
        content_hash="deadbeef", raw_text="<raw>A full database body.</raw>"))
    insert_item(db, make_item(
        "crossref:10.7000/dup", "Delta database record", "A full database body.",
        source="crossref", url="https://doi.org/10.7000/dup",
        links=("https://doi.org/10.7000/dup",),
        content_hash="deadbeef", raw_text="<raw>A full database body.</raw>"))
    capsys.readouterr()

    out = run_context(capsys, "database")
    # the two reps collapse to one canonical Best Match (the work-collapse, ADR 0101)…
    assert out.count("### ") == 1
    # …but the uncollapsed scope still sees both byte-identical holdings
    assert "_Duplicates: 1 group(s) of byte-identical content (2 item(s))._" in out


def test_context_duplicates_line_gated_off_index(scrolls_home, capsys):
    # the `index` tier makes no custody claim (the H47 gate), exactly like the
    # headline/`_Conflicts:_`/`_At-risk work:_`/`_Archive:_`
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:A", "Alpha database", "A body.",
                              content_hash="deadbeef"))
    insert_item(db, make_item("wikipedia:en:B", "Beta database", "B body.",
                              content_hash="deadbeef"))
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "index")
    assert "_Duplicates:" not in out
    assert "## Best Matches" in out


def test_context_duplicates_line_is_in_scope(scrolls_home, capsys):
    # in-scope semantics (the `_Conflicts:_` precedent): a content group split by the
    # scope reads only its in-scope members — a byte-identical pair where one copy is
    # off-query has only one in-scope member, so it is not a duplicate within the
    # briefing.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database", "A body.",
                              content_hash="deadbeef"))
    insert_item(db, make_item("wikipedia:en:Tarragon", "Tarragon herb", "A body.",
                              content_hash="deadbeef"))  # same bytes, off-scope
    capsys.readouterr()

    out = run_context(capsys, "database")  # matches SQLite only
    assert "SQLite database" in out
    assert "Tarragon" not in out
    assert "_Duplicates:" not in out  # only one in-scope member of the group


def test_context_duplicates_line_omitted_when_unique(scrolls_home, capsys):
    # honest absence: every in-scope item holds distinct content → no `_Duplicates:` line
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:A", "Alpha database", "A body.",
                              content_hash="aaaa"))
    insert_item(db, make_item("wikipedia:en:B", "Beta database", "B body.",
                              content_hash="bbbb"))
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert "_Custody:" in out
    assert "_Duplicates:" not in out


def test_context_duplicates_line_mcp_parity(scrolls_home):
    # the MCP twin routes through the same build_context, so the duplicates line rides
    # MCP identically (CLI ≡ MCP)
    from scrolls.mcp_server import get_context_bundle

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:A", "Alpha database", "A body.",
                              content_hash="deadbeef"))
    insert_item(db, make_item("wikipedia:en:B", "Beta database", "B body.",
                              content_hash="deadbeef"))

    bundle = get_context_bundle("database")
    assert "_Duplicates: 1 group(s) of byte-identical content (2 item(s))._" in bundle


# --- readable whole-library `_Posture:_` line (roadmap H371) ------------------
#
# The shareable-briefing leg of the custody-posture theme (custody-vision §3.1,
# ADR 0107) on the agent context bundle: `doctor`'s `custody.posture` verdict
# (sound/attention/at_risk + reasons, H369) travels with the briefing. Unlike the
# in-scope `_Conflicts:_`/`_Archive:_`/`_Duplicates:_` siblings, this is the
# *whole-library* verdict (posture is a library-level fact, H369) and is **rendered
# always** (even the clean `sound` verdict, the H370 resolve), from the shared
# `render_posture`. Gated to `connected`+ like the headline (the `index` tier makes
# no custody claim — and the posture audit reads the ledger the lean tier skips).


def _drift_item(db, item_id, title):
    """Hold a matchable item and record a `drifted` event — the soft source-drift
    concern that moves the whole-library posture to `attention`. `markdown_path=None`
    so no `missing_scroll` integrity issue fires (no scroll file written here). The
    body is non-matching ("Body.") so query scope is driven by the title alone — an
    off-scope title genuinely stays out of the bundle."""
    insert_item(db, make_item(item_id, title, "Body.",
                              content_hash="deadbeef", markdown_path=None))
    record_events(db, [CustodyEvent(
        item_id=item_id, checked_at="2026-06-20T00:00:00+00:00",
        status="drifted", prior_hash="deadbeef", observed_hash="moved")])


def test_context_carries_a_posture_line(scrolls_home, capsys):
    # roadmap H371: a library with a soft custody concern (source drift) surfaces one
    # `_Posture:_` line — the H370 maintain surface lifted to the context briefing.
    main(["init"])
    db = get_paths().db_path
    _drift_item(db, "wikipedia:en:SQLite", "SQLite database")
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert "_Posture: attention (source_drift)._" in out
    # grouped with the divergence lines, below the scope custody headline
    assert out.index("_Posture:") > out.index("_Custody:")


def test_context_posture_line_renders_even_on_a_sound_library(scrolls_home, capsys):
    # the H370 always-render divergence: the clean `sound` verdict still renders,
    # unlike the omit-when-clean `_Conflicts:_`/`_Archive:_`/`_Duplicates:_` siblings.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database",
                              "A database body.", markdown_path=None))
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert "_Posture: sound._" in out
    assert "_Conflicts:" not in out


def test_context_posture_line_is_whole_library_not_in_scope(scrolls_home, capsys):
    # the documented divergence from the in-scope siblings: posture is a library-level
    # fact (H369), so a drift on an item OUTSIDE the query scope still moves the verdict.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item("wikipedia:en:SQLite", "SQLite database",
                              "A database body.", markdown_path=None))
    _drift_item(db, "wikipedia:en:Tarragon", "Tarragon herb")  # off-scope drift
    capsys.readouterr()

    out = run_context(capsys, "database")  # matches SQLite only
    assert "Tarragon" not in out
    assert "_Posture: attention (source_drift)._" in out  # off-scope drift counts


def test_context_posture_line_converges_with_doctor(scrolls_home, capsys):
    # the verdict is the *same* `_assess_custody_posture` fold `doctor`'s
    # `custody.posture` reads — the readable line and the JSON audit name the same
    # whole-library verdict + reasons by construction (the H373 convergence).
    from scrolls.doctor import run_doctor

    main(["init"])
    db = get_paths().db_path
    _drift_item(db, "wikipedia:en:SQLite", "SQLite database")
    capsys.readouterr()

    out = run_context(capsys, "database")
    posture = run_doctor(get_paths())["custody"]["posture"]
    reasons = f" ({', '.join(posture['reasons'])})" if posture["reasons"] else ""
    assert f"_Posture: {posture['verdict']}{reasons}._" in out


def test_context_posture_line_gated_off_index(scrolls_home, capsys):
    # the `index` tier makes no custody claim (the H47 gate), exactly like the
    # headline/`_Conflicts:_`/`_At-risk work:_`/`_Archive:_`/`_Duplicates:_`
    main(["init"])
    db = get_paths().db_path
    _drift_item(db, "wikipedia:en:SQLite", "SQLite database")
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "index")
    assert "_Posture:" not in out
    assert "## Best Matches" in out


def test_context_posture_line_mcp_parity(scrolls_home):
    # the MCP twin routes through the same build_context, so the posture line rides
    # MCP identically (CLI ≡ MCP)
    from scrolls.mcp_server import get_context_bundle

    main(["init"])
    db = get_paths().db_path
    _drift_item(db, "wikipedia:en:SQLite", "SQLite database")

    bundle = get_context_bundle("database")
    assert "_Posture: attention (source_drift)._" in bundle


# --- readable per-source `_Refresh:_` line (roadmap H178) --------------------
#
# The enrichment/summary-axis counterpart of `_Attention:_` on the model-facing
# context bundle: which source's classifications/summaries are stale and the
# exact `classify --stale`/`kb --stale --source <S>` refresh. Gated to
# `connected`+ like the headline; over the same builders doctor's per-source debt
# maps fold.


def _refresh_provenance(ruleset):
    from scrolls.classify import ENGINE as RULES_ENGINE

    return {
        "fetched_at": "2026-06-12T00:00:00+00:00", "via": "test",
        "classified_by": RULES_ENGINE, "classified_basis": "documentation-url",
        "classified_ruleset": ruleset,
    }


def _seed_context_refresh_debt(db):
    """Stale classification on `web` + a stale summary spanning `web`+`arxiv`."""
    from scrolls.kb import ConceptSummary, save_concept_summary
    from scrolls.kb_llm import ENGINE as SUMMARY_ENGINE

    insert_item(db, make_item(
        "web:old-class", "Old database doc", "An old database doc.", source="web",
        url="https://web/old", category="documentation",
        provenance=_refresh_provenance("oldfingerprint")))
    insert_item(db, make_item(
        "web:db1", "Web database", "A web database note.", source="web",
        url="https://web/db1", concepts=("Databases",)))
    insert_item(db, make_item(
        "arxiv:db2", "Arxiv database", "An arxiv database note.", source="arxiv",
        url="https://arxiv.org/abs/db2", concepts=("Databases",)))
    save_concept_summary(db, ConceptSummary(
        slug="databases", display="Databases", summary="Old synthesis.",
        members_hash="stalefingerprint", engine=SUMMARY_ENGINE,
        model="claude-test", generated_at="2026-06-12T00:00:00+00:00"))


def test_context_carries_a_refresh_line(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    _seed_context_refresh_debt(db)
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert (
        "_Refresh: classifications stale in `web` — refresh with "
        "`scrolls classify --stale --source <S>`; summaries stale in `arxiv`, "
        "`web` — refresh with `scrolls kb --stale --source <S>`._" in out
    )


def test_context_refresh_line_gated_off_index(scrolls_home, capsys):
    # gated to `connected`/`full` like the headline — the leanest tier stays bare
    main(["init"])
    db = get_paths().db_path
    _seed_context_refresh_debt(db)
    capsys.readouterr()

    out = run_context(capsys, "database", "--budget", "index")
    assert "_Refresh:" not in out
    assert "## Best Matches" in out


def test_context_refresh_line_omitted_when_clean(scrolls_home, capsys):
    from scrolls.classify import RULESET_FINGERPRINT

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "web:fresh", "Fresh database", "A current database note.", source="web",
        url="https://web/fresh", category="documentation",
        provenance=_refresh_provenance(RULESET_FINGERPRINT)))
    capsys.readouterr()

    out = run_context(capsys, "database")
    assert "_Custody:" in out
    assert "_Refresh:" not in out  # honest absence


def test_context_refresh_line_mcp_parity(scrolls_home):
    # the MCP twin routes through the same build_context — CLI ≡ MCP
    from scrolls.mcp_server import get_context_bundle

    main(["init"])
    db = get_paths().db_path
    _seed_context_refresh_debt(db)

    bundle = get_context_bundle("database")
    assert "_Refresh: classifications stale in `web`" in bundle
    assert "summaries stale in `arxiv`, `web`" in bundle


# --- per-excerpt provenance tags at the `full` budget (H44 + H62) ----------


def _excerpt_block(out, heading):
    """The lines of one `### <heading>` excerpt block, up to the next section."""
    lines = out.splitlines()
    start = lines.index(f"### {heading}")
    block = []
    for line in lines[start + 1 :]:
        if line.startswith("### ") or line.startswith("## "):
            break
        block.append(line)
    return block


def test_context_full_excerpt_carries_classification_provenance(scrolls_home, capsys):
    # H44: how the category was derived rides each excerpt, the same view
    # `show`/`list`/`search` carry, rendered through the shared phrase
    from scrolls.classify import classify_item

    main(["init"])
    db = get_paths().db_path
    insert_item(db, classify_item(make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine with full-text search support.",
    )))
    capsys.readouterr()

    block = _excerpt_block(run_context(capsys, "database engine"), "SQLite")
    # a curated source → rules engine, curated-source basis, deterministic+current
    assert (
        "_classified by `rules-v1` (curated-source) · confidence deterministic, current_"
        in block
    )


def test_context_excerpt_classification_records_the_llm_model(scrolls_home, capsys):
    # the LLM engine's `model` rides the excerpt tag, as on the bundle briefing
    main(["init"])
    insert_item(get_paths().db_path, make_item(
        "web:llm", "A classified web post",
        "Some prose about a database engine, classified by a model.",
        source="web", url="https://ex.com/llm", category="reference",
        provenance={"classified_by": "llm-v1", "classified_model": "claude-x"},
    ))
    capsys.readouterr()

    block = _excerpt_block(run_context(capsys, "database engine"), "A classified web post")
    # inferred, and no freshness — no ruleset to compare (honest absence, H21)
    assert "_classified by `llm-v1` (model claude-x) · confidence inferred_" in block


def test_context_excerpt_classification_omitted_on_honest_absence(scrolls_home, capsys):
    # an unclassified item claims no method — the classification tag is dropped,
    # but the drift tag still rides the excerpt (the row shape stays stable)
    main(["init"])
    insert_item(get_paths().db_path, make_item(
        "web:plain", "An ordinary post",
        "Some plain prose about a database engine.",
        source="web", url="https://ex.com/plain",
    ))
    capsys.readouterr()

    block = _excerpt_block(run_context(capsys, "database engine"), "An ordinary post")
    assert not any(line.startswith("_classified") for line in block)
    assert "_drift `unverified` · never re-checked_" in block


def test_context_full_excerpt_carries_drift_posture(scrolls_home, capsys):
    # H62: whether the source has moved rides each excerpt, from the verify ledger
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine.",
        content_hash="deadbeef", raw_text="<raw>body</raw>",
    ))
    record_events(db, [_drift_event("wikipedia:en:SQLite", "drifted", observed="cafe1234")])
    capsys.readouterr()

    block = _excerpt_block(run_context(capsys, "database engine"), "SQLite")
    # H90: the drift tag also carries *as of when* the verdict was taken
    assert "_drift `drifted` · last seen 2026-06-14T00:00:00+00:00_" in block


def test_context_excerpt_drift_unverified_when_never_checked(scrolls_home, capsys):
    # honest absence on both axes: a never-checked item is `unverified`, stated
    # explicitly — never silently "clean" — and `never re-checked`, not a faked time
    main(["init"])
    insert_item(get_paths().db_path, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))
    capsys.readouterr()

    block = _excerpt_block(run_context(capsys, "database engine"), "SQLite")
    assert "_drift `unverified` · never re-checked_" in block


def test_context_excerpt_drift_matches_the_ledger_primitives(scrolls_home, capsys):
    # the per-excerpt posture and timestamp are the shared `custody.drift_posture`
    # / `custody.last_checked` over the latest verdict — so the excerpt reads the
    # same posture *and* staleness every other surface does
    from scrolls.custody import drift_posture, last_checked, latest_events

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
        content_hash="deadbeef", raw_text="<raw>body</raw>",
    ))
    record_events(db, [_drift_event("wikipedia:en:SQLite", "unchanged", observed="deadbeef")])
    capsys.readouterr()

    block = _excerpt_block(run_context(capsys, "database engine"), "SQLite")
    verdict = latest_events(db)["wikipedia:en:SQLite"]
    posture = drift_posture(verdict)
    checked = last_checked(verdict)
    assert posture == "verified"
    assert f"_drift `{posture}` · last seen {checked}_" in block


def test_context_excerpt_tags_absent_below_full(scrolls_home, capsys):
    # the per-excerpt tags are a `full`-only deepening (H10 depth honesty): the
    # `connected` tier has no Excerpts section, so no per-excerpt tag at all
    from scrolls.classify import classify_item

    main(["init"])
    insert_item(get_paths().db_path, classify_item(make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    )))
    capsys.readouterr()

    out = run_context(capsys, "database engine", "--budget", "connected")
    assert "## Excerpts" not in out
    assert "_classified" not in out
    # the scope `_Custody:` headline still carries the drift *count* at connected,
    # but no per-excerpt `_drift ` tag (that is a full-tier deepening)
    assert "_drift `" not in out


def test_context_excerpt_classification_phrase_matches_the_shared_view(scrolls_home, capsys):
    # cross-surface parity: the excerpt's classification segment is exactly the
    # shared `classification_phrase` over the item's own derived view — the same
    # rendering the bundle briefing (H35) uses, so they cannot drift apart
    from scrolls.classify import classify_item
    from scrolls.items import classification_phrase, classification_provenance

    main(["init"])
    db = get_paths().db_path
    item = classify_item(make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))
    insert_item(db, item)
    capsys.readouterr()

    block = _excerpt_block(run_context(capsys, "database engine"), "SQLite")
    expected = f"_classified {classification_phrase(classification_provenance(item))}_"
    assert expected in block


# --- same-work collapse in the bundle (ADR 0101) ---------------------------


def _insert_attention_pair(db):
    # an arXiv preprint and its published Crossref record: one work, two
    # near-identical matches for the same query
    insert_item(db, make_item(
        "arxiv:1706.03762", "Attention Is All You Need",
        "We propose the Transformer based on attention mechanisms.",
        source="arxiv", source_id="1706.03762", category="paper",
        links=("https://doi.org/10.5555/3295222",),
    ))
    insert_item(db, make_item(
        "crossref:10.5555/3295222", "Attention Is All You Need",
        "We propose the Transformer based on attention mechanisms.",
        source="crossref", source_id="10.5555/3295222", category="paper",
    ))


def test_context_collapses_same_work_representations(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    _insert_attention_pair(db)
    capsys.readouterr()

    out = run_context(capsys, "attention transformer")
    # exactly one Best-Matches entry for the work, not two
    assert out.count("Attention Is All You Need (`") == 1
    # the folded sibling and the canonical form are named on the kept line
    assert "same work as `crossref:10.5555/3295222`" in out
    assert "canonical `crossref:10.5555/3295222`" in out
    # the work is excerpted once — its content appears a single time
    assert out.count("We propose the Transformer based on attention mechanisms.") == 1
    # only the kept representation is linked
    assert "- [Attention Is All You Need]" in out
    assert out.count("- [Attention Is All You Need]") == 1


def test_collapse_by_work_folds_later_representations_of_a_seen_work():
    # deterministic over hits we construct, independent of BM25 tie-breaks
    from scrolls.context import _collapse_by_work
    from scrolls.search import SearchHit
    from scrolls.works import WorkRef

    def hit(item_id, *dois, canonical):
        works = tuple(
            WorkRef(doi=d, url=f"https://doi.org/{d}", canonical=canonical,
                    is_canonical=item_id == canonical, representations=2)
            for d in dois
        )
        return SearchHit(id=item_id, source="s", title=item_id, url="u",
                         stage="fetched", score=-1.0, snippet="", fidelity="full",
                         works=works)

    preprint = hit("arxiv:1706.03762", "10.5555/3295222", canonical="crossref:10.5555/3295222")
    published = hit("crossref:10.5555/3295222", "10.5555/3295222", canonical="crossref:10.5555/3295222")
    lone = hit("web:abc", canonical="")  # no works → never folds

    kept, folded = _collapse_by_work([preprint, published, lone])
    # the preprint ranked first, so it is kept; the published record folds in
    assert [h.id for h in kept] == ["arxiv:1706.03762", "web:abc"]
    assert folded == {"arxiv:1706.03762": ["crossref:10.5555/3295222"]}


def test_collapse_keeps_a_hit_that_brings_a_new_work():
    # a multi-work hit sharing one already-seen work but bringing another is kept
    from scrolls.context import _collapse_by_work
    from scrolls.search import SearchHit
    from scrolls.works import WorkRef

    def hit(item_id, *dois):
        works = tuple(
            WorkRef(doi=d, url=f"https://doi.org/{d}", canonical=item_id,
                    is_canonical=True, representations=2)
            for d in dois
        )
        return SearchHit(id=item_id, source="s", title=item_id, url="u",
                         stage="fetched", score=-1.0, snippet="", fidelity="full",
                         works=works)

    a = hit("a", "10.1000/x")
    b = hit("b", "10.1000/x", "10.2000/y")  # shares x, brings y → kept
    kept, folded = _collapse_by_work([a, b])
    assert [h.id for h in kept] == ["a", "b"]
    assert folded == {}


def test_work_note_marks_the_kept_hit_when_it_is_canonical():
    from scrolls.context import _work_note
    from scrolls.search import SearchHit
    from scrolls.works import WorkRef

    canonical_kept = SearchHit(
        id="crossref:10.5555/3295222", source="crossref", title="t", url="u",
        stage="fetched", score=-1.0, snippet="", fidelity="full",
        works=(WorkRef(doi="10.5555/3295222", url="https://doi.org/10.5555/3295222",
                       canonical="crossref:10.5555/3295222", is_canonical=True,
                       representations=2),))
    note = _work_note(canonical_kept, ["arxiv:1706.03762"])
    assert "same work as `arxiv:1706.03762`" in note
    assert "this is the canonical form" in note
    # no folded siblings → no note at all
    assert _work_note(canonical_kept, []) == ""


def test_context_does_not_collapse_unrelated_matches(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite database",
        "SQLite is a database engine with full text search.",
    ))
    insert_item(db, make_item(
        "wikipedia:en:Postgres", "Postgres database",
        "Postgres is a database engine with full text search.",
    ))
    capsys.readouterr()

    out = run_context(capsys, "database engine")
    # two distinct works (no shared DOI) — both kept, neither annotated
    assert "SQLite database (`wikipedia:en:SQLite`)" in out
    assert "Postgres database (`wikipedia:en:Postgres`)" in out
    assert "same work as" not in out


# --- the rank explanation on the bundle (roadmap H315) ----------------------


def _strength_line(out):
    return next(line for line in out.splitlines() if line.startswith("_Strength:"))


def _best_match_strengths(out):
    """The `· <band>` strength marker on each numbered Best-Matches line.

    The strength is the first ` · ` segment after the `N. title (`id`)[ — cat]`
    prefix (the work note, when present, follows it), so a fold over the lines
    that mirrors what the `_Strength:_` headline tallies.
    """
    bands = []
    in_best = False
    for line in out.splitlines():
        if line.startswith("## Best Matches"):
            in_best = True
            continue
        if in_best and line.startswith("## "):
            break
        if in_best and re.match(r"^\d+\. ", line):
            bands.append(line.split(" · ")[1])
    return bands


def _seed_strength_mix(db):
    """One title hit (strong), one summary-only (moderate), one body-only (weak)
    for the query `ranking` — each landing in exactly one strongest field."""
    insert_item(db, make_item(
        "wikipedia:en:Strong", "BM25 ranking guide", "a body about engines.",
        summary="a summary about engines.",
    ))  # `ranking` in the title → strong
    insert_item(db, make_item(
        "wikipedia:en:Moderate", "Plain engine title", "a body about engines.",
        summary="this summary discusses ranking functions.",
    ))  # `ranking` only in the summary → moderate
    insert_item(db, make_item(
        "wikipedia:en:Weak", "Another engine title", "deep in the body ranking appears.",
        summary="an unrelated engine summary.",
    ))  # `ranking` only in the body → weak


def test_context_best_match_lines_carry_a_strength_marker(scrolls_home, capsys):
    # roadmap H315: each match explains *why it ranked* — a `· <strength>` marker
    # naming the strongest field its query landed in (title → strong, summary →
    # moderate, body-only → weak). Non-vacuous: the three bands are distinct, so a
    # return-one-fixed-band stub would fail.
    main(["init"])
    _seed_strength_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "ranking")
    assert "(`wikipedia:en:Strong`) · strong" in out
    assert "(`wikipedia:en:Moderate`) · moderate" in out
    assert "(`wikipedia:en:Weak`) · weak" in out


def test_context_carries_a_strength_headline(scrolls_home, capsys):
    # the bundle-level rank-confidence summary beside the Coverage line: the
    # `tally_strength` fold over the kept matches (H313's histogram on the bundle).
    main(["init"])
    _seed_strength_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "ranking")
    assert _strength_line(out) == "_Strength: strong 1, moderate 1, weak 1 (of 3)._"


def test_context_strength_headline_folds_the_per_match_markers(scrolls_home, capsys):
    # the headline and the per-line markers can never disagree: the headline is the
    # tally of exactly the markers below it (the same `match_strength`, one fold).
    main(["init"])
    _seed_strength_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "ranking")
    from collections import Counter

    marker_counts = Counter(_best_match_strengths(out))
    line = _strength_line(out)
    for band, count in marker_counts.items():
        assert f"{band} {count}" in line
    assert f"(of {sum(marker_counts.values())})" in line


def test_context_strength_counts_a_collapsed_work_once(scrolls_home, capsys):
    # both representations of one work are strong title hits, but the bundle keeps
    # the work once (ADR 0101) — the headline counts it once (the kept set), not a
    # `strong 2` double-count, converging with the single Best-Matches marker.
    main(["init"])
    _insert_attention_pair(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "attention transformer")
    assert _strength_line(out) == "_Strength: strong 1 (of 1)._"
    assert _best_match_strengths(out) == ["strong"]


def test_context_strength_renders_at_every_budget_tier(scrolls_home, capsys):
    # the rank explanation is a ledger-free FTS fact (like fidelity), so the marker
    # and headline travel at every tier — including the leanest `index` catalog,
    # where an agent most needs to tell a strong match from a weak one before
    # spending budget on bodies.
    main(["init"])
    insert_item(get_paths().db_path, make_item(
        "wikipedia:en:BM25", "BM25 ranking", "BM25 is a ranking function.",
    ))
    capsys.readouterr()

    for budget in ("index", "connected", "full"):
        out = run_context(capsys, "ranking", "--budget", budget)
        assert "_Strength: strong 1 (of 1)._" in out
        assert "(`wikipedia:en:BM25`) · strong" in out


def test_context_strength_marker_precedes_the_work_note(scrolls_home, capsys):
    # marker placement: `· <strength>` sits between the category and the work note,
    # so a collapsed line reads `… — paper · strong · same work as …` (the strength
    # is a property of the match, the note a property of the fold).
    main(["init"])
    _insert_attention_pair(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "attention transformer")
    assert "· strong · same work as `crossref:10.5555/3295222`" in out


# --- H316: `context --strength` — the rank-axis filter on the context bundle ---


def test_context_strength_filter_keeps_the_band_and_stronger(scrolls_home, capsys):
    # roadmap H316: `--strength` is the rank-axis third custody-style scope, the
    # same before-cap threshold band `search --strength` adds (H314). Threshold
    # semantics (at or above), not exact-band equality: `strong` keeps title hits,
    # `moderate` title-or-summary, `weak` every match. The seed lands one hit in
    # each band for `ranking`, so the three scopes nest provably.
    main(["init"])
    _seed_strength_mix(get_paths().db_path)
    capsys.readouterr()

    strong = run_context(capsys, "ranking", "--strength", "strong")
    assert "wikipedia:en:Strong" in strong
    assert "wikipedia:en:Moderate" not in strong and "wikipedia:en:Weak" not in strong

    moderate = run_context(capsys, "ranking", "--strength", "moderate")
    assert "wikipedia:en:Strong" in moderate and "wikipedia:en:Moderate" in moderate
    assert "wikipedia:en:Weak" not in moderate

    weak = run_context(capsys, "ranking", "--strength", "weak")
    for present in ("Strong", "Moderate", "Weak"):
        assert f"wikipedia:en:{present}" in weak


def test_context_strength_filter_rescopes_the_headline(scrolls_home, capsys):
    # the kept slice re-folds H315's `_Strength:_` headline + per-match markers, so
    # a `--strength strong` bundle reports a strong-only headline describing exactly
    # what it contains — never the whole-library `strong 1, moderate 1, weak 1`.
    main(["init"])
    _seed_strength_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "ranking", "--strength", "strong")
    assert _strength_line(out) == "_Strength: strong 1 (of 1)._"
    assert _best_match_strengths(out) == ["strong"]

    out = run_context(capsys, "ranking", "--strength", "moderate")
    assert _strength_line(out) == "_Strength: strong 1, moderate 1 (of 2)._"
    assert sorted(_best_match_strengths(out)) == ["moderate", "strong"]


def test_context_strength_sieves_before_the_limit(scrolls_home, capsys):
    # the before-cap sieve (the list-sieve shape, like --fidelity/--drift):
    # `--strength moderate --limit 1` returns the top match *at moderate-or-above*,
    # and the Coverage denominator counts only the band's matches (2 of the 3), so a
    # capped rank-scoped bundle stays scope-honest about its own rank scope.
    main(["init"])
    _seed_strength_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "ranking", "--strength", "moderate", "--limit", "1")
    assert "1. " in out
    # the denominator is the moderate-or-above count (2), never the library-wide 3
    assert "the top 1 of 2 matching scrolls" in out
    # and the one kept match is a moderate-or-above one (the weak hit was sieved out)
    assert _best_match_strengths(out)[0] in ("strong", "moderate")


def test_context_strength_scope_named_in_the_title(scrolls_home, capsys):
    # a rank-scoped bundle is self-documenting: the title names the strength band,
    # beside the existing facet/custody echo (and reads after fidelity/drift).
    main(["init"])
    _seed_strength_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "ranking", "--strength", "strong")
    assert out.startswith("# Scrolls Context Bundle: ranking (strength=strong)\n")
    out = run_context(
        capsys, "ranking", "--source", "wikipedia", "--strength", "moderate"
    )
    assert out.startswith(
        "# Scrolls Context Bundle: ranking (source=wikipedia, strength=moderate)\n"
    )


def test_context_strength_ands_with_fidelity(scrolls_home, capsys):
    # the rank axis ANDs with the per-item custody axes: two strong title hits, one
    # held in full and one partial, so `--strength strong --fidelity full` keeps
    # only the full one — the rank sieve and the holdings sieve both apply.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:FullStrong", "Ranking held in full", "a body about engines.",
        content_hash="deadbeef", raw_text="<raw>a full ranking body.</raw>",
    ))
    insert_item(db, make_item(
        "wikipedia:en:PartialStrong", "Ranking held in part", "a body about engines.",
    ))  # no hash/raw → partial fidelity
    capsys.readouterr()

    # strength alone keeps both strong title hits
    both = run_context(capsys, "ranking", "--strength", "strong")
    assert "wikipedia:en:FullStrong" in both and "wikipedia:en:PartialStrong" in both
    # ANDed with --fidelity full, only the full-fidelity strong hit survives
    out = run_context(capsys, "ranking", "--strength", "strong", "--fidelity", "full")
    assert "wikipedia:en:FullStrong" in out
    assert "wikipedia:en:PartialStrong" not in out


def test_context_unknown_strength_raises(scrolls_home):
    main(["init"])
    with pytest.raises(ValueError):
        build_context(get_paths().db_path, "ranking", strength="strongest")


def test_context_cli_rejects_unknown_strength(scrolls_home):
    # argparse `choices=` rejects a bad band with exit 2 before any DB access — the
    # closed-vocabulary contract `search --strength` keeps (H314).
    main(["init"])
    with pytest.raises(SystemExit) as exc:
        main(["context", "ranking", "--strength", "bogus"])
    assert exc.value.code == 2


# --- H345: `context --content-duplicate` — the content-identity browse filter ---
# The content-identity axis lifted to the agent context bundle, beside
# `context --fidelity`/`--drift`/`--strength` (H257/H316): keep only the matches
# the library holds a byte-identical copy of under another id (the same
# `content_hash`). A boolean flag, whole-library sibling scope, report-only (never
# a merge, H325), ANDed before the `--limit`/`--budget` cap. It reuses the H338
# `search_items(content_duplicate=)` clause (the correlated `content_hash`
# sub-count), so the kept set cannot disagree with `list`/`search
# --content-duplicate`, and the kept slice re-folds the Coverage denominator and
# the H331 `_Duplicates:_` briefing line.


def _best_match_ids(out):
    """The `id` in backticks on each numbered Best-Matches line, in order."""
    ids = []
    in_best = False
    for line in out.splitlines():
        if line.startswith("## Best Matches"):
            in_best = True
            continue
        if in_best and line.startswith("## "):
            break
        if in_best and re.match(r"^\d+\. ", line):
            ids.append(re.search(r"\(`([^`]+)`\)", line).group(1))
    return ids


def _seed_content_dup_mix(db):
    """Two byte-identical `database` matches + a unique held + a NULL-hash, all matching.

    `A`/`B` share `deadbeef` (a content-duplicate pair, held in full); `C` holds
    distinct content (`cafef00d`); `D` holds no content (NULL hash). All four match
    the query `database`, so `--content-duplicate` provably keeps only the pair and
    drops the unique and NULL-hash holdings.
    """
    insert_item(db, make_item(
        "wikipedia:en:A", "Alpha database", "A shared database body.",
        content_hash="deadbeef", raw_text="<raw>A shared database body.</raw>"))
    insert_item(db, make_item(
        "wikipedia:en:B", "Beta database", "A shared database body.",
        content_hash="deadbeef", raw_text="<raw>A shared database body.</raw>"))
    insert_item(db, make_item(
        "wikipedia:en:C", "Gamma database", "A distinct database body.",
        content_hash="cafef00d", raw_text="<raw>A distinct database body.</raw>"))
    insert_item(db, make_item(
        "wikipedia:en:D", "Delta database", "A bodiless database stub."))
    # ^ no content_hash → NULL, never a duplicate


def test_context_content_duplicate_keeps_only_redundant_holdings(scrolls_home, capsys):
    # roadmap H345: `--content-duplicate` keeps only the matches the library holds a
    # byte-identical copy of under another id — the H338 browse filter on the third
    # browse surface. Drops the unique (`C`) and the NULL-hash (`D`) holdings.
    main(["init"])
    _seed_content_dup_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "database", "--content-duplicate")
    assert set(_best_match_ids(out)) == {"wikipedia:en:A", "wikipedia:en:B"}
    # the unique and NULL-hash holdings are dropped
    assert "wikipedia:en:C" not in out and "wikipedia:en:D" not in out
    # unfiltered, all four match
    bare = run_context(capsys, "database")
    assert set(_best_match_ids(bare)) == {
        "wikipedia:en:A", "wikipedia:en:B", "wikipedia:en:C", "wikipedia:en:D"
    }


def test_context_content_duplicate_uses_whole_library_sibling_scope(scrolls_home, capsys):
    # decisive choice (b): whole-library sibling scope, not the query/source scope of
    # the matched rows. `A` matches `database` and its byte-identical sibling `B` is
    # OFF-query (no `database` token), yet `A` is still kept — its sibling is held
    # anywhere in the library (the H328 cross-source rule).
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:A", "Alpha database", "A shared body.",
        content_hash="deadbeef", raw_text="<raw>A shared body.</raw>"))
    insert_item(db, make_item(
        "wikipedia:en:B", "Beta tarragon", "A shared body.",  # off-query sibling
        content_hash="deadbeef", raw_text="<raw>A shared body.</raw>"))
    capsys.readouterr()

    out = run_context(capsys, "database", "--content-duplicate")
    assert _best_match_ids(out) == ["wikipedia:en:A"]  # kept: its sibling is held
    assert "tarragon" not in out  # B is off-query, never a match


def test_context_content_duplicate_rescopes_coverage_and_duplicates_line(scrolls_home, capsys):
    # the kept slice re-folds the Coverage denominator (`count_matches` under the same
    # axis) and the H331 `_Duplicates:_` briefing line: the bundle covers 2 (the pair),
    # never the library-wide 4, and the readable duplicate line describes the kept set.
    main(["init"])
    _seed_content_dup_mix(get_paths().db_path)
    capsys.readouterr()

    bare = run_context(capsys, "database")
    assert "Coverage: all 4 matching scrolls" in bare

    out = run_context(capsys, "database", "--content-duplicate")
    assert "Coverage: all 2 matching scrolls" in out
    assert "_Duplicates: 1 group(s) of byte-identical content (2 item(s))._" in out


def test_context_content_duplicate_sieves_before_the_limit(scrolls_home, capsys):
    # the before-cap sieve (the list-sieve shape, like --fidelity/--drift/--strength):
    # `--content-duplicate --limit 1` returns the top match *among the duplicates*, and
    # the Coverage denominator counts only the 2 duplicate matches (never the 4), so a
    # capped content-scoped bundle stays scope-honest about its own content scope.
    main(["init"])
    _seed_content_dup_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "database", "--content-duplicate", "--limit", "1")
    assert "the top 1 of 2 matching scrolls" in out
    # the one kept match is one of the duplicate pair (the unique/NULL were sieved out)
    assert _best_match_ids(out)[0] in ("wikipedia:en:A", "wikipedia:en:B")


def test_context_content_duplicate_ands_with_fidelity(scrolls_home, capsys):
    # the content axis ANDs with the per-item custody axes: a byte-identical pair, one
    # held full and one partial, so `--content-duplicate --fidelity full` keeps only the
    # full one — both the content sieve and the holdings sieve apply.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:Full", "Full database copy", "a shared database body.",
        content_hash="deadbeef", raw_text="<raw>a shared database body.</raw>"))
    # hash + summary only (no body) → partial fidelity, still a content-dup of Full
    part = make_item("wikipedia:en:Part", "Partial database copy", "x",
                     content_hash="deadbeef")
    insert_item(db, dataclasses.replace(
        part, extracted_text=None, summary="a partial database digest."))
    capsys.readouterr()

    # content-duplicate alone keeps both byte-identical holdings
    both = run_context(capsys, "database", "--content-duplicate")
    assert set(_best_match_ids(both)) == {"wikipedia:en:Full", "wikipedia:en:Part"}
    # ANDed with --fidelity full, only the full-fidelity copy survives
    out = run_context(capsys, "database", "--content-duplicate", "--fidelity", "full")
    assert _best_match_ids(out) == ["wikipedia:en:Full"]
    assert "wikipedia:en:Part" not in out


def test_context_content_duplicate_scope_named_in_the_title(scrolls_home, capsys):
    # a content-scoped bundle is self-documenting: the title carries a bare
    # `content-duplicate` marker (no value — a boolean), the H341 `export bundle`
    # scope-note idiom, beside the existing facet echo (and reads last).
    main(["init"])
    _seed_content_dup_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "database", "--content-duplicate")
    assert out.startswith("# Scrolls Context Bundle: database (content-duplicate)\n")
    out = run_context(
        capsys, "database", "--source", "wikipedia", "--content-duplicate"
    )
    assert out.startswith(
        "# Scrolls Context Bundle: database (source=wikipedia, content-duplicate)\n"
    )


def test_context_content_duplicate_converges_with_search(scrolls_home, capsys):
    # the kept ids ≡ exactly `search --content-duplicate` over the same query scope
    # (the H338 browse-filter convergence; no works here, so the work-collapse is a
    # no-op and the two sets agree id-for-id) — both fold the same `search_items`
    # `content_hash` sub-count clause, so they cannot disagree.
    main(["init"])
    _seed_content_dup_mix(get_paths().db_path)
    capsys.readouterr()

    out = run_context(capsys, "database", "--content-duplicate")
    main(["search", "database", "--content-duplicate"])
    search_ids = {row["id"] for row in json.loads(capsys.readouterr().out)}
    assert set(_best_match_ids(out)) == search_ids == {
        "wikipedia:en:A", "wikipedia:en:B"
    }
