"""The append-only custody-ledger contract (roadmap H409) — one completeness-asserted invariant.

The sixteenth **contract-consolidation** cell and the *ledger-integrity* sibling of
H408's raw-immutability act-surface contract. Where H408 pins that every CLI write
leaves the held raw `scrolls/` tree byte-identical except the four named scroll-file
writers, this pins the parallel guarantee on the *custody ledger*: the
`custody_events` table only ever **grows**. Across *every* mutating surface — every
CLI write command (`_CLI_WRITE_COMMANDS`, H394) ∪ every custody-safe MCP write tool
(`_MCP_SAFE_WRITE_TOOLS`, H364) — no existing ledger row is ever deleted or rewritten:
the per-`_EVENT_IDENTITY` row set after any act is a **superset** of the set before
(drift/conflict/supersession is a recorded *event*, never an overwrite; custody-vision
§1, ADR 0104). The scattered per-event durability tests (the H274 conflict-event, the
H311 supersession-event, the verify-event ledger tests) are lifted to one matrix.

Two faces, the H388/H394/H399/H406 shape:

1. **The completeness keystone** — every act in the union write-registry
   (`_CLI_WRITE_COMMANDS` flat-keyed ∪ `_MCP_SAFE_WRITE_TOOLS`) is classified
   ``appends`` (records ≥1 event, naming the verb its driven invocation joins) or
   ``ledger-neutral`` (records nothing), and is either *driven* here or a *named*
   drive-exemption with a reason. A *new* mutating surface fails the contract until it
   declares its ledger effect — the H364/H394 registry-completeness mechanism on the
   ledger axis. An ``appends`` act can never be drive-exempt (an unproven append), and
   the foreign-format ingest exemptions are tied to H399's `_IMPORT_INTERCHANGE_EXEMPT`
   so the two registries cannot drift.

2. **The matrix guard** — over the shared wide fixture
   (`seed_read_surface_determinism_mix`, whose `web:hub` carries a pre-existing
   `drifted` + `conflict` ledger), each driven act runs over its own fresh
   `SCROLLS_HOME`; the `_EVENT_IDENTITY` set is snapshotted before and after, and:
   the universal claim ``after ⊇ before`` holds for *every* act (nothing deleted or
   rewritten); a ``ledger-neutral`` act adds nothing (``after == before``); an
   ``appends`` act grows the ledger and the verbs it joined equal its declared set.
   The load-bearing cases are the destructive-looking neutrals — ``rm`` (an item with
   ledger history is removed; its drift events survive, no FK cascade), ``archive
   prune``, ``import archive`` — and the seven appends (``verify``/``verify_scroll`` →
   drifted, ``reconcile`` → resolved, ``import items``/``import bundle`` → conflict,
   ``import events`` → verified, ``archive restore`` → superseded).

**Roadmap correction (the H404/H407 precedent):** the H409 spec's parenthetical
named ``reconcile`` ledger-neutral — it is not. `reconcile --keep-held` records a
``resolved`` event, and ``archive restore`` (which adopts an archived prior through
`_merge_items` accept-incoming) records a ``superseded`` event; both are ``appends``.
The spec's ``export *`` example is moot — the export transports are `_CLI_EXEMPT_READS`
(H394), never `_CLI_WRITE_COMMANDS`, so they are outside this contract's universe.

**Sabotage (the teeth):** an act that rewrites a prior event row's `checked_at` (a
silent ledger edit) shrinks/replaces the identity set. Patching `mcp_server.record_events`
— the binding *only* the MCP `verify_scroll` records through, a distinct module binding
from `cli.record_events` (the verify/reconcile/import legs) — to rewrite the oldest
existing row fails *only* the `verify_scroll` leg, the cross-surface regression a single
act's own durability test misses.

Test-only, no production change: the `custody_events` table has no DELETE/UPDATE/DROP
anywhere in `src/` (only `record_events`/`import_events` ever write it, both INSERT),
so the ledger is append-only by construction; this contract regression-proofs it and
auto-covers a new mutating surface.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from pathlib import Path

import pytest

import scrolls.cli as cli
import scrolls.mcp_server as mcp_server
from scrolls.bundle import build_bundle
from scrolls.cli import main
from scrolls.custody import _EVENT_IDENTITY
from scrolls.db import init_db
from scrolls.items import ScrollItem, adopt_incoming, insert_item
from scrolls.items_export import dump_items_export
from scrolls.paths import get_paths

from read_surface_fixture import seed_read_surface_determinism_mix

# The write registries the H394/H364 contracts hold to the live argparse / MCP
# surfaces; the H399 foreign-format interchange set, reused so the exemption can't
# drift from its source of truth (the cross-test registry idiom, H400/H405).
from test_cli_determinism import _CLI_WRITE_COMMANDS, _key  # noqa: E402
from test_mcp import _MCP_SAFE_WRITE_TOOLS  # noqa: E402
from test_roundtrip import _IMPORT_INTERCHANGE_EXEMPT  # noqa: E402

# The whole union write-surface, flat-keyed: CLI commands as space-joined paths
# ("import items", "archive restore"), MCP tools by name ("verify_scroll"). The two
# key spaces are disjoint (command words vs snake_case tool names; asserted below).
_LEDGER_MUTATORS = {_key(path) for path in _CLI_WRITE_COMMANDS} | set(_MCP_SAFE_WRITE_TOOLS)

_STATUS_IDX = _EVENT_IDENTITY.index("status")


# --- the ledger identity reader ----------------------------------------------


def _ledger_identity(db_path: Path) -> set[tuple]:
    """Every `custody_events` row as its `_EVENT_IDENTITY` 5-tuple — the content key
    the ledger dedups on (the autoincrement `id` and `detail` are not identity, H67).
    A library too old to hold the table (pre-v7) reads as the empty ledger."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_EVENT_IDENTITY)} FROM custody_events"
        ).fetchall()
    except sqlite3.OperationalError:  # no custody_events table (pre-v7 library)
        rows = []
    finally:
        conn.close()
    return {tuple(row) for row in rows}


