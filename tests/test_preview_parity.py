"""The preview ↔ live-run parity contract (roadmap H416) — one completeness-asserted invariant.

The twenty-third **contract-consolidation** cell, the *preview-never-drifts* sibling
of H409's append-only-ledger and H408's raw-immutability act-surface matrices. Those
two pin what a *live* act may touch (the ledger only grows; the raw `scrolls/` tree
stays byte-identical except the four named scroll-file writers). This pins the dual
guarantee on the *preview* surface: a read-only preview (``--dry-run`` / report-only
until ``--apply``) **touches nothing yet predicts the live effect exactly**.

For every CLI write command that ships a preview mode, the contract asserts:

1. **The no-op on all three durable axes** — running the preview leaves the library
   byte-identical on (a) the `custody_events` ledger (the `_EVENT_IDENTITY` row set,
   H409), (b) the raw `scrolls/` capture tree (the `{relpath → sha256}` whole-tree
   hash, H408/H363), *and* (c) the `items` / `item_archive` row counts. The decisive
   choice (the spec's): assert the no-op on **all three** durable axes, not just the
   report — a preview that writes one ledger/raw/row mutation behind a clean report is
   the precise failure mode (custody-vision §1/§2.4: the ledger is append-only, raw is
   sacred — a preview must not slip a write past either).

2. **The prediction parity** — the preview's predicted disposition equals what the
   live run then produces. Each act runs its preview over one fresh-seeded copy and
   the live act over a second; stripping each report's preview-only bookkeeping keys
   (``dry_run``/``new``/``held`` for the dry-run acts, ``applied``/``dropped`` for the
   report-only prune) yields the **same disposition** — the counts/ids/outcome the
   live act realizes (the H220/H226/H245/H273/H353 "the preview never lies"
   discipline, lifted from the scattered per-command tests to one matrix).

Two faces, the H388/H408/H409 shape:

- **The completeness keystone** — `_PREVIEW_ACTS` (the four write commands with a
  preview mode) ∪ `_NO_PREVIEW` (the named write commands with none) must partition
  `_CLI_WRITE_COMMANDS` (H394) *exactly*, so a *new* write command shipping a preview
  mode fails the contract until it declares a parity assertion (the H408/H409
  registry-completeness mechanism on the preview axis). Backed by an argparse
  introspection leg: every `_PREVIEW_ACTS` leaf parser declares its preview option
  (``--dry-run`` or ``--apply``) and every `_NO_PREVIEW` leaf parser has **neither**,
  so a new command that ships ``--dry-run`` but is mis-filed in `_NO_PREVIEW` is caught
  even before it is driven (a registry constant cannot quietly mask a real preview).

- **The behavioural matrix** — over the shared wide fixture
  (`seed_read_surface_determinism_mix`, whose `web:hub` carries an unresolved conflict
  and `web:archived` a real archived prior), each preview act is driven to a
  *non-vacuous* disposition (a conflicting + adding bundle import, the open conflict,
  the archived prior, a prunable row), and both the no-op and the prediction faces are
  asserted. Two sabotages prove the teeth and the isolation: a preview that secretly
  writes (a stray ledger event in the import-bundle preview path) fails *only* its
  no-op leg; a preview that mispredicts (an under-counting prune drop-set) fails *only*
  its prediction leg.

**Roadmap correction (the H404/H407/H409/H412/H413 precedent).** The H416 spec's
`_PREVIEW_ACTS` sketch listed ``import items`` / ``import bundle`` / ``import events``
``--dry-run``. On the live argparse surface only **`import bundle`** carries
``--dry-run``: `import items`/`import events`/`import archive` have *no* preview flag
(they are id-keyed/dedup-idempotent restores; `import bundle` is the one previewable
importer). The real preview surfaces are therefore exactly four — `import bundle
--dry-run`, `reconcile --dry-run`, `archive restore --dry-run`, and `archive prune`
(report-only until `--apply`) — and the other twenty-one writes are `_NO_PREVIEW`. The
partition + introspection legs hold that classification to the live registry.

Test-only, no production change: every preview path already exists and is correct
(``_preview_merge_items``/``preview_import_events``/``select_prunable_archive`` are the
read-only twins of the live writers); this consolidates the per-command preview tests
into one completeness-asserted matrix that auto-covers a new preview-shipping write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import scrolls.cli as cli
from scrolls.bundle import build_bundle
from scrolls.cli import build_parser, main
from scrolls.custody import CustodyEvent, _EVENT_IDENTITY, record_events
from scrolls.db import init_db
from scrolls.items import ScrollItem, insert_item
from scrolls.paths import get_paths

from read_surface_fixture import seed_read_surface_determinism_mix

# The live argparse write registry the H394 contract holds to the CLI surface.
# Keying the partition to it makes a *new* write command first fail H394's
# classification (until declared a write), then this contract (until it declares
# whether it ships a preview mode and, if so, a parity assertion).
from test_cli_determinism import _CLI_WRITE_COMMANDS, _key  # noqa: E402


# --- the three durable-axis snapshots (the H408/H409 idioms) ------------------


def _ledger_identity(db_path: Path) -> set[tuple]:
    """Every `custody_events` row as its `_EVENT_IDENTITY` tuple — the H409 reader.
    A library too old to hold the table reads as the empty ledger."""
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


def _scroll_tree(paths) -> dict[str, str]:
    """`{relpath → sha256}` over every held scroll under `scrolls/` — the H408/H363
    whole-tree fingerprint that catches any byte change to a held capture, or a
    deletion, not just a count drift."""
    return {
        file.relative_to(paths.root).as_posix(): hashlib.sha256(
            file.read_bytes()
        ).hexdigest()
        for file in sorted(paths.scrolls_dir.rglob("*.md"))
    }


def _row_counts(db_path: Path) -> tuple[int, int]:
    """The `(items, item_archive)` row counts — the third durable axis (a preview must
    not insert/delete a held row or an archived prior). A pre-v8 library reads (0, 0)."""
    conn = sqlite3.connect(db_path)
    try:
        items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    except sqlite3.OperationalError:
        items = 0
    try:
        archive = conn.execute("SELECT COUNT(*) FROM item_archive").fetchone()[0]
    except sqlite3.OperationalError:
        archive = 0
    finally:
        conn.close()
    return items, archive


def _durable_state(paths) -> tuple:
    """The three durable axes a preview must leave byte-identical."""
    return (
        _ledger_identity(paths.db_path),
        _scroll_tree(paths),
        _row_counts(paths.db_path),
    )


def _disposition(report: dict, preview_only: frozenset) -> dict:
    """The report minus its preview-vs-live bookkeeping keys — the canonical
    disposition that must be identical across the preview and the live run."""
    return {k: v for k, v in report.items() if k not in preview_only}


# --- the import-bundle incoming (a non-vacuous conflict + add) ----------------


def _divergent_arxiv_dba() -> ScrollItem:
    """A peer's capture of a held id (`arxiv:dba`) at a divergent content hash — a
    content conflict on import. Carries "database" so `build_bundle` (FTS scope)
    lands it in the peer bundle the `import bundle` preview imports."""
    return ScrollItem(
        id="arxiv:dba", source="arxiv", source_id="dba",
        url="https://arxiv.example/dba", saved_at="2026-06-12T08:00:00+00:00",
        title="Indexing in a database", stage="rendered",
        raw_text="A divergent database index capture.",
        extracted_text="A divergent database index capture.",
        content_hash="sha256:divergent",
        concepts=("Database", "Indexing"), tags=("efficient",),
    )


def _brand_new_arxiv() -> ScrollItem:
    """A bundle item the target library does not hold — the `imported` side of the
    disposition, so the preview predicts a real add, not just a conflict."""
    return ScrollItem(
        id="arxiv:brandnew", source="arxiv", source_id="brandnew",
        url="https://arxiv.example/brandnew", saved_at="2026-06-12T08:00:00+00:00",
        title="A brand new database paper", stage="rendered",
        raw_text="A brand new database body.",
        extracted_text="A brand new database body.",
        content_hash="sha256:brandnew", concepts=("Database",),
    )


def _setup_bundle(work: Path) -> None:
    """Build a peer bundle carrying one conflict (divergent arxiv:dba) + one add
    (arxiv:brandnew), so the import-bundle preview's disposition is non-vacuous."""
    peer = work / "peer.db"
    init_db(peer)
    insert_item(peer, _divergent_arxiv_dba())
    insert_item(peer, _brand_new_arxiv())
    (work / "incoming.bundle.md").write_text(
        build_bundle(peer, "database"), encoding="utf-8"
    )


