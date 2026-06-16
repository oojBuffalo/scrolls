# Autonomous roadmap & automation buffer

How the hourly autonomous worker (`work/scrolls-dev`) spends its runs. This is
the **scheduling layer** under `docs/product/prd.md` (direction) and
`docs/product/mvp.md` (scope). The cron worker and launcher live outside the
repo (`/Users/claw/.hermes/scripts/scrolls_hourly_progress_worker.sh` and
`…_launcher.sh`); this doc is the queue they should read.

**How to read the hour slots.** The launcher fires hourly but holds a lock, so a
run that overruns an hour causes later ticks to **skip, not overlap**. The
"hour-by-hour" buffer below is therefore an *ordered queue of intended coherent
slices*, not a promise that slot N starts exactly at hour N. A run picks the next
unstarted slice whose preconditions are met, finishes it to a real stopping
point (committed, tested, clean), and stops — even if that consumes several
nominal slots.

**Authority.** Slices are justified against `docs/custody-vision.md` and the
MVP. New adapters are out unless they introduce a new custody shape
(custody-vision §2.7). Anything not on the queue still loses to "finish the
half-done slice from the previous run first."

---

## 24h buffer (concrete) — 2026-06-16 → 2026-06-17

Ordered queue. `→ Mn` marks the MVP slice; `cap N` marks the PRD capability.

| Slot | Intended slice | Maps to |
| --- | --- | --- |
| H1 (2026-06-16) | **✓ shipped.** Sentinel boundary defined and implemented for compiled `library/` pages: pure helper `src/scrolls/generated.py` (`@generated`…`@end` fence, preserve user regions, tombstone stale-annotated pages) wired through `src/scrolls/kb.py`. Tests in `tests/test_generated.py`, `tests/test_kb.py`. See ADR 0102. | → M1, cap 6 |
| H2 | **✓ shipped (with H1).** KB compiler writes every generated region inside the fence; a re-compile replaces only the fenced content and keeps annotations outside it. `docs/library-format.md` regenerated (pinned examples now assert the generated body; new sentinel-fence example added). MCP `get_tag_page` reads the heading from the fenced body. | → M1, cap 6 |
| H3 (next) | **M1 extend to generated `agents/` files** (`src/scrolls/agents.py` / `agent install`): reuse `generated.write_generated` so a hand-annotated agent file is not clobbered. Note: `agents/` files round-trip through `_TARGETS` and are asserted by `tests/test_agents.py` + `test_library_format_names_every_generated_artifact` — update those. Tests. | → M1, cap 6 |
| H4 | **M1 wrap-up:** add a line to `docs/architecture.md` describing the refresh-safe regeneration boundary; confirm ADR 0102 consequences match what shipped. Full `uv run pytest`. Commit. | → M1, cap 6 |
| H5 | **M2 contract spec.** Write the anti-fabrication / search-completeness invariant into `docs/cli.md` (scope-honest results; "nothing found" ≠ "not checked") as the testable contract before touching code. | → M2, cap 7 |
| H6 | **M2 enforce on `search` + `list`.** A result over a filtered slice must not imply library-wide completeness; pin with `tests/test_search.py` / `tests/test_cli.py`. | → M2, cap 7 |
| H7 | **M2 enforce on `context` + `related` + `works`.** Same scope-honesty; tests in the matching suites. | → M2, cap 7 |
| H8 | **M2 enforce on `doctor`.** Custody report states what it did and did not verify (network-free vs would-need-refetch). Tests in `tests/test_doctor.py`. Full suite. Commit. | → M2, cap 1/7 |
| H9 | **M3 context budgets — design.** Specify the budget tiers for `scrolls context` (index/identity first → deep bodies on demand), reusing the same-work collapse already shipped. | → M3, cap 10 |
| H10 | **M3 implement budget flag.** Bound bundle size predictably; tests pin tiering and the collapse interaction. Update `docs/cli.md`. Commit. | → M3, cap 10 |
| H11 | **Buffer refresh checkpoint** (see maintenance rule). Re-read repo state, mark completed slots, append the next 24h of slices below H12, prune stale ones. | maintenance |
| H12–H24 | **M4 custody bundle** (scoped Markdown/HTML briefing carrying provenance + fidelity, lossless re-import), then **M5 dogfood proof** (the end-to-end flow). Break into vertical slices as H11's refresh decides. | → M4/M5, cap 9/11 |

