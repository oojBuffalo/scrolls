"""Shared rendering for discussion-thread adapters (ADR 0093).

Every source that fetches a conversation folds it into `extracted_text` as
the same Markdown subsection: a `### <heading>` header over one `#### <byline>`
block per contribution. That shape is shared by a dozen adapters — the four
code hosts' issue/PR threads (github/gitlab/gitea/bitbucket, ADR 0084-0087),
the link aggregators (lobsters/lemmy/piefed, ADR 0046/0052/0053), Stack
Exchange answers (ADR 0033), Discourse replies (ADR 0054), and the Fediverse
posts (mastodon/misskey/bluesky, ADR 0048/0049/0051).

What legitimately differs between them is which contributions to skip, how to
byline them (a comment, an answer with its score, a reply with its likes), how
to extract their text (Markdown, HTML, `cooked` posts), the order, and the
heading word. What does *not* differ is the assembly — the `####` block, the
blank-line join, the `### <heading>` wrapper, and the "" returned when nothing
survives. That assembly was copied into each adapter; this module owns it so
the per-source choices stay the adapter's and the rendering stays one contract.

An adapter does its source-specific work, produces the `Comment(byline, body)`
list it has already decided on, and calls `format_thread`. The result drops in
to `extracted_text` with a plain truthy join, the same as before.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["Comment", "format_thread"]


@dataclass(frozen=True)
class Comment:
    """One rendered contribution: a `byline` heading and its `body` text.

    `byline` is the source's already-composed attribution line (`Comment by
    alice`, `Accepted answer by ev (score 9)`, `Reply by bob (3 likes)`); it
    becomes the block's `#### ` heading. `body` is the already-extracted,
    plain-text content; an empty one is dropped by `format_thread`.
    """

    byline: str
    body: str


def format_thread(comments: Iterable[Comment], *, heading: str) -> str:
    """Assemble bylined contributions into a `### {heading}` Markdown subsection.

    Each comment becomes a `#### {byline}\n\n{body}` block, the body stripped so
    callers need not; a comment whose body is empty after stripping is dropped
    (the deleted/media-only contribution an adapter forwarded rather than
    pre-filtering). Surviving blocks are joined with a blank line under the
    `### {heading}` header, or "" is returned when none remain — so a caller
    folds the result into `extracted_text` with a plain truthy join.
    """
    blocks = [
        f"#### {comment.byline}\n\n{body}"
        for comment in comments
        if (body := comment.body.strip())
    ]
    if not blocks:
        return ""
    return f"### {heading}\n\n" + "\n\n".join(blocks)
