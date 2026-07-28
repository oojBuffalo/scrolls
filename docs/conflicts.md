# Custody conflicts in Scrolls

**Status:** Original design plus the shipped surface. The design record below is
the foundation for the Reconcile stage in the Scrolls pipeline; the
custody-conflict surface it led to (detection → read → resolution → recovery)
has since shipped and is documented in
[What has shipped](#what-has-shipped--the-conflict-on-import-surface).

*Amended: 2026-07-26 — inspiration references reduced to pointers
(`docs/inspiration/`); 2026-07-27 — shipped-slice narration consolidated into a
per-capability contract section for readability, and the file renamed from
`reconciliation.md` to `conflicts.md` to end the name collision with the dev
check-in `reconciliation.md` files under `docs/agents/progress/`.*

## Goals

- Collapse multiple representations of the same intellectual work into one canonical item.
- Detect and handle duplicates gracefully.
- Infer and maintain typed relationships between items.
- Produce explainable, auditable results.
- Be re-runnable without destroying user data.

## Where this design stands

The sections from here through "Open Questions" are the original design record —
they predate implementation and are kept as written, with brief time notes. As of
2026-07:

- **Shipped:** conflict detection and classification at the import boundary, the
  `conflict` custody event and its read surfaces (`doctor`, the briefings,
  `status`, `maintain`), the `reconcile --keep-held` resolution, the
  `--accept-incoming` adoption, and the `item_archive` recovery family — all in
  "What has shipped" below.
- **Shipped in a different shape:** `scrolls works` exists as a *derived,
  read-only* clustering of representations by shared DOI (ADR 0069, ADR 0070),
  with fidelity/drift/at-risk browse predicates — no stored `works` table, and
  never a merge.
- **Genuinely unbuilt:** the `works` / `work_representations` /
  `work_relationships` tables; the `work_id` / `is_canonical` /
  `reconciliation_state` item columns; whole-library `scrolls reconcile
  --dry-run` sweeps and `--item` / `--since` selection; `scrolls works merge`;
  and an MCP `reconcile` / accept-incoming *write* twin (the archive reads have
  MCP twins; the custody-changing writes stay CLI-only by design).

## Core Concepts

### Work

A "Work" is the canonical intellectual object (e.g., a specific research paper, a
specific GitHub repository, a specific YouTube video).

### Representation

A "Representation" is one saved form of a Work (e.g., the arXiv preprint, the
PubMed record, the published DOI version, the GitHub mirror).

### Canonical Item

One primary `ScrollItem` that represents the Work. Other representations link to it.

## Proposed Data Model Additions

*Time note: none of these tables or columns shipped. The shipped system records a
divergence as an append-only custody-ledger event (ADR 0104) instead of a
`reconciliation_state` column, and clusters representations at read time instead
of storing `works` rows.*

New tables / relationships (to be implemented incrementally):

- `works` table: canonical work id, primary title, primary source, quality score, created_at, updated_at
- `work_representations`: work_id, item_id, representation_type, confidence, is_canonical
- `work_relationships`: from_work_id, to_work_id, relationship_type (cites, extends, same_as, derived_from, etc.), confidence, provenance

Existing `items` table gains:

- `work_id` (nullable FK)
- `is_canonical` boolean
- `reconciliation_state` enum (pending, reviewed, merged, conflict)

## CLI Surface (Proposed)

*Time note: this sketch predates implementation. What actually shipped is a
per-item, opt-in resolution — `scrolls reconcile <id> --keep-held [--dry-run]` —
plus the import-path `--accept-incoming` adoption and the `scrolls archive`
family (below). The whole-library `reconcile` sweep and `works merge` remain
unbuilt.*

```bash
scrolls reconcile                    # run reconciliation on the whole library
scrolls reconcile --dry-run          # show what would change
scrolls reconcile --item <id>        # reconcile a specific item
scrolls reconcile --since 7d         # only consider recently added items
scrolls works list                   # list canonical works
scrolls works show <work-id>         # show a work and all its representations
scrolls works merge <work-id>        # manually force a merge (with confirmation)
```

MCP tools should expose equivalent capabilities. *(Holds today for reads only:
the conflict aggregate and the archive have MCP read twins; the resolution
writes are deliberately CLI-only — custody §2.4.)*

## First Implementation Slice (Recommended)

*Time note: written before implementation. The slice that actually shipped first
was the import-boundary conflict surface (H272–H274), not the `works` table —
and reconciliation state did reach `scrolls doctor`, as the `custody.conflicts`
aggregate rather than a work-clustering readout.*

1. Add the `work_id` column and basic indexes.
2. Implement a simple `reconcile --dry-run` that detects obvious duplicates by DOI / canonical URL / title+author fingerprint.
3. Create a basic `works` table and populate it for items that have clear canonical signals (DOI, arXiv id, GitHub repo, etc.).
4. Add `scrolls reconcile --dry-run` command + tests.
5. Expose basic reconciliation state via `scrolls doctor` and source pages.

This gives us a foundation without over-committing to a complex engine immediately.

## Open Questions

The original questions, annotated with what the shipped work answered:

- **How aggressive should automatic merging be vs requiring human review?**
  *Answered: never automatic.* A divergence is surfaced and recorded; resolution
  is an explicit operator act (`reconcile --keep-held`,
  `import … --accept-incoming`) — ADR 0104, ADR 0105.
- **What is the confidence threshold for auto-merging?**
  *Moot* — there is no auto-merge to threshold. The only equivalence the shipped
  surface trusts is `content_hash` equality (an identical re-import is
  `unchanged`); anything else is a surfaced conflict.
- **How do we handle conflicting metadata across representations?**
  *Answered for captured content at the import boundary:* a recorded `conflict`
  event plus the two explicit resolutions. *Still open* for metadata
  reconciliation across representations of one work — the works read surface
  lists representations side by side and merges nothing.
- **Should reconciliation run automatically after ingest, or only on demand?**
  *Answered for the conflict surface:* detection is automatic at import;
  resolution is only ever on demand. *Still open* for the consolidation engine —
  there is no post-ingest reconciliation pass.

The still-open ends will be answered in subsequent slices with real usage data.

## What has shipped — the conflict-on-import surface

The reconcile posture is **keep the detection, replace auto-overwrite with
surfacing a conflict for review — surface, don't silently rewrite** (an adopted
mechanism; see `docs/inspiration/obsidian-second-brain-inspiration.md`). Its
first concrete enactment is at the **import boundary**, where two libraries'
captures actually collide. The surface is complete across detect → read →
resolve → recover; H-numbers below are provenance pointers into the roadmap, not
structure.

