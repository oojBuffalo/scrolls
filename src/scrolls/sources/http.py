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


def get_bytes(
    url: str, headers: dict[str, str] | None = None, max_bytes: int | None = None
) -> bytes:
    """GET the URL's bytes, optionally refusing a body larger than `max_bytes`.

    With `max_bytes` set the body is read in chunks and a ValueError is
    raised the moment it would exceed the cap, so a caller that only wants
    a small file (a package README inside a tarball, say) never buffers an
    unexpectedly huge download.
    """
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        if max_bytes is None:
            return response.read()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"response body exceeds {max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)


def get_text(url: str, headers: dict[str, str] | None = None) -> str:
    return get_bytes(url, headers).decode("utf-8", errors="replace")


def get_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    return json.loads(get_text(url, headers))


def post_json(
    url: str, payload: Any, headers: dict[str, str] | None = None
) -> Any:
    """POST a JSON body and parse the JSON response.

    For APIs that take a JSON request body rather than query params — Misskey's
    `/api/notes/show` (ADR 0051) is the first. The payload is JSON-encoded with
    a `Content-Type: application/json` header and the shared descriptive
    User-Agent; transport and HTTP errors propagate as urllib raises them
    (HTTPError is an OSError, so adapters catch them the same way as a GET).
    The response may be an object or an array (Misskey's `notes/children`),
    so the return type is the parsed JSON as-is.
    """
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
            **(headers or {}),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


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
