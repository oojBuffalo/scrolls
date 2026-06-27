"""H396 — the regeneration-safety contract (ADR 0102).

The third **contract-consolidation** cell, after H388 (the whole MCP read-surface
determinism contract) and H394/H395 (the CLI read + round-trip transport
contracts). Where those retired per-tool / per-command / per-transport
treadmills, this retires the per-page non-destructive-regeneration treadmill:
the M1 tests proved refresh-safety one page at a time (a custody marker survives
on `categories/news.md` here, a per-source breakdown survives on `index.md`
there, the agent skill suffix survives in `test_agents.py`). This is **one**
guard over *every* generated-artifact family at once.

The **completeness keystone** (`_GENERATED_ARTIFACT_KINDS`, the kb/agents analogue
of `_MCP_READ_TOOLS` / `_CLI_READ_COMMANDS`): the covered kinds must equal the
live source-of-truth registries the compiler/installer drive — kb.py's
`_GENERATED_DIRS` + `_GENERATED_FILES` (the exact set `compile_kb` writes and
`_reconcile_generated` cleans up) and agents.py's `_TARGETS`. So a *new*
generated artifact (a new `library/` page family or a new `agents/` target) fails
the contract until it is given a regeneration-safety entry — `@user` blocks can
never be silently clobbered by a new view (the H364 registry-completeness
mechanism on the regeneration-safety axis). A defense-in-depth leg walks the
pages a real compile actually emits and pins each to a registered kind, so even a
rogue writer that emits an unregistered `library/` page is caught.

Refresh-safety rationale (ADR 0102 / the obsidian-second-brain "mechanism, not
philosophy" adoption): a regenerate is *authoritative over the fenced region* —
stale generated content can never linger — while anything outside the fence is
preserved byte-for-byte. The uniform per-kind probe injects a STALE sentinel
*inside* the fence and a `@user` note *outside* it (as a suffix — the one
position preserved across every kind, including the header-pinned SKILL.md whose
prefix is a regenerated frontmatter), then asserts the STALE text is purged (the
refresh happened, authoritatively) **and** the `@user` note survives (raw
annotation is sacred). This catches both failure modes the contract guards: a
no-op writer leaves STALE behind, and a whole-file-overwrite writer clobbers the
annotation.
"""

from collections import namedtuple

import pytest

import scrolls.agents as agents
import scrolls.kb as kb
from scrolls.cli import main
from scrolls.generated import (
    GENERATED_END,
    fence,
    generated_body,
    user_regions,
)
from scrolls.items import ScrollItem, insert_item
from scrolls.paths import get_paths

# The begin-marker token (literal, matching `test_agents.py`): the @generated
# fence opener. Stable across reworded marker tails (matched by prefix).
_BEGIN = "<!-- @generated scrolls"

# A distinctive sentinel injected inside the fence; if it survives a regenerate
# the writer is not authoritative over the fenced region (no refresh happened).
_STALE = "ZZZ-STALE-GENERATED-MUST-NOT-LINGER-ZZZ"

# The marker tail the probe stamps on its injected fence — cosmetic (matching is
# by the begin token), so any string works.
_PROBE_BY = "regeneration-safety probe"


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


# A generated artifact family: how to regenerate it ("kb" recompiles the library,
# "agents" reinstalls the instruction files), the registry key it must match in
# the source-of-truth registries, and a representative page the seed produces.
Kind = namedtuple("Kind", "regenerator key relpath")

# Every generated-artifact family, keyed to the live registries asserted equal in
# the completeness keystone below. The kb dir-kinds point at a representative page
# the seed guarantees; the kb file-kinds and the three agent targets are fixed
# paths.
_GENERATED_ARTIFACT_KINDS = (
    Kind("kb", "sources", "library/sources/arxiv.md"),
    Kind("kb", "categories", "library/categories/reference.md"),
    Kind("kb", "concepts", "library/concepts/databases.md"),
    Kind("kb", "tags", "library/tags/sql.md"),
    Kind("kb", "index.md", "library/index.md"),
    Kind("kb", "graph.md", "library/graph.md"),
    Kind("kb", "works.md", "library/works.md"),
    Kind("agents", "agents/claude/SKILL.md", "agents/claude/SKILL.md"),
    Kind("agents", "agents/codex/AGENTS.md", "agents/codex/AGENTS.md"),
    Kind("agents", "agents/hermes/SKILL.md", "agents/hermes/SKILL.md"),
)


def _make_rendered(item_id, source, title, *, category, concepts, tags, url, links):
    slug = title.lower().replace(" ", "-")
    return ScrollItem(
        id=item_id,
        source=source,
        url=url,
        saved_at="2026-06-01T00:00:00+00:00",
        title=title,
        category=category,
        concepts=tuple(concepts),
        tags=tuple(tags),
        links=tuple(links),
        markdown_path=f"scrolls/{source}/{slug}.md",
        stage="rendered",
        raw_text=f"body for {item_id}",
        content_hash=item_id,
    )


