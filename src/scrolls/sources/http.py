"""Shared HTTP transport for source adapters.

Stdlib urllib with a descriptive User-Agent (API etiquette for Wikipedia
and friendliness elsewhere). Adapters keep these behind injectable
parameters so tests never touch the network.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from scrolls import __version__

USER_AGENT = f"scrolls/{__version__} (+https://github.com/oojBuffalo/scrolls)"
_TIMEOUT_SECONDS = 30


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
