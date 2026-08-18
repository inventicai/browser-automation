"""Tests for the benchmark CLI's card generator."""

from __future__ import annotations

import json
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
