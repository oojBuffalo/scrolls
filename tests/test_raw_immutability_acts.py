"""The raw-immutability act-surface contract (roadmap H408) — one completeness-asserted invariant.

The fifteenth **contract-consolidation** cell, the CLI sibling of H364's MCP
holdings-immutability guard on the *raw-bytes* axis. Where H364 pins that no
registered MCP write tool carries a capture-destroying verb, this pins the
durable on-disk consequence over *every* CLI act: running a write command leaves
the held raw `scrolls/` capture tree **byte-identical** (a `{relpath → sha256}`
whole-tree hash, the H363 idiom) — except a named set of acts that legitimately
write raw. So no recompile/verify/maintain/reconcile/classify-adjacent op ever
silently mutates or destroys a held capture (custody-vision §2.4, *raw is
sacred; drift is a recorded event, never an overwrite*).

Two faces, the H388/H406 shape:

1. **The completeness keystone** — `_RAW_PRESERVING_ACTS` ∪ `_RAW_WRITING_ACTS`
   must partition `_CLI_WRITE_COMMANDS` (H394) *exactly*, so a *new* write
   command fails the contract until it declares whether it touches raw (the H364
   registry-completeness mechanism on the CLI raw-bytes axis).
2. **The behavioural matrix** — over the shared wide fixture
   (`seed_read_surface_determinism_mix`), each preserving act leaves the
   `scrolls/` tree byte-identical, and each named raw-writer *actually* mutates
   it (the exemption is earned, not a silent skip — and the kind of mutation is
   pinned: a capture adds a file, a delete removes one, a re-render modifies
   bytes in place). The sabotage proves the teeth and the isolation: a `verify`
   that re-renders (overwrites) the held scroll on drift — the precise
   custody violation — fails *only* the `verify` leg.

**Roadmap correction (the H404/H407 precedent).** The H408 sketch grouped acts
by *capture/adopt semantics*: `save`/`ingest`/the `import *` family as
raw-writers, `classify`/`follow`/`sync`/`export *` as preservers. But H408
measures the literal `scrolls/` *file* tree (the H363 whole-tree hash), and on
that axis the partition is determined by which handlers call
`render.write_scroll` (or unlink a scroll), not by what they do to the DB:

- **`classify`/`set` are raw-*writers*** — both re-render the held scroll to keep
  its frontmatter in sync with the DB (`cli._cmd_classify`/`_cmd_set` →
  `write_scroll`). The captured *body* is preserved, but the file bytes change,
  so on the whole-file axis they mutate `scrolls/`.
- **`add`/`sync`/`archive restore` and the whole `import *` family are
  *preservers*** — they write DB rows (or a subscription/archive row) only and
  never render: `add`/`sync` register *detected* rows (`pipeline.register_url` /
  `feeds.sync_subscription`, "exactly what `scrolls add` would store"),
  `archive restore` adopts through `adopt_incoming` ("no new write path"), and
  every importer defers rendering to the documented `doctor --fix`/`md` restore
  (`_cmd_import_items`' own comment). On the `scrolls/`-file axis they touch
  nothing.

So the raw-writers are exactly the four scroll-file mutators —
`ingest` (captures + renders a new scroll), `classify`/`set` (re-render a held
scroll's frontmatter), and `rm` (deletes the scroll file) — and the other
twenty-one writes are raw-immutable. `export *` is outside this contract's
universe (H394 classified it `_CLI_EXEMPT_READS`, a read transport).
"""

import dataclasses
import hashlib
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

import scrolls.cli as cli
import scrolls.feeds as feeds
import scrolls.pipeline as pipeline
from scrolls.cli import main
from scrolls.items import ScrollItem
from scrolls.paths import get_paths
from scrolls.render import write_scroll
from scrolls.sources.http import ConditionalText

from read_surface_fixture import seed_read_surface_determinism_mix

# The live argparse write registry the H394 contract holds to the CLI surface.
# Keying the partition to it makes a *new* write command force a raw-or-not
# decision here (it first fails H394's classification until declared a write,
# then this contract until it declares raw-preserving-or-writing).
from test_cli_determinism import _CLI_WRITE_COMMANDS  # noqa: E402


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


