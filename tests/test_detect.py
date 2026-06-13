"""Contract tests for URL source detection (IDEAS.md §5: `scrolls add <url>`).

Known simplifications, pinned deliberately for the first slice:
- GitHub sub-resources (issues, PRs) collapse to `owner/repo`; richer IDs
  are a future adapter concern.
- gist.github.com falls back to `web` until a gist adapter exists.
- Playlist IDs share the `youtube` namespace with video IDs.
"""

import pytest

from scrolls.sources.detect import DetectedSource, detect_source

CASES = [
    # --- youtube ---
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube", "dQw4w9WgXcQ"),
    ("https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "youtube", "dQw4w9WgXcQ"),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "youtube", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "youtube", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?t=42", "youtube", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/abc123DEF45", "youtube", "abc123DEF45"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "youtube", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/live/jfKfPfyJRdk", "youtube", "jfKfPfyJRdk"),
    ("https://www.youtube.com/playlist?list=PLAXtNZ16wQ", "youtube", "PLAXtNZ16wQ"),
    # youtube URL that is not a single item: source known, id unknown
    ("https://www.youtube.com/@somechannel", "youtube", None),
    # --- wikipedia ---
    ("https://en.wikipedia.org/wiki/SQLite", "wikipedia", "en:SQLite"),
    ("https://en.wikipedia.org/wiki/Okapi_BM25#Ranking", "wikipedia", "en:Okapi_BM25"),
    ("https://en.m.wikipedia.org/wiki/SQLite", "wikipedia", "en:SQLite"),
    ("https://de.wikipedia.org/wiki/Volltextsuche", "wikipedia", "de:Volltextsuche"),
    # percent-encoded titles decode to the canonical page name
    ("https://en.wikipedia.org/wiki/Kurt_G%C3%B6del", "wikipedia", "en:Kurt_Gödel"),
    # portal/front pages: source known, id unknown
    ("https://www.wikipedia.org/", "wikipedia", None),
    # --- github ---
    ("https://github.com/oojBuffalo/scrolls", "github", "oojBuffalo/scrolls"),
    ("https://github.com/owner/repo/issues/42", "github", "owner/repo"),
    ("https://github.com/owner/repo/blob/main/README.md", "github", "owner/repo"),
    ("https://www.github.com/owner/repo", "github", "owner/repo"),
    # profile and reserved pages: source known, id unknown
    ("https://github.com/oojBuffalo", "github", None),
    ("https://github.com/orgs/anthropics/repositories", "github", None),
    ("https://github.com/trending", "github", None),
    # gist is not the github repo adapter (pinned simplification)
    ("https://gist.github.com/user/abcdef123456", "web", None),
    # --- arxiv ---
    ("https://arxiv.org/abs/2406.01234", "arxiv", "2406.01234"),
    ("https://arxiv.org/abs/2406.01234v2", "arxiv", "2406.01234v2"),
    ("https://arxiv.org/pdf/2406.01234", "arxiv", "2406.01234"),
    ("https://arxiv.org/pdf/2406.01234v2.pdf", "arxiv", "2406.01234v2"),
    ("https://www.arxiv.org/abs/cs/9901002", "arxiv", "cs/9901002"),
    # --- x / twitter ---
    ("https://x.com/karpathy/status/1234567890123", "x", "1234567890123"),
    ("https://twitter.com/karpathy/status/1234567890123?s=20", "x", "1234567890123"),
    ("https://mobile.twitter.com/karpathy/status/99", "x", "99"),
    # profile pages: source known, id unknown
    ("https://x.com/karpathy", "x", None),
    # --- hacker news ---
    ("https://news.ycombinator.com/item?id=8863", "hackernews", "8863"),
    ("https://news.ycombinator.com/item?id=121003&p=2", "hackernews", "121003"),
    ("https://www.news.ycombinator.com/item?id=1", "hackernews", "1"),
    # front page, profiles, listings: source known, item id unknown
    ("https://news.ycombinator.com/", "hackernews", None),
    ("https://news.ycombinator.com/newest", "hackernews", None),
    ("https://news.ycombinator.com/user?id=pg", "hackernews", None),
    # --- lobsters ---
    ("https://lobste.rs/s/vg5hdf", "lobsters", "vg5hdf"),
    # a trailing title slug is decoration: identity is the short id only
    ("https://lobste.rs/s/vg5hdf/designing_lispy_dsls_part_1_scss", "lobsters", "vg5hdf"),
    ("https://www.lobste.rs/s/vg5hdf", "lobsters", "vg5hdf"),
    # comment permalink, tag, user, and front pages: source known, story unknown
    ("https://lobste.rs/c/abcdef", "lobsters", None),
    ("https://lobste.rs/t/programming", "lobsters", None),
    ("https://lobste.rs/u/someone", "lobsters", None),
    ("https://lobste.rs/", "lobsters", None),
    # --- bluesky ---
    ("https://bsky.app/profile/alice.bsky.social/post/3kqpost1",
     "bluesky", "alice.bsky.social/3kqpost1"),
    # the handle is case-folded (DNS/DID are case-insensitive), the rkey kept verbatim
    ("https://bsky.app/profile/Alice.BSKY.Social/post/3kqAbC",
     "bluesky", "alice.bsky.social/3kqAbC"),
    # a DID actor instead of a handle
    ("https://bsky.app/profile/did:plc:abc123/post/3kqpost1",
     "bluesky", "did:plc:abc123/3kqpost1"),
    ("https://www.bsky.app/profile/alice.bsky.social/post/3kqpost1",
     "bluesky", "alice.bsky.social/3kqpost1"),
    # profile, feed, list, and home routes carry no post id
    ("https://bsky.app/profile/alice.bsky.social", "bluesky", None),
    ("https://bsky.app/profile/alice.bsky.social/feed/whats-hot", "bluesky", None),
    ("https://bsky.app/profile/alice.bsky.social/lists/3kqlist", "bluesky", None),
    ("https://bsky.app/", "bluesky", None),
    ("https://bsky.app/search", "bluesky", None),
    # --- mastodon / fediverse (no shared host: matched by URL shape) ---
    ("https://mastodon.social/@Gargron/109252172978473811",
     "mastodon", "mastodon.social/109252172978473811"),
    # the ActivityPub object URL collapses to the same host/<id> identity
    ("https://mastodon.social/users/Gargron/statuses/109252172978473811",
     "mastodon", "mastodon.social/109252172978473811"),
    # any instance host, with a trailing slash tolerated
    ("https://hachyderm.io/@user/110000000000000001/", "mastodon",
     "hachyderm.io/110000000000000001"),
    ("https://infosec.exchange/@someone/111111111111111111", "mastodon",
     "infosec.exchange/111111111111111111"),
    # the host is lowercased (DNS is case-insensitive)
    ("https://Mastodon.Social/@user/109252172978473811", "mastodon",
     "mastodon.social/109252172978473811"),
    # a non-numeric last segment is NOT a status: Medium's /@user/<slug>
    # stays a web page, not a misdetected mastodon post
    ("https://medium.com/@author/why-rust-is-great-a1b2c3d4", "web", None),
    # a three-segment /@user/<kind>/<id> (Threads, TikTok) is not the shape
    ("https://www.threads.net/@user/post/abc123", "web", None),
    # profile, timeline, and tag pages carry no status id -> plain web
    ("https://mastodon.social/@Gargron", "web", None),
    ("https://mastodon.social/public", "web", None),
    ("https://mastodon.social/tags/introductions", "web", None),
    # --- stack exchange network ---
    ("https://stackoverflow.com/questions/11227809/why-is-it-faster",
     "stackexchange", "stackoverflow:11227809"),
    # /q/<id> shortlink, with a fragment that detection ignores
    ("https://stackoverflow.com/q/11227809#11227902", "stackexchange", "stackoverflow:11227809"),
    ("https://www.stackoverflow.com/questions/42/x", "stackexchange", "stackoverflow:42"),
    # *.stackexchange.com subdomains are each their own API site
    ("https://math.stackexchange.com/questions/9/foo", "stackexchange", "math:9"),
    ("https://meta.stackexchange.com/questions/7/bar", "stackexchange", "meta:7"),
    ("https://rpg.meta.stackexchange.com/questions/3/baz", "stackexchange", "rpg.meta:3"),
    # dedicated-domain sites, including the slug that literally keeps .net
    ("https://superuser.com/questions/5/y", "stackexchange", "superuser:5"),
    ("https://serverfault.com/questions/6/z", "stackexchange", "serverfault:6"),
    ("https://askubuntu.com/questions/8/w", "stackexchange", "askubuntu:8"),
    ("https://mathoverflow.net/questions/12/q", "stackexchange", "mathoverflow.net:12"),
    # meta of a dedicated domain -> meta.<slug>
    ("https://meta.stackoverflow.com/questions/4/v", "stackexchange", "meta.stackoverflow:4"),
    # tag, user, and listing pages: source known, question id unknown
    ("https://stackoverflow.com/questions/tagged/python", "stackexchange", None),
    ("https://stackoverflow.com/users/87234/gmannickg", "stackexchange", None),
    ("https://stackoverflow.com/", "stackexchange", None),
    # answer permalinks carry an answer id, not a question id (pinned simplification)
    ("https://stackoverflow.com/a/11227902", "stackexchange", None),
    # the bare network portal is not a question host
    ("https://stackexchange.com/", "web", None),
    # --- pypi ---
    ("https://pypi.org/project/requests/", "pypi", "requests"),
    # a versioned page is the same package: identity is the name only
    ("https://pypi.org/project/requests/2.31.0/", "pypi", "requests"),
    ("https://www.pypi.org/project/Flask/", "pypi", "flask"),
    # PEP 503 name normalization: case-folded, [-_.] runs collapse to one -
    ("https://pypi.org/project/zope.interface/", "pypi", "zope-interface"),
    ("https://pypi.org/project/ruamel_yaml/", "pypi", "ruamel-yaml"),
    ("https://pypi.org/project/typing--extensions/", "pypi", "typing-extensions"),
    # search, user, and help pages: source known, package unknown
    ("https://pypi.org/", "pypi", None),
    ("https://pypi.org/search/?q=http", "pypi", None),
    ("https://pypi.org/user/someone/", "pypi", None),
    ("https://pypi.org/help/", "pypi", None),
    # --- npm ---
    ("https://www.npmjs.com/package/express", "npm", "express"),
    # a versioned page is the same package: identity is the name only
    ("https://www.npmjs.com/package/express/v/4.18.2", "npm", "express"),
    ("https://npmjs.com/package/chalk", "npm", "chalk"),
    # scoped packages keep the @scope/name shape
    ("https://www.npmjs.com/package/@babel/core", "npm", "@babel/core"),
    ("https://www.npmjs.com/package/@babel/core/v/7.24.0", "npm", "@babel/core"),
    # the registry is case-sensitive, so the name is preserved verbatim
    ("https://www.npmjs.com/package/JSONStream", "npm", "JSONStream"),
    # search, user, and org pages: source known, package unknown
    ("https://www.npmjs.com/", "npm", None),
    ("https://www.npmjs.com/search?q=http", "npm", None),
    ("https://www.npmjs.com/~someone", "npm", None),
    ("https://www.npmjs.com/package", "npm", None),
    # --- crates.io ---
    ("https://crates.io/crates/serde", "crates", "serde"),
    # a versioned page is the same crate: identity is the name only
    ("https://crates.io/crates/serde_json/1.0.150", "crates", "serde-json"),
    # case-insensitive and -/_ -equivalent, folded like PEP 503
    ("https://crates.io/crates/Serde-Json", "crates", "serde-json"),
    ("https://crates.io/crates/SERDE_JSON", "crates", "serde-json"),
    ("https://www.crates.io/crates/tokio", "crates", "tokio"),
    # crate list, search, user, and category pages: source known, crate unknown
    ("https://crates.io/", "crates", None),
    ("https://crates.io/crates", "crates", None),
    ("https://crates.io/search?q=http", "crates", None),
    ("https://crates.io/users/dtolnay", "crates", None),
    ("https://crates.io/categories/encoding", "crates", None),
    # --- packagist (Composer/PHP) ---
    ("https://packagist.org/packages/monolog/monolog", "packagist", "monolog/monolog"),
    # case-insensitive: the schema is lowercase, mixed case folds to dedupe
    ("https://packagist.org/packages/Monolog/Monolog", "packagist", "monolog/monolog"),
    # a deeper subpage is the same package: identity is vendor/name only
    ("https://packagist.org/packages/monolog/monolog/stats", "packagist",
     "monolog/monolog"),
    # the API URL people paste drops its trailing .json
    ("https://packagist.org/packages/symfony/console.json", "packagist",
     "symfony/console"),
    ("https://www.packagist.org/packages/laravel/framework", "packagist",
     "laravel/framework"),
    # the list, a vendor-only page, and search: source known, package unknown
    ("https://packagist.org/", "packagist", None),
    ("https://packagist.org/packages/", "packagist", None),
    ("https://packagist.org/packages/monolog/", "packagist", None),
    ("https://packagist.org/search/?q=log", "packagist", None),
    # --- rubygems ---
    ("https://rubygems.org/gems/rails", "rubygems", "rails"),
    # a version page is the same gem: identity is the name only
    ("https://rubygems.org/gems/rails/versions/8.1.3", "rubygems", "rails"),
    # gem names are case-sensitive (gems/Ascii85 resolves, ascii85 404s), so
    # the name is preserved verbatim — npm's rule, not PyPI's fold
    ("https://rubygems.org/gems/Ascii85", "rubygems", "Ascii85"),
    ("https://www.rubygems.org/gems/nokogiri", "rubygems", "nokogiri"),
    # the gems list and search pages: source known, gem unknown
    ("https://rubygems.org/", "rubygems", None),
    ("https://rubygems.org/gems", "rubygems", None),
    ("https://rubygems.org/search?query=http", "rubygems", None),
    # --- go modules (pkg.go.dev) ---
    ("https://pkg.go.dev/github.com/gin-gonic/gin", "go", "github.com/gin-gonic/gin"),
    # a version is attached with @; the module path is everything before it
    ("https://pkg.go.dev/github.com/gin-gonic/gin@v1.12.0", "go",
     "github.com/gin-gonic/gin"),
    # a versioned sub-package URL still dedupes to its module (before the @)
    ("https://pkg.go.dev/github.com/gin-gonic/gin@v1.12.0/binding", "go",
     "github.com/gin-gonic/gin"),
    # module paths are case-sensitive — kept verbatim (the proxy escapes the
    # request, not the identity), so a mixed-case module never folds
    ("https://pkg.go.dev/github.com/Masterminds/squirrel", "go",
     "github.com/Masterminds/squirrel"),
    # vanity paths are modules too: a domain first segment, two+ segments
    ("https://pkg.go.dev/golang.org/x/tools", "go", "golang.org/x/tools"),
    ("https://pkg.go.dev/rsc.io/quote", "go", "rsc.io/quote"),
    ("https://www.pkg.go.dev/k8s.io/client-go", "go", "k8s.io/client-go"),
    # standard library (first segment has no dot) and site routes carry no
    # fetchable module: source known, module unknown
    ("https://pkg.go.dev/net/http", "go", None),
    ("https://pkg.go.dev/fmt", "go", None),
    ("https://pkg.go.dev/std", "go", None),
    ("https://pkg.go.dev/about", "go", None),
    ("https://pkg.go.dev/search?q=logging", "go", None),
    ("https://pkg.go.dev/", "go", None),
    # --- crossref (doi.org) ---
    ("https://doi.org/10.1145/2939672.2939754", "crossref", "10.1145/2939672.2939754"),
    # the suffix may itself contain slashes; the whole path is the DOI
    ("https://doi.org/10.1000/182/sub", "crossref", "10.1000/182/sub"),
    # DOIs are case-insensitive: the id is folded lowercase to dedupe
    ("https://doi.org/10.1145/ABC.DEF", "crossref", "10.1145/abc.def"),
    # the legacy dx.doi.org resolver dedupes to the same item
    ("https://dx.doi.org/10.1145/2939672.2939754", "crossref", "10.1145/2939672.2939754"),
    # percent-encoded suffix characters decode
    ("https://doi.org/10.1007/978-3-319-10590-1_53", "crossref",
     "10.1007/978-3-319-10590-1_53"),
    # the bare resolver and non-DOI paths: source known, item unknown
    ("https://doi.org/", "crossref", None),
    ("https://doi.org/about", "crossref", None),
    ("https://doi.org/not-a-doi", "crossref", None),
    # --- huggingface ---
    # a model repo is <org>/<name>; the repo type rides in source_id so one
    # adapter serves both the /api/models and /api/datasets endpoints
    ("https://huggingface.co/google-bert/bert-base-uncased", "huggingface",
     "model:google-bert/bert-base-uncased"),
    # repo subpages (tree/blob/commits/discussions) dedupe to the repo:
    # identity is the first two path segments, like a pypi version page
    ("https://huggingface.co/google-bert/bert-base-uncased/tree/main", "huggingface",
     "model:google-bert/bert-base-uncased"),
    # repo ids are case-sensitive — preserved verbatim (the npm/github rule),
    # so a mixed-case org or name is never folded into a fetch miss
    ("https://huggingface.co/Qwen/Qwen2.5-7B-Instruct", "huggingface",
     "model:Qwen/Qwen2.5-7B-Instruct"),
    # datasets carry the datasets/ prefix; org/name or a legacy single name
    ("https://huggingface.co/datasets/rajpurkar/squad", "huggingface",
     "dataset:rajpurkar/squad"),
    ("https://huggingface.co/datasets/squad", "huggingface", "dataset:squad"),
    # Spaces carry the spaces/ prefix; the kind rides in source_id (ADR 0043)
    ("https://huggingface.co/spaces/HuggingFaceH4/zephyr-chat", "huggingface",
     "space:HuggingFaceH4/zephyr-chat"),
    # a Space subpage (tree/blob) dedupes to the repo, like a model
    ("https://huggingface.co/spaces/HuggingFaceH4/zephyr-chat/tree/main",
     "huggingface", "space:HuggingFaceH4/zephyr-chat"),
    # the short hf.co host resolves to the same repo
    ("https://hf.co/google-bert/bert-base-uncased", "huggingface",
     "model:google-bert/bert-base-uncased"),
    # site pages, listings, docs, blog, and a bare profile:
    # source known, repo unknown (no fetchable item)
    ("https://huggingface.co/", "huggingface", None),
    ("https://huggingface.co/models", "huggingface", None),
    ("https://huggingface.co/datasets", "huggingface", None),
    ("https://huggingface.co/spaces", "huggingface", None),
    ("https://huggingface.co/docs/transformers/index", "huggingface", None),
    ("https://huggingface.co/blog/llama3", "huggingface", None),
    ("https://huggingface.co/google-bert", "huggingface", None),
    # --- pdf (generic, after platform-specific checks) ---
    ("https://example.com/papers/attention.pdf", "pdf", None),
    ("https://example.com/REPORT.PDF", "pdf", None),
    # --- web fallback ---
    ("https://example.com/blog/post", "web", None),
    ("http://example.com", "web", None),
]


@pytest.mark.parametrize("url,source,source_id", CASES)
def test_detect_source(url, source, source_id):
    assert detect_source(url) == DetectedSource(source=source, source_id=source_id)


def test_leading_and_trailing_whitespace_is_tolerated():
    result = detect_source("  https://en.wikipedia.org/wiki/SQLite \n")
    assert result == DetectedSource(source="wikipedia", source_id="en:SQLite")


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not a url",
        "ftp://example.com/file.txt",
        "file:///etc/passwd",
        "//example.com/protocol-relative",
        "javascript:alert(1)",
    ],
)
def test_non_http_input_is_rejected(bad):
    with pytest.raises(ValueError):
        detect_source(bad)
