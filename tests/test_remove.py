"""Tests for `scrolls rm`: item removal (ADR 0027).

The removal engine (`remove.py`) is `scrolls add`'s inverse: it resolves
an id or URL to the id `add` would mint, deletes the files the item owns
(its scroll, its captured media), then deletes the row — files first,
row last, so an interrupted removal leaves a re-runnable item rather
than orphan files doctor refuses to delete. Recorded paths that escape
the library root fail the removal before anything is touched.
"""

import dataclasses

import pytest

from scrolls.db import init_db
from scrolls.items import ScrollItem, get_item, insert_item, make_item_id
from scrolls.paths import get_paths
from scrolls.remove import remove_item, resolve_item_id
from scrolls.render import write_scroll
from scrolls.search import search_items


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


@pytest.fixture
def paths(scrolls_home):
    library = get_paths()
    library.root.mkdir(parents=True)
    init_db(library.db_path)
    return library


def _web_item(url, *, fetched=False, **overrides):
    fields = {
        "id": make_item_id("web", None, url),
        "source": "web",
        "source_id": None,
        "url": url,
        "saved_at": "2026-06-12T08:00:00+00:00",
    }
    if fetched:
        fields.update(
            title="A Post",
            extracted_text="body text",
            summary="a post about things",
            content_hash="sha256:abc",
            stage="fetched",
        )
    fields.update(overrides)
    return ScrollItem(**fields)


# --- resolve_item_id: the id-or-URL handle ---


def test_resolve_passes_ids_through_verbatim():
    assert resolve_item_id("wikipedia:en:SQLite") == "wikipedia:en:SQLite"


def test_resolve_mints_the_same_id_as_add():
    url = "https://youtu.be/dQw4w9WgXcQ"
    assert resolve_item_id(url) == "youtube:dQw4w9WgXcQ"


def test_resolve_normalizes_urls_like_add():
    """A tracking-decorated spelling resolves to the clean URL's id (ADR 0023)."""
    clean = "https://example.com/post"
    junk = "https://example.com/post?utm_source=newsletter&fbclid=IwAR0"
    assert resolve_item_id(junk) == make_item_id("web", None, clean)


def test_resolve_rejects_non_http_urls():
    with pytest.raises(ValueError):
        resolve_item_id("ftp://example.com/file")


# --- remove_item: files first, row last ---


def test_remove_deletes_row_scroll_and_media(paths):
    item = _web_item("https://example.com/post", fetched=True)
    rendered = write_scroll(paths, item)
    media_relpath = "media/web/post-1.jpg"
    media_file = paths.root / media_relpath
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"jpeg")
    rendered = dataclasses.replace(
        rendered,
        media=(
            {"type": "photo", "url": "https://example.com/p.jpg", "path": media_relpath},
        ),
    )
    insert_item(paths.db_path, rendered)

    removed = remove_item(paths, rendered)

    assert sorted(removed) == sorted([rendered.markdown_path, media_relpath])
    assert not (paths.root / rendered.markdown_path).exists()
    assert not media_file.exists()
    assert get_item(paths.db_path, rendered.id) is None


def test_remove_detected_item_deletes_only_the_row(paths):
    item = _web_item("https://example.com/post")
    insert_item(paths.db_path, item)

    assert remove_item(paths, item) == []
    assert get_item(paths.db_path, item.id) is None


def test_remove_tolerates_files_already_gone(paths):
    """The goal state is absence; a hand-deleted scroll is not an error."""
    item = _web_item("https://example.com/post", fetched=True)
    rendered = write_scroll(paths, item)
    insert_item(paths.db_path, rendered)
    (paths.root / rendered.markdown_path).unlink()

    assert remove_item(paths, rendered) == []
    assert get_item(paths.db_path, rendered.id) is None


def test_remove_rejects_paths_escaping_the_root(paths, tmp_path):
    """A recorded path scrolls never wrote fails the removal untouched."""
    outside = tmp_path / "outside.md"
    outside.write_text("not scrolls' file")
    item = _web_item(
        "https://example.com/post", fetched=True, markdown_path="../outside.md"
    )
    insert_item(paths.db_path, item)

    with pytest.raises(ValueError):
        remove_item(paths, item)
    assert outside.exists()
    assert get_item(paths.db_path, item.id) is not None  # row kept: re-runnable


def test_remove_validates_every_path_before_deleting_any(paths, tmp_path):
    """One poisoned media ref must not half-delete the item's good files."""
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"x")
    item = _web_item("https://example.com/post", fetched=True)
    rendered = write_scroll(paths, item)
    rendered = dataclasses.replace(
        rendered,
        media=({"type": "photo", "url": "https://e.com/p", "path": "../outside.bin"},),
    )
    insert_item(paths.db_path, rendered)

    with pytest.raises(ValueError):
        remove_item(paths, rendered)
    assert (paths.root / rendered.markdown_path).exists()
    assert outside.exists()


def test_removed_item_leaves_the_search_index(paths):
    """The FTS delete trigger keeps search in sync — no manual rebuild."""
    item = _web_item("https://example.com/post", fetched=True)
    insert_item(paths.db_path, item)
    assert search_items(paths.db_path, "post")

    remove_item(paths, item)
    assert search_items(paths.db_path, "post") == []
