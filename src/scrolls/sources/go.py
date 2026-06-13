"""Go modules fetch adapter (IDEAS.md §6, ADR 0042).

A saved Go module page (`pkg.go.dev/<module>`) becomes a clean scroll
instead of a `trafilatura` scrape of a JS-rendered docs page. Two GETs
against the keyless Go module proxy (`proxy.golang.org`) — no auth, no
runtime dependency — return everything the proxy holds: the module's
latest version and publish time (`/@latest`) and its `go.mod` manifest
(`/@v/<version>.mod`). This is the last obvious registry on the
JSON-metadata pattern the PyPI, npm, crates.io, Packagist, and RubyGems
adapters established (ADR 0034–0036, 0039, 0040), and the sparsest:

1. **Identity is the module path, case-sensitive.** A Go module path is
   `<host>/<owner>/<repo>[/...]` (or a vanity path like `golang.org/x/tools`,
   `rsc.io/quote`). Paths are case-sensitive — the proxy *case-encodes*
   uppercase letters as `!`+lowercase (`github.com/Masterminds/squirrel`
   → `github.com/!masterminds/squirrel`), and an unescaped mixed-case path
   is a 400 — so the source id is preserved verbatim (npm/RubyGems' rule)
   and only the proxy *request* URL is escaped. Folding would corrupt the
   identity of a mixed-case module.

2. **The proxy carries no description, keywords, or license.** Unlike the
   other registries, `/@latest` returns only `{Version, Time, Origin}`,
   so a Go scroll has no `summary` (honest — there is no description),
   empty `concepts` (no keywords, like RubyGems — ADR 0040), and empty
   `tags` (no license/classifier facet at all). The `go.mod` manifest is
   the only content: it declares the module path, the `go` directive, and
   the dependency graph, so it becomes the searchable `extracted_text` —
   the closest honest analog to crates' README (ADR 0036). A `.mod` that
   fails to fetch degrades to a metadata-only scroll (ADR 0002).

3. **The repo link comes from `Origin`, with a path fallback.** `/@latest`
   often carries an `Origin.URL` — the actual VCS repository, which for a
   vanity path (`golang.org/x/tools` → `go.googlesource.com/tools`) is the
   only way to learn the repo. When it is absent (older modules omit it),
   the repo is derived from the module path for the well-known VCS hosts
   (`github.com`/`gitlab.com`/`bitbucket.org`). Either way it becomes the
   one `link`, resolving through `scrolls related` to a saved github repo
   (the package↔repo edge the whole family produces).

A Go module classifies as `tool` like the other packages (ADR 0004).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

PROXY_ROOT = "https://proxy.golang.org"
SITE_ROOT = "https://pkg.go.dev"
# A go.mod is a few KB; cap the download defensively (reuses npm/crates'
# capped-GET transport, ADR 0035).
_MOD_MAX_BYTES = 1_000_000

# Module paths whose first segment is one of these resolve their repo
# straight from the path when the proxy omits Origin.
_VCS_HOSTS = ("github.com", "gitlab.com", "bitbucket.org")

_MODULE_DECL = re.compile(r"^module\s+(\S+)", re.MULTILINE)

GetJson = Callable[[str], Any]
GetText = Callable[[str], str]


def fetch_item(
    item: ScrollItem,
    *,
    get_json: GetJson | None = None,
    get_text: GetText | None = None,
) -> ScrollItem:
    """Fetch a detected Go module's proxy metadata; return it at stage 'fetched'.

    Raises FetchError when the module path is missing, the request fails,
    or the proxy has no such module. The input item is never mutated.
    """
    get_json = get_json or http.get_json
    get_text = get_text or _get_mod_text
    module = item.source_id
    if not module:
        raise FetchError(f"cannot determine module for item {item.id!r}")

    escaped = _escape(module)
    try:
        latest = get_json(f"{PROXY_ROOT}/{escaped}/@latest")
    except (OSError, ValueError) as exc:
        raise FetchError(f"Go module proxy request failed: {exc}") from exc

    version = latest.get("Version") if isinstance(latest, dict) else None
    if not isinstance(version, str) or not version:
        raise FetchError(f"module not found: {module}")

    # The go.mod is the only content the proxy holds; a failed fetch
    # degrades to a metadata-only scroll (ADR 0002).
    go_mod = _fetch_mod(get_text, escaped, version)
    title = _module_decl(go_mod) or module

    raw = json.dumps(latest, ensure_ascii=False)
    hashed = go_mod or raw
    return replace(
        item,
        title=title,
        published_at=_published(latest) or item.published_at,
        canonical_url=f"{SITE_ROOT}/{module}",
        raw_text=raw,
        extracted_text=go_mod,
        summary=None,  # the proxy carries no description — honestly empty
        tags=(),  # no license/classifier facet in the proxy
        concepts=(),  # no keywords — structurally empty, like RubyGems
        links=_links(latest, module),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "go",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "go-proxy:mod" if go_mod else "go-proxy:latest",
        },
        stage="fetched",
    )


def _escape(path: str) -> str:
    """Case-encode a module path or version for the proxy: `X` -> `!x`.

    The Go module proxy protocol escapes every uppercase letter as a `!`
    followed by its lowercase form, so a verbatim mixed-case identity can
    address the proxy without a 400 ("invalid escaped module path").
    """
    return re.sub(r"[A-Z]", lambda m: "!" + m.group(0).lower(), path)


def _fetch_mod(get_text: GetText, escaped_module: str, version: str) -> str | None:
    """The module's `go.mod` text at `version`, or None if it can't be fetched."""
    url = f"{PROXY_ROOT}/{escaped_module}/@v/{_escape(version)}.mod"
    try:
        text = get_text(url)
    except (OSError, ValueError):
        return None
    text = (text or "").strip()
    return text or None


def _module_decl(go_mod: str | None) -> str | None:
    """The canonical module path from a go.mod `module <path>` line, or None.

    Authoritative over the URL-derived source id (a path may be declared
    with different casing than the page that was saved), with the source
    id as the fallback when the go.mod is absent or malformed.
    """
    if not go_mod:
        return None
    match = _MODULE_DECL.search(go_mod)
    return match.group(1).strip('"') if match else None


def _published(latest: dict[str, Any]) -> str | None:
    """The latest version's publish time as UTC ISO 8601, or None.

    `/@latest` `Time` is RFC 3339 with a `Z` suffix; the shared
    `to_utc_iso` (ADR 0024) normalizes it. Guarded with isinstance because
    `to_utc_iso` strips its argument.
    """
    time = latest.get("Time")
    return to_utc_iso(time) if isinstance(time, str) else None


def _links(latest: dict[str, Any], module: str) -> tuple[str, ...]:
    """The module's source repository as the one link, or empty.

    Prefers the proxy's `Origin.URL` (the real VCS repo, the only source
    of truth for a vanity path); falls back to deriving the repo from the
    module path for the well-known VCS hosts. The `.git` suffix is folded
    so `detect_source` reads a clean `owner/repo` and `scrolls related`
    resolves the link to a saved github repo (the package↔repo edge).
    """
    repo = _origin_url(latest) or _repo_from_module(module)
    return (repo,) if repo else ()


def _origin_url(latest: dict[str, Any]) -> str | None:
    origin = latest.get("Origin") if isinstance(latest, dict) else None
    url = origin.get("URL") if isinstance(origin, dict) else None
    return _clean_repo(url)


def _clean_repo(url: Any) -> str | None:
    """An http(s) repo URL with no `.git` suffix, or None."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    if url.endswith(".git"):
        url = url[: -len(".git")]
    if not url.lower().startswith(("http://", "https://")):
        return None
    return url or None


def _repo_from_module(module: str) -> str | None:
    """`https://<host>/<owner>/<repo>` for a well-known VCS host module path, else None."""
    segments = [s for s in module.split("/") if s]
    if len(segments) >= 3 and segments[0] in _VCS_HOSTS:
        return "https://" + "/".join(segments[:3])
    return None


def _get_mod_text(url: str) -> str:
    """Default go.mod fetcher: a capped GET decoded as UTF-8."""
    return http.get_bytes(url, max_bytes=_MOD_MAX_BYTES).decode("utf-8", errors="replace")