Cross-cutting custody contract, held by every capability below:

- **The held copy is never overwritten** by detection or reads. Only the explicit
  `--accept-incoming` adoption replaces it — and that archives the prior copy
  first (raw is sacred, custody §2.4).
- **The two ledger axes never mix.** Drift means "the live *source* moved" (known
  only by re-capturing via `verify`); a conflict means "a *peer's capture*
  disagreed". Each read folds only its own axis, so neither ever inflates the
  other (ADR 0104).
- **Report-only reads never feed exit codes** — the conflict aggregate, briefing
  lines, and scalars are report views, never structural `issues`/`fixed` or
  posture triggers.
- **Writes are opt-in and CLI-only** — resolution, adoption, restore, and prune
  are explicit operator acts, never ambient MCP capabilities; MCP gets read
  twins only.
- **Idempotency** — re-imports, repeated resolutions, and repeated prunes are
  no-ops by construction.
- **Dry-runs predict the write** — every write path has a `--dry-run` or
  report-only mode that emits the same decision payload and writes nothing.

### Detection and classification at import (H272–H273)

Both lossless importers — `scrolls import items` and `scrolls import bundle` —
classify every row instead of reporting an opaque skip. Each row goes through
`items.merge_item`, which keeps the `INSERT OR IGNORE` custody guarantee (the
held copy is never overwritten) and classifies the skip on `content_hash` — the
same captured-content fingerprint the verify ledger drifts on (ADR 0098):

- **`unchanged`** — the held copy has the same content: an idempotent re-import.
- **`conflict`** — the held copy has *different* captured content for the same
  id: a divergent capture. The held copy is kept; the diverging ids ride the
  structured `conflicts` field **and** a loud stderr warning — a recorded,
  reviewable event, never silently swallowed into a `skipped` count, never an
  overwrite (vision §2.4).
- **Detection chooses no winner.** It answers "these two captures of the same id
  disagree" without rewriting anything.
- **Dry-run predicts.** `import bundle --dry-run` predicts the conflict set the
  live merge would surface (the same `content_hash` compare, simulated without
  writing), so an operator can review a peer's divergences before committing —
  and a within-bundle duplicate that disagrees with itself classifies
  identically on both paths.

