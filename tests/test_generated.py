"""Tests for the sentinel-fenced regeneration helper (ADR 0102).

The pure boundary that lets `scrolls kb` (and, later, `scrolls agent install`)
refresh a generated artifact without clobbering a hand-written annotation:
the generated region lives inside a `@generated`…`@end` fence and is replaced
wholesale; anything outside the fence is preserved byte-for-byte.
"""

from scrolls.generated import (
    GENERATED_END,
    begin_marker,
    fence,
    generated_body,
    has_user_content,
    splice,
    user_regions,
    write_generated,
)


def test_fence_wraps_body_between_markers():
    out = fence("# Title\n\nbody.", "scrolls kb")
    lines = out.splitlines()
    assert lines[0].startswith("<!-- @generated scrolls")
    assert "scrolls kb" in lines[0]  # self-describes which command regenerates it
    assert lines[1:4] == ["# Title", "", "body."]
    assert lines[-1] == GENERATED_END
    assert out.endswith("\n")


def test_begin_marker_names_the_regenerating_command():
    assert "scrolls agent install" in begin_marker("scrolls agent install")
    assert begin_marker("scrolls kb").startswith("<!-- @generated scrolls")


def test_splice_into_nothing_is_just_the_fence():
    assert splice(None, "BODY", "scrolls kb") == fence("BODY", "scrolls kb")


def test_user_regions_of_a_marker_less_file_is_none():
    # a hand-written or pre-sentinel file carries no fence; the caller overwrites
    assert user_regions("# just some text\n") is None


def test_user_regions_splits_prefix_and_suffix_around_the_fence():
    existing = (
        "USER PREAMBLE\n"
        + fence("OLD GENERATED", "scrolls kb")
        + "USER APPENDIX\n"
    )
    prefix, suffix = user_regions(existing)
    assert prefix == "USER PREAMBLE\n"
    assert suffix == "USER APPENDIX\n"


def test_splice_replaces_generated_region_and_keeps_user_regions():
    existing = "TOP\n" + fence("OLD", "scrolls kb") + "BOTTOM\n"
    out = splice(existing, "NEW", "scrolls kb")
    assert "OLD" not in out
    assert "NEW" in out
    assert out.startswith("TOP\n")
    assert out.endswith("BOTTOM\n")


def test_splice_into_marker_less_file_overwrites_wholesale():
    # no fence to anchor on → the prior hand-written content is replaced
    out = splice("PRE-SENTINEL CONTENT\n", "NEW", "scrolls kb")
    assert "PRE-SENTINEL CONTENT" not in out
    assert out == fence("NEW", "scrolls kb")


def test_generated_body_is_the_inverse_of_user_regions():
    body = "# Title\n\nbody."
    out = fence(body, "scrolls kb")
    assert generated_body(out) == body + "\n"
    assert generated_body("# marker-less\n") is None
    # ignores the surrounding user regions
    wrapped = "TOP\n" + out + "BOTTOM\n"
    assert generated_body(wrapped) == body + "\n"


def test_has_user_content_distinguishes_annotated_from_bare_pages():
    bare = fence("GENERATED", "scrolls kb")
    annotated = "a note\n" + bare
    assert not has_user_content(bare)
    assert not has_user_content("# marker-less\n")
    assert has_user_content(annotated)


def test_write_generated_round_trips_an_annotation(tmp_path):
    page = tmp_path / "index.md"
    write_generated(page, "FIRST", "scrolls kb")
    # a human annotates outside the fence
    page.write_text("MY NOTE\n" + page.read_text(encoding="utf-8"), encoding="utf-8")

    write_generated(page, "SECOND", "scrolls kb")
    out = page.read_text(encoding="utf-8")
    assert out.startswith("MY NOTE\n")  # annotation survived the regenerate
    assert "FIRST" not in out  # generated region refreshed
    assert "SECOND" in out
