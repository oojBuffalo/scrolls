"""Bundles carry media in an opt-in sidecar (ADR 0115, issue #12).

A Markdown bundle is lossless for text and custody state but holds media only
as re-fetchable references, so anything that rotted upstream is gone from a
fresh library. `export bundle --with-media DIR` writes the in-scope items' held
files beside the bundle, with a SHA-256 manifest; `import bundle` adopts them
when the sidecar sits beside the bundle (or is named with `--media`), checking
every hash and never overwriting a file the library already holds. The default
bundle is unchanged.
"""

import hashlib
import json

import pytest

from scrolls.cli import main
from scrolls.items import ScrollItem, insert_item
from scrolls.paths import get_paths

PDF_BYTES = b"%PDF-1.4 the station report"
PNG_BYTES = b"\x89PNG figure bytes"


@pytest.fixture
def library_a(monkeypatch, tmp_path, capsys):
    """A library holding one in-scope item with two captured files."""
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-a"))
    main(["init"])
    paths = get_paths()
    _hold(paths, "media/wikipedia/station-1.pdf", PDF_BYTES)
    _hold(paths, "media/wikipedia/station-2.png", PNG_BYTES)
    insert_item(
        paths.db_path,
        _item(
            "wikipedia:en:Station",
            "Station database",
            media=(
                {"type": "pdf", "url": "https://u.example/Station.pdf",
                 "path": "media/wikipedia/station-1.pdf"},
                {"type": "image", "url": "https://u.example/fig.png",
                 "path": "media/wikipedia/station-2.png"},
                {"type": "video", "url": "https://u.example/big.webm",
                 "oversize": 100, "bytes": 5000},
            ),
        ),
    )
    _hold(paths, "media/wikipedia/other-1.png", b"out of scope")
    insert_item(
        paths.db_path,
        _item(
            "wikipedia:en:Other",
            "Unrelated page",
            media=({"type": "image", "url": "https://u.example/o.png",
                    "path": "media/wikipedia/other-1.png"},),
        ),
    )
    capsys.readouterr()
    return paths


