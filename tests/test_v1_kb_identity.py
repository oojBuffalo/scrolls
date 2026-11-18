"""A compiled group owns its filename and annotations across later compiles."""
import dataclasses

import pytest

from scrolls.generated import generated_body
from scrolls.items import ScrollItem, insert_item, update_item
from scrolls.kb import compile_kb
from scrolls.mcp_server import get_tag_page
from scrolls.paths import get_paths
from scrolls.pipeline import ensure_library
from scrolls.render import write_scroll


@pytest.fixture
def library(monkeypatch, tmp_path):
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path))
    paths = get_paths()
    ensure_library(paths)
    return paths


def save(paths, suffix, **fields):
    item = ScrollItem(id=f"web:{suffix}", source="web", source_id=suffix,
                      url=f"https://example.com/{suffix}", title=suffix,
                      saved_at="2026-01-01T00:00:00+00:00", stage="fetched",
                      raw_text="Held text", extracted_text="Held text", **fields)
    item = write_scroll(paths, item)
    insert_item(paths.db_path, item)
    return item


def page_for(paths, directory, heading):
    return next(p for p in (paths.library_dir / directory).glob("*.md")
                if (generated_body(p.read_text()) or "").startswith(heading + "\n"))


def test_adding_colliding_tag_keeps_annotation_with_its_original_group(library):
    item = save(library, "cpp", tags=("C++",))
    compile_kb(library)
    original = page_for(library, "tags", "# Tag: C++")
    original.write_text(original.read_text() + "\nMy C++ note\n")
    update_item(library.db_path, dataclasses.replace(item, tags=("C++", "C#")))
    compile_kb(library)
    assert page_for(library, "tags", "# Tag: C++") == original
    assert "My C++ note" in get_tag_page("C++")
    assert "My C++ note" not in get_tag_page("C#")


def test_category_slug_collisions_keep_every_membership(library):
    save(library, "cpp", category="C++")
    save(library, "csharp", category="C#")
    compile_kb(library)
    cpp = page_for(library, "categories", "# Category: C++")
    csharp = page_for(library, "categories", "# Category: C#")
    assert cpp != csharp
    assert "cpp.md" in cpp.read_text()
    assert "csharp.md" in csharp.read_text()
    index = (library.library_dir / "index.md").read_text()
    assert f"[C++](categories/{cpp.name})" in index
    assert f"[C#](categories/{csharp.name})" in index


def test_tag_suffix_does_not_overwrite_a_literal_slug(library):
    save(library, "tagged", tags=("C#", "C++", "C-2"))
    compile_kb(library)
    paths = [page_for(library, "tags", f"# Tag: {tag}")
             for tag in ("C#", "C++", "C-2")]
    assert len(set(paths)) == 3
    for tag in ("C#", "C++", "C-2"):
        assert f"# Tag: {tag}\n" in get_tag_page(tag)


def test_annotation_cannot_be_claimed_by_a_replacement_category(library):
    item = save(library, "cpp", category="C++")
    compile_kb(library)
    original = page_for(library, "categories", "# Category: C++")
    original.write_text(original.read_text() + "\nMy C++ note\n")
    update_item(library.db_path, dataclasses.replace(item, category="C#"))
    compile_kb(library)
    assert "My C++ note" in original.read_text()
    assert "no longer part of the compiled library" in original.read_text()
    replacement = page_for(library, "categories", "# Category: C#")
    assert replacement != original
    assert "My C++ note" not in replacement.read_text()
    update_item(library.db_path, item)
    compile_kb(library)
    assert page_for(library, "categories", "# Category: C++") == original
    assert "My C++ note" in original.read_text()
    assert "no longer part" not in original.read_text()


def test_merged_spellings_count_each_item_once(library):
    save(library, "merged", tags=("MIT", "mit"), concepts=("RAG", "rag"))
    result = compile_kb(library)
    assert result.tags == result.concepts == 1
    for directory, heading in (("tags", "# Tag: MIT"), ("concepts", "# Concept: RAG")):
        text = page_for(library, directory, heading).read_text()
        assert "1 scroll." in text
        assert text.count("merged.md)") == 1


def test_multiline_category_keeps_its_page_and_annotation(library):
    save(library, "multi", category="A\nB")
    compile_kb(library)
    [page] = (library.library_dir / "categories").glob("*.md")
    page.write_text(page.read_text() + "\nMy note\n")
    compile_kb(library)
    assert list((library.library_dir / "categories").glob("*.md")) == [page]
    assert "My note" in page.read_text()
    assert "no longer part" not in page.read_text()
    # A new group named like the first line must not inherit the page.
    save(library, "plain", category="A")
    compile_kb(library)
    assert "My note" in page.read_text()
    assert "My note" not in page_for(library, "categories", "# Category: A").read_text()


