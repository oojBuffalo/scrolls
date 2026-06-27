"""The lossless-importer conflict/adoption parity contract (roadmap H405) — one
completeness-asserted invariant.

The twelfth **contract-consolidation** cell (after H388's whole-MCP determinism
contract … H404's compiled-page custody-honesty matrix) and the *conflict*-axis
sibling of H400's CLI↔MCP read-parity matrix. Where the round-trip/idempotency
cells (H395/H399) pin that a *clean* re-import is a no-op, this pins the
divergent case: that the two Scrolls-native **lossless** importers — `import
items` and `import bundle`, the pair routing incoming `content_hash`-bearing rows
through `_merge_items` — detect and record a content conflict **identically**, and
adopt one **identically** under `--accept-incoming`.

The claim, for *every* conflict-bearing lossless importer:

- **keep-held (the default):** a held id whose incoming `content_hash` differs is
  surfaced as a `conflict` in the report — the held copy is **kept, never
  overwritten** (custody-vision §2.4: drift/conflict is a recorded event, not an
  overwrite) — and a typed `conflict` custody event joins the append-only ledger
  (held vs incoming hash), readable on the per-item `scrolls history` timeline;
- **adopt (`--accept-incoming`):** the held capture is **archived** (recoverable
  via `scrolls archive show`, never destroyed), a `superseded` event is recorded
  (archived prior → adopted incoming), and the held row is replaced.

Two faces, the H388/H394/H399 shape:

1. **The completeness keystone** — `_CONFLICT_IMPORTERS` (the registry whose two
   kinds route through `_merge_items`) ∪ a *named* `_NO_CONFLICT_IMPORTS` set
   (`events`/`archive`, custody-store appends with no held-row *content* to
   diverge) ∪ the H399 `_IMPORT_INTERCHANGE_EXEMPT` foreign formats (reused, the
   five third-party ingests) must partition the live `import` subcommand registry
   *exactly*. A *new* lossless importer fails the contract until it declares a
   conflict-parity assertion — the H394/H399 registry-completeness mechanism on
   the conflict axis.

2. **The matrix guard** — driven off `_CONFLICT_IMPORTERS`, each importer's
   keep-held and adopt dispositions are pinned to one shared canonical disposition
   (so they are identical across importers by construction), and each is checked on
   the **durable ledger** axis (the recorded `conflict`/`superseded` event), not
   just the transient report — the H399 both-axes discipline on the conflict axis.
   The bundle's report nests `events`/`archive` blocks the items-axis parity
   normalises away (the items-axis fields are top-level on both reports).

**Sabotage (the teeth):** an importer that overwrites the held copy on conflict —
no event, nothing surfaced in `conflicts` — must fail *only* its leg.
Monkeypatching `cli._cmd_import_items` (the binding *only* the items importer
dispatches through; `_cmd_import_bundle` never calls it) with an overwrite-on-
conflict importer fails the `items` keep-held check while the `bundle` leg, routing
through the unpatched `_cmd_import_bundle` → `_merge_items`, stays green — the leak
isolated to one importer (the H400 binding-isolation precedent).

Test-only, no production change (the importers already share `_merge_items`, so
the conflict/adopt parity holds by construction; the scattered per-importer
conflict/adopt tests H272–H283 in `test_cli.py`/`test_bundle.py` stay as deeper
regression guards, the H395 discipline).
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from pathlib import Path
from typing import Callable, NamedTuple

import pytest

import scrolls.cli as cli
from scrolls.bundle import build_bundle
from scrolls.cli import main
from scrolls.custody import CONFLICT_STATUS, SUPERSEDED_STATUS, item_events
from scrolls.db import init_db
from scrolls.items import ScrollItem, get_item, insert_item
from scrolls.items_export import dump_items_export, load_items_export
from scrolls.paths import get_paths

# The H399 ingest keystone harness — the live `import` subcommand registry and the
# five named foreign-format interchange exemptions — reused so this contract holds
# to the *same* source of truth (the cross-test `_CLI_READ_PATHS` import idiom,
# H400/H398). A new foreign-format ingest classified there auto-flows here.
from test_roundtrip import (  # noqa: E402
    _IMPORT_INTERCHANGE_EXEMPT,
    _registered_transport_kinds,
)


# --- the held item and its divergent peer capture ----------------------------

_HELD_ID = "arxiv:1706.03762"
_HELD_HASH = "sha256:held"
_INCOMING_HASH = "sha256:incoming"
_HELD_BODY = "The held capture: a transformer attention paper."
_INCOMING_BODY = "A divergent peer capture of the same transformer paper."
# a rare token in both the title and the body so `build_bundle` (FTS `search_items`)
# lands the divergent copy in the peer bundle's scope
_QUERY = "transformer"


def _held_item() -> ScrollItem:
    """The held capture an importer's incoming row will diverge from — a rendered,
    content-bearing holding (raw + hash), so `adopt_incoming` has a real prior to
    archive and `archive show` has bytes to recover."""
    return ScrollItem(
        id=_HELD_ID,
        source="arxiv",
        url="https://arxiv.org/abs/1706.03762",
        saved_at="2026-06-12T00:00:00+00:00",
        title="Attention transformer paper",
        extracted_text=_HELD_BODY,
        raw_text=f"<raw>{_HELD_BODY}</raw>",
        content_hash=_HELD_HASH,
        stage="rendered",
    )


def _divergent_item() -> ScrollItem:
    """Another library's capture of the *same id* at another time: the same
    spine, a different captured `content_hash` + body — what a content conflict
    is (custody-vision §2.4, a peer disagreement, never evidence the source moved)."""
    return dataclasses.replace(
        _held_item(),
        extracted_text=_INCOMING_BODY,
        raw_text=f"<raw>{_INCOMING_BODY}</raw>",
        content_hash=_INCOMING_HASH,
    )


# --- the conflict-bearing importer registry (the completeness keystone axis) ---


class _ConflictImporter(NamedTuple):
    kind: str  # the `scrolls import <kind>` leaf subcommand
    # write the divergent incoming capture in this importer's wire format, return
    # the file the held library imports
    make_incoming: Callable[[ScrollItem, Path], Path]


def _items_incoming(divergent: ScrollItem, tmp_path: Path) -> Path:
    """The `import items` wire format: a one-row lossless JSONL export."""
    path = tmp_path / "incoming.items.jsonl"
    path.write_text(dump_items_export([divergent]), encoding="utf-8")
    return path


def _bundle_incoming(divergent: ScrollItem, tmp_path: Path) -> Path:
    """The `import bundle` wire format: a peer's portable custody bundle carrying
    the divergent capture. Built from a standalone source library holding only the
    divergent copy (the "take it with me across libraries" shape, test_bundle's
    cross-library round-trip), then handed to the held library's importer."""
    src_db = tmp_path / "peer-source.db"
    init_db(src_db)
    insert_item(src_db, divergent)
    path = tmp_path / "incoming.bundle.md"
    path.write_text(build_bundle(src_db, _QUERY), encoding="utf-8")
    return path


