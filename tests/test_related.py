"""Tests for deterministic related-scroll discovery (IDEAS.md §10)."""

import json

import pytest

from scrolls.cli import main
from scrolls.items import ScrollItem, insert_item
from scrolls.paths import get_paths
from scrolls.related import count_related, find_related, scored_related


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


def test_same_work_relates_representations_with_no_hub_present(db):
    # The case `scrolls graph` cannot catch (ADR 0069): an arXiv preprint and
    # a PubMed record both name the same published DOI, but no Crossref hub
    # item owns that DOI as its identity, so no realized link edge binds them.
    # They are still the same work, and `related` says so.
    insert_item(db, make_item(
        "arxiv:2310.06825",
        url="https://arxiv.org/abs/2310.06825",
        links=("https://doi.org/10.1109/example.2024.12345",),
    ))
    insert_item(db, make_item(
        "pubmed:99887766",
        url="https://pubmed.ncbi.nlm.nih.gov/99887766/",
        links=("https://doi.org/10.1109/example.2024.12345",),
    ))
    insert_item(db, make_item("web:other", url="https://example.com/elsewhere"))

    hits = find_related(db, "arxiv:2310.06825")
    assert [hit.id for hit in hits] == ["pubmed:99887766"]
    assert hits[0].reasons == ("same work: https://doi.org/10.1109/example.2024.12345",)
    # neither item's identity is the DOI, so there is no link reason at all
    assert not any("link" in reason for reason in hits[0].reasons)


def test_same_work_outranks_a_one_way_link(db):
    # target links to a citee (one-way link, 5 pts) and is the same work as a
    # sibling sharing its DOI (6 pts). Identity beats a citation: the sibling
    # ranks first.
    insert_item(db, make_item(
        "arxiv:2310.06825",
        url="https://arxiv.org/abs/2310.06825",
        source_id="2310.06825",
        links=(
            "https://doi.org/10.1109/example.2024.12345",  # the work DOI
            "https://example.com/cited",                    # a one-way citation
        ),
    ))
    insert_item(db, make_item(
        "crossref:10.1109/example.2024.12345",
        source_id="10.1109/example.2024.12345",
        url="https://doi.org/10.1109/example.2024.12345",
    ))
    insert_item(db, make_item("web:cited", url="https://example.com/cited"))

    hits = find_related(db, "arxiv:2310.06825")
    assert [hit.id for hit in hits] == [
        "crossref:10.1109/example.2024.12345",  # same work + link, ranks first
        "web:cited",                             # one-way link only
    ]
    # the hub-present sibling carries both the same-work and the link reason
    same_work = hits[0]
    assert any("same work" in reason for reason in same_work.reasons)
    assert any("links to it" in reason for reason in same_work.reasons)
    assert same_work.score > hits[1].score


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


def test_related_hits_carry_the_neighbours_custody_fidelity(db):
    # following a related edge lands on an item; the hit says at what fidelity
    # the library holds *that* item, the same tier `scrolls list`/`search` give.
    insert_item(db, make_item("github:a/repo", concepts=("agents",)))
    insert_item(db, make_item(
        "github:full/repo", concepts=("agents",),
        raw_text="the whole readme", content_hash="sha256:r", stage="rendered",
    ))
    insert_item(db, make_item(
        "github:ref/repo", concepts=("agents",), stage="detected",
    ))  # no body, no summary — a reference-only neighbour

    by_id = {hit.id: hit for hit in find_related(db, "github:a/repo")}
    assert by_id["github:full/repo"].fidelity == "full"
    assert by_id["github:ref/repo"].fidelity == "reference"


def test_cli_related_hit_exposes_fidelity(db, capsys):
    insert_item(db, make_item("x:1111", title="@a: thread", concepts=("ml",)))
    insert_item(db, make_item(
        "arxiv:2605.27848", title="A Paper", concepts=("ml",),
        raw_text="the abstract and body", content_hash="sha256:p", stage="rendered",
    ))
    capsys.readouterr()

    assert main(["related", "x:1111"]) == 0
    (hit,) = json.loads(capsys.readouterr().out)
    assert hit["id"] == "arxiv:2605.27848"
    assert hit["fidelity"] == "full"


def test_related_hits_carry_the_neighbours_drift_posture(db):
    # the node shape now carries both custody axes: how much (fidelity) and
    # whether the source moved (drift), read from the verify ledger (H56)
    from scrolls.custody import CustodyEvent, record_events

    insert_item(db, make_item("github:a/repo", concepts=("agents",)))
    insert_item(db, make_item("github:drifted/repo", concepts=("agents",)))
    insert_item(db, make_item("github:checked/repo", concepts=("agents",)))
    insert_item(db, make_item("github:never/repo", concepts=("agents",)))
    record_events(db, [
        CustodyEvent("github:drifted/repo", "t", "drifted", "h", "x", None),
        CustodyEvent("github:checked/repo", "t", "unchanged", "h", "h", None),
        # github:never/repo left with no verdict
    ])

    by_id = {hit.id: hit for hit in find_related(db, "github:a/repo")}
    assert by_id["github:drifted/repo"].drift == "drifted"
    assert by_id["github:checked/repo"].drift == "verified"  # unchanged → verified
    assert by_id["github:never/repo"].drift == "unverified"  # honest default


