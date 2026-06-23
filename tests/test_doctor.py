"""Tests for `scrolls doctor`: library integrity diagnosis and repair (ADR 0026).

The doctor engine (`run_doctor`) finds drift between the SQLite index
and the file tree — duplicate items left behind by pre-normalization
URLs (ADR 0023's deferred debt), rendered scrolls missing on disk,
captured media files gone, orphan scroll files, and an FTS index out of
sync with the items table. `--fix` repairs only what is safe offline:
merges duplicates into the canonical id, rewrites missing scrolls from
the index, rebuilds the FTS index. Missing media (network) and orphan
files (not provably tool-owned) are report-only.
"""

import json
import shutil
import sqlite3
from dataclasses import replace

import pytest

from scrolls.cli import main
from scrolls.custody import CustodyEvent, record_events
from scrolls.db import init_db
from scrolls.doctor import run_doctor
from scrolls.items import (
    adopt_incoming,
    insert_item,
    list_items,
    make_item_id,
    ScrollItem,
)
from scrolls.paths import get_paths
from scrolls.render import write_scroll
from scrolls.search import search_items


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


@pytest.fixture
def paths(scrolls_home):
    library = get_paths()
    library.root.mkdir(parents=True)
    init_db(library.db_path)
    return library


def _web_item(url, *, fetched=False, **overrides):
    """A url-hash-identity item, the kind ADR 0023 duplicates affect."""
    fields = {
        "id": make_item_id("web", None, url),
        "source": "web",
        "source_id": None,
        "url": url,
        "saved_at": "2026-06-12T08:00:00+00:00",
    }
    if fetched:
        fields.update(
            title="A Post",
            extracted_text="body text",
            summary="a post about things",
            content_hash="sha256:abc",
            stage="fetched",
        )
    fields.update(overrides)
    return ScrollItem(**fields)


def _rendered(paths, item):
    """Write the item's scroll and store the rendered row, like `scrolls md`."""
    rendered = write_scroll(paths, item)
    insert_item(paths.db_path, rendered)
    return rendered


def insert_and_id(paths, url):
    """Insert a fetched web item for `url` and return its id (for drift tests)."""
    item = _web_item(url, fetched=True)
    insert_item(paths.db_path, item)
    return item.id


# --- clean and empty libraries ---


def test_clean_library_reports_no_issues(paths):
    _rendered(paths, _web_item("https://example.com/post", fetched=True))
    report = run_doctor(paths)
    assert report["issues"] == 0
    assert report["fixed"] == 0
    assert report["duplicates"] == []
    assert report["missing_scrolls"] == []
    assert report["missing_media"] == []
    assert report["orphan_scrolls"] == []
    assert report["fts"] == {"in_sync": True, "status": "ok"}


def test_uninitialized_library_reports_empty(scrolls_home):
    report = run_doctor(get_paths())
    assert report["issues"] == 0
    assert report["fts"] == {"in_sync": None, "status": "skipped"}


# --- duplicate items (ADR 0023's deferred debt) ---


def test_finds_pre_normalization_duplicates(paths):
    junk = "https://example.com/post?utm_source=newsletter&fbclid=IwAR0"
    insert_item(paths.db_path, _web_item(junk, fetched=True))
    insert_item(paths.db_path, _web_item("https://example.com/post"))

    report = run_doctor(paths)

    assert report["issues"] == 1
    [group] = report["duplicates"]
    assert group["source"] == "web"
    assert group["url"] == "https://example.com/post"
    assert sorted(group["ids"]) == sorted(
        [make_item_id("web", None, junk), make_item_id("web", None, "https://example.com/post")]
    )
    assert group["status"] == "found"
    assert len(list_items(paths.db_path)) == 2  # report mode never mutates


def test_items_with_source_ids_never_count_as_duplicates(paths):
    # identity comes from the source-local id, not the URL, so a shared
    # URL spelling is not doctor's business
    insert_item(paths.db_path, ScrollItem(
        id="wikipedia:en:SQLite", source="wikipedia", source_id="en:SQLite",
        url="https://en.wikipedia.org/wiki/SQLite", saved_at="2026-06-12T08:00:00+00:00"))
    insert_item(paths.db_path, ScrollItem(
        id="wikipedia:en:Sqlite", source="wikipedia", source_id="en:Sqlite",
        url="https://en.wikipedia.org/wiki/SQLite", saved_at="2026-06-12T08:01:00+00:00"))
    assert run_doctor(paths)["duplicates"] == []


def test_fix_merges_duplicates_into_canonical_id(paths):
    junk = "https://example.com/post?utm_source=newsletter"
    clean = "https://example.com/post"
    # the junk-url item is the one with content: fetched, rendered, classified
    junk_item = _rendered(paths, _web_item(
        junk, fetched=True, category="opinion", tags=("essays",),
        saved_at="2026-06-10T08:00:00+00:00"))
    insert_item(paths.db_path, _web_item(clean, saved_at="2026-06-12T08:00:00+00:00"))

    report = run_doctor(paths, fix=True)

    assert report["issues"] == 1
    assert report["fixed"] == 1
    [group] = report["duplicates"]
    assert group["status"] == "merged"
    assert group["merged_id"] == make_item_id("web", None, clean)

    [survivor] = list_items(paths.db_path)
    assert survivor.id == make_item_id("web", None, clean)
    assert survivor.url == clean
    assert survivor.title == "A Post"  # content came from the rendered donor
    assert survivor.category == "opinion"
    assert survivor.saved_at == "2026-06-10T08:00:00+00:00"  # earliest save wins
    assert survivor.stage == "rendered"
    # the survivor's scroll was re-rendered under the donor's stable path
    # with merged identity in the frontmatter
    assert survivor.markdown_path == junk_item.markdown_path
    scroll = (paths.root / survivor.markdown_path).read_text(encoding="utf-8")
    assert f'id: "{survivor.id}"' in scroll
    assert f'url: "{clean}"' in scroll


def test_fix_merges_classification_across_members(paths):
    junk = "https://example.com/post?utm_campaign=x"
    clean = "https://example.com/post"
    # donor (most advanced) has no category; the detected loser carries
    # user classification that must survive the merge
    insert_item(paths.db_path, _web_item(junk, fetched=True, tags=("a",)))
    insert_item(paths.db_path, _web_item(
        clean, category="tool", domain="databases", tags=("b", "a")))

    run_doctor(paths, fix=True)

    [survivor] = list_items(paths.db_path)
    assert survivor.category == "tool"
    assert survivor.domain == "databases"
    assert survivor.tags == ("a", "b")  # union, donor's order first


def test_fix_deletes_the_losing_duplicates_scroll_file(paths):
    junk = "https://example.com/post?utm_source=x"
    clean = "https://example.com/post"
    junk_item = _rendered(paths, _web_item(junk, fetched=True))
    clean_item = _rendered(paths, _web_item(
        clean, fetched=True, title="A Post Again",
        saved_at="2026-06-12T09:00:00+00:00"))

    run_doctor(paths, fix=True)

    [survivor] = list_items(paths.db_path)
    # both were rendered: the donor (earlier saved) wins, the loser's file goes
    assert survivor.markdown_path == junk_item.markdown_path
    assert (paths.root / junk_item.markdown_path).exists()
    assert not (paths.root / clean_item.markdown_path).exists()


def test_merged_duplicates_do_not_recur(paths):
    junk = "https://example.com/post?utm_source=x"
    insert_item(paths.db_path, _web_item(junk, fetched=True))
    insert_item(paths.db_path, _web_item("https://example.com/post"))

    run_doctor(paths, fix=True)
    assert run_doctor(paths)["issues"] == 0

    # the canonical id is what a future clean `scrolls add` mints, so
    # re-adding the URL dedupes instead of re-creating the duplicate
    exit_code = main(["add", "https://example.com/post"])
    assert exit_code == 0


def test_fix_reports_a_merge_it_cannot_complete(paths):
    _rendered(paths, _web_item("https://example.com/post?utm_source=x", fetched=True))
    insert_item(paths.db_path, _web_item("https://example.com/post"))
    # block the survivor's scroll rewrite: a file squats where its dir must be
    shutil.rmtree(paths.scrolls_dir / "web")
    (paths.scrolls_dir / "web").write_text("not a directory", encoding="utf-8")

    report = run_doctor(paths, fix=True)

    [group] = report["duplicates"]
    assert group["status"] == "failed"
    assert group["error"]
    assert len(list_items(paths.db_path)) == 2  # a failed merge mutates nothing


def test_merged_item_stays_searchable(paths):
    junk = "https://example.com/post?utm_source=x"
    insert_item(paths.db_path, _web_item(junk, fetched=True))
    insert_item(paths.db_path, _web_item("https://example.com/post"))

    run_doctor(paths, fix=True)

    hits = search_items(paths.db_path, "post things")
    assert [hit.id for hit in hits] == [make_item_id("web", None, "https://example.com/post")]


# --- missing scroll files ---


def test_finds_missing_scroll_file(paths):
    rendered = _rendered(paths, _web_item("https://example.com/post", fetched=True))
    (paths.root / rendered.markdown_path).unlink()

    report = run_doctor(paths)

    assert report["issues"] == 1
    assert report["missing_scrolls"] == [
        {"id": rendered.id, "path": rendered.markdown_path, "status": "found"}
    ]


def test_fix_rewrites_missing_scroll_from_the_index(paths):
    rendered = _rendered(paths, _web_item("https://example.com/post", fetched=True))
    (paths.root / rendered.markdown_path).unlink()

    report = run_doctor(paths, fix=True)

    assert report["fixed"] == 1
    assert report["missing_scrolls"][0]["status"] == "rewritten"
    assert (paths.root / rendered.markdown_path).exists()
    assert run_doctor(paths)["issues"] == 0


def test_fix_reports_a_scroll_it_cannot_rewrite(paths):
    rendered = _rendered(paths, _web_item("https://example.com/post", fetched=True))
    (paths.root / rendered.markdown_path).unlink()
    # block the rewrite: a file squats where the scroll's directory must be
    shutil.rmtree(paths.scrolls_dir / "web")
    (paths.scrolls_dir / "web").write_text("not a directory", encoding="utf-8")

    report = run_doctor(paths, fix=True)

    [entry] = report["missing_scrolls"]
    assert entry["status"] == "failed"
    assert entry["error"]
    assert report["issues"] == 1
    assert report["fixed"] == 0


# --- missing media files ---


def test_finds_missing_captured_media_file(paths):
    item = _web_item(
        "https://example.com/post", fetched=True,
        media=({"type": "photo", "url": "https://example.com/p.jpg",
                "path": "media/web/p-1.jpg"},))
    insert_item(paths.db_path, item)

    report = run_doctor(paths)

    assert report["missing_media"] == [
        {"id": item.id, "path": "media/web/p-1.jpg",
         "url": "https://example.com/p.jpg", "status": "found"}
    ]
    assert report["issues"] == 1


