"""The bundle's media sidecar (ADR 0115, issue #12).

A Markdown bundle (ADR 0103) carries text and custody state losslessly, but
media only as references a fresh library must re-fetch — and whatever rotted
upstream since is gone. The sidecar is the opt-in carry leg for the files
themselves: a directory beside the bundle holding the in-scope items' captured
files at their library-relative paths, plus a manifest.

```text
ml.md                 # the bundle, byte-identical with or without a sidecar
ml.media/
  MANIFEST.jsonl      # {path, sha256, bytes, item_id}, one line per file
  media/<source>/...  # the files, at the paths their refs record
```

Import adopts a file only where a held row's media ref records that path, so a
file always lands where the library already expects it. Every file is checked
against its manifest hash on the way in, and a file the library already holds
is never overwritten — the bundle importer's INSERT OR IGNORE, applied to bytes.
Paths are checked as the filesystem resolves them, not only as written: a
symlink cannot carry a write outside the library's `media/`, nor pull a file in
from outside the sidecar.

The manifest is validated before anything lands: a malformed line, or a path
outside `media/`, fails the whole import naming the line (a backup that lies
about where a file goes is corrupt, not partially usable). A bad *file* — a
hash mismatch, or one missing from the sidecar — is rejected alone and named,
and the rest still land.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from scrolls.items import ScrollItem
from scrolls.paths import LibraryPaths

MANIFEST_NAME = "MANIFEST.jsonl"
SIDECAR_SUFFIX = ".media"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHUNK = 1 << 20


class SidecarError(Exception):
    """The sidecar is missing, unwritable, or its manifest is corrupt."""


@dataclass(frozen=True)
class ManifestEntry:
    """One file the sidecar carries."""

    path: str
    sha256: str
    bytes: int
    item_id: str


def sidecar_beside(bundle_path: Path) -> Path:
    """Where a bundle's sidecar sits by convention: `ml.md` → `ml.media/`."""
    return bundle_path.with_suffix(SIDECAR_SUFFIX)


def empty_report() -> dict[str, Any]:
    """The import's media block when no sidecar travelled — checked, nothing."""
    return {"sidecar": None, "adopted": 0, "already_held": 0, "unattached": [], "rejected": []}


def export_media(
    paths: LibraryPaths, items: Iterable[ScrollItem], dest: Path
) -> dict[str, Any]:
    """Copy the items' held media files into a new sidecar at `dest`.

    Args:
        paths: The library the files are held in.
        items: The bundle's in-scope items — exactly the custody block's rows.
        dest: The sidecar directory; created, and refused unless empty.

    Returns:
        The export summary: `sidecar`, `files`, `bytes`, `missing` (refs whose
        recorded file is gone from disk, named rather than silently dropped),
        `outside` (refs whose file resolves outside the library's `media/` —
        a symlink to somewhere else — named and never shipped, since the
        sidecar is made to be shared), and `uncaptured` (refs that travel as
        references only — never captured, or declined on size).

    Raises:
        SidecarError: `dest` is a file or a non-empty directory.
    """
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise SidecarError(f"--with-media destination is not empty: {dest}")
    held: dict[str, tuple[str, Path]] = {}
    missing: set[str] = set()
    outside: set[str] = set()
    media_root = paths.root / "media"
    uncaptured = 0
    for item in items:
        for ref in item.media:
            if not isinstance(ref, dict):
                continue
            relpath = ref.get("path")
            if not relpath:
                uncaptured += 1 if ref.get("url") else 0
                continue
            source = paths.root / relpath
            if not _is_safe(relpath) or not source.is_file():
                missing.add(relpath)
                continue
            try:
                inside = _resolves_within(source, media_root)
            except (OSError, RuntimeError):  # unresolvable, e.g. a symlink loop
                inside = False
            if inside:
                held.setdefault(relpath, (item.id, source))
            else:
                outside.add(relpath)
    dest.mkdir(parents=True, exist_ok=True)
    lines, total = [], 0
    for relpath in sorted(held):
        item_id, source = held[relpath]
        target = dest / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            digest, size = _copy_into(source, handle)
        lines.append({"path": relpath, "sha256": digest, "bytes": size, "item_id": item_id})
        total += size
    (dest / MANIFEST_NAME).write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )
    return {
        "sidecar": str(dest),
        "files": len(lines),
        "bytes": total,
        "missing": sorted(missing),
        "outside": sorted(outside),
        "uncaptured": uncaptured,
    }


