"""Production app: wires AgentLoop + SessionEngine + WebSocket transport.

Per architecture: Unified AgentLoop for both dev and extension modes.
Extension mode: WebSocket transport (CanonicalTransport) → SessionEngine → AgentLoop.
Dev mode: Playwright direct → AgentLoop.

This file creates the SessionEngine with AgentLoop for full end-to-end agent control.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent
from brotto_orchestrator.contracts import BrowserAction

from ..browser_interface import BrowserInterface
from ..domain.models import SessionDeps, PlanningInput, PlanningOutcome
from ..domain.ports import InferencePort
from ..harness.agent_loop import AgentLoop
from ..context.builder import build_context


class AgentLoopInferenceAdapter(InferencePort):
    """Adapts AgentLoop (observe→plan→act) as InferencePort (just planning).

    For extension mode: SessionEngine calls plan(), which runs one agent turn.
    For dev mode: Use AgentLoop directly (includes execution).

    This adapter lets SessionEngine and AgentLoop coexist:
    - Extension: SessionEngine handles observation reception + action dispatch
    - Dev: AgentLoop handles everything end-to-end
    """

    def __init__(
        self,
        agent: Agent[SessionDeps, BrowserAction],
        browser: BrowserInterface | None = None,
    ):
        """Initialize adapter.

        Args:
            agent: PydanticAI agent
            browser: Optional browser for dev mode integration
        """
        self.agent = agent
        self.browser = browser

    async def plan(self, input: PlanningInput) -> PlanningOutcome:
        """Implement InferencePort.plan() for SessionEngine.

        Takes planning input (goal, observation, history, memory),
        calls agent with context, returns action.
        """
        # Build context from observation + history + memory
        context_text = build_context(
            observation=input.observation,
            history=input.history,
            memory=input.memory,
            goal=input.goal,
        )

        # Call agent
        deps = SessionDeps(
            session_id=input.session_id,
            sink=None,  # SessionEngine handles sink
            history=[h.get("type", "") for h in input.history],
        )
        result = await self.agent.run(context_text, deps=deps)

        # Extract action
        action_dict = {}
        if hasattr(result.output, "model_dump"):
            action_dict = result.output.model_dump()
        elif isinstance(result.output, dict):
            action_dict = result.output
        else:
            action_dict = {"type": "unknown"}

        return PlanningOutcome(
            action=action_dict,
            usage={"tokens": len(context_text) // 4},
        )


def create_agent_app(
    agent: Agent[SessionDeps, BrowserAction],
    browser: BrowserInterface | None = None,
) -> AgentLoopInferenceAdapter:
    """Create production app that unifies agent across all modes.

    Usage:
      # Dev mode (Playwright):
      browser = PlaywrightBrowser()
      await browser.launch(url=target_url)
      loop = AgentLoop(agent=agent, browser=browser)
      result = await loop.run(goal=goal, session_id=sid, session_deps=deps)

      # Extension mode (WebSocket):
      inference_port = create_agent_app(agent=agent)
      engine = SessionEngine(agent=inference_port, ...)
      # Extension sends observations → engine.handle_observation() → actions back
    """
    return AgentLoopInferenceAdapter(agent=agent, browser=browser)
