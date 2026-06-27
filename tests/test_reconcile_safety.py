"""H402 — the reconcile-safety contract (ADR 0102).

The ninth **contract-consolidation** cell and the *removal*-axis sibling of
H396's refresh-safety contract. Where H396 pins that a recompile whose group
*still exists* refreshes the fenced region while sparing annotations, this pins
the opposite event: a compiled `library/` page whose group has **vanished** (a
reclassified category, a dropped concept/tag, an emptied source) is never
silently destroyed when it carries a hand annotation. `_reconcile_generated`
(ADR 0102) splits the two outcomes:

  * a stale page that carries a `@user` annotation outside its fence is
    **tombstoned** — its generated region is replaced by `kb._STALE_BODY` and the
    annotation is preserved byte-for-byte (raw annotation is sacred); and
  * a stale page with *no* annotation **is unlinked** (the "stale pages can't
    linger" guarantee — a recompile is authoritative over the generated tree).

This is **one** guard over *every* reconcilable dir-kind, retiring the scattered
per-kind reconcile tests (`test_kb_recompile_removes_stale_pages_but_keeps_user_files`
and `test_kb_stale_annotated_page_is_kept_with_a_tombstone` in `test_kb.py`, which
proved one dir-kind — `categories` — at a time; they stay as deeper regression
guards, the H395 discipline).

The **completeness keystone** (`test_reconcilable_kinds_equal_the_generated_dirs`):
the covered kinds must equal `kb._GENERATED_DIRS` *exactly*, and be disjoint from
`kb._GENERATED_FILES`. Only dir-kinds are reconcilable — `index.md`/`graph.md`/
`works.md` are always written (they land in `compile_kb`'s `written` set, so the
`if path in written` short-circuit never reconciles them). So a *new* reconcilable
page family fails the contract until it is given a reconcile-safety entry (the H364
registry-completeness mechanism on the deletion axis).

Each dir-kind is driven to the vanish event uniformly: a base item keeps the
directory alive (so the dir survives the reconcile and the test stays
non-vacuous), plus two dedicated items each owning a *unique* page on that kind's
axis — one whose page is annotated (must be tombstoned) and one left plain (must
be unlinked). Deleting both with `delete_item` makes exactly those two pages
vanish on the next compile, exercising **both** reconcile branches in one pass.

The sabotage (`test_tombstone_branch_has_teeth`) drops the `has_user_content`
tombstone branch so the reconcile unlinks an annotated stale page wholesale (the
exact failure mode the contract guards), and pins that the annotated page the
contract requires tombstoned is gone — the regression each per-kind leg catches.
"""

from collections import namedtuple

import pytest

import scrolls.kb as kb
from scrolls.cli import main
from scrolls.generated import generated_body
from scrolls.items import ScrollItem, delete_item, insert_item
from scrolls.paths import get_paths

# The reconcilable dir-kinds, asserted equal to `kb._GENERATED_DIRS` in the
# completeness keystone — this tuple *is* the registry the contract drives.
_RECONCILE_KINDS = ("sources", "categories", "concepts", "tags")

# Per kind, the two unique axis values — already valid slugs (lowercase ascii),
# so each maps to `library/<kind>/<value>.md` with no slugify surprise. The
# `keep*` page is annotated (→ tombstone), the `drop*` page is plain (→ unlink).
_VANISH_VALUES = {
    "sources": ("keepsrc", "dropsrc"),
    "categories": ("keepcat", "dropcat"),
    "concepts": ("keepcon", "dropcon"),
    "tags": ("keeptag", "droptag"),
}

# A distinctive token stamped into the vanishing page's generated body so the
# test can assert the stale rollup is gone after the tombstone (the note the
# probe appends never carries this token).
_MARKER = "MARKER"


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


def _make_rendered(item_id, source, title, *, category, concepts, tags):
    slug = title.lower().replace(" ", "-")
    return ScrollItem(
        id=item_id,
        source=source,
        url=f"https://example.org/{item_id}",
        saved_at="2026-06-01T00:00:00+00:00",
        title=title,
        category=category,
        concepts=tuple(concepts),
        tags=tuple(tags),
        links=(),
        markdown_path=f"scrolls/{source}/{slug}.md",
        stage="rendered",
        raw_text=f"body for {item_id}",
        content_hash=item_id,
    )


def _vanishing_item(item_id, kind, value):
    """A rendered item that owns a unique page on `kind`'s axis and base values
    on every other axis (so deleting it drops *only* its own `<kind>/<value>.md`
    — the shared base pages stay alive via the base item)."""
    source, category, concepts, tags = "web", "reference", ("databases",), ("sql",)
    if kind == "sources":
        source = value
    elif kind == "categories":
        category = value
    elif kind == "concepts":
        concepts = (value,)
    elif kind == "tags":
        tags = (value,)
    return _make_rendered(
        item_id, source, f"{_MARKER} {value}",
        category=category, concepts=concepts, tags=tags,
    )


# What a seed of one kind hands back: the two page paths and the two item ids to
# delete to make them vanish.
Vanish = namedtuple("Vanish", "keep_page drop_page keep_id drop_id")


