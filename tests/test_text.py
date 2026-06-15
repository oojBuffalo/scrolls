"""The shared Markdown-body normalizer."""

from __future__ import annotations

from scrolls.sources.text import normalize_markdown


def test_normalizes_crlf_and_cr_to_lf():
    assert normalize_markdown("a\r\nb\rc") == "a\nb\nc"


def test_collapses_blank_line_runs_to_one_blank_line():
    assert normalize_markdown("a\n\n\n\nb") == "a\n\nb"


def test_keeps_a_single_blank_line_between_paragraphs():
    assert normalize_markdown("a\n\nb") == "a\n\nb"


def test_strips_surrounding_whitespace():
    assert normalize_markdown("\n\n  hello  \n\n") == "hello"


def test_crlf_blank_runs_collapse_after_line_ending_normalization():
    # \r\n\r\n\r\n is three newlines once normalized, so it collapses too.
    assert normalize_markdown("a\r\n\r\n\r\nb") == "a\n\nb"


def test_empty_input_yields_empty_string():
    assert normalize_markdown("") == ""
    assert normalize_markdown("\n\n\n") == ""
