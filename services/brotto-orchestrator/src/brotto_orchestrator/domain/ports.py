from __future__ import annotations

from abc import ABC, abstractmethod

from .models import PlanningInput, PlanningOutcome


class InferencePort(ABC):
    @abstractmethod
    async def plan(self, input: PlanningInput) -> PlanningOutcome:
        pass


class ActionExecutor(ABC):
    @abstractmethod
    async def execute(self, action: dict, deps) -> object:
        pass
