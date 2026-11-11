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
- 2026-07-27 — docs: rename docs/reconciliation.md to docs/conflicts.md to end the name collision with the check-in reconciliation.md files; all referrers retargeted.
- 2026-10-03 — feat: settle the collection on-ramp contract (ADR 0113, issue #2) — saved collections are declared once in saved_collections.py and pulled through one `scrolls sync <source> --collection <name>` loop; --bookmarks/--reading-lists kept as aliases, --list-collections answers honestly when a source has none, and naming two collections (including a repeated --collection) is refused before any pull.
- 2026-10-22 — refactor: remove the Field Theory runtime dependency (issue #5) — `scrolls import fieldtheory` and `fieldtheory.py` deleted outright, the cli.md demo re-seeded on the native X sync's row shape, ADR 0009 amended as history and the inspiration doc moved to past-tense lineage.
- 2026-10-22 — docs: audit every adapter against the collection-import principle (issue #3) — a Collections verdict per adapter plus an at-a-glance table (4 reachable, 22 gap, 16 none), the adapter contract now requires it, and a docs test keeps the catalog, table, counts and collection registry in step.
- 2026-10-22 — feat: read captured PDFs into the scroll (ADR 0114, issue #10) — `scrolls media` reads every held PDF through the shared pypdf seam, backfills from disk, and the scroll renders a `## Documents` section; read, empty, and unread stay distinct.
- 2026-10-22 — feat: carry a bundle's media in an opt-in sidecar (ADR 0115, issue #12) — `export bundle --with-media DIR` writes the in-scope files with a SHA-256 manifest beside an unchanged bundle; `import bundle` adopts them hash-checked, never overwriting, and reports a `media` block.
- 2026-10-29 — docs: roadmap maintenance pass; 261029 check-in, ledger H426–H441 re-compacted into the table, queue requeued as H442–H445 (#22–#25).
- 2026-10-29 — fix: a cited DOI is not a work identity (ADR 0116, issue #22) — only scholarly-record sources' `doi.org` links join a work; on a copy of the live library 185 Wikipedia-only works drop to 0 and the posture verdict from `at_risk` to `attention`.
- 2026-10-29 — feat: make `scrolls maintain` safe to schedule (ADR 0117, issue #23) — one pass at a time under an `flock` run lock (a second pass skips with exit 75 and names the holder; a killed pass never wedges the schedule), plus a daily launchd/cron recipe in docs/dogfood.md.
