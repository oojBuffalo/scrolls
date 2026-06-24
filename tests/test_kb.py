"""Tests for the compiled library (IDEAS.md §9, §14 Pass 5)."""

import json

import pytest

from scrolls.cli import main
from scrolls.custody import CustodyEvent, record_events
from scrolls.generated import generated_body
from scrolls.items import ScrollItem, insert_item, update_item
from scrolls.kb import compile_kb
from scrolls.paths import get_paths


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


def make_rendered(item_id, source, title, *, category=None, concepts=(), tags=(),
                  links=(), saved_at="2026-06-01T00:00:00+00:00", markdown_path=None,
                  source_id=None, url=None, raw_text=None, content_hash=None,
                  provenance=None):
    slug = title.lower().replace(" ", "-")
    return ScrollItem(
        id=item_id,
        source=source,
        source_id=source_id,
        url=url or f"https://example.org/{item_id}",
        saved_at=saved_at,
        title=title,
        category=category,
        concepts=tuple(concepts),
        tags=tuple(tags),
        links=tuple(links),
        markdown_path=markdown_path or f"scrolls/{source}/{slug}.md",
        stage="rendered",
        raw_text=raw_text,
        content_hash=content_hash,
        provenance=provenance,
    )


def run_kb(capsys):
    exit_code = main(["kb"])
    assert exit_code == 0
    return json.loads(capsys.readouterr().out)


def test_kb_before_init_reports_zero_pages(scrolls_home, capsys):
    payload = run_kb(capsys)
    assert payload == {"items": 0, "sources": 0, "categories": 0, "concepts": 0, "tags": 0, "summaries": 0, "clusters": 0, "works": 0, "pages": 0}
    assert not scrolls_home.exists()  # kb never creates a library


def test_compile_kb_missing_db_writes_nothing(tmp_path):
    paths = get_paths(tmp_path / "nope")
    result = compile_kb(paths)
    assert result.pages == 0
    assert not (tmp_path / "nope").exists()


def test_kb_compiles_index_source_and_category_pages(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "wikipedia:en:SQLite", "wikipedia", "SQLite", category="reference"))
    insert_item(db, make_rendered(
        "youtube:abc123", "youtube", "How SQLite FTS Works", category="media"))
    # detected-but-unrendered items have no scroll file to link to
    insert_item(db, ScrollItem(
        id="github:o/r", source="github", url="https://github.com/o/r",
        saved_at="2026-06-02T00:00:00+00:00"))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload == {"items": 2, "sources": 2, "categories": 2, "concepts": 0, "tags": 0, "summaries": 0, "clusters": 0, "works": 0, "pages": 7}

    library = scrolls_home / "library"
    index = (library / "index.md").read_text(encoding="utf-8")
    assert "# Scrolls Library" in index
    assert "2 scrolls from 2 sources." in index
    assert "- [wikipedia](sources/wikipedia.md) — 1 scroll" in index
    assert "- [youtube](sources/youtube.md) — 1 scroll" in index
    assert "- [reference](categories/reference.md) — 1 scroll" in index
    assert "- [media](categories/media.md) — 1 scroll" in index
    assert "github" not in index

    source_page = (library / "sources" / "wikipedia.md").read_text(encoding="utf-8")
    assert "# Source: wikipedia" in source_page
    assert "1 scroll." in source_page
    assert "- [SQLite](../../scrolls/wikipedia/sqlite.md) — reference" in source_page

    category_page = (library / "categories" / "reference.md").read_text(encoding="utf-8")
    assert "# Category: reference" in category_page
    assert "- [SQLite](../../scrolls/wikipedia/sqlite.md) — wikipedia" in category_page


def test_kb_index_links_recent_scrolls_newest_first(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    for index in range(12):
        insert_item(db, make_rendered(
            f"web:item{index:02d}", "web", f"Post {index:02d}",
            saved_at=f"2026-06-{index + 1:02d}T00:00:00+00:00"))
    capsys.readouterr()

    run_kb(capsys)
    index_text = generated_body(
        (scrolls_home / "library" / "index.md").read_text(encoding="utf-8"))
    recent = index_text.split("## Recent\n")[1].strip().splitlines()
    assert len(recent) == 10  # capped
    assert recent[0] == "- [Post 11](../scrolls/web/post-11.md)"
    assert recent[-1] == "- [Post 02](../scrolls/web/post-02.md)"


def test_kb_counts_unclassified_items_in_index(scrolls_home, capsys):
    main(["init"])
    insert_item(get_paths().db_path, make_rendered("web:abc", "web", "An ordinary post"))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload == {"items": 1, "sources": 1, "categories": 0, "concepts": 0, "tags": 0, "summaries": 0, "clusters": 0, "works": 0, "pages": 4}
    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    assert "- unclassified — 1 scroll" in index
    assert not (scrolls_home / "library" / "categories").exists()


def test_kb_groups_concepts_across_spellings(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "wikipedia:en:Okapi_BM25", "wikipedia", "Okapi BM25", concepts=("BM25",)))
    insert_item(db, make_rendered(
        "web:fts", "web", "FTS in practice", concepts=("bm25", "SQLite")))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload["concepts"] == 2

    library = scrolls_home / "library"
    concept_page = (library / "concepts" / "bm25.md").read_text(encoding="utf-8")
    assert "# Concept: BM25" in concept_page  # spellings merge; one display form
    assert "- [FTS in practice](../../scrolls/web/fts-in-practice.md) — web" in concept_page
    assert "- [Okapi BM25](../../scrolls/wikipedia/okapi-bm25.md) — wikipedia" in concept_page

    index = (library / "index.md").read_text(encoding="utf-8")
    assert "- [BM25](concepts/bm25.md) — 2 scrolls" in index
    assert "- [SQLite](concepts/sqlite.md) — 1 scroll" in index


def test_kb_concept_page_lists_related_concepts(scrolls_home, capsys):
    """A concept page names the concepts that co-occur on its member scrolls."""
    main(["init"])
    db = get_paths().db_path
    # BM25 co-occurs with full-text search on two scrolls, with SQLite on one.
    insert_item(db, make_rendered(
        "web:a", "web", "FTS deep dive",
        concepts=("BM25", "Full-text search", "SQLite")))
    insert_item(db, make_rendered(
        "web:b", "web", "Ranking notes", concepts=("BM25", "Full-text search")))
    capsys.readouterr()

    run_kb(capsys)
    page = generated_body(
        (scrolls_home / "library" / "concepts" / "bm25.md").read_text(encoding="utf-8"))
    assert "## Related Concepts" in page
    related = page.split("## Related Concepts\n")[1].strip().splitlines()
    # ordered by shared-scroll count descending (strength), link relative to siblings
    assert related == [
        "- [Full-text search](full-text-search.md) — 2 shared scrolls",
        "- [SQLite](sqlite.md) — 1 shared scroll",
    ]


def test_kb_concept_page_without_co_occurrence_omits_related_section(scrolls_home, capsys):
    """A concept whose member scrolls carry no other concept gets no section."""
    main(["init"])
    insert_item(get_paths().db_path, make_rendered(
        "web:solo", "web", "Lonely topic", concepts=("Solitude",)))
    capsys.readouterr()

    run_kb(capsys)
    page = (scrolls_home / "library" / "concepts" / "solitude.md").read_text(encoding="utf-8")
    assert "## Related Concepts" not in page


def test_related_concepts_merges_spellings_and_caps(scrolls_home):
    """The pure co-occurrence map merges by slug, counts scrolls, and caps."""
    from scrolls.kb import group_concepts, related_concepts

    items = [
        # hub concept "RAG" co-occurs with 12 distinct neighbours (one scroll each)
        make_rendered(f"web:n{i:02d}", "web", f"Note {i:02d}", concepts=("RAG", f"Topic {i:02d}"))
        for i in range(12)
    ]
    # a spelling variant of RAG that slugifies the same must not self-relate
    items.append(make_rendered("web:variant", "web", "rag variant", concepts=("rag", "Topic 00")))

    by_concept = group_concepts(items)
    related = related_concepts(by_concept, limit=10)

    rag = related["rag"]
    assert len(rag) == 10  # capped from 12 neighbours
    assert all(slug != "rag" for slug, _display, _shared in rag)  # never self-relates
    # Topic 00 appears on two RAG scrolls (Note 00 and the variant), the rest on one,
    # so it ranks first by shared-scroll count.
    assert rag[0] == ("topic-00", "Topic 00", 2)


def test_kb_compiles_tag_pages(scrolls_home, capsys):
    """Tags get browsable pages and an index section, like concepts (ADR 0064)."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "arxiv:1706.03762", "arxiv", "Attention Is All You Need",
        category="paper", tags=("cs.CL", "cs.LG")))
    insert_item(db, make_rendered(
        "arxiv:1409.0473", "arxiv", "Neural Machine Translation",
        category="paper", tags=("cs.CL",)))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload["tags"] == 2

    library = scrolls_home / "library"
    tag_page = (library / "tags" / "cs-cl.md").read_text(encoding="utf-8")
    assert "# Tag: cs.CL" in tag_page
    assert "2 scrolls." in tag_page
    assert "- [Attention Is All You Need](../../scrolls/arxiv/attention-is-all-you-need.md) — arxiv" in tag_page
    assert "- [Neural Machine Translation](../../scrolls/arxiv/neural-machine-translation.md) — arxiv" in tag_page

    index = (library / "index.md").read_text(encoding="utf-8")
    assert "- [cs.CL](tags/cs-cl.md) — 2 scrolls" in index
    assert "- [cs.LG](tags/cs-lg.md) — 1 scroll" in index


def test_kb_groups_tags_case_insensitively_but_keeps_distinct_folds(scrolls_home, capsys):
    """`MIT`/`mit` merge to one page; `C++`/`C#` share a slug yet stay separate."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered("pypi:flask", "pypi", "Flask", tags=("MIT",)))
    insert_item(db, make_rendered("npm:express", "npm", "express", tags=("mit",)))
    insert_item(db, make_rendered("bitbucket:o/cpp", "bitbucket", "cpp repo", tags=("C++",)))
    insert_item(db, make_rendered("bitbucket:o/csharp", "bitbucket", "csharp repo", tags=("C#",)))
    capsys.readouterr()

    payload = run_kb(capsys)
    # MIT+mit merge → one tag; C++ and C# both slugify to "c" but are distinct folds → two tags
    assert payload["tags"] == 3

    library = scrolls_home / "library"
    mit_page = (library / "tags" / "mit.md").read_text(encoding="utf-8")
    assert "# Tag: MIT" in mit_page  # smallest spelling is the display form
    assert "2 scrolls." in mit_page

    # the two C-family tags collide on slug "c"; the second sorted key gets "-2"
    tag_files = sorted(p.name for p in (library / "tags").glob("*.md"))
    assert "c.md" in tag_files and "c-2.md" in tag_files
    index = (library / "index.md").read_text(encoding="utf-8")
    assert "- [C#](tags/c.md) — 1 scroll" in index   # "c#" sorts before "c++"
    assert "- [C++](tags/c-2.md) — 1 scroll" in index


def test_kb_tag_page_lists_related_tags(scrolls_home, capsys):
    """A tag page names the tags that co-occur on its member scrolls (ADR 0064)."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "pypi:a", "pypi", "Package A", tags=("MIT", "Python", "CLI")))
    insert_item(db, make_rendered(
        "pypi:b", "pypi", "Package B", tags=("MIT", "Python")))
    capsys.readouterr()

    run_kb(capsys)
    page = generated_body(
        (scrolls_home / "library" / "tags" / "mit.md").read_text(encoding="utf-8"))
    assert "## Related Tags" in page
    related = page.split("## Related Tags\n")[1].strip().splitlines()
    assert related == [
        "- [Python](python.md) — 2 shared scrolls",
        "- [CLI](cli.md) — 1 shared scroll",
    ]


def test_kb_tag_page_without_co_occurrence_omits_related_section(scrolls_home, capsys):
    """A tag whose member scrolls carry no other tag gets no Related Tags section."""
    main(["init"])
    insert_item(get_paths().db_path, make_rendered(
        "pypi:solo", "pypi", "Lonely package", tags=("Unlicense",)))
    capsys.readouterr()

    run_kb(capsys)
    page = (scrolls_home / "library" / "tags" / "unlicense.md").read_text(encoding="utf-8")
    assert "## Related Tags" not in page


def test_related_tags_co_occurrence_folds_case_and_caps(scrolls_home):
    """The pure tag co-occurrence map merges by case-fold, counts scrolls, and caps."""
    from scrolls.kb import group_tags, related_tags

    items = [
        make_rendered(f"pypi:n{i:02d}", "pypi", f"Pkg {i:02d}", tags=("Python", f"lib{i:02d}"))
        for i in range(12)
    ]
    # a case variant of Python that must merge, not self-relate
    items.append(make_rendered("pypi:variant", "pypi", "py variant", tags=("python", "lib00")))

    by_tag = group_tags(items)
    related = related_tags(by_tag, limit=10)

    python = related["python"]
    assert len(python) == 10  # capped from 12 neighbours
    assert all(key != "python" for key, _display, _shared in python)  # never self-relates
    assert python[0] == ("lib00", "lib00", 2)  # lib00 co-occurs on two Python scrolls


# --- per-item custody markers on the list pages (roadmap H89) -------------


def _drift(db, item_id, status, *, checked_at="2026-06-10T00:00:00+00:00"):
    """Seed one latest custody verdict so a list-page row shows a posture."""
    record_events(db, [CustodyEvent(
        item_id=item_id, checked_at=checked_at, status=status,
        prior_hash="old", observed_hash="new" if status == "drifted" else None)])


def test_kb_list_pages_carry_per_item_custody_markers(scrolls_home, capsys):
    """Each source/category page row carries `· <fidelity> · <drift>`."""
    main(["init"])
    db = get_paths().db_path
    # a full-fidelity capture (re-derivable body + hash) and a reference-only one
    insert_item(db, make_rendered(
        "wikipedia:en:SQLite", "wikipedia", "SQLite", category="reference",
        raw_text="full body", content_hash="h1"))
    insert_item(db, make_rendered(
        "web:pointer", "wikipedia", "A pointer", category="reference"))
    capsys.readouterr()
    run_kb(capsys)

    source_page = (scrolls_home / "library" / "sources" / "wikipedia.md").read_text(
        encoding="utf-8")
    # marker trails the existing note (the category here), never replaces it;
    # a never-checked item is honestly `unverified`, never silently "clean"
    assert ("- [SQLite](../../scrolls/wikipedia/sqlite.md) — reference"
            " · full · unverified") in source_page
    assert ("- [A pointer](../../scrolls/wikipedia/a-pointer.md) — reference"
            " · reference · unverified") in source_page

    category_page = (scrolls_home / "library" / "categories" / "reference.md").read_text(
        encoding="utf-8")
    assert ("- [SQLite](../../scrolls/wikipedia/sqlite.md) — wikipedia"
            " · full · unverified") in category_page


def test_kb_list_page_marker_reflects_the_drift_ledger(scrolls_home, capsys):
    """The drift half of a row's marker is the item's latest ledger verdict."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "web:drifted", "web", "Moved post", category="news",
        raw_text="body", content_hash="h1"))
    insert_item(db, make_rendered(
        "web:clean", "web", "Steady post", category="news",
        raw_text="body", content_hash="h2"))
    _drift(db, "web:drifted", "drifted")
    _drift(db, "web:clean", "unchanged")  # `unchanged` reads as the `verified` posture
    capsys.readouterr()
    run_kb(capsys)

    page = (scrolls_home / "library" / "categories" / "news.md").read_text(
        encoding="utf-8")
    assert ("- [Moved post](../../scrolls/web/moved-post.md) — web"
            " · full · drifted") in page
    assert ("- [Steady post](../../scrolls/web/steady-post.md) — web"
            " · full · verified") in page


