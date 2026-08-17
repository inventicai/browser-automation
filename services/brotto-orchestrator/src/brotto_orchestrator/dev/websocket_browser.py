"""WebSocket browser adapter for extension mode.

Per Decision D9: WebSocket + sequence tracking for extension.
Receives observations from chrome.debugger extension, sends actions back.
"""

from __future__ import annotations

from typing import Any
from brotto_orchestrator.contracts import ObservationV1

from brotto_orchestrator.browser_interface import BrowserInterface
from brotto_orchestrator.domain.models import ActionResult, SessionDeps


class WebSocketBrowser(BrowserInterface):
    """Remote browser via WebSocket (extension mode).

    Per Decision D9: Outbound WSS relay for security.
    Extension sends observations, orchestrator sends actions.
    """

    def __init__(self, session_id: str, send_action_fn, receive_observation_fn):
        """Initialize WebSocket browser.

        Args:
            session_id: Session identifier
            send_action_fn: Async callback to send action dict to extension
            receive_observation_fn: Async callback to receive observation from extension
        """
        self.session_id = session_id
        self.send_action = send_action_fn
        self.receive_observation = receive_observation_fn
        self.last_observation: ObservationV1 | None = None

    async def observe(self) -> ObservationV1:
        """BrowserInterface: Receive observation from extension."""
        obs = await self.receive_observation()
        self.last_observation = obs
        return obs

    async def execute(self, action: dict[str, Any], deps: SessionDeps) -> ActionResult:
        """BrowserInterface: Send action to extension and await result.

        Per Decision D5: Errors surface to agent immediately.
        """
        try:
            # Send action to extension
            action_with_session = {
                **action,
                "session_id": self.session_id,
            }
            result = await self.send_action(action_with_session)

            # Extension returns {ok: bool, error?: str, ref_id?: str, evidence?: str}
            return ActionResult(
                ok=result.get("ok", False),
                error=result.get("error"),
                ref_id=result.get("ref_id"),
                evidence=result.get("evidence", ""),
            )
        except Exception as e:
            return ActionResult(ok=False, error=f"WebSocket action failed: {str(e)}")

    async def close(self) -> None:
        """Close WebSocket connection gracefully."""
        # Extension will close connection when session ends
        pass
