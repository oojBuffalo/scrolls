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

import argparse
import dataclasses
import json
import sqlite3
from typing import Callable, NamedTuple

import pytest

from scrolls.cli import build_parser, main
from scrolls.custody import (
    CONFLICT_STATUS,
    CustodyEvent,
    conflict_event,
    item_history,
    record_events,
)
from scrolls.db import init_db
from scrolls.items import (
    ScrollItem,
    adopt_incoming,
    archived_records,
    insert_item,
    item_to_dict,
    list_items,
    make_item_id,
)
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


def _archive_count(db_path) -> int:
    """The raw `item_archive` row count — the whole recovery-store size, read
    straight from the table (not folded through `archived_records`) so the
    assertion sees the prior captures SQLite actually holds, the `_event_count`
    idiom on the archive axis."""
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM item_archive").fetchone()[0]
    finally:
        conn.close()


def _seed_archive(db_path) -> int:
    """Supersede two held items so the recovery store spans a multi-prior fold.

    Drives the production archival path (`adopt_incoming`, ADR 0106): item 0 is
    superseded **twice** (a two-link chain — two priors of one id, distinct
    `prior_hash`/`archived_at`) and item 2 once, so `item_archive` holds three
    rows across two items. That makes both fold orders non-vacuous — within an
    id (the chain) and across ids — so `archived_records`' `(archived_at,
    item_id, prior_hash)` sort is actually exercised, not a single-row pass.
    Each `archived_at` is distinct and increasing in adoption order (the H384
    chronological-append shape), so the fresh home's re-export reproduces the
    sender's read order regardless of restored local ids. Returns the seeded row
    count.
    """
    held = {item.id: item for item in list_items(db_path)}
    ids = list(held)
    first_id, third_id = ids[0], ids[2]
    # item 0, link 1: original prior (the held content_hash) → archived
    adopt_incoming(
        db_path,
        dataclasses.replace(held[first_id], content_hash="sha256:adopt0a"),
        archived_at="2026-06-20T00:00:00+00:00",
    )
    # item 0, link 2: the now-held "sha256:adopt0a" → archived (the chain's 2nd prior)
    adopt_incoming(
        db_path,
        dataclasses.replace(held[first_id], content_hash="sha256:adopt0b"),
        archived_at="2026-06-21T00:00:00+00:00",
    )
    # item 2: one prior superseded
    adopt_incoming(
        db_path,
        dataclasses.replace(held[third_id], content_hash="sha256:adopt2"),
        archived_at="2026-06-22T00:00:00+00:00",
    )
    return _archive_count(db_path)


