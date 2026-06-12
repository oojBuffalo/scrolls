"""Media capture: download items' media refs into the library (ADR 0011).

Adapters record media as `{"type", "url"}` dicts (youtube thumbnails,
arXiv PDFs, x photos) but fetch only stores the reference. Capture
downloads each ref to `media/<source>/<id-slug>-<n><ext>` and writes the
root-relative location back onto the ref as `path` — the same
root-relative convention as `markdown_path` — so scrolls and the index
point at local files. A recorded `path` is reused on re-capture, keeping
file locations stable. SQLite stays canonical: files can always be
re-downloaded from the recorded URLs.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

from scrolls.items import ScrollItem
from scrolls.paths import LibraryPaths
from scrolls.render import slugify
from scrolls.sources import http

# patchable seam, mirroring the source adapters: tests never touch the network
_get_bytes = http.get_bytes

# extension fallback when the URL path has none (pbs.twimg.com puts the
# format in the query; arXiv PDF links have no suffix at all)
_TYPE_EXTENSIONS = {
    "pdf": ".pdf",
    "photo": ".jpg",
    "thumbnail": ".jpg",
    "video": ".mp4",
}
_DEFAULT_EXTENSION = ".bin"
# short, and at least one letter: ".jpg" yes, arXiv's version tail ".03762" no
_SAFE_SUFFIX = re.compile(r"^\.(?=[^.]*[A-Za-z])[A-Za-z0-9]{1,5}$")


def capture_media(
    paths: LibraryPaths, item: ScrollItem, force: bool = False
) -> tuple[ScrollItem, list[dict[str, Any]]]:
    """Download the item's media refs; return (updated item, per-ref results).

    Each result is `{"url", "status": "captured"|"skipped"|"failed"}` plus
    `path` when captured/skipped or `error` when failed. Refs already on
    disk are skipped unless `force`; refs without a `url` (including
    legacy non-dict refs) are skipped; one failed download never stops
    the others, and refs captured before a failure keep their paths.
    """
    refs = [dict(ref) if isinstance(ref, dict) else ref for ref in item.media]
    results: list[dict[str, Any]] = []
    changed = False
    for index, ref in enumerate(refs, start=1):
        url = ref.get("url") if isinstance(ref, dict) else None
        if not url:
            results.append({"url": None, "status": "skipped"})
            continue
        relpath = ref.get("path") or _media_relpath(paths, item, index, ref)
        target = paths.root / relpath
        if not force and ref.get("path") and target.exists():
            results.append({"url": url, "status": "skipped", "path": relpath})
            continue
        try:
            payload = _get_bytes(url)
        except (OSError, ValueError) as exc:  # URLError is an OSError
            results.append({"url": url, "status": "failed", "error": str(exc)})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        if ref.get("path") != relpath:
            ref["path"] = relpath
            changed = True
        results.append({"url": url, "status": "captured", "path": relpath})
    updated = replace(item, media=tuple(refs)) if changed else item
    return updated, results


def has_pending_media(paths: LibraryPaths, item: ScrollItem) -> bool:
    """True if any media ref has a URL but no captured file on disk."""
    for ref in item.media:
        if not isinstance(ref, dict) or not ref.get("url"):
            continue
        relpath = ref.get("path")
        if not relpath or not (paths.root / relpath).exists():
            return True
    return False


def _media_relpath(
    paths: LibraryPaths, item: ScrollItem, index: int, ref: dict[str, Any]
) -> str:
    """`media/<source>/<id-slug>-<n><ext>`, root-relative and deterministic."""
    local_id = item.id.split(":", 1)[1] if ":" in item.id else item.id
    slug = slugify(local_id) or "item"
    name = f"{slug}-{index}{_extension(ref)}"
    return str((paths.media_dir / item.source / name).relative_to(paths.root))


def _extension(ref: dict[str, Any]) -> str:
    suffix = PurePosixPath(urlparse(ref.get("url", "")).path).suffix
    if _SAFE_SUFFIX.match(suffix):
        return suffix.lower()
    return _TYPE_EXTENSIONS.get(ref.get("type"), _DEFAULT_EXTENSION)
