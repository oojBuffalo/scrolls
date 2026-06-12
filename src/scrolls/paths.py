"""Library path resolution (IDEAS.md §14 Pass 1, README layout).

The root is `$SCROLLS_HOME` when set, else `~/.scrolls`. All other paths
derive from the root so the whole layout can be relocated for tests or
portable installs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LibraryPaths:
    root: Path
    items_dir: Path
    scrolls_dir: Path
    library_dir: Path
    media_dir: Path
    db_path: Path
    config_path: Path

    @property
    def subdirs(self) -> tuple[Path, ...]:
        return (self.items_dir, self.scrolls_dir, self.library_dir, self.media_dir)


def get_paths(root: Path | None = None) -> LibraryPaths:
    """Resolve the library layout, honoring `$SCROLLS_HOME` when no root is given."""
    if root is None:
        env_root = os.environ.get("SCROLLS_HOME")
        root = Path(env_root).expanduser() if env_root else Path.home() / ".scrolls"
    return LibraryPaths(
        root=root,
        items_dir=root / "items",
        scrolls_dir=root / "scrolls",
        library_dir=root / "library",
        media_dir=root / "media",
        db_path=root / "db.sqlite",
        config_path=root / "config.toml",
    )
