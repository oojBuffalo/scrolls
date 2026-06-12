# ADR 0001: Implementation stack — Python managed with uv

- Status: accepted
- Date: 2026-06-11
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

`IDEAS.md` §13 left the implementation stack open between TypeScript and
Python, with trade-offs sketched for both. No code exists yet; the first
implementation slice needs a stack decision so that tests, packaging, and the
CLI skeleton can compound across autonomous runs.

Environment facts observed on the development machine:

- Node v26 + npm 11 installed; Bun not installed.
- Python 3.12 + uv 0.11 installed.
- Field Theory data exists at `~/.fieldtheory/` as JSONL + SQLite +
  Markdown — i.e. compatibility with Field Theory is a **file-format**
  contract, not a code-level one. Importing it does not require sharing
  Field Theory's implementation language.

## Decision

Implement Scrolls as a **Python ≥3.11 package managed with uv**, using a
`src/` layout, `pytest` for tests, and stdlib-first dependencies.

Initial posture:

- CLI: stdlib `argparse` until a real ergonomic need justifies
  `typer`/`rich` (re-evaluate when subcommands multiply).
- Storage/search: stdlib `sqlite3` with FTS5.
- Runtime dependencies: none for the first slices; add per-adapter
  dependencies (`trafilatura`, `yt-dlp`, etc.) only when that adapter lands.
- Distribution: `uv tool install scrolls` (later).

## Rationale

1. **Unattended reliability.** The stdlib `sqlite3` module ships FTS5 with
   zero native-build risk. The Node equivalents (`better-sqlite3` native
   compilation, or `sql.js-fts5` WASM) add exactly the kind of
   install/build failure mode that breaks unattended hourly runs.
2. **Source-target fit.** The declared targets (YouTube transcripts, web
   article extraction, Wikipedia, PDFs/arXiv) are best served by the Python
   ecosystem: `yt-dlp`, `trafilatura`/`readability-lxml`, PyMuPDF. The
   TypeScript side has no equally mature equivalents for transcripts or
   PDF extraction.
3. **Field Theory compatibility is data-level.** Confirmed on disk:
   `~/.fieldtheory/bookmarks/bookmarks.jsonl`, `bookmarks.db` (SQLite), and
   a Markdown `library/`. A Python importer reads these directly; the
   "TS aligns with Field Theory" argument from `IDEAS.md` does not bind.
4. **Agent exposure is language-invisible.** Per `IDEAS.md` §10, agents use
   shell commands (`scrolls search --json`); MCP comes later and has good
   Python SDK support.
5. **Tooling present.** uv is installed and gives a fast, reproducible
   test/packaging loop (`uv run pytest`, `uv build`).

## Consequences

- Browser/session-heavy sync (native X bookmarks) may be less ergonomic
  than in Node; mitigated by the planned `scrolls import fieldtheory` path
  which sidesteps X auth entirely for v1.
- npm distribution is off the table; `uv tool install` / `pipx` is the
  install story.
- The pipeline boundaries from `IDEAS.md` §13 (adapter → ScrollItem →
  SQLite → Markdown → KB) stay language-clean, so this decision remains
  reversible until substantial adapter code accumulates.

## First slice (this ADR's proof)

`scrolls.sources.detect.detect_source(url)` — URL → `(source, source_id)`
detection for `scrolls add <url>` auto-detection (`IDEAS.md` §5), with
table-driven pytest coverage and a `scrolls detect <url>` debug command
emitting JSON.
