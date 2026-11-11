"""Tests for the shared HTTP transport's conditional GET (ADR 0019) and
JSON POST (ADR 0051).

Both are urllib glue — `get_conditional` sends If-None-Match/If-Modified-Since
and catches the 304 urllib surfaces as HTTPError; `post_json` sends a
JSON-encoded body with the right headers and parses the reply — so these tests
run against a real localhost HTTP server instead of faking the transport.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from scrolls.sources.http import ConditionalText, get_conditional, post_json

ETAG = '"feed-v1"'
LAST_MODIFIED = "Thu, 11 Jun 2026 09:00:00 GMT"
BODY = b"<rss version=\"2.0\"><channel><title>T</title></channel></rss>"


class _ConditionalHandler(BaseHTTPRequestHandler):
    """Serves /feed.xml with validators; honors If-None-Match and
    If-Modified-Since with an empty 304."""

    def do_GET(self):
        if (
            self.headers.get("If-None-Match") == ETAG
            or self.headers.get("If-Modified-Since") == LAST_MODIFIED
        ):
            self.send_response(304)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("ETag", ETAG)
        self.send_header("Last-Modified", LAST_MODIFIED)
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *args):  # keep pytest output clean
        pass


@pytest.fixture
def feed_url():
    server = HTTPServer(("127.0.0.1", 0), _ConditionalHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/feed.xml"
    server.shutdown()
    thread.join()
    server.server_close()


def test_get_conditional_without_validators_returns_text_and_validators(feed_url):
    response = get_conditional(feed_url)
    assert response == ConditionalText(
        text=BODY.decode("utf-8"), etag=ETAG, last_modified=LAST_MODIFIED
    )
    assert response.not_modified is False


def test_get_conditional_with_matching_etag_reports_not_modified(feed_url):
    response = get_conditional(feed_url, etag=ETAG)
    assert response.not_modified is True
    assert response.text is None


def test_get_conditional_with_matching_last_modified_reports_not_modified(feed_url):
    response = get_conditional(feed_url, last_modified=LAST_MODIFIED)
    assert response.not_modified is True


def test_get_conditional_with_stale_etag_returns_fresh_text(feed_url):
    response = get_conditional(feed_url, etag='"stale"')
    assert response.not_modified is False
    assert response.text == BODY.decode("utf-8")
    assert response.etag == ETAG  # the new validator replaces the stale one


class _EchoHandler(BaseHTTPRequestHandler):
    """Echoes a POST's parsed JSON body plus the Content-Type it arrived with."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length)) if length else None
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {
                    "echo": payload,
                    "content_type": self.headers.get("Content-Type"),
                    "user_agent": self.headers.get("User-Agent"),
                }
            ).encode("utf-8")
        )

    def log_message(self, *args):  # keep pytest output clean
        pass


@pytest.fixture
def echo_url():
    server = HTTPServer(("127.0.0.1", 0), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/api/notes/show"
    server.shutdown()
    thread.join()
    server.server_close()


def test_post_json_sends_the_body_as_json_and_parses_the_reply(echo_url):
    result = post_json(echo_url, {"noteId": "9bf2dbi3p4"})
    assert result["echo"] == {"noteId": "9bf2dbi3p4"}
    assert result["content_type"] == "application/json"
    assert result["user_agent"].startswith("scrolls/")


class _GzipHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        import gzip

        body = BODY if self.path == "/feed" else json.dumps({"text": "alpha " * 100}).encode()
        payload = gzip.compress(body)
        if self.path == "/truncated":
            payload = payload[:-4]
        elif self.path == "/corrupt":
            payload = payload[:10] + b"\xff" + payload[11:]
        self.send_response(200)
        if self.path != "/raw-file":
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("ETag", ETAG)
        self.end_headers()
        self.wfile.write(payload)

    do_POST = do_GET

    def log_message(self, *args):
        pass


@pytest.fixture
def gzip_url():
    server = HTTPServer(("127.0.0.1", 0), _GzipHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join()
    server.server_close()


def test_gzip_text_and_json_are_decoded(gzip_url):
    from scrolls.sources.http import get_text, get_json

    assert get_text(gzip_url + "/feed") == BODY.decode()
    assert get_json(gzip_url + "/json") == {"text": "alpha " * 100}


def test_gzip_conditional_and_post_are_decoded(gzip_url):
    assert get_conditional(gzip_url + "/feed").text == BODY.decode()
    assert post_json(gzip_url + "/json", {}) == {"text": "alpha " * 100}


def test_gzip_limits_apply_to_decoded_body(gzip_url):
    from scrolls.sources.http import get_bytes, get_bytes_within

    with pytest.raises(ValueError, match="exceeds"):
        get_bytes(gzip_url + "/json", max_bytes=100)
    payload, size = get_bytes_within(gzip_url + "/json", max_bytes=100)
    assert payload is None
    assert size is None
    payload, size = get_bytes_within(gzip_url + "/json", max_bytes=1000)
    assert json.loads(payload) == {"text": "alpha " * 100}
    assert size == len(payload)


def test_gzip_file_without_content_encoding_stays_compressed(gzip_url):
    import gzip
    from scrolls.sources.http import get_bytes

    payload = get_bytes(gzip_url + "/raw-file")
    assert payload.startswith(b"\x1f\x8b")
    assert json.loads(gzip.decompress(payload)) == {"text": "alpha " * 100}


@pytest.mark.parametrize("path", ["/truncated", "/corrupt"])
def test_invalid_gzip_is_a_transport_error(gzip_url, path):
    from scrolls.sources.http import get_bytes, get_bytes_within, get_text, get_json

    for read in (get_bytes, get_bytes_within, get_text, get_json, get_conditional,
                 lambda url: post_json(url, {})):
        with pytest.raises(OSError):
            read(gzip_url + path)