def test_export_archive_is_a_reproducible_artifact(home, capsys):
    """`export archive` is the whole-library *prior-content recovery-store backup
    transport* (ADR 0106/H280 — the JSONL the bundle's `--with-archive` block also
    wraps), and a backup must be a reproducible artifact:

    1. exporting the *same unchanged library*'s archive twice yields a
       **byte-identical** JSONL (whole-file, not one row — an unsorted
       `item_archive` fold or a per-row non-determinism would make two recovery
       backups of one library disagree, breaking an operator who `diff`s two
       machines' archive stores), and
    2. a real `export archive` → restore into a *fresh* home → re-`export archive`
       reproduces the sender's bytes — the lossless-backup reproduction a
       single-pass identity check misses.

    The **third leg of the transport-determinism triptych** — after H379
    (`export items`, the held set) and H384 (`export events`, the verify ledger) —
    on the **archive** transport: `dump_archive_export` folds `archive_export_dict`
    over the whole `item_archive` table, a *distinct code path* from both siblings
    and from H385's per-item `archive show <id>` recovery read (which folds
    `archived_snapshots`/`latest_archived` over one item). H280/H285 pin the
    *restore outcome* (the recovered prior body), not the JSONL *bytes* — so an
    unsorted `item_archive` fold or a per-row non-determinism would pass those yet
    make two recovery backups of one library disagree.

    Not cross-seed: `archived_records` is an explicit ordered fold
    (`ORDER BY (archived_at, item_id, prior_hash)`, no set to scramble), so the
    same-process two-export check suffices — the H384 events precedent, where the
    cross-`PYTHONHASHSEED` face is reserved for surfaces whose per-row field folds
    a `set`. The realistic full restore mirrors H384: `import items` rebuilds the
    held library the recovery store recovers *into*, and `import archive`
    repopulates the standalone `item_archive` whose bytes the re-export reproduces.
    """
    src = home("source")
    _build_library(_seed_items())
    capsys.readouterr()  # drain the kb report so the export captures are clean

    seeded = _seed_archive(src.db_path)
    assert seeded == 3  # non-vacuous: a real multi-prior, multi-item recovery store

    # 1. same-library determinism: two exports, no DB change between them, are
    #    byte-identical (the artifact a `diff` across two machines must match).
    assert main(["export", "archive"]) == 0
    first_export = capsys.readouterr().out
    assert main(["export", "archive"]) == 0
    second_export = capsys.readouterr().out
    assert second_export == first_export
    # non-vacuous: the whole store travels (one JSON line per prior), not "" == ""
    assert first_export.count("\n") == seeded

    # 2. round-trip reproduction: restore into a *fresh* home from the backups
    #    alone, then re-export the archive and assert it reproduces the sender's
    #    bytes. The recovery store is keyed by `item_id` with no held-row join, so
    #    `import archive` alone repopulates the bytes; `import items` rides along to
    #    rebuild the library the store recovers into (the realistic full restore).
    assert main(["export", "items"]) == 0
    items_backup = src.root.parent / "items.jsonl"
    items_backup.write_text(capsys.readouterr().out, encoding="utf-8")
    archive_backup = src.root.parent / "archive.jsonl"
    archive_backup.write_text(first_export, encoding="utf-8")

    dst = home("rebuilt")
    assert main(["import", "items", str(items_backup)]) == 0
    assert main(["import", "archive", str(archive_backup)]) == 0
    capsys.readouterr()  # drain the import reports before the re-export capture
    assert main(["export", "archive"]) == 0
    assert capsys.readouterr().out == first_export
    # guard: the re-export read a real rebuilt store, and the priors survived the
    # restore byte-for-byte (the recovered records equal the sender's by content).
    assert _archive_count(dst.db_path) == seeded
    assert archived_records(dst.db_path) == archived_records(src.db_path)


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


# --- the round-trip transport contract (H395) --------------------------------
#
# The second **contract-consolidation** cell (the H388/H394 pattern applied to
# the PRD round-trip success-metric: "Round-trip invariant holds in CI —
# export→import→export byte-stable"). The per-transport reproducibility guards
# above and in `test_bundle.py` each hand-wrote one cell for one transport —
# H379 (`export items`), H384 (`export events`), H390 (`export archive`), and
# H368 (`export bundle`) — a treadmill that appends a new cell every time a
# transport ships. This lifts that family to a single completeness-asserted
# invariant driven off an enumerated transport registry, so a *new* lossless
# transport is auto-covered: it must either register a round-trip guard or be
# explicitly exempted, exactly the way H394's `_CLI_READ_COMMANDS` keystone ends
# the per-command determinism treadmill.
#
# Two faces, the H394 shape:
#   1. the **completeness keystone** — `_ROUND_TRIP_TRANSPORTS` (the lossless
#      custody transports) plus an explicit interchange-exempt set must partition
#      *exactly* the bidirectional `export <kind>` ∩ `import <kind>` pairs walked
#      from the live argparse registry, so a new `export X`/`import X` pair fails
#      the contract until classified (the `_MCP_READ_TOOLS`/H364 mechanism on the
#      transport axis); and
#   2. the **per-transport round-trip + determinism guard**, parametrised over
#      the registry: for every transport, two same-library exports are
#      byte-identical (the determinism leg — an unsorted fold or a per-row
#      counter would diverge) AND a real export→import→export into a fresh
#      `SCROLLS_HOME` reproduces the sender's bytes (the round-trip leg). A new
#      transport added to the registry is round-tripped automatically.
#
# The interchange-exempt set is `opml`/`bookmarks`: both expose an `export` and
# an `import`, but neither is a *lossless custody* round-trip — they are foreign
# interchange formats (a Netscape bookmark file, an OPML feed list) that carry no
# custody model to reproduce, so export→import→export is not a byte-stable
# identity over them. Listing them by name (not silently skipping them) is the
# keystone's teeth: a transport can only leave the round-trip set by an explicit,
# reasoned exemption.


