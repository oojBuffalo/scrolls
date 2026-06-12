"""Tests for URL normalization at item registration (ADR 0023).

`normalize_url` is the identity gate for the URL-hash half of
`make_item_id`: two spellings of the same resource should collapse
before hashing, but nothing meaningful may change — a dropped param
that mattered would silently merge different pages, which is worse
than the duplicate it prevents. Hence the asymmetry below: known
tracking names go, everything else stays byte-identical.
"""

from scrolls.sources.urls import normalize_url


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
