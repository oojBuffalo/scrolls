"""The compiled-page custody-honesty contract (roadmap H404) — one completeness-asserted invariant.

The eleventh **contract-consolidation** cell (after H388's whole-MCP determinism
contract … H403's browse-filter drill contract) and the *compiled-surface* sibling
of H398 (the JSON/MCP G1 honesty matrix). Where H398 pins that the agent-facing
JSON/MCP reads never fabricate a custody picture they have no basis for, this pins
the same G1 *honest-absence/honest-presence* invariant on the human-readable
compiled `library/` pages — lifting the scattered per-page honest-absence tests in
`tests/test_completeness.py` (H190's `test_compiled_pages_omit_action_lines_with_no_basis`
and `test_compiled_refresh_line_is_per_axis_honest`, which only exercised `index.md`)
to one matrix guard over *every* custody-bearing compiled page kind.

The claim, for *every* compiled page kind that carries a scope custody headline —
the four group-page dirs (`sources`/`categories`/`concepts`/`tags`, each folding
its own member scope via `kb._write_page`) plus the whole-library `index.md`
landing page (`kb._write_index`):

- a `_Custody:` headline **always** renders (its basis is the page's own held
  scope — even an empty scope is the honest ``_Custody: 0 scroll(s).``);
- a `_By source:` split renders **iff** the page spans ≥2 sources;
- an `_Attention:` drift pointer renders **iff** its scope carries a cross-source
  loss (`weakest_source` non-`None` — ≥2 sources *and* a `drifted`/`rotted`
  source); and
- a `_Refresh:` enrichment/summary pointer renders **iff** its scope carries stale
  classification or summary debt (`stale_classification_counts_by_source` /
  `stale_summary_counts_by_source` non-empty) — per-axis, so a clause appears only
  for the axis with a basis (never a fabricated `summaries stale` with no stored
  summary, H190's per-axis honesty).

Two faces, the H388/H398/H403 shape:

1. **The completeness keystone** — `_CUSTODY_BEARING_DIRS` ∪ `_CUSTODY_BEARING_FILES`
   ∪ a *named* `_NO_CUSTODY_HEADLINE` set partition the live
   `kb._GENERATED_DIRS`/`kb._GENERATED_FILES` *exactly*, so a *new* compiled page
   kind fails the contract until it declares a custody-honesty leg or is named
   no-headline. The H388/H403 registry-completeness mechanism on the compiled-page
   axis. (Note: the roadmap's parenthetical named `graph.md` as custody-bearing;
   the live compiler does **not** — `graph.md` is a pure link-graph rollup with no
   `_Custody:` headline, pinned by `test_kb.py`, and `works.md` rides the *works*
   axis with a per-work `_Custody:` marker per section, H270 — so both are named
   no-headline exemptions, not custody-headline pages.)

2. **The honesty matrix** — over a clean fixture and a drift/stale-debt fixture,
   every emitted page of every custody-bearing kind renders its custody lines
   honestly. The whole-library `index.md` is tied directly to the JSON
   `status`/`doctor` `attention`/`enrichment`/`summaries` bases (the independent
   H190 convergence anchor); each group page is tied to its own scope's bases,
   recomputed over its members (the same per-source folds `doctor` itself uses,
   applied at scope) — and each page's `_Custody: N scroll(s)` headline count is
   cross-checked against the member model so the basis recompute is validated
   against the live page, not assumed. A sabotage that drops the `_By source:`
   split fails *only* the kinds with a multi-source page (`index.md`/`categories`/
   `concepts`/`tags`), never the single-source-only `sources` kind — the matrix
   isolates the broken seam and proves single-source honest-absence is a genuine
   no-op (the H403 selector-isolation precedent on the compiled-page axis).
"""

import json
import re

import pytest