# --- the divergent peer capture (the import-conflict driver) ------------------

# A peer library's capture of an id the fixture already holds (`arxiv:dba`, hash
# sha256:dba), at a divergent content_hash — what a content conflict is (a peer
# disagreement, never evidence the source moved). Carries "database" so `build_bundle`
# (FTS scope) lands it in the peer bundle the `import bundle` leg imports.
def _divergent_arxiv_dba() -> ScrollItem:
    return ScrollItem(
        id="arxiv:dba", source="arxiv", source_id="dba",
        url="https://arxiv.example/dba", saved_at="2026-06-12T08:00:00+00:00",
        title="Indexing in a database", stage="rendered",
        raw_text="A divergent database index capture.",
        extracted_text="A divergent database index capture.",
        content_hash="sha256:divergent",
        concepts=("Database", "Indexing"), tags=("efficient",),
    )


# --- the driven acts ----------------------------------------------------------
#
# Each entry: ``verbs`` (an appends act's declared driven verb set) or ``None`` (a
# ledger-neutral act), plus ``setup`` (build any incoming files / pre-state) and
# ``run`` (drive the act). Both receive (paths, work, capsys). The seven appends acts
# are driven so each verb the ledger can grow by is exercised; the neutral acts are
# driven to prove they add nothing — especially the destructive-looking removers.


def _noop_setup(paths, work, capsys):
    pass


def _setup_items_conflict(paths, work, capsys):
    (work / "incoming.items.jsonl").write_text(
        dump_items_export([_divergent_arxiv_dba()]), encoding="utf-8"
    )


def _run_items_conflict(paths, work, capsys):
    assert main(["import", "items", str(work / "incoming.items.jsonl")]) == 0


