# Progress Report — 2026-10-29

**Date:** 2026-10-29
**Branch:** `work/scrolls-dev` (agent trunk) — HEAD `e271186`, 593 commits ahead of `main`
**Slice series:** through **H441**
**Suite:** 4663 tests passing (~101s, `uv run pytest -q`), network blocked

This is a **facts-only** report. The judgment lives beside it:
`reconciliation.md` (did the 2026-07-22 plan happen?) and `plans.md` (what
next). Per-slice detail is in git and the roadmap's shipped ledger.

## Codebase shape

| Area | Size | Δ since 2026-07-22 |
| --- | --- | --- |
| Source (`src/scrolls`) | 101 files, ~41.8k LOC | +11 files, +4.9k LOC |
| Tests (`tests/`) | 140 files, ~96.3k LOC | +14 files, +4.9k LOC |
| ADRs (`docs/adr`) | through 0115 | +8 (0108–0115) |
| Fetch adapters (`FETCH_ADAPTERS`) | 40 | `x` added (H433) |
| Saved collections (`COLLECTIONS`) | 2 | new (ADR 0113) |

## What shipped (H426 → H441)

All sixteen slices came from using the tool on a real library, not from the
guard-cell queue.

| Theme | Slices | ADRs |
| --- | --- | --- |
| **Collection on-ramp** — pull what a user saved in another service | H426, H427, H437, H438, H439 | 0108, 0109, 0113 |
| **Wikipedia capture depth** — links, figures, math, media limits | H428–H431, H436 | 0110, 0111, 0112 |
| **Live dogfood** — whole-library verify, X fetch adapter | H432, H433 | — |
| **Ops** — bulk re-render, network-blocked suite, GitHub CI | H434, H435, #7 | — |
| **Take it with me** — PDF text, bundle media sidecar | H440, H441 | 0114, 0115 |

Issues #2–#13 are all closed. PRs #17–#21 merged 2026-10-24 as a stack.

## The live library (`~/.scrolls`)

Read 2026-10-29, offline (`scrolls status`, and a copy for the rest).

| Fact | Value |
| --- | --- |
| Items | 1,048 — 566 Wikipedia, 482 X |
| Fidelity | 1,048 full |
| Last verified | Wikipedia 2026-08-23, X 2026-08-25 (ledger, UTC); nothing since |
| Drift | 993 unchanged, 55 drifted (all Wikipedia), 0 rotted |
| Posture | `at_risk` — `at_risk_works`, `source_drift` |
| Works (≥2 representations) | 185, every one Wikipedia-only |
| Classified | 0 of 1,048 |
| Compiled `library/`, `agents/` | never built (empty) |
| PDFs on disk | 3, none read yet |

**The works figure is wrong.** Every one of the 185 works is a set of
Wikipedia articles that *cite* the same paper. `works.item_dois` reads any
`doi.org` link as identity, and since ADR 0110 an article carries its
citations as links. So the `at_risk` verdict is a false alarm (issue #22).

**Classification adds little here.** On a copy, the rules engine filed all
566 articles as `reference` and left 472 of 482 posts unmatched.

## Automation & ops

- **The hourly worker stayed paused** the whole period. Work moved to a
  human-steered loop: issue → branch → Codex review to zero findings → PR →
  Elijah merges.
- **GitHub CI is live.** It runs pytest on 3.11/3.12/3.13. The trunk tip
  `e271186` is green; the four runs before it were cancelled as superseded
  by the stack merge.
- **The CI checkpoint `401ad34`** from the autonomous machine was never
  pushed. CI landed instead as `324da9c` (#7).
- **The daily 17:00 report** was not resumed.
