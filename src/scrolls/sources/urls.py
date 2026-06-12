"""URL normalization for item identity (ADR 0023).

The URL-hash half of `make_item_id` makes the URL string itself the
identity of `web`/`pdf` items, so volatile decorations — tracking
params, fragments, host casing, default ports — would mint a fresh
item id for the same resource (ADR 0017's known identity quirk).
`normalize_url` collapses exactly the decorations that never change
what a fetch returns and keeps everything else byte-identical: a
dropped param that mattered would silently merge different pages,
which is worse than the duplicate it prevents.
"""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

_DEFAULT_PORTS = {"http": 80, "https": 443}

# Unambiguous cross-site click/campaign identifiers. Names that mean
# something somewhere (`ref` is a GitHub branch, `si`/`source` carry
# state on enough sites) stay out — see the module docstring.
_TRACKING_NAMES = frozenset({
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "twclid",
    "yclid", "igshid", "mc_cid", "mc_eid", "_hsenc", "_hsmi", "mkt_tok",
    "vero_conv", "vero_id", "oly_anon_id", "oly_enc_id",
})
_TRACKING_PREFIXES = ("utm_",)


def normalize_url(url: str) -> str:
    """Normalize an http(s) URL for identity; pass anything else through.

    Lowercases scheme and host, drops default ports, the fragment, and
    known tracking params; keeps every other query param in its
    original order and percent-encoding. Idempotent.
    """
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    scheme = parsed.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not parsed.hostname:
        return cleaned
    return urlunparse((
        scheme,
        _normalized_netloc(parsed, scheme),
        parsed.path or "/",
        parsed.params,
        _without_tracking(parsed.query),
        "",  # the fragment is never sent to the server
    ))


def _normalized_netloc(parsed, scheme: str) -> str:
    host = parsed.hostname.lower()
    if ":" in host:  # bare IPv6 address; urlparse strips its brackets
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:  # non-numeric port; not ours to repair
        return parsed.netloc
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        host = f"{host}:{port}"
    if parsed.username:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo += f":{parsed.password}"
        host = f"{userinfo}@{host}"
    return host


def _without_tracking(query: str) -> str:
    kept = [
        part for part in query.split("&")
        if part and not _is_tracking(part.split("=", 1)[0])
    ]
    return "&".join(kept)


def _is_tracking(name: str) -> bool:
    lowered = name.lower()
    return lowered in _TRACKING_NAMES or lowered.startswith(_TRACKING_PREFIXES)