def load_manifest(sidecar: Path) -> list[ManifestEntry]:
    """Read and validate a sidecar's manifest.

    Raises:
        SidecarError: The manifest is missing or undecodable, or a line is not
            a well-formed entry with a safe `media/` path, or repeats a path —
            named by line number.
    """
    manifest = sidecar / MANIFEST_NAME
    try:
        text = manifest.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SidecarError(f"no readable {MANIFEST_NAME} in {sidecar}: {exc}") from exc
    entries = []
    seen: dict[str, int] = {}  # path -> the line that first named it
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = _entry(json.loads(line))
        except (json.JSONDecodeError, ValueError) as exc:
            raise SidecarError(f"{MANIFEST_NAME} line {number}: {exc}") from exc
        if entry.path in seen:  # an export never repeats a path
            raise SidecarError(
                f"{MANIFEST_NAME} line {number}: {entry.path} repeats line {seen[entry.path]}"
            )
        seen[entry.path] = number
        entries.append(entry)
    return entries


def adopt_media(
    paths: LibraryPaths,
    entries: Iterable[ManifestEntry],
    sidecar: Path,
    held_row: Callable[[str], ScrollItem | None],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Bring the sidecar's files into the library, hash-checked, never overwriting.

    Args:
        paths: The receiving library.
        entries: The validated manifest.
        sidecar: The sidecar directory the entries are relative to.
        held_row: The row each file attaches to, by item id — the library's row
            after the import, or the one a dry run predicts.
        dry_run: Check every file but write nothing, so a preview reports what
            the import would.

    Returns:
        The import's media block: `sidecar`, `adopted`, `already_held`,
        `unattached` (files no held ref points at) and `rejected` (`{path,
        reason}` for a hash mismatch, a file missing from the sidecar, a path
        that resolves outside its root, or an I/O failure — each file on its
        own, so one bad file never stops the rest).
    """
    report = {**empty_report(), "sidecar": str(sidecar)}
    media_root = paths.root / "media"
    for entry in entries:
        row = held_row(entry.item_id)
        recorded = {ref.get("path") for ref in row.media if isinstance(ref, dict)} if row else set()
        if entry.path not in recorded:
            report["unattached"].append(entry.path)
            continue
        target = paths.root / entry.path
        try:
            if target.exists() or target.is_symlink():  # never touch what is held
                outcome = _held_outcome(target)
            else:
                outcome = _adopt_one(sidecar / entry.path, sidecar, target, media_root,
                                     entry.sha256, dry_run=dry_run)
        except (OSError, RuntimeError) as exc:  # RuntimeError: a symlink loop, pre-3.13
            outcome = f"cannot copy: {exc}"
        if outcome == _ADOPTED:
            report["adopted"] += 1
        elif outcome == _HELD:  # held already, or landed by another writer meanwhile
            report["already_held"] += 1
        else:
            report["rejected"].append({"path": entry.path, "reason": outcome})
    return report


_ADOPTED = "adopted"
_HELD = "already_held"
_NOT_A_FILE = "held path is not a regular file"
# Short and fixed, so a held name near the filesystem's 255-byte limit still
# leaves room for the temporary file it is copied through.
_TEMP_PREFIX, _TEMP_SUFFIX = ".scrolls-", ".incoming"


def _held_outcome(target: Path) -> str:
    """Something already sits at `target`: held if it is a usable file.

    A directory or a dangling symlink there is left exactly as it is, but it is
    no held copy of the file, so the entry is rejected rather than counted.
    """
    return _HELD if target.is_file() else _NOT_A_FILE


def _adopt_one(
    source: Path,
    sidecar: Path,
    target: Path,
    media_root: Path,
    expected: str,
    *,
    dry_run: bool,
) -> str:
    """Bring one file in: `_ADOPTED`, `_HELD`, or why it was rejected."""
    if not _resolves_within(source, sidecar):
        return "outside the sidecar"
    if not source.is_file():
        return "missing from the sidecar"
    if not _lands_within(target, media_root):
        return "outside the library's media directory"
    if dry_run:
        return _ADOPTED if _verify(source, expected) else "sha256 mismatch"
    target.parent.mkdir(parents=True, exist_ok=True)
    return _adopt(source, target, expected)


def _entry(raw: Any) -> ManifestEntry:
    if not isinstance(raw, dict):
        raise ValueError("not a JSON object")
    path, digest, size, item_id = (raw.get(k) for k in ("path", "sha256", "bytes", "item_id"))
    if not isinstance(path, str) or not _is_safe(path):
        raise ValueError(f"unsafe or missing path {path!r} (must lie under media/)")
    if not isinstance(digest, str) or not _SHA256.match(digest):
        raise ValueError(f"sha256 must be 64 lowercase hex digits, got {digest!r}")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError(f"bytes must be a non-negative integer, got {size!r}")
    if not isinstance(item_id, str) or not item_id:
        raise ValueError("missing item_id")
    return ManifestEntry(path=path, sha256=digest, bytes=size, item_id=item_id)


def _is_safe(relpath: str) -> bool:
    """A library-relative path under `media/` that cannot climb out of it."""
    if "\\" in relpath or "\x00" in relpath:
        return False
    parts = PurePosixPath(relpath).parts
    return (
        len(parts) >= 2
        and parts[0] == "media"
        and not PurePosixPath(relpath).is_absolute()
        and ".." not in parts
    )


def _resolves_within(path: Path, root: Path) -> bool:
    """True when `path`, symlinks followed, lies inside `root`.

    Raises:
        OSError, RuntimeError: The path cannot be resolved — a symlink loop is
            a RuntimeError before Python 3.13 and an OSError after.
    """
    return path.resolve().is_relative_to(root.resolve())


def _lands_within(target: Path, media_root: Path) -> bool:
    """True when writing `target` cannot be redirected outside `media_root`.

    Checks the nearest ancestor that exists, as the filesystem resolves it:
    a symlinked directory under `media/` pointing elsewhere fails here, before
    any directory or file is created. When `media/` itself does not exist yet,
    no link under it can redirect the write.
    """
    if not media_root.exists():
        return not media_root.is_symlink()
    probe = target.parent
    while not probe.exists():
        probe = probe.parent
    return probe.resolve().is_relative_to(media_root.resolve())


def _copy_into(source: Path, handle: Any) -> tuple[str, int]:
    """Stream `source` into an open binary `handle`; return (sha256 hex, size)."""
    digest, size = hashlib.sha256(), 0
    with source.open("rb") as src:
        while chunk := src.read(_CHUNK):
            digest.update(chunk)
            handle.write(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _verify(source: Path, expected: str) -> bool:
    digest = hashlib.sha256()
    with source.open("rb") as src:
        while chunk := src.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest() == expected


def _adopt(source: Path, target: Path, expected: str) -> str:
    """Copy through a fresh temporary file; publish it only if the hash matches.

    The temporary file is created exclusively under a unique name, so no file
    already in the directory — whatever it is called — is ever opened for
    writing or cleaned up; only the file this call created is removed. It is
    published with a hard link, which refuses an existing name: a file another
    writer landed while this one copied is kept, and counted as held.

    Returns:
        `_ADOPTED`, `_HELD`, `_NOT_A_FILE`, or `"sha256 mismatch"`.
    """
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=_TEMP_PREFIX, suffix=_TEMP_SUFFIX)
    partial = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            digest, _ = _copy_into(source, handle)
        if digest != expected:
            return "sha256 mismatch"
        try:
            os.link(partial, target)
        except FileExistsError:
            return _held_outcome(target)
        return _ADOPTED
    finally:
        partial.unlink(missing_ok=True)
