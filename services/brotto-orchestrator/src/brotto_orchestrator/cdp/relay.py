"""CDPRelay: unified interface over playwright (dev) or WebSocket tunnel (extension)."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from ..dev.ax_tree_extractor import SemanticTarget


class CDPRelay:
    """Wraps a PlaywrightBrowser for dev mode.

    For extension mode, replace _browser with a WebSocket-based implementation
    that forwards CDP commands through the tunnel.
    """

    def __init__(self, browser: Any) -> None:
        # ponytail: duck-typed — works with PlaywrightBrowser or any compatible impl
        self._browser = browser

    async def navigate(self, url: str) -> None:
        await self._browser._handle_visit_url({"url": url})
        await asyncio.sleep(0.5)  # brief settle after navigation

    async def get_targets(self) -> list[SemanticTarget]:
        return await self._browser._extract_semantic_targets()

    async def get_current_url(self) -> str:
        if self._browser.page:
            return self._browser.page.url
        return ""

    async def get_page_title(self) -> str:
        if self._browser.page:
            return await self._browser.page.title()
        return ""

    async def click_ref(self, ref: str) -> str:
        target = self._browser.target_map.get(ref)
        if not target:
            return f"ref {ref} not found"
        result = await self._browser._handle_left_click({"type": "left_click", "target_id": ref})
        return "ok" if result.get("ok") else result.get("error", "failed")

    async def focus_ref(self, ref: str) -> None:
        await self.click_ref(ref)

    async def clear_ref(self, ref: str) -> None:
        if self._browser.page:
            await self._browser.page.keyboard.press("Control+A")

    async def type_text_to_ref(self, ref: str, text: str) -> str:
        result = await self._browser._handle_insert_text(
            {"type": "insert_text", "target_id": ref, "text": text}
        )
        return "ok" if result.get("ok") else result.get("error", "failed")

    async def scroll(self, direction: str, amount: int = 300) -> None:
        await self._browser._handle_scroll({"type": "scroll", "direction": direction, "amount_px": amount})

    async def wait_for_network_idle(self, timeout: int = 8) -> None:
        if self._browser.page:
            try:
                await self._browser.page.wait_for_load_state("networkidle", timeout=timeout * 1000)
            except Exception:
                pass

    async def ping(self) -> bool:
        if not self._browser.page:
            return False
        try:
            await asyncio.wait_for(
                self._browser.page.evaluate("1"),
                timeout=5.0,
            )
            return True
        except Exception:
            return False

    async def read_page_text(self, selector: str = "body", max_chars: int = 3000) -> str:
        if not self._browser.page:
            return "(no page)"
        try:
            text = await self._browser.page.evaluate(
                f'(document.querySelector({repr(selector)}) || document.body).innerText.substring(0, {max_chars})'
            )
            return str(text or "")
        except Exception as e:
            return f"(error reading page text: {e})"

    async def refresh_target_map(self) -> None:
        """Re-extract AX targets and update browser's target_map."""
        targets = await self._browser._extract_semantic_targets()
        self._browser.target_map = {t.ref_id: t for t in targets}
