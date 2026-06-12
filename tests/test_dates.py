"""Tests for the shared `published_at` normalizer (ADR 0024).

Every writer of `published_at` — feed sync, the web/github/arxiv/pdf
adapters, the Field Theory import — funnels source date dialects
through `to_utc_iso`, so the field is one vocabulary: UTC ISO 8601 at
seconds precision, or an honest None.
"""

from scrolls.dates import to_utc_iso


def test_rfc3339_z_suffix_becomes_utc_offset():
    assert to_utc_iso("2026-05-01T12:00:00Z") == "2026-05-01T12:00:00+00:00"


def test_non_utc_offset_is_converted():
    assert to_utc_iso("2026-05-01T12:00:00+05:00") == "2026-05-01T07:00:00+00:00"


def test_naive_datetime_is_assumed_utc():
    assert to_utc_iso("2026-05-01T12:00:00") == "2026-05-01T12:00:00+00:00"


def test_date_only_becomes_midnight_utc():
    # trafilatura's dialect; midnight is invented precision, but one
    # shape for the whole field beats two parsers in every consumer
    assert to_utc_iso("2025-03-01") == "2025-03-01T00:00:00+00:00"


def test_rfc822_pubdate_is_understood():
    assert to_utc_iso("Tue, 02 Jun 2026 10:00:00 GMT") == "2026-06-02T10:00:00+00:00"


def test_subsecond_precision_is_trimmed():
    assert to_utc_iso("2026-05-01T12:00:00.123456Z") == "2026-05-01T12:00:00+00:00"


def test_garbage_is_an_honest_none():
    assert to_utc_iso("circa 2020") is None


def test_absent_input_is_none():
    assert to_utc_iso(None) is None
    assert to_utc_iso("   ") is None
