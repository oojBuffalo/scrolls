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
| H3 | **✓ shipped.** M1 extended to generated `agents/` files: `install_agent_docs` now writes through `generated.write_generated`, with skill frontmatter as a regenerated *header* pinned at byte 0 (new `header=` arg on `splice`/`write_generated`) and the shared body as the fenced region. A note after `@end` survives a reinstall; `SKILL.md` keeps a suffix annotation, header-less `AGENTS.md` either side. Tests in `tests/test_agents.py`, `tests/test_generated.py`; `_TARGETS` now maps relpath→header. | → M1, cap 6 |
| H4 | **✓ shipped (with H3).** `docs/architecture.md` Agent-install entry now describes the refresh-safe boundary; `docs/library-format.md` agents section documents the contract and points at `test_agent_install_preserves_annotation_outside_the_fence`. ADR 0102 consequences confirmed: both `kb.py` and `agents.py` now carry the generated-vs-user boundary it predicted. Full `uv run pytest` green (2297). **M1 complete.** | → M1, cap 6 |
| H5 | **✓ shipped.** M2 contract written into `docs/cli.md` as a new top-level "The completeness contract" section, split into **G1** (honest absence / honest failure — empty ≠ error, nothing fabricated) and **G2** (honest scope / truncation, the H6–H8 enforcement target). G1 is locked *now* by a cross-surface invariant module `tests/test_completeness.py` (search/list/related/works/context/doctor); cross-referenced from `docs/library-format.md` "What consumers may rely on". Full suite green (2318). | → M2, cap 7 |
| H6 | **✓ shipped.** M2 G2 enforced on `search` + `list` via an opt-in `--stats` envelope. New pure builder `src/scrolls/scope.py` (`scope_envelope` → `{scope, stats, results}`, consistent with the `works`/`graph` stats companion); `search.py` gains `count_matches` (the honest denominator past the cap, so `truncated` iff `matched > returned`); `list` gains `--limit`. The bare array stays the default, so G1's locked `[]` empty form and the CLI/MCP list contract never regress (the documented additive resolution of the G1/G2 tension). Tests: `tests/test_scope.py`, `tests/test_search.py` (count_matches), `tests/test_cli.py` (scope echo, truncation, opt-in default, empty-scope honesty). `docs/cli.md` G2 marker flipped for these two surfaces; `README.md` updated. Full suite green (2347). | → M2, cap 7 |
| H7 | **✓ shipped. M2 enforce on `context` + `related` + `works`.** `related`: `--stats` echoes anchor + limit + truncation, `count_related` the past-the-cap denominator. `works`: an always-on `scope` companion in `to_payload` naming the `--min` floor or the resolved `ref` anchor (no `--stats` flag — `works` already emits an object, no bare array to protect; uncapped, so the floor *is* its truncation story). `context`: a `Coverage:` line over `count_matches` — `all N` vs `top N of M matching scrolls` — with the empty bundle's G1 form untouched. CLI + MCP twins share the builders, so both surfaces carry the honesty. Tests in `tests/test_works.py`, `tests/test_context.py`, `tests/test_mcp.py`; `docs/cli.md` G2 markers flipped; README updated. | → M2, cap 7 |
| H8 | **✓ shipped. M2 enforce on `doctor` — M2 complete.** The custody `drift` block now states what it verified: `basis` (`last_verify` — verdicts read from the ledger, not re-checked live this run), `as_of` (the freshest verdict timestamp the picture rests on, `null` when none), and `unverified` (held items the ledger has no verdict for — never checked, so unknown, **not** clean). A reader holding only the report can tell "confirmed unchanged at the last verify" from "never checked". Tests in `tests/test_doctor.py` (drift unverified/basis/as_of, no-ledger-table honesty); `docs/cli.md` G2 marker flipped — **G2 now enforced across every read surface.** Full suite green (2365). | → M2, cap 1/7 |
| H9 | **✓ shipped (with H10).** M3 design folded into the implementation: the budget tiers are specified in `docs/cli.md` (the `--budget` paragraph) and the `src/scrolls/context.py` module docstring — `index`/`connected`/`full`, strictly nested, identity/index first → deep bodies on demand (the obsidian L0–L3 adaptation). No ADR: the tier set is a small, reversible CLI surface documented in `cli.md`, the same way the `--stats` envelope and Coverage line were (no ADR for H6–H8). | → M3, cap 10 |
| H10 | **✓ shipped. M3 complete.** `scrolls context --budget {index,connected,full}` bounds bundle *depth* through nested tiers (`BUDGET_TIERS` in `context.py`): `index` is the catalog (Best Matches + Links, no graph build), `connected` adds `## Connected scrolls`, `full` (default) adds `## Excerpts` — the current bundle, unchanged. A tier below `full` carries a `_Budget:_` note disclosing what it held back (the depth-axis counterpart to the Coverage line's scope honesty; the two hold independently). Same-work collapse (ADR 0101) is index-level, so it holds at every tier. CLI + MCP twins share `build_context`. Tests in `tests/test_context.py` (10 new: tiering, default=full unchanged, budget note, coverage×budget independence, collapse×budget, empty-bundle/invalid-budget honesty) + `tests/test_mcp.py` (twin). `docs/cli.md`/`README.md` updated. Full suite green (2375). | → M3, cap 10 |
| H11 | **✓ executed in the 2026-06-16 run that shipped H9/H10.** Buffer refresh checkpoint (maintenance rule): M1, M2, and M3 are all shipped ahead of schedule (M3 was the Day-2 target). M4 broken into the concrete vertical slices H12–H15 below; M5 into H16–H17. 3-day/week plans re-derived. | maintenance |
| H12 | **M4 custody bundle — design (ADR 0103).** Specify the portable *briefing* bundle distinct from `export items` (ADR 0082, lossless JSONL of index rows): a scoped, self-contained Markdown/HTML slice carrying provenance + fidelity *per item*, re-importable losslessly. Decide the manifest shape (the embedded canonical rows the importer reads vs. the human/agent-readable briefing body), the scope selector (query/facets, reusing `search_items`), and the round-trip contract (re-import reconstructs index rows like `import items`, `INSERT OR IGNORE`). ADR because the on-disk format is consequential and shareable. | → M4, cap 9 |
| H13 | **M4 implement `scrolls bundle export`.** Emit the self-contained bundle for a scope (query + the `search`/`context` facets) to a path: briefing body (best matches, fidelity tier, provenance per item) + an embedded lossless block the importer round-trips against. Tests pin the bundle contents (provenance + fidelity present per item; scope honored). `docs/cli.md` + README. | → M4, cap 9 |
| H14 | **M4 implement `scrolls bundle import` + round-trip.** Re-import reconstructs index rows from the embedded block (dedupe by id, never overwrite — the ADR 0099 lossless invariant). A fixture proves export→import round-trips the custody state byte-for-byte and that the bundle is self-describing offline (no network, no original library). Tests land in a new bundle round-trip test module. | → M4, cap 9/11 |
| H15 | **M4 docs + self-describing proof.** Document the bundle in `docs/cli.md`/`README.md`/`docs/architecture.md`; confirm ADR 0103 consequences; capture concrete export→import command output. **M4 complete.** | → M4, cap 9 |
| H16 | **M5 dogfood flow — draft.** Write the one agent-runnable end-to-end flow (custody-vision dogfood): *hold a topic → prove custody (`doctor` score) → detect loss (drift recheck) → take it with me (`bundle export` → reimport)*. Script it against fixtures, offline. | → M5, cap 11 |
| H17 | **M5 dogfood flow — run + score.** Run the flow offline against fixtures end to end; capture a before/after custody score; reference it from `docs/custody-vision.md`'s success section. **M5 complete → MVP M1–M5 done.** | → M5, cap 11 |
| H18 | **Buffer refresh checkpoint** (maintenance rule). With the MVP complete, re-derive the post-MVP week plan (cap 8 re-derivable enrichment, scheduled custody maintenance) into concrete slices. | maintenance |

If the queue empties before the day does, deepen tests/fixtures on the slice
just shipped or pick the next-highest PRD capability — never manufacture
cosmetic churn (CLAUDE.md, *Avoid trivial progress*).

---

## 3-day plan (tentative) — through 2026-06-19

- **Day 1 (2026-06-16):** M1 (refresh-safe generated artifacts, ADR 0102)
  **complete** — shipped for compiled `library/` pages (H1+H2) and generated
  `agents/` instruction files (H3), with the architecture/library-format docs
  updated (H4). M2 (completeness invariant) **started**: the contract is written
  and its G1 half (honest absence/failure) is locked by `tests/test_completeness.py`
  (H5); G2 (scope echo + truncation) is enforced on `search` + `list` via the
  opt-in `--stats` envelope (`src/scrolls/scope.py`, H6), extended to
  `related` + `works` + `context` (H7 — `related`/`works` carry the scope
  echo, `context` a `Coverage:` line over `count_matches`), and finished on
  `doctor` (H8 — the drift block's `basis`/`as_of`/`unverified` make it
  verified-now-vs-as-of-last-check honest). **M2 complete: G2 enforced across
  every read surface, ahead of the Day-2 target.** **M3 (progressive context
  budgets) also shipped Day 1** (H9+H10): `scrolls context --budget
  {index,connected,full}` bounds bundle depth through nested tiers, identity/
  index first → deep bodies on demand, with a `_Budget:_` depth-honesty note
  and same-work collapse holding at every tier. Full suite green (2375).
- **Day 2 (2026-06-17):** M2 **and M3 done early** (H5–H10 all shipped Day 1).
  Next: M4 (custody bundle) — design with **ADR 0103** (the on-disk briefing
  format is consequential and shareable, H12), then implement export (H13) and
  import + round-trip fixture (H14).
- **Day 3 (2026-06-18 → 2026-06-19):** M4 finished (docs + self-describing
  proof, H15); M5 dogfood flow drafted (H16) and run offline against fixtures
  with a before/after custody score (H17) — **MVP M1–M5 complete.**

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
