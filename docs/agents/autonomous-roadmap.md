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

## Status snapshot — 2026-06-22

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
- **Self-healing dogfood, both surfaces, both act axes.** The
  *act-where-the-loss-is* flow — read the pointer → run exactly the scoped act it
  names → the debt clears — is now pinned on the **drift** axis over MCP (H204) and
  the CLI shell (H206), and on the **enrichment/summary refresh** axis over the CLI
  shell (H210, `tests/test_dogfood.py`). The drift triage reads `status`'s
  `attention` → runs `maintain --source <S>`; the refresh triage reads the
  `context` `_Refresh:_` line → runs the scoped `classify --stale --source <S>` /
  `kb --stale --source <S>`.
- **The custody-filter family is complete across both axes and *every* surface —
  read, act, relate, maintain, context bundle, the portable shareable bundle,
  the whole-library JSONL backup, *and* the whole-library custody-ledger backup.**
  The two per-item custody axes — *holdings* (`fidelity`, a content-column fact,
  no ledger) and *ledger-claim* (`drift`, the verify-ledger posture) — can now be
  **browsed, ranked, acted on, scoped on the relationship surface, scoped on the
  agent context bundle, scoped on the portable `export bundle`, *and* scoped on
  the whole-library `export items` backup**:
  `list --fidelity` (H250) / `search --fidelity` (H251) / `verify --fidelity`
  (H252) / `related --fidelity` (H254) / `context --fidelity` (H257) /
  `export bundle --fidelity` (H258) / `export items --fidelity` (H259) on the
  holdings axis, and `list --drift`
  (H54) / `search --drift` (H253) / `verify --drift` (H80) / `related --drift`
  (H254) / `context --drift` (H257) / `export bundle --drift` (H258) /
  `export items --drift` (H259) on the
  ledger axis, each with its MCP twin
  where one exists
  (`list_scrolls`/`search_scrolls`/`get_related_scrolls`/`get_context_bundle`;
  the CLI-only act/export surfaces `verify`/`maintain`/`export bundle`/`export items`
  have none).
  Every filter folds the
  *same* primitive the per-item field is read off
  (`get_fidelity`/`fidelity_tier`, `drift_posture`/`posture_from_status`), so a row
  is selected by exactly the value it shows, and the per-value totals partition the
  scope (drill-from-`facets fidelity`/`drift`, or — for `related`, which has no
  facets analogue — drill-from-the-neighbourhood `--stats` tally). The ranked
  surface scopes *before* the cap (UDF-in-SQL, never a post-sieve), and the
  `related` neighbourhood sieve and the `context` bundle sieve run *before* their
  `[:limit]`/budget cap (the `list`-sieve shape over the scored hits), so
  `--stats`/Coverage truncation counts only the kept set (G2). `context` reuses
  `search`'s before-cap UDF sieve verbatim (threading `fidelity`/`drift` through
  `search_items`/`count_matches`), so its `_Custody:_`/`_Fidelity:_` headline,
  per-excerpt drift tags, and Coverage denominator all describe exactly the kept
  set. **H259 closed the family's `export items` (raw-rows backup)** — threading
  `fidelity`/`drift` through `list_items` (which already applies both, the
  H250/H54 primitives), and because the post-SQL sieve preserves saved order the
  scoped JSONL is the byte-identical subset of the unscoped backup, so `import
  items` of a custody-scoped backup re-holds exactly the exported rows (the H216
  round-trip under a custody scope). **H260 (this run) closed the family's *last*
  surface — `export events --fidelity`/`--drift`, the whole-library
  custody-ledger backup** — as an **item-set sieve** (the one design choice the
  slice resolved): the two axes narrow the *item resolution* (the same
  `list_items` sieve H259 folds), then the **whole ledger** of the selected items
  travels, exactly as `--source` already scopes events by item — so `--drift
  drifted` ships a moved item's *entire* custody history (its earlier `unchanged`
  rows included), the full proof of *when* the source moved for a recapture
  handoff, not a single per-row match. Composes with `--since` (item-set sieve,
  then time window) and the durable facets; the drift-scoped backup round-trips
  losslessly into a fresh library with no leakage of the filtered-out items'
  events. **With H260 the custody-filter family is closed across every read, act,
  and export surface; the next theme is the consolidation surface — work-level
  custody (H261–H263), vision §3.5.**
- **Work-level custody consolidation — a work has an aggregate custody posture *and*
  is scopable by it.** `scrolls works` (CLI + MCP `get_works`) reports a per-work
  `custody` block `{best_fidelity, safest_drift, safely_held}` (H261), folding the
  per-rep `fidelity`/`drift` `works` already computes into one work-level verdict —
  the **consolidation** of representations, the new custody *shape* (vision §3.5):
  "is this work *safely held*?" `safely_held` is the strong form — ∃ a
  representation that is `full` *and* drift ∈ {verified, unverified} (an unmoved,
  fully re-derivable copy exists); `partial` can't fully re-derive and
  `drifted`/`rotted`/`error` aren't safe, and both must hold on the *same* rep. The
  shared `works.work_custody` helper (+ the `custody.SAFE_DRIFT_POSTURES` vocab
  constant) is the primitive H263's at-risk-works signal reuses — no schema change, a
  pure fold over data `works` already computes. **H262 then lifted the
  custody-filter family to this surface** — `scrolls works --fidelity`/`--drift` + the
  MCP `get_works` twin — over the *contains* semantics (a work is kept *whole* iff it
  has a representation at the custody value; both axes AND on the *same* rep), via the
  shared `works.filter_works` sieve, so `--drift drifted` surfaces the works needing a
  recapture decision with their safe siblings intact. `stats.custody` honors the
  filter, the filters ride the `scope` echo (G2) and compose with the per-item `ref`
  lens, closed vocab → exit 2 / `ValueError` — and, again, no schema change. **H263
  (this run) turned the `safely_held` verdict into an alarm** — the *at-risk-works*
  signal on `doctor` + `maintain` + MCP `get_library_health`: a work is **at risk**
  when **no** representation is safely held (the H261 `safely_held == False` set —
  every copy degraded or moved, no unmoved full form anywhere), the
  consolidation-level analogue of the per-source weakest-source `attention` flag and a
  sharper alarm than the per-item drift count (an item drifting is survivable if a
  sibling rep is still full+verified; a *work* with no safe rep is a real loss). The
  shared `works.at_risk_signal` (a pure fold over the H261 aggregate, **no schema
  change, no extra ledger read**) surfaces `{status, total, at_risk, most_at_risk}` —
  `most_at_risk` the single lowest-custody-ceiling work (worst `best_fidelity`, then
  worst `safest_drift`, then `doi`), with a self-describing `reason` and **no
  fabricated `command`** (no whole-library recapture act exists; the `suggested`-block
  orphan discipline). Lives under `doctor`'s `custody.works` (a report view, never
  `issues`/exit code), is the **third non-source-attributable check** (a work spans
  sources, so a `--source` audit fragments works → `status: "skipped"`, beside
  orphan/FTS), rides `maintain` as `at_risk_works` (live-pass only) and `get_library_health`
  for free (the `**custody` spread, pinned convergent with `doctor`). With H263 the
  **consolidation theme (H261–H263) is closed** — work-level custody is *readable,
  scopable, and alarmed* everywhere. **H264 (this run) completed the alarm's
  *readable* side** — a work-level `_At-risk work:_` line on the shareable `export
  bundle` and `scrolls context` briefings, the consolidation counterpart of the
  per-source weakest-source readable `_Attention:_` line (H159): the shared
  `works.render_at_risk_works` distils the *same* `at_risk_signal` fold into one line
  (``_At-risk work: `<doi>` — <reason>; N work(s) at risk._``) the briefings emit
  byte-identically, naming the work `most_at_risk` names and reusing its `reason`
  verbatim (convergence with the JSON alarm by construction). The helper lives in
  `works.py` beside `at_risk_signal` (a `custody.render_at_risk_works` calling it
  would close an import cycle — the home follows the primitive); `scrolls context`
  clusters the **uncollapsed** matched scope (`scope_items`) so a folded full+verified
  sibling correctly marks a work safely held, not the lone kept canonical (ADR 0101).
  So the at-risk-works alarm now reaches *every* surface — JSON read, readable
  briefing — with only the browse predicate (H265, `works --at-risk`) left. **H265
  (this run) closed that browse leg** — `scrolls works --at-risk` + the MCP
  `get_works(at_risk=True)` twin browse the `safely_held == false` set, a genuinely
  new predicate **not** expressible as a single fidelity/drift filter (the negation of
  ∃(full ∧ unmoved), the consolidation analogue of `list --drift`), by extending the
  shared `works.filter_works` with an `at_risk` boolean — the *same* `work_custody`
  fold the aggregate block and `at_risk_signal` read (one rule, three reads), gated
  behind the `not at_risk` early-exit so the unfiltered path reads no ledger. It
  **ANDs** with `--fidelity`/`--drift`, so `--at-risk --fidelity full` surfaces the
  recapture candidates whose content is in hand but whose work is at risk. **H266
  (this run) added the works-stats scope-level at-risk summary** — `stats.custody.at_risk`
  on `scrolls works` (CLI + MCP `get_works`), the `at_risk_signal` fold
  `{total, at_risk, most_at_risk}` over the **reported** works, beside `attention` in the
  same `stats.custody` loss-summary family — so a reader of any `works` payload sees "N
  of the reported works are at risk; worst is `<doi>`" without a second `doctor` call. A
  pure fold over the post-filter works (composes with H262/H265: under `--at-risk`
  `at_risk == total`, under `--fidelity full` the at-risk subset of the kept works) that
  converges field-for-field with `doctor`'s `custody.works` / MCP `get_library_health`
  by construction; **no schema change beyond stats, no extra ledger read.** **With H266
  the consolidation theme is complete across every *point-in-time* axis — work-level
  custody is readable (H261), filterable (H262), alarmed (H263), readable-briefing
  (H264), browsable (H265), and stats-summarized (H266).** **H267 (this run) opened the
  *consolidation-loss-over-time* leg** — the at-risk-works count now rides the
  `maintain` `custody_snapshot`, its cross-run `delta`, and `--history`/`--trend`'s new
  `at_risk_change` axis (and `status`'s `custody.at_risk`, the shared primitive), a
  scalar like recheck `coverage` (H115), reported but never a `posture` trigger (it
  re-views the `fidelity`/`drift` the score/drift already move on). **H268 (this run)
  shipped the *readable line*** — `_At-risk works: N (▲M since last run)_` on the
  `maintain` report and `_At-risk works: N (▲M over K runs)_` on the `--trend` summary,
  the readable counterpart of H267's snapshot scalar (and the trend twin of the at-risk
  `_At-risk work:_` briefing line H264). The shared `maintain.at_risk_headline(count,
  change, *, span)` distils the snapshot's `at_risk` scalar + the delta's signed change
  into one line: `▲` a rise (worse), `▼` a fall (better), `0` the explicit `no change`,
  and a `None` change (first run / scoped non-persisting pass / <2-run trend) the bare
  `_At-risk works: N._` — *exactly* when there is no baseline (the H267 honesty). Unlike
  the snapshot-only `headline` (position-independent), it embeds the delta's change so it
  is **run-position-dependent** — the MCP↔CLI convergence test now strips it beside
  `delta`/`recorded_at` (a documented distinction). **H269 (this run) shipped the last
  leg — the *compiled surface*** — the at-risk-works alarm on the compiled landing
  `library/index.md`, beneath the whole-library `_Custody:_` headline (H96) and grouped
  with the source `_Attention:_` line (the `export bundle`/`context` order), folded by
  the shared `works.render_at_risk_works` over the rendered library and **`index.md`-only**
  (the alarm is non-source-attributable — a scoped group page fragments works, just as
  `doctor`'s `custody.works` skips under `--source`). Inside the `@generated` sentinel
  fence (M1, ADR 0102) so a recompile refreshes it / a recapture clears it while a hand
  annotation survives; honest no-op when no multi-rep work is at risk; converges with
  `doctor`'s `custody.works` over the whole library by construction (the parse-it-back
  tie H97). **With H269 the consolidation theme is closed across *every* surface** — read,
  filter, alarm, browse, stats, trend, briefing, *and* the static compiled library. **H270
  (this run) added the per-work `_Custody:_` marker to the compiled `works.md` rollup** —
  one line per `## <doi>` section (``_Custody: best held <tier>, safest drift <posture> —
  safely held._`` / ``— at risk._``), the works-page analogue of the per-item
  `· <fidelity> · <drift>` list-page marker (H89). The shared `works.render_work_custody_marker`
  distils the H261 `work_custody` dict (`{best_fidelity, safest_drift, safely_held}`) — the
  *same* dict `scrolls works`'s per-work `custody` block carries — so the compiled marker and
  the JSON verdict are two renders of one fold (convergent by construction), and an at-risk
  section's marker agrees with `index.md`'s `_At-risk work:_` line / `doctor`'s `custody.works`.
  Inside the `@generated` fence (M1, ADR 0102) so a recompile refreshes it (a recapture flips
  `at risk`→`safely held`) while a hand annotation survives; threaded by passing the
  shared `verdicts` ledger `compile_kb` already loads into `_write_works_page` — no schema
  change, no extra ledger read. **H271 (this run) shipped the last adjacent consolidation
  read — the `_At-risk work:_` line on the *HTML* `export bundle` form** (`build_bundle_html`),
  the HTML twin of H264's Markdown line, closing the bundle's two-form parity for the
  consolidation alarm. The HTML form rendered the custody headline, the source
  `custody-attention` pointer, `custody-refresh`, and the `custody-by-source` map but **no
  work-level at-risk paragraph** — so the shareable HTML briefing silently dropped the alarm
  the Markdown form carries. H271 adds a red `<p class="custody-at-risk">` (a new CSS rule
  beside `.custody-attention`/`.custody-refresh`), grouped with the source attention line and
  above `_refresh_html` (the Markdown order), distilled from the *same*
  `works.at_risk_signal` over the same lean-scope `works_over` fold — so it names the same
  work the Markdown line / `doctor`'s `custody.works` do (the `_attention_html`↔
  `render_custody_attention` HTML-twin precedent, H39). Honest absence (no paragraph) when no
  multi-rep work in scope is at risk; export-only, never in the lossless JSONL fence. The
  shared `_at_risk_html` helper folds `at_risk_signal(works_over(items), verdicts)` —
  **no schema change, no extra ledger read** (the verdicts the bundle already loads). 4
  tests in `tests/test_bundle.py` (carries-the-line + position, convergence with the Markdown
  form / `at_risk_signal`, honest no-op when no work at risk, omitted for single-rep/empty
  scope). **With H271 the consolidation theme is closed across *every* read, act, and export
  surface, both bundle forms included** — the next un-started slots are the de-prioritized
  budget/tier guard cells (H244–H249) and the H256 buffer-refresh checkpoint.
- **The scheduled-maintenance pass now scopes on the holdings axis too.**
  `scrolls maintain --fidelity <tier>` (H255) is the act twin of `verify
  --fidelity` (H252): the holdings-axis sibling of `maintain --source` (H165), but
  it narrows *less* — only the **recheck** targets the tier (the `verify
  --fidelity` held, hash-bearing subset, same `get_fidelity` primitive), while the
  **audit/regeneration stay whole-library** (a fidelity tier spans sources, so
  `run_doctor`'s source semantics don't apply; scoping the audit is deferred). Like
  `--source` it is a **non-persisting** focused triage (records drift events, never
  the trend baseline → null delta). Closed vocab → exit 2; composes with
  `--all`/`--limit`/`--no-recheck`; conflicts with `--source` (one scope axis per
  pass) and `--history`. CLI-only (the H252 precedent). So both per-item custody
  axes are now scopable on **every** read *and* act surface, including the
  scheduled worker's own pass.

**Per-slice provenance is in git** — every shipped slice's commit subject carries
its `(H<NN>)` tag, so `git log --oneline | grep '(H183)'` resolves any slice to
its full description and diff. This doc points **forward** (maintenance-rule §4:
*git is the changelog*); the compact **Shipped ledger** below is the in-file
index that keeps `H<NN>` cross-references resolvable.

---

## Live work queue (un-started)

Ordered. Take the next slice whose preconditions are met (all listed
preconditions are shipped), finish it to a committed/tested/clean stopping
point, and stop. `→ capN` marks the PRD capability. These are the un-started
**work** slices; the next checkpoint (H256) follows.

**The horizon, re-derived at this H218 checkpoint (2026-06-21), advanced through
H264 (the consolidation theme H261–H263 closed; H264 completed the at-risk alarm's
readable side).** Two themes that ran the last ~50 slices are now *closed*: the
**budget/tier custody honesty** theme (H212–H249's leanest-`index`
`_Fidelity:_` line and its whole cross-tier × CLI/MCP × scoped/unscoped ×
untruncated/truncated convergence matrix) and — now fully — the
**custody-filter family**: the per-item *holdings* and *ledger-claim* axes are
browsable/rankable/actable *and scopable on the relationship surface* across
`list`/`search`/`verify`/`related`, holdings via H250/H251/H252/H254 and ledger
via H54/H253/H80/H254 (see the snapshot bullet). **H254 closed the
last un-filtered *relationship* read surface** — `related --fidelity`/`--drift` +
the MCP `get_related_scrolls` twins — so a neighbourhood can be scoped to "only the
full-fidelity neighbours I can re-derive offline" or "only the ones that have
drifted," sieving the scored hits *before* the cap (the `list`-sieve shape).
**H255 closed the last un-scoped *act* surface** — `maintain
--fidelity` scopes the scheduled pass to one holdings tier (recheck-only against
`verify --fidelity`'s hash-bearing set; audit/regen stay whole-library, null
delta — see the snapshot bullet). H257 closed the *agent context
bundle* — `context --fidelity`/`--drift` + the MCP `get_context_bundle` twin.
H258 closed the family's last *shareable-bundle* surface — the
portable `export bundle --fidelity`/`--drift` — by threading the two axes through
`_gather_scope` into the same `search_items`/`count_matches` sieve, so a
custody-scoped briefing travels and `import bundle` of it re-holds exactly the
exported rows. **H259 closed the *whole-library JSONL backup*** (`export items
--fidelity`/`--drift`), and **H260 closed the family's *last* surface
— the whole-library custody-ledger backup** (`export events
--fidelity`/`--drift`) as an **item-set sieve**: both axes narrow the item
resolution (the same `list_items` sieve H259 folds), then the in-scope items'
*whole* ledger travels, so `--drift drifted` ships a moved item's full custody
history for a recapture handoff (its earlier `unchanged` rows included), not a
per-row match. **With H260 the custody-filter family is closed across every read,
act, and export surface — there is no un-filtered custody surface left.** **H261
then opened the next theme** — work-level custody consolidation: each
`scrolls works` entry now carries an aggregate `custody` block
(`{best_fidelity, safest_drift, safely_held}`, the shared `work_custody` fold), the
work-level "is this work *safely held*?" verdict, no schema change. **H262 (this
run) then lifted the custody-filter family to that surface** — `scrolls works
--fidelity`/`--drift` + the MCP `get_works` twin, over the *contains* semantics
(a work is kept whole iff it has a representation at the custody value; both axes
AND on the same rep), via the shared `works.filter_works` sieve.

