"""Shared HTTP transport for source adapters.

Stdlib urllib with a descriptive User-Agent (API etiquette for Wikipedia
and friendliness elsewhere). Adapters keep these behind injectable
parameters so tests never touch the network.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from scrolls import __version__

USER_AGENT = f"scrolls/{__version__} (+https://github.com/oojBuffalo/scrolls)"
_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class ConditionalText:
    """A conditional GET's outcome: fresh text plus its validators, or a 304."""

    text: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


def get_bytes(url: str, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        return response.read()


def get_text(url: str, headers: dict[str, str] | None = None) -> str:
    return get_bytes(url, headers).decode("utf-8", errors="replace")


def get_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    return json.loads(get_text(url, headers))


def get_conditional(
    url: str, etag: str | None = None, last_modified: str | None = None
) -> ConditionalText:
    """GET with If-None-Match/If-Modified-Since (ADR 0019).

    urllib surfaces 304 as HTTPError; here it becomes an honest
    `not_modified` result. A 200 carries the response's own validators
    so the caller can store them for the next poll.
    """
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return ConditionalText(
                text=response.read().decode("utf-8", errors="replace"),
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
            )
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            exc.close()
            return ConditionalText(not_modified=True)
        raise
