"""Tests for the compiled library (IDEAS.md §9, §14 Pass 5)."""

import json

import pytest

from scrolls.cli import main
from scrolls.items import ScrollItem, insert_item, update_item
from scrolls.kb import compile_kb
from scrolls.paths import get_paths


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


def make_rendered(item_id, source, title, *, category=None, concepts=(),
                  saved_at="2026-06-01T00:00:00+00:00", markdown_path=None):
    slug = title.lower().replace(" ", "-")
    return ScrollItem(
        id=item_id,
        source=source,
        url=f"https://example.org/{item_id}",
        saved_at=saved_at,
        title=title,
        category=category,
        concepts=tuple(concepts),
        markdown_path=markdown_path or f"scrolls/{source}/{slug}.md",
        stage="rendered",
    )


def run_kb(capsys):
    exit_code = main(["kb"])
    assert exit_code == 0
    return json.loads(capsys.readouterr().out)


def test_kb_before_init_reports_zero_pages(scrolls_home, capsys):
    payload = run_kb(capsys)
    assert payload == {"items": 0, "sources": 0, "categories": 0, "concepts": 0, "pages": 0}
    assert not scrolls_home.exists()  # kb never creates a library


def test_compile_kb_missing_db_writes_nothing(tmp_path):
    paths = get_paths(tmp_path / "nope")
    result = compile_kb(paths)
    assert result.pages == 0
    assert not (tmp_path / "nope").exists()


def test_kb_compiles_index_source_and_category_pages(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "wikipedia:en:SQLite", "wikipedia", "SQLite", category="reference"))
    insert_item(db, make_rendered(
        "youtube:abc123", "youtube", "How SQLite FTS Works", category="media"))
    # detected-but-unrendered items have no scroll file to link to
    insert_item(db, ScrollItem(
        id="github:o/r", source="github", url="https://github.com/o/r",
        saved_at="2026-06-02T00:00:00+00:00"))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload == {"items": 2, "sources": 2, "categories": 2, "concepts": 0, "pages": 5}

    library = scrolls_home / "library"
    index = (library / "index.md").read_text(encoding="utf-8")
    assert "# Scrolls Library" in index
    assert "2 scrolls from 2 sources." in index
    assert "- [wikipedia](sources/wikipedia.md) — 1 scroll" in index
    assert "- [youtube](sources/youtube.md) — 1 scroll" in index
    assert "- [reference](categories/reference.md) — 1 scroll" in index
    assert "- [media](categories/media.md) — 1 scroll" in index
    assert "github" not in index

    source_page = (library / "sources" / "wikipedia.md").read_text(encoding="utf-8")
    assert "# Source: wikipedia" in source_page
    assert "1 scroll." in source_page
    assert "- [SQLite](../../scrolls/wikipedia/sqlite.md) — reference" in source_page

    category_page = (library / "categories" / "reference.md").read_text(encoding="utf-8")
    assert "# Category: reference" in category_page
    assert "- [SQLite](../../scrolls/wikipedia/sqlite.md) — wikipedia" in category_page


def test_kb_index_links_recent_scrolls_newest_first(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    for index in range(12):
        insert_item(db, make_rendered(
            f"web:item{index:02d}", "web", f"Post {index:02d}",
            saved_at=f"2026-06-{index + 1:02d}T00:00:00+00:00"))
    capsys.readouterr()

    run_kb(capsys)
    index_text = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    recent = index_text.split("## Recent\n")[1].strip().splitlines()
    assert len(recent) == 10  # capped
    assert recent[0] == "- [Post 11](../scrolls/web/post-11.md)"
    assert recent[-1] == "- [Post 02](../scrolls/web/post-02.md)"


def test_kb_counts_unclassified_items_in_index(scrolls_home, capsys):
    main(["init"])
    insert_item(get_paths().db_path, make_rendered("web:abc", "web", "An ordinary post"))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload == {"items": 1, "sources": 1, "categories": 0, "concepts": 0, "pages": 2}
    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    assert "- unclassified — 1 scroll" in index
    assert not (scrolls_home / "library" / "categories").exists()


def test_kb_groups_concepts_across_spellings(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "wikipedia:en:Okapi_BM25", "wikipedia", "Okapi BM25", concepts=("BM25",)))
    insert_item(db, make_rendered(
        "web:fts", "web", "FTS in practice", concepts=("bm25", "SQLite")))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload["concepts"] == 2

    library = scrolls_home / "library"
    concept_page = (library / "concepts" / "bm25.md").read_text(encoding="utf-8")
    assert "# Concept: BM25" in concept_page  # spellings merge; one display form
    assert "- [FTS in practice](../../scrolls/web/fts-in-practice.md) — web" in concept_page
    assert "- [Okapi BM25](../../scrolls/wikipedia/okapi-bm25.md) — wikipedia" in concept_page

    index = (library / "index.md").read_text(encoding="utf-8")
    assert "- [BM25](concepts/bm25.md) — 2 scrolls" in index
    assert "- [SQLite](concepts/sqlite.md) — 1 scroll" in index


def test_kb_recompile_removes_stale_pages_but_keeps_user_files(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    item = make_rendered("web:abc", "web", "A handy utility", category="tool")
    insert_item(db, item)
    capsys.readouterr()
    run_kb(capsys)
    assert (scrolls_home / "library" / "categories" / "tool.md").exists()

    notes = scrolls_home / "library" / "notes.md"
    notes.write_text("user notes must survive recompiles\n")
    import dataclasses
    update_item(db, dataclasses.replace(item, category="reference"))

    run_kb(capsys)
    assert not (scrolls_home / "library" / "categories" / "tool.md").exists()
    assert (scrolls_home / "library" / "categories" / "reference.md").exists()
    assert notes.read_text() == "user notes must survive recompiles\n"


def test_kb_empty_initialized_library_writes_empty_index(scrolls_home, capsys):
    main(["init"])
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload == {"items": 0, "sources": 0, "categories": 0, "concepts": 0, "pages": 1}
    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    assert "0 scrolls from 0 sources." in index
    assert "## Sources" not in index
    assert "## Recent" not in index
