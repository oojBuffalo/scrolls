# 0029: YouTube history arrives via Google Takeout import, at stage detected

Date: 2026-06-12
Status: accepted

## Context

IDEAS.md §13 argues a large YouTube history belongs to the bulk-archive
path — "Google Takeout gives a fast, local, resumable spine of video
IDs/timestamps; enrichment can later fetch transcripts, thumbnails,
channels, descriptions" — rather than browser-driving thousands of
history entries. ADR 0009 established the `import` namespace for bulk
local archives and named `scrolls import google-takeout` as its next
occupant.

A Takeout export's `history/watch-history.json` (the user must select
JSON format; the default is HTML) is an array of watch events:

```json
{
  "header": "YouTube",
  "title": "Watched How SQLite FTS Works",
  "titleUrl": "https://www.youtube.com/watch?v=abc123xyz00",
  "subtitles": [{"name": "Some Channel", "url": "…"}],
  "time": "2024-10-12T18:23:45.123Z",
  "products": ["YouTube"]
}
```

Unlike Field Theory's archive, this carries no content: no transcript,
no description, not even the video's publish date. It also carries
noise every real history has — ad playbacks (`"details": [{"name":
"From Google Ads"}]`), deleted videos (no `titleUrl`), community-post
visits, and many repeat watches of the same video. Takeout localizes
directory names ("YouTube and YouTube Music" is translated per account
language), so fixed paths into the export tree are unreliable.

## Decision

`scrolls import google-takeout <path>` (`src/scrolls/takeout.py`)
imports watch history as youtube items:

- **Items enter at stage `detected`, not `fetched`.** Takeout is a
  spine, not content. The export's title and channel seed the item the
  way feed entries do (ADR 0021), and `scrolls fetch` enriches through
  the existing youtube adapter — the importer adds zero fetch
  machinery. This sharpens ADR 0009's boundary: importers of archives
  *with* content enter at `fetched` (Field Theory); importers of bare
  spines enter at `detected` and join the normal pipeline.
- **The watch time becomes `saved_at`, never `published_at`.** It is
  when the video entered the user's life — the analogue of Field
  Theory's `bookmarkedAt` — and Takeout simply does not know when the
  video was published. Lying it into `published_at` would poison the
  one-vocabulary guarantee of ADR 0024.
- **Repeat watches collapse to one item; the earliest watch wins.**
  The file lists newest first; keeping the earliest watch as `saved_at`
  matches the doctor's earliest-save-date merge rule (ADR 0026).
  Collapsed events are reported as `repeats`.
- **Noise is counted, never fatal, and never exits 1.** Ads, no-URL
  entries, and non-video URLs (posts, channel visits — anything
  `detect_source` doesn't give a youtube `source_id`) land in an
  `ignored` breakdown. Unlike `import fieldtheory`'s malformed JSONL
  lines, these are *expected* in every export, so they are not
  failures; only document-level problems (missing path, no
  `watch-history.json`, non-JSON content) error out.
- **`path` is the zip, a directory, or the JSON file itself.**
  Discovery searches for `watch-history.json` anywhere in the tree
  (zip or extracted) instead of assuming the localized directory
  names; the direct file path is the escape hatch when even the file
  name is translated.
- **Ids align with everything else.** URLs are normalized (ADR 0023)
  and detected like `add`, so `youtube:<videoId>` dedupes against
  `scrolls add`, feed sync, and re-imports (`INSERT OR IGNORE`, like
  ADR 0009).
- **No `--youtube-history` flag yet**, deviating from the IDEAS.md §13
  sketch: history is the only product supported, and a required flag
  with one valid value is noise. Flags can select products when
  playlists/subscriptions support lands.

## Consequences

- A YouTube history of any size becomes fetchable items offline in one
  command; `scrolls fetch` then pulls metadata/transcripts at whatever
  pace the user wants, resumable because the spine is already stored.
- Watch-history `saved_at` ordering means `scrolls list` reads as watch
  chronology for imported items.
- The English `"Watched "` title prefix is stripped; localized prefixes
  survive in the seeded title until fetch replaces it with the real
  one — degraded, honest, and self-healing.
- Ad detection matches the English `"From Google Ads"` marker;
  localized exports may import the occasional ad. It fetches like any
  video and `scrolls rm` takes it back out.
- The HTML export format is rejected with an error pointing at the
  JSON option, not half-parsed.