**The active theme is the *consolidation* surface — work-level custody (vision §3.5,
"canonical works as custody consolidation — continue here"), now begun.** The
custody-filter family made the per-*item* custody axes (fidelity, drift) scopable
everywhere; the unworked shape was custody at the level of a *work* — the canonical
cluster of many representations (preprint + DOI + PMC, ADR 0095/0096). `works`
already carried each representation's `fidelity`/`drift`/`last_checked` and a
representation-scoped `stats.custody` tally, but a work had **no aggregate custody
posture**. **H261 closed that gap**: each work carries a
`custody` block `{best_fidelity, safest_drift, safely_held}` (the consolidation of
its representations — "is this work *safely held*: does at least one representation
survive at full fidelity, unmoved?"), via the shared `works.work_custody` helper. A
genuinely new custody *shape* (custody-vision §2.7), not a filter replay. **H262
(shipped this run) then lifted the custody-filter family to the consolidation surface**
— `scrolls works --fidelity`/`--drift` + the MCP `get_works` twin — over the
*contains* semantics (a work is kept *whole* iff it has a representation at the custody
value, both axes AND on the *same* rep), folding the per-rep `fidelity`/`drift` `works`
already computes through the shared `works.filter_works` sieve. **H263 (shipped this
run) turned the `safely_held` verdict into an alarm** — the *at-risk-works* signal on
`doctor`'s `custody.works`, `maintain`'s `at_risk_works`, and MCP `get_library_health`
(the `safely_held == false` set, a pure fold over the H261 aggregate via the shared
`works.at_risk_signal`), **closing the consolidation theme (H261–H263)**. **The next
lead is the *readable* completion of the alarm (H264) — a work-level `_Attention:_`
line on the shareable `export bundle`/`scrolls context` briefings**, the consolidation
counterpart of the per-source weakest-source readable `_Attention:_` line
(`render_custody_attention`, H159): H263 put the alarm on the JSON read surfaces, but
the readable briefings an agent skims still carry only the per-*item* source flag.
The **budget/tier convergence cells H244–H249 remain valid regression guards but
explicitly de-prioritized** — the tail of a combinatorial matrix, each self-describing
as *correct-by-construction*; the last runs correctly preferred genuine capability
over taking them. Take H264 first; reach for H244–H249 only when no capability slice
is ready, and prefer closing one rather than appending more of the same shape.

| Slot | Intended slice | Maps to |
| --- | --- | --- |
| H244 | **The custody bundle is reproducible across the round-trip boundary — `export bundle <Q>` from a library rebuilt *from a bundle* is byte-identical to the original `export bundle <Q>`, the bundle-artifact analogue of `test_export_rebuild_is_byte_identical`'s point 2 (export→import→export byte-stability).** H238 (this run) pins the rebuilt *scrolls* + compiled `library/` pages byte-identical across the `export bundle` → `import bundle` boundary; the untested guarantee is that the *bundle artifact itself* re-exports byte-for-byte from the rebuilt library. It is a genuine, distinct claim: the bundle is more than its item block — it carries derived prose (the `custody_headline`, the `_Attention:_`/`_Refresh:_` pointers, the per-source breakdown via `render_custody_by_source`) computed over the rows + ledger, none of it clock-derived (`bundle.py` has no `datetime`/`now()` call). So if the round-trip carries every field those folds read from, re-exporting the *whole* briefing from the rebuilt home reproduces the original byte-for-byte — the M4/cap 9 "self-contained, shareable" briefing is itself reproducible, not just its lossless core. Pin it: over the mixed-fidelity `_mixed_fidelity_scope` (no recorded events → an empty events block on both sides, keeping the slice correct-by-construction), `export bundle "database"` from source A, `import bundle` + `doctor --fix` + `kb` into fresh B, then `export bundle "database"` from B and assert the two bundle texts are byte-identical (and, separately, that the re-exported items block alone is byte-stable — the `dump_items_export`-over-identical-rows guarantee point 2 already covers for `export items`). Implementation path: `build_bundle` folds only row/ledger-derived primitives (`custody_headline`, `custody_counts_by_source`, `_refresh_debt_by_source`) with no clock input, and H238/export-items byte-stability already give row-level byte-identity, so bundle reproducibility is correct-by-construction; the slice pins it on the bundle artifact the scroll/library byte-identity tests never re-export. Test only (`tests/test_bundle.py`, beside the H238 byte-identity test). Precondition: H238 (the bundle scroll/library byte-identity, **shipped this run**), H216 (the mixed-fidelity bundle round-trip). | → cap 9, cap 4 |
| H245 | **The dry-run's `new`/`held` partition *predicts the real import's per-id write effect* — the identity-level closure of H233's count-level "the preview never drifts from reality."** H233 ties the dry-run's `imported`/`skipped` *counts* to a real import's; the untested guarantee is that the dry-run's reviewable *id sets* name exactly the rows the merge actually moves on disk. The counts could match while the preview names the wrong ids — and an operator confirms a merge by reading `new`/`held`, not by reconciling integer counts. Pin it: over a mixed bundle (would-be-new ids, already-held ids, within-bundle dups), capture each parsed id's pre-import held-state (`get_item is None`), dry-run to read `new`/`held`, then real-import the *same* bundle into the same library; assert every id in `new` was absent before and is held after (a genuine absent→present transition the merge caused) and every id in `held` was held before *and* after (no transition) — so the reviewable surface an operator confirms is exactly the set of rows the merge inserts vs. leaves untouched, not merely the right *number* of them. Mutation-checked: pre-holding one of the `new` ids before the dry-run moves it from `new` to `held` *and* removes it from the post-import absent→present transition set, in lockstep — the prediction tracks the library's real state, never a stale snapshot. Implementation path: the dry-run's `new`/`held` come from the same `get_item(...) is None` test the live import's INSERT OR IGNORE (ADR 0082) acts on, so the prediction is correct-by-construction; the slice pins the identity-level closure H233 left at the count level (the reviewable surface describes the *actual* merge, the M2/cap-9 custody-honesty on the predict-the-write axis). Test only (`tests/test_bundle.py`, beside H239/H233). Precondition: H239 (the partition, **shipped this run**), H233 (the count-level reality tie), H226 (the reviewable lists). | → cap 9, cap 7 |
| H246 | **The whole budget ladder stays mutually equal under truncation while *together* diverging from the *library-wide* `doctor` audit — the *unscoped* twin of H240 (and the truncated boundary of H213).** H213 ties the unscoped `index` ≡ `connected` ≡ `full` ≡ `doctor` *only* when one query matches the whole library (no truncation); H240 (shipped this run) pins the *scoped* ladder under a cap diverging from `doctor --source <S>`. The untested cell is the *unscoped* ladder under a cap: the no-facet path, where the library-wide audit and the kept-`k` bundle must genuinely differ. Over `_seed_mixed_custody` (four scrolls: full 2, partial 1, reference 1, no source filter), `context --budget {index,connected,full} --limit k` with `k` below the held count renders three fidelity sections all *equal to each other* (the kept-`k` slice) and all `≠` the library-wide `doctor`'s `custody.tiers` (summing to the whole held count `> k`); lifting the cap (`--limit` ≥ held) reconverges all four to the H213 unscoped equality. So the no-facet budget ladder never disagrees *with itself* under a cap, and neither the leanest nor the deeper tiers inflate the bundle-kept holdings to a library-wide claim — H240's cohesion guarantee on the unscoped (no-`--source`) read path. Test only (`tests/test_custody_convergence.py`, beside H240/H213). Implementation path: all three tiers fold `get_fidelity` over the same post-cap `items` (`index` via `render_fidelity_holdings`, `connected`/`full` via `custody_headline`) while unscoped `doctor` folds over every held row, so the cohesion-under-truncation is correct-by-construction; the slice pins the unscoped boundary H213 (untruncated) and H240 (scoped) leave between them. Precondition: H240 (the scoped ladder-under-truncation, **shipped this run**), H213 (the unscoped four-way tie). | → cap 1, cap 2, cap 10 |
| H247 | **The whole budget ladder is mutually equal *and* equal to `get_library_health()`'s `tiers`, all read over MCP and untruncated — the direct MCP twin of H213 (and the unscoped sibling of H241).** H241 (this run) pins `index` ≡ `connected` ≡ `full` over MCP *under scope*; H214 pins only the *leanest* `index` `_Fidelity:_` line ≡ the CLI over MCP, never the cross-*tier* tie over MCP. The untested cell is the *unscoped* (no-`source`) MCP cross-tier tie: over a library-wide query matching every held item (no facet, no truncation), `get_context_bundle(query, budget={index,connected,full})`'s fidelity counts must all be equal to each other *and* equal to `get_library_health()`'s `tiers` — the leanest `_Fidelity:_` line (`render_fidelity_holdings`) and the deeper `_Custody:_` headlines' `fidelity` section (`render_custody_headline`, a **different** function) and the whole-library MCP audit (the MCP twin of `doctor`) are four reads of one ledger-free fact (`get_fidelity` per item) over the one library-wide scope. Pin it: over `_seed_mixed_custody`-style holdings (full 2, partial 1, reference 1) with every title sharing a query token (so one unscoped query matches all 4 held < the default limit → no truncation), all three MCP budget tiers' fidelity counts equal each other and equal `get_library_health()`'s `tiers` (the `index` line still withholds the drift verdict the deeper tiers carry — the H214/H219 honesty stays intact). Mutation-checked: dropping a `full` item's body shifts the tier on all three MCP tiers *and* the MCP audit in lockstep. Test only (`tests/test_mcp.py`, beside the H241/H235/H214 twins). Implementation path: all three tiers fold `get_fidelity` over the same `items` in `build_context` and `get_library_health()` is the MCP twin of `doctor` folding over every held row, so the four-way unscoped tie is correct-by-construction; the slice pins the direct MCP twin of H213's CLI cross-tier convergence (the unscoped sibling of H241). Precondition: H241 (the scoped MCP cross-tier tie, **shipped this run**), H214 (the unscoped MCP leanest line ≡ CLI), H213 (the CLI cross-tier tie). | → cap 1, cap 2, cap 10 |
| H248 | **The whole *unscoped* MCP budget ladder stays mutually equal under truncation while *together* diverging from the *library-wide* `get_library_health()` `tiers` — the *MCP twin of H246* (and the truncated boundary of H247), filling the last open cell of the cross-tier × untruncated/truncated × CLI/MCP × scoped/unscoped fidelity-convergence matrix.** H247 ties the *unscoped* `index` ≡ `connected` ≡ `full` ≡ `get_library_health()` over MCP *untruncated*; H242 (shipped this run) pins the *scoped* MCP ladder under a cap diverging from `get_library_health(source=<S>)`. The untested cell is the *unscoped* MCP ladder under a cap: the no-`source` path, where the library-wide MCP audit and the kept-`k` bundle must genuinely differ. The `connected`/`full` `_Custody:_` headline's `fidelity` section is rendered by `render_custody_headline` (a **different** function than the `index` line's `render_fidelity_holdings`), yet all three fold over the *same* post-cap kept set — so under truncation the three MCP budget tiers must stay mutually equal (all bundle-kept, summing to `k`) *even as all three collectively diverge* from the whole-library MCP audit (summing to the held count `> k`). Pin it: over a library-wide mixed-fidelity holdings (full 2, partial 1, reference 1) where one unscoped query matches every held item, `get_context_bundle(query, budget={index,connected,full}, limit=k)` with `k` below the held count renders three fidelity sections all equal to each other and all `≠ get_library_health()`'s `tiers`; lifting the cap (`limit` ≥ held) reconverges all three to the H247 unscoped MCP equality. So the no-`source` MCP budget ladder never disagrees *with itself* on holdings under a cap, and neither the leanest nor the deeper tiers inflate the bundle-kept holdings to a library-wide claim — H242's cohesion guarantee on the unscoped MCP read path. Test only (`tests/test_mcp.py`, beside the H242/H247/H214 twins). Implementation path: all three tiers fold `get_fidelity` over the same post-cap `items` in `build_context` while `get_library_health()` (no `source`) is the MCP twin of `doctor` folding over every held row, so the cohesion-under-truncation is correct-by-construction; the slice pins the unscoped MCP boundary H247 (untruncated) and H242 (scoped) leave between them. Precondition: H242 (the scoped MCP ladder-under-truncation, **shipped this run**), H247 (the unscoped MCP four-way tie), H246 (the unscoped CLI ladder-under-truncation). | → cap 1, cap 2, cap 10 |
| H249 | **The dry-run's `new`/`held`/`orphaned_items` form a clean *three-way* id-space partition even over a bundle corrupt on *both* axes — the both-axes closure of H239 (which proved the two-way `new`/`held` partition over an items-*only* corrupt bundle).** H239 pins `set(new) ∪ set(held)` = the bundle's distinct item ids and `set(new) ∩ set(held) == ∅`, but only over an items-only corrupt bundle (empty events); the untested cell is whether that reviewable partition stays clean when the *events* block is *also* corrupt (orphan events present), and whether the orphan-item id-space stays disjoint from the item partition. It is a genuine guarantee: `new`/`held` are folded from the items block (`imported_items`) while `orphaned_items` is folded from the events block's unresolved ids (`_orphan_item_ids`), two independent reads of the one parsed bundle, so a naive impl could let an orphan item leak into `new`/`held` (double-classifying an id the merge never writes) or an items-block id vanish from review. Pin it: over the H243 `_spliced_items_and_events_bundle` (a within-bundle item-dup items block *plus* anchored-and-orphan events), dry-run and assert (a) `sorted(new + held)` equals the distinct items-block ids computed independently via `parse_bundle`, (b) `set(new).isdisjoint(held)`, and (c) `set(orphaned_items).isdisjoint(set(new) | set(held))` — three non-overlapping id-spaces, so an operator reviewing the preview never sees one id classified two ways across the item and orphan axes. Mutation-checked: adding a distinct orphan event for a new missing item extends `orphaned_items` by exactly that id and leaves `new`/`held` untouched (the orphan axis never perturbs the item partition). Implementation path: `orphan` item ids are exactly those neither held nor in `known_ids` (`partition_resolvable_events`), so they are disjoint from the items-block ids by construction; the slice pins the cross-axis disjointness H239 (items-only) and H243 (counts, not the id partition) leave open. Test only (`tests/test_bundle.py`, beside H243/H239). Precondition: H243 (the both-axes whole-summary tie + `_spliced_items_and_events_bundle`, **shipped this run**), H239 (the two-way items-only partition). | → cap 9, cap 7 |
| H256 | **Buffer refresh checkpoint** (maintenance rule; next full refresh due ~2026-06-22). Mark shipped slices into the ledger, prune overtaken slices, keep ≥6 un-started work slots, and re-derive the 3-day/week plans with absolute dates. Re-confirm the week plan still maps to `docs/product/mvp.md`. Bi-temporal drift framing stays deferred unless an agent workflow shows the event record insufficient. | maintenance |

The next lead slot is **H256** — the buffer-refresh checkpoint (maintenance rule, due
~2026-06-22): with H271 shipped the **consolidation theme is closed across *every*
surface, both bundle forms included**, so the queue holds only de-prioritized guard
cells and no live capability lead. The next run should take H256 to re-derive the next
capability theme from `docs/product/mvp.md` / `docs/product/prd.md` before reaching for a
guard cell. **With H271 the consolidation theme is closed** — work-level custody is
readable (H261), filterable (H262), alarmed (H263 JSON), readable-briefing on both bundle
forms (H264 Markdown + **H271 HTML**), browsable (H265), stats-summarized (H266),
trend-over-time (H267), readable-trend (H268), on the static compiled `index.md` (H269),
*and* per-work on the compiled `works.md` rollup (H270). The **budget/tier convergence
cells H244–H249** sit below as **de-prioritized but valid regression guards** — each a
correct-by-construction cell of the cross-tier × CLI/MCP × scoped/unscoped ×
untruncated/truncated fidelity matrix (H244 bundle-artifact reproducibility, H245 dry-run
per-id write prediction, H246 unscoped CLI ladder-under-truncation, H247 unscoped MCP
four-way tie, H248 unscoped MCP ladder-under-truncation, H249 both-axes three-way id
partition). Take H256 (re-derive the next theme) first; reach for a guard cell only when no
capability is ready. Per-slice provenance
for every *shipped* slot lives in git (`git log --oneline | grep '(H<NN>)'`); the **Shipped
ledger** below is the one-line in-file index (maintenance-rule §4: *git is the changelog*).

**This run (2026-06-22) shipped H271** — the readable work-level `_At-risk work:_` line now
rides the **HTML `export bundle` form** (`build_bundle_html`), the HTML twin of H264's
Markdown line and the **last adjacent consolidation read**. H264 added the line to the
Markdown bundle (`build_bundle`) but left the HTML form without it: the HTML briefing
rendered the custody headline, the source `custody-attention` pointer, `custody-refresh`,
and the `custody-by-source` map — but **no work-level at-risk paragraph**, so the shareable
HTML briefing an operator reads in a browser silently dropped the consolidation alarm the
Markdown form carries. H271 adds a red `<p class="custody-at-risk">` (a new CSS rule beside
`.custody-attention`/`.custody-refresh` — both loss alarms share the `#b3261e` red; amber
`custody-refresh` stays reserved for recoverable staleness) beneath the headline, **grouped
with the source `_attention_html` line and above `_refresh_html`** (the Markdown
attention→at-risk→refresh→by-source order). The **decisive design choice** is the shared
fold: the new `_at_risk_html` helper distils `at_risk_signal(works_over(items), verdicts)` —
the *same* lean-scope fold (`works_over` over the gathered item set) the Markdown
`render_at_risk_works` reads — so the HTML `<p>` names the same work, reason, and `at_risk`
count as the Markdown line / `doctor`'s `custody.works` / `maintain`'s `at_risk_works` / MCP
`get_library_health` **by construction** (the `_attention_html`↔`render_custody_attention`
HTML-twin precedent, H39). Honest absence (no paragraph) exactly when `most_at_risk` is
`None` — no multi-representation work in scope is at risk (clean, single-rep, or empty
scope), the `_attention_html` no-op shape. The doi/reason are HTML-escaped for safety (the
`_attention_html` precedent), and the line is **export-only** — a derived read view in the
`<body>`, never inside the lossless `@generated` JSONL fence, so the Markdown round-trip is
untouched. **No schema change, no extra ledger read** — it folds the `verdicts` the bundle's
`_gather_scope` already loads. 4 tests in `tests/test_bundle.py` (carries-the-line + position
above the `custody-by-source` list; convergence with the Markdown form via `at_risk_signal`;
honest no-op when no work at risk; omitted for single-rep + empty scope). Docs: the `docs/cli.md`
H264 paragraph extended with the HTML twin (`custody-at-risk` paragraph, H39 precedent).
End-to-end verified on a real four-item library (two at-risk reference-only reps + a
safely-held full+reference work): the HTML line renders inside the body in position and
converges byte-for-byte (modulo HTML escaping) with the Markdown twin. Full suite green
(3530 passed). **H271 closes the consolidation theme across *every* read, act, and export
surface — both bundle forms now carry the at-risk alarm. The queue holds only the
de-prioritized budget/tier guard cells (H244–H249) and the H256 buffer-refresh checkpoint;
the next run should take H256 to re-derive the next capability theme.**

**The previous run (2026-06-22) shipped H270** — the compiled `works.md` rollup now carries a
**per-work `_Custody:_` marker** beneath each `## <doi>` section's resolver line, the
works-page analogue of the per-item `· <fidelity> · <drift>` list-page marker (H89) and
the **last un-marked compiled surface for work-level custody**. `works.md` rendered each
work's resolver link, representation count, and per-rep bullets, but carried **no
work-level custody verdict** — a human browsing the rollup couldn't see which works are
safely held vs. at risk without opening `scrolls works` JSON. H270 emits one line per
section — ``_Custody: best held <tier>, safest drift <posture> — safely held._`` (or
``— at risk._`` when no representation is both `full` and unmoved) — folded by the new
shared `works.render_work_custody_marker` over the H261 `work_custody` dict
(`{best_fidelity, safest_drift, safely_held}`). The **decisive design choice**: the
renderer takes the `work_custody` *dict* (not the representations), so the compiled marker
and `scrolls works`'s per-work `custody` block are two renders of the **same fold** —
convergent by construction, the parse-it-back tie the compiled custody headlines already
hold (H97) lifted to the work level. Threaded by passing the `verdicts` ledger
`compile_kb` already loads into `_write_works_page` (the H269 precedent) — **no schema
change, no extra ledger read**. Inside the page's `@generated` sentinel fence (M1,
ADR 0102), so a recompile refreshes it (a recapture flips a section `at risk`→`safely
held`) while a hand annotation outside the fence survives. 3 tests: 2 in `tests/test_kb.py`
(the marker renders on at-risk + safely-held sections in the right position; refresh-safe
recapture flip with an outside-fence annotation preserved), 1 in
`tests/test_custody_convergence.py` (each work's compiled marker is byte-identical to
`render_work_custody_marker(scrolls works['custody'])` in its own section, the at-risk
section agrees with `doctor`'s `custody.works.most_at_risk`, mutation-in-lockstep recapture
flips both the JSON verdict and the compiled marker). Updated the pre-existing
`test_kb_graph_and_works_pages_omit_the_scope_custody_headline` (the per-work marker is a
different `_Custody:` line than the scope headline — it carries no `scroll(s)`) and the
`docs/library-format.md` `example-works-page` pinned block (now shows the `— at risk._`
marker the bare-reference fixtures produce). Docs: `docs/cli.md` `works.md` paragraph,
`docs/library-format.md` works-page section. End-to-end verified on a real two-work library
(a full+reference work reads `— safely held._`, a two-reference work reads `— at risk._`).
Full suite green (3526 passed). **H270 closes the consolidation theme across read/filter/
alarm/browse/stats/trend/briefing/compiled-index *and* the compiled works rollup; the last
adjacent read is H271 (the at-risk line on the HTML `export bundle` form).**

