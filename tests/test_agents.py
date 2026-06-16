"""Tests for agent instruction files (IDEAS.md §10, §14 Pass 5)."""

import json

import pytest

from scrolls.cli import main
from scrolls.generated import GENERATED_END


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
    assert not agents_md.startswith("---")  # no skill frontmatter, unlike SKILL.md
    assert "# Scrolls" in agents_md
    assert "scrolls context" in agents_md


def test_agent_install_regenerates_edited_files(scrolls_home, capsys):
    run_install(capsys)
    skill = scrolls_home / "agents" / "claude" / "SKILL.md"
    skill.write_text("user scribbles\n")

    payload = run_install(capsys)
    assert payload["installed"][0] == "agents/claude/SKILL.md"
    assert "scrolls context" in skill.read_text(encoding="utf-8")


def test_installed_files_carry_the_sentinel_fence(scrolls_home, capsys):
    run_install(capsys)
    for relpath in (
        "agents/claude/SKILL.md",
        "agents/codex/AGENTS.md",
        "agents/hermes/SKILL.md",
    ):
        text = (scrolls_home / relpath).read_text(encoding="utf-8")
        assert "<!-- @generated scrolls" in text
        assert "scrolls agent install" in text  # marker names the regenerator
        assert GENERATED_END in text


def test_agent_install_preserves_annotation_outside_the_fence(scrolls_home, capsys):
    # the M1/ADR 0102 promise extended to agents/: a hand annotation outside the
    # fence survives a reinstall while the generated region refreshes
    run_install(capsys)
    skill = scrolls_home / "agents" / "claude" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    skill.write_text(text + "\n## My project notes\nPrefer the foo library.\n")

    run_install(capsys)
    out = skill.read_text(encoding="utf-8")
    assert "## My project notes" in out  # annotation survived
    assert "Prefer the foo library." in out
    assert out.count("<!-- @generated scrolls") == 1  # generated region refreshed once


def test_skill_frontmatter_stays_at_byte_zero_after_annotation(scrolls_home, capsys):
    run_install(capsys)
    skill = scrolls_home / "agents" / "hermes" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nuser tail\n")

    run_install(capsys)
    out = skill.read_text(encoding="utf-8")
    assert out.startswith("---\n")  # frontmatter must remain first for skill loading
    assert "name: scrolls" in out.split("---", 2)[1]  # still inside the frontmatter
    assert out.rstrip().endswith("user tail")


def test_codex_file_preserves_an_annotation_on_either_side_of_the_fence(scrolls_home, capsys):
    # AGENTS.md has no pinned header, so — like a library/ page — it keeps a note
    # placed *before* the fence too, not only a suffix
    run_install(capsys)
    agents_md = scrolls_home / "agents" / "codex" / "AGENTS.md"
    agents_md.write_text("# Local overrides\nUse staging creds.\n" + agents_md.read_text(encoding="utf-8"))

    run_install(capsys)
    out = agents_md.read_text(encoding="utf-8")
    assert out.startswith("# Local overrides\nUse staging creds.\n")  # prefix survived
    assert "scrolls context" in out  # generated body refreshed
    assert out.count("<!-- @generated scrolls") == 1


def test_reinstall_migrates_a_pre_sentinel_file_wholesale(scrolls_home, capsys):
    # a file installed before ADR 0102 carries no fence; a reinstall finds no
    # region to anchor on and overwrites it, leaving exactly one fenced template
    run_install(capsys)
    skill = scrolls_home / "agents" / "claude" / "SKILL.md"
    skill.write_text(
        "---\nname: scrolls\ndescription: old\n---\n\n# Scrolls\n\nlegacy body\n"
    )

    run_install(capsys)
    out = skill.read_text(encoding="utf-8")
    assert "legacy body" not in out  # the marker-less file was replaced wholesale
    assert out.startswith("---\n")
    assert out.count("<!-- @generated scrolls") == 1
    assert "scrolls context" in out
