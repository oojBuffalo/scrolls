"""Tests for URL normalization at item registration (ADR 0023).

`normalize_url` is the identity gate for the URL-hash half of
`make_item_id`: two spellings of the same resource should collapse
before hashing, but nothing meaningful may change — a dropped param
that mattered would silently merge different pages, which is worse
than the duplicate it prevents. Hence the asymmetry below: known
tracking names go, everything else stays byte-identical.
"""

from scrolls.sources.urls import body_edge_links, normalize_url, scan_urls


def test_strips_utm_params():
    assert (
        normalize_url(
            "https://blog.example.com/post"
            "?utm_source=newsletter&utm_medium=email&utm_campaign=launch"
        )
        == "https://blog.example.com/post"
    )


def test_strips_known_click_ids():
    assert (
        normalize_url("https://blog.example.com/post?fbclid=IwAR0abc&gclid=xyz")
        == "https://blog.example.com/post"
    )


def test_keeps_meaningful_params_in_order_and_encoding():
    url = "https://example.com/search?q=a%20b&page=2&v=abc"
    assert normalize_url(url) == url


def test_drops_tracking_params_mixed_with_kept_ones():
    assert (
        normalize_url("https://example.com/post?id=42&utm_source=feed&page=3")
        == "https://example.com/post?id=42&page=3"
    )


def test_tracking_param_match_is_case_insensitive():
    assert (
        normalize_url("https://example.com/p?UTM_Source=x&FBCLID=y")
        == "https://example.com/p"
    )


def test_ambiguous_param_names_are_kept():
    # `ref` is a branch on GitHub and a section anchor on many sites;
    # `si`/`source` are meaningful often enough that dropping them
    # could merge genuinely different pages.
    url = "https://example.com/post?ref=sidebar&source=rss&si=42"
    assert normalize_url(url) == url


def test_lowercases_scheme_and_host_only():
    assert (
        normalize_url("HTTPS://Example.COM/Mixed/Case?Q=Keep")
        == "https://example.com/Mixed/Case?Q=Keep"
    )


def test_drops_default_port_keeps_custom():
    assert normalize_url("https://example.com:443/post") == "https://example.com/post"
    assert normalize_url("http://example.com:80/post") == "http://example.com/post"
    assert (
        normalize_url("http://example.com:8080/post")
        == "http://example.com:8080/post"
    )


def test_drops_fragment():
    assert normalize_url("https://example.com/post#section-2") == "https://example.com/post"


def test_empty_path_becomes_slash():
    assert normalize_url("https://example.com") == "https://example.com/"
    assert normalize_url("https://example.com?a=1") == "https://example.com/?a=1"


def test_query_emptied_by_stripping_loses_its_question_mark():
    assert normalize_url("https://example.com/post?utm_source=x") == "https://example.com/post"


def test_blank_and_bare_params_survive():
    assert normalize_url("https://example.com/post?a=&b") == "https://example.com/post?a=&b"


def test_non_http_input_passes_through_stripped():
    assert normalize_url("  not-a-url  ") == "not-a-url"
    assert normalize_url("ftp://example.com/file") == "ftp://example.com/file"


def test_normalization_is_idempotent():
    once = normalize_url("HTTPS://Example.com:443/post?utm_source=x&page=2#top")
    assert normalize_url(once) == once


# scan_urls / body_edge_links — the body-link grammar shared by the thread and
# Fediverse adapters (ADR 0094).


def test_scan_urls_finds_http_and_https_in_order():
    text = "see https://a.example/x and http://b.example/y for more"
    assert scan_urls(text) == ["https://a.example/x", "http://b.example/y"]


def test_scan_urls_trims_trailing_sentence_and_markdown_punctuation():
    assert scan_urls("read https://a.example/doc.") == ["https://a.example/doc"]
    # the closing `)` of a `[label](url)` link and a wrapping paren both trim
    assert scan_urls("[docs](https://a.example/p)") == ["https://a.example/p"]
    assert scan_urls("(see https://a.example/p)") == ["https://a.example/p"]


def test_scan_urls_stops_at_whitespace_and_angle_brackets():
    assert scan_urls("a <https://a.example/p> b") == ["https://a.example/p"]


def test_scan_urls_keeps_duplicates_and_does_not_dedupe():
    text = "https://a.example/p then again https://a.example/p"
    assert scan_urls(text) == ["https://a.example/p", "https://a.example/p"]


def test_scan_urls_ignores_non_string_and_textless_input():
    assert scan_urls(None) == []
    assert scan_urls(42) == []
    assert scan_urls("no links here") == []


def test_body_edge_links_leads_with_the_seed_then_body_urls():
    out = body_edge_links(
        "https://github.com/o/r",
        "https://github.com/o/r/issues/5",
        "compare https://github.com/o/r/issues/3 and https://docs.example/g",
    )
    assert out == (
        "https://github.com/o/r",
        "https://github.com/o/r/issues/3",
        "https://docs.example/g",
    )


def test_body_edge_links_excludes_the_self_url_and_dedupes_against_the_seed():
    out = body_edge_links(
        "https://github.com/o/r",
        "https://github.com/o/r/issues/5",
        # the thread links to itself and back to its own repo — both dropped
        "self https://github.com/o/r/issues/5 repo https://github.com/o/r end",
    )
    assert out == ("https://github.com/o/r",)


def test_body_edge_links_dedupes_repeated_body_urls():
    out = body_edge_links(
        "https://github.com/o/r",
        "",
        "https://x.example/a https://x.example/a https://x.example/b",
    )
    assert out == (
        "https://github.com/o/r",
        "https://x.example/a",
        "https://x.example/b",
    )
