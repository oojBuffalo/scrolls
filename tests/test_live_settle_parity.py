"""H422 — live-act settle parity for preview-capable writes.

The twenty-ninth **contract-consolidation** cell and the *settle* sibling of H416's
preview-never-drifts contract. H416 proves a preview touches nothing and predicts the
first live run; this proves the live run itself reaches a stable state: running the
same preview-capable act a second time is a durable no-op and reports the settled
disposition.

The matrix is intentionally keyed to H416's `_PREVIEW_ACTS` registry, so a new write
command that gains a preview mode automatically inherits this settle assertion. The
non-preview write commands are carried through from H416's `_NO_PREVIEW` set as named
out-of-scope acts for this preview-settle axis.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime as _real_datetime
from datetime import timedelta, timezone

import pytest

import scrolls.cli as cli
from scrolls.cli import main
from scrolls.items import get_item, item_to_dict
from scrolls.paths import get_paths

from test_cli_determinism import _CLI_WRITE_COMMANDS, _key  # noqa: E402
from test_preview_parity import (  # noqa: E402
    _NO_PREVIEW,
    _PREVIEW_ACTS,
    _durable_state,
    _noop_reason,
    _seed,
)


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


class _TickingDateTime:
    """A deterministic clock whose seconds advance every time the CLI asks for now.

    H422 must not be masked by two live runs landing in the same wall-clock second:
    repeated import conflicts would otherwise have equal `_EVENT_IDENTITY` timestamps.
    """

    tick = 0
    base = _real_datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        value = cls.base + timedelta(seconds=cls.tick)
        cls.tick += 1
        return value if tz is None else value.astimezone(tz)


def _install_ticking_clock(monkeypatch):
    _TickingDateTime.tick = 0
    monkeypatch.setattr(cli, "datetime", _TickingDateTime)


def _ok(condition: bool, reason: str) -> str | None:
    return None if condition else reason


def _import_bundle_first(report: dict) -> str | None:
    return _ok(
        report["imported"] == 1 and report["conflict"] == 1,
        f"first import bundle was vacuous: {report}",
    )


def _import_bundle_settled(report: dict) -> str | None:
    return _ok(
        report["imported"] == 0
        and report["skipped"] == report["items"]
        and report["events"]["imported"] == 0
        and report["archive"]["imported"] == 0,
        f"second import bundle did not settle as all-skipped/imported=0: {report}",
    )


def _reconcile_first(report: dict) -> str | None:
    return _ok(
        report["resolved"] is True,
        f"first reconcile did not resolve the open conflict: {report}",
    )


def _reconcile_settled(report: dict) -> str | None:
    return _ok(
        report["resolved"] is False
        and report.get("reason") == "no unresolved import conflict"
        and report["dry_run"] is False,
        f"second reconcile did not report the settled no-conflict shape: {report}",
    )


def _archive_restore_first(report: dict) -> str | None:
    return _ok(
        report["restored"] is True
        and report["outcome"] == "adopted"
        and report["prior_hash"] == "sha256:tampered",
        f"first archive restore did not adopt the selected prior: {report}",
    )


def _archive_restore_settled(report: dict) -> str | None:
    return _ok(
        report["restored"] is False
        and report["outcome"] == "unchanged"
        and report["prior_hash"] == "sha256:tampered"
        and report["dry_run"] is False,
        f"second archive restore did not report unchanged: {report}",
    )


def _archive_prune_first(report: dict) -> str | None:
    return _ok(
        report["applied"] is True and report["matched"] == report["dropped"] == 1,
        f"first archive prune did not drop the seeded prior: {report}",
    )


def _archive_prune_settled(report: dict) -> str | None:
    return _ok(
        report["applied"] is True
        and report["matched"] == report["dropped"] == report["remaining"] == 0
        and report["by_item"] == []
        and report["archived"] == [],
        f"second archive prune did not report a 0-drop settled shape: {report}",
    )


# H416's archive-restore leg uses the default-latest selector to prove preview parity.
# For the settle axis we drive the stable version-specific form: the same `--hash`
# selector run twice must be adopted then unchanged. A bare default-latest restore is
# the reversible "undo the latest adoption" affordance, so repeating it intentionally
# points at the just-displaced copy rather than at the same version.
_SETTLE_ACTS = {
    ("import", "bundle"): {
        "setup": _PREVIEW_ACTS[("import", "bundle")]["setup"],
        "live_argv": _PREVIEW_ACTS[("import", "bundle")]["live_argv"],
        "first": _import_bundle_first,
        "settled": _import_bundle_settled,
    },
    ("reconcile",): {
        "setup": _PREVIEW_ACTS[("reconcile",)]["setup"],
        "live_argv": _PREVIEW_ACTS[("reconcile",)]["live_argv"],
        "first": _reconcile_first,
        "settled": _reconcile_settled,
    },
    ("archive", "restore"): {
        "setup": _PREVIEW_ACTS[("archive", "restore")]["setup"],
        "live_argv": lambda w: [
            "archive", "restore", "web:archived", "--hash", "sha256:tampered"
        ],
        "first": _archive_restore_first,
        "settled": _archive_restore_settled,
    },
    ("archive", "prune"): {
        "setup": _PREVIEW_ACTS[("archive", "prune")]["setup"],
        "live_argv": _PREVIEW_ACTS[("archive", "prune")]["live_argv"],
        "first": _archive_prune_first,
        "settled": _archive_prune_settled,
    },
}


def test_live_settle_registry_reuses_the_preview_registry():
    """The completeness keystone: every preview act from H416 has a live-settle leg,
    and H416's named no-preview commands remain outside this preview-settle axis.
    """
    settle = set(_SETTLE_ACTS)
    no_preview = set(_NO_PREVIEW)

    assert settle == set(_PREVIEW_ACTS)
    assert settle.isdisjoint(no_preview)
    assert settle | no_preview == set(_CLI_WRITE_COMMANDS)
    assert len(settle) + len(no_preview) == len(_CLI_WRITE_COMMANDS)
    assert all(_NO_PREVIEW[key] for key in no_preview)


def _run_json(argv, capsys) -> dict:
    capsys.readouterr()
    assert main(argv) == 0
    return json.loads(capsys.readouterr().out)


def _run_settle_leg(monkeypatch, tmp_path, key, spec, capsys) -> str | None:
    safe = _key(key).replace(" ", "-")
    work = tmp_path / f"{safe}-work"
    work.mkdir(parents=True)
    spec["setup"](work)

    _seed(monkeypatch, tmp_path / f"{safe}-home")
    paths = get_paths()

    before_first = _durable_state(paths)
    first_report = _run_json(spec["live_argv"](work), capsys)
    after_first = _durable_state(paths)
    if before_first == after_first:
        return "first live run was a durable no-op; settle assertion would be vacuous"
    reason = spec["first"](first_report)
    if reason is not None:
        return reason

    before_second = _durable_state(paths)
    second_report = _run_json(spec["live_argv"](work), capsys)
    after_second = _durable_state(paths)
    return _noop_reason(before_second, after_second) or spec["settled"](second_report)


def _settle_violations(monkeypatch, tmp_path, capsys) -> dict[str, str]:
    violations = {}
    for key, spec in _SETTLE_ACTS.items():
        reason = _run_settle_leg(monkeypatch, tmp_path, key, spec, capsys)
        if reason is not None:
            violations[_key(key)] = reason
    return violations


def test_every_preview_live_act_settles_on_the_second_run(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    """Over H416's wide fixture, every preview-capable live act mutates on the first
    run, then the second run is byte-identical on ledger/raw/row-count durable axes
    and emits its settled report shape.
    """
    _install_ticking_clock(monkeypatch)
    assert _settle_violations(monkeypatch, tmp_path / "matrix", capsys) == {}


def test_a_non_settling_prune_fails_only_the_archive_prune_leg(
    scrolls_home, monkeypatch, tmp_path, capsys
):
    """Sabotage: the second ``archive prune --apply`` performs a hidden archive-row
    write after the policy has already settled. The matrix should fail only the prune
    leg, and on the row-count durable axis.
    """
    _install_ticking_clock(monkeypatch)
    assert _settle_violations(monkeypatch, tmp_path / "base", capsys) == {}

    real_prune_archive = cli.prune_archive

    def _non_settling_prune_archive(db_path, *, before=None, keep=None):
        dropped = real_prune_archive(db_path, before=before, keep=keep)
        if not dropped:
            item = get_item(db_path, "web:archived")
            assert item is not None
            conn = sqlite3.connect(db_path)
            try:
                with conn:
                    conn.execute(
                        "INSERT INTO item_archive "
                        "(item_id, archived_at, prior_hash, superseded_by, snapshot) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            item.id,
                            "2026-07-01T00:00:59+00:00",
                            item.content_hash,
                            item.content_hash,
                            json.dumps(item_to_dict(item)),
                        ),
                    )
            finally:
                conn.close()
        return dropped

    monkeypatch.setattr(cli, "prune_archive", _non_settling_prune_archive)

    violations = _settle_violations(monkeypatch, tmp_path / "sab", capsys)
    assert set(violations) == {"archive prune"}, violations
    assert "row counts changed" in violations["archive prune"]
