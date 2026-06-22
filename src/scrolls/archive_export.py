"""Lossless JSONL prior-content-archive export and import — the portable recovery
store (roadmap H280, the archive-axis counterpart of `events_export`'s H72
portable custody).

`scrolls export archive` serializes the library's prior-content archive
(`item_archive`, ADR 0106) to JSON Lines on stdout and `scrolls import archive
<path>` reads them back, deduped. Where `export bundle --with-archive` carries a
*scoped* topic's archived priors inside a sentinel-fenced block, this is the
*whole-library* recovery store as a machine-oriented stream — the third member
of the lossless backup family (`export items` for the holdings, `export events`
for the custody ledger, `export archive` for the recoverable superseded priors).

A library rebuilt from `import items` + `import events` reads *that* an adoption
happened (the `superseded` event travels in the ledger) but cannot recover the
prior bytes; `import archive` restores the recovery store, so `scrolls archive
show <id>` re-emits the same prior on the rebuilt library.

The unit is one JSON object per archived prior per line (the full
`archive_export_dict` row: `item_id`, `archived_at`, `prior_hash`,
`superseded_by`, and the nested model-complete `snapshot`). The
ArchiveRecord↔dict mapping lives with the model
(`items.archive_export_dict`/`archive_from_dict`), so this module is only the
JSONL framing, file IO, and validation.

Validation mirrors the items/events exports: a malformed line — not JSON, not an
object, or missing a required identity field (`item_id`/`archived_at`/`snapshot`)
— raises naming the line rather than being silently dropped (losing a prior from
a recovery backup would lose the only copy of a superseded capture). Unknown keys
are tolerated (`archive_from_dict` drops them, e.g. the per-library autoincrement
`id`, which is never part of the identity), so a newer schema's export still
loads. Blank lines are skipped.

Import restores through `items.import_archive`, which dedups by `(item_id,
prior_hash)` — the same idempotent restore the bundle import uses — so
re-importing a backup, or the overlapping union of two bundles, is a no-op.
"""

from __future__ import annotations

import json
from pathlib import Path

from scrolls.items import ArchiveRecord, archive_from_dict

# An archive row with no item_id/archived_at/snapshot is not a restorable prior
# capture — the minimal identity it must carry (mirrors the items/events exports'
# required-identity check). `prior_hash`/`superseded_by` are nullable.
_REQUIRED = ("item_id", "archived_at", "snapshot")


class ArchiveSourceError(Exception):
    """The archive export is missing, or a line is not a valid archived prior."""


def load_archive_export(path: Path) -> tuple[list[ArchiveRecord], dict]:
    """Parse a JSONL archive export into records — the export inverse.

    Returns (records, stats) where stats is `{"archive": N}`. Blank lines are
    skipped. Raises ArchiveSourceError for a missing file or any malformed line
    (invalid JSON, a non-object, or a record missing a required identity field),
    naming the line so corruption is locatable; unknown keys are tolerated for
    forward compatibility.
    """
    if not path.is_file():
        raise ArchiveSourceError(f"no archive export at {path}")

    records: list[ArchiveRecord] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ArchiveSourceError(
                f"{path} line {lineno}: not valid JSON ({exc.msg})"
            ) from exc
        if not isinstance(data, dict):
            raise ArchiveSourceError(
                f"{path} line {lineno}: expected a JSON object, "
                f"got {type(data).__name__}"
            )
        missing = [name for name in _REQUIRED if not data.get(name)]
        if missing:
            raise ArchiveSourceError(
                f"{path} line {lineno}: archived prior missing required field(s): "
                + ", ".join(missing)
            )
        records.append(archive_from_dict(data))

    return records, {"archive": len(records)}
