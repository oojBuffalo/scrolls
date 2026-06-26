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
import sqlite3

import pytest

from scrolls.cli import main
from scrolls.custody import (
    CONFLICT_STATUS,
    CustodyEvent,
    conflict_event,
    item_history,
    record_events,
)
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


def test_export_items_is_a_reproducible_artifact(home, capsys):
    """`export items` is the whole-library *backup transport* (the JSONL the
    bundle's item block wraps), and a backup must be a reproducible artifact:

    1. exporting the *same unchanged library* twice yields a **byte-identical**
       JSONL (whole-file, not one row — an unsorted `list_items` fold or a
       per-row non-determinism would make two backups of one library disagree,
       breaking an operator who `diff`s the same library across two machines), and
    2. a real `export items` → `import items` into a *fresh* home → re-`export
       items` reproduces the sender's bytes — the lossless-backup reproduction a
       single-pass identity check misses.

    The whole-library-backup sibling of the scoped-bundle determinism guard
    (H368): the same `dump_items_export` fold over the *entire* holdings, no
    query scope. The existing `test_export_rebuild_is_byte_identical` pins the
    round-trip leg amid a five-surface rebuild check; this isolates the
    transport's own reproducibility — the same-library two-export determinism it
    does not pin — and compares the *whole JSONL file*, not one row.
    """
    src = home("source")
    _build_library(_seed_items())
    capsys.readouterr()  # drain the kb report so the export captures are clean

    # 1. same-library determinism: two exports, no DB change between them,
    #    are byte-identical (the artifact a `diff` across machines must match).
    assert main(["export", "items"]) == 0
    first_export = capsys.readouterr().out
    assert main(["export", "items"]) == 0
    second_export = capsys.readouterr().out
    assert second_export == first_export
    # non-vacuous: a real multi-row backup, not two empty strings comparing equal
    assert first_export.count("\n") == len(_seed_items())

    # 2. round-trip reproduction: rebuild the index in a fresh home from the
    #    backup alone, re-export, and assert it reproduces the sender's bytes.
    #    `export items` reads the index rows, so `import items` is sufficient —
    #    no `doctor --fix`/`kb` rebuild needed to reproduce the JSONL transport.
    backup = src.root.parent / "backup.jsonl"
    backup.write_text(first_export, encoding="utf-8")

    dst = home("rebuilt")
    assert main(["import", "items", str(backup)]) == 0
    capsys.readouterr()  # drain the import report before the re-export capture
    assert main(["export", "items"]) == 0
    assert capsys.readouterr().out == first_export
    assert dst.db_path.exists()  # guard: the re-export read a real rebuilt store


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


def _event_count(db_path) -> int:
    """The raw `custody_events` row count — the whole-ledger size a silent
    double-insert would inflate, read straight from the table (not folded through
    any reader) so the assertion sees the ledger SQLite actually holds."""
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM custody_events").fetchone()[0]
    finally:
        conn.close()


