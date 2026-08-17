"""Agent harness: synchronous observe→plan→act loop.

Implements the core agent loop per decision D3.
- Synchronous, single-threaded loop per session
- Clear causality: action result → next observation
- Predictable sequencing (no async action dispatch)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic_ai import Agent
from brotto_orchestrator.contracts import BrowserAction

from brotto_orchestrator.browser_interface import BrowserInterface
from brotto_orchestrator.context.builder import build_context
from brotto_orchestrator.domain.models import SessionDeps


@dataclass
class LoopState:
    """Mutable state during agent loop execution."""
    goal: str
    session_id: str
    step: int = 0
    max_steps: int = 20
    history: list[dict[str, Any]] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)
    terminated: bool = False
    error: Optional[str] = None


class AgentLoop:
    """Synchronous agent loop: observe → plan → act → repeat."""

    def __init__(
        self,
        agent: Agent[SessionDeps, BrowserAction],
        browser: BrowserInterface,
        max_steps: int = 20,
    ):
        """Initialize the agent loop.

        Args:
            agent: PydanticAI agent configured with BrowserAction output
            browser: Browser interface (dev: Playwright, extension: WebSocket)
            max_steps: Max iterations before termination
        """
        self.agent = agent
        self.browser = browser
        self.max_steps = max_steps

    async def run(
        self,
        goal: str,
        session_id: str,
        session_deps: SessionDeps,
    ) -> LoopResult:
        """Run the agent loop until termination or max steps.

        Args:
            goal: User's goal (e.g., "Fill this form with my information")
            session_id: Session identifier for tracking
            session_deps: SessionDeps for agent context

        Returns:
            LoopResult with history, final state, success status
        """
        state = LoopState(goal=goal, session_id=session_id, max_steps=self.max_steps)
        current_observation = None

        while not state.terminated and state.step < state.max_steps:
            state.step += 1

            try:
                # === OBSERVE ===
                # Get observation from browser (screenshot + CDP targets)
                obs = await self.browser.observe()
                current_observation = _obs_to_dict(obs)

                # === PLAN ===
                # Build context from observation, history, memory
                context_text = build_context(
                    observation=current_observation,
                    history=state.history,
                    memory=state.memory,
                    goal=state.goal,
                )

                # Call agent with context
                agent_result = await self.agent.run(
                    context_text,
                    deps=session_deps,
                )

                action: BrowserAction = agent_result.output

                # === ACT ===
                # Execute action on browser
                action_dict = _action_to_dict(action)
                action_result = await self.browser.execute(
                    action_dict,
                    deps=session_deps,
                )

                # Record in history
                state.history.append({
                    "step": state.step,
                    "type": action_dict.get("type", "unknown"),
                    "action": action_dict,
                    "result": {
                        "ok": action_result.ok,
                        "error": action_result.error,
                    },
                })

                # Check termination
                if action_dict.get("type") in ("terminate", "completion_proposed"):
                    state.terminated = True
                    if action_result.ok:
                        return LoopResult(
                            success=True,
                            step=state.step,
                            history=state.history,
                            memory=state.memory,
                            final_observation=current_observation,
                        )

            except Exception as e:
                state.error = f"{type(e).__name__}: {e}"
                state.terminated = True
                return LoopResult(
                    success=False,
                    step=state.step,
                    history=state.history,
                    memory=state.memory,
                    error=state.error,
                    final_observation=current_observation,
                )

        # Max steps reached
        if state.step >= state.max_steps:
            return LoopResult(
                success=False,
                step=state.step,
                history=state.history,
                memory=state.memory,
                error=f"Reached max_steps={state.max_steps} without termination",
                final_observation=current_observation,
            )

        return LoopResult(
            success=state.terminated,
            step=state.step,
            history=state.history,
            memory=state.memory,
            final_observation=current_observation,
        )


@dataclass
class LoopResult:
    """Result of a completed agent loop."""
    success: bool
    step: int
    history: list[dict[str, Any]]
    memory: dict[str, Any]
    final_observation: dict[str, Any]
    error: Optional[str] = None


def _action_to_dict(action: Any) -> dict[str, Any]:
    """Convert BrowserAction (Pydantic model) to dict."""
    if hasattr(action, "model_dump"):
        return action.model_dump()
    if isinstance(action, dict):
        return action
    return {"type": "unknown", "error": f"Unknown action type: {type(action)}"}


def _obs_to_dict(obs: Any) -> dict[str, Any]:
    """Convert ObservationV1 (Pydantic model) to dict."""
    if hasattr(obs, "model_dump"):
        return obs.model_dump()
    if isinstance(obs, dict):
        return obs
    return {"error": f"Unknown observation type: {type(obs)}"}