def test_kb_concept_and_tag_pages_carry_custody_markers(scrolls_home, capsys):
    """Concept and tag list pages carry the same per-row custody marker."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "web:a", "web", "FTS deep dive", concepts=("BM25",), tags=("search",),
        raw_text="body", content_hash="h1"))
    _drift(db, "web:a", "rotted")
    capsys.readouterr()
    run_kb(capsys)

    library = scrolls_home / "library"
    concept_page = (library / "concepts" / "bm25.md").read_text(encoding="utf-8")
    assert ("- [FTS deep dive](../../scrolls/web/fts-deep-dive.md) — web"
            " · full · rotted") in concept_page
    tag_page = (library / "tags" / "search.md").read_text(encoding="utf-8")
    assert ("- [FTS deep dive](../../scrolls/web/fts-deep-dive.md) — web"
            " · full · rotted") in tag_page


def test_kb_category_consolidated_representations_carry_custody_markers(scrolls_home, capsys):
    """A consolidated work's nested representation bullets carry the marker too."""
    main(["init"])
    db = get_paths().db_path
    doi_url = "https://doi.org/10.1234/abc"
    insert_item(db, make_rendered(
        "arxiv:1", "arxiv", "A Paper (preprint)", category="ml",
        links=(doi_url,), raw_text="body", content_hash="h1"))
    insert_item(db, make_rendered(
        "crossref:1", "crossref", "A Paper", category="ml",
        links=(doi_url,), raw_text="body", content_hash="h2"))
    _drift(db, "arxiv:1", "drifted")
    capsys.readouterr()
    run_kb(capsys)

    page = (scrolls_home / "library" / "categories" / "ml.md").read_text(encoding="utf-8")
    # consolidated under one work heading; each rep is a nested bullet with a marker
    assert "  - [A Paper (preprint)](../../scrolls/arxiv/a-paper-(preprint).md) — arxiv" \
        " · full · drifted" in page
    assert "  - [A Paper](../../scrolls/crossref/a-paper.md) — crossref" \
        " · full · unverified" in page


def test_kb_custody_markers_are_refresh_safe(scrolls_home, capsys):
    """A re-verify refreshes the marker on recompile; an annotation survives."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "web:x", "web", "A post", category="news", raw_text="body", content_hash="h1"))
    capsys.readouterr()
    run_kb(capsys)

    page_path = scrolls_home / "library" / "categories" / "news.md"
    page = page_path.read_text(encoding="utf-8")
    assert "· full · unverified · never checked" in page
    # the marker lives inside the generated fence (it is part of the body)
    assert "· full · unverified · never checked" in generated_body(page)
    # a human annotation appended outside the fence
    page_path.write_text(page + "\n\n_My note._\n", encoding="utf-8")

    # the source drifts and is re-verified, then the library recompiles
    _drift(db, "web:x", "drifted", checked_at="2026-06-12T00:00:00+00:00")
    run_kb(capsys)
    refreshed = page_path.read_text(encoding="utf-8")
    # both axes refresh in the fenced region: the posture *and* its timestamp
    assert "· full · drifted · checked 2026-06-12T00:00:00+00:00" in refreshed
    assert "· full · unverified · never checked" not in refreshed
    assert "_My note._" in refreshed  # annotation outside the fence preserved


def test_kb_list_page_marker_carries_last_checked_timestamp(scrolls_home, capsys):
    """The marker's time axis (roadmap H93): `· checked <ts>` for a row with a
    ledger verdict, `· never checked` for one with none (honest absence)."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "web:seen", "web", "Checked post", category="news",
        raw_text="body", content_hash="h1"))
    insert_item(db, make_rendered(
        "web:never", "web", "New post", category="news",
        raw_text="body", content_hash="h2"))
    _drift(db, "web:seen", "drifted", checked_at="2026-06-14T00:00:00+00:00")
    capsys.readouterr()
    run_kb(capsys)

    page = (scrolls_home / "library" / "categories" / "news.md").read_text(
        encoding="utf-8")
    # a checked row trails the verbatim ledger timestamp — the time-axis sibling
    # of the drift posture, the same `checked_at` the `history` head and the JSON
    # browse rows show; a never-checked row is honestly `never checked`, never a
    # faked time (the `null`/`unverified` honest-absence counterpart)
    assert ("- [Checked post](../../scrolls/web/checked-post.md) — web"
            " · full · drifted · checked 2026-06-14T00:00:00+00:00") in page
    assert ("- [New post](../../scrolls/web/new-post.md) — web"
            " · full · unverified · never checked") in page


def test_kb_index_and_graph_pages_omit_the_custody_marker(scrolls_home, capsys):
    """The marker is scoped to the group list pages, not the index/graph rollups."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "web:x", "web", "A post", category="news", raw_text="body", content_hash="h1"))
    _drift(db, "web:x", "drifted")
    capsys.readouterr()
    run_kb(capsys)

    library = scrolls_home / "library"
    index = (library / "index.md").read_text(encoding="utf-8")
    recent = generated_body(index).split("## Recent\n")[1]
    assert "- [A post](../scrolls/web/a-post.md)" in recent
    assert "· full · drifted" not in recent  # index Recent teaser stays a bare row


# --- scope custody headline on the compiled group list pages (roadmap H95) ---


def test_kb_group_pages_carry_a_scope_custody_headline(scrolls_home, capsys):
    """Each group list page carries a `_Custody:_` headline under its count line,
    summarising how custody stands across that page's members — totals equal to
    the page's own per-row markers, via the shared `custody.custody_headline`."""
    from scrolls.custody import custody_headline, latest_events
    from scrolls.items import list_items

    main(["init"])
    db = get_paths().db_path
    # a fidelity/drift mix on one source page: a full+drifted and a reference+never
    insert_item(db, make_rendered(
        "web:moved", "web", "Moved post", category="news",
        raw_text="body", content_hash="h1"))
    insert_item(db, make_rendered(
        "web:pointer", "web", "A pointer", category="news"))  # reference fidelity
    _drift(db, "web:moved", "drifted")
    capsys.readouterr()
    run_kb(capsys)

    page = (scrolls_home / "library" / "sources" / "web.md").read_text(encoding="utf-8")
    # the headline reads byte-identically to the shared primitive over the page's
    # members — so the human-readable scope summary can never disagree with the
    # bundle/context/`status` headlines that share `custody_headline`
    members = [i for i in list_items(db) if i.source == "web"]
    expected = custody_headline(members, latest_events(db))
    assert expected == (
        "_Custody: 2 scroll(s) · fidelity full 1, reference 1"
        " · drift unverified 1, drifted 1._")
    # under the count line, before the first bullet
    body = page.split("2 scrolls.\n\n")[1]
    assert body.startswith(expected + "\n\n- [")


def test_kb_group_page_headline_totals_match_the_per_row_markers(scrolls_home, capsys):
    """The headline's tier/posture totals equal the sum of the page's per-row
    `· <fidelity> · <drift>` markers — convergence by construction (H89 ↔ H95)."""
    import re

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "web:a", "web", "Alpha", category="news", raw_text="b", content_hash="h1"))
    insert_item(db, make_rendered(
        "web:b", "web", "Beta", category="news", raw_text="b", content_hash="h2"))
    insert_item(db, make_rendered("web:c", "web", "Gamma", category="news"))
    _drift(db, "web:a", "drifted")
    _drift(db, "web:b", "unchanged")  # reads as `verified`
    capsys.readouterr()
    run_kb(capsys)

    body = generated_body(
        (scrolls_home / "library" / "categories" / "news.md").read_text(encoding="utf-8"))
    headline = next(l for l in body.splitlines() if l.startswith("_Custody:"))
    # tally the per-row markers off the page
    rows = re.findall(r"· (\w+) · (\w+) · (?:checked \S+|never checked)", body)
    fid_total = {}
    drift_total = {}
    for fid, drift in rows:
        fid_total[fid] = fid_total.get(fid, 0) + 1
        drift_total[drift] = drift_total.get(drift, 0) + 1
    assert fid_total == {"full": 2, "reference": 1}
    assert drift_total == {"drifted": 1, "verified": 1, "unverified": 1}
    # the headline names exactly those non-zero totals
    assert headline == (
        "_Custody: 3 scroll(s) · fidelity full 2, reference 1"
        " · drift verified 1, unverified 1, drifted 1._")


def test_kb_group_page_headline_is_refresh_safe(scrolls_home, capsys):
    """A re-verify refreshes the headline on recompile; an annotation survives."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "web:x", "web", "A post", category="news", raw_text="body", content_hash="h1"))
    capsys.readouterr()
    run_kb(capsys)

    page_path = scrolls_home / "library" / "categories" / "news.md"
    page = page_path.read_text(encoding="utf-8")
    assert "_Custody: 1 scroll(s) · fidelity full 1 · drift unverified 1._" in page
    assert "_Custody: 1 scroll(s)" in generated_body(page)  # inside the fence
    page_path.write_text(page + "\n\n_My note._\n", encoding="utf-8")

    _drift(db, "web:x", "drifted")
    run_kb(capsys)
    refreshed = page_path.read_text(encoding="utf-8")
    # the posture count moved unverified → drifted; the headline refreshed in-fence
    assert "_Custody: 1 scroll(s) · fidelity full 1 · drift drifted 1._" in refreshed
    assert "drift unverified 1" not in refreshed
    assert "_My note._" in refreshed  # annotation outside the fence preserved


def test_kb_graph_and_works_pages_omit_the_scope_custody_headline(scrolls_home, capsys):
    """The page-scoped headline is on the four group list pages; `graph`/`works`
    are not member lists, so they carry no *scope* headline. The index carries its
    own *whole-library* headline (roadmap H96), not a page-scoped one. `works.md`
    does carry per-work `_Custody:` *markers* (roadmap H270) — a different line
    (`_Custody: best held …`), never the scope headline (`_Custody: N scroll(s) …`)."""
    main(["init"])
    db = get_paths().db_path
    doi_url = "https://doi.org/10.1234/abc"
    insert_item(db, make_rendered(
        "arxiv:1", "arxiv", "A Paper (preprint)", category="ml",
        links=(doi_url,), raw_text="body", content_hash="h1"))
    insert_item(db, make_rendered(
        "crossref:1", "crossref", "A Paper", category="ml",
        links=(doi_url,), raw_text="body", content_hash="h2"))
    _drift(db, "arxiv:1", "drifted")
    capsys.readouterr()
    run_kb(capsys)

    library = scrolls_home / "library"
    # the scope headline (`_Custody: N scroll(s) · …`) is absent from both rollups;
    # `works.md`'s per-work markers (`_Custody: best held …`) carry no `scroll(s)`
    for rollup in ("graph.md", "works.md"):
        assert "scroll(s)" not in (library / rollup).read_text(encoding="utf-8"), rollup
    # graph carries no `_Custody:` of any kind (not a member list, no works)
    assert "_Custody:" not in (library / "graph.md").read_text(encoding="utf-8")
    # the group pages and the index landing page do carry a custody headline
    assert "_Custody:" in (library / "categories" / "ml.md").read_text(encoding="utf-8")
    assert "_Custody:" in (library / "index.md").read_text(encoding="utf-8")


def test_kb_index_carries_a_library_wide_custody_headline(scrolls_home, capsys):
    """The landing `index.md` carries a whole-library `_Custody:_` headline (the
    compiled counterpart of `scrolls status`, roadmap H96), over the rendered
    library it heads — byte-identical to the shared `custody.custody_headline`."""
    from scrolls.custody import custody_headline, latest_events
    from scrolls.items import list_items

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "web:a", "web", "Alpha", category="news", raw_text="b", content_hash="h1"))
    insert_item(db, make_rendered(
        "web:b", "web", "Beta", category="news", raw_text="b", content_hash="h2"))
    insert_item(db, make_rendered("wikipedia:x", "wikipedia", "Pointer", category="ref"))
    _drift(db, "web:a", "drifted")
    capsys.readouterr()
    run_kb(capsys)

    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    rendered = [i for i in list_items(db) if i.markdown_path]
    expected = custody_headline(rendered, latest_events(db))
    assert expected == (
        "_Custody: 3 scroll(s) · fidelity full 2, reference 1"
        " · drift unverified 2, drifted 1._")
    # it sits in the header block, right after the works line, before ## Sources
    header = index.split("## Sources")[0]
    assert expected in header
    # and converges with `doctor`'s custody aggregate (all three items rendered)
    capsys.readouterr()
    main(["doctor"])
    custody = json.loads(capsys.readouterr().out)["custody"]
    assert custody["tiers"] == {"full": 2, "partial": 0, "reference": 1}
    assert custody["drift"]["drifted"] == 1


def test_kb_empty_library_index_has_honest_custody_headline(scrolls_home, capsys):
    """An initialized but empty library's index carries the honest zero headline."""
    main(["init"])
    capsys.readouterr()
    run_kb(capsys)
    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    assert "_Custody: 0 scroll(s)._" in index