def _noop_setup(work: Path) -> None:
    """The conflict/archive/prunable pre-state the fixture already seeds."""


# --- the preview-act registry — the completeness keystone --------------------
#
# Each act: ``preview_argv``/``live_argv`` (built against the shared ``work`` dir),
# ``preview_option`` (the argparse flag that distinguishes preview from live —
# ``--dry-run`` adds a preview, ``--apply`` adds the live run), ``preview_only``
# (the bookkeeping keys stripped from both reports before the disposition compare),
# and ``setup`` (build any incoming files into ``work``). The disposition each act
# is driven to is non-vacuous (asserted in the matrix): a conflicting+adding bundle
# import, the fixture's open conflict, its archived prior, its one prunable row.

_PREVIEW_ACTS = {
    ("import", "bundle"): {
        "setup": _setup_bundle,
        "preview_argv": lambda w: [
            "import", "bundle", str(w / "incoming.bundle.md"), "--dry-run"
        ],
        "live_argv": lambda w: ["import", "bundle", str(w / "incoming.bundle.md")],
        "preview_option": "--dry-run",
        # the dry-run-only review id lists (H226) ride alongside `dry_run`
        "preview_only": frozenset({"dry_run", "new", "held"}),
    },
    ("reconcile",): {
        "setup": _noop_setup,
        "preview_argv": lambda w: ["reconcile", "web:hub", "--keep-held", "--dry-run"],
        "live_argv": lambda w: ["reconcile", "web:hub", "--keep-held"],
        "preview_option": "--dry-run",
        "preview_only": frozenset({"dry_run"}),
    },
    ("archive", "restore"): {
        "setup": _noop_setup,
        "preview_argv": lambda w: ["archive", "restore", "web:archived", "--dry-run"],
        "live_argv": lambda w: ["archive", "restore", "web:archived"],
        "preview_option": "--dry-run",
        "preview_only": frozenset({"dry_run"}),
    },
    ("archive", "prune"): {
        "setup": _noop_setup,
        # report-only is the default; the live run adds --apply (no --dry-run flag)
        "preview_argv": lambda w: [
            "archive", "prune", "--before", "2099-01-01T00:00:00+00:00"
        ],
        "live_argv": lambda w: [
            "archive", "prune", "--before", "2099-01-01T00:00:00+00:00", "--apply"
        ],
        "preview_option": "--apply",
        # `applied` flips false→true; `dropped` is 0 in preview, == matched after apply
        "preview_only": frozenset({"applied", "dropped"}),
    },
}