def _seed_kind(scrolls_home, db, kind):
    """Seed a base item (keeps the dir alive) plus a keep/drop pair on `kind`'s
    axis, and return the page paths + ids the recompile will reconcile."""
    insert_item(db, _make_rendered(
        "reconcile-base", "web", f"{_MARKER} base",
        category="reference", concepts=("databases",), tags=("sql",),
    ))
    keep_value, drop_value = _VANISH_VALUES[kind]
    keep_id, drop_id = f"reconcile-{kind}-keep", f"reconcile-{kind}-drop"
    insert_item(db, _vanishing_item(keep_id, kind, keep_value))
    insert_item(db, _vanishing_item(drop_id, kind, drop_value))
    library = scrolls_home / "library"
    return Vanish(
        keep_page=library / kind / f"{keep_value}.md",
        drop_page=library / kind / f"{drop_value}.md",
        keep_id=keep_id,
        drop_id=drop_id,
    )


def _compile_then_vanish(scrolls_home, capsys, kind):
    """init → seed → compile → annotate the keep page → delete the pair →
    recompile. Returns (Vanish, the byte-for-byte note appended to keep_page).

    The keep page is annotated and the drop page left plain, so the recompile's
    reconcile must tombstone the first and unlink the second in one pass.
    """
    main(["init"])
    db = get_paths().db_path
    vanish = _seed_kind(scrolls_home, db, kind)
    capsys.readouterr()
    assert main(["kb"]) == 0
    capsys.readouterr()

    # both vanishing pages (and the dir) exist before the vanish — non-vacuous
    assert vanish.keep_page.is_file(), f"{kind}: keep page was not compiled"
    assert vanish.drop_page.is_file(), f"{kind}: drop page was not compiled"

    # annotate the keep page with a @user note after the fence (the suffix region)
    keep_value = _VANISH_VALUES[kind][0]
    note = f"\n<!-- @user -->\nKept annotation for the {keep_value} page.\n"
    vanish.keep_page.write_text(
        vanish.keep_page.read_text(encoding="utf-8") + note, encoding="utf-8"
    )

    # both groups vanish; their pages are no longer written this run
    assert delete_item(db, vanish.keep_id)
    assert delete_item(db, vanish.drop_id)
    assert main(["kb"]) == 0
    capsys.readouterr()
    return vanish, note


def test_reconcilable_kinds_equal_the_generated_dirs():
    """The completeness keystone (roadmap H402): the covered reconcilable kinds
    equal `kb._GENERATED_DIRS` exactly and exclude `kb._GENERATED_FILES` (the
    always-written pages are never reconciled), so a *new* reconcilable page
    family fails until given a reconcile-safety entry (the H364 mechanism on the
    deletion axis)."""
    assert set(_RECONCILE_KINDS) == set(kb._GENERATED_DIRS), (
        f"coverage drift vs kb._GENERATED_DIRS: "
        f"uncovered={set(kb._GENERATED_DIRS) - set(_RECONCILE_KINDS)}, "
        f"unknown={set(_RECONCILE_KINDS) - set(kb._GENERATED_DIRS)}"
    )
    assert set(_RECONCILE_KINDS).isdisjoint(kb._GENERATED_FILES), (
        "an always-written file-kind is not reconcilable"
    )
    assert len(set(_RECONCILE_KINDS)) == len(_RECONCILE_KINDS)  # no duplicate key


@pytest.mark.parametrize("kind", _RECONCILE_KINDS)
def test_reconcile_tombstones_annotated_and_unlinks_plain_stale_pages(
    scrolls_home, capsys, kind
):
    """For every reconcilable dir-kind: when its page's group vanishes, an
    annotated stale page is tombstoned (annotation byte-for-byte, generated body
    replaced by `_STALE_BODY`) and a plain stale page is unlinked, while the
    dir survives (ADR 0102)."""
    vanish, note = _compile_then_vanish(scrolls_home, capsys, kind)

    # the annotated page is kept as a tombstone, not deleted
    assert vanish.keep_page.is_file(), (
        f"{kind}: an annotated stale page was destroyed instead of tombstoned"
    )
    tombstoned = vanish.keep_page.read_text(encoding="utf-8")
    assert tombstoned.endswith(note), f"{kind}: the @user annotation was not preserved verbatim"
    assert generated_body(tombstoned).strip() == kb._STALE_BODY, (
        f"{kind}: the generated region is not the tombstone body"
    )
    assert _MARKER not in tombstoned, f"{kind}: the stale rollup lingered in a tombstone"

    # the plain page is removed (stale pages can't linger)
    assert not vanish.drop_page.exists(), f"{kind}: a plain stale page was not unlinked"

    # the directory itself survives (the base item still populates it)
    assert vanish.keep_page.parent.is_dir(), f"{kind}: the dir was removed despite a live base page"


def test_tombstone_branch_has_teeth(scrolls_home, capsys, monkeypatch):
    """Sabotage: drop the `has_user_content` tombstone branch so the reconcile
    unlinks an annotated stale page wholesale. The annotated page each per-kind
    leg requires tombstoned is gone — the regression the contract catches (a
    global helper patch fails every leg; one representative kind proves it)."""
    monkeypatch.setattr(kb, "has_user_content", lambda text: False)
    vanish, _ = _compile_then_vanish(scrolls_home, capsys, "categories")
    assert not vanish.keep_page.exists(), (
        "sabotage did not reach the unlink branch — the teeth test is vacuous"
    )