def test_kb_index_carries_a_per_source_custody_breakdown(scrolls_home, capsys):
    """A multi-source compiled index carries a `_By source:_` breakdown under the
    whole-library headline (roadmap H145), byte-identical to the shared
    `custody.render_custody_by_source` and summing to the headline by construction."""
    from scrolls.custody import (
        custody_counts_by_source,
        latest_events,
        render_custody_by_source,
    )
    from scrolls.items import list_items

    main(["init"])
    db = get_paths().db_path
    # web: a full+drifted and a reference+never; arxiv: a full+never
    insert_item(db, make_rendered(
        "web:a", "web", "Alpha", category="news", raw_text="b", content_hash="h1"))
    insert_item(db, make_rendered("web:b", "web", "Beta", category="news"))
    insert_item(db, make_rendered(
        "arxiv:1", "arxiv", "A Paper", category="ml", raw_text="b", content_hash="h3"))
    _drift(db, "web:a", "drifted")
    capsys.readouterr()
    run_kb(capsys)

    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    rendered = [i for i in list_items(db) if i.markdown_path]
    expected = render_custody_by_source(custody_counts_by_source(rendered, latest_events(db)))
    assert expected == [
        "_By source:_",
        "",
        "- `arxiv` — 1 scroll(s) · fidelity full 1 · drift unverified 1"
        " · coverage 0/1",
        "- `web` — 2 scroll(s) · fidelity full 1, reference 1"
        " · drift unverified 1, drifted 1 · coverage 1/1",
        "",
    ]
    # the breakdown sits under the headline, before ## Sources
    header = index.split("## Sources")[0]
    assert "_By source:_" in header
    for line in expected[:-1]:  # the bullets (the trailing spacer is dropped)
        assert line in header
    # and the headline precedes the breakdown in the header block
    assert header.index("_Custody:") < header.index("_By source:_")


def test_kb_index_per_source_breakdown_sums_to_the_headline(scrolls_home, capsys):
    """Each per-source bullet's tier/posture counts sum to the index headline's
    totals — convergence by construction (every scroll lands in one source)."""
    import re

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "web:a", "web", "Alpha", category="news", raw_text="b", content_hash="h1"))
    insert_item(db, make_rendered("web:b", "web", "Beta", category="news"))
    insert_item(db, make_rendered(
        "arxiv:1", "arxiv", "A Paper", category="ml", raw_text="b", content_hash="h3"))
    _drift(db, "web:a", "drifted")
    capsys.readouterr()
    run_kb(capsys)

    header = (scrolls_home / "library" / "index.md").read_text(
        encoding="utf-8").split("## Sources")[0]
    # tally the per-source bullets' fidelity counts (sections read `<tier> <count>`)
    fid_total: dict[str, int] = {}
    for bullet in re.findall(r"^- `\w+` — .*$", header, re.MULTILINE):
        for tier, count in re.findall(r"(full|partial|reference) (\d+)", bullet):
            fid_total[tier] = fid_total.get(tier, 0) + int(count)
    # the headline names exactly those non-zero totals (2 full, 1 reference)
    assert fid_total == {"full": 2, "reference": 1}
    assert "_Custody: 3 scroll(s) · fidelity full 2, reference 1" in header


def test_kb_index_single_source_omits_the_per_source_breakdown(scrolls_home, capsys):
    """A single-source library's index carries the headline but no `_By source:_`
    split — the whole-library headline already says everything (the helper no-op)."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered("web:a", "web", "Alpha", category="news"))
    insert_item(db, make_rendered("web:b", "web", "Beta", category="news"))
    capsys.readouterr()
    run_kb(capsys)

    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    assert "_Custody:" in index
    assert "_By source:_" not in index


def test_kb_index_per_source_breakdown_is_refresh_safe(scrolls_home, capsys):
    """A re-verify refreshes the per-source breakdown on recompile, inside the
    `@generated` fence; an annotation outside the fence survives."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "web:a", "web", "Alpha", category="news", raw_text="b", content_hash="h1"))
    insert_item(db, make_rendered("arxiv:1", "arxiv", "A Paper", category="ml"))
    capsys.readouterr()
    run_kb(capsys)

    index_path = scrolls_home / "library" / "index.md"
    page = index_path.read_text(encoding="utf-8")
    assert "- `web` — 1 scroll(s) · fidelity full 1 · drift unverified 1" in page
    assert "_By source:_" in generated_body(page)  # inside the fence
    index_path.write_text(page + "\n\n_My note._\n", encoding="utf-8")

    _drift(db, "web:a", "drifted")
    run_kb(capsys)
    refreshed = index_path.read_text(encoding="utf-8")
    # the web posture moved unverified → drifted; its bullet refreshed in-fence
    # (arxiv is reference-only and never re-checked, so it stays unverified)
    assert "- `web` — 1 scroll(s) · fidelity full 1 · drift drifted 1" in refreshed
    assert "- `web` — 1 scroll(s) · fidelity full 1 · drift unverified 1" not in refreshed
    assert "_My note._" in refreshed  # annotation outside the fence preserved


def test_kb_multi_source_group_page_carries_a_per_source_breakdown(scrolls_home, capsys):
    """A multi-source group list page (a category over arxiv + web) carries a
    `_By source:_` breakdown under its scope headline (roadmap H152) — byte-identical
    to the shared `custody.render_custody_by_source` over the page's members, and
    sitting under the headline before the first item bullet."""
    from scrolls.custody import (
        custody_counts_by_source,
        latest_events,
        render_custody_by_source,
    )
    from scrolls.items import list_items

    main(["init"])
    db = get_paths().db_path
    # category `ml` spans two sources: arxiv (full+drifted) and web
    # (a full+verified and a reference+never) — no shared DOI, so no consolidation
    insert_item(db, make_rendered(
        "arxiv:1", "arxiv", "A Paper", category="ml", raw_text="b", content_hash="h1"))
    insert_item(db, make_rendered(
        "web:a", "web", "Alpha", category="ml", raw_text="b", content_hash="h2"))
    insert_item(db, make_rendered("web:b", "web", "Beta", category="ml"))
    _drift(db, "arxiv:1", "drifted")
    _drift(db, "web:a", "unchanged")  # reads as `verified`
    capsys.readouterr()
    run_kb(capsys)

    page = (scrolls_home / "library" / "categories" / "ml.md").read_text(encoding="utf-8")
    members = [i for i in list_items(db) if i.category == "ml"]
    verdicts = latest_events(db)
    expected = render_custody_by_source(custody_counts_by_source(members, verdicts))
    assert expected == [
        "_By source:_",
        "",
        "- `arxiv` — 1 scroll(s) · fidelity full 1 · drift drifted 1"
        " · coverage 1/1",
        "- `web` — 2 scroll(s) · fidelity full 1, reference 1"
        " · drift verified 1, unverified 1 · coverage 1/1",
        "",
    ]
    # the breakdown sits under the page headline; the `_Attention:_` pointer
    # (H184) — arxiv carries the drift — now sits between them, before `_By source:_`
    headline = "_Custody: 3 scroll(s) · fidelity full 2, reference 1" \
        " · drift verified 1, unverified 1, drifted 1._"
    attention = (
        "_Attention: source `arxiv` carries the most drift (1 drifted) — "
        "recheck with `scrolls verify --source arxiv`._"
    )
    body = page.split("3 scrolls.\n\n")[1]
    assert body.startswith(headline + "\n\n" + attention + "\n\n_By source:_")
    assert (headline + "\n\n" + attention + "\n\n" + "\n".join(expected)) in body


def test_kb_group_page_per_source_breakdown_sums_to_the_page_headline(scrolls_home, capsys):
    """Each per-source bullet's fidelity counts sum to the page headline's totals —
    convergence by construction (every scroll on the page lands in one source)."""
    import re

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "arxiv:1", "arxiv", "A Paper", category="ml", raw_text="b", content_hash="h1"))
    insert_item(db, make_rendered(
        "web:a", "web", "Alpha", category="ml", raw_text="b", content_hash="h2"))
    insert_item(db, make_rendered("web:b", "web", "Beta", category="ml"))
    _drift(db, "arxiv:1", "drifted")
    capsys.readouterr()
    run_kb(capsys)

    body = generated_body(
        (scrolls_home / "library" / "categories" / "ml.md").read_text(encoding="utf-8"))
    fid_total: dict[str, int] = {}
    for bullet in re.findall(r"^- `\w+` — .*$", body, re.MULTILINE):
        for tier, count in re.findall(r"(full|partial|reference) (\d+)", bullet):
            fid_total[tier] = fid_total.get(tier, 0) + int(count)
    assert fid_total == {"full": 2, "reference": 1}
    assert "_Custody: 3 scroll(s) · fidelity full 2, reference 1" in body


def test_kb_source_page_omits_the_per_source_breakdown(scrolls_home, capsys):
    """A `sources/*.md` page is always single-source, so the per-source split is the
    helper's `<2`-source no-op — it carries the headline but never a `_By source:_`."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "web:a", "web", "Alpha", category="news", raw_text="b", content_hash="h1"))
    insert_item(db, make_rendered("web:b", "web", "Beta", category="news"))
    capsys.readouterr()
    run_kb(capsys)

    page = (scrolls_home / "library" / "sources" / "web.md").read_text(encoding="utf-8")
    assert "_Custody:" in page
    assert "_By source:_" not in page


def test_kb_single_source_category_page_omits_the_per_source_breakdown(scrolls_home, capsys):
    """A category page whose members all share one source omits the split — the
    multi-source gate is uniform (≥2 sources ⟹ a split), not special-cased to
    `sources/`, so a single-source category likewise carries only the headline."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered("web:a", "web", "Alpha", category="news"))
    insert_item(db, make_rendered("web:b", "web", "Beta", category="news"))
    capsys.readouterr()
    run_kb(capsys)

    page = (scrolls_home / "library" / "categories" / "news.md").read_text(encoding="utf-8")
    assert "_Custody:" in page
    assert "_By source:_" not in page