# The write commands with no preview mode — each named with the reason it has none,
# so a *new* mutating surface cannot dodge the contract (the H409 named-exemption
# discipline on the preview axis). Roadmap correction: `import items`/`import
# events`/`import archive` are here (no --dry-run flag), not in `_PREVIEW_ACTS`.
_NO_PREVIEW = {
    ("add",): "live network capture; no preview mode",
    ("agent", "install"): "regenerates agents/ docs; idempotent, no preview mode",
    ("classify",): "deterministic re-classify + re-render; no preview mode",
    ("fetch",): "live network advance; no preview mode",
    ("follow",): "feed-subscription roster op; no preview mode",
    ("ingest",): "live network capture + render; no preview mode",
    ("init",): "library bootstrap; no preview mode",
    ("kb",): "recompiles library/ views; idempotent, no preview mode",
    ("rm",): "deletes a held scroll; no preview mode (archive recovery is the safety net)",
    ("set",): "hand-set a field + re-render; no preview mode",
    ("sync",): "feed-subscription poll; no preview mode",
    ("unfollow",): "feed-subscription roster op; no preview mode",
    ("verify",): "records a verify verdict; no preview mode",
    ("import", "archive"): "recovery-store restore; idempotent dedupe, no --dry-run flag",
    ("import", "bookmarks"): "foreign-format ingest; no preview mode",
    ("import", "events"): "ledger restore; idempotent dedupe, no --dry-run flag",
    ("import", "fieldtheory"): "foreign-format ingest; no preview mode",
    ("import", "google-takeout"): "foreign-format ingest; no preview mode",
    ("import", "items"): "items restore; no --dry-run flag (bundle is the previewable importer)",
    ("import", "opml"): "foreign-format ingest; no preview mode",
    ("import", "pocket"): "foreign-format ingest; no preview mode",
}


