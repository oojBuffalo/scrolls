"""Plain-text normalization shared by Markdown-bearing adapters.

Sources whose payload is already Markdown — no HTML to strip — still need
the same light tidy before the text becomes a scroll's body: normalize line
endings and collapse the blank-line runs an authored or API-rendered body
accumulates. The code hosts (github/gitlab/gitea/bitbucket, ADR 0084-0087),
Lobsters (ADR 0046), and dev.to (ADR 0061) had each carried a byte-identical
copy of that three-line `_plain`; this module owns it once, the text-side
companion to `discussion.format_thread` (ADR 0093) and `urls.scan_urls`
(ADR 0094). Adapters that must strip HTML (web, the Fediverse, Stack Exchange)
have their own extraction and do not use this.
"""

from __future__ import annotations

import re

__all__ = ["normalize_markdown"]

_BLANK_RUN_RE = re.compile(r"\n{3,}")


def normalize_markdown(text: str) -> str:
    """Tidy an already-Markdown body: CRLF/CR to LF, collapse blank runs, strip.

    Line endings are normalized to `\n`, three-or-more consecutive newlines
    (a blank-line run) collapse to one blank line, and surrounding whitespace
    is trimmed. There is no HTML handling — callers pass text that is already
    Markdown or plain (Lobsters' `*_plain` economy, ADR 0046).
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _BLANK_RUN_RE.sub("\n\n", text)
    return text.strip()
