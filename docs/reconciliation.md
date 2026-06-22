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

A reviewed `reconcile` resolution (choose a winner, record the supersession) and
a `doctor` scope-level conflict aggregate remain deferred (ADR 0104): detection
ships first, the obsidian *surface, don't rewrite* posture.
