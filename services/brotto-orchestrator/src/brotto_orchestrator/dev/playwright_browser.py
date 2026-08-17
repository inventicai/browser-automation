"""Playwright browser adapter for local dev testing.

Uses Chrome DevTools Protocol for semantic target extraction via AX tree.
Implements D1, D2 (CDP Accessibility Tree, semantic ref_ids).
Implements BrowserInterface for unified dev+extension architecture.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

from playwright.async_api import Browser, Page, async_playwright, CDPSession
from brotto_orchestrator.contracts import ObservationV1

from brotto_orchestrator.browser_interface import BrowserInterface
from brotto_orchestrator.domain.models import ActionResult, SessionDeps
from .ax_tree_extractor import AXTreeExtractor, SemanticTarget


class PlaywrightBrowser(BrowserInterface):
    """Local browser automation via Playwright + CDP for dev/testing.

    Per Decision D8: Playwright + CDP for dev harness.
    """

    def __init__(self) -> None:
        self.browser: Browser | None = None
        self.page: Page | None = None
        self.target_map: dict[str, SemanticTarget] = {}

    async def launch(self, headless: bool = False, url: str = "about:blank") -> None:
        """Launch browser and navigate to URL."""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=headless)
        self.page = await self.browser.new_page()
        await self.page.goto(url, wait_until="domcontentloaded")

    async def observe(self) -> ObservationV1:
        """BrowserInterface: Take observation of current page state."""
        return await self.screenshot_to_observation()

    async def close(self) -> None:
        """Close browser gracefully."""
        if self.page:
            await self.page.close()
        if self.browser:
            await self.browser.close()

    async def screenshot_to_observation(self) -> ObservationV1:
        """Take screenshot and generate ObservationV1 with semantic targets.

        Per Decision D4: Structured observation with targets + screenshot.
        """
        if not self.page:
            raise RuntimeError("Browser not launched")

        # Screenshot
        screenshot = await self.page.screenshot()
        screenshot_b64 = base64.b64encode(screenshot).decode("utf-8")

        # HTML content
        html = await self.page.content()

        # Page info
        url = self.page.url
        title = await self.page.title()

        # Extract semantic targets via CDP AX tree (Decision D1)
        targets = await self._extract_semantic_targets()

        # Store target map for action execution
        self.target_map = {t.ref_id: t for t in targets}

        # Observation
        return ObservationV1.model_construct(
            observation_id="obs_dev_" + str(int(asyncio.get_event_loop().time() * 1000)),
            sequence=0,
            payload={
                "html": html,
                "screenshot": f"data:image/png;base64,{screenshot_b64}",
            },
            url=url,
            title=title,
            semantic_targets=[self._target_to_dict(t) for t in targets],
            timestamp=None,
        )

    async def _extract_semantic_targets(self) -> list[SemanticTarget]:
        """Extract semantic targets via CDP Accessibility Tree.

        Per Decision D1: Use CDP, not JavaScript DOM queries.
        """
        if not self.page:
            return []

        try:
            cdp_session = await self.page.context.new_cdp_session(self.page)
            targets = await AXTreeExtractor.extract_targets(cdp_session, max_targets=50)
            return targets
        except Exception as e:
            print(f"Warning: Failed to extract targets via CDP: {e}")
            return []

    @staticmethod
    def _target_to_dict(target: SemanticTarget) -> dict[str, Any]:
        """Convert SemanticTarget to dict for observation."""
        return {
            "ref_id": target.ref_id,
            "tag": target.tag,
            "role": target.role,
            "name": target.name,
            "value": target.value,
            "coordinates": target.coordinates,
        }

    async def execute(self, action: dict[str, Any], deps: SessionDeps) -> ActionResult:
        """BrowserInterface: Execute action on page.

        Per Decision D2: Actions reference targets by ref_id, not coordinates.
        """
        if not self.page:
            return ActionResult(ok=False, error="Browser not launched")

        action_type = action.get("type")

        try:
            result = await self._execute_action_internal(action)
            return ActionResult(
                ok=result.get("ok", False),
                error=result.get("error"),
                ref_id=action.get("target_id"),
            )
        except Exception as e:
            return ActionResult(ok=False, error=str(e))

    async def _execute_action_internal(self, action: dict[str, Any]) -> dict[str, Any]:
        """Internal action execution returning dict for easy conversion."""
        action_type = action.get("type")

        try:
            if action_type == "left_click":
                return await self._handle_left_click(action)
            elif action_type == "insert_text":
                return await self._handle_insert_text(action)
            elif action_type == "visit_url":
                return await self._handle_visit_url(action)
            elif action_type == "key":
                return await self._handle_key(action)
            elif action_type == "scroll":
                return await self._handle_scroll(action)
            elif action_type == "terminate" or action_type == "completion_proposed":
                return {"ok": True, "action_type": action_type}
            elif action_type == "wait":
                return await self._handle_wait(action)
            else:
                return {
                    "ok": False,
                    "error": f"Unknown action type: {action_type}",
                    "action_type": action_type,
                }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "action_type": action_type,
            }

    async def _handle_left_click(self, action: dict[str, Any]) -> dict[str, Any]:
        """Handle left_click action via semantic target ref_id."""
        if not self.page:
            return {"ok": False, "error": "Browser not initialized"}

        target_id = action.get("target_id")
        if not target_id:
            return {
                "ok": False,
                "error": "No target_id provided",
                "action_type": "left_click",
            }

        target = self.target_map.get(target_id)
        if not target:
            return {
                "ok": False,
                "error": f"Target not found: {target_id}",
                "action_type": "left_click",
            }

        try:
            if target.backend_node_id:
                await self.page.click(
                    f'[data-backend-node-id="{target.backend_node_id}"]',
                    timeout=5000,
                )
            else:
                coords = target.coordinates
                if coords and "x" in coords and "y" in coords:
                    await self.page.mouse.click(coords["x"], coords["y"])
                else:
                    return {
                        "ok": False,
                        "error": "No coordinates or backend_node_id for target",
                        "action_type": "left_click",
                    }

            return {"ok": True, "action_type": "left_click"}
        except Exception as e:
            return {
                "ok": False,
                "error": f"Click failed: {e}",
                "action_type": "left_click",
            }

    async def _handle_insert_text(self, action: dict[str, Any]) -> dict[str, Any]:
        """Handle insert_text action."""
        if not self.page:
            return {"ok": False, "error": "Browser not initialized"}

        target_id = action.get("target_id")
        text = action.get("text", "")

        if not target_id:
            return {
                "ok": False,
                "error": "No target_id provided",
                "action_type": "insert_text",
            }

        target = self.target_map.get(target_id)
        if not target:
            return {
                "ok": False,
                "error": f"Target not found: {target_id}",
                "action_type": "insert_text",
            }

        try:
            if target.backend_node_id:
                await self.page.fill(
                    f'[data-backend-node-id="{target.backend_node_id}"]',
                    text,
                    timeout=5000,
                )
            else:
                return {
                    "ok": False,
                    "error": "No selector for target",
                    "action_type": "insert_text",
                }

            return {"ok": True, "action_type": "insert_text"}
        except Exception as e:
            return {
                "ok": False,
                "error": f"Insert text failed: {e}",
                "action_type": "insert_text",
            }

    async def _handle_visit_url(self, action: dict[str, Any]) -> dict[str, Any]:
        """Handle visit_url action."""
        if not self.page:
            return {"ok": False, "error": "Browser not initialized"}

        url = action.get("url")
        if not url:
            return {
                "ok": False,
                "error": "No URL provided",
                "action_type": "visit_url",
            }

        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return {"ok": True, "action_type": "visit_url"}
        except Exception as e:
            return {
                "ok": False,
                "error": f"Navigation failed: {e}",
                "action_type": "visit_url",
            }

    async def _handle_key(self, action: dict[str, Any]) -> dict[str, Any]:
        """Handle key action."""
        if not self.page:
            return {"ok": False, "error": "Browser not initialized"}

        key = action.get("key")
        if not key:
            return {
                "ok": False,
                "error": "No key provided",
                "action_type": "key",
            }

        try:
            await self.page.press("body", key)
            return {"ok": True, "action_type": "key"}
        except Exception as e:
            return {
                "ok": False,
                "error": f"Key press failed: {e}",
                "action_type": "key",
            }

    async def _handle_scroll(self, action: dict[str, Any]) -> dict[str, Any]:
        """Handle scroll action."""
        if not self.page:
            return {"ok": False, "error": "Browser not initialized"}

        direction = action.get("direction", "down")
        try:
            if direction == "up":
                await self.page.evaluate("window.scrollBy(0, -500)")
            else:
                await self.page.evaluate("window.scrollBy(0, 500)")
            return {"ok": True, "action_type": "scroll"}
        except Exception as e:
            return {
                "ok": False,
                "error": f"Scroll failed: {e}",
                "action_type": "scroll",
            }

    async def _handle_wait(self, action: dict[str, Any]) -> dict[str, Any]:
        """Handle wait action."""
        duration_ms = action.get("duration_ms", 1000)
        try:
            await asyncio.sleep(duration_ms / 1000.0)
            return {"ok": True, "action_type": "wait"}
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "action_type": "wait",
            }