def test_reimport_events_is_whole_ledger_idempotent(home, capsys):
    """`import events` re-import is whole-ledger idempotent — the events-transport
    sibling of `test_reimport_is_idempotent` (which pins the *items* transport).

    The custody-events backup (`scrolls export events`, ADR 0082/H72) is restored
    through `import_events`, which content-dedups on the `_EVENT_IDENTITY` 5-tuple
    (a *distinct* code path from `merge_item`'s `INSERT OR IGNORE` — the items
    transport): importing the *same* ledger a second time into a library that
    already holds those events must be a true no-op. H72/H73 pin the events
    export→import *round-trip* preserves the posture, but the whole-*ledger*
    idempotency of a re-import into a populated ledger is only *implied*: a
    regression that dropped the `_EVENT_IDENTITY` dedup (or keyed it on the
    per-library autoincrement `id`, which is never exported) would pass the
    single-import round-trip tests yet double every event row on the second pass,
    inflating the per-item `history` and any count that folds the raw ledger.

    The **decisive choice** is asserting *both* axes: the raw `custody_events`
    row count (catches a silent double-insert) **and** the per-item `history`
    list identity (catches a dedup that drops the wrong row) — a naïve "import
    reports skipped" check misses a re-keyed dedup that both skips *and*
    re-inserts. A recorded *conflict* event rides the ledger so the non-verify
    axis travels and dedups too.
    """
    src = home("source")
    _build_library(_seed_items())
    capsys.readouterr()  # drain the kb report

    # seed a realistic ledger on real held items: a verify history (unchanged →
    # drifted) plus an import-time conflict on the first item, a single verify on
    # the second — so the backup spans ≥2 items, ≥2 statuses, and the conflict
    # axis, not a single trivial row.
    ids = [item.id for item in list_items(src.db_path)]
    first_id, second_id = ids[0], ids[1]
    record_events(src.db_path, [
        CustodyEvent(first_id, "2026-06-11T00:00:00+00:00", "unchanged", "h0", "h0"),
        CustodyEvent(first_id, "2026-06-12T00:00:00+00:00", "drifted", "h0", "h0b"),
        conflict_event(
            first_id, held_hash="h0b", incoming_hash="hX",
            now="2026-06-13T00:00:00+00:00",
        ),
        CustodyEvent(second_id, "2026-06-11T00:00:00+00:00", "unchanged", "h1", "h1"),
    ])
    seeded = _event_count(src.db_path)
    assert seeded == 4  # non-vacuous: a real multi-event ledger to round-trip

    assert main(["export", "events"]) == 0
    backup = src.root.parent / "events.jsonl"
    backup.write_text(capsys.readouterr().out, encoding="utf-8")
    assert backup.read_text().count("\n") == seeded  # the whole ledger travels

    # restore the ledger into a *fresh* home, twice, with no intervening mutation
    dst = home("rebuilt")
    assert main(["import", "events", str(backup)]) == 0
    first = json.loads(capsys.readouterr().out)
    after_first_count = _event_count(dst.db_path)
    after_first_history = {
        first_id: item_history(dst.db_path, first_id),
        second_id: item_history(dst.db_path, second_id),
    }

    assert main(["import", "events", str(backup)]) == 0
    second = json.loads(capsys.readouterr().out)
    after_second_count = _event_count(dst.db_path)
    after_second_history = {
        first_id: item_history(dst.db_path, first_id),
        second_id: item_history(dst.db_path, second_id),
    }

    # the first pass restores the whole ledger; the second is a true no-op
    assert first["imported"] == seeded and first["skipped"] == 0
    assert second["imported"] == 0 and second["skipped"] == seeded

    # axis 1 — the raw ledger did not grow: a dropped `_EVENT_IDENTITY` dedup (or
    # one keyed on the per-library autoincrement id) would double it to 8 here
    assert after_first_count == seeded
    assert after_second_count == seeded

    # axis 2 — every item's `history` timeline is byte-identical list-for-list
    # across the two passes: a dedup that both skips *and* re-inserts (wrong row)
    # would leave the count equal yet perturb the per-item timeline
    assert after_second_history == after_first_history
    # non-vacuous: the timeline really carries the multi-status + conflict ledger
    assert [e["status"] for e in after_first_history[first_id]] == [
        CONFLICT_STATUS, "drifted", "unchanged",  # item_history is newest-first
    ]
    assert len(after_first_history[second_id]) == 1


