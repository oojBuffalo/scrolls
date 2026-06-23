# The dogfood flow — hold → prove → detect → take it with me

This is Scrolls' **success metric made runnable**: the one end-to-end,
agent-runnable flow that exercises the whole custody promise in order. The
custody vision (`docs/custody-vision.md`, capability 8) names it directly —
*"If an agent can't run it unattended, it isn't done."* It is MVP slice **M5**
(`docs/product/mvp.md`), and it ties together the earlier slices: refresh-safe
regeneration (M1), the completeness contract (M2), context budgets (M3), and
the shareable custody bundle (M4).

The executable proof is `tests/test_dogfood.py`. This page narrates what it
does, the exact commands an agent runs, and the custody story the numbers tell.

## The four legs

| Leg | What an agent runs | What it proves |
| --- | --- | --- |
| **Hold a topic** | `scrolls ingest <url>` (×N), then `scrolls kb` | the artifact is captured, rendered, and indexed at an honest fidelity tier |
| **Prove custody** | `scrolls doctor` | a custody **score** and tier breakdown — what we hold and how faithfully |
| **Detect loss** | `scrolls verify --all` | a re-check against the live source records **drift/rot** as an event, never an overwrite |
| **Take it with me** | `scrolls export bundle <query> > briefing.md` → `scrolls import bundle briefing.md` | the topic round-trips losslessly into a fresh library |

## Running it as commands

```bash
# 1. HOLD — capture a topic (live; each ingest fetches, renders, indexes)
scrolls ingest https://arxiv.org/abs/1706.03762
scrolls ingest https://example.com/transformer-explained
scrolls ingest https://example.com/scaling-transformers
scrolls kb                         # compile the interlinked library/ views

# 2. PROVE — score what we hold (network-free, deterministic)
scrolls doctor                     # → custody.score, custody.tiers, custody.drift

# 3. DETECT — re-check against the live sources (live; records custody events)
scrolls verify --all               # → unchanged / drifted / rotted / error
scrolls doctor                     # the drift block now reflects the re-check

# 4. TAKE IT WITH ME — a self-contained briefing that re-imports losslessly
scrolls export bundle transformer > transformer-briefing.md
cd /some/empty/library && scrolls init
scrolls import bundle /path/to/transformer-briefing.md
scrolls doctor --fix && scrolls doctor   # the fresh library proves its own custody
```

## The two live edges, and how the offline proof stands in for them

The flow has exactly two steps that touch the network — **capture** (`ingest`)
and **recheck** (`verify`). `tests/test_dogfood.py` keeps the proof
deterministic and offline by substituting a faithful stand-in for each:

- **Hold** seeds rendered, full-fidelity items the way a finished `ingest`
  leaves them (the same shape `tests/test_roundtrip.py` builds), through the
  production `write_scroll` path.
- **Detect** injects a scripted re-capture at the one seam `scrolls verify`
  uses — `cli.live_recapture`, exactly as `tests/test_verify_cli.py` does — so a
  known drift is observed without a live fetch.

The live edges themselves are covered by the adapter tests and the `verify`
tests. The dogfood proof's job is to show they **compose** into the custody
narrative the vision promises, reproducibly and unattended.

## What the run shows (captured 2026-06-16)

**Prove (after `hold`, before any recheck).** Three transformer scrolls, all
held in full; the drift block is honest that *nothing has been re-checked yet*
— `unverified` is the whole library, never silently `unchanged` (M2):

```json
{
  "score": 100,
  "tiers": { "full": 3, "partial": 0, "reference": 0 },
  "drift": { "basis": "last_verify", "as_of": null,
             "checked": 0, "unverified": 3, "drifted": 0, "rotted": 0 }
}
```

**Detect (`verify --all`).** One source has drifted upstream; the other two
come back byte-identical:

```json
{ "checked": 3, "unchanged": 2, "drifted": 1, "rotted": 0, "error": 0 }
```

**Prove again (after the recheck).** The drift posture moved — `unverified` → 0,
`drifted` → 1, with the event recorded against the held item — **but the
integrity score is unchanged at 100**:

```json
{
  "score": 100,
  "drift": { "basis": "last_verify", "as_of": "2026-06-16T10:05:23+00:00",
             "checked": 3, "unverified": 0, "unchanged": 2, "drifted": 1,
             "events": [ { "id": "arxiv:1706.03762", "status": "drifted",
                           "prior_hash": "sha256:06.03762",
                           "observed_hash": "sha256:drifted-upstream" } ] }
}
```

