"""Tests for shareable custody bundles (ADR 0103, MVP M4)."""

import json

import pytest

from scrolls.bundle import BundleError, build_bundle, parse_bundle
from scrolls.cli import main
from scrolls.items import ScrollItem, get_item, insert_item, item_to_dict
from scrolls.paths import get_paths


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
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
        raw_text=f"<raw>{extracted_text}</raw>",
        extracted_text=extracted_text,
        summary=extracted_text.split(".")[0] + ".",
        content_hash="deadbeef",
        provenance={"fetched_at": "2026-06-12T00:00:00+00:00", "via": "test"},
        markdown_path=f"scrolls/wikipedia/{item_id}.md",
        stage="rendered",
    )
    base.update(overrides)
    return ScrollItem(**base)


# --- build / parse round-trip (in memory) ----------------------------------


def test_bundle_has_a_briefing_and_a_custody_block(scrolls_home):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine with full-text search support.",
    ))

    bundle = build_bundle(db, "database engine")
    # the readable briefing names the scroll and its custody facts
    assert bundle.startswith("# Scrolls Custody Bundle: database engine\n")
    assert "## 1. SQLite (`wikipedia:en:SQLite`)" in bundle
    assert "fidelity `full`" in bundle  # raw_text + hash + rendered → full tier
    assert "captured 2026-06-12T00:00:00+00:00" in bundle
    # the self-describing fenced custody block travels alongside
    assert "@generated scrolls" in bundle
    assert "```jsonl" in bundle
    assert "@end scrolls" in bundle


def test_parse_bundle_recovers_the_items(scrolls_home):
    main(["init"])
    db = get_paths().db_path
    original = make_item(
        "wikipedia:en:SQLite", "SQLite",
        "SQLite is a database engine.",
    )
    insert_item(db, original)

    items = parse_bundle(build_bundle(db, "database engine"))
    assert [i.id for i in items] == ["wikipedia:en:SQLite"]
    # the recovered item is byte-for-byte the original (the lossless core)
    assert item_to_dict(items[0]) == item_to_dict(original)


def test_bundle_carries_the_raw_body_even_when_the_excerpt_is_capped(scrolls_home):
    # self-describing offline: the briefing excerpt is capped, but the custody
    # block still holds the full raw_text, so a re-import loses nothing
    main(["init"])
    db = get_paths().db_path
    long_body = "database " * 400  # ~3600 chars
    insert_item(db, make_item(
        "wikipedia:en:Long", "Long", long_body.strip(),
        raw_text=long_body.strip(), summary=None,
    ))

    bundle = build_bundle(db, "database")
    briefing, _, _block = bundle.partition("@generated scrolls")
    assert "…" in briefing  # the readable excerpt is capped
    recovered = parse_bundle(bundle)[0]
    assert recovered.raw_text == long_body.strip()  # the block is complete


# --- full export → import round-trip across libraries (ADR 0099) ------------