def test_uncaptured_media_refs_are_not_drift(paths):
    # a ref without a recorded path was never captured; that is normal
    # pipeline state for `scrolls media` to handle, not drift
    insert_item(paths.db_path, _web_item(
        "https://example.com/post", fetched=True,
        media=({"type": "photo", "url": "https://example.com/p.jpg"},)))
    assert run_doctor(paths)["missing_media"] == []


def test_fix_leaves_missing_media_to_scrolls_media(paths):
    insert_item(paths.db_path, _web_item(
        "https://example.com/post", fetched=True,
        media=({"type": "photo", "url": "https://example.com/p.jpg",
                "path": "media/web/p-1.jpg"},)))

    report = run_doctor(paths, fix=True)

    assert report["missing_media"][0]["status"] == "found"  # not touched
    assert report["issues"] == 1
    assert report["fixed"] == 0


# --- orphan scroll files ---


def test_finds_orphan_scroll_files(paths):
    _rendered(paths, _web_item("https://example.com/post", fetched=True))
    stray = paths.scrolls_dir / "web" / "deleted-item.md"
    stray.write_text("# leftover\n", encoding="utf-8")

    report = run_doctor(paths)

    assert report["orphan_scrolls"] == [
        {"path": "scrolls/web/deleted-item.md", "status": "found"}
    ]
    assert report["issues"] == 1


def test_fix_never_deletes_orphan_scrolls(paths):
    stray = paths.scrolls_dir / "web" / "deleted-item.md"
    stray.parent.mkdir(parents=True)
    stray.write_text("# leftover\n", encoding="utf-8")

    report = run_doctor(paths, fix=True)

    assert stray.exists()
    assert report["orphan_scrolls"][0]["status"] == "found"
    assert report["fixed"] == 0


# --- FTS index drift ---


def _corrupt_fts(db_path):
    """Plant a phantom index entry with no items row behind it."""
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO items_fts(rowid, title, summary, extracted_text) "
                "VALUES (999, 'ghost', '', '')"
            )
    finally:
        conn.close()


def test_finds_fts_drift(paths):
    insert_item(paths.db_path, _web_item("https://example.com/post", fetched=True))
    _corrupt_fts(paths.db_path)

    report = run_doctor(paths)

    assert report["fts"] == {"in_sync": False, "status": "found"}
    assert report["issues"] == 1


def test_fix_rebuilds_drifted_fts(paths):
    insert_item(paths.db_path, _web_item("https://example.com/post", fetched=True))
    _corrupt_fts(paths.db_path)

    report = run_doctor(paths, fix=True)

    assert report["fts"] == {"in_sync": True, "status": "rebuilt"}
    assert report["fixed"] == 1
    assert run_doctor(paths)["issues"] == 0


def test_fts_check_degrades_on_old_sqlite(paths, monkeypatch):
    # before SQLite 3.42 'integrity-check' cannot verify the index
    # against the content table; doctor says so instead of guessing
    monkeypatch.setattr("scrolls.doctor.sqlite3.sqlite_version_info", (3, 41, 0))
    insert_item(paths.db_path, _web_item("https://example.com/post", fetched=True))

    report = run_doctor(paths)

    assert report["fts"] == {"in_sync": None, "status": "unsupported"}
    assert report["issues"] == 0


# --- CLI ---


