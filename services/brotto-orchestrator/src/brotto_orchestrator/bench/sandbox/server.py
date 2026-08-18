"""Sandbox: a tiny static HTML server for deterministic benchmark tasks.

Real sites change. Sandboxes don't. Each task gets its own sandbox
on a free port so multiple benchmark runs can run in parallel.

The server is plain `http.server` in a daemon thread. It serves a
single HTML page at `/` and shuts down cleanly when the context
manager exits.
"""

from __future__ import annotations

import socket
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator


def _free_port() -> int:
    """Find a free TCP port. Race-free via SO_REUSEADDR on Linux."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _SinglePageHandler(BaseHTTPRequestHandler):
    """Serve one HTML page at every path. Quiet by default."""

    html: bytes = b""

    def do_GET(self) -> None:  # noqa: N802 — http.server contract
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(self.html)))
        self.end_headers()
        self.wfile.write(self.html)

    def log_message(self, *_args) -> None:  # silence stderr noise
        return


@contextmanager
def sandbox(html: str) -> Iterator[str]:
    """Serve `html` on a free local port. Yields the URL.

    Usage:
        with sandbox("<html>...</html>") as url:
            ... # url is e.g. "http://127.0.0.1:8765"
    """
    port = _free_port()
    handler = type(
        "_BoundHandler",
        (_SinglePageHandler,),
        {"html": html.encode("utf-8")},
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


__all__ = ["sandbox"]
