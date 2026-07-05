"""H423 — archive-selector recovery convergence.

The thirtieth **contract-consolidation** cell and the selector-axis sibling of the
archive recovery reads: the re-importable `archive show` artifact, the decide-before-
you-restore `archive diff` read, and the `archive restore --dry-run` preview must all
select the exact same archived prior for every selector form (`--hash`, `--at`, and
implicit latest).
"""

from __future__ import annotations

import ast
import argparse
import inspect
import json
import textwrap

import pytest

import scrolls.cli as cli
from scrolls.cli import build_parser, main
from scrolls.items import (
    get_item,
    item_to_dict,
    list_archived,
    select_archived_snapshot,
)
from scrolls.paths import get_paths

from test_cli import _seed_archived_chain_at  # noqa: E402


_SELECTOR_FORMS = {
    "latest": {
        "argv": [],
        "expected_hash": "sha256:m2",
        "expected_archived_at": "2026-06-24T00:00:00+00:00",
    },
    "hash": {
        "argv": ["--hash", "sha256:abc"],
        "expected_hash": "sha256:abc",
        "expected_archived_at": "2026-06-22T00:00:00+00:00",
    },
    "at": {
        # exact-boundary inclusive: an exclusive implementation would fall back to abc
        "argv": ["--at", "2026-06-23T00:00:00+00:00"],
        "expected_hash": "sha256:m1",
        "expected_archived_at": "2026-06-23T00:00:00+00:00",
    },
}
_SELECTOR_SURFACES = {"show", "diff", "restore"}
_ARCHIVE_NO_SELECTOR = {
    "list": "archive index/browse surface, not a per-version snapshot selector",
    "prune": "retention-policy write over archive rows, not a recovery read",
}


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


def _archive_leaf_option_strings() -> dict[str, set[str]]:
    parser = build_parser()
    root_sub = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    archive = root_sub.choices["archive"]
    archive_sub = next(
        a for a in archive._actions if isinstance(a, argparse._SubParsersAction)
    )
    return {
        name: {opt for action in sub._actions for opt in action.option_strings}
        for name, sub in archive_sub.choices.items()
    }


def _calls(function, target: str) -> bool:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == target
        for node in ast.walk(tree)
    )


def test_selector_registry_matches_the_live_archive_recovery_surface():
    """The completeness keystone: only the three recovery surfaces expose version
    selectors, they all expose the whole selector vocabulary, and they all route their
    selection through one shared helper that folds `select_archived_snapshot`.
    """
    options = _archive_leaf_option_strings()
    assert _SELECTOR_SURFACES | set(_ARCHIVE_NO_SELECTOR) == set(options)
    assert _SELECTOR_SURFACES.isdisjoint(_ARCHIVE_NO_SELECTOR)
    assert set(_SELECTOR_FORMS) == {"latest", "hash", "at"}

    for surface in _SELECTOR_SURFACES:
        assert "--hash" in options[surface]
        assert "--at" in options[surface]
    assert "--all" in options["show"]  # full-history sibling, not a selector form
    for surface, reason in _ARCHIVE_NO_SELECTOR.items():
        assert "--hash" not in options[surface] and "--at" not in options[surface], reason

    for function in (cli._cmd_archive_show, cli._cmd_archive_diff, cli._cmd_archive_restore):
        assert _calls(function, "_select_archive_prior")
    assert _calls(cli._select_archive_prior, "select_archived_snapshot")


def _seed_selector_history(scrolls_home) -> str:
    return _seed_archived_chain_at(scrolls_home, [
        ("sha256:m1", "2026-06-22T00:00:00+00:00"),
        ("sha256:m2", "2026-06-23T00:00:00+00:00"),
        ("sha256:m3", "2026-06-24T00:00:00+00:00"),
    ])


