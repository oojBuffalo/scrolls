# 0105: A reviewed `reconcile` resolution affirms the held copy by recording a `resolved` conflict-axis event — the operator act on a recorded import conflict

Date: 2026-06-22

Status: accepted

## Context

The conflict-on-import theme reached its **act** leg. Detection ships
(ADR 0104, roadmap H272–H274): a divergent re-import of a held id is recorded as
a typed `conflict` custody event (`prior_hash` = the kept held copy,
`observed_hash` = the incoming capture that disagreed). The read leg ships
(roadmap H275/H277): `doctor`'s `custody.conflicts` aggregate and the readable
`_Conflicts:_` briefing line fold the *resolution-aware* `unresolved_conflicts`
predicate — a conflict is **unresolved** while the latest conflict event's
`observed_hash` still differs from the held copy's current `content_hash`.

But there was **no operator path to resolve** a recorded conflict. The held copy
is always kept (raw is sacred — custody §2.4; ADR 0104), so every recorded
conflict stays unresolved forever, and `doctor`/the `_Conflicts:_` line flag it
indefinitely. An operator who has reviewed a divergence — "I merged a peer's
bundle, our captures of this id differ, I have looked and **my** copy is the one
I want" — had no way to record that decision and clear the alarm.

H275 framed the future resolution as the obsidian *surface, don't rewrite*
posture's final move: *choose a winner, record the supersession, never destroy
the prior capture.* The slice that adds it (roadmap H276) must resolve two
design questions:

> **(1)** Which resolutions can ship from data already in hand, and which need
> more than the ledger holds?
>
> **(2)** How is a "keep the held copy" decision *recorded* so it clears the
> resolution-aware predicate — given that keep-held does **not** change the held
> `content_hash` the predicate compares against?

## Decision

### Ship `--keep-held`; defer `--accept-incoming` (the ledger stores hashes, not the incoming content)

The two reconcile directions are **not** symmetric in what they require:

- **`--keep-held`** affirms the held copy as authoritative. It needs nothing
  beyond data already in hand — the held copy stays, and the operator's decision
  is recorded. **Shipped.**

- **`--accept-incoming`** would adopt the peer's capture — *re-render from the
  incoming content*, recording a supersession that keeps the prior content
  recoverable. But the conflict event records only **hashes**
  (`prior_hash`/`observed_hash`), never the incoming *content*: the importer
  computed the incoming `content_hash`, surfaced the divergence, and discarded
  the incoming bytes (the held copy was never overwritten). At `reconcile` time
  the incoming content is **gone**, so accept-incoming genuinely requires
  **re-supplying** it (a re-import with an accept flag, or a content-bearing
  conflict record) plus the custody-safe prior-content archival ADR 0098
  deferred as "re-capture-on-accept". That is a separate, heavier slice — the
  first import-path *write that can change a held capture*. **Deferred.**

This is an honest scope boundary, not an arbitrary one: keep-held is complete
from the ledger, accept-incoming is blocked on content the ledger does not hold.
Shipping keep-held alone is a complete, custody-safe vertical slice — the safe
direction of the operator decision — and establishes the `reconcile` command and
the resolution event the accept-incoming slice will reuse.

### Record keep-held as a `resolved` conflict-axis event that *supersedes* the conflict

The resolution-aware predicate (`unresolved_conflicts`, H275) clears a conflict
when the latest conflict event's `observed_hash` equals the held copy's current
`content_hash`. That **hash mechanism** is exactly right for a future
accept-incoming (the held hash *becomes* the observed hash → cleared with no
special event, as H275 anticipated). But it **cannot** clear a keep-held: the
held hash is unchanged, so `observed_hash != content_hash` holds forever. A
keep-held therefore needs an **explicit recorded decision**.

