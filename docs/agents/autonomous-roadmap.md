# Autonomous roadmap & automation buffer

*Amended: 2026-07-27 — restructured for readability; shipped narration folded
out of the queue into the one-line ledger.*

How the hourly autonomous worker (`work/scrolls-dev`) spends its runs. This is
the **scheduling layer** under `docs/product/prd.md` (direction) and
`docs/product/mvp.md` (scope). The cron worker and launcher live outside the
repo (`/Users/claw/.hermes/scripts/scrolls_hourly_progress_worker.sh` and
`…_launcher.sh`); this doc is the queue they should read.

**How to read the hour slots.**

- **A lock, not a clock:** the launcher fires hourly but holds a lock, so a run
  that overruns an hour causes later ticks to **skip, not overlap**.
- **A queue, not a timetable:** the "hour-by-hour" buffer below is an *ordered
  queue of intended coherent slices*, not a promise that slot N starts exactly
  at hour N.
- **One coherent slice per run:** a run picks the next unstarted slice whose
  preconditions are met, finishes it to a real stopping point (committed,
  tested, clean), and stops — even if that consumes several nominal slots.

**Authority.**

- Slices are justified against `docs/vision.md` and the MVP.
- New adapters are out unless they introduce a new custody shape (vision §2.7).
- Anything not on the queue still loses to "finish the half-done slice from the
  previous run first."

---

## Live work queue (un-started)

*Steer note (2026-07-27): per `docs/agents/progress/260722/plans.md` this
un-started guard-cell queue is superseded pending the next maintenance pass —
the latest check-in's plans file is the operative steer.*

Ordered. Take the next slice whose preconditions are met (all listed
preconditions are shipped), finish it to a committed/tested/clean stopping
point, and stop. `→ capN` marks the PRD capability.

**The ordered queue is currently empty.** The forward-hardening guard-cell
sequence closed with H425. Per the assessment gate, pause before appending more
same-shaped guard cells; choose the next slice from current product/runtime
evidence rather than automatically extending the contract-consolidation
treadmill.

**De-prioritized backlog** — the budget/tier convergence cells **H244–H249**
remain valid regression guards but are explicitly de-prioritized (the tail of a
combinatorial matrix, each correct-by-construction); reach for them only when
no capability or forward-hardening slice is ready, and prefer closing one over
appending more of the same shape.

---

## Shipped ledger (compact index)

- One line per shipped slice; the full description + diff live in git
  (`git log --oneline | grep '(H<NN>)'`).
- This index exists only to keep `H<NN>` cross-references resolvable in-file —
  it is **not** a changelog (maintenance-rule §4).
- Re-compacted 2026-06-25 (the per-slice prose that had re-accreted here and in
  the then-current status snapshot — now
  `docs/agents/progress/260625/report.md` — was folded back to one line each),
  and again 2026-07-27 (the H363–H425 rows and the queue's shipped narration
  compressed back to one line each).

