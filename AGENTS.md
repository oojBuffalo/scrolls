# Scrolls Agent Guide

Scrolls is a local-first custody system for saved internet artifacts. Its job is
to hold what a person deliberately saved, prove what was held at capture time,
surface drift/rot honestly, and export the library losslessly.

Core flow:

```text
Sources → Items → Scrolls → Library → Agents
```

Use this file as the default, tool-agnostic agent entrypoint. `CLAUDE.md`
carries the same project norms for Claude-specific environments; keep the two
aligned when changing durable agent instructions.

## Non-negotiable product posture

- **Custody, not discovery.** Retrieval, search, ranking, and summaries are
  conveniences over material the user already chose to keep. Do not steer the
  project toward open-web discovery as the primary product.
- **Raw is sacred.** Raw capture, content hashes, source response/provenance, and
  custody events are the root of trust. Derived views are rebuildable.
- **Drift is an event, not an overwrite.** Re-fetch disagreements should be
  recorded and reported; never silently clobber the stored capture.
- **Fidelity must travel with results.** CLI JSON, MCP tools, scroll
  frontmatter, `library/` pages, and bundles should expose enough scope,
  provenance, and fidelity for agents to know what they can trust.
- **Adapters are commodity.** Add a new adapter only when it exercises a new
  custody shape: a new fidelity boundary, identity rule, canonical/threaded
  structure, or export/import concern.
- **If an agent cannot run it unattended, it is not done.** Prefer fixture-backed
  vertical slices that can be verified by commands over prose-only progress.

## Required context reading

For trivial edits, read the touched file plus nearby docs. For architectural,
CLI, data-model, adapter, MCP, custody, or automation changes, read the relevant
docs before editing.

Start with the reading order in `docs/agents/domain.md`:

1. `README.md` — public framing and current command surface.
2. `docs/architecture.md` — pipeline stages, module map, data model, and source
   adapter contract.
3. `docs/cli.md` — CLI JSON/output contract, exit codes, and error envelopes.
4. `docs/library-format.md` — scroll, `library/`, agent-doc, and media artifact
   contracts.
5. `docs/adr/README.md` and the relevant ADRs.
6. `docs/custody-vision.md` — operative north star; this outranks older vision
   docs when they differ.
7. `docs/product/prd.md`, `docs/product/mvp.md`, and
   `docs/agents/autonomous-roadmap.md`.
8. `docs/agents/last30days-inspiration.md` and
   `docs/agents/obsidian-second-brain-inspiration.md` for adopt/adapt/reject
   mappings.
9. `IDEAS.md` — brainstorm and backlog; not everything in it exists yet.

When a slice changes the pipeline, adapter contract, or data model, update
`docs/architecture.md`. When it changes command arguments, output keys, or exit
codes, update `docs/cli.md`. When it changes scroll frontmatter, body sections,
compiled `library/` pages, generated agent docs, or media artifacts, update
`docs/library-format.md`. Consequential decisions should get an ADR.

## `/grill-me-docs` checklist

Before a substantive design or implementation slice, self-grill the plan against
the docs. Answer these in your own notes, commit message, PR/issue body, ADR, or
source comments as appropriate:

1. **Custody fit:** Which custody-vision principle does this strengthen? Does it
   preserve raw capture as the source of truth?
2. **Scope honesty:** Could an agent mistake a filtered, truncated, stale, or
   unverified result for a complete answer? If so, add scope/provenance/fidelity
   fields or wording.
3. **Regenerability:** Is any derived artifact gaining non-regenerable state? If
   yes, either move that state to the canonical model or protect user-authored
   regions with the documented sentinel-fence pattern.
4. **Surface consistency:** Do CLI, MCP, scroll files, `library/` pages, exports,
   and tests agree semantically? Avoid one-off behavior on a single surface.
5. **Adapter discipline:** If adding or extending a source, what new custody
   shape justifies it beyond breadth?
6. **Verification:** Which fixture, invariant test, CLI sample, or dogfood flow
   proves the claim? Do not rely on assertion-only documentation.
7. **Docs impact:** Which contract docs or ADRs must change in the same slice?
8. **Exit path:** Does export/import or bundle behavior remain lossless for the
   model-complete fields?

