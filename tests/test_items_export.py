"""Lossless JSONL item export/import (ADR 0082).

`dump_items_export` serializes items to JSON Lines and `load_items_export`
reads them back; the contract is a byte-faithful round-trip at the
ScrollItem level — unlike the bookmarks/OPML exports, which carry only a
spine, this carries every field. The exporter is Scrolls itself, so the
round-trip is provable here (the external-importer gap ADR 0077/0079 named).
"""

from __future__ import annotations

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.items_export import (
    ItemsSourceError,
    dump_items_export,
    load_items_export,
)


def _rich_item(**overrides) -> ScrollItem:
    """An item with every field populated, so the round-trip is exercised whole."""
    base = dict(
        id="arxiv:1706.03762",
        source="arxiv",
        url="https://arxiv.org/abs/1706.03762",
        saved_at="2026-06-12T08:00:00+00:00",
        source_id="1706.03762",
        canonical_url="http://arxiv.org/abs/1706.03762v7",
        title="Attention Is All You Need",
        author="Ashish Vaswani et al.",
        published_at="2017-06-12T17:57:34+00:00",
        raw_text="<the raw Atom entry>",
        extracted_text="The dominant sequence transduction models…",
        summary="We propose the Transformer.",
        category="paper",
        domain="machine learning",
        tags=("cs.CL", "cs.LG"),
        concepts=("Attention", "Transformer"),
        links=("https://doi.org/10.5555/3295222",),
        media=(
            {
                "type": "pdf",
                "url": "https://arxiv.org/pdf/1706.03762",
                "path": "media/arxiv/1706-03762-1.pdf",
            },
        ),
        content_hash="sha256:6d2e1066",
        markdown_path="scrolls/arxiv/attention-is-all-you-need.md",
        provenance={
            "adapter": "arxiv",
            "fetched_at": "2026-06-12T08:00:05+00:00",
            "extraction_method": "arxiv-atom+pypdf",
        },
        stage="rendered",
    )
    base.update(overrides)
    return ScrollItem(**base)


def test_dump_emits_one_json_object_per_line():
    items = [
        _rich_item(),
        ScrollItem(
            id="web:abc123def456",
            source="web",
            url="https://example.com/post",
            saved_at="2026-06-13T00:00:00+00:00",
        ),
    ]
    out = dump_items_export(items)
    lines = out.splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["id"] == "arxiv:1706.03762"
    assert first["tags"] == ["cs.CL", "cs.LG"]  # tuples serialize as JSON arrays
    # a minimal item still carries every key (lossless shape), defaults included
    second = json.loads(lines[1])
    assert second["title"] is None and second["tags"] == [] and second["stage"] == "detected"


def test_dump_then_load_is_a_lossless_round_trip(tmp_path):
    items = [
        _rich_item(),
        _rich_item(id="crossref:10.5555/3295222", source="crossref"),
    ]
    path = tmp_path / "library.jsonl"
    path.write_text(dump_items_export(items), encoding="utf-8")

    loaded, stats = load_items_export(path)
    # every field survives, list fields come back as tuples (not lists)
    assert loaded == items
    assert isinstance(loaded[0].tags, tuple) and isinstance(loaded[0].media, tuple)
    assert loaded[0].provenance == items[0].provenance
    assert stats == {"items": 2}


def test_dump_empty_is_an_empty_document():
    assert dump_items_export([]) == ""


def test_load_empty_document_yields_no_items(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    loaded, stats = load_items_export(path)
    assert loaded == [] and stats == {"items": 0}


def test_load_skips_blank_lines(tmp_path):
    # a trailing newline or hand-editing leaves blank lines; they are not items
    path = tmp_path / "library.jsonl"
    line = json.dumps({"id": "web:x", "source": "web", "url": "u", "saved_at": "t"})
    path.write_text(f"\n{line}\n\n", encoding="utf-8")
    loaded, stats = load_items_export(path)
    assert stats == {"items": 1} and loaded[0].id == "web:x"


def test_load_missing_file_raises():
    with pytest.raises(ItemsSourceError):
        load_items_export(__import__("pathlib").Path("/no/such/library.jsonl"))


def test_load_malformed_json_line_raises_naming_the_line(tmp_path):
    path = tmp_path / "bad.jsonl"
    good = json.dumps({"id": "web:x", "source": "web", "url": "u", "saved_at": "t"})
    path.write_text(f"{good}\nnot json at all\n", encoding="utf-8")
    with pytest.raises(ItemsSourceError, match="line 2"):
        load_items_export(path)


def test_load_non_object_line_raises(tmp_path):
    path = tmp_path / "array.jsonl"
    path.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(ItemsSourceError, match="line 1"):
        load_items_export(path)


def test_load_line_missing_required_field_raises(tmp_path):
    # a Scrolls export is internally consistent; a record without identity is
    # corruption, and silently dropping it from a *backup* would lose data
    path = tmp_path / "incomplete.jsonl"
    path.write_text(json.dumps({"source": "web", "url": "u"}) + "\n", encoding="utf-8")
    with pytest.raises(ItemsSourceError, match="id"):
        load_items_export(path)


def test_load_ignores_unknown_keys(tmp_path):
    # forward-compat: an export written by a newer schema (an extra field) still
    # loads under an older reader, dropping the field it doesn't know
    path = tmp_path / "future.jsonl"
    record = {
        "id": "web:x",
        "source": "web",
        "url": "https://example.com",
        "saved_at": "2026-06-13T00:00:00+00:00",
        "future_field": "from a newer scrolls",
    }
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    loaded, _ = load_items_export(path)
    assert loaded[0].id == "web:x"
    assert not hasattr(loaded[0], "future_field")
