"""Agent instruction files (IDEAS.md §10, §14 Pass 5; ADR 0006).

`scrolls agent install` writes small instruction docs teaching coding
agents the shell-first interface: `context` for compact bundles,
`search`/`show` for depth, `ingest` to save new URLs. One shared body is
wrapped per tool — skill frontmatter for Claude Code and Hermes, plain
AGENTS.md for Codex.

Everything lands under `<root>/agents/`, never inside another tool's
config tree: an install (often unattended) shouldn't edit `~/.claude` or
`~/.hermes`. Users wire the files up where their tool expects them
(copy, symlink, or include).

The files are generated templates, regenerated on every run like the
compiled KB — but, like the KB pages, each generated body lives inside a
sentinel fence (`scrolls.generated`, ADR 0102) so a reinstall replaces only
the fenced region and any annotation outside it survives. The skill
frontmatter is a regenerated *header*: its `---` has to stay at byte 0 for
the file to load as a skill, so it is pinned above the fence and refreshed
every run, and only a suffix annotation (after the `@end` marker) is kept —
the natural place to add project-specific notes.
"""

from __future__ import annotations

from scrolls.generated import write_generated
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
  research question. `--budget index` (or `connected`) boots on the
  catalog/link-graph without bodies when you only need the map.
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
- Budget your context: `scrolls context "<topic>" --budget index` for a
  cheap catalog (matches + links, no bodies), then pull the bodies you
  want with `scrolls show <id>` or re-run at `--budget full`.
- If a command reports an uninitialized library, run `scrolls init`.
"""

# Names the command in each file's `@generated` marker (ADR 0102).
_REGENERATED_BY = "scrolls agent install"

# relpath under the library root -> regenerated header pinned above the fence.
# Skill files lead with frontmatter (its `---` must stay at byte 0); Codex's
# AGENTS.md has no header, so its whole body is fenced. The shared command
# reference (`_BODY`) is the fenced, regenerated region in every case.
_TARGETS = {
    "agents/claude/SKILL.md": _FRONTMATTER,
    "agents/codex/AGENTS.md": "",
    "agents/hermes/SKILL.md": _FRONTMATTER,
}


def install_agent_docs(paths: LibraryPaths) -> list[str]:
    """(Re)write the instruction files; return their root-relative paths.

    Each file is regenerated inside its sentinel fence (ADR 0102), so a
    reinstall refreshes the generated body while preserving any annotation a
    user appended after the `@end` marker.
    """
    written = []
    body = _BODY.rstrip("\n")  # fence() re-adds the single trailing newline
    for relpath, header in _TARGETS.items():
        write_generated(paths.root / relpath, body, _REGENERATED_BY, header=header)
        written.append(relpath)
    return written
