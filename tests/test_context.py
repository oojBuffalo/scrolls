"""Tests for context bundles (IDEAS.md §11, §14 Pass 5)."""

import json

import pytest

from scrolls.cli import main
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
    assert len(excerpt) < 800  # capped well below the full text


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
