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

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Collection, Iterable

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem, get_fidelity, get_item
from scrolls.sources import FETCH_ADAPTERS, FetchError

CUSTODY_STATUSES = ("unchanged", "drifted", "rotted", "error")

# The import-time content-divergence event (roadmap H274): a *different* capture
# of an already-held id — a peer's bundle, another library's `export items` — was
# presented at merge time with a `content_hash` that disagrees with the held copy.
# A **distinct provenance-of-divergence axis**, deliberately *not* a verify verdict:
# `verify` re-captures through the live adapter and asks "has the *source* moved?";
# an import conflict involves no source re-capture at all — we only know a *peer*
# disagreed. So it is recorded in the same append-only ledger (queryable on the
# per-item `scrolls history` timeline) but is **excluded from the drift posture**
# (`latest_events` reads only `CUSTODY_STATUSES`): claiming the source `drifted`
# off a peer disagreement would be fabrication (the M2 honesty — the drift axis
# means "the live source moved", which a conflict is not evidence of). The held
# copy is never touched; the conflict is a recorded, surfaced event (custody §2.4,
# the obsidian reconcile adoption — *detect, surface, don't rewrite*).
CONFLICT_STATUS = "conflict"

# The human detail stamped on a conflict event — the readable counterpart of the
# `_warn_conflicts` stderr line, persisted so `scrolls history` is self-describing.
_CONFLICT_DETAIL = "import conflict: an incoming capture of this id differs from the held copy"

# Every status that can appear in a ledger row — the four verify verdicts plus the
# import-conflict event. The `scrolls history --status` filter validates against
# this superset (a conflict event is readable on the timeline and filterable), but
# the drift posture reads only the `CUSTODY_STATUSES` verify verdicts.
LEDGER_STATUSES = CUSTODY_STATUSES + (CONFLICT_STATUS,)

# The custody-fidelity tiers in best-held-first order — the three `get_fidelity`
# returns. The canonical order every custody headline renders tiers in.
FIDELITY_TIERS = ("full", "partial", "reference")

# The drift postures in reading order — the five `drift_posture` returns.
# `verified` is the posture word for the ledger's `unchanged` status, so a
# headline's `verified` count equals `doctor`'s `custody.drift.unchanged` and
# `unverified` equals held − verdicts (the H42 convergence, lifted to a scope).
# The order is also *safest-first*: `verified` (confirmed unmoved) is the most
# reassuring custody posture, `unverified` (never checked, so unknown — but no
# evidence of movement) next, then the confirmed/uncertain losses
# (`drifted`/`rotted`/`error`). The consolidation surface reads it that way —
# `works.work_custody`'s `safest_drift` is the min-index posture across a work's
# representations (roadmap H261).
DRIFT_POSTURES = ("verified", "unverified", "drifted", "rotted", "error")

# The drift postures that count as a *safe hold* — the source has not confirmed
# moved away from, or rotted out from under, our capture. `verified` (re-checked
# unchanged) and `unverified` (never checked, so no *evidence* of movement — the
# M2 honesty: unknown, not silently "clean") are safe; `drifted`/`rotted` are
# confirmed loss and `error` is "we tried and could not confirm" (weaker than
# never-checked), so none of those three is a safe hold. The complement of
# `_LOSS_POSTURES` ∪ {`error`}. The work-level `safely_held` predicate
# (roadmap H261) pairs this with full fidelity: a work is safely held when a
# representation is both `full` *and* in a safe drift posture.
SAFE_DRIFT_POSTURES = ("verified", "unverified")

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


def conflict_event(
    item_id: str,
    *,
    held_hash: str | None,
    incoming_hash: str | None,
    now: str,
) -> CustodyEvent:
    """Build the custody event recording an import-time content divergence (H274).

    The conflict-axis counterpart of `verify_item`'s drift event: where that records
    "the live source moved" from a re-capture, this records "another capture of this
    id disagreed with mine, observed at import time" from a lossless merge
    (`import items` / `import bundle`, the importers whose rows carry a model-complete
    `content_hash`). Pure and deterministic given `now`, exactly like `verify_item`,
    so the construction is testable without a clock — the CLI edge stamps the wall
    time and the held copy is never touched.

    The two-hash slot reuses the verify-event field semantics verbatim, so every
    existing serializer (`event_payload`, `event_export_dict`) and the export/import
    round-trip carry it unchanged:

    - ``prior_hash`` = the held copy's `content_hash` — what *we* hold (raw is sacred,
      kept, never overwritten);
    - ``observed_hash`` = the *incoming* `content_hash` that disagreed — what the
      peer's capture presented.

    ``status`` is `CONFLICT_STATUS`, deliberately *outside* the verify verdicts, so
    the event rides the per-item `scrolls history` timeline yet never enters the
    drift posture `latest_events` derives (it reads only `CUSTODY_STATUSES`) — the
    M2 honesty that a peer disagreement is not evidence the live source drifted.
    """
    return CustodyEvent(
        item_id=item_id,
        checked_at=now,
        status=CONFLICT_STATUS,
        prior_hash=held_hash,
        observed_hash=incoming_hash,
        detail=_CONFLICT_DETAIL,
    )


# --- ledger persistence ---------------------------------------------------

_EVENT_COLUMNS = ("item_id", "checked_at", "status", "prior_hash", "observed_hash", "detail")


def parse_since(since: str | None) -> str | None:
    """Normalize a ``--since`` ledger-window boundary to the stored UTC ISO
    vocabulary (ADR 0024), or ``None`` when no window was asked for.

    The shared validator behind every time-windowed ledger read — `scrolls
    history <id> --since` (roadmap H71) and `scrolls export events --since`
    (H75). It funnels the raw boundary through `dates.to_utc_iso`, the one
    parser every `published_at`/`checked_at` writer uses, so the window edge
    ends up in *exactly* the ``isoformat(timespec="seconds")`` ``+00:00`` shape
    `verify` stamps a `checked_at` with. That makes the downstream lexicographic
    ``checked_at >= since`` compare apples-to-apples regardless of how the
    boundary was written — a ``Z`` suffix, a different offset, or a date-only
    ``2026-06-15`` (which becomes that day's midnight UTC) all normalize to the
    stored shape before the compare, so the ordering is correct and not a
    string-shape accident.

    ``None`` or a blank value means *no window* (returns ``None``); a non-blank
    value that does not parse as a timestamp raises ``ValueError`` — a malformed
    window is a loud usage error (the CLI maps it to exit 2, the MCP twin lets
    it surface), never a silently empty result that could mask a typo.
    """
    if since is None or not since.strip():
        return None
    normalized = to_utc_iso(since)
    if normalized is None:
        raise ValueError(f"not a valid ISO-8601 timestamp: {since!r}")
    return normalized


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


def event_payload(event: CustodyEvent) -> dict[str, str | None]:
    """One ledger event as a JSON-ready dict — the per-event read shape.

    The shared serializer behind `scrolls history <id>` (roadmap H66) and its
    MCP twin, so the per-item custody timeline reads byte-identical whichever
    surface an agent reaches. The item id is omitted on purpose: `history` is
    scoped to one item (the argument), so every row carries the same id — the
    five fields that vary per check are ``checked_at`` (when), ``status`` (the
    verdict), the ``prior_hash``/``observed_hash`` pair (what we held vs what the
    re-capture saw), and ``detail`` (the failure message for a ``rotted``/
    ``error`` event, ``None`` for a clean check).
    """
    return {
        "checked_at": event.checked_at,
        "status": event.status,
        "prior_hash": event.prior_hash,
        "observed_hash": event.observed_hash,
        "detail": event.detail,
    }


