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
