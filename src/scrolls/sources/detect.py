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
# Gists live on a distinct host with a distinct API (`/gists/<id>`, not
# `/repos/<owner>/<repo>`) and content (code snippets, not repo metadata), so
# they are their own source rather than a github repo shape (ADR 0078).
GIST_HOSTS = {"gist.github.com", "www.gist.github.com"}
GITLAB_HOSTS = {"gitlab.com", "www.gitlab.com"}
# Gitea/Forgejo is self-hosted across many hosts, but only the two big public
# instances are recognized for now (host-scoped like github/gitlab; a bare
# repo root has no shape tell — ADR 0055/0056). Codeberg runs Forgejo,
# gitea.com runs Gitea; one `gitea` source covers both (ADR 0056).
GITEA_HOSTS = {"codeberg.org", "www.codeberg.org", "gitea.com", "www.gitea.com"}
# Bitbucket Cloud is a single hosted service (api.bitbucket.org), so it is
# host-scoped like github/gitlab — not host-in-id like gitea (ADR 0057).
# Bitbucket Server/Data Center (self-hosted, a different API) is deferred like
# self-hosted GitLab.
BITBUCKET_HOSTS = {"bitbucket.org", "www.bitbucket.org"}
ARXIV_HOSTS = {"arxiv.org", "www.arxiv.org"}
# bioRxiv and medRxiv are sibling preprint servers run by one operator (Cold
# Spring Harbor Laboratory) on one shared API (`api.biorxiv.org/details/<server>/
# <doi>`) that differs only by a `[server]` path segment. They are kept as two
# *distinct* sources, not one (the huggingface kind-in-id pattern), because a
# medRxiv paper does not live on bioRxiv — labeling it `source=biorxiv` would be
# dishonest. One fetch adapter serves both, reading `item.source` to pick the
# server (ADR 0068).
BIORXIV_HOSTS = {"biorxiv.org", "www.biorxiv.org"}
MEDRXIV_HOSTS = {"medrxiv.org", "www.medrxiv.org"}
HACKERNEWS_HOSTS = {"news.ycombinator.com", "www.news.ycombinator.com"}
LOBSTERS_HOSTS = {"lobste.rs", "www.lobste.rs"}
# bsky.app is the public web app whose post URLs users save; the fetch
# adapter talks to the keyless AppView (public.api.bsky.app).
BLUESKY_HOSTS = {"bsky.app", "www.bsky.app"}
PYPI_HOSTS = {"pypi.org", "www.pypi.org"}
NPM_HOSTS = {"npmjs.com", "www.npmjs.com"}
CRATES_HOSTS = {"crates.io", "www.crates.io"}
PACKAGIST_HOSTS = {"packagist.org", "www.packagist.org"}
RUBYGEMS_HOSTS = {"rubygems.org", "www.rubygems.org"}
# pkg.go.dev is the canonical Go module browse host; the fetch adapter
# talks to proxy.golang.org, deriving the module path from the URL.
GO_HOSTS = {"pkg.go.dev", "www.pkg.go.dev"}
# dev.to is the flagship Forem community; the fetch adapter talks to its
# keyless `/api/articles/<user>/<slug>` endpoint. Self-hosted Forem
# instances have no shape tell (a bare article URL looks like any blog), so
# they are deferred like self-hosted GitLab (ADR 0055/0061).
DEVTO_HOSTS = {"dev.to", "www.dev.to"}
# hf.co is Hugging Face's short domain; it redirects to huggingface.co, but
# the fetch adapter uses the repo id, not the host, so both resolve alike.
HUGGINGFACE_HOSTS = {"huggingface.co", "www.huggingface.co", "hf.co", "www.hf.co"}
# Open Library is the keyless bibliographic catalog for *books* — a content type
# with no prior first-class home (the RFC/dev.to gap, ADR 0066/0061). Books live
# on the one host; the fetch adapter reads the record's `.json` view (ADR 0073).
OPENLIBRARY_HOSTS = {"openlibrary.org", "www.openlibrary.org"}
# Wikidata is the structured-knowledge sibling of Wikipedia (ADR 0075): a graph of
# entities (`Q<digits>`), each with labels, descriptions, type relations, and
# sitelinks back to the Wikipedia articles about it. One host serves the web UI
# (`/wiki/Q42`), the RDF concept URI (`/entity/Q42`), and the canonical entity
# data the adapter reads (`/wiki/Special:EntityData/Q42.json`).
WIKIDATA_HOSTS = {"wikidata.org", "www.wikidata.org", "m.wikidata.org"}
# doi.org is the canonical DOI resolver; dx.doi.org is its legacy alias.
# Both carry the DOI as the whole path, handled by the Crossref adapter.
DOI_HOSTS = {"doi.org", "www.doi.org", "dx.doi.org", "www.dx.doi.org"}
# PubMed has its own dedicated host where the first path segment is the PMID;
# the legacy `ncbi.nlm.nih.gov/pubmed/<pmid>` form rides the shared NCBI host
# that also serves PMC, Gene, Nucleotide, …, so it is matched by *shape* rather
# than claimed wholesale (ADR 0065).
PUBMED_HOSTS = {"pubmed.ncbi.nlm.nih.gov", "www.pubmed.ncbi.nlm.nih.gov"}
NCBI_HOSTS = {"ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov"}
# IETF RFC hosts. These also serve Internet-Drafts, working-group pages, and the
# org site, so — like the shared NCBI host (ADR 0065) — only the `rfc<N>` shape is
# claimed and every other path falls through to `web`. The fetch adapter reads the
# RFC Editor's JSON view regardless of which host the saved URL named.
RFC_HOSTS = {
    "rfc-editor.org", "www.rfc-editor.org",
    "datatracker.ietf.org", "www.datatracker.ietf.org",
    "tools.ietf.org", "www.tools.ietf.org",
    "ietf.org", "www.ietf.org",
}

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

# Top-level gist.github.com path segments that are site routes, not gist owners.
GIST_RESERVED = {"discover", "starred", "search", "mine", "auth"}