**This run (2026-06-22) shipped H269** — the consolidation at-risk-works alarm now rides
the **compiled landing `library/index.md`**, the *static compiled* surface, **closing
the consolidation theme across every surface**. The per-source weakest-source picture
rode the compiled pages (H184), but the consolidation alarm — "N works at risk" —
appeared only on the agent JSON/briefing surfaces, never the human-browsable compiled
library. H269 threads an optional `at_risk_lines` through the shared
`kb._custody_scope_block`, spliced beneath the whole-library `_Custody:_` headline (H96)
and **grouped with the source `_Attention:_` line** (above `_Refresh:_`/`_By source:_` —
the `export bundle`/`context` order), folded by the shared `works.render_at_risk_works`
over the rendered library so the line names the same work `doctor`'s `custody.works` /
the `index.md` JSON does. The **decisive design choice**: `index.md`-**only**, not every
compiled group page (unlike the per-source `_Attention:_`/`_Refresh:_` lines that ride
every multi-source group page) — the consolidation alarm is **non-source-attributable**:
a work spans sources, so a scoped group page fragments its representations into single-rep
clusters (dropped by the `min_representations` floor) and could not converge with the
library-wide audit, *exactly* why `doctor`'s `custody.works` is skipped under `--source`
(the H263 third-non-source-attributable-check discipline). The line sits **inside** the
page's `@generated` sentinel fence (M1, ADR 0102) — a recompile refreshes it (a recapture
clears it), while a hand annotation outside the fence survives — and is the honest no-op
(no line) when no multi-rep work is at risk. It converges with `doctor`'s `custody.works`
over the whole rendered library by construction (the parse-it-back tie the compiled
custody headlines already hold, H97). Threading via the *optional* `at_risk_lines` kwarg
(default `[]`, passed only by `_write_index`) keeps the shared block untouched for group
pages, so the source attention/refresh/by-source lines are byte-identical as before. 7
tests: 6 in `tests/test_kb.py` (carries-the-line + position, `render_at_risk_works`
byte-identity, the full grouping order `_Custody:` < `_Attention:` < `_At-risk work:` <
`_Refresh:` < `_By source:_`, honest no-op, group-pages-omit, refresh-safe-with-recapture-
clears), 1 in `tests/test_custody_convergence.py` (doctor `custody.works` parse-it-back +
mutation-in-lockstep recapture). Docs: `docs/cli.md` compiled-index at-risk paragraph.
End-to-end verified on a real library (line renders inside the fence → recapture clears
it → converges field-for-field with `doctor`). Full suite green (3523 passed). **H269
closes the consolidation theme across read/filter/alarm/browse/stats/trend/briefing *and*
compiled surface; the next leads are the adjacent consolidation reads H270 (per-work
custody marker on compiled `works.md`) and H271 (the at-risk line on the HTML bundle
form).**

**The previous run (2026-06-22) shipped H268** — the at-risk-works count is now **readable** on
the `maintain` report (`_At-risk works: N (▲M since last run)._`) and the `--trend`
summary (`_At-risk works: N (▲M over K runs)._`), the readable counterpart of H267's
snapshot scalar and the trend twin of the at-risk `_At-risk work:_` briefing line (H264).
H267 recorded the count in the snapshot/delta/trend as JSON; H268 distils it to the one
line a human skimming the maintenance output reads without parsing the `delta` JSON — the
at-risk analogue of the `snapshot_headline` `_Custody:_` line (H103/H142) and the
per-source readable `_Attention:_` line (H159). The new shared `maintain.at_risk_headline(
count, change, *, span="since last run")` is a pure formatter over two scalars the report
and trend already carry: `▲M` a **rise** (more works lost their last safe copy — worse),
`▼M` a **fall** (a recapture restored one — better), `0` the explicit `no change`, and a
`change` of `None` the bare `_At-risk works: N._` — degrade-safe *exactly* when there is
no baseline (a first run, a scoped non-persisting `--source`/`--fidelity` pass whose
`delta` is null, or a `<2`-run trend with no trajectory; the H267 first-run/missing-axis
honesty, ADR 0082). The report reads `current["at_risk"]` + `delta["at_risk"]["change"]`
(span "since last run"); the trend reads the window's last snapshot + `at_risk_change`
(span "over K runs", the score-`first→last` shape). The **decisive design consequence**:
unlike the snapshot-only `headline` (position-independent — purely the current snapshot),
`at_risk_headline` embeds the *delta's signed change*, so it is **run-position-dependent**
— a first run reads the bare line, a later run the `(no change …)` clause. The MCP↔CLI
`run_maintenance` convergence test therefore strips `at_risk_headline` beside
`delta`/`recorded_at` in `_audit_fields` (a documented distinction: the snapshot headline
converges field-for-field across run positions, the delta-bearing at-risk line does not).
Rides MCP for free (the `assemble_report`/`compute_trend` composition `run_maintenance`/
`get_maintenance_history` reuse, pinned by the existing full-envelope CLI↔MCP equality
`test_get_maintenance_history_matches_cli_maintain_history`). 14 tests in
`tests/test_maintain.py` (5 unit `at_risk_headline` rise/fall/no-change/bare/span; 3
report integration: first-run bare + convergence with the JSON alarm/snapshot, the ▲ rise
across two persisting passes, the bare line under a `--source`/`--fidelity` scope; 4
trend integration: the readable window line, the ▼ fall, the no-change steady, the bare
`<2`-run/empty), plus the `_audit_fields` strip and two MCP report-shape assertions
updated. Docs: `docs/cli.md` report `at_risk_headline` paragraph, the `--trend`
`at_risk_headline` paragraph, the four maintain console examples, and the MCP
`run_maintenance` shape list. End-to-end verified on a real library (bare → ▲1 on a
drift → ▼1 on a recapture). Full suite green (3516 passed). **H268 gives the
consolidation-loss trend a readable line; the last leg is H269 (the at-risk alarm on the
compiled `library/index.md`).**

**This run (2026-06-22) shipped H267** — the at-risk-works count now rides the
`maintain` custody snapshot, its cross-run `delta`, and `--history`/`--trend`: the
**consolidation-loss-over-time** axis, the at-risk counterpart of recording recheck
`coverage` in the snapshot (H115). The consolidation theme (H261–H266) put the
at-risk-works alarm on every *point-in-time* surface (JSON read, readable briefing,
works stats), but the **trend** didn't track it — `custody_snapshot` recorded
`score`/`tiers`/`drift`/`coverage`/`enrichment_stale`/`summaries_stale`, never the
at-risk count, so an operator couldn't see whether consolidation health was improving
or degrading. H267 adds an `at_risk` scalar to `custody_snapshot` (read from the
doctor report's `custody.works.at_risk`, degrade-safe `0` for an absent `works` block
or a `status: skipped` `--source` pass), folds it into the cross-run `delta` with the
same first-run/missing-axis tolerance the other scalars carry, and adds the
`at_risk_change` net-delta axis to `compute_trend`. So an operator reading `--trend`
sees "2 → 4 works at risk" without re-auditing each run. The **decisive design
choices**, both resolved as the spec leaned: (1) **store the scalar `at_risk` count**,
not the whole `{total, at_risk, most_at_risk}` block — the snapshot is a
comparable-scalars record, and `most_at_risk`'s named work is not a quantity a delta
can difference (the live `at_risk_works` block already carries it, live-pass only);
(2) **`at_risk_change` is a reported axis, never a `posture` trigger** (the
`coverage_change`/`stale_change` precedent) — it re-views the very `fidelity`/`drift`
the `score` and `drift_change` already move the posture on (a work is at risk because
its reps degraded or drifted), so folding it into `posture` would **double-count** the
same integrity loss. A second consequence falls out of the shared primitive:
`custody_snapshot` is also `scrolls status`'s `custody` block, so `status` gains
`custody.at_risk` for free — the documented "status can never disagree with a
maintenance snapshot" convergence (H38/H103). Only the **fully-unscoped** persisting
pass records the snapshot, so a recorded `at_risk` is always the whole-library count
(a `--source`/`--fidelity` triage is non-persisting, null delta — H165/H255). The
H143 trend≡telescoped-deltas invariant gained the `at_risk` axis (the four-run
non-monotone window now moves at-risk up/down/up, telescoping +3). 14 tests: 11 in
`tests/test_maintain.py` (snapshot records the count + degrades to 0; delta against a
baseline / first-run null / pre-H267-baseline-zero; trend movement / posture-
independence / clears / pre-H267-endpoint-zero; `<2`-run null; the recorded-snapshot
== live-block convergence; `--history` carries the scalar + cross-run delta), 3 in
`tests/test_custody_convergence.py` (the telescoping invariant extended to the at-risk
axis on all three of its forms). Docs: `docs/cli.md` trend-layer paragraph, the
`custody.works`/`status` field rows, and every `status`/`maintain`/`--trend` example
JSON. Full suite green (3504 passed). **H267 opens the consolidation theme's
trend-over-time leg; the next lead is H268 (the readable `_At-risk works: N (▲M)_`
line on the `maintain` report and `--trend` summary).**

**This run (2026-06-22) shipped H266** — the `scrolls works` *stats* carry a
scope-level at-risk-works summary at `stats.custody.at_risk`, the works-surface
counterpart of the `doctor`/`maintain`/`get_library_health` at-risk-works alarm
(H263) and the **closing slice of the consolidation theme's point-in-time axes**. So
a reader of any `works` payload (CLI or MCP) sees "N of the reported works are at
risk; worst is `<doi>`" without a second `doctor` call. The decisive design choice —
resolved as the spec leaned — was the **home**: `stats.custody.at_risk` beside
`attention` (the same `stats.custody` loss-summary family — `attention` is itself a
scope-level custody-loss summary, a source flag rather than a rep tally), not a
top-level `stats.at_risk`. The field is the **whole** `at_risk_signal` fold
`{total, at_risk, most_at_risk}` (not just the count), so it is field-identical to
`doctor`'s `custody.works` (minus its `status`) and converges with it / MCP
`get_library_health` **by construction** over the unscoped default 2+ clustering — a
cross-surface invariant pinned on both CLI (`works`↔`doctor`) and MCP
(`get_works`↔`get_library_health`). A **pure fold over the reported (post-filter)
works**, so it composes with the H262/H265 filters: under `--at-risk` `at_risk ==
total`, and under `--fidelity full` it counts the at-risk subset of the kept works
(both pinned). `at_risk.total` equals `stats.works` beside it by construction (a
coherence invariant), and the empty scope is the honest zeroed fold `{total: 0,
at_risk: 0, most_at_risk: null}`. **No schema change beyond stats, no extra ledger
read** — reuses the `verdicts` the per-rep `drift` already folds, riding MCP
`get_works` for free (shared `to_payload`). The two existing `stats.custody`
convergence tests (the CLI works-stats-matches-reps and its MCP twin) and the
`test_works_stats_custody_agrees_with_its_representations` invariant gained the
works-only `at_risk` member (the shared `_tally_rows` per-rep fold, used by the
list/search/related/graph surfaces that have *no* `at_risk` member, was left
untouched). 10 tests: 7 in `tests/test_works.py` (summary == `at_risk_signal`,
`total == stats.works`, zeroed-when-empty, empty-when-all-safe, composes-with-`--at-risk`,
composes-with-`--fidelity`, CLI↔doctor convergence), 2 in `tests/test_mcp.py`
(rides-the-twin, MCP↔`get_library_health` convergence). Docs: `docs/cli.md`
`stats.custody.at_risk` paragraph + MCP table row. Full suite green (3493 passed).
**H266 closes the consolidation theme's point-in-time axes; the next lead is H267 (the
at-risk-works count in the `maintain` snapshot/trend — consolidation loss over time).**

**This run (2026-06-21) shipped H265** — `scrolls works --at-risk` + the MCP `get_works(at_risk=True)` twin, **closing the consolidation theme's browse leg** (the theme's fifth and final axis). A work is browsed as *at risk* when **no** representation safely holds it — the H261 `work_custody` `safely_held == False` set the H263 alarm counts (no copy is both `full` *and* unmoved anywhere in its cluster). It is a genuinely new browse predicate, **not** a `--fidelity`/`--drift` value: "no rep is safely held" is the **negation of ∃(full ∧ unmoved)**, so it cannot be expressed as a single per-rep custody filter — the consolidation analogue of `scrolls list --drift`. The slice **extends the shared `works.filter_works`** with an `at_risk: bool` parameter rather than adding a parallel sieve, so the predicate composes naturally: it **ANDs** with the per-rep `--fidelity`/`--drift` contains-filters via one combined comprehension, and `--at-risk --fidelity full` surfaces the **recapture candidates** whose content is in hand (a full rep exists) but whose work is at risk (that full copy drifted) — the sharpest "act on this" set. The decisive choices: (1) **extend `filter_works`, don't fork it** — the at-risk predicate is `not work_custody(reps, verdicts)["safely_held"]`, the same fold the aggregate `custody` block (H261) and `at_risk_signal` (H263) read, so a work is browsed by exactly the verdict it shows (one rule, three reads); (2) **gate behind the `not at_risk` early-exit** so the unfiltered path (`fidelity is None and drift is None and not at_risk`) returns the input list unchanged and reads no ledger — the H262 identity preserved, and `work_custody` is never computed when `--at-risk` is off; (3) **boolean → `or None` scope echo** — unlike the vocabulary filters (pruned when `None`), a `False` boolean would survive `to_payload`'s `None`-pruning, so `_cmd_works`/`get_works` pass `at_risk or None` into the scope dict, present only when set (G2). `stats.custody` partitions the kept set unchanged (the H262 before-the-cut sieve shape); composes with the per-item `ref` lens (`works <id> --at-risk` answers "is the work this item represents at risk?"). 12 tests: 5 unit `filter_works(at_risk=)` in `tests/test_works.py` (keeps-the-unsafely-held set, `at_risk_signal`-set parity, whole-work-travels, ANDs-with-the-per-rep-filters, `at_risk=False`-is-identity), 4 CLI (`tests/test_works.py` — browse, scope-omits-flag-when-unset, ANDs-with-custody-filters, composes-with-ref-lens), 3 MCP (`tests/test_mcp.py` — browse incl. scope echo, ANDs, CLI↔MCP parity). Docs: `docs/cli.md` `--at-risk` paragraph + heading + MCP table row. Full suite green (3484 passed). **H265 closes the consolidation browse leg; work-level custody is now readable/filterable/alarmed/readable-briefing/browsable. The next lead is H266 (the works-stats scope-level at-risk summary, the works-surface twin of the `doctor`/`maintain`/`get_library_health` alarm).**

**This run (2026-06-21) shipped H264** — the readable work-level `_At-risk work:_` line on the shareable `export bundle` and the `scrolls context` briefings, the *consolidation*-level counterpart of the per-source weakest-source readable `_Attention:_` line (`custody.render_custody_attention`, H159). H263 put the at-risk-works alarm on every JSON read surface (`doctor`'s `custody.works`, `maintain`'s `at_risk_works`, MCP `get_library_health`); H264 distils the *same* `works.at_risk_signal` fold into a readable line the briefings emit byte-identically: ``_At-risk work: `<doi>` — no representation is both full and unmoved (best held <tier>, safest drift <posture>); N work(s) at risk._``, naming the work `most_at_risk` names and reusing its `reason` verbatim, so the readable line and the JSON alarm converge by construction. The new shared `works.render_at_risk_works(items, verdicts)` clusters the briefing scope's items (`works_over`) and folds `at_risk_signal`, returning `[line, ""]` or `[]` on honest absence (no multi-rep work at risk — clean/single-rep/empty scope, exactly when `most_at_risk` is `null`); the trailing `N work(s) at risk` is the `at_risk` count. The decisive design choices: (1) the helper **lives in `works.py`** beside `at_risk_signal`, not in `custody.py` with `render_custody_attention` — `works` imports `custody`, so a `custody.render_at_risk_works` calling `at_risk_signal` would close an import cycle (the home follows the primitive); (2) **lean scope** — the line describes the works the briefing's matched set touches, and for `scrolls context` (whose `items` are collapsed to one canonical per work, ADR 0101) it clusters the **uncollapsed** matched scope (`scope_items`, kept + folded) so a work's full custody picture — including a folded full+verified sibling that makes it safely held — is judged correctly, not from the lone kept canonical; (3) placed **directly beneath the source `_Attention:_` line**, grouping the two custody-loss pointers above the `_Refresh:_`/`_By source:_` map; gated to `connected`+ on `context` like the headline, always present on the bundle. 16 tests: 4 unit (`render_at_risk_works` — names lowest-ceiling work, converges with `at_risk_signal`, empty-when-safe, empty-for-single-rep) in `tests/test_works.py`, 6 `tests/test_bundle.py` (line/position, convergence, no-op-when-safe, single-rep-no-op, empty-scope, round-trip), 6 `tests/test_context.py` (line/position, convergence, index-gated-off, present-from-connected, no-op-when-safe, MCP parity). Docs: `docs/cli.md` `_At-risk work:_` paragraph beside the `_Attention:_`/`_Refresh:_` lines. Full suite green (3472 passed). **H264 completes the readable side of the consolidation alarm; the next lead is H265 (`scrolls works --at-risk` — browse the `safely_held == false` set, a new predicate not expressible as a single fidelity/drift filter).**

