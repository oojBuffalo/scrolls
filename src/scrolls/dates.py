"""One `published_at` vocabulary: UTC ISO 8601 (ADR 0024).

Sources speak different date dialects — trafilatura's bare
`YYYY-MM-DD`, GitHub's and Atom's RFC 3339 `Z` suffix, RSS 2.0's
RFC 822 pubDates, PDF creation datetimes with arbitrary offsets.
Every writer of `published_at` funnels through `to_utc_iso` so the
stored field is one shape: `isoformat(timespec="seconds")` in UTC.
Composed as `to_utc_iso(source_date) or fallback`, an unparseable
source date degrades to the fallback instead of storing garbage.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def epoch_to_utc_iso(text: str | None) -> str | None:
    """A Unix-epoch string as UTC ISO 8601, or None when absent/unparseable.

    Bookmark exporters disagree on the unit — Netscape-format ADD_DATE
    is epoch seconds in modern browsers, but milli- and microsecond
    variants exist in the wild — so values too large to be seconds are
    divided down until they are. Zero and negative values are treated
    as absent: exporters write them for "no date", never for 1970.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if not math.isfinite(value) or value <= 0:  # "inf" would loop below
        return None
    while value > 1e11:  # beyond year 5138 in seconds: a smaller unit
        value /= 1000
    try:
        stamp = datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return stamp.isoformat(timespec="seconds")


def iso_to_epoch(text: str | None) -> str | None:
    """A UTC ISO 8601 timestamp as a Unix-epoch-seconds string — `epoch_to_utc_iso`'s
    inverse, for writing a bookmark export's `ADD_DATE` from a stored `saved_at`.

    Returns the whole-second epoch as a string (the Netscape format's unit;
    fractional seconds are truncated, matching the seconds-precision the
    library stores) or None when the input is absent or unparseable, so a
    caller composes `iso_to_epoch(saved_at)` and simply omits the attribute on
    None. A naive timestamp is assumed UTC, mirroring `to_utc_iso`. Round-trips
    with `epoch_to_utc_iso` for any seconds-precision UTC timestamp.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return str(int(parsed.timestamp()))


def to_utc_iso(text: str | None) -> str | None:
    """`text` as a UTC ISO 8601 timestamp, or None when absent/unparseable.

    Accepts ISO 8601 / RFC 3339 (including date-only, which becomes
    midnight UTC — invented precision, but one shape for the whole
    field beats two parsers in every consumer) and RFC 822 dates.
    Naive datetimes are assumed UTC.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    for parse in (datetime.fromisoformat, parsedate_to_datetime):
        try:
            parsed = parse(cleaned)
        except (ValueError, TypeError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    return None