def test_export_import_round_trips_across_a_fresh_library(scrolls_home, monkeypatch, tmp_path, capsys):
    # hold a topic in library A, take it with you to an empty library B
    main(["init"])
    db_a = get_paths().db_path
    insert_item(db_a, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))
    insert_item(db_a, make_item(
        "arxiv:1706.03762", "Attention", "A database-adjacent attention paper.",
        source="arxiv", url="https://arxiv.org/abs/1706.03762",
    ))
    capsys.readouterr()

    assert main(["export", "bundle", "database"]) == 0
    bundle_text = capsys.readouterr().out
    bundle_path = tmp_path / "briefing.md"
    bundle_path.write_text(bundle_text, encoding="utf-8")

    # a fresh, empty library B
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    capsys.readouterr()

    assert main(["import", "bundle", str(bundle_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["imported"] == 2
    # both scrolls landed in B with their canonical custody records intact
    a = get_item(db_b, "wikipedia:en:SQLite")
    assert a is not None and a.raw_text == "<raw>SQLite is a database engine.</raw>"
    assert a.content_hash == "deadbeef"
    assert get_item(db_b, "arxiv:1706.03762") is not None


def test_import_bundle_never_overwrites_an_existing_scroll(scrolls_home, tmp_path, capsys):
    # custody-safe re-import: INSERT OR IGNORE, so an item already held is kept
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))
    capsys.readouterr()
    main(["export", "bundle", "database"])
    bundle_path = tmp_path / "b.md"
    bundle_path.write_text(capsys.readouterr().out, encoding="utf-8")

    # importing back into the same library imports nothing new
    main(["import", "bundle", str(bundle_path)])
    report = json.loads(capsys.readouterr().out)
    assert report["imported"] == 0
    assert report["skipped"] == 1


# --- scope, completeness, honesty ------------------------------------------


def test_bundle_scope_is_self_documenting_and_filters(scrolls_home):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_item(
        "wikipedia:en:SQLite", "SQLite", "SQLite is a database engine.",
    ))
    insert_item(db, make_item(
        "arxiv:2401.0001", "Paper", "This paper studies database engines.",
        source="arxiv", url="https://arxiv.org/abs/2401.0001",
    ))

    bundle = build_bundle(db, "database", source="arxiv")
    assert bundle.startswith("# Scrolls Custody Bundle: database (source=arxiv)\n")
    assert "arxiv:2401.0001" in bundle
    # the wikipedia scroll is out of scope — absent from briefing AND block
    assert "wikipedia:en:SQLite" not in bundle


def test_bundle_carries_every_match_not_a_capped_slice(scrolls_home):
    # a custody artifact is complete about its scope: no silent top-N truncation
    main(["init"])
    db = get_paths().db_path
    for index in range(12):
        insert_item(db, make_item(
            f"wikipedia:en:Page_{index}", f"Page {index}",
            "Every page mentions databases.",
        ))

    items = parse_bundle(build_bundle(db, "databases"))
    assert len(items) == 12


def test_empty_scope_yields_a_valid_importable_bundle(scrolls_home, tmp_path, capsys):
    main(["init"])
    capsys.readouterr()
    main(["export", "bundle", "nothingmatcheshere"])
    bundle_text = capsys.readouterr().out
    assert "No matching scrolls." in bundle_text
    # an empty bundle still parses and imports zero — never crashes
    assert parse_bundle(bundle_text) == []
    bundle_path = tmp_path / "empty.md"
    bundle_path.write_text(bundle_text, encoding="utf-8")
    main(["import", "bundle", str(bundle_path)])
    report = json.loads(capsys.readouterr().out)
    assert report["imported"] == 0


def test_export_bundle_before_init_is_a_valid_empty_bundle(scrolls_home, capsys):
    # like `scrolls context`, export never creates a library; the bundle is a
    # valid, importable empty one (it still carries the custody-block markers)
    capsys.readouterr()
    assert main(["export", "bundle", "anything"]) == 0
    out = capsys.readouterr().out
    assert "No matching scrolls." in out
    assert parse_bundle(out) == []
    assert not scrolls_home.exists()


def test_build_bundle_blank_query_is_an_error(scrolls_home):
    main(["init"])
    with pytest.raises(ValueError):
        build_bundle(get_paths().db_path, '""')


def test_parse_bundle_rejects_a_non_bundle(scrolls_home):
    with pytest.raises(BundleError):
        parse_bundle("# Just some markdown\n\nNo custody block here.\n")


def test_import_bundle_reports_a_corrupt_block(scrolls_home, tmp_path, capsys):
    main(["init"])
    bad = tmp_path / "bad.md"
    bad.write_text(
        "# Scrolls Custody Bundle: x\n\n"
        "<!-- @generated scrolls — regenerated by `scrolls export bundle` -->\n"
        "```jsonl\n{not valid json\n```\n"
        "<!-- @end scrolls -->\n",
        encoding="utf-8",
    )
    capsys.readouterr()
    assert main(["import", "bundle", str(bad)]) == 1
    assert "error" in json.loads(capsys.readouterr().err)
