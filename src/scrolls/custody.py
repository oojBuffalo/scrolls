"""Custody drift/rot detection — the custody ledger made real (ADR 0098).

The custody integrity audit (ADR 0097) answers "do we still hold, on disk,
what the index claims?" entirely offline. This module answers the network
question it deferred: *has the live source drifted away from, or rotted out
from under, what we captured?* `scrolls verify` re-captures a rendered item
through its adapter, recomputes the content hash, compares it to the stored
one, and appends a **custody event** to the ledger — never clobbering the
original capture. Detecting that a source changed must not destroy the proof
of what it was when we saved it; that is the whole point of custody.

The verdict taxonomy (`CUSTODY_STATUSES`):

- ``unchanged`` — the re-captured hash equals the stored one. The live source
  still matches our capture.
- ``drifted`` — the hashes differ. The source changed since we saved it; we
  still hold the original, and now we know it diverged.
- ``rotted`` — the resource is gone (a definitive HTTP 404/410). We can no
  longer re-fetch it; our capture may be the only copy left.
- ``error`` — the re-capture failed for some other reason (transient network,
  a parse error, no adapter). Not a custody verdict about the *source*, just an
  honest "we could not check right now".

`verify_item` is pure and deterministic: it takes the stored item, a
``recapture`` callable (`ScrollItem -> ScrollItem`, raising `FetchError`), and
the timestamp to stamp, so the whole decision is testable without a network.
The live wiring (`live_recapture`) is the only part that touches a source
adapter. The rot/error split reads the real HTTP status off the raised
`FetchError`'s ``__cause__`` (adapters ``raise FetchError(...) from exc``), so
it is grounded in the actual status code, not a string match on the message.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError

CUSTODY_STATUSES = ("unchanged", "drifted", "rotted", "error")

# HTTP statuses that mean the resource is definitively gone, not transiently
# unreachable: 404 Not Found and 410 Gone. A capture whose source returns one
# of these has rotted — we hold the last copy.
_GONE_CODES = frozenset({404, 410})

# A re-capture that re-fetches and normalizes a stored item, returning the
# fresh ScrollItem (with a freshly computed content_hash) or raising FetchError.
Recapture = Callable[[ScrollItem], ScrollItem]


@dataclass(frozen=True)
class CustodyEvent:
    """One verification of an item against its live source — a ledger row.

    ``prior_hash`` is the content hash held at check time; ``observed_hash`` is
    what the re-capture produced (``None`` when the re-capture failed, so there
    was nothing to observe). ``detail`` carries the failure message for a
    ``rotted``/``error`` event and is ``None`` for a clean check.
    """

    item_id: str
    checked_at: str
    status: str
    prior_hash: str | None
    observed_hash: str | None
    detail: str | None = None


def _is_gone(exc: BaseException) -> bool:
    """Did this fetch failure carry a definitive HTTP 'gone' status?

    Adapters wrap transport errors as ``raise FetchError(...) from exc``, so the
    original ``urllib`` ``HTTPError`` (which carries ``.code``) survives as the
    cause. Reading the real status keeps the rot/error split honest — a string
    like "not found" in a message never decides custody.
    """
    cause = getattr(exc, "__cause__", None)
    return getattr(cause, "code", None) in _GONE_CODES


def verify_item(
    item: ScrollItem, recapture: Recapture, *, now: str
) -> CustodyEvent:
    """Re-capture `item` and classify the result against its stored hash.

    Pure and network-free given `recapture`: re-capture succeeds and the hashes
    match → ``unchanged``; they differ → ``drifted``; the re-capture raises with
    a 404/410 cause → ``rotted``; any other failure → ``error``. The stored item
    is read, never written — the caller records the returned event to the ledger
    and leaves the original capture intact.
    """
    try:
        fresh = recapture(item)
    except FetchError as exc:
        status = "rotted" if _is_gone(exc) else "error"
        return CustodyEvent(item.id, now, status, item.content_hash, None, str(exc))
    status = "unchanged" if fresh.content_hash == item.content_hash else "drifted"
    return CustodyEvent(
        item.id, now, status, item.content_hash, fresh.content_hash, None
    )


def live_recapture(item: ScrollItem) -> ScrollItem:
    """Re-fetch a stored item through its source adapter (the network edge).

    The one impure step `verify_item` is built to keep at arm's length: it
    routes to the same `FETCH_ADAPTERS` entry `scrolls fetch` uses, so a
    re-capture sees exactly what a fresh capture would. An item whose source has
    no adapter cannot be verified, which is an honest `FetchError` (→ ``error``),
    not a crash.
    """
    adapter = FETCH_ADAPTERS.get(item.source)
    if adapter is None:
        raise FetchError(f"no fetch adapter for source '{item.source}'")
    return adapter(item)


# --- ledger persistence ---------------------------------------------------

_EVENT_COLUMNS = ("item_id", "checked_at", "status", "prior_hash", "observed_hash", "detail")


def record_events(db_path: Path, events: Iterable[CustodyEvent]) -> int:
    """Append custody events to the ledger in one transaction; return the count.

    Append-only: the ledger keeps every check, so the drift history of an item
    is reconstructable. The autoincrement `id` orders them.
    """
    rows = [
        (e.item_id, e.checked_at, e.status, e.prior_hash, e.observed_hash, e.detail)
        for e in events
    ]
    if not rows:
        return 0
    placeholders = ", ".join("?" for _ in _EVENT_COLUMNS)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.executemany(
                f"INSERT INTO custody_events ({', '.join(_EVENT_COLUMNS)}) "
                f"VALUES ({placeholders})",
                rows,
            )
    finally:
        conn.close()
    return len(rows)


def _from_row(row: sqlite3.Row) -> CustodyEvent:
    return CustodyEvent(
        item_id=row["item_id"],
        checked_at=row["checked_at"],
        status=row["status"],
        prior_hash=row["prior_hash"],
        observed_hash=row["observed_hash"],
        detail=row["detail"],
    )


def _query_events(db_path: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Run a ledger read, tolerating a library too old to hold the table.

    The ledger arrived in schema v7; a v6 library that has only ever been read
    (never `verify`-ed, never otherwise migrated) has no `custody_events` table.
    A read-only consumer — `scrolls doctor`'s drift aggregation — must report
    "no events" there, not crash, so a missing table reads as an empty ledger.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:  # no custody_events table (pre-v7 library)
        return []
    finally:
        conn.close()


def item_events(db_path: Path, item_id: str) -> list[CustodyEvent]:
    """Every recorded check for one item, newest first."""
    rows = _query_events(
        db_path,
        "SELECT * FROM custody_events WHERE item_id = ? ORDER BY id DESC",
        (item_id,),
    )
    return [_from_row(row) for row in rows]


def latest_events(db_path: Path) -> dict[str, CustodyEvent]:
    """The most recent custody event per item, keyed by item id.

    "Most recent" is the largest `id` for that item — a monotonic counter that
    breaks the same-second ties `checked_at` cannot. Items never verified are
    simply absent. This is what doctor aggregates into its drift report.
    """
    rows = _query_events(
        db_path,
        "SELECT * FROM custody_events WHERE id IN "
        "(SELECT MAX(id) FROM custody_events GROUP BY item_id)",
    )
    return {row["item_id"]: _from_row(row) for row in rows}