We introduce **`custody.RESOLVED_STATUS = "resolved"`**, a second status on the
**conflict axis** (`CONFLICT_AXIS_STATUSES = (CONFLICT_STATUS, RESOLVED_STATUS)`),
and the pure builder **`custody.resolution_event(item_id, *, held_hash,
incoming_hash, now)`** (deterministic given `now`, exactly like `conflict_event`
/ `verify_item`): `prior_hash` = the held copy's hash (the affirmed winner, kept,
never overwritten), `observed_hash` = the rejected incoming hash, status =
`RESOLVED_STATUS`, so `history --status resolved` is self-describing ("I kept
`prior_hash`, rejected `observed_hash`").

The supersession is a single-read fold, mirroring how a re-observed conflict
supersedes an earlier one:

- **`latest_conflict_events`** now takes the `MAX(id)` per item over the
  **conflict axis** (`status IN (conflict, resolved)`), not the `conflict` rows
  alone — so the latest decision (a higher-`id` `resolved`, or a fresh higher-`id`
  `conflict` that re-opens) wins.

- **`unresolved_conflicts`** keeps an item only when its latest conflict-axis
  event is **still an open `conflict`** (`event.status == CONFLICT_STATUS and
  event.observed_hash != item.content_hash`). A `resolved` latest event is
  skipped on the status gate (regardless of its hashes); a `conflict` whose
  incoming hash now matches the held copy is skipped on the hash gate (the
  accept-incoming mechanism). Both clearing paths coexist.

- **`current_conflict(db_path, item)`** is the per-item reconcile target: it
  folds the *same* `unresolved_conflicts` over `latest_conflict_events`,
  restricted to one item, so what `reconcile` acts on is exactly what
  `doctor`'s `custody.conflicts` and the `_Conflicts:_` line count
  (convergence by construction — no second definition of "open conflict").

Because every conflict read folds `unresolved_conflicts` over
`latest_conflict_events`, the resolution propagates to **every** surface for
free: `doctor`'s `custody.conflicts` (and its MCP `get_library_health` twin),
both `export bundle` forms' and `scrolls context`'s `_Conflicts:_` line all drop
the resolved item with no per-surface change.

### Drift isolation preserved; append-only; CLI-only

`RESOLVED_STATUS` is outside `CUSTODY_STATUSES`, and `latest_events` (the drift
read) folds only the verify verdicts — so a `resolved` event rides the per-item
`scrolls history` timeline and the conflict axis but **never** enters the drift
posture, exactly the isolation ADR 0104 built for `conflict`. `LEDGER_STATUSES =
CUSTODY_STATUSES + CONFLICT_AXIS_STATUSES`, so `history --status resolved`
(CLI + MCP) is a first-class read.

The original `conflict` event is **never removed** (append-only) — `history
--status conflict` always shows the divergence happened; the resolution is a
*new* row, not an edit. The held content is **never touched**. The command is
**CLI-only** for this slice, like `verify`: a write that changes the custody
posture should be an explicit operator act (custody §2.4), not an ambient MCP
capability. It is **idempotent** (a second `reconcile --keep-held` on an
already-resolved item is a no-op — the latest axis event is `resolved`, so
`current_conflict` returns `None`) and **dry-run-able** (`--dry-run` returns the
same decision payload the live run would but writes nothing — the H245/H273
"predict the write effect" discipline). A genuinely new divergent import after a
resolution appends a fresh `conflict` event (higher `id`) and **re-opens** the
alarm — correct, because it is new evidence of a new disagreement.

No schema change (the v7 `custody_events` table holds the two-hash slot and an
unconstrained `status` column), no network — a deterministic ledger append.

## Consequences

- The conflict axis now carries **two** event kinds — `conflict` (a peer's
  capture disagreed, recorded at import) and `resolved` (the operator affirmed
  the held copy, recorded at reconcile) — sharing one storage, one serializer,
  and the export/import round-trip, while the drift axis stays untouched. An
  operator's resolution decision is now durable, queryable
  (`history --status resolved`), and travels in bundles.

- `doctor`'s `custody.conflicts.items`, the `_Conflicts:_` briefing line, and the
  MCP twin all clear a reconciled item automatically (the shared predicate), so
  the detection → read → **resolve** arc closes: an operator reads the count,
  reviews the per-item `history`, runs `reconcile <id> --keep-held`, and the
  alarm drops — with the divergence still on the timeline for the record.

- The conflict-on-import theme is now complete on the keep-held direction across
  detect → read → resolve. The remaining work is **`--accept-incoming`** (a
  re-import-driven, content-bearing supersession with prior-content archival —
  the first held-capture write) and an **MCP `reconcile` twin**, both deferred.

- Verified offline: `tests/test_custody.py` (the `resolution_event` shape +
  serializer round-trip, a `resolved` event excluded from the drift posture,
  `latest_conflict_events` returns the resolution when it is latest,
  `unresolved_conflicts` clears after a resolution and re-opens on a fresh
  conflict, `current_conflict`); `tests/test_cli.py` (`reconcile --keep-held`
  resolves a recorded conflict and clears `doctor`'s aggregate while the held
  copy is untouched, idempotent re-run, `--dry-run` predicts without recording,
  a missing resolution flag is exit 2, an unknown id is exit 1, a held item with
  no conflict is an honest no-op, the `conflict` row survives on `history` beside
  the new `resolved` row).

## Deferred

- **`--accept-incoming`.** Adopting the peer's capture needs the incoming
  *content* (re-supplied), a custody-safe content replacement that keeps the
  prior capture recoverable, and a `superseded` event distinct from `resolved`.
  The first import-path write that can change a held capture — opt-in,
  dry-run-able, idempotent — on its own slice.

- **An MCP `reconcile` twin.** A custody-changing write is operator-gated for
  now (custody §2.4); the read side already travels over MCP
  (`get_library_health`'s `custody.conflicts`).

- **Bi-temporal storage.** The `resolved` event records *decided-at* via
  `checked_at` and the two hashes; a richer schema stays deferred (ADR 0102/0104)
  unless a workflow shows the event record insufficient.