# --- the deterministic offline seams -----------------------------------------

# A one-post RSS feed the patched fetchers return, so `follow`/`sync` validate
# and register an entry without the network (the post link detects to `web`).
_FEED_URL = "https://blog.example.com/feed.xml"
_FEED_TEXT = (
    '<?xml version="1.0"?><rss version="2.0"><channel>'
    "<title>A Weblog</title><link>https://blog.example.com/</link>"
    "<item><title>Post one</title>"
    "<link>https://blog.example.com/2026/post-one/</link></item>"
    "</channel></rss>"
)


def _recapture_drift(item: ScrollItem) -> ScrollItem:
    """A deterministic re-capture that always reports a changed body → `drifted`."""
    return dataclasses.replace(item, content_hash="sha256:reverified")


def _fake_fetch(item: ScrollItem) -> ScrollItem:
    """An offline fetch adapter: a captured body + hash, so `ingest` renders a
    scroll and `fetch` advances a detected item — without the network."""
    return dataclasses.replace(
        item, stage="fetched", title="Captured", extracted_text="captured body",
        content_hash="sha256:captured",
    )


@pytest.fixture
def offline_seams(monkeypatch):
    """Patch every network edge a write act reaches so the whole surface runs
    offline and deterministically — the verify re-capture, the feed fetch/
    conditional-GET seams, and the fetch adapter table in *both* the namespaces
    that read it (`pipeline` for `ingest`, `cli` for `fetch`)."""
    monkeypatch.setattr(cli, "live_recapture", _recapture_drift)
    monkeypatch.setattr(feeds, "_get_text", lambda url: _FEED_TEXT)
    monkeypatch.setattr(
        feeds, "_get_conditional",
        lambda url, etag, last_modified: ConditionalText(text=_FEED_TEXT),
    )
    monkeypatch.setattr(
        pipeline, "FETCH_ADAPTERS",
        {**pipeline.FETCH_ADAPTERS, "web": _fake_fetch, "arxiv": _fake_fetch},
    )
    monkeypatch.setattr(
        cli, "FETCH_ADAPTERS",
        {**cli.FETCH_ADAPTERS, "web": _fake_fetch, "arxiv": _fake_fetch},
    )


# --- the held-raw whole-tree fingerprint (the H363 idiom) --------------------


def _scroll_tree(paths):
    """Map every held scroll under `scrolls/` to its sha256, keyed by POSIX
    relpath — the whole-tree fingerprint that catches *any* byte change to a
    held capture (a re-render, a tamper) or a deletion, not just a count drift."""
    return {
        file.relative_to(paths.root).as_posix(): hashlib.sha256(
            file.read_bytes()
        ).hexdigest()
        for file in sorted(paths.scrolls_dir.rglob("*.md"))
    }


def _key(path):
    """Flat string key for a command path — `("archive", "prune")` → "archive prune"."""
    return " ".join(path)


def _drain(capsys):
    capsys.readouterr()


def _export_to_file(capsys, argv, name):
    """Run an `export` command, capture its stdout, and write it to a temp file —
    the input the matching importer re-imports (the H395 round-trip idiom)."""
    assert main(argv) == 0
    out = capsys.readouterr().out
    target = Path(tempfile.mkdtemp()) / name
    target.write_text(out, encoding="utf-8")
    return target


def _file(name, content):
    target = Path(tempfile.mkdtemp()) / name
    target.write_text(content, encoding="utf-8")
    return target


# --- the act drivers ---------------------------------------------------------
# Each driver performs one write act (plus any pre-state) over the seeded
# fixture. They never assert the scroll tree themselves — the harness hashes
# `scrolls/` around each call. A non-zero exit on a legitimately-empty selection
# (e.g. a foreign import of a held url) is fine: the contract is about *raw*, not
# the report, so drivers tolerate it unless a clean exit is the point.


def _act_add(capsys):
    assert main(["add", "https://arxiv.org/abs/2401.99999"]) == 0


def _act_agent_install(capsys):
    assert main(["agent", "install"]) == 0


def _act_fetch(capsys):
    # seed one detected row, then fetch it through the patched adapter → the row
    # advances to `fetched` in the DB, but `fetch` never renders a scroll
    assert main(["add", "https://example.com/to-fetch"]) == 0
    _drain(capsys)
    assert main(["fetch"]) == 0


