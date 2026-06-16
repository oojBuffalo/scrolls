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

## 24h buffer (concrete) — 2026-06-16 → 2026-06-18

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
| H12–H15 | **✓ shipped as one slice (ADR 0103). M4 complete.** `scrolls export bundle <query>` / `import bundle <path>`: one self-contained Markdown file that is both a readable topic *briefing* (per scroll: id, source, custody fidelity tier, capture timestamp, link, content-hash, capped excerpt) and a lossless re-import unit — the same `item_to_dict` JSONL `export items` writes, inside a ` ```jsonl ` fence wrapped in the ADR 0102 `@generated` sentinel (so the briefing body stays hand-annotatable). Scoped by the query + `context`/`search` facets and *complete about that scope* (every match, `count_matches` is the limit — no top-N), so it is the shareable, take-it-with-you complement to `export items`. New `src/scrolls/bundle.py` is an *envelope* reusing `search_items`/`count_matches`/`get_fidelity`/`dump_items_export`/`item_from_dict`/`generated.fence` — no new storage. `import bundle` reuses the `import items` path (`INSERT OR IGNORE`, custody-safe), so losslessness is the ADR 0082/0099 property already tested; the export→import→fresh-library round-trip is verified end to end. Tests: `tests/test_bundle.py` (11). Docs: `docs/cli.md` (two headings), README, `docs/architecture.md`, ADR 0103 + index. Done in one slice rather than the H12–H15 split because the round-trip core already existed — the bundle is an envelope, and the ADR lands with working code (repo convention). | → M4, cap 9 |
| H16–H17 | **✓ shipped as one slice. M5 complete → MVP M1–M5 done.** The one agent-runnable end-to-end dogfood flow — *hold a topic → prove custody (`doctor` score) → detect loss (`verify` drift recheck) → take it with me (`export bundle` → `import bundle`)* — runs offline against fixtures in `tests/test_dogfood.py` (4 tests: each leg + the full ordered flow). Done as one slice (the H12–H15 precedent) because every underlying surface already shipped, so M5 is a *proof* tying M1–M4 together, not new feature code. The flow's two live edges (capture, recheck) are stood in for offline: **hold** seeds rendered full-fidelity items via the production `write_scroll` path; **detect** injects a scripted re-capture at the one `cli.live_recapture` seam (as `test_verify_cli.py` does). Captured before/after narrated in new `docs/dogfood.md`; referenced from `docs/custody-vision.md` §8. The sharp result the proof makes visible: detecting source drift moves the *drift posture* (`unverified` → `drifted`, recorded) **without** lowering the integrity `score` (held at 100) — because raw is sacred and drift is a recorded event, never an overwrite (custody §2.4). | → M5, cap 11 |
| H18 | **✓ executed (with H16–H17).** Buffer refresh checkpoint (maintenance rule): MVP M1–M5 marked complete; 3-day/week plans re-derived below; post-MVP cap-8 enrichment + scheduled-custody-maintenance week broken into concrete slices H19–H24. | maintenance |
| H19 | **✓ shipped. Enrichment provenance audit (cap 8 — baseline).** Audited what the three engines already record: rules stamps `classified_by="rules-v1"`, the LLM classifier adds `classified_model`, kb_llm summaries store a `members_hash` + `engine` and skip unchanged concepts. The gap was not *recording* but a *tested cross-engine contract*: new `tests/test_enrichment_provenance.py` (9 tests) pins method-is-recorded, deterministic re-derivation (re-classify is a no-op in result; the marker is idempotent, not accreting), capture-chain preservation, and anti-fabrication — the cap-8 baseline, modeled on `test_completeness.py`. Baseline + the one known gap (rules records version, not precedence tier; deferred to H20) documented in `docs/architecture.md`. Network-free. | → cap 8 |
| H20 | **Re-derivable classification records inputs + method.** Ensure `scrolls classify` (rules engine) records the engine + ruleset fingerprint in provenance so a re-classify is reproducible and auditable, and surface it on `show` (parity with `list`). Tests pin determinism (same inputs → same category + recorded method) and the surface echo. Builds on H19's baseline. | → cap 8 |
| H21 | **Confidence / recency marker on enriched fields (obsidian "confidence levels").** Derive a confidence/recency marker for classification + summary (rule-matched vs llm-inferred vs unset; freshness vs capture), surfaced identically across browse surfaces (search ≡ list ≡ MCP ≡ facets) and scope-honest. Tests pin the derivation + surface parity. | → cap 8 |
| H22 | **Scheduled custody maintenance flow — draft (obsidian "scheduled agents", custody-shaped).** Write the one agent-runnable maintenance pass — *audit → bounded drift recheck → regenerate views (`kb`) → report a custody delta* — as the dogfood flow's recurring sibling. Script it offline against fixtures (same `live_recapture` seam), the way `tests/test_dogfood.py` does. | → cap 8, maintenance framing |
| H23 | **Custody-delta maintenance report — run + artifact.** Emit a custody delta (score / tier / drift change since the last run) as a durable artifact the scheduled worker writes; run the H22 flow offline end to end and capture a before/after delta. Tests pin the delta computation. | → cap 8, maintenance framing |
| H24 | **Buffer refresh checkpoint** (maintenance rule). Re-derive the next post-MVP horizon; keep ≥6 un-started slots. Consider the deferred bi-temporal drift framing *only if* an agent workflow has shown the event record insufficient (else keep deferred per MVP out-of-scope). | maintenance |

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
  **M4 (shareable custody bundle) also shipped Day 1** (H12–H15, ADR 0103):
  `scrolls export bundle` / `import bundle` — a self-contained Markdown briefing
  with an embedded lossless custody block, verified round-trip across a fresh
  library. Done as one slice because the round-trip core (ADR 0082) already
  existed; the bundle is an envelope.
- **Day 2 (2026-06-17):** M2, M3, M4, **and M5 all done early** — the whole MVP
  shipped ahead of schedule. M5 (H16–H17) landed as one slice: the dogfood proof
  *hold → prove → detect → take it with me* runs offline against fixtures
  (`tests/test_dogfood.py`), is narrated in `docs/dogfood.md`, and is referenced
  from the vision's §8 success section. **MVP M1–M5 complete.** Next: begin the
  post-MVP week (cap 8 re-derivable enrichment — H19–H21; scheduled custody
  maintenance — H22–H23).
- **Day 3 (2026-06-18 → 2026-06-19):** Post-MVP. Land the cap-8 enrichment
  provenance baseline (H19) and re-derivable classification (H20), then the
  confidence/recency marker (H21). Begin framing the hourly worker as scheduled
  custody maintenance (H22 draft).

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
| 24h H12+ | cap 9 (custody bundle), cap 11 (dogfood) | M4, M5 |
| 24h H19–H21 / Week | cap 8 (re-derivable enrichment, confidence markers) | post-MVP |
| 24h H22–H23 / Week | scheduled custody maintenance (cap 8 + maintenance framing) | post-MVP |

The two obsidian-second-brain adoptions (M1 refresh-safe regeneration, M2
completeness invariant) are intentionally first in the queue: they are the
decision-grade, custody-deepening slices, and everything later reads cleaner
once regeneration is non-destructive and results are scope-honest.
