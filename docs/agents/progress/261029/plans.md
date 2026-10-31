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
| H443 | `maintain` is safe to schedule | Nothing has re-verified the library since 2026-08-25 | #23 |
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
  qualifies (maintenance rule §5). Rules 1–2 now say the same.

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

*Closing pass, 2026-10-29: all four slices shipped, each through the Codex
review loop to zero findings.*

What each changed, measured on a copy of the live library:

| Slot | Result |
| --- | --- |
| H442 | Works 185 → 0; posture `at_risk` → `attention` (`source_drift` only) |
| H443 | A pass started during a running one was refused, exit 75, holder named |
| H444 | Fixture-proven only; a live pull needs the browser session (below) |
| H445 | Schema 8 → 9 on a v8 copy; a word only in the CIA PDF is found |

**The live library is already on schema 9.** Three `detect` tests called
`main()` with no `$SCROLLS_HOME`, so the H445 suite run upgraded
`~/.scrolls` itself. The result matches the reviewed migration of a v8 copy
taken before that run: DDL, all 1,048 rows, FTS integrity. `tests/conftest.py`
now gives every test its own library. Until the stack merges and the main
checkout pulls, trunk `scrolls` refuses the library as newer than it
supports.

**Two steps that turn shipped slices into live custody.** Elijah approved
both on 2026-10-30, and both feed the next check-in:

- **`maintain` is scheduled.** The `docs/dogfood.md` launchd recipe is
  installed as `dev.scrolls.maintain`: daily at 04:00, `--limit 200`,
  against the main checkout. Its first pass met the schema-9 library on
  trunk code and stopped before writing; it runs once the merge is pulled.
  Nothing has re-verified the live library since 2026-08-25.
- **One live collection pull on a copy** still needs the browser session,
  which the agent sandbox cannot read. H444's comparison has never met real
  X or MediaWiki responses. One `sync --collection` per source on a copied
  `SCROLLS_HOME` shows whether real walks come back `complete` with no
  unidentified entries.

**Observed this queue, not queued:**

- **An unreadable browser directory crashes `sync`** with a raw
  `PermissionError` instead of the typed "no session" envelope. Seen only
  under the agent sandbox so far.
- **A `.pdf` link that serves a JPEG** (Dystonia) is read as an unreadable
  document. Honest, but media typing could check the bytes.
- **The first account-scoped walk is a baseline**, so removals made before
  it are not recovered (ADR 0118). Nothing to build; worth knowing.

The next queue is cut at the next check-in, from what the scheduled passes
and the live pull surface.
