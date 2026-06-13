"""Item removal: delete an item and the files it owns (ADR 0027).

`scrolls add`'s inverse. Files go first and the row last, so an
interrupted removal always leaves a re-runnable item — never orphan
files, which doctor reports but deliberately refuses to delete. Only
paths scrolls itself recorded (`markdown_path`, captured media `path`s)
are touched, and only inside the library root; the KB pages referencing
a removed scroll stay until the next `scrolls kb`, like every other
mutation.
"""

from __future__ import annotations

from scrolls.items import ScrollItem, delete_item, make_item_id
from scrolls.paths import LibraryPaths
from scrolls.sources.detect import detect_source
from scrolls.sources.urls import normalize_url


def resolve_item_id(ref: str) -> str:
    """An item id verbatim, or a URL resolved to the id `add` would mint.

    The same normalize → detect → mint chain as `pipeline.register_url`
    (ADR 0023 included), so the URL that created an item — in any
    tracking-decorated spelling — is always a valid handle for removing
    it. Raises ValueError for URLs no adapter can handle.
    """
    if "://" not in ref:
        return ref
    cleaned = normalize_url(ref)
    detected = detect_source(cleaned)
    return make_item_id(detected.source, detected.source_id, cleaned)


def remove_item(paths: LibraryPaths, item: ScrollItem) -> list[str]:
    """Delete the item's files, then its row; return the deleted paths.

    Files already gone are fine — the goal state is absence. Every
    recorded path is validated against the library root before anything
    is deleted: one poisoned ref must not half-delete the item, and a
    path scrolls never wrote (ValueError) is not removal's to delete.
    """
    relpaths = [item.markdown_path] if item.markdown_path else []
    relpaths += [
        ref["path"] for ref in item.media if isinstance(ref, dict) and ref.get("path")
    ]
    root = paths.root.resolve()
    targets = []
    for relpath in relpaths:
        target = (paths.root / relpath).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"recorded path escapes the library root: {relpath}")
        targets.append((relpath, target))

    removed = []
    for relpath, target in targets:
        if target.exists():
            target.unlink()
            removed.append(relpath)
    delete_item(paths.db_path, item.id)
    return removed