def _seed_events_ledger(db_path) -> int:
    """Append a realistic chronological custody ledger on the held items: a
    verify history (unchanged → drifted) plus an import-time conflict on the
    first item and a single verify on the second — the `export events` fixture
    shape (≥2 items, ≥2 statuses, the conflict axis), every `checked_at`
    distinct and increasing in append order so the importer's stable
    sort-by-`checked_at` reproduces the sender's read order. Returns the count."""
    ids = [item.id for item in list_items(db_path)]
    first_id, second_id = ids[0], ids[1]
    record_events(db_path, [
        CustodyEvent(first_id, "2026-06-11T00:00:00+00:00", "unchanged", "h0", "h0"),
        CustodyEvent(second_id, "2026-06-11T06:00:00+00:00", "unchanged", "h1", "h1"),
        CustodyEvent(first_id, "2026-06-12T00:00:00+00:00", "drifted", "h0", "h0b"),
        conflict_event(
            first_id, held_hash="h0b", incoming_hash="hX",
            now="2026-06-13T00:00:00+00:00",
        ),
    ])
    return _event_count(db_path)


class _Transport(NamedTuple):
    """One lossless round-trip transport: how to seed a source library that
    makes its export non-vacuous, the export argv, the ordered imports that
    restore it into a fresh home, and whether the re-export needs the derived
    artifacts materialised (`doctor --fix`/`kb`) first."""

    kind: str
    export_argv: tuple[str, ...]
    # the ordered (import-kind, that-kind's export argv) restore steps run in the
    # fresh home; the import subcommand name equals the kind for every transport.
    restore: tuple[tuple[str, tuple[str, ...]], ...]
    materialize: bool
    seed: Callable[[object], object] | None


# The registry the round-trip loop is driven off. `items` reads index rows and
# `events`/`archive` read their own tables, so the re-export needs only the rows
# restored (no `doctor --fix`/`kb`); `bundle` renders a briefing over the
# materialised library, so its recipient runs the documented restore first. The
# `kind` set is held equal to `_ROUND_TRIP_KINDS` by the keystone below.
_ROUND_TRIP_TRANSPORTS: tuple[_Transport, ...] = (
    _Transport(
        kind="items",
        export_argv=("export", "items"),
        restore=(("items", ("export", "items")),),
        materialize=False,
        seed=None,
    ),
    _Transport(
        kind="events",
        export_argv=("export", "events"),
        # `export events` is item-scoped, so the held items are restored first.
        restore=(("items", ("export", "items")), ("events", ("export", "events"))),
        materialize=False,
        seed=_seed_events_ledger,
    ),
    _Transport(
        kind="archive",
        export_argv=("export", "archive"),
        # the recovery store recovers *into* the held library, restored first.
        restore=(("items", ("export", "items")), ("archive", ("export", "archive"))),
        materialize=False,
        seed=_seed_archive,
    ),
    _Transport(
        kind="bundle",
        # "search" matches the two databases scrolls in `_seed_items` (a
        # non-vacuous multi-scroll bundle), the H368 round-trip shape.
        export_argv=("export", "bundle", "search"),
        restore=(("bundle", ("export", "bundle", "search")),),
        materialize=True,
        seed=None,
    ),
)