def item_history(
    db_path: Path,
    item_id: str,
    *,
    limit: int | None = None,
    since: str | None = None,
    status: str | None = None,
) -> list[dict[str, str | None]]:
    """The custody ledger timeline for one item, newest first.

    The read-surface form of the append-only events `verify` writes: every
    recorded check serialized through `event_payload`, newest first (the
    `item_events` order). An item the ledger has never checked yields ``[]`` —
    the honest-empty form (completeness G1), distinct from an *unknown* item,
    which the caller rejects as a could-not-check before reaching here. Pure
    over the ledger read; the single primitive `scrolls history` and the MCP
    `get_scroll_history` twin share, so they can never disagree.

    Three independent filter axes, applied **verdict → time → count** (order is
    immaterial to the result — the first two are AND filters, `limit` only caps
    what remains):

    - `status` keeps only the checks whose verdict is exactly this — one of
      `LEDGER_STATUSES` (the four verify verdicts
      ``unchanged``/``drifted``/``rotted``/``error`` *plus* the import-time
      ``conflict`` event, roadmap H274 — the raw event status `history` emits,
      *not* the reader-facing drift posture): "show me only the times this source
      actually changed" (H77), or "only the import conflicts" (H274). An unknown
      verdict raises ``ValueError`` (a closed vocabulary — never a silent empty,
      the `list --drift` posture), so both the CLI (which also guards via argparse
      ``choices``) and the MCP twin inherit the guarantee.
    - `since` is a **pre-normalized** UTC ISO boundary (see `parse_since`, which
      the CLI/MCP edge calls): only checks ``checked_at >= since`` are kept —
      the time-axis window a maintenance worker asks for ("what has this source
      done since the last sweep", roadmap H71).
    - `limit` then bounds the result to the most recent N checks (newest first,
      oldest dropped) — a maintenance worker that appends a verdict per pass
      accumulates a long history, and `--limit` reads only the head. ``0`` is
      the honest empty `[]` and an over-count returns all.

    Each axis is ``None`` by default, so the unfiltered shape is unchanged.
    """
    if status is not None and status not in LEDGER_STATUSES:
        raise ValueError(
            f"unknown custody status {status!r}; "
            f"choose one of {', '.join(LEDGER_STATUSES)}"
        )
    events = item_events(db_path, item_id)
    if status is not None:
        events = [event for event in events if event.status == status]
    if since is not None:
        events = [event for event in events if event.checked_at >= since]
    payloads = [event_payload(event) for event in events]
    return payloads if limit is None else payloads[:limit]


def event_export_dict(event: CustodyEvent) -> dict[str, str | None]:
    """One ledger event as a full export row — every column, ``item_id`` included.

    The bundle-export shape (roadmap H67), distinct from `event_payload` (the
    `scrolls history` read shape, which *omits* ``item_id`` because it is scoped
    to one item): a shareable bundle's custody-events block spans many items, so
    each row must name its own. Reuses `event_payload` for the five per-check
    fields and prepends the id, so the two serializers can never drift on the
    shared fields.
    """
    return {"item_id": event.item_id, **event_payload(event)}


def dump_events_export(events: Iterable[CustodyEvent]) -> str:
    """Serialize custody events to JSON Lines — the bundle custody-events block.

    One JSON object per event per line (newline-terminated), the full
    `event_export_dict` row, in the given order. Mirrors `dump_items_export`
    (the items block): an empty iterable produces an empty string — a valid empty
    document, the shape an unverified library's events block carries.
    """
    return "".join(json.dumps(event_export_dict(e)) + "\n" for e in events)


def event_from_dict(data: dict) -> CustodyEvent:
    """Reconstruct a `CustodyEvent` from an export row — the `event_export_dict`
    inverse. Unknown keys are tolerated (forward compatibility) and the
    autoincrement ledger id is intentionally absent: it is per-library, never
    exported, so a restored event is re-numbered by the target ledger. Identity
    validation (required fields present) is the caller's, like `item_from_dict`.
    """
    return CustodyEvent(
        item_id=data["item_id"],
        checked_at=data["checked_at"],
        status=data["status"],
        prior_hash=data.get("prior_hash"),
        observed_hash=data.get("observed_hash"),
        detail=data.get("detail"),
    )


def events_for_items(
    db_path: Path, item_ids: Iterable[str], *, since: str | None = None
) -> list[CustodyEvent]:
    """Every custody event for a set of items, in append (chronological) order.

    The export-side read behind the shareable bundle's custody-events block
    (roadmap H67) and the whole-library `export events` stream (H72): the
    in-scope items' full ledger so their drift *history* travels, not just the
    exporter's last-seen posture. Ordered by the monotonic `id` (the append
    order `verify` writes, i.e. chronological), so a fresh-library import
    re-appends them in the same order and `latest_events` there picks the same
    latest verdict. Filters the whole ledger in Python by the id set rather than
    a large ``IN`` clause, so a bundle covering many matches never hits SQLite's
    bound-parameter limit; reuses `_query_events`, so a pre-v7 library with no
    ledger table reads as an empty history.

    `since` is a **pre-normalized** UTC ISO boundary (see `parse_since`): only
    events ``checked_at >= since`` travel — the incremental-backup window
    (`scrolls export events --since`, roadmap H75) so a maintenance worker
    re-exports only what is new since the last backup. ``None`` (the default,
    and the bundle/H72 callers' value) exports the whole scoped ledger, so the
    untouched-window shape is unchanged; `import events`' content-dedup makes the
    union of overlapping incremental backups idempotent regardless.
    """
    wanted = set(item_ids)
    if not wanted:
        return []
    rows = _query_events(db_path, "SELECT * FROM custody_events ORDER BY id")
    events = [_from_row(row) for row in rows if row["item_id"] in wanted]
    if since is not None:
        events = [event for event in events if event.checked_at >= since]
    return events


# The content key that identifies a check across libraries — the autoincrement
# `id` is per-library (never exported) and `detail` describes the same check, so
# neither is part of the identity. Two ledger rows with this 5-tuple equal are
# the same custody event (roadmap H67's idempotent-restore key).
_EVENT_IDENTITY = ("item_id", "checked_at", "status", "prior_hash", "observed_hash")


def import_events(db_path: Path, events: Iterable[CustodyEvent]) -> tuple[int, int]:
    """Restore custody events into the ledger, deduped by content; return
    ``(imported, skipped)``.

    The verify-axis sibling of `import items`' ``INSERT OR IGNORE`` (ADR 0082):
    an event is skipped when the ledger already holds a content-identical row —
    same `_EVENT_IDENTITY` 5-tuple — so importing the *same* ledger twice is a
    custody no-op (the events are append-only with an autoincrement id; a blind
    append would grow the ledger on every re-import). The live append path
    `record_events` is left untouched — only this restore dedups, because only
    import can re-present an event the ledger already holds.

    Events are inserted oldest-`checked_at` first (a stable sort over the
    chronological export order), so in a fresh target the restored ids run in
    time order and `latest_events` picks the chronologically-latest verdict —
    the posture an agent reads after import matches the exporter's. Within-batch
    duplicates also dedup: the first insert makes the next iteration's existence
    check see it. NULL hashes compare NULL-safely (SQLite ``IS``).
    """
    ordered = sorted(events, key=lambda e: e.checked_at)
    where = " AND ".join(f"{col} IS ?" for col in _EVENT_IDENTITY)
    insert_cols = ", ".join(_EVENT_COLUMNS)
    placeholders = ", ".join("?" for _ in _EVENT_COLUMNS)
    imported = skipped = 0
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            for e in ordered:
                identity = (e.item_id, e.checked_at, e.status, e.prior_hash, e.observed_hash)
                exists = conn.execute(
                    f"SELECT 1 FROM custody_events WHERE {where} LIMIT 1", identity
                ).fetchone()
                if exists is not None:
                    skipped += 1
                    continue
                conn.execute(
                    f"INSERT INTO custody_events ({insert_cols}) VALUES ({placeholders})",
                    (*identity, e.detail),
                )
                imported += 1
    finally:
        conn.close()
    return imported, skipped