def _act_follow(capsys):
    assert main(["follow", _FEED_URL]) == 0


def _act_init(capsys):
    assert main(["init"]) == 0


def _act_kb(capsys):
    assert main(["kb"]) == 0


def _act_reconcile(capsys):
    # the fixture's `web:hub` carries an unresolved import conflict to resolve
    assert main(["reconcile", "web:hub", "--keep-held"]) == 0


def _act_sync(capsys):
    assert main(["follow", _FEED_URL]) == 0
    _drain(capsys)
    assert main(["sync"]) == 0  # registers the feed entry as a detected row


def _act_x_login(capsys):
    """OAuth authorization: browser and network stubbed, credential store real."""
    from scrolls.x_oauth import TokenSet

    with mock.patch.dict(os.environ, {"SCROLLS_X_CLIENT_ID": "CID"}), mock.patch(
        "scrolls.cli.run_login_flow",
        return_value=TokenSet(access_token="A", refresh_token="R"),
    ):
        assert main(["x", "login"]) == 0


def _act_x_logout(capsys):
    assert main(["x", "logout"]) == 0


def _act_unfollow(capsys):
    assert main(["follow", _FEED_URL]) == 0
    _drain(capsys)
    assert main(["unfollow", _FEED_URL]) == 0


def _act_verify(capsys):
    assert main(["verify", "arxiv:dba"]) == 0  # drifts via the seam; never re-renders


def _act_archive_prune(capsys):
    assert main(["archive", "prune", "--before", "2030-01-01", "--apply"]) == 0


def _act_archive_restore(capsys):
    assert main(["archive", "restore", "web:archived"]) == 0  # adopts a prior in the DB


def _act_import_items(capsys):
    target = _export_to_file(capsys, ["export", "items"], "items.jsonl")
    assert main(["import", "items", str(target)]) == 0


def _act_import_bundle(capsys):
    target = _export_to_file(
        capsys, ["export", "bundle", "database", "--with-archive"], "bundle.md"
    )
    assert main(["import", "bundle", str(target)]) == 0


def _act_import_events(capsys):
    target = _export_to_file(capsys, ["export", "events"], "events.jsonl")
    assert main(["import", "events", str(target)]) == 0


def _act_import_archive(capsys):
    target = _export_to_file(capsys, ["export", "archive"], "archive.jsonl")
    assert main(["import", "archive", str(target)]) == 0


def _act_import_bookmarks(capsys):
    target = _file(
        "bookmarks.html",
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>\n"
        '<DL><DT><A HREF="https://arxiv.org/abs/2402.00001">Paper</A></DL>',
    )
    assert main(["import", "bookmarks", str(target)]) == 0


def _act_import_opml(capsys):
    target = _file(
        "feeds.opml",
        '<opml version="2.0"><body>'
        '<outline type="rss" text="X" xmlUrl="https://x.example/feed.xml"/>'
        "</body></opml>",
    )
    assert main(["import", "opml", str(target)]) == 0


def _act_import_pocket(capsys):
    target = _file(
        "pocket.csv",
        "url,time_added,status\nhttps://arxiv.org/abs/2402.00002,1614556800,unread\n",
    )
    assert main(["import", "pocket", str(target)]) == 0


def _act_import_takeout(capsys):
    target = _file(
        "watch-history.json",
        '[{"title":"Watched X","titleUrl":'
        '"https://www.youtube.com/watch?v=abc123xyz00","time":"2026-01-01T00:00:00Z"}]',
    )
    assert main(["import", "google-takeout", str(target)]) == 0


def _act_import_fieldtheory(capsys):
    root = Path(tempfile.mkdtemp()) / "ft"
    (root / "bookmarks").mkdir(parents=True)
    (root / "bookmarks" / "bookmarks.jsonl").write_text(
        '{"tweetId":"1","url":"https://x.com/i/status/1","text":"a thread"}\n',
        encoding="utf-8",
    )
    assert main(["import", "fieldtheory", "--root", str(root)]) == 0


# --- raw-writer drivers (the named exemptions) -------------------------------


