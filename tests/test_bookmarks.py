"""Tests for the browser-bookmarks HTML importer (IDEAS.md §13)."""

import pytest

from scrolls.bookmarks import ImportSourceError, load_bookmark_export
from scrolls.items import make_item_id

# A realistic Chrome/Firefox-style export: Netscape bookmark file format,
# unclosed <DT>/<DD> tags and all. ADD_DATE values are epoch seconds.
EXPORT = """\
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<!-- This is an automatically generated file. -->
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 ADD_DATE="1614556800" PERSONAL_TOOLBAR_FOLDER="true">Bookmarks bar</H3>
    <DL><p>
        <DT><H3 ADD_DATE="1614556800">Databases</H3>
        <DL><p>
            <DT><A HREF="https://example.com/sqlite-article?utm_source=share" ADD_DATE="1614556800">SQLite &amp; FTS Internals</A>
            <DD>Why SQLite's full-text search is enough.
            <DT><A HREF="https://www.youtube.com/watch?v=abc123xyz00" ADD_DATE="1620000000">How SQLite FTS Works</A>
        </DL><p>
        <DT><A HREF="javascript:alert('hi')" ADD_DATE="1610000000">Bookmarklet</A>
    </DL><p>
    <DT><H3 ADD_DATE="1614556800">Reading</H3>
    <DL><p>
        <DT><A HREF="https://example.com/sqlite-article" ADD_DATE="1700000000">SQLite article again</A>
    </DL><p>
</DL><p>
"""


