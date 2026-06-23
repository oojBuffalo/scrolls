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
- **New theme opened — conflict-on-import is surfaced, never silently swallowed
  (custody §2.4; the obsidian reconcile adoption *detect, surface, don't rewrite*).**
  The H256 checkpoint (this run) re-derived the next capability theme: with the
  per-item and consolidation custody surfaces closed, the un-worked custody shape was
  the **import boundary**, where two libraries' captures collide. `import items` used
  `INSERT OR IGNORE` keyed on id alone, so a re-import of a held id with *different*
  captured content was dropped into an opaque `skipped` count — a real custody blind
  spot (a divergence silently lost). **H272 (this run) closed it for the lossless
  whole-library importer** — `import items` now partitions every skip on the
  `content_hash` (the same captured-content fingerprint the verify ledger drifts on)
  into `unchanged` (idempotent re-import) and `conflict` (the incoming copy disagrees
  with the held one), surfacing the diverging ids in a structured, uncapped
  `conflicts` field **and** a loud bounded stderr warning, while still **never
  overwriting** the held copy (raw is sacred; a conflict is a *recorded, surfaced*
  event, not an overwrite). The shared `items.merge_item` primitive (`"imported"` /
  `"unchanged"` / `"conflict"`, a content-hash compare on the INSERT-OR-IGNORE skip)
  and the cli `_merge_items`/`_warn_conflicts` helpers are the home the bundle import
  (H273) reuses; `skipped == unchanged + conflict` is the coherence invariant, and a
  *derived*-field-only difference (title/category) is `unchanged`, not a conflict (the
  signal is content custody, not every column). **No schema change, no network** — a
  deterministic content-hash compare. 5 tests (`tests/test_cli.py`: idempotent-is-
  unchanged, title-edit-is-unchanged, surfaces-a-conflict + stderr warning + held-copy-
  preserved, mixed-batch partition + `skipped==unchanged+conflict`, `merge_item` unit).
  Docs: `docs/cli.md` import-items conflict table + console example, `docs/reconciliation.md`
  "Shipped: conflict-on-import detection". **H273 (this run) lifted the same partition to
  the bundle importer** — `import bundle` now routes its items through `_merge_items` (the
  live conflict surface + `_warn_conflicts` stderr) and its `--dry-run` through the new
  read-only twin `_preview_merge_items`, which **predicts** the conflict set the live merge
  would surface (the H245-style "predict the write effect" closure, on the conflict axis).
  The decisive design choice the slice resolved is the **within-batch simulation**: the live
  `merge_item` does INSERT OR IGNORE so a bundle that *repeats* an id sees its own prior
  insert (first occurrence kept, a later one conflicts against it); the dry-run writes
  nothing, so `_preview_merge_items` records the first occurrence's `content_hash` in a
  `kept_hash` map to classify within-batch dups identically — and the repeated id rides
  `new` (library-absent) *and* `conflicts` (the bundle disagrees with itself) at once,
  keeping `new`/`held` library-relative (H239/H245). The live≡preview convergence holds:
  both paths grow the same `unchanged`/`conflict`/`conflicts` fields, pinned over a mixed
  bundle and the within-bundle-dup edge. **No schema change, no network** — a deterministic
  content-hash compare. 4 tests in `tests/test_bundle.py` (live conflict surfaced +
  held-copy-preserved; dry-run predicts the conflict set + writes nothing; live≡preview
  under a mixed conflicting bundle; within-bundle-dup parity on both paths) + 2 updated
  convergence assertions. Docs: `docs/cli.md` bundle conflict partition + dry-run prediction
  + key table, `docs/reconciliation.md` "both lossless importers". **H274 (2026-06-22) closed
  the theme's *detection* leg** — a surfaced conflict is now a **recorded custody event** (ADR
  0104): each divergence is appended to the ledger as a typed `conflict` event on the held item
  (`prior_hash` = the kept held copy, `observed_hash` = the incoming capture that disagreed,
  stamped at import time), queryable via `scrolls history <id> --status conflict`. The decisive
  design choice: a conflict is a **distinct provenance-of-divergence axis**, *not* a verify-drift
  — the drift axis means "the live *source* moved" (re-capture through the adapter, ADR 0098),
  whereas a conflict involves no source re-capture, only a peer disagreeing, so claiming
  `drifted` would be fabrication (the M2 honesty). `latest_events` now reads `MAX(id)` per item
  over the verify verdicts only, so a conflict event lives in the ledger and on the `history`
  timeline yet **never** enters the drift posture — `doctor`'s `custody.drift`, `list/search
  --drift`, the scope headlines, the `works` aggregate, and `maintain` are all unaffected; an
  item with only a conflict reads `unverified`; a conflict appended after a real `drifted`
  verdict never masks it. The pure `custody.conflict_event(...)` (reusing the verify-event field
  semantics, so every serializer + the export/import round-trip carry it unchanged),
  `CONFLICT_STATUS`/`LEDGER_STATUSES`, and the recording in the **shared `cli._merge_items`** (both
  lossless importers; the read-only `_preview_merge_items` records nothing) are the home a future
  `reconcile` (H276) acts on. **No schema change, no network.** 8 tests (`tests/test_custody.py`
  ×4 incl. the drift-isolation invariant, `tests/test_cli.py` ×2 incl. `doctor`'s drift block
  unaffected, `tests/test_bundle.py` ×2 incl. the dry-run records nothing). Docs: ADR 0104,
  `docs/reconciliation.md` "Shipped: a conflict is a recorded custody event", `docs/cli.md`.
  **With H274 the conflict-on-import *detection* leg is closed.** **H275 (2026-06-22)
  opened the theme's *read* leg** — a `doctor` scope-level **conflict aggregate**
  (`custody.conflicts`), the read-aggregate sibling of `custody.drift` over the other
  provenance-of-divergence axis (ADR 0104's first deferred read). H274 records each
  conflict as a per-item ledger event queryable via `scrolls history <id> --status
  conflict`, but there was **no library-scope view** — an operator who merged several
  peer bundles could not ask "how many of my held items carry an unresolved import
  conflict, and which?" without scanning every item's history. `doctor` now folds the
  latest recorded import-`conflict` event per held item into `custody.conflicts`
  `{basis, as_of, items, events}` (the new pure primitives `custody.latest_conflict_events`
  — MAX(id) per item over the `conflict` rows, the conflict-axis sibling of
  `latest_events` — and `custody.unresolved_conflicts`). **The decisive design choice**
  the slice resolved: a conflict is counted **unresolved** while the *latest* conflict
  event's `observed_hash` still differs from the held copy's current `content_hash` —
  **not** by mere existence of a `conflict` event. The held copy is never auto-overwritten
  (ADR 0104; raw is sacred), so every recorded conflict is unresolved *today*, but the
  predicate is deliberately **resolution-aware**: a future `reconcile` (H276) that adopts
  the incoming content — the held hash becomes the observed hash — clears the item with
  **no** special "resolved" event, exactly the `latest_events` held-filter precedent (read
  the latest event, compare to the current state). The two ledger axes stay **disjoint by
  construction** — `latest_conflict_events` reads only the `conflict` rows, `latest_events`
  only the verify verdicts — so a conflict never inflates `custody.drift` and a drift
  verdict never appears here. Held-filtered like the drift block (a conflict on a
  since-deleted id is dropped) and, unlike the cross-source `custody.works` alarm,
  **source-attributable** — so `--source S` scopes it for free (a held item owns a source).
  A **report view only** (custody §2.4), never `issues`/`fixed`/the exit code; the MCP
  `get_library_health` twin carries it **for free** (the tool returns `run_doctor`'s whole
  custody block), converging field-for-field with the CLI by construction. **No schema
  change, no network** — a deterministic ledger fold. 10 tests (`tests/test_custody.py` ×5:
  the `latest_conflict_events` MAX(id)-over-conflict-rows + verify-verdict-exclusion, the
  `unresolved_conflicts` keep/clear/held-filter; `tests/test_cli.py` ×4:
  `doctor`'s `custody.conflicts` surfaces an unresolved conflict + drift-disjoint, honest
  empty on a clean library, held-filter clears on delete, `--source` scoping;
  `tests/test_mcp.py` ×1: the `get_library_health` twin carries it + converges) + 2 updated
  exact-shape assertions (`tests/test_doctor.py`). Docs: ADR 0104 (the doctor-aggregate
  deferred bullet marked shipped), `docs/reconciliation.md` "Shipped: a `doctor`
  scope-level conflict aggregate", `docs/cli.md`. **With H275 the conflict-on-import
  *read* leg is open on the JSON surface.** **H277 (2026-06-22) shipped the theme's
  *readable read* leg** — a `_Conflicts:_` briefing line, the readable completion of
  H275's JSON aggregate (ADR 0104), on the **three Markdown briefings**: the shareable
  `export bundle` (both Markdown `build_bundle` *and* HTML `build_bundle_html` forms,
  the H264/H271 two-form parity) and the `scrolls context` briefing. The line —
  ``_Conflicts: N item(s) carry an unresolved import conflict._`` (and the HTML twin
  `<p class="custody-conflicts">`) — is the **import-conflict-axis counterpart of the
  drift `_Attention:_` line** (`render_custody_attention`, H159): where that names the
  source whose live source moved, this names how many held items carry an *unresolved
  import conflict* (a peer's capture disagreed at merge time, still open — raw is never
  auto-overwritten). The shared `custody.render_custody_conflicts` helper folds the
  *same* `unresolved_conflicts` predicate over the same `latest_conflict_events` map
  `doctor`'s `custody.conflicts` reads, so the readable count and the JSON `items` cannot
  disagree for the same scope (the `render_at_risk_works`/`render_custody_attention`
  readable-line precedents). **The decisive design choice**: the line **names no command**
  — the resolution act, a reviewed `reconcile` (H276), does not exist yet, so it surfaces
  the count only (the `at_risk_signal` orphan-command discipline; the per-item detail lives
  on `doctor`'s `custody.conflicts.events` and `scrolls history <id> --status conflict`).
  Folded over the briefing's own `items` (the per-*item* custody axis the headline and
  `_Attention:_` line use — a conflict is a per-item fact, not a work consolidation),
  gated to `connected`+ on `scrolls context` like the headline (the `index` tier reads no
  ledger), and **export-only** on the bundle (a derived read view outside the lossless
  `@generated` JSONL fence, so the round-trip is untouched). Honest absence — no line when
  no held item in scope carries an unresolved conflict, and a *resolved* conflict (the held
  copy now matches the incoming hash) drops out via the resolution-aware predicate. **No
  schema change, no extra ledger read beyond the one `latest_conflict_events` query.** 16
  tests (`tests/test_bundle.py` ×7: Markdown carries-the-line + doctor convergence +
  clean/resolution-aware/round-trip no-ops, HTML twin + clean no-op; `tests/test_context.py`
  ×6: carries-the-line + doctor convergence + `index` gate + `connected` presence + clean
  no-op + MCP parity; `tests/test_custody.py` ×3: the `render_custody_conflicts` count,
  held-filter + resolution-aware, honest no-op). Docs: `docs/reconciliation.md` "Shipped: a
  readable `_Conflicts:_` briefing line", `docs/cli.md`. End-to-end verified on a real
  library (divergent peer-bundle import → `_Conflicts: 1 …_` on both bundle forms + the
  `context` briefing, omitted at `index`, converges with `doctor`'s `custody.conflicts.items
  == 1`). **With H277 the conflict-on-import theme's *read* leg is closed across the JSON
  and readable surfaces; the last leg is the operator act (H276, a reviewed `reconcile`
  resolution).** **H276 (2026-06-22) shipped that act — the conflict-on-import theme's
  detect → read → *resolve* arc is now closed for the safe direction.** `scrolls reconcile
  <id> --keep-held` affirms the held copy as authoritative, recording a typed `resolved`
  **conflict-axis** custody event (`custody.resolution_event` — `prior_hash` = the affirmed
  held copy, `observed_hash` = the rejected incoming capture) that **supersedes** the open
  conflict: `latest_conflict_events` now reads the `MAX(id)` over the conflict axis (`conflict`
  *and* `resolved`) and `unresolved_conflicts` keeps an item only while its latest axis event
  is *still an open* `conflict` (the status gate; the H275 hash gate — observed == held —
  coexists for the future `--accept-incoming`). So the resolution clears across **every**
  conflict surface at once — `doctor`'s `custody.conflicts`, the `_Conflicts:_` line on both
  bundle forms + `context`, and the MCP `get_library_health` twin — they all fold that one
  shared predicate. **The decisive design choice** the slice resolved (ADR 0105): *why
  keep-held ships and accept-incoming is deferred.* The conflict event records only the
  incoming **hash**, never the incoming **content** (the importer discarded the bytes — the
  held copy was never overwritten), so adopting the peer's capture genuinely needs the content
  **re-supplied** plus custody-safe prior-content archival (ADR 0098's deferred
  "re-capture-on-accept", the first import-path write that changes a held capture) — an honest
  scope boundary; keep-held needs nothing beyond data in hand. Two guarantees hold by
  construction: the **held copy is never overwritten** (raw is sacred, custody §2.4 — content +
  `content_hash` provably untouched, `reconcile` only *appends*) and the **original `conflict`
  event survives** (append-only — `history --status conflict` still shows *when* a peer
  disagreed; the resolution is a new `resolved` row, readable via `history --status resolved`).
  **CLI-only** (a custody-changing write is an explicit operator act, not an ambient MCP
  capability, like `verify`), **opt-in** (a bare `reconcile <id>` is exit 2 — a resolution is a
  decision, not a default), **idempotent** (a second `--keep-held` is a `resolved: false` no-op
  — latest axis event is already `resolved`), **dry-run-able** (`--dry-run` emits the same
  decision payload the live run would, plus `dry_run: true`, and writes nothing — the H245/H273
  predict-the-write discipline). A genuinely new divergent import *after* a resolution appends a
  fresh higher-`id` `conflict` and **re-opens** the alarm. The `resolved` event stays off the
  drift axis (`latest_events` reads only the verify verdicts — the ADR 0104 isolation, kept on
  the act axis); the new `current_conflict(db_path, item)` per-item helper folds the same
  `unresolved_conflicts`/`latest_conflict_events` over one item, so `reconcile`'s target equals
  what `doctor`/the line count. **No schema change, no network** — a deterministic ledger
  append. 14 tests (`tests/test_custody.py` ×7: `resolution_event` shape + round-trip,
  drift-isolation, `latest_conflict_events` axis read, `unresolved_conflicts` clears-after-
  keep-held + re-opens-on-fresh-conflict, `current_conflict`, the `LEDGER_STATUSES` vocab;
  `tests/test_cli.py` ×7: resolves + clears `doctor` + held copy untouched, idempotent,
  `--dry-run` predicts without recording, missing-flag exit 2, unknown-id exit 1, no-conflict
  no-op, the `conflict` row survives on `history` beside the `resolved` row). Docs: ADR 0105,
  `docs/reconciliation.md` "Shipped: a reviewed `reconcile` resolution — keep-held",
  `docs/cli.md` (the `reconcile` command + `history --status resolved`), README. End-to-end
  verified on a real library (divergent import → conflict → dry-run predicts/writes nothing →
  live reconcile clears `doctor` to 0 → idempotent no-op → both `conflict` and `resolved` on
  `history` → held copy untouched → no-flag exit 2). **With H276 the conflict-on-import theme is
  complete on detect → read → resolve for the safe direction; `--accept-incoming` (H278) and an
  MCP `reconcile` twin remain deferred.** **H279 (2026-06-22) closed the theme's *last conflict
  read gap on the JSON surface*** — a `conflicts` scalar on `scrolls status`'s machine `custody`
  snapshot, the JSON-status counterpart of H277's readable `_Conflicts:_` line. H277 scoped the
  readable count to the three Markdown briefings (`export bundle` ×2 + `context`); `scrolls
  status` renders no readable line, carrying the machine `custody_snapshot` block instead
  (`score`/`tiers`/`drift`/`enrichment_stale`/`summaries_stale`/`at_risk`) — but **not** an
  import-conflict count, so an agent reading `status` for a custody dashboard saw drift and
  at-risk-works but not unresolved conflicts. H279 folds the *same* `unresolved_conflicts` over
  `latest_conflict_events` (`doctor`'s `custody.conflicts` / the `_Conflicts:_` line read) into
  the shared `maintain.custody_snapshot` primitive (`custody.get("conflicts", {}).get("items",
  0)`, the defensive read `at_risk` uses) — and because `status`'s `custody` block *is*
  `custody_snapshot(run_doctor(...))`, the scalar converges field-for-field with `doctor`'s
  `custody.conflicts.items` **by construction** (a pure read of the report `run_doctor` already
  produced — no extra ledger query). It is **resolution-aware** (a `reconcile --keep-held`
  clears it) and **source-scopable for free** (`status --source <S>` narrows the conflict fold
  like the drift scalar, since a held item owns a source — unlike the whole-library-only
  cross-source `at_risk` alarm). The MCP `get_library_health` twin already carries the full
  `custody.conflicts` block (it spreads `**custody`), so it needed no change. **No schema change,
  no network** — a pure report fold. 6 tests (`tests/test_cli.py` ×4: surfaces + converges with
  `doctor` + off the drift axis, clears after `reconcile`, honest 0 on a clean library,
  source-scopes to the conflicting source; `tests/test_maintain.py` ×2: the `custody_snapshot`
  primitive records `custody.conflicts.items` + defaults to 0 without a `conflicts` block) + the
  exact-shape `custody_snapshot` / `_custody_headline` assertions updated. End-to-end verified on
  a real library (divergent import → `status.custody.conflicts == 1`, `--source` scopes,
  converges with `doctor`, clears to 0 after `reconcile`). Docs: `docs/cli.md` (the `status`
  `conflicts` scalar), `docs/reconciliation.md` "Shipped: a conflict scalar on `scrolls status`".
  **Shipped in H283 (the `at_risk` → H267/H268 analogue):** the cross-run
  `delta`/`--history`/`--trend` treatment of the conflict scalar + a readable `_Conflicts:_`
  `maintain` line — recorded in the snapshot by H279, differenced by H283. **With H279 the
  conflict-on-import theme's *read* leg is closed across *every* surface.**
- **The conflict-on-import theme is now closed on *both* resolution directions — H278 shipped the
  content-bearing adopt.** `scrolls import items/bundle --accept-incoming` (ADR 0106, schema v8)
  *adopts* a diverging peer capture: the held copy is **replaced** by the incoming one and a
  `superseded` conflict-axis event recorded — the **first import-path write that changes a held
  capture** — while the prior copy is **archived first** into the new append-only `item_archive`
  table (model-complete `item_to_dict` snapshot via the single-transaction `items.adopt_incoming`,
  archive-before-replace), recoverable, **never destroyed** (raw is sacred, §2.4). The decisive
  choices: **(1)** the flag is on the **import path**, not `reconcile` — the incoming content is in
  hand only at the merge (gone by reconcile time, only its hash was recorded); **(2)** adoption
  archives rather than overwrites, so recovery is **symmetric** — `scrolls archive show <id>`
  re-emits the archived prior as a re-importable `export items` line, and `archive show <id> |
  import items /dev/stdin --accept-incoming` restores it (re-adopting the prior, archiving the
  current copy in turn). The `superseded` status joins `CONFLICT_AXIS_STATUSES` (=
  `conflict`+`resolved`+`superseded`) so it supersedes the open conflict and clears
  `unresolved_conflicts` on **both** gates (status — latest axis event is `superseded`; hash —
  held copy *is* the incoming), staying **off** the drift axis (`latest_events` reads only
  `CUSTODY_STATUSES`, the ADR 0104 isolation). Idempotent by construction (a re-import of an
  adopted capture is `unchanged`), dry-run-able on the bundle importer (`_preview_merge_items`
  predicts the adopted set), loud on stderr (`_warn_adopted`), CLI-only (operator-gated write).
  New `scrolls archive list`/`archive show` are the recovery surface; the merge returns an
  `adopted` bucket/list beside `conflict`/`conflicts`. The archive is a **local recovery store**,
  not yet in the lossless round-trip (the `superseded` event travels; carrying the prior bytes in
  bundles is H280). 21 tests; full suite 3613 passed. Docs: ADR 0106, `docs/reconciliation.md`,
  `docs/cli.md` (schema pin → 8), README. **With H278 the conflict-on-import theme is closed on
  both resolution directions (keep-held + accept-incoming) across detect → read → resolve; the new
  lead is H283 (the conflict-over-time leg), then the archive-recovery sub-theme H280–H282/H284.**
- **H283 (2026-06-22) closed the conflict-over-time leg — the conflict scalar is now *differenced*,
  not just recorded.** H279 put the unresolved-import-conflict count on `status`'s snapshot and the
  shared `maintain.custody_snapshot` but never differenced it; H283 lifts the *exact* H267/H268
  at-risk-works machinery to the conflict axis (the clean analogue the slice was scoped as):
  `compute_delta` now subtracts the scalar (`delta["conflicts"]`), `compute_trend` differences it
  (a new `conflicts_change` axis beside `at_risk_change`, telescoping to the per-run deltas a worker
  reads back from `--history`), and the shared `maintain.conflicts_headline(count, change, *, span)`
  (the conflict twin of `at_risk_headline`) renders the readable `maintain`/trend `_Conflicts:_`
  line — `▲` worse, `▼` better, `0` no-change, bare `_Conflicts: N._` when there is no baseline
  (the H267 honesty). The line rides the `maintain` report *and* the MCP `run_maintenance` twin for
  free; like `at_risk_headline` it embeds the delta's signed change, so it is **run-position-
  dependent** and the MCP↔CLI convergence test strips it beside `delta`/`recorded_at` (a documented
  distinction from the position-independent `headline`). Two design points the slice resolved: **(1)**
  it is **recorded-but-never-a-`posture`-trigger** — a peer divergence moves *neither* the integrity
  score *nor* the drift axis (the held copy is never overwritten — raw is sacred, §2.4), so the
  posture stays integrity-only (the H115/H267 precedent); **(2)** unlike the whole-library-only
  at-risk line, the conflict count is **source-attributable**, so a `--source S` pass narrows it to
  `S` (a held item owns a source — the `custody.drift` posture, not the cross-source `custody.works`
  one). **No schema change, no network** — a pure report fold over the snapshot H279 already records.
  18 new tests in `tests/test_maintain.py` (`conflicts_headline` renderer ×5, `compute_delta`
  conflict axis ×3, `compute_trend` `conflicts_change`/headline ×5, integration
  report/`--history`/`--trend`/`--source` lines ×5), plus modified guards in
  `tests/test_custody_convergence.py` (the conflict axis telescopes with drift/coverage/staleness/
  at-risk; the `_audit_fields` MCP-strip extended) and `tests/test_mcp.py` (the `conflicts_headline`
  field added to the `run_maintenance` shape assertions). Full suite 3631 passed. End-to-end verified on a real library (divergent peer import → `_Conflicts: 1 (▲1
  since last run)._` → `reconcile --keep-held` → `_Conflicts: 0 (▼1 since last run)._`; the `--trend`
  line distils the 0→1→0 window). Docs: `docs/reconciliation.md` "Shipped: the conflict-over-time
  leg", `docs/cli.md` (the `maintain` report/trend `_Conflicts:_` line + the MCP twin row). **With
  H283 the conflict-on-import theme is closed across *every* surface including the over-time axis;
  the new lead is the archive-recovery sub-theme H280–H282/H284.**
- **The prior-content archive now travels in the portable round-trip (H280, the archive-recovery
  sub-theme's lossless-round-trip leg).** ADR 0106 left the recovery store *local* — a `superseded`
  event travelled while the archived prior *bytes* stayed behind, so a library rebuilt from a bundle
  could read *that* an adoption happened but not recover the prior copy. H280 lets it travel:
  **`export bundle --with-archive`** appends an opt-in **third `@generated` region** (the in-scope
  items' `item_archive` snapshots) beside the items + events blocks — without the flag the bundle is
  **byte-identical to a pre-H280 one** (the byte-identity/round-trip guarantees untouched) — and
  **`export archive`/`import archive`** are the whole-library JSONL siblings of `export
  events`/`import events`, the third member of the lossless backup family. `import bundle` restores
  any archive block **unconditionally**, deduped by `(item_id, prior_hash)` (the H67 events-dedup
  precedent), so a re-import is a no-op; the `--dry-run` predicts the restore. Records sort
  content-deterministically (`archived_at`, `item_id`, `prior_hash`), so a re-export from a rebuilt
  library is **byte-for-byte identical** — `archive show` re-emits the same prior on the rebuilt
  library. A standalone recovery store keyed by `item_id` (only appends to `item_archive`), so unlike
  the events restore it needs **no orphan split**. **No schema change** (v8 `item_archive`
  unchanged), no network. 35 tests; full suite 3666 passed. **The recovery store round-trips
  losslessly; the new lead is H281 (an MCP archive *read* twin), then H282/H284.**
- **The recovery store now reads over MCP too (H281, the archive-recovery sub-theme's MCP
  *read* leg).** ADR 0106's deferred MCP twin, read side only: `archive list`/`archive show`
  were CLI-only, so an agent over MCP could read *that* an adoption happened (the `superseded`
  event via `get_scroll_history`, the cleared `custody.conflicts` via `get_library_health`)
  but not reach the recovery store itself. H281 adds the same CLI split over MCP —
  **`list_archived(item_id=None)`** is the recovery *index* (the `{count, archived}` metadata
  the CLI `archive list` prints, folding the **shared** `items.archive_entry_dict` serializer)
  and **`get_archived(item_id)`** is the recovery *snapshot* (the model-complete, re-importable
  `item_to_dict` prior the CLI `archive show` emits, folding the same `items.latest_archived`).
  Both fold the *same* primitives the CLI reads → convergence by construction (pinned by
  the `archive list`/`archive show` ties). The **write stays operator-gated** (custody §2.4):
  the `import … --accept-incoming` adoption and the symmetric restore remain CLI acts; this is
  the *read* twin only. Honest empty before init / on a never-adopted library, could-not-recover
  error (the `archive show` exit-1 twin) on a never-superseded/unknown id; the registered tool
  surface grows to 24. A shared `items.archive_entry_dict` refactor (CLI `_cmd_archive_list`
  now folds it too) is the one production change beyond the two tools. **No schema change**, no
  network — a pure read fold. 9 tests (`tests/test_mcp.py`); full suite 3675 passed. **With H281
  the archive read travels everywhere; the new lead is H282 (`archive prune` retention), then
  H284 (the accept-incoming end-to-end dogfood).**
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
over taking them. **The conflict-on-import theme is now closed on the safe direction** —
detect (H272 `import items`, H273 `import bundle`, H274 the durable conflict event, ADR 0104)
→ read (H275 `doctor`'s `custody.conflicts` + MCP twin, H277 the `_Conflicts:_` briefing line
on both bundle forms + `context`) → **resolve** (H276, `reconcile --keep-held` — affirm the
held copy, recording a `resolved` event that supersedes the open conflict; ADR 0105) →
**status-JSON read** (H279, `scrolls status`'s `custody.conflicts` scalar — the JSON-status
counterpart of H277's readable line, shipped 2026-06-22). **The conflict-on-import theme's
*read* leg is now closed across every surface (JSON status, JSON doctor/MCP, readable
briefings); the single remaining theme slice is H278** (the heavy one — `--accept-incoming`,
the content-bearing supersession that adopts the peer's capture; the first import-path write
that changes a held capture, needs an ADR for the prior-content archive). Take H278 next; reach
for the de-prioritized budget/tier guards H244–H249 only when no capability slice is ready, and
prefer closing one rather than appending more of the same shape.

| Slot | Intended slice | Maps to |
| --- | --- | --- |
| H297 | **A *JSONL-backup recovery dogfood* — the decide→restore→act recovery workflow survives an `export items` + `export archive` handoff, the H292 twin on the backup (not bundle) path.** H292 dogfoods the recovery *act* surviving a `--with-archive` *bundle* handoff; H294 pins the JSONL-backup read-family round-trips but runs reads + dry-run only. The untested operator workflow is the recovery *act* on the JSONL-backup path: back up machine A with `export items` + `export archive` to two files, rebuild a fresh machine B from those two backups (`import items` + `import archive`), prove `doctor --fix` + `kb` → `custody.score` 100, then `archive show --all` inspects the travelled history → `archive diff --hash` decides → `archive restore --hash` *acts* — a real write on the rebuilt library, reaching past the latest prior to an earlier version — so the held copy flips, the displaced copy re-archives reversibly, and `custody.score` holds at 100 through the real recovery write (the would-change and idempotent cases). The operator-workflow layer **above** H294's non-mutating read-family tie, exactly as H292 sits above H291. Test + docs (`tests/test_dogfood.py` + a new `docs/dogfood.md` section, the H292 narrative on the JSONL-backup transport). Sabotage-verified non-vacuous (the H292 discipline — inverting the diff predicate fails the cross-machine convergence). Precondition: H294 (the JSONL read-family round-trip, **shipped 2026-06-23**), H292 (the bundle-path recovery dogfood, **shipped 2026-06-23**). | → cap 3, cap 8 |
| H298 | **The archive-integrity alarm gets a readable `maintain`/`status` headline — `custody.archive`'s `mismatched` count surfaces as a human-readable line, the `conflicts_headline` (H283) / `_Conflicts:_` (H277) analogue on the archive axis.** H293 added the `doctor` `custody.archive` integrity check (a corrupt/laundered prior, `prior_hash != snapshot.content_hash`), but it is **JSON-only**: `maintain`'s readable summary folds score/tiers/drift/`conflicts_headline`/`at_risk_works` yet is *blind* to the archive-integrity axis, so the scheduled custody-maintenance pass an operator reads reports a conflict but never a tampered/laundered backup. Add `archive_integrity_headline(custody["archive"])` in `maintain.py` (the `conflicts_headline` sibling: `_Archive: N prior(s) fail integrity (prior_hash ≠ snapshot)._`, omitted entirely when `mismatched == 0` or `status == "skipped"` — no fabricated "0 mismatched"), wire it into the `maintain` readable block, and add the JSON `status` scalar twin (the `status`-renders-no-readable-line precedent H279 set for conflicts: `status` carries `archive_mismatched` as a scalar, `maintain` carries the readable line). Convergence pinned: the readable count ≡ `doctor`'s `custody.archive.mismatched` ≡ the `status` scalar (the H277/H279 three-way honesty tie on the archive axis). Tests (`tests/test_maintain.py`, beside the `maintain`/`status` H279/H283 tests): the line appears with the right count on a corrupt prior, is *absent* on a clean/`--source`-skipped library, and converges with `doctor`. Sabotage-verified non-vacuous (hard-coding the headline count fails the convergence tie). Docs: `docs/cli.md` `maintain`/`status` sections, ADR 0106 deferred bullet. Precondition: H293 (the `doctor` archive-integrity check, **shipped 2026-06-23**), H283 (the `conflicts_headline` trend-line precedent), H279 (the `status` JSON-scalar twin precedent). | → cap 5, cap 8 |
| H299 | **The archive-integrity alarm gets a cross-run delta/trend in `maintain` — `_Archive: N (▲M since last run)._`, the H283 (`conflicts` trend) analogue on the archive axis.** H298 surfaces the *current* mismatch count; the untested capability is the run-to-run *movement* an operator scanning successive `maintain` passes needs — `0 → N` is new corruption (a backup tampered/laundered since the last pass), `N → 0` is a repaired backup. Record the archive `mismatched` count in the same `maintain` trend snapshot `conflicts_headline` reads its prior value from (the `(▲2 since last run)` machinery), and render the delta in the H298 line. Pin: a first pass over a clean library shows no delta, a corrupt prior introduced before the second pass reads `▲N`, repairing it before a third reads `▼N` back to clean — the trend tracks the backup's *content* across passes, never a phantom. Tests beside H298's (`tests/test_maintain.py`). Correct-by-construction (the same snapshot-diff `conflicts_headline` uses), a regression guard; sabotage-verified non-vacuous (freezing the prior-snapshot count fails the `▲`/`▼` legs). Docs: `docs/cli.md` `maintain` trend section. Precondition: H298 (the readable archive-integrity headline), H283 (the conflicts trend-line machinery). | → cap 5, cap 8 |
| H300 | **Scoped `export archive --id <ref>` round-trips the recovery read-family identically — the H294 twin on the *per-item* export path.** H294 pins the *whole-library* `export archive` → `import archive` round-trip carries the recovery read-family (`archive show --all`/`diff`/`restore --dry-run`); the per-item `--id`-scoped export (`archived_records(db, [item_id])`, a *different* fold than the whole-library `archived_records(db, None)`) is the operator move "back up *just this item's* recoverable history" and nothing pins that it round-trips the family for that item identically. Pin it (the H294 assertion shape, scoped): adopt a multi-supersession chain on item X *and* a one-prior chain on item Y in A, `export archive --id X` to a file, rebuild a fresh B from `export items` + the *scoped* `export archive --id X`, then assert X's recovery read-family is byte/field-identical across A and B over all three selectors (`--hash`/`--at`/default-latest) **and** that Y's archive is absent on B (the scope genuinely excluded it — a vacuous "everything travelled" would pass falsely). Test (`tests/test_cli.py`, beside the H294 whole-library round-trip). Correct-by-construction (both folds share `archived_records`'s content-determined ordering + the verbatim-snapshot `import_archive`), a regression guard; mutation-checked (scoping to Y instead leaves X's archive empty on B → the family cannot read identically). Precondition: H294 (the whole-library JSONL-backup round-trip, **shipped 2026-06-23**). | → cap 4, cap 8 |
| H244 | **The custody bundle is reproducible across the round-trip boundary — `export bundle <Q>` from a library rebuilt *from a bundle* is byte-identical to the original `export bundle <Q>`, the bundle-artifact analogue of `test_export_rebuild_is_byte_identical`'s point 2 (export→import→export byte-stability).** H238 (this run) pins the rebuilt *scrolls* + compiled `library/` pages byte-identical across the `export bundle` → `import bundle` boundary; the untested guarantee is that the *bundle artifact itself* re-exports byte-for-byte from the rebuilt library. It is a genuine, distinct claim: the bundle is more than its item block — it carries derived prose (the `custody_headline`, the `_Attention:_`/`_Refresh:_` pointers, the per-source breakdown via `render_custody_by_source`) computed over the rows + ledger, none of it clock-derived (`bundle.py` has no `datetime`/`now()` call). So if the round-trip carries every field those folds read from, re-exporting the *whole* briefing from the rebuilt home reproduces the original byte-for-byte — the M4/cap 9 "self-contained, shareable" briefing is itself reproducible, not just its lossless core. Pin it: over the mixed-fidelity `_mixed_fidelity_scope` (no recorded events → an empty events block on both sides, keeping the slice correct-by-construction), `export bundle "database"` from source A, `import bundle` + `doctor --fix` + `kb` into fresh B, then `export bundle "database"` from B and assert the two bundle texts are byte-identical (and, separately, that the re-exported items block alone is byte-stable — the `dump_items_export`-over-identical-rows guarantee point 2 already covers for `export items`). Implementation path: `build_bundle` folds only row/ledger-derived primitives (`custody_headline`, `custody_counts_by_source`, `_refresh_debt_by_source`) with no clock input, and H238/export-items byte-stability already give row-level byte-identity, so bundle reproducibility is correct-by-construction; the slice pins it on the bundle artifact the scroll/library byte-identity tests never re-export. Test only (`tests/test_bundle.py`, beside the H238 byte-identity test). Precondition: H238 (the bundle scroll/library byte-identity, **shipped this run**), H216 (the mixed-fidelity bundle round-trip). | → cap 9, cap 4 |
| H245 | **The dry-run's `new`/`held` partition *predicts the real import's per-id write effect* — the identity-level closure of H233's count-level "the preview never drifts from reality."** H233 ties the dry-run's `imported`/`skipped` *counts* to a real import's; the untested guarantee is that the dry-run's reviewable *id sets* name exactly the rows the merge actually moves on disk. The counts could match while the preview names the wrong ids — and an operator confirms a merge by reading `new`/`held`, not by reconciling integer counts. Pin it: over a mixed bundle (would-be-new ids, already-held ids, within-bundle dups), capture each parsed id's pre-import held-state (`get_item is None`), dry-run to read `new`/`held`, then real-import the *same* bundle into the same library; assert every id in `new` was absent before and is held after (a genuine absent→present transition the merge caused) and every id in `held` was held before *and* after (no transition) — so the reviewable surface an operator confirms is exactly the set of rows the merge inserts vs. leaves untouched, not merely the right *number* of them. Mutation-checked: pre-holding one of the `new` ids before the dry-run moves it from `new` to `held` *and* removes it from the post-import absent→present transition set, in lockstep — the prediction tracks the library's real state, never a stale snapshot. Implementation path: the dry-run's `new`/`held` come from the same `get_item(...) is None` test the live import's INSERT OR IGNORE (ADR 0082) acts on, so the prediction is correct-by-construction; the slice pins the identity-level closure H233 left at the count level (the reviewable surface describes the *actual* merge, the M2/cap-9 custody-honesty on the predict-the-write axis). Test only (`tests/test_bundle.py`, beside H239/H233). Precondition: H239 (the partition, **shipped this run**), H233 (the count-level reality tie), H226 (the reviewable lists). | → cap 9, cap 7 |
| H246 | **The whole budget ladder stays mutually equal under truncation while *together* diverging from the *library-wide* `doctor` audit — the *unscoped* twin of H240 (and the truncated boundary of H213).** H213 ties the unscoped `index` ≡ `connected` ≡ `full` ≡ `doctor` *only* when one query matches the whole library (no truncation); H240 (shipped this run) pins the *scoped* ladder under a cap diverging from `doctor --source <S>`. The untested cell is the *unscoped* ladder under a cap: the no-facet path, where the library-wide audit and the kept-`k` bundle must genuinely differ. Over `_seed_mixed_custody` (four scrolls: full 2, partial 1, reference 1, no source filter), `context --budget {index,connected,full} --limit k` with `k` below the held count renders three fidelity sections all *equal to each other* (the kept-`k` slice) and all `≠` the library-wide `doctor`'s `custody.tiers` (summing to the whole held count `> k`); lifting the cap (`--limit` ≥ held) reconverges all four to the H213 unscoped equality. So the no-facet budget ladder never disagrees *with itself* under a cap, and neither the leanest nor the deeper tiers inflate the bundle-kept holdings to a library-wide claim — H240's cohesion guarantee on the unscoped (no-`--source`) read path. Test only (`tests/test_custody_convergence.py`, beside H240/H213). Implementation path: all three tiers fold `get_fidelity` over the same post-cap `items` (`index` via `render_fidelity_holdings`, `connected`/`full` via `custody_headline`) while unscoped `doctor` folds over every held row, so the cohesion-under-truncation is correct-by-construction; the slice pins the unscoped boundary H213 (untruncated) and H240 (scoped) leave between them. Precondition: H240 (the scoped ladder-under-truncation, **shipped this run**), H213 (the unscoped four-way tie). | → cap 1, cap 2, cap 10 |
| H247 | **The whole budget ladder is mutually equal *and* equal to `get_library_health()`'s `tiers`, all read over MCP and untruncated — the direct MCP twin of H213 (and the unscoped sibling of H241).** H241 (this run) pins `index` ≡ `connected` ≡ `full` over MCP *under scope*; H214 pins only the *leanest* `index` `_Fidelity:_` line ≡ the CLI over MCP, never the cross-*tier* tie over MCP. The untested cell is the *unscoped* (no-`source`) MCP cross-tier tie: over a library-wide query matching every held item (no facet, no truncation), `get_context_bundle(query, budget={index,connected,full})`'s fidelity counts must all be equal to each other *and* equal to `get_library_health()`'s `tiers` — the leanest `_Fidelity:_` line (`render_fidelity_holdings`) and the deeper `_Custody:_` headlines' `fidelity` section (`render_custody_headline`, a **different** function) and the whole-library MCP audit (the MCP twin of `doctor`) are four reads of one ledger-free fact (`get_fidelity` per item) over the one library-wide scope. Pin it: over `_seed_mixed_custody`-style holdings (full 2, partial 1, reference 1) with every title sharing a query token (so one unscoped query matches all 4 held < the default limit → no truncation), all three MCP budget tiers' fidelity counts equal each other and equal `get_library_health()`'s `tiers` (the `index` line still withholds the drift verdict the deeper tiers carry — the H214/H219 honesty stays intact). Mutation-checked: dropping a `full` item's body shifts the tier on all three MCP tiers *and* the MCP audit in lockstep. Test only (`tests/test_mcp.py`, beside the H241/H235/H214 twins). Implementation path: all three tiers fold `get_fidelity` over the same `items` in `build_context` and `get_library_health()` is the MCP twin of `doctor` folding over every held row, so the four-way unscoped tie is correct-by-construction; the slice pins the direct MCP twin of H213's CLI cross-tier convergence (the unscoped sibling of H241). Precondition: H241 (the scoped MCP cross-tier tie, **shipped this run**), H214 (the unscoped MCP leanest line ≡ CLI), H213 (the CLI cross-tier tie). | → cap 1, cap 2, cap 10 |
| H248 | **The whole *unscoped* MCP budget ladder stays mutually equal under truncation while *together* diverging from the *library-wide* `get_library_health()` `tiers` — the *MCP twin of H246* (and the truncated boundary of H247), filling the last open cell of the cross-tier × untruncated/truncated × CLI/MCP × scoped/unscoped fidelity-convergence matrix.** H247 ties the *unscoped* `index` ≡ `connected` ≡ `full` ≡ `get_library_health()` over MCP *untruncated*; H242 (shipped this run) pins the *scoped* MCP ladder under a cap diverging from `get_library_health(source=<S>)`. The untested cell is the *unscoped* MCP ladder under a cap: the no-`source` path, where the library-wide MCP audit and the kept-`k` bundle must genuinely differ. The `connected`/`full` `_Custody:_` headline's `fidelity` section is rendered by `render_custody_headline` (a **different** function than the `index` line's `render_fidelity_holdings`), yet all three fold over the *same* post-cap kept set — so under truncation the three MCP budget tiers must stay mutually equal (all bundle-kept, summing to `k`) *even as all three collectively diverge* from the whole-library MCP audit (summing to the held count `> k`). Pin it: over a library-wide mixed-fidelity holdings (full 2, partial 1, reference 1) where one unscoped query matches every held item, `get_context_bundle(query, budget={index,connected,full}, limit=k)` with `k` below the held count renders three fidelity sections all equal to each other and all `≠ get_library_health()`'s `tiers`; lifting the cap (`limit` ≥ held) reconverges all three to the H247 unscoped MCP equality. So the no-`source` MCP budget ladder never disagrees *with itself* on holdings under a cap, and neither the leanest nor the deeper tiers inflate the bundle-kept holdings to a library-wide claim — H242's cohesion guarantee on the unscoped MCP read path. Test only (`tests/test_mcp.py`, beside the H242/H247/H214 twins). Implementation path: all three tiers fold `get_fidelity` over the same post-cap `items` in `build_context` while `get_library_health()` (no `source`) is the MCP twin of `doctor` folding over every held row, so the cohesion-under-truncation is correct-by-construction; the slice pins the unscoped MCP boundary H247 (untruncated) and H242 (scoped) leave between them. Precondition: H242 (the scoped MCP ladder-under-truncation, **shipped this run**), H247 (the unscoped MCP four-way tie), H246 (the unscoped CLI ladder-under-truncation). | → cap 1, cap 2, cap 10 |
| H249 | **The dry-run's `new`/`held`/`orphaned_items` form a clean *three-way* id-space partition even over a bundle corrupt on *both* axes — the both-axes closure of H239 (which proved the two-way `new`/`held` partition over an items-*only* corrupt bundle).** H239 pins `set(new) ∪ set(held)` = the bundle's distinct item ids and `set(new) ∩ set(held) == ∅`, but only over an items-only corrupt bundle (empty events); the untested cell is whether that reviewable partition stays clean when the *events* block is *also* corrupt (orphan events present), and whether the orphan-item id-space stays disjoint from the item partition. It is a genuine guarantee: `new`/`held` are folded from the items block (`imported_items`) while `orphaned_items` is folded from the events block's unresolved ids (`_orphan_item_ids`), two independent reads of the one parsed bundle, so a naive impl could let an orphan item leak into `new`/`held` (double-classifying an id the merge never writes) or an items-block id vanish from review. Pin it: over the H243 `_spliced_items_and_events_bundle` (a within-bundle item-dup items block *plus* anchored-and-orphan events), dry-run and assert (a) `sorted(new + held)` equals the distinct items-block ids computed independently via `parse_bundle`, (b) `set(new).isdisjoint(held)`, and (c) `set(orphaned_items).isdisjoint(set(new) | set(held))` — three non-overlapping id-spaces, so an operator reviewing the preview never sees one id classified two ways across the item and orphan axes. Mutation-checked: adding a distinct orphan event for a new missing item extends `orphaned_items` by exactly that id and leaves `new`/`held` untouched (the orphan axis never perturbs the item partition). Implementation path: `orphan` item ids are exactly those neither held nor in `known_ids` (`partition_resolvable_events`), so they are disjoint from the items-block ids by construction; the slice pins the cross-axis disjointness H239 (items-only) and H243 (counts, not the id partition) leave open. Test only (`tests/test_bundle.py`, beside H243/H239). Precondition: H243 (the both-axes whole-summary tie + `_spliced_items_and_events_bundle`, **shipped this run**), H239 (the two-way items-only partition). | → cap 9, cap 7 |
| H256 | **Buffer refresh checkpoint** (maintenance rule). *Serviced 2026-06-22, post-H278*: the conflict-on-import / reconciliation theme is now **closed on *both* resolution directions across detect → read → resolve** — detect (H272 `import items`, H273 `import bundle`, H274 the recorded conflict event, ADR 0104), read (H275 `doctor`'s `custody.conflicts` + MCP twin, H277 the `_Conflicts:_` briefing line on both bundle forms + `context`, H279 the `status` JSON scalar), and **resolve** both ways (H276 `reconcile --keep-held` — affirm the held copy, ADR 0105; **H278 `import … --accept-incoming` — adopt the incoming copy with prior-content archival, ADR 0106 + schema v8**). With the theme closed, the queue was **re-derived** from ADR 0106's deferred section (the archive's reach + retention) and H279's deferred (the conflict-over-time leg): the new **archive-recovery sub-theme** — ~~H283 (the conflict cross-run delta/trend + readable `maintain` line, the H267/H268 analogue — **shipped 2026-06-22**)~~, ~~H280 (the archive travels in the portable bundle, the lossless-round-trip reach — **shipped 2026-06-22**)~~, ~~H281 (an MCP archive *read* twin — **shipped 2026-06-22**)~~, ~~H282 (`archive prune` retention — **shipped 2026-06-22**)~~, ~~H284 (an accept-incoming end-to-end dogfood — **shipped 2026-06-22**, closing the sub-theme)~~ — plus the de-prioritized budget/tier guards H244–H249 below. *Serviced again 2026-06-22, post-H282*: with H280/H281/H282/H283 shipped, the sub-theme's capability cushion thinned to a single fresh slot (H284) above the correct-by-construction guards, so the queue was **extended** from ADR 0106's remaining deferred list — **H285** (`archive show --all`, the full-history read) and **H286** (`archive restore --hash/--at`, restore-by-version over the H285 history). *Serviced again 2026-06-22, post-H284*: with H284 shipped the archive-recovery sub-theme (H280–H284) is **closed**; the queue held **2 fresh capability slots** (H285, H286) above the 6 guards (8 un-started work slots — ≥6, buffer healthy). *Serviced again 2026-06-22, post-H285*: **H285 (`archive show --all`, the full archived-history read) shipped**, leaving **1 fresh capability slot** (H286 — `archive restore --hash/--at`, now precondition-clear) above the 6 guards (7 un-started work slots — still ≥6, buffer healthy, no append yet). *Serviced again 2026-06-22, post-H286*: **H286 (`archive restore <id> --hash/--at`, restore-by-version over the H285 history — `select_archived_snapshot` feeding the existing accept-incoming adoption, no new write path) shipped**, **closing the archive-recovery sub-theme (H280–H286)**: every deferred archive read/retention/portability leg of ADR 0106 has now landed, and the *only* item still genuinely deferred is the **MCP accept-incoming *write* twin** (operator-gated by §2.4 — stays deferred unless a workflow shows the read-only surfaces insufficient). With the capability cushion **emptied** (only the 6 correct-by-construction guards H244–H249 remained), the queue was **extended** from the natural restore-by-version follow-ups: **H287** (the restore-by-version dogfood — the H284 analogue, multi-supersession roll-back narrated in `docs/dogfood.md`) and **H288** (`archive diff <id> --hash/--at` — the "decide before you restore" read comparing held vs a selected prior). That restores **2 fresh capability slots** above the 6 guards (8 un-started work slots — ≥6, buffer healthy). **Now due at the next checkpoint:** the 3-day plan below still reads 2026-06-21→24 (expiring 2026-06-25) — a full 3-day/week-plan re-derivation with absolute dates against `docs/product/mvp.md` is due **next run** (or when the capability queue next drops below ~6); the MVP M1–M5 and every post-MVP custody theme are closed, so fresh capability now comes from hardening/integration and the archive read-surface follow-ups, not ADR 0106's exhausted deferred list. Bi-temporal drift framing stays deferred. *Serviced again 2026-06-22, post-H287*: **H287 (the restore-by-version dogfood — multi-supersession roll-back narrated in `docs/dogfood.md`, the H284 analogue on the H285/H286 reads) shipped**, leaving the queue at **H288** (`archive diff`, the decide-before-you-restore read) above the 6 de-prioritized correct-by-construction guards H244–H249 (**7 un-started work slots — ≥6, buffer healthy**). The due 3-day/week-plan re-derivation **was performed this run**: the 3-day plan is re-stamped **2026-06-22 → 2026-06-25** and the week plan **through 2026-06-29**, both with absolute dates against the now-closed MVP M1–M5 + post-MVP custody themes — the forward capability is the archive read-surface follow-up (H288), then hardening/integration (full-suite reliability, doctor/repair, export/import round trips, MCP/search/list consistency); a new source adapter only if it introduces a genuinely new custody shape (§2.7). Bi-temporal drift framing stays deferred. *Serviced again 2026-06-22, post-H288*: **H288 (`archive diff <id> [--hash H \| --at ISO]`, the decide-before-you-restore read — `select_archived_snapshot` + the new pure `items.diff_snapshot` folded against the held copy, `would_restore` keyed on `content_hash` like `merge_item`) shipped**, completing the archive read/act/recover surfaces (every deferred archive *read* leg of ADR 0106 has landed; only the operator-gated **MCP accept-incoming write twin** — and, with it, an MCP `archive diff` read twin — stays deferred per §2.4). With the capability cushion emptied (only the 6 de-prioritized guards remained), the queue was **extended** from the natural H288 proof/integration follow-ups: **H289** (the decide-before-you-restore dogfood — read `archive diff`, then act, the H287 analogue), **H290** (the `archive diff` `would_restore` ≡ `archive restore --dry-run` `restored` cross-command tie), and **H291** (the archive-read-family round-trip — `archive show --all`/`diff`/`restore` identical on a `--with-archive`-rebuilt library, the H280↔H285/H286/H288 integration tie). That restores **3 fresh capability slots** above the 6 guards (**9 un-started work slots — ≥6, buffer healthy**). The 3-day plan stays **2026-06-22 → 2026-06-25** (H288 folded into Day 1 done; H289–H291 are Day 2; hardening Day 3) and the week plan **through 2026-06-29**; after H289–H291 the forward work is pure hardening/integration, not a new theme. Bi-temporal drift framing stays deferred. *Serviced again 2026-06-22, post-H289*: **H289 (the decide-before-you-restore dogfood — read `archive diff`, then act, and the act lands exactly on the read's prediction; the H287 analogue on the H288 read) shipped**, leaving the queue at **H290** (the `archive diff`↔`archive restore --dry-run` write-prediction convergence guard) and **H291** (the archive-read-family lossless round-trip) above the 6 de-prioritized correct-by-construction guards H244–H249 (**8 un-started work slots — ≥6, buffer healthy, no append**). The 3-day plan stays **2026-06-22 → 2026-06-25** (H289 folded into Day 2 done; H290/H291 are the rest of Day 2; hardening Day 3) and the week plan **through 2026-06-29**; after H290/H291 the forward work is pure hardening/integration. Bi-temporal drift framing stays deferred. *Serviced again 2026-06-23, post-H290/H291*: **H290 (the `archive diff`↔`archive restore --dry-run` write-prediction convergence guard) and H291 (the archive-recovery read-family lossless round-trip — `archive show --all`/`diff`/`restore --dry-run` identical on a `--with-archive`-rebuilt library) both shipped**, **closing the archive-recovery theme end-to-end** (read → act → recover → travel → round-trip, all pinned). With the capability cushion emptied (only the 6 de-prioritized guards H244–H249 remained) and the whole archive surface mature (`export/import archive`, `archive list/show --all/restore/diff/prune`, the MCP read twin, the portable `--with-archive` bundle), the queue was **re-derived from the hardening/integration priorities** (no new theme): **H292** (the cross-machine recovery *dogfood* — the decide→restore loop survives a bundle handoff, the operator-workflow layer of H291's test), **H293** (a `doctor` archive-integrity check — `prior_hash ≡ snapshot.content_hash`, report-only, a genuine new doctor/repair capability), and **H294** (the whole-library `export items`+`export archive` → `import` round-trip preserves the recovery read-family, the H291 twin on the JSONL-backup path). That restores **3 fresh capability slots** above the 6 guards (**9 un-started work slots — ≥6, buffer healthy**). The 3-day plan stays **2026-06-22 → 2026-06-25** (H290/H291 fold into Day 2 done; H292–H294 are Day 3 hardening) and the week plan **through 2026-06-29**; the once-per-24h full re-derivation was performed at the post-H288 checkpoint and is not yet due. Bi-temporal drift framing stays deferred. *Serviced again 2026-06-23, post-H293*: **H293 (the `doctor` archive-integrity check — `custody.archive` folds over `archived_records` and flags any row whose advertised `prior_hash != snapshot.content_hash`, report-only, with the offending `{item_id, prior_hash, snapshot_hash}` and no fabricated repair; NULL `prior_hash` vacuously skipped; whole-library-only — `status: "skipped"` under `--source`, like `fts`/`orphan_scrolls`; the MCP `get_library_health` twin carries it for free; ADR 0106 Deferred updated) shipped**, a genuine new doctor/repair capability taken **ahead of the H292 dogfood lead** (capability-first: H293 is a new code/test surface, H292 narrates existing ones; the two are independent — H292's preconditions don't include H293). That leaves the queue at **H292** (the cross-machine recovery dogfood, still lead) and **H294** (the JSONL-backup read-family round-trip) above the 6 de-prioritized correct-by-construction guards H244–H249 (**8 un-started work slots — ≥6, buffer healthy, no append**). The 3-day plan stays **2026-06-22 → 2026-06-25** (H293 folded into Day 3 done; H292/H294 the rest of Day 3 hardening) and the week plan **through 2026-06-29**; the once-per-24h full re-derivation (last done post-H288) is **due 2026-06-25**. Bi-temporal drift framing stays deferred. *Serviced again 2026-06-23, post-H292*: **H292 (the cross-machine recovery dogfood — the whole decide→restore recovery *workflow* survives a `--with-archive` bundle handoff: hold + adopt a 2-step chain on machine A, `export bundle --with-archive`, then on a fresh machine B `import bundle` + `doctor --fix` + `kb` → prove score 100 → `archive show --all` inspects the travelled history → `archive diff --hash` decides → `archive restore --hash` *acts* — a real write on the rebuilt library, reaching past the latest prior to the original — so the held copy flips, the displaced copy re-archives reversibly, and `custody.score` holds at 100 through the real recovery write, on both the would-change and idempotent cases; `test_recovery_workflow_survives_a_machine_handoff` in `tests/test_dogfood.py`, the operator-workflow layer **above** H291's non-mutating read-family tie — H291 ran reads + dry-run only, H292 runs the recovery *act* on B) shipped**, sabotage-verified non-vacuous (inverting `_cmd_archive_diff`'s `would_restore` fails the cross-machine convergence) + docs (`docs/dogfood.md` new "Taking the recovery workflow with you — a machine handoff" section with captured CLI output, test-count 9→10). That leaves the queue at **H294** (the JSONL-backup read-family round-trip, now lead) above the 6 de-prioritized correct-by-construction guards H244–H249 (**7 un-started work slots — ≥6, buffer healthy, no append**). The 3-day plan stays **2026-06-22 → 2026-06-25** (H292 folded into Day 3 done; H294 the last Day 3 hardening slot) and the week plan **through 2026-06-29**; the once-per-24h full re-derivation (last done post-H288) is **due 2026-06-25**. Bi-temporal drift framing stays deferred. *Serviced again 2026-06-23, post-H294*: **H294 (the whole-library JSONL backup round-trips the recovery read-family — `archive show --all` byte-for-byte, `archive diff`, and `archive restore --dry-run` field-for-field identical across all three selectors on a library rebuilt from `export items` + `export archive`, the H291 twin on the backup path) shipped**, **closing the archive-recovery hardening trio (H292–H294)**: the recovery surface now has *both* round-trip family ties (the bundle path H291 + the JSONL-backup path H294), the cross-machine recovery dogfood (H292), and the `doctor` archive-integrity check (H293). With the whole archive surface mature and both transports pinned, the capability cushion **emptied** (only the 6 de-prioritized correct-by-construction guards H244–H249 remained), so the queue was **re-derived from the hardening/integration priorities** (no new theme) into the natural H293×H294 follow-ups: **H295** (the archive-integrity alarm *survives the JSONL-backup round-trip* — a corrupt prior is flagged identically on the rebuilt library, never laundered by a backup), **H296** (the same alarm *travels in the `--with-archive` bundle* — the bundle-path twin of H295), and **H297** (the JSONL-backup recovery *dogfood* — the decide→restore→act workflow survives an `export items`+`export archive` handoff, the H292 twin on the backup path). That restores **3 fresh capability slots** above the 6 guards (**9 un-started work slots — ≥6, buffer healthy**). The 3-day plan stays **2026-06-22 → 2026-06-25** (H294 folds into Day 3 done; H295–H297 are the forward hardening/integration work) and the week plan **through 2026-06-29**; the once-per-24h full re-derivation (last done post-H288) remains **due 2026-06-25**. Bi-temporal drift framing stays deferred. *Serviced again 2026-06-23, post-H295*: **H295 (the archive-integrity alarm *survives the JSONL-backup round-trip* — a corrupt archived prior, `prior_hash != snapshot.content_hash`, carried through `export items` + `export archive` → `import items` + `import archive` is flagged *identically* by `doctor`'s `custody.archive` on the rebuilt library; the corruption is **not laundered** by the backup) shipped**, as a regression guard correct-by-construction (`import_archive` stores the snapshot verbatim and dedups by `(item_id, prior_hash)`, never re-deriving `prior_hash`): `test_archive_integrity_alarm_survives_the_jsonl_backup_round_trip` asserts B's `custody.archive` is byte-for-byte A's (same offending `{item_id, prior_hash, snapshot_hash}`, same `checked`/`mismatched`, the clean prior passing on both), and `test_repairing_the_archive_backup_clears_the_alarm_on_the_rebuilt_library` is the load-bearing mutation guard (repairing the divergence in the JSONL before import makes B read clean — the alarm tracks the backup's *content*, not a phantom), in `tests/test_doctor.py` beside the H293 archive-integrity tests; sabotage-verified non-vacuous (transiently re-deriving `prior_hash` from the snapshot at import — laundering the corruption — fails the A==B tie while the repair guard still passes, pinning both directions); suite **3742 passed**. That leaves the queue at **H296** (the same alarm travels in the `--with-archive` bundle, the bundle-path twin) and **H297** (the JSONL-backup recovery dogfood) above the 6 de-prioritized correct-by-construction guards H244–H249 (**8 un-started work slots — ≥6, buffer healthy, no append**). The 3-day plan stays **2026-06-22 → 2026-06-25** (H295 folded into Day 3 done; H296/H297 the rest of the hardening/integration work) and the week plan **through 2026-06-29**; the once-per-24h full re-derivation (last done post-H288) remains **due 2026-06-25**. Bi-temporal drift framing stays deferred. *Serviced again 2026-06-23, post-H296*: **H296 (the archive-integrity alarm *also travels in the portable `--with-archive` bundle* — a corrupt archived prior carried in the bundle's fenced archive block is flagged *identically* by `doctor`'s `custody.archive` on the bundle-rebuilt library; the shareable briefing does not launder a corruption either) shipped**, as a regression guard correct-by-construction (`import bundle` restores the archive through `parse_bundle_archive` → `import_archive`, the *same* verbatim-snapshot restore the JSONL path uses, and the bundle's fenced archive block carries the same `prior_hash`/`snapshot` columns the JSONL does): `test_archive_integrity_alarm_survives_the_with_archive_bundle_round_trip` asserts B's `custody.archive` is byte-for-byte A's (same offending `{item_id, prior_hash, snapshot_hash}`, same `checked`/`mismatched`, the clean prior passing on both) and `test_repairing_the_prior_on_the_bundle_wire_clears_the_alarm_on_the_rebuild` is the load-bearing mutation guard (repairing the corrupt `prior_hash` on the bundle wire before import makes B read clean — the alarm tracks the bundle's *content*, not a phantom), in `tests/test_bundle.py` beside the H291 read-family round-trip test; sabotage-verified non-vacuous (transiently re-deriving `prior_hash` from the snapshot at `archive_from_dict` — laundering the corruption on the bundle import path — fails the A==B tie while the repair guard still passes, pinning both directions); suite **3744 passed**. **With H296 the archive-integrity alarm is proved un-launderable across *both* transports (the JSONL backup H295 + the portable bundle H296).** That leaves the queue at **H297** (the JSONL-backup recovery dogfood, now lead) above the 6 de-prioritized correct-by-construction guards H244–H249 (**7 un-started work slots — ≥6, buffer healthy, no append**). The 3-day plan stays **2026-06-22 → 2026-06-25** (H296 folded into Day 3 done; H297 the last hardening slot) and the week plan **through 2026-06-29**; the once-per-24h full re-derivation (last done post-H288) remains **due 2026-06-25**. Bi-temporal drift framing stays deferred. *Serviced again 2026-06-23, post-H297*: **H297 (the JSONL-backup recovery *dogfood* — the whole decide→restore→act recovery *workflow* survives an `export items` + `export archive` handoff: hold + adopt a 2-step chain on machine A, back A up to two JSONL files, then on a fresh machine B `import items` + `import archive` + `doctor --fix` + `kb` → prove score 100 → `archive show --all` inspects the travelled history → `archive diff --hash` decides → `archive restore --hash` *acts* — a real write on the backup-rebuilt library, reaching past the latest prior to the original — so the held copy flips, the displaced copy re-archives reversibly, and `custody.score` holds at 100 through the real recovery write, on both the would-change and idempotent cases; `test_recovery_workflow_survives_a_jsonl_backup_handoff` in `tests/test_dogfood.py`, the operator-workflow layer **above** H294's non-mutating read-family round-trip — H294 ran reads + dry-run only, H297 runs the recovery *act* on B; the JSONL-backup twin of H292, **closing the archive-recovery dogfood family across both transports**: the recovery *workflow* now travels the portable bundle (H292) *and* the off-machine backup (H297), and the integrity alarm is un-launderable across both (H295/H296)) shipped**, sabotage-verified non-vacuous (inverting `_cmd_archive_diff`'s `would_restore` fails the cross-machine convergence — the H292 discipline) + docs (`docs/dogfood.md` new "Recovering from a whole-library backup — the JSONL transport" section with captured CLI output, test-count 10→11). With the whole archive-recovery surface now mature across both transports and all four hardening axes pinned (both round-trip family ties H291/H294, both recovery dogfoods H292/H297, the `doctor` integrity check H293, the un-launderable alarm H295/H296), the capability cushion **emptied** (only the 6 de-prioritized correct-by-construction guards H244–H249 remained), so the queue was **re-derived from the hardening/integration priorities** (no new theme) into the natural read-surface follow-ups the archive-integrity check (H293) left open: **H298** (the archive-integrity alarm gets a readable `maintain`/`status` headline — the `conflicts_headline`/H277 `_Conflicts:_` analogue on the archive axis, since H293 is JSON-only and `maintain` is currently blind to `custody.archive`), **H299** (the same alarm's cross-run delta/trend in `maintain` — the H283 conflicts-trend analogue), and **H300** (scoped `export archive --id` round-trips the recovery read-family identically — the H294 twin on the per-item export path). That restores **3 fresh capability slots** above the 6 guards (**9 un-started work slots — ≥6, buffer healthy**). The 3-day plan is re-stamped below to **2026-06-23 → 2026-06-26** (H295–H297 fold into done; H298–H300 are the forward readable-surface/integration work) and the week plan **through 2026-06-30**; the once-per-24h full re-derivation (last done post-H288) remains **due 2026-06-25**. Bi-temporal drift framing stays deferred. | maintenance |

The next lead slot is **H298** (the archive-integrity alarm gets a readable `maintain`/`status`
headline — the `conflicts_headline`/H277 `_Conflicts:_` analogue on the archive axis, since H293's
`custody.archive` check is JSON-only and `maintain`'s readable summary is currently blind to it),
then **H299** (the same alarm's cross-run delta/trend in `maintain`, the H283 conflicts-trend
analogue) and **H300** (scoped `export archive --id` round-trips the recovery read-family
identically, the H294 twin on the per-item export path) — three fresh readable-surface/integration
slots above the 6 de-prioritized guards.
**H297 (the JSONL-backup recovery *dogfood* — the whole decide→restore→act recovery *workflow*
survives an `export items` + `export archive` handoff: hold + adopt a 2-step chain on machine A,
back A up to two JSONL files, then on a fresh machine B `import items` + `import archive` +
`doctor --fix` + `kb` → score 100 → `archive show --all` → `archive diff --hash` decides →
`archive restore --hash` *acts* (a real write reaching past the latest prior to the original) →
the held copy flips, the displaced copy re-archives reversibly, score holds at 100, on both the
would-change and idempotent cases) shipped 2026-06-23**:
`test_recovery_workflow_survives_a_jsonl_backup_handoff` in `tests/test_dogfood.py`, the
operator-workflow layer **above** H294's non-mutating read-family round-trip (H294 ran reads +
dry-run only; H297 runs the recovery *act* on B) — the JSONL-backup twin of H292, **closing the
archive-recovery dogfood family across both transports** (the recovery workflow travels the
portable bundle H292 *and* the off-machine backup H297; the integrity alarm is un-launderable
across both H295/H296); sabotage-verified non-vacuous (inverting `_cmd_archive_diff`'s
`would_restore` fails the cross-machine convergence — the H292 discipline) + docs
(`docs/dogfood.md` new "Recovering from a whole-library backup — the JSONL transport" section
with captured CLI output, test-count 10→11); suite **3745 passed**.
**H296 (the archive-integrity alarm *also travels in the portable `--with-archive` bundle* — a
corrupt archived prior carried in the bundle's fenced archive block is flagged *identically* by
`doctor`'s `custody.archive` on the bundle-rebuilt library, the H293 × H291/H280 tie, the
bundle-path twin of H295) shipped 2026-06-23**:
`test_archive_integrity_alarm_survives_the_with_archive_bundle_round_trip` (A names the corrupt
row, the clean prior passes; B's report is byte-for-byte A's — the shareable briefing does *not
launder* the corruption) + `test_repairing_the_prior_on_the_bundle_wire_clears_the_alarm_on_the_rebuild`
(the load-bearing mutation guard — repairing the corrupt `prior_hash` on the bundle wire before
import makes B read clean, so the alarm tracks the bundle's *content*, not a phantom), in
`tests/test_bundle.py` beside the H291 read-family round-trip test; correct-by-construction
(`import bundle` restores the archive through `parse_bundle_archive` → `import_archive`, the
same verbatim-snapshot restore the JSONL path uses), sabotage-verified non-vacuous (transiently
re-deriving `prior_hash` from the snapshot at `archive_from_dict` — laundering the corruption on
the bundle import path — fails the A==B tie while the repair guard still passes); **with H296
the archive-integrity alarm is proved un-launderable across *both* transports** (the JSONL
backup H295 + the portable bundle H296); suite **3744 passed**. **H295 (the archive-integrity alarm *survives the JSONL-backup
round-trip* — a corrupt archived prior, `prior_hash != snapshot.content_hash`, carried through
`export items` + `export archive` → `import items` + `import archive` is flagged *identically*
by `doctor`'s `custody.archive` on the rebuilt library, the H293 × H294 tie) shipped
2026-06-23**: `test_archive_integrity_alarm_survives_the_jsonl_backup_round_trip` (A names the
corrupt row, the clean prior passes; B's report is byte-for-byte A's — the corruption is *not
laundered* by the backup) + `test_repairing_the_archive_backup_clears_the_alarm_on_the_rebuilt_library`
(the load-bearing mutation guard — repairing the divergence in the JSONL before import makes B
read clean, so the alarm tracks the backup's *content*, not a phantom), in
`tests/test_doctor.py` beside the H293 archive-integrity tests; correct-by-construction
(`import_archive` stores the snapshot verbatim and dedups by `(item_id, prior_hash)`, never
re-deriving `prior_hash`), sabotage-verified non-vacuous (transiently re-deriving `prior_hash`
from the snapshot at import — laundering the corruption — fails the A==B tie while the repair
guard still passes, pinning both directions); suite **3742 passed**. **H294 (the whole-library
JSONL backup round-trips the recovery read-family — `archive show --all` byte-for-byte,
`archive diff`, and `archive restore --dry-run` field-for-field identical across all three
selectors on a library rebuilt from `export items` + `export archive`, the H291 twin on the
JSONL-backup path, **closing the archive-recovery hardening trio H292–H294**) shipped
2026-06-23**: `test_jsonl_backup_round_trips_the_archive_recovery_read_family` +
`test_jsonl_backup_round_trip_breaks_if_the_archive_stream_is_truncated`
(`tests/test_cli.py`, beside the existing `export/import archive` tests), correct-by-
construction (the same content-determined `(archived_at, item_id, prior_hash)` ordering H291
relies on), sabotage-verified non-vacuous (importing a truncated archive into B trips the
chain-depth precondition + the read-family equality); suite **3740 passed**. **H292 (the cross-machine recovery dogfood — the whole
decide→restore recovery *workflow* survives a `--with-archive` bundle handoff: on a fresh
machine B rebuilt from the bundle alone, `archive diff --hash` decides and `archive restore
--hash` *acts* — a real recovery write, not a dry-run — so the held copy flips to the chosen
prior, the displaced copy re-archives reversibly, and `doctor`'s `custody.score` holds at 100
through the real write; the operator-workflow layer above H291's non-mutating read-family
tie) shipped 2026-06-23**, `test_recovery_workflow_survives_a_machine_handoff` in
`tests/test_dogfood.py` (sabotage-verified non-vacuous — inverting `_cmd_archive_diff`'s
`would_restore` fails the cross-machine convergence) + `docs/dogfood.md` (new "Taking the
recovery workflow with you — a machine handoff" section, test-count 9→10); suite **3738
passed**. **H293 (the `doctor` archive-integrity check — `custody.archive` flags any archived prior
whose advertised `prior_hash` diverges from its snapshot's `content_hash`, report-only,
the MCP `get_library_health` twin carrying it for free) shipped 2026-06-23**, taken
capability-first ahead of the H292 dogfood lead (a new code/test surface vs. narrating
existing ones; the two are independent), `tests/test_doctor.py` (clean/empty/null/scoped/
divergence/ordering, report-only + exit-0) and `tests/test_mcp.py` (the `get_library_health`
twin converges with the CLI `doctor` field-for-field), ADR 0106 Deferred updated; suite
**3737 passed**. **H291 and H290 both shipped 2026-06-23**,
closing the archive-recovery theme end-to-end — see the checkpoint above. **H291 (the
archive-recovery read-family lossless round-trip)** pins that the whole recovery family —
`archive show --all` (byte-for-byte JSONL), `archive diff` (held↔prior
hashes/fidelities/`changed_fields`/`would_restore`), and `archive restore --dry-run` —
reads field-for-field identically on a library rebuilt from a `export bundle
--with-archive`, over all three selectors, proving the bundle carries enough for the
*entire* recovery surface, not just `archive show`'s latest head;
`test_archive_recovery_read_family_survives_the_with_archive_round_trip`
(`tests/test_bundle.py`) adopts a multi-supersession chain (a `_seed_archived_chain`
helper, strictly-increasing `archived_at` so A's adoption order and B's import order yield
the same `id DESC` newest-first history), round-trips the bundle into a fresh library, and
asserts the read-family equal across A and B; mutation-checked twice (a latest-only archive
trips the chain-depth precondition, a perturbed prior snapshot trips the family
comparison). **H290 (the cross-command write-prediction tie)** pins that `archive diff
<id> <sel>`'s `would_restore` equals `archive restore <id> <sel> --dry-run`'s `restored`
across all three selectors and both the would-change and idempotent-no-op cases (with
matching `prior_hash`/`held_hash`) — two reads of one predicted write, never disagreeing;
mutation-checked by inverting the diff predicate. Suite **3727 passed**. **H289 (the
decide-before-you-restore dogfood —
read `archive diff`, then act, and the act lands exactly on the read's prediction)
shipped 2026-06-22**: `test_archive_diff_decides_then_restore_acts_exactly_as_predicted`
(`tests/test_dogfood.py`) holds `_held_topic()`, adopts one divergent peer capture (one
archived prior), then runs the whole decide → act loop offline — `archive diff` →
`archive restore` → `archive diff --hash <ORIG>` → `archive restore --hash <ORIG>` —
pinning that the diff's `would_restore` *is* the restore's `restored` (with matching
`prior_hash`/`held_hash`/`selector`) on **both** the would-change and the idempotent
no-op cases, that a diff is a true read (the held `content_hash` untouched across each
diff until the `restore` between them), and that `doctor`'s `custody.score` holds at 100
the whole way. Narrated in `docs/dogfood.md`'s new "Deciding before you restore" section
with captured CLI output; test-count 8→9, suite **3725 passed**, sabotage-verified
non-vacuous. **H288 (`scrolls archive diff <id> [--hash H |
--at ISO]`, the decide-before-you-restore read) shipped 2026-06-22**, ADR 0106's
read-surface follow-up to restore-by-version: an operator chose a version to restore by
eyeballing `archive list`/`archive show --all`, but no read *compared* what is held now
against a specific prior. `archive diff` folds the **same** `select_archived_snapshot`
selector restore uses (`--hash`/`--at`, default the latest) against the held copy
(`get_item`) and reports the custody-relevant delta — held↔prior `content_hash`, each
side's `fidelity` tier (`get_fidelity`), the model-complete fields that differ (a new
pure `items.diff_snapshot(held, prior)` over `item_to_dict`), and `would_restore` (the
H286 idempotency predicted *before* the write: the same `content_hash` compare
`merge_item` makes, so `false` when the prior already *is* the held copy). The field
delta keys on every column while `would_restore` keys on `content_hash` alone (what a
restore acts on), so a metadata-only difference can list `changed_fields` while
`would_restore` is `false` — honest, not contradictory. CLI-only read, no write (the
`archive show` gate, MCP twin deferred); an unmatched selector / unknown id is a
could-not-recover (exit 1). **With H288 the archive read/act/recover surfaces are
complete; with H289/H290/H291 shipped (the decide-before-you-restore dogfood, the
cross-command convergence guard, and the read-family round-trip tie), the
archive-recovery theme is closed end-to-end — the forward queue is the cross-machine
recovery dogfood (H292), the `doctor` archive-integrity check (H293 — **shipped
2026-06-23**), and the JSONL-backup round-trip twin (H294), then pure
hardening/integration, above the 6
de-prioritized guards H244–H249.**
**H287 (the restore-by-version dogfood — the H284 analogue, multi-supersession
roll-back narrated in `docs/dogfood.md`) shipped 2026-06-22**: it holds a topic,
adopts a chain v1→v2→v3 over three days (a scripted `cli.datetime` clock spacing the
archive timestamps so `--at` can bisect them offline), inspects the full history via
`archive show <id> --all`, then rolls back by `--hash` to the *intermediate* v1 (not
the latest prior) and by `--at` to the *original*, pinning the three custody points
(held flips to the *chosen* prior / the displaced copy is itself archived and
`archive show`-recoverable / `doctor`'s `custody.score` holds at 100 throughout).
**H286 (`scrolls archive restore <id> [--hash H | --at ISO]`, restore-by-version)
shipped 2026-06-22**, ADR 0106's last deferred archive leg: `archive show <id> | import
items --accept-incoming` restored only the *latest* prior; `archive restore` selects a
*specific* version — `--hash` the prior with that content hash, `--at` the newest archived
at/before the boundary (inclusive), default the latest — and adopts it through the **same**
accept-incoming write via the new `items.select_archived_snapshot` (which folds the same
newest-first `list_archived`/`archived_snapshots` reads `archive show --all` uses, so a bare
restore re-adopts exactly what `archive show` emits). No new write path: the displaced
current copy is itself archived (reversible, §2.4), restoring the already-held content is an
`unchanged` no-op (idempotent), `--dry-run` predicts without writing. **With H286 the
archive-recovery sub-theme (H280–H286) is closed.** **H285 (`scrolls archive show <id>
--all`, the full archived-history read) shipped 2026-06-22**, ADR 0106's deferred "archive
show --all": after several adoptions
`archive show <id>` recovered only the *latest* prior, while the earlier priors were
reachable in the `archive list` index but not re-emittable as re-importable snapshots.
`--all` now emits **every** archived prior for the id as a JSONL stream (newest first, the
`archive list` `id DESC` order), each line the model-complete `item_to_dict` snapshot, so a
multi-supersession item's *whole* recoverable history backs up or inspects, not just its
newest copy. The decisive choice landed as a new `items.archived_snapshots(db_path,
item_id) -> list[ScrollItem]` (the list-returning sibling of the scalar `latest_archived`),
and `latest_archived` was **refactored to be its head** (`archived_snapshots(...)[0]`), so
the single-snapshot recovery (`archive show`) and the full-history read (`archive show
--all`) share one snapshot-parsing read and can never disagree — `archive show` is
byte-identical to `archive show --all`'s first line (convergence by construction, pinned by
`tests/test_cli.py` and `tests/test_items.py`). Default (no `--all`) unchanged (latest only);
an empty history is the same exit-1 could-not-recover as a never-superseded id. CLI-only read,
no schema change, no network — restoring a *specific* older version is the downstream H286
selector over this stream. **H284 (the accept-incoming end-to-end dogfood) shipped 2026-06-22,
closing the archive-recovery sub-theme (H280–H284)**: `tests/test_dogfood.py` now pins
*adopt a peer's better capture* end to end (import a peer bundle → conflict surfaced +
recorded → review via `doctor`/`history` → `import bundle --accept-incoming` adopts +
archives + clears the aggregate → `archive show \| import items --accept-incoming`
restores the prior), with the conflict aggregate moving 0→1→0 and the held `content_hash`
flipping *original→peer→original* while the integrity score holds at 100 throughout
(`docs/dogfood.md` narrates it with captured CLI output). **H282 (`scrolls archive prune` — a retention act bounding the
append-only archive) shipped 2026-06-22**, ADR 0106's deferred retention: `archive prune
(--before ISO | --keep N) [--apply]` bounds the recovery store — `--before` drops priors
archived strictly before a boundary (the `verify --stale-before` precedent), `--keep N`
keeps the most recent N per item (N>=1, so `archive show` always survives). **Report-only
by default** (predict the drop set, write nothing — the H245/H273 dry-run discipline);
`--apply` deletes and warns loudly. Exactly one policy is required (the `reconcile` opt-in
gate), idempotent, and it **only ever DELETEs from `item_archive`** — the held items and
ledger are untouched (the archive is a recovery convenience, not the root of trust — §2.4).
The read-only `select_prunable_archive` (preview) and `prune_archive` (write) fold the one
pure `_select_prunable`, so the preview predicts the write exactly. *(Design note: the slot
named "report-only by default with `--dry-run`"; since prune is Scrolls' first row-deleting
op, the report-only default + explicit `--apply`-to-commit is the custody-safer reading of
that intent — you can't delete by forgetting a flag — while still honoring "dry-run-able".)*
**H281 (an MCP archive *read* twin — `list_archived`/`get_archived`
over MCP, so agents reach the recovery store; the write stays operator-gated) shipped 2026-06-22**,
ADR 0106's deferred MCP read twin, folding the shared `items.archive_entry_dict`/`latest_archived`
the CLI reads (convergence by construction). **H280 (the prior-content archive travels in the
portable bundle — `export bundle --with-archive` + the `export archive`/`import archive` JSONL
siblings, deduped by `(item_id, prior_hash)`) shipped 2026-06-22**, the lossless-round-trip reach
of ADR 0106's recovery store; **H283 (the conflict cross-run delta/trend + readable `maintain`
`_Conflicts:_` line — the clean H267/H268 analogue) shipped 2026-06-22, closing H279's deferred
conflict-over-time leg.** The **conflict-on-import /
reconciliation theme is now closed on *both* resolution directions across all three legs *and* the
over-time axis**, with
**H278 (`import … --accept-incoming`, ADR 0106 + schema v8)** shipping the content-bearing adopt:
detect (H272 `import items`, H273 `import bundle`, H274 the recorded conflict event, ADR 0104) →
read (H275 `doctor`'s scope-level `custody.conflicts` aggregate + the MCP `get_library_health`
twin, H277 the `_Conflicts:_` briefing line on both `export bundle` forms + `scrolls context`,
H279 the `scrolls status` JSON `custody.conflicts` scalar) → **resolve** both ways (H276 `scrolls
reconcile <id> --keep-held` — affirm the held copy, ADR 0105; H278 `scrolls import …
--accept-incoming` — adopt the incoming copy, archiving the prior, ADR 0106). `doctor`
folds the latest recorded conflict-axis
event per held item into `{basis, as_of, items, events}` (primitives
`custody.latest_conflict_events`/`unresolved_conflicts`), counting a conflict **unresolved**
while its latest axis event is *still an open* `conflict` whose `observed_hash` differs from the
held copy's `content_hash` — and H276's `reconcile --keep-held` now *clears* one by recording a
`resolved` event that supersedes it (`latest_conflict_events` reads the `MAX(id)` over the
conflict axis = `conflict` + `resolved`; the status gate clears a keep-held, the hash gate the
future accept-incoming). The conflict axis stays disjoint from the drift axis by construction
(`latest_conflict_events` reads the conflict-axis rows, `latest_events` only the verify
verdicts), held-filtered and `--source`-scopable like the drift block, a report view only; the
`_Conflicts:_` line, `doctor`'s aggregate, and the MCP twin all fold the *same*
`unresolved_conflicts`/`render_custody_conflicts`, so a `reconcile` clears them together. The
prior **consolidation theme (H261–H271) is closed across *every* surface** — work-level
custody is readable (H261), filterable (H262), alarmed (H263 JSON), readable-briefing on both
bundle forms (H264 Markdown + H271 HTML), browsable (H265), stats-summarized (H266),
trend-over-time (H267), readable-trend (H268), on the static compiled `index.md` (H269), *and*
per-work on the compiled `works.md` rollup (H270). The **budget/tier convergence cells
H244–H249** sit below as **de-prioritized but valid regression guards** — each a
correct-by-construction cell of the cross-tier × CLI/MCP × scoped/unscoped ×
untruncated/truncated fidelity matrix (H244 bundle-artifact reproducibility, H245 dry-run
per-id write prediction, H246 unscoped CLI ladder-under-truncation, H247 unscoped MCP
four-way tie, H248 unscoped MCP ladder-under-truncation, H249 both-axes three-way id
partition). Take **H287 next** (the restore-by-version dogfood), then **H288** (`archive
diff`) — **H286 shipped 2026-06-22, closing the archive-recovery sub-theme (H280–H286)**:
`archive restore <id> [--hash H | --at ISO]` restores a *specific* archived prior in place
through the existing accept-incoming write (`select_archived_snapshot` feeding the adoption,
no new write path; reversible, idempotent, `--dry-run`-able). The earlier sub-theme leg
**H284 (the accept-incoming dogfood) shipped 2026-06-22**: the
accept-incoming end-to-end dogfood now pins *adopt a peer's better capture* offline in
`tests/test_dogfood.py` (the conflict aggregate moves 0→1→0, the held content flips
*original→peer→original*, the integrity score never lowered), narrated in `docs/dogfood.md`
with captured CLI output. The sub-theme's earlier slots all shipped 2026-06-22: H282
(`scrolls archive prune (--before ISO | --keep N) [--apply]` bounds the
append-only recovery store, report-only by default + `--apply` to commit, ADR 0106's
deferred retention); H281 (the MCP archive *read* twin
`list_archived`/`get_archived` reaches the recovery store over MCP, the write staying
operator-gated); H280 (the prior-content archive travels in
the portable round-trip via `export bundle --with-archive` + the `export archive`/`import archive`
JSONL siblings, deduped by `(item_id, prior_hash)`); H283 (closing the
conflict-over-time leg — the conflict-on-import theme is closed across detect → read → resolve *and*
the over-time axis). With H284 the archive-recovery sub-theme is closed; the next leads are
H285/H286 (the deferred archive-history reads). Reach
for a guard cell only when no capability is ready. Per-slice
provenance for every *shipped* slot lives in git (`git log --oneline | grep '(H<NN>)'`); the
**Shipped ledger** below is the one-line in-file index (maintenance-rule §4: *git is the changelog*).

**The 2026-06-22 H276 run shipped the conflict-on-import theme's *resolve* leg** — `scrolls
reconcile <id> --keep-held`, the operator act on a recorded conflict (ADR 0105). Detection
(H272–H274) and the scope read (H275/H277) surfaced and counted a divergence but never resolved
it — the held copy is always kept, so `doctor`/the `_Conflicts:_` line flagged every recorded
conflict indefinitely. `reconcile --keep-held` affirms the held copy, recording a typed
`resolved` **conflict-axis** event (`custody.resolution_event` — `prior_hash` = the affirmed
held copy, `observed_hash` = the rejected incoming capture) that **supersedes** the open
conflict: `latest_conflict_events` now reads the `MAX(id)` over the conflict axis (`conflict` +
`resolved`) and `unresolved_conflicts` keeps an item only while its latest axis event is *still
an open* `conflict`. So the resolution clears across **every** conflict surface at once —
`doctor`'s `custody.conflicts`, the `_Conflicts:_` line on both bundle forms + `context`, the
MCP `get_library_health` twin (one shared predicate). **The decisive design choice** (ADR 0105):
*why keep-held ships and accept-incoming is deferred* — the conflict event records only the
incoming **hash**, never the **content** (the importer discarded the bytes — the held copy was
never overwritten), so adopting the peer's capture needs the content **re-supplied** + a
custody-safe prior-content archive (ADR 0098's "re-capture-on-accept", the first held-capture
write — deferred to **H278**); keep-held needs nothing beyond data in hand. Two guarantees hold
by construction: the **held copy is never overwritten** (raw is sacred, custody §2.4 — content +
`content_hash` provably untouched, `reconcile` only appends) and the **original `conflict` event
survives** (append-only — `history --status conflict` still shows *when* a peer disagreed; the
resolution is a new `resolved` row, readable via `history --status resolved`). CLI-only (an
operator-gated write, like `verify`), opt-in (a bare `reconcile <id>` is exit 2), idempotent (a
second `--keep-held` is a `resolved: false` no-op), dry-run-able (`--dry-run` predicts the same
payload + writes nothing — the H245/H273 discipline); a fresh divergent import re-opens via a
higher-`id` `conflict`. The `resolved` event stays off the drift axis (`latest_events` reads only
the verify verdicts — the ADR 0104 isolation). **No schema change, no network** — a deterministic
ledger append. 14 tests (`tests/test_custody.py` ×7, `tests/test_cli.py` ×7). Docs: ADR 0105,
`docs/reconciliation.md`, `docs/cli.md`, README. Full suite green (3586 passed). End-to-end
verified on a real library. **With H276 the theme is closed on detect → read → resolve for the
safe direction; the new leads are H279 (status-JSON conflict scalar) and H278 (`--accept-incoming`).**

**The H274 run (2026-06-22) shipped H274** — a surfaced import conflict is now a **recorded custody
event**, closing the conflict-on-import theme's *detection* leg (H272 `import items`, H273
`import bundle` surfaced the divergence; H274 makes it durable, ADR 0104). H272/H273 printed a
conflict to the report + stderr but left no queryable trace — re-run the import and the
divergence was re-detected from scratch. H274 records each conflict as a typed `conflict` event
on the held item (`prior_hash` = the kept held copy, `observed_hash` = the incoming capture that
disagreed, stamped at import time), queryable on the per-item ledger via `scrolls history <id>
--status conflict`. **The decisive design choice** the slice resolved (ADR 0104): an import
conflict is a **distinct provenance-of-divergence axis**, *not* a verify-drift — the drift axis
means "the live *source* moved" (known only by re-capturing through the adapter, ADR 0098's
`verify`), whereas a conflict involves no source re-capture, only a peer disagreeing, so mapping
it to `drifted` would be fabrication (the M2 honesty). The isolation is total: `latest_events`
now reads `MAX(id)` per item over the verify verdicts only (`WHERE status IN
(CUSTODY_STATUSES)`), so a `conflict` event lives in the ledger and on the `history` timeline yet
**never** enters the drift posture — every surface folding `latest_events` (`doctor`'s
`custody.drift`, `list/search --drift`, scope headlines, `works` aggregate, `weakest_source`,
`maintain`) is unaffected; an item with only a conflict reads `unverified`; a conflict appended
after a real `drifted` verdict never masks it. The new pure `custody.conflict_event(...)`
(reusing the verify-event field semantics, so every serializer + the export/import round-trip
carry it unchanged), `CONFLICT_STATUS`/`LEDGER_STATUSES` (the `history --status` superset), and
the recording in the **shared `cli._merge_items`** (so both lossless importers get it free; the
read-only `_preview_merge_items` records nothing) are the home a future `reconcile` acts on.
**No schema change, no network** — a deterministic content-hash compare. 8 tests (`tests/test_custody.py`:
the `conflict_event` shape + serializer round-trip, `latest_events` excludes a lone conflict, a
conflict-after-drift never overrides the drift posture, `history --status conflict`;
`tests/test_cli.py`: `import items` records an event readable via `history` while `doctor`'s
drift block stays empty + a clean re-import records nothing; `tests/test_bundle.py`: `import
bundle` records via the shared path + the `--dry-run` records nothing). Docs: ADR 0104,
`docs/reconciliation.md` "Shipped: a conflict is a recorded custody event",
`docs/cli.md` (history `--status conflict`, both importers' event recording). End-to-end
verified on a real library (divergent re-import → `conflict` event with held/incoming hashes,
drift posture stays `unverified`, `history --status conflict` surfaces it, `--status drifted`
excludes it). Full suite green (3546 passed). **H274 closes the detection leg; the next legs are
the scope read (H275, `doctor`'s `custody.conflicts`) and the operator act (H276, `reconcile`).**

**The H273 run (2026-06-22) shipped H273** — the conflict-on-import partition now reaches the
**bundle importer**, the second slice of the conflict-on-import / reconciliation-detection
theme (H272 opened it on `import items`). The live `_cmd_import_bundle` looped `insert_item`
and lumped a divergent held id into an opaque `skipped`; H273 routes its items through the
shared `_merge_items` (the H272 primitive — the held copy is never overwritten, but a held id
re-imported with a different `content_hash` is a surfaced `conflict`, not a silent skip) +
`_warn_conflicts` on stderr, and adds `conflicts`/`unchanged`/`conflict` to the report beside
the existing `events`/`orphaned` block. The genuinely new part is the **dry-run prediction**:
the new read-only twin `_preview_merge_items` predicts the conflict set the live merge would
surface (the H245-style "predict the write effect" closure, on the conflict axis), so an
operator merging a peer's bundle can review the divergences before committing. The **decisive
design choice** the slice resolved is the **within-batch simulation**: the live `merge_item`
does INSERT OR IGNORE, so a bundle that *repeats* an id sees its own prior insert (the first
occurrence is the kept copy, a later one conflicts against it); the dry-run writes nothing, so
`_preview_merge_items` records the first occurrence's `content_hash` in a `kept_hash` map to
classify within-batch dups identically — and the repeated id rides `new` (library-absent)
*and* `conflicts` (the bundle disagrees with itself) at once, keeping `new`/`held`
**library-relative** (an id absent before the import stays `new` even if it repeats, the
H239/H245 partition). The live≡preview convergence holds: both paths grow the *same*
`unchanged`/`conflict`/`conflicts` fields, pinned over a mixed conflicting bundle and the
within-bundle-dup edge. **No schema change, no network** — a deterministic content-hash
compare, scoped to the lossless importers where `content_hash` is model-complete. 4 tests in
`tests/test_bundle.py` (live conflict surfaced + stderr warning + held-copy-preserved; dry-run
predicts the conflict set + writes nothing + warns; live≡preview whole-summary under a mixed
conflicting bundle; within-bundle-dup parity on both paths) + 2 updated convergence
assertions. Docs: `docs/cli.md` bundle conflict partition + dry-run prediction + key table,
`docs/reconciliation.md` "both lossless importers". End-to-end verified on a real CLI flow
(export bundle → clean import → idempotent re-import is `unchanged` → divergent-capture bundle:
`--dry-run` predicts the conflict + warns, live import surfaces it + warns, held copy
preserved, dry-run≡live). Full suite green (3538 passed). **H273 lifts the conflict surface to
the bundle importer; the last slice is H274 (lift a surfaced conflict into a recorded custody
event).**

**The H272 run (2026-06-22) shipped H272** — conflict-on-import is now surfaced on the lossless
whole-library importer (`import items`), **opening the conflict-on-import /
reconciliation-detection theme** the H256 checkpoint re-derived. `import items` used
`INSERT OR IGNORE` keyed on id alone, so a re-import of a held id with *different* captured
content was silently dropped into an opaque `skipped` count — a custody blind spot (a
divergence lost). H272 partitions every skip on the `content_hash` (the same captured-content
fingerprint the verify ledger drifts on) into `unchanged` (idempotent re-import) and `conflict`
(the incoming copy disagrees with the held one), surfacing the diverging ids in a structured,
uncapped `conflicts` field **and** a loud bounded stderr warning — while still **never
overwriting** the held copy (raw is sacred; a conflict is a *recorded, surfaced* event, not an
overwrite — custody §2.4, the obsidian reconcile adoption *surface, don't rewrite*). The
**decisive design choices**: (1) compare on **`content_hash`**, not the whole row — a
*derived*-field-only difference (title/category) is `unchanged`, not a conflict (the signal is
content custody, the same fingerprint `verify` drifts on, not every column; pinned by
`test_import_items_title_only_edit_is_unchanged_not_a_conflict`); (2) keep `skipped` as the
backward-compat total with `skipped == unchanged + conflict` as a coherence invariant; (3)
scope to the **lossless** importers (`import items` now, `import bundle` next) where
`content_hash` is a model-complete field — the heterogeneous third-party imports
(bookmarks/Pocket/takeout) keep the simple imported/skipped bool. The shared `items.merge_item`
primitive (`"imported"`/`"unchanged"`/`"conflict"` over the INSERT-OR-IGNORE skip) + the cli
`_merge_items`/`_warn_conflicts` helpers are the home H273's bundle import reuses. **No schema
change, no network** — a deterministic content-hash compare. 5 tests in `tests/test_cli.py`
(idempotent-is-unchanged, title-edit-is-unchanged, surfaces-a-conflict + stderr warning +
held-copy-preserved, mixed-batch partition + the coherence invariant, `merge_item` unit) +
3 updated exact-equality assertions. Docs: `docs/cli.md` import-items conflict table + console
example, `docs/reconciliation.md` "Shipped: conflict-on-import detection". End-to-end verified
on a real library (clean re-import → `unchanged`; a divergent copy → `conflict` + stderr
warning naming the id; held copy preserved). Full suite green (3534 passed). **H272 opens the
conflict-on-import theme; the next lead is H273 (the same partition on `import bundle` + its
dry-run conflict prediction).**

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
| H272 | **Conflict-on-import is surfaced on the lossless whole-library importer (`import items`) — never silently swallowed; opens the conflict-on-import / reconciliation-detection theme (custody §2.4; the obsidian reconcile adoption *detect, surface, don't rewrite*).** The H256 checkpoint re-derived the next theme: with the per-item and consolidation custody surfaces closed, the un-worked custody shape was the **import boundary**. `import items` used `INSERT OR IGNORE` keyed on id alone, so a re-import of a held id with *different* captured content was dropped into an opaque `skipped` count — a divergence silently lost. H272 partitions every skip on the `content_hash` (the same fingerprint the verify ledger drifts on) into `unchanged` (idempotent) and `conflict` (incoming copy disagrees), surfacing the diverging ids in an uncapped structured `conflicts` field **and** a loud bounded stderr warning, while **never overwriting** the held copy (a conflict is a recorded, surfaced event, not an overwrite). **Decisions:** (1) compare on **`content_hash`** not the whole row — a derived-field-only diff (title/category) is `unchanged`, not a conflict; (2) `skipped == unchanged + conflict` (backward-compat total + coherence invariant); (3) scope to the **lossless** importers (`import items` now, `import bundle` H273) where `content_hash` is model-complete — third-party imports keep the imported/skipped bool. Shared `items.merge_item` (`"imported"`/`"unchanged"`/`"conflict"`) + cli `_merge_items`/`_warn_conflicts` are the home H273 reuses. No schema change, no network. 5 tests (`tests/test_cli.py`) + 3 updated exact-equality assertions. Docs: `docs/cli.md` import-items conflict table + console example, `docs/reconciliation.md` "Shipped: conflict-on-import detection". End-to-end verified (clean re-import → `unchanged`; divergent copy → `conflict` + stderr warning; held copy preserved). Full suite 3534 passed. **Opens the conflict-on-import theme; next lead H273 (the same partition on `import bundle` + its dry-run conflict prediction).** | cap 7, cap 1, cap 9 |
| H273 | **The conflict-on-import partition reaches the bundle importer — `import bundle` surfaces `unchanged`/`conflict` (the H272 `_merge_items`/`_warn_conflicts`) *and* its `--dry-run` *predicts* the conflict set the live merge would surface.** The live `_cmd_import_bundle` looped `insert_item` and lumped a divergent held id into an opaque `skipped`; H273 routes its items through the shared `_merge_items` (held copy never overwritten, a different-`content_hash` re-import is a surfaced `conflict`) + `_warn_conflicts`, adding `conflicts`/`unchanged`/`conflict` to the report beside the `events`/`orphaned` block. The genuinely new part is the **dry-run prediction**: the new read-only twin `_preview_merge_items` predicts the conflict set without writing (the H245-style "predict the write effect" closure, on the conflict axis). **Decisive choice — within-batch simulation:** the live `merge_item` does INSERT OR IGNORE so a bundle that *repeats* an id sees its own prior insert (first occurrence kept, a later one conflicts against it); the dry-run writes nothing, so `_preview_merge_items` records the first occurrence's `content_hash` in a `kept_hash` map to classify within-batch dups identically — and the repeated id rides `new` (library-absent) *and* `conflicts` (the bundle disagrees with itself) at once, keeping `new`/`held` library-relative (H239/H245). live≡preview holds: both grow the *same* `unchanged`/`conflict`/`conflicts`. No schema change, no network. 4 tests (`tests/test_bundle.py`) + 2 updated convergence assertions. Docs: `docs/cli.md` bundle conflict partition + dry-run prediction + key table, `docs/reconciliation.md` "both lossless importers". End-to-end verified (clean import → idempotent `unchanged` → divergent bundle: dry-run predicts + warns, live surfaces + warns, held copy preserved, dry-run≡live). Full suite 3538 passed. **Lifts the conflict surface to the bundle importer; last slice H274 (lift a surfaced conflict into a recorded custody event).** | cap 9, cap 7, cap 1 |
| H274 | **A surfaced import conflict becomes a recorded custody *event* — closing the conflict-on-import theme's *detection* leg (ADR 0104).** H272/H273 printed a conflict to the report + stderr but left no durable trace — re-run the import and the divergence was re-detected from scratch, never queryable. H274 records each conflict as a typed `conflict` event on the held item (`prior_hash` = the kept held copy, `observed_hash` = the incoming capture that disagreed, stamped at import time), queryable via `scrolls history <id> --status conflict`. **Decisive choice (ADR 0104):** an import conflict is a **distinct provenance-of-divergence axis**, *not* a verify-drift — the drift axis means "the live *source* moved" (re-capture through the adapter, ADR 0098), a conflict involves no source re-capture (only a peer disagreeing), so mapping it to `drifted` would be fabrication (the M2 honesty). `latest_events` now takes `MAX(id)` per item over the verify verdicts only (`WHERE status IN (CUSTODY_STATUSES)`), so a `conflict` event lives in the ledger and on the `history` timeline yet **never** enters the drift posture — `doctor`'s `custody.drift`, `list/search --drift`, scope headlines, `works` aggregate, `weakest_source`, `maintain` all unaffected; an item with only a conflict reads `unverified`; a conflict after a `drifted` verdict never masks it. New pure `custody.conflict_event(...)` (reusing the verify-event field semantics → every serializer + export/import round-trip carry it unchanged), `CONFLICT_STATUS`/`LEDGER_STATUSES` (the `history --status` superset), recorded in the **shared `cli._merge_items`** (both lossless importers; read-only `_preview_merge_items` records nothing). No schema change, no network. 8 tests (`tests/test_custody.py` ×4, `tests/test_cli.py` ×2, `tests/test_bundle.py` ×2). Docs: ADR 0104, `docs/reconciliation.md`, `docs/cli.md`. Full suite 3546 passed. **Closes the detection leg; next legs H275 (`doctor`'s `custody.conflicts` scope read) + H276 (a reviewed `reconcile` resolution).** | cap 1, cap 3, cap 9 |
| H275 | **A `doctor` scope-level *conflict aggregate* (`custody.conflicts`) — the read-aggregate sibling of `custody.drift`, opening the conflict-on-import theme's *read* leg (ADR 0104's first deferred read).** H274 records each import conflict per-item (queryable via `scrolls history <id> --status conflict`) but gave **no library-scope view** — an operator who merged several peer bundles couldn't ask "how many held items carry an unresolved import conflict, and which?" without scanning every item's history. `doctor` now folds the latest recorded import-`conflict` event per held item into `custody.conflicts` `{basis: "import_ledger", as_of, items, events}` (new pure primitives `custody.latest_conflict_events` — MAX(id) per item over the `conflict` rows, the conflict-axis sibling of `latest_events` — and `custody.unresolved_conflicts`). **Decisive choice:** a conflict is counted **unresolved** while the *latest* conflict event's `observed_hash` still differs from the held copy's current `content_hash` — **not** by mere existence of a `conflict` event. The held copy is never auto-overwritten (raw is sacred), so every recorded conflict is unresolved today, but the predicate is **resolution-aware**: a future `reconcile` (H276) that adopts the incoming content clears it with **no** special "resolved" event (the `latest_events` held-filter precedent). The two ledger axes stay **disjoint by construction** (`latest_conflict_events` reads only `conflict` rows, `latest_events` only the verify verdicts) — a conflict never inflates `custody.drift`, a drift verdict never appears here. Held-filtered like the drift block and, unlike the cross-source `custody.works` alarm, **source-attributable** (`--source S` scopes it for free). A **report view only**, never `issues`/`fixed`/the exit code; the MCP `get_library_health` twin carries it **for free** (returns `run_doctor`'s whole custody block), converging field-for-field with the CLI. No schema change, no network. 10 tests (`tests/test_custody.py` ×5, `tests/test_cli.py` ×4, `tests/test_mcp.py` ×1) + 2 updated exact-shape assertions (`tests/test_doctor.py`). Docs: ADR 0104 (deferred bullet marked shipped), `docs/reconciliation.md` "Shipped: a `doctor` scope-level conflict aggregate", `docs/cli.md`. End-to-end verified (divergent re-import → `custody.conflicts.items == 1` with held/incoming hashes, drift block stays empty). Full suite 3556 passed. **Opens the read leg; next lead H277 (the readable `_Conflicts:_` briefing line) + H276 (a reviewed `reconcile` resolution).** | cap 1, cap 3, cap 9 |
| H276 | **A reviewed `reconcile --keep-held` resolution — the operator *act* on a recorded conflict, closing the conflict-on-import theme's *resolve* leg for the safe direction (ADR 0105).** Detection (H272–H274) + the scope read (H275/H277) surfaced and counted a divergence but never resolved it — the held copy is always kept, so `doctor`/the `_Conflicts:_` line flagged every recorded conflict indefinitely. `scrolls reconcile <id> --keep-held` affirms the held copy, recording a typed `resolved` **conflict-axis** event (`custody.resolution_event` — `prior_hash` = the affirmed held copy, `observed_hash` = the rejected incoming capture) that **supersedes** the open conflict: `latest_conflict_events` now reads `MAX(id)` over the conflict axis (`CONFLICT_AXIS_STATUSES` = `conflict` + `resolved`) and `unresolved_conflicts` keeps an item only while its latest axis event is *still an open* `conflict` (status gate clears a keep-held; the H275 hash gate — observed == held — coexists for the future `--accept-incoming`). So the resolution clears across **every** conflict surface at once — `doctor`'s `custody.conflicts`, the `_Conflicts:_` line on both bundle forms + `context`, the MCP `get_library_health` twin (one shared predicate). **Decisive choice (ADR 0105):** *why keep-held ships and accept-incoming is deferred* — the conflict event records only the incoming **hash**, never the **content** (the importer discarded the bytes — held copy never overwritten), so adopting the peer's capture needs the content **re-supplied** + a custody-safe prior-content archive (ADR 0098's "re-capture-on-accept" — deferred to H278); keep-held needs nothing beyond data in hand. Guarantees by construction: held copy **never overwritten** (content + `content_hash` provably untouched, `reconcile` only appends), original `conflict` event **survives** (append-only — `history --status conflict` still shows when; `--status resolved` shows the decision). CLI-only (operator-gated like `verify`), opt-in (bare `reconcile <id>` is exit 2), idempotent (`resolved: false` no-op on re-run), dry-run-able (`--dry-run` predicts same payload + writes nothing — H245/H273 discipline); a fresh divergent import re-opens via a higher-`id` `conflict`. The `resolved` event stays off the drift axis (`latest_events` reads only verify verdicts — the ADR 0104 isolation); new `current_conflict(db_path, item)` per-item helper folds the same predicate over one item so `reconcile`'s target == what `doctor`/the line count. No schema change, no network. 14 tests (`tests/test_custody.py` ×7, `tests/test_cli.py` ×7). Docs: ADR 0105, `docs/reconciliation.md` "Shipped: a reviewed `reconcile` resolution — keep-held", `docs/cli.md` (`reconcile` + `history --status resolved`), README. Full suite 3586 passed. End-to-end verified (divergent import → conflict → dry-run predicts/writes nothing → live reconcile clears `doctor` to 0 → idempotent no-op → both `conflict` + `resolved` on `history` → held copy untouched → no-flag exit 2). **Closes the theme on detect → read → resolve for the safe direction; new leads H279 (status-JSON conflict scalar) + H278 (`--accept-incoming`, the content-bearing supersession).** | cap 1, cap 3 |
| H277 | **A readable `_Conflicts:_` briefing line — the readable completion of H275's JSON `custody.conflicts` aggregate (ADR 0104), closing the conflict-on-import theme's *read* leg across both surfaces.** H275 put the import-conflict aggregate on `doctor`'s JSON read (+ MCP twin), but the readable briefings an agent skims carried only the per-item drift/source headlines, never the scope-level conflict count. The three Markdown briefings — `export bundle` (Markdown `build_bundle` *and* HTML `build_bundle_html`, the H264/H271 two-form parity) and `scrolls context` — now render a one-line `_Conflicts: N item(s) carry an unresolved import conflict._` (HTML twin `<p class="custody-conflicts">`), the **import-conflict-axis counterpart of the drift `_Attention:_` line** (`render_custody_attention`, H159). The shared `custody.render_custody_conflicts` folds the *same* `unresolved_conflicts` over the same `latest_conflict_events` map `doctor`'s `custody.conflicts` reads, so the readable count and the JSON `items` converge by construction. **Decisive choice:** the line **names no command** — the resolution act (a reviewed `reconcile`, H276) does not exist yet, so it surfaces the count only (the `at_risk_signal` orphan-command discipline; per-item detail on `doctor`'s `custody.conflicts.events` + `scrolls history <id> --status conflict`). Folded over the briefing's own `items` (the per-*item* custody axis the headline/`_Attention:_` use), gated to `connected`+ on `context` like the headline (the `index` tier reads no ledger), export-only on the bundle (outside the lossless `@generated` JSONL fence). Honest absence — no line when nothing unresolved in scope, and a *resolved* conflict (held copy now matches the incoming hash) drops out via the resolution-aware predicate. No schema change, one `latest_conflict_events` read. 16 tests (`tests/test_bundle.py` ×7, `tests/test_context.py` ×6, `tests/test_custody.py` ×3). Docs: `docs/reconciliation.md` "Shipped: a readable `_Conflicts:_` briefing line", `docs/cli.md`. End-to-end verified (divergent peer-bundle import → `_Conflicts: 1 …_` on both bundle forms + `context`, omitted at `index`, converges with `doctor`'s `custody.conflicts.items == 1`). Full suite 3572 passed. **Closes the read leg across JSON + readable surfaces; last theme leg is the operator act H276 (a reviewed `reconcile`).** | cap 1, cap 3, cap 9 |
| H279 | **A `conflicts` scalar on `scrolls status`'s machine `custody` snapshot — the JSON-status counterpart of H277's readable `_Conflicts:_` line, closing the conflict-on-import theme's *read* leg across *every* surface.** H277 scoped the readable conflict count to the three Markdown briefings (`export bundle` ×2 + `context`); `scrolls status` renders no readable line, carrying the machine `custody_snapshot` block instead (`score`/`tiers`/`drift`/`enrichment_stale`/`summaries_stale`/`at_risk`) — but **not** an import-conflict count, so an agent reading `status` for a custody dashboard saw drift and at-risk-works but not unresolved conflicts. H279 folds the *same* `unresolved_conflicts` over `latest_conflict_events` (`doctor`'s `custody.conflicts` / the `_Conflicts:_` line read) into the shared `maintain.custody_snapshot` primitive (`custody.get("conflicts", {}).get("items", 0)`, the defensive read `at_risk` uses). Because `status`'s `custody` block *is* `custody_snapshot(run_doctor(...))`, the scalar converges field-for-field with `doctor`'s `custody.conflicts.items` **by construction** — a pure read of the report `run_doctor` already produced, no extra ledger query, no schema change. **Resolution-aware** (a `reconcile --keep-held` clears it) and **source-scopable for free** (`status --source <S>` narrows the conflict fold like the drift scalar, since a held item owns a source — unlike the whole-library-only cross-source `at_risk` alarm). MCP `get_library_health` already carries the full `custody.conflicts` block (spreads `**custody`) → no change. 6 tests (`tests/test_cli.py` ×4: surfaces + converges + off the drift axis, clears after `reconcile`, honest 0, source-scopes; `tests/test_maintain.py` ×2: primitive records `conflicts` + defaults to 0) + exact-shape `custody_snapshot`/`_custody_headline` assertions updated. Docs: `docs/cli.md` (`status` `conflicts` scalar), `docs/reconciliation.md` "Shipped: a conflict scalar on `scrolls status`". End-to-end verified (divergent import → `status.custody.conflicts == 1`, `--source` scopes, converges with `doctor`, clears to 0 after `reconcile`). Full suite 3592 passed. **Deferred (the `at_risk` → H267/H268 analogue): the cross-run `delta`/`--trend` treatment + a readable `maintain` `_Conflicts:_` line — shipped in H283. Closes the conflict-on-import *read* leg across every surface; only H278 (`--accept-incoming`) remains.** | cap 10, cap 1 |
| H278 | **`--accept-incoming` — the content-bearing reconcile resolution that *adopts* the peer's capture (ADR 0106; the first import-path write that changes a held capture), closing the conflict-on-import theme on *both* resolution directions.** ADR 0105 shipped keep-held and deferred accept-incoming because the conflict event records only **hashes**, never the incoming *content* (the importer discarded the bytes — held copy never overwritten), so at `reconcile` time the content is gone. Two design questions resolved: **(1)** *where the content comes from* → the **import path** (`import items`/`import bundle --accept-incoming`), not `reconcile` — the content is in hand only at the merge (a `reconcile --accept-incoming` is impossible by construction); **(2)** *how the prior stays recoverable* (raw is sacred, §2.4) → adoption replaces the held row but **archives the prior copy first** into a new append-only `item_archive` table (schema v8: model-complete `item_to_dict` snapshot + `prior_hash`/`superseded_by`/`archived_at`), via the single-transaction `items.adopt_incoming` (archive-insert + items-UPDATE atomically, archive-before-replace) — *not* a destructive overwrite. The adoption records a new `custody.SUPERSEDED_STATUS = "superseded"` on the conflict axis (`CONFLICT_AXIS_STATUSES = (conflict, resolved, superseded)`) via the pure `supersession_event` (`prior_hash` = archived prior, `observed_hash` = adopted incoming), distinct from `resolved` because it *changes* content; it clears the conflict on **both** gates of `unresolved_conflicts` (status — latest axis event is `superseded`; hash — held copy *is* the incoming) so `doctor`/`status`/the `_Conflicts:_` line/MCP all drop it via the one shared predicate, and stays **off the drift axis** (`latest_events` reads only `CUSTODY_STATUSES`, the ADR 0104 isolation). **Idempotent by construction** (once adopted, a re-import is `unchanged` — no second archive/event), **dry-run-able** on the bundle importer (`_preview_merge_items` predicts the adopted set, writes nothing — the H245/H273 discipline on the adopt axis), and **recoverable** via new `scrolls archive list` (the recovery index) / `scrolls archive show <id>` (re-emits the latest archived prior as a re-importable `export items` line) so restore is **symmetric** (`archive show <id> \| import items /dev/stdin --accept-incoming` re-adopts the prior, archiving the current copy in turn). Merge returns `{imported, skipped, unchanged, conflict, adopted}` (`imported + unchanged + adopted` totals the input, `skipped == unchanged + conflict` holds with `conflict == 0` under accept), loud on stderr (`_warn_adopted`), CLI-only (operator-gated write, §2.4). The archive is a **local recovery store**, not part of the lossless round-trip (the `superseded` event travels; the prior bytes stay local — carrying them in bundles is deferred). No network. 21 tests (`tests/test_db.py` ×2 v8 migration; `tests/test_custody.py` ×5 the `superseded` event/axis/clears; `tests/test_items.py` ×6 `adopt_incoming`/archive reads/round-trip; `tests/test_cli.py` ×6 + `tests/test_bundle.py` ×2 the importers/archive/dry-run) + 6 exact-payload assertions updated for the `adopted` key. Docs: ADR 0106, `docs/reconciliation.md`, `docs/cli.md` (`--accept-incoming` on both importers + `archive list`/`show`, schema pin → 8), README. Full suite 3613 passed. End-to-end verified (divergent import → plain conflict kept → `--accept-incoming` adopts + archives + clears `doctor`/`status` to 0 + `superseded` on `history`; bundle dry-run predicts; `archive show` round-trips back through `--accept-incoming`). **Closes the conflict-on-import theme on both resolution directions (keep-held + accept-incoming) across detect → read → resolve.** | cap 1, cap 3 |
| H283 | **The conflict-over-time leg — the unresolved-conflict scalar is *differenced* (cross-run `delta` + `--history`/`--trend` `conflicts_change` axis) and a readable `_Conflicts:_` line rides the `maintain` report + trend, the clean H267/H268 analogue closing H279's deferred leg.** H279 *recorded* the unresolved-import-conflict count on `status`'s snapshot and the shared `maintain.custody_snapshot` but never *differenced* it. H283 lifts the exact at-risk-works machinery (H267/H268) to the conflict axis: `compute_delta` subtracts the scalar (`delta["conflicts"]`, degrade-safe — pre-H279 baseline reads 0, first run reads null), `compute_trend` differences it (a new `conflicts_change` axis beside `at_risk_change`, telescoping to the per-run `--history` deltas), and the shared `maintain.conflicts_headline(count, change, *, span)` (the conflict twin of `at_risk_headline`) renders the `maintain`/trend `_Conflicts: N (▲M since last run)._` / `_Conflicts: N (▲M over K runs)._` line — `▲` worse, `▼` better, `0` no-change, bare `_Conflicts: N._` when no baseline (the H267 honesty). The line rides the MCP `run_maintenance` twin for free; like `at_risk_headline` it embeds the delta's signed change → run-position-dependent, so the MCP↔CLI convergence test (`_audit_fields`) strips it beside `delta`/`recorded_at`. Two design points: **(1)** recorded-but-never-a-`posture`-trigger — a peer divergence moves *neither* the integrity score *nor* the drift axis (the held copy is never overwritten, §2.4), so posture stays integrity-only (the H115/H267 precedent); **(2)** unlike the whole-library-only at-risk line, the conflict count is **source-attributable**, so a `--source S` pass narrows it (a held item owns a source). No schema change, no network — a pure fold over the snapshot H279 records. 18 new tests in `tests/test_maintain.py` (`conflicts_headline` ×5, `compute_delta` ×3, `compute_trend` ×5, integration report/`--history`/`--trend`/`--source` ×5) + modified guards in `tests/test_custody_convergence.py` (the conflict axis telescopes with drift/coverage/staleness/at-risk; `_audit_fields` strip extended) and `tests/test_mcp.py` (the `conflicts_headline` field on the `run_maintenance` shape). Docs: `docs/reconciliation.md` "Shipped: the conflict-over-time leg", `docs/cli.md` (the `maintain` report/trend `_Conflicts:_` line + the MCP twin row). Full suite 3631 passed. End-to-end verified (divergent peer import → `_Conflicts: 1 (▲1 since last run)._` → `reconcile --keep-held` → `_Conflicts: 0 (▼1 since last run)._`; `--trend` distils the 0→1→0 window). **With H283 the conflict-on-import theme is closed across *every* surface including the over-time axis; the new lead is the archive-recovery sub-theme H280–H282/H284.** | cap 10, cap 1 |
| H280 | **The prior-content archive travels in the portable round-trip — `export bundle --with-archive` + the `export archive`/`import archive` JSONL siblings, so "take it with me" includes the recovery store (ADR 0106's first deferred extension).** ADR 0106 made adoption custody-safe *locally* (the superseded prior is archived, recoverable via `scrolls archive show`), but left the archive a **local** store: a `superseded` event travels in the lossless round-trip while the archived prior *bytes* stay behind, so a library rebuilt from a bundle could read *that* an adoption happened (the event) but not recover the prior copy. **Design choices resolved:** **(1)** *opt-in, not always-on* — `export bundle --with-archive` appends an optional **third `@generated` region** (the in-scope items' `item_archive` snapshots) beside the items + events blocks, because the archive can be large (a model-complete prior body per adoption) and the `superseded` event already documents the adoption; **without the flag the bundle is byte-identical to a pre-H280 one** (the H238/H244 byte-identity + round-trip guarantees untouched). **(2)** *the JSONL surface is a standalone `export archive`*, not a mix into `export items` (two record types in one stream is wrong) — `export archive`/`import archive` are the whole-library siblings of `export events`/`import events`, the third member of the lossless backup family (items, events, archive). **(3)** *import is unconditional* — `import bundle` restores any archive block present (the flag is an export concern only), deduped by `(item_id, prior_hash)` (the H67 events-dedup precedent on the archive identity), so a re-import / overlapping union is a no-op. **(4)** *content-deterministic order* — records sort by `(archived_at, item_id, prior_hash)`, independent of the per-library autoincrement id (never exported), so a re-export from a rebuilt library reproduces the block **byte-for-byte**, and within an item the latest prior still imports to the highest id so `archive show` returns the most-recent. The archive stays a **standalone recovery store** keyed by `item_id` with no held-row interaction (only appends to `item_archive`), so unlike the events restore it needs **no orphan split**. The `--dry-run` predicts the archive restore without writing (`preview_import_archive`, the H220/H245 discipline on the archive axis); the HTML bundle embeds the block under `--with-archive` for parity (export-only). New: `items.ArchiveRecord`/`archived_records`/`archive_export_dict`/`archive_from_dict`/`dump_archive_export`/`import_archive`/`preview_import_archive`, `archive_export.load_archive_export`, `bundle._archive_block`/`parse_bundle_archive`. **No schema change** (the v8 `item_archive` table is unchanged), no network. 35 tests (`tests/test_items.py` ×11 the reader/dedup/preview/round-trip; `tests/test_archive_export.py` ×10 JSONL framing+validation; `tests/test_bundle.py` ×7 lean-default/`--with-archive`/round-trip/byte-identical/idempotent/dry-run/HTML; `tests/test_cli.py` ×14 `export archive`/`import archive` round-trip/idempotency/`--id`/empty/error) + 2 exact-shape `import bundle` payload assertions extended for the `archive` key. Docs: ADR 0106 (deferred bullet marked shipped), `docs/reconciliation.md` "Shipped: the prior-content archive travels in the portable round-trip", `docs/cli.md` (`export archive`/`import archive` + `export bundle --with-archive` + the `archive` import key), README. Full suite 3666 passed. End-to-end verified (default bundle 2 regions / `--with-archive` 3 regions → import into fresh library → `archive show` recovers the prior → re-export byte-identical → re-import dedups → dry-run predicts). **The recovery store now round-trips losslessly; next lead H281 (an MCP archive *read* twin).** | cap 9, cap 5 |
| H281 | **An MCP archive *read* twin — `list_archived` / `get_archived`, so agents reach the prior-content recovery store over MCP (ADR 0106's deferred MCP twin, read side only).** `archive list`/`archive show` were CLI-only: an agent over MCP could read *that* an adoption happened (the `superseded` event via `get_scroll_history`, the cleared `custody.conflicts` via `get_library_health`) but not reach the recovery store itself. H281 adds the same CLI split over MCP — **`list_archived(item_id=None)`** is the recovery *index* (the `{count, archived}` metadata of what an adoption superseded — `{item_id, prior_hash, superseded_by, archived_at}`, newest first, scopable to one item, honest empty before init / on a never-adopted library) and **`get_archived(item_id)`** is the recovery *snapshot* (the model-complete, re-importable `item_to_dict` prior, so an agent can recover the bytes and hand them back to a CLI restore; a never-superseded/unknown id is the could-not-recover error, the `archive show` exit-1 twin). **Decisive choice:** the payload shape mirrors the CLI split — metadata list vs. the full re-importable snapshot. Both fold the *same* primitives the CLI reads (the new shared `items.archive_entry_dict` serializer — CLI `_cmd_archive_list` refactored to fold it too — and `items.latest_archived`), so the surfaces converge by construction (pinned by `archive list`/`archive show` convergence ties). The **write stays operator-gated** (custody §2.4): `import … --accept-incoming` and the symmetric restore remain CLI acts; this is the *read* twin only. Registered tool surface grows 22 → 24. **No schema change, no network** — a pure read fold. 9 tests (`tests/test_mcp.py`: index + four-field row, honest empty before-init / never-adopted, `item_id` scope, the two CLI-convergence ties, the re-importable snapshot, no-prior + unknown-id could-not-recover errors) + the registered-surface assertion. Docs: ADR 0106 (deferred MCP-read-twin bullet marked shipped), `docs/reconciliation.md` "Shipped: an MCP archive read twin", `docs/cli.md` (`archive show` MCP-read note), `_INSTRUCTIONS`. Full suite 3675 passed. End-to-end verified (adopt → `list_archived` indexes the prior → `get_archived` recovers the model-complete snapshot as lists → no-prior raises → 24 tools registered). **The archive read now travels everywhere; next lead H282 (`archive prune` retention), then H284 (the accept-incoming dogfood).** | cap 6, cap 1 |
| H282 | **`scrolls archive prune (--before ISO \| --keep N) [--apply]` — a retention act bounding the append-only recovery store (ADR 0106's deferred retention).** The `item_archive` grows unbounded (every accept-incoming adoption snapshots the prior, the symmetric restore appends more). H282 bounds it with two mutually-exclusive policies, exactly one required (a bare prune / both → exit 2, the `reconcile` opt-in gate): **`--before ISO`** drops priors archived *strictly before* a boundary (date-only → UTC midnight via `parse_since`, the `verify --stale-before` precedent; may drop an item's latest prior — the honest time-bound consequence) and **`--keep N`** keeps the most recent N priors per item (N>=1 enforced, so the latest prior always survives and `archive show` keeps recovering it — a clean recovery invariant the count policy guarantees). **Decisive question:** *is pruning a custody violation?* — no: raw-is-sacred protects the **held** copy, a superseded prior is already a deliberate replacement, and the archive is a *recovery convenience*, not the root of trust (§2.4) — so it is custody-safe provided the act is explicit and never touches a held row (it only DELETEs from `item_archive`; a test pins the held copy byte-for-byte + ledger unchanged across a prune). **Report-only by default** (predict the drop set, write nothing — the H245/H273 dry-run discipline); `--apply` deletes + warns loudly (`_warn_pruned`). *Design note:* the slot named "report-only by default with `--dry-run`"; since prune is Scrolls' first row-deleting op, report-only default + explicit `--apply`-to-commit is the custody-safer reading (you can't delete by forgetting a flag) while still honoring "dry-run-able". The read-only `items.select_prunable_archive` (preview) and `items.prune_archive` (write) fold the one pure `items._select_prunable`, so the preview predicts the write exactly; idempotent (second `--apply` drops 0); CLI-only, **no schema change, no network**. 16 tests (`tests/test_items.py` ×7 the per-item keep / strictly-before selection, preview≡apply, idempotency, held-row+ledger untouched, empty-archive no-op; `tests/test_cli.py` ×9 the policy gate, `--keep 0`/malformed-`--before` rejections, report-only writes nothing, `--apply` drops+warns+keeps-latest-recoverable, before-clears-archive, clean-library empty report). Docs: ADR 0106 (retention bullet marked shipped), `docs/reconciliation.md` "Shipped: `archive prune`", `docs/cli.md`, README. Full suite 3691 passed. End-to-end verified (3 priors → report-only leaves archive at 3 → `--apply --keep 1` drops 2, keeps latest, `archive show` recovers it → idempotent re-apply drops 0 → `--before 2099` clears all). **The archive-recovery sub-theme's retention leg is closed; the last sub-theme slot is H284 (the accept-incoming dogfood).** | cap 1 |
| H284 | **An end-to-end *adopt a peer's better capture* dogfood — the accept-incoming flow on both surfaces, offline + fixture-driven, narrated in `docs/dogfood.md` with captured before/after output (the M5 dogfood discipline on the new write), closing the archive-recovery sub-theme.** The existing dogfood proves *hold → prove → detect → take it with me*; H278 added a genuinely new custody move — *adopt* a diverging peer capture while keeping the prior recoverable, the first import path that **changes** a held capture — that no dogfood exercised end-to-end. `test_adopt_a_peers_better_capture_flips_the_held_copy_and_clears_the_conflict` (`tests/test_dogfood.py`) holds `_held_topic()` in a `library` home, has a `peer` home export a bundle with one diverging arxiv capture (a fuller body, a fresh `content_hash`; the two web scrolls byte-identical), then runs the flow: `import bundle` (no flag → the conflict is **surfaced + recorded**, the held copy kept) → review via `doctor`/`history --status conflict` → `import bundle --accept-incoming` (adopt → the held row is replaced, its prior archived, a `superseded` event clears the conflict) → `archive show <id> > prior.jsonl` → `import items prior.jsonl --accept-incoming` (the symmetric restore — the held content flips back, the peer copy archived in turn). **The two custody points pinned:** the **conflict aggregate moves 0 → 1 → 0** (`doctor`'s `custody.conflicts.items`) and the **held `content_hash` flips *original → peer → original* while `custody.score` holds at 100 throughout** — adoption swaps one full-fidelity capture for another and the displaced one is archived (§2.4: a re-fetch that disagrees is a custody *event*, never a loss), so integrity is never lowered and every prior stays recoverable (the flip is fully reversible). Reuses the `home` factory's side-by-side library/peer homes (the H206/H210 self-healing-dogfood shape) and the M4 bundle round-trip; `adopt_incoming` swaps the row without re-rendering, so the held scroll the prior render left in place keeps the fidelity audit honest (a real agent runs `kb` after — noted in the doc). Test-only + docs, no production change. 1 new test (suite 3692 passed). Docs: `docs/dogfood.md` new "Adopting a peer's better capture — the accept-incoming flow" section with captured CLI output (detect/adopt/restore JSON), test-count + ADR 0106 reference updated. End-to-end verified on a real library (the captured output *is* the live CLI run). **Closes the archive-recovery sub-theme (H280–H284); the queue holds only the de-prioritized guard cells H244–H249 and the new read-history slices H285/H286 above the next checkpoint.** | cap 8, cap 3 |
| H285 | **`scrolls archive show <id> --all` — emit an item's *full* archived history, not just the latest prior (ADR 0106's deferred "archive show --all").** `archive show <id>` recovered only the **most-recently** superseded copy (the latest `item_archive` row); after several adoptions the *earlier* priors were reachable in the `archive list` index but not re-emittable as re-importable snapshots — a multi-supersession item's deeper history could be inspected (metadata) but not backed up (bytes). `--all` now emits **every** archived prior for the id as a JSONL stream, **newest first** (the `archive list` `id DESC` order), each line the model-complete `item_to_dict` snapshot — so the whole recoverable history backs up or inspects as re-importable `export items` lines, not just the head. **Decisive choice:** a new `items.archived_snapshots(db_path, item_id) -> list[ScrollItem]` (the list-returning sibling of the scalar `latest_archived`, folding the same `snapshot` column over *all* rows for the id by `id DESC`), and `latest_archived` was **refactored to return its head** (`archived_snapshots(...)[0] if … else None`) — so the single-snapshot recovery (`archive show`) and the full-history read (`archive show --all`) share **one** snapshot-parsing read and can never disagree: `archive show` is byte-identical to `archive show --all`'s first line (convergence by construction). Default (no `--all`) is unchanged (latest only — byte-identical to pre-H285); an **empty history is the same exit-1 could-not-recover** as a never-superseded/unknown id (an empty stream is not a recovery). Restoring a *specific* older version is the downstream H286 selector over this stream. **CLI-only read, no schema change, no network** — a pure fold over `item_archive` (pre-v8 tolerant, returns `[]`). 7 tests (`tests/test_items.py` ×4: `archived_snapshots` all-priors-newest-first + matches `list_archived` order, `latest_archived` is its head, `[]` for never-superseded, pre-v8 tolerant; `tests/test_cli.py` ×3: `--all` emits N lines newest-first for an N-adoption item + default still one line + convergence with the head, single-prior `--all` ≡ default, never-superseded `--all` exit-1). Docs: roadmap queue/checkpoint advanced (lead → H286), ADR 0106 deferred bullet marked shipped. Full suite **3699 passed**. End-to-end verified (2 adoptions → `archive show` one line latest, `archive show --all` two lines newest-first, default ≡ `--all` head, each line a re-importable body). **The archive-recovery reads now reach the full history; next lead H286 (`archive restore --hash/--at`, restore-by-version over this stream — now precondition-clear).** | cap 1, cap 5 |
| H286 | **`scrolls archive restore <id> [--hash H \| --at ISO]` — restore a *specific* archived prior in place, not only the latest (ADR 0106's last deferred archive leg, restore-by-version).** `archive show <id> \| import items --accept-incoming` restored only the *latest* prior; after multiple supersessions an operator may want a *specific older* version back. `archive restore` adds a version selector — `--hash <prior_hash>` (the archived prior with that content hash), `--at <ISO>` (the **newest** prior archived at/before the boundary, the `verify --stale-before` normalization, **inclusive**), default the latest — and adopts the chosen prior through the **same** accept-incoming write, so there is **no new write path**. **Decisive choice:** a new `items.select_archived_snapshot(db_path, item_id, *, prior_hash, at) -> (ArchiveEntry, ScrollItem) | None` folds the *same* newest-first `list_archived` (metadata, for the predicate) zipped with `archived_snapshots` (bodies) `archive show --all` reads — so a bare restore returns `archived_snapshots[0]` = `latest_archived` exactly (convergence by construction: it re-adopts precisely what `archive show` emits) — then feeds the selected prior to the existing `_merge_items` accept-incoming merge (→ `adopt_incoming`: archive the *currently-held* copy, replace, record `superseded`). So restore-by-version stays custody-safe (the displaced current copy is itself archived, recoverable — fully reversible, §2.4) and idempotent (restoring the already-held content is an `unchanged` no-op — falls out of the content-hash compare). At most one selector (exit 2); an unmatched `--hash`/`--at` or unknown id is a could-not-recover (exit 1); a malformed `--at` is a usage error (exit 2, the `archive prune --before` precedent); `--dry-run` predicts the decision via the read-only `_preview_merge_items` and writes nothing (H245/H273). The decision reports `{selector, prior_hash, archived_at, held_hash, outcome (adopted\|unchanged\|imported), restored}`. **CLI-only write, no schema change, no network.** 13 tests (`tests/test_items.py` ×5: `select_archived_snapshot` default/by-hash/by-`--at`-boundary (inclusive + newest-at-or-before)/unmatched/never-superseded+pre-v8; `tests/test_cli.py` ×8: restore by hash / default latest / by `--at` / idempotent no-op / `--dry-run` writes nothing / unmatched selector exit 1 / both-selectors+malformed-`--at` exit 2 / unknown id exit 1). Docs: `docs/cli.md` new section, README CLI line, ADR 0106 deferred bullet marked shipped, roadmap queue/checkpoint advanced. Full suite **3712 passed**. End-to-end verified on a real library (`--at` bisect picks the right version, `--hash`, the displaced copy archived + recoverable, `--dry-run` no-write, unmatched exit 1). **Closes the archive-recovery sub-theme (H280–H286); only the operator-gated MCP accept-incoming *write* twin stays deferred. Next leads H287 (the restore-by-version dogfood) + H288 (`archive diff`, decide-before-you-restore).** | cap 1, cap 3 |
| H287 | **A *restore-by-version* dogfood — roll back to a *specific earlier* version across multiple supersessions, the H284 analogue on the H285/H286 reads.** H284 dogfoods *adopt a peer's better capture* (one supersession, restore-the-latest); it never exercised **multi-supersession restore-by-version** — an operator who made several adoptions then realised a *specific earlier* version was right and rolls back to it by `--hash`/`--at`, not just the latest. `test_restore_by_version_rolls_back_to_a_specific_earlier_capture` (`tests/test_dogfood.py`) holds `_held_topic()` in a `library` home, adopts three successive divergent arxiv captures over three days (v1→v2→v3) via `import items --accept-incoming` (archiving the original + two intermediates), inspects the full history via `archive show <id> --all` (H285) **and** `archive list --id` (the spaced archive timestamps), then rolls back twice via `archive restore <id>` (H286): by `--hash` to the **intermediate** v1 (NOT the latest prior v2 — the *chosen* version), and by `--at 2026-06-19T12:00` to the **original** (the earliest archived prior, the version held at the earliest point in time). **The three custody points pinned:** (a) the held `content_hash` flips to the *chosen* prior, not merely the latest (v1 via `--hash`, then the original via `--at`); (b) the displaced copy is itself archived — after each rollback `archive show` recovers exactly the version just left, so the rollback is reversible (§2.4); and (c) `doctor`'s `custody.score` holds at 100 throughout (restore-by-version swaps one full-fidelity capture for another; the displaced one is archived, never lost). **Decisive choice:** a scripted `cli.datetime` clock spaces the three adoptions across days so `--at` has a real history to bisect deterministically offline — the same offline-stand-in discipline this module already applies to its two live edges (capture, recheck), here on the archive clock; the recaptures are built from the *held DB row* (not the in-memory item) so they carry the rendered `markdown_path` and never orphan the scroll file (the `_seed_with_archived_priors` discipline). Test-only + docs, no production change. 1 new test (suite **3713 passed**). Docs: `docs/dogfood.md` new "Rolling back to a specific earlier version — restore-by-version" section with captured CLI output (history / `--hash` / `--at` decision JSON), test-count 7→8 + ADR 0106 reference extended to the restore-by-version reads. End-to-end verified on a real library (the captured output *is* the live CLI run: 3 adoptions → `archive show --all` 3 priors newest-first → `--hash peer-v1` flips to the intermediate, displaced v3 archived → `--at 06-19T12` flips to the original, displaced v1 archived → score 100 the whole way). **The next lead is H288 (`archive diff`, decide-before-you-restore).** | cap 3, cap 8 |
| H288 | **`scrolls archive diff <id> [--hash H \| --at ISO]` — the decide-before-you-restore read, comparing the held copy against a selected archived prior (ADR 0106's read-surface follow-up to restore-by-version).** An operator chose a version to restore by eyeballing `archive list`/`archive show --all` (hashes + bodies); no read *compared* what is held now against a specific prior. H288 adds a CLI **read** that folds the **same** `select_archived_snapshot` selector H286 uses (`--hash`/`--at`, default the latest) against the currently-held copy (`get_item`), reporting the custody-relevant delta: held↔prior `content_hash`, each side's `fidelity` tier (`get_fidelity`, so a degradation full→partial is visible *before* the swap), the model-complete `changed_fields` (a new pure `items.diff_snapshot(held, prior)` field-level diff over `item_to_dict` — empty on identical, the whole prior against an absent held), and `would_restore` (the H286 idempotency predicted *before* the write). **Decisive choice:** `would_restore` keys on `content_hash` alone — the *same* compare `merge_item`/restore acts on (an absent id would be re-imported, an equal-hash prior is the held copy already → `unchanged` no-op), so it converges with `archive restore --dry-run`'s `restored` by construction; `diff_snapshot` keys the field delta on *every* column, so a metadata-only difference can list `changed_fields` while `would_restore` is `false` — honest, not contradictory (a restore wouldn't pick it up). **CLI-only read, no write** (the `archive show` gate; the MCP twin stays deferred with the accept-incoming write twin per §2.4). Exits mirror `archive restore`: at most one selector (exit 2), malformed `--at` (exit 2), an unmatched selector / unknown id is a could-not-recover (exit 1). 11 new tests (`tests/test_items.py` ×3: `diff_snapshot` changed-field set, empty on identical, whole-prior vs absent held; `tests/test_cli.py` ×8: held-vs-prior delta + writes-nothing, default/`--hash`/`--at` selection, `would_restore` true/false, the fidelity-tier delta (held partial vs prior full), unmatched + unknown-id exit 1, both-selectors + malformed-`--at` exit 2). Sabotage-verified non-vacuous (forcing `would_restore=True` fails the idempotent test; `diff_snapshot→[]` fails the delta test). Docs: README CLI line, `docs/cli.md` new section, ADR 0106 deferred bullet marked shipped. Full suite **3724 passed**. End-to-end verified on a real library (the captured output: `--hash sha256:orig` correctly shows `extracted_text` *unchanged* (both hold the original body) while `content_hash`/`raw_text`/`title` differ — the field diff is precise). **The next leads are H289 (the decide-before-you-restore dogfood), H290 (the `diff`↔`restore --dry-run` convergence guard), H291 (the archive-read-family round-trip), then hardening.** | cap 1, cap 6 |
| H289 | **A *decide-before-you-restore* dogfood — read `archive diff`, then act, end to end, and the act lands exactly on the read's prediction (the H287 analogue on the H288 read).** H287 dogfoods restore-by-version (the *act*); it never exercised the **read an operator runs first** — `archive diff` (H288), the decide-before-you-restore inspection answering *what would a restore change, and would it change anything at all?* before `archive restore` (H286) writes. `test_archive_diff_decides_then_restore_acts_exactly_as_predicted` (`tests/test_dogfood.py`) holds `_held_topic()` in a `library` home, adopts **one** divergent peer capture via `import items --accept-incoming` (so a single prior is archived), then runs the whole decide → act loop offline: `archive diff <id>` (default = latest prior) → `archive restore <id>` → `archive diff <id> --hash <ORIG>` (against the just-restored prior) → `archive restore <id> --hash <ORIG>`. **The two custody points pinned:** (a) **read-then-act convergence** — the diff's `would_restore` *is* the subsequent restore's `restored`, and the diff's `prior_hash`/`held_hash`/`selector` are exactly the version a restore lands and the copy it displaces, on **both** outcomes (the would-change case: diff `true` → restore `adopted`; *and* the idempotent case: a second diff against the restored prior reports `would_restore: false` + empty `changed_fields` → a restore is an `unchanged` no-op), because the read and the write fold the *same* `select_archived_snapshot` selector + `content_hash` compare; and (b) **the diff is a true read** — the held `content_hash` is untouched across each diff (only the `restore` between them moves it), and `doctor`'s `custody.score` holds at 100 the whole way (no inspection, and no reversible rollback, lowers integrity — §2.4). The recapture is built from the *held DB row* so it carries the rendered `markdown_path` and never orphans the scroll file (the H287 discipline). Test-only + docs, no production change. 1 new test (suite **3725 passed**). Sabotage-verified non-vacuous (forcing `would_restore=True` in `_cmd_archive_diff` fails the idempotent leg's `would_restore is False`). Docs: `docs/dogfood.md` new "Deciding before you restore — `archive diff`" section with captured CLI output (decide/act/decide-again/act-again decision JSON, deterministic clock), test-count 8→9 + ADR 0106 reference extended to the decide-before-you-restore reads. End-to-end verified on a real library (the captured output *is* the live CLI run: diff `would_restore: true` + `changed_fields: [content_hash, extracted_text, raw_text]` → restore `adopted`, the held copy flips to the original → diff `--hash ORIG` `would_restore: false` + `changed_fields: []` → restore `unchanged`, score 100 throughout). **The next leads are H290 (the `diff`↔`restore --dry-run` convergence guard), H291 (the archive-read-family round-trip), then hardening.** | cap 1, cap 6 |

---

## 3-day plan — 2026-06-23 → 2026-06-26

Forward-looking (re-stamped at the H256 checkpoint, 2026-06-23, post-H297). Each day
ends on a committed, tested, clean stopping point; slips roll forward. The MVP M1–M5,
every post-MVP custody theme, and the **whole archive-recovery surface across both
transports** (read → act → recover → travel → round-trip, both recovery dogfoods,
the un-launderable integrity alarm) are closed, so the forward work is the **readable
archive-integrity surface** (H298/H299, the `_Conflicts:_`/H277 analogue the JSON-only
H293 check left open) and **per-item integration** (H300) — hardening, not a new theme.

- **Day 1 (2026-06-23):** **Done.** The **archive-recovery hardening trio (H292–H294)**
  and its **un-launderable-alarm + recovery-dogfood follow-ups (H295–H297)** all shipped
  this day. H293 (the `doctor` `custody.archive` integrity check), H292 (the cross-machine
  recovery dogfood over a `--with-archive` bundle), H294 (the whole-library JSONL-backup
  read-family round-trip); then H295/H296 (the integrity alarm is un-launderable across
  *both* the JSONL backup and the portable bundle) and **H297 (this run)** — the
  *JSONL-backup recovery dogfood*: the whole decide→restore→act workflow survives an
  `export items` + `export archive` handoff (the H292 twin on the backup transport),
  `test_recovery_workflow_survives_a_jsonl_backup_handoff` in `tests/test_dogfood.py`,
  narrated in `docs/dogfood.md` with captured CLI output, **closing the archive-recovery
  dogfood family across both transports**. Full suite **3745 passed**.
- **Day 2 (2026-06-24):** **The readable archive-integrity surface (H298, then H299).**
  **H298** — `custody.archive`'s `mismatched` count gets a readable `maintain`/`status`
  headline (`archive_integrity_headline`, the `conflicts_headline`/H277 `_Conflicts:_`
  analogue on the archive axis), since H293 is JSON-only and `maintain`'s readable summary
  is currently blind to the archive-integrity axis; the readable count ≡ `doctor`'s
  `custody.archive.mismatched` ≡ the `status` scalar (the H277/H279 honesty tie). Then
  **H299** — the same alarm's cross-run delta/trend in `maintain` (`▲N`/`▼N`, the H283
  conflicts-trend analogue), so successive maintenance passes show new corruption / a
  repaired backup, not just the current count.
- **Day 3 (2026-06-25 → 2026-06-26):** **Per-item integration + the due full re-derivation.**
  **H300** — scoped `export archive --id <ref>` round-trips the recovery read-family
  identically (the H294 twin on the per-item export path: back up *just one item's*
  recoverable history and prove it reads identically on the rebuild, while a sibling
  item's archive is correctly excluded). The **once-per-24h full 3-day/week re-derivation
  (last done post-H288) is due 2026-06-25** — perform it this day: mark done, prune stale,
  re-derive against `docs/product/mvp.md`. Close a de-prioritized guard (H244–H249) only if
  no capability slice is ready, and prefer closing one over appending more of the same
  combinatorial shape.

---

## Week plan (more tentative) — through 2026-06-30

- **Closed this past week:** the **conflict-on-import / reconciliation theme**
  (detect → read → resolve both ways: H272–H279 + the keep-held/accept-incoming
  resolutions, ADR 0104/0105/0106) and the **archive-recovery sub-theme (H280–H287)**
  — the prior-content archive now travels in the portable round-trip, reads over MCP,
  prunes under retention, differences over time, restores by version (`--hash`/`--at`)
  and the *whole* flow (adopt-a-chain → inspect-history → roll-back) is dogfooded end
  to end. Every deferred archive read/retention/portability leg of ADR 0106 has
  landed; only the operator-gated **MCP accept-incoming *write* twin** stays deferred.
- **Also closed this week — the archive-recovery hardening family, across both transports.**
  The read/act/recover surfaces (H288–H291), the cross-machine recovery dogfood over a
  `--with-archive` bundle (H292), the `doctor` `custody.archive` integrity check (H293), the
  whole-library JSONL-backup read-family round-trip (H294), the un-launderable integrity alarm
  across *both* transports (H295/H296), and the JSONL-backup recovery dogfood (H297 —
  **shipped 2026-06-23**) all landed. The recovery *workflow* now travels both the portable
  bundle and the off-machine backup, and a tampered prior cannot be laundered by either.
- **This week's horizon — the readable archive-integrity surface, then hardening.** The JSON-only
  H293 check left the *readable* axis open: **H298** (`custody.archive`'s `mismatched` gets a
  readable `maintain`/`status` headline, the `conflicts_headline`/H277 analogue), then **H299**
  (its cross-run trend, the H283 analogue) and **H300** (scoped `export archive --id` round-trip,
  the H294 twin on the per-item path). After those the forward work is pure
  **hardening/integration**, not a new theme: full-suite reliability, doctor/repair depth,
  export/import round-trip edges, and MCP/search/list/filter consistency across the archive
  surfaces. The once-per-24h full re-derivation (last done post-H288) is **due 2026-06-25**.
- The **budget/tier convergence guard cells H244–H249** remain valid regression
  guards but are explicitly **de-prioritized** — take a capability first; close a
  guard only when no capability is ready, and prefer closing one over appending more
  of the same combinatorial shape.
- A **new source adapter** is out unless it introduces a genuinely new custody
  *shape* (a new fidelity boundary, identity rule, or thread/canonical structure —
  custody-vision §2.7); adapter-churn for its own sake loses to hardening.
- Consider a bi-temporal framing pass on drift events (captured-at vs
  source-changed-at) *only if* an agent workflow shows the event record is
  insufficient; otherwise keep deferred (MVP "out of scope").
- Explicitly **not** this week: new adapters (absent a new custody shape),
  productivity surfaces, paid research integrations.

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
