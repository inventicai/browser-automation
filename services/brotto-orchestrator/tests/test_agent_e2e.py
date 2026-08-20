"""E2E smoke test: agent harness with TestModel (no real LLM calls)."""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("AGENT_AUTH_DISABLED", "true")
os.environ.setdefault("AGENT_MODEL", "test")  # use pydantic_ai TestModel


@pytest.mark.asyncio
async def test_stagnation_detector():
    from brotto_orchestrator.agent.stagnation import check_stagnation
    from brotto_orchestrator.agent.context import StepSummary

    steps = [
        StepSummary(step=i, url="http://same.com", action_taken="click(btn)", outcome="nothing")
        for i in range(3)
    ]
    stagnated, reason = check_stagnation(steps, window=3)
    assert stagnated
    assert "same.com" in reason


@pytest.mark.asyncio
async def test_no_stagnation_with_progress():
    from brotto_orchestrator.agent.stagnation import check_stagnation
    from brotto_orchestrator.agent.context import StepSummary

    steps = [
        StepSummary(step=0, url="http://a.com", action_taken="click(x)", outcome="ok"),
        StepSummary(step=1, url="http://b.com", action_taken="click(y)", outcome="ok"),
        StepSummary(step=2, url="http://c.com", action_taken="click(z)", outcome="ok"),
    ]
    stagnated, _ = check_stagnation(steps, window=3)
    assert not stagnated


def test_login_guardrail():
    from brotto_orchestrator.agent.guardrails import check_login_page

    assert check_login_page("Sign In", "", "")
    assert check_login_page("Dashboard", "password textbox", "")
    assert not check_login_page("Dashboard", "welcome", "http://app.com/home")


def test_critical_action_guardrail():
    from brotto_orchestrator.agent.guardrails import check_critical_action

    assert check_critical_action("click", {"description": "delete account"})
    assert check_critical_action("click", {"description": "confirm payment"})
    assert not check_critical_action("click", {"ref": "btn_save", "description": "save draft"})


def test_ax_filter():
    from brotto_orchestrator.agent.ax_filter import filter_ax_targets
    from brotto_orchestrator.dev.ax_tree_extractor import SemanticTarget

    targets = [
        SemanticTarget(ref_id="btn_1", tag="button", role="button", name="Submit"),
        SemanticTarget(ref_id="lnk_1", tag="a", role="link", name="Home"),
        SemanticTarget(ref_id="gen_1", tag="div", role="generic", name=""),
        SemanticTarget(ref_id="txt_1", tag="input", role="textbox", name="Email"),
    ]
    result = filter_ax_targets(targets)
    assert "btn_1" in result
    assert "lnk_1" in result
    assert "txt_1" in result
    assert "gen_1" not in result  # stripped generic with no name


@pytest.mark.asyncio
async def test_harness_completes_with_test_model():
    """Harness should run + return result when agent calls task_complete."""
    from pydantic_ai.models.test import TestModel
    from brotto_orchestrator.agent.harness import AgentHarness, _turn_to_prompt
    from brotto_orchestrator.agent.context import AgentDeps, AgentDecision, Scratchpad

    # Build a fake CDPRelay
    from brotto_orchestrator.dev.ax_tree_extractor import SemanticTarget
    fake_target = SemanticTarget(ref_id="btn_ok", tag="button", role="button", name="OK")

    cdp = MagicMock()
    cdp.ping = AsyncMock(return_value=True)
    cdp.get_targets = AsyncMock(return_value=[fake_target])
    cdp.get_current_url = AsyncMock(return_value="http://example.com")
    cdp.get_page_title = AsyncMock(return_value="Example Page")
    cdp.refresh_target_map = AsyncMock()

    messages = []

    async def ws_send(msg):
        messages.append(msg)

    deps = AgentDeps(
        user_id="test",
        task="Check that http://example.com loads",
        cdp=cdp,
        ws_send=ws_send,
    )

    # Patch the global agent to use TestModel with a canned task_complete decision
    import brotto_orchestrator.agent.harness as harness_mod
    original_agent = harness_mod.agent

    test_agent = harness_mod.agent.__class__(
        TestModel(
            custom_output_args={
                "reasoning": "Page loaded successfully",
                "thought": "Page loaded",
                "actions": [
                    {"action": "task_complete", "action_args": {"summary": "Page loaded", "extracted_data": None}},
                ],
            },
        ),
        output_type=AgentDecision,
        deps_type=AgentDeps,
        system_prompt=harness_mod.SYSTEM_PROMPT,
    )
    harness_mod.agent = test_agent

    try:
        h = AgentHarness()
        result = await h.run(deps)
        assert result.status == "completed"
        assert result.steps_taken == 0
        # progress event was sent
        assert any(m.get("type") == "step_progress" for m in messages)
    finally:
        harness_mod.agent = original_agent