import scrolls.kb as kb
from scrolls.classify import stale_classification_counts_by_source
from scrolls.cli import main
from scrolls.custody import (
    CustodyEvent,
    custody_counts_by_source,
    latest_events,
    record_events,
    weakest_source,
)
from scrolls.doctor import run_doctor
from scrolls.items import ScrollItem, insert_item, list_items
from scrolls.kb import group_concepts, group_tags
from scrolls.kb_llm import stale_summary_counts_by_source
from scrolls.paths import get_paths
from scrolls.render import slugify


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


# --- the compiled-page registry — the completeness keystone ------------------

# The compiled `library/` page kinds that carry a *scope custody headline* and its
# derived action-pointer lines (roadmap H184): the four group-page dirs (each page
# folds its own member scope, `kb._write_page`) plus the whole-library `index.md`
# landing page (`kb._write_index`). Each must render its custody lines honestly.
# Hardcoded (not derived from the live registry) so the keystone below *bites*: a
# new `_GENERATED_DIRS` entry breaks the equality until it is classified here.
_CUSTODY_BEARING_DIRS = {"sources", "categories", "concepts", "tags"}
_CUSTODY_BEARING_FILES = {"index.md"}  # the landing page

# The generated *files* that carry NO scope custody headline — each named, never a
# silent skip (the H388/H403 keystone idiom). The roadmap's parenthetical was wrong
# about `graph.md`: the live compiler emits neither a `_Custody:` headline on it.
_NO_CUSTODY_HEADLINE = {
    "graph.md": "pure link-graph rollup — no custody scope (test_kb.py pins `_Custody:` absent)",
    "works.md": "rides the works axis — a per-work `_Custody:` marker per section (H270), pinned in test_custody_convergence.py",
}


def test_compiled_page_registry_partitions_the_generated_tree():
    """`_CUSTODY_BEARING_DIRS` ∪ `_CUSTODY_BEARING_FILES` ∪ the named
    `_NO_CUSTODY_HEADLINE` set partition the live `kb._GENERATED_DIRS`/
    `kb._GENERATED_FILES` *exactly* — so a *new* compiled page kind fails the
    contract until it declares a custody-honesty leg or is named no-headline. The
    H388/H403 registry-completeness mechanism on the compiled-page axis."""
    # every generated dir is custody-bearing (each group page folds its own scope)
    assert _CUSTODY_BEARING_DIRS == set(kb._GENERATED_DIRS)
    # the generated files split into custody-bearing ∪ named no-headline, exactly
    assert _CUSTODY_BEARING_FILES.isdisjoint(_NO_CUSTODY_HEADLINE)
    assert _CUSTODY_BEARING_FILES | set(_NO_CUSTODY_HEADLINE) == set(kb._GENERATED_FILES)
    # the load-bearing distinction (sanity, not a tautology): index.md carries a
    # headline; graph.md/works.md do not — the parenthetical the roadmap got wrong
    assert "index.md" in _CUSTODY_BEARING_FILES
    assert {"graph.md", "works.md"} <= set(_NO_CUSTODY_HEADLINE)


# --- fixtures ----------------------------------------------------------------


