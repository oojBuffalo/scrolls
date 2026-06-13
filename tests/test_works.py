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
from scrolls.works import find_works, works_for_item, works_over


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
    assert payload["stats"] == {"items": 2, "works": 1}
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
    }


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
    assert payload["stats"] == {"items": 1, "works": 1}


def test_cli_works_empty_library(scrolls_home, capsys):
    assert main(["works"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "works": [],
        "stats": {"items": 0, "works": 0},
    }


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
    assert payload["stats"] == {"items": 4, "works": 1}  # items = whole library


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