def _item(item_id, title, **overrides):
    base = dict(
        id=item_id,
        source="wikipedia",
        url=f"https://example.org/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00",
        title=title,
        extracted_text=f"{title}. Body.",
        content_hash="sha256:" + hashlib.sha256(title.encode()).hexdigest(),
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def _hold(paths, relpath, payload):
    target = paths.root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


def _export(tmp_path, capsys, *extra):
    """Export the `database` bundle to `tmp_path/ml.md`; return (rc, stderr)."""
    code = main(["export", "bundle", "database", *extra])
    captured = capsys.readouterr()
    (tmp_path / "ml.md").write_text(captured.out, encoding="utf-8")
    return code, captured


def _library_b(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    capsys.readouterr()
    return get_paths()


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


# --- export -----------------------------------------------------------------


def test_the_default_bundle_is_unchanged_by_the_sidecar(library_a, tmp_path, capsys):
    main(["export", "bundle", "database"])
    plain = capsys.readouterr().out

    code, captured = _export(tmp_path, capsys, "--with-media", str(tmp_path / "ml.media"))

    assert code == 0
    assert captured.out == plain  # text-pure: the markdown never changes


def test_the_sidecar_holds_the_in_scope_files_and_a_manifest(library_a, tmp_path, capsys):
    sidecar = tmp_path / "ml.media"

    code, captured = _export(tmp_path, capsys, "--with-media", str(sidecar))

    assert code == 0
    manifest = [
        json.loads(line)
        for line in (sidecar / "MANIFEST.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert manifest == [
        {"path": "media/wikipedia/station-1.pdf", "sha256": _sha(PDF_BYTES),
         "bytes": len(PDF_BYTES), "item_id": "wikipedia:en:Station"},
        {"path": "media/wikipedia/station-2.png", "sha256": _sha(PNG_BYTES),
         "bytes": len(PNG_BYTES), "item_id": "wikipedia:en:Station"},
    ]
    assert (sidecar / "media/wikipedia/station-1.pdf").read_bytes() == PDF_BYTES
    assert not (sidecar / "media/wikipedia/other-1.png").exists()  # out of scope
    summary = json.loads(captured.err)["media"]
    assert summary == {
        "sidecar": str(sidecar),
        "files": 2,
        "bytes": len(PDF_BYTES) + len(PNG_BYTES),
        "missing": [],
        "uncaptured": 1,  # the declined video travels as a reference only
    }


def test_a_recorded_file_gone_from_disk_is_named_not_shipped(library_a, tmp_path, capsys):
    (library_a.root / "media/wikipedia/station-2.png").unlink()
    sidecar = tmp_path / "ml.media"

    code, captured = _export(tmp_path, capsys, "--with-media", str(sidecar))

    assert code == 0
    summary = json.loads(captured.err)["media"]
    assert summary["files"] == 1
    assert summary["missing"] == ["media/wikipedia/station-2.png"]
    lines = (sidecar / "MANIFEST.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["path"] for line in lines] == ["media/wikipedia/station-1.pdf"]


def test_a_non_empty_destination_is_refused_before_anything_is_written(
    library_a, tmp_path, capsys
):
    sidecar = tmp_path / "ml.media"
    sidecar.mkdir()
    (sidecar / "notes.txt").write_text("mine")

    code = main(["export", "bundle", "database", "--with-media", str(sidecar)])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "not empty" in json.loads(captured.err)["error"]
    assert sorted(p.name for p in sidecar.iterdir()) == ["notes.txt"]


def test_the_html_briefing_cannot_carry_a_sidecar(library_a, tmp_path, capsys):
    code = main(
        ["export", "bundle", "database", "--format", "html",
         "--with-media", str(tmp_path / "ml.media")]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "--with-media" in json.loads(captured.err)["error"]
    assert not (tmp_path / "ml.media").exists()


# --- import -----------------------------------------------------------------


def test_a_sidecar_beside_the_bundle_restores_the_files_byte_for_byte(
    library_a, monkeypatch, tmp_path, capsys
):
    _export(tmp_path, capsys, "--with-media", str(tmp_path / "ml.media"))
    library_b = _library_b(monkeypatch, tmp_path, capsys)

    assert main(["import", "bundle", str(tmp_path / "ml.md")]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 1
    assert payload["media"] == {
        "sidecar": str(tmp_path / "ml.media"),
        "adopted": 2,
        "already_held": 0,
        "unattached": [],
        "rejected": [],
    }
    assert (library_b.root / "media/wikipedia/station-1.pdf").read_bytes() == PDF_BYTES
    assert (library_b.root / "media/wikipedia/station-2.png").read_bytes() == PNG_BYTES
    # the take-it-with-me leg is now lossless for media: nothing is missing
    assert main(["doctor"]) == 0
    assert json.loads(capsys.readouterr().out)["missing_media"] == []


def test_a_sidecar_can_be_named_explicitly(library_a, monkeypatch, tmp_path, capsys):
    elsewhere = tmp_path / "carried" / "files"
    _export(tmp_path, capsys, "--with-media", str(elsewhere))
    library_b = _library_b(monkeypatch, tmp_path, capsys)

    assert main(["import", "bundle", str(tmp_path / "ml.md"), "--media", str(elsewhere)]) == 0

    assert json.loads(capsys.readouterr().out)["media"]["adopted"] == 2
    assert (library_b.root / "media/wikipedia/station-1.pdf").exists()


def test_a_named_sidecar_that_does_not_exist_is_an_error(
    library_a, monkeypatch, tmp_path, capsys
):
    _export(tmp_path, capsys)
    _library_b(monkeypatch, tmp_path, capsys)

    code = main(["import", "bundle", str(tmp_path / "ml.md"), "--media", str(tmp_path / "nope")])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "nope" in json.loads(captured.err)["error"]


def test_no_sidecar_is_an_honest_empty_media_block(library_a, monkeypatch, tmp_path, capsys):
    _export(tmp_path, capsys)
    _library_b(monkeypatch, tmp_path, capsys)

    assert main(["import", "bundle", str(tmp_path / "ml.md")]) == 0

    assert json.loads(capsys.readouterr().out)["media"] == {
        "sidecar": None,
        "adopted": 0,
        "already_held": 0,
        "unattached": [],
        "rejected": [],
    }


def test_a_file_the_library_already_holds_is_never_overwritten(
    library_a, monkeypatch, tmp_path, capsys
):
    _export(tmp_path, capsys, "--with-media", str(tmp_path / "ml.media"))
    library_b = _library_b(monkeypatch, tmp_path, capsys)
    _hold(library_b, "media/wikipedia/station-1.pdf", b"the held copy")

    assert main(["import", "bundle", str(tmp_path / "ml.md")]) == 0

    media = json.loads(capsys.readouterr().out)["media"]
    assert media["adopted"] == 1
    assert media["already_held"] == 1
    assert (library_b.root / "media/wikipedia/station-1.pdf").read_bytes() == b"the held copy"


def test_a_file_that_fails_its_hash_is_rejected_and_not_written(
    library_a, monkeypatch, tmp_path, capsys
):
    sidecar = tmp_path / "ml.media"
    _export(tmp_path, capsys, "--with-media", str(sidecar))
    (sidecar / "media/wikipedia/station-1.pdf").write_bytes(b"tampered in transit")
    library_b = _library_b(monkeypatch, tmp_path, capsys)

    code = main(["import", "bundle", str(tmp_path / "ml.md")])

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["imported"] == 1  # the rows still landed
    assert payload["media"]["adopted"] == 1
    assert payload["media"]["rejected"] == [
        {"path": "media/wikipedia/station-1.pdf", "reason": "sha256 mismatch"}
    ]
    assert not (library_b.root / "media/wikipedia/station-1.pdf").exists()
    assert list((library_b.root / "media/wikipedia").iterdir()) == [
        library_b.root / "media/wikipedia/station-2.png"
    ]  # no partial file left behind


def test_a_file_missing_from_the_sidecar_is_rejected(library_a, monkeypatch, tmp_path, capsys):
    sidecar = tmp_path / "ml.media"
    _export(tmp_path, capsys, "--with-media", str(sidecar))
    (sidecar / "media/wikipedia/station-2.png").unlink()
    _library_b(monkeypatch, tmp_path, capsys)

    assert main(["import", "bundle", str(tmp_path / "ml.md")]) == 1

    assert json.loads(capsys.readouterr().out)["media"]["rejected"] == [
        {"path": "media/wikipedia/station-2.png", "reason": "missing from the sidecar"}
    ]


@pytest.mark.parametrize(
    "bad_path",
    ["../escape.pdf", "/etc/passwd", "scrolls/wikipedia/x.md", "media/../../x.pdf"],
)
def test_an_unsafe_manifest_path_fails_the_import_before_anything_lands(
    library_a, monkeypatch, tmp_path, capsys, bad_path
):
    sidecar = tmp_path / "ml.media"
    _export(tmp_path, capsys, "--with-media", str(sidecar))
    line = {"path": bad_path, "sha256": _sha(b"x"), "bytes": 1, "item_id": "wikipedia:en:Station"}
    with (sidecar / "MANIFEST.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")
    library_b = _library_b(monkeypatch, tmp_path, capsys)

    code = main(["import", "bundle", str(tmp_path / "ml.md")])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "MANIFEST.jsonl line 3" in json.loads(captured.err)["error"]
    assert main(["list"]) == 0
    assert json.loads(capsys.readouterr().out) == []  # nothing imported
    assert not (library_b.root / "media").exists() or not any(
        (library_b.root / "media").rglob("*.*")
    )


def test_a_file_no_held_ref_points_at_is_unattached(library_a, monkeypatch, tmp_path, capsys):
    sidecar = tmp_path / "ml.media"
    _export(tmp_path, capsys, "--with-media", str(sidecar))
    _hold_in = sidecar / "media/wikipedia/stray-1.png"
    _hold_in.write_bytes(b"stray")
    line = {"path": "media/wikipedia/stray-1.png", "sha256": _sha(b"stray"),
            "bytes": 5, "item_id": "wikipedia:en:Station"}
    with (sidecar / "MANIFEST.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")
    library_b = _library_b(monkeypatch, tmp_path, capsys)

    assert main(["import", "bundle", str(tmp_path / "ml.md")]) == 0

    media = json.loads(capsys.readouterr().out)["media"]
    assert media["unattached"] == ["media/wikipedia/stray-1.png"]
    assert not (library_b.root / "media/wikipedia/stray-1.png").exists()


def test_a_dry_run_predicts_the_adoption_without_writing(
    library_a, monkeypatch, tmp_path, capsys
):
    _export(tmp_path, capsys, "--with-media", str(tmp_path / "ml.media"))
    library_b = _library_b(monkeypatch, tmp_path, capsys)

    assert main(["import", "bundle", str(tmp_path / "ml.md"), "--dry-run"]) == 0

    preview = json.loads(capsys.readouterr().out)
    assert preview["media"]["adopted"] == 2
    assert not (library_b.root / "media/wikipedia/station-1.pdf").exists()

    assert main(["import", "bundle", str(tmp_path / "ml.md")]) == 0
    assert json.loads(capsys.readouterr().out)["media"] == preview["media"]


# --- review round 1: file safety on adoption ---------------------------------


def test_a_held_file_named_like_a_temporary_file_is_never_touched(
    library_a, monkeypatch, tmp_path, capsys
):
    _export(tmp_path, capsys, "--with-media", str(tmp_path / "ml.media"))
    library_b = _library_b(monkeypatch, tmp_path, capsys)
    lookalike = library_b.root / "media/wikipedia/station-1.pdf.part"
    _hold(library_b, "media/wikipedia/station-1.pdf.part", b"someone's held bytes")

    assert main(["import", "bundle", str(tmp_path / "ml.md")]) == 0

    assert json.loads(capsys.readouterr().out)["media"]["adopted"] == 2
    assert lookalike.read_bytes() == b"someone's held bytes"
    assert (library_b.root / "media/wikipedia/station-1.pdf").read_bytes() == PDF_BYTES
    leftovers = [p.name for p in (library_b.root / "media/wikipedia").iterdir()]
    assert sorted(leftovers) == ["station-1.pdf", "station-1.pdf.part", "station-2.png"]


def test_a_symlinked_directory_cannot_carry_a_file_outside_media(
    library_a, monkeypatch, tmp_path, capsys
):
    _export(tmp_path, capsys, "--with-media", str(tmp_path / "ml.media"))
    library_b = _library_b(monkeypatch, tmp_path, capsys)
    outside = tmp_path / "outside"
    outside.mkdir()
    (library_b.root / "media").mkdir(exist_ok=True)
    (library_b.root / "media/wikipedia").symlink_to(outside, target_is_directory=True)

    assert main(["import", "bundle", str(tmp_path / "ml.md")]) == 1

    rejected = json.loads(capsys.readouterr().out)["media"]["rejected"]
    assert {r["reason"] for r in rejected} == {"outside the library's media directory"}
    assert list(outside.iterdir()) == []


def test_a_symlink_in_the_sidecar_cannot_pull_in_a_file_from_elsewhere(
    library_a, monkeypatch, tmp_path, capsys
):
    sidecar = tmp_path / "ml.media"
    _export(tmp_path, capsys, "--with-media", str(sidecar))
    secret = tmp_path / "secret.png"
    secret.write_bytes(PNG_BYTES)  # same bytes, so only containment can stop it
    carried = sidecar / "media/wikipedia/station-2.png"
    carried.unlink()
    carried.symlink_to(secret)
    library_b = _library_b(monkeypatch, tmp_path, capsys)

    assert main(["import", "bundle", str(tmp_path / "ml.md")]) == 1

    assert json.loads(capsys.readouterr().out)["media"]["rejected"] == [
        {"path": "media/wikipedia/station-2.png", "reason": "outside the sidecar"}
    ]
    assert not (library_b.root / "media/wikipedia/station-2.png").exists()


def test_a_file_that_cannot_be_copied_is_rejected_and_the_rest_still_land(
    library_a, monkeypatch, tmp_path, capsys
):
    import scrolls.bundle_media as bundle_media

    _export(tmp_path, capsys, "--with-media", str(tmp_path / "ml.media"))
    library_b = _library_b(monkeypatch, tmp_path, capsys)
    real_copy = bundle_media._copy_into

    def copy_into(source, handle):
        if source.name == "station-1.pdf":
            raise PermissionError(13, "Permission denied", str(source))
        return real_copy(source, handle)

    monkeypatch.setattr(bundle_media, "_copy_into", copy_into)

    assert main(["import", "bundle", str(tmp_path / "ml.md")]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["media"]["adopted"] == 1
    [rejected] = payload["media"]["rejected"]
    assert rejected["path"] == "media/wikipedia/station-1.pdf"
    assert "Permission denied" in rejected["reason"]
    assert (library_b.root / "media/wikipedia/station-2.png").read_bytes() == PNG_BYTES
    assert sorted(p.name for p in (library_b.root / "media/wikipedia").iterdir()) == [
        "station-2.png"
    ]


# --- review round 2: no-clobber publish, merge-faithful preview, NUL paths ---


def test_a_file_that_appears_mid_copy_is_never_clobbered(
    library_a, monkeypatch, tmp_path, capsys
):
    import scrolls.bundle_media as bundle_media

    _export(tmp_path, capsys, "--with-media", str(tmp_path / "ml.media"))
    library_b = _library_b(monkeypatch, tmp_path, capsys)
    racer = library_b.root / "media/wikipedia/station-1.pdf"
    real_copy = bundle_media._copy_into

    def copy_into(source, handle):
        result = real_copy(source, handle)
        if source.name == "station-1.pdf":  # another writer lands it meanwhile
            racer.write_bytes(b"the concurrent capture")
        return result

    monkeypatch.setattr(bundle_media, "_copy_into", copy_into)

    assert main(["import", "bundle", str(tmp_path / "ml.md")]) == 0

    media = json.loads(capsys.readouterr().out)["media"]
    assert (media["adopted"], media["already_held"]) == (1, 1)
    assert racer.read_bytes() == b"the concurrent capture"
    assert sorted(p.name for p in racer.parent.iterdir()) == ["station-1.pdf", "station-2.png"]


def test_the_preview_attaches_files_to_the_row_the_merge_keeps(
    library_a, monkeypatch, tmp_path, capsys
):
    _export(tmp_path, capsys, "--with-media", str(tmp_path / "ml.media"))
    bundle = tmp_path / "ml.md"
    lines = bundle.read_text(encoding="utf-8").splitlines(keepends=True)
    [first] = [i for i, line in enumerate(lines) if line.startswith('{"id": "wikipedia:en:Station"')]
    repeat = lines[first].replace("station-1.pdf", "station-8.pdf").replace(
        "station-2.png", "station-9.png"
    )
    lines.insert(first + 1, repeat)  # same id again: INSERT OR IGNORE keeps the first
    bundle.write_text("".join(lines), encoding="utf-8")
    _library_b(monkeypatch, tmp_path, capsys)

    assert main(["import", "bundle", str(bundle), "--dry-run"]) == 0
    preview = json.loads(capsys.readouterr().out)["media"]
    assert main(["import", "bundle", str(bundle)]) == 0
    real = json.loads(capsys.readouterr().out)["media"]

    assert real["adopted"] == 2
    assert preview == real


def test_a_nul_in_a_manifest_path_fails_before_anything_lands(
    library_a, monkeypatch, tmp_path, capsys
):
    sidecar = tmp_path / "ml.media"
    _export(tmp_path, capsys, "--with-media", str(sidecar))
    line = {"path": "media/wikipedia/bad\u0000.png", "sha256": _sha(b"x"), "bytes": 1,
            "item_id": "wikipedia:en:Station"}
    with (sidecar / "MANIFEST.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")
    _library_b(monkeypatch, tmp_path, capsys)

    code = main(["import", "bundle", str(tmp_path / "ml.md")])

    captured = capsys.readouterr()
    assert code == 1
    assert "MANIFEST.jsonl line 3" in json.loads(captured.err)["error"]
    assert main(["list"]) == 0
    assert json.loads(capsys.readouterr().out) == []