_CONFLICT_IMPORTERS: tuple[_ConflictImporter, ...] = (
    _ConflictImporter("items", _items_incoming),
    _ConflictImporter("bundle", _bundle_incoming),
)
_CONFLICT_IMPORTER_KINDS = frozenset(t.kind for t in _CONFLICT_IMPORTERS)

# Lossless import subcommands that carry no held-row *content* to diverge: the
# custody-store appends. `import events` writes only the append-only custody_events
# ledger and `import archive` only the item_archive recovery store — neither ever
# touches a held capture, so there is no "incoming content disagrees with what we
# hold" to detect (their re-import settle is the H399/H380/H386 idempotency cells).
# Named, not skipped, so a new lossless importer cannot silently dodge this
# contract (the keystone's teeth, the H399 `_IMPORT_INTERCHANGE_EXEMPT` discipline
# on the conflict axis).
_NO_CONFLICT_IMPORTS = {
    "events": "custody-ledger append (custody_events); no held-row content to diverge",
    "archive": "recovery-store append (item_archive); no held-row content to diverge",
}


def test_conflict_importer_registry_partitions_every_import_subcommand():
    """The completeness keystone (roadmap H405): every `scrolls import <kind>` leaf
    subcommand is classified — a conflict-bearing lossless importer
    (`_CONFLICT_IMPORTERS`, the pair routing rows through `_merge_items`, which the
    matrix guard drives both ways), a content-less custody-store append
    (`_NO_CONFLICT_IMPORTS`), or a foreign-format interchange ingest
    (`_IMPORT_INTERCHANGE_EXEMPT`, reused from H399). A *new* lossless importer
    fails this until classified, so the conflict-parity contract auto-covers it —
    the `_CLI_READ_PATHS`/H394 mechanism on the conflict axis."""
    import_kinds = _registered_transport_kinds("import")
    classified = (
        _CONFLICT_IMPORTER_KINDS
        | set(_NO_CONFLICT_IMPORTS)
        | set(_IMPORT_INTERCHANGE_EXEMPT)
    )
    assert classified == import_kinds, (
        f"import classification drift: unclassified={import_kinds - classified}, "
        f"unknown={classified - import_kinds}"
    )
    # disjoint: each importer is conflict-bearing XOR content-less XOR foreign-interchange
    assert _CONFLICT_IMPORTER_KINDS.isdisjoint(_NO_CONFLICT_IMPORTS)
    assert _CONFLICT_IMPORTER_KINDS.isdisjoint(_IMPORT_INTERCHANGE_EXEMPT)
    assert set(_NO_CONFLICT_IMPORTS).isdisjoint(_IMPORT_INTERCHANGE_EXEMPT)
    # every conflict-bearing importer really is a registered import subcommand
    assert _CONFLICT_IMPORTER_KINDS <= import_kinds
    # the registry and the classification stay in sync (no spec without a kind)
    assert _CONFLICT_IMPORTER_KINDS == {t.kind for t in _CONFLICT_IMPORTERS}
    # non-vacuous: the two Scrolls-native lossless importers are actually present
    assert _CONFLICT_IMPORTER_KINDS == {"items", "bundle"}


