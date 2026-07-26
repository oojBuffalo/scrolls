# Reconciliation in Scrolls

**Status:** Initial design. This is the foundation for the Reconcile stage in the Scrolls pipeline.

## Goals

- Collapse multiple representations of the same intellectual work into one canonical item.
- Detect and handle duplicates gracefully.
- Infer and maintain typed relationships between items.
- Produce explainable, auditable results.
- Be re-runnable without destroying user data.

## Core Concepts

### Work
A "Work" is the canonical intellectual object (e.g., a specific research paper, a specific GitHub repository, a specific YouTube video).

### Representation
A "Representation" is one saved form of a Work (e.g., the arXiv preprint, the PubMed record, the published DOI version, the GitHub mirror).

### Canonical Item
One primary `ScrollItem` that represents the Work. Other representations link to it.

## Proposed Data Model Additions

New tables / relationships (to be implemented incrementally):

- `works` table: canonical work id, primary title, primary source, quality score, created_at, updated_at
- `work_representations`: work_id, item_id, representation_type, confidence, is_canonical
- `work_relationships`: from_work_id, to_work_id, relationship_type (cites, extends, same_as, derived_from, etc.), confidence, provenance

Existing `items` table gains:
- `work_id` (nullable FK)
- `is_canonical` boolean
- `reconciliation_state` enum (pending, reviewed, merged, conflict)

## CLI Surface (Proposed)

```bash
scrolls reconcile                    # run reconciliation on the whole library
scrolls reconcile --dry-run          # show what would change
scrolls reconcile --item <id>        # reconcile a specific item
scrolls reconcile --since 7d         # only consider recently added items
scrolls works list                   # list canonical works
scrolls works show <work-id>         # show a work and all its representations
scrolls works merge <work-id>        # manually force a merge (with confirmation)
```

MCP tools should expose equivalent capabilities.

## First Implementation Slice (Recommended)

1. Add the `work_id` column and basic indexes.
2. Implement a simple `reconcile --dry-run` that detects obvious duplicates by DOI / canonical URL / title+author fingerprint.
3. Create a basic `works` table and populate it for items that have clear canonical signals (DOI, arXiv id, GitHub repo, etc.).
4. Add `scrolls reconcile --dry-run` command + tests.
5. Expose basic reconciliation state via `scrolls doctor` and source pages.

This gives us a foundation without over-committing to a complex engine immediately.

## Open Questions

- How aggressive should automatic merging be vs requiring human review?
- What is the confidence threshold for auto-merging?
- How do we handle conflicting metadata across representations?
- Should reconciliation run automatically after ingest, or only on demand?

These will be answered in subsequent slices with real usage data.

## Shipped: conflict-on-import detection (the custody-safe reconcile surface)

The obsidian-second-brain inspiration (`docs/agents/obsidian-second-brain-inspiration.md`,
the `/obsidian-reconcile` row) sharpened the reconcile posture: **keep the
detection, replace auto-overwrite with surfacing a conflict for review — surface,
don't silently rewrite.** The first concrete enactment of that posture is at the
**import boundary**, where two libraries' captures actually collide.

**Both lossless importers** — `scrolls import items` (H272) and `scrolls import
bundle` (H273) — no longer treat a skipped row as opaque. Every row goes through
`items.merge_item`, which keeps the `INSERT OR IGNORE` custody guarantee (the held
copy is never overwritten) but classifies the skip on the `content_hash` — the
same captured-content fingerprint the verify ledger drifts on (ADR 0098):

- `unchanged` — the held copy has the same content (an idempotent re-import).
- `conflict` — the held copy has *different* captured content for the same id (a
  divergent capture — exactly the "conflicting metadata across representations"
  question above, observed at merge time). The held copy is kept; the diverging
  ids are surfaced in the structured `conflicts` field **and** a loud stderr
  warning, so the divergence is a recorded, reviewable event — never silently
  swallowed into a `skipped` count, and never an overwrite (vision §2.4).

This is reconciliation *detection* made custody-safe: it answers "these two
captures of the same id disagree" without choosing a winner or rewriting anything.
On the bundle importer the `--dry-run` preview also **predicts** the conflict set
the live merge would surface (the same `content_hash` compare, simulated without
writing), so an operator merging a peer's bundle can review the divergences before
committing — and a within-bundle duplicate that disagrees with itself classifies
identically on both paths (H273).

### Shipped: a conflict is a recorded custody event (H274, ADR 0104)

