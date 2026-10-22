"""Captured PDF documents read into the scroll (ADR 0114, issue #10).

A PDF held as a media file of another item — a Wikipedia article's attached
report, say — used to sit in `media/` with its text unread. `scrolls media`
now reads it through the same pypdf seam the `pdf` and `arxiv` adapters use,
records the text on the media ref, and the scroll renders it under
`## Documents`. The three states stay distinguishable, per the completeness
contract: text read, read but nothing extractable, and not yet read.
"""

import json
from dataclasses import replace

import pypdf
import pytest

import scrolls.media as media
from pdf_fixtures import make_pdf
from scrolls.cli import main
from scrolls.items import ScrollItem, get_item, insert_item
from scrolls.media import capture_media, has_pending_document_text
from scrolls.paths import get_paths
from scrolls.render import render_markdown

REPORT_TEXT = "The station reported three anomalies before the shutdown."
REPORT = make_pdf(REPORT_TEXT)
REPORT_URL = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Station_report.pdf"
METHOD = f"pypdf-{pypdf.__version__}"


def _as_download(fake):
    """Adapt a `url -> bytes` fake to the `(payload, size)` download seam."""

    def download(url, *, max_bytes=None):
        payload = fake(url)
        return payload, len(payload)

    return download


@pytest.fixture
def paths(tmp_path):
    p = get_paths(tmp_path / "home")
    p.root.mkdir(parents=True)
    return p