def test_kb_group_page_per_source_breakdown_is_refresh_safe(scrolls_home, capsys):
    """A re-verify refreshes a group page's per-source breakdown on recompile, inside
    the `@generated` fence; an annotation outside the fence survives."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "web:a", "web", "Alpha", category="ml", raw_text="b", content_hash="h1"))
    insert_item(db, make_rendered("arxiv:1", "arxiv", "A Paper", category="ml"))
    capsys.readouterr()
    run_kb(capsys)

    page_path = scrolls_home / "library" / "categories" / "ml.md"
    page = page_path.read_text(encoding="utf-8")
    assert "- `web` — 1 scroll(s) · fidelity full 1 · drift unverified 1" in page
    assert "_By source:_" in generated_body(page)  # inside the fence
    page_path.write_text(page + "\n\n_My note._\n", encoding="utf-8")

    _drift(db, "web:a", "drifted")
    run_kb(capsys)
    refreshed = page_path.read_text(encoding="utf-8")
    # the web posture moved unverified → drifted; its bullet refreshed in-fence
    # (arxiv is reference-only and never re-checked, so it stays unverified)
    assert "- `web` — 1 scroll(s) · fidelity full 1 · drift drifted 1" in refreshed
    assert "- `web` — 1 scroll(s) · fidelity full 1 · drift unverified 1" not in refreshed
    assert "_My note._" in refreshed  # annotation outside the fence preserved


# --- readable `_Attention:_` + `_Refresh:_` action-pointer lines on compiled
# --- `library/` pages (roadmap H184) --------------------------------------------
#
# The compiled-page counterpart of the bundle/context briefing action lines: the
# drift `_Attention:_` (H159) and refresh `_Refresh:_` (H178) pointers now ride the
# index + group pages beside the `_By source:_` map (H145/H152), through the same
# shared renderers so they read byte-identical and converge with the JSON
# `status`/`maintain` flags + `doctor`'s debt maps. The refresh debt is computed
# over each page's own member scope (the scope-consistent posture H178 took).


def _seed_action_debt(db):
    """A multi-source library that triggers all three action lines (H184).

    `web:a` — full + drifted (the `_Attention:_` weakest source) + a stale-ruleset
    classification (enrichment `_Refresh:_` debt {web}); `arxiv:1` — full. Both sit
    in concept `Models` whose stored summary is stale → summary `_Refresh:_` debt
    {arxiv, web} (the H171 multi-source attribution). Both in category `ml`.
    """
    from scrolls.classify import ENGINE
    from scrolls.kb import save_concept_summary

    stale_prov = {"classified_by": ENGINE, "classified_basis": "documentation-url",
                  "classified_ruleset": "oldfingerprint"}
    insert_item(db, make_rendered(
        "web:a", "web", "Alpha", category="ml", concepts=("Models",),
        raw_text="b", content_hash="h1", provenance=stale_prov))
    insert_item(db, make_rendered(
        "arxiv:1", "arxiv", "A Paper", category="ml", concepts=("Models",),
        raw_text="b", content_hash="h2"))
    _drift(db, "web:a", "drifted")
    save_concept_summary(db, make_summary("models", "Models", "Old synthesis."))


def _action_block(items, db):
    """The expected `_custody_scope_block` over `items` — the byte-identical oracle."""
    from scrolls.classify import stale_classification_counts_by_source
    from scrolls.custody import (
        custody_counts_by_source,
        latest_events,
        render_custody_attention,
        render_custody_by_source,
        render_custody_refresh,
    )
    from scrolls.kb import load_concept_summaries
    from scrolls.kb_llm import stale_summary_counts_by_source

    by_source = custody_counts_by_source(items, latest_events(db))
    return (
        render_custody_attention(by_source)
        + render_custody_refresh(
            stale_classification_counts_by_source(items),
            stale_summary_counts_by_source(items, load_concept_summaries(db)))
        + render_custody_by_source(by_source)
    )


def test_kb_index_carries_attention_and_refresh_action_lines(scrolls_home, capsys):
    """The whole-library index carries `_Attention:_`, `_Refresh:_`, then
    `_By source:_` under the headline — byte-identical to the shared renderers, in
    order, naming the same sources doctor's debt maps do (roadmap H184)."""
    from scrolls.items import list_items

    main(["init"])
    db = get_paths().db_path
    _seed_action_debt(db)
    capsys.readouterr()
    run_kb(capsys)

    rendered = [i for i in list_items(db) if i.markdown_path]
    expected = _action_block(rendered, db)
    header = (scrolls_home / "library" / "index.md").read_text(
        encoding="utf-8").split("## Sources")[0]
    # the whole block (minus its trailing spacer, which `## Sources` supplies) is
    # contiguous under the headline
    assert "\n".join(expected[:-1]) in header
    assert (header.index("_Custody:") < header.index("_Attention:")
            < header.index("_Refresh:") < header.index("_By source:_"))
    # the readable lines name the same sources the audit maps do
    assert "_Attention: source `web` carries the most drift" in header
    assert "classifications stale in `web`" in header
    assert "summaries stale in `arxiv`, `web`" in header


def test_kb_group_page_carries_attention_and_refresh_action_lines(scrolls_home, capsys):
    """A multi-source group page carries the same action block over its own members,
    between the scope headline and the first item bullet (roadmap H184)."""
    from scrolls.items import list_items

    main(["init"])
    db = get_paths().db_path
    _seed_action_debt(db)
    capsys.readouterr()
    run_kb(capsys)

    members = [i for i in list_items(db) if i.category == "ml"]
    expected = _action_block(members, db)
    body = generated_body(
        (scrolls_home / "library" / "categories" / "ml.md").read_text(encoding="utf-8"))
    assert "\n".join(expected[:-1]) in body
    assert (body.index("_Custody:") < body.index("_Attention:")
            < body.index("_Refresh:") < body.index("_By source:_"))