Tests: `test_import_items_surfaces_a_content_conflict` and siblings in
`tests/test_cli.py`; `test_import_bundle_surfaces_a_content_conflict` plus the
dry-run-prediction and within-bundle-dup siblings in `tests/test_bundle.py`.

### A conflict is a recorded custody event (H274, ADR 0104)

A surfaced conflict joins the append-only custody ledger (ADR 0098) as a typed
`conflict` event on the held item — "another capture of this id disagreed with
mine, observed at import time".

- **Shape.** `prior_hash` = the held copy we keep; `observed_hash` = the
  incoming capture that disagreed, stamped at import time (the bi-temporal
  captured-at vs source-changed-at signal). Queryable per item via
  `scrolls history <id> --status conflict`.
- **Recorded by both importers for free** — the event rides the shared
  `cli._merge_items`. The bundle `--dry-run` predicts the conflict but, being
  read-only, records nothing.
- **A distinct provenance-of-divergence axis, not a verify-drift** (the ADR 0104
  decision). Drift means the live **source** moved — known only by re-capturing
  through the adapter (`verify`). An import conflict involves no source
  re-capture, only a peer disagreeing, so claiming the source `drifted` would be
  fabrication (the M2 honesty).
- **Total isolation from the drift posture.** `custody.latest_events` reads only
  the verify verdicts, so a `conflict` event never enters `doctor`'s
  `custody.drift`, `list`/`search --drift`, the scope headlines, or the `works`
  aggregate; an item with only a conflict reads `unverified`, and a conflict
  appended after a real `drifted` verdict never masks it.

Tests: `test_conflict_event_records_held_vs_incoming_hash`,
`test_conflict_event_is_excluded_from_the_drift_posture`, and siblings in
`tests/test_custody.py`; the records/clean-reimport import pairs in
`tests/test_cli.py` and `tests/test_bundle.py`.

### The read surfaces

