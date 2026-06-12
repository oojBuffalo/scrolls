"""Docs stay tied to the code they describe.

`docs/cli.md` cites test functions as proof of each behavior claim and
pins the version its examples were captured from; the architecture doc
and ADRs lean on relative links and `IDEAS.md §N` references. These
tests turn the audits behind those docs into permanent guards, so a
renamed test, moved file, or renumbered IDEAS section fails the suite
instead of silently rotting the docs.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from scrolls import __version__
from scrolls.agents import _TARGETS
from scrolls.cli import build_parser
from scrolls.db import SCHEMA_VERSION, init_db
from scrolls.items import ScrollItem, insert_item
from scrolls.kb import _GENERATED_DIRS, compile_kb
from scrolls.paths import get_paths
from scrolls.render import _FRONTMATTER_FIELDS, render_markdown

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"

# Docs whose references are contracts; IDEAS.md is brainstorm, not contract.
_DOC_FILES = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "CLAUDE.md",
    *sorted((REPO_ROOT / "docs").rglob("*.md")),
]

_FENCE = re.compile(r"```.*?```", re.DOTALL)


def _prose(path: Path) -> str:
    """The document without fenced code blocks (examples aren't references)."""
    return _FENCE.sub("", path.read_text(encoding="utf-8"))


def test_cited_test_names_exist():
    defined = set()
    for test_file in TESTS_DIR.glob("test_*.py"):
        defined.add(test_file.stem)  # `tests/test_cli.py` style citations
        defined.update(re.findall(r"^def (test_[a-z0-9_]+)\(", test_file.read_text(), re.M))

    missing = [
        f"{doc.relative_to(REPO_ROOT)}: {token}"
        for doc in _DOC_FILES
        for token in set(re.findall(r"\btest_[a-z0-9_]+\b", _prose(doc)))
        if token not in defined
    ]
    assert not missing, "docs cite tests that don't exist (renamed?): " + ", ".join(missing)


def test_relative_links_and_repo_paths_resolve():
    broken = []
    for doc in _DOC_FILES:
        prose = _prose(doc)
        for match in re.finditer(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)", prose):
            target = match.group(1)
            if re.match(r"^[a-z][a-z0-9+.-]*:", target):  # http(s):, mailto:
                continue
            if not (doc.parent / target).exists():
                broken.append(f"{doc.relative_to(REPO_ROOT)}: ({target})")
        for match in re.finditer(r"`((?:docs|src|tests)/[A-Za-z0-9_./-]+)`", prose):
            if not (REPO_ROOT / match.group(1)).exists():
                broken.append(f"{doc.relative_to(REPO_ROOT)}: `{match.group(1)}`")
    assert not broken, "docs reference paths that don't exist: " + ", ".join(broken)


def test_ideas_section_references_exist():
    ideas = (REPO_ROOT / "IDEAS.md").read_text(encoding="utf-8")
    sections = {int(n) for n in re.findall(r"^## (\d+)\.", ideas, re.M)}
    assert sections, "IDEAS.md numbered sections not found; did its heading style change?"

    scanned = [*_DOC_FILES, *sorted((REPO_ROOT / "src").rglob("*.py"))]
    bad = [
        f"{path.relative_to(REPO_ROOT)}: §{n}"
        for path in scanned
        for n in map(int, re.findall(r"IDEAS\.md §(\d+)", path.read_text(encoding="utf-8")))
        if n not in sections
    ]
    assert not bad, "references to nonexistent IDEAS.md sections: " + ", ".join(bad)


def _cli_surface() -> set[str]:
    """Every invocable command, with nested subcommands expanded ('agent install')."""
    surface = set()
    for action in build_parser()._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, sub in action.choices.items():
            nested = [a for a in sub._actions
                      if isinstance(a, argparse._SubParsersAction)]
            if nested:
                surface.update(f"{name} {inner}" for inner in nested[0].choices)
            else:
                surface.add(name)
    return surface


def test_cli_reference_documents_exactly_the_cli_surface():
    """docs/cli.md has one `### scrolls <command>` heading per real command."""
    text = (REPO_ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^### `scrolls ([a-z]+(?: [a-z]+)?)", text, re.M))
    surface = _cli_surface()
    assert documented == surface, (
        f"docs/cli.md headings out of sync with the parser — "
        f"undocumented: {sorted(surface - documented)}, "
        f"stale: {sorted(documented - surface)}"
    )


def test_readme_mentions_every_cli_command():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    missing = [cmd for cmd in sorted(_cli_surface())
               if not re.search(rf"scrolls {cmd}\b", readme)]
    assert not missing, "README.md never mentions: " + ", ".join(missing)


_LIBRARY_FORMAT = REPO_ROOT / "docs" / "library-format.md"

# The illustrative item docs/library-format.md describes; its pinned example
# scroll and KB index are regenerated from this fixture by the tests below,
# so a format change fails here instead of silently rotting the doc.
_EXAMPLE_ITEM = ScrollItem(
    id="arxiv:1706.03762",
    source="arxiv",
    url="https://arxiv.org/abs/1706.03762",
    saved_at="2026-06-12T08:00:00+00:00",
    source_id="1706.03762",
    canonical_url="http://arxiv.org/abs/1706.03762v7",
    title="Attention Is All You Need",
    author="Ashish Vaswani et al.",
    published_at="2017-06-12T17:57:34+00:00",
    raw_text="<the raw Atom entry; stored in the index, never rendered>",
    extracted_text="The dominant sequence transduction models are based on "
    "complex recurrent or convolutional neural networks…",
    summary="We propose the Transformer, a model architecture relying "
    "entirely on attention.",
    category="paper",
    tags=("cs.CL", "cs.LG"),
    links=("https://arxiv.org/pdf/1706.03762",),
    media=("https://arxiv.org/pdf/1706.03762",),
    content_hash="sha256:6d2e1066c2f3aae40f4ea846cebee5ee5cdc77a2f9bb582a0f5a526f70b48aaa",
    markdown_path="scrolls/arxiv/attention-is-all-you-need.md",
    provenance={
        "adapter": "arxiv",
        "fetched_at": "2026-06-12T08:00:05+00:00",
        "extraction_method": "arxiv-atom+pypdf",
    },
    stage="rendered",
)

_EXAMPLE_NEIGHBOR = ScrollItem(
    id="wikipedia:en:SQLite",
    source="wikipedia",
    url="https://en.wikipedia.org/wiki/SQLite",
    saved_at="2026-06-12T09:00:00+00:00",
    title="SQLite",
    category="reference",
    concepts=("Database software",),
    markdown_path="scrolls/wikipedia/sqlite.md",
    stage="rendered",
)


def _pinned_block(marker: str) -> str:
    """The fenced block right after `<!-- pinned: <marker> -->` in the format doc."""
    text = _LIBRARY_FORMAT.read_text(encoding="utf-8")
    match = re.search(
        rf"<!-- pinned: {re.escape(marker)} -->\n+```[^\n]*\n(.*?)```", text, re.DOTALL
    )
    assert match, f"docs/library-format.md has no pinned block '{marker}'"
    return match.group(1)


def test_library_format_frontmatter_table_matches_render_fields():
    """The doc's frontmatter key table lists exactly render's fields, in order."""
    text = _LIBRARY_FORMAT.read_text(encoding="utf-8")
    match = re.search(r"<!-- pinned: frontmatter-keys -->\n+((?:\|[^\n]*\n)+)", text)
    assert match, "docs/library-format.md has no pinned frontmatter key table"
    rows = match.group(1).splitlines()[2:]  # drop header and separator rows
    documented = tuple(row.split("|")[1].strip().strip("`") for row in rows)
    assert documented == _FRONTMATTER_FIELDS, (
        "docs/library-format.md frontmatter table no longer matches "
        "render._FRONTMATTER_FIELDS — update the table (order matters)"
    )


def test_library_format_example_scroll_is_render_output():
    assert _pinned_block("example-scroll") == render_markdown(_EXAMPLE_ITEM), (
        "docs/library-format.md's example scroll no longer matches "
        "render_markdown() for the documented fixture item"
    )


def test_library_format_kb_index_example_matches_compiler_output(tmp_path):
    paths = get_paths(tmp_path / "home")
    paths.root.mkdir(parents=True)
    init_db(paths.db_path)
    insert_item(paths.db_path, _EXAMPLE_ITEM)
    insert_item(paths.db_path, _EXAMPLE_NEIGHBOR)
    compile_kb(paths)
    index = (paths.library_dir / "index.md").read_text(encoding="utf-8")
    assert index == _pinned_block("example-kb-index"), (
        "docs/library-format.md's example library/index.md no longer matches "
        "compile_kb() output for the documented fixture items"
    )


def test_library_format_names_every_generated_artifact():
    """Generated KB dirs and agent install paths must appear in the doc."""
    text = _LIBRARY_FORMAT.read_text(encoding="utf-8")
    missing = [f"library/{name}/" for name in _GENERATED_DIRS
               if f"library/{name}/" not in text]
    missing += [relpath for relpath in _TARGETS if relpath not in text]
    assert not missing, (
        "docs/library-format.md no longer mentions generated artifacts: "
        + ", ".join(missing)
    )


def test_adr_index_lists_every_adr():
    """A new ADR file must get a row in docs/adr/README.md."""
    adr_dir = REPO_ROOT / "docs" / "adr"
    index = (adr_dir / "README.md").read_text(encoding="utf-8")
    missing = [f.name for f in sorted(adr_dir.glob("[0-9]*.md"))
               if f.name not in index]
    assert not missing, "docs/adr/README.md is missing rows for: " + ", ".join(missing)


def test_cli_reference_capture_pin_matches_code():
    """docs/cli.md pins the version/schema its examples were captured from.

    When either constant changes, re-verify the captured examples (the
    doc's reproduction appendix makes that cheap) and update the pin in
    the same commit — see docs/agents/domain.md.
    """
    intro = (REPO_ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
    pin = re.search(r"`scrolls ([0-9][\w.]*)`\s*\(schema version (\d+)\)", intro)
    assert pin, "docs/cli.md no longer states which version its examples came from"
    assert pin.group(1) == __version__ and int(pin.group(2)) == SCHEMA_VERSION, (
        f"docs/cli.md examples were captured from scrolls {pin.group(1)} "
        f"(schema {pin.group(2)}) but the code is now {__version__} "
        f"(schema {SCHEMA_VERSION}); re-run the doc's reproduction appendix "
        "and update the pin"
    )