def _act_classify(capsys):
    assert main(["classify"]) == 0  # re-renders the classified rendered scrolls


def _act_set(capsys):
    assert main(["set", "arxiv:dba", "category=reference"]) == 0  # re-renders one scroll


def _act_rm(capsys):
    assert main(["rm", "arxiv:dba"]) == 0  # deletes the held scroll file


def _act_ingest(capsys):
    assert main(["ingest", "https://newsite.example/post"]) == 0  # captures + renders


# --- the two registries — the completeness keystone --------------------------

# Every write whose held `scrolls/` tree must be byte-identical after the act.
_RAW_PRESERVING_ACTS = {
    ("add",): _act_add,
    ("agent", "install"): _act_agent_install,
    ("fetch",): _act_fetch,
    ("follow",): _act_follow,
    ("init",): _act_init,
    ("kb",): _act_kb,
    ("reconcile",): _act_reconcile,
    ("sync",): _act_sync,
    ("unfollow",): _act_unfollow,
    ("x", "login"): _act_x_login,
    ("x", "logout"): _act_x_logout,
    ("verify",): _act_verify,
    ("archive", "prune"): _act_archive_prune,
    ("archive", "restore"): _act_archive_restore,
    ("import", "items"): _act_import_items,
    ("import", "bundle"): _act_import_bundle,
    ("import", "events"): _act_import_events,
    ("import", "archive"): _act_import_archive,
    ("import", "bookmarks"): _act_import_bookmarks,
    ("import", "opml"): _act_import_opml,
    ("import", "pocket"): _act_import_pocket,
    ("import", "google-takeout"): _act_import_takeout,
    ("import", "fieldtheory"): _act_import_fieldtheory,
}

# The named raw-writers: the four acts that legitimately mutate the scroll tree,
# each tagged with the *kind* of mutation it earns (so the exemption is precise,
# not a blanket "anything goes").
_RAW_WRITING_ACTS = {
    ("ingest",): (_act_ingest, "added"),
    ("classify",): (_act_classify, "modified"),
    ("set",): (_act_set, "modified"),
    ("rm",): (_act_rm, "removed"),
}


# --- the harness -------------------------------------------------------------


def _seed_fixture(monkeypatch, home, capsys):
    """init + seed the wide read-surface mix into a fresh home, drain the output."""
    monkeypatch.setenv("SCROLLS_HOME", str(home))
    assert main(["init"]) == 0
    seed_read_surface_determinism_mix(get_paths())
    _drain(capsys)


def _preserving_violations(monkeypatch, tmp_path, capsys):
    """The set of preserving acts whose held `scrolls/` tree changed after the
    act (the matrix asserts this is empty; the sabotage asserts it is exactly
    `{verify}`). Each act runs over its *own* fresh seeded home."""
    violations = set()
    for index, (path, driver) in enumerate(_RAW_PRESERVING_ACTS.items()):
        _seed_fixture(monkeypatch, tmp_path / f"{index}-{_key(path).replace(' ', '-')}", capsys)
        before = _scroll_tree(get_paths())
        driver(capsys)
        _drain(capsys)
        if before != _scroll_tree(get_paths()):
            violations.add(path)
    return violations


# --- the keystone tests ------------------------------------------------------


def test_the_act_surface_partitions_the_write_registry():
    """The completeness keystone (roadmap H408): the preserving and writing act
    sets are disjoint and together cover *exactly* `_CLI_WRITE_COMMANDS` (H394),
    so a *new* CLI write command fails the contract until it declares whether it
    touches raw — the H364 registry-completeness mechanism on the raw-bytes axis."""
    preserving = set(_RAW_PRESERVING_ACTS)
    writing = set(_RAW_WRITING_ACTS)
    assert preserving.isdisjoint(writing)
    assert preserving | writing == set(_CLI_WRITE_COMMANDS), (
        "raw-classification drift: "
        f"unclassified={set(_CLI_WRITE_COMMANDS) - (preserving | writing)}, "
        f"unknown={(preserving | writing) - set(_CLI_WRITE_COMMANDS)}"
    )
    # disjoint + total ⇒ the count is exact (no command double-counted)
    assert len(preserving) + len(writing) == len(_CLI_WRITE_COMMANDS)
    # non-trivial: the raw-writers are exactly the four scroll-file mutators (a
    # registry that quietly emptied itself would still pass the partition)
    assert writing == {("ingest",), ("classify",), ("set",), ("rm",)}


