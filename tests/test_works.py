"""Tests for scholarly-work clustering by shared DOI (ADR 0069).

`scrolls works` groups the items that are *the same scholarly work* — an
arXiv preprint, its published Crossref article, a PubMed record, a
bioRxiv/medRxiv preprint — keyed by the DOI that names the work, not by
the realized link edges `scrolls graph` resolves. The decisive case is a
work whose binding Crossref hub item is *not* in the library: two items
each linking to `doi.org/D` share no graph edge (their links resolve to a
URL token no item owns), yet they are the same work, and `works` clusters
them where `graph` cannot.
"""

import json

import pytest

from scrolls.cli import main
from scrolls.items import ScrollItem, insert_item
from scrolls.paths import get_paths
from scrolls.works import (
    filter_works,
    find_works,
    membership_payload,
    to_payload,
    work_membership,
    works_for_item,
    works_over,
)


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
        source_id=item_id.split(":", 1)[1] if ":" in item_id else None,
        url=f"https://example.org/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00",
        title=item_id,
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def _core_stats(stats):
    """The `items`/`works` pair, dropping the H100 `custody` member.

    The `works` stats block now also carries a `custody` tally over the reported
    works' representations (roadmap H100, the parity with the browse
    `search`/`list`/`related --stats` envelopes and `graph` stats); these
    structural-shape tests pin the counts, so they drop `custody` and let the
    dedicated H100 tests below own its value.
    """
    return {key: value for key, value in stats.items() if key != "custody"}


# The zeroed custody shape an empty scope tallies to — every tier/posture
# present in the canonical order with a zero count (a stable shape to filter).
ZERO_CUSTODY = {
    "tiers": {"full": 0, "partial": 0, "reference": 0},
    "drift": {
        "verified": 0,
        "unverified": 0,
        "drifted": 0,
        "rotted": 0,
        "error": 0,
    },
    # no reported works → no representations → the empty per-source split (H155)
    "by_source": {},
    # no sources → the weakest-source flag is honestly `null` (roadmap H174)
    "attention": None,
    # no works → the at-risk-works summary is the honest zeroed fold (roadmap H266)
    "at_risk": {"total": 0, "at_risk": 0, "most_at_risk": None},
}


def test_preprint_and_published_doi_cluster_into_one_work(db):
    # The arXiv preprint links to its published DOI; the Crossref item *is*
    # that DOI. They are one work, bound by the DOI.
    insert_item(db, make_item(
        "arxiv:1706.03762",
        url="https://arxiv.org/abs/1706.03762",
        links=("https://doi.org/10.5555/3295222",),
    ))
    insert_item(db, make_item(
        "crossref:10.5555/3295222",
        url="https://doi.org/10.5555/3295222",
    ))

    works = find_works(db)
    assert len(works) == 1
    work = works[0]
    assert work.doi == "10.5555/3295222"
    assert work.url == "https://doi.org/10.5555/3295222"
    assert [r.id for r in work.representations] == [
        "arxiv:1706.03762",
        "crossref:10.5555/3295222",
    ]


def test_clusters_without_the_crossref_hub_present(db):
    # The distinction from `scrolls graph`: two items each linking to the
    # same DOI, with no Crossref item in the library, share no graph edge
    # but are still the same work.
    insert_item(db, make_item(
        "arxiv:1706.03762",
        url="https://arxiv.org/abs/1706.03762",
        links=("https://doi.org/10.5555/3295222",),
    ))
    insert_item(db, make_item(
        "pubmed:99887766",
        url="https://pubmed.ncbi.nlm.nih.gov/99887766/",
        links=("https://doi.org/10.5555/3295222",),
    ))

    works = find_works(db)
    assert len(works) == 1
    assert [r.id for r in works[0].representations] == [
        "arxiv:1706.03762",
        "pubmed:99887766",
    ]


def test_single_representation_work_is_omitted_by_default(db):
    insert_item(db, make_item(
        "arxiv:1706.03762",
        url="https://arxiv.org/abs/1706.03762",
        links=("https://doi.org/10.5555/3295222",),
    ))

    assert find_works(db) == []


def test_min_one_lists_single_representation_works(db):
    insert_item(db, make_item(
        "arxiv:1706.03762",
        url="https://arxiv.org/abs/1706.03762",
        links=("https://doi.org/10.5555/3295222",),
    ))

    works = find_works(db, min_representations=1)
    assert len(works) == 1
    assert [r.id for r in works[0].representations] == ["arxiv:1706.03762"]


def test_doi_in_source_id_keys_the_work(db):
    # bioRxiv/medRxiv ids *are* DOIs (10.1101/<accession>): a saved bioRxiv
    # preprint and its directly-saved Crossref DOI are one work, even though
    # the bioRxiv item emits no doi.org link to its own preprint DOI.
    insert_item(db, make_item(
        "biorxiv:10.1101/2021.01.01.123456",
        url="https://www.biorxiv.org/content/10.1101/2021.01.01.123456v1",
    ))
    insert_item(db, make_item(
        "crossref:10.1101/2021.01.01.123456",
        url="https://doi.org/10.1101/2021.01.01.123456",
    ))

    works = find_works(db)
    assert len(works) == 1
    assert works[0].doi == "10.1101/2021.01.01.123456"
    assert [r.id for r in works[0].representations] == [
        "biorxiv:10.1101/2021.01.01.123456",
        "crossref:10.1101/2021.01.01.123456",
    ]


def test_doi_case_is_folded(db):
    # detect_source lowercases a doi.org DOI and Crossref stores it
    # lowercased, so a mixed-case link and the folded id are one work.
    insert_item(db, make_item(
        "arxiv:1706.03762",
        url="https://arxiv.org/abs/1706.03762",
        links=("https://doi.org/10.5555/AbC.123",),
    ))
    insert_item(db, make_item(
        "crossref:10.5555/abc.123",
        url="https://doi.org/10.5555/abc.123",
    ))

    works = find_works(db)
    assert len(works) == 1
    assert works[0].doi == "10.5555/abc.123"
    assert len(works[0].representations) == 2


def test_unrelated_items_form_no_work(db):
    insert_item(db, make_item("github:rust-lang/rust"))
    insert_item(db, make_item(
        "arxiv:1706.03762",
        links=("https://doi.org/10.5555/3295222",),
    ))
    insert_item(db, make_item(
        "wikipedia:en:SQLite",
        url="https://en.wikipedia.org/wiki/SQLite",
    ))

    assert find_works(db) == []


def test_works_sorted_by_representation_count_then_doi(db):
    # Work A: three representations. Work B: two. Work A first (more), then
    # ties (none here) break on the DOI string.
    for n in (1, 2, 3):
        insert_item(db, make_item(
            f"arxiv:230{n}.0000{n}",
            url=f"https://arxiv.org/abs/230{n}.0000{n}",
            links=("https://doi.org/10.1000/aaa",),
        ))
    for n in (1, 2):
        insert_item(db, make_item(
            f"pubmed:1000{n}",
            url=f"https://pubmed.ncbi.nlm.nih.gov/1000{n}/",
            links=("https://doi.org/10.2000/bbb",),
        ))

    works = find_works(db)
    assert [w.doi for w in works] == ["10.1000/aaa", "10.2000/bbb"]
    assert [len(w.representations) for w in works] == [3, 2]


def test_one_item_can_belong_to_two_works(db):
    # A review linking to two distinct DOIs is a representation of neither
    # work alone, but it does bind into both clusters.
    insert_item(db, make_item(
        "web:review",
        url="https://example.org/review",
        links=("https://doi.org/10.1000/aaa", "https://doi.org/10.2000/bbb"),
    ))
    insert_item(db, make_item(
        "crossref:10.1000/aaa", url="https://doi.org/10.1000/aaa",
    ))
    insert_item(db, make_item(
        "crossref:10.2000/bbb", url="https://doi.org/10.2000/bbb",
    ))

    works = find_works(db)
    assert {w.doi for w in works} == {"10.1000/aaa", "10.2000/bbb"}
    for w in works:
        assert "web:review" in {r.id for r in w.representations}


def test_empty_and_uninitialized_library_have_no_works(db, tmp_path):
    assert find_works(db) == []  # initialized but empty
    assert find_works(tmp_path / "nope.sqlite") == []  # missing db


def test_works_over_takes_a_given_item_set():
    items = [
        make_item("arxiv:1", links=("https://doi.org/10.1000/x",)),
        make_item("crossref:10.1000/x", url="https://doi.org/10.1000/x"),
    ]
    works = works_over(items)
    assert len(works) == 1
    assert works[0].doi == "10.1000/x"


# --- the canonical representation -----------------------------------------


def test_canonical_prefers_the_published_record_over_the_preprint():
    # crossref (registered published work) outranks the arXiv preprint, so
    # the published record is the work's canonical representation regardless
    # of which item was saved first or sorts first by id.
    items = [
        make_item("arxiv:1706.03762", links=("https://doi.org/10.5555/x",)),
        make_item("crossref:10.5555/x", url="https://doi.org/10.5555/x"),
    ]
    work = works_over(items)[0]
    assert work.canonical.id == "crossref:10.5555/x"
    # the canonical is one of the work's own representations
    assert work.canonical in work.representations


def test_canonical_follows_the_source_precedence_order():
    # pubmed outranks biorxiv outranks arxiv: the highest-ranked source wins
    # even when a lower-ranked id sorts first alphabetically.
    items = [
        make_item("arxiv:zzz", links=("https://doi.org/10.1000/y",)),
        make_item("biorxiv:10.1101/2021.01.01.000001",
                  url="https://www.biorxiv.org/content/10.1101/2021.01.01.000001v1",
                  links=("https://doi.org/10.1000/y",)),
        make_item("pubmed:aaa",
                  url="https://pubmed.ncbi.nlm.nih.gov/aaa/",
                  links=("https://doi.org/10.1000/y",)),
    ]
    work = works_over(items)[0]
    assert work.canonical.source == "pubmed"


def test_canonical_breaks_source_ties_by_id():
    # two representations from the same (out-of-table) source: the lower id
    # is the deterministic canonical choice.
    items = [
        make_item("web:zeta", url="https://example.org/zeta",
                  links=("https://doi.org/10.1000/z",)),
        make_item("web:alpha", url="https://example.org/alpha",
                  links=("https://doi.org/10.1000/z",)),
    ]
    work = works_over(items)[0]
    assert work.canonical.id == "web:alpha"


def test_works_for_item_solo_work_canonical_is_the_item_itself():
    preprint, _ = _attention_pair()
    work = works_for_item([preprint], "arxiv:1706.03762")[0]
    assert work.canonical.id == "arxiv:1706.03762"


