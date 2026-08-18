"""CDPRelay backed by a browser extension WebSocket instead of Playwright."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from ..dev.ax_tree_extractor import SemanticTarget

log = logging.getLogger("brotto.ext_relay")


class ExtensionCDPRelay:
    """Implements the CDPRelay interface; delegates CDP to the browser extension over WebSocket.

    Protocol:
    - Server sends {type: "observe"} → extension replies {type: "observation", url, title, axTargets}
    - Server sends {type: "action", action: {...}} → extension executes, then auto-sends observation
    - We consume the auto-sent observation so the next get_targets() skips the round-trip.
    """

    def __init__(
        self,
        ws_send: Callable[[dict], Awaitable[None]],
        obs_queue: asyncio.Queue,
        eval_queue: asyncio.Queue | None = None,
        session_id: str = "?",
    ) -> None:
        self._ws_send = ws_send
        self._obs_queue = obs_queue
        self._eval_queue: asyncio.Queue = eval_queue or asyncio.Queue()
        self._sid = session_id
        self._cached_obs: dict | None = None

    # ---------- Internal ----------

    async def _get_observation(self) -> dict:
        """Return fresh observation; request one from extension if queue is empty."""
        if self._obs_queue.empty():
            log.debug("[%s] requesting observation", self._sid)
            await self._ws_send({"type": "observe"})
        else:
            log.debug("[%s] using queued observation", self._sid)
        try:
            obs = await asyncio.wait_for(self._obs_queue.get(), timeout=30)
        except asyncio.TimeoutError:
            log.error("[%s] timed out waiting for observation", self._sid)
            raise
        self._cached_obs = obs
        log.debug(
            "[%s] observation received  url=%s  ax=%d",
            self._sid, obs.get("url", "")[:80], len(obs.get("axTargets", [])),
        )
        return obs

    async def _send_action(self, action: dict) -> None:
        """Send action to extension; wait for the auto-sent post-action observation."""
        log.debug("[%s] sending action %s", self._sid, action)
        await self._ws_send({"type": "action", "action": action})
        try:
            obs = await asyncio.wait_for(self._obs_queue.get(), timeout=30)
        except asyncio.TimeoutError:
            log.error("[%s] timed out waiting for post-action observation after %s", self._sid, action)
            raise
        self._cached_obs = obs
        log.debug(
            "[%s] post-action observation  url=%s  ax=%d",
            self._sid, obs.get("url", "")[:80], len(obs.get("axTargets", [])),
        )

    def _coords(self, ref: str) -> dict | None:
        if not self._cached_obs:
            return None
        for t in self._cached_obs.get("axTargets", []):
            if str(t.get("ref")) == str(ref) and "x" in t:
                return {"x": t["x"], "y": t["y"]}
        return None

    # ---------- CDPRelay interface ----------

    async def ping(self) -> bool:
        log.debug("[%s] ping → ok", self._sid)
        return True

    async def get_targets(self) -> list[SemanticTarget]:
        obs = await self._get_observation()
        targets = _to_semantic(obs.get("axTargets", []))
        log.info("[%s] get_targets → %d targets", self._sid, len(targets))
        return targets

    async def _ensure_fresh_obs(self) -> None:
        """Drain any pending observation pushed by the SW (webNavigation
        or tabs.onUpdated) into the cache. Does NOT request a new
        observation — that's _get_observation's job. Keeps get_current_url
        / get_page_title cheap while still reflecting state changes that
        arrived between agent steps."""
        if self._cached_obs is not None and self._obs_queue.empty():
            return
        try:
            self._cached_obs = await asyncio.wait_for(self._obs_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

    async def get_current_url(self) -> str:
        await self._ensure_fresh_obs()
        url = (self._cached_obs or {}).get("url", "")
        log.debug("[%s] get_current_url → %s", self._sid, url)
        return url

    async def get_page_title(self) -> str:
        await self._ensure_fresh_obs()
        title = (self._cached_obs or {}).get("title", "")
        log.debug("[%s] get_page_title → %r", self._sid, title)
        return title

    async def navigate(self, url: str) -> None:
        log.info("[%s] navigate → %s", self._sid, url)
        await self._send_action({"type": "navigate", "url": url})

    async def wait_for_network_idle(self) -> None:
        pass  # extension adds its own delay after navigate

    async def refresh_target_map(self) -> None:
        pass  # next get_targets() will re-observe

    async def click_ref(self, ref: str) -> str:
        coords = self._coords(ref)
        if not coords:
            log.warning("[%s] click_ref %r — no coords (off-screen or missing)", self._sid, ref)
            return f"No coordinates for ref {ref!r} — element may be off-screen"
        log.info("[%s] click_ref %r at (%d,%d)", self._sid, ref, coords["x"], coords["y"])
        await self._send_action({"type": "click", **coords})
        return f"Clicked [{ref}]"

    async def focus_ref(self, ref: str) -> None:
        coords = self._coords(ref)
        if coords:
            log.debug("[%s] focus_ref %r", self._sid, ref)
            await self._ws_send({"type": "action", "action": {"type": "click", **coords}})

    async def clear_ref(self, ref: str) -> None:
        coords = self._coords(ref)
        if coords:
            log.debug("[%s] clear_ref %r — click + select-all", self._sid, ref)
            await self._ws_send({"type": "action", "action": {"type": "click", **coords}})
            await self._ws_send({"type": "action", "action": {"type": "key", "key": "a", "modifiers": 2}})

    async def type_text_to_ref(self, ref: str, text: str) -> str:
        log.info("[%s] type_text_to_ref %r  len=%d", self._sid, ref, len(text))
        await self._send_action({"type": "type", "text": text})
        return f"Typed into [{ref}]"

    async def read_page_text(self, selector: str = "body", max_chars: int = 3000) -> str:
        sel = selector.replace('"', '\\"')
        expr = f'(document.querySelector("{sel}") || document.body).innerText.substring(0, {max_chars})'
        log.info("[%s] read_page_text  selector=%r", self._sid, selector)
        await self._ws_send({"type": "evaluate", "expression": expr})
        try:
            text = await asyncio.wait_for(self._eval_queue.get(), timeout=15)
        except asyncio.TimeoutError:
            log.error("[%s] timed out waiting for evaluate_result", self._sid)
            return "(timeout reading page text)"
        log.debug("[%s] read_page_text → %d chars", self._sid, len(text))
        return text

    async def scroll(self, direction: str, amount_px: int) -> None:
        delta = amount_px if direction == "down" else -amount_px
        log.info("[%s] scroll  direction=%s  delta=%d", self._sid, direction, delta)
        await self._send_action({"type": "scroll", "deltaY": delta})


def _to_semantic(ax_targets: list[dict]) -> list[SemanticTarget]:
    result = []
    for t in ax_targets:
        coords: dict[str, int] = {}
        if "x" in t and "y" in t:
            coords = {"x": t["x"], "y": t["y"]}
        result.append(SemanticTarget(
            ref_id=str(t.get("ref", "")),
            tag=t.get("role", ""),
            role=t.get("role", ""),
            name=t.get("name", ""),
            value=t.get("value"),
            coordinates=coords,
        ))
    return result
