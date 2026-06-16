"""Tests for the compiled library (IDEAS.md §9, §14 Pass 5)."""

import json

import pytest

from scrolls.cli import main
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
                  source_id=None, url=None):
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


def _category_bullets(scrolls_home, slug):
    """The top-level (column-0) bullets of a compiled category page."""
    page = (scrolls_home / "library" / "categories" / f"{slug}.md").read_text(
        encoding="utf-8"
    )
    return [line for line in page.splitlines() if line.startswith("- ")]


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
    assert bullets[0] == "- [Apex Paper](../../scrolls/web/apex-paper.md) — web"
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
    assert bullets == ["- [Solo Preprint](../../scrolls/arxiv/solo-preprint.md) — arxiv"]


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
        "- [A](../../scrolls/web/a.md) — web\n"
        "- [B](../../scrolls/web/b.md) — web\n"
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