@pytest.mark.asyncio
async def test_harness_blocks_on_approval_when_queue_is_empty():
    """Diagnose the approval_gate stall.

    When the agent emits a critical action, the harness sends
    `approval_required` and then `await human_input_queue.get()` with
    no timeout. With an empty queue the run stalls; the benchmark
    runner's outer wait_for(timeout=120) is what surfaces this as a
    timeout error. Confirms the runner must pre-seed the queue for
    `requires_approval` tasks.
    """
    from pydantic_ai.models.test import TestModel
    from brotto_orchestrator.agent.harness import AgentHarness
    import brotto_orchestrator.agent.harness as harness_mod
    from brotto_orchestrator.agent.context import AgentDeps, AgentDecision
    from brotto_orchestrator.dev.ax_tree_extractor import SemanticTarget

    cdp = MagicMock()
    cdp.ping = AsyncMock(return_value=True)
    cdp.get_targets = AsyncMock(
        return_value=[SemanticTarget(ref_id="btn_del", tag="button", role="button", name="Delete account")]
    )
    cdp.get_current_url = AsyncMock(return_value="http://example.com/account")
    cdp.get_page_title = AsyncMock(return_value="Account")
    cdp.refresh_target_map = AsyncMock()
    cdp.click_ref = AsyncMock(return_value="clicked")
    cdp.get_targets_after = cdp.get_targets

    messages: list[dict] = []
    q: asyncio.Queue = asyncio.Queue()  # intentionally empty

    async def ws_send(msg):
        messages.append(msg)

    deps = AgentDeps(
        user_id="test",
        task="delete the account, ask first",
        cdp=cdp,
        ws_send=ws_send,
        human_input_queue=q,
    )

    test_agent = harness_mod.agent.__class__(
        TestModel(
            custom_output_args={
                "reasoning": "destructive action",
                "thought": "clicking delete",
                "actions": [
                    {"action": "click", "action_args": {"ref": "btn_del", "description": "delete account"}},
                ],
            },
        ),
        output_type=AgentDecision,
        deps_type=AgentDeps,
        system_prompt=harness_mod.SYSTEM_PROMPT,
    )
    original = harness_mod.agent
    harness_mod.agent = test_agent
    try:
        h = AgentHarness()
        # short timeout proves the stall — no sentinel = blocks forever
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(h.run(deps), timeout=0.5)
        # The approval_required frame DID go out before the stall.
        assert any(m.get("type") == "approval_required" for m in messages), (
            "harness should have sent approval_required before blocking on the queue"
        )
    finally:
        harness_mod.agent = original


@pytest.mark.asyncio
async def test_harness_unblocks_when_approval_sentinel_is_queued():
    """End-to-end: a sentinel 'yes' on the queue unblocks the harness
    and lets the run complete normally. This is what the benchmark
    runner must do for tasks with `requires_approval=True`.
    """
    from pydantic_ai.models.test import TestModel
    from brotto_orchestrator.agent.harness import AgentHarness
    import brotto_orchestrator.agent.harness as harness_mod
    from brotto_orchestrator.agent.context import AgentDeps, AgentDecision
    from brotto_orchestrator.dev.ax_tree_extractor import SemanticTarget

    cdp = MagicMock()
    cdp.ping = AsyncMock(return_value=True)
    cdp.get_targets = AsyncMock(
        return_value=[SemanticTarget(ref_id="btn_del", tag="button", role="button", name="Delete account")]
    )
    cdp.get_current_url = AsyncMock(return_value="http://example.com/account")
    cdp.get_page_title = AsyncMock(return_value="Account")
    cdp.refresh_target_map = AsyncMock()
    cdp.click_ref = AsyncMock(return_value="clicked")

    messages: list[dict] = []
    q: asyncio.Queue = asyncio.Queue()
    # Pre-seed the approval reply BEFORE the harness runs — same pattern
    # the benchmark runner should use for requires_approval tasks.
    # TestModel re-emits the same critical action every step, so we need
    # a sentinel ready for each iteration (capped by max_steps=4).
    for _ in range(4):
        q.put_nowait("yes")

    async def ws_send(msg):
        messages.append(msg)

    deps = AgentDeps(
        user_id="test",
        task="delete the account, ask first",
        cdp=cdp,
        ws_send=ws_send,
        human_input_queue=q,
    )

    test_agent = harness_mod.agent.__class__(
        TestModel(
            custom_output_args={
                "reasoning": "destructive action",
                "thought": "clicking delete",
                "actions": [
                    {"action": "click", "action_args": {"ref": "btn_del", "description": "delete account"}},
                ],
            },
        ),
        output_type=AgentDecision,
        deps_type=AgentDeps,
        system_prompt=harness_mod.SYSTEM_PROMPT,
    )
    original = harness_mod.agent
    harness_mod.agent = test_agent
    try:
        h = AgentHarness()
        # Run in the background; we only need to assert the harness
        # progressed PAST the approval gate (click ran) without stalling.
        # We don't drive the full 30-step loop — TestModel re-emits the
        # same click until stagnation or max_steps, which isn't what
        # we're testing here.
        run_task = asyncio.create_task(h.run(deps))

        # Wait for the first approval_required frame, then for the
        # subsequent step_progress (proves the click executed).
        deadline = asyncio.get_event_loop().time() + 2.0
        while asyncio.get_event_loop().time() < deadline:
            if any(m.get("type") == "step_progress" for m in messages):
                break
            await asyncio.sleep(0.05)
        else:
            run_task.cancel()
            raise AssertionError("harness stalled — no step_progress after approval sentinel")

        # Approval frame went out and the click ran through the gate.
        assert any(m.get("type") == "approval_required" for m in messages)

        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):
            pass
    finally:
        harness_mod.agent = original


if __name__ == "__main__":
    # Quick self-check without pytest
    asyncio.run(test_harness_completes_with_test_model())
    test_stagnation_detector.__wrapped__ = None
    asyncio.run(test_stagnation_detector())
    asyncio.run(test_no_stagnation_with_progress())
    test_login_guardrail()
    test_critical_action_guardrail()
    test_ax_filter()
    print("All checks passed")