| Slot | Shipped | Maps to |
| --- | --- | --- |
| H1 | Sentinel boundary defined and implemented for compiled `library/` pages: pure helper… | M1, cap 6 |
| H2 | KB compiler writes every generated region inside the fence; a re-compile replaces only the fenced con… | M1, cap 6 |
| H3 | M1 extended to generated `agents/` files: `install_agent_docs` now writes through… | M1, cap 6 |
| H4 | `docs/architecture.md` Agent-install entry now describes the refresh-safe boundary… | M1, cap 6 |
| H5 | M2 contract written into `docs/cli.md` as a new top-level "The completeness contract" section, split… | M2, cap 7 |
| H6 | M2 G2 enforced on `search` + `list` via an opt-in `--stats` envelope | M2, cap 7 |
| H7 | M2 enforce on `context` + `related` + `works` | M2, cap 7 |
| H8 | M2 enforce on `doctor` — M2 complete | M2, cap 1/7 |
| H9 | M3 design folded into the implementation: the budget tiers are specified in `docs/cli.md` (the… | M3, cap 10 |
| H10 | M3 complete — `context --budget {index,connected,full}` bounds bundle depth through nested tiers | M3, cap 10 |
| H11 | Buffer checkpoint — M1/M2/M3 shipped ahead of schedule; M4→H12–H15, M5→H16–H17 | maint |
| H12–H15 | M4: `export bundle`/`import bundle` — self-contained Markdown briefing + lossless re-import (ADR 0103) | M4, cap 9 |
| H16–H17 | M5: offline dogfood proof *hold → prove → detect → take it with me* (`docs/dogfood.md`) | M5, cap 11 |
| H18 | Buffer checkpoint | maint |
| H19 | Enrichment provenance audit | cap 8 |
| H20 | Re-derivable classification records inputs + method | cap 8 |
| H21 | Confidence / recency marker on the classification view (obsidian "confidence levels") | cap 8 |
| H22–H23 | Scheduled-maintenance flow + custody-delta artifact (landed in `scrolls maintain`, H34) | cap 1, maintenance framing |
| H25 | Stale-ruleset signal in `doctor` (makes H20's fingerprint actionable) | cap 8, cap 1 |
| H26 | Classification view on `search` hits (search ≡ list ≡ show ≡ MCP parity) | cap 7, cap 8 |
| H27 | `scrolls classify --stale` — act on the H25 signal (regenerate on request) | cap 8, maintenance framing |
| H28 | `scrolls facets method` — the facets leg of the classification-method parity | cap 8, cap 7 |
| H29 | LLM concept-summary provenance view + doctor stale-summary signal (the summary-axis counterpart of H2… | cap 8, cap 1 |
| H31 | `scrolls kb --stale` — refresh summaries whose members changed (the summary-axis counterpart of H27) | cap 8, cap 1 |
| H33 | Summary axis pinned into the cap-8 cross-engine invariant | cap 8 |
| H34 | `scrolls maintain` — the scheduled custody-maintenance pass as a durable command (obsidian "scheduled… | cap 1, maintenance framing |
| H35 | Enrichment provenance travels in the shareable bundle's *briefing* | cap 9, cap 8 |
| H36 | `scrolls maintain` run log — the custody *trend*, not just the last delta | cap 1, maintenance framing |
| H37 | Anti-fabrication / completeness invariant covers `maintain` | cap 7 |
| H38 | Custody headline on `scrolls status` | cap 1, cap 2 |
| H39 | `export bundle --format html` — a browser-readable briefing | cap 9 |
| H40 | `scrolls maintain` suggests the explicit repair, never runs it | cap 1, maintenance framing |
| H42 | Drift posture per scroll in the bundle briefing | cap 1, cap 9 |
| H43 | Pinned `export bundle` into the M2 completeness invariant | cap 7 |
| H44 | Per-excerpt provenance tags on `scrolls context` excerpts at `full` budget | cap 8, cap 10 |
| H45 | Scope custody headline at the top of the bundle briefing | cap 1, cap 9 |
| H46 | `scrolls maintain --history --trend` derived trend summary | cap 1, maintenance framing |
| H47 | Scope custody headline on the `scrolls context` bundle | cap 1, cap 10 |
| H48 | `scrolls facets drift` — the drift-posture browse aggregate | cap 7, cap 1 |
| H50 | Custody-convergence cross-surface invariant | cap 1, cap 7 |
| H51 | `scrolls verify --unverified` — recheck only the never-checked held items | cap 1, maintenance framing |
| H52 | Custody headline on the `scrolls graph` stats block | cap 1, cap 2 |
| H53 | Buffer checkpoint | maint |
| H54 | `scrolls list --drift <posture>` — browse by custody drift posture | cap 7, cap 1 |
| H55 | `scrolls maintain` rechecks the unverified set first | cap 1, maintenance framing |
| H56 | Drift posture travels with the node shape — `related` hits + `graph` nodes | cap 7, cap 1 |
| H58 | Drift posture on the primary browse rows — `list` rows + `search` hits | cap 7, cap 1 |
| H59 | Per-item drift-posture cross-surface invariant | cap 7, cap 1 |
| H60 | Buffer checkpoint | maint |
| H61 | Per-item custody axes on the inspect surface — `scrolls show` + MCP `get_scroll` | cap 1, cap 2 |
| H62 | Per-excerpt drift posture on `context` excerpts at `full` budget | cap 1, cap 10 |
| H63 | Buffer checkpoint | maint |
| H64 | Drift posture on the `works` representation shape — `scrolls works` + MCP `get_works` | cap 1, cap 7 |
| H66 | `scrolls history <id>` — the per-item custody ledger timeline | cap 1, cap 7 |
| H67 | The verify-ledger custody events travel in the shareable bundle — portable custody | cap 9, cap 1 |
| H68 | Buffer checkpoint | maint |
| H69 | `scrolls history <id> --limit N` — bound a long per-item ledger to the most recent N checks | cap 1, cap 7 |
| H70 | Fold `scrolls history` into the per-item custody-convergence invariant — the timeline head ≡ the post… | cap 1, cap 7 |
| H71 | `scrolls history <id> --since <ISO>` — the per-item ledger window by time | cap 1, cap 7 |
| H72 | Whole-library portable custody — `scrolls export events` / `import events` | cap 9 |
| H73 | Portable-custody round-trip invariant — the posture survives export→import | cap 7, cap 9 |
| H74 | Buffer checkpoint | maint |
| H75 | Incremental custody backup — `scrolls export events --since <ISO>` | cap 9 |
| H77 | `scrolls history <id> --status <verdict>` — the verdict-axis ledger filter | cap 1, cap 7 |
| H78 | Incremental-backup posture round-trip invariant — the windowed union preserves custody | cap 7, cap 9 |
| H79 | `scrolls verify --stale-before <ISO>` — staleness-bounded recheck | cap 1, maintenance framing |
| H80 | `scrolls verify --drift <posture>` — recheck the items at a given posture | cap 1, maintenance framing |
| H81 | Verify-selection family convergence invariant — the batch selections relate as documented | cap 1, cap 7 |
| H82 | Buffer checkpoint | maint |
| H83 | `scrolls maintain` bounds its recheck to the stale set | cap 1, maintenance framing |
| H84 | Per-item `last_checked` timestamp on the browse rows | cap 1, cap 2 |
| H85 | `scrolls list --stale-before <ISO>` — browse the stale set | cap 7, cap 1 |
| H86 | Per-item `last_checked` rides the node-shape surfaces — `related` hits + `graph` nodes | cap 7, cap 1 |
| H87 | Per-item `last_checked` on the `works` representation shape — `scrolls works` + MCP `get_works` | cap 7, cap 1 |
| H88 | Consolidated per-item `last_checked` cross-surface invariant — the time-axis analogue of H59 | cap 7, cap 1 |
| H89 | Per-item custody markers on the compiled `library/` KB list pages (cap 1 + cap 2) — H65 brought current | cap 1, cap 2 |
| H90 | Per-excerpt `last_checked` on `scrolls context` excerpts at `full` budget (cap 1 + cap 10) — the time… | cap 1, cap 10 |
| H91 | Fold the compiled `library/` per-item marker into the per-item cross-surface invariant | cap 1, cap 7 |
| H92 | Buffer checkpoint | maint |
| H93 | Per-item `last_checked` on the compiled `library/` page marker (cap 1 + cap 2) — the time-axis comple… | cap 1, cap 2 |
| H94 | Per-excerpt `context` tag ≡ inspect-surface parity invariant | cap 7, cap 10 |
| H95 | Scope custody headline on the compiled `library/` group list pages | cap 1, cap 2 |
| H96 | Library-wide custody headline on the compiled `library/index.md` landing page | cap 1, cap 2 |
| H97 | Fold the compiled `library/` scope custody headlines into the custody-convergence invariant | cap 1, cap 7 |
| H98 | Custody counts in the `search`/`list --stats` scope envelope | cap 7, cap 1 |
| H99 | `scrolls related --stats` carries the custody member too — the `--stats`-envelope custody family is n… | cap 7, cap 1 |
| H100 | Custody tally on the `scrolls works` stats block (the works-surface entry in the `stats.custody` fami… | cap 7, cap 1 |
| H101 | Fold the browse-surface `stats.custody` family into the custody-convergence invariant | cap 7, cap 1 |
| H102 | Buffer checkpoint | maint |
| H103 | Custody headline in the `scrolls maintain` report | cap 1, maintenance framing |
| H104 | Per-source custody breakdown in `scrolls doctor` | cap 1 |
| H106 | `maintain`'s `doctor --fix` suggestion converges with what `doctor --fix` actually repairs | cap 1, cap 7 |
| H108 | Buffer checkpoint | maint |
| H109 | `scrolls maintain` reports recheck *coverage* | cap 1, maintenance framing |
| H110 | Buffer checkpoint | maint |
| H111 | maintain's default stale recheck ≡ `verify --stale-before <last-run>` — a convergence invariant | cap 1, cap 7 |
| H112 | Buffer checkpoint | maint |
| H113 | Recheck coverage on the `doctor` custody block | cap 1 |
| H114 | Buffer checkpoint | maint |
| H115 | `scrolls maintain` records recheck coverage in the snapshot/trend | cap 1, maintenance framing |
| H116 | Buffer checkpoint | maint |
| H117 | `scrolls status` carries the rendered one-line `headline` string (cap 1 + cap 2) — the status-surface… | cap 1, cap 2 |
| H118 | Buffer checkpoint | maint |
| H119 | `scrolls maintain` names the single weakest source in its report (`attention`) | cap 1, maintenance framing |
| H120 | Buffer checkpoint | maint |
| H121 | Per-source recheck coverage in the `doctor` custody breakdown | cap 1 |
| H122 | Buffer checkpoint | maint |
| H123 | Per-source custody breakdown in the `scrolls maintain` report (`by_source`) | cap 1, maintenance framing |
| H124 | Buffer checkpoint | maint |
| H125 | `scrolls verify --source <S>` — re-verify one source's held items (the act-side of the per-source cus… | cap 1, maintenance framing |
| H126 | Buffer checkpoint | maint |
| H127 | Maintain `by_source` ≡ doctor `by_source` — a cross-surface convergence invariant | cap 1, cap 7 |
| H128 | Buffer checkpoint | maint |
| H129 | `attention` ≡ doctor's max-loss source — the single-flag convergence invariant | cap 1, cap 7 |
| H130 | Buffer checkpoint | maint |
| H131 | `maintain --trend` reports the enrichment/summary staleness trajectory | cap 1, cap 8 |
| H132 | Buffer checkpoint | maint |
| H133 | `scrolls status` carries the per-source custody breakdown (`by_source`) — the status-surface counterp… | cap 1, cap 2 |
| H134 | Buffer checkpoint | maint |
| H135 | Per-source enrichment staleness in the `doctor` custody breakdown | cap 8, cap 1 |
| H136 | Buffer checkpoint | maint |
| H137 | `maintain`'s `attention` block names the `verify --source <S>` recheck command | cap 1, maintenance framing |
| H138 | Buffer checkpoint | maint |
| H139 | `scrolls status` carries the single weakest-source `attention` flag — the status-surface counterpart… | cap 1, cap 2 |
| H141 | Per-source custody breakdown in the `export bundle` briefing headline | cap 9, cap 1 |
| H142 | Buffer checkpoint | maint |
| H143 | Trend-axis ≡ telescoped per-run delta convergence invariant | cap 1, cap 7 |
| H144 | Buffer checkpoint | maint |
| H145 | Per-source custody breakdown on the compiled `library/index.md` landing page | cap 1, cap 2 |
| H146 | Buffer checkpoint | maint |
| H147 | Per-source enrichment staleness in the `scrolls maintain` report | cap 8, cap 1 |
| H148 | Buffer checkpoint | maint |
| H149 | Per-source custody breakdown on the `scrolls context` model-facing bundle | cap 1, cap 10 |
| H150 | Per-source custody breakdown on the `scrolls graph` stats block (`stats.custody.by_source`) | cap 1, cap 2 |
| H151 | Per-source custody breakdown rendered-line cross-surface invariant | cap 1, cap 7 |
| H152 | Per-source custody breakdown on the compiled multi-source group list pages — `categories/`… | cap 1, cap 2 |
| H153 | Per-source `coverage` rides the weakest-source `attention` flag | cap 1, maintenance framing |
| H154 | `scrolls classify --stale --source <S>` — the enrichment-axis per-source refresh | cap 8, maintenance framing |
| H155 | Per-source `by_source` member on the browse-stats `stats.custody` envelopes | cap 7, cap 1 |
| H157 | JSON per-source `by_source` cross-surface convergence invariant | cap 1, cap 7 |
| H158 | Per-source recheck `coverage` in the readable `_By source:_` breakdown | cap 1, cap 2 |
| H159 | Readable weakest-source `_Attention:_` line on the bundle/context briefing | cap 1, cap 9, cap 10 |
| H160 | Attention-flag full-shape cross-surface convergence invariant | cap 1, cap 7 |
| H161 | MCP `get_library_health` — the custody audit over MCP | cap 1, cap 2 |
| H162 | `scrolls doctor --source <S>` — scope the whole custody audit to one source | cap 1, maintenance framing |
| H163 | MCP browse twins are array-only — the per-source split rides the object/audit twins | cap 2, cap 7 |
| H164 | Weakest-source `attention` flag on the `graph` stats block (`stats.custody.attention`) | cap 1, cap 2 |
| H165 | `scrolls maintain --source <S>` — scope the scheduled custody pass to one source | cap 1, maintenance framing |
| H166 | `scrolls status --source <S>` — scope the status custody read to one source | cap 1, cap 2 |
| H167 | MCP `get_library_health(source=...)` — the scoped custody read over MCP | cap 1, cap 2 |
| H168 | Buffer checkpoint | maint |
| H169 | Per-source-scope cross-surface convergence invariant — the scoped reads agree | cap 1, cap 7 |
| H170 | Buffer checkpoint | maint |
| H171 | Per-source stale-summary debt in `doctor`'s `custody.summaries.by_source` | cap 8, cap 1 |
| H172 | `scrolls kb --stale --source <S>` — the summary-axis per-source refresh | cap 8, maintenance framing |
| H173 | Buffer checkpoint | maint |
| H174 | Weakest-source `attention` flag on the lean browse-stats `stats.custody` family — `search`/`list`… | cap 2, cap 7 |
| H175 | `maintain` report carries `summary_by_source` — the scheduled-surface read of H171's per-source stale… | cap 8, cap 1 |
| H176 | Summary-axis per-source refresh convergence folded into `tests/test_custody_convergence.py` | cap 8, cap 1 |
| H177 | `status` JSON carries `enrichment_by_source` + `summary_by_source` — the read-surface per-source stal… | cap 2, cap 8 |
| H178 | Readable per-source `_Refresh:_` line on the `context`/`export bundle` briefing — the enrichment/summ… | cap 5, cap 8 |
| H179 | Status per-source refresh-debt maps (`enrichment_by_source`/`summary_by_source`) ≡ `maintain` ≡ `doctor`, whole-library + scoped, folded… | cap 2, cap 8 |
| H180 | MCP `get_library_health` keeps the fuller nested refresh-debt block — flat≡nested tie pinned | cap 2, cap 8 |
| H181 | `maintain`'s `suggested` block emits *source-scoped* refresh commands when debt is confined | cap 1, cap 8 |
| H182 | `maintain --source <S>` suggests the *scoped* refresh, not the whole-library sweep | cap 1, cap 8 |
| H183 | `maintain`'s scoped `suggested` refresh commands name exactly the debt-map sources — convergence folded into the suite | cap 1, cap 8 |
| H184 | Readable `_Attention:_` + `_Refresh:_` action-pointer lines on the compiled `library/` index/group pages | cap 1, cap 5, cap 8 |
| H185 | `scrolls list --stale-classification` — browse the stale-enrichment set | cap 7, cap 8 |
| H186 | MCP read-surface shape contract pinned once — the capstone of H163/H180 | cap 2, cap 7 |
| H188 | Action-pointer lines byte-identical across *all* readable surfaces | cap 5, cap 8 |
| H189 | `scrolls list --stale-summary` — browse the items in a stale-summary cluster | cap 7, cap 8 |
| H190 | Compiled-page action-line honest-absence folded into the M2 completeness invariant | cap 7, M2 |
| H191 | Buffer checkpoint | maint |
| H192 | Bundle-HTML action-line *content* parity ≡ the Markdown form ≡ the canonical primitive (the HTML counterpart of H188's byte-identical… | cap 5, cap 8 |
| H193 | Single-source compiled `sources/<S>.md` `_Refresh:_` honest presence ≡ `doctor --source` debt,… | cap 7, cap 8 |
| H194 | The Markdown-string read twins are the *fourth* shape class in the H186 contract | cap 2, cap 7 |
| H195 | MCP object-twin `stats.custody.by_source` *content* ≡ `doctor` — graph twin whole-library (≡ doctor incl | cap 1, cap 2 |
| H196 | `run_maintenance` MCP tool — the scheduled custody pass over MCP | cap 1, cap 11 |
| H197 | Buffer checkpoint | maint |
| H198 | `get_maintenance_history` MCP tool — the custody *trend* over MCP, the read sibling of H196 | cap 1, cap 11 |
| H200 | Buffer checkpoint | maint |
| H201 | MCP-driven dogfood custody loop — the agent-facing counterpart of `docs/dogfood.md` | cap 11 |
| H202 | Buffer checkpoint | maint |
| H203 | Scoped `run_maintenance(source=)` over MCP — the source-scoped custody pass an agent runs on the weak… | cap 1, cap 11 |
| H204 | Scoped MCP maintenance pass folded into the agent-driven dogfood flow | cap 11 |
| H205 | Buffer checkpoint | maint |
| H206 | CLI attention→scoped-`maintain` *drift*-act triage as one shell sequence in `tests/test_dogfood.py` — the shell twin of H204's MCP flow:… | cap 11 |
| H208 | MCP `get_library_health` nested refresh-debt read (`enrichment.by_source`/`summaries.by_source`) folded into the H179 three-way tie ≡… | cap 2, cap 8 |
| H209 | MCP `run_maintenance` scoped `suggested` ↔ debt-map convergence folded into the suite — the agent-facing sibling of H183: the… | cap 1, cap 11 |
| H210 | CLI refresh-debt *act* dogfood in `tests/test_dogfood.py` — the refresh-axis twin of H206's drift-act triage: an agent reads the… | cap 8, cap 11 |
| H211 | MCP object-twin `stats.custody.attention` *scope* tie — graph flag whole-library (≡ `weakest_source(doctor.by_source)` ≡ `status` ≡… | cap 1, cap 2 |
| H212 | `_Fidelity: full <a>, partial <b>, reference <c> (of N)._` holdings line at the `index` budget on `scrolls context` — the leanest tier… | cap 2, cap 7, cap 10 |
| H213 | Cross-tier fidelity convergence test in `tests/test_custody_convergence.py` — the `index` `_Fidelity:_` counts ≡ the `connected` *and*… | cap 7 |
| H214 | MCP twin of H212 in `tests/test_mcp.py` — `get_context_bundle(budget="index")` carries the `_Fidelity:_` holdings line (non-vacuous full… | cap 2, cap 10 |
| H215 | The `index` fidelity line folded into the M2 completeness/anti-fabrication invariant (`tests/test_completeness.py`) — the leanest… | cap 7, M2 |
| H216 | Mixed-fidelity bundle round-trip invariant in `tests/test_bundle.py` (`test_mixed_fidelity_bundle_parse_preserves_each_tier` +… | cap 7, cap 9 |
| H217 | Bundle import is honest about *orphan* custody events (`custody.partition_resolvable_events`, `src/scrolls/cli.py` `_cmd_import_bundle`,… | cap 9, cap 7 |
| H219 | MCP twin of H215 in `tests/test_completeness.py` (`test_mcp_index_budget_names_fidelity_holdings_but_no_drift_verdict`), beside the CLI… | cap 2, cap 7, M2 |
| H220 | `scrolls import bundle --dry-run` — the read-only preview of a bundle merge (`src/scrolls/cli.py` `_preview_import_bundle`,… | cap 9, cap 7 |
| H221 | The `index` `_Fidelity:_` line's `(of N)` scope is honest under truncation (`tests/test_context.py`) — the leanest tier's holdings count… | cap 7, cap 10 |
| H222 | MCP twin of H221 in `tests/test_mcp.py` (`test_get_context_bundle_index_fidelity_scope_is_honest_under_truncation`, beside the H214… | cap 2, cap 10 |
| H223 | The `index` `_Fidelity:_` holdings honor the active facet scope (`tests/test_context.py`,… | cap 7, cap 10 |
| H224 | The whole-library JSONL backup is *tier-lossless* too — the H216 round-trip guarantee on the other portable surface… | cap 9, cap 4 |
| H225 | `import bundle` names *which* items the orphan custody events dangle on — the diagnosable half of H217 (`src/scrolls/cli.py`… | cap 9, cap 7 |
| H226 | `import bundle --dry-run` names *which* scrolls are new vs | cap 9, cap 7 |
| H227 | MCP twin of H223 in `tests/test_mcp.py` (`test_get_context_bundle_index_fidelity_scope_honors_the_active_facet`, beside the H214/H222… | cap 2, cap 7, cap 10 |
| H228 | The `index` `_Fidelity:_` `(of N)` is honest under facet scope *and* truncation at once — the *composition* of H221 (truncation) and… | cap 7, cap 10 |
| H229 | The scoped `index` `_Fidelity:_` counts ≡ `doctor --source <S>`'s `custody.tiers` — the scoped sibling of H213's cross-tier convergence… | cap 1, cap 7, cap 10 |
| H230 | The import summary names *which* items orphaned in its structured JSON — the machine-readable half of H225 (`src/scrolls/cli.py`… | cap 9, cap 7 |
| H231 | The whole-library backup's byte-identical rebuild holds across *mixed* fidelity tiers too — the byte-depth sibling of H224's tier-count… | cap 4, cap 9 |
| H232 | MCP twin of H228 in `tests/test_mcp.py` (`test_get_context_bundle_index_fidelity_scope_is_honest_under_facet_and_truncation`, beside the… | cap 2, cap 7, cap 10 |
| H233 | The dry-run `new`/`held` review lists dedup honestly under within-bundle duplicate item ids — the *dedup* half of H226… | cap 9, cap 7 |
| H234 | The scoped `index` `_Fidelity:_` holdings diverge honestly from `doctor --source <S>`'s `custody.tiers` *under truncation* — the… | cap 1, cap 7, cap 10 |
| H235 | The scoped `index` `_Fidelity:_` counts ≡ `get_library_health(source=<S>)`'s `custody.tiers` over MCP — the MCP twin of H229… | cap 1, cap 2, cap 7 |
| H236 | The scoped `index` `_Fidelity:_` holdings diverge honestly from `get_library_health(source=<S>)`'s `tiers` *under truncation* over MCP —… | cap 1, cap 2, cap 7 |
| H237 | The dry-run preview's whole `events` block — `{imported, skipped, orphaned, orphaned_items}` — is byte-identical to the real import's… | cap 9, cap 7 |
| H238 | The scoped `export bundle` → `import bundle` round-trip rebuilds the `partial` scroll byte-identically — the *bundle*-surface corner of… | cap 9, cap 4 |
| H239 | The dry-run `new`/`held` lists *partition* the bundle's distinct item ids — the *completeness complement* of H233's dedup… | cap 9, cap 7 |
| H240 | The whole budget ladder stays mutually equal under truncation while *together* diverging from `doctor --source <S>` — the… | cap 1, cap 2, cap 10 |
| H241 | The scoped `index` `_Fidelity:_` counts ≡ the scoped `connected`/`full` `_Custody:_` headline's `fidelity` section, all read over MCP —… | cap 1, cap 2, cap 10 |
| H242 | The whole MCP budget ladder stays mutually equal under truncation while *together* diverging from `get_library_health(source=<S>)`'s… | cap 1, cap 2, cap 10 |
| H243 | The dry-run's *whole top-level summary* `{imported, skipped, items, events}` (sans the dry-run-only `{dry_run, new, held}`) is… | cap 9, cap 7 |
| H250 | `scrolls list --fidelity <tier>` + MCP `list_scrolls(fidelity=)` — browse holdings by custody-fidelity tier… | cap 2, cap 7 |
| H251 | `scrolls search --fidelity <tier>` + MCP `search_scrolls(fidelity=)` — the holdings-axis filter on the *ranked* surface, the search twin… | cap 1, cap 2, cap 7 |
| H252 | `scrolls verify --fidelity <tier>` — the holdings-axis *act* surface, the verify-axis twin of H250's `list --fidelity` / H251's… | cap 1, cap 2, cap 7 |
| H253 | `scrolls search --drift <posture>` + MCP `search_scrolls(drift=)` — the ledger-claim-axis filter on the *ranked* surface, the drift twin… | cap 1, cap 2, cap 7 |
| H254 | `scrolls related --fidelity <tier>` / `--drift <posture>` + MCP `get_related_scrolls(fidelity=, drift=)` — the custody-filter family on… | cap 1, cap 2, cap 7 |
| H255 | `scrolls maintain --fidelity <tier>` — the scheduled-maintenance *act* twin of `verify --fidelity`, closing the custody-filter family… | cap 1, cap 2, cap 7 |
| H257 | `scrolls context <query> --fidelity <tier>` / `--drift <posture>` + MCP `get_context_bundle(fidelity=, drift=)` — the custody-filter… | cap 1, cap 2, cap 7, cap 10 |
| H258 | `scrolls export bundle <query> --fidelity <tier>` / `--drift <posture>` — the custody-filter family on the *portable shareable bundle*,… | cap 9, cap 4, cap 1 |
| H259 | `scrolls export items --fidelity <tier>` / `--drift <posture>` — the custody-filter family on the *whole-library JSONL backup*, the… | cap 9, cap 4, cap 1 |
| H260 | `scrolls export events --fidelity <tier>` / `--drift <posture>` — the custody-filter family on the *whole-library custody-ledger… | cap 9, cap 4, cap 1 |
| H261 | `scrolls works` reports a per-work *aggregate custody posture* — the consolidation-level custody verdict, the new-custody-shape lead… | cap 1, cap 2, cap 5 |
| H262 | `scrolls works --fidelity <tier>` / `--drift <posture>` + the MCP `get_works(fidelity=, drift=)` twin — the custody-filter family on the… | cap 1, cap 2, cap 7 |
| H263 | The *at-risk-works* consolidation alarm on `doctor` + `maintain` + MCP `get_library_health` — closing the consolidation theme (H261–H263) | cap 1, cap 5, cap 8 |
| H264 | The readable work-level `_At-risk work:_` line on the `export bundle` + `scrolls context` briefings — the consolidation-level… | cap 1, cap 9, cap 10 |
| H265 | `scrolls works --at-risk` + the MCP `get_works(at_risk=True)` twin — browse only the works no representation safely holds, the… | cap 1, cap 7 |
| H266 | `scrolls works` stats carry a scope-level at-risk-works summary at `stats.custody.at_risk` (CLI + MCP `get_works`) — the works-surface… | cap 1, cap 2, cap 7 |
| H267 | The at-risk-works count rides the `maintain` custody snapshot, its cross-run `delta`, and `--history`/`--trend` (and `status`'s… | cap 1, maintenance framing |
| H268 | The at-risk-works count is readable on the `maintain` report (`_At-risk works: N (▲M since last run)._`) and the `--trend` summary… | cap 1, maintenance framing |
| H269 | The compiled landing `library/index.md` carries the at-risk-works alarm — the consolidation alarm on the *static compiled* surface, the… | cap 1, cap 2, cap 6 |
| H270 | The compiled `works.md` rollup carries a per-work `_Custody:_` marker beneath each `## <doi>` section's resolver line — the works-page… | cap 1, cap 2, cap 6 |
| H271 | The `_At-risk work:_` line rides the *HTML* `export bundle` form too — the HTML twin of H264's Markdown at-risk line, closing the… | cap 9, cap 1 |
| H272 | Conflict-on-import is surfaced on the lossless whole-library importer (`import items`) — never silently swallowed; opens the… | cap 7, cap 1, cap 9 |
| H273 | The conflict-on-import partition reaches the bundle importer — `import bundle` surfaces `unchanged`/`conflict` (the H272… | cap 9, cap 7, cap 1 |
| H274 | A surfaced import conflict becomes a recorded custody *event* — closing the conflict-on-import theme's *detection* leg (ADR 0104) | cap 1, cap 3, cap 9 |
| H275 | A `doctor` scope-level *conflict aggregate* (`custody.conflicts`) — the read-aggregate sibling of `custody.drift`, opening the… | cap 1, cap 3, cap 9 |
| H276 | A reviewed `reconcile --keep-held` resolution — the operator *act* on a recorded conflict, closing the conflict-on-import theme's… | cap 1, cap 3 |
| H277 | A readable `_Conflicts:_` briefing line — the readable completion of H275's JSON `custody.conflicts` aggregate (ADR 0104), closing the… | cap 1, cap 3, cap 9 |
| H278 | `--accept-incoming` — the content-bearing reconcile resolution that *adopts* the peer's capture (ADR 0106; the first import-path write… | cap 1, cap 3 |
| H279 | A `conflicts` scalar on `scrolls status`'s machine `custody` snapshot — the JSON-status counterpart of H277's readable `_Conflicts:_`… | cap 10, cap 1 |
| H280 | The prior-content archive travels in the portable round-trip — `export bundle --with-archive` + the `export archive`/`import archive`… | cap 9, cap 5 |
| H281 | An MCP archive *read* twin — `list_archived` / `get_archived`, so agents reach the prior-content recovery store over MCP (ADR 0106's… | cap 6, cap 1 |
| H282 | `scrolls archive prune (--before ISO \| --keep N) [--apply]` — a retention act bounding the append-only recovery store (ADR 0106's… | cap 1 |
| H283 | The conflict-over-time leg — the unresolved-conflict scalar is *differenced* (cross-run `delta` + `--history`/`--trend`… | cap 10, cap 1 |
| H284 | An end-to-end *adopt a peer's better capture* dogfood — the accept-incoming flow on both surfaces, offline + fixture-driven, narrated in… | cap 8, cap 3 |
| H285 | `scrolls archive show <id> --all` — emit an item's *full* archived history, not just the latest prior (ADR 0106's deferred "archive show… | cap 1, cap 5 |
| H286 | `scrolls archive restore <id> [--hash H \| --at ISO]` — restore a *specific* archived prior in place, not only the latest (ADR 0106's… | cap 1, cap 3 |
| H287 | A *restore-by-version* dogfood — roll back to a *specific earlier* version across multiple supersessions, the H284 analogue on the… | cap 3, cap 8 |
| H288 | `scrolls archive diff <id> [--hash H \| --at ISO]` — the decide-before-you-restore read, comparing the held copy against a selected… | cap 1, cap 6 |
| H289 | A *decide-before-you-restore* dogfood — read `archive diff`, then act, end to end, and the act lands exactly on the read's prediction… | cap 1, cap 6 |
| H300 | Scoped `export archive --id <ref>` round-trips the recovery read-family identically — the H294 twin on the per-item export path | cap 4, cap 8 |
| H301 | `export archive --source <S>` — the source-scoped recovery-store backup, the `export events --source` analogue on the archive axis | cap 4, cap 8 |
| H302 | `export archive --fidelity`/`--drift` — the custody-filter family completed on the recovery store, the *last un-filtered export surface* | cap 4, cap 8 |
| H303 | `export archive --since <ISO>` — the incremental recovery-store backup, the `export events --since` analogue on the archive axis | cap 4, cap 8 |
| H304 | The `--since` family shares one boundary-normalization contract — `history --since` ≡ `export events --since` ≡ `export archive --since`… | cap 4, cap 10 |
| H308 | The incremental backup is honestly append-only — an `archive prune` on machine A does *not* propagate through a later… | cap 4 |
| H309 | The archive-integrity alarm survives the *incremental*-backup round-trip — a corrupt prior (`prior_hash ≠ snapshot.content_hash`)… | cap 4 |
| H310 | The archive-integrity alarm is un-launderable by a *local repair pass* — `doctor --fix` over a corrupt prior… | cap 1, cap 4 |
| H311 | The archive-integrity alarm composes honestly with `archive prune` — pruning *other* priors leaves the corrupt prior's alarm firing… | cap 1, cap 4 |
| H312 | Explainable ranking — each search hit explains its own rank: `matched_fields` (the indexed fields the query terms landed in, BM25-weight… | cap 2, custody-vision §3.5 |
| H313 | The `--stats` envelope carries a `strength` tally over the matched scope — `{strong, moderate, weak}` counts summing to `stats.matched`,… | cap 2 |
| H314 | `search --strength {strong|moderate|weak}` + MCP `search_scrolls(strength=)` — the act-axis companion of the explanation: keep only the… | cap 2 |
| H315 | The agent context bundle surfaces the rank explanation — `scrolls context <Q>` / MCP `get_context_bundle` carry each match's… | cap 2, cap 10 |
| H316 | `scrolls context --strength {strong|moderate|weak}` + the MCP `get_context_bundle(strength=)` twin — the act-axis companion on the… | cap 2, cap 10 |
| H317 | The explainable-ranking surface reaches the shareable `export bundle` — a per-match `· rank <strength>` marker and the `_Strength:_`… | cap 2, cap 4 |
| H318 | `export bundle --strength {strong|moderate|weak}` — the rank-axis filter on the portable bundle, the H258/H314/H317 sibling (the act… | cap 2, cap 4 |
| H319 | The shareable `export bundle` carries a readable `_Archive:_` integrity line… | cap 1, cap 4 |
| H320 | The agent context bundle carries the same `_Archive:_` integrity line — `scrolls context <Q>` / MCP `get_context_bundle` surface the… | cap 1, cap 4 |
| H321 | The compiled landing `library/index.md` carries the `_Archive:_` integrity line — the whole-library archive-integrity alarm on the… | cap 1, cap 4 |
| H322 | Explainable relatedness — each `related` hit carries a `relation_strength` band (`strong`/`moderate`/`weak`), the relationship-surface… | cap 2, custody-vision §3.5 |
| H323 | `related --stats` carries a `strength` tally over the matched neighbourhood, the H313 analogue on the relation axis. | cap 2 |
| H324 | `related --strength {strong|moderate|weak}` + MCP `get_related_scrolls(strength=)` — the act-axis filter on the relation surface, the… | cap 2 |
| H325 | `doctor`'s `custody.content_duplicates` — a content-identity redundancy report flagging held items that share a non-null `content_hash`… | cap 1, custody-vision §3.5 |
| H326 | A `related` "identical content" edge — when two items share a `content_hash`, `related` scores it as the strongest possible bond (above… | cap 2 |
| H327 | The content-duplicate count gets a readable surface — a `_Duplicates:_` headline on `maintain` (+ the `status` JSON scalars), the… | cap 1 |
| H328 | Per-item content-identity — `scrolls show <id>` / MCP `get_scroll` carries `content_duplicate_ids` (the *other* held ids sharing this… | cap 1, cap 7 |
| H329 | Work-level content-identity — `scrolls works` (+ MCP `get_works`) flags a work whose representations include a byte-identical pair… | cap 1 |
| H330 | The content-duplicate `_Duplicates:_` line gains a cross-run trend clause — the H299-analogue on the content-identity axis: successive… | cap 1 |
| H331 | The content-duplicate count reaches the readable *briefings* — a `_Duplicates:_` line on the shareable `export bundle` (+ HTML twin) and… | cap 1, cap 4 |
| H332 | A cross-surface content-identity convergence invariant — one pinned test that the byte-identical-holding count reads *identically*… | cap 1 |
| H333 | Per-item content-identity reaches the *rendered* scroll — the compiled `library/` group list-page rows carry a `· also held as `<id>… | cap 1, cap 7 |
| H334 | The compiled landing `library/index.md` carries a whole-library `_Duplicates:_` line — the content-identity counterpart of the… | cap 1, cap 4 |
| H335 | MCP content-identity trend parity — `get_maintenance_history(trend=True)` carries `content_duplicates_change` + the trend… | cap 1 |
| H336 | The content-duplicate briefing line travels the bundle round-trip — `export bundle <Q>` → `import bundle` → the rebuilt library… | cap 1, cap 4, cap 9 |
| H337 | The no-merge custody-honesty guard — `doctor --fix` NEVER merges or touches a content-identity duplicate, the executable form of the… | cap 1, cap 9 |
| H338 | The content-identity *browse* filter — `list --content-duplicate` / `search --content-duplicate` (+ the MCP… | cap 1, cap 7 |
| H339 | The H333 rendered marker joins the cross-surface convergence guard — `tests/test_custody_convergence.py` adds the compiled `library/`… | cap 1 |
| H340 | The content-identity dogfood proof — `tests/test_dogfood.py` pins the *spot-the-redundancy → prune → it clears* flow end-to-end across… | cap 1, cap 9 |
| H341 | The content-identity browse filter reaches the *export* surfaces — `export bundle --content-duplicate`… | cap 1, cap 4, cap 7 |
| H342 | The content-identity *aggregate* — `scrolls facets content-duplicate` partitions the library into `{duplicate, unique}` with a held-item… | cap 1, cap 7 |
| H343 | Per-item content-identity reaches the `graph` surface — each `graph` node carries `content_duplicate_ids` (its byte-identical siblings)… | cap 1 |
| H344 | The content-identity browse filter reaches the *work-consolidation* surface — `scrolls works --content-duplicate` (+ MCP… | cap 1, cap 7 |
| H345 | The content-identity browse filter reaches the *context-assembly* surface — `scrolls context <Q> --content-duplicate` (+ the MCP… | cap 1, cap 7, cap 10 |
| H346 | A unified content-identity browse/aggregate convergence guard — one pinned test that the redundant-holding *count* reads identically… | cap 1, cap 7 |
| H347 | The content-identity browse filter reaches the *custody-record* + *recovery-store* export surfaces — `export events --content-duplicate`… | cap 1, cap 4, cap 7 |
| H348 | The `facets content-duplicate` aggregate completes the cross-surface convergence guard — the partition-completeness leg beside H346's… | cap 1, cap 7 |
| H349 | The whole-library `_Duplicates:_` content-identity line reaches the compiled *group/concept/tag/source* pages — each compiled member… | cap 1, cap 7 |
| H350 | The content-identity browse filter reaches the *relationship* surface — `scrolls related <id> --content-duplicate` (+ MCP… | cap 1, cap 7 |
| H351 | A compiled-surface content-identity dogfood loop — `tests/test_dogfood.py` pins *compile → the landing + group `_Duplicates:_` lines… | cap 1, cap 9 |
| H352 | `scrolls graph --content-duplicate` — the content-identity node-set filter on the relationship graph (+ MCP… | cap 1, cap 7 |
| H353 | The content-duplicate-on-import notice — `import items`/`import bundle` add a `content_duplicates` count to their JSON result when an… | cap 1, cap 7 |
| H354 | The content-identity *export round-trip family* guard — one pinned section that each content-scoped export surface round-trips into a… | cap 1, cap 4, cap 7 |
| H355 | The content-identity *MCP-surface dogfood loop* — `tests/test_dogfood_mcp.py` pins the agent triage loop over the MCP transport:… | cap 1, cap 7, cap 9 |
| H356 | The content-duplicate *suggested prune* guidance on `maintain` — turn the `custody.content_duplicates` finding into actionable guidance:… | cap 1, cap 7 |
| H357 | The content-duplicate prune *dogfood* loop over the suggested block — `tests/test_dogfood.py` pins suggested → act → clear: `maintain`… | cap 1, cap 9 |
| H358 | The content-duplicate-on-import ↔ doctor *convergence* guard — pins the H353 import-time `content_duplicates` count to `doctor`'s… | cap 1, cap 7 |
| H359 | The import→prune→re-import content-identity dogfood loop — `tests/test_dogfood.py` pins *import a JSONL source reporting… | cap 1, cap 9 |
| H360 | The content-duplicate *prune guidance travels the bundle round-trip* — one guard that the H356 `duplicate_prunes` block re-derives… | cap 9, cap 1 |
| H361 | The `run_maintenance` MCP `duplicate_prunes` byte-parity with CLI `maintain` — one convergence guard that the MCP transport's prune… | cap 7, cap 1 |
| H362 | The *relationship-graph* content-identity surface joins the convergence picture — `graph --content-duplicate` (+ MCP… | cap 1, cap 7 |
| H363 | In-place `kb` recompile-determinism guard (test-only) — a same-process two-pass whole-tree-hash no-op plus a cross-`PYTHONHASHSEED` subprocess pair; first forward-hardening cell | cap 1, cap 9 |
| H364 | MCP holdings-immutability contract guard (test-only) — `tests/test_mcp.py` pins the registered tool set as an allow-list of read + custody-safe-write tools, no capture-destroying verb | cap 7, cap 1 |
| H365 | `doctor --fix` repair-convergence guard (test-only) — `tests/test_doctor.py` pins a second `--fix` as a total no-op on both the report and the whole-tree hash | cap 1, cap 9 |
| H366 | `context --budget` tier-nesting contract guard (test-only) — `tests/test_context.py` pins the strictly-nested `index`/`connected`/`full` contract (leaner budgets cut depth, never the match set) on CLI + MCP | cap 1, cap 3 |
| H367 | `scrolls status` ↔ `doctor` custody-scalar convergence guard (test-only) — `tests/test_custody_convergence.py` pins the whole lean-`status` custody block field-for-field against the `doctor --json` audit | cap 1, cap 7 |
| H368 | Whole-library `export bundle` determinism + round-trip byte-identity guard (test-only) — `tests/test_bundle.py` pins two exports byte-identical and export→import→re-export reproducing the sender's bytes | cap 1, cap 4 |
| H369 | `doctor`'s whole-library `custody.posture` verdict (`{verdict: sound\|attention\|at_risk, reasons}`) — the seven custody blocks distilled by `_assess_custody_posture` into one fold (+ the `get_library_health` MCP twin) | cap 1, custody-vision §3.1 |
| H370 | The readable `_Posture:_` line on the `maintain` report (`posture_headline`) + the `status.custody.posture` scalar twin — the verdict made human and machine-readable, always-rendered | cap 1, cap 2 |
| H371 | The `_Posture:_` briefing line on `export bundle` + `scrolls context` — `doctor`'s whole-library `custody.posture` verdict travels with the shareable/agent briefings, always-rendered | cap 1, custody-vision §3.1 |
| H372 | The cross-run posture-movement clause on the `maintain`/trend `_Posture:_` line — `compute_delta` gains a categorical `posture` axis, `compute_trend` a `posture_change` + windowed headline; reported, never a trajectory trigger | cap 1, cap 7 |
| H373 | Cross-surface posture convergence guard (test-only) — `tests/test_custody_convergence.py` pins `status` ≡ `doctor` ≡ `get_library_health` ≡ `maintain` ≡ the `_Posture:_` briefing line, plus the movement axis, at CLI↔MCP parity; closes the custody-posture theme | cap 1, cap 7 |
| H374 | `import bundle` re-import idempotency guard (test-only) — `tests/test_bundle.py` pins re-importing a held bundle as a true no-op on item rows, disk bytes, and the conflict ledger | cap 1, cap 4 |
| H375 | `scrolls doctor` whole-report determinism guard (test-only) — `tests/test_doctor.py` pins two same-process `run_doctor` reads byte-identical and `doctor` stdout identical across `PYTHONHASHSEED` subprocesses | cap 1 |
| H376 | `scrolls context` bundle determinism guard (test-only) — `tests/test_context.py` pins the model-facing bundle byte-identical same-process and across hash-seed subprocesses at `--budget full` | cap 1, cap 3 |
| H377 | `scrolls maintain` trend-log determinism + no-movement settle guard (test-only) — `tests/test_maintain.py` pins a second `--no-recheck` pass all-zero on every delta axis and the report/trend byte-identical across seeds | cap 1 |
| H378 | `export bundle --format html` whole-text determinism guard (test-only) — `tests/test_bundle.py` pins two same-library HTML exports byte-identical (export-only surface, so no round-trip leg) | cap 9 |
| H379 | `export items` JSONL whole-file determinism + round-trip byte-identity guard (test-only) — `tests/test_roundtrip.py` pins two same-library exports byte-identical and export→import→re-export reproducing the sender's bytes | cap 9 |
| H380 | `import events` re-import idempotency guard (test-only) — `tests/test_roundtrip.py` pins a second `import events` as a whole-ledger no-op on the report, the raw `custody_events` row count, and every per-item history timeline | cap 9 |
| H381 | MCP `get_library_health` whole-payload determinism guard (test-only) — `tests/test_mcp.py` pins the agent-facing custody audit byte-identical same-process and across hash-seed subprocesses | cap 1/2 |
| H382 | MCP `get_context_bundle` whole-payload determinism guard (test-only) — `tests/test_context.py` pins the MCP bundle byte-identical to the CLI `build_context` and across hash-seed subprocesses | cap 1, cap 3 |
| H383 | MCP `run_maintenance` whole-payload determinism + no-movement settle guard (test-only) — `tests/test_mcp.py` pins two calls settled on every delta axis and the payload byte-identical across hash-seed subprocesses | cap 1/2 |
| H384 | `export events` JSONL whole-file determinism + round-trip byte-identity guard (test-only) — `tests/test_roundtrip.py` pins two same-library exports byte-identical and a full-restore re-export reproducing the sender's bytes | cap 9 |
| H385 | `scrolls archive show` JSONL determinism + restore round-trip guard (test-only) — `tests/test_cli.py` pins two reads byte-identical (default + `--all`) and a real re-adopt of the shown prior via `import items --accept-incoming` | cap 9 |
| H386 | `import archive` whole-store re-import idempotency guard (test-only) — `tests/test_cli.py` pins a second import as a no-op on the report, the raw `item_archive` row count, and each item's multi-prior recovery history | cap 9 |
| H387 | MCP `get_link_graph` whole-payload determinism guard (test-only) — `tests/test_mcp.py` pins the agent-facing whole-link-structure read byte-identical same-process and across hash-seed subprocesses | cap 3/10 |
| H388 | Whole MCP read-surface determinism contract (test-only) — one completeness-asserted guard in `tests/test_mcp.py` over every registered read tool, retiring the per-tool determinism-twin treadmill (the queued H389/H391/H392/H393 subsumed and pruned) | cap 1/2 |
| H390 | `export archive` whole-library JSONL determinism + round-trip byte-identity guard (test-only) — `tests/test_roundtrip.py` pins two same-library exports byte-identical and a full-restore re-export reproducing the sender's bytes; third leg of the transport-determinism triptych | cap 9 |
| H394 | CLI read-surface determinism contract (test-only) — `tests/test_cli_determinism.py` classifies every argparse leaf subcommand (read/write/exempt) and pins every JSON read byte-identical same-process and across hash-seed subprocesses | cap 1/2 |
| H395 | Round-trip transport contract (test-only) — `tests/test_roundtrip.py` pins every lossless export/import transport (`items`/`events`/`archive`/`bundle`) deterministic and byte-reproducible through a fresh-home round-trip, with a completeness keystone over the live registry | cap 4 |
| H396 | Regeneration-safety contract (test-only) — `tests/test_regeneration_safety.py` pins a `@user` annotation surviving re-compile (and stale fenced content purged) across every generated-artifact family, keyed to the live compiler/installer registries (ADR 0102) | cap 6 |
| H397 | Surface-parity contract (test-only) — `tests/test_surface_parity.py` pins every held item's custody axes reading identically across `search`/`list`/the MCP twins/`facets` against one canonical projection | cap 3 |
| H398 | Completeness-honesty contract (test-only) — `tests/test_completeness_contract.py` pins every browse/audit surface scope-honest (a filtered slice never reads as the whole library) and empty-vs-could-not-check honest | cap 7 |
| H399 | Re-import idempotency contract (test-only) — `tests/test_roundtrip.py` pins import-twice as a whole-store no-op on both the report and the raw dedup-table row count for every lossless `import <kind>`, retiring the scattered ingest-idempotency cells | cap 4 |
| H400 | CLI↔MCP read-parity contract (test-only) — `tests/test_cli_mcp_parity.py` pins every MCP read tool's custody-bearing payload identical to its CLI twin (or a named exemption), partitioning the MCP read surface exactly | cap 3 |
| H401 | Bundle-format briefing-parity contract (test-only) — `tests/test_bundle_format_parity.py` pins every custody briefing fact rendering the same content in both the Markdown and HTML bundle forms, keyed to the two builders' ASTs | cap 9 |
| H402 | Reconcile-safety contract (test-only) — `tests/test_reconcile_safety.py` pins that when a compiled page's group vanishes, the reconcile tombstones an annotated stale page (note preserved byte-for-byte) and unlinks a plain one, across every reconcilable dir-kind (ADR 0102) | cap 6 |
| H403 | Browse-filter drill contract (test-only) — `tests/test_browse_filter_drill.py` pins every custody/rank browse filter on `search`/`list` (+ MCP twins) selecting exactly the unfiltered rows at that value, keyed to the live argparse optionals | cap 3 |
| H404 | Compiled-page custody-honesty contract (test-only) — `tests/test_compiled_page_custody_honesty.py` pins every custody-bearing compiled page rendering its `_Custody:`/`_By source:`/`_Attention:`/`_Refresh:` lines honestly (headline always, pointers iff a non-empty basis); `graph.md`/`works.md` named exemptions | cap 2 |
| H405 | Lossless-importer conflict/adoption parity contract (test-only) — `tests/test_import_conflict_parity.py` pins `import items`/`import bundle` detecting a content conflict identically (held copy kept, durable `conflict` event) and adopting identically under `--accept-incoming` | cap 4 |
| H406 | CLI↔MCP write-act parity contract (test-only) — `tests/test_cli_mcp_write_parity.py` pins every custody-safe MCP write tool producing the same durable custody effect as its CLI act twin, partitioning the MCP write surface exactly | cap 4 |
| H407 | Rank-explainability convergence contract (test-only) — `tests/test_rank_explainability.py` pins every rank-band surface reading the canonical `match_strength`/`relation_strength` fold, each headline tally converging with its per-row bands; `graph` reclassified as no-rank-axis | cap 8 |
| H408 | Raw-immutability act-surface contract (test-only) — `tests/test_raw_immutability_acts.py` pins every CLI write leaving the raw `scrolls/` tree byte-identical except the four named scroll-file writers (`ingest`/`classify`/`set`/`rm`) | cap 4 |
| H409 | Append-only custody-ledger contract (test-only) — `tests/test_ledger_append_only.py` pins the `custody_events` row set only ever growing across every mutating surface, each appends-act joining exactly its declared verb (ADR 0104); `reconcile`/`archive restore` reclassified as appends | cap 8 |
| H410 | Stale-set drill contract (test-only) — `tests/test_stale_set_drill.py` pins each `--stale-*` filter on `list` (+ `list_scrolls`) selecting exactly its act-side companion's targets and totalling the audit aggregate | cap 7/1 |
| H411 | Facet-aggregate drill contract (test-only) — `tests/test_facet_aggregate_drill.py` pins every drillable `facets <dim>` value count equal to the rows the matching `list`/`search` filter enumerates (`method` the named no-drill exemption) | cap 7 |
| H412 | Enrichment-provenance convergence contract (test-only) — `tests/test_provenance_convergence.py` pins every provenance-bearing surface reading the canonical `classification_provenance` view per item and the `facets method` engine tally in aggregate | cap 8 |
| H413 | Recency-`last_checked` convergence contract (test-only) — `tests/test_recency_convergence.py` pins every per-item recency surface (incl. `works`/`graph`, reclassified in) reading the canonical `last_checked` projection, never fabricating one for a never-checked item | cap 1/8 |
| H414 | Could-not-check (G1) error-parity contract (test-only) — `tests/test_g1_error_parity.py` pins every targeted read surfacing a could-not-check as the same typed error across its CLI↔MCP twin (byte-identical on the id axis, structural on the argparse-`choices` vocab axis), never a silent empty | cap 7 |
| H415 | Bundle-briefing ↔ live-audit convergence contract (test-only) — `tests/test_bundle_audit_convergence.py` pins every audit-basis briefing line of a whole-library-scope bundle equal to the live `run_doctor` custody projection | cap 9 |
| H416 | Preview ↔ live-run parity contract (test-only) — `tests/test_preview_parity.py` pins the four real preview surfaces (`import bundle --dry-run`/`reconcile --dry-run`/`archive restore --dry-run`/`archive prune`) touching nothing on all three durable axes while predicting the live disposition exactly | cap 7/9 |
| H417 | Facet scope-composition convergence contract (test-only) — `tests/test_facet_scope_composition.py` pins `facets <dim> --<scope> V` equal to the dimension recomputed over the rows `list --<scope> V` enumerates, plus the two-facet AND case | cap 7 |
| H418 | Audit-aggregate ↔ browse-drill convergence contract (test-only) — `tests/test_audit_drill_convergence.py` pins every drillable `doctor`/`get_library_health` custody count equal to the matching `list` filter's row count (`summaries.stale` named non-drillable) | cap 1/7 |
| H419 | Compiled group-page classification marker (production, `src/scrolls/kb.py`) — the shared classification phrase now renders on every compiled group-page row inside the fence, omitted on honest absence; the H412 contract promoted `get_concept_page`/`get_tag_page` into its provenance surfaces (`tests/test_provenance_convergence.py`) | cap 8, cap 2 |
| H420 | Truncation / scope-echo honesty contract (test-only) — `tests/test_truncation_scope_honesty.py` pins `stats.matched` as the full pre-cap count, `stats.truncated == matched > returned`, and rows as the top-limit prefix across the truncation surfaces | cap 7 |
| H421 | Context-briefing ↔ live-audit convergence contract — `tests/test_context_audit_convergence.py` reuses the H415 audit-basis registry against `scrolls context --budget full`; production change: the context briefing folds its audit lines over the uncollapsed match scope so same-work collapse cannot hide held rows | cap 9 |
| H422 | Live-act settle parity contract — `tests/test_live_settle_parity.py` pins every preview-capable live act settled on its second run across the ledger/raw/row-count durable axes; production change: re-presenting the same still-open import conflict no longer appends a duplicate conflict event | cap 7/9 |
| H423 | Archive-selector recovery convergence contract — `tests/test_archive_selector_convergence.py` pins `archive show`/`archive diff`/`archive restore --dry-run` to the same selected prior for `latest`/`--hash`/inclusive `--at`; `archive show` gained `--hash`/`--at` via the shared selector | cap 1/9 |
| H424 | Per-source scoped audit-drill convergence contract — `tests/test_source_audit_drill_convergence.py` pins every per-source `tiers`/`drift` audit count across `doctor.by_source`/`doctor --source`/`get_library_health(source=)` equal to `list --source S --<filter>`, per-source sums reproducing the whole-library counts | cap 1/5/7 |
| H425 | Compiled group-page custody-marker convergence contract — `tests/test_group_page_custody_marker_convergence.py` pins the rendered `get_concept_page`/`get_tag_page` row markers equal to the canonical per-item `(fidelity, drift, last_checked)` projection read by `list`/`show`/`get_scroll` | cap 1/9 |

---

## Maintenance rule — keeping the buffer fresh

The buffer rots if nobody refreshes it. The rule:

1. **Every run, before stopping**, the worker checks whether the lead work slot
   is done. If fewer than ~6 un-started work slots remain, it **appends** new
   concrete slices derived from the MVP and PRD so the lead always covers the
   next ~24h.
2. **At least once per 24h** (or the first run after midnight UTC), do a full
   refresh: fold completed slots into the shipped ledger, prune slices overtaken
   by events, and re-derive the forward plan. Dated status snapshots and
   day/week plans belong in the dated check-in dirs
   (`docs/agents/progress/<YYMMDD>/`), not in this file.
3. **Date discipline:** always write absolute dates (`YYYY-MM-DD`), never
   "today" — this doc is read later (obsidian anti-pattern: `date: today`).
4. **Provenance:** when a slice ships, the commit subject (with its `(H<NN>)`
   tag) and any ADR are the record; this doc points forward, not backward. Don't
   turn it into a changelog — git is the changelog. The shipped ledger is a
   one-line index only.
5. **No invented work:** a slice goes on the buffer only if it has a concrete
   implementation path and maps to a PRD capability. If none qualifies, the
   correct buffer entry is "report blocker," not filler.
6. **File size:** if the doc again approaches the Read-tool ceiling (~256 KB),
   the full refresh must re-compact the shipped ledger and prune any prose that
   has re-accreted (the H187 lesson — the file had grown to ~370 KB / ~430 rows
   of changelog prose before this refresh).

---

## How this maps to the PRD/MVP

| Theme | PRD capability | MVP slice |
| --- | --- | --- |
| Refresh-safe generated artifacts | cap 6 | M1 + ADR 0102 |
| Completeness / anti-fabrication invariant | cap 7 | M2 |
| Progressive context budgets | cap 10 | M3 |
| Shareable custody bundle (`export/import bundle`) | cap 9 | M4 + ADR 0103 |
| Dogfood proof (`docs/dogfood.md`) | cap 11 | M5 |
| Re-derivable enrichment + confidence markers | cap 8 | post-MVP |
| Scheduled custody maintenance (`scrolls maintain`) | cap 1 | post-MVP |
| Per-item + scope custody picture everywhere | cap 1/2/7/8/10 | post-MVP |
| Per-source custody breakdown + scoped reads/acts | cap 1/2/5/7/8 | post-MVP |
| Maintenance & dogfood over MCP | cap 1/11 | post-MVP |
| Custody-filter family (`--fidelity`/`--drift` browse/rank/act) | cap 1/2/7 | post-MVP |

The two obsidian-second-brain adoptions (M1 refresh-safe regeneration, M2
completeness invariant) were intentionally first in the queue: they are the
decision-grade, custody-deepening slices, and everything later reads cleaner
once raw is sacred and absence is honest.
