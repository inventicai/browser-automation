"""Dev mode action executor: semantic target → DOM execution via Playwright.

Maps target_id refs to actual DOM elements and executes actions.
Per Decision D2: Actions reference targets by ref_id, not coordinates.
"""

from __future__ import annotations

from typing import Any, Optional
from dataclasses import dataclass

from playwright.async_api import Page

from ..domain.models import ActionResult, SessionDeps
from ..domain.ports import ActionExecutor
from .ax_tree_extractor import SemanticTarget


@dataclass
class TargetNotFoundError(Exception):
    """Raised when target_id doesn't exist in target_map."""

    target_id: str
    message: str


class DevActionExecutor(ActionExecutor):
    """Execute actions on page using Playwright.

    Per Decision D8: Playwright for dev harness.
    Maps semantic target refs to actual DOM elements via multiple strategies:
    1. Direct coordinate-based clicking (from AX tree coordinates)
    2. Fallback to visible element detection
    """

    def __init__(self, page: Page, target_map: dict[str, SemanticTarget]):
        """Initialize executor with page reference and target map.

        Args:
            page: Playwright Page object
            target_map: Mapping of ref_id → SemanticTarget (from AX tree)
        """
        self.page = page
        self.target_map = target_map

    async def execute(self, action: dict[str, Any], deps: SessionDeps) -> ActionResult:
        """Execute action on page.

        Args:
            action: Action dict with type, target_id, params
            deps: Session dependencies

        Returns:
            ActionResult with ok/error status
        """
        action_type = action.get("type")

        try:
            if action_type == "left_click":
                return await self._execute_left_click(action)
            elif action_type == "insert_text":
                return await self._execute_insert_text(action)
            elif action_type == "visit_url":
                return await self._execute_visit_url(action)
            elif action_type == "key":
                return await self._execute_key(action)
            elif action_type == "scroll":
                return await self._execute_scroll(action)
            elif action_type == "terminate" or action_type == "completion_proposed":
                return ActionResult(ok=True, error=None)
            elif action_type == "wait":
                return await self._execute_wait(action)
            else:
                return ActionResult(
                    ok=False,
                    error=f"Unknown action type: {action_type}",
                )

        except Exception as e:
            return ActionResult(
                ok=False,
                error=f"{type(e).__name__}: {str(e)}",
            )

    async def _execute_left_click(self, action: dict[str, Any]) -> ActionResult:
        """Execute left_click action.

        Strategy:
        1. Look up target by ref_id in target_map
        2. Use coordinates to click (most reliable for dev)
        3. Error if target not found or no coordinates
        """
        target_id = action.get("target_id")

        if not target_id:
            return ActionResult(
                ok=False,
                error="Action missing target_id",
            )

        target = self.target_map.get(target_id)
        if not target:
            return ActionResult(
                ok=False,
                error=f"Target not found: {target_id}. Page may have changed.",
            )

        coords = target.coordinates
        if not coords or "x" not in coords or "y" not in coords:
            return ActionResult(
                ok=False,
                error=f"Target {target_id} has no valid coordinates. Cannot click.",
            )

        try:
            # Click at center of target element
            await self.page.mouse.click(coords["x"], coords["y"])
            return ActionResult(ok=True, error=None)

        except Exception as e:
            return ActionResult(
                ok=False,
                error=f"Click failed: {str(e)}",
            )

    async def _execute_insert_text(self, action: dict[str, Any]) -> ActionResult:
        """Execute insert_text action.

        Strategy:
        1. Look up target
        2. Click to focus (if needed)
        3. Clear existing text
        4. Type new text
        """
        target_id = action.get("target_id")
        text = action.get("text", "")

        if not target_id:
            return ActionResult(ok=False, error="Action missing target_id")

        target = self.target_map.get(target_id)
        if not target:
            return ActionResult(
                ok=False,
                error=f"Target not found: {target_id}",
            )

        coords = target.coordinates
        if not coords or "x" not in coords or "y" not in coords:
            return ActionResult(
                ok=False,
                error=f"Target {target_id} has no valid coordinates",
            )

        try:
            # Click to focus
            await self.page.mouse.click(coords["x"], coords["y"])
            # Clear existing
            await self.page.keyboard.press("Control+A")
            # Type new text
            await self.page.keyboard.type(text)
            return ActionResult(ok=True, error=None)

        except Exception as e:
            return ActionResult(ok=False, error=f"Insert text failed: {str(e)}")

    async def _execute_visit_url(self, action: dict[str, Any]) -> ActionResult:
        """Execute visit_url action."""
        url = action.get("url")

        if not url:
            return ActionResult(ok=False, error="Action missing url")

        try:
            await self.page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000,
            )
            return ActionResult(ok=True, error=None)

        except Exception as e:
            return ActionResult(
                ok=False,
                error=f"Navigation failed: {str(e)}",
            )

    async def _execute_key(self, action: dict[str, Any]) -> ActionResult:
        """Execute key action (e.g., Enter, Escape, Tab)."""
        key = action.get("key")

        if not key:
            return ActionResult(ok=False, error="Action missing key")

        try:
            await self.page.press("body", key)
            return ActionResult(ok=True, error=None)

        except Exception as e:
            return ActionResult(ok=False, error=f"Key press failed: {str(e)}")

    async def _execute_scroll(self, action: dict[str, Any]) -> ActionResult:
        """Execute scroll action."""
        direction = action.get("direction", "down")
        amount = action.get("amount_px", 500)

        try:
            if direction == "up":
                await self.page.evaluate(f"window.scrollBy(0, -{amount})")
            else:
                await self.page.evaluate(f"window.scrollBy(0, {amount})")
            return ActionResult(ok=True, error=None)

        except Exception as e:
            return ActionResult(ok=False, error=f"Scroll failed: {str(e)}")

    async def _execute_wait(self, action: dict[str, Any]) -> ActionResult:
        """Execute wait action (sleep)."""
        import asyncio

        duration_ms = action.get("duration_ms", 1000)

        try:
            await asyncio.sleep(duration_ms / 1000.0)
            return ActionResult(ok=True, error=None)

        except Exception as e:
            return ActionResult(ok=False, error=f"Wait failed: {str(e)}")