def _seed(db):
    """Two DOI-clustered, mutually linked papers — so every generated-artifact
    family is non-vacuous: a `sources/` page per source, a shared
    `categories/reference.md`, a `concepts/databases.md`, a `tags/sql.md`, a
    `graph.md` with a real edge, and a `works.md` with a real 2-representation
    work (both name `doi.org/10.1/db`)."""
    insert_item(db, _make_rendered(
        "arxiv:dba", "arxiv", "A DB Paper",
        category="reference", concepts=("Databases",), tags=("sql",),
        url="https://example.org/dba",
        links=("https://doi.org/10.1/db", "https://example.org/dbb"),
    ))
    insert_item(db, _make_rendered(
        "crossref:dbb", "crossref", "B DB Paper",
        category="reference", concepts=("Databases",), tags=("sql",),
        url="https://example.org/dbb",
        links=("https://doi.org/10.1/db",),
    ))


def _prepare_library(capsys):
    """init + seed + compile — the shared setup the kb-kind reads run against."""
    main(["init"])
    _seed(get_paths().db_path)
    capsys.readouterr()
    assert main(["kb"]) == 0
    capsys.readouterr()


def _prepare_all(capsys):
    """The library compile plus the agent-doc install, so every kind's
    representative page exists on disk."""
    _prepare_library(capsys)
    assert main(["agent", "install"]) == 0
    capsys.readouterr()


def _regenerate(regenerator, capsys):
    if regenerator == "kb":
        assert main(["kb"]) == 0
    else:
        assert main(["agent", "install"]) == 0
    capsys.readouterr()


def test_generated_artifact_kinds_cover_the_live_registries():
    """The completeness keystone (roadmap H396): the covered kinds equal the live
    source-of-truth registries the compiler/installer drive — kb's
    `_GENERATED_DIRS`/`_GENERATED_FILES` and agents' `_TARGETS` — so a *new*
    generated artifact fails the contract until given a regeneration-safety entry
    (the H364 registry-completeness mechanism on the regeneration axis)."""
    registered = (
        {("kb", k) for k in set(kb._GENERATED_DIRS) | set(kb._GENERATED_FILES)}
        | {("agents", k) for k in agents._TARGETS}
    )
    classified = {(kind.regenerator, kind.key) for kind in _GENERATED_ARTIFACT_KINDS}
    assert classified == registered, (
        f"coverage drift: uncovered={registered - classified}, "
        f"unknown={classified - registered}"
    )
    # one entry per kind (no duplicate key), and each kb dir-kind's representative
    # path lives under its registered directory
    assert len({(k.regenerator, k.key) for k in _GENERATED_ARTIFACT_KINDS}) == len(
        _GENERATED_ARTIFACT_KINDS
    )


def test_every_emitted_library_page_maps_to_a_registered_kind(scrolls_home, capsys):
    """Defense in depth for the keystone: every `.md` a real compile emits under
    `library/` belongs to a registered kind, so even a rogue writer that emits an
    unregistered page (without touching `_GENERATED_DIRS`/`_GENERATED_FILES`) is
    caught — `library/` holds only generated pages (scroll files live under
    `scrolls/`)."""
    _prepare_library(capsys)
    library = scrolls_home / "library"
    kb_kinds = set(kb._GENERATED_DIRS) | set(kb._GENERATED_FILES)
    emitted = sorted(library.rglob("*.md"))
    assert emitted  # the seed produced pages
    for page in emitted:
        rel = page.relative_to(library)
        kind = rel.parts[0] if len(rel.parts) > 1 else rel.name
        assert kind in kb_kinds, f"unregistered generated page: {rel} (kind {kind!r})"


@pytest.mark.parametrize(
    "kind", _GENERATED_ARTIFACT_KINDS, ids=lambda k: f"{k.regenerator}:{k.key}"
)
def test_artifact_kind_regeneration_is_refresh_safe(scrolls_home, capsys, kind):
    """For every generated-artifact family: a regenerate refreshes the fenced
    region (a STALE sentinel injected inside the fence is purged) while a `@user`
    annotation outside the fence survives byte-for-byte (ADR 0102)."""
    _prepare_all(capsys)
    path = scrolls_home / kind.relpath
    assert path.is_file(), f"{kind.relpath} was not produced by the seed"

    original = path.read_text(encoding="utf-8")
    regions = user_regions(original)
    assert regions is not None, f"{kind.relpath} carries no @generated fence"
    assert generated_body(original).strip(), f"{kind.relpath} has an empty fenced region"
    assert original.count(_BEGIN) == 1

    # Tamper: replace the fenced body with a STALE sentinel and append a `@user`
    # note after the `@end` marker (the suffix region every kind preserves).
    prefix, suffix = regions
    note = f"_Hand annotation kept for {kind.key}._"
    user_block = f"\n<!-- @user -->\n{note}\n"
    path.write_text(prefix + fence(_STALE, _PROBE_BY) + suffix + user_block, encoding="utf-8")

    _regenerate(kind.regenerator, capsys)

    refreshed = path.read_text(encoding="utf-8")
    assert note in refreshed, "the @user annotation outside the fence was clobbered"
    assert _STALE not in refreshed, "stale generated content lingered (no authoritative refresh)"
    assert refreshed.count(_BEGIN) == 1, "the regenerate left more than one fenced region"
    assert GENERATED_END in refreshed
    assert generated_body(refreshed).strip(), "the regenerated fenced region is empty"
