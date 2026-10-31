"""Tests for searching held document text (roadmap H445, ADR 0119).

ADR 0114 reads a captured PDF into its media ref (`text`, `text_method`) but
left it out of the search index, so `search` and `context` answered "nothing"
for words the library held. The index now carries a fourth column,
`document_text`, derived from the refs on every write and backfilled when an
older library is upgraded.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from scrolls.cli import main
from scrolls.db import MIGRATIONS, SCHEMA_VERSION, init_db, read_schema_version
from scrolls.doctor import run_doctor
from scrolls.items import ScrollItem, document_text, get_item, insert_item, update_item
from scrolls.paths import get_paths
from scrolls.search import search_items


@pytest.fixture
def home(monkeypatch, tmp_path):
    """An initialized library under a temp root; never touches ~/.scrolls."""
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "scrolls-home"))
    assert main(["init"]) == 0
    return get_paths()


def _pdf(text, **extra):
    ref = {"type": "file", "url": "https://example.org/treaty.pdf",
           "path": "media/web/treaty.pdf", **extra}
    if text is not ...:
        ref["text"] = text
    return ref


def _item(item_id="web:treaty", media=(), **overrides):
    base = dict(
        id=item_id,
        source="web",
        url=f"https://example.org/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00",
        title="A page about a treaty",
        extracted_text="The page mentions a document.",
        stage="fetched",
        media=tuple(media),
    )
    base.update(overrides)
    return ScrollItem(**base)


def test_a_word_held_only_in_a_pdf_is_found(home):
    insert_item(home.db_path, _item(media=[_pdf("Signed at Zanzibar in 1890.", text_method="pypdf")]))

    (hit,) = search_items(home.db_path, "zanzibar")
    assert hit.id == "web:treaty"
    assert hit.matched_fields == ("document_text",)
    assert hit.match_strength == "weak"
    assert "[Zanzibar]" in hit.snippet


def test_document_text_is_a_body_hit_for_the_strength_filter(home):
    insert_item(home.db_path, _item(media=[_pdf("Signed at Zanzibar in 1890.")]))

    assert [h.id for h in search_items(home.db_path, "zanzibar", strength="weak")] == ["web:treaty"]
    assert search_items(home.db_path, "zanzibar", strength="moderate") == []


def test_unread_and_unreadable_documents_add_nothing(home):
    # ADR 0114 keeps read / read-but-empty / unread distinct; only read text indexes.
    refs = [_pdf(...), _pdf(None), _pdf(""), {"type": "image", "url": "u"}, "not a ref"]
    assert document_text(tuple(refs)) is None
    insert_item(home.db_path, _item(media=refs))
    assert search_items(home.db_path, "zanzibar") == []
    assert search_items(home.db_path, "treaty")[0].matched_fields == ("title",)


def test_reading_a_document_later_updates_the_index(home):
    db = home.db_path
    insert_item(db, _item(media=[_pdf(...)]))
    assert search_items(db, "zanzibar") == []

    update_item(db, _item(media=[_pdf("Signed at Zanzibar.")]))
    assert [h.id for h in search_items(db, "zanzibar")] == ["web:treaty"]

    update_item(db, _item(media=[]))
    assert search_items(db, "zanzibar") == []
    assert run_doctor(home)["fts"]["in_sync"] is True


def test_cli_search_and_context_reach_document_text(home, capsys):
    insert_item(home.db_path, _item(media=[_pdf("Signed at Zanzibar in 1890.")]))
    capsys.readouterr()

    assert main(["search", "zanzibar"]) == 0
    (row,) = json.loads(capsys.readouterr().out)
    assert row["matched_fields"] == ["document_text"]

    assert main(["context", "zanzibar"]) == 0
    assert "A page about a treaty" in capsys.readouterr().out


def test_context_excerpts_the_document_text_that_matched(home, capsys):
    # The item's own body says nothing about Zanzibar; the bundle's excerpt
    # must carry the held document's words around the match, not the body.
    filler = "Preamble clause. " * 120
    insert_item(home.db_path, _item(media=[_pdf(filler + "Signed at Zanzibar in 1890.")]))
    capsys.readouterr()

    assert main(["context", "zanzibar", "--budget", "full"]) == 0
    out = capsys.readouterr().out
    excerpts = out.split("## Excerpts", 1)[1]
    assert "From a held document: … " in excerpts
    assert "Signed at Zanzibar in 1890." in excerpts
    assert "The page mentions a document." not in excerpts


def test_a_body_match_keeps_the_body_excerpt(home, capsys):
    insert_item(
        home.db_path,
        _item(extracted_text="Zanzibar is named in the page itself.", media=[_pdf("Zanzibar again.")]),
    )
    capsys.readouterr()

    assert main(["context", "zanzibar", "--budget", "full"]) == 0
    excerpts = capsys.readouterr().out.split("## Excerpts", 1)[1]
    assert "Zanzibar is named in the page itself." in excerpts
    assert "From a held document" not in excerpts


def test_the_derived_column_never_leaves_the_library(home, capsys):
    insert_item(home.db_path, _item(media=[_pdf("Signed at Zanzibar.")]))
    capsys.readouterr()
    assert main(["export", "items"]) == 0
    (line,) = capsys.readouterr().out.splitlines()
    assert "document_text" not in json.loads(line)
    assert get_item(home.db_path, "web:treaty").media[0]["text"] == "Signed at Zanzibar."


# --- upgrading an older library ---------------------------------------------


def _v8_library(db_path, media):
    """A library as schema 8 wrote it: no document_text column, a 3-column index."""
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        for version in range(1, 9):
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '8')")
        conn.execute(
            "INSERT INTO items (id, source, url, saved_at, title, extracted_text, "
            "media, stage) VALUES ('web:treaty', 'web', 'https://example.org/t', "
            "'2026-06-12T00:00:00+00:00', 'A page about a treaty', 'Body.', ?, 'fetched')",
            (json.dumps(media),),
        )
    conn.close()


def test_upgrading_backfills_and_indexes_held_document_text(home):
    db = home.db_path
    db.unlink()
    media = [_pdf("Signed at Zanzibar."), _pdf(""), {"type": "image"}, "x", _pdf("Second page.")]
    _v8_library(db, media)

    init_db(db)

    assert read_schema_version(db) == SCHEMA_VERSION
    conn = sqlite3.connect(db)
    (stored,) = conn.execute("SELECT document_text FROM items").fetchone()
    conn.close()
    # the SQL backfill derives exactly what every later Python write will
    assert stored == document_text(tuple(media)) == "Signed at Zanzibar.\nSecond page."
    assert [h.id for h in search_items(db, "zanzibar")] == ["web:treaty"]
    assert run_doctor(home)["fts"]["in_sync"] is True


def test_a_failed_upgrade_leaves_the_library_as_it_was(home, monkeypatch):
    # Every command upgrades first, so a migration that dies halfway must not
    # strand the library between schemas (Codex review of H445, P1).
    import scrolls.db as db_module

    db = home.db_path
    db.unlink()
    _v8_library(db, [_pdf("Signed at Zanzibar.")])
    broken = (*MIGRATIONS[9], "SELECT * FROM no_such_table")
    monkeypatch.setitem(db_module.MIGRATIONS, 9, broken)

    with pytest.raises(sqlite3.OperationalError):
        init_db(db)

    assert read_schema_version(db) == 8
    conn = sqlite3.connect(db)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    triggers = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    conn.close()
    assert "document_text" not in columns
    assert {"items_fts_insert", "items_fts_delete", "items_fts_update"} <= triggers

    monkeypatch.undo()
    init_db(db)  # the retry succeeds from a clean v8
    assert [h.id for h in search_items(db, "zanzibar")] == ["web:treaty"]


def test_any_command_upgrades_an_older_library_before_writing(home, capsys):
    # `scrolls set` writes the item without calling init itself; on a v8
    # library the new column must already exist when it does.
    db = home.db_path
    db.unlink()
    _v8_library(db, [_pdf("Signed at Zanzibar.")])

    capsys.readouterr()
    assert main(["set", "web:treaty", "category=reference"]) == 0
    assert read_schema_version(db) == SCHEMA_VERSION
    assert get_item(db, "web:treaty").category == "reference"
    assert [h.id for h in search_items(db, "zanzibar")] == ["web:treaty"]


def test_a_current_library_is_not_rewritten_by_a_read(home, capsys):
    before = home.db_path.read_bytes()
    capsys.readouterr()
    assert main(["search", "anything"]) == 0
    assert home.db_path.read_bytes() == before
