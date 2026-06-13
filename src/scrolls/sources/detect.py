"""URL source detection for `scrolls add <url>` (IDEAS.md §5).

Maps a URL to the source adapter that should handle it, plus a stable
source-local identifier when one can be read off the URL itself. The pair
feeds the `source:source_id` item-ID scheme (IDEAS.md §12). A known source
with `source_id=None` means the adapter must resolve identity at fetch time.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}
GITHUB_HOSTS = {"github.com", "www.github.com"}
ARXIV_HOSTS = {"arxiv.org", "www.arxiv.org"}
HACKERNEWS_HOSTS = {"news.ycombinator.com", "www.news.ycombinator.com"}

# Stack Exchange network sites on dedicated domains, mapped to the API
# `site` slug. Every *.stackexchange.com subdomain is its own site (the
# label before .stackexchange.com), handled separately.
STACKEXCHANGE_DEDICATED = {
    "stackoverflow.com": "stackoverflow",
    "superuser.com": "superuser",
    "serverfault.com": "serverfault",
    "askubuntu.com": "askubuntu",
    "mathoverflow.net": "mathoverflow.net",
    "stackapps.com": "stackapps",
}

# Top-level github.com path segments that are site pages, not user accounts.
GITHUB_RESERVED = {
    "about", "collections", "events", "explore", "features", "login",
    "marketplace", "orgs", "pricing", "settings", "sponsors", "topics",
    "trending",
}


@dataclass(frozen=True)
class DetectedSource:
    source: str
    source_id: str | None = None


def detect_source(url: str) -> DetectedSource:
    """Detect which source adapter a URL belongs to.

    Raises ValueError for anything that is not an absolute http(s) URL.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"not an http(s) URL: {url!r}")

    host = parsed.hostname.lower()
    path_parts = [p for p in parsed.path.split("/") if p]

    if host in YOUTUBE_HOSTS or host == "youtu.be":
        return DetectedSource("youtube", _youtube_id(host, path_parts, parsed.query))

    if host == "wikipedia.org" or host.endswith(".wikipedia.org"):
        return DetectedSource("wikipedia", _wikipedia_id(host, path_parts))

    if host in GITHUB_HOSTS:
        return DetectedSource("github", _github_id(path_parts))

    if host in ARXIV_HOSTS:
        return DetectedSource("arxiv", _arxiv_id(path_parts))

    if host in X_HOSTS:
        return DetectedSource("x", _x_status_id(path_parts))

    if host in HACKERNEWS_HOSTS:
        return DetectedSource("hackernews", _hackernews_id(path_parts, parsed.query))

    se_site = _stackexchange_site(host)
    if se_site is not None:
        return DetectedSource("stackexchange", _stackexchange_id(se_site, path_parts))

    if parsed.path.lower().endswith(".pdf"):
        return DetectedSource("pdf")

    return DetectedSource("web")


def _youtube_id(host: str, path_parts: list[str], query: str) -> str | None:
    if host == "youtu.be":
        return path_parts[0] if path_parts else None
    if not path_parts:
        return None
    head = path_parts[0]
    if head == "watch":
        return _first_query_value(query, "v")
    if head == "playlist":
        return _first_query_value(query, "list")
    if head in ("shorts", "embed", "live") and len(path_parts) > 1:
        return path_parts[1]
    return None


def _wikipedia_id(host: str, path_parts: list[str]) -> str | None:
    if len(path_parts) < 2 or path_parts[0] != "wiki":
        return None
    # en.wikipedia.org / en.m.wikipedia.org -> "en"; bare wikipedia.org has no language
    lang = host.split(".")[0]
    if lang in ("wikipedia", "www"):
        return None
    title = unquote("/".join(path_parts[1:]))
    return f"{lang}:{title}" if title else None


def _github_id(path_parts: list[str]) -> str | None:
    if len(path_parts) < 2 or path_parts[0] in GITHUB_RESERVED:
        return None
    return f"{path_parts[0]}/{path_parts[1]}"


def _arxiv_id(path_parts: list[str]) -> str | None:
    if len(path_parts) < 2 or path_parts[0] not in ("abs", "pdf"):
        return None
    arxiv_id = "/".join(path_parts[1:])
    if arxiv_id.lower().endswith(".pdf"):
        arxiv_id = arxiv_id[: -len(".pdf")]
    return arxiv_id or None


def _x_status_id(path_parts: list[str]) -> str | None:
    # /<user>/status/<numeric-id>
    if len(path_parts) >= 3 and path_parts[1] == "status" and path_parts[2].isdigit():
        return path_parts[2]
    return None


def _stackexchange_site(host: str) -> str | None:
    """The Stack Exchange API `site` slug for a host, or None if not the network.

    Dedicated domains map through a table; every *.stackexchange.com host
    is its own site named by the label before `.stackexchange.com`, so
    `math.stackexchange.com` -> `math` and `rpg.meta.stackexchange.com` ->
    `rpg.meta`. Meta sites of dedicated domains (`meta.stackoverflow.com`)
    map to `meta.<slug>`.
    """
    if host.startswith("www."):
        host = host[4:]
    if host in STACKEXCHANGE_DEDICATED:
        return STACKEXCHANGE_DEDICATED[host]
    if host.endswith(".stackexchange.com"):
        return host[: -len(".stackexchange.com")] or None
    if host.startswith("meta."):
        base = STACKEXCHANGE_DEDICATED.get(host[len("meta."):])
        if base:
            return f"meta.{base}"
    return None


def _stackexchange_id(site: str, path_parts: list[str]) -> str | None:
    """`<site>:<question_id>` for a question URL, else None.

    Question URLs are `/questions/<id>/...` and the `/q/<id>` shortlink;
    answer permalinks (`/a/<id>`), tag pages, and user pages carry no
    question id, so they are the source with no fetchable item.
    """
    if len(path_parts) >= 2 and path_parts[0] in ("questions", "q") and path_parts[1].isdigit():
        return f"{site}:{path_parts[1]}"
    return None


def _hackernews_id(path_parts: list[str], query: str) -> str | None:
    # /item?id=<numeric>; front page, /user, /newest etc. carry no item id
    if path_parts == ["item"]:
        item_id = _first_query_value(query, "id")
        if item_id and item_id.isdigit():
            return item_id
    return None


def _first_query_value(query: str, key: str) -> str | None:
    values = parse_qs(query).get(key)
    return values[0] if values else None
