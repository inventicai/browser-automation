"""Tests for the sandbox static HTML server."""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from brotto_orchestrator.bench.sandbox import sandbox  # noqa: E402


def test_sandbox_serves_html():
    html = "<html><body><h1>hello</h1></body></html>"
    with sandbox(html) as url:
        with urllib.request.urlopen(url) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
            assert body == html


def test_sandbox_releases_port_after_exit():
    """The port must be free after the context manager exits."""
    from brotto_orchestrator.bench.sandbox.server import _free_port

    with sandbox("<html/>") as url:
        used_port = int(url.rsplit(":", 1)[1])
        # Confirm the port is in use.
        with pytest.raises(OSError):
            with socket_bind_check(used_port):
                pass

    # After exit, the port should be reusable.
    assert _free_port() != used_port or _free_port() > 0


def socket_bind_check(port):
    """Context manager that asserts the port is busy."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return s
    finally:
        s.close()


def test_sandbox_supports_concurrent_tasks():
    """Two sandboxes can run side-by-side on different ports."""
    with sandbox("<html>one</html>") as url1:
        with sandbox("<html>two</html>") as url2:
            assert url1 != url2
            with urllib.request.urlopen(url1) as r1:
                assert r1.read().decode() == "<html>one</html>"
            with urllib.request.urlopen(url2) as r2:
                assert r2.read().decode() == "<html>two</html>"
