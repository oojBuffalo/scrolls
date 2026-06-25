# 0107: A whole-library custody posture verdict folds the doctor custody blocks into one `sound`/`attention`/`at_risk` read

Date: 2026-06-25

Status: accepted

## Context

The custody-vision §3.1 (the load-bearing "custody integrity audit") asks `scrolls
doctor` to output **"a per-library custody score with a categorized breakdown."** The
codebase has the *categorized breakdown* — `run_doctor`'s `custody` block carries seven
audit dimensions (integrity findings + `score`, fidelity `tiers`, the `drift` posture,
the `conflicts` aggregate, the `works` at-risk alarm, the `archive` integrity audit, the
`content_duplicates` redundancy report, plus the `enrichment`/`summaries`
re-derivability blocks) — and an integrity `score` (the percent of items free of the
three integrity findings). But the `score` is **integrity-only**: it ignores drift,
at-risk works, open conflicts, and archive tampering. An agent or operator asking the
one question the vision frames — *"is this library in good custody?"* — had to read and
weigh seven separate blocks and apply its own severity judgment.

That judgment is exactly what should live in the audit, not be re-derived by every
reader. The slice (roadmap H369) adds the single distilled verdict — but it must resolve
which dimensions count, and at what severity, **without** contradicting two custody
principles already enforced elsewhere:

> **(1)** Where does *drift* sit? The §3.8 dogfood proof's sharp result is that
> detecting source drift moves the **posture** *without* lowering the **integrity
> score** — raw is sacred, drift is a recorded *event*, not a defect (§2.4). A verdict
> that flagged a drifted library as a hard custody loss would re-break that.
>
> **(2)** Do byte-identical *content duplicates* count? H325 settled that holding two
> faithful copies is honest custody, a redundancy *fact*, **never** a defect (no
> `--fix` merge). A verdict that degraded on duplicates would contradict that.

## Decision

### A deterministic fold over the already-computed blocks, never a new judgment

`custody.posture = {"verdict": <band>, "reasons": [<slug>, …]}` is computed by
`doctor._assess_custody_posture(report)` **after every check runs**, reading only the
report `run_doctor` already produced — no network, no second query, no new data. It
asserts nothing integrity (§2.8) does not already verify; it only *summarises* verified
findings, and `reasons` keeps it explainable (§2.6), never a black box. Because
`get_library_health` returns `run_doctor`'s whole custody block (`{**custody, …}`), the
MCP twin carries the verdict for free, converging with the CLI `doctor` by construction.

### Three bands, grounded in the codebase's own severity distinctions

The bands are **not invented thresholds**; each axis maps to the severity the codebase
already assigns it:

- **`at_risk` — a hard custody loss is present** (custody is *actually* compromised):
  a custody integrity finding (`custody.issues > 0` — a fingerprint we can no longer
  reproduce, a missing scroll, missing provenance), an at-risk work
  (`custody.works.at_risk > 0` — every representation of a work degraded or moved), or
  an archive-integrity mismatch (`custody.archive.mismatched > 0` — the un-launderable
  tamper alarm whose `restore` would adopt content under a different hash than
  advertised).

