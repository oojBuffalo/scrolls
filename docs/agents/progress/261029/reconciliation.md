# Reconciliation — 2026-10-29

**Question this file answers:** did development match the 2026-07-22 plan
(`../260722/plans.md`)? Judged against `docs/vision.md` and the PRD, with
`report.md` alongside as the facts.

## Verdict

The plan's *direction* held: evidence from use replaced guard-cell matrices,
and every slice traces to friction met on a real library. Its *process*
items slipped: the roadmap maintenance pass came three months late, and one
regression from the capture work went unnoticed until this pass.

## The 2026-07-22 objectives

| # | Objective | Outcome |
| --- | --- | --- |
| 1 | Unstick the branch; CI green on GitHub | **Done** — CI as `324da9c` (#7), green on the trunk tip |
| 2 | Keep the hourly H-number factory paused | **Held** — no worker runs |
| 3 | Real dogfood pass | **Done, live** — H432/H433 on the real library, not a throwaway |
| 4 | Issues from friction | **Done** — #9–#13, all closed |
| 5 | One product-facing slice | **Not done** — the collection on-ramp absorbed the period |
| 6 | Next custody-deepening theme (cap 8) | **Moot** — cap 8 provenance was already shipped (H20–H28) |
| 7 | Resume the daily report | **Not done** — superseded, see `plans.md` |
| 8 | Collection on-ramp (issue #2) | **Done** — ADRs 0108, 0109, 0113 |
| — | 7-day: roadmap maintenance pass | **Late** — done in this check-in |
| — | 7-day: decide automation restart | **Late** — decided in `plans.md` |

## Deviations and corrections

1. **A capture slice broke work identity, unseen for two months.** ADR 0110
   (2026-08-18) gave Wikipedia articles their citation links. `works`
   already read any `doi.org` link as identity (ADR 0069), so 185 false
   works formed and the posture verdict turned `at_risk`. Fixture tests
   could not see it: no fixture held a non-paper item linking a DOI.
   **Correction:** H442 (#22), first in the queue.

2. **The ledger re-accreted and broke.** Rows H426–H441 grew to paragraph
   length, and ten of them were appended *after* the maintenance-rule
   section, outside the table. **Correction (applied):** re-compacted to
   one line each and moved back into the table.

3. **The queue sat "superseded" for three months.** Issues steered the work
   instead, which was fine, but the roadmap stopped saying what was next.
   **Correction (applied):** requeued H442–H445, each backed by an issue.

4. **Verification became a one-off.** The live library was verified once,
   on 2026-08-23, and never again. A custody system that verifies only when
   someone remembers is not stewardship. **Correction:** H443 (#23).

5. **Two deferrals rested on premises that no longer hold.** ADR 0113
   deferred "unsaved upstream" because it would need a full walk, yet every
   unlimited sync already walks everything. ADR 0114 deferred document
   search, leaving `search` silent on held text. **Corrections:** H444
   (#24), H445 (#25).

6. **No product-direction correction needed.** Nothing shipped contradicts
   the custody vision. The one new adapter (`x`, H433) introduced a new
   custody shape — verifying a capture-at-pull collection — as §2.7 requires.
