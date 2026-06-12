"""Tests for agent instruction files (IDEAS.md §10, §14 Pass 5)."""

import json

import pytest

from scrolls.cli import main


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


def run_install(capsys):
    exit_code = main(["agent", "install"])
    assert exit_code == 0
    return json.loads(capsys.readouterr().out)


def test_agent_install_writes_instruction_files(scrolls_home, capsys):
    payload = run_install(capsys)
    assert payload == {
        "root": str(scrolls_home),
        "installed": [
            "agents/claude/SKILL.md",
            "agents/codex/AGENTS.md",
            "agents/hermes/SKILL.md",
        ],
    }
    for relpath in payload["installed"]:
        assert (scrolls_home / relpath).is_file()


def test_agent_install_auto_initializes_the_library(scrolls_home, capsys):
    run_install(capsys)
    assert (scrolls_home / "db.sqlite").is_file()
    assert (scrolls_home / "config.toml").is_file()


def test_skill_files_carry_frontmatter_and_commands(scrolls_home, capsys):
    run_install(capsys)
    for tool in ("claude", "hermes"):
        skill = (scrolls_home / "agents" / tool / "SKILL.md").read_text(encoding="utf-8")
        assert skill.startswith("---\n")
        assert "name: scrolls" in skill
        assert "description:" in skill
        assert "scrolls context" in skill
        assert "scrolls search" in skill
        assert "scrolls show" in skill


def test_codex_file_is_plain_markdown_without_frontmatter(scrolls_home, capsys):
    run_install(capsys)
    agents_md = (scrolls_home / "agents" / "codex" / "AGENTS.md").read_text(encoding="utf-8")
    assert agents_md.startswith("# Scrolls")
    assert "scrolls context" in agents_md


def test_agent_install_regenerates_edited_files(scrolls_home, capsys):
    run_install(capsys)
    skill = scrolls_home / "agents" / "claude" / "SKILL.md"
    skill.write_text("user scribbles\n")

    payload = run_install(capsys)
    assert payload["installed"][0] == "agents/claude/SKILL.md"
    assert "scrolls context" in skill.read_text(encoding="utf-8")