def test_representations_carry_their_per_item_custody_fidelity():
    # each representation reports its own tier (ADR 0100), so an agent sees the
    # library may hold the preprint in full but only a reference to the record.
    items = [
        make_item("arxiv:1706.03762", links=("https://doi.org/10.1000/x",),
                  raw_text="the preprint body", content_hash="sha256:a",
                  stage="rendered"),
        make_item("crossref:10.1000/x", url="https://doi.org/10.1000/x"),
    ]
    (work,) = works_over(items)
    by_id = {rep.id: rep for rep in work.representations}
    assert by_id["arxiv:1706.03762"].fidelity == "full"
    assert by_id["crossref:10.1000/x"].fidelity == "reference"


def test_representation_payload_carries_per_item_drift_posture():
    # H64: each representation's drift posture rides the payload, from the same
    # `drift_posture`/`latest_events` ledger every other per-item surface reads —
    # the ledger-derived axis is a payload enrichment (the H56 graph-node split),
    # so the item-intrinsic `fidelity` stays on the dataclass.
    from scrolls.custody import CustodyEvent, drift_posture

    items = [
        make_item("arxiv:1706.03762", links=("https://doi.org/10.1000/x",)),
        make_item("crossref:10.1000/x", url="https://doi.org/10.1000/x"),
    ]
    (work,) = works_over(items)
    verdicts = {
        "arxiv:1706.03762": CustodyEvent(
            item_id="arxiv:1706.03762", checked_at="2026-06-14T00:00:00+00:00",
            status="drifted", prior_hash="a", observed_hash="b"),
        # crossref:10.1000/x left out of the ledger → unverified
    }
    payload = to_payload(
        [work], len(items), scope={"min_representations": 2}, verdicts=verdicts
    )
    by_id = {r["id"]: r for r in payload["works"][0]["representations"]}
    assert by_id["arxiv:1706.03762"]["drift"] == "drifted"
    assert by_id["crossref:10.1000/x"]["drift"] == "unverified"
    # the shared primitive, not a re-derivation
    assert by_id["arxiv:1706.03762"]["drift"] == drift_posture(
        verdicts["arxiv:1706.03762"]
    )


def test_representation_drift_defaults_to_unverified_without_a_ledger():
    # the pure caller (no verdicts) reads `unverified` for every representation —
    # honest never-checked, never silently "clean" (drift_posture(None))
    items = [
        make_item("arxiv:1706.03762", links=("https://doi.org/10.1000/x",)),
        make_item("crossref:10.1000/x", url="https://doi.org/10.1000/x"),
    ]
    (work,) = works_over(items)
    payload = to_payload([work], len(items), scope={"min_representations": 2})
    assert all(
        rep["drift"] == "unverified"
        for rep in payload["works"][0]["representations"]
    )


def test_representation_payload_carries_per_item_last_checked():
    # H87: the time axis (last_checked) rides each representation beside `drift`,
    # from the same `last_checked`/`latest_events` ledger — the time-axis sibling
    # of the H64 drift split, completing the seventh per-item surface.
    from scrolls.custody import CustodyEvent, last_checked

    items = [
        make_item("arxiv:1706.03762", links=("https://doi.org/10.1000/x",)),
        make_item("crossref:10.1000/x", url="https://doi.org/10.1000/x"),
    ]
    (work,) = works_over(items)
    verdicts = {
        "arxiv:1706.03762": CustodyEvent(
            item_id="arxiv:1706.03762", checked_at="2026-06-14T00:00:00+00:00",
            status="drifted", prior_hash="a", observed_hash="b"),
        # crossref:10.1000/x left out of the ledger → null
    }
    payload = to_payload(
        [work], len(items), scope={"min_representations": 2}, verdicts=verdicts
    )
    by_id = {r["id"]: r for r in payload["works"][0]["representations"]}
    assert by_id["arxiv:1706.03762"]["last_checked"] == "2026-06-14T00:00:00+00:00"
    assert by_id["crossref:10.1000/x"]["last_checked"] is None  # honest absence
    # the shared primitive, not a re-derivation
    assert by_id["arxiv:1706.03762"]["last_checked"] == last_checked(
        verdicts["arxiv:1706.03762"]
    )


def test_representation_last_checked_defaults_to_null_without_a_ledger():
    # the pure caller (no verdicts) reads `null` for every representation —
    # honest never-checked, never a fabricated timestamp (last_checked(None))
    items = [
        make_item("arxiv:1706.03762", links=("https://doi.org/10.1000/x",)),
        make_item("crossref:10.1000/x", url="https://doi.org/10.1000/x"),
    ]
    (work,) = works_over(items)
    payload = to_payload([work], len(items), scope={"min_representations": 2})
    assert all(
        rep["last_checked"] is None
        for rep in payload["works"][0]["representations"]
    )


# --- the per-work aggregate custody posture (roadmap H261) -----------------
#
# Each work now carries a `custody` block — the *consolidation* of its
# representations' per-item custody (the new custody shape, vision §3.5): the
# work-level verdict "is this work safely held?", not just the per-row fidelity/
# drift. `best_fidelity`/`safest_drift` are the best each axis offers across the
# representations; `safely_held` is the strong predicate ∃ a `full` rep whose
# drift ∈ {verified, unverified} — an unmoved, fully re-derivable copy exists.


def _full(item_id, doi, **overrides):
    """A full-fidelity representation of the work named by `doi`."""
    return make_item(
        item_id, url=f"https://example.org/{item_id}",
        links=(f"https://doi.org/{doi}",),
        raw_text="body", content_hash=f"sha256:{item_id}", stage="rendered",
        **overrides,
    )


def _partial(item_id, doi, **overrides):
    """A partial-fidelity representation (summary only) of `doi`."""
    return make_item(
        item_id, url=f"https://example.org/{item_id}",
        links=(f"https://doi.org/{doi}",),
        summary="a summary", stage="rendered", **overrides,
    )


def _reference(item_id, doi, **overrides):
    """A reference-only representation (bare pointer) of `doi`."""
    return make_item(
        item_id, url=f"https://example.org/{item_id}",
        links=(f"https://doi.org/{doi}",), stage="rendered", **overrides,
    )


def _verdict(item_id, status, at="2026-06-14T00:00:00+00:00"):
    from scrolls.custody import CustodyEvent

    return CustodyEvent(
        item_id=item_id, checked_at=at, status=status,
        prior_hash="sha256:a", observed_hash="sha256:b",
    )


def _work_custody(items, verdicts=None):
    """The `custody` block of the single work the items form."""
    (work,) = works_over(items)
    payload = to_payload(
        [work], len(items), scope={"min_representations": 2}, verdicts=verdicts
    )
    return payload["works"][0]["custody"]


def test_work_custody_block_consolidates_the_representations():
    # the basic shape: a full+verified preprint and a reference+unverified record →
    # the work is safely held (the full copy is unmoved), best fidelity is full, the
    # safest drift verified — the consolidated verdict, not the per-row detail.
    items = [_full("arxiv:a", "10.1000/x"), _reference("crossref:10.1000/x", "10.1000/x")]
    custody = _work_custody(items, {"arxiv:a": _verdict("arxiv:a", "unchanged")})
    assert custody == {
        "best_fidelity": "full",
        "safest_drift": "verified",
        "safely_held": True,
    }


def test_work_custody_safely_held_requires_a_full_representation():
    # the one judgement (H261 spec): a partial copy cannot fully re-derive the work
    # offline, so even a partial+verified rep does NOT make the work safely held —
    # the strong form. best_fidelity reports the partial honestly.
    items = [
        _partial("arxiv:a", "10.1000/x", title="A"),
        _reference("crossref:10.1000/x", "10.1000/x"),
    ]
    custody = _work_custody(items, {"arxiv:a": _verdict("arxiv:a", "unchanged")})
    assert custody["best_fidelity"] == "partial"
    assert custody["safest_drift"] == "verified"
    assert custody["safely_held"] is False  # partial+verified is not "safely held"


def test_work_custody_not_safely_held_when_the_full_copy_drifted():
    # a full copy that has *drifted* is no longer a safe hold (the source moved away
    # from our capture); a verified *partial* sibling does not rescue it (partial
    # can't re-derive). So a work can hold a full form and a verified form yet be
    # unsafe — neither is *both* full and unmoved.
    items = [
        _full("arxiv:a", "10.1000/x", title="A"),
        _partial("biorxiv:10.1101/y", "10.1000/x", title="B"),
    ]
    verdicts = {
        "arxiv:a": _verdict("arxiv:a", "drifted"),
        "biorxiv:10.1101/y": _verdict("biorxiv:10.1101/y", "unchanged"),
    }
    custody = _work_custody(items, verdicts)
    assert custody["best_fidelity"] == "full"  # the full form is still held
    assert custody["safest_drift"] == "verified"  # the partial is verified
    assert custody["safely_held"] is False  # but no single rep is full AND unmoved


def test_work_custody_safely_held_via_an_unverified_full_copy():
    # a never-checked full copy *is* safely held: it is fully re-derivable and there
    # is no evidence the source moved (unverified ∈ the safe set, the M2 honesty —
    # unknown, not confirmed loss). The pure caller (no ledger) is exactly this case.
    items = [_full("arxiv:a", "10.1000/x"), _reference("crossref:10.1000/x", "10.1000/x")]
    custody = _work_custody(items)  # no verdicts → every rep unverified
    assert custody == {
        "best_fidelity": "full",
        "safest_drift": "unverified",
        "safely_held": True,
    }


def test_work_custody_best_and_safest_pick_across_representations():
    # best_fidelity/safest_drift are the best each axis offers anywhere in the work,
    # picked independently: a reference+drifted rep and a partial+verified rep →
    # best fidelity partial (FIDELITY_TIERS order), safest drift verified
    # (DRIFT_POSTURES order). Not safely held (no full rep at all).
    items = [
        _reference("arxiv:a", "10.1000/x", title="A"),
        _partial("biorxiv:10.1101/y", "10.1000/x", title="B"),
    ]
    verdicts = {
        "arxiv:a": _verdict("arxiv:a", "drifted"),
        "biorxiv:10.1101/y": _verdict("biorxiv:10.1101/y", "unchanged"),
    }
    custody = _work_custody(items, verdicts)
    assert custody["best_fidelity"] == "partial"
    assert custody["safest_drift"] == "verified"
    assert custody["safely_held"] is False


def test_work_custody_error_posture_is_not_a_safe_hold():
    # a full copy whose only verdict is `error` is NOT safely held: an error means
    # we *tried and could not confirm* the source is unchanged — weaker than
    # never-checked, so it is excluded from the safe set {verified, unverified}.
    items = [_full("arxiv:a", "10.1000/x"), _reference("crossref:10.1000/x", "10.1000/x")]
    custody = _work_custody(items, {"arxiv:a": _verdict("arxiv:a", "error")})
    assert custody["best_fidelity"] == "full"
    assert custody["safest_drift"] == "unverified"  # the reference rep is unverified
    assert custody["safely_held"] is False