# --- argparse leaf introspection (the keystone's behavioural backstop) --------


def _leaf_option_strings() -> dict[tuple, set[str]]:
    """Every leaf subcommand path → the set of option strings its parser declares,
    walked from the live argparse tree — the source of truth the introspection leg
    holds the preview classification to."""
    out: dict[tuple, set[str]] = {}

    def walk(parser, prefix=()):
        subs = [
            a for a in parser._actions
            if isinstance(a, argparse._SubParsersAction)
        ]
        if not subs:
            if prefix:
                opts: set[str] = set()
                for action in parser._actions:
                    opts |= set(action.option_strings)
                out[prefix] = opts
            return
        for action in subs:
            for name, sub in action.choices.items():
                walk(sub, prefix + (name,))

    walk(build_parser())
    return out


# --- the keystone tests ------------------------------------------------------


def test_preview_registry_partitions_the_write_registry():
    """The completeness keystone (roadmap H416): the preview-act paths and the named
    no-preview paths are disjoint and together cover *exactly* `_CLI_WRITE_COMMANDS`
    (H394), so a *new* CLI write command fails the contract until it declares whether
    it ships a preview mode — the H408/H409 registry-completeness mechanism on the
    preview axis."""
    preview = set(_PREVIEW_ACTS)
    no_preview = set(_NO_PREVIEW)
    assert preview.isdisjoint(no_preview)
    assert preview | no_preview == set(_CLI_WRITE_COMMANDS), (
        "preview-classification drift: "
        f"unclassified={set(_CLI_WRITE_COMMANDS) - (preview | no_preview)}, "
        f"unknown={(preview | no_preview) - set(_CLI_WRITE_COMMANDS)}"
    )
    # disjoint + total ⇒ the count is exact (no command double-counted)
    assert len(preview) + len(no_preview) == len(_CLI_WRITE_COMMANDS)
    # non-trivial: the preview acts are exactly the four with a preview mode (a
    # registry that quietly emptied itself would still pass the partition)
    assert preview == {
        ("import", "bundle"), ("reconcile",),
        ("archive", "restore"), ("archive", "prune"),
    }


