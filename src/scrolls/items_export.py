"""Lossless JSONL item export and import (ADR 0082).

`scrolls export items` serializes the library's items to JSON Lines on
stdout and `scrolls import items <path>` reads them back. This is the
fourth member of the `export` namespace (after `opml` and `bookmarks`),
but the first whose **importer is Scrolls itself**: where the OPML and
bookmark exports round-trip against external readers (and so carry only a
spine an external format can hold — feeds, or URL+title+date+tags),
this carries every `ScrollItem` field — `raw_text`, `extracted_text`,
`links`, `media`, `provenance`, `content_hash`, `markdown_path`, `stage`
— because the format it round-trips against is Scrolls' own model. That
makes it the **lossless** export ADR 0077/0079 deferred for want of an
external importer: a library you can back up, migrate to another machine,
or merge into another library, byte-for-byte.

The unit is one JSON object per line (JSON Lines): streamable, robust to
a truncated tail, `jq`/`grep`-friendly, and the same shape Field Theory's
raw cache uses (IDEAS.md §13). The ScrollItem↔dict mapping lives with the
model (`items.item_to_dict`/`item_from_dict`), so this module is only the
JSONL framing, file IO, and validation.

Validation is stricter than the heterogeneous third-party imports
(bookmarks/Pocket count per-entry oddities and continue): a Scrolls
export is internally consistent, so a malformed line — not JSON, not an
object, or missing a required identity field — raises naming the line
rather than being silently dropped. Silently skipping a record from a
*backup* would lose data without telling anyone. Unknown keys, by
contrast, are tolerated (`item_from_dict` drops them) so a newer schema's
export still loads under an older reader. Blank lines are skipped.

Import reconstructs the index rows only — the canonical store. The
derived artifacts (the Markdown scrolls, captured media, the compiled
`library/`) rebuild from those rows: `scrolls doctor --fix` rewrites any
missing scroll file and the FTS index, and `scrolls kb` recompiles the
library. Rows go in with `INSERT OR IGNORE` (dedupe by id, the universal
import contract), so a re-import is cheap and never overwrites.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from scrolls.items import ScrollItem, item_from_dict, item_to_dict

# An item with no id/source/url/saved_at isn't a Scrolls item — every writer
# sets all four (none has a dataclass default), so a record missing one is a
# corrupt or wrong file, not a tolerable per-entry oddity.
_REQUIRED = ("id", "source", "url", "saved_at")


class ItemsSourceError(Exception):
    """The items export is missing, or a line is not a valid item record."""


def dump_items_export(items: Iterable[ScrollItem]) -> str:
    """Serialize items to a JSON Lines document — the import inverse.

    One JSON object per item per line (newline-terminated), every
    `ScrollItem` field present in dataclass order, in the given order. An
    empty iterable produces an empty string — a valid empty document, not
    an error.
    """
    return "".join(json.dumps(item_to_dict(item)) + "\n" for item in items)


def load_items_export(path: Path) -> tuple[list[ScrollItem], dict]:
    """Parse a JSONL items export into items.

    Returns (items, stats) where stats is `{"items": N}`. Blank lines are
    skipped. Raises ItemsSourceError for a missing file or any malformed
    line (invalid JSON, a non-object, or a record missing a required
    identity field), naming the line so corruption is locatable; unknown
    keys are tolerated for forward compatibility.
    """
    if not path.is_file():
        raise ItemsSourceError(f"no items export at {path}")

    items: list[ScrollItem] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ItemsSourceError(
                f"{path} line {lineno}: not valid JSON ({exc.msg})"
            ) from exc
        if not isinstance(data, dict):
            raise ItemsSourceError(
                f"{path} line {lineno}: expected a JSON object, "
                f"got {type(data).__name__}"
            )
        missing = [name for name in _REQUIRED if not data.get(name)]
        if missing:
            raise ItemsSourceError(
                f"{path} line {lineno}: item missing required field(s): "
                + ", ".join(missing)
            )
        items.append(item_from_dict(data))

    return items, {"items": len(items)}
