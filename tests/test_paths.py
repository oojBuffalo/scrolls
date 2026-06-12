"""Tests for library path resolution (IDEAS.md §14 Pass 1).

The library root is `$SCROLLS_HOME` when set, else `~/.scrolls`. Everything
else hangs off the root so agents can discover the layout via `scrolls paths`.
"""

from pathlib import Path

from scrolls.paths import LibraryPaths, get_paths


def test_root_defaults_to_home_dot_scrolls(monkeypatch):
    monkeypatch.delenv("SCROLLS_HOME", raising=False)
    paths = get_paths()
    assert paths.root == Path.home() / ".scrolls"


def test_scrolls_home_env_overrides_root(monkeypatch, tmp_path):
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "lib"))
    paths = get_paths()
    assert paths.root == tmp_path / "lib"


def test_scrolls_home_tilde_is_expanded(monkeypatch):
    monkeypatch.setenv("SCROLLS_HOME", "~/custom-scrolls")
    paths = get_paths()
    assert paths.root == Path.home() / "custom-scrolls"


def test_layout_matches_readme(tmp_path):
    paths = get_paths(root=tmp_path)
    assert paths == LibraryPaths(
        root=tmp_path,
        items_dir=tmp_path / "items",
        scrolls_dir=tmp_path / "scrolls",
        library_dir=tmp_path / "library",
        media_dir=tmp_path / "media",
        agents_dir=tmp_path / "agents",
        db_path=tmp_path / "db.sqlite",
        config_path=tmp_path / "config.toml",
    )
