# Scrolls Agent Guide

Scrolls is a local-first CLI/project for turning saved internet artifacts into an agent-readable knowledge library.

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

**Primary north star:** Read `docs/agents/vision.md` first. It defines the first-principles product vision synthesized from Scrolls and last30days-skill. The operative, most-current north star is `docs/custody-vision.md` (custody-first synthesis, 2026-06-15); `docs/vision.md` and `docs/agents/vision.md` are the earlier syntheses it sharpens. All autonomous decisions must be justified against the custody vision.

Secondary references: `docs/agents/last30days-inspiration.md` and `docs/agents/obsidian-second-brain-inspiration.md` (specific patterns to adapt) and `docs/agents/domain.md`.

**Product direction:** `docs/product/prd.md` (inspiration-backed direction), `docs/product/mvp.md` (near-term coherent scope), and `docs/agents/autonomous-roadmap.md` (the hour/day/week buffer the hourly worker should follow). Read these to pick the next coherent slice.

### Last30Days inspiration

Use `/Users/claw/.hermes/gh-repos/last30days-skill` as a reference checkout for inspiration only. Adapt its patterns to Scrolls' local-first library model: agent-facing contracts, multi-source fanout with graceful degradation, evidence clustering/dedupe, signal-aware ranking, shareable artifacts, fixtures/evals, and dogfood workflows. Do not copy secrets, vendored code, or implementation details blindly.

### Obsidian Second Brain inspiration

Use `/Users/claw/.hermes/gh-repos/obsidian-second-brain` (GitHub: `eugeniughelbur/obsidian-second-brain`) as a reference checkout for inspiration only. Adopt **mechanisms, not its self-mutating-vault philosophy**: Scrolls rejects "the vault rewrites itself" / auto-overwriting reconciliation because it violates custody (raw is sacred; drift is a recorded event, never an overwrite). Adopt refresh-safe sentinel-fenced regeneration of generated artifacts, anti-fabrication/search-completeness as a tested contract, progressive context budgets, portable custody bundles, and scheduled custody maintenance. See `docs/agents/obsidian-second-brain-inspiration.md` and ADR 0102 for the full adopt/adapt/reject mapping. Do not copy secrets, vendored code, or implementation details blindly.

## Development process

Use these practices for substantive work:

- `/grill-me-docs`: Before a design or implementation slice, self-grill the plan against this repo's documented decisions and terminology (the docs-aware grill; installed as `grill-with-docs`). Because hourly automation is unattended, answer the questions yourself using repo context and document important assumptions in the commit message, issue, PRD, ADR, or source comments.
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

Current autonomous priority (from vision.md): deep works merge, explainable ranking & confidence, evidence clustering, MCP/search/list consistency, doctor/repair, lossless export/import + shareable bundles, threaded rendering, fixtures/evals, and dogfood workflows. New adapters only when they validate a broader abstraction.

The goal is not to check a box once the hourly automation fires. A run should complete an isolated feature, vertical slice, schema/module, CLI path, adapter, test-backed behavior, or decision-grade architecture step that future runs can build on without first finishing half-done work.

If a meaningful slice takes longer than an hour, keep going. The automation lock makes later cron ticks skip rather than overlap. Stop when the slice is finished, verified, committed, pushed, and clean — not when an arbitrary time threshold is hit. Conversely, if a first slice finishes very quickly and there is obvious adjacent work, continue to another adjacent slice or deepen tests, verification, and integration instead of ending the run early.

Avoid trivial progress: typo-only edits, README reshuffling, formatting-only churn, isolated TODO lists, vague "future work" docs, or issues with no implementation path. If a run cannot make meaningful progress, report the blocker rather than manufacturing a trivial commit.

## Safety

- Do not commit secrets.
- Do not force-push unless explicitly instructed by the user.
- Do not rewrite `main` history, and do not touch repository `main` beyond fetch/compare operations unless Elijah explicitly asks.
- Do not let multiple agents write the same checkout at the same time.
- If a tool, install, auth, or network failure blocks useful progress, stop and report the blocker rather than fabricating results.
