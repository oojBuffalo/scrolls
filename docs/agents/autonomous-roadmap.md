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

## Status snapshot — 2026-06-25

This snapshot is **current-state only**, never a per-slice changelog — the per-slice
detail (subject, design, diff) lives in git (`git log --oneline | grep '(H<NN>)'`) and
the one-line Shipped ledger below (maintenance-rule §4: *git is the changelog*). This
section was re-compacted 2026-06-25 (the file had re-accreted to ~637 KB / 2.5× the
Read-tool ceiling; maintenance-rule §6).

**MVP M1–M5 complete** (custody-first): refresh-safe sentinel-fenced regeneration
(M1, ADR 0102), the anti-fabrication/completeness invariant (M2), progressive
`context --budget` tiers (M3), the shareable `export/import bundle` custody bundle
(M4, ADR 0103), and the offline dogfood proof *hold → prove → detect → take it with
me* (M5, `docs/dogfood.md`).

**Post-MVP themes complete** (all custody-deepening, no new adapters):

- **Per-item + per-source + per-scope custody surface** — fidelity tier, drift posture,
  `last_checked`, recheck coverage, and the custody-filter family (`--fidelity`/`--drift`
  browse/rank/act) across every read, act, and export surface (CLI + MCP + compiled
  `library/`), with cross-surface convergence guards (through ~H260).
- **Work-level custody consolidation** — each `scrolls works` entry carries an aggregate
  `custody` block + the at-risk-works alarm on `doctor`/`maintain`/MCP and the readable
  `_At-risk work:_` briefings (H261–H271).
- **Conflict-on-import** — detect → read → resolve (`reconcile --keep-held` /
  `--accept-incoming`), the durable conflict event, and the `_Conflicts:_` briefings
  (ADR 0104/0105/0106, H272–H283).
- **Archive recovery + un-launderable integrity alarm** — the prior-content archive
  travels both transports, the `_Archive:_` integrity line on every readable surface
  (bundle/context/compiled `index.md` + `maintain`/`status`), un-launderable across
  transport *and* local repair (ADR 0106, H280–H311, H319–H321).
- **Explainable ranking & relatedness** — `match_strength`/`relation_strength` bands, the
  `_Strength:_` headline, the `--strength` filter, and the `--stats` tally across
  search/context/`export bundle`/`related` (H312–H318, H322–H324).
- **Content-identity / near-duplicate custody** (a genuinely new custody shape — byte-
  identical holdings under different ids, custody-vision §2.7): the
  `doctor.custody.content_duplicates` report, the `related` "identical content" edge,
  per-item/work/browse/graph/aggregate surfaces, the `_Duplicates:_` readable line + trend,
  the `duplicate_prunes` suggested guidance, and the import-time notice — report-only, never
  an auto-merge (raw is sacred); pinned across every read/render/compile/MCP/import surface
  by convergence + dogfood guards (H325–H362).

