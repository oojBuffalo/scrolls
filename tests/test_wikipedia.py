"""Tests for the Wikipedia fetch adapter (IDEAS.md §6, ADR 0002)."""

import hashlib
import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.wikipedia import fetch_item

EXTRACT = (
    "SQLite is a database engine written in the C programming language.\n"
    "It is not a standalone app.\n"
    "\n"
    "\n"
    "== History ==\n"
    "D. Richard Hipp designed SQLite in the spring of 2000.\n"
    "\n"
    "\n"
    "== Features ==\n"
    "SQLite implements most of the SQL-92 standard.\n"
)


def make_item(**overrides):
    base = dict(
        id="wikipedia:en:SQLite",
        source="wikipedia",
        source_id="en:SQLite",
        url="https://en.wikipedia.org/wiki/SQLite",
        saved_at="2026-06-12T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def make_payload(**page_overrides):
    page = {
        "pageid": 25387,
        "title": "SQLite",
        "fullurl": "https://en.wikipedia.org/wiki/SQLite",
        "canonicalurl": "https://en.wikipedia.org/wiki/SQLite",
        "extract": EXTRACT,
    }
    page.update(page_overrides)
    return {"query": {"pages": [page]}}


def test_fetch_item_normalizes_page_onto_item():
    fetched = fetch_item(make_item(), get_json=lambda url: make_payload())

    assert fetched.title == "SQLite"
    assert fetched.canonical_url == "https://en.wikipedia.org/wiki/SQLite"
    assert fetched.extracted_text == EXTRACT
    assert fetched.summary == (
        "SQLite is a database engine written in the C programming language.\n"
        "It is not a standalone app."
    )
    assert fetched.content_hash == (
        "sha256:" + hashlib.sha256(EXTRACT.encode("utf-8")).hexdigest()
    )
    assert json.loads(fetched.raw_text)["pageid"] == 25387
    assert fetched.provenance["adapter"] == "wikipedia"
    assert fetched.provenance["extraction_method"] == "mediawiki-api:extracts"
    assert fetched.provenance["fetched_at"]  # set, exact value is clock-dependent
    assert fetched.stage == "fetched"


def test_fetch_item_preserves_identity_fields():
    item = make_item()
    fetched = fetch_item(item, get_json=lambda url: make_payload())
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url
    assert fetched.saved_at == item.saved_at


def test_fetch_item_builds_action_api_url_for_language_and_title():
    seen = {}

    def capture(url):
        # the figures request is a second call; this test is about the page one
        if "generator=images" not in url:
            seen["url"] = url
        return make_payload()

    fetch_item(make_item(source_id="de:Straße"), get_json=capture)
    assert seen["url"].startswith("https://de.wikipedia.org/w/api.php?")
    assert "titles=Stra%C3%9Fe" in seen["url"]
    assert "explaintext=1" in seen["url"]
    assert "redirects=1" in seen["url"]
    assert "prop=extracts%7Cinfo%7Ccategories" in seen["url"]
    assert "clshow=%21hidden" in seen["url"]
    assert "cllimit=max" in seen["url"]


def test_fetch_item_maps_visible_categories_to_concepts():
    payload = make_payload(
        categories=[
            {"ns": 14, "title": "Category:Database management systems"},
            {"ns": 14, "title": "Category:SQLite"},
        ]
    )
    fetched = fetch_item(make_item(), get_json=lambda url: payload)
    assert fetched.concepts == ("Database management systems", "SQLite")
    # the raw page keeps the category records for rebuilds
    assert json.loads(fetched.raw_text)["categories"][0]["title"] == (
        "Category:Database management systems"
    )


def test_fetch_item_strips_localized_category_prefixes():
    payload = make_payload(categories=[{"ns": 14, "title": "Kategorie:Datenbanken"}])
    fetched = fetch_item(make_item(source_id="de:SQLite"), get_json=lambda url: payload)
    assert fetched.concepts == ("Datenbanken",)


def test_fetch_item_without_categories_has_no_concepts():
    fetched = fetch_item(make_item(), get_json=lambda url: make_payload())
    assert fetched.concepts == ()


def test_fetch_item_splits_source_id_on_first_colon_only():
    seen = {}

    def capture(url):
        seen["url"] = url
        return make_payload()

    fetch_item(make_item(source_id="en:Category:Databases"), get_json=capture)
    assert seen["url"].startswith("https://en.wikipedia.org/w/api.php?")
    assert "titles=Category%3ADatabases" in seen["url"]


def test_fetch_item_uses_redirect_resolved_title_but_keeps_item_id():
    # detect() recorded "en:Sqlite"; the API resolves the redirect to "SQLite".
    item = make_item(id="wikipedia:en:Sqlite", source_id="en:Sqlite")
    fetched = fetch_item(item, get_json=lambda url: make_payload())
    assert fetched.title == "SQLite"
    assert fetched.id == "wikipedia:en:Sqlite"  # identity assigned at add time


def test_fetch_item_rejects_missing_page():
    payload = {"query": {"pages": [{"title": "Nope", "missing": True}]}}
    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_item(source_id="en:Nope"), get_json=lambda url: payload)