If the queue empties before the day does, deepen tests/fixtures on the slice
just shipped or pick the next-highest PRD capability — never manufacture
cosmetic churn (CLAUDE.md, *Avoid trivial progress*).

---

## 3-day plan (tentative) — through 2026-06-19

- **Day 1 (2026-06-16):** M1 (refresh-safe generated artifacts, ADR 0102)
  shipped for compiled `library/` pages (H1+H2); remaining M1 is `agents/`
  files (H3) and the architecture-doc line (H4). M2 (completeness invariant)
  begins once M1 closes.
- **Day 2 (2026-06-17):** M2 finished and tested on every browse/audit surface;
  M3 (context budgets) shipped; M4 (custody bundle) designed with an ADR if the
  bundle format is consequential.
- **Day 3 (2026-06-18 → 2026-06-19):** M4 implemented with a round-trip fixture;
  M5 dogfood flow drafted and run offline against fixtures; capture a
  before/after custody score.

Each day ends on a committed, tested, clean stopping point. Slips roll forward;
the 3-day plan is re-derived at each buffer refresh.

---

## Week plan (more tentative) — through 2026-06-23

- Complete M1–M5 (the MVP) with the dogfood flow referenced from the vision's
  success section.
- Deepen provenance-complete enrichment (cap 8): classification + LLM concept
  summaries record inputs/method and regenerate deterministically; surface a
  confidence/recency marker (obsidian "confidence levels" adoption).
- Frame the hourly worker as scheduled **custody maintenance** (audit → drift
  recheck → regenerate views → report) once M1/M2 make regeneration and audit
  trustworthy — the obsidian "scheduled agents" adoption, custody-shaped.
- Consider a bi-temporal framing pass on drift events (captured-at vs
  source-changed-at) *only if* an agent workflow shows the event record is
  insufficient; otherwise keep deferred (MVP "out of scope").
- Explicitly **not** this week: new adapters, productivity surfaces, paid
  research integrations.

---

## Maintenance rule — keeping the 24h buffer fresh

The buffer rots if nobody refreshes it. The rule:

1. **Every run, before stopping**, the worker (or the agent it drives) checks
   whether the 24h buffer's lead slot is done. If the buffer has fewer than ~6
   un-started slots, it **appends** new concrete slices derived from the MVP and
   PRD so the lead always covers the next ~24h.
2. **At least once per 24h** (slot H11 above, or the first run after midnight
   UTC), do a full refresh: mark completed slots, prune slices overtaken by
   events, re-derive the 3-day plan, and re-confirm the week plan still maps to
   `docs/product/mvp.md`.
3. **Date discipline:** always write absolute dates (`YYYY-MM-DD`), never
   "today" — this doc is read later (obsidian anti-pattern: `date: today`).
4. **Provenance:** when a slice ships, the commit subject and any ADR are the
   record; this doc points forward, not backward. Don't turn it into a
   changelog — git is the changelog.
5. **No invented work:** a slice goes on the buffer only if it has a concrete
   implementation path and maps to a PRD capability. If none qualifies, the
   correct buffer entry is "report blocker," not filler.

---

## How this maps to the PRD/MVP and current priorities

| Roadmap horizon | PRD capability | MVP slice |
| --- | --- | --- |
| 24h H1–H4 | cap 6 (refresh-safe artifacts) | M1 + ADR 0102 |
| 24h H5–H8 | cap 7 (completeness invariant) | M2 |
| 24h H9–H10 | cap 10 (context budgets) | M3 |
| 24h H12+ / Day 3 | cap 9 (custody bundle), cap 11 (dogfood) | M4, M5 |
| Week | cap 8 (re-derivable enrichment), scheduled maintenance | post-MVP |

The two obsidian-second-brain adoptions (M1 refresh-safe regeneration, M2
completeness invariant) are intentionally first in the queue: they are the
decision-grade, custody-deepening slices, and everything later reads cleaner
once regeneration is non-destructive and results are scope-honest.