def make_item(**overrides):
    base = dict(
        id="wikipedia:en:Station",
        source="wikipedia",
        source_id="en:Station",
        url="https://en.wikipedia.org/wiki/Station",
        saved_at="2026-08-19T08:00:00+00:00",
        title="Station",
        extracted_text="Station is a research outpost.",
        media=({"type": "pdf", "url": REPORT_URL},),
        provenance={"adapter": "wikipedia", "extraction_method": "mediawiki-extracts"},
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def _held(paths, item, payload=REPORT):
    """The item with its PDF already captured to disk, text never read."""
    relpath = "media/wikipedia/station-1.pdf"
    (paths.root / relpath).parent.mkdir(parents=True, exist_ok=True)
    (paths.root / relpath).write_bytes(payload)
    ref = {**item.media[0], "path": relpath}
    return replace(item, media=(ref,))


def test_capturing_a_pdf_reads_its_text_onto_the_ref(paths, monkeypatch):
    monkeypatch.setattr(media, "_download", _as_download(lambda url: REPORT))

    updated, results = capture_media(paths, make_item())

    ref = updated.media[0]
    assert ref["text"] == REPORT_TEXT
    assert ref["text_method"] == METHOD
    assert results[0]["status"] == "captured"
    assert results[0]["text"] == "extracted"


def test_a_pdf_with_no_text_layer_is_checked_and_honestly_empty(paths, monkeypatch):
    monkeypatch.setattr(media, "_download", _as_download(lambda url: b"%PDF-1.4 scan"))

    updated, results = capture_media(paths, make_item())

    ref = updated.media[0]
    assert ref["text"] is None  # read, and nothing was there
    assert ref["text_method"] == METHOD
    assert (paths.root / ref["path"]).read_bytes() == b"%PDF-1.4 scan"  # still held
    assert results[0]["text"] == "none"


def test_a_held_pdf_is_read_without_downloading_it_again(paths, monkeypatch):
    def no_network(url, *, max_bytes=None):
        raise AssertionError("a held file must not be re-downloaded")

    monkeypatch.setattr(media, "_download", no_network)
    item = _held(paths, make_item())
    assert "text" not in item.media[0]

    updated, results = capture_media(paths, item)

    assert updated.media[0]["text"] == REPORT_TEXT
    assert results == [
        {
            "url": REPORT_URL,
            "status": "skipped",
            "path": "media/wikipedia/station-1.pdf",
            "text": "extracted",
        }
    ]


def test_a_read_document_is_not_read_again(paths, monkeypatch):
    monkeypatch.setattr(media, "_download", _as_download(lambda url: REPORT))
    first, _ = capture_media(paths, make_item())

    again, results = capture_media(paths, first)

    assert again is first  # nothing changed, nothing rewritten
    assert "text" not in results[0]


def test_a_pdf_typed_by_extension_alone_is_read(paths, monkeypatch):
    monkeypatch.setattr(media, "_download", _as_download(lambda url: REPORT))
    item = make_item(media=({"type": "file", "url": REPORT_URL},))

    updated, _ = capture_media(paths, item)

    assert updated.media[0]["text"] == REPORT_TEXT


def test_non_pdf_media_is_never_read(paths, monkeypatch):
    monkeypatch.setattr(media, "_download", _as_download(lambda url: b"png-bytes"))
    item = make_item(media=({"type": "image", "url": "https://example.org/a.png"},))

    updated, results = capture_media(paths, item)

    assert "text" not in updated.media[0]
    assert "text" not in results[0]


@pytest.mark.parametrize(
    "source, method",
    [("pdf", "pypdf-5.0.0"), ("arxiv", "arxiv-api:atom+pypdf-5.0.0")],
)
def test_a_document_the_adapter_already_read_is_not_read_twice(
    paths, monkeypatch, source, method
):
    monkeypatch.setattr(media, "_download", _as_download(lambda url: REPORT))
    item = make_item(
        id=f"{source}:x",
        source=source,
        extracted_text=REPORT_TEXT,
        provenance={"adapter": source, "extraction_method": method},
    )

    updated, _ = capture_media(paths, item)

    assert "text" not in updated.media[0]
    assert not has_pending_document_text(paths, updated)
    assert "## Documents" not in render_markdown(updated)


def test_an_arxiv_paper_whose_pdf_text_failed_gets_a_second_reading(paths, monkeypatch):
    monkeypatch.setattr(media, "_download", _as_download(lambda url: REPORT))
    item = make_item(
        id="arxiv:1706.03762",
        source="arxiv",
        extracted_text=None,
        provenance={"adapter": "arxiv", "extraction_method": "arxiv-api:atom"},
    )

    updated, _ = capture_media(paths, item)

    assert updated.media[0]["text"] == REPORT_TEXT


def test_pending_document_text_means_held_and_never_read(paths, monkeypatch):
    assert not has_pending_document_text(paths, make_item())  # not held yet
    held = _held(paths, make_item())
    assert has_pending_document_text(paths, held)

    monkeypatch.setattr(media, "_download", _as_download(lambda url: REPORT))
    read, _ = capture_media(paths, held)
    assert not has_pending_document_text(paths, read)


def test_the_scroll_renders_the_document_text_and_keeps_it_out_of_frontmatter():
    ref = {
        "type": "pdf",
        "url": REPORT_URL,
        "path": "media/wikipedia/station-1.pdf",
        "text": REPORT_TEXT,
        "text_method": METHOD,
    }

    scroll = render_markdown(make_item(media=(ref,)))

    frontmatter, body = scroll.split("\n---\n", 1)
    assert REPORT_TEXT not in frontmatter
    assert '"text_method"' in frontmatter
    assert "## Documents\n\n### Station_report.pdf\n\n" + REPORT_TEXT in body
    assert body.index("## Extracted Content") < body.index("## Documents")
    assert body.index("## Documents") < body.index("## Links")


def test_the_scroll_says_when_a_held_document_had_no_text():
    ref = {
        "type": "pdf",
        "url": REPORT_URL,
        "path": "media/wikipedia/station-1.pdf",
        "text": None,
        "text_method": METHOD,
    }

    body = render_markdown(make_item(media=(ref,)))

    assert "### Station_report.pdf" in body
    assert "_No extractable text: the PDF is held at `media/wikipedia/station-1.pdf`" in body


def test_the_scroll_says_when_a_held_document_has_not_been_read():
    ref = {"type": "pdf", "url": REPORT_URL, "path": "media/wikipedia/station-1.pdf"}

    body = render_markdown(make_item(media=(ref,)))

    assert "_Not read yet: run `scrolls media` to read the held PDF" in body


def test_a_document_that_is_not_held_is_left_to_the_frontmatter():
    declined = {"type": "pdf", "url": REPORT_URL, "oversize": 1000, "bytes": 5000}

    assert "## Documents" not in render_markdown(make_item(media=(declined,)))
    assert "## Documents" not in render_markdown(make_item())


def test_scrolls_media_reads_held_documents_and_rerenders_the_scroll(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "home"))
    paths = get_paths()
    main(["init"])
    capsys.readouterr()
    insert_item(paths.db_path, _held(paths, make_item()))
    main(["md"])
    capsys.readouterr()

    def no_network(url, *, max_bytes=None):
        raise AssertionError("a held file must not be re-downloaded")

    monkeypatch.setattr(media, "_download", no_network)
    assert main(["media"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["extracted"] == 1
    assert payload["results"] == [
        {
            "id": "wikipedia:en:Station",
            "status": "extracted",
            "documents": [{"path": "media/wikipedia/station-1.pdf", "text": "extracted"}],
        }
    ]
    stored = get_item(paths.db_path, "wikipedia:en:Station")
    assert stored.media[0]["text"] == REPORT_TEXT
    scroll = (paths.root / stored.markdown_path).read_text(encoding="utf-8")
    assert REPORT_TEXT in scroll.split("## Documents", 1)[1]


# --- review round 1: refresh survival and isolated read failures -------------


def _read_ref(**extra):
    return {
        "type": "pdf",
        "url": REPORT_URL,
        "path": "media/wikipedia/station-1.pdf",
        "text": REPORT_TEXT,
        "text_method": METHOD,
        **extra,
    }


def test_a_refetch_keeps_what_scrolls_media_learned_about_each_ref():
    held = make_item(media=(_read_ref(), {"type": "image", "url": "https://u/x.png",
                                          "oversize": 10, "bytes": 99}))
    fresh = make_item(
        title="Station (revised)",
        media=(
            {"type": "pdf", "url": REPORT_URL},  # the same file, rebuilt from scratch
            {"type": "image", "url": "https://u/x.png"},
            {"type": "image", "url": "https://u/new.png"},  # new since last fetch
        ),
    )

    kept = media.carry_capture_state(held, fresh)

    assert kept.title == "Station (revised)"  # the fetch itself still wins
    assert kept.media[0] == _read_ref()
    assert list(kept.media[0])[:2] == ["type", "url"]  # adapter keys first
    assert kept.media[1] == {"type": "image", "url": "https://u/x.png",
                             "oversize": 10, "bytes": 99}
    assert kept.media[2] == {"type": "image", "url": "https://u/new.png"}


def test_a_refetch_with_nothing_to_carry_returns_the_fetch_unchanged():
    fresh = make_item()

    assert media.carry_capture_state(make_item(), fresh) is fresh


@pytest.mark.parametrize("command", ["fetch", "ingest"])
def test_scrolls_fetch_and_ingest_keep_the_reading_across_a_refresh(
    tmp_path, monkeypatch, capsys, command
):
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "home"))
    from scrolls.sources import FETCH_ADAPTERS

    paths = get_paths()
    main(["init"])
    insert_item(paths.db_path, make_item(media=(_read_ref(),)))
    capsys.readouterr()

    def refetch(item):  # what wikipedia.fetch_item does: fresh refs, no state
        return replace(make_item(), media=({"type": "pdf", "url": REPORT_URL},))

    monkeypatch.setitem(FETCH_ADAPTERS, "wikipedia", refetch)
    target = "wikipedia:en:Station" if command == "fetch" else "https://en.wikipedia.org/wiki/Station"
    assert main([command, target]) == 0
    capsys.readouterr()

    stored = get_item(paths.db_path, "wikipedia:en:Station")
    assert stored.media[0]["path"] == "media/wikipedia/station-1.pdf"
    assert stored.media[0]["text"] == REPORT_TEXT


def test_an_unreadable_held_pdf_fails_its_ref_and_not_the_others(paths, monkeypatch):
    item = _held(paths, make_item())
    second = {"type": "pdf", "url": "https://u.example/Annex.pdf",
              "path": "media/wikipedia/station-2.pdf"}
    (paths.root / second["path"]).write_bytes(REPORT)
    item = replace(item, media=(item.media[0], second))
    unreadable = paths.root / item.media[0]["path"]
    real_read_bytes = type(unreadable).read_bytes

    def read_bytes(self):
        if self == unreadable:
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_bytes(self)

    monkeypatch.setattr(type(unreadable), "read_bytes", read_bytes)

    updated, results = capture_media(paths, item)

    assert results[0]["status"] == "failed"
    assert "Permission denied" in results[0]["error"]
    assert "text" not in updated.media[0]  # still unread, so a later run retries
    assert updated.media[1]["text"] == REPORT_TEXT
