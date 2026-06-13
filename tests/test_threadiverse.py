"""Tests for the link-aggregator fetch dispatcher (ADR 0052, 0053).

A `/post/<digits>` URL is detected as the `lemmy` source, but which backend
serves it — Lemmy's `/api/v3` or PieFed's `/api/alpha` — is resolved at fetch
time: Lemmy first, PieFed fallback (PieFed shares the identical URL shape, so
detection can't tell them apart). The two implementation adapters are injected so
the dispatch logic is exercised without the network (ADR 0001).
"""

from dataclasses import replace

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.threadiverse import fetch_item


def make_item():
    return ScrollItem(
        id="lemmy:piefed.social/1600132",
        source="lemmy",
        source_id="piefed.social/1600132",
        url="https://piefed.social/post/1600132",
        saved_at="2026-06-13T00:00:00+00:00",
    )


def stub(label, error=None):
    """A fake implementation fetch: tags the item with `label`, or raises."""
    calls = []

    def fetch(item):
        calls.append(item)
        if error is not None:
            raise FetchError(error)
        return replace(item, title=label, stage="fetched")

    fetch.calls = calls
    return fetch


def test_lemmy_hit_never_touches_piefed():
    lemmy = stub("from lemmy")
    piefed = stub("from piefed")
    fetched = fetch_item(make_item(), lemmy_fetch=lemmy, piefed_fetch=piefed)
    assert fetched.title == "from lemmy"
    assert len(lemmy.calls) == 1
    assert piefed.calls == []  # Lemmy answered, so PieFed is never asked


def test_lemmy_miss_falls_back_to_piefed():
    # a PieFed instance 404s the Lemmy /api/v3 call (it serves only /api/alpha)
    lemmy = stub("", error="lemmy API request failed: HTTP Error 404")
    piefed = stub("from piefed")
    fetched = fetch_item(make_item(), lemmy_fetch=lemmy, piefed_fetch=piefed)
    assert fetched.title == "from piefed"
    assert len(lemmy.calls) == 1
    assert len(piefed.calls) == 1


def test_neither_backend_serves_the_post_raises_naming_both():
    lemmy = stub("", error="lemmy post not found")
    piefed = stub("", error="piefed post not found")
    with pytest.raises(FetchError) as excinfo:
        fetch_item(make_item(), lemmy_fetch=lemmy, piefed_fetch=piefed)
    message = str(excinfo.value)
    assert "Lemmy" in message and "PieFed" in message
    assert "piefed.social/1600132" in message


def test_real_dispatcher_is_registered_for_lemmy():
    assert FETCH_ADAPTERS["lemmy"] is fetch_item
