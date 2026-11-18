"""Malformed primary API envelopes are per-item failures, never tracebacks."""

import pytest

from scrolls.items import ScrollItem, make_item_id
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.detect import detect_source


@pytest.mark.parametrize("url", [
    "https://github.com/octocat/Hello-World",
    "https://gitlab.com/gitlab-org/gitlab",
    "https://gist.github.com/octocat/0123456789abcdef",
    "https://en.wikipedia.org/wiki/SQLite",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
])
@pytest.mark.parametrize("payload", [None, [], "upstream error"])
def test_non_object_primary_response_is_fetch_error(url, payload):
    detected = detect_source(url)
    item = ScrollItem(id=make_item_id(detected.source, detected.source_id, url),
                      source=detected.source, source_id=detected.source_id,
                      url=url, saved_at="2026-01-01T00:00:00Z")
    with pytest.raises(FetchError):
        FETCH_ADAPTERS[item.source](item, get_json=lambda _: payload)
