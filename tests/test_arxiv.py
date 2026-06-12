"""Tests for the arXiv fetch adapter (IDEAS.md §6, ADR 0008, ADR 0010).

The Atom and PDF transports are faked; tests cover the
abstract-as-summary semantics, PDF full-text extraction with its
degradation contract, and error entries offline.
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.arxiv import fetch_item


def make_pdf(text: str) -> bytes:
    """A minimal one-page PDF carrying `text` in its content stream."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    return bytes(out)


PDF_TEXT = "Mistral 7B leverages grouped-query attention for faster inference."
PDF = make_pdf(PDF_TEXT)

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title type="html">ArXiv Query: search_query=&amp;id_list=2310.06825</title>
  <entry>
    <id>http://arxiv.org/abs/2310.06825v1</id>
    <updated>2023-10-10T17:54:02Z</updated>
    <published>2023-10-10T17:54:02Z</published>
    <title>Mistral
 7B</title>
    <summary>  We introduce Mistral 7B, a 7-billion-parameter language model.
It outperforms Llama 2 13B across all evaluated benchmarks.
</summary>
    <author><name>Albert Q. Jiang</name></author>
    <author><name>Alexandre Sablayrolles</name></author>
    <link href="http://arxiv.org/abs/2310.06825v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2310.06825v1" rel="related"
          type="application/pdf"/>
    <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="cs.CL"/>
    <category term="cs.CL"/>
    <category term="cs.AI"/>
    <category term="cs.CL"/>
  </entry>
</feed>"""

EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title type="html">ArXiv Query: search_query=&amp;id_list=2310.99999</title>
</feed>"""

ERROR_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/api/errors#incorrect_id_format_for_bogus</id>
    <title>Error</title>
    <summary>incorrect id format for bogus</summary>
  </entry>
