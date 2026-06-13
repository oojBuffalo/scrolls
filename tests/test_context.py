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


def test_context_blank_query_is_an_error(scrolls_home, capsys):
    exit_code = main(["context", '""'])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)