def test_fetch_item_rejects_empty_pages_payload():
    with pytest.raises(FetchError):
        fetch_item(make_item(), get_json=lambda url: {"query": {"pages": []}})


def test_fetch_item_rejects_item_without_page_identity():
    with pytest.raises(FetchError, match="page"):
        fetch_item(make_item(source_id=None), get_json=lambda url: make_payload())


def test_fetch_item_wraps_transport_errors():
    def boom(url):
        raise OSError("connection refused")

    with pytest.raises(FetchError, match="connection refused"):
        fetch_item(make_item(), get_json=boom)


def test_wikipedia_adapter_is_registered():
    assert FETCH_ADAPTERS["wikipedia"] is fetch_item


# --- link graph and media capture -------------------------------------------
#
# The reading-lists on-ramp saves articles as an agent knowledgebase, so an
# article's outbound links and its figures are content, not decoration: links
# are what `scrolls graph` turns into edges between saved articles (the
# "backlinks" of a wiki, resolved within the library), and images are what
# `scrolls media` pulls onto disk.


def images_payload(*titles_and_urls):
    """A `generator=images` response: one page per file, with its imageinfo."""
    return {
        "query": {
            "pages": [
                {"title": title, "imageinfo": [{"url": url, "mime": "image/png"}]}
                for title, url in titles_and_urls
            ]
        }
    }


def routed(page_payload, image_payload):
    """A get_json that answers the page request and the images request."""

    def get_json(url):
        return image_payload if "generator=images" in url else page_payload

    return get_json


def test_fetch_item_captures_article_links_as_wiki_urls():
    payload = make_payload(
        links=[{"ns": 0, "title": "C (programming language)"}, {"ns": 0, "title": "SQL"}]
    )
    fetched = fetch_item(make_item(), get_json=routed(payload, {}))

    assert fetched.links == (
        "https://en.wikipedia.org/wiki/C_(programming_language)",
        "https://en.wikipedia.org/wiki/SQL",
    )


def test_article_links_use_the_items_own_language():
    item = make_item(id="wikipedia:de:SQLite", source_id="de:SQLite")
    payload = make_payload(links=[{"ns": 0, "title": "Datenbank"}])
    fetched = fetch_item(item, get_json=routed(payload, {}))

    assert fetched.links == ("https://de.wikipedia.org/wiki/Datenbank",)


def test_captured_links_match_what_add_would_mint():
    """A link to a saved article must resolve to that article, not near it."""
    from scrolls.sources.detect import detect_source
    from scrolls.sources.urls import normalize_url

    payload = make_payload(links=[{"ns": 0, "title": "Public key infrastructure"}])
    fetched = fetch_item(make_item(), get_json=routed(payload, {}))

    detected = detect_source(normalize_url(fetched.links[0]))
    assert detected is not None
    assert detected.source == "wikipedia"
    assert detected.source_id == "en:Public_key_infrastructure"


def test_external_links_follow_the_article_links():
    payload = make_payload(
        links=[{"ns": 0, "title": "SQL"}],
        extlinks=[{"url": "https://sqlite.org/"}, {"url": "https://example.com/paper"}],
    )
    fetched = fetch_item(make_item(), get_json=routed(payload, {}))

    assert fetched.links == (
        "https://en.wikipedia.org/wiki/SQL",
        "https://sqlite.org/",
        "https://example.com/paper",
    )


