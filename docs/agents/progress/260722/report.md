# Progress Report — 2026-07-22

**Date:** 2026-07-22
**Branch:** `work/scrolls-dev` (agent trunk) — HEAD `2a5344f`, 523 commits ahead of `main`
**Slice series:** through **H425**
**Suite:** 4370 tests passing (~62s, `uv run pytest -q`)

*Amended: 2026-07-26 — moved from the old top-level docs progress location
into the check-in structure `docs/agents/progress/<YYMMDD>/`; retitled to a
facts-only report
(the "what's next" material moved to `plans.md` alongside) and vision/lineage
pointers retargeted after the docs consolidation. Realigned the same day:
the automation/ops facts from the autonomous-machine session (the 2026-07-20
reassessment) were folded in — see "Automation & ops" below and
`reconciliation.md` — and the H363→H425 phase corrected from "in progress"
to closed.*

This is a **facts-only** current-state report, not a changelog: what exists
and what is complete. The companion files in this directory carry the
judgment: `reconciliation.md` (did progress match the goals/plans?) and
`plans.md` (next objectives + 1/3/7-day plan). Per-slice detail lives in git
(`git log --oneline | grep '(H<NN>)'`) and the shipped ledger in
`docs/agents/autonomous-roadmap.md`.

---

## What Scrolls is

A **local-first custody system** for internet artifacts a person deliberately saved
or referenced (bookmarks, papers, videos, repos, threads, PDFs). Its job is *not*
discovery or web search — it is durable stewardship of material the user already chose
to keep: hold each artifact faithfully, prove what it was at capture time, surface
drift/rot honestly, degrade transparently when full fidelity is impossible, and let
the user walk away with everything losslessly at any time.

```
Sources → Items → Scrolls → Library → Agents
```

The Markdown scroll (rich frontmatter + body) is the canonical durable artifact;
SQLite is a rebuildable index. **Raw is sacred** — every derived view (scrolls,
`library/`, facets, bundles) must be regenerable from raw + index with one command.

Authoritative north star: `docs/vision.md` (the custody-first synthesis; the
three vision documents were merged into it 2026-07-26).

## Codebase shape

| Area | Size |
| --- | --- |
| Source (`src/scrolls`) | 90 files, ~36.9k LOC |
| Tests (`tests/`) | 126 files, ~91.4k LOC |
| ADRs (`docs/adr`) | 108 (0004 → 0107) |
| Source adapters (`sources/`) | ~57 |
| MCP tools | 24 (17 read + 7 custody-safe write; pinned by H364) |
| Commits (dev trunk) | 526 total / 523 ahead of `main` |

The test suite is roughly **2.5× the size of the source** — the project's discipline
is that every custody claim is backed by a fixture-driven contract, not asserted.

## Pipeline & module map

Six stages, elevated from the Field Theory lineage
(`docs/inspiration/fieldtheory-cli-inspiration.md`):

1. **Ingest** — `sources/*` adapters detect + fetch; `detect.py`, `pipeline.py`.
2. **Enrich** — full text, transcripts, metadata, provenance.
3. **Classify** — `classify.py` (rules) + `classify_llm.py`; re-runnable, auditable.
4. **Reconcile** — `works.py`, `related.py`, `custody.py` — works merge, dedup,
   relationship + content-identity inference. Report-only; never auto-merges raw.
5. **Index & Compile** — `db.py` (SQLite/FTS), `kb.py`/`render.py`/`generated.py`
   compile the interlinked `library/` Markdown + graph.
6. **Expose** — `cli.py`, `mcp_server.py`, `context.py`, `bundle.py`,
   `*_export.py` — CLI JSON, MCP tools, context bundles, portable library bundles.

## Where development stands

### Done — MVP (M1–M5, custody-first)

- **M1** refresh-safe sentinel-fenced regeneration (ADR 0102)
- **M2** anti-fabrication / completeness invariant (absence is honest)
- **M3** progressive `context --budget` tiers (index / connected / full)
- **M4** shareable `export/import bundle` custody bundle (ADR 0103)
- **M5** offline dogfood proof — *hold → prove → detect → take it with me*
  (`docs/dogfood.md`)

### Done — Post-MVP themes (all custody-deepening, no new adapters)

- **Per-item / per-source / per-scope custody surface** — fidelity tier, drift
  posture, `last_checked`, recheck coverage, and the `--fidelity`/`--drift` filter
  family across every read/act/export surface (CLI + MCP + compiled `library/`),
  with cross-surface convergence guards.
- **Work-level custody consolidation** — aggregate `custody` block per work +
  at-risk-works alarm on `doctor`/`maintain`/MCP (H261–H271).