def preview_import_events(
    db_path: Path, events: Iterable[CustodyEvent]
) -> tuple[int, int]:
    """Count how `import_events` would split `events` into ``(imported, skipped)``
    *without writing* — the read-only sibling for `import bundle --dry-run` (H220).

    Mirrors `import_events`' dedup exactly: an event is *skipped* when the ledger
    already holds a content-identical row (`_EVENT_IDENTITY`) or an earlier event
    in this same batch already claimed that identity; otherwise *imported*.
    Because nothing is inserted, the within-batch dedup the writer gets for free
    from its prior INSERT is tracked here in a local `seen` set instead. The H220
    dry-run test pins these counts equal to a real import's, so the two never
    drift apart.
    """
    where = " AND ".join(f"{col} IS ?" for col in _EVENT_IDENTITY)
    imported = skipped = 0
    seen: set[tuple[object, ...]] = set()
    conn = sqlite3.connect(db_path)
    try:
        for e in sorted(events, key=lambda e: e.checked_at):
            identity = (e.item_id, e.checked_at, e.status, e.prior_hash, e.observed_hash)
            if identity in seen:
                skipped += 1
                continue
            exists = conn.execute(
                f"SELECT 1 FROM custody_events WHERE {where} LIMIT 1", identity
            ).fetchone()
            if exists is not None:
                skipped += 1
                continue
            seen.add(identity)
            imported += 1
    finally:
        conn.close()
    return imported, skipped


def partition_resolvable_events(
    db_path: Path,
    events: Iterable[CustodyEvent],
    known_ids: Collection[str] | None = None,
) -> tuple[list[CustodyEvent], list[CustodyEvent]]:
    """Split custody events into those the library can anchor and *orphans*.

    An event **resolves** when `get_item` finds its `item_id` in the library — a
    held-or-imported item it can be a custody record *of*; otherwise it is an
    **orphan**, a ledger row pointing at an item not in custody. Returns
    ``(resolvable, orphan)``, each in input order.

    The bundle-import honesty guard (roadmap H217): a bundle's custody-events
    block carries events only for in-scope items (`events_for_items`), every one
    of which also rides the items block, so a *well-formed* bundle yields no
    orphans. A corrupt or hand-edited bundle whose events name a missing item must
    be **surfaced** by the caller (an orphan count), never silently inserted as a
    dangling history — the ledger would assert a custody record for an item
    `scrolls show` 404s on (`history`/`facets drift` would read a phantom) — nor
    silently dropped (a take-it-with-me artifact that quietly loses rows). The
    caller decides what to do with the orphan list; this only classifies.

    Membership is read **once per distinct `item_id`** (cached), so a large
    in-scope ledger costs one `get_item` per item, not one per event. The
    whole-library `import events` restore (H72) deliberately does *not* use this:
    that path tolerates events restored before their items (the ledger is keyed by
    the `item_id` string and order is the operator's), whereas a bundle is an
    atomic items+events unit whose events should always anchor.

    `known_ids` names items the caller knows *will* be present even though the DB
    does not hold them yet — the `import bundle --dry-run` preview (H220) passes
    the bundle's own item ids, because a real import inserts those rows *before*
    partitioning, so an event for a not-yet-written bundle item resolves in the
    preview exactly as it would after the write. The live import path leaves it
    empty: its items are already on disk, so `get_item` finds them.
    """
    resolvable: list[CustodyEvent] = []
    orphan: list[CustodyEvent] = []
    known = set(known_ids) if known_ids else set()
    held: dict[str, bool] = {}
    for event in events:
        if event.item_id in known:
            resolvable.append(event)
            continue
        anchored = held.get(event.item_id)
        if anchored is None:
            anchored = get_item(db_path, event.item_id) is not None
            held[event.item_id] = anchored
        (resolvable if anchored else orphan).append(event)
    return resolvable, orphan


def latest_events(db_path: Path) -> dict[str, CustodyEvent]:
    """The most recent *verify* verdict per item, keyed by item id — the drift posture.

    "Most recent" is the largest `id` for that item — a monotonic counter that
    breaks the same-second ties `checked_at` cannot. Items never verified are
    simply absent. This is what doctor aggregates into its drift report and what
    every `drift_posture` read folds, so it is restricted to the **verify verdicts**
    (`CUSTODY_STATUSES`): a `conflict` event (roadmap H274 — a peer's capture
    disagreed at import time) lives in the same ledger and is readable on the
    per-item `scrolls history` timeline, but it must **not** become a drift posture
    (a peer disagreement is not evidence the live *source* moved — the M2 honesty),
    so the MAX(id) is taken over the verify rows only. An item carrying only a
    conflict event therefore reads `unverified` (never re-checked), and a conflict
    appended *after* a `drifted` verdict never overrides it.
    """
    placeholders = ", ".join("?" for _ in CUSTODY_STATUSES)
    rows = _query_events(
        db_path,
        "SELECT * FROM custody_events WHERE id IN "
        f"(SELECT MAX(id) FROM custody_events WHERE status IN ({placeholders}) "
        "GROUP BY item_id)",
        tuple(CUSTODY_STATUSES),
    )
    return {row["item_id"]: _from_row(row) for row in rows}


def latest_conflict_events(db_path: Path) -> dict[str, CustodyEvent]:
    """The most recent *import-conflict* event per item, keyed by item id (H275).

    The conflict-axis sibling of `latest_events`: where that reads the MAX(id) per
    item over the *verify verdicts* (`CUSTODY_STATUSES`) for the drift posture, this
    reads the MAX(id) per item over the `conflict` rows (`CONFLICT_STATUS`) for the
    `doctor` conflict aggregate (`custody.conflicts`). The two never mix — an import
    conflict is a distinct provenance-of-divergence axis (ADR 0104), so the drift
    posture and the conflict view fold disjoint ledger slices. A re-observed
    divergence (a higher-`id` conflict event) supersedes the earlier one, exactly as
    `latest_events` keeps the latest verify verdict. An item carrying *only* a
    conflict event appears here yet stays absent from `latest_events` (its drift
    posture reads `unverified` — never re-checked).
    """
    rows = _query_events(
        db_path,
        "SELECT * FROM custody_events WHERE id IN "
        "(SELECT MAX(id) FROM custody_events WHERE status = ? GROUP BY item_id)",
        (CONFLICT_STATUS,),
    )
    return {row["item_id"]: _from_row(row) for row in rows}


