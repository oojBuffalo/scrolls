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
  swallowed into a `skipped` count, and never an overwrite (custody vision §2.4).

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

A reviewed `reconcile` resolution (choose a winner, record the supersession)
remains deferred (ADR 0104, roadmap H276): detection → read ship first, the
obsidian *surface, don't rewrite* posture; a readable `_Conflicts:_` briefing line
is the next adjacent read.

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
held-filter + resolution-aware, honest no-op). A reviewed `reconcile` resolution
(H276) remains the last deferred leg of the theme.
