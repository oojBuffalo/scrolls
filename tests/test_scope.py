"""The scope/completeness envelope — G2 honest scope + truncation (MVP M2).

`scope_envelope` is the pure builder behind `scrolls search --stats` /
`scrolls list --stats`: it wraps a result list in the `{scope, stats,
results}` shape so a reader that holds *only the result* — not the call that
produced it — can recover the filters honored and whether the answer was
truncated below a cap (`docs/cli.md` → completeness contract G2, roadmap H6).
Consistent with the `stats` envelope `works`/`graph` already emit.
"""

from scrolls.scope import scope_envelope


def test_envelope_has_the_three_blocks_in_order():
    env = scope_envelope([{"id": "web:a"}], scope={"query": "x", "limit": 20}, matched=1)
    assert list(env) == ["scope", "stats", "results"]
    assert env["results"] == [{"id": "web:a"}]


def test_stats_report_returned_matched_and_truncation():
    # 2 returned out of 5 in scope → truncated, because the cap hid 3.
    env = scope_envelope(
        [{"id": "web:a"}, {"id": "web:b"}],
        scope={"query": "x", "limit": 2},
        matched=5,
    )
    assert env["stats"] == {"returned": 2, "matched": 5, "truncated": True}


def test_not_truncated_when_every_match_is_returned():
    env = scope_envelope(
        [{"id": "web:a"}, {"id": "web:b"}],
        scope={"query": "x", "limit": 20},
        matched=2,
    )
    assert env["stats"] == {"returned": 2, "matched": 2, "truncated": False}


def test_checked_and_empty_is_scope_honest_not_truncated():
    """An empty scoped result still names its scope and is not truncated.

    "Nothing in *this* scope" must say which scope — the empty case is where
    silent scope is most dangerous (it reads as library-wide absence).
    """
    env = scope_envelope([], scope={"query": "zzz", "source": "arxiv", "limit": 20}, matched=0)
    assert env["results"] == []
    assert env["stats"] == {"returned": 0, "matched": 0, "truncated": False}
    assert env["scope"] == {"query": "zzz", "source": "arxiv", "limit": 20}


def test_scope_drops_unapplied_facets_but_keeps_the_unclassified_pool():
    """`None` facets are pruned (not applied); an empty-string category stays.

    The empty string is a *meaningful* applied facet — the unclassified pool,
    mirroring `list`/`set` — so it must survive pruning, unlike a `None`.
    """
    env = scope_envelope(
        [],
        scope={
            "query": "x",
            "source": None,
            "category": "",
            "stage": None,
            "tag": None,
            "concept": None,
            "limit": 20,
        },
        matched=0,
    )
    assert env["scope"] == {"query": "x", "category": "", "limit": 20}


def test_custody_member_is_omitted_unless_passed():
    """No `custody` arg → no `stats.custody` key (the lean shape `related`/`works`
    keep); the three blocks and the existing stats keys are untouched."""
    env = scope_envelope([{"id": "web:a"}], scope={"query": "x", "limit": 20}, matched=1)
    assert "custody" not in env["stats"]
    assert env["stats"] == {"returned": 1, "matched": 1, "truncated": False}


def test_custody_member_rides_the_stats_block_when_passed():
    """A `custody` tally is attached under `stats.custody` (roadmap H98) — the
    browse-surface counterpart of the `graph` `stats.custody` block — without
    disturbing the returned/matched/truncated trio it sits beside."""
    custody = {"tiers": {"full": 2, "partial": 0, "reference": 1},
               "drift": {"verified": 1, "unverified": 2, "drifted": 0, "rotted": 0, "error": 0}}
    env = scope_envelope(
        [{"id": "web:a"}], scope={"query": "x", "limit": 1}, matched=3, custody=custody,
    )
    assert env["stats"]["custody"] == custody
    # it counts the *matched* scope, not the returned page: the tier/posture totals
    # sum to `matched` (3) even though only one row was returned (truncated)
    assert sum(env["stats"]["custody"]["tiers"].values()) == env["stats"]["matched"]
    assert sum(env["stats"]["custody"]["drift"].values()) == env["stats"]["matched"]
    assert env["stats"]["returned"] == 1 and env["stats"]["truncated"] is True


def test_an_uncapped_listing_omits_limit_and_never_truncates():
    """List with no `--limit` is uncapped: no `limit` key, truncated False.

    A uniform shape across capped/uncapped surfaces, but honest: the absence
    of a `limit` key says "this listing returned everything in scope."
    """
    env = scope_envelope(
        [{"id": "web:a"}, {"id": "web:b"}],
        scope={"source": "web", "limit": None},
        matched=2,
    )
    assert "limit" not in env["scope"]
    assert env["scope"] == {"source": "web"}
    assert env["stats"]["truncated"] is False
