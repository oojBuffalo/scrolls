# 0104: An import conflict is a recorded custody event — a distinct provenance-of-divergence axis, excluded from the drift posture

Date: 2026-06-22

Status: accepted

## Context

The conflict-on-import theme (roadmap H272/H273) made the **lossless** importers
(`scrolls import items` and `scrolls import bundle`) custody-honest about a
collision: when a held id is re-imported with a *different* captured
`content_hash` — another library's bundle, a peer's `export items` of a source
that has since drifted — `items.merge_item` keeps the `INSERT OR IGNORE`
guarantee (the held copy is never overwritten) but classifies the skip as a
`conflict` instead of swallowing it into an opaque `skipped` count. The diverging
ids are surfaced in a structured `conflicts` field and a loud stderr warning
(`_warn_conflicts`); the bundle importer's `--dry-run` even *predicts* the
conflict set the live merge would surface.

But a surfaced conflict left **no durable trace**: re-run the import and the
divergence is re-detected from scratch, never queryable via `scrolls history
<id>`. Custody §2.4 (and ADR 0098's event model) holds that drift/conflict is a
*recorded event*, not just a printed warning — "another capture of this id
disagreed with mine, observed at import time" should join the ledger the way a
`verify` drift verdict does. The slice that records it (roadmap H274) must
resolve one design question:

> Is an import-conflict the **same** custody axis as a verify-drift (one ledger,
> one `drift_posture`) — or a **distinct** provenance-of-divergence axis (a
> sibling event type)?

## Decision

**An import conflict is a distinct provenance-of-divergence axis.** It is
recorded as a typed `conflict` event in the same append-only `custody_events`
ledger ADR 0098 introduced — so it rides the per-item `scrolls history` timeline
— but it is **deliberately excluded from the drift posture**.

The reasoning is the M2 anti-fabrication honesty. The drift axis answers *"has
the live **source** drifted away from, or rotted out from under, what we
captured?"* — and the only honest way to know that is to **re-capture through the
adapter** (`verify`), which is exactly what ADR 0098 built. An import conflict
involves **no source re-capture at all**: we learn only that a *peer's* capture
of the same id disagrees with ours. Mapping that into `drifted` would claim the
source moved when we have no such evidence — precisely the fabrication the M2
contract forbids. So the two axes share a ledger and a serializer, but not a
posture.

Concretely:

- **`custody.CONFLICT_STATUS = "conflict"`** is a new event status, *outside* the
  four verify verdicts `CUSTODY_STATUSES`. `LEDGER_STATUSES = CUSTODY_STATUSES +
  ("conflict",)` is the full set of statuses a ledger row may carry; the
  `scrolls history --status` filter (CLI + MCP `get_scroll_history`) validates
  against this superset, so `history --status conflict` is a first-class read.

- **`custody.conflict_event(item_id, *, held_hash, incoming_hash, now)`** builds
  the event — pure and deterministic given `now`, exactly like `verify_item`. It
  reuses the verify-event field semantics verbatim: `prior_hash` = the held copy's
  hash (what we keep, never overwritten), `observed_hash` = the incoming capture
  that disagreed. So `event_payload` / `event_export_dict` / the export→import
  round-trip carry it with **no special-casing**, and a conflict event
  round-trips losslessly through `export events` / `import bundle` like any other.

- **`latest_events` reads only the verify verdicts.** It now takes the `MAX(id)`
  per item over rows `WHERE status IN (CUSTODY_STATUSES)`, so a conflict event
  never becomes a `drift_posture`. The blast-radius isolation is total: every
  surface that folds `latest_events` (`doctor`'s `custody.drift`, `list/search
  --drift`, the scope custody headlines, `works`' aggregate, `weakest_source`,
  `maintain`) is unaffected by a conflict event. An item carrying *only* a
  conflict event reads `unverified` (never re-checked); a conflict appended
  *after* a real `drifted` verdict never masks it.

- **The recording lives in the shared `cli._merge_items`** — the one live,
  writing path both lossless importers route through — so `import items` and
  `import bundle` get it for free. The read-only `_preview_merge_items` (the
  bundle `--dry-run` twin) deliberately does **not** record: a dry-run predicts
  and warns but writes nothing, the ledger included. A clean import records
  nothing (`record_events` no-ops on the empty list), so only a genuine
  divergence leaves a trace — the append-only honesty of the verify ledger, now
  on the conflict axis. Each conflict observation appends an event (matching
  `verify`'s append-on-each-check posture), so the timeline records *when* a peer
  disagreed; `import events`' content-dedup keeps a re-imported backup idempotent.

No schema change (the v7 `custody_events` table already holds the two-hash slot),
no network — a deterministic content-hash compare, scoped to the lossless
importers where `content_hash` is model-complete.

## Consequences

- The custody ledger now records *two kinds* of divergence with one storage and
  one set of serializers: a **verify-drift** (the live source moved, from a
  re-capture) and an **import-conflict** (a peer's capture disagreed, from a
  merge). Both are queryable per-item via `scrolls history`, filterable by
  `--status`, and travel in `export events` / bundle exports; only the verify
  verdicts drive the drift posture. This is the bi-temporal *captured-at vs
  source-changed-at* signal ADR 0102 framed as a concept — now grounded by a
  concrete workflow (merging a peer's bundle) without a bi-temporal schema.

- The decision keeps the drift axis's meaning intact: `doctor`'s
  `custody.drift.drifted` still counts only sources *confirmed* moved by a
  re-capture, and the weakest-source `_Attention:_` flag still points at `verify
  --source <S>` (a recheck), never conflating "a peer disagreed" with "the source
  drifted". A conflict is reported, never repaired and never an overwrite — the
  held copy is provably untouched (custody §2.4).

- Verified offline: `tests/test_custody.py` (the `conflict_event` shape +
  serializer round-trip, `latest_events` excludes a lone conflict event, a
  conflict appended after a drift never overrides the drift posture, `history
  --status conflict` filtering against `LEDGER_STATUSES`); `tests/test_cli.py`
  (`import items` records a conflict event readable via `scrolls history` while
  `doctor`'s drift block stays empty, a clean re-import records nothing);
  `tests/test_bundle.py` (`import bundle` records via the shared `_merge_items`,
  the `--dry-run` records nothing).

## Deferred

- **A reviewed `reconcile` resolution.** Recording a conflict is *detection*; an
  explicit operator path to choose a winner (re-render from the incoming capture,
  recording the supersession) is the heavier, separate decision ADR 0098 already
  deferred for `verify` ("re-capture-on-accept"). The conflict event gives that
  future slice a queryable home to act on.

- **A `doctor` conflict aggregate.** ~~`doctor` aggregates verify drift into
  `custody.drift`; a parallel `custody.conflicts` roll-up (how many items carry an
  unresolved import conflict) is a natural next read but waits on a workflow that
  needs the scope-level count rather than the per-item `history`.~~ **Shipped
  (roadmap H275).** `scrolls doctor` (and the MCP `get_library_health` twin, for
  free) now carries `custody.conflicts` `{basis, as_of, items, events}` — the
  read-aggregate sibling of `custody.drift`. A conflict is counted **unresolved**
  while the *latest* conflict event's `observed_hash` still differs from the held
  copy's current `content_hash` (the resolution-aware predicate: a future
  `reconcile` that adopts the incoming content clears it with no special "resolved"
  event — the `latest_events` held-filter precedent). Held-filtered and
  `--source`-scopable like the drift block; a **report view only**, never
  `issues`/`fixed`/the exit code. `latest_conflict_events` reads only the `conflict`
  rows and `latest_events` only the verify verdicts, so the two axes stay disjoint
  by construction. A readable `_Conflicts:_` briefing line is the next adjacent read.

- **Bi-temporal storage.** The event records *observed-at-import* via `checked_at`
  and the two hashes; a richer captured-at vs source-changed-at schema stays
  deferred (ADR 0102) unless an agent workflow shows the event record
  insufficient.
