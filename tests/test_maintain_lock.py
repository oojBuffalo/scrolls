"""Tests for the maintenance run lock (roadmap H443, ADR 0117).

A scheduled `scrolls maintain` pass that overruns its interval, or a manual
pass started during a scheduled one, must not run beside it: two passes
would recheck the same items, append to the same ledger, and write the same
trend baseline at once. The lock makes a second pass **skip, not overlap**,
the way the hourly worker's launcher already behaves. It is an OS file lock,
so a holder that dies releases it with no stale-lock cleanup.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

import scrolls.mcp_server as mcp_server
from scrolls.cli import main
from scrolls.maintain import (
    EXIT_ALREADY_RUNNING,
    MaintenanceBusy,
    lock_path,
    log_path,
    maintenance_lock,
    snapshot_path,
)
from scrolls.paths import get_paths

STARTED = "2026-10-29T12:00:00+00:00"


@pytest.fixture
def home(monkeypatch, tmp_path):
    """An initialized library under a temp root; never touches ~/.scrolls."""
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "scrolls-home"))
    assert main(["init"]) == 0
    return get_paths()


def test_a_second_holder_is_refused_and_told_who_holds_it(home):
    with maintenance_lock(home, now=STARTED):
        with pytest.raises(MaintenanceBusy) as busy:
            with maintenance_lock(home, now="2026-10-29T12:05:00+00:00"):
                pass
    holder = busy.value.holder
    assert holder["started_at"] == STARTED
    assert isinstance(holder["pid"], int)


def test_the_lock_is_released_when_the_pass_ends(home):
    with maintenance_lock(home, now=STARTED):
        pass
    with maintenance_lock(home, now=STARTED):
        pass


def test_the_lock_is_released_when_the_pass_fails(home):
    with pytest.raises(RuntimeError, match="boom"):
        with maintenance_lock(home, now=STARTED):
            raise RuntimeError("boom")
    with maintenance_lock(home, now=STARTED):
        pass


def test_a_dead_holders_lock_is_reclaimed(home):
    # A pass killed mid-run leaves its lock file behind; the OS lock died with
    # the process, so the next scheduled pass runs instead of wedging.
    script = (
        "import os, sys\n"
        "from scrolls.maintain import maintenance_lock\n"
        "from scrolls.paths import get_paths\n"
        "with maintenance_lock(get_paths(), now='2026-10-29T11:00:00+00:00'):\n"
        "    os._exit(9)\n"
    )
    done = subprocess.run([sys.executable, "-c", script], check=False)
    assert done.returncode == 9
    assert lock_path(home).exists()  # the file outlives its holder

    with maintenance_lock(home, now=STARTED):
        pass
    assert json.loads(lock_path(home).read_text())["started_at"] == STARTED


def test_cli_maintain_skips_while_another_pass_runs(home, capsys):
    capsys.readouterr()
    with maintenance_lock(home, now=STARTED):
        code = main(["maintain", "--no-recheck"])
    captured = capsys.readouterr()

    assert code == EXIT_ALREADY_RUNNING == 75
    assert captured.out == ""
    envelope = json.loads(captured.err)
    assert envelope["reason"] == "already_running"
    assert envelope["holder"]["started_at"] == STARTED
    assert "already running" in envelope["error"]
    # nothing recorded: the skipped pass wrote no baseline and no log entry
    assert not snapshot_path(home).exists()
    assert not log_path(home).exists()

    # once the holder finishes, the next pass runs and records normally
    assert main(["maintain", "--no-recheck"]) == 0
    assert snapshot_path(home).exists()


def test_cli_scoped_pass_also_waits_its_turn(home, capsys):
    capsys.readouterr()
    with maintenance_lock(home, now=STARTED):
        code = main(["maintain", "--no-recheck", "--source", "web"])
    assert code == EXIT_ALREADY_RUNNING
    assert json.loads(capsys.readouterr().err)["reason"] == "already_running"


def test_reading_the_history_never_takes_the_lock(home, capsys):
    capsys.readouterr()
    with maintenance_lock(home, now=STARTED):
        assert main(["maintain", "--history"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_mcp_run_maintenance_refuses_while_another_pass_runs(home):
    with maintenance_lock(home, now=STARTED):
        with pytest.raises(MaintenanceBusy, match="already running"):
            mcp_server.run_maintenance()
    assert not snapshot_path(home).exists()
    assert mcp_server.run_maintenance()["issues"] == 0
