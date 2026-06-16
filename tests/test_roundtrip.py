"""The lossless round-trip is a *verified* invariant, not a docstring claim.

`items_export.py` promises that a library exports to JSONL and rebuilds from
it: "the derived artifacts (the Markdown scrolls, captured media, the compiled
`library/`) rebuild from those rows: `scrolls doctor --fix` rewrites any missing
scroll file and the FTS index, and `scrolls kb` recompiles the library." The
custody vision (`docs/custody-vision.md`, capability 4) demands that this be a
*tested* invariant — "integrity is verified, not asserted" — and a dogfood-
verified path (capability 8: *take it with me — export bundle → reimport*).

These tests build a real multi-source library, export it, then reconstruct it
in a *fresh* library using only the documented commands
(`import items` → `doctor --fix` → `kb`) and prove the reconstruction is
byte-identical to the original across every surface that matters:

- the canonical store (the item rows),
- the re-export JSONL itself (export→import→export is byte-stable),
- the rendered scrolls on disk,
- the compiled `library/` pages,
- full-text search results,

and that the rebuilt library passes its own custody audit. The one thing a
JSONL backup cannot carry — captured media *blobs* — degrades honestly: doctor
reports the missing file rather than pretending it is held, exactly the
"graceful degradation" the vision names.
"""

from __future__ import annotations

import json

import pytest

from scrolls.cli import main
from scrolls.db import init_db
from scrolls.items import ScrollItem, insert_item, item_to_dict, list_items, make_item_id
from scrolls.paths import get_paths
from scrolls.render import write_scroll
from scrolls.search import search_items


def _rendered(source, source_id, url, **fields) -> ScrollItem:
    """A fully-populated item the way a finished ingest leaves it: rendered,
    with content, classification, concepts/tags, links and provenance — so the
    round-trip is exercised over every field, not a thin spine."""
    base = dict(
        id=make_item_id(source, source_id, url),
        source=source,
        source_id=source_id,
        url=url,
        saved_at="2026-06-10T00:00:00+00:00",
        content_hash="sha256:" + (source_id or url)[-8:],
        stage="rendered",
    )
    base.update(fields)
    return ScrollItem(**base)


def _seed_items() -> list[ScrollItem]:
    """A small, interlinked multi-source library: shared concepts and tags so
    the KB compiles real concept/tag/source/category/related pages, not stubs."""
    return [
        _rendered(
            "arxiv", "1706.03762", "https://arxiv.org/abs/1706.03762",
            title="Attention Is All You Need",
            author="Ashish Vaswani et al.",
            published_at="2017-06-12T17:57:34+00:00",
            raw_text="<the raw Atom entry>",
            extracted_text="The dominant sequence transduction models use the "
            "transformer with attention.",
            summary="We propose the Transformer.",
            category="paper",
            domain="machine learning",
            tags=("cs.CL", "cs.LG"),
            concepts=("Attention", "Transformer"),
            links=("https://doi.org/10.5555/3295222",),
            provenance={
                "adapter": "arxiv",
                "fetched_at": "2026-06-10T00:00:05+00:00",
                "extraction_method": "arxiv-atom",
            },
        ),
        _rendered(
            "crossref", "10.5555/3295222", "https://doi.org/10.5555/3295222",
            title="Attention Is All You Need (NIPS)",
            published_at="2017-12-04T00:00:00+00:00",
            extracted_text="Published proceedings record of the Transformer.",
            category="paper",
            domain="machine learning",
            concepts=("Transformer",),
            provenance={"adapter": "crossref", "extraction_method": "csl-json"},
        ),
        _rendered(
            "web", None, "https://example.com/sqlite-fts",
            title="How SQLite FTS Works",
            extracted_text="SQLite FTS5 ranks results with BM25 full-text search.",
            category="technique",
            domain="databases",
            tags=("sqlite", "search"),
            concepts=("BM25", "Full-text search"),
            provenance={"adapter": "web", "extraction_method": "readability"},
        ),
        _rendered(
            "web", None, "https://example.com/local-first",
            title="Local-First Software",
            extracted_text="Local-first software keeps a full-text search index "
            "on the user's machine.",
            category="opinion",
            domain="software",
            tags=("search",),
            concepts=("Full-text search", "Local-first software"),
            provenance={"adapter": "web", "extraction_method": "readability"},
        ),
    ]


