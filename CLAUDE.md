# Scrolls Agent Guide

Scrolls is a local-first CLI/project for turning saved internet artifacts into an agent-readable knowledge library.

Core flow:

```text
Sources → Items → Scrolls → Library → Agents
```

See `README.md` and `IDEAS.md` before making architectural or implementation changes.

## Development commands

Python ≥3.11 + uv, src layout (see `docs/adr/0001-implementation-stack.md`):

```bash
uv run pytest          # run the test suite
uv run scrolls --help  # run the CLI from source
```

## Current working branch

The autonomous hourly work happens on `work/scrolls-dev`, or branches/worktrees created from it. Keep `main` stable.

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

This is a single-context project. Use this `CLAUDE.md`, root `README.md`, root `IDEAS.md`, and future `docs/adr/` records. See `docs/agents/domain.md`.

## Development process

Use these practices for substantive work:

- `/grill-me`: Before a design or implementation slice, self-grill the plan. Because hourly automation is unattended, answer the questions yourself using repo context and document important assumptions in the commit message, issue, PRD, ADR, or source comments.
- `/tdd`: Prefer red-green-refactor for code changes once implementation starts.
- `/diagnose`: Use a disciplined reproduce/minimize/hypothesize/instrument/fix loop for bugs.
- `/improve-codebase-architecture`: Periodically look for opportunities to deepen modules and simplify interfaces.
- `/zoom-out`: Use when changing an unfamiliar area to preserve whole-system coherence.

## Project decision posture

The user has authorized autonomous, practical decisions on architecture, design, and implementation for this branch. Make decisions that are:

1. grounded in `IDEAS.md` and observed code/repo state,
2. simple enough to revise,
3. documented when consequential,
4. verified with tests or concrete command output when possible.

Prefer small vertical slices over broad rewrites, but each autonomous run should do real work until it reaches a natural, coherent stopping point.

The goal is not to check a box once the hourly automation fires. A run should complete an isolated feature, vertical slice, schema/module, CLI path, adapter, test-backed behavior, or decision-grade architecture step that future runs can build on without first finishing half-done work.

If a meaningful slice takes longer than an hour, keep going. The automation lock makes later cron ticks skip rather than overlap. Stop when the slice is finished, verified, committed, pushed, and clean — not when an arbitrary time threshold is hit. Conversely, if a first slice finishes very quickly and there is obvious adjacent work, continue to another adjacent slice or deepen tests, verification, and integration instead of ending the run early.

Avoid trivial progress: typo-only edits, README reshuffling, formatting-only churn, isolated TODO lists, vague "future work" docs, or issues with no implementation path. If a run cannot make meaningful progress, report the blocker rather than manufacturing a trivial commit.

## Safety

- Do not commit secrets.
- Do not force-push unless explicitly instructed by the user.
- Do not rewrite `main` history.
- Do not let multiple agents write the same checkout at the same time.
- If a tool, install, auth, or network failure blocks useful progress, stop and report the blocker rather than fabricating results.
