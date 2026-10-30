# Plans — 2026-10-29

**Question this file answers:** with the 2026-07-22 plan reconciled, what
comes next, and how is the work run?

This file is the operative steer. The roadmap's live queue
(`docs/agents/autonomous-roadmap.md`) carries the same slices in order.

## The queue

Ordered by custody value. Each is a GitHub issue with its evidence, scope,
and done-when.

| Slot | Slice | Why now | Issue |
| --- | --- | --- | --- |
| H442 | A cited DOI is not a work identity | The live posture verdict is a false `at_risk`; 185 forged works | #22 |
| H443 | `maintain` is safe to schedule | Nothing has re-verified the library in 66 days | #23 |
| H444 | Saves removed upstream are recorded | ADR 0113's reason to defer no longer holds | #24 |
| H445 | Held document text is searchable | `search` answers "nothing" for held PDF text (M2) | #25 |

**H443 is the 2026-07-22 plan's product-facing slice** (objective 5), chosen
from its three candidates by the evidence: verification is the custody
promise, and the live library shows it lapsing.

## Decisions

- **The hourly worker stays paused.** The working mode is the one that
  produced H426–H441: issue → worktree branch → Codex review loop to zero
  findings → PR → Elijah merges. A cron does not choose slices.
- **The daily 17:00 report is retired.** A check-in in
  `docs/agents/progress/<YYMMDD>/` follows each drained queue instead.
- **Roadmap upkeep happens per queue, not per day.** When the queue drains,
  the closing check-in requeues from evidence or records that nothing
  qualifies (maintenance rule §5).

## Considered and not queued

- **Classify on the collection paths.** `ingest` classifies; `sync
  --collection` does not, so the live library is 0% classified. Not queued:
  the rules engine files every article as `reference` and matches 10 of 482
  posts, so parity buys no custody value. Revisit with the LLM engine, which
  needs a billed key.
- **A first-run sample library, MCP onboarding.** No friction observed yet:
  no agent has used the live library over MCP. Revisit once one does.
- **Bundle archive variant, incremental sidecars** (ADR 0115), **an
  `--all-profiles` cookie sweep** (ADR 0108), **OCR** (ADR 0114). Deferred
  with no evidence of need.
- **More guard-cell matrices.** Retired as a default (2026-07-22); H244–H249
  pruned from the backlog.

## After the queue

Run the closing check-in: re-read the live library, record the posture
change H442 should produce (`at_risk` → `attention`), and requeue only from
what that pass surfaces.