**The previous run (2026-06-21) shipped H263** — the *at-risk-works* consolidation alarm, **closing the consolidation theme (H261–H263)**. A work is **at risk** when **no** representation is *safely held* (the H261 `work_custody` `safely_held == False` set — every copy degraded (`partial`/`reference`) or moved (`drifted`/`rotted`/`error`), no unmoved full form anywhere in its cluster); it is the consolidation-level analogue of the per-source weakest-source `attention` flag and a sharper alarm than the per-item drift count (an item drifting is survivable if a sibling rep of the same work is still full+verified; a *work* with no safe rep is a real custody loss). The shared `works.at_risk_signal(works, verdicts)` is a **pure fold over the H261 aggregate** (`work_custody` over each work's reps, **no schema change, no extra ledger read**), returning `{total, at_risk, most_at_risk}` — `most_at_risk` the single **lowest-custody-ceiling** work (worst `best_fidelity` first — a `reference`-best work, content never captured, over a `full`-but-`drifted` one whose content is merely moved; then worst `safest_drift`; then `doi`), carrying the work's `doi`/`url`/`canonical`, `representations` count, the H261 `custody` verdict, and a self-describing `reason` but **no fabricated `command`** (no whole-library recapture act exists — the `suggested`-block orphan discipline). Surfaced on three JSON read surfaces: `doctor`'s `custody.works` (a report view, never `issues`/exit code; the **third non-source-attributable check** — a work spans sources, so a `--source` audit fragments works → `status: "skipped"`, beside orphan/FTS), `maintain`'s `at_risk_works` (live-pass only, like `attention`/`by_source`), and MCP `get_library_health` for free (the `**custody` spread, pinned convergent with `doctor`). The decisive design choices: (1) **skip-under-scope** (not compute-whole-library-under-scope), matching orphan/FTS and avoiding a G1 "0 at risk" honesty trap; (2) **min_representations=2** (the consolidation question only applies to a work with siblings — single-rep degradation is already the per-item signal); (3) **no command** (don't name a path that won't close the gap). 18 tests: 6 unit (`at_risk_signal` — count, lowest-ceiling pick, fidelity-then-drift-then-doi ordering, empty-when-safe, unverified-full-is-safe, matches-`work_custody`) in `tests/test_works.py`, 7 `tests/test_doctor.py` (flags/names/never-feeds-issues/ok-empty/empty-lib/uninit-skipped/source-skipped), 4 `tests/test_maintain.py` (reports/empty/source-skipped-fidelity-computed/history-bare), 1 `tests/test_mcp.py` (`get_library_health` carries it). Docs: `docs/cli.md` doctor + maintain + MCP-table paragraphs. Full suite green (3456 passed). **H263 closes the consolidation theme; the next lead is H264 (the readable work-level at-risk `_Attention:_` line on the briefings).**

**The previous run (2026-06-21) shipped H262** — `scrolls works --fidelity <tier>` / `--drift <posture>` + the MCP `get_works(fidelity=, drift=)` twin, the custody-filter family lifted to the **consolidation** surface (the work cluster the family reached every per-item read/act/export surface but never, H250–H260). The decisive design choice the slice resolved was the lift semantics, settled as the **contains** read: a work is kept *whole* (every representation still travels) iff it **has a representation** at the custody value, since a work is a set of forms and "show me the works with a drifted representation" wants the *work and its siblings* (so a reader can see whether a safe sibling exists), not the lone matching form — so `--drift drifted` surfaces *the works needing a recapture decision* with their representation set intact. The two axes AND **on the same representation** (the ∃-lift of the per-item `filter_related` predicate, "no neighbour is *both*", H254): `--fidelity full --drift drifted` keeps a work iff some rep is *both* full and drifted (a fully-held copy whose source moved — the recapture candidate where the content is in hand), not merely some full rep and some — possibly different — drifted rep (the rejected "Option A", pinned by a test that `--fidelity reference --drift drifted` is **empty** over a work that contains a reference rep *and* a drifted rep but in different forms). The new shared `works.filter_works(works, verdicts, *, fidelity, drift)` sieve folds the same per-rep `fidelity`/`drift` `works` already computes — pure over the already-clustered works (the `filter_related` shape: cluster via `works_over`/`works_for_item`, sieve here, *then* `to_payload`), so whole works are kept (no rep pruned), the sieve commutes with the `min_representations` floor, and `stats.custody` partitions exactly the reported set with **no change to `to_payload`**. The filters ride the `scope` echo (pruned when unset, G2) and compose with the per-item `ref` lens (`works <id> --drift drifted`). Closed vocabulary → exit 2 over the CLI (argparse `choices=`) / `ValueError` over MCP (no `choices`), the `verify --fidelity`/`get_related_scrolls` precedent. **No schema change, no extra ledger read** — `filter_works` reuses the verdicts `to_payload` already loads. 18 tests: 7 unit (`filter_works` over clustered works — per-axis keep, whole-work contains, both-axes same-rep AND, unfiltered identity, two unknown-vocab raises) + 6 CLI (`tests/test_works.py`) + 5 MCP (`tests/test_mcp.py`: per-axis, both-axes, unknown-vocab, CLI↔MCP parity). Docs: `docs/cli.md` consolidation-filter paragraph + heading + MCP table row. Full suite green (3438 passed). **H262 closes the second consolidation slice; the next lead is H263 (the "at-risk works" `safely_held == false` alarm on `doctor`/`maintain`).**

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
| H179 | Status per-source refresh-debt maps (`enrichment_by_source`/`summary_by_source`) ≡ `maintain` ≡ `doctor`, whole-library + scoped, folded into the convergence suite | cap 2, cap 8 |
| H180 | MCP `get_library_health` keeps the fuller nested refresh-debt block — flat≡nested tie pinned | cap 2, cap 8 |
| H181 | `maintain`'s `suggested` block emits *source-scoped* refresh commands when debt is confined | cap 1, cap 8 |
| H182 | `maintain --source <S>` suggests the *scoped* refresh, not the whole-library sweep | cap 1, cap 8 |
| H183 | `maintain`'s scoped `suggested` refresh commands name exactly the debt-map sources — convergence folded into the suite | cap 1, cap 8 |
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
| H192 | Bundle-HTML action-line *content* parity ≡ the Markdown form ≡ the canonical primitive (the HTML counterpart of H188's byte-identical Markdown tie) | cap 5, cap 8 |
| H193 | Single-source compiled `sources/<S>.md` `_Refresh:_` honest presence ≡ `doctor --source` debt, multi-source-cluster-narrowed-below-`MIN_MEMBERS` summary-absence pinned positively — the last compiled readable-parity tie | cap 7, cap 8 |
| H195 | MCP object-twin `stats.custody.by_source` *content* ≡ `doctor` — graph twin whole-library (≡ doctor incl. coverage, isolation-independent; *not* connected-only ⊂ doctor, the slice-framing correction), works twin representation-only (≡ doctor lean projection; ⊂ doctor when an item is unrepresented) | cap 1, cap 2 |
| H211 | MCP object-twin `stats.custody.attention` *scope* tie — graph flag whole-library (≡ `weakest_source(doctor.by_source)` ≡ `status` ≡ `maintain`, sees the loss on an isolated node), works flag representation-only (honestly `null` when the loss is unrepresented; fires + re-converges on shared fields when the loss enters scope, coverage staying the whole-library flag's alone) | cap 1, cap 2 |
| H206 | CLI attention→scoped-`maintain` *drift*-act triage as one shell sequence in `tests/test_dogfood.py` — the shell twin of H204's MCP flow: `status`'s `attention` names the weakest source + the exact recheck command, `maintain --source <S>` collapses to it (singleton `by_source`, null `attention`, `custody` ≡ `doctor --source <S>` distilled), the scoped triage non-persisting (whole-library trend baseline byte-untouched, `delta` null, ADR 0082) | cap 11 |
| H208 | MCP `get_library_health` nested refresh-debt read (`enrichment.by_source`/`summaries.by_source`) folded into the H179 three-way tie ≡ `status` flat maps ≡ `doctor`, whole-library + `--source`-scoped, over the combined stale-classification+stale-summary seed — carrying the H171 double-attribution asymmetry and the single-source-cluster scope-collapse, mutation-checked; H179/H183/H208 seed triplication factored into one `_seed_refresh_debt_both_axes` helper | cap 2, cap 8 |
| H209 | MCP `run_maintenance` scoped `suggested` ↔ debt-map convergence folded into the suite — the agent-facing sibling of H183: the whole-library `run_maintenance()` tool's scoped `classify --stale --source <S>` / `kb --stale --source <S>` suggestion sources ≡ its own `enrichment_by_source` / `summary_by_source` keys (H171 double-attribution carried), the MCP report converges field-for-field with CLI `maintain --no-recheck` and the pure `suggest_repairs(run_doctor())`, the H182 short-circuit pinned over MCP (a scoped `run_maintenance(source=S)` names exactly `<command> --source S` per present axis — web enrichment-only, wikipedia summary-only under their own scopes), mutation-checked by a `kb --stale --source wikipedia` refresh moving the suggestions in lockstep with the debt map | cap 1, cap 11 |
| H210 | CLI refresh-debt *act* dogfood in `tests/test_dogfood.py` — the refresh-axis twin of H206's drift-act triage: an agent reads the `context` `_Refresh:_` line (== `doctor`'s `enrichment.by_source`/`summaries.by_source`, enrichment `{web}` ≠ summary `{arxiv, web}`, non-vacuous), runs the scoped `classify --stale --source web` (drops only the enrichment clause), then `kb --stale --source web` (clears the whole two-source cluster in lockstep — the H171 attribution: a cluster is refreshed under any of its sources) and the `_Refresh:_` line vanishes (honest absence); the refresh act *is* the mutation, the model call scripted offline at `kb_llm._anthropic_complete`. Closed the per-source convergence theme | cap 8, cap 11 |
| H212 | `_Fidelity: full <a>, partial <b>, reference <c> (of N)._` holdings line at the `index` budget on `scrolls context` — the leanest tier reads no ledger (no `_Custody:_` drift claim, the M2 honesty gate) but *fidelity travels with every result* (vision principle 3): a ledger-free holdings fact via the new shared `custody.render_fidelity_holdings`/`_fidelity_tokens`, byte-identical to the `connected`+ headline's `fidelity` section (converge by construction), an `index`-only lever never duplicated above it. Opened the budget/tier custody-honesty horizon | cap 2, cap 7, cap 10 |
| H213 | Cross-tier fidelity convergence test in `tests/test_custody_convergence.py` — the `index` `_Fidelity:_` counts ≡ the `connected` *and* `full` `_Custody:_` headline's `fidelity` section ≡ `doctor`'s `custody.tiers`, four reads of one ledger-free fact (`get_fidelity` per item) over one mixed-fidelity scope (full 2, partial 1, reference 1; ≥2 tiers, non-vacuous), parsed back from each rendered line by a shared `_rendered_fidelity_counts` tier-token regex; mutation-checked — dropping `web:full1`'s `raw_text`+`content_hash` falls it `full`→`partial` and the shift registers on every surface in lockstep ({full 1, partial 2, reference 1}). Sabotage-verified non-vacuous (dropping `partial` from the `index` line alone breaks the four-way tie). The budget/tier-honesty sibling of the module's headline spine | cap 7 |
| H214 | MCP twin of H212 in `tests/test_mcp.py` — `get_context_bundle(budget="index")` carries the `_Fidelity:_` holdings line (non-vacuous full 1 + partial 1, `(of 2)`), honestly omits the drift verdict (no `_Custody:`/`drifted` token over the unread ledger), and its line is *byte-identical to the CLI*'s `scrolls context --budget index` (the agent-facing bundle and the CLI never diverge on the leanest tier's fidelity read); from `connected` up the dedicated line yields to the headline's `fidelity` section (the H212 no-duplication rule, here over MCP). Sabotage-verified non-vacuous (a post-processing divergence in `get_context_bundle` breaks the CLI≡MCP equality) | cap 2, cap 10 |
| H215 | The `index` fidelity line folded into the M2 completeness/anti-fabrication invariant (`tests/test_completeness.py`) — the leanest `context --budget index` tier names its `_Fidelity: full N (of K)._` holdings (fidelity is a ledger-free fact, travels everywhere; vision principle 3) but carries no `_Custody:`/drift token, while the *same* query at `connected`+, over a **recorded** `drifted` verdict, carries the `_Custody:_` headline's `drift drifted 1` section — so the `index` absence is a genuine withholding of an unread ledger claim, not an empty scope (the budget/tier-honesty counterpart of H190's compiled-page action-line honest-absence; the per-excerpt drift block's honesty on the depth axis). Sabotage-verified non-vacuous (flipping the `index`-tier ledger gate makes the dedicated `_Fidelity:_` line vanish, failing the test). Closes the budget/tier-honesty sub-theme CLI-side | cap 7, M2 |
| H219 | MCP twin of H215 in `tests/test_completeness.py` (`test_mcp_index_budget_names_fidelity_holdings_but_no_drift_verdict`), beside the CLI fold — the M2 anti-fabrication contract on the read an agent reaches over MCP. `get_context_bundle(query, budget="index")` names its `_Fidelity: full N (of K)._` holdings (ledger-free fact; fidelity travels, vision principle 3) and carries no `_Custody:`/drift token, while the *same* query at `connected`+, over a **recorded** `drifted` verdict, carries the `_Custody:_` headline's `drift drifted 1` section — so the `index` silence is a genuine withholding, not an empty scope. Where H214 pinned the MCP fidelity *line* + its CLI byte-identity, H219 adds the *completeness* framing (the honest absence proven against a verdict the deeper tiers surface). Sabotage-verified non-vacuous (flipping the `index`-tier ledger gate so the `_Custody:_` headline leaks suppresses the dedicated `_Fidelity:_` line). Closes the budget/tier-honesty *drift-withholding* contract on both surfaces (CLI H215 + MCP H219) | cap 2, cap 7, M2 |
| H217 | Bundle import is honest about *orphan* custody events (`custody.partition_resolvable_events`, `src/scrolls/cli.py` `_cmd_import_bundle`, `tests/test_bundle.py`) — every imported event must resolve to a held-or-imported item; one whose `item_id` names no such item is split off, counted in the summary (`events.orphaned`, always present), warned on stderr, and *not* inserted (no dangling ledger row for an item `scrolls show` 404s on). A well-formed export never orphans (events ride only for in-scope items, all in the items block), so this guards the corrupt/hand-edited case — the M2 anti-fabrication ethos on the import-completeness axis (custody §2.4); the whole-library `import events` restore (H72) stays orphan-tolerant by design (events restore independently of items). Sabotage-verified non-vacuous (neutering the partition fails both the orphan-count and no-dangling-row tests). Opened the *event-complete* leg of the portable-bundle round-trip-depth horizon | cap 9, cap 7 |
| H216 | Mixed-fidelity bundle round-trip invariant in `tests/test_bundle.py` (`test_mixed_fidelity_bundle_parse_preserves_each_tier` + `test_mixed_fidelity_bundle_round_trips_across_a_fresh_library`) — portability is *tier-lossless*, not just full-lossless. The other round-trip ties only exercise an all-`full` fixture; H216 builds a scope spanning all three tiers (a `full` body, an extracted-but-unhashed `partial`, a body-less `reference` pointer riding its query term in the title), `export bundle`s it, and re-imports into a fresh library, asserting each item's `get_fidelity` tier is identical across the boundary (exact-equality catches a downgrade *or* a spurious promotion). Test-only — the round-trip is lossless by construction (`item_to_dict`/`item_from_dict` carry every field; `insert_item` writes every column), so fidelity travels (vision principle 3). Sabotage-verified non-vacuous (dropping the body in `item_from_dict` falls `full`→`partial`, `partial`→`reference`; both tests fail). Opened the portable-bundle round-trip-depth horizon | cap 7, cap 9 |
| H220 | `scrolls import bundle --dry-run` — the read-only preview of a bundle merge (`src/scrolls/cli.py` `_preview_import_bundle`, `custody.preview_import_events`, `partition_resolvable_events(known_ids=)`, `tests/test_bundle.py`). An agent handed a portable "take it with me" bundle sees *exactly* what an import would add vs. skip — the same `{imported, skipped, items, events}` summary plus a `"dry_run": true` marker — **without writing**, the read-only sibling of the custody-safe `INSERT OR IGNORE` import (ADR 0082). Item counts from `get_item` existence (within-bundle dups tracked in a `seen_item_ids` set, so exact); event counts from the new `preview_import_events` (the writer's content-dedup, read-only, within-batch dups in a local `seen` set); the orphan split from `partition_resolvable_events`, now taking `known_ids` so the bundle's own item ids anchor the partition — a real import inserts those rows *before* partitioning, so a preview into an **empty** library resolves the bundle's events instead of mis-flagging every one as an orphan. Summary pinned byte-for-byte equal to the subsequent real import's (sans `dry_run`) over a mixed held/new scope (`test_import_bundle_dry_run_counts_match_a_real_import`), the dry-run writing nothing (`…_previews_without_writing`) and honest about orphans exactly as the real import (`…_previews_orphan_events`). Sabotage-verified non-vacuous (neutering `known_ids` fails all three). Built on H217's orphan accounting | cap 9, cap 7 |
| H221 | The `index` `_Fidelity:_` line's `(of N)` scope is honest under truncation (`tests/test_context.py`) — the leanest tier's holdings count the *in-bundle* set (`len(items)`, the kept post-cap representations), never the library-wide matched total. Over a mixed-fidelity scope larger than the cap (3 `full` + 3 `partial`, all matching `database`), `context --budget index --limit 4` carries `_Fidelity: … (of 4)._` whose `(of 4)` equals the `_Coverage: the top 4 of 6` line's `returned` (parsed from both rendered lines, so tied not hardcoded), whose tier counts sum to that kept set (4, not the library-wide 6), and whose split is provably mixed (pigeonhole: 4 from {3 full, 3 partial} spans both tiers). Test-only — the production line already passes `len(items)` to `render_fidelity_holdings` (`context.py:252`), so the honesty is correct-by-construction and the slice pins it (the depth-axis sibling of H215's drift-absence honesty; the *fidelity* counterpart of the Coverage line's match-set honesty). Sabotage-verified on both guards (passing `matched` as N fails the `(of N)` tie; folding library-wide tier counts under the kept `(of N)` fails the tier-sum tie) | cap 7, cap 10 |
| H222 | MCP twin of H221 in `tests/test_mcp.py` (`test_get_context_bundle_index_fidelity_scope_is_honest_under_truncation`, beside the H214 twin) — the leanest tier's `(of N)` scope-honesty under a cap on the read an agent reaches over MCP. `get_context_bundle("database", budget="index", limit=4)` over a >`limit` mixed-fidelity scope (3 `full` + 3 `partial`) carries `_Fidelity: … (of 4)._` whose `(of 4)` equals the `_Coverage: the top 4 of 6` line's `returned` (parsed from both lines, tied not hardcoded — never the library-wide `matched` 6), whose tier counts sum to that kept set (4, not 6), and whose split is provably mixed (pigeonhole). The distinguishing MCP-twin assertion is the H214 byte-identity *under truncation*: the bundle's `_Fidelity:_` line is byte-identical to the CLI's `context --budget index --limit 4` (both `build_context`). Test-only — `get_context_bundle` is a read-through of `build_context`, which already counts `len(items)` (the kept post-cap reps), so shared-by-construction. Sabotage-verified non-vacuous on both guards in `context.py` (passing `matched` as N fails the `(of N)` tie; inflating the tier counts under the kept `(of N)` fails the tier-sum tie) | cap 2, cap 10 |
| H223 | The `index` `_Fidelity:_` holdings honor the active facet scope (`tests/test_context.py`, `test_context_index_fidelity_scope_honors_the_active_facet`, beside the H221 truncation pin) — the leanest tier's holdings count the *post-facet* kept set (the representations `build_context` keeps after the `source`/`category`/`stage`/`tag`/`concept` filter, `len(items)`), so a scoped `context --budget index --source <S>` names only `<S>`'s fidelity tiers and `(of k)` scope, never the library-wide holdings of a multi-source library. The fixture is multi-source *and* mixed-fidelity within one source (web full 1 + partial 1, arxiv full 2), so web's scoped holdings (`{full 1, partial 1}`, `(of 2)`) are a provable strict subset of — and a different tier split than — the library-wide holdings (`{full 3, partial 1}`, `(of 4)`); the test reads both the scoped and unscoped `_Fidelity:_` line and asserts the scoped counts + `(of N)` equal web's subset (tied to the shared `custody_counts_by_source` primitive, not independently hardcoded) while the unscoped names the whole library, the two genuinely differing on both axes. The *facet*-axis sibling of H221's *truncation*-axis `(of N)` scope-honesty. Test-only — the production passes the post-facet `len(items)`/`custody_counts(items, {})` to `render_fidelity_holdings` (`context.py:251`), correct-by-construction. Sabotage-verified non-vacuous (recomputing holdings over the whole library, ignoring the facet, leaks `{full 3, partial 1}` and fails both the tier-count and `(of N)` guards) | cap 7, cap 10 |
| H225 | `import bundle` names *which* items the orphan custody events dangle on — the diagnosable half of H217 (`src/scrolls/cli.py` `_warn_orphan_events`, `tests/test_bundle.py`). H217's stderr warning surfaced only the orphan *event count*; it now leads with that count, then names the distinct orphan `item_id`s (sorted, deduped, bounded with a `(+N more)` tail at `_MAX_ORPHAN_ITEM_IDS = 5`, the readable-surface idiom), so "3 orphan events" becomes "… not in this bundle …: `arxiv:2401.00001`, `wikipedia:en:Ghost`" — the operator sees which rows the items block is missing (a splice/truncation), not just that the bundle is corrupt. The leading count stays the *event* count; the named id list is the *distinct-item* count (two events on one missing item name it once — `…_warning_names_which_items_the_orphans_dangle_on`, 3 events / 2 items). Shared by the live import and the `--dry-run` preview (H220), so both surfaces get the ids for free. A second test pins the `(+N more)` bound (`…_orphan_warning_bounds_the_id_list`). `docs/cli.md`'s orphan-restore paragraph documents it. The *diagnosable* sibling of H217's orphan-count honesty | cap 9, cap 7 |
| H227 | MCP twin of H223 in `tests/test_mcp.py` (`test_get_context_bundle_index_fidelity_scope_honors_the_active_facet`, beside the H214/H222 twins) — the leanest tier's *facet*-scope honesty on the read an agent reaches over MCP. `get_context_bundle("database", budget="index", source="web")` over a multi-source, mixed-fidelity library (web full 1 + partial 1, arxiv full 2) carries a `_Fidelity:_` line whose tier counts (`{full 1, partial 1}`) + `(of 2)` scope equal web's post-facet subset (tied to the shared `custody_counts_by_source` primitive, not independently hardcoded), while the *unscoped* twin names the library-wide holdings (`{full 3, partial 1}`, `(of 4)`); the two differ on both axes (non-vacuous). The distinguishing MCP-twin assertion is the H214 byte-identity *under facet scope*: the scoped bundle's `_Fidelity:_` line is byte-identical to the CLI's `context --budget index --source web` (both `build_context`). Test-only — `get_context_bundle` forwards `source`/facets straight to `build_context` (`mcp_server.py:491`), which passes the post-facet `len(items)`/`custody_counts(items, {})` to `render_fidelity_holdings`, so shared-by-construction. Sabotage-verified non-vacuous (recomputing holdings over the whole library, ignoring the facet, leaks `{full 3, partial 1}` and fails both the H227 MCP and H223 CLI facet tests in lockstep). The *facet*-axis MCP twin completing the H222 (truncation) / H227 (facet) MCP-twin pair | cap 2, cap 7, cap 10 |
| H224 | The whole-library JSONL backup is *tier-lossless* too — the H216 round-trip guarantee on the other portable surface (`tests/test_roundtrip.py`, `test_whole_library_backup_is_tier_lossless`). Every prior round-trip test builds an all-`full` library (`_seed_items` — raw + hash at a rendered stage), so the `partial`/`reference` tiers were never proven to survive the *whole-library* backup the way H216 proved they survive the *scoped bundle*. The new `_mixed_fidelity_seed` spans all three tiers (2 `full` raw+hash captures, a `partial` whose extracted text survives but carries no raw body or `content_hash`, a body-less `reference` pointer at `detected` stage); the test reads `doctor`'s `custody.tiers` as the source spread (`{full 2, partial 1, reference 1}`, non-vacuous — ≥2 non-zero tiers), rebuilds in a fresh home via the documented backup commands (`export items` → `import items` → `doctor --fix` → `kb`), and asserts the rebuilt `custody.tiers` *equals* that spread (no rebuild-side downgrade) plus a clean audit (`score 100`, `issues 0` — an honest partial/reference is custody, not a violation). Test-only — `import items` carries every content field (`item_to_dict`/`item_from_dict`, ADR 0082) and `doctor --fix` rebuilds only derived artifacts, never the row fields `get_fidelity` reads from, so tier-losslessness is correct-by-construction. Sabotage-verified non-vacuous (dropping `raw_text`+`content_hash` in `item_from_dict` downgrades both `full` items to `partial`, `{full 2, partial 1}` → `{full 0, partial 3}`, failing the equality). The whole-library-backup sibling of H216 | cap 9, cap 4 |
| H226 | `import bundle --dry-run` names *which* scrolls are new vs. already held — the reviewable half of H220 (`src/scrolls/cli.py` `_preview_import_bundle`, `tests/test_bundle.py`, `docs/cli.md`). H220's preview surfaces *counts* (`imported, skipped`) — how much a merge changes, not *what*; the dry-run summary now carries two reviewable id lists beside them: `new` (would-be-imported ids) and `held` (already-in-library ids the merge skips), each **sorted, deduped, uncapped** (structured completeness vs. the bounded human orphan warning, the M2 ethos). **Dry-run-only** — the live import stays terse (its rows are written; "new vs. held" is a pre-merge concept). The read-only preview loop now collects the two sets directly (`new_ids` = ids `get_item` finds absent, `held_ids` = present), so `item_imported = len(new_ids)` is unchanged and `len(new) == imported` holds by construction; `len(held) == skipped` for a dup-free bundle. `test_import_bundle_dry_run_names_which_items_are_new_vs_held` pins the one-new/one-held case; the H220 byte-identity test was widened to strip the dry-run-only `new`/`held` alongside `dry_run`, so the *counts* byte-identity guarantee survives and the real import is asserted terse | cap 9, cap 7 |
| H228 | The `index` `_Fidelity:_` `(of N)` is honest under facet scope *and* truncation at once — the *composition* of H221 (truncation) and H223 (facet) (`tests/test_context.py`, `test_context_index_fidelity_scope_is_honest_under_facet_and_truncation`, beside the H221 truncation pin). Over a mixed-fidelity, multi-source library where one source's matching scope exceeds the cap (web 3 `full` + 3 `partial` = 6 matching; arxiv 2 `full`; library-wide 8), `context --budget index --source web --limit 4` carries `_Fidelity: … (of 4)._` whose `(of 4)` equals the scoped-*and*-truncated `_Coverage: the top 4 of 6`'s `returned` (parsed from both rendered lines, tied not hardcoded), whose tier counts sum to that kept set (4, not the scoped-untruncated 6 or library-wide 8), and whose split is provably mixed (pigeonhole: 4 from {3 full, 3 partial} spans both tiers). Both axes pinned non-vacuous: the scoped Coverage denominator is web's 6 — never the library-wide 8 the *unscoped* read at the same cap shows (`top 4 of 8`), so the facet stays applied under the cap; and the *untruncated* scoped read names web's `(of 6)`, so the cap genuinely truncated. Test-only — `build_context` passes `len(items)` (kept after *both* the facet filter and the cap) to `render_fidelity_holdings` (`context.py:252`), correct-by-construction; the slice pins neither axis reverts when the other is active (the CLI sibling H232 will twin over MCP). Sabotage-verified non-vacuous (passing the scoped-but-untruncated `matched` 6 as N fails the `(of N)` tie on both H228 and the H221 truncation pin in lockstep) | cap 7, cap 10 |
| H232 | MCP twin of H228 in `tests/test_mcp.py` (`test_get_context_bundle_index_fidelity_scope_is_honest_under_facet_and_truncation`, beside the H222/H227 twins) — the leanest `index` `_Fidelity:_` `(of N)` honest under facet scope *and* truncation at once on the read an agent reaches over MCP. `get_context_bundle("database", budget="index", source="web", limit=4)` over a mixed-fidelity, multi-source library where web's matching scope exceeds the cap (web 3 `full` + 3 `partial` = 6; arxiv 2 `full`; library-wide 8) carries `_Fidelity: … (of 4)._` whose `(of 4)` equals the scoped-*and*-truncated `_Coverage: the top 4 of 6`'s `returned` (parsed from both rendered lines, tied not hardcoded), whose tier counts sum to that kept set (4, not the scoped-untruncated 6 or library-wide 8), and whose split is provably mixed (pigeonhole). Both axes non-vacuous: the *unscoped* read at the same cap shows `top 4 of 8` (facet stays applied, 6 ≠ 8); the *untruncated* scoped read names web's `(of 6)` (cap genuinely truncated, 4 ≠ 6). Distinguishing MCP-twin assertion: the H214 byte-identity *under both filters* — the bundle's `_Fidelity:_` line is byte-identical to the CLI's `context --budget index --source web --limit 4` (both `build_context`). Test-only — `get_context_bundle` reads through `build_context`, which passes `len(items)` (kept after both the facet filter and the cap) to `render_fidelity_holdings` (`context.py:252`), shared-by-construction. Sabotage-verified non-vacuous on both fidelity-line guards in `context.py` (passing the scoped-but-untruncated `matched` 6 as N fails the `(of N)` tie; inflating the tier counts under the kept `(of N)` fails the tier-sum tie). With H228 (CLI) and H232 (MCP) both shipped, the facet+truncation composition honesty holds on both surfaces | cap 2, cap 7, cap 10 |
| H229 | The scoped `index` `_Fidelity:_` counts ≡ `doctor --source <S>`'s `custody.tiers` — the scoped sibling of H213's cross-tier convergence (`tests/test_custody_convergence.py`, `test_scoped_index_fidelity_line_ties_to_doctor_source_tiers`, beside the H213 unscoped tie). Over a multi-source, mixed-fidelity library where one query matches all of `<S>`'s held items (no truncation), `context --budget index --source <S>`'s `_Fidelity:_` tier counts equal `doctor --source <S>`'s `custody.tiers` (non-zero entries) — both fold `get_fidelity` over the same scoped item set — so the leanest tier an agent boots on and the deep custody audit never disagree on what fraction of one source is held in full. Fixture: `_seed_mixed_custody` (web `full 2, partial 1, reference 1`) + one out-of-scope arxiv `full`, so web's scoped tiers `{full 2, partial 1, reference 1}` are a strict subset of — and differ from — the whole-library `{full 3, partial 1, reference 1}` (scoping non-vacuous); `(of 4)` confirms the query matched all of web's held items (no truncation — the H229 precondition; H234 is the truncated boundary). Tied to the shared `custody_counts_by_source` primitive, not independently hardcoded. Mutation-checked: dropping `web:full1`'s `raw_text`+`content_hash` falls it `full`→`partial`, shifting both the scoped `_Fidelity:_` line and `doctor --source web`'s tiers to `{full 1, partial 2, reference 1}` in lockstep. Test-only — `build_context` passes the post-facet `len(items)` to `render_fidelity_holdings` and `run_doctor(source=)` folds over the scoped rows, so the tie is correct-by-construction. Sabotage-verified non-vacuous on both axes (neutering `run_doctor`'s source filter leaks the whole-library `full 3` into the audit; recomputing the `_Fidelity:_` tiers over the whole library leaks `full 3` into the line — each fails the `index == tiers` tie). The scoped completion of H213's convergence loop | cap 1, cap 7, cap 10 |
| H231 | The whole-library backup's byte-identical rebuild holds across *mixed* fidelity tiers too — the byte-depth sibling of H224's tier-count guarantee (`tests/test_roundtrip.py`, `test_whole_library_backup_rebuilds_byte_identically_across_tiers`, beside the H224 tier-lossless pin). `test_export_rebuild_is_byte_identical` pins the rebuilt scrolls + compiled `library/` pages byte-identical only over the all-`full` `_seed_items`; a `partial` capture's scroll, rendered with no `content_hash` to fingerprint it (`render.py` omits a `None` frontmatter field — a strictly different byte-shape than a `full` scroll), had never been proven to rebuild byte-for-byte. Reusing H224's `_mixed_fidelity_seed` (2 `full` + 1 `partial` + 1 `reference`), the test captures the source's `scrolls_dir`/`library_dir` trees, rebuilds in a fresh home via `import items` → `doctor --fix` → `kb`, and asserts both `_read_tree` snapshots are byte-identical — so the lossless round-trip is a guarantee in the rendered *bytes* of a degraded capture, not only its tier count. A non-vacuous guard proves the tree spans both byte-shapes (≥1 scroll with a `content_hash:` line, ≥1 without — the partial). Test-only — `import items` carries every content field (`item_to_dict`/`item_from_dict`, ADR 0082) and `doctor --fix` re-renders each scroll deterministically (`write_scroll`), so byte-identity is correct-by-construction. Sabotage-verified non-vacuous (dropping `extracted_text` in `item_from_dict` strips every rebuilt scroll's `## Extracted Content`, the partial's included, failing the equality). The byte-depth sibling of H224 | cap 4, cap 9 |
| H230 | The import summary names *which* items orphaned in its structured JSON — the machine-readable half of H225 (`src/scrolls/cli.py` `_orphan_item_ids`, `tests/test_bundle.py`, `docs/cli.md`). H225 named the distinct orphan `item_id`s only in the `{"warning": …}` *stderr* string; an agent piping `import bundle` *stdout* saw only the `events.orphaned` event count and had to scrape the human prose to learn *which* items dangle. The import summary now carries `events.orphaned_items` beside the count — the distinct orphan `item_id`s, sorted + deduped + **uncapped** — on **both** the live import and the `--dry-run` preview, always present (`[]` is the honest "we checked, none dangled"). A new `_orphan_item_ids` helper is the single source of truth shared by the structured field and `_warn_orphan_events` (which still bounds its *named* list with a `(+N more)` tail), so the two surfaces never disagree on the orphan set; the cap is a human-readability concern, never a structured-field truncation (M2: structured completeness vs. human bound). `test_import_bundle_summary_names_which_items_orphaned` pins a 3-event / 2-item spliced bundle's `orphaned_items == ["arxiv:2401.00001", "wikipedia:en:Ghost"]` (doubly-orphaned id named once; `orphaned` stays the event count 3; byte-equal between live import and dry-run); `test_import_bundle_orphaned_items_is_uncapped_while_the_warning_bounds` pins a `>_MAX_ORPHAN_ITEM_IDS` bundle's `orphaned_items` listing every distinct id while the warning shows five + a `(+N more)` tail; the honest-zero test now also pins `orphaned_items == []`. Eight existing exact-equality `events` assertions updated to the always-present shape. Test + small source — the diagnosability H225 gave the human warning now rides the machine channel too. Sabotage-verified non-vacuous (capping `_orphan_item_ids` drops the tail ids and fails the uncapped test). The *machine-readable* sibling of H225 | cap 9, cap 7 |
| H233 | The dry-run `new`/`held` review lists dedup honestly under within-bundle duplicate item ids — the *dedup* half of H226 (`tests/test_bundle.py`, `test_import_bundle_dry_run_dedups_new_and_held_under_within_bundle_dup_ids` + the new `_items_only_bundle` helper, beside the H226 pin). H226's `new`/`held` are deduped sets and `len(new) == imported` holds by construction over a well-formed bundle; H233 pins the corrupt case a naive id-list would phantom-inflate. A spliced bundle whose custody block repeats both a would-be-new id and an already-held id (rendered via the real `_items_block([new, new, held, held])`; `parse_bundle` appends every record without deduping, `bundle.py:667`, so the dups reach `_preview_import_bundle`) names each distinct id exactly once — `new == ["arxiv:1706.03762"]`, `held == ["wikipedia:en:SQLite"]` — while `items`/`imported`/`skipped` count the raw occurrences (4 → `imported 1, skipped 3`), so the reviewable surface never over-claims more distinct items than the bundle holds (the M2 ethos on the dedup axis). Pins the distinguishing asymmetry — `len(new) == imported == 1` survives the dup (distinct-new count), `len(held) < skipped` (held-id repeat skipped twice but named once, plus the dup-new skip) — and that the raw `imported`/`skipped` equal a real import of the same corrupt bundle (the preview never drifts from reality under dups; the live import stays terse). Test-only — the set-based collection dedups by construction. Sabotage-verified non-vacuous (swapping the sets for append-lists inflates `new` to two entries, fails the test). The *dedup* sibling of H226 | cap 9, cap 7 |
| H234 | The scoped `index` `_Fidelity:_` holdings diverge honestly from `doctor --source <S>`'s `custody.tiers` *under truncation* — the boundary/complement of H229 (`tests/test_custody_convergence.py`, `test_scoped_index_fidelity_holdings_diverge_from_doctor_under_truncation`, beside the H229 tie). H229 ties the scoped leanest line to the scoped audit *only when one query matches all of `<S>`'s held items* (no truncation); H234 pins the truncated case, where the two answer different questions — the line is a *this-bundle* fact ("what does this bundle hold in full", over the post-cap kept set `len(items)`), the audit a *whole-source* fact (over every held row). Over `_seed_mixed_custody` (web `full 2, partial 1, reference 1`) + one out-of-scope arxiv `full`, `context --budget index --source web --limit 2` (cap `2 < 4 = held`) renders a `_Fidelity:_` line whose `(of N)` and tier counts both sum to the kept slice `2`, while `doctor --source web`'s tiers sum to web's whole held count `4` — so the two genuinely differ (bundle-kept `2` ≠ source-wide `{full 2, partial 1, reference 1}`), the leanest tier never inflating the holdings to a source-wide claim it didn't render. Mutation: lifting to `--limit 4` (≥ held) keeps every matching web item, reconverging the line exactly to `doctor --source web`'s tiers — the H229 equality, recovered, so the gap is exactly the cap. The `--source web` filter is non-vacuous on both reads (the *unscoped* audit names `{full 3, partial 1, reference 1}`). Test-only — `build_context` passes the post-cap `len(items)` to `render_fidelity_holdings` while `run_doctor(source=)` folds over the whole scoped rows, so the divergence (and its collapse on lift) is correct-by-construction. Sabotage-verified non-vacuous (passing the pre-cap `matched` count to `render_fidelity_holdings` inflates the line's `(of N)` to the source-wide `4` even under the cap, failing the `scope_n == 2` divergence). The *truncated boundary* of H229 | cap 1, cap 7, cap 10 |
| H235 | The scoped `index` `_Fidelity:_` counts ≡ `get_library_health(source=<S>)`'s `custody.tiers` over MCP — the MCP twin of H229 (`tests/test_mcp.py`, `test_get_context_bundle_index_fidelity_counts_tie_to_scoped_library_health`, beside the H222/H227/H232 twins). Where H229 ties the *CLI* `context --budget index --source <S>`'s `_Fidelity:_` tier counts to `doctor --source <S>`'s `custody.tiers`, H235 carries that scoped tie onto the read *pair* an agent reaches over MCP: over a multi-source, mixed-fidelity library where one query matches all of `<S>`'s held items (no truncation), `get_context_bundle(query, budget="index", source=<S>)`'s `_Fidelity:_` tier counts equal `get_library_health(source=<S>)`'s `tiers` (non-zero) — both fold `get_fidelity` over the same scoped item set — so the leanest tier an agent boots on over MCP and the deep custody audit it also reads over MCP never disagree on what fraction of one source is held in full. Fixture: web `full 2, partial 1, reference 1` + one out-of-scope arxiv `full`, so web's `{full 2, partial 1, reference 1}` is a strict subset of — and differs from — the whole-library `{full 3, partial 1, reference 1}` (scoping non-vacuous over MCP, `get_library_health()` vs `get_library_health(source="web")`); `(of 4)` confirms the query matched all of web's held items (no truncation — H236 is the truncated boundary). Tied to the shared `custody_counts_by_source` primitive. Mutation-checked: dropping `web:full1`'s `raw_text`+`content_hash` falls it `full`→`partial`, shifting both the scoped `_Fidelity:_` line and `get_library_health(source="web")`'s tiers to `{full 1, partial 2, reference 1}` in lockstep. Test-only — `get_context_bundle` forwards to `build_context` (post-facet `len(items)` → `render_fidelity_holdings`) and `get_library_health` is the MCP twin of `doctor` (`run_doctor`), both folding over the same scoped rows. Sabotage-verified non-vacuous on both axes (neutering `run_doctor`'s source filter leaks the whole-library `full 3` into `get_library_health(source="web")`'s tiers; recomputing the bundle line over the whole library, ignoring the facet, leaks `full 3` into the line — each fails the `index == tiers` tie). The *MCP twin* of H229 | cap 1, cap 2, cap 7 |
| H236 | The scoped `index` `_Fidelity:_` holdings diverge honestly from `get_library_health(source=<S>)`'s `tiers` *under truncation* over MCP — the MCP twin of H234 (and the truncated boundary of H235) (`tests/test_mcp.py`, `test_get_context_bundle_index_fidelity_diverges_from_scoped_health_under_truncation`, beside the H232/H235 twins). H235 ties the bundle line to the scoped audit *only* when one query matches all of `<S>`'s held items (no truncation); H236 pins the **boundary** where the bundle is capped, on the read *pair* an agent reaches over MCP. The two answer different questions: the bundle line is a *this-bundle* fact ("what does this bundle hold in full", over the post-cap kept set `len(items)`), the scoped health audit a *whole-source* fact (over every held row). Over a `web` scope of `full 2, partial 1, reference 1` (4 held) + one out-of-scope arxiv `full`, `get_context_bundle("topic", budget="index", source="web", limit=2)` (cap `2 < 4`) renders a `_Fidelity:_` line whose `(of N)` and tier counts both sum to the kept slice `2`, while `get_library_health(source="web")`'s `tiers` sum to web's whole held count `4` — so the two genuinely differ over MCP (bundle-kept `2` ≠ source-wide `{full 2, partial 1, reference 1}`), the leanest tier never inflating the holdings to a source-wide claim. Mutation: lifting to `limit=4` (≥ held) keeps every matching web item, reconverging the line exactly to `get_library_health(source="web")`'s tiers — the H235 equality, recovered, so the gap is exactly the cap. The `source="web"` filter is non-vacuous on both reads (the *unscoped* MCP audit names `{full 3, partial 1, reference 1}`); the scoped audit is tied to the shared `custody_counts_by_source` primitive. Test-only — `get_context_bundle` forwards to `build_context` (post-cap `len(items)` → `render_fidelity_holdings`) while `get_library_health(source=)` is the MCP twin of `doctor` (`run_doctor`) folding over the whole scoped rows, so the divergence (and its collapse on lift) is correct-by-construction. Sabotage-verified non-vacuous (passing the pre-cap `matched` count to `render_fidelity_holdings` inflates the line's `(of N)` to the source-wide `4` even under the cap, failing the `scope_n == cap == 2` divergence). The *MCP twin* of H234 (truncated boundary of H235) | cap 1, cap 2, cap 7 |
| H237 | The dry-run preview's whole `events` block — `{imported, skipped, orphaned, orphaned_items}` — is byte-identical to the real import's over a corrupt, orphan-bearing bundle — the corrupt-bundle analogue of H220's byte-identity guarantee (`tests/test_bundle.py`, `test_import_bundle_dry_run_whole_events_block_matches_a_real_import_under_orphans`, beside the H230 orphan tests). H220 pins the dry-run summary byte-equal to the real import's only over a *clean* held/new scope; H230 pins only `orphaned`/`orphaned_items` equal across the two surfaces. The untested cell was the **whole** `events` block including the resolvable-event accounting `{imported, skipped}` — a genuine cross-implementation guarantee, since the dry-run counts resolvable events via `preview_import_events` (within-batch dedup tracked in a local `seen` set) and the live import via `import_events` (that dedup free from its prior INSERT). Over a `_spliced_bundle` whose anchored events carry a within-bundle **duplicate** (forcing `imported 2`, `skipped 1`) beside three orphan events on two missing items (`orphaned 3`, `orphaned_items` 2, the doubly-orphaned id named once), the test dry-runs first (writing nothing — asserted via `get_item`/`item_events`), then real-imports into the same library, and asserts the dry-run's entire `events` block equals the real import's *and* equals the expected non-trivial block (non-vacuous in every field). Strictly stronger than H230's two-field tie: this also pins the `{imported, skipped}` accounting each surface computes through a *different* function. The live import's two distinct resolvable events land on disk (`[drifted, rotted]`, the dup skipped), the orphans never. Test-only — `preview_import_events`/`import_events` are the read-only/writing twins of the same content-dedup over the shared `partition_resolvable_events`/`_orphan_item_ids` split, so the byte-identity is correct-by-construction. Sabotage-verified non-vacuous (stripping `preview_import_events`'s within-batch `seen` dedup makes the dry-run report `imported 3, skipped 0` while the live import still reports `imported 2, skipped 1`, failing both the whole-block tie and the expected-block assertion). The *corrupt-bundle analogue* of H220's byte-identity | cap 9, cap 7 |
| H238 | The scoped `export bundle` → `import bundle` round-trip rebuilds the `partial` scroll byte-identically — the *bundle*-surface corner of the H216/H224/H231 round-trip matrix (`tests/test_bundle.py`, `test_mixed_fidelity_bundle_rebuilds_byte_identically_across_a_fresh_library` + the new `_render_mixed_library`/`_read_tree` helpers, beside `test_mixed_fidelity_bundle_round_trips_across_a_fresh_library`). H216 pins every fidelity *tier* survives `export bundle` → `import bundle`; H231 pins the rebuilt scrolls + compiled `library/` pages byte-for-byte — but only over the *whole-library JSONL backup* (`export items`). The untested cell was *bundle × bytes*: a `partial` capture's `content_hash`-less scroll, carried in a portable briefing rather than a whole-library JSONL dump, rebuilding byte-for-byte. Genuine guarantee, not the same code as H231: the bundle item block is `export items`' JSONL (`dump_items_export`) embedded in a sentinel-fenced Markdown envelope (`bundle.py` `_items_block`), a different envelope around the same `item_to_dict` rows. Over the mixed-fidelity `_mixed_fidelity_scope` (full + partial + reference, all in the `"database"` scope), `_render_mixed_library` renders the rendered-stage scrolls to disk (the reference holds no body → inserted as-is, minting no scroll) and compiles the KB; the test captures the source's `scrolls_dir`/`library_dir` trees, `export bundle "database"` (no cap → captures every item), `import bundle` into a fresh home, rebuilds via `doctor --fix` → `kb`, and asserts both `_read_tree` snapshots are byte-identical across the bundle boundary — the `partial`'s scroll included. Non-vacuous guard proves the tree spans both byte-shapes (≥1 scroll with a `content_hash:` line, ≥1 without — the partial, `render.py` omitting the `None` field). Test-only — `import bundle` reconstructs identical rows via `parse_bundle`/`item_from_dict` (ADR 0082) and `doctor --fix` re-renders each scroll deterministically (`write_scroll`), so byte-identity is correct-by-construction. Sabotage-verified non-vacuous (dropping `extracted_text` on the bundle's parse path `item_from_dict` strips the rebuilt `partial` scroll's `## Extracted Content` section, failing the scroll-tree byte-identity). The *bundle × bytes* corner completing the round-trip-depth matrix | cap 9, cap 4 |
| H239 | The dry-run `new`/`held` lists *partition* the bundle's distinct item ids — the *completeness complement* of H233's dedup (`tests/test_bundle.py`, `test_import_bundle_dry_run_new_and_held_partition_the_distinct_bundle_ids`, beside the H233/H226 pins). H233 pins that each reviewable list **dedups** (no list over-claims a within-bundle repeat); H239 pins that *together* `new`/`held` form a **complete, non-overlapping partition** of the bundle's distinct ids — `set(new) ∪ set(held)` equals every distinct id the bundle holds and `set(new) ∩ set(held) == ∅`. Without it a preview could silently drop an id from review (in neither list — invisible to the operator confirming the merge) or double-count it (in both — a contradiction, since an id is either already held or not). Over a mixed, corrupt bundle (two would-be-new arxiv ids + one already-held wikipedia id, each with a within-bundle repeat via the H233 `_items_only_bundle` helper so the dups reach `_preview_import_bundle`), the test computes the distinct bundle ids *independently* via `parse_bundle` (the same parse the import uses — the partition target, not a hardcode), then asserts `sorted(new + held)` equals that distinct set and `set(new).isdisjoint(held)`. Mutation-checked: appending one more distinct would-be-new id extends `new` by exactly that id, leaves `held` untouched, and grows the union by one — the partition tracks the bundle's distinct set, never a stale snapshot. Test-only — `new_ids`/`held_ids` are built from the disjoint branches of `get_item(...) is not None` over every parsed item (`cli.py:1873`), so the union = the distinct ids and the intersection is empty by construction. Sabotage-verified non-vacuous (adding the held id to `new_ids` as well as `held_ids` breaks disjointness, so `sorted(new + held)` carries it twice and the partition equality fails). The *completeness complement* of H233 (M2 ethos on the reviewable-partition axis) | cap 9, cap 7 |
| H240 | The whole budget ladder stays mutually equal under truncation while *together* diverging from `doctor --source <S>` — the *deeper-tier-headline analogue* of H234 (`tests/test_custody_convergence.py`, `test_scoped_budget_ladder_stays_equal_under_truncation_while_diverging_from_doctor`, beside the H234/H229/H213 ties). H213 ties the *unscoped* `index` ≡ `connected` ≡ `full` ≡ `doctor` (all four equal, untruncated); H234 pins only the *leanest* `index` `_Fidelity:_` line diverging from `doctor --source <S>` under truncation. The untested cell was the *deeper* budget tiers under a cap: the `connected`/`full` `_Custody:_` headline's `fidelity` section is rendered by a **different** function (`custody_headline` over the kept items) than the `index` line (`render_fidelity_holdings`), yet both fold over the *same* post-cap kept set (`build_context` applies `--limit` at `search_items` regardless of budget). Over `_seed_mixed_custody` (four `web` scrolls: full 2, partial 1, reference 1) + one out-of-scope `arxiv` `full`, `context --budget {index,connected,full} --source web --limit 2` (cap `2 < 4 = held`) renders three fidelity sections all *equal to each other* (the kept-2 slice `{partial 1, reference 1}`, summing to `k`) and all `≠ doctor --source web`'s `custody.tiers` (summing to the held count `4 > k`) — so no tier, leanest or deeper, inflates the bundle-kept holdings to a source-wide claim. Lifting the cap (`--limit 4` ≥ held) reconverges all four to the H213 scoped equality (`index ≡ connected ≡ full ≡` the scoped audit), proving the gap is exactly the cap. The `--source web` filter is non-vacuous on every read: the *unscoped* audit names the whole library `{full 3, …}` (arxiv's `full` lifts it). Test-only — all three tiers fold `get_fidelity` over the same post-cap `items` while `doctor --source` folds over the whole scoped rows, so the cohesion-under-truncation is correct-by-construction. Sabotage-verified non-vacuous (folding the `connected`/`full` `_Custody:_` headline over a doubled item set breaks `index == connected == full`, the kept slice's `{partial 1, reference 1}` ≠ `{partial 2, reference 2}`). The *budget-ladder-cohesion* axis of M2/principle-3 honesty | cap 1, cap 2, cap 10 |
| H241 | The scoped `index` `_Fidelity:_` counts ≡ the scoped `connected`/`full` `_Custody:_` headline's `fidelity` section, all read over MCP — the cross-*tier* MCP convergence under scope, the MCP twin of H213's deeper-tier tie (`tests/test_mcp.py`, `test_get_context_bundle_index_fidelity_ties_to_the_deeper_tier_headlines_over_mcp`, beside the H235/H236/H214 twins). H235 ties the scoped `index` line to `get_library_health(source=<S>)` *across tools* over MCP and H227/H229 tie it to the CLI; but no test pinned that the *deeper budget tiers* an agent boots over MCP agree with the leanest one *over MCP*. Genuinely distinct renderers: `get_context_bundle(query, budget="connected"/"full", source=<S>)`'s `_Custody:_` headline renders its `fidelity` section via `render_custody_headline` (`custody_headline` over the kept items), a **different** function than the `index` line's `render_fidelity_holdings`, so their agreement is a cross-rendering guarantee, not the same code twice. Over a `web` scope of `full 2, partial 1, reference 1` (4 held) + one out-of-scope `arxiv` `full` (so the *unscoped* MCP audit names `{full 3, …}` — `source="web"` genuinely exercised), every title carrying "topic" so one query matches all 4 held < the default limit (no truncation — H242 is the truncated boundary), all three MCP budget tiers' fidelity counts are equal — `index ≡ connected ≡ full == {full 2, partial 1, reference 1}` — and equal `custody_counts_by_source(...)["web"]["tiers"]`, so an agent that boots cheap on `index` then deepens over MCP never sees the held-fidelity counts shift. The drift-withholding asymmetry stays intact (H214/H219): the `index` bundle carries no `_Custody:_` headline and no `drift` token, the deeper tiers carry `drift unverified 4` — the tie is on the *fidelity* section alone. Mutation-checked: dropping `web:full1`'s `raw_text`+`content_hash` falls it `full`→`partial`, shifting all three MCP tiers to `{full 1, partial 2, reference 1}` in lockstep. Test-only — all three tiers fold `get_fidelity` over the same scoped post-facet `items` in `build_context`, correct-by-construction. Sabotage-verified non-vacuous (folding the `connected`/`full` `_Custody:_` headline over a doubled item set breaks `index == connected == full`). The *cross-tier MCP convergence* under scope, the MCP twin of H213's deeper-tier tie | cap 1, cap 2, cap 10 |
| H242 | The whole MCP budget ladder stays mutually equal under truncation while *together* diverging from `get_library_health(source=<S>)`'s `tiers` — the MCP twin of H240 (and the truncated boundary of H241), completing the leanest/cross-tier × untruncated/truncated × CLI/MCP fidelity-convergence matrix on the scoped axis (`tests/test_mcp.py`, `test_get_context_bundle_budget_ladder_stays_equal_under_truncation_over_mcp`, beside the H236/H241/H235 twins). H241 ties `index` ≡ `connected` ≡ `full` over MCP *untruncated*; H236 pins only the *leanest* `index` line diverging from `get_library_health(source=<S>)` under truncation over MCP. The untested cell was the *deeper* MCP tiers under a cap: `get_context_bundle(query, budget="connected"/"full", source=<S>)`'s `_Custody:_` headline renders its `fidelity` section via `render_custody_headline` (a **different** function than the `index` line's `render_fidelity_holdings`), yet all three fold over the *same* post-cap kept set (`build_context` applies `limit` at `search_items` regardless of budget). Over a `web` scope of `full 2, partial 1, reference 1` (4 held) + one out-of-scope `arxiv` `full` (so the *unscoped* MCP audit names `{full 3, …}` — `source="web"` genuinely exercised), `get_context_bundle("topic", budget={index,connected,full}, source="web", limit=2)` (cap `2 < 4 = held`) renders three fidelity sections all *equal to each other* (the kept-2 slice, summing to `k`) and all `≠ get_library_health(source="web")`'s `tiers` `{full 2, partial 1, reference 1}` (summing to `4 > k`) — no MCP budget tier inflates the bundle-kept holdings to a source-wide claim. The drift-withholding asymmetry stays intact under truncation too (H214/H219): the `index` bundle carries no `_Custody:_`/`drift` token, the deeper tiers carry `drift unverified 2` — *also* over the kept slice. Lifting the cap (`limit=4` ≥ held) reconverges all four to the H241/H235 scoped MCP equality (the gap was exactly the cap). Test-only — all three tiers fold `get_fidelity` over the same post-cap `items` while `get_library_health(source=)` folds over the whole scoped rows, correct-by-construction. Sabotage-verified non-vacuous (folding the `connected`/`full` `_Custody:_` headline over a doubled item set breaks `index == connected == full` under the cap). The *MCP twin of H240's budget-ladder-cohesion axis* | cap 1, cap 2, cap 10 |
| H250 | **`scrolls list --fidelity <tier>` + MCP `list_scrolls(fidelity=)` — browse holdings by custody-fidelity tier (`full`/`partial`/`reference`, ADR 0097).** A real capability slice (not a convergence pin): `list`/MCP could filter by the *ledger-claim* axis (`--drift`, H54) and `facets fidelity` *counted* the holdings axis, but no surface let you *enumerate the items* in a fidelity tier — the exact query vision §3.2 names ("you hold 1,200 scrolls: 800 full…" → drill to the rows). The filter folds the same `get_fidelity`/`fidelity_tier` primitive `facets fidelity` counts with (`items.list_items` post-SQL over the already-filtered rows, ANDs with every facet, no ledger read), so the rows it returns total `facets fidelity`'s count for the tier (drill-from-the-count convergence, the holdings-axis twin of `--drift` ↔ `facets drift`); an unknown tier is a `ValueError`/exit-2 (closed vocabulary). Surfaced on `list` (CLI), `list_scrolls` (MCP, surface parity §2.6), echoed in the `--stats` scope. 11 new tests (`test_items.py` ×2 unit + ValueError, `test_cli.py` ×7: selection, drill-from-count, honest-empty, stats-scope, AND-composition, row-shows-≡-filter, unknown-tier-exit-2, `test_mcp.py` ×2: MCP selection+drill-from-count, unknown-tier ValueError). Out-of-queue: chosen over the next test-only cell (H244) as genuine capability. | cap 2, cap 7 |
| H251 | **`scrolls search --fidelity <tier>` + MCP `search_scrolls(fidelity=)` — the holdings-axis filter on the *ranked* surface, the search twin of H250's `list --fidelity`.** The capability completion the H250 steering note named first: `list`/MCP could enumerate a fidelity tier (H250) but `search` could not, so an agent ranking matches for a topic couldn't scope to "only the full-fidelity ones I can re-derive offline" (vision §3, fidelity travels with every result). The new filter keeps only the matches the library holds at one tier, derived from the same content-presence flags each hit's `fidelity` is read off — so a hit is *selected* by exactly the tier it *shows* (the row-shows-≡-filter guarantee, the search twin of H250's `test_list_row_fidelity_matches_the_fidelity_filter_value`). **Key design difference from `list --fidelity`:** `list` has no cap, so it sieves loaded rows in Python (H250); `search` applies a ranked `LIMIT`, so the tier must scope the *ranked* selection (the top-k full-fidelity matches, not the full ones among the top-k). It therefore rides a new `scrolls_fidelity` SQL UDF (registered in `items.register_facet_functions`, delegating to `fidelity_tier` so the rule keeps one home; passed the presence booleans + stage, never the body text, honoring `_PRESENCE`'s presence-not-content discipline) ANDed into both `_QUERY` (before LIMIT) and `_COUNT_QUERY` via a shared `_search_filters` helper — so `count_matches` honors it too and the `--stats` truncation denominator counts only the kept tier (never inflated by tiers it never showed, G2). ANDs with every other facet; unknown tier is a `ValueError`/exit-2 (closed vocabulary). 15 new tests (`test_search.py` ×8: selection, row-≡-filter, partitions-the-matches, ANDs-with-facets, applies-before-limit, unknown-tier-raises ×2, count_matches-honors-it; `test_cli.py` ×5: selection, hits-≡-filter, stats-scope+truncation-denominator, composes-with-source, unknown-tier-exit-2; `test_mcp.py` ×2: MCP selection+row-≡-filter, unknown-tier ValueError). Full suite 3310 passed. Out-of-queue (alongside the un-taken test-only cells H244–H249), per the H250 steering note: genuine capability over another convergence-matrix pin. | cap 1, cap 2, cap 7 |
| H243 | The dry-run's *whole top-level summary* `{imported, skipped, items, events}` (sans the dry-run-only `{dry_run, new, held}`) is byte-identical to the real import's over a bundle corrupt on *both* axes at once — within-bundle item dups *and* orphan events — the union of H233 (item counts) and H237 (whole events block) on one bundle (`tests/test_bundle.py`, `test_import_bundle_dry_run_whole_summary_matches_a_real_import_under_both_corruptions`, beside the H237/H233 twins). H233 pins the item-level `{imported, skipped}` equal under item dups (empty events); H237 pins the whole `events` block equal under orphan events (a single, distinct item). Neither exercises both axes at once, where the item-dedup path (`new_ids`/`held_ids` sets, the read-only twin of INSERT OR IGNORE) and the event-accounting path (`partition_resolvable_events` + `preview_import_events`/`import_events`) both run over the one parsed bundle. Over a `_spliced_items_and_events_bundle` whose items block repeats both a would-be-new id and an already-held id (4 raw → imported 1, skipped 3) *and* whose events block carries a dup'd anchored event on the held item (imported 2, skipped 1) beside three orphan events on two missing items (orphaned 3, orphaned_items 2), dry-run first (writes nothing — asserted via `get_item`/`item_events`) then real import into the same library; the dry-run's entire summary sans `{dry_run, new, held}` equals the real import's *and* the expected non-trivial block — so neither corruption axis silently distorts the other's accounting. Test-only — the item dedup and the event split are two independent folds over the one parsed bundle, correct-by-construction. Sabotage-verified non-vacuous (computing `item_skipped` as `len(held_ids)` instead of `len(items) − item_imported` ignores the within-bundle item dups, so the dry-run reports `skipped 1` while the real import reports `skipped 3` and the whole-summary tie fails). The *both-axes-corrupt analogue of H220's whole-summary byte-identity* | cap 9, cap 7 |
| H252 | **`scrolls verify --fidelity <tier>` — the holdings-axis *act* surface, the verify-axis twin of H250's `list --fidelity` / H251's `search --fidelity`.** A real capability slice (not a convergence pin): `list`/`search`/MCP could *enumerate/rank* a fidelity tier (H250/H251) and `verify --source`/`--drift` could *act* on the source/ledger axes (H125/H54), but no surface let a worker *re-verify exactly its holdings at one fidelity tier* — "re-check the full-fidelity scrolls I can re-derive offline" (vision §3, fidelity travels with every result, now on the act axis). A new standalone batch selection mirroring `--source`: it folds the same `get_fidelity` primitive the read surfaces count with — a pure function of stored content columns, **no ledger read** (the holdings-fact axis, vs `--drift`'s ledger-claim axis) — over the held, hash-bearing rows. **Key design subtlety vs `--source`:** every batch verify touches only hash-bearing rows (a re-fetch needs a baseline hash to diff), and fidelity ⊥ hash-bearing — a `full` capture held by `raw_text` alone carries no `content_hash`, so it lists `full` (H250) yet has no baseline and is skipped. So `verify --fidelity <tier>` re-checks `list --fidelity <tier>`'s held, *hash-bearing* subset (genuinely narrower than the listing), and a tier with no fingerprint (typically `reference`, which keeps no content) is an honest empty no-op. Closed vocabulary (`full`/`partial`/`reference`, argparse `choices` → exit 2). CLI-only: the batch verify selections have no MCP twin (MCP `verify_scroll` is single-item). 12 new tests (`test_verify_cli.py` ×11: tier selection, full-without-hash skip, list-fidelity hash-bearing convergence, reference empty no-op, ledger write, `--limit` pacing, empty library, unknown-tier exit-2, three mutual-exclusion rejections; `test_custody_convergence.py` ×1: the act ≡ read drill across all three tiers, folded into the verify-selection-family invariant). Full suite 3322 passed. Sabotage-verified non-vacuous (filtering `all_items` instead of `hash_bearing` fails 4 tests — the no-hash full leaks into the recheck). Out-of-queue (alongside the un-taken test-only cells H244–H249), per the H251 steering note: the `--fidelity`-scoped act surface. | cap 1, cap 2, cap 7 |
| H253 | **`scrolls search --drift <posture>` + MCP `search_scrolls(drift=)` — the ledger-claim-axis filter on the *ranked* surface, the drift twin of H251's `search --fidelity`.** Completes the search filter family to match `list` (`--fidelity` + `--drift` H54) and `verify` (`--fidelity` H252 + `--drift` H80): search could rank a topic's matches and scope them by the *holdings* axis but not the *ledger-claim* axis — "only the matches I have re-verified as still faithful." **Key design difference from `--fidelity`:** a fidelity tier is a pure function of an item's own content columns (the `scrolls_fidelity` UDF), but a drift posture is read from the verify ledger, so it cannot ride a content-column UDF. It instead ANDs a new `scrolls_drift` UDF over the item's *latest `custody_events` verdict* (a correlated subquery for the most-recent row, `NULL`→`unverified`) into both `_QUERY` (before LIMIT) and `_COUNT_QUERY` via `_search_filters` — so the ranked selection is scoped before the cap (not post-sieved like `list --drift` can be, having no cap) and `count_matches` honors it (the `--stats` truncation denominator counts only the kept posture, G2). `scrolls_drift` delegates to a new `custody.posture_from_status` (the status-level core factored out of `drift_posture`) so the filter and the per-hit `drift` field read one rule (row-shows-≡-filter); the per-posture totals partition the matches (drill-from-`facets drift`). ANDs with every facet incl. `--fidelity` (the two custody axes scope independently); closed vocab (`DRIFT_POSTURES`) → exit 2 / `ValueError`. 17 new tests (`test_search.py` ×9, `test_cli.py` ×6, `test_mcp.py` ×2); full suite 3339 passed. Out-of-queue, then ran the H218 checkpoint. | cap 1, cap 2, cap 7 |
| H254 | **`scrolls related --fidelity <tier>` / `--drift <posture>` + MCP `get_related_scrolls(fidelity=, drift=)` — the custody-filter family on the *relationship* surface, closing it across the last un-filtered read surface.** `related`/`graph` nodes already *carried* per-item `fidelity`/`drift` (H56) but no surface could *scope a neighbourhood* to one custody value; this adds the relationship-surface twin of `list --fidelity`/`--drift` (H250/H54) and `search --fidelity`/`--drift` (H251/H253). **Key design point:** unlike `search`'s before-LIMIT UDF (the ranked surface caps in SQL), `find_related` scores *every* candidate then caps in Python, so this is the **`list`-sieve shape**: a new `related.filter_related(hits, *, fidelity, drift)` narrows the scored hits by `hit.fidelity`/`hit.drift` (the same per-hit primitives the node shape is read off, `get_fidelity`/`drift_posture`, H56 — row-shows-≡-filter) *before* the `[:limit]` slice, so the cap returns the top-`k` neighbours *at that value*, not the matching ones among the top-`k`. `find_related`/`count_related` both thread the filters through `filter_related`, so the `--stats` denominator counts the kept set; the two axes AND; closed vocab → `ValueError`/exit 2; the CLI stats scope echoes the honored filters (`None`-pruned). 15 new tests (`test_related.py` ×11: sieve-before-cap, both-axis AND, denominator, library+CLI vocab, CLI rows/scope-echo/exit-2; `test_mcp.py` ×4: the twins + AND + vocab) + a both-axes drill fold in `test_custody_convergence.py` (`related --fidelity/--drift X` rows ≡ the value's count in the unfiltered `--stats` neighbourhood tally, anchor excluded). Docs: `docs/cli.md` `related` section + MCP tool table. Full suite 3355 passed. | cap 1, cap 2, cap 7 |
| H255 | **`scrolls maintain --fidelity <tier>` — the scheduled-maintenance *act* twin of `verify --fidelity`, closing the custody-filter family across the last un-scoped act surface (browse/rank/act/relate/maintain).** The holdings-axis sibling of `maintain --source` (H165), but narrows *less*: only the **recheck** targets the tier (`_recheck_held_items`/`maintain_coverage` filter the hash-bearing set by `get_fidelity` — the `verify --fidelity` subset H252), while the **audit/regeneration stay whole-library** — a fidelity tier spans sources, so `run_doctor`'s source semantics (`by_source` collapse, orphan/FTS skip) don't apply, and scoping the audit is deferred (the genuine design decision, not a copy of `--source`). Like `--source` the pass is **non-persisting**: `assemble_report` records the snapshot/log only when fully unscoped (`source is None and fidelity is None`), so a fidelity pass records drift events but a `null` delta — a partial-recheck pass never stamps the trend as a whole-library sweep. Closed vocab → exit 2 (argparse `choices`); composes with `--all`/`--limit`/`--no-recheck`; conflicts with `--source` (one scope axis per pass) and `--history`; CLI-only (the H252 precedent — MCP `run_maintenance` keeps `fidelity=None`). The report gains a `fidelity` scope-echo beside `source`. 13 tests in `test_maintain.py` (recheck-set ≡ `verify --fidelity`, audit-stays-whole-library vs `--source`, non-persisting/null-delta, holdings-vs-verifiable gap, reference empty no-op, composes-with-limit, offline tier coverage, two conflicts, closed vocab, fixture-invariant guard). Docs: `docs/cli.md` holdings-axis scope-twin paragraph. Full suite 3368 passed. | cap 1, cap 2, cap 7 |
| H257 | **`scrolls context <query> --fidelity <tier>` / `--drift <posture>` + MCP `get_context_bundle(fidelity=, drift=)` — the custody-filter family on the *agent context bundle*, the one progressive *read* surface it had not reached.** `build_context` already scoped its candidate set by `--source`/`--category`/`--stage`/`--tag`/`--concept` and *rendered* the custody headline but couldn't scope to a tier/posture; the slice threads `fidelity`/`drift` straight through to `search_items`/`count_matches`, which already apply the `scrolls_fidelity`/`scrolls_drift` UDFs ANDed **before** the LIMIT (the H251/H253 search primitives). So the candidate set is sieved before the cap (the `list`-sieve shape) and *everything downstream reads the kept set by construction*: the work-collapse, the budget tiers' depth, the `_Custody:_`/`_Fidelity:_` headline, the Coverage denominator, and the `full`-budget per-excerpt drift tags — the genuine subtlety (sieve runs before the budget tier nests excerpts) satisfied for free. Both axes AND; the scope-note title names the active custody value beside the facet echo; closed vocab → exit 2 (argparse `choices`) / `ValueError` (`build_context`/MCP). A *read* surface, so it gets the MCP twin (unlike the CLI-only `verify`/`maintain --fidelity`). 10 tests in `test_context.py` (keeps-only-tier/posture, sieve-before-cap, axes-AND, scope-note title, describes-kept-set at full/index budget, two `ValueError`s, CLI exit-2 closed-vocab), 3 in `test_mcp.py` (fidelity/drift twins + closed-vocab), 2 convergence invariants in `test_custody_convergence.py` (`--fidelity T` count ≡ tier T's share of the unfiltered `_Fidelity:_` line + lockstep mutation; `--drift P` count ≡ `facets drift`'s P count). Docs: `docs/cli.md` custody-scope paragraph + heading. Full suite 3383 passed. | cap 1, cap 2, cap 7, cap 10 |
| H258 | **`scrolls export bundle <query> --fidelity <tier>` / `--drift <posture>` — the custody-filter family on the *portable shareable bundle*, the family's last agent-readable surface.** `build_bundle`/`build_bundle_html` scoped by `--source`/`--category`/`--stage`/`--tag`/`--concept` (the shared `_gather_scope`) and rendered the custody headline but couldn't scope to a tier/posture; the slice threads `fidelity`/`drift` through `_gather_scope` to `count_matches`/`search_items`, which already apply the `scrolls_fidelity`/`scrolls_drift` UDFs in SQL (the H251/H253 primitives) — so the whole gathered set (items, ledger verdicts, the portable custody-events block) is sieved at the source and *everything downstream reads the kept set by construction*: the briefing prose, the lossless custody block, and the events block all describe exactly the exported slice. The bundle carries no cap (M2 completeness — every match, no top-N), so there is no before-/after-cap distinction; the sieve simply narrows the complete set. The lossless round-trip holds over the scope — `import bundle` of a custody-scoped bundle re-holds exactly the exported rows + their custody events, no unscoped leakage (the H216 round-trip narrowed to one custody value). Both axes AND; the title scope note echoes the active custody value (provenance of *what slice* was shared); closed vocab → exit 2 (argparse `choices`) / `ValueError` (`build_bundle`/`search_items`). CLI-only (no MCP twin — a portable artifact, not a structured read surface). 12 tests in `test_bundle.py` (keeps-only-tier/posture, axes-AND + AND-empties, scope-in-title, headline-describes-kept-set, the fidelity↔unfiltered-headline + drift↔`facets drift` convergence invariants, lossless round-trip under a drift scope with no leakage, two `ValueError`s, CLI exit-2 closed-vocab, end-to-end CLI fidelity run, HTML-form scope). Docs: `docs/cli.md` custody-scope paragraph + heading. Full suite 3395 passed. | cap 9, cap 4, cap 1 |
| H259 | **`scrolls export items --fidelity <tier>` / `--drift <posture>` — the custody-filter family on the *whole-library JSONL backup*, the backup-path sibling of H258.** `export items` (the lossless JSONL backup, ADR 0082) scoped by `--source`/`--category`/`--tag` but carried no custody-axis scope; the missing capability was "back up only my full-fidelity holdings" / "ship only the drifted rows for a recapture handoff." The simplest member of the family: a pure thread-through of two args through the parser → `_cmd_export_items` → `list_items`, which **already accepts `fidelity`/`drift`** (the `list --fidelity`/`--drift` primitives, H250/H54) — no new sieve. The post-SQL sieve preserves saved order, so the scoped JSONL is the **byte-identical subset** of the unscoped backup for those rows (`dump_items_export` over the kept rows). Both axes AND; closed vocab → exit 2 (argparse `choices`); the `_cmd_export_items` programmatic path catches the `list_items` `ValueError` → JSON-on-stderr exit 1 (the `_cmd_export_bundle` precedent). The lossless round-trip holds over the scope — `import items` of a custody-scoped backup re-holds exactly the exported rows, no leakage of the filtered-out tiers (the H216 round-trip narrowed to one custody value). CLI-only (no MCP twin — `export items` is a portable backup artifact, not a structured read surface; the H258 precedent). 8 tests in `test_cli.py` (fidelity/drift scope, byte-identical-subset, axes-AND + honest-empty, custody-scoped round-trip, two exit-2 closed-vocab, programmatic exit-1). Docs: `docs/cli.md` custody-scope paragraph + heading. Full suite 3403 passed. | cap 9, cap 4, cap 1 |
| H260 | **`scrolls export events --fidelity <tier>` / `--drift <posture>` — the custody-filter family on the *whole-library custody-ledger backup*, the family's **last** surface and the custody-sibling of H259.** `export events` (the verify-ledger JSONL backup, H72) resolves its item set via `list_items(source/category/tag)` then exports *their* events; the slice threads `fidelity`/`drift` into that same `list_items` call (which already accepts both, H250/H54) — like H259, a pure thread-through, no new sieve. The one design decision was resolved as an **item-set sieve** (not a per-row event filter): the axes narrow the item resolution, then the in-scope items' *whole* ledger travels — exactly how `--source` scopes events by item — so `--drift drifted` ships a moved item's entire custody history (earlier `unchanged` rows included), the full proof of *when* a source moved for a recapture handoff. Composes with `--since` (item-set sieve, then time window) and the durable facets; both axes AND; honest empty intersection → exit 0/empty doc; closed vocab → exit 2 (argparse `choices`); the `_cmd_export_events` programmatic path catches the `list_items` `ValueError` → exit 1 (after the existing `--since` exit-2 validation). CLI-only (the `export items`/`export bundle` backup-artifact precedent). Drift-scoped backup round-trips losslessly into a fresh library with no leakage. 8 tests in `test_cli.py` (fidelity scope, item-set-sieve/whole-ledger drift, axes-AND + honest-empty, composes-with-`--since`, custody-scoped round-trip, two exit-2 closed-vocab, programmatic exit-1). Docs: `docs/cli.md` custody-scope paragraph + heading + example. Full suite 3411 passed. **Closes the custody-filter family across every read/act/export surface; new lead = work-level custody consolidation (H261–H263).** | cap 9, cap 4, cap 1 |
| H261 | **`scrolls works` reports a per-work *aggregate custody posture* — the consolidation-level custody verdict, the new-custody-shape lead (vision §3.5, custody-vision §2.7).** Each `Work` already exposed its representations' per-item `fidelity`/`drift`/`last_checked`, but the payload answered no *work-level* custody question. The slice adds a `custody` block per work in `works.to_payload` — `{best_fidelity, safest_drift, safely_held}` from a new shared `works.work_custody(representations, verdicts)` fold over the same per-rep `fidelity`/`drift` the entries carry (**no schema change, no extra ledger read**). `best_fidelity`/`safest_drift` are the best each axis offers anywhere in the cluster, by the canonical `FIDELITY_TIERS`/`DRIFT_POSTURES` orders (picked independently). `safely_held` is the **strong** form resolving the one judgement the spec flagged: `true` iff **∃ a representation that is `full` *and* drift ∈ `custody.SAFE_DRIFT_POSTURES` ({verified, unverified})** — an unmoved, fully re-derivable copy exists; a `partial` capture can't fully re-derive (excluded even when verified), and `drifted`/`rotted`/`error` (the source moved, or we couldn't confirm) are not safe — both must hold on the *same* rep (a drifted full preprint + a verified partial record is **not** safely held). New `SAFE_DRIFT_POSTURES` constant lives in `custody.py` beside `DRIFT_POSTURES`. Rides the MCP `get_works` twin for free (shared `to_payload`). The shared `work_custody` helper is the primitive H262's `works --fidelity`/`--drift` filter and H263's at-risk-works signal reuse. 9 tests (`test_works.py` ×7: the block shape, the strong-form `partial`-not-safe judgement, drifted-full-not-safe, unverified-full-is-safe, best/safest-pick-across-reps, error-not-safe, shared-helper parity; `test_works.py` ×1 CLI end-to-end; `test_mcp.py` ×1 MCP parity). Docs: `docs/cli.md` per-work custody paragraph + updated examples + MCP table. Full suite 3420 passed. **First slice of the work-level custody consolidation theme; H262 (the `works` custody filter) follows.** | cap 1, cap 2, cap 5 |
| H262 | **`scrolls works --fidelity <tier>` / `--drift <posture>` + the MCP `get_works(fidelity=, drift=)` twin — the custody-filter family on the *consolidation* surface (the work cluster the family never reached, H250–H260).** The lift semantics, settled as the **contains** read: a work is kept *whole* (every representation still travels) iff it **has a representation** at the custody value — since a work is a set of forms and "show me the works with a drifted rep" wants the work *and its siblings* (to see whether a safe one exists), not the lone matching form — so `--drift drifted` surfaces *the works needing a recapture decision*, intact. The two axes AND **on the same representation** (the ∃-lift of `filter_related`'s "no neighbour is *both*", H254): `--fidelity full --drift drifted` keeps a work iff some rep is *both* (a fully-held copy whose source moved), not merely some full rep *and* some — possibly different — drifted rep (the rejected "Option A", pinned by `--fidelity reference --drift drifted` being empty over a work with both values in different reps). New shared `works.filter_works(works, verdicts, *, fidelity, drift)` sieve, pure over the already-clustered works (`works_over`/`works_for_item` → sieve → `to_payload`): whole works kept (no rep pruned), commutes with the `min_representations` floor, `stats.custody` partitions the reported set with **no change to `to_payload`**. Rides the `scope` echo (pruned when unset, G2); composes with the per-item `ref` lens. Closed vocab → exit 2 (CLI `choices=`) / `ValueError` (MCP). **No schema change, no extra ledger read.** 18 tests: 7 unit + 6 CLI (`test_works.py`) + 5 MCP (`test_mcp.py`, incl. CLI↔MCP parity). Docs: `docs/cli.md` consolidation-filter paragraph + heading + MCP table row. Full suite 3438 passed. **Second consolidation slice; next lead H263 (the `safely_held == false` at-risk alarm).** | cap 1, cap 2, cap 7 |
| H263 | **The *at-risk-works* consolidation alarm on `doctor` + `maintain` + MCP `get_library_health` — closing the consolidation theme (H261–H263).** A work is **at risk** when **no** representation is safely held (the H261 `work_custody` `safely_held == False` set — every copy degraded or moved, no unmoved full form anywhere); the consolidation-level analogue of the per-source weakest-source `attention` flag, and a sharper alarm than the per-item drift count (a sibling rep still full+verified makes an item's drift survivable; a *work* with no safe rep is a real loss). New shared `works.at_risk_signal(works, verdicts)` — a **pure fold over the H261 aggregate** (no schema change, no extra ledger read) — returns `{total, at_risk, most_at_risk}`; `most_at_risk` is the single lowest-custody-ceiling work (worst `best_fidelity`, then worst `safest_drift`, then `doi`) with a self-describing `reason` and **no fabricated `command`** (no whole-library recapture act exists — the orphan/`suggested` discipline). Surfaced on `doctor`'s `custody.works` (report view, never `issues`/exit code; the **third non-source-attributable check** — a work spans sources, so `--source` audits fragment works → `status: "skipped"`, beside orphan/FTS), `maintain`'s `at_risk_works` (live-pass only), and `get_library_health` for free (the `**custody` spread). Decisions: skip-under-scope (matches orphan/FTS, avoids a G1 "0 at risk" trap), `min_representations=2` (consolidation needs siblings), no command. 18 tests (6 unit `test_works.py`, 7 `test_doctor.py`, 4 `test_maintain.py`, 1 `test_mcp.py`). Docs: `docs/cli.md` doctor + maintain + MCP-table. Full suite 3456 passed. **Closes the consolidation theme; next lead H264 (the readable work-level at-risk `_Attention:_` line on the briefings).** | cap 1, cap 5, cap 8 |
| H264 | **The readable work-level `_At-risk work:_` line on the `export bundle` + `scrolls context` briefings — the consolidation-level counterpart of the per-source weakest-source `_Attention:_` line (H159).** H263 put the at-risk-works alarm on every JSON read surface; H264 distils the *same* `works.at_risk_signal` fold into a readable line — ``_At-risk work: `<doi>` — no representation is both full and unmoved (best held <tier>, safest drift <posture>); N work(s) at risk._`` — naming the work `most_at_risk` names and reusing its `reason` verbatim, so the briefing line and `doctor`'s `custody.works`/`maintain`/`get_library_health` converge by construction. New shared `works.render_at_risk_works(items, verdicts)` (clusters via `works_over`, folds `at_risk_signal`; `[line, ""]` or `[]` on honest absence). Decisions: (1) helper lives in `works.py` beside `at_risk_signal` (not `custody.py` — `works` imports `custody`, so `custody.render_at_risk_works` calling `at_risk_signal` is a cycle; home follows the primitive); (2) lean scope — `context` clusters the **uncollapsed** matched scope (`scope_items`, kept + folded reps) so a folded full+verified sibling correctly marks a work safely held, not the lone kept canonical (ADR 0101 collapse); (3) placed directly beneath the source `_Attention:_` line (the two loss pointers grouped), gated `connected`+ on `context`, always present on the bundle. 16 tests (4 unit `test_works.py`, 6 `test_bundle.py`, 6 `test_context.py` incl. MCP parity). Docs: `docs/cli.md` `_At-risk work:_` paragraph. Full suite 3472 passed. **Completes the readable side of the consolidation alarm; next lead H265 (`scrolls works --at-risk`).** | cap 1, cap 9, cap 10 |
| H265 | **`scrolls works --at-risk` + the MCP `get_works(at_risk=True)` twin — browse only the works no representation safely holds, the at-risk-works alarm (H263) as a *browse predicate*.** A genuinely new predicate, **not** a `--fidelity`/`--drift` value: "no rep is safely held" is the **negation of ∃(full ∧ unmoved)** (the consolidation analogue of `list --drift`). Extends the shared `works.filter_works` with an `at_risk` boolean keeping the works whose `work_custody` `safely_held == False` — the *same* set `at_risk_signal` counts (one rule, three reads: the aggregate `custody` block H261, the JSON alarm H263, this browse) — gated behind the `not at_risk` early-exit so the unfiltered path reads no ledger and stays the H262 identity. **ANDs** with `--fidelity`/`--drift`: `--at-risk --fidelity full` surfaces the **recapture candidates** whose content is in hand but whose work is at risk (the full copy drifted). Boolean predicate → rides the `scope` echo via `or None` (present only when set, G2); composes with the per-item `ref` lens; `stats.custody` partitions the kept set (the H262 sieve shape, before-the-cut). 12 tests: 5 unit `filter_works(at_risk=)` (`test_works.py` — keeps-unsafe, `at_risk_signal`-set parity, whole-work, ANDs-with-filters, false-is-identity), 4 CLI (`test_works.py` — browse, scope-omit-when-unset, ANDs, ref-lens), 3 MCP (`test_mcp.py` — browse, ANDs, CLI↔MCP parity). Docs: `docs/cli.md` `--at-risk` paragraph + heading + MCP table row. Full suite 3484 passed. **Closes the consolidation theme's browse leg — work-level custody is now readable (H261), filterable (H262), alarmed (H263), readable-briefing (H264), and browsable (H265); next lead H266 (the works-stats at-risk summary).** | cap 1, cap 7 |
| H266 | **`scrolls works` stats carry a scope-level at-risk-works summary at `stats.custody.at_risk` (CLI + MCP `get_works`) — the works-surface counterpart of the `doctor`/`maintain`/`get_library_health` at-risk-works alarm (H263), closing the consolidation theme's point-in-time axes.** Adds the whole `at_risk_signal` fold `{total, at_risk, most_at_risk}` over the **reported** (post-filter) works to the works `stats.custody` block, beside `attention` in the same loss-summary family (`attention` is itself a scope-level custody-loss summary, a source flag not a rep tally — the precedent the spec named). Field-identical to `doctor`'s `custody.works` (minus `status`), so it converges with it / MCP `get_library_health` **by construction** over the unscoped default 2+ clustering (pinned on both CLI and MCP). A pure fold over the reported works → composes with the H262/H265 filters (under `--at-risk` `at_risk == total`; under `--fidelity full` the at-risk subset of the kept works), `at_risk.total == stats.works` by construction, honest zeroed fold on an empty scope. **No schema change beyond stats, no extra ledger read** (reuses the `verdicts` the per-rep `drift` folds), riding MCP `get_works` for free. The two existing `stats.custody` convergence tests + the `test_works_stats_custody_agrees_with_its_representations` invariant gained the works-only `at_risk` member (the shared `_tally_rows` per-rep fold, used by the no-`at_risk` browse surfaces, left untouched). 10 tests (7 `test_works.py`, 2 `test_mcp.py`) + 1 convergence-test update. Docs: `docs/cli.md` `stats.custody.at_risk` paragraph + MCP table row. Full suite 3493 passed. **Closes the consolidation theme's point-in-time axes; next lead H267 (the at-risk-works count in the `maintain` snapshot/trend — consolidation loss over time).** | cap 1, cap 2, cap 7 |
| H267 | **The at-risk-works count rides the `maintain` custody snapshot, its cross-run `delta`, and `--history`/`--trend` (and `status`'s `custody.at_risk`) — the consolidation-loss-*over-time* axis, the at-risk counterpart of recording recheck `coverage` in the snapshot (H115).** Adds an `at_risk` scalar to `custody_snapshot` (read from the doctor report's `custody.works.at_risk`, degrade-safe `0` for an absent `works` block or a `status: skipped` `--source` pass), folds it into the cross-run `delta` with the other scalars' first-run/missing-axis tolerance, and adds the `at_risk_change` net-delta axis to `compute_trend`. So an operator reading `--trend` sees "2 → 4 works at risk" without re-auditing each run. **Decisions:** (1) store the **scalar count**, not the whole `{total, at_risk, most_at_risk}` block (the snapshot is a comparable-scalars record; `most_at_risk`'s named work is not a quantity a delta can difference — the live `at_risk_works` block carries it, live-pass only); (2) `at_risk_change` is a **reported axis, never a `posture` trigger** (the `coverage_change`/`stale_change` precedent) — it re-views the `fidelity`/`drift` the `score`/`drift_change` already move on, so folding it in double-counts. `custody_snapshot` is shared with `scrolls status`, so `status` gains `custody.at_risk` for free (the H38/H103 "status can't disagree with a snapshot" convergence). Only the fully-unscoped persisting pass records it (a `--source`/`--fidelity` triage is non-persisting, null delta — H165/H255). The H143 trend≡telescoped-deltas invariant gained the `at_risk` axis. 14 tests (11 `test_maintain.py`, 3 `test_custody_convergence.py`). Docs: `docs/cli.md` trend-layer paragraph + `custody.works`/`status` field rows + every `status`/`maintain`/`--trend` example JSON. Full suite 3504 passed. **Opens the consolidation trend-over-time leg; next lead H268 (the readable `_At-risk works: N (▲M)_` line).** | cap 1, maintenance framing |
| H268 | **The at-risk-works count is readable on the `maintain` report (`_At-risk works: N (▲M since last run)._`) and the `--trend` summary (`_At-risk works: N (▲M over K runs)._`) — the readable counterpart of H267's snapshot scalar and the trend twin of the at-risk `_At-risk work:_` briefing line (H264).** New shared `maintain.at_risk_headline(count, change, *, span="since last run")` — a pure formatter over two scalars the report/trend already carry: `▲M` a rise (worse), `▼M` a fall (better), `0` the explicit `no change`, and a `None` change the bare `_At-risk works: N._` — degrade-safe *exactly* when there is no baseline (first run / scoped non-persisting `--source`/`--fidelity` pass with null `delta` / `<2`-run trend; the H267 honesty, ADR 0082). The report reads `current["at_risk"]` + `delta["at_risk"]["change"]`; the trend reads the window's last snapshot + `at_risk_change` (the score-`first→last` shape). **Decisive consequence:** unlike the snapshot-only `headline` (position-independent), it embeds the delta's change → **run-position-dependent**, so the MCP↔CLI `run_maintenance` convergence test strips it beside `delta`/`recorded_at` in `_audit_fields` (documented). Rides MCP for free (`assemble_report`/`compute_trend`, pinned by the existing full-envelope `test_get_maintenance_history_matches_cli_maintain_history`). 14 tests in `tests/test_maintain.py` (5 unit, 3 report, 4 trend) + the `_audit_fields` strip + 2 MCP shape assertions. Docs: `docs/cli.md` report + `--trend` paragraphs, 4 console examples, MCP shape list. End-to-end verified (bare → ▲1 → ▼1). Full suite 3516 passed. **Gives the consolidation-loss trend a readable line; last leg H269 (the at-risk alarm on the compiled `library/index.md`).** | cap 1, maintenance framing |
| H269 | **The compiled landing `library/index.md` carries the at-risk-works alarm — the consolidation alarm on the *static compiled* surface, the at-risk counterpart of the whole-library `_Custody:_` headline on `index.md` (H96).** The per-source weakest-source picture rode the compiled pages (H184), but the *consolidation* alarm — "N works at risk" — appeared only on the agent JSON/briefing surfaces, never the human-browsable compiled library. The slice threads an optional `at_risk_lines` through the shared `_custody_scope_block`, spliced beneath the headline and grouped with the source `_Attention:_` line (above `_Refresh:_`/`_By source:_` — the `export bundle`/`context` order), folded by the shared `works.render_at_risk_works` over the rendered library so it names the same work `doctor`'s `custody.works`/`index.md` JSON does. **Decisive design choice:** `index.md`-**only**, not every group page (the source `_Attention:_`/`_Refresh:_` precedent) — the consolidation alarm is **non-source-attributable** (a work spans sources, so a scoped group page fragments its reps into single-rep clusters dropped by the `min_representations` floor, and could not converge with the library-wide audit), exactly why `doctor`'s `custody.works` is skipped under `--source`. Sits **inside** the `@generated` sentinel fence (M1, ADR 0102) — a recompile refreshes it (a recapture clears it), a hand annotation outside survives; honest no-op (no line) when no multi-rep work is at risk. Converges with `doctor`'s `custody.works` over the whole rendered library by construction (the parse-it-back tie H97). 7 tests (6 `tests/test_kb.py` — carries-the-line, render_at_risk_works convergence, grouped-with-the-loss-pointers `_Custody:`<`_Attention:`<`_At-risk work:`<`_Refresh:`<`_By source:_`, honest no-op, group-pages-omit, refresh-safe-recapture-clears; 1 `tests/test_custody_convergence.py` — doctor parse-it-back + mutation-in-lockstep). Docs: `docs/cli.md` compiled-index at-risk paragraph. End-to-end verified (line renders → recapture clears, converges with `doctor`). Full suite 3523 passed. **Closes the consolidation theme across every read/filter/alarm/browse/stats/trend/briefing *and* compiled surface; next leads H270 (per-work custody marker on compiled `works.md`) and H271 (the at-risk line on the HTML bundle form).** | cap 1, cap 2, cap 6 |
| H270 | **The compiled `works.md` rollup carries a per-work `_Custody:_` marker beneath each `## <doi>` section's resolver line — the works-page analogue of the per-item `· <fidelity> · <drift>` list-page marker (H89) and the last un-marked compiled surface for work-level custody.** `works.md` rendered each work's resolver link, rep count, and per-rep bullets but carried no work-level custody verdict — a human browsing the rollup couldn't see safely-held-vs-at-risk without `scrolls works` JSON. Emits one line per section — ``_Custody: best held <tier>, safest drift <posture> — safely held._`` (or ``— at risk._`` when no rep is both `full` and unmoved) — folded by the new shared `works.render_work_custody_marker` over the H261 `work_custody` dict. **Decisive choice:** the renderer takes the `work_custody` *dict* (not the reps), so the compiled marker and `scrolls works`'s per-work `custody` block are two renders of the **same fold** — convergent by construction (the H97 parse-it-back tie at the work level). Threaded by passing the `verdicts` ledger `compile_kb` already loads into `_write_works_page` (the H269 precedent) — no schema change, no extra ledger read. Inside the `@generated` fence (M1, ADR 0102) so a recompile refreshes it (a recapture flips `at risk`→`safely held`), a hand annotation outside survives. 3 tests (2 `tests/test_kb.py` — renders on at-risk + safely-held sections in position, refresh-safe recapture flip with outside-fence note kept; 1 `tests/test_custody_convergence.py` — each section's marker byte-identical to `render_work_custody_marker(works['custody'])`, agrees with `doctor`'s `custody.works.most_at_risk`, mutation-in-lockstep) + updated the scope-headline-omission test (the per-work marker carries no `scroll(s)`) and the `example-works-page` pinned doc block. Docs: `docs/cli.md` + `docs/library-format.md` works-page sections. End-to-end verified (full+ref → `— safely held._`; two-ref → `— at risk._`). Full suite 3526 passed. **Closes the consolidation theme across read/filter/alarm/browse/stats/trend/briefing/compiled-index *and* the compiled works rollup; last adjacent read H271 (the at-risk line on the HTML bundle form).** | cap 1, cap 2, cap 6 |
| H271 | **The `_At-risk work:_` line rides the *HTML* `export bundle` form too — the HTML twin of H264's Markdown at-risk line, closing the bundle's two-form parity for the consolidation alarm.** H264 added the readable work-level `_At-risk work:_` line to the Markdown bundle (`build_bundle`) but not its HTML twin (`build_bundle_html`): the HTML form rendered the custody headline, the source `custody-attention` pointer, `custody-refresh`, and the `custody-by-source` map but no work-level at-risk paragraph — so the shareable HTML briefing silently dropped the alarm the Markdown form carries. Adds a red `<p class="custody-at-risk">` (a new CSS rule beside `.custody-attention`/`.custody-refresh`) beneath the headline, grouped with the source `_attention_html` line and above `_refresh_html` (the Markdown order), distilled from the *same* `works.at_risk_signal` over the same lean-scope `works_over` fold so it names the same work the Markdown line / `doctor`'s `custody.works` do (the `_attention_html`↔`render_custody_attention` HTML-twin precedent, H39). Honest absence (no paragraph) when no multi-rep work in scope is at risk; export-only, never in the lossless JSONL fence. The new shared `_at_risk_html` helper folds `at_risk_signal(works_over(items), verdicts)` — no schema change, no extra ledger read (the verdicts the bundle already loads). 4 tests (`tests/test_bundle.py` — carries-the-line + position, convergence with the Markdown form / `at_risk_signal`, honest no-op when no work at risk, omitted for single-rep/empty scope). Docs: `docs/cli.md` H264 paragraph extended with the HTML twin. End-to-end verified (line renders inside the body in position, converges byte-for-byte with the Markdown twin). Full suite 3530 passed. **Closes the consolidation theme across *every* read/filter/alarm/browse/stats/trend/briefing/compiled surface, both bundle forms included; the queue holds only de-prioritized guard cells (H244–H249) and the H256 buffer-refresh checkpoint.** | cap 9, cap 1 |

---

## 3-day plan — 2026-06-21 → 2026-06-24

Forward-looking (re-derived at this H218 checkpoint, 2026-06-21). Each day ends
on a committed, tested, clean stopping point; slips roll forward.

- **Day 1 (2026-06-21):** **Done.** Shipped **H253** (`scrolls search --drift
  <posture>` + MCP `search_scrolls(drift=)`, the ledger-claim-axis twin of
  `search --fidelity`, completing the custody-filter family across both per-item
  axes and all three verbs), then ran the **overdue H218 checkpoint**: refreshed
  the snapshot/plans to absolute dates, re-grounded the horizon, and compacted
  ~850 lines of re-accreted changelog prose (maintenance-rule §6).
- **Day 2 (pulled forward into 2026-06-21):** **Done.** Shipped **H254** —
  `scrolls related --fidelity <tier>` / `--drift <posture>` + the MCP
  `get_related_scrolls` twins, the custody-filter family on the *relationship*
  surface (the last un-filtered read surface). The `list`-sieve path: a new
  `related.filter_related` narrows `scored_related(...)` by the per-hit
  `fidelity`/`drift` *before* the `[:limit]` slice, so the cap returns the
  top-`k` neighbours *at that value*; closed vocab → exit 2; both axes AND;
  `--stats` count honors it. 15 tests + a both-axes custody-convergence drill
  fold; full suite 3355 passed.
- **Day 3 (pulled forward into 2026-06-21):** **Done.** Shipped **H255** —
  `scrolls maintain --fidelity <tier>`, the scheduled-maintenance act twin of
  `verify --fidelity`, closing the custody-filter family across the last un-scoped
  act surface. Resolved the audit-scoping decision exactly as scoped: only the
  recheck narrows to the tier (the `verify --fidelity` hash-bearing set via
  `get_fidelity`), audit/regenerate stay whole-library with a null delta (the
  non-persisting triage posture), `assemble_report` records only when fully
  unscoped. Closed vocab → exit 2; conflicts with `--source`/`--history`; CLI-only.
  13 tests; full suite 3368 passed.
- **Day 4 (pulled forward into 2026-06-21):** **Done.** Shipped **H257** —
  `scrolls context --fidelity`/`--drift` (+ the MCP `get_context_bundle` twin),
  the custody-filter family on the *agent context bundle* (the one progressive
  read surface it had not reached): the two axes thread straight through to
  `search_items`/`count_matches`, reusing the H251/H253 before-cap UDF sieve, so
  the bundle covers the top matches *at that custody value* and the rendered
  `_Fidelity:_`/`_Custody:_` headline, Coverage denominator, and per-excerpt drift
  tags all describe the kept set. 15 tests (10 `test_context.py`, 3 `test_mcp.py`,
  2 convergence); full suite 3383 passed.
- **Day 5 (pulled forward into 2026-06-21):** **Done.** Shipped **H258** —
  `scrolls export bundle --fidelity`/`--drift`, the custody-filter family on the
  *portable shareable bundle* (the family's last agent-readable surface): the two
  axes thread through `_gather_scope` into the same `search_items`/`count_matches`
  sieve, so the briefing prose, the lossless custody block, and the custody-events
  block all describe exactly the exported slice, and `import bundle` of a
  custody-scoped bundle re-holds exactly those rows (the H216 round-trip under a
  custody scope). 12 tests in `test_bundle.py`; full suite 3395 passed.
- **Day 6 (pulled forward into 2026-06-21):** **Done.** Shipped **H259** then
  **H260** — `export items` then `export events --fidelity`/`--drift`, the two
  whole-library backups, **closing the custody-filter family across every read,
  act, and export surface.** H260 resolved its one design choice as an *item-set
  sieve* (the in-scope items' whole ledger travels, like `--source`), so a
  `--drift drifted` backup carries the moved items' full custody history for a
  recapture handoff. 8 tests; full suite 3411 passed.
- **Done (2026-06-21 → 2026-06-22):** the **work-level custody consolidation**
  theme's point-in-time axes — **H261** (per-work aggregate custody posture),
  **H262** (`works --fidelity`/`--drift` filter), **H263** (the at-risk-works
  doctor/maintain alarm), **H264** (readable `_At-risk work:_` briefing line),
  **H265** (`works --at-risk` browse), **H266** (works-stats at-risk summary) — and
  **H267 (this run)** opened the *trend-over-time* leg (the at-risk count in the
  `maintain` snapshot/delta/`--trend` + `status`'s `custody.at_risk`).
- **Next (2026-06-22 → 2026-06-24):** **H268** — the readable `_At-risk works:
  N (▲M since last run)_` line on the `maintain` report and `--trend` summary (the
  readable counterpart of H267's scalar), then **H269** — the at-risk alarm on the
  compiled `library/index.md`. The **H256 buffer-refresh checkpoint** is due
  ~2026-06-22 (fold H261–H267 into the compact ledger, prune, re-derive plans).

---

## Week plan (more tentative) — through 2026-06-28

- **Closed this past week:** the **budget/tier custody honesty** matrix
  (H212–H249 — the leanest `index` `_Fidelity:_` line and its whole cross-tier ×
  CLI/MCP × scoped/unscoped × untruncated/truncated convergence) and — now fully —
  the **custody-filter family**: the per-item *holdings* and *ledger-claim* axes
  are browsable/rankable/actable *and scopable on the relationship surface*:
  `list`/`search`/`verify`/`related --fidelity` H250/H251/H252/H254 and
  `list`/`search`/`verify`/`related --drift` H54/H253/H80/H254. Both per-item
  custody axes are now filterable on **every** read and act surface; **H255 (this
  run) closed the last un-scoped *act* surface** (`maintain --fidelity`), so the
  family spans browse/rank/act/relate/maintain end to end.
- **The custody-filter family is *complete*.** With H259 (`export items`) and
  H260 (`export events`) **both shipped this run**, the per-item *holdings* and
  *ledger-claim* axes are scopable on **every** read, act, and export surface —
  browse/rank/act/relate/maintain, both agent-readable bundles (`context` H257,
  `export bundle` H258), and both whole-library backups. There is no un-filtered
  custody surface left.
- **This week's horizon — work-level custody consolidation (vision §3.5).** The
  next custody *shape* is custody at the level of a *work* (the canonical cluster
  of representations, ADR 0095/0096), not the item. `works` already carries each
  representation's `fidelity`/`drift` but answers no work-level "is this work
  safely held?" question. **H261** (per-work aggregate custody posture) is the
  lead, **H262** (`works --fidelity`/`--drift` filter — the family on the
  consolidation surface) and **H263** ("at-risk works" doctor/maintain signal)
  follow — all pure folds over data `works` already computes, no schema change,
  each a genuinely new custody capability rather than a filter replay.
- The **budget/tier convergence guard cells H244–H249** remain valid regression
  guards but are explicitly **de-prioritized** — take a capability first; close a
  guard only when no capability is ready, and prefer closing one over appending
  more of the same combinatorial shape.
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
| Custody-filter family (`--fidelity`/`--drift` browse/rank/act) | cap 1/2/7 | post-MVP |

The two obsidian-second-brain adoptions (M1 refresh-safe regeneration, M2
completeness invariant) were intentionally first in the queue: they are the
decision-grade, custody-deepening slices, and everything later reads cleaner
once raw is sacred and absence is honest.