def test_preview_option_introspection_matches_the_live_argparse_surface():
    """The keystone's behavioural backstop: every preview act's leaf parser declares
    its preview option (``--dry-run`` / ``--apply``), and every no-preview act's leaf
    parser declares **neither** — so a new write command shipping ``--dry-run`` but
    mis-filed in `_NO_PREVIEW` is caught against the live argparse tree, not just the
    hand-maintained constant (the H394 registry-vs-reality mechanism on the preview
    axis)."""
    options = _leaf_option_strings()
    for key, spec in _PREVIEW_ACTS.items():
        assert key in options, f"{_key(key)} is not a registered leaf command"
        assert spec["preview_option"] in options[key], (
            f"{_key(key)} no longer declares its preview option "
            f"{spec['preview_option']!r}"
        )
    # exactly the three --dry-run acts and the one --apply act carry a preview flag;
    # every no-preview command has neither (so the partition is earned, not asserted)
    for key, reason in _NO_PREVIEW.items():
        assert key in options, f"{_key(key)} is not a registered leaf command"
        opts = options[key]
        assert "--dry-run" not in opts and "--apply" not in opts, (
            f"{_key(key)} declares a preview option but is filed _NO_PREVIEW "
            f"({reason})"
        )


# --- the matrix --------------------------------------------------------------


def _seed(monkeypatch, home: Path) -> None:
    monkeypatch.setenv("SCROLLS_HOME", str(home))
    assert main(["init"]) == 0
    seed_read_surface_determinism_mix(get_paths())


def _run_leg(monkeypatch, tmp_path, key, spec, capsys):
    """Drive one preview act: the preview over a fresh-seeded copy (snapshotting the
    three durable axes around it) and the live act over a *second* fresh copy. Returns
    (before, after, preview_report, live_report) — the no-op axes ride (before, after);
    the prediction axis rides the two reports."""
    safe = _key(key).replace(" ", "-")
    work = tmp_path / f"{safe}-work"
    work.mkdir(parents=True)
    spec["setup"](work)  # build any incoming files once; both copies read them

    # the preview copy — snapshot durable, run the preview, snapshot again
    _seed(monkeypatch, tmp_path / f"{safe}-preview")
    capsys.readouterr()
    before = _durable_state(get_paths())
    assert main(spec["preview_argv"](work)) == 0
    preview_report = json.loads(capsys.readouterr().out)
    after = _durable_state(get_paths())

    # the live copy — fresh seed, run the live act, capture its report
    _seed(monkeypatch, tmp_path / f"{safe}-live")
    capsys.readouterr()
    assert main(spec["live_argv"](work)) == 0
    live_report = json.loads(capsys.readouterr().out)

    return before, after, preview_report, live_report


def _noop_reason(before, after) -> str | None:
    """The durable axis a preview mutated, or None if all three held."""
    if before[0] != after[0]:
        return f"ledger changed (+{after[0] - before[0]}, -{before[0] - after[0]})"
    if before[1] != after[1]:
        return "raw scroll tree changed"
    if before[2] != after[2]:
        return f"row counts changed {before[2]} → {after[2]}"
    return None


def _prediction_reason(spec, preview_report, live_report) -> str | None:
    """The disposition mismatch between preview and live, or None if they agree."""
    predicted = _disposition(preview_report, spec["preview_only"])
    realized = _disposition(live_report, spec["preview_only"])
    if predicted != realized:
        return f"predicted {predicted} != realized {realized}"
    return None


def _violating_legs(monkeypatch, tmp_path, capsys):
    """The {leg: reason} of every preview act that broke either face — empty for the
    matrix guard, exactly the sabotaged leg for the teeth tests."""
    violations: dict[str, str] = {}
    for key, spec in _PREVIEW_ACTS.items():
        before, after, preview_report, live_report = _run_leg(
            monkeypatch, tmp_path, key, spec, capsys
        )
        reason = _noop_reason(before, after) or _prediction_reason(
            spec, preview_report, live_report
        )
        if reason is not None:
            violations[_key(key)] = reason
    return violations


def _assert_dispositions_non_vacuous(monkeypatch, tmp_path, capsys):
    """Each preview act predicts a real effect — so the parity claim is not over a
    trivially-empty disposition (an act that previews nothing would pass {} == {})."""
    reports = {}
    for key, spec in _PREVIEW_ACTS.items():
        _, _, preview_report, _ = _run_leg(monkeypatch, tmp_path, key, spec, capsys)
        reports[_key(key)] = preview_report
    bundle = reports["import bundle"]
    assert bundle["imported"] == 1 and bundle["conflict"] == 1  # a real add + conflict
    assert reports["reconcile"]["resolved"] is True             # the open conflict
    assert reports["archive restore"]["restored"] is True       # the archived prior
    assert reports["archive prune"]["matched"] == 1             # the prunable row


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "base"))
    return tmp_path / "base"