## Development commands

Python ≥3.11 + uv, src layout:

```bash
uv run pytest          # run the full test suite
uv run scrolls --help  # run the CLI from source
```

Use narrower tests while iterating, then run the relevant broader command before
reporting completion. For CLI/MCP contract changes, capture concrete command
output or fixture-backed tests.

## Branch and git workflow

Autonomous work happens on `work/scrolls-dev`, or on branches/worktrees created
from it. Treat `work/scrolls-dev` as the agents' integration trunk. Keep
repository `main` stable; do not open PRs to `main`, merge into `main`, or
rewrite `main` history unless Elijah explicitly asks.

Before editing:

```bash
git status --short --branch
git pull --ff-only
```

Do not let multiple agents write the same checkout at the same time. If the
checkout is dirty with changes you did not make, stop and identify the owner
instead of overwriting them.

After a useful autonomous slice, agents with commit/push authority should:

```bash
git status --short
git diff --stat
git add <changed-files>
git commit -m "type: concise subject"
git push
```

Commit types: `docs:`, `feat:`, `fix:`, `test:`, `refactor:`, `chore:`.

Ad-hoc coding assistants should not commit or push unless the user or runner
explicitly grants that authority.

## Required automation report

At the end of every autonomous run or agent-authored slice, append one short
entry to `CHANGELOG.md` summarizing what changed or what was attempted. Keep it
roughly git-commit-message sized.

Use this format:

```markdown
- YYYY-MM-DD — type: concise summary of the work; include blocker if no change landed.
```

Examples:

```markdown
- 2026-06-18 — feat: add source-scoped custody health to MCP get_library_health.
- 2026-06-18 — blocked: skipped feature work because the checkout was dirty.
```

## Issue tracker and labels

GitHub Issues are the default issue tracker for this repo. See
`docs/agents/issue-tracker.md`.

Use the default Matt Pocock triage vocabulary. See
`docs/agents/triage-labels.md`.

## Reference checkouts

- Last30Days inspiration: `/Users/claw/.hermes/gh-repos/last30days-skill`
- Obsidian Second Brain inspiration:
  `/Users/claw/.hermes/gh-repos/obsidian-second-brain`

Use these for mechanisms and patterns only. Do not copy secrets, vendored code,
or implementation details blindly. Scrolls explicitly rejects the
self-mutating-vault philosophy: generated views may refresh, but raw artifacts
and user-authored regions must not be silently rewritten.

## Development process

- Prefer small vertical slices over broad rewrites.
- Prefer red-green-refactor for code changes: failing test or reproduced symptom
  first, smallest implementation, then cleanup.
- Use a disciplined reproduce/minimize/hypothesize/instrument/fix loop for bugs.
- Periodically simplify interfaces and deepen modules, but avoid drive-by
  refactors unrelated to the slice.
- Preserve whole-system coherence when changing unfamiliar areas; trace symbols
  to definitions and usages before editing.
- Do not invent imports, files, symbols, or APIs. Inspect the repo and manifests.

Current autonomous priority: finish and harden custody-depth work before breadth:
deep works merge, explainable ranking/confidence, evidence clustering,
MCP/search/list consistency, doctor/repair, lossless export/import plus
shareable bundles, threaded rendering, fixtures/evals, and dogfood workflows.

## Verification expectations

- Meaningful code changes need relevant tests, linters, build checks, or CLI
  commands before reporting success.
- Contract changes need docs and tests in the same slice.
- Fixture-backed invariants are preferred over live-network assertions.
- If a full suite is too expensive for the current runner, state the narrower
  verification performed and why it is sufficient or what remains unverified.
- Do not fabricate command output, test results, issue numbers, or CI status.

## Safety

- Do not commit secrets.
- Do not force-push unless explicitly instructed.
- Do not rewrite `main` history.
- Do not overwrite another agent's uncommitted work.
- Do not introduce self-mutating behavior that silently changes raw captures or
  user annotations.
- If a tool, install, auth, or network failure blocks useful progress, report the
  blocker clearly instead of manufacturing a trivial commit.
