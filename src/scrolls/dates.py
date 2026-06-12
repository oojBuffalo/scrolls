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

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


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
