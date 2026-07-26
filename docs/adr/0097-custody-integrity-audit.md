# 0097: Custody integrity audit and fidelity tiers

Date: 2026-06-15

Status: accepted

*Amended: 2026-07-26 — the vision docs were merged into `docs/vision.md`
(§ numbering preserved); the path reference below was updated. Decision
content unchanged.*

## Context

The custody-first vision (`docs/vision.md`) names the **custody
integrity audit** as the load-bearing first capability: `scrolls doctor` should
graduate from "find broken links / missing scrolls" to a per-library *custody
report* — a fidelity distribution, categorized integrity findings, and an
aggregate score — and `fidelity` should become a queryable facet. A first pass
(commit c81bffe) landed the shape of this but shipped on a **red suite** and
with three real defects:

1. **Double counting.** `_check_custody_integrity` re-detected missing rendered
   scrolls and incremented the same `report["issues"]` counter the structural
   `_check_missing_scrolls` already drives, so a single deleted scroll counted
   as two issues and broke `doctor`'s exit-code contract (two existing tests
   went red).
2. **A facet that always lied.** `_fidelity_counts` loaded items through
   `_load_facet_columns`, which selects only `id, tags, concepts` — none of the
   fields `get_fidelity` reads — so every item collapsed to `reference`. A weak
   `or`-chained assertion masked it.
3. **Dead checks.** Two of the four custody checks (`body_not_rederivable`,
   `full_fidelity_without_raw_or_hash`) could never fire, because `get_fidelity`
   only returns `full` when a body is present.

The vision's slice 5 also explicitly asked for "an ADR so future drift-detection
and bundle work reference a stable vocabulary." This record is that vocabulary.

## Decision

**Fidelity tiers** (`doctor.get_fidelity`, network-free, derived not stored):

- `full` — a re-derivable body is held (`raw_text`, or `extracted_text` paired
  with a `content_hash` that fingerprints it) *and* the item reached
  `fetched`/`rendered`. The body regenerates and a future re-fetch has a hash to
  diff.
- `partial` — some content survives (`raw_text`, `extracted_text`, or `summary`)
  but not enough for `full` (no hash, or still at `detected`). A degraded but
  honest capture. (Fixed a gap: raw content held at `detected` stage previously
  fell through to `reference`.)
- `reference` — only the pointer and provenance are held, no content. Honest
  custody of a thing held by reference, **not** a failure.

**Custody audit** lives entirely under `report["custody"]`, deliberately
*separate* from the repairable-drift accounting (`issues`/`fixed`) that drives
`doctor`'s exit code:

- `tiers` — the fidelity distribution.
- `findings` — per-item integrity violations, each deterministic and offline:
  - `missing_scroll` — a `rendered` item whose scroll file is gone. The
    *repairable* side is `_check_missing_scrolls` (it rewrites the file and owns
    the exit code); the custody view mirrors it for the score but **never
    double-counts** `issues`.
  - `unrederivable_hash` — a `content_hash` is stored but neither `raw_text` nor
    `extracted_text` survives: a fingerprint of content we can no longer
    reproduce or verify.
  - `missing_provenance` — content is held (full/partial) but neither `url` nor
    `source_id` records where it came from.
- `issues` — count of items carrying ≥1 finding (custody-local, not the
  structural counter).
- `score` — `round(100 × clean / total)`, `100` for an empty library. A
  reference-only item with complete provenance is clean, so honest degradation
  never lowers the score; the score measures *integrity*, not *fidelity mix*.

A true recompute-and-verify of `content_hash` is **not** done here: each adapter
hashes a different, unstored input (web hashes the body, pdf the blob, most a
composed string), so there is no generic re-derivation. `unrederivable_hash` is
the honest network-free proxy — we assert a body must exist to back any hash —
and a real diff belongs to the later `fetch --recheck` drift slice.

**Exit code unchanged.** Custody findings are a *report*, not repairable drift,
and `doctor` cannot fix them, so they stay out of the `issues == fixed → exit 0`
contract. Whether custody violations should gate exit is deferred to the drift
slice that will have somewhere to record them.

**Fidelity facet** reads its own columns (`_load_fidelity_columns`:
`raw_text, extracted_text, summary, content_hash, stage`), scoped by the same
`item_filters` as search, ranked like every other facet.

## Consequences

- `scrolls doctor --json` carries a `custody` block (`score`, `issues`, `tiers`,
  `findings`) on every run; the structural `issues`/`fixed`/exit code are
  byte-for-byte unchanged, so all prior doctor behavior is preserved.
- `scrolls facets fidelity` (and the MCP `list_facets`) now report a truthful
  tier distribution — "you hold N full, M partial, K reference" in one command.
- The custody vocabulary (`full`/`partial`/`reference`, the three finding codes,
  the score definition) is now stable for the drift/rot detection slice
  (`fetch --recheck`) to report into and for bundle export to carry.
- Verified offline: `tests/test_fidelity.py` (tier derivation incl. the
  raw-at-detected and lone-hash edges, the facet reading the right columns),
  `tests/test_doctor.py` custody section (each finding code, the
  no-double-count regression, the percent-clean score, the CLI block), and the
  facet-shape tests in `tests/test_cli.py`/`tests/test_mcp.py`.
