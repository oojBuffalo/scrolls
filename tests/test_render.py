"""Tests for Markdown scroll rendering (IDEAS.md §2-3, §14 Pass 2)."""

import dataclasses
import json

import pytest

from scrolls.items import ScrollItem
from scrolls.paths import get_paths
from scrolls.render import render_markdown, write_scroll


def make_item(**overrides):
    base = dict(
        id="wikipedia:en:SQLite",
        source="wikipedia",
        source_id="en:SQLite",
        url="https://en.wikipedia.org/wiki/SQLite",
        canonical_url="https://en.wikipedia.org/wiki/SQLite",
        title="SQLite",
        saved_at="2026-06-12T00:00:00+00:00",
        extracted_text="SQLite is a database engine.\n\n\n== History ==\nEarly days.",
        summary="SQLite is a database engine.",
        content_hash="sha256:abc",
        provenance={
            "adapter": "wikipedia",
            "fetched_at": "2026-06-12T00:00:00+00:00",
            "extraction_method": "mediawiki-api:extracts",
        },
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def parse_frontmatter(markdown):
    """Each frontmatter line is `key: <JSON value>` — valid YAML by construction."""
    assert markdown.startswith("---\n")
    block = markdown.split("---\n")[1]
    fields = {}
    for line in block.splitlines():
        key, _, value = line.partition(": ")
        fields[key] = json.loads(value)
    return fields


def test_render_markdown_frontmatter_round_trips_fields():
    fields = parse_frontmatter(render_markdown(make_item(tags=("sqlite", "db"))))
    assert fields["id"] == "wikipedia:en:SQLite"
    assert fields["source"] == "wikipedia"
    assert fields["url"] == "https://en.wikipedia.org/wiki/SQLite"
    assert fields["title"] == "SQLite"
    assert fields["saved_at"] == "2026-06-12T00:00:00+00:00"
    assert fields["tags"] == ["sqlite", "db"]
    assert fields["content_hash"] == "sha256:abc"
    assert fields["provenance"]["adapter"] == "wikipedia"


def test_render_markdown_omits_empty_fields():
    fields = parse_frontmatter(render_markdown(make_item(author=None, tags=())))
    assert "author" not in fields
    assert "tags" not in fields
    assert "category" not in fields


def test_render_markdown_body_sections():
    markdown = render_markdown(make_item())
    body = markdown.split("---\n")[2]
    assert "# SQLite" in body
    assert "## Summary" in body
    assert "SQLite is a database engine." in body
    assert "## Extracted Content" in body
    assert "== History ==" in body
    assert "## Links" in body
    assert "- Source: https://en.wikipedia.org/wiki/SQLite" in body


def test_render_markdown_shows_canonical_link_only_when_different():
    same = render_markdown(make_item())
    assert "- Canonical:" not in same

    different = render_markdown(
        make_item(url="https://en.wikipedia.org/wiki/Sqlite")
    )
    assert "- Canonical: https://en.wikipedia.org/wiki/SQLite" in different


def test_render_markdown_lists_item_links_in_links_section():
    markdown = render_markdown(
        make_item(links=("https://sqlite.org/fts5.html", "https://example.com/post"))
    )
    body = markdown.split("---\n")[2]
    links_section = body.split("## Links")[1]
    assert "- Source: https://en.wikipedia.org/wiki/SQLite" in links_section
    assert "- https://sqlite.org/fts5.html" in links_section
    assert "- https://example.com/post" in links_section


def test_render_markdown_media_round_trips_in_frontmatter():
    media = ({"type": "photo", "url": "https://pbs.twimg.com/media/abc.png"},)
    fields = parse_frontmatter(render_markdown(make_item(media=media)))
    assert fields["media"] == [{"type": "photo", "url": "https://pbs.twimg.com/media/abc.png"}]


def test_render_markdown_omits_empty_links_and_media():
    markdown = render_markdown(make_item(links=(), media=()))
    assert "media" not in parse_frontmatter(markdown)
    links_section = markdown.split("## Links")[1]
    assert links_section.strip().splitlines() == ["- Source: https://en.wikipedia.org/wiki/SQLite"]


@pytest.fixture
def library(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    paths = get_paths()
    paths.root.mkdir(parents=True)
    return paths


def test_write_scroll_creates_file_and_advances_stage(library):
    rendered = write_scroll(library, make_item())
    assert rendered.markdown_path == "scrolls/wikipedia/sqlite.md"
    assert rendered.stage == "rendered"
    target = library.root / rendered.markdown_path
    assert target.read_text(encoding="utf-8") == render_markdown(rendered)


def test_write_scroll_reuses_stored_path_even_when_title_changes(library):
    first = write_scroll(library, make_item())
    again = write_scroll(library, dataclasses.replace(first, title="SQLite 3"))
    assert again.markdown_path == first.markdown_path
    target = library.root / again.markdown_path
    assert "# SQLite 3" in target.read_text(encoding="utf-8")


def test_write_scroll_disambiguates_slug_collisions(library):
    first = write_scroll(library, make_item())
    other = make_item(id="wikipedia:simple:SQLite", source_id="simple:SQLite")
    second = write_scroll(library, other)
    assert second.markdown_path != first.markdown_path
    assert second.markdown_path.startswith("scrolls/wikipedia/sqlite-")
    assert (library.root / first.markdown_path).exists()
    assert (library.root / second.markdown_path).exists()


def test_write_scroll_slug_falls_back_to_id_when_title_unusable(library):
    rendered = write_scroll(library, make_item(title=None))
    assert rendered.markdown_path == "scrolls/wikipedia/wikipedia-en-sqlite.md"
