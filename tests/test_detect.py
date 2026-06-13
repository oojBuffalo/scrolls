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
