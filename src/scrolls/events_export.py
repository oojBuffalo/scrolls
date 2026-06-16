"""Lossless JSONL custody-event export and import — whole-library portable
custody (roadmap H72, the backup-path counterpart of the shareable bundle's
H67 portable custody).

`scrolls export events` serializes the library's verify ledger
(`custody_events`) to JSON Lines on stdout and `scrolls import events <path>`
reads them back, deduped. Where `export bundle`/`import bundle` (H67) carry a
*scoped* topic's ledger inside a readable briefing, this is the *whole-library*
ledger as a machine-oriented stream — the custody sibling of `export items`
(ADR 0082): back up the library's items with `export items`, its custody record
with `export events`, and a fresh machine reconstructs both.

The unit is one JSON object per event per line (the full `event_export_dict`
row — every `custody_events` column, `item_id` included). The CustodyEvent↔dict
mapping lives with the model (`custody.event_export_dict`/`event_from_dict`), so
this module is only the JSONL framing, file IO, and validation.

Validation mirrors the items export: a malformed line — not JSON, not an
object, or missing a required identity field (`item_id`/`checked_at`/`status`)
— raises naming the line rather than being silently dropped (losing a check
from a custody backup would lose the proof of *when* a source was verified).
Unknown keys are tolerated (`event_from_dict` drops them, e.g. the per-library
autoincrement `id`, which is never part of the identity), so a newer schema's
export still loads. Blank lines are skipped.

Import restores through `custody.import_events`, which dedups by the content
5-tuple `(item_id, checked_at, status, prior_hash, observed_hash)` — the same
idempotent restore the bundle import uses — so re-importing a backup is a
custody no-op, the append-only ledger's `INSERT OR IGNORE`.
"""

from __future__ import annotations

import json
from pathlib import Path

from scrolls.custody import CustodyEvent, event_from_dict

# A ledger row with no item_id/checked_at/status is not a custody event — the
# minimal identity an event must carry to be restorable (mirrors the items
# export's required-identity check).
_REQUIRED = ("item_id", "checked_at", "status")


class EventsSourceError(Exception):
    """The events export is missing, or a line is not a valid custody event."""


def load_events_export(path: Path) -> tuple[list[CustodyEvent], dict]:
    """Parse a JSONL custody-events export into events — the export inverse.

    Returns (events, stats) where stats is `{"events": N}`. Blank lines are
    skipped. Raises EventsSourceError for a missing file or any malformed line
    (invalid JSON, a non-object, or a record missing a required identity field),
    naming the line so corruption is locatable; unknown keys are tolerated for
    forward compatibility.
    """
    if not path.is_file():
        raise EventsSourceError(f"no events export at {path}")

    events: list[CustodyEvent] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EventsSourceError(
                f"{path} line {lineno}: not valid JSON ({exc.msg})"
            ) from exc
        if not isinstance(data, dict):
            raise EventsSourceError(
                f"{path} line {lineno}: expected a JSON object, "
                f"got {type(data).__name__}"
            )
        missing = [name for name in _REQUIRED if not data.get(name)]
        if missing:
            raise EventsSourceError(
                f"{path} line {lineno}: custody event missing required field(s): "
                + ", ".join(missing)
            )
        events.append(event_from_dict(data))

    return events, {"events": len(events)}
