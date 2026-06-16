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

from scrolls.items import ScrollItem, get_fidelity
from scrolls.sources import FETCH_ADAPTERS, FetchError

CUSTODY_STATUSES = ("unchanged", "drifted", "rotted", "error")

# The custody-fidelity tiers in best-held-first order — the three `get_fidelity`
# returns. The canonical order every custody headline renders tiers in.
FIDELITY_TIERS = ("full", "partial", "reference")

# The drift postures in reading order — the five `drift_posture` returns.
# `verified` is the posture word for the ledger's `unchanged` status, so a
# headline's `verified` count equals `doctor`'s `custody.drift.unchanged` and
# `unverified` equals held − verdicts (the H42 convergence, lifted to a scope).
DRIFT_POSTURES = ("verified", "unverified", "drifted", "rotted", "error")

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


def item_history(db_path: Path, item_id: str) -> list[dict[str, str | None]]:
    """The full custody ledger timeline for one item, newest first.

    The read-surface form of the append-only events `verify` writes: every
    recorded check serialized through `event_payload`, newest first (the
    `item_events` order). An item the ledger has never checked yields ``[]`` —
    the honest-empty form (completeness G1), distinct from an *unknown* item,
    which the caller rejects as a could-not-check before reaching here. Pure
    over the ledger read; the single primitive `scrolls history` and the MCP
    `get_scroll_history` twin share, so they can never disagree.
    """
    return [event_payload(event) for event in item_events(db_path, item_id)]


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
    doctor's counts can never disagree.
    """
    if event is None:
        return "unverified"
    return "verified" if event.status == "unchanged" else event.status


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


def custody_counts(
    items: list[ScrollItem], verdicts: dict[str, CustodyEvent]
) -> dict[str, dict[str, int]]:
    """Scope-level fidelity-tier and drift-posture counts over a set of items.

    The one tally behind every *scope* custody headline — `scrolls status` (the
    whole library), the shareable bundle briefing (roadmap H45), and the
    `scrolls context` bundle (roadmap H47). It counts the *same* `get_fidelity`
    and `drift_posture` each surface's per-item view uses, so a headline's totals
    equal its own entries by construction, and — for a whole-library, uncapped
    scope — equal `doctor`'s `custody.tiers` / `custody.drift` aggregate (with the
    documented `verified` ≡ ledger `unchanged` mapping; `unverified` = held −
    verdicts). `verdicts` is the `latest_events` ledger read keyed by item id; an
    item absent from it is `unverified`. Both maps carry every tier/posture in the
    canonical order (`FIDELITY_TIERS`/`DRIFT_POSTURES`), zeros included, so the
    shape is stable for a renderer to filter.
    """
    tiers = {tier: 0 for tier in FIDELITY_TIERS}
    drift = {posture: 0 for posture in DRIFT_POSTURES}
    for item in items:
        tiers[get_fidelity(item)] += 1
        drift[drift_posture(verdicts.get(item.id))] += 1
    return {"tiers": tiers, "drift": drift}


def custody_headline(
    items: list[ScrollItem], verdicts: dict[str, CustodyEvent]
) -> str:
    """One Markdown line summarising how custody stands across a set of items.

    ``_Custody: N scroll(s) · fidelity <tier counts> · drift <posture counts>._``
    — the shared renderer behind every scope custody headline (the bundle
    briefing H45, the `scrolls context` bundle H47), so the surfaces emit a
    byte-identical line over the same `custody_counts` tally and can never
    disagree. Shows only the *non-zero* tiers/postures in canonical order (each
    section still sums to N — every scroll has exactly one tier and one posture);
    an empty scope is the honest ``_Custody: 0 scroll(s)._`` with no sections.
    """
    counts = custody_counts(items, verdicts)
    parts = [f"{len(items)} scroll(s)"]
    fidelity = ", ".join(
        f"{tier} {counts['tiers'][tier]}"
        for tier in FIDELITY_TIERS
        if counts["tiers"][tier]
    )
    if fidelity:
        parts.append(f"fidelity {fidelity}")
    drift = ", ".join(
        f"{posture} {counts['drift'][posture]}"
        for posture in DRIFT_POSTURES
        if counts["drift"][posture]
    )
    if drift:
        parts.append(f"drift {drift}")
    return "_Custody: " + " · ".join(parts) + "._"
