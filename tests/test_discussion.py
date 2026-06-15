"""The shared discussion-thread renderer (ADR 0093)."""

from __future__ import annotations

from scrolls.sources.discussion import Comment, format_thread


def test_empty_thread_renders_nothing():
    assert format_thread([], heading="Comments") == ""


def test_single_comment_is_a_bylined_block_under_the_heading():
    out = format_thread([Comment("Comment by alice", "Hello there")], heading="Comments")
    assert out == "### Comments\n\n#### Comment by alice\n\nHello there"


def test_comments_join_with_a_blank_line_in_order():
    out = format_thread(
        [Comment("Comment by alice", "first"), Comment("Comment by bob", "second")],
        heading="Comments",
    )
    assert out == (
        "### Comments\n\n"
        "#### Comment by alice\n\nfirst\n\n"
        "#### Comment by bob\n\nsecond"
    )


def test_heading_is_configurable_for_answers_and_replies():
    answer = format_thread([Comment("Answer by ev", "use BM25")], heading="Top Answers")
    assert answer.startswith("### Top Answers\n\n")
    reply = format_thread([Comment("Reply by ev", "agreed")], heading="Replies")
    assert reply.startswith("### Replies\n\n")


def test_empty_bodies_are_dropped():
    # An adapter that forwards a deleted/media-only comment rather than
    # pre-filtering it still gets the same subsection as if it had.
    out = format_thread(
        [
            Comment("Comment by alice", "kept"),
            Comment("Comment by ghost", ""),
            Comment("Comment by space", "   "),
            Comment("Comment by bob", "also kept"),
        ],
        heading="Comments",
    )
    assert out == (
        "### Comments\n\n"
        "#### Comment by alice\n\nkept\n\n"
        "#### Comment by bob\n\nalso kept"
    )


def test_a_thread_of_only_empty_bodies_renders_nothing():
    assert format_thread([Comment("Comment by ghost", "")], heading="Comments") == ""


def test_body_is_stripped_so_callers_need_not():
    out = format_thread([Comment("Comment by alice", "  padded  ")], heading="Comments")
    assert out == "### Comments\n\n#### Comment by alice\n\npadded"


def test_accepts_any_iterable_not_just_a_list():
    out = format_thread(
        (Comment("Comment by alice", "from a tuple"),), heading="Comments"
    )
    assert out == "### Comments\n\n#### Comment by alice\n\nfrom a tuple"