def _setup_bundle_conflict(paths, work, capsys):
    peer = work / "peer.db"
    init_db(peer)
    insert_item(peer, _divergent_arxiv_dba())
    (work / "incoming.bundle.md").write_text(
        build_bundle(peer, "database"), encoding="utf-8"
    )


def _run_bundle_conflict(paths, work, capsys):
    assert main(["import", "bundle", str(work / "incoming.bundle.md")]) == 0


def _setup_events(paths, work, capsys):
    # a fresh verified event for arxiv:dba (the fixture's ledger holds only web:hub),
    # so the restore imports exactly one new row carrying the `verified` verb
    line = json.dumps({
        "item_id": "arxiv:dba", "checked_at": "2026-06-20T00:00:00+00:00",
        "status": "verified", "prior_hash": "sha256:dba",
        "observed_hash": "sha256:dba", "detail": None,
    })
    (work / "incoming.events.jsonl").write_text(line + "\n", encoding="utf-8")


def _run_events(paths, work, capsys):
    assert main(["import", "events", str(work / "incoming.events.jsonl")]) == 0


def _setup_restore(paths, work, capsys):
    # a clean held item with an archived prior the restore re-adopts — built with a
    # direct `adopt_incoming` (which records nothing itself; the superseded event is
    # the restore's own), so the leg is independent of the fixture's tampered archive
    item = ScrollItem(
        id="web:restoreme", source="web", source_id="restoreme",
        url="https://web.example/restoreme", saved_at="2026-06-12T08:00:00+00:00",
        title="Restore me", stage="rendered",
        raw_text="the held body", extracted_text="the held body",
        content_hash="sha256:rm-held",
    )
    insert_item(paths.db_path, item)
    adopt_incoming(
        paths.db_path,
        dataclasses.replace(
            item, raw_text="a newer body", extracted_text="a newer body",
            content_hash="sha256:rm-new",
        ),
        archived_at="2026-06-23T00:00:00+00:00",
    )


def _run_restore(paths, work, capsys):
    assert main(["archive", "restore", "web:restoreme"]) == 0


def _run_import_archive(paths, work, capsys):
    # a self round-trip: export the fixture's archive store, re-import it (idempotent,
    # all-skipped). Touches only item_archive — never the custody ledger.
    capsys.readouterr()
    assert main(["export", "archive"]) == 0
    archive_file = work / "archive.jsonl"
    archive_file.write_text(capsys.readouterr().out, encoding="utf-8")
    assert main(["import", "archive", str(archive_file)]) == 0