def _item(item_id, **overrides):
    base = dict(
        id=item_id,
        source=item_id.split(":")[0],
        url=f"https://example.org/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00",
        title=item_id,
        extracted_text="alpha beta gamma delta",
        summary="alpha beta gamma delta",
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def _rendered(item_id, **overrides):
    """A clean, fully-held rendered item (full fidelity, no drift, no stale debt)."""
    base = dict(
        stage="rendered",
        markdown_path=f"scrolls/{item_id.replace(':', '/')}.md",
        raw_text="<raw>alpha</raw>",
        content_hash=f"sha256:{item_id}",
    )
    base.update(overrides)
    return _item(item_id, **base)


def _stale_classified(item_id, **overrides):
    """A rendered item whose rules category was stamped under a superseded ruleset —
    a real basis for a `_Refresh:` classifications clause (the H190 helper shape)."""
    base = dict(
        category="tutorial",
        stage="rendered",
        markdown_path=f"scrolls/{item_id.replace(':', '/')}.md",
        raw_text="<raw>alpha</raw>",
        content_hash=f"sha256:{item_id}",
        provenance={
            "classified_by": "rules-v1",
            "classified_basis": "weak-source",
            "classified_ruleset": "deadbeef0000",
        },
    )
    base.update(overrides)
    return _item(item_id, **base)


def _seed_clean_fixture(db):
    """A clean multi-source library — held, full fidelity, no drift, no stale debt.

    Two sources (so `index.md` and the shared group pages span ≥2 sources and carry
    a `_By source:` split) plus a single-source group, but no source carries any
    loss and no enrichment is stale — so `doctor`'s `attention`/`enrichment`/
    `summaries` bases are all empty and *every* compiled page must show the
    `_Custody:` headline and never an `_Attention:`/`_Refresh:` pointer (the
    honest-absence direction, H190 generalised to every page kind)."""
    insert_item(db, _rendered("web:sa", category="shared",
                              concepts=("topology",), tags=("paired",)))
    insert_item(db, _rendered("arxiv:sb", category="shared",
                              concepts=("topology",), tags=("paired",),
                              url="https://arxiv.org/abs/sb"))
    insert_item(db, _rendered("web:solo", category="onlyweb",
                              concepts=("alone",), tags=("webonly",)))


def _seed_debt_fixture(db):
    """A library whose custody-honesty axes are each non-vacuous at *page scope*.

    - **clean multi-source pair** (`web:sa`/`arxiv:sb`, category/concept/tag
      `shared`/`topology`/`paired`): 2 sources, no loss → `_By source:` present,
      `_Attention:`/`_Refresh:` absent;
    - **multi-source group with a drift loss** (`web:da`/`arxiv:db`,
      `moved`/`relocation`/`risky`; `arxiv:db` recorded `drifted`): 2 sources, an
      arxiv loss → `_By source:` *and* `_Attention:` present, `_Refresh:` absent;
    - **single-source stale classification** (`web:st`, `stalecat`/`aging`/`webtag`):
      1 source, superseded ruleset → `_Refresh:` present, `_By source:`/`_Attention:`
      absent (the no-single-source-gate of refresh, H178).

    So across the compiled pages each pointer axis appears on ≥1 page and is absent
    on ≥1 page (the iff is non-trivial), and `index.md` (whole library) carries all
    three. The drifted `arxiv:db` also proves a single-source page never fabricates
    an `_Attention:` from a loss its scope cannot compare across sources
    (`sources/arxiv.md`: drift present yet no attention)."""
    insert_item(db, _rendered("web:sa", category="shared",
                              concepts=("topology",), tags=("paired",)))
    insert_item(db, _rendered("arxiv:sb", category="shared",
                              concepts=("topology",), tags=("paired",),
                              url="https://arxiv.org/abs/sb"))
    insert_item(db, _rendered("web:da", category="moved",
                              concepts=("relocation",), tags=("risky",)))
    insert_item(db, _rendered("arxiv:db", category="moved",
                              concepts=("relocation",), tags=("risky",),
                              url="https://arxiv.org/abs/db"))
    record_events(db, [
        CustodyEvent("arxiv:db", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:arxiv:db", "cafe1234", None),
    ])
    insert_item(db, _stale_classified("web:st", category="stalecat",
                                      concepts=("aging",), tags=("webtag",)))


# --- the honesty matrix ------------------------------------------------------


_HEADLINE_RE = re.compile(r"_Custody: (\d+) scroll")
_AXES = ("custody", "attention", "refresh", "by_source")


def _headline_count(text):
    """The N in a page's ``_Custody: N scroll(s)`` headline — proves the page on
    disk holds the member set the contract assumes (validates the basis recompute)."""
    match = _HEADLINE_RE.search(text)
    assert match, "compiled page carries no `_Custody:` headline"
    return int(match.group(1))


def _present(text):
    """Which custody lines a compiled page actually renders — read off the emitted
    markdown, independent of the renderer that produced it."""
    return {
        "custody": "_Custody:" in text,
        "attention": "_Attention:" in text,
        "refresh": "_Refresh:" in text,
        "by_source": "_By source:_" in text,
    }


def _expected(members, verdicts):
    """The custody lines a page's scope *honestly* warrants — recomputed from the
    page's own members. `by_source` uses the raw distinct-source count (independent
    of `render_custody_by_source`, so a dropped-split sabotage is catchable);
    `attention`/`refresh` use the canonical `weakest_source` / stale-count folds
    `doctor` itself reads (applied at scope)."""
    by_source = custody_counts_by_source(members, verdicts)
    return {
        "custody": True,  # the headline is always rendered, even for an empty scope
        "attention": weakest_source(by_source) is not None,
        "refresh": bool(stale_classification_counts_by_source(members))
        or bool(stale_summary_counts_by_source(members, {})),
        "by_source": len({member.source for member in members}) >= 2,
    }


def _group_pages(items):
    """`{ (kind, relpath) : members }` for every compiled group page, built from the
    live grouping helpers `compile_kb` uses — so membership is exact and the test
    pins custody-line honesty, not grouping (the headline-count cross-check still
    validates each page on disk matches this model)."""
    pages = {}
    by_source, by_category = {}, {}
    for item in items:
        by_source.setdefault(item.source, []).append(item)
        if item.category:
            by_category.setdefault(item.category, []).append(item)
    for source, members in by_source.items():
        pages[("sources", f"sources/{slugify(source) or 'untitled'}.md")] = members
    for category, members in by_category.items():
        pages[("categories", f"categories/{slugify(category) or 'untitled'}.md")] = members
    for slug, entry in group_concepts(items).items():
        pages[("concepts", f"concepts/{slug}.md")] = entry["items"]
    by_tag = group_tags(items)
    filenames = kb._tag_filenames(by_tag)
    for key, entry in by_tag.items():
        pages[("tags", f"tags/{filenames[key]}.md")] = entry["items"]
    return pages


def _custody_pages(db):
    """`[(kind, relpath, text)]` for every emitted custody-bearing page (the group
    pages plus the whole-library `index.md`)."""
    items = [item for item in list_items(db) if item.markdown_path]
    library = get_paths().library_dir
    pages = []
    for (kind, relpath), members in _group_pages(items).items():
        path = library / relpath
        assert path.exists(), f"compiler did not emit {relpath}"
        pages.append((kind, relpath, path.read_text(encoding="utf-8")))
    pages.append(("index.md", "index.md",
                  (library / "index.md").read_text(encoding="utf-8")))
    return pages


def _honesty_violations(capsys):
    """The set of custody-bearing page kinds whose emitted custody lines disagree
    with the basis their scope honestly warrants. The matrix asserts this is empty;
    the sabotage asserts it is exactly the kinds whose seam it broke."""
    capsys.readouterr()
    db = get_paths().db_path
    items = [item for item in list_items(db) if item.markdown_path]
    verdicts = latest_events(db)
    library = get_paths().library_dir
    violations = set()
    # group pages: tied to each scope's own bases, with a headline-count cross-check
    for (kind, relpath), members in _group_pages(items).items():
        text = (library / relpath).read_text(encoding="utf-8")
        assert _headline_count(text) == len(members), (
            relpath, _headline_count(text), len(members))
        if _present(text) != _expected(members, verdicts):
            violations.add(kind)
    # index.md: tied directly to the JSON status/doctor bases (the H190 anchor)
    index_text = (library / "index.md").read_text(encoding="utf-8")
    assert _headline_count(index_text) == len(items)
    custody = run_doctor(get_paths())["custody"]
    assert main(["status"]) == 0
    attention = json.loads(capsys.readouterr().out)["attention"]
    index_expected = {
        "custody": True,
        "attention": attention is not None,
        "refresh": bool(custody["enrichment"]["by_source"])
        or bool(custody["summaries"]["by_source"]),
        "by_source": len({item.source for item in items}) >= 2,
    }
    if _present(index_text) != index_expected:
        violations.add("index.md")
    return violations


def _axis_coverage(db):
    """For each axis, the set of booleans observed across all compiled pages — both
    {True, False} must appear for the iff to be non-trivial."""
    seen = {axis: set() for axis in _AXES}
    for _, _, text in _custody_pages(db):
        present = _present(text)
        for axis in _AXES:
            seen[axis].add(present[axis])
    return seen


def test_a_clean_library_compiles_no_fabricated_action_pointers(scrolls_home, capsys):
    """Over a clean multi-source library every compiled page shows the `_Custody:`
    headline and never an `_Attention:`/`_Refresh:` pointer — tied to `doctor`'s
    empty `attention`/`enrichment`/`summaries` bases (H190's honest-absence test,
    lifted to every page kind)."""
    main(["init"])
    db = get_paths().db_path
    _seed_clean_fixture(db)
    assert main(["kb"]) == 0
    capsys.readouterr()  # drop the `kb` summary so the status read below is clean

    # the JSON bases the pointers would need are all empty
    custody = run_doctor(get_paths())["custody"]
    assert custody["enrichment"]["by_source"] == {}
    assert custody["summaries"]["by_source"] == {}
    assert main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["attention"] is None

    # so no compiled page fabricates a pointer, and every page carries the headline
    for _, relpath, text in _custody_pages(db):
        assert "_Custody:" in text, relpath
        assert "_Attention:" not in text, relpath
        assert "_Refresh:" not in text, relpath
    assert _honesty_violations(capsys) == set()


def test_every_compiled_page_renders_its_action_pointers_honestly(scrolls_home, capsys):
    """Over the drift/stale-debt fixture every custody-bearing page kind renders its
    `_Custody:`/`_By source:`/`_Attention:`/`_Refresh:` lines iff its scope warrants
    them — the whole matrix pinned at once, with each axis non-vacuous (present on
    ≥1 page, absent on ≥1) and the `_Refresh:` clause per-axis honest (the
    classifications clause appears, the summaries clause never does — no stored
    summary basis, H190's per-axis honesty)."""
    main(["init"])
    db = get_paths().db_path
    _seed_debt_fixture(db)
    assert main(["kb"]) == 0

    # every registered custody-bearing kind actually produced a page in the fixture
    # (so a forgotten `_group_pages` enumeration can't silently skip a kind)
    covered = {kind for kind, _, _ in _custody_pages(db)}
    assert covered == _CUSTODY_BEARING_DIRS | _CUSTODY_BEARING_FILES

    coverage = _axis_coverage(db)
    assert coverage["custody"] == {True}  # the headline is on every page
    for axis in ("attention", "refresh", "by_source"):
        assert coverage[axis] == {True, False}, (axis, coverage[axis])

    assert _honesty_violations(capsys) == set()

    blob = "\n".join(text for _, _, text in _custody_pages(db))
    assert "classifications stale in" in blob  # the axis with a basis renders
    assert "summaries stale in" not in blob  # the axis with no basis is omitted


def test_dropping_the_by_source_split_fails_only_the_multi_source_kinds(
    scrolls_home, capsys, monkeypatch
):
    """The sabotage proves the matrix has teeth and isolates to the broken seam:
    dropping the shared `_By source:` split fails *only* the kinds that have a
    multi-source page (`index.md`/`categories`/`concepts`/`tags`), never the
    single-source-only `sources` kind — whose pages have no split to drop, so its
    honest-absence is a genuine no-op (the H403 selector-isolation precedent)."""
    main(["init"])
    db = get_paths().db_path
    _seed_debt_fixture(db)
    assert main(["kb"]) == 0

    # baseline: every page honest
    assert _honesty_violations(capsys) == set()

    # a compiler that silently drops the multi-source `_By source:` split
    monkeypatch.setattr(kb, "render_custody_by_source", lambda *a, **k: [])
    assert main(["kb"]) == 0

    assert _honesty_violations(capsys) == {
        "index.md", "categories", "concepts", "tags"}