A surfaced conflict is no longer just a transient warning the next import
re-detects from scratch: it now **joins the append-only custody ledger** (ADR
0098) as a typed `conflict` event on the held item, queryable on the per-item
`scrolls history` timeline (`scrolls history <id> --status conflict`). The event
carries `prior_hash` = the held copy we keep and `observed_hash` = the incoming
capture that disagreed, stamped at import time — "another capture of this id
disagreed with mine, observed at import time" (the bi-temporal captured-at vs
source-changed-at signal, now grounded by the concrete merge-a-peer's-bundle
workflow). It rides the shared `cli._merge_items`, so both lossless importers
record it for free; the bundle `--dry-run` predicts the conflict but, being
read-only, records nothing.

The design decision ADR 0104 resolves: an import conflict is a **distinct
provenance-of-divergence axis**, *not* a verify-drift. The drift axis means "the
live **source** moved" — known only by re-capturing through the adapter
(`verify`); an import conflict involves no source re-capture, only a peer
disagreeing, so claiming the source `drifted` would be fabrication (the M2
honesty). The isolation is total: `custody.latest_events` reads only the verify
verdicts, so a `conflict` event never enters the drift posture — `doctor`'s
`custody.drift`, `list/search --drift`, the scope headlines and `works` aggregate
are all unaffected, an item with only a conflict reads `unverified`, and a
conflict appended after a real `drifted` verdict never masks it.

Tested: `test_conflict_event_records_held_vs_incoming_hash`,
`test_conflict_event_is_excluded_from_the_drift_posture`,
`test_a_conflict_appended_after_a_drift_never_overrides_it`, and
`test_item_history_status_filters_to_conflict_events` in `tests/test_custody.py`;
`test_import_items_records_a_conflict_as_a_custody_event` and
`test_import_items_clean_reimport_records_no_event` in `tests/test_cli.py`;
`test_import_bundle_records_a_conflict_as_a_custody_event` and
`test_import_bundle_dry_run_records_no_conflict_event` in `tests/test_bundle.py`.
The earlier *surface, don't overwrite* primitive remains tested by
`test_import_items_surfaces_a_content_conflict` and siblings in
`tests/test_cli.py`; `test_import_bundle_surfaces_a_content_conflict` and the
dry-run-prediction / within-bundle-dup siblings in `tests/test_bundle.py`.

## Shipped: a `doctor` scope-level conflict aggregate (H275, ADR 0104)

Recording each conflict per-item (H274) gives a queryable per-item history, but
an operator who merged several peer bundles had **no library-scope view** — no
way to ask "how many of my held items carry an unresolved import conflict, and
which?" without scanning every item's `history`. `scrolls doctor` now carries a
`custody.conflicts` block — the **read-aggregate sibling of `custody.drift`**,
over the *other* provenance-of-divergence axis:

```jsonc
"conflicts": {
  "basis": "import_ledger",   // read from the recorded conflict events, not live
  "as_of": "2026-06-22T…",    // the freshest unresolved conflict's checked_at (null if none)
  "items": 1,                 // currently-held items carrying an unresolved conflict
  "events": [                 // the latest unresolved conflict per affected held item
    {"id": "web:demo", "status": "conflict", "checked_at": "…",
     "prior_hash": "sha256:held", "observed_hash": "sha256:moved"}
  ]
}
```

The design decision the slice resolves: a conflict is **unresolved** while the
*latest* conflict event's `observed_hash` (the incoming capture that disagreed)
still differs from the held copy's current `content_hash`. The held copy is never
auto-overwritten (ADR 0104; raw is sacred), so every recorded conflict is
unresolved today — but the predicate is deliberately **resolution-aware**: a
future `reconcile` (H276) that adopts the incoming content (the held hash becomes
the observed hash) clears the item with **no** special "resolved" event, exactly
the `latest_events` held-filter precedent (read the latest event, compare to the
current state). Held-filtered like the drift block — a conflict on a since-deleted
id is not this library's divergence — so the count `doctor` reports is exactly the
set a `reconcile` would act on, and a `--source` audit scopes the aggregate for
free (a held item owns a source, so an import conflict is source-attributable,
unlike the cross-source `custody.works` alarm).