_ROUND_TRIP_KINDS = frozenset(t.kind for t in _ROUND_TRIP_TRANSPORTS)

# Bidirectional transports that are *not* lossless custody round-trips: foreign
# interchange formats with no custody model to reproduce byte-for-byte. Named,
# not skipped, so a new bidirectional transport cannot silently dodge the
# round-trip contract (the keystone's teeth).
_INTERCHANGE_EXEMPT = {
    "opml": "OPML feed-subscription interchange, not a lossless custody transport",
    "bookmarks": "Netscape bookmark interchange, not a lossless custody transport",
}


def _registered_transport_kinds(command: str) -> set[str]:
    """The leaf subcommand names registered under `export`/`import` in the live
    argparse tree — the source of truth the completeness keystone holds the
    classification to (the `_registered_cli_command_paths` idiom, H394)."""
    for action in build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            sub = action.choices.get(command)
            if sub is None:
                continue
            for inner in sub._actions:
                if isinstance(inner, argparse._SubParsersAction):
                    return set(inner.choices)
    raise AssertionError(f"no {command!r} subcommand registry found")


def _export(argv, capsys) -> str:
    """Run one `export` command and return its stdout, asserting a clean exit."""
    rc = main(list(argv))
    captured = capsys.readouterr()
    assert rc == 0, f"{' '.join(argv)} exited {rc}: {captured.err}"
    return captured.out


def test_round_trip_registry_covers_every_export_import_pair():
    """The completeness keystone (roadmap H395): every transport that exposes
    *both* a `scrolls export <kind>` and a `scrolls import <kind>` is classified
    — either a lossless round-trip transport (`_ROUND_TRIP_TRANSPORTS`, which the
    parametrised guard round-trips) or an explicit interchange exemption. A
    *new* bidirectional transport fails this until classified, so the round-trip
    contract auto-covers it — the `_CLI_READ_COMMANDS`/H394 mechanism on the
    transport axis, the mechanism that ends the per-transport round-trip
    treadmill."""
    export_kinds = _registered_transport_kinds("export")
    import_kinds = _registered_transport_kinds("import")
    bidirectional = export_kinds & import_kinds

    classified = _ROUND_TRIP_KINDS | set(_INTERCHANGE_EXEMPT)
    assert classified == bidirectional, (
        f"transport classification drift: unclassified="
        f"{bidirectional - classified}, unknown={classified - bidirectional}"
    )
    # disjoint: a transport is round-trip *or* exempt, never both
    assert _ROUND_TRIP_KINDS.isdisjoint(_INTERCHANGE_EXEMPT)
    # every round-trip transport really has both legs in the registry
    assert _ROUND_TRIP_KINDS <= export_kinds and _ROUND_TRIP_KINDS <= import_kinds
    # the registry and the classification stay in sync (no spec without a kind)
    assert _ROUND_TRIP_KINDS == {t.kind for t in _ROUND_TRIP_TRANSPORTS}
    # non-vacuous: the four lossless transports are actually present
    assert _ROUND_TRIP_KINDS == {"items", "events", "archive", "bundle"}


