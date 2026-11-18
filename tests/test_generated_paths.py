"""Generated views never follow filesystem links outside their owned tree."""
import json

import pytest

from scrolls import mcp_server
from scrolls.cli import main


@pytest.mark.parametrize("relative,command", [
    ("library/index.md", ["kb"]),
    ("library/sources/stale.md", ["kb"]),
    ("library/tags", ["maintain", "--no-recheck"]),
    ("agents/codex/AGENTS.md", ["agent", "install"]),
])
def test_generated_commands_reject_symlinks_without_touching_external_content(
    monkeypatch, tmp_path, capsys, relative, command
):
    root = tmp_path / "library-root"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    assert main(["init"]) == 0
    capsys.readouterr()
    external = tmp_path / "external"
    if relative == "library/tags":
        external.mkdir()
        (external / "secret.md").write_text("External content")
    else:
        external.write_text("External content")
    link = root / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(external, target_is_directory=external.is_dir())
    assert main(command) == 1
    result = capsys.readouterr()
    assert result.out == ""
    assert "symlink" in json.loads(result.err)["error"]
    assert link.is_symlink()
    target = external / "secret.md" if external.is_dir() else external
    assert target.read_text() == "External content"


@pytest.mark.parametrize("tool,relative,argument", [
    (mcp_server.get_concept_page, "concepts/topic.md", "topic"),
    (mcp_server.get_tag_page, "tags/topic.md", "topic"),
])
def test_generated_mcp_pages_reject_symlink_reads(monkeypatch, tmp_path, tool, relative, argument):
    root = tmp_path / "library-root"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    external = tmp_path / "external.md"
    external.write_text("# Tag: topic\nPrivate content")
    link = root / "library" / relative
    link.parent.mkdir(parents=True)
    link.symlink_to(external)
    with pytest.raises(ValueError, match="symlink"):
        tool(argument)
    assert external.read_text() == "# Tag: topic\nPrivate content"