# --- the parametrised matrix guard -------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Point the active library at a named home under tmp_path; a factory so one
    test can build several fresh held libraries side by side (the test_roundtrip
    idiom) — the sabotage runs both importers under one patch."""

    def use(name: str):
        monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / name))
        return get_paths()

    return use


# the full items-axis disposition both importers carry at the *top* level of their
# report (the bundle's nested events/archive blocks are normalised away)
_DISPOSITION_KEYS = ("imported", "skipped", "unchanged", "conflict", "conflicts", "adopted")


def _disposition(report: dict) -> dict:
    return {key: report[key] for key in _DISPOSITION_KEYS}


def _seed_held(home, name: str):
    """A fresh held library holding the single content-bearing capture every
    incoming row diverges from. Returns its db path."""
    paths = home(name)
    assert main(["init"]) == 0
    insert_item(paths.db_path, _held_item())
    return paths.db_path


def _check_conflict_is_kept_and_recorded(importer, home, tmp_path, capsys) -> dict:
    """keep-held (the default): a divergent incoming capture is surfaced as a
    conflict, the held copy untouched, a durable `conflict` event recorded —
    identically for every conflict-bearing importer. Returns the disposition."""
    db = _seed_held(home, f"{importer.kind}-conflict")
    incoming = importer.make_incoming(_divergent_item(), tmp_path)
    capsys.readouterr()  # drain init/seed before the import capture

    assert main(["import", importer.kind, str(incoming)]) == 0
    disposition = _disposition(json.loads(capsys.readouterr().out))

    # the report disposition: the divergence is surfaced as a *kept* conflict —
    # nothing imported, nothing adopted, the held id named in `conflicts`
    assert disposition == {
        "imported": 0,
        "skipped": 1,
        "unchanged": 0,
        "conflict": 1,
        "conflicts": [_HELD_ID],
        "adopted": [],
    }, f"{importer.kind}: keep-held conflict disposition diverged"
    # the held copy is preserved byte-for-byte — never overwritten (custody §2.4)
    kept = get_item(db, _HELD_ID)
    assert kept.content_hash == _HELD_HASH and kept.extracted_text == _HELD_BODY, (
        f"{importer.kind}: the held copy was overwritten on conflict"
    )
    # the durable ledger axis (the decisive choice, not just the transient report):
    # a typed `conflict` event joined the append-only timeline (held vs incoming)
    events = item_events(db, _HELD_ID)
    assert [e.status for e in events] == [CONFLICT_STATUS], (
        f"{importer.kind}: no durable conflict event recorded"
    )
    assert events[0].prior_hash == _HELD_HASH  # what we hold
    assert events[0].observed_hash == _INCOMING_HASH  # what the peer presented
    return disposition


def _check_accept_incoming_adopts_and_archives(importer, home, tmp_path, capsys) -> dict:
    """adopt (`--accept-incoming`): the held capture is replaced by the incoming
    one, the prior archived (recoverable), a durable `superseded` event recorded —
    identically for every conflict-bearing importer. Returns the disposition."""
    db = _seed_held(home, f"{importer.kind}-adopt")
    incoming = importer.make_incoming(_divergent_item(), tmp_path)
    capsys.readouterr()

    assert main(["import", importer.kind, str(incoming), "--accept-incoming"]) == 0
    disposition = _disposition(json.loads(capsys.readouterr().out))

    # the report disposition: the divergence is *adopted*, not kept — the held id
    # named in `adopted`, nothing left as a conflict
    assert disposition == {
        "imported": 0,
        "skipped": 0,
        "unchanged": 0,
        "conflict": 0,
        "conflicts": [],
        "adopted": [_HELD_ID],
    }, f"{importer.kind}: accept-incoming adoption disposition diverged"
    # the held row now carries the incoming capture (the adoption happened)
    now_held = get_item(db, _HELD_ID)
    assert now_held.content_hash == _INCOMING_HASH
    assert now_held.extracted_text == _INCOMING_BODY
    # the durable ledger axis: a `superseded` event (archived prior → adopted incoming)
    events = item_events(db, _HELD_ID)
    assert [e.status for e in events] == [SUPERSEDED_STATUS], (
        f"{importer.kind}: no durable superseded event recorded"
    )
    assert events[0].prior_hash == _HELD_HASH  # the archived prior copy
    assert events[0].observed_hash == _INCOMING_HASH  # the adopted incoming copy
    # the prior capture is archived, recoverable byte-for-byte via `archive show`
    capsys.readouterr()
    assert main(["archive", "show", _HELD_ID]) == 0
    recovered = json.loads(capsys.readouterr().out.splitlines()[0])
    assert recovered["content_hash"] == _HELD_HASH
    assert recovered["extracted_text"] == _HELD_BODY
    return disposition


@pytest.mark.parametrize(
    "importer", _CONFLICT_IMPORTERS, ids=[t.kind for t in _CONFLICT_IMPORTERS]
)
def test_a_divergent_capture_is_kept_and_recorded(importer, home, tmp_path, capsys):
    """Roadmap H405, the keep-held leg: for *every* conflict-bearing lossless
    importer, a held id re-imported with a different `content_hash` is a kept,
    surfaced, durably-recorded conflict — the held copy never overwritten. Driven
    off `_CONFLICT_IMPORTERS`, so a new lossless importer is checked automatically."""
    _check_conflict_is_kept_and_recorded(importer, home, tmp_path, capsys)


@pytest.mark.parametrize(
    "importer", _CONFLICT_IMPORTERS, ids=[t.kind for t in _CONFLICT_IMPORTERS]
)
def test_accept_incoming_adopts_and_archives(importer, home, tmp_path, capsys):
    """Roadmap H405, the adopt leg: for *every* conflict-bearing lossless importer,
    `--accept-incoming` adopts the divergent capture — replacing the held row,
    archiving the recoverable prior, and recording a durable `superseded` event."""
    _check_accept_incoming_adopts_and_archives(importer, home, tmp_path, capsys)


# --- the teeth ----------------------------------------------------------------


def _overwriting_import_items(path, accept_incoming: bool = False) -> int:
    """A buggy lossless importer that **overwrites** the held copy on conflict — no
    `conflict` event recorded, nothing surfaced in `conflicts` (the exact failure
    mode the contract guards: a silent rewrite of a held capture, custody §2.4
    violated). Reports a clean import so a report-only check would be blind."""
    items, _ = load_items_export(Path(path).expanduser())
    db = get_paths().db_path
    conn = sqlite3.connect(db)
    try:
        for item in items:
            conn.execute(
                "UPDATE items SET content_hash = ?, extracted_text = ? WHERE id = ?",
                (item.content_hash, item.extracted_text, item.id),
            )
        conn.commit()
    finally:
        conn.close()
    print(
        json.dumps(
            {
                "imported": 0,
                "skipped": len(items),
                "unchanged": len(items),
                "conflict": 0,
                "conflicts": [],
                "adopted": [],
                "content_duplicates": 0,
                "items": len(items),
            }
        )
    )
    return 0


def test_conflict_parity_contract_has_teeth(home, tmp_path, capsys, monkeypatch):
    """Roadmap H405 sabotage: an importer that overwrites the held copy on conflict
    (no event, no `conflicts` surface) must fail *only* its leg.

    Monkeypatching `cli._cmd_import_items` — the binding *only* the items importer
    dispatches through (`_cmd_import_bundle` never calls it) — with the overwrite-on-
    conflict importer is exactly that regression. The `items` keep-held check fails
    (the held copy was rewritten and no conflict surfaced) while the `bundle` leg,
    routing through the unpatched `_cmd_import_bundle` → `_merge_items`, stays a
    correct kept-and-recorded conflict — proving the leak is isolated to one
    importer, not a global break any assertion would catch (the H400 precedent)."""
    monkeypatch.setattr(cli, "_cmd_import_items", _overwriting_import_items)
    items_importer = next(t for t in _CONFLICT_IMPORTERS if t.kind == "items")
    bundle_importer = next(t for t in _CONFLICT_IMPORTERS if t.kind == "bundle")

    # the sabotaged items importer fails its keep-held leg…
    with pytest.raises(AssertionError):
        _check_conflict_is_kept_and_recorded(items_importer, home, tmp_path, capsys)
    # …while the bundle importer — untouched by the patch — still holds (isolation)
    _check_conflict_is_kept_and_recorded(bundle_importer, home, tmp_path, capsys)
