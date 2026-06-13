"""Tests for the pipeline engine's item-ref resolution (ADR 0027/0028).

`resolve_item_id` turns an id-or-URL ref into the item id `scrolls add`
would mint — the same normalize → detect → mint chain as
`register_url` — so the URL that saved an item is a valid handle for
every command that takes an item id.
"""

import pytest

from scrolls.items import make_item_id
from scrolls.pipeline import resolve_item_id


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
