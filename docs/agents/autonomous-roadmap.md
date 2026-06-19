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

## Status snapshot — 2026-06-19

**MVP M1–M5 complete** (custody-first): refresh-safe sentinel-fenced
regeneration (M1, ADR 0102), the anti-fabrication/completeness invariant (M2),
progressive `context --budget` tiers (M3), the shareable `export/import bundle`
custody bundle (M4, ADR 0103), and the offline dogfood proof
*hold → prove → detect → take it with me* (M5, `docs/dogfood.md`).

**Post-MVP themes complete** (all custody-deepening, no new adapters):

- **cap 8 — re-derivable enrichment.** Classification *and* LLM concept
  summaries record inputs/method and regenerate on request:
  record → report (`doctor`) → refresh (`classify --stale` / `kb --stale`) →
  confidence/freshness marker → cross-engine invariant
  (`tests/test_enrichment_provenance.py`).
- **Per-item custody picture** (`fidelity` + `drift`) reads identically on every
  surface — `list`/`search`/`related`/`graph`/bundle/`show`/`works` and the
  compiled `library/` pages — pinned by `tests/test_custody_convergence.py`.
- **Scope custody headlines** ride `status`/bundle/`context`/`graph`/`facets`
  and the compiled group + index pages, all from one shared
  `custody.custody_headline` primitive.
- **Scheduled custody maintenance.** `scrolls maintain` (recheck → regenerate →
  audit → custody delta), an append-only trend log (`maintain --history
  [--trend]`), and by-finding repair `suggested` blocks — report-only and
  idempotent (custody §2.4).
- **Per-source custody breakdown.** `custody.by_source` (`{tiers, drift,
  coverage}`) + the single weakest-source `attention` flag across
  `doctor`/`status`/`maintain`/`graph`, the scoped `--source` reads
  (`doctor`/`status`/`maintain`) and acts (`verify --source`, `classify/kb
  --stale --source`), with `maintain`↔`doctor`↔`status` convergence invariants.
- **Maintenance & dogfood over MCP.** `run_maintenance` (+ scoped),
  `get_maintenance_history`, and the agent-driven dogfood loop
  (`tests/test_dogfood_mcp.py`).
- **Readable action lines.** `_Attention:_`/`_Refresh:_` pointers render
  byte-identical across the Markdown surfaces and converge with `doctor`.

**Per-slice provenance is in git** — every shipped slice's commit subject carries
its `(H<NN>)` tag, so `git log --oneline | grep '(H183)'` resolves any slice to
its full description and diff. This doc points **forward** (maintenance-rule §4:
*git is the changelog*); the compact **Shipped ledger** below is the in-file
index that keeps `H<NN>` cross-references resolvable.

---

## Live work queue (un-started)

Ordered. Take the next slice whose preconditions are met (all listed
preconditions are shipped), finish it to a committed/tested/clean stopping
point, and stop. `→ capN` marks the PRD capability. These are the only
un-started **work** slices; the next checkpoint (H207) follows.