It is a **report view only** (custody §2.4): like the drift block it never feeds
the structural `issues`/`fixed` or the exit code — `doctor` cannot repair a
divergence it must not silently overwrite. The two ledger axes never mix:
`latest_conflict_events` reads only the `conflict` rows, `latest_events` only the
verify verdicts, so a conflict never inflates `custody.drift` and a drift verdict
never appears here. The MCP `get_library_health` twin carries it for free (the
tool returns `run_doctor`'s whole custody block), converging field-for-field with
the CLI `doctor` by construction.

Tested: `test_latest_conflict_events_reads_the_max_id_per_item_over_conflict_rows`
and `test_unresolved_conflicts_clears_when_the_held_copy_now_matches_the_incoming`
(the primitives, incl. the resolution-aware clear) and their siblings in
`tests/test_custody.py`;
`test_doctor_custody_conflicts_surfaces_an_unresolved_import_conflict` and the
clean/held-filter/source-scope siblings in `tests/test_cli.py`;
`test_get_library_health_carries_the_conflicts_aggregate` in `tests/test_mcp.py`.

A readable `_Conflicts:_` briefing line (H277, below) and a reviewed `reconcile`
resolution (H276, below — *choose a winner, record the supersession*) both shipped
after this read leg: detection → read → resolve, the obsidian *surface, don't
rewrite* posture carried to its close.

## Shipped: a readable `_Conflicts:_` briefing line (H277, ADR 0104)

H275 put the import-conflict aggregate on `doctor`'s `custody.conflicts` JSON read
(and the MCP `get_library_health` twin), but the **readable briefings an agent
skims** — the shareable `export bundle` (both Markdown and HTML forms) and the
`scrolls context` briefing — carried only the per-item drift/source headlines,
never the scope-level conflict count. The three briefings now render a one-line
conflict pointer beside the existing custody headline and the `_Attention:_` /
`_At-risk work:_` / `_Refresh:_` lines:

```text
_Conflicts: 1 item(s) carry an unresolved import conflict._
```

and its HTML twin `<p class="custody-conflicts">Conflicts: 1 item(s) carry an
unresolved import conflict.</p>`. It is the **conflict-axis counterpart of the
drift `_Attention:_` line** (`custody.render_custody_attention`, H159) and the
work-level `_At-risk work:_` line (`works.render_at_risk_works`, H264): the
readable completion of H275's JSON aggregate.

Design decisions:

- **Converges by construction.** The line folds the *same* `unresolved_conflicts`
  predicate over the *same* `latest_conflict_events` map `doctor`'s
  `custody.conflicts` reads (the shared `custody.render_custody_conflicts` helper),
  so the readable count and the JSON `items` cannot disagree for the same scope.
- **Names no command.** Unlike `_Attention:_`/`_Refresh:_`, which point at an
  existing recheck/refresh act, the conflict resolution act — a reviewed
  `reconcile` (H276) — does not exist yet, so the line surfaces the *count* only;
  fabricating a command would violate the `at_risk_signal` orphan-command
  discipline (the per-item detail lives on `doctor`'s `custody.conflicts.events`
  and `scrolls history <id> --status conflict`).
- **Per-item axis, scope-relative.** Folded over the briefing's own `items` (the
  per-item custody axis the headline and `_Attention:_` line use — a conflict is a
  per-item fact, not a work consolidation), held-filtered by `unresolved_conflicts`.
- **Gated like the headline.** In `context`, the line is gated to the
  `connected`/`full` budget tiers — the leanest `index` tier reads no ledger, so it
  makes no conflict claim (the M2 anti-fabrication gate). Export-only on the bundle:
  a derived read view, never inside the lossless `@generated` JSONL fence, so the
  round-trip is untouched.
- **Honest absence.** No line when no held item in scope carries an unresolved
  conflict (a clean or never-merged-with-a-peer scope), the `_Attention:_`/`_At-risk
  work:_` no-op shape — and a *resolved* conflict (the held copy now matches the
  incoming hash) drops out via the resolution-aware predicate.

Tested: `tests/test_bundle.py` (Markdown carries-the-line + doctor convergence +
clean/resolution-aware/round-trip no-ops; HTML twin + clean no-op),
`tests/test_context.py` (carries-the-line + doctor convergence + `index` gate +
`connected` presence + clean no-op + MCP parity), and the
`render_custody_conflicts` unit tests in `tests/test_custody.py` (count,
held-filter + resolution-aware, honest no-op).

## Shipped: a reviewed `reconcile` resolution — keep-held (H276, ADR 0105)

Detection (H272–H274) and the scope read (H275/H277) *surface and count* a
divergence but never resolve it — the held copy is always kept, so `doctor`'s
`custody.conflicts` and the `_Conflicts:_` line flag every recorded conflict
indefinitely. `scrolls reconcile <id> --keep-held` is the **operator act** that
closes the loop — the final move of the obsidian *surface, don't rewrite* posture:
*choose a winner, record the supersession, never destroy the prior capture.*

```bash
scrolls reconcile <id> --keep-held              # affirm the held copy
scrolls reconcile <id> --keep-held --dry-run    # predict, write nothing
```

