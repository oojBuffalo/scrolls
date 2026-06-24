"""The scope/completeness envelope — G2 honest scope + truncation (MVP M2).

`docs/cli.md` → "The completeness contract" G2 promises that a scoped or
`--limit`-capped result lets a reader holding *only the result* recover the
scope it covered and whether it was truncated below the cap. The bare result
array (the G1-locked default) cannot carry that, so the self-describing form
an agent opts into (`scrolls search --stats`, `scrolls list --stats`) wraps
the array in this `{scope, stats, results}` envelope — the same `stats`
companion shape `scrolls works`/`graph` already emit (custody-vision §6).

Pure and presentation-free: it frames an already-serialized result list with
the facts the call knows (which filters it honored, how many matched, how
many it returned), and never touches the store. That keeps the truncation
arithmetic — the one load-bearing claim — trivially testable in isolation.
"""

from __future__ import annotations

from typing import Any


def scope_envelope(
    results: list[dict[str, Any]],
    *,
    scope: dict[str, Any],
    matched: int,
    custody: dict[str, Any] | None = None,
    strength: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap `results` in the scope-honest `{scope, stats, results}` envelope.

    `scope` is the call's parameters (e.g. `query`, `source`, `limit`); a
    `None` value means *that facet was not applied* and is pruned, so the
    echoed scope names exactly the filters honored — never a facet the call
    left open. An **empty-string** value survives, because `category=""` is
    the meaningful "unclassified pool" selector (mirroring `list`/`set`), not
    an absent filter.

    `stats.matched` is the total in scope *before* the cap; `stats.returned`
    is how many this result carries; `truncated` is true exactly when the cap
    hid matches (`matched > returned`). An empty result is therefore never
    "truncated" and still names its scope, so "nothing in *this* slice" can
    never be misread as library-wide absence.

    `custody`, when given, is the `custody.custody_counts` tally over the
    *matched* scope (the full match set, not just the returned page) — added to
    `stats.custody` so a reader paging results sees "of the N that matched, how
    much is held in full and how much has drifted" without a second `facets`
    call (roadmap H98, the browse-surface counterpart of the `graph`
    `stats.custody` block). It counts the same matched set `stats.matched`
    totals, so the tier/posture counts sum to `matched`. Omitted (no
    `stats.custody` key) when the caller passes nothing, so surfaces that do not
    opt in — `related`/`works` — keep the lean stats shape. The framer is agnostic
    to the tally's inner shape: a caller folding a per-source `by_source` split into
    the `custody` dict (roadmap H155) rides through `stats.custody` intact, no
    envelope change.

    `strength`, when given, is the `search.tally_strength` histogram over the same
    *matched* scope (roadmap H313): `{strong, moderate, weak}` counts of each hit's
    `match_strength`, added to `stats.strength` beside `stats.custody` so a reader
    sees not just *how much* matched but the *rank-quality* distribution of it (how
    many matched on a title vs only a body) without a second call. It partitions the
    matched scope, so the band counts sum to `stats.matched` (the drill-from-strength
    tie behind `--strength`, H314). Omitted when the caller passes nothing — the
    rank-quality tally is a `search`-only axis (only a search hit has a
    `match_strength`), so `list`/`related`/`works` keep the lean stats shape.
    """
    returned = len(results)
    applied = {key: value for key, value in scope.items() if value is not None}
    stats: dict[str, Any] = {
        "returned": returned,
        "matched": matched,
        "truncated": matched > returned,
    }
    if custody is not None:
        stats["custody"] = custody
    if strength is not None:
        stats["strength"] = strength
    return {
        "scope": applied,
        "stats": stats,
        "results": results,
    }
