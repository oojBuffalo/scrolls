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
    assert payload == {"items": 0, "sources": 0, "categories": 0, "concepts": 0, "summaries": 0, "pages": 0}
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
    assert payload == {"items": 2, "sources": 2, "categories": 2, "concepts": 0, "summaries": 0, "pages": 5}

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
    assert payload == {"items": 1, "sources": 1, "categories": 0, "concepts": 0, "summaries": 0, "pages": 2}
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
    assert payload == {"items": 0, "sources": 0, "categories": 0, "concepts": 0, "summaries": 0, "pages": 1}
    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    assert "0 scrolls from 0 sources." in index
    assert "## Sources" not in index
    assert "## Recent" not in index

def make_summary(slug, display, text, members_hash="abc123"):
    from scrolls.kb import ConceptSummary
    return ConceptSummary(
        slug=slug,
        display=display,
        summary=text,
        members_hash=members_hash,
        engine="kb-llm-v1",
        model="claude-test",
        generated_at="2026-06-12T00:00:00+00:00",
    )


def test_kb_concept_page_leads_with_stored_summary(scrolls_home, capsys):
    from scrolls.kb import save_concept_summary

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "wikipedia:en:Okapi_BM25", "wikipedia", "Okapi BM25", concepts=("BM25",)))
    insert_item(db, make_rendered(
        "web:fts", "web", "FTS in practice", concepts=("BM25", "SQLite")))
    save_concept_summary(db, make_summary(
        "bm25", "BM25", "BM25 appears across saved items about ranking and FTS."))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload["concepts"] == 2
    assert payload["summaries"] == 1  # only bm25 has a stored summary

    page = (scrolls_home / "library" / "concepts" / "bm25.md").read_text(encoding="utf-8")
    assert page.startswith(
        "# Concept: BM25\n"
        "\n"
        "BM25 appears across saved items about ranking and FTS.\n"
        "\n"
        "2 scrolls.\n"
    )
    # pages without a stored summary keep the plain shape
    sqlite_page = (scrolls_home / "library" / "concepts" / "sqlite.md").read_text(encoding="utf-8")
    assert sqlite_page.startswith("# Concept: SQLite\n\n1 scroll.\n")


def test_kb_summary_for_vanished_concept_is_simply_unused(scrolls_home, capsys):
    from scrolls.kb import save_concept_summary

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered("web:abc", "web", "A post", concepts=("SQLite",)))
    save_concept_summary(db, make_summary("bm25", "BM25", "Nothing links here anymore."))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload["summaries"] == 0
    assert not (scrolls_home / "library" / "concepts" / "bm25.md").exists()


def test_concept_summary_store_roundtrip_and_delete(scrolls_home):
    from scrolls.kb import (
        delete_concept_summaries,
        load_concept_summaries,
        save_concept_summary,
    )

    main(["init"])
    db = get_paths().db_path
    assert load_concept_summaries(db) == {}

    save_concept_summary(db, make_summary("bm25", "BM25", "First take."))
    save_concept_summary(db, make_summary("bm25", "BM25", "Second take.", members_hash="def456"))
    save_concept_summary(db, make_summary("sqlite", "SQLite", "An embedded database."))

    stored = load_concept_summaries(db)
    assert set(stored) == {"bm25", "sqlite"}
    assert stored["bm25"].summary == "Second take."  # replaced, not duplicated
    assert stored["bm25"].members_hash == "def456"

    delete_concept_summaries(db, ["bm25"])
    assert set(load_concept_summaries(db)) == {"sqlite"}
    delete_concept_summaries(db, [])  # no-op, never raises


def test_load_concept_summaries_tolerates_pre_v6_database(tmp_path):
    """`scrolls kb` reads without migrating; a v5 library must not crash it."""
    import sqlite3

    from scrolls.db import MIGRATIONS
    from scrolls.kb import load_concept_summaries

    db_path = tmp_path / "db.sqlite"
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        for version in (1, 2, 3, 4, 5):
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '5')")
    conn.close()

    assert load_concept_summaries(db_path) == {}

# --- scrolls kb --engine llm (ADR 0025) -----------------------------------


@pytest.fixture
def fake_summary_llm(monkeypatch):
    """Replace the concept engine's Anthropic completer with a canned summary."""
    import scrolls.kb_llm as kb_llm

    calls = []

    def complete(system, user, model):
        calls.append({"system": system, "user": user, "model": model})
        return json.dumps({"summary": "BM25 threads through search-ranking scrolls."})

    monkeypatch.setattr(kb_llm, "_anthropic_complete", complete)
    return calls