| Slot | Intended slice | Maps to |
| --- | --- | --- |
| H179 | **Status per-source stale-debt convergence folded into `tests/test_custody_convergence.py` (cap 8).** Appended (maintenance rule, buffer top-up). Once `status` carries `enrichment_by_source`/`summary_by_source` (H177), the cross-surface convergence suite — the one home for the `status`≡`maintain`≡`doctor` ties — should pin the refresh-debt axis beside the drift `by_source` tie (H157) and the maintain enrichment/summary ties (H147/H175). Over the multi-source stale-classification **and** stale-summary seed, assert `status`'s `enrichment_by_source` ≡ `maintain`'s ≡ `doctor`'s `custody.enrichment.by_source`, and likewise on the summary axis (carrying the non-sum-to-whole asymmetry), with the `--source`-scoped slice equal too; non-vacuous and mutation-checked. Test + docs only; no production change. Precondition: **H177** (the status debt maps, shipped); H157 (the JSON `by_source` convergence precedent, shipped). | → cap 8 |
| H183 | **Scoped-suggestion ↔ debt-map convergence folded into `tests/test_custody_convergence.py` (cap 1 + cap 8).** Appended (maintenance rule, buffer top-up after H181 shipped). H181 pinned the scoped-suggestion behavior in `tests/test_maintain.py`; the convergence suite — the home for the cross-surface custody ties (H157/H169 `by_source`, H147/H175 maintain debt-map ties, H177 status ties) — should also pin that `maintain`'s **scoped** `suggested` refresh commands name exactly the sources the debt maps do. Over a confined multi-source stale-classification **and** stale-summary seed, assert the set of sources in the scoped `classify --stale --source <S>` suggestions ≡ `enrichment_by_source`'s keys, and likewise the `kb --stale --source <S>` suggestions ≡ `summary_by_source`'s keys (carrying the H171 multi-source attribution — a cluster's every member appears), with the whole-library fallback asserted when every source is stale. Non-vacuous (≥2 sources, one clean so scoping fires) and mutation-checked. Test + docs only; no production change. Precondition: H181 (the scoped suggestions, shipped); H157 (the convergence-suite precedent, shipped). | → cap 1, cap 8 |
| H192 | **Action-line *content* parity on the bundle HTML form (cap 5 + cap 8).** Appended (maintenance rule, buffer top-up after H188 shipped). H188 pins the `_Attention:_`/`_Refresh:_` lines **byte-identical** across the *Markdown* surfaces (bundle-MD / `context` / compiled-index / compiled-group-page); the HTML bundle (`build_bundle_html`) renders the same pointers as `<p class="custody-attention">` / `<p class="custody-refresh">`, so it cannot be *string*-identical to the Markdown, but its **content must not diverge**. Pin the HTML counterpart in `tests/test_custody_convergence.py` beside H188: over the same `_seed_action_line_fixture` scope, the HTML `_Attention:_` fields (`_attention_fields(html, _ATTENTION_HTML)` → `{source, reason, command}`, already parsed in H159) equal the Markdown line's fields, and the HTML `_Refresh:_` per-axis source lists (`_refresh_sources(html, _REFRESH_*_HTML)`) equal the Markdown's — so the two forms name the same source(s)/reason/command over one scope, the action-line analogue of H151's `_html_by_source_bullets` content tie. Non-vacuous (both axes present) and mutation-checked (perturbing the data moves both forms together). Test + docs only; no production change. Precondition: H188 (the Markdown byte-identical invariant, shipped); H159/H178 (the HTML parsers `_ATTENTION_HTML`/`_REFRESH_*_HTML`, shipped). | → cap 5, cap 8 |
| H193 | **Single-source compiled `sources/*.md` page `_Refresh:_` honest presence ≡ `doctor --source`'s debt (cap 7 + cap 8).** Appended (maintenance rule, buffer top-up). H190 pins the compiled honest-*absence* (a clean page omits the action lines); the positive companion is that a **single-source** compiled `sources/<S>.md` page shows the `_Refresh:_` line (it has *no* single-source gate, unlike `_Attention:_`/`_By source:_`) **exactly when** source `<S>` carries stale debt, naming the same axes `doctor --source <S>`'s `custody.enrichment.by_source`/`summaries.by_source` do — and never `_Attention:_` or `_By source:_` on that single-source page. Fold into `tests/test_custody_convergence.py` (the compiled-surface convergence home, beside H184/H190): over a seed where one source carries a stale classification (and optionally a within-source stale summary cluster), `sources/<S>.md`'s `_Refresh:_` clauses ≡ `run_doctor(source=S)`'s debt-map keys for the page's own scope (the scope-consistent posture H178/H184 took), with the multi-source-concept-narrowed-below-`MIN_MEMBERS` summary-absence case from H184 pinned positively. Non-vacuous (≥1 source with debt) and mutation-checked (refresh clears the clause). Test + docs only; no production change. Precondition: H184 (the compiled action lines + scope-consistency, shipped); H190 (the honest-absence sibling, shipped). | → cap 7, cap 8 |
| H195 | **Object-twin `stats.custody.by_source` *content* converges with `doctor` over a whole-library scope (cap 1 + cap 2).** Appended (maintenance rule, buffer top-up). H186 pins the *shape* (the object twins carry `stats.custody.by_source`); the unproven *content* tie is that, **when the scope is the whole library** (every item connected in the graph / represented in a work), `get_link_graph`/`get_works` `stats.custody.by_source` equals `run_doctor`'s `custody.by_source` field-for-field — the per-source split is the same tally, only differently scoped. The load-bearing subtlety to pin (not just assert equality): the graph/works maps are **scope-restricted** (connected-only / representation-only), so they equal the whole-library audit *exactly when* the seed leaves nothing isolated/unrepresented; over a seed with an isolated item, the object-twin map is a strict subset of doctor's — the honest scope difference, never a disagreement. Fold into `tests/test_custody_convergence.py` beside the H157/H169 `by_source` ties (the cross-surface convergence home): the whole-connected case (object-twin ≡ doctor) and the isolated-item case (object-twin ⊂ doctor, the dropped source is the isolate's). Non-vacuous (≥2 sources) and mutation-checked. Test + docs only; no production change. Precondition: H186 (shipped); H150/H155 (the object-twin `by_source`, shipped); H157 (the convergence-suite precedent, shipped). | → cap 1, cap 2 |
| H206 | **CLI-side attention→scoped-maintenance triage folded into the shell dogfood flow (cap 11).** Appended (maintenance rule, buffer top-up after H204 shipped). H204 pinned the *MCP* attention→scoped-pass triage as one agent-driven flow (`tests/test_dogfood_mcp.py`); the symmetric **shell** flow — read `scrolls status`/`doctor` (the `attention` JSON flag names the weakest source) → run `scrolls maintain --source <that source>` to triage just it — is pinned per-command (H139/H165/H181) but not as one end-to-end dogfood sequence in `tests/test_dogfood.py` (the CLI dogfood home, where the whole-library `maintain` leg already lives). Add a test that drives that exact sequence over the CLI dogfood's drifted multi-source fixture: assert `status --json`'s `attention.source` names the weakest source, that `maintain --source <that source>` scopes to it (singleton `by_source`, null `attention`, `custody == doctor --source <S>`'s distilled), and that the scoped pass is **non-persisting** (the whole-library snapshot/log the dogfood's earlier whole-library `maintain` recorded is untouched, `delta` honestly absent) — the shell sibling of H204's MCP flow, so the triage-where-the-loss-is point is pinned over *both* surfaces. Non-vacuous (≥2 sources, one clean) and mutation-checked. Test + docs only (`docs/dogfood.md`'s CLI flow section gains the attention→`maintain --source` triage sentence beside the recurring `maintain` leg); no production change. Precondition: H204 (the MCP sibling, shipped); H139 (`status` JSON `attention`, shipped); H165/H181 (`maintain --source`, shipped); the CLI dogfood suite (shipped). | → cap 11 |
| H207 | **Buffer refresh checkpoint** (maintenance rule). Mark shipped slices into the ledger, prune overtaken slices, keep ≥6 un-started work slots, and re-derive the 3-day/week plans with absolute dates. Re-confirm the week plan still maps to `docs/product/mvp.md`. Bi-temporal drift framing stays deferred unless an agent workflow shows the event record insufficient. | maintenance |