def unresolved_conflicts(
    items: list[ScrollItem], conflicts: dict[str, CustodyEvent]
) -> dict[str, CustodyEvent]:
    """Held items whose latest import-conflict is still unresolved (roadmap H275).

    A recorded conflict is *unresolved* while the latest `conflict` event's
    ``observed_hash`` (the incoming capture that disagreed) still differs from the
    held item's current ``content_hash`` — the divergence the importer surfaced has
    not been closed. Because the held copy is never auto-overwritten (ADR 0104; raw
    is sacred), every freshly recorded conflict is unresolved; the predicate is
    deliberately *resolution-aware* so a future `reconcile` (roadmap H276) that
    adopts the incoming content — the held hash becomes the observed hash — clears
    the item with **no** special "resolved" event, exactly the `latest_events`
    held-filter precedent (read the latest event, compare it to the current state).

    Held-filtered like the drift aggregate (`doctor._check_custody_drift`): a
    conflict on a since-deleted id is not this library's divergence, so an item
    absent from ``{item.id for item in items}`` is excluded — and, because ``items``
    may be a ``--source``-scoped slice, the conflict aggregate scopes by source for
    free (a held item owns a source, so the divergence is source-attributable).
    """
    by_id = {item.id: item for item in items}
    unresolved: dict[str, CustodyEvent] = {}
    for item_id, event in conflicts.items():
        item = by_id.get(item_id)
        if item is not None and event.observed_hash != item.content_hash:
            unresolved[item_id] = event
    return unresolved


def posture_from_status(status: str | None) -> str:
    """The reader-facing custody posture for a raw latest-verdict status.

    The status-level core of `drift_posture`: ``None`` (no verdict on the ledger)
    → ``unverified`` (never re-checked, so *unknown*, never silently "clean");
    an ``unchanged`` re-check → ``verified``; any other status
    (``drifted``/``rotted``/``error``) is itself the posture. Factored out so the
    posture rule keeps a single home whether folded in Python from a
    `CustodyEvent` (`drift_posture`, every browse surface) or called from SQL over
    a raw `custody_events.status` column (the ``scrolls_drift`` UDF behind
    `search --drift`, which must scope the *ranked* match before the LIMIT, so it
    cannot post-filter the Python-side `drift_posture`).
    """
    if status is None:
        return "unverified"
    return "verified" if status == "unchanged" else status


def drift_posture(event: CustodyEvent | None) -> str:
    """The reader-facing custody posture for an item, from its latest verdict.

    ``unverified`` when the ledger holds no verdict for the item — never
    re-checked, so *unknown*, never silently "clean" (the drift block's
    ``unverified`` honesty); otherwise the verdict mapped to a posture an agent
    reads directly: ``verified`` for an ``unchanged`` re-check, else the status
    itself (``drifted``/``rotted``/``error``). The single per-item derivation
    behind the shareable bundle's per-scroll posture marker (roadmap H42).
    Because `doctor`'s ``custody.drift`` aggregate counts the same
    `latest_events` per status (``unchanged`` → the bundle's ``verified``,
    ``unverified`` = held − verdicts), the per-scroll posture an agent reads and
    doctor's counts can never disagree. Delegates to `posture_from_status` so the
    SQL `scrolls_drift` filter reads the same rule.
    """
    return posture_from_status(event.status if event is not None else None)


def last_checked(event: CustodyEvent | None) -> str | None:
    """When an item was last verified — the `checked_at` of its latest verdict.

    The time-axis sibling of `drift_posture` over the *same* `latest_events`
    verdict: where `drift_posture` answers "has the source moved", this answers
    "as of when do we know that" (roadmap H84). ``None`` when the ledger holds no
    verdict for the item — never re-checked, so there is no timestamp to report
    (the honest-absence shape, the `null` counterpart of the ``unverified``
    posture `drift_posture(None)` returns; never a fabricated wall-clock time).
    The stored timestamp is reported verbatim, so it is deterministic and
    idempotent (the H21 posture — a row never shows a moving "x ago"), and it
    equals the `checked_at` of the head of the per-item `scrolls history` ledger
    by construction (both read the chronologically-latest event), so an agent
    can pick a `verify --stale-before <ISO>` boundary (H79) straight from a
    browse row.
    """
    return event.checked_at if event is not None else None


def unverified_items(
    items: list[ScrollItem], verdicts: dict[str, CustodyEvent]
) -> list[ScrollItem]:
    """The held items the custody ledger has *no* verdict for — ``held − verdicts``.

    The single "never re-checked" predicate behind both the *count* every custody
    surface reports as ``unverified`` (`doctor`'s ``custody.drift.unverified``,
    `facets drift`, and the scope custody headlines — all the
    `drift_posture(None)` items) and the *selection* `scrolls verify --unverified`
    re-checks, so a re-check clears exactly the bucket those surfaces flag — the
    report↔refresh convergence `classify --stale` (H27) and `kb --stale` (H31)
    have on the enrichment axes, now on the verify axis. ``verdicts`` is the
    `latest_events` ledger read keyed by item id; an item absent from it has never
    been verified, so its posture is ``unverified`` (unknown), never silently
    "clean". Preserves input order, so an oldest-saved-first caller can bound a
    re-check with a limit.
    """
    return [item for item in items if item.id not in verdicts]


def items_in_posture(
    items: list[ScrollItem], verdicts: dict[str, CustodyEvent], posture: str
) -> list[ScrollItem]:
    """The held items whose latest ledger drift posture is `posture`.

    The read-side selection behind `scrolls list --drift <posture>` (roadmap
    H54) — the browse-filter sibling of `unverified_items` (the verify-axis
    selection): where that names the one never-checked bucket `verify
    --unverified` acts on, this enumerates *any* posture's items, bucketed by the
    same `drift_posture` over the same `latest_events` ledger read `facets drift`
    and the scope custody headlines count. So the rows `list --drift X` returns
    are exactly the items `facets drift` tallies under `X` for the same scope —
    drill-from-the-count convergence by construction (`verified` ≡ ledger
    ``unchanged``; an item absent from `verdicts` is ``unverified``). Preserves
    input order, so an oldest-saved-first caller keeps that order. Note
    `unverified_items(items, v)` equals `items_in_posture(items, v, "unverified")`
    — kept distinct because the verify axis names its bucket by intent (the
    never-checked set to re-verify), not by the posture string.
    """
    return [item for item in items if drift_posture(verdicts.get(item.id)) == posture]


def items_checked_before(
    items: list[ScrollItem], verdicts: dict[str, CustodyEvent], boundary: str
) -> list[ScrollItem]:
    """The held items whose newest ledger verdict predates `boundary` — the
    *stale* set a time-bounded recheck targets.

    The act-side time window behind `scrolls verify --stale-before <ISO>`
    (roadmap H79), completing the `--since` family across all three custody
    surfaces: the per-item *read* (`history --since`, H71) and the *backup*
    (`export events --since`, H75) already window the ledger by time; this
    windows the *recheck* — "re-verify everything not seen since the last
    sweep".

    An item is stale when **either** the ledger holds no verdict for it (never
    re-checked, so trivially stale at any boundary) **or** its latest verdict's
    `checked_at` is strictly *before* `boundary`. The boundary itself is
    therefore *fresh*: an item last checked exactly at `boundary` is not stale.
    That makes this selection the exact complement of the
    ``checked_at >= boundary`` window `history --since` / `export events --since`
    keep, so a verdicted item is either fresh (at/after the boundary) or
    stale-before it, never both — and because a never-checked item is always in,
    `items_checked_before(items, v, <future>)` is a superset of
    `unverified_items(items, v)`: it subsumes the `--unverified` selection and
    adds the long-unchecked.

    `boundary` is a **pre-normalized** UTC ISO string (see `parse_since`, which
    the CLI edge calls), so the lexicographic `checked_at < boundary` compare is
    apples-to-apples with the stored timestamp. `verdicts` is the `latest_events`
    ledger read keyed by item id — the same read `unverified_items` /
    `items_in_posture` use. Preserves input order, so an oldest-saved-first
    caller can bound a recheck with a `--limit` and make monotone coverage
    progress (roadmap H55).
    """
    return [
        item
        for item in items
        if (event := verdicts.get(item.id)) is None or event.checked_at < boundary
    ]