def test_kb_clean_multi_source_pages_omit_the_action_lines(scrolls_home, capsys):
    """A multi-source library with no actionable drift and no stale debt keeps the
    `_By source:_` split but shows neither action line — honest absence (H184)."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "web:a", "web", "Alpha", category="ml", raw_text="b", content_hash="h1"))
    insert_item(db, make_rendered(
        "arxiv:1", "arxiv", "A Paper", category="ml", raw_text="b", content_hash="h2"))
    capsys.readouterr()
    run_kb(capsys)

    for page in ("index.md", "categories/ml.md"):
        text = (scrolls_home / "library" / page).read_text(encoding="utf-8")
        assert "_By source:_" in text, page
        assert "_Attention:" not in text, page  # no source carries actionable loss
        assert "_Refresh:" not in text, page  # nothing stale to refresh


def test_kb_single_source_page_shows_refresh_but_not_attention(scrolls_home, capsys):
    """A single-source page shows `_Refresh:_` (per-source work, no single-source
    gate) but never `_Attention:_`/`_By source:_` (both rank across sources) — and
    its summary debt is scope-consistent: the multi-source concept drops below
    `MIN_MEMBERS` over one source, so only the classification axis remains (H184)."""
    main(["init"])
    db = get_paths().db_path
    _seed_action_debt(db)  # web:a (stale class + drifted), arxiv:1; concept Models
    capsys.readouterr()
    run_kb(capsys)

    page = (scrolls_home / "library" / "sources" / "web.md").read_text(encoding="utf-8")
    assert "_Custody:" in page
    assert "_Attention:" not in page  # single source: nothing to rank across
    assert "_By source:_" not in page  # single source: the headline says all
    # the enrichment axis still fires (web:a is stale-classified)...
    assert "_Refresh: classifications stale in `web`" in page
    # ...but the summary axis does not: concept `Models` has one web member on this
    # page (< MIN_MEMBERS), so it is not eligible here — scope-consistent debt
    assert "summaries stale" not in page


def test_kb_action_lines_are_refresh_safe(scrolls_home, capsys):
    """The action lines live inside the `@generated` fence and refresh on recompile;
    an annotation outside the fence survives (roadmap H184 × ADR 0102)."""
    main(["init"])
    db = get_paths().db_path
    _seed_action_debt(db)
    capsys.readouterr()
    run_kb(capsys)

    index_path = scrolls_home / "library" / "index.md"
    page = index_path.read_text(encoding="utf-8")
    assert "_Attention: source `web`" in generated_body(page)  # inside the fence
    assert "_Refresh: classifications stale in `web`" in generated_body(page)
    index_path.write_text(page + "\n\n_My note._\n", encoding="utf-8")

    # clear the stale classification: web:a re-classified under the live ruleset
    import dataclasses

    from scrolls.classify import ENGINE, RULESET_FINGERPRINT
    from scrolls.items import get_item, update_item
    web_a = get_item(db, "web:a")
    update_item(db, dataclasses.replace(web_a, provenance={
        "classified_by": ENGINE, "classified_basis": "documentation-url",
        "classified_ruleset": RULESET_FINGERPRINT}))
    run_kb(capsys)

    refreshed = index_path.read_text(encoding="utf-8")
    # the enrichment clause is gone; the summary clause remains (still stale)
    assert "classifications stale in `web`" not in refreshed
    assert "summaries stale in `arxiv`, `web`" in refreshed
    assert "_My note._" in refreshed  # annotation outside the fence preserved


# --- work-level at-risk `_At-risk work:_` line on the compiled `index.md` (H269) ---
# The consolidation alarm on the static compiled surface — the at-risk counterpart of
# the whole-library `_Custody:_` headline (H96). Folded by the shared
# `render_at_risk_works` over the rendered library, so the line names the same work
# `doctor`'s `custody.works` does; only the whole-library `index.md` carries it (the
# alarm is non-source-attributable — a scoped group page would fragment works).


def _seed_at_risk_work_rendered(db):
    """One at-risk multi-rep work (Z) + one safely-held multi-rep work (Y), rendered.

    Work Z (10.3000/z): two reference-only reps (no full form anywhere) → no
    representation is both full and unmoved → at risk, the lowest custody ceiling.
    Work Y (10.2000/y): a full + never-checked preprint (unverified ∈ the safe set,
    so safely held) + a reference record. Every rep is rendered (`make_rendered`
    gives a `markdown_path`), so all four appear in the compiled library. 2 works,
    1 at risk → Z is named.
    """
    insert_item(db, make_rendered(
        "arxiv:zref", "arxiv", "Zeta preprint",
        links=("https://doi.org/10.3000/z",)))
    insert_item(db, make_rendered(
        "crossref:zrec", "crossref", "Zeta record",
        links=("https://doi.org/10.3000/z",)))
    insert_item(db, make_rendered(
        "arxiv:yfull", "arxiv", "Ypsilon preprint",
        links=("https://doi.org/10.2000/y",),
        raw_text="<raw>A full body.</raw>", content_hash="deadbeef"))
    insert_item(db, make_rendered(
        "crossref:yrec", "crossref", "Ypsilon record",
        links=("https://doi.org/10.2000/y",)))


def test_kb_index_carries_an_at_risk_work_line(scrolls_home, capsys):
    """The landing `index.md` carries the consolidation `_At-risk work:_` alarm —
    naming the single work no representation safely holds (roadmap H269)."""
    main(["init"])
    db = get_paths().db_path
    _seed_at_risk_work_rendered(db)
    capsys.readouterr()
    run_kb(capsys)

    header = (scrolls_home / "library" / "index.md").read_text(
        encoding="utf-8").split("## Sources")[0]
    assert (
        "_At-risk work: `10.3000/z` — no representation is both full and unmoved "
        "(best held reference, safest drift unverified); 1 work(s) at risk._"
        in header
    )
    # beneath the whole-library headline, above the per-source map (no source drift
    # here, so no `_Attention:_` line precedes it)
    assert (header.index("_Custody:") < header.index("_At-risk work:")
            < header.index("_By source:_"))


def test_kb_index_at_risk_line_converges_with_render_at_risk_works(scrolls_home, capsys):
    """The rendered line is byte-identical to the shared `render_at_risk_works` over
    the rendered library, so it names the same work `at_risk_signal` does (H269)."""
    from scrolls.custody import latest_events
    from scrolls.items import list_items
    from scrolls.works import at_risk_signal, render_at_risk_works, works_over

    main(["init"])
    db = get_paths().db_path
    _seed_at_risk_work_rendered(db)
    capsys.readouterr()
    run_kb(capsys)

    rendered = [i for i in list_items(db) if i.markdown_path]
    verdicts = latest_events(db)
    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    for line in render_at_risk_works(rendered, verdicts):
        assert line in index
    most = at_risk_signal(works_over(rendered), verdicts)["most_at_risk"]
    assert most["doi"] == "10.3000/z"
    assert f"`{most['doi']}`" in index


def test_kb_index_groups_at_risk_line_with_the_loss_pointers(scrolls_home, capsys):
    """The at-risk line groups with the custody-loss pointers: beneath the headline,
    after the per-source `_Attention:_` line, before `_Refresh:_`/`_By source:_` —
    the `export bundle`/`context` briefing order (roadmap H269)."""
    main(["init"])
    db = get_paths().db_path
    _seed_action_debt(db)            # web:a full+drifted+stale, arxiv:1, Models stale
    _seed_at_risk_work_rendered(db)  # at-risk work Z + safely-held Y
    capsys.readouterr()
    run_kb(capsys)

    header = (scrolls_home / "library" / "index.md").read_text(
        encoding="utf-8").split("## Sources")[0]
    assert (header.index("_Custody:") < header.index("_Attention:")
            < header.index("_At-risk work:") < header.index("_Refresh:")
            < header.index("_By source:_"))


def test_kb_index_omits_at_risk_line_when_no_work_at_risk(scrolls_home, capsys):
    """A library whose every multi-rep work is safely held shows no at-risk line —
    honest absence, the same no-op the briefings take (roadmap H269)."""
    main(["init"])
    db = get_paths().db_path
    # one safely-held multi-rep work (full + reference) → nothing at risk
    insert_item(db, make_rendered(
        "arxiv:yfull", "arxiv", "Ypsilon preprint",
        links=("https://doi.org/10.2000/y",),
        raw_text="<raw>A full body.</raw>", content_hash="deadbeef"))
    insert_item(db, make_rendered(
        "crossref:yrec", "crossref", "Ypsilon record",
        links=("https://doi.org/10.2000/y",)))
    capsys.readouterr()
    run_kb(capsys)

    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    assert "_Custody:" in index
    assert "_At-risk work:" not in index


def test_kb_group_pages_omit_the_at_risk_work_line(scrolls_home, capsys):
    """The consolidation alarm rides only the whole-library `index.md`; the scoped
    group pages omit it (a work spans sources — a scoped page fragments works and
    could not converge with the library-wide audit, roadmap H269)."""
    main(["init"])
    db = get_paths().db_path
    # give the at-risk reps a shared category so a category page exists over them
    insert_item(db, make_rendered(
        "arxiv:zref", "arxiv", "Zeta preprint", category="ml",
        links=("https://doi.org/10.3000/z",)))
    insert_item(db, make_rendered(
        "crossref:zrec", "crossref", "Zeta record", category="ml",
        links=("https://doi.org/10.3000/z",)))
    capsys.readouterr()
    run_kb(capsys)

    library = scrolls_home / "library"
    assert "_At-risk work:" in (library / "index.md").read_text(encoding="utf-8")
    for page in ("sources/arxiv.md", "sources/crossref.md", "categories/ml.md"):
        assert "_At-risk work:" not in (library / page).read_text(encoding="utf-8"), page


def test_kb_at_risk_work_line_is_refresh_safe(scrolls_home, capsys):
    """The at-risk line lives inside the `@generated` fence and refreshes on recompile;
    an annotation outside the fence survives, and a recapture clears the line
    (roadmap H269 × ADR 0102)."""
    import dataclasses

    from scrolls.items import get_item, update_item

    main(["init"])
    db = get_paths().db_path
    _seed_at_risk_work_rendered(db)
    capsys.readouterr()
    run_kb(capsys)

    index_path = scrolls_home / "library" / "index.md"
    page = index_path.read_text(encoding="utf-8")
    assert "_At-risk work: `10.3000/z`" in generated_body(page)  # inside the fence
    index_path.write_text(page + "\n\n_My note._\n", encoding="utf-8")

    # recapture Z: give one of its reps a full body → the work is now safely held
    zref = get_item(db, "arxiv:zref")
    update_item(db, dataclasses.replace(
        zref, raw_text="<raw>Recaptured.</raw>", content_hash="cafef00d"))
    run_kb(capsys)

    refreshed = index_path.read_text(encoding="utf-8")
    assert "_At-risk work:" not in refreshed       # the alarm cleared on recompile
    assert "_My note._" in refreshed               # annotation outside the fence kept


# --- whole-library archive-integrity `_Archive:_` line on `index.md` (H321) ---
# The recovery-store counterpart of the at-risk-works `index.md` line (H269) and the
# whole-library `_Custody:_` headline (H96): one `_Archive:_` line when any archived
# prior is corrupt — its advertised `prior_hash` no longer equals its snapshot's
# `content_hash`, a custody-honesty bug invisible until restore. Folds the *same*
# whole-library `archive_integrity_block(archived_records(db))` `doctor`'s
# `custody.archive` reads, rendered by the *same* `archive_integrity_headline` the
# `maintain`/bundle/context surfaces use (the shared `render_archive_integrity`), so
# the line converges with the JSON audit by construction. Whole-library — *not*
# in-scope: a compiled landing page is the library-wide view; only `index.md` carries
# it (the recovery store is a single non-source-attributable store, like the at-risk
# line — group pages omit it). Inside the page's `@generated` fence (ADR 0102).


def _seed_corrupt_archived_prior(db, item_id="wikipedia:en:SQLite",
                                 title="SQLite database", source="wikipedia"):
    """Hold a rendered item, archive a prior via an adoption, then tamper the archived
    row's `prior_hash` so it diverges from its snapshot's `content_hash` — the corrupt
    recovery store the whole-library integrity alarm must name on `index.md`. The held
    copy stays rendered (`dataclasses.replace` preserves `markdown_path`/`stage`), so
    it appears in the compiled library too. Returns the item id."""
    import dataclasses
    import sqlite3

    from scrolls.items import adopt_incoming

    held = make_rendered(item_id, source, title,
                         raw_text="<raw>Body.</raw>", content_hash="deadbeef")
    insert_item(db, held)
    incoming = dataclasses.replace(
        held, raw_text="<raw>A later capture.</raw>", content_hash="moved")
    adopt_incoming(db, incoming, archived_at="2026-06-22T00:00:00+00:00")
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("UPDATE item_archive SET prior_hash = ? WHERE item_id = ?",
                     ("sha256:tampered", item_id))
    conn.close()
    return item_id


def test_kb_index_carries_an_archive_integrity_line(scrolls_home, capsys):
    """The landing `index.md` carries the whole-library `_Archive:_` integrity alarm —
    one line naming how many archived priors fail integrity (roadmap H321)."""
    main(["init"])
    db = get_paths().db_path
    _seed_corrupt_archived_prior(db)
    capsys.readouterr()
    run_kb(capsys)

    header = (scrolls_home / "library" / "index.md").read_text(
        encoding="utf-8").split("## Sources")[0]
    assert "_Archive: 1 prior(s) fail integrity (prior_hash ≠ snapshot)._" in header
    # beneath the whole-library `_Custody:_` headline, with the custody-loss pointers
    assert header.index("_Custody:") < header.index("_Archive:")


def test_kb_index_archive_line_converges_with_doctor(scrolls_home, capsys):
    """The count is the *same* whole-library `archive_integrity_block` fold `doctor`'s
    `custody.archive` reads, so the readable line and the JSON audit agree (H321)."""
    from scrolls.doctor import run_doctor

    main(["init"])
    db = get_paths().db_path
    _seed_corrupt_archived_prior(db, "wikipedia:en:SQLite", "SQLite database")
    _seed_corrupt_archived_prior(db, "arxiv:postgres", "Postgres paper", source="arxiv")
    capsys.readouterr()
    run_kb(capsys)

    mismatched = run_doctor(get_paths())["custody"]["archive"]["mismatched"]
    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    assert mismatched == 2
    assert f"_Archive: {mismatched} prior(s) fail integrity" in index


def test_kb_index_archive_line_converges_with_shared_renderer(scrolls_home, capsys):
    """The rendered line is byte-identical to the shared `render_archive_integrity`
    over the whole library, so the compiled surface cannot desync from the bundle /
    context / maintain surfaces that fold through the same helper (H321)."""
    from scrolls.maintain import render_archive_integrity

    main(["init"])
    db = get_paths().db_path
    _seed_corrupt_archived_prior(db)
    capsys.readouterr()
    run_kb(capsys)

    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    for line in render_archive_integrity(db, None):  # None → whole-library
        if line:
            assert line in index


def test_kb_index_groups_archive_line_with_the_loss_pointers(scrolls_home, capsys):
    """The archive line groups with the custody-loss pointers: beneath the headline,
    after the work-level `_At-risk work:_` line, before the `_By source:_` map — the
    `export bundle`/`context` briefing order (Attention → At-risk → Archive, roadmap
    H321)."""
    main(["init"])
    db = get_paths().db_path
    _seed_at_risk_work_rendered(db)   # at-risk work Z + safely-held Y (arxiv, crossref)
    _seed_corrupt_archived_prior(db)  # one corrupt prior (wikipedia)
    capsys.readouterr()
    run_kb(capsys)

    header = (scrolls_home / "library" / "index.md").read_text(
        encoding="utf-8").split("## Sources")[0]
    assert (header.index("_Custody:") < header.index("_At-risk work:")
            < header.index("_Archive:") < header.index("_By source:_"))


def test_kb_index_omits_archive_line_when_store_is_clean(scrolls_home, capsys):
    """A well-formed archived prior (prior_hash == snapshot.content_hash) shows no
    `_Archive:` line — honest absence, the same no-op the briefings take (H321)."""
    import dataclasses

    from scrolls.items import adopt_incoming

    main(["init"])
    db = get_paths().db_path
    held = make_rendered("wikipedia:en:SQLite", "wikipedia", "SQLite database",
                         raw_text="<raw>Body.</raw>", content_hash="deadbeef")
    insert_item(db, held)
    adopt_incoming(db, dataclasses.replace(held, raw_text="<raw>later</raw>",
                                           content_hash="moved"),
                   archived_at="2026-06-22T00:00:00+00:00")
    capsys.readouterr()
    run_kb(capsys)

    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    assert "_Custody:" in index           # the headline still renders
    assert "_Archive:" not in index       # a clean store is silent


def test_kb_group_pages_omit_the_archive_line(scrolls_home, capsys):
    """The recovery-store alarm rides only the whole-library `index.md`; the scoped
    group pages omit it (the store is a single non-source-attributable store, like the
    at-risk line — a group page is not the library-wide view, roadmap H321)."""
    main(["init"])
    db = get_paths().db_path
    _seed_corrupt_archived_prior(db, "wikipedia:en:SQLite", "SQLite database")
    insert_item(db, make_rendered("arxiv:1", "arxiv", "A paper", category="ml"))
    capsys.readouterr()
    run_kb(capsys)

    library = scrolls_home / "library"
    assert "_Archive:" in (library / "index.md").read_text(encoding="utf-8")
    for page in ("sources/wikipedia.md", "sources/arxiv.md", "categories/ml.md"):
        assert "_Archive:" not in (library / page).read_text(encoding="utf-8"), page


def test_kb_archive_line_is_refresh_safe(scrolls_home, capsys):
    """The archive line lives inside the `@generated` fence and refreshes on recompile;
    an annotation outside the fence survives, and repairing the corrupt prior clears
    the line (roadmap H321 × ADR 0102)."""
    import sqlite3

    main(["init"])
    db = get_paths().db_path
    _seed_corrupt_archived_prior(db, "wikipedia:en:SQLite", "SQLite database")
    capsys.readouterr()
    run_kb(capsys)

    index_path = scrolls_home / "library" / "index.md"
    page = index_path.read_text(encoding="utf-8")
    assert "_Archive: 1 prior(s)" in generated_body(page)  # inside the fence
    index_path.write_text(page + "\n\n_My note._\n", encoding="utf-8")

    # repair the corrupt prior — its advertised hash matches the snapshot again
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("UPDATE item_archive SET prior_hash = ? WHERE item_id = ?",
                     ("deadbeef", "wikipedia:en:SQLite"))
    conn.close()
    run_kb(capsys)

    refreshed = index_path.read_text(encoding="utf-8")
    assert "_Archive:" not in refreshed   # the alarm cleared on recompile
    assert "_My note._" in refreshed       # annotation outside the fence kept


def test_kb_recompile_removes_stale_pages_but_keeps_user_files(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    item = make_rendered("web:abc", "web", "A handy utility", category="tool")
    insert_item(db, item)
    capsys.readouterr()
    run_kb(capsys)
    assert (scrolls_home / "library" / "categories" / "tool.md").exists()

    notes = scrolls_home / "library" / "notes.md"
    notes.write_text("user notes must survive recompiles\n")
    import dataclasses
    update_item(db, dataclasses.replace(item, category="reference"))

    run_kb(capsys)
    assert not (scrolls_home / "library" / "categories" / "tool.md").exists()
    assert (scrolls_home / "library" / "categories" / "reference.md").exists()
    assert notes.read_text() == "user notes must survive recompiles\n"


# --- refresh-safe regeneration: the sentinel fence (ADR 0102) -------------


def test_kb_generated_pages_carry_the_sentinel_fence(scrolls_home, capsys):
    from scrolls.generated import GENERATED_END

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "wikipedia:en:SQLite", "wikipedia", "SQLite",
        category="reference", concepts=("Database",), tags=("db",)))
    capsys.readouterr()
    run_kb(capsys)

    library = scrolls_home / "library"
    for relpath in ("index.md", "graph.md", "works.md", "sources/wikipedia.md",
                    "categories/reference.md", "concepts/database.md", "tags/db.md"):
        text = (library / relpath).read_text(encoding="utf-8")
        assert "<!-- @generated scrolls" in text, relpath
        assert text.rstrip().endswith(GENERATED_END), relpath


def test_kb_recompile_preserves_a_user_annotation_outside_the_fence(scrolls_home, capsys):
    """The headline M1 contract: a @user note survives while generated refreshes."""
    main(["init"])
    db = get_paths().db_path
    item = make_rendered("web:abc", "web", "First Post")
    insert_item(db, item)
    capsys.readouterr()
    run_kb(capsys)

    # a human annotates the generated index, both above and below the fence
    index = scrolls_home / "library" / "index.md"
    body = index.read_text(encoding="utf-8")
    index.write_text(
        "<!-- @user -->\nRead the FTS page first.\n\n" + body + "\nMy closing note.\n",
        encoding="utf-8",
    )

    # new data arrives and the library is recompiled
    insert_item(db, make_rendered("web:def", "web", "Second Post"))
    run_kb(capsys)

    refreshed = index.read_text(encoding="utf-8")
    # the annotations outside the fence survived verbatim
    assert refreshed.startswith("<!-- @user -->\nRead the FTS page first.\n\n")
    assert refreshed.rstrip().endswith("My closing note.")
    # the generated region refreshed: the new item is in, the old count is gone
    assert "Second Post" in generated_body(refreshed)
    assert "1 scroll from 1 source." not in refreshed
    assert "2 scrolls from 1 source." in generated_body(refreshed)


def test_kb_marker_less_page_is_overwritten_wholesale(scrolls_home, capsys):
    """A hand-written generated page with no fence is replaced (migration path)."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered("web:abc", "web", "A Post"))
    capsys.readouterr()

    # pre-sentinel / hand-written index with no fence to anchor on
    index = scrolls_home / "library" / "index.md"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("# Hand-written\n\nnothing generated here.\n", encoding="utf-8")

    run_kb(capsys)
    refreshed = index.read_text(encoding="utf-8")
    assert "Hand-written" not in refreshed  # wholesale overwrite, as before
    assert "<!-- @generated scrolls" in refreshed  # now fenced for next time


def test_kb_stale_annotated_page_is_kept_with_a_tombstone(scrolls_home, capsys):
    """A vanished group's page is kept (not deleted) when it carries a note."""
    import dataclasses

    main(["init"])
    db = get_paths().db_path
    item = make_rendered("web:abc", "web", "A handy utility", category="tool")
    insert_item(db, item)
    capsys.readouterr()
    run_kb(capsys)

    page = scrolls_home / "library" / "categories" / "tool.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nMy note on tools.\n",
                    encoding="utf-8")

    # the only `tool` item is reclassified, so the tool category page goes stale
    update_item(db, dataclasses.replace(item, category="reference"))
    run_kb(capsys)

    assert page.exists()  # kept, because it carries an annotation
    text = page.read_text(encoding="utf-8")
    assert "My note on tools." in text  # the annotation survived
    assert "A handy utility" not in generated_body(text)  # stale rollup gone
    assert "no longer part of the compiled library" in generated_body(text)


def test_kb_recompile_preserves_an_annotation_on_a_group_page(scrolls_home, capsys):
    """Preservation is not index-only: a source page keeps its note too."""
    main(["init"])
    db = get_paths().db_path
    item = make_rendered("web:abc", "web", "First", category="tool")
    insert_item(db, item)
    capsys.readouterr()
    run_kb(capsys)

    page = scrolls_home / "library" / "sources" / "web.md"
    page.write_text(page.read_text(encoding="utf-8") + "\n<!-- @user --> see also notes.md\n",
                    encoding="utf-8")

    # the page's membership grows; the source page stays generated and refreshes
    insert_item(db, make_rendered("web:def", "web", "Second", category="tool"))
    run_kb(capsys)
    text = page.read_text(encoding="utf-8")
    assert text.rstrip().endswith("<!-- @user --> see also notes.md")
    assert "Second" in generated_body(text)  # generated region refreshed
    assert "2 scrolls." in generated_body(text)


