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
    agents_dir: Path
    db_path: Path
    config_path: Path
    credentials_path: Path

    @property
    def subdirs(self) -> tuple[Path, ...]:
        return (
            self.items_dir,
            self.scrolls_dir,
            self.library_dir,
            self.media_dir,
            self.agents_dir,
        )


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
        agents_dir=root / "agents",
        db_path=root / "db.sqlite",
        config_path=root / "config.toml",
        # Deliberately not in `subdirs`: the credential store is created on
        # first write, at 0600, and never by `ensure_library`.
        credentials_path=root / "credentials.json",
    )


def validate_artifact_relpath(relpath: str, directory: str) -> None:
    """Reject imported paths that cannot name an owned, portable artifact."""
    if (
        not isinstance(relpath, str)
        or "\\" in relpath
        or "\x00" in relpath
        or len(parts := relpath.split("/")) < 2
        or parts[0] != directory
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise ValueError(f"recorded path must stay inside {directory}/: {relpath!r}")


def artifact_path(paths: LibraryPaths, relpath: str, directory: str) -> Path:
    """Resolve an owned artifact without symlink aliases or tree escapes."""
    validate_artifact_relpath(relpath, directory)
    target = paths.root / relpath
    current = paths.root
    for part in relpath.split("/"):
        current = current / part
        if current.is_symlink():
            raise ValueError(f"recorded artifact path contains a symlink: {relpath!r}")
    if not target.resolve().is_relative_to(paths.root.resolve() / directory):
        raise ValueError(f"recorded path escapes {directory}/: {relpath!r}")
    return target