_DRIVEN = {
    # --- appends: the seven verbs the ledger can grow by ----------------------
    "verify": {  # the CLI verify verdict (offline drift seam → `drifted`)
        "verbs": frozenset({"drifted"}),
        "setup": _noop_setup,
        "run": lambda paths, work, capsys: (
            None if main(["verify", "arxiv:dba"]) == 0 else pytest.fail("verify")
        ),
    },
    "verify_scroll": {  # the MCP verify verdict — the sabotage's binding
        "verbs": frozenset({"drifted"}),
        "setup": _noop_setup,
        "run": lambda paths, work, capsys: mcp_server.verify_scroll("arxiv:dba"),
    },
    "reconcile": {  # closes web:hub's open conflict → `resolved`
        "verbs": frozenset({"resolved"}),
        "setup": _noop_setup,
        "run": lambda paths, work, capsys: (
            None if main(["reconcile", "web:hub", "--keep-held"]) == 0
            else pytest.fail("reconcile")
        ),
    },
    "import items": {
        "verbs": frozenset({"conflict"}),
        "setup": _setup_items_conflict,
        "run": _run_items_conflict,
    },
    "import bundle": {
        "verbs": frozenset({"conflict"}),
        "setup": _setup_bundle_conflict,
        "run": _run_bundle_conflict,
    },
    "import events": {
        "verbs": frozenset({"verified"}),
        "setup": _setup_events,
        "run": _run_events,
    },
    "archive restore": {  # adopts an archived prior via _merge_items → `superseded`
        "verbs": frozenset({"superseded"}),
        "setup": _setup_restore,
        "run": _run_restore,
    },
    # --- ledger-neutral: records nothing (verbs=None) -------------------------
    "rm": {  # the crux: an item with ledger history is removed; its events survive
        "verbs": None,
        "setup": _noop_setup,
        "run": lambda paths, work, capsys: (
            None if main(["rm", "web:hub"]) == 0 else pytest.fail("rm")
        ),
    },
    "archive prune": {  # drops an archived prior (item_archive), never the ledger
        "verbs": None,
        "setup": _noop_setup,
        "run": lambda paths, work, capsys: (
            None
            if main(["archive", "prune", "--before", "2099-01-01T00:00:00+00:00",
                     "--apply"]) == 0
            else pytest.fail("archive prune")
        ),
    },
    "import archive": {  # re-imports the recovery store (item_archive), not the ledger
        "verbs": None,
        "setup": _noop_setup,
        "run": _run_import_archive,
    },
    "set": {  # hand-set a classification field on an item
        "verbs": None,
        "setup": _noop_setup,
        "run": lambda paths, work, capsys: (
            None if main(["set", "arxiv:dba", "category=reference"]) == 0
            else pytest.fail("set")
        ),
    },
    "classify": {  # the deterministic rules engine (offline)
        "verbs": None,
        "setup": _noop_setup,
        "run": lambda paths, work, capsys: (
            None if main(["classify", "arxiv:dba"]) == 0 else pytest.fail("classify")
        ),
    },
    "kb": {  # recompile the library/ views
        "verbs": None,
        "setup": _noop_setup,
        "run": lambda paths, work, capsys: (
            None if main(["kb"]) == 0 else pytest.fail("kb")
        ),
    },
    "agent install": {  # regenerate the agents/ instruction docs
        "verbs": None,
        "setup": _noop_setup,
        "run": lambda paths, work, capsys: (
            None if main(["agent", "install"]) == 0 else pytest.fail("agent install")
        ),
    },
    "compile_library": {  # the MCP recompile twin
        "verbs": None,
        "setup": _noop_setup,
        "run": lambda paths, work, capsys: mcp_server.compile_library(),
    },
    "run_maintenance": {  # the MCP maintenance pass — offline (no-recheck), records nothing
        "verbs": None,
        "setup": _noop_setup,
        "run": lambda paths, work, capsys: mcp_server.run_maintenance(),
    },
}

# The acts not behaviorally driven here — each ledger-neutral by construction (it never
# calls record_events) and needing live network, a foreign-format file, or bootstrap to
# run. Named with a reason, never silently skipped, so a *new* mutating surface cannot
# dodge the contract (the H406 network-exemption discipline on the ledger axis).
_DRIVE_EXEMPT = {
    "add": "live network capture; records no custody event",
    "ingest": "live network capture; records no custody event",
    "fetch": "live network re-render; records no custody event",
    "ingest_url": "live network capture (MCP); records no custody event",
    "init": "library bootstrap; creates the empty ledger, records nothing",
    "follow": "feed-subscription roster op; records no custody event",
    "unfollow": "feed-subscription roster op; records no custody event",
    "sync": "feed-subscription roster op; records no custody event",
    "follow_feed": "feed-subscription roster op (MCP); records no custody event",
    "unfollow_feed": "feed-subscription roster op (MCP); records no custody event",
    "sync_feeds": "feed-subscription roster op (MCP); records no custody event",
    "import bookmarks": "foreign-format ingest; records no custody event",
    "import opml": "foreign-format ingest; records no custody event",
    "import pocket": "foreign-format ingest; records no custody event",
    "import fieldtheory": "foreign-format ingest; records no custody event",
    "import google-takeout": "foreign-format ingest; records no custody event",
}


