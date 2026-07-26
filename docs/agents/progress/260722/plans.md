# Plans — 2026-07-22

**Question this file answers:** with the codebase and goals reconciled
(`reconciliation.md`), what are the next goals/objectives — as logical items,
detached from timelines — and what is a reasonable 1/3/7-day plan?

*Agent-drafted 2026-07-26, pending Elijah's review; rewritten the same day to
fold in the 2026-07-20 autonomous-machine reassessment. This file — not the
roadmap's un-started guard-cell queue — is the operative steer: Scrolls is
**post-custody-spine, post-contract-consolidation, early release/dogfood
phase**. More H426-style guard matrices are explicitly the wrong default; the
roadmap queue stands superseded pending its next maintenance pass.*

## Next objectives (logical items, no timelines)

1. **Unstick the branch.** Review and push the autonomous machine's
   checkpoint commit `401ad34` ("chore: add GitHub CI + post-H425 docs
   freshness reset") and confirm the CI workflow actually runs green on
   GitHub. Local "we have CI" is not remote verification.
2. **Keep the hourly H-number factory paused.** Do not restart the hourly
   worker on the guard-cell prompt; restart — if at all — only with a
   non-guard-cell, evidence-driven prompt after the objectives below.
3. **Real dogfood.** On a throwaway `SCROLLS_HOME`: `scrolls init` → ingest
   a few live URLs → `scrolls kb` → `scrolls doctor` → `scrolls context` →
   `scrolls export bundle` → import into a second library. Evidence from
   *use*, not another invariant family.
4. **Issue backlog from friction.** Turn what the dogfood pass surfaces into
   3–5 GitHub issues (onboarding, CLI noise, MCP setup, live-source honesty).
5. **One product-facing slice, chosen by that evidence** — a first-run
   sample/quickstart library, or the MCP agent onboarding path, or an
   operational `scrolls maintain` recipe / safe cron. One of these, not all.
6. **Only after that: the next custody-deepening theme.** Cap-8-style
   enrichment provenance remains the right *eventual* depth theme unless
   dogfood surfaces something sharper — it does not jump the queue ahead of
   "can a cold user/agent trust and use this without reading the ADRs?"
7. **Resume the daily 17:00 progress report** only after the push and the
   first dogfood pass, so it reports release/dogfood movement rather than
   H-slice theater.

## 1-day plan

- Land the 2026-07-26 docs branch onto `work/scrolls-dev` (user-side merge;
  the repo hook blocks agent pushes).
- Push `401ad34` from the autonomous machine; watch the GitHub CI run and
  get it green (3.11/3.12/3.13).

## 3-day plan

- The full dogfood pass (objective 3), with captured output.
- File the 3–5 friction issues (objective 4).
- Pick the one product-facing slice (objective 5) from that evidence.

## 7-day plan

- Ship the chosen product-facing slice — test-backed, contract docs updated
  in the same commit.
- Run the roadmap maintenance pass: sync its status snapshot to this
  check-in, prune the superseded guard-cell queue, and requeue against these
  objectives.
- Decide the automation-restart question explicitly (prompt, cadence, scope)
  rather than letting a cron decide it.
