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

from scrolls.items import ScrollItem, delete_item
from scrolls.paths import LibraryPaths


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