</feed>"""


def make_item(**overrides):
    base = dict(
        id="arxiv:2310.06825",
        source="arxiv",
        source_id="2310.06825",
        url="https://arxiv.org/abs/2310.06825",
        saved_at="2026-06-12T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fetch(item=None, feed=FEED, pdf=PDF):
    def get_bytes(url):
        if isinstance(pdf, Exception):
            raise pdf
        return pdf

    return fetch_item(
        item or make_item(), get_text=lambda url: feed, get_bytes=get_bytes
    )


def test_fetch_item_normalizes_entry_onto_item():
    fetched = fetch()

    assert fetched.title == "Mistral 7B"  # whitespace collapsed
    assert fetched.author == "Albert Q. Jiang, Alexandre Sablayrolles"
    assert fetched.published_at == "2023-10-10T17:54:02Z"
    assert fetched.canonical_url == "http://arxiv.org/abs/2310.06825v1"
    assert fetched.summary == (
        "We introduce Mistral 7B, a 7-billion-parameter language model. "
        "It outperforms Llama 2 13B across all evaluated benchmarks."
    )
    assert PDF_TEXT in fetched.extracted_text  # full text from the PDF (ADR 0010)
    assert fetched.tags == ("cs.CL", "cs.AI")  # taxonomy codes, deduped
    # taxonomy display names join the concept graph (ADR 0012)
    assert fetched.concepts == ("Computation and Language", "Artificial Intelligence")
    assert fetched.media == (
        {"type": "pdf", "url": "http://arxiv.org/pdf/2310.06825v1"},
    )
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.provenance["adapter"] == "arxiv"
    assert fetched.provenance["extraction_method"].startswith("arxiv-api:atom+pypdf-")
    assert fetched.stage == "fetched"


def test_fetch_item_keeps_unknown_category_codes_out_of_concepts():
    # pre-2007 archive names like cmp-lg are valid tags but have no
    # taxonomy entry; they must not crash or pollute the concept graph
    feed = FEED.replace('term="cs.AI"', 'term="cmp-lg"')
    fetched = fetch(feed=feed)

    assert fetched.tags == ("cs.CL", "cmp-lg")
    assert fetched.concepts == ("Computation and Language",)


def test_fetch_item_merges_concept_names_shared_across_codes():
    # cs.LG and stat.ML both display as "Machine Learning" — one concept
    feed = FEED.replace('term="cs.CL"', 'term="cs.LG"').replace(
        'term="cs.AI"', 'term="stat.ML"'
    )
    fetched = fetch(feed=feed)

    assert fetched.tags == ("cs.LG", "stat.ML")
    assert fetched.concepts == ("Machine Learning",)


def test_fetch_item_downloads_the_pdf_link_over_https():
    seen = {}

    def get_bytes(url):
        seen["url"] = url
        return PDF

    fetch_item(make_item(), get_text=lambda url: FEED, get_bytes=get_bytes)
    # the feed's link is plain http; arxiv redirects to https anyway
    assert seen["url"] == "https://arxiv.org/pdf/2310.06825v1"


def test_fetch_item_content_hash_covers_the_full_text():
    with_text = fetch()
    without_text = fetch(pdf=OSError("offline"))
    assert with_text.content_hash != without_text.content_hash


def test_fetch_item_pdf_download_failure_degrades_to_abstract_only():
    fetched = fetch(pdf=OSError("connection refused"))

    assert fetched.extracted_text is None
    assert fetched.summary.startswith("We introduce Mistral 7B")
    assert fetched.provenance["extraction_method"] == "arxiv-api:atom"
    assert fetched.stage == "fetched"


def test_fetch_item_unparseable_pdf_degrades_to_abstract_only():
    fetched = fetch(pdf=b"this is not a pdf")
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "arxiv-api:atom"


def test_fetch_item_textless_pdf_degrades_to_abstract_only():
    fetched = fetch(pdf=make_pdf(""))
    assert fetched.extracted_text is None
    assert fetched.provenance["extraction_method"] == "arxiv-api:atom"


def test_fetch_item_without_pdf_link_skips_the_download():
    feed = FEED.replace(
        '<link title="pdf" href="http://arxiv.org/pdf/2310.06825v1" rel="related"\n'
        '          type="application/pdf"/>',
        "",
    )
    calls = []

    def get_bytes(url):
        calls.append(url)
        return PDF

    fetched = fetch_item(make_item(), get_text=lambda url: feed, get_bytes=get_bytes)
    assert calls == []
    assert fetched.extracted_text is None
    assert fetched.media == ()


def test_fetch_item_keeps_raw_feed_for_rebuilds():
    fetched = fetch()
    assert fetched.raw_text == FEED


def test_fetch_item_preserves_identity_fields():
    item = make_item()
    fetched = fetch(item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url
    assert fetched.saved_at == item.saved_at


def test_fetch_item_requests_the_export_api():
    seen = {}

    def capture(url):
        seen["url"] = url
        return FEED

    fetch_item(make_item(), get_text=capture, get_bytes=lambda url: PDF)
    assert seen["url"] == (
        "https://export.arxiv.org/api/query?id_list=2310.06825&max_results=1"
    )


def test_fetch_item_handles_old_style_slashed_ids():
    seen = {}

    def capture(url):
        seen["url"] = url
        return FEED

    item = make_item(id="arxiv:math/0211159", source_id="math/0211159",
                     url="https://arxiv.org/abs/math/0211159")
    fetch_item(item, get_text=capture, get_bytes=lambda url: PDF)
    assert "id_list=math%2F0211159" in seen["url"]


def test_fetch_item_without_summary_or_pdf_degrades_to_metadata_only():
    feed = FEED.replace(
        "<summary>  We introduce Mistral 7B, a 7-billion-parameter language model.\n"
        "It outperforms Llama 2 13B across all evaluated benchmarks.\n</summary>",
        "<summary> </summary>",
    )
    fetched = fetch(feed=feed, pdf=OSError("offline"))
    assert fetched.summary is None
    assert fetched.extracted_text is None
    assert fetched.title == "Mistral 7B"
    assert fetched.content_hash.startswith("sha256:")


def test_fetch_item_rejects_unknown_paper():
    with pytest.raises(FetchError, match="not found"):
        fetch(feed=EMPTY_FEED)


def test_fetch_item_rejects_api_error_entries():
    with pytest.raises(FetchError, match="incorrect id format"):
        fetch(feed=ERROR_FEED)


def test_fetch_item_rejects_item_without_paper_identity():
    with pytest.raises(FetchError, match="cannot determine arxiv paper"):
        fetch_item(make_item(source_id=None), get_text=lambda url: FEED)


def test_fetch_item_wraps_transport_errors():
    def boom(url):
        raise OSError("connection refused")

    with pytest.raises(FetchError, match="connection refused"):
        fetch_item(make_item(), get_text=boom)


def test_fetch_item_wraps_malformed_xml():
    with pytest.raises(FetchError, match="arxiv API request failed"):
        fetch(feed="this is not xml")


def test_arxiv_adapter_is_registered():
    assert FETCH_ADAPTERS["arxiv"] is fetch_item


def test_payloads_round_trip_through_json():
    fetched = fetch()
    assert json.loads(json.dumps(list(fetched.media)))[0]["type"] == "pdf"
