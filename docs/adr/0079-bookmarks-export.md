# 0079: `scrolls export bookmarks` — items back out, the import inverse

Date: 2026-06-13
Status: accepted

## Context

ADR 0077 added `scrolls export opml` and named the principle it served: a
migration tool that only imports is a roach motel. It then deferred item
export explicitly — "no single universal format; the durable form is the
Markdown scrolls" — and left the `export` namespace ready for "a JSON dump of
items" once a concrete target appeared.

`scrolls import bookmarks` (ADR 0030) is itself a roach motel today. A user can
pour a browser's `bookmarks.html` *into* Scrolls, curate it (fetch, classify,
tag, `rm`), and then have no way to get the curated URL list back out into a
browser, a read-later service, or a backup. The library owns everything needed:
`items.list_items` returns every item oldest-first, and `src/scrolls/bookmarks.py`
already owns the Netscape format in one direction.

The Netscape bookmark file *is* the concrete universal format ADR 0077 was
waiting for — but for the item **spine**, not the whole item. A bookmark file
holds a URL, anchor text, a save date, and (by attribute or folder) tags. That
is exactly `url` / `title` / `saved_at` / `tags`, and the import already
established that mapping. An item's *content* — extracted text, summary — has no
place in a bookmark file and stays where it is durable: the Markdown scrolls.
So this is not "item export" in the full sense ADR 0077 deferred (a lossless
JSON dump); it is spine export to a format whose importer already exists, the
exact symmetry that justified `export opml`.

## Decision

`scrolls export bookmarks` writes the library's items as a Netscape-format
bookmark file to **stdout** (`bookmarks.dump_bookmark_export`,
`cli._cmd_export_bookmarks`):

- **A second `export` subcommand**, `export bookmarks` alongside `export opml`,
  the namespace ADR 0077 introduced for exactly this. `import bookmarks` ↔
  `export bookmarks` reads symmetrically with `import opml` ↔ `export opml`.
- **The bookmark file is the artifact, so it prints raw on stdout** — the
  `scrolls context` / `export opml` exception to the JSON-on-stdout rule.
  `scrolls export bookmarks > bookmarks.html` is the natural use; there is no
  path argument, so no overwrite, permission, or path-validation surface — the
  shell owns redirection, exactly as `export opml` decided.
- **The export carries the spine, not the content.** Each item becomes one
  `<DT><A HREF=… ADD_DATE=… TAGS=…>title</A>`: `url` → `HREF`; `saved_at` →
  `ADD_DATE` as epoch seconds via `dates.iso_to_epoch` (the inverse of the
  import's `epoch_to_utc_iso`, ADR 0024); `tags` → a comma-joined `TAGS`
  attribute; `title` as the anchor text, falling back to the URL when an item
  has none — the same "label by URL" rule `export opml` uses for a titleless
  subscription, since a bookmark needs anchor text. Extracted text and summary
  are deliberately not emitted: a bookmark file is a URL list, and the content's
  durable home is the Markdown scroll.
- **Tags are flat (the `TAGS` attribute), not a folder tree.** The import reads
  tags from *both* folder ancestry and a `TAGS` attribute; the export emits the
  attribute and no folders. Folders would have to duplicate a multi-tag item
  (one copy per folder) and a browser reconstructs nothing useful from them on
  re-import anyway, whereas the `TAGS` attribute round-trips cleanly through the
  importer's attribute-tag path and is what Pinboard-style tools read. This is
  the same "the export is flat" honesty `export opml` chose (ADR 0077): emit
  what Scrolls actually holds, not an invented hierarchy. A browser silently
  ignores the attribute but keeps the bookmark, so nothing is lost for a browser
  either.
- **Text and attribute values are HTML-escaped** (`html.escape`, `quote=True`
  on attributes), so a title with `<`/`&` and a URL with `&` survive a
  re-import. The document opens with the format's
  `<!DOCTYPE NETSCAPE-Bookmark-file-1>` marker — the same string the importer
  keys on — plus a charset META and `<TITLE>`/`<H1>`, then a flat `<DL>`. An
  empty library produces a valid empty document, not an error.
- **Items are exported in `list_items` order** (oldest `saved_at` first, id
  tiebreak), the whole library by default. Three optional filters scope the
  export to a slice — `--source`, `--category`, `--tag` — the same durable
  *item-property* facets `scrolls list` filters by, passed straight through to
  the shared, already-tested `list_items` query (they AND together). `--stage`
  and `--concept`, which `scrolls list` also offers, are deliberately not
  exposed: stage is transient pipeline state and concept is a derived KB-graph
  lens, neither a property a user curates a bookmark set by. So "export my
  github items" or "export my `paper` items" is one command, while the bare
  `export bookmarks` still matches `export opml`'s whole-library shape.
- **Round-trip is the contract.** `dump_bookmark_export` then
  `load_bookmark_export` reproduces the same URLs, titles, save dates, and tags
  in order, and re-importing through the CLI skips every item as
  already-registered (`test_export_round_trips_through_import` in
  `tests/test_bookmarks.py`,
  `test_export_bookmarks_round_trips_through_import` in `tests/test_cli.py`) —
  the proof the two halves agree, exactly as `export opml` is verified.

## Consequences

- The bookmarks round-trip is complete: a browser's bookmark list flows into
  Scrolls (`import bookmarks`), is curated there, and flows back out to any
  browser or read-later tool (`export bookmarks`). Backup falls out for free.
  `import bookmarks` is no longer a roach motel.
- The `export` namespace now has two members, both spine-or-subscription
  interchange to a format whose importer already exists (OPML feeds, Netscape
  bookmarks). The full lossless **item** export ADR 0077 deferred — a JSON dump
  that preserves extracted text, summary, classification, and provenance, the
  reserved `items/` directory's eventual job — is still open and is a different
  shape (no standard external format, so no existing importer to round-trip
  against). This export does not pretend to be it.
- `dates.iso_to_epoch` now exists as the documented inverse of
  `epoch_to_utc_iso`, available to any future export that needs an epoch
  timestamp.
- A titleless item (added but never fetched) exports with its URL as anchor
  text; a re-import then sets `title` to that URL rather than leaving it None.
  This is the same lossy edge `export opml` accepts for a titleless
  subscription, and `fetch` overwrites it with the source's real title on the
  next enrich, so it is not load-bearing.
- Scoping filters (`--source`, `--category`, `--tag`) reuse the `list_items`
  query rather than re-implementing selection, so the export stays a thin
  serializer over the same item-selection logic the rest of the CLI shares;
  adding `--stage`/`--concept` later, if a need appears, is a one-line
  passthrough. Folder-from-tags emission is deliberately not done and would
  only be revisited if a concrete consumer needed a hierarchy a flat `TAGS`
  attribute cannot express.
