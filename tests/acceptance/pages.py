"""Local test pages for the acceptance tests. Nothing here touches the internet.

The `site` fixture runs one HTTP server on 127.0.0.1. Zen reaches it as an
HTTP proxy (see `Site.prefs`), so page URLs keep their plain form, for
example `http://docs.test/a`, with no port and no DNS lookup. Requests for
any other host get a 404 and HTTPS tunnels are refused, so a test can never
reach the network by accident.

`http://meet.test/share` stands in for a meeting site. Its body is one
full-viewport button; a click on it calls
`navigator.mediaDevices.getDisplayMedia({video: true})` and sets the title to
`"shared"` on success or `"share failed <error name>"`. Its first title is
`"meet.test share"`. `http://meet.test/camera` does the same with
`getUserMedia({video: true})`, and `screen-and-mic` and
`screen-and-audio-capture` with the legacy `getUserMedia` screen request plus
a microphone or audio capture (`CAPTURE_PAGES`). The test profiles list `meet.test` in
`dom.securecontext.allowlist`, so these plain-HTTP pages are secure contexts.
"""

from __future__ import annotations

import html
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

HOSTS: tuple[str, ...] = (
    "meet.test",
    "docs.test",
    "wiki.test",
    "mail.test",
    "shop.test",
    "news.test",
)

# The page keeps the stream in `window.stream`, so it is not collected.
_CAPTURE_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>meet.test {name}</title>
<style>html, body {{ margin: 0; height: 100%; }}
button {{ position: fixed; inset: 0; width: 100vw; height: 100vh; }}</style>
</head><body><button id="go">{label}</button>
<script>
document.getElementById("go").addEventListener("click", async () => {{
  try {{
    window.stream = await navigator.mediaDevices.{call}({constraints});
    document.title = "shared";
  }} catch (e) {{
    document.title = "share failed " + e.name;
  }}
}});
</script></body></html>
"""

# Page name -> (call, constraints).
CAPTURE_PAGES: dict[str, tuple[str, str]] = {
    "share": ("getDisplayMedia", "{ video: true }"),
    "camera": ("getUserMedia", "{ video: true }"),
    # The legacy screen request with a microphone (P34).
    "screen-and-mic": (
        "getUserMedia",
        '{ video: { mediaSource: "screen" }, audio: true }',
    ),
    # The legacy screen request with audio capture (P34).
    "screen-and-audio-capture": (
        "getUserMedia",
        '{ video: { mediaSource: "screen" }, audio: { mediaSource: "audioCapture" } }',
    ),
}


def _capture_page(name: str) -> bytes:
    call, constraints = CAPTURE_PAGES[name]
    return _CAPTURE_PAGE.format(
        name=name, label=html.escape(call), call=call, constraints=constraints
    ).encode()


class _Handler(BaseHTTPRequestHandler):
    server_version = "zen-share-picker-test/1"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._serve(with_body=True)

    def do_HEAD(self) -> None:
        self._serve(with_body=False)

    def do_CONNECT(self) -> None:
        self._send(405, b"HTTPS is not served by the test proxy\n", "text/plain")

    def _serve(self, *, with_body: bool) -> None:
        # Through the proxy the request line carries the absolute URL.
        parts = urlsplit(self.path)
        host = (parts.hostname or self.headers.get("Host", "")).split(":")[0]
        name = parts.path.lstrip("/")
        served = self.server.files.get((host, name))
        if served is not None:
            body, ctype = served
            self._send(200, body, ctype, with_body=with_body)
            return
        if host not in self.server.hosts or not name or name == "favicon.ico":
            self._send(404, b"not found\n", "text/plain", with_body=with_body)
            return
        if host == "meet.test" and name in CAPTURE_PAGES:
            body = _capture_page(name)
        else:
            title = html.escape(f"{host} {name}")
            body = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                f"<title>{title}</title></head>"
                f"<body><h1>{title}</h1></body></html>"
            ).encode()
        self._send(200, body, "text/html; charset=utf-8", with_body=with_body)

    def _send(
        self, code: int, body: bytes, ctype: str, *, with_body: bool = True
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if with_body:
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, hosts: tuple[str, ...]) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.hosts = frozenset(hosts)
        # (host, path) -> (body, content type), set through Site.serve.
        self.files: dict[tuple[str, str], tuple[bytes, str]] = {}


@dataclass(frozen=True)
class Site:
    """Serves `http://<host>/<name>` for every host in `hosts`.

    Every page is a small HTML document titled `"<host> <name>"`, except the
    capture pages on `meet.test` (see the module docstring). `serve` adds a
    file at any other URL.
    """

    hosts: tuple[str, ...]
    port: int
    files: dict[tuple[str, str], tuple[bytes, str]] = field(
        default_factory=dict, compare=False, repr=False
    )

    def serve(self, url: str, body: bytes, ctype: str) -> None:
        """Serve `body` at the plain-HTTP `url` (any host) until `unserve`."""
        parts = urlsplit(url)
        if parts.scheme != "http" or not parts.hostname:
            raise ValueError(f"only http URLs can be served: {url}")
        self.files[(parts.hostname, parts.path.lstrip("/"))] = (body, ctype)

    def unserve(self, url: str) -> None:
        parts = urlsplit(url)
        self.files.pop((parts.hostname, parts.path.lstrip("/")), None)

    def url(self, host: str, name: str) -> str:
        """The URL of page `name` on `host`, for example `http://docs.test/a`."""
        if host not in self.hosts:
            raise ValueError(f"{host!r} is not served; known hosts: {self.hosts}")
        return f"http://{host}/{name}"

    @property
    def prefs(self) -> dict[str, object]:
        """Firefox prefs that route every HTTP(S) request through this server."""
        return {
            "network.proxy.type": 1,
            "network.proxy.http": "127.0.0.1",
            "network.proxy.http_port": self.port,
            "network.proxy.ssl": "127.0.0.1",
            "network.proxy.ssl_port": self.port,
            "network.proxy.share_proxy_settings": False,
            "network.proxy.no_proxies_on": "",
            "network.proxy.allow_hijacking_localhost": True,
            "network.proxy.socks_remote_dns": True,
        }


@pytest.fixture(scope="session")
def site():
    """A `Site` serving the hosts in `HOSTS` for the whole test session."""
    server = _Server(HOSTS)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Site(hosts=HOSTS, port=server.server_address[1], files=server.files)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
