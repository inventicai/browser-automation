#!/usr/bin/env python3
"""Dev eval runner using Playwright + AgentLoop for unified testing."""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, "services/brotto-orchestrator/src")

from brotto_orchestrator.dev.playwright_browser import PlaywrightBrowser
from brotto_orchestrator.harness.agent_loop import AgentLoop
from brotto_orchestrator.domain.models import SessionDeps
from brotto_orchestrator.settings import load_settings


@dataclass
class DevTaskResult:
    name: str
    success: bool = False
    steps: int = 0
    duration_ms: int = 0
    actions: list[str] = field(default_factory=list)
    error: str | None = None


async def run_dev_task(
    *,
    name: str,
    goal: str,
    start_url: str,
    max_steps: int = 5,
    headless: bool = True,
) -> DevTaskResult:
    """Run agent against real browser via AgentLoop + Playwright."""
    import os

    result = DevTaskResult(name=name)
    browser = PlaywrightBrowser()
    start = time.perf_counter()

    try:
        # Launch browser
        await browser.launch(headless=headless, url=start_url)
        cfg = load_settings()

        # Set API key for PydanticAI
        os.environ['ANTHROPIC_API_KEY'] = cfg.api_key

        # Build agent via factory
        from brotto_orchestrator.agent.factory import build_agent
        from brotto_orchestrator.policy.adapter import PolicyAdapter
        from brotto_policy import SessionPolicyChecker

        policy = PolicyAdapter(SessionPolicyChecker())
        agent = build_agent(
            model_name=cfg.model,
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            executor=None,
            policy=policy,
            approval_manager=None,
            history_sink=None,
        )

        # Create agent loop with BrowserInterface
        loop = AgentLoop(agent=agent, browser=browser, max_steps=max_steps)
        deps = SessionDeps(session_id="dev_session", sink=None)

        # Run agent loop
        loop_result = await loop.run(
            goal=goal,
            session_id="dev_session",
            session_deps=deps,
        )

        result.success = loop_result.success
        result.steps = loop_result.step
        result.error = loop_result.error

        # Extract action types from history
        for h in loop_result.history:
            result.actions.append(h.get("type", "unknown"))

    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
    finally:
        await browser.close()
        result.duration_ms = int((time.perf_counter() - start) * 1000)

    return result


async def main() -> None:
    """Run dev eval suite."""
    tasks = [
        {
            "name": "simple-visit",
            "goal": "Navigate to example.com",
            "start_url": "about:blank",
            "max_steps": 2,
        },
        {
            "name": "screenshot",
            "goal": "Take screenshot of current page",
            "start_url": "https://example.com",
            "max_steps": 1,
        },
    ]

    results = []
    for task in tasks:
        print(f"\n[dev] {task['name']}...")
        result = await run_dev_task(**task, headless=True)
        results.append(result)
        print(
            f"  {'✓' if result.success else '✗'} "
            f"({result.steps} steps, {result.duration_ms}ms)"
        )
        if result.error:
            print(f"  Error: {result.error}")

    print("\n" + "=" * 60)
    print("DEV EVAL SUMMARY")
    print("=" * 60)
    passed = sum(1 for r in results if r.success)
    print(f"Passed: {passed}/{len(results)}")
    for r in results:
        status = "✓" if r.success else "✗"
        print(f"  {status} {r.name:30s} ({r.steps} steps, {r.duration_ms}ms)")


if __name__ == "__main__":
    asyncio.run(main())