# --- Explainable relatedness: the qualitative relation-strength band (H322) ----
#
# `related` already carries the human-readable `reasons` (the *basis* of the
# edge, like search's `matched_fields`) and an opaque integer `score` (the
# magnitude, like the BM25 `score`); the missing piece — the relationship-surface
# analogue of search's `match_strength` (H312) — is a one-word `relation_strength`
# band (`strong`/`moderate`/`weak`) grounded in the relation signal-class point
# weights: a same-work (DOI) or link edge is an identity-/citation-grade bond
# (→ strong), shared concepts/tags are curated topical overlap (→ moderate), and
# same category/domain is weak corroboration (→ weak). The band names the *kind*
# of the strongest contributing class, never the multiplied magnitude.


def test_same_work_hit_is_strong(db):
    # A shared-DOI edge is identity-grade — the strongest signal — so it bands
    # `strong`. (No hub item owns the DOI, so only the work signal fires.)
    insert_item(db, make_item(
        "arxiv:1", links=("https://doi.org/10.1234/abc",)))
    insert_item(db, make_item(
        "pubmed:1", links=("https://doi.org/10.1234/abc",)))
    (hit,) = find_related(db, "arxiv:1")
    assert hit.id == "pubmed:1"
    assert any(reason.startswith("same work") for reason in hit.reasons)
    assert hit.relation_strength == "strong"


def test_link_edge_is_strong(db):
    # A realized link edge between two held items is a structural bond — strong.
    insert_item(db, make_item(
        "x:1111",
        url="https://x.com/a/status/1111",
        links=("https://arxiv.org/abs/2605.27848",),
    ))
    insert_item(db, make_item("arxiv:2605.27848", url="https://arxiv.org/abs/2605.27848"))
    (hit,) = find_related(db, "x:1111")
    assert hit.id == "arxiv:2605.27848"
    assert hit.relation_strength == "strong"


def test_shared_concepts_only_is_moderate(db):
    # Curated topical overlap, no identity bond → moderate.
    insert_item(db, make_item("web:a", concepts=("agents",)))
    insert_item(db, make_item("web:b", concepts=("agents",)))
    (hit,) = find_related(db, "web:a")
    assert hit.relation_strength == "moderate"


def test_shared_tags_only_is_moderate(db):
    insert_item(db, make_item("web:a", tags=("ml",)))
    insert_item(db, make_item("web:b", tags=("ml",)))
    (hit,) = find_related(db, "web:a")
    assert hit.relation_strength == "moderate"


def test_same_domain_only_is_weak(db):
    # Same domain is the weakest corroboration — "never enough on its own" → weak.
    insert_item(db, make_item("web:a", url="https://blog.example.org/1", domain="blog.example.org"))
    insert_item(db, make_item("web:b", url="https://blog.example.org/2", domain="blog.example.org"))
    (hit,) = find_related(db, "web:a")
    assert hit.relation_strength == "weak"


def test_relation_strength_is_the_strongest_class_not_the_magnitude(db):
    # A hit bound by BOTH a shared DOI (strong) and a shared tag (moderate) bands
    # `strong` — the strongest contributing class wins. And a hit bound by *three*
    # shared tags (6 points, the same magnitude as one same-work edge) stays
    # `moderate`: the band names the *kind* of the strongest bond, not the score.
    insert_item(db, make_item(
        "arxiv:1", links=("https://doi.org/10.1234/abc",), tags=("ml", "nlp", "agents")))
    insert_item(db, make_item(
        "pubmed:1", links=("https://doi.org/10.1234/abc",), tags=("ml",)))  # work + 1 tag
    insert_item(db, make_item(
        "web:tagged", tags=("ml", "nlp", "agents")))  # 3 tags, score 6, no identity bond

    by_id = {hit.id: hit for hit in find_related(db, "arxiv:1")}
    assert by_id["pubmed:1"].relation_strength == "strong"  # work dominates the tag
    tagged = by_id["web:tagged"]
    assert tagged.score == 6  # three shared tags, same magnitude as one work edge
    assert tagged.relation_strength == "moderate"  # but still a topical bond


def test_relation_strength_surfaces_on_the_cli(db, capsys):
    insert_item(db, make_item("web:a", tags=("ml",)))
    insert_item(db, make_item("web:b", tags=("ml",)))
    capsys.readouterr()
    assert main(["related", "web:a"]) == 0
    (hit,) = json.loads(capsys.readouterr().out)
    assert hit["relation_strength"] == "moderate"


def test_relation_strength_surfaces_on_mcp(db):
    from scrolls.mcp_server import get_related_scrolls

    insert_item(db, make_item(
        "x:1111", url="https://x.com/a/status/1111",
        links=("https://arxiv.org/abs/2605.27848",)))
    insert_item(db, make_item("arxiv:2605.27848", url="https://arxiv.org/abs/2605.27848"))
    (hit,) = get_related_scrolls("x:1111")
    assert hit["id"] == "arxiv:2605.27848"
    assert hit["relation_strength"] == "strong"