# --- the offline seam --------------------------------------------------------


def _recapture_drift(item: ScrollItem) -> ScrollItem:
    """A deterministic re-capture that always reports a changed body → `drifted`,
    so the verify legs append exactly the `drifted` verb offline (H406's seam)."""
    return ScrollItem(**{**dataclasses.asdict(item), "content_hash": "sha256:reverified"})


@pytest.fixture
def offline_seams(monkeypatch):
    """Patch the verify re-capture in both module namespaces so the verify legs run
    offline and deterministically (no other driven act reaches the network)."""
    monkeypatch.setattr(cli, "live_recapture", _recapture_drift)
    monkeypatch.setattr(mcp_server, "live_recapture", _recapture_drift)


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "base"))
    return tmp_path / "base"


# --- the keystone tests ------------------------------------------------------


def test_key_spaces_are_disjoint():
    """The CLI flat-keys ("import items") and MCP tool names ("verify_scroll") never
    collide, so flat-keying the union into one registry is lossless."""
    cli_keys = {_key(path) for path in _CLI_WRITE_COMMANDS}
    assert cli_keys.isdisjoint(set(_MCP_SAFE_WRITE_TOOLS))
    assert len(_LEDGER_MUTATORS) == len(cli_keys) + len(_MCP_SAFE_WRITE_TOOLS)


def test_ledger_mutator_registry_partitions_every_write_surface():
    """The completeness keystone (roadmap H409): every CLI write command ∪ custody-safe
    MCP write tool is classified driven-or-exempt, so a *new* mutating surface fails the
    contract until it declares its ledger effect — the H364/H394 registry-completeness
    mechanism on the append-only-ledger axis."""
    driven = set(_DRIVEN)
    exempt = set(_DRIVE_EXEMPT)
    # (1) driven ⊎ exempt partitions the whole union write-surface, exactly
    assert driven.isdisjoint(exempt)
    assert driven | exempt == _LEDGER_MUTATORS, (
        f"ledger-mutator classification drift: "
        f"unclassified={_LEDGER_MUTATORS - (driven | exempt)}, "
        f"unknown={(driven | exempt) - _LEDGER_MUTATORS}"
    )
    # (2) an appends act (verbs not None) can never be drive-exempt — an unproven
    #     append. Every act that grows the ledger is driven and its verb pinned.
    appends = {name for name, spec in _DRIVEN.items() if spec["verbs"] is not None}
    assert appends <= driven
    assert appends == {
        "verify", "verify_scroll", "reconcile",
        "import items", "import bundle", "import events", "archive restore",
    }
    # (3) the foreign-format ingest exemptions stay tied to H399's interchange set,
    #     so a new foreign importer classified there auto-flows into this exemption
    assert {f"import {kind}" for kind in _IMPORT_INTERCHANGE_EXEMPT} <= exempt


# --- the matrix guard --------------------------------------------------------


def _run_leg(monkeypatch, tmp_path, name, spec, capsys):
    """Seed a fresh sub-home, apply the act's pre-state, snapshot the ledger, drive the
    act, and snapshot again — the (before, after) `_EVENT_IDENTITY` sets for one leg."""
    safe = name.replace(" ", "-")
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / safe))
    assert main(["init"]) == 0
    seed_read_surface_determinism_mix(get_paths())
    work = tmp_path / f"{safe}-work"
    work.mkdir()
    capsys.readouterr()
    spec["setup"](get_paths(), work, capsys)
    before = _ledger_identity(get_paths().db_path)
    capsys.readouterr()
    spec["run"](get_paths(), work, capsys)
    capsys.readouterr()
    after = _ledger_identity(get_paths().db_path)
    return before, after