def _run_show(item_id: str, argv: list[str], capsys) -> dict:
    capsys.readouterr()
    assert main(["archive", "show", item_id, *argv]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    lines = out.splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    return {
        "prior_hash": payload["content_hash"],
        "archived_at": None,
        "snapshot": payload,
    }


def _run_diff(item_id: str, argv: list[str], capsys) -> dict:
    capsys.readouterr()
    assert main(["archive", "diff", item_id, *argv]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    report = json.loads(out)
    return {
        "prior_hash": report["prior_hash"],
        "archived_at": report["archived_at"],
        "would_restore": report["would_restore"],
    }


def _run_restore_dry_run(item_id: str, argv: list[str], capsys) -> dict:
    capsys.readouterr()
    assert main(["archive", "restore", item_id, *argv, "--dry-run"]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    report = json.loads(out)
    return {
        "prior_hash": report["prior_hash"],
        "archived_at": report["archived_at"],
        "restored": report["restored"],
    }


def _selector_violations(scrolls_home, capsys) -> dict[str, str]:
    item_id = _seed_selector_history(scrolls_home)
    db = get_paths().db_path
    held_before = get_item(db, item_id)
    archive_before = list_archived(db, item_id)
    violations: dict[str, str] = {}

    for name, spec in _SELECTOR_FORMS.items():
        argv = spec["argv"]
        show = _run_show(item_id, argv, capsys)
        diff = _run_diff(item_id, argv, capsys)
        restore = _run_restore_dry_run(item_id, argv, capsys)

        selected = select_archived_snapshot(
            db,
            item_id,
            prior_hash=argv[1] if argv[:1] == ["--hash"] else None,
            at=argv[1] if argv[:1] == ["--at"] else None,
        )
        assert selected is not None
        entry, prior = selected
        expected = (entry.prior_hash, entry.archived_at)
        observed = {
            "show": (show["prior_hash"], entry.archived_at),
            "diff": (diff["prior_hash"], diff["archived_at"]),
            "restore": (restore["prior_hash"], restore["archived_at"]),
        }
        if expected != (spec["expected_hash"], spec["expected_archived_at"]):
            violations[name] = f"canonical selector drifted: {expected} != {spec}"
            continue
        mismatched = {surface: value for surface, value in observed.items() if value != expected}
        if mismatched:
            violations[name] = f"expected {expected}, mismatched {mismatched}"
            continue
        if show["snapshot"] != json.loads(json.dumps(item_to_dict(prior))):
            violations[name] = "archive show did not emit the selected prior snapshot"
            continue
        if diff["would_restore"] is not True or restore["restored"] is not True:
            violations[name] = "diff/restore did not agree this prior would restore"

    assert get_item(db, item_id) == held_before
    assert list_archived(db, item_id) == archive_before
    return violations


def test_archive_show_diff_and_restore_dry_run_select_the_same_prior(
    scrolls_home, capsys
):
    """For every selector form, `archive show`, `archive diff`, and
    `archive restore --dry-run` agree on the exact archived prior. The `--at` leg uses
    an exact boundary so inclusive/exclusive drift is visible.
    """
    assert _selector_violations(scrolls_home, capsys) == {}


def test_an_exclusive_at_diff_fails_only_the_at_selector(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    """Sabotage: only `archive diff --at` resolves the boundary exclusively. Hash and
    latest stay green; the at-form leg catches the selector-surface split.
    """
    assert _selector_violations(scrolls_home, capsys) == {}

    original = cli._cmd_archive_diff

    def _exclusive_at_diff(ref, *, prior_hash=None, at=None):
        if at == "2026-06-23T00:00:00+00:00":
            return original(ref, prior_hash=prior_hash, at="2026-06-22T23:59:59+00:00")
        return original(ref, prior_hash=prior_hash, at=at)

    monkeypatch.setattr(cli, "_cmd_archive_diff", _exclusive_at_diff)
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "sabotage-home"))

    violations = _selector_violations(tmp_path / "sabotage-home", capsys)
    assert set(violations) == {"at"}, violations
    assert "diff" in violations["at"]