def seed_bm25_pair(db):
    insert_item(db, make_rendered(
        "wikipedia:en:Okapi_BM25", "wikipedia", "Okapi BM25", concepts=("BM25",)))
    insert_item(db, make_rendered(
        "web:fts", "web", "FTS in practice", concepts=("bm25",)))


def test_kb_llm_engine_synthesizes_then_compiles(scrolls_home, fake_summary_llm, capsys):
    main(["init"])
    seed_bm25_pair(get_paths().db_path)
    capsys.readouterr()

    exit_code = main(["kb", "--engine", "llm"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["generated"] == 1
    assert payload["results"] == [
        {"slug": "bm25", "concept": "BM25", "status": "generated"}
    ]
    assert payload["concepts"] == 1
    assert payload["summaries"] == 1
    assert len(fake_summary_llm) == 1

    page = (scrolls_home / "library" / "concepts" / "bm25.md").read_text(encoding="utf-8")
    assert "BM25 threads through search-ranking scrolls." in page

    # a later plain compile keeps the summary without any model call
    exit_code = main(["kb"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["summaries"] == 1
    assert len(fake_summary_llm) == 1
    page = (scrolls_home / "library" / "concepts" / "bm25.md").read_text(encoding="utf-8")
    assert "BM25 threads through search-ranking scrolls." in page


def test_kb_llm_engine_rerun_is_free_when_nothing_changed(
    scrolls_home, fake_summary_llm, capsys
):
    main(["init"])
    seed_bm25_pair(get_paths().db_path)
    main(["kb", "--engine", "llm"])
    capsys.readouterr()

    exit_code = main(["kb", "--engine", "llm"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["generated"] == 0
    assert payload["current"] == 1
    assert len(fake_summary_llm) == 1  # no new model calls


def test_kb_llm_engine_without_credentials_aborts_before_compiling(
    scrolls_home, monkeypatch, capsys
):
    import scrolls.kb_llm as kb_llm
    from scrolls.llm import LLMAuthError

    def no_auth(system, user, model):
        raise LLMAuthError("llm engine needs Anthropic credentials")

    monkeypatch.setattr(kb_llm, "_anthropic_complete", no_auth)
    main(["init"])
    seed_bm25_pair(get_paths().db_path)
    capsys.readouterr()

    exit_code = main(["kb", "--engine", "llm"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "credentials" in json.loads(captured.err)["error"]
    assert not (scrolls_home / "library" / "index.md").exists()


def test_kb_llm_engine_reports_failures_but_still_compiles(
    scrolls_home, monkeypatch, capsys
):
    import scrolls.kb_llm as kb_llm
    from scrolls.llm import LLMError

    def broken(system, user, model):
        raise LLMError("Anthropic API error: overloaded")

    monkeypatch.setattr(kb_llm, "_anthropic_complete", broken)
    main(["init"])
    seed_bm25_pair(get_paths().db_path)
    capsys.readouterr()

    exit_code = main(["kb", "--engine", "llm"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed"] == 1
    assert payload["results"][0]["status"] == "failed"
    assert payload["summaries"] == 0
    assert (scrolls_home / "library" / "index.md").exists()  # compile still ran


def test_kb_llm_engine_on_uninitialized_library_is_a_zero_run(
    scrolls_home, fake_summary_llm, capsys
):
    exit_code = main(["kb", "--engine", "llm"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["generated"] == 0
    assert payload["pages"] == 0
    assert fake_summary_llm == []
    assert not scrolls_home.exists()  # kb never creates a library


def test_kb_llm_engine_uses_config_llm_model(scrolls_home, fake_summary_llm, capsys):
    main(["init"])
    seed_bm25_pair(get_paths().db_path)
    (scrolls_home / "config.toml").write_text(
        '[classify]\nllm_model = "claude-from-config"\n', encoding="utf-8"
    )
    capsys.readouterr()

    exit_code = main(["kb", "--engine", "llm"])
    assert exit_code == 0
    assert fake_summary_llm[0]["model"] == "claude-from-config"


def test_kb_llm_engine_rejects_invalid_config(scrolls_home, fake_summary_llm, capsys):
    main(["init"])
    (scrolls_home / "config.toml").write_text("not toml [", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(["kb", "--engine", "llm"])
    assert exit_code == 1
    assert "invalid TOML" in json.loads(capsys.readouterr().err)["error"]
    assert fake_summary_llm == []