def _build_library(items: list[ScrollItem]) -> None:
    """Render and index a library at the active SCROLLS_HOME, then compile KB.

    Renders through the same `write_scroll` a real ingest uses, so the scroll
    files the round-trip later rebuilds are produced by the same code path.
    """
    paths = get_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    init_db(paths.db_path)
    for item in items:
        rendered = write_scroll(paths, item)  # assigns markdown_path, stage=rendered
        insert_item(paths.db_path, rendered)  # FTS populated by the insert trigger
    assert main(["kb"]) == 0


def _read_tree(directory) -> dict[str, bytes]:
    """Every file under `directory`, keyed by path relative to it (bytes)."""
    if not directory.exists():
        return {}
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _rows(paths) -> list[dict]:
    return [item_to_dict(item) for item in list_items(paths.db_path)]


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Switch the active library to a named home under tmp_path; returns a
    factory so one test can build a *source* and a *rebuilt* library side by
    side and compare them."""

    def use(name):
        root = tmp_path / name
        monkeypatch.setenv("SCROLLS_HOME", str(root))
        return get_paths()

    return use


def test_export_rebuild_is_byte_identical(home, capsys):
    """The headline custody guarantee: a library exported to JSONL and rebuilt
    in a *fresh* library via `import → doctor --fix → kb` is byte-identical."""
    src = home("source")
    _build_library(_seed_items())
    capsys.readouterr()  # drain the kb report so the export capture is clean

    # capture the source library's every observable surface
    assert main(["export", "items"]) == 0
    export_jsonl = capsys.readouterr().out
    src_rows = _rows(src)
    src_scrolls = _read_tree(src.scrolls_dir)
    src_library = _read_tree(src.library_dir)
    src_hits = [h.id for h in search_items(src.db_path, "transformer")]

    # write the backup, then rebuild from nothing in a separate home
    backup = src.root.parent / "backup.jsonl"
    backup.write_text(export_jsonl, encoding="utf-8")

    dst = home("rebuilt")
    assert main(["import", "items", str(backup)]) == 0
    import_report = json.loads(capsys.readouterr().out)
    assert import_report["imported"] == len(src_rows) and import_report["skipped"] == 0

    assert main(["doctor", "--fix"]) == 0
    assert main(["kb"]) == 0
    capsys.readouterr()  # drain the doctor/kb reports before the re-export capture

    # 1. the canonical store round-trips field-for-field
    assert _rows(dst) == src_rows
    # 2. export→import→export is byte-stable (the re-export equals the backup)
    assert main(["export", "items"]) == 0
    assert capsys.readouterr().out == export_jsonl
    # 3. the rendered scrolls rebuild byte-identically from the index rows
    assert _read_tree(dst.scrolls_dir) == src_scrolls
    # 4. the compiled library/ pages rebuild byte-identically
    assert _read_tree(dst.library_dir) == src_library
    # 5. full-text search returns the same items (FTS rebuilt from rows)
    assert [h.id for h in search_items(dst.db_path, "transformer")] == src_hits
    assert src_hits  # guard: the query actually matched something to compare


def test_rebuilt_library_passes_its_own_custody_audit(home, capsys):
    """After the rebuild, the fresh library is not just equal — it is *clean*:
    doctor finds no structural drift and the custody score is a perfect 100."""
    home("source")
    _build_library(_seed_items())
    capsys.readouterr()  # drain the kb report
    assert main(["export", "items"]) == 0
    export_jsonl = capsys.readouterr().out
    backup = get_paths().root.parent / "backup.jsonl"
    backup.write_text(export_jsonl, encoding="utf-8")

    home("rebuilt")
    assert main(["import", "items", str(backup)]) == 0
    capsys.readouterr()
    assert main(["doctor", "--fix"]) == 0
    assert main(["kb"]) == 0
    capsys.readouterr()  # drain before the final doctor's report

    # a second doctor on the rebuilt library: nothing left to find or fix
    assert main(["doctor"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["issues"] == 0
    assert report["custody"]["score"] == 100
    assert report["custody"]["tiers"]["full"] == len(_seed_items())
    assert report["fts"]["in_sync"] is True
    assert report["orphan_scrolls"] == []


def test_reimport_is_idempotent(home, capsys):
    """Custody re-import is `INSERT OR IGNORE`: importing the same backup twice
    imports once and skips the rest, so re-running the restore is cheap and
    never duplicates or overwrites."""
    home("source")
    _build_library(_seed_items())
    capsys.readouterr()  # drain the kb report
    assert main(["export", "items"]) == 0
    backup = get_paths().root.parent / "backup.jsonl"
    backup.write_text(capsys.readouterr().out, encoding="utf-8")

    home("rebuilt")
    assert main(["import", "items", str(backup)]) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(["import", "items", str(backup)]) == 0
    second = json.loads(capsys.readouterr().out)

    assert first["imported"] == len(_seed_items()) and first["skipped"] == 0
    assert second["imported"] == 0 and second["skipped"] == len(_seed_items())


def test_media_blob_degrades_honestly_on_rebuild(home, capsys):
    """A JSONL backup carries media *references*, not the captured *bytes*. On
    rebuild the scroll's media frontmatter round-trips intact, but the blob is
    gone — and doctor reports it as missing media (honest degradation) rather
    than pretending the library still holds it. This is the one custody gap the
    lossless item export cannot close offline; `scrolls media` re-downloads it.
    """
    src = home("source")
    src.root.mkdir(parents=True, exist_ok=True)
    init_db(src.db_path)
    media_relpath = "media/web/diagram.png"
    (src.root / media_relpath).parent.mkdir(parents=True, exist_ok=True)
    (src.root / media_relpath).write_bytes(b"\x89PNG fake bytes")
    item = _rendered(
        "web", None, "https://example.com/with-image",
        title="A Post With An Image",
        extracted_text="See the diagram.",
        media=({"type": "image", "url": "https://example.com/d.png", "path": media_relpath},),
    )
    rendered = write_scroll(src, item)
    insert_item(src.db_path, rendered)
    src_scroll = (src.root / rendered.markdown_path).read_bytes()

    assert main(["export", "items"]) == 0
    backup = src.root.parent / "backup.jsonl"
    backup.write_text(capsys.readouterr().out, encoding="utf-8")

    dst = home("rebuilt")
    assert main(["import", "items", str(backup)]) == 0
    capsys.readouterr()
    # doctor --fix exits 1 here, and honestly so: it rewrote the missing scroll
    # but cannot re-download the media blob offline, so one issue stays unfixed.
    assert main(["doctor", "--fix"]) == 1
    fix_report = json.loads(capsys.readouterr().out)
    assert fix_report["missing_scrolls"][0]["status"] == "rewritten"

    # the scroll itself (media reference in frontmatter included) round-trips
    assert (dst.root / rendered.markdown_path).read_bytes() == src_scroll
    # but the blob is not held, and doctor says so plainly
    assert not (dst.root / media_relpath).exists()
    assert main(["doctor"]) == 1  # still one unrepairable issue: the blob
    report = json.loads(capsys.readouterr().out)
    assert report["missing_media"] == [
        {"id": item.id, "path": media_relpath, "url": "https://example.com/d.png", "status": "found"}
    ]


def test_slug_collision_survives_the_round_trip(home, capsys):
    """Two items whose titles slug identically get distinct scroll paths in the
    source library (`title.md` and `title-<hash>.md`). The round-trip must
    rebuild *both* at their original paths — because the backup carries the
    stored `markdown_path`, and `write_scroll` honors it rather than re-slugging
    from the (now-ambiguous) title. Without that, a rebuild could collapse the
    two scrolls onto one path and silently lose a capture.
    """
    src = home("source")
    src.root.mkdir(parents=True, exist_ok=True)
    init_db(src.db_path)
    paths_seen = []
    for url in ("https://a.example/post", "https://b.example/post"):
        item = _rendered("web", None, url, title="Same Title", extracted_text="body")
        rendered = write_scroll(src, item)  # second collides → distinct suffixed path
        insert_item(src.db_path, rendered)
        paths_seen.append(rendered.markdown_path)
    assert paths_seen[0] != paths_seen[1]  # the collision really happened
    src_scrolls = _read_tree(src.scrolls_dir)
    assert len(src_scrolls) == 2

    assert main(["export", "items"]) == 0
    backup = src.root.parent / "backup.jsonl"
    backup.write_text(capsys.readouterr().out, encoding="utf-8")

    dst = home("rebuilt")
    assert main(["import", "items", str(backup)]) == 0
    capsys.readouterr()
    assert main(["doctor", "--fix"]) == 0

    # both scrolls reappear at their original, distinct paths, byte-for-byte
    assert _read_tree(dst.scrolls_dir) == src_scrolls
