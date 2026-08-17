"""Unified browser interface for dev + extension modes.

Per Decision D7: Shared agent code with pluggable browser.
Both Playwright (dev) and WebSocket (extension) implement this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from brotto_orchestrator.contracts import ObservationV1

from brotto_orchestrator.domain.models import ActionResult, SessionDeps


class BrowserInterface(ABC):
    """Abstract browser interface for dev and extension modes.

    Allows AgentLoop to work with any browser backend.
    """

    @abstractmethod
    async def observe(self) -> ObservationV1:
        """Take observation of current page state.

        Returns:
            ObservationV1 with url, title, semantic_targets, screenshot
        """
        pass

    @abstractmethod
    async def execute(self, action: dict[str, Any], deps: SessionDeps) -> ActionResult:
        """Execute action on page.

        Args:
            action: Action dict with type, target_id, params
            deps: Session dependencies

        Returns:
            ActionResult(ok, error)
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close browser/connection gracefully."""
        pass