def test_duplicate_links_collapse_keeping_first_order():
    payload = make_payload(
        links=[{"ns": 0, "title": "SQL"}, {"ns": 0, "title": "SQL"}],
        extlinks=[{"url": "https://sqlite.org/"}, {"url": "https://sqlite.org/"}],
    )
    fetched = fetch_item(make_item(), get_json=routed(payload, {}))

    assert fetched.links == ("https://en.wikipedia.org/wiki/SQL", "https://sqlite.org/")


def test_fetch_item_captures_page_images_as_media_refs():
    images = images_payload(
        ("File:Dihydrocodeine skeletal.svg", "https://upload.wikimedia.org/a/skeletal.svg")
    )
    fetched = fetch_item(make_item(), get_json=routed(make_payload(), images))

    assert fetched.media == (
        {
            "type": "image",
            "url": "https://upload.wikimedia.org/a/skeletal.svg",
            "title": "Dihydrocodeine skeletal.svg",
        },
    )


def test_interface_chrome_is_not_captured_as_article_media():
    """MediaWiki lists every file the page renders, icons included."""
    images = images_payload(
        ("File:Commons-logo.svg", "https://upload.wikimedia.org/a/Commons-logo.svg"),
        ("File:Edit-clear.svg", "https://upload.wikimedia.org/a/Edit-clear.svg"),
        ("File:Question book-new.svg", "https://upload.wikimedia.org/a/Question.svg"),
        ("File:X mark.svg", "https://upload.wikimedia.org/a/X_mark.svg"),
        ("File:Yes check.svg", "https://upload.wikimedia.org/a/Yes_check.svg"),
        ("File:OOjs UI icon edit-ltr.svg", "https://upload.wikimedia.org/a/OOjs.svg"),
        ("File:Real diagram.png", "https://upload.wikimedia.org/a/Real_diagram.png"),
    )
    fetched = fetch_item(make_item(), get_json=routed(make_payload(), images))

    assert [ref["title"] for ref in fetched.media] == ["Real diagram.png"]


def test_an_article_with_no_figures_captures_no_media():
    fetched = fetch_item(make_item(), get_json=routed(make_payload(), {}))
    assert fetched.media == ()


def test_a_failed_image_request_never_costs_the_article():
    """Figures are a bonus; losing them must not lose 26k characters of text."""

    def get_json(url):
        if "generator=images" in url:
            raise OSError("connection reset")
        return make_payload()

    fetched = fetch_item(make_item(), get_json=get_json)

    assert fetched.extracted_text == EXTRACT
    assert fetched.media == ()


def test_a_failed_page_request_still_raises():
    def get_json(url):
        raise OSError("connection reset")

    with pytest.raises(FetchError):
        fetch_item(make_item(), get_json=get_json)


def image_page(title, url, *, width=None, thumburl=None, thumbwidth=None):
    info = {"url": url, "mime": "image/jpeg"}
    if width is not None:
        info["width"] = width
    if thumburl is not None:
        info["thumburl"] = thumburl
        info["thumbwidth"] = thumbwidth
    return {"title": title, "imageinfo": [info]}


def test_analytics_parameters_are_stripped_from_media_urls():
    """Wikimedia appends utm_* to imageinfo URLs; they belong to the API call."""
    images = {
        "query": {
            "pages": [
                image_page(
                    "File:Diagram.svg",
                    "https://upload.wikimedia.org/a/Diagram.svg"
                    "?utm_source=en.wikipedia.org&utm_campaign=imageinfo",
                )
            ]
        }
    }
    fetched = fetch_item(make_item(), get_json=routed(make_payload(), images))

    assert fetched.media[0]["url"] == "https://upload.wikimedia.org/a/Diagram.svg"


def test_an_oversized_photo_is_captured_at_its_capped_width():
    images = {
        "query": {
            "pages": [
                image_page(
                    "File:Package.jpg",
                    "https://upload.wikimedia.org/a/Package.jpg",
                    width=3857,
                    thumburl="https://upload.wikimedia.org/thumb/a/Package.jpg/1280px.jpg",
                    thumbwidth=1280,
                )
            ]
        }
    }
    fetched = fetch_item(make_item(), get_json=routed(make_payload(), images))

    ref = fetched.media[0]
    assert ref["url"] == "https://upload.wikimedia.org/thumb/a/Package.jpg/1280px.jpg"
    assert ref["original_url"] == "https://upload.wikimedia.org/a/Package.jpg"


