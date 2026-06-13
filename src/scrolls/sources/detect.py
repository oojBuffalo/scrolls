"""URL source detection for `scrolls add <url>` (IDEAS.md §5).

Maps a URL to the source adapter that should handle it, plus a stable
source-local identifier when one can be read off the URL itself. The pair
feeds the `source:source_id` item-ID scheme (IDEAS.md §12). A known source
with `source_id=None` means the adapter must resolve identity at fetch time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}
GITHUB_HOSTS = {"github.com", "www.github.com"}
ARXIV_HOSTS = {"arxiv.org", "www.arxiv.org"}
HACKERNEWS_HOSTS = {"news.ycombinator.com", "www.news.ycombinator.com"}
PYPI_HOSTS = {"pypi.org", "www.pypi.org"}
NPM_HOSTS = {"npmjs.com", "www.npmjs.com"}
CRATES_HOSTS = {"crates.io", "www.crates.io"}
PACKAGIST_HOSTS = {"packagist.org", "www.packagist.org"}
RUBYGEMS_HOSTS = {"rubygems.org", "www.rubygems.org"}
# doi.org is the canonical DOI resolver; dx.doi.org is its legacy alias.
# Both carry the DOI as the whole path, handled by the Crossref adapter.
DOI_HOSTS = {"doi.org", "www.doi.org", "dx.doi.org", "www.dx.doi.org"}

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

    if host in PYPI_HOSTS:
        return DetectedSource("pypi", _pypi_id(path_parts))

    if host in NPM_HOSTS:
        return DetectedSource("npm", _npm_id(path_parts))

    if host in CRATES_HOSTS:
        return DetectedSource("crates", _crates_id(path_parts))

    if host in PACKAGIST_HOSTS:
        return DetectedSource("packagist", _packagist_id(path_parts))

    if host in RUBYGEMS_HOSTS:
        return DetectedSource("rubygems", _rubygems_id(path_parts))

    if host in DOI_HOSTS:
        return DetectedSource("crossref", _crossref_id(path_parts))

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


def _pypi_id(path_parts: list[str]) -> str | None:
    """The PEP 503-normalized project name for a `/project/<name>[/<version>]` URL.

    Identity is the project name only: `Flask`, `flask`, and the versioned
    page `/project/flask/3.0.0/` are the same package, so the trailing
    version segment is ignored. Search, user, and help pages carry no
    project name and resolve to the source with no fetchable item.
    """
    if len(path_parts) < 2 or path_parts[0] != "project":
        return None
    return _normalize_project_name(path_parts[1])


def _normalize_project_name(name: str) -> str | None:
    """Canonical PyPI project name (PEP 503): case-folded, `[-_.]` runs to one `-`."""
    normalized = re.sub(r"[-_.]+", "-", unquote(name)).strip("-").lower()
    return normalized or None


def _npm_id(path_parts: list[str]) -> str | None:
    """The package name for a `/package/<name>[/v/<version>]` URL, else None.

    The name may be scoped (`@scope/name`, three URL segments after
    `package`), and a `/v/<version>` suffix is ignored: a version page is
    the same package, identity is the name only — the PyPI pattern
    (ADR 0034). Unlike PyPI's PEP 503 fold, the name is preserved
    verbatim because the npm registry is case-sensitive (legacy
    mixed-case packages like `JSONStream` 404 when lowercased), so
    folding could break the fetch. Search, user (`~name`), and org pages
    carry no package name and resolve to the source with no fetchable
    item — github's and PyPI's pattern.
    """
    if len(path_parts) < 2 or path_parts[0] != "package":
        return None
    first = unquote(path_parts[1]).strip()
    if first.startswith("@"):
        # Scoped: `@scope/name`. Normally three segments, but a
        # percent-encoded slash (`@scope%2Fname`) decodes whole here.
        if "/" in first:
            name = first
        elif len(path_parts) >= 3:
            name = f"{first}/{unquote(path_parts[2]).strip()}"
        else:
            return None
    else:
        name = first
    return name or None


def _crates_id(path_parts: list[str]) -> str | None:
    """The normalized crate name for a `/crates/<name>[/<version>]` URL, else None.

    Identity is the crate name only: `serde_json` and the versioned page
    `/crates/serde_json/1.0.150` are the same crate, so the trailing
    version segment is ignored. crates.io is case-insensitive and treats
    `-`/`_` as equivalent, so the name is folded the way PyPI applies PEP
    503 (`serde-json` and `serde_json` dedupe to one id) — the registry
    resolves the folded form, and the adapter reads the canonical
    published name back from the API. The crate list, search, user, and
    category pages carry no crate name and resolve to the source with no
    fetchable item.
    """
    if len(path_parts) < 2 or path_parts[0] != "crates":
        return None
    return _normalize_crate_name(path_parts[1])


def _normalize_crate_name(name: str) -> str | None:
    """Canonical crates.io lookup name: case-folded, `[-_]` runs to one `-`."""
    normalized = re.sub(r"[-_]+", "-", unquote(name)).strip("-").lower()
    return normalized or None


# A Composer package name is `vendor/package`; each part is lowercase
# alphanumerics with single `_.-` separators (the composer.json schema).
_PACKAGIST_NAME_RE = re.compile(r"[a-z0-9]([_.-]?[a-z0-9]+)*")


def _packagist_id(path_parts: list[str]) -> str | None:
    """The `vendor/package` name for a `/packages/<vendor>/<package>` URL, else None.

    Composer package names are `vendor/package` and case-insensitive —
    the schema forbids uppercase, and Packagist redirects mixed case to
    the lowercase canonical — so the id is folded lowercase: `Monolog/Monolog`
    and `monolog/monolog` dedupe to one item, the canonical form read back
    from the API response. A trailing `.json` (the API URL people paste)
    and any deeper path (`/stats`, `/dependents`) are dropped; the
    packages list, a vendor-only page, and search carry no package name
    and resolve to the source with no fetchable item.
    """
    if len(path_parts) < 3 or path_parts[0] != "packages":
        return None
    vendor = unquote(path_parts[1]).strip().lower()
    package = unquote(path_parts[2]).strip().lower()
    if package.endswith(".json"):
        package = package[: -len(".json")]
    if not _fullmatch(_PACKAGIST_NAME_RE, vendor) or not _fullmatch(
        _PACKAGIST_NAME_RE, package
    ):
        return None
    return f"{vendor}/{package}"


def _fullmatch(pattern: re.Pattern[str], text: str) -> bool:
    return bool(text) and pattern.fullmatch(text) is not None


def _rubygems_id(path_parts: list[str]) -> str | None:
    """The gem name for a `/gems/<name>[/versions/<v>]` URL, verbatim, else None.

    Identity is the gem name only: `/gems/rails` and the version page
    `/gems/rails/versions/8.1.3` are the same gem. RubyGems gem names are
    case-sensitive (`gems/Ascii85` resolves, `gems/ascii85` 404s), so the
    name is preserved verbatim — npm's rule (ADR 0035), not the
    case-folding PyPI/crates/Packagist apply. The gems list and search
    pages carry no gem name and resolve to the source with no fetchable
    item.
    """
    if len(path_parts) < 2 or path_parts[0] != "gems":
        return None
    name = unquote(path_parts[1]).strip()
    return name or None


_DOI_RE = re.compile(r"^10\.\d{4,}/.+$")


def _crossref_id(path_parts: list[str]) -> str | None:
    """The DOI for a `doi.org/<doi>` URL, lowercased, else None.

    A DOI is `10.<registrant>/<suffix>` and the suffix may itself contain
    slashes, so the whole path is the identifier (path segments rejoined,
    percent-decoded). DOIs are case-insensitive — the DOI Handbook §2.4 —
    and Crossref stores them lowercased, so the id is folded: `doi.org`
    and the legacy `dx.doi.org`, and any case variant, dedupe to one item.
    The canonical published form is read back from the Crossref response.
    The bare resolver host and non-DOI paths carry no fetchable item.
    """
    if not path_parts:
        return None
    doi = unquote("/".join(path_parts)).strip().lower()
    return doi if _DOI_RE.match(doi) else None


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