def test_export_events_is_a_reproducible_artifact(home, capsys):
    """`export events` is the whole-library *custody-events backup transport* (the
    JSONL the bundle's custody-events block wraps, ADR 0082/H72), and a backup
    must be a reproducible artifact:

    1. exporting the *same unchanged library*'s events twice yields a
       **byte-identical** JSONL (whole-file, not one row — an unsorted event fold
       or a per-row non-determinism would make two custody backups of one library
       disagree, breaking an operator who `diff`s two machines' ledgers), and
    2. a real `export events` → restore into a *fresh* home → re-`export events`
       reproduces the sender's bytes — the lossless-backup reproduction a
       single-pass identity check misses.

    The events-transport sibling of `test_export_items_is_a_reproducible_artifact`
    (H379, the items transport) and the *export*-reproducibility complement of
    `test_reimport_events_is_whole_ledger_idempotent` (H380, the *import* settle
    axis): the same whole-library-backup shape on the `dump_events_export` fold
    rather than `dump_items_export`. H72/H73/H78 pin the events round-trip
    preserves the rebuilt *posture*, not the JSONL *bytes* — so an unsorted
    `events_for_items` fold or a set-iteration leak in a per-row field would pass
    those yet make two backups of one library disagree.

    `export events` is **item-scoped** (it resolves `list_items` then their
    events), so the round-trip's fresh home must hold the *items* too — the
    realistic full restore (`import items` + `import events`), not events alone.
    The seeded ledger is appended in **chronological** `checked_at` order (the
    real-world shape `verify` writes, monotonic in append order across the whole
    ledger), so `import_events`' stable sort-by-`checked_at` is a no-op and the
    fresh home's `ORDER BY id` re-export reproduces the sender's row order.
    """
    src = home("source")
    _build_library(_seed_items())
    capsys.readouterr()  # drain the kb report so the export captures are clean

    # seed a realistic ledger appended in chronological order on real held items:
    # a verify history (unchanged → drifted) plus an import-time conflict on the
    # first item, a single verify on the second — so the backup spans ≥2 items,
    # ≥2 statuses, the conflict axis, and a non-None `detail` row, not one trivial
    # row. Every `checked_at` is distinct and increasing in append order, so the
    # importer's sort-by-`checked_at` reproduces the sender's `ORDER BY id` order.
    ids = [item.id for item in list_items(src.db_path)]
    first_id, second_id = ids[0], ids[1]
    record_events(src.db_path, [
        CustodyEvent(first_id, "2026-06-11T00:00:00+00:00", "unchanged", "h0", "h0"),
        CustodyEvent(second_id, "2026-06-11T06:00:00+00:00", "unchanged", "h1", "h1"),
        CustodyEvent(first_id, "2026-06-12T00:00:00+00:00", "drifted", "h0", "h0b"),
        conflict_event(
            first_id, held_hash="h0b", incoming_hash="hX",
            now="2026-06-13T00:00:00+00:00",
        ),
    ])
    seeded = _event_count(src.db_path)
    assert seeded == 4  # non-vacuous: a real multi-event, multi-status ledger

    # 1. same-library determinism: two exports, no DB change between them, are
    #    byte-identical (the artifact a `diff` across two machines must match).
    assert main(["export", "events"]) == 0
    first_export = capsys.readouterr().out
    assert main(["export", "events"]) == 0
    second_export = capsys.readouterr().out
    assert second_export == first_export
    # non-vacuous: the whole ledger travels (one JSON line per event), not "" == ""
    assert first_export.count("\n") == seeded

    # 2. round-trip reproduction: restore into a *fresh* home from the backups
    #    alone, then re-export the events and assert it reproduces the sender's
    #    bytes. `export events` is item-scoped, so the items backup is restored
    #    first (the realistic full restore) before the events backup.
    assert main(["export", "items"]) == 0
    items_backup = src.root.parent / "items.jsonl"
    items_backup.write_text(capsys.readouterr().out, encoding="utf-8")
    events_backup = src.root.parent / "events.jsonl"
    events_backup.write_text(first_export, encoding="utf-8")

    dst = home("rebuilt")
    assert main(["import", "items", str(items_backup)]) == 0
    assert main(["import", "events", str(events_backup)]) == 0
    capsys.readouterr()  # drain the import reports before the re-export capture
    assert main(["export", "events"]) == 0
    assert capsys.readouterr().out == first_export
    assert _event_count(dst.db_path) == seeded  # guard: the re-export read a real ledger


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


# --- the whole-library backup is *tier-lossless* too (H224) ------------------
#
# `_seed_items` (and every round-trip test above) is all-`full` — every item
# carries raw_text + a content_hash at a rendered stage, so they only ever
# exercise the `full` fidelity tier. H216 pinned that the *scoped bundle*
# round-trip preserves each `get_fidelity` tier; this is the sibling guarantee
# on the *other* portable surface: the whole-library `export items` →
# `import items` → `doctor --fix` backup (ADR 0082). A library whose items span
# all three tiers must rebuild with doctor's `custody.tiers` equal to the source
# spread — no rebuild-side downgrade, because `import items` carries every
# content field and `doctor --fix` rebuilds only derived artifacts (scroll
# files, FTS), never the row fields fidelity reads from.