**Take it with me.** `export bundle transformer` writes a self-contained
briefing whose head reads like a topic summary and whose fenced block carries
the full custody record; `import bundle` into a fresh library reports
`{"imported": 3}` and recovers every scroll byte-for-byte (a second import
reports `{"imported": 0, "skipped": 3}` — re-import is idempotent and never
overwrites). The fresh library then scores its own custody at `100`.

## The custody point the before/after makes visible

The "before/after custody score" the dogfood captures is **not** the integrity
score — that holds at `100` throughout. It is the **drift posture**: a library
moves from *"unverified"* (we have not looked) to *"drifted, recorded"* (we
looked and the source moved).

That the integrity score does **not** drop when a source drifts is the whole
point, not a gap. *Raw is sacred* (custody-vision §2.2): the source changing
upstream is a recorded custody **event**, not a loss of what we hold
(§2.4 — "a re-fetch that disagrees … is a custody event … not an overwrite").
Custody stays intact precisely because the capture is never clobbered by the
re-check. An agent reading the report can always tell *"confirmed unchanged at
the last verify"* from *"never checked"* from *"the source drifted, here is the
event"* — and can still walk away with the faithful copy it held.

## Adopting a peer's better capture — the accept-incoming flow

The four legs above are the *one-custodian* story: I hold a topic, prove it,
watch the source drift, and carry it elsewhere. The accept-incoming flow
(ADR 0106, roadmap H278) adds the *two-custodian* one — **a peer re-captured a
source I hold and got a better copy, and I want to adopt it without losing the
one I had.** It is a genuinely new custody move: the first import path that
*changes* a held capture. The drift leg never overwrites; this one does — but
custody-safely, because the prior is archived first and the swap is a recorded
event, so it is a *flip of which faithful copy I hold*, never a loss.

`tests/test_dogfood.py` pins it offline as
`test_adopt_a_peers_better_capture_flips_the_held_copy_and_clears_the_conflict`:
the same `_held_topic()` is held in a `library` home, then a `peer` home holds
the same topic with one diverging arxiv capture (a fuller body, a fresh content
hash) and exports a bundle. The custody story is the **conflict aggregate moving
0 → 1 → 0** while the **held content flips and flips back and the integrity score
never drops**.

```bash
# A peer shares a bundle. One capture (the arxiv paper) diverges from mine.
# 1. DETECT — import it WITHOUT adopting: the divergence is surfaced + recorded,
#    my held copy is kept untouched (raw is sacred — custody §2.4).
scrolls import bundle peer-briefing.md
# → {"unchanged": 2, "conflict": 1, "conflicts": ["arxiv:1706.03762"], "adopted": []}

# 2. REVIEW — doctor counts the open conflict (0 → 1); the score is still 100.
scrolls doctor                       # → custody.conflicts.items == 1
scrolls history arxiv:1706.03762 --status conflict   # the recorded divergence

# 3. ADOPT — re-import WITH --accept-incoming: the held copy is replaced by the
#    peer's, its prior archived (recoverable), the conflict cleared.
scrolls import bundle peer-briefing.md --accept-incoming
# → {"adopted": ["arxiv:1706.03762"], "conflicts": []}
scrolls doctor                       # → custody.conflicts.items == 0, score 100
scrolls history arxiv:1706.03762 --status superseded   # the recorded adoption

# 4. RESTORE — the prior is never gone: emit it and re-adopt it (the peer copy is
#    archived in turn — the symmetric round-trip).
scrolls archive show arxiv:1706.03762 > prior.jsonl
scrolls import items prior.jsonl --accept-incoming
# → {"adopted": ["arxiv:1706.03762"]}      # held content flipped back to mine
scrolls doctor                       # → custody.conflicts.items == 0, score 100
```

**Detect (`import bundle`, no flag).** The peer's two web scrolls travel
byte-identical (`unchanged`); their arxiv capture disagrees on `content_hash`, so
it is surfaced as a `conflict` and recorded — never written over my held copy:

```json
{ "unchanged": 2, "conflict": 1, "conflicts": ["arxiv:1706.03762"], "adopted": [] }
```

