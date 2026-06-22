# 0106: `--accept-incoming` adopts a diverging capture on the import path, archiving the prior copy — the content-bearing reconcile resolution

Date: 2026-06-22

Status: accepted

## Context

ADR 0105 shipped the **safe** direction of the reconcile resolution —
`scrolls reconcile <id> --keep-held` affirms the held copy and records a
`resolved` conflict-axis event — and deliberately **deferred** the
content-bearing direction, `--accept-incoming` (adopt the peer's capture). It
named exactly why:

> `--accept-incoming` would adopt the peer's capture — *re-render from the
> incoming content*, recording a supersession that keeps the prior content
> recoverable. But the conflict event records only **hashes**
> (`prior_hash`/`observed_hash`), never the incoming *content*: the importer
> computed the incoming `content_hash`, surfaced the divergence, and discarded
> the incoming bytes (the held copy was never overwritten). At `reconcile` time
> the incoming content is **gone**, so accept-incoming genuinely requires
> **re-supplying** it (a re-import with an accept flag, or a content-bearing
> conflict record) plus the custody-safe prior-content archival ADR 0098
> deferred as "re-capture-on-accept".

This record is that deferred slice (roadmap H278). It is the **first
import-path write that changes a held capture**, so it must resolve two design
questions ADR 0105 left open:

> **(1)** Where does the incoming content come from, given the ledger stored
> only its hash?
>
> **(2)** How is the prior capture kept recoverable, given that raw is sacred
> (custody §2.4) — an adoption may *replace* a held copy but must never
> *destroy* it?

## Decision

### `--accept-incoming` lives on the **import path**, not on `reconcile`

The two reconcile directions diverge precisely on *what content is in hand*:

- **`reconcile <id> --keep-held`** needs nothing beyond data already held — it
  affirms the held copy. CLI-only, ADR 0105.
- **`--accept-incoming`** needs the incoming *content*, which the conflict event
  never stored. The one place the content **is** in hand is the **merge**: the
  importer is parsing the peer's full `ScrollItem` rows at that moment. So the
  flag belongs on the importers — `scrolls import items <file> --accept-incoming`
  and `scrolls import bundle <file> --accept-incoming` — re-supplying the content
  by re-running the import with the flag. A `reconcile --accept-incoming` is
  *impossible by construction* (the content is gone at reconcile time); the
  honest home is the import path.

This is the shape ADR 0105 anticipated ("a re-import with an accept flag"). The
flag is **opt-in**: without it a conflict is surfaced and the held copy kept
(the ADR 0104/0105 default); with it, a conflict is *adopted*.

### Adoption replaces the held row but **archives the prior copy first** (schema v8)

Raw is sacred (custody §2.4): an adoption may replace what we hold, but the
prior capture must remain recoverable — it is itself a deliberately-held
artifact. So the adoption is **not** a destructive overwrite-in-place. A new
append-only table **`item_archive`** (schema v8) snapshots the prior row before
it is replaced:

```sql
CREATE TABLE item_archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    archived_at TEXT NOT NULL,
    prior_hash TEXT,        -- the archived copy's content_hash (before)
    superseded_by TEXT,     -- the incoming content_hash that replaced it (after)
    snapshot TEXT NOT NULL  -- json.dumps(item_to_dict(prior)) — model-complete
)
```

The `snapshot` is the **model-complete** `item_to_dict` JSON — the same lossless
shape `export items` writes — so recovery round-trips through the importer the
library already trusts (`item_from_dict`), carrying no new serialization. The
single primitive `items.adopt_incoming(db_path, incoming, *, archived_at)` does
the archive insert **and** the items `UPDATE` in **one transaction**, archiving
before replacing, so a crash never leaves the row replaced with the prior
capture unsaved. It returns the prior `ScrollItem` so the caller records the
event with the archived `prior_hash`.

### Adoption records a `superseded` conflict-axis event distinct from `resolved`

A new status **`custody.SUPERSEDED_STATUS = "superseded"`** joins the conflict
axis (`CONFLICT_AXIS_STATUSES = (conflict, resolved, superseded)`), with the
pure builder `custody.supersession_event(item_id, *, prior_hash, incoming_hash,
now)`: `prior_hash` = the archived prior copy (recoverable), `observed_hash` =
the adopted incoming copy (the new held content). It is distinct from `resolved`
because the two decisions differ in *what they did to the content*: `resolved`
affirms the held copy (no content change), `superseded` adopts the incoming one
(the held content **becomes** the incoming, the prior archived).

It clears the conflict on **both** gates the resolution-aware predicate
(`unresolved_conflicts`, ADR 0104/0105) folds:

- the **status gate** — the latest conflict-axis event is now `superseded`, not
  an open `conflict`; and
- the **hash gate** — the held copy *is* the incoming, so the held
  `content_hash` equals the event's `observed_hash` (the H275 mechanism).

Both agree, so the divergence clears across **every** conflict surface at once —
`doctor`'s `custody.conflicts`, the `_Conflicts:_` briefing line on both bundle
forms + `context`, `status`'s `custody.conflicts` scalar, the MCP
`get_library_health` twin — because they all fold the one shared predicate.

`superseded` stays **off the drift axis** (`latest_events` reads only
`CUSTODY_STATUSES` — the verify verdicts), exactly the ADR 0104 isolation kept on
the adopt axis. `LEDGER_STATUSES` extends automatically, so `history --status
superseded` (CLI + MCP) is a first-class read. The original `conflict` event, if
one was recorded by a prior plain import, is **never removed** (append-only) —
`history --status conflict` still shows *when* a peer disagreed.

### Idempotent by construction; dry-run-able; recoverable through existing paths

- **Idempotent.** Once adopted, the held copy *is* the incoming, so a re-import
  of the same content yields `merge_item == "unchanged"` — no second adoption,
  no second archive row, no second event. No special-casing: idempotency falls
  out of the content-hash compare the merge already runs.
- **Dry-run-able** on the bundle importer (which has `--dry-run`):
  `_preview_merge_items` predicts the *adopted* set (the held copies a live merge
  would replace) and writes nothing — the held→incoming transition prediction,
  the H245/H273 "predict the write effect" discipline on the adopt axis.
  `import items` has no dry-run today, so accept-incoming there is live-only
  (consistent with its surface).
- **Recoverable through existing infrastructure.** `scrolls archive list`
  indexes the prior captures an adoption replaced (newest first, `--id` scopes);
  `scrolls archive show <id>` re-emits the latest archived prior as a
  re-importable `export items` JSONL line. So **restore is symmetric**: `archive
  show <id> | import items /dev/stdin --accept-incoming` re-adopts the prior copy
  (archiving the current one in turn). No bespoke restore command — recovery is
  accept-incoming of the archived snapshot.

### Disposition buckets; CLI-only

The merge returns `{imported, skipped, unchanged, conflict, adopted}` plus the
structured `adopted` id list. Under accept mode a divergence counts under
`adopted` (a write), not `skipped`/`conflict`, so the buckets `imported +
unchanged + adopted` total the input; the `skipped == unchanged + conflict`
invariant still holds (`conflict == 0` under accept). The adoption is loud on
stderr (`_warn_adopted`) — a held copy was replaced, a custody signal even though
the operator asked for it. Like `verify`/`reconcile`, the importers and `archive`
are **CLI-only** for this write — a custody-changing write is an explicit
operator act (custody §2.4), not an ambient MCP capability.

## Consequences

- The conflict-on-import theme is now complete on **both** resolution
  directions: keep-held (ADR 0105, affirm the held copy) and accept-incoming
  (this ADR, adopt the incoming copy). Detect → read → **resolve** closes for
  the full decision space.
- A held capture can now be *changed* on the import path — a first for Scrolls —
  but never *destroyed*: the prior copy is archived and recoverable, so the
  custody guarantee (we can always answer "what did we hold, and can we get it
  back?") survives the one write that replaces a capture.
- The archive is a **local recovery store**, not part of the lossless
  export/import round-trip: `export items`/`export bundle` carry the current held
  rows + the ledger (the `superseded` event travels, documenting the adoption and
  its prior hash), while the archived prior *bytes* stay local. The byte-stable
  round-trip guarantee for held items + events is unaffected.
- Verified offline: `tests/test_db.py` (the v8 migration preserves the ledger);
  `tests/test_custody.py` (the `supersession_event` shape + serializer
  round-trip, off the drift axis, supersedes the conflict, clears
  `unresolved_conflicts` on both gates); `tests/test_items.py` (`adopt_incoming`
  archives + replaces atomically, the archive index + recovery read, the
  symmetric round-trip restores the prior byte-for-byte); `tests/test_cli.py` and
  `tests/test_bundle.py` (`import … --accept-incoming` adopts + archives + records
  + clears the aggregate, idempotent, the bundle dry-run predicts without
  writing, `archive list`/`archive show`, the show→import round-trip restores).

## Deferred

- **The archive in portable bundles.** ~~Carrying the archived prior captures in
  `export bundle`/`export items` (so "take it with me" includes the recovery
  store) is a clean extension, left until a workflow needs the prior bytes to
  travel; the `superseded` event already travels with the ledger.~~ **Shipped
  (roadmap H280):** `scrolls export bundle --with-archive` carries the in-scope
  archive in an optional third `@generated` block (opt-in — a default bundle stays
  byte-identical to a pre-H280 one), `scrolls export archive`/`import archive` are
  the whole-library JSONL siblings of `export events`/`import events`, and `import
  bundle` restores any archive block unconditionally, deduped by `(item_id,
  prior_hash)` (the H67 events-dedup precedent). No schema change.
- **An MCP `import … --accept-incoming` write twin.** The custody-changing
  *write* (and the symmetric restore via `archive show | import …
  --accept-incoming`) stays operator-gated (custody §2.4), like
  `reconcile`/`verify`. **The *read* side shipped (roadmap H281):** `list_archived`
  (the recovery index — what an adoption superseded, with the hash before/after and
  when, the twin of `scrolls archive list`) and `get_archived(item_id)` (the
  model-complete, re-importable prior snapshot, the twin of `scrolls archive show`)
  travel over MCP, folding the same `items.archive_entry_dict`/`latest_archived` the
  CLI reads (convergence by construction) — beside the already-travelling
  `history --status superseded` and the cleared conflict aggregate. The write twin
  remains deferred.
- **`archive prune` / retention.** ~~The archive is append-only and unbounded; a
  retention policy (drop snapshots older than N, or beyond K per item) is left
  until the store's growth is shown to matter.~~ **Shipped (roadmap H282):**
  `scrolls archive prune (--before ISO | --keep N) [--apply]` bounds the store —
  `--before` drops priors archived strictly before a boundary (the `verify
  --stale-before` precedent), `--keep N` keeps the most recent N priors per item
  (N>=1, so `archive show` always survives a keep-prune). It is **report-only by
  default** (predict the drop set, write nothing — the H245/H273 dry-run discipline);
  `--apply` deletes and warns loudly. Exactly one policy is required (the `reconcile`
  opt-in gate), it is idempotent, and it **only ever DELETEs from `item_archive`** —
  the held items and the custody ledger are untouched, because the archive is a
  *recovery convenience*, not the root of trust (a superseded prior is already a
  deliberate replacement — custody §2.4). CLI-only, no schema change. The
  read-only `items.select_prunable_archive` (the preview) and the `items.prune_archive`
  write fold the one pure `_select_prunable`, so the preview predicts the write
  exactly. Verified offline: `tests/test_items.py` (the per-item keep / before
  selection, the preview ≡ apply drop set, idempotency, held-row + ledger untouched)
  and `tests/test_cli.py` (the policy gate, report-only default, `--apply` + warn,
  the keep>=1 recovery invariant, the before-policy whole-archive clear).
- **`archive show --all` — the full archived history.** ~~`archive show` emits the
  latest archived prior; emitting the full archived history for an id is left until a
  multi-supersession workflow needs it.~~ **Shipped (roadmap H285):** `scrolls archive
  show <id> --all` emits **every** archived prior for the id as a JSONL stream, newest
  first (the `archive list` `id DESC` order), each line the model-complete `item_to_dict`
  snapshot — so a multi-supersession item's whole recoverable history backs up as
  re-importable `export items` lines, not just the head. The decisive choice: a new
  `items.archived_snapshots(db_path, item_id) -> list[ScrollItem]` (the list-returning
  sibling of the scalar `latest_archived`), and `latest_archived` refactored to return
  its head, so the single-snapshot recovery and the full-history read share one
  snapshot-parsing read and never disagree (convergence by construction). Default (no
  `--all`) unchanged; an empty history is the same exit-1 could-not-recover as a
  never-superseded id. CLI-only read, no schema change. Verified offline:
  `tests/test_items.py` (`archived_snapshots` all-priors-newest-first, `latest_archived`
  is its head, `[]` for never-superseded, pre-v8 tolerant) and `tests/test_cli.py`
  (`--all` N lines for an N-adoption item, default one line, convergence with the head,
  never-superseded exit-1).
- **Restore-by-version.** Restoring a *specific* older archived version (not only the
  latest) is left until a multi-supersession workflow needs it (roadmap H286, a selector
  — `--hash`/`--at` — over the H285 `archived_snapshots` stream, feeding the existing
  accept-incoming adoption write).
