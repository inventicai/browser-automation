from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class SessionState:
    user_id: str
    connected: bool = True
    current_task: asyncio.Task | None = None

    def cancel_current_task(self) -> None:
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def get_or_create(self, user_id: str) -> SessionState:
        if user_id not in self._sessions:
            self._sessions[user_id] = SessionState(user_id=user_id)
        return self._sessions[user_id]

    def mark_disconnected(self, user_id: str) -> None:
        if session := self._sessions.get(user_id):
            session.connected = False
            session.cancel_current_task()