`doctor`'s conflict aggregate now reads `1`, the divergence named with both
hashes, **while the integrity score holds at 100** (a peer disagreeing is not
evidence *my* capture degraded):

```json
{
  "score": 100,
  "conflicts": { "basis": "import_ledger", "items": 1,
                 "events": [ { "id": "arxiv:1706.03762", "status": "conflict",
                               "prior_hash": "sha256:06.03762",
                               "observed_hash": "sha256:peer-recapture" } ] }
}
```

**Adopt (`import bundle --accept-incoming`).** Now I take the peer's copy. The
held row is replaced, its prior snapshot appended to the recovery archive, and a
`superseded` event supersedes the open conflict — so the aggregate clears (`1 →
0`) across every conflict surface at once, and the score is still 100:

```json
{ "adopted": ["arxiv:1706.03762"], "conflicts": [] }
```

```json
{ "checked_at": "…", "status": "superseded",
  "prior_hash": "sha256:06.03762", "observed_hash": "sha256:peer-recapture",
  "detail": "import conflict resolved: incoming capture adopted (accept-incoming); prior copy archived" }
```

**Restore (`archive show … | import items --accept-incoming`).** The prior was
archived, not destroyed: `archive show` re-emits it in the `export items` JSONL
shape, and re-adopting it flips the held content back to my original capture
(archiving the peer copy in turn). The aggregate stays `0` — a `superseded`
adoption is a resolution, never an open conflict — and the final audit is clean:

```json
{ "score": 100, "conflicts": { "items": 0 },
  "tiers": { "full": 3, "partial": 0, "reference": 0 } }
```

The custody point is the adopt-axis twin of the drift leg's: **adopting a peer's
capture never lowers the integrity score**, because the swap trades one
full-fidelity copy for another and the displaced one is archived (custody §2.4 —
"a re-fetch that disagrees … is a custody event"). The held `content_hash` goes
*original → peer → original* while the score holds at `100` throughout; every
prior stays recoverable, so the flip is fully reversible. (`adopt_incoming` swaps
the row but does not re-render the scroll view — a real agent runs `scrolls kb`
afterward to recompile `library/`; the held file the prior render left in place
keeps the fidelity audit honest in the meantime.)

## Rolling back to a specific earlier version — restore-by-version

The adopt flow above takes *one* peer capture and, if I change my mind, restores
the **latest** prior. The restore-by-version flow (ADR 0106, roadmap H285/H286)
covers the case a real custodian hits after living with a source for a while: I
adopted a **chain** of recaptures over several days (v1 → v2 → v3), then realised a
*specific earlier* version — not the latest — was the right one. `archive show
<id> --all` shows the **whole** recoverable history, and `archive restore <id>
--hash H` / `--at ISO` rolls back to the version I name. The custody story is the
adopt leg's, extended across many supersessions: **the held copy flips to the
*chosen* prior, the displaced copy is itself archived, and the integrity score
holds at 100 the whole way.**

`tests/test_dogfood.py` pins it offline as
`test_restore_by_version_rolls_back_to_a_specific_earlier_capture`: the same
`_held_topic()` arxiv paper is recaptured three times via `import items
--accept-incoming`, then rolled back twice — by `--hash` to an intermediate, by
`--at` to the original. (A scripted clock spaces the three adoptions across days so
`--at` has a real history to bisect — the same offline stand-in this module applies
to capture and recheck, here on the adoption clock.)

```bash
# I adopted three divergent recaptures over three days; the prior is archived each time.
scrolls import items in.jsonl --accept-incoming   # → {"adopted": ["arxiv:1706.03762"]}  ×3

# 1. INSPECT the full recoverable history (newest first) — every version is still here.
scrolls archive show arxiv:1706.03762 --all
# → sha256:peer-v2 / sha256:peer-v1 / sha256:06.03762   (the three displaced priors)
scrolls archive list --id arxiv:1706.03762            # the same, with archive timestamps
scrolls doctor                                        # → custody.score 100 (held = peer-v3)

# 2. ROLL BACK by --hash to a *specific intermediate* (v1, NOT the latest prior v2).
scrolls archive restore arxiv:1706.03762 --hash sha256:peer-v1
scrolls doctor                                        # → custody.score 100 (held = peer-v1)

# 3. ROLL BACK by --at to the *original*, as held at the earliest point in time.
scrolls archive restore arxiv:1706.03762 --at 2026-06-19T12:00:00+00:00
scrolls doctor                                        # → custody.score 100 (held = the original)
```