@pytest.mark.parametrize(
    "transport", _ROUND_TRIP_TRANSPORTS, ids=[t.kind for t in _ROUND_TRIP_TRANSPORTS]
)
def test_round_trip_transport_is_a_reproducible_artifact(transport, home, capsys):
    """Roadmap H395, the per-transport leg: for *every* lossless transport,

    1. exporting the same unchanged library twice is **byte-identical** (the
       determinism leg — an unsorted fold or a per-row counter would diverge), and
    2. a real `export <kind>` → restore into a fresh `SCROLLS_HOME` →
       re-`export <kind>` reproduces the sender's bytes (the round-trip leg).

    Driven off `_ROUND_TRIP_TRANSPORTS`, so a new transport added to the registry
    is round-tripped automatically — the consolidation that retires the
    per-transport reproducibility cells (H368/H379/H384/H390)."""
    src = home("source")
    _build_library(_seed_items())
    if transport.seed is not None:
        transport.seed(src.db_path)
    capsys.readouterr()  # drain the kb (+ any seed) output before the export captures

    # 1. determinism: two exports of the unchanged library are byte-identical
    first = _export(transport.export_argv, capsys)
    second = _export(transport.export_argv, capsys)
    assert second == first, f"{transport.kind}: two same-library exports diverged"
    # non-vacuous: the export carried real rows, not an empty stream comparing equal
    assert first.strip(), f"{transport.kind}: export was empty (vacuous determinism)"

    # produce every restore backup from the *source* (the transport's own export
    # plus, for the item-scoped transports, the held items the restore needs)
    backups = []
    for dep_kind, dep_argv in transport.restore:
        out = _export(dep_argv, capsys)
        path = src.root.parent / f"{transport.kind}.{dep_kind}.backup"
        path.write_text(out, encoding="utf-8")
        backups.append((dep_kind, path))

    # 2. round-trip: rebuild in a fresh home from the backups alone, re-export,
    #    and assert it reproduces the sender's bytes
    dst = home("rebuilt")
    assert main(["init"]) == 0
    for dep_kind, path in backups:
        assert main(["import", dep_kind, str(path)]) == 0
    if transport.materialize:
        # the documented restore for a transport whose re-export reads the
        # rendered/compiled artifacts, not just the rows (the bundle briefing)
        assert main(["doctor", "--fix"]) == 0
        assert main(["kb"]) == 0
    capsys.readouterr()  # drain the import/restore reports before the re-export

    reexport = _export(transport.export_argv, capsys)
    assert reexport == first, (
        f"{transport.kind}: export→import→export was not byte-stable"
    )
    assert dst.db_path.exists()  # guard: the re-export read a real rebuilt store


def test_round_trip_contract_has_teeth(home, capsys, monkeypatch):
    """Roadmap H395 sabotage: a per-row counter on *one* transport's export rows
    must fail that transport's determinism leg while the others stay green.

    Monkeypatching `dump_items_export` (the items transport's export fold) to
    append a process-global counter to each call is exactly the "lossless backup
    that secretly carries a per-export sequence" regression the byte-identity leg
    exists to catch: two exports of the unchanged library now differ. A transport
    that does *not* fold through `dump_items_export` (`export archive`, whose own
    `dump_archive_export` is untouched) stays byte-identical — proving the leak is
    isolated to its transport, not a global break that any assertion would catch.
    """
    src = home("source")
    _build_library(_seed_items())
    seeded = _seed_archive(src.db_path)  # a non-vacuous archive for the green leg
    assert seeded == 3
    capsys.readouterr()

    import scrolls.cli as cli

    real_dump = cli.dump_items_export
    counter = {"n": 0}

    def leaky(items):
        # a process-global per-export counter — the exact reproducibility
        # regression (first export numbered 1, the second 2) the guard must catch
        counter["n"] += 1
        return real_dump(items) + json.dumps({"_seq": counter["n"]}) + "\n"

    monkeypatch.setattr(cli, "dump_items_export", leaky)

    # the items transport's determinism leg now FAILS (the guard has teeth)
    first_items = _export(("export", "items"), capsys)
    second_items = _export(("export", "items"), capsys)
    assert first_items != second_items, "the per-export counter must break byte-identity"

    # a transport that does not fold through dump_items_export stays green — and
    # non-vacuously so (the seeded archive really travels), proving the leak is
    # isolated to one transport rather than a global non-determinism
    first_archive = _export(("export", "archive"), capsys)
    second_archive = _export(("export", "archive"), capsys)
    assert first_archive == second_archive
    assert first_archive.count("\n") == seeded