def _leg_violation(spec, before, after):
    """The reason a leg breaks the append-only contract, or None if it holds.

    Universal: the ledger never shrinks or rewrites (after ⊇ before). Then the
    class-specific claim: a neutral act adds nothing; an appends act grows the ledger
    by exactly its declared verb(s)."""
    if not before <= after:
        return f"ledger shrank/rewritten: lost {before - after}"
    joined = after - before
    joined_verbs = {row[_STATUS_IDX] for row in joined}
    if spec["verbs"] is None:  # ledger-neutral
        if joined:
            return f"ledger-neutral act appended {joined_verbs}"
        return None
    # appends: must grow, by exactly the declared verb(s)
    if not joined:
        return "appends act recorded nothing"
    if joined_verbs != spec["verbs"]:
        return f"joined verbs {joined_verbs} != declared {set(spec['verbs'])}"
    return None


def _violating_legs(monkeypatch, tmp_path, capsys):
    """The set of driven acts that broke the append-only contract — empty for the
    matrix guard, exactly the sabotaged leg for the teeth test."""
    violations = {}
    for name, spec in _DRIVEN.items():
        before, after = _run_leg(monkeypatch, tmp_path, name, spec, capsys)
        reason = _leg_violation(spec, before, after)
        if reason is not None:
            violations[name] = reason
    return violations


def test_every_write_surface_only_grows_the_ledger(
    scrolls_home, offline_seams, monkeypatch, tmp_path, capsys
):
    """Over the wide fixture (whose `web:hub` carries a pre-existing drifted+conflict
    ledger), every mutating surface only *grows* the custody ledger — the destructive
    `rm`/`archive prune`/`import archive` preserve every row, and the seven appends acts
    add exactly their verb. The one invariant the scattered per-event durability tests
    pinned piecemeal."""
    # non-vacuous: the fixture seeds a real ledger to (fail to) shrink, and the
    # divergent peer capture really conflicts with the held arxiv:dba.
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "sanity"))
    main(["init"])
    seed_read_surface_determinism_mix(get_paths())
    base = _ledger_identity(get_paths().db_path)
    assert len(base) >= 2  # web:hub's drifted + conflict
    assert {row[_STATUS_IDX] for row in base} == {"drifted", "conflict"}

    assert _violating_legs(monkeypatch, tmp_path, capsys) == {}


def test_a_ledger_rewriting_act_fails_only_that_leg(
    scrolls_home, offline_seams, monkeypatch, tmp_path, capsys
):
    """The sabotage proves the matrix has teeth and is *isolating*: an act that rewrites
    a prior event row's `checked_at` — a silent ledger edit — replaces an identity tuple,
    so the after-set is no longer a superset of the before-set. Patching
    `mcp_server.record_events` (the binding *only* `verify_scroll` records through, a
    distinct module binding from `cli.record_events`) fails *only* the `verify_scroll`
    leg; the CLI verify/reconcile/import legs, recording through `cli.record_events`, and
    every neutral leg stay green — the cross-surface regression a single act's own
    durability test misses."""
    # baseline: every leg holds the contract
    assert _violating_legs(monkeypatch, tmp_path / "base", capsys) == {}

    real_record_events = mcp_server.record_events

    def _rewriting_record_events(db_path, events):
        # silently rewrite the oldest existing event's checked_at before appending —
        # a ledger edit, the failure mode the append-only contract guards
        conn = sqlite3.connect(db_path)
        try:
            with conn:
                conn.execute(
                    "UPDATE custody_events SET checked_at = ? "
                    "WHERE id = (SELECT MIN(id) FROM custody_events)",
                    ("1999-01-01T00:00:00+00:00",),
                )
        finally:
            conn.close()
        return real_record_events(db_path, events)

    monkeypatch.setattr(mcp_server, "record_events", _rewriting_record_events)

    violations = _violating_legs(monkeypatch, tmp_path / "sab", capsys)
    assert set(violations) == {"verify_scroll"}, violations
