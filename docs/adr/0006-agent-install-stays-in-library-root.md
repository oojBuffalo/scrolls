# ADR 0006: `scrolls agent install` writes only under the library root

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

The last Pass 5 piece (IDEAS.md §10, §14) is `scrolls agent install`,
which generates instruction files teaching coding agents the shell-first
interface. IDEAS.md §10 sketches per-tool destinations including
`~/.hermes/skills/scrolls/SKILL.md` — i.e., writing into another tool's
config tree — while placing the Claude Code and Codex files under
`~/.scrolls/agents/`. The open question was whether install may touch
directories Scrolls doesn't own.

## Decision

All generated files land under `<root>/agents/` (`claude/SKILL.md`,
`codex/AGENTS.md`, `hermes/SKILL.md`), never inside `~/.claude`,
`~/.codex`, or `~/.hermes`:

1. **Don't edit other tools' homes uninvited.** Installs run unattended
   (setup scripts, agents); silently dropping files into another tool's
   skill directory is surprising and hard to undo. Users wire the files
   up where their tool expects them — copy, symlink, or include.
2. **One shared body, thin per-tool wrappers.** Claude Code and Hermes
   get skill frontmatter; Codex gets plain `AGENTS.md`. The body teaches
   the interface: `context` first, `search`/`show` for depth, `ingest`
   to save, `paths` to discover the layout.
3. **Generated templates, regenerated every run** (like the compiled
   KB). Customization belongs in the installed copies, not in
   `<root>/agents/`.
4. **`agents/` is a first-class library subdir** in `LibraryPaths`,
   created by `init` and reported by `scrolls paths`, so agents and
   scripts can discover the files. `agent install` auto-initializes the
   library like `add` does.

A future explicit flag (e.g. `agent install --into ~/.claude/skills`)
can opt into tool-tree installs with user consent; `agent` is a command
group so `install` can grow siblings (`status`, `uninstall`).

## Consequences

- Installing the files somewhere useful is a manual (or documented)
  step: e.g. symlink `<root>/agents/claude` into `~/.claude/skills/scrolls`.
- The instruction files reference the installed `scrolls` command; from
  a source checkout the prefix is `uv run scrolls`.
- Adding `agents_dir` changed the exact-layout assertions in
  `tests/test_paths.py` and `tests/test_cli.py` — the README layout and
  `scrolls paths` stay the single source of truth.

## Proof

`src/scrolls/agents.py` + the `agent` command group in `cli.py`, with
tests (`tests/test_agents.py`; 189 passing) and a fresh-home smoke test:
`scrolls agent install` on an empty `$SCROLLS_HOME` initialized the
library and wrote all three files with frontmatter and command docs.
