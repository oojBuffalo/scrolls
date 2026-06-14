"""Tests for deterministic related-scroll discovery (IDEAS.md §10)."""

import json

import pytest

from scrolls.cli import main
from scrolls.items import ScrollItem, insert_item
from scrolls.paths import get_paths
from scrolls.related import find_related


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


@pytest.fixture
def db(scrolls_home):
    main(["init"])
    return get_paths().db_path


def make_item(item_id, **overrides):
    base = dict(
        id=item_id,
        source=item_id.split(":")[0],
        url=f"https://example.org/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00",
        title=item_id,
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def test_link_to_another_items_url_relates_them_both_ways(db):
    insert_item(db, make_item(
        "x:1111",
        url="https://x.com/a/status/1111",
        links=("https://arxiv.org/pdf/2605.27848",),
    ))
    insert_item(db, make_item(
        "arxiv:2605.27848",
        url="https://arxiv.org/abs/2605.27848",
    ))
    insert_item(db, make_item("x:9999", url="https://x.com/b/status/9999"))

    forward = find_related(db, "x:1111")
    assert [hit.id for hit in forward] == ["arxiv:2605.27848"]
    assert any("links to it" in reason for reason in forward[0].reasons)

    backward = find_related(db, "arxiv:2605.27848")
    assert [hit.id for hit in backward] == ["x:1111"]
    assert any("linked from it" in reason for reason in backward[0].reasons)


def test_gitlab_thread_relates_to_its_project(db):
    # The GitLab thread adapter (ADR 0085) stamps a gitlab.com/<project> link on
    # an issue/MR, so the thread resolves to the saved project item the way a
    # github issue resolves to its repo (ADR 0084) — the edge, not just the
    # link string, surfacing in `find_related`.
    insert_item(db, make_item(
        "gitlab:gitlab-org/gitlab#7",
        url="https://gitlab.com/gitlab-org/gitlab/-/issues/7",
        links=("https://gitlab.com/gitlab-org/gitlab",),
    ))
    insert_item(db, make_item(
        "gitlab:gitlab-org/gitlab",
        url="https://gitlab.com/gitlab-org/gitlab",
        category="project",
    ))
    insert_item(db, make_item("gitlab:other/project", url="https://gitlab.com/other/project"))

    forward = find_related(db, "gitlab:gitlab-org/gitlab#7")
    assert [hit.id for hit in forward] == ["gitlab:gitlab-org/gitlab"]
    assert any("links to it" in reason for reason in forward[0].reasons)

    # and the edge resolves both ways: the project finds its discussion thread
    backward = find_related(db, "gitlab:gitlab-org/gitlab")
    assert [hit.id for hit in backward] == ["gitlab:gitlab-org/gitlab#7"]
    assert any("linked from it" in reason for reason in backward[0].reasons)


def test_arxiv_preprint_relates_to_its_published_crossref_paper(db):
    # arXiv stamps the published DOI as a doi.org link (ADR 0038); it
    # resolves to the crossref item id even though the link's DOI case
    # differs from the stored id — DOIs fold through source detection
    insert_item(db, make_item(
        "arxiv:2310.06825",
        url="https://arxiv.org/abs/2310.06825",
        links=("https://doi.org/10.1109/Example.2024.12345",),  # mixed case
    ))
    insert_item(db, make_item(
        "crossref:10.1109/example.2024.12345",
        url="https://doi.org/10.1109/example.2024.12345",
    ))
    insert_item(db, make_item("web:other", url="https://example.com/elsewhere"))

    forward = find_related(db, "arxiv:2310.06825")
    assert [hit.id for hit in forward] == ["crossref:10.1109/example.2024.12345"]
    assert any("links to it" in reason for reason in forward[0].reasons)

    backward = find_related(db, "crossref:10.1109/example.2024.12345")
    assert [hit.id for hit in backward] == ["arxiv:2310.06825"]
    assert any("linked from it" in reason for reason in backward[0].reasons)


def test_exact_url_match_relates_web_items(db):
    insert_item(db, make_item(
        "x:1111",
        url="https://x.com/a/status/1111",
        links=("https://blog.example.com/post",),
    ))
    insert_item(db, make_item("web:abc123", url="https://blog.example.com/post"))

    hits = find_related(db, "x:1111")
    assert [hit.id for hit in hits] == ["web:abc123"]


def test_link_with_tracking_params_matches_the_clean_stored_url(db):
    """Links inside saved content carry whatever junk the author pasted;
    registration stores the normalized URL, so matching must normalize
    the link side too or the connection is silently lost."""
    insert_item(db, make_item(
        "x:1111",
        url="https://x.com/a/status/1111",
        links=("https://blog.example.com/post?utm_source=tweet#intro",),
    ))
    insert_item(db, make_item("web:abc123", url="https://blog.example.com/post"))

    hits = find_related(db, "x:1111")
    assert [hit.id for hit in hits] == ["web:abc123"]


def test_shared_concepts_outrank_same_category_only(db):
    insert_item(db, make_item(
        "github:a/repo", concepts=("full-text search", "BM25"), category="project",
    ))
    insert_item(db, make_item(
        "wikipedia:en:FTS",
        concepts=("Full-text search",),  # different spelling, same slug
        category="reference",
    ))
    insert_item(db, make_item("github:b/repo", category="project"))

    hits = find_related(db, "github:a/repo")
    assert [hit.id for hit in hits] == ["wikipedia:en:FTS", "github:b/repo"]
    assert any("full-text search" in reason for reason in hits[0].reasons)
    assert any("same category" in reason for reason in hits[1].reasons)


def test_devto_article_wires_to_its_crosspost_origin_and_co_concept(db):
    # The dev.to adapter (ADR 0061) records a cross-posted article's external
    # origin in `links` and its tags as `concepts`. So a saved dev.to post
    # connects to the original blog it cross-posted from (the cross-source
    # edge) and to anything sharing its concepts — the payoff a `web` scrape
    # (no concepts, no structured canonical) never delivered.
    insert_item(db, make_item(
        "devto:odeeb/sec-edgar-guide",
        url="https://dev.to/odeeb/sec-edgar-guide",
        links=("https://datatooly.xyz/sec-edgar-search/",),  # the cross-post origin
        concepts=("python", "api", "finance"),
    ))
    insert_item(db, make_item(
        "web:datatooly", url="https://datatooly.xyz/sec-edgar-search/",
    ))
    insert_item(db, make_item(
        "pypi:requests", concepts=("Python",),  # same slug, different spelling
    ))

    hits = find_related(db, "devto:odeeb/sec-edgar-guide")
    ids = [hit.id for hit in hits]
    assert "web:datatooly" in ids and "pypi:requests" in ids
    # the cross-post origin is reached through the link edge, the stronger signal
    assert ids[0] == "web:datatooly"
    origin = next(hit for hit in hits if hit.id == "web:datatooly")
    assert any("links to it" in reason for reason in origin.reasons)
    co_concept = next(hit for hit in hits if hit.id == "pypi:requests")
    assert any("python" in reason for reason in co_concept.reasons)

    # and the edge resolves both ways: the origin blog finds the dev.to post
    back = find_related(db, "web:datatooly")
    assert [hit.id for hit in back] == ["devto:odeeb/sec-edgar-guide"]
    assert any("linked from it" in reason for reason in back[0].reasons)


def test_shared_tags_match_case_insensitively(db):
    insert_item(db, make_item("arxiv:1", tags=("cs.CL", "nlp")))
    insert_item(db, make_item("arxiv:2", tags=("CS.cl",)))
    insert_item(db, make_item("arxiv:3", tags=("cs.CV",)))

    hits = find_related(db, "arxiv:1")
    assert [hit.id for hit in hits] == ["arxiv:2"]


def test_unrelated_items_yield_nothing(db):
    insert_item(db, make_item("x:1", url="https://x.com/a/status/1"))
    insert_item(db, make_item("wikipedia:en:Pelican"))
    assert find_related(db, "x:1") == []


def test_limit_caps_results(db):
    insert_item(db, make_item("github:a/repo", concepts=("agents",)))
    for index in range(5):
        insert_item(db, make_item(f"github:other/repo{index}", concepts=("agents",)))
    assert len(find_related(db, "github:a/repo", limit=2)) == 2


def test_unknown_id_raises(db):
    with pytest.raises(ValueError):
        find_related(db, "x:missing")


def test_cli_related_prints_hits_json(db, capsys):
    insert_item(db, make_item(
        "x:1111",
        url="https://x.com/a/status/1111",
        title="@a: paper thread",
        links=("https://arxiv.org/abs/2605.27848",),
    ))
    insert_item(db, make_item("arxiv:2605.27848", title="A Paper"))
    capsys.readouterr()

    exit_code = main(["related", "x:1111"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    hit = payload[0]
    assert hit["id"] == "arxiv:2605.27848"
    assert hit["title"] == "A Paper"
    assert hit["score"] > 0
    assert hit["reasons"]


def test_cli_related_unknown_id_is_an_error(scrolls_home, capsys):
    exit_code = main(["related", "x:missing"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)
