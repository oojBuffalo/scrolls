"""YouTube fetch adapter (IDEAS.md §6, ADR 0003).

Metadata (title, channel, thumbnail) comes from YouTube's keyless oEmbed
endpoint; the searchable content is the transcript, fetched with
youtube-transcript-api. The transcript is optional enrichment: videos
without captions — and playlists — still become metadata-only scrolls,
and `provenance.extraction_method` records which path produced the item.
The raw oEmbed payload and transcript snippets are kept in `raw_text` so
scrolls and indexes can be rebuilt without refetching.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlencode, urlparse

from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

OEMBED_ENDPOINT = "https://www.youtube.com/oembed"

GetJson = Callable[[str], dict[str, Any]]
GetTranscript = Callable[[str], list[dict[str, Any]]]


def fetch_item(
    item: ScrollItem,
    *,
    get_json: GetJson | None = None,
    get_transcript: GetTranscript | None = None,
) -> ScrollItem:
    """Fetch a detected YouTube item's metadata and transcript; return it at stage 'fetched'.

    Raises FetchError when the video/playlist identity is missing or the
    oEmbed request fails; a missing transcript only downgrades the item to
    metadata-only. The input item is never mutated.
    """
    get_json = get_json or _get_json
    get_transcript = get_transcript or _get_transcript
    if not item.source_id:
        raise FetchError(f"cannot determine youtube video for item {item.id!r}")

    is_playlist = _is_playlist_url(item.url)
    if is_playlist:
        canonical_url = f"https://www.youtube.com/playlist?list={item.source_id}"
    else:
        canonical_url = f"https://www.youtube.com/watch?v={item.source_id}"

    try:
        oembed = get_json(_oembed_url(canonical_url))
    except (OSError, ValueError) as exc:
        raise FetchError(f"youtube oEmbed request failed: {exc}") from exc

    transcript: list[dict[str, Any]] | None = None
    if not is_playlist:
        # The transcript is optional: the client raises a wide range of
        # errors (no captions, subtitles disabled, region-blocked) and none
        # of them should fail an otherwise-identified video.
        try:
            transcript = list(get_transcript(item.source_id))
        except Exception:
            transcript = None

    text = _transcript_text(transcript)
    if not text:
        transcript = None
    hashed = text or json.dumps(oembed, sort_keys=True, ensure_ascii=False)

    thumbnail = oembed.get("thumbnail_url")
    return replace(
        item,
        title=oembed.get("title") or item.title,
        author=oembed.get("author_name") or None,
        canonical_url=canonical_url,
        raw_text=json.dumps(
            {"oembed": oembed, "transcript": transcript}, ensure_ascii=False
        ),
        extracted_text=text or None,
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        media=({"type": "thumbnail", "url": thumbnail},) if thumbnail else (),
        provenance={
            "adapter": "youtube",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "oembed+youtube-transcript-api" if text else "oembed",
        },
        stage="fetched",
    )


def _is_playlist_url(url: str) -> bool:
    path_parts = [p for p in urlparse(url).path.split("/") if p]
    return path_parts[:1] == ["playlist"]


def _oembed_url(target_url: str) -> str:
    return f"{OEMBED_ENDPOINT}?{urlencode({'url': target_url, 'format': 'json'})}"


def _transcript_text(transcript: list[dict[str, Any]] | None) -> str:
    if not transcript:
        return ""
    return " ".join(
        " ".join(str(snippet.get("text", "")).split()) for snippet in transcript
    ).strip()


def _get_transcript(video_id: str) -> list[dict[str, Any]]:
    """Fetch transcript snippets, preferring English, else any available language.

    Imported lazily so commands that never fetch YouTube don't pay for it.
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    transcripts = YouTubeTranscriptApi().list(video_id)
    try:
        transcript = transcripts.find_transcript(["en"])
    except Exception:
        transcript = next(iter(transcripts))  # manual captions first, then generated
    return transcript.fetch().to_raw_data()


_get_json = http.get_json