def test_work_custody_matches_the_shared_helper():
    # the payload block is exactly `work_custody(reps, verdicts)` — the one helper
    # H262's filter and H263's at-risk signal reuse (their preconditions), not a
    # re-derivation, so the consolidation rule has a single home.
    from scrolls.works import work_custody

    items = [_full("arxiv:a", "10.1000/x"), _reference("crossref:10.1000/x", "10.1000/x")]
    verdicts = {"arxiv:a": _verdict("arxiv:a", "drifted")}
    (work,) = works_over(items)
    payload = to_payload(
        [work], len(items), scope={"min_representations": 2}, verdicts=verdicts
    )
    assert payload["works"][0]["custody"] == work_custody(
        work.representations, verdicts
    )


# --- work-level content-identity (roadmap H329) ------------------------
# Each work also carries a `content_duplicate` boolean beside its H261 `custody`
# block: True iff ≥2 of its representations hold byte-identical content (the same
# non-null `content_hash`) — a preprint mirrored into a DOI capture, the same body
# under two forms. The consolidation-surface analogue of the whole-library
# `doctor.custody.content_duplicates` report (H325): report-only, never a merge
# (raw is sacred, the H325 no-merge discipline). A pure fold over the reps'
# `content_hash`, with the H325 NULL-skip (a reference-only rep holds no captured
# content, so it fingerprints nothing and never forms a content-duplicate pair).


def _rep(item_id, doi, content_hash):
    """A representation of `doi` holding `content_hash` bytes (None → reference)."""
    return make_item(
        item_id, url=f"https://example.org/{item_id}",
        links=(f"https://doi.org/{doi}",),
        raw_text="body" if content_hash else None,
        content_hash=content_hash, stage="rendered",
    )


def _work_content_duplicate(items):
    """The `content_duplicate` flag of the single work the items form."""
    (work,) = works_over(items)
    payload = to_payload([work], len(items), scope={"min_representations": 2})
    return payload["works"][0]["content_duplicate"]


def test_work_content_duplicate_flags_a_byte_identical_rep_pair():
    # two representations of one work holding the SAME bytes (a preprint mirrored
    # into its DOI capture) → content_duplicate True, the redundancy an operator
    # consolidating the work may want to know
    items = [
        _rep("arxiv:a", "10.1000/x", "sha256:same"),
        _rep("crossref:10.1000/x", "10.1000/x", "sha256:same"),
    ]
    assert _work_content_duplicate(items) is True


def test_work_content_duplicate_false_for_distinct_content():
    # two reps of one work holding DIFFERENT bytes (the normal case: a preprint and
    # its published record differ) → False, not a byte-identical pair
    items = [
        _rep("arxiv:a", "10.1000/x", "sha256:a"),
        _rep("crossref:10.1000/x", "10.1000/x", "sha256:b"),
    ]
    assert _work_content_duplicate(items) is False


def test_work_content_duplicate_false_when_only_one_rep_holds_content():
    # a full rep (content held) + a reference rep (no captured content, NULL hash)
    # is not a byte-identical pair — the H325 NULL-skip: the reference rep
    # fingerprints nothing
    items = [
        _rep("arxiv:a", "10.1000/x", "sha256:a"),
        _rep("crossref:10.1000/x", "10.1000/x", None),
    ]
    assert _work_content_duplicate(items) is False


def test_work_content_duplicate_false_for_two_reference_reps():
    # two reference-only reps (both NULL content_hash) are NOT byte-identical
    # holdings — they hold no bytes; the H325 rule that a NULL hash fingerprints
    # nothing, so two reference reps never form a content-duplicate pair
    items = [
        _rep("arxiv:a", "10.1000/x", None),
        _rep("crossref:10.1000/x", "10.1000/x", None),
    ]
    assert _work_content_duplicate(items) is False


def test_work_content_duplicate_flags_a_pair_among_three_reps():
    # three reps, two sharing bytes and one distinct → still flagged: the byte-
    # identical pair is the redundancy, regardless of the distinct sibling
    items = [
        _rep("arxiv:a", "10.1000/x", "sha256:same"),
        _rep("biorxiv:10.1101/y", "10.1000/x", "sha256:same"),
        _rep("crossref:10.1000/x", "10.1000/x", "sha256:other"),
    ]
    assert _work_content_duplicate(items) is True


def test_work_content_duplicate_helper_is_a_pure_fold_over_reps():
    # the payload flag is exactly `work_content_duplicate(reps)` — a pure fold over
    # the representations' `content_hash` (no schema change), the consolidation-scope
    # analogue of the whole-library `items.content_duplicate_groups` fold (H325)
    from scrolls.works import work_content_duplicate

    items = [
        _rep("arxiv:a", "10.1000/x", "sha256:same"),
        _rep("crossref:10.1000/x", "10.1000/x", "sha256:same"),
    ]
    (work,) = works_over(items)
    assert work_content_duplicate(work.representations) is True
    assert _work_content_duplicate(items) == work_content_duplicate(
        work.representations
    )


# --- H263: the at-risk-works consolidation alarm -----------------------
# `at_risk_signal` is the consolidation-level analogue of the per-source
# weakest-source `attention` flag: a work is *at risk* when NO representation is
# safely held (`work_custody`'s `safely_held == False`), and `most_at_risk` names the
# single lowest-custody-ceiling one. A pure fold over the H261 aggregate.


def test_at_risk_signal_counts_the_works_no_rep_safely_holds():
    from scrolls.works import at_risk_signal

    items, verdicts = _two_work_custody_mix()
    signal = at_risk_signal(works_over(items), verdicts)
    # X (full+drifted, ref+unverified) and Z (all reference) are at risk; Y holds a
    # full+verified rep so it is safely held — 2 of 3 works at risk.
    assert signal["total"] == 3
    assert signal["at_risk"] == 2


def test_at_risk_signal_names_the_lowest_ceiling_work_as_most_at_risk():
    from scrolls.works import at_risk_signal

    items, verdicts = _two_work_custody_mix()
    most = at_risk_signal(works_over(items), verdicts)["most_at_risk"]
    # Z (all-reference, nothing re-derivable held) outranks X (which still holds a
    # full-but-drifted copy): worst best_fidelity wins — content gone, not just moved.
    assert most["doi"] == "10.3000/z"
    assert most["canonical"] == "crossref:cz"  # crossref outranks arxiv (CANONICAL_SOURCE_RANK)
    assert most["representations"] == 2
    assert most["custody"] == {
        "best_fidelity": "reference",
        "safest_drift": "unverified",
        "safely_held": False,
    }
    # self-describing, no fabricated command (no whole-library recapture act exists)
    assert most["reason"] == (
        "no representation is both full and unmoved "
        "(best held reference, safest drift unverified)"
    )
    assert "command" not in most


def test_at_risk_signal_breaks_a_fidelity_tie_by_worst_drift_then_doi():
    from scrolls.works import at_risk_signal

    # two at-risk works, both reference-ceiling: W1's *every* rep drifted (so its
    # safest drift is `drifted`), W2's both unverified. Worst-drift-first → W1 is
    # most at risk; the DOI tiebreak never fires because the drift axis decides.
    items = [
        _reference("arxiv:a", "10.1000/a", title="A"),
        _reference("crossref:ca", "10.1000/a", title="A"),
        _reference("arxiv:b", "10.2000/b", title="B"),
        _reference("crossref:cb", "10.2000/b", title="B"),
    ]
    verdicts = {
        "arxiv:a": _verdict("arxiv:a", "drifted"),
        "crossref:ca": _verdict("crossref:ca", "drifted"),
    }
    most = at_risk_signal(works_over(items), verdicts)["most_at_risk"]
    assert most["doi"] == "10.1000/a"
    assert most["custody"]["safest_drift"] == "drifted"


def test_at_risk_signal_is_empty_when_every_work_is_safely_held():
    from scrolls.works import at_risk_signal

    # two works each with a full+verified rep → none at risk, no work named
    items = [
        _full("arxiv:a", "10.1000/a"), _reference("crossref:ca", "10.1000/a"),
        _full("biorxiv:b", "10.2000/b"), _reference("crossref:cb", "10.2000/b"),
    ]
    verdicts = {
        "arxiv:a": _verdict("arxiv:a", "unchanged"),
        "biorxiv:b": _verdict("biorxiv:b", "unchanged"),
    }
    signal = at_risk_signal(works_over(items), verdicts)
    assert signal == {"total": 2, "at_risk": 0, "most_at_risk": None}


def test_at_risk_signal_unverified_full_copy_is_safe_no_network():
    from scrolls.works import at_risk_signal

    # the pure caller (no ledger): a never-checked full copy is safely held (unverified
    # ∈ the safe set, the M2 honesty), so a work with one is NOT at risk.
    items = [_full("arxiv:a", "10.1000/a"), _reference("crossref:ca", "10.1000/a")]
    signal = at_risk_signal(works_over(items), {})
    assert signal["at_risk"] == 0


def test_at_risk_signal_matches_work_custody_per_work():
    # the alarm is exactly the `safely_held == False` set of the H261 helper — one
    # home for the consolidation rule, not a re-derivation.
    from scrolls.works import at_risk_signal, work_custody

    items, verdicts = _two_work_custody_mix()
    works = works_over(items)
    expected = sum(
        1 for w in works if not work_custody(w.representations, verdicts)["safely_held"]
    )
    assert at_risk_signal(works, verdicts)["at_risk"] == expected


# --- H264: the readable work-level at-risk `_At-risk work:_` line --------
# `render_at_risk_works` is the consolidation-level counterpart of the per-source
# weakest-source `render_custody_attention` line (H159): it distils `at_risk_signal`'s
# `most_at_risk` over the briefing scope's clustered works into one readable line the
# `export bundle`/`scrolls context` briefings emit byte-identically.


def test_render_at_risk_works_names_the_lowest_ceiling_work():
    from scrolls.works import render_at_risk_works

    items, verdicts = _two_work_custody_mix()
    # Z (all-reference) is the lowest-ceiling at-risk work; 2 of 3 works at risk
    # (X full+drifted + Z all-reference; Y holds a full+verified rep).
    assert render_at_risk_works(items, verdicts) == [
        "_At-risk work: `10.3000/z` — no representation is both full and unmoved "
        "(best held reference, safest drift unverified); 2 work(s) at risk._",
        "",
    ]


def test_render_at_risk_works_converges_with_at_risk_signal():
    # the line reuses the same `most_at_risk` (doi + reason) and `at_risk` count the
    # JSON alarm carries, so the readable briefing and `doctor`/`maintain`/MCP name
    # the same work by construction (not a re-derivation).
    from scrolls.works import at_risk_signal, render_at_risk_works

    items, verdicts = _two_work_custody_mix()
    signal = at_risk_signal(works_over(items), verdicts)
    (line, blank) = render_at_risk_works(items, verdicts)
    assert blank == ""
    assert f"`{signal['most_at_risk']['doi']}`" in line
    assert signal["most_at_risk"]["reason"] in line
    assert f"{signal['at_risk']} work(s) at risk" in line


