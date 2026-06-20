"""Tests for context bundles (IDEAS.md §11, §14 Pass 5)."""

import json

import pytest

from scrolls.cli import main
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