def test_legacy_multiline_heading_keeps_its_annotation_from_a_first_line_namesake(library):
    save(library, "multi", category="A\nB")
    compile_kb(library)
    [page] = (library.library_dir / "categories").glob("*.md")
    # A page written before group names were one line carried the raw name.
    legacy = page.read_text().replace("# Category: A B", "# Category: A\nB")
    assert legacy != page.read_text()
    page.write_text(legacy + "\nMy note\n")
    save(library, "plain", category="A")
    compile_kb(library)
    assert page == page_for(library, "categories", "# Category: A B")
    assert "My note" in page.read_text()
    assert "My note" not in page_for(library, "categories", "# Category: A").read_text()


def test_tag_page_lookup_uses_the_one_line_name(library):
    save(library, "sep", tags=("A\u0085B",))
    compile_kb(library)
    assert "# Tag: A B" in get_tag_page("A\u0085B")


def test_tombstone_of_a_legacy_multiline_page_keeps_its_whole_name(library):
    item = save(library, "multi", category="A\nB")
    compile_kb(library)
    [page] = (library.library_dir / "categories").glob("*.md")
    page.write_text(page.read_text().replace("# Category: A B", "# Category: A\nB") + "\nMy note\n")
    update_item(library.db_path, dataclasses.replace(item, category=None))
    compile_kb(library)
    assert generated_body(page.read_text()).startswith("# Category: A B\n")
    save(library, "plain", category="A")
    compile_kb(library)
    assert "My note" in page.read_text()
    assert "My note" not in page_for(library, "categories", "# Category: A").read_text()


def test_tag_page_lookup_finds_a_page_kept_at_a_legacy_filename(library):
    save(library, "sep", tags=("A\u0085B",))
    compile_kb(library)
    [page] = (library.library_dir / "tags").glob("*.md")
    page.rename(page.with_name("ab.md"))  # the name the old slug gave this tag
    compile_kb(library)
    assert [p.name for p in (library.library_dir / "tags").glob("*.md")] == ["ab.md"]
    assert "# Tag: A B" in get_tag_page("A\u0085B")


def test_new_group_never_takes_a_page_name_differing_only_in_case(library):
    item = save(library, "cs", tags=("C#",))
    compile_kb(library)
    [page] = (library.library_dir / "tags").glob("*.md")
    page.write_text(page.read_text() + "\nMy C# note\n")
    page = page.rename(page.with_name("C.md"))  # one file with c.md on macOS and Windows
    update_item(library.db_path, dataclasses.replace(item, tags=("C#", "C++")))
    compile_kb(library)
    stems = sorted(p.stem for p in (library.library_dir / "tags").glob("*.md"))
    assert stems == ["C", "c-2"]
    assert "My C# note" in get_tag_page("C#")
    assert "My C# note" not in get_tag_page("C++")


def test_tag_page_lookup_matches_the_compilers_key_not_a_looser_fold(library):
    save(library, "sharp", tags=("ss",))
    compile_kb(library)
    assert "# Tag: ss" in get_tag_page("SS")
    with pytest.raises(ValueError):
        get_tag_page("\u00df")  # casefolds to "ss" but is a different tag


def test_tag_page_lookup_prefers_the_live_page_over_a_tombstone(library):
    save(library, "one", tags=("A B",))
    compile_kb(library)
    [page] = (library.library_dir / "tags").glob("*.md")
    twin = page.with_name("a-b-2.md")  # sorts first, so it claims the group
    twin.write_text(page.read_text())
    page.write_text(page.read_text() + "\nMy note\n")
    compile_kb(library)
    assert "no longer part" in page.read_text()
    assert get_tag_page("A B") == twin.read_text()


def test_compile_ignores_a_directory_named_like_a_page(library):
    save(library, "one", tags=("A",))
    (library.library_dir / "tags" / "odd.md").mkdir(parents=True)
    assert compile_kb(library).tags == 1


def test_tag_page_lookup_skips_a_directory_named_like_a_page(library):
    save(library, "sep", tags=("A\u0085B",))
    compile_kb(library)
    [page] = (library.library_dir / "tags").glob("*.md")
    page.rename(page.with_name("zz.md"))  # found only by the all-pages fallback
    (library.library_dir / "tags" / "aa.md").mkdir()  # sorts ahead of it
    compile_kb(library)
    assert "# Tag: A B" in get_tag_page("A\u0085B")