def test_kb_double_recompile_is_byte_stable_and_keeps_annotation(scrolls_home, capsys):
    """Recompiling twice with no data change is idempotent and note-preserving."""
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered("web:abc", "web", "Only Post"))
    capsys.readouterr()
    run_kb(capsys)

    index = scrolls_home / "library" / "index.md"
    index.write_text("<!-- @user --> top note\n\n" + index.read_text(encoding="utf-8"),
                     encoding="utf-8")
    run_kb(capsys)
    once = index.read_text(encoding="utf-8")
    run_kb(capsys)
    twice = index.read_text(encoding="utf-8")
    assert once == twice  # stable across redundant recompiles
    assert once.startswith("<!-- @user --> top note\n")


def test_kb_empty_initialized_library_writes_empty_index(scrolls_home, capsys):
    main(["init"])
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload == {"items": 0, "sources": 0, "categories": 0, "concepts": 0, "tags": 0, "summaries": 0, "clusters": 0, "works": 0, "pages": 3}
    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    assert "0 scrolls from 0 sources." in index
    assert "## Sources" not in index
    assert "## Recent" not in index


# --- the link-graph page library/graph.md (ADR 0062) ---------------------


def test_kb_graph_page_clusters_linked_scrolls(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "web:a", "web", "Article A", links=("https://example.org/web:b",)))
    insert_item(db, make_rendered("web:b", "web", "Article B"))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload["clusters"] == 1
    assert payload["pages"] == 4  # index + graph + works + 1 source page (web)

    graph = (scrolls_home / "library" / "graph.md").read_text(encoding="utf-8")
    assert "# Scrolls Link Graph" in graph
    assert "2 scrolls connected across 1 cluster." in graph
    assert "## Cluster 1" in graph
    # members link to scrolls relative to library/, with the directed edge nested
    assert "- [Article A](../scrolls/web/article-a.md) — web" in graph
    assert "  - → [Article B](../scrolls/web/article-b.md)" in graph
    assert "- [Article B](../scrolls/web/article-b.md) — web" in graph

    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    assert "[Link graph](graph.md) — 2 scrolls connected across 1 cluster." in index


def test_kb_graph_page_is_empty_when_no_scrolls_link(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered("web:a", "web", "Article A"))
    insert_item(db, make_rendered("web:b", "web", "Article B"))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload["clusters"] == 0

    graph = generated_body(
        (scrolls_home / "library" / "graph.md").read_text(encoding="utf-8"))
    assert graph == "# Scrolls Link Graph\n\nNo linked scrolls yet.\n"
    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    assert "[Link graph](graph.md) — no linked scrolls yet." in index