One predicate, four reads. Every surface below folds the same
`unresolved_conflicts` predicate over the same `latest_conflict_events` map, so
all conflict counts converge for a given scope by construction. An item is
**unresolved** while its latest conflict-axis event is still an open `conflict`
whose `observed_hash` differs from the held copy's current `content_hash` — so
the predicate is **resolution-aware** (a keep-held or an adoption clears it,
with no bookkeeping pass) and **held-filtered** (a conflict on a since-deleted
id is not this library's divergence).

#### `doctor` — the `custody.conflicts` aggregate (H275)

The read-aggregate sibling of `custody.drift`, over the other
provenance-of-divergence axis:

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

- **Report view only** (custody §2.4): like the drift block it never feeds the
  structural `issues`/`fixed` or the exit code — `doctor` cannot repair a
  divergence it must not silently overwrite.
- **The count is exactly the set a `reconcile` would act on**, and a `--source`
  audit scopes it for free — a held item owns a source, so an import conflict is
  source-attributable (unlike the cross-source `custody.works` alarm).
- **The MCP `get_library_health` twin carries the block for free** (the tool
  returns `run_doctor`'s whole custody block), converging field-for-field with
  the CLI by construction.

Tests: `test_doctor_custody_conflicts_surfaces_an_unresolved_import_conflict`
and siblings in `tests/test_cli.py`; the `latest_conflict_events` /
`unresolved_conflicts` primitives in `tests/test_custody.py`;
`test_get_library_health_carries_the_conflicts_aggregate` in `tests/test_mcp.py`.

#### The `_Conflicts:_` briefing line (H277)

The readable completion of the JSON aggregate, on the three briefings an agent
skims — the shareable `export bundle` (Markdown, and the
`<p class="custody-conflicts">…</p>` HTML twin) and `scrolls context` — rendered
beside the custody headline and the `_Attention:_` / `_At-risk work:_` /
`_Refresh:_` lines:

```text
_Conflicts: 1 item(s) carry an unresolved import conflict._
```

- **The conflict-axis counterpart** of the drift `_Attention:_` line
  (`custody.render_custody_attention`, H159) and the work-level `_At-risk
  work:_` line (`works.render_at_risk_works`, H264).
- **Converges by construction.** The shared `custody.render_custody_conflicts`
  helper folds the same predicate `doctor` reads, so the readable count and the
  JSON `items` cannot disagree for the same scope.
- **Names no command** — the count only; the per-item detail lives on `doctor`'s
  `custody.conflicts.events` and `scrolls history <id> --status conflict` (the
  `at_risk_signal` orphan-command discipline, adopted before `reconcile`
  existed).
- **Per-item axis, scope-relative:** folded over the briefing's own `items` (the
  per-item custody axis the headline and `_Attention:_` line use — a conflict is
  a per-item fact, not a work consolidation), held-filtered.
- **Gated like the headline.** In `context` the line renders only at the
  `connected`/`full` budget tiers — the leanest `index` tier reads no ledger, so
  it makes no conflict claim (the M2 anti-fabrication gate). Export-only on the
  bundle: a derived read view, never inside the lossless `@generated` JSONL
  fence, so the round-trip is untouched.
- **Honest absence.** No line on a clean or never-merged-with-a-peer scope, and
  a resolved conflict drops out via the resolution-aware predicate.

Tests: `tests/test_bundle.py` (Markdown and HTML forms, doctor convergence,
no-op shapes), `tests/test_context.py` (presence, tier gate, MCP parity), and
the `render_custody_conflicts` units in `tests/test_custody.py`.

#### The `status` conflict scalar (H279)

`scrolls status` carries the machine custody snapshot (`score`, `tiers`,
`drift`, `enrichment_stale`/`summaries_stale`, `at_risk`) rather than readable
lines, so its conflict read is a scalar:

```json
// scrolls status  →  "custody": { …, "at_risk": 0, "conflicts": 1 }
```

- **Same predicate, shared primitive.** The count folds into
  `maintain.custody_snapshot` (the defensive read `at_risk` uses); because
  `status`'s custody block *is* `custody_snapshot(run_doctor(...))`, the scalar
  converges with `doctor`'s `custody.conflicts.items` by construction — a pure
  read of the report already produced, no extra ledger query, no schema change.
- **Resolution-aware and source-scopable for free** (`status --source <S>`
  narrows the fold like the drift scalar — unlike the cross-source `at_risk`
  alarm).
- **The MCP `get_library_health` twin needed no change** — it already carries
  the full `custody.conflicts` block.

Tests: `tests/test_cli.py` (surfaces, converges with `doctor`, stays off the
drift axis, clears after `reconcile --keep-held`, honest `0`, source-scopes);
`tests/test_maintain.py` (the `custody_snapshot` primitive and its `0` default).

#### The `maintain` delta/trend leg (H283)

The conflict scalar differenced over time — the at-risk (H267/H268) machinery
lifted to the conflict axis:

```text
scrolls maintain        →  "conflicts_headline": "_Conflicts: 1 (▲1 since last run)._"
scrolls maintain --trend →  trend.conflicts_headline: "_Conflicts: 0 (▼1 over 3 runs)._"
```

- **`compute_delta`** subtracts the scalar — `delta["conflicts"]` is the
  cross-run `{before, after, change}` (degrade-safe: a pre-H279 baseline reads
  `0`, a first run reads `null`, exactly as the other scalars do).
- **`compute_trend`** differences it across the window — a `conflicts_change`
  axis beside `at_risk_change`, telescoping to the per-run deltas a worker reads
  back from `--history` (pinned in `tests/test_custody_convergence.py`).
- **`conflicts_headline`** renders the readable line (the conflict twin of
  `at_risk_headline`): `▲` a rise (more held items carry an unresolved peer
  divergence — worse), `▼` a fall (a resolution cleared one — better), an
  explicit `no change`, and a bare `_Conflicts: N._` when there is no baseline
  (first run / scoped non-persisting pass / <2-run trend — the H267 honesty).
- **Resolution-aware and source-scopable** (`maintain --source <S>`, unlike the
  whole-library-only `at_risk` line). End to end: a divergent peer import reads
  `▲1 since last run`; a `reconcile --keep-held` reads `▼1`; `--trend` distills
  the window.
- **Never a `posture` trigger.** A peer divergence moves neither the integrity
  score nor the drift axis (the held copy is never overwritten — custody §2.4),
  so the posture stays integrity-only (the H115/H267 precedent).
- **MCP twin.** `run_maintenance` carries the line; like `at_risk_headline` it
  embeds the delta's signed change, so it is run-position-dependent and the
  MCP↔CLI convergence test strips it beside `delta`/`recorded_at` (a documented
  distinction from the position-independent `headline`).

Tests: `tests/test_maintain.py` (renderer, delta, trend, and the report /
`--history` / `--trend` / `--source` integrations);
`tests/test_custody_convergence.py` (the conflict axis telescopes with drift /
coverage / staleness / at-risk); `tests/test_mcp.py` (the `run_maintenance`
field).

### Resolution: keep-held (H276, ADR 0105)

`scrolls reconcile <id> --keep-held` is the operator act that closes the loop —
*choose a winner, record the supersession, never destroy the prior capture*:

```bash
scrolls reconcile <id> --keep-held              # affirm the held copy
scrolls reconcile <id> --keep-held --dry-run    # predict, write nothing
```

- **Records, never rewrites.** It appends a typed `resolved` conflict-axis event
  (`custody.resolution_event` — `prior_hash` = the affirmed held copy,
  `observed_hash` = the rejected incoming) that supersedes the open conflict:
  `latest_conflict_events` reads the `MAX(id)` over the conflict axis
  (`conflict` *and* `resolved`), and `unresolved_conflicts` keeps an item only
  while its latest axis event is still an open `conflict`. One resolution
  therefore clears every read surface at once — `doctor`, the `_Conflicts:_`
  lines, the `status` scalar, and the MCP twin all fold that one predicate.
- **The held copy is never overwritten** (raw is sacred — custody §2.4): its
  content and `content_hash` are provably untouched; `reconcile` only appends a
  ledger event.
- **The original `conflict` event survives** (append-only): `--status conflict`
  still shows *when* a peer disagreed; `--status resolved` shows the operator
  decision. The resolution is a new row, not an edit.
- **Opt-in, idempotent, dry-run-able, CLI-only.** A bare `reconcile <id>` is
  exit 2 (a resolution is a decision, not a default), and an unknown id is
  exit 1. A held item with no open conflict is a clean no-op, and a second
  `--keep-held` is a no-op (the latest axis event is already `resolved`).
  `--dry-run` emits the same decision payload plus `dry_run: true` and writes
  nothing (the `import bundle --dry-run` predict-the-write discipline). And
  the custody-changing write is an explicit operator act, not an ambient MCP
  capability — like `verify`.
- **Re-openable.** A genuinely new divergent import after a resolution appends a
  fresh `conflict` event and re-opens the alarm — new evidence of a new
  disagreement. The `resolved` event stays off the drift axis (the ADR 0104
  isolation).
- **Why keep-held shipped first** (the ADR 0105 decision):
  - The hash-compare predicate clears an *adoption* naturally (the held hash
    becomes the observed hash) but can never clear a keep-held (the held hash
    is unchanged), so keep-held needs an explicit recorded decision.
  - Adopting the peer's capture needs the incoming **content**, but the
    conflict event records only the incoming *hash* — the importer discarded
    the bytes.
  - Adoption therefore required re-supplying the content plus custody-safe
    prior-content archival (ADR 0098's deferred "re-capture-on-accept") — the
    heavier slice that shipped as H278.

Tests: `tests/test_custody.py` (the `resolution_event` shape, drift-axis
exclusion, clear-and-re-open behavior); `tests/test_cli.py` (resolve-and-clear
with the held copy untouched, idempotency, dry-run, the exit-2 gate, the
unknown-id exit 1, the no-conflict no-op, the surviving `conflict` row on
`history`).

### Resolution: accept-incoming and the `item_archive` recovery store (H278, ADR 0106)

The other direction — adopt the peer's capture. Because the incoming content is
in hand only at the merge, `--accept-incoming` is an **import-path** flag, not a
`reconcile` flag:

```bash
scrolls import items <file>  --accept-incoming             # adopt diverging items
scrolls import bundle <file> --accept-incoming             # adopt diverging bundle scrolls
scrolls import bundle <file> --accept-incoming --dry-run   # predict the adoptions, write nothing
```

- **Archive before replace, in one transaction.** `items.adopt_incoming`
  snapshots the prior row (model-complete `item_to_dict` JSON) into the
  `item_archive` table (schema v8) and updates the items row atomically, so a
  crash never loses the prior. This is the first import-path write that changes
  a held capture — custody-safe because the prior is archived, recoverable,
  never destroyed (raw is sacred, §2.4).
- **A `superseded` conflict-axis event** records `prior_hash` (the archived
  copy) and `observed_hash` (the adopted incoming), staying off the drift axis
  (the ADR 0104 isolation). The adoption clears the conflict on every read
  surface at once: the held copy now *is* the incoming and the latest axis event
  is a `superseded` — both gates of the shared `unresolved_conflicts` predicate
  agree.
- **Idempotent by construction.** Once adopted, the held copy equals the
  incoming, so a re-import is `unchanged` — no second archive, no second event,
  no special-casing.
- **Opt-in, loud, CLI-only.** Without the flag a conflict is surfaced and the
  held copy kept (the detection default); with it, the adoption rides a
  structured `adopted` list and a loud stderr warning (a held copy was
  replaced). Like `verify`/`reconcile`, the write and its recovery are
  operator-gated, not ambient MCP. The bundle `--dry-run` predicts the adoptions
  and writes nothing.
- **A local recovery store, not part of the lossless round-trip:** the
  `superseded` event travels in `export items`/`export bundle` (documenting the
  adoption and its prior hash) while the archived prior *bytes* stay local —
  until `--with-archive` (H280, below) lets them travel too.

Tests: `tests/test_db.py` (the v8 migration preserves the ledger);
`tests/test_custody.py` (the `supersession_event` shape, axis isolation, both
clearing gates); `tests/test_items.py` (`adopt_incoming` archives + replaces
atomically); `tests/test_cli.py` and `tests/test_bundle.py` (the import flags,
dry-run prediction, aggregate clearing, idempotency).

### The archive surface (H280–H282, H285; ADR 0106)

The recovery store grew its own read, transport, and retention surface.

#### Recovery reads — `archive list` / `archive show [--all]` (H278, H285)

- **`scrolls archive list`** is the recovery index: the priors an adoption
  replaced, with before/after hashes, newest first (`--id` scopes to one item).
- **`scrolls archive show <id>`** re-emits the latest archived prior as a
  re-importable `export items` line; **`--all`** (H285) emits *every* archived
  prior for the id as a JSONL stream, newest first (the `archive list` `id
  DESC` order) — the full recoverable history as re-importable lines, not just
  the head.
- **Convergence by construction:** `items.archived_snapshots` folds the snapshot
  column once (`latest_archived` is its head — `archived_snapshots(...)[0]`), so
  the two reads share one snapshot parse and `show <id>` is byte-identical to
  `--all`'s first line. An empty history is the same exit-1 could-not-recover as
  the single read — an empty stream is not a recovery. A CLI-only read, pre-v8
  tolerant, no schema change, no network.

#### The restore flow

- `archive show <id> | import items /dev/stdin --accept-incoming` re-adopts the
  archived prior, archiving the current copy in turn — recovery is symmetric.
- Since this doc's shipped narration was written, the deferred
  restore-by-version shipped as `scrolls archive restore [--hash|--at]` (H286)
  with the decide-before-you-restore `scrolls archive diff` (H288) — see
  `docs/cli.md` for their contracts.

#### The archive travels — `--with-archive` and `export`/`import archive` (H280)

- **`scrolls export bundle --with-archive`** appends an optional third
  `@generated` region — the in-scope items' `item_archive` snapshots — beside
  the items and events blocks (`bundle._archive_block`/`parse_bundle_archive`).
  Opt-in because the archive can be large and the `superseded` event already
  documents the adoption; **without the flag the bundle is byte-identical to a
  pre-H280 one**, so the round-trip / byte-identity guarantees are untouched.
- **`scrolls export archive` / `scrolls import archive`** are the whole-library
  JSONL siblings of `export events`/`import events`
  (`items.archived_records`/`dump_archive_export`/`import_archive`,
  `archive_export.load_archive_export`) — the third member of the lossless
  backup family: items, events, archive.
- **`import bundle` restores any archive block unconditionally** (the flag is an
  export concern only), deduped by `(item_id, prior_hash)` — the H67
  events-dedup precedent on the archive identity, covering within-batch
  duplicates and NULL `prior_hash` rows — so a re-import, or the overlapping
  union of two bundles, is a no-op. The `--dry-run` predicts the restore
  without writing (`preview_import_archive` mirrors the live import's dedup).
- **Deterministic and standalone.** Records are ordered
  content-deterministically (`archived_at`, `item_id`, `prior_hash`),
  independent of the per-library autoincrement id, so a re-export from a rebuilt
  library reproduces the block byte-for-byte — the lossless-round-trip reach of
  the recovery store. The archive stays a standalone store keyed by `item_id`
  with no held-row interaction (it only appends to `item_archive`), so — unlike
  the events restore — it needs no orphan split. No schema change; no network.

#### MCP read twins — `list_archived` / `get_archived` (H281)

Before these, an MCP-only agent could see *that* an adoption happened (the
`superseded` event via `get_scroll_history --status superseded`, the cleared
aggregate via `get_library_health`) but had no way to reach the recovery store
itself.

- **`list_archived(item_id=None)`** is the recovery index twin of `archive
  list`: each `{item_id, prior_hash, superseded_by, archived_at}`, newest first,
  scoped to one item or the whole archive — the same `{count, archived}` shape
  the CLI prints, folding the same shared `items.archive_entry_dict` serializer
  (convergence by construction). A clean, pre-v8, or uninitialized library is an
  honest empty block, never an error.
- **`get_archived(item_id)`** is the recovery snapshot twin of `archive show`:
  the most-recently superseded copy as the model-complete, re-importable
  `item_to_dict` snapshot (the same shape an `export items` line carries),
  folding the same `items.latest_archived` the CLI reads — so an agent can
  recover the prior bytes and hand them back to a CLI
  `import items … --accept-incoming` to restore. A no-prior item, an unknown id,
  or a pre-v8 library is an error (the could-not-recover signal, the MCP twin of
  `archive show`'s exit 1).
- **The write stays operator-gated** (custody §2.4): the adoption and the
  symmetric restore are shell acts, not ambient MCP capabilities. Read twins
  only; no schema change, no network.

#### Retention — `archive prune` (H282)

The `item_archive` is append-only and unbounded — every adoption (and every
symmetric restore) appends — so `scrolls archive prune (--before ISO | --keep N)
[--apply]` bounds it.

- **The custody rationale** (the decisive question: is pruning a custody
  violation? — answered **no**): raw-is-sacred (§2.4) protects the **held**
  copy; a superseded prior is a *deliberate replacement* the operator already
  chose, and the archive is a recovery convenience, not the root of trust. So
  dropping old snapshots is custody-safe provided the act is explicit,
  predictable, and never touches a held row: it only ever DELETEs from
  `item_archive`; the items table and the custody ledger are untouched (a test
  pins the held copy byte-for-byte intact and the ledger unchanged across a
  prune).
- **Two mutually exclusive policies, exactly one required** (a bare `prune`, or
  both, is exit 2 — the `reconcile <id>` opt-in gate):
  - `--before ISO` — drop priors archived *strictly before* the boundary
    (date-only ok → that day's UTC midnight, the `verify --stale-before`
    normalization via `parse_since`). The time-based policy; it **may** drop an
    item's latest prior — an explicit, honest consequence (`archive show` then
    could-not-recovers for it).
  - `--keep N` — per item, keep the most recent N priors and drop the rest.
    N>=1 (`--keep 0` is rejected, as is a malformed `--before` ISO), so the
    latest prior **always survives** a keep-prune and `archive show <id>` keeps
    recovering it — a recovery invariant the count policy guarantees and the
    time policy deliberately does not.
- **Report-only by default** (the H245/H273 dry-run discipline): a bare run
  predicts the drop set (`matched`) and writes nothing (`dropped: 0`,
  `applied: false`); `--apply` performs the deletion (`dropped == matched`) and
  warns loudly on stderr (a recovery store was shrunk, even though the operator
  asked). The read-only preview (`items.select_prunable_archive`) and the write
  (`items.prune_archive`) fold one pure `_select_prunable`, so the preview
  predicts the write exactly.
- **Idempotent and CLI-only.** A second `--apply` finds the rows gone and drops
  0; a custody-changing write, like `verify`/`reconcile`. No schema change, no
  network — a deterministic DELETE over the local recovery store.

Archive-surface tests: `tests/test_items.py` (readers, restore dedup, prune
preview ≡ apply, the held-row + ledger untouched pins);
`tests/test_archive_export.py` (JSONL framing and round-trip);
`tests/test_bundle.py` (`--with-archive`, byte-identical re-export, idempotent
restore, dry-run); `tests/test_cli.py` (the `archive` commands and
`export`/`import archive` end to end); `tests/test_mcp.py` (the read twins and
their CLI convergence ties).
