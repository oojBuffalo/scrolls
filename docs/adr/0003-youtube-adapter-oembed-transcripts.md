# ADR 0003: YouTube adapter — keyless oEmbed + optional transcripts

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

YouTube is the last of the IDEAS.md §6 MVP source trio (Wikipedia and web
landed in ADR 0002 / the trafilatura slice). ADR 0002 assumed YouTube
would need `yt-dlp`; this slice revisits that. What a scroll needs from a
video is metadata (title, channel, thumbnail) plus the transcript — the
only searchable text a video has. The official Data API requires an API
key, which is the wrong default for a local-first keyless CLI.

## Decision

1. **Not `yt-dlp` (for now).** It is a large, fast-moving dependency built
   for media download. This slice needs metadata and captions only, so it
   takes two much smaller paths instead. `yt-dlp` remains the obvious
   choice later for `media/` downloads (thumbnails, audio) if that slice
   ever lands.
2. **Metadata via the keyless oEmbed endpoint.**
   `https://www.youtube.com/oembed?url=…&format=json` returns title,
   channel name/URL, and thumbnail with no auth, over the existing stdlib
   transport. It also works for playlist URLs, so playlists become
   metadata-only scrolls for free. It does not return description or
   publish date; those can be added later from the watch page or Data API
   without changing item identity.
3. **Transcript via `youtube-transcript-api`** (second per-adapter
   dependency, per the ADR 0001 pattern that trafilatura established).
   English is preferred, falling back to the first available language
   (manual captions before generated ones).
4. **The transcript is optional enrichment.** Unlike wikipedia/web —
   where no text means `FetchError` — a caption-less video still yields a
   useful bookmark-grade scroll. Any transcript failure (no captions,
   disabled, region-blocked) degrades to a metadata-only item at stage
   `fetched`, with `provenance.extraction_method` recording which path ran:
   `oembed+youtube-transcript-api` vs `oembed`. `FetchError` is reserved
   for missing identity (no video id, e.g. channel URLs) and oEmbed
   failures. Refetching later can upgrade a metadata-only item.
5. **Canonical URL is normalized** to
   `https://www.youtube.com/watch?v=<id>` (or `playlist?list=<id>`), so
   youtu.be/shorts/embed spellings converge. `content_hash` covers the
   transcript text when present, else the oEmbed payload. The thumbnail
   URL is stored as the first `media` entry — the first use of that field.
   `summary` stays empty rather than faking one from transcript openings.

## Consequences

- Videos whose captions are blocked for cloud IPs silently become
  metadata-only scrolls; the degradation is visible in provenance, and
  `scrolls fetch <id>` retries.
- Playlist scrolls carry only the playlist title/channel; enumerating
  playlist entries into per-video items is a future sync-shaped slice.
- No description/publish date until a richer metadata source is added.
- `media` entries now exist (`{"type": "thumbnail", "url": …}`) but
  nothing downloads them yet; render ignores them.

## Proof

`src/scrolls/sources/youtube.py` with transport-faked tests
(`tests/test_youtube.py`, end-to-end CLI test in `tests/test_cli.py`), and
a live smoke test: `scrolls ingest https://youtu.be/jNQXAC9IVRw` produced
a rendered scroll titled "Me at the zoo" by "jawed" with a 217-char real
transcript and `extraction_method=oembed+youtube-transcript-api`.
