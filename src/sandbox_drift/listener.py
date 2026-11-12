"""A tiny HTTP listener on 127.0.0.1 that records which paths were requested."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_HITS = 100  # bounded so a noisy sandbox cannot grow memory


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        hits: list[str] = self.server.hits  # type: ignore[attr-defined]
        if len(hits) < MAX_HITS:
            hits.append(self.path)
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # silence the default stderr log
        return


class CanaryListener:
    """Bind to ``127.0.0.1`` on a random port; always shut down on exit."""

    def __init__(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.daemon_threads = True
        self._server.hits = []  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def hits(self) -> list[str]:
        return list(self._server.hits)  # type: ignore[attr-defined]

    def __enter__(self) -> "CanaryListener":
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
