# ADR 0011: Media capture is an explicit stage-neutral command

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

Adapters have recorded media references as `{"type", "url"}` dicts since
they landed — youtube thumbnails (ADR 0003), arXiv PDF links (ADR 0008),
x photos via the Field Theory import (ADR 0009) — but nothing ever
downloaded them: `media/` sat reserved-but-unused, and a scroll's
`media` frontmatter pointed only at remote URLs that can rot. IDEAS.md
§2–3 always intended `media/` to hold local copies ("thumbnail:
media/youtube/abc123.jpg").

Open questions: where capture runs (inside `fetch`, inside `ingest`, or
its own command), how files are named, what gets recorded, and what a
re-run does.

## Decision

1. **A separate `scrolls media [id]` command, not part of `fetch` or
   `ingest`.** Fetch is the *text* network step and stays fast; media
   can be megabytes per item (a single arXiv PDF is ~2 MB). The Field
   Theory lesson in IDEAS.md §13 — separate sync/import from
   enrichment — applies: capture is opt-in enrichment, runnable any
   time after fetch. The command is stage-neutral like `classify` and
   `kb`.
2. **Conventions copied from the existing batch commands.** No
   argument: capture every ref that lacks a file on disk. With an id:
   explicit re-capture (like `fetch <id>` refetches). Per-item failures
   never abort the batch; exit 1 if any item failed; counts + per-item
   `results` envelope (`docs/cli.md`).
3. **Files land at `media/<source>/<id-slug>-<n><ext>`,** `<n>` the
   ref's 1-based position, extension from the URL path when it looks
   like one (must contain a letter — arXiv ids' `.03762` tails don't),
   else mapped from the ref `type` (`pdf` → `.pdf`, `photo`/`thumbnail`
   → `.jpg`, `video` → `.mp4`, else `.bin`).
4. **The ref itself records the file** as a root-relative `path` key —
   the same convention as `markdown_path`, no schema change because
   `media` is already a JSON column. A recorded `path` is reused on
   re-capture, so file locations are as stable as scroll paths. After
   capture, a rendered scroll is re-rendered so frontmatter shows the
   local path (the `classify` precedent).
5. **The media tree is cache, not canon.** Files are plain downloads;
   the recorded `url` always allows re-capture, and a batch run heals
   deleted files. SQLite remains the canonical index (IDEAS.md §3).

## Consequences

- `src/scrolls/media.py` (`capture_media`, `has_pending_media`),
  `scrolls media [id]` in `cli.py`; tests in `tests/test_media.py` and
  the media block of `tests/test_cli.py`. No new dependency — downloads
  go through the shared stdlib transport (`sources/http.py`) behind the
  same patchable seam adapters use, so tests stay offline.
- The documented media ref shape changed from "array of strings" (which
  no adapter ever produced) to the real array-of-objects shape, now with
  the optional `path` key (`docs/library-format.md`).
- Deferred: a size cap or content-type check on downloads (capture
  trusts the adapter-recorded URL), transcripts-as-media, and wiring
  capture into `ingest` behind a flag if one-command workflows want it.
