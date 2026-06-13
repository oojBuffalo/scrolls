# 0074: Pocket arrives via CSV import — the read-later spine, the bookmarks sibling

Date: 2026-06-13
Status: accepted

## Context

IDEAS.md §13 defines `import` as bulk local archive ingestion, and the
namespace now has three occupants: Field Theory (ADR 0009, an archive
*with* content), Google Takeout (ADR 0029, a bare YouTube spine), and
browser bookmarks (ADR 0030, a heterogeneous bare spine). The product
thesis is "turn your *saved internet* into a library", and for a large
population the saved internet lives in a **read-later service** — Pocket
most of all.

Mozilla shut Pocket down in 2025 and will delete user data, mailing each
account a **data export** to take elsewhere. That export is a CSV (large
accounts get a `.zip` of `part_*.csv` files) with the header
`title,url,time_added,tags,status`: `time_added` is epoch seconds,
`tags` are pipe-delimited, `status` is `unread` or `archive`, and a save
with no title is exported with the URL repeated in the title field.
Millions of saves are looking for a new home on a deadline, and Scrolls
has nowhere to put them.

This is almost exactly the bookmarks situation (ADR 0030): a
heterogeneous spine of URLs the user curated, pointing at videos, repos,
papers, and articles, carrying only a URL, a title, a save time, and
tags — but in a different, far simpler container (a CSV, not the
notorious Netscape pseudo-HTML).

## Decision

`scrolls import pocket <path>` (`src/scrolls/pocket.py`) imports a Pocket
CSV export as detected items, reusing the bookmarks-import spine
wholesale:

- **Items enter at stage `detected`** — ADR 0029's spine rule. The
  export's title seeds `title` and fetch replaces it with the source's
  own value (ADR 0021); `time_added` becomes `saved_at` (when the page
  entered the user's life), never `published_at` (ADR 0024), through the
  shared `epoch_to_utc_iso` (`src/scrolls/dates.py`) the bookmarks import
  already uses.
- **Every URL routes through `detect_source`.** The spine is
  heterogeneous, so the importer reuses the exact normalize → detect →
  mint chain of `scrolls add` (ADR 0023): a saved video becomes a
  `youtube` item, a repo a `github` item, all deduping against the rest
  of the library. `INSERT OR IGNORE` keeps re-imports and cross-import
  collisions cheap (ADR 0009).
- **Pipe-delimited `tags` become `tags`** — the user's own curation, the
  bookmarks-folder analog (ADR 0030): free-form, where the user's word is
  final (ADR 0018), *not* `category` (engines pin that vocabulary).
- **A title equal to the URL is dropped.** Pocket stores "no title" as
  the URL repeated in the title field, so `_title` treats a title equal
  to the raw URL as absent — fetch fills the real one rather than
  enshrining a URL as a title.
- **Columns are read by header name, case-insensitive, via
  `csv.DictReader`.** Reordered or extra columns (a `cursor` field appears
  in some exports) survive; only a `url` column is required. A CSV with no
  `url` column is the document-level signal that this isn't a Pocket
  export (strict on the document, lenient on rows — ADR 0029's posture),
  and CSV text is decoded `utf-8-sig` so a BOM never hides the first
  header cell.
- **`.zip`, directory, or single `.csv`** all work (the Takeout
  zip/dir/file shape, ADR 0029): a zip or directory contributes all its
  `*.csv` parts, since Pocket splits large accounts across `part_*.csv`.
  A zip or directory holding no CSV is a document-level error.
- **Noise is counted, never fatal.** Blank URLs (`ignored.no_url`) and
  non-http(s) saves (`ignored.not_http`) are reported, the command exits
  0, and the same URL saved twice (across parts, or once unread once
  archived) collapses to one item — earliest `time_added` wins `saved_at`
  (the doctor's merge rule, ADR 0026), reported as `repeats`, tags
  unioned across occurrences, exactly the bookmarks rule.
- **`status` is tallied for the saves that become items.** The
  unread/archive split is reported in `stats.status` as migration context
  ("you brought over N unread, M archived"), counted after detection so it
  describes the library, not skipped rows. It drives nothing else: an
  archived save is still saved internet, so it imports like any other and
  `status` is not mapped to `category` or a tag.

## Consequences

- A Pocket export — the most common read-later archive, on a deletion
  deadline — becomes fetchable items offline in one command;
  `scrolls fetch --limit N` (ADR 0029) paces the enrichment of a years-deep
  pile resumably, and `scrolls classify`/`kb` then fold those saves into
  the same concept/link graph as everything else.
- The `import` namespace now spans the two archive shapes (content vs
  spine) and, within spines, the three container formats that matter:
  JSON (Takeout), Netscape HTML (browser bookmarks), and CSV (Pocket) —
  each a thin parser over one shared detect → dedupe → insert spine, the
  same way 30+ adapters are thin fetchers over one shared contract.
- Pocket tags seed user curation into `tags` like bookmark folders do
  (ADR 0030), feeding `related`'s shared-tags signal (IDEAS.md §10) and
  the KB tag pages (ADR 0064); the same arxiv-overwrites-`tags` caveat
  (ADR 0008) applies to saved arXiv papers.
- The importer is Pocket-shaped, not Pocket-only: any CSV carrying a
  `url` column (Instapaper, a hand-written reading list, a service whose
  export Pocket-alikes mimic) imports through the same path. Service-
  specific CSV dialects — Instapaper's `Folder`, Raindrop's richer column
  set, tag delimiters other than `|` — are deferred; today the contract is
  Pocket's `title,url,time_added,tags,status` and a `url`-bearing CSV.
- Pocket's HTML export (the older `ril_export.html`, a `<ul>/<li>` list,
  not the Netscape `<dl>/<dt>` the bookmarks importer reads) is not
  handled; the mailed CSV is the current export and the one users have.