def _mixed_fidelity_seed() -> list[ScrollItem]:
    """A library spanning all three fidelity tiers. The tier is a pure function
    of the stored content fields (`get_fidelity`): a re-derivable body (raw +
    hash at a captured stage) → ``full``; a degraded-but-honest capture (text
    survives but no body/hash to re-derive it) → ``partial``; a body-less
    pointer → ``reference``. Spans ≥2 tiers so the spread is non-vacuous."""
    return [
        # full ×2: raw + extracted + hash at a rendered stage → body re-derivable
        _rendered(
            "arxiv", "1706.03762", "https://arxiv.org/abs/1706.03762",
            title="Attention Is All You Need",
            raw_text="<the raw Atom entry>",
            extracted_text="The Transformer uses attention.",
            category="paper", domain="machine learning",
            provenance={"adapter": "arxiv", "extraction_method": "arxiv-atom"},
        ),
        _rendered(
            "web", None, "https://example.com/sqlite-fts",
            title="How SQLite FTS Works",
            raw_text="<html>FTS5</html>",
            extracted_text="SQLite FTS5 ranks results with BM25.",
            category="technique", domain="databases",
            provenance={"adapter": "web", "extraction_method": "readability"},
        ),
        # partial: extracted text survives but no raw body and no content_hash to
        # fingerprint it → degraded-but-honest, not re-derivable to full
        _rendered(
            "web", None, "https://example.com/local-first",
            title="Local-First Software",
            raw_text=None, content_hash=None,
            extracted_text="Local-first software keeps the index on-device.",
            category="opinion", domain="software",
            provenance={"adapter": "web", "extraction_method": "readability"},
        ),
        # reference: only the pointer + provenance are held, no content at all,
        # and it never reached a rendered stage (a deliberate held-by-reference)
        _rendered(
            "web", None, "https://example.com/paywalled",
            title="A Paywalled Article We Hold By Reference",
            content_hash=None, stage="detected",
            provenance={"adapter": "web"},
        ),
    ]


def _build_mixed_library(items: list[ScrollItem]) -> None:
    """Render the captured items and index every item at the active home, then
    compile the KB. The reference item never reached a rendered stage, so it is
    inserted as-is rather than rendered (rendering would mint a scroll and a
    `markdown_path` it has no body to fill)."""
    paths = get_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    init_db(paths.db_path)
    for item in items:
        if item.stage == "rendered":
            item = write_scroll(paths, item)
        insert_item(paths.db_path, item)
    assert main(["kb"]) == 0


