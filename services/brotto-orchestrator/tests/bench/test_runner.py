"""Tests for the benchmark runner.

We stub the harness so the runner tests don't need a real LLM or
Playwright. The runner's job is wiring — Playwright startup, sandbox
lifecycle, success check, JSONL append — and that's what we test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

# Import the modules we patch so they're loaded into sys.modules.
from brotto_orchestrator.dev import playwright_browser as _pb  # noqa: E402, F401
from brotto_orchestrator.cdp import relay as _relay  # noqa: E402, F401
from brotto_orchestrator.agent import harness as _harness  # noqa: E402, F401

from brotto_orchestrator.bench.runner import _append_jsonl, run_task  # noqa: E402
from brotto_orchestrator.bench.spec import RunState, TaskResult, TaskSpec  # noqa: E402


def _stub_harness_module(stub_run):
    """Patch PlaywrightBrowser, CDPRelay, and AgentHarness to fakes."""
    fake_target = {"ref": "x", "x": 1, "y": 1}
    fake_cdp = MagicMock()
    fake_cdp.get_current_url = AsyncMock(return_value="http://x.example/done")
    fake_cdp.get_targets = AsyncMock(return_value=[fake_target])
    fake_cdp.get_page_title = AsyncMock(return_value="Done")
    fake_browser = MagicMock()
    fake_browser.launch = AsyncMock()
    fake_browser.close = AsyncMock()

    harness_cls_mock = MagicMock()
    harness_cls_mock.return_value.run = AsyncMock(side_effect=stub_run)

    HarnessCls = patch("brotto_orchestrator.agent.harness.AgentHarness", harness_cls_mock)

    patches = [
        patch("brotto_orchestrator.dev.playwright_browser.PlaywrightBrowser", return_value=fake_browser),
        patch("brotto_orchestrator.cdp.relay.CDPRelay", return_value=fake_cdp),
        HarnessCls,
    ]
    return patches, fake_browser, fake_cdp


@pytest.mark.asyncio
async def test_run_task_appends_jsonl(tmp_path):
    """The runner writes a JSONL row per task run."""
    async def ok_check(state: RunState) -> bool:
        return True

    async def stub_run(deps):
        from brotto_orchestrator.agent.context import TaskResult as _TR
        return _TR(
            status="completed",
            summary="stub",
            steps_taken=3,
            extracted_data={"answer": 42},
            timing={"total_tokens": 1234},
        )

    spec = TaskSpec(
        name="login_form",
        goal="Log in",
        start_url="http://127.0.0.1:1/",
        success_check=ok_check,
    )

    patches, _, _ = _stub_harness_module(stub_run)
    for p in patches:
        p.start()

    try:
        result = await run_task(
            spec, model="haiku-4-5", results_path=tmp_path / "runs.jsonl",
        )
    finally:
        for p in patches:
            p.stop()

    assert result.ok is True
    assert result.task == "login_form"
    assert result.model == "haiku-4-5"
    assert result.steps == 3
    assert result.extracted == {"answer": 42}

    lines = (tmp_path / "runs.jsonl").read_text().strip().split("\n")
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["task"] == "login_form"
    assert parsed["ok"] is True


@pytest.mark.asyncio
async def test_run_task_records_timeout(tmp_path):
    """A harness that hangs gets a timeout JSONL row."""
    async def hang(deps):
        await asyncio.sleep(60)

    async def ok_check(state):
        return True

    spec = TaskSpec(name="hang", goal="hang", start_url="http://x", success_check=ok_check)
    patches, _, _ = _stub_harness_module(hang)
    for p in patches:
        p.start()

    try:
        result = await run_task(
            spec, model="haiku-4-5", results_path=tmp_path / "r.jsonl",
            timeout_s=1.0,
        )
    finally:
        for p in patches:
            p.stop()

    assert result.ok is False
    assert result.error == "timeout"


@pytest.mark.asyncio
async def test_success_check_can_fail(tmp_path):
    """The runner respects the success check's verdict."""
    async def stub_run(deps):
        from brotto_orchestrator.agent.context import TaskResult as _TR
        return _TR(status="completed", summary="stub", steps_taken=1)

    async def ok(state):
        return True

    async def fail(state):
        return False

    spec_ok = TaskSpec(name="ok", goal="g", start_url="http://x", success_check=ok)
    spec_fail = TaskSpec(name="fail", goal="g", start_url="http://x", success_check=fail)

    patches, _, _ = _stub_harness_module(stub_run)
    for p in patches:
        p.start()

    try:
        r_ok = await run_task(spec_ok, model="haiku-4-5", results_path=tmp_path / "ok.jsonl")
        r_fail = await run_task(spec_fail, model="haiku-4-5", results_path=tmp_path / "fail.jsonl")
    finally:
        for p in patches:
            p.stop()

    assert r_ok.ok is True
    assert r_fail.ok is False


@pytest.mark.asyncio
async def test_success_check_can_raise(tmp_path):
    """A success check that raises marks the task as failed, not crashed."""
    async def stub_run(deps):
        from brotto_orchestrator.agent.context import TaskResult as _TR
        return _TR(status="completed", summary="stub", steps_taken=1)

    async def kaboom(state):
        raise RuntimeError("intentional")

    spec = TaskSpec(name="kaboom", goal="g", start_url="http://x", success_check=kaboom)
    patches, _, _ = _stub_harness_module(stub_run)
    for p in patches:
        p.start()

    try:
        result = await run_task(spec, model="haiku-4-5", results_path=tmp_path / "r.jsonl")
    finally:
        for p in patches:
            p.stop()

    assert result.ok is False
    assert "check_error" in (result.error or "")


def test_append_jsonl_creates_parent_dirs(tmp_path):
    """The runner should create the results directory if missing."""
    out = tmp_path / "nested" / "deep" / "runs.jsonl"
    r = TaskResult(
        timestamp="t", task="x", model="m", ok=True,
        steps=1, tokens=1, elapsed_ms=1,
    )
    _append_jsonl(out, r)
    assert out.exists()
    assert json.loads(out.read_text().strip())["task"] == "x"


import asyncio  # noqa: E402