The current un-started theme is the **cross-surface convergence + readable-parity
tail** of the per-source custody work: three convergence invariants (H179, H183,
H195), two compiled/HTML readable-parity ties (H192, H193), and the CLI dogfood
symmetry (H206). All are test+docs slices over already-shipped production code —
they pin contracts, not new behavior.

If the queue empties before the day does, deepen tests/fixtures on the slice just
shipped or pick the next-highest PRD capability — never manufacture cosmetic
churn (CLAUDE.md, *Avoid trivial progress*).

---

## Shipped ledger (compact index)

One line per shipped slice; full description + diff live in git
(`git log --oneline | grep '(H<NN>)'`). `maint` = buffer checkpoint. This index
exists only to keep `H<NN>` cross-references resolvable in-file — it is **not** a
changelog (maintenance-rule §4).

| Slot | Shipped | Maps to |
| --- | --- | --- |
| H1 | Sentinel boundary defined and implemented for compiled `library/` pages: pure helper `src/scrolls/gen… | M1, cap 6 |
| H2 | KB compiler writes every generated region inside the fence; a re-compile replaces only the fenced con… | M1, cap 6 |
| H3 | M1 extended to generated `agents/` files: `install_agent_docs` now writes through `generated.write_ge… | M1, cap 6 |
| H4 | `docs/architecture.md` Agent-install entry now describes the refresh-safe boundary; `docs/library-for… | M1, cap 6 |
| H5 | M2 contract written into `docs/cli.md` as a new top-level "The completeness contract" section, split… | M2, cap 7 |
| H6 | M2 G2 enforced on `search` + `list` via an opt-in `--stats` envelope | M2, cap 7 |
| H7 | M2 enforce on `context` + `related` + `works` | M2, cap 7 |
| H8 | M2 enforce on `doctor` — M2 complete | M2, cap 1/7 |
| H9 | M3 design folded into the implementation: the budget tiers are specified in `docs/cli.md` (the `--bud… | M3, cap 10 |
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
| H72 | Whole-library portable custody — `scrolls export events` / `import events` | cap 9 |
| H73 | Portable-custody round-trip invariant — the posture survives export→import | cap 7, cap 9 |
| H74 | Buffer checkpoint | maint |
| H75 | Incremental custody backup — `scrolls export events --since <ISO>` | cap 9 |
| H69 | `scrolls history <id> --limit N` — bound a long per-item ledger to the most recent N checks | cap 1, cap 7 |
| H70 | Fold `scrolls history` into the per-item custody-convergence invariant — the timeline head ≡ the post… | cap 1, cap 7 |
| H71 | `scrolls history <id> --since <ISO>` — the per-item ledger window by time | cap 1, cap 7 |
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
| H152 | Per-source custody breakdown on the compiled multi-source group list pages — `categories/`, `concepts… | cap 1, cap 2 |
| H151 | Per-source custody breakdown rendered-line cross-surface invariant | cap 1, cap 7 |
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
| H175 | `maintain` report carries `summary_by_source` — the scheduled-surface read of H171's per-source stale… | cap 8, cap 1 |
| H174 | Weakest-source `attention` flag on the lean browse-stats `stats.custody` family — `search`/`list`/`re… | cap 2, cap 7 |
| H176 | Summary-axis per-source refresh convergence folded into `tests/test_custody_convergence.py` | cap 8, cap 1 |
| H177 | `status` JSON carries `enrichment_by_source` + `summary_by_source` — the read-surface per-source stal… | cap 2, cap 8 |
| H178 | Readable per-source `_Refresh:_` line on the `context`/`export bundle` briefing — the enrichment/summ… | cap 5, cap 8 |
| H180 | MCP `get_library_health` keeps the fuller nested refresh-debt block — flat≡nested tie pinned | cap 2, cap 8 |
| H181 | `maintain`'s `suggested` block emits *source-scoped* refresh commands when debt is confined | cap 1, cap 8 |
| H182 | `maintain --source <S>` suggests the *scoped* refresh, not the whole-library sweep | cap 1, cap 8 |
| H184 | Readable `_Attention:_` + `_Refresh:_` action-pointer lines on the compiled `library/` index/group pages | cap 1, cap 5, cap 8 |
| H185 | `scrolls list --stale-classification` — browse the stale-enrichment set | cap 7, cap 8 |
| H186 | MCP read-surface shape contract pinned once — the capstone of H163/H180 | cap 2, cap 7 |
| H188 | Action-pointer lines byte-identical across *all* readable surfaces | cap 5, cap 8 |
| H189 | `scrolls list --stale-summary` — browse the items in a stale-summary cluster | cap 7, cap 8 |
| H191 | Buffer checkpoint | maint |
| H190 | Compiled-page action-line honest-absence folded into the M2 completeness invariant | cap 7, M2 |
| H194 | The Markdown-string read twins are the *fourth* shape class in the H186 contract | cap 2, cap 7 |
| H196 | `run_maintenance` MCP tool — the scheduled custody pass over MCP | cap 1, cap 11 |
| H197 | Buffer checkpoint | maint |
| H198 | `get_maintenance_history` MCP tool — the custody *trend* over MCP, the read sibling of H196 | cap 1, cap 11 |
| H200 | Buffer checkpoint | maint |
| H201 | MCP-driven dogfood custody loop — the agent-facing counterpart of `docs/dogfood.md` | cap 11 |
| H202 | Buffer checkpoint | maint |
| H203 | Scoped `run_maintenance(source=)` over MCP — the source-scoped custody pass an agent runs on the weak… | cap 1, cap 11 |
| H204 | Scoped MCP maintenance pass folded into the agent-driven dogfood flow | cap 11 |
| H205 | Buffer checkpoint | maint |

