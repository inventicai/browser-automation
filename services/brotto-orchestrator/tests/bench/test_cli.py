"""Tests for the benchmark CLI's card generator and sandbox lifecycle."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from brotto_orchestrator.bench.cli import _write_card  # noqa: E402


def test_write_card_with_no_results(tmp_path):
    """Empty results file produces a card with header but no rows."""
    r = tmp_path / "runs.jsonl"
    r.write_text("")
    card = tmp_path / "card.md"
    _write_card(r, card)
    text = card.read_text()
    assert "# Brotto Benchmark" in text
    assert "No benchmark runs yet" in text


def test_write_card_with_two_runs(tmp_path):
    """Two runs produce two rows in the card."""
    r = tmp_path / "runs.jsonl"
    rows = [
        {"timestamp": "2026-08-17T10:00:00Z", "task": "login_form", "ok": True},
        {"timestamp": "2026-08-17T10:00:00Z", "task": "data_extract", "ok": False},
        {"timestamp": "2026-08-18T10:00:00Z", "task": "login_form", "ok": True},
        {"timestamp": "2026-08-18T10:00:00Z", "task": "data_extract", "ok": True},
    ]
    r.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    card = tmp_path / "card.md"
    _write_card(r, card)
    text = card.read_text()
    assert "2026-08-17" in text
    assert "2026-08-18" in text


def test_write_card_caps_at_three_runs(tmp_path):
    """Card shows only the last 3 runs, not all of them."""
    r = tmp_path / "runs.jsonl"
    rows = []
    for i in range(5):
        ts = f"2026-08-1{i}T10:00:00Z"
        rows.append({"timestamp": ts, "task": "login_form", "ok": True})
    r.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    card = tmp_path / "card.md"
    _write_card(r, card)
    text = card.read_text()
    # 5 runs total, but only 3 rows in the table.
    assert text.count("2026-08-") == 3


def test_sandbox_port_freed_when_run_one_raises(monkeypatch, tmp_path):
    """Lifecycle: if _run_one raises, the sandbox port must still be released.

    Uses the public `task_urls` context manager from the CLI. We monkeypatch
    `_run_one` to raise immediately so the with-block exits via the exception
    path. After exit, the under-the-hood bind check (the same one used in
    `test_sandbox_releases_port_after_exit`) should succeed.
    """
    import asyncio

    from brotto_orchestrator.bench import cli as cli_mod

    async def _boom(*args, **kwargs):  # noqa: ANN001, ANN002
        raise RuntimeError("simulated task failure")

    monkeypatch.setattr(cli_mod, "_run_one", _boom)

    with pytest.raises(RuntimeError, match="simulated task failure"):
        with cli_mod.task_urls(["login_form"]) as urls:
            port = int(urls["login_form"].rsplit(":", 1)[1])
            # Inside the block: port is busy.
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                with pytest.raises(OSError):
                    s.bind(("127.0.0.1", port))
            finally:
                s.close()

            # Pump the inner coroutine so the exception actually fires.
            asyncio.run(_boom())

    # After the with-block exits (even via exception), the port must be free.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))  # would raise if still in use
    finally:
        s.close()


def test_task_urls_closes_all_on_inner_exception(monkeypatch):
    """If multiple sandboxes are opened and inner code raises, all get closed."""
    from brotto_orchestrator.bench import cli as cli_mod

    opened_ports: list[int] = []

    with pytest.raises(RuntimeError, match="inner boom"):
        with cli_mod.task_urls(["login_form", "data_extract"]) as urls:
            for u in urls.values():
                opened_ports.append(int(u.rsplit(":", 1)[1]))
            # Raise inside the with-block; cleanup must still run.
            raise RuntimeError("inner boom")

    # Every port should be bindable now.
    assert opened_ports, "sanity: we should have opened two sandboxes"
    for port in opened_ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
        finally:
            s.close()