def _write_export(tmp_path, text=EXPORT, name="bookmarks.html"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_imports_bookmarks_as_detected_items(tmp_path):
    items, stats = load_bookmark_export(_write_export(tmp_path))
    assert [item.id for item in items] == [
        make_item_id("web", None, "https://example.com/sqlite-article"),
        "youtube:abc123xyz00",
    ]
    article, video = items
    assert article.source == "web"
    assert article.stage == "detected"
    # tracking params are stripped before identity is minted (ADR 0023)
    assert article.url == "https://example.com/sqlite-article"
    assert article.title == "SQLite & FTS Internals"
    assert article.saved_at == "2021-03-01T00:00:00+00:00"
    assert video.source == "youtube"
    assert video.source_id == "abc123xyz00"
    assert video.title == "How SQLite FTS Works"
    assert stats == {
        "bookmarks": 4,
        "repeats": 1,
        "ignored": {"not_http": 1, "no_url": 0},
    }


def test_folder_ancestry_becomes_tags(tmp_path):
    items, _ = load_bookmark_export(_write_export(tmp_path))
    article = items[0]
    # "Bookmarks bar" is browser furniture, not curation — excluded;
    # the same URL in two folders unions both folders' tags
    assert article.tags == ("Databases", "Reading")
    assert items[1].tags == ("Databases",)


def test_dd_description_seeds_summary(tmp_path):
    items, _ = load_bookmark_export(_write_export(tmp_path))
    assert items[0].summary == "Why SQLite's full-text search is enough."
    assert items[1].summary is None


def test_repeat_urls_collapse_to_the_earliest(tmp_path):
    items, stats = load_bookmark_export(_write_export(tmp_path))
    # the Reading copy was added later; the earliest ADD_DATE wins
    assert items[0].saved_at == "2021-03-01T00:00:00+00:00"
    assert items[0].title == "SQLite & FTS Internals"
    assert stats["repeats"] == 1


def test_firefox_tags_attribute_merges_with_folder_tags(tmp_path):
    export = """\
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><H3>Papers</H3>
    <DL><p>
        <DT><A HREF="https://arxiv.org/abs/2403.00001" ADD_DATE="1700000000" TAGS="ranking,Papers">Some Paper</A>
    </DL><p>
</DL><p>
"""
    items, _ = load_bookmark_export(_write_export(tmp_path, export))
    assert items[0].id == "arxiv:2403.00001"
    assert items[0].tags == ("Papers", "ranking")  # deduped, folder first


def test_root_container_folders_are_not_tags(tmp_path):
    export = """\
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><H3>Bookmarks Toolbar</H3>
    <DL><p>
        <DT><A HREF="https://example.com/a" ADD_DATE="1700000000">A</A>
    </DL><p>
    <DT><H3>Other Bookmarks</H3>
    <DL><p>
        <DT><A HREF="https://example.com/b" ADD_DATE="1700000000">B</A>
    </DL><p>
</DL><p>
"""
    items, _ = load_bookmark_export(_write_export(tmp_path, export))
    assert [item.tags for item in items] == [(), ()]


def test_bookmark_at_top_level_has_no_tags(tmp_path):
    export = """\
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><A HREF="https://example.com/loose" ADD_DATE="1700000000">Loose</A>
</DL><p>
"""
    items, _ = load_bookmark_export(_write_export(tmp_path, export))
    assert items[0].tags == ()


def test_nested_folder_ancestry_is_ordered_outer_first(tmp_path):
    export = """\
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><H3 PERSONAL_TOOLBAR_FOLDER="true">Bookmarks bar</H3>
    <DL><p>
        <DT><H3>Programming</H3>
        <DL><p>
            <DT><H3>Databases</H3>
            <DL><p>
                <DT><A HREF="https://example.com/deep" ADD_DATE="1700000000">Deep</A>
            </DL><p>
        </DL><p>
    </DL><p>
</DL><p>
"""
    items, _ = load_bookmark_export(_write_export(tmp_path, export))
    assert items[0].tags == ("Programming", "Databases")


def test_folder_description_is_not_a_bookmark_summary(tmp_path):
    # old Firefox and some services write <DD> folder descriptions; they
    # must not leak into the previous bookmark's summary
    export = """\
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><A HREF="https://example.com/a" ADD_DATE="1700000000">A</A>
    <DT><H3>Research</H3>
    <DD>Papers I keep meaning to read.
    <DL><p>
        <DT><A HREF="https://example.com/b" ADD_DATE="1700000000">B</A>
    </DL><p>
</DL><p>
"""
    items, _ = load_bookmark_export(_write_export(tmp_path, export))
    assert [item.summary for item in items] == [None, None]


def test_truncated_export_keeps_the_dangling_bookmark(tmp_path):
    # a file cut off mid-entry still surfaces the last anchor
    export = """\
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><A HREF="https://example.com/a" ADD_DATE="1700000000">A</A>
    <DT><A HREF="https://example.com/b" ADD_DATE="1700000000">cut of"""
    items, stats = load_bookmark_export(_write_export(tmp_path, export))
    assert [item.url for item in items] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert stats["bookmarks"] == 2


def test_inline_markup_inside_dd_notes_survives(tmp_path):
    # service exports may format descriptions; formatting tags must not
    # truncate the note
    export = """\
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><A HREF="https://example.com/a" ADD_DATE="1700000000">A</A>
    <DD>First half <i>with emphasis</i> second half.
</DL><p>
"""
    items, _ = load_bookmark_export(_write_export(tmp_path, export))
    assert items[0].summary == "First half with emphasis second half."


def test_missing_add_date_falls_back_to_import_time(tmp_path):
    export = """\
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><A HREF="https://example.com/undated">Undated</A>
</DL><p>
"""
    items, _ = load_bookmark_export(_write_export(tmp_path, export))
    assert items[0].saved_at  # never empty: list/doctor rely on saved_at


def test_millisecond_add_dates_are_normalized(tmp_path):
    # some exporters write epoch milli/microseconds; same instant either way
    export = """\
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><A HREF="https://example.com/ms" ADD_DATE="1614556800000">MS</A>
</DL><p>
"""
    items, _ = load_bookmark_export(_write_export(tmp_path, export))
    assert items[0].saved_at == "2021-03-01T00:00:00+00:00"


def test_non_http_schemes_are_ignored_not_fatal(tmp_path):
    export = """\
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><A HREF="place:type=6&sort=14" ADD_DATE="1700000000">Recent Tags</A>
    <DT><A HREF="file:///home/me/notes.txt" ADD_DATE="1700000000">Notes</A>
    <DT><A HREF="https://example.com/ok" ADD_DATE="1700000000">OK</A>
</DL><p>
"""
    items, stats = load_bookmark_export(_write_export(tmp_path, export))
    assert [item.url for item in items] == ["https://example.com/ok"]
    assert stats["ignored"]["not_http"] == 2


def test_anchor_without_href_is_counted(tmp_path):
    export = """\
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><A ADD_DATE="1700000000">No link</A>
</DL><p>
"""
    items, stats = load_bookmark_export(_write_export(tmp_path, export))
    assert items == []
    assert stats["ignored"]["no_url"] == 1


def test_x_bookmarks_register_without_an_adapter(tmp_path):
    # detection routes everything; x has no fetch adapter yet, but the
    # item registers exactly as `scrolls add` would register it
    export = """\
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><A HREF="https://x.com/someone/status/1234567890" ADD_DATE="1700000000">A tweet</A>
</DL><p>
"""
    items, _ = load_bookmark_export(_write_export(tmp_path, export))
    assert items[0].id == "x:1234567890"
    assert items[0].source == "x"


def test_empty_folders_import_nothing(tmp_path):
    export = """\
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><H3>Empty</H3>
    <DL><p>
    </DL><p>
</DL><p>
"""
    items, stats = load_bookmark_export(_write_export(tmp_path, export))
    assert items == []
    assert stats == {"bookmarks": 0, "repeats": 0, "ignored": {"not_http": 0, "no_url": 0}}


def test_missing_path_raises(tmp_path):
    with pytest.raises(ImportSourceError):
        load_bookmark_export(tmp_path / "nowhere.html")


def test_non_bookmark_html_raises(tmp_path):
    path = _write_export(tmp_path, "<html><body><a href='https://x.com'>hi</a></body></html>")
    with pytest.raises(ImportSourceError, match="NETSCAPE-Bookmark-file"):
        load_bookmark_export(path)