---

## 3-day plan — 2026-06-19 → 2026-06-22

Forward-looking (re-derived at this H187 full refresh). Each day ends on a
committed, tested, clean stopping point; slips roll forward.

- **Day 1 (2026-06-19):** The per-source custody **convergence-invariant**
  cluster. H179 (status `enrichment_by_source`/`summary_by_source` ≡ `maintain`
  ≡ `doctor`, refresh-debt axis), H183 (scoped `suggested` refresh commands name
  exactly the debt-map sources), H195 (object-twin `stats.custody.by_source`
  content ≡ `doctor` over a whole-library scope, with the scope-subset honesty
  for isolated items). All fold into `tests/test_custody_convergence.py`.
- **Day 2 (2026-06-20):** The **readable / compiled-page parity** cluster.
  H192 (action-line *content* parity on the bundle HTML form vs Markdown),
  H193 (single-source compiled `sources/<S>.md` `_Refresh:_` honest presence ≡
  `doctor --source <S>` debt). Both pin the action-line contract onto the two
  surfaces H188 left out.
- **Day 3 (2026-06-21 → 2026-06-22):** The **dogfood symmetry** H206 (CLI
  attention → `maintain --source` triage as one shell flow in
  `tests/test_dogfood.py`, the sibling of H204's MCP flow), then re-derive the
  next custody-deepening horizon at the H207 checkpoint.

---

## Week plan (more tentative) — through 2026-06-26

- Close the per-source custody **convergence invariants** (H179, H183, H195) and
  the **compiled/HTML readable-parity** ties (H192, H193): make "custody reads
  the same everywhere" a tested contract on the per-source and action-line axes.
- Pin the **CLI/MCP dogfood symmetry** (H206) so the attention → scoped-triage
  flow is proven on both surfaces.
- Re-derive the next post-MVP horizon at the next full checkpoint. Candidate
  directions stay custody-deepening (no new adapters): portable-custody depth,
  progressive context bundles, doctor/repair surfacing.
- Consider a bi-temporal framing pass on drift events (captured-at vs
  source-changed-at) *only if* an agent workflow shows the event record is
  insufficient; otherwise keep deferred (MVP "out of scope").
- Explicitly **not** this week: new adapters, productivity surfaces, paid
  research integrations.

---

## Maintenance rule — keeping the buffer fresh

The buffer rots if nobody refreshes it. The rule:

1. **Every run, before stopping**, the worker checks whether the lead work slot
   is done. If fewer than ~6 un-started work slots remain, it **appends** new
   concrete slices derived from the MVP and PRD so the lead always covers the
   next ~24h.
2. **At least once per 24h** (or the first run after midnight UTC), do a full
   refresh: fold completed slots into the shipped ledger, prune slices overtaken
   by events, re-derive the 3-day plan, and re-confirm the week plan still maps
   to `docs/product/mvp.md`.
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

The two obsidian-second-brain adoptions (M1 refresh-safe regeneration, M2
completeness invariant) were intentionally first in the queue: they are the
decision-grade, custody-deepening slices, and everything later reads cleaner
once raw is sacred and absence is honest.