# Top-level gitlab.com path segments that are site pages or platform routes,
# never the first segment of a project's group/project path. GitLab reserves
# these names so no group can claim them, so excluding them can't shadow a
# real project.
GITLAB_RESERVED = {
    "admin", "api", "dashboard", "explore", "groups", "help", "import",
    "profile", "projects", "public", "register", "s", "search", "sign_in",
    "snippets", "users",
}

# Top-level Gitea/Forgejo path segments that are site pages or platform
# routes, never a repo owner. Drawn from Gitea's reserved-username list (so
# none can shadow a real account); only the names that appear as top-level
# routes are kept, github's small-set scale.
GITEA_RESERVED = {
    "-", "admin", "api", "assets", "attachments", "avatar", "avatars",
    "explore", "ghost", "help", "issues", "login", "milestones", "new",
    "notifications", "org", "pulls", "repo", "search", "sign_up", "user",
}

# Top-level bitbucket.org path segments that are site pages or platform routes,
# never a repo workspace. Bitbucket repos live at `<workspace>/<repo>`, so only
# the first-segment site routes need excluding (github's small-set scale).
BITBUCKET_RESERVED = {
    "account", "dashboard", "repo", "snippets", "product", "plans", "pricing",
    "support", "blog", "whats-new",
}

# Top-level dev.to path segments that are site routes, never an article's
# author/org handle. Forem reserves these names so no user can claim them, so
# excluding them can't shadow a real article. `t` (tag pages, `/t/<tag>`) is
# the common two-segment collision; the rest are the platform's fixed routes.
DEVTO_RESERVED = {
    "t", "tags", "search", "settings", "dashboard", "admin", "enter", "new",
    "notifications", "readinglist", "listings", "pod", "videos", "about",
    "contact", "privacy", "terms", "code-of-conduct", "faq", "api", "page",
    "onboarding", "welcome", "signout", "latest", "top",
}

