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
    assert payload["stats"]["custody"] == expected
    assert set(expected["by_source"]) == {"arxiv", "crossref"}  # genuinely multi-source
    # the flag names the drifted source and carries no fabricated coverage
    assert expected["attention"]["source"] == "arxiv"
    assert "coverage" not in expected["attention"]


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
