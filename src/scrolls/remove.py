"""Item removal: delete an item and the files it owns (ADR 0027).

`scrolls add`'s inverse. Files go first and the row last, so an
interrupted removal always leaves a re-runnable item — never orphan
files, which doctor reports but deliberately refuses to delete. Only
paths scrolls itself recorded (`markdown_path`, captured media `path`s)
are touched, inside their respective scrolls/ and media/ trees; KB pages referencing
a removed scroll stay until the next `scrolls kb`, like every other
mutation.
"""

from __future__ import annotations

from scrolls.items import ScrollItem, delete_item, list_items
from scrolls.paths import LibraryPaths, artifact_path


def remove_item(paths: LibraryPaths, item: ScrollItem) -> list[str]:
    """Delete the item's files, then its row; return the deleted paths.

    Files already gone are fine — the goal state is absence. Every
    recorded path is validated against the library root before anything
    is deleted: one poisoned ref must not half-delete the item, and a
    path scrolls never wrote (ValueError) is not removal's to delete.
    """
    relpaths = [(item.markdown_path, "scrolls")] if item.markdown_path else []
    relpaths += [
        (ref["path"], "media")
        for ref in item.media if isinstance(ref, dict) and ref.get("path")
    ]
    targets = []
    for relpath, directory in relpaths:
        target = artifact_path(paths, relpath, directory)
        targets.append((relpath, target))

    shared = set()
    for peer in list_items(paths.db_path):
        if peer.id == item.id:
            continue
        if peer.markdown_path:
            shared.add(peer.markdown_path)
        shared.update(
            ref["path"] for ref in peer.media if isinstance(ref, dict) and ref.get("path")
        )

    removed = []
    for relpath, target in targets:
        if relpath not in shared and target.exists():
            target.unlink()
            removed.append(relpath)
    delete_item(paths.db_path, item.id)
    return removed
