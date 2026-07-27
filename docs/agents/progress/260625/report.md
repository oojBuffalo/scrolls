# Progress Report — 2026-06-25

**Date:** 2026-06-25
**Branch:** `work/scrolls-dev` (agent trunk) — HEAD `a7af87e` (H343) at check-in time
**Suite:** ~4043 tests passing at check-in time (per the autonomous-machine session notes)

*Reconstructed: 2026-07-26 — this check-in happened (its trace is the
2026-06-25 status-snapshot re-compaction, commit `34a37b1`) but never got a
durable artifact under `docs/agents/progress/`. The status-snapshot section
below was moved here in full from `docs/agents/autonomous-roadmap.md`, which
no longer carries it; location references were adjusted for the move,
content otherwise verbatim. Caveat: the snapshot accreted in place — the
overrunning worker kept appending "(this run)" updates after 2026-06-25, so
its later paragraphs describe work through H425 (2026-07-05), not the frozen
check-in state. The frozen state was: HEAD `a7af87e`/H343, ~4043 tests, the
content-identity surface-closure tail (H344–H348) open, the hourly worker
live, verification local-only (no CI on GitHub). The direction set at this
check-in is `plans.md` alongside; see `../260722/` for how development
actually unfolded.*

## Status snapshot — 2026-06-25 (moved from the roadmap)

This snapshot is **current-state only**, never a per-slice changelog — the per-slice
detail (subject, design, diff) lives in git (`git log --oneline | grep '(H<NN>)'`) and
the one-line Shipped ledger in `docs/agents/autonomous-roadmap.md` (its maintenance-rule §4: *git is the changelog*). This
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
  identical holdings under different ids, vision §2.7): the
  `doctor.custody.content_duplicates` report, the `related` "identical content" edge,
  per-item/work/browse/graph/aggregate surfaces, the `_Duplicates:_` readable line + trend,
  the `duplicate_prunes` suggested guidance, and the import-time notice — report-only, never
  an auto-merge (raw is sacred); pinned across every read/render/compile/MCP/import surface
  by convergence + dogfood guards (H325–H362).

**Closed theme — custody posture** (vision §3.1, ADR 0107): `doctor`'s
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
"identical semantics across surfaces" contract (vision §2.6) on the boot-vs-audit axis, beside
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
buffer's active **contract-consolidation** theme has since shipped **H394–H419** (CLI read-surface
determinism, round-trip transport, regeneration-safety, surface-parity, completeness-honesty, re-import
idempotency, CLI↔MCP read-parity, bundle-format parity, reconcile-safety, browse-filter drill, compiled-page
custody-honesty, lossless-importer conflict/adoption parity, CLI↔MCP write-act parity, rank-explainability
convergence, raw-immutability act-surface, append-only custody-ledger, stale-set drill, facet-aggregate
drill, enrichment-provenance convergence, recency-`last_checked` convergence, could-not-check error-parity,
bundle-briefing ↔ live-audit convergence, preview ↔ live-run parity, facet scope-composition convergence,
audit-aggregate ↔ browse-drill convergence, and the compiled group-page classification marker [H419, the
one *production* cell — the H412-deferred slice]); the roadmap's live queue is the authoritative lead, now
closed through **H425**; the next step is the post-theme assessment/recommendation gate.