- **`attention` — no hard loss, but a soft concern wants a decision:** an open import
  conflict (`custody.conflicts.items > 0` — a peer's capture disagreed; reconcile it) or
  source drift (`custody.drift.drifted > 0 or .rotted > 0` — the live source moved;
  recapture may be warranted).

- **`sound`** — none of the above: every held copy faithful, re-derivable,
  provenance-complete, unmoved, undisputed, untampered.

`verdict` is the **worst** band any axis fires (hard wins over soft); `reasons` lists
**every** contributing axis in fixed severity order (`custody_integrity`,
`at_risk_works`, `archive_integrity`, then `open_conflicts`, `source_drift`), so an
agent triaging an `at_risk` library sees the whole picture, not only the worst axis. The
axes are declared once in `doctor._POSTURE_AXES` as `(slug, band, read)` triples — adding
a future dimension is one row.

### Drift is `attention`, never `at_risk`; content duplicates are excluded entirely

Resolving the two questions above:

- **Drift maps to `attention`, never the hard band, and never touches the integrity
  `score`.** This is the §3.8 invariant lifted to the verdict: *detecting* drift moves
  the **posture** (sound → attention, a recapture decision), not the integrity score —
  raw is sacred, drift is an event, not a defect (§2.4). Pinned by a test asserting a
  drifted item yields `posture.verdict == "attention"` **and** `custody.score == 100`.

- **Content duplicates contribute nothing.** They are a redundancy fact, never a defect
  (H325) — a content-duplicate-only library stays `sound`. Pinned by a test.

### Scope honesty mirrors the blocks the verdict folds

Under `doctor --source`, the whole-library alarms `at_risk_works` and `archive_integrity`
are `status: "skipped"` (a work spans sources; the archive is one whole-library store),
so they contribute nothing and a scoped posture reflects only the source-attributable
axes — integrity, drift, conflicts. A whole-library verdict therefore requires a
whole-library run, exactly the scope honesty those blocks already carry. A
missing/uninitialized library keeps the skeleton default `sound` (empty, hence healthy —
the existing `run_doctor` contract).

### Report-only, like every custody block

The posture **never** feeds `doctor`'s structural `issues`/`fixed` counts or its exit
code: an `at_risk` posture from an upstream loss doctor cannot repair still exits 0 (no
structural drift to fix). It is a triage signal for an agent/operator, not a repair gate
— the drift/conflicts/works/archive report-view precedent.

## Consequences

- An agent asks `get_library_health` (or reads `scrolls doctor`'s
  `custody.posture.verdict`) **once** to learn whether the library is in good custody,
  instead of cross-referencing seven blocks and applying its own severity judgment — the
  "categorized breakdown → single verdict" the vision §3.1 calls for. `reasons` points it
  at exactly which dimensions to drill into.

- The verdict converges with `doctor`/`get_library_health` by construction (one
  `run_doctor` read, one fold), so the CLI and MCP transports can never disagree about
  the library's posture (custody §2.6, identical semantics across surfaces).

- This opens the **custody-posture theme**. The remaining legs propagate the verdict to
  the surfaces an operator/agent *skims* (the `fidelity`/`drift` surface-propagation
  precedent), all deferred to their own slices: a readable `_Posture:_` headline on
  `maintain` + the `scrolls status` scalar twin, the same line on the shareable `export
  bundle`/`scrolls context` briefings, and a cross-run posture-movement clause (the
  `at_risk`/`conflicts` trend precedent). `custody_snapshot`/`maintain`/`status` are
  deliberately **untouched** this slice, so the verdict lives on `doctor`/MCP only until
  those legs land.

- Verified offline (`tests/test_doctor.py` ×13, `tests/test_mcp.py` ×1): clean / empty /
  uninitialized → `sound`; an integrity finding / at-risk work / archive mismatch →
  `at_risk` with the matching reason; an open conflict / source drift → `attention` with
  the integrity score untouched (the §3.8 invariant); content duplicates alone →
  `sound`; a hard + soft loss together → `at_risk` listing both reasons worst-first; the
  scoped run reflects only source-attributable axes; the posture never feeds the exit
  code; and the MCP `get_library_health` twin carries it at byte-parity with CLI
  `doctor`. Full suite **4143 passed**.

## Deferred

- **The readable `_Posture:_` headline + `status` scalar + briefing line + cross-run
  trend** (the surface-propagation legs above), each on its own slice.

- **A numeric composite score.** The vision §3.1 says "score with a categorized
  breakdown"; this ships the *categorical verdict* over the breakdown. A weighted numeric
  roll-up risks the "invented number" the vision cautions against (§2.8, integrity is
  verified, not asserted) — deferred unless a workflow shows the three-band verdict
  insufficient.
