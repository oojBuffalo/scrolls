# 0093: One shared renderer for discussion threads

Date: 2026-06-15

Status: accepted

*Amended: 2026-07-26 — the inspiration doc moved to
`docs/inspiration/last30days-inspiration.md`; the path reference below was
updated. Decision content unchanged.*

## Context

The library now fetches conversations from a dozen sources: the four code
hosts' issue/PR threads (github/gitlab/gitea/bitbucket, ADR 0084–0087), the
link aggregators (lobsters, lemmy, piefed, ADR 0046/0052/0053), Stack Exchange
answers (ADR 0033), Discourse replies (ADR 0054), and the Fediverse posts
(mastodon, misskey, bluesky, ADR 0048/0049/0051). Each folds its conversation
into `extracted_text` as the same Markdown subsection — a `### <heading>` header
over one `#### <byline>` block per contribution, blocks joined by a blank line,
and `""` returned when nothing survives.

That assembly was copied verbatim into all twelve adapters. The tail

```python
    blocks.append(f"#### {byline}\n\n{text}")
if not blocks:
    return ""
return "### Comments\n\n" + "\n\n".join(blocks)
```

appeared, character-for-character, in `github._format_comments`,
`gitlab._format_notes`, `gitea`/`bitbucket`/`lobsters`/`lemmy`/`piefed`
`_format_comments`, `stackexchange._format_answers`, `discourse`/`misskey`
`_format_replies`, and `mastodon`/`bluesky`'s reply renderers. The only things
that legitimately differ between sources are *which* contributions to skip
(deleted, moderated, `system: true`, inline review comments), *how* to byline
them (a comment, an answer with its score, a reply with its likes/favourites/
reactions), *how* to extract their text (Markdown, HTML, Misskey MFM, Discourse
`cooked`), the *order* (Lemmy/PieFed sort into thread pre-order), and the
*heading word* (`Comments`, `Top Answers`, `Replies`). The rendering itself was
one contract expressed twelve times — so a change to it (a different heading
level, comment counts, nested indentation) meant twelve identical edits, and a
thirteenth thread adapter would copy the tail a thirteenth time.

## Decision

Extract the assembly into `src/scrolls/sources/discussion.py`: a frozen
`Comment(byline, body)` dataclass and `format_thread(comments, *, heading)`.
The function renders each comment as a `#### {byline}\n\n{body}` block with the
body stripped, drops any whose body is empty, joins the survivors with a blank
line under the `### {heading}` header, and returns `""` when none remain — the
exact contract the twelve copies expressed.

Each adapter keeps every source-specific choice — its skip rules, byline
composition, text extraction, and ordering all stay in the adapter, where they
belong — and changes only its last few lines: it builds the
`discussion.Comment(byline, text)` list it had already decided on and returns
`discussion.format_thread(rendered, heading=...)`. No detection, dispatch,
fetch path, or output byte changes; the heading argument carries the one word
that varied (`Comments` / `Top Answers` / `Replies`).

The split mirrors how the system already factors the fetch layer: `http`
owns the transport every adapter shares while each adapter owns its endpoints
and payload shape (ADR 0002); `discussion` now owns the thread-rendering
contract every thread adapter shares while each keeps its own conversation
semantics. The unit is named `Comment` because a comment is the generic thread
contribution; an answer or a reply is a kind of comment, distinguished only by
its byline and the section heading.

## Consequences

- The threaded-rendering contract lives in one place. A future enrichment that
  every thread should gain — rendering the nesting `depth`/`path` the
  aggregators already keep in `raw_text`, a per-comment permalink, a collapsed
  long-thread summary — is a one-file change behind a stable call site rather
  than twelve parallel edits, and it lands for every source at once.
- The change is behavior-preserving by construction: the existing per-adapter
  thread tests (`tests/test_github.py`, `test_lobsters.py`, `test_lemmy.py`,
  `test_stackexchange.py`, `test_discourse.py`, …) all pass unchanged, pinning
  byte-identical output; `tests/test_discussion.py` covers the shared helper
  directly (empty thread, single/multiple blocks, configurable heading,
  empty-body drop, whitespace stripping, non-list iterables).
- The next discussion adapter writes its skip/byline/text logic and calls
  `format_thread` — the rendering is no longer something to get right a
  thirteenth time. This is the consolidation the autonomous priority calls for
  over more one-off adapters: a deeper module with a smaller interface
  (`docs/inspiration/last30days-inspiration.md`, the "threaded/comment
  rendering" slice).
- Deliberately *not* consolidated: the skip rules, bylines, text extraction,
  and ordering. Those are genuine per-source knowledge (GitLab's `system`
  notes, Bitbucket's inline review comments, Lemmy's `path` pre-order, Stack
  Exchange's accepted-answer-first sort), not duplication; pulling them behind
  a config object would trade real clarity for false uniformity.
