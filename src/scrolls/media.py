"""Media capture: download items' media refs into the library (ADR 0011).

Adapters record media as `{"type", "url"}` dicts (youtube thumbnails,
arXiv PDFs, x photos) but fetch only stores the reference. Capture
downloads each ref to `media/<source>/<id-slug>-<n><ext>` and writes the
root-relative location back onto the ref as `path` — the same
root-relative convention as `markdown_path` — so scrolls and the index
point at local files. A recorded `path` is reused on re-capture, keeping
file locations stable. SQLite stays canonical: files can always be
re-downloaded from the recorded URLs.

A captured PDF is also *read*: its text goes onto the ref (`text`,
`text_method`) so the scroll can render it (ADR 0114, `scrolls.documents`).
A held PDF that predates that is read from disk on the next run, never
downloaded again.
"""

from __future__ import annotations

import re
import time
import urllib.error
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Any, Callable
from urllib.parse import urlparse

from scrolls import documents
from scrolls.items import ScrollItem
from scrolls.paths import LibraryPaths
from scrolls.render import slugify
from scrolls.sources import http

# patchable seam, mirroring the source adapters: tests never touch the network
# The single network seam. It returns `(payload, size)` and declines a file
# larger than `max_bytes`, because "download this, but not if it is huge" is
# one operation — splitting it in two left the capped path untestable.
_download = http.get_bytes_within

# extension fallback when the URL path has none (pbs.twimg.com puts the
# format in the query; arXiv PDF links have no suffix at all)
_TYPE_EXTENSIONS = {
    "pdf": ".pdf",
    "photo": ".jpg",
    "thumbnail": ".jpg",
    "video": ".mp4",
}
_DEFAULT_EXTENSION = ".bin"

# A bulk capture is the one place this tool can look like a scraper. Wikimedia
# answers a fast run with HTTP 429 ("your bot is making too many requests"),
# and the honest reading of that is not "456 files failed" — the files are
# there, we asked too quickly. So downloads are paced, and a 429 is waited out
# rather than counted as a loss.
_DEFAULT_DELAY_SECONDS = 0.25
_DEFAULT_MAX_ATTEMPTS = 5
_BACKOFF_BASE_SECONDS = 2
_BACKOFF_CAP_SECONDS = 60
_RATE_LIMIT_STATUS = 429
# short, and at least one letter: ".jpg" yes, arXiv's version tail ".03762" no
_SAFE_SUFFIX = re.compile(r"^\.(?=[^.]*[A-Za-z])[A-Za-z0-9]{1,5}$")


def capture_media(
    paths: LibraryPaths,
    item: ScrollItem,
    force: bool = False,
    *,
    sleep: Callable[[float], None] = time.sleep,
    delay: float = _DEFAULT_DELAY_SECONDS,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    limit_for: Callable[[str | None], int | None] | None = None,
) -> tuple[ScrollItem, list[dict[str, Any]]]:
    """Download the item's media refs; return (updated item, per-ref results).

    Each result is `{"url", "status": "captured"|"skipped"|"failed"}` plus
    `path` when captured/skipped or `error` when failed. Refs already on
    disk are skipped unless `force`; refs without a `url` (including
    legacy non-dict refs) are skipped; one failed download never stops
    the others, and refs captured before a failure keep their paths.

    Args:
        paths: The library layout to write into.
        item: The item whose media refs to capture.
        force: Re-download refs that already have a file on disk.
        sleep: Injected sleep, for tests.
        delay: Seconds to pause after each download attempt, so a bulk run
            does not earn a rate limit in the first place.
        max_attempts: Attempts per file before a rate limit is reported as
            a failure.
        limit_for: Maps a ref's `type` to its byte cap, or None for no cap;
            omit to capture every file whatever its size. A declined file
            keeps its ref and records what was passed over, so the skip is
            custody rather than loss.
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
            result = {"url": url, "status": "skipped", "path": relpath}
            if documents.wants_text(item, ref) and "text" not in ref:
                try:
                    held = target.read_bytes()
                except OSError as exc:  # left unread, so a later run retries
                    results.append(
                        {"url": url, "status": "failed", "error": f"cannot read {relpath}: {exc}"}
                    )
                    continue
                result["text"] = _read_document(ref, held)
                changed = True
            results.append(result)
            continue
        cap = limit_for(ref.get("type")) if limit_for else None
        try:
            payload, size = _fetch_with_backoff(
                url, sleep=sleep, delay=delay, max_attempts=max_attempts, max_bytes=cap
            )
        except (OSError, ValueError) as exc:  # URLError is an OSError
            results.append({"url": url, "status": "failed", "error": str(exc)})
            continue
        if payload is None:  # declined on size — recorded, not lost
            if ref.get("oversize") != cap or ref.get("bytes") != size:
                ref["oversize"], ref["bytes"] = cap, size
                ref.pop("path", None)
                changed = True
            results.append(
                {"url": url, "status": "skipped", "reason": "oversize", "bytes": size}
            )
            continue
        if "oversize" in ref:  # the cap was raised since the last run
            ref.pop("oversize", None)
            ref.pop("bytes", None)
            changed = True
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        if ref.get("path") != relpath:
            ref["path"] = relpath
            changed = True
        result = {"url": url, "status": "captured", "path": relpath}
        if documents.wants_text(item, ref):  # a fresh file is always read afresh
            before = (ref.get("text", _UNREAD), ref.get("text_method"))
            result["text"] = _read_document(ref, payload)
            changed = changed or before != (ref["text"], ref["text_method"])
        results.append(result)
    updated = replace(item, media=tuple(refs)) if changed else item
    return updated, results


def _fetch_with_backoff(
    url: str,
    *,
    sleep: Callable[[float], None],
    delay: float,
    max_attempts: int,
    max_bytes: int | None = None,
) -> tuple[bytes | None, int | None]:
    """Download one file, waiting out rate limits.

    Returns:
        A `(payload, size)` pair; `payload` is None when the file was declined
        for exceeding `max_bytes`.

    Raises:
        ValueError: The host kept rate-limiting us past `max_attempts`. The
            message says so in those words, because "rate limited" and
            "the file is gone" want different responses from the operator.
        OSError: Any other transport failure, unretried — a 404 will not
            become a 200 by asking again.
    """
    for attempt in range(max_attempts):
        try:
            payload, size = _download(url, max_bytes=max_bytes)
        except urllib.error.HTTPError as exc:
            if exc.code != _RATE_LIMIT_STATUS:
                raise
            if attempt == max_attempts - 1:
                raise ValueError(
                    f"rate limited by the host after {max_attempts} attempts; "
                    "the file is still there — re-run the capture later"
                ) from exc
            sleep(_retry_wait(exc, attempt))
            continue
        if delay:
            sleep(delay)
        return payload, size
    raise ValueError("exhausted attempts")  # pragma: no cover - loop always returns



def _retry_wait(exc: urllib.error.HTTPError, attempt: int) -> float:
    """Seconds to wait: the host's own `Retry-After` when it named one."""
    headers = getattr(exc, "headers", None)
    raw = headers.get("retry-after") if headers else None
    if raw:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    return float(min(_BACKOFF_BASE_SECONDS * (2**attempt), _BACKOFF_CAP_SECONDS))


