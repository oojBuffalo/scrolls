# 0030: Browser bookmarks arrive via Netscape-HTML import, folders become tags

Date: 2026-06-12
Status: accepted

## Context

IDEAS.md §13 defines `import` as bulk local archive ingestion, and the
namespace has two occupants: Field Theory (ADR 0009, an archive *with*
content) and Google Takeout (ADR 0029, a bare spine). Browser bookmarks
are the most universal saved-content archive there is — every major
browser (Chrome, Firefox, Safari, Edge) exports the same
Netscape bookmark file format, and bookmark services (Pinboard and its
ancestors) speak it too. For most people, `bookmarks.html` *is* their
saved internet.

The format is a notorious pseudo-HTML: a `NETSCAPE-Bookmark-file-1`
DOCTYPE, then nested `<DL>` lists where `<DT><H3>` names a folder,
`<DT><A>` is a bookmark (`HREF`, `ADD_DATE` in epoch seconds — though
milli/microsecond variants exist in the wild — and Firefox's `TAGS`
attribute), and an optional `<DD>` note follows a bookmark. `<DT>` and
`<DD>` are never closed, so tree parsers choke or hallucinate
structure. Real exports also accumulate noise: `javascript:`
bookmarklets, Firefox `place:` smart folders, `file:` links.

Unlike Takeout's single-source spine, a bookmarks file points at
everything: videos, repos, papers, tweets, articles.

## Decision

`scrolls import bookmarks <path>` (`src/scrolls/bookmarks.py`) imports
a Netscape-format export as detected items:

- **Items enter at stage `detected`** — ADR 0029's spine rule: archives
  with content enter at `fetched`, bare spines enter at `detected` and
  join the normal pipeline. Anchor text seeds `title`, a `<DD>` note
  seeds `summary`, and fetch replaces both with the source's own
  values. `ADD_DATE` becomes `saved_at` (when the page entered the
  user's life), never `published_at` (ADR 0024); epoch values too large
  to be seconds are divided down (`epoch_to_utc_iso` in
  `src/scrolls/dates.py`).
- **Every http(s) URL routes through `detect_source`.** The spine is
  heterogeneous, so the importer reuses the exact normalize → detect →
  mint chain of `scrolls add` (ADR 0023): a bookmarked video becomes a
  `youtube` item, a repo a `github` item, a tweet an `x` item (no fetch
  adapter yet — registered like `add` would). `INSERT OR IGNORE` keeps
  re-imports and cross-import collisions cheap (ADR 0009).
- **Folder ancestry becomes `tags`.** Folders are the user's own
  curation; `tags` is the free-form field where the user's word is
  final (ADR 0018). They are *not* `category` — engines pin that
  vocabulary, and honestly-unclassified beats folder names that mean
  something only to their author. Root containers ("Bookmarks bar",
  "Bookmarks Menu/Toolbar", "Other/Mobile/Unsorted Bookmarks", or
  anything flagged `PERSONAL_TOOLBAR_FOLDER`) are browser furniture,
  not curation, and are excluded. Firefox's `TAGS` attribute merges
  after folder tags. Known trade-off: the arxiv adapter overwrites
  `tags` with taxonomy codes at fetch (ADR 0008), so folder tags on
  bookmarked arXiv papers don't survive enrichment; every other
  adapter leaves `tags` untouched.
- **Parsing is a stdlib `HTMLParser` token stream, never a tree.** A
  folder stack tracks `<H3>`/`<DL>`/`</DL>`; `<DD>` text (no closing
  tag) attaches to the bookmark just seen and is flushed at the next
  tag event. No new dependency for a format whose grammar is four tags.
- **Noise is counted, never fatal.** Non-http(s) bookmarks
  (`ignored.not_http`) and href-less anchors (`ignored.no_url`) are
  expected in real exports, so the command exits 0 and reports them.
  Only document-level problems error: a missing file, or content
  without the `NETSCAPE-Bookmark-file` marker (strict on the document,
  lenient on entries — ADR 0029's posture).
- **The same URL in several folders collapses to one item.** Earliest
  `ADD_DATE` wins `saved_at` (the doctor's merge rule, ADR 0026),
  reported as `repeats`; folder tags union across occurrences, because
  each placement is real curation.

## Consequences

- Anyone's browser bookmarks become fetchable items offline in one
  command; `scrolls fetch --limit N` (ADR 0029) paces the enrichment of
  a decades-old pile politely and resumably.
- Folder tags survive fetch for every source except arxiv, feeding
  `related`'s shared-tags signal (IDEAS.md §10) and staying visible in
  scroll frontmatter — the first import that seeds user curation into
  `tags` at scale.
- `saved_at` from `ADD_DATE` means `scrolls list` reads imported
  bookmarks as bookmarking chronology, and `repeats` collapse keeps one
  URL one item no matter how many folders held it.
- Safari exports omit `ADD_DATE`; those items get the import time as
  `saved_at` — degraded but never empty.
- A bookmarks file from a service that omits the Netscape DOCTYPE is
  rejected whole; the error names the expected format rather than
  guessing at arbitrary HTML.