def test_render_at_risk_works_empty_when_every_work_is_safely_held():
    # honest absence — exactly the no-op `at_risk_signal` (most_at_risk None) takes
    from scrolls.works import render_at_risk_works

    items = [
        _full("arxiv:a", "10.1000/a"), _reference("crossref:ca", "10.1000/a"),
        _full("biorxiv:b", "10.2000/b"), _reference("crossref:cb", "10.2000/b"),
    ]
    verdicts = {
        "arxiv:a": _verdict("arxiv:a", "unchanged"),
        "biorxiv:b": _verdict("biorxiv:b", "unchanged"),
    }
    assert render_at_risk_works(items, verdicts) == []


def test_render_at_risk_works_empty_for_a_single_representation_scope():
    # a lone representation is no work (the min_representations floor), so the
    # consolidation question does not apply — honest absence, not a false alarm
    from scrolls.works import render_at_risk_works

    items = [_reference("arxiv:lone", "10.9000/lone", title="Lone")]
    assert render_at_risk_works(items, {}) == []


# --- H262: the custody-filter family on the consolidation surface ------
# `filter_works` keeps WHOLE works that *contain* a representation at the given
# custody value(s) — the cluster "contains" semantics (a work is a set of forms),
# both axes AND on the *same* representation (the ∃-lift of the per-item filter).


def _two_work_custody_mix():
    """Three 2-rep works across a custody spread, for the H262 consolidation filter.

    Sorted by DOI (works_over's stable order, all 2-rep): X, Y, Z.
    - Work X (10.1000/x): a *full* arxiv preprint that has **drifted** + a bare
      *reference* crossref record (unverified).
    - Work Y (10.2000/y): a *full* biorxiv preprint that is **verified**
      (unchanged) + a *partial* pubmed record (unverified).
    - Work Z (10.3000/z): two *reference* records, both unverified — no full
      form anywhere (a work with nothing re-derivable held).
    """
    items = [
        _full("arxiv:x", "10.1000/x", title="X"),
        _reference("crossref:cx", "10.1000/x", title="X"),
        _full("biorxiv:y", "10.2000/y", title="Y"),
        _partial("pubmed:y", "10.2000/y", title="Y"),
        _reference("arxiv:z", "10.3000/z", title="Z"),
        _reference("crossref:cz", "10.3000/z", title="Z"),
    ]
    verdicts = {
        "arxiv:x": _verdict("arxiv:x", "drifted"),
        "biorxiv:y": _verdict("biorxiv:y", "unchanged"),
    }
    return items, verdicts


def _dois(works):
    return [work.doi for work in works]


def test_filter_works_keeps_works_with_a_matching_fidelity_rep():
    items, verdicts = _two_work_custody_mix()
    works = works_over(items)
    # only X and Y hold a full-fidelity representation; Z is all-reference
    assert _dois(filter_works(works, verdicts, fidelity="full")) == [
        "10.1000/x", "10.2000/y"]
    # partial lives only in Y; reference in X and Z
    assert _dois(filter_works(works, verdicts, fidelity="partial")) == ["10.2000/y"]
    assert _dois(filter_works(works, verdicts, fidelity="reference")) == [
        "10.1000/x", "10.3000/z"]


def test_filter_works_keeps_works_with_a_matching_drift_rep():
    items, verdicts = _two_work_custody_mix()
    works = works_over(items)
    # X's preprint drifted; Y's preprint is verified; everything else unverified
    assert _dois(filter_works(works, verdicts, drift="drifted")) == ["10.1000/x"]
    assert _dois(filter_works(works, verdicts, drift="verified")) == ["10.2000/y"]
    # every work carries at least one unverified representation
    assert _dois(filter_works(works, verdicts, drift="unverified")) == [
        "10.1000/x", "10.2000/y", "10.3000/z"]
    # a posture no representation holds → an honest empty set, never an error
    assert filter_works(works, verdicts, drift="rotted") == []


def test_filter_works_keeps_the_whole_work_not_just_the_matching_rep():
    # the cluster "contains" semantics: a work kept for its drifted rep still carries
    # its (non-drifted) sibling, so a reader can see whether a safe form exists.
    items, verdicts = _two_work_custody_mix()
    (kept,) = filter_works(works_over(items), verdicts, drift="drifted")
    # both the matching full+drifted rep AND the non-matching reference sibling travel
    assert [rep.id for rep in kept.representations] == ["arxiv:x", "crossref:cx"]


def test_filter_works_ands_both_axes_on_the_same_representation():
    # Option B (the ∃-lift of the per-item AND): a work is kept iff a SINGLE rep is
    # both. X holds a full+drifted rep and a reference+unverified rep.
    items, verdicts = _two_work_custody_mix()
    works = works_over(items)
    # full AND drifted → X (arxiv:x is both); full AND verified → Y (biorxiv:y is both)
    assert _dois(filter_works(works, verdicts, fidelity="full", drift="drifted")) == [
        "10.1000/x"]
    assert _dois(filter_works(works, verdicts, fidelity="full", drift="verified")) == [
        "10.2000/y"]
    # reference AND drifted → EMPTY, though X *contains* a reference rep AND a drifted
    # rep — no single rep is both (a contains-per-axis "Option A" would wrongly keep X)
    assert filter_works(works, verdicts, fidelity="reference", drift="drifted") == []


def test_filter_works_unfiltered_is_identity_without_a_ledger():
    works = works_over(_two_work_custody_mix()[0])
    # both axes None → the input list unchanged, and no ledger read needed
    assert filter_works(works) is works


def test_filter_works_rejects_an_unknown_fidelity_tier():
    works = works_over(_two_work_custody_mix()[0])
    with pytest.raises(ValueError, match="unknown fidelity tier"):
        filter_works(works, fidelity="gold")


def test_filter_works_rejects_an_unknown_drift_posture():
    works = works_over(_two_work_custody_mix()[0])
    with pytest.raises(ValueError, match="unknown drift posture"):
        filter_works(works, drift="moved")


# --- H265: the at-risk browse predicate on the consolidation surface ----
# `filter_works(at_risk=True)` keeps the works NO representation safely holds — the
# H261 `work_custody` `safely_held == False` set the H263 alarm counts. It is a
# genuinely new predicate (the negation of ∃(full ∧ safe)), NOT a single
# fidelity/drift value, and ANDs with the per-rep contains-filters.


def test_filter_works_at_risk_keeps_the_unsafely_held_works():
    items, verdicts = _two_work_custody_mix()
    works = works_over(items)
    # X (full+drifted, no full-and-unmoved rep) and Z (all-reference) are at risk;
    # Y holds a full+verified rep → safely held, dropped
    assert _dois(filter_works(works, verdicts, at_risk=True)) == [
        "10.1000/x", "10.3000/z"]


def test_filter_works_at_risk_matches_the_at_risk_signal_set():
    # the predicate is exactly H263's `safely_held == False` set — one rule, two reads
    from scrolls.works import at_risk_signal, work_custody

    items, verdicts = _two_work_custody_mix()
    works = works_over(items)
    expected = [
        w.doi
        for w in works
        if not work_custody(w.representations, verdicts)["safely_held"]
    ]
    assert _dois(filter_works(works, verdicts, at_risk=True)) == expected
    assert len(expected) == at_risk_signal(works, verdicts)["at_risk"]


def test_filter_works_at_risk_keeps_the_whole_work_not_just_a_loss():
    # the cluster "contains" shape: an at-risk work travels with every rep, so a reader
    # sees the (degraded/moved) forms it does hold — here X's drifted full preprint AND
    # its bare reference sibling
    items, verdicts = _two_work_custody_mix()
    kept = filter_works(works_over(items), verdicts, at_risk=True)
    x = next(w for w in kept if w.doi == "10.1000/x")
    assert [rep.id for rep in x.representations] == ["arxiv:x", "crossref:cx"]


def test_filter_works_at_risk_ands_with_the_per_rep_filters():
    # `at_risk` ANDs with the contains-filters. at-risk AND holds a full rep → X only
    # (the recapture candidate: content in hand but the work is at risk); Z is at risk
    # but all-reference, so it drops under --fidelity full.
    items, verdicts = _two_work_custody_mix()
    works = works_over(items)
    assert _dois(filter_works(works, verdicts, at_risk=True, fidelity="full")) == [
        "10.1000/x"]
    # at-risk AND has a drifted rep → X (Z is at risk but has no drifted rep)
    assert _dois(filter_works(works, verdicts, at_risk=True, drift="drifted")) == [
        "10.1000/x"]
    # at-risk AND has a verified rep → empty: the only verified rep is Y's, and Y is
    # safely held, so it is not in the at-risk set at all
    assert filter_works(works, verdicts, at_risk=True, drift="verified") == []


def test_filter_works_at_risk_false_is_the_unfiltered_identity():
    works = works_over(_two_work_custody_mix()[0])
    # at_risk defaults False; with no other axis it is the input list unchanged, no
    # ledger read needed (the H262 identity, now guarding the `not at_risk` early exit)
    assert filter_works(works, at_risk=False) is works


# --- H344: the content-identity browse predicate on the consolidation surface ----
# `filter_works(content_duplicate=True)` keeps the works that hold the SAME bytes under
# two representations — the H329 `work_content_duplicate` flag (≥2 reps share a non-null
# `content_hash`) turned into a sieve, the consolidation analogue of `list
# --content-duplicate` (H338). Within-work scope (a work is kept iff its own forms
# duplicate each other), a boolean property reading no ledger, ANDing with the per-rep
# contains-filters and `at_risk`.


def _content_dup_work_mix():
    """Works spread across the content-identity axis, for the H344 browse filter.

    works_over orders by (-representations, doi):
    - Work B (10.2000/b, 3 reps, first): two *full* reps holding the SAME bytes
      (sha256:dupB) + a *reference* rep → content_duplicate, and it also holds a
      reference form (for the --fidelity composition).
    - Work A (10.1000/a, 2 reps): two *full* reps holding the SAME bytes (sha256:dupA)
      → content_duplicate, both full, no reference rep.
    - Work C (10.3000/c, 2 reps): two *full* reps holding DIFFERENT bytes → NOT a
      content duplicate (the normal preprint-vs-published case).
    """
    return [
        _rep("arxiv:a", "10.1000/a", "sha256:dupA"),
        _rep("crossref:ca", "10.1000/a", "sha256:dupA"),
        _rep("arxiv:b", "10.2000/b", "sha256:dupB"),
        _rep("biorxiv:b", "10.2000/b", "sha256:dupB"),
        _rep("crossref:cb", "10.2000/b", None),  # reference-only form
        _rep("arxiv:c", "10.3000/c", "sha256:c1"),
        _rep("crossref:cc", "10.3000/c", "sha256:c2"),
    ]


