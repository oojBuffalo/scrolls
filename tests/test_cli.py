"""Tests for the `scrolls` CLI entry point."""

import json

import pytest

import scrolls.sources.wikipedia as wikipedia
import scrolls.sources.youtube as youtube
from scrolls.cli import main
from scrolls.db import SCHEMA_VERSION
from scrolls.paths import get_paths
from scrolls.items import get_item


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
        "db": str(scrolls_home / "db.sqlite"),
        "config": str(scrolls_home / "config.toml"),
    }


def test_init_creates_library_skeleton(scrolls_home, capsys):
    exit_code = main(["init"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"root": str(scrolls_home), "created": True}
    for subdir in ("items", "scrolls", "library", "media"):
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
    main(["add", "https://github.com/oojBuffalo/scrolls"])
    main(["add", "https://en.wikipedia.org/wiki/SQLite"])
    capsys.readouterr()

    exit_code = main(["fetch"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fetched"] == 1
    assert payload["skipped"] == 1
    by_id = {entry["id"]: entry for entry in payload["results"]}
    assert by_id["github:oojBuffalo/scrolls"]["status"] == "skipped"
    assert "github" in by_id["github:oojBuffalo/scrolls"]["reason"]
    # the skipped item is untouched and will be picked up once an adapter lands
    assert get_item(get_paths().db_path, "github:oojBuffalo/scrolls").stage == "detected"


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
    main(["add", "https://github.com/oojBuffalo/scrolls"])
    capsys.readouterr()

    exit_code = main(["fetch", "github:oojBuffalo/scrolls"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed"] == 1
    assert payload["results"][0]["status"] == "failed"
    assert "github" in payload["results"][0]["error"]


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
        "stage": "rendered",
        "markdown_path": "scrolls/wikipedia/sqlite.md",
    }
    assert (scrolls_home / "scrolls" / "wikipedia" / "sqlite.md").is_file()


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
    exit_code = main(["ingest", "https://github.com/oojBuffalo/scrolls"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "github:oojBuffalo/scrolls"
    assert payload["stage"] == "detected"
    assert "github" in payload["error"]
    # the item is still durably registered for a future adapter
    assert get_item(get_paths().db_path, "github:oojBuffalo/scrolls").stage == "detected"


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
