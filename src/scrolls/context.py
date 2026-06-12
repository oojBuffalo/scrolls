"""Agent context bundles (IDEAS.md §11, §14 Pass 5).

`scrolls context <query>` answers "what does my library know about X?"
with one compact Markdown document: ranked matches, capped excerpts, and
source links. Agents don't want 100 files — they want a high-signal
bundle they can drop straight into context, so unlike the data commands
this one emits Markdown, not JSON (the bundle *is* the artifact). Each
excerpt carries the item id, source, and scroll path so an agent can
follow up with `scrolls show <id>` or read the full scroll.

Ranking comes from the existing FTS5/BM25 search; excerpts prefer the
stored summary and fall back to the leading extracted text. A
"Synthesized Brief" needs an LLM and is omitted honestly, like LLM
classification (ADR 0004) and LLM concept pages (ADR 0005).
"""

from __future__ import annotations

from pathlib import Path

from scrolls.items import ScrollItem, get_item
from scrolls.search import search_items

_EXCERPT_CHARS = 700
DEFAULT_LIMIT = 8


def build_context(db_path: Path, query: str, limit: int = DEFAULT_LIMIT) -> str:
    """Render the Markdown bundle for a query; raises ValueError on a blank one.

    No matches (or no library yet) still yields a valid bundle saying so,
    because agents shouldn't crash on an empty library.
    """
    hits = search_items(db_path, query, limit=limit)
    items = [item for item in (get_item(db_path, hit.id) for hit in hits) if item]

    lines = [f"# Scrolls Context Bundle: {query}", ""]
    if not items:
        lines.append("No matching scrolls.")
        return "\n".join(lines) + "\n"

    lines += ["## Best Matches", ""]
    for rank, item in enumerate(items, start=1):
        line = f"{rank}. {item.title or item.id} (`{item.id}`)"
        if item.category:
            line += f" — {item.category}"
        lines.append(line)

    lines += ["", "## Excerpts"]
    for item in items:
        lines += ["", f"### {item.title or item.id}", "", _meta_line(item)]
        excerpt = _excerpt(item)
        if excerpt:
            lines += ["", excerpt]

    lines += ["", "## Links", ""]
    lines += [
        f"- [{item.title or item.id}]({item.canonical_url or item.url})"
        for item in items
    ]
    return "\n".join(lines) + "\n"


def _meta_line(item: ScrollItem) -> str:
    parts = [f"`{item.id}`", item.source]
    if item.markdown_path:
        parts.append(item.markdown_path)
    return " · ".join(parts)


def _excerpt(item: ScrollItem) -> str:
    # collapse whitespace so stray markdown in extracted text can't break
    # the bundle's own structure
    text = " ".join((item.summary or item.extracted_text or "").split())
    if len(text) <= _EXCERPT_CHARS:
        return text
    return text[:_EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"