def test_filter_works_content_duplicate_keeps_only_byte_identical_works():
    works = works_over(_content_dup_work_mix())
    # B (3 reps, full pair shares bytes) and A (2 reps, full pair shares bytes) are kept;
    # C (distinct bytes) drops out — works_over's (-reps, doi) order is B then A
    assert _dois(filter_works(works, content_duplicate=True)) == [
        "10.2000/b", "10.1000/a"]


def test_filter_works_content_duplicate_drops_distinct_and_single_holder():
    # the H329 fold's two falses: a work whose reps hold DIFFERENT bytes (C), and a work
    # where only one rep holds content (a full + a reference rep, the NULL-skip) — neither
    # is a byte-identical pair. A two-rep mix of one full + one reference is dropped.
    items = [
        _rep("arxiv:c", "10.3000/c", "sha256:c1"),
        _rep("crossref:cc", "10.3000/c", "sha256:c2"),  # distinct bytes
        _rep("arxiv:d", "10.4000/d", "sha256:d"),
        _rep("crossref:cd", "10.4000/d", None),  # only one rep holds content
    ]
    assert filter_works(works_over(items), content_duplicate=True) == []


def test_filter_works_content_duplicate_ands_with_the_per_rep_filters():
    # `content_duplicate` ANDs with the contains-filters. Among the two duplicate works
    # (B, A), only B holds a reference rep, so --fidelity reference narrows to B; both
    # hold full reps, so --fidelity full keeps both.
    works = works_over(_content_dup_work_mix())
    assert _dois(filter_works(works, content_duplicate=True, fidelity="reference")) == [
        "10.2000/b"]
    assert _dois(filter_works(works, content_duplicate=True, fidelity="full")) == [
        "10.2000/b", "10.1000/a"]


def test_filter_works_content_duplicate_drills_the_unfiltered_flag():
    # the drill-from-the-flag tie (the `works --at-risk`↔`safely_held` precedent): the
    # works kept by content_duplicate=True are EXACTLY the works whose `content_duplicate`
    # flag reads true in an unfiltered listing — one rule, two reads.
    from scrolls.works import work_content_duplicate

    items = _content_dup_work_mix()
    works = works_over(items)
    flagged = [w.doi for w in works if work_content_duplicate(w.representations)]
    assert _dois(filter_works(works, content_duplicate=True)) == flagged
    # and it agrees with the rendered payload flag (the same fold to_payload carries)
    payload = to_payload(works, len(items), scope={"min_representations": 2})
    assert [w["doi"] for w in payload["works"] if w["content_duplicate"]] == flagged


def test_filter_works_content_duplicate_false_is_the_unfiltered_identity():
    works = works_over(_content_dup_work_mix())
    # content_duplicate defaults False; with no other axis it returns the input unchanged,
    # no ledger read (the H262 identity, now also guarding the content-duplicate early exit)
    assert filter_works(works, content_duplicate=False) is works


def _seed_two_work_custody_mix(db):
    """Insert the three-work custody mix into a real library (the CLI/MCP seed)."""
    from scrolls.custody import record_events

    items, verdicts = _two_work_custody_mix()
    for item in items:
        insert_item(db, item)
    record_events(db, list(verdicts.values()))


def _seed_content_dup_work_mix(db):
    """Insert the content-identity work mix into a real library (the H344 CLI seed)."""
    for item in _content_dup_work_mix():
        insert_item(db, item)


# --- CLI ---------------------------------------------------------------