def recheck_order(
    items: list[ScrollItem], verdicts: dict[str, CustodyEvent]
) -> list[ScrollItem]:
    """Order held items for a coverage-first bounded recheck (roadmap H55).

    `scrolls maintain`'s recheck is bounded by ``--limit``; left in list order it
    re-verifies the same already-checked head every pass and a ``--limit``-bounded
    run can never reach the never-checked tail — so a scheduled worker spins
    without ever improving custody *coverage*. This ordering fixes that:

    - the **never-checked** items first — exactly the `unverified_items` set
      (``held − verdicts``), in input order (oldest-saved-first when the caller
      passes `list_items`), so a bounded pass spends its budget on *new* coverage
      until every held item carries a verdict;
    - then the **already-verified** items oldest-verdict-first (ascending
      `checked_at`), so once coverage is complete the pass revisits the *stalest*
      item next. A just-rechecked item gets a fresh `checked_at`, falling to the
      back of the queue, so successive bounded passes cycle the whole library
      rather than re-checking one head — monotone coverage progress.

    The sort is **stable**: verdicts sharing a `checked_at` keep input
    (oldest-saved-first) order, so the ordering is deterministic, never a
    same-second accident — mirroring the `latest_events` same-second tie note.
    `verdicts` is the `latest_events` ledger read keyed by item id, the same read
    every selector here uses. An **empty ledger** leaves the input order
    untouched (every item is never-checked, so the verified tail is empty) — a
    fresh library's first maintenance pass behaves exactly as before this
    ordering existed. Reorders only; the returned list is a permutation of the
    input, so an *unbounded* recheck checks the same set with the same counts.
    """
    never_checked = unverified_items(items, verdicts)
    verified = [item for item in items if item.id in verdicts]
    verified.sort(key=lambda item: verdicts[item.id].checked_at)
    return never_checked + verified


def recheck_coverage(
    items: list[ScrollItem],
    verdicts: dict[str, CustodyEvent],
    checked_ids: Iterable[str] = (),
) -> dict[str, int]:
    """Recheck coverage over the verifiable held set — ``{verified, total}`` (H109).

    `scrolls maintain`'s recheck advances custody *coverage*: a bounded pass
    re-checks the never-checked items first (`recheck_order`, H55), so over
    successive passes every verifiable item comes to carry a verdict. This makes
    that progress visible in one report — of the held items that *can* be
    verified, how many now do — so a worker reads "N of M covered" directly
    instead of diffing the `unverified` count across runs.

    ``total`` is how many held items carry a baseline ``content_hash`` (the
    caller passes its hash-bearing set as `items`): a reference-only capture has
    no hash to diff a re-fetch against, so it is *unverifiable* and excluded from
    the denominator — coverage measures progress over what can actually be
    covered, and so can reach ``total`` (full coverage). ``verified`` is how many
    of those now carry a ledger verdict.

    **Post-recheck by construction.** An item is verified-after if it had a
    verdict *before* this pass (its id is in `verdicts`) **or** was re-checked
    *in* it (its id is in `checked_ids`). Folding this pass's `checked_ids` into
    the pre-read `verdicts` avoids a second ledger read — the recheck reads
    `latest_events` once — and keeps the figure consistent with the
    post-maintenance `doctor` audit, which runs after the recheck: ``verified``
    equals the drift block's ``checked``, and ``total − verified`` equals its
    ``unverified`` when every held item is hash-bearing. Both derive from the
    same `unverified_items` predicate (``held − verdicts``) doctor's
    ``custody.drift.unverified`` reports on, so coverage and the audit converge by
    construction. With no recheck (``--no-recheck``) `checked_ids` is empty and
    the figure is the current ledger coverage — a read, not the live edge.
    """
    checked = set(checked_ids)
    remaining = [
        item
        for item in unverified_items(items, verdicts)
        if item.id not in checked
    ]
    total = len(items)
    return {"verified": total - len(remaining), "total": total}


def tally_custody(
    pairs: Iterable[tuple[str, str]]
) -> dict[str, dict[str, int]]:
    """Canonical fidelity-tier / drift-posture counts from `(fidelity, drift)` pairs.

    The shape-and-count core every scope custody tally shares: it folds an
    iterable of already-derived ``(fidelity_tier, drift_posture)`` pairs into the
    ``{"tiers": …, "drift": …}`` maps, every tier/posture present in the canonical
    order (`FIDELITY_TIERS`/`DRIFT_POSTURES`) with zeros included, so the shape is
    stable for a renderer to filter. `custody_counts` derives the pairs from items
    + the ledger; the `scrolls search --stats` envelope (roadmap H98) derives them
    from each matched hit's own `fidelity`/`drift` fields (which equal the same
    primitives by the per-item parity, roadmap H58) — both feed this one tally, so
    the count is identical however the pairs were sourced.
    """
    tiers = {tier: 0 for tier in FIDELITY_TIERS}
    drift = {posture: 0 for posture in DRIFT_POSTURES}
    for fidelity, posture in pairs:
        tiers[fidelity] += 1
        drift[posture] += 1
    return {"tiers": tiers, "drift": drift}


def tally_custody_by_source(
    triples: Iterable[tuple[str, str, str]]
) -> dict[str, dict[str, dict[str, int]]]:
    """Per-source fidelity-tier / drift-posture counts from `(source, fidelity, drift)`.

    The `by_source` analogue of `tally_custody`: it groups already-derived
    ``(source, fidelity_tier, drift_posture)`` triples by source and folds each
    group through `tally_custody`, yielding a map from source name to that source's
    own ``{"tiers": …, "drift": …}`` tally, source keys in sorted order. It is the
    pairs-based sibling of `custody_counts_by_source` (which derives the triples
    from items + the ledger): the browse-stats `--stats` envelopes' `stats.custody`
    (`search`/`list`/`related`, roadmap H99/H98) and the always-on `works` stats
    block (roadmap H100) fold each matched hit/representation's own
    `source`/`fidelity`/`drift` fields — the same per-item parity (roadmap H58) their
    whole-scope `stats.custody` already folds — through this one helper, so the
    per-source split (roadmap H155) costs no ledger read beyond the one the
    whole-scope tally already does.

    Carries only the `{tiers, drift}` axes `tally_custody` produces — *not* the
    per-source `coverage` `custody_counts_by_source` adds — because the browse-stats
    `stats.custody` it rides under carries no whole-scope coverage either (the lean
    family shape, H98–H101): coverage counts strictly `content_hash`-bearing held
    items (`recheck_coverage`), which a `(fidelity, drift)` pair cannot recover (a
    raw-only capture is `full` yet hash-less), so it stays an audit/maintenance axis
    on the surfaces holding the items (`doctor`/`graph`, which fold the heavier
    `custody_counts_by_source`). Because every triple lands in exactly one source
    group and each group folds the same `tally_custody`, the per-source tallies sum
    to `tally_custody(...)` over the whole iterable by construction (the H104
    sum-to-whole posture, per the matched scope), and — for an uncapped whole-library
    scope — equal `doctor`'s `custody.by_source` on the tiers/drift axes. An empty
    iterable is the honest empty map.
    """
    groups: dict[str, list[tuple[str, str]]] = {}
    for source, fidelity, posture in triples:
        groups.setdefault(source, []).append((fidelity, posture))
    return {source: tally_custody(pairs) for source, pairs in sorted(groups.items())}


