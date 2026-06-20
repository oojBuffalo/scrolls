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

## Status snapshot — 2026-06-20

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
**work** slices; the next checkpoint (H218) follows.

The new horizon, re-derived at this H207 checkpoint, is **budget/tier custody
honesty** (cap 2/7/10): the `scrolls context` budgeted boot sequence currently
hides *all* custody signal at its leanest `index` tier (the headline/per-source
map are gated to `connected`+, `src/scrolls/context.py:203`), so an agent reading
an `index` catalog can't tell whether the top matches are full-fidelity,
reference-only, or anything between — a gap against vision principle 3 (*fidelity
and provenance travel with every result*). The fix is honest *and* ledger-free:
**fidelity is a holdings fact** (`items.fidelity_tier`, computed from item fields),
so it can ride the leanest tier; **drift is a ledger claim**, so it honestly stays
gated to `connected`+ (rendering "unverified" at `index`, where no ledger was read,
would be the exact M2 anti-fabrication violation we forbid). **H212 shipped the
production `_Fidelity:_` line and H213 (this run) pinned its cross-tier convergence
tie** — the `index` line ≡ the `connected`/`full` `_Custody:_` headline ≡ `doctor`'s
`custody.tiers`, mutation-checked, folded into `tests/test_custody_convergence.py`.
**H214 pinned the MCP twin** — `get_context(budget="index")` carries the
same `_Fidelity:_` line, byte-identical to the CLI. **H215 folded the
`index` line into the M2 completeness invariant** (names its holdings, never a drift
verdict it didn't read), closing the sub-theme CLI-side; **H219 (this run) finished it
over MCP** (the same completeness fold on `get_context_bundle`, beside the CLI test) —
so the *drift-withholding* honesty now holds on both surfaces. H216–H217 (+ the
appended H220–H223) deepen portable-bundle round-trip custody and the leanest tier's
scope-honesty under truncation and facet scope.

| Slot | Intended slice | Maps to |
| --- | --- | --- |
| H222 | **MCP `get_context(budget="index")` `(of N)` scope-honesty under truncation — the MCP twin of H221.** Just as H219 is the MCP completeness twin of H215, the leanest tier's holdings-scope honesty under a cap must hold on the read an agent actually reaches over MCP: `get_context_bundle(query, budget="index", limit=k)` over a >`limit` mixed-fidelity scope carries `_Fidelity: … (of k)._` whose `(of k)` equals the `_Coverage:` line's `returned`, never the library-wide `matched` — and is *byte-identical to the CLI*'s `context --budget index --limit k` (the agent-facing bundle and the CLI never diverge on the leanest tier's holdings scope, just as H214 pinned for the untruncated line). Test only (`tests/test_mcp.py`, beside the H214 twin). Precondition: H214 (the MCP `_Fidelity:_` line, shipped), H221 (the CLI truncation honesty). | → cap 2, cap 10 |
| H223 | **The `index` `_Fidelity:_` holdings honor the active facet scope.** The leanest tier's holdings line counts the post-facet `items` (the representations `build_context` keeps after the `source`/`category`/`stage`/`tag`/`concept` filter), so a scoped `context --budget index --source <S>` must name only `<S>`'s fidelity tiers and `(of k)` scope — never the library-wide holdings of a multi-source library. Pin it: over a mixed-fidelity, multi-source scope, `--source <S>` carries a `_Fidelity:_` line whose tier counts + `(of k)` equal the scoped subset, while the unscoped run names the whole-library holdings — the *facet*-axis sibling of H221's *truncation*-axis `(of N)` scope-honesty (the holdings fact never over-claims beyond the agent's chosen scope). Test only (`tests/test_context.py`). Precondition: H212; `context` facet scoping (shipped). | → cap 7, cap 10 |
| H225 | **`import bundle` names *which* items the orphan events dangle on — the diagnosable half of H217.** H217 surfaces an orphan *count* (`events.orphaned`) and a generic stderr warning, which tells an agent a bundle is corrupt but not *what to fix*. Make the loss actionable: include the distinct orphan `item_id`s (sorted, deduped, bounded) in the stderr warning so "2 orphan events" becomes "2 orphan events reference `arxiv:x`, `web:ghost`" — the operator can see the bundle was spliced/truncated and which rows the items block is missing. Implementation path: `partition_resolvable_events` already groups by `item_id`, so collect the distinct orphan ids from the orphan list and render them in the warning (cap the list with an "(+N more)" tail like the other bounded readable surfaces). Test (`tests/test_bundle.py`): a spliced bundle with orphan events naming two missing items warns with both ids; the count stays the event count, the id list the distinct-item count. Precondition: H217 (the orphan partition + count, shipped). | → cap 9, cap 7 |
| H224 | **The whole-library JSONL backup is tier-lossless too — the H216 sibling on the other portable surface.** H216 pinned that the scoped *bundle* round-trip preserves each `get_fidelity` tier; the whole-library `export items` → `import items` → `doctor --fix` backup (ADR 0082 — the migrate/merge/restore path) is the *other* portable surface and is only ever exercised all-`full` (`tests/test_roundtrip.py::_seed_items`; `test_rebuilt_library_passes_its_own_custody_audit` asserts `custody.tiers["full"] == len(seed)`). Pin it: a library whose items span all three fidelity tiers rebuilds via the documented backup commands with `doctor`'s `custody.tiers` equal to the source spread (≥2 tiers, non-vacuous), no rebuild-side downgrade — `import items` carries every content field (ADR 0082) and `doctor --fix` rebuilds only the derived artifacts, never the row fields fidelity reads from. So portability is *tier-lossless* on **both** the scoped-bundle (H216) and whole-library-backup paths. Test only (`tests/test_roundtrip.py`). Precondition: the lossless backup round-trip (ADR 0082, shipped); `get_fidelity` (shipped). | → cap 9, cap 4 |
| H227 | **MCP `get_context(budget="index", source=<S>)` facet-scope `(of N)` honesty — the MCP twin of H223.** Just as H222 is the MCP twin of H221's *truncation*-axis scope-honesty, the leanest tier's holdings must name only the agent's *facet* scope on the read reached over MCP: `get_context_bundle(query, budget="index", source=<S>)` over a mixed-fidelity, multi-source library carries a `_Fidelity:_` line whose tier counts + `(of k)` equal the scoped `<S>` subset — never the library-wide holdings — and is *byte-identical to the CLI*'s `context --budget index --source <S>` (the agent-facing bundle and the CLI never diverge on the leanest tier's facet-scoped holdings, just as H214/H222 pin for the untruncated/truncated line). Test only (`tests/test_mcp.py`, beside the H214/H222 twins). Implementation path: `get_context_bundle` already forwards `source`/facets straight to `build_context` (`src/scrolls/mcp_server.py:491`), so the honesty is shared-by-construction; the slice pins it. Precondition: H214 (the MCP `_Fidelity:_` line, shipped), H223 (the CLI facet honesty). | → cap 2, cap 10 |
| H226 | **`import bundle --dry-run` names *which* scrolls are new vs. already held — the reviewable half of H220.** H220 surfaces import *counts* (`imported: 2, skipped: 1`), which tells an agent how much a merge would change but not *what*. Make the preview reviewable: include the would-be-imported item ids and the already-held (skipped) ids (each sorted + deduped) in the dry-run JSON, so "2 new" becomes `"new": ["arxiv:x", "web:y"]` — the operator can confirm the bundle adds what they expect before committing. Implementation path: `_preview_import_bundle` already partitions items by `get_item` existence (and tracks within-bundle dups in `seen_item_ids`); collect the two id lists there and render them under a `new`/`held` key, present only under `--dry-run` (the real import's terse counts stay unchanged). Test (`tests/test_bundle.py`): a mixed bundle (one new, one held) previews with the new id in `new` and the held id in `held`, each list length equal to its count. Precondition: H220 (the dry-run preview, **shipped this run**). | → cap 9, cap 7 |
| H218 | **Buffer refresh checkpoint** (maintenance rule). Mark shipped slices into the ledger, prune overtaken slices, keep ≥6 un-started work slots, and re-derive the 3-day/week plans with absolute dates. Re-confirm the week plan still maps to `docs/product/mvp.md`. Bi-temporal drift framing stays deferred unless an agent workflow shows the event record insufficient. | maintenance |

The next lead slot is **H222** (the MCP twin of H221's `(of N)`
scope-honesty under truncation), now that **H221 shipped this run** — the `index`
`_Fidelity:_` line's `(of N)` scope is honest under truncation: over a >`--limit`
mixed-fidelity scope, `context --budget index --limit k` carries `_Fidelity: …
(of k)._` whose `(of k)` equals the `_Coverage: the top k of N_` line's `returned`
(never the library-wide `matched`), and whose tier counts sum to that kept set —
the fidelity holdings never over-claim scope the bundle didn't see (test-only,
`tests/test_context.py`; the production line already counts `len(items)`, the kept
post-cap representations, so the honesty is correct-by-construction and the slice
pins it). H222 is its MCP twin, H223 is the *facet*-axis sibling of that truncation
honesty, H227 (appended this run) is *its* MCP twin, H224 is the whole-library-backup
sibling of H216 — *tier-lossless* on the `export items` → `import items` path too —
H225 makes H217's orphan loss *diagnosable* by naming which items the orphan events
dangle on, and H226 makes H220's preview *reviewable* by naming which scrolls are new
vs. already held. Per-slice provenance for every *shipped* slot lives in git
(`git log --oneline | grep '(H<NN>)'`); the **Shipped ledger** below is the one-line
in-file index (maintenance-rule §4: *git is the changelog*).

**Buffer-health note (2026-06-20, H207 checkpoint + H212/H213).** The earlier
H207-checkpoint run shipped **H210**
(the CLI refresh-debt *act* dogfood — read the `context` `_Refresh:_` pointer → run the
scoped `classify --stale --source <S>` / `kb --stale --source <S>` it names → the named
axis/source clears while the untouched axis persists; the refresh-axis twin of H206's
drift-act triage), which **closed the per-source custody convergence theme**: every read
*and* act surface, on both the drift and enrichment/summary axes, over both the CLI and
MCP, now ties to the `doctor` audit, and the self-healing dogfood is pinned across both
surfaces and both act axes (H204/H206/H210). With that theme exhausted, the H207
checkpoint **opened a fresh horizon** — *budget/tier custody honesty* — backed by a
verified gap (the `index` tier hid fidelity, `context.py:203`) and vision principle 3,
and that run also **shipped its lead slice H212** (the `index`-budget `_Fidelity:_`
holdings line — fidelity travels even at the leanest tier, drift honestly does not).

**This run shipped H213 and H214** — the cross-tier *and* cross-surface fidelity
convergence ties for the H212 line. **H213**: the `index` `_Fidelity:_` counts ≡ the
`connected`/`full` `_Custody:_` headline's `fidelity` section ≡ `doctor`'s
`custody.tiers` over one mixed-fidelity scope (full 2, partial 1, reference 1; ≥2
tiers, non-vacuous), mutation-checked (drop a body → the tier shifts `full`→`partial`
on every surface in lockstep), folded into `tests/test_custody_convergence.py`.
**H214**: the MCP twin — `get_context(budget="index")` carries the same line,
byte-identical to the CLI, and honestly omits the drift verdict (no ledger read);
sabotage-verified non-vacuous in `tests/test_mcp.py`. Shipping two slices dropped the
queue, so per maintenance-rule §1 that run **kept it at ~6** by appending three
concrete, PRD-mapped slices (§5: no invented work) — **H219** (the MCP completeness
twin of H215), **H220** (an `import bundle --dry-run` preview built on H217's
orphan-event accounting), and **H221** (the leanest tier's `(of N)` scope-honesty
under truncation).

**This run shipped H219** — the MCP twin of the H215 CLI completeness fold
(`tests/test_completeness.py`,
`test_mcp_index_budget_names_fidelity_holdings_but_no_drift_verdict`), placed beside
it so the M2 anti-fabrication contract is pinned on the read an agent actually reaches
over MCP. `get_context_bundle(query, budget="index")` names its `_Fidelity: full N
(of K)._` holdings (a ledger-free fact; fidelity travels, vision principle 3) and
carries no `_Custody:`/drift token, while the *same* query at `connected`+ — over a
**recorded** `drifted` verdict — does carry the `_Custody:_` headline's `drift drifted
1` section, so the `index` silence is a genuine withholding, not an empty scope. Where
H214 already pinned the MCP fidelity *line* and its CLI byte-identity, H219 adds the
*completeness* framing: the honest absence is proven against a verdict the deeper tiers
surface. Sabotage-verified non-vacuous (flipping the `index`-tier ledger gate so the
`_Custody:_` headline leaks suppresses the dedicated `_Fidelity:_` line, failing the
test). With H215 (CLI) and H219 (MCP) both shipped, the budget/tier-honesty
*drift-withholding* contract holds on both surfaces. Shipping one slice dropped the
work queue to 5, so per maintenance-rule §1 this run **restored it to ~6** by appending
**H223** (the *facet*-axis sibling of H221's *truncation*-axis `(of N)` scope-honesty —
the `index` fidelity holdings name only the agent's scoped subset, never the
library-wide tiers). The queue now sits at **6** un-started work slots (H216–H217 +
H220–H223) + the H218 checkpoint, which re-derives. The full §2 refresh already ran at
today's H207 checkpoint, so this was the incremental §1 update.

**This run shipped H216** — the mixed-fidelity bundle round-trip invariant, opening
the *portable-bundle round-trip depth* horizon (`tests/test_bundle.py`,
`test_mixed_fidelity_bundle_parse_preserves_each_tier` +
`test_mixed_fidelity_bundle_round_trips_across_a_fresh_library`). The other
round-trip ties only ever exercise an all-`full` fixture, so the `partial`/`reference`
tiers were never proven portable end-to-end. The new tests build a scope spanning all
three tiers (a `full` body, an extracted-but-unhashed `partial`, and a body-less
`reference` pointer that rides its query term in the title), `export bundle` it, and
re-import into a fresh library — asserting each item's `get_fidelity` tier is identical
across the boundary (exact-equality, so it catches a downgrade *or* a spurious
promotion). Sabotage-verified non-vacuous: dropping the body in `item_from_dict`
falls `full`→`partial` and `partial`→`reference` and both tests fail. The work is
*test-only* — the round-trip is lossless by construction (`item_to_dict`/`item_from_dict`
carry every field; `insert_item` writes every column), so H216 pins that portability is
*tier-lossless*, not just full-lossless (vision principle 3 — fidelity travels with every
result). The fixture also surfaced a correctness fact now noted in the H224 entry:
a `full` body backed by *both* `raw_text` and `extracted_text`+`content_hash` stays
`full` if either survives — the tier rule is robust, not brittle. Shipping one slice
dropped the work queue to 5, so per §1 this run **restored it to ~6** by appending
**H224** (the whole-library `export items`/`import items` backup sibling of H216 — the
*other* portable surface, only ever exercised all-`full` in `test_roundtrip.py`). The
queue now sits at **6** un-started work slots (H217 + H220–H224) + the H218 checkpoint.

**This run shipped H217** — bundle import is honest about orphan custody events,
opening the *event-complete* leg of the portable-bundle round-trip-depth horizon
(`src/scrolls/custody.py`, `src/scrolls/cli.py`, `tests/test_bundle.py`). The new
`custody.partition_resolvable_events` splits a bundle's parsed events into those that
resolve to a held-or-imported item and *orphans* (an `item_id` matching no such item);
`_cmd_import_bundle` imports only the resolvable ones, counts the orphans in the summary
(`events.orphaned`, **always present** — `0` is the honest affirmative "we checked, none
dangled"), and emits a `{"warning": …}` on stderr when non-zero. A well-formed export
never produces orphans (its events ride only for in-scope items, all in the items block),
so this guards the corrupt/hand-edited case: importing such an event would write a
dangling ledger row for an item `scrolls show` 404s on — `history`/`facets drift` would
read a phantom — so it is neither silently retained nor silently dropped (the M2
anti-fabrication ethos, on the import-completeness axis; custody §2.4). The whole-library
`import events` restore (H72) deliberately stays orphan-tolerant — that path restores
events independently of items, order the operator's (cli.md) — so the asymmetry is
principled, not accidental. Sabotage-verified non-vacuous: neutering the partition to
treat every event as resolvable fails both the orphan-count test and the
no-dangling-row test. Three existing exact-equality `events` assertions
(`test_bundle.py` ×2, `test_custody_convergence.py` ×1) were updated to the new
always-present `orphaned: 0` shape. Shipping one slice dropped the work queue to 5, so
per maintenance-rule §1 this run **restored it to ~6** by appending **H225** (the
*diagnosable* half of H217 — name *which* items the orphan events dangle on, so a
corrupt bundle is fixable, not just flagged). The queue now sits at **6** un-started work
slots (H220–H225) + the H218 checkpoint.

**This run shipped H220** — `scrolls import bundle --dry-run`, the read-only preview
of a bundle merge (`src/scrolls/cli.py` `_preview_import_bundle`,
`src/scrolls/custody.py`, `tests/test_bundle.py`). An agent handed a portable
"take it with me" bundle can now see *exactly* what an import would add vs. skip —
the same `{imported, skipped, items, events}` summary the real import prints, plus a
`"dry_run": true` marker — **without writing**, the read-only sibling of the
custody-safe `INSERT OR IGNORE` import (ADR 0082). Item counts come from `get_item`
existence (tracking within-bundle dups in a `seen_item_ids` set, so the preview is
exact, not just existence-based); event counts from the new
`custody.preview_import_events` (the writer's content-dedup, read-only, tracking
within-batch dups in a local `seen` set instead of via the prior INSERT); the orphan
split from `partition_resolvable_events`, now taking a `known_ids` argument so the
bundle's own item ids anchor the partition — a real import inserts those rows
*before* partitioning, so a preview into an **empty** library resolves the bundle's
events instead of mis-flagging every one as an orphan (the key correctness subtlety,
sabotage-verified: neutering `known_ids` fails all three new tests). The summary is
pinned **byte-for-byte equal to the subsequent real import's** (sans `dry_run`) over
a mixed held/new scope (`test_import_bundle_dry_run_counts_match_a_real_import`), so
the preview can never drift from reality; the dry-run also writes nothing
(`test_import_bundle_dry_run_previews_without_writing`) and is honest about orphan
events exactly as the real import (`test_import_bundle_dry_run_previews_orphan_events`,
warning on stderr, nothing written). Shipping one slice dropped the work queue to 5,
so per maintenance-rule §1 this run **restored it to ~6** by appending **H226** (the
*reviewable* half of H220 — name *which* scrolls are new vs. already held in the
preview JSON, so an agent confirms the merge adds what it expects, not just how much).
The queue now sits at **6** un-started work slots (H221–H226) + the H218 checkpoint.

**This run shipped H221** — the `index` `_Fidelity:_` line's `(of N)` scope is honest
under truncation (`tests/test_context.py`,
`test_context_index_fidelity_scope_is_honest_under_truncation`). The leanest tier's
holdings line counts the *in-bundle* set — `len(items)`, the kept post-cap
representations — not the library-wide matched total, so when the bundle is capped the
`(of N)` names only what the bundle saw. The test seeds a mixed-fidelity scope larger
than the cap (3 `full` + 3 `partial`, all matching `database`) and runs `context
--budget index --limit 4`: pigeonhole forces the kept 4 to span *both* tiers (only 3 of
either exist), so the in-bundle split (sums to 4) is provably not the library-wide `full
3, partial 3` (sums to 6). It pins three ties — the `_Fidelity:` `(of N)` equals the
`_Coverage: the top 4 of 6` line's `returned` (4, never the `matched` 6, the two numbers
parsed from the rendered lines so they're tied, not independently hardcoded), the tier
counts sum to that kept set (4, not 6), and the kept set is genuinely mixed. The work is
**test-only**: the production line already passes `len(items)` to
`render_fidelity_holdings` (`src/scrolls/context.py:252`), so the truncation honesty is
correct-by-construction — the slice *pins* it (the depth-axis sibling of H215's
drift-absence honesty; the *fidelity* counterpart of the Coverage line's match-set
honesty). Sabotage-verified non-vacuous on **both** guards: passing `matched` as the
scope N fails the `(of N)` tie, and folding the library-wide tier counts under the kept
`(of N)` fails the tier-sum tie. Shipping one slice dropped the work queue to 5, so per
maintenance-rule §1 this run **restored it to ~6** by appending **H227** (the MCP twin of
H223's *facet*-axis scope-honesty — the leanest tier names only the agent's facet scope on
the read reached over MCP, byte-identical to the CLI). The queue now sits at **6**
un-started work slots (H222–H227) + the H218 checkpoint.

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

---

## 3-day plan — 2026-06-20 → 2026-06-23

Forward-looking (re-derived at this H207 checkpoint). Each day ends on a
committed, tested, clean stopping point; slips roll forward.

- **Day 1 (2026-06-20):** Close the per-source custody convergence theme and
  re-derive the buffer. **H210** (the CLI refresh-debt *act* dogfood —
  read `context` `_Refresh:_` → run the scoped `classify --stale --source <S>` /
  `kb --stale --source <S>` it names → the named axis/source clears while the
  untouched axis persists; the refresh-axis twin of H206's drift triage)
  **shipped** in `tests/test_dogfood.py`, exhausting the per-source theme: every
  read *and* act surface, both axes, both the CLI and MCP, now ties to `doctor`.
  The **H207 checkpoint** (this refresh) opened the *budget/tier custody honesty*
  horizon, and the same run **shipped its lead slice H212** (the `_Fidelity:_`
  holdings line at `index` budget — fidelity travels even at the leanest tier via the
  new shared `custody.render_fidelity_holdings`, drift honestly does not;
  `src/scrolls/context.py` + `tests/test_context.py` + `docs/cli.md`).
- **Day 2 (2026-06-21):** Close the **budget/tier custody honesty** sub-theme around
  the shipped H212 line. **H213** (cross-tier fidelity convergence ≡ `doctor.tiers`),
  **H214** (the MCP `get_context(budget="index")` twin), **H215** (the CLI M2
  completeness fold — the `index` line names its holdings, never a drift verdict it
  didn't read), and **H219** (the MCP completeness twin of H215, this run) **all
  shipped 2026-06-20**, closing the sub-theme as a tested cross-tier / cross-surface /
  completeness contract on both surfaces — the *drift-withholding* honesty holds on
  the CLI and the read an agent reaches over MCP.
- **Day 3 (2026-06-22 → 2026-06-23):** Portable-bundle round-trip depth. **H216**
  (the mixed-fidelity bundle round-trip invariant — `partial`/`reference` tiers
  re-import tier-lossless, not just `full`) and **H217** (bundle import honest about
  orphan custody events — every imported event resolves to a held-or-imported item or
  is counted-and-skipped, never a dangling ledger row) **both shipped 2026-06-20**
  (`tests/test_bundle.py`), opening this horizon ahead of schedule. **H220**
  (`import bundle --dry-run` — the read-only preview of a merge, built on H217's
  orphan accounting) **shipped 2026-06-20**. Next: **H224** (the whole-library
  `export items`/`import items` backup sibling of H216 — tier-lossless on the *other*
  portable surface too), **H225** (the diagnosable half of H217 — name which items the
  orphan events dangle on), and **H226** (the reviewable half of H220 — name which
  scrolls are new vs. already held in the preview). The budget/tier scope-honesty
  pins slot in alongside: **H221** (the `index` `_Fidelity:_` `(of N)` honest under
  *truncation*, CLI) **shipped 2026-06-20**; **H222** (its MCP twin), **H223** (the
  *facet*-axis CLI sibling), and **H227** (the MCP twin of H223) remain. Re-derive at
  the H218 checkpoint.

---

## Week plan (more tentative) — through 2026-06-27

- The per-source custody **convergence theme is closed** (H179/H183/H195/H211/H208/
  H209 the reads, H206/H210 the self-healing dogfood across both surfaces and both
  act axes). "Custody reads the same everywhere, and an agent can act on exactly what
  the pointer names" is now a tested contract on the per-source, action-line,
  suggestion↔debt-map, and dogfood axes.
- The fresh horizon **budget/tier custody honesty** (H212–H215, H219) is **closed**:
  the leanest `index` context tier carries the *fidelity* holdings fact (vision
  principle 3 — fidelity travels with every result) while honestly *withholding* any
  drift verdict it read no ledger for (M2 anti-fabrication). H212 is the one production
  slice; H213 (the cross-tier tie), H214 (the MCP fidelity-line twin), H215 (the CLI M2
  completeness fold), and H219 (its MCP twin) all shipped — the drift-withholding
  contract holds on both the CLI and the read an agent reaches over MCP. The
  truncation/facet scope-honesty pins are the depth-axis follow-ons: **H221** (the
  `index` `_Fidelity:_` `(of N)` honest under *truncation*, CLI) **shipped 2026-06-20**;
  **H222**/**H223**/**H227** (its MCP twin, the facet-axis CLI sibling, and that
  sibling's MCP twin) remain.
- Then **portable-bundle round-trip depth** — **H216 and H217 both shipped
  2026-06-20** (H216 the mixed-fidelity bundle round-trip: portability is
  *tier-lossless*, not just full-lossless; H217 the event-complete leg: no silently
  orphaned custody events on import — every imported event resolves to a
  held-or-imported item or is counted-and-skipped), opening this horizon. **H220**
  (`import bundle --dry-run` — the read-only preview letting an agent review a shared
  bundle before merging it) **shipped 2026-06-20**; remaining are **H224** (the
  whole-library `export items`/`import items` backup sibling of H216 — tier-lossless on
  the *other* portable surface too), **H225** (the diagnosable half of H217 — name which
  items the orphan events dangle on), and **H226** (the reviewable half of H220 — name
  which scrolls are new vs. already held in the preview JSON).
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
