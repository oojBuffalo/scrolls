# Scrolls Agent Guide

*Amended: 2026-07-26 — vision, inspiration, and priority pointers consolidated
(see `docs/vision.md` and `docs/inspiration/`). 2026-07-27 — doc-style rule
added. 2026-08-24 — browser-session-first rule for reaching online accounts
added.*

Scrolls is a local-first custody system for saved internet artifacts: it holds
what you deliberately saved, proves what was captured, surfaces drift honestly,
and exports losslessly.

Core flow:

```text
Sources → Items → Scrolls → Library → Agents
```

See `README.md`, `docs/architecture.md`, and `IDEAS.md` before making architectural or implementation changes.

## Development commands

Python ≥3.11 + uv, src layout (see `docs/adr/0001-implementation-stack.md`):

```bash
uv run pytest          # run the test suite
uv run scrolls --help  # run the CLI from source
```

## Current working branch

The autonomous work happens on `work/scrolls-dev`, or branches/worktrees created from it. Treat `work/scrolls-dev` as the agents' main/integration trunk. Keep repository `main` stable and do not open PRs to `main` or merge into `main` unless Elijah explicitly asks.

Before editing:

```bash
git status --short --branch
git pull --ff-only
```

After a useful slice:

```bash
git status --short
git diff --stat
git add <changed-files>
git commit -m "type: concise subject"
git push
```

Commit types: `docs:`, `feat:`, `fix:`, `test:`, `refactor:`, `chore:`.

## Agent skills

Matt Pocock's skills are installed in `~/.claude/skills`.

### Issue tracker

GitHub Issues are the default issue tracker for this repo. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default Matt Pocock triage vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context project. Use this `CLAUDE.md`, root `README.md`, `docs/architecture.md`, root `IDEAS.md`, and the `docs/adr/` records (indexed at `docs/adr/README.md`). See `docs/agents/domain.md` for the reading order.

**Primary north star:** Read `docs/vision.md` first — the custody-first synthesis (original 2026-06-15; the three vision documents were merged into it 2026-07-26). All autonomous decisions must be justified against it.

Secondary references: `docs/inspiration/` (the adopt/adapt/reject mappings per inspiration source) and `docs/agents/domain.md`.

**Product direction:** `docs/product/prd.md` (direction), `docs/product/mvp.md` (shipped near-term scope), `docs/agents/autonomous-roadmap.md` (the queue the hourly worker follows), and the latest `docs/agents/progress/` check-in (`report.md` facts, `reconciliation.md` deviations, `plans.md` steering). Read these to pick the next coherent slice.

### Inspiration sources

All inspiration/lineage material — the per-source adopt/adapt/reject
mappings, the ground rules, and the reference-checkout paths — lives in
`docs/inspiration/` (start at its `README.md`).

## Development process

Use these practices for substantive work:

- `/grill-me-docs`: Before a design or implementation slice, self-grill the plan against this repo's documented decisions and terminology (the docs-aware grill; installed as `grill-with-docs`). Because hourly automation is unattended, answer the questions yourself using repo context and document important assumptions in the commit message, issue, PRD, ADR, or source comments.
- `/tdd`: Prefer red-green-refactor for code changes once implementation starts.
- `/diagnose`: Use a disciplined reproduce/minimize/hypothesize/instrument/fix loop for bugs.
- `/improve-codebase-architecture`: Periodically look for opportunities to deepen modules and simplify interfaces.
- `/zoom-out`: Use when changing an unfamiliar area to preserve whole-system coherence.

### Doc style

Docs are read by humans first. Verbose is fine; walls of text are not: short
paragraphs (roughly six lines max), bullets with bold lead-ins for
enumerations, tables for catalogs, no multi-line parenthetical asides. Shipped
facts go to the roadmap's one-line ledger; dated narration goes to
`docs/agents/progress/<YYMMDD>/`; design docs state the current contract and
leave slice-by-slice history to git.

## Reaching an online account

**The logged-in browser session is the primary route. Always.** Any capability
that reaches a user's account borrows the session already sitting in their
browser, the way `fieldtheory-cli` does. Stored credentials — OAuth grants, API
keys, tokens — are a **secondary, optional** fallback, never the default and
never required.

This is a standing architectural constraint across the whole repository, not a
per-adapter preference. It binds new sources, new sync shapes, and re-fetch or
verify paths just as much as first capture.

**Why:** it avoids storing credentials at all, and many platforms either do not
support third-party API use or do not hand out API keys. Requiring a developer
account makes the on-ramp cost money and locks out every platform without a
public API.

Applying it:

- **Route it through `browser_cookies.py`** with a per-service `CookieSpec`
  (hosts, required cookie names, login URL). That module is already generic —
  do not write a second cookie reader.
- **Keep credential paths behind an explicit opt-in flag**, the shape
  `scrolls sync x --auth oauth` already uses, and document them as optional and
  (where true) billed.
- **An anonymous public endpoint is not a substitute.** It is a *different*
  surface that sees less than the signed-in user does. Rejected on exactly
  those grounds while designing the `x` fetch adapter (ADR 0108): a keyless CDN
  cannot see a protected account you follow, so a re-capture through it would
  report drift that never happened.
- **Env-var cookie overrides** (`SCROLLS_X_AUTH_TOKEN` / `SCROLLS_X_CT0`) are
  part of the primary route, not the secondary one — the same session, pasted.

## Project decision posture

The user has authorized autonomous, practical decisions on architecture, design, and implementation for this branch. Make decisions that are:

1. grounded in `IDEAS.md` and observed code/repo state,
2. simple enough to revise,
3. documented when consequential,
4. verified with tests or concrete command output when possible.

Prefer small vertical slices over broad rewrites, but each autonomous run should do real work until it reaches a natural, coherent stopping point.

Current autonomous priority: follow the `docs/agents/autonomous-roadmap.md` queue, steered by the latest `docs/agents/progress/` check-in's `plans.md`. New adapters only when they introduce a genuinely new custody shape (vision §2.7).

The goal is not to check a box once the hourly automation fires. A run should complete an isolated feature, vertical slice, schema/module, CLI path, adapter, test-backed behavior, or decision-grade architecture step that future runs can build on without first finishing half-done work.

If a meaningful slice takes longer than an hour, keep going. The automation lock makes later cron ticks skip rather than overlap. Stop when the slice is finished, verified, committed, pushed, and clean — not when an arbitrary time threshold is hit. Conversely, if a first slice finishes very quickly and there is obvious adjacent work, continue to another adjacent slice or deepen tests, verification, and integration instead of ending the run early.

Avoid trivial progress: typo-only edits, README reshuffling, formatting-only churn, isolated TODO lists, vague "future work" docs, or issues with no implementation path. If a run cannot make meaningful progress, report the blocker rather than manufacturing a trivial commit.

## Safety

- Do not commit secrets.
- Do not change the operative vision (`docs/vision.md`) without explicit human approval.
- Do not force-push unless explicitly instructed by the user.
- Do not rewrite `main` history, and do not touch repository `main` beyond fetch/compare operations unless Elijah explicitly asks.
- Do not let multiple agents write the same checkout at the same time.
- If a tool, install, auth, or network failure blocks useful progress, stop and report the blocker rather than fabricating results.
