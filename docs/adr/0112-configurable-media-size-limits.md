# ADR 0112: Bulk media capture is bounded by configurable size limits

Date: 2026-08-19

Status: accepted

Amends: [0011](0011-media-capture-command.md), [0110](0110-wikipedia-article-links-and-figures.md)

## Context

ADR 0110 shipped figure capture and named its own gap: the 1600px rule caps
rasters by *pixel width* and says nothing about bytes, so video was unbounded.
The first full run over the user's 566-article reading-list library showed what
that costs.

**23 of 5,416 files held 4.1 GB of 5.7 GB.** A single
`electromagnetic-interference` `.webm` was 2.5 GB — 43% of the entire library
in one file. The remaining 5,393 files, every diagram and photograph and short
clip, came to 1.7 GB together.

**The expensive classes are the ones an agent cannot read.** Broken down by
role rather than extension: diagrams (2,189 SVGs, 246 MB) are XML an agent
reads directly; photographs (3,038 files, 988 MB) carry captions; documents (3
PDFs, 63 MB) are text. Audio and video are 105 files and 4.4 GB, and are opaque
to every reader this library serves.

**But "big" and "worthless" are not the same axis.** The 62.6 MB file in that
tail is a CIA PDF — a document full of exactly the knowledge the library is
for. A pure byte threshold would have thrown it away.

## Decision

**Capture is bounded by default at 25 MB, and the limits are configuration
rather than policy baked into the code.** The operator picks the number:

```toml
[media]
max_bytes = 26214400
max_image_width = 1600

[media.max_bytes_by_type]
pdf = 0
```

**`0` means no limit**, and a per-invocation `--max-bytes` beats the file, the
same precedence `--engine` already has over `default_engine` (ADR 0016).

**Limits are per-type overridable, and documents are uncapped by default.** A
PDF is the one large class that is text; size alone is a bad reason to drop
something an agent can read. This keeps the byte cap aimed at what it is
actually for — bulk an agent cannot use — rather than at bigness as such.

**A declined file is recorded, not lost.** The ref keeps its `type`, `url` and
`title`, and gains `oversize` (the cap that rejected it) and `bytes` (its real
size). The scroll therefore states what was passed over and why, and raising
the limit and re-running captures it. This is the same custody move ADR 0110
made with `original_url` for capped rasters: recording what was declined is
what makes it custody rather than loss.

**`has_pending_media` treats a declined ref as settled**, so a bounded library
is a clean no-op on the next `scrolls media` rather than one that reports work
forever outstanding.

**Size comes from `Content-Length` before the body is read.** Declining a
2.5 GB file costs one set of response headers, not a cap's worth of downloaded
bytes.

## Consequences

**Applied to the live library**: 22 files declined, 4.04 GB freed, 5.7 GB →
1.8 GB, 5,416 → 5,394 files, `doctor` 0 issues, all 566 items still `rendered`,
and `scrolls media` now returns `{captured: 0, skipped: 0, failed: 0}`. The
CIA PDF was kept, as the per-type rule intends.

**Media has one network seam now, not two.** The first cut kept
`_get_bytes` for the uncapped path and added `_get_bytes_within` for the capped
one. With a cap on by default that left the live path unpatched by the tests
that monkeypatch the seam — a suite run silently reached the real network and
reported an HTTP 400 as a test failure. `_download(url, max_bytes)` returning
`(payload, size)` is one operation, and "download this, but not if it is huge"
was always one operation.

**Ogg containers are typed `file`, not `audio`/`video`.** MediaWiki reports
`application/ogg` for `.ogv`/`.ogg`, which ADR 0110's MIME mapping does not
resolve further, and the container genuinely is ambiguous. The default cap
still applies, so the capture is bounded correctly; only a per-type override
for those files would misfire. Left as a known gap rather than guessed at.

**Deferred**: extracting text from captured PDFs into the scroll. The repo
already does this for arXiv (`extraction_method: arxiv-atom+pypdf`), so a
62.6 MB document sitting in `media/` with its text unread is a real gap — but
it is a capture-depth change, not a size-limit one.