`--keep-held` affirms the held copy as authoritative. It records a typed
`resolved` **conflict-axis** custody event (`custody.resolution_event` —
`prior_hash` = the affirmed held copy, `observed_hash` = the rejected incoming
capture) that **supersedes** the open conflict: `latest_conflict_events` now reads
the `MAX(id)` over the conflict axis (`conflict` *and* `resolved`), and
`unresolved_conflicts` keeps an item only while its latest axis event is *still an
open* `conflict`. So the resolution clears across every conflict surface at once —
`doctor`'s `custody.conflicts`, the `_Conflicts:_` briefing line on both bundle
forms and `scrolls context`, and the MCP `get_library_health` twin — because they
all fold that one shared predicate.

Two custody guarantees hold by construction:

- **The held copy is never overwritten** (raw is sacred — custody §2.4): its
  content and `content_hash` are provably untouched; `reconcile` only *appends* a
  ledger event.
- **The original `conflict` event survives** (append-only): `scrolls history <id>
  --status conflict` still shows *when* a peer disagreed, and `--status resolved`
  shows the operator decision. The resolution is a new row, not an edit.

The decision the slice resolves (ADR 0105): **why keep-held ships and
accept-incoming is deferred.** The hash-compare resolution predicate (H275) clears
a conflict when the held copy's `content_hash` equals the incoming hash — which is
exactly how a future `--accept-incoming` *would* clear (the held hash *becomes* the
observed hash). But it cannot clear a keep-held, because keep-held leaves the held
hash unchanged; so keep-held needs an **explicit recorded decision** (the
`resolved` event, skipped on the status gate). And `--accept-incoming` (adopt the
peer's capture) needs the incoming **content** — but the conflict event records
only the incoming *hash*; the importer discarded the bytes (the held copy was never
overwritten). Adopting the peer's capture therefore requires re-supplying the
content plus custody-safe prior-content archival (ADR 0098's deferred
"re-capture-on-accept") — the first import-path write that changes a held capture,
a separate, heavier slice.

The command is **CLI-only** (a custody-changing write is an explicit operator act,
not an ambient MCP capability, like `verify`), **opt-in** (a bare `reconcile <id>`
is exit 2 — the resolution is a decision, not a default), **idempotent** (a second
`--keep-held` is a no-op — the latest axis event is already `resolved`), and
**dry-run-able** (`--dry-run` emits the same decision payload the live run would,
plus `dry_run: true`, and writes nothing — the `import bundle --dry-run`
predict-the-write discipline). A genuinely new divergent import *after* a
resolution appends a fresh `conflict` event and **re-opens** the alarm — new
evidence of a new disagreement. The `resolved` event stays off the drift axis
(`latest_events` reads only the verify verdicts), exactly the ADR 0104 isolation.

Tested: `tests/test_custody.py` (the `resolution_event` shape + serializer
round-trip, a `resolved` event excluded from the drift posture,
`latest_conflict_events` returns the resolution when it is latest,
`unresolved_conflicts` clears after a keep-held resolution and re-opens on a fresh
conflict, the `current_conflict` per-item target); `tests/test_cli.py`
(`reconcile --keep-held` resolves and clears `doctor` while the held copy is
untouched, idempotent re-run, `--dry-run` predicts without recording, a missing
resolution flag is exit 2, an unknown id is exit 1, a no-conflict held item is a
no-op, the `conflict` row survives on `history` beside the `resolved` row).

**Deferred at the time:** `--accept-incoming` (a content-bearing, re-import-driven
supersession with prior-content archival — the first held-capture write) and an MCP
`reconcile` twin. With keep-held the conflict-on-import theme was complete on the
detect → read → **resolve** arc for the safe direction; `--accept-incoming` then
shipped (H278, ADR 0106 — see below), closing both resolution directions.

## Shipped: a conflict scalar on `scrolls status`'s JSON custody snapshot (H279)

The readable `_Conflicts:_` line (H277) was deliberately scoped to the three
Markdown briefings (`export bundle` ×2 + `scrolls context`). `scrolls status`
renders no readable `_Attention:_`/`_At-risk work:_` lines — it carries the
**machine** custody snapshot instead (`custody`: `score`, `tiers`, `drift`,
`enrichment_stale`/`summaries_stale`, `at_risk`). It did *not* yet carry an
import-conflict count, so an agent reading `status` for a custody dashboard saw
drift and at-risk-works but not unresolved import conflicts. H279 closes that last
conflict **read** gap on the JSON surface:

```json
// scrolls status  →  "custody": { …, "at_risk": 0, "conflicts": 1 }
```

`custody.conflicts` is the count of currently-held items carrying an *unresolved*
import conflict — the same `unresolved_conflicts` over `latest_conflict_events`
that `doctor`'s `custody.conflicts` and the `_Conflicts:_` line read, folded into
the shared `maintain.custody_snapshot` primitive (`custody.get("conflicts",
{}).get("items", 0)`, the defensive read `at_risk` uses). Because `status`'s
`custody` block *is* `custody_snapshot(run_doctor(...))`, the scalar converges
field-for-field with `doctor`'s `custody.conflicts.items` by construction — a pure
read of the report `run_doctor` already produced, no extra ledger query, no schema
change. It is **resolution-aware** (a `reconcile --keep-held` clears it) and
**source-scopable** for free (`status --source <S>` narrows the conflict fold like
the drift scalar, since a held item owns a source — unlike the cross-source
`at_risk` alarm). The MCP `get_library_health` twin already carries the full
`custody.conflicts` block (it spreads `**custody`), so it needs no change.

Tested: `tests/test_cli.py` (the scalar surfaces an unresolved conflict + converges
with `doctor` + stays off the drift axis, clears after `reconcile --keep-held`,
honest `0` on a clean library, source-scopes to the conflicting source);
`tests/test_maintain.py` (the `custody_snapshot` primitive records
`custody.conflicts.items` and defaults to `0` without a `conflicts` block).

**Shipped in H283 (the `at_risk` → H267/H268 analogue):** the cross-run `delta` /
`--history` / `--trend` treatment of the conflict scalar and a readable
`_Conflicts:_` line on the `maintain` report (see below). H279 *recorded* the scalar
on the snapshot; H283 *differences* it.

## Shipped: the conflict-over-time leg — the `_Conflicts:_` `maintain` line + delta/trend (H283)

H279 put the unresolved-conflict count on `status`'s custody snapshot and the shared
`maintain.custody_snapshot`, but — unlike the at-risk-works count (H267/H268) — it
was recorded *without* being differenced. H283 lifts the exact at-risk machinery to
the conflict axis, the clean H267/H268 analogue:

- **`compute_delta`** subtracts the scalar — `delta["conflicts"]` is the
  cross-run `{before, after, change}` (degrade-safe: a pre-H279 baseline reads `0`,
  a first run reads `null`, exactly as the other scalars do).
- **`compute_trend`** differences it across the window — a new `conflicts_change`
  axis beside `at_risk_change`, telescoping to the per-run deltas a worker reads back
  from `--history` (pinned in `tests/test_custody_convergence.py`).
- **`conflicts_headline(count, change, *, span)`** renders the readable line (the
  conflict twin of `at_risk_headline`): `▲` a rise (more held items carry an
  unresolved peer divergence — worse), `▼` a fall (a `reconcile`/accept-incoming
  resolution cleared one — better), `0` the explicit `no change`, and a bare
  `_Conflicts: N._` when there is no baseline (first run / scoped non-persisting pass
  / <2-run trend — the H267 honesty).

```text
scrolls maintain        →  "conflicts_headline": "_Conflicts: 1 (▲1 since last run)._"
scrolls maintain --trend →  trend.conflicts_headline: "_Conflicts: 0 (▼1 over 3 runs)._"
```

Like the snapshot scalar it is **resolution-aware** (a `reconcile --keep-held` /
`import … --accept-incoming` clears it) and **source-scopable** for free
(`maintain --source <S>` narrows the conflict count to <S> — unlike the
whole-library-only `at_risk` line, since a held item owns a source). It is recorded
but **never a `posture` trigger** (a peer divergence moves neither the integrity
score nor the drift axis — the held copy is never overwritten, custody §2.4 — so the
posture stays integrity-only, the H115/H267 precedent). The MCP `run_maintenance`
twin carries the line; like `at_risk_headline` it embeds the delta's signed change,
so it is run-position-dependent and the MCP↔CLI convergence test strips it beside
`delta`/`recorded_at` (a documented distinction from the position-independent
`headline`).

Tested: `tests/test_maintain.py` (the `conflicts_headline` renderer ×5, the
`compute_delta` conflict axis ×3, the `compute_trend` `conflicts_change`/headline ×5,
and the integration report/`--history`/`--trend`/`--source` lines ×5);
`tests/test_custody_convergence.py` (the conflict axis telescopes with drift /
coverage / staleness / at-risk; the `_audit_fields` MCP-strip); `tests/test_mcp.py`
(the `conflicts_headline` field rides the `run_maintenance` shape). End-to-end:
divergent peer import → `_Conflicts: 1 (▲1 since last run)._` → `reconcile
--keep-held` → `_Conflicts: 0 (▼1 since last run)._`, the `--trend` line distilling
the window.

**With H283 the conflict-on-import theme's read leg is closed across *every* surface
including the over-time axis** — JSON status/doctor/MCP, the readable briefings, and
now the `maintain` delta/trend.

## Shipped: `--accept-incoming` — the content-bearing resolution that *adopts* the peer's capture (H278, ADR 0106)

`reconcile --keep-held` (H276) shipped the **safe** direction — affirm the held
copy. The other direction, **adopt the peer's capture**, was deferred (ADR 0105)
for a concrete reason: the conflict event records only *hashes*, never the incoming
*content* (the importer discarded the bytes — the held copy was never overwritten),
so at `reconcile` time the incoming content is gone. Adopting it must **re-supply**
the content — which is in hand only at the **merge**. So `--accept-incoming` is an
**import-path** flag, not a `reconcile` flag:

```bash
scrolls import items <file>  --accept-incoming             # adopt diverging items
scrolls import bundle <file> --accept-incoming             # adopt diverging bundle scrolls
scrolls import bundle <file> --accept-incoming --dry-run   # predict the adoptions, write nothing
```

On a content conflict, `--accept-incoming` **replaces** the held copy with the
incoming one and records a `superseded` conflict-axis event — the *first
import-path write that changes a held capture*. It stays custody-safe because **raw
is sacred** (§2.4): the prior copy is **archived first** into the new `item_archive`
table (schema v8), recoverable, never destroyed. The adoption clears the conflict
across every surface at once (`doctor`'s `custody.conflicts`, the `_Conflicts:_`
line on both bundle forms + `context`, `status`'s scalar, the MCP twin) because the
held copy now *is* the incoming and the latest conflict-axis event is a `superseded`
— both gates of the shared `unresolved_conflicts` predicate agree.

The decisive design choices (ADR 0106):

- **The archive, not an overwrite.** `items.adopt_incoming` snapshots the prior row
  (model-complete `item_to_dict` JSON) into `item_archive` and updates the items row
  in **one transaction** (archive before replace, so a crash never loses the prior).
  The `superseded` event records `prior_hash` (the archived copy) and `observed_hash`
  (the adopted incoming), staying off the drift axis (the ADR 0104 isolation).
- **Idempotent by construction.** Once adopted, the held copy equals the incoming, so
  a re-import is `unchanged` — no second archive, no second event, no special-casing.
- **Recovery is symmetric.** `scrolls archive list` is the recovery index (the prior
  captures an adoption replaced, with before/after hashes); `scrolls archive show
  <id>` re-emits the latest archived prior as a re-importable `export items` line, so
  restoring it is just `archive show <id> | import items /dev/stdin
  --accept-incoming` — accept-incoming of the archived snapshot re-adopts the prior
  (archiving the current copy in turn).
- **Opt-in, loud, CLI-only.** Without the flag a conflict is surfaced and the held
  copy kept (the H272–H274 default); with it, the adoption rides a structured
  `adopted` list and a loud stderr warning (a held copy was replaced). Like
  `verify`/`reconcile`, the write and its recovery are operator-gated, not ambient MCP.

The archive is a **local recovery store**, not part of the lossless round-trip: the
`superseded` event travels in `export items`/`export bundle` (documenting the
adoption and its prior hash), while the archived prior *bytes* stay local (carrying
them in bundles is a deferred extension).

Tested: `tests/test_db.py` (the v8 migration preserves the ledger);
`tests/test_custody.py` (the `supersession_event` shape + serializer round-trip, off
the drift axis, supersedes the conflict, clears `unresolved_conflicts` on both
gates); `tests/test_items.py` (`adopt_incoming` archives + replaces atomically, the
`list_archived`/`latest_archived` recovery reads, the symmetric round-trip);
`tests/test_cli.py` (`import items --accept-incoming` adopts + archives + records +
clears the aggregate, idempotent, `archive list`/`show`, the show→import restore);
`tests/test_bundle.py` (`import bundle --accept-incoming` adopts, the dry-run
predicts without writing).

**Deferred:** ~~the archive in portable bundles~~ (shipped — H280, below), an MCP
accept-incoming *write* twin, ~~`archive prune` / retention~~ (shipped — H282,
below), ~~`archive show --all`~~ (shipped — H285, below), and restore-by-version
(H286). With `--accept-incoming` the conflict-on-import theme is complete on **both**
resolution directions — keep-held and accept-incoming — across detect → read →
resolve.

## Shipped: the prior-content archive travels in the portable round-trip (H280)

ADR 0106 made adoption custody-safe *locally* — the superseded prior is archived
and recoverable via `scrolls archive show` — but left the archive a **local**
store: a `superseded` event travels in the lossless round-trip while the archived
prior *bytes* stay behind, so a library rebuilt from a bundle could read *that* an
adoption happened (the event) but not recover the prior copy. H280 lets the
recovery store travel:

- **`scrolls export bundle --with-archive`** appends an optional **third
  `@generated` region** — the in-scope items' `item_archive` snapshots — beside the
  items and events blocks (`bundle._archive_block`/`parse_bundle_archive`). Opt-in
  because the archive can be large and the `superseded` event already documents the
  adoption; **without the flag the bundle is byte-identical to a pre-H280 one**, so
  the round-trip / byte-identity guarantees are untouched.
- **`scrolls export archive` / `scrolls import archive`** are the whole-library
  JSONL siblings of `export events`/`import events` (`items.archived_records`/
  `dump_archive_export`/`import_archive`, `archive_export.load_archive_export`) — the
  third member of the lossless backup family (items, events, archive).
- **`import bundle` restores any archive block unconditionally** (the flag is an
  export concern only), deduped by `(item_id, prior_hash)` — the H67 events-dedup
  precedent on the archive identity — so a re-import, or the overlapping union of two
  bundles, is a no-op. The `--dry-run` predicts the restore without writing.

The records are ordered content-deterministically (`archived_at`, `item_id`,
`prior_hash`), independent of the per-library autoincrement id, so a re-export from
a rebuilt library reproduces the block **byte-for-byte** — the lossless-round-trip
reach of the recovery store. The archive stays a **standalone recovery store** keyed
by `item_id` with no held-row interaction (it only appends to `item_archive`), so —
unlike the events restore — it needs no orphan split. **No schema change** (the v8
`item_archive` table is unchanged); no network.

Tested: `tests/test_items.py` (the `archived_records` reader, `import_archive`
dedup incl. within-batch + NULL prior_hash, the `preview_import_archive` parity, the
dump→load→import round-trip); `tests/test_archive_export.py` (the JSONL framing +
validation + load↔dump round-trip); `tests/test_bundle.py` (the default bundle
carries no archive block, `--with-archive` carries the scoped priors, the round-trip
recovers them in a fresh library, the byte-identical re-export, idempotent restore,
the dry-run prediction, the HTML form); `tests/test_cli.py` (`export archive` /
`import archive` round-trip, idempotency, `--id` scope, empty/error cases).

## Shipped: an MCP archive *read* twin — `list_archived` / `get_archived` (H281, ADR 0106)

The recovery store was **CLI-only**: `scrolls archive list` / `scrolls archive show`
read what an accept-incoming adoption superseded, but an agent operating purely over
MCP could see *that* an adoption happened (the `superseded` event over
`get_scroll_history --status superseded`, the cleared `custody.conflicts` over
`get_library_health`) yet had no way to reach the recovery store itself. H281 adds the
*read* twin — the same CLI split, over MCP:

- **`list_archived(item_id=None)`** is the recovery *index* (the twin of `scrolls
  archive list`): the metadata an adoption archived — each `{item_id, prior_hash,
  superseded_by, archived_at}`, newest first — scoped to one item or the whole
  archive. It returns the **same `{count, archived}` shape** the CLI prints, folding
  the **same shared `items.archive_entry_dict` serializer**, so the index reads
  identically on the shell and over MCP (convergence by construction). A clean /
  pre-v8 / uninitialized library is the honest empty block, never an error.
- **`get_archived(item_id)`** is the recovery *snapshot* (the twin of `scrolls
  archive show`): the most-recently superseded copy of one item as the
  model-complete, re-importable `item_to_dict` snapshot — the same shape an `export
  items` line carries — folding the same `items.latest_archived` the CLI reads. So an
  agent can recover the prior bytes and, if it chooses, hand the snapshot back to a
  CLI `scrolls import items … --accept-incoming` to *restore* it. An item with no
  archived prior (never superseded), an unknown id, or a pre-v8 library is an error
  (the could-not-recover signal, the MCP twin of `archive show`'s exit 1).

The **write stays operator-gated** (custody §2.4): the custody-changing
`import … --accept-incoming` adoption — and the symmetric restore — is a shell act, not
an ambient MCP capability. This is the *read* twin only. The two tools fold the same
primitives the CLI reads (`archive_entry_dict`/`latest_archived`), so the surfaces
converge by construction; **no schema change, no network.**

Tested: `tests/test_mcp.py` (the index after an adoption + the four-field row, honest
empty before init / on a never-adopted library, `--id`/`item_id` scope, the
convergence-with-CLI `archive list`/`archive show` ties, the model-complete
re-importable snapshot, the no-prior / unknown-id could-not-recover errors, the
registered-tool surface).

## Shipped: `archive prune` — a retention act bounding the recovery store (H282, ADR 0106)

The `item_archive` is **append-only and unbounded**: every accept-incoming adoption
snapshots the prior copy, and the symmetric restore round-trip
(`archive show | import … --accept-incoming`) appends more, so the store accumulates
superseded captures with no way to reclaim space. H282 adds the bound:

```text
scrolls archive prune (--before ISO | --keep N) [--apply]
```

**The decisive question** the slice resolved: *is pruning the archive a custody
violation?* — answered **no**. Raw-is-sacred (§2.4) protects the **held** copy; a
superseded prior is already a *deliberate replacement* the operator chose, and the
archive is a **recovery convenience**, not the root of trust. So dropping old
snapshots is custody-safe — provided the act is **explicit**, **predictable**, and
**never touches a held row**. It only ever DELETEs from `item_archive`; the items
table and the custody ledger are untouched (a test pins the held copy byte-for-byte
intact and the ledger unchanged across a prune).

Two mutually-exclusive policies, exactly one required (a bare `prune`, or both, is
exit 2 — the `reconcile <id>` opt-in gate):

- **`--before ISO`** — drop priors archived *strictly before* the boundary (date-only
  ok → that day's UTC midnight, the `verify --stale-before` normalization via
  `parse_since`). The time-based policy; it **may** drop an item's latest prior (an
  explicit, honest consequence — `archive show` then could-not-recovers for it).
- **`--keep N`** — per item, keep the most recent N priors and drop the rest. **N>=1**
  (a `--keep 0` is rejected), so the latest prior **always survives** a keep-prune and
  `archive show <id>` keeps recovering it — a clean recovery invariant the count
  policy guarantees and the time policy deliberately does not.

**Report-only by default** (the H245/H273 dry-run discipline): a bare
`archive prune --keep 1` predicts the drop set (`matched`) and writes nothing
(`dropped: 0`, `applied: false`); the archive is genuinely untouched. `--apply`
performs the deletion (`dropped == matched`) and warns loudly on stderr (a recovery
store was shrunk, even though the operator asked). The read-only
`items.select_prunable_archive` (the preview) and the `items.prune_archive` write fold
the **one pure `_select_prunable`**, so the preview predicts the write exactly. The
write is **idempotent** (a second `--apply` finds the rows gone, drops 0) and
**CLI-only** (a custody-changing write, like `verify`/`reconcile`). No schema change,
no network — a deterministic DELETE over the local recovery store.

Tested: `tests/test_items.py` (the per-item keep / strictly-before selection, the
preview ≡ apply drop set, idempotency, the held-row + ledger untouched, the
empty-archive no-op); `tests/test_cli.py` (the exactly-one-policy gate, the
`--keep 0` / malformed-`--before` rejections, report-only writes nothing, `--apply`
drops + warns + leaves the latest recoverable, the before-policy whole-archive clear,
the clean-library empty report).

## Shipped: `archive show --all` — the full archived history (H285, ADR 0106)

`scrolls archive show <id>` recovered only the **most-recently** superseded copy (the
latest `item_archive` row). After several adoptions of the same id the *earlier* priors
were reachable in the `archive list` index (their metadata) but not re-emittable as
re-importable snapshots — a multi-supersession item's deeper history could be inspected
but not backed up. H285 adds the full-history read:

```text
scrolls archive show <id> --all
```

`--all` emits **every** archived prior for the id as a JSONL stream, **newest first**
(the `archive list` `id DESC` order), each line the model-complete `item_to_dict`
snapshot — so the whole recoverable history backs up or inspects as re-importable
`export items` lines, not just the head. The default (no `--all`) is unchanged: latest
prior only.

**The decisive choice** — convergence by construction. A new
`items.archived_snapshots(db_path, item_id) -> list[ScrollItem]` (the list-returning
sibling of the scalar `latest_archived`) folds the same `snapshot` column over *all*
rows for the id by `id DESC`, and `latest_archived` was **refactored to return its
head** (`archived_snapshots(...)[0]`). So `archive show` (the single-snapshot recovery)
and `archive show --all` (the full history) share **one** snapshot-parsing read and can
never disagree: `archive show <id>` is byte-identical to `archive show <id> --all`'s
first line. An empty history (`--all` on a never-superseded or unknown id) is the same
exit-1 could-not-recover as the single-snapshot read — an empty stream is not a recovery.

A **CLI-only read** (no write), no schema change, no network — a pure fold over
`item_archive` (pre-v8 tolerant, returns `[]`). Restoring a *specific* older version
(not just the latest) is the deferred restore-by-version (H286): a `--hash`/`--at`
selector over this same stream, feeding the existing accept-incoming adoption write.

Tested: `tests/test_items.py` (`archived_snapshots` returns all priors newest-first and
matches the `list_archived` order, `latest_archived` is its head, `[]` for a
never-superseded id, pre-v8 tolerant); `tests/test_cli.py` (`--all` emits N lines
newest-first for an N-adoption item, the default still one line and byte-identical to
the `--all` head, a single-prior `--all` ≡ the default, a never-superseded `--all`
exit-1).