def custody_counts(
    items: list[ScrollItem], verdicts: dict[str, CustodyEvent]
) -> dict[str, dict[str, int]]:
    """Scope-level fidelity-tier and drift-posture counts over a set of items.

    The one tally behind every *scope* custody headline — `scrolls status` (the
    whole library), the shareable bundle briefing (roadmap H45), the `scrolls
    context` bundle (roadmap H47), and the `scrolls search`/`list --stats`
    envelope's `stats.custody` (roadmap H98). It counts the *same* `get_fidelity`
    and `drift_posture` each surface's per-item view uses (folding them through
    `tally_custody`), so a headline's totals equal its own entries by construction,
    and — for a whole-library, uncapped scope — equal `doctor`'s `custody.tiers` /
    `custody.drift` aggregate (with the documented `verified` ≡ ledger `unchanged`
    mapping; `unverified` = held − verdicts). `verdicts` is the `latest_events`
    ledger read keyed by item id; an item absent from it is `unverified`. Both maps
    carry every tier/posture in the canonical order
    (`FIDELITY_TIERS`/`DRIFT_POSTURES`), zeros included, so the shape is stable for
    a renderer to filter.
    """
    return tally_custody(
        (get_fidelity(item), drift_posture(verdicts.get(item.id))) for item in items
    )


def custody_counts_by_source(
    items: list[ScrollItem], verdicts: dict[str, CustodyEvent]
) -> dict[str, dict[str, dict[str, int]]]:
    """Per-source fidelity-tier / drift-posture counts + coverage (roadmap H104, H121).

    `custody_counts` grouped by `source`: a map from source name to that source's
    own `{"tiers": …, "drift": …, "coverage": …}` tally, source keys in sorted
    order. Used by `doctor`'s ``custody.by_source`` block (and the `maintain` report
    that faithfully reads it, H123) so the audit names *which* source's custody is
    weakest (most reference-only, most drifted) — the source to target a
    `verify --drift`/`media`/recapture at.

    Each entry carries the `{tiers, drift}` of `custody_counts` **plus** a per-source
    `coverage` ``{verified, total}`` (roadmap H121) — the per-source counterpart of
    the whole-library `drift.coverage` (H113): of that source's *verifiable*
    (hash-bearing) held items, how many carry a ledger verdict. A reference-only
    capture has no baseline hash to diff, so it is excluded from a source's
    denominator (coverage can reach full, never stuck below 100% on the unverifiable),
    and the same shared `recheck_coverage` primitive backs it as backs the
    whole-library figure — so the per-source coverage names *which* source is least
    *covered* (most never-checked), the coverage-axis counterpart of the drift the
    tiers/drift maps already surface.

    Because each group folds through the same `custody_counts` **and** the same
    `recheck_coverage`, the per-source tallies sum to `custody_counts(items, verdicts)`
    (the whole-library `custody` block) by construction — every item lands in exactly
    one source group, so summing the groups re-counts the whole library (the H50
    convergence posture, per source) — and the per-source coverage sums to the
    whole-library `recheck_coverage` over the hash-bearing held set. An empty scope is
    the honest empty map.
    """
    groups: dict[str, list[ScrollItem]] = {}
    for item in items:
        groups.setdefault(item.source, []).append(item)
    result: dict[str, dict[str, dict[str, int]]] = {}
    for source, members in sorted(groups.items()):
        counts = custody_counts(members, verdicts)
        counts["coverage"] = recheck_coverage(
            [m for m in members if m.content_hash], verdicts
        )
        result[source] = counts
    return result


# The drift postures that count as *actionable* custody loss — the sources a
# follow-up recheck/recapture targets. `verified`/`unverified`/`error` are not
# *confirmed* loss, so they do not flag a source — `drifted`/`rotted` do. (The
# same postures `maintain`'s attention flag has always keyed off; this is its
# canonical home now that the readable surfaces share the primitive, roadmap H159.)
_LOSS_POSTURES = ("drifted", "rotted")


def _source_loss(tally: dict[str, dict[str, int]]) -> int:
    """How many of a source's held items are confirmed drifted or rotted."""
    drift = tally.get("drift", {})
    return sum(drift.get(posture, 0) for posture in _LOSS_POSTURES)


def _attention_reason(tally: dict[str, dict[str, int]]) -> str:
    """A one-line reason naming the actionable loss that flagged a source.

    Lists only the non-zero loss postures (`drifted`/`rotted`) in canonical order —
    e.g. ``"2 drifted, 1 rotted"`` — never empty (a source is flagged only when its
    loss is non-zero), so the line is always self-describing.
    """
    drift = tally.get("drift", {})
    return ", ".join(
        f"{drift[posture]} {posture}" for posture in _LOSS_POSTURES if drift.get(posture)
    )


def weakest_source(
    by_source: dict[str, dict[str, dict[str, int]]],
    *,
    include_coverage: bool = True,
) -> dict[str, Any] | None:
    """The single source carrying the most actionable custody loss (roadmap H119/H159).

    The shared distillation behind every weakest-source `attention` flag: JSON
    `scrolls status` (H139) and `scrolls maintain` (H119/H137) thread it over
    `doctor`'s per-source breakdown, the readable `export bundle`/`scrolls context`
    briefings render it as an `_Attention:_` line (H159, via
    `render_custody_attention`) over the bundle scope's own `custody_counts_by_source`,
    and the `graph` (H164) + browse `search`/`list`/`related`/`works --stats` (H174)
    `stats.custody` blocks carry it over their own `by_source` map — so every
    surface's flag is *the same source, the same tally* by construction. It lives
    here, beside `custody_counts_by_source`, so the readable surfaces no longer reach
    into `maintain` for it (`maintain.weakest_source` re-exports this).

    Weakest = the most **actionable loss**: the most `drifted` + `rotted` items (the
    sources *confirmed* to have moved or gone — the set a follow-up
    `verify --drift`/`media` targets), tie-broken by the most `reference`-only items
    (lowest fidelity), then the source name (so the pick is deterministic). Returns
    ``{source, tiers, drift, coverage, reason, command}`` — the flagged source's own
    tally (so the per-source picture rides along, including the recheck ``coverage``
    ``{verified, total}`` H121 the tally already carries, roadmap H153 — a pure read
    of the same tally, **no new ledger read**, so it equals that source's
    `custody.by_source[<source>].coverage` by construction), a one-line reason naming
    the loss that earned the flag, and (roadmap H137) the **exact recheck command**
    (``scrolls verify --source <source>``, H125) — the bridge from naming the weakest
    source to the act.

    `include_coverage` (roadmap H174) governs the ``coverage`` member. The
    coverage-bearing surfaces (`status`/`maintain`/`doctor`/`graph`) feed a
    `custody_counts_by_source` map whose entries carry the per-source recheck
    ``coverage`` (H121), so the flag rides it along (the default). The **lean**
    browse-stats family (`search`/`list`/`related`/`works --stats`) folds a
    `tally_custody_by_source` map carrying only ``{tiers, drift}`` — a `(fidelity,
    drift)` pair cannot recover coverage (a raw-only capture is `full` yet hash-less),
    exactly why coverage stays an audit axis there (H155) — so those surfaces pass
    ``include_coverage=False`` to **omit** the member rather than emit a fabricated
    ``0/0`` a reader would misread as "nothing checked". A lean flag for a lean map:
    the honest projection, convergent with the coverage-bearing flag on every shared
    field (`source`/`tiers`/`drift`/`reason`/`command`).

    Honest absence (`None`), the same three gates as the JSON flag — so a surface's
    readable line is absent exactly when its JSON `attention` is:

    - an **empty** map — no library / no sources, nothing to flag;
    - a **single** source — no source *stands out*; the whole-scope custody headline
      already says everything `attention` could, which only adds value by
      discriminating *across* sources, so a one-source scope is null even with drift;
    - a **fully-clean** scope — no source carries any `drifted`/`rotted` loss, so
      there is nothing actionable to flag (reference-only is the normal capture
      posture, a tie-breaker, never a trigger on its own).
    """
    if len(by_source) < 2:
        return None
    source, tally = min(
        by_source.items(),
        key=lambda kv: (-_source_loss(kv[1]), -kv[1].get("tiers", {}).get("reference", 0), kv[0]),
    )
    if _source_loss(tally) == 0:
        return None
    flag: dict[str, Any] = {
        "source": source,
        "tiers": tally["tiers"],
        "drift": tally["drift"],
    }
    if include_coverage:
        # H153: the flagged source's recheck coverage (`{verified, total}`, H121)
        # rides along beside its tiers/drift — a pure read of the same tally (no
        # new ledger read), so it equals `doctor`'s per-source coverage by
        # construction. `.get` keeps the degrade-safe posture: an older/empty
        # schema without coverage reads the honest zero fraction, never a KeyError.
        flag["coverage"] = tally.get("coverage", {"verified": 0, "total": 0})
    # H137: the exact act to re-check this source — a recheck, not a repair.
    # Source slugs are single tokens (no shell-quoting needed).
    flag["reason"] = _attention_reason(tally)
    flag["command"] = f"scrolls verify --source {source}"
    return flag