**Inspect (`archive show --all`).** After three adoptions the archive holds three
priors; `--all` re-emits **every** one as a re-importable `export items` line,
newest first — not just the head `archive show` would give:

```json
{ "count": 3, "archived": [
  { "prior_hash": "sha256:peer-v2", "superseded_by": "sha256:peer-v3", "archived_at": "2026-06-21T00:00:00+00:00" },
  { "prior_hash": "sha256:peer-v1", "superseded_by": "sha256:peer-v2", "archived_at": "2026-06-20T00:00:00+00:00" },
  { "prior_hash": "sha256:06.03762", "superseded_by": "sha256:peer-v1", "archived_at": "2026-06-19T00:00:00+00:00" } ] }
```

**Roll back by `--hash`.** The selector lands the *chosen* version — the
intermediate `peer-v1`, even though the latest prior is `peer-v2` — and the
currently-held `peer-v3` it displaces is archived in turn, so the rollback is
itself reversible:

```json
{ "selector": { "hash": "sha256:peer-v1" }, "prior_hash": "sha256:peer-v1",
  "held_hash": "sha256:peer-v3", "outcome": "adopted", "restored": true }
```

**Roll back by `--at`.** A point-in-time selector — the newest prior archived
at/before the boundary. `--at 2026-06-19T12:00` lands the **original** capture
(`06-19`); the v1/v2/v3 priors were archived later, so they fall after the line.
The displaced `peer-v1` is archived in turn:

```json
{ "selector": { "at": "2026-06-19T12:00:00+00:00" }, "prior_hash": "sha256:06.03762",
  "archived_at": "2026-06-19T00:00:00+00:00", "held_hash": "sha256:peer-v1",
  "outcome": "adopted", "restored": true }
```

The custody point is the restore-by-version twin of the adopt leg's: across a whole
chain of adoptions **and** two rollbacks, **`doctor`'s `custody.score` never leaves
100** — each restore swaps one full-fidelity capture for another and the displaced
one is archived, so no version is ever destroyed and the held copy can flip to *any*
prior on demand (custody §2.4). `archive show` after each rollback recovers exactly
the version just left, the proof the whole history stays reversible.

## Deciding before you restore — `archive diff`

Restore-by-version above *acts* — it rolls back to a version I name. But a careful
custodian wants to **look before they leap**: *what* would a restore change, and
*would it change anything at all*? `archive diff <id>` (ADR 0106, roadmap H288) is
that read — it folds the **same** `select_archived_snapshot` selector
(`--hash`/`--at`, default the latest) `archive restore` uses against the
currently-held copy and reports the delta *without writing*: the held↔prior
`content_hash`, each side's fidelity tier, the model-complete `changed_fields` a
restore would surface, and `would_restore` (would a restore actually move the held
copy, or is the prior already what I hold?). Because the diff and the restore share
one selector and one `content_hash` compare, **the decision the diff shows can never
disagree with the restore I then run** — `would_restore` *is* the restore's
`restored`.

`tests/test_dogfood.py` pins the whole decide → act loop offline as
`test_archive_diff_decides_then_restore_acts_exactly_as_predicted`: hold the topic,
adopt one divergent peer capture (one prior archived), then **diff → restore → diff
again → restore again**, asserting each act lands exactly on the diff's prediction —
on both the would-change case and the idempotent no-op.

```bash
# I adopted one peer capture; my original is archived as the prior.
scrolls import items peer.jsonl --accept-incoming   # → {"adopted": ["arxiv:1706.03762"]}

# 1. DECIDE — what would restoring the prior change, and would it change anything?
scrolls archive diff arxiv:1706.03762
#   → would_restore: true, changed_fields: [content_hash, extracted_text, raw_text]
#     held = the peer's capture, prior = my original (both still full fidelity)

# 2. ACT — restore lands exactly what the diff predicted (read-then-act convergence).
scrolls archive restore arxiv:1706.03762            # → restored: true, outcome: adopted
scrolls doctor                                       # → custody.score 100 (held = my original)

# 3. DECIDE AGAIN — diff the version I just restored: nothing left to restore.
scrolls archive diff arxiv:1706.03762 --hash sha256:06.03762
#   → would_restore: false, changed_fields: []   (the prior already *is* what I hold)

# 4. ACT AGAIN — restoring the already-held version is the no-op the diff predicted.
scrolls archive restore arxiv:1706.03762 --hash sha256:06.03762   # → restored: false, outcome: unchanged
```

