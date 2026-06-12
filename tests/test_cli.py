"""Tests for the `scrolls` CLI entry point."""

import json

import pytest

import scrolls.sources.wikipedia as wikipedia
import scrolls.sources.youtube as youtube
from scrolls.cli import main
from scrolls.db import SCHEMA_VERSION
from scrolls.paths import get_paths
from scrolls.items import ScrollItem, get_item, insert_item, update_item


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


def test_detect_prints_json(capsys):
    exit_code = main(["detect", "https://youtu.be/dQw4w9WgXcQ"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"source": "youtube", "source_id": "dQw4w9WgXcQ"}


def test_detect_web_fallback_has_null_source_id(capsys):
    exit_code = main(["detect", "https://example.com/post"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"source": "web", "source_id": None}


def test_detect_rejects_non_http_url(capsys):
    exit_code = main(["detect", "ftp://example.com/file"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_no_command_exits_with_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


def test_paths_prints_layout_json(scrolls_home, capsys):
    exit_code = main(["paths"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "root": str(scrolls_home),
        "items": str(scrolls_home / "items"),
        "scrolls": str(scrolls_home / "scrolls"),
        "library": str(scrolls_home / "library"),
        "media": str(scrolls_home / "media"),
        "agents": str(scrolls_home / "agents"),
        "db": str(scrolls_home / "db.sqlite"),
        "config": str(scrolls_home / "config.toml"),
    }


def test_init_creates_library_skeleton(scrolls_home, capsys):
    exit_code = main(["init"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"root": str(scrolls_home), "created": True}
    for subdir in ("items", "scrolls", "library", "media", "agents"):
        assert (scrolls_home / subdir).is_dir()
    assert (scrolls_home / "db.sqlite").is_file()
    assert (scrolls_home / "config.toml").is_file()


def test_init_is_idempotent_and_preserves_config(scrolls_home, capsys):
    main(["init"])
    config = scrolls_home / "config.toml"
    config.write_text("# user edits must survive re-init\n")
    capsys.readouterr()

    exit_code = main(["init"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"root": str(scrolls_home), "created": False}
    assert config.read_text() == "# user edits must survive re-init\n"


def test_status_before_init(scrolls_home, capsys):
    exit_code = main(["status"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "initialized": False,
        "root": str(scrolls_home),
        "schema_version": None,
    }


def test_status_after_init(scrolls_home, capsys):
    main(["init"])
    capsys.readouterr()

    exit_code = main(["status"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "initialized": True,
        "root": str(scrolls_home),
        "schema_version": SCHEMA_VERSION,
    }


def test_add_persists_detected_item(scrolls_home, capsys):
    exit_code = main(["add", "https://youtu.be/dQw4w9WgXcQ"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "id": "youtube:dQw4w9WgXcQ",
        "source": "youtube",
        "source_id": "dQw4w9WgXcQ",
        "url": "https://youtu.be/dQw4w9WgXcQ",
        "stage": "detected",
        "created": True,
    }
    # add auto-initializes the library skeleton
    assert (scrolls_home / "db.sqlite").is_file()
    assert (scrolls_home / "config.toml").is_file()


def test_add_same_video_via_other_url_form_is_deduped(scrolls_home, capsys):
    main(["add", "https://youtu.be/dQw4w9WgXcQ"])
    capsys.readouterr()

    exit_code = main(["add", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is False
    assert payload["id"] == "youtube:dQw4w9WgXcQ"
    assert payload["url"] == "https://youtu.be/dQw4w9WgXcQ"  # first record wins


def test_add_rejects_non_http_url(scrolls_home, capsys):
    exit_code = main(["add", "not-a-url"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)
    assert not scrolls_home.exists()  # no library created on failure


def test_list_before_init_prints_empty_array(scrolls_home, capsys):
    exit_code = main(["list"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


@pytest.fixture
def fake_wikipedia_api(monkeypatch):
    """Serve a canned MediaWiki extracts payload instead of the network."""
    payload = {
        "query": {
            "pages": [
                {
                    "pageid": 25387,
                    "title": "SQLite",
                    "fullurl": "https://en.wikipedia.org/wiki/SQLite",
                    "canonicalurl": "https://en.wikipedia.org/wiki/SQLite",
                    "extract": "SQLite is a database engine.\n\n\n== History ==\nEarly days.",
                    "categories": [
                        {"ns": 14, "title": "Category:Database management systems"}
                    ],
                }
            ]
        }
    }
    monkeypatch.setattr(wikipedia, "_get_json", lambda url: payload)
    return payload


def test_fetch_all_fetches_detected_wikipedia_item(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    exit_code = main(["fetch"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fetched"] == 1
    assert payload["failed"] == 0
    assert payload["results"] == [
        {"id": "wikipedia:en:SQLite", "status": "fetched", "title": "SQLite", "stage": "fetched"}
    ]

    stored = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    assert stored.stage == "fetched"
    assert stored.title == "SQLite"
    assert stored.extracted_text.startswith("SQLite is a database engine.")


def test_fetch_all_skips_sources_without_adapter(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://x.com/karpathy/status/1234567890123456789"])
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    exit_code = main(["fetch"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fetched"] == 1
    assert payload["skipped"] == 1
    by_id = {entry["id"]: entry for entry in payload["results"]}
    assert by_id["x:1234567890123456789"]["status"] == "skipped"
    assert "x" in by_id["x:1234567890123456789"]["reason"]
    # the skipped item is untouched and will be picked up once an adapter lands
    assert get_item(get_paths().db_path, "x:1234567890123456789").stage == "detected"


def test_fetch_all_with_nothing_detected(scrolls_home, capsys):
    exit_code = main(["fetch"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"fetched": 0, "skipped": 0, "failed": 0, "results": []}


def test_fetch_continues_past_failures_and_exits_nonzero(scrolls_home, monkeypatch, capsys):
    def boom(url):
        raise OSError("connection refused")

    monkeypatch.setattr(wikipedia, "_get_json", boom)
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    exit_code = main(["fetch"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed"] == 1
    assert payload["results"][0]["status"] == "failed"
    assert "connection refused" in payload["results"][0]["error"]
    # the item stays detected so a later fetch can retry it
    assert get_item(get_paths().db_path, "wikipedia:en:SQLite").stage == "detected"


def test_fetch_by_id_refetches_regardless_of_stage(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    exit_code = main(["fetch", "wikipedia:en:SQLite"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fetched"] == 1
    assert payload["results"][0]["id"] == "wikipedia:en:SQLite"


def test_fetch_by_id_without_adapter_fails(scrolls_home, capsys):
    main(["add", "https://x.com/karpathy/status/1234567890123456789"])
    capsys.readouterr()

    exit_code = main(["fetch", "x:1234567890123456789"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed"] == 1
    assert payload["results"][0]["status"] == "failed"
    assert "'x'" in payload["results"][0]["error"]


def test_fetch_unknown_id_is_an_error(scrolls_home, capsys):
    exit_code = main(["fetch", "wikipedia:en:Missing"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_md_renders_fetched_items_to_scroll_files(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    exit_code = main(["md"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rendered"] == 1
    assert payload["failed"] == 0
    assert payload["results"] == [
        {
            "id": "wikipedia:en:SQLite",
            "status": "rendered",
            "path": "scrolls/wikipedia/sqlite.md",
        }
    ]

    scroll = scrolls_home / "scrolls" / "wikipedia" / "sqlite.md"
    assert scroll.is_file()
    assert "# SQLite" in scroll.read_text(encoding="utf-8")
    stored = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    assert stored.stage == "rendered"
    assert stored.markdown_path == "scrolls/wikipedia/sqlite.md"


def test_md_bulk_run_is_idempotent(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    main(["md"])
    capsys.readouterr()

    exit_code = main(["md"])  # nothing left at stage 'fetched'
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"rendered": 0, "failed": 0, "results": []}


def test_md_by_id_rerenders_a_rendered_item(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    main(["md"])
    capsys.readouterr()

    exit_code = main(["md", "wikipedia:en:SQLite"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rendered"] == 1
    assert payload["results"][0]["path"] == "scrolls/wikipedia/sqlite.md"


def test_md_by_id_fails_for_unfetched_item(scrolls_home, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    exit_code = main(["md", "wikipedia:en:SQLite"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed"] == 1
    assert "detected" in payload["results"][0]["error"]
    # still no scroll file, stage unchanged
    assert not (scrolls_home / "scrolls" / "wikipedia").exists()
    assert get_item(get_paths().db_path, "wikipedia:en:SQLite").stage == "detected"


def test_md_unknown_id_is_an_error(scrolls_home, capsys):
    exit_code = main(["md", "wikipedia:en:Missing"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_search_returns_ranked_hits_json(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    exit_code = main(["search", "database engine"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    hit = payload[0]
    assert hit["id"] == "wikipedia:en:SQLite"
    assert hit["title"] == "SQLite"
    assert set(hit) == {"id", "source", "title", "url", "stage", "score", "snippet"}


def test_search_no_matches_prints_empty_array(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    exit_code = main(["search", "pelicans"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


def test_search_before_init_prints_empty_array(scrolls_home, capsys):
    exit_code = main(["search", "anything"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


def test_search_blank_query_is_an_error(scrolls_home, capsys):
    exit_code = main(["search", '""'])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_search_respects_limit_flag(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    exit_code = main(["search", "database", "--limit", "0"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


def test_show_prints_full_item_json(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    exit_code = main(["show", "wikipedia:en:SQLite"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "wikipedia:en:SQLite"
    assert payload["title"] == "SQLite"
    assert payload["stage"] == "fetched"
    assert payload["extracted_text"].startswith("SQLite is a database engine.")
    assert payload["provenance"]["adapter"] == "wikipedia"
    assert payload["tags"] == []


def test_show_unknown_id_is_an_error(scrolls_home, capsys):
    exit_code = main(["show", "wikipedia:en:Missing"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


@pytest.fixture
def fake_youtube_api(monkeypatch):
    """Serve canned oEmbed metadata and transcript instead of the network."""
    oembed = {
        "title": "How SQLite FTS Works",
        "author_name": "Example Channel",
        "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    }
    transcript = [
        {"text": "today we look at SQLite FTS5", "start": 0.0, "duration": 3.0},
        {"text": "and BM25 ranking", "start": 3.0, "duration": 2.0},
    ]
    monkeypatch.setattr(youtube, "_get_json", lambda url: dict(oembed))
    monkeypatch.setattr(youtube, "_get_transcript", lambda video_id: list(transcript))
    return oembed


def test_ingest_youtube_video_end_to_end(scrolls_home, fake_youtube_api, capsys):
    exit_code = main(["ingest", "https://youtu.be/dQw4w9WgXcQ"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "id": "youtube:dQw4w9WgXcQ",
        "source": "youtube",
        "url": "https://youtu.be/dQw4w9WgXcQ",
        "created": True,
        "title": "How SQLite FTS Works",
        "category": "media",  # classified inline: youtube source default
        "stage": "rendered",
        "markdown_path": "scrolls/youtube/how-sqlite-fts-works.md",
    }
    scroll = (scrolls_home / "scrolls" / "youtube" / "how-sqlite-fts-works.md").read_text()
    assert "SQLite FTS5 and BM25 ranking" in scroll
    capsys.readouterr()

    # the transcript is indexed: search finds the video by spoken content
    exit_code = main(["search", "BM25 ranking"])
    assert exit_code == 0
    hits = json.loads(capsys.readouterr().out)
    assert [hit["id"] for hit in hits] == ["youtube:dQw4w9WgXcQ"]


@pytest.fixture
def fake_github_api(monkeypatch):
    """Serve canned repo metadata and README instead of the network."""
    import base64

    import scrolls.sources.github as github

    repo = {
        "full_name": "oojBuffalo/scrolls",
        "html_url": "https://github.com/oojBuffalo/scrolls",
        "description": "Turn saved internet artifacts into agent-readable knowledge.",
        "owner": {"login": "oojBuffalo"},
        "created_at": "2026-05-01T12:00:00Z",
        "topics": ["knowledge-base", "sqlite"],
    }
    readme = "# Scrolls\n\nSQLite FTS5 keeps the library searchable.\n"
    encoded = base64.b64encode(readme.encode("utf-8")).decode("ascii")

    def get_json(url):
        if url.endswith("/readme"):
            return {"content": encoded, "encoding": "base64"}
        return dict(repo)

    monkeypatch.setattr(github, "_get_json", get_json)
    return repo


def test_ingest_github_repo_end_to_end(scrolls_home, fake_github_api, capsys):
    exit_code = main(["ingest", "https://github.com/oojBuffalo/scrolls"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "id": "github:oojBuffalo/scrolls",
        "source": "github",
        "url": "https://github.com/oojBuffalo/scrolls",
        "created": True,
        "title": "oojBuffalo/scrolls",
        "category": "project",  # classified inline: github curated default
        "stage": "rendered",
        "markdown_path": "scrolls/github/oojbuffalo-scrolls.md",
    }
    scroll = (scrolls_home / "scrolls" / "github" / "oojbuffalo-scrolls.md").read_text()
    assert '\nconcepts: ["knowledge-base", "sqlite"]\n' in scroll
    assert "SQLite FTS5 keeps the library searchable." in scroll
    capsys.readouterr()

    # repo topics are the first concepts producer: kb builds concept pages
    exit_code = main(["kb"])
    assert exit_code == 0
    kb_payload = json.loads(capsys.readouterr().out)
    assert kb_payload["concepts"] == 2
    concept_page = scrolls_home / "library" / "concepts" / "knowledge-base.md"
    assert "oojBuffalo/scrolls" in concept_page.read_text()


@pytest.fixture
def fake_arxiv_api(monkeypatch):
    """Serve a canned Atom feed and PDF instead of the network."""
    import scrolls.sources.arxiv as arxiv
    from pdf_fixtures import make_pdf

    feed = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2310.06825v1</id>
    <published>2023-10-10T17:54:02Z</published>
    <title>Mistral 7B</title>
    <summary>We introduce Mistral 7B, a 7-billion-parameter language model.</summary>
    <author><name>Albert Q. Jiang</name></author>
    <link href="http://arxiv.org/abs/2310.06825v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2310.06825v1" rel="related"
          type="application/pdf"/>
    <category term="cs.CL"/>
  </entry>
</feed>"""
    pdf = make_pdf("Grouped-query attention accelerates decoding throughput.")
    monkeypatch.setattr(arxiv, "_get_text", lambda url: feed)
    monkeypatch.setattr(arxiv, "_get_bytes", lambda url: pdf)
    return feed


def test_ingest_arxiv_paper_end_to_end(scrolls_home, fake_arxiv_api, capsys):
    exit_code = main(["ingest", "https://arxiv.org/abs/2310.06825"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "id": "arxiv:2310.06825",
        "source": "arxiv",
        "url": "https://arxiv.org/abs/2310.06825",
        "created": True,
        "title": "Mistral 7B",
        "category": "paper",  # classified inline: arxiv curated default
        "stage": "rendered",
        "markdown_path": "scrolls/arxiv/mistral-7b.md",
    }
    scroll = (scrolls_home / "scrolls" / "arxiv" / "mistral-7b.md").read_text()
    assert '\ntags: ["cs.CL"]\n' in scroll
    # taxonomy display names join the concept graph (ADR 0012)
    assert '\nconcepts: ["Computation and Language"]\n' in scroll
    assert "We introduce Mistral 7B" in scroll
    # PDF full text lands in the scroll's extracted content (ADR 0010)
    assert "Grouped-query attention accelerates decoding throughput." in scroll
    capsys.readouterr()

    # the abstract is indexed: search finds the paper by its summary
    exit_code = main(["search", "language model"])
    assert exit_code == 0
    hits = json.loads(capsys.readouterr().out)
    assert [hit["id"] for hit in hits] == ["arxiv:2310.06825"]
    capsys.readouterr()

    # the PDF full text is indexed too: this phrase appears nowhere else
    exit_code = main(["search", "decoding throughput"])
    assert exit_code == 0
    hits = json.loads(capsys.readouterr().out)
    assert [hit["id"] for hit in hits] == ["arxiv:2310.06825"]


def test_ingest_pdf_url_end_to_end(scrolls_home, monkeypatch, capsys):
    import scrolls.sources.pdf as pdf
    from pdf_fixtures import make_pdf

    blob = make_pdf(
        "Grouped-query attention trades model capacity for decode speed.",
        {"Title": "GQA Technical Report", "Subject": "A grouped-query attention report."},
    )
    monkeypatch.setattr(pdf, "_get_bytes", lambda url: blob)

    exit_code = main(["ingest", "https://example.com/papers/attention.pdf"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "id": "pdf:eb2e6487c357",
        "source": "pdf",
        "url": "https://example.com/papers/attention.pdf",
        "created": True,
        "title": "GQA Technical Report",
        "category": None,  # honestly unclassified: no rule for generic PDFs
        "stage": "rendered",
        "markdown_path": "scrolls/pdf/gqa-technical-report.md",
    }
    scroll = (scrolls_home / "scrolls" / "pdf" / "gqa-technical-report.md").read_text()
    assert "A grouped-query attention report." in scroll
    assert "Grouped-query attention trades model capacity" in scroll
    # the document itself is a media ref, so `scrolls media` can capture it
    assert (
        '\nmedia: [{"type": "pdf", "url": "https://example.com/papers/attention.pdf"}]\n'
        in scroll
    )
    capsys.readouterr()

    # the PDF text is indexed for search
    exit_code = main(["search", "decode speed"])
    assert exit_code == 0
    hits = json.loads(capsys.readouterr().out)
    assert [hit["id"] for hit in hits] == ["pdf:eb2e6487c357"]


def test_ingest_runs_add_fetch_md_in_one_command(scrolls_home, fake_wikipedia_api, capsys):
    exit_code = main(["ingest", "https://en.wikipedia.org/wiki/SQLite"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "id": "wikipedia:en:SQLite",
        "source": "wikipedia",
        "url": "https://en.wikipedia.org/wiki/SQLite",
        "created": True,
        "title": "SQLite",
        "category": "reference",
        "stage": "rendered",
        "markdown_path": "scrolls/wikipedia/sqlite.md",
    }
    # the first render already carries the category — no second pass needed
    scroll = (scrolls_home / "scrolls" / "wikipedia" / "sqlite.md").read_text()
    assert '\ncategory: "reference"\n' in scroll
    # visible page categories arrive as concepts (ADR 0007 follow-up)
    assert '\nconcepts: ["Database management systems"]\n' in scroll

    stored = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    assert stored.category == "reference"
    assert stored.provenance["classified_by"] == "rules-v1"


def test_ingest_leaves_unmatched_items_unclassified(scrolls_home, monkeypatch, capsys):
    import scrolls.sources.web as web

    html = (
        "<html><head><title>An ordinary post</title></head><body><article>"
        "<h1>An ordinary post</h1><p>Some long enough paragraph about nothing "
        "in particular, just plain prose for the extractor to find.</p>"
        "</article></body></html>"
    )
    monkeypatch.setattr(web, "_get_html", lambda url: html)

    exit_code = main(["ingest", "https://blog.example.com/post"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["category"] is None
    assert payload["stage"] == "rendered"


def test_ingest_existing_url_refreshes_it(scrolls_home, fake_wikipedia_api, capsys):
    main(["ingest", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    exit_code = main(["ingest", "https://en.wikipedia.org/wiki/SQLite"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is False
    assert payload["stage"] == "rendered"
    assert payload["markdown_path"] == "scrolls/wikipedia/sqlite.md"  # stable path


def test_ingest_without_adapter_registers_but_reports_failure(scrolls_home, capsys):
    exit_code = main(["ingest", "https://x.com/karpathy/status/1234567890123456789"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "x:1234567890123456789"
    assert payload["stage"] == "detected"
    assert "'x'" in payload["error"]
    # the item is still durably registered for a future adapter
    assert get_item(get_paths().db_path, "x:1234567890123456789").stage == "detected"


def test_ingest_fetch_failure_leaves_item_detected(scrolls_home, monkeypatch, capsys):
    def boom(url):
        raise OSError("connection refused")

    monkeypatch.setattr(wikipedia, "_get_json", boom)
    exit_code = main(["ingest", "https://en.wikipedia.org/wiki/SQLite"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == "detected"
    assert "connection refused" in payload["error"]


def test_ingest_rejects_non_http_url(scrolls_home, capsys):
    exit_code = main(["ingest", "not-a-url"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)
    assert not scrolls_home.exists()


def test_classify_batch_categorizes_and_rerenders(scrolls_home, fake_wikipedia_api, capsys):
    # add + fetch + md, not ingest: ingest classifies inline, and this test
    # exercises the batch path over an already-rendered uncategorized scroll
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    main(["md"])
    capsys.readouterr()

    exit_code = main(["classify"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["classified"] == 1
    assert payload["results"] == [
        {"id": "wikipedia:en:SQLite", "status": "classified", "category": "reference"}
    ]

    stored = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    assert stored.category == "reference"
    assert stored.provenance["classified_by"] == "rules-v1"
    assert stored.stage == "rendered"
    # the already-rendered scroll was re-rendered with the category in frontmatter
    scroll = (scrolls_home / "scrolls" / "wikipedia" / "sqlite.md").read_text()
    assert '\ncategory: "reference"\n' in scroll


def test_classify_batch_reports_unmatched_items(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    # make the stored item look like an unclassifiable web post
    plain = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    import dataclasses
    update_item(
        get_paths().db_path,
        dataclasses.replace(plain, source="web", title="An ordinary post",
                            url="https://blog.example.com/post"),
    )

    exit_code = main(["classify"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["classified"] == 0
    assert payload["unmatched"] == 1
    assert payload["results"][0]["status"] == "unmatched"
    assert get_item(get_paths().db_path, "wikipedia:en:SQLite").category is None


def test_classify_batch_never_overwrites_an_existing_category(
    scrolls_home, fake_wikipedia_api, capsys
):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    # a user-set category must win over the rules engine (IDEAS.md §8)
    import dataclasses
    item = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    update_item(get_paths().db_path, dataclasses.replace(item, category="tool"))

    exit_code = main(["classify"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"classified": 0, "unmatched": 0, "failed": 0, "results": []}
    assert get_item(get_paths().db_path, "wikipedia:en:SQLite").category == "tool"


def test_classify_batch_ignores_unfetched_items(scrolls_home, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])  # stage: detected
    capsys.readouterr()

    exit_code = main(["classify"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"classified": 0, "unmatched": 0, "failed": 0, "results": []}


def test_classify_by_id_reclassifies_explicitly(scrolls_home, fake_wikipedia_api, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    main(["fetch"])
    capsys.readouterr()

    import dataclasses
    item = get_item(get_paths().db_path, "wikipedia:en:SQLite")
    update_item(get_paths().db_path, dataclasses.replace(item, category="tool"))

    exit_code = main(["classify", "wikipedia:en:SQLite"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["classified"] == 1
    assert get_item(get_paths().db_path, "wikipedia:en:SQLite").category == "reference"


def test_classify_unknown_id_is_an_error(scrolls_home, capsys):
    exit_code = main(["classify", "wikipedia:en:Missing"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


@pytest.fixture
def fake_fieldtheory_root(tmp_path):
    """A miniature ~/.fieldtheory archive with one classified bookmark."""
    record = {
        "id": "1111",
        "tweetId": "1111",
        "url": "https://x.com/karpathy/status/1111",
        "text": "SQLite FTS5 is criminally underrated for local search.",
        "authorHandle": "karpathy",
        "authorName": "Andrej Karpathy",
        "postedAt": "Mon Jun 01 15:34:00 +0000 2026",
        "bookmarkedAt": None,
        "syncedAt": "2026-06-04T04:27:46.057Z",
        "media": [],
        "mediaObjects": [],
        "links": ["https://sqlite.org/fts5.html"],
        "tags": [],
    }
    root = tmp_path / "fieldtheory"
    (root / "bookmarks").mkdir(parents=True)
    (root / "bookmarks" / "bookmarks.jsonl").write_text(json.dumps(record) + "\n")
    pages = root / "library" / "bookmarks"
    pages.mkdir(parents=True)
    (pages / "2026-06-01-karpathy.md").write_text(
        '---\ncategory: technique\ndomain: databases\ntweet_id: "1111"\n---\n'
    )
    return root


def test_import_fieldtheory_end_to_end(scrolls_home, fake_fieldtheory_root, capsys):
    exit_code = main(["import", "fieldtheory", "--root", str(fake_fieldtheory_root)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"imported": 1, "skipped": 0, "failed": 0, "failures": []}

    stored = get_item(get_paths().db_path, "x:1111")
    assert stored.stage == "fetched"
    assert stored.category == "technique"
    assert stored.domain == "databases"
    assert stored.saved_at == "2026-06-04T04:27:46+00:00"

    # the imported bookmark flows through md and search unchanged
    main(["md"])
    capsys.readouterr()
    exit_code = main(["search", "criminally underrated"])
    assert exit_code == 0
    hits = json.loads(capsys.readouterr().out)
    assert [hit["id"] for hit in hits] == ["x:1111"]
    scroll = scrolls_home / "scrolls" / "x"
    assert list(scroll.glob("*.md"))


def test_import_fieldtheory_is_idempotent(scrolls_home, fake_fieldtheory_root, capsys):
    main(["import", "fieldtheory", "--root", str(fake_fieldtheory_root)])
    capsys.readouterr()
    exit_code = main(["import", "fieldtheory", "--root", str(fake_fieldtheory_root)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"imported": 0, "skipped": 1, "failed": 0, "failures": []}


def test_import_fieldtheory_never_overwrites_existing_item(
    scrolls_home, fake_fieldtheory_root, capsys
):
    main(["import", "fieldtheory", "--root", str(fake_fieldtheory_root)])
    import dataclasses
    item = get_item(get_paths().db_path, "x:1111")
    update_item(get_paths().db_path, dataclasses.replace(item, category="tool"))
    main(["import", "fieldtheory", "--root", str(fake_fieldtheory_root)])
    assert get_item(get_paths().db_path, "x:1111").category == "tool"


def test_import_fieldtheory_reports_bad_lines(scrolls_home, fake_fieldtheory_root, capsys):
    jsonl = fake_fieldtheory_root / "bookmarks" / "bookmarks.jsonl"
    jsonl.write_text("not json\n" + jsonl.read_text())
    exit_code = main(["import", "fieldtheory", "--root", str(fake_fieldtheory_root)])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 1
    assert payload["failed"] == 1
    assert payload["failures"][0]["line"] == 1


def test_import_fieldtheory_missing_archive_is_an_error(scrolls_home, tmp_path, capsys):
    exit_code = main(["import", "fieldtheory", "--root", str(tmp_path / "nowhere")])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_list_after_adds_prints_summaries(scrolls_home, capsys):
    main(["add", "https://youtu.be/dQw4w9WgXcQ"])
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    exit_code = main(["list"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert {entry["id"] for entry in payload} == {"youtube:dQw4w9WgXcQ", "wikipedia:en:SQLite"}
    for entry in payload:
        assert entry["stage"] == "detected"
        assert set(entry) == {"id", "source", "url", "title", "stage", "saved_at"}


# --- scrolls media (ADR 0011) ---


def _seed_fetched_item_with_media(item_id="arxiv:1706.03762", **overrides):
    """Insert a fetched item carrying one media ref; library must exist."""
    base = dict(
        id=item_id,
        source=item_id.split(":", 1)[0],
        source_id=item_id.split(":", 1)[1],
        url="https://arxiv.org/abs/1706.03762",
        saved_at="2026-06-12T08:00:00+00:00",
        title="Attention Is All You Need",
        summary="We propose the Transformer.",
        media=({"type": "pdf", "url": "https://arxiv.org/pdf/1706.03762"},),
        stage="fetched",
    )
    base.update(overrides)
    item = ScrollItem(**base)
    insert_item(get_paths().db_path, item)
    return item


def test_media_batch_captures_pending_refs_and_rerenders(scrolls_home, monkeypatch, capsys):
    import scrolls.media as media

    main(["init"])
    _seed_fetched_item_with_media()
    main(["md"])
    capsys.readouterr()
    monkeypatch.setattr(media, "_get_bytes", lambda url: b"%PDF-1.4 fake")

    exit_code = main(["media"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "captured": 1,
        "skipped": 0,
        "failed": 0,
        "results": [
            {
                "id": "arxiv:1706.03762",
                "status": "captured",
                "files": ["media/arxiv/1706-03762-1.pdf"],
            }
        ],
    }
    assert (
        scrolls_home / "media" / "arxiv" / "1706-03762-1.pdf"
    ).read_bytes() == b"%PDF-1.4 fake"
    stored = get_item(get_paths().db_path, "arxiv:1706.03762")
    assert stored.media[0]["path"] == "media/arxiv/1706-03762-1.pdf"
    # the rendered scroll's frontmatter now points at the local file
    scroll = (scrolls_home / "scrolls" / "arxiv" / "attention-is-all-you-need.md").read_text()
    assert '"path": "media/arxiv/1706-03762-1.pdf"' in scroll


def test_media_batch_is_idempotent(scrolls_home, monkeypatch, capsys):
    import scrolls.media as media

    main(["init"])
    _seed_fetched_item_with_media()
    monkeypatch.setattr(media, "_get_bytes", lambda url: b"%PDF-1.4 fake")
    main(["media"])
    capsys.readouterr()

    def boom(url):
        raise AssertionError("captured refs must not be re-downloaded")

    monkeypatch.setattr(media, "_get_bytes", boom)
    exit_code = main(["media"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"captured": 0, "skipped": 0, "failed": 0, "results": []}


def test_media_by_id_recaptures_explicitly(scrolls_home, monkeypatch, capsys):
    import scrolls.media as media

    main(["init"])
    _seed_fetched_item_with_media()
    monkeypatch.setattr(media, "_get_bytes", lambda url: b"version 1")
    main(["media"])
    capsys.readouterr()

    monkeypatch.setattr(media, "_get_bytes", lambda url: b"version 2")
    exit_code = main(["media", "arxiv:1706.03762"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["captured"] == 1
    assert (
        scrolls_home / "media" / "arxiv" / "1706-03762-1.pdf"
    ).read_bytes() == b"version 2"


def test_media_by_id_unknown_item_is_an_error(scrolls_home, capsys):
    exit_code = main(["media", "arxiv:nope"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_media_by_id_without_refs_reports_skip(scrolls_home, capsys):
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    exit_code = main(["media", "wikipedia:en:SQLite"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "captured": 0,
        "skipped": 1,
        "failed": 0,
        "results": [
            {
                "id": "wikipedia:en:SQLite",
                "status": "skipped",
                "reason": "no media references to capture",
            }
        ],
    }


def test_media_continues_past_failures_and_exits_nonzero(scrolls_home, monkeypatch, capsys):
    import scrolls.media as media

    main(["init"])
    _seed_fetched_item_with_media()
    _seed_fetched_item_with_media(
        item_id="x:1111",
        url="https://x.com/karpathy/status/1111",
        title="SQLite FTS5 is criminally underrated.",
        summary=None,
        media=({"type": "photo", "url": "https://pbs.twimg.com/bad"},),
    )
    capsys.readouterr()

    def get_bytes(url):
        if "bad" in url:
            raise OSError("connection refused")
        return b"good bytes"

    monkeypatch.setattr(media, "_get_bytes", get_bytes)
    exit_code = main(["media"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["captured"] == 1
    assert payload["failed"] == 1
    by_id = {entry["id"]: entry for entry in payload["results"]}
    assert by_id["arxiv:1706.03762"]["status"] == "captured"
    assert by_id["x:1111"]["status"] == "failed"
    assert "connection refused" in by_id["x:1111"]["error"]
    # the failed ref stays pending: no path recorded, nothing on disk
    stored = get_item(get_paths().db_path, "x:1111")
    assert "path" not in stored.media[0]
