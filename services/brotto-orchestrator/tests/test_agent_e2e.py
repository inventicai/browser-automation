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
                "action": "task_complete",
                "action_args": {"summary": "Page loaded", "extracted_data": None},
                "scratchpad_update": None,
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