def test_cli_works_reports_clusters(db, capsys):
    insert_item(db, make_item(
        "arxiv:1706.03762",
        url="https://arxiv.org/abs/1706.03762",
        title="Attention Is All You Need",
        links=("https://doi.org/10.5555/3295222",),
    ))
    insert_item(db, make_item(
        "crossref:10.5555/3295222",
        url="https://doi.org/10.5555/3295222",
        title="Attention Is All You Need",
        stage="rendered",
    ))

    assert main(["works"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert _core_stats(payload["stats"]) == {"items": 2, "works": 1}
    work = payload["works"][0]
    assert work["doi"] == "10.5555/3295222"
    assert work["url"] == "https://doi.org/10.5555/3295222"
    assert [r["id"] for r in work["representations"]] == [
        "arxiv:1706.03762",
        "crossref:10.5555/3295222",
    ]
    assert work["representations"][0] == {
        "id": "arxiv:1706.03762",
        "source": "arxiv",
        "title": "Attention Is All You Need",
        "url": "https://arxiv.org/abs/1706.03762",
        "stage": "fetched",
        # no body held for this representation — a bare reference (ADR 0100)
        "fidelity": "reference",
        # never re-checked against its source — the honest never-verified posture
        "drift": "unverified",
        # …so no timestamp to report (H87, the time-axis null counterpart)
        "last_checked": None,
    }
    # the canonical representation is named by id (the published record, here)
    assert work["canonical"] == "crossref:10.5555/3295222"


def test_cli_works_representation_drift_matches_the_list_row(db, capsys):
    # H64 per-item parity: the drift a `works` representation shows for an item is
    # exactly the drift its `list` row shows — same `drift_posture`/`latest_events`
    from scrolls.custody import CustodyEvent, record_events

    insert_item(db, make_item(
        "arxiv:1706.03762", url="https://arxiv.org/abs/1706.03762",
        links=("https://doi.org/10.1000/x",),
        raw_text="the preprint body", content_hash="sha256:a", stage="rendered"))
    insert_item(db, make_item(
        "crossref:10.1000/x", url="https://doi.org/10.1000/x", stage="rendered"))
    record_events(db, [CustodyEvent(
        item_id="arxiv:1706.03762", checked_at="2026-06-14T00:00:00+00:00",
        status="drifted", prior_hash="sha256:a", observed_hash="sha256:b")])

    assert main(["works"]) == 0
    reps = {
        r["id"]: r
        for r in json.loads(capsys.readouterr().out)["works"][0]["representations"]
    }
    assert main(["list"]) == 0
    rows = {r["id"]: r for r in json.loads(capsys.readouterr().out)}

    for item_id in ("arxiv:1706.03762", "crossref:10.1000/x"):
        assert reps[item_id]["drift"] == rows[item_id]["drift"]
    assert reps["arxiv:1706.03762"]["drift"] == "drifted"
    assert reps["crossref:10.1000/x"]["drift"] == "unverified"


def test_cli_works_representation_last_checked_matches_the_list_row(db, capsys):
    # H87 per-item parity: the last_checked a `works` representation shows for an
    # item is exactly the timestamp its `list` row shows — same `last_checked`/
    # `latest_events`, the time-axis sibling of the H64 drift parity.
    from scrolls.custody import CustodyEvent, record_events

    insert_item(db, make_item(
        "arxiv:1706.03762", url="https://arxiv.org/abs/1706.03762",
        links=("https://doi.org/10.1000/x",),
        raw_text="the preprint body", content_hash="sha256:a", stage="rendered"))
    insert_item(db, make_item(
        "crossref:10.1000/x", url="https://doi.org/10.1000/x", stage="rendered"))
    record_events(db, [CustodyEvent(
        item_id="arxiv:1706.03762", checked_at="2026-06-14T00:00:00+00:00",
        status="drifted", prior_hash="sha256:a", observed_hash="sha256:b")])

    assert main(["works"]) == 0
    reps = {
        r["id"]: r
        for r in json.loads(capsys.readouterr().out)["works"][0]["representations"]
    }
    assert main(["list"]) == 0
    rows = {r["id"]: r for r in json.loads(capsys.readouterr().out)}

    for item_id in ("arxiv:1706.03762", "crossref:10.1000/x"):
        assert reps[item_id]["last_checked"] == rows[item_id]["last_checked"]
    assert reps["arxiv:1706.03762"]["last_checked"] == "2026-06-14T00:00:00+00:00"
    assert reps["crossref:10.1000/x"]["last_checked"] is None


def test_cli_works_carries_the_aggregate_custody_block(db, capsys):
    # H261 end to end: each work's `custody` block consolidates the fidelity/drift
    # the rendered representation entries carry — the work-level "safely held?"
    # verdict, derived from the same per-rep fields by construction.
    from scrolls.custody import CustodyEvent, record_events

    insert_item(db, make_item(
        "arxiv:1706.03762", url="https://arxiv.org/abs/1706.03762",
        links=("https://doi.org/10.1000/x",),
        raw_text="the preprint body", content_hash="sha256:a", stage="rendered"))
    insert_item(db, make_item(
        "crossref:10.1000/x", url="https://doi.org/10.1000/x", stage="rendered"))
    # the full preprint is re-checked and unchanged → the work is safely held by it
    record_events(db, [CustodyEvent(
        item_id="arxiv:1706.03762", checked_at="2026-06-14T00:00:00+00:00",
        status="unchanged", prior_hash="sha256:a", observed_hash="sha256:a")])

    assert main(["works"]) == 0
    work = json.loads(capsys.readouterr().out)["works"][0]
    assert work["custody"] == {
        "best_fidelity": "full",
        "safest_drift": "verified",
        "safely_held": True,
    }
    # the block folds exactly the rep entries it is rendered beside (parity)
    reps = work["representations"]
    assert {r["fidelity"] for r in reps} == {"full", "reference"}
    assert work["custody"]["best_fidelity"] == "full"


def test_cli_works_min_flag(db, capsys):
    insert_item(db, make_item(
        "arxiv:1706.03762",
        url="https://arxiv.org/abs/1706.03762",
        links=("https://doi.org/10.5555/3295222",),
    ))

    assert main(["works"]) == 0
    assert json.loads(capsys.readouterr().out)["works"] == []

    assert main(["works", "--min", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [w["doi"] for w in payload["works"]] == ["10.5555/3295222"]
    assert _core_stats(payload["stats"]) == {"items": 1, "works": 1}


def test_cli_works_empty_library(scrolls_home, capsys):
    assert main(["works"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "scope": {"min_representations": 2},
        "works": [],
        "stats": {"items": 0, "works": 0, "custody": ZERO_CUSTODY},
    }


# --- H262 CLI: `scrolls works --fidelity` / `--drift` ----------------------


def test_cli_works_filters_by_fidelity_tier(db, capsys):
    _seed_two_work_custody_mix(db)
    assert main(["works", "--fidelity", "full"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # only X and Y hold a full-fidelity representation; Z (all-reference) drops out
    assert [work["doi"] for work in payload["works"]] == ["10.1000/x", "10.2000/y"]
    # the scope echoes the filter so a reader holding only the payload recovers it (G2)
    assert payload["scope"] == {"min_representations": 2, "fidelity": "full"}
    # stats.custody honors the filter: it tallies only the two kept works' (whole)
    # representations — the full + their non-matching reference/partial siblings
    assert payload["stats"]["works"] == 2
    assert payload["stats"]["custody"]["tiers"] == {
        "full": 2, "partial": 1, "reference": 1}


def test_cli_works_filters_by_drift_posture(db, capsys):
    _seed_two_work_custody_mix(db)
    assert main(["works", "--drift", "drifted"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # only work X has a drifted representation — the work needing a recapture decision
    assert [work["doi"] for work in payload["works"]] == ["10.1000/x"]
    # the whole work travels: the drifted preprint AND its reference sibling
    assert [r["id"] for r in payload["works"][0]["representations"]] == [
        "arxiv:x", "crossref:cx"]
    assert payload["scope"] == {"min_representations": 2, "drift": "drifted"}


def test_cli_works_ands_both_custody_axes(db, capsys):
    _seed_two_work_custody_mix(db)
    # full AND verified on the same rep → work Y only
    assert main(["works", "--fidelity", "full", "--drift", "verified"]) == 0
    assert [w["doi"] for w in json.loads(capsys.readouterr().out)["works"]] == [
        "10.2000/y"]
    # reference AND drifted → empty: X contains both values, but in different reps
    assert main(["works", "--fidelity", "reference", "--drift", "drifted"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["works"] == []
    assert payload["scope"] == {
        "min_representations": 2, "fidelity": "reference", "drift": "drifted"}


def test_cli_works_unfiltered_scope_omits_the_custody_filters(db, capsys):
    _seed_two_work_custody_mix(db)
    assert main(["works"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # None filters are pruned from the scope echo — the lean unfiltered shape
    assert payload["scope"] == {"min_representations": 2}
    assert [w["doi"] for w in payload["works"]] == [
        "10.1000/x", "10.2000/y", "10.3000/z"]


def test_cli_works_rejects_an_unknown_fidelity_via_exit_2(db):
    # the closed vocabulary is enforced by argparse `choices=` → exit 2, before the
    # command runs (the H252/H254 precedent for an act/relationship surface)
    with pytest.raises(SystemExit) as exc:
        main(["works", "--fidelity", "gold"])
    assert exc.value.code == 2


def test_cli_works_filter_composes_with_the_per_item_ref_lens(db, capsys):
    # the filter rides the per-item lens too: `works <id> --drift drifted` answers
    # "is the work this item represents one with a drifted rep?"
    _seed_two_work_custody_mix(db)
    # arxiv:x's work X has a drifted rep → kept, with the anchor echoed beside the filter
    assert main(["works", "arxiv:x", "--drift", "drifted"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [w["doi"] for w in payload["works"]] == ["10.1000/x"]
    assert payload["scope"] == {"ref": "arxiv:x", "drift": "drifted"}
    # biorxiv:y's work Y has no drifted rep → empty (an explicit "not at this posture")
    assert main(["works", "biorxiv:y", "--drift", "drifted"]) == 0
    assert json.loads(capsys.readouterr().out)["works"] == []


# --- H265: `scrolls works --at-risk` browse predicate --------------------


def test_cli_works_at_risk_browses_the_unsafely_held_works(db, capsys):
    _seed_two_work_custody_mix(db)
    assert main(["works", "--at-risk"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # X (full+drifted, no full-and-unmoved rep) and Z (all-reference) are at risk;
    # Y (full+verified) is safely held and drops out
    assert [w["doi"] for w in payload["works"]] == ["10.1000/x", "10.3000/z"]
    # the boolean predicate rides the scope echo, present only when set (G2)
    assert payload["scope"] == {"min_representations": 2, "at_risk": True}
    # stats.custody partitions exactly the kept set — the two at-risk works' (whole)
    # representations: X's full preprint + its reference sibling, Z's two references
    assert payload["stats"]["works"] == 2
    assert payload["stats"]["custody"]["tiers"] == {
        "full": 1, "partial": 0, "reference": 3}


def test_cli_works_at_risk_omits_the_flag_from_scope_when_unset(db, capsys):
    _seed_two_work_custody_mix(db)
    assert main(["works"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # unset → pruned from the scope echo (the lean unfiltered shape), and every work
    # is reported (the at-risk Y, X, Z all travel)
    assert "at_risk" not in payload["scope"]
    assert payload["scope"] == {"min_representations": 2}


def test_cli_works_at_risk_ands_with_the_custody_filters(db, capsys):
    _seed_two_work_custody_mix(db)
    # at-risk AND holds a full rep → X only (the recapture candidate: content in hand,
    # but its full copy drifted so the work is at risk); Z is at risk but all-reference
    assert main(["works", "--at-risk", "--fidelity", "full"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [w["doi"] for w in payload["works"]] == ["10.1000/x"]
    assert payload["scope"] == {
        "min_representations": 2, "fidelity": "full", "at_risk": True}


def test_cli_works_at_risk_composes_with_the_per_item_ref_lens(db, capsys):
    _seed_two_work_custody_mix(db)
    # arxiv:x's work X is at risk → kept, anchor echoed beside the predicate
    assert main(["works", "arxiv:x", "--at-risk"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [w["doi"] for w in payload["works"]] == ["10.1000/x"]
    assert payload["scope"] == {"ref": "arxiv:x", "at_risk": True}
    # biorxiv:y's work Y is safely held → empty (an explicit "this work is not at risk")
    assert main(["works", "biorxiv:y", "--at-risk"]) == 0
    assert json.loads(capsys.readouterr().out)["works"] == []


# --- H344: `scrolls works --content-duplicate` browse predicate ----------


def test_cli_works_content_duplicate_browses_the_byte_identical_works(db, capsys):
    _seed_content_dup_work_mix(db)
    assert main(["works", "--content-duplicate"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # B (3 reps, full pair shares bytes) and A (2 reps, full pair shares bytes) are kept;
    # C (distinct bytes) drops out — works_over's (-reps, doi) order is B then A
    assert [w["doi"] for w in payload["works"]] == ["10.2000/b", "10.1000/a"]
    # each kept work's content_duplicate flag reads true (the drill-from-the-flag tie)
    assert all(w["content_duplicate"] for w in payload["works"])
    # the boolean predicate rides the scope echo, present only when set (G2)
    assert payload["scope"] == {"min_representations": 2, "content_duplicate": True}
    # stats.custody partitions exactly the kept set — B's two full + reference siblings
    # and A's two full reps (5 reps across the two kept works)
    assert payload["stats"]["works"] == 2
    assert payload["stats"]["custody"]["tiers"] == {
        "full": 4, "partial": 0, "reference": 1}


def test_cli_works_content_duplicate_omits_the_flag_from_scope_when_unset(db, capsys):
    _seed_content_dup_work_mix(db)
    assert main(["works"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # unset → pruned from the scope echo (the lean unfiltered shape); every work travels
    assert "content_duplicate" not in payload["scope"]
    assert payload["scope"] == {"min_representations": 2}
    assert [w["doi"] for w in payload["works"]] == [
        "10.2000/b", "10.1000/a", "10.3000/c"]


def test_cli_works_content_duplicate_ands_with_the_custody_filters(db, capsys):
    _seed_content_dup_work_mix(db)
    # content-duplicate AND holds a reference rep → B only (A is a pure full pair);
    # the within-work + fidelity axes AND on the kept works
    assert main(["works", "--content-duplicate", "--fidelity", "reference"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [w["doi"] for w in payload["works"]] == ["10.2000/b"]
    assert payload["scope"] == {
        "min_representations": 2, "fidelity": "reference", "content_duplicate": True}


def test_cli_works_content_duplicate_composes_with_the_per_item_ref_lens(db, capsys):
    _seed_content_dup_work_mix(db)
    # arxiv:a's work A holds a byte-identical pair → kept, anchor echoed beside the flag
    assert main(["works", "arxiv:a", "--content-duplicate"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [w["doi"] for w in payload["works"]] == ["10.1000/a"]
    assert payload["scope"] == {"ref": "arxiv:a", "content_duplicate": True}
    # arxiv:c's work C holds distinct bytes → empty (an explicit "no byte-identical pair")
    assert main(["works", "arxiv:c", "--content-duplicate"]) == 0
    assert json.loads(capsys.readouterr().out)["works"] == []


# --- the stats.custody tally (roadmap H100) -------------------------------


def test_stats_custody_tallies_the_reported_works_representations():
    # H100: the works stats block carries a `custody` member — the shared
    # `tally_custody` over the reported works' representations, the same
    # `(fidelity, drift)` pairs each rep entry exposes (the works-surface member
    # of the stats.custody family, beside browse --stats and graph stats).
    from scrolls.custody import CustodyEvent
    from scrolls.works import works_over

    items = [
        # a full-fidelity preprint, drifted at its last verify
        make_item("arxiv:1706.03762", url="https://arxiv.org/abs/1706.03762",
                  links=("https://doi.org/10.1000/x",),
                  raw_text="body", content_hash="sha256:a", stage="rendered"),
        # its published record, a bare reference, never re-checked
        make_item("crossref:10.1000/x", url="https://doi.org/10.1000/x",
                  stage="rendered"),
    ]
    works = works_over(items)
    verdicts = {
        "arxiv:1706.03762": CustodyEvent(
            item_id="arxiv:1706.03762", checked_at="2026-06-14T00:00:00+00:00",
            status="drifted", prior_hash="sha256:a", observed_hash="sha256:b"),
    }
    custody = to_payload(works, len(items), scope={"min_representations": 2},
                         verdicts=verdicts)["stats"]["custody"]
    # one full+drifted preprint, one reference+unverified published record
    assert custody["tiers"] == {"full": 1, "partial": 0, "reference": 1}
    assert custody["drift"] == {
        "verified": 0, "unverified": 1, "drifted": 1, "rotted": 0, "error": 0}


def test_stats_custody_totals_equal_the_reported_representation_entries():
    # the tally sums to the number of representation entries rendered, so a
    # reader can trust it describes exactly the works the payload shows
    from scrolls.works import works_over

    items = [
        make_item("arxiv:1706.03762", url="https://arxiv.org/abs/1706.03762",
                  links=("https://doi.org/10.1000/x",)),
        make_item("crossref:10.1000/x", url="https://doi.org/10.1000/x"),
        make_item("arxiv:2001.0", url="https://arxiv.org/abs/2001.0",
                  links=("https://doi.org/10.1000/y",)),
        make_item("crossref:10.1000/y", url="https://doi.org/10.1000/y"),
    ]
    works = works_over(items)
    payload = to_payload(works, len(items), scope={"min_representations": 2})
    rep_entries = sum(len(w["representations"]) for w in payload["works"])
    custody = payload["stats"]["custody"]
    assert rep_entries == 4
    assert sum(custody["tiers"].values()) == rep_entries
    assert sum(custody["drift"].values()) == rep_entries


def test_stats_custody_counts_a_two_work_item_per_representation_entry():
    # an item that represents two works is rendered as a representation in both;
    # the tally is over representation entries, so it is counted in both — its
    # totals stay equal to the rendered entries (no silent dedup)
    from scrolls.works import works_over

    # `shared` names two DOIs, so it is a representation of two works
    items = [
        make_item("arxiv:shared", url="https://arxiv.org/abs/shared",
                  links=("https://doi.org/10.1000/x", "https://doi.org/10.1000/y")),
        make_item("crossref:10.1000/x", url="https://doi.org/10.1000/x"),
        make_item("crossref:10.1000/y", url="https://doi.org/10.1000/y"),
    ]
    works = works_over(items)
    payload = to_payload(works, len(items), scope={"min_representations": 2})
    rep_entries = sum(len(w["representations"]) for w in payload["works"])
    custody = payload["stats"]["custody"]
    # two works of two reps each = four representation entries (shared in both)
    assert rep_entries == 4
    assert sum(custody["tiers"].values()) == rep_entries
    # all four reps are bare references, never re-checked
    assert custody["tiers"]["reference"] == 4
    assert custody["drift"]["unverified"] == 4


def test_stats_custody_is_zeroed_when_no_work_is_reported():
    # nothing clears the floor → no representations → the honest zeroed shape,
    # not an absent key (a stable shape a renderer can filter)
    from scrolls.works import works_over

    items = [make_item("arxiv:solo", url="https://arxiv.org/abs/solo",
                       links=("https://doi.org/10.1000/x",))]
    works = works_over(items)  # one-rep work, below the default floor of 2
    payload = to_payload(works, len(items), scope={"min_representations": 2})
    assert payload["works"] == []
    assert payload["stats"]["custody"] == ZERO_CUSTODY


def test_cli_works_stats_custody_member_matches_the_rendered_reps(db, capsys):
    # end to end through the CLI: the stats.custody tally equals the fidelity/
    # drift each rendered representation entry carries (parity by construction)
    from scrolls.custody import (
        CustodyEvent,
        record_events,
        tally_custody_by_source,
        weakest_source,
    )

    insert_item(db, make_item(
        "arxiv:1706.03762", url="https://arxiv.org/abs/1706.03762",
        links=("https://doi.org/10.1000/x",),
        raw_text="the preprint body", content_hash="sha256:a", stage="rendered"))
    insert_item(db, make_item(
        "crossref:10.1000/x", url="https://doi.org/10.1000/x", stage="rendered"))
    record_events(db, [CustodyEvent(
        item_id="arxiv:1706.03762", checked_at="2026-06-14T00:00:00+00:00",
        status="drifted", prior_hash="sha256:a", observed_hash="sha256:b")])

    assert main(["works"]) == 0
    payload = json.loads(capsys.readouterr().out)
    reps = [r for w in payload["works"] for r in w["representations"]]
    expected = {"tiers": {"full": 0, "partial": 0, "reference": 0},
                "drift": {p: 0 for p in
                          ("verified", "unverified", "drifted", "rotted", "error")},
                "by_source": {}}
    for rep in reps:
        expected["tiers"][rep["fidelity"]] += 1
        expected["drift"][rep["drift"]] += 1
    # the per-source split (roadmap H155): the same reps grouped by source — this
    # seed spans two (`arxiv` preprint + `crossref` published record)
    expected["by_source"] = tally_custody_by_source(
        (rep["source"], rep["fidelity"], rep["drift"]) for rep in reps)
    # the weakest-source flag (roadmap H174): distilled from the lean `by_source`,
    # so it carries no per-source coverage (`include_coverage=False`) — the arxiv
    # preprint drifted, so `arxiv` is the flagged source here
    expected["attention"] = weakest_source(expected["by_source"], include_coverage=False)
    # the at-risk-works summary (roadmap H266): the shared `at_risk_signal` fold over
    # the reported works — the one work here is at risk (its full copy drifted, no
    # safely-held rep), so the summary names it
    from scrolls.custody import latest_events
    from scrolls.items import list_items
    from scrolls.works import at_risk_signal

    expected["at_risk"] = at_risk_signal(
        works_over(list_items(db)), latest_events(db))
    assert payload["stats"]["custody"] == expected
    assert set(expected["by_source"]) == {"arxiv", "crossref"}  # genuinely multi-source
    # the flag names the drifted source and carries no fabricated coverage
    assert expected["attention"]["source"] == "arxiv"
    assert "coverage" not in expected["attention"]
    # the at-risk summary names the lone at-risk work (the full copy drifted)
    assert expected["at_risk"]["at_risk"] == 1


def test_stats_custody_attention_is_null_single_source():
    # roadmap H174: the works `stats.custody.attention` flag is honestly `null` when
    # the reported works span a single source — `attention` only discriminates across
    # sources (the `weakest_source` single-source gate), even with drift in scope.
    from scrolls.works import works_over

    # two arxiv preprints sharing one DOI → a single-source two-rep work
    items = [
        make_item("arxiv:a", url="https://arxiv.org/abs/a",
                  links=("https://doi.org/10.1000/x",),
                  raw_text="<r>", content_hash="sha256:a", stage="rendered"),
        make_item("arxiv:b", url="https://arxiv.org/abs/b",
                  links=("https://doi.org/10.1000/x",),
                  raw_text="<r>", content_hash="sha256:b", stage="rendered"),
    ]
    works = works_over(items)
    payload = to_payload(works, len(items), scope={"min_representations": 2})
    custody = payload["stats"]["custody"]
    assert set(custody["by_source"]) == {"arxiv"}  # single source
    assert custody["attention"] is None


# --- H266: the works stats carry a scope-level at-risk-works summary -------
# `stats.custody.at_risk` is the works-surface counterpart of the
# `doctor`/`maintain`/`get_library_health` at-risk-works alarm (H263): the
# `at_risk_signal` fold over the *reported* works, beside `attention` in the same
# `stats.custody` loss-summary family. A reader of any `works` payload sees "N of the
# reported works are at risk; worst is `<doi>`" without a second `doctor` call.


def test_stats_custody_at_risk_summarizes_the_reported_works():
    # the works `stats.custody.at_risk` is exactly the `at_risk_signal` fold over the
    # reported works — same {total, at_risk, most_at_risk} the H263 alarm reads.
    from scrolls.works import at_risk_signal

    items, verdicts = _two_work_custody_mix()
    works = works_over(items)
    payload = to_payload(
        works, len(items), scope={"min_representations": 2}, verdicts=verdicts
    )
    at_risk = payload["stats"]["custody"]["at_risk"]
    assert at_risk == at_risk_signal(works, verdicts)
    # X (full+drifted, ref) and Z (all reference) are at risk; Y holds a full+verified
    # rep so it is safely held → 2 of 3 works at risk, Z the lowest-ceiling worst.
    assert at_risk["total"] == 3
    assert at_risk["at_risk"] == 2
    assert at_risk["most_at_risk"]["doi"] == "10.3000/z"


def test_stats_custody_at_risk_total_equals_the_reported_works_count():
    # `at_risk.total` is the reported-works count, equal to `stats.works` beside it by
    # construction (both fold over the same reported list) — a coherence invariant.
    items, verdicts = _two_work_custody_mix()
    works = works_over(items)
    payload = to_payload(
        works, len(items), scope={"min_representations": 2}, verdicts=verdicts
    )
    assert payload["stats"]["custody"]["at_risk"]["total"] == payload["stats"]["works"]


def test_stats_custody_at_risk_is_zeroed_when_no_work_is_reported():
    # nothing clears the floor → no works → the honest zeroed fold, not an absent key
    items = [make_item("arxiv:solo", url="https://arxiv.org/abs/solo",
                       links=("https://doi.org/10.1000/x",))]
    works = works_over(items)  # one-rep work, below the default floor of 2
    payload = to_payload(works, len(items), scope={"min_representations": 2})
    assert payload["stats"]["custody"]["at_risk"] == {
        "total": 0, "at_risk": 0, "most_at_risk": None,
    }


def test_stats_custody_at_risk_is_empty_when_every_work_is_safely_held():
    # every work holds a full+verified rep → none at risk, no work named (the
    # honest no-op the H263 alarm takes), even though the works are reported.
    items = [
        _full("arxiv:a", "10.1000/a"), _reference("crossref:ca", "10.1000/a"),
        _full("biorxiv:b", "10.2000/b"), _reference("crossref:cb", "10.2000/b"),
    ]
    verdicts = {
        "arxiv:a": _verdict("arxiv:a", "unchanged"),
        "biorxiv:b": _verdict("biorxiv:b", "unchanged"),
    }
    works = works_over(items)
    payload = to_payload(
        works, len(items), scope={"min_representations": 2}, verdicts=verdicts
    )
    at_risk = payload["stats"]["custody"]["at_risk"]
    assert at_risk == {"total": 2, "at_risk": 0, "most_at_risk": None}


def test_stats_custody_at_risk_composes_with_the_at_risk_filter():
    # H265 composition: under `--at-risk` every reported work is at risk, so the
    # summary reads `at_risk == total` — honest, the kept set IS the at-risk set.
    from scrolls.works import filter_works

    items, verdicts = _two_work_custody_mix()
    kept = filter_works(works_over(items), verdicts, at_risk=True)
    payload = to_payload(
        kept, len(items), scope={"min_representations": 2, "at_risk": True},
        verdicts=verdicts,
    )
    at_risk = payload["stats"]["custody"]["at_risk"]
    assert at_risk["total"] == at_risk["at_risk"] == 2  # X + Z, no safely-held Y


def test_stats_custody_at_risk_composes_with_the_fidelity_filter():
    # H262 composition: the fold counts the at-risk subset of the *kept* works.
    # `--fidelity full` keeps X (full+drifted) and Y (full+verified); of those only
    # X is at risk (Y is safely held), so the summary reads 1 of 2.
    from scrolls.works import filter_works

    items, verdicts = _two_work_custody_mix()
    kept = filter_works(works_over(items), verdicts, fidelity="full")
    payload = to_payload(
        kept, len(items), scope={"min_representations": 2, "fidelity": "full"},
        verdicts=verdicts,
    )
    at_risk = payload["stats"]["custody"]["at_risk"]
    assert [w["doi"] for w in payload["works"]] == ["10.1000/x", "10.2000/y"]
    assert at_risk["total"] == 2
    assert at_risk["at_risk"] == 1
    assert at_risk["most_at_risk"]["doi"] == "10.1000/x"


def test_cli_works_stats_custody_at_risk_converges_with_doctor(db, capsys):
    # cross-surface invariant: the unscoped `works` payload's `stats.custody.at_risk`
    # equals `doctor`'s `custody.works` (minus its `status`) — both fold the shared
    # `at_risk_signal` over the same default 2+ clustering and ledger, so the
    # consolidation alarm reads identically without a second `doctor` call.
    from scrolls.custody import CustodyEvent, record_events
    from scrolls.doctor import run_doctor
    from scrolls.paths import get_paths

    for item in [
        _full("arxiv:x", "10.1000/x", title="X"),
        _reference("crossref:cx", "10.1000/x", title="X"),
        _reference("arxiv:z", "10.3000/z", title="Z"),
        _reference("crossref:cz", "10.3000/z", title="Z"),
    ]:
        insert_item(db, item)
    record_events(db, [CustodyEvent(
        item_id="arxiv:x", checked_at="2026-06-14T00:00:00+00:00",
        status="drifted", prior_hash="sha256:a", observed_hash="sha256:b")])

    assert main(["works"]) == 0
    at_risk = json.loads(capsys.readouterr().out)["stats"]["custody"]["at_risk"]
    works_block = run_doctor(get_paths())["custody"]["works"]
    # doctor's block is the same fold plus a `status` key; drop it to compare
    assert at_risk == {k: v for k, v in works_block.items() if k != "status"}
    assert at_risk["at_risk"] == 2  # both X (full+drifted) and Z (all-reference)


# --- the scope echo: completeness contract G2 -----------------------------


def test_to_payload_echoes_the_applied_scope():
    # the self-describing scope companion names exactly the filters honored,
    # pruning None the way scope_envelope does (search/list/related)
    payload = to_payload([], 3, scope={"min_representations": 2, "ref": None})
    assert payload["scope"] == {"min_representations": 2}
    assert payload["stats"] == {"items": 3, "works": 0, "custody": ZERO_CUSTODY}
    assert payload["works"] == []


def test_cli_works_echoes_the_min_floor_as_scope(db, capsys):
    insert_item(db, make_item(
        "arxiv:1706.03762",
        url="https://arxiv.org/abs/1706.03762",
        links=("https://doi.org/10.5555/3295222",),
    ))
    insert_item(db, make_item(
        "crossref:10.5555/3295222", url="https://doi.org/10.5555/3295222"
    ))

    assert main(["works"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # the default floor travels with the result so a reader holding only the
    # output knows works below it were hidden by scope, not absent (G2)
    assert payload["scope"] == {"min_representations": 2}
    assert [w["doi"] for w in payload["works"]] == ["10.5555/3295222"]

    assert main(["works", "--min", "5"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # nothing clears a floor of 5, but the scope is honest about why it is
    # empty: the floor hid the 2-representation work, the library is not bare
    assert payload["scope"] == {"min_representations": 5}
    assert payload["works"] == []


def test_cli_works_ref_scope_names_the_anchor_not_the_floor(db, capsys):
    preprint, published = _attention_pair()
    insert_item(db, preprint)
    insert_item(db, published)

    assert main(["works", "arxiv:1706.03762"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # the per-item lens echoes the anchor it was scoped to; --min is ignored
    # in this form (a solo work is still reported), so it must not appear
    assert payload["scope"] == {"ref": "arxiv:1706.03762"}
    assert [w["doi"] for w in payload["works"]] == ["10.5555/3295222"]


def test_cli_works_ref_scope_resolves_a_url_to_the_item_id(db, capsys):
    preprint, published = _attention_pair()
    insert_item(db, preprint)
    insert_item(db, published)

    assert main(["works", "https://arxiv.org/abs/1706.03762"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # the saved URL is a valid handle (ADR 0028), but the echoed scope names
    # the resolved item id, not the URL the caller happened to pass
    assert payload["scope"] == {"ref": "arxiv:1706.03762"}


# --- the per-item lens: works_for_item ------------------------------------


def _attention_pair():
    """A preprint and its published Crossref record — one work, two reps."""
    preprint = make_item(
        "arxiv:1706.03762",
        url="https://arxiv.org/abs/1706.03762",
        links=("https://doi.org/10.5555/3295222",),
    )
    published = make_item(
        "crossref:10.5555/3295222", url="https://doi.org/10.5555/3295222"
    )
    return preprint, published


def test_works_for_item_returns_the_items_work_with_every_representation():
    preprint, published = _attention_pair()
    works = works_for_item([preprint, published], "arxiv:1706.03762")
    assert [work.doi for work in works] == ["10.5555/3295222"]
    # both representations, the target included, sorted by id
    assert [rep.id for rep in works[0].representations] == [
        "arxiv:1706.03762",
        "crossref:10.5555/3295222",
    ]


def test_works_for_item_reports_a_solo_work_when_no_sibling_is_saved():
    # the item names a DOI but nothing else shares it: an explicit "no
    # sibling" answer (one representation, just itself), not an empty result
    preprint, _ = _attention_pair()
    works = works_for_item([preprint], "arxiv:1706.03762")
    assert len(works) == 1
    assert [rep.id for rep in works[0].representations] == ["arxiv:1706.03762"]


def test_works_for_item_yields_nothing_for_an_item_that_names_no_doi():
    plain = make_item("web:abc", links=("https://example.org/elsewhere",))
    assert works_for_item([plain], "web:abc") == []


def test_works_for_item_raises_for_an_unknown_item():
    preprint, _ = _attention_pair()
    with pytest.raises(ValueError, match="no such item: web:missing"):
        works_for_item([preprint], "web:missing")


def test_cli_works_with_ref_reports_only_that_items_work(db, capsys):
    preprint, published = _attention_pair()
    insert_item(db, preprint)
    insert_item(db, published)
    # an unrelated work that should NOT appear in the per-item view
    insert_item(db, make_item(
        "arxiv:9999.0", url="https://arxiv.org/abs/9999.0",
        links=("https://doi.org/10.5555/other",)))
    insert_item(db, make_item("crossref:10.5555/other", url="https://doi.org/10.5555/other"))

    assert main(["works", "arxiv:1706.03762"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [w["doi"] for w in payload["works"]] == ["10.5555/3295222"]
    # items = whole library; works/custody count only the reported work's reps
    assert _core_stats(payload["stats"]) == {"items": 4, "works": 1}


def test_cli_works_with_url_ref_resolves_the_item(db, capsys):
    preprint, published = _attention_pair()
    insert_item(db, preprint)
    insert_item(db, published)
    # the saved URL is a valid handle wherever an id is (ADR 0028)
    assert main(["works", "https://arxiv.org/abs/1706.03762"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [w["doi"] for w in payload["works"]] == ["10.5555/3295222"]


def test_cli_works_with_unknown_ref_errors(db, capsys):
    assert main(["works", "arxiv:does-not-exist"]) == 1
    err = json.loads(capsys.readouterr().err)
    assert err == {"error": "no such item: arxiv:does-not-exist"}


# --- the browse-surface index: work_membership (ADR 0101) ------------------


def test_work_membership_maps_each_representation_to_its_work():
    preprint, published = _attention_pair()
    membership = work_membership([preprint, published])
    # both representations of the one work appear, each pointing at the work
    assert set(membership) == {"arxiv:1706.03762", "crossref:10.5555/3295222"}
    (preprint_ref,) = membership["arxiv:1706.03762"]
    assert preprint_ref.doi == "10.5555/3295222"
    assert preprint_ref.url == "https://doi.org/10.5555/3295222"
    assert preprint_ref.representations == 2
    # the published Crossref record is the canonical form (ADR 0095) ...
    assert preprint_ref.canonical == "crossref:10.5555/3295222"
    assert preprint_ref.is_canonical is False  # ... and the preprint is not it
    (published_ref,) = membership["crossref:10.5555/3295222"]
    assert published_ref.is_canonical is True


def test_work_membership_omits_single_representation_works():
    # a paper that names a DOI no sibling shares is not a duplicate of anything,
    # so it carries no membership — the 2+ floor `works_over` applies by default
    preprint, _ = _attention_pair()
    assert work_membership([preprint]) == {}


def test_work_membership_omits_items_with_no_doi():
    plain = make_item("web:abc", links=("https://example.org/elsewhere",))
    assert work_membership([plain]) == {}


def test_work_membership_indexes_an_item_into_each_of_its_works():
    # one item can name two DOIs and so be a representation of two works
    # (mirrors test_one_item_can_belong_to_two_works); membership lists both
    hub = make_item(
        "arxiv:multi",
        url="https://arxiv.org/abs/multi",
        links=("https://doi.org/10.1000/a", "https://doi.org/10.2000/b"),
    )
    sib_a = make_item("crossref:10.1000/a", url="https://doi.org/10.1000/a")
    sib_b = make_item("crossref:10.2000/b", url="https://doi.org/10.2000/b")
    refs = work_membership([hub, sib_a, sib_b])["arxiv:multi"]
    assert sorted(ref.doi for ref in refs) == ["10.1000/a", "10.2000/b"]


def test_membership_payload_is_the_browse_json_shape():
    preprint, published = _attention_pair()
    refs = work_membership([preprint, published])["arxiv:1706.03762"]
    assert membership_payload(refs) == [
        {
            "doi": "10.5555/3295222",
            "url": "https://doi.org/10.5555/3295222",
            "canonical": "crossref:10.5555/3295222",
            "is_canonical": False,
            "representations": 2,
        }
    ]
    assert membership_payload(()) == []


def test_cli_list_annotates_each_row_with_its_work(db, capsys):
    preprint, published = _attention_pair()
    insert_item(db, preprint)
    insert_item(db, published)
    insert_item(db, make_item("web:lonely", url="https://example.org/lonely"))

    assert main(["list"]) == 0
    rows = {row["id"]: row for row in json.loads(capsys.readouterr().out)}
    # the preprint row points at the published canonical form
    assert rows["arxiv:1706.03762"]["works"] == [
        {
            "doi": "10.5555/3295222",
            "url": "https://doi.org/10.5555/3295222",
            "canonical": "crossref:10.5555/3295222",
            "is_canonical": False,
            "representations": 2,
        }
    ]
    assert rows["crossref:10.5555/3295222"]["works"][0]["is_canonical"] is True
    # the unrelated item carries no membership
    assert rows["web:lonely"]["works"] == []


def test_cli_list_membership_survives_a_facet_filter(db, capsys):
    # filtering to one source hides the sibling representation, but membership
    # is computed over the whole library, so the shown row still reports 2 reps
    preprint, published = _attention_pair()
    insert_item(db, preprint)
    insert_item(db, published)

    assert main(["list", "--source", "arxiv"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in rows] == ["arxiv:1706.03762"]
    assert rows[0]["works"][0]["representations"] == 2
    assert rows[0]["works"][0]["canonical"] == "crossref:10.5555/3295222"


def test_cli_search_hits_point_at_the_canonical_representation(db, capsys):
    insert_item(db, make_item(
        "arxiv:1706.03762", url="https://arxiv.org/abs/1706.03762",
        title="Attention Is All You Need",
        extracted_text="We propose the Transformer based on attention.",
        links=("https://doi.org/10.5555/3295222",),
    ))
    insert_item(db, make_item(
        "crossref:10.5555/3295222", url="https://doi.org/10.5555/3295222",
        title="Attention Is All You Need",
        extracted_text="We propose the Transformer based on attention.",
    ))

    assert main(["search", "attention transformer"]) == 0
    hits = {h["id"]: h for h in json.loads(capsys.readouterr().out)}
    assert hits["arxiv:1706.03762"]["works"][0]["canonical"] == "crossref:10.5555/3295222"
    assert hits["arxiv:1706.03762"]["works"][0]["is_canonical"] is False
    assert hits["crossref:10.5555/3295222"]["works"][0]["is_canonical"] is True
