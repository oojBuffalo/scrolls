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
    """
    returned = len(results)
    applied = {key: value for key, value in scope.items() if value is not None}
    return {
        "scope": applied,
        "stats": {
            "returned": returned,
            "matched": matched,
            "truncated": matched > returned,
        },
        "results": results,
    }