def test_cli_related_hit_exposes_drift(db, capsys):
    insert_item(db, make_item("x:1111", title="@a: thread", concepts=("ml",)))
    insert_item(db, make_item("arxiv:2605.27848", title="A Paper", concepts=("ml",)))
    capsys.readouterr()

    # never re-checked → the honest unverified posture travels to the CLI surface
    assert main(["related", "x:1111"]) == 0
    (hit,) = json.loads(capsys.readouterr().out)
    assert hit["id"] == "arxiv:2605.27848"
    assert hit["drift"] == "unverified"


def test_related_hits_carry_the_neighbours_last_checked(db):
    # the time axis of the per-item custody picture rides the node shape too:
    # *when* the drift verdict was taken (H86), beside `drift` (whether it moved)
    from scrolls.custody import CustodyEvent, last_checked, latest_events, record_events

    insert_item(db, make_item("github:a/repo", concepts=("agents",)))
    insert_item(db, make_item("github:checked/repo", concepts=("agents",)))
    insert_item(db, make_item("github:never/repo", concepts=("agents",)))
    record_events(db, [
        CustodyEvent("github:checked/repo", "2026-06-14T00:00:00+00:00",
                     "unchanged", "h", "h", None),
        # github:never/repo left with no verdict
    ])

    by_id = {hit.id: hit for hit in find_related(db, "github:a/repo")}
    assert by_id["github:checked/repo"].last_checked == "2026-06-14T00:00:00+00:00"
    assert by_id["github:never/repo"].last_checked is None  # honest absence
    # and it is exactly the shared primitive over the same ledger verdict
    verdicts = latest_events(db)
    assert by_id["github:checked/repo"].last_checked == last_checked(
        verdicts.get("github:checked/repo")
    )


def test_cli_related_hit_exposes_last_checked(db, capsys):
    insert_item(db, make_item("x:1111", title="@a: thread", concepts=("ml",)))
    insert_item(db, make_item("arxiv:2605.27848", title="A Paper", concepts=("ml",)))
    capsys.readouterr()

    # never re-checked → the honest null timestamp travels to the CLI surface
    assert main(["related", "x:1111"]) == 0
    (hit,) = json.loads(capsys.readouterr().out)
    assert hit["id"] == "arxiv:2605.27848"
    assert hit["last_checked"] is None


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


# --- The completeness contract G2 on `related`: scope echo + truncation ------


def _related_pool(db, count):
    """`count` items that all relate to a shared anchor by a common tag."""
    for index in range(count):
        insert_item(db, make_item(f"web:rel{index}", tags=("shared",)))


def _core_stats(stats):
    """The returned/matched/truncated trio, dropping the H99/H323 tally members.

    `related --stats` also carries a `custody` tally over the matched related set
    (roadmap H99) and a `strength` relation-strength tally (roadmap H323), the
    parity with `search`/`list --stats`; these G2 truncation/scope tests pin the
    *denominator*, so they drop both tallies and let the dedicated H99/H323 tests
    below own their values.
    """
    return {
        key: value
        for key, value in stats.items()
        if key not in ("custody", "strength")
    }


def test_find_related_is_the_capped_view_of_scored_related(db):
    """`find_related` is exactly `scored_related[:limit]` — same ranking."""
    _related_pool(db, 4)  # anchor + 3 neighbours
    full = scored_related(db, "web:rel0")
    assert [h.id for h in find_related(db, "web:rel0", limit=2)] == [
        h.id for h in full[:2]
    ]
    assert len(full) == 3  # every other item relates by the shared tag


def test_count_related_counts_every_neighbour_past_the_cap(db):
    _related_pool(db, 6)  # anchor + 5 neighbours
    assert len(find_related(db, "web:rel0", limit=2)) == 2
    assert count_related(db, "web:rel0") == 5


def test_count_related_raises_on_unknown_id_like_find_related(db):
    with pytest.raises(ValueError):
        count_related(db, "web:does-not-exist")