def test_doctor_clean_library_exits_zero(paths, capsys):
    _rendered(paths, _web_item("https://example.com/post", fetched=True))
    exit_code = main(["doctor"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["issues"] == 0


def test_doctor_before_init_exits_zero(scrolls_home, capsys):
    exit_code = main(["doctor"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["issues"] == 0
    assert not scrolls_home.exists()  # doctor never creates a library


def test_doctor_reports_issues_and_exits_one(paths, capsys):
    insert_item(paths.db_path, _web_item("https://example.com/post?utm_source=x"))
    insert_item(paths.db_path, _web_item("https://example.com/post"))

    exit_code = main(["doctor"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["issues"] == 1
    assert payload["fixed"] == 0
    assert len(list_items(paths.db_path)) == 2  # report mode never mutates


def test_doctor_fix_repairs_everything_fixable_and_exits_zero(paths, capsys):
    insert_item(paths.db_path, _web_item("https://example.com/post?utm_source=x", fetched=True))
    insert_item(paths.db_path, _web_item("https://example.com/post"))
    rendered = _rendered(paths, _web_item("https://example.com/other", fetched=True,
                                          title="Other"))
    (paths.root / rendered.markdown_path).unlink()
    _corrupt_fts(paths.db_path)

    exit_code = main(["doctor", "--fix"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["issues"] == 3
    assert payload["fixed"] == 3


def test_doctor_fix_exits_one_when_unfixable_drift_remains(paths, capsys):
    insert_item(paths.db_path, _web_item(
        "https://example.com/post", fetched=True,
        media=({"type": "photo", "url": "https://example.com/p.jpg",
                "path": "media/web/p-1.jpg"},)))

    exit_code = main(["doctor", "--fix"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["issues"] == 1
    assert payload["fixed"] == 0


# --- custody integrity audit (ADR 0097) ---


def test_clean_library_scores_full_custody(paths):
    _rendered(paths, _web_item("https://example.com/post", fetched=True,
                               extracted_text="full body", content_hash="sha256:123"))
    custody = run_doctor(paths)["custody"]
    assert custody["score"] == 100
    assert custody["issues"] == 0
    assert custody["findings"] == []
    assert custody["tiers"]["full"] == 1


def test_empty_library_scores_full_custody(paths):
    custody = run_doctor(paths)["custody"]
    assert custody["score"] == 100
    assert custody["tiers"] == {"full": 0, "partial": 0, "reference": 0}


def test_custody_report_counts_each_fidelity_tier(paths):
    insert_item(paths.db_path, _web_item(
        "https://example.com/full", fetched=True,
        extracted_text="full body", content_hash="sha256:123"))
    insert_item(paths.db_path, _web_item(
        "https://example.com/partial", extracted_text="partial", content_hash=None))
    insert_item(paths.db_path, _web_item("https://example.com/ref"))

    tiers = run_doctor(paths)["custody"]["tiers"]
    assert tiers == {"full": 1, "partial": 1, "reference": 1}


def test_custody_by_source_is_empty_for_an_empty_library(paths):
    # no held items → no sources → the honest empty map (a stable shape, never None)
    assert run_doctor(paths)["custody"]["by_source"] == {}


def test_custody_by_source_groups_each_source(paths):
    # the audit names which source's custody is weakest: a per-source split of
    # the same fidelity/drift aggregate (roadmap H104), source keys sorted.
    insert_item(paths.db_path, _web_item(
        "https://example.com/full", fetched=True,
        extracted_text="full body", content_hash="sha256:123"))
    insert_item(paths.db_path, _web_item("https://example.com/ref"))  # reference
    insert_item(paths.db_path, ScrollItem(
        id="arxiv:1", source="arxiv", source_id="1",
        url="https://arxiv.org/abs/1", saved_at="2026-06-12T08:00:00+00:00",
        extracted_text="paper body", content_hash="sha256:abc", stage="fetched"))

    by_source = run_doctor(paths)["custody"]["by_source"]
    assert list(by_source) == ["arxiv", "web"]  # sorted keys
    assert by_source["arxiv"]["tiers"] == {"full": 1, "partial": 0, "reference": 0}
    assert by_source["web"]["tiers"] == {"full": 1, "partial": 0, "reference": 1}
    # never verified → both sources' items are unverified
    assert by_source["arxiv"]["drift"]["unverified"] == 1
    assert by_source["web"]["drift"]["unverified"] == 2


def test_custody_by_source_carries_the_drift_posture_per_source(paths):
    # a drifted web item and an unchanged arxiv one: each source reports its own
    # posture, read from the same ledger the whole-library drift block aggregates.
    insert_item(paths.db_path, _web_item(
        "https://example.com/post", fetched=True,
        extracted_text="body", content_hash="sha256:old"))
    insert_item(paths.db_path, ScrollItem(
        id="arxiv:1", source="arxiv", source_id="1",
        url="https://arxiv.org/abs/1", saved_at="2026-06-12T08:00:00+00:00",
        extracted_text="paper", content_hash="sha256:p", stage="fetched"))
    web_id = _web_item("https://example.com/post").id
    record_events(paths.db_path, [
        CustodyEvent(web_id, "2026-06-15T00:00:00+00:00", "drifted",
                     "sha256:old", "sha256:new", None),
        CustodyEvent("arxiv:1", "2026-06-15T00:00:00+00:00", "unchanged",
                     "sha256:p", "sha256:p", None),
    ])

    by_source = run_doctor(paths)["custody"]["by_source"]
    assert by_source["web"]["drift"]["drifted"] == 1
    assert by_source["arxiv"]["drift"]["verified"] == 1


def test_custody_by_source_tallies_sum_to_the_whole_library_block(paths):
    # the load-bearing convergence (H50, per source): summing the per-source
    # tallies re-counts the whole library, so by_source can never disagree with
    # the custody block it splits.
    insert_item(paths.db_path, _web_item(
        "https://example.com/full", fetched=True,
        extracted_text="full body", content_hash="sha256:1"))
    insert_item(paths.db_path, _web_item(
        "https://example.com/partial", extracted_text="partial", content_hash=None))
    insert_item(paths.db_path, ScrollItem(
        id="arxiv:1", source="arxiv", source_id="1",
        url="https://arxiv.org/abs/1", saved_at="2026-06-12T08:00:00+00:00",
        extracted_text="paper", content_hash="sha256:p", stage="fetched"))

    custody = run_doctor(paths)["custody"]
    by_source = custody["by_source"]
    # tiers sum to the whole-library `tiers`
    summed_tiers = {tier: 0 for tier in ("full", "partial", "reference")}
    for counts in by_source.values():
        for tier, n in counts["tiers"].items():
            summed_tiers[tier] += n
    assert summed_tiers == custody["tiers"]
    # drift postures sum to the whole-library drift block (verified ≡ unchanged)
    summed_drift = {p: 0 for p in ("verified", "unverified", "drifted", "rotted", "error")}
    for counts in by_source.values():
        for posture, n in counts["drift"].items():
            summed_drift[posture] += n
    drift = custody["drift"]
    assert summed_drift == {
        "verified": drift["unchanged"], "unverified": drift["unverified"],
        "drifted": drift["drifted"], "rotted": drift["rotted"], "error": drift["error"],
    }


def test_custody_by_source_never_feeds_issues_or_the_exit_code(paths):
    # report-only like the rest of the custody block: a weak per-source custody
    # picture is a view, never a structural issue.
    insert_item(paths.db_path, _web_item("https://example.com/ref"))  # reference-only
    report = run_doctor(paths)
    assert report["custody"]["by_source"]["web"]["tiers"]["reference"] == 1
    assert report["issues"] == 0


def test_custody_by_source_carries_per_source_coverage(paths):
    # roadmap H121: each by_source entry carries its own coverage {verified, total}
    # over that source's verifiable (hash-bearing) held items — so the audit names
    # which source is least *covered* (most never-checked), not just most drifted.
    insert_item(paths.db_path, _web_item(
        "https://example.com/post", fetched=True,
        extracted_text="body", content_hash="sha256:old"))
    insert_item(paths.db_path, _web_item("https://example.com/ref"))  # reference-only
    insert_item(paths.db_path, ScrollItem(
        id="arxiv:1", source="arxiv", source_id="1",
        url="https://arxiv.org/abs/1", saved_at="2026-06-12T08:00:00+00:00",
        extracted_text="paper", content_hash="sha256:p", stage="fetched"))
    record_events(paths.db_path, [
        CustodyEvent(_web_item("https://example.com/post").id,
                     "2026-06-15T00:00:00+00:00", "unchanged",
                     "sha256:old", "sha256:old", None),
    ])

    by_source = run_doctor(paths)["custody"]["by_source"]
    # web: one hash-bearing item verified, the reference-only one excluded → 1 of 1
    assert by_source["web"]["coverage"] == {"verified": 1, "total": 1}
    # arxiv: one hash-bearing item, never verified → 0 of 1
    assert by_source["arxiv"]["coverage"] == {"verified": 0, "total": 1}


def test_custody_by_source_coverage_sums_to_the_whole_drift_coverage(paths):
    # the coverage-axis convergence (the H121 sibling of the tiers/drift
    # sum-to-whole): summing the per-source coverage re-counts the whole-library
    # drift.coverage, so by_source can never disagree with it.
    insert_item(paths.db_path, _web_item(
        "https://example.com/post", fetched=True,
        extracted_text="body", content_hash="sha256:w"))
    insert_item(paths.db_path, _web_item("https://example.com/ref"))  # reference-only
    insert_item(paths.db_path, ScrollItem(
        id="arxiv:1", source="arxiv", source_id="1",
        url="https://arxiv.org/abs/1", saved_at="2026-06-12T08:00:00+00:00",
        extracted_text="paper", content_hash="sha256:p", stage="fetched"))
    record_events(paths.db_path, [
        CustodyEvent(_web_item("https://example.com/post").id,
                     "2026-06-15T00:00:00+00:00", "unchanged",
                     "sha256:w", "sha256:w", None),
    ])

    custody = run_doctor(paths)["custody"]
    summed = {"verified": 0, "total": 0}
    for counts in custody["by_source"].values():
        summed["verified"] += counts["coverage"]["verified"]
        summed["total"] += counts["coverage"]["total"]
    assert summed == custody["drift"]["coverage"]


def test_custody_by_source_coverage_excludes_reference_only(paths):
    # a source holding only reference-only items has no verifiable items, so its
    # coverage denominator is 0 (can reach full, never stuck below 100%).
    insert_item(paths.db_path, _web_item("https://example.com/ref"))  # reference-only
    by_source = run_doctor(paths)["custody"]["by_source"]
    assert by_source["web"]["coverage"] == {"verified": 0, "total": 0}


# --- at-risk works: the consolidation custody alarm (roadmap H263) ---
# A work is *at risk* when NO representation is safely held (the H261
# `safely_held == False` set) — every copy degraded or moved, no unmoved full form
# anywhere. The work-level analogue of the per-source weakest-source flag.


def _rep(item_id, doi, tier, **overrides):
    """A representation of the work `doi` at the given fidelity tier (links to doi.org)."""
    fields = dict(
        id=item_id, source=item_id.split(":")[0],
        source_id=item_id.split(":", 1)[1] if ":" in item_id else None,
        url=f"https://example.org/{item_id}", saved_at="2026-06-12T08:00:00+00:00",
        links=(f"https://doi.org/{doi}",), stage="rendered",
    )
    if tier == "full":
        fields.update(extracted_text="body", content_hash=f"sha256:{item_id}")
    elif tier == "partial":
        fields.update(summary="a summary")
    fields.update(overrides)
    return ScrollItem(**fields)


def _seed_works_custody_mix(paths):
    """Three 2-rep works: X at risk (full+drifted, ref), Y safely held (full+verified,
    partial), Z most at risk (all reference). Returns nothing — seeds the library."""
    for item in [
        _rep("arxiv:x", "10.1000/x", "full"),
        _rep("crossref:cx", "10.1000/x", "reference"),
        _rep("biorxiv:y", "10.2000/y", "full"),
        _rep("pubmed:y", "10.2000/y", "partial"),
        _rep("arxiv:z", "10.3000/z", "reference"),
        _rep("crossref:cz", "10.3000/z", "reference"),
    ]:
        insert_item(paths.db_path, item)
    record_events(paths.db_path, [
        CustodyEvent(item_id="arxiv:x", checked_at="2026-06-14T00:00:00+00:00",
                     status="drifted", prior_hash="sha256:a", observed_hash="sha256:b"),
        CustodyEvent(item_id="biorxiv:y", checked_at="2026-06-14T00:00:00+00:00",
                     status="unchanged", prior_hash="sha256:c", observed_hash="sha256:c"),
    ])


def test_custody_works_flags_the_at_risk_works(paths):
    # 2 of 3 works at risk (X holds a full-but-drifted copy; Z holds nothing
    # re-derivable); Y is safely held by its full+verified preprint, so excluded.
    _seed_works_custody_mix(paths)
    works = run_doctor(paths)["custody"]["works"]
    assert works["status"] == "ok"
    assert works["total"] == 3
    assert works["at_risk"] == 2


def test_custody_works_names_the_lowest_ceiling_work_as_most_at_risk(paths):
    # Z (all-reference: no content held anywhere) outranks X (still holds a full,
    # only-drifted copy) — worst fidelity ceiling wins.
    _seed_works_custody_mix(paths)
    most = run_doctor(paths)["custody"]["works"]["most_at_risk"]
    assert most["doi"] == "10.3000/z"
    assert most["url"] == "https://doi.org/10.3000/z"
    assert most["canonical"] == "crossref:cz"  # crossref outranks arxiv
    assert most["representations"] == 2
    assert most["custody"] == {
        "best_fidelity": "reference", "safest_drift": "unverified", "safely_held": False,
    }
    assert most["reason"] == (
        "no representation is both full and unmoved "
        "(best held reference, safest drift unverified)"
    )


def test_custody_works_never_feeds_issues_or_the_exit_code(paths):
    # at-risk works are a custody *report*, like drift — doctor cannot repair an
    # upstream move, so they never bump the structural issue count or the exit code.
    _seed_works_custody_mix(paths)
    report = run_doctor(paths)
    assert report["custody"]["works"]["at_risk"] == 2
    assert report["issues"] == 0
    assert main(["doctor"]) == 0  # healthy exit despite the consolidation loss


def test_custody_works_is_ok_and_empty_when_every_work_is_safely_held(paths):
    # two works, each with a full+unverified rep (never checked, so safely held) →
    # computed (status ok), none at risk, no work named.
    for item in [
        _rep("arxiv:a", "10.1000/a", "full"),
        _rep("crossref:ca", "10.1000/a", "reference"),
        _rep("biorxiv:b", "10.2000/b", "full"),
        _rep("crossref:cb", "10.2000/b", "reference"),
    ]:
        insert_item(paths.db_path, item)
    works = run_doctor(paths)["custody"]["works"]
    assert works == {"status": "ok", "total": 2, "at_risk": 0, "most_at_risk": None}


def test_custody_works_on_an_empty_library_is_ok_with_no_works(paths):
    # an initialized but empty library computes the signal (status ok): 0 works.
    works = run_doctor(paths)["custody"]["works"]
    assert works == {"status": "ok", "total": 0, "at_risk": 0, "most_at_risk": None}


def test_custody_works_on_an_uninitialized_library_is_skipped(scrolls_home):
    # no database → the early return leaves the honest skipped default, never a
    # fabricated "0 at risk" the audit never computed.
    works = run_doctor(get_paths())["custody"]["works"]
    assert works == {
        "status": "skipped", "total": 0, "at_risk": 0, "most_at_risk": None,
    }


# --- per-source scoped audit (roadmap H162) ---


def _arxiv_item(suffix, **overrides):
    """A source_id-identity arxiv item (a second source for scope tests)."""
    fields = dict(
        id=f"arxiv:{suffix}", source="arxiv", source_id=suffix,
        url=f"https://arxiv.org/abs/{suffix}", saved_at="2026-06-12T08:00:00+00:00",
        extracted_text="paper body", content_hash=f"sha256:{suffix}", stage="fetched",
    )
    fields.update(overrides)
    return ScrollItem(**fields)


def _seed_two_sources(paths):
    """One full web item, one reference-only web item, one full arxiv item."""
    insert_item(paths.db_path, _web_item(
        "https://example.com/post", fetched=True,
        extracted_text="body", raw_text="<raw>body</raw>", content_hash="sha256:w"))
    insert_item(paths.db_path, _web_item("https://example.com/ref"))  # reference-only
    insert_item(paths.db_path, _arxiv_item("1"))


def test_doctor_source_scopes_the_custody_view_to_one_source(paths):
    # --source narrows the whole audit to that source's held items: tiers/drift
    # count only web, and by_source collapses to the singleton {web: ...}.
    _seed_two_sources(paths)
    custody = run_doctor(paths, source="web")["custody"]
    # web holds one full + one reference (the arxiv full item is excluded)
    assert custody["tiers"] == {"full": 1, "partial": 0, "reference": 1}
    assert list(custody["by_source"]) == ["web"]  # present-and-singleton
    assert custody["by_source"]["web"]["tiers"] == {"full": 1, "partial": 0, "reference": 1}
    # only web's two items are counted as unverified (arxiv's is not in scope)
    assert custody["drift"]["unverified"] == 2


def test_doctor_source_audit_equals_the_whole_library_by_source_slice(paths):
    # the load-bearing convergence (pinned cross-surface in
    # test_custody_convergence.py): a --source S audit's tiers/drift/coverage
    # equals the whole-library audit's by_source[S] — same held subset, same tally.
    _seed_two_sources(paths)
    record_events(paths.db_path, [
        CustodyEvent(_web_item("https://example.com/post").id,
                     "2026-06-15T00:00:00+00:00", "unchanged",
                     "sha256:w", "sha256:w", None),
    ])
    whole = run_doctor(paths)["custody"]["by_source"]["web"]
    scoped = run_doctor(paths, source="web")["custody"]
    assert scoped["tiers"] == whole["tiers"]
    assert scoped["by_source"]["web"]["drift"] == whole["drift"]
    assert scoped["drift"]["coverage"] == whole["coverage"] == {"verified": 1, "total": 1}


def test_doctor_source_narrows_the_drift_events_to_that_source(paths):
    # the offending-id lists narrow too, not just the counts: a drifted web item
    # and a drifted arxiv item, scoped to web → only web's event is listed.
    _seed_two_sources(paths)
    web_id = _web_item("https://example.com/post").id
    record_events(paths.db_path, [
        CustodyEvent(web_id, "2026-06-15T00:00:00+00:00", "drifted",
                     "sha256:w", "sha256:new", None),
        CustodyEvent("arxiv:1", "2026-06-15T00:00:00+00:00", "drifted",
                     "sha256:1", "sha256:new", None),
    ])
    scoped = run_doctor(paths, source="web")["custody"]["drift"]
    assert scoped["drifted"] == 1
    assert [e["id"] for e in scoped["events"]] == [web_id]


def test_doctor_source_narrows_enrichment_stale_to_that_source(paths):
    # the enrichment offending-id list + count narrow to the scoped source, and
    # equal the whole-library enrichment.by_source[S] entry by construction.
    from scrolls.classify import RULESET_FINGERPRINT

    def _classified(item, ruleset):
        return replace(item, category="tutorial", provenance={
            "classified_by": "rules-v1", "classified_basis": "weak-source",
            "classified_ruleset": ruleset})

    insert_item(paths.db_path, _classified(
        _web_item("https://example.com/post", fetched=True), "deadbeef0000"))
    insert_item(paths.db_path, _classified(_arxiv_item("1"), "cafe00000000"))
    whole = run_doctor(paths)["custody"]["enrichment"]
    assert whole["by_source"] == {"arxiv": 1, "web": 1}

    scoped = run_doctor(paths, source="web")["custody"]["enrichment"]
    assert scoped["stale"] == whole["by_source"]["web"] == 1
    assert [entry["id"] for entry in scoped["items"]] == [
        _web_item("https://example.com/post").id]
    assert scoped["by_source"] == {"web": 1}  # the singleton offenders map


def test_doctor_unknown_source_is_the_honest_empty_audit(paths):
    # an unknown source holds nothing → the empty audit (score 100, zeroed
    # counts, empty by_source), never an error.
    _seed_two_sources(paths)
    report = run_doctor(paths, source="ghost")
    custody = report["custody"]
    assert custody["score"] == 100  # empty is healthy
    assert custody["tiers"] == {"full": 0, "partial": 0, "reference": 0}
    assert custody["by_source"] == {}
    assert custody["drift"]["checked"] == 0 and custody["drift"]["unverified"] == 0
    assert report["issues"] == 0
    assert main(["doctor", "--source", "ghost"]) == 0


def test_doctor_source_skips_orphan_and_fts_checks(paths):
    # the two non-source-attributable checks are skipped under --source: another
    # source's owned scroll is never an orphan, a genuine stray .md is left to the
    # whole-library audit, and the single FTS index reports its skipped default.
    rendered_arxiv = _rendered(paths, _arxiv_item("1"))
    assert rendered_arxiv.markdown_path  # arxiv's scroll is on disk, owned by arxiv
    stray = paths.scrolls_dir / "stray.md"
    stray.write_text("orphaned, owned by no item")

    scoped = run_doctor(paths, source="web")
    assert scoped["orphan_scrolls"] == []  # arxiv's scroll + the stray are not web's
    assert scoped["fts"] == {"in_sync": None, "status": "skipped"}
    assert scoped["issues"] == 0  # nothing web-attributable

    # sanity: the whole-library audit *does* flag the stray orphan
    whole = run_doctor(paths)
    assert [o["path"] for o in whole["orphan_scrolls"]] == [str(stray.relative_to(paths.root))]


def test_doctor_source_skips_the_at_risk_works_alarm(paths):
    # a work spans sources (arxiv preprint + crossref record), so a --source-scoped
    # item set fragments works: the at-risk-works alarm is whole-library only, the
    # third non-source-attributable check. Scoped → the honest skipped default.
    _seed_works_custody_mix(paths)
    scoped = run_doctor(paths, source="arxiv")["custody"]["works"]
    assert scoped == {
        "status": "skipped", "total": 0, "at_risk": 0, "most_at_risk": None,
    }
    # sanity: the unscoped audit *does* see the at-risk works
    assert run_doctor(paths)["custody"]["works"]["at_risk"] == 2


def test_doctor_source_reports_only_that_sources_missing_scrolls(paths):
    # a missing scroll for each source: scoped to web, only web's is a finding and
    # only it drives the exit code (whole-audit semantics, scoped to the source).
    web = _rendered(paths, _web_item("https://example.com/post", fetched=True))
    arxiv = _rendered(paths, _arxiv_item("1"))
    (paths.root / web.markdown_path).unlink()
    (paths.root / arxiv.markdown_path).unlink()

    scoped = run_doctor(paths, source="web")
    assert [m["id"] for m in scoped["missing_scrolls"]] == [web.id]
    assert scoped["issues"] == 1
    assert main(["doctor", "--source", "web"]) == 1  # web's drift fails the exit code


def test_doctor_source_fix_repairs_only_that_source(paths):
    # --source composes with --fix on the attributable repairs: it rewrites web's
    # missing scroll and leaves arxiv's gone (a whole-library --fix repairs both).
    web = _rendered(paths, _web_item("https://example.com/post", fetched=True))
    arxiv = _rendered(paths, _arxiv_item("1"))
    (paths.root / web.markdown_path).unlink()
    (paths.root / arxiv.markdown_path).unlink()

    report = run_doctor(paths, source="web", fix=True)
    assert report["fixed"] == 1
    assert (paths.root / web.markdown_path).exists()  # web's scroll rebuilt
    assert not (paths.root / arxiv.markdown_path).exists()  # arxiv's left for later
    # the whole-library audit now sees only arxiv's scroll still missing
    whole = run_doctor(paths)
    assert [m["id"] for m in whole["missing_scrolls"]] == [arxiv.id]


def test_custody_flags_a_rendered_scroll_gone_from_disk(paths):
    rendered = _rendered(paths, _web_item("https://example.com/post", fetched=True))
    (paths.root / rendered.markdown_path).unlink()

    custody = run_doctor(paths)["custody"]
    [finding] = custody["findings"]
    assert finding == {
        "id": rendered.id, "tier": "full", "issues": ["missing_scroll"],
        "status": "found",
    }
    assert custody["issues"] == 1


def test_custody_missing_scroll_does_not_double_count_structural_issues(paths):
    # a deleted scroll is one drift, surfaced by the structural check (which
    # repairs it and drives the exit code) and mirrored in the custody view —
    # it must never be counted twice in the headline `issues`.
    rendered = _rendered(paths, _web_item("https://example.com/post", fetched=True))
    (paths.root / rendered.markdown_path).unlink()

    report = run_doctor(paths)
    assert report["issues"] == 1  # structural only, not inflated by custody
    assert report["custody"]["issues"] == 1


def test_custody_flags_a_hash_with_no_body_to_reproduce(paths):
    # we kept a fingerprint but lost the content it fingerprints: we can no
    # longer reproduce or verify what we claim to hold
    insert_item(paths.db_path, _web_item(
        "https://example.com/post", content_hash="sha256:orphan", stage="fetched"))

    custody = run_doctor(paths)["custody"]
    [finding] = custody["findings"]
    assert finding["issues"] == ["unrederivable_hash"]
    assert custody["issues"] == 1


def test_custody_flags_held_content_with_no_provenance(paths):
    # content is held but nothing records where it came from
    insert_item(paths.db_path, ScrollItem(
        id="web:orphan", source="web", source_id=None, url="",
        saved_at="2026-06-12T08:00:00+00:00",
        extracted_text="body with no origin", stage="fetched"))

    custody = run_doctor(paths)["custody"]
    [finding] = custody["findings"]
    assert finding["issues"] == ["missing_provenance"]


def test_custody_reference_only_item_is_honest_not_a_finding(paths):
    # a pointer we deliberately hold by reference is complete custody, so it
    # carries no finding and does not lower the score
    insert_item(paths.db_path, _web_item("https://example.com/ref"))
    custody = run_doctor(paths)["custody"]
    assert custody["findings"] == []
    assert custody["score"] == 100


def test_custody_score_is_percent_of_items_free_of_findings(paths):
    # three honest items, one with an unrederivable hash -> 75% clean
    insert_item(paths.db_path, _web_item(
        "https://example.com/a", fetched=True, extracted_text="a", content_hash="sha256:a"))
    insert_item(paths.db_path, _web_item("https://example.com/b", extracted_text="b"))
    insert_item(paths.db_path, _web_item("https://example.com/c"))
    insert_item(paths.db_path, _web_item(
        "https://example.com/d", content_hash="sha256:orphan", stage="fetched"))

    custody = run_doctor(paths)["custody"]
    assert custody["issues"] == 1
    assert custody["score"] == 75


def test_doctor_cli_emits_the_custody_report(paths, capsys):
    insert_item(paths.db_path, _web_item(
        "https://example.com/full", fetched=True,
        extracted_text="full body", content_hash="sha256:123"))

    main(["doctor"])
    custody = json.loads(capsys.readouterr().out)["custody"]
    from scrolls.classify import RULESET_FINGERPRINT
    assert custody == {
        "score": 100, "issues": 0,
        "tiers": {"full": 1, "partial": 0, "reference": 0},
        "by_source": {
            # one held web item, full fidelity, never verified — one verifiable
            # (hash-bearing) item, 0 of 1 covered (H121)
            "web": {
                "tiers": {"full": 1, "partial": 0, "reference": 0},
                "drift": {"verified": 0, "unverified": 1, "drifted": 0,
                          "rotted": 0, "error": 0},
                "coverage": {"verified": 0, "total": 1},
            },
        },
        "findings": [],
        "drift": {
            "basis": "last_verify", "as_of": None,
            "checked": 0, "unverified": 1,
            "unchanged": 0, "drifted": 0, "rotted": 0,
            "error": 0,
            "coverage": {"verified": 0, "total": 1},
            "events": [],
        },
        "conflicts": {
            # no recorded import conflict — the honest all-zero aggregate, the
            # read-aggregate sibling of the drift block (H275, ADR 0104)
            "basis": "import_ledger", "as_of": None, "items": 0, "events": [],
        },
        "enrichment": {
            # the seeded item carries no engine classification, so nothing to
            # measure for ruleset staleness — an honest, all-zero block
            "basis": "ruleset_fingerprint", "current_ruleset": RULESET_FINGERPRINT,
            "classified": 0, "current": 0, "stale": 0, "unfingerprinted": 0,
            "items": [], "by_source": {},
        },
        "summaries": {
            # one item, so no ≥2-member concept is eligible for a summary —
            # the all-zero block (the summary-axis counterpart of enrichment)
            "basis": "members_hash",
            "eligible": 0, "summarized": 0, "current": 0, "stale": 0, "never": 0,
            "items": [], "by_source": {},
        },
        "works": {
            # one item with no DOI → no multi-representation work, so the
            # at-risk-works alarm is computed (status ok) and names none (H263)
            "status": "ok", "total": 0, "at_risk": 0, "most_at_risk": None,
        },
        "archive": {
            # no accept-incoming adoption has archived a prior, so the integrity
            # check is computed (status ok) and finds nothing to verify (H293)
            "status": "ok", "checked": 0, "mismatched": 0, "events": [],
        },
    }


# --- custody drift/rot aggregation (ADR 0098) ---


def _record(paths, item_id, status, *, prior="sha256:old", observed="sha256:old",
            detail=None):
    record_events(paths.db_path, [
        CustodyEvent(item_id, "2026-06-15T00:00:00+00:00", status, prior, observed, detail),
    ])


def test_drift_report_is_empty_without_any_verification(paths):
    insert_item(paths.db_path, _web_item("https://example.com/a", fetched=True))
    drift = run_doctor(paths)["custody"]["drift"]
    assert drift == {
        # the held item has never been verified: it is unverified, not clean,
        # and the block names its basis as the ledger, not a live re-check
        "basis": "last_verify", "as_of": None,
        "checked": 0, "unverified": 1,
        "unchanged": 0, "drifted": 0, "rotted": 0,
        "error": 0, "events": [],
        # one hash-bearing held item, never verified → 0 of 1 covered (H113)
        "coverage": {"verified": 0, "total": 1},
    }


def test_drift_report_counts_each_verdict(paths):
    a = insert_and_id(paths, "https://example.com/a")
    b = insert_and_id(paths, "https://example.com/b")
    c = insert_and_id(paths, "https://example.com/c")
    _record(paths, a, "unchanged")
    _record(paths, b, "drifted", observed="sha256:new")
    _record(paths, c, "rotted", observed=None, detail="gone")

    drift = run_doctor(paths)["custody"]["drift"]
    assert drift["checked"] == 3
    assert drift["unverified"] == 0  # every held item has a ledger verdict
    assert (drift["unchanged"], drift["drifted"], drift["rotted"], drift["error"]) == (
        1, 1, 1, 0,
    )
    # only the actionable losses (drift + rot) are itemized, sorted by id
    assert [e["id"] for e in drift["events"]] == sorted([b, c])
    assert {e["status"] for e in drift["events"]} == {"drifted", "rotted"}


def test_drift_names_held_items_never_verified_as_unverified(paths):
    # one item verified, two never checked: the two are unverified, NOT folded
    # into "unchanged" — "not in the drift counts" must never read as "clean"
    a = insert_and_id(paths, "https://example.com/a")
    insert_and_id(paths, "https://example.com/b")
    insert_and_id(paths, "https://example.com/c")
    _record(paths, a, "unchanged")

    drift = run_doctor(paths)["custody"]["drift"]
    assert drift["checked"] == 1
    assert drift["unverified"] == 2
    assert drift["unchanged"] == 1  # only the verified item, not the other two


def test_drift_states_its_verdicts_are_as_of_the_last_verify(paths):
    # the block is honest that its verdicts come from the ledger (the last
    # `scrolls verify`), not a live re-check this run, and how fresh that is
    a = insert_and_id(paths, "https://example.com/a")
    record_events(paths.db_path, [
        CustodyEvent(a, "2026-06-10T00:00:00+00:00", "unchanged",
                     "sha256:old", "sha256:old", None),
        CustodyEvent(a, "2026-06-14T12:00:00+00:00", "unchanged",
                     "sha256:old", "sha256:old", None),
    ])

    drift = run_doctor(paths)["custody"]["drift"]
    assert drift["basis"] == "last_verify"
    # as_of is the freshest verdict the picture rests on, not "now"
    assert drift["as_of"] == "2026-06-14T12:00:00+00:00"


def test_drift_report_uses_only_the_latest_event_per_item(paths):
    a = insert_and_id(paths, "https://example.com/a")
    _record(paths, a, "drifted", observed="sha256:new")
    _record(paths, a, "unchanged")  # a later re-verify found it back in sync

    drift = run_doctor(paths)["custody"]["drift"]
    assert drift["checked"] == 1
    assert drift["unchanged"] == 1
    assert drift["drifted"] == 0
    assert drift["events"] == []


def test_drift_report_ignores_events_for_deleted_items(paths):
    # a verdict for an item no longer in the library is not this library's drift
    _record(paths, "web:ghost", "rotted", observed=None, detail="gone")
    drift = run_doctor(paths)["custody"]["drift"]
    assert drift["checked"] == 0
    assert drift["events"] == []


def test_drift_ignores_events_for_deleted_items_keeps_unverified_honest(paths):
    # the ghost's verdict is dropped (not this library's drift), and the one
    # held item — which has no verdict of its own — is named unverified
    insert_item(paths.db_path, _web_item("https://example.com/a", fetched=True))
    _record(paths, "web:ghost", "rotted", observed=None, detail="gone")
    drift = run_doctor(paths)["custody"]["drift"]
    assert drift["checked"] == 0
    assert drift["unverified"] == 1


def test_doctor_survives_a_library_without_the_ledger_table(paths):
    # a v6 library never migrated to v7 has no custody_events table; doctor's
    # drift aggregation must read it as empty, not crash
    insert_item(paths.db_path, _web_item("https://example.com/a", fetched=True))
    conn = sqlite3.connect(paths.db_path)
    with conn:
        conn.execute("DROP TABLE custody_events")
    conn.close()

    drift = run_doctor(paths)["custody"]["drift"]
    assert drift["checked"] == 0
    assert drift["events"] == []
    # no ledger at all, so the held item is unverified, not silently clean
    assert drift["unverified"] == 1
    assert drift["basis"] == "last_verify"
    # no ledger ⇒ 0 of the 1 verifiable held item carries a verdict (H113)
    assert drift["coverage"] == {"verified": 0, "total": 1}


# --- recheck coverage on the drift block (cap 1, roadmap H113) ---


def test_drift_report_carries_recheck_coverage(paths):
    # of the verifiable (hash-bearing) held items, how many carry a verdict —
    # the coverage fraction the standalone audit now reports at parity with
    # `scrolls maintain`'s recheck block (H109)
    a = insert_and_id(paths, "https://example.com/a")
    b = insert_and_id(paths, "https://example.com/b")
    insert_and_id(paths, "https://example.com/c")  # held, never verified
    _record(paths, a, "unchanged")
    _record(paths, b, "drifted", observed="sha256:new")

    drift = run_doctor(paths)["custody"]["drift"]
    assert drift["coverage"] == {"verified": 2, "total": 3}


def test_drift_coverage_verified_equals_the_checked_count(paths):
    # `coverage.verified` ≡ `drift.checked` by construction: every verdict-bearing
    # held item is hash-bearing (verify never runs on a reference-only item, which
    # has no baseline hash to diff), so the coverage numerator equals the block's
    # own `checked` count — the within-block convergence H113 pins.
    a = insert_and_id(paths, "https://example.com/a")
    insert_and_id(paths, "https://example.com/b")  # never verified
    _record(paths, a, "unchanged")

    drift = run_doctor(paths)["custody"]["drift"]
    assert drift["coverage"]["verified"] == drift["checked"] == 1


def test_drift_coverage_denominator_excludes_reference_only(paths):
    # a reference-only capture has no baseline hash to diff a re-fetch against, so
    # it is unverifiable and excluded from the coverage denominator — coverage
    # measures progress over what *can* be covered, and so can reach full (100%)
    # even while the honest `unverified` count still names the unverifiable item.
    a = insert_and_id(paths, "https://example.com/a")  # hash-bearing
    insert_item(paths.db_path, _web_item("https://example.com/ref"))  # reference-only
    _record(paths, a, "unchanged")

    drift = run_doctor(paths)["custody"]["drift"]
    # the one verifiable item is verified → full coverage; the reference-only
    # item is not in the denominator (and stays in the `unverified` count)
    assert drift["coverage"] == {"verified": 1, "total": 1}
    assert drift["unverified"] == 1  # the reference-only item, never verifiable


def test_drift_does_not_affect_issues_or_exit_code(paths, capsys):
    a = insert_and_id(paths, "https://example.com/a")
    _record(paths, a, "drifted", observed="sha256:new")
    _record(paths, insert_and_id(paths, "https://example.com/b"), "rotted",
            observed=None, detail="gone")

    exit_code = main(["doctor"])
    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0  # drift/rot are reported, not repairable drift
    assert report["issues"] == 0
    assert report["custody"]["drift"]["drifted"] == 1
    assert report["custody"]["drift"]["rotted"] == 1


# --- enrichment re-derivability: stale-ruleset signal (cap 8, H20→H25) ---
#
# `scrolls classify` stamps `classified_ruleset` = the ruleset fingerprint that
# produced a category (roadmap H20). Doctor reports rules-classified items
# whose stored fingerprint no longer matches the live `RULESET_FINGERPRINT` —
# classified under a *superseded* ruleset. Like the drift block, this is
# report-only: a stale fingerprint means the ruleset changed, not that the
# category is wrong, so it never feeds `issues`/the exit code and doctor never
# auto-reclassifies (custody §2.4 — regenerate on request, never silent
# overwrite).


def _classified_item(url, *, ruleset, by="rules-v1", basis="title-pattern"):
    """A rules-classified web item carrying a given ruleset fingerprint."""
    provenance = {"adapter": "web", "fetched_at": "2026-06-12T08:00:00+00:00",
                  "classified_by": by, "classified_basis": basis}
    if ruleset is not None:
        provenance["classified_ruleset"] = ruleset
    return _web_item(url, fetched=True, category="tutorial", provenance=provenance)


def test_enrichment_counts_an_item_classified_under_the_current_ruleset_as_current(paths):
    from scrolls.classify import RULESET_FINGERPRINT
    insert_item(paths.db_path, _classified_item(
        "https://example.com/a", ruleset=RULESET_FINGERPRINT))
    enrichment = run_doctor(paths)["custody"]["enrichment"]
    assert enrichment["classified"] == 1
    assert enrichment["current"] == 1
    assert enrichment["stale"] == 0
    assert enrichment["items"] == []


def test_enrichment_flags_an_item_classified_under_a_superseded_ruleset_as_stale(paths):
    insert_item(paths.db_path, _classified_item(
        "https://example.com/old", ruleset="deadbeef0000"))
    enrichment = run_doctor(paths)["custody"]["enrichment"]
    assert enrichment["classified"] == 1
    assert enrichment["stale"] == 1
    assert enrichment["current"] == 0
    # the stale item is named so a reader can target a re-classify
    assert enrichment["items"] == [
        {"id": make_item_id("web", None, "https://example.com/old"),
         "ruleset": "deadbeef0000"}
    ]


def test_enrichment_names_a_pre_fingerprint_classification_as_unfingerprinted(paths):
    # classified before H20: an engine stamp but no ruleset fingerprint — we
    # cannot tell if a re-classify would differ, so it is unknown, not current
    insert_item(paths.db_path, _classified_item(
        "https://example.com/legacy", ruleset=None))
    enrichment = run_doctor(paths)["custody"]["enrichment"]
    assert enrichment["classified"] == 1
    assert enrichment["unfingerprinted"] == 1
    assert enrichment["current"] == 0
    assert enrichment["stale"] == 0


def test_enrichment_ignores_non_rules_classifications(paths):
    # the ruleset fingerprint is a rules-engine concept; an LLM-classified item
    # (a different re-derivability axis) is out of scope, not counted stale
    insert_item(paths.db_path, _classified_item(
        "https://example.com/llm", ruleset=None, by="llm-v1"))
    enrichment = run_doctor(paths)["custody"]["enrichment"]
    assert enrichment["classified"] == 0
    assert enrichment["unfingerprinted"] == 0


# --- per-source enrichment staleness (cap 8 + cap 1, roadmap H135) ---
#
# H104/H121 split the *custody* picture per source (`custody.by_source` →
# tiers/drift/coverage). H135 adds the re-derivability counterpart on the
# classification axis: a `by_source` sub-map under `custody.enrichment` naming
# how much stale-ruleset debt each source carries, so an operator can target a
# `classify --stale` at the source with the most. (The summary axis gets its own
# `summaries.by_source` in H171 — but attributed per contributing source and not
# summing to the whole, since a concept summary spans a cluster; see the
# `summaries` docstring and the per-source tests below.)


def _classified_arxiv(source_id, *, ruleset):
    """A rules-classified arxiv item carrying a given ruleset fingerprint."""
    return ScrollItem(
        id=f"arxiv:{source_id}", source="arxiv", source_id=source_id,
        url=f"https://arxiv.org/abs/{source_id}",
        saved_at="2026-06-12T08:00:00+00:00",
        category="tutorial", stage="fetched",
        extracted_text="paper", content_hash=f"sha256:{source_id}",
        provenance={"adapter": "arxiv", "fetched_at": "2026-06-12T08:00:00+00:00",
                    "classified_by": "rules-v1", "classified_basis": "weak-source",
                    "classified_ruleset": ruleset})


def test_enrichment_by_source_is_empty_when_no_stale_classifications(paths):
    from scrolls.classify import RULESET_FINGERPRINT
    # one current classification — no stale debt → the honest empty map
    insert_item(paths.db_path, _classified_item(
        "https://example.com/a", ruleset=RULESET_FINGERPRINT))
    enrichment = run_doctor(paths)["custody"]["enrichment"]
    assert enrichment["stale"] == 0
    assert enrichment["by_source"] == {}


def test_enrichment_by_source_is_empty_for_an_empty_library(paths):
    # no held items → nothing classified → the honest empty map (stable, never None)
    assert run_doctor(paths)["custody"]["enrichment"]["by_source"] == {}


def test_enrichment_by_source_groups_stale_classifications_per_source(paths):
    # two stale web items + one stale arxiv item, classified under a superseded
    # ruleset: the breakdown names which source carries the most stale debt.
    insert_item(paths.db_path, _classified_item(
        "https://example.com/old1", ruleset="deadbeef0000"))
    insert_item(paths.db_path, _classified_item(
        "https://example.com/old2", ruleset="deadbeef0000"))
    insert_item(paths.db_path, _classified_arxiv("1", ruleset="deadbeef0000"))

    enrichment = run_doctor(paths)["custody"]["enrichment"]
    assert enrichment["stale"] == 3
    # sorted keys, the stale count per source
    assert enrichment["by_source"] == {"arxiv": 1, "web": 2}
    assert list(enrichment["by_source"]) == ["arxiv", "web"]


def test_enrichment_by_source_sums_to_the_whole_enrichment_stale(paths):
    # the load-bearing convergence (H104/H121 posture, on the enrichment axis):
    # every stale item lands in exactly one source group, so summing the groups
    # re-counts the whole-library `stale`.
    from scrolls.classify import RULESET_FINGERPRINT
    insert_item(paths.db_path, _classified_item(
        "https://example.com/old", ruleset="deadbeef0000"))
    insert_item(paths.db_path, _classified_item(  # current — not stale
        "https://example.com/cur", ruleset=RULESET_FINGERPRINT))
    insert_item(paths.db_path, _classified_arxiv("1", ruleset="cafe00000000"))

    enrichment = run_doctor(paths)["custody"]["enrichment"]
    assert sum(enrichment["by_source"].values()) == enrichment["stale"] == 2


def test_enrichment_by_source_omits_a_source_with_no_stale_classifications(paths):
    from scrolls.classify import RULESET_FINGERPRINT
    # arxiv is current (not stale); only web carries stale debt → arxiv omitted
    insert_item(paths.db_path, _classified_item(
        "https://example.com/old", ruleset="deadbeef0000"))
    insert_item(paths.db_path, _classified_arxiv("1", ruleset=RULESET_FINGERPRINT))

    enrichment = run_doctor(paths)["custody"]["enrichment"]
    assert enrichment["by_source"] == {"web": 1}  # arxiv (clean) omitted


def test_enrichment_by_source_never_feeds_issues_or_the_exit_code(paths):
    # report-only like the rest of the custody block: a stale-debt source is a
    # view, never a structural issue.
    insert_item(paths.db_path, _classified_item(
        "https://example.com/old", ruleset="deadbeef0000"))
    report = run_doctor(paths)
    assert report["custody"]["enrichment"]["by_source"] == {"web": 1}
    assert report["issues"] == 0


def test_per_item_confidence_marker_converges_with_the_doctor_aggregate(paths):
    # the recency an agent reads on each item (`classification.confidence.freshness`,
    # H21) and the count doctor aggregates (`custody.enrichment`) share one
    # `classification_freshness` derivation, so they can never disagree: doctor's
    # stale/current/unfingerprinted counts equal the rollup of the per-item markers
    from collections import Counter

    from scrolls.classify import RULESET_FINGERPRINT
    from scrolls.items import classification_provenance, list_items

    insert_item(paths.db_path, _classified_item(
        "https://example.com/fresh", ruleset=RULESET_FINGERPRINT))
    insert_item(paths.db_path, _classified_item(
        "https://example.com/old", ruleset="deadbeef0000"))
    insert_item(paths.db_path, _classified_item(
        "https://example.com/legacy", ruleset=None))
    insert_item(paths.db_path, _classified_item(
        "https://example.com/llm", ruleset=None, by="llm-v1"))

    # roll up the freshness each held item's own marker reports
    rolled = Counter()
    for item in list_items(paths.db_path):
        view = classification_provenance(item)
        if view and view["by"] == "rules-v1":
            rolled[view["confidence"].get("freshness")] += 1

    enrichment = run_doctor(paths)["custody"]["enrichment"]
    assert rolled["current"] == enrichment["current"] == 1
    assert rolled["stale"] == enrichment["stale"] == 1
    assert rolled["unknown"] == enrichment["unfingerprinted"] == 1  # doctor's name
    assert enrichment["classified"] == 3  # the LLM item is a different axis


def test_stale_ruleset_does_not_affect_issues_or_exit_code(paths, capsys):
    # report-only: a stale ruleset is not repairable drift, and doctor never
    # silently re-classifies — the stored category and provenance are untouched
    insert_item(paths.db_path, _classified_item(
        "https://example.com/old", ruleset="deadbeef0000"))
    exit_code = main(["doctor"])
    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["issues"] == 0
    assert report["custody"]["enrichment"]["stale"] == 1
    # the item was not rewritten: its old fingerprint and category still stand
    stored = list_items(paths.db_path)[0]
    assert stored.provenance["classified_ruleset"] == "deadbeef0000"
    assert stored.category == "tutorial"


# --- enrichment re-derivability: stale-summary signal (cap 8, H29) -------
#
# `scrolls kb --engine llm` stores each concept summary with a `members_hash`
# fingerprint of the scrolls it synthesized (`kb_llm.members_hash`). Doctor
# reports summary-eligible concepts (≥ MIN_MEMBERS rendered members) whose
# stored summary's fingerprint no longer matches the live members — the
# membership changed since synthesis, so the summary is regenerable. The
# summary-axis counterpart of the stale-ruleset enrichment block; like it,
# report-only: a stale summary means the members moved, not that the synthesis
# is wrong, so it never feeds `issues`/the exit code and doctor never
# auto-regenerates (the refresh is `kb --stale`, H31).


def _concept_item(item_id, concept, *, content_hash, source="web"):
    """An item carrying one concept and full custody (so it is clean).

    Provenance + a body + a hash keep it free of custody findings; it is
    written to disk by `_seed_eligible_concept` so it has a real scroll file
    and joins its concept group. `source` defaults to ``web`` (the single-source
    callers); the per-source `by_source` tests pass it to seed a cluster whose
    members span sources.
    """
    return ScrollItem(
        id=item_id, source=source, url=f"https://{source}.example.org/{item_id}",
        saved_at="2026-06-01T00:00:00+00:00", title=item_id,
        extracted_text="body", raw_text="body", concepts=(concept,),
        content_hash=content_hash, provenance={"fetched_at": "2026-06-01T00:00:00+00:00"})


def _seed_eligible_concept(paths, concept="BM25", hashes=("h1", "h2")):
    """Two rendered items sharing one concept; returns the live members digest.

    Scrolls are written to disk (via `write_scroll`) so the library stays
    structurally clean — the audit measures summary freshness, not drift.
    """
    from scrolls.kb_llm import members_hash

    rendered = []
    for n, h in enumerate(hashes):
        item = _concept_item(f"web:{concept.lower()}-{n}", concept, content_hash=h)
        rendered.append(_rendered(paths, item))
    return members_hash(rendered)


def _seed_multi_source_concept(paths, concept, members):
    """A rendered concept whose members span sources; returns the live digest.

    `members` is a sequence of ``(source, content_hash)`` pairs — one rendered
    item per pair — so the per-source `by_source` tests can build a cluster
    drawing on more than one source.
    """
    from scrolls.kb_llm import members_hash

    rendered = []
    for n, (source, h) in enumerate(members):
        item = _concept_item(
            f"{source}:{concept.lower()}-{n}", concept, content_hash=h, source=source)
        rendered.append(_rendered(paths, item))
    return members_hash(rendered)


def _store_summary(paths, slug, members_hash, *, engine="kb-llm-v1"):
    from scrolls.kb import ConceptSummary, save_concept_summary

    save_concept_summary(paths.db_path, ConceptSummary(
        slug=slug, display=slug.upper(), summary="How it shows up.",
        members_hash=members_hash, engine=engine, model="claude-opus-4-8",
        generated_at="2026-06-16T00:00:00+00:00"))


def test_summaries_counts_a_summary_over_current_members_as_current(paths):
    live = _seed_eligible_concept(paths)
    _store_summary(paths, "bm25", live)
    summaries = run_doctor(paths)["custody"]["summaries"]
    assert summaries["eligible"] == 1
    assert summaries["summarized"] == 1
    assert summaries["current"] == 1
    assert summaries["stale"] == 0
    assert summaries["never"] == 0
    assert summaries["items"] == []


def test_summaries_flags_a_summary_whose_members_changed_as_stale(paths):
    live = _seed_eligible_concept(paths)
    _store_summary(paths, "bm25", "stale-old-digest")
    summaries = run_doctor(paths)["custody"]["summaries"]
    assert summaries["eligible"] == 1
    assert summaries["summarized"] == 1
    assert summaries["stale"] == 1
    assert summaries["current"] == 0
    # the stale concept is named with both fingerprints so a re-synthesis can
    # be targeted and verified (the enrichment block's `items` posture)
    assert summaries["items"] == [
        {"slug": "bm25", "members_hash": "stale-old-digest", "live_hash": live}
    ]


def test_summaries_names_an_eligible_concept_with_no_summary_as_never(paths):
    _seed_eligible_concept(paths)
    summaries = run_doctor(paths)["custody"]["summaries"]
    assert summaries["eligible"] == 1
    assert summaries["summarized"] == 0
    assert summaries["never"] == 1
    assert summaries["current"] == 0
    assert summaries["stale"] == 0
    assert summaries["items"] == []


def test_summaries_treats_a_superseded_engine_as_stale(paths):
    # a summary from another engine is regenerated even with unchanged members
    # (the generators' `prior.engine == ENGINE` skip condition), so it is stale
    live = _seed_eligible_concept(paths)
    _store_summary(paths, "bm25", live, engine="kb-llm-v0")
    summaries = run_doctor(paths)["custody"]["summaries"]
    assert summaries["stale"] == 1
    assert summaries["current"] == 0


def test_summaries_block_is_empty_when_no_concept_is_summary_eligible(paths):
    # a single rendered item forms no ≥2-member concept — honest all-zero block
    insert_item(paths.db_path, _concept_item("web:solo", "Loner", content_hash="h1"))
    summaries = run_doctor(paths)["custody"]["summaries"]
    assert summaries["eligible"] == 0
    assert summaries["summarized"] == 0
    assert summaries["items"] == []


def test_summaries_invariant_eligible_equals_summarized_plus_never(paths):
    # the buckets partition the eligible concepts cleanly: a fresh + a stale +
    # a never-summarized concept sum to eligible, and summarized = current+stale
    fresh = _seed_eligible_concept(paths, concept="Fresh", hashes=("a", "b"))
    _seed_eligible_concept(paths, concept="Stale", hashes=("c", "d"))
    _seed_eligible_concept(paths, concept="New", hashes=("e", "f"))
    _store_summary(paths, "fresh", fresh)
    _store_summary(paths, "stale", "old-digest")
    summaries = run_doctor(paths)["custody"]["summaries"]
    assert summaries["eligible"] == 3
    assert summaries["current"] == 1
    assert summaries["stale"] == 1
    assert summaries["never"] == 1
    assert summaries["summarized"] == summaries["current"] + summaries["stale"]
    assert summaries["eligible"] == summaries["summarized"] + summaries["never"]


def test_stale_summary_does_not_affect_issues_or_exit_code(paths, capsys):
    # report-only: a stale summary is not repairable drift, and doctor never
    # silently re-synthesizes — the stored summary and its fingerprint stand
    from scrolls.kb import load_concept_summaries

    _seed_eligible_concept(paths)
    _store_summary(paths, "bm25", "stale-old-digest")
    exit_code = main(["doctor"])
    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["issues"] == 0
    assert report["custody"]["summaries"]["stale"] == 1
    # the summary was not rewritten: its old fingerprint still stands
    assert load_concept_summaries(paths.db_path)["bm25"].members_hash == "stale-old-digest"


def test_summaries_aggregate_converges_with_the_per_concept_view(paths):
    # the per-concept `summary_provenance` view a reader builds and the count
    # doctor aggregates share one `summary_freshness` derivation, so they can
    # never disagree — the H21 convergence, on the summary axis
    from collections import Counter

    from scrolls.kb import load_concept_summaries
    from scrolls.kb_llm import (
        eligible_concepts, members_hash, summary_provenance,
    )

    fresh = _seed_eligible_concept(paths, concept="Fresh", hashes=("a", "b"))
    _seed_eligible_concept(paths, concept="Stale", hashes=("c", "d"))
    _seed_eligible_concept(paths, concept="New", hashes=("e", "f"))
    _store_summary(paths, "fresh", fresh)
    _store_summary(paths, "stale", "old-digest")

    # roll up the freshness each eligible concept's own view reports
    stored = load_concept_summaries(paths.db_path)
    eligible = eligible_concepts(list_items(paths.db_path))
    rolled = Counter()
    for slug, entry in eligible.items():
        view = summary_provenance(stored.get(slug), members_hash(entry["items"]))
        rolled[view["freshness"] if view else "never"] += 1

    summaries = run_doctor(paths)["custody"]["summaries"]
    assert rolled["current"] == summaries["current"] == 1
    assert rolled["stale"] == summaries["stale"] == 1
    assert rolled["never"] == summaries["never"] == 1


# --- per-source stale-summary debt (roadmap H171) ---
# `custody.summaries.by_source` splits the stale-summary count per source — the
# summary-axis counterpart of `enrichment.by_source` (H135). A concept summary
# spans a *cluster* whose members can come from several sources, and the stored
# fingerprint records only the digest, not which member moved — so a stale
# summary is attributed to *every* source among its live members. One stale
# multi-source concept therefore counts toward each contributing source, and the
# map need **not** sum to `summaries.stale` (unlike drift/enrichment, where each
# item has exactly one source). Offenders-only, sorted keys, the H135 posture.


def test_summaries_by_source_is_empty_when_no_summary_is_stale(paths):
    # a current concept + a never-summarized concept contribute no stale debt, so
    # no source appears (the offenders-only map, honest empty)
    fresh = _seed_eligible_concept(paths, concept="Fresh", hashes=("a", "b"))
    _seed_eligible_concept(paths, concept="New", hashes=("c", "d"))
    _store_summary(paths, "fresh", fresh)
    summaries = run_doctor(paths)["custody"]["summaries"]
    assert summaries["stale"] == 0
    assert summaries["by_source"] == {}


def test_summaries_by_source_attributes_a_multi_source_stale_concept_to_each_source(paths):
    # a single stale concept whose members span web + arxiv counts toward *both*
    # sources — so by_source is {arxiv: 1, web: 1} while summaries.stale is 1, and
    # the per-source values sum to MORE than stale (the documented asymmetry).
    _seed_multi_source_concept(paths, "BM25", [("web", "h1"), ("arxiv", "h2")])
    _store_summary(paths, "bm25", "stale-old-digest")
    summaries = run_doctor(paths)["custody"]["summaries"]
    assert summaries["stale"] == 1
    assert summaries["by_source"] == {"arxiv": 1, "web": 1}
    # the multi-source stale concept is double-attributed, so the map need not
    # sum to `stale` (the H171 decision, unlike the enrichment/drift maps)
    assert sum(summaries["by_source"].values()) == 2 > summaries["stale"]


def test_summaries_by_source_omits_clean_sources_and_counts_offenders_only(paths):
    # web drives two stale concepts, arxiv one; reddit only participates in a
    # *current* concept, so it is omitted. Keys are sorted; a single-source stale
    # concept attributes to exactly its one source.
    _seed_multi_source_concept(paths, "Stale1", [("web", "a"), ("arxiv", "b")])
    _seed_multi_source_concept(paths, "Stale2", [("web", "c"), ("web", "d")])
    clean = _seed_multi_source_concept(paths, "Clean", [("reddit", "e"), ("web", "f")])
    _store_summary(paths, "stale1", "old-1")
    _store_summary(paths, "stale2", "old-2")
    _store_summary(paths, "clean", clean)
    summaries = run_doctor(paths)["custody"]["summaries"]
    assert summaries["stale"] == 2
    # web: in both stale concepts; arxiv: in one. reddit only touches the current
    # concept, so it carries no stale debt and is omitted.
    assert summaries["by_source"] == {"arxiv": 1, "web": 2}
    assert list(summaries["by_source"]) == ["arxiv", "web"]  # sorted keys
    assert "reddit" not in summaries["by_source"]


def test_summaries_by_source_never_feeds_issues_or_the_exit_code(paths, capsys):
    # report-only like the whole summaries block: a per-source stale count is a
    # refresh signal, not repairable drift
    _seed_multi_source_concept(paths, "BM25", [("web", "h1"), ("arxiv", "h2")])
    _store_summary(paths, "bm25", "stale-old-digest")
    exit_code = main(["doctor"])
    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["issues"] == 0
    assert report["custody"]["summaries"]["by_source"] == {"arxiv": 1, "web": 1}


# --- archive integrity: prior_hash ≡ snapshot.content_hash (roadmap H293) ---
#
# Every archived prior records `prior_hash` (the advertised fingerprint
# `archive list`/`archive restore --hash` key on) *separately* from its `snapshot`
# body (which carries its own `content_hash`). At archival time `adopt_incoming`
# writes `prior.content_hash` to both, so they agree by construction — but a
# corrupt/hand-edited bundle or a bad `import archive` could land a row where they
# diverge, and then `archive restore --hash <prior_hash>` silently adopts content
# with a *different* hash than advertised. The check folds over `archived_records`
# and flags any divergence, report-only (never `issues`/`fixed`/the exit code: the
# archive is a recovery convenience, not the root of trust — ADR 0106).


def _seed_archived_prior(
    paths, url="https://example.com/post", *, held_hash="sha256:held"
):
    """Hold an item, then adopt a divergent capture so one prior is archived.

    Leaves the held copy carrying the incoming content and one recoverable prior
    in `item_archive` whose `prior_hash` equals its snapshot's `content_hash` (the
    honest-by-construction shape). Returns the archived prior's item id.
    """
    held = _web_item(url, fetched=True, content_hash=held_hash)
    insert_item(paths.db_path, held)
    incoming = replace(
        held, extracted_text="a later capture", content_hash="sha256:moved"
    )
    adopt_incoming(paths.db_path, incoming, archived_at="2026-06-22T00:00:00+00:00")
    return held.id


def _tamper_archive(db_path, item_id, **columns):
    """Out-of-band rewrite of one archive row — a corrupt/hand-edited store."""
    assignments = ", ".join(f"{name} = ?" for name in columns)
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            f"UPDATE item_archive SET {assignments} WHERE item_id = ?",
            tuple(columns.values()) + (item_id,),
        )
    conn.close()


def test_clean_archive_reports_no_mismatch(paths):
    # a well-formed prior (prior_hash == snapshot.content_hash) is honest custody
    _seed_archived_prior(paths)
    archive = run_doctor(paths)["custody"]["archive"]
    assert archive == {"status": "ok", "checked": 1, "mismatched": 0, "events": []}


def test_empty_archive_reports_ok_with_zero_checked(paths):
    # an un-superseded library has no archived priors — the honest empty audit,
    # `status: "ok"` (the table was read), not the skipped default
    _rendered(paths, _web_item("https://example.com/post", fetched=True))
    archive = run_doctor(paths)["custody"]["archive"]
    assert archive == {"status": "ok", "checked": 0, "mismatched": 0, "events": []}


def test_uninitialized_library_leaves_archive_skipped(scrolls_home):
    # no db → run_doctor returns early; the archive block stays at its honest
    # skipped default (never a fabricated "0 mismatched")
    archive = run_doctor(get_paths())["custody"]["archive"]
    assert archive["status"] == "skipped"
    assert archive["mismatched"] == 0
    assert archive["events"] == []


def test_archive_integrity_flags_a_prior_hash_snapshot_hash_divergence(paths):
    item_id = _seed_archived_prior(paths)
    # corrupt the advertised fingerprint so it no longer matches the snapshot body
    _tamper_archive(paths.db_path, item_id, prior_hash="sha256:tampered")
    archive = run_doctor(paths)["custody"]["archive"]
    assert archive["status"] == "ok"
    assert archive["checked"] == 1
    assert archive["mismatched"] == 1
    assert archive["events"] == [
        {
            "item_id": item_id,
            "prior_hash": "sha256:tampered",
            "snapshot_hash": "sha256:held",
        }
    ]


def test_archive_mismatch_never_feeds_issues_or_the_exit_code(paths, capsys):
    # report-only like drift/conflicts/works: a tampered archive is a custody-honesty
    # signal, not repairable structural drift — doctor must not auto-rewrite the store
    item_id = _seed_archived_prior(paths)
    _tamper_archive(paths.db_path, item_id, prior_hash="sha256:tampered")
    exit_code = main(["doctor"])
    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["issues"] == 0
    assert report["fixed"] == 0
    assert report["custody"]["archive"]["mismatched"] == 1
    # no fabricated repair command on the offending event (no auto-rewrite — the
    # suggested-block orphan discipline; the event carries only the three fields)
    assert set(report["custody"]["archive"]["events"][0]) == {
        "item_id",
        "prior_hash",
        "snapshot_hash",
    }


def test_null_prior_hash_archive_row_is_not_a_defect(paths):
    # a NULL `prior_hash` is vacuously skipped (the `import_archive` NULL-safe
    # precedent): there is no advertised fingerprint to verify, so the row is
    # neither checked nor mismatched — even when the snapshot still carries a hash
    item_id = _seed_archived_prior(paths)
    _tamper_archive(paths.db_path, item_id, prior_hash=None)
    archive = run_doctor(paths)["custody"]["archive"]
    assert archive["checked"] == 0
    assert archive["mismatched"] == 0
    assert archive["events"] == []


def test_archive_integrity_flags_only_the_corrupt_row(paths):
    # two priors, one tampered: the clean row is checked-and-clean, the corrupt one
    # is named once with its diverging hashes
    clean = _seed_archived_prior(paths, "https://example.com/a", held_hash="sha256:a")
    bad = _seed_archived_prior(paths, "https://example.com/b", held_hash="sha256:b")
    _tamper_archive(paths.db_path, bad, prior_hash="sha256:wrong")
    archive = run_doctor(paths)["custody"]["archive"]
    assert archive["checked"] == 2
    assert archive["mismatched"] == 1
    assert [e["item_id"] for e in archive["events"]] == [bad]
    assert clean not in {e["item_id"] for e in archive["events"]}


def test_archive_check_skipped_under_a_source_scope(paths):
    # the archive is a single whole-library recovery store (like fts/orphan_scrolls),
    # not source-attributable — a `--source` audit leaves it at the skipped default
    # rather than reading a scope-induced "0 mismatched" over a partial store
    item_id = _seed_archived_prior(paths)
    _tamper_archive(paths.db_path, item_id, prior_hash="sha256:tampered")
    archive = run_doctor(paths, source="web")["custody"]["archive"]
    assert archive == {"status": "skipped", "checked": 0, "mismatched": 0, "events": []}


def test_archive_events_are_ordered_by_item_then_hash(paths):
    # deterministic ordering so the report is a stable line for diffs/dogfood reads
    a = _seed_archived_prior(paths, "https://example.com/a", held_hash="sha256:a")
    b = _seed_archived_prior(paths, "https://example.com/b", held_hash="sha256:b")
    _tamper_archive(paths.db_path, a, prior_hash="sha256:x")
    _tamper_archive(paths.db_path, b, prior_hash="sha256:y")
    archive = run_doctor(paths)["custody"]["archive"]
    assert [e["item_id"] for e in archive["events"]] == sorted([a, b])


# --- archive integrity survives the JSONL-backup round-trip (roadmap H295) ---
#
# H293 (above) added the report-only archive-integrity check; H294
# (`tests/test_cli.py`) pins that the *clean* recovery read-family survives an
# `export items` + `export archive` → `import items` + `import archive` round
# trip. The untested guarantee these tie together: a *corruption* (an archived
# prior whose advertised `prior_hash` diverges from its snapshot's
# `content_hash`) must NOT be laundered by the JSONL backup — it has to trip the
# alarm *identically* on a library rebuilt from the backup, never read clean
# (vision §2.4 — provenance/fidelity travel with every result; a backup may not
# silently repair a corruption it cannot actually fix). Correct-by-construction:
# `import_archive` stores the snapshot verbatim and dedups by
# `(item_id, prior_hash)`, never re-deriving `prior_hash` — so a regression
# guard, mutation-checked by *repairing* the backup row before import (the alarm
# then clears on the rebuild, proving the tie is load-bearing).


def _export_jsonl_backup(tmp_path, capsys):
    """Back up the *current* library to two JSONL files — `export items` +
    `export archive`, the whole-library backup (no bundle). Returns the two file
    paths. Reads `get_paths()` from the env, so call it before switching
    `SCROLLS_HOME` to the rebuild target."""
    capsys.readouterr()  # clear anything buffered
    assert main(["export", "items"]) == 0
    items_path = tmp_path / "library.jsonl"
    items_path.write_text(capsys.readouterr().out, encoding="utf-8")
    assert main(["export", "archive"]) == 0
    archive_path = tmp_path / "archive.jsonl"
    archive_path.write_text(capsys.readouterr().out, encoding="utf-8")
    return items_path, archive_path


def _rebuild_from_backup(root, monkeypatch, items_path, archive_path):
    """Rebuild a fresh library at `root` from the two JSONL backups (held rows
    then their archived priors) and return its `Paths`. Switches `SCROLLS_HOME`,
    so the source library's `run_doctor(paths)` must be read *before* this call."""
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    assert main(["init"]) == 0
    assert main(["import", "items", str(items_path)]) == 0
    assert main(["import", "archive", str(archive_path)]) == 0
    return get_paths()


def _repair_archive_backup(jsonl_text):
    """Rewrite an `export archive` JSONL so every prior's advertised `prior_hash`
    matches its snapshot's `content_hash` again — the honest store a clean
    library would have exported, the inverse of `_tamper_archive` on the backup
    wire. Used to prove the alarm-on-the-rebuild is load-bearing (repairing the
    backup must clear it)."""
    out = []
    for line in jsonl_text.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("prior_hash") is not None:
            row["prior_hash"] = row["snapshot"].get("content_hash")
        out.append(json.dumps(row))
    return "".join(s + "\n" for s in out)


def _seed_corrupt_plus_clean_archive(paths):
    """Seed `paths` with two archived priors — one clean, one whose `prior_hash`
    was tampered to diverge from its snapshot's `content_hash`. Returns the
    corrupt prior's item id (the one the integrity alarm must name)."""
    _seed_archived_prior(paths, "https://example.com/clean", held_hash="sha256:clean")
    corrupt = _seed_archived_prior(
        paths, "https://example.com/corrupt", held_hash="sha256:held"
    )
    _tamper_archive(paths.db_path, corrupt, prior_hash="sha256:tampered")
    return corrupt


def test_archive_integrity_alarm_survives_the_jsonl_backup_round_trip(
    paths, tmp_path, monkeypatch, capsys
):
    # A corrupt archived prior carried through `export archive` → `import archive`
    # is flagged *identically* by `doctor`'s `custody.archive` on the rebuilt
    # library — the backup does not launder the corruption (H293 × H294 tie).
    corrupt = _seed_corrupt_plus_clean_archive(paths)

    archive_a = run_doctor(paths)["custody"]["archive"]
    # sanity: A names exactly the corrupt row, the clean prior passes — a genuine
    # mismatch travels (a vacuous all-clean read would pass the A==B tie falsely)
    assert archive_a["status"] == "ok"
    assert archive_a["checked"] == 2
    assert archive_a["mismatched"] == 1
    assert archive_a["events"] == [
        {
            "item_id": corrupt,
            "prior_hash": "sha256:tampered",
            "snapshot_hash": "sha256:held",
        }
    ]

    items_path, archive_path = _export_jsonl_backup(tmp_path, capsys)
    paths_b = _rebuild_from_backup(
        tmp_path / "library-b", monkeypatch, items_path, archive_path
    )

    # the rebuilt library holds the whole archive (both priors travelled) and trips
    # the alarm on the same offending event set with the same checked/mismatched —
    # byte-for-byte the report A read, never read clean
    archive_b = run_doctor(paths_b)["custody"]["archive"]
    assert archive_b == archive_a


def test_repairing_the_archive_backup_clears_the_alarm_on_the_rebuilt_library(
    paths, tmp_path, monkeypatch, capsys
):
    # Mutation guard: the alarm-on-the-rebuild is load-bearing. If the divergence is
    # *repaired* in the backup before import, the rebuilt library reads clean — so
    # the flag on B genuinely tracks the backup's content, not a phantom.
    _seed_corrupt_plus_clean_archive(paths)
    assert run_doctor(paths)["custody"]["archive"]["mismatched"] == 1  # A is dirty

    items_path, archive_path = _export_jsonl_backup(tmp_path, capsys)
    archive_path.write_text(
        _repair_archive_backup(archive_path.read_text(encoding="utf-8")),
        encoding="utf-8",
    )

    paths_b = _rebuild_from_backup(
        tmp_path / "library-b", monkeypatch, items_path, archive_path
    )
    archive_b = run_doctor(paths_b)["custody"]["archive"]
    assert archive_b == {"status": "ok", "checked": 2, "mismatched": 0, "events": []}