# --- the behavioural matrix --------------------------------------------------


def test_every_raw_preserving_act_leaves_the_capture_tree_byte_identical(
    scrolls_home, offline_seams, monkeypatch, tmp_path, capsys
):
    """Over the wide non-vacuous fixture, *every* raw-preserving write leaves the
    held `scrolls/` tree byte-identical — no recompile/verify/reconcile/feed/
    import op ever silently mutates or destroys a held capture (custody §2.4)."""
    # non-vacuity: the fixture renders a real, multi-scroll tree across >1 source,
    # so byte-identity is a claim over actual holdings (an empty tree would pass
    # {} == {} trivially). The mix renders three scrolls — `arxiv:dba`/`arxiv:dbb`
    # (arxiv) and `web:hub` (web).
    _seed_fixture(monkeypatch, tmp_path / "sanity", capsys)
    tree = _scroll_tree(get_paths())
    assert len(tree) >= 3
    assert len({relpath.split("/")[1] for relpath in tree}) >= 2  # ≥2 source dirs

    assert _preserving_violations(monkeypatch, tmp_path, capsys) == set()


def test_every_named_raw_writer_actually_mutates_raw(
    scrolls_home, offline_seams, monkeypatch, tmp_path, capsys
):
    """Each named raw-writer *actually* changes the scroll tree — the exemption is
    earned, not a silent skip — and changes it in its declared way: `ingest` adds
    a scroll, `rm` removes one, `classify`/`set` modify bytes in place (a
    frontmatter re-render). A writer that left raw untouched would be a mis-grant
    of the exemption; this catches it."""
    for index, (path, (driver, kind)) in enumerate(_RAW_WRITING_ACTS.items()):
        _seed_fixture(monkeypatch, tmp_path / f"w{index}-{_key(path)}", capsys)
        before = _scroll_tree(get_paths())
        driver(capsys)
        _drain(capsys)
        after = _scroll_tree(get_paths())

        added = set(after) - set(before)
        removed = set(before) - set(after)
        modified = {k for k in set(before) & set(after) if before[k] != after[k]}
        assert before != after, f"{_key(path)} left raw unchanged — exemption not earned"
        if kind == "added":
            assert added and not removed and not modified, (_key(path), added, removed, modified)
        elif kind == "removed":
            assert removed and not added, (_key(path), added, removed, modified)
        else:  # modified
            assert modified and not added and not removed, (_key(path), added, removed, modified)


# --- the sabotage ------------------------------------------------------------


def test_a_verify_that_re_renders_the_held_capture_fails_only_its_leg(
    scrolls_home, offline_seams, monkeypatch, tmp_path, capsys
):
    """The sabotage proves the matrix has teeth and is *isolating*: a `verify`
    that overwrites the held scroll with the re-captured body on drift — the
    precise custody violation (drift must archive, never overwrite — §2.4) —
    fails *only* the `verify` leg. The other twenty preservers, whose paths never
    touch `scrolls/`, stay byte-identical.

    `cli.verify_item` is the function `verify` records its event through — and the
    *only* preserver in the registry that calls it. So injecting a `write_scroll`
    into it desyncs only `verify`; `kb`/`reconcile`/the imports/the feed ops flow
    through unrelated code and are untouched — the regression a single command's
    own test cannot see across the whole act surface at once."""
    # baseline: every preserver is clean
    assert _preserving_violations(monkeypatch, tmp_path / "base", capsys) == set()

    real_verify_item = cli.verify_item

    def _overwriting_verify(item, recapture, *, now):
        event = real_verify_item(item, recapture, now=now)
        if item.markdown_path:  # the violation: re-capture overwrites the held scroll
            write_scroll(get_paths(), recapture(item))
        return event

    monkeypatch.setattr(cli, "verify_item", _overwriting_verify)

    assert _preserving_violations(monkeypatch, tmp_path / "sab", capsys) == {("verify",)}