def test_cli_related_stats_echoes_anchor_and_marks_truncation(db, capsys):
    _related_pool(db, 4)  # anchor + 3 neighbours
    capsys.readouterr()

    exit_code = main(["related", "web:rel0", "--limit", "1", "--stats"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == {"item": "web:rel0", "limit": 1}
    assert _core_stats(payload["stats"]) == {"returned": 1, "matched": 3, "truncated": True}
    assert len(payload["results"]) == 1
    assert payload["results"][0]["reasons"]  # reasons survive into the envelope


def test_cli_related_stats_is_opt_in_default_stays_a_bare_array(db, capsys):
    _related_pool(db, 2)
    capsys.readouterr()

    main(["related", "web:rel0"])
    assert isinstance(json.loads(capsys.readouterr().out), list)

    main(["related", "web:rel0", "--stats"])
    assert isinstance(json.loads(capsys.readouterr().out), dict)


def test_cli_related_stats_isolated_item_is_scope_honest_not_truncated(db, capsys):
    """An item with no neighbour: empty results, but the anchor is named."""
    insert_item(db, make_item("web:lonely"))
    capsys.readouterr()

    exit_code = main(["related", "web:lonely", "--stats"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"] == []
    assert payload["scope"] == {"item": "web:lonely", "limit": 10}
    assert _core_stats(payload["stats"]) == {"returned": 0, "matched": 0, "truncated": False}


def test_cli_related_stats_unknown_id_still_errors_loudly(scrolls_home, capsys):
    """--stats does not soften the could-not-check path (G1): error, exit 1."""
    main(["init"])
    capsys.readouterr()
    exit_code = main(["related", "web:does-not-exist", "--stats"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


# --- H99: stats.custody — the custody tally over the matched related set ------


def _related_custody_mix(db):
    """An anchor + three neighbours all related by a shared tag, spanning the
    custody axes: a `full` neighbour re-checked unchanged (→ verified), a
    `partial` one drifted, a `reference` one never re-checked (→ unverified). The
    anchor itself is `full` but recorded `rotted` — a posture no neighbour has —
    so a tally that wrongly folded in the anchor would show `rotted: 1`; the
    related set never contains the anchor, so it stays 0.
    """
    from scrolls.custody import CustodyEvent, record_events

    insert_item(db, make_item(
        "web:anchor", tags=("shared",), raw_text="<raw>", content_hash="sha256:a"))
    insert_item(db, make_item(
        "web:full", tags=("shared",), raw_text="<raw>", content_hash="sha256:f"))
    insert_item(db, make_item("web:partial", tags=("shared",), extracted_text="body"))
    insert_item(db, make_item("web:ref", tags=("shared",)))
    record_events(db, [
        CustodyEvent("web:anchor", "2026-06-14T00:00:00+00:00", "rotted",
                     "sha256:a", None, "gone"),
        CustodyEvent("web:full", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:f", "sha256:f", None),
        CustodyEvent("web:partial", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:p", "sha256:x", None),
        # web:ref left with no verdict → unverified
    ])


_RELATED_TIERS = {"full": 1, "partial": 1, "reference": 1}
_RELATED_DRIFT = {"verified": 1, "unverified": 1, "drifted": 1, "rotted": 0, "error": 0}
_RELATED_MIX_CUSTODY = {
    "tiers": _RELATED_TIERS,
    "drift": _RELATED_DRIFT,
    # the neighbourhood is single-source `web`, so the per-source split (roadmap
    # H155) folds to one `{web: {tiers, drift}}` entry re-stating the whole tally
    "by_source": {"web": {"tiers": _RELATED_TIERS, "drift": _RELATED_DRIFT}},
    # single source → the weakest-source flag is honestly `null` (roadmap H174)
    "attention": None,
}


def test_cli_related_stats_custody_tallies_the_matched_related_set(db, capsys):
    # roadmap H99: `related --stats` carries the same `stats.custody` tally as
    # `search`/`list --stats`, over the anchor's related *neighbourhood* — "of the
    # N items related to this one, how much is held in full and how much drifted".
    _related_custody_mix(db)
    capsys.readouterr()

    assert main(["related", "web:anchor", "--stats"]) == 0
    stats = json.loads(capsys.readouterr().out)["stats"]
    assert stats["custody"] == _RELATED_MIX_CUSTODY
    # each section sums to `matched` (every related scroll has one tier + one posture)
    assert sum(stats["custody"]["tiers"].values()) == stats["matched"] == 3
    assert sum(stats["custody"]["drift"].values()) == stats["matched"]


def test_cli_related_stats_custody_excludes_the_anchor(db, capsys):
    # the anchor is `full` + `rotted`, a posture no neighbour has; the related set
    # never contains the anchor, so the tally shows `rotted: 0` — the anchor's own
    # custody is not folded into its neighbourhood picture.
    _related_custody_mix(db)
    capsys.readouterr()

    main(["related", "web:anchor", "--stats"])
    stats = json.loads(capsys.readouterr().out)["stats"]
    assert stats["custody"]["drift"]["rotted"] == 0  # anchor's posture, excluded


def test_cli_related_stats_custody_covers_the_matched_set_past_the_cap(db, capsys):
    # the load-bearing claim (mirroring H98 search/list): a `--limit 1` cap returns
    # one hit but the custody tally still covers the *whole* related set, so paging
    # never shrinks the custody picture.
    _related_custody_mix(db)
    capsys.readouterr()

    main(["related", "web:anchor", "--limit", "1", "--stats"])
    stats = json.loads(capsys.readouterr().out)["stats"]
    assert stats["returned"] == 1 and stats["matched"] == 3 and stats["truncated"] is True
    # over the matched 3, not the returned 1
    assert stats["custody"] == _RELATED_MIX_CUSTODY


def test_cli_related_stats_custody_present_even_when_empty(db, capsys):
    # an isolated anchor: no neighbours, but the custody member is present as the
    # stable zeroed shape (the H98 empty-envelope posture), never omitted.
    insert_item(db, make_item("web:lonely"))
    capsys.readouterr()

    main(["related", "web:lonely", "--stats"])
    stats = json.loads(capsys.readouterr().out)["stats"]
    assert stats["custody"] == {
        "tiers": {"full": 0, "partial": 0, "reference": 0},
        "drift": {"verified": 0, "unverified": 0, "drifted": 0, "rotted": 0, "error": 0},
        "by_source": {},  # no neighbours → the empty per-source split (roadmap H155)
        "attention": None,  # no sources → the honest-null weakest-source flag (H174)
    }


def test_cli_related_stats_custody_is_opt_in_absent_from_the_bare_array(db, capsys):
    # the custody member rides only the opt-in envelope — the bare default array is
    # unchanged, carrying no envelope and so no custody block.
    _related_custody_mix(db)
    capsys.readouterr()

    main(["related", "web:anchor"])
    assert isinstance(json.loads(capsys.readouterr().out), list)


# --- H323: stats.strength — the relation-strength tally over the matched set ---


def _related_strength_mix(db):
    """An anchor + three neighbours, one per relation-strength band: a same-work
    (shared DOI) sibling → `strong`, a shared-tag neighbour → `moderate`, a
    same-domain-only neighbour → `weak`. The anchor carries all three signals so
    each neighbour matches by exactly one.
    """
    insert_item(db, make_item(
        "web:anchor", url="https://blog.example.org/anchor", domain="blog.example.org",
        tags=("shared",), links=("https://doi.org/10.1234/abc",)))
    insert_item(db, make_item(  # same work (DOI) → strong
        "pubmed:strong", links=("https://doi.org/10.1234/abc",)))
    insert_item(db, make_item("web:moderate", tags=("shared",)))  # shared tag → moderate
    insert_item(db, make_item(  # same domain only → weak
        "web:weak", url="https://blog.example.org/other", domain="blog.example.org"))


def test_cli_related_stats_carries_a_relation_strength_tally(db, capsys):
    # roadmap H323: `related --stats` carries a `strength` tally over the matched
    # neighbourhood, the H313 analogue on the relation axis — the bands sum to
    # `matched` (every related hit has exactly one `relation_strength`).
    _related_strength_mix(db)
    capsys.readouterr()

    assert main(["related", "web:anchor", "--stats"]) == 0
    stats = json.loads(capsys.readouterr().out)["stats"]
    assert stats["strength"] == {"strong": 1, "moderate": 1, "weak": 1}
    assert sum(stats["strength"].values()) == stats["matched"] == 3
    # and the tally folds exactly the per-hit bands the rows show
    rows = json.loads(json.dumps(stats["strength"]))  # plain dict, band order stable
    assert list(rows) == ["strong", "moderate", "weak"]  # RELATION_STRENGTH_BANDS order


def test_cli_related_stats_strength_covers_the_matched_set_past_the_cap(db, capsys):
    # the load-bearing claim (the H313/H98 shape): a `--limit 1` cap returns one
    # hit but the strength tally still covers the *whole* matched neighbourhood.
    _related_strength_mix(db)
    capsys.readouterr()

    main(["related", "web:anchor", "--limit", "1", "--stats"])
    stats = json.loads(capsys.readouterr().out)["stats"]
    assert stats["returned"] == 1 and stats["matched"] == 3 and stats["truncated"] is True
    assert stats["strength"] == {"strong": 1, "moderate": 1, "weak": 1}  # the matched 3


def test_cli_related_stats_strength_present_even_when_empty(db, capsys):
    # an isolated anchor: the strength member is present as the stable zeroed shape
    # (the H323/H98 empty-envelope posture), never omitted.
    insert_item(db, make_item("web:lonely"))
    capsys.readouterr()

    main(["related", "web:lonely", "--stats"])
    stats = json.loads(capsys.readouterr().out)["stats"]
    assert stats["strength"] == {"strong": 0, "moderate": 0, "weak": 0}


def test_cli_related_stats_strength_is_opt_in_absent_from_the_bare_array(db, capsys):
    # the strength member rides only the opt-in envelope — the bare default array
    # carries no envelope and so no strength tally.
    _related_strength_mix(db)
    capsys.readouterr()

    main(["related", "web:anchor"])
    assert isinstance(json.loads(capsys.readouterr().out), list)


def test_tally_relation_strength_unit(db):
    # the fold is the closed-vocab histogram in band order, zeros included.
    from scrolls.related import tally_relation_strength

    assert tally_relation_strength(["strong", "weak", "strong"]) == {
        "strong": 2, "moderate": 0, "weak": 1,
    }
    assert tally_relation_strength([]) == {"strong": 0, "moderate": 0, "weak": 0}


# --- H324: --strength — the act-axis filter on the relation surface -----------
#
# Threshold semantics (at or above), the H314 `search --strength` / H254
# `related --fidelity` sibling on the rank axis: `--strength strong` keeps only
# identity/citation bonds, `moderate` adds topical overlap, `weak` keeps all.


def test_related_strength_strong_keeps_only_identity_bonds(db):
    _related_strength_mix(db)  # strong (work), moderate (tag), weak (domain)
    strong = find_related(db, "web:anchor", strength="strong")
    assert [h.id for h in strong] == ["pubmed:strong"]
    assert all(h.relation_strength == "strong" for h in strong)


def test_related_strength_moderate_keeps_band_and_stronger(db):
    # threshold: --strength moderate keeps strong + moderate, drops weak.
    _related_strength_mix(db)
    moderate = find_related(db, "web:anchor", strength="moderate")
    assert {h.relation_strength for h in moderate} == {"strong", "moderate"}
    assert "web:weak" not in {h.id for h in moderate}


def test_related_strength_weak_keeps_everything(db):
    _related_strength_mix(db)
    assert len(find_related(db, "web:anchor", strength="weak")) == 3


def test_related_strength_row_shows_equals_what_the_filter_selects(db):
    # a hit is kept by exactly the band it shows (the H254 row-shows-≡-filter tie):
    # --strength <band> keeps precisely the rows whose relation_strength is at or
    # above <band>.
    _related_strength_mix(db)
    order = ["strong", "moderate", "weak"]
    for i, band in enumerate(order):
        kept = {h.relation_strength for h in find_related(db, "web:anchor", strength=band)}
        assert kept <= set(order[: i + 1])  # only the band and stronger


def test_related_strength_ands_with_fidelity(db):
    # --strength ANDs with --fidelity (the H254/H314 AND semantics): the mix's
    # neighbours are all reference-tier, so strong∧reference keeps the same-work
    # sibling and strong∧full keeps nothing.
    _related_strength_mix(db)
    assert [h.id for h in find_related(
        db, "web:anchor", strength="strong", fidelity="reference")] == ["pubmed:strong"]
    assert find_related(db, "web:anchor", strength="strong", fidelity="full") == []


def test_related_strength_unknown_band_raises_valueerror(db):
    from scrolls.related import filter_related, scored_related

    _related_strength_mix(db)
    with pytest.raises(ValueError):
        filter_related(scored_related(db, "web:anchor"), strength="huge")


def test_count_related_honors_the_strength_filter(db):
    # the --stats denominator counts the kept set, never the whole scored set.
    _related_strength_mix(db)
    assert count_related(db, "web:anchor") == 3
    assert count_related(db, "web:anchor", strength="strong") == 1


def test_cli_related_strength_drills_from_the_tally(db, capsys):
    # H324 drill-from-tally tie: --strength <band> matched == sum of the bands at
    # or above <band> in the unfiltered strength tally (threshold, strongest-first
    # prefix), and the filtered tally re-folds over exactly the kept slice.
    _related_strength_mix(db)
    capsys.readouterr()

    main(["related", "web:anchor", "--stats"])
    tally = json.loads(capsys.readouterr().out)["stats"]["strength"]
    assert tally == {"strong": 1, "moderate": 1, "weak": 1}

    assert main(["related", "web:anchor", "--strength", "moderate", "--stats"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"]["strength"] == "moderate"
    assert payload["stats"]["matched"] == tally["strong"] + tally["moderate"] == 2
    assert payload["stats"]["strength"] == {"strong": 1, "moderate": 1, "weak": 0}


def test_cli_related_strength_unfiltered_scope_omits_the_key(db, capsys):
    # the None-is-pruned convention: --strength rides the scope echo only when honored.
    _related_strength_mix(db)
    capsys.readouterr()
    main(["related", "web:anchor", "--stats"])
    assert "strength" not in json.loads(capsys.readouterr().out)["scope"]


def test_cli_related_strength_rejects_unknown_band_with_exit_2(db):
    _related_strength_mix(db)
    with pytest.raises(SystemExit) as exc:
        main(["related", "web:anchor", "--strength", "huge"])
    assert exc.value.code == 2


def test_mcp_get_related_scrolls_strength_filter(db):
    from scrolls.mcp_server import get_related_scrolls

    _related_strength_mix(db)
    strong = get_related_scrolls("web:anchor", strength="strong")
    assert [h["id"] for h in strong] == ["pubmed:strong"]
    with pytest.raises(ValueError):
        get_related_scrolls("web:anchor", strength="nope")


# --- H155: stats.custody.by_source — the per-source split on `related --stats` ---


def _related_multi_source_mix(db):
    """An anchor + two neighbours sharing a tag across two sources: a `web` full
    one re-checked unchanged (→ verified) and an `arxiv` full one drifted. So the
    related set splits per source into `{web: verified, arxiv: drifted}`.
    """
    from scrolls.custody import CustodyEvent, record_events

    insert_item(db, make_item("web:anchor", tags=("shared",)))
    insert_item(db, make_item(
        "web:nb", tags=("shared",), raw_text="<raw>", content_hash="sha256:w"))
    insert_item(db, make_item(
        "arxiv:nb", tags=("shared",), raw_text="<raw>", content_hash="sha256:a"))
    record_events(db, [
        CustodyEvent("web:nb", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:w", "sha256:w", None),
        CustodyEvent("arxiv:nb", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:a", "sha256:x", None),
    ])


def test_cli_related_stats_by_source_splits_the_related_set(db, capsys):
    # roadmap H155: `related --stats` carries a `stats.custody.by_source` member —
    # the neighbourhood custody split per source, sorted keys, the lean
    # `{tiers, drift}` shape — summing to the whole-scope `stats.custody`.
    _related_multi_source_mix(db)
    capsys.readouterr()

    assert main(["related", "web:anchor", "--stats"]) == 0
    custody = json.loads(capsys.readouterr().out)["stats"]["custody"]
    by_source = custody["by_source"]
    assert list(by_source) == ["arxiv", "web"]  # sorted keys
    assert by_source["web"]["drift"]["verified"] == 1
    assert by_source["arxiv"]["drift"]["drifted"] == 1
    assert by_source["web"]["tiers"]["full"] == 1
    assert by_source["arxiv"]["tiers"]["full"] == 1
    # sums to the whole-scope tally beside it (the anchor's own custody is excluded
    # from both, pinned by test_cli_related_stats_custody_excludes_the_anchor)
    summed = {"full": 0, "partial": 0, "reference": 0}
    for entry in by_source.values():
        for tier, n in entry["tiers"].items():
            summed[tier] += n
    assert summed == custody["tiers"]
    # lean: no per-source coverage on the browse envelope
    assert all("coverage" not in entry for entry in by_source.values())


def test_cli_related_stats_by_source_empty_when_isolated(db, capsys):
    # an isolated anchor has no neighbours → the honest empty `{}` split.
    insert_item(db, make_item("web:lonely"))
    capsys.readouterr()
    main(["related", "web:lonely", "--stats"])
    custody = json.loads(capsys.readouterr().out)["stats"]["custody"]
    assert custody["by_source"] == {}


# --- H174: stats.custody.attention — the weakest-source flag on `related --stats` ---


def test_cli_related_stats_attention_names_the_weakest_source(db, capsys):
    # roadmap H174: `related --stats` distils its `by_source` map to the weakest-
    # source `attention` flag (the browse-surface counterpart of the graph flag). The
    # multi-source seed makes `arxiv` the only drifted neighbour, so it is flagged.
    _related_multi_source_mix(db)
    capsys.readouterr()

    assert main(["related", "web:anchor", "--stats"]) == 0
    attention = json.loads(capsys.readouterr().out)["stats"]["custody"]["attention"]
    assert attention is not None
    assert attention["source"] == "arxiv"  # the only neighbour with actionable loss
    assert attention["command"] == "scrolls verify --source arxiv"
    # lean flag for a lean map — no fabricated per-source coverage (H174)
    assert "coverage" not in attention


def test_cli_related_stats_attention_is_null_single_source(db, capsys):
    # the honest-null gate: the single-source `web` neighbourhood flags nothing even
    # with drift (`attention` only discriminates across sources).
    _related_custody_mix(db)  # single-source web, one drifted neighbour
    capsys.readouterr()
    main(["related", "web:anchor", "--stats"])
    assert json.loads(capsys.readouterr().out)["stats"]["custody"]["attention"] is None


# --- H254: --fidelity/--drift — the custody-filter family on the relationship surface ---


def test_find_related_fidelity_filters_the_neighbourhood_by_tier(db):
    # the holdings-axis sieve on the relationship surface: keep only the neighbours
    # held at one custody tier, the relationship twin of `list --fidelity`. The
    # `_related_custody_mix` neighbours span the tiers (full/partial/reference).
    _related_custody_mix(db)
    assert [h.id for h in find_related(db, "web:anchor", fidelity="full")] == ["web:full"]
    assert [h.id for h in find_related(db, "web:anchor", fidelity="partial")] == [
        "web:partial"
    ]
    assert [h.id for h in find_related(db, "web:anchor", fidelity="reference")] == [
        "web:ref"
    ]
    # row-shows-≡-filter: every kept hit shows exactly the tier it was selected by
    for tier in ("full", "partial", "reference"):
        hits = find_related(db, "web:anchor", fidelity=tier)
        assert hits and all(h.fidelity == tier for h in hits)


def test_find_related_drift_filters_the_neighbourhood_by_posture(db):
    # the ledger-claim-axis sieve: keep only the neighbours at one drift posture,
    # the relationship twin of `list --drift`. The mix's neighbours read verified
    # (web:full, unchanged), drifted (web:partial), unverified (web:ref).
    _related_custody_mix(db)
    assert [h.id for h in find_related(db, "web:anchor", drift="verified")] == [
        "web:full"
    ]
    assert [h.id for h in find_related(db, "web:anchor", drift="drifted")] == [
        "web:partial"
    ]
    assert [h.id for h in find_related(db, "web:anchor", drift="unverified")] == [
        "web:ref"
    ]
    # a posture no neighbour holds is an honest empty neighbourhood, never an error
    assert find_related(db, "web:anchor", drift="rotted") == []
    for posture in ("verified", "drifted", "unverified"):
        hits = find_related(db, "web:anchor", drift=posture)
        assert hits and all(h.drift == posture for h in hits)


def test_find_related_ands_both_custody_axes(db):
    # the two axes AND: web:full is the only full *and* verified neighbour; full
    # ANDed with drifted (web:partial is drifted but partial) is empty.
    _related_custody_mix(db)
    assert [
        h.id for h in find_related(db, "web:anchor", fidelity="full", drift="verified")
    ] == ["web:full"]
    assert (
        find_related(db, "web:anchor", fidelity="full", drift="drifted") == []
    )  # no neighbour is both


def _related_fidelity_rank(db):
    """An anchor + three neighbours whose *score* and *fidelity* deliberately
    diverge: a reference neighbour outranks both full ones, so a filter that runs
    *after* the cap would wrongly drop a full neighbour the user asked for.

    `web:refhi` (reference) shares 3 concepts → 9 pts, the top hit overall.
    `web:fullmid` (full) shares 2 → 6 pts; `web:fulllo` (full) shares 1 → 3 pts.
    """
    insert_item(db, make_item(
        "web:anchor", concepts=("alpha", "beta", "gamma")))
    insert_item(db, make_item(
        "web:refhi", concepts=("alpha", "beta", "gamma")))  # reference, top score
    insert_item(db, make_item(
        "web:fullmid", concepts=("alpha", "beta"),
        raw_text="<body>", content_hash="sha256:m"))  # full, mid score
    insert_item(db, make_item(
        "web:fulllo", concepts=("alpha",),
        raw_text="<body>", content_hash="sha256:l"))  # full, low score


def test_find_related_fidelity_sieves_before_the_cap(db):
    # the load-bearing H254 claim (the `list`-sieve shape, not the search
    # after-LIMIT shape): the filter runs *before* `[:limit]`, so the cap returns
    # the top-k neighbours *at that tier* — not the matching ones among the top-k.
    _related_fidelity_rank(db)
    # unfiltered, the reference neighbour is #1 overall
    assert find_related(db, "web:anchor", limit=1)[0].id == "web:refhi"
    # fidelity=full + limit=1 returns the top *full* neighbour, skipping the
    # higher-scoring reference one — proof the sieve precedes the cap
    capped = find_related(db, "web:anchor", limit=1, fidelity="full")
    assert [h.id for h in capped] == ["web:fullmid"]
    # uncapped, both full neighbours come back in score order
    assert [h.id for h in find_related(db, "web:anchor", fidelity="full")] == [
        "web:fullmid",
        "web:fulllo",
    ]


def test_count_related_honours_the_custody_filter(db):
    # the --stats denominator: `count_related` counts the *filtered* neighbourhood,
    # so a `related --fidelity X --stats` truncation marker is honest about X's set.
    _related_custody_mix(db)
    assert count_related(db, "web:anchor") == 3  # the whole neighbourhood
    assert count_related(db, "web:anchor", fidelity="full") == 1
    assert count_related(db, "web:anchor", drift="drifted") == 1
    assert count_related(db, "web:anchor", fidelity="full", drift="drifted") == 0


def test_find_related_rejects_unknown_custody_vocab(db):
    # closed vocabulary at the library level (the `list_items` contract): a typo is
    # a loud could-not-check ValueError, never a silent empty neighbourhood.
    _related_custody_mix(db)
    with pytest.raises(ValueError):
        find_related(db, "web:anchor", fidelity="ful")
    with pytest.raises(ValueError):
        find_related(db, "web:anchor", drift="drited")
    with pytest.raises(ValueError):
        count_related(db, "web:anchor", fidelity="ful")


def test_cli_related_fidelity_filters_the_rows(db, capsys):
    _related_custody_mix(db)
    capsys.readouterr()
    assert main(["related", "web:anchor", "--fidelity", "full"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in rows] == ["web:full"]
    assert all(r["fidelity"] == "full" for r in rows)


def test_cli_related_drift_filters_the_rows(db, capsys):
    _related_custody_mix(db)
    capsys.readouterr()
    assert main(["related", "web:anchor", "--drift", "drifted"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in rows] == ["web:partial"]
    assert all(r["drift"] == "drifted" for r in rows)


def test_cli_related_rejects_unknown_custody_vocab(db):
    # the CLI's closed vocabulary is enforced by argparse `choices=` → exit 2,
    # before the command body runs (the `list --fidelity`/`--drift` precedent).
    for bad in (["--fidelity", "ful"], ["--drift", "drited"]):
        with pytest.raises(SystemExit) as excinfo:
            main(["related", "web:anchor", *bad])
        assert excinfo.value.code == 2


def test_cli_related_stats_scope_echoes_the_custody_filters(db, capsys):
    # G2 scope honesty: a reader holding only the envelope recovers which
    # custody-filtered neighbourhood it covered, and `matched` counts that set.
    _related_custody_mix(db)
    capsys.readouterr()
    assert main(["related", "web:anchor", "--fidelity", "full", "--stats"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == {"item": "web:anchor", "fidelity": "full", "limit": 10}
    assert _core_stats(payload["stats"]) == {
        "returned": 1,
        "matched": 1,
        "truncated": False,
    }


def test_cli_related_unfiltered_scope_omits_the_custody_keys(db, capsys):
    # the `None`-is-pruned convention (scope_envelope): an unfiltered call keeps the
    # lean scope shape — `fidelity`/`drift` appear only when honored.
    _related_custody_mix(db)
    capsys.readouterr()
    main(["related", "web:anchor", "--stats"])
    scope = json.loads(capsys.readouterr().out)["scope"]
    assert scope == {"item": "web:anchor", "limit": 10}
    assert "fidelity" not in scope and "drift" not in scope
