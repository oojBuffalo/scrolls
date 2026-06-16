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

import pytest

from scrolls.cli import main
from scrolls.custody import CustodyEvent, record_events
from scrolls.db import init_db
from scrolls.doctor import run_doctor
from scrolls.items import ScrollItem, insert_item, list_items, make_item_id
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
    assert custody == {
        "score": 100, "issues": 0,
        "tiers": {"full": 1, "partial": 0, "reference": 0}, "findings": [],
        "drift": {
            "basis": "last_verify", "as_of": None,
            "checked": 0, "unverified": 1,
            "unchanged": 0, "drifted": 0, "rotted": 0,
            "error": 0, "events": [],
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
