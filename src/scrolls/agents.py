"""Agent instruction files (IDEAS.md §10, §14 Pass 5; ADR 0006).

`scrolls agent install` writes small instruction docs teaching coding
agents the shell-first interface: `context` for compact bundles,
`search`/`show` for depth, `ingest` to save new URLs. One shared body is
wrapped per tool — skill frontmatter for Claude Code and Hermes, plain
AGENTS.md for Codex.

Everything lands under `<root>/agents/`, never inside another tool's
config tree: an install (often unattended) shouldn't edit `~/.claude` or
`~/.hermes`. Users wire the files up where their tool expects them
(copy, symlink, or include). The files are generated templates,
regenerated on every run like the compiled KB — customization belongs in
the installed copies, not here.
"""

from __future__ import annotations

from scrolls.paths import LibraryPaths

_FRONTMATTER = """\
---
name: scrolls
description: Search the user's local Scrolls library of saved internet
  content (articles, videos, wiki pages). Use when the user asks what
  their library or scrolls say about a topic, or when their saved
  sources would inform the current task.
---

"""

_BODY = """\
# Scrolls

Scrolls is a local-first library of the user's saved internet content,
stored as Markdown scrolls and indexed with SQLite full-text search.
All commands are agent-friendly: data commands emit JSON, and
`scrolls context` emits Markdown built to drop into your context.

## Commands

- `scrolls context "<topic>"` — compact Markdown bundle: ranked
  matches, capped excerpts, and source links. Start here for any
  research question.
- `scrolls search "<query>" --limit 20` — BM25-ranked hits with
  snippets, as JSON.
- `scrolls show <id>` — one item in full (extracted text, provenance,
  classification), as JSON.
- `scrolls related <id>` — other saved items connected to one item
  (links between them, shared concepts/tags, same category), with
  the reasons, as JSON.
- `scrolls list` — every saved item with id, stage, and title, as JSON.
- `scrolls paths` — library layout, as JSON. Scroll files live under
  `scrolls/<source>/`, compiled index pages under `library/`.
- `scrolls ingest <url>` — save a new URL into the library (register,
  fetch, classify, render), as JSON.

## Tips

- Prefer `scrolls context` over assembling results yourself; fall back
  to `search` + `show` when you need full text or structured fields.
- Excerpts in a context bundle cite the item id and scroll path — use
  `scrolls show <id>` or read the scroll file for the full source.
- If a command reports an uninitialized library, run `scrolls init`.
"""

# relpath under the library root -> file content
_TARGETS = {
    "agents/claude/SKILL.md": _FRONTMATTER + _BODY,
    "agents/codex/AGENTS.md": _BODY,
    "agents/hermes/SKILL.md": _FRONTMATTER + _BODY,
}


def install_agent_docs(paths: LibraryPaths) -> list[str]:
    """(Re)write the instruction files; return their root-relative paths."""
    written = []
    for relpath, content in _TARGETS.items():
        target = paths.root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(relpath)
    return written