**Closed theme — custody posture** (custody-vision §3.1, ADR 0107): `doctor`'s
`custody.posture` distils the seven custody audit blocks into one whole-library verdict
(`{verdict: sound|attention|at_risk, reasons}`) — a deterministic fold over the report
`run_doctor` already produces (drift is `attention` never `at_risk`; content duplicates
contribute nothing). Shipped, read → render → travel → trend → converge: **H369** (`doctor`
+ the `get_library_health` twin), **H370** (the readable `_Posture:_` line on `maintain` +
the `status` posture twin), **H371** (the `_Posture:_` briefing line on `export bundle` +
`scrolls context`, whole-library and always-rendered, via the shared `render_posture`),
**H372** (the cross-run posture-movement clause on the `maintain`/trend `_Posture:_` line:
`compute_delta` gains a categorical `posture` axis `{before, after, changed}`,
`compute_trend` a `posture_change` `{first, last, changed}` + a windowed `posture_headline`,
and `posture_headline(verdict, reasons, before, *, span)` renders the `sound → attention`
band transition — *reported, never a trajectory trigger*: the integrity-first trend
`posture` stays score+drift-driven, the H115/H267 discipline on the verdict axis), and
**H373** (this run — the cross-surface posture convergence guard: one test in
`tests/test_custody_convergence.py` pins `status.custody.posture` ≡ `doctor.custody.posture`
≡ `get_library_health` ≡ the `maintain`/`run_maintenance` report `custody.posture` ≡ the
bare `_Posture:_` briefing line on `export bundle`/`context`, plus the cross-run movement
axis — the report's `posture_headline` clause read off `delta.posture.before` and the trend's
`posture_change`/windowed `posture_headline` at CLI↔MCP parity — over one non-vacuous
`sound → attention` fixture, the H367 boot↔audit precedent on the posture axis). With the
theme closed, the forward work is **hardening/integration** (the forward-hardening
guard cells), not a new theme. **H363** (the in-place `kb` recompile-determinism guard —
a same-process two-pass whole-tree-hash no-op *plus* a cross-`PYTHONHASHSEED` subprocess
pair), **H364** (the MCP holdings-immutability contract guard: one `tests/test_mcp.py` test
pins the registered MCP tool surface — `mcp_server._TOOLS`, asserted ≡ what `build_server`
registers — is *exactly* an allow-list of 17 read + 7 custody-safe-write tools **and** that no
non-feed registered tool name carries a capture-destroying verb so an agent driving MCP can
never delete or overwrite raw), and **H365** (this run) have shipped. **H365** is the
`doctor --fix` repair-convergence guard: one `tests/test_doctor.py` test seeds real repairable
findings (a deleted scroll → `missing_scrolls`, an FTS desync), runs `doctor --fix` (asserts it
fixes both), then runs `--fix` *again* with no intervening mutation and pins that the second pass
is a **total no-op on both axes** — the report level (`issues == 0` / `fixed == 0`, every finding
list empty) **and** the disk level (a `{relpath → sha256}` whole-tree hash of `scrolls/` is
byte-identical, so not one scroll is silently re-rendered — the H363 whole-tree-hash precedent on
the *repair* axis). A held byte-identical content-duplicate pair rides along and stays a non-finding
on both passes (`doctor --fix` never merges a content duplicate, H337). Two sabotages prove the
teeth: a silent re-render fails *only* the hash-map assertion (report no-op stays green — the
decisive both-axes choice), and dropping the `exists()` short-circuit so `--fix` re-flags a repaired
scroll fails the report no-op. So every dogfood/round-trip restore step (H336/H360) that re-audits
after `doctor --fix` now has its settle contract regression-proof. **H366** (this run) is the
`context --budget` tier-nesting contract guard: two `tests/test_context.py` tests (the CLI bundle
+ the MCP `get_context_bundle` twin) over one seeded library (three "database" keyword matches + one
linked-but-unmatched paper, so every tier-gated section is non-vacuous) pin the M3 strictly-nested
contract as a whole — the **Best-Match id set is identical** across `index`/`connected`/`full` (the
load-bearing depth-vs-set orthogonality: a leaner budget cuts per-match depth, never the match set),
the **Connected** block is absent at `index`, present at `connected`/`full`, and **byte-identical**
between the two, **Excerpts** appear only at `full`, and the `_Budget:_` honest-depth note renders on
`index`/`connected`, omitted at `full`. The sabotage proves the teeth: a "save tokens" truncation that
drops a Best Match at a leaner budget (guarded to multi-match scopes) fails the set-equality assertion
on both surfaces while all 12 existing per-block presence budget tests stay green — the regression the
new guard catches that the scattered per-tier tests miss. Test-only, no production change. **H367** (this
run) is the `scrolls status` ↔ `doctor` custody-scalar convergence guard (the fifth forward-hardening
cell): one `tests/test_custody_convergence.py` test over a **non-vacuous** fixture (a held byte-identical
content pair, a stale-classified member, a drifted item carrying an unresolved import conflict, an
all-reference at-risk work — so `score`/`tiers`/`drift`/`coverage`/`enrichment_stale`/`at_risk`/
`conflicts`/`content_duplicate_{groups,items}` are all non-zero) pins the *whole* lean-`status` flat
custody block scalar-to-nested against the full `doctor --json` `custody` audit, field-for-field:
`status.custody.<scalar>` ≡ its `doctor.custody.<path>` counterpart (incl. `score`, `tiers`, the six
`drift` axes, `coverage`, `enrichment_stale`/`summaries_stale`, `at_risk`→`works.at_risk`,
`conflicts`→`conflicts.items`, `archive_mismatched`→`archive.mismatched`, the two
`content_duplicate_*`→`content_duplicates.total_{groups,items}`, and the whole `posture` dict) — the M2
"identical semantics across surfaces" contract (custody-vision §2.6) on the boot-vs-audit axis, beside
H363's compile determinism, H364's MCP-registry immutability, H365's repair convergence, and H366's
read-budget nesting. The sabotage proves the teeth: re-wiring one `status` scalar in `_cmd_status` (e.g.
`content_duplicate_groups = content_duplicate_items`) fails *only* the convergence guard while all 434
`maintain`+`doctor` unit tests stay green — the boot↔audit desync no surface's own tests cover (the
`custody_snapshot` unit tests pin the projection in isolation, never the CLI surface wiring). Test-only,
no production change. **H368 (this run)** is the whole-library `export bundle` determinism + round-trip
byte-identity guard (the sixth forward-hardening cell): two `tests/test_bundle.py` tests over a
multi-source + drift-event fixture (`_seed_multi_source`, so the per-source breakdown, the items block,
and the custody-events block are all non-vacuous) pin the shareable bundle is a *reproducible artifact* —
exporting the same unchanged library twice yields a **byte-identical** bundle (whole-text, not one
section — the H363 whole-tree-hash precedent on the bundle axis), AND a real `export bundle` → `import
bundle` into a fresh `SCROLLS_HOME` → re-`export bundle` (both sides materialised via the documented
`doctor --fix`/`kb` restore) reproduces the sender's bytes, so a recipient who re-exports to forward the
bundle emits the same artifact. The sabotage proves the teeth: a `random.random()` injected into the
bundle header fails *both* assertions (same-library determinism and round-trip reproduction) while every
per-section bundle test stays green — the whole-artifact reproducibility regression the scattered
per-block tests miss. Test-only, no production change (the bundle is already deterministic — ordered
folds, no wall-clock; `bundle.py` carries no `now()`/`generated_at`). **H374 (this run)** is the
`import bundle` re-import idempotency guard (the seventh forward-hardening cell): one
`tests/test_bundle.py` test over the `_seed_multi_source` fixture materialised in a fresh
`SCROLLS_HOME` (`doctor --fix`/`kb`) pins that re-importing the *same* bundle into a library that
already holds it is a true no-op on **all three** axes — the item rows (count + per-id `item_to_dict`
identity, no re-insert), the `scrolls/` disk bytes (a `{relpath → sha256}` whole-tree map
byte-identical, nothing re-rendered — the H363/H365 whole-tree-hash precedent on the import axis), and
the conflict ledger (zero `conflict` events: byte-identical content is not a divergence, ADR-0104) —
with the re-import report confirming `imported == 0`/`skipped == 3`/`conflicts == []`/
`content_duplicates == 0`. Two sabotages prove the teeth: flagging every re-import a conflict fails
the conflict-ledger axis, and re-inserting the held row fails the `imported == 0` axis, while every
single-import round-trip test stays green. Test-only, no production change (re-import already settles —
id-keyed `INSERT OR IGNORE` + content-equal conflict suppression). **H375 (this run)** is the `scrolls
doctor` whole-report determinism guard (the eighth forward-hardening cell — the audit trust-root axis):
two `tests/test_doctor.py` tests over a new non-vacuous fixture (`_seed_doctor_determinism_mix`: three
sources so `custody.by_source` is a multi-key map, a byte-identical content pair, a drifted full item
*also* carrying an unresolved import conflict so `drift.events` + `conflicts.events` are both non-empty,
a tampered archived prior so `archive.events` carries one mismatched recovery row, and an all-reference
work so `works.most_at_risk` is populated — structurally clean, `issues == 0`, so `scrolls doctor` exits
0) pin that the audit `status`/`maintain`/MCP `get_library_health` all fold (H367 pinned status ≡ doctor)
is a *reproducible artifact*: two same-process `run_doctor` reads serialize to byte-identical JSON (no
wall-clock/counter leak), AND `scrolls doctor` emits byte-identical stdout across two subprocesses under
different `PYTHONHASHSEED`s (the H363 `kb` cross-seed copytree precedent on the audit axis). The decisive
choice is the cross-seed pair: a `set` leaking into any sub-block fold iterates the *same* way twice
under one fixed seed, so the same-process read stays green over it — only two differently-seeded processes
surface the divergence (verified: a by-source set-fold sabotage fails the cross-seed guard while the
same-process read passes; a 6-seed sweep confirms one report hash). Test-only, no production change (the
audit is already deterministic — ordered folds, no wall-clock). **H376 (this run)** is the `scrolls
context` bundle determinism guard (the ninth forward-hardening cell — the *agent-read-surface* axis): two
`tests/test_context.py` tests over a new wide fixture (`_seed_context_determinism_mix`: eight "database"
keyword matches, each linking to one unique unmatched paper, so the Best-Match list, the Connected
link-graph, and the deep-body Excerpts are each an eight-element fold whose order a `set` leak would
scramble — the H366 single-neighbour nested-library widened so the connected-fold sabotage is non-vacuous)
pin that the model-facing context bundle — an agent's *primary read* — is a *reproducible artifact*: two
same-process `scrolls context db --budget full` reads are byte-identical (no wall-clock leak), AND the
command emits byte-identical stdout across two subprocesses under different `PYTHONHASHSEED`s (the H363
`kb` / H375 `doctor` cross-seed copytree precedent on the agent-read axis — `context.py` builds the
Connected/Excerpts sections from search + relatedness folds the `export bundle` of H368 never runs, a
genuinely distinct code path). The decisive choices: test at `--budget full` (every order-sensitive
section exercised) and include the cross-seed pair, the order-leak catcher a same-process pass misses. The
sabotage proves the teeth: folding the connected-neighbours section over a `set` (`list(set(connections))`
in `_connected_lines`) fails *only* the cross-seed byte-identity while the same-process read **and** H366's
two nesting tests stay green — the reproducibility regression those per-tier presence tests structurally
cannot see (verified the eight-element fold reliably diverges across seeds 0/1; four did not). Test-only,
no production change (the bundle is already deterministic — ordered search + relatedness folds, no
wall-clock). **H377 (this run)** is the `scrolls maintain` trend-log determinism + no-movement settle
guard (the tenth forward-hardening cell — the cross-run *maintenance-ledger* axis): three
`tests/test_maintain.py` tests over the H367 non-vacuous mix (`_seed_maintain_determinism_mix`: a
byte-identical content pair, a stale-classified member, a drifted item *also* carrying an unresolved
import conflict, an all-reference at-risk work, a partial item — so every snapshot scalar plus an
`at_risk` multi-reason posture is non-zero, structurally clean so the subprocesses exit 0) pin that the
snapshot/trend an unattended worker reads to judge *"is custody degrading?"* is both a **settled** and a
**reproducible** read. The settle test runs two `maintain --no-recheck` passes over one unchanged library
and asserts the recorded snapshots' comparable scalars are byte-equal AND that *both* `compute_delta(S1,
S2)` and the second pass's *production* delta are the all-zero / no-movement shape on every axis (scalar +
per-key mapping + the categorical posture band) — so a clean library never reports phantom drift
(`--no-recheck` keeps the pass from re-verifying the fixture's drifted item, the only ledger mutation a
default pass would make). The two determinism tests add the cross-`PYTHONHASHSEED` subprocess face a
same-process pass structurally cannot see (a `set` iterates the same way twice under one fixed seed): the
whole `maintain --no-recheck` report is byte-identical (minus the wall-clock `recorded_at`) across seeds
0/1, and `maintain --history --trend` over a *fixed* two-entry log (a clean `sound` baseline → a degraded
`at_risk` window with multi-reason posture) is byte-identical across seeds **and** read-stable
same-process. Three sabotages prove the teeth: a phantom `+1` in a `compute_delta` axis fails the settle;
the posture `reasons` folded over a `set` in `custody_snapshot` fails the report cross-seed; and the same
fold in `posture_headline`'s reasons join fails the trend cross-seed — while all 300 existing `maintain`
tests stay green. Test-only, no production change (the snapshot is a pure fold of the deterministic
`run_doctor` report — ordered folds, no wall-clock). **H378 (this run)** is the `export bundle
--format html` whole-text determinism guard (the eleventh forward-hardening cell — the *HTML-render*
axis): one `tests/test_bundle.py` test over the H368 multi-source + drift-event fixture
(`_seed_multi_source`, materialised via `doctor --fix`/`kb`) pins that the browser-readable briefing
(H39) is a *reproducible artifact* — exporting the same unchanged library to HTML twice yields a
**byte-identical** document (whole-text, the H368 whole-artifact precedent on the HTML axis, a
genuinely distinct code path: `build_bundle_html` emits `html.escape`d `<h1>`/`<h2>`/`<li>` markup and
the `_html_document` wrapper the Markdown form never runs). Unlike H368 there is no round-trip leg —
HTML is export-only (no `import bundle --format html`; the import path consumes the Markdown
`@generated` fence) — so the cell pins same-library two-export determinism only. The sabotage proves
the teeth: a `random.random()` injected into the `<h1>` heading fails the byte-identity while the
per-section HTML substring tests stay green — the whole-document reproducibility regression those
substring tests structurally cannot see. Test-only, no production change (the HTML bundle is already
deterministic — ordered folds, no wall-clock; `_html_document`'s `<head>` embeds no timestamp). **H379
(this run)** is the `export items` JSONL whole-file determinism + round-trip byte-identity guard (the
twelfth forward-hardening cell — the *whole-library-backup transport* axis, the unscoped sibling of
H368's scoped-bundle determinism): one `tests/test_roundtrip.py` test over the multi-source `_seed_items`
fixture pins that the JSONL backup transport (`scrolls export items`, the same `dump_items_export` fold
the bundle item block wraps but over the *entire* holdings, no query scope) is a *reproducible artifact*
on two axes — exporting the same unchanged library twice yields **byte-identical** JSONL (the
genuinely-new axis: the existing `test_export_rebuild_is_byte_identical` pins only the round-trip
re-export leg amid a five-surface rebuild check, never the same-library two-export determinism), AND a
real `export items` → `import items` into a fresh `SCROLLS_HOME` → re-`export items` reproduces the
sender's bytes (the leaner round-trip needs no `doctor --fix`/`kb` — `export items` reads the index rows
`import items` populates). The decisive choice is comparing the *whole JSONL file* (not one row) on both
axes; the cell is *not* cross-seed (no set to scramble — `dump_items_export` is a pure ordered fold:
`list_items` orders `ORDER BY saved_at, id`, `item_to_dict` is `asdict` in dataclass field order, the H384
"same-process two-export check suffices" guidance). The sabotage proves the teeth: a per-call counter
appended to one exported row (`_seq`) fails the same-library determinism axis (`_seq: 1` vs `_seq: 2`)
while every per-row round-trip tree test stays green — the whole-file reproducibility regression the
rebuilt-tree comparison structurally cannot see. Test-only, no production change (`export items` is
already deterministic). **H380 shipped this run** (the `import events` re-import idempotency guard — the
events-transport sibling of H374, a whole-ledger no-op on both the raw `custody_events` row count and the
per-item `item_history` identity; two sabotages bite — a dropped `_EVENT_IDENTITY` dedup fails the
second-pass report, and a dedup that reports `skipped` yet re-inserts passes the report axis but fails the
row-count axis). **H381 shipped this run** (the MCP `get_library_health` whole-payload determinism
guard, the fourteenth pivot cell — the *MCP-surface* sibling of H375's CLI `scrolls doctor`
determinism: `get_library_health` spreads `run_doctor`'s custody block and adds `attention`/`headline`
through the MCP tool envelope, a distinct serialization an agent caches; two same-process reads
byte-identical + a cross-`PYTHONHASHSEED` subprocess pair byte-identical, riding the H186/H180
registered-twin shape contract; a by-source `set`-fold sabotage in the MCP path fails *only* the
cross-seed guard). **H382 shipped this run** (the MCP `get_context_bundle` whole-payload determinism
guard, the fifteenth pivot cell — the *MCP-surface* sibling of H376's CLI `scrolls context`
determinism: `get_context_bundle` folds the *same* deterministic `build_context` the CLI prints through
a separate MCP entry point; two same-process reads byte-identical to the CLI `build_context` + a
cross-`PYTHONHASHSEED` subprocess pair, riding the H186/H180 registered-twin shape contract; a `set`-fold
of the shared connected-neighbours section fails *only* the cross-seed guard while the same-process read
and the H366 nesting twin stay green). **H383 shipped this run** (the MCP `run_maintenance` whole-payload
determinism + no-movement settle guard, the sixteenth pivot cell — the *MCP-surface* twin of H377's CLI
`scrolls maintain` settle/determinism: an MCP-driven dogfood loop never calls the CLI, it calls
`run_maintenance` which passes a `skipped_recheck_report` and returns the same `assemble_report` through
the MCP tool envelope; two in-process `run_maintenance()` calls record byte-equal comparable scalars and a
no-movement second delta on every axis, and the whole payload is byte-identical across a
`PYTHONHASHSEED` subprocess pair, riding the H186/H180 registered-twin shape contract; two sabotages bite —
a phantom `+1` in `_scalar_delta` fails *only* the settle, and the posture `reasons` folded over a `set` in
`custody_snapshot` fails *only* the cross-seed while the per-tool shape tests stay green). **H384 and H385
have shipped** (the `export events` JSONL determinism + round-trip guard, then the `archive show` JSONL
determinism + restore round-trip guard), and **H386 shipped this run** (the `import archive` whole-store
re-import idempotency guard — the multi-prior, three-axis [report/store/recovery] sharpening of the
pre-existing single-prior `test_import_archive_is_idempotent`, completing the items/events/archive
ingest-idempotency triptych after H374/H380). **H387 shipped this run** (the MCP `get_link_graph`
whole-payload determinism guard — the *fourth* MCP-surface determinism twin after H381/H382/H383, on the
agent-facing whole-link-structure read: two same-process `get_link_graph()` reads byte-identical + a
cross-`PYTHONHASHSEED` subprocess pair over a wide multi-source fixture [five connected nodes, four edges, a
four-key `by_source` map, a byte-identical web pair so the per-node `content_duplicate_ids` fold is
non-vacuous]; a `set`-fold of the node list fails *only* the cross-seed while the same-process read + the
per-tool shape tests stay green; suite **4218 passed**). **H388 shipped this run** — and it *retires the
per-tool MCP determinism-twin treadmill*: instead of hand-writing one cross-seed cell per read tool
forever (H381/H382/H383/H387 shipped that way; H389/H391/H392/H393 were queued to continue it), H388 is
the **whole MCP read-surface determinism contract** — one guard over *every* registered read tool
(`_MCP_READ_TOOLS`) at once. Three `tests/test_mcp.py` tests over one wide fixture
(`_seed_read_surface_determinism_mix` + `_prepare_read_surface_library`: four sources, three DOI-clustered
works incl. an all-reference at-risk work, a ≥3-node/≥2-edge link graph, a rendered "Database" concept +
"efficient" tag each with ≥3 members, a byte-identical content pair, a drifted item carrying an unresolved
conflict, a tampered archived prior, and a two-pass maintenance trend — so every order-sensitive fold of
all 17 read tools is non-vacuous): (1) a **completeness keystone** — the determinism call list covers
*exactly* `_MCP_READ_TOOLS`, so a *new* read tool fails the contract until given a call, forcing
reproducibility coverage by construction (the M2/H364 registry-completeness contract lifted to the
determinism axis — the mechanism that ends the treadmill); (2) a same-process whole-surface byte-identity
read; and (3) a single cross-`PYTHONHASHSEED` subprocess pair that calls *every* read tool from the one
source-of-truth call list and compares the whole concatenated output — so a `set` leaking into *any*
current-or-future read fold is caught, not just the one tool a per-tool twin happened to guard. The
sabotage proves the teeth on the load-bearing axis: a `list(set(...))` leak injected into `get_works`
stays invisible to two reads under the *same* seed yet diverges across seeds 0/1 (suite **4222 passed**).
With the per-tool MCP determinism twins subsumed (H389/H391/H392/H393 pruned), the forward buffer pivots
off the treadmill to a **contract-consolidation** theme grounded in the PRD success metrics
(round-trip, regeneration-safety, surface-parity, completeness-honesty). **H390 shipped this run** — the
CLI `export archive` whole-library JSONL determinism + round-trip byte-identity guard, the *third leg of
the transport-determinism triptych* after H379 (`export items`, the held set) and H384 (`export events`,
the verify ledger), on the **archive** transport: one `tests/test_roundtrip.py` test
(`test_export_archive_is_a_reproducible_artifact`) over `_build_library(_seed_items())` + a
`_seed_archive` fixture that supersedes two held items via the production `adopt_incoming` path (item 0
*twice* — a two-link chain of distinct `prior_hash`/`archived_at`, item 2 once → three `item_archive` rows
across two items, so both fold orders [within-id chain + across-id] are non-vacuous) pins that
`dump_archive_export` — the recovery-backup root both `export archive` and the bundle's `--with-archive`
block emit (H280), a *distinct code path* from H379/H384's siblings and from H385's per-item `archive show`
read — is a *reproducible artifact*: two same-library `export archive` are **byte-identical** whole-file,
AND a real `export archive` → full restore (`import items` + `import archive`) into a fresh `SCROLLS_HOME`
→ re-`export archive` reproduces the sender's bytes (`archived_records(dst) == archived_records(src)`).
Not cross-seed — `archived_records` is an explicit `(archived_at, item_id, prior_hash)` ordered fold, no
set to scramble, so the same-process two-export check suffices (the H384/H385 guidance). The sabotage
proves the teeth: a process-global per-row counter (`_seq`) appended to each exported archive row fails
*only* the same-library byte-identity (`_seq: 1..3` first export vs `_seq: 4..6` second) while every
archive restore-outcome test (H280/H285) stays green — the whole-file reproducibility regression those
recovered-prior tests structurally cannot see (suite **4223 passed**). Test-only, no production change
(`export archive` is already deterministic — ordered `item_archive` fold, no wall-clock). The forward
buffer's active **contract-consolidation** theme has since shipped **H394** (CLI read-surface determinism)
and **H395** (the round-trip transport contract); the live queue (below) is the authoritative lead.

---

## Live work queue (un-started)

Ordered. Take the next slice whose preconditions are met (all listed preconditions are
shipped), finish it to a committed/tested/clean stopping point, and stop. `→ capN` marks
the PRD capability. Slices are justified against `docs/custody-vision.md` and the MVP; new
adapters are out unless they introduce a new custody shape (custody-vision §2.7). Anything
not on the queue still loses to "finish the half-done slice from the previous run first."

**The custody-posture theme is closed** (H369–H373; the cross-surface convergence guard
H373 closed it). The forward work is hardening/integration — the guard cells below.
**H363** (the first pivot cell, `kb` recompile-determinism), **H364** (the MCP
holdings-immutability contract guard, the second pivot cell), **H365** (the `doctor --fix`
repair-convergence guard, the third pivot cell), **H366** (the `context --budget`
tier-nesting contract guard, the fourth pivot cell), **H367** (the `scrolls status` ↔ `doctor`
custody-scalar convergence guard, the fifth pivot cell), **H368** (the whole-library
`export bundle` determinism + round-trip byte-identity guard, the sixth pivot cell),
**H374** (the `import bundle` re-import idempotency guard, the seventh pivot cell — the
ingest-transport settle axis), **H375** (the `scrolls doctor` whole-report determinism guard,
the eighth pivot cell — the audit trust-root axis), **H376** (the `scrolls context` bundle
determinism guard, the ninth pivot cell — the agent-read-surface axis), and **H377 shipped this
run** (the `scrolls maintain` trend-log determinism + no-movement settle guard, the tenth pivot
cell — the cross-run maintenance-ledger axis), **H378 shipped** (the `export bundle
--format html` whole-text determinism guard, the eleventh pivot cell — the HTML-render axis), and
**H379 shipped** (the `export items` JSONL whole-file determinism + round-trip byte-identity
guard, the twelfth pivot cell — the whole-library-backup-transport axis), and **H380 shipped this run**
(the `import events` re-import idempotency guard, the thirteenth pivot cell — the ledger-ingest settle
axis: a whole-ledger no-op on both the raw `custody_events` row count and the per-item `item_history`
identity), and **H381 shipped this run** (the MCP `get_library_health` whole-payload determinism
guard, the fourteenth pivot cell — the *MCP-surface* sibling of H375's CLI `scrolls doctor`
determinism: `get_library_health` spreads `run_doctor`'s custody block and adds `attention`/`headline`
through the MCP tool envelope, a distinct serialization; two same-process reads + a cross-seed
subprocess pair byte-identical, riding the H186/H180 registered-twin shape contract), and **H382
shipped this run** (the MCP `get_context_bundle` whole-payload determinism guard, the fifteenth pivot
cell — the *MCP-surface* sibling of H376's CLI `scrolls context` determinism: `get_context_bundle`
folds the *same* deterministic `build_context` the CLI prints through a separate MCP entry point; two
same-process reads byte-identical to the CLI `build_context` + a cross-seed subprocess pair, riding the
H186/H180 shape contract), and **H383 shipped this run** (the MCP `run_maintenance` whole-payload
determinism + no-movement settle guard, the sixteenth pivot cell — the *MCP-surface* twin of H377's CLI
`scrolls maintain` settle/determinism: two in-process `run_maintenance()` calls record byte-equal
comparable scalars + a no-movement second delta on every axis, and the whole payload is byte-identical
across a `PYTHONHASHSEED` subprocess pair; a phantom `+1` in `_scalar_delta` fails *only* the settle and a
posture-`reasons` `set`-fold in `custody_snapshot` fails *only* the cross-seed, the per-tool shape tests
staying green), and **H384 shipped this run** (the `export events` JSONL whole-file determinism +
round-trip byte-identity guard, the seventeenth pivot cell — the *events-transport* reproducibility axis:
two same-library `export events` byte-identical whole-file + a full-restore round-trip
[`import items` + `import events`, since `export events` is item-scoped] re-export reproducing the sender's
bytes, the `dump_events_export` sibling of H379's `dump_items_export` and the *export* complement of H380's
`import events` idempotency; a per-call counter on each exported event row fails *only* the byte-identity),
and **H385 shipped this run** (the `scrolls archive show` JSONL determinism + restore round-trip guard, the
eighteenth pivot cell — the *archive-recovery-transport* sibling of H379's `export items` determinism: the
same `dump_items_export` fold over `item_archive` rows [`archived_snapshots`, `ORDER BY id DESC`], a distinct
code path from `list_items`; two same-library `archive show <id>` byte-identical whole-file [single-prior
default *and* the `--all` multi-prior fold] + a real `archive show <id>` → `import items --accept-incoming`
re-adopting the archived prior; not cross-seed — `archived_snapshots` is an `ORDER BY id DESC` fold with no
set to scramble, so the same-process two-read check suffices; a per-call counter on one shown prior row fails
*only* the byte-identity). **H386 shipped this run** (the `import archive` whole-store re-import idempotency
guard — `export archive` → `import archive` *twice* into a fresh home is a true no-op on the report
[`imported == 0`/`skipped == 3`], store [`item_archive` row count stable], and recovery [`archived_snapshots`
list identity] axes over a three-prior history; two sabotages prove the teeth — a re-insert-despite-skip fails
*only* the store axis [6 ≠ 3], and an `item_id`-only dedup collapses the first import to 1 of 3 priors where
the single-prior `test_import_archive_is_idempotent` stays green; suite **4216 passed**). **H387 shipped this
run** (the MCP `get_link_graph` whole-payload determinism guard — the fourth MCP-surface determinism twin
[after H381/H382/H383] on the agent-facing whole-link-structure read; two same-process reads byte-identical +
a cross-`PYTHONHASHSEED` subprocess pair over a wide multi-source fixture, a `set`-fold of the node list
failing *only* the cross-seed; suite **4218 passed**); **H388 shipped this run** as the **whole MCP
read-surface determinism contract** — one completeness-asserted guard over *every* registered read tool,
*retiring the per-tool MCP determinism-twin treadmill* (the queued H389/H391/H392/H393 are subsumed and
pruned; see the Status snapshot). The forward buffer pivoted to a **contract-consolidation** theme, and
**H390 shipped this run** (the CLI `export archive` whole-library JSONL determinism + round-trip
byte-identity guard — the third leg of the transport-determinism triptych after H379/H384, on the
**archive** transport; a process-global per-row `_seq` counter fails *only* the same-library byte-identity;
suite **4223 passed**; see the Status snapshot). **H394 shipped this run** — the CLI read-surface
determinism contract, the CLI sibling of H388's MCP contract: one completeness-asserted guard over
*every* CLI JSON read command at once (the 14 reads `search`/`list`/`facets`/`works`/`graph`/`related`/
`doctor`/`context`/`status`/`history`/`maintain --history --trend`/`archive list`/`archive show`/`show`),
byte-identical across two same-process reads AND across a `PYTHONHASHSEED` subprocess pair. The
completeness keystone is a `_CLI_READ_COMMANDS` classification (the argparse-subcommand analogue of
`_MCP_READ_TOOLS`/H364) plus a `_CLI_WRITE_COMMANDS`/`_CLI_EXEMPT_READS` split asserted to cover the
live argparse registry exactly (all 51 leaf subcommands), so a *new* read subcommand fails until given a
determinism call. The shared `_seed_read_surface_determinism_mix` was extracted to
`tests/read_surface_fixture.py` and re-imported by both H388 (`test_mcp.py`) and H394
(`test_cli_determinism.py`); a `set`-fold leaked into one CLI read (`works`) fails *only* the cross-seed
while two same-seed reads stay green (the load-bearing half), and `history` is folded in for parity with
the MCP `get_scroll_history` twin the roadmap list omitted. Test-only, no production change (the CLI reads
are already deterministic — ordered folds, no wall-clock in any read path; suite **4227 passed**). **H395
shipped this run** — the round-trip transport contract, the second **contract-consolidation** cell: one
completeness-asserted invariant over *every* lossless export/import transport (`items`/`events`/`archive`/
`bundle`), retiring the per-transport reproducibility treadmill (H368/H379/H384/H390). Two faces in
`tests/test_roundtrip.py`: (1) the **completeness keystone** — `_ROUND_TRIP_TRANSPORTS` (the four lossless
transports) plus a named `_INTERCHANGE_EXEMPT` set (`opml`/`bookmarks`, foreign-format interchange with no
custody model to reproduce) must partition *exactly* the bidirectional `export <kind>` ∩ `import <kind>`
pairs walked from the live argparse registry, so a *new* `export X`/`import X` pair fails the contract until
classified (the `_CLI_READ_COMMANDS`/H394 mechanism on the transport axis); and (2) a parametrised
round-trip + determinism guard per transport — two same-library exports byte-identical AND a real
export→import→export into a fresh `SCROLLS_HOME` (materialised via `doctor --fix`/`kb` only where the
re-export reads the tree, i.e. `bundle`) reproduces the sender's bytes. The teeth test monkeypatches
`dump_items_export` to append a process-global `_seq` counter and pins that the *items* determinism leg
fails while `export archive`'s own fold stays byte-identical and non-vacuous — the per-row-counter sabotage
isolated to one transport. Test-only, no production change (every transport is already deterministic and
lossless; the existing per-transport cells stay as deeper regression guards). Suite **4233 passed**.
**H396 shipped this run** — the regeneration-safety contract (ADR 0102), the third
**contract-consolidation** cell: one completeness-asserted invariant in `tests/test_regeneration_safety.py`
that a `@user` annotation survives a re-compile across *every* generated-artifact family — the compiled
`library/` pages (`sources/*`, `categories/*`, `concepts/*`, `tags/*`, `index.md`, `graph.md`, `works.md`)
and the three generated `agents/` instruction files. Two faces: (1) a **completeness keystone** —
`_GENERATED_ARTIFACT_KINDS` must equal the live source-of-truth registries the compiler/installer drive
(`kb._GENERATED_DIRS` + `kb._GENERATED_FILES`, the exact set `compile_kb` writes and `_reconcile_generated`
cleans, plus `agents._TARGETS`), so a *new* generated artifact fails the contract until given a
regeneration-safety entry (the H364 registry-completeness mechanism on the regeneration axis) — backed by a
defense-in-depth leg that walks the pages a real compile *emits* and pins each to a registered kind (a rogue
writer emitting an unregistered `library/` page is caught even without touching the constants); and (2) a
parametrised per-kind probe over a non-vacuous two-DOI-clustered, mutually-linked fixture (so every family —
sources, the shared category/concept/tag, a real graph edge, a real 2-representation work — is present): the
probe injects a STALE sentinel *inside* the fence and a `@user` note *outside* it (a suffix, the one position
preserved across every kind including the header-pinned SKILL.md), regenerates, and asserts the STALE text is
purged (the refresh is authoritative — ADR 0102's "stale content can never linger") **and** the `@user` note
survives byte-for-byte (raw annotation is sacred). The sabotage proves the teeth on both axes: a
whole-file-overwrite `write_generated` (ignoring the fence) fails all 10 per-kind legs (annotation clobbered)
while the keystone stays green, and a new uncovered `_GENERATED_FILES` entry fails *only* the keystone — the
two failure modes the contract guards (no-op writer leaves STALE, overwrite writer clobbers the note).
Test-only, no production change (M1/H1–H3's `write_generated`/`splice` already implement refresh-safe
regeneration). Suite **4245 passed**. **H397 shipped this run** — the surface-parity contract, the fourth
**contract-consolidation** cell: one completeness-asserted (surface × axis) matrix in
`tests/test_surface_parity.py` that, for *every* held item, its custody axes (fidelity tier, drift posture,
works membership, content-duplicate partition) read identically across the browse-and-enumerate family
`search` ≡ `list` ≡ MCP `search_scrolls`/`list_scrolls` ≡ `facets`. Per-item surfaces are compared
item-for-item against one canonical projection read off the primitives (`get_fidelity`/`drift_posture`/
`work_membership`/`content_duplicate_ids`); the aggregate `facets` count-for-count against the canonical
tally; values compared *on the wire* (`json.dumps`) so a `tuple`/`list` JSON-array difference between the
CLI (`json.dumps` → list) and MCP (native tuple) surfaces is not a false desync (the H400 normalisation,
which the matrix surfaced immediately). Three completeness keystones force a *new* surface/axis into the
matrix: (1) `_PARITY_SURFACES × _CUSTODY_AXES` is covered cell-for-cell by a live assertion or a *named*
exemption (the per-item rows carry no content-duplicate field — that read rides `show`/`get_scroll`, H328;
`facets` has no works dimension); (2) the carried axes equal exactly the custody-bearing fields of the live
`item_summary`+`hit_payload` shapes minus a named non-custody set (a new custody row field fails until
classified); and (3) the parity surfaces partition the live read registries (`_CLI_READ_PATHS`/H394,
`_MCP_READ_TOOLS`/H388, imported from their contracts) so a new browse command/tool fails until declared
parity-or-exempt. The sabotage proves both teeth *and* isolation: monkeypatching `cli.item_summary` (the CLI
`list` row builder, a distinct binding from `mcp_server.item_summary` and `hit_payload`) to claim one
drifted source is clean fails *only* `(list, drift)` — not its `list_scrolls`/search/facets siblings.
Test-only, no production change (the surfaces already share `item_summary`/`hit_payload`/`membership_payload`,
one home). Suite **4250 passed**. **H398 shipped this run** — the completeness-honesty contract (M2),
the fifth **contract-consolidation** cell: one registry-driven invariant in `tests/test_completeness_contract.py`
that *every* browse/audit surface (`search`/`list`/`related`/`works`/`context`/`doctor` + the MCP twins) is
scope-honest and completeness-honest on two axes — (1) a *scoped* read discloses a scope its other-scope read
does not (a filtered slice never reads as the whole library), and (2) an empty in-scope read is the empty form,
distinguishable from a could-not-check. The **completeness keystone** (`_COMPLETENESS_SURFACES` ∪ named
exemptions partition `_CLI_READ_PATHS`/H394 ∪ `_MCP_READ_TOOLS`/H388) fails when a *new* browse/audit surface
ships without a scope-honesty assertion; the sabotage drops `cli.works_payload`'s scope echo (a per-ref read
claims whole-library completeness) and fails *only* `works`. Test-only, no production change (G2 shipped H6–H8,
G1 in `test_completeness.py`); suite **4256 passed**. **H399 shipped this run** — the re-import idempotency
contract (the PRD round-trip success-metric on the *ingest settle* axis), the sixth **contract-consolidation**
cell: one completeness-asserted invariant in `tests/test_roundtrip.py` that re-importing *any* lossless custody
export into a library that already holds it is a whole-store no-op, across *every* `import <kind>` transport
(`items`/`events`/`archive`/`bundle`). The **completeness keystone**
(`test_import_idempotency_registry_covers_every_import_subcommand`) holds `_IMPORT_TRANSPORTS` ∪ a named
`_IMPORT_INTERCHANGE_EXEMPT` set (the five foreign-format ingests `bookmarks`/`opml`/`pocket`/`google-takeout`/
`fieldtheory`, each with no lossless `export <kind>` that produces its input) to partition *exactly* the live
`import` subparser registry, so a *new* `import X` fails until classified (the H394/H395 keystone mechanism on the
ingest axis). The parametrised guard (`test_reimport_transport_is_a_whole_store_no_op`) imports each transport's
export into a fresh `SCROLLS_HOME` *twice* and pins the second pass is a no-op on **both** axes — the report
(`imported == 0`/all-`skipped`) **and** the raw-store row count read straight from the transport's dedup table
(`merge_item`'s `INSERT OR IGNORE` → `items`; `import_events`' `_EVENT_IDENTITY` → `custody_events`;
`import_archive`'s `_ARCHIVE_IDENTITY` → `item_archive`; the bundle's items axis), never the per-library
autoincrement id the export never carries. The both-axes choice is decisive (the H380/H386 precedent): the
sabotage `test_reimport_idempotency_contract_has_teeth` monkeypatches `cli.import_archive` to duplicate
`item_archive` behind a *clean* report (`imported == 0`/`skipped == 3`, store 3 → 6) and pins the raw-count axis
catches it while the `items` transport — folding through `merge_item`, not the patched function — stays a true
no-op, proving a report-only check is blind and the leak is isolated to one transport. This retires the scattered
ingest-idempotency triptych (H374 bundle, H380 events, H386 archive) and items' `test_reimport_is_idempotent` (the
per-transport cells stay as deeper regression guards, the H395 discipline). Test-only, no production change (every
importer is already content-deduped). Suite **4262 passed**. **H400 shipped this run** — the CLI↔MCP
read-parity contract, the seventh **contract-consolidation** cell and the *cross-transport* sibling of
H397's intra-CLI surface-parity matrix: one completeness-asserted invariant in `tests/test_cli_mcp_parity.py`
that *every* MCP read tool either has a CLI twin whose **custody-bearing payload** reads identically across
the (CLI command, MCP tool) twin, or is a *named* exemption. The matrix checks the four inspect + aggregate
twins H397's browse-enumerate matrix does *not* cover — `get_scroll`≡`show` (the per-item axes
`fidelity`/`drift`/`last_checked`/`content_duplicate_ids` over every held item, where the H328
content-duplicate axis lives), `get_link_graph`≡`graph` and `get_works`≡`works` (the aggregate
`stats.custody` block plus each node/representation's per-node custody axes), and
`get_library_health`≡`doctor` (the shared `run_doctor` custody block — `get_library_health` spreads it with
two distilled `attention`/`headline` members `scrolls status` adds beside it, the H367/H381 precedent, so the
twin strips them and compares the block). The **completeness keystone**
(`test_cli_mcp_twin_registry_partitions_the_mcp_read_surface`) holds `_CLI_MCP_TWINS` (the four checked twins)
∪ three *named* exemption sets — `_BROWSE_PARITY_BY_H397` (`search_scrolls`/`list_scrolls`/`list_facets`,
custody parity already H397's job), `_NON_CUSTODY_AXIS_TWIN` (the six reads with a CLI twin carrying a
*non*-custody-axis payload: the `history` ledger timeline, the `related` rank list, the `archive list`/`archive
show` recovery snapshots, the `maintain --history` ledger, the `context` bundle [CLI≡MCP byte-identity pinned
by H382]), and `_MCP_ONLY` (`get_concept_page`/`get_tag_page`/`list_sources`/`list_feed_subscriptions`, with no
CLI JSON read twin) — to partition `_MCP_READ_TOOLS` (H388) *exactly*, so a *new* MCP read tool fails until
classified; a second keystone holds every declared CLI twin path to the live `_CLI_READ_PATHS` (H394), the
"fails until *both* contracts register it" tie. The sabotage
(`test_a_single_transport_re_deriving_one_axis_fails_only_that_twin`) monkeypatches `mcp_server.get_fidelity`
(the binding *only* `get_scroll` reads through — a distinct module binding from `cli.get_fidelity` and from
the `graph`/`works`/`doctor` builders' own `get_fidelity`) to misreport one full holding's tier and pins the
failure set is *exactly* `{get_scroll}` — the cross-transport regression a single surface's own tests miss.
This retires the scattered per-twin convergence guards in `tests/test_custody_convergence.py`
(`test_status_custody_scalars_converge_with_doctor_nested_audit`, the `graph`/`works` object-twin
convergence guards, `test_mcp_library_health_converges_with_status_and_doctor`) — they stay as deeper
regression guards, the H395 discipline. Test-only, no production change (the twins share one builder, so parity
holds by construction). Suite **4266 passed**. H401 (the bundle-format briefing-parity contract) then shipped
(suite **4270 passed**), then **H402 shipped this run** — the reconcile-safety contract (the ninth
**contract-consolidation** cell, the *removal*-axis sibling of H396's refresh axis): one completeness-asserted
invariant in `tests/test_reconcile_safety.py` that when a compiled `library/` page's group vanishes,
`_reconcile_generated` (ADR 0102) **tombstones** an annotated stale page (generated region → `kb._STALE_BODY`,
the `@user` note preserved byte-for-byte) and **unlinks** a plain one, across *every* reconcilable dir-kind. The
**completeness keystone** holds `_RECONCILE_KINDS` ≡ `kb._GENERATED_DIRS` exactly and disjoint from
`kb._GENERATED_FILES` (the always-written `index.md`/`graph.md`/`works.md` never reconcile), so a *new*
reconcilable family fails until given a reconcile-safety entry; the parametrised guard drives each dir-kind to
the vanish via `delete_item` (a base item keeps the dir alive, a keep/drop pair owns two unique pages),
exercising both reconcile branches in one pass; the teeth patch `kb.has_user_content → False` unlinks the
annotated page wholesale (the failure mode the contract guards). Test-only, suite **4276 passed** (see the
Shipped ledger). **H403 shipped this run** — the browse-filter drill contract (the tenth
**contract-consolidation** cell, the *filter*-axis sibling of H397's read-parity matrix): one
completeness-asserted invariant in `tests/test_browse_filter_drill.py` that every custody/rank browse filter
(`--fidelity`/`--drift`/`--strength`/`--content-duplicate`) on `search`/`list` (+ the MCP
`search_scrolls`/`list_scrolls` twins) selects *exactly* the rows the unfiltered surface carries at that axis
value, driven off a `_BrowseFilter` registry held to the live `search`/`list` argparse optionals. **H404
shipped this run** — the compiled-page custody-honesty contract (the eleventh **contract-consolidation**
cell, the compiled-surface sibling of H398's JSON/MCP G1 matrix): one completeness-asserted invariant in
`tests/test_compiled_page_custody_honesty.py` (four tests) that *every* custody-bearing compiled `library/`
page kind renders its `_Custody:`/`_By source:`/`_Attention:`/`_Refresh:` lines **honestly** — the headline
always, the split iff ≥2 sources, the action-pointers iff their scope's basis is non-empty — lifting H190's
two `index.md`-only honest-absence tests to a matrix over the four group-page dirs + `index.md`. The
completeness keystone hardcodes `_CUSTODY_BEARING_DIRS` and asserts it equals `kb._GENERATED_DIRS` (so a
*new* dir breaks it) and that `{index.md}` ∪ a *named* `_NO_CUSTODY_HEADLINE` set (`graph.md` pure rollup,
`works.md` works-axis — the roadmap's parenthetical wrongly called `graph.md` custody-bearing; the live
compiler does not) partitions `kb._GENERATED_FILES` exactly. `index.md` is tied to the JSON `status`/`doctor`
bases (the independent H190 anchor); group pages to their own scope folds with a `_Custody: N` headline-count
cross-check; the sabotage (drop the shared `_By source:` split) fails *only* the multi-source kinds
(`index.md`/`categories`/`concepts`/`tags`), never single-source-only `sources` (suite **4284 passed**; see
the Shipped ledger). **H405 shipped this run** — the lossless-importer conflict/adoption parity contract
(the twelfth **contract-consolidation** cell, the *conflict*-axis sibling of H400's CLI↔MCP read-parity
matrix): one completeness-asserted invariant in `tests/test_import_conflict_parity.py` (six tests) that the
two Scrolls-native lossless importers (`import items`/`import bundle`, the pair routing
`content_hash`-bearing rows through `_merge_items`) detect a content conflict **identically** — held copy
kept (never overwritten), a typed `conflict` event on the append-only ledger, the divergent id in the
report's `conflicts` — and, with `--accept-incoming`, adopt **identically** — held capture archived
(recoverable via `archive show`), a `superseded` event recorded, the held row replaced. The **completeness
keystone** holds `_CONFLICT_IMPORTERS` (`{items, bundle}`) ∪ a named `_NO_CONFLICT_IMPORTS` (`events`/
`archive`, custody-store appends with no held-row content to diverge) ∪ the H399 `_IMPORT_INTERCHANGE_EXEMPT`
foreign formats (reused, cross-imported from `test_roundtrip.py`) partitioning the live `import` registry
*exactly*, so a *new* lossless importer fails until classified. The parametrised matrix pins each importer's
keep-held and adopt dispositions to one shared canonical disposition (so the importers agree by construction,
the bundle's nested `events`/`archive` report blocks normalised away) and checks the **durable** ledger event
(the decisive both-axes choice, not just the transient report). The teeth patch `cli._cmd_import_items` (the
binding only the items importer dispatches through) to overwrite-on-conflict and isolate the failure to the
items leg while the bundle leg stays green. Test-only, suite **4290 passed** (see the Shipped ledger).
**H406 shipped this run** — the CLI↔MCP write-act parity contract (the thirteenth **contract-consolidation**
cell, the *write-side* sibling of H400's read-parity matrix): one completeness-asserted invariant in
`tests/test_cli_mcp_write_parity.py` (four tests) that *every* custody-safe MCP write tool produces the
**same durable custody effect** as its CLI act twin over two fresh fixture copies — `verify_scroll`≡`verify`
(the appended `item_events` row), `run_maintenance`≡`maintain --no-recheck` (the report + recorded
snapshot/trend), `compile_library`≡`kb` (the compiled-`library/` whole-tree hash), the feed ops≡`follow`/
`unfollow`/`sync` (the subscription roster). The **completeness keystone** — `_WRITE_TWINS` ∪ a named
`_NETWORK_WRITE_EXEMPT` (`ingest_url`) partition `_MCP_SAFE_WRITE_TOOLS`/H364 *exactly* — fails when a new
MCP write tool ships without a declared CLI act twin; the verb sabotage (an MCP `verify_item` recording
`rotted` where the CLI records `drifted`) fails *only* the `verify_scroll` leg. Test-only, suite **4294
passed** (see the Shipped ledger). The forward buffer's **contract-consolidation** theme now leads with
**H407** (rank-explainability convergence), with **H408–H412** the remaining consolidation cells.

**The forward-hardening guard cells.** The per-tool MCP determinism treadmill is closed (H388's
completeness-asserted whole-surface contract subsumes it — a new read tool now fails the contract until
covered, so no further per-tool twins are needed). The active queue is the **contract-consolidation**
theme: each cell replaces a *family* of per-surface tests with a single completeness-asserted invariant
that auto-covers new surfaces (the H388 pattern applied to round-trip, regeneration-safety, surface-parity,
and completeness-honesty — the PRD success metrics). Take the next one whose preconditions are met (H407
next; H405 lossless-importer conflict/adoption parity + H406 CLI↔MCP write-act parity shipped — see the
Status snapshot / Shipped ledger):

| Slot | Intended slice | Maps to |
| --- | --- | --- |
| H407 | **Rank-explainability convergence contract — the *rank*-axis sibling of H397's custody-axis surface matrix: one completeness-asserted invariant that every surface carrying an explainable-rank band reads the *same* band for the same item/edge as the canonical fold — `match_strength` on `search`/`context`/`export bundle` (the `_Strength:_` headline + per-row marker), `relation_strength` on `related`/`graph` (the `_Strength:_` neighbour marker) — and each surface's headline tally converges with its own per-row bands, pinned once over a `_RANK_SURFACES` registry rather than the scattered H312–H324 per-surface strength tests. The fourteenth **contract-consolidation** cell whose **completeness keystone** — `_RANK_SURFACES` (each surface × its rank axis) ∪ a named `_NO_RANK_AXIS` exemption set (the pure-custody reads with no rank band: `list`/`works`/`doctor` + their MCP twins) must partition the rank-bearing slice of `_CLI_READ_PATHS`/H394 ∪ `_MCP_READ_TOOLS`/H388 *exactly*, so a *new* rank-bearing surface fails until it declares its band-convergence. → PRD success-metric: re-derivable enrichment + confidence markers (cap 8).** Over one fixture spanning all three strength bands (a title hit, a summary-only hit, a body-only hit) and a relation edge, assert each surface's per-row band equals `search.match_strength`/`related.relation_strength` for that id and its headline tally sums to the bands. **Sabotage:** one surface re-deriving a band a tier high must fail *only* that surface's leg (the H397 binding-isolation precedent). **Decisive choice:** drive the loop off the rank-bearing partition of the live read registries so a new rank surface is forced to prove band convergence. Test-only. Precondition: `match_strength`/`render_strength_headline`/`tally_strength` (`search.py`), `relation_strength` (`related.py`), the H397 `_seed_surface_parity_mix` fixture, the H312–H324 per-surface strength tests. | → cap 8 |
| H408 | **Raw-immutability act-surface contract (the CLI sibling of H364's MCP holdings-immutability, on the *raw-bytes* axis) — one completeness-asserted invariant that *every* CLI act/write command leaves the held raw `scrolls/` capture tree **byte-identical** (a `{relpath → sha256}` whole-tree hash, the H363 helper) except a named raw-writing set, so no recompile/verify/maintain/reconcile/classify/feed op ever mutates or destroys a held raw scroll (custody-vision §2.4, raw is sacred). The fifteenth **contract-consolidation** cell whose **completeness keystone** — `_CLI_WRITE_COMMANDS` (H394) partitioned into `_RAW_PRESERVING_ACTS` (the acts that must leave raw untouched: `verify`/`maintain`/`kb`/`reconcile`/`classify`/`follow`/`unfollow`/`sync`/`export *`) ∪ a named `_RAW_WRITING` set (`save`/`ingest`/the `import *` family that legitimately captures or adopts raw, and `doctor --fix`, which *restores* a deleted raw scroll — the H365 repair axis) partitioning the live write registry *exactly* — fails when a *new* write command ships without declaring whether it touches raw. → PRD success-metric: raw is sacred; no act destroys/overwrites a held capture (cap 4).** For each raw-preserving act: hash `scrolls/` before and after running the act over the shared fixture and assert byte-identity; for each named raw-writer assert its raw mutation is non-vacuous (the exemption is earned, not a silent skip). **Sabotage:** an act that rewrites one held scroll's bytes (e.g. a `verify` that re-renders the capture) must fail *only* its leg. **Decisive choice:** drive the loop off `_CLI_WRITE_COMMANDS` so a new act is forced to declare raw-immutability-or-write — the H364 mechanism on the CLI raw-bytes axis. Test-only. Precondition: `_CLI_WRITE_COMMANDS` (H394, `tests/test_cli_determinism.py`), the H363 `{relpath → sha256}` whole-tree-hash helper, the shared `seed_read_surface_determinism_mix`, the CLI act handlers in `cli.py`. | → cap 4 |
| H409 | **Append-only custody-ledger contract — one completeness-asserted invariant that the `custody_events` ledger only ever *grows*: across *every* mutating surface (every CLI write command ∪ every custody-safe MCP write tool), no existing ledger row is ever deleted or rewritten — the per-`(item_id, kind, at)` identity set after any act is a **superset** of the set before (drift/conflict/supersession is a recorded *event*, never an overwrite; custody-vision §1, ADR 0104). The sixteenth **contract-consolidation** cell and the ledger-integrity sibling of H408's raw-immutability, lifting the scattered per-event durability tests (the H274 conflict-event, the H311 supersession-event, the verify-event tests) to one matrix whose **completeness keystone** — `_LEDGER_MUTATORS` ≡ `_CLI_WRITE_COMMANDS` (H394) ∪ `_MCP_SAFE_WRITE_TOOLS` (H364), each act classified `appends` (names the verb[s] it adds) or `ledger-neutral` (a named set that records nothing: `kb`/`reconcile`/`export *`) — fails when a *new* mutating surface ships without declaring its ledger effect. → PRD success-metric: every drift/conflict event is durable and append-only (cap 8).** For each mutator: snapshot the `_EVENT_IDENTITY` row set, run the act over the shared fixture, and assert the new set ⊇ the old (and, for an `appends` act, that exactly its declared verb joined). **Sabotage:** an act that rewrites a prior event row's `at` (a silent ledger edit) shrinks/replaces the identity set and must fail *only* its leg. **Decisive choice:** drive the loop off the union write-registry so a new act is forced to declare append-or-neutral — the H400/H406 keystone mechanism on the ledger axis. Test-only. Precondition: `_EVENT_IDENTITY`/`record_events` (`custody.py`), `_CLI_WRITE_COMMANDS` (H394), `_MCP_SAFE_WRITE_TOOLS` (H364), the H274/H311 durability tests, the shared `seed_read_surface_determinism_mix`. | → cap 8 |
| H410 | **Stale-set drill contract — the *staleness*-axis sibling of H403, picking up the three custody-adjacent browse filters H403 explicitly *named as exempt* (`_NON_DRILL_FLAGS`: `--stale-before`/`--stale-classification`/`--stale-summary`, each a range/flag read whose drill H403 left to its own scattered guard). One completeness-asserted invariant that each stale-* filter on `list` (+ the MCP `list_scrolls` twin) selects *exactly* the rows its act-side companion would act on and its `doctor` aggregate counts — `--stale-before <ISO>` ≡ the set `verify --stale-before` re-captures (H85), `--stale-classification` ≡ `classify --stale`'s targets ≡ `doctor`'s `custody.enrichment.stale` (H185), `--stale-summary` ≡ `kb --stale`'s cluster members (H189) — pinned once over a `_STALE_FILTERS` registry rather than the three scattered per-filter convergence tests. The seventeenth **contract-consolidation** cell whose **completeness keystone** — `_STALE_FILTERS` ≡ exactly the `list` argparse flags H403's `_NON_DRILL_FLAGS` tagged as *stale-axis* (imported from `tests/test_browse_filter_drill.py`, so the two registries can't drift: a flag is either an H403 value/band/flag drill or an H410 stale-axis drill, never silently neither) — fails when a *new* stale-axis filter ships without a drill assertion. → PRD success-metric: read-side ≡ act-side ≡ audit convergence (cap 7/1).** For each stale-* filter over a fixture with a non-vacuous stale set on each axis (a ledger-old item, a ruleset-stale classification, a member of a stale concept summary), assert the `list`/`list_scrolls` rows equal the act-side selector's targets and (where it has one) the `doctor`/`get_library_health` count. **Sabotage:** a filter whose post-SQL selector admits one fresh row must fail *only* that filter's leg (the H403 selector-isolation precedent — `items_checked_before`/`stale_classifications`/`stale_summary_members` are three distinct seams). **Decisive choice:** import H403's `_NON_DRILL_FLAGS` so the stale-axis flags are forced into *this* contract the moment H403 exempts them — the two browse-filter registries jointly cover the whole `list` filter surface. Test-only. Precondition: `list_items`' `stale_before`/`stale_classification`/`stale_summary` clauses, `custody.items_checked_before`, `classify.stale_classifications`, `kb_llm.stale_summary_members`, the H85/H185/H189 convergence guards, H403's `_NON_DRILL_FLAGS` in `tests/test_browse_filter_drill.py`. | → cap 7 |
| H411 | **Facet-aggregate drill contract — the *aggregate↔enumeration* completion of the H403 browse-filter matrix: one completeness-asserted invariant that *every* `facets <dimension>` per-value count equals exactly the number of rows the matching `list`/`search` value-filter enumerates at that value, across the whole facet vocabulary (`sources`/`categories`/`stages`/`tags`/`concepts`/`fidelity`/`drift`/`method`/`content-duplicate`), so the aggregate an agent browses by is always a faithful index into the rows it can then drill — pinned once over the live `facets` field registry rather than the scattered per-dimension drill-from-count tests (`test_content_duplicate_facet_converges_with_doctor_and_the_drill_filter`, the per-facet `…_facet_counts_…` guards). The eighteenth **contract-consolidation** cell whose **completeness keystone** — a `_FACET_DIMENSIONS` registry asserted to equal the live `facets` field choices exactly, each mapped to the `list`/`search` filter (or a *named* no-drill-filter exemption, e.g. a facet with an aggregate but no row filter) — fails when a *new* facet dimension ships without a drill tie. → PRD success-metric: filter consistency / completeness honesty (cap 7).** For each dimension over the H403/H397 wide fixture, assert `count_facets(field)[value]` equals `len(list --<field> value)` for every enumerated value (and the search twin where the filter exists). **Sabotage:** a facet counter that double-counts one value (or a filter that drops one row) desyncs *only* that dimension's leg. **Decisive choice:** drive the loop off the live `facets` field vocabulary so a new dimension is forced to prove its count↔rows tie. Test-only. Precondition: `facets.count_facets`/the `facets` argparse field choices, `list_items`/`search_items` value filters, the H397/H403 fixtures, the per-facet convergence guards in `tests/test_facets.py`. | → cap 7 |
| H412 | **Enrichment-provenance convergence contract — the *enrichment*-axis sibling of H407's rank-explainability convergence (H407 pins the *rank* band reads the same on every surface; this pins the classification provenance — engine/method, the ruleset/model fingerprint, and the confidence/recency marker — reads the same on every surface that carries it). One completeness-asserted invariant that for *every* held item its enrichment provenance reads identically across the classification-bearing surfaces — `search` hits (H26), `list`/`show` rows, the MCP `search_scrolls`/`list_scrolls`/`get_scroll` twins, the `facets method` aggregate (H28), and the compiled `library/` group pages (H89-family marker) — against one canonical projection read off the stored classification record (`classification.method`/`ruleset_fingerprint`/`confidence`, the H20/H21 provenance the re-derivable record stores). The nineteenth **contract-consolidation** cell whose **completeness keystone** — `_PROVENANCE_SURFACES` ∪ a named `_NO_PROVENANCE_AXIS` exemption set (the pure-custody/rank reads that carry no classification marker: `works`/`graph`/`related`/`doctor` + their MCP twins, and the model-facing `context` bundle whose provenance rides per-excerpt tags H44) must partition the classification-bearing slice of `_CLI_READ_PATHS`/H394 ∪ `_MCP_READ_TOOLS`/H388 *exactly*, so a *new* enrichment-bearing surface fails until it declares its provenance convergence (the H397/H407 mechanism on the enrichment axis). → PRD success-metric: re-derivable enrichment + confidence/recency markers (cap 8).** Over the H397/H407 wide fixture (already multi-method: rule-classified + a stale-ruleset item + an LLM-summarized concept), assert each surface's per-item provenance marker equals the canonical projection for that id, and the `facets method` count-for-count against the canonical method tally. **Sabotage:** one surface (e.g. `cli.item_summary`, the `list` row builder — a distinct binding from `mcp_server.item_summary`/`hit_payload`) re-deriving a stale-ruleset item's method as fresh must fail *only* that surface's leg (the H397/H400 binding-isolation precedent). **Decisive choice:** drive the loop off the enrichment-bearing partition of the live read registries so a new classification surface is forced to prove provenance convergence. Test-only. Precondition: the classification provenance record (`classify.py`'s `method`/`ruleset_fingerprint`/`confidence`, H20/H21), the per-surface markers (H26/H28/H33/H89), the H397 `_seed_surface_parity_mix` / H407 fixtures, `_CLI_READ_PATHS`/H394, `_MCP_READ_TOOLS`/H388. | → cap 8 |

**De-prioritized backlog** — the budget/tier convergence cells **H244–H249** remain valid
regression guards but are explicitly de-prioritized (the tail of a combinatorial matrix,
each correct-by-construction); reach for them only when no capability or forward-hardening
slice is ready, and prefer closing one over appending more of the same shape.

---

## Shipped ledger (compact index)

One line per shipped slice; the full description + diff live in git
(`git log --oneline | grep '(H<NN>)'`). This index exists only to keep `H<NN>`
cross-references resolvable in-file — it is **not** a changelog (maintenance-rule §4).
Re-compacted 2026-06-25 (the per-slice prose that had re-accreted here and in the
status snapshot was folded back to one line each).

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
| H363 | In-place `kb` recompile-determinism guard (test-only) — a same-process two-pass whole-tree-hash no-op (recompile rewrites/removes nothing; splice + ADR-0102 reconcile are idempotent) **plus** a cross-`PYTHONHASHSEED` subprocess pair (the latter the only one that catches an unsorted page-fold leak the same-process pass cannot); first forward-hardening/integration cell | cap 1, cap 9 |
| H364 | MCP holdings-immutability contract guard (test-only) — one `tests/test_mcp.py` test pins `mcp_server._TOOLS` (asserted ≡ what `build_server` registers) is exactly an allow-list of 17 read + 7 custody-safe-write tools **and** no non-feed tool name carries a capture-destroying verb (delete/remove/drop/purge/prune/rm/overwrite/merge, token-based snake_case); a sabotage `delete_scroll` fails both halves — the M2 tested-contract shape lifted to the tool registry, second forward-hardening pivot cell | cap 7, cap 1 |
| H365 | `doctor --fix` repair-convergence guard (test-only) — one `tests/test_doctor.py` test seeds real repairable findings (deleted scroll → `missing_scrolls`, FTS desync), `--fix` fixes both, then a second `--fix` with no intervening mutation is pinned a total no-op on **both** axes: report level (`issues == 0`/`fixed == 0`, every finding list empty) **and** disk level (a `{relpath → sha256}` whole-tree hash of `scrolls/` byte-identical, no scroll silently re-rendered); a held byte-identical content pair stays a non-finding on both passes (H337). Two sabotages prove the teeth — a silent re-render fails only the hash assertion, a dropped `exists()` short-circuit fails the report no-op; third forward-hardening pivot cell, the H363 whole-tree-hash precedent on the repair axis | cap 1, cap 9 |
| H366 | `context --budget` tier-nesting contract guard (test-only) — two `tests/test_context.py` tests (the CLI bundle + the MCP `get_context_bundle` twin) pin the M3 strictly-nested `index`/`connected`/`full` contract as a whole over one seeded library (3 keyword matches + 1 linked-but-unmatched neighbour): the **Best-Match id set is identical** across all three tiers (the load-bearing depth-vs-set orthogonality — a leaner budget cuts per-match depth, never the match set), the **Connected** block is absent at `index`, present at `connected`/`full` and **byte-identical** between them, **Excerpts** appear only at `full`, and the `_Budget:_` depth note renders on `index`/`connected`, omitted at `full`. Sabotage: a "save tokens" truncation dropping a Best Match at a leaner budget fails the set-equality assertion on both surfaces while all 12 per-block presence budget tests stay green; fourth forward-hardening pivot cell, the agent-facing read-budget axis | cap 1, cap 3 |
| H367 | `scrolls status` ↔ `doctor` custody-scalar convergence guard (test-only) — one `tests/test_custody_convergence.py` test over a non-vacuous fixture (a byte-identical content pair, a stale-classified member, a drifted item carrying an unresolved import conflict, an all-reference at-risk work) pins the *whole* lean-`status` flat custody block scalar-to-nested against the full `doctor --json` `custody` audit, field-for-field (`score`/`tiers`/6 `drift` axes/`coverage`/`enrichment_stale`/`summaries_stale`/`at_risk`→`works.at_risk`/`conflicts`→`conflicts.items`/`archive_mismatched`→`archive.mismatched`/`content_duplicate_{groups,items}`→`content_duplicates.total_{groups,items}`/whole `posture`). Sabotage: re-wiring one `status` scalar in `_cmd_status` fails *only* the guard while all 434 `maintain`+`doctor` unit tests stay green — the boot↔audit desync the `custody_snapshot` unit tests (projection in isolation) never cover; fifth forward-hardening pivot cell, the M2 cross-surface-semantics contract on the boot-vs-audit axis | cap 1, cap 7 |
| H368 | Whole-library `export bundle` determinism + round-trip byte-identity guard (test-only) — two `tests/test_bundle.py` tests over a multi-source + drift-event fixture (`_seed_multi_source`, so the per-source breakdown + items block + custody-events block are non-vacuous) pin the shareable bundle is a *reproducible artifact*: two exports of one unchanged library are **whole-text byte-identical** (the H363 whole-tree-hash precedent on the bundle axis), AND a real `export bundle` → `import bundle` into a fresh `SCROLLS_HOME` → re-`export bundle` (both sides materialised via `doctor --fix`/`kb`) reproduces the sender's bytes. Sabotage: a `random.random()` in the bundle header fails *both* assertions while every per-section bundle test stays green; sixth forward-hardening pivot cell, the portable-bundle/export-transport reproducibility axis | cap 1, cap 4 |
| H369 | `doctor`'s whole-library `custody.posture` verdict (`{verdict: sound\|attention\|at_risk, reasons}`) — the seven custody blocks distilled by `_assess_custody_posture` into one fold (+ the `get_library_health` MCP twin) | cap 1, custody-vision §3.1 |
| H370 | The readable `_Posture:_` line on the `maintain` report (`posture_headline`) + the `status.custody.posture` scalar twin — the verdict made human and machine-readable, always-rendered | cap 1, cap 2 |
| H371 | The `_Posture:_` briefing line on `export bundle` + `scrolls context` — `doctor`'s whole-library `custody.posture` verdict travels with the shareable/agent briefings, always-rendered | cap 1, custody-vision §3.1 |
| H372 | The cross-run posture-movement clause on the `maintain`/trend `_Posture:_` line — `compute_delta` gains a categorical `posture` axis, `compute_trend` a `posture_change` + windowed `posture_headline`, the renderer the `sound → attention` band transition; reported, never a trajectory trigger | cap 1, cap 7 |
| H373 | The cross-surface posture convergence guard (test-only) — one `tests/test_custody_convergence.py` test pins `status`≡`doctor`≡`get_library_health`≡`maintain`/`run_maintenance`≡the bare `export bundle`/`context` `_Posture:_` line on one non-vacuous `sound → attention` fixture, plus the movement axis (report clause off `delta.posture.before`, trend `posture_change`/windowed `posture_headline`) at CLI↔MCP parity; closes the custody-posture theme | cap 1, cap 7 |
| H374 | `import bundle` re-import idempotency guard (test-only) — one `tests/test_bundle.py` test over the `_seed_multi_source` fixture materialised in a fresh `SCROLLS_HOME` (`doctor --fix`/`kb`) pins that re-importing the *same* bundle into a library that already holds it is a true no-op on **all three** axes: the item rows (count + per-id `item_to_dict` identity, no re-insert), the `scrolls/` disk bytes (a `{relpath → sha256}` whole-tree map byte-identical, nothing re-rendered — the H363/H365 whole-tree-hash precedent on the import axis), and the conflict ledger (zero `conflict` events — byte-identical content is not a divergence, ADR-0104); the re-import report confirms `imported == 0`/`skipped == 3`/`conflicts == []`/`content_duplicates == 0`. Two sabotages prove the teeth — flagging every re-import a conflict fails the conflict-ledger axis, re-inserting the held row fails the `imported == 0` axis — while every single-import round-trip test stays green; seventh forward-hardening pivot cell, the ingest-transport settle axis | cap 1, cap 4 |
| H375 | `scrolls doctor` whole-report determinism guard (test-only) — two `tests/test_doctor.py` tests over a new non-vacuous fixture (`_seed_doctor_determinism_mix`: 3 sources → a multi-key `custody.by_source`, a byte-identical content pair, a drifted full item *also* carrying an unresolved import conflict → non-empty `drift.events` + `conflicts.events`, a tampered archived prior → a mismatched `archive.events` row, an all-reference work → `works.most_at_risk`; structurally clean, `issues == 0`) pin the audit `status`/`maintain`/MCP `get_library_health` all fold (H367) is a *reproducible artifact*: two same-process `run_doctor` reads serialize byte-identical (no wall-clock/counter leak), AND `scrolls doctor` emits byte-identical stdout across two subprocesses under different `PYTHONHASHSEED`s (the H363 `kb` cross-seed copytree precedent on the audit axis). Decisive: the cross-seed pair — a `set` leaking into any sub-block iterates the *same* way twice under one fixed seed, so the same-process read stays green; only differently-seeded processes diverge (verified by a by-source set-fold sabotage that fails the cross-seed guard while the same-process read passes; a 6-seed sweep confirms one report hash); eighth forward-hardening pivot cell, the audit trust-root reproducibility axis | cap 1 |
| H376 | `scrolls context` bundle determinism guard (test-only) — two `tests/test_context.py` tests over a new wide fixture (`_seed_context_determinism_mix`: 8 "database" keyword matches each linking to one unique unmatched paper → an 8-element Best-Match list + 8-bullet Connected link-graph + 8 Excerpts; the H366 single-neighbour nested-library widened so the connected-fold sabotage is non-vacuous) pin the model-facing context bundle — an agent's *primary read* — is a *reproducible artifact*: two same-process `scrolls context db --budget full` reads are byte-identical (no wall-clock leak), AND the command emits byte-identical stdout across two subprocesses under different `PYTHONHASHSEED`s (the H363 `kb` / H375 `doctor` cross-seed copytree precedent on the agent-read axis — `context.py` builds Connected/Excerpts from search + relatedness folds the H368 `export bundle` never runs, a distinct code path). Decisive: `--budget full` (every order-sensitive section exercised) + the cross-seed pair. Sabotage: folding the connected-neighbours section over a `set` (`list(set(connections))` in `_connected_lines`) fails *only* the cross-seed byte-identity while the same-process read **and** H366's two nesting tests stay green (verified the 8-element fold reliably diverges across seeds 0/1; 4 did not); ninth forward-hardening pivot cell, the agent-read-surface reproducibility axis | cap 1, cap 3 |
| H377 | `scrolls maintain` trend-log determinism + no-movement settle guard (test-only) — three `tests/test_maintain.py` tests over the H367 non-vacuous mix (`_seed_maintain_determinism_mix`: a byte-identical content pair, a stale-classified member, a drifted item *also* carrying an unresolved import conflict, an all-reference at-risk work, a partial item; structurally clean, `issues == 0`) pin the snapshot/trend an unattended worker reads to judge "is custody degrading?" is **settled** and **reproducible**: two `maintain --no-recheck` passes record byte-equal comparable scalars and *both* `compute_delta(S1,S2)` and the second pass's *production* delta are the all-zero/no-movement shape on every axis (scalar + per-key mapping + the categorical posture band); the whole `maintain --no-recheck` report is byte-identical (minus the wall-clock `recorded_at`) across `PYTHONHASHSEED` 0/1; and `maintain --history --trend` over a *fixed* two-entry log (`sound → at_risk`) is byte-identical across seeds **and** read-stable same-process. Three sabotages prove the teeth — a phantom `+1` in a `compute_delta` axis fails the settle, the posture `reasons` folded over a `set` in `custody_snapshot` fails the report cross-seed, the same fold in `posture_headline`'s reasons join fails the trend cross-seed — while all 300 existing `maintain` tests stay green; tenth forward-hardening pivot cell, the cross-run maintenance-ledger settle + reproducibility axis | cap 1 |
| H378 | `export bundle --format html` whole-text determinism guard (test-only) — one `tests/test_bundle.py` test over the H368 multi-source + drift-event fixture (`_seed_multi_source`, materialised via `doctor --fix`/`kb`) pins the browser-readable briefing (H39) is a *reproducible artifact*: exporting the same unchanged library to HTML twice yields a **byte-identical** document (whole-text, the H368 whole-artifact precedent on the HTML axis — a distinct code path: `build_bundle_html` emits `html.escape`d `<h1>`/`<h2>`/`<li>` markup + the `_html_document` wrapper the Markdown form never runs). HTML is export-only (no `import bundle --format html`; the import path consumes the Markdown `@generated` fence), so — unlike H368 — there is no round-trip leg, only same-library two-export determinism; non-vacuity asserts the `<h1>` + a per-source `<li>`. Sabotage: a `random.random()` injected into the `<h1>` heading fails the byte-identity while the per-section HTML substring tests stay green (the whole-document reproducibility regression they structurally cannot see); eleventh forward-hardening pivot cell, the HTML-render reproducibility axis | cap 9 |
| H379 | `export items` JSONL whole-file determinism + round-trip byte-identity guard (test-only) — one `tests/test_roundtrip.py` test over the multi-source `_seed_items` fixture pins the whole-library-backup transport (`scrolls export items`, the same `dump_items_export` fold the bundle item block wraps but over the *entire* holdings, no query scope) is a *reproducible artifact* on two axes: exporting the same unchanged library twice yields **byte-identical** JSONL (the genuinely-new axis — the existing `test_export_rebuild_is_byte_identical` pins only the round-trip re-export leg amid a five-surface rebuild check, never the same-library two-export determinism), AND a real `export items` → `import items` into a fresh `SCROLLS_HOME` → re-`export items` reproduces the sender's bytes (the leaner round-trip needs no `doctor --fix`/`kb` — `export items` reads the index rows `import items` populates). Decisive: compare the *whole JSONL file* (not one row) on both axes; *not* cross-seed (no set to scramble — `dump_items_export` is a pure ordered fold: `list_items` orders `ORDER BY saved_at, id`, `item_to_dict` is `asdict` in dataclass field order, the H384 "same-process two-export check suffices" guidance). Sabotage: a per-call counter appended to one exported row (`_seq`) fails the same-library determinism axis (`_seq: 1` vs `_seq: 2`) while every per-row round-trip tree test stays green; twelfth forward-hardening pivot cell, the whole-library-backup-transport reproducibility axis | cap 9 |
| H381 | MCP `get_library_health` whole-payload determinism guard (test-only) — two `tests/test_mcp.py` tests over a local mirror of the H375 non-vacuous fixture (`_seed_health_determinism_mix`: 3 sources → a multi-key `by_source`, a byte-identical content pair, a drifted full item *also* carrying an unresolved import conflict → non-empty `drift.events` + `conflicts.events`, a tampered archived prior → a mismatched `archive.events` row, an all-reference work → `works.most_at_risk`; `issues == 0`) pin the *agent-facing* custody audit (the MCP twin of `scrolls doctor`, H161 — a *separate serialization*: `get_library_health` spreads `run_doctor`'s custody block and adds `attention`/`headline` through the MCP tool envelope, a distinct code path from the CLI `print(json.dumps(run_doctor(...)))` H375 pinned) is a *reproducible artifact*: two same-process `get_library_health()` reads serialize byte-identical, AND the tool emits a byte-identical payload across two subprocesses under different `PYTHONHASHSEED`s (the H375 `doctor` cross-seed copytree precedent on the MCP-surface axis). Rides the H186/H180 registered-twin shape contract (every `run_doctor` custody key carried verbatim, keys ≡ custody ∪ {`attention`, `headline`}, the tool in `_TOOLS`). Decisive: the cross-seed pair — a by-source `set`-fold sabotage in the MCP path fails *only* the cross-seed guard while the same-process read and the `returns_the_doctor_custody_block` shape test stay green (verified); fourteenth forward-hardening pivot cell, the MCP audit-twin reproducibility axis | cap 1/2 |
| H380 | `import events` re-import idempotency guard (test-only) — one `tests/test_roundtrip.py` test (the events-transport sibling of `test_reimport_is_idempotent`) over `_build_library(_seed_items())` with a recorded ledger (verify `unchanged → drifted` + an import `conflict` on item 0, one verify on item 1 = 4 events spanning ≥2 items + the conflict axis) pins that `export events` → `import events` *twice* into a fresh `SCROLLS_HOME` is whole-ledger idempotent: the second pass reports `imported == 0`/`skipped == 4`, the raw `custody_events` row count is unchanged across both passes (`import_events` content-dedups on the `_EVENT_IDENTITY` 5-tuple — a *distinct* code path from `merge_item`'s `INSERT OR IGNORE`, never the per-library autoincrement id), and every item's `item_history` timeline is byte-identical list-for-list. Decisive: assert *both* the raw row count (catches a silent double-insert) **and** the per-item `history` list identity (catches a dedup that drops the wrong row) — a naïve "import reports skipped" check is blind to a re-keyed dedup that both skips *and* re-inserts. Two sabotages prove the teeth — dropping the `_EVENT_IDENTITY` dedup fails the second-pass report (re-imports all 4), and a dedup that reports `skipped` yet re-inserts anyway passes the report axis but fails the row-count axis (8 ≠ 4) — while every single-import round-trip/events-export test stays green; thirteenth forward-hardening pivot cell, the ledger-ingest settle axis | cap 9 |
| H382 | MCP `get_context_bundle` whole-payload determinism guard (test-only) — two `tests/test_context.py` tests over the H376 wide fixture (`_seed_context_determinism_mix`: 8 "database" matches + 8 Connected neighbours) pin the *agent-transport* context bundle (the MCP twin of `scrolls context`, exercised by the H366 MCP nesting twin — `get_context_bundle` folds the *same* deterministic `build_context` the CLI prints, a separate MCP entry point H376's CLI `print(build_context(...))` determinism never pins) is a *reproducible artifact*: two same-process `get_context_bundle("database", budget="full")` reads byte-identical AND byte-identical to the CLI `build_context` over the same query/budget (the registered-twin shape contract — no MCP-side re-wrap, the tool in `_TOOLS`), AND the tool emits byte-identical output across two subprocesses under different `PYTHONHASHSEED`s (the H376 `scrolls context` cross-seed copytree precedent on the MCP-surface axis). Decisive: the cross-seed pair + `budget="full"` (every order-sensitive section exercised). Sabotage: a `set`-fold of the shared connected-neighbours section (`list(set(connections))` in the connected-lines fold) fails *only* the cross-seed byte-identity while the same-process read **and** the H366 nesting twin stay green; fifteenth forward-hardening pivot cell, the MCP context-bundle reproducibility axis | cap 1, cap 3 |
| H383 | MCP `run_maintenance` whole-payload determinism + no-movement settle guard (test-only) — two `tests/test_mcp.py` tests over a local mirror of the H377 non-vacuous fixture (`_seed_maintain_determinism_mix`: a byte-identical content pair, a stale-classified member, a drifted item *also* carrying an unresolved import conflict, an all-reference at-risk work, a partial item; `issues == 0`) pin the *agent-facing* scheduled-maintenance pass (the MCP twin of `scrolls maintain`, H196 — an agent driving MCP never calls the CLI, it calls `run_maintenance` which passes a `skipped_recheck_report` and returns the same `assemble_report` through the MCP tool envelope, a distinct entry point + serialization H377's CLI `_cmd_maintain` settle/determinism never pins) is both *settled* and *reproducible*: two in-process `run_maintenance()` calls record byte-equal comparable snapshot scalars (the recorded snapshot + the report `custody` block) and the second's `delta` is the all-zero/no-movement shape on every axis (scalar + per-key mapping + the categorical posture band), AND the whole payload is byte-identical (minus the wall-clock `recorded_at`) across a `PYTHONHASHSEED` subprocess pair. Rides the H186/H180 registered-twin shape contract (the tool in `_TOOLS`, the documented 21-key report shape). Decisive: assert *both* faces — the settle (the value face a fixed seed catches) and the cross-seed determinism (the iteration-order face a same-process pass cannot). Two sabotages prove the teeth — a phantom `+1` in `_scalar_delta` (`change == 0 → 1`) fails *only* the settle, and the posture `reasons` folded over a `set` in `custody_snapshot` fails *only* the cross-seed while the per-tool `run_maintenance` shape tests stay green; suite **4213 passed**; sixteenth forward-hardening pivot cell, the MCP scheduled-maintenance settle + reproducibility axis | cap 1/2 |
| H384 | `export events` JSONL whole-file determinism + round-trip byte-identity guard (test-only) — one `tests/test_roundtrip.py` test (`test_export_events_is_a_reproducible_artifact`, the events-transport sibling of H379's `export items` reproducible-artifact guard and the *export* complement of H380's `import events` idempotency) over `_build_library(_seed_items())` + a chronologically-appended ledger (verify `unchanged`×2 + `drifted` + an import `conflict` = 4 events spanning ≥2 items, ≥2 statuses, a non-None `detail`) pins the whole-library custody-events backup (`scrolls export events`, ADR 0082/H72 — the `dump_events_export` fold the bundle's custody-events block also emits) is a *reproducible artifact*: two same-library exports are **byte-identical** whole-file (the artifact a `diff` across two machines must match), AND a real `export events`→full restore (`import items` + `import events`, since `export events` is item-scoped) into a fresh `SCROLLS_HOME`→re-`export events` reproduces the sender's bytes (the seeded ledger's chronological append order makes `import_events`' sort-by-`checked_at` a no-op so the fresh home's `ORDER BY id` re-export matches). Decisive: compare the *whole JSONL file* not one row, and include the round-trip — H72/H73/H78 compare rebuilt *posture* not bytes, so an unsorted event fold or a per-row set-iteration leak would pass those yet make two backups disagree. Sabotage: a per-call counter appended to each exported event row fails *only* the same-library byte-identity while every events-export/round-trip test stays green; suite **4214 passed**; seventeenth forward-hardening pivot cell, the events-transport reproducibility axis | cap 9 |
| H385 | `scrolls archive show` JSONL determinism + restore round-trip guard (test-only) — one `tests/test_cli.py` test (`test_archive_show_is_a_reproducible_recovery_artifact`, the archive-recovery-transport sibling of H379's `export items` determinism) over `_seed_with_archived_priors(…, 3)` (three adoptions → the archive holds priors v2/v1/abc newest-first) pins the recovery read (the superseded prior the un-launderable integrity alarm preserves, ADR 0106/H278/H285 — `dump_items_export` folded over `item_archive` rows via `archived_snapshots`, an `ORDER BY id DESC` path distinct from `list_items`) is a *reproducible artifact*: two `archive show <id>` reads byte-identical whole-file on **both** the single-prior default *and* the `--all` multi-prior fold (the order-sensitive `archived_snapshots` path the default never hits), the default ≡ the `--all` head (convergence), AND a real `archive show <id>` → `import items --accept-incoming` re-adopts the archived prior (held v3 → recovered v2). Decisive: compare the *whole JSONL document* not one row, exercise the `--all` multi-prior fold, include the restore round-trip; *not* cross-seed (`archived_snapshots` is an `ORDER BY id DESC` fold, no set — same-process two-read suffices, the H384 guidance). Sabotage: a per-call counter folded into one shown prior row (`_seq`) fails *only* the byte-identity (`_seq: 1` vs `_seq: 2`) while every archive-show/round-trip test stays green; suite **4215 passed**; eighteenth forward-hardening pivot cell, the archive-recovery-transport reproducibility axis | cap 9 |
| H386 | `import archive` whole-store re-import idempotency guard (test-only) — one `tests/test_cli.py` test (`test_reimport_archive_is_whole_store_idempotent`, the third member of the ingest-idempotency triptych after H374 `import bundle`/H380 `import events`) over `_seed_with_archived_priors(…, 3)` (three superseded priors → the archive holds abc/v1/v2, newest-first [v2, v1, abc]) pins that `export archive` → `import archive` **twice** into a fresh `SCROLLS_HOME` is a true whole-store no-op on three axes: the second pass reports `imported == 0`/`skipped == 3` (report), the raw `item_archive` row count is unchanged across both passes (`import_archive` content-dedups on `_ARCHIVE_IDENTITY = (item_id, prior_hash)`, a *distinct* code path from `merge_item`'s `INSERT OR IGNORE` and `import_events`' 5-tuple), and every item's `archived_snapshots(id)` recovery history is identical list-for-list. The **multi-prior** sharpening of the pre-existing single-prior `test_import_archive_is_idempotent`: a one-prior archive cannot distinguish the full `(item_id, prior_hash)` key from `item_id` alone, but a three-prior history does. Decisive: assert *both* the raw row count (catches a silent double-insert) **and** the per-item `archived_snapshots` list identity over a multi-prior history (catches a dedup that drops the wrong prior) — the H380 both-axes precedent. Two sabotages prove the teeth — a dedup that reports `skipped` yet re-inserts anyway passes the report axis but fails the row-count axis (6 ≠ 3), and an `item_id`-only dedup collapses the first import to 1 of 3 priors (the single-prior test stays green, this fails) — while every archive round-trip test stays green; suite **4216 passed**; nineteenth forward-hardening pivot cell, the archive-ingest settle axis | cap 9 |
| H387 | MCP `get_link_graph` whole-payload determinism guard (test-only) — two `tests/test_mcp.py` tests (`test_get_link_graph_is_byte_identical_across_two_same_process_reads` + `…_is_deterministic_across_hash_seeds`, the fourth MCP-surface determinism twin after H381 `get_library_health`/H382 `get_context_bundle`/H383 `run_maintenance`) over a new `_seed_link_graph_determinism_mix` (an x→arxiv→crossref link chain + a mutually-linked byte-identical web pair = five connected nodes, four edges, a four-key `by_source` map, the arxiv preprint left `drifted`) pin that the agent-facing whole-link-structure read (`get_link_graph` folds `build_graph`→`graph_payload`, a code path distinct from the `run_doctor` audit the JSON twins wrap) is a *reproducible artifact*: two same-process `get_link_graph()` reads serialize byte-identical, AND two subprocesses under different `PYTHONHASHSEED`s emit identical output. Decisive: serialize/compare the *whole* MCP payload (nodes + edges + stats + envelope), include the cross-seed pair (the set-iteration leak a same-process pass misses), and ride the H186 shape contract (`get_link_graph in _TOOLS`, the class-B `stats.custody.by_source` twin). Sabotage: folding the node list over a `set` in `graph.to_payload` reorders the nodes across the two seeds → fails *only* the cross-seed byte-identity while the same-process read + the per-tool `get_link_graph` shape tests stay green; suite **4218 passed**; twentieth forward-hardening pivot cell, the agent-facing structural-read reproducibility axis | cap 3/10 |
| H388 | Whole MCP read-surface determinism contract (test-only) — three `tests/test_mcp.py` tests + `_seed_read_surface_determinism_mix`/`_prepare_read_surface_library`/`_READ_SURFACE_CALLS` that *retire the per-tool MCP determinism-twin treadmill* (the shipped H381/H382/H383/H387 cells and the queued H389/H391/H392/H393, now pruned): one guard over *every* registered read tool (`_MCP_READ_TOOLS`) at once. (1) `test_mcp_read_surface_calls_cover_exactly_the_registered_read_tools` — the **completeness keystone**: the determinism call list ≡ `_MCP_READ_TOOLS`, so a *new* read tool fails until given a call (the M2/H364 registry-completeness contract on the determinism axis — the mechanism that ends the treadmill). (2) `…_is_byte_identical_across_two_same_process_reads` — two whole-surface reads of one unchanged library byte-identical, over a wide fixture (4 sources, 3 DOI works incl. an all-reference at-risk one, a ≥3-node/≥2-edge graph, a rendered Database concept + efficient tag each ≥3 members, a content pair, a drifted+conflicted item, a tampered archived prior, a 2-pass maintenance trend → every order-sensitive fold non-vacuous). (3) `…_is_deterministic_across_hash_seeds` — one cross-`PYTHONHASHSEED` subprocess pair calls *every* read tool from the one source-of-truth call list and compares the whole concatenated output, so a `set` leaking into *any* read fold is caught. Teeth: `…_determinism_guard_has_teeth` injects a `list(set(...))` leak into `get_works` — invisible to two reads under one seed, divergent across seeds 0/1 (proving the cross-seed dimension is load-bearing); suite **4222 passed**; the contract-consolidation pivot that closed the MCP determinism treadmill | cap 1/2 |
| H390 | `export archive` whole-library JSONL determinism + round-trip byte-identity guard (test-only) — one `tests/test_roundtrip.py` test (`test_export_archive_is_a_reproducible_artifact`, the *third leg of the transport-determinism triptych* after H379 `export items` / H384 `export events`, on the **archive** transport) over `_build_library(_seed_items())` + a `_seed_archive` fixture that supersedes two held items via the production `adopt_incoming` path (item 0 *twice* — a two-link chain of distinct `prior_hash`/`archived_at`, item 2 once → three `item_archive` rows across two items, so both fold orders [within-id chain + across-id] are non-vacuous) pins that `dump_archive_export` — the recovery-backup root both `export archive` and the bundle's `--with-archive` block emit (H280), a *distinct code path* from H379/H384's siblings and from H385's per-item `archive show` read — is a *reproducible artifact*: two same-library `export archive` are **byte-identical** whole-file, AND a real `export archive` → full restore (`import items` + `import archive`) into a fresh `SCROLLS_HOME` → re-`export archive` reproduces the sender's bytes (`archived_records(dst) == archived_records(src)`). Decisive: compare the *whole JSONL file* not one row, include the round-trip — H280/H285 assert the *recovered prior* not the JSONL bytes, so an unsorted `item_archive` fold or a per-row set-leak would pass those yet make two recovery backups disagree; *not* cross-seed (`archived_records` is an explicit `(archived_at, item_id, prior_hash)` ordered fold, no set — the H384/H385 same-process-two-read guidance). Sabotage: a process-global per-row counter (`_seq`) appended to each exported archive row fails *only* the same-library byte-identity (`_seq: 1..3` vs `4..6`) while every archive restore-outcome test stays green; suite **4223 passed**; twenty-third forward-hardening cell / first leg of the contract-consolidation pivot, the archive-transport reproducibility axis | cap 9 |
| H394 | CLI read-surface determinism contract (test-only) — the CLI sibling of H388's whole MCP read-surface contract and the *second* contract-consolidation cell: four `tests/test_cli_determinism.py` tests over `seed_read_surface_determinism_mix` (extracted to the shared `tests/read_surface_fixture.py`, re-imported by both H388/`test_mcp.py` and H394) that *retire the per-command CLI determinism-twin treadmill* (H375 `doctor`/H376 `context`/H377 `maintain`/H378 `bundle html`/H379 `export items` each shipped as a hand-written cell). One guard over *every* CLI JSON read command at once (the 14 reads `search`/`list`/`facets`/`works`/`graph`/`related`/`doctor`/`context`/`status`/`history`/`maintain --history --trend`/`archive list`/`archive show`/`show`). (1) `test_cli_read_surface_classifies_every_registered_command` — the **completeness keystone**: `_CLI_READ_COMMANDS` + `_CLI_WRITE_COMMANDS`/`_CLI_EXEMPT_READS` (each exempt read carrying its reason) are disjoint and cover the live argparse leaf-subcommand registry walked from `build_parser()` *exactly* (all 51), so a *new* read subcommand fails until added with a determinism call (the H364 registry-completeness mechanism on the CLI determinism axis). (2) `…_is_byte_identical_across_two_same_process_reads` — two whole-surface reads of one unchanged library byte-identical per command. (3) `…_is_deterministic_across_hash_seeds` — one cross-`PYTHONHASHSEED` subprocess pair (same shared `SCROLLS_HOME` for both seeds so `status.root` + recorded-run timestamps match by construction) drives every read from the one source-of-truth list and compares the whole `json.dumps([[key, out], …])` payload. Teeth: `…_determinism_guard_has_teeth` appends a `list(set(...))` leak to `works`' captured stdout — invisible to two reads under one seed, divergent across seeds 0/1. Notes: `maintain` is classified read via its `--history --trend` mode (the CLI home of MCP `get_maintenance_history`); `history` is folded in for parity with `get_scroll_history` (the roadmap list omitted it); `doctor` exits 0 (the fixture's tampered archive/conflict/duplicates are `at_risk`/report-only, not `issues`); no read path stamps wall-clock so no line is dropped. Test-only, no production change; suite **4227 passed**; the contract-consolidation cell that closed the CLI determinism treadmill | cap 1/2 |
| H395 | Round-trip transport contract (test-only) — the *second* contract-consolidation cell, retiring the per-transport reproducibility treadmill (H368/H379/H384/H390): six `tests/test_roundtrip.py` tests (one keystone + a 4-way parametrised round-trip + a teeth test) over one completeness-asserted invariant across *every* lossless export/import transport (`items`/`events`/`archive`/`bundle`). (1) `test_round_trip_registry_covers_every_export_import_pair` — the **completeness keystone**: `_ROUND_TRIP_TRANSPORTS` (the four lossless kinds) ∪ a named `_INTERCHANGE_EXEMPT` (`opml`/`bookmarks`, foreign-format interchange with no custody model to reproduce — listed, not skipped) partition *exactly* the bidirectional `export <kind>` ∩ `import <kind>` pairs walked from the live argparse registry (`build_parser()`), so a *new* `export X`/`import X` pair fails until classified (the `_CLI_READ_COMMANDS`/H394 mechanism on the transport axis — the mechanism that ends the treadmill). (2) `test_round_trip_transport_is_a_reproducible_artifact[items|events|archive|bundle]` — per transport: two same-library exports byte-identical (determinism leg) AND a real export→import→export into a fresh `SCROLLS_HOME` reproduces the sender's bytes (round-trip leg); each transport carries its own seed (`_seed_events_ledger`/`_seed_archive`/none), ordered restore imports (item-scoped `events`/`archive` restore `import items` first), and `materialize` flag (`doctor --fix`/`kb` only for `bundle`, whose re-export reads the tree). A new transport added to the registry is round-tripped automatically. Teeth: `test_round_trip_contract_has_teeth` monkeypatches `dump_items_export` to append a process-global `_seq` counter — the *items* determinism leg fails while `export archive`'s untouched `dump_archive_export` fold stays byte-identical and non-vacuous (the per-row-counter sabotage isolated to one transport). Test-only, no production change (every transport already deterministic + lossless; the per-transport cells stay as deeper regression guards); suite **4233 passed** | cap 4 |
| H396 | Regeneration-safety contract (test-only) — the *third* contract-consolidation cell (ADR 0102), retiring the per-page non-destructive-regeneration treadmill (the M1/H1–H3 per-page refresh-safe tests): twelve `tests/test_regeneration_safety.py` cases (one keystone + a defense-in-depth emitted-page walk + a 10-way parametrised per-kind probe) over one completeness-asserted invariant that a `@user` annotation survives a re-compile across *every* generated-artifact family — the compiled `library/` pages (`sources/*`/`categories/*`/`concepts/*`/`tags/*`/`index.md`/`graph.md`/`works.md`) and the three `agents/` instruction files. (1) `test_generated_artifact_kinds_cover_the_live_registries` — the **completeness keystone**: `_GENERATED_ARTIFACT_KINDS` ≡ the live source-of-truth registries `kb._GENERATED_DIRS` ∪ `kb._GENERATED_FILES` (the exact set `compile_kb` writes and `_reconcile_generated` cleans) ∪ `agents._TARGETS`, so a *new* generated artifact fails until given a regeneration-safety entry (the H364 registry-completeness mechanism on the regeneration axis). (2) `test_every_emitted_library_page_maps_to_a_registered_kind` — defense in depth: every `.md` a real compile *emits* under `library/` maps to a registered kind, catching a rogue writer that emits an unregistered page without touching the constants. (3) `test_artifact_kind_regeneration_is_refresh_safe[…]` — per kind over a non-vacuous two-DOI-clustered mutually-linked fixture (every family present incl. a real graph edge + 2-rep work): inject a STALE sentinel *inside* the fence and a `@user` note *outside* it (a suffix, the one position preserved across every kind incl. the header-pinned SKILL.md), regenerate, assert STALE is purged (authoritative refresh — ADR 0102's "stale content can never linger") AND the note survives byte-for-byte (raw annotation sacred). Teeth on both axes: a whole-file-overwrite `write_generated` (ignoring the fence) fails all 10 per-kind legs while the keystone stays green, and a new uncovered `_GENERATED_FILES` entry fails *only* the keystone (the no-op-writer-leaves-STALE / overwrite-writer-clobbers-note failure modes). Test-only, no production change (M1/H1–H3's `write_generated`/`splice` already implement refresh-safe regeneration); suite **4245 passed** | cap 6 |
| H397 | Surface-parity contract (test-only) — the *fourth* contract-consolidation cell, lifting the scattered per-axis/pairwise convergence guards in `test_custody_convergence.py` to one (surface × axis) matrix in `tests/test_surface_parity.py` (five tests): for *every* held item its custody axes (fidelity tier, drift posture, works membership, content-duplicate partition) read identically across the browse-and-enumerate family `search` ≡ `list` ≡ MCP `search_scrolls`/`list_scrolls` ≡ `facets`. Per-item surfaces compared item-for-item against one canonical projection off the primitives (`get_fidelity`/`drift_posture`/`work_membership`/`content_duplicate_ids`); aggregate `facets` count-for-count against the canonical tally; values compared *on the wire* (`json.dumps`, so the CLI list ≡ MCP native tuple JSON-array difference H400 anticipates is not a false desync — the matrix surfaced it on first run). Three completeness keystones: (1) `test_surface_parity_matrix_is_complete` — `_PARITY_SURFACES × _CUSTODY_AXES` covered cell-for-cell by a live assertion or a *named* exemption (per-item rows carry no content-duplicate field → rides `show`/`get_scroll` H328; `facets` has no works dimension); (2) `test_custody_axes_cover_the_browse_row_shape` — the carried axes equal exactly the custody-bearing fields of the live `item_summary`+`hit_payload` shapes minus a named non-custody set (a new custody row field fails until classified); (3) `test_parity_surfaces_classify_the_live_read_registries` — the parity surfaces partition `_CLI_READ_PATHS`/H394 ∪ `_MCP_READ_TOOLS`/H388 (imported from their contracts) so a new browse command/tool fails until declared parity-or-exempt. Sabotage proves teeth *and* isolation: monkeypatching `cli.item_summary` (the CLI `list` row builder, a distinct binding from `mcp_server.item_summary`/`hit_payload`) to claim one drifted source clean fails *only* `(list, drift)`. Wide fixture spans all 3 fidelity tiers, all 5 drift postures, a content-duplicate pair, and a 2-representation work. Test-only, no production change (the surfaces already share `item_summary`/`hit_payload`/`membership_payload`, one home); suite **4250 passed** | cap 3 |
| H398 | Completeness-honesty contract (test-only) — the *fifth* contract-consolidation cell, lifting the scattered per-surface scope-echo (G2) tests (`tests/test_cli.py`/`tests/test_search.py`/`tests/test_works.py`/`tests/test_context.py`) to one registry-driven invariant in `tests/test_completeness_contract.py` (six tests): *every* browse/audit surface (`search`/`list`/`related`/`works`/`context`/`doctor` + the MCP twins) is scope-honest and completeness-honest on two axes — (axis 1) a *scoped* read discloses a scope its other-scope read does not (so a filtered slice never reads as the whole library, the H398 fabrication), and (axis 2) an empty in-scope read is the empty form, distinguishable from a could-not-check (G1 reaffirmed in registry-driven form). Two keystones: (1) `test_completeness_matrix_is_complete` — every (surface × axis) cell is a live probe or a *named* exemption (`_SCOPE_ECHO_EXEMPT` names the per-item ledgers `history`/`get_scroll_history` + the array-only MCP browse twins `search_scrolls`/`list_scrolls`/`get_related_scrolls` [H163]; `_NO_COULD_NOT_CHECK` names `list`/`doctor`/`list_scrolls`/`get_library_health`, which take no required input so have no could-not-check form); (2) `test_completeness_surfaces_partition_the_live_read_registries` — `_COMPLETENESS_SURFACES` ∪ the named exemptions partition `_CLI_READ_PATHS`/H394 ∪ `_MCP_READ_TOOLS`/H388 (imported from their contracts), so a *new* browse/audit surface fails until declared completeness-or-exempt (the H394 mechanism on the completeness-honesty axis). Guards: `test_every_scope_echoing_surface_discloses_its_scope` (9 live surfaces — `search`/`list`/`related`/`works`/`context`/`doctor` + MCP `get_works`/`get_context_bundle`/`get_library_health` — each scoped disclosure ≠ its other-scope read AND names its scope token) and `test_cli_every_surface_distinguishes_empty_from_not_checked` / `test_mcp_every_surface_distinguishes_empty_from_not_checked`. Sabotage proves teeth + isolation: monkeypatching `cli.works_payload` (a distinct binding from `mcp_server.works_payload`/`get_works`) to emit the whole-library scope shape regardless of the ref makes a per-ref `works` read claim whole-library completeness → fails *only* `works` (`test_dropping_a_scope_echo_fails_only_that_surface`). Wide fixture: an isolated never-verified item (genuine checked-and-empty for `related`/`works`/`history`) + two topic items in two sources (real scoped narrowing; `doctor` `by_source` spans both). Test-only, no production change (G2 shipped H6–H8, G1 in `tests/test_completeness.py`); doc tie-in in `docs/cli.md`; suite **4256 passed** | cap 7 |
| H399 | Re-import idempotency contract (test-only) — the *sixth* contract-consolidation cell, the *settle*-axis sibling of H395's round-trip contract (H395 pins export→import→export byte-stable; this pins import-twice = a whole-store no-op), retiring the scattered ingest-idempotency triptych (H374 bundle / H380 events / H386 archive) + items' `test_reimport_is_idempotent`: six `tests/test_roundtrip.py` tests (one keystone + a 4-way parametrised guard + a teeth test) over one completeness-asserted invariant that re-importing *any* lossless custody export into a library that already holds it is a whole-store no-op, across *every* `import <kind>` transport (`items`/`events`/`archive`/`bundle`). (1) `test_import_idempotency_registry_covers_every_import_subcommand` — the **completeness keystone**: `_IMPORT_TRANSPORTS` (the four lossless kinds) ∪ a named `_IMPORT_INTERCHANGE_EXEMPT` (the five foreign-format ingests `bookmarks`/`opml`/`pocket`/`google-takeout`/`fieldtheory`, each with no lossless `export <kind>` to re-import twice — listed, not skipped) partition *exactly* the live `import` subparser registry walked from `build_parser()`, so a *new* `import X` fails until classified (the `_CLI_READ_COMMANDS`/H394 mechanism on the ingest axis). (2) `test_reimport_transport_is_a_whole_store_no_op[items|events|archive|bundle]` — per transport: import its export into a fresh `SCROLLS_HOME` *twice* and pin the second pass is a no-op on **both** axes — the report (`imported == 0`/all-`skipped`) AND the raw-store row count read straight from the transport's dedup table (`merge_item`'s `INSERT OR IGNORE` → `items`; `import_events`' `_EVENT_IDENTITY` → `custody_events`; `import_archive`'s `_ARCHIVE_IDENTITY` → `item_archive`; the bundle's items axis), never the per-library autoincrement id the export never carries. A new transport added to the registry is re-imported automatically. Teeth: `test_reimport_idempotency_contract_has_teeth` monkeypatches `cli.import_archive` to duplicate `item_archive` behind a *clean* report (`imported == 0`/`skipped == 3`, store 3 → 6) — the raw-count axis catches it while the `items` transport (folding through `merge_item`, not the patched fn) stays a true no-op, proving a report-only check is blind (the both-axes H380/H386 precedent) and the leak is isolated. Test-only, no production change (every importer is already content-deduped; the per-transport cells stay as deeper regression guards); suite **4262 passed** | cap 4 |
| H400 | CLI↔MCP read-parity contract (test-only) — the *seventh* contract-consolidation cell and the *cross-transport* sibling of H397's intra-CLI surface-parity matrix, lifting the scattered per-twin convergence guards in `test_custody_convergence.py` (`test_status_custody_scalars_converge_with_doctor_nested_audit`, the `graph`/`works` object-twin convergence guards, `test_mcp_library_health_converges_with_status_and_doctor`) to one matrix in `tests/test_cli_mcp_parity.py` (four tests): for *every* MCP read tool, either its CLI twin's **custody-bearing payload** reads identically across the (CLI command, MCP tool) twin, or it is a *named* exemption. The matrix checks the four inspect + aggregate twins H397's browse-enumerate matrix omits — `get_scroll`≡`show` (per-item axes `fidelity`/`drift`/`last_checked`/`content_duplicate_ids` over every held item, the H328 content-duplicate axis), `get_link_graph`≡`graph` + `get_works`≡`works` (the aggregate `stats.custody` block + each node/representation's per-node custody axes), `get_library_health`≡`doctor` (the shared `run_doctor` custody block; `get_library_health` spreads it with `attention`/`headline` `scrolls status` adds beside it [H367/H381], stripped before the field-for-field compare); values compared *on the wire* (`json.dumps`) so the CLI-list ≡ MCP-tuple JSON-array difference is no false desync. (1) `test_cli_mcp_twin_registry_partitions_the_mcp_read_surface` — the **completeness keystone**: `_CLI_MCP_TWINS` (the four checked twins) ∪ `_BROWSE_PARITY_BY_H397` (`search_scrolls`/`list_scrolls`/`list_facets`, already H397's job) ∪ `_NON_CUSTODY_AXIS_TWIN` (the six reads with a CLI twin carrying a non-custody-axis payload: `history`/`related`/`archive list`/`archive show`/`maintain --history`/`context` [CLI≡MCP byte-identity pinned by H382]) ∪ `_MCP_ONLY` (`get_concept_page`/`get_tag_page`/`list_sources`/`list_feed_subscriptions`, no CLI JSON twin) partition `_MCP_READ_TOOLS`/H388 *exactly*, so a *new* MCP read tool fails until classified. (2) `test_every_declared_cli_twin_is_a_live_read_command` — every declared CLI twin path is a registered read in `_CLI_READ_PATHS`/H394, the "fails until *both* contracts register it" tie. (3) `test_every_cli_mcp_read_twin_agrees_on_its_custody_payload` over the shared `seed_read_surface_determinism_mix` (4 sources, 2 tiers, 3 postures, a duplicate pair, a 3-work cluster, an at-risk posture). Sabotage `test_a_single_transport_re_deriving_one_axis_fails_only_that_twin` monkeypatches `mcp_server.get_fidelity` (the binding only `get_scroll` reads through — distinct from `cli.get_fidelity` and the `graph`/`works`/`doctor` builders' own bindings) to misreport one full holding's tier → failure set is *exactly* `{get_scroll}`. Test-only, no production change (the twins share one builder, so parity holds by construction; the per-twin convergence guards stay as deeper regression guards, the H395 discipline); suite **4266 passed** | cap 3 |
| H401 | Bundle-format briefing-parity contract (test-only) — the *eighth* contract-consolidation cell and the *two-portable-forms* sibling of H400's cross-transport matrix, lifting the scattered per-line Markdown↔HTML convergence guards in `test_bundle.py` (the per-line `..._converges_with_the_markdown_form` pairs) to one matrix in `tests/test_bundle_format_parity.py` (four tests): *every* custody briefing fact a shareable bundle carries renders in **both** the Markdown `export bundle` and the `--format html` form, carrying the same fact. The eleven registered lines — scope headline, rank-strength, weakest-source attention, at-risk-work, conflicts, archive-integrity, content-duplicates, whole-library posture, refresh, per-source breakdown, and the concept-summary provenance (`--concept` render) — each fold one shared primitive per line (`build_bundle`'s `render_custody_attention` vs `build_bundle_html`'s `_attention_html`, both distilling `weakest_source`), so parity holds by construction; the matrix pins it. Facts compared after normalising Markdown emphasis/`` `code` `` against the HTML `<p>`/`<li>`/`<code>`/entity wrappers (`&lt;S&gt;` unescapes to the literal `<S>` the refresh template carries). (1) `test_briefing_line_registry_covers_every_emitter_in_both_builders` — the **completeness keystone**: `_BRIEFING_LINES`' Markdown + HTML emitter names equal *exactly* the briefing-line functions read off the two builders' ASTs (`_module_fn_calls`: every bare-name call resolving to a `bundle` module function) minus a named `_STRUCTURAL` set (scope-gather/data-fold/per-entry/custody-block/HTML-wrapper helpers), so a *new* briefing line in one form fails until registered — and registering it declares its twin emitter, whose leg fails until the other form carries it (the "forced into both forms" tie). (2) `test_every_briefing_line_renders_the_same_fact_in_both_forms` over one composite fixture (multi-source drift + unresolved conflict + corrupt archived prior + a byte-identical pair + an all-reference at-risk work + stale enrichment + a stale concept summary; every content_hash distinct save the dup pair so the `_Duplicates:_` count is exactly one group of two) lighting all eleven lines non-vacuously. Two sabotages: `_conflicts_html → []` (dropped from the HTML form) fails *only* `{conflicts}`; a `_content_duplicates_html` rendering a tampered count fails *only* `{duplicates}` (the matrix compares the fact, not mere presence). Test-only, no production change (the per-line convergence guards stay as deeper regression guards, the H395/H400 discipline); suite **4270 passed** | cap 9 |
| H402 | Reconcile-safety contract (test-only) — the *ninth* contract-consolidation cell and the *removal*-axis sibling of H396's refresh-safety contract (H396 pins a recompile whose group *still exists* refreshes the fence while sparing annotations; this pins the vanish event), lifting the scattered per-kind reconcile tests in `test_kb.py` (`test_kb_recompile_removes_stale_pages_but_keeps_user_files`, `test_kb_stale_annotated_page_is_kept_with_a_tombstone`, which proved one dir-kind — `categories` — at a time) to one matrix in `tests/test_reconcile_safety.py` (six tests) over one completeness-asserted invariant: when a compiled `library/` page's group **vanishes** (a reclassified category, a dropped concept/tag, an emptied source), `_reconcile_generated` (ADR 0102) **tombstones** an annotated stale page (generated region → `kb._STALE_BODY`, the `@user` annotation preserved byte-for-byte) and **unlinks** a plain stale page (stale pages can't linger), across *every* reconcilable dir-kind. (1) `test_reconcilable_kinds_equal_the_generated_dirs` — the **completeness keystone**: `_RECONCILE_KINDS` equals `kb._GENERATED_DIRS` *exactly* and is disjoint from `kb._GENERATED_FILES` (the always-written `index.md`/`graph.md`/`works.md` land in `compile_kb`'s `written` set, so the `if path in written` short-circuit never reconciles them), so a *new* reconcilable page family fails until given a reconcile-safety entry (the H364 mechanism on the deletion axis). (2) `test_reconcile_tombstones_annotated_and_unlinks_plain_stale_pages[sources|categories|concepts|tags]` — per dir-kind: a base item keeps the dir alive plus a keep/drop pair each owning a *unique* page on that kind's axis; `delete_item` on both makes exactly those pages vanish on recompile, exercising **both** reconcile branches in one pass (annotated keep page tombstoned + note verbatim + generated body ≡ `_STALE_BODY` + stale rollup gone; plain drop page unlinked; dir survives). Teeth: `test_tombstone_branch_has_teeth` monkeypatches `kb.has_user_content → False` so the reconcile unlinks the annotated stale page wholesale — the annotated page each leg requires tombstoned is gone (the exact failure mode the contract guards; a global helper patch fails every leg, one representative kind proves it). Test-only, no production change (M1/H1–H3's `_reconcile_generated` already tombstones; the per-kind `test_kb.py` cells stay as deeper regression guards, the H395 discipline); suite **4276 passed** | cap 6 |
| H403 | Browse-filter drill contract (test-only) — the *tenth* contract-consolidation cell and the *filter*-axis sibling of H397's read-parity matrix (H397 pins every browse surface reads the *same* per-item axis; this pins the dual — drilling by a filter returns *exactly* the rows the surface carries at that value), lifting the scattered per-filter convergence guards (`test_content_duplicate_browse_filter_converges_with_doctor_groups`, the `test_search_fidelity_filter_agrees_with_the_per_hit_tier`/`test_search_drift_filter_agrees_with_the_per_hit_posture` drills, `test_context_fidelity_filter_partitions_the_unfiltered_holdings`) to one matrix in `tests/test_browse_filter_drill.py` (four tests) over one completeness-asserted invariant: every custody/rank browse filter (`--fidelity`/`--drift`/`--strength`/`--content-duplicate`) on `search`/`list` (+ the MCP `search_scrolls`/`list_scrolls` twins) selects *exactly* `{id : the unfiltered surface's row matches the filter at this value}`, every returned row's own axis consistent with the filter (no off-axis leak). The `_BrowseFilter` registry declares each filter's drill *kind* — `value` (exact equality, fidelity/drift), `band` (the at-or-above strength prefix), `flag` (the content-identity predicate, read off the canonical `content_duplicate_ids` the browse row does not carry). (1) `test_browse_filter_registry_partitions_the_search_list_flags` — the **completeness keystone**: for each of `search`/`list`, the declared drill flags ∪ a *named* `_NON_DRILL_FLAGS` set (the plain facets, `--limit`/`--stats`, and the `--stale-*` filters whose drill is pinned by their own H85/H185/H189 act↔read guards) partition that subparser's *live* argparse optionals exactly, so a *new* filter fails until classified (the H394 mechanism on the filter axis); `test_browse_filter_registry_partitions_the_mcp_twin_signatures` holds the same partition on the twins' `inspect.signature` kwargs. (2) `test_every_browse_filter_drills_exactly_the_unfiltered_rows` over one wide dedicated fixture (all three fidelity tiers, all five drift postures, a content-duplicate pair, and a rare "beacon" token landing in title/summary/body so `search beacon` returns one hit per strength band — H397's mix has no strength diversity, so a purpose-built `_seed_browse_filter_mix` was written). Sabotage `test_a_filter_admitting_one_off_axis_row_fails_only_that_filter` monkeypatches `custody.items_in_posture` (the `list_items(drift=)` selector — distinct from the row's own `drift_posture` field and the search surfaces' `scrolls_drift` SQL UDF) to admit the genuinely *drifted* `web:drift` into the `verified` selection → failure set is *exactly* `{(list, drift), (list_scrolls, drift)}` (the two list legs that share the selector; the search legs and every other filter stay green). Test-only, no production change (the filters already drill correctly; the per-filter convergence guards stay as deeper regression guards, the H395 discipline); suite **4280 passed** | cap 3 |
| H404 | Compiled-page custody-honesty contract (test-only) — the *eleventh* contract-consolidation cell and the *compiled-surface* sibling of H398 (H398 pins G1 anti-fabrication on the JSON/MCP reads; this pins the same honest-absence/honest-presence invariant on the human-readable compiled `library/` pages), lifting H190's two `index.md`-only honest-absence tests in `test_completeness.py` (`test_compiled_pages_omit_action_lines_with_no_basis`/`test_compiled_refresh_line_is_per_axis_honest`) to one matrix in `tests/test_compiled_page_custody_honesty.py` (four tests) over *every* custody-bearing compiled page kind — the four group-page dirs (`sources`/`categories`/`concepts`/`tags`, `kb._write_page`) plus the whole-library `index.md` (`kb._write_index`): each renders its `_Custody:` headline always, a `_By source:` split iff ≥2 sources, an `_Attention:` drift pointer iff its scope carries a cross-source loss (`weakest_source` non-None), and a `_Refresh:` pointer iff its scope carries stale classification/summary debt — per-axis (the classifications clause renders, the summaries clause stays absent with no stored summary, H190's per-axis honesty). (1) `test_compiled_page_registry_partitions_the_generated_tree` — the **completeness keystone**: a *hardcoded* `_CUSTODY_BEARING_DIRS` asserted ≡ `kb._GENERATED_DIRS` (so a *new* dir breaks it) and `{index.md}` ∪ a *named* `_NO_CUSTODY_HEADLINE` set partitioning `kb._GENERATED_FILES` exactly — `graph.md` (pure link-graph rollup, no headline; `test_kb.py` pins `_Custody:` absent) and `works.md` (rides the *works* axis with a per-work `_Custody:` marker per section, H270) are named exemptions, **not** custody-headline pages (the roadmap's H404 parenthetical wrongly called `graph.md` custody-bearing). (2) `test_a_clean_library_compiles_no_fabricated_action_pointers` (every page: headline yes, no `_Attention:`/`_Refresh:`, tied to `doctor`'s empty `attention`/`enrichment`/`summaries` bases) and `test_every_compiled_page_renders_its_action_pointers_honestly` over a drift/stale-debt fixture — `index.md` tied to the JSON `status`/`doctor` bases (the independent H190 anchor); group pages to their own scope folds with a `_Custody: N` headline-count cross-check (validates the member model against the live page); each axis non-vacuous (present on ≥1 page, absent on ≥1) and the covered kinds asserted ≡ the registry (no silent `_group_pages` skip). Sabotage `test_dropping_the_by_source_split_fails_only_the_multi_source_kinds` monkeypatches `kb.render_custody_by_source → []` → failure set is *exactly* `{index.md, categories, concepts, tags}` (the kinds with a multi-source page), never single-source-only `sources` (whose pages have no split to drop — honest-absence is a genuine no-op). Test-only, no production change (the compiler already renders honestly; H190's per-page tests stay as deeper regression guards, the H395 discipline); suite **4284 passed** | cap 2 |
| H405 | Lossless-importer conflict/adoption parity contract (test-only) — the *twelfth* contract-consolidation cell and the *conflict*-axis sibling of H400's CLI↔MCP read-parity matrix (H400 pins clean-read parity; this pins divergent-write parity), lifting the scattered per-importer conflict/adopt tests (H272–H283 in `test_cli.py`/`test_bundle.py`) to one matrix in `tests/test_import_conflict_parity.py` (six tests) over one completeness-asserted invariant: the two Scrolls-native lossless importers (`import items`/`import bundle`, the pair routing `content_hash`-bearing rows through `_merge_items`) detect and record a content conflict **identically**, and adopt one **identically** under `--accept-incoming`. (1) `test_conflict_importer_registry_partitions_every_import_subcommand` — the **completeness keystone**: `_CONFLICT_IMPORTERS` (`{items, bundle}`) ∪ a named `_NO_CONFLICT_IMPORTS` (`events`/`archive`, custody-store appends with no held-row content to diverge) ∪ the H399 `_IMPORT_INTERCHANGE_EXEMPT` (the five foreign-format ingests, cross-imported from `test_roundtrip.py`) partition the live `import` subparser registry *exactly*, so a *new* lossless importer fails until classified (the H394/H399 mechanism on the conflict axis). (2) `test_a_divergent_capture_is_kept_and_recorded[items|bundle]` — keep-held (the default): the held id is surfaced as a kept `conflict` (disposition `{imported:0, skipped:1, conflict:1, conflicts:[id], adopted:[]}`), the held copy preserved byte-for-byte (never overwritten, custody §2.4), and a durable `conflict` event (held→incoming hash) on the append-only `item_events` timeline — the **decisive both-axes choice** (the durable ledger, not just the transient report). (3) `test_accept_incoming_adopts_and_archives[items|bundle]` — adopt: `--accept-incoming` replaces the held row with the incoming capture (disposition `adopted:[id]`), records a durable `superseded` event (archived prior → adopted incoming), the prior recoverable byte-for-byte via `archive show`. Both legs pin the same canonical disposition, so the importers agree by construction (the bundle's nested `events`/`archive` report blocks normalised away — the items-axis fields are top-level on both). Teeth: `test_conflict_parity_contract_has_teeth` monkeypatches `cli._cmd_import_items` (the binding only the items importer dispatches through; `_cmd_import_bundle` never calls it) with an overwrite-on-conflict importer (rewrites the held row, reports a clean import) — the items keep-held leg fails while the bundle leg, routing through the unpatched `_cmd_import_bundle` → `_merge_items`, stays green, isolating the leak to one importer (the H400 binding-isolation precedent). Test-only, no production change (the importers already share `_merge_items`, so parity holds by construction; the H272–H283 per-importer tests stay as deeper regression guards, the H395 discipline); suite **4290 passed** | cap 4 |
| H406 | CLI↔MCP write-act parity contract (test-only) — the *thirteenth* contract-consolidation cell and the *write-side* sibling of H400's CLI↔MCP read-parity matrix (H400 pins clean-read parity; this pins write-effect parity), lifting the scattered per-tool effect tests (`verify_scroll` drift, `compile_library` payload, `run_maintenance`≡`maintain` convergence, the feed-op tests) to one matrix in `tests/test_cli_mcp_write_parity.py` (four tests) over one completeness-asserted invariant: *every* custody-safe MCP write tool produces the **same durable custody effect** as its CLI act twin over two fresh copies of the shared fixture. The six offline twins — `verify_scroll`≡`verify` (the same typed `custody_events` row appended, read off the durable `item_events` ledger not the transient return, behind the patched `live_recapture` seam in both module namespaces), `run_maintenance`≡`maintain --no-recheck` (the same report disposition + recorded snapshot/trend `read_log`, the H383 offline-by-default `assemble_report`/`skipped_recheck_report` convergence), `compile_library`≡`kb` (the same `{relpath → sha256}` whole-tree hash of compiled `library/`, the H363 deterministic-compile axis), and `follow_feed`/`unfollow_feed`/`sync_feeds`≡`follow`/`unfollow`/`sync` (the same `list_subscriptions` roster — plus, for sync, the same detected items — behind the patched `feeds._get_text`/`feeds._get_conditional` defaults both transports read). (1) `test_write_twin_registry_partitions_the_mcp_write_surface` — the **completeness keystone**: `_WRITE_TWINS` (the six effect-checked twins) ∪ a named `_NETWORK_WRITE_EXEMPT` (`ingest_url`, the one live-capture write pinned by its own fake-API tests, not an offline effect twin) partition `_MCP_SAFE_WRITE_TOOLS`/H364 *exactly*, so a *new* MCP write tool fails until it declares a CLI act twin (or the exemption). (2) `test_every_declared_cli_act_twin_is_a_registered_command` — each twin's CLI path is registered: the five pure writes in `_CLI_WRITE_COMMANDS`/H394, the dual-mode `maintain` in `_CLI_READ_PATHS` (H394 read-classified it for its `--history` read; driven here in its `--no-recheck` write-pass mode) — the "fails until *both* contracts register it" tie on the write axis. (3) `test_every_write_twin_agrees_on_its_custody_effect` runs each twin over two fresh sub-homes (one per transport, never sharing state), comparing the durable effect *on the wire* with wall-clock timestamps normalised (`checked_at`/`recorded_at`/`added_at`/`last_synced_at` legitimately differ between two acts; the event verb/hashes, snapshot scalars, compiled bytes, roster membership are the content that must agree). Sabotage `test_an_mcp_write_recording_a_different_verb_fails_only_that_twin` monkeypatches `mcp_server.verify_item` (the binding only `verify_scroll` records through — distinct from `cli.verify_item`) to record a `rotted` verb where the CLI records `drifted` → failure set is *exactly* `{verify_scroll}`, the maintenance/compile/feed legs (flowing through `compile_kb`/`assemble_report`/`feeds`) untouched. Test-only, no production change (the write tools converge by construction — shared `verify_item`/`compile_kb`/`assemble_report`/`feeds`; the per-tool effect tests stay as deeper regression guards, the H395 discipline); suite **4294 passed** | cap 4 |

---

## 3-day plan — 2026-06-27 → 2026-06-30

Forward-looking (re-derived 2026-06-27, the once-per-24h full re-derivation, at the
contract-consolidation mid-theme boundary — the prior 2026-06-25→06-28 day-by-day narrative was
pruned, its per-slice detail living in git + the Shipped ledger per maintenance-rule §4). Each day
ends on a committed, tested, clean stopping point; slips roll forward. MVP M1–M5, every post-MVP
custody theme, the **content-identity / near-duplicate custody theme** (H325–H362), and the
**custody-posture theme** (H369–H373) are closed. The active work is the **contract-consolidation
theme** — each cell replaces a *family* of per-surface tests with one completeness-asserted invariant
that auto-covers new surfaces (the H388 pattern). Eleven cells have shipped (H388 MCP-determinism, H394
CLI-determinism, H395 round-trip, H396 regeneration-safety, H397 surface-parity, H398
completeness-honesty, H399 re-import-idempotency, H400 CLI↔MCP read-parity, H401 bundle-format
briefing-parity, H402 reconcile-safety, H403 browse-filter drill, H404 compiled-page custody-honesty);
the forward queue is H405–H411. No new adapters.

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
- **Day 3 (2026-06-29 → 2026-06-30): H405** — the lossless-importer conflict/adoption parity contract
  (`import items`/`import bundle` detect+record a content conflict identically and adopt identically under
  `--accept-incoming`, keyed to a `_CONFLICT_IMPORTERS` registry). → cap 4. Then **H406** (MCP↔CLI write-act
  parity) if it lands fast. Next once-per-24h full re-derivation **due 2026-06-28**.

---

## Week plan (more tentative) — through 2026-07-02

- **Closed this past week:** the **content-identity / near-duplicate custody theme**
  (H325–H362) — a genuinely new custody shape (byte-identical holdings under different ids):
  the `doctor` report, the `related` content edge, the per-item/work/browse/graph/aggregate
  surfaces, the `_Duplicates:_` readable line + trend, the `duplicate_prunes` suggested
  guidance, the import-time notice, and the full convergence + dogfood guard set across
  read/render/compile/MCP/import — report-only, never an auto-merge.
- **Closed — the custody-posture theme** (H369–H373): `doctor`'s `custody.posture` distils the
  seven custody blocks into one whole-library verdict (custody-vision §3.1, ADR 0107) — read →
  render → travel → trend → converge, all shipped.
- **Active — the contract-consolidation theme.** Each cell replaces a *family* of per-surface
  tests with one completeness-asserted invariant that auto-covers new surfaces (the H388 pattern).
  **Shipped:** H388 (whole-MCP determinism), H394 (CLI determinism), H395 (round-trip transport),
  H396 (regeneration-safety, ADR 0102), H397 (surface-parity), H398 (completeness-honesty, M2),
  H399 (re-import idempotency), H400 (CLI↔MCP read-parity), **H401 (bundle-format briefing-parity)**.
  **Forward queue:** H402 (reconcile-safety, the removal-axis sibling of H396), H403
  (browse-filter drill), H404 (compiled-page custody-honesty, M2), H405 (lossless-importer
  conflict/adoption parity), H406 (MCP↔CLI write-act parity, the write-side sibling of H400), H407
  (rank-explainability convergence). The once-per-24h full re-derivation was **performed 2026-06-27**;
  the next is **due 2026-06-28**.
- The **budget/tier convergence guard cells H244–H249** remain valid regression guards but
  are explicitly **de-prioritized** — take a capability or forward-hardening slice first.
- A **new source adapter** is out unless it introduces a genuinely new custody *shape* (a new
  fidelity boundary, identity rule, or thread/canonical structure — custody-vision §2.7);
  adapter-churn for its own sake loses to hardening.
- Explicitly **not** this week: new adapters (absent a new custody shape), productivity
  surfaces, paid research integrations.

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