_UNREAD = object()

# What `scrolls media` learns about a ref: where its file is held, why it was
# declined, and what the held document says. None of it is the adapter's to know.
_CAPTURE_STATE = ("path", "oversize", "bytes", "text", "text_method")


def carry_capture_state(held: ScrollItem, fetched: ScrollItem) -> ScrollItem:
    """Keep each media ref's capture state across a re-fetch, matched by URL.

    An adapter rebuilds an item's media refs from the source every time, so a
    re-fetch would otherwise forget the held file — and the document text read
    from it (ADR 0114) — until `scrolls media` downloaded the file again. The
    adapter's own fields still win; a ref whose URL is new carries nothing.

    Args:
        held: The stored item, before the re-fetch.
        fetched: What the adapter returned.

    Returns:
        `fetched`, with the matching refs' capture state restored; `fetched`
        itself when there is nothing to carry.
    """
    state = {
        ref["url"]: {key: ref[key] for key in _CAPTURE_STATE if key in ref}
        for ref in held.media
        if isinstance(ref, dict) and ref.get("url")
    }
    refs, changed = [], False
    for ref in fetched.media:
        carried = state.get(ref.get("url")) if isinstance(ref, dict) else None
        missing = {k: v for k, v in (carried or {}).items() if k not in ref}
        if missing:
            ref = {**ref, **missing}
            changed = True
        refs.append(ref)
    return replace(fetched, media=tuple(refs)) if changed else fetched


def _read_document(ref: dict[str, Any], payload: bytes) -> str:
    """Read a PDF's text onto its ref; return `"extracted"` or `"none"`.

    The one extraction seam the `pdf` and `arxiv` adapters already share, so
    a document reads the same whichever route held it. A file pypdf cannot
    read, or one with no text layer, records `text: None` — read, and
    honestly empty — rather than leaving it looking unread.
    """
    import pypdf

    from scrolls.sources.pdf import extract_text

    ref["text"] = extract_text(payload)
    ref["text_method"] = f"pypdf-{pypdf.__version__}"
    return "extracted" if ref["text"] else "none"


def has_pending_document_text(paths: LibraryPaths, item: ScrollItem) -> bool:
    """True if a held PDF on disk has never been read (ADR 0114)."""
    return any(
        documents.wants_text(item, ref)
        and documents.is_held(ref)
        and "text" not in ref
        and (paths.root / ref["path"]).exists()
        for ref in item.media
    )


def has_pending_media(paths: LibraryPaths, item: ScrollItem) -> bool:
    """True if any media ref has a URL but no captured file on disk."""
    for ref in item.media:
        if not isinstance(ref, dict) or not ref.get("url"):
            continue
        if ref.get("oversize"):  # declined on size, recorded, not pending
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
