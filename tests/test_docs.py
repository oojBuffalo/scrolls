"""Docs stay tied to the code they describe.

`docs/cli.md` cites test functions as proof of each behavior claim and
pins the version its examples were captured from; the architecture doc
and ADRs lean on relative links and `IDEAS.md §N` references. These
tests turn the audits behind those docs into permanent guards, so a
renamed test, moved file, or renumbered IDEAS section fails the suite
instead of silently rotting the docs.
"""

from __future__ import annotations

import re
from pathlib import Path

from scrolls import __version__
from scrolls.db import SCHEMA_VERSION

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