def test_a_small_figure_is_captured_whole():
    """A vector diagram's 'thumbnail' is a bigger raster; the original wins."""
    images = {
        "query": {
            "pages": [
                image_page(
                    "File:Skeletal.svg",
                    "https://upload.wikimedia.org/a/Skeletal.svg",
                    width=460,
                    thumburl="https://upload.wikimedia.org/thumb/a/Skeletal.svg/1280px.png",
                    thumbwidth=1280,
                )
            ]
        }
    }
    fetched = fetch_item(make_item(), get_json=routed(make_payload(), images))

    assert fetched.media[0]["url"] == "https://upload.wikimedia.org/a/Skeletal.svg"
    assert "original_url" not in fetched.media[0]


def typed_page(title, url, mime):
    return {"title": title, "imageinfo": [{"url": url, "mime": mime}]}


def test_media_type_follows_the_files_mime_not_a_blanket_image():
    """Wikipedia pages carry audio and video; calling an .ogg an image is a lie."""
    images = {
        "query": {
            "pages": [
                typed_page("File:Diagram.svg", "https://u.w/a.svg", "image/svg+xml"),
                typed_page("File:Speech.ogg", "https://u.w/a.ogg", "audio/ogg"),
                typed_page("File:Launch.webm", "https://u.w/a.webm", "video/webm"),
                typed_page("File:Report.pdf", "https://u.w/a.pdf", "application/pdf"),
            ]
        }
    }
    fetched = fetch_item(make_item(), get_json=routed(make_payload(), images))

    assert [ref["type"] for ref in fetched.media] == ["image", "audio", "video", "pdf"]


@pytest.mark.parametrize(
    "name",
    [
        "Loudspeaker at the concert hall.jpg",
        "Padlock on a canal gate.jpg",
        "Symbol of the Olympic Games.jpg",
    ],
)
def test_a_figure_is_not_dropped_for_merely_resembling_an_icon(name):
    """A false drop loses real content silently — worse than an icon leaking in."""
    images = {"query": {"pages": [typed_page(f"File:{name}", "https://u.w/a.jpg", "image/jpeg")]}}
    fetched = fetch_item(make_item(), get_json=routed(make_payload(), images))

    assert [ref["title"] for ref in fetched.media] == [name]


@pytest.mark.parametrize(
    "name",
    ["Loudspeaker.svg", "Padlock-silver.svg", "Symbol support vote.svg"],
)
def test_the_icons_those_names_resemble_are_still_dropped(name):
    images = {"query": {"pages": [typed_page(f"File:{name}", "https://u.w/a.svg", "image/svg+xml")]}}
    fetched = fetch_item(make_item(), get_json=routed(make_payload(), images))

    assert fetched.media == ()


@pytest.mark.parametrize(
    "name",
    [
        "Symbol list class.svg",
        "Symbol category class.svg",
        "Symbol template class pink.svg",
    ],
)
def test_namespace_class_icons_are_chrome(name):
    """Wikipedia's own namespace badges — the shape a bare 'symbol ' match caught."""
    images = {"query": {"pages": [typed_page(f"File:{name}", "https://u.w/a.svg", "image/svg+xml")]}}
    fetched = fetch_item(make_item(), get_json=routed(make_payload(), images))

    assert fetched.media == ()


@pytest.mark.parametrize(
    "name",
    [
        "Diode symbol.svg",
        "Antenna schematic symbol.svg",
        "IEEE 315 Fundamental Items Symbols (56).svg",
        "Radiation warning symbol.svg",
    ],
)
def test_symbols_that_are_the_subject_survive(name):
    """A circuit diagram is what the article is about, not furniture around it."""
    images = {"query": {"pages": [typed_page(f"File:{name}", "https://u.w/a.svg", "image/svg+xml")]}}
    fetched = fetch_item(make_item(), get_json=routed(make_payload(), images))

    assert [ref["title"] for ref in fetched.media] == [name]