def _fidelity_tokens(tiers: dict[str, int]) -> str:
    """The non-zero fidelity-tier counts in canonical order: ``full <a>, partial <b>``.

    The one fidelity-rendering primitive shared by the scope custody headline's
    ``fidelity`` section (`custody_sections`) and the standalone `_Fidelity:_`
    holdings line (`render_fidelity_holdings`, roadmap H212), so the leanest
    `index` budget tier and the `connected`+ headline emit byte-identical fidelity
    tokens — they cannot disagree on what fraction is held in full. Absent counts
    read as zero; an all-zero map is the empty string (no scope to report).
    """
    return ", ".join(
        f"{tier} {tiers.get(tier, 0)}" for tier in FIDELITY_TIERS if tiers.get(tier)
    )


def custody_sections(
    tiers: dict[str, int],
    drift: dict[str, int],
    coverage: dict[str, int] | None = None,
) -> list[str]:
    """The ` · `-joined ``fidelity …``/``drift …``/``coverage …`` sections of a custody line.

    The shared core behind both the scope headline (`render_custody_headline`) and
    the per-source breakdown (`render_custody_by_source`, roadmap H141): the
    *non-zero* fidelity tiers and drift postures in canonical order
    (`FIDELITY_TIERS`/`DRIFT_POSTURES`), each as ``<axis> <a> <i>, <b> <j>``. Both
    surfaces fold the same counts through this one helper, so a per-source line's
    sections read byte-identical to the scope headline's. Absent counts read as
    zero, so a partial mapping never crashes the renderer.

    `coverage` is the per-source recheck `coverage` ``{verified, total}`` the
    breakdown carries (roadmap H121/H158); when given, a trailing ``coverage V/T``
    section names how much of that source's verifiable held set is checked — the
    readable counterpart of the JSON `by_source[S].coverage`. Unlike the
    fidelity/drift sections (non-zero only), coverage is *always shown* when
    provided — even ``coverage 0/0`` for an all-reference source — so the section
    stays positionally stable across sources. The **scope headline passes no
    coverage** (`coverage is None` → no section), keeping the whole-scope
    `_Custody:_` line a posture summary, not a per-source triage signal (the
    H113/H103 boundary that kept coverage off `status`'s headline).
    """
    parts = []
    fidelity = _fidelity_tokens(tiers)
    if fidelity:
        parts.append(f"fidelity {fidelity}")
    drift_str = ", ".join(
        f"{posture} {drift.get(posture, 0)}"
        for posture in DRIFT_POSTURES
        if drift.get(posture)
    )
    if drift_str:
        parts.append(f"drift {drift_str}")
    if coverage is not None:
        parts.append(f"coverage {coverage.get('verified', 0)}/{coverage.get('total', 0)}")
    return parts


def render_custody_headline(
    n: int, tiers: dict[str, int], drift: dict[str, int]
) -> str:
    """Render the one-line custody headline from precomputed posture counts.

    ``_Custody: N scroll(s) · fidelity <tier counts> · drift <posture counts>._``
    — the shared *formatter* behind every scope custody headline. `custody_headline`
    derives the counts from items + the ledger; `maintain.snapshot_headline`
    (roadmap H103) maps a recorded doctor snapshot's drift axes into postures; both
    feed this one renderer, so a Markdown surface and the maintenance JSON report
    emit a byte-identical line. `tiers` is keyed by `FIDELITY_TIERS`, `drift` by
    `DRIFT_POSTURES` (`verified`, …); only the *non-zero* entries are shown in
    canonical order (each section still sums to `n` — every scroll has exactly one
    tier and one posture). An empty scope (`n == 0`) is the honest
    ``_Custody: 0 scroll(s)._`` with no sections. Absent counts read as zero, so a
    partial mapping never crashes the renderer.
    """
    parts = [f"{n} scroll(s)"] + custody_sections(tiers, drift)
    return "_Custody: " + " · ".join(parts) + "._"


def render_fidelity_holdings(tiers: dict[str, int], n: int) -> str:
    """Render the ledger-free `_Fidelity:_` holdings line for the leanest budget tier.

    ``_Fidelity: full <a>, partial <b>, reference <c> (of N)._`` — the fidelity-only
    counterpart of `render_custody_headline`, for the `scrolls context` `index` tier
    (roadmap H212), which reads no custody ledger at all. Fidelity is a *holdings*
    fact (`get_fidelity`, derived from stored fields), so it travels even at the
    leanest tier — *fidelity travels with every result* (vision principle 3). *Drift*
    is a ledger *claim*, so it is deliberately absent here: claiming a `verified` /
    `unverified` verdict over a ledger the tier never read would be the exact M2
    anti-fabrication violation (the leanest tier honestly states what it *holds*,
    never what it hasn't *checked*). The counts are the non-zero tiers in canonical
    order (`_fidelity_tokens`), exactly the tokens `render_custody_headline`'s
    ``fidelity`` section emits, so the `index` line and the `connected`+ headline
    converge by construction (roadmap H213). `n` is the scope size the counts sum to.
    An empty scope is the honest ``_Fidelity: 0 scroll(s)._`` — the defensive form;
    the context bundle returns early on no matches, so it is never reached there.
    """
    tokens = _fidelity_tokens(tiers)
    if not tokens:
        return "_Fidelity: 0 scroll(s)._"
    return f"_Fidelity: {tokens} (of {n})._"