def test_kb_graph_page_orders_clusters_largest_first(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    # a two-item cluster and a three-item chain
    insert_item(db, make_rendered(
        "web:p", "web", "Pair One", links=("https://example.org/web:q",)))
    insert_item(db, make_rendered("web:q", "web", "Pair Two"))
    insert_item(db, make_rendered(
        "web:x", "web", "Chain One", links=("https://example.org/web:y",)))
    insert_item(db, make_rendered(
        "web:y", "web", "Chain Two", links=("https://example.org/web:z",)))
    insert_item(db, make_rendered("web:z", "web", "Chain Three"))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload["clusters"] == 2

    graph = (scrolls_home / "library" / "graph.md").read_text(encoding="utf-8")
    # the three-item chain (Chain One) sorts before the pair under Cluster 1
    assert graph.index("Chain One") < graph.index("Pair One")
    assert graph.index("## Cluster 1") < graph.index("## Cluster 2")


def test_kb_recompile_clears_a_stale_graph_cluster(scrolls_home, capsys):
    import dataclasses

    main(["init"])
    db = get_paths().db_path
    a = make_rendered("web:a", "web", "Article A", links=("https://example.org/web:b",))
    insert_item(db, a)
    insert_item(db, make_rendered("web:b", "web", "Article B"))
    capsys.readouterr()
    run_kb(capsys)
    assert "## Cluster 1" in (scrolls_home / "library" / "graph.md").read_text()

    update_item(db, dataclasses.replace(a, links=()))  # the link is gone
    run_kb(capsys)
    graph = generated_body(
        (scrolls_home / "library" / "graph.md").read_text(encoding="utf-8"))
    assert graph == "# Scrolls Link Graph\n\nNo linked scrolls yet.\n"


# --- the works page library/works.md (ADR 0070) --------------------------


def _crossref_rep(doi, title, *, category=None):
    """A rendered crossref representation whose source_id is the work's DOI."""
    return make_rendered(
        f"crossref:{doi}", "crossref", title,
        source_id=doi, url=f"https://doi.org/{doi}", category=category)


def test_kb_works_page_clusters_representations_by_shared_doi(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    # a preprint that names the published DOI as a link, and the crossref
    # record whose source_id *is* that DOI — one work, two representations
    doi = "10.5555/3295222"
    insert_item(db, make_rendered(
        "arxiv:1706.03762", "arxiv", "Attention Is All You Need",
        links=(f"https://doi.org/{doi}",)))
    insert_item(db, _crossref_rep(doi, "Attention Is All You Need"))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload["works"] == 1
    # index + works + graph + 2 source pages + 1 category page (crossref → paper?)
    # arxiv has no category here, crossref none either, so 0 category pages
    assert payload["pages"] == 5  # index + works + graph + arxiv + crossref

    works = (scrolls_home / "library" / "works.md").read_text(encoding="utf-8")
    assert "# Scrolls Works" in works
    assert "1 work held as 2 representations." in works
    assert f"## {doi}" in works
    assert f"[doi.org/{doi}](https://doi.org/{doi}) — 2 representations." in works
    # both representations link to their scroll relative to library/
    assert "- [Attention Is All You Need](../scrolls/arxiv/attention-is-all-you-need.md) — arxiv" in works
    assert "- [Attention Is All You Need](../scrolls/crossref/attention-is-all-you-need.md) — crossref" in works

    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    assert "[Works](works.md) — 1 work held as 2 representations." in index


def test_kb_works_page_marks_the_canonical_representation(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    # crossref (the registered published record) outranks the arXiv preprint,
    # so the crossref representation is the work's canonical one (ADR 0095).
    doi = "10.5555/3295222"
    insert_item(db, make_rendered(
        "arxiv:1706.03762", "arxiv", "Attention Is All You Need",
        links=(f"https://doi.org/{doi}",)))
    insert_item(db, _crossref_rep(doi, "Attention Is All You Need"))
    capsys.readouterr()
    run_kb(capsys)

    works = (scrolls_home / "library" / "works.md").read_text(encoding="utf-8")
    # the canonical (crossref) bullet is marked; the preprint bullet is not
    assert ("- [Attention Is All You Need](../scrolls/crossref/"
            "attention-is-all-you-need.md) — crossref · canonical") in works
    assert ("- [Attention Is All You Need](../scrolls/arxiv/"
            "attention-is-all-you-need.md) — arxiv\n") in works


def test_kb_works_page_is_empty_when_no_shared_doi(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered("web:a", "web", "Article A"))
    insert_item(db, _crossref_rep("10.1/solo", "A Lonely Paper"))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload["works"] == 0  # the crossref DOI has only one representation

    works = generated_body(
        (scrolls_home / "library" / "works.md").read_text(encoding="utf-8"))
    assert works == "# Scrolls Works\n\nNo works held in multiple representations yet.\n"
    index = (scrolls_home / "library" / "index.md").read_text(encoding="utf-8")
    assert "[Works](works.md) — no works held in multiple representations yet." in index


def test_kb_works_page_orders_works_by_representation_count(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    # a 3-representation work (DOI ...big) and a 2-representation work (...small)
    big = "10.5555/big"
    small = "10.5555/small"
    insert_item(db, _crossref_rep(big, "Big Work"))
    insert_item(db, make_rendered(
        "arxiv:9001", "arxiv", "Big Preprint", links=(f"https://doi.org/{big}",)))
    insert_item(db, make_rendered(
        "pubmed:9001", "pubmed", "Big Indexed", links=(f"https://doi.org/{big}",)))
    insert_item(db, _crossref_rep(small, "Small Work"))
    insert_item(db, make_rendered(
        "arxiv:9002", "arxiv", "Small Preprint", links=(f"https://doi.org/{small}",)))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload["works"] == 2

    works = (scrolls_home / "library" / "works.md").read_text(encoding="utf-8")
    assert "2 works held as 5 representations." in works
    # the 3-representation work sorts before the 2-representation work
    assert works.index(f"## {big}") < works.index(f"## {small}")
    assert f"[doi.org/{big}](https://doi.org/{big}) — 3 representations." in works
    assert f"[doi.org/{small}](https://doi.org/{small}) — 2 representations." in works


def test_kb_recompile_clears_a_stale_work(scrolls_home, capsys):
    import dataclasses

    main(["init"])
    db = get_paths().db_path
    doi = "10.5555/3295222"
    preprint = make_rendered(
        "arxiv:1706.03762", "arxiv", "Attention Is All You Need",
        links=(f"https://doi.org/{doi}",))
    insert_item(db, preprint)
    insert_item(db, _crossref_rep(doi, "Attention Is All You Need"))
    capsys.readouterr()
    run_kb(capsys)
    assert f"## {doi}" in (scrolls_home / "library" / "works.md").read_text()

    update_item(db, dataclasses.replace(preprint, links=()))  # the DOI edge is gone
    run_kb(capsys)
    works = generated_body(
        (scrolls_home / "library" / "works.md").read_text(encoding="utf-8"))
    assert works == "# Scrolls Works\n\nNo works held in multiple representations yet.\n"


# --- per-work custody marker on the compiled works.md rollup (H270) ----------
# The works-page analogue of the per-item `· <fidelity> · <drift>` marker on the
# compiled list pages (`_custody_marker`, H89): one `_Custody:` line per `## <doi>`
# section, folded by the shared `render_work_custody_marker` over the same
# `work_custody` dict (H261) `scrolls works`'s per-work `custody` block carries, so a
# human browsing the rollup reads "safely held" vs. "at risk" without opening the JSON.


def test_kb_works_page_carries_a_per_work_custody_marker(scrolls_home, capsys):
    """Each `## <doi>` section carries a work-level `_Custody:` marker beneath its
    resolver line — the consolidation verdict (safely held vs. at risk) a human reads
    without opening `scrolls works` JSON (roadmap H270)."""
    main(["init"])
    db = get_paths().db_path
    _seed_at_risk_work_rendered(db)  # at-risk work Z + safely-held work Y
    capsys.readouterr()
    run_kb(capsys)

    works = (scrolls_home / "library" / "works.md").read_text(encoding="utf-8")
    # Z: two reference reps, never checked → no full+unmoved form anywhere → at risk
    assert "_Custody: best held reference, safest drift unverified — at risk._" in works
    # Y: a full + never-checked preprint → an unmoved full copy exists → safely held
    assert "_Custody: best held full, safest drift unverified — safely held._" in works
    # the marker sits beneath the resolver line, above the representation bullets
    z = works.split("## 10.3000/z", 1)[1].split("\n## ", 1)[0]
    assert (z.index("— 2 representations.")
            < z.index("_Custody: best held reference")
            < z.index("- ["))


def test_kb_works_page_custody_marker_is_refresh_safe(scrolls_home, capsys):
    """The per-work marker lives inside the `@generated` fence and refreshes on
    recompile: recapturing a representation flips its work's marker from `at risk` to
    `safely held`, while an annotation outside the fence survives (H270 × ADR 0102)."""
    import dataclasses

    from scrolls.items import get_item, update_item

    main(["init"])
    db = get_paths().db_path
    _seed_at_risk_work_rendered(db)
    capsys.readouterr()
    run_kb(capsys)

    works_path = scrolls_home / "library" / "works.md"
    page = works_path.read_text(encoding="utf-8")
    # Z's marker is at-risk and inside the fence
    assert ("best held reference, safest drift unverified — at risk._"
            in generated_body(page))
    works_path.write_text(page + "\n\n_My note._\n", encoding="utf-8")

    # recapture one of Z's reps with a full body → the work is now safely held
    zref = get_item(db, "arxiv:zref")
    update_item(db, dataclasses.replace(
        zref, raw_text="<raw>Recaptured.</raw>", content_hash="cafef00d"))
    run_kb(capsys)

    refreshed = works_path.read_text(encoding="utf-8")
    z = refreshed.split("## 10.3000/z", 1)[1].split("\n## ", 1)[0]
    assert "best held full, safest drift unverified — safely held._" in z  # flipped
    assert "— at risk._" not in refreshed              # both works now safely held
    assert "_My note._" in refreshed                   # annotation outside fence kept


def _category_bullets(scrolls_home, slug):
    """The top-level (column-0) item/work bullets of a compiled category page.

    Excludes the per-source custody breakdown bullets (roadmap H152), which are
    backtick-wrapped source names (`` - `web` — N scroll(s) ``); item/work bullets
    are markdown links (`- [Title](…)`) or bold work headings (`- **Title**`).
    """
    page = (scrolls_home / "library" / "categories" / f"{slug}.md").read_text(
        encoding="utf-8"
    )
    return [
        line for line in page.splitlines()
        if line.startswith("- ") and not line.startswith("- `")
    ]


def test_kb_category_page_consolidates_work_representations(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    doi = "10.5555/3295222"
    # two paper representations of one work, both classified `paper`: a preprint
    # naming the published DOI and the crossref record whose source_id is it
    insert_item(db, make_rendered(
        "arxiv:1706.03762", "arxiv", "Attention Is All You Need",
        category="paper", links=(f"https://doi.org/{doi}",)))
    insert_item(db, _crossref_rep(doi, "Attention Is All You Need", category="paper"))
    # a standalone paper that is part of no multi-representation work
    insert_item(db, make_rendered(
        "arxiv:2000.00001", "arxiv", "Another Paper", category="paper"))
    capsys.readouterr()

    run_kb(capsys)
    page = (scrolls_home / "library" / "categories" / "paper.md").read_text(encoding="utf-8")
    # the work renders as one consolidated entry: a bold heading with its DOI
    # resolver link, then each representation nested beneath
    assert (
        f"- **Attention Is All You Need** — 2 representations "
        f"([doi.org/{doi}](https://doi.org/{doi}))"
    ) in page
    assert (
        "  - [Attention Is All You Need](../../scrolls/arxiv/attention-is-all-you-need.md) — arxiv"
    ) in page
    assert (
        "  - [Attention Is All You Need](../../scrolls/crossref/attention-is-all-you-need.md) — crossref"
    ) in page
    # the duplicated work never appears as two separate top-level bullets
    assert "\n- [Attention Is All You Need](" not in page
    # the standalone paper stays an ordinary top-level bullet
    assert "- [Another Paper](../../scrolls/arxiv/another-paper.md) — arxiv" in page
    # the count line still counts scrolls, not entries — every representation
    # is still a scroll on the page
    assert "3 scrolls." in page


def test_kb_category_page_uses_canonical_title_and_interleaves(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    doi = "10.5555/zeta"
    # crossref (published) outranks arxiv (preprint), so its title heads the work
    insert_item(db, make_rendered(
        "arxiv:5", "arxiv", "Zeta Preprint Title", category="paper",
        links=(f"https://doi.org/{doi}",)))
    insert_item(db, _crossref_rep(doi, "Zeta Published Title", category="paper"))
    # a singleton that sorts before the work's canonical title
    insert_item(db, make_rendered("web:apex", "web", "Apex Paper", category="paper"))
    capsys.readouterr()

    run_kb(capsys)
    bullets = _category_bullets(scrolls_home, "paper")
    # the singleton 'Apex Paper' sorts before the work header 'Zeta Published Title'
    assert bullets[0] == (
        "- [Apex Paper](../../scrolls/web/apex-paper.md) — web"
        " · reference · unverified · never checked")
    # the canonical (crossref) title heads the consolidated work, not the preprint's
    assert bullets[1].startswith("- **Zeta Published Title** — 2 representations")
    assert "Zeta Preprint Title" not in bullets[1]


def test_kb_category_page_leaves_single_representation_uncollapsed(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    doi = "10.5555/solo"
    # only one representation of the work is on this page (the published DOI is
    # not in the library), so there is nothing to consolidate — a flat bullet
    insert_item(db, make_rendered(
        "arxiv:7", "arxiv", "Solo Preprint", category="paper",
        links=(f"https://doi.org/{doi}",)))
    capsys.readouterr()

    run_kb(capsys)
    bullets = _category_bullets(scrolls_home, "paper")
    assert bullets == [
        "- [Solo Preprint](../../scrolls/arxiv/solo-preprint.md) — arxiv"
        " · reference · unverified · never checked"]


def test_kb_source_pages_do_not_consolidate(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    doi = "10.5555/same-source"
    # two same-source representations of one work would consolidate on a category
    # page, but source pages are single-source and list each scroll flatly
    insert_item(db, make_rendered(
        "arxiv:8", "arxiv", "Source Page Preprint", category="paper",
        links=(f"https://doi.org/{doi}",)))
    insert_item(db, make_rendered(
        "arxiv:9", "arxiv", "Source Page Other", category="paper", source_id=doi,
        url="https://example.org/arxiv:9"))
    capsys.readouterr()

    run_kb(capsys)
    source_page = (scrolls_home / "library" / "sources" / "arxiv.md").read_text(encoding="utf-8")
    assert "**" not in source_page  # no consolidated work heading
    assert "representations" not in source_page


def make_summary(slug, display, text, members_hash="abc123"):
    from scrolls.kb import ConceptSummary
    return ConceptSummary(
        slug=slug,
        display=display,
        summary=text,
        members_hash=members_hash,
        engine="kb-llm-v1",
        model="claude-test",
        generated_at="2026-06-12T00:00:00+00:00",
    )


def test_kb_concept_page_leads_with_stored_summary(scrolls_home, capsys):
    from scrolls.kb import save_concept_summary

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered(
        "wikipedia:en:Okapi_BM25", "wikipedia", "Okapi BM25", concepts=("BM25",)))
    insert_item(db, make_rendered(
        "web:fts", "web", "FTS in practice", concepts=("BM25", "SQLite")))
    save_concept_summary(db, make_summary(
        "bm25", "BM25", "BM25 appears across saved items about ranking and FTS."))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload["concepts"] == 2
    assert payload["summaries"] == 1  # only bm25 has a stored summary

    page = generated_body(
        (scrolls_home / "library" / "concepts" / "bm25.md").read_text(encoding="utf-8"))
    assert page.startswith(
        "# Concept: BM25\n"
        "\n"
        "BM25 appears across saved items about ranking and FTS.\n"
        "\n"
        "2 scrolls.\n"
    )
    # pages without a stored summary keep the plain shape
    sqlite_page = generated_body(
        (scrolls_home / "library" / "concepts" / "sqlite.md").read_text(encoding="utf-8"))
    assert sqlite_page.startswith("# Concept: SQLite\n\n1 scroll.\n")


def test_kb_concept_page_combines_lead_summary_and_related_concepts(scrolls_home, capsys):
    """A page with both a stored summary and co-occurrence: lead first, related last."""
    from scrolls.kb import save_concept_summary

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered("web:a", "web", "A", concepts=("BM25", "SQLite")))
    insert_item(db, make_rendered("web:b", "web", "B", concepts=("BM25", "SQLite")))
    save_concept_summary(db, make_summary("bm25", "BM25", "How BM25 shows up here."))
    capsys.readouterr()

    run_kb(capsys)
    page = generated_body(
        (scrolls_home / "library" / "concepts" / "bm25.md").read_text(encoding="utf-8"))
    assert page == (
        "# Concept: BM25\n"
        "\n"
        "How BM25 shows up here.\n"
        "\n"
        "2 scrolls.\n"
        "\n"
        "_Custody: 2 scroll(s) · fidelity reference 2 · drift unverified 2._\n"
        "\n"
        # the stored summary's members_hash (`abc123`) does not match the live
        # members, so the concept's single-source summary debt names `web` (H184);
        # single source ⟹ no `_Attention:_`/`_By source:_`, but `_Refresh:_` has no
        # single-source gate
        "_Refresh: summaries stale in `web` — refresh with "
        "`scrolls kb --stale --source <S>`._\n"
        "\n"
        "- [A](../../scrolls/web/a.md) — web · reference · unverified · never checked\n"
        "- [B](../../scrolls/web/b.md) — web · reference · unverified · never checked\n"
        "\n"
        "## Related Concepts\n"
        "\n"
        "- [SQLite](sqlite.md) — 2 shared scrolls\n"
    )


def test_kb_summary_for_vanished_concept_is_simply_unused(scrolls_home, capsys):
    from scrolls.kb import save_concept_summary

    main(["init"])
    db = get_paths().db_path
    insert_item(db, make_rendered("web:abc", "web", "A post", concepts=("SQLite",)))
    save_concept_summary(db, make_summary("bm25", "BM25", "Nothing links here anymore."))
    capsys.readouterr()

    payload = run_kb(capsys)
    assert payload["summaries"] == 0
    assert not (scrolls_home / "library" / "concepts" / "bm25.md").exists()


def test_concept_summary_store_roundtrip_and_delete(scrolls_home):
    from scrolls.kb import (
        delete_concept_summaries,
        load_concept_summaries,
        save_concept_summary,
    )

    main(["init"])
    db = get_paths().db_path
    assert load_concept_summaries(db) == {}

    save_concept_summary(db, make_summary("bm25", "BM25", "First take."))
    save_concept_summary(db, make_summary("bm25", "BM25", "Second take.", members_hash="def456"))
    save_concept_summary(db, make_summary("sqlite", "SQLite", "An embedded database."))

    stored = load_concept_summaries(db)
    assert set(stored) == {"bm25", "sqlite"}
    assert stored["bm25"].summary == "Second take."  # replaced, not duplicated
    assert stored["bm25"].members_hash == "def456"

    delete_concept_summaries(db, ["bm25"])
    assert set(load_concept_summaries(db)) == {"sqlite"}
    delete_concept_summaries(db, [])  # no-op, never raises


def test_load_concept_summaries_tolerates_pre_v6_database(tmp_path):
    """`scrolls kb` reads without migrating; a v5 library must not crash it."""
    import sqlite3

    from scrolls.db import MIGRATIONS
    from scrolls.kb import load_concept_summaries

    db_path = tmp_path / "db.sqlite"
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        for version in (1, 2, 3, 4, 5):
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '5')")
    conn.close()

    assert load_concept_summaries(db_path) == {}

# --- scrolls kb --engine llm (ADR 0025) -----------------------------------


@pytest.fixture
def fake_summary_llm(monkeypatch):
    """Replace the concept engine's Anthropic completer with a canned summary."""
    import scrolls.kb_llm as kb_llm

    calls = []

    def complete(system, user, model):
        calls.append({"system": system, "user": user, "model": model})
        return json.dumps({"summary": "BM25 threads through search-ranking scrolls."})

    monkeypatch.setattr(kb_llm, "_anthropic_complete", complete)
    return calls


def seed_bm25_pair(db):
    insert_item(db, make_rendered(
        "wikipedia:en:Okapi_BM25", "wikipedia", "Okapi BM25", concepts=("BM25",)))
    insert_item(db, make_rendered(
        "web:fts", "web", "FTS in practice", concepts=("bm25",)))


def test_kb_llm_engine_synthesizes_then_compiles(scrolls_home, fake_summary_llm, capsys):
    main(["init"])
    seed_bm25_pair(get_paths().db_path)
    capsys.readouterr()

    exit_code = main(["kb", "--engine", "llm"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["generated"] == 1
    assert payload["results"] == [
        {"slug": "bm25", "concept": "BM25", "status": "generated"}
    ]
    assert payload["concepts"] == 1
    assert payload["summaries"] == 1
    assert len(fake_summary_llm) == 1

    page = (scrolls_home / "library" / "concepts" / "bm25.md").read_text(encoding="utf-8")
    assert "BM25 threads through search-ranking scrolls." in page

    # a later plain compile keeps the summary without any model call
    exit_code = main(["kb"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["summaries"] == 1
    assert len(fake_summary_llm) == 1
    page = (scrolls_home / "library" / "concepts" / "bm25.md").read_text(encoding="utf-8")
    assert "BM25 threads through search-ranking scrolls." in page


def test_kb_llm_engine_rerun_is_free_when_nothing_changed(
    scrolls_home, fake_summary_llm, capsys
):
    main(["init"])
    seed_bm25_pair(get_paths().db_path)
    main(["kb", "--engine", "llm"])
    capsys.readouterr()

    exit_code = main(["kb", "--engine", "llm"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["generated"] == 0
    assert payload["current"] == 1
    assert len(fake_summary_llm) == 1  # no new model calls


def test_kb_llm_engine_without_credentials_aborts_before_compiling(
    scrolls_home, monkeypatch, capsys
):
    import scrolls.kb_llm as kb_llm
    from scrolls.llm import LLMAuthError

    def no_auth(system, user, model):
        raise LLMAuthError("llm engine needs Anthropic credentials")

    monkeypatch.setattr(kb_llm, "_anthropic_complete", no_auth)
    main(["init"])
    seed_bm25_pair(get_paths().db_path)
    capsys.readouterr()

    exit_code = main(["kb", "--engine", "llm"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "credentials" in json.loads(captured.err)["error"]
    assert not (scrolls_home / "library" / "index.md").exists()


def test_kb_llm_engine_reports_failures_but_still_compiles(
    scrolls_home, monkeypatch, capsys
):
    import scrolls.kb_llm as kb_llm
    from scrolls.llm import LLMError

    def broken(system, user, model):
        raise LLMError("Anthropic API error: overloaded")

    monkeypatch.setattr(kb_llm, "_anthropic_complete", broken)
    main(["init"])
    seed_bm25_pair(get_paths().db_path)
    capsys.readouterr()

    exit_code = main(["kb", "--engine", "llm"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed"] == 1
    assert payload["results"][0]["status"] == "failed"
    assert payload["summaries"] == 0
    assert (scrolls_home / "library" / "index.md").exists()  # compile still ran


def test_kb_llm_engine_on_uninitialized_library_is_a_zero_run(
    scrolls_home, fake_summary_llm, capsys
):
    exit_code = main(["kb", "--engine", "llm"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["generated"] == 0
    assert payload["pages"] == 0
    assert fake_summary_llm == []
    assert not scrolls_home.exists()  # kb never creates a library


def test_kb_llm_engine_uses_config_llm_model(scrolls_home, fake_summary_llm, capsys):
    main(["init"])
    seed_bm25_pair(get_paths().db_path)
    (scrolls_home / "config.toml").write_text(
        '[classify]\nllm_model = "claude-from-config"\n', encoding="utf-8"
    )
    capsys.readouterr()

    exit_code = main(["kb", "--engine", "llm"])
    assert exit_code == 0
    assert fake_summary_llm[0]["model"] == "claude-from-config"


def test_kb_llm_engine_rejects_invalid_config(scrolls_home, fake_summary_llm, capsys):
    main(["init"])
    (scrolls_home / "config.toml").write_text("not toml [", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(["kb", "--engine", "llm"])
    assert exit_code == 1
    assert "invalid TOML" in json.loads(capsys.readouterr().err)["error"]
    assert fake_summary_llm == []


# --- scrolls kb --engine llm --batch (ADR 0032) ---------------------------


@pytest.fixture
def fake_summary_llm_batch(monkeypatch):
    """Replace the concept engine's Batches transport with a canned summary."""
    import scrolls.kb_llm as kb_llm

    calls = []

    def complete_batch(system, requests, model):
        calls.append({"system": system, "requests": list(requests), "model": model})
        return {
            cid: json.dumps({"summary": "BM25 threads through search-ranking scrolls."})
            for cid, _ in requests
        }

    monkeypatch.setattr(kb_llm, "_anthropic_complete_batch", complete_batch)
    return calls


def test_kb_llm_batch_flag_submits_one_batch(
    scrolls_home, fake_summary_llm, fake_summary_llm_batch, capsys
):
    main(["init"])
    seed_bm25_pair(get_paths().db_path)
    capsys.readouterr()

    exit_code = main(["kb", "--engine", "llm", "--batch"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["generated"] == 1
    assert payload["summaries"] == 1
    assert len(fake_summary_llm_batch) == 1  # one Batches submission...
    assert fake_summary_llm == []  # ...and no per-concept calls

    page = (scrolls_home / "library" / "concepts" / "bm25.md").read_text(encoding="utf-8")
    assert "BM25 threads through search-ranking scrolls." in page


def test_kb_batch_flag_requires_the_llm_engine(scrolls_home, capsys):
    exit_code = main(["kb", "--batch"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "llm" in json.loads(captured.err)["error"]


def test_kb_llm_batch_without_credentials_aborts_before_compiling(
    scrolls_home, monkeypatch, capsys
):
    import scrolls.kb_llm as kb_llm
    from scrolls.llm import LLMAuthError

    def no_auth(system, requests, model):
        raise LLMAuthError("llm engine needs Anthropic credentials")

    monkeypatch.setattr(kb_llm, "_anthropic_complete_batch", no_auth)
    main(["init"])
    seed_bm25_pair(get_paths().db_path)
    capsys.readouterr()

    exit_code = main(["kb", "--engine", "llm", "--batch"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "credentials" in json.loads(captured.err)["error"]
    assert not (scrolls_home / "library" / "index.md").exists()


def test_kb_llm_batch_rejected_submission_aborts_before_compiling(
    scrolls_home, monkeypatch, capsys
):
    # A rejected submission raises the shared transport's base LLMError
    # (not the auth subclass); the CLI's widened catch must still abort.
    import scrolls.kb_llm as kb_llm
    from scrolls.llm import LLMError

    def rejected(system, requests, model):
        raise LLMError("Anthropic API error: batch submission rejected")

    monkeypatch.setattr(kb_llm, "_anthropic_complete_batch", rejected)
    main(["init"])
    seed_bm25_pair(get_paths().db_path)
    capsys.readouterr()

    exit_code = main(["kb", "--engine", "llm", "--batch"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "rejected" in json.loads(captured.err)["error"]
    assert not (scrolls_home / "library" / "index.md").exists()


def test_kb_llm_batch_per_concept_failure_compiles_and_exits_1(
    scrolls_home, monkeypatch, capsys
):
    # A per-concept batch failure is reported, the library still compiles,
    # and the run exits 1 — the batch path's exit-code wiring.
    import scrolls.kb_llm as kb_llm
    from scrolls.llm import LLMError

    def one_failure(system, requests, model):
        return {cid: LLMError("batch request expired") for cid, _ in requests}

    monkeypatch.setattr(kb_llm, "_anthropic_complete_batch", one_failure)
    main(["init"])
    seed_bm25_pair(get_paths().db_path)
    capsys.readouterr()

    exit_code = main(["kb", "--engine", "llm", "--batch"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed"] == 1
    assert payload["results"][0]["status"] == "failed"
    assert payload["summaries"] == 0
    assert (scrolls_home / "library" / "index.md").exists()  # compile still ran


# --- scrolls kb --stale: targeted summary refresh (roadmap H31) -----------
#
# The summary-axis counterpart of `classify --stale` (H27). `kb --stale`
# re-synthesizes exactly the concept summaries `scrolls doctor` reports stale
# in custody.summaries — members changed since synthesis — and nothing else:
# never-summarized eligible concepts are left for a full `kb --engine llm`
# (generation, not refresh). One shared `is_stale_summary` predicate backs both
# doctor's report and the refresh, so the count converges and the loop H29
# (record/report) → H31 (refresh) closes.


def _add_bm25_member(db, item_id):
    """Add another rendered scroll to the BM25 concept (its members change)."""
    insert_item(db, make_rendered(item_id, "web", item_id, concepts=("BM25",)))


def test_kb_stale_refreshes_only_the_stale_summary(
    scrolls_home, fake_summary_llm, capsys
):
    main(["init"])
    db = get_paths().db_path
    seed_bm25_pair(db)
    main(["kb", "--engine", "llm"])  # bm25 summarized over 2 members
    capsys.readouterr()

    # bm25's members change (now stale); a brand-new concept appears unsummarized
    _add_bm25_member(db, "web:bm25-extra")
    insert_item(db, make_rendered("web:g1", "web", "Graph one", concepts=("Graphs",)))
    insert_item(db, make_rendered("web:g2", "web", "Graph two", concepts=("Graphs",)))

    exit_code = main(["kb", "--stale"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    # only the stale concept is regenerated — not the never-summarized one
    assert payload["generated"] == 1
    assert payload["results"] == [
        {"slug": "bm25", "concept": "BM25", "status": "generated"}
    ]
    assert len(fake_summary_llm) == 2  # the initial synthesis + this one refresh

    from scrolls.kb import load_concept_summaries

    stored = load_concept_summaries(db)
    assert "graphs" not in stored  # the new eligible concept is left for a full run


def test_kb_stale_is_a_noop_when_nothing_is_stale(
    scrolls_home, fake_summary_llm, capsys
):
    main(["init"])
    seed_bm25_pair(get_paths().db_path)
    main(["kb", "--engine", "llm"])
    capsys.readouterr()

    # nothing changed since synthesis: --stale touches nothing and calls no model
    exit_code = main(["kb", "--stale"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["generated"] == 0
    assert payload["current"] == 0  # current concepts aren't even in the target set
    assert len(fake_summary_llm) == 1  # no new model call — network-free no-op


def test_kb_stale_rejects_the_deterministic_engine(scrolls_home, capsys):
    exit_code = main(["kb", "--stale", "--engine", "deterministic"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "deterministic" in json.loads(captured.err)["error"]


def test_kb_stale_clears_the_doctor_stale_signal(
    scrolls_home, fake_summary_llm, capsys
):
    # the loop closes: doctor reports one stale summary, --stale refreshes
    # exactly it, and doctor then reports none stale (one current instead)
    from scrolls.doctor import run_doctor

    main(["init"])
    db = get_paths().db_path
    seed_bm25_pair(db)
    main(["kb", "--engine", "llm"])
    _add_bm25_member(db, "web:bm25-extra")  # bm25 now stale
    capsys.readouterr()

    before = run_doctor(get_paths())["custody"]["summaries"]
    assert before["stale"] == 1
    assert before["current"] == 0

    assert main(["kb", "--stale"]) == 0
    capsys.readouterr()

    after = run_doctor(get_paths())["custody"]["summaries"]
    assert after["stale"] == 0
    assert after["current"] == 1  # refreshed to the live 3-member fingerprint


def test_kb_stale_batch_refreshes_the_stale_summary_in_one_submission(
    scrolls_home, fake_summary_llm, fake_summary_llm_batch, capsys
):
    # --stale composes with the batch transport (both are the llm engine):
    # the stale concept is refreshed via one Batches submission, not per-call
    main(["init"])
    db = get_paths().db_path
    seed_bm25_pair(db)
    main(["kb", "--engine", "llm"])  # per-call synthesis
    _add_bm25_member(db, "web:bm25-extra")
    capsys.readouterr()

    exit_code = main(["kb", "--stale", "--batch"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["generated"] == 1
    assert len(fake_summary_llm_batch) == 1  # one submission for the one stale concept
    assert len(fake_summary_llm) == 1  # no extra per-call beyond the initial synthesis


# --- scrolls kb --stale --source <S>: the per-source summary refresh (H172) ---
#
# The summary-axis counterpart of `classify --stale --source` (H154). `--source`
# narrows the `--stale` refresh to the concepts that source participates in —
# doctor's custody.summaries.by_source[<S>] offenders (H171). A multi-source
# cluster is refreshed under any of its sources (it shares the cluster); the
# refresh clears that source's entry from the by_source map and leaves the rest.


def _seed_two_source_stale_summaries(db):
    """BM25 (wikipedia+web) and Graphs (arxiv): both summarized, then both stale."""
    insert_item(db, make_rendered("wikipedia:bm25", "wikipedia", "Okapi BM25",
                                  concepts=("BM25",)))
    insert_item(db, make_rendered("web:fts", "web", "FTS in practice",
                                  concepts=("BM25",)))
    insert_item(db, make_rendered("arxiv:g1", "arxiv", "Graph one",
                                  concepts=("Graphs",)))
    insert_item(db, make_rendered("arxiv:g2", "arxiv", "Graph two",
                                  concepts=("Graphs",)))
    main(["kb", "--engine", "llm"])  # both synthesized
    insert_item(db, make_rendered("web:bm25-3", "web", "More BM25", concepts=("BM25",)))
    insert_item(db, make_rendered("arxiv:g3", "arxiv", "Graph three",
                                  concepts=("Graphs",)))


def test_kb_stale_source_refreshes_only_that_sources_concepts(
    scrolls_home, fake_summary_llm, capsys
):
    main(["init"])
    db = get_paths().db_path
    _seed_two_source_stale_summaries(db)
    capsys.readouterr()

    exit_code = main(["kb", "--stale", "--source", "arxiv"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    # only arxiv's concept (Graphs) is refreshed — BM25 (web/wikipedia) is left
    assert payload["generated"] == 1
    assert payload["results"] == [
        {"slug": "graphs", "concept": "Graphs", "status": "generated"}
    ]


def test_kb_stale_source_clears_only_that_sources_doctor_entry(
    scrolls_home, fake_summary_llm, capsys
):
    # the per-source signal-clears property: doctor reports both sources stale,
    # `--source arxiv` refreshes just arxiv's concept, and doctor then reports
    # only the other sources (web/wikipedia) stale — arxiv's entry is gone.
    from scrolls.doctor import run_doctor

    main(["init"])
    db = get_paths().db_path
    _seed_two_source_stale_summaries(db)
    capsys.readouterr()

    before = run_doctor(get_paths())["custody"]["summaries"]
    assert before["stale"] == 2  # BM25 + Graphs
    assert before["by_source"] == {"arxiv": 1, "web": 1, "wikipedia": 1}

    assert main(["kb", "--stale", "--source", "arxiv"]) == 0
    capsys.readouterr()

    after = run_doctor(get_paths())["custody"]["summaries"]
    assert after["stale"] == 1  # only BM25 remains
    assert after["by_source"] == {"web": 1, "wikipedia": 1}  # arxiv cleared


def test_kb_stale_source_for_a_multi_source_cluster_refreshes_under_either_source(
    scrolls_home, fake_summary_llm, capsys
):
    # BM25 spans wikipedia + web; refreshing under *either* source regenerates it
    # (the H171 attribution — a stale cluster is "stale for" every member source).
    from scrolls.doctor import run_doctor

    main(["init"])
    db = get_paths().db_path
    _seed_two_source_stale_summaries(db)
    capsys.readouterr()

    assert main(["kb", "--stale", "--source", "wikipedia"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"] == [
        {"slug": "bm25", "concept": "BM25", "status": "generated"}
    ]
    after = run_doctor(get_paths())["custody"]["summaries"]
    # BM25 refreshed → web *and* wikipedia entries clear; only arxiv (Graphs) left
    assert after["by_source"] == {"arxiv": 1}


def test_kb_stale_source_unknown_is_a_network_free_noop(
    scrolls_home, fake_summary_llm, capsys
):
    main(["init"])
    db = get_paths().db_path
    _seed_two_source_stale_summaries(db)
    calls_before = len(fake_summary_llm)
    capsys.readouterr()

    exit_code = main(["kb", "--stale", "--source", "ghost"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["generated"] == 0
    assert payload["results"] == []
    assert len(fake_summary_llm) == calls_before  # no model call for an unknown source


def test_kb_source_without_stale_is_a_usage_error(scrolls_home, capsys):
    # `--source` narrows the --stale refresh; alone it has no stale set to narrow
    exit_code = main(["kb", "--source", "web"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--stale" in json.loads(captured.err)["error"]


def test_kb_stale_source_rejects_the_deterministic_engine(scrolls_home, capsys):
    # --stale is rules-free here: it's the llm summary refresh; deterministic is a
    # contradiction even with --source (the existing --stale guard covers it)
    exit_code = main(["kb", "--stale", "--source", "web", "--engine", "deterministic"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "deterministic" in json.loads(captured.err)["error"]


def test_kb_stale_source_composes_with_batch(
    scrolls_home, fake_summary_llm, fake_summary_llm_batch, capsys
):
    # --source narrows the batch transport identically (both are the llm engine)
    main(["init"])
    db = get_paths().db_path
    _seed_two_source_stale_summaries(db)
    capsys.readouterr()

    exit_code = main(["kb", "--stale", "--source", "arxiv", "--batch"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"] == [
        {"slug": "graphs", "concept": "Graphs", "status": "generated"}
    ]
    assert len(fake_summary_llm_batch) == 1  # one submission for the one scoped concept
