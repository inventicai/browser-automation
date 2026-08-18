from __future__ import annotations

from abc import ABC, abstractmethod


class ActionExecutor(ABC):
    @abstractmethod
    async def execute(self, action: dict, deps) -> object:
        pass