def custody_source_breakdown(
    by_source: dict[str, dict[str, dict[str, int]]]
) -> list[tuple[str, int, list[str]]]:
    """Structured per-source custody breakdown for a readable briefing (roadmap H141).

    Maps a `custody_counts_by_source` map to an ordered list of
    ``(source, n, sections)`` — ``n`` the source's scroll count, ``sections`` its
    non-zero ``fidelity …``/``drift …`` strings **plus** a trailing
    ``coverage V/T`` (canonical order, the *same* `custody_sections` the scope
    headline folds, here with the source's per-source `coverage`, roadmap H158).
    Sources keep the sorted order `custody_counts_by_source` returns. Returns ``[]``
    when fewer than two sources are present: a single-source scope's split says
    nothing the scope headline doesn't, and an empty scope has none — the honest
    no-op a caller omits. The structured layer shared by the Markdown
    (`render_custody_by_source`) and HTML per-source renderers, so a surface's
    per-source line and the JSON `by_source` can never disagree — including the
    coverage section, which reads the same `coverage` already in the map (no new
    derivation/ledger read). An entry without a `coverage` member (a
    `tally_custody_by_source` browse-stats entry, which carries none) degrades to
    no coverage section.
    """
    if len(by_source) < 2:
        return []
    breakdown: list[tuple[str, int, list[str]]] = []
    for source, counts in by_source.items():
        tiers, drift = counts["tiers"], counts["drift"]
        sections = custody_sections(tiers, drift, counts.get("coverage"))
        breakdown.append((source, sum(tiers.values()), sections))
    return breakdown


def render_custody_by_source(
    by_source: dict[str, dict[str, dict[str, int]]]
) -> list[str]:
    """Markdown per-source custody breakdown lines under a scope headline (roadmap H141).

    A ``_By source:_`` lead-in then one bullet per source —
    ``- `<source>` — N scroll(s) · fidelity … · drift … · coverage V/T`` — the
    per-source counterpart of `render_custody_headline`, the same non-zero
    `custody_sections` per source plus the per-source recheck `coverage`
    (``V/T``, roadmap H158 — always shown so the section is positionally stable;
    the scope headline itself stays coverage-free). Returns ``[]`` for fewer than
    two sources (the `custody_source_breakdown` no-op), so a single-source/empty
    briefing omits the split entirely (the whole-scope headline already says
    everything). Shared by the `export bundle` briefing (H141), the `scrolls
    context` bundle (H149), and the compiled `library/` index + group pages
    (H145/H152), so the per-source line — coverage included — reads identically
    across surfaces and, because it folds the same `custody_counts_by_source`,
    sums to the scope headline and equals `doctor`'s `custody.by_source` for the
    same scope by construction.
    """
    breakdown = custody_source_breakdown(by_source)
    if not breakdown:
        return []
    lines = ["_By source:_", ""]
    for source, n, sections in breakdown:
        suffix = (" · " + " · ".join(sections)) if sections else ""
        lines.append(f"- `{source}` — {n} scroll(s){suffix}")
    lines.append("")
    return lines


def render_custody_attention(
    by_source: dict[str, dict[str, dict[str, int]]]
) -> list[str]:
    """The readable weakest-source `_Attention:_` line for a briefing (roadmap H159).

    The readable counterpart of the JSON `attention` flag `scrolls status`/`maintain`
    carry: one line naming the single source with the most actionable custody loss and
    the exact recheck command, so an agent skimming the `export bundle`/`scrolls
    context` briefing reads "this one source needs attention" without scanning the
    whole `_By source:_` map below it. Distilled by the shared `weakest_source`
    primitive over the *same* `custody_counts_by_source` the breakdown folds, so the
    line names the same source and tally as the JSON flag by construction:

        ``_Attention: source `<S>` carries the most drift (<reason>) — recheck with
        `scrolls verify --source <S>`._``

    where ``<reason>`` is the flagged source's non-zero loss postures (``2 drifted,
    1 rotted``), so the line is self-describing even for a rotted-only source.

    Returns ``[line, ""]`` (the line plus a trailing blank) so a caller splices it
    straight in above the `_By source:_` bullets. Returns ``[]`` on honest absence —
    exactly when `weakest_source` is `None` (empty, single-source, or fully-clean
    scope), the same no-op the JSON flag and the `_By source:_` split take — so a
    surface never shows an attention pointer it has no JSON counterpart for.
    """
    flagged = weakest_source(by_source)
    if flagged is None:
        return []
    line = (
        f"_Attention: source `{flagged['source']}` carries the most drift "
        f"({flagged['reason']}) — recheck with `{flagged['command']}`._"
    )
    return [line, ""]


def render_custody_refresh(
    enrichment_by_source: dict[str, int],
    summary_by_source: dict[str, int],
) -> list[str]:
    """The readable per-source `_Refresh:_` line for a briefing (roadmap H178).

    The *enrichment/summary*-axis counterpart of the drift `_Attention:_` line
    (H159): where `_Attention:_` names the source carrying the most drift and the
    `verify --source <S>` recheck, this names the source(s) whose classifications or
    summaries were produced under a superseded ruleset / changed membership, and the
    `classify --stale --source <S>` / `kb --stale --source <S>` *refresh* to run — so
    an agent skimming the `export bundle`/`scrolls context` briefing reads "this
    source's enrichment needs refreshing" without re-running `doctor`:

        ``_Refresh: classifications stale in `arxiv`, `web` — `scrolls classify
        --stale --source <S>`; summaries stale in `web` — `scrolls kb --stale
        --source <S>`._``

    The two maps are offending-source → stale-count (`classify
    .stale_classification_counts_by_source` / `kb_llm.stale_summary_counts_by_source`
    — the *same* builders `doctor`'s `custody.enrichment.by_source`/
    `custody.summaries.by_source` fold), so the sources this line names equal the
    audit's maps by construction. Only the axes that carry debt appear; the command
    is a ``--source <S>`` *template* (one run per named source).

    Unlike `_Attention:_` and the `_By source:_` split, this line has **no
    single-source gate**: refresh debt is per-source actionable work, not a
    cross-source comparison, so a single-source scope with stale enrichment still
    shows it (and the custody headline, which carries fidelity/drift but not
    enrichment freshness, would otherwise hide it). Returns ``[line, ""]`` so a
    caller splices it straight in; returns ``[]`` on honest absence — exactly when
    *both* maps are empty (no source carries refresh debt on either axis).
    """
    clauses = []
    if enrichment_by_source:
        sources = ", ".join(f"`{s}`" for s in enrichment_by_source)
        clauses.append(
            f"classifications stale in {sources} — "
            "refresh with `scrolls classify --stale --source <S>`"
        )
    if summary_by_source:
        sources = ", ".join(f"`{s}`" for s in summary_by_source)
        clauses.append(
            f"summaries stale in {sources} — "
            "refresh with `scrolls kb --stale --source <S>`"
        )
    if not clauses:
        return []
    return [f"_Refresh: {'; '.join(clauses)}._", ""]


def custody_headline(
    items: list[ScrollItem], verdicts: dict[str, CustodyEvent]
) -> str:
    """One Markdown line summarising how custody stands across a set of items.

    ``_Custody: N scroll(s) · fidelity <tier counts> · drift <posture counts>._``
    — the shared renderer behind every scope custody headline (the bundle
    briefing H45, the `scrolls context` bundle H47, the compiled `library/` pages
    H95/H96, the `scrolls maintain` report H103), so the surfaces emit a
    byte-identical line over the same `custody_counts` tally and can never
    disagree. Shows only the *non-zero* tiers/postures in canonical order (each
    section still sums to N — every scroll has exactly one tier and one posture);
    an empty scope is the honest ``_Custody: 0 scroll(s)._`` with no sections.
    """
    counts = custody_counts(items, verdicts)
    return render_custody_headline(len(items), counts["tiers"], counts["drift"])