**Decide (`archive diff`).** The held copy is the peer's capture; the prior is my
original. The diff names exactly the fields a restore would surface (the three the
peer recapture diverged on, no more — a full→full swap, no fidelity loss) and
predicts the write:

```json
{ "selector": { "latest": true }, "prior_hash": "sha256:06.03762",
  "held_hash": "sha256:peer-recapture", "held_fidelity": "full", "prior_fidelity": "full",
  "changed_fields": ["content_hash", "extracted_text", "raw_text"], "would_restore": true }
```

**Act (`archive restore`).** Run with the same selector, the restore lands exactly
what the diff named — `would_restore` *is* `restored`, the prior the diff showed is
the version restored, the held copy the diff showed is the one displaced:

```json
{ "selector": { "latest": true }, "prior_hash": "sha256:06.03762",
  "held_hash": "sha256:peer-recapture", "outcome": "adopted", "restored": true }
```

**Decide again (`archive diff --hash`).** Diff the version I just restored: held and
prior are now the same capture, so there is nothing left to restore — the idempotency
the first diff's chain implied, read *before* I'd act on it:

```json
{ "selector": { "hash": "sha256:06.03762" }, "held_hash": "sha256:06.03762",
  "prior_hash": "sha256:06.03762", "changed_fields": [], "would_restore": false }
```

**Act again (`archive restore --hash`).** Restoring the already-held version is the
`unchanged` no-op the second diff predicted — `would_restore: false` *is*
`restored: false` on the idempotent case too:

```json
{ "selector": { "hash": "sha256:06.03762" }, "outcome": "unchanged", "restored": false }
```

The custody point is the decide-before-you-restore twin of restore-by-version's: a
diff is a true **read** — the held `content_hash` is untouched across every diff, only
the `restore` between them moves it, and `doctor`'s `custody.score` holds at 100 the
whole way. So an operator can inspect a rollback as many times as they like, on any
version, before committing to it, and the write they finally run is exactly the one the
read promised (custody §2.4).

## Taking the recovery workflow with you — a machine handoff

The flows above all recover on the *same* library that made the adoptions. The
custody promise is bigger than that: **the whole recovery workflow travels.**
`export bundle --with-archive` (ADR 0106, roadmap H280) packs the prior-content
archive *into* the portable bundle, so someone can hand you a single file and you
can `import bundle` it into a fresh library on a machine that *never saw the
original adoptions* — and still **decide-and-restore** on it. H291 pins that the
recovery *reads* (`archive show --all`/`diff`/`restore --dry-run`) come back
identical after the round-trip; this leg runs the recovery *act* — a real
`archive restore` write — on the rebuilt library.

`tests/test_dogfood.py` pins it offline as
`test_recovery_workflow_survives_a_machine_handoff`: on **machine A**, hold the
topic and adopt a *chain* of two divergent peer captures (v1 → v2) so the archive
holds two recoverable priors, then `export bundle --with-archive`. On **machine
B** — a fresh library — `import bundle`, repair, then **inspect → decide → act**,
asserting the act lands exactly on the diff's prediction across the machine
boundary, on both the would-change and the idempotent cases.

```bash
# ── machine A: I adopted a chain of two peer captures; both priors are archived ──
scrolls export bundle transformer --with-archive > briefing.md   # the artifact I hand off

# ── machine B (never saw A's adoptions): rebuild from the bundle alone ──
scrolls import bundle briefing.md
#   → {"imported": 2, "archive": {"imported": 2, "skipped": 0}}   (both priors travelled)
scrolls doctor --fix && scrolls kb     # import inserts rows; --fix materializes the scrolls
scrolls doctor                         # → custody.score 100  (the recovery store is here)

# 1. INSPECT — the full recoverable history travelled, newest-first.
scrolls archive show arxiv:1706.03762 --all
#   → sha256:peer-v1, sha256:06.03762     (the latest prior *and* my original)

# 2. DECIDE — reach *past* the latest prior (v1) to my original by --hash.
scrolls archive diff arxiv:1706.03762 --hash sha256:06.03762
#   → would_restore: true, changed_fields: [content_hash, extracted_text, raw_text]

# 3. ACT — a real restore on B lands exactly what the diff predicted.
scrolls archive restore arxiv:1706.03762 --hash sha256:06.03762   # → restored: true, outcome: adopted
scrolls doctor                                                     # → custody.score 100 (held = my original)

# 4. DECIDE + ACT AGAIN — the version I just restored has nothing left to restore.
scrolls archive diff arxiv:1706.03762 --hash sha256:06.03762      # → would_restore: false, changed_fields: []
scrolls archive restore arxiv:1706.03762 --hash sha256:06.03762   # → restored: false, outcome: unchanged
```

