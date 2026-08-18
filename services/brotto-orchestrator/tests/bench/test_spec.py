"""Tests for the benchmark task spec types."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from brotto_orchestrator.bench.spec import RunState, TaskResult, TaskSpec  # noqa: E402


def test_task_spec_is_immutable():
    """TaskSpec is frozen — once defined, a task cannot drift."""
    async def ok(state: RunState) -> bool:
        return True

    spec = TaskSpec(name="x", goal="g", start_url="http://x", success_check=ok)
    with pytest.raises(Exception):
        spec.name = "y"


def test_run_state_defaults():
    state = RunState()
    assert state.final_url == ""
    assert state.extracted_data is None
    assert state.scratchpad == ""
    assert state.steps_taken == 0
    assert state.approval_was_requested is False


def test_task_result_serialises_to_jsonl():
    """JSONL output is one row per (task, model) run."""
    import json
    r = TaskResult(
        timestamp="2026-08-18T00:00:00Z",
        task="login_form",
        model="haiku-4-5",
        ok=True,
        steps=4,
        tokens=1823,
        elapsed_ms=12400,
    )
    line = json.dumps(r.__dict__)
    parsed = json.loads(line)
    assert parsed["task"] == "login_form"
    assert parsed["ok"] is True
    assert parsed["steps"] == 4
