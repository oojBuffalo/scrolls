# ADR 0115: Bundles carry media in an opt-in sidecar

Date: 2026-10-22

Status: accepted

Settles: issue #12. Extends: [0103](0103-shareable-custody-bundle.md).

## Context

The live carry-leg round-trip (roadmap H432) was byte-perfect for scrolls
— 109 of 109, idempotent on re-import — but it named the boundary: media
is the one thing a Markdown bundle cannot carry (1,479 refs). A fresh
library holds re-fetchable references, not the files, and anything that
rotted upstream since is gone.

So *take it with me* (vision M4/M5) was lossless for text and custody state
and lossy for figures, audio, video and documents. ADR 0110/0112's size
profile puts the media at about 1.8 GB against 42 MB of scrolls, so folding
the files into the bundle would change what the artifact is.

Three options were weighed: a sidecar beside the bundle, a single archive
file holding both, or declaring references the contract and documenting the
boundary. Elijah chose the sidecar.

## Decision

1. **An opt-in sidecar directory, never inside the bundle.**
   `export bundle --with-media DIR` copies the in-scope items' captured
   files into DIR at their library-relative paths, with a
   `MANIFEST.jsonl` of `{path, sha256, bytes, item_id}` sorted by path.
   The Markdown on stdout is byte-identical with or without the flag, so
   the bundle stays small, text-pure, and every existing guarantee holds.
2. **Exactly the custody block's files.** The sidecar is built from the
   rows the bundle's own custody block carries, so scope, filters and the
   sidecar can never disagree.
3. **Honest about what did not travel.** The export summary (stderr, since
   stdout is the bundle) names refs whose recorded file is gone from disk
   (`missing`) and counts refs that travel as references only
   (`uncaptured`: never captured, or declined on size).
4. **Found by convention, or named.** `import bundle ml.md` adopts
   `ml.media/` when it sits beside the bundle; `--media DIR` names one
   kept elsewhere.
5. **The manifest is validated before anything lands.** A malformed line,
   or a path outside `media/`, fails the whole import naming the line. A
   backup that lies about where a file goes is corrupt, not partly usable.
6. **Files land only where a held ref expects them.** A file is adopted
   when the row it names, after the import, records that exact `path`.
   Anything else is `unattached` and left in the sidecar.
7. **Hash-checked, never overwriting.** Each file is copied through a
   temporary name and renamed only if its SHA-256 matches. A mismatch, or a
   file missing from the sidecar, is `rejected` and fails the run, while
   the rows and the other files still land. A file the library already
   holds is never touched — the importer's `INSERT OR IGNORE`, applied to
   bytes.

## Consequences

- **Take it with me is lossless for media** when the sidecar travels: a
  fresh library's `doctor` reports no missing media after the import.
- **The import's JSON gains an always-present `media` block**
  (`{sidecar, adopted, already_held, unattached, rejected}`), null and
  zeros when nothing travelled, like the `archive` block. `--dry-run`
  predicts it, hashing without writing.
- **`--format html` refuses the flag:** the HTML briefing has no custody
  block for files to attach to.
- **Deferred:** a single-file archive variant (a tarball of bundle plus
  sidecar) for transports that want one file; incremental sidecars that
  skip files the receiver already holds.

Tests: `tests/test_bundle_media.py`.