- **Conflict-on-import** — detect → read → resolve (`reconcile --keep-held` /
  `--accept-incoming`), durable conflict events (ADR 0104/0105/0106, H272–H283).
- **Archive recovery + un-launderable integrity alarm** — prior-content archive
  travels both transports; `_Archive:_` integrity line everywhere (H280–H321).
- **Explainable ranking & relatedness** — `match_strength`/`relation_strength`
  bands, `--strength` filter, `--stats` tally (H312–H324).
- **Content-identity / near-duplicate custody** — byte-identical holdings under
  different ids; report-only `content_duplicates` across every surface, never an
  auto-merge (H325–H362).
- **Custody posture verdict** (ADR 0107) — `doctor` folds the seven custody audit
  blocks into one whole-library verdict `{sound | attention | at_risk}` + readable
  `_Posture:_` line + cross-run movement, at CLI↔MCP parity (H369–H373).

### Done — forward hardening / contract consolidation (H363 → H425, closed)

With the custody themes closed, this phase was **not a new theme** — it was
cross-surface *convergence & determinism guards* locking the invariants the
themes established. The slices are largely test-only contracts, each an
executable, completeness-asserted invariant with a proven-teeth sabotage:

- Compile determinism (`kb` two-pass + cross-`PYTHONHASHSEED`) — H363
- MCP registry immutability (allow-list, no capture-destroying verbs) — H364
- `doctor --fix` repair convergence (second pass = total no-op) — H365
- `context --budget` strict tier-nesting — H366
- `status` ↔ `doctor` custody-scalar convergence — H367
- `export bundle` determinism + round-trip byte-identity — H368
- CLI↔MCP read/write parity, browse-drill ↔ facet-aggregate ↔ audit convergence,
  preview ↔ live-run parity, bundle-briefing ↔ live-audit convergence,
  append-only ledger, raw-immutability act-surface — H397–H420
- context briefing ↔ live audit alignment (H421), live-act settle parity (H422),
  archive-selector recovery (H423), per-source audit-drill (H424), compiled
  group-page custody-marker convergence (H425).

The through-line: any custody fact must read **identically** across every surface
that carries it (search ≡ list ≡ show ≡ facets ≡ MCP ≡ compiled `library/` ≡
bundle ≡ context), and every generated artifact must be a reproducible,
byte-stable fold — verified, not asserted.

The contract-consolidation queue is **closed through H425** (last slices
landed 2026-07-05). The roadmap's named next lead is an
assessment/recommendation gate — not another guard-cell family.

## Automation & ops

How the H344→H425 span actually shipped (commit dates from git):

- **2026-06-25** — the prior check-in (`../260625/`, HEAD `a7af87e`/H343),
  followed the same day by ~24 more slices (the content-identity closure
  H344–H362 and the posture verdict H369–H373).
- **2026-06-26 → 06-27** — ~47 slices: the contract-consolidation run
  (H388–H419 era), the worker's lock letting single runs overrun through
  whole day-plan slots.
- **2026-07-01 → 07-05** — the tail: H420 (07-01), H421 (07-02),
  H422 (07-03), H423–H425 (07-05).
- **2026-07-05 → 07-22** — no commits on the trunk; the repo sat idle.

Per the autonomous-machine session notes: both Scrolls crons were paused
around 2026-06-27/28 (last hourly finish recorded 2026-06-28) — yet the July
tail still landed, because automated development had been **accidentally
re-enabled** after the pause. In total, 77 H-slice commits landed after the
2026-06-25 check-in with no steering checkpoint (the judgment on this is in
`reconciliation.md`). The crons are paused now.

A checkpoint commit `401ad34` ("chore: add GitHub CI + post-H425 docs
freshness reset", 2026-07-07) exists **only on the autonomous machine's
checkout** — one commit ahead of `origin/work/scrolls-dev`, never pushed. So
the CI workflow has never actually run on GitHub, and that commit is absent
from other clones (including the one this report was written on).

## Health

- ✅ 4370 tests green in ~62s (locally; claimed green on 3.11/3.12/3.13).
- ✅ Working tree clean; this clone tracks `origin/work/scrolls-dev`, up to
  date with the origin tip (`2a5344f`).
- ✅ No new source adapters added recently (correct per vision §2.7 — breadth
  is not the unit of progress; a new adapter needs a genuinely new custody shape).
- ⚠️ The 2026-07-07 CI checkpoint (`401ad34`) is unpushed — GitHub CI has
  never run; "we have CI" is so far a local-only claim.
- ⚠️ Automation idle since 2026-07-05; both crons paused (deliberately, this
  time).

Forward-looking material lives in `plans.md` alongside this report.