**Rebuild (`import bundle`).** The fresh library takes the holdings, the custody
ledger, *and* the prior-content archive from the one file — both archived priors,
not just the latest head:

```json
{ "imported": 2, "skipped": 0, "adopted": [], "conflicts": [],
  "events": { "imported": 2, "skipped": 0, "orphaned": 0 },
  "archive": { "imported": 2, "skipped": 0 } }
```

**Decide on B (`archive diff --hash`).** B holds the peer's latest capture (v2);
the `--hash` selector reaches past the latest prior to my original, and the diff
predicts the write — identical to the diff I'd have read on A:

```json
{ "selector": { "hash": "sha256:06.03762" }, "prior_hash": "sha256:06.03762",
  "held_hash": "sha256:peer-v2", "held_fidelity": "full", "prior_fidelity": "full",
  "changed_fields": ["content_hash", "extracted_text", "raw_text"], "would_restore": true }
```

**Act on B (`archive restore --hash`).** A real write on the rebuilt library —
`would_restore` *is* `restored`, the held copy flips to my original, the displaced
v2 is archived in turn (the rollback stays reversible on B too):

```json
{ "selector": { "hash": "sha256:06.03762" }, "prior_hash": "sha256:06.03762",
  "held_hash": "sha256:peer-v2", "outcome": "adopted", "restored": true }
```

The custody point is the cross-machine twin of decide-before-you-restore's: the
*whole* recovery workflow — inspect, decide, **and act** — travels in the portable
bundle, so you can recover on a machine that never witnessed the adoptions, the
act still lands exactly what the read promised, and `doctor`'s `custody.score`
holds at 100 through the real recovery write. "Take it with me" reaches past the
holdings to the recovery *capability* itself (M4/cap 4, custody §2.4).

## Running the proof

```bash
uv run pytest tests/test_dogfood.py
```

Ten tests: each leg on its own — the core hold/detect/take legs, the scoped
drift- and refresh-triage legs, the accept-incoming *adopt-a-peer's-better-capture*
flow, the *restore-by-version* roll-back, the *decide-before-you-restore*
`archive diff` → `archive restore` loop, and the *cross-machine recovery* leg above
(the whole decide → act loop run on a library rebuilt from a `--with-archive`
bundle) — plus `test_dogfood_flow_hold_prove_detect_take`, the whole hold → prove →
detect → take sequence in order, unattended. The lossless round-trip leg shares its guarantee
with `tests/test_roundtrip.py` (the JSONL backup invariant, ADR 0099); the bundle
envelope is ADR 0103; the accept-incoming adoption + prior-content archive (and its
restore-by-version and decide-before-you-restore reads) are ADR 0106.

## The recurring sibling — `scrolls maintain`

The dogfood flow is the *one-shot* proof. Its recurring form is a single command,
`scrolls maintain` (see [cli.md](cli.md), `### scrolls maintain`), the
scheduled custody-maintenance pass an hourly worker can run unattended:

1. **recheck** the live edge — a bounded `verify --all` (`--limit N`, or
   `--no-recheck` for a fully offline pass), recording drift events;
2. **regenerate** the `library/` views (deterministic `kb` compile);
3. **audit** the post-maintenance state read-only (`doctor`, never `--fix`);
4. report the **custody delta** since the last run — `score`, fidelity `tiers`,
   drift posture, and the `enrichment_stale`/`summaries_stale` counts — against a
   snapshot recorded at `<root>/.maintenance/last-run.json`.

It is report-only and idempotent (custody-vision §2.4): it records events and
regenerates views, but never repairs index rows, reclassifies, or re-summarizes —
`doctor --fix`, `classify --stale`, and `kb --stale` stay the explicit, on-request
mutations. The delta makes the custody point above **recurring**: each pass shows
the drift posture moving without the integrity score ever dropping. Proven offline
in `tests/test_maintain.py` (the same `cli.live_recapture` seam this flow uses).

