"""Tests for the generic PDF fetch adapter (ADR 0013).

The byte transport is faked; tests cover document-info metadata mapping,
the filename-title fallback, the metadata-only degradation for textless
PDFs, and the hard failures for broken downloads and non-PDF payloads.
"""

import hashlib

import pytest

from pdf_fixtures import make_pdf
from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.pdf import extract_text, fetch_item

PDF_TEXT = "Grouped-query attention trades model capacity for decode speed."
INFO = {
    "Title": "GQA Technical Report",
    "Author": "A. Researcher",
    "Subject": "A short report on grouped-query attention.",
    "CreationDate": "D:20240315120000Z",
}
PDF = make_pdf(PDF_TEXT, INFO)


def make_item(**overrides):
    base = dict(
        id="pdf:eb2e6487c357",
        source="pdf",
        source_id=None,
        url="https://example.com/papers/attention-is-all-you-need.pdf",
        saved_at="2026-06-12T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fetch(item=None, pdf=PDF):
    def get_bytes(url):
        if isinstance(pdf, Exception):
            raise pdf
        return pdf

    return fetch_item(item or make_item(), get_bytes=get_bytes)


def test_fetch_item_normalizes_document_onto_item():
    fetched = fetch()

    assert fetched.title == "GQA Technical Report"
    assert fetched.author == "A. Researcher"
    assert fetched.published_at == "2024-03-15T12:00:00+00:00"
    assert fetched.summary == "A short report on grouped-query attention."
    assert PDF_TEXT in fetched.extracted_text
    assert fetched.canonical_url == fetched.url
    assert fetched.media == ({"type": "pdf", "url": fetched.url},)
    assert fetched.provenance["adapter"] == "pdf"
    assert fetched.provenance["extraction_method"].startswith("pypdf-")
    assert fetched.stage == "fetched"


def test_fetch_item_content_hash_covers_the_exact_bytes():
    fetched = fetch()
    assert fetched.content_hash == "sha256:" + hashlib.sha256(PDF).hexdigest()


def test_fetch_item_keeps_no_raw_text():
    # the binary itself is the raw record; `scrolls media` captures it and
    # the content hash pins it — a TEXT column is the wrong home (ADR 0013)
    assert fetch().raw_text is None


def test_fetch_item_title_falls_back_to_the_filename():
    fetched = fetch(pdf=make_pdf(PDF_TEXT))
    assert fetched.title == "attention is all you need"


def test_fetch_item_filename_title_decodes_percent_escapes():
    item = make_item(url="https://example.com/files/Deep%20Learning_notes-v2.pdf")
    fetched = fetch(item, pdf=make_pdf(PDF_TEXT))
    assert fetched.title == "Deep Learning notes v2"


def test_fetch_item_blank_metadata_falls_back_to_the_filename():
    fetched = fetch(pdf=make_pdf(PDF_TEXT, {"Title": "   "}))
    assert fetched.title == "attention is all you need"


def test_fetch_item_without_subject_has_no_summary():
    fetched = fetch(pdf=make_pdf(PDF_TEXT, {"Title": "GQA Technical Report"}))
    assert fetched.summary is None


def test_fetch_item_textless_pdf_degrades_to_metadata_only():
    fetched = fetch(pdf=make_pdf("", INFO))

    assert fetched.extracted_text is None
    assert fetched.title == "GQA Technical Report"
    assert fetched.media == ({"type": "pdf", "url": fetched.url},)
    assert fetched.stage == "fetched"


def test_fetch_item_download_failure_raises():
    with pytest.raises(FetchError, match="pdf download failed"):
        fetch(pdf=OSError("connection refused"))


def test_fetch_item_non_pdf_payload_raises():
    # an HTML error page or paywall stub must not become a scroll
    with pytest.raises(FetchError, match="not a readable PDF"):
        fetch(pdf=b"<html>404 Not Found</html>")


def test_fetch_item_preserves_identity_fields():
    item = make_item()
    fetched = fetch(item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url
    assert fetched.saved_at == item.saved_at


def test_pdf_adapter_is_registered():
    assert FETCH_ADAPTERS["pdf"] is fetch_item


def test_extract_text_returns_none_for_junk():
    assert extract_text(b"this is not a pdf") is None


def test_extract_text_reads_page_text():
    assert extract_text(make_pdf("hello scrolls")) == "hello scrolls"
