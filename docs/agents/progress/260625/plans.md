# Plans — 2026-06-25 (historical; superseded)

*Reconstructed: 2026-07-26 — the direction set at this check-in, kept as the
historical record. **Superseded by `../260722/plans.md`:** automated
development was accidentally re-enabled after this check-in and had
completed — and overshot — this entire sequence by 2026-07-05. The 3-day-plan
and week-plan sections below were moved here in full from
`docs/agents/autonomous-roadmap.md`, which no longer carries them; location
references were adjusted for the move, content otherwise verbatim. Note the
sections are the worker's 2026-06-27 re-derivation (its maintenance pass
pruned the original 2026-06-25 slotting), and their "Done — shipped early /
the lock let the run overrun" annotations were written by the overrunning
worker itself, not at the check-in.*

## Objectives as set then

1. Finish the content-identity surface-closure tail (**H344–H348**).
2. Then stop at the **assessment/recommendation gate** before choosing the
   next theme (stewardship over more slices).
3. Then the cap-8-style **enrichment-provenance depth theme** (re-derivable,
   provenance-complete enrichment).

## 3-day plan — 2026-06-27 → 2026-06-30

Forward-looking (re-derived 2026-06-27, the once-per-24h full re-derivation, at the
contract-consolidation mid-theme boundary — the prior 2026-06-25→06-28 day-by-day narrative was
pruned, its per-slice detail living in git + the roadmap's Shipped ledger per its maintenance-rule §4). Each day
ends on a committed, tested, clean stopping point; slips roll forward. MVP M1–M5, every post-MVP
custody theme, the **content-identity / near-duplicate custody theme** (H325–H362), the
**custody-posture theme** (H369–H373), and the **contract-consolidation theme** are
closed. That contract-consolidation pass replaced a *family* of per-surface tests with one
completeness-asserted invariant per cell (the H388 pattern). The shipped cells run from MCP-determinism through the
facet-aggregate drill (H388 MCP-determinism, H394 CLI-determinism, H395 round-trip, H396
regeneration-safety, H397 surface-parity, H398 completeness-honesty, H399 re-import-idempotency, H400
CLI↔MCP read-parity, H401 bundle-format briefing-parity, H402 reconcile-safety, H403 browse-filter drill,
H404 compiled-page custody-honesty, H405 importer conflict/adoption parity, H406 CLI↔MCP write-act parity,
H407 rank-explainability, H408 raw-immutability act-surface, H409 append-only custody-ledger, H410
stale-set drill, H411 facet-aggregate drill, H412 enrichment-provenance convergence, H413
recency-`last_checked` convergence, H414 could-not-check error-parity, H415 bundle-briefing ↔ live-audit
convergence, H416 preview ↔ live-run parity, H417 facet scope-composition convergence, H418
audit-aggregate ↔ browse-drill convergence, H419 compiled group-page classification marker, H420
truncation/scope-echo honesty, H421 context-briefing ↔ live-audit convergence, H422 live-act settle parity, H423 archive-selector recovery convergence, H424 per-source scoped audit-drill convergence, H425 compiled group-page custody-marker convergence);
the contract-consolidation queue is now closed through **H425**. No new adapters; run the assessment/recommendation gate before choosing the next slice.

- **Day 1 (2026-06-27): Done — H400 + H401 shipped.** H400 (`tests/test_cli_mcp_parity.py`): every MCP
  read tool has a CLI twin whose custody-bearing payload reads identically (the four inspect+aggregate
  twins `get_scroll`≡`show`, `get_link_graph`≡`graph`, `get_works`≡`works`, `get_library_health`≡`doctor`)
  or is a named exemption partitioning `_MCP_READ_TOOLS`. H401 (`tests/test_bundle_format_parity.py`):
  every custody briefing fact renders in **both** the Markdown and `--format html` bundle forms, pinned
  over an AST-checked `_BRIEFING_LINES` registry (the eleven lines minus a named `_STRUCTURAL` set);
  sabotages isolate to `{conflicts}` / `{duplicates}`. Suite **4270 passed**. The 3-day/week plans were
  re-derived (this section) per the once-per-24h maintenance rule.
- **Day 2 (2026-06-28): Done early — H402 + H403 + H404 shipped** (the lock let the H400/H401 run overrun
  into these slots). H402 reconcile-safety (a stale annotated compiled page is tombstoned, a plain one
  unlinked, across every reconcilable dir-kind keyed to `kb._GENERATED_DIRS`). H403 browse-filter drill
  (every `--fidelity`/`--drift`/`--strength`/`--content-duplicate` filter selects exactly the unfiltered
  rows at that axis value, keyed to `_BROWSE_FILTERS`). H404 compiled-page custody-honesty (every
  custody-bearing compiled page renders its `_Custody:`/`_By source:`/`_Attention:`/`_Refresh:` lines iff
  its scope warrants them, keyed to `kb._GENERATED_DIRS`/`_GENERATED_FILES`).
- **Day 3 (2026-06-29 → 2026-06-30): Done early — H405–H411 all shipped** (the lock let the run overrun
  through the whole forward queue): H405 (importer conflict/adoption parity), H406 (CLI↔MCP write-act
  parity), H407 (rank-explainability convergence), H408 (raw-immutability act-surface), H409 (append-only
  custody-ledger), H410 (stale-set drill), H411 (facet-aggregate drill), H412 (enrichment-provenance
  convergence) — **then H413–H416 also shipped this same span** (H413 recency-`last_checked` convergence,
  H414 could-not-check error-parity, H415 bundle-briefing ↔ live-audit convergence, H416 preview ↔ live-run
  parity; the lock let the run overrun through them). **Then H417 + H418 also shipped this same span**
  (H417 facet scope-composition convergence, H418 audit-aggregate ↔ browse-drill convergence), followed by
  H419 (compiled library group-page classification marker), H420 (truncation/scope-echo honesty), H421
  (context-briefing ↔ live-audit convergence), H422 (live-act settle parity), H423
  (archive-selector recovery convergence), H424 (per-source scoped audit-drill convergence), and H425
  (compiled group-page custody-marker convergence). The contract-consolidation queue is now closed; the next lead is the assessment/recommendation gate. Next once-per-24h full re-derivation **due 2026-06-28**.

---

## Week plan (more tentative) — through 2026-07-02

- **Closed this past week:** the **content-identity / near-duplicate custody theme**
  (H325–H362) — a genuinely new custody shape (byte-identical holdings under different ids):
  the `doctor` report, the `related` content edge, the per-item/work/browse/graph/aggregate
  surfaces, the `_Duplicates:_` readable line + trend, the `duplicate_prunes` suggested
  guidance, the import-time notice, and the full convergence + dogfood guard set across
  read/render/compile/MCP/import — report-only, never an auto-merge.
- **Closed — the custody-posture theme** (H369–H373): `doctor`'s `custody.posture` distils the
  seven custody blocks into one whole-library verdict (vision §3.1, ADR 0107) — read →
  render → travel → trend → converge, all shipped.
- **Closed — the contract-consolidation theme.** Each cell replaced a *family* of per-surface
  tests with one completeness-asserted invariant that auto-covers new surfaces (the H388 pattern).
  **Shipped:** H388 (whole-MCP determinism), H394 (CLI determinism), H395 (round-trip transport),
  H396 (regeneration-safety, ADR 0102), H397 (surface-parity), H398 (completeness-honesty, M2),
  H399 (re-import idempotency), H400 (CLI↔MCP read-parity), H401 (bundle-format briefing-parity),
  H402 (reconcile-safety), H403 (browse-filter drill), H404 (compiled-page custody-honesty, M2),
  H405 (importer conflict/adoption parity), H406 (CLI↔MCP write-act parity), H407
  (rank-explainability), H408 (raw-immutability act-surface), H409 (append-only custody-ledger),
  H410 (stale-set drill), H411 (facet-aggregate drill), H412 (enrichment-provenance convergence), H413
  (recency `last_checked` convergence), H414 (could-not-check G1 error-parity), H415 (bundle-briefing ↔
  live-audit convergence), H416 (preview ↔ live-run parity), H417 (facet scope-composition convergence),
  H418 (audit-aggregate ↔ browse-drill convergence), H419 (compiled group-page classification marker),
  H420 (truncation/scope-echo G2 honesty), H421 (context-briefing ↔ live-audit convergence),
  H422 (live-act settle parity), H423 (archive-selector recovery convergence), H424
  (per-source scoped audit-drill convergence), and **H425 (compiled group-page custody-marker convergence)**.
  **Forward queue:** assessment/recommendation gate before choosing another guard-cell family. The once-per-24h full
  re-derivation was **performed 2026-06-27**; the next is **due 2026-06-28**.
- The **budget/tier convergence guard cells H244–H249** remain valid regression guards but
  are explicitly **de-prioritized** — take a capability or forward-hardening slice first.
- A **new source adapter** is out unless it introduces a genuinely new custody *shape* (a new
  fidelity boundary, identity rule, or thread/canonical structure — vision §2.7);
  adapter-churn for its own sake loses to hardening.
- Explicitly **not** this week: new adapters (absent a new custody shape), productivity
  surfaces, paid research integrations.
