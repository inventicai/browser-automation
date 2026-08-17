from __future__ import annotations

import asyncio
from typing import Callable, Coroutine, Any


class CDPWatchdog:
    def __init__(self, relay: Any, on_dead: Callable[[], Coroutine[Any, Any, None]]) -> None:
        self._relay = relay
        self._on_dead = on_dead
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(10)
            if not await self._relay.ping():
                await self._on_dead()
                break

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