def test_whole_library_backup_is_tier_lossless(home, capsys):
    """The whole-library JSONL backup preserves every fidelity tier, not only
    `full`: a mixed-fidelity library rebuilt via the documented `import items`
    → `doctor --fix` → `kb` backup has doctor's `custody.tiers` equal to the
    source spread, with no rebuild-side downgrade — portability is tier-lossless
    on the whole-library path too, the H216 guarantee's other portable surface."""
    home("source")
    _build_mixed_library(_mixed_fidelity_seed())
    capsys.readouterr()  # drain the kb report

    # the source spread is genuinely mixed (≥2 non-zero tiers — here all three),
    # so "tier-lossless" is a non-vacuous claim and not just "all full survives"
    assert main(["doctor"]) == 0
    src_tiers = json.loads(capsys.readouterr().out)["custody"]["tiers"]
    assert src_tiers == {"full": 2, "partial": 1, "reference": 1}
    assert sum(1 for count in src_tiers.values() if count) >= 2

    assert main(["export", "items"]) == 0
    backup = get_paths().root.parent / "backup.jsonl"
    backup.write_text(capsys.readouterr().out, encoding="utf-8")

    home("rebuilt")
    assert main(["import", "items", str(backup)]) == 0
    assert json.loads(capsys.readouterr().out)["imported"] == len(_mixed_fidelity_seed())
    assert main(["doctor", "--fix"]) == 0
    assert main(["kb"]) == 0
    capsys.readouterr()  # drain before the final doctor's report

    # tier-lossless: the rebuilt library's fidelity spread equals the source's,
    # with no downgrade — `import items` carried every content field and
    # `doctor --fix` rebuilt only derived artifacts, never the row fields
    # `get_fidelity` reads from (raw_text / extracted_text / content_hash / stage)
    assert main(["doctor"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["custody"]["tiers"] == src_tiers
    # and the rebuild is clean: an honest partial/reference is not a violation
    assert report["custody"]["score"] == 100
    assert report["issues"] == 0


# --- the rebuild is byte-identical across mixed tiers too (H231) --------------
#
# `test_export_rebuild_is_byte_identical` (above) proves the rebuilt *scrolls*
# and compiled `library/` pages are byte-for-byte equal to the source — but only
# over the all-`full` `_seed_items`, so a `partial` capture's scroll (rendered
# with *no* `content_hash` to fingerprint it — render.py omits a None field, a
# strictly different frontmatter byte-shape than a `full` scroll) has never been
# proven to rebuild byte-for-byte. H224 pinned that a mixed-fidelity backup
# rebuilds with doctor's `custody.tiers` equal to the source spread (the tier
# *counts* survive); this is the byte-depth sibling: the rendered *bytes* of a
# degraded capture survive the round-trip too, not only its tier count.


def test_whole_library_backup_rebuilds_byte_identically_across_tiers(home, capsys):
    """The whole-library backup rebuilds byte-for-byte across *mixed* fidelity
    tiers, not only the all-`full` `_seed_items`. Reusing H224's mixed-fidelity
    fixture, the rendered scrolls — including the `partial` capture's
    `content_hash`-less scroll — and the compiled `library/` pages built over the
    tier spread rebuild identical after the documented `import items` →
    `doctor --fix` → `kb` restore in a fresh home. Byte-identity is correct-by-
    construction (`write_scroll` is deterministic in the item fields, which
    `import items` carries field-for-field, and `doctor --fix` re-renders only
    from those rows), so this pins it on the partial tier the all-`full`
    byte-identity test never reaches — the rendered-bytes sibling of H224's
    tier-count guarantee."""
    src = home("source")
    _build_mixed_library(_mixed_fidelity_seed())
    capsys.readouterr()  # drain the kb report before capturing the source trees

    # capture the source's rendered scrolls and compiled library trees (bytes)
    src_scrolls = _read_tree(src.scrolls_dir)
    src_library = _read_tree(src.library_dir)

    # non-vacuous: the source tree genuinely spans the partial byte-shape. A
    # `full` scroll carries a `content_hash:` frontmatter line; a `partial`
    # capture has no hash to fingerprint its body, so render.py omits the line —
    # a strictly different frontmatter byte-shape. Both shapes are present, so
    # byte-identity over this tree is a stronger claim than over the all-`full`
    # one (where every scroll has a `content_hash` line).
    with_hash = [path for path, body in src_scrolls.items() if b"content_hash" in body]
    without_hash = [path for path, body in src_scrolls.items() if b"content_hash" not in body]
    assert with_hash, "expected at least one full scroll (with a content_hash line)"
    assert without_hash, "expected the partial scroll (rendered with no content_hash)"

    assert main(["export", "items"]) == 0
    backup = src.root.parent / "backup.jsonl"
    backup.write_text(capsys.readouterr().out, encoding="utf-8")

    dst = home("rebuilt")
    assert main(["import", "items", str(backup)]) == 0
    assert json.loads(capsys.readouterr().out)["imported"] == len(_mixed_fidelity_seed())
    assert main(["doctor", "--fix"]) == 0
    assert main(["kb"]) == 0
    capsys.readouterr()  # drain the doctor/kb reports

    # the rendered scrolls — including the partial's content_hash-less scroll —
    # rebuild byte-identically from the imported rows
    assert _read_tree(dst.scrolls_dir) == src_scrolls
    # and the compiled library/ pages, built over the mixed-fidelity spread,
    # rebuild byte-identically too
    assert _read_tree(dst.library_dir) == src_library
