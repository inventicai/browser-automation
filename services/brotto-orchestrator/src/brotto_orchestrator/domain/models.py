from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActionResult:
    ok: bool
    error: str | None = None
    ref_id: str | None = None
    evidence: str = ""


@dataclass
class SessionDeps:
    session_id: str
    sink: Any = None  # WebSocket or callable for sending messages
    history: list[str] = field(default_factory=list)
