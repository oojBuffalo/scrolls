"""Contract tests for URL source detection (IDEAS.md §5: `scrolls add <url>`).

Known simplifications, pinned deliberately for the first slice:
- GitHub sub-resources (issues, PRs) collapse to `owner/repo`; richer IDs
  are a future adapter concern.
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
    # --- wikidata (structured-knowledge sibling of wikipedia) ---
    ("https://www.wikidata.org/wiki/Q42", "wikidata", "Q42"),
    # a sitelinks/statements fragment is stripped (it is not part of the path)
    ("https://www.wikidata.org/wiki/Q42#sitelinks-wikipedia", "wikidata", "Q42"),
    # the RDF concept URI form, including the bare http scheme it uses
    ("https://www.wikidata.org/entity/Q42", "wikidata", "Q42"),
    ("http://www.wikidata.org/entity/Q42", "wikidata", "Q42"),
    # the canonical entity-data URL the adapter itself reads
    ("https://www.wikidata.org/wiki/Special:EntityData/Q42.json", "wikidata", "Q42"),
    # routes case-insensitively; the id folds to the uppercase canonical
    ("https://www.wikidata.org/wiki/q42", "wikidata", "Q42"),
    ("https://m.wikidata.org/wiki/Q7251", "wikidata", "Q7251"),
    ("https://wikidata.org/wiki/Q11660", "wikidata", "Q11660"),
    # Properties and Lexemes are deferred (meta/schema entities, not "things")
    ("https://www.wikidata.org/wiki/Property:P31", "wikidata", None),
    ("https://www.wikidata.org/wiki/Lexeme:L1", "wikidata", None),
    # project/portal/home pages carry no Q item: source known, id unknown
    ("https://www.wikidata.org/wiki/Wikidata:Main_Page", "wikidata", None),
    ("https://www.wikidata.org/", "wikidata", None),
    # --- github ---
    ("https://github.com/oojBuffalo/scrolls", "github", "oojBuffalo/scrolls"),
    ("https://github.com/owner/repo/issues/42", "github", "owner/repo"),
    ("https://github.com/owner/repo/blob/main/README.md", "github", "owner/repo"),
    ("https://www.github.com/owner/repo", "github", "owner/repo"),
    # profile and reserved pages: source known, id unknown
    ("https://github.com/oojBuffalo", "github", None),
    ("https://github.com/orgs/anthropics/repositories", "github", None),
    ("https://github.com/trending", "github", None),
    # --- gist (its own source/host, ADR 0078) ---
    # `/<owner>/<gist_id>` — the owner is decorative, identity is the id alone
    ("https://gist.github.com/oojBuffalo/0123456789abcdef0123456789abcdef",
     "gist", "0123456789abcdef0123456789abcdef"),
    # a bare/anonymous `/<gist_id>` (full-length hex) dedupes to the same id
    ("https://gist.github.com/0123456789abcdef0123456789abcdef",
     "gist", "0123456789abcdef0123456789abcdef"),
    # a revision sha after the id dedupes to the gist (deep-link rule)
    ("https://gist.github.com/oojBuffalo/0123456789abcdef0123456789abcdef/a1b2c3d4",
     "gist", "0123456789abcdef0123456789abcdef"),
    # routes case-insensitively; the hex id folds to its lowercase canonical
    ("https://gist.github.com/User/0123456789ABCDEF0123456789ABCDEF",
     "gist", "0123456789abcdef0123456789abcdef"),
    # a user's gist-list page (one short segment) carries no fetchable gist
    ("https://gist.github.com/octocat", "gist", None),
    # site routes and the gist home carry no gist
    ("https://gist.github.com/discover", "gist", None),
    ("https://gist.github.com/", "gist", None),
    # --- gitlab ---
    ("https://gitlab.com/inkscape/inkscape", "gitlab", "inkscape/inkscape"),
    # nested groups: the whole path before any /-/ is the project
    ("https://gitlab.com/group/subgroup/project", "gitlab", "group/subgroup/project"),
    # sub-resources hang off the reserved /-/ separator and dedupe to the project
    ("https://gitlab.com/gitlab-org/gitlab/-/issues/1", "gitlab", "gitlab-org/gitlab"),
    ("https://gitlab.com/gitlab-org/gitlab/-/blob/master/README.md", "gitlab",
     "gitlab-org/gitlab"),
    ("https://www.gitlab.com/gitlab-org/gitlab", "gitlab", "gitlab-org/gitlab"),
    # paths fold lowercase (GitLab forces lowercase slugs, routes case-insensitively)
    ("https://gitlab.com/Group/Project", "gitlab", "group/project"),
    # group/user pages and reserved routes: source known, id unknown
    ("https://gitlab.com/gitlab-org", "gitlab", None),
    ("https://gitlab.com/explore", "gitlab", None),
    ("https://gitlab.com/explore/projects/trending", "gitlab", None),
    ("https://gitlab.com/-/snippets/2716", "gitlab", None),
    # --- gitea / forgejo (host-scoped; the instance host rides in the id) ---
    ("https://codeberg.org/forgejo/forgejo", "gitea", "codeberg.org/forgejo/forgejo"),
    ("https://gitea.com/gitea/tea", "gitea", "gitea.com/gitea/tea"),
    # www. folds to the canonical host so it dedupes
    ("https://www.codeberg.org/forgejo/forgejo", "gitea", "codeberg.org/forgejo/forgejo"),
    # deep links dedupe to the repo (github's flat owner/repo shape)
    ("https://codeberg.org/forgejo/forgejo/issues/123", "gitea",
     "codeberg.org/forgejo/forgejo"),
    ("https://codeberg.org/forgejo/forgejo/src/branch/forgejo/README.md", "gitea",
     "codeberg.org/forgejo/forgejo"),
    # owner/repo kept verbatim like github (Gitea preserves display case)
    ("https://codeberg.org/Codeberg/Community", "gitea", "codeberg.org/Codeberg/Community"),
    # profile, reserved routes, and the bare host carry no fetchable repo
    ("https://codeberg.org/forgejo", "gitea", None),
    ("https://codeberg.org/explore/repos", "gitea", None),
    ("https://gitea.com/issues", "gitea", None),
    ("https://codeberg.org/", "gitea", None),
    # --- bitbucket (host-scoped, single API host like github; flat workspace/repo) ---
    ("https://bitbucket.org/atlassian/python-bitbucket", "bitbucket",
     "atlassian/python-bitbucket"),
    ("https://www.bitbucket.org/atlassian/python-bitbucket", "bitbucket",
     "atlassian/python-bitbucket"),
    # deep links dedupe to the repo (github's flat shape)
    ("https://bitbucket.org/atlassian/python-bitbucket/src/master/", "bitbucket",
     "atlassian/python-bitbucket"),
    ("https://bitbucket.org/atlassian/python-bitbucket/pull-requests/1", "bitbucket",
     "atlassian/python-bitbucket"),
    # folded lowercase (Bitbucket auto-lowercases slugs, routes case-insensitively)
    ("https://bitbucket.org/Atlassian/Python-Bitbucket", "bitbucket",
     "atlassian/python-bitbucket"),
    # workspace page, reserved routes, and the bare host carry no fetchable repo
    ("https://bitbucket.org/atlassian", "bitbucket", None),
    ("https://bitbucket.org/dashboard/overview", "bitbucket", None),
    ("https://bitbucket.org/product", "bitbucket", None),
    ("https://bitbucket.org/", "bitbucket", None),
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
    # --- fediverse forks on the same Mastodon API (ADR 0050) ---
    # GoToSocial web permalink: /@<user>/statuses/<ULID>. The literal
    # `statuses` segment is the guard, so the non-numeric ULID is accepted
    # and kept verbatim (ULIDs are uppercase Crockford base32).
    ("https://gts.example/@user/statuses/01HQ3W8M4PXP5VZ9R7K2N6T0YB",
     "mastodon", "gts.example/01HQ3W8M4PXP5VZ9R7K2N6T0YB"),
    # its ActivityPub object URL collapses to the same host/<id> identity
    ("https://gts.example/users/user/statuses/01HQ3W8M4PXP5VZ9R7K2N6T0YB",
     "mastodon", "gts.example/01HQ3W8M4PXP5VZ9R7K2N6T0YB"),
    # Pleroma/Akkoma web permalink: /notice/<FlakeId> (a base62 run)
    ("https://pleroma.example/notice/A1mZ9pQr7sT4uV2wXy",
     "mastodon", "pleroma.example/A1mZ9pQr7sT4uV2wXy"),
    # its ActivityPub object URL (a non-numeric id on the AP form) dedupes too
    ("https://pleroma.example/users/nick/statuses/A1mZ9pQr7sT4uV2wXy",
     "mastodon", "pleroma.example/A1mZ9pQr7sT4uV2wXy"),
    # host lowercased, trailing slash tolerated, the id's case preserved
    ("https://GTS.Example/@user/statuses/01HQ3W8M4PXP5VZ9R7K2N6T0YB/",
     "mastodon", "gts.example/01HQ3W8M4PXP5VZ9R7K2N6T0YB"),
    # a Pleroma AP *Object* URL (/objects/<uuid>) is NOT a /api/v1/statuses
    # id, so it is left to the web adapter rather than misrouted to mastodon
    ("https://pleroma.example/objects/abc12345-6789-def0-1234-56789abcdef0",
     "web", None),
    # the /notice/<id> length floor (16) keeps short word paths out: a
    # /notice/privacy or hyphenated /notice/cookie-policy stays a web page
    ("https://blog.example/notice/privacy", "web", None),
    ("https://blog.example/notice/cookie-policy", "web", None),
    # /@<user>/statuses/<id> with an empty id is not a status either
    ("https://gts.example/@user/statuses/", "web", None),
    # boundary: the /notice/ floor is 16 base62 chars — exactly 16 matches,
    # 15 falls through to web (pins the length claim against silent drift)
    ("https://pleroma.example/notice/Ab3Cd4Ef5Gh6Jk7M",
     "mastodon", "pleroma.example/Ab3Cd4Ef5Gh6Jk7M"),
    ("https://blog.example/notice/Ab3Cd4Ef5Gh6Jk7", "web", None),
    # the statuses-bearing forms admit any base62 id, but a non-base62 id (a
    # hyphen or a dot) is not a status — the charset guard, on both forms
    ("https://gts.example/@user/statuses/not-a-valid-id", "web", None),
    ("https://gts.example/users/user/statuses/has.dots", "web", None),
    # --- misskey-family (its own API, not Mastodon's — ADR 0051) ---
    # Misskey web/AP permalink: /notes/<id>. The shared shape across Misskey,
    # Sharkey, Firefish/Calckey, and Foundkey; identity carries the host.
    ("https://misskey.io/notes/9bf2dbi3p4", "misskey", "misskey.io/9bf2dbi3p4"),
    # any instance host, with a trailing slash tolerated
    ("https://example.social/notes/9g8h7f6e5d4c3b2a/", "misskey",
     "example.social/9g8h7f6e5d4c3b2a"),
    # the host is lowercased (DNS), the id kept verbatim (aidx/ulid are
    # case-sensitive); a 26-char Crockford-base32 ULID id is accepted
    ("https://Misskey.IO/notes/01HQ3W8M4PXP5VZ9R7K2N6", "misskey",
     "misskey.io/01HQ3W8M4PXP5VZ9R7K2N6"),
    # a /notes/<slug> with a separator (hyphen) is a note-taking page, not a
    # Misskey note — the charset guard keeps it a web page
    ("https://blog.example/notes/getting-started", "web", None),
    # boundary: the /notes/ floor is 10 base62 chars (the `aid` length) —
    # exactly 10 matches, 9 falls through to web (pins the floor against drift)
    ("https://misskey.example/notes/Ab3Cd4Ef5G", "misskey",
     "misskey.example/Ab3Cd4Ef5G"),
    ("https://blog.example/notes/Ab3Cd4Ef5", "web", None),
    # a short dictionary-word /notes/<word> is below the floor -> web
    ("https://blog.example/notes/welcome", "web", None),
    # profile, timeline, and deeper note routes carry no fetchable note id
    ("https://misskey.io/@alice", "web", None),
    ("https://misskey.io/notes/9bf2dbi3p4/reactions", "web", None),
    # --- lemmy (federated link aggregator: its own API, not Mastodon's — ADR 0052) ---
    # /post/<digits> on any instance; identity carries the host, id verbatim
    ("https://lemmy.world/post/27855171", "lemmy", "lemmy.world/27855171"),
    ("https://programming.dev/post/12345", "lemmy", "programming.dev/12345"),
    # the host is lowercased (DNS); a fragment/query is ignored by path parsing
    ("https://Lemmy.World/post/27855171", "lemmy", "lemmy.world/27855171"),
    ("https://lemmy.ml/post/42?scrollToComments=true", "lemmy", "lemmy.ml/42"),
    # the all-digits guard keeps a blog's /post/<slug> a web page (the weak
    # `post` literal can't carry the match on its own — ADR 0052)
    ("https://blog.example/post/why-rust-2-0-wont-happen", "web", None),
    # exactly two segments: /post/<id>/<extra> is not the canonical permalink
    ("https://blog.example/post/12345/comments", "web", None),
    # comment, community, and user routes carry no fetchable post id
    ("https://lemmy.world/comment/98765", "web", None),
    ("https://lemmy.world/c/rust", "web", None),
    ("https://lemmy.world/u/ferris", "web", None),
    # PieFed shares Lemmy's exact /post/<digits> shape (autoincrement int ids),
    # so it is detected as `lemmy` too — the backend (Lemmy vs PieFed) is resolved
    # at fetch time by the threadiverse dispatcher, not at detection (ADR 0053).
    ("https://piefed.social/post/1600132", "lemmy", "piefed.social/1600132"),
    ("https://piefed.world/post/956553", "lemmy", "piefed.world/956553"),
    # --- discourse forums (host-less, fetched from the keyless .json view — ADR 0054) ---
    # /t/<slug>/<topic_id> on any instance; identity carries the host + the
    # all-digits topic id, the display-only slug dropped
    ("https://discuss.python.org/t/welcome-to-discourse/8", "discourse",
     "discuss.python.org/8"),
    ("https://meta.discourse.org/t/how-to-do-x/12345", "discourse",
     "meta.discourse.org/12345"),
    # a trailing /<post_number> jump target dedupes to the same topic
    ("https://discuss.python.org/t/welcome-to-discourse/8/3", "discourse",
     "discuss.python.org/8"),
    # the host is lowercased (DNS); a query is ignored by path parsing
    ("https://Discuss.Python.org/t/welcome-to-discourse/8", "discourse",
     "discuss.python.org/8"),
    ("https://users.rust-lang.org/t/help-with-lifetimes/4242?page=2", "discourse",
     "users.rust-lang.org/4242"),
    # the all-digits guard keeps a /t/<slug>/<non-numeric> a web page (the weak
    # `t` literal can't carry the match on its own — the Lemmy rule, ADR 0052)
    ("https://blog.example/t/some-thread/not-a-number", "web", None),
    # a two-segment /t/<tag> tag page carries no topic id -> plain web
    ("https://blog.example/t/python", "web", None),
    # category and user routes don't match the /t/<slug>/<digits> shape
    ("https://discuss.python.org/c/users-help/7", "web", None),
    ("https://discuss.python.org/u/guido", "web", None),
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
    # --- dev.to (Forem) ---
    # an article is <user>/<slug>; the id is folded lowercase (Forem mints
    # lowercase handles/slugs and the case-sensitive API only resolves them)
    ("https://dev.to/ben/the-dev-to-story-2c8j", "devto", "ben/the-dev-to-story-2c8j"),
    ("https://www.dev.to/ben/the-dev-to-story-2c8j", "devto", "ben/the-dev-to-story-2c8j"),
    # the URL handle is the author *or organization* the post is published under
    ("https://dev.to/devteam/what-was-your-win-this-week-4k11", "devto",
     "devteam/what-was-your-win-this-week-4k11"),
    # a mixed-case paste folds to the one form the API resolves
    ("https://dev.to/Ben/The-Story-2c8j", "devto", "ben/the-story-2c8j"),
    # a deeper link (the comments anchor) dedupes to the article (first two segments)
    ("https://dev.to/ben/the-dev-to-story-2c8j/comments", "devto",
     "ben/the-dev-to-story-2c8j"),
    # tag pages, profiles, and reserved site routes carry no article:
    # source known, item unknown
    ("https://dev.to/t/python", "devto", None),
    ("https://dev.to/ben", "devto", None),
    ("https://dev.to/settings/profile", "devto", None),
    ("https://dev.to/dashboard", "devto", None),
    ("https://dev.to/", "devto", None),
    # --- openlibrary (books) ---
    # a work (the abstract book) — the OLID's W is the kind, no extra prefix
    ("https://openlibrary.org/works/OL45804W", "openlibrary", "OL45804W"),
    ("https://openlibrary.org/works/OL45804W/Fantastic_Mr_Fox", "openlibrary",
     "OL45804W"),
    # the editions subpage dedupes to the work
    ("https://openlibrary.org/works/OL45804W/editions", "openlibrary", "OL45804W"),
    ("https://www.openlibrary.org/works/OL45804W", "openlibrary", "OL45804W"),
    # an edition (a specific manifestation) — the OLID's M is the kind
    ("https://openlibrary.org/books/OL27112900M/Fluent_Python", "openlibrary",
     "OL27112900M"),
    # a mixed-case paste folds to the canonical uppercase OLID
    ("https://openlibrary.org/works/ol45804w", "openlibrary", "OL45804W"),
    # an ISBN names an edition; the kind is prefixed since it is not an OLID
    ("https://openlibrary.org/isbn/9781491946008", "openlibrary",
     "isbn:9781491946008"),
    # hyphens are stripped; an ISBN-10's X check char uppercases
    ("https://openlibrary.org/isbn/0-13-110362-8", "openlibrary", "isbn:0131103628"),
    ("https://openlibrary.org/isbn/097522980x", "openlibrary", "isbn:097522980X"),
    # author pages, subjects, search, and the home page carry no book:
    # source known, item unknown
    ("https://openlibrary.org/authors/OL34184A", "openlibrary", None),
    ("https://openlibrary.org/subjects/python", "openlibrary", None),
    ("https://openlibrary.org/search?q=python", "openlibrary", None),
    ("https://openlibrary.org/isbn/not-an-isbn", "openlibrary", None),
    ("https://openlibrary.org/", "openlibrary", None),
    # --- zenodo (open-science records) ---
    # the modern records URL; the numeric record id is the identity
    ("https://zenodo.org/records/7834392", "zenodo", "7834392"),
    # a deep link (files, preview) dedupes to the record
    ("https://zenodo.org/records/7834392/files/data.zip", "zenodo", "7834392"),
    ("https://zenodo.org/records/7834392/preview/readme.txt", "zenodo", "7834392"),
    # the legacy singular `record` form dedupes to the same item
    ("https://zenodo.org/record/7834392", "zenodo", "7834392"),
    # the API URL people sometimes paste resolves to the record too
    ("https://zenodo.org/api/records/7834392", "zenodo", "7834392"),
    ("https://www.zenodo.org/records/7834392", "zenodo", "7834392"),
    # communities, search, deposit, and badge routes carry no record:
    # source known, item unknown
    ("https://zenodo.org/communities/covid-19", "zenodo", None),
    ("https://zenodo.org/search?q=covid", "zenodo", None),
    ("https://zenodo.org/records/", "zenodo", None),
    ("https://zenodo.org/records/not-a-number", "zenodo", None),
    ("https://zenodo.org/", "zenodo", None),
    # the sandbox test instance is deliberately not Zenodo here (throwaway records)
    ("https://sandbox.zenodo.org/records/12345", "web", None),
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
    # --- biorxiv / medrxiv (sibling preprint servers, two sources, one adapter) ---
    # the modern content URL carries the DOI accession; version + view drop off
    ("https://www.biorxiv.org/content/10.1101/2020.03.20.001008v2", "biorxiv",
     "10.1101/2020.03.20.001008"),
    ("https://www.biorxiv.org/content/10.1101/2020.03.20.001008v2.full", "biorxiv",
     "10.1101/2020.03.20.001008"),
    ("https://www.biorxiv.org/content/10.1101/2020.03.20.001008v2.full.pdf", "biorxiv",
     "10.1101/2020.03.20.001008"),
    # a legacy bare-integer accession
    ("https://biorxiv.org/content/10.1101/339747v4", "biorxiv", "10.1101/339747"),
    # the legacy early-access path: the accession is the last segment
    ("https://www.biorxiv.org/content/early/2020/03/21/2020.03.20.001008v1", "biorxiv",
     "10.1101/2020.03.20.001008"),
    # medRxiv is its own source (a medRxiv paper does not live on bioRxiv)
    ("https://www.medrxiv.org/content/10.1101/2020.03.09.20033357v1", "medrxiv",
     "10.1101/2020.03.09.20033357"),
    ("https://medrxiv.org/content/10.1101/2020.03.09.20033357v1.full", "medrxiv",
     "10.1101/2020.03.09.20033357"),
    # non-content pages carry no accession: source known, item unknown
    ("https://www.biorxiv.org/", "biorxiv", None),
    ("https://www.biorxiv.org/collection/microbiology", "biorxiv", None),
    ("https://www.medrxiv.org/about", "medrxiv", None),
    # --- pubmed ---
    # the dedicated host carries the PMID as the first path segment
    ("https://pubmed.ncbi.nlm.nih.gov/22745249/", "pubmed", "22745249"),
    ("https://pubmed.ncbi.nlm.nih.gov/22745249", "pubmed", "22745249"),
    ("https://www.pubmed.ncbi.nlm.nih.gov/34265844/", "pubmed", "34265844"),
    # a record subpage dedupes to the PMID (the first segment)
    ("https://pubmed.ncbi.nlm.nih.gov/22745249/citedby/", "pubmed", "22745249"),
    # search/advanced/home pages carry no record: source known, item unknown
    ("https://pubmed.ncbi.nlm.nih.gov/", "pubmed", None),
    ("https://pubmed.ncbi.nlm.nih.gov/advanced/", "pubmed", None),
    ("https://pubmed.ncbi.nlm.nih.gov/?term=crispr", "pubmed", None),
    # the legacy ncbi.nlm.nih.gov/pubmed/<pmid> form is shape-matched
    ("https://www.ncbi.nlm.nih.gov/pubmed/22745249", "pubmed", "22745249"),
    ("https://www.ncbi.nlm.nih.gov/pubmed/22745249/", "pubmed", "22745249"),
    # other NCBI databases on the shared host fall through to web (not claimed)
    ("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6286148/", "web", None),
    ("https://www.ncbi.nlm.nih.gov/gene/672", "web", None),
    ("https://www.ncbi.nlm.nih.gov/pubmed/", "web", None),
    # --- rfc (IETF, host-restricted shape match like the legacy NCBI host) ---
    # the RFC Editor canonical form, with and without a format extension
    ("https://www.rfc-editor.org/rfc/rfc9110", "rfc", "9110"),
    ("https://www.rfc-editor.org/rfc/rfc9110.txt", "rfc", "9110"),
    ("https://www.rfc-editor.org/rfc/rfc9110.html", "rfc", "9110"),
    ("https://www.rfc-editor.org/info/rfc9110", "rfc", "9110"),
    # zero-padded low numbers dedupe to the bare integer (rfc0020 == rfc20)
    ("https://www.rfc-editor.org/rfc/rfc0020", "rfc", "20"),
    ("https://www.rfc-editor.org/rfc/rfc20", "rfc", "20"),
    # the IETF datatracker and the legacy tools/ietf hosts and their shapes
    ("https://datatracker.ietf.org/doc/rfc9110/", "rfc", "9110"),
    ("https://datatracker.ietf.org/doc/html/rfc9110", "rfc", "9110"),
    ("https://tools.ietf.org/html/rfc2616", "rfc", "2616"),
    ("https://www.ietf.org/rfc/rfc2616.txt", "rfc", "2616"),
    # drafts and org/working-group pages on these hosts are NOT RFCs → web
    ("https://datatracker.ietf.org/doc/draft-ietf-quic-http/", "web", None),
    ("https://datatracker.ietf.org/wg/httpbis/about/", "web", None),
    ("https://www.rfc-editor.org/search/rfc_search.php", "web", None),
    ("https://www.ietf.org/about/", "web", None),
    # the rfc<N> shape on an unknown host is not claimed (host-restricted)
    ("https://example.com/rfc/rfc9110", "web", None),
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