Each pass also appends its `{recorded_at, snapshot, delta}` to an append-only
`<root>/.maintenance/log.jsonl`, so `scrolls maintain --history [N]` reads the
last N runs back as the custody **trend** — the score/drift *trajectory* an
unattended worker watches over time, not just the single most recent diff.

When custody loss is confined to one source, an agent reads `scrolls status`
(or `scrolls doctor`) — whose `attention` flag names the single weakest source
and the exact `scrolls verify --source <S>` recheck command — and runs a
**scoped** pass, `scrolls maintain --source <S> --no-recheck`, to triage *only*
that source instead of the whole library. A scoped pass narrows the audit/delta
to `<S>` (`by_source` collapses to the singleton `{S: …}`, `attention` is null —
one source has nothing to flag *across*), regenerates the global views, and stays
**non-persisting**: it writes no whole-library snapshot, so its `delta` is
honestly `null` and the whole-library trend baseline an earlier pass recorded is
left byte-untouched (ADR 0082 — the whole-library pass owns the single trend
baseline). Its `custody` ≡ `doctor --source <S>`'s distilled snapshot. The
dogfood suite pins this as one shell sequence — `status`'s `attention` names the
weakest source, the agent runs the scoped pass on *exactly* that source, the
trend baseline is untouched — the symmetric shell twin of the MCP triage below,
so the agent reads *where* the loss is and acts *only there*, custody-safely.

## The same loop over MCP

The flow above is how an agent drives custody from the **shell**. An agent that
speaks the [Model Context Protocol](architecture.md) instead drives the *same*
loop through the MCP tools (`scrolls mcp`), with no network, against fixtures —
pinned in `tests/test_dogfood_mcp.py`, the MCP sibling of `tests/test_dogfood.py`:

| Leg | CLI command | MCP tool |
| --- | --- | --- |
| **Prove custody** | `scrolls doctor` | `get_library_health` (whole-library score, tiers, drift) |
| **Detect loss** | `scrolls verify --all` | `verify_scroll` per held item (the `mcp_server.live_recapture` seam) |
| **Recur** | `scrolls maintain` / `--history --trend` | `run_maintenance` then `get_maintenance_history(trend=True)` |

The MCP loop has **no "take it with me" leg** — export/import-bundle is a shell
concern with no MCP twin (an MCP tool must never trigger a paid or implicit
write). An MCP agent's *recurring* custody work is the maintenance pass and its
trend read instead: `run_maintenance` runs offline (always `--no-recheck`,
never an implicit re-capture — targeted live rechecks stay the explicit
`verify_scroll`), records a snapshot, and `get_maintenance_history(trend=True)`
reads the trajectory. Two passes that both carry the recorded drift read
`holding`, not `regressing` — the recurring form of the custody point above:
the drift is recorded and the integrity score never drops.

When `get_library_health`'s `attention` flag names a single weakest source, the
agent can run a **scoped** pass on just that source — `run_maintenance(source=S)`
(H203), the MCP sibling of `scrolls maintain --source S` — instead of the whole
library or re-composing the triage. A scoped pass narrows the audit/delta to
`S`, regenerates the global views, and stays **non-persisting** (it writes no
whole-library snapshot, so its `delta` is honestly `null` — the whole-library
pass owns the trend baseline). It converges field-for-field with the CLI
`maintain --source S --no-recheck`. The dogfood-MCP suite pins this as one
agent-driven sequence — the `attention` flag names the weakest source, the agent
runs the scoped pass on *exactly* that source, and the whole-library trend
baseline an earlier pass recorded is left byte-untouched — so the agent reads
*where* the loss is and acts *only there*, custody-safely (the scoped sibling of
the whole-library pass H201 tied in).

The MCP twins are pinned to converge with the CLI commands they wrap per-tool in
`tests/test_mcp.py` (`get_library_health` ≡ `status`/`doctor`, `run_maintenance`
≡ `maintain --no-recheck`, `get_maintenance_history` ≡ `maintain --history`); the
dogfood-MCP suite ties them into one agent-driven flow and pins that an agent
reading custody over MCP reaches the same conclusion `scrolls doctor` does over
the identical post-drift state.
