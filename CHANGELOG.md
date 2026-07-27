# Automation Changelog

Short, append-only reports from automation and agent-authored work on `work/scrolls-dev`.

Each autonomous run or agent slice should append one entry roughly the size of a git commit message:

```markdown
- YYYY-MM-DD — type: concise summary of the work; include blocker if no change landed.
```

## Entries

- 2026-06-18 — docs: add AGENTS.md and automation changelog reporting convention.
- 2026-06-18 — docs: grill and expand AGENTS.md with custody-first agent workflow.
- 2026-07-01 — test: add H420 truncation/scope-echo honesty contract and fix uv toolchain availability.
- 2026-07-01 — fix: align context custody briefing with live audit and add H421 convergence contract.
- 2026-07-03 — fix: add H422 live-act settle parity and suppress duplicate open-conflict ledger appends.
- 2026-07-05 — feat: add H423 archive-selector recovery convergence and versioned archive show selectors.
- 2026-07-05 — test: add H424 per-source scoped audit-drill convergence contract.
- 2026-07-05 — test: add H425 compiled group-page custody-marker convergence contract.
- 2026-07-26 — docs: consolidate inspiration into docs/inspiration/, merge the vision docs into a single docs/vision.md, scrub scattered lineage references to pointers, and restructure dev check-ins under docs/agents/progress/<YYMMDD>/.
- 2026-07-26 — docs: amend the ADRs to the consolidated doc paths and remove the transition stubs.
- 2026-07-26 — docs: realign the dev check-ins — backfill the reconstructed 2026-06-25 check-in and fold the accidental automation re-enable, ops stall, and release/dogfood pivot into the 2026-07-22 check-in.
- 2026-07-26 — docs: complete the inspiration moves as full cuts — the former IDEAS.md lineage portions now live only in docs/inspiration/, and CLAUDE.md/AGENTS.md no longer restate its ground rules or checkout paths.
- 2026-07-26 — docs: move the 2026-06-25 status snapshot and 3-day/week plans out of the roadmap into docs/agents/progress/260625/ as full cuts; retarget the roadmap's internal references.
- 2026-07-27 — docs: restructure the wall-of-text docs for human readability — per-adapter sections in adapters.md, bulleted prose in cli.md/dogfood.md/library-format.md, the roadmap queue folded to the one-line ledger (queue now empty), reconciliation.md de-accreted into a per-capability contract record; doc-style rule added to the agent guides.
