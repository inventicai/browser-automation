"""Minimal brotto contracts — shared Pydantic models for observation and action."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ObservationV1(BaseModel):
    observation_id: str = ""
    sequence: int = 0
    payload: dict[str, Any] = {}
    url: str = ""
    title: str = ""
    semantic_targets: list[dict[str, Any]] = []
    timestamp: Any = None


class BrowserAction(BaseModel):
    type: str
    target_id: str | None = None
    text: str | None = None
    url: str | None = None
    key: str | None = None
    direction: str | None = None
    duration_ms: int | None = None
    answer: str | None = None
    reason: str | None = None


__all__ = ["ObservationV1", "BrowserAction"]
