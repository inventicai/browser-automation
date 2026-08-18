"""Tests for the runner's approval-queue seeding."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from brotto_orchestrator.dev import playwright_browser as _pb  # noqa: E402, F401
from brotto_orchestrator.cdp import relay as _relay  # noqa: E402, F401
from brotto_orchestrator.agent import harness as _harness  # noqa: E402, F401

from brotto_orchestrator.bench.spec import RunState, TaskSpec  # noqa: E402
from brotto_orchestrator.bench.runner import run_task  # noqa: E402


def _stub_harness(stub_run):
    fake_cdp = MagicMock()
    fake_cdp.get_current_url = AsyncMock(return_value="http://x")
    fake_cdp.get_targets = AsyncMock(return_value=[])
    fake_cdp.get_page_title = AsyncMock(return_value="x")
    fake_browser = MagicMock()
    fake_browser.launch = AsyncMock()
    fake_browser.close = AsyncMock()

    harness_cls = MagicMock()
    harness_cls.return_value.run = AsyncMock(side_effect=stub_run)

    patches = [
        patch("brotto_orchestrator.dev.playwright_browser.PlaywrightBrowser", return_value=fake_browser),
        patch("brotto_orchestrator.cdp.relay.CDPRelay", return_value=fake_cdp),
        patch("brotto_orchestrator.agent.harness.AgentHarness", harness_cls),
    ]
    return patches


@pytest.mark.asyncio
async def test_runner_seeds_approval_queue_when_requires_approval(tmp_path):
    """Tasks with requires_approval must pre-seed the human queue."""
    seen_queues: list[asyncio.Queue] = []

    from brotto_orchestrator.agent.context import AgentDeps

    async def stub_run(deps):
        seen_queues.append(deps.human_input_queue)
        from brotto_orchestrator.agent.context import TaskResult as _TR
        return _TR(status="completed", summary="x", steps_taken=1,
                   extracted_data={"request": "approved"})

    async def fail_check(state):
        return True

    spec = TaskSpec(
        name="approval", goal="x", start_url="http://x",
        success_check=fail_check, requires_approval=True, max_steps=4,
    )
    patches = _stub_harness(stub_run)
    for p in patches:
        p.start()
    try:
        await run_task(spec, model="m", results_path=tmp_path / "r.jsonl", timeout_s=5)
    finally:
        for p in patches:
            p.stop()

    assert seen_queues, "harness was not invoked"
    q = seen_queues[0]
    # The runner pre-seeds max_steps sentinels. The stub harness does
    # not consume them, so the queue still holds them all.
    assert q.qsize() == spec.max_steps, (
        f"expected {spec.max_steps} sentinels, got {q.qsize()}"
    )


@pytest.mark.asyncio
async def test_runner_does_not_seed_queue_when_not_required(tmp_path):
    """Tasks without requires_approval must leave the queue empty."""
    seen_queues: list[asyncio.Queue] = []

    async def stub_run(deps):
        seen_queues.append(deps.human_input_queue)
        from brotto_orchestrator.agent.context import TaskResult as _TR
        return _TR(status="completed", summary="x", steps_taken=1)

    async def ok(state):
        return True

    spec = TaskSpec(
        name="nope", goal="x", start_url="http://x",
        success_check=ok,
    )
    patches = _stub_harness(stub_run)
    for p in patches:
        p.start()
    try:
        await run_task(spec, model="m", results_path=tmp_path / "r.jsonl", timeout_s=5)
    finally:
        for p in patches:
            p.stop()

    assert seen_queues
    assert seen_queues[0].qsize() == 0