def test_every_preview_is_a_no_op_and_predicts_the_live_run(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    """The behavioural matrix (roadmap H416): over the wide non-vacuous fixture, every
    preview act (1) leaves all three durable axes — ledger, raw tree, row counts —
    byte-identical, and (2) predicts the disposition the live run then realizes. The
    one invariant the scattered per-command preview tests (H220/H226/H245/H273/H353)
    pinned piecemeal."""
    _assert_dispositions_non_vacuous(monkeypatch, tmp_path / "vacuity", capsys)
    assert _violating_legs(monkeypatch, tmp_path / "matrix", capsys) == {}


def test_a_preview_that_secretly_writes_fails_only_its_noop_leg(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    """Sabotage (the decisive axis): a preview that slips a write past a clean report.
    `cli.preview_import_events` is the read-only twin the *import-bundle* preview folds
    its events block through — and the only preview leg that routes through it (the live
    bundle import uses the real `import_events`, and reconcile/restore/prune never touch
    it). Making it append a stray ledger event grows the import-bundle preview's ledger,
    failing *only* that leg's no-op axis; the other three previews stay byte-identical,
    and the disposition (unchanged by a stray write outside the report) stays correct —
    the cross-surface regression a single command's own dry-run test cannot see."""
    assert _violating_legs(monkeypatch, tmp_path / "base", capsys) == {}

    real_preview_import_events = cli.preview_import_events

    def _stray_writing_preview_import_events(db_path, events):
        # the violation: the "preview" appends a real custody event — a write behind a
        # clean report (the no-op axis catches it; the report counts do not)
        if db_path.exists():
            init_db(db_path)
            record_events(
                db_path,
                [CustodyEvent(
                    item_id="arxiv:dba", checked_at="2026-06-26T00:00:00+00:00",
                    status="verified", prior_hash="sha256:dba",
                    observed_hash="sha256:dba",
                )],
            )
        return real_preview_import_events(db_path, events)

    monkeypatch.setattr(
        cli, "preview_import_events", _stray_writing_preview_import_events
    )

    violations = _violating_legs(monkeypatch, tmp_path / "sab", capsys)
    assert set(violations) == {"import bundle"}, violations
    assert "ledger changed" in violations["import bundle"]


def test_a_preview_that_mispredicts_fails_only_its_prediction_leg(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    """Sabotage (the prediction axis): a preview whose predicted disposition diverges
    from the live run. `cli.select_prunable_archive` is the drop-set predictor the
    *archive-prune* report-only preview uses — and the only preview leg that routes
    through it (the live `--apply` run deletes via the unpatched `prune_archive`; no
    other preview touches it). Making it under-count the drop set makes the preview
    predict fewer drops than the live run deletes, failing *only* that leg's prediction
    axis; its no-op axis (the preview still writes nothing) and the other three legs
    stay green."""
    assert _violating_legs(monkeypatch, tmp_path / "base", capsys) == {}

    real_select_prunable_archive = cli.select_prunable_archive

    def _undercounting_select_prunable_archive(db_path, *, before=None, keep=None):
        # the violation: drop one fewer than the policy actually matches, so the
        # preview's `matched`/`by_item`/`remaining` diverge from the live `--apply`
        return real_select_prunable_archive(db_path, before=before, keep=keep)[:-1]

    monkeypatch.setattr(
        cli, "select_prunable_archive", _undercounting_select_prunable_archive
    )

    violations = _violating_legs(monkeypatch, tmp_path / "sab", capsys)
    assert set(violations) == {"archive prune"}, violations
    assert "predicted" in violations["archive prune"]