# Top-level huggingface.co path segments that are site pages, not model repos.
# `datasets` and `spaces` are handled by dedicated branches before this set is
# consulted; the rest are routes that can never be a model's `<org>/<name>`.
HUGGINGFACE_RESERVED = {
    "datasets", "spaces", "docs", "blog", "models", "tasks", "pricing",
    "settings", "login", "join", "organizations", "posts", "papers",
    "collections", "new", "notifications", "search", "chat", "learn",
    "enterprise", "api", "support", "welcome", "changelog", "metrics",
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

    if host in WIKIDATA_HOSTS:
        return DetectedSource("wikidata", _wikidata_id(path_parts))

    if host in GITHUB_HOSTS:
        return DetectedSource("github", _github_id(path_parts))

    if host in GIST_HOSTS:
        return DetectedSource("gist", _gist_id(path_parts))

    if host in GITLAB_HOSTS:
        return DetectedSource("gitlab", _gitlab_id(path_parts))

    if host in GITEA_HOSTS:
        return DetectedSource("gitea", _gitea_id(host, path_parts))

    if host in BITBUCKET_HOSTS:
        return DetectedSource("bitbucket", _bitbucket_id(path_parts))

    if host in ARXIV_HOSTS:
        return DetectedSource("arxiv", _arxiv_id(path_parts))

    if host in BIORXIV_HOSTS:
        return DetectedSource("biorxiv", _biorxiv_id(path_parts))

    if host in MEDRXIV_HOSTS:
        return DetectedSource("medrxiv", _biorxiv_id(path_parts))

    if host in X_HOSTS:
        return DetectedSource("x", _x_status_id(path_parts))

    if host in HACKERNEWS_HOSTS:
        return DetectedSource("hackernews", _hackernews_id(path_parts, parsed.query))

    if host in LOBSTERS_HOSTS:
        return DetectedSource("lobsters", _lobsters_id(path_parts))

    if host in BLUESKY_HOSTS:
        return DetectedSource("bluesky", _bluesky_id(path_parts))

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

    if host in GO_HOSTS:
        return DetectedSource("go", _go_id(path_parts))

    if host in DEVTO_HOSTS:
        return DetectedSource("devto", _devto_id(path_parts))

    if host in HUGGINGFACE_HOSTS:
        return DetectedSource("huggingface", _huggingface_id(path_parts))

    if host in OPENLIBRARY_HOSTS:
        return DetectedSource("openlibrary", _openlibrary_id(path_parts))

    if host in DOI_HOSTS:
        return DetectedSource("crossref", _crossref_id(path_parts))

    if host in PUBMED_HOSTS:
        return DetectedSource("pubmed", _pubmed_id(path_parts))

    # The legacy `ncbi.nlm.nih.gov/pubmed/<pmid>` form lives on a host that
    # serves many NCBI databases, so it is shape-matched (returns None → falls
    # through for PMC/Gene/… paths), not host-claimed like the dedicated host.
    ncbi_pmid = _ncbi_pubmed_id(host, path_parts)
    if ncbi_pmid is not None:
        return DetectedSource("pubmed", ncbi_pmid)

    # IETF RFCs live across several hosts that also serve drafts and org pages, so
    # — like the shared NCBI host above — only the `rfc<digits>` shape is claimed
    # and every other path on those hosts falls through to `web` (ADR 0066).
    rfc_id = _rfc_id(host, path_parts)
    if rfc_id is not None:
        return DetectedSource("rfc", rfc_id)

    # Mastodon/Fediverse has no shared host, so it is matched by URL shape on
    # whatever instance the URL names — after every known-host branch above,
    # before the generic pdf/web fallback.
    mastodon_id = _mastodon_id(host, path_parts)
    if mastodon_id is not None:
        return DetectedSource("mastodon", mastodon_id)

    # Misskey-family software is *also* host-less Fediverse, but it does not
    # speak the Mastodon API (it has its own `/api/notes/show`), so it is its
    # own source and adapter rather than a mastodon shape — yet detected the
    # same shape-only way, after mastodon (their literals never collide).
    misskey_id = _misskey_id(host, path_parts)
    if misskey_id is not None:
        return DetectedSource("misskey", misskey_id)

    # Lemmy — the federated link aggregator — is host-less Fediverse too, and
    # like Misskey speaks its own API (`/api/v3/post`, not Mastodon's), so it is
    # its own source/adapter detected by URL shape (ADR 0052). Its `/post/<id>`
    # literal never collides with mastodon's or misskey's shapes.
    lemmy_id = _lemmy_id(host, path_parts)
    if lemmy_id is not None:
        return DetectedSource("lemmy", lemmy_id)

    # Discourse — the forum software behind countless dev communities
    # (discuss.python.org, meta.discourse.org, users.rust-lang.org) — is
    # host-less like the Fediverse sources, recognized by its `/t/<slug>/<id>`
    # topic shape on whatever instance the URL names and fetched from that
    # instance's keyless `.json` view (ADR 0054). Its `/t/` literal never
    # collides with the Fediverse shapes above, so it runs after them.
    discourse_id = _discourse_id(host, path_parts)
    if discourse_id is not None:
        return DetectedSource("discourse", discourse_id)

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


# A Wikidata item id is `Q` followed by digits (`Q42`). Properties (`P<digits>`)
# and Lexemes (`L<digits>`) are deferred — they are schema/meta entities, not the
# "things" a knowledge library saves — so only the Q form is claimed (ADR 0075).
_WIKIDATA_QID = re.compile(r"Q\d+", re.IGNORECASE)


def _wikidata_id(path_parts: list[str]) -> str | None:
    """The `Q<digits>` item id for a Wikidata entity URL, uppercased, else None.

    An entity is reachable several ways on the one host — the web/UI permalink
    (`/wiki/Q42`), the RDF concept URI (`/entity/Q42`), and the canonical entity
    data (`/wiki/Special:EntityData/Q42[.json]`) — so the id is taken from the
    first path segment that *is* a QID (a trailing `.json`/`.ttl` extension
    stripped first), which covers every form without enumerating routes. On
    `wikidata.org` a `/wiki/Q<n>` title is always the entity Q<n> (there are no
    article pages that merely look like a QID), so this is safe.

    The QID is uppercased to its canonical form — Wikidata routes
    case-insensitively but displays uppercase, so `/wiki/q42` and `/wiki/Q42`
    dedupe (the crates/Open Library fold, ADR 0036/0073). A Property
    (`/wiki/Property:P31`), a Lexeme (`/wiki/Lexeme:L1`), and the project/portal
    pages (`/wiki/Wikidata:Main_Page`, the home page) carry no Q item and resolve
    to the source with no fetchable item — github's profile-page pattern.
    """
    for segment in path_parts:
        stem = unquote(segment).split(".", 1)[0]
        if _WIKIDATA_QID.fullmatch(stem):
            return stem.upper()
    return None


def _github_id(path_parts: list[str]) -> str | None:
    if len(path_parts) < 2 or path_parts[0] in GITHUB_RESERVED:
        return None
    return f"{path_parts[0]}/{path_parts[1]}"


# A gist id is a hexadecimal hash — modern gists use 32 hex chars, older ones
# can be shorter or all-digits. Folded lowercase to canonical (hex is
# case-insensitive in the API), like the crates/Open Library id fold.
_GIST_ID = re.compile(r"[0-9a-f]+", re.IGNORECASE)


def _gist_id(path_parts: list[str]) -> str | None:
    """The gist id for a gist.github.com URL, lowercased, else None.

    The owner login that may precede the id is decorative: the API is keyed by
    the gist id alone (`GET /gists/<id>`), which resolves the owner itself, so
    identity drops the login and `/<owner>/<id>`, a bare `/<id>`, and a
    `/<owner>/<id>/<revision-sha>` URL all dedupe to one item (the slug-dropped
    Discourse pattern, ADR 0054).

    A bare `gist.github.com/<owner>` is a user's gist-list page and the reserved
    site routes (`/discover`, `/starred`, …) carry no gist, so both resolve to
    the source with no fetchable item — github's profile-page pattern.
    """
    if not path_parts or path_parts[0] in GIST_RESERVED:
        return None
    # `/<owner>/<gist_id>[/<revision>…]` — the owner disambiguates, so any hex
    # id is safe to claim from the second segment.
    if len(path_parts) >= 2 and _GIST_ID.fullmatch(path_parts[1]):
        return path_parts[1].lower()
    # `/<gist_id>` — a bare/anonymous gist with no owner segment. A hex-looking
    # username would be ambiguous with that owner's gist-list page, so claim it
    # only at the full modern-id length; a shorter bare legacy id is left to the
    # owner-qualified form (a rare, documented miss).
    only = path_parts[0]
    if len(only) >= 20 and _GIST_ID.fullmatch(only):
        return only.lower()
    return None


def _gitlab_id(path_parts: list[str]) -> str | None:
    """The `group[/subgroup…]/project` path for a gitlab.com project URL, else None.

    GitLab supports nested groups, so a project lives at a multi-segment path
    (`group/project`, `group/subgroup/project`), not GitHub's flat
    `owner/repo`. Every sub-resource hangs off a reserved `/-/` separator
    (`/-/issues`, `/-/blob/...`, `/-/tree/...`), so everything before the `-`
    segment is the project path and a deep-linked URL still dedupes to its
    project. The API takes that whole path URL-encoded, so the adapter keeps
    it joined rather than splitting on `/` (the github rule can't apply).

    From the URL alone a path like `group/subgroup` is ambiguous — a project
    in `group`, or a subgroup — exactly the Go-module ambiguity (ADR 0042);
    detection mints the path as a candidate and the fetch resolves it (a
    non-project 404s, a benign failed fetch). A single segment is a group or
    user page, and the reserved top-level routes (`explore`, `help`, …) carry
    no project, so both resolve to the source with no fetchable item.

    The path is folded lowercase: GitLab forces lowercase path slugs and routes
    case-insensitively, so `/Group/Project` and `/group/project` dedupe to one
    item (the crates/Packagist case-fold, ADR 0036/0039) — unlike github's
    case-preserving `owner/repo`. Segments are *not* percent-decoded (unlike
    the registry parsers, whose package names legitimately appear encoded —
    npm's `@scope%2Fname`): a GitLab slug is constrained to ASCII
    `[a-z0-9._-]` and is never percent-encoded in practice, the github rule;
    the fetch adapter re-encodes the whole path for the API, so a stray
    encoded segment would simply 404 rather than mis-resolve.
    """
    if "-" in path_parts:
        path_parts = path_parts[: path_parts.index("-")]
    if len(path_parts) < 2 or path_parts[0].lower() in GITLAB_RESERVED:
        return None
    return "/".join(p.lower() for p in path_parts) or None


def _gitea_id(host: str, path_parts: list[str]) -> str | None:
    """`<host>/<owner>/<repo>` for a Gitea/Forgejo repo URL, else None.

    Gitea/Forgejo repos use github's flat `<owner>/<repo>` shape, so the first
    two segments are the repo and a deep link (`/issues/1`, `/src/branch/...`)
    dedupes to it. Unlike github, the host rides in the identity: the Gitea API
    lives on each instance's own host (`codeberg.org/api/v1`, `gitea.com/api/v1`),
    so the adapter needs the host to fetch — the Fediverse identity shape
    (`<host>/<id>`, ADR 0049). The host is folded to its canonical form
    (`www.` stripped) so `www.gitea.com` and `gitea.com` dedupe; owner/repo are
    kept verbatim like github (Gitea routes case-insensitively but preserves
    display case, and the API resolves either).

    A bare profile/org page (one segment) and the reserved site routes
    (`explore`, `issues`, `user`, …) carry no repo and resolve to the source
    with no fetchable item — github's pattern. Detection is host-scoped to the
    two big public instances; self-hosted Gitea has no universal shape tell, so
    it is deferred exactly as self-hosted GitLab is (ADR 0055/0056).
    """
    canonical_host = host[4:] if host.startswith("www.") else host
    if len(path_parts) < 2 or path_parts[0].lower() in GITEA_RESERVED:
        return None
    return f"{canonical_host}/{path_parts[0]}/{path_parts[1]}"


def _bitbucket_id(path_parts: list[str]) -> str | None:
    """`<workspace>/<repo>` for a Bitbucket Cloud repo URL, else None.

    Bitbucket repos use github's flat `<workspace>/<repo>` shape, so the first
    two segments are the repo and a deep link (`/src/...`, `/pull-requests/1`,
    `/issues`) dedupes to it. Unlike gitea, the host does *not* ride in the
    identity: Bitbucket Cloud is a single hosted service (`api.bitbucket.org`),
    so one fixed API host serves every repo (the github/gitlab rule).

    The path is folded lowercase: Bitbucket auto-lowercases repo slugs, mints
    lowercase workspace ids, and routes case-insensitively (the live API
    resolves a mixed-case request), so `/Workspace/Repo` and `/workspace/repo`
    dedupe to one item — the gitlab/crates case-fold (ADR 0055/0036), not
    github's verbatim `owner/repo`. A bare workspace page (one segment) and the
    reserved site routes (`account`, `dashboard`, `snippets`, …) carry no repo
    and resolve to the source with no fetchable item — github's pattern.
    """
    if len(path_parts) < 2 or path_parts[0].lower() in BITBUCKET_RESERVED:
        return None
    return f"{path_parts[0].lower()}/{path_parts[1].lower()}"


def _arxiv_id(path_parts: list[str]) -> str | None:
    if len(path_parts) < 2 or path_parts[0] not in ("abs", "pdf"):
        return None
    arxiv_id = "/".join(path_parts[1:])
    if arxiv_id.lower().endswith(".pdf"):
        arxiv_id = arxiv_id[: -len(".pdf")]
    return arxiv_id or None


# A bioRxiv/medRxiv accession is either the modern dotted form
# `YYYY.MM.DD.<serial>` (bioRxiv's serial is 6 digits, medRxiv's 8) or a legacy
# bare integer (`339747`); a `vN` version suffix and any format extension
# (`.full`, `.full.pdf`, `.abstract`) follow it.
_BIORXIV_ACCESSION = re.compile(r"\d{4}\.\d{2}\.\d{2}\.\d+|\d{4,}")


def _biorxiv_id(path_parts: list[str]) -> str | None:
    """The `10.1101/<accession>` DOI for a bioRxiv/medRxiv content URL, else None.

    A preprint lives at `/content/10.1101/<accession>v<version>[.<ext>]` (the
    modern canonical form) or the legacy early-access path
    `/content/early/<YYYY>/<MM>/<DD>/<accession>v<version>`. Either way the
    identity is the DOI `10.1101/<accession>` — the version suffix and any
    `.full`/`.full.pdf`/`.abstract` extension are dropped so every version and
    view of one preprint dedupes to a single item, the arXiv `abs`/`pdf` rule
    (ADR 0008). The accession is found as the segment after a literal `10.1101`
    path part, or the last segment of an early-access path.

    The DOI is the lookup key the shared fetch adapter passes to
    `api.biorxiv.org/details/<server>/<doi>` (ADR 0068). A non-content page
    (the homepage, a subject collection, an about page) carries no accession and
    resolves to the source with no fetchable item — github's profile-page
    pattern.
    """
    if not path_parts or path_parts[0] != "content":
        return None
    rest = path_parts[1:]
    if "10.1101" in rest:
        index = rest.index("10.1101")
        raw = rest[index + 1] if index + 1 < len(rest) else ""
    else:
        raw = rest[-1] if rest else ""
    match = _BIORXIV_ACCESSION.match(unquote(raw))
    return f"10.1101/{match.group()}" if match else None


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


def _go_id(path_parts: list[str]) -> str | None:
    """The module path for a `pkg.go.dev/<module>[@version][/<pkg>]` URL, else None.

    A pkg.go.dev URL is `<module-path>[@<version>][/<package-in-module>]`.
    When a version is present the module path is unambiguously everything
    before the `@` (pkg.go.dev attaches the version to the module, then any
    in-module package follows it), so a versioned sub-package URL still
    dedupes to its module. Without a version the whole path is taken as the
    module candidate — an unversioned sub-package URL (`.../gin/binding`)
    can't be told from a module and resolves to the source with no
    fetchable item if the proxy 404s it.

    A real module path's first segment is a domain (it contains a `.`), so
    the standard library (`net/http`, `fmt`) and site routes (`about`,
    `search`) — first segment with no dot — carry no fetchable module. The
    path is kept verbatim: module paths are case-sensitive, and the proxy
    case-encodes the request at fetch time, not the identity.
    """
    if not path_parts:
        return None
    module = unquote("/".join(path_parts)).split("@", 1)[0].strip("/")
    segments = [s for s in module.split("/") if s]
    if len(segments) < 2 or "." not in segments[0]:
        return None
    return "/".join(segments)


def _devto_id(path_parts: list[str]) -> str | None:
    """`<user>/<slug>` for a dev.to article URL, folded lowercase, else None.

    A dev.to article lives at `/<author-or-org>/<slug>` — github's flat
    two-segment shape — so the first two segments are the identity and a
    deeper link (`/comments`, a series page) dedupes to the article by
    taking only those two. The fetch adapter hits
    `/api/articles/<user>/<slug>` with exactly this pair (the URL's handle,
    which is the *author or organization* the post is published under, not
    the byline author of an org post).

    The id is folded lowercase: Forem mints lowercase handles and lowercase
    article slugs, the canonical URL uses the lowercase form, and the API
    is case-sensitive — only the lowercase form resolves (a mixed-case
    request 404s) — so folding both dedupes a mixed-case paste and aims at
    the one form that works (the gitlab/bitbucket/crates fold, ADR
    0055/0057/0036), unlike github's case-preserving `owner/repo`.

    A bare profile page (one segment) and the reserved site routes (`t` tag
    pages, `settings`, `dashboard`, …) carry no article and resolve to the
    source with no fetchable item — github's pattern. A misrouted two-
    segment URL degrades to a benign failed fetch (the API 404s), never a
    wrong scroll.
    """
    if len(path_parts) < 2 or path_parts[0].lower() in DEVTO_RESERVED:
        return None
    return f"{path_parts[0].lower()}/{path_parts[1].lower()}"


def _huggingface_id(path_parts: list[str]) -> str | None:
    """`<kind>:<repo_id>` for a model, dataset, or Space repo URL, else None.

    The fetch adapter serves the `/api/models`, `/api/datasets`, and
    `/api/spaces` endpoints, so the repo *kind* rides in the source id the
    way the Stack Exchange site does: a model is `model:<org>/<name>`, a
    dataset is `dataset:<org>/<name>` (or a legacy single-segment
    `dataset:<name>`), a Space is `space:<org>/<name>` (ADR 0043).

    A model repo is exactly `<org>/<name>` — the github rule — so a
    repo subpage (`/tree/main`, `/blob/...`, `/discussions`) dedupes to
    the repo by taking only the first two path segments, and a bare
    `<org>` (a profile, ambiguous with legacy un-namespaced models) is
    not fetchable. Site routes (`docs`, `blog`, `models`, …) carry no
    repo. Repo ids are case-sensitive, so they are kept verbatim (the
    npm/github rule), not folded like a PyPI name.
    """
    if not path_parts:
        return None
    head = path_parts[0]
    if head == "datasets":
        return _hf_repo("dataset", path_parts[1:])
    if head == "spaces":
        return _hf_repo("space", path_parts[1:])
    if head in HUGGINGFACE_RESERVED:  # `datasets`/`spaces` handled above
        return None
    if len(path_parts) >= 2:
        return f"model:{path_parts[0]}/{path_parts[1]}"
    return None


def _hf_repo(kind: str, rest: list[str]) -> str | None:
    """`<kind>:<org>/<name>`, or `<kind>:<name>` for a legacy single name."""
    if not rest:
        return None
    name = f"{rest[0]}/{rest[1]}" if len(rest) >= 2 else rest[0]
    name = name.strip()
    return f"{kind}:{name}" if name else None


# An Open Library identifier (OLID) is `OL<digits><type-letter>`: a work ends in
# `W`, an edition in `M` (author records end in `A`, not a book). The letter
# carries the *kind*, so the fetch adapter routes on it without a separate
# prefix — the huggingface `kind:id` economy without the prefix.
_OLID_WORK = re.compile(r"OL\d+W", re.IGNORECASE)
_OLID_EDITION = re.compile(r"OL\d+M", re.IGNORECASE)
# An ISBN-13 is 13 digits; an ISBN-10 is 9 digits plus a check char that may be
# `X`. Hyphens/spaces are stripped before matching (a pasted ISBN may carry them).
_ISBN = re.compile(r"\d{13}|\d{9}[\dX]", re.IGNORECASE)


def _openlibrary_id(path_parts: list[str]) -> str | None:
    """The identity for an Open Library work, edition, or ISBN URL, else None.

    Open Library models books in the FRBR sense the rest of Scrolls uses for
    `works` (ADR 0069): a *work* (`/works/OL…W`) is the abstract book, an
    *edition* (`/books/OL…M`) a specific manifestation, and an ISBN
    (`/isbn/<isbn>`) names an edition. All three are common save targets, so all
    three are claimed; the kind rides in the source id the way Hugging Face's
    does (ADR 0043) — but the OLID's own type letter (`W`/`M`) already encodes
    work-vs-edition, so only the ISBN form needs an explicit `isbn:` prefix.

    The OLID is uppercased to a canonical form (Open Library routes
    case-insensitively but displays uppercase), so a mixed-case paste dedupes —
    the crates/gitlab fold (ADR 0036/0055). A trailing title slug or `/editions`
    subpage dedupes to the OLID by taking only the id segment. The ISBN is
    stripped of hyphens/spaces and uppercased (the check char may be `X`).

    Author pages (`/authors/OL…A`), subject/search/list routes, and the home
    page carry no book and resolve to the source with no fetchable item —
    github's profile-page pattern.
    """
    if len(path_parts) < 2:
        return None
    head, ident = path_parts[0], path_parts[1]
    if head == "works" and _OLID_WORK.fullmatch(ident):
        return ident.upper()
    if head == "books" and _OLID_EDITION.fullmatch(ident):
        return ident.upper()
    if head == "isbn":
        isbn = unquote(ident).replace("-", "").replace(" ", "").upper()
        return f"isbn:{isbn}" if _ISBN.fullmatch(isbn) else None
    return None


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


def _pubmed_id(path_parts: list[str]) -> str | None:
    """The PMID for a `pubmed.ncbi.nlm.nih.gov/<pmid>` URL, else None.

    PubMed permalinks are `pubmed.ncbi.nlm.nih.gov/<pmid>/`, where the PMID is
    the integer accession the efetch API takes. A record subpage
    (`/<pmid>/citedby/`) dedupes to the record by taking only the first segment.
    The PMID is digits-only, so the search, advanced-query, and home pages
    (a non-numeric or empty first segment) carry no record and resolve to the
    source with no fetchable item — github's profile-page pattern.
    """
    if path_parts and path_parts[0].isdigit():
        return path_parts[0]
    return None


def _ncbi_pubmed_id(host: str, path_parts: list[str]) -> str | None:
    """The PMID for a legacy `ncbi.nlm.nih.gov/pubmed/<pmid>` URL, else None.

    Before PubMed moved to its own host, records lived at
    `www.ncbi.nlm.nih.gov/pubmed/<pmid>` (NCBI now redirects this to the
    dedicated host). That host still serves many other NCBI databases — PMC
    (`/pmc/...`), Gene, Nucleotide — so, unlike the dedicated host, it is not
    claimed wholesale: only the `/pubmed/<digits>` shape matches, and every
    other NCBI path falls through to `web`. The PMID is taken verbatim, so a
    legacy and a modern link to the same record dedupe to one `pubmed:<pmid>`.
    """
    if (
        host in NCBI_HOSTS
        and len(path_parts) >= 2
        and path_parts[0] == "pubmed"
        and path_parts[1].isdigit()
    ):
        return path_parts[1]
    return None


# An RFC path segment is `rfc<number>`, optionally zero-padded (`rfc0020`) and
# optionally carrying a format extension (`rfc9110.txt`/`.html`/`.json`).
_RFC_SEGMENT = re.compile(r"rfc0*(\d+)", re.IGNORECASE)


def _rfc_id(host: str, path_parts: list[str]) -> str | None:
    """The integer RFC number for an `rfc<N>` URL on a known IETF host, else None.

    RFCs are reachable at several shapes across the RFC Editor and IETF hosts —
    `rfc-editor.org/rfc/rfc9110[.txt]`, `rfc-editor.org/info/rfc9110`,
    `datatracker.ietf.org/doc/rfc9110/`, `datatracker.ietf.org/doc/html/rfc9110`,
    the legacy `tools.ietf.org/html/rfc9110`, `ietf.org/rfc/rfc9110.txt` — all of
    which carry an `rfc<digits>` path segment. The number is taken from the first
    such segment with leading zeros stripped, so `rfc0020` and `rfc20` dedupe to
    `rfc:20`.

    Because these hosts also serve Internet-Drafts (`draft-…`), working-group
    pages, and the org site, only the `rfc<digits>` shape is claimed: a URL with
    no such segment returns None and falls through to `web` — the shared-NCBI-host
    posture (ADR 0065), not a wholesale host claim. A `/doc/draft-ietf-quic-…`
    draft therefore stays a `web` page even on `datatracker.ietf.org`.
    """
    if host not in RFC_HOSTS:
        return None
    for segment in path_parts:
        stem = unquote(segment).split(".", 1)[0]
        match = _RFC_SEGMENT.fullmatch(stem)
        if match:
            return str(int(match.group(1)))
    return None


def _hackernews_id(path_parts: list[str], query: str) -> str | None:
    # /item?id=<numeric>; front page, /user, /newest etc. carry no item id
    if path_parts == ["item"]:
        item_id = _first_query_value(query, "id")
        if item_id and item_id.isdigit():
            return item_id
    return None


def _lobsters_id(path_parts: list[str]) -> str | None:
    """The story short id for a `/s/<short_id>[/<slug>]` URL, else None.

    A Lobsters story URL is `/s/<short_id>` optionally followed by a title
    slug; the short id (a base-36 handle like `vg5hdf`) is the identity,
    kept verbatim. Comment permalinks (`/c/<id>`), tag pages (`/t/<tag>`),
    user pages (`/u/<user>`), and the front page carry no story id and
    resolve to the source with no fetchable item — Hacker News's and Stack
    Exchange's pattern (ADR 0031, ADR 0033).
    """
    if len(path_parts) >= 2 and path_parts[0] == "s":
        return path_parts[1] or None
    return None


def _bluesky_id(path_parts: list[str]) -> str | None:
    """`<actor>/<rkey>` for a `bsky.app/profile/<actor>/post/<rkey>` URL, else None.

    A Bluesky post URL is `/profile/<actor>/post/<rkey>`, where `<actor>` is
    either a handle (`bsky.app`) or a DID (`did:plc:…`) and `<rkey>` is the
    post's record key. The actor is folded lowercase: handles are DNS names
    and DIDs are lowercase by construction, both case-insensitive, so
    `Bsky.App` and `bsky.app` dedupe to one item — while the record key is
    kept verbatim. The stable identity is really the post's AT-URI
    (`at://<did>/…`), but the DID can only be learned at fetch time, so the
    actor the URL carries is used as registered, like the handle in any
    other source's URL.

    A profile page (`/profile/<actor>`), feeds, lists, and the home/search
    routes carry no post and resolve to the source with no fetchable item —
    Hacker News's and Lobsters' pattern (ADR 0031, ADR 0046).
    """
    if (
        len(path_parts) >= 4
        and path_parts[0] == "profile"
        and path_parts[2] == "post"
    ):
        actor = unquote(path_parts[1]).strip().lower()
        rkey = unquote(path_parts[3]).strip()
        if actor and rkey:
            return f"{actor}/{rkey}"
    return None


# A Fediverse status id is a snowflake integer (Mastodon), a ULID
# (GoToSocial), or a base62 FlakeId (Pleroma/Akkoma) — every form is a run of
# base62 with no separators, so this already excludes a hyphenated slug.
_FEDIVERSE_ID = re.compile(r"[A-Za-z0-9]+")
# The bare `/notice/<id>` shape (Pleroma/Akkoma) is anchored only by the weak
# `notice` literal on a host we don't otherwise know, so its id carries a
# length floor a real FlakeId clears (~18 chars) but a word path does not.
_NOTICE_ID = re.compile(r"[A-Za-z0-9]{16,}")


def _mastodon_id(host: str, path_parts: list[str]) -> str | None:
    """`<host>/<status_id>` for a Fediverse status URL on any instance, else None.

    The Fediverse is federated across thousands of independent instances with
    no shared host, so unlike every other adapter a status is recognized by
    its URL *shape* on whatever host the saved URL carries — this branch runs
    only after every known-platform host has already been ruled out. The
    source name stays `mastodon`, but the shapes cover the whole
    Mastodon-API-compatible family — Mastodon (and Hometown/glitch-soc),
    GoToSocial, and Pleroma/Akkoma — because all of them serve the same
    keyless `/api/v1/statuses/<id>` endpoint the adapter fetches (ADR 0050).
    Four canonical forms are matched:

        /@<user>/<status_id>                  — Mastodon web/UI permalink
        /@<user>/statuses/<status_id>         — GoToSocial web permalink
        /users/<user>/statuses/<status_id>    — the ActivityPub object URL
        /notice/<status_id>                   — Pleroma/Akkoma web permalink

    Safety is host-agnostic, so the id constraint is what keeps the heuristic
    from stealing lookalike paths. The Mastodon `/@<user>/<id>` form keeps the
    strict all-digits rule (Mastodon mints snowflake integers), so a Medium
    `/@user/<slug>` (non-numeric) stays a web page. The two `statuses`-bearing
    forms are anchored by that distinctive literal — no mainstream platform
    uses `/@user/statuses/<id>` or `/users/<user>/statuses/<id>` — so their id
    may be any base62 run (a ULID or FlakeId, both non-numeric). The bare
    `/notice/<id>` form has only the weak `notice` literal, so its id carries
    a length floor (16+ base62 chars) that a real FlakeId clears while a
    `/notice/privacy` or `/notice/cookie-policy` does not. A Pleroma AP
    *Object* URL (`/objects/<uuid>`) is deliberately *not* matched — its uuid
    is not a `/api/v1/statuses` id — and any residual misdetection degrades to
    a failed fetch (the adapter's API call 404s), never a wrong scroll: the
    conservative, reversible tradeoff a federated network with no host list
    forces (ADR 0049).

    Identity carries the instance host because a status id is unique only
    within its instance, and every form collapses to the same
    `<host>/<status_id>` so a status saved any way dedupes. The host is
    lowercased (DNS is case-insensitive); the non-numeric ids are kept
    verbatim (ULIDs are uppercase, FlakeIds case-sensitive), and the `<user>`
    segment is not part of identity. Profiles, timelines, tag pages, and
    API/media routes carry no status id and resolve to the source with no
    fetchable item — Bluesky's and Lobsters' pattern (ADR 0048, ADR 0046).
    """
    status_id = _fediverse_status_id(path_parts)
    return f"{host}/{status_id}" if status_id else None


def _fediverse_status_id(path_parts: list[str]) -> str | None:
    """The status id from a Mastodon/GoToSocial/Pleroma status URL shape, else None."""
    n = len(path_parts)
    # Mastodon web permalink: /@<user>/<digits>. The id stays strict digits so
    # a Medium /@author/<slug> stays a web page.
    if n == 2 and path_parts[0].startswith("@") and path_parts[1].isdigit():
        return path_parts[1]
    # GoToSocial web permalink: /@<user>/statuses/<ULID>. The `statuses`
    # literal is the guard, so the id may be any base62 run.
    if n == 3 and path_parts[0].startswith("@") and path_parts[1] == "statuses":
        return path_parts[2] if _fullmatch(_FEDIVERSE_ID, path_parts[2]) else None
    # ActivityPub object URL: /users/<user>/statuses/<id> (Mastodon,
    # GoToSocial, Pleroma alike). The two literals anchor it.
    if n == 4 and path_parts[0] == "users" and path_parts[2] == "statuses":
        return path_parts[3] if _fullmatch(_FEDIVERSE_ID, path_parts[3]) else None
    # Pleroma/Akkoma web permalink: /notice/<FlakeId>. Only the weak `notice`
    # literal anchors it, so the id needs the length floor.
    if n == 2 and path_parts[0] == "notice":
        return path_parts[1] if _fullmatch(_NOTICE_ID, path_parts[1]) else None
    return None


# A Misskey note id is one of four configurable formats — `aid` (10 base36
# chars, the shortest and the eldest default), `aidx` (16), `objectid` (24
# hex), or `ulid` (26 Crockford base32) — each a separator-free base62 run.
# Like Pleroma's bare `/notice/`, the `/notes/` literal is weak (many sites
# use it), so the id carries a charset + length floor; the floor is 10, the
# `aid` length, the lowest that still admits the eldest default rather than
# the 16 a `/notice/` FlakeId clears.
_MISSKEY_ID = re.compile(r"[A-Za-z0-9]{10,}")


def _misskey_id(host: str, path_parts: list[str]) -> str | None:
    """`<host>/<note_id>` for a Misskey-family `/notes/<id>` URL, else None.

    Misskey and its forks (Sharkey, Firefish/Calckey, Foundkey) are Fediverse
    software that does *not* implement the Mastodon API — a saved note is
    fetched from `/api/notes/show`, not `/api/v1/statuses/<id>` — so they get
    their own `misskey` source and adapter, unlike GoToSocial and Pleroma,
    which ride mastodon's because they are Mastodon-API-compatible (ADR 0050).
    Detection is still shape-only, because the Misskey ecosystem is as host-less
    as the rest of the Fediverse: the whole family shares the `/notes/<id>` web
    and ActivityPub permalink.

    The `notes` literal is a weak anchor (plenty of non-Fediverse sites have a
    `/notes/<slug>` path), so the id constraint carries the weight, exactly as
    Pleroma's `/notice/` form does: a base62 run (no `-`/`.`/`_`, which a slug
    would have) at least 10 chars long (the shortest Misskey id format, `aid`).
    A `/notes/getting-started` or `/notes/welcome` falls through to `web`. The
    residual risk — a non-Misskey `/notes/<10+ base62 chars>` URL the user
    wanted as `web` — degrades to a benign failed fetch (the API call 404s),
    never a wrong scroll: the conservative, reversible tradeoff a host-less
    network forces, the same one ADR 0049 accepts for mastodon.

    Identity carries the instance host (a note id is unique only within its
    instance) and the host is lowercased; the id is kept verbatim (`aidx`/
    `objectid`/`ulid` are case-sensitive). Profiles, timelines, and other
    routes carry no note id and resolve to the source with no fetchable item.
    """
    if len(path_parts) == 2 and path_parts[0] == "notes":
        note_id = path_parts[1]
        if _fullmatch(_MISSKEY_ID, note_id):
            return f"{host}/{note_id}"
    return None


def _lemmy_id(host: str, path_parts: list[str]) -> str | None:
    """`<host>/<post_id>` for a Lemmy `/post/<digits>` URL, else None.

    Lemmy (and the Lemmy-API link aggregators) is host-less Fediverse software
    like Misskey, fetched from its own `/api/v3/post` rather than the Mastodon
    API (ADR 0052), so — like every Fediverse source — a post is recognized by
    its URL *shape* on whatever instance the saved URL names; this branch runs
    only after every known-platform host and the other Fediverse shapes have
    been ruled out.

    The canonical post permalink is `/post/<id>`, where `<id>` is Lemmy's
    autoincrement integer post id. The `post` literal is weak (countless sites
    have a `/post/...` path), so — exactly as Pleroma's `/notice/` and Misskey's
    `/notes/` forms make their id carry the weight (ADR 0050, ADR 0051) — the
    constraint is strict: an *all-digits* id and exactly two path segments, so a
    blog's `/post/<slug>` (non-numeric) or `/post/<id>/<extra>` stays a web page.
    The residual risk — a non-Lemmy `/post/<digits>` URL the user wanted as
    `web` — degrades to a benign failed fetch (the API call 404s), never a wrong
    scroll: the conservative, reversible tradeoff a host-less network forces
    (ADR 0049).

    Identity carries the instance host (a post id is unique only within its
    instance) and the host is lowercased; the numeric id is kept as written.
    Comment permalinks (`/comment/<id>`), community (`/c/<name>`), and user
    (`/u/<name>`) pages carry no post id and resolve to the source with no
    fetchable item — Hacker News's and Lobsters' pattern (ADR 0031, ADR 0046).
    """
    if len(path_parts) == 2 and path_parts[0] == "post" and path_parts[1].isdigit():
        return f"{host}/{path_parts[1]}"
    return None


def _discourse_id(host: str, path_parts: list[str]) -> str | None:
    """`<host>/<topic_id>` for a Discourse `/t/<slug>/<id>` topic URL, else None.

    Discourse powers thousands of independent forums with no shared host, so —
    like the Fediverse sources (ADR 0049–0052) — a topic is recognized by its
    URL *shape* on whatever instance the saved URL names; this branch runs only
    after every known-platform host and the Fediverse shapes have been ruled out.

    The canonical topic permalink is `/t/<slug>/<topic_id>`, optionally followed
    by a `/<post_number>` jump target — so the topic id is the third path
    segment, an autoincrement integer, and any trailing post number is not part
    of identity. The `t` literal is weak (countless sites use a `/t/...` path),
    so — the Pleroma/Misskey/Lemmy rule that a weak literal makes the id carry
    the weight (ADR 0050–0052) — the constraint is strict: a `slug` segment
    between `t` and an *all-digits* topic id, so a two-segment `/t/<tag>` tag
    page or a `/t/<slug>/<non-numeric>` stays a web page. The residual risk — a
    non-Discourse `/t/<slug>/<digits>` URL the user wanted as `web` — degrades
    to a benign failed fetch (the `.json` view 404s or lacks `post_stream`),
    never a wrong scroll: the conservative, reversible tradeoff a host-less
    shape forces (ADR 0049).

    Identity carries the instance host (a topic id is unique only within its
    instance) lowercased; the slug is *not* part of identity — Discourse treats
    it as display-only and redirects a wrong slug to the canonical one, and the
    adapter fetches the slug-free `/t/<id>.json` route. Category
    (`/c/<slug>/<id>`), user (`/u/<name>`), and tag (`/tag/<name>`) pages carry
    no topic id and resolve to the source with no fetchable item.
    """
    if len(path_parts) >= 3 and path_parts[0] == "t" and path_parts[2].isdigit():
        return f"{host}/{path_parts[2]}"
    return None


def _first_query_value(query: str, key: str) -> str | None:
    values = parse_qs(query).get(key)
    return values[0] if values else None
